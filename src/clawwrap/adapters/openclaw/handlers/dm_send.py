"""OpenClaw handler binding: dm.send_text.

Sends a single text DM via wacli with rate limit enforcement.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from clawwrap.engine.rate_limit import RateLimitError, RateLimitGuard
from clawwrap.handlers.registry import handler

_WACLI_TIMEOUT_SEC: int = 30
_MAX_OUTPUT_BYTES: int = 4096

_guard = RateLimitGuard()  # module-level; shares lockfile across the process


@handler("dm.send_text", adapter_name="openclaw")
def send_text(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send a text DM via wacli after enforcing rate limits.

    Contract inputs:
        normalized_jid (str): Validated recipient JID.
        message (str): Message body.
        dry_run (bool, optional): When True, skip the actual send (default False).

    Contract outputs:
        message_id (str): wacli message ID (empty on dry_run).
        sent_at (str): ISO 8601 UTC timestamp of send.
        rate_limit_applied (bool): True (a jitter delay was always applied).
        dry_run (bool): Echoes the dry_run flag.
        detail (str): Human-readable result.
    """
    jid: str = str(inputs.get("normalized_jid", ""))
    message: str = str(inputs.get("message", ""))
    dry_run: bool = bool(inputs.get("dry_run", False))

    if not jid:
        return _error("normalized_jid is required")
    if not message:
        return _error("message is required")

    # Rate limit check — raises RateLimitError on violation.
    try:
        check = _guard.check_and_record(dry_run=dry_run)
    except RateLimitError as exc:
        return _error(f"rate limit: {exc}")

    # Human jitter delay — always applied.
    time.sleep(check.jitter_seconds)

    sent_at = datetime.now(tz=timezone.utc).isoformat()

    if dry_run:
        return {
            "message_id": "",
            "sent_at": sent_at,
            "rate_limit_applied": True,
            "dry_run": True,
            "detail": f"dry_run: would send to {jid}; jitter={check.jitter_seconds:.1f}s",
        }

    try:
        result = subprocess.run(  # noqa: S603
            ["wacli", "send", "text", "--to", jid, "--message", message, "--json"],
            capture_output=True,
            timeout=_WACLI_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return _error("wacli binary not found")
    except subprocess.TimeoutExpired:
        return _error(f"wacli timed out after {_WACLI_TIMEOUT_SEC}s")
    except OSError as exc:
        return _error(f"wacli OS error: {exc}")

    stdout = result.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        stderr = result.stderr[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
        return _error(f"wacli exit {result.returncode}: {stderr or stdout}")

    message_id = _extract_message_id(stdout)
    return {
        "message_id": message_id,
        "sent_at": sent_at,
        "rate_limit_applied": True,
        "dry_run": False,
        "detail": f"sent to {jid}; message_id={message_id}",
    }


def _extract_message_id(stdout: str) -> str:
    """Extract message ID from wacli JSON output."""
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return str(data.get("id") or data.get("message_id") or "")
    except (json.JSONDecodeError, KeyError):
        pass
    return stdout[:64]  # Fallback: raw output as ID if JSON parse fails


def _error(detail: str) -> dict[str, Any]:
    return {
        "message_id": "",
        "sent_at": "",
        "rate_limit_applied": False,
        "dry_run": False,
        "detail": detail,
    }
