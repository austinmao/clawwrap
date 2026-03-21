"""OpenClaw handler binding: slack.channel_info.

Fetches Slack channel metadata and verifies the channel name matches
an expected value. Used by the outbound gate's live identity verification.

Requires env var: SLACK_BOT_TOKEN
API: POST https://slack.com/api/conversations.info
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from clawwrap.handlers.registry import handler

_SLACK_CONVERSATIONS_INFO_URL: str = "https://slack.com/api/conversations.info"
_TIMEOUT_SEC: int = 10


@handler("slack.channel_info", adapter_name="openclaw")
def slack_channel_info(inputs: dict[str, Any]) -> dict[str, Any]:
    """Fetch channel info and verify the channel name matches expected_name.

    Contract inputs:
        channel_id (str): Slack channel ID (e.g. "C0123456789").
        expected_name (str): Expected channel display name.

    Contract outputs:
        matched (bool): True when channel name matches expected_name.
        detail (str): Human-readable result or error description.
    """
    channel_id: str = str(inputs.get("channel_id", "")).strip()
    expected_name: str = str(inputs.get("expected_name", "")).strip()

    if not channel_id:
        return {"matched": False, "detail": "channel_id is required"}
    if not expected_name:
        return {"matched": False, "detail": "expected_name is required"}

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return {"matched": False, "detail": "SLACK_BOT_TOKEN env var not set"}

    try:
        resp = httpx.post(
            _SLACK_CONVERSATIONS_INFO_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"channel": channel_id},
            timeout=_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        return {"matched": False, "detail": f"Slack API timed out after {_TIMEOUT_SEC}s"}
    except httpx.RequestError as exc:
        return {"matched": False, "detail": f"Slack request error: {exc}"}

    try:
        data = resp.json()
    except Exception:
        return {"matched": False, "detail": f"Slack HTTP {resp.status_code}: non-JSON response"}

    if not data.get("ok"):
        error_msg = data.get("error", "unknown error")
        return {"matched": False, "detail": f"Slack API error: {error_msg}"}

    channel_data = data.get("channel", {})
    actual_name = str(channel_data.get("name", "")).strip()

    if not actual_name:
        return {"matched": False, "detail": "Slack response did not contain a channel name"}

    if actual_name != expected_name:
        return {"matched": False, "detail": f"expected {expected_name!r}, got {actual_name!r}"}

    return {"matched": True, "detail": f"matched channel name {actual_name!r}"}
