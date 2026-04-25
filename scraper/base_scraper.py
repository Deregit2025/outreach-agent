"""
base_scraper.py — Abstract base class for all Playwright-based scrapers in the
Tenacious signal pipeline.

Provides:
  - Shared async Playwright browser/context lifecycle via async context manager
  - robots.txt compliance check (_is_robots_allowed)
  - Page fetch helper with optional wait selector (_fetch_page)
  - Per-host rate limiting with configurable crawl delay
  - Resource blocking (images, fonts, stylesheets) via route interceptor
  - Realistic user-agent string

Usage:
    class MyScaper(BaseScraper):
        async def run(self):
            async with self as scraper:
                page = await self._context.new_page()
                html = await self._fetch_page(page, "https://example.com")
"""

from __future__ import annotations
 
import asyncio 
import logging
import time
import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default user-agent identifies the bot politely
_USER_AGENT = (
    "Mozilla/5.0 (compatible; TenaciousSDRBot/1.0; "
    "+https://gettenacious.com/bot)"
)

# Resource types to block by default (saves bandwidth, speeds crawl)
_DEFAULT_BLOCKED_RESOURCES = ["image", "font", "stylesheet"]

# Glob patterns for static assets to abort via route handler
_STATIC_ASSET_GLOB = "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,otf,eot}"


class BaseScraper:
    """
    Async context manager base class for Playwright-based scrapers.

    Subclasses inherit browser/context lifecycle, rate limiting, robots.txt
    compliance, and the _fetch_page helper. Override run() to implement
    scraper-specific logic.

    Attributes:
        _crawl_delay: Minimum seconds between requests to the same host.
        _user_agent:  HTTP User-Agent string sent to remote servers.
        _headless:    Whether to launch Chromium in headless mode.
    """

    _crawl_delay: float = 2.0
    _user_agent: str = _USER_AGENT
    _headless: bool = True

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        # Per-host last-request timestamp (monotonic clock)
        self._host_last_request: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseScraper":
        """Launch Playwright, browser, and browser context."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is not installed. Run: pip install playwright && "
                "python -m playwright install chromium"
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless
        )
        self._context = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": 1280, "height": 800},
        )
        logger.debug("BaseScraper: browser context opened")
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb) -> bool:
        """Close browser context and stop Playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.debug("BaseScraper: browser context closed")
        # Do not suppress exceptions
        return False

    # ------------------------------------------------------------------
    # robots.txt compliance
    # ------------------------------------------------------------------

    def _is_robots_allowed(self, url: str, user_agent: str = "*") -> bool:
        """
        Check whether robots.txt permits crawling the given URL.

        Fetches and parses robots.txt from the URL's origin. Returns True
        (permissive) if robots.txt cannot be fetched or parsed, so transient
        network errors do not block the entire crawl.

        Args:
            url:        The page URL to check.
            user_agent: The User-Agent string to match against robots.txt rules.
                        Defaults to "*" (wildcard).

        Returns:
            True if crawling is permitted, False if explicitly disallowed.
        """
        try:
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            rp.read()
            allowed = rp.can_fetch(user_agent, url)
            if not allowed:
                logger.info("robots.txt disallows %s — skipping", url)
            return allowed
        except Exception as exc:
            logger.debug(
                "Could not fetch robots.txt for %s (%s) — assuming allowed",
                url,
                exc,
            )
            return True

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self, url: str) -> None:
        """
        Enforce per-host crawl delay.

        Sleeps the minimum amount needed so that requests to the same host
        are separated by at least self._crawl_delay seconds.
        """
        host = urlparse(url).netloc
        last = self._host_last_request.get(host, 0.0)
        wait = self._crawl_delay - (time.monotonic() - last)
        if wait > 0:
            logger.debug("Rate limiting: sleeping %.2fs before %s", wait, host)
            await asyncio.sleep(wait)

    def _record_request(self, url: str) -> None:
        """Update the per-host last-request timestamp after a fetch."""
        host = urlparse(url).netloc
        self._host_last_request[host] = time.monotonic()

    # ------------------------------------------------------------------
    # Resource blocking
    # ------------------------------------------------------------------

    async def _block_resources(
        self,
        page,
        resource_types: Optional[list[str]] = None,
    ) -> None:
        """
        Attach a Playwright route interceptor that aborts requests for
        resource types that are not needed for text scraping.

        Aborts images/fonts via glob pattern and aborts by resource type
        (stylesheet, image, font, media) for anything matching the list.

        Args:
            page:           An active Playwright Page object.
            resource_types: Resource type strings to block. Defaults to
                            ["image", "font", "stylesheet"].
        """
        if resource_types is None:
            resource_types = list(_DEFAULT_BLOCKED_RESOURCES)
        blocked = set(resource_types)

        # Abort static asset file-extension patterns
        await page.route(
            _STATIC_ASSET_GLOB,
            lambda route: route.abort(),
        )

        # Abort by resource type for anything else in the blocked set
        async def _handle_route(route):
            if route.request.resource_type in blocked:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _handle_route)

    # ------------------------------------------------------------------
    # Page fetch
    # ------------------------------------------------------------------

    async def _fetch_page(
        self,
        page,
        url: str,
        wait_selector: Optional[str] = None,
    ) -> str:
        """
        Navigate to url and return the fully-rendered page HTML.

        Applies rate limiting before the request and records the request
        timestamp after. Waits for DOMContentLoaded, then optionally waits
        for a CSS selector to appear (for JS-rendered content), then allows
        a short JS-render window before capturing HTML.

        Args:
            page:          An active Playwright Page object.
            url:           The URL to navigate to.
            wait_selector: Optional CSS selector to wait for after load,
                           useful for JS-rendered content. Ignored if not
                           found within 5 s (non-fatal).

        Returns:
            The page's outer HTML as a string, or "" on error.
        """
        await self._rate_limit(url)
        try:
            await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=5_000)
                except Exception:
                    pass  # Selector absent; continue with whatever rendered
            # Allow JS rendering to settle
            await page.wait_for_timeout(1_500)
            html = await page.content()
            return html
        except Exception as exc:
            logger.warning("Failed to load %s: %s", url, exc)
            return ""
        finally:
            self._record_request(url)
