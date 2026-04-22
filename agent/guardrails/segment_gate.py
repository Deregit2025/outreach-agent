"""
segment_gate.py — ICP segment assignment validation and gating.
Tenacious Consulting & Outsourcing SDR Agent

Enforces business rules around which segment pitch is appropriate for a given prospect.
All segment assignments produced by the ICP classifier must pass through validate_segment_pitch()
before outreach is generated.

Rules:
  - Segment 4 (Specialized capability gaps) requires ai_maturity_score >= 2.
  - A prospect with a confirmed layoff signal should not be pitched as Segment 1
    (recently funded). The layoff likely post-dates the funding and changes the context.
  - Segment assignments outside 1–4 are always blocked.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Segment metadata
# ---------------------------------------------------------------------------

SEGMENT_NAMES: dict[int, str] = {
    1: "Recently-funded Series A/B startups",
    2: "Mid-market platforms restructuring cost",
    3: "Engineering-leadership transitions",
    4: "Specialized capability gaps",
}

SEGMENT_PITCH_ANGLES: dict[int, str] = {
    1: (
        "Investors expect velocity; hiring full-time engineers takes 4–6 months. "
        "We embed a working squad in 2–3 weeks with no permanent headcount."
    ),
    2: (
        "Headcount reductions leave delivery gaps. A time-boxed squad engagement "
        "keeps commitments on track without reversing the cost structure."
    ),
    3: (
        "New engineering leaders need immediate capacity for priority initiatives "
        "before the org is fully built out. We run alongside existing teams for "
        "scoped projects."
    ),
    4: (
        "Specialized capability gaps are slow to close through hiring alone. "
        "Our bench has engineers in relevant specialties available now."
    ),
}


# ---------------------------------------------------------------------------
# Segment 4 gate
# ---------------------------------------------------------------------------

def gate_segment_4(ai_maturity_score: int) -> bool:
    """
    Return True if the Segment 4 pitch is allowed for this prospect.

    The Segment 4 pitch (Specialized capability gaps) requires an AI maturity
    score of at least 2. Pitching AI/ML capability to a company with no
    demonstrated AI investment wastes credibility and is not honest outreach.

    Parameters
    ----------
    ai_maturity_score : int — the prospect's AI maturity score (0–5 scale)

    Returns
    -------
    bool — True if Segment 4 is allowed, False if it must be blocked
    """
    return ai_maturity_score >= 2


# ---------------------------------------------------------------------------
# Full segment pitch validation
# ---------------------------------------------------------------------------

def validate_segment_pitch(segment: int, brief: dict) -> tuple[bool, str]:
    """
    Check whether the proposed segment pitch is valid for the given prospect brief.

    Parameters
    ----------
    segment : int  — proposed ICP segment (1–4)
    brief   : dict — enriched prospect brief. Relevant keys:
                       ai_maturity_score (int, default 0)
                       layoff_age_days   (int | None)
                       funding_age_days  (int | None)
                       funding_amount_usd (float | None)

    Returns
    -------
    (allowed: bool, reason: str)

    'allowed' is False when the pitch must be blocked entirely.
    'allowed' is True with a non-empty 'reason' when the pitch is permitted but a
    warning should be logged (e.g. a combination of signals that warrants care).
    'allowed' is True with an empty 'reason' when the pitch is clean.
    """
    # Validate segment is in range
    if segment not in SEGMENT_NAMES:
        return (
            False,
            f"Segment {segment} is not a valid ICP segment. "
            f"Valid segments: {sorted(SEGMENT_NAMES.keys())}.",
        )

    ai_score: int = int(brief.get("ai_maturity_score", 0))
    layoff_age: int | None = brief.get("layoff_age_days")
    funding_age: int | None = brief.get("funding_age_days")

    warnings: list[str] = []

    # ── Hard block: Segment 4 without sufficient AI maturity ──
    if segment == 4:
        if not gate_segment_4(ai_score):
            return (
                False,
                (
                    f"Segment 4 pitch blocked: ai_maturity_score is {ai_score} "
                    f"(minimum 2 required). Use a different segment or mark for human review."
                ),
            )

    # ── Soft warning: Segment 1 when a layoff signal is also present ──
    if segment == 1 and layoff_age is not None:
        if layoff_age <= 365:
            warnings.append(
                f"Segment 1 (recently-funded) pitch flagged: a layoff signal exists "
                f"({layoff_age} days old). The layoff may post-date the funding round "
                f"and materially changes the company context. Consider Segment 2 or "
                f"review the brief manually before sending."
            )

    # ── Soft warning: Segment 1 without a funding signal ──
    if segment == 1 and (funding_age is None or funding_age > 180):
        funding_msg = (
            "no funding signal present"
            if funding_age is None
            else f"funding signal is {funding_age} days old (max 180 for Segment 1)"
        )
        warnings.append(
            f"Segment 1 pitch flagged: {funding_msg}. "
            f"Verify funding is recent and confirmed before sending."
        )

    # ── Soft warning: Segment 3 without a leadership change signal ──
    if segment == 3:
        leadership_age: int | None = brief.get("leadership_change_age_days")
        if leadership_age is None or leadership_age > 180:
            age_msg = (
                "no leadership change signal present"
                if leadership_age is None
                else f"leadership change is {leadership_age} days old (max 180 for Segment 3)"
            )
            warnings.append(
                f"Segment 3 pitch flagged: {age_msg}. "
                f"Verify the leadership transition before sending."
            )

    if warnings:
        return (True, " | ".join(warnings))

    return (True, "")


# ---------------------------------------------------------------------------
# Segment name lookup
# ---------------------------------------------------------------------------

def get_segment_name(segment: int) -> str:
    """
    Return the human-readable name for a segment number.

    Parameters
    ----------
    segment : int — ICP segment (1–4)

    Returns
    -------
    str — segment name, or a descriptive error string if segment is invalid
    """
    return SEGMENT_NAMES.get(segment, f"Unknown segment ({segment})")


def get_segment_pitch_angle(segment: int) -> str:
    """
    Return the canonical pitch angle description for a segment.

    Parameters
    ----------
    segment : int — ICP segment (1–4)

    Returns
    -------
    str — pitch angle summary, or empty string if segment is invalid
    """
    return SEGMENT_PITCH_ANGLES.get(segment, "")


# ---------------------------------------------------------------------------
# Segment selection helper: pick best valid segment from a ranked list
# ---------------------------------------------------------------------------

def select_best_segment(ranked_segments: list[int], brief: dict) -> tuple[int | None, str]:
    """
    Given an ordered list of candidate segments (most preferred first), return
    the first one that passes validation.

    Parameters
    ----------
    ranked_segments : list[int]  — candidate segments in preference order
    brief           : dict       — enriched prospect brief

    Returns
    -------
    (segment: int | None, reason: str)
    Returns (None, reason) if no segment passes validation.
    """
    last_reason = "No candidate segments provided."

    for segment in ranked_segments:
        allowed, reason = validate_segment_pitch(segment, brief)
        if allowed:
            return (segment, reason)  # reason may carry warnings even on success
        last_reason = reason

    return (None, f"All candidate segments blocked. Last reason: {last_reason}")
