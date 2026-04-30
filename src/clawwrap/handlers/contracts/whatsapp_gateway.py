"""WhatsApp gateway channel handler — outbound WA via openclaw gateway RPC.

Registered as ``whatsapp.send_gateway``. Replaces the wacli-based
``dm_send_via_gateway`` for the spec 085 unified gate pipeline.

Transport choice: the openclaw gateway CLI (``openclaw gateway call send``)
invoked via ``subprocess.run`` with a 90s timeout. The gateway exposes the
``send`` RPC over WebSocket, but reusing the CLI keeps clawwrap dep-free
(no ``websocket-client`` requirement) and preserves the 90s timeout that
the CLI's ``openclaw message send`` bug truncated to 10s.

Escape-hatch guard mirrors bluebubbles — handlers must be entered via
``outbound.submit`` unless ``CLAWWRAP_EMERGENCY=1``.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawwrap.engine.rate_limit import EscapeHatchError
from clawwrap.gate import _gate_context
from clawwrap.handlers.contracts.errors import DispatchError
from clawwrap.handlers.registry import handler

logger = logging.getLogger(__name__)

_EMERGENCY_LOG_DIR = Path("memory") / "logs" / "outbound"
_SUBPROCESS_TIMEOUT_SECONDS = 90.0
_SUBPROCESS_TIMEOUT_MS = int(_SUBPROCESS_TIMEOUT_SECONDS * 1000)
_MAX_OUTPUT_BYTES = 16384


@handler("whatsapp.send_gateway", adapter_name="openclaw")
def send(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send a WhatsApp message via the local openclaw gateway.

    Args:
        inputs: Dict with keys ``to`` (E.164 or JID), ``message`` (body),
            and optional ``idempotencyKey`` (auto-generated if missing).

    Returns:
        ``{"messageId": str, "channel": "whatsapp", "toJid": str, "status": "sent"}``.

    Raises:
        EscapeHatchError: If called outside the gate context without
            ``CLAWWRAP_EMERGENCY=1``.
        DispatchError: If ``to`` is missing, the gateway returns unauthorized
            or any non-zero exit, or the subprocess times out.
    """
    target = str(inputs.get("to", "")).strip()
    message = str(inputs.get("message", ""))
    idempotency_key = str(inputs.get("idempotencyKey") or uuid.uuid4())

    if not target:
        raise DispatchError("whatsapp.send_gateway: 'to' is required")

    _enforce_escape_hatch(target)

    cmd = [
        "openclaw",
        "gateway",
        "call",
        "--timeout",
        str(_SUBPROCESS_TIMEOUT_MS),
        "--json",
        "send",
        "--channel",
        "whatsapp",
        "--to",
        target,
        "--message",
        message,
        "--idempotencyKey",
        idempotency_key,
    ]

    try:
        result = subprocess.run(  # noqa: S603 — cmd is a fixed list, no shell
            cmd,
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DispatchError(
            f"whatsapp gateway: timed out after {_SUBPROCESS_TIMEOUT_SECONDS:.0f}s"
        ) from exc
    except FileNotFoundError as exc:
        raise DispatchError("whatsapp gateway: openclaw CLI not found on PATH") from exc
    except OSError as exc:
        raise DispatchError(f"whatsapp gateway: OS error: {exc}") from exc

    stdout = result.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
    stderr = result.stderr[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        combined = stderr or stdout
        if "unauthorized" in combined.lower():
            raise DispatchError(f"whatsapp gateway: unauthorized — {combined}")
        raise DispatchError(
            f"whatsapp gateway: exit {result.returncode} — {combined}"
        )

    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        raise DispatchError(
            f"whatsapp gateway: response not JSON: {stdout[:200]!r}"
        ) from exc

    if not isinstance(payload, dict) or not payload:
        raise DispatchError(f"whatsapp gateway: malformed response: {payload!r}")

    message_id = str(
        payload.get("id")
        or payload.get("messageId")
        or payload.get("message_id")
        or ""
    )
    if not message_id:
        raise DispatchError(f"whatsapp gateway: response missing messageId: {payload!r}")

    to_jid = str(payload.get("toJid") or payload.get("to_jid") or _derive_jid(target))
    status = str(payload.get("status") or "sent")

    return {
        "messageId": message_id,
        "channel": "whatsapp",
        "toJid": to_jid,
        "status": status,
    }


def _enforce_escape_hatch(target: str) -> None:
    active = getattr(_gate_context, "active", False)
    if active:
        return
    if os.environ.get("CLAWWRAP_EMERGENCY") != "1":
        raise EscapeHatchError()
    _log_emergency_bypass(target)


def _log_emergency_bypass(target: str) -> None:
    """Append a WARN line to today's emergency log. Best-effort."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    redacted = _redact_target(target)
    line = (
        f"[WARN] {timestamp} CLAWWRAP_EMERGENCY override — "
        f"direct whatsapp.send_gateway called outside outbound.submit; "
        f"target={redacted}\n"
    )
    try:
        _EMERGENCY_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _EMERGENCY_LOG_DIR / f"emergency-{date_stamp}.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.warning("whatsapp_gateway: could not write emergency log (best-effort)")


def _redact_target(target: str) -> str:
    if not target:
        return "<unknown>"
    if len(target) <= 6:
        return target[:3] + "***"
    return target[:6] + "***"


def _derive_jid(target: str) -> str:
    """Best-effort E.164 → WA JID guess (used only if gateway omits toJid).

    WA JIDs use the bare number (no ``+``) followed by ``@s.whatsapp.net``.
    """
    phone = target.lstrip("+").strip()
    if not phone.isdigit():
        return target
    return f"{phone}@s.whatsapp.net"


__all__ = ["send"]
