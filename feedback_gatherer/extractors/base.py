"""Shared types for extractors.

Every extractor takes the raw bytes of one file plus its filename and returns a
ParsedSource: the respondent identity hints found in the file, the full extracted
text (for the raw-vs-parsed view), and a list of RawItem comments. The engine then
resolves respondents and canonical sections - extractors stay format-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawItem:
    section_raw: str = ""               # label/number as found ("2.3", "Incentives for IMs")
    considerations: str = ""            # the comment text
    proposal: Optional[str] = None      # proposed change, if the source separates it
    raw_text: str = ""                  # verbatim excerpt this item came from
    confidence: str = "high"            # high (structured) | medium (numbered prose) | low (fallback)


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
