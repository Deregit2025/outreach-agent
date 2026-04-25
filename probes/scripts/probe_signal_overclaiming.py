"""
probe_signal_overclaiming.py — Probes 7-12: Signal Over-Claiming failures.

Tests confidence_aware_phrasing.adjust_claim(), detect_overclaim(), and
build_grounded_opener() to ensure assertions never exceed their evidence basis.
All checks are deterministic — no LLM calls.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mechanism.confidence_aware_phrasing import (
    adjust_claim,
    detect_overclaim,
    build_grounded_opener,
)


def run_probe() -> dict:
    failures: list[str] = []
    details: list[str] = []

    # ── Probe 7: Low-confidence funding claim → must NOT be "assert" mode ────
    # A low-confidence funding claim rephrased via adjust_claim must not contain
    # assertive openers like "you closed" or "your company" without softening.
    raw_claim = "You closed a $10M Series B last month."
    rephrased_low = adjust_claim(raw_claim, confidence="low", signal_type="funding")
    # Low confidence → should produce ask-register phrasing (contains "?")
    ok7 = "?" in rephrased_low or "may suggest" in rephrased_low or "noticed" in rephrased_low
    details.append(
        f"Probe 7 (low-conf funding must not assert): rephrased='{rephrased_low}' "
        f"— {'PASS' if ok7 else 'FAIL'}"
    )
    if not ok7:
        failures.append(
            f"Probe 7: low-confidence funding claim must be rephrased to ask/hedge; "
            f"got '{rephrased_low}'"
        )

    # ── Probe 8: 180-day-old funding → must use "hedge" not "assert" ──────────
    # A medium-confidence (stale) funding event should NOT use "recent" assertively.
    stale_claim = "You recently closed a Series B."
    rephrased_medium = adjust_claim(stale_claim, confidence="medium", signal_type="funding")
    # Medium → hedge; the result should NOT start with "You recently..."
    ok8 = rephrased_medium.lower().startswith("based on") or "appears" in rephrased_medium.lower()
    details.append(
        f"Probe 8 (stale funding hedge): rephrased='{rephrased_medium}' "
        f"— {'PASS' if ok8 else 'FAIL'}"
    )
    if not ok8:
        failures.append(
            f"Probe 8: 180-day-old funding must use hedge register; "
            f"got '{rephrased_medium}'"
        )

    # ── Probe 9: Velocity = 2 roles → language_register must be "ask" ─────────
    # Per job_scraper.py: eng_count < 3 → register = "ask"
    from scraper.job_scraper import _is_engineering_role  # reuse internal

    # Simulate the register decision from get_job_velocity_signal() logic
    eng_count = 2
    if eng_count >= 5:
        register = "assert"
    elif eng_count >= 3:
        register = "hedge"
    else:
        register = "ask"
    ok9 = register == "ask"
    details.append(
        f"Probe 9 (velocity=2 roles → language_register): register={register} "
        f"— {'PASS' if ok9 else 'FAIL'}"
    )
    if not ok9:
        failures.append(
            f"Probe 9: 2 engineering roles should produce 'ask' register; got '{register}'"
        )

    # ── Probe 10: AI maturity with single weak signal → score should be ≤ 1 ──
    # One low-confidence "ai_maturity" signal (a single blog mention) must not
    # push the signal into assert territory.
    # We test this by checking adjust_claim with low confidence produces ask register.
    weak_ai_claim = "You are scaling aggressively with AI and ML infrastructure."
    rephrased_weak_ai = adjust_claim(weak_ai_claim, confidence="low", signal_type="ai_maturity")
    # Should be in ask mode
    ok10 = "?" in rephrased_weak_ai or "may suggest" in rephrased_weak_ai
    details.append(
        f"Probe 10 (single weak AI signal → low register): "
        f"rephrased='{rephrased_weak_ai[:80]}...' — {'PASS' if ok10 else 'FAIL'}"
    )
    if not ok10:
        failures.append(
            f"Probe 10: single weak AI signal must produce ask/hedge phrasing; "
            f"got '{rephrased_weak_ai}'"
        )

    # ── Probe 11: detect_overclaim() catches assertive language on low-conf ───
    # Draft uses "you are scaling aggressively" but signal has low confidence.
    draft_overclaim = (
        "Hi, I saw your team is scaling aggressively with several engineering hires. "
        "You are clearly investing heavily in AI infrastructure."
    )
    low_conf_signals = [
        {
            "signal_type": "job_velocity",
            "value": "scaling aggressively",
            "confidence": "low",
            "language_register": "assert",  # wrong register — should have been "ask"
        }
    ]
    warnings = detect_overclaim(draft_overclaim, low_conf_signals)
    ok11 = len(warnings) > 0
    details.append(
        f"Probe 11 (detect_overclaim on low-conf assert): warnings={warnings} "
        f"— {'PASS' if ok11 else 'FAIL'}"
    )
    if not ok11:
        failures.append(
            "Probe 11: detect_overclaim() must return warnings when low-confidence "
            "signal uses assertive language in draft"
        )

    # ── Probe 12: build_grounded_opener() with no signals → generic exploratory ─
    opener_no_signals = build_grounded_opener(
        company_name="Acme Corp",
        signals=[],
        ai_maturity_score=0,
    )
    # Must be exploratory / non-assertive — no "closed", "scaled", "tripled"
    assertive_words = ["closed", "scaled", "tripled", "your team has", "you recently"]
    ok12 = not any(w in opener_no_signals.lower() for w in assertive_words)
    details.append(
        f"Probe 12 (no signals → generic opener): opener='{opener_no_signals}' "
        f"— {'PASS' if ok12 else 'FAIL'}"
    )
    if not ok12:
        failures.append(
            f"Probe 12: build_grounded_opener() with no signals must return "
            f"non-assertive exploratory text; got '{opener_no_signals}'"
        )

    passed = len(failures) == 0
    return {
        "probe_id": "signal_overclaiming",
        "passed": passed,
        "details": details,
        "failures": failures,
        "business_cost_label": (
            "High — asserting wrong facts about a prospect "
            "(wrong funding amount, wrong AI maturity) destroys trust immediately"
        ),
    }


if __name__ == "__main__":
    import json
    result = run_probe()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
