"""
decision_engine.py — Decides the next action for a given prospect thread.

Pure deterministic logic — no LLM calls. agent.py calls decide() then acts.
"""

from __future__ import annotations

from enum import Enum, auto

from agent.state import ConversationState
from enrichment.schemas.hiring_signal_brief import HiringSignalBrief

MAX_EMAIL_TOUCHES = 2   # cold + 1 follow-up before pausing
MAX_SMS_TOUCHES   = 3


class Action(Enum):       
    SEND_COLD_EMAIL   = auto()
    SEND_FOLLOW_UP    = auto()
    ASK_NEXT_QUAL_Q   = auto()
    SEND_BOOKING_LINK = auto()
    ESCALATE          = auto()
    SKIP              = auto()   # stage suppresses outreach
    PAUSE             = auto()   # max touches, no reply


_SUPPRESS_STAGES = {"booked", "paused", "closed"}


def decide(
    state: ConversationState,
    brief: HiringSignalBrief,
    follow_up_interval_days: int = 5,
) -> Action:
    """Return the recommended next Action for this thread."""
    if state.stage in _SUPPRESS_STAGES:
        return Action.SKIP

    if state.escalated:
        return Action.ESCALATE

    if state.segment == 0 and brief.recommended_segment is None:
        return Action.ESCALATE

    if state.has_replied():
        if state.qualification.is_complete():
            return Action.SEND_BOOKING_LINK
        return Action.ASK_NEXT_QUAL_Q

    if state.email_touches == 0:
        return Action.SEND_COLD_EMAIL

    if not state.follow_up_sent and state.email_touches < MAX_EMAIL_TOUCHES:
        return Action.SEND_FOLLOW_UP

    return Action.PAUSE


def next_qualification_question(state: ConversationState) -> tuple[int, str]:
    """Return (question_number, question_text) for the next unanswered Q. (0, "") if done."""
    QUESTIONS: dict[int, str] = {
        1: (
            "What's the specific engineering initiative or project at the top of "
            "your priority list right now?"
        ),
        2: (
            "What's the timeline or milestone pressure on that initiative — is there "
            "a hard deadline or external commitment driving it?"
        ),
        3: (
            "What's currently blocking or slowing it — is it team capacity, a specific "
            "skill gap, or something in the existing stack?"
        ),
        4: (
            "Who else is typically involved when you bring in external engineering "
            "support — is this a decision you own or is there a broader group?"
        ),
    }
    q_num = state.next_unanswered_question()
    if q_num is None:
        return 0, ""
    return q_num, QUESTIONS[q_num]


def absorb_reply(state: ConversationState, reply_body: str) -> None:
    """
    Extract qualification answers from a free-text reply and update state.

    Two passes:
    1. Sentiment analysis — stores score on state, adjusts pace via next_action hint
    2. Keyword heuristics — deterministic qualification answer extraction
       (the LLM in agent.py does a more nuanced extraction on top of this)
    """
    text = reply_body.lower()
    q = state.qualification

    # ── Pass 1: Sentiment ─────────────────────────────────────────────────────
    try:
        from agent.reply_sentiment import analyze_sentiment
        from enrichment.evidence_graph import log_decision

        sentiment_result = analyze_sentiment(reply_body)
        state.reply_sentiment_score = sentiment_result["score"]
        state.reply_sentiment_label = sentiment_result["sentiment"]
        state.suggested_tone_shift = sentiment_result["suggested_tone_shift"]

        log_decision(
            prospect_id=state.prospect_id,
            decision_type="sentiment_analysis",
            inputs={"reply_length": len(reply_body), "stage": state.stage},
            logic=(
                f"Sentiment: {sentiment_result['sentiment']} "
                f"(score={sentiment_result['score']:.2f}, "
                f"confidence={sentiment_result['confidence']:.2f})"
            ),
            output={
                "sentiment": sentiment_result["sentiment"],
                "score": sentiment_result["score"],
                "tone_shift": sentiment_result["suggested_tone_shift"],
            },
            decision=f"sentiment:{sentiment_result['sentiment']} → {sentiment_result['suggested_tone_shift']}",
        )
    except Exception:
        pass  # sentiment is advisory; never block qualification extraction

    # ── Pass 2: Keyword-based qualification answer extraction ─────────────────
    if q.q1_initiative is None:
        initiative_kw = [
            "building", "launching", "migrating", "rewriting", "scaling",
            "platform", "product", "roadmap", "api", "pipeline", "service",
            "feature", "initiative", "project",
        ]
        if any(kw in text for kw in initiative_kw):
            q.q1_initiative = reply_body[:200]

    if q.q2_timeline is None:
        timeline_kw = [
            "q1", "q2", "q3", "q4", "deadline", "launch", "ship", "end of",
            "by ", "weeks", "months", "sprint", "milestone",
        ]
        if any(kw in text for kw in timeline_kw):
            q.q2_timeline = reply_body[:200]

    if q.q3_blocker is None:
        blocker_kw = [
            "shortage", "gap", "slow", "behind", "under-resourced", "bandwidth",
            "capacity", "skill", "expertise", "hire", "headcount",
        ]
        if any(kw in text for kw in blocker_kw):
            q.q3_blocker = reply_body[:200]

    if q.q4_stakeholders is None:
        stake_kw = [
            "cto", "vp", "head of", "leadership", "board", "just me",
            "my call", "team decides", "procurement",
        ]
        if any(kw in text for kw in stake_kw):
            q.q4_stakeholders = reply_body[:200]
