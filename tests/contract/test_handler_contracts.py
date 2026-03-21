"""T071: Contract tests for handler registry bindings.

Tests the HandlerRegistry API, the @handler decorator, and validate_bindings
against a HostAdapter spec.
"""

from __future__ import annotations

from typing import Any

import pytest

from clawwrap.handlers.registry import HandlerRegistry, handler
from clawwrap.model.adapter import ApprovalIdentityConfig, HandlerBinding, HostAdapter, OwnedSurfaceDeclaration
from clawwrap.model.types import SurfaceType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(handler_ids: list[str]) -> HostAdapter:
    """Build a HostAdapter spec with the given handler IDs as supported_handlers."""
    bindings = [
        HandlerBinding(
            handler_id=hid,
            contract_version="1.0.0",
            binding_module=f"clawwrap.handlers.{hid.replace('.', '_')}",
        )
        for hid in handler_ids
    ]
    return HostAdapter(
        name="contract-test-adapter",
        version="1.0.0",
        schema_version=1,
        supported_handlers=bindings,
        approval_identity=ApprovalIdentityConfig(
            source_type="test",
            subject_key="id",
            trust_basis="test",
        ),
        owned_surfaces=[
            OwnedSurfaceDeclaration(
                surface_type=SurfaceType.file,
                selector_pattern="**/*.yaml",
            )
        ],
        capabilities=[],
    )


# ---------------------------------------------------------------------------
# HandlerRegistry — register and get_binding
# ---------------------------------------------------------------------------


class TestHandlerRegistryRegister:
    """Tests for HandlerRegistry.register and get_binding."""

    def test_register_and_get_wildcard_binding(self) -> None:
        """register with adapter_name='*' must be retrievable by any adapter name."""
        reg = HandlerRegistry()

        def my_fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("my.handler", my_fn, adapter_name="*")
        result = reg.get_binding("my.handler", "any-adapter")

        assert result is my_fn

    def test_register_and_get_specific_adapter_binding(self) -> None:
        """register with a specific adapter_name must be retrievable by that name."""
        reg = HandlerRegistry()

        def specific_fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("my.handler", specific_fn, adapter_name="openclaw")
        result = reg.get_binding("my.handler", "openclaw")

        assert result is specific_fn

    def test_specific_binding_overrides_wildcard(self) -> None:
        """A specific adapter binding must take precedence over the wildcard."""
        reg = HandlerRegistry()

        def wildcard_fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"source": "wildcard"}

        def specific_fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"source": "specific"}

        reg.register("my.handler", wildcard_fn, adapter_name="*")
        reg.register("my.handler", specific_fn, adapter_name="openclaw")

        result = reg.get_binding("my.handler", "openclaw")
        assert result is specific_fn

    def test_wildcard_fallback_when_no_specific_binding(self) -> None:
        """When no specific binding exists, get_binding must fall back to wildcard."""
        reg = HandlerRegistry()

        def wildcard_fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("my.handler", wildcard_fn, adapter_name="*")
        result = reg.get_binding("my.handler", "unknown-adapter")

        assert result is wildcard_fn

    def test_get_binding_raises_for_unknown_handler_id(self) -> None:
        """get_binding with an unregistered handler_id must raise KeyError."""
        reg = HandlerRegistry()

        with pytest.raises(KeyError, match="No bindings registered"):
            reg.get_binding("nonexistent.handler", "any")

    def test_get_binding_raises_when_adapter_not_registered_and_no_wildcard(self) -> None:
        """get_binding must raise KeyError when the adapter has no binding and no wildcard."""
        reg = HandlerRegistry()

        def fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("my.handler", fn, adapter_name="specific-adapter")

        with pytest.raises(KeyError):
            reg.get_binding("my.handler", "other-adapter")


# ---------------------------------------------------------------------------
# HandlerRegistry — list_handlers
# ---------------------------------------------------------------------------


class TestHandlerRegistryListHandlers:
    """Tests for HandlerRegistry.list_handlers."""

    def test_list_handlers_empty_registry(self) -> None:
        """list_handlers on an empty registry must return an empty list."""
        reg = HandlerRegistry()
        assert reg.list_handlers() == []

    def test_list_handlers_returns_sorted_list(self) -> None:
        """list_handlers must return handler IDs in sorted order."""
        reg = HandlerRegistry()

        def fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("z.handler", fn)
        reg.register("a.handler", fn)
        reg.register("m.handler", fn)

        result = reg.list_handlers()
        assert result == ["a.handler", "m.handler", "z.handler"]

    def test_list_handlers_no_duplicates(self) -> None:
        """list_handlers must not include duplicate entries for multi-adapter registrations."""
        reg = HandlerRegistry()

        def fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("dup.handler", fn, adapter_name="adapter-a")
        reg.register("dup.handler", fn, adapter_name="adapter-b")

        result = reg.list_handlers()
        assert result.count("dup.handler") == 1


