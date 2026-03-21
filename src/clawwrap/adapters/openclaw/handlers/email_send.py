"""OpenClaw handler binding: email.send.

Sends a transactional email via the Resend API.
This is the production email send path used in clawwrap E2E tests.

Requires env var: RESEND_API_KEY_SENDING (falls back to RESEND_API_KEY)
API: POST https://api.resend.com/emails
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from clawwrap.handlers.registry import handler

_RESEND_API_URL: str = "https://api.resend.com/emails"
_TIMEOUT_SEC: int = 20
_FALLBACK_FROM: str = "noreply@example.com"


@handler("email.send", adapter_name="openclaw")
def send_email(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send a transactional email via Resend.

    Contract inputs:
        to (str): Recipient email address.
        subject (str): Email subject line.
        body_text (str): Plain-text email body.
        from_address (str, optional): Sender address (default: RESEND_DEFAULT_FROM,
            then RESEND_TRANSACTIONAL_FROM, then RESEND_FROM_ADDRESS).
        dry_run (bool, optional): When True, skip API call and return mock result (default False).

    Contract outputs:
        email_id (str): Resend-assigned message ID (empty on dry_run).
        sent_at (str): ISO 8601 UTC timestamp of send attempt.
        dry_run (bool): Echoes the dry_run flag.
        detail (str): Human-readable result.
    """
    to: str = str(inputs.get("to", "")).strip()
    subject: str = str(inputs.get("subject", "")).strip()
    body_text: str = str(inputs.get("body_text", "")).strip()
    from_address: str = str(inputs.get("from_address", "") or _default_from_address()).strip()
    dry_run: bool = bool(inputs.get("dry_run", False))

    if not to:
        return _error("to is required")
    if not subject:
        return _error("subject is required")
    if not body_text:
        return _error("body_text is required")

    sent_at = datetime.now(tz=timezone.utc).isoformat()

    if dry_run:
        return {
            "email_id": "",
            "sent_at": sent_at,
            "dry_run": True,
            "detail": f"dry_run: would send '{subject}' to {to}",
        }

    api_key = os.environ.get("RESEND_API_KEY_SENDING") or os.environ.get("RESEND_API_KEY")
    if not api_key:
        return _error("RESEND_API_KEY_SENDING or RESEND_API_KEY env var not set")

    payload = {
        "from": from_address,
        "to": [to],
        "subject": subject,
        "text": body_text,
    }

    try:
        resp = httpx.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        return _error(f"Resend API timed out after {_TIMEOUT_SEC}s")
    except httpx.RequestError as exc:
        return _error(f"Resend request error: {exc}")

    if resp.status_code not in (200, 201):
        body = resp.text[:512]
        return _error(f"Resend HTTP {resp.status_code}: {body}")

    try:
        data = resp.json()
        email_id = str(data.get("id") or "")
    except Exception:
        email_id = ""

    return {
        "email_id": email_id,
        "sent_at": sent_at,
        "dry_run": False,
        "detail": f"sent '{subject}' to {to}; id={email_id}",
    }


def _error(detail: str) -> dict[str, Any]:
    return {
        "email_id": "",
        "sent_at": "",
        "dry_run": False,
        "detail": detail,
    }


def _default_from_address() -> str:
    return (
        os.environ.get("RESEND_DEFAULT_FROM")
        or os.environ.get("RESEND_TRANSACTIONAL_FROM")
        or os.environ.get("RESEND_FROM_ADDRESS")
        or _FALLBACK_FROM
    )
