"""Extract .docx feedback in three shapes:
  1. Table responses  - a table like  Paragraph | Considerations | Proposals  (Trenitalia).
  2. "same as FTE"     - identical template endorsing the FTE response; flagged, not re-parsed.
  3. Prose             - section-numbered paragraphs, split on numbered headers.
"""
from __future__ import annotations

import io
import re

import docx

from .base import ParsedSource, RawItem

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

# header cell keywords that mark the three logical columns of a feedback table
_PARA_KEYS = ("paragraph", "section", "chapter", "article", "ref")
_CONS_KEYS = ("consideration", "comment", "remark", "input", "feedback", "observation")
_PROP_KEYS = ("proposal", "suggestion", "amendment", "change", "wording")


def _email(text: str) -> str | None:
    m = EMAIL_RE.search(text or "")
    return m.group(0) if m else None


def _classify_table(header_cells: list[str]) -> dict | None:
    """If the header row looks like a feedback table, return a column->role map."""
    roles = {}
    for i, h in enumerate(header_cells):
        h = (h or "").lower()
        if any(k in h for k in _PARA_KEYS):
            roles.setdefault("section", i)
        elif any(k in h for k in _CONS_KEYS):
            roles.setdefault("considerations", i)
        elif any(k in h for k in _PROP_KEYS):
            roles.setdefault("proposal", i)
    return roles if "considerations" in roles else None


def extract(data: bytes, filename: str, cfg: dict) -> list[ParsedSource]:
    doc = docx.Document(io.BytesIO(data))
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(paras)

    ps = ParsedSource(source_format="docx")
    ps.email_hint = _email(full_text)
    # company / representative hint: first 1-3 short lines before the body
    if paras:
        ps.company_hint = paras[0][:120]
        for p in paras[:4]:
            if " - " in p or "–" in p:
                ps.company_hint = p[:120]
                break

    # ---- (2) "same as FTE" endorsement -----------------------------------
    markers = [m.lower() for m in cfg.get("same_as_fte_filename_markers", ["same as fte"])]
    if any(m in filename.lower() for m in markers):
        ps.is_endorsement = True
        ps.notes.append("Endorses the FTE response (\"same as FTE\").")
        ps.full_text = full_text
        return [ps]

    # ---- (1) feedback table ----------------------------------------------
    parsed_any = False
    parts = []
    for t in doc.tables:
        if not t.rows:
            continue
        header = [c.text.strip() for c in t.rows[0].cells]
        roles = _classify_table(header)
        if not roles:
            continue
        sc, cc, pc = roles.get("section"), roles["considerations"], roles.get("proposal")
        last_section = "general remarks"
        for r in t.rows[1:]:
            cells = [c.text.strip() for c in r.cells]
            cons = cells[cc] if cc < len(cells) else ""
            if not cons:
                continue
            section = cells[sc] if (sc is not None and sc < len(cells) and cells[sc]) else last_section
            last_section = section
            prop = cells[pc] if (pc is not None and pc < len(cells)) else None
            ps.items.append(RawItem(section_raw=section, considerations=cons,
                                    proposal=(prop or None),
                                    raw_text=" | ".join(c for c in cells if c)))
            parts.append(f"### {section}\n{cons}" + (f"\nProposal: {prop}" if prop else ""))
            parsed_any = True

    # ---- (3) prose fallback ----------------------------------------------
    if not parsed_any:
        _split_prose(full_text, ps)

    ps.full_text = "\n\n".join(parts) if parts else full_text
    if not ps.items:
        ps.notes.append("No structured feedback detected; stored as one general item.")
        ps.items.append(RawItem(section_raw="general", considerations=full_text,
                                raw_text=full_text, confidence="low"))
    return [ps]


def _split_prose(text: str, ps: ParsedSource):
    """Split section-numbered prose into items keyed by the numbered headers."""
    from taxonomy import Taxonomy  # local import to avoid cycle at module load
    matches = list(Taxonomy.HEADER_RE.finditer(text))
    if not matches:
        return
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            ps.items.append(RawItem(section_raw=f"{m.group(1)} {m.group(2)}".strip(),
                                    considerations=body, raw_text=m.group(0) + "\n" + body,
                                    confidence="medium"))
