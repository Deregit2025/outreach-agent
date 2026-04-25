"""
tone_checker.py — Outreach tone validation and over-claim detection.
Tenacious Consulting & Outsourcing SDR Agent

Every outbound message must pass enforce() before the channel handler sends it.
A failed check blocks the send and returns a structured report for logging/escalation.

Design principles:
  - Prohibited phrases are a hard block (no exceptions).
  - Over-claims are flagged based on the provided signals list; the caller is
    responsible for passing the full evaluated signal set.
  - score_tone() returns a 0–10 quality score: 10 = pristine, 0 = do not send.
  - enforce() is the single entry point used by the agent before every send.
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Load prohibited phrases from style guide
# ---------------------------------------------------------------------------

def _load_prohibited_phrases() -> list[str]:
    style_guide_path = Path("data/tenacious_sales_data/seed/style_guide.md")

    if not style_guide_path.exists():
        return [
            "excited to connect",
            "i hope this email finds you well",
            "world-class",
            "cutting-edge",
            "best-in-class",
            "innovative",
            "synergy",
            "just following up",
            "i wanted to reach out",
            "offshore team",
            "scale your team aggressively",
        ]

    content = style_guide_path.read_text()
    prohibited_section = ""
    in_section = False
    for line in content.splitlines():
        if "### Prohibited phrases" in line:
            in_section = True
            continue
        elif in_section and line.startswith("###"):
            break
        elif in_section:
            prohibited_section += line + "\n"

    phrases = []
    for line in prohibited_section.splitlines():
        line = line.strip()
        if line.startswith("- "):
            phrase = line[2:].strip()
            if phrase.startswith('"') and phrase.endswith('"'):
                phrase = phrase[1:-1]
            phrases.append(phrase.lower())

    return phrases if phrases else [
        "excited to connect",
        "i hope this email finds you well",
        "world-class",
        "cutting-edge",
        "best-in-class",
        "innovative",
        "synergy",
        "just following up",
        "i wanted to reach out",
        "offshore team",
        "scale your team aggressively",
    ]


PROHIBITED_PHRASES: list[str] = _load_prohibited_phrases()

# ---------------------------------------------------------------------------
# Over-claim signal mappings
# ---------------------------------------------------------------------------

_OVERCLAIM_RULES: list[tuple[str, str, str, str]] = [
    (
        r"\baggressiv\w*\s+hir\w*|\bhiring\s+aggressiv\w*",
        "job_velocity",
        "assert",
        "Text implies aggressive hiring but job_velocity is not at assert level.",
    ),
    (
        r"\bjust\s+raised|\brecently\s+raised|\bclosed\s+(?:a|your|the)\s+round",
        "funding",
        "assert",
        "Text asserts a completed funding round but funding signal is not at assert level.",
    ),
    (
        r"\blaid\s+off|\blayoff|\breduction\s+in\s+force|\brif\b",
        "layoff",
        "assert",
        "Text asserts a layoff event but layoff signal is not at assert level.",
    ),
    (
        r"\bnew\s+(?:cto|vp\s+(?:of\s+)?eng\w*|head\s+of\s+eng\w*)|\bjust\s+(?:joined|hired|appointed|started)\b",
        "leadership",
        "assert",
        "Text asserts a leadership change but leadership signal is not at assert level.",
    ),
    (
        r"\bai\s+initiative|\bml\s+(?:project|initiative|roadmap)|\bmachine\s+learning\s+(?:project|initiative)",
        "ai_maturity",
        "hedge",
        "Text references an AI/ML initiative but ai_maturity signal is below hedge level.",
    ),
    (
        r"\bwe\s+have\s+(?:\w+\s+)?engineers?\s+available|\bour\s+bench\b|\bavailable\s+(?:now|immediately|today)",
        "bench",
        "confirmed",
        "Text claims bench availability but no bench confirmation was passed in signals.",
    ),
]

REQUIRED_ELEMENTS: dict[str, list[str]] = {
    "cold_email": ["signal_fact", "one_ask"],
    "qualification": ["one_ask"],
    "booking": ["calendar_link"],
    "sms": ["one_ask"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_prohibited(text: str) -> list[str]:
    text_lower = text.lower()
    found: list[str] = []
    for phrase in PROHIBITED_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return found


def check_over_claim(text: str, signals: list[dict]) -> list[str]:
    text_lower = text.lower()
    warnings: list[str] = []
    signal_map: dict[str, str] = {s["type"]: s["register"] for s in signals if "type" in s}
    _register_rank = {"ask": 0, "hedge": 1, "assert": 2, "confirmed": 3}

    for pattern, required_type, required_register, warning_msg in _OVERCLAIM_RULES:
        if re.search(pattern, text_lower, re.IGNORECASE):
            actual_register = signal_map.get(required_type)
            if actual_register is None:
                warnings.append(
                    f"{warning_msg} (signal '{required_type}' not present in brief)"
                )
            else:
                actual_rank = _register_rank.get(actual_register, 0)
                required_rank = _register_rank.get(required_register, 0)
                if actual_rank < required_rank:
                    warnings.append(
                        f"{warning_msg} "
                        f"(actual register: '{actual_register}', "
                        f"required: '{required_register}')"
                    )
    return warnings


def score_tone(text: str, signals: list[dict]) -> dict:
    prohibited = check_prohibited(text)
    over_claims = check_over_claim(text, signals)
    advisory_warnings: list[str] = []

    score = 10.0
    score -= len(prohibited) * 2.0
    score -= len(over_claims) * 1.5

    word_count = len(text.split())
    if word_count > 120:
        score -= 1.0
        advisory_warnings.append(
            f"Message is {word_count} words (limit: 120 for cold email)."
        )

    has_signal_fact = any(s.get("register") in ("assert", "hedge") for s in signals)
    if not has_signal_fact:
        score -= 1.0
        advisory_warnings.append("No assert- or hedge-level signal present.")

    score = max(0.0, min(10.0, score))
    passed = score >= 6.0 and len(prohibited) == 0

    return {
        "passed": passed,
        "score": round(score, 1),
        "prohibited_found": prohibited,
        "over_claims": over_claims,
        "warnings": advisory_warnings,
    }


def enforce(text: str, signals: list[dict]) -> tuple[bool, dict]:
    report = score_tone(text, signals)
    if report["passed"]:
        action = "send"
    elif report["prohibited_found"]:
        action = "escalate_to_human"
    elif report["score"] >= 4.0:
        action = "fix_and_retry"
    else:
        action = "escalate_to_human"
    report["action"] = action
    return (report["passed"], report)


def check_required_elements(
    text: str,
    message_type: str,
    signals: list[dict] | None = None,
) -> list[str]:
    required = REQUIRED_ELEMENTS.get(message_type, [])
    missing: list[str] = []
    signals = signals or []

    for element in required:
        if element == "signal_fact":
            has_signal_fact = any(s.get("register") in ("assert", "hedge") for s in signals)
            if not has_signal_fact:
                missing.append("signal_fact: cold emails must contain at least one assert- or hedge-level signal fact.")
        elif element == "one_ask":
            question_count = text.count("?")
            if question_count == 0:
                missing.append("one_ask: every outbound message must end with exactly one question — none found.")
            elif question_count > 1:
                missing.append(f"one_ask: found {question_count} questions — only one ask per message allowed.")
        elif element == "calendar_link":
            text_lower = text.lower()
            has_link = "http" in text_lower and any(
                marker in text_lower for marker in ("cal.com", "/book", "/schedule", "calendly")
            )
            if not has_link:
                missing.append("calendar_link: booking messages must include a Cal.com booking URL.")

    return missing
