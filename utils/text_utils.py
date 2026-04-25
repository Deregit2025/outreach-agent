"""
text_utils.py — String normalisation and extraction helpers used across the project.

Functions are stateless and dependency-free (stdlib only).
"""

from __future__ import annotations

import html
import re
from typing import Optional


# ── Company name suffix tokens to strip ──────────────────────────────────────
_COMPANY_SUFFIXES: list[str] = [
    # Legal forms — longer patterns first to avoid partial matches
    r"\bpublic limited company\b",
    r"\blimited liability company\b",
    r"\blimited liability partnership\b",
    r"\bprivate limited\b",
    r"\bincorporated\b",
    r"\bcorporation\b",
    r"\bcompany\b",
    r"\blimited\b",
    r"\binc\.?",
    r"\bllc\.?",
    r"\bltd\.?",
    r"\bcorp\.?",
    r"\bco\.?",
    r"\bplc\.?",
    r"\bllp\.?",
    r"\bgmbh\.?",
    r"\bs\.a\.?",
    r"\bb\.v\.?",
    # Domain suffixes that sometimes appear in company names
    r"\.com\b",
    r"\.io\b",
    r"\.ai\b",
    r"\.co\b",
]
_SUFFIX_RE = re.compile(
    r"(?i)(?:" + "|".join(_COMPANY_SUFFIXES) + r")",
)

# Dollar / amount extraction
_DOLLAR_PATTERN = re.compile(
    r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|million|thousand|[BbMmKk])\b"
    r"|([0-9]+(?:\.[0-9]+)?)\s*(billion|million|thousand)\s+dollars?",
    re.I,
)
_UNIT_MAP: dict[str, str] = {
    "billion": "B", "b": "B",
    "million": "M", "m": "M",
    "thousand": "K", "k": "K",
}


def slugify(text: str) -> str:
    """
    Convert *text* to a URL-safe slug.

    - Lowercases
    - Replaces any run of non-alphanumeric characters with a single hyphen
    - Strips leading/trailing hyphens

    Example:
        "Acme Corp, Inc.!" → "acme-corp-inc"
    """
    if not text:
        return ""
    lowered = text.lower()
    # Replace non-alphanumeric runs with a hyphen
    slugged = re.sub(r"[^a-z0-9]+", "-", lowered)
    return slugged.strip("-")


def truncate(text: str, max_chars: int, suffix: str = "...") -> str:
    """
    Return *text* truncated to *max_chars* characters, appending *suffix* if cut.

    The total length of the returned string including *suffix* will not exceed
    *max_chars* (suffix is inserted within the budget).
    """
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    cut = max_chars - len(suffix)
    if cut <= 0:
        return suffix[:max_chars]
    return text[:cut] + suffix


def normalize_company_name(name: str) -> str:
    """
    Normalise a company name for comparison or deduplication.

    Steps:
      1. Strip legal / domain suffixes (Inc., LLC, .com, etc.)
      2. Collapse extra whitespace
      3. Strip leading/trailing whitespace
      4. Lowercase

    Example:
        "Acme Solutions, Inc."   → "acme solutions"
        "DataBricks.com"         → "databricks"
        "OpenAI, LLC"            → "openai"
    """
    if not name:
        return ""
    normalised = _SUFFIX_RE.sub("", name)
    # Remove trailing commas or periods left after suffix removal
    normalised = re.sub(r"[,.\s]+$", "", normalised)
    normalised = re.sub(r"\s+", " ", normalised).strip().lower()
    return normalised


def extract_dollar_amount(text: str) -> tuple[Optional[float], Optional[str]]:
    """
    Extract a dollar amount and scale unit from a free-text string.

    Recognises patterns such as:
      "$14M"         → (14.0, "M")
      "$2.5 billion" → (2.5, "B")
      "14 million dollars" → (14.0, "M")
      "$500K"        → (500.0, "K")

    Returns:
        (amount_float, unit_str) or (None, None) if no match.
    """
    if not text:
        return None, None

    m = _DOLLAR_PATTERN.search(text)
    if not m:
        return None, None

    # Group 1 + 2: "$14M" style
    if m.group(1) is not None:
        amount = float(m.group(1))
        raw_unit = (m.group(2) or "").lower()
    else:
        # Group 3 + 4: "14 million dollars" style
        amount = float(m.group(3))
        raw_unit = (m.group(4) or "").lower()

    unit = _UNIT_MAP.get(raw_unit, raw_unit.upper() or None)
    return amount, unit


def count_words(text: str) -> int:
    """
    Return the number of whitespace-delimited words in *text*.

    Empty string → 0.
    """
    if not text or not text.strip():
        return 0
    return len(text.split())


def clean_html_text(html_str: str) -> str:
    """
    Strip HTML tags, unescape HTML entities, and collapse whitespace.

    Steps:
      1. Remove <script> and <style> blocks and their contents
      2. Strip all remaining HTML tags
      3. Unescape HTML entities (&amp; → &, &lt; → <, etc.)
      4. Collapse runs of whitespace (including newlines) to single spaces
      5. Strip leading/trailing whitespace

    Args:
        html_str: Raw HTML string.

    Returns:
        Clean plain-text string.
    """
    if not html_str:
        return ""

    # Remove <script> ... </script> and <style> ... </style>
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html_str, flags=re.I | re.S)

    # Strip all HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Unescape HTML entities
    text = html.unescape(text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text
