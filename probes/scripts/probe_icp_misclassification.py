"""
probe_icp_misclassification.py — Probes 1-6: ICP Misclassification failures.

Tests classify_with_abstention() against six boundary-condition scenarios where
the classifier must either abstain, escalate, or refuse segment_specific mode.
All assertions are deterministic — no LLM calls.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mechanism.icp_abstention import classify_with_abstention


def _sig(
    signal_type: str,
    confidence: str,
    age_days: int | None = None,
    value: str = "",
) -> dict:
    register = (
        "assert" if confidence == "high"
        else "hedge" if confidence == "medium"
        else "ask"
    )
    return {
        "signal_type": signal_type,
        "confidence": confidence,
        "data_age_days": age_days,
        "value": value,
        "language_register": register,
    }


def run_probe() -> dict:
    failures: list[str] = []
    details: list[str] = []

    # ── Probe 1: Post-layoff company mis-assigned Segment 1 ──────────────────
    # Company raised $12M Series B 90 days ago AND laid off 25% of staff 45 days ago.
    # The layoff is recent (≤90 days) → score gets *0.5 penalty → should NOT be segment_specific.
    signals_p1 = [
        _sig("funding", "high", age_days=90, value="$12M Series B"),
        _sig("layoff", "high", age_days=45, value="25% staff reduction"),
        _sig("job_velocity", "medium", age_days=90, value="5 open engineering roles"),
    ]
    r1 = classify_with_abstention(
        segment=1, signals=signals_p1, employee_min=50, employee_max=70
    )
    ok1 = r1.pitch_mode != "segment_specific"
    details.append(
        f"Probe 1 (post-layoff Seg1): pitch_mode={r1.pitch_mode}, "
        f"score={r1.confidence_score} — {'PASS' if ok1 else 'FAIL'}"
    )
    if not ok1:
        failures.append(
            f"Probe 1: recent layoff (45 days) must prevent segment_specific Seg1 pitch; "
            f"got pitch_mode='{r1.pitch_mode}' score={r1.confidence_score}"
        )

    # ── Probe 2: Headcount 350 for Segment 1 → employee range mismatch ───────
    # Segment 1 requires 15-80 employees; midpoint of (320,380) = 350 → score *= 0.6 penalty.
    # Expect: not segment_specific
    signals_p2 = [
        _sig("funding", "high", age_days=30, value="$8M Series A"),
        _sig("job_velocity", "medium", age_days=20, value="8 open engineering roles"),
    ]
    r2 = classify_with_abstention(
        segment=1, signals=signals_p2, employee_min=320, employee_max=380
    )
    ok2 = r2.pitch_mode != "segment_specific"
    details.append(
        f"Probe 2 (headcount 350 for Seg1): pitch_mode={r2.pitch_mode}, "
        f"score={r2.confidence_score} — {'PASS' if ok2 else 'FAIL'}"
    )
    if not ok2:
        failures.append(
            f"Probe 2: headcount 350 is outside Seg1 range (15-80); "
            f"got '{r2.pitch_mode}' score={r2.confidence_score}"
        )

    # ── Probe 3: Segment 4 pitch with ai_maturity_score=0 ────────────────────
    # Only a low-confidence tech_stack signal; no ai_maturity signal.
    # Seg4 required: ["ai_maturity"] — missing → raw score will be tiny → escalate.
    signals_p3 = [
        _sig("tech_stack", "low", age_days=60, value="Python, Node"),
    ]
    r3 = classify_with_abstention(
        segment=4, signals=signals_p3, employee_min=40, employee_max=60
    )
    ok3 = r3.pitch_mode != "segment_specific"
    details.append(
        f"Probe 3 (Seg4 zero AI maturity): pitch_mode={r3.pitch_mode}, "
        f"score={r3.confidence_score} — {'PASS' if ok3 else 'FAIL'}"
    )
    if not ok3:
        failures.append(
            f"Probe 3: Seg4 with no AI maturity signal must NOT be segment_specific; "
            f"got '{r3.pitch_mode}' score={r3.confidence_score}"
        )

    # ── Probe 4: Segment 1 with no funding signal → should abstain/escalate ──
    # Funding is required for Seg1; only low-confidence job_velocity present.
    signals_p4 = [
        _sig("job_velocity", "low", age_days=120, value="2 open engineering roles"),
    ]
    r4 = classify_with_abstention(
        segment=1, signals=signals_p4, employee_min=30, employee_max=50
    )
    ok4 = r4.pitch_mode in ("exploratory", "escalate")
    details.append(
        f"Probe 4 (Seg1 no funding): pitch_mode={r4.pitch_mode}, "
        f"score={r4.confidence_score} — {'PASS' if ok4 else 'FAIL'}"
    )
    if not ok4:
        failures.append(
            f"Probe 4: Seg1 with no funding and only low-confidence job signal "
            f"must abstain/escalate; got '{r4.pitch_mode}' score={r4.confidence_score}"
        )

    # ── Probe 5: Segment 2 with 0 engineering roles → should escalate ────────
    # Only layoff signal (high, 30 days old). Required: ["layoff"]. Score =
    # 0.30 * 1.0 * 1.5 = 0.45 → below ABSTAIN_THRESHOLD (0.50) → escalate.
    signals_p5 = [
        _sig("layoff", "high", age_days=30, value="15% staff reduction"),
    ]
    r5 = classify_with_abstention(
        segment=2, signals=signals_p5, employee_min=400, employee_max=600
    )
    ok5 = r5.confidence_score < 0.70  # must not reach high-confidence territory
    details.append(
        f"Probe 5 (Seg2 zero eng roles, only layoff): pitch_mode={r5.pitch_mode}, "
        f"score={r5.confidence_score} — {'PASS' if ok5 else 'FAIL'}"
    )
    if not ok5:
        failures.append(
            f"Probe 5: Seg2 with only layoff signal and 0 eng roles should not "
            f"reach high confidence; got score={r5.confidence_score}"
        )

    # ── Probe 6: Valid Segment 3 with fresh high-confidence leadership change ─
    # Required for Seg3: ["leadership_change"] — present at high confidence, fresh.
    # Supporting: funding (medium) + ai_maturity (medium). Should be segment_specific.
    signals_p6 = [
        _sig("leadership_change", "high", age_days=20, value="New VP Engineering hired"),
        _sig("funding", "medium", age_days=60, value="$5M Series A"),
        _sig("ai_maturity", "medium", age_days=45, value="ML team building"),
    ]
    r6 = classify_with_abstention(
        segment=3, signals=signals_p6, employee_min=35, employee_max=65
    )
    ok6 = r6.pitch_mode == "segment_specific"
    details.append(
        f"Probe 6 (valid Seg3 leadership change): pitch_mode={r6.pitch_mode}, "
        f"score={r6.confidence_score} — {'PASS' if ok6 else 'FAIL'}"
    )
    if not ok6:
        failures.append(
            f"Probe 6: Seg3 with fresh high-confidence leadership change and supporting "
            f"signals should be segment_specific; got '{r6.pitch_mode}' score={r6.confidence_score}"
        )

    passed = len(failures) == 0
    return {
        "probe_id": "icp_misclassification",
        "passed": passed,
        "details": details,
        "failures": failures,
        "business_cost_label": (
            "High — wrong-segment pitches cause permanent brand damage "
            "(e.g., growth pitch to a company mid-layoff)"
        ),
    }


if __name__ == "__main__":
    import json
    result = run_probe()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
