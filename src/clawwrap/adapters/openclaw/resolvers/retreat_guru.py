"""Retreat Guru recipient resolver adapter."""
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

_RETREAT_GURU_API_KEY_ENV = "RETREAT_GURU_API_KEY"
_RETREAT_GURU_BASE_URL_ENV = "RETREAT_GURU_BASE_URL"


class RetreatGuruRegistrationsResolver:
    """Resolve ``retreat_guru:registrations/<id>`` refs via Retreat Guru."""

    def resolve(self, recipient_ref: str, channel: str) -> tuple[str, str, str]:
        registration_id = _extract_suffix(recipient_ref, "retreat_guru:registrations/")
        api_key = os.environ.get(_RETREAT_GURU_API_KEY_ENV, "").strip()
        base_url = os.environ.get(_RETREAT_GURU_BASE_URL_ENV, "").strip()

        if not api_key:
            raise ValueError(f"{_RETREAT_GURU_API_KEY_ENV} is not set")
        if not base_url:
            raise ValueError(f"{_RETREAT_GURU_BASE_URL_ENV} is not set")

        url = f"{base_url.rstrip('/')}/registrations/{quote(registration_id)}"
        payload = _get_json(
            url,
            params={"token": api_key},
            headers={"Accept": "application/json", "User-Agent": "clawwrap/0.1"},
        )
        registration = _coerce_retreat_guru_registration(payload, registration_id)

        target = _extract_retreat_guru_target(registration, channel)
        label = _build_label(registration, recipient_ref)
        provider_id = str(registration.get("id") or registration_id)
        return target, label, provider_id


def _extract_retreat_guru_target(registration: dict[str, Any], channel: str) -> str:
    if channel == "email":
        email = _first_string(registration, "email", "Email")
        if email:
            return email
        raise ValueError("Retreat Guru registration is missing an email address")
    if channel == "whatsapp":
        questions = registration.get("questions")
        if isinstance(questions, dict):
            phone = _first_string(questions, "phone", "Phone")
            if phone:
                return _normalize_phone(phone)
        raise ValueError("Retreat Guru registration is missing a phone number")
    raise ValueError(f"unsupported channel {channel!r} for retreat_guru registrations")


def _coerce_retreat_guru_registration(payload: Any, registration_id: str) -> dict[str, Any]:
    registration: Any = payload
    if isinstance(payload, list):
        registration = payload[0] if payload else None
    if not isinstance(registration, dict):
        raise ValueError(
            f"Retreat Guru registration {registration_id!r} returned {type(payload).__name__}, expected object"
        )
    return registration


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
