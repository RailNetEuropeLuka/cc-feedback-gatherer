"""Headless analysis engine for the feedback dashboard (stage 2.1).

Loads the gathered feedback, embeds the MS Form items with a local sentence
transformer (falling back to TF-IDF when the model is unavailable), and offers
similarity / clustering / aggregation primitives. No Streamlit imports here -
dashboard.py is a thin UI over this module, mirroring the stage-1 principle of
one engine with thin front-ends.

Smoke test:  PYTHONIOENCODING=utf-8 python feedback_gatherer/analysis.py
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUTPUT_DIR = HERE / "output"
CACHE_DIR = OUTPUT_DIR / "_cache"
MODEL_NAME = "all-MiniLM-L6-v2"

SECTION_ORDER = ["1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "2.4", "2.5",
                 "3.1", "3.2", "general"]

_GATHER_HINT = ("No gathered feedback found. Run the stage-1 gatherer first:\n"
                "    python feedback_gatherer/gather.py")


# --------------------------------------------------------------------- loading
def load_feedback(path: Path | None = None) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Read feedback.json -> (meta, respondents_df, items_df)."""
    path = Path(path) if path else OUTPUT_DIR / "feedback.json"
    if not path.exists():
        raise FileNotFoundError(f"{_GATHER_HINT}\n(expected: {path})")
    env = json.loads(path.read_text(encoding="utf-8"))
    return env.get("meta", {}), pd.DataFrame(env["respondents"]), pd.DataFrame(env["items"])


def msform_items(items_df: pd.DataFrame) -> pd.DataFrame:
    """The structured MS Form channel subset - the dashboard's scope."""
    df = items_df[items_df["channel"] == "msform"].reset_index(drop=True)
    return df


def item_text(row) -> str:
    """Text used for embedding. proposal is null on msform items today, but
    tolerate it for future-proofing."""
    parts = [row.get("considerations") or ""]
    if row.get("proposal"):
        parts.append(row["proposal"])
    return "\n".join(p for p in parts if p).strip()


# -------------------------------------------------------------------- backends
@dataclass
class Backend:
    name: str                                  # "minilm" | "tfidf"
    encode: Callable[[list[str]], np.ndarray]  # -> unit-normalised float32 (n, d)
    warning: str | None = None                 # set when degraded to fallback
    cacheable: bool = True                     # tfidf vectors are corpus-dependent


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (mat / norms).astype(np.float32)


