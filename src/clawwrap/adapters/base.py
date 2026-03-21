"""Adapter base protocol — all host adapters must satisfy this interface."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from clawwrap.model.adapter import ApprovalIdentityConfig
from clawwrap.model.approval import ApprovalIdentityEvidence
from clawwrap.model.types import ApprovalRole

if TYPE_CHECKING:
    from clawwrap.model.run import Run


@runtime_checkable
class AdapterProtocol(Protocol):
    """Protocol that all host adapters must implement.

    Host adapters bridge clawwrap's abstract run model to a specific
    deployment environment (e.g. local-cli, openclaw).
    """

    def bind_handler(self, handler_id: str) -> Callable[..., Any]:
        """Return the callable that implements the named handler contract.

        Args:
            handler_id: Dotted global handler identifier (e.g. ``group.identity_matches``).

        Returns:
            Callable that satisfies the handler's input/output schema.

        Raises:
            KeyError: If the handler is not bound by this adapter.
        """
        ...

    def resolve_approval_identity(
        self, evidence: ApprovalIdentityEvidence
    ) -> ApprovalRole:
        """Map identity evidence to an ApprovalRole using the adapter's trust rules.

        Args:
            evidence: Identity evidence submitted by the approver.

        Returns:
            Resolved ApprovalRole for the given evidence.

        Raises:
            ValueError: If the evidence cannot be resolved to a valid role.
        """
        ...

    def generate_artifacts(self, run: Run) -> list[dict[str, Any]]:
        """Generate host-native artifacts derived from a completed run.

        Args:
            run: The completed Run whose outputs drive artifact generation.

        Returns:
            List of artifact dicts describing generated outputs.
        """
        ...

    def read_host_state(self, surfaces: list[str]) -> dict[str, Any]:
        """Read the current state of the specified host surfaces.

        Args:
            surfaces: List of surface selector strings (paths, config keys, etc.).

        Returns:
            Dict mapping each surface selector to its observed value or
            ``None`` if the surface does not exist.
        """
        ...

    def get_approval_identity_config(self) -> ApprovalIdentityConfig:
        """Return the approval identity configuration for this adapter.

        Returns:
            ApprovalIdentityConfig describing how identity evidence is sourced.
        """
        ...

    def validate_secret_references(self, refs: list[str]) -> list[str]:
        """Check that all secret references are valid without resolving values.

        Args:
            refs: List of secret reference strings (e.g. Doppler paths).

        Returns:
            List of invalid or unresolvable reference strings (empty = all valid).
        """
        ...
