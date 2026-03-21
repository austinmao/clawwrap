"""OpenClaw handler binding: slack.post.

Posts a message to a Slack channel via the Slack Web API chat.postMessage.

Requires env var: SLACK_BOT_TOKEN
API: POST https://slack.com/api/chat.postMessage
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from clawwrap.handlers.registry import handler

_SLACK_API_URL: str = "https://slack.com/api/chat.postMessage"
_TIMEOUT_SEC: int = 20


@handler("slack.post", adapter_name="openclaw")
def slack_post(inputs: dict[str, Any]) -> dict[str, Any]:
    """Post a message to a Slack channel.

    Contract inputs:
        channel_id (str): Slack channel ID (e.g. "C0123456789").
        text (str): Message body.
        dry_run (bool, optional): When True, skip API call and return mock result (default False).

    Contract outputs:
        message_id (str): Slack message timestamp ID (empty on dry_run).
        sent_at (str): ISO 8601 UTC timestamp of send attempt.
        detail (str): Human-readable result.
    """
    channel_id: str = str(inputs.get("channel_id", "")).strip()
    text: str = str(inputs.get("text", "")).strip()
    dry_run: bool = bool(inputs.get("dry_run", False))

    if not channel_id:
        return _error("channel_id is required")
    if not text:
        return _error("text is required")

    sent_at = datetime.now(tz=timezone.utc).isoformat()

    if dry_run:
        return {
            "message_id": "",
            "sent_at": sent_at,
            "detail": f"dry_run: would post to {channel_id}",
        }

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return _error("SLACK_BOT_TOKEN env var not set")

    payload = {
        "channel": channel_id,
        "text": text,
    }

    try:
        resp = httpx.post(
            _SLACK_API_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        return _error(f"Slack API timed out after {_TIMEOUT_SEC}s")
    except httpx.RequestError as exc:
        return _error(f"Slack request error: {exc}")

    try:
        data = resp.json()
    except Exception:
        return _error(f"Slack HTTP {resp.status_code}: non-JSON response")

    if not data.get("ok"):
        error_msg = data.get("error", "unknown error")
        return _error(f"Slack API error: {error_msg}")

    ts = str(data.get("ts") or "")

    return {
        "message_id": ts,
        "sent_at": sent_at,
        "detail": f"posted to {channel_id}",
    }


def _error(detail: str) -> dict[str, Any]:
    return {
        "message_id": "",
        "sent_at": "",
        "detail": detail,
    }