def _chunks(text: str, max_words: int = 150) -> list[str]:
    """MiniLM truncates around 256 tokens; mean-pool word-window chunks for the
    handful of long items (max observed ~4000 chars)."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]


def _minilm_backend() -> Backend:
    from sentence_transformers import SentenceTransformer  # lazy: heavy import
    model = SentenceTransformer(MODEL_NAME)

    def encode(texts: list[str]) -> np.ndarray:
        flat: list[str] = []
        spans: list[tuple[int, int]] = []
        for t in texts:
            cs = _chunks(t)
            spans.append((len(flat), len(flat) + len(cs)))
            flat.extend(cs)
        vecs = model.encode(flat, normalize_embeddings=True, show_progress_bar=False)
        pooled = np.vstack([vecs[a:b].mean(axis=0) for a, b in spans])
        return _normalize(pooled)

    return Backend(name="minilm", encode=encode)


def _tfidf_backend(corpus: list[str]) -> Backend:
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True,
                          ngram_range=(1, 2), min_df=1)
    vec.fit(corpus)

    def encode(texts: list[str]) -> np.ndarray:
        return _normalize(np.asarray(vec.transform(texts).todense()))

    return Backend(
        name="tfidf", encode=encode, cacheable=False,
        warning=("Semantic model unavailable - running on TF-IDF word overlap "
                 "instead. Similarity still works, but 'same idea, different "
                 "wording' matches are weaker."))


def get_backend(corpus: list[str], prefer: str = "minilm") -> Backend:
    """Semantic embeddings when possible, TF-IDF otherwise (offline machines)."""
    if prefer == "minilm":
        try:
            return _minilm_backend()
        except Exception:  # ImportError, blocked download (OSError), etc.
            pass
    return _tfidf_backend(corpus)


# ----------------------------------------------------------------- embeddings
def embed_items(items_df: pd.DataFrame, backend: Backend,
                cache_dir: Path = CACHE_DIR) -> np.ndarray:
    """Encode every item, using a per-item disk cache keyed by text hash so a
    re-gather only re-encodes what changed."""
    texts = [item_text(r) for _, r in items_df.iterrows()]
    if not backend.cacheable:
        return backend.encode(texts)

    hashes = [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in texts]
    cache_file = cache_dir / f"embeddings_{backend.name}.npz"
    cached: dict[str, np.ndarray] = {}
    if cache_file.exists():
        try:
            z = np.load(cache_file, allow_pickle=False)
            cached = {h: v for h, v in zip(z["hashes"], z["vectors"])}
        except Exception:
            cached = {}

    missing = [i for i, h in enumerate(hashes) if h not in cached]
    if missing:
        new_vecs = backend.encode([texts[i] for i in missing])
        for i, v in zip(missing, new_vecs):
            cached[hashes[i]] = v
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_file,
                            hashes=np.array(list(cached.keys())),
                            vectors=np.vstack(list(cached.values())))
    return np.vstack([cached[h] for h in hashes])


def similarity_matrix(emb: np.ndarray) -> np.ndarray:
    return np.clip(emb @ emb.T, -1.0, 1.0)


# ----------------------------------------------------------------- similarity
def top_similar(item_idx: int, sim: np.ndarray, items_df: pd.DataFrame, *,
                k: int = 10, min_score: float = 0.35,
                exclude_same_respondent: bool = True,
                same_section_only: bool = False) -> pd.DataFrame:
    """Most-similar items to items_df.iloc[item_idx], with filters."""
    row = items_df.iloc[item_idx]
    scores = sim[item_idx].copy()
    scores[item_idx] = -1.0
    out = items_df.assign(score=scores)
    if exclude_same_respondent:
        out = out[out["respondent_id"] != row["respondent_id"]]
    if same_section_only:
        out = out[out["section_ref"] == row["section_ref"]]
    out = out[out["score"] >= min_score]
    return out.sort_values("score", ascending=False).head(k)


# ------------------------------------------------------------------ clustering
def cluster_items(emb: np.ndarray, items_df: pd.DataFrame, *,
                  threshold: float = 0.60, scope: str = "per_section") -> pd.DataFrame:
    """Group similar items. Agglomerative + cosine distance threshold: no preset
    K, deterministic, and the threshold maps directly to a UI slider. Singletons
    get cluster_id "-" (unique points, not forced into a theme).

    threshold is a SIMILARITY floor: items closer than (1 - threshold) cosine
    distance may merge. scope: "all" or "per_section".
    """
    from sklearn.cluster import AgglomerativeClustering

    df = items_df.copy()
    df["cluster_id"] = "-"

    def _run(idx: np.ndarray, prefix: str):
        if len(idx) < 2:
            return
        model = AgglomerativeClustering(
            n_clusters=None, distance_threshold=1.0 - threshold,
            metric="cosine", linkage="average")
        labels = model.fit_predict(emb[idx])
        counts = pd.Series(labels).value_counts()
        for pos, lab in zip(idx, labels):
            if counts[lab] >= 2:
                df.iloc[pos, df.columns.get_loc("cluster_id")] = f"{prefix}{lab}"

    if scope == "per_section":
        for sec in df["section_ref"].unique():
            idx = np.where((df["section_ref"] == sec).to_numpy())[0]
            _run(idx, f"{sec}/")
    else:
        _run(np.arange(len(df)), "")
    return df


def _cluster_keywords(texts: list[str], all_texts: list[str], top_n: int = 4) -> str:
    """Cheap human-readable label: terms most distinctive for the cluster
    against the whole corpus."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
        vec.fit(all_texts)
        centroid = np.asarray(vec.transform([" ".join(texts)]).todense()).ravel()
        top = centroid.argsort()[::-1][:top_n]
        return ", ".join(np.array(vec.get_feature_names_out())[top])
    except Exception:
        return ""


