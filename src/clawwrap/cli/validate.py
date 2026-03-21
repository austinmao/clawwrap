"""clawwrap validate and graph CLI subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from clawwrap.engine.dag import DagResult, build_dependency_graph
from clawwrap.engine.loader import SpecRegistry, load_specs
from clawwrap.engine.validation import ValidationResult, validate_spec
from clawwrap.model.wrapper import Wrapper

# ---------------------------------------------------------------------------
# Subcommand registration
# ---------------------------------------------------------------------------


def add_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register 'validate' and 'graph' subcommands onto the root subparsers."""
    _add_validate_subcommand(subparsers)
    _add_graph_subcommand(subparsers)


def _add_validate_subcommand(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("validate", help="Validate a wrapper, policy, or adapter spec")
    p.add_argument("spec_path", metavar="spec-path", help="Path to the YAML spec file")
    p.add_argument(
        "--format",
        dest="format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p.add_argument(
        "--schema-version",
        dest="schema_version",
        type=int,
        default=None,
        help="Override schema version check",
    )


def _add_graph_subcommand(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("graph", help="Show dependency graph for a wrapper")
    p.add_argument("wrapper_name", metavar="wrapper-name", help="Wrapper name to graph")
    p.add_argument(
        "--format",
        dest="format",
        choices=["dot", "text"],
        default="text",
        help="Output format (default: text)",
    )
    p.add_argument(
        "--specs-dir",
        dest="specs_dir",
        default="specs",
        help="Specs directory to load registry from (default: specs)",
    )


# ---------------------------------------------------------------------------
# validate handler
# ---------------------------------------------------------------------------


def _schema_version_check_error(result: ValidationResult, override: int) -> str | None:
    """Return an error message if spec schema_version disagrees with override, else None."""
    if result.model is None:
        return None
    actual = getattr(result.model, "schema_version", None)
    if actual is None:
        return None
    if actual != override:
        return (
            f"Schema version mismatch: spec declares schema_version={actual}, "
            f"but --schema-version={override} was requested"
        )
    return None


def _render_validate_text(result: ValidationResult, path: str) -> str:
    """Render validation result as human-readable text."""
    lines: list[str] = []
    status = "PASS" if result.valid else "FAIL"
    lines.append(f"{status}  {path}  [{result.spec_type}]")
    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for err in result.errors:
            lines.append(f"  - {err}")
    elif result.model is not None:
        name = getattr(result.model, "name", "")
        version = getattr(result.model, "version", "")
        if name:
            lines.append(f"  name:    {name}")
        if version:
            lines.append(f"  version: {version}")
    return "\n".join(lines)


def _render_validate_json(result: ValidationResult, path: str) -> str:
    """Render validation result as JSON."""
    model_name = getattr(result.model, "name", None) if result.model else None
    model_version = getattr(result.model, "version", None) if result.model else None
    payload: dict[str, Any] = {
        "valid": result.valid,
        "spec_type": result.spec_type,
        "path": path,
        "errors": result.errors,
        "model": {"name": model_name, "version": model_version} if result.model else None,
    }
    return json.dumps(payload, indent=2)


def handle_validate(args: argparse.Namespace) -> int:
    """Execute 'clawwrap validate <spec-path>'."""
    path = Path(args.spec_path)
    result = validate_spec(path)

    # Apply schema version override check on top of normal validation.
    extra_error: str | None = None
    if result.valid and args.schema_version is not None:
        extra_error = _schema_version_check_error(result, args.schema_version)
        if extra_error:
            result = ValidationResult(
                valid=False,
                spec_type=result.spec_type,
                errors=result.errors + [extra_error],
                model=result.model,
            )

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        print(_render_validate_json(result, str(path)))
    else:
        print(_render_validate_text(result, str(path)))

    if not result.valid:
        return 2  # Exit code 2 = validation failure per CLI contract.
    return 0


# ---------------------------------------------------------------------------
# graph handler
# ---------------------------------------------------------------------------


def _load_registry_for_graph(specs_dir: Path, verbose: bool = False) -> SpecRegistry:
    """Load the spec registry, printing load errors to stderr."""
    registry = load_specs(specs_dir, verbose=verbose)
    if registry.has_errors():
        print(
            f"Warning: {len(registry.load_errors)} spec(s) failed to load:",
            file=sys.stderr,
        )
        for err in registry.load_errors:
            print(f"  {err.path}: {'; '.join(err.errors)}", file=sys.stderr)
    return registry


def _build_dag_for_wrapper(wrapper_name: str, registry: SpecRegistry) -> tuple[Wrapper | None, DagResult | None]:
    """Return the root wrapper and DAG result for a named wrapper, or (None, None) on failure."""
    root = registry.wrappers.get(wrapper_name)
    if root is None:
        return None, None

    # Build DAG from the full registry of wrappers for correct resolution.
    all_wrappers = list(registry.wrappers.values())
    dag = build_dependency_graph(all_wrappers, registry)
    return root, dag


def _render_text_tree(wrapper_name: str, registry: SpecRegistry, depth: int = 0) -> list[str]:
    """Recursively render the dependency tree as indented text."""
    prefix = "  " * depth
    lines = [f"{prefix}{wrapper_name}"]
    wrapper = registry.wrappers.get(wrapper_name)
    if wrapper is None:
        lines.append(f"{prefix}  (not found in registry)")
        return lines
    for dep in wrapper.dependencies:
        lines.extend(_render_text_tree(dep.name, registry, depth + 1))
    return lines


def _render_dot_graph(root_name: str, registry: SpecRegistry) -> str:
    """Render the dependency graph as a Graphviz DOT string."""
    edges: list[tuple[str, str]] = []
    visited: set[str] = set()

    def _collect_edges(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        w = registry.wrappers.get(name)
        if w is None:
            return
        for dep in w.dependencies:
            edges.append((name, dep.name))
            _collect_edges(dep.name)

    _collect_edges(root_name)

    lines = ["digraph clawwrap {", f'  "{root_name}";']
    for src, dst in edges:
        lines.append(f'  "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


def _render_graph_json(wrapper_name: str, dag: DagResult, registry: SpecRegistry) -> str:
    """Render graph result as JSON."""
    wrapper = registry.wrappers.get(wrapper_name)
    deps = [d.name for d in wrapper.dependencies] if wrapper else []
    payload: dict[str, Any] = {
        "wrapper": wrapper_name,
        "execution_order": dag.execution_order,
        "direct_dependencies": deps,
        "errors": dag.errors,
    }
    return json.dumps(payload, indent=2)


def handle_graph(args: argparse.Namespace) -> int:
    """Execute 'clawwrap graph <wrapper-name>'."""
    specs_dir = Path(getattr(args, "specs_dir", "specs"))
    verbose = getattr(args, "verbose", False)
    fmt = getattr(args, "format", "text")
    wrapper_name = args.wrapper_name

    registry = _load_registry_for_graph(specs_dir, verbose=verbose)

    root, dag = _build_dag_for_wrapper(wrapper_name, registry)
    if root is None:
        print(f"Error: wrapper '{wrapper_name}' not found in {specs_dir}/wrappers/", file=sys.stderr)
        return 1

    assert dag is not None  # type narrowing; _build_dag_for_wrapper returns both or neither

    if dag.errors:
        print("Dependency graph errors:", file=sys.stderr)
        for err in dag.errors:
            print(f"  {err}", file=sys.stderr)
        if any("Circular" in e for e in dag.errors):
            return 3  # Exit code 3 = cycle detected per CLI contract.

    if fmt == "dot":
        print(_render_dot_graph(wrapper_name, registry))
    elif fmt == "json":
        print(_render_graph_json(wrapper_name, dag, registry))
    else:
        lines = _render_text_tree(wrapper_name, registry)
        print("\n".join(lines))

    return 0 if not dag.errors else 1
