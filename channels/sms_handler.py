"""
SMS channel handler using the Africa's Talking API.

Handles outbound SMS sending and inbound webhook parsing.
All sends are routed through the kill switch before delivery.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import settings
from config.kill_switch import route_phone

try:
    from observability.cost_tracker import cost_tracker
    _COST_TRACKER_AVAILABLE = True
except ImportError:
    _COST_TRACKER_AVAILABLE = False

logger = logging.getLogger(__name__)

_AT_SMS_URL = "https://api.africastalking.com/version1/messaging"


class SMSHandler:
    """Send and receive SMS messages via Africa's Talking."""

    def __init__(self) -> None:
        self._api_key: str = settings.at_api_key
        self._username: str = settings.at_username
        self._short_code: str = settings.at_short_code

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def send(self, to: str, message: str) -> dict[str, Any]:
        """
        Send an SMS via Africa's Talking.

        Kill switch is applied before delivery: when active, the message is
        redirected to the staff sink phone number rather than the real recipient.

        Returns a dict with keys:
            status      – "sent" | "error"
            sent_to     – actual phone number used
            message_id  – Africa's Talking message ID (empty string on error)
            error       – None or error message string
        """
        actual_to = route_phone(to)

        headers = {
            "apiKey": self._api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        form_data: dict[str, str] = {
            "username": self._username,
            "to": actual_to,
            "message": message,
        }
        if self._short_code:
            form_data["from"] = self._short_code

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(_AT_SMS_URL, data=form_data, headers=headers)
                response.raise_for_status()
                data = response.json()

            recipients: list[dict[str, Any]] = (
                data.get("SMSMessageData", {}).get("Recipients", [])
            )
            if not recipients:
                raise ValueError(f"No recipients in AT response: {data}")

            recipient = recipients[0]
            message_id: str = recipient.get("messageId", "")
            status_code: str = recipient.get("statusCode", "")

            logger.info(
                "SMS sent | message_id=%s | to=%s | status=%s",
                message_id,
                actual_to,
                status_code,
            )

            if _COST_TRACKER_AVAILABLE:
                try:
                    cost_tracker.track(channel="sms", event="send", units=1)
                except Exception:
                    pass

            return {
                "status": "sent",
                "sent_to": actual_to,
                "message_id": message_id,
                "error": None,
            }

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            logger.error(
                "Africa's Talking HTTP error %s | to=%s | body=%s",
                exc.response.status_code,
                actual_to,
                error_body,
            )
            return {
                "status": "error",
                "sent_to": actual_to,
                "message_id": "",
                "error": f"HTTP {exc.response.status_code}: {error_body}",
            }
        except Exception as exc:
            logger.exception("Unexpected error sending SMS to %s", actual_to)
            return {
                "status": "error",
                "sent_to": actual_to,
                "message_id": "",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def parse_inbound_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Parse an inbound SMS webhook payload from Africa's Talking.

        Africa's Talking POSTs form-encoded data; by the time it reaches here
        it has been decoded to a dict by the web framework.

        Returns:
            {
                "from": sender MSISDN,
                "text": message body,
                "date": ISO timestamp string,
            }
        """
        return {
            "from": payload.get("from", payload.get("From", "")),
            "text": payload.get("text", payload.get("Text", payload.get("body", ""))),
            "date": payload.get("date", payload.get("Date", payload.get("received_at", ""))),
        }
