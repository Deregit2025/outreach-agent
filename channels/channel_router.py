"""
Channel router — state machine that dispatches outbound messages and inbound
replies to the correct handler based on the prospect's current lead stage.

State machine transitions:
    new  ──email──▶  replied_by_email
    replied_by_email  ──email──▶  qualified
    replied_by_email  ──(sms_opt_in)──▶  warm_prefers_sms
    warm_prefers_sms  ──sms──▶  qualified
    qualified  ──(booking link sent)──▶  booked
    booked  ──(none)
    paused  ──(none)
    closed  ──(none)

Warm-lead SMS gate:
    SMS is ONLY sent after the prospect has replied to email AND has explicitly
    confirmed SMS preference. Transitioning to warm_prefers_sms requires
    sms_opt_in=True. Cold SMS is prohibited by this router.
"""

from __future__ import annotations

import logging
from typing import Any

from channels.email_handler import EmailHandler
from channels.sms_handler import SMSHandler
from channels.calendar_handler import CalendarHandler
from channels.crm_handler import CRMHandler
from config.settings import settings

logger = logging.getLogger(__name__)

# ── Stage → channel map ───────────────────────────────────────────────────────
# None = no automated outreach permitted from this stage.
STAGE_CHANNEL_MAP: dict[str, str | None] = {
    "new": "email",
    "replied_by_email": "email",
    "warm_prefers_sms": "sms",
    "qualified": "email",   # booking link delivered via email (and SMS if warm)
    "booked": None,
    "paused": None,
    "closed": None,
}

# ── Valid state-machine transitions ──────────────────────────────────────────
# Maps (current_stage, event) → next_stage.
# Events: "email_sent", "email_replied", "sms_opt_in", "booking_link_sent",
#         "booking_confirmed", "pause", "close", "unsubscribe"
VALID_TRANSITIONS: dict[tuple[str, str], str] = {
    ("new",              "email_sent"):        "new",
    ("new",              "email_replied"):     "replied_by_email",
    ("replied_by_email", "email_replied"):     "replied_by_email",
    ("replied_by_email", "sms_opt_in"):        "warm_prefers_sms",
    ("replied_by_email", "booking_link_sent"): "qualified",
    ("warm_prefers_sms", "sms_replied"):       "warm_prefers_sms",
    ("warm_prefers_sms", "booking_link_sent"): "qualified",
    ("qualified",        "booking_confirmed"): "booked",
    # Any stage can be paused or closed
    ("new",              "pause"):             "paused",
    ("replied_by_email", "pause"):             "paused",
    ("warm_prefers_sms", "pause"):             "paused",
    ("qualified",        "pause"):             "paused",
    ("new",              "unsubscribe"):       "closed",
    ("replied_by_email", "unsubscribe"):       "closed",
    ("warm_prefers_sms", "unsubscribe"):       "closed",
    ("qualified",        "unsubscribe"):       "closed",
    ("booked",           "close"):             "closed",
}


