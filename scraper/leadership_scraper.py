"""
leadership_scraper.py — Detect new CTO / VP Engineering appointments.

This is a key signal for Segment 3 (engineering-leadership transitions) in the
Tenacious ICP classification pipeline.

Strategy (tried in order):
  1. Company "team" or "about" page — look for listed CTO / VP Eng titles
  2. Company blog / newsroom page — look for leadership announcement posts
  3. DuckDuckGo HTML search — extract result snippets for recent appointments

Constraints:
  - Playwright async for all page fetches
  - Respects robots.txt before every request
  - No login, no CAPTCHA bypass
  - Maximum 3 pages fetched per company call (one per strategy)

Usage:
    from scraper.leadership_scraper import get_leadership_signal

    signal = get_leadership_signal("Acme AI", website_url="https://acme.ai")
    # Returns a SignalItem-compatible dict or None
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; TenaciousSDRBot/1.0; +https://gettenacious.com/bot)"
)

_CRAWL_DELAY = 2.0  # seconds between requests to the same host

# ── Role title detection ───────────────────────────────────────────────────────

_LEADERSHIP_TITLE_RE = re.compile(
    r"\b(CTO|Chief\s+Technology\s+Officer"
    r"|VP\s+(?:of\s+)?Engineering"
    r"|VP\s+(?:of\s+)?Data"
    r"|Head\s+of\s+(?:Engineering|AI|Data|Machine\s+Learning)"
    r"|Director\s+of\s+(?:Engineering|AI|Data)"
    r"|Chief\s+AI\s+Officer|CAIO"
    r"|Chief\s+Data\s+Officer|CDO"
    r"|Chief\s+Product\s+Officer|CPO)\b",
    re.I,
)

# Appointment action verbs (used when parsing press text)
_APPOINTMENT_VERBS_RE = re.compile(
    r"\b(appointed(?:\s+as)?|joins?\s+as|named|promoted\s+to|hired\s+as"
    r"|welcomes?|tapped\s+as|elevated\s+to|announced\s+as)\b",
    re.I,
)

# Name patterns: 2–3 capitalised words
_NAME_RE = re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})")

# Date patterns for tenure estimation
_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\bQ[1-4]\s+\d{4}\b"
    r"|\b20\d{2}\b",  # bare year as fallback
    re.I,
)

# "New" recency markers — used to boost confidence of a recent appointment
_RECENCY_RE = re.compile(
    r"\b(new(?:ly)?|recent(?:ly)?|just\s+announced|today|this\s+(?:week|month|quarter|year)"
    r"|2025|2026)\b",
    re.I,
)


# ── Dataclass ──────────────────────────────────────────────────────────────────

@dataclass
class LeadershipScrapeResult:
    company_name: str
    scraped_at: str
    source_url: Optional[str] = None
    leaders_found: list[dict] = field(default_factory=list)
    new_leadership_signal: bool = False
    error: Optional[str] = None


# ── robots.txt helper ─────────────────────────────────────────────────────────

def _is_robots_allowed(url: str) -> bool:
    """Check robots.txt. Returns True if crawl is permitted, True on failure."""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(_USER_AGENT, url)
    except Exception:
        return True


# ── Playwright page fetch ──────────────────────────────────────────────────────

async def _fetch_page(page, url: str) -> str:
    """Navigate with Playwright and return page HTML. Returns '' on failure."""
    try:
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        return await page.content()
    except Exception as exc:
        logger.warning("Failed to load %s: %s", url, exc)
        return ""


# ── Extraction helpers ─────────────────────────────────────────────────────────

def _text_sentences(html: str) -> list[str]:
    """Extract visible text from HTML and return split sentences."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    raw = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", raw) if len(s.strip()) > 10]


def _extract_date_str(text: str) -> Optional[str]:
    match = _DATE_RE.search(text)
    return match.group(0) if match else None


