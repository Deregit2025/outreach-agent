from __future__ import annotations

from datetime import datetime, date
from pathlib import Path

import pandas as pd

_CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "layoffs_fyi.csv"

_df: pd.DataFrame = pd.read_csv(_CSV_PATH, encoding="utf-8")
_df_lower_company: pd.Series = _df["company"].astype(str).str.strip().str.lower()


def _parse_date(date_str: str) -> date | None:
    if not isinstance(date_str, str) or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _today() -> date:
    return datetime.now().date()


def check_layoff(company_name: str, within_days: int = 120) -> dict | None:
    needle = company_name.strip().lower()
    mask = _df_lower_company == needle
    if not mask.any():
        return None
    today = _today()
    for _, row in _df[mask].iterrows():
        event_date = _parse_date(str(row.get("date", "")))
        if event_date is not None and (today - event_date).days <= within_days:
            return row.to_dict()
    return None


def get_recent_layoffs(within_days: int = 120) -> list[dict]:
    today = _today()
    results = []
    for _, row in _df.iterrows():
        event_date = _parse_date(str(row.get("date", "")))
        if event_date is not None and (today - event_date).days <= within_days:
            results.append(row.to_dict())
    return results
