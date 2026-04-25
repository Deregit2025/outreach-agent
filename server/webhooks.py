"""
webhooks.py — Inbound webhook handlers for email replies, SMS, and Cal.com bookings.

Each handler:
  1. Parses the raw payload via ChannelRouter.handle_reply()
  2. Returns a structured JSON error if the payload is malformed
  3. Matches the inbound contact to a ConversationState by prospect_id
  4. Enforces channel-specific gates (warm-lead SMS gate, STOP unsubscribe)
  5. Advances the state machine via ChannelRouter.transition_state()
  6. Saves state and returns a structured result dict
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agent.decision_engine import absorb_reply
from agent.state import ConversationState
from channels.channel_router import ChannelRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhooks"])

_STATE_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "states"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

_channel_router = ChannelRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ok(data: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"status": "ok", **data})


def _error(code: int, reason: str, detail: str = "") -> JSONResponse:
    body: dict[str, Any] = {"status": "error", "reason": reason}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=code)


def _ignored(reason: str) -> JSONResponse:
    return JSONResponse({"status": "ignored", "reason": reason})


def _load_state(prospect_id: str) -> ConversationState | None:
    path = _STATE_DIR / f"{prospect_id}.json"
    if not path.exists():
        return None
    try:
        return ConversationState.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        logger.error("Failed to load state for %s: %s", prospect_id, exc)
        return None


def _find_state_by_email(email: str) -> ConversationState | None:
    """Scan state files to match a prospect by contact_email."""
    for state_file in _STATE_DIR.glob("*.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if data.get("contact_email", "").lower() == email.lower():
                return ConversationState.model_validate(data)
        except Exception:
            continue
    return None


def _find_state_by_phone(phone: str) -> ConversationState | None:
    """Scan state files to match a prospect by contact_phone."""
    normalized = phone.replace(" ", "").replace("-", "")
    for state_file in _STATE_DIR.glob("*.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            stored = data.get("contact_phone", "").replace(" ", "").replace("-", "")
            if stored and stored == normalized:
                return ConversationState.model_validate(data)
        except Exception:
            continue
    return None


def _save_state(state: ConversationState) -> None:
    path = _STATE_DIR / f"{state.prospect_id}.json"
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Email reply  (POST /webhook/email)
# ---------------------------------------------------------------------------

@router.post("/email")
async def email_webhook(request: Request) -> JSONResponse:
    """
    Receive an inbound email reply from Resend's inbound webhook.

    Expected payload (Resend inbound format):
        { "data": { "from": "prospect@co.com", "subject": "Re: ...", "text": "..." } }

    Returns:
        200 { status: ok, prospect_id, stage }     — reply recorded
        200 { status: ignored, reason }             — no matching thread or missing fields
        400 { status: error, reason, detail }       — malformed payload
        500 { status: error, reason, detail }       — state save failure
    """
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        return _error(400, "invalid_json", str(exc))

    # Parse via ChannelRouter (normalises Resend envelope differences)
    parsed = _channel_router.handle_reply("email", payload)
    sender: str = parsed.get("prospect_email", "")
    body: str = parsed.get("body", "")
    subject: str = parsed.get("subject", "")

    if not sender:
        return _ignored("missing_sender")
    if not body:
        return _ignored("empty_body")

    # Match prospect state
    state = _find_state_by_email(sender)
    if state is None:
        logger.info("No matching thread for email from %s", sender)
        return _ignored("no_matching_thread")

    # Advance state machine
    next_stage, err = _channel_router.transition_state(state.stage, "email_replied")
    if err:
        logger.warning("State transition failed for %s: %s", state.prospect_id, err)
    else:
        state.stage = next_stage

    # Record the reply and feed it to the decision engine
    state.record_inbound("email", body, subject=subject)
    absorb_reply(state, body)

    try:
        _save_state(state)
    except Exception as exc:
        logger.exception("Failed to save state for %s", state.prospect_id)
        return _error(500, "state_save_failed", str(exc))

    logger.info(
        "Email reply recorded | prospect=%s | stage=%s",
        state.prospect_id, state.stage,
    )
    return _ok({"prospect_id": state.prospect_id, "stage": state.stage})


# ---------------------------------------------------------------------------
# SMS inbound  (POST /webhook/sms)
# ---------------------------------------------------------------------------

@router.post("/sms")
async def sms_webhook(request: Request) -> JSONResponse:
    """
    Receive an inbound SMS from Africa's Talking (form-encoded POST).

    Africa's Talking fields: from, to, text, date, id, linkId

    Enforces:
      - STOP / UNSUBSCRIBE signal: marks state as closed, suppresses all future sends.
      - Warm-lead SMS gate: sms_opt_in_signal in the text triggers a
        transition_state("sms_opt_in") so the state machine advances to
        warm_prefers_sms only with explicit consent.

    Returns:
        200 { status: ok, prospect_id, stage }          — reply recorded
        200 { status: ok, action: unsubscribed }        — STOP processed
        200 { status: ignored, reason }                 — no matching thread
        400 { status: error, reason, detail }           — malformed payload
        500 { status: error, reason, detail }           — state save failure
    """
    try:
        form_data = await request.form()
        payload = dict(form_data)
    except Exception as exc:
        return _error(400, "invalid_form_payload", str(exc))

    # Parse via ChannelRouter (normalises field names; detects STOP + opt-in keywords)
    parsed = _channel_router.handle_reply("sms", payload)
    from_number: str = parsed.get("from", "")
    text: str = parsed.get("text", "")

    if not from_number:
        return _ignored("missing_from_number")
    if not text:
        return _ignored("empty_text")

    # Match prospect state by phone number
    state = _find_state_by_phone(from_number)
    if state is None:
        logger.info("No matching thread for SMS from %s", from_number)
        return _ignored("no_matching_thread")

    # ── STOP / unsubscribe gate ──────────────────────────────────────────────
    if parsed.get("unsubscribe_request"):
        next_stage, _ = _channel_router.transition_state(state.stage, "unsubscribe")
        state.stage = next_stage
        try:
            _save_state(state)
        except Exception as exc:
            return _error(500, "state_save_failed", str(exc))
        logger.warning(
            "Unsubscribe via SMS | prospect=%s | phone=%s",
            state.prospect_id, from_number,
        )
        return _ok({"action": "unsubscribed", "prospect_id": state.prospect_id})

    # ── Warm-lead SMS gate ────────────────────────────────────────────────────
    # If the prospect signals SMS preference, transition to warm_prefers_sms.
    # This is the only path that unlocks SMS as an outbound channel.
    if parsed.get("sms_opt_in_signal"):
        next_stage, err = _channel_router.transition_state(
            state.stage, "sms_opt_in", sms_opt_in=True
        )
        if err:
            logger.warning(
                "SMS opt-in transition failed | prospect=%s | err=%s",
                state.prospect_id, err,
            )
        else:
            state.stage = next_stage
            logger.info(
                "Warm-lead SMS gate opened | prospect=%s | stage=%s",
                state.prospect_id, state.stage,
            )

    # Record reply and feed to decision engine
    state.record_inbound("sms", text)
    absorb_reply(state, text)

    try:
        _save_state(state)
    except Exception as exc:
        return _error(500, "state_save_failed", str(exc))

    logger.info(
        "SMS reply recorded | prospect=%s | stage=%s", state.prospect_id, state.stage
    )
    return _ok({"prospect_id": state.prospect_id, "stage": state.stage})


# ---------------------------------------------------------------------------
# Cal.com booking  (POST /webhook/calendar)
# ---------------------------------------------------------------------------

@router.post("/calendar")
async def calendar_webhook(request: Request) -> JSONResponse:
    """
    Receive a Cal.com booking confirmation webhook.

    Cal.com wraps the booking under a "payload" key:
        { "triggerEvent": "BOOKING_CREATED", "payload": { "uid": "...", ... } }

    Returns:
        200 { status: ok, booking_id, attendee_email, stage }
        200 { status: ignored, reason }
        400 { status: error, reason, detail }
        500 { status: error, reason, detail }
    """
    try:
        payload: dict[str, Any] = await request.json()
    except Exception as exc:
        return _error(400, "invalid_json", str(exc))

    parsed = _channel_router.handle_reply("calendar", payload)
    booking_id: str = parsed.get("booking_id", "")
    attendee_email: str = parsed.get("attendee_email", "")
    start_time: str = parsed.get("start_time", "")

    if not attendee_email:
        return _ignored("missing_attendee_email")

    # Match state by attendee email
    state = _find_state_by_email(attendee_email)
    if state is None:
        logger.info(
            "No matching thread for calendar booking by %s", attendee_email
        )
        return _ignored("no_matching_thread")

    # Advance state machine to booked
    next_stage, err = _channel_router.transition_state(state.stage, "booking_confirmed")
    if err:
        logger.warning(
            "Booking transition failed | prospect=%s | err=%s",
            state.prospect_id, err,
        )
    else:
        state.stage = next_stage

    from datetime import datetime, timezone
    state.booked_at = datetime.now(timezone.utc).isoformat()

    try:
        _save_state(state)
    except Exception as exc:
        return _error(500, "state_save_failed", str(exc))

    logger.info(
        "Booking confirmed | prospect=%s | booking=%s | start=%s",
        state.prospect_id, booking_id, start_time,
    )
    return _ok({
        "booking_id": booking_id,
        "attendee_email": attendee_email,
        "stage": state.stage,
    })
