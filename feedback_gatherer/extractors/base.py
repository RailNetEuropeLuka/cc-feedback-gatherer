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


# outline-style chapter headings: "3) Incentives for Applicants (Section 2.2)"
_OUTLINE_RE = re.compile(r"^\s*\d{1,2}[).]\s+(\S.{3,90}?)\s*$", re.MULTILINE)


def outline_items(text: str, sections_cfg: list[dict]) -> list[RawItem]:
    """Split prose on the author's numbered outline ("1) ... 2) ...") when the
    headings name guideline chapters - either by explicit citation ("(Section
    2.2)") or by chapter title ("Incentives for Applicants").

    Each block inherits its heading as section context; ➢-topics inside a block
    are split further and keep "heading > topic" so the engine can resolve the
    chapter from the heading part. Returns [] unless >= 2 headings anchor to a
    guideline section (random numbered lists never trigger this).
    """
    from taxonomy import Taxonomy
    tax = Taxonomy(sections_cfg)

    anchors = []          # (match, title, cited_explicitly)
    for m in _OUTLINE_RE.finditer(text):
        title = m.group(1).strip()
        cited = tax.from_number(title) is not None
        if cited or tax.from_label(title) is not None:
            anchors.append((m, title, cited))
    if len(anchors) < 2:
        return []

    items: list[RawItem] = []
    intro = text[:anchors[0][0].start()].strip()
    if len(intro) > 200:
        # the part before the outline often carries its own ➢-topics
        items.extend(topic_items(intro, min_topics=1)
                     or [RawItem(section_raw="general", considerations=intro,
                                 raw_text=intro, confidence="medium")])

    for i, (m, title, cited) in enumerate(anchors):
        end = anchors[i + 1][0].start() if i + 1 < len(anchors) else len(text)
        block = text[m.end():end].strip()
        conf = "high" if cited else "medium"
        subs = topic_items(block, min_topics=1)
        if subs:
            for s in subs:
                s.section_raw = title if s.section_raw == "general" \
                    else f"{title} > {s.section_raw}"
                s.confidence = conf
                items.append(s)
        elif block:
            items.append(RawItem(section_raw=title, considerations=block,
                                 raw_text=f"{title}\n{block}", confidence=conf))
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
