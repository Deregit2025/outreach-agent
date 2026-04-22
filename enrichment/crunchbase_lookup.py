from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from enrichment.schemas.prospect import (
    FundingRound,
    LeadershipEvent,
    LayoffEvent,
    TechEntry,
)

_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "crunchbase_odm_sample.csv"

_df: pd.DataFrame = pd.read_csv(_CSV_PATH, encoding="utf-8")
_df_lower_name: pd.Series = _df["name"].str.strip().str.lower()


def lookup_by_name(company_name: str) -> dict | None:
    needle = company_name.strip().lower()
    mask = _df_lower_name == needle
    if not mask.any():
        return None
    return _df[mask].iloc[0].to_dict()


def lookup_by_id(uuid: str) -> dict | None:
    mask = _df["uuid"] == uuid
    if not mask.any():
        return None
    return _df[mask].iloc[0].to_dict()


def get_companies_by_industry(industry_keyword: str, limit: int = 20) -> list[dict]:
    keyword_lower = industry_keyword.lower()

    def _matches(cell) -> bool:
        if not isinstance(cell, str) or not cell.strip():
            return False
        try:
            items = json.loads(cell)
            return any(keyword_lower in str(item.get("value", "")).lower() for item in items)
        except (json.JSONDecodeError, AttributeError):
            return False

    mask = _df["industries"].apply(_matches)
    return _df[mask].head(limit).to_dict(orient="records")


def _safe_json(cell) -> list:
    if not isinstance(cell, str) or not cell.strip():
        return []
    try:
        result = json.loads(cell)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def parse_funding_rounds(row: dict) -> list[FundingRound]:
    rounds = []
    for item in _safe_json(row.get("funding_rounds_list")):
        rounds.append(
            FundingRound(
                announced_on=item.get("announced_on"),
                title=item.get("title"),
                uuid=item.get("uuid"),
            )
        )
    return rounds


def parse_leadership_hires(row: dict) -> list[LeadershipEvent]:
    hires = []
    for item in _safe_json(row.get("leadership_hire")):
        hires.append(
            LeadershipEvent(
                key_event_date=item.get("key_event_date"),
                label=item.get("label", ""),
                link=item.get("link"),
                uuid=item.get("uuid"),
            )
        )
    return hires


def parse_layoff_events(row: dict) -> list[LayoffEvent]:
    events = []
    for item in _safe_json(row.get("layoff")):
        events.append(
            LayoffEvent(
                key_event_date=item.get("key_event_date"),
                label=item.get("label", ""),
                link=item.get("link"),
                uuid=item.get("uuid"),
            )
        )
    return events


def parse_tech_stack(row: dict) -> list[TechEntry]:
    entries = []
    for item in _safe_json(row.get("builtwith_tech")):
        name = item.get("name", "")
        categories = item.get("technology_category", [])
        if isinstance(categories, str):
            categories = [categories]
        entries.append(TechEntry(name=name, technology_category=categories))
    return entries


def parse_employee_range(row: dict) -> tuple[int | None, int | None]:
    raw = row.get("num_employees", "")
    if not isinstance(raw, str) or not raw.strip():
        return (None, None)
    raw = raw.strip()
    if raw.endswith("+"):
        try:
            return (int(raw[:-1]), None)
        except ValueError:
            return (None, None)
    if "-" in raw:
        parts = raw.split("-", 1)
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return (None, None)
    try:
        val = int(raw)
        return (val, val)
    except ValueError:
        return (None, None)


def parse_industries(row: dict) -> list[str]:
    values = []
    for item in _safe_json(row.get("industries")):
        val = item.get("value")
        if val:
            values.append(str(val))
    return values
