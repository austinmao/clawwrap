"""DAG construction and topological ordering for wrapper dependency graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter

from clawwrap.engine.loader import SpecRegistry
from clawwrap.model.wrapper import Wrapper


@dataclass
class DagResult:
    """Result of building the dependency graph for a set of wrappers."""

    execution_order: list[str]
    """Wrapper names in a valid topological execution order (leaves first)."""

    errors: list[str] = field(default_factory=list)
    """Non-fatal warnings or resolution failures (empty on full success)."""

    @property
    def valid(self) -> bool:
        """Return True when the graph is acyclic and all references resolved."""
        return not self.errors


def _collect_graph_edges(wrappers: list[Wrapper]) -> dict[str, set[str]]:
    """Build an adjacency map: each wrapper maps to the set of wrappers it depends on."""
    graph: dict[str, set[str]] = {}
    for w in wrappers:
        deps = {dep.name for dep in w.dependencies}
        graph[w.name] = deps
    return graph


def _validate_wrapper_refs(wrappers: list[Wrapper], registry: SpecRegistry) -> list[str]:
    """Return error strings for any WrapperRef that does not resolve in the registry."""
    errors: list[str] = []
    known = {w.name for w in wrappers} | set(registry.wrappers.keys())
    for wrapper in wrappers:
        for dep in wrapper.dependencies:
            if dep.name not in known:
                errors.append(
                    f"Wrapper '{wrapper.name}' depends on '{dep.name}' "
                    f"which is not found in the registry"
                )
    return errors


def _validate_policy_refs(wrappers: list[Wrapper], registry: SpecRegistry) -> list[str]:
    """Return error strings for any PolicyRef that does not resolve in the registry."""
    errors: list[str] = []
    for wrapper in wrappers:
        for ref in wrapper.policies:
            if ref.name not in registry.policies:
                errors.append(
                    f"Wrapper '{wrapper.name}' references policy '{ref.name}' "
                    f"which is not found in the registry"
                )
    return errors


def _try_topological_sort(graph: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """Attempt topological sort; return (order, errors).

    Returns ([], [cycle-error-message]) if a cycle is detected.
    """
    sorter: TopologicalSorter[str] = TopologicalSorter(graph)
    try:
        order = list(sorter.static_order())
        return order, []
    except CycleError as exc:
        # exc.args[1] is the list of nodes in the cycle (Python stdlib).
        cycle_nodes = exc.args[1] if len(exc.args) > 1 else []
        cycle_path = " -> ".join(str(n) for n in cycle_nodes)
        return [], [f"Circular dependency detected: {cycle_path}"]


def build_dependency_graph(wrappers: list[Wrapper], registry: SpecRegistry) -> DagResult:
    """Build and validate the wrapper dependency DAG.

    Steps:
    1. Validate all WrapperRef names resolve.
    2. Validate all PolicyRef names resolve.
    3. Build adjacency graph and run topological sort.
    4. Detect cycles and report the cycle path.

    Args:
        wrappers: The wrappers to include in the graph (typically all wrappers being validated).
        registry: The loaded SpecRegistry providing resolution context.

    Returns:
        DagResult with execution_order and any errors.
    """
    all_errors: list[str] = []

    all_errors.extend(_validate_wrapper_refs(wrappers, registry))
    all_errors.extend(_validate_policy_refs(wrappers, registry))

    # Still attempt the sort even with ref errors so cycles can also be reported.
    graph = _collect_graph_edges(wrappers)
    order, cycle_errors = _try_topological_sort(graph)
    all_errors.extend(cycle_errors)

    return DagResult(execution_order=order, errors=all_errors)
