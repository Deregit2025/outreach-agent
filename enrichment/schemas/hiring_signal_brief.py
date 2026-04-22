from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class SignalItem(BaseModel):
    signal_type: str
    value: str
    evidence: str
    confidence: str            # high / medium / low
    data_age_days: Optional[int] = None
    language_register: str = "ask"   # assert / hedge / ask


class HiringSignalBrief(BaseModel):
    prospect_id: str
    company_name: str
    generated_at: str

    funding: Optional[SignalItem] = None
    job_velocity: Optional[SignalItem] = None
    layoff: Optional[SignalItem] = None
    leadership_change: Optional[SignalItem] = None
    tech_stack: Optional[SignalItem] = None
    ai_maturity: Optional[SignalItem] = None

    recommended_segment: Optional[int] = None
    segment_confidence: str = "low"
    pitch_language_ai: str = "low_readiness"
    brief_summary: str = ""

    def all_signals(self) -> list[SignalItem]:
        return [
            s for s in [
                self.funding, self.job_velocity, self.layoff,
                self.leadership_change, self.tech_stack, self.ai_maturity,
            ]
            if s is not None
        ]
