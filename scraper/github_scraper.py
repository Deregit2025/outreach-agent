"""
github_scraper.py — Scrape a company's public GitHub org page for AI/ML activity signals.

This is one of the inputs to the AI maturity scoring pipeline.

Constraints enforced:
  - Uses requests (not Playwright) — GitHub public org pages are SSR'd
  - Respects robots.txt for github.com before fetching
  - No login, no CAPTCHA bypass, no GitHub API token required
  - User-Agent identifies Tenacious bot

Usage:
    from scraper.github_scraper import get_ai_maturity_signal_from_github

    signal = get_ai_maturity_signal_from_github("openai")
    # Returns a SignalItem-compatible dict or None
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; TenaciousSDRBot/1.0; +https://gettenacious.com/bot)"
)

_REQUEST_TIMEOUT = 15  # seconds

# Repo name keywords that indicate AI/ML activity
_AI_REPO_KEYWORDS = re.compile(
    r"\b(ml|ai|llm|rag|model|nlp|embedding|embeddings|transformer|diffusion"
    r"|gpt|bert|neural|inference|training|finetune|fine.?tun"
    r"|vector|semantic|classify|classification|detection|vision"
    r"|data.?science|feature.?store|mlflow|pipeline|dataset|benchmark)\b",
    re.I,
)

_GITHUB_ROBOTS_CACHE: dict[str, bool] = {}


def _is_robots_allowed(url: str) -> bool:
    """Check github.com robots.txt. Cached per session."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base in _GITHUB_ROBOTS_CACHE:
        return _GITHUB_ROBOTS_CACHE[base]
    try:
        robots_url = f"{base}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        allowed = rp.can_fetch(_USER_AGENT, url)
    except Exception:
        allowed = True  # permissive on failure
    _GITHUB_ROBOTS_CACHE[base] = allowed
    return allowed


def _fetch_html(url: str) -> Optional[str]:
    """Fetch a URL with requests, respecting robots.txt. Returns HTML or None."""
    if not _is_robots_allowed(url):
        logger.info("robots.txt disallows fetch of %s — skipping", url)
        return None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code == 200:
            return response.text
        logger.warning("HTTP %s fetching %s", response.status_code, url)
        return None
    except requests.RequestException as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return None


def _parse_org_repos(html: str) -> list[str]:
    """
    Parse repo names from a GitHub org page.

    GitHub renders org pages with repo cards that contain the repo name in an
    <a> element with itemprop="name codeRepository" or inside a specific
    data-hydro-click attribute. We use a broad selector to be resilient to
    minor markup changes.
    """
    soup = BeautifulSoup(html, "lxml")
    repo_names: list[str] = []
    seen: set[str] = set()

    # Primary: <a> with itemprop containing repo paths like /org/repo-name
    for a in soup.find_all("a", itemprop=True):
        itemprop = a.get("itemprop", "")
        if "codeRepository" in itemprop or "name" in itemprop:
            href = a.get("href", "")
            # href format: /org-slug/repo-name
            parts = [p for p in href.strip("/").split("/") if p]
            if len(parts) == 2:
                repo_name = parts[1]
                if repo_name not in seen:
                    seen.add(repo_name)
                    repo_names.append(repo_name)

    if repo_names:
        return repo_names

    # Fallback: <a> elements whose href matches /<org>/<repo> (two path segments)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        parts = [p for p in href.strip("/").split("/") if p]
        if len(parts) == 2 and not any(c in href for c in ["?", "#", ".", ":"]):
            repo_name = parts[1]
            # Skip obvious non-repo links
            if repo_name in {"followers", "following", "people", "repositories", "projects"}:
                continue
            if repo_name not in seen:
                seen.add(repo_name)
                repo_names.append(repo_name)

    return repo_names


def _count_public_repos(html: str) -> int:
    """Extract the public repository count from the GitHub org page."""
    soup = BeautifulSoup(html, "lxml")
    # GitHub renders "N repositories" in a counter element
    # Look for text like "42 repositories" or "1,234 repositories"
    text = soup.get_text(separator=" ")
    match = re.search(r"([\d,]+)\s+(?:public\s+)?repositor(?:y|ies)", text, re.I)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            pass
    # Fallback: count the repo cards we actually parsed
    return 0


@dataclass
class GitHubOrgResult:
    org_slug: str
    total_repos: int
    ai_repos: list[str] = field(default_factory=list)
    ai_ratio: float = 0.0
    scraped_at: str = ""
    error: Optional[str] = None


