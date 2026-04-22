from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class FundingRound(BaseModel):
    announced_on: Optional[str] = None
    title: Optional[str] = None
    uuid: Optional[str] = None
    amount_usd: Optional[float] = None
    series: Optional[str] = None


class LeadershipEvent(BaseModel):
    key_event_date: Optional[str] = None
    label: str
    link: Optional[str] = None
    uuid: Optional[str] = None


class LayoffEvent(BaseModel):
    key_event_date: Optional[str] = None
    label: str
    link: Optional[str] = None
    uuid: Optional[str] = None


class TechEntry(BaseModel):
    name: str
    technology_category: list[str] = Field(default_factory=list)


class Prospect(BaseModel):
    prospect_id: str
    crunchbase_id: Optional[str] = None

    company_name: str
    website: Optional[str] = None
    industries: list[str] = Field(default_factory=list)
    country_code: Optional[str] = None
    region: Optional[str] = None
    employee_count_raw: Optional[str] = None
    employee_count_min: Optional[int] = None
    employee_count_max: Optional[int] = None
    description: Optional[str] = None

    # Synthetic contact — never a real person
    contact_first_name: Optional[str] = None
    contact_last_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_title: Optional[str] = None
    contact_phone: Optional[str] = None

    funding_rounds: list[FundingRound] = Field(default_factory=list)
    leadership_hires: list[LeadershipEvent] = Field(default_factory=list)
    layoff_events: list[LayoffEvent] = Field(default_factory=list)
    tech_stack: list[TechEntry] = Field(default_factory=list)

    icp_segment: Optional[int] = None
    icp_confidence: Optional[str] = None
    ai_maturity_score: Optional[int] = None
    ai_maturity_confidence: Optional[str] = None

    thread_status: str = "new"
    channel: str = "email"
    last_enriched_at: Optional[str] = None
