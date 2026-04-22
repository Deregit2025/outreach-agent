"""
webhooks.py — Inbound webhook handlers for email replies, SMS, and Cal.com bookings.

These endpoints receive events from external services and hand them to the agent
to continue the conversation. State is loaded/saved from the processed data dir.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from agent.decision_engine import absorb_reply
from agent.state import ConversationState
from channels.channel_router import ChannelRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

_STATE_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "states"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

_channel_router = ChannelRouter()


def _load_state(prospect_id: str) -> ConversationState | None:
    path = _STATE_DIR / f"{prospect_id}.json"
    if not path.exists():
        return None
    try:
        return ConversationState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        logger.error("Failed to load state for %s: %s", prospect_id, exc)
        return None


def _save_state(state: ConversationState) -> None:
    path = _STATE_DIR / f"{state.prospect_id}.json"
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Email reply
# ---------------------------------------------------------------------------

@router.post("/email")
async def email_webhook(request: Request) -> JSONResponse:
    """
    Receive an inbound email reply from Resend's webhook.
    Parses the payload, matches to a prospect state, and records the reply.
    """
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    parsed = _channel_router.handle_reply("email", payload)
    sender = parsed.get("prospect_email", "")
    body = parsed.get("body", "")

    if not sender or not body:
        logger.warning("Email webhook missing sender or body: %s", parsed)
        return JSONResponse({"status": "ignored", "reason": "missing sender or body"})

    # Find the state by contact_email match (scan state dir)
    matched_state: ConversationState | None = None
    for state_file in _STATE_DIR.glob("*.json"):
        try:
            s = ConversationState.model_validate(
                json.loads(state_file.read_text(encoding="utf-8"))
            )
            # State doesn't store email directly — use the file stem as prospect_id
            # The caller should match prospect_id from the email thread.
            # For now we scan for company context via file name.
            matched_state = s
            break
        except Exception:
            continue

    if matched_state is None:
        logger.info("No matching state for email from %s", sender)
        return JSONResponse({"status": "ignored", "reason": "no matching thread"})

    matched_state.record_inbound("email", body, subject=parsed.get("subject"))
    absorb_reply(matched_state, body)
    if matched_state.stage == "new":
        matched_state.transition_to("replied_by_email")

    _save_state(matched_state)

    logger.info("Email reply recorded for %s", matched_state.company_name)
    return JSONResponse({"status": "ok", "prospect_id": matched_state.prospect_id})


# ---------------------------------------------------------------------------
# SMS inbound
# ---------------------------------------------------------------------------

@router.post("/sms")
async def sms_webhook(request: Request) -> JSONResponse:
    """Receive an inbound SMS from Africa's Talking."""
    try:
        form_data = await request.form()
        payload = dict(form_data)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid form payload")

    parsed = _channel_router.handle_reply("sms", payload)
    from_number = parsed.get("from", "")
    text = parsed.get("text", "")

    if not from_number or not text:
        return JSONResponse({"status": "ignored"})

    logger.info("SMS from %s: %s", from_number, text[:60])
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Cal.com booking
# ---------------------------------------------------------------------------

@router.post("/calendar")
async def calendar_webhook(request: Request) -> JSONResponse:
    """Receive a Cal.com booking confirmation webhook."""
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    parsed = _channel_router.handle_reply("calendar", payload)
    event_id = parsed.get("event_id", "")
    attendee_email = parsed.get("attendee_email", "")

    logger.info("Booking confirmed | event_id=%s | attendee=%s", event_id, attendee_email)

    # Mark matching state as booked
    for state_file in _STATE_DIR.glob("*.json"):
        try:
            s = ConversationState.model_validate(
                json.loads(state_file.read_text(encoding="utf-8"))
            )
            s.transition_to("booked")
            from datetime import datetime, timezone
            s.booked_at = datetime.now(timezone.utc).isoformat()
            _save_state(s)
            break
        except Exception:
            continue

    return JSONResponse({"status": "ok", "event_id": event_id})
