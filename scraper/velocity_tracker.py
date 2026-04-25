"""
velocity_tracker.py — Job-posting velocity tracking for the Tenacious signal
pipeline.

Persists timestamped snapshots of a company's open-role counts to disk and
computes velocity (rate of change) by comparing the current count against the
most-recent saved snapshot.

Public API:
  - save_snapshot(company_slug, engineering_count, total_count, source_urls)
      Writes a JSON snapshot to data/processed/job_snapshots/<slug>.json.
  - load_snapshot(company_slug) -> dict | None
      Reads the most-recent snapshot for a slug.
  - compute_velocity(company_slug, current_engineering_count) -> VelocityResult
      Diffs current count against the stored snapshot and returns a
      VelocityResult dataclass.
  - meets_segment1_threshold(velocity_result) -> bool
      Returns True when engineering_roles >= 5 (Segment 1 ICP minimum).
  - velocity_signal_register(velocity_result) -> str
      Returns "assert", "hedge", or "ask" based on count + delta.

Snapshot file format (JSON):
    {
        "company_slug":       "acme-ai",
        "engineering_count":  8,
        "total_count":        22,
        "source_urls":        ["https://wellfound.com/company/acme-ai/jobs"],
        "saved_at":           "2025-04-10T14:30:00+00:00"
    }
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "processed" / "job_snapshots"

# Segment 1 ICP minimum open engineering roles (icp_definition.md)
_SEGMENT1_MIN_ENG_ROLES = 5

# Signal-register thresholds
_ASSERT_MIN_COUNT = 10
_ASSERT_MIN_DELTA = 3
_HEDGE_MIN_COUNT = 5


def _normalise_slug(company_slug: str) -> str:
    """Normalise a company slug to safe filename characters."""
    return re.sub(r"[^a-z0-9]+", "-", company_slug.lower()).strip("-")


@dataclass
class VelocityResult:
    """
    Result of a velocity computation for a single company.

    Attributes:
        company_slug:      URL-safe company identifier.
        current_count:     Current open engineering role count.
        previous_count:    Engineering role count from the stored snapshot,
                           or None if no snapshot exists.
        delta:             current_count - previous_count (0 if no snapshot).
        delta_pct:         Percentage change (0.0 if previous_count is 0 or
                           no snapshot exists).
        snapshot_age_days: Age of the reference snapshot in days, or None if
                           no snapshot exists.
        confidence:        "high" if snapshot ≤ 60 days old, "low" otherwise.
        trend:             "growing" / "stable" / "declining" / "unknown".
    """

    company_slug: str
    current_count: int
    previous_count: Optional[int]
    delta: int
    delta_pct: float
    snapshot_age_days: Optional[int]
    confidence: str
    trend: str

    def __str__(self) -> str:
        return (
            f"VelocityResult(slug={self.company_slug!r}, "
            f"current={self.current_count}, "
            f"delta={self.delta:+d}, "
            f"trend={self.trend!r}, "
            f"confidence={self.confidence!r})"
        )


# ------------------------------------------------------------------
# Snapshot I/O
# ------------------------------------------------------------------

def save_snapshot(
    company_slug: str,
    engineering_count: int,
    total_count: int,
    source_urls: list[str],
) -> Path:
    """
    Persist a timestamped snapshot of a company's open-role counts.

    Creates the snapshot directory if it does not exist. Overwrites any
    existing snapshot for the same slug (one snapshot per company is kept;
    the old value is read by load_snapshot before being replaced).

    Args:
        company_slug:      URL-safe identifier (e.g. "acme-ai").
        engineering_count: Number of open engineering roles at scrape time.
        total_count:       Total number of open roles at scrape time.
        source_urls:       List of URLs that were scraped to produce the counts.

    Returns:
        Path to the written snapshot file.
    """
    slug = _normalise_slug(company_slug)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{slug}.json"

    payload = {
        "company_slug": slug,
        "engineering_count": engineering_count,
        "total_count": total_count,
        "source_urls": source_urls,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.debug(
        "Saved snapshot for %r: eng=%d total=%d → %s",
        slug,
        engineering_count,
        total_count,
        path,
    )
    return path


def load_snapshot(company_slug: str) -> Optional[dict]:
    """
    Load the most-recent snapshot for a company slug.

    Args:
        company_slug: URL-safe identifier (e.g. "acme-ai").

    Returns:
        Parsed snapshot dict, or None if no snapshot file exists or the
        file cannot be parsed.
    """
    slug = _normalise_slug(company_slug)
    path = SNAPSHOT_DIR / f"{slug}.json"
    if not path.exists():
        logger.debug("No snapshot found for %r", slug)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.debug("Loaded snapshot for %r from %s", slug, path)
        return data
    except Exception as exc:
        logger.warning("Could not parse snapshot for %r: %s", slug, exc)
        return None


# ------------------------------------------------------------------
# Velocity computation
# ------------------------------------------------------------------

def _snapshot_age_days(snapshot: dict) -> Optional[int]:
    """Return age of snapshot in whole days, or None if unparseable."""
    try:
        saved = datetime.fromisoformat(snapshot["saved_at"])
        if saved.tzinfo is None:
            saved = saved.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - saved).days)
    except Exception:
        return None


def _classify_trend(delta: int, previous_count: Optional[int]) -> str:
    """Map a delta onto a trend label."""
    if previous_count is None:
        return "unknown"
    if delta > 0:
        return "growing"
    if delta < 0:
        return "declining"
    return "stable"


def compute_velocity(
    company_slug: str,
    current_engineering_count: int,
    reference_days: int = 60,
) -> VelocityResult:
    """
    Compute job-posting velocity for a company by comparing the current
    engineering role count against the stored snapshot.

    Args:
        company_slug:              URL-safe company identifier.
        current_engineering_count: Engineering role count at this moment.
        reference_days:            Maximum snapshot age (days) to consider
                                   high-confidence. Defaults to 60.

    Returns:
        A VelocityResult dataclass.
    """
    slug = _normalise_slug(company_slug)
    snapshot = load_snapshot(slug)

    if snapshot is None:
        return VelocityResult(
            company_slug=slug,
            current_count=current_engineering_count,
            previous_count=None,
            delta=0,
            delta_pct=0.0,
            snapshot_age_days=None,
            confidence="low",
            trend="unknown",
        )

    previous_count: int = snapshot.get("engineering_count", 0)
    delta = current_engineering_count - previous_count

    if previous_count > 0:
        delta_pct = round((delta / previous_count) * 100, 2)
    else:
        delta_pct = 0.0

    age_days = _snapshot_age_days(snapshot)
    confidence = (
        "high"
        if age_days is not None and age_days <= reference_days
        else "low"
    )
    trend = _classify_trend(delta, previous_count)

    return VelocityResult(
        company_slug=slug,
        current_count=current_engineering_count,
        previous_count=previous_count,
        delta=delta,
        delta_pct=delta_pct,
        snapshot_age_days=age_days,
        confidence=confidence,
        trend=trend,
    )


# ------------------------------------------------------------------
# ICP qualification helpers
# ------------------------------------------------------------------

def meets_segment1_threshold(velocity_result: VelocityResult) -> bool:
    """
    Return True if the company meets the Segment 1 ICP engineering-role floor.

    Segment 1 (Recently-funded Series A/B startups) requires at least 5 open
    engineering roles. Fewer than 3 is an explicit disqualifying signal per
    icp_definition.md; this function uses the qualifying threshold of 5.

    Args:
        velocity_result: A VelocityResult returned by compute_velocity.

    Returns:
        True when current_count >= 5.
    """
    return velocity_result.current_count >= _SEGMENT1_MIN_ENG_ROLES


def velocity_signal_register(velocity_result: VelocityResult) -> str:
    """
    Map a VelocityResult onto a language register for outreach copy.

    Rules:
      - "assert" : count >= 10 AND delta >= 3 (clear, growing signal)
      - "hedge"  : count >= 5 (meets ICP floor but not strong growth)
      - "ask"    : anything below the ICP floor (exploratory tone)

    Args:
        velocity_result: A VelocityResult returned by compute_velocity.

    Returns:
        One of "assert", "hedge", or "ask".
    """
    count = velocity_result.current_count
    delta = velocity_result.delta

    if count >= _ASSERT_MIN_COUNT and delta >= _ASSERT_MIN_DELTA:
        return "assert"
    if count >= _HEDGE_MIN_COUNT:
        return "hedge"
    return "ask"
