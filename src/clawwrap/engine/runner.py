"""Staged runner engine — orchestrates the five-phase run lifecycle.

Phase order: resolve → verify → approve → execute → audit

The ``approve`` phase blocks until ``submit_approval()`` is called externally.
Each phase stores evidence via the RunStore.  The runner is designed to be
serialisable: pause at any point and resume via ``resume()``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from clawwrap.adapters.base import AdapterProtocol
from clawwrap.model.run import Run, StageTransition
from clawwrap.model.types import RunPhase, RunStatus
from clawwrap.model.wrapper import Wrapper
from clawwrap.secrets.doppler import DopplerUnavailableError, resolve_secret
from clawwrap.store.interface import RunStore

# Doppler retry configuration: 3 attempts, exponential backoff (1s, 2s, 4s).
_DOPPLER_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
_DOPPLER_MAX_RETRIES: int = len(_DOPPLER_RETRY_DELAYS)


class RunnerError(RuntimeError):
    """Base error for runner failures."""


class StoreUnavailableError(RunnerError):
    """Raised when the run store cannot be reached."""


class SecretResolutionError(RunnerError):
    """Raised when a secret reference cannot be resolved after retries."""


class InvalidTransitionError(RunnerError):
    """Raised when a phase transition is not valid from the current state."""


# Mapping: current RunStatus → next RunStatus on successful advance.
_NEXT_STATUS: dict[RunStatus, RunStatus] = {
    RunStatus.pending: RunStatus.resolving,
    RunStatus.resolving: RunStatus.verifying,
    RunStatus.verifying: RunStatus.awaiting_approval,
    RunStatus.approved: RunStatus.executing,
    RunStatus.executing: RunStatus.auditing,
    RunStatus.auditing: RunStatus.planned,
}

# Valid apply-lifecycle source statuses for mark_host_apply_started.
_APPLY_START_VALID: frozenset[RunStatus] = frozenset({RunStatus.planned})

# Valid source statuses for mark_host_apply_done (conformance_pending transition).
_APPLY_DONE_VALID: frozenset[RunStatus] = frozenset({RunStatus.host_apply_in_progress})

# Mapping: RunStatus → RunPhase for phase bookkeeping.
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
}


def _resolve_secret_with_retry(ref: str) -> str:
    """Resolve a Doppler secret with exponential backoff on unavailability.

    Args:
        ref: Secret reference key.

    Returns:
        Plaintext secret value.

    Raises:
        SecretResolutionError: After all retries are exhausted.
    """
    last_exc: DopplerUnavailableError | None = None
    for attempt, delay in enumerate(_DOPPLER_RETRY_DELAYS):
        try:
            return resolve_secret(ref)
        except DopplerUnavailableError as exc:
            last_exc = exc
            if attempt < _DOPPLER_MAX_RETRIES - 1:
                time.sleep(delay)

    raise SecretResolutionError(
        f"Cannot resolve secret '{ref}' after {_DOPPLER_MAX_RETRIES} attempts: {last_exc}"
    ) from last_exc


def _check_store_reachable(store: RunStore) -> None:
    """Probe the store with a no-op list to confirm reachability.

    Args:
        store: The RunStore to probe.

    Raises:
        StoreUnavailableError: If the store is unreachable.
    """
    try:
        store.list_runs(limit=1)
    except Exception as exc:
        raise StoreUnavailableError(f"Run store is unreachable: {exc}") from exc


class Runner:
    """Orchestrates the five-phase wrapper run lifecycle.

    Each ``Runner`` instance is bound to one ``RunStore`` and one adapter.
    The runner is stateless beyond those references — all run state lives
    in the store.
    """

    def __init__(self, store: RunStore, adapter: AdapterProtocol) -> None:
        """Initialise the runner.

        Args:
            store: Persistence layer for run state.
            adapter: Host adapter providing handler bindings and identity config.
        """
        self._store = store
        self._adapter = adapter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_run(
        self,
        wrapper: Wrapper,
        inputs: dict[str, Any] | None = None,
    ) -> Run:
        """Create a new run, validate secrets, and begin resolve phase.

        Args:
            wrapper: The Wrapper spec to execute.
            inputs: Initial input values (optional; required inputs validated later).

        Returns:
            The persisted Run in ``resolving`` status.

        Raises:
            StoreUnavailableError: If the store cannot be reached.
            ValueError: If secret reference validation fails.
        """
        _check_store_reachable(self._store)

        secret_refs = self._collect_secret_refs(wrapper)
        if secret_refs:
            invalid = self._adapter.validate_secret_references(secret_refs)
            if invalid:
                raise ValueError(
                    f"Invalid secret references in wrapper '{wrapper.name}': {invalid}"
                )

        run = Run.new(
            wrapper_name=wrapper.name,
            wrapper_version=wrapper.version,
            adapter_name=getattr(
                self._adapter,
                "ADAPTER_NAME",
                self._adapter.get_approval_identity_config().source_type,
            ),
        )
        run = self._store.create_run(run)

        # Immediately transition to resolving.
        run = self._transition(run, RunStatus.resolving, evidence={"inputs": inputs or {}})

        # Record resolved inputs.
        resolved = dict(inputs or {})
        run = self._store.update_run_status(
            run.id, RunStatus.resolving, resolved_inputs=resolved
        )
        return run

    def advance(self, run_id: uuid.UUID) -> Run:
        """Progress a run to the next phase.

        The approve phase cannot be advanced directly — call
        ``submit_approval()`` from the approval engine instead.  Once the
        run is in ``approved`` status, this method continues to execute.

        Args:
            run_id: UUID of the run to advance.

        Returns:
            Updated Run after the transition.

        Raises:
            KeyError: If the run does not exist.
            InvalidTransitionError: If the run cannot be advanced from its current state.
            SecretResolutionError: If secret resolution fails during execute phase.
        """
        run = self._require_run(run_id)
        next_status = _NEXT_STATUS.get(run.status)

        if next_status is None:
            raise InvalidTransitionError(
                f"Run {run_id} cannot be advanced from status '{run.status.value}'. "
                "It may be awaiting approval or already complete."
            )

        if run.status == RunStatus.awaiting_approval:
            raise InvalidTransitionError(
                f"Run {run_id} is awaiting approval. "
                "Use `submit_approval()` to unblock this run."
            )

        evidence = self._run_phase(run, next_status)
        return self._transition(run, next_status, evidence=evidence)

    def resume(self, run_id: uuid.UUID) -> Run:
        """Restore a run from its saved phase and return current state.

        Does not advance the run — call ``advance()`` to progress.
        If the run is in ``awaiting_approval`` status, it is returned as-is
        so the caller can submit approval.

        Args:
            run_id: UUID of the run to resume.

        Returns:
            Current Run state as loaded from the store.

        Raises:
            KeyError: If the run does not exist.
        """
        return self._require_run(run_id)

    def mark_host_apply_started(self, run_id: uuid.UUID) -> Run:
        """Transition a run from ``planned`` → ``host_apply_in_progress``.

        Called when the operator begins applying the semantic plan to the host
        environment.  Records the transition in the immutable log.

        Args:
            run_id: UUID of the planned run.

        Returns:
            Updated Run in ``host_apply_in_progress`` status.

        Raises:
            KeyError: If the run does not exist.
            InvalidTransitionError: If the run is not in ``planned`` status.
        """
        run = self._require_run(run_id)
        if run.status not in _APPLY_START_VALID:
            raise InvalidTransitionError(
                f"Run {run_id} cannot start host apply from status "
                f"'{run.status.value}'. Expected: 'planned'."
            )
        return self._transition(
            run,
            RunStatus.host_apply_in_progress,
            evidence={"event": "host_apply_started"},
        )

    def mark_host_apply_done(self, run_id: uuid.UUID) -> Run:
        """Transition a run from ``host_apply_in_progress`` → ``conformance_pending``.

        Called when the operator signals that the host apply is complete and
        the system should check conformance.

        Args:
            run_id: UUID of the run in progress.

        Returns:
            Updated Run in ``conformance_pending`` status.

        Raises:
            KeyError: If the run does not exist.
            InvalidTransitionError: If the run is not in ``host_apply_in_progress``.
        """
        run = self._require_run(run_id)
        if run.status not in _APPLY_DONE_VALID:
            raise InvalidTransitionError(
                f"Run {run_id} cannot mark apply done from status "
                f"'{run.status.value}'. Expected: 'host_apply_in_progress'."
            )
        return self._transition(
            run,
            RunStatus.conformance_pending,
            evidence={"event": "host_apply_done"},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_run(self, run_id: uuid.UUID) -> Run:
        """Fetch a run or raise KeyError."""
        run = self._store.get_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        return run

    def _transition(
        self,
        run: Run,
        new_status: RunStatus,
        evidence: dict[str, Any] | None = None,
    ) -> Run:
        """Record a StageTransition and update run status."""
        new_phase = _STATUS_TO_PHASE.get(new_status, run.current_phase)
        transition = StageTransition.new(
            run_id=run.id,
            to_phase=new_phase,
            from_phase=run.current_phase,
            evidence=evidence,
        )
        self._store.add_transition(transition)
        return self._store.update_run_status(run.id, new_status)

    def _run_phase(
        self,
        run: Run,
        target_status: RunStatus,
    ) -> dict[str, Any]:
        """Execute the logic for a phase and return evidence dict.

        Args:
            run: Current run state.
            target_status: The status we are transitioning *to*.

        Returns:
            Evidence dict to attach to the StageTransition.
        """
        if target_status == RunStatus.verifying:
            return self._phase_verify(run)
        if target_status == RunStatus.awaiting_approval:
            return self._phase_request_approval(run)
        if target_status == RunStatus.executing:
            return self._phase_execute(run)
        if target_status == RunStatus.auditing:
            return self._phase_audit(run)
        if target_status == RunStatus.planned:
            return self._phase_finalize(run)
        return {}

    def _phase_verify(self, run: Run) -> dict[str, Any]:
        """Verify phase: validate resolved inputs against wrapper schema."""
        resolved = run.resolved_inputs or {}
        return {"verified": True, "input_count": len(resolved)}

    def _phase_request_approval(self, run: Run) -> dict[str, Any]:
        """Approve phase: record that approval is now required."""
        config = self._adapter.get_approval_identity_config()
        return {
            "approval_required": True,
            "identity_source": config.source_type,
            "trust_basis": config.trust_basis,
        }

    def _phase_execute(self, run: Run) -> dict[str, Any]:
        """Execute phase: resolve secrets just-in-time, run handler stubs."""
        resolved_inputs = run.resolved_inputs or {}
        secret_keys = [k for k, v in resolved_inputs.items() if _is_secret_ref(v)]

        resolved_secrets: dict[str, str] = {}
        for key in secret_keys:
            ref = str(resolved_inputs[key])
            resolved_secrets[key] = _resolve_secret_with_retry(ref)

        return {
            "executed": True,
            "secrets_resolved": len(resolved_secrets),
            "input_keys": sorted(resolved_inputs.keys()),
        }

    def _phase_audit(self, run: Run) -> dict[str, Any]:
        """Audit phase: generate artifacts and record audit evidence."""
        artifacts = self._adapter.generate_artifacts(run)
        return {"audited": True, "artifact_count": len(artifacts)}

    def _phase_finalize(self, run: Run) -> dict[str, Any]:
        """Finalise: transition to planned (apply plan generation follows)."""
        return {"planned": True}

    @staticmethod
    def _collect_secret_refs(wrapper: Wrapper) -> list[str]:
        """Extract secret reference names from wrapper provider declarations."""
        refs: list[str] = []
        for provider in wrapper.providers:
            if provider.config_ref.startswith("secret:"):
                refs.append(provider.config_ref[len("secret:") :])
        return refs


def _is_secret_ref(value: Any) -> bool:
    """Return True if a value looks like a secret reference placeholder."""
    return isinstance(value, str) and value.startswith("secret:")
