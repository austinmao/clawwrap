"""Spec registry loader: discovers and validates all YAML specs under a specs directory."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from clawwrap.engine.validation import validate_spec
from clawwrap.model.adapter import HostAdapter
from clawwrap.model.policy import Policy
from clawwrap.model.wrapper import Wrapper


@dataclass
class LoadError:
    """Records a failed spec load."""

    path: Path
    errors: list[str]


@dataclass
class SpecRegistry:
    """Collection of all successfully loaded spec models keyed by name."""

    wrappers: dict[str, Wrapper] = field(default_factory=dict)
    policies: dict[str, Policy] = field(default_factory=dict)
    adapters: dict[str, HostAdapter] = field(default_factory=dict)
    load_errors: list[LoadError] = field(default_factory=list)

    def has_errors(self) -> bool:
        """Return True when one or more specs failed to load."""
        return bool(self.load_errors)


# Sub-directory names and their corresponding spec_type labels.
_SUBDIR_SPEC_TYPE: dict[str, str] = {
    "wrappers": "wrapper",
    "policies": "policy",
    "hosts": "adapter",
}


def _add_to_registry(registry: SpecRegistry, spec_type: str, model: Wrapper | Policy | HostAdapter) -> None:
    """Insert a loaded model into the appropriate registry bucket."""
    if spec_type == "wrapper" and isinstance(model, Wrapper):
        registry.wrappers[model.name] = model
    elif spec_type == "policy" and isinstance(model, Policy):
        registry.policies[model.name] = model
    elif spec_type == "adapter" and isinstance(model, HostAdapter):
        registry.adapters[model.name] = model


def load_specs(specs_dir: Path, *, verbose: bool = False) -> SpecRegistry:
    """Discover all *.yaml files under ``specs_dir/{wrappers,policies,hosts}/`` and load them.

    Each file is validated individually. Failures are recorded in
    ``SpecRegistry.load_errors`` and do not prevent other specs from loading
    (partial-load semantics).

    Args:
        specs_dir: Root specs directory containing ``wrappers/``, ``policies/``, and ``hosts/``.
        verbose: If True, print progress to stderr.

    Returns:
        A SpecRegistry populated with all successfully validated specs and any errors.
    """
    registry = SpecRegistry()

    for subdir_name, expected_type in _SUBDIR_SPEC_TYPE.items():
        subdir = specs_dir / subdir_name
        if not subdir.is_dir():
            continue

        yaml_files = sorted(subdir.glob("*.yaml"))
        for yaml_path in yaml_files:
            if verbose:
                print(f"Loading {yaml_path} ...", file=sys.stderr)

            result = validate_spec(yaml_path)
            if not result.valid or result.model is None:
                registry.load_errors.append(LoadError(path=yaml_path, errors=result.errors))
                if verbose:
                    for err in result.errors:
                        print(f"  ERROR: {err}", file=sys.stderr)
                continue

            # Warn if the detected type disagrees with the sub-directory expectation.
            if result.spec_type != expected_type:
                registry.load_errors.append(
                    LoadError(
                        path=yaml_path,
                        errors=[
                            f"Spec type mismatch: file is under '{subdir_name}/' "
                            f"but was detected as '{result.spec_type}'"
                        ],
                    )
                )
                continue

            _add_to_registry(registry, result.spec_type, result.model)

    return registry
