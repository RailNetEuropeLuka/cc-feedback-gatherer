"""Respondent registry: load the Overview spreadsheet into a lookup that
resolves any (company name / email) found in a source file to a known stakeholder.

The registry is authoritative for classification (RU/IM/Association/MTO) and
FTE-alignment. Matching is fuzzy on company name with an exact email fallback,
so spelling variants across files ("SBB Cargo International" vs "SBB Cargo")
still resolve to one respondent.
"""
from __future__ import annotations

import re
import unicodedata

import openpyxl
from rapidfuzz import fuzz, process

from schema import Respondent


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "unknown"


def _norm_company(name: str) -> str:
    name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    name = name.lower()
    # drop common suffixes / noise that hurt matching
    name = re.sub(r"\b(s\.?a\.?|a\.?g\.?|n\.?v\.?|gmbh|ab|in restructuring|international|cargo|nv)\b",
                  " ", name)
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _email_addr(raw: str) -> str | None:
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw or "")
    return m.group(0).lower() if m else None


class Registry:
    def __init__(self):
        self.respondents: dict[str, Respondent] = {}
        self._by_norm_company: dict[str, str] = {}   # normalised name -> respondent_id
        self._by_email: dict[str, str] = {}          # email -> respondent_id

    # ------------------------------------------------------------------ load
    @classmethod
    def from_config(cls, cfg: dict, root) -> "Registry":
        reg = cls()
        rc = cfg["registry"]
        path = root / rc["file"]
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[rc["sheet"]]
        col = rc["columns"]
        for row in ws.iter_rows(min_row=rc["first_data_row"],
                                max_row=rc["last_data_row"], values_only=True):
            company = row[col["company"]]
            if not company or not str(company).strip():
                continue
            company = str(company).strip()
            rid = slugify(company)
            classification = (row[col["classification"]] or "Unknown")
            rep = row[col["representative"]]
            email = _email_addr(str(row[col["email"]] or "")) or None
            alignment = reg._alignment(row, col)
            channels = []
            if reg._truthy(row[col["msform"]]):
                channels.append("msform")
            if reg._truthy(row[col["mailbox"]]):
                channels.append("mailbox")
            date = row[col["date"]]
            r = Respondent(
                respondent_id=rid,
                company=company,
                classification=str(classification).strip(),
                representative=(str(rep).strip() if rep else None),
                email=email,
                channels=channels,
                fte_alignment=alignment,
            )
            reg._add(r)
        # register abbreviation/spelling aliases pointing at canonical respondents
        for alias, canonical in (cfg.get("company_aliases") or {}).items():
            rid = reg._by_norm_company.get(_norm_company(canonical)) or slugify(canonical)
            if rid in reg.respondents:
                reg._by_norm_company[_norm_company(alias)] = rid
        return reg

    @staticmethod
    def _truthy(v) -> bool:
        return str(v).strip().lower() in {"x", "yes", "1", "true"}

    def _alignment(self, row, col) -> str | None:
        if self._truthy(row[col["same_as_fte"]]):
            return "same"
        if self._truthy(row[col["partial_fte"]]):
            return "partial"
        return "independent"

    def _add(self, r: Respondent):
        self.respondents[r.respondent_id] = r
        self._by_norm_company[_norm_company(r.company)] = r.respondent_id
        if r.email:
            self._by_email[r.email] = r.respondent_id

    # --------------------------------------------------------------- resolve
    def resolve(self, company: str | None = None, email_blob: str | None = None,
                min_score: int = 82) -> tuple[Respondent | None, str]:
        """Return (respondent, how) where how in {email, exact, fuzzy, none}."""
        email = _email_addr(email_blob or "")
        if email and email in self._by_email:
            return self.respondents[self._by_email[email]], "email"
        # email domain -> company stem fallback
        norm = _norm_company(company or "")
        if norm and norm in self._by_norm_company:
            return self.respondents[self._by_norm_company[norm]], "exact"
        if norm:
            choices = list(self._by_norm_company.keys())
            hit = process.extractOne(norm, choices, scorer=fuzz.token_set_ratio)
            if hit and hit[1] >= min_score:
                return self.respondents[self._by_norm_company[hit[0]]], "fuzzy"
        return None, "none"

    def get_or_create(self, company: str | None, email_blob: str | None,
                      classification: str = "Unknown") -> tuple[Respondent, str]:
        """Resolve to a known respondent, or mint an ad-hoc one (for web-app uploads
        of companies not in the registry)."""
        r, how = self.resolve(company, email_blob)
        if r:
            return r, how
        name = (company or "Unknown").strip()
        rid = slugify(name)
        if rid in self.respondents:
            return self.respondents[rid], "exact"
        r = Respondent(
            respondent_id=rid, company=name, classification=classification,
            email=_email_addr(email_blob or ""), fte_alignment=None,
        )
        self._add(r)
        return r, "new"
