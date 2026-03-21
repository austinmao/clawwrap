"""OpenClaw handler binding: dm.send_via_gateway.

Sends a WhatsApp DM through OpenClaw's native gateway channel — the production
send path used by all agents (e.g. post-call-whatsapp skill action object).

This is the correct handler to use for production clawwrap E2E tests.
It calls: openclaw message send --channel whatsapp --target <E.164> --message <text> --json

NOTE: The `dm.send_text` handler (wacli) is kept for identity verification workflows
but is NOT the production send path. Use this handler for outbound message tests.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from clawwrap.engine.rate_limit import RateLimitError, RateLimitGuard
from clawwrap.handlers.registry import handler

_OPENCLAW_TIMEOUT_SEC: int = 30
_MAX_OUTPUT_BYTES: int = 4096

# Matches s.whatsapp.net JID → extracts number for E.164 conversion
_JID_RE = re.compile(r"^(\d+)@s\.whatsapp\.net$")

_guard = RateLimitGuard()  # module-level; shares lockfile with dm_send


def _jid_to_e164(jid: str) -> str:
    """Convert a WhatsApp DM JID to E.164 phone number.

    Args:
        jid: JID like 13033324741@s.whatsapp.net or E.164 like +13033324741.

    Returns:
        E.164 string (e.g. +13033324741).

    Raises:
        ValueError: If the input cannot be converted.
    """
    jid = jid.strip()
    if jid.startswith("+"):
        return jid  # Already E.164
    m = _JID_RE.match(jid)
    if m:
        return f"+{m.group(1)}"
    raise ValueError(f"Cannot convert to E.164: {jid!r}")


@handler("dm.send_via_gateway", adapter_name="openclaw")
def send_via_gateway(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send a WhatsApp DM via OpenClaw's native gateway channel.

    This is the production send path. Agents use the equivalent action object:
        {"action": "send", "channel": "whatsapp", "target": "<JID>", "message": "..."}

    Contract inputs:
        normalized_jid (str): Validated JID (13033324741@s.whatsapp.net) or E.164.
        message (str): Message body.
        dry_run (bool, optional): When True, passes --dry-run to openclaw CLI (default False).

    Contract outputs:
        message_id (str): Gateway-assigned message ID.
        sent_at (str): ISO 8601 UTC timestamp of send.
        rate_limit_applied (bool): True when rate guard delay was applied.
        dry_run (bool): Echoes the dry_run flag.
        channel (str): Always "whatsapp".
        detail (str): Human-readable result.
    """
    jid: str = str(inputs.get("normalized_jid", ""))
    message: str = str(inputs.get("message", ""))
    dry_run: bool = bool(inputs.get("dry_run", False))

    if not jid:
        return _error("normalized_jid is required")
    if not message:
        return _error("message is required")

    try:
        e164 = _jid_to_e164(jid)
    except ValueError as exc:
        return _error(f"JID conversion failed: {exc}")

    # Rate limit check — raises RateLimitError on violation.
    try:
        check = _guard.check_and_record(dry_run=dry_run)
    except RateLimitError as exc:
        return _error(f"rate limit: {exc}")

    # Human jitter delay.
    time.sleep(check.jitter_seconds)

    sent_at = datetime.now(tz=timezone.utc).isoformat()

    cmd = [
        "openclaw", "message", "send",
        "--channel", "whatsapp",
        "--target", e164,
        "--message", message,
        "--json",
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            timeout=_OPENCLAW_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return _error("openclaw CLI not found")
    except subprocess.TimeoutExpired:
        return _error(f"openclaw timed out after {_OPENCLAW_TIMEOUT_SEC}s")
    except OSError as exc:
        return _error(f"openclaw OS error: {exc}")

    stdout = result.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        stderr = result.stderr[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
        return _error(f"openclaw exit {result.returncode}: {stderr or stdout}")

    message_id = _extract_message_id(stdout)
    return {
        "message_id": message_id,
        "sent_at": sent_at,
        "rate_limit_applied": True,
        "dry_run": dry_run,
        "channel": "whatsapp",
        "detail": f"sent via gateway to {e164}; message_id={message_id}",
    }


def _extract_message_id(stdout: str) -> str:
    """Extract message ID from openclaw JSON output."""
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return str(
                data.get("id") or data.get("messageId") or data.get("message_id") or ""
            )
    except (json.JSONDecodeError, KeyError):
        pass
    return stdout[:64]


def _error(detail: str) -> dict[str, Any]:
    return {
        "message_id": "",
        "sent_at": "",
        "rate_limit_applied": False,
        "dry_run": False,
        "channel": "whatsapp",
        "detail": detail,
    }
