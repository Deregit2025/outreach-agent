"""
evidence_validator.py — Validate that every numeric claim in a memo draft
traces to an authorised source.

Every number in the memo must resolve to one of:
  1. A value in baseline_numbers.md
  2. A value in bench_summary.json
  3. A trace file in eval/runs/ (referenced by trace ID)
  4. A published public source cited inline

Functions here perform deterministic text checks — no LLM calls.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_PATH = (
    PROJECT_ROOT / "data" / "tenacious_sales_data" / "seed" / "baseline_numbers.md"
)
BENCH_SUMMARY_PATH = (
    PROJECT_ROOT / "data" / "tenacious_sales_data" / "seed" / "bench_summary.json"
)

# ── Regex patterns for numeric claim extraction ───────────────────────────────

# Matches: percentages, dollar amounts, plain integers/floats in context
_NUMBER_PATTERNS: list[re.Pattern] = [
    # Percentages: 42%, 3.5%, ~72%
    re.compile(r"~?\d+(?:\.\d+)?\s*%"),
    # Dollar amounts: $14M, $2.5B, $500K, $1,200
    re.compile(r"\$\s*\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|[BbMmKk])?"),
    # Plain counts in context (e.g., "26 engineers", "9 clients", "36 on bench")
    re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?\s+(?:engineers?|clients?|months?|weeks?|days?|hours?|people|companies|prospects?|leads?)\b", re.I),
    # Ratios and ranges like "1–3%", "30–50%", "7–12%"
    re.compile(r"\b\d+(?:\.\d+)?\s*[–\-]\s*\d+(?:\.\d+)?\s*%"),
    # Multipliers / growth: "520%", "3×", "42% pass@1"
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:×|x)\b"),
]

# Citation markers that indicate a source is provided
_CITATION_MARKERS: list[str] = [
    "[source]", "cite as", "per ", "from ", "source:", "based on",
    "according to", "measured from", "trace id", "seed/", "baseline_numbers",
    "bench_summary", "eval/", "gettenacious.com", "leadeiq", "apollo",
    "clay ", "smartlead", "b2b services", "crm pipeline", "τ²-bench",
    "tenacious internal", "tenacious overview", "public on",
]

# Assertive language that signals a claim is being made without hedging
_ASSERTIVE_CLAIM_WORDS = re.compile(
    r"\b(is|are|was|were|will|can|does|yields?|generates?|produces?|results? in|"
    r"closes?|converts?|achieves?|delivers?|expects?)\b",
    re.I,
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_baseline_text(baseline_numbers_path: Optional[Path]) -> str:
    """Load baseline_numbers.md as a lowercase string for substring matching."""
    path = baseline_numbers_path or DEFAULT_BASELINE_PATH
    if path.exists():
        return path.read_text(encoding="utf-8").lower()
    return ""


def _load_bench_text() -> str:
    """Load bench_summary.json as a lowercase string for substring matching."""
    if BENCH_SUMMARY_PATH.exists():
        return BENCH_SUMMARY_PATH.read_text(encoding="utf-8").lower()
    return ""


def _extract_numeric_claims(memo_text: str) -> list[dict]:
    """
    Find all numeric claims in *memo_text*.

    Returns a list of dicts:
        { "claim": str, "line_number": int, "start": int }
    """
    claims: list[dict] = []
    lines = memo_text.split("\n")
    for line_no, line in enumerate(lines, start=1):
        for pattern in _NUMBER_PATTERNS:
            for m in pattern.finditer(line):
                claims.append({
                    "claim": m.group(0).strip(),
                    "line_number": line_no,
                    "start": m.start(),
                    "_line": line,
                })
    return claims


def _source_found(claim: str, line: str, baseline_text: str, bench_text: str) -> bool:
    """
    Return True if the numeric claim appears traceable to a known source.

    Check order:
      1. The claim value appears verbatim in baseline_numbers.md
      2. The claim value appears verbatim in bench_summary.json
      3. The line containing the claim includes a citation marker
    """
    claim_lower = claim.lower().replace(",", "")
    # Normalise claim for baseline comparison (strip spaces around currency symbols)
    claim_normalised = re.sub(r"\s+", " ", claim_lower).strip()

    # 1. In baseline_numbers.md?
    if claim_normalised and claim_normalised in baseline_text.replace(",", ""):
        return True

    # 2. In bench_summary.json?
    if claim_normalised and claim_normalised in bench_text.replace(",", ""):
        return True

    # 3. Citation marker on the same line?
    line_lower = line.lower()
    if any(marker in line_lower for marker in _CITATION_MARKERS):
        return True

    return False


# ── Public API ────────────────────────────────────────────────────────────────

def validate_memo_numbers(
    memo_text: str,
    baseline_numbers_path: Optional[Path] = None,
) -> list[dict]:
    """
    Extract all numeric claims from *memo_text* and check each for source traceability.

    Args:
        memo_text:             Full text of the memo draft.
        baseline_numbers_path: Optional override path to baseline_numbers.md.

    Returns:
        List of dicts, one per numeric claim found:
        {
            "claim":        str  — the extracted numeric string,
            "line_number":  int  — 1-based line number in the memo,
            "source_found": bool — True if a source was identified,
            "warning":      str | None — human-readable warning or None,
        }
    """
    baseline_text = _load_baseline_text(baseline_numbers_path)
    bench_text = _load_bench_text()

    raw_claims = _extract_numeric_claims(memo_text)
    results: list[dict] = []
    seen: set[tuple] = set()  # deduplicate (line_no, claim) pairs

    for item in raw_claims:
        claim = item["claim"]
        line_no = item["line_number"]
        line = item["_line"]

        key = (line_no, claim)
        if key in seen:
            continue
        seen.add(key)

        found = _source_found(claim, line, baseline_text, bench_text)
        warning: Optional[str]
        if not found:
            warning = (
                f"Line {line_no}: numeric claim '{claim}' has no detectable source. "
                f"Add a citation (e.g., 'Tenacious internal, baseline_numbers.md') "
                f"or remove the number."
            )
        else:
            warning = None

        results.append({
            "claim": claim,
            "line_number": line_no,
            "source_found": found,
            "warning": warning,
        })

    return results


def check_fabrication_risk(memo_text: str) -> list[str]:
    """
    Flag sentences that contain numbers but no source citation.

    This is a lighter sweep than validate_memo_numbers: it operates at the
    sentence level rather than the individual-claim level, and flags any
    sentence where:
      - At least one digit is present, AND
      - No citation marker is present, AND
      - An assertive verb is present (indicating a factual claim, not hedging)

    Args:
        memo_text: Full text of the memo draft.

    Returns:
        List of warning strings, one per flagged sentence.
    """
    warnings: list[str] = []

    # Split on sentence-ending punctuation; preserve the delimiter
    sentences = re.split(r"(?<=[.!?])\s+", memo_text)

    for raw_sentence in sentences:
        sentence = raw_sentence.strip()
        if not sentence:
            continue

        # Must contain a digit
        if not re.search(r"\d", sentence):
            continue

        # Must contain assertive language
        if not _ASSERTIVE_CLAIM_WORDS.search(sentence):
            continue

        # Has a citation marker → safe
        sentence_lower = sentence.lower()
        if any(marker in sentence_lower for marker in _CITATION_MARKERS):
            continue

        # Truncate for readability in the warning
        preview = sentence if len(sentence) <= 120 else sentence[:117] + "..."
        warnings.append(
            f"Fabrication risk — numeric claim with no citation: \"{preview}\""
        )

    return warnings
