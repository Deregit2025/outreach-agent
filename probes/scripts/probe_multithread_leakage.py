"""
probe_multithread_leakage.py — Probes 21-22: Multi-Thread Context Leakage.

Tests that ConversationState is keyed by prospect_id (UUID), not company_name.
Two separate threads for the same company must be fully independent.
All assertions are deterministic — no LLM calls.
"""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agent.state import ConversationState


def run_probe() -> dict:
    failures: list[str] = []
    details: list[str] = []

    COMPANY = "Acme Technologies"

    # ── Probe 21: Two states for same company, different prospect_ids ─────────
    state1 = ConversationState(
        prospect_id="pid-cofounder-001",
        company_name=COMPANY,
        stage="qualifying",
    )
    state2 = ConversationState(
        prospect_id="pid-vpeng-002",
        company_name=COMPANY,
        stage="new",
    )

    # Confirm they are independent objects with different prospect_ids
    ok21_ids = state1.prospect_id != state2.prospect_id
    ok21_same_company = state1.company_name == state2.company_name
    details.append(
        f"Probe 21a (same company, different IDs): "
        f"pid1={state1.prospect_id}, pid2={state2.prospect_id}, "
        f"same_company={ok21_same_company} — {'PASS' if ok21_ids else 'FAIL'}"
    )
    if not ok21_ids:
        failures.append(
            "Probe 21a: two ConversationState objects for same company must have "
            "different prospect_ids"
        )

    # ── Probe 22: Answering Q in state1 must not affect state2 ────────────────
    # Set a qualification answer in state1
    state1.qualification.q1_initiative = "Build a real-time ML inference pipeline"
    state1.record_inbound("email", "We are building a real-time ML inference pipeline.")

    # State2 must remain unaffected
    ok22_qual = state2.qualification.q1_initiative is None
    ok22_messages = len(state2.messages) == 0
    ok22_stage = state2.stage == "new"
    ok22 = ok22_qual and ok22_messages and ok22_stage
    details.append(
        f"Probe 22 (no leakage after state1 update): "
        f"state2.q1={state2.qualification.q1_initiative}, "
        f"state2.messages={len(state2.messages)}, "
        f"state2.stage={state2.stage} — {'PASS' if ok22 else 'FAIL'}"
    )
    if not ok22:
        failures.append(
            f"Probe 22: answering Q1 in state1 must not affect state2; "
            f"q1={state2.qualification.q1_initiative}, "
            f"messages={len(state2.messages)}, stage={state2.stage}"
        )

    # ── Probe 22b: State1 changes don't retroactively affect state2 ──────────
    state1.transition_to("qualifying")
    state1.email_touches = 3
    ok22b = state2.stage == "new" and state2.email_touches == 0
    details.append(
        f"Probe 22b (stage/touch independence): "
        f"state2.stage={state2.stage}, state2.email_touches={state2.email_touches} "
        f"— {'PASS' if ok22b else 'FAIL'}"
    )
    if not ok22b:
        failures.append(
            f"Probe 22b: state1 stage/touch mutations must not affect state2"
        )

    # ── Probe 22c: State serialization preserves prospect_id ─────────────────
    serialized1 = state1.model_dump_json()
    data1 = json.loads(serialized1)
    ok22c = data1["prospect_id"] == "pid-cofounder-001"
    ok22c_company = data1["company_name"] == COMPANY
    details.append(
        f"Probe 22c (serialization preserves prospect_id): "
        f"prospect_id='{data1.get('prospect_id')}', "
        f"company_name='{data1.get('company_name')}' — {'PASS' if ok22c else 'FAIL'}"
    )
    if not ok22c:
        failures.append(
            f"Probe 22c: model_dump_json() must preserve prospect_id='pid-cofounder-001'; "
            f"got '{data1.get('prospect_id')}'"
        )

    # Also verify state2 serialization is distinct
    serialized2 = state2.model_dump_json()
    data2 = json.loads(serialized2)
    ok22c2 = data2["prospect_id"] == "pid-vpeng-002"
    details.append(
        f"Probe 22c (state2 prospect_id in serialized form): "
        f"'{data2.get('prospect_id')}' — {'PASS' if ok22c2 else 'FAIL'}"
    )
    if not ok22c2:
        failures.append(
            f"Probe 22c: state2.model_dump_json() must have prospect_id='pid-vpeng-002'; "
            f"got '{data2.get('prospect_id')}'"
        )

    # ── Probe 22d: Company rename scenario — state keyed by prospect_id ───────
    # Simulate company rename: state is loaded by prospect_id, not company_name.
    # After rename, updating company_name on state1 must not affect state2's company_name.
    original_company_s2 = state2.company_name
    state1.company_name = "Acme Technologies (formerly AcmeCo)"
    ok22d = state2.company_name == original_company_s2
    details.append(
        f"Probe 22d (company rename independence): "
        f"state2.company_name='{state2.company_name}' "
        f"— {'PASS' if ok22d else 'FAIL'}"
    )
    if not ok22d:
        failures.append(
            f"Probe 22d: renaming company in state1 must not affect state2"
        )

    passed = len(failures) == 0
    return {
        "probe_id": "multithread_leakage",
        "passed": passed,
        "details": details,
        "failures": failures,
        "business_cost_label": (
            "Very High — cross-thread context leakage signals machine processing "
            "to prospects and destroys trust; e.g. referencing co-founder answers in VP Eng thread"
        ),
    }


if __name__ == "__main__":
    import json
    result = run_probe()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["passed"] else 1)
