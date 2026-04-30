"""BlueBubbles REST channel handler — outbound iMessage/SMS via BB Server.

Registered as ``bluebubbles.send`` via the handler registry. Intended to be
invoked through ``outbound.submit`` which sets ``_gate_context.active=True``
around the dispatch block.

Escape-hatch guard:
- If ``_gate_context.active`` is ``False`` and ``CLAWWRAP_EMERGENCY`` is not
  set, raises :class:`EscapeHatchError`.
- If ``_gate_context.active`` is ``False`` and ``CLAWWRAP_EMERGENCY=1``, the
  call proceeds but an append-only WARN line is written to
  ``memory/logs/outbound/emergency-YYYY-MM-DD.log`` so ops can audit bypasses.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from clawwrap.engine.rate_limit import EscapeHatchError
from clawwrap.gate import _gate_context
from clawwrap.handlers.contracts.errors import DispatchError
from clawwrap.handlers.registry import handler

logger = logging.getLogger(__name__)

_GATEWAY_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
_EMERGENCY_LOG_DIR = Path("memory") / "logs" / "outbound"
_DEFAULT_ACCOUNT = "austinmao"
_DEFAULT_ACCOUNT_PATH = ("channels", "bluebubbles", "accounts", _DEFAULT_ACCOUNT)
_REQUEST_TIMEOUT_SECONDS = 30.0


@handler("bluebubbles.send", adapter_name="openclaw")
def send(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send an iMessage/SMS via the local BlueBubbles Server REST API.

    Args:
        inputs: Dict with keys ``target`` (E.164 phone number, optionally with
            ``+``), ``message`` (body), and optional ``config`` (dict with
            ``serverUrl``/``password`` to override the gateway config file).

    Returns:
        ``{"messageId": str, "channel": "bluebubbles", "status": "sent"}``.

    Raises:
        EscapeHatchError: If called outside ``outbound.submit`` context and
            ``CLAWWRAP_EMERGENCY`` is not set.
        DispatchError: If BlueBubbles returns non-200, an empty body, or a
            malformed (non-dict) response; also on network timeout/error.
    """
    target = str(inputs.get("target", "")).strip()
    message = str(inputs.get("message", ""))
    config_override = inputs.get("config") if isinstance(inputs.get("config"), dict) else None

    _enforce_escape_hatch(target)

    config = config_override or _load_bluebubbles_config()
    server_url = str(config.get("serverUrl", "")).rstrip("/")
    password = str(config.get("password", ""))
    if not server_url or not password:
        raise DispatchError(
            "bluebubbles: missing serverUrl/password in config (expected at "
            f"channels.bluebubbles.accounts.{_DEFAULT_ACCOUNT})"
        )

    chat_guid = _to_chat_guid(target)
    url = f"{server_url}/api/v1/message/text"
    body = {
        "chatGuid": chat_guid,
        "message": message,
        "method": "apple-script",
    }

    try:
        response = requests.post(
            url,
            params={"password": password},
            json=body,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise DispatchError(f"bluebubbles: request timed out after {_REQUEST_TIMEOUT_SECONDS}s") from exc
    except requests.RequestException as exc:
        raise DispatchError(f"bluebubbles: transport error: {exc}") from exc

    if response.status_code != 200:
        raise DispatchError(
            f"bluebubbles: unexpected HTTP {response.status_code}: {response.text[:200]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise DispatchError(f"bluebubbles: response body not JSON: {response.text[:200]}") from exc

    if not isinstance(payload, dict) or not payload:
        raise DispatchError(f"bluebubbles: malformed response body: {payload!r}")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message_id = str(data.get("guid") or payload.get("messageId") or "")
    if not message_id:
        raise DispatchError(f"bluebubbles: response missing messageId/guid: {payload!r}")

    return {
        "messageId": message_id,
        "channel": "bluebubbles",
        "status": "sent",
    }


def _enforce_escape_hatch(target: str) -> None:
    """Raise EscapeHatchError on direct calls unless CLAWWRAP_EMERGENCY=1.

    When the emergency env var is set, emit a WARN audit line and proceed.
    """
    active = getattr(_gate_context, "active", False)
    if active:
        return

    if os.environ.get("CLAWWRAP_EMERGENCY") != "1":
        raise EscapeHatchError()

    _log_emergency_bypass(target)


def _log_emergency_bypass(target: str) -> None:
    """Append a WARN line to the daily emergency log. Best-effort."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    redacted = _redact_target(target)
    line = (
        f"[WARN] {timestamp} CLAWWRAP_EMERGENCY override — "
        f"direct bluebubbles.send called outside outbound.submit; "
        f"target={redacted}\n"
    )
    try:
        _EMERGENCY_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _EMERGENCY_LOG_DIR / f"emergency-{date_stamp}.log"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        logger.warning("bluebubbles: could not write emergency log (best-effort)")


def _redact_target(target: str) -> str:
    """Keep country code + 3 digits, mask the rest. E.g. +1310*** or +4207***"""
    if not target:
        return "<unknown>"
    if len(target) <= 6:
        return target[:3] + "***"
    return target[:6] + "***"


def _to_chat_guid(target: str) -> str:
    """Normalize an E.164 phone to BlueBubbles chat_guid.

    BB expects ``iMessage;-;+E164`` for 1:1 iMessage chats (service prefix
    ``iMessage`` covers both iMessage and SMS-relay via macOS Messages.app).
    """
    phone = target.strip()
    if not phone.startswith("+"):
        phone = "+" + phone
    return f"iMessage;-;{phone}"


def _load_bluebubbles_config() -> dict[str, Any]:
    """Load serverUrl/password from ~/.openclaw/openclaw.json.

    Returns an empty dict if the file is missing or malformed; the caller
    surfaces a DispatchError with a clear remediation message.
    """
    if not _GATEWAY_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(_GATEWAY_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    node: Any = data
    for key in _DEFAULT_ACCOUNT_PATH:
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
        if node is None:
            return {}
    return node if isinstance(node, dict) else {}


__all__ = ["send"]
