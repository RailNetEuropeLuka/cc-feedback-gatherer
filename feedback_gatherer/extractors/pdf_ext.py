"""Extract .pdf feedback (FTE master response, RLE, GÜTERBAHNEN, ALLRAIL, ...).

These are prose documents organised by the guideline's section numbers, so we pull
the text with PyMuPDF and split it on numbered section headers. If no headers are
found, the whole document becomes one "general" item.
"""
from __future__ import annotations

import re

import fitz  # PyMuPDF

from .base import ParsedSource, RawItem

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def extract(data: bytes, filename: str, cfg: dict) -> list[ParsedSource]:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = [doc[i].get_text() for i in range(doc.page_count)]
    full_text = "\n".join(pages)
    doc.close()

    ps = ParsedSource(source_format="pdf", full_text=full_text)
    m = EMAIL_RE.search(full_text)
    if m:
        ps.email_hint = m.group(0)
    # first non-empty line is usually the title / org
    for line in full_text.splitlines():
        if line.strip():
            ps.company_hint = line.strip()[:120]
            break

    from taxonomy import Taxonomy
    matches = list(Taxonomy.HEADER_RE.finditer(full_text))
    if matches:
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
    if not ps.items:
        ps.notes.append("No numbered sections found; stored as one general item.")
        ps.items.append(RawItem(section_raw="general", considerations=full_text.strip(),
                                raw_text=full_text.strip(), confidence="low"))
    return [ps]
