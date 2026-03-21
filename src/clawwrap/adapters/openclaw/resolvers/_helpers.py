"""Shared helper functions for resolver adapters."""
from __future__ import annotations

import re
from typing import Any

import httpx

_HTTP_TIMEOUT_SEC = 10.0
_E164_RE = re.compile(r"^\+\d{7,15}$")


def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    try:
        response = httpx.get(url, headers=headers, params=params, timeout=_HTTP_TIMEOUT_SEC)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"HTTP {exc.response.status_code} from {url}") from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"request failed for {url}: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise ValueError(f"invalid JSON from {url}") from exc


def _extract_suffix(recipient_ref: str, prefix: str) -> str:
    if not recipient_ref.startswith(prefix):
        raise ValueError(f"recipient_ref {recipient_ref!r} must start with {prefix!r}")
    suffix = recipient_ref[len(prefix):].strip()
    if not suffix:
        raise ValueError(f"recipient_ref {recipient_ref!r} is missing an identifier")
    return suffix


def _build_label(record: dict[str, Any], recipient_ref: str) -> str:
    name = _first_string(
        record,
        "Full Name",
        "full_name",
        "name",
        "Name",
        "first_name",
    )
    last_name = _first_string(record, "last_name")
    if name and last_name and name == _first_string(record, "first_name"):
        name = f"{name} {last_name}".strip()
    return f"{name or 'Recipient'} ({recipient_ref})"


def _first_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_phone(value: str) -> str:
    value = value.strip()
    if _E164_RE.match(value):
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if value.startswith("00") and digits:
        return f"+{digits}"
    raise ValueError(f"phone number is not a recognizable E.164 value: {value!r}")
