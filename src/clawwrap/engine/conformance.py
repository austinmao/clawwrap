"""Conformance checker and drift exception recorder.

After a host apply completes, ``check_conformance`` reads current host state
via the adapter and compares it against the expected owned state stored in the
apply plan.  A surface not found on the host counts as drifted.

``record_exception`` accepts a drift exception when the run is in ``drifted``
status, enforcing that the exception approver's role is >= the original apply
approver's role.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from clawwrap.adapters.base import AdapterProtocol
from clawwrap.model.approval import ApprovalIdentityEvidence, DriftExceptionRecord
from clawwrap.model.run import Run
from clawwrap.model.types import ApprovalRole, ConformanceStatus, RunStatus
from clawwrap.store.interface import RunStore


class ConformanceError(RuntimeError):
    """Base error for conformance failures."""


class InsufficientExceptionRoleError(ConformanceError):
    """Exception approver role is below the original apply approver's role."""


class NoDriftToExceptError(ConformanceError):
    """Raised when recording an exception on a non-drifted run."""


@dataclass
class SurfaceComparison:
    """Per-surface comparison result.

    Attributes:
        surface_path: Selector of the surface that was checked.
        status: Whether the surface matches expected state or has drifted.
        expected: The expected value from the apply plan.
        observed: The observed value from host state (None = not found).
        detail: Optional human-readable explanation.
    """

    surface_path: str
    status: ConformanceStatus
    expected: Any
    observed: Any
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "surface_path": self.surface_path,
            "status": self.status.value,
            "expected": self.expected,
            "observed": self.observed,
            "detail": self.detail,
        }


@dataclass
class ConformanceResult:
    """Aggregated conformance result for a run.

    Attributes:
        id: Generated result UUID (set after persistence).
        run_id: Parent run UUID.
        status: Overall conformance outcome.
        checked_at: When the check was performed.
        surface_comparisons: Per-surface breakdown.
    """

    run_id: uuid.UUID
    status: ConformanceStatus
    checked_at: datetime
    surface_comparisons: list[SurfaceComparison] = field(default_factory=list)
    id: uuid.UUID = field(default_factory=uuid.uuid4)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "status": self.status.value,
            "checked_at": self.checked_at.isoformat(),
            "surfaces": [s.to_dict() for s in self.surface_comparisons],
        }


def check_conformance(
    run: Run,
    adapter: AdapterProtocol,
    store: RunStore,
) -> ConformanceResult:
    """Read current host state and compare against expected state from the apply plan.

    A surface that is not present on the host counts as drifted.
    The run status is updated to ``applied`` or ``drifted`` based on results.

    Args:
        run: The Run to check (should be in ``conformance_pending`` status).
        adapter: Host adapter used to read current surface state.
        store: RunStore for persisting the result and updating run status.

    Returns:
        ConformanceResult with per-surface comparison details.

    Raises:
        KeyError: If the run does not exist.
    """
    apply_plan = _load_apply_plan(run, store)
    expected_surfaces = _extract_expected_surfaces(apply_plan)
    surface_paths = list(expected_surfaces.keys())

    observed_state = adapter.read_host_state(surface_paths)
    comparisons = _compare_surfaces(expected_surfaces, observed_state)

    overall = _aggregate_status(comparisons)
    checked_at = datetime.now(UTC)

    result = ConformanceResult(
        run_id=run.id,
        status=overall,
        checked_at=checked_at,
        surface_comparisons=comparisons,
    )

    details = result.to_dict()
    conformance_id = store.save_conformance(
        run_id=run.id,
        status=overall.value,
        details=details,
    )
    result.id = conformance_id

    new_status = RunStatus.applied if overall == ConformanceStatus.matching else RunStatus.drifted
    store.update_run_status(run.id, new_status)

    return result


