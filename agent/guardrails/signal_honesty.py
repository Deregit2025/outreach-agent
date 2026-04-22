"""
signal_honesty.py — Signal strength evaluation and language register assignment.
Tenacious Consulting & Outsourcing SDR Agent

Every factual claim in outreach must carry one of three language registers:
  - "assert"  : strong, multi-source, recent signal — use declarative language
  - "hedge"   : single source or aging signal — use conditional/softened language
  - "ask"     : weak, inferred, or unconfirmed signal — turn the claim into a question

The thresholds below are the authoritative source of truth for register assignment.
No other module may override or bypass them.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Threshold definitions
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, dict] = {
    "job_velocity": {
        "assert": {"min_roles": 10, "min_sources": 2, "max_age_days": 30},
        "hedge":  {"min_roles": 5,  "min_sources": 1, "max_age_days": 60},
        # ask: everything else (fewer than 5 roles, single old source, etc.)
    },
    "funding": {
        "assert": {"min_amount_usd": 5_000_000, "max_age_days": 180},
        "hedge":  {"min_amount_usd": 1_000_000, "max_age_days": 365},
        # ask: amount unknown, unconfirmed, or older than 365 days
    },
    "layoff": {
        "assert": {"max_age_days": 120},
        "hedge":  {"max_age_days": 365},
        # ask: unconfirmed or older than 365 days
    },
    "leadership": {
        "assert": {"max_age_days": 90},
        "hedge":  {"max_age_days": 180},
        # ask: unconfirmed or older than 180 days
    },
    "ai_maturity": {
        "assert": {"min_score": 3, "min_confidence": "high"},
        "hedge":  {"min_score": 2},
        # ask: score 0–1 or confidence not "high" at score 3
    },
}

# Human-readable confidence levels, ordered low → high
_CONFIDENCE_ORDER = ["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Core register logic
# ---------------------------------------------------------------------------

def get_register(signal_type: str, **kwargs) -> str:
    """
    Return 'assert', 'hedge', or 'ask' for a given signal and its observed metrics.

    Parameters
    ----------
    signal_type : str
        One of: 'job_velocity', 'funding', 'layoff', 'leadership', 'ai_maturity'
    **kwargs : signal-specific metrics (see THRESHOLDS for required keys per type)

    Returns
    -------
    str — one of 'assert', 'hedge', 'ask'

    Raises
    ------
    ValueError — if signal_type is not recognised
    """
    if signal_type not in THRESHOLDS:
        raise ValueError(
            f"Unknown signal_type '{signal_type}'. "
            f"Valid types: {list(THRESHOLDS.keys())}"
        )

    thresholds = THRESHOLDS[signal_type]

    if signal_type == "job_velocity":
        return _register_job_velocity(
            min_roles=kwargs.get("open_roles", 0),
            min_sources=kwargs.get("sources", 0),
            age_days=kwargs.get("age_days", 9999),
            thresholds=thresholds,
        )

    if signal_type == "funding":
        return _register_funding(
            amount_usd=kwargs.get("amount_usd", 0),
            age_days=kwargs.get("age_days", 9999),
            thresholds=thresholds,
        )

    if signal_type == "layoff":
        return _register_age_only(
            age_days=kwargs.get("age_days", 9999),
            thresholds=thresholds,
        )

    if signal_type == "leadership":
        return _register_age_only(
            age_days=kwargs.get("age_days", 9999),
            thresholds=thresholds,
        )

    if signal_type == "ai_maturity":
        return _register_ai_maturity(
            score=kwargs.get("score", 0),
            confidence=kwargs.get("confidence", "low"),
            thresholds=thresholds,
        )

    return "ask"  # safe fallback — unreachable given the guard above


# ---------------------------------------------------------------------------
# Signal-specific register helpers
# ---------------------------------------------------------------------------

def _register_job_velocity(
    min_roles: int,
    min_sources: int,
    age_days: int,
    thresholds: dict,
) -> str:
    a = thresholds["assert"]
    h = thresholds["hedge"]

    if (
        min_roles >= a["min_roles"]
        and min_sources >= a["min_sources"]
        and age_days <= a["max_age_days"]
    ):
        return "assert"

    if (
        min_roles >= h["min_roles"]
        and min_sources >= h["min_sources"]
        and age_days <= h["max_age_days"]
    ):
        return "hedge"

    return "ask"


def _register_funding(
    amount_usd: int | float,
    age_days: int,
    thresholds: dict,
) -> str:
    a = thresholds["assert"]
    h = thresholds["hedge"]

    if amount_usd >= a["min_amount_usd"] and age_days <= a["max_age_days"]:
        return "assert"

    if amount_usd >= h["min_amount_usd"] and age_days <= h["max_age_days"]:
        return "hedge"

    return "ask"


def _register_age_only(age_days: int, thresholds: dict) -> str:
    """Used for layoff and leadership signals where age alone determines register."""
    a = thresholds["assert"]
    h = thresholds["hedge"]

    if age_days <= a["max_age_days"]:
        return "assert"

    if age_days <= h["max_age_days"]:
        return "hedge"

    return "ask"


def _register_ai_maturity(
    score: int,
    confidence: str,
    thresholds: dict,
) -> str:
    a = thresholds["assert"]
    h = thresholds["hedge"]

    # Normalise confidence string
    confidence = confidence.lower().strip()
    confidence_rank = _CONFIDENCE_ORDER.index(confidence) if confidence in _CONFIDENCE_ORDER else 0

    min_confidence_rank = _CONFIDENCE_ORDER.index(a["min_confidence"])

    if score >= a["min_score"] and confidence_rank >= min_confidence_rank:
        return "assert"

    if score >= h["min_score"]:
        return "hedge"

    return "ask"


# ---------------------------------------------------------------------------
# Convenience: job velocity language string
# ---------------------------------------------------------------------------

def get_velocity_language(open_roles: int, sources: int, age_days: int) -> str:
    """
    Return the exact language register string for job velocity, including a
    human-readable sentence fragment that can be used directly in signal_opening.

    Parameters
    ----------
    open_roles : int  — number of open engineering roles observed
    sources    : int  — number of independent sources confirming the roles
    age_days   : int  — age of the most recent observation in days

    Returns
    -------
    str — a register-appropriate sentence fragment (not a full sentence)
    """
    register = get_register(
        "job_velocity",
        open_roles=open_roles,
        sources=sources,
        age_days=age_days,
    )

    if register == "assert":
        return (
            f"You currently have {open_roles} open engineering roles — "
            f"a signal of active team growth."
        )

    if register == "hedge":
        return (
            f"It looks like you may have around {open_roles} open engineering roles "
            f"based on recent postings."
        )

    # ask register
    return "Are you in an active period of engineering team growth right now?"


# ---------------------------------------------------------------------------
# Register dispatcher: apply the right text for a given register
# ---------------------------------------------------------------------------

def apply_register(
    register: str,
    assert_text: str,
    hedge_text: str,
    ask_text: str,
) -> str:
    """
    Return the right text based on the register value.

    Parameters
    ----------
    register    : str  — one of 'assert', 'hedge', 'ask'
    assert_text : str  — language to use when signal is strong
    hedge_text  : str  — language to use when signal is weak or aging
    ask_text    : str  — language to use when signal is unconfirmed (question form)

    Returns
    -------
    str — the appropriate text for the given register

    Raises
    ------
    ValueError — if register is not one of the three valid values
    """
    register = register.lower().strip()

    if register == "assert":
        return assert_text
    if register == "hedge":
        return hedge_text
    if register == "ask":
        return ask_text

    raise ValueError(
        f"Invalid register '{register}'. Must be one of: 'assert', 'hedge', 'ask'."
    )


# ---------------------------------------------------------------------------
# Batch convenience: evaluate all signals in a brief at once
# ---------------------------------------------------------------------------

def evaluate_brief_signals(brief: dict) -> dict[str, str]:
    """
    Given a prospect brief dict, evaluate every present signal and return a
    mapping of signal_type → register.

    Expected brief keys (all optional):
        funding_amount_usd, funding_age_days
        layoff_age_days
        leadership_change_age_days
        job_velocity_open_roles, job_velocity_sources, job_velocity_age_days
        ai_maturity_score, ai_maturity_confidence

    Returns
    -------
    dict[str, str] — e.g. {"funding": "assert", "layoff": "hedge", ...}
    Only includes keys for signals present in the brief.
    """
    results: dict[str, str] = {}

    if "funding_amount_usd" in brief or "funding_age_days" in brief:
        results["funding"] = get_register(
            "funding",
            amount_usd=brief.get("funding_amount_usd", 0),
            age_days=brief.get("funding_age_days", 9999),
        )

    if "layoff_age_days" in brief:
        results["layoff"] = get_register(
            "layoff",
            age_days=brief.get("layoff_age_days", 9999),
        )

    if "leadership_change_age_days" in brief:
        results["leadership"] = get_register(
            "leadership",
            age_days=brief.get("leadership_change_age_days", 9999),
        )

    if "job_velocity_open_roles" in brief or "job_velocity_age_days" in brief:
        results["job_velocity"] = get_register(
            "job_velocity",
            open_roles=brief.get("job_velocity_open_roles", 0),
            sources=brief.get("job_velocity_sources", 0),
            age_days=brief.get("job_velocity_age_days", 9999),
        )

    if "ai_maturity_score" in brief:
        results["ai_maturity"] = get_register(
            "ai_maturity",
            score=brief.get("ai_maturity_score", 0),
            confidence=brief.get("ai_maturity_confidence", "low"),
        )

    return results
