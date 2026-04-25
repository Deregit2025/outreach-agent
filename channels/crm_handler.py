"""
CRM channel handler using the HubSpot REST API.

Handles deterministic writes (upsert, notes, deals, email activity).
The LLM uses MCP for lookups; this module is for programmatic writes only.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import settings

try:
    from observability.cost_tracker import tracker as _cost_tracker
    _COST_TRACKER_AVAILABLE = True
except ImportError:
    _cost_tracker = None  # type: ignore
    _COST_TRACKER_AVAILABLE = False

logger = logging.getLogger(__name__)


class CRMHandler:
    """Interact with HubSpot CRM via the REST v3 API."""

    BASE = "https://api.hubapi.com"

    def __init__(self) -> None:
        self._token: str = settings.hubspot_access_token

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=20.0)

    # ------------------------------------------------------------------
    # Contact upsert
    # ------------------------------------------------------------------

    def upsert_contact(self, email: str, properties: dict[str, Any]) -> dict[str, Any]:
        """
        Create or update a HubSpot contact by email.

        Attempts a POST first. On 409 Conflict (contact already exists) it
        fetches the existing contact ID and PATCHes it instead.

        Args:
            email:      Primary email address (used as deduplication key).
            properties: Flat dict of HubSpot property names → values.
                        Common keys: firstname, lastname, company, jobtitle,
                                     phone, hs_lead_status.

        Returns:
            {"contact_id": str, "status": "created" | "updated" | "error", "error": None | str}
        """
        props = {**properties, "email": email}
        url_create = f"{self.BASE}/crm/v3/objects/contacts"

        try:
            with self._client() as client:
                response = client.post(
                    url_create,
                    json={"properties": props},
                    headers=self._headers,
                )

                # 409 → contact already exists; switch to patch
                if response.status_code == 409:
                    existing = self.search_contact(email)
                    if existing is None:
                        return {
                            "contact_id": "",
                            "status": "error",
                            "error": "Contact exists but could not be found via search",
                        }
                    contact_id = existing["contact_id"]
                    patch_url = f"{self.BASE}/crm/v3/objects/contacts/{contact_id}"
                    patch_resp = client.patch(
                        patch_url,
                        json={"properties": properties},
                        headers=self._headers,
                    )
                    patch_resp.raise_for_status()
                    logger.info("Contact updated | id=%s | email=%s", contact_id, email)
                    return {"contact_id": contact_id, "status": "updated", "error": None}

                response.raise_for_status()
                data = response.json()
                contact_id = str(data.get("id", ""))
                logger.info("Contact created | id=%s | email=%s", contact_id, email)

                logger.debug("CRM contact_created recorded | id=%s", contact_id)

                return {"contact_id": contact_id, "status": "created", "error": None}

        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpot upsert_contact HTTP error %s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "contact_id": "",
                "status": "error",
                "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
            }
        except Exception as exc:
            logger.exception("Unexpected error upserting HubSpot contact: %s", email)
            return {"contact_id": "", "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Note creation
    # ------------------------------------------------------------------

    def create_note(self, contact_id: str, body: str) -> dict[str, Any]:
        """
        Create a note in HubSpot and associate it with a contact.

        Returns:
            {"note_id": str, "status": "created" | "error", "error": None | str}
        """
        url = f"{self.BASE}/crm/v3/objects/notes"
        payload: dict[str, Any] = {
            "properties": {
                "hs_note_body": body,
                "hs_timestamp": _now_ms(),
            },
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 202,  # note → contact
                        }
                    ],
                }
            ],
        }

        try:
            with self._client() as client:
                response = client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                data = response.json()

            note_id = str(data.get("id", ""))
            logger.info("Note created | id=%s | contact=%s", note_id, contact_id)
            return {"note_id": note_id, "status": "created", "error": None}

        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpot create_note HTTP error %s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "note_id": "",
                "status": "error",
                "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
            }
        except Exception as exc:
            logger.exception("Unexpected error creating HubSpot note for contact %s", contact_id)
            return {"note_id": "", "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Deal stage update
    # ------------------------------------------------------------------

    def update_deal_stage(
        self,
        contact_id: str,
        stage: str,
        amount: float | None = None,
    ) -> dict[str, Any]:
        """
        Create or update the deal associated with a contact.

        Searches for an existing deal linked to the contact first.
        Creates a new deal if none exists; patches dealstage if one is found.

        Returns:
            {"deal_id": str, "status": "created" | "updated" | "error", "error": None | str}
        """
        # Search for an existing deal on this contact
        search_url = f"{self.BASE}/crm/v3/objects/deals/search"
        search_payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "associations.contact",
                            "operator": "EQ",
                            "value": contact_id,
                        }
                    ]
                }
            ],
            "properties": ["dealstage", "dealname", "amount"],
            "limit": 1,
        }

        try:
            with self._client() as client:
                search_resp = client.post(
                    search_url, json=search_payload, headers=self._headers
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()
                results: list[dict[str, Any]] = search_data.get("results", [])

                deal_props: dict[str, Any] = {"dealstage": stage}
                if amount is not None:
                    deal_props["amount"] = str(amount)

                if results:
                    # Update existing deal
                    deal_id = str(results[0]["id"])
                    patch_url = f"{self.BASE}/crm/v3/objects/deals/{deal_id}"
                    patch_resp = client.patch(
                        patch_url,
                        json={"properties": deal_props},
                        headers=self._headers,
                    )
                    patch_resp.raise_for_status()
                    logger.info(
                        "Deal updated | id=%s | stage=%s | contact=%s",
                        deal_id, stage, contact_id,
                    )
                    return {"deal_id": deal_id, "status": "updated", "error": None}

                # Create new deal and associate with contact
                deal_props["dealname"] = f"Deal – contact {contact_id}"
                create_payload: dict[str, Any] = {
                    "properties": deal_props,
                    "associations": [
                        {
                            "to": {"id": contact_id},
                            "types": [
                                {
                                    "associationCategory": "HUBSPOT_DEFINED",
                                    "associationTypeId": 3,  # deal → contact
                                }
                            ],
                        }
                    ],
                }
                create_resp = client.post(
                    f"{self.BASE}/crm/v3/objects/deals",
                    json=create_payload,
                    headers=self._headers,
                )
                create_resp.raise_for_status()
                deal_id = str(create_resp.json().get("id", ""))
                logger.info(
                    "Deal created | id=%s | stage=%s | contact=%s",
                    deal_id, stage, contact_id,
                )
                return {"deal_id": deal_id, "status": "created", "error": None}

        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpot update_deal_stage HTTP error %s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "deal_id": "",
                "status": "error",
                "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
            }
        except Exception as exc:
            logger.exception(
                "Unexpected error updating deal stage for contact %s", contact_id
            )
            return {"deal_id": "", "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Email activity logging
    # ------------------------------------------------------------------

    def log_email_activity(
        self,
        contact_id: str,
        subject: str,
        body: str,
        direction: str = "OUTBOUND",
    ) -> dict[str, Any]:
        """
        Log an email engagement on a HubSpot contact record.

        Args:
            contact_id: HubSpot contact ID.
            subject:    Email subject line.
            body:       Email body (plain text or HTML).
            direction:  "OUTBOUND" (default) or "INBOUND".

        Returns:
            {"activity_id": str, "status": "logged" | "error", "error": None | str}
        """
        url = f"{self.BASE}/crm/v3/objects/emails"
        _direction_map = {"OUTBOUND": "EMAIL", "INBOUND": "INCOMING_EMAIL"}
        hs_direction = _direction_map.get(direction, "EMAIL")
        payload: dict[str, Any] = {
            "properties": {
                "hs_email_direction": hs_direction,
                "hs_email_status": "SENT" if direction == "OUTBOUND" else "RECEIVED",
                "hs_email_subject": subject,
                "hs_email_text": body,
                "hs_timestamp": _now_ms(),
            },
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 198,  # email → contact
                        }
                    ],
                }
            ],
        }

        try:
            with self._client() as client:
                response = client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                data = response.json()

            activity_id = str(data.get("id", ""))
            logger.info(
                "Email activity logged | id=%s | contact=%s | direction=%s",
                activity_id, contact_id, direction,
            )
            return {"activity_id": activity_id, "status": "logged", "error": None}

        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpot log_email_activity HTTP error %s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "activity_id": "",
                "status": "error",
                "error": f"HTTP {exc.response.status_code}: {exc.response.text}",
            }
        except Exception as exc:
            logger.exception(
                "Unexpected error logging email activity for contact %s", contact_id
            )
            return {"activity_id": "", "status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Contact search
    # ------------------------------------------------------------------

    def search_contact(self, email: str) -> dict[str, Any] | None:
        """
        Search for a HubSpot contact by email address.

        Returns a dict with at least {"contact_id": str, "properties": dict}
        or None if no matching contact is found.
        """
        url = f"{self.BASE}/crm/v3/objects/contacts/search"
        payload: dict[str, Any] = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": email,
                        }
                    ]
                }
            ],
            "properties": [
                "email", "firstname", "lastname", "company",
                "jobtitle", "phone", "hs_lead_status",
            ],
            "limit": 1,
        }

        try:
            with self._client() as client:
                response = client.post(url, json=payload, headers=self._headers)
                response.raise_for_status()
                data = response.json()

            results: list[dict[str, Any]] = data.get("results", [])
            if not results:
                return None

            record = results[0]
            return {
                "contact_id": str(record.get("id", "")),
                "properties": record.get("properties", {}),
            }

        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpot search_contact HTTP error %s | body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return None
        except Exception as exc:
            logger.exception("Unexpected error searching HubSpot contact: %s", email)
            return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now_ms() -> str:
    """Return the current UTC time as a millisecond-epoch string for HubSpot."""
    from datetime import datetime, timezone
    return str(int(datetime.now(timezone.utc).timestamp() * 1000))
