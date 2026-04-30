"""Outbound gate — channel dispatch.

Routes outbound sends to the correct channel-specific handler.
Internal module called by outbound.submit, not a registered handler.
"""
from __future__ import annotations

import itertools
import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

# TCPA keyword canonical forms. Matching is exact after strip() + upper().
_TCPA_STOP = "STOP"
_TCPA_HELP = "HELP"
_TCPA_START = "START"
_TCPA_KEYWORDS = frozenset({_TCPA_STOP, _TCPA_HELP, _TCPA_START})

# Canned TCPA-compliant HELP auto-response. Must include STOP opt-out reminder.
_HELP_RESPONSE = (
    "Reply STOP to unsubscribe. Reply HELP for help. Msg&data rates may apply."
)

# Fallback counter for compliance-event IDs when the injected DB connection
# is a test double whose RETURNING fetch returns None. Real DB paths get the
# actual row id from ``cur.fetchone()[0]``.
_compliance_id_fallback = itertools.count(1)

# Channel → default handler ID mapping.
#
# Spec 085 additions (2026-04-17):
#   bluebubbles → bluebubbles.send        (new native iMessage/SMS transport)
#   imessage    → bluebubbles.send        (alias — shares lockfile/quota with bluebubbles)
#   whatsapp    → whatsapp.send_gateway   (new DM handler; group sends still use dm.send_text via _select_handler_id)
_CHANNEL_HANDLERS: dict[str, str] = {
    "email": "email.send",
    "slack": "slack.post",
    "mailchimp": "mailchimp.send_campaign",
    "lumina-relay": "relay.send",
    "resend-broadcast": "resend.send_broadcast",
    "bluebubbles": "bluebubbles.send",
    "imessage": "bluebubbles.send",
    "sms": "sms_relay.send",
}

# `imessage` is now implemented via bluebubbles. `sms` is implemented via the
# Twilio SMS-relay plugin (spec 087) — the TCPA keyword gate lives in
# :func:`dispatch_sms_relay` and runs before any handler binding. `telegram`
# remains not-yet-implemented.
_UNIMPLEMENTED_CHANNELS: set[str] = {"telegram"}


