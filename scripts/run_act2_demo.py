#!/usr/bin/env python3
"""
Act II Demo Script — End-to-End Conversion Engine

Runs the full pipeline for all 8 synthetic prospects:
  1. Build Prospect + HiringSignalBrief + CompetitorGapBrief from synthetic data
  2. Save briefs to disk
  3. Run agent cold-email send for all 8 (latency data)
  4. For syn001 (Verdant Labs): simulate full thread
       cold email -> reply -> qualification (4 q's) -> booking link

Output:
  data/act2_latency.json   — interaction timings for p50/p95 calculation
  data/act2_thread.json    — full thread for syn001

Usage:
    python scripts/run_act2_demo.py
"""

from __future__ import annotations

import io
import json
import logging
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows consoles so arrow characters don't crash
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("act2_demo")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

# ── Imports ────────────────────────────────────────────────────────────────────
from enrichment.schemas.prospect import Prospect, FundingRound, LeadershipEvent, LayoffEvent, TechEntry
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief, SignalItem
from enrichment.schemas.competitor_gap_brief import CompetitorGapBrief
from enrichment.ai_maturity_scorer import score_ai_maturity
from enrichment.icp_classifier import classify_segment
from enrichment.competitor_finder import find_peers, build_competitor_gap_brief
from enrichment.evidence_graph import log_decision
from agent.agent import run as agent_run
from agent.state import ConversationState
from channels.channel_router import ChannelRouter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIEFS_DIR = PROJECT_ROOT / "data" / "processed" / "hiring_signal_briefs"
COMP_DIR = PROJECT_ROOT / "data" / "processed" / "competitor_gap_briefs"
BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
COMP_DIR.mkdir(parents=True, exist_ok=True)


# ── Signal builder helpers (mirrors pipeline.py logic) ────────────────────────

def _funding_sig(prospect: Prospect) -> SignalItem | None:
    if not prospect.funding_rounds:
        return None
    latest = prospect.funding_rounds[0]
    age_days: int | None = None
    if latest.announced_on:
        try:
            from datetime import datetime as dt
            d = dt.strptime(latest.announced_on, "%Y-%m-%d").date()
            age_days = (datetime.now(timezone.utc).date() - d).days
        except ValueError:
            pass
    return SignalItem(
        signal_type="funding",
        value=latest.title or "Funding round",
        evidence=f"Round: {latest.title or 'unknown'}, announced {latest.announced_on or 'unknown'}",
        confidence="high" if latest.title else "medium",
        data_age_days=age_days,
        language_register="assert",
    )


def _leadership_sig(prospect: Prospect) -> SignalItem | None:
    if not prospect.leadership_hires:
        return None
    hire = prospect.leadership_hires[0]
    age_days: int | None = None
    if hire.key_event_date:
        try:
            from datetime import datetime as dt
            d = dt.strptime(hire.key_event_date[:10], "%Y-%m-%d").date()
            age_days = (datetime.now(timezone.utc).date() - d).days
        except ValueError:
            pass
    return SignalItem(
        signal_type="leadership_change",
        value=hire.label,
        evidence=f"Leadership hire: {hire.label} on {hire.key_event_date or 'unknown'}",
        confidence="high" if age_days is not None and age_days <= 90 else "medium",
        data_age_days=age_days,
        language_register="ask",
    )


def _layoff_sig(prospect: Prospect) -> SignalItem | None:
    if not prospect.layoff_events:
        return None
    event = prospect.layoff_events[0]
    age_days: int | None = None
    if event.key_event_date:
        try:
            from datetime import datetime as dt
            d = dt.strptime(event.key_event_date[:10], "%Y-%m-%d").date()
            age_days = (datetime.now(timezone.utc).date() - d).days
        except ValueError:
            pass
    return SignalItem(
        signal_type="layoff",
        value=event.label,
        evidence=f"Layoff: {event.label} on {event.key_event_date or 'unknown'}",
        confidence="high",
        data_age_days=age_days,
        language_register="hedge",
    )


def _tech_sig(prospect: Prospect) -> SignalItem | None:
    if not prospect.tech_stack:
        return None
    names = [t.name for t in prospect.tech_stack[:5]]
    return SignalItem(
        signal_type="tech_stack",
        value=", ".join(names),
        evidence=f"Detected technologies: {', '.join(names)}",
        confidence="medium",
        data_age_days=None,
        language_register="ask",
    )


