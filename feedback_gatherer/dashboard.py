"""Local analysis dashboard for gathered consultation feedback (stage 2.1).

Question-first layout: the Guidelines' own chapters are the navigation, the
machine-learning machinery stays out of sight. Thin Streamlit UI over analysis.py.

    pip install -r feedback_gatherer/requirements-analysis.txt
    streamlit run feedback_gatherer/dashboard.py

Reads feedback_gatherer/output/feedback.json (run gather.py first). Local-only:
this dashboard is not part of the public deployment and real data stays on disk.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analysis  # noqa: E402
from analysis import SECTION_ORDER, item_text  # noqa: E402

st.set_page_config(page_title="CC Feedback Analysis", page_icon="📊", layout="wide")

# ---- palette (validated reference palette; entity-fixed, never re-ranked) ----
SURFACE = "#fcfcfb"
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, BASELINE = "#e1e0d9", "#c3c2b7"
CLASS_COLORS = {"RU": "#2a78d6", "Association": "#1baf7a",
                "Unknown": "#eda100", "MTO": "#008300"}
SEQ_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# clustering defaults tuned on this corpus; adjustable under "Advanced"
DEFAULT_THRESHOLD, DEFAULT_SCOPE = 0.60, "per_section"


def _style(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=INK_2, size=13),
        margin=dict(l=8, r=8, t=28, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hoverlabel=dict(bgcolor="#ffffff", font=dict(family=FONT, color=INK)))
    fig.update_xaxes(gridcolor=GRID, linecolor=BASELINE,
                     tickfont=dict(color=MUTED), zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=BASELINE,
                     tickfont=dict(color=MUTED), zeroline=False)
    return fig


def consensus_words(v: float | None) -> str:
    """Plain-language reading of a section's cross-respondent similarity."""
    if v is None or np.isnan(v):
        return ""
    if v >= 0.55:
        return "🤝 strong common ground"
    if v >= 0.35:
        return "↔️ partly shared concerns"
    return "🧩 scattered viewpoints"


def org_line(companies: list[str]) -> str:
    return " · ".join(f"**{c}**" for c in companies)


# ------------------------------------------------------------------ data layer
FEEDBACK = analysis.OUTPUT_DIR / "feedback.json"


@st.cache_data(show_spinner="Loading feedback…")
def load_data(mtime: float) -> pd.DataFrame:
    _, _, items_df = analysis.load_feedback(FEEDBACK)
    df = analysis.msform_items(items_df)
    df["text"] = [item_text(r) for _, r in df.iterrows()]
    df["excerpt"] = df["considerations"].str.replace(r"\s+", " ", regex=True).str.slice(0, 130)
    return df


@st.cache_resource(show_spinner="Loading language model (first time only)…")
def get_backend(corpus: tuple[str, ...]):
    # model weights are read-only -> process-wide cache is safe here
    return analysis.get_backend(list(corpus))


@st.cache_data(show_spinner="Analysing similarity…")
def get_matrices(mtime: float, backend_name: str):
    df = load_data(mtime)
    backend = get_backend(tuple(df["text"]))
    emb = analysis.embed_items(df, backend)
    return emb, analysis.similarity_matrix(emb)


@st.cache_data(show_spinner="Grouping recurring points…")
def get_clusters(mtime: float, backend_name: str, threshold: float, scope: str):
    df = load_data(mtime)
    emb, _ = get_matrices(mtime, backend_name)
    clustered = analysis.cluster_items(emb, df, threshold=threshold, scope=scope)
    return clustered, analysis.summarize_clusters(clustered, emb)


@st.cache_data(show_spinner=False)
def get_consensus(mtime: float, backend_name: str) -> pd.DataFrame:
    df = load_data(mtime)
    _, sim = get_matrices(mtime, backend_name)
    return analysis.section_consensus(sim, df).set_index("section_ref")


if not FEEDBACK.exists():
    st.error("No gathered feedback found.\n\nRun the stage-1 gatherer first:\n"
             "```\npython feedback_gatherer/gather.py\n```")
    st.stop()

MTIME = FEEDBACK.stat().st_mtime
df = load_data(MTIME)
backend = get_backend(tuple(df["text"]))
emb, sim = get_matrices(MTIME, backend.name)
clustered, themes = get_clusters(MTIME, backend.name, DEFAULT_THRESHOLD, DEFAULT_SCOPE)
consensus = get_consensus(MTIME, backend.name)
SECTIONS = [s for s in SECTION_ORDER if s in set(df["section_ref"])]
TITLE_BY_SEC = df.drop_duplicates("section_ref").set_index("section_ref")["section_title"]