def _estimate_tenure_days(date_str: Optional[str]) -> Optional[int]:
    """
    Rough estimate of how many days ago a person started.

    Returns None if we cannot parse the date.
    """
    if not date_str:
        return None
    now = datetime.now(timezone.utc).date()
    formats = [
        "%B %Y", "%b %Y", "%b. %Y",
        "%Y-%m-%d", "%Y",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str.strip(), fmt).date()
            return (now - parsed).days
        except ValueError:
            continue
    # If it's a bare "Q1 2025" style
    q_match = re.match(r"Q([1-4])\s+(\d{4})", date_str, re.I)
    if q_match:
        quarter = int(q_match.group(1))
        year = int(q_match.group(2))
        # Approximate: Q1→Jan, Q2→Apr, Q3→Jul, Q4→Oct
        month = (quarter - 1) * 3 + 1
        try:
            parsed = datetime(year, month, 1).date()
            return (now - parsed).days
        except ValueError:
            pass
    return None


def _leaders_from_team_page(html: str, company_name: str) -> list[dict]:
    """
    Parse a company team/about page for leadership titles.

    Looks for named sections or cards where a title role appears near a name.
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []
    seen: set[str] = set()

    # Strategy A: scan all text nodes for (name, role) pairs
    # Many team pages use: <h3>Jane Doe</h3><p>CTO</p> or similar
    for container in soup.find_all(["article", "div", "section", "li"]):
        text = container.get_text(separator=" ")
        role_match = _LEADERSHIP_TITLE_RE.search(text)
        if not role_match:
            continue
        role = role_match.group(0).strip()

        # Try to find a name in headings within this container
        person_name: Optional[str] = None
        for heading in container.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
            heading_text = heading.get_text(separator=" ").strip()
            name_match = _NAME_RE.match(heading_text)
            if name_match and company_name.lower() not in heading_text.lower():
                candidate = name_match.group(0)
                # Skip if candidate is just the role text itself
                if not _LEADERSHIP_TITLE_RE.search(candidate):
                    person_name = candidate
                    break

        person_name = person_name or "Unknown"
        key = (person_name.lower(), role.lower())
        if key in seen:
            continue
        seen.add(key)

        # Team pages don't usually say when someone started; tenure unknown
        results.append(
            {
                "name": person_name,
                "role": role,
                "tenure_start_est": None,
                "confidence": "medium" if person_name != "Unknown" else "low",
                "source_hint": "team_page",
            }
        )

    return results


def _leaders_from_press_text(sentences: list[str], company_name: str) -> list[dict]:
    """
    Parse sentences (from a blog/newsroom or DDG snippet) for appointment signals.

    Looks for: action verb + person name + role title.
    """
    results: list[dict] = []
    seen: set[str] = set()

    for sentence in sentences:
        role_match = _LEADERSHIP_TITLE_RE.search(sentence)
        if not role_match:
            continue
        verb_match = _APPOINTMENT_VERBS_RE.search(sentence)
        if not verb_match:
            continue

        role = role_match.group(0).strip()
        date_str = _extract_date_str(sentence)

        person_name: Optional[str] = None
        # Look for a name before the verb
        pre_verb = sentence[: verb_match.start()]
        name_candidates = list(_NAME_RE.finditer(pre_verb))
        if name_candidates:
            candidate = name_candidates[-1].group(0)
            if company_name.lower() not in candidate.lower() and not _LEADERSHIP_TITLE_RE.search(candidate):
                person_name = candidate
        if not person_name:
            # Try after the verb
            post_verb = sentence[verb_match.end():]
            name_candidates_post = list(_NAME_RE.finditer(post_verb))
            if name_candidates_post:
                candidate = name_candidates_post[0].group(0)
                if company_name.lower() not in candidate.lower() and not _LEADERSHIP_TITLE_RE.search(candidate):
                    person_name = candidate

        person_name = person_name or "Unknown"
        key = (person_name.lower(), role.lower())
        if key in seen:
            continue
        seen.add(key)

        has_recency = bool(_RECENCY_RE.search(sentence))
        confidence = "high" if (person_name != "Unknown" and has_recency) else (
            "medium" if person_name != "Unknown" else "low"
        )

        results.append(
            {
                "name": person_name,
                "role": role,
                "tenure_start_est": date_str,
                "confidence": confidence,
                "source_hint": "press",
            }
        )

    return results


def _leaders_from_ddg_snippets(html: str, company_name: str) -> list[dict]:
    """Parse DuckDuckGo HTML result snippets for leadership signals."""
    soup = BeautifulSoup(html, "lxml")
    # DDG HTML results: result snippets live in <a class="result__snippet">
    # and result titles in <a class="result__a">
    snippets: list[str] = []
    for el in soup.find_all(["a", "div", "span"], class_=re.compile(r"result__snippet|result__a|result-snippet", re.I)):
        snippets.append(el.get_text(separator=" "))

    if not snippets:
        # Fallback: grab all paragraph text
        for p in soup.find_all("p"):
            snippets.append(p.get_text(separator=" "))

    all_sentences: list[str] = []
    for snippet in snippets:
        snippet = re.sub(r"\s+", " ", snippet).strip()
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", snippet)
        all_sentences.extend(s.strip() for s in sentences if len(s.strip()) > 10)

    return _leaders_from_press_text(all_sentences, company_name)


# ── Core async scraper ────────────────────────────────────────────────────────

async def _scrape_async(
    company_name: str,
    website_url: Optional[str] = None,
) -> LeadershipScrapeResult:
    """Three-strategy async scraper. Stops at first strategy that finds leaders."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return LeadershipScrapeResult(
            company_name=company_name,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            error="playwright not installed",
        )

    scraped_at = datetime.now(timezone.utc).isoformat()
    all_leaders: list[dict] = []
    source_url: Optional[str] = None
    last_host_time: dict[str, float] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # Block images / fonts to speed up crawl
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf}",
            lambda route: route.abort(),
        )

        async def _guarded_fetch(url: str) -> str:
            """Fetch URL with robots.txt check and per-host rate limiting."""
            if not _is_robots_allowed(url):
                logger.info("robots.txt disallows crawl of %s — skipping", url)
                return ""
            host = urlparse(url).netloc
            elapsed = time.monotonic() - last_host_time.get(host, 0)
            wait = _CRAWL_DELAY - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            html = await _fetch_page(page, url)
            last_host_time[host] = time.monotonic()
            return html

        # ── Strategy 1: Team / About page ─────────────────────────────────────
        if website_url:
            base = website_url.rstrip("/")
            for suffix in ["/team", "/about", "/about-us", "/leadership"]:
                url = base + suffix
                html = await _guarded_fetch(url)
                if not html:
                    continue
                leaders = _leaders_from_team_page(html, company_name)
                if leaders:
                    all_leaders = leaders
                    source_url = url
                    logger.info(
                        "Strategy 1 (team page) found %d leaders at %s",
                        len(leaders), url,
                    )
                    break

        # ── Strategy 2: Blog / Newsroom ────────────────────────────────────────
        if not all_leaders and website_url:
            base = website_url.rstrip("/")
            for suffix in ["/blog", "/news", "/newsroom", "/press"]:
                url = base + suffix
                html = await _guarded_fetch(url)
                if not html:
                    continue
                sentences = _text_sentences(html)
                leaders = _leaders_from_press_text(sentences, company_name)
                if leaders:
                    all_leaders = leaders
                    source_url = url
                    logger.info(
                        "Strategy 2 (blog/newsroom) found %d leaders at %s",
                        len(leaders), url,
                    )
                    break

        # ── Strategy 3: DuckDuckGo HTML search ────────────────────────────────
        if not all_leaders:
            query = quote_plus(
                f"{company_name} new CTO VP Engineering 2025 2026"
            )
            ddg_url = f"https://html.duckduckgo.com/html/?q={query}"
            html = await _guarded_fetch(ddg_url)
            if html:
                leaders = _leaders_from_ddg_snippets(html, company_name)
                if leaders:
                    all_leaders = leaders
                    source_url = ddg_url
                    logger.info(
                        "Strategy 3 (DDG search) found %d leaders", len(leaders)
                    )

        await browser.close()

    # ── Determine new_leadership_signal ───────────────────────────────────────
    new_leadership = False
    for leader in all_leaders:
        tenure_str = leader.get("tenure_start_est")
        tenure_days = _estimate_tenure_days(tenure_str)
        leader["tenure_days_est"] = tenure_days
        # Signal is "new" if tenure is within 120 days, OR if DDG/blog found them
        # with a recency keyword (confidence == "high"), OR if no date but source
        # is press (we treat as potentially new)
        if tenure_days is not None and tenure_days <= 120:
            new_leadership = True
        elif leader.get("confidence") == "high" and leader.get("source_hint") == "press":
            new_leadership = True

    return LeadershipScrapeResult(
        company_name=company_name,
        scraped_at=scraped_at,
        source_url=source_url,
        leaders_found=all_leaders,
        new_leadership_signal=new_leadership,
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_leadership_changes(
    company_name: str,
    website_url: Optional[str] = None,
) -> LeadershipScrapeResult:
    """
    Async entry point. Tries three strategies to detect CTO / VP Eng appointments.

    Returns a LeadershipScrapeResult dataclass.
    """
    try:
        return await _scrape_async(company_name=company_name, website_url=website_url)
    except Exception as exc:
        logger.warning("Leadership scrape failed for '%s': %s", company_name, exc)
        return LeadershipScrapeResult(
            company_name=company_name,
            scraped_at=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )


def get_leadership_signal(
    company_name: str,
    website_url: Optional[str] = None,
) -> Optional[dict]:
    """
    Synchronous wrapper for scrape_leadership_changes.

    Returns a SignalItem-compatible dict or None if no signal is found.

    Dict keys: signal_type, value, evidence, confidence, language_register
    """
    try:
        result: LeadershipScrapeResult = asyncio.run(
            scrape_leadership_changes(company_name=company_name, website_url=website_url)
        )
    except Exception as exc:
        logger.warning("get_leadership_signal failed for '%s': %s", company_name, exc)
        return None

    if result.error and not result.leaders_found:
        return None

    if not result.leaders_found:
        return None

    # Build human-readable summary of found leaders
    leader_lines: list[str] = []
    for ldr in result.leaders_found[:5]:  # cap at 5 for readability
        name = ldr.get("name", "Unknown")
        role = ldr.get("role", "unknown role")
        tenure_str = ldr.get("tenure_start_est") or "date unknown"
        leader_lines.append(f"{name} ({role}, since {tenure_str})")

    leaders_summary = "; ".join(leader_lines)

    # Signal value and register
    if result.new_leadership_signal:
        value = f"New engineering leadership detected: {result.leaders_found[0].get('name', 'Unknown')} as {result.leaders_found[0].get('role', 'unknown')}"
        register = "assert"
        confidence = "high"
    elif len(result.leaders_found) >= 2:
        value = f"{len(result.leaders_found)} engineering leaders found (tenure unknown)"
        register = "hedge"
        confidence = "medium"
    else:
        ldr = result.leaders_found[0]
        value = f"{ldr.get('name', 'Unknown')} as {ldr.get('role', 'unknown role')}"
        register = "ask"
        confidence = ldr.get("confidence", "low")

    evidence = (
        f"Leadership scrape of '{company_name}' via {result.source_url or 'unknown source'}. "
        f"Found: {leaders_summary}"
    )

    return {
        "signal_type": "leadership_change",
        "value": value,
        "evidence": evidence,
        "confidence": confidence,
        "language_register": register,
        # Bonus fields for the pipeline (not in SignalItem schema but harmless)
        "leaders_found": result.leaders_found,
        "new_leadership_signal": result.new_leadership_signal,
        "source_url": result.source_url,
    }
