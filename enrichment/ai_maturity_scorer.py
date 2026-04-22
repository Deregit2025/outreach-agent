from __future__ import annotations

from enrichment.schemas.prospect import TechEntry, LeadershipEvent

AI_TOOLS: set[str] = {
    "databricks",
    "snowflake",
    "weights & biases",
    "ray",
    "vllm",
    "mlflow",
    "sagemaker",
    "vertex ai",
    "huggingface",
    "pinecone",
    "weaviate",
    "dbt",
}

AI_LEADERSHIP_KEYWORDS: set[str] = {
    "chief ai",
    "head of ai",
    "vp data",
    "chief scientist",
    "ml engineer",
    "ai engineer",
    "applied scientist",
    "llm",
    "machine learning",
}

_DESCRIPTION_KEYWORDS: set[str] = {"ai", "machine learning", "llm", "ml"}
_AI_INDUSTRY_KEYWORDS: set[str] = {"artificial intelligence", "machine learning", "data analytics", "deep learning"}

_RAW_TO_SCORE: dict[int, int] = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3}


def score_ai_maturity(
    tech_stack: list[TechEntry],
    leadership_hires: list[LeadershipEvent],
    industries: list[str],
    description: str,
) -> tuple[int, str, list[str]]:
    justification: list[str] = []

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
        justification.append(f"Multiple AI tools detected: {', '.join(matched_tools[:5])}")

    leadership_score = 0
    for hire in leadership_hires:
        label_lower = hire.label.lower()
        if any(kw in label_lower for kw in AI_LEADERSHIP_KEYWORDS):
            leadership_score = 2
            justification.append(f"AI leadership hire: {hire.label}")
            break

    desc_lower = (description or "").lower()
    description_score = 0
    matched_desc = [kw for kw in _DESCRIPTION_KEYWORDS if kw in desc_lower]
    if matched_desc:
        description_score = 1
        justification.append(f"Description contains AI keywords: {', '.join(matched_desc)}")

    industry_score = 0
    matched_industries = [
        ind for ind in industries
        if any(kw in ind.lower() for kw in _AI_INDUSTRY_KEYWORDS)
    ]
    if matched_industries:
        industry_score = 1
        justification.append(f"AI-adjacent industry: {', '.join(matched_industries)}")

    raw_total = tech_score + leadership_score + description_score + industry_score
    score = _RAW_TO_SCORE.get(min(raw_total, 5), 3)

    signal_count = sum([
        1 if tech_score > 0 else 0,
        1 if leadership_score > 0 else 0,
        1 if description_score > 0 else 0,
        1 if industry_score > 0 else 0,
    ])
    if signal_count >= 2:
        confidence = "high"
    elif signal_count == 1:
        confidence = "medium"
    else:
        confidence = "low"

    return score, confidence, justification
