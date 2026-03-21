"""OpenClaw handler binding: dm.verify_receipt.

Polls wacli messages list to confirm a sent DM appears in the local store.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from clawwrap.handlers.registry import handler

_POLL_INTERVAL_SEC: int = 10
_POLL_MAX_ATTEMPTS: int = 3
_WACLI_TIMEOUT_SEC: int = 15
_MAX_OUTPUT_BYTES: int = 32768


@handler("dm.verify_receipt", adapter_name="openclaw")
def verify_receipt(inputs: dict[str, Any]) -> dict[str, Any]:
    """Poll wacli to verify a sent message appears in the local store.

    Polls up to 3 times at 10-second intervals (30s total).

    Contract inputs:
        normalized_jid (str): JID of the chat to search.
        message_id (str): Expected message ID (used for exact match if available).
        sent_at (str): ISO 8601 UTC timestamp; only messages after this are considered.
        dry_run (bool, optional): Skip actual polling, return mock success.

    Contract outputs:
        verified (bool): True when message was found in local store.
        round_trip_ms (int): Milliseconds from sent_at to verification.
        attempts (int): Number of poll attempts made.
        detail (str): Human-readable result.
    """
    jid: str = str(inputs.get("normalized_jid", ""))
    message_id: str = str(inputs.get("message_id", ""))
    sent_at_str: str = str(inputs.get("sent_at", ""))
    dry_run: bool = bool(inputs.get("dry_run", False))

    if not jid:
        return _result(False, 0, 0, "normalized_jid is required")

    if dry_run:
        return _result(True, 1, 42, "dry_run: verification skipped")

    sent_ts = _parse_ts(sent_at_str)

    for attempt in range(1, _POLL_MAX_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(_POLL_INTERVAL_SEC)

        messages = _fetch_messages(jid, since=sent_at_str)
        if messages is None:
            continue  # wacli error; try again

        if _find_message(messages, message_id):
            now_ms = int(time.time() * 1000)
            sent_ms = int(sent_ts * 1000) if sent_ts else now_ms
            return _result(True, attempt, now_ms - sent_ms, f"found after {attempt} attempt(s)")

    return _result(False, _POLL_MAX_ATTEMPTS, 0, "message not found after 3 poll attempts")


def _fetch_messages(jid: str, since: str) -> list[dict[str, Any]] | None:
    """Call wacli messages list and return parsed JSON, or None on error."""
    cmd = ["wacli", "messages", "list", "--chat", jid, "--json", "--limit", "10"]
    if since:
        cmd += ["--after", since[:10]]  # wacli accepts YYYY-MM-DD

    try:
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, timeout=_WACLI_TIMEOUT_SEC
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None

    stdout = result.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(stdout)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return None


def _find_message(messages: list[dict[str, Any]], message_id: str) -> bool:
    """Return True when message_id matches any item, or any message is present."""
    if not messages:
        return False
    if not message_id:
        return True  # Any new message counts as confirmation
    return any(
        str(m.get("id") or m.get("message_id") or "") == message_id
        for m in messages
    )


def _parse_ts(iso_str: str) -> float:
    """Parse ISO 8601 string to unix timestamp, or return 0.0 on error."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _result(verified: bool, attempts: int, round_trip_ms: int, detail: str) -> dict[str, Any]:
    return {
        "verified": verified,
        "round_trip_ms": round_trip_ms,
        "attempts": attempts,
        "detail": detail,
    }
