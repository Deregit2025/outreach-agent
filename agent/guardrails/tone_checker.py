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


from __future__ import annotations

"""
tone_checker.py — Outreach tone validation and over-claim detection.
Tenacious Consulting & Outsourcing SDR Agent

Every outbound message must pass enforce() before the channel handler sends it.
A failed check blocks the send and returns a structured report for logging/escalation.

Design principles:
  - Prohibited phrases are loaded from the style guide.
  - Over-claims are flagged based on the provided signals list; the caller is
    responsible for passing the full evaluated signal set.
  - score_tone() returns a 0–10 quality score: 10 = pristine, 0 = do not send.
  - enforce() is the single entry point used by the agent before every send.
"""

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Load prohibited phrases from style guide
# ---------------------------------------------------------------------------

def _load_prohibited_phrases() -> list[str]:
    """Load prohibited phrases from the tenacious_sales_data/seed/style_guide.md file."""
    style_guide_path = Path("data/tenacious_sales_data/seed/style_guide.md")
    
    if not style_guide_path.exists():
        # Fallback prohibited phrases
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
    
    # Extract prohibited phrases from the "Prohibited phrases" section
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
    
    # Parse the list items
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
# Over-claim: text asserts something that requires a signal the brief does not assert.
# Format: (text_pattern_regex, required_signal_type, required_register, warning_message)
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
        "hedge",  # AI maturity needs at least hedge to claim an AI initiative
        "Text references an AI/ML initiative but ai_maturity signal is below hedge level.",
    ),
    (
        r"\bwe\s+have\s+(?:\w+\s+)?engineers?\s+available|\bour\s+bench\b|\bavailable\s+(?:now|immediately|today)",
        "bench",
        "confirmed",
        "Text claims bench availability but no bench confirmation was passed in signals.",
    ),
]

# Required elements per message type
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
    """
    Return a list of prohibited phrases found in the text (case-insensitive).

    Parameters
    ----------
    text : str — the outbound message body (and subject line if applicable)

    Returns
    -------
    list[str] — prohibited phrases found; empty list means clean
    """
    text_lower = text.lower()
    found: list[str] = []

    for phrase in PROHIBITED_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)

    return found


def check_over_claim(text: str, signals: list[dict]) -> list[str]:
    """
    Return a list of over-claim warnings.

    An over-claim occurs when the text asserts something that requires a
    corroborating signal at a minimum register level, but that signal is
    either absent or at a weaker register.

    Parameters
    ----------
    text    : str         — the outbound message body
    signals : list[dict]  — evaluated signals for this prospect. Each dict has:
                              {"type": str, "register": str}
                            e.g. [{"type": "funding", "register": "assert"},
                                   {"type": "layoff",  "register": "hedge"}]

    Returns
    -------
    list[str] — warning messages; empty list means no over-claims detected
    """
    text_lower = text.lower()
    warnings: list[str] = []

    # Build a fast lookup: signal_type → register
    signal_map: dict[str, str] = {s["type"]: s["register"] for s in signals if "type" in s}

    _register_rank = {"ask": 0, "hedge": 1, "assert": 2, "confirmed": 3}

    for pattern, required_type, required_register, warning_msg in _OVERCLAIM_RULES:
        if re.search(pattern, text_lower, re.IGNORECASE):
            actual_register = signal_map.get(required_type)

            if actual_register is None:
                # Pattern matched but no signal of this type is present at all
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
    """
    Evaluate the tone quality of an outbound message and return a structured report.

    Scoring rubric (starts at 10, deductions applied):
      - Each prohibited phrase found:    -2 points (min 0)
      - Each over-claim warning:         -1.5 points (min 0)
      - Text length > 120 words:         -1 point (cold email standard)
      - No verifiable signal fact used:  -1 point

    Parameters
    ----------
    text    : str        — outbound message body (plain text)
    signals : list[dict] — evaluated signals; same format as check_over_claim()

    Returns
    -------
    dict with keys:
        "passed"           : bool         — True if score >= 6 and no prohibited phrases
        "score"            : float        — 0–10 quality score
        "prohibited_found" : list[str]    — prohibited phrases found
        "over_claims"      : list[str]    — over-claim warnings
        "warnings"         : list[str]    — advisory (non-blocking) notes
    """
    prohibited = check_prohibited(text)
    over_claims = check_over_claim(text, signals)
    advisory_warnings: list[str] = []

    score = 10.0

    # Deduct for prohibited phrases
    score -= len(prohibited) * 2.0

    # Deduct for over-claims
    score -= len(over_claims) * 1.5

    # Check word count (cold email standard: 120 words max)
    word_count = len(text.split())
    if word_count > 120:
        score -= 1.0
        advisory_warnings.append(
            f"Message is {word_count} words (limit: 120 for cold email). "
            f"Consider trimming before send."
        )

    # Check that at least one signal is present (assert or hedge level)
    has_signal_fact = any(
        s.get("register") in ("assert", "hedge") for s in signals
    )
    if not has_signal_fact:
        score -= 1.0
        advisory_warnings.append(
            "No assert- or hedge-level signal is present. "
            "The email may lack a specific, verifiable fact. "
            "Consider using an ask-register opening instead of a generic one."
        )

    score = max(0.0, min(10.0, score))

    # Pass threshold: score >= 6.0 AND no prohibited phrases
    passed = score >= 6.0 and len(prohibited) == 0

    return {
        "passed": passed,
        "score": round(score, 1),
        "prohibited_found": prohibited,
        "over_claims": over_claims,
        "warnings": advisory_warnings,
    }


