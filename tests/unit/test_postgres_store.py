"""Unit tests for the Postgres run store implementation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from clawwrap.model.types import RunPhase, RunStatus
from clawwrap.store.postgres import PostgresRunStore


class _FakeCursor:
    """Minimal cursor stub that records the last executed parameters."""

    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row
        self.sql: str | None = None
        self.params: dict[str, Any] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.sql = sql
        self.params = params

    def fetchone(self) -> dict[str, Any]:
        return self._row


class _FakeConnection:
    """Minimal connection stub that returns a pre-seeded cursor."""

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def cursor(self, row_factory: Any = None) -> _FakeCursor:  # noqa: ARG002
        return self._cursor

    def commit(self) -> None:
        self.committed = True


@pytest.mark.parametrize(
    ("status", "expected_phase", "resolved_inputs"),
    [
        (RunStatus.verifying, RunPhase.verify, None),
        (RunStatus.resolving, RunPhase.resolve, {"target": "staff-group"}),
    ],
)
def test_update_run_status_persists_current_phase(
    monkeypatch: pytest.MonkeyPatch,
    status: RunStatus,
    expected_phase: RunPhase,
    resolved_inputs: dict[str, str] | None,
) -> None:
    """update_run_status must write the derived current_phase alongside status changes."""
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    row = {
        "id": str(run_id),
        "wrapper_name": "verified-send",
        "wrapper_version": "1.0.0",
        "adapter_name": "openclaw",
        "current_phase": expected_phase.value,
        "status": status.value,
        "resolved_inputs": resolved_inputs,
        "created_at": now,
        "updated_at": now,
    }
    cursor = _FakeCursor(row)
    connection = _FakeConnection(cursor)

    import clawwrap.store.postgres as postgres

    monkeypatch.setattr(postgres, "get_connection", lambda db_url: connection)

    store = PostgresRunStore("postgresql://example.test/clawwrap")
    run = store.update_run_status(run_id, status, resolved_inputs=resolved_inputs)

    assert cursor.params is not None
    assert cursor.params["current_phase"] == expected_phase.value
    assert run.current_phase == expected_phase
    assert connection.committed is True
