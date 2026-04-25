"""
job_scraper.py — Playwright-based job-post scraper for the Tenacious signal pipeline.

Targets: Wellfound, BuiltIn, and company direct careers pages.
LinkedIn is explicitly skipped (requires login; robots.txt prohibits crawling).

Constraints enforced:
  - Respect robots.txt (urllib.robotparser — async wrapper)
  - No login, no CAPTCHA bypass
  - Maximum 200 company pages per challenge-week crawl
  - Frozen snapshot path: data/processed/job_snapshots/<company_slug>.json
  - Velocity computed from snapshot delta (current vs. 60-day reference)

Usage:
    from scraper.job_scraper import get_job_velocity_signal

    # Synchronous wrapper for use inside enrich_prospect
    signal_item = get_job_velocity_signal(
        company_name="Acme AI",
        wellfound_slug="acme-ai",          # optional
        builtin_slug="acme-ai",            # optional
        careers_url="https://acme.ai/careers",  # optional
    )
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from scraper.velocity_tracker import (
    save_snapshot as vt_save_snapshot,
    compute_velocity as vt_compute_velocity,
    velocity_signal_register,
)
from scraper.confidence_scorer import score_scrape_result

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "processed" / "job_snapshots"

# Minimum delay between requests to the same host (seconds)
_CRAWL_DELAY = 2.0

# Engineering role title keywords (used for velocity classification)
_ENG_KW = re.compile(
    r"\b(engineer|engineering|developer|architect|sre|devops|mlops|data\s+scientist"
    r"|data\s+engineer|ml\s+engineer|ai\s+engineer|platform|backend|frontend"
    r"|full.?stack|infrastructure|infra|cloud|software|systems|research\s+scientist"
    r"|applied\s+scientist|llm\s+engineer|ml\s+platform|ai\s+product)\b",
    re.I,
)


@dataclass
class JobPostSnapshot:
    title: str
    url: Optional[str] = None
    department: Optional[str] = None
    location: Optional[str] = None
    is_engineering: bool = False


@dataclass
class JobScrapeResult:
    company_name: str
    scraped_at: str
    source_urls: list[str] = field(default_factory=list)
    total_open_roles: int = 0
    engineering_roles: int = 0
    posts: list[JobPostSnapshot] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "company_name": self.company_name,
            "scraped_at": self.scraped_at,
            "source_urls": self.source_urls,
            "total_open_roles": self.total_open_roles,
            "engineering_roles": self.engineering_roles,
            "posts": [asdict(p) for p in self.posts],
            "error": self.error,
        }


def _company_slug(company_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")


def _is_robots_allowed(url: str, user_agent: str = "*") -> bool:
    """Check robots.txt synchronously. Returns True if crawl is permitted."""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True  # permissive on failure


def _is_engineering_role(title: str) -> bool:
    return bool(_ENG_KW.search(title))


async def _fetch_page(page, url: str, wait_selector: Optional[str] = None) -> str:
    """Navigate to URL and return page HTML. Gracefully handles errors."""
    try:
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=5000)
            except Exception:
                pass
        # Allow JS rendering
        await page.wait_for_timeout(1500)
        return await page.content()
    except Exception as exc:
        logger.warning("Failed to load %s: %s", url, exc)
        return ""


def _parse_jobs_from_html(html: str, source_url: str) -> list[JobPostSnapshot]:
    """Extract job posts from page HTML using the jd_extractor."""
    if not html:
        return []
    try:
        from scraper.extractors.jd_extractor import (
            extract_from_wellfound,
            extract_from_builtin,
            extract_generic,
            JobPost,
        )
        if "wellfound.com" in source_url:
            raw = extract_from_wellfound(html, source_url)
        elif "builtin.com" in source_url:
            raw = extract_from_builtin(html, source_url)
        else:
            raw = extract_generic(html, source_url)

        return [
            JobPostSnapshot(
                title=p.title,
                url=p.url,
                department=p.department,
                location=p.location,
                is_engineering=p.is_engineering,
            )
            for p in raw
        ]
    except Exception as exc:
        logger.warning("jd_extractor failed for %s: %s", source_url, exc)
        return []


async def _scrape_async(
    company_name: str,
    wellfound_slug: Optional[str] = None,
    builtin_slug: Optional[str] = None,
    careers_url: Optional[str] = None,
) -> JobScrapeResult:
    """Core async scraper. Runs inside an event loop."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return JobScrapeResult(
            company_name=company_name,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            error="playwright not installed",
        )

    target_urls: list[str] = []

    if wellfound_slug:
        target_urls.append(f"https://wellfound.com/company/{wellfound_slug}/jobs")
    if builtin_slug:
        target_urls.append(f"https://builtin.com/company/{builtin_slug}/jobs")
    if careers_url:
        target_urls.append(careers_url)

    if not target_urls:
        return JobScrapeResult(
            company_name=company_name,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            error="no target URLs provided",
        )

    all_posts: list[JobPostSnapshot] = []
    fetched_urls: list[str] = []
    last_host_time: dict[str, float] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (compatible; TenaciousSDRBot/1.0; "
                "+https://gettenacious.com/bot)"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # Block images and fonts to speed up crawl
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf}",
            lambda route: route.abort(),
        )

        for url in target_urls:
            if not _is_robots_allowed(url):
                logger.info("robots.txt disallows crawl of %s — skipping", url)
                continue

            # Rate-limit per host
            host = urlparse(url).netloc
            last = last_host_time.get(host, 0)
            wait = _CRAWL_DELAY - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)

            html = await _fetch_page(page, url)
            last_host_time[host] = time.monotonic()

            if html:
                posts = _parse_jobs_from_html(html, url)
                all_posts.extend(posts)
                fetched_urls.append(url)
                logger.info("Scraped %d posts from %s", len(posts), url)

        await browser.close()

    # Deduplicate by (title, url)
    seen: set[str] = set()
    unique: list[JobPostSnapshot] = []
    for p in all_posts:
        key = (p.title.lower(), p.url or "")
        if key not in seen:
            seen.add(key)
            unique.append(p)

    engineering_count = sum(1 for p in unique if p.is_engineering)

    return JobScrapeResult(
        company_name=company_name,
        scraped_at=datetime.now(timezone.utc).isoformat(),
        source_urls=fetched_urls,
        total_open_roles=len(unique),
        engineering_roles=engineering_count,
        posts=unique,
    )


