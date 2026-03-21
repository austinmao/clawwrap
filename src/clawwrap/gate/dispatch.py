"""Outbound gate — channel dispatch.

Routes outbound sends to the correct channel-specific handler.
Internal module called by outbound.submit, not a registered handler.
"""
from __future__ import annotations

from typing import Any

# Channel → default handler ID mapping.
_CHANNEL_HANDLERS: dict[str, str] = {
    "email": "email.send",
    "slack": "slack.post",
    "mailchimp": "mailchimp.send_campaign",
}

_UNIMPLEMENTED_CHANNELS: set[str] = {"imessage", "sms", "telegram"}


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
        return handler({
            "normalized_jid": target,
            "message": message,
            "dry_run": False,
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
    elif channel == "mailchimp":
        if not payload:
            return {
                "message_id": "",
                "sent_at": "",
                "detail": "mailchimp channel requires a payload dict",
            }
        import os
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


def _select_handler_id(channel: str, target: str) -> str | None:
    if channel == "whatsapp":
        if target.endswith("@g.us"):
            return "dm.send_text"
        return "dm.send_via_gateway"
    return _CHANNEL_HANDLERS.get(channel)
