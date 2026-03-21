"""Global handler contracts — input/output schemas for named check handlers."""

from __future__ import annotations

from clawwrap.handlers.contracts.audit import AUDIT_LOG_RESOLUTION_PATH
from clawwrap.handlers.contracts.group import GROUP_IDENTITY_MATCHES
from clawwrap.handlers.contracts.target import (
    TARGET_RESOLVE_FROM_CANONICAL,
    TARGET_VERIFY_NO_HARDCODED_JID,
)
from clawwrap.model.handler import HandlerContract

#: All globally defined handler contracts, keyed by handler_id.
ALL_CONTRACTS: dict[str, HandlerContract] = {
    GROUP_IDENTITY_MATCHES.handler_id: GROUP_IDENTITY_MATCHES,
    TARGET_RESOLVE_FROM_CANONICAL.handler_id: TARGET_RESOLVE_FROM_CANONICAL,
    TARGET_VERIFY_NO_HARDCODED_JID.handler_id: TARGET_VERIFY_NO_HARDCODED_JID,
    AUDIT_LOG_RESOLUTION_PATH.handler_id: AUDIT_LOG_RESOLUTION_PATH,
}

__all__ = [
    "ALL_CONTRACTS",
    "AUDIT_LOG_RESOLUTION_PATH",
    "GROUP_IDENTITY_MATCHES",
    "TARGET_RESOLVE_FROM_CANONICAL",
    "TARGET_VERIFY_NO_HARDCODED_JID",
]
