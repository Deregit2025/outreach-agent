"""
Email channel handler using the Resend API.

Handles outbound sending and inbound reply webhook parsing.
All sends are routed through the kill switch before delivery.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import settings
from config.kill_switch import route_email

try:
    from observability.cost_tracker import cost_tracker
    _COST_TRACKER_AVAILABLE = True
except ImportError:
    _COST_TRACKER_AVAILABLE = False

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_DEFAULT_FROM_EMAIL = "agent@tenacious.dev"


class EmailHandler:
    """Send and receive emails via the Resend API."""

    def __init__(self) -> None:
        self._api_key: str = settings.resend_api_key
        self._from_email: str = settings.resend_from_email or _DEFAULT_FROM_EMAIL

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        from_name: str = "Tenacious",
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an email via Resend.

        Kill switch is applied before delivery: when active, the message is
        redirected to the staff sink address rather than the real recipient.

        Returns a dict with keys:
            id        – Resend message ID (empty string on error)
            sent_to   – actual recipient address used
            status    – "sent" | "error"
            error     – None or error message string
        """
        actual_to = route_email(to)
        from_field = f"{from_name} <{self._from_email}>"

        payload: dict[str, Any] = {
            "from": from_field,
            "to": [actual_to],
            "subject": subject,
            "html": body,
        }
        if reply_to:
            payload["reply_to"] = reply_to

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(_RESEND_URL, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

            message_id: str = data.get("id", "")
            logger.info("Email sent | id=%s | to=%s", message_id, actual_to)

            if _COST_TRACKER_AVAILABLE:
                try:
                    cost_tracker.track(channel="email", event="send", units=1)
                except Exception:
                    pass

            return {
                "id": message_id,
                "sent_to": actual_to,
                "status": "sent",
                "error": None,
            }

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            logger.error(
                "Resend HTTP error %s | to=%s | body=%s",
                exc.response.status_code,
                actual_to,
                error_body,
            )
            return {
                "id": "",
                "sent_to": actual_to,
                "status": "error",
                "error": f"HTTP {exc.response.status_code}: {error_body}",
            }
        except Exception as exc:
            logger.exception("Unexpected error sending email to %s", actual_to)
            return {
                "id": "",
                "sent_to": actual_to,
                "status": "error",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def parse_reply_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Parse an inbound email webhook payload from Resend.

        Resend delivers inbound email data under various key formats depending
        on the plan and webhook version.  We normalise to a flat dict.

        Returns:
            {
                "from":            sender address string,
                "subject":         email subject string,
                "body":            plain-text or HTML body,
                "prospect_email":  the original sender (same as "from"),
            }
        """
        # Resend inbound webhook envelope
        data: dict[str, Any] = payload.get("data", payload)

        sender: str = (
            data.get("from")
            or data.get("sender")
            or data.get("from_address", "")
        )
        subject: str = data.get("subject", "")
        body: str = (
            data.get("text")
            or data.get("html")
            or data.get("body", "")
        )

        return {
            "from": sender,
            "subject": subject,
            "body": body,
            "prospect_email": sender,
        }