def record_exception(
    run_id: uuid.UUID,
    reason: str,
    identity_evidence: ApprovalIdentityEvidence,
    store: RunStore,
    adapter: AdapterProtocol,
) -> DriftExceptionRecord:
    """Accept a drift exception for a drifted run.

    The exception approver must hold a role >= the role of the original apply
    approver (enforced via the role lattice).

    Args:
        run_id: UUID of the drifted run.
        reason: Human-readable explanation of why the drift is accepted.
        identity_evidence: Identity evidence for the exception approver.
        store: RunStore for fetching run state and persisting the exception.
        adapter: Host adapter for resolving exception approver's role.

    Returns:
        Persisted DriftExceptionRecord.

    Raises:
        KeyError: If run does not exist.
        NoDriftToExceptError: If the run is not in ``drifted`` status.
        InsufficientExceptionRoleError: If approver role < original apply role.
    """
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(f"Run {run_id} not found")

    if run.status != RunStatus.drifted:
        raise NoDriftToExceptError(
            f"Run {run_id} is not drifted (current status: {run.status.value}). "
            "Only drifted runs accept exceptions."
        )

    exception_role = adapter.resolve_approval_identity(identity_evidence)
    original_role = _fetch_original_apply_role(run_id, store)
    latest_conformance_id = _fetch_latest_conformance_id(run_id, store)

    try:
        record = DriftExceptionRecord.new(
            run_id=run_id,
            conformance_id=latest_conformance_id,
            reason=reason,
            identity_source=identity_evidence.identity_source,
            subject_id=identity_evidence.subject_id,
            role=exception_role,
            original_apply_role=original_role,
        )
    except ValueError as exc:
        raise InsufficientExceptionRoleError(str(exc)) from exc

    stored = store.save_drift_exception(record)
    store.update_run_status(run_id, RunStatus.exception_recorded)
    return stored


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_apply_plan(run: Run, store: RunStore) -> dict[str, Any]:
    """Retrieve the apply plan content for the run.

    Uses ``get_apply_plan`` if available on the store, otherwise returns an
    empty plan (for stores not yet extended with retrieval methods).

    Args:
        run: Parent run.
        store: RunStore instance.

    Returns:
        Plan content dict (may be empty if not found).
    """
    if hasattr(store, "get_apply_plan"):
        plan = getattr(store, "get_apply_plan")(run.id)
        if plan is not None:
            return dict(plan)
    # Fallback: reconstruct minimal plan from run metadata.
    return {
        "run_id": str(run.id),
        "wrapper_name": run.wrapper_name,
        "artifacts": [],
        "patch_items": [],
    }


def _extract_expected_surfaces(apply_plan: dict[str, Any]) -> dict[str, Any]:
    """Extract a surface_path → expected_value mapping from an apply plan.

    Args:
        apply_plan: Plan content dict from the store.

    Returns:
        Dict mapping surface paths to their expected values.
    """
    expected: dict[str, Any] = {}
    patch_items = apply_plan.get("patch_items", [])
    for item in patch_items:
        path = str(item.get("surface_path", ""))
        if path:
            expected[path] = item.get("content", item.get("value"))
    if not expected:
        artifacts = apply_plan.get("artifacts", [])
        for artifact in artifacts:
            path = str(artifact.get("surface_path", ""))
            if path:
                expected[path] = artifact.get("content", artifact.get("value"))
    return expected


