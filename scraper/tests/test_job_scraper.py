"""
test_job_scraper.py — Unit tests for scraper/extractors/jd_extractor.py
and the VelocityTracker integration.

Tests run fully offline against HTML fixture strings — no Playwright, no network.
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scraper.extractors.jd_extractor import (
    JobPost,
    _is_engineering_role,
    extract_from_wellfound,
    extract_generic,
)
from scraper.velocity_tracker import (
    VelocityResult,
    compute_velocity,
    save_snapshot,
)
from scraper.tests.fixtures import (
    WELLFOUND_HTML_FIXTURE,
    GENERIC_CAREERS_HTML_FIXTURE,
    PRESS_RELEASE_HTML_FIXTURE,
)


# ── extract_from_wellfound() ──────────────────────────────────────────────────

class TestExtractFromWellfoundFixture:
    """Load WELLFOUND_HTML_FIXTURE and verify engineering posts are extracted."""

    def test_returns_list_of_job_posts(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        assert isinstance(posts, list)
        assert len(posts) > 0

    def test_finds_at_least_three_engineering_posts(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        eng_posts = [p for p in posts if p.is_engineering]
        assert len(eng_posts) >= 3, (
            f"Expected >= 3 engineering posts; got {len(eng_posts)}: "
            f"{[p.title for p in eng_posts]}"
        )

    def test_senior_backend_engineer_is_found(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        titles = [p.title.lower() for p in posts]
        assert any("backend engineer" in t or "senior backend" in t for t in titles), (
            f"Senior Backend Engineer not found in: {titles}"
        )

    def test_ml_engineer_is_classified_as_engineering(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        ml_posts = [p for p in posts if "ml" in p.title.lower() or "engineer" in p.title.lower()]
        assert any(p.is_engineering for p in ml_posts)

    def test_account_executive_is_not_engineering(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        ae_posts = [p for p in posts if "account executive" in p.title.lower()]
        for p in ae_posts:
            assert p.is_engineering is False, (
                f"Account Executive should not be classified as engineering: {p.title}"
            )

    def test_post_urls_point_to_wellfound(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        for p in posts:
            if p.url:
                assert "wellfound.com" in p.url or p.url.startswith("/jobs/"), (
                    f"Unexpected URL: {p.url}"
                )

    def test_no_duplicate_posts(self):
        posts = extract_from_wellfound(WELLFOUND_HTML_FIXTURE, "https://wellfound.com")
        urls = [p.url for p in posts if p.url]
        assert len(urls) == len(set(urls)), "Duplicate post URLs found"

    def test_empty_html_returns_empty_list(self):
        posts = extract_from_wellfound("", "https://wellfound.com")
        assert posts == []


# ── extract_generic() ─────────────────────────────────────────────────────────

class TestExtractGenericFixture:
    """Load GENERIC_CAREERS_HTML_FIXTURE and verify engineering jobs in h2/h3."""

    def test_returns_list_of_job_posts(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        assert isinstance(posts, list)
        assert len(posts) > 0

    def test_finds_at_least_four_engineering_jobs(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        eng_posts = [p for p in posts if p.is_engineering]
        assert len(eng_posts) >= 4, (
            f"Expected >= 4 engineering posts from generic page; "
            f"got {len(eng_posts)}: {[p.title for p in eng_posts]}"
        )

    def test_python_fastapi_role_is_found(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        titles_lower = [p.title.lower() for p in posts]
        assert any("python" in t or "software engineer" in t for t in titles_lower), (
            f"Python/Software Engineer not found in: {titles_lower}"
        )

    def test_infrastructure_engineer_is_found(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        titles_lower = [p.title.lower() for p in posts]
        assert any("infrastructure" in t for t in titles_lower)

    def test_marketing_manager_is_not_engineering(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        marketing_posts = [p for p in posts if "marketing" in p.title.lower()]
        for p in marketing_posts:
            assert p.is_engineering is False

    def test_customer_success_is_not_engineering(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        cs_posts = [p for p in posts if "customer success" in p.title.lower()]
        for p in cs_posts:
            assert p.is_engineering is False

    def test_apply_links_include_base_url(self):
        posts = extract_generic(GENERIC_CAREERS_HTML_FIXTURE, "https://bluewave.io")
        linked = [p for p in posts if p.url]
        # At least the anchor-href strategy should pick up some /careers/apply links
        assert len(linked) >= 1

    def test_empty_html_returns_empty_list(self):
        posts = extract_generic("", "https://bluewave.io")
        assert posts == []


# ── _is_engineering_role() ────────────────────────────────────────────────────

class TestIsEngineeringRole:
    """Unit tests for the engineering keyword matching function."""

    @pytest.mark.parametrize("title", [
        "Senior Backend Engineer",
        "ML Engineer — LLM Platform",
        "Data Engineer (dbt + Snowflake)",
        "DevOps Engineer — Kubernetes",
        "Software Developer",
        "Cloud Architect",
        "SRE Lead",
        "Platform Engineer",
        "Frontend Engineer — React",
        "Full Stack Developer",
        "Infrastructure Engineer",
        "Data Scientist — Machine Learning",
        "Applied Scientist, Recommendations",
        "AI Product Engineer",
        "MLOps Engineer",
        "iOS Engineer",
        "Android Developer",
        "Embedded Systems Engineer",
        "Research Scientist, NLP",
    ])
    def test_engineering_titles_are_classified_true(self, title: str):
        assert _is_engineering_role(title) is True, (
            f"Expected '{title}' to be classified as engineering"
        )

    @pytest.mark.parametrize("title", [
        "Account Executive",
        "Marketing Manager",
        "Customer Success Manager",
        "HR Business Partner",
        "Finance Analyst",
        "Legal Counsel",
        "Office Manager",
        "Content Writer",
        "PR Manager",
        "UX Designer",
        "Graphic Designer",
        "Recruiting Coordinator",
        "Sales Development Representative",
        "Operations Manager",
    ])
    def test_non_engineering_titles_are_classified_false(self, title: str):
        assert _is_engineering_role(title) is False, (
            f"Expected '{title}' to be classified as non-engineering"
        )

    def test_empty_string_is_not_engineering(self):
        assert _is_engineering_role("") is False

    def test_case_insensitive(self):
        assert _is_engineering_role("SENIOR SOFTWARE ENGINEER") is True
        assert _is_engineering_role("senior software engineer") is True


# ── VelocityTracker.compute_velocity() ───────────────────────────────────────

class TestVelocityTrackerCompute:
    """
    Tests for compute_velocity() that mirror the probe requirements.
    Snapshots are written to a temp directory to keep tests isolated.
    """

    def _write_snapshot(self, tmp_path: Path, slug: str, eng_count: int, age_days: int = 5):
        saved_at = (
            datetime.now(timezone.utc) - timedelta(days=age_days)
        ).isoformat()
        data = {
            "company_slug": slug,
            "engineering_count": eng_count,
            "total_count": eng_count + 3,
            "source_urls": [],
            "saved_at": saved_at,
        }
        (tmp_path / f"{slug}.json").write_text(json.dumps(data), encoding="utf-8")

    def test_growing_trend_current_10_previous_5(self, tmp_path):
        slug = "acme-growing"
        self._write_snapshot(tmp_path, slug, eng_count=5, age_days=5)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=10)

        assert result.trend == "growing"
        assert result.delta == 5
        assert result.current_count == 10
        assert result.previous_count == 5

    def test_compute_velocity_returns_velocity_result_instance(self, tmp_path):
        slug = "acme-type-check"
        self._write_snapshot(tmp_path, slug, eng_count=3)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=6)

        assert isinstance(result, VelocityResult)

    def test_declining_trend_current_3_previous_8(self, tmp_path):
        slug = "acme-declining"
        self._write_snapshot(tmp_path, slug, eng_count=8, age_days=10)

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=3)

        assert result.trend == "declining"
        assert result.delta == -5

    def test_no_snapshot_returns_unknown_low_delta_zero(self, tmp_path):
        slug = "acme-no-snap"
        # Do NOT write any snapshot

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            result = compute_velocity(slug, current_engineering_count=7)

        assert result.trend == "unknown"
        assert result.delta == 0
        assert result.confidence == "low"
        assert result.previous_count is None

    def test_save_then_compute_roundtrip(self, tmp_path):
        slug = "acme-roundtrip"

        with patch("scraper.velocity_tracker.SNAPSHOT_DIR", tmp_path):
            save_snapshot(slug, engineering_count=6, total_count=12, source_urls=[])
            result = compute_velocity(slug, current_engineering_count=9)

        assert result.previous_count == 6
        assert result.delta == 3
        assert result.trend == "growing"
