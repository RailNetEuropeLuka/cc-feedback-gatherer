# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A tool ("Feedback Gatherer", in `feedback_gatherer/`) that extracts stakeholder feedback from heterogeneous file formats (`.msg`, `.docx`, `.pdf`, `.xlsx`) into one unified structure, built for the RNE 2025 Commercial Conditions Guidelines consultation. The repo also contains the source data archive `2025 CCs Guidelines review/` — **which is gitignored and must never be committed or pushed** (it holds real stakeholder names, e-mails, and confidential feedback). The public GitHub remote (`RailNetEuropeLuka/cc-feedback-gatherer`) and the Streamlit Cloud deployment contain only the tool plus synthetic samples in `feedback_gatherer/samples/`.

This is stage 1 of a multi-stage project; stage 2 (semantic synthesis of the gathered feedback) is not yet built.

## Commands

```bash
pip install -r feedback_gatherer/requirements.txt   # deps (root requirements.txt mirrors it for Streamlit Cloud)

# Batch CLI: gather the whole consultation archive -> output/feedback.{json,xlsx} + gather_report.md
python feedback_gatherer/gather.py                  # options: --config <yaml> --out <dir>

# Web app (drag-and-drop extraction demo)
streamlit run feedback_gatherer/app.py
```

There is no test suite or linter. Verification is done by running the CLI and checking `feedback_gatherer/output/gather_report.md` (totals, needs-review list, dedup actions) against expectations — last known-good run: ~239 items / 29 respondents (placeholder answers like "vacat"/"-"/"no comments yet" are skipped and counted in the report).

On Windows, prefix Python runs with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` (bash) — the data contains non-ASCII company names that crash cp1252 console output.

## Architecture

One shared extraction engine with two thin front-ends — never duplicate logic between them:

- `engine.py` — the core. `extract_file(bytes, filename, ...)` dispatches by extension to an extractor, then normalizes; `gather_folder()` walks the configured archive with dedup rules. Recurses into e-mail attachments (cover `.msg` → attached PDF/DOCX), passing the carrier's company hint down. Never writes files.
- `gather.py` (CLI) and `app.py` (Streamlit) both call the engine. The app processes uploads **in memory only** — nothing may be written to disk in the app path. It auto-detects "demo mode" (runs registry-free) when the data archive is absent, which is how the public deployment stays free of personal data.
- `extractors/` — one module per format. Each returns `list[ParsedSource]` (a file can hold many respondents, e.g. the MS Form export has one per row) containing raw `RawItem`s with per-item `confidence`. Extractors are format-only: they emit hints (`company_hint`, `email_hint`, `company_authoritative`) and never resolve respondents or canonical sections themselves. Review markup is feedback too: `pdf_ext` extracts PDF annotations, `docx_ext` extracts Word comments and tracked changes; when a file is an RNE-published copy of the Guidelines (detected via `guidelines_doc_markers` letterhead strings), its body text is suppressed and *only* markup is extracted.
- `respondents.py` — registry loaded from the Overview xlsx; fuzzy company matching (rapidfuzz) with exact-email priority. Unknown respondents are minted and flagged `needs_review` rather than dropped.
- `taxonomy.py` — maps raw section labels/numbers to canonical refs (`1.1`…`3.2`, `general`). All section resolution funnels through here.
- `schema.py` — `FeedbackItem` / `Respondent` dataclasses; single source of truth for output shape. Keep `writers.py` (JSON + Excel serialization, used by both front-ends) in sync with it.
- `config.yaml` — everything dataset-specific: paths, channel→folder map (incl. which mirror folders to skip), section aliases, company aliases, path-based attribution, test-row filters. Adapting the tool to a new consultation should require only config changes, not code.

### Respondent resolution order (engine `_normalize`)

Forced path attribution (config) → filename-derived company → in-file hints — except when an extractor sets `company_authoritative` (MS Form rows), where the in-file Company column beats the filename. Email match always wins inside `resolve()`.

### Data quirks encoded in config (do not "fix" them in code)

- The MS Form export filename contains a non-breaking space → resolved via `file_glob`, not a literal path.
- Registry sheet `Splitted 2 - IMs clean`: data rows 4–28; later rows are summary statistics.
- `Feedback mailbox/` and `mails/` subfolders mirror the numbered top-level mailbox files → marked `ingest: false`.
- "same as FTE" docx files are endorsements of the FTE response: recorded as a single linking item (`endorses: fte`), never re-extracted as content.
- RNE-internal test submissions are filtered by domain/name blocklists (including a typo'd `rne.u` domain); every skip is logged in the gather report.
- ProRail, Infrabel and PKP Polskie Linie Kolejowe are real stakeholders absent from the registry — they get minted and flagged, intentionally. (PKP PLK was once silently merged into PKP Cargo by loose fuzzy matching; that's why `resolve()` uses strict `token_sort_ratio` ≥ 87. Never loosen the matcher to fix an unmatched name — add a `company_aliases` entry instead.)
- MS Form notification e-mails are all sent by the same RNE mailbox, so `msg_ext` deliberately clears sender-based identity hints for them; the respondent comes from the filename.

## Privacy rules (non-negotiable)

- Never commit or push `2025 CCs Guidelines review/`, `feedback_gatherer/output/`, or any `.msg` file. Check `git status` before any commit; the `.gitignore` is the enforcement layer — don't weaken it.
- The Streamlit app must keep processing uploads purely in memory (no temp files, no persistence).
- The committed `feedback_gatherer/samples/` files are synthetic (fictional companies) and are the only "data" allowed in the repo.
