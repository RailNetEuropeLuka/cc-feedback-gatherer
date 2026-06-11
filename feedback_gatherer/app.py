"""Streamlit "try-it" web app for the Feedback Gatherer.

Externals (and the team) can drag-and-drop their own feedback files in any
supported format (.msg / .docx / .pdf / .xlsx) and immediately see how the tool
extracts them into the unified structure, then download JSON + Excel.

  streamlit run feedback_gatherer/app.py

Privacy: uploads are processed entirely in memory and never written to disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Engine, load_config  # noqa: E402
import writers  # noqa: E402

SUPPORTED = ["msg", "docx", "pdf", "xlsx"]
ITEM_VIEW_COLS = ["company", "classification", "section_ref", "section_title",
                  "considerations", "proposal", "extraction_confidence",
                  "needs_review", "source_file"]
HERE = Path(__file__).resolve().parent
SAMPLES_DIR = HERE / "samples"

st.set_page_config(page_title="RNE Feedback Gatherer", page_icon="🚆", layout="wide")


def registry_available() -> bool:
    """True only if the consultation archive (holding the respondent registry with
    names/e-mails) is present. On a public deploy it is NOT, so the app runs
    registry-free and no personal data is ever involved."""
    try:
        cfg = load_config()
        return (HERE.parent / cfg["registry"]["file"]).exists()
    except Exception:
        return False


def get_engine(with_registry: bool):
    """One engine PER BROWSER SESSION (st.session_state), never shared.

    The engine's registry is mutable (uploads mint respondents into it), so a
    process-wide cache (st.cache_resource) would leak company names from one
    user's uploads into other users' sessions on a shared deployment.
    """
    key = f"engine_{with_registry}"
    if key not in st.session_state:
        try:
            st.session_state[key] = (Engine.create(with_registry=with_registry), None)
        except Exception as exc:
            # fall back to a registry-less engine (ad-hoc respondents only)
            st.session_state[key] = (Engine.create(with_registry=False), str(exc))
    return st.session_state[key]


def _conf_emoji(c: str) -> str:
    return {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 low"}.get(c, c)


# --------------------------------------------------------------------------- UI
st.title("🚆 Commercial Conditions — Feedback Gatherer")
st.caption("Upload consultation feedback in any format and see it extracted into "
           "one unified structure. Files are processed in memory and never stored.")

HAS_REGISTRY = registry_available()

with st.sidebar:
    st.header("Options")
    if HAS_REGISTRY:
        use_registry = st.toggle(
            "Match against known respondents", value=True,
            help="Use the consultation Overview spreadsheet to classify respondents "
                 "(RU/IM/Association) and detect FTE alignment. Turn off to treat every "
                 "upload as a brand-new respondent.")
    else:
        use_registry = False
        st.info("**Demo mode** — running without the respondent registry, so no "
                "personal data is involved. Uploads are extracted and shown, never stored.")

    st.markdown("**Supported formats**")
    st.markdown("- `.msg` Outlook e-mails\n- `.docx` Word responses\n- `.pdf` documents\n- `.xlsx` MS Form export")

    # let testers grab a dummy file to try, if samples are bundled
    if SAMPLES_DIR.exists():
        sample_files = sorted(p for p in SAMPLES_DIR.iterdir()
                              if p.suffix.lstrip(".") in SUPPORTED)
        if sample_files:
            st.divider()
            st.markdown("**No file handy? Try a sample:**")
            for sp in sample_files:
                st.download_button(f"⬇️ {sp.name}", data=sp.read_bytes(),
                                   file_name=sp.name, key=f"samp_{sp.name}")
    st.divider()
    st.caption("Section taxonomy follows the Guidelines (1.1 → 3.2 + general).")

engine, reg_err = get_engine(use_registry)
if reg_err and use_registry:
    st.warning(f"Respondent registry unavailable — running registry-free. ({reg_err})")

uploads = st.file_uploader(
    "Drop feedback files here", type=SUPPORTED, accept_multiple_files=True)

if not uploads:
    st.info("⬆️ Upload one or more files to begin. Try a `.docx` response, a `.pdf`, "
            "or the MS Form `.xlsx` export.")
    st.stop()

# ---- run the shared engine on each upload (in memory) ----------------------
all_items = []
per_file = []
for up in uploads:
    data = up.getvalue()
    items, sources = engine.extract_file(data, up.name, channel="upload")
    all_items.extend(items)
    per_file.append((up.name, items, sources))

# refresh respondent rosters for the download payload
resp_ids = {it.respondent_id for it in all_items}
respondents = [engine.registry.respondents[r] for r in resp_ids
               if r in engine.registry.respondents]
for r in respondents:
    r.n_items = sum(1 for it in all_items if it.respondent_id == r.respondent_id)

# ---- summary metrics -------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Files", len(uploads))
c2.metric("Feedback items", len(all_items))
c3.metric("Respondents", len(respondents))
c4.metric("Need review", sum(1 for it in all_items if it.needs_review))

# ---- combined items table --------------------------------------------------
st.subheader("Extracted feedback items")
if all_items:
    df = pd.DataFrame([it.to_dict() for it in all_items])[ITEM_VIEW_COLS]
    df["extraction_confidence"] = df["extraction_confidence"].map(_conf_emoji)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={
                     "considerations": st.column_config.TextColumn(width="large"),
                     "proposal": st.column_config.TextColumn(width="medium"),
                 })

    # downloads (built in memory)
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Download JSON", data=writers.to_json_bytes(all_items, respondents),
                       file_name="feedback_extract.json", mime="application/json")
    d2.download_button("⬇️ Download Excel",
                       data=writers.to_excel_bytes(all_items, respondents),
                       file_name="feedback_extract.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.warning("No feedback items could be extracted from the upload(s).")

# ---- per-file: raw text vs parsed -----------------------------------------
st.subheader("Per-file detail (raw ↔ parsed)")
for name, items, sources in per_file:
    n_items = len(items)
    with st.expander(f"📄 {name} — {n_items} item(s)", expanded=(len(per_file) == 1)):
        for ps in sources:
            who = items[0].company if items else (ps.company_hint or "—")
            badges = []
            if ps.is_endorsement:
                badges.append("🔁 endorsement (same as FTE)")
            if any("__TEST__" in n for n in ps.notes):
                badges.append("🧪 test/internal submission (skipped)")
            if ps.attachments:
                badges.append(f"📎 {len(ps.attachments)} attachment(s) parsed")
            st.markdown(f"**Detected respondent:** {who}  &nbsp; "
                        f"**Format:** `{ps.source_format}`  "
                        + ("&nbsp; " + " · ".join(badges) if badges else ""))
            for note in ps.notes:
                if not note.startswith("__") and not note.startswith("rep:"):
                    st.caption("ℹ️ " + note)

        col_raw, col_parsed = st.columns(2)
        with col_raw:
            st.markdown("**Raw extracted text**")
            raw = "\n\n".join(ps.full_text for ps in sources if ps.full_text)
            st.text_area("raw", raw or "(no text)", height=320,
                         label_visibility="collapsed", key=f"raw_{name}")
        with col_parsed:
            st.markdown("**Parsed items**")
            if items:
                for it in items:
                    flag = " ⚠️" if it.needs_review else ""
                    st.markdown(f"**[{it.section_ref}] {it.section_title}** "
                                f"· {_conf_emoji(it.extraction_confidence)}{flag}")
                    st.write(it.considerations or "_(no text)_")
                    if it.proposal:
                        st.markdown(f"➡️ *Proposal:* {it.proposal}")
                    st.divider()
            else:
                st.write("_No items extracted._")
