"""Schema validation engine: load and validate wrapper/policy/adapter YAML specs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from jsonschema import Draft7Validator

from clawwrap.model.adapter import HostAdapter
from clawwrap.model.policy import Policy
from clawwrap.model.wrapper import Wrapper
from clawwrap.schemas import host_adapter as adapter_schema_mod
from clawwrap.schemas import policy as policy_schema_mod
from clawwrap.schemas import wrapper as wrapper_schema_mod

if TYPE_CHECKING:
    from clawwrap.engine.loader import SpecRegistry

# Sentinel for when spec type cannot be determined.
UNKNOWN_SPEC_TYPE = "unknown"

# Type alias for a factory callable that builds a model from a raw dict.
_ModelFactory = Callable[[dict[str, Any]], Wrapper | Policy | HostAdapter]

# Mapping from spec_type string to (schema, factory).
_SPEC_REGISTRY: dict[str, tuple[dict[str, Any], _ModelFactory]] = {
    "wrapper": (wrapper_schema_mod.SCHEMA, Wrapper.from_dict),
    "policy": (policy_schema_mod.SCHEMA, Policy.from_dict),
    "adapter": (adapter_schema_mod.SCHEMA, HostAdapter.from_dict),
}


@dataclass
class ValidationResult:
    """Result of validating a single spec file."""

    valid: bool
    spec_type: str
    errors: list[str] = field(default_factory=list)
    model: Wrapper | Policy | HostAdapter | None = None


def _detect_spec_type(data: dict[str, Any]) -> str:
    """Detect spec type from the YAML data structure.

    Wrappers have ``inputs``/``outputs``/``stages``.
    Policies have ``checks``.
    Adapters have ``supported_handlers``/``approval_identity``/``owned_surfaces``.
    """
    if "supported_handlers" in data and "approval_identity" in data:
        return "adapter"
    if "checks" in data:
        return "policy"
    if "inputs" in data or "outputs" in data or "stages" in data:
        return "wrapper"
    return UNKNOWN_SPEC_TYPE


def _collect_schema_errors(schema: dict[str, Any], data: dict[str, Any]) -> list[str]:
    """Run jsonschema validation and collect all error messages with path context."""
    validator = Draft7Validator(schema)
    errors: list[str] = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "<root>"
        errors.append(f"{path}: {error.message}")
    return errors


def _build_model(
    spec_type: str,
    data: dict[str, Any],
) -> Wrapper | Policy | HostAdapter | None:
    """Attempt to build a typed model from raw data; return None on failure."""
    entry = _SPEC_REGISTRY.get(spec_type)
    if entry is None:
        return None
    _schema, factory = entry
    try:
        return factory(data)
    except (KeyError, ValueError, TypeError):
        return None


def validate_spec(path: Path) -> ValidationResult:
    """Load a YAML spec, detect its type, validate against schema, return a ValidationResult.

    Args:
        path: Path to the YAML spec file.

    Returns:
        ValidationResult with valid flag, detected spec_type, any errors, and
        a typed model instance on success.
    """
    if not path.exists():
        return ValidationResult(
            valid=False,
            spec_type=UNKNOWN_SPEC_TYPE,
            errors=[f"File not found: {path}"],
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult(
            valid=False,
            spec_type=UNKNOWN_SPEC_TYPE,
            errors=[f"Cannot read file: {exc}"],
        )

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return ValidationResult(
            valid=False,
            spec_type=UNKNOWN_SPEC_TYPE,
            errors=[f"YAML parse error: {exc}"],
        )

    if not isinstance(data, dict):
        return ValidationResult(
            valid=False,
            spec_type=UNKNOWN_SPEC_TYPE,
            errors=["Spec must be a YAML mapping (dict) at the top level"],
        )

    spec_type = _detect_spec_type(data)
    if spec_type == UNKNOWN_SPEC_TYPE:
        return ValidationResult(
            valid=False,
            spec_type=UNKNOWN_SPEC_TYPE,
            errors=[
                "Cannot determine spec type. "
                "Wrapper specs require 'stages'; policy specs require 'checks'; "
                "adapter specs require 'supported_handlers' and 'approval_identity'."
            ],
        )

    schema, _factory = _SPEC_REGISTRY[spec_type]
    schema_errors = _collect_schema_errors(schema, data)
    if schema_errors:
        return ValidationResult(valid=False, spec_type=spec_type, errors=schema_errors)

    model = _build_model(spec_type, data)
    if model is None:
        return ValidationResult(
            valid=False,
            spec_type=spec_type,
            errors=["Spec passed schema validation but model construction failed"],
        )

    return ValidationResult(valid=True, spec_type=spec_type, model=model)


class UnboundHandlerError(Exception):
    """Raised when a policy references handler IDs not supported by the adapter.

    Attributes:
        missing: Sorted list of handler IDs that could not be bound.
    """

    def __init__(self, missing: list[str]) -> None:
        """Initialise with the list of missing handler IDs."""
        self.missing = sorted(missing)
        super().__init__(
            f"Unbound handlers: {', '.join(self.missing)}"
        )


def resolve_policies(
    wrapper: Wrapper,
    registry: SpecRegistry,
    adapter: HostAdapter,
) -> list[Policy]:
    """Load all policies referenced by a wrapper and validate handler bindings.

    Collects all ``handler_id`` values across every referenced policy, then
    checks each one against the adapter's ``supported_handlers`` list.  Fails
    closed: if *any* handler cannot be bound, raises ``UnboundHandlerError``
    listing every missing ID.

    Args:
        wrapper: The Wrapper whose ``policies`` list is resolved.
        registry: Registry of loaded specs, used to look up Policy objects by name.
        adapter: Host adapter whose ``supported_handlers`` set constrains which
            handler IDs are permissible.

    Returns:
        Ordered list of Policy objects corresponding to the wrapper's policy refs.

    Raises:
        KeyError: If a policy referenced by the wrapper is not in the registry.
        UnboundHandlerError: If one or more handler IDs in the resolved policies
            are not declared in ``adapter.supported_handlers``.
    """
    supported: frozenset[str] = frozenset(
        b.handler_id for b in adapter.supported_handlers
    )

    policies: list[Policy] = []
    missing_handlers: list[str] = []

    for policy_ref in wrapper.policies:
        policy = registry.policies.get(policy_ref.name)
        if policy is None:
            raise KeyError(
                f"Policy '{policy_ref.name}' referenced by wrapper "
                f"'{wrapper.name}' not found in registry"
            )
        policies.append(policy)
        for check in policy.checks:
            if check.handler_id not in supported:
                missing_handlers.append(check.handler_id)

    if missing_handlers:
        raise UnboundHandlerError(list(dict.fromkeys(missing_handlers)))

    return policies
