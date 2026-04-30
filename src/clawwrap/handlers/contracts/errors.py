"""Shared exception types for clawwrap channel handlers.

``DispatchError`` is the common failure signal raised by outbound channel
handlers (bluebubbles, whatsapp_gateway, …) when the underlying transport
refuses or fails the send. Handlers must catch their transport-specific
errors (``requests.HTTPError``, ``requests.Timeout``, WS close codes, etc.)
and re-raise as ``DispatchError`` so ``outbound.submit`` can treat all
dispatch failures uniformly in the audit log.
"""
from __future__ import annotations


class DispatchError(Exception):
    """Raised when a channel handler cannot complete a send.

    Covers: non-2xx HTTP responses, WebSocket auth/timeout failures,
    malformed or empty response bodies, missing required config fields.
    """


__all__ = ["DispatchError"]