# ---------------------------------------------------------------------------
# HandlerRegistry — validate_bindings
# ---------------------------------------------------------------------------


class TestHandlerRegistryValidateBindings:
    """Tests for HandlerRegistry.validate_bindings against a HostAdapter spec."""

    def test_all_handlers_bound_returns_empty_list(self) -> None:
        """validate_bindings must return empty list when all handlers are bound."""
        reg = HandlerRegistry()

        def fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("target.resolve_from_canonical", fn, adapter_name="contract-test-adapter")
        adapter = _make_adapter(["target.resolve_from_canonical"])

        unbound = reg.validate_bindings(adapter)
        assert unbound == []

    def test_wildcard_binding_satisfies_any_adapter(self) -> None:
        """A wildcard binding must satisfy any adapter's handler requirement."""
        reg = HandlerRegistry()

        def fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        reg.register("target.resolve_from_canonical", fn, adapter_name="*")
        adapter = _make_adapter(["target.resolve_from_canonical"])

        unbound = reg.validate_bindings(adapter)
        assert unbound == []

    def test_missing_handler_binding_reported(self) -> None:
        """validate_bindings must report handler IDs without a registered binding."""
        reg = HandlerRegistry()
        adapter = _make_adapter(["group.identity_matches"])

        unbound = reg.validate_bindings(adapter)
        assert "group.identity_matches" in unbound

    def test_multiple_missing_handlers_all_reported(self) -> None:
        """validate_bindings must report all unbound handler IDs."""
        reg = HandlerRegistry()
        adapter = _make_adapter(["target.check_a", "target.check_b"])

        unbound = reg.validate_bindings(adapter)
        assert "target.check_a" in unbound
        assert "target.check_b" in unbound

    def test_no_supported_handlers_returns_empty_list(self) -> None:
        """validate_bindings on an adapter with no supported_handlers must return empty."""
        reg = HandlerRegistry()
        adapter = _make_adapter([])

        unbound = reg.validate_bindings(adapter)
        assert unbound == []


# ---------------------------------------------------------------------------
# @handler decorator
# ---------------------------------------------------------------------------


class TestHandlerDecorator:
    """Tests for the module-level @handler decorator."""

    def test_decorator_registers_function(self) -> None:
        """@handler must register the function in the module-level registry."""
        from clawwrap.handlers.registry import registry

        # Use a unique handler_id to avoid collisions with other tests.
        test_handler_id = "test.decorator_registration_unique"

        @handler(test_handler_id)  # type: ignore[untyped-decorator]  # @handler returns Callable[...,Any] which erases inner signature
        def my_test_handler(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        # Verify it was registered in the global registry.
        bound = registry.get_binding(test_handler_id, "any-adapter")
        assert bound is my_test_handler

    def test_decorator_returns_original_function(self) -> None:
        """@handler must return the original function unchanged."""

        test_handler_id = "test.decorator_returns_original_unique"

        @handler(test_handler_id)  # type: ignore[untyped-decorator]  # @handler returns Callable[...,Any] which erases inner signature
        def my_fn(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"original": True}

        # The function should be callable directly without going through the registry.
        result = my_fn({"x": 1})
        assert result == {"original": True}

    def test_decorator_with_specific_adapter_name(self) -> None:
        """@handler with adapter_name must register under that adapter scope."""
        from clawwrap.handlers.registry import registry

        test_handler_id = "test.adapter_scoped_registration_unique"

        @handler(test_handler_id, adapter_name="specific-adapter")  # type: ignore[untyped-decorator]  # @handler returns Callable[...,Any] which erases inner signature
        def specific_handler(inputs: dict[str, Any]) -> dict[str, Any]:
            return {}

        # Must be retrievable for the specific adapter.
        bound = registry.get_binding(test_handler_id, "specific-adapter")
        assert bound is specific_handler

        # Must NOT be retrievable for a different adapter without wildcard.
        with pytest.raises(KeyError):
            registry.get_binding(test_handler_id, "other-adapter")
