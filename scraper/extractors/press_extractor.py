"""
press_extractor.py — Extract leadership, funding, and AI signals from press release HTML.

Used by the Tenacious signal pipeline to parse public press releases from sources
such as TechCrunch, VentureBeat, company blogs, PR Newswire, and LinkedIn articles.

Constraints:
  - Pure HTML parsing — no network calls, no login, no CAPTCHA bypass
  - Inputs are pre-fetched HTML strings
  - All returned dicts are JSON-serialisable
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# ── Role title patterns ────────────────────────────────────────────────────────

_LEADERSHIP_ROLE_RE = re.compile(
    r"\b(CTO|VP\s+Engineering|VP\s+of\s+Engineering|Chief\s+Technology(?:\s+Officer)?"
    r"|Head\s+of\s+Engineering|Head\s+of\s+AI|VP\s+Data|VP\s+of\s+Data"
    r"|Chief\s+AI\s+Officer|CAIO|Chief\s+Data\s+Officer|CDO"
    r"|VP\s+of\s+Product|Chief\s+Product\s+Officer|CPO)\b",
    re.I,
)

# Action verbs that introduce a leadership appointment
_APPOINTMENT_VERBS_RE = re.compile(
    r"\b(appointed(?:\s+as)?|joins?\s+as|named|promoted\s+to|hired\s+as"
    r"|announced\s+as|selected\s+as|welcomes?|tapped\s+as|elevated\s+to)\b",
    re.I,
)

# Name: two or more capitalised words (First [Middle] Last)
_NAME_RE = re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})")

# Approximate date patterns: "January 2025", "Jan. 2025", "2025-01-15", "Q1 2025"
_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December"
    r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\bQ[1-4]\s+\d{4}\b",
    re.I,
)

# ── Funding patterns ───────────────────────────────────────────────────────────

_DOLLAR_AMOUNT_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?(?:\s*(?:M(?:illion)?|B(?:illion)?|K(?:ilo)?))?\b",
    re.I,
)

_FUNDING_KEYWORDS_RE = re.compile(
    r"\b(raised?|Series\s+[A-E]|seed\s+round|funding\s+round|investment|secured|closed"
    r"|pre-?seed|Series\s+[A-E]\+?|growth\s+equity|venture)\b",
    re.I,
)

_ROUND_TYPE_RE = re.compile(
    r"\b(pre-?seed|seed|Series\s+[A-E]\+?|growth\s+equity|strategic\s+investment"
    r"|venture|bridge)\b",
    re.I,
)

# ── AI/ML strategic language ──────────────────────────────────────────────────

_AI_KEYWORDS = [
    "AI strategy",
    "machine learning",
    "LLM",
    "large language model",
    "generative AI",
    "GenAI",
    "artificial intelligence",
    "MLOps",
    "deep learning",
    "natural language processing",
    "NLP",
    "computer vision",
    "data science",
    "RAG",
    "retrieval-augmented generation",
    "neural network",
    "foundation model",
    "AI infrastructure",
    "AI platform",
    "AI-powered",
    "AI-driven",
]

_AI_KEYWORD_RE = re.compile(
    "|".join(re.escape(kw) for kw in _AI_KEYWORDS),
    re.I,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_text_sentences(html: str) -> list[str]:
    """Extract visible text from HTML and split into sentences."""
    soup = BeautifulSoup(html, "lxml")
    # Remove script / style noise
    for tag in soup(["script", "style", "noscript", "meta", "head"]):
        tag.decompose()
    raw_text = soup.get_text(separator=" ")
    # Collapse whitespace
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    # Split on sentence boundaries (period/exclamation/question + space + capital)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", raw_text)
    return [s.strip() for s in sentences if len(s.strip()) > 10]


def _extract_date_from_text(text: str) -> Optional[str]:
    match = _DATE_RE.search(text)
    return match.group(0) if match else None


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_leadership_changes(html: str, company_name: str) -> list[dict]:
    """
    Parse HTML for leadership appointment signals.

    Looks for sentences combining:
      - A capitalised person name
      - An appointment verb (appointed as, joins as, named, promoted to, …)
      - A target role title (CTO, VP Engineering, Head of AI, …)

    Returns a list of dicts:
      {person_name, role, action, date_str, confidence}

    confidence: "high" when all three elements (name + verb + role) are in the
                same sentence; "medium" when role + verb present but name inferred.
    """
    sentences = _get_text_sentences(html)
    results: list[dict] = []
    seen: set[str] = set()  # deduplicate by (person_name, role)

    for sentence in sentences:
        role_match = _LEADERSHIP_ROLE_RE.search(sentence)
        if not role_match:
            continue
        verb_match = _APPOINTMENT_VERBS_RE.search(sentence)
        if not verb_match:
            continue

        role = role_match.group(0).strip()
        action = verb_match.group(0).strip()
        date_str = _extract_date_from_text(sentence)

        # Try to extract a person name: words that appear *before* the verb
        # and look like a proper name (two+ capitalised tokens)
        person_name: Optional[str] = None
        pre_verb = sentence[: verb_match.start()]
        # Look backward for a proper-name cluster
        name_matches = list(_NAME_RE.finditer(pre_verb))
        if name_matches:
            # Prefer the name closest to the verb
            candidate = name_matches[-1].group(0)
            # Reject if it's the company name itself
            if company_name.lower() not in candidate.lower():
                person_name = candidate

        if person_name is None:
            # Try right after the verb
            post_verb = sentence[verb_match.end():]
            name_matches_post = list(_NAME_RE.finditer(post_verb))
            if name_matches_post:
                candidate = name_matches_post[0].group(0)
                if company_name.lower() not in candidate.lower():
                    person_name = candidate

        confidence = "high" if person_name else "medium"
        person_name = person_name or "Unknown"

        key = (person_name.lower(), role.lower())
        if key in seen:
            continue
        seen.add(key)

        results.append(
            {
                "person_name": person_name,
                "role": role,
                "action": action,
                "date_str": date_str,
                "confidence": confidence,
            }
        )

    return results


def extract_funding_mentions(html: str) -> list[dict]:
    """
    Find sentences that mention a dollar amount alongside a funding keyword.

    Returns a list of dicts:
      {amount_str, round_type, date_str, confidence}

    confidence: "high" when both a dollar amount and a round-type label are found;
                "medium" when only a dollar amount + generic funding verb is present.
    """
    sentences = _get_text_sentences(html)
    results: list[dict] = []
    seen_amounts: set[str] = set()

    for sentence in sentences:
        # Must have a dollar amount
        amount_match = _DOLLAR_AMOUNT_RE.search(sentence)
        if not amount_match:
            continue
        # Must have a funding keyword nearby (within the sentence)
        if not _FUNDING_KEYWORDS_RE.search(sentence):
            continue

        amount_str = amount_match.group(0).strip()
        if amount_str in seen_amounts:
            continue
        seen_amounts.add(amount_str)

        round_match = _ROUND_TYPE_RE.search(sentence)
        round_type = round_match.group(0).strip() if round_match else "funding round"
        date_str = _extract_date_from_text(sentence)
        confidence = "high" if round_match else "medium"

        results.append(
            {
                "amount_str": amount_str,
                "round_type": round_type,
                "date_str": date_str,
                "confidence": confidence,
            }
        )

    return results


def extract_ai_mentions(html: str) -> list[dict]:
    """
    Find sentences containing AI/ML strategic language.

    Returns a list of dicts:
      {sentence, keyword, confidence}

    confidence is always "medium" — AI mentions in press are strategic intent, not proof.
    """
    sentences = _get_text_sentences(html)
    results: list[dict] = []
    seen_sentences: set[str] = set()

    for sentence in sentences:
        match = _AI_KEYWORD_RE.search(sentence)
        if not match:
            continue
        key = sentence.lower()[:120]
        if key in seen_sentences:
            continue
        seen_sentences.add(key)

        results.append(
            {
                "sentence": sentence[:400],  # cap to avoid huge payloads
                "keyword": match.group(0),
                "confidence": "medium",
            }
        )

    return results


def classify_press_source(url: str) -> str:
    """
    Classify a press release URL into a source category.

    Returns one of:
      "techcrunch" | "venturebeat" | "company_blog" | "pr_newswire"
      | "linkedin" | "businesswire" | "other"
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "other"

    # Strip leading "www."
    host = re.sub(r"^www\.", "", host)

    if "techcrunch.com" in host:
        return "techcrunch"
    if "venturebeat.com" in host:
        return "venturebeat"
    if "prnewswire.com" in host:
        return "pr_newswire"
    if "businesswire.com" in host:
        return "businesswire"
    if "linkedin.com" in host:
        return "linkedin"
    if "globenewswire.com" in host:
        return "pr_newswire"
    if "accesswire.com" in host or "einpresswire.com" in host or "newswire.com" in host:
        return "pr_newswire"

    # Heuristic: path contains /blog/ or /news/ → company blog
    try:
        path = urlparse(url).path.lower()
    except Exception:
        path = ""
    if re.search(r"/(blog|news|newsroom|press)/", path):
        return "company_blog"

    return "other"
