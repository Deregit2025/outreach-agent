"""
confidence_aware_phrasing.py — Adjust claim language based on signal confidence.

This is the core Act IV mechanism. When the hiring signal brief has low or medium
confidence on a key signal, the agent's language must shift from assertion to hedging
or inquiry. Over-claiming against weak evidence damages the Tenacious brand more
than silence would.

Signal confidence thresholds:
  high   → assert ("you closed a $14M Series B in February")
  medium → hedge  ("our data suggests a recent funding event")
  low    → ask    ("we noticed what may be a recent funding round — is that accurate?")

The language_register field on SignalItem maps directly to these modes.
This module applies the register to actual claim sentences and detects
when a draft message contains assertions that exceed its evidence basis.
"""

from __future__ import annotations

import re
from typing import Optional


# ── Register phrase templates ─────────────────────────────────────────────────

_ASSERT_OPENERS = [
    "you closed", "your team has", "you are", "you have",
    "your company", "you recently", "since your",
    "your open", "you scaled", "you tripled",
]

_HEDGE_OPENERS = [
    "our data suggests", "it looks like", "we noticed",
    "based on public signals", "the data indicates",
    "from what we can see publicly",
]

_ASK_OPENERS = [
    "we noticed indicators that may suggest", "is it accurate that",
    "we saw what may be", "could it be that", "we wondered whether",
    "are you currently", "have you recently",
]


def adjust_claim(
    claim: str,
    confidence: str,  # "high" | "medium" | "low"
    signal_type: Optional[str] = None,
) -> str:
    """
    Rephrase a factual claim sentence according to confidence level.

    Args:
        claim: A sentence asserting something about the prospect.
        confidence: "high" | "medium" | "low"
        signal_type: Optional hint for signal-specific phrasing.

    Returns:
        Rephrased sentence matching the appropriate register.
    """
    confidence = confidence.lower()
    if confidence == "high":
        return claim  # assert mode — keep as written

    claim_stripped = claim.strip().rstrip(".")

    if confidence == "medium":
        # Prefix with a hedging opener
        prefix = "Based on public data, it appears that"
        lowered = claim_stripped[0].lower() + claim_stripped[1:]
        return f"{prefix} {lowered}."

    # low confidence → inquiry mode
    # Convert assertion → question
    prefix = "We noticed signals that may suggest"
    lowered = claim_stripped[0].lower() + claim_stripped[1:]
    return f"{prefix} {lowered} — is that accurate?"


def detect_overclaim(
    draft_text: str,
    signals: list[dict],
) -> list[str]:
    """
    Scan a draft message for assertion language that exceeds signal confidence.

    Args:
        draft_text: The full draft email/SMS body.
        signals: List of SignalItem dicts with 'value', 'confidence', 'language_register'.

    Returns:
        List of warning strings identifying over-claimed sentences.
    """
    warnings: list[str] = []
    draft_lower = draft_text.lower()

    for sig in signals:
        conf = (sig.get("confidence") or "low").lower()
        register = (sig.get("language_register") or "ask").lower()

        if conf in ("low", "medium") and register in ("assert",):
            # Check if the draft uses assertive language about this signal value
            value = (sig.get("value") or "").lower()
            if value and any(part in draft_lower for part in value.split()[:3]):
                # Look for assertive openers near this value mention
                for opener in _ASSERT_OPENERS:
                    if opener in draft_lower:
                        warnings.append(
                            f"Potential over-claim: '{opener}...' used for "
                            f"signal '{sig.get('signal_type')}' with "
                            f"confidence='{conf}'. Consider hedging."
                        )
                        break

    return warnings


def rephrase_for_confidence(
    sentence: str,
    current_confidence: str,
    target_register: str,
) -> str:
    """
    Force a sentence into a specific register ('assert' | 'hedge' | 'ask').

    Used by tone_preservation.py when a generated draft fails the confidence audit.
    """
    if target_register == "assert":
        return sentence

    # Strip existing hedge/ask openers before re-wrapping
    for opener_list in (_HEDGE_OPENERS, _ASK_OPENERS):
        for opener in opener_list:
            pattern = re.compile(re.escape(opener), re.I)
            sentence = pattern.sub("", sentence).strip(" ,.")

    sentence = sentence[0].upper() + sentence[1:] if sentence else sentence

    if target_register == "hedge":
        return f"Based on public data, it appears that {sentence[0].lower() + sentence[1:]}."

    # ask
    return (
        f"We noticed signals that may suggest "
        f"{sentence[0].lower() + sentence[1:].rstrip('.')} — is that accurate?"
    )


def build_grounded_opener(
    company_name: str,
    signals: list[dict],
    ai_maturity_score: int,
) -> str:
    """
    Build the opening hook sentence for a cold email from the signal brief.

    Selects the strongest asserted signal and phrases it appropriately.
    Falls back to generic exploratory language if all signals are low-confidence.
    """
    # Prioritise signals by confidence then type
    priority = {"funding": 3, "leadership_change": 2, "job_velocity": 2,
                "layoff": 1, "ai_maturity": 1, "tech_stack": 0}

    asserted = [s for s in signals if s.get("language_register") == "assert"]
    hedged = [s for s in signals if s.get("language_register") == "hedge"]
    all_ranked = sorted(
        asserted or hedged or signals,
        key=lambda s: priority.get(s.get("signal_type", ""), 0),
        reverse=True,
    )

    if not all_ranked:
        return (
            f"I came across {company_name} while looking at companies "
            f"in your space and wanted to reach out."
        )

    top = all_ranked[0]
    conf = top.get("confidence", "low")
    sig_type = top.get("signal_type", "")
    value = top.get("value", "")

    if sig_type == "funding" and conf == "high":
        return (
            f"I noticed {company_name} recently {value.lower()} — "
            f"that typically means a team scaling faster than in-house recruiting can support."
        )
    elif sig_type == "job_velocity" and conf in ("high", "medium"):
        return (
            f"I saw {value.lower()} open at {company_name} — "
            f"that pace of hiring often means recruiting capacity is the bottleneck."
        )
    elif sig_type == "leadership_change" and conf == "high":
        return (
            f"I noticed a leadership change at {company_name} recently — "
            f"new engineering leaders often reassess vendor and delivery mix early on."
        )
    elif sig_type == "layoff" and conf in ("high", "medium"):
        return (
            f"We saw signals of a recent restructuring at {company_name} — "
            f"companies in that position are often looking to maintain delivery "
            f"capacity while reshaping cost."
        )
    else:
        return (
            f"Based on public data, it looks like {company_name} may be at an "
            f"interesting inflection point — happy to share what we noticed if it's useful."
        )