def summarize_clusters(df: pd.DataFrame, emb: np.ndarray) -> pd.DataFrame:
    """One row per theme: size, respondents, sections, medoid text, keyword label."""
    all_texts = [item_text(r) for _, r in df.iterrows()]
    rows = []
    for cid, grp in df[df["cluster_id"] != "-"].groupby("cluster_id"):
        idx = grp.index.to_numpy()
        sub = emb[idx] @ emb[idx].T
        medoid_pos = idx[np.argmax(sub.mean(axis=1))]
        med = df.loc[medoid_pos]
        rows.append({
            "cluster_id": cid,
            "n_items": len(grp),
            "n_respondents": grp["respondent_id"].nunique(),
            "respondents": sorted(grp["company"].unique()),
            "classifications": sorted(grp["classification"].unique()),
            "sections": sorted(grp["section_ref"].unique(),
                               key=lambda s: SECTION_ORDER.index(s) if s in SECTION_ORDER else 99),
            "keywords": _cluster_keywords([all_texts[i] for i in idx], all_texts),
            "medoid_item_id": med["item_id"],
            "medoid_excerpt": (med["considerations"] or "")[:220],
            "member_idx": list(idx),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["n_respondents", "n_items"], ascending=False).reset_index(drop=True)
    return out


# ---------------------------------------------------------------- aggregations
def respondent_similarity(sim: np.ndarray, items_df: pd.DataFrame) -> pd.DataFrame:
    """R x R agreement map: for each ordered pair, the mean over A's items of the
    best-matching item from B; symmetrised by averaging both directions."""
    companies = sorted(items_df["company"].unique())
    pos = {c: np.where((items_df["company"] == c).to_numpy())[0] for c in companies}
    n = len(companies)
    mat = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            block = sim[np.ix_(pos[companies[i]], pos[companies[j]])]
            val = (block.max(axis=1).mean() + block.max(axis=0).mean()) / 2
            mat[i, j] = mat[j, i] = val
    return pd.DataFrame(mat, index=companies, columns=companies)


def section_consensus(sim: np.ndarray, items_df: pd.DataFrame) -> pd.DataFrame:
    """Per section: how similar are comments from DIFFERENT respondents?
    High -> consensus theme; low -> divergent viewpoints."""
    rows = []
    for sec in [s for s in SECTION_ORDER if s in set(items_df["section_ref"])]:
        idx = np.where((items_df["section_ref"] == sec).to_numpy())[0]
        rids = items_df.iloc[idx]["respondent_id"].to_numpy()
        pair_scores = []
        for ii in range(len(idx)):
            for jj in range(ii + 1, len(idx)):
                if rids[ii] != rids[jj]:
                    pair_scores.append(sim[idx[ii], idx[jj]])
        rows.append({"section_ref": sec,
                     "n_items": len(idx),
                     "n_respondents": items_df.iloc[idx]["respondent_id"].nunique(),
                     "mean_cross_similarity": float(np.mean(pair_scores)) if pair_scores else np.nan})
    return pd.DataFrame(rows)


def semantic_search(query: str, backend: Backend, emb: np.ndarray,
                    items_df: pd.DataFrame, k: int = 20) -> pd.DataFrame:
    qv = backend.encode([query])
    scores = (emb @ qv.T).ravel()
    out = items_df.assign(score=scores).sort_values("score", ascending=False)
    return out.head(k)


# ------------------------------------------------------------------ smoke test
def _main():
    meta, resp_df, items_df = load_feedback()
    df = msform_items(items_df)
    texts = [item_text(r) for _, r in df.iterrows()]
    backend = get_backend(texts)
    print(f"backend: {backend.name}" + (f"  (WARNING: {backend.warning})" if backend.warning else ""))
    print(f"msform items: {len(df)}  respondents: {df['respondent_id'].nunique()}")
    emb = embed_items(df, backend)
    sim = similarity_matrix(emb)
    print(f"embeddings: {emb.shape}  sim diag ok: {bool(np.allclose(np.diag(sim), 1.0, atol=1e-4))}")
    for thr in (0.35, 0.45, 0.55):
        cl = cluster_items(emb, df, threshold=thr)
        summ = summarize_clusters(cl, emb)
        multi = summ[summ["n_respondents"] >= 2] if not summ.empty else summ
        print(f"threshold {thr}: {len(summ)} themes, {len(multi)} with >=2 respondents, "
              f"{(cl['cluster_id'] == '-').sum()} unique items")
    cl = cluster_items(emb, df, threshold=0.45)
    summ = summarize_clusters(cl, emb)
    print("\ntop themes @0.45:")
    for _, r in summ.head(8).iterrows():
        print(f"  [{r['n_respondents']} resp / {r['n_items']} items] {r['keywords']}"
              f"  | sections: {', '.join(r['sections'])}")
    sc = section_consensus(sim, df)
    print("\nsection consensus:")
    print(sc.to_string(index=False))


if __name__ == "__main__":
    _main()
