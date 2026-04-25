"""
test_velocity_tracker.py — Unit tests for scraper/velocity_tracker.py

Tests cover:
  - Growing / declining / stable / unknown trend classification
  - Segment 1 threshold gate (>= 5 engineering roles)
  - Language register mapping ("assert" / "hedge" / "ask")
  - compute_velocity() when no snapshot exists
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scraper.velocity_tracker import (
    VelocityResult,
    compute_velocity,
    meets_segment1_threshold,
    save_snapshot,
    velocity_signal_register,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_snapshot(
    slug: str,
    engineering_count: int,
    age_days: int = 10,
    tmpdir: Path | None = None,
) -> dict:
    """
    Build a snapshot dict and optionally write it to a temp directory so that
    compute_velocity() can find it via load_snapshot().
    """
    saved_at = (
        datetime.now(timezone.utc) - timedelta(days=age_days)
    ).isoformat()
    data = {
        "company_slug": slug,
        "engineering_count": engineering_count,
        "total_count": engineering_count + 5,
        "source_urls": ["https://example.com/jobs"],
        "saved_at": saved_at,
    }
    if tmpdir is not None:
        path = tmpdir / f"{slug}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
    return data


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGrowingTrend:
    """Probe: current 10, previous 5, delta=5 → trend='growing'"""

    def test_trend_is_growing(self, tmp_path):
        slug = "test-growing"
        _make_snapshot(slug, engineering_count=5, age_days=10, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=10)

        assert result.trend == "growing"
        assert result.delta == 5
        assert result.current_count == 10
        assert result.previous_count == 5

    def test_delta_pct_is_positive(self, tmp_path):
        slug = "test-delta-pct"
        _make_snapshot(slug, engineering_count=5, age_days=10, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=10)

        assert result.delta_pct == 100.0  # (5/5)*100

    def test_confidence_is_high_for_fresh_snapshot(self, tmp_path):
        slug = "test-fresh"
        _make_snapshot(slug, engineering_count=5, age_days=10, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=10)

        assert result.confidence == "high"


class TestDecliningTrend:
    """Probe: current 3, previous 8 → trend='declining'"""

    def test_trend_is_declining(self, tmp_path):
        slug = "test-declining"
        _make_snapshot(slug, engineering_count=8, age_days=15, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=3)

        assert result.trend == "declining"
        assert result.delta == -5
        assert result.delta_pct == pytest.approx(-62.5)

    def test_declining_confidence(self, tmp_path):
        slug = "test-declining-conf"
        _make_snapshot(slug, engineering_count=8, age_days=20, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=3)

        # 20 days ≤ 60 → high confidence even when declining
        assert result.confidence == "high"

    def test_stale_snapshot_is_low_confidence(self, tmp_path):
        slug = "test-stale"
        _make_snapshot(slug, engineering_count=8, age_days=90, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=3)

        assert result.confidence == "low"
        assert result.snapshot_age_days is not None
        assert result.snapshot_age_days >= 90


class TestSegment1Threshold:
    """Probe: >= 5 engineering roles → meets_segment1_threshold() returns True"""

    def test_at_threshold_returns_true(self, tmp_path):
        slug = "threshold-5"
        _make_snapshot(slug, engineering_count=3, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=5)

        assert meets_segment1_threshold(result) is True

    def test_above_threshold_returns_true(self, tmp_path):
        slug = "threshold-above"
        _make_snapshot(slug, engineering_count=3, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=12)

        assert meets_segment1_threshold(result) is True

    def test_below_threshold_returns_false(self, tmp_path):
        slug = "threshold-below"
        _make_snapshot(slug, engineering_count=1, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=4)

        assert meets_segment1_threshold(result) is False

    def test_zero_roles_is_false(self, tmp_path):
        slug = "threshold-zero"
        _make_snapshot(slug, engineering_count=0, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=0)

        assert meets_segment1_threshold(result) is False


class TestVelocitySignalRegister:
    """
    Probe:
      - 12 roles + delta 4 → "assert"
      - 5 roles (no high delta) → "hedge"
      - 2 roles → "ask"
    """

    def _result(self, current: int, delta: int) -> VelocityResult:
        previous = current - delta
        return VelocityResult(
            company_slug="test",
            current_count=current,
            previous_count=previous,
            delta=delta,
            delta_pct=0.0,
            snapshot_age_days=10,
            confidence="high",
            trend="growing" if delta > 0 else ("declining" if delta < 0 else "stable"),
        )

    def test_assert_register_at_12_roles_delta_4(self):
        result = self._result(current=12, delta=4)
        assert velocity_signal_register(result) == "assert"

    def test_assert_requires_sufficient_count_and_delta(self):
        # count >= 10 AND delta >= 3 required for assert
        result_low_delta = self._result(current=12, delta=2)
        assert velocity_signal_register(result_low_delta) == "hedge"

        result_low_count = self._result(current=8, delta=5)
        assert velocity_signal_register(result_low_count) == "hedge"

    def test_hedge_register_at_5_roles(self):
        result = self._result(current=5, delta=1)
        assert velocity_signal_register(result) == "hedge"

    def test_hedge_at_exactly_5_no_delta(self):
        result = self._result(current=5, delta=0)
        assert velocity_signal_register(result) == "hedge"

    def test_ask_register_at_2_roles(self):
        result = self._result(current=2, delta=0)
        assert velocity_signal_register(result) == "ask"

    def test_ask_at_4_roles(self):
        result = self._result(current=4, delta=2)
        assert velocity_signal_register(result) == "ask"

    def test_ask_at_zero_roles(self):
        result = self._result(current=0, delta=0)
        assert velocity_signal_register(result) == "ask"


class TestComputeVelocityNoSnapshot:
    """Probe: no previous snapshot → VelocityResult with delta=0, confidence='low'"""

    def test_no_snapshot_returns_unknown_trend(self, tmp_path):
        slug = "no-snapshot-company"
        # Do NOT write any snapshot file

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=7)

        assert result.trend == "unknown"
        assert result.delta == 0
        assert result.confidence == "low"
        assert result.previous_count is None
        assert result.snapshot_age_days is None

    def test_no_snapshot_current_count_is_preserved(self, tmp_path):
        slug = "no-snapshot-count"

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=15)

        assert result.current_count == 15

    def test_no_snapshot_delta_pct_is_zero(self, tmp_path):
        slug = "no-snapshot-pct"

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=5)

        assert result.delta_pct == 0.0


class TestStableTrend:
    """Stable when current == previous."""

    def test_stable_trend(self, tmp_path):
        slug = "test-stable"
        _make_snapshot(slug, engineering_count=7, age_days=5, tmpdir=tmp_path)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=7)

        assert result.trend == "stable"
        assert result.delta == 0
        assert result.delta_pct == 0.0


class TestSaveAndLoad:
    """Round-trip: save_snapshot then load_snapshot then compute_velocity."""

    def test_save_then_compute(self, tmp_path):
        slug = "roundtrip-co"

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            save_snapshot(slug, engineering_count=6, total_count=15, source_urls=[])
            result = compute_velocity(slug, current_engineering_count=9)

        assert result.previous_count == 6
        assert result.delta == 3
        assert result.trend == "growing"
        assert result.confidence == "high"  # just saved → age = 0 days
