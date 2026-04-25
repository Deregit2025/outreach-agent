"""
tfidf_extractor.py — Statistically-grounded term extraction from company text.

Builds a TF-IDF corpus model over the full 1,513-company Crunchbase dataset
(full_description + about + technology_highlights) once at import time, then
scores individual company documents against that corpus.

Why TF-IDF over hardcoded keywords:
  - Terms like "mlops", "llmops", "agentic", "rag pipeline" are not in any
    hardcoded list but become statistically significant when they appear in a
    company description while being rare across the corpus.
  - Allows the AI maturity scorer to discover novel signals without manual updates.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRUNCHBASE_CSV = PROJECT_ROOT / "data" / "raw" / "crunchbase_odm_sample.csv"

# Terms that reliably signal AI / ML work when they appear in company text
AI_SIGNAL_TERMS: set[str] = {
    "machine learning", "deep learning", "neural network", "nlp",
    "natural language", "computer vision", "reinforcement learning",
    "llm", "large language model", "generative ai", "genai", "gpt",
    "transformer", "bert", "diffusion", "stable diffusion",
    "mlops", "llmops", "mlflow", "kubeflow", "ray", "vllm",
    "vector database", "embedding", "rag", "retrieval augmented",
    "databricks", "snowflake", "sagemaker", "vertex ai", "huggingface",
    "pinecone", "weaviate", "chroma", "qdrant", "faiss",
    "data science", "data scientist", "data engineer", "analytics engineer",
    "ai platform", "ai infrastructure", "model serving", "feature store",
    "a/b testing framework", "experimentation platform",
    "recommendation system", "search relevance", "anomaly detection",
    "forecasting", "predictive", "classification", "segmentation",
}


class TFIDFResult(TypedDict):
    top_terms: list[str]
    top_scores: list[float]
    ai_signal_score: float      # 0.0–1.0, fraction of AI terms in top-20
    ai_signal_terms: list[str]  # which AI terms fired
    corpus_percentile: float    # where this doc sits in the TF-IDF score dist


def _build_corpus_text(row: pd.Series) -> str:
    """Combine text fields into a single document for TF-IDF."""
    parts: list[str] = []
    for col in ("full_description", "about", "technology_highlights",
                "overview_highlights", "people_highlights"):
        val = row.get(col, "")
        if isinstance(val, str) and val.strip():
            # technology_highlights may be a JSON array string
            if col == "technology_highlights" and val.startswith("["):
                try:
                    items = json.loads(val)
                    if isinstance(items, list):
                        val = " ".join(
                            str(item.get("name", "")) if isinstance(item, dict) else str(item)
                            for item in items
                        )
                except Exception:
                    pass
            parts.append(val.strip())
    return " ".join(parts)


@lru_cache(maxsize=1)
def _load_vectorizer() -> tuple[TfidfVectorizer, np.ndarray, list[str]]:
    """
    Load Crunchbase CSV, build TF-IDF model. Cached — runs once per process.
    Returns (vectorizer, tfidf_matrix, company_names).
    """
    if not CRUNCHBASE_CSV.exists():
        raise FileNotFoundError(f"Crunchbase CSV not found: {CRUNCHBASE_CSV}")

    df = pd.read_csv(CRUNCHBASE_CSV, low_memory=False)
    corpus = df.apply(_build_corpus_text, axis=1).fillna("").tolist()
    names = df["name"].fillna("").astype(str).tolist()

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 3),        # unigrams + bigrams + trigrams
        min_df=1,                  # keep rare specialist terms (mlops, vllm, etc.)
        max_df=0.85,               # ignore terms in >85% of docs (too common)
        max_features=60000,        # cap vocab for memory efficiency
        sublinear_tf=True,         # log(1 + tf) scaling
        strip_accents="unicode",
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_\-\.]{1,}\b",
    )
    matrix = vectorizer.fit_transform(corpus)
    logger.info("TF-IDF corpus built: %d docs, %d features", len(corpus), len(vectorizer.vocabulary_))
    return vectorizer, matrix, names


def extract_tfidf(
    company_text: str,
    top_k: int = 20,
) -> TFIDFResult:
    """
    Score a single company document against the corpus vocabulary.

    Args:
        company_text: Concatenated text for the company (full_description + about + tech)
        top_k: Number of top terms to return

    Returns:
        TFIDFResult with top terms, AI signal score, and corpus percentile
    """
    if not company_text.strip():
        return TFIDFResult(
            top_terms=[], top_scores=[], ai_signal_score=0.0,
            ai_signal_terms=[], corpus_percentile=0.0,
        )

    try:
        vectorizer, matrix, _ = _load_vectorizer()
    except FileNotFoundError:
        logger.warning("Crunchbase CSV missing — TF-IDF disabled")
        return TFIDFResult(
            top_terms=[], top_scores=[], ai_signal_score=0.0,
            ai_signal_terms=[], corpus_percentile=0.0,
        )

    doc_vec = vectorizer.transform([company_text])
    feature_names = vectorizer.get_feature_names_out()

    # Get top-k terms by TF-IDF weight
    scores = doc_vec.toarray()[0]
    top_indices = scores.argsort()[::-1][:top_k]
    top_terms = [feature_names[i] for i in top_indices if scores[i] > 0]
    top_scores_list = [round(float(scores[i]), 4) for i in top_indices if scores[i] > 0]

    # Identify AI-signal terms in top-k using bidirectional substring matching:
    #   "mlops" matches AI term "mlops" (exact)
    #   "machine learning models" matches AI term "machine learning" (AI kw ⊂ top term)
    #   "model" matches AI term "model serving" (top term ⊂ AI kw)
    ai_terms_found = [
        t for t in top_terms
        if t.lower() in AI_SIGNAL_TERMS
        or any(ai_kw in t.lower() for ai_kw in AI_SIGNAL_TERMS)
        or any(t.lower() in ai_kw for ai_kw in AI_SIGNAL_TERMS)
    ]
    ai_signal_score = round(len(ai_terms_found) / max(len(top_terms), 1), 3)

    # Corpus percentile: what fraction of docs have a lower max TF-IDF score
    doc_max = float(scores.max()) if scores.max() > 0 else 0.0
    corpus_max_scores = np.asarray(matrix.max(axis=1).todense()).flatten()
    percentile = float(np.mean(corpus_max_scores < doc_max))

    return TFIDFResult(
        top_terms=top_terms[:top_k],
        top_scores=top_scores_list[:top_k],
        ai_signal_score=ai_signal_score,
        ai_signal_terms=ai_terms_found,
        corpus_percentile=round(percentile, 3),
    )


def build_company_text(
    about: str = "",
    full_description: str = "",
    technology_highlights: str | list = "",
) -> str:
    """Helper to assemble company text from individual fields."""
    parts: list[str] = []
    if about:
        parts.append(about.strip())
    if full_description:
        parts.append(full_description.strip())
    if isinstance(technology_highlights, list):
        tech_str = " ".join(
            item.get("name", "") if isinstance(item, dict) else str(item)
            for item in technology_highlights
        )
        if tech_str.strip():
            parts.append(tech_str.strip())
    elif isinstance(technology_highlights, str) and technology_highlights.strip():
        if technology_highlights.startswith("["):
            try:
                items = json.loads(technology_highlights)
                tech_str = " ".join(
                    item.get("name", "") if isinstance(item, dict) else str(item)
                    for item in items
                )
                parts.append(tech_str)
            except Exception:
                parts.append(technology_highlights)
        else:
            parts.append(technology_highlights)
    return " ".join(parts)
