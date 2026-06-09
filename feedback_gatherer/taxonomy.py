"""Guideline section taxonomy: map raw labels/numbers to canonical section refs.

All extractors funnel their section guesses through here so the unified output
uses one consistent set of section_ref values.
"""
from __future__ import annotations

import re


def _norm(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace - for alias matching."""
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class Taxonomy:
    def __init__(self, sections_cfg: list[dict]):
        self.sections = sections_cfg
        self.title_by_key = {s["key"]: s["title"] for s in sections_cfg}
        # alias (normalised) -> key, longest aliases first so specific wins
        self._alias_to_key: list[tuple[str, str]] = []
        for s in sections_cfg:
            for a in s.get("aliases", []):
                self._alias_to_key.append((_norm(a), s["key"]))
        self._alias_to_key.sort(key=lambda t: len(t[0]), reverse=True)

    # -- numbered references, e.g. "1.4.3", "2.1", "Section 2.3" -------------
    def from_number(self, raw: str) -> tuple[str, str, str] | None:
        """Return (canonical_key, title, raw_match) for a numbered header, else None."""
        m = re.search(r"\b([1-3])\.(\d)(?:\.\d+)?\b", raw or "")
        if not m:
            return None
        top = f"{m.group(1)}.{m.group(2)}"
        if top in self.title_by_key:
            return top, self.title_by_key[top], m.group(0)
        return None

    # -- text labels, e.g. "Incentives for IMs" ------------------------------
    def from_label(self, text: str) -> tuple[str, str] | None:
        """Return (canonical_key, title) if a section alias is contained in text."""
        norm = _norm(text)
        if not norm:
            return None
        for alias, key in self._alias_to_key:
            if alias and alias in norm:
                return key, self.title_by_key[key]
        return None

    def resolve(self, raw: str) -> tuple[str, str, str]:
        """Best-effort resolve any label to (key, title, raw). Falls back to 'general'."""
        by_num = self.from_number(raw)
        if by_num:
            return by_num
        by_lbl = self.from_label(raw)
        if by_lbl:
            return by_lbl[0], by_lbl[1], raw.strip()
        return "general", self.title_by_key.get("general", "General"), (raw or "").strip()

    def title(self, key: str) -> str:
        return self.title_by_key.get(key, key)

    # regex that matches a line beginning a numbered guideline section
    HEADER_RE = re.compile(r"^\s*([1-3]\.\d(?:\.\d+)?)\s+([A-Z][^\n]{2,80})", re.MULTILINE)