def themes_for(sec: str) -> pd.DataFrame:
    if themes.empty:
        return themes
    return themes[themes["cluster_id"].str.startswith(f"{sec}/")]


def render_comment(row, show_section=False):
    tag = f" · chapter {row['section_ref']}" if show_section else ""
    st.markdown(f"**{row['company']}** ({row['classification']}){tag}")
    st.write(row["considerations"])


# ------------------------------------------------------------------------- UI
st.title("📊 What did stakeholders say about the Commercial Conditions Guidelines?")
st.caption(f"{len(df)} structured comments (MS Form) from "
           f"{df['respondent_id'].nunique()} organisations · 23 Jun – 23 Aug 2025 "
           "consultation · analysed locally, chapter by chapter")
if backend.warning:
    st.warning(backend.warning)

tab_ch, tab_th, tab_find, tab_align = st.tabs([
    "📖 By chapter", "🔁 Recurring points", "🔎 Find a comment", "🤝 Who aligns"])

# ------------------------------------------------------------------ By chapter
with tab_ch:
    st.markdown("**Start here.** Every chapter of the Guidelines, what came in, and "
                "whether respondents pull in the same direction. Pick a chapter to read it.")

    # digest: one compact row per chapter
    digest_rows = []
    for sec in SECTIONS:
        sub = df[df["section_ref"] == sec]
        th = themes_for(sec)
        n_rec = len(th[th["n_respondents"] >= 2]) if not th.empty else 0
        cons = consensus["mean_cross_similarity"].get(sec, np.nan)
        digest_rows.append({
            "Chapter": f"{sec} — {TITLE_BY_SEC.get(sec, '')}",
            "Comments": len(sub),
            "Organisations": sub["respondent_id"].nunique(),
            "Recurring points": n_rec,
            "Mood": consensus_words(cons),
        })
    st.dataframe(pd.DataFrame(digest_rows), width="stretch", hide_index=True)

    st.divider()
    sec = st.selectbox("Open a chapter", SECTIONS,
                       format_func=lambda s: f"{s} — {TITLE_BY_SEC.get(s, '')}")
    sub = df[df["section_ref"] == sec]
    cons = consensus["mean_cross_similarity"].get(sec, np.nan)
    st.subheader(f"{sec} — {TITLE_BY_SEC.get(sec, '')}")
    st.caption(f"{len(sub)} comments from {sub['respondent_id'].nunique()} organisations · "
               f"{consensus_words(cons)}")

    inner_rec, inner_all = st.tabs(["Recurring points", "All comments"])
    with inner_rec:
        th = themes_for(sec)
        multi = th[th["n_respondents"] >= 2] if not th.empty else th
        if multi.empty:
            st.info("No point in this chapter was raised by more than one organisation — "
                    "see All comments for the individual views.")
        for _, t in multi.iterrows():
            st.markdown(f"##### “{t['medoid_excerpt'].strip()}…”")
            st.caption(f"Raised by {t['n_respondents']} organisations · "
                       f"key terms: {t['keywords']}")
            st.markdown(org_line(t["respondents"]))
            with st.popover("Read all versions of this point"):
                for i in t["member_idx"]:
                    render_comment(clustered.iloc[i])
                    st.divider()
            st.divider()
        singles = sub[clustered.loc[sub.index, "cluster_id"] == "-"] \
            if not sub.empty else sub
        if not singles.empty:
            st.markdown(f"**Points raised by a single organisation ({len(singles)})**")
            for _, s in singles.iterrows():
                with st.popover(f"{s['company']}: {s['excerpt']}…"):
                    render_comment(s)
    with inner_all:
        for _, r in sub.iterrows():
            render_comment(r)
            st.divider()

# ------------------------------------------------------------- Recurring points
with tab_th:
    st.markdown("**The points stakeholders raised again and again** — across all "
                "chapters, most-echoed first. Each card is one recurring point; open it "
                "to read every organisation's version.")

    with st.expander("⚙️ Advanced: how points are grouped"):
        c1, c2 = st.columns(2)
        tightness = c1.slider(
            "Grouping", 0.40, 0.80, DEFAULT_THRESHOLD, 0.05,
            help="Left: broader groups (more comments per point, looser match). "
                 "Right: only near-identical comments group together.")
        min_orgs = c2.slider("Only show points raised by at least … organisations",
                             1, 6, 2)
    cl2, th2 = get_clusters(MTIME, backend.name, tightness, DEFAULT_SCOPE)
    shown = th2[th2["n_respondents"] >= min_orgs] if not th2.empty else th2
    if shown.empty:
        st.info("Nothing recurs at this setting — move the grouping slider left.")
    for _, t in shown.iterrows():
        secs = ", ".join(t["sections"])
        st.markdown(f"##### “{t['medoid_excerpt'].strip()}…”")
        st.caption(f"Raised by {t['n_respondents']} organisations · chapter {secs} · "
                   f"key terms: {t['keywords']}")
        st.markdown(org_line(t["respondents"]))
        with st.popover("Read all versions of this point"):
            for i in t["member_idx"]:
                render_comment(cl2.iloc[i], show_section=True)
                st.divider()
        st.divider()

