"""
Calendar channel handler using the Cal.com self-hosted API.

Handles slot availability, booking creation, and webhook parsing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from config.settings import settings

try:
    from observability.cost_tracker import cost_tracker
    _COST_TRACKER_AVAILABLE = True
except ImportError:
    _COST_TRACKER_AVAILABLE = False

logger = logging.getLogger(__name__)


def _iso_to_display(iso: str) -> str:
    """Convert an ISO 8601 datetime string to a human-readable label."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%A, %b %-d at %-I:%M %p UTC")
    except Exception:
        return iso


class CalendarHandler:
    """Interact with a self-hosted Cal.com instance."""

    def __init__(self) -> None:
        self._base_url: str = settings.calcom_base_url.rstrip("/")
        self._api_key: str = settings.calcom_api_key
        self._default_event_type_id: str = settings.calcom_event_type_id

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Slot availability
    # ------------------------------------------------------------------

    def get_available_slots(
        self,
        event_type_id: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, Any]]:
        """
        Retrieve available booking slots from Cal.com.

        Args:
            event_type_id: Cal.com event type ID.
            date_from:     Start of the window, ISO 8601 string (e.g. "2026-04-21T00:00:00Z").
            date_to:       End of the window, ISO 8601 string.

        Returns:
            List of dicts with keys:
                time    – ISO datetime string
                display – human-readable label
        """
        url = f"{self._base_url}/api/v1/slots"
        params = {
            "eventTypeId": event_type_id or self._default_event_type_id,
            "startTime": date_from,
            "endTime": date_to,
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(url, params=params, headers=self._headers)
                response.raise_for_status()
                data = response.json()

            # Cal.com returns {"slots": {"YYYY-MM-DD": [{"time": "..."}], ...}}
            raw_slots = data.get("slots", data)
            slots: list[dict[str, Any]] = []

            if isinstance(raw_slots, dict):
                for _, day_slots in sorted(raw_slots.items()):
                    for slot in day_slots:
                        iso = slot.get("time", "")
                        slots.append({"time": iso, "display": _iso_to_display(iso)})
            elif isinstance(raw_slots, list):
                for slot in raw_slots:
                    iso = slot.get("time", slot.get("startTime", ""))
                    slots.append({"time": iso, "display": _iso_to_display(iso)})

            logger.info(
                "Fetched %d slots | event_type=%s | window=%s → %s",
                len(slots),
                event_type_id,
                date_from,
                date_to,
            )
            return slots

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Cal.com slots HTTP error %s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return []
        except Exception as exc:
            logger.exception("Unexpected error fetching Cal.com slots")
            return []

    # ------------------------------------------------------------------
    # Booking creation
    # ------------------------------------------------------------------

    def create_booking(
        self,
        event_type_id: str,
        start_time: str,
        name: str,
        email: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """
        Create a booking on Cal.com.

        Returns a dict with keys:
            booking_id  – Cal.com booking UID or integer ID as string
            booking_url – URL to view/manage the booking
            start_time  – confirmed start time ISO string
            status      – "confirmed" | "error"
        """
        url = f"{self._base_url}/api/v1/bookings"
        payload: dict[str, Any] = {
            "eventTypeId": int(event_type_id or self._default_event_type_id),
            "start": start_time,
            "responses": {
                "name": name,
                "email": email,
                "notes": notes,
            },
            "timeZone": "UTC",
            "language": "en",
            "metadata": {},
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                data = response.json()

            booking_id = str(data.get("uid", data.get("id", "")))
            booking_url = data.get(
                "bookingUrl",
                f"{self._base_url}/booking/{booking_id}" if booking_id else "",
            )
            confirmed_start = data.get("startTime", start_time)

            logger.info(
                "Booking created | id=%s | attendee=%s | start=%s",
                booking_id,
                email,
                confirmed_start,
            )

            if _COST_TRACKER_AVAILABLE:
                try:
                    cost_tracker.track(channel="calendar", event="booking_created", units=1)
                except Exception:
                    pass

            return {
                "booking_id": booking_id,
                "booking_url": booking_url,
                "start_time": confirmed_start,
                "status": "confirmed",
            }

        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            logger.error(
                "Cal.com booking HTTP error %s | body=%s",
                exc.response.status_code,
                error_body,
            )
            return {
                "booking_id": "",
                "booking_url": "",
                "start_time": start_time,
                "status": "error",
                "error": f"HTTP {exc.response.status_code}: {error_body}",
            }
        except Exception as exc:
            logger.exception("Unexpected error creating Cal.com booking")
            return {
                "booking_id": "",
                "booking_url": "",
                "start_time": start_time,
                "status": "error",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Inbound webhook
    # ------------------------------------------------------------------

    def parse_booking_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Parse a Cal.com booking webhook payload.

        Returns:
            {
                "booking_id":     UID or ID as string,
                "attendee_email": primary attendee email,
                "start_time":     ISO datetime string,
                "status":         booking status string (e.g. "ACCEPTED"),
            }
        """
        # Cal.com webhook wraps the booking under a "payload" key
        data: dict[str, Any] = payload.get("payload", payload)

        booking_id = str(data.get("uid", data.get("id", "")))

        # Attendees is a list; take the first non-organiser entry if available
        attendees: list[dict[str, Any]] = data.get("attendees", [])
        attendee_email: str = ""
        for attendee in attendees:
            email = attendee.get("email", "")
            if email and not attendee.get("isOrganizer", False):
                attendee_email = email
                break
        if not attendee_email and attendees:
            attendee_email = attendees[0].get("email", "")

        start_time: str = data.get("startTime", data.get("start", ""))
        status: str = data.get("status", payload.get("triggerEvent", ""))

        return {
            "booking_id": booking_id,
            "attendee_email": attendee_email,
            "start_time": start_time,
            "status": status,
        }
