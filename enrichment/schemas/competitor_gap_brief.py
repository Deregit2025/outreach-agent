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
    # Free-text summary of the gap (used in email framing)
    evidence: str
    # Specific public evidence items — each must cite a source or observable fact
    public_evidence: list[str] = Field(default_factory=list)
    framing: str   # non-condescending hook for the agent to use


class CompetitorGapBrief(BaseModel):
    prospect_id: str
    company_name: str
    sector: str
    generated_at: str

    prospect_ai_score: int
    prospect_ai_confidence: str

    # Number of sector peers found — drives sparse-sector warnings
    peers_found: int = 0
    # True when fewer than 5 sector peers were available (reduces gap confidence)
    sparse_sector: bool = False

    peers: list[CompetitorProfile] = Field(default_factory=list)

    sector_mean_score: float = 0.0
    sector_top_quartile_score: float = 0.0
    # Prospect's percentile rank within the sector peer set (0–100)
    prospect_percentile: Optional[float] = None

    # Documented criteria used to select "top quartile" peers
    top_quartile_criteria: list[str] = Field(default_factory=list)

    gaps: list[CapabilityGap] = Field(default_factory=list)
    gap_hook: str = ""
