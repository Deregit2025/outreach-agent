"""
test_confidence_scorer.py — Unit tests for scraper/confidence_scorer.py

Tests:
  - score_scrape_result() for perfect, error, zero-roles, and stale inputs
  - score_signal_item() for confidence + freshness matrix
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scraper.confidence_scorer import (
    score_scrape_result,
    score_signal_item,
)
from scraper.job_scraper import JobScrapeResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iso(days_ago: int = 0) -> str:
    """Return an ISO-8601 UTC timestamp N days in the past."""
    return (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).isoformat()


def _make_result(
    *,
    source_urls: list[str] | None = None,
    engineering_roles: int = 0,
    total_open_roles: int = 0,
    scraped_at_days_ago: int = 0,
    error: str | None = None,
) -> JobScrapeResult:
    return JobScrapeResult(
        company_name="Test Co",
        scraped_at=_iso(scraped_at_days_ago),
        source_urls=source_urls or [],
        total_open_roles=total_open_roles,
        engineering_roles=engineering_roles,
        error=error,
    )


# ── score_scrape_result() tests ───────────────────────────────────────────────

class TestScorePerfectResult:
    """
    Probe: 2 sources, very recent data, high engineering-role ratio → score >= 0.7
    """

    def test_two_sources_recent_many_eng_roles(self):
        result = _make_result(
            source_urls=[
                "https://wellfound.com/company/acme-ai/jobs",
                "https://acme.ai/careers",
            ],
            engineering_roles=8,
            total_open_roles=10,
            scraped_at_days_ago=1,
        )
        scored = score_scrape_result(result)
        assert scored.score >= 0.7, (
            f"Perfect result should score >= 0.7; got {scored.score}\n{scored.breakdown}"
        )

    def test_error_penalty_is_false(self):
        result = _make_result(
            source_urls=["https://wellfound.com/company/acme/jobs"],
            engineering_roles=5,
            total_open_roles=8,
            scraped_at_days_ago=0,
        )
        scored = score_scrape_result(result)
        assert scored.error_penalty is False

    def test_three_sources_gives_multi_source_base(self):
        result = _make_result(
            source_urls=["https://a.com", "https://b.com", "https://c.com"],
            engineering_roles=6,
            total_open_roles=8,
            scraped_at_days_ago=2,
        )
        scored = score_scrape_result(result)
        assert scored.base_score == 0.8
        assert scored.score >= 0.7

    def test_breakdown_contains_all_keys(self):
        result = _make_result(
            source_urls=["https://a.com", "https://b.com"],
            engineering_roles=4,
            total_open_roles=6,
            scraped_at_days_ago=3,
        )
        scored = score_scrape_result(result)
        assert "sources" in scored.breakdown
        assert "freshness" in scored.breakdown
        assert "eng_ratio" in scored.breakdown
        assert "final" in scored.breakdown


class TestScoreErrorResult:
    """Probe: result with error → score <= 0.2"""

    def test_error_collapses_score(self):
        result = _make_result(
            error="playwright not installed",
            source_urls=[],
            engineering_roles=0,
        )
        scored = score_scrape_result(result)
        assert scored.score <= 0.2, (
            f"Error result should score <= 0.2; got {scored.score}"
        )

    def test_error_penalty_flag_is_set(self):
        result = _make_result(error="timeout after 20s")
        scored = score_scrape_result(result)
        assert scored.error_penalty is True

    def test_error_score_is_positive_not_zero(self):
        # Score collapses to 0.1 (non-zero, to avoid treating as "no data")
        result = _make_result(error="no target URLs provided")
        scored = score_scrape_result(result)
        assert scored.score == pytest.approx(0.1)

    def test_error_with_sources_still_collapses(self):
        # Error takes precedence over source count
        result = _make_result(
            error="robots.txt disallows crawl",
            source_urls=["https://a.com", "https://b.com"],
            engineering_roles=5,
        )
        scored = score_scrape_result(result)
        assert scored.score <= 0.2
        assert scored.error_penalty is True


class TestScoreZeroRoles:
    """Probe: 0 total roles → score <= 0.3"""

    def test_zero_roles_no_sources(self):
        result = _make_result(
            source_urls=[],
            engineering_roles=0,
            total_open_roles=0,
        )
        scored = score_scrape_result(result)
        assert scored.score <= 0.3, (
            f"Zero roles with no sources should score <= 0.3; got {scored.score}"
        )

    def test_zero_roles_no_eng_bonus(self):
        result = _make_result(
            source_urls=["https://wellfound.com/company/empty/jobs"],
            engineering_roles=0,
            total_open_roles=0,
        )
        scored = score_scrape_result(result)
        assert scored.eng_ratio_bonus == 0.0

    def test_zero_eng_roles_but_total_present(self):
        # 0 engineering out of 5 total → no eng bonus; score depends on source + freshness
        result = _make_result(
            source_urls=["https://a.com"],
            engineering_roles=0,
            total_open_roles=5,
            scraped_at_days_ago=3,
        )
        scored = score_scrape_result(result)
        assert scored.eng_ratio_bonus == 0.0
        assert scored.score <= 0.55  # base 0.5 * 1.0 freshness + 0 bonus


class TestScoreStaleResult:
    """Probe: scraped 60 days ago → reduced score"""

    def test_stale_60_days_reduces_score(self):
        # Fresh result baseline
        fresh = _make_result(
            source_urls=["https://a.com"],
            engineering_roles=4,
            total_open_roles=5,
            scraped_at_days_ago=1,
        )
        # Same result but 60 days old
        stale = _make_result(
            source_urls=["https://a.com"],
            engineering_roles=4,
            total_open_roles=5,
            scraped_at_days_ago=60,
        )
        fresh_score = score_scrape_result(fresh).score
        stale_score = score_scrape_result(stale).score
        assert stale_score < fresh_score, (
            f"Stale result should score lower than fresh; "
            f"stale={stale_score}, fresh={fresh_score}"
        )

    def test_stale_uses_0_5_multiplier(self):
        result = _make_result(
            source_urls=["https://a.com"],
            engineering_roles=3,
            total_open_roles=5,
            scraped_at_days_ago=60,
        )
        scored = score_scrape_result(result)
        # 60 days > STALE_DAYS (30) → multiplier should be 0.5
        assert scored.freshness_mult == pytest.approx(0.5)

    def test_aging_31_days_uses_stale_multiplier(self):
        result = _make_result(
            source_urls=["https://a.com"],
            engineering_roles=2,
            total_open_roles=4,
            scraped_at_days_ago=31,
        )
        scored = score_scrape_result(result)
        assert scored.freshness_mult == pytest.approx(0.5)

    def test_aging_15_days_uses_0_8_multiplier(self):
        result = _make_result(
            source_urls=["https://a.com"],
            engineering_roles=2,
            total_open_roles=4,
            scraped_at_days_ago=15,
        )
        scored = score_scrape_result(result)
        assert scored.freshness_mult == pytest.approx(0.8)


# ── score_signal_item() tests ─────────────────────────────────────────────────

class TestSignalItemConfidence:
    """
    Probe:
      - high confidence + fresh → >= 0.8
      - low + stale → <= 0.3
    """

    def test_high_confidence_fresh_above_0_8(self):
        signal = {"confidence": "high", "data_age_days": 5}
        score = score_signal_item(signal)
        assert score >= 0.8, f"High conf + fresh should be >= 0.8; got {score}"

    def test_high_confidence_very_fresh_is_1_0(self):
        signal = {"confidence": "high", "data_age_days": 0}
        score = score_signal_item(signal)
        # 1.0 * 1.0 = 1.0
        assert score == pytest.approx(1.0)

    def test_low_confidence_stale_below_0_3(self):
        signal = {"confidence": "low", "data_age_days": 90}
        score = score_signal_item(signal)
        # 0.3 * 0.6 = 0.18
        assert score <= 0.3, f"Low conf + stale should be <= 0.3; got {score}"

    def test_medium_confidence_aging_score(self):
        signal = {"confidence": "medium", "data_age_days": 20}
        score = score_signal_item(signal)
        # 0.6 * 0.85 = 0.51
        assert score == pytest.approx(0.51, abs=0.01)

    def test_unknown_confidence_defaults_to_low(self):
        signal = {"confidence": "unknown", "data_age_days": 5}
        score = score_signal_item(signal)
        # default low label = 0.3; age ≤ 7 → *1.0
        assert score == pytest.approx(0.3)

    def test_missing_confidence_defaults_to_low(self):
        signal = {"data_age_days": 10}
        score = score_signal_item(signal)
        assert score <= 0.35

    def test_missing_age_penalises_score(self):
        signal_with_age = {"confidence": "high", "data_age_days": 5}
        signal_no_age = {"confidence": "high"}
        score_with = score_signal_item(signal_with_age)
        score_without = score_signal_item(signal_no_age)
        assert score_without < score_with

    def test_stale_signal_age_none_uses_penalty(self):
        signal = {"confidence": "medium", "data_age_days": None}
        score = score_signal_item(signal)
        # 0.6 * 0.7 = 0.42
        assert score == pytest.approx(0.42, abs=0.01)

    def test_score_clamped_to_1_0(self):
        # Even if confidence = "high" and fresh, should not exceed 1.0
        signal = {"confidence": "high", "data_age_days": 0}
        score = score_signal_item(signal)
        assert score <= 1.0

    def test_score_clamped_to_0_0(self):
        # Sanity check: never negative
        signal = {"confidence": "low", "data_age_days": 999}
        score = score_signal_item(signal)
        assert score >= 0.0