class ChannelRouter:
    """
    Top-level router that owns one instance of every channel handler and
    provides a unified interface for sending and receiving messages.

    Enforces:
    - Stage-to-channel mapping (STAGE_CHANNEL_MAP)
    - Warm-lead SMS gate (sms_opt_in must be True before SMS sends)
    - Cal.com booking link generation for both email and SMS delivery paths
    - State machine transitions via transition_state()
    """

    def __init__(self) -> None:
        self.email = EmailHandler()
        self.sms = SMSHandler()
        self.calendar = CalendarHandler()
        self.crm = CRMHandler()

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def transition_state(
        self,
        current_stage: str,
        event: str,
        sms_opt_in: bool = False,
    ) -> tuple[str, str | None]:
        """
        Apply a state machine transition.

        Args:
            current_stage: The prospect's current pipeline stage.
            event:         The triggering event string (see VALID_TRANSITIONS).
            sms_opt_in:    Must be True for the "sms_opt_in" event to succeed.

        Returns:
            (next_stage, error_message | None)
            On success: (new_stage_string, None)
            On invalid transition: (current_stage, error description)
        """
        # Guard the warm-lead SMS gate: sms_opt_in event requires explicit consent
        if event == "sms_opt_in" and not sms_opt_in:
            return current_stage, (
                "SMS opt-in event blocked: sms_opt_in flag must be True. "
                "SMS requires explicit prospect consent (keyword: 'text me', "
                "'WhatsApp', or phone number provided in reply)."
            )

        next_stage = VALID_TRANSITIONS.get((current_stage, event))
        if next_stage is None:
            return current_stage, (
                f"No valid transition from stage={current_stage!r} on event={event!r}. "
                f"Valid events from this stage: "
                f"{[e for (s, e) in VALID_TRANSITIONS if s == current_stage]}"
            )

        logger.info(
            "Stage transition | %s --[%s]--> %s", current_stage, event, next_stage
        )
        return next_stage, None

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    def get_channel(self, lead_stage: str) -> str | None:
        """
        Return the preferred channel name for the given lead stage.

        Returns "email", "sms", or None (no automated outreach).
        Unknown stages default to "email" with a warning.
        """
        if lead_stage not in STAGE_CHANNEL_MAP:
            logger.warning(
                "Unknown lead stage %r — defaulting to email", lead_stage
            )
            return "email"
        return STAGE_CHANNEL_MAP[lead_stage]

    # ------------------------------------------------------------------
    # Booking link generation
    # ------------------------------------------------------------------

    def get_booking_link(self) -> str:
        """
        Return the Cal.com booking link for the discovery call.

        Uses CALCOM_BOOKING_URL from settings (the public self-scheduling link)
        so the prospect can pick their own slot without the agent needing to
        call the Cal.com API for slot availability.
        """
        return settings.calcom_booking_url or "https://cal.com/tenacious/discovery"

    def send_booking_link(
        self,
        prospect: dict[str, Any],
        lead_stage: str,
        extra_context: str = "",
    ) -> dict[str, Any]:
        """
        Send the Cal.com booking link via the appropriate channel (email or SMS).

        For email stages: delivers a full email with the booking link embedded.
        For warm_prefers_sms: delivers a short SMS with the link.
        Both paths include the same canonical booking URL.

        Args:
            prospect:      Must contain "email", optionally "phone" and "name".
            lead_stage:    Current stage; controls email vs. SMS delivery.
            extra_context: Optional one-line qualifier to personalise the message.

        Returns:
            Unified result dict from send_message() with "booking_url" added.
        """
        booking_url = self.get_booking_link()
        name = prospect.get("name", "there")

        channel = self.get_channel(lead_stage)

        if channel == "sms":
            message = (
                f"Hi {name} — grab a 20-min slot with the Tenacious team here: "
                f"{booking_url}"
            )
            if extra_context:
                message = f"{extra_context} {booking_url}"
            result = self.send_message(
                prospect=prospect,
                message=message,
                lead_stage=lead_stage,
            )
        else:
            subject = "Quick call — pick a time that works for you"
            body = (
                f"Hi {name},\n\n"
                f"{''.join([extra_context, chr(10), chr(10)] if extra_context else [])}"
                f"Happy to set up a 20-minute call to explore whether Tenacious is a fit.\n\n"
                f"Pick a time here (no sign-in required):\n{booking_url}\n\n"
                f"The Tenacious Team"
            )
            result = self.send_message(
                prospect=prospect,
                message=body,
                subject=subject,
                lead_stage=lead_stage,
            )

        result["booking_url"] = booking_url
        return result

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def send_message(
        self,
        prospect: dict[str, Any],
        message: str,
        subject: str = "",
        lead_stage: str = "new",
    ) -> dict[str, Any]:
        """
        Send a message to a prospect via the appropriate channel.

        Enforces the warm-lead SMS gate: if the current stage maps to "sms"
        but the prospect dict does not contain a "phone" key, the send is
        rejected with an error rather than silently falling back to email.

        Args:
            prospect:   Dict with at least "email"; "phone" required for SMS.
            message:    Message body (plain text; HTML accepted for email).
            subject:    Email subject (ignored for SMS).
            lead_stage: Current CRM stage — controls channel selection.

        Returns a unified result dict:
            {
                "channel":  "email" | "sms" | None,
                "sent_to":  actual address or number used,
                "status":   "sent" | "error" | "skipped",
                "error":    None | str,
                ...channel-specific keys...
            }
        """
        channel = self.get_channel(lead_stage)

        if channel is None:
            logger.info(
                "Outreach skipped — stage=%s suppresses automated sends", lead_stage
            )
            return {
                "channel": None,
                "sent_to": "",
                "status": "skipped",
                "error": f"Stage '{lead_stage}' does not permit automated outreach",
            }

        if channel == "email":
            to_email: str = prospect.get("email", "")
            if not to_email:
                return {
                    "channel": "email",
                    "sent_to": "",
                    "status": "error",
                    "error": "Prospect dict missing 'email' field",
                }
            result = self.email.send(
                to=to_email,
                subject=subject or "Following up",
                body=message,
                from_name="Tenacious",
                reply_to=prospect.get("reply_to"),
            )
            return {"channel": "email", **result}

        if channel == "sms":
            to_phone: str = prospect.get("phone", "")
            if not to_phone:
                # Hard reject — do not silently fall back to email for SMS stage.
                # The warm-lead gate requires an explicit phone number.
                return {
                    "channel": "sms",
                    "sent_to": "",
                    "status": "error",
                    "error": (
                        "Warm-lead SMS gate: prospect dict missing 'phone' field. "
                        "SMS is only sent after the prospect provides a phone number. "
                        "Transition back to 'replied_by_email' or resolve phone first."
                    ),
                }
            result = self.sms.send(to=to_phone, message=message)
            return {"channel": "sms", **result}

        return {
            "channel": channel,
            "sent_to": "",
            "status": "error",
            "error": f"Unrecognised channel: {channel!r}",
        }

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def handle_reply(self, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Parse an inbound webhook payload from the given channel.

        Args:
            channel: "email" | "sms" | "calendar"
            payload: Raw webhook body (already decoded to dict).

        Returns a unified reply dict:
            {
                "channel": str,
                ...channel-specific parsed fields...
            }
        """
        if channel == "email":
            parsed = self.email.parse_reply_webhook(payload)
            return {"channel": "email", **parsed}

        if channel == "sms":
            parsed = self.sms.parse_inbound_webhook(payload)
            # Check for STOP/unsubscribe signal
            text = parsed.get("text", "").strip().upper()
            if text in ("STOP", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
                parsed["unsubscribe_request"] = True
                logger.warning(
                    "Unsubscribe request via SMS from %s", parsed.get("from")
                )
            else:
                parsed["unsubscribe_request"] = False
            # Check for SMS opt-in keywords
            text_lower = parsed.get("text", "").lower()
            parsed["sms_opt_in_signal"] = any(
                kw in text_lower
                for kw in ("text me", "whatsapp", "sms", "message me")
            )
            return {"channel": "sms", **parsed}

        if channel == "calendar":
            parsed = self.calendar.parse_booking_webhook(payload)
            return {"channel": "calendar", **parsed}

        logger.warning("handle_reply called with unknown channel: %r", channel)
        return {
            "channel": channel,
            "error": f"Unknown channel: {channel!r}",
            "raw": payload,
        }
