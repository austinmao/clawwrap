"""T068: Integration tests for the RunStore Postgres backend.

These tests require a live PostgreSQL database.
They are skipped automatically when no Postgres connection is available.
"""

from __future__ import annotations

import os

import pytest


def _postgres_available() -> bool:
    """Return True when a Postgres DSN is available in the environment."""
    return bool(os.environ.get("CLAWWRAP_TEST_DATABASE_URL"))


# All tests in this module are skipped when Postgres is unavailable.
pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="CLAWWRAP_TEST_DATABASE_URL not set — Postgres integration tests skipped",
)


class TestRunStorePostgres:
    """Placeholder integration tests for the Postgres RunStore.

    These tests will be expanded once a live database is available in CI.
    Each test documents its intended behaviour as a contract.
    """

    def test_placeholder_create_run(self) -> None:
        """PLACEHOLDER: create_run should persist a new Run and return it with a UUID.

        Implementation required:
        1. Create a RunStore with the test DSN.
        2. Build a Run.new() instance.
        3. Call store.create_run(run).
        4. Assert returned run has a non-null id and status == pending.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_get_run_returns_none_for_missing(self) -> None:
        """PLACEHOLDER: get_run with an unknown UUID should return None.

        Implementation required:
        1. Create a RunStore.
        2. Call store.get_run(uuid.uuid4()).
        3. Assert result is None.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_update_run_status(self) -> None:
        """PLACEHOLDER: update_run_status should reflect the new status on retrieval.

        Implementation required:
        1. Create and persist a Run.
        2. Call store.update_run_status(run.id, RunStatus.resolving).
        3. Retrieve the run via get_run.
        4. Assert retrieved run has status == resolving.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_add_transition_is_immutable(self) -> None:
        """PLACEHOLDER: add_transition records must not be deletable.

        Implementation required:
        1. Create a Run.
        2. Add a StageTransition.
        3. Verify the transition is retrievable.
        4. Verify no delete path exists in the store interface.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_list_runs_with_status_filter(self) -> None:
        """PLACEHOLDER: list_runs with status filter should return only matching runs.

        Implementation required:
        1. Create two runs in different statuses.
        2. Call store.list_runs(status=RunStatus.resolving).
        3. Assert only the resolving run is returned.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_save_approval(self) -> None:
        """PLACEHOLDER: save_approval should persist an ApprovalRecord for a run.

        Implementation required:
        1. Create a Run.
        2. Build an ApprovalRecord.new().
        3. Call store.save_approval(record).
        4. Assert the record is retrievable by run_id.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_invalidate_approval(self) -> None:
        """PLACEHOLDER: invalidate_approval should set valid=False on the approval.

        Implementation required:
        1. Create a Run and save an approval.
        2. Call store.invalidate_approval(run_id, reason="test").
        3. Retrieve and assert valid == False and reason is set.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_save_drift_exception(self) -> None:
        """PLACEHOLDER: save_drift_exception should persist a DriftExceptionRecord.

        Implementation required:
        1. Create a DriftExceptionRecord.new().
        2. Call store.save_drift_exception(record).
        3. Assert the record is persisted with correct role and run_id.
        """
        pytest.skip("Requires live Postgres — implement when DB available")
