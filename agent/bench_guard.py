"""
bench_guard.py — Capacity commitment detector.

Scans draft outreach for any language that claims bench availability,
then validates those claims against the confirmed bench counts.

Returns (passed: bool, violations: list[str]).
"""

from __future__ import annotations

import re

from config.bench_summary import get_available

_CAPACITY_PATTERNS: list[tuple[str, str]] = [
    (r"\bpython\b",                                     "python"),
    (r"\bml\b|\bmachine\s*learning\b|\bai\s+engineer",  "ml"),
    (r"\bgo\s+engineer|\bgolang\b",                     "go"),
    (r"\bdata\s+engineer|\bdbt\b|\bdata\s+pipeline",    "data"),
    (r"\binfra\w*|\bdevops\b|\bsre\b|\bplatform\s+engineer", "infrastructure"),
]

_COMMITMENT_PATTERNS: list[str] = [
    r"we\s+have\s+.{0,30}available",
    r"our\s+bench",
    r"available\s+now|available\s+immediately|available\s+today",
    r"can\s+have\s+.{0,30}in\s+\d+\s+(?:days?|weeks?)",
    r"ready\s+to\s+start",
    r"embed\s+a\s+.{0,30}squad",
    r"\d+\s+(?:python|ml|go|data|infra\w*|devops)\s+engineer",
    r"(?:python|ml|go|data|infra\w*)\s+engineers?\s+available",
]


def _is_commitment(text_lower: str) -> bool:
    return any(
        re.search(pat, text_lower, re.IGNORECASE)
        for pat in _COMMITMENT_PATTERNS
    )


def check_draft(draft: str) -> tuple[bool, list[str]]:
    """
    Inspect a draft for capacity commitments that exceed the bench.

    Returns (passed, violations). violations is empty when no issues found.
    """
    text_lower = draft.lower()

    if not _is_commitment(text_lower):
        return True, []

    violations: list[str] = []

    for pattern, bench_key in _CAPACITY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            available = get_available(bench_key)
            if available == 0:
                violations.append(
                    f"Draft references '{bench_key}' capacity but bench shows 0 available. "
                    f"Remove the commitment or escalate to a human SDR."
                )

    return len(violations) == 0, violations


def safe_bench_claim(specialty: str) -> str:
    """Return a safe capacity sentence — assertive if bench > 0, hedged if 0."""
    available = get_available(specialty)
    if available > 0:
        return (
            f"We currently have {available} {specialty} engineer"
            f"{'s' if available != 1 else ''} available."
        )
    return (
        "We'd want to confirm current availability before quoting a start date, "
        "but our typical ramp time is 2–3 weeks once a fit is confirmed."
    )
