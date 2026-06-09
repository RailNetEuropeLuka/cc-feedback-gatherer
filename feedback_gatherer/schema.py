"""Unified data model for gathered feedback.

Two record types:
  - FeedbackItem: one atomic comment by one respondent on one guideline section.
  - Respondent:   one stakeholder who submitted feedback (any number of items / channels).

These dataclasses are the single source of truth for the shape of feedback.json and
the columns of feedback.xlsx. Keep them in sync with writers.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# --- confidence levels for an extraction -----------------------------------
CONF_HIGH = "high"      # structured source, section explicitly labelled (form xlsx, doc tables)
CONF_MEDIUM = "medium"  # section inferred from a numbered header in prose
CONF_LOW = "low"        # could not map to a section / fell back to "general"


@dataclass
class FeedbackItem:
    """One respondent's comment on one section of the Guidelines."""

    item_id: str                         # stable id, e.g. "fte__2.3__001"
    respondent_id: str                   # FK into the respondent registry
    company: str                         # denormalised for easy reading/filtering
    classification: str                  # RU | IM | Association | MTO | Unknown

    section_ref: str                     # canonical key, e.g. "2.3" or "general"
    section_title: str                   # human title for section_ref
    section_raw: str = ""                # the label/number exactly as found in the source

    considerations: str = ""             # the comment / concern / remark
    proposal: Optional[str] = None       # proposed change, when the source separates it
    raw_text: str = ""                   # verbatim source excerpt (for audit)

    # provenance
    channel: str = "unknown"             # msform | mailbox | other
    source_file: str = ""                # basename of the file it came from
    source_format: str = ""              # xlsx | docx | pdf | msg
    date: Optional[str] = None           # ISO date if known

    # relationships / flags
    fte_alignment: Optional[str] = None  # self | same | partial | independent | None
    endorses: Optional[str] = None       # respondent_id this item endorses (e.g. "fte")
    extraction_confidence: str = CONF_HIGH
    needs_review: bool = False
    review_note: str = ""

    representative: Optional[str] = None
    email: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Respondent:
    """A stakeholder who submitted feedback."""

    respondent_id: str
    company: str
    classification: str = "Unknown"
    representative: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None

    channels: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    fte_alignment: Optional[str] = None  # self | same | partial | independent
    n_items: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# --- JSON envelope ----------------------------------------------------------
def build_envelope(items: list[FeedbackItem], respondents: list[Respondent],
                   meta: dict | None = None) -> dict:
    """Assemble the canonical feedback.json structure."""
    return {
        "meta": meta or {},
        "respondents": [r.to_dict() for r in respondents],
        "items": [i.to_dict() for i in items],
    }