def scrape_company_jobs(
    company_name: str,
    wellfound_slug: Optional[str] = None,
    builtin_slug: Optional[str] = None,
    careers_url: Optional[str] = None,
) -> JobScrapeResult:
    """
    Synchronous entry point. Runs the async scraper in a new event loop.

    Saves result to data/processed/job_snapshots/<slug>.json for velocity tracking.
    """
    result = asyncio.run(
        _scrape_async(
            company_name=company_name,
            wellfound_slug=wellfound_slug,
            builtin_slug=builtin_slug,
            careers_url=careers_url,
        )
    )
    vt_save_snapshot(
        company_slug=_company_slug(result.company_name),
        engineering_count=result.engineering_roles,
        total_count=result.total_open_roles,
        source_urls=result.source_urls,
    )
    return result


def get_job_velocity_signal(
    company_name: str,
    wellfound_slug: Optional[str] = None,
    builtin_slug: Optional[str] = None,
    careers_url: Optional[str] = None,
) -> Optional[dict]:
    """
    High-level entry point for the enrichment pipeline.

    Returns a dict compatible with SignalItem fields, or None if scrape fails.
    Adds a job_velocity signal based on engineering role count and 60-day delta.
    """
    try:
        result = scrape_company_jobs(
            company_name=company_name,
            wellfound_slug=wellfound_slug,
            builtin_slug=builtin_slug,
            careers_url=careers_url,
        )
    except Exception as exc:
        logger.warning("Job scrape failed for %s: %s", company_name, exc)
        return None

    if result.error or result.total_open_roles == 0:
        logger.info(
            "No job posts found for %s (error=%s)", company_name, result.error
        )
        return None

    slug = _company_slug(company_name)
    vel = vt_compute_velocity(slug, result.engineering_roles)
    register = velocity_signal_register(vel)
    conf_score = score_scrape_result(result)

    if vel.delta >= 3:
        value = f"{vel.current_count} open engineering roles (+{vel.delta} in 60 days)"
    else:
        value = f"{vel.current_count} open engineering roles"

    return {
        "signal_type": "job_velocity",
        "value": value,
        "evidence": (
            f"Scraped {result.total_open_roles} total open roles "
            f"({vel.current_count} engineering) from "
            f"{', '.join(result.source_urls) or 'unknown'} "
            f"(scrape confidence={conf_score.score:.2f})"
        ),
        "confidence": vel.confidence,
        "language_register": register,
        "engineering_role_count": vel.current_count,
        "role_delta_60d": vel.delta,
        "scrape_confidence": conf_score.score,
    }