async def scrape_org(org_slug: str) -> GitHubOrgResult:
    """
    Fetch https://github.com/{org_slug} and return a GitHubOrgResult.

    Runs requests in a thread pool executor so it is safe to call from async code.
    """
    url = f"https://github.com/orgs/{org_slug}/repositories"
    loop = asyncio.get_event_loop()

    html: Optional[str] = await loop.run_in_executor(None, _fetch_html, url)
    if html is None:
        # Try the plain org page as a fallback
        html = await loop.run_in_executor(
            None, _fetch_html, f"https://github.com/{org_slug}"
        )

    scraped_at = datetime.now(timezone.utc).isoformat()

    if not html:
        return GitHubOrgResult(
            org_slug=org_slug,
            total_repos=0,
            scraped_at=scraped_at,
            error="failed to fetch org page",
        )

    repo_names = _parse_org_repos(html)
    total_from_page = _count_public_repos(html)
    total_repos = total_from_page if total_from_page > 0 else len(repo_names)

    ai_repos = [r for r in repo_names if _AI_REPO_KEYWORDS.search(r)]
    ai_ratio = len(ai_repos) / len(repo_names) if repo_names else 0.0

    return GitHubOrgResult(
        org_slug=org_slug,
        total_repos=total_repos,
        ai_repos=ai_repos,
        ai_ratio=round(ai_ratio, 3),
        scraped_at=scraped_at,
    )


async def get_ai_signal(org_slug: str) -> Optional[dict]:
    """
    Fetch a GitHub org page and return an AI signal dict, or None on failure.

    Return dict keys:
      org_slug, ai_repo_count, total_repos, ai_ratio, ai_repos, confidence
    """
    url = f"https://github.com/{org_slug}"
    loop = asyncio.get_event_loop()

    html: Optional[str] = await loop.run_in_executor(None, _fetch_html, url)

    # Also try the /repositories listing which shows more repos
    repos_html: Optional[str] = await loop.run_in_executor(
        None, _fetch_html, f"https://github.com/orgs/{org_slug}/repositories"
    )

    if not html and not repos_html:
        logger.warning("Could not fetch any GitHub page for org '%s'", org_slug)
        return None

    combined_repos: list[str] = []
    seen_names: set[str] = set()

    for source_html in [html, repos_html]:
        if not source_html:
            continue
        for name in _parse_org_repos(source_html):
            if name not in seen_names:
                seen_names.add(name)
                combined_repos.append(name)

    # Use the count from the more informative page
    total_repos = 0
    for source_html in [repos_html, html]:
        if source_html:
            total_repos = _count_public_repos(source_html)
            if total_repos > 0:
                break
    if total_repos == 0:
        total_repos = len(combined_repos)

    ai_repos = [r for r in combined_repos if _AI_REPO_KEYWORDS.search(r)]
    ai_repo_count = len(ai_repos)
    ai_ratio = ai_repo_count / len(combined_repos) if combined_repos else 0.0

    # Confidence based on how much data we have
    if len(combined_repos) >= 5:
        confidence = "high"
    elif len(combined_repos) >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "org_slug": org_slug,
        "ai_repo_count": ai_repo_count,
        "total_repos": total_repos,
        "ai_ratio": round(ai_ratio, 3),
        "ai_repos": ai_repos,
        "confidence": confidence,
    }


def get_ai_maturity_signal_from_github(org_slug: str) -> Optional[dict]:
    """
    Synchronous wrapper for get_ai_signal. Calls asyncio.run internally.

    Returns a SignalItem-compatible dict or None.

    Dict keys: signal_type, value, evidence, confidence, language_register
    """
    try:
        result = asyncio.run(get_ai_signal(org_slug))
    except Exception as exc:
        logger.warning("GitHub AI signal failed for '%s': %s", org_slug, exc)
        return None

    if result is None:
        return None

    ai_repo_count = result["ai_repo_count"]
    total_repos = result["total_repos"]
    ai_ratio = result["ai_ratio"]
    ai_repos = result["ai_repos"]
    confidence = result["confidence"]

    # Value string
    if ai_repo_count >= 5:
        value = f"{ai_repo_count} AI/ML repos ({ai_ratio:.0%} of public repos)"
        register = "assert"
    elif ai_repo_count >= 2:
        value = f"{ai_repo_count} AI/ML repos out of {total_repos} public repos"
        register = "hedge"
    elif ai_repo_count == 1:
        value = f"1 AI/ML repo detected ({ai_repos[0]})"
        register = "ask"
    else:
        value = f"No AI/ML repos detected in {total_repos} public repos"
        register = "ask"
        confidence = "low"

    evidence_repos = ", ".join(ai_repos[:6]) if ai_repos else "none"
    evidence = (
        f"GitHub org '{org_slug}': {ai_repo_count} AI/ML repos out of "
        f"{total_repos} public repos. Repos: {evidence_repos}"
    )

    return {
        "signal_type": "github_ai_activity",
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
        "language_register": register,
        # Extra fields for downstream use (not part of SignalItem schema but harmless)
        "org_slug": org_slug,
        "ai_repo_count": ai_repo_count,
        "total_repos": total_repos,
        "ai_ratio": ai_ratio,
        "ai_repos": ai_repos,
    }
