# Feedback Gatherer — Stage 1

Consolidates RNE consultation feedback locked in many formats (`.msg`, `.docx`,
`.pdf`, `.xlsx`) into **one unified structure** — one record per atomic feedback
item (respondent × guideline section). Built as a reusable, config-driven tool
with **two front-ends on one shared engine**.

## Install

```bash
pip install -r feedback_gatherer/requirements.txt
```

## 1. Batch CLI — gather the whole consultation folder

```bash
python feedback_gatherer/gather.py
# options: --config path/to/config.yaml   --out path/to/output
```

Writes to `feedback_gatherer/output/`:
- `feedback.json` — canonical structured data (respondents + items)
- `feedback.xlsx` — review copy (sheets: **Items**, **Respondents**, **Summary**)
- `gather_report.md` — run report: counts, dedup actions, endorsements,
  skipped test rows, and a **needs-review** list

## 2. "Try-it" web app — upload and watch it extract

```bash
streamlit run feedback_gatherer/app.py
```

Drag-and-drop one or more feedback files of any supported format and see the
extracted items table, a raw-vs-parsed view per file, and JSON/Excel downloads.
**Uploads are processed in memory and never stored.** Local-first; deployable
later (internal server / cloud) with no code change.

## How it works

```
config.yaml        paths, channel map, section taxonomy, dedup + test-row rules, aliases
engine.py          SHARED CORE: extract_file(bytes) + gather_folder()
gather.py          CLI front-end            app.py   Streamlit front-end
extractors/        xlsx_form · docx · pdf · msg
respondents.py     registry (Overview xlsx) + fuzzy company matching
taxonomy.py        map raw labels/numbers -> canonical section refs (1.1 … 3.2, general)
writers.py         JSON + Excel serialisation
schema.py          FeedbackItem / Respondent data model
```

Pipeline: **build respondent registry → extract each source → resolve
respondent (email → filename → body, fuzzy) → tag canonical section → dedup
(drop mirrors/zips, collapse "same as FTE" to endorsements) → write**.

## Tuning for a future consultation

Everything data-specific lives in `config.yaml`: the data root, which folders
map to which channel (and which to ignore), the section taxonomy and aliases,
company aliases, path-based attribution, and test-row filters. Point it at a new
archive and re-run.
