"""CLI front-end: gather the whole consultation folder into feedback.json +
feedback.xlsx + a human-readable run report.

Usage:
    python feedback_gatherer/gather.py
    python feedback_gatherer/gather.py --config path/to/config.yaml --out path/to/output
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# allow running both as a module and as a script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Engine, load_config  # noqa: E402
import writers  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Gather consultation feedback into one structure.")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--out", default=None, help="output directory")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    repo_root = here.parent
    cfg = load_config(args.config)
    out_dir = Path(args.out) if args.out else here / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Building respondent registry ...")
    engine = Engine.create(config_path=args.config, repo_root=repo_root, with_registry=True)
    print(f"  {len(engine.registry.respondents)} respondents in registry")

    print("Gathering feedback ...")
    result = engine.gather_folder()

    meta = {
        "source": cfg.get("data_root"),
        "totals": result.report.get("totals", {}),
        "generated_by": "feedback_gatherer",
    }
    (out_dir / "feedback.json").write_bytes(
        writers.to_json_bytes(result.items, result.respondents, meta))
    (out_dir / "feedback.xlsx").write_bytes(
        writers.to_excel_bytes(result.items, result.respondents))
    (out_dir / "gather_report.md").write_text(_report_md(result), encoding="utf-8")

    t = result.report["totals"]
    print(f"\nDone. {t['items']} items from {t['respondents_with_feedback']} respondents.")
    print(f"  -> {out_dir / 'feedback.json'}")
    print(f"  -> {out_dir / 'feedback.xlsx'}")
    print(f"  -> {out_dir / 'gather_report.md'}")


def _report_md(result) -> str:
    r = result.report
    t = r["totals"]
    lines = ["# Feedback gather report", ""]
    lines += [f"- **Total feedback items:** {t['items']}",
              f"- **Respondents with feedback:** {t['respondents_with_feedback']}",
              f"- **Respondents in registry:** {t['respondents_in_registry']}", ""]

    lines.append("## Items by format")
    for fmt, n in sorted(r["by_format"].items()):
        lines.append(f"- {fmt}: {n} file(s)")
    lines.append("")

    # per-respondent counts
    lines.append("## Respondents")
    lines.append("| Company | Class | Align | Items | Channels |")
    lines.append("|---|---|---|---|---|")
    for rs in result.respondents:
        lines.append(f"| {rs.company} | {rs.classification} | {rs.fte_alignment or ''} "
                     f"| {rs.n_items} | {', '.join(rs.channels)} |")
    lines.append("")

    # items per section
    by_sec: dict[str, int] = {}
    for it in result.items:
        by_sec[it.section_ref] = by_sec.get(it.section_ref, 0) + 1
    lines.append("## Items by guideline section")
    for sec in sorted(by_sec):
        lines.append(f"- {sec}: {by_sec[sec]}")
    lines.append("")

    _block(lines, "Files ingested", r["files_ingested"])
    _block(lines, "Endorsements (same as FTE)", r["endorsements"])
    _block(lines, "Test rows skipped", r["test_rows_skipped"])
    _block(lines, "Files skipped (dedup/ignored/channel off)", r["files_skipped"])
    _block(lines, "Errors", r["errors"])

    # needs-review list
    nr = [it for it in result.items if it.needs_review]
    lines.append(f"## Needs review ({len(nr)})")
    for it in nr[:200]:
        lines.append(f"- `{it.source_file}` -> {it.company} / {it.section_ref}: {it.review_note}")
    return "\n".join(lines) + "\n"


def _block(lines: list[str], title: str, entries: list[str]):
    lines.append(f"## {title} ({len(entries)})")
    for e in entries:
        lines.append(f"- {e}")
    lines.append("")


if __name__ == "__main__":
    main()
