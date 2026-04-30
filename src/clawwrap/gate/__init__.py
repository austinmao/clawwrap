"""Outbound gate — policy-enforced message control plane.

The ``_gate_context`` thread-local acts as a sentinel for the
resolve → verify → dispatch → audit pipeline. ``outbound.submit`` sets
``_gate_context.active = True`` around dispatch. Channel handlers (e.g.
bluebubbles, whatsapp_gateway) check this flag to detect direct calls that
bypass the gate and raise ``EscapeHatchError`` unless ``CLAWWRAP_EMERGENCY=1``
is set in the environment.
"""
from __future__ import annotations

import threading

_gate_context = threading.local()
_gate_context.active = False


__all__ = ["_gate_context"]
