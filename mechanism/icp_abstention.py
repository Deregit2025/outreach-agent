"""
icp_abstention.py — ICP classifier with calibrated abstention.

When segment confidence falls below a threshold, the agent sends a generic
exploratory email instead of a segment-specific pitch. This prevents the brand
damage of a confident wrong-segment pitch (e.g., a Segment 1 growth pitch to a
company that just laid off 30% of its team).

Abstention thresholds (per challenge spec):
  >= 0.70  → confident classification → segment-specific pitch
  0.50–0.69 → uncertain → generic exploratory
  <  0.50  → abstain → escalate to human or hold

The classifier combines signal count, signal age, and signal strength.
It does NOT call an LLM — purely deterministic confidence scoring so that
ablation is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


ABSTAIN_THRESHOLD = 0.50
UNCERTAIN_THRESHOLD = 0.70


@dataclass
class ClassificationResult:
    segment: int            # 1-4, or 0 for abstain
    confidence_score: float  # 0.0–1.0
    confidence_label: str    # "high" | "medium" | "low" | "abstain"
    should_abstain: bool
    abstention_reason: Optional[str]
    pitch_mode: str          # "segment_specific" | "exploratory" | "escalate"
    signals_used: list[str]


def _confidence_label(score: float) -> str:
    if score >= UNCERTAIN_THRESHOLD:
        return "high"
    if score >= ABSTAIN_THRESHOLD:
        return "medium"
    return "low"


def _signal_weight(signal_type: str, confidence: str, age_days: Optional[int]) -> float:
    """Return a 0–1 weight for a single signal."""
    base_weights = {
        "funding": 0.35,
        "job_velocity": 0.25,
        "layoff": 0.30,
        "leadership_change": 0.25,
        "ai_maturity": 0.15,
        "tech_stack": 0.10,
    }
    w = base_weights.get(signal_type, 0.05)

    # Adjust for signal-level confidence
    conf_multiplier = {"high": 1.0, "medium": 0.65, "low": 0.30}.get(confidence, 0.30)
    w *= conf_multiplier

    # Penalise stale signals
    if age_days is not None:
        if age_days > 180:
            w *= 0.4
        elif age_days > 90:
            w *= 0.7

    return min(w, 0.35)  # cap per-signal contribution


def score_classification_confidence(
    segment: int,
    signals: list[dict],
    employee_min: Optional[int] = None,
    employee_max: Optional[int] = None,
) -> float:
    """
    Compute a 0–1 confidence score for the proposed segment assignment.

    Higher score = more signal support for the segment.
    Each signal contributes a capped weighted vote; conflicting signals reduce score.
    """
    if segment == 0 or not signals:
        return 0.0

    # Signals expected per segment
    segment_required: dict[int, list[str]] = {
        1: ["funding", "job_velocity"],
        2: ["layoff"],
        3: ["leadership_change"],
        4: ["ai_maturity"],
    }
    segment_supporting: dict[int, list[str]] = {
        1: ["funding", "job_velocity", "ai_maturity", "tech_stack"],
        2: ["layoff", "job_velocity", "tech_stack"],
        3: ["leadership_change", "funding", "ai_maturity"],
        4: ["ai_maturity", "tech_stack", "job_velocity"],
    }

    required = segment_required.get(segment, [])
    supporting = segment_supporting.get(segment, [])

    sig_by_type = {s["signal_type"]: s for s in signals}
    score = 0.0
    signals_used: list[str] = []

    # Required signals carry more weight
    for req_type in required:
        if req_type in sig_by_type:
            s = sig_by_type[req_type]
            w = _signal_weight(req_type, s.get("confidence", "low"), s.get("data_age_days"))
            score += w * 1.5  # required signal bonus
            signals_used.append(req_type)

    # Supporting signals
    for sup_type in supporting:
        if sup_type in sig_by_type and sup_type not in signals_used:
            s = sig_by_type[sup_type]
            w = _signal_weight(sup_type, s.get("confidence", "low"), s.get("data_age_days"))
            score += w
            signals_used.append(sup_type)

    # Conflicting signal penalties
    # A layoff signal on a Segment 1 candidate reduces confidence significantly
    if segment == 1 and "layoff" in sig_by_type:
        layoff = sig_by_type["layoff"]
        age = layoff.get("data_age_days", 999)
        if age is not None and age <= 90:
            score *= 0.5  # recent layoff strongly conflicts with Seg1

    # Employee count plausibility check
    if employee_min is not None and employee_max is not None:
        midpoint = (employee_min + employee_max) / 2
        if segment == 1 and not (15 <= midpoint <= 80):
            score *= 0.6
        elif segment == 2 and not (200 <= midpoint <= 2000):
            score *= 0.6

    return min(score, 1.0)


def classify_with_abstention(
    segment: int,
    signals: list[dict],
    employee_min: Optional[int] = None,
    employee_max: Optional[int] = None,
    force_abstain: bool = False,
) -> ClassificationResult:
    """
    Decide whether to proceed with segment-specific pitch or abstain.

    Args:
        segment:      The proposed segment from icp_classifier.py (0-4).
        signals:      List of SignalItem dicts from HiringSignalBrief.
        employee_min: Minimum employee count for plausibility check.
        employee_max: Maximum employee count for plausibility check.
        force_abstain: Override to always abstain (used in probes).

    Returns:
        ClassificationResult with pitch_mode recommendation.
    """
    if force_abstain or segment == 0:
        return ClassificationResult(
            segment=0,
            confidence_score=0.0,
            confidence_label="abstain",
            should_abstain=True,
            abstention_reason="No qualifying segment identified from available signals.",
            pitch_mode="escalate",
            signals_used=[],
        )

    score = score_classification_confidence(
        segment=segment,
        signals=signals,
        employee_min=employee_min,
        employee_max=employee_max,
    )
    label = _confidence_label(score)
    signals_used = [s["signal_type"] for s in signals]

    if score >= UNCERTAIN_THRESHOLD:
        return ClassificationResult(
            segment=segment,
            confidence_score=round(score, 3),
            confidence_label=label,
            should_abstain=False,
            abstention_reason=None,
            pitch_mode="segment_specific",
            signals_used=signals_used,
        )

    if score >= ABSTAIN_THRESHOLD:
        return ClassificationResult(
            segment=segment,
            confidence_score=round(score, 3),
            confidence_label=label,
            should_abstain=False,
            abstention_reason=(
                f"Segment {segment} tentative — confidence {score:.2f} below "
                f"{UNCERTAIN_THRESHOLD} threshold. Using exploratory outreach."
            ),
            pitch_mode="exploratory",
            signals_used=signals_used,
        )

    # Below abstain threshold → escalate
    return ClassificationResult(
        segment=segment,
        confidence_score=round(score, 3),
        confidence_label="low",
        should_abstain=True,
        abstention_reason=(
            f"Confidence {score:.2f} below abstention floor {ABSTAIN_THRESHOLD}. "
            f"Insufficient signal to pitch any segment. Routing to human review."
        ),
        pitch_mode="escalate",
        signals_used=signals_used,
    )


def exploratory_email_subject(company_name: str) -> str:
    return f"Quick question for the {company_name} engineering team"


def exploratory_email_body(company_name: str) -> str:
    """Generic first-touch body when segment confidence is uncertain."""
    return (
        f"Hi,\n\n"
        f"I came across {company_name} while mapping the engineering landscape "
        f"in your space. I didn't want to make assumptions about where you are "
        f"right now — so I'm reaching out directly.\n\n"
        f"Tenacious provides dedicated engineering and data teams to B2B tech "
        f"companies. We typically work with teams either scaling fast or navigating "
        f"a specific capability gap.\n\n"
        f"Would a 20-minute conversation make sense? Happy to explain what we "
        f"might be relevant for and let you tell me if it's a fit.\n\n"
        f"Best,\n"
        f"[Tenacious Delivery Lead]"
    )
