"""Local analysis dashboard for gathered consultation feedback (stage 2.1).

Thin Streamlit UI over analysis.py. Scope: the structured MS Form channel only.

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
CLASS_COLORS = {          # categorical slots 1-4, fixed per classification
    "RU": "#2a78d6",
    "Association": "#1baf7a",
    "Unknown": "#eda100",
    "MTO": "#008300",
}
SEQ_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _style(fig: go.Figure, height: int = 380) -> go.Figure:
    fig.update_layout(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=INK_2, size=13),
        margin=dict(l=8, r=8, t=28, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(color=INK_2)),
        hoverlabel=dict(bgcolor="#ffffff", font=dict(family=FONT, color=INK)),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=BASELINE, tickfont=dict(color=MUTED),
                     zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=BASELINE, tickfont=dict(color=MUTED),
                     zeroline=False)
    return fig


# ------------------------------------------------------------------ data layer
FEEDBACK = analysis.OUTPUT_DIR / "feedback.json"


@st.cache_data(show_spinner="Loading feedback…")
def load_data(mtime: float) -> pd.DataFrame:
    _, _, items_df = analysis.load_feedback(FEEDBACK)
    df = analysis.msform_items(items_df)
    df["text"] = [item_text(r) for _, r in df.iterrows()]
    df["excerpt"] = df["considerations"].str.slice(0, 110)
    return df


@st.cache_resource(show_spinner="Loading embedding model…")
def get_backend(corpus: tuple[str, ...]):
    # model weights are read-only -> process-wide cache is safe here
    # (unlike app.py's mutable engine, which is session-scoped by design)
    return analysis.get_backend(list(corpus))


@st.cache_data(show_spinner="Embedding items…")
def get_matrices(mtime: float, backend_name: str) -> tuple[np.ndarray, np.ndarray]:
    df = load_data(mtime)
    backend = get_backend(tuple(df["text"]))
    emb = analysis.embed_items(df, backend)
    return emb, analysis.similarity_matrix(emb)


@st.cache_data(show_spinner="Clustering…")
def get_clusters(mtime: float, backend_name: str, threshold: float, scope: str):
    df = load_data(mtime)
    emb, _ = get_matrices(mtime, backend_name)
    clustered = analysis.cluster_items(emb, df, threshold=threshold, scope=scope)
    return clustered, analysis.summarize_clusters(clustered, emb)


if not FEEDBACK.exists():
    st.error("No gathered feedback found.\n\nRun the stage-1 gatherer first:\n"
             "```\npython feedback_gatherer/gather.py\n```")
    st.stop()

MTIME = FEEDBACK.stat().st_mtime
df = load_data(MTIME)
backend = get_backend(tuple(df["text"]))
emb, sim = get_matrices(MTIME, backend.name)

# ------------------------------------------------------------------------- UI
st.title("📊 Commercial Conditions — Feedback Analysis")
st.caption("Structured MS Form responses only · similarity computed locally "
           f"({'semantic embeddings' if backend.name == 'minilm' else 'TF-IDF'})")
if backend.warning:
    st.warning(backend.warning)

with st.sidebar:
    st.header("Filters")
    sections = st.multiselect(
        "Guideline section", [s for s in SECTION_ORDER if s in set(df["section_ref"])])
    classes = st.multiselect("Respondent type", sorted(df["classification"].unique()))
    companies = st.multiselect("Respondent", sorted(df["company"].unique()))
    st.divider()
    fdf = df.copy()
    if sections:
        fdf = fdf[fdf["section_ref"].isin(sections)]
    if classes:
        fdf = fdf[fdf["classification"].isin(classes)]
    if companies:
        fdf = fdf[fdf["company"].isin(companies)]
    st.caption(f"MS Form channel only\n\n**{len(fdf)}** items · "
               f"**{fdf['respondent_id'].nunique()}** respondents after filters")

tab_ov, tab_sim, tab_cl, tab_br, tab_map = st.tabs(
    ["Overview", "Similarity explorer", "Theme clusters", "Item browser", "Agreement map"])

# ------------------------------------------------------------------- Overview
with tab_ov:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Feedback items", len(fdf))
    k2.metric("Respondents", fdf["respondent_id"].nunique())
    k3.metric("Sections covered", fdf["section_ref"].nunique())
    k4.metric("Similarity engine", "Semantic" if backend.name == "minilm" else "TF-IDF")

    if fdf.empty:
        st.info("No items match the current filters.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Items per section")
            secs = [s for s in SECTION_ORDER if s in set(fdf["section_ref"])]
            fig = go.Figure()
            for cls, color in CLASS_COLORS.items():
                sub = fdf[fdf["classification"] == cls]
                if sub.empty:
                    continue
                counts = sub.groupby("section_ref").size().reindex(secs).fillna(0)
                fig.add_bar(name=cls, x=secs, y=counts.values, marker_color=color,
                            marker_line=dict(color=SURFACE, width=2),
                            hovertemplate=f"{cls} · %{{x}}: %{{y}}<extra></extra>")
            totals = fdf.groupby("section_ref").size().reindex(secs).fillna(0)
            fig.add_scatter(x=secs, y=totals.values, mode="text",
                            text=[int(v) for v in totals.values], textposition="top center",
                            textfont=dict(color=INK_2, size=12), showlegend=False,
                            hoverinfo="skip")
            fig.update_layout(barmode="stack", bargap=0.45)
            st.plotly_chart(_style(fig), width="stretch")

        with c2:
            st.subheader("Items per respondent")
            per_resp = (fdf.groupby(["company", "classification"]).size()
                        .reset_index(name="n").sort_values("n"))
            fig = go.Figure(go.Bar(
                x=per_resp["n"], y=per_resp["company"], orientation="h",
                marker_color=[CLASS_COLORS.get(c, MUTED) for c in per_resp["classification"]],
                marker_line=dict(color=SURFACE, width=2),
                text=per_resp["n"], textposition="outside",
                textfont=dict(color=INK_2, size=12),
                customdata=per_resp["classification"],
                hovertemplate="%{y} (%{customdata}): %{x} items<extra></extra>"))
            fig.update_layout(bargap=0.35, showlegend=False)
            st.plotly_chart(_style(fig, height=max(320, 24 * len(per_resp))),
                            width="stretch")

        st.subheader("Where respondents agree vs diverge")
        st.caption("Mean similarity between comments from *different* respondents in the "
                   "same section — high = shared concerns, low = scattered viewpoints.")
        cons = analysis.section_consensus(sim, df)     # corpus-level, not filtered
        cons = cons.dropna(subset=["mean_cross_similarity"])
        fig = go.Figure(go.Bar(
            x=cons["section_ref"], y=cons["mean_cross_similarity"],
            marker_color="#2a78d6", marker_line=dict(color=SURFACE, width=2),
            text=[f"{v:.2f}" for v in cons["mean_cross_similarity"]],
            textposition="outside", textfont=dict(color=INK_2, size=12),
            customdata=np.stack([cons["n_items"], cons["n_respondents"]], axis=-1),
            hovertemplate="Section %{x}: %{y:.2f} mean similarity<br>"
                          "%{customdata[0]} items from %{customdata[1]} respondents<extra></extra>"))
        fig.update_layout(bargap=0.5, yaxis_title="mean cross-respondent similarity")
        st.plotly_chart(_style(fig, height=320), width="stretch")

# --------------------------------------------------------- Similarity explorer
with tab_sim:
    st.subheader("Who else said something like this?")
    labels = [f"{r.section_ref} | {r.company} | {r.excerpt}" for r in df.itertuples()]
    pick = st.selectbox("Pick a feedback item", range(len(df)),
                        format_func=lambda i: labels[i])
    c1, c2, c3 = st.columns(3)
    k = c1.slider("Max results", 3, 20, 8)
    min_score = c2.slider("Minimum similarity", 0.0, 0.9, 0.35, 0.05)
    same_sec = c3.toggle("Same section only", value=False)

    row = df.iloc[pick]
    st.markdown(f"**{row['company']}** ({row['classification']}) on "
                f"**{row['section_ref']} {row['section_title']}**")
    st.info(row["considerations"])

    similar = analysis.top_similar(pick, sim, df, k=k, min_score=min_score,
                                   exclude_same_respondent=True,
                                   same_section_only=same_sec)
    if similar.empty:
        st.caption("No sufficiently similar items from other respondents — this "
                   "point appears to be unique. Lower the minimum similarity to widen.")
    for _, s in similar.iterrows():
        with st.expander(f"{s['score']:.2f} · {s['company']} ({s['classification']}) "
                         f"· {s['section_ref']} — {s['excerpt']}…"):
            st.write(s["considerations"])

# --------------------------------------------------------------- Theme clusters
with tab_cl:
    st.subheader("Recurring themes")
    c1, c2, c3 = st.columns(3)
    scope = c1.radio("Cluster scope", ["per_section", "all"], horizontal=True,
                     format_func=lambda s: "Within each section" if s == "per_section"
                     else "Whole corpus")
    threshold = c2.slider("Similarity threshold", 0.30, 0.80, 0.60, 0.05,
                          help="How similar items must be to share a theme. "
                               "Higher = tighter, more specific themes.")
    min_resp = c3.slider("Min respondents per theme", 1, 6, 2)

    clustered, summary = get_clusters(MTIME, backend.name, threshold, scope)
    if summary.empty:
        st.info("No themes at this threshold — lower it to allow looser grouping.")
    else:
        shown = summary[summary["n_respondents"] >= min_resp]
        if shown.empty:
            st.info("No themes shared by that many respondents — lower the minimum "
                    "or the threshold.")
        for _, cl in shown.iterrows():
            badge = "" if cl["n_respondents"] > 1 else " · ⚠️ single respondent"
            secs = ", ".join(cl["sections"])
            st.markdown(f"#### {cl['keywords']}")
            st.caption(f"{cl['n_respondents']} respondents · {cl['n_items']} items · "
                       f"section(s) {secs}{badge}")
            st.markdown("**" + "** · **".join(cl["respondents"]) + "**")
            with st.expander(f"Representative: “{cl['medoid_excerpt']}…” — show all "
                             f"{cl['n_items']} items"):
                for i in cl["member_idx"]:
                    m = clustered.iloc[i]
                    st.markdown(f"**{m['company']}** · {m['section_ref']}")
                    st.write(m["considerations"])
                    st.divider()
            st.divider()

        singles = clustered[clustered["cluster_id"] == "-"]
        with st.expander(f"Unique items — {len(singles)} points no other respondent echoed"):
            for _, s in singles.iterrows():
                st.markdown(f"**{s['company']}** · {s['section_ref']} — {s['excerpt']}…")

# ----------------------------------------------------------------- Item browser
with tab_br:
    st.subheader("Browse & search items")
    c1, c2 = st.columns([3, 1])
    query = c1.text_input("Search", placeholder="e.g. compensation for TCR changes")
    semantic = c2.toggle("Semantic search", value=True,
                         help="Rank by meaning instead of exact words.")
    bdf = fdf
    if query.strip():
        if semantic:
            hits = analysis.semantic_search(query, backend, emb, df, k=30)
            bdf = hits[hits["item_id"].isin(fdf["item_id"])]
        else:
            mask = (fdf["considerations"].str.contains(query, case=False, na=False)
                    | fdf["company"].str.contains(query, case=False, na=False))
            bdf = fdf[mask]
    cols = ["company", "classification", "section_ref", "excerpt"]
    if "score" in bdf.columns:
        cols = ["score"] + cols
    st.caption(f"{len(bdf)} item(s)")
    sel = st.dataframe(bdf[cols], width="stretch", hide_index=True,
                       on_select="rerun", selection_mode="single-row")
    if sel.selection.rows:
        r = bdf.iloc[sel.selection.rows[0]]
        st.markdown(f"**{r['company']}** ({r['classification']}) · "
                    f"**{r['section_ref']} {r['section_title']}** · `{r['item_id']}`")
        st.info(r["considerations"])

# ---------------------------------------------------------------- Agreement map
with tab_map:
    st.subheader("Respondent agreement map")
    st.caption("How similar two respondents' overall feedback is (mean of each item's "
               "best match in the other's items). Darker = more aligned.")
    rs = analysis.respondent_similarity(sim, df)
    fig = go.Figure(go.Heatmap(
        z=rs.values, x=rs.columns, y=rs.index,
        colorscale=[[i / (len(SEQ_RAMP) - 1), c] for i, c in enumerate(SEQ_RAMP)],
        zmin=0, zmax=1, xgap=2, ygap=2,
        colorbar=dict(title="similarity", tickfont=dict(color=MUTED)),
        hovertemplate="%{y} ↔ %{x}: %{z:.2f}<extra></extra>"))
    st.plotly_chart(_style(fig, height=560), width="stretch")
    st.caption("Note: diagonal = 1 by definition. High off-diagonal pairs often "
               "signal coordinated or template-based responses.")
