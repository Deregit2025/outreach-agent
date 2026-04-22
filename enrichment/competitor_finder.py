from __future__ import annotations

import statistics
from datetime import datetime, timezone

from enrichment.schemas.prospect import Prospect
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief
from enrichment.schemas.competitor_gap_brief import (
    CompetitorGapBrief,
    CompetitorProfile,
    CapabilityGap,
)
from enrichment.crunchbase_lookup import (
    get_companies_by_industry,
    parse_tech_stack,
    parse_leadership_hires,
    parse_industries,
)
from enrichment.ai_maturity_scorer import score_ai_maturity

_CAPABILITY_LABELS: dict[str, str] = {
    "databricks": "Databricks (unified analytics)",
    "snowflake": "Snowflake (cloud data warehouse)",
    "mlflow": "MLflow (experiment tracking)",
    "sagemaker": "SageMaker (ML platform)",
    "vertex ai": "Vertex AI (Google ML platform)",
    "huggingface": "HuggingFace (model hub)",
    "pinecone": "Pinecone (vector search)",
    "weaviate": "Weaviate (vector database)",
    "weights & biases": "Weights & Biases (ML observability)",
    "ray": "Ray (distributed ML)",
    "vllm": "vLLM (inference serving)",
    "dbt": "dbt (data transformation)",
}


def find_peers(prospect: Prospect, limit: int = 8) -> list[dict]:
    if not prospect.industries:
        return []
    primary_industry = prospect.industries[0]
    candidates = get_companies_by_industry(primary_industry, limit=limit + 10)
    peers = [
        row for row in candidates
        if str(row.get("name", "")).strip().lower() != prospect.company_name.strip().lower()
    ]
    return peers[:limit]


def build_competitor_gap_brief(
    prospect: Prospect,
    brief: HiringSignalBrief,
    peers_raw: list[dict],
) -> CompetitorGapBrief:
    generated_at = datetime.now(timezone.utc).isoformat()
    sector = prospect.industries[0] if prospect.industries else "Unknown"

    prospect_score = prospect.ai_maturity_score or 0
    prospect_confidence = prospect.ai_maturity_confidence or "low"

    peer_profiles: list[CompetitorProfile] = []
    peer_scores: list[int] = []

    for row in peers_raw:
        tech = parse_tech_stack(row)
        hires = parse_leadership_hires(row)
        inds = parse_industries(row)
        desc = str(row.get("about", "") or "")
        p_score, p_conf, p_just = score_ai_maturity(tech, hires, inds, desc)
        peer_scores.append(p_score)
        peer_profiles.append(
            CompetitorProfile(
                company_name=str(row.get("name", "")),
                ai_maturity_score=p_score,
                ai_maturity_confidence=p_conf,
                key_signals=p_just,
            )
        )

    if peer_scores:
        sector_mean = statistics.mean(peer_scores)
        sorted_scores = sorted(peer_scores)
        q3_index = max(0, len(sorted_scores) - len(sorted_scores) // 4 - 1)
        sector_top_quartile = float(sorted_scores[q3_index])
        scores_at_or_below = sum(1 for s in peer_scores if s <= prospect_score)
        prospect_percentile = round((scores_at_or_below / len(peer_scores)) * 100, 1)
    else:
        sector_mean = 0.0
        sector_top_quartile = 0.0
        prospect_percentile = None

    prospect_ai_evidence = brief.ai_maturity.evidence if brief.ai_maturity else ""

    gaps: list[CapabilityGap] = []
    if peer_profiles and sector_top_quartile >= 2 and prospect_score <= 1:
        top_quartile_profiles = [p for p in peer_profiles if p.ai_maturity_score >= 2]
        tool_counts: dict[str, int] = {}
        for profile in top_quartile_profiles:
            for signal in profile.key_signals:
                signal_lower = signal.lower()
                for tool_key in _CAPABILITY_LABELS:
                    if tool_key in signal_lower:
                        tool_counts[tool_key] = tool_counts.get(tool_key, 0) + 1

        top_gaps = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        for tool_key, count in top_gaps:
            label = _CAPABILITY_LABELS.get(tool_key, tool_key)
            framing = (
                f"{count} of {len(top_quartile_profiles)} peer companies in {sector} "
                f"are running {label} — {prospect.company_name} isn't showing that signal yet"
            )
            evidence = f"Detected in {count} top-quartile peers"
            if prospect_ai_evidence:
                evidence += f"; prospect signal: {prospect_ai_evidence}"
            gaps.append(
                CapabilityGap(
                    capability=label,
                    quartile_count=count,
                    evidence=evidence,
                    framing=framing,
                )
            )

    gap_hook = gaps[0].framing if gaps else (
        f"{prospect.company_name} appears behind peers in {sector} on AI tooling adoption"
    )

    return CompetitorGapBrief(
        prospect_id=prospect.prospect_id,
        company_name=prospect.company_name,
        sector=sector,
        generated_at=generated_at,
        prospect_ai_score=prospect_score,
        prospect_ai_confidence=prospect_confidence,
        peers=peer_profiles,
        sector_mean_score=round(sector_mean, 2),
        sector_top_quartile_score=sector_top_quartile,
        prospect_percentile=prospect_percentile,
        gaps=gaps,
        gap_hook=gap_hook,
    )
