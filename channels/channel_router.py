"""
Channel router — dispatches outbound messages and inbound replies to the
correct handler based on the prospect's current lead stage.
"""

from __future__ import annotations

import logging
from typing import Any

from channels.email_handler import EmailHandler
from channels.sms_handler import SMSHandler
from channels.calendar_handler import CalendarHandler
from channels.crm_handler import CRMHandler

logger = logging.getLogger(__name__)

# Maps a lead stage to the preferred outbound channel.
# None means no further automated outreach should be sent.
STAGE_CHANNEL_MAP: dict[str, str | None] = {
    "new": "email",
    "replied_by_email": "email",
    "warm_prefers_sms": "sms",
    "qualified": "email",   # calendar link delivered via email
    "booked": None,         # no outreach until after the call
    "paused": None,
    "closed": None,
}


class ChannelRouter:
    """
    Top-level router that owns one instance of every channel handler and
    provides a unified interface for sending and receiving messages.
    """

    def __init__(self) -> None:
        self.email = EmailHandler()
        self.sms = SMSHandler()
        self.calendar = CalendarHandler()
        self.crm = CRMHandler()

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

        Args:
            prospect:   Dict that must contain at least "email" and optionally
                        "phone", "name".
            message:    Message body (plain text; HTML is acceptable for email).
            subject:    Email subject line (ignored for SMS).
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
                return {
                    "channel": "sms",
                    "sent_to": "",
                    "status": "error",
                    "error": "Prospect dict missing 'phone' field",
                }
            result = self.sms.send(to=to_phone, message=message)
            return {"channel": "sms", **result}

        # Should never reach here given known channel values, but guard anyway
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
