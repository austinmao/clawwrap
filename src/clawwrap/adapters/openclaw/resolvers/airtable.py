"""Airtable contact recipient resolver adapter."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from clawwrap.adapters.openclaw.resolvers._helpers import (
    _build_label,
    _extract_suffix,
    _get_json,
    _normalize_phone,
)

_AIRTABLE_API_BASE = "https://api.airtable.com/v0"
_AIRTABLE_BASE_ID_ENV = "AIRTABLE_BASE_ID"
_AIRTABLE_CONTACTS_TABLE_ENV = "AIRTABLE_CONTACTS_TABLE_ID"
_AIRTABLE_FALLBACK_TABLE_ENV = "AIRTABLE_TABLE_ID"
_AIRTABLE_DEFAULT_BASE_ID = ""  # Must be set via AIRTABLE_BASE_ID env var
_AIRTABLE_DEFAULT_CONTACTS_TABLE_ID = "tblsuU413owKxHWzp"


class AirtableContactsResolver:
    """Resolve ``airtable:contacts/<record_id>`` refs via Airtable."""

    def resolve(self, recipient_ref: str, channel: str) -> tuple[str, str, str]:
        record_id = _extract_suffix(recipient_ref, "airtable:contacts/")
        api_key = os.environ.get("AIRTABLE_API_KEY", "").strip()
        base_id = os.environ.get(_AIRTABLE_BASE_ID_ENV, _AIRTABLE_DEFAULT_BASE_ID).strip()
        table_id = (
            os.environ.get(_AIRTABLE_CONTACTS_TABLE_ENV, "").strip()
            or os.environ.get(_AIRTABLE_FALLBACK_TABLE_ENV, "").strip()
            or _AIRTABLE_DEFAULT_CONTACTS_TABLE_ID
        )

        if not api_key:
            raise ValueError("AIRTABLE_API_KEY is not set")
        if not base_id or not table_id:
            raise ValueError("Airtable base/table configuration is incomplete")

        url = f"{_AIRTABLE_API_BASE}/{quote(base_id)}/{quote(table_id)}/{quote(record_id)}"
        payload = _get_json(url, headers={"Authorization": f"Bearer {api_key}"})

        if not isinstance(payload, dict):
            raise ValueError(f"Airtable record response must be an object, got {type(payload).__name__}")

        fields = payload.get("fields")
        if not isinstance(fields, dict):
            raise ValueError(f"Airtable record {record_id!r} is missing fields")

        target = _extract_airtable_target(fields, channel)
        label = _build_label(fields, recipient_ref)
        provider_id = str(payload.get("id") or record_id)
        return target, label, provider_id


def _extract_airtable_target(fields: dict[str, Any], channel: str) -> str:
    if channel == "email":
        email = _first_string(fields, "email", "Email")
        if email:
            return email
        raise ValueError("Airtable contact is missing an email address")
    if channel == "whatsapp":
        phone = _first_string(fields, "phone", "Phone", "Phone number")
        if phone:
            return _normalize_phone(phone)
        raise ValueError("Airtable contact is missing a phone number")
    raise ValueError(f"unsupported channel {channel!r} for airtable contacts")


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
