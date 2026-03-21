"""Approval dataclasses with SHA-256 hash computation over canonical inputs."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clawwrap.model.types import ApprovalRole


def compute_approval_hash(resolved_inputs: dict[str, Any]) -> str:
    """Compute a stable SHA-256 hash over the canonical JSON of resolved inputs.

    Uses sorted keys and no extra whitespace for determinism.
    """
    canonical = json.dumps(resolved_inputs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ApprovalIdentityEvidence:
    """Identity evidence submitted by an approver."""

    identity_source: str
    subject_id: str
    issued_at: datetime
    trust_basis: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalIdentityEvidence:
        """Construct from a raw dict."""
        issued_at = data["issued_at"]
        if isinstance(issued_at, str):
            issued_at = datetime.fromisoformat(issued_at)
        return cls(
            identity_source=data["identity_source"],
            subject_id=data["subject_id"],
            issued_at=issued_at,
            trust_basis=data["trust_basis"],
        )


@dataclass
class ApprovalRecord:
    """Persisted approval for a run, including role and hash validation state."""

    id: uuid.UUID
    run_id: uuid.UUID
    approval_hash: str
    identity_source: str
    subject_id: str
    issued_at: datetime
    trust_basis: str
    role: ApprovalRole
    valid: bool
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None

    @classmethod
    def new(
        cls,
        run_id: uuid.UUID,
        resolved_inputs: dict[str, Any],
        evidence: ApprovalIdentityEvidence,
        role: ApprovalRole,
    ) -> ApprovalRecord:
        """Create a new ApprovalRecord from identity evidence and resolved inputs."""
        return cls(
            id=uuid.uuid4(),
            run_id=run_id,
            approval_hash=compute_approval_hash(resolved_inputs),
            identity_source=evidence.identity_source,
            subject_id=evidence.subject_id,
            issued_at=evidence.issued_at,
            trust_basis=evidence.trust_basis,
            role=role,
            valid=True,
        )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ApprovalRecord:
        """Construct an ApprovalRecord from a Postgres row dict."""
        return cls(
            id=uuid.UUID(str(row["id"])),
            run_id=uuid.UUID(str(row["run_id"])),
            approval_hash=str(row["approval_hash"]),
            identity_source=str(row["identity_source"]),
            subject_id=str(row["subject_id"]),
            issued_at=row["issued_at"],
            trust_basis=str(row["trust_basis"]),
            role=ApprovalRole[str(row["role"])],
            valid=bool(row["valid"]),
            invalidated_at=row.get("invalidated_at"),
            invalidation_reason=row.get("invalidation_reason"),
        )


@dataclass
class DriftExceptionRecord:
    """Records an accepted drift exception after a conformance failure."""

    id: uuid.UUID
    run_id: uuid.UUID
    conformance_id: uuid.UUID
    reason: str
    identity_source: str
    subject_id: str
    role: ApprovalRole
    original_apply_role: ApprovalRole
    recorded_at: datetime

    @classmethod
    def new(
        cls,
        run_id: uuid.UUID,
        conformance_id: uuid.UUID,
        reason: str,
        identity_source: str,
        subject_id: str,
        role: ApprovalRole,
        original_apply_role: ApprovalRole,
    ) -> DriftExceptionRecord:
        """Create a new DriftExceptionRecord.

        Raises ValueError if role < original_apply_role (lattice constraint).
        """
        if not (role >= original_apply_role):
            raise ValueError(
                f"Exception approver role {role.name!r} must be >= "
                f"original apply role {original_apply_role.name!r}"
            )
        return cls(
            id=uuid.uuid4(),
            run_id=run_id,
            conformance_id=conformance_id,
            reason=reason,
            identity_source=identity_source,
            subject_id=subject_id,
            role=role,
            original_apply_role=original_apply_role,
            recorded_at=datetime.utcnow(),
        )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DriftExceptionRecord:
        """Construct a DriftExceptionRecord from a Postgres row dict."""
        return cls(
            id=uuid.UUID(str(row["id"])),
            run_id=uuid.UUID(str(row["run_id"])),
            conformance_id=uuid.UUID(str(row["conformance_id"])),
            reason=str(row["reason"]),
            identity_source=str(row["identity_source"]),
            subject_id=str(row["subject_id"]),
            role=ApprovalRole[str(row["role"])],
            original_apply_role=ApprovalRole[str(row["original_apply_role"])],
            recorded_at=row["recorded_at"],
        )
