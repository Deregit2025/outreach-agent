 """
probe_gap_overclaiming.py — Probes 12 + 18: Competitor Gap Fabrication failures.

Tests that competitor gap framing does not fabricate claims from thin data,
and that condescending gap language fails the tone check.
All assertions are deterministic — no LLM calls.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mechanism.confidence_aware_phrasing import adjust_claim, detect_overclaim, build_grounded_opener
from mechanism.tone_preservation import check_tone


def _gap_claim_register(peer_count: int) -> str:
    """
    Determine the language register for a competitor gap claim based on peer_count.

    Matches the spec: when peer_count < 3, gap claims must use 'ask' not 'assert'.
    """
    if peer_count < 3:
        return "ask"
    elif peer_count < 5:
        return "hedge"
    else:
        return "assert"


def run_probe() -> dict:
    failures: list[str] = []
    details: list[str] = []

    # ── Probe Gap-1: peer_count < 3 → gap claims must use "ask" register ──────
    # When only 2 sector peers are found, the competitor gap claim must not assert.
    peer_count_thin = 2
    register_thin = _gap_claim_register(peer_count_thin)
    ok_gap1 = register_thin == "ask"
    details.append(
        f"Probe Gap-1 (peer_count={peer_count_thin} → register): "
        f"register={register_thin} — {'PASS' if ok_gap1 else 'FAIL'}"
    )
    if not ok_gap1:
        failures.append(
            f"Probe Gap-1: peer_count={peer_count_thin} (< 3) must produce 'ask' register; "
            f"got '{register_thin}'"
        )

    # Also verify adjust_claim with low confidence shifts the gap assertion
    gap_assert_claim = "Your competitors are all adopting AI-powered pipelines at scale."
    rephrased_gap = adjust_claim(gap_assert_claim, confidence="low", signal_type="ai_maturity")
    ok_gap1b = "?" in rephrased_gap or "may suggest" in rephrased_gap
    details.append(
        f"Probe Gap-1b (low-conf gap claim rephrased): '{rephrased_gap[:80]}' "
        f"— {'PASS' if ok_gap1b else 'FAIL'}"
    )
    if not ok_gap1b:
        failures.append(
            f"Probe Gap-1b: low-confidence gap claim must become ask register; "
            f"got '{rephrased_gap}'"
        )

    # ── Probe Gap-2: "competitors are beating you" framing → must fail tone ───
    # This exact phrase is in PROHIBITED_PHRASES in tone_preservation.py
    draft_condescending_gap = (
        "Hi,\n\n"
        "Based on our market research, your competitors are beating you in AI adoption. "
        "Companies in your sector have already integrated ML pipelines that you have not.\n\n"
        "Would it make sense to discuss how Tenacious can help close that gap?"
    )
    result_gap2 = check_tone(draft_condescending_gap)
    ok_gap2 = (
        not result_gap2.passed
        and "your competitors are beating you" in result_gap2.prohibited_hits
    )
    details.append(
        f"Probe Gap-2 (condescending gap framing): passed={result_gap2.passed}, "
        f"prohibited_hits={result_gap2.prohibited_hits}, score={result_gap2.score} "
        f"— {'PASS' if ok_gap2 else 'FAIL'}"
    )
    if not ok_gap2:
        failures.append(
            f"Probe Gap-2: 'your competitors are beating you' must fail tone check; "
            f"got passed={result_gap2.passed}, prohibited_hits={result_gap2.prohibited_hits}"
        )

    # ── Probe Gap-3: Valid framing → must pass tone check ─────────────────────
    # "leading companies in your space are doing X" is the correct framing.
    draft_good_gap = (
        "Hi,\n\n"
        "I noticed that leading companies in your space are building out dedicated "
        "data engineering capacity — typically through a mix of in-house hiring and "
        "an external team that can ramp quickly on existing infrastructure.\n\n"
        "Based on what we can see publicly about your stack and team, I wanted to "
        "check whether that is a direction worth exploring for you.\n\n"
        "Would a short conversation make sense?"
    )
    result_gap3 = check_tone(draft_good_gap)
    ok_gap3 = result_gap3.passed
    details.append(
        f"Probe Gap-3 (valid gap framing): passed={result_gap3.passed}, "
        f"score={result_gap3.score} — {'PASS' if ok_gap3 else 'FAIL'}"
    )
    if not ok_gap3:
        failures.append(
            f"Probe Gap-3: 'leading companies in your space...' framing should pass "
            f"tone check; got passed={result_gap3.passed}, score={result_gap3.score}, "
            f"flags={result_gap3.flags}"
        )

    # ── Probe Gap-4: detect_overclaim on fabricated gap signal ───────────────
    # A draft that asserts a specific competitor count with thin data
    draft_fabricated = (
        "We have analysed 15 companies in your sector and all of them have already "
        "adopted ML pipelines. You are behind the curve on AI adoption."
    )
    fabricated_signals = [
        {
            "signal_type": "ai_maturity",
            "value": "15 companies",
            "confidence": "low",
            "language_register": "assert",  # wrongly marked assert
        }
    ]
    warnings_gap4 = detect_overclaim(draft_fabricated, fabricated_signals)
    # detect_overclaim looks for assertive openers + low-conf signal values in draft
    # The signal value "15 companies" — check if detection fires
    # Note: if "15" appears in draft and opener "you are" is present → warning
    ok_gap4 = len(warnings_gap4) > 0
    details.append(
        f"Probe Gap-4 (fabricated gap detect_overclaim): warnings={warnings_gap4} "
        f"— {'PASS' if ok_gap4 else 'FAIL'}"
    )
    if not ok_gap4:
        failures.append(
            "Probe Gap-4: detect_overclaim must catch low-confidence gap claims "
            "using assertive language in draft"
        )

    passed = len(failures) == 0
    return {
        "probe_id": "gap_overclaiming",
        "passed": passed,
        "details": details,
        "failures": failures,
        "business_cost_label": (
            "Very High — fabricated competitor comparisons are immediately "
            "checkable by prospects who know their market; destroys credibility"
        ),
    }


if __name__ == "__main__":
    import json
    result = run_probe()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