def enforce(text: str, signals: list[dict]) -> tuple[bool, dict]:
    """
    Run the full tone check suite and return a pass/fail decision with a structured report.

    This is the single entry point the agent must call before every send.
    If this returns (False, report), the message must NOT be sent. Log the report
    and either fix the draft or escalate to a human SDR.

    Parameters
    ----------
    text    : str        — full outbound message text (subject + body for email)
    signals : list[dict] — evaluated signals for this prospect

    Returns
    -------
    (passed: bool, report: dict)

    report keys:
        "passed"           : bool
        "score"            : float (0–10)
        "prohibited_found" : list[str]
        "over_claims"      : list[str]
        "warnings"         : list[str]
        "action"           : str  — "send", "fix_and_retry", or "escalate_to_human"
    """
    report = score_tone(text, signals)

    # Determine recommended action
    if report["passed"]:
        action = "send"
    elif report["prohibited_found"]:
        # Prohibited phrases are a hard block — always escalate, not just retry
        action = "escalate_to_human"
    elif report["score"] >= 4.0:
        # Recoverable: over-claims or length, no prohibited phrases
        action = "fix_and_retry"
    else:
        # Score too low to recover automatically
        action = "escalate_to_human"

    report["action"] = action

    return (report["passed"], report)


# ---------------------------------------------------------------------------
# Utility: check required elements for a message type
# ---------------------------------------------------------------------------

def check_required_elements(
    text: str,
    message_type: str,
    signals: list[dict] | None = None,
) -> list[str]:
    """
    Verify that a message of the given type contains all required structural elements.
    Derives element presence directly from the text and signals rather than relying
    on caller-supplied booleans.

    Parameters
    ----------
    text         : str             — rendered message body (subject + body for email)
    message_type : str             — one of the keys in REQUIRED_ELEMENTS
    signals      : list[dict]|None — evaluated signals for this prospect (same format
                                     as check_over_claim). Pass None if not applicable.

    Element detection rules:
      signal_fact   — at least one signal in `signals` is at assert or hedge level
      one_ask       — exactly one sentence ending in '?' is found in the text
      calendar_link — text contains 'http' and ('cal.com' or '/book' or '/schedule')

    Returns
    -------
    list[str] — missing element descriptions; empty means all required elements present
    """
    required = REQUIRED_ELEMENTS.get(message_type, [])
    missing: list[str] = []
    signals = signals or []

    for element in required:
        if element == "signal_fact":
            has_signal_fact = any(
                s.get("register") in ("assert", "hedge") for s in signals
            )
            if not has_signal_fact:
                missing.append(
                    "signal_fact: cold emails must contain at least one assert- or "
                    "hedge-level signal fact. Add a verifiable public data point or "
                    "use an ask-register opening."
                )

        elif element == "one_ask":
            question_count = text.count("?")
            if question_count == 0:
                missing.append(
                    "one_ask: every outbound message must end with exactly one "
                    "question or call to action — none found."
                )
            elif question_count > 1:
                missing.append(
                    f"one_ask: found {question_count} questions in the message — "
                    "only one ask per message is allowed. Remove the extras."
                )

        elif element == "calendar_link":
            text_lower = text.lower()
            has_link = "http" in text_lower and any(
                marker in text_lower
                for marker in ("cal.com", "/book", "/schedule", "calendly")
            )
            if not has_link:
                missing.append(
                    "calendar_link: booking messages must include a Cal.com (or "
                    "equivalent) booking URL."
                )

    return missing