def _ai_maturity_sig(score: int, confidence: str, justification: list[str]) -> SignalItem:
    label = {0: "none", 1: "early", 2: "developing", 3: "advanced"}.get(score, "unknown")
    return SignalItem(
        signal_type="ai_maturity",
        value=label,
        evidence="; ".join(justification) if justification else "No AI signals detected",
        confidence=confidence,
        data_age_days=None,
        language_register="assert" if score >= 2 else "ask",
    )


# ── Build briefs from synthetic prospect data ──────────────────────────────────

def build_briefs(p: Prospect) -> tuple[HiringSignalBrief, CompetitorGapBrief]:
    now_iso = datetime.now(timezone.utc).isoformat()

    # Score AI maturity from the synthetic data fields
    ai_score, ai_confidence, ai_justification = score_ai_maturity(
        tech_stack=p.tech_stack,
        leadership_hires=p.leadership_hires,
        industries=p.industries,
        description=p.description or "",
        full_description="",
        technology_highlights_raw="",
    )
    p.ai_maturity_score = ai_score
    p.ai_maturity_confidence = ai_confidence

    # Build signals
    funding_s = _funding_sig(p)
    leadership_s = _leadership_sig(p)
    layoff_s = _layoff_sig(p)
    tech_s = _tech_sig(p)
    ai_s = _ai_maturity_sig(ai_score, ai_confidence, ai_justification)

    partial_brief = HiringSignalBrief(
        prospect_id=p.prospect_id,
        company_name=p.company_name,
        generated_at=now_iso,
        funding=funding_s,
        leadership_change=leadership_s,
        layoff=layoff_s,
        tech_stack=tech_s,
        ai_maturity=ai_s,
    )

    # Classify ICP segment
    segment, seg_confidence = classify_segment(p, partial_brief)
    p.icp_segment = segment if segment != 0 else None
    p.icp_confidence = seg_confidence if seg_confidence != "abstain" else None

    pitch_language = "high_readiness" if ai_score >= 2 else "low_readiness"
    active_signals = partial_brief.all_signals()
    summary_parts = [f"{s.signal_type}: {s.value}" for s in active_signals]
    brief_summary = (
        f"{p.company_name} — " + "; ".join(summary_parts)
        if summary_parts else p.company_name
    )

    brief = HiringSignalBrief(
        prospect_id=p.prospect_id,
        company_name=p.company_name,
        generated_at=now_iso,
        funding=funding_s,
        leadership_change=leadership_s,
        layoff=layoff_s,
        tech_stack=tech_s,
        ai_maturity=ai_s,
        recommended_segment=segment if segment != 0 else None,
        segment_confidence=seg_confidence,
        pitch_language_ai=pitch_language,
        brief_summary=brief_summary,
    )

    # Competitor gap brief
    peers_raw = find_peers(p)
    comp_brief = build_competitor_gap_brief(p, brief, peers_raw)

    # Save to disk
    (BRIEFS_DIR / f"{p.prospect_id}.json").write_text(
        brief.model_dump_json(indent=2), encoding="utf-8"
    )
    (COMP_DIR / f"{p.prospect_id}.json").write_text(
        comp_brief.model_dump_json(indent=2), encoding="utf-8"
    )

    return brief, comp_brief


# ── Load all synthetic prospects ───────────────────────────────────────────────

def load_synthetic_prospects() -> list[Prospect]:
    raw = json.loads(
        (PROJECT_ROOT / "data" / "synthetic" / "synthetic_prospects.json").read_text(encoding="utf-8")
    )
    prospects = []
    for d in raw:
        d.setdefault("last_enriched_at", datetime.now(timezone.utc).isoformat())
        p = Prospect.model_validate(d)
        prospects.append(p)
    return prospects


# ── Simulate a conversation turn ───────────────────────────────────────────────

