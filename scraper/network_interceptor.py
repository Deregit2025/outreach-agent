"""
network_interceptor.py — Playwright network-layer utilities for the Tenacious
signal pipeline.

Provides three composable helpers that attach route/response handlers to an
active Playwright Page:

  - block_resources  : abort requests for expensive resource types so pages
                       load faster during text scraping.
  - log_requests     : log XHR/fetch requests to a Python logger, optionally
                       filtered by URL pattern; useful for discovering hidden
                       API endpoints that serve job data.
  - intercept_json_api: capture JSON response bodies from URLs matching a
                       regex pattern; stores results in self.captured so the
                       caller can inspect them after navigation.

All methods are async and designed to be called on a page before navigation.

Usage:
    interceptor = NetworkInterceptor()
    page = await context.new_page()

    await interceptor.block_resources(page)
    await interceptor.log_requests(page, filter_pattern=r"api.*jobs")
    await interceptor.intercept_json_api(page, url_pattern=r"/graphql")

    await page.goto("https://example.com/jobs")
    print(interceptor.captured)   # list of parsed JSON dicts
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Resource types that carry no useful text for scraping
_DEFAULT_BLOCKED_TYPES: list[str] = ["image", "font", "stylesheet", "media"]

# File-extension glob that aborts common static assets before type check
_ASSET_GLOB = "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,otf,eot,mp4,mp3}"


class NetworkInterceptor:
    """
    Attaches Playwright network handlers to a page to block, log, or
    capture network traffic.

    Attributes:
        captured: List of JSON payloads captured by intercept_json_api.
                  Each entry is a dict with keys "url" and "body".
    """

    def __init__(self) -> None:
        self.captured: list[dict] = []

    # ------------------------------------------------------------------
    # Resource blocking
    # ------------------------------------------------------------------

    async def block_resources(
        self,
        page,
        resource_types: Optional[list[str]] = None,
    ) -> None:
        """
        Attach route handlers that abort requests for non-text resource types.

        Aborts known static-asset file extensions via glob pattern first, then
        aborts any request whose Playwright resource_type is in resource_types.
        This significantly reduces page-load time and bandwidth during crawls.

        Args:
            page:           An active Playwright Page object.
            resource_types: Resource type strings to block. Defaults to
                            ["image", "font", "stylesheet", "media"].
        """
        if resource_types is None:
            resource_types = list(_DEFAULT_BLOCKED_TYPES)
        blocked = frozenset(resource_types)

        # Fast path: abort common asset file extensions by glob
        await page.route(_ASSET_GLOB, lambda route: route.abort())

        # Slower path: inspect resource type for everything else
        async def _type_blocker(route):
            if route.request.resource_type in blocked:
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _type_blocker)
        logger.debug(
            "block_resources: blocking resource types %s", sorted(blocked)
        )

    # ------------------------------------------------------------------
    # Request logging
    # ------------------------------------------------------------------

    async def log_requests(
        self,
        page,
        filter_pattern: Optional[str] = None,
    ) -> None:
        """
        Attach a handler that logs XHR and fetch requests to the Python logger.

        Only requests whose resource_type is "xhr" or "fetch" are logged.
        If filter_pattern is supplied, only requests whose URL matches the
        compiled regex are logged.

        This is useful for discovering hidden JSON API endpoints that serve
        job-listing data which is not present in the static HTML.

        Args:
            page:           An active Playwright Page object.
            filter_pattern: Optional regex string. When supplied, only requests
                            whose URL matches are logged.
        """
        compiled: Optional[re.Pattern] = None
        if filter_pattern:
            compiled = re.compile(filter_pattern, re.I)

        def _on_request(request) -> None:
            if request.resource_type not in ("xhr", "fetch"):
                return
            url = request.url
            if compiled and not compiled.search(url):
                return
            logger.info(
                "[NetworkInterceptor] %s %s", request.method, url
            )

        page.on("request", _on_request)
        logger.debug(
            "log_requests: listening for XHR/fetch (pattern=%r)", filter_pattern
        )

    # ------------------------------------------------------------------
    # JSON API interception
    # ------------------------------------------------------------------

    async def intercept_json_api(
        self,
        page,
        url_pattern: str,
    ) -> None:
        """
        Capture JSON response bodies from URLs matching url_pattern.

        Attaches a 'response' event listener on the page. Whenever a response
        arrives whose URL matches the regex, the response body is read and
        parsed as JSON. Successful parses are appended to self.captured as
        dicts with keys:
            - "url":  the matched response URL
            - "body": the parsed JSON value (dict or list)

        Responses that cannot be parsed as JSON are silently skipped.

        Args:
            page:        An active Playwright Page object.
            url_pattern: Regex string matched against each response URL.
        """
        compiled = re.compile(url_pattern, re.I)

        async def _on_response(response) -> None:
            url = response.url
            if not compiled.search(url):
                return
            try:
                body = await response.body()
                data = json.loads(body)
                self.captured.append({"url": url, "body": data})
                logger.info(
                    "[NetworkInterceptor] captured JSON from %s (%d bytes)",
                    url,
                    len(body),
                )
            except Exception:
                # Not JSON or body unavailable — skip silently
                pass

        page.on("response", _on_response)
        logger.debug(
            "intercept_json_api: watching responses matching %r", url_pattern
        )
