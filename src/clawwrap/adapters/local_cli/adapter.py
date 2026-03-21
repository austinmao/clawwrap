"""Local-CLI host adapter — development/testing implementation of AdapterProtocol.

This adapter is explicitly NOT for production use. It provides:
- Pass-through handler stubs (return empty dicts)
- File-based approval identity from .clawwrap/identity.yaml
- Local filesystem host state reading
- Non-production guardrails that prevent live sends
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from clawwrap.adapters.local_cli.identity import (
    DEFAULT_IDENTITY_PATH,
    load_identity,
)
from clawwrap.model.adapter import ApprovalIdentityConfig
from clawwrap.model.approval import ApprovalIdentityEvidence
from clawwrap.model.types import ApprovalRole
from clawwrap.secrets.doppler import DopplerUnavailableError, validate_references

# Adapters name used in specs and bindings.
ADAPTER_NAME: str = "local-cli"

# Explicit guardrail: these handler IDs must never perform live sends in this adapter.
_LIVE_SEND_HANDLERS: frozenset[str] = frozenset(
    {
        "target.send_whatsapp_message",
        "target.broadcast_group",
        "outbound.send_verified_message",
    }
)


def _pass_through_stub(inputs: dict[str, Any]) -> dict[str, Any]:
    """Default handler stub that returns its inputs unchanged.

    This ensures the pipeline advances without errors during local testing.
    """
    return {"result": "stub", "inputs_received": inputs}


def _live_send_guard(inputs: dict[str, Any]) -> dict[str, Any]:
    """Handler stub that blocks live send operations in local-cli mode."""
    raise RuntimeError(
        "GUARDRAIL: live send operations are blocked in the local-cli adapter. "
        "Use a production adapter to execute real sends."
    )


class LocalCliAdapter:
    """Development adapter that reads identity from .clawwrap/identity.yaml.

    Implements AdapterProtocol.  All handler bindings return stubs unless
    a live-send guardrail applies.
    """

    # Explicit non-production marker.
    IS_PRODUCTION: bool = False
    ADAPTER_NAME: str = ADAPTER_NAME

    def __init__(
        self,
        identity_path: Path = DEFAULT_IDENTITY_PATH,
        host_state_root: Path | None = None,
    ) -> None:
        """Initialise the adapter.

        Args:
            identity_path: Path to the local identity YAML file.
            host_state_root: Root directory for local file-based host state reads.
                Defaults to the current working directory.
        """
        self._identity_path = identity_path
        self._host_state_root = host_state_root or Path(".")

    # ------------------------------------------------------------------
    # AdapterProtocol implementation
    # ------------------------------------------------------------------

    def bind_handler(self, handler_id: str) -> Callable[..., Any]:
        """Return a callable for the given handler ID.

        Live-send handlers are bound to a guardrail that raises at call time.
        All other handlers receive a pass-through stub.

        Args:
            handler_id: Dotted global handler identifier.

        Returns:
            Callable implementing the handler contract.
        """
        if handler_id in _LIVE_SEND_HANDLERS:
            return _live_send_guard
        return _pass_through_stub

    def resolve_approval_identity(
        self, evidence: ApprovalIdentityEvidence
    ) -> ApprovalRole:
        """Resolve the role from identity evidence.

        The local-cli adapter reads the role directly from the identity file
        rather than from an authoritative identity provider.

        Args:
            evidence: Identity evidence (must have been loaded from identity file).

        Returns:
            Resolved ApprovalRole.

        Raises:
            ValueError: If the identity file has no valid role or cannot be loaded.
        """
        # Verify the identity file is readable before reading the role.
        try:
            load_identity(self._identity_path)
        except OSError as exc:
            raise ValueError(f"Cannot load identity for role resolution: {exc}") from exc

        # The identity file contains the role at the top level. Re-read raw.
        import yaml

        raw_data: dict[str, Any] = {}
        if self._identity_path.exists():
            raw_data = yaml.safe_load(
                self._identity_path.read_text(encoding="utf-8")
            ) or {}

        raw_role = raw_data.get("role", "operator")
        try:
            return ApprovalRole[raw_role]
        except KeyError:
            raise ValueError(
                f"Unknown role '{raw_role}' in identity file {self._identity_path}. "
                f"Valid roles: {[r.name for r in ApprovalRole]}"
            ) from None

    def generate_artifacts(self, run: Any) -> list[dict[str, Any]]:
        """Generate artifacts for a completed run (stub for local-cli).

        Returns an empty list — the local-cli adapter does not produce
        host-native artifacts.

        Args:
            run: The completed Run.

        Returns:
            Empty list (no artifacts generated by local-cli).
        """
        return []

    def read_host_state(self, surfaces: list[str]) -> dict[str, Any]:
        """Read local file-based host state for the listed surfaces.

        Interprets each surface selector as a file path relative to
        ``host_state_root``.

        Args:
            surfaces: List of file path selectors.

        Returns:
            Dict mapping each surface to its content string, or ``None`` if missing.
        """
        state: dict[str, Any] = {}
        for surface in surfaces:
            candidate = self._host_state_root / surface
            if candidate.exists():
                state[surface] = candidate.read_text(encoding="utf-8")
            else:
                state[surface] = None
        return state

    def get_approval_identity_config(self) -> ApprovalIdentityConfig:
        """Return the approval identity configuration for this adapter.

        Returns:
            ApprovalIdentityConfig describing local-file-based identity sourcing.
        """
        return ApprovalIdentityConfig(
            source_type=ADAPTER_NAME,
            subject_key="subject_id",
            trust_basis="local-cli-development",
        )

    def validate_secret_references(self, refs: list[str]) -> list[str]:
        """Check that all secret references exist in Doppler.

        Args:
            refs: List of secret reference keys.

        Returns:
            List of invalid reference keys (empty = all valid).
            If Doppler is unavailable, returns refs unchanged (local-cli
            treats Doppler as optional during planning).
        """
        if not refs:
            return []
        try:
            return validate_references(refs)
        except DopplerUnavailableError:
            # In local-cli mode, Doppler unavailability is a warning, not a hard error.
            return []
