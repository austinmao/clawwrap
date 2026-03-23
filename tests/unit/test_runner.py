"""T066: Unit tests for clawwrap.engine.runner.Runner.

Covers:
- Runner phase transitions (using mock store)
- Invalid transition raises InvalidTransitionError
- start_run creates a run in resolving status
- advance from awaiting_approval raises InvalidTransitionError
- advance from a terminal/unknown state raises InvalidTransitionError
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from clawwrap.engine.runner import InvalidTransitionError, Runner, StoreUnavailableError
from clawwrap.model.run import Run, StageTransition
from clawwrap.model.types import ApprovalRole, RunPhase, RunStatus
from clawwrap.model.wrapper import Wrapper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(status: RunStatus, resolved_inputs: dict[str, Any] | None = None) -> Run:
    """Build a Run dataclass in the given status."""
    now = datetime.now(UTC)
    return Run(
        id=uuid.uuid4(),
        wrapper_name="test-wrapper",
        wrapper_version="1.0.0",
        adapter_name="local-cli",
        current_phase=RunPhase.resolve,
        status=status,
        created_at=now,
        updated_at=now,
        resolved_inputs=resolved_inputs,
    )


def _minimal_wrapper() -> Wrapper:
    """Build a minimal Wrapper with no providers or dependencies."""
    return Wrapper(
        name="test-wrapper",
        version="1.0.0",
        schema_version=1,
        description="Minimal test wrapper",
        inputs=[],
        outputs=[],
        stages=[],
        providers=[],
        dependencies=[],
        policies=[],
        approval_role=ApprovalRole.operator,
    )


def _make_mock_store(run: Run) -> MagicMock:
    """Build a mock RunStore that returns the given run on get/update/create."""
    store = MagicMock()
    store.list_runs.return_value = []
    store.create_run.return_value = run
    store.get_run.return_value = run
    store.update_run_status.return_value = run
    store.add_transition.return_value = MagicMock(spec=StageTransition)
    return store


def _make_mock_adapter() -> MagicMock:
    """Build a mock adapter with a minimal identity config."""
    adapter = MagicMock()
    from clawwrap.model.adapter import ApprovalIdentityConfig

    adapter.get_approval_identity_config.return_value = ApprovalIdentityConfig(
        source_type="local-cli",
        subject_key="subject_id",
        trust_basis="local-cli-development",
    )
    adapter.validate_secret_references.return_value = []
    adapter.generate_artifacts.return_value = []
    return adapter


# ---------------------------------------------------------------------------
# start_run
# ---------------------------------------------------------------------------


class TestRunnerStartRun:
    """Tests for Runner.start_run."""

    def test_start_run_creates_run(self) -> None:
        """start_run must call store.create_run and return a run in resolving status."""
        pending_run = _make_run(RunStatus.pending)
        resolving_run = _make_run(RunStatus.resolving)

        store = _make_mock_store(pending_run)
        store.create_run.return_value = pending_run
        store.update_run_status.return_value = resolving_run

        adapter = _make_mock_adapter()
        runner = Runner(store=store, adapter=adapter)
        wrapper = _minimal_wrapper()

        result = runner.start_run(wrapper)

        store.create_run.assert_called_once()
        assert result.status == RunStatus.resolving

    def test_start_run_raises_when_store_unreachable(self) -> None:
        """start_run must raise StoreUnavailableError when the store throws."""
        store = MagicMock()
        store.list_runs.side_effect = ConnectionError("DB offline")

        adapter = _make_mock_adapter()
        runner = Runner(store=store, adapter=adapter)

        with pytest.raises(StoreUnavailableError):
            runner.start_run(_minimal_wrapper())

    def test_start_run_validates_secret_refs(self) -> None:
        """start_run must call validate_secret_references when providers have secret refs."""
        from clawwrap.model.wrapper import ProviderRef

        wrapper = Wrapper(
            name="wrapper-with-secret",
            version="1.0.0",
            schema_version=1,
            description="Has a secret provider",
            inputs=[],
            outputs=[],
            stages=[],
            providers=[ProviderRef(kind="doppler", config_ref="secret:MY_KEY")],
            dependencies=[],
            policies=[],
        )

        run = _make_run(RunStatus.resolving)
        store = _make_mock_store(run)
        adapter = _make_mock_adapter()
        runner = Runner(store=store, adapter=adapter)

        runner.start_run(wrapper)

        adapter.validate_secret_references.assert_called_once_with(["MY_KEY"])

    def test_start_run_raises_on_invalid_secret_ref(self) -> None:
        """start_run must raise ValueError when adapter reports invalid secret refs."""
        from clawwrap.model.wrapper import ProviderRef

        wrapper = Wrapper(
            name="bad-secret-wrapper",
            version="1.0.0",
            schema_version=1,
            description="Invalid secret ref",
            inputs=[],
            outputs=[],
            stages=[],
            providers=[ProviderRef(kind="doppler", config_ref="secret:MISSING_KEY")],
            dependencies=[],
            policies=[],
        )

        run = _make_run(RunStatus.resolving)
        store = _make_mock_store(run)
        adapter = _make_mock_adapter()
        adapter.validate_secret_references.return_value = ["MISSING_KEY"]
        runner = Runner(store=store, adapter=adapter)

        with pytest.raises(ValueError, match="MISSING_KEY"):
            runner.start_run(wrapper)

    def test_start_run_persists_adapter_name_not_identity_source(self) -> None:
        """start_run must persist the adapter name even when identity source differs."""
        pending_run = _make_run(RunStatus.pending)
        resolving_run = _make_run(RunStatus.resolving)

        store = _make_mock_store(pending_run)
        store.update_run_status.return_value = resolving_run

        adapter = _make_mock_adapter()
        adapter.ADAPTER_NAME = "openclaw"
        runner = Runner(store=store, adapter=adapter)

        runner.start_run(_minimal_wrapper())

        created_run = store.create_run.call_args.args[0]
        assert created_run.adapter_name == "openclaw"


# ---------------------------------------------------------------------------
# advance — valid transitions
# ---------------------------------------------------------------------------


class TestRunnerAdvanceValid:
    """Tests for Runner.advance with valid state transitions."""

    def test_advance_from_resolving_to_verifying(self) -> None:
        """advance() on a resolving run must update status to verifying."""
        current_run = _make_run(RunStatus.resolving, resolved_inputs={})
        next_run = _make_run(RunStatus.verifying)

        store = _make_mock_store(current_run)
        store.update_run_status.return_value = next_run

        adapter = _make_mock_adapter()
        runner = Runner(store=store, adapter=adapter)

        result = runner.advance(current_run.id)

        assert result.status == RunStatus.verifying

    def test_advance_from_verifying_to_awaiting_approval(self) -> None:
        """advance() on a verifying run must update status to awaiting_approval."""
        current_run = _make_run(RunStatus.verifying)
        next_run = _make_run(RunStatus.awaiting_approval)

        store = _make_mock_store(current_run)
        store.update_run_status.return_value = next_run

        adapter = _make_mock_adapter()
        runner = Runner(store=store, adapter=adapter)

        result = runner.advance(current_run.id)

        assert result.status == RunStatus.awaiting_approval


# ---------------------------------------------------------------------------
# advance — invalid transitions
# ---------------------------------------------------------------------------


class TestRunnerAdvanceInvalid:
    """Tests for Runner.advance with invalid state transitions."""

    def test_advance_from_awaiting_approval_raises(self) -> None:
        """advance() must raise InvalidTransitionError when run is awaiting approval."""
        run = _make_run(RunStatus.awaiting_approval)
        store = _make_mock_store(run)
        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(InvalidTransitionError, match="awaiting approval"):
            runner.advance(run.id)

    def test_advance_from_failed_raises(self) -> None:
        """advance() must raise InvalidTransitionError when run is in failed status."""
        run = _make_run(RunStatus.failed)
        store = _make_mock_store(run)
        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(InvalidTransitionError):
            runner.advance(run.id)

    def test_advance_from_cancelled_raises(self) -> None:
        """advance() must raise InvalidTransitionError when run is cancelled."""
        run = _make_run(RunStatus.cancelled)
        store = _make_mock_store(run)
        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(InvalidTransitionError):
            runner.advance(run.id)

    def test_advance_missing_run_raises_key_error(self) -> None:
        """advance() must raise KeyError when the run does not exist."""
        store = MagicMock()
        store.list_runs.return_value = []
        store.get_run.return_value = None

        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(KeyError):
            runner.advance(uuid.uuid4())


# ---------------------------------------------------------------------------
# mark_host_apply_started / mark_host_apply_done
# ---------------------------------------------------------------------------


class TestRunnerApplyLifecycle:
    """Tests for host apply lifecycle transitions."""

    def test_mark_host_apply_started_from_planned(self) -> None:
        """mark_host_apply_started must succeed from planned status."""
        run = _make_run(RunStatus.planned)
        next_run = _make_run(RunStatus.host_apply_in_progress)

        store = _make_mock_store(run)
        store.update_run_status.return_value = next_run

        runner = Runner(store=store, adapter=_make_mock_adapter())
        result = runner.mark_host_apply_started(run.id)

        assert result.status == RunStatus.host_apply_in_progress

    def test_mark_host_apply_started_from_non_planned_raises(self) -> None:
        """mark_host_apply_started must raise InvalidTransitionError from non-planned."""
        run = _make_run(RunStatus.resolving)
        store = _make_mock_store(run)
        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(InvalidTransitionError):
            runner.mark_host_apply_started(run.id)

    def test_mark_host_apply_done_from_in_progress(self) -> None:
        """mark_host_apply_done must succeed from host_apply_in_progress."""
        run = _make_run(RunStatus.host_apply_in_progress)
        next_run = _make_run(RunStatus.conformance_pending)

        store = _make_mock_store(run)
        store.update_run_status.return_value = next_run

        runner = Runner(store=store, adapter=_make_mock_adapter())
        result = runner.mark_host_apply_done(run.id)

        assert result.status == RunStatus.conformance_pending

    def test_mark_host_apply_done_from_wrong_status_raises(self) -> None:
        """mark_host_apply_done must raise InvalidTransitionError from non in-progress status."""
        run = _make_run(RunStatus.planned)
        store = _make_mock_store(run)
        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(InvalidTransitionError):
            runner.mark_host_apply_done(run.id)


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


class TestRunnerResume:
    """Tests for Runner.resume."""

    def test_resume_returns_current_run(self) -> None:
        """resume() must return the run as-is from the store."""
        run = _make_run(RunStatus.awaiting_approval)
        store = _make_mock_store(run)
        runner = Runner(store=store, adapter=_make_mock_adapter())

        result = runner.resume(run.id)
        assert result == run

    def test_resume_missing_run_raises_key_error(self) -> None:
        """resume() must raise KeyError when the run does not exist."""
        store = MagicMock()
        store.list_runs.return_value = []
        store.get_run.return_value = None
        runner = Runner(store=store, adapter=_make_mock_adapter())

        with pytest.raises(KeyError):
            runner.resume(uuid.uuid4())
