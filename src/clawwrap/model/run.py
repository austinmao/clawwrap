"""Run and StageTransition dataclasses — Postgres-persisted runtime state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from clawwrap.model.types import RunPhase, RunStatus


@dataclass
class Run:
    """Runtime state for a single wrapper run, stored in Postgres."""

    id: uuid.UUID
    wrapper_name: str
    wrapper_version: str
    adapter_name: str
    current_phase: RunPhase
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    resolved_inputs: dict[str, Any] | None = None

    @classmethod
    def new(
        cls,
        wrapper_name: str,
        wrapper_version: str,
        adapter_name: str,
    ) -> Run:
        """Create a new Run in pending status."""
        now = datetime.now(UTC)
        return cls(
            id=uuid.uuid4(),
            wrapper_name=wrapper_name,
            wrapper_version=wrapper_version,
            adapter_name=adapter_name,
            current_phase=RunPhase.resolve,
            status=RunStatus.pending,
            created_at=now,
            updated_at=now,
            resolved_inputs=None,
        )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Run:
        """Construct a Run from a Postgres row dict."""
        return cls(
            id=uuid.UUID(str(row["id"])),
            wrapper_name=str(row["wrapper_name"]),
            wrapper_version=str(row["wrapper_version"]),
            adapter_name=str(row["adapter_name"]),
            current_phase=RunPhase(row["current_phase"]),
            status=RunStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_inputs=row.get("resolved_inputs"),
        )


@dataclass
class StageTransition:
    """Immutable log entry recording a phase transition for a run."""

    id: uuid.UUID
    run_id: uuid.UUID
    to_phase: RunPhase
    transitioned_at: datetime
    from_phase: RunPhase | None = None
    evidence: dict[str, Any] | None = None

    @classmethod
    def new(
        cls,
        run_id: uuid.UUID,
        to_phase: RunPhase,
        from_phase: RunPhase | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> StageTransition:
        """Create a new StageTransition."""
        return cls(
            id=uuid.uuid4(),
            run_id=run_id,
            to_phase=to_phase,
            transitioned_at=datetime.now(UTC),
            from_phase=from_phase,
            evidence=evidence,
        )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StageTransition:
        """Construct a StageTransition from a Postgres row dict."""
        from_phase_raw = row.get("from_phase")
        return cls(
            id=uuid.UUID(str(row["id"])),
            run_id=uuid.UUID(str(row["run_id"])),
            to_phase=RunPhase(row["to_phase"]),
            transitioned_at=row["transitioned_at"],
            from_phase=RunPhase(from_phase_raw) if from_phase_raw else None,
            evidence=row.get("evidence"),
        )
