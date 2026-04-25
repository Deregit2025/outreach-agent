"""
confidence_scorer.py — Confidence scoring for scrape results and signal items
in the Tenacious signal pipeline.

Provides:
  - ScraperConfidenceScore dataclass with a single float score (0.0–1.0) and
    a breakdown of contributing factors for transparency/debugging.
  - score_scrape_result(result) -> ScraperConfidenceScore
    Scores a JobScrapeResult on source URL count, data freshness, and
    engineering-role ratio. Collapses to 0.1 when an error is present.
  - score_signal_item(signal_item_dict) -> float
    Scores a SignalItem-like dict (from job_velocity or any other signal)
    based on its "confidence" label and "data_age_days" field.

Scoring philosophy:
  - Start from a base score derived from how many sources were successfully
    scraped; more independent sources = higher confidence.
  - Multiply by a freshness factor: data scraped within 7 days is full value,
    30 days is 0.8x, older is 0.5x.
  - Add a small bonus (up to 0.15) for a high engineering-role ratio, because
    a page with mostly engineering roles is more likely to be correctly parsed.
  - Hard-cap the result at 1.0 and floor at 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Freshness thresholds (days)
_FRESH_DAYS = 7
_STALE_DAYS = 30

# Freshness multipliers
_FRESH_MULT = 1.0
_AGING_MULT = 0.8
_STALE_MULT = 0.5

# Maximum engineering-ratio bonus
_ENG_RATIO_BONUS_MAX = 0.15

# Base scores by source count
_BASE_BY_SOURCES = {0: 0.0, 1: 0.5}
_BASE_MULTI_SOURCE = 0.8  # 2 or more sources

# Confidence label → numeric value for signal_item scoring
_CONFIDENCE_LABEL_SCORE: dict[str, float] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

# Age thresholds for signal_item scoring (days)
_SIGNAL_FRESH_DAYS = 7
_SIGNAL_STALE_DAYS = 30


@dataclass
class ScraperConfidenceScore:
    """
    Confidence score for a single JobScrapeResult.

    Attributes:
        score:              Final 0.0–1.0 confidence value.
        base_score:         Score contribution from source URL count.
        freshness_mult:     Multiplier applied for data age.
        eng_ratio_bonus:    Bonus applied for engineering-role ratio.
        error_penalty:      True when result had an error (score collapsed to 0.1).
        breakdown:          Human-readable explanation of each factor.
    """

    score: float
    base_score: float
    freshness_mult: float
    eng_ratio_bonus: float
    error_penalty: bool
    breakdown: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"ScraperConfidenceScore(score={self.score:.3f}, "
            f"base={self.base_score:.2f}, "
            f"freshness_mult={self.freshness_mult:.2f}, "
            f"eng_bonus={self.eng_ratio_bonus:.3f}, "
            f"error={self.error_penalty})"
        )


def _data_age_days(scraped_at_iso: str) -> Optional[int]:
    """Parse scraped_at ISO string and return age in days, or None on error."""
    try:
        scraped = datetime.fromisoformat(scraped_at_iso)
        # Ensure timezone-aware comparison
        if scraped.tzinfo is None:
            scraped = scraped.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - scraped
        return max(0, delta.days)
    except Exception:
        return None


def _freshness_multiplier(age_days: Optional[int]) -> tuple[float, str]:
    """Return (multiplier, description) based on data age."""
    if age_days is None:
        return _STALE_MULT, "unknown age → 0.5x"
    if age_days <= _FRESH_DAYS:
        return _FRESH_MULT, f"{age_days}d old (≤{_FRESH_DAYS}d) → 1.0x"
    if age_days <= _STALE_DAYS:
        return _AGING_MULT, f"{age_days}d old (≤{_STALE_DAYS}d) → 0.8x"
    return _STALE_MULT, f"{age_days}d old (>{_STALE_DAYS}d) → 0.5x"


def score_scrape_result(result) -> ScraperConfidenceScore:
    """
    Compute a confidence score for a JobScrapeResult.

    The result parameter is a JobScrapeResult instance (imported lazily to
    avoid circular imports). The function inspects:
      - result.error            — collapses score to 0.1 if present
      - result.source_urls      — determines base score
      - result.scraped_at       — determines freshness multiplier
      - result.engineering_roles / result.total_open_roles — ratio bonus

    Args:
        result: A JobScrapeResult instance.

    Returns:
        A ScraperConfidenceScore with score in [0.0, 1.0].
    """
    breakdown: dict[str, str] = {}

    # Error path: collapse to a minimal score immediately
    if result.error:
        breakdown["error"] = f"error present: '{result.error}'"
        return ScraperConfidenceScore(
            score=0.1,
            base_score=0.1,
            freshness_mult=1.0,
            eng_ratio_bonus=0.0,
            error_penalty=True,
            breakdown=breakdown,
        )

    # --- Base score from source URL count ---
    n_sources = len(result.source_urls)
    if n_sources == 0:
        base = _BASE_BY_SOURCES[0]
        breakdown["sources"] = "0 sources scraped → base 0.0"
    elif n_sources == 1:
        base = _BASE_BY_SOURCES[1]
        breakdown["sources"] = "1 source scraped → base 0.5"
    else:
        base = _BASE_MULTI_SOURCE
        breakdown["sources"] = f"{n_sources} sources scraped → base 0.8"

    # --- Freshness multiplier ---
    age_days = _data_age_days(result.scraped_at)
    freshness_mult, freshness_desc = _freshness_multiplier(age_days)
    breakdown["freshness"] = freshness_desc

    # --- Engineering ratio bonus ---
    eng_bonus = 0.0
    total = getattr(result, "total_open_roles", 0)
    eng = getattr(result, "engineering_roles", 0)
    if total > 0:
        ratio = eng / total
        eng_bonus = round(ratio * _ENG_RATIO_BONUS_MAX, 4)
        breakdown["eng_ratio"] = (
            f"{eng}/{total} engineering roles "
            f"(ratio={ratio:.2f}) → bonus {eng_bonus:.3f}"
        )
    else:
        breakdown["eng_ratio"] = "0 total roles → no bonus"

    # --- Final score ---
    raw = base * freshness_mult + eng_bonus
    score = round(min(1.0, max(0.0, raw)), 4)
    breakdown["final"] = (
        f"({base:.2f} × {freshness_mult:.2f}) + {eng_bonus:.3f} = {score:.4f}"
    )

    return ScraperConfidenceScore(
        score=score,
        base_score=base,
        freshness_mult=freshness_mult,
        eng_ratio_bonus=eng_bonus,
        error_penalty=False,
        breakdown=breakdown,
    )


def score_signal_item(signal_item_dict: dict) -> float:
    """
    Score a SignalItem-like dict and return a float in [0.0, 1.0].

    Combines two factors:
      1. The "confidence" field ("high" / "medium" / "low") mapped to a
         numeric anchor (1.0 / 0.6 / 0.3). Unrecognised values default to 0.3.
      2. A freshness multiplier based on "data_age_days":
         - None or absent  → 0.7x (unknown age, moderately penalised)
         - ≤ 7 days        → 1.0x
         - ≤ 30 days       → 0.85x
         - > 30 days       → 0.6x

    The two factors are multiplied and the result is clamped to [0.0, 1.0].

    Args:
        signal_item_dict: A dict with at least "confidence" (str) and
                          optionally "data_age_days" (int | None).

    Returns:
        Float confidence score in [0.0, 1.0].
    """
    confidence_label = str(signal_item_dict.get("confidence", "low")).lower()
    label_score = _CONFIDENCE_LABEL_SCORE.get(confidence_label, 0.3)

    data_age = signal_item_dict.get("data_age_days")

    if data_age is None:
        age_mult = 0.7  # Penalise unknown age
    elif data_age <= _SIGNAL_FRESH_DAYS:
        age_mult = 1.0
    elif data_age <= _SIGNAL_STALE_DAYS:
        age_mult = 0.85
    else:
        age_mult = 0.6

    raw = label_score * age_mult
    return round(min(1.0, max(0.0, raw)), 4)
