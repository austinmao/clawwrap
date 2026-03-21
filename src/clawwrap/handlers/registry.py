"""Handler decorator registry for binding global handler IDs to Python callables.

Usage::

    from clawwrap.handlers.registry import handler, registry

    @handler("group.identity_matches")
    def my_impl(inputs: dict) -> dict:
        ...

    fn = registry.get_binding("group.identity_matches", "local-cli")
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from clawwrap.model.adapter import HostAdapter


class HandlerRegistry:
    """Global registry mapping handler IDs to adapter-specific callables.

    Handler functions are registered via the ``@handler`` decorator.
    Each registration associates a handler_id with an adapter_name
    (or ``"*"`` for adapter-agnostic bindings).
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        # {handler_id: {adapter_name: callable}}
        self._bindings: dict[str, dict[str, Callable[..., Any]]] = {}

    def register(
        self,
        handler_id: str,
        fn: Callable[..., Any],
        adapter_name: str = "*",
    ) -> None:
        """Register a callable for a given handler_id and adapter_name.

        Args:
            handler_id: Dotted global handler identifier (e.g. ``group.identity_matches``).
            fn: Python callable that implements the handler contract.
            adapter_name: Adapter scope for this binding.  Use ``"*"`` for
                adapter-agnostic implementations (wildcard fallback).
        """
        if handler_id not in self._bindings:
            self._bindings[handler_id] = {}
        self._bindings[handler_id][adapter_name] = fn

    def get_binding(self, handler_id: str, adapter_name: str) -> Callable[..., Any]:
        """Return the callable bound to handler_id for the given adapter.

        Looks up the adapter-specific binding first, then falls back to
        the wildcard (``"*"``) binding.

        Args:
            handler_id: Dotted global handler identifier.
            adapter_name: Name of the requesting adapter.

        Returns:
            The registered callable.

        Raises:
            KeyError: If no binding exists for the handler_id / adapter_name
                combination and no wildcard is present.
        """
        adapters = self._bindings.get(handler_id)
        if adapters is None:
            raise KeyError(
                f"No bindings registered for handler '{handler_id}'"
            )
        fn = adapters.get(adapter_name) or adapters.get("*")
        if fn is None:
            raise KeyError(
                f"No binding for handler '{handler_id}' on adapter '{adapter_name}' "
                f"(available: {sorted(adapters)})"
            )
        return fn

    def list_handlers(self) -> list[str]:
        """Return sorted list of all registered handler IDs."""
        return sorted(self._bindings)

    def validate_bindings(self, adapter: HostAdapter) -> list[str]:
        """Return handler IDs declared in the adapter spec that have no registered binding.

        Args:
            adapter: HostAdapter spec whose ``supported_handlers`` list is checked.

        Returns:
            List of unbound handler IDs (empty means all are bound).
        """
        unbound: list[str] = []
        for binding in adapter.supported_handlers:
            hid = binding.handler_id
            adapters = self._bindings.get(hid)
            if adapters is None:
                unbound.append(hid)
                continue
            if adapter.name not in adapters and "*" not in adapters:
                unbound.append(hid)
        return unbound


# Module-level singleton used by the @handler decorator.
registry: HandlerRegistry = HandlerRegistry()


def handler(
    handler_id: str,
    *,
    adapter_name: str = "*",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that registers a function in the global ``registry``.

    Args:
        handler_id: Dotted global handler identifier (e.g. ``group.identity_matches``).
        adapter_name: Adapter scope.  Defaults to ``"*"`` (wildcard / all adapters).

    Returns:
        A decorator that registers the wrapped function and returns it unchanged.

    Example::

        @handler("group.identity_matches")
        def check_identity(inputs: dict) -> dict:
            ...

        @handler("target.resolve_from_canonical", adapter_name="openclaw")
        def resolve_target(inputs: dict) -> dict:
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(handler_id, fn, adapter_name=adapter_name)
        return fn

    return decorator
