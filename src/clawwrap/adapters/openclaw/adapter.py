"""OpenClaw host adapter — production implementation of AdapterProtocol.

Bridges clawwrap's abstract run model to the OpenClaw agent runtime.
Handles handler binding, approval identity resolution (including Slack-attested
Austin approval for Ceremonia outbound flows), host state reading, and
artifact generation.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

# Register all OpenClaw handler bindings when this module is imported.
import clawwrap.adapters.openclaw.handlers.audit_log  # noqa: F401
import clawwrap.adapters.openclaw.handlers.dm_receive_verify  # noqa: F401
import clawwrap.adapters.openclaw.handlers.dm_resolve  # noqa: F401
import clawwrap.adapters.openclaw.handlers.dm_send  # noqa: F401
import clawwrap.adapters.openclaw.handlers.dm_send_gateway  # noqa: F401
import clawwrap.adapters.openclaw.handlers.email_send  # noqa: F401
import clawwrap.adapters.openclaw.handlers.email_verify_receipt  # noqa: F401
import clawwrap.adapters.openclaw.handlers.group_identity  # noqa: F401
import clawwrap.adapters.openclaw.handlers.jid_verify  # noqa: F401
import clawwrap.adapters.openclaw.handlers.outbound_submit  # noqa: F401
import clawwrap.adapters.openclaw.handlers.slack_channel_info  # noqa: F401
import clawwrap.adapters.openclaw.handlers.slack_post  # noqa: F401
import clawwrap.adapters.openclaw.handlers.target_resolve  # noqa: F401
from clawwrap.adapters.openclaw import patches as patch_mod
from clawwrap.handlers.registry import registry as global_registry
from clawwrap.model.adapter import ApprovalIdentityConfig, HostAdapter
from clawwrap.model.approval import ApprovalIdentityEvidence
from clawwrap.model.types import ApprovalRole

# Adapter name used in specs and bindings.
ADAPTER_NAME: str = "openclaw"

# Identity source type for OpenClaw gateway sessions.
_SESSION_SOURCE: str = "openclaw_session"

# Identity source type for Austin's Slack-attested approval via #lumina-bot.
_SLACK_ATTESTED_SOURCE: str = "slack_attested"

# Subject ID that identifies the operator's Slack approval (configurable via env var).
# Default is intentionally left empty; should be set by provision.py or config.
_OPERATOR_SLACK_SUBJECT: str = os.environ.get("OPERATOR_SLACK_SUBJECT", "")

# Default OpenClaw config path.
_DEFAULT_CONFIG_PATH: Path = Path(".openclaw") / "openclaw.json"


class OpenClawAdapter:
    """Production adapter targeting the OpenClaw agent runtime.

    Implements AdapterProtocol.  Handler bindings are resolved from the
    module-level global handler registry (populated by the ``@handler``
    decorators in the ``handlers/`` subpackage).

    Approval identity supports two sources:
    - ``openclaw_session``: authenticated gateway session (operator role)
    - ``slack_attested``: Austin's Slack approval from #lumina-bot (admin role)
      used for Ceremonia-bound outbound WhatsApp flows
    """

    IS_PRODUCTION: bool = True
    ADAPTER_NAME: str = ADAPTER_NAME

    def __init__(
        self,
        adapter_spec: HostAdapter | None = None,
        config_path: Path = _DEFAULT_CONFIG_PATH,
        workspace_root: Path | None = None,
    ) -> None:
        """Initialise the OpenClaw adapter.

        Args:
            adapter_spec: Loaded HostAdapter spec.  When provided, handler
                bindings are also verified against the spec's supported_handlers.
            config_path: Path to the openclaw.json config file.
            workspace_root: Workspace root used for file surface reads.
                Defaults to the current working directory.
        """
        self._spec = adapter_spec
        self._config_path = config_path
        self._workspace_root = workspace_root or Path(".")

    # ------------------------------------------------------------------
    # AdapterProtocol implementation
    # ------------------------------------------------------------------

    def bind_handler(self, handler_id: str) -> Callable[..., Any]:
        """Resolve a handler callable from the global registry for openclaw.

        Args:
            handler_id: Dotted global handler identifier.

        Returns:
            Callable registered for this handler_id under the openclaw adapter.

        Raises:
            KeyError: If no binding exists for the handler_id.
        """
        return global_registry.get_binding(handler_id, ADAPTER_NAME)

    def resolve_approval_identity(
        self,
        evidence: ApprovalIdentityEvidence,
    ) -> ApprovalRole:
        """Map identity evidence to an ApprovalRole.

        Rules:
        - ``slack_attested`` source with Austin's subject_id → admin
        - ``openclaw_session`` source → operator
        - Any other recognised source → operator
        - Unrecognised source → raises ValueError

        Args:
            evidence: Identity evidence submitted by the approver.

        Returns:
            Resolved ApprovalRole.

        Raises:
            ValueError: If the identity source is not recognised.
        """
        source = evidence.identity_source

        if source == _SLACK_ATTESTED_SOURCE:
            if _OPERATOR_SLACK_SUBJECT and evidence.subject_id == _OPERATOR_SLACK_SUBJECT:
                return ApprovalRole.admin
            # Other Slack attestations map to approver.
            return ApprovalRole.approver

        if source == _SESSION_SOURCE:
            return ApprovalRole.operator

        raise ValueError(
            f"Unrecognised identity source '{source}' for OpenClaw adapter. "
            f"Valid sources: {_SESSION_SOURCE!r}, {_SLACK_ATTESTED_SOURCE!r}"
        )

    def generate_artifacts(self, run: Any) -> list[dict[str, Any]]:
        """Generate OpenClaw-compatible wrapper runtime files from a completed run.

        Produces:
        - A runtime YAML fragment describing the resolved wrapper configuration.
        - Prompt/config fragments suitable for injection via the patch engine.

        Args:
            run: The completed Run whose outputs drive artifact generation.

        Returns:
            List of artifact dicts, each with ``type``, ``path``, and ``content``.
        """
        artifacts: list[dict[str, Any]] = []
        wrapper_name: str = getattr(run, "wrapper_name", "unknown")
        resolved_inputs: dict[str, Any] = getattr(run, "resolved_inputs", None) or {}

        # Runtime descriptor artifact.
        runtime_content = _render_runtime_descriptor(wrapper_name, resolved_inputs)
        runtime_path = f"agents/generated/{wrapper_name}-runtime.yaml"
        artifacts.append(
            {
                "type": "runtime_descriptor",
                "path": runtime_path,
                "content": runtime_content,
            }
        )

        return artifacts

    def read_host_state(self, surfaces: list[str]) -> dict[str, Any]:
        """Read owned config keys, files, and mapping entries from OpenClaw runtime.

        Interprets each surface selector as:
        - A file path relative to workspace_root (surface_type file/prompt_fragment)
        - A dotted config key in openclaw.json (surface_type config_key/mapping_entry)

        Args:
            surfaces: List of surface selector strings.

        Returns:
            Dict mapping each selector to its observed value or None if absent.
        """
        import json

        state: dict[str, Any] = {}
        config: dict[str, Any] = {}

        if self._config_path.exists():
            try:
                raw = self._config_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                config = parsed if isinstance(parsed, dict) else {}
            except (OSError, json.JSONDecodeError):
                config = {}

        for surface in surfaces:
            file_candidate = self._workspace_root / surface
            if file_candidate.exists():
                try:
                    state[surface] = file_candidate.read_text(encoding="utf-8")
                except OSError:
                    state[surface] = None
            else:
                state[surface] = _navigate_config(config, surface)

        return state

    def get_approval_identity_config(self) -> ApprovalIdentityConfig:
        """Return the approval identity configuration for this adapter.

        Returns:
            ApprovalIdentityConfig for the OpenClaw gateway session source.
        """
        return ApprovalIdentityConfig(
            source_type=_SESSION_SOURCE,
            subject_key="operator_id",
            trust_basis="OpenClaw gateway authenticated session",
        )

    def validate_secret_references(self, refs: list[str]) -> list[str]:
        """Check that all secret references are valid in Doppler.

        Args:
            refs: List of secret reference keys.

        Returns:
            List of invalid or unresolvable references (empty = all valid).
        """
        if not refs:
            return []
        from clawwrap.secrets.doppler import DopplerUnavailableError, validate_references

        try:
            return validate_references(refs)
        except DopplerUnavailableError as exc:
            raise RuntimeError(
                f"Doppler unavailable; cannot validate secret references: {exc}"
            ) from exc

    def generate_patches(
        self,
        mapping_entries: dict[str, str] | None = None,
        file_artifacts: list[dict[str, Any]] | None = None,
        prompt_fragments: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate ownership-aware patches for this adapter.

        Delegates to the OpenClaw patch generator with this adapter's owned
        surfaces as the ownership manifest.

        Args:
            mapping_entries: Dict of group-name→JID entries to patch.
            file_artifacts: List of artifact dicts with ``path`` and ``content``.
            prompt_fragments: Dict of fragment-id→content entries.

        Returns:
            List of patch dicts describing required config and file changes.
        """
        owned_patterns = (
            [s.selector_pattern for s in self._spec.owned_surfaces]
            if self._spec is not None
            else []
        )
        return patch_mod.generate_patches(
            mapping_entries=mapping_entries or {},
            file_artifacts=file_artifacts or [],
            prompt_fragments=prompt_fragments or {},
            owned_patterns=owned_patterns,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_config(config: dict[str, Any], dotted_key: str) -> Any:
    """Traverse a nested dict using a dotted key path.

    Args:
        config: Root config dict.
        dotted_key: Dot-separated path string.

    Returns:
        Value at the path, or None if any segment is missing.
    """
    node: Any = config
    for segment in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(segment)
    return node


def _render_runtime_descriptor(wrapper_name: str, resolved_inputs: dict[str, Any]) -> str:
    """Render a YAML runtime descriptor for the wrapper.

    Args:
        wrapper_name: Name of the wrapper.
        resolved_inputs: Resolved input values.

    Returns:
        YAML string describing the runtime configuration.
    """
    import yaml

    descriptor: dict[str, Any] = {
        "wrapper": wrapper_name,
        "adapter": ADAPTER_NAME,
        "resolved_inputs": resolved_inputs,
    }
    return yaml.safe_dump(descriptor, default_flow_style=False, sort_keys=True)
