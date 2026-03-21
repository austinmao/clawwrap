"""T063: Unit tests for clawwrap.engine.dag.

Covers:
- Acyclic graph produces correct topological order
- Cycle detected with CycleError including cycle path
- Single wrapper with no dependencies
- Diamond dependency (A→B, A→C, B→D, C→D)
- Unresolved wrapper reference detected
"""

from __future__ import annotations

from clawwrap.engine.dag import build_dependency_graph
from clawwrap.engine.loader import SpecRegistry
from clawwrap.model.wrapper import Wrapper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_wrapper(name: str, deps: list[str] | None = None) -> Wrapper:
    """Build a minimal Wrapper object with optional dependency names."""
    from clawwrap.model.wrapper import WrapperRef

    wrapper_deps = [WrapperRef(name=d, version_constraint=">=1.0.0") for d in (deps or [])]
    return Wrapper(
        name=name,
        version="1.0.0",
        schema_version=1,
        description=f"Test wrapper {name}",
        inputs=[],
        outputs=[],
        stages=[],
        dependencies=wrapper_deps,
    )


def _empty_registry(*wrappers: Wrapper) -> SpecRegistry:
    """Create a SpecRegistry pre-populated with the given wrappers."""
    registry = SpecRegistry()
    for w in wrappers:
        registry.wrappers[w.name] = w
    return registry


# ---------------------------------------------------------------------------
# Single wrapper
# ---------------------------------------------------------------------------


class TestSingleWrapper:
    """DAG tests with a single wrapper and no dependencies."""

    def test_single_wrapper_no_deps_is_valid(self) -> None:
        """A single wrapper with no dependencies must produce a valid, ordered result."""
        w = _minimal_wrapper("alpha")
        registry = _empty_registry(w)

        result = build_dependency_graph([w], registry)

        assert result.valid is True
        assert result.errors == []
        assert "alpha" in result.execution_order

    def test_single_wrapper_appears_in_order(self) -> None:
        """The single wrapper must be the only element in execution_order."""
        w = _minimal_wrapper("only-one")
        registry = _empty_registry(w)

        result = build_dependency_graph([w], registry)

        assert result.execution_order == ["only-one"]


# ---------------------------------------------------------------------------
# Linear chain
# ---------------------------------------------------------------------------


class TestLinearChain:
    """DAG tests for a simple linear dependency chain."""

    def test_linear_chain_correct_order(self) -> None:
        """A→B means B must appear before A in execution order."""
        b = _minimal_wrapper("b")
        a = _minimal_wrapper("a", deps=["b"])
        registry = _empty_registry(a, b)

        result = build_dependency_graph([a, b], registry)

        assert result.valid is True
        order = result.execution_order
        assert order.index("b") < order.index("a")

    def test_three_node_linear_chain(self) -> None:
        """A→B→C: C appears first, then B, then A."""
        c = _minimal_wrapper("c")
        b = _minimal_wrapper("b", deps=["c"])
        a = _minimal_wrapper("a", deps=["b"])
        registry = _empty_registry(a, b, c)

        result = build_dependency_graph([a, b, c], registry)

        assert result.valid is True
        order = result.execution_order
        assert order.index("c") < order.index("b") < order.index("a")


# ---------------------------------------------------------------------------
# Diamond dependency
# ---------------------------------------------------------------------------


