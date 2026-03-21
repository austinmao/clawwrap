"""Shared type definitions for clawwrap: enums and lattice comparisons."""

from __future__ import annotations

import enum


class ApprovalRole(enum.Enum):
    """Role lattice for approval authority: operator < approver < admin."""

    operator = 0
    approver = 1
    admin = 2

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, ApprovalRole):
            return NotImplemented
        return self.value >= other.value

    def __le__(self, other: object) -> bool:
        if not isinstance(other, ApprovalRole):
            return NotImplemented
        return self.value <= other.value

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, ApprovalRole):
            return NotImplemented
        return self.value > other.value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ApprovalRole):
            return NotImplemented
        return self.value < other.value


class RunPhase(enum.Enum):
    """Ordered phases of a wrapper run."""

    resolve = "resolve"
    verify = "verify"
    approve = "approve"
    execute = "execute"
    audit = "audit"


class RunStatus(enum.Enum):
    """All possible run lifecycle statuses."""

    pending = "pending"
    resolving = "resolving"
    verifying = "verifying"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    executing = "executing"
    auditing = "auditing"
    planned = "planned"
    host_apply_in_progress = "host_apply_in_progress"
    conformance_pending = "conformance_pending"
    applied = "applied"
    drifted = "drifted"
    exception_recorded = "exception_recorded"
    failed = "failed"
    cancelled = "cancelled"
    not_checked = "not_checked"


class ConformanceStatus(enum.Enum):
    """Outcome of a post-apply conformance check."""

    matching = "matching"
    drifted = "drifted"
    not_checked = "not_checked"


class SurfaceType(enum.Enum):
    """Types of host surfaces an adapter can own."""

    file = "file"
    config_key = "config_key"
    mapping_entry = "mapping_entry"
    prompt_fragment = "prompt_fragment"


class FailAction(enum.Enum):
    """What a policy check should do on failure."""

    block = "block"
    warn = "warn"
