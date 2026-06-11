"""Shared types for extractors.

Every extractor takes the raw bytes of one file plus its filename and returns a
ParsedSource: the respondent identity hints found in the file, the full extracted
text (for the raw-vs-parsed view), and a list of RawItem comments. The engine then
resolves respondents and canonical sections - extractors stay format-only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawItem:
    section_raw: str = ""               # label/number as found ("2.3", "Incentives for IMs")
    considerations: str = ""            # the comment text
    proposal: Optional[str] = None      # proposed change, if the source separates it
    raw_text: str = ""                  # verbatim excerpt this item came from
    confidence: str = "high"            # high (structured) | medium (numbered prose) | low (fallback)


# lines that open a thematic block in free-style prose (no guideline numbering),
# e.g. ALLRAIL's "➢ TCRs and Commercial Conditions: ..."
_TOPIC_RE = re.compile(r"^\s*[➢►▶▪‣◦•→]\s*(\S.*)$", re.MULTILINE)


def topic_items(text: str, min_topics: int = 2) -> list[RawItem]:
    """Split free-style prose on visible topic-heading bullets.

    Fallback for documents organised by the author's own themes instead of the
    guideline chapter numbers. The topic heading is kept in section_raw (the
    canonical section stays unresolved -> 'general'), and each theme becomes its
    own item instead of one document-sized blob. Returns [] if fewer than
    min_topics headings are found.
    """
    marks = list(_TOPIC_RE.finditer(text))
    if len(marks) < min_topics:
        return []
    items: list[RawItem] = []

    # any substantial introduction before the first heading is feedback too
    intro = text[:marks[0].start()].strip()
    if len(intro) > 200:
        items.append(RawItem(section_raw="general",
                             considerations=intro,
                             raw_text=intro,
                             confidence="medium"))

    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.start():end].strip()
        line = m.group(1).strip()
        # "Heading: first sentence..." -> heading is the part before the colon
        heading = line.split(":", 1)[0].strip() if ":" in line[:120] else line[:120].strip()
        body = _TOPIC_RE.sub(r"\1", block, count=1).strip()
        items.append(RawItem(section_raw=heading[:90],
                             considerations=body,
                             raw_text=block,
                             confidence="medium"))
    return items


@dataclass
class ParsedSource:
    source_format: str = ""             # xlsx | docx | pdf | msg
    company_hint: Optional[str] = None  # respondent identity guessed from the file
    company_authoritative: bool = False  # True => company_hint is reliable (form column),
                                         # so trust it over the filename
    email_hint: Optional[str] = None
    date_hint: Optional[str] = None     # ISO date if found
    full_text: str = ""                 # everything extracted, for the raw view
    items: list[RawItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # human hints (e.g. "looks like a cover e-mail")
    attachments: list[tuple[str, bytes]] = field(default_factory=list)  # (filename, bytes)
    is_endorsement: bool = False        # "same as FTE" style: endorses another respondent
