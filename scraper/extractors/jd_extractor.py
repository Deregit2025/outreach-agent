"""
jd_extractor.py — Extract job postings from HTML page content.

Used by job_scraper.py after Playwright fetches page HTML.
Handles Wellfound, BuiltIn, and generic careers-page layouts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup

ENGINEERING_KEYWORDS: set[str] = {
    "engineer", "engineering", "developer", "dev", "architect", "sre",
    "devops", "mlops", "data", "scientist", "ml", "ai", "platform",
    "backend", "frontend", "fullstack", "full stack", "full-stack",
    "infrastructure", "infra", "cloud", "security", "reliability",
    "software", "systems", "embedded", "mobile", "ios", "android",
    "api", "microservice", "algorithm", "research",
}

NON_ENGINEERING_KEYWORDS: set[str] = {
    "sales", "marketing", "recruiter", "recruiting", "hr", "finance",
    "accountant", "legal", "counsel", "designer", "ux", "ui designer",
    "content", "communications", "pr ", "office", "operations manager",
    "customer success", "support", "account executive",
}


@dataclass
class JobPost:
    title: str
    department: Optional[str] = None
    location: Optional[str] = None
    date_posted: Optional[str] = None
    url: Optional[str] = None
    is_engineering: bool = False


def _is_engineering_role(title: str) -> bool:
    tl = title.lower()
    if any(kw in tl for kw in NON_ENGINEERING_KEYWORDS):
        return False
    return any(kw in tl for kw in ENGINEERING_KEYWORDS)


def _clean_title(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()


def extract_from_wellfound(html: str, base_url: str = "") -> list[JobPost]:
    """Parse Wellfound /jobs page HTML."""
    soup = BeautifulSoup(html, "lxml")
    posts: list[JobPost] = []

    # Wellfound uses <a> tags with job role text inside data-test or aria labels
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not ("/jobs/" in href or "/job/" in href):
            continue
        title_text = _clean_title(a.get_text(separator=" "))
        if not title_text or len(title_text) < 4:
            continue
        url = href if href.startswith("http") else f"https://wellfound.com{href}"
        posts.append(JobPost(
            title=title_text,
            url=url,
            is_engineering=_is_engineering_role(title_text),
        ))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[JobPost] = []
    for p in posts:
        key = p.url or p.title
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def extract_from_builtin(html: str, base_url: str = "") -> list[JobPost]:
    """Parse BuiltIn /jobs page HTML."""
    soup = BeautifulSoup(html, "lxml")
    posts: list[JobPost] = []

    # BuiltIn renders job cards with <a> data-id or class="job-bounded-responsive-link"
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/job/" not in href and "/jobs/" not in href:
            continue
        title_el = a.find(["h2", "h3", "span", "div"])
        title_text = _clean_title(title_el.get_text() if title_el else a.get_text(separator=" "))
        if not title_text or len(title_text) < 4:
            continue
        url = href if href.startswith("http") else f"https://builtin.com{href}"

        # Department hint from parent container
        dept = None
        parent = a.parent
        if parent:
            dept_el = parent.find(class_=re.compile(r"dept|category|function", re.I))
            if dept_el:
                dept = _clean_title(dept_el.get_text())

        posts.append(JobPost(
            title=title_text,
            department=dept,
            url=url,
            is_engineering=_is_engineering_role(title_text),
        ))

    seen: set[str] = set()
    unique: list[JobPost] = []
    for p in posts:
        key = p.url or p.title
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def extract_generic(html: str, base_url: str = "") -> list[JobPost]:
    """
    Generic extractor for company careers pages.

    Heuristic: find headings or list items that look like job titles.
    Prioritises h2/h3 elements whose text contains engineering keywords.
    """
    soup = BeautifulSoup(html, "lxml")
    posts: list[JobPost] = []
    seen_titles: set[str] = set()

    # Strategy 1: anchor tags whose visible text is a job title
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"job|career|opening|position|role|apply", href, re.I):
            continue
        raw = _clean_title(a.get_text(separator=" "))
        if not raw or len(raw) < 6 or len(raw) > 120:
            continue
        if raw in seen_titles:
            continue
        seen_titles.add(raw)
        url = href if href.startswith("http") else (base_url.rstrip("/") + "/" + href.lstrip("/"))
        posts.append(JobPost(
            title=raw,
            url=url,
            is_engineering=_is_engineering_role(raw),
        ))

    # Strategy 2: h2/h3/li elements with engineering keywords
    for tag in soup.find_all(["h2", "h3", "li"]):
        raw = _clean_title(tag.get_text(separator=" "))
        if not raw or len(raw) < 6 or len(raw) > 120:
            continue
        if raw in seen_titles:
            continue
        if not _is_engineering_role(raw):
            continue
        seen_titles.add(raw)
        posts.append(JobPost(
            title=raw,
            is_engineering=True,
        ))

    return posts