class TestDiamondDependency:
    """DAG tests for a diamond pattern: A→B, A→C, B→D, C→D."""

    def test_diamond_dependency_is_valid(self) -> None:
        """Diamond DAG must be valid (not a cycle)."""
        d = _minimal_wrapper("d")
        b = _minimal_wrapper("b", deps=["d"])
        c = _minimal_wrapper("c", deps=["d"])
        a = _minimal_wrapper("a", deps=["b", "c"])
        registry = _empty_registry(a, b, c, d)

        result = build_dependency_graph([a, b, c, d], registry)

        assert result.valid is True

    def test_diamond_d_before_b_and_c(self) -> None:
        """In diamond DAG, D must appear before B and C."""
        d = _minimal_wrapper("d")
        b = _minimal_wrapper("b", deps=["d"])
        c = _minimal_wrapper("c", deps=["d"])
        a = _minimal_wrapper("a", deps=["b", "c"])
        registry = _empty_registry(a, b, c, d)

        result = build_dependency_graph([a, b, c, d], registry)

        order = result.execution_order
        assert order.index("d") < order.index("b")
        assert order.index("d") < order.index("c")

    def test_diamond_a_appears_last(self) -> None:
        """In diamond DAG, A (the root) must appear last."""
        d = _minimal_wrapper("d")
        b = _minimal_wrapper("b", deps=["d"])
        c = _minimal_wrapper("c", deps=["d"])
        a = _minimal_wrapper("a", deps=["b", "c"])
        registry = _empty_registry(a, b, c, d)

        result = build_dependency_graph([a, b, c, d], registry)

        order = result.execution_order
        assert order[-1] == "a"


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    """DAG tests for cycle detection."""

    def test_direct_cycle_reports_error(self) -> None:
        """A→B and B→A must produce a cycle error in DagResult.errors."""
        a = _minimal_wrapper("a", deps=["b"])
        b = _minimal_wrapper("b", deps=["a"])
        registry = _empty_registry(a, b)

        result = build_dependency_graph([a, b], registry)

        assert result.valid is False
        assert any("circular" in e.lower() or "cycle" in e.lower() for e in result.errors)

    def test_direct_cycle_error_includes_cycle_path(self) -> None:
        """Cycle error message must name the nodes involved."""
        a = _minimal_wrapper("a", deps=["b"])
        b = _minimal_wrapper("b", deps=["a"])
        registry = _empty_registry(a, b)

        result = build_dependency_graph([a, b], registry)

        combined = " ".join(result.errors)
        # Both node names should appear in the error message.
        assert "a" in combined and "b" in combined

    def test_three_node_cycle_detected(self) -> None:
        """A→B→C→A must be detected as a cycle."""
        a = _minimal_wrapper("a", deps=["b"])
        b = _minimal_wrapper("b", deps=["c"])
        c = _minimal_wrapper("c", deps=["a"])
        registry = _empty_registry(a, b, c)

        result = build_dependency_graph([a, b, c], registry)

        assert result.valid is False

    def test_self_cycle_detected(self) -> None:
        """A→A (self-reference) must be detected as a cycle."""
        a = _minimal_wrapper("a", deps=["a"])
        registry = _empty_registry(a)

        result = build_dependency_graph([a], registry)

        assert result.valid is False


# ---------------------------------------------------------------------------
# Unresolved references
# ---------------------------------------------------------------------------


class TestUnresolvedReferences:
    """DAG tests for unresolved wrapper references."""

    def test_missing_dependency_reports_error(self) -> None:
        """Reference to a non-existent wrapper must appear in errors."""
        a = _minimal_wrapper("a", deps=["does-not-exist"])
        registry = _empty_registry(a)

        result = build_dependency_graph([a], registry)

        assert result.valid is False
        assert any("does-not-exist" in e for e in result.errors)

    def test_two_missing_deps_both_reported(self) -> None:
        """Multiple missing dependencies must all be reported."""
        a = _minimal_wrapper("a", deps=["ghost-1", "ghost-2"])
        registry = _empty_registry(a)

        result = build_dependency_graph([a], registry)

        combined = " ".join(result.errors)
        assert "ghost-1" in combined
        assert "ghost-2" in combined

    def test_empty_wrappers_list_is_valid(self) -> None:
        """An empty wrappers list must produce a valid DAG with empty order."""
        registry = SpecRegistry()
        result = build_dependency_graph([], registry)

        assert result.valid is True
        assert result.execution_order == []
