"""
topic_modeler.py — Latent topic modeling over the Crunchbase company corpus.

Uses Non-negative Matrix Factorization (NMF) on the TF-IDF matrix produced by
tfidf_extractor.py.  NMF is preferred over LDA here because:
  - Faster and more interpretable on short-to-medium company descriptions
  - Topics have crisp, additive structure (no negative weights)
  - Works well even when many docs are sparse (empty descriptions)

The 8 topics discovered map naturally to Tenacious ICP signals:
  Topic 0: AI / ML platforms          ← Segment 4 indicator
  Topic 1: Data engineering / analytics ← AI maturity signal
  Topic 2: SaaS / B2B software        ← general software
  Topic 3: Fintech / payments         ← sector
  Topic 4: E-commerce / retail        ← sector
  Topic 5: Infrastructure / DevOps    ← tech stack signal
  Topic 6: Healthcare / biotech       ← sector
  Topic 7: Traditional / services     ← low AI signal

In practice, the topic names above are derived from the top terms found during
fit and are labeled heuristically. The important outputs for downstream use are:
  - dominant_topic (int 0–7)
  - ai_topic_score (float 0–1): weight in AI/ML topics (0, 1)
  - topic_distribution (list[float]): full 8-dim distribution
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TypedDict

import numpy as np
from sklearn.decomposition import NMF

from enrichment.tfidf_extractor import _load_vectorizer

logger = logging.getLogger(__name__)

N_TOPICS = 8
N_TOP_WORDS = 12

# Topic indices that represent AI / ML / Data themes
# Determined empirically by inspecting top words — may shift slightly
# depending on corpus version; we identify them at fit time.
_AI_TOPIC_KEYWORDS = {
    "machine learning", "deep learning", "neural", "nlp", "ai platform",
    "data science", "mlops", "llm", "generative", "vector", "embedding",
    "model", "prediction", "analytics engine", "recommendation",
}


class TopicResult(TypedDict):
    dominant_topic: int
    dominant_topic_label: str
    ai_topic_score: float       # summed weight across AI-themed topics (0–1)
    topic_distribution: list[float]   # 8 values summing to ~1.0
    top_words_per_topic: list[list[str]]  # 8 × N_TOP_WORDS


def _identify_ai_topics(
    feature_names: np.ndarray,
    components: np.ndarray,
) -> set[int]:
    """Return the set of topic indices whose top-12 words overlap AI keywords."""
    ai_topics: set[int] = set()
    for idx, topic_vec in enumerate(components):
        top_idx = topic_vec.argsort()[::-1][:N_TOP_WORDS]
        top_words = {feature_names[i].lower() for i in top_idx}
        if top_words & _AI_TOPIC_KEYWORDS:
            ai_topics.add(idx)
    return ai_topics


@lru_cache(maxsize=1)
def _load_nmf() -> tuple[NMF, np.ndarray, np.ndarray, set[int], list[list[str]]]:
    """
    Fit NMF on the TF-IDF corpus matrix. Cached — runs once per process.
    Returns (model, W_corpus, feature_names, ai_topic_indices, top_words_per_topic).
    """
    vectorizer, matrix, _ = _load_vectorizer()
    feature_names = vectorizer.get_feature_names_out()

    nmf = NMF(
        n_components=N_TOPICS,
        random_state=42,
        max_iter=400,
        l1_ratio=0.1,
    )
    W = nmf.fit_transform(matrix)  # shape: (n_docs, N_TOPICS)
    H = nmf.components_            # shape: (N_TOPICS, n_features)

    # Build human-readable top-words per topic
    top_words_per_topic: list[list[str]] = []
    for topic_vec in H:
        top_idx = topic_vec.argsort()[::-1][:N_TOP_WORDS]
        top_words_per_topic.append([str(feature_names[i]) for i in top_idx])

    ai_topics = _identify_ai_topics(feature_names, H)
    logger.info(
        "NMF fit complete: %d topics, AI-themed topics: %s",
        N_TOPICS, sorted(ai_topics),
    )
    return nmf, W, feature_names, ai_topics, top_words_per_topic


def get_topic_distribution(company_text: str) -> TopicResult:
    """
    Infer topic distribution for a single company document.

    Args:
        company_text: Combined company description text

    Returns:
        TopicResult with dominant topic, AI score, and full distribution
    """
    empty_result = TopicResult(
        dominant_topic=7,
        dominant_topic_label="unknown",
        ai_topic_score=0.0,
        topic_distribution=[0.0] * N_TOPICS,
        top_words_per_topic=[[] for _ in range(N_TOPICS)],
    )

    if not company_text.strip():
        return empty_result

    try:
        nmf, _, feature_names, ai_topics, top_words = _load_nmf()
        vectorizer, _, _ = _load_vectorizer()
    except Exception as exc:
        logger.warning("Topic modeling unavailable: %s", exc)
        return empty_result

    doc_vec = vectorizer.transform([company_text])
    W_doc = nmf.transform(doc_vec)[0]  # shape: (N_TOPICS,)

    # Normalize to [0,1] distribution
    total = W_doc.sum()
    if total > 0:
        dist = (W_doc / total).tolist()
    else:
        dist = [1.0 / N_TOPICS] * N_TOPICS

    dominant = int(np.argmax(W_doc))
    dominant_words = top_words[dominant][:5] if top_words else []
    dominant_label = ", ".join(dominant_words) if dominant_words else f"topic_{dominant}"

    # AI score = sum of weights for AI-themed topics
    ai_score = round(sum(dist[i] for i in ai_topics), 4)

    return TopicResult(
        dominant_topic=dominant,
        dominant_topic_label=dominant_label,
        ai_topic_score=ai_score,
        topic_distribution=[round(v, 4) for v in dist],
        top_words_per_topic=top_words,
    )