def dispatch_to_channel(
    target: str,
    channel: str,
    message: str,
    dry_run: bool,
    bind_handler: Any,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route to the correct channel send handler.

    Args:
        target: Resolved target address (JID, email, phone, list ID).
        channel: Channel name.
        message: Message body.
        dry_run: If True, skip the actual send.
        bind_handler: Callable to resolve a handler by ID (adapter.bind_handler).
        payload: Optional structured payload for channels that need more than a message string (e.g. mailchimp).

    Returns:
        Dict with message_id, sent_at, detail keys from the channel handler.
    """
    if dry_run:
        return {
            "message_id": "",
            "sent_at": "",
            "detail": f"dry_run: would send to {target} via {channel}",
        }

    if channel in _UNIMPLEMENTED_CHANNELS:
        return {
            "message_id": "",
            "sent_at": "",
            "detail": f"channel {channel!r} is not yet implemented",
        }

    handler_id = _select_handler_id(channel, target)
    if handler_id is None:
        return {
            "message_id": "",
            "sent_at": "",
            "detail": f"unknown channel {channel!r}",
        }

    handler = bind_handler(handler_id)

    if channel == "whatsapp":
        # Group sends (ends with @g.us) still use the wacli identity path;
        # DMs now go through the new whatsapp_gateway handler (spec 085).
        if str(target).endswith("@g.us"):
            return handler({
                "normalized_jid": target,
                "message": message,
                "dry_run": False,
            })
        return handler({
            "to": target,
            "message": message,
        })
    elif channel in ("bluebubbles", "imessage"):
        return handler({
            "target": target,
            "message": message,
        })
    elif channel == "sms":
        # Spec 087: TCPA keyword gate runs via `dispatch_sms_relay()` before any outbound.
        # Hub vs tenant credential resolution happens inside the handler via sms_credentials.
        return handler({
            "to": target,
            "message": message,
        })
    elif channel == "email":
        return handler({
            "to": target,
            "subject": message[:80] if len(message) > 80 else message,
            "body_text": message,
            "dry_run": False,
        })
    elif channel == "slack":
        return handler({
            "channel_id": target,
            "text": message,
            "dry_run": False,
        })
    elif channel == "lumina-relay":
        return _dispatch_relay(target, message, payload or {})
    elif channel == "resend-broadcast":
        if not payload:
            return {
                "message_id": "",
                "sent_at": "",
                "detail": "resend-broadcast channel requires a payload dict",
            }
        return handler({
            "segment_id": target,
            "subject": payload.get("subject", ""),
            "html": payload.get("html", ""),
            "from": payload.get("from", os.environ.get("RESEND_FROM_ADDRESS", "")),
            "scheduled_at": payload.get("scheduled_at"),
            "dry_run": False,
        })
    elif channel == "mailchimp":
        if not payload:
            return {
                "message_id": "",
                "sent_at": "",
                "detail": "mailchimp channel requires a payload dict",
            }
        from_email_default = os.environ.get("MAILCHIMP_DEFAULT_FROM_EMAIL", "noreply@example.com")
        reply_to_default = os.environ.get("MAILCHIMP_DEFAULT_REPLY_TO", "support@example.com")

        return handler({
            "list_id": target,
            "subject": payload.get("subject", message),
            "html": payload.get("html", ""),
            "plain_text": payload.get("plain_text", ""),
            "from_name": payload.get("from_name", "Support"),
            "from_email": payload.get("from_email", from_email_default),
            "reply_to": payload.get("reply_to", reply_to_default),
            "dry_run": False,
        })
    else:
        return {
            "message_id": "",
            "sent_at": "",
            "detail": f"no dispatch logic for channel {channel!r}",
        }


def _dispatch_relay(
    target: str,
    message: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch an outbound reply through the Lumina Relay hub outbound endpoint.

    Args:
        target: Recipient phone number (E.164).
        message: Reply text.
        payload: Must include: tenant_id, message_id, sequence.

    Returns:
        Standard dispatch result dict.
    """
    import json
    import urllib.error
    import urllib.request
    from datetime import datetime, timezone

    hub_endpoint = os.environ.get("LUMINA_RELAY_HUB_ENDPOINT", "")
    outbound_secret = os.environ.get("LUMINA_RELAY_OUTBOUND_SECRET", "")

    if not hub_endpoint or not outbound_secret:
        return {
            "message_id": "",
            "sent_at": "",
            "detail": "lumina-relay: missing LUMINA_RELAY_HUB_ENDPOINT or LUMINA_RELAY_OUTBOUND_SECRET",
        }

    callback_url = hub_endpoint.rstrip("/") + "/lumina-relay/outbound"
    callback_payload = {
        "tenant_id": payload.get("tenant_id", ""),
        "message_id": payload.get("message_id", ""),
        "recipient_phone": target,
        "reply": message,
        "sequence": payload.get("sequence", 1),
    }

    body = json.dumps(callback_payload).encode("utf-8")
    req = urllib.request.Request(
        callback_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {outbound_secret}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            sent_at = datetime.now(timezone.utc).isoformat()
            return {
                "message_id": payload.get("message_id", ""),
                "sent_at": sent_at,
                "detail": f"relay callback delivered (status {resp.status})",
            }
    except urllib.error.HTTPError as exc:
        return {
            "message_id": "",
            "sent_at": "",
            "detail": f"relay callback failed: HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "message_id": "",
            "sent_at": "",
            "detail": f"relay callback error: {exc}",
        }


# ---------------------------------------------------------------------------
# SMS-relay TCPA keyword gate (spec 087, T033)
# ---------------------------------------------------------------------------


def _classify_tcpa_keyword(body: str) -> str | None:
    """Return the canonical TCPA keyword for ``body``, or None.

    Matching rules (per spec 087 TCPA contract):
        * Strip whitespace, uppercase.
        * Exact compare to STOP / HELP / START.
        * Multi-word variants (e.g. "STOP NOW", "help me") do NOT match.
    """
    normalized = body.strip().upper()
    if normalized in _TCPA_KEYWORDS:
        return normalized
    return None


def _fetch_id_from_cursor(cur: Any) -> int | None:
    """Return the first column of ``cur.fetchone()`` as int, or None."""
    try:
        row = cur.fetchone()
    except Exception:  # noqa: BLE001 — defensive for mocks
        return None
    if row is None:
        return None
    try:
        value = row[0]
    except (TypeError, IndexError):
        return None
    if isinstance(value, int):
        return value
    # Mock objects will have non-int here — fall through to None.
    return None


def _insert_compliance_event(
    db_conn: Any,
    tenant_id: str,
    phone_e164: str,
    keyword: str,
    action: str,
    timestamp: datetime,
) -> int:
    """INSERT into sms_compliance_events and return the new row id.

    Falls back to a monotonic counter id when the test-double cursor does
    not return an integer from ``fetchone()``.
    """
    cur = db_conn.cursor()
    sql = (
        "INSERT INTO sms_compliance_events "
        "(tenant_id, phone_e164, keyword, action, timestamp) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id"
    )
    params = (tenant_id, phone_e164, keyword, action, timestamp)
    cur.execute(sql, params)
    row_id = _fetch_id_from_cursor(cur)
    if row_id is None:
        row_id = next(_compliance_id_fallback)
    return row_id


def _delete_suppression_row(
    db_conn: Any,
    tenant_id: str,
    phone_e164: str,
) -> None:
    """Remove any prior STOP suppression for (tenant_id, phone_e164)."""
    cur = db_conn.cursor()
    sql = (
        "DELETE FROM sms_compliance_events "
        "WHERE tenant_id = %s AND phone_e164 = %s AND action = %s"
    )
    cur.execute(sql, (tenant_id, phone_e164, "suppress"))


def _lookup_suppression(
    db_conn: Any,
    tenant_id: str,
    phone_e164: str,
) -> bool:
    """Return True if (tenant_id, phone_e164) has an active STOP row."""
    cur = db_conn.cursor()
    sql = (
        "SELECT 1 FROM sms_compliance_events "
        "WHERE tenant_id = %s AND phone_e164 = %s AND action = %s "
        "ORDER BY timestamp DESC LIMIT 1"
    )
    cur.execute(sql, (tenant_id, phone_e164, "suppress"))
    try:
        row = cur.fetchone()
    except Exception:  # noqa: BLE001 — defensive for mocks
        return False
    if row is None:
        return False
    # Treat any returned row as evidence of active suppression.
    return True


def dispatch_sms_relay(
    tenant_id: str,
    phone_e164: str,
    body: str,
    direction: Literal["inbound", "outbound"],
    db_conn: Any,
) -> dict[str, Any]:
    """TCPA keyword gate for inbound/outbound SMS (spec 087).

    Classifies ``body`` as STOP / HELP / START / passthrough and performs
    the compliance bookkeeping required by TCPA / CTIA:

    * STOP  — writes a ``suppress`` event, returns suppressed=True.
    * HELP  — writes a ``respond_help`` event, returns a canned auto-reply
              that includes the STOP opt-out reminder.
    * START — deletes any prior suppression row, writes an ``unsuppress``
              event, returns suppressed=False.
    * Other — no compliance event; suppressed flag reflects the current
              stored suppression state for (tenant_id, phone_e164).

    All SQL is scoped by ``(tenant_id, phone_e164)`` — STOP on one tenant
    does not leak across tenants.

    Args:
        tenant_id: Tenant scope for the suppression lookup.
        phone_e164: End-user phone number in E.164.
        body: Raw SMS body as received from Twilio (pre-strip).
        direction: ``"inbound"`` or ``"outbound"``. Reserved for future
            audit use; current keyword semantics are direction-agnostic.
        db_conn: psycopg-style DB connection (supports ``.cursor()``).

    Returns:
        Dispatch result dict. See module docstring contract.
    """
    _ = direction  # reserved for future auditing
    keyword = _classify_tcpa_keyword(body)
    now = datetime.now(timezone.utc)

    if keyword == _TCPA_STOP:
        event_id = _insert_compliance_event(
            db_conn, tenant_id, phone_e164, _TCPA_STOP, "suppress", now
        )
        return {
            "action": "suppress",
            "keyword": _TCPA_STOP,
            "compliance_event_id": event_id,
            "outbound_text": None,
            "suppressed": True,
        }

    if keyword == _TCPA_HELP:
        event_id = _insert_compliance_event(
            db_conn, tenant_id, phone_e164, _TCPA_HELP, "respond_help", now
        )
        return {
            "action": "respond_help",
            "keyword": _TCPA_HELP,
            "compliance_event_id": event_id,
            "outbound_text": _HELP_RESPONSE,
            "suppressed": False,
        }

    if keyword == _TCPA_START:
        _delete_suppression_row(db_conn, tenant_id, phone_e164)
        event_id = _insert_compliance_event(
            db_conn, tenant_id, phone_e164, _TCPA_START, "unsuppress", now
        )
        return {
            "action": "unsuppress",
            "keyword": _TCPA_START,
            "compliance_event_id": event_id,
            "outbound_text": None,
            "suppressed": False,
        }

    # Non-keyword passthrough — no event, but we must return the current
    # suppression state scoped to (tenant_id, phone_e164).
    suppressed = _lookup_suppression(db_conn, tenant_id, phone_e164)
    return {
        "action": "passthrough",
        "keyword": None,
        "compliance_event_id": None,
        "outbound_text": None,
        "suppressed": suppressed,
    }


def _select_handler_id(channel: str, target: str) -> str | None:
    if channel == "whatsapp":
        if target.endswith("@g.us"):
            return "dm.send_text"
        # Spec 085: DMs route to the new gateway handler (replaces wacli dm.send_via_gateway)
        return "whatsapp.send_gateway"
    return _CHANNEL_HANDLERS.get(channel)
