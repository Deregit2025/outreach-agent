"""
agent.py — Main SDR agent orchestrator.

Ties together enrichment, decision engine, LLM calls, guardrails,
and channel routing into a single run() call per prospect thread.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from agent.state import ConversationState
from agent.decision_engine import Action, decide, next_qualification_question, absorb_reply
from agent.bench_guard import check_draft
from agent.guardrails.tone_checker import enforce as tone_enforce
from agent.guardrails.segment_gate import validate_segment_pitch
from agent.guardrails.signal_honesty import get_register, apply_register
from channels.channel_router import ChannelRouter
from config.settings import settings
from enrichment.schemas.prospect import Prospect
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief, SignalItem
from enrichment.schemas.competitor_gap_brief import CompetitorGapBrief

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_SYSTEM_PROMPT = (_PROMPTS_DIR / "system_prompt.txt").read_text(encoding="utf-8")

_jinja_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def _llm_call(
    messages: list[dict],
    model: str | None = None,
    eval_mode: bool = False,
) -> str:
    """Call the LLM via LiteLLM. Uses OpenRouter for both dev and eval tiers."""
    try:
        import litellm  # type: ignore
        import os

        # Choose model tier: explicit override → eval tier → dev tier
        if model:
            resolved_model = model
        elif eval_mode:
            resolved_model = f"openrouter/{settings.llm_model_eval}"
        else:
            resolved_model = f"openrouter/{settings.llm_model_dev}"

        # Inject OpenRouter key so LiteLLM can authenticate
        api_key = settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")

        response = litellm.completion(
            model=resolved_model,
            messages=messages,
            temperature=0.3,
            max_tokens=512,
            api_key=api_key,
            api_base="https://openrouter.ai/api/v1",
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("LLM call failed: %s — using template fallback", exc)
        return ""


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------

def _build_signal_opening(brief: HiringSignalBrief, segment: int) -> tuple[str, list[dict]]:
    """
    Build the signal_opening sentence for the email template and the
    evaluated signals list used by guardrails.

    Returns (opening_text, signals_list).
    """
    evaluated: list[dict] = []
    primary_signal: SignalItem | None = None

    # Pick the most segment-relevant signal
    if segment == 1 and brief.funding:
        primary_signal = brief.funding
    elif segment == 2 and brief.layoff:
        primary_signal = brief.layoff
    elif segment == 3 and brief.leadership_change:
        primary_signal = brief.leadership_change
    elif segment == 4 and brief.ai_maturity:
        primary_signal = brief.ai_maturity

    # Fallback: pick any non-None signal
    if primary_signal is None:
        for sig in brief.all_signals():
            primary_signal = sig
            break

    if primary_signal is None:
        return "", []

    stype = primary_signal.signal_type
    age = primary_signal.data_age_days or 9999

    # Compute register from signal_honesty
    if stype == "funding":
        amount = 0.0
        try:
            # evidence may contain amount info; best-effort parse
            import re
            m = re.search(r"\$?([\d,]+(?:\.\d+)?)[MmKk]?", primary_signal.evidence)
            if m:
                raw = m.group(1).replace(",", "")
                amount = float(raw)
                if "M" in primary_signal.evidence or "m" in primary_signal.evidence:
                    amount *= 1_000_000
        except Exception:
            pass
        register = get_register("funding", amount_usd=amount, age_days=age)
    elif stype == "layoff":
        register = get_register("layoff", age_days=age)
    elif stype == "leadership_change":
        register = get_register("leadership", age_days=age)
    elif stype == "ai_maturity":
        score = 0
        try:
            score_map = {"none": 0, "early": 1, "developing": 2, "advanced": 3}
            score = score_map.get(primary_signal.value.lower(), 0)
        except Exception:
            pass
        register = get_register(
            "ai_maturity",
            score=score,
            confidence=primary_signal.confidence,
        )
    else:
        register = primary_signal.language_register or "ask"

    evaluated.append({"type": stype, "register": register})

    # Compose opening text per register
    value = primary_signal.value
    company = brief.company_name

    if stype == "funding":
        opening = apply_register(
            register,
            assert_text=f"{company} closed a funding round ({value}) recently — the clock is running on putting that capital to work.",
            hedge_text=f"It looks like {company} may have recently closed a funding round ({value}).",
            ask_text=f"Are you in an active growth phase following a recent fundraise?",
        )
    elif stype == "layoff":
        opening = apply_register(
            register,
            assert_text=f"{company} went through a restructuring recently ({value}) — delivery gaps often follow.",
            hedge_text=f"It looks like {company} may have gone through some recent workforce changes.",
            ask_text=f"Has your team structure changed recently in ways that affect delivery capacity?",
        )
    elif stype == "leadership_change":
        opening = apply_register(
            register,
            assert_text=f"Congrats on the new engineering leadership at {company} — new leaders typically need immediate capacity before the org is fully built out.",
            hedge_text=f"It looks like {company} may have recently brought on new engineering leadership.",
            ask_text=f"Has your engineering leadership structure changed recently?",
        )
    elif stype == "ai_maturity":
        opening = apply_register(
            register,
            assert_text=f"{company} has an established AI/ML practice — we noticed your investment in this space.",
            hedge_text=f"It looks like {company} may be building out AI/ML capabilities.",
            ask_text=f"Are you currently investing in AI/ML capabilities or exploring where they might fit?",
        )
    else:
        opening = f"I came across {company} and noticed some signals that seemed relevant."

    return opening, evaluated


def _build_brief_context(
    prospect: Prospect,
    brief: HiringSignalBrief,
    comp_brief: CompetitorGapBrief,
    state: ConversationState,
) -> str:
    """Build a compact JSON context block for the LLM prompt."""
    ctx = {
        "company": prospect.company_name,
        "segment": state.segment,
        "signals": {
            "funding": brief.funding.model_dump() if brief.funding else None,
            "layoff": brief.layoff.model_dump() if brief.layoff else None,
            "leadership_change": brief.leadership_change.model_dump() if brief.leadership_change else None,
            "ai_maturity": brief.ai_maturity.model_dump() if brief.ai_maturity else None,
        },
        "competitor_gap_hook": comp_brief.gap_hook,
        "qualification_progress": {
            "q1": state.qualification.q1_initiative,
            "q2": state.qualification.q2_timeline,
            "q3": state.qualification.q3_blocker,
            "q4": state.qualification.q4_stakeholders,
        },
        "stage": state.stage,
        "email_touches": state.email_touches,
    }
    return json.dumps(ctx, default=str, indent=2)


# ---------------------------------------------------------------------------
# Draft generators
# ---------------------------------------------------------------------------

def _generate_cold_email(
    prospect: Prospect,
    brief: HiringSignalBrief,
    comp_brief: CompetitorGapBrief,
    state: ConversationState,
) -> tuple[str, str, list[dict]]:
    """
    Generate cold email subject + body using the Jinja2 template.
    Returns (subject, body, evaluated_signals).
    """
    signal_opening, evaluated = _build_signal_opening(brief, state.segment)

    # Ask LLM for bridge and qualification_ask
    ctx = _build_brief_context(prospect, brief, comp_brief, state)
    llm_resp = _llm_call([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"PROSPECT BRIEF:\n{ctx}\n\n"
            "Write ONLY a JSON object with two keys:\n"
            '  "bridge": 1-2 sentences connecting the signal to a common pattern for this segment\n'
            '  "qualification_ask": one low-commitment qualifying question (no question mark stacking)\n'
            "Keep the bridge under 30 words. Keep the ask under 20 words."
        )},
    ])

    bridge = ""
    qualification_ask = "Would it make sense to have a quick conversation about your current engineering priorities?"
    try:
        import re
        m = re.search(r'\{.*\}', llm_resp, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            bridge = parsed.get("bridge", "")
            qualification_ask = parsed.get("qualification_ask", qualification_ask)
    except Exception:
        pass

    tmpl = _jinja_env.get_template("outreach_email.jinja2")
    rendered = tmpl.render(
        company_name=prospect.company_name,
        contact_first_name=prospect.contact_first_name or "there",
        segment=state.segment,
        signal_opening=signal_opening,
        bridge=bridge,
        case_study_line=None,
        qualification_ask=qualification_ask,
        sender_name="The Tenacious Team",
    )

    lines = rendered.strip().splitlines()
    subject = ""
    body_lines: list[str] = []
    for line in lines:
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    return subject, body, evaluated


def _generate_follow_up(
    prospect: Prospect,
    brief: HiringSignalBrief,
    state: ConversationState,
) -> tuple[str, str, list[dict]]:
    _, evaluated = _build_signal_opening(brief, state.segment)
    subject = f"Re: Engineering capacity for {prospect.company_name}"
    body = (
        f"{prospect.contact_first_name or 'Hi'},\n\n"
        "Wanted to follow up on my note from last week — different angle.\n\n"
        "Most engineering leaders I talk to are balancing delivery speed against "
        "permanent headcount risk. If that tension is live for you right now, "
        "it might be worth 20 minutes to see if there's a fit.\n\n"
        "Worth a quick chat?"
    )
    return subject, body, evaluated


def _generate_qual_message(
    prospect: Prospect,
    state: ConversationState,
    q_num: int,
    q_text: str,
) -> tuple[str, str, list[dict]]:
    subject = f"Re: {prospect.company_name}"
    body = (
        f"{prospect.contact_first_name or 'Thanks for the reply'},\n\n"
        f"{q_text}"
    )
    return subject, body, []


def _generate_booking_message(
    prospect: Prospect,
    state: ConversationState,
) -> tuple[str, str, list[dict]]:
    booking_url = settings.calcom_booking_url or "https://cal.com/tenacious/discovery"
    subject = f"Discovery call — {prospect.company_name}"
    body = (
        f"{prospect.contact_first_name or 'Hi'},\n\n"
        "Based on what you've shared, I think there's a real fit worth exploring "
        "on a proper call with our delivery team.\n\n"
        f"Book a time that works for you: {booking_url}\n\n"
        "The call is 30 minutes. No deck. Just an honest conversation about whether "
        "the engagement model makes sense for your situation."
    )
    return subject, body, []


# ---------------------------------------------------------------------------
# Main run loop
# ---------------------------------------------------------------------------

def run(
    prospect: Prospect,
    brief: HiringSignalBrief,
    comp_brief: CompetitorGapBrief,
    state: ConversationState,
    router: ChannelRouter | None = None,
    inbound_reply: str | None = None,
    inbound_channel: str = "email",
) -> dict[str, Any]:
    """
    Execute one tick of the SDR agent for a given prospect thread.

    Parameters
    ----------
    prospect      : enriched Prospect record
    brief         : HiringSignalBrief from enrichment pipeline
    comp_brief    : CompetitorGapBrief
    state         : mutable ConversationState (mutated in-place)
    router        : ChannelRouter instance (created if None)
    inbound_reply : text body of a reply from the prospect (if any)
    inbound_channel: channel the reply arrived on

    Returns a result dict with keys:
        action, sent, subject, body, tone_report, bench_violations, error
    """
    if router is None:
        router = ChannelRouter()

    t0 = time.time()

    # Absorb any inbound reply into state
    if inbound_reply:
        state.record_inbound(inbound_channel, inbound_reply)
        absorb_reply(state, inbound_reply)
        if state.stage == "new":
            state.transition_to("replied_by_email")

    # Sync segment from brief if not yet set
    if state.segment == 0 and brief.recommended_segment:
        state.segment = brief.recommended_segment
        state.segment_confidence = brief.segment_confidence

    # Validate segment pitch
    seg_ok, seg_reason = validate_segment_pitch(
        state.segment,
        {
            "ai_maturity_score": prospect.ai_maturity_score or 0,
            "layoff_age_days": (
                brief.layoff.data_age_days if brief.layoff else None
            ),
            "funding_age_days": (
                brief.funding.data_age_days if brief.funding else None
            ),
        }
    )
    if not seg_ok:
        state.escalated = True
        state.escalation_reason = seg_reason
        return {
            "action": "ESCALATE",
            "sent": False,
            "subject": "",
            "body": "",
            "tone_report": {},
            "bench_violations": [],
            "error": seg_reason,
        }

    action = decide(state, brief)

    if action == Action.SKIP:
        return {"action": "SKIP", "sent": False, "subject": "", "body": "",
                "tone_report": {}, "bench_violations": [], "error": None}

    if action == Action.PAUSE:
        state.transition_to("paused")
        _existing = router.crm.search_contact(prospect.contact_email or "")
        if _existing:
            router.crm.update_deal_stage(
                contact_id=_existing["contact_id"],
                stage="closedlost",
            )
        return {"action": "PAUSE", "sent": False, "subject": "", "body": "",
                "tone_report": {}, "bench_violations": [], "error": None}

    if action == Action.ESCALATE:
        return {"action": "ESCALATE", "sent": False, "subject": "", "body": "",
                "tone_report": {}, "bench_violations": [], "error": state.escalation_reason}

    # Generate draft
    subject = body = ""
    evaluated_signals: list[dict] = []

    if action == Action.SEND_COLD_EMAIL:
        subject, body, evaluated_signals = _generate_cold_email(
            prospect, brief, comp_brief, state
        )
    elif action == Action.SEND_FOLLOW_UP:
        subject, body, evaluated_signals = _generate_follow_up(
            prospect, brief, state
        )
        state.follow_up_sent = True
    elif action == Action.ASK_NEXT_QUAL_Q:
        q_num, q_text = next_qualification_question(state)
        subject, body, evaluated_signals = _generate_qual_message(
            prospect, state, q_num, q_text
        )
    elif action == Action.SEND_BOOKING_LINK:
        subject, body, evaluated_signals = _generate_booking_message(
            prospect, state
        )
        state.transition_to("qualified")

    full_text = f"{subject}\n\n{body}"

    # Guardrail: tone checker
    tone_passed, tone_report = tone_enforce(full_text, evaluated_signals)

    # Guardrail: bench guard
    bench_passed, bench_violations = check_draft(full_text)

    if not tone_passed or not bench_passed:
        all_issues = tone_report.get("prohibited_found", []) + bench_violations
        logger.warning(
            "Guardrail block for %s — tone_passed=%s bench_passed=%s issues=%s",
            prospect.company_name, tone_passed, bench_passed, all_issues,
        )
        state.escalated = True
        state.escalation_reason = "; ".join(all_issues)
        return {
            "action": action.name,
            "sent": False,
            "subject": subject,
            "body": body,
            "tone_report": tone_report,
            "bench_violations": bench_violations,
            "error": "Guardrail block — message not sent",
        }

    # Send via channel router
    prospect_dict = {
        "email": prospect.contact_email or "",
        "phone": prospect.contact_phone or "",
        "name": f"{prospect.contact_first_name or ''} {prospect.contact_last_name or ''}".strip(),
    }
    send_result = router.send_message(
        prospect=prospect_dict,
        message=body,
        subject=subject,
        lead_stage=state.stage,
    )

    _HS_STAGE_MAP: dict[str, str] = {
        "new": "NEW",
        "replied_by_email": "CONNECTED",
        "warm_prefers_sms": "IN_PROGRESS",
        "qualified": "OPEN_DEAL",
        "booked": "OPEN_DEAL",
        "paused": "BAD_TIMING",
        "closed": "UNQUALIFIED",
    }

    # Log to CRM
    try:
        contact_email = prospect.contact_email or ""
        crm_result = router.crm.upsert_contact(
            email=contact_email,
            properties={
                "firstname": prospect.contact_first_name or "",
                "lastname": prospect.contact_last_name or "",
                "company": prospect.company_name,
                "jobtitle": prospect.contact_title or "",
                "phone": prospect.contact_phone or "",
                "hs_lead_status": _HS_STAGE_MAP.get(state.stage, "NEW"),
            },
        )
        contact_id = crm_result.get("contact_id", "")
        if contact_id:
            router.crm.log_email_activity(
                contact_id=contact_id,
                subject=subject,
                body=body,
                direction="OUTBOUND",
            )
    except Exception as exc:
        logger.warning("CRM update failed for %s: %s", prospect.company_name, exc)

    # Update state
    state.record_outbound(
        channel="email",
        body=body,
        subject=subject,
        tone_score=tone_report.get("score"),
        send_result=send_result,
    )

    if action == Action.SEND_BOOKING_LINK:
        state.transition_to("qualified")

    duration = round(time.time() - t0, 3)
    logger.info(
        "Agent tick complete | company=%s | action=%s | sent=%s | duration=%.3fs",
        prospect.company_name, action.name, send_result.get("status"), duration,
    )

    return {
        "action": action.name,
        "sent": send_result.get("status") == "sent",
        "subject": subject,
        "body": body,
        "tone_report": tone_report,
        "bench_violations": bench_violations,
        "error": send_result.get("error"),
        "duration_s": duration,
    }