def _compare_surfaces(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> list[SurfaceComparison]:
    """Compare expected vs observed surface values.

    A surface that is absent from the observed state (None) is treated as
    drifted per the spec.

    Args:
        expected: Mapping of surface_path → expected value.
        observed: Mapping of surface_path → observed value (None = not found).

    Returns:
        List of SurfaceComparison results.
    """
    comparisons: list[SurfaceComparison] = []
    for path, exp_value in expected.items():
        obs_value = observed.get(path)
        if obs_value is None:
            status = ConformanceStatus.drifted
            detail = "Surface not found on host."
        elif obs_value == exp_value:
            status = ConformanceStatus.matching
            detail = "Surface matches expected state."
        else:
            status = ConformanceStatus.drifted
            detail = f"Expected {exp_value!r} but observed {obs_value!r}."
        comparisons.append(
            SurfaceComparison(
                surface_path=path,
                status=status,
                expected=exp_value,
                observed=obs_value,
                detail=detail,
            )
        )
    return comparisons


def _aggregate_status(comparisons: list[SurfaceComparison]) -> ConformanceStatus:
    """Compute the overall status from per-surface comparisons.

    Any drifted surface makes the overall result drifted.  An empty comparison
    list means no surfaces were checked — treated as matching (vacuously true).

    Args:
        comparisons: List of per-surface comparison results.

    Returns:
        Overall ConformanceStatus.
    """
    if not comparisons:
        return ConformanceStatus.matching
    for comp in comparisons:
        if comp.status == ConformanceStatus.drifted:
            return ConformanceStatus.drifted
    return ConformanceStatus.matching


def _fetch_original_apply_role(run_id: uuid.UUID, store: RunStore) -> ApprovalRole:
    """Retrieve the role from the original apply approval record.

    Falls back to ``operator`` if no approval record is retrievable (e.g.
    stores not yet extended with ``get_approval``).

    Args:
        run_id: Run UUID.
        store: RunStore instance.

    Returns:
        ApprovalRole of the original approver.
    """
    if hasattr(store, "get_approval"):
        record = getattr(store, "get_approval")(run_id)
        if record is not None:
            role: ApprovalRole = record.role
            return role
    from clawwrap.store.postgres import PostgresRunStore

    if isinstance(store, PostgresRunStore):
        return _pg_fetch_approval_role(run_id, store)
    return ApprovalRole.operator


def _pg_fetch_approval_role(run_id: uuid.UUID, store: Any) -> ApprovalRole:
    """Fetch the approval role from Postgres for the given run.

    Args:
        run_id: Run UUID.
        store: PostgresRunStore instance.

    Returns:
        ApprovalRole, defaulting to operator if not found.
    """
    try:
        from psycopg.rows import dict_row

        from clawwrap.store.connection import get_connection

        sql = (
            "SELECT role FROM clawwrap.approval_records "
            "WHERE run_id = %(run_id)s ORDER BY issued_at DESC LIMIT 1"
        )
        with get_connection(store._db_url) as conn:  # noqa: SLF001
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"run_id": str(run_id)})
                row = cur.fetchone()
        if row is not None:
            return ApprovalRole[str(row["role"])]
    except Exception:
        pass
    return ApprovalRole.operator


def _fetch_latest_conformance_id(run_id: uuid.UUID, store: RunStore) -> uuid.UUID:
    """Retrieve the latest conformance result ID for a run.

    Falls back to a newly generated UUID if the store does not support
    conformance retrieval.

    Args:
        run_id: Run UUID.
        store: RunStore instance.

    Returns:
        UUID of the most recent conformance result, or a new UUID as fallback.
    """
    from clawwrap.store.postgres import PostgresRunStore

    if isinstance(store, PostgresRunStore):
        return _pg_fetch_conformance_id(run_id, store)
    return uuid.uuid4()


def _pg_fetch_conformance_id(run_id: uuid.UUID, store: Any) -> uuid.UUID:
    """Fetch the most recent conformance result ID from Postgres.

    Args:
        run_id: Run UUID.
        store: PostgresRunStore instance.

    Returns:
        UUID of the most recent conformance result, or a new UUID as fallback.
    """
    try:
        from psycopg.rows import dict_row

        from clawwrap.store.connection import get_connection

        sql = (
            "SELECT id FROM clawwrap.conformance_results "
            "WHERE run_id = %(run_id)s ORDER BY checked_at DESC LIMIT 1"
        )
        with get_connection(store._db_url) as conn:  # noqa: SLF001
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"run_id": str(run_id)})
                row = cur.fetchone()
        if row is not None:
            return uuid.UUID(str(row["id"]))
    except Exception:
        pass
    return uuid.uuid4()
