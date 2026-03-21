"""Abstract RunStore interface — all storage backends must implement this."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from clawwrap.model.approval import ApprovalRecord, DriftExceptionRecord
from clawwrap.model.run import Run, StageTransition
from clawwrap.model.types import RunStatus


class RunStore(ABC):
    """Abstract base class for clawwrap run persistence."""

    @abstractmethod
    def create_run(self, run: Run) -> Run:
        """Persist a new Run record and return it."""
        ...

    @abstractmethod
    def get_run(self, run_id: uuid.UUID) -> Run | None:
        """Retrieve a run by ID. Returns None if not found."""
        ...

    @abstractmethod
    def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        wrapper: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Run]:
        """List runs with optional filters. Results are ordered by created_at DESC."""
        ...

    @abstractmethod
    def update_run_status(
        self,
        run_id: uuid.UUID,
        status: RunStatus,
        resolved_inputs: dict[str, Any] | None = None,
    ) -> Run:
        """Update the status (and optionally resolved_inputs) of a run.

        Also updates updated_at. Returns the updated Run.
        Raises KeyError if run_id does not exist.
        """
        ...

    @abstractmethod
    def add_transition(self, transition: StageTransition) -> StageTransition:
        """Append a StageTransition to the immutable log for a run."""
        ...

    @abstractmethod
    def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Persist an approval record (one active approval per run — upsert by run_id)."""
        ...

    @abstractmethod
    def invalidate_approval(
        self,
        run_id: uuid.UUID,
        reason: str,
    ) -> ApprovalRecord:
        """Mark the active approval for a run as invalid.

        Sets valid=False, records invalidated_at and invalidation_reason.
        Raises KeyError if no active approval exists for run_id.
        """
        ...

    @abstractmethod
    def save_apply_plan(
        self,
        run_id: uuid.UUID,
        plan_content: dict[str, Any],
        patch_items: Any,
        ownership_manifest: dict[str, Any],
        approval_hash: str | None = None,
    ) -> uuid.UUID:
        """Persist a semantic apply plan for a run. Returns the plan ID."""
        ...

    @abstractmethod
    def get_apply_plan(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the most recent semantic apply plan for a run, if one exists."""
        ...

    @abstractmethod
    def save_conformance(
        self,
        run_id: uuid.UUID,
        status: str,
        details: dict[str, Any],
    ) -> uuid.UUID:
        """Persist a conformance result for a run. Returns the conformance result ID."""
        ...

    @abstractmethod
    def save_drift_exception(
        self, exception: DriftExceptionRecord
    ) -> DriftExceptionRecord:
        """Persist a drift exception record."""
        ...

    @abstractmethod
    def save_legacy_entry(
        self,
        flow_name: str,
        source_type: str,
        source_path: str,
        expected_status: str,
    ) -> uuid.UUID:
        """Insert or update a legacy authority entry. Returns the entry ID."""
        ...

    @abstractmethod
    def get_legacy_inventory(self, flow_name: str) -> list[dict[str, Any]]:
        """Return all legacy authority entries for the given flow name."""
        ...
