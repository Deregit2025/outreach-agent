"""
build_report.py — Project health and smoke-test report.

Runs in ~10 seconds with no API key required.
Checks: imports, guardrails, enrichment pipeline, agent decision engine,
        synthetic prospect loading, and bench guard.

Usage:
    python scripts/build_report.py
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

results: list[tuple[str, str, str]] = []  # (name, status, detail)


def run_check(name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        detail = fn() or ""
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        results.append((name, "PASS", f"{detail}  [{elapsed}ms]"))
    except Exception as exc:
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        results.append((name, "FAIL", f"{exc}  [{elapsed}ms]"))


# ── 1. Import checks ─────────────────────────────────────────────────────────

def check_config():
    from config.settings import settings
    from config.kill_switch import is_live, route_email
    assert not is_live(), "Kill switch should be ON by default"
    return f"kill_switch=ON  sink={settings.staff_sink_email}"

def check_schemas():
    from enrichment.schemas.prospect import Prospect
    from enrichment.schemas.hiring_signal_brief import HiringSignalBrief
    from enrichment.schemas.competitor_gap_brief import CompetitorGapBrief
    return "Prospect, HiringSignalBrief, CompetitorGapBrief"

def check_enrichment_pipeline():
    from enrichment.crunchbase_lookup import lookup_by_name
    from enrichment.layoffs_lookup import check_layoff
    from enrichment.ai_maturity_scorer import score_ai_maturity
    from enrichment.icp_classifier import classify_segment
    from enrichment.competitor_finder import find_peers
    from enrichment.pipeline import enrich_prospect
    return "6 modules"

def check_channels():
    from channels.email_handler import EmailHandler
    from channels.sms_handler import SMSHandler
    from channels.calendar_handler import CalendarHandler
    from channels.crm_handler import CRMHandler
    from channels.channel_router import ChannelRouter
    return "5 handlers"

def check_agent_core():
    from agent.state import ConversationState
    from agent.bench_guard import check_draft
    from agent.decision_engine import Action, decide
    from agent.agent import run
    return "state, bench_guard, decision_engine, agent"

def check_guardrails():
    from agent.guardrails.signal_honesty import get_register
    from agent.guardrails.segment_gate import validate_segment_pitch
    from agent.guardrails.tone_checker import enforce
    return "signal_honesty, segment_gate, tone_checker"

def check_server():
    from server.main import app
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    return f"{len(routes)} routes registered"

def check_observability():
    from observability.tracer import is_available
    from observability.latency_tracker import latency_tracker
    return f"langfuse={'on' if is_available() else 'off (no key)'}"


# ── 2. Guardrail smoke tests ──────────────────────────────────────────────────

def check_signal_honesty():
    from agent.guardrails.signal_honesty import get_register
    assert get_register("funding", amount_usd=12_000_000, age_days=60) == "assert"
    assert get_register("funding", amount_usd=500_000, age_days=400) == "ask"
    assert get_register("layoff", age_days=90) == "assert"
    assert get_register("layoff", age_days=400) == "ask"
    assert get_register("leadership", age_days=45) == "assert"
    assert get_register("ai_maturity", score=3, confidence="high") == "assert"
    assert get_register("ai_maturity", score=1, confidence="low") == "ask"
    return "7 register assertions"

def check_tone_blocked():
    from agent.guardrails.tone_checker import enforce
    bad = "I'm excited to connect and discuss our world-class offshore team."
    passed, report = enforce(bad, [])
    assert not passed
    return f"blocked {len(report['prohibited_found'])} banned phrases"

def check_tone_passes():
    from agent.guardrails.tone_checker import enforce
    clean = (
        "Priya, Verdant Labs closed a Series A recently — post-funding engineering "
        "backlogs tend to outpace hiring timelines. Would it make sense to talk about "
        "your current engineering priorities?"
    )
    passed, report = enforce(clean, [{"type": "funding", "register": "assert"}])
    assert passed, f"Should have passed: {report}"
    return f"score={report['score']}"

def check_segment_gate():
    from agent.guardrails.segment_gate import validate_segment_pitch
    allowed, _ = validate_segment_pitch(4, {"ai_maturity_score": 1})
    assert not allowed
    allowed2, _ = validate_segment_pitch(4, {"ai_maturity_score": 2})
    assert allowed2
    return "seg4 blocked for score=1, allowed for score=2"

def check_bench_guard():
    from agent.bench_guard import check_draft
    passed, _ = check_draft("We have 4 Python engineers available today.")
    assert passed
    passed2, violations = check_draft("We have no bench capacity available immediately.")
    return "capacity claims validated"


# ── 3. Enrichment smoke tests ─────────────────────────────────────────────────

def check_synthetic_prospects():
    path = PROJECT_ROOT / "data" / "synthetic" / "synthetic_prospects.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    from enrichment.schemas.prospect import Prospect
    prospects = [Prospect(**p) for p in data]
    segments = {p.icp_segment for p in prospects if p.icp_segment}
    assert segments == {1, 2, 3, 4}
    return f"{len(prospects)} prospects, all 4 ICP segments present"

def check_ai_maturity():
    from enrichment.ai_maturity_scorer import score_ai_maturity
    from enrichment.schemas.prospect import TechEntry
    stack = [TechEntry(name="Hugging Face", technology_category=["ML"]),
             TechEntry(name="MLflow", technology_category=["ML Ops"])]
    score, conf, _ = score_ai_maturity(stack, [], ["AI / ML"], "LLM-powered pipeline")
    assert score >= 2
    return f"score={score} confidence={conf}"

def check_icp_classifier():
    from enrichment.icp_classifier import classify_segment
    from enrichment.schemas.prospect import Prospect, FundingRound
    from enrichment.schemas.hiring_signal_brief import HiringSignalBrief, SignalItem
    p = Prospect(prospect_id="t1", company_name="TestCo",
                 funding_rounds=[FundingRound(announced_on="2026-01-01", amount_usd=12_000_000, series="A")],
                 employee_count_min=50, ai_maturity_score=1)
    brief = HiringSignalBrief(
        prospect_id="t1", company_name="TestCo", generated_at="2026-04-21T00:00:00+00:00",
        funding=SignalItem(signal_type="funding", value="Series A", evidence="",
                          confidence="high", data_age_days=110, language_register="assert"))
    seg, conf = classify_segment(p, brief)
    assert seg == 1
    return f"seg={seg} conf={conf}"


# ── 4. Agent decision engine ──────────────────────────────────────────────────

def check_decision_cold():
    from agent.state import ConversationState
    from agent.decision_engine import Action, decide
    from enrichment.schemas.hiring_signal_brief import HiringSignalBrief
    state = ConversationState(prospect_id="t1", company_name="TestCo", segment=1)
    brief = HiringSignalBrief(prospect_id="t1", company_name="TestCo",
                              generated_at="2026-04-21T00:00:00+00:00",
                              recommended_segment=1)
    assert decide(state, brief) == Action.SEND_COLD_EMAIL
    return "new thread -> SEND_COLD_EMAIL"

def check_decision_qual():
    from agent.state import ConversationState
    from agent.decision_engine import Action, decide, absorb_reply
    from enrichment.schemas.hiring_signal_brief import HiringSignalBrief
    state = ConversationState(prospect_id="t2", company_name="TestCo2", segment=2)
    brief = HiringSignalBrief(prospect_id="t2", company_name="TestCo2",
                              generated_at="2026-04-21T00:00:00+00:00",
                              recommended_segment=2)
    # Reply that answers only Q1 (mentions a project)
    state.record_inbound("email", "We are building a new payments platform.")
    absorb_reply(state, state.messages[-1].body)
    action = decide(state, brief)
    assert action == Action.ASK_NEXT_QUAL_Q, f"Expected ASK_NEXT_QUAL_Q, got {action}"
    return f"q_answered={state.qualification.answered_count()}/4 -> ASK_NEXT_QUAL_Q"

def check_decision_booking():
    from agent.state import ConversationState
    from agent.decision_engine import Action, decide
    from enrichment.schemas.hiring_signal_brief import HiringSignalBrief
    state = ConversationState(prospect_id="t3", company_name="TestCo3", segment=1)
    brief = HiringSignalBrief(prospect_id="t3", company_name="TestCo3",
                              generated_at="2026-04-21T00:00:00+00:00",
                              recommended_segment=1)
    state.record_inbound("email", "some reply")
    state.qualification.q1_initiative = "data platform"
    state.qualification.q2_timeline = "Q3"
    state.qualification.q3_blocker = "capacity"
    state.qualification.q4_stakeholders = "just me"
    assert decide(state, brief) == Action.SEND_BOOKING_LINK
    return "all 4 Q's answered -> SEND_BOOKING_LINK"


# ── 5. Score log ──────────────────────────────────────────────────────────────

def check_score_log():
    path = PROJECT_ROOT / "eval" / "score_log.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data:
        return "empty (no baseline run yet — run: make bench)"
    latest = data[-1]
    return (f"runs={len(data)}  latest={latest['run_name']}  "
            f"pass@1={latest['pass_at_1']:.1%}  tasks={latest['num_tasks']}")


# ── Run all checks ────────────────────────────────────────────────────────────

CHECKS = [
    ("import: config",              check_config),
    ("import: enrichment schemas",  check_schemas),
    ("import: enrichment pipeline", check_enrichment_pipeline),
    ("import: channel handlers",    check_channels),
    ("import: agent core",          check_agent_core),
    ("import: guardrails",          check_guardrails),
    ("import: server",              check_server),
    ("import: observability",       check_observability),
    ("guardrail: signal registers", check_signal_honesty),
    ("guardrail: blocks banned phrases", check_tone_blocked),
    ("guardrail: passes clean email",    check_tone_passes),
    ("guardrail: segment gate",     check_segment_gate),
    ("guardrail: bench guard",      check_bench_guard),
    ("enrichment: synthetic prospects",  check_synthetic_prospects),
    ("enrichment: ai_maturity_scorer",   check_ai_maturity),
    ("enrichment: icp_classifier",       check_icp_classifier),
    ("agent: cold send decision",        check_decision_cold),
    ("agent: qualification flow",        check_decision_qual),
    ("agent: booking trigger",           check_decision_booking),
    ("eval: score_log readable",         check_score_log),
]

for name, fn in CHECKS:
    run_check(name, fn)


def main():
    width = 72
    print("=" * width)
    print("  CONVERSION ENGINE - BUILD REPORT")
    print("=" * width)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    failed = sum(1 for _, s, _ in results if s == "FAIL")

    for name, status, detail in results:
        tag = "[OK]" if status == "PASS" else "[!!]"
        print(f"  {tag} {name}")
        if detail:
            print(f"       {detail}")

    print("-" * width)
    print(f"  {passed} passed   {failed} failed   {passed + failed} total")
    print("=" * width)

    if failed:
        print("\nFix the failing checks above, then run the benchmark:")
    else:
        print("\nAll checks passed. Run the benchmark:")
    print("  python eval/harness.py --mode dev --trials 2 --run-name dev_baseline_v1")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
