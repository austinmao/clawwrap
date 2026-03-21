"""OpenClaw handler binding: email.verify_receipt.

Polls the AgentMail REST API to confirm a sent email appears in the inbox.
API: GET https://api.agentmail.to/v0/inboxes/{inbox_id}/messages

Requires env var: AGENTMAIL_API_KEY
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from clawwrap.handlers.registry import handler

_POLL_INTERVAL_SEC: int = 10
_POLL_MAX_ATTEMPTS: int = 4  # 40s total window
_TIMEOUT_SEC: int = 10
_AGENTMAIL_BASE: str = "https://api.agentmail.to/v0"


@handler("email.verify_receipt", adapter_name="openclaw")
def verify_email_receipt(inputs: dict[str, Any]) -> dict[str, Any]:
    """Poll AgentMail to confirm a sent email arrived in the inbox.

    Polls up to 4 times at 10-second intervals (40s total).

    Contract inputs:
        inbox (str): AgentMail inbox address to poll (e.g. dangerousflower464@agentmail.to).
        subject_contains (str): Substring expected in the matched message subject.
        sent_at (str): ISO 8601 UTC timestamp; messages before this time are ignored.
        dry_run (bool, optional): Skip polling, return mock success.

    Contract outputs:
        verified (bool): True when matching message was found.
        message_id (str): AgentMail message_id of the matched message (empty if not found).
        round_trip_ms (int): Milliseconds from sent_at to verification.
        attempts (int): Number of poll attempts made.
        detail (str): Human-readable result.
    """
    inbox: str = str(inputs.get("inbox", "")).strip()
    subject_contains: str = str(inputs.get("subject_contains", "")).strip()
    sent_at_str: str = str(inputs.get("sent_at", "")).strip()
    dry_run: bool = bool(inputs.get("dry_run", False))

    if not inbox:
        return _result(False, "", 0, 0, "inbox is required")
    if not subject_contains:
        return _result(False, "", 0, 0, "subject_contains is required")

    if dry_run:
        return _result(True, "dry-run-msg-id", 1, 42, "dry_run: verification skipped")

    api_key = os.environ.get("AGENTMAIL_API_KEY")
    if not api_key:
        return _result(False, "", 0, 0, "AGENTMAIL_API_KEY env var not set")

    sent_ts = _parse_ts(sent_at_str)

    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(_POLL_INTERVAL_SEC)

        messages = _fetch_messages(inbox, api_key)
        if messages is None:
            continue

        match = _find_message(messages, subject_contains, sent_ts)
        if match:
            now_ms = int(time.time() * 1000)
            sent_ms = int(sent_ts * 1000) if sent_ts else now_ms
            return _result(
                True,
                match,
                attempt,
                now_ms - sent_ms,
                f"found after {attempt} attempt(s): subject matches '{subject_contains}'",
            )

    return _result(
        False, "", _POLL_MAX_ATTEMPTS, 0,
        f"message not found after {_POLL_MAX_ATTEMPTS} poll attempts"
    )


def _fetch_messages(inbox: str, api_key: str) -> list[dict[str, Any]] | None:
    """Call AgentMail API and return message list, or None on error."""
    url = f"{_AGENTMAIL_BASE}/inboxes/{inbox}/messages"
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 20},
            timeout=_TIMEOUT_SEC,
        )
    except (httpx.TimeoutException, httpx.RequestError):
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
        return data.get("messages", []) if isinstance(data, dict) else []
    except Exception:
        return None


def _find_message(
    messages: list[dict[str, Any]],
    subject_contains: str,
    sent_ts: float,
) -> str:
    """Return message_id of first matching message, or empty string."""
    for msg in messages:
        subject = str(msg.get("subject") or "")
        if subject_contains.lower() not in subject.lower():
            continue
        # Skip messages from before the send
        msg_ts = _parse_ts(str(msg.get("timestamp") or ""))
        if sent_ts and msg_ts and msg_ts < sent_ts - 5:  # 5s tolerance
            continue
        return str(msg.get("message_id") or "")
    return ""


def _parse_ts(iso_str: str) -> float:
    """Parse ISO 8601 string to unix timestamp, or 0.0 on error."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _result(
    verified: bool,
    message_id: str,
    attempts: int,
    round_trip_ms: int,
    detail: str,
) -> dict[str, Any]:
    return {
        "verified": verified,
        "message_id": message_id,
        "round_trip_ms": round_trip_ms,
        "attempts": attempts,
        "detail": detail,
    }