def agent_tick(
    prospect: Prospect,
    brief: HiringSignalBrief,
    comp_brief: CompetitorGapBrief,
    state: ConversationState,
    router: ChannelRouter,
    inbound_reply: str | None = None,
    inbound_channel: str = "email",
) -> tuple[dict, float]:
    t0 = time.perf_counter()
    result = agent_run(
        prospect=prospect,
        brief=brief,
        comp_brief=comp_brief,
        state=state,
        router=router,
        inbound_reply=inbound_reply,
        inbound_channel=inbound_channel,
    )
    elapsed = round(time.perf_counter() - t0, 3)
    return result, elapsed


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n{'='*65}")
    print("  ACT II DEMO — Conversion Engine End-to-End")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*65}\n")

    prospects = load_synthetic_prospects()
    router = ChannelRouter()
    all_latencies: list[float] = []
    interaction_log: list[dict] = []

    # ── Phase 1: Enrich all 8 prospects + send cold email ─────────────────────
    print("Phase 1 — Enrichment + cold email send for all 8 prospects")
    print("-" * 65)

    briefs_map: dict[str, tuple[Prospect, HiringSignalBrief, CompetitorGapBrief]] = {}

    for prospect in prospects:
        print(f"\n  [{prospect.prospect_id}] {prospect.company_name}")
        t_enrich_start = time.perf_counter()
        brief, comp_brief = build_briefs(prospect)
        enrich_elapsed = round(time.perf_counter() - t_enrich_start, 3)
        print(
            f"         enriched in {enrich_elapsed:.1f}s  "
            f"| segment={brief.recommended_segment}({brief.segment_confidence})  "
            f"| ai_maturity={brief.ai_maturity.value if brief.ai_maturity else 'n/a'}"
        )

        state = ConversationState(
            prospect_id=prospect.prospect_id,
            company_name=prospect.company_name,
        )

        result, tick_elapsed = agent_tick(prospect, brief, comp_brief, state, router)
        all_latencies.append(tick_elapsed)

        status = "SENT" if result.get("sent") else f"BLOCKED({result.get('error', '?')})"
        print(
            f"         cold email -> {status}  "
            f"({tick_elapsed:.2f}s)  action={result.get('action')}"
        )

        interaction_log.append({
            "prospect_id": prospect.prospect_id,
            "company_name": prospect.company_name,
            "turn": 0,
            "action": result.get("action"),
            "sent": result.get("sent"),
            "latency_s": tick_elapsed,
            "enrich_s": enrich_elapsed,
        })
        briefs_map[prospect.prospect_id] = (prospect, brief, comp_brief)

    # ── Phase 2: Full thread simulation for syn001 (Verdant Labs) ─────────────
    print(f"\n{'='*65}")
    print("Phase 2 — Full conversation thread: syn001 (Verdant Labs)")
    print(f"{'='*65}")

    p, brief, comp_brief = briefs_map["syn001"]
    state = ConversationState(
        prospect_id="syn001",
        company_name="Verdant Labs",
    )
    thread_events: list[dict] = []

    # Turn 0 already done in phase 1 — re-run fresh state for the full thread log
    print("\n  Turn 1: Cold email ->")
    result, elapsed = agent_tick(p, brief, comp_brief, state, router)
    all_latencies.append(elapsed)
    thread_events.append({"turn": 1, "direction": "out", **result, "latency_s": elapsed})
    print(f"    subject: {result.get('subject', '')[:80]}")
    print(f"    sent: {result.get('sent')}  action: {result.get('action')}  ({elapsed:.2f}s)")

    # Simulate a positive reply
    reply_1 = (
        "Thanks for reaching out. Yes, we raised our Series A in January and we're "
        "struggling to hire fast enough — our current recruiter pipeline is 3 months "
        "behind demand. Happy to chat."
    )
    print(f"\n  Simulated reply from Priya Sharma:")
    print(f"    '{reply_1[:90]}...'")

    print("\n  Turn 2: Qualification question 1 ->")
    result, elapsed = agent_tick(p, brief, comp_brief, state, router, inbound_reply=reply_1)
    all_latencies.append(elapsed)
    thread_events.append({"turn": 2, "direction": "out", **result, "latency_s": elapsed})
    print(f"    subject: {result.get('subject', '')[:80]}")
    print(f"    sent: {result.get('sent')}  action: {result.get('action')}  ({elapsed:.2f}s)")

    # Simulate reply with Q1 answer
    reply_2 = (
        "Our top priority right now is shipping our ML-based demand forecasting feature. "
        "We have two engineers on it but need two more with Python / sklearn experience."
    )
    print(f"\n  Simulated reply: Q1 answered -> '{reply_2[:70]}...'")

    print("\n  Turn 3: Qualification question 2 ->")
    result, elapsed = agent_tick(p, brief, comp_brief, state, router, inbound_reply=reply_2)
    all_latencies.append(elapsed)
    thread_events.append({"turn": 3, "direction": "out", **result, "latency_s": elapsed})
    print(f"    sent: {result.get('sent')}  action: {result.get('action')}  ({elapsed:.2f}s)")

    # Simulate reply with Q2 + Q3 answers
    reply_3 = (
        "We're targeting a Q3 launch. The main blocker is recruiting — we interviewed "
        "12 candidates last month and only extended one offer. Our Series A runway "
        "gives us about 18 months."
    )
    print(f"\n  Simulated reply: Q2+Q3 answered -> '{reply_3[:70]}...'")

    print("\n  Turn 4: Qualification question 4 ->")
    result, elapsed = agent_tick(p, brief, comp_brief, state, router, inbound_reply=reply_3)
    all_latencies.append(elapsed)
    thread_events.append({"turn": 4, "direction": "out", **result, "latency_s": elapsed})
    print(f"    sent: {result.get('sent')}  action: {result.get('action')}  ({elapsed:.2f}s)")

    # Simulate final reply with stakeholder info
    reply_4 = (
        "It's just me and our CEO on this decision. We'd need to align on scope "
        "and cost structure — let's get on a call."
    )
    print(f"\n  Simulated reply: Q4 answered + ready to book -> '{reply_4[:70]}...'")

    print("\n  Turn 5: Booking link ->")
    result, elapsed = agent_tick(p, brief, comp_brief, state, router, inbound_reply=reply_4)
    all_latencies.append(elapsed)
    thread_events.append({"turn": 5, "direction": "out", **result, "latency_s": elapsed})
    print(f"    subject: {result.get('subject', '')[:80]}")
    print(f"    sent: {result.get('sent')}  action: {result.get('action')}  ({elapsed:.2f}s)")
    if result.get("body"):
        print(f"\n    Email body preview:")
        for line in result["body"].splitlines()[:8]:
            print(f"      {line}")

    # ── SMS turn: prospect says they prefer SMS for scheduling ────────────────
    print("\n  SMS turn: prospect sends SMS 'what times work?'")
    state.stage = "warm_prefers_sms"
    sms_reply = "What times work for the call? I prefer SMS for scheduling."
    result_sms, elapsed_sms = agent_tick(
        p, brief, comp_brief, state, router,
        inbound_reply=sms_reply, inbound_channel="sms",
    )
    all_latencies.append(elapsed_sms)
    thread_events.append({"turn": 6, "direction": "out", "channel": "sms", **result_sms, "latency_s": elapsed_sms})
    print(f"    sent: {result_sms.get('sent')}  action: {result_sms.get('action')}  ({elapsed_sms:.2f}s)")

    # ── Latency stats ──────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("Latency Summary")
    print(f"{'='*65}")
    all_latencies_sorted = sorted(all_latencies)
    n = len(all_latencies_sorted)
    p50 = statistics.median(all_latencies_sorted)
    p95_idx = min(int(n * 0.95), n - 1)
    p95 = all_latencies_sorted[p95_idx]
    p_min = min(all_latencies_sorted)
    p_max = max(all_latencies_sorted)
    print(f"  Total interactions : {n}")
    print(f"  Min latency        : {p_min:.2f}s")
    print(f"  p50 latency        : {p50:.2f}s")
    print(f"  p95 latency        : {p95:.2f}s")
    print(f"  Max latency        : {p_max:.2f}s")

    # ── Save outputs ───────────────────────────────────────────────────────────
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(exist_ok=True)

    latency_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_interactions": n,
        "latency_p50_s": round(p50, 3),
        "latency_p95_s": round(p95, 3),
        "latency_min_s": round(p_min, 3),
        "latency_max_s": round(p_max, 3),
        "all_latencies_s": all_latencies,
        "interactions": interaction_log,
    }
    (data_dir / "act2_latency.json").write_text(
        json.dumps(latency_output, indent=2), encoding="utf-8"
    )

    thread_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prospect_id": "syn001",
        "company_name": "Verdant Labs",
        "contact_email": p.contact_email,
        "icp_segment": state.segment,
        "final_stage": state.stage,
        "events": thread_events,
    }
    (data_dir / "act2_thread.json").write_text(
        json.dumps(thread_output, indent=2, default=str), encoding="utf-8"
    )

    print(f"\n  Saved: data/act2_latency.json")
    print(f"  Saved: data/act2_thread.json")
    print(f"\n{'='*65}")
    print("  Act II demo complete.")
    print(f"{'='*65}\n")
    print("  Next steps:")
    print("  1. Open HubSpot -> check contact 'Priya Sharma' (Verdant Labs)")
    print("     Screenshot the contact record (all fields populated)")
    print("  2. Open Cal.com (localhost:3000) -> make a test booking")
    print("     Screenshot the booking confirmation")
    print("  3. Check derejederib@gmail.com for the actual emails sent")
    print()


if __name__ == "__main__":
    main()
