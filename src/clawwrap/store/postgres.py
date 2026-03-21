"""Postgres implementation of the RunStore interface using psycopg (synchronous)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

from clawwrap.model.approval import ApprovalRecord, DriftExceptionRecord
from clawwrap.model.run import Run, StageTransition
from clawwrap.model.types import RunPhase, RunStatus
from clawwrap.store.connection import get_connection
from clawwrap.store.interface import RunStore

SCHEMA = "clawwrap"

_STATUS_TO_PHASE: dict[RunStatus, RunPhase] = {
    RunStatus.pending: RunPhase.resolve,
    RunStatus.resolving: RunPhase.resolve,
    RunStatus.verifying: RunPhase.verify,
    RunStatus.awaiting_approval: RunPhase.approve,
    RunStatus.approved: RunPhase.approve,
    RunStatus.executing: RunPhase.execute,
    RunStatus.auditing: RunPhase.audit,
    RunStatus.planned: RunPhase.audit,
    RunStatus.host_apply_in_progress: RunPhase.audit,
    RunStatus.conformance_pending: RunPhase.audit,
    RunStatus.applied: RunPhase.audit,
    RunStatus.drifted: RunPhase.audit,
    RunStatus.exception_recorded: RunPhase.audit,
    RunStatus.failed: RunPhase.audit,
    RunStatus.cancelled: RunPhase.audit,
}


def _jsonb(value: Any | None) -> str | None:
    """Serialize a JSON-compatible value to a string for psycopg JSONB parameters."""
    if value is None:
        return None
    return json.dumps(value)


class PostgresRunStore(RunStore):
    """Postgres-backed RunStore using psycopg synchronous API.

    All tables are in the ``clawwrap`` schema.  The search_path is set per
    connection by the connection manager, so plain table names are used in
    all SQL statements.
    """

    def __init__(self, db_url: str) -> None:
        """Initialise with a Postgres connection string."""
        self._db_url = db_url

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(self, run: Run) -> Run:
        """Insert a new Run row and return it."""
        sql = """
            INSERT INTO runs (
                id, wrapper_name, wrapper_version, adapter_name,
                current_phase, status, resolved_inputs, created_at, updated_at
            ) VALUES (
                %(id)s, %(wrapper_name)s, %(wrapper_version)s, %(adapter_name)s,
                %(current_phase)s, %(status)s, %(resolved_inputs)s,
                %(created_at)s, %(updated_at)s
            )
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(run.id),
                        "wrapper_name": run.wrapper_name,
                        "wrapper_version": run.wrapper_version,
                        "adapter_name": run.adapter_name,
                        "current_phase": run.current_phase.value,
                        "status": run.status.value,
                        "resolved_inputs": _jsonb(run.resolved_inputs),
                        "created_at": run.created_at,
                        "updated_at": run.updated_at,
                    },
                )
            conn.commit()
        return run

    def get_run(self, run_id: uuid.UUID) -> Run | None:
        """Retrieve a run by primary key. Returns None if not found."""
        sql = "SELECT * FROM runs WHERE id = %(id)s"
        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"id": str(run_id)})
                row = cur.fetchone()
        if row is None:
            return None
        return Run.from_row(dict(row))

    def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        wrapper: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Run]:
        """List runs with optional filters, ordered by created_at DESC."""
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if status is not None:
            clauses.append("status = %(status)s")
            params["status"] = status.value
        if wrapper is not None:
            clauses.append("wrapper_name = %(wrapper)s")
            params["wrapper"] = wrapper

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s"  # nosec B608 — clauses contain only parameterized placeholders, no user input

        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [Run.from_row(dict(r)) for r in rows]

    def update_run_status(
        self,
        run_id: uuid.UUID,
        status: RunStatus,
        resolved_inputs: dict[str, Any] | None = None,
    ) -> Run:
        """Update run status (and optionally resolved_inputs). Raises KeyError if missing."""
        now = datetime.utcnow()
        current_phase = _STATUS_TO_PHASE.get(status, RunPhase.audit)
        if resolved_inputs is not None:
            sql = """
                UPDATE runs
                SET status = %(status)s, current_phase = %(current_phase)s,
                    resolved_inputs = %(resolved_inputs)s, updated_at = %(updated_at)s
                WHERE id = %(id)s
                RETURNING *
            """
            params: dict[str, Any] = {
                "status": status.value,
                "current_phase": current_phase.value,
                "resolved_inputs": _jsonb(resolved_inputs),
                "updated_at": now,
                "id": str(run_id),
            }
        else:
            sql = """
                UPDATE runs
                SET status = %(status)s, current_phase = %(current_phase)s,
                    updated_at = %(updated_at)s
                WHERE id = %(id)s
                RETURNING *
            """
            params = {
                "status": status.value,
                "current_phase": current_phase.value,
                "updated_at": now,
                "id": str(run_id),
            }

        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()

        if row is None:
            raise KeyError(f"Run {run_id} not found")
        return Run.from_row(dict(row))

    # ------------------------------------------------------------------
    # Stage transitions
    # ------------------------------------------------------------------

    def add_transition(self, transition: StageTransition) -> StageTransition:
        """Append a StageTransition to the immutable log."""
        sql = """
            INSERT INTO stage_transitions (
                id, run_id, from_phase, to_phase, transitioned_at, evidence
            ) VALUES (
                %(id)s, %(run_id)s, %(from_phase)s, %(to_phase)s,
                %(transitioned_at)s, %(evidence)s
            )
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(transition.id),
                        "run_id": str(transition.run_id),
                        "from_phase": transition.from_phase.value if transition.from_phase else None,
                        "to_phase": transition.to_phase.value,
                        "transitioned_at": transition.transitioned_at,
                        "evidence": _jsonb(transition.evidence),
                    },
                )
            conn.commit()
        return transition

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def save_approval(self, approval: ApprovalRecord) -> ApprovalRecord:
        """Persist an approval record (upsert by run_id — one active record per run)."""
        sql = """
            INSERT INTO approval_records (
                id, run_id, approval_hash, identity_source, subject_id,
                issued_at, trust_basis, role, valid, invalidated_at, invalidation_reason
            ) VALUES (
                %(id)s, %(run_id)s, %(approval_hash)s, %(identity_source)s,
                %(subject_id)s, %(issued_at)s, %(trust_basis)s, %(role)s,
                %(valid)s, %(invalidated_at)s, %(invalidation_reason)s
            )
            ON CONFLICT (run_id) DO UPDATE SET
                id = EXCLUDED.id,
                approval_hash = EXCLUDED.approval_hash,
                identity_source = EXCLUDED.identity_source,
                subject_id = EXCLUDED.subject_id,
                issued_at = EXCLUDED.issued_at,
                trust_basis = EXCLUDED.trust_basis,
                role = EXCLUDED.role,
                valid = EXCLUDED.valid,
                invalidated_at = EXCLUDED.invalidated_at,
                invalidation_reason = EXCLUDED.invalidation_reason
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(approval.id),
                        "run_id": str(approval.run_id),
                        "approval_hash": approval.approval_hash,
                        "identity_source": approval.identity_source,
                        "subject_id": approval.subject_id,
                        "issued_at": approval.issued_at,
                        "trust_basis": approval.trust_basis,
                        "role": approval.role.name,
                        "valid": approval.valid,
                        "invalidated_at": approval.invalidated_at,
                        "invalidation_reason": approval.invalidation_reason,
                    },
                )
            conn.commit()
        return approval

    def invalidate_approval(
        self,
        run_id: uuid.UUID,
        reason: str,
    ) -> ApprovalRecord:
        """Mark the active approval for a run as invalid. Raises KeyError if missing."""
        now = datetime.utcnow()
        sql = """
            UPDATE approval_records
            SET valid = false, invalidated_at = %(now)s, invalidation_reason = %(reason)s
            WHERE run_id = %(run_id)s AND valid = true
            RETURNING *
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"now": now, "reason": reason, "run_id": str(run_id)})
                row = cur.fetchone()
            conn.commit()

        if row is None:
            raise KeyError(f"No active approval for run {run_id}")
        return ApprovalRecord.from_row(dict(row))

    # ------------------------------------------------------------------
    # Apply plans
    # ------------------------------------------------------------------

    def save_apply_plan(
        self,
        run_id: uuid.UUID,
        plan_content: dict[str, Any],
        patch_items: Any,
        ownership_manifest: dict[str, Any],
        approval_hash: str | None = None,
    ) -> uuid.UUID:
        """Persist a semantic apply plan. Returns the plan ID."""
        plan_id = uuid.uuid4()
        sql = """
            INSERT INTO apply_plans (
                id, run_id, plan_content, patch_items, ownership_manifest,
                created_at, approval_hash
            ) VALUES (
                %(id)s, %(run_id)s, %(plan_content)s, %(patch_items)s,
                %(ownership_manifest)s, %(created_at)s, %(approval_hash)s
            )
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(plan_id),
                        "run_id": str(run_id),
                        "plan_content": _jsonb(plan_content),
                        "patch_items": _jsonb(patch_items),
                        "ownership_manifest": _jsonb(ownership_manifest),
                        "created_at": datetime.utcnow(),
                        "approval_hash": approval_hash,
                    },
                )
            conn.commit()
        return plan_id

    def get_apply_plan(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Return the most recent semantic apply plan for a run."""
        sql = """
            SELECT *
            FROM apply_plans
            WHERE run_id = %(run_id)s
            ORDER BY created_at DESC
            LIMIT 1
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"run_id": str(run_id)})
                row = cur.fetchone()

        if row is None:
            return None

        row_dict = dict(row)
        plan_content = row_dict.get("plan_content") or {}
        result = dict(plan_content)
        result["id"] = row_dict["id"]
        result["run_id"] = row_dict["run_id"]
        result["patch_items"] = row_dict.get("patch_items") or []
        result["ownership_manifest"] = row_dict.get("ownership_manifest") or {}
        result["created_at"] = row_dict.get("created_at")
        result["approval_hash"] = row_dict.get("approval_hash")
        return result

    # ------------------------------------------------------------------
    # Conformance results
    # ------------------------------------------------------------------

    def save_conformance(
        self,
        run_id: uuid.UUID,
        status: str,
        details: dict[str, Any],
    ) -> uuid.UUID:
        """Persist a conformance result. Returns the conformance result ID."""
        result_id = uuid.uuid4()
        sql = """
            INSERT INTO conformance_results (
                id, run_id, status, checked_at, details
            ) VALUES (
                %(id)s, %(run_id)s, %(status)s, %(checked_at)s, %(details)s
            )
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(result_id),
                        "run_id": str(run_id),
                        "status": status,
                        "checked_at": datetime.utcnow(),
                        "details": _jsonb(details),
                    },
                )
            conn.commit()
        return result_id

    # ------------------------------------------------------------------
    # Drift exceptions
    # ------------------------------------------------------------------

    def save_drift_exception(
        self, exception: DriftExceptionRecord
    ) -> DriftExceptionRecord:
        """Persist a drift exception record."""
        sql = """
            INSERT INTO drift_exceptions (
                id, run_id, conformance_id, reason, identity_source,
                subject_id, role, original_apply_role, recorded_at
            ) VALUES (
                %(id)s, %(run_id)s, %(conformance_id)s, %(reason)s,
                %(identity_source)s, %(subject_id)s, %(role)s,
                %(original_apply_role)s, %(recorded_at)s
            )
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(exception.id),
                        "run_id": str(exception.run_id),
                        "conformance_id": str(exception.conformance_id),
                        "reason": exception.reason,
                        "identity_source": exception.identity_source,
                        "subject_id": exception.subject_id,
                        "role": exception.role.name,
                        "original_apply_role": exception.original_apply_role.name,
                        "recorded_at": exception.recorded_at,
                    },
                )
            conn.commit()
        return exception

    # ------------------------------------------------------------------
    # Legacy authority
    # ------------------------------------------------------------------

    def save_legacy_entry(
        self,
        flow_name: str,
        source_type: str,
        source_path: str,
        expected_status: str,
    ) -> uuid.UUID:
        """Upsert a legacy authority entry by (flow_name, source_path). Returns entry ID."""
        entry_id = uuid.uuid4()
        sql = """
            INSERT INTO legacy_authority_entries (
                id, flow_name, source_type, source_path, expected_status
            ) VALUES (
                %(id)s, %(flow_name)s, %(source_type)s, %(source_path)s, %(expected_status)s
            )
            ON CONFLICT (flow_name, source_path) DO UPDATE SET
                source_type = EXCLUDED.source_type,
                expected_status = EXCLUDED.expected_status
            RETURNING id
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "id": str(entry_id),
                        "flow_name": flow_name,
                        "source_type": source_type,
                        "source_path": source_path,
                        "expected_status": expected_status,
                    },
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return entry_id
        return uuid.UUID(str(row[0]))

    def get_run_detail(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Return a run with all related data (transitions, approvals, plans, conformance, exceptions)."""
        run = self.get_run(run_id)
        if run is None:
            return None

        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM stage_transitions WHERE run_id = %(run_id)s ORDER BY transitioned_at",
                    {"run_id": str(run_id)},
                )
                transitions = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    "SELECT * FROM approval_records WHERE run_id = %(run_id)s ORDER BY issued_at DESC",
                    {"run_id": str(run_id)},
                )
                approvals = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    "SELECT * FROM apply_plans WHERE run_id = %(run_id)s ORDER BY created_at DESC",
                    {"run_id": str(run_id)},
                )
                plans = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    "SELECT * FROM conformance_results WHERE run_id = %(run_id)s ORDER BY checked_at DESC",
                    {"run_id": str(run_id)},
                )
                conformance_results = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    "SELECT * FROM drift_exceptions WHERE run_id = %(run_id)s ORDER BY recorded_at DESC",
                    {"run_id": str(run_id)},
                )
                exceptions = [dict(r) for r in cur.fetchall()]

        return {
            "run": {
                "id": str(run.id),
                "wrapper_name": run.wrapper_name,
                "wrapper_version": run.wrapper_version,
                "adapter_name": run.adapter_name,
                "current_phase": run.current_phase,
                "status": run.status.value,
                "resolved_inputs": run.resolved_inputs,
                "created_at": str(run.created_at),
                "updated_at": str(run.updated_at),
            },
            "transitions": transitions,
            "approvals": approvals,
            "apply_plans": plans,
            "conformance_results": conformance_results,
            "drift_exceptions": exceptions,
        }

    def get_legacy_inventory(self, flow_name: str) -> list[dict[str, Any]]:
        """Return all legacy authority entries for the given flow, ordered by source_path."""
        sql = """
            SELECT * FROM legacy_authority_entries
            WHERE flow_name = %(flow_name)s
            ORDER BY source_path
        """
        with get_connection(self._db_url) as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, {"flow_name": flow_name})
                rows = cur.fetchall()
        return [dict(r) for r in rows]