# -------------------------------------------------------------- Find a comment
with tab_find:
    st.markdown("**Look anything up.** Search by meaning (\"penalties for late TCRs\") "
                "or filter by organisation — then click a row to read the comment and "
                "see who else made the same point.")
    c1, c2, c3 = st.columns([3, 2, 2])
    query = c1.text_input("Search", placeholder='e.g. "compensation for TCR changes"')
    f_org = c2.multiselect("Organisation", sorted(df["company"].unique()))
    f_sec = c3.multiselect("Chapter", SECTIONS)

    bdf = df
    if f_org:
        bdf = bdf[bdf["company"].isin(f_org)]
    if f_sec:
        bdf = bdf[bdf["section_ref"].isin(f_sec)]
    if query.strip():
        hits = analysis.semantic_search(query, backend, emb, df, k=40)
        bdf = hits[hits["item_id"].isin(bdf["item_id"])]

    view = bdf[["company", "classification", "section_ref", "excerpt"]].rename(columns={
        "company": "Organisation", "classification": "Type",
        "section_ref": "Chapter", "excerpt": "Comment (start)"})
    st.caption(f"{len(bdf)} comment(s)")
    sel = st.dataframe(view, width="stretch", hide_index=True,
                       on_select="rerun", selection_mode="single-row")
    if sel.selection.rows:
        r = bdf.iloc[sel.selection.rows[0]]
        st.divider()
        st.markdown(f"### {r['company']} on {r['section_ref']} {r['section_title']}")
        st.info(r["considerations"])
        st.markdown("**Who else made a similar point?**")
        idx = df.index[df["item_id"] == r["item_id"]][0]
        similar = analysis.top_similar(idx, sim, df, k=6, min_score=0.45)
        if similar.empty:
            st.caption("No other organisation said something comparable — "
                       "this point appears to be unique.")
        for _, s in similar.iterrows():
            pct = int(round(s["score"] * 100))
            with st.expander(f"{s['company']} · chapter {s['section_ref']} · "
                             f"{pct}% similar — {s['excerpt']}…"):
                st.write(s["considerations"])

# ------------------------------------------------------------------ Who aligns
with tab_align:
    st.markdown("**Which organisations say similar things?** Darker = their comments "
                "overlap more. Useful for spotting coordinated positions "
                "(e.g. respondents following the same association line).")
    scope_sec = st.selectbox(
        "Compare organisations on…", ["All chapters combined"] + SECTIONS,
        format_func=lambda s: s if s == "All chapters combined"
        else f"chapter {s} — {TITLE_BY_SEC.get(s, '')}")

    if scope_sec == "All chapters combined":
        a_df, a_sim = df, sim
    else:
        pos = np.where((df["section_ref"] == scope_sec).to_numpy())[0]
        a_df = df.iloc[pos].reset_index(drop=True)
        a_sim = sim[np.ix_(pos, pos)]

    if a_df["respondent_id"].nunique() < 2:
        st.info("Fewer than two organisations commented here — nothing to compare.")
    else:
        rs = analysis.respondent_similarity(a_sim, a_df)
        fig = go.Figure(go.Heatmap(
            z=rs.values, x=rs.columns, y=rs.index,
            colorscale=[[i / (len(SEQ_RAMP) - 1), c] for i, c in enumerate(SEQ_RAMP)],
            zmin=0, zmax=1, xgap=2, ygap=2,
            colorbar=dict(title="overlap", tickfont=dict(color=MUTED)),
            hovertemplate="%{y} ↔ %{x}: %{z:.2f}<extra></extra>"))
        st.plotly_chart(_style(fig, height=max(380, 38 * len(rs))), width="stretch")

        # the same insight in words, no chart-reading required
        pairs = []
        cols = list(rs.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                pairs.append((rs.iloc[i, j], cols[i], cols[j]))
        pairs.sort(reverse=True)
        where = ("across all chapters" if scope_sec == "All chapters combined"
                 else f"on chapter {scope_sec}")
        st.markdown(f"**Most aligned pairs {where}:**")
        for score, a, b in pairs[:5]:
            st.markdown(f"- **{a}** ↔ **{b}** — {int(round(score * 100))}% overlap")
