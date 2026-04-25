"""
date_utils.py — Date parsing and age helpers used across the enrichment pipeline.

All functions are timezone-naive and compare against today's date in local time.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

# Ordered list of formats to try when parsing an explicit date string.
_DEFAULT_FORMATS: list[str] = [
    "%Y-%m-%d",      # ISO: 2025-03-15
    "%m/%d/%Y",      # US:  03/15/2025
    "%d %b %Y",      # Day-abbr: 15 Mar 2025
    "%d %B %Y",      # Day-full: 15 March 2025
    "%B %d %Y",      # Full month first: March 15 2025
    "%B %d, %Y",     # With comma: March 15, 2025
    "%Y-%m-%dT%H:%M:%SZ",   # ISO 8601 UTC
    "%Y-%m-%dT%H:%M:%S",    # ISO 8601 no TZ
    "%Y-%m-%dT%H:%M:%S%z",  # ISO 8601 with offset
]

# Maps short month abbreviations and full month names → month number
_MONTH_MAP: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Quarter → first month of quarter
_QUARTER_START: dict[str, int] = {"q1": 1, "q2": 4, "q3": 7, "q4": 10}

# Signal-type age thresholds (days) that qualify as "high" confidence
_HIGH_CONF_THRESHOLDS: dict[str, int] = {
    "funding": 180,
    "leadership": 90,
    "leadership_change": 90,
    "job_velocity": 30,
}
_DEFAULT_HIGH_THRESHOLD = 60

_MEDIUM_MULT = 2  # medium = up to 2× the high threshold


def days_ago(date_str: str, formats: Optional[list[str]] = None) -> Optional[int]:
    """
    Parse *date_str* and return how many calendar days ago it was from today.

    Args:
        date_str: A date string in one of the supported formats.
        formats:  Override the default list of formats to try.

    Returns:
        Integer ≥ 0, or None if the string cannot be parsed.
    """
    if not date_str or not isinstance(date_str, str):
        return None

    raw = date_str.strip()
    fmts = formats if formats is not None else _DEFAULT_FORMATS

    for fmt in fmts:
        try:
            parsed = datetime.strptime(raw, fmt)
            delta = date.today() - parsed.date()
            return max(0, delta.days)
        except (ValueError, AttributeError):
            continue

    return None


def is_within_days(date_str: str, days: int) -> Optional[bool]:
    """
    Return True if *date_str* is within *days* calendar days of today.

    Returns None if the date cannot be parsed.
    """
    age = days_ago(date_str)
    if age is None:
        return None
    return age <= days


def format_age(days: int) -> str:
    """
    Convert an integer number of days into a human-readable age string.

    Examples:
        0  → "today"
        3  → "3 days ago"
        14 → "2 weeks ago"
        90 → "3 months ago"
        400 → "1 year ago"
    """
    if days < 0:
        days = 0
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    if days < 14:
        return f"{days} days ago"
    weeks = days // 7
    if weeks < 8:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    months = days // 30
    if months < 24:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


def parse_fuzzy_date(text: str) -> Optional[str]:
    """
    Extract a best-estimate ISO date (YYYY-MM-DD) from a fuzzy English phrase.

    Handles patterns like:
      "last March"         → first day of most-recent March
      "Q1 2026"            → 2026-01-01
      "February 2026"      → 2026-02-01
      "early 2025"         → 2025-01-01
      "mid 2025"           → 2025-07-01
      "late 2025"          → 2025-10-01
      "2025"               → 2025-01-01

    Returns None if no date-like phrase is found.
    """
    if not text or not isinstance(text, str):
        return None

    lowered = text.strip().lower()
    today = date.today()

    # ── Quarter pattern: "Q1 2026", "q3 2025" ────────────────────────────────
    q_match = re.search(r"\b(q[1-4])\s+(\d{4})\b", lowered)
    if q_match:
        quarter = q_match.group(1)
        year = int(q_match.group(2))
        month = _QUARTER_START.get(quarter, 1)
        return date(year, month, 1).isoformat()

    # ── "Month Year" pattern: "February 2026", "Feb 2026" ────────────────────
    month_year = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may"
        r"|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?"
        r"|nov(?:ember)?|dec(?:ember)?)\s+(\d{4})\b",
        lowered,
    )
    if month_year:
        month_name = month_year.group(1).lower().rstrip(".")
        year = int(month_year.group(2))
        month_num = _MONTH_MAP.get(month_name)
        if month_num:
            return date(year, month_num, 1).isoformat()

    # ── "last Month" pattern: "last March" ──────────────────────────────────
    last_month = re.search(
        r"\blast\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may"
        r"|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?"
        r"|nov(?:ember)?|dec(?:ember)?)\b",
        lowered,
    )
    if last_month:
        month_name = last_month.group(1).lower()
        month_num = _MONTH_MAP.get(month_name)
        if month_num:
            year = today.year if today.month > month_num else today.year - 1
            return date(year, month_num, 1).isoformat()

    # ── Vague period + year: "early 2025", "mid 2025", "late 2025" ──────────
    vague = re.search(r"\b(early|mid|late)\s+(\d{4})\b", lowered)
    if vague:
        period = vague.group(1)
        year = int(vague.group(2))
        month_map = {"early": 1, "mid": 7, "late": 10}
        return date(year, month_map[period], 1).isoformat()

    # ── Bare year: "2025" ────────────────────────────────────────────────────
    bare_year = re.search(r"\b(20\d{2})\b", lowered)
    if bare_year:
        year = int(bare_year.group(1))
        return date(year, 1, 1).isoformat()

    return None


def confidence_from_age(age_days: int, signal_type: str = "") -> str:
    """
    Map data age (days) and signal type to a confidence label.

    Thresholds:
      funding:            high ≤ 180d,  medium ≤ 360d,  low > 360d
      leadership /
      leadership_change:  high ≤  90d,  medium ≤ 180d,  low > 180d
      job_velocity:       high ≤  30d,  medium ≤  60d,  low >  60d
      default:            high ≤  60d,  medium ≤ 120d,  low > 120d

    Args:
        age_days:    Number of calendar days since the signal date.
        signal_type: Optional signal category key (used to select threshold).

    Returns:
        "high" | "medium" | "low"
    """
    key = signal_type.lower().strip() if signal_type else ""
    high_threshold = _HIGH_CONF_THRESHOLDS.get(key, _DEFAULT_HIGH_THRESHOLD)
    medium_threshold = high_threshold * _MEDIUM_MULT

    if age_days <= high_threshold:
        return "high"
    if age_days <= medium_threshold:
        return "medium"
    return "low"
