"""Domain objects for the outbound gate.

Defines the canonical shapes used throughout the gate pipeline:
OutboundRequest, GateVerdict, CheckResult, ResolvedContext.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class OutboundRequest:
    """Canonical shape submitted by every skill before any outbound send."""

    route_mode: str  # "shared" | "direct"
    channel: str  # "whatsapp" | "email" | "imessage" | "sms" | "mailchimp"
    message: str
    requested_by: str  # skill name, e.g. "post-call-whatsapp"
    context_key: str | None = None  # for shared routes
    audience: str | None = None  # for shared routes
    recipient_ref: str | None = None  # for direct routes
    dry_run: bool = False
    payload: dict[str, Any] | None = None

    def validate(self) -> str | None:
        """Return an error message if inputs are invalid, else None."""
        if self.route_mode not in ("shared", "direct"):
            return f"route_mode must be 'shared' or 'direct', got {self.route_mode!r}"
        if self.route_mode == "shared":
            if not self.context_key:
                return "shared route requires context_key"
            if not self.audience:
                return "shared route requires audience"
        if self.route_mode == "direct":
            if not self.recipient_ref:
                return "direct route requires recipient_ref"
        if not self.channel:
            return "channel is required"
        if not self.message:
            return "message is required"
        if not self.requested_by:
            return "requested_by is required"
        return None


@dataclass
class CheckResult:
    """One evaluation within the verify stage."""

    name: str  # e.g. "target_exists"
    passed: bool
    detail: str  # human-readable


@dataclass
class ResolvedContext:
    """Internal state passed between pipeline stages."""

    target: str | list[str] | None
    audience_label: str
    expected_identity: dict[str, Any] | None
    allowlist_key: str
    verification_supported: bool
    live_identity_match: bool | None = None
    live_identity: dict[str, Any] | None = None


@dataclass
class GateVerdict:
    """Structured result returned from the gate pipeline."""

    allowed: bool
    request_id: str
    target: str | list[str] | None
    audience_label: str
    channel: str
    requested_by: str
    verification_supported: bool
    live_identity: dict[str, Any] | None
    checks: list[CheckResult]
    denied_by: str | None
    reason: str
    timestamp: str
    send_result: dict[str, Any] | list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for YAML logging and handler return."""
        return {
            "allowed": self.allowed,
            "request_id": self.request_id,
            "target": self.target,
            "audience_label": self.audience_label,
            "channel": self.channel,
            "requested_by": self.requested_by,
            "verification_supported": self.verification_supported,
            "live_identity": self.live_identity,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
            "denied_by": self.denied_by,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "send_result": self.send_result,
        }


def make_request_id() -> str:
    """Generate a unique request ID for audit trail."""
    ts = int(time.time())
    short = uuid.uuid4().hex[:4]
    return f"gate-{ts}-{short}"


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()
