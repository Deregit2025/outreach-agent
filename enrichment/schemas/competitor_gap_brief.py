from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class CompetitorProfile(BaseModel):
    company_name: str
    ai_maturity_score: int
    ai_maturity_confidence: str
    key_signals: list[str] = Field(default_factory=list)


class CapabilityGap(BaseModel):
    capability: str
    quartile_count: int
    evidence: str
    framing: str   # non-condescending hook for the agent to use


class CompetitorGapBrief(BaseModel):
    prospect_id: str
    company_name: str
    sector: str
    generated_at: str

    prospect_ai_score: int
    prospect_ai_confidence: str

    peers: list[CompetitorProfile] = Field(default_factory=list)

    sector_mean_score: float = 0.0
    sector_top_quartile_score: float = 0.0
    prospect_percentile: Optional[float] = None

    gaps: list[CapabilityGap] = Field(default_factory=list)
    gap_hook: str = ""
