"""
cluster_builder.py — Build sector clusters from company descriptions using
TF-IDF + K-Means.

Reuses the TF-IDF vectorizer and corpus model from enrichment/tfidf_extractor.py
when available; otherwise builds a standalone vectorizer from the descriptions
passed in the input DataFrame.

The cluster labels are auto-generated from the top-5 TF-IDF terms in each
K-Means centroid, making them interpretable without manual curation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── Text assembly helper ──────────────────────────────────────────────────────

def _row_to_text(row: pd.Series) -> str:
    """
    Concatenate description columns into a single document for a company row.

    Uses 'about' and 'full_description' — the same columns scored by
    enrichment/tfidf_extractor.py.
    """
    parts: list[str] = []
    for col in ("about", "full_description", "overview_highlights"):
        val = row.get(col, "")
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    return " ".join(parts)


# ── Public API ────────────────────────────────────────────────────────────────

def get_cluster_top_terms(
    vectorizer: TfidfVectorizer,
    kmeans: KMeans,
    cluster_id: int,
    top_n: int = 5,
) -> list[str]:
    """
    Return the top-N TF-IDF terms for a K-Means cluster centroid.

    Args:
        vectorizer: Fitted TfidfVectorizer instance.
        kmeans:     Fitted KMeans instance.
        cluster_id: Zero-based cluster index.
        top_n:      Number of terms to return.

    Returns:
        List of term strings, highest-weight first.
    """
    feature_names = vectorizer.get_feature_names_out()
    centroid = kmeans.cluster_centers_[cluster_id]
    top_indices = centroid.argsort()[::-1][:top_n]
    return [feature_names[i] for i in top_indices]


def _make_label(terms: list[str]) -> str:
    """Turn a list of top terms into a readable cluster label."""
    if not terms:
        return "misc"
    # Take the first 3 terms; strip stopwords that leak through
    _STOP = {"and", "the", "for", "with", "from", "that", "this", "are", "has"}
    filtered = [t for t in terms if t.lower() not in _STOP][:3]
    return " / ".join(filtered) if filtered else terms[0]


def build_sector_clusters(
    df: pd.DataFrame,
    n_clusters: int = 12,
) -> pd.DataFrame:
    """
    Cluster companies by description similarity using TF-IDF + K-Means.

    Attempts to reuse the pre-built TF-IDF corpus from
    enrichment.tfidf_extractor; falls back to building a standalone vectorizer
    from the input DataFrame if the module is unavailable.

    Args:
        df:         DataFrame containing at least 'about' and/or 'full_description'.
        n_clusters: Number of K-Means clusters (default 12).

    Returns:
        A copy of *df* with two new columns:
          - cluster_id:    int, zero-based cluster index
          - cluster_label: str, auto-named from top-5 centroid terms
    """
    if df.empty:
        logger.warning("build_sector_clusters: empty DataFrame, nothing to cluster.")
        df = df.copy()
        df["cluster_id"] = pd.Series(dtype=int)
        df["cluster_label"] = pd.Series(dtype=str)
        return df

    # Build per-row document texts
    texts = df.apply(_row_to_text, axis=1).fillna("").tolist()

    # ── Try to reuse the corpus vectorizer from enrichment ───────────────────
    vectorizer: Optional[TfidfVectorizer] = None
    matrix = None

    try:
        from enrichment.tfidf_extractor import _load_vectorizer  # type: ignore

        existing_vectorizer, _, _ = _load_vectorizer()
        # Transform the *input* texts through the existing vocabulary
        matrix = existing_vectorizer.transform(texts)
        vectorizer = existing_vectorizer
        logger.info("Using pre-built TF-IDF corpus vectorizer from enrichment.tfidf_extractor")
    except Exception as exc:
        logger.info(
            "Could not reuse enrichment vectorizer (%s); building standalone.", exc
        )

    # ── Fallback: standalone vectorizer from the input DataFrame ────────────
    if vectorizer is None or matrix is None:
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=max(1, len(texts) // 100),   # ignore terms in < 1% of docs
            max_df=0.85,
            max_features=30_000,
            sublinear_tf=True,
            strip_accents="unicode",
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_\-\.]{1,}\b",
        )
        matrix = vectorizer.fit_transform(texts)
        logger.info(
            "Standalone TF-IDF built: %d docs, %d features",
            matrix.shape[0],
            matrix.shape[1],
        )

    # Ensure we don't request more clusters than documents
    effective_clusters = min(n_clusters, len(texts))
    if effective_clusters < 2:
        logger.warning("Too few documents (%d) for clustering.", len(texts))
        df = df.copy()
        df["cluster_id"] = 0
        df["cluster_label"] = "all"
        return df

    # ── K-Means clustering ───────────────────────────────────────────────────
    kmeans = KMeans(
        n_clusters=effective_clusters,
        random_state=42,
        n_init=10,
        max_iter=300,
    )
    labels = kmeans.fit_predict(matrix)

    # ── Auto-name each cluster from centroid top terms ───────────────────────
    cluster_labels: dict[int, str] = {}
    for cid in range(effective_clusters):
        terms = get_cluster_top_terms(vectorizer, kmeans, cid, top_n=5)
        cluster_labels[cid] = _make_label(terms)
        logger.debug("Cluster %d (%s): %s", cid, cluster_labels[cid], terms)

    df = df.copy()
    df["cluster_id"] = labels
    df["cluster_label"] = [cluster_labels[lbl] for lbl in labels]

    logger.info(
        "Clustering complete: %d companies → %d clusters",
        len(df),
        effective_clusters,
    )
    return df
