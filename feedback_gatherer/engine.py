"""Shared extraction engine used by BOTH front-ends (CLI and Streamlit app).

  extract_file(data, filename, ...) -> (items, parsed_sources)
        Format-dispatch one file's bytes, resolve respondent + canonical section
        for every comment, and recurse into e-mail attachments. Pure in-memory.

  gather_folder() -> GatherResult
        Walk the configured channel folders, dedup, and aggregate items + a
        respondent roster + a run report.

The engine never writes files; serialisation lives in writers.py.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from schema import FeedbackItem, Respondent, CONF_LOW
from taxonomy import Taxonomy
from respondents import Registry, slugify
from extractors import base
from extractors import xlsx_form, docx_ext, pdf_ext, msg_ext

EXT_DISPATCH = {
    ".xlsx": xlsx_form.extract,
    ".docx": docx_ext.extract,
    ".pdf": pdf_ext.extract,
    ".msg": msg_ext.extract,
}


def load_config(config_path: str | Path | None = None) -> dict:
    here = Path(__file__).resolve().parent
    path = Path(config_path) if config_path else here / "config.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class GatherResult:
    items: list[FeedbackItem] = field(default_factory=list)
    respondents: list[Respondent] = field(default_factory=list)
    report: dict = field(default_factory=dict)


class Engine:
    def __init__(self, cfg: dict, repo_root: Path, registry: Registry | None = None):
        self.cfg = cfg
        self.root = repo_root
        self.tax = Taxonomy(cfg["sections"])
        self.registry = registry if registry is not None else Registry()
        self._item_seq = 0          # engine-wide counter -> globally unique item_ids
        self._placeholders = {str(p).strip().lower()
                              for p in cfg.get("placeholder_answers", [])}

    def _is_placeholder(self, text: str | None) -> bool:
        t = (text or "").strip().lower().rstrip(".!")
        return (not t) or t in self._placeholders

    @classmethod
    def create(cls, config_path=None, repo_root: Path | None = None,
               with_registry: bool = True) -> "Engine":
        cfg = load_config(config_path)
        root = repo_root or Path(__file__).resolve().parent.parent
        registry = Registry.from_config(cfg, root) if with_registry else Registry()
        return cls(cfg, root, registry)

    # ------------------------------------------------------------- one file
    def extract_file(self, data: bytes, filename: str, channel: str = "unknown",
                     date_hint: str | None = None, company_hint: str | None = None,
                     _depth: int = 0
                     ) -> tuple[list[FeedbackItem], list[base.ParsedSource]]:
        ext = os.path.splitext(filename)[1].lower()
        fn = EXT_DISPATCH.get(ext)
        if fn is None:
            return [], []
        try:
            sources = fn(data, filename, self.cfg)
        except Exception as exc:  # never let one bad file abort a folder run
            ps = base.ParsedSource(source_format=ext.lstrip("."),
                                   notes=[f"ERROR extracting: {exc!r}"])
            return [], [ps]

        items: list[FeedbackItem] = []
        for ps in sources:
            items.extend(self._normalize(ps, filename, channel, date_hint, company_hint))
            # recurse into attachments (cover-mail documents) - attribute to the
            # same respondent as the carrying e-mail via company_hint.
            if _depth < 2:
                mail_company = ps.company_hint or company_hint or _company_from_filename(filename)
                for att_name, att_bytes in ps.attachments:
                    sub_items, _ = self.extract_file(
                        att_bytes, att_name, channel, date_hint=ps.date_hint,
                        company_hint=mail_company, _depth=_depth + 1)
                    items.extend(sub_items)
        return items, sources

    # --------------------------------------------------- ParsedSource -> items
    def _normalize(self, ps: base.ParsedSource, filename: str, channel: str,
                   date_hint: str | None, company_hint: str | None = None
                   ) -> list[FeedbackItem]:
        # Resolution priority. Email always wins inside resolve(). For most files
        # the filename reliably carries the org; for the MS Form export the per-row
        # Company column is authoritative, so it must beat the (useless) filename.
        fname_hint = _company_from_filename(filename)
        if ps.company_authoritative:
            candidates = [company_hint, ps.company_hint, fname_hint]
        else:
            candidates = [company_hint, fname_hint, ps.company_hint]
        respondent, how = None, "none"
        for cand in candidates:
            if not cand:
                continue
            r, h = self.registry.resolve(company=cand, email_blob=ps.email_hint)
            if r:
                respondent, how = r, h
                break
        if respondent is None:
            mint_name = next((c for c in candidates if c), None)
            respondent, how = self.registry.get_or_create(
                company=mint_name, email_blob=ps.email_hint)

        date = ps.date_hint or date_hint
        align = respondent.fte_alignment
        if respondent.respondent_id == self.cfg.get("fte_respondent_id"):
            align = "self"

        # track provenance on the respondent
        if channel not in respondent.channels:
            respondent.channels.append(channel)
        base_name = os.path.basename(filename)
        if base_name not in respondent.source_files:
            respondent.source_files.append(base_name)

        out: list[FeedbackItem] = []

        # endorsement ("same as FTE") -> a single linking item, no content
        if ps.is_endorsement:
            key = "general"
            out.append(self._mk_item(respondent, key, self.tax.title(key), "same as FTE",
                                     "Endorses the FTE response in full.", None,
                                     ps.full_text[:1000], channel, base_name, ps.source_format,
                                     date, align, endorses=self.cfg.get("fte_respondent_id"),
                                     conf="high"))
            return out

        skipped_placeholders = 0
        for raw in ps.items:
            # placeholder answers ("-", "vacat", "no comments yet", ...) carry no
            # content - skip them so counts reflect substance, not form-filling
            if self._is_placeholder(raw.considerations) and self._is_placeholder(raw.proposal):
                skipped_placeholders += 1
                continue
            key, title, _ = self.tax.resolve(raw.section_raw)
            conf = raw.confidence
            needs_review = (how == "new") or (conf == CONF_LOW)
            note = ""
            if how == "new":
                note = "Respondent not found in registry."
            elif conf == CONF_LOW:
                note = "Low-confidence extraction; verify section/content."
            out.append(self._mk_item(
                respondent, key, title, raw.section_raw,
                raw.considerations, raw.proposal, raw.raw_text,
                channel, base_name, ps.source_format, date, align,
                conf=conf, needs_review=needs_review, review_note=note))
        if skipped_placeholders:
            ps.notes.append(f"Skipped {skipped_placeholders} placeholder answer(s) "
                            f"(e.g. '-', 'vacat', 'no comments yet').")
        return out

    def _mk_item(self, r: Respondent, key, title, section_raw, considerations, proposal,
                 raw_text, channel, source_file, source_format, date, align,
                 endorses=None, conf="high", needs_review=False, review_note=""
                 ) -> FeedbackItem:
        self._item_seq += 1
        item_id = f"{r.respondent_id}__{key}__{self._item_seq:04d}"
        return FeedbackItem(
            item_id=item_id, respondent_id=r.respondent_id, company=r.company,
            classification=r.classification,
            section_ref=key, section_title=title, section_raw=str(section_raw or ""),
            considerations=(considerations or "").strip(),
            proposal=(proposal.strip() if proposal else None),
            raw_text=(raw_text or "").strip(),
            channel=channel, source_file=source_file, source_format=source_format, date=date,
            fte_alignment=align, endorses=endorses,
            extraction_confidence=conf, needs_review=needs_review, review_note=review_note,
            representative=r.representative, email=r.email,
        )

    # ------------------------------------------------------------ whole folder
    def gather_folder(self) -> GatherResult:
        result = GatherResult()
        report = {"files_ingested": [], "files_skipped": [], "test_rows_skipped": [],
                  "endorsements": [], "placeholders_skipped": 0, "errors": [],
                  "by_format": {}}
        seen_hashes: dict[str, str] = {}   # sha1 of content -> first filename

        for ch in self.cfg["channels"]:
            if not ch.get("ingest", False):
                report["files_skipped"].append(f"[channel off] {ch['path']}")
                continue
            chan_dir = self.root / self.cfg["data_root"] / ch["path"]
            if not chan_dir.exists():
                report["errors"].append(f"missing channel dir: {chan_dir}")
                continue
            files = self._list_files(chan_dir, recurse=ch.get("recurse", False))
            for fpath in files:
                if self._ignored(fpath.name):
                    report["files_skipped"].append(f"[ignored] {fpath.name}")
                    continue
                data = fpath.read_bytes()
                # dedup by CONTENT, not filename: identical bytes are a mirror copy;
                # distinct files that merely share a name are both ingested
                digest = hashlib.sha1(data).hexdigest()
                if digest in seen_hashes:
                    report["files_skipped"].append(
                        f"[same content as {seen_hashes[digest]}] {fpath.name}")
                    continue
                seen_hashes[digest] = fpath.name
                forced = self._attribution_for(fpath)
                items, sources = self.extract_file(data, fpath.name, ch["channel"],
                                                   company_hint=forced)
                fmt = os.path.splitext(fpath.name)[1].lstrip(".")
                report["by_format"][fmt] = report["by_format"].get(fmt, 0) + 1
                self._tally_sources(report, fpath.name, sources)
                result.items.extend(items)
                report["files_ingested"].append(f"{fpath.name} ({len(items)} items)")

        # also ingest the dedicated MS Form export
        self._ingest_msform_export(result, report)

        # finalise respondent roster (only those who actually produced items)
        counts: dict[str, int] = {}
        for it in result.items:
            counts[it.respondent_id] = counts.get(it.respondent_id, 0) + 1
        for rid, r in self.registry.respondents.items():
            r.n_items = counts.get(rid, 0)
        result.respondents = [r for r in self.registry.respondents.values() if r.n_items > 0]
        result.respondents.sort(key=lambda r: (-r.n_items, r.company.lower()))

        report["totals"] = {
            "items": len(result.items),
            "respondents_with_feedback": len(result.respondents),
            "respondents_in_registry": len(self.registry.respondents),
        }
        result.report = report
        return result

    def _attribution_for(self, fpath: Path) -> str | None:
        """Forced respondent company for files matching an attribution path rule."""
        rel = str(fpath).replace("\\", "/")
        for rule in self.cfg.get("attribution", []):
            if rule.get("path_contains", "").lower() in rel.lower():
                return rule.get("company")
        return None

    def _tally_sources(self, report: dict, filename: str,
                       sources: list[base.ParsedSource]):
        """Aggregate per-source notes (tests, endorsements, placeholders, errors)
        into the run report."""
        for ps in sources:
            if "__TEST__" in ps.notes:
                report["test_rows_skipped"].append(f"{filename}: {ps.company_hint}")
            if ps.is_endorsement:
                report["endorsements"].append(filename)
            for n in ps.notes:
                if n.startswith("ERROR"):
                    report["errors"].append(f"{filename}: {n}")
                m = re.match(r"Skipped (\d+) placeholder", n)
                if m:
                    report["placeholders_skipped"] += int(m.group(1))

    def _ingest_msform_export(self, result: GatherResult, report: dict):
        mf = self.cfg.get("msform_export", {})
        fpath = self._resolve_data_file(mf.get("file"), mf.get("file_glob"))
        if not mf or fpath is None:
            report["errors"].append("MS Form export not found; skipped.")
            return
        items, sources = self.extract_file(fpath.read_bytes(), fpath.name, "msform")
        report["by_format"]["xlsx"] = report["by_format"].get("xlsx", 0) + 1
        self._tally_sources(report, fpath.name, sources)
        result.items.extend(items)
        report["files_ingested"].append(f"{fpath.name} ({len(items)} items, MS Form export)")

    def _resolve_data_file(self, rel: str | None, glob_pat: str | None) -> Path | None:
        """Resolve a data file by exact relative path, else by glob under data_root.
        (Some source filenames contain non-breaking spaces, so glob is the fallback.)"""
        if rel:
            p = self.root / rel
            if p.exists():
                return p
        if glob_pat:
            base = self.root / self.cfg["data_root"]
            hits = sorted(base.rglob(glob_pat))
            if hits:
                return hits[0]
        return None

    # --------------------------------------------------------------- helpers
    def _list_files(self, d: Path, recurse: bool) -> list[Path]:
        if recurse:
            return sorted(p for p in d.rglob("*") if p.is_file())
        return sorted(p for p in d.iterdir() if p.is_file())

    def _ignored(self, name: str) -> bool:
        import fnmatch
        for pat in self.cfg.get("ignore_globs", []):
            if fnmatch.fnmatch(name.lower(), pat.lower()):
                return True
        return os.path.splitext(name)[1].lower() not in EXT_DISPATCH


# noise that follows the organisation name in feedback filenames; the company is
# whatever precedes the EARLIEST of these markers
_FNAME_NOISE = ("public consultation", "same as", " remarks", " inputs", " feedback",
                " reply", " response", " complementary", "_")


def _company_from_filename(filename: str) -> str | None:
    """Derive the organisation from a feedback filename.

    '0.3a_ProRail Public Consultation - Commercial Conditions .msg' -> 'ProRail'
    '3_DB Cargo Germany_Christine Roemermann_Public Consultation....msg' -> 'DB Cargo Germany'
    '2_2025_08_14_GUETERBAHNEN_RNE-Consultation....pdf' -> 'GUETERBAHNEN'
    """
    stem = os.path.splitext(os.path.basename(filename))[0]
    # strip leading numeric index group(s): "14_", "0.3a_", "2_2025_08_14_", "998 "
    stem = re.sub(r"^(?:[0-9][0-9.\-]*[a-z]?[\s_]+)+", "", stem, flags=re.IGNORECASE)
    low = stem.lower()
    cut = min((i for i in (low.find(m) for m in _FNAME_NOISE) if i > 0), default=len(stem))
    stem = stem[:cut].strip(" -_")
    stem = re.sub(r"'s$", "", stem)        # "RLE's" -> "RLE"
    return stem.strip() or None
