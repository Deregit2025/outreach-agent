"""
ai_maturity_scorer.py — Score a company's AI/ML maturity on a 0–3 scale.

Signal sources (in order of weight):
  1. Tech stack: known AI/ML tool names from Crunchbase technology_highlights
  2. Leadership hires: AI/ML-titled executives from Crunchbase people events
  3. TF-IDF signals: statistically significant AI terms in full_description/about
  4. Topic modeling: NMF topic distribution — weight in AI-themed topics
  5. Description keywords: fallback keyword match on about/full_description
  6. Industry classification: Crunchbase industry labels

The TF-IDF and topic signals replace the brittle single-keyword approach for
description and industry scoring — they are data-driven and will capture terms
like "llmops", "agentic systems", "retrieval augmented generation" without
requiring manual list maintenance.
"""

from __future__ import annotations

import logging

from enrichment.schemas.prospect import TechEntry, LeadershipEvent

logger = logging.getLogger(__name__)

AI_TOOLS: set[str] = {
    "databricks", "snowflake", "weights & biases", "wandb",
    "ray", "vllm", "mlflow", "sagemaker", "vertex ai",
    "huggingface", "pinecone", "weaviate", "chroma", "qdrant",
    "dbt", "great expectations", "feast", "tecton", "bentoml",
    "seldon", "triton inference", "onnx", "kubeflow", "metaflow",
    "langchain", "llamaindex", "openai", "anthropic", "cohere",
    "mistral", "together ai", "replicate",
}

AI_LEADERSHIP_KEYWORDS: set[str] = {
    "chief ai", "head of ai", "vp data", "chief scientist",
    "chief data officer", "cdo", "ml engineer", "ai engineer",
    "applied scientist", "research scientist", "llm", "machine learning",
    "head of machine learning", "director of ai", "vp of ai",
    "director of machine learning", "ai lead", "ml lead",
}

_DESCRIPTION_KEYWORDS: set[str] = {
    "ai", "machine learning", "llm", "ml", "deep learning",
    "neural network", "generative ai", "genai", "nlp", "computer vision",
    "data science", "predictive", "recommendation system",
}

_AI_INDUSTRY_KEYWORDS: set[str] = {
    "artificial intelligence", "machine learning", "data analytics",
    "deep learning", "computer vision", "natural language processing",
    "data science", "mlops", "ai infrastructure",
}

_RAW_TO_SCORE: dict[int, int] = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3, 6: 3}


def score_ai_maturity(
    tech_stack: list[TechEntry],
    leadership_hires: list[LeadershipEvent],
    industries: list[str],
    description: str,
    full_description: str = "",
    technology_highlights_raw: str = "",
) -> tuple[int, str, list[str]]:
    """
    Score AI maturity using rule-based + TF-IDF + topic signals.

    Returns:
        (score 0–3, confidence "high"/"medium"/"low", justification list)
    """
    justification: list[str] = []

    # ── Signal 1: Known AI tools in tech stack ────────────────────────────────
    matched_tools = [
        entry.name
        for entry in tech_stack
        if entry.name.lower() in AI_TOOLS
    ]
    tool_count = len(matched_tools)
    if tool_count == 0:
        tech_score = 0
    elif tool_count == 1:
        tech_score = 1
        justification.append(f"AI tool detected: {matched_tools[0]}")
    else:
        tech_score = 2
        justification.append(f"Multiple AI tools: {', '.join(matched_tools[:5])}")

    # ── Signal 2: AI/ML leadership hire ──────────────────────────────────────
    leadership_score = 0
    for hire in leadership_hires:
        label_lower = hire.label.lower()
        if any(kw in label_lower for kw in AI_LEADERSHIP_KEYWORDS):
            leadership_score = 2
            justification.append(f"AI leadership hire: {hire.label}")
            break

    # ── Signal 3: TF-IDF — statistically significant AI terms ────────────────
    tfidf_score = 0
    tfidf_ai_terms: list[str] = []
    try:
        from enrichment.tfidf_extractor import extract_tfidf, build_company_text
        company_text = build_company_text(
            about=description or "",
            full_description=full_description or "",
            technology_highlights=technology_highlights_raw or "",
        )
        if company_text.strip():
            result = extract_tfidf(company_text)
            tfidf_ai_terms = result["ai_signal_terms"]
            ai_sig_score = result["ai_signal_score"]
            if ai_sig_score >= 0.30:
                tfidf_score = 2
                justification.append(
                    f"TF-IDF AI signals (score={ai_sig_score:.2f}): "
                    f"{', '.join(tfidf_ai_terms[:5])}"
                )
            elif ai_sig_score >= 0.10:
                tfidf_score = 1
                justification.append(
                    f"TF-IDF weak AI signal (score={ai_sig_score:.2f}): "
                    f"{', '.join(tfidf_ai_terms[:3])}"
                )
    except Exception as exc:
        logger.debug("TF-IDF scoring skipped: %s", exc)

    # ── Signal 4: Topic modeling — weight in AI-themed latent topics ──────────
    topic_score = 0
    try:
        from enrichment.topic_modeler import get_topic_distribution, _load_vectorizer
        # Reuse the text built above if available, else rebuild
        if "company_text" not in dir():
            from enrichment.tfidf_extractor import build_company_text
            company_text = build_company_text(
                about=description or "",
                full_description=full_description or "",
                technology_highlights=technology_highlights_raw or "",
            )
        topic_result = get_topic_distribution(company_text)
        ai_topic_score = topic_result["ai_topic_score"]
        if ai_topic_score >= 0.35:
            topic_score = 2
            justification.append(
                f"Topic model: strong AI theme "
                f"(ai_topic_weight={ai_topic_score:.2f}, "
                f"dominant='{topic_result['dominant_topic_label']}')"
            )
        elif ai_topic_score >= 0.15:
            topic_score = 1
            justification.append(
                f"Topic model: moderate AI theme (weight={ai_topic_score:.2f})"
            )
    except Exception as exc:
        logger.debug("Topic modeling skipped: %s", exc)

    # ── Signal 5: Fallback keyword match on description ───────────────────────
    desc_lower = (description or "").lower() + " " + (full_description or "").lower()
    description_score = 0
    if tfidf_score == 0 and topic_score == 0:
        # Only use keyword fallback if TF-IDF/topic didn't fire
        matched_desc = [kw for kw in _DESCRIPTION_KEYWORDS if kw in desc_lower]
        if matched_desc:
            description_score = 1
            justification.append(f"Keyword match in description: {', '.join(matched_desc[:4])}")

    # ── Signal 6: Industry label ──────────────────────────────────────────────
    industry_score = 0
    matched_industries = [
        ind for ind in industries
        if any(kw in ind.lower() for kw in _AI_INDUSTRY_KEYWORDS)
    ]
    if matched_industries:
        industry_score = 1
        justification.append(f"AI-adjacent industry: {', '.join(matched_industries)}")

    # ── Aggregate ─────────────────────────────────────────────────────────────
    # Use the best of (tfidf_score OR description_score) to avoid double-counting
    text_score = max(tfidf_score, description_score)
    raw_total = tech_score + leadership_score + text_score + topic_score + industry_score
    score = _RAW_TO_SCORE.get(min(raw_total, 6), 3)

    signal_count = sum([
        1 if tech_score > 0 else 0,
        1 if leadership_score > 0 else 0,
        1 if text_score > 0 else 0,
        1 if topic_score > 0 else 0,
        1 if industry_score > 0 else 0,
    ])
    if signal_count >= 3:
        confidence = "high"
    elif signal_count >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    return score, confidence, justification
