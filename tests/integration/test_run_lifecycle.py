"""T069: Integration tests for the full run lifecycle.

These tests require a live PostgreSQL database.
They are skipped automatically when no Postgres connection is available.
"""

from __future__ import annotations

import os

import pytest


def _postgres_available() -> bool:
    """Return True when a Postgres DSN is available in the environment."""
    return bool(os.environ.get("CLAWWRAP_TEST_DATABASE_URL"))


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason="CLAWWRAP_TEST_DATABASE_URL not set — Postgres integration tests skipped",
)


class TestRunLifecycle:
    """Placeholder lifecycle tests for Runner + Postgres store integration.

    These document the intended end-to-end contract.
    """

    def test_placeholder_full_lifecycle_pending_to_planned(self) -> None:
        """PLACEHOLDER: A run should advance from pending → resolving → verifying →
        awaiting_approval → approved → executing → auditing → planned.

        Implementation required:
        1. Create a real Postgres RunStore and LocalCliAdapter.
        2. Instantiate Runner.
        3. Call start_run(), then advance() repeatedly.
        4. Submit approval manually at awaiting_approval.
        5. Assert final status == planned.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_approval_hash_invalidated_on_input_change(self) -> None:
        """PLACEHOLDER: Changing resolved_inputs after approval must invalidate the approval.

        Implementation required:
        1. Create a run and approve it.
        2. Mutate resolved_inputs.
        3. Recompute approval hash and compare.
        4. Assert the hashes differ.
        5. Assert the old approval is invalidated.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_host_apply_transitions(self) -> None:
        """PLACEHOLDER: After planned, mark_host_apply_started and mark_host_apply_done
        should transition through host_apply_in_progress → conformance_pending.

        Implementation required:
        1. Advance a run to planned.
        2. Call mark_host_apply_started → assert host_apply_in_progress.
        3. Call mark_host_apply_done → assert conformance_pending.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_stage_transitions_are_immutable_log(self) -> None:
        """PLACEHOLDER: Every advance() call must append a StageTransition to the log.

        Implementation required:
        1. Run through several phases.
        2. Query the transition log for the run.
        3. Assert each phase change is recorded in order.
        4. Assert no transition record can be deleted.
        """
        pytest.skip("Requires live Postgres — implement when DB available")

    def test_placeholder_cancel_terminates_run(self) -> None:
        """PLACEHOLDER: Setting status to cancelled must prevent further advance().

        Implementation required:
        1. Create a run and start resolving.
        2. Directly update status to cancelled.
        3. Call advance() and assert InvalidTransitionError is raised.
        """
        pytest.skip("Requires live Postgres — implement when DB available")
