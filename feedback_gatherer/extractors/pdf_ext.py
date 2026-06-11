"""Extract .pdf feedback in two layers:

  1. Body text   - prose responses (FTE, RLE, ...) split on numbered section headers.
  2. Annotations - comment bubbles / highlights / strikeouts added on top of a PDF.
                   pdftotext-style extraction never sees these, yet for reviewed
                   copies of the Guidelines they ARE the feedback.

If the file is an RNE-published copy of the Guidelines itself (detected via
letterhead markers from config), its body text is the *guideline* text - not
feedback - so body-derived items are suppressed and only annotations are kept.
"""
from __future__ import annotations

import re

import fitz  # PyMuPDF

from .base import ParsedSource, RawItem, topic_items

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_HDR_LINE = re.compile(r"^\s*([1-3]\.\d(?:\.\d+)?)\s")


def _is_guidelines_copy(full_text: str, cfg: dict) -> bool:
    head = full_text[:4000].lower()
    return any(m.lower() in head for m in cfg.get("guidelines_doc_markers", []))


def _nearest_section(page, y: float) -> str:
    """Last numbered section header that appears above height y on this page."""
    best = ""
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            if line["bbox"][1] > y:
                continue
            text = "".join(s.get("text", "") for s in line.get("spans", []))
            if _HDR_LINE.match(text):
                best = text.strip()
    return best


def _annotation_items(doc) -> list[RawItem]:
    items = []
    for page in doc:
        for annot in page.annots() or []:
            content = (annot.info.get("content") or "").strip()
            # the passage the annotation sits on, as context
            try:
                anchor = page.get_textbox(annot.rect).strip()
            except Exception:
                anchor = ""
            kind = annot.type[1] if annot.type else "Annot"
            if not content and not anchor:
                continue
            if not content:
                # a bare highlight/strikeout with no note still signals "look here"
                content = f"[{kind} without text on:] {anchor[:300]}"
            section = _nearest_section(page, annot.rect.y0)
            items.append(RawItem(
                section_raw=section or "general",
                considerations=content,
                raw_text=(f"{kind} on p.{page.number + 1}"
                          + (f' over: "{anchor[:300]}"' if anchor else "")
                          + f" -> {content}"),
                confidence="medium" if section else "low"))
    return items


def extract(data: bytes, filename: str, cfg: dict) -> list[ParsedSource]:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = [doc[i].get_text() for i in range(doc.page_count)]
    full_text = "\n".join(pages)

    ps = ParsedSource(source_format="pdf", full_text=full_text)
    m = EMAIL_RE.search(full_text)
    if m:
        ps.email_hint = m.group(0)
    for line in full_text.splitlines():
        if line.strip():
            ps.company_hint = line.strip()[:120]
            break

    # layer 2: annotations
    annot_items = _annotation_items(doc)
    doc.close()

    guidelines_copy = _is_guidelines_copy(full_text, cfg)
    if guidelines_copy:
        # body text IS the guideline text - not feedback
        ps.company_hint = None      # first line would be the RNE title page
        ps.notes.append("Marked-up copy of the Guidelines: body text suppressed, "
                        f"{len(annot_items)} annotation(s) extracted as feedback.")
        ps.items = annot_items
        if not annot_items:
            ps.notes.append("No annotations found in the Guidelines copy.")
        return [ps]

    # layer 1: body prose split by numbered section headers
    from taxonomy import Taxonomy
    matches = list(Taxonomy.HEADER_RE.finditer(full_text))
    for i, mt in enumerate(matches):
        start = mt.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        body = full_text[start:end].strip()
        if body:
            ps.items.append(RawItem(
                section_raw=mt.group(1),
                considerations=body,
                raw_text=mt.group(0) + "\n" + body,
                confidence="medium"))

    # no guideline numbering: try the author's own topic headings ("➢ ...")
    if not ps.items:
        topics = topic_items(full_text)
        if topics:
            ps.notes.append(f"No numbered sections; split on {len(topics)} "
                            "topic heading(s) instead (canonical section unknown).")
            ps.items.extend(topics)

    if annot_items:
        ps.notes.append(f"{len(annot_items)} annotation(s) extracted in addition to body text.")
        ps.items.extend(annot_items)

    if not ps.items:
        ps.notes.append("No numbered sections found; stored as one general item.")
        ps.items.append(RawItem(section_raw="general", considerations=full_text.strip(),
                                raw_text=full_text.strip(), confidence="low"))
    return [ps]
