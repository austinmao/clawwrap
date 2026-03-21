"""CLI handler subcommand group: list and test handler bindings.

Commands:
  clawwrap handler list [--adapter <name>] [--format json|text]
  clawwrap handler test <handler-id> --adapter <name>
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Exit code for unbound handler (per CLI contract).
_EXIT_UNBOUND: int = 4
_EXIT_OK: int = 0
_EXIT_ERROR: int = 1


def add_subcommands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the 'handler' subcommand group with its sub-subcommands.

    Args:
        subparsers: Root-level subparsers action from the main parser.
    """
    handler_parser = subparsers.add_parser(
        "handler",
        help="Inspect and test handler bindings",
    )
    handler_sub = handler_parser.add_subparsers(dest="handler_command")

    # handler list
    list_parser = handler_sub.add_parser(
        "list",
        help="List all registered handlers, optionally filtered by adapter",
    )
    list_parser.add_argument(
        "--adapter",
        default=None,
        metavar="NAME",
        help="Filter to handlers registered for this adapter name",
    )
    list_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    # handler test
    test_parser = handler_sub.add_parser(
        "test",
        help="Run contract tests for a specific handler binding",
    )
    test_parser.add_argument(
        "handler_id",
        metavar="HANDLER_ID",
        help="Dotted global handler identifier (e.g. group.identity_matches)",
    )
    test_parser.add_argument(
        "--adapter",
        required=True,
        metavar="NAME",
        help="Adapter name to test the handler binding against",
    )
    test_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )


def handle(args: argparse.Namespace) -> int:
    """Dispatch handler subcommands.

    Args:
        args: Parsed argument namespace.

    Returns:
        Exit code.
    """
    if not hasattr(args, "handler_command") or args.handler_command is None:
        print("Usage: clawwrap handler <list|test>", file=sys.stderr)
        return _EXIT_ERROR

    if args.handler_command == "list":
        return _handle_list(args)
    if args.handler_command == "test":
        return _handle_test(args)

    print(f"Unknown handler subcommand: {args.handler_command}", file=sys.stderr)
    return _EXIT_ERROR


def _ensure_adapter_bindings(adapter_name: str | None) -> None:
    """Import known adapter modules to trigger handler registration side-effects.

    Handler bindings are registered via ``@handler`` decorators when their
    containing module is first imported.  This function imports the appropriate
    adapter module to populate the registry before listing or testing.

    Args:
        adapter_name: Adapter to load, or None to load all known adapters.
    """
    if adapter_name in ("openclaw", None):
        import clawwrap.adapters.openclaw.adapter  # noqa: F401


def _handle_list(args: argparse.Namespace) -> int:
    """List registered handlers, optionally filtered by adapter.

    Args:
        args: Parsed argument namespace.

    Returns:
        Exit code.
    """
    from clawwrap.handlers.registry import registry

    adapter_filter: str | None = getattr(args, "adapter", None)
    _ensure_adapter_bindings(adapter_filter)
    all_handler_ids = registry.list_handlers()
    fmt: str = getattr(args, "format", "text")

    if adapter_filter is not None:
        # Filter to handler IDs that have a binding for this adapter or a wildcard.
        filtered: list[str] = []
        for hid in all_handler_ids:
            try:
                registry.get_binding(hid, adapter_filter)
                filtered.append(hid)
            except KeyError:
                pass
        handler_ids = filtered
    else:
        handler_ids = all_handler_ids

    if fmt == "json":
        output: dict[str, Any] = {
            "handlers": handler_ids,
            "adapter_filter": adapter_filter,
            "count": len(handler_ids),
        }
        print(json.dumps(output, indent=2))
        return _EXIT_OK

    # Text format.
    if not handler_ids:
        filter_note = f" for adapter '{adapter_filter}'" if adapter_filter else ""
        print(f"No handlers registered{filter_note}.")
        return _EXIT_OK

    filter_header = f"  (filtered to adapter: {adapter_filter})" if adapter_filter else ""
    print(f"Registered handlers{filter_header}:")
    for hid in handler_ids:
        print(f"  {hid}")
    return _EXIT_OK


def _handle_test(args: argparse.Namespace) -> int:
    """Run contract tests for a specific handler binding.

    Loads the global contract for the handler, attempts to bind the handler
    via the named adapter, then validates the contract's input/output schemas
    are present and structurally valid.

    Args:
        args: Parsed argument namespace.

    Returns:
        Exit code (0 = pass, 4 = unbound, 1 = error).
    """
    from clawwrap.handlers.contracts import ALL_CONTRACTS
    from clawwrap.handlers.registry import registry

    handler_id: str = args.handler_id
    adapter_name: str = args.adapter
    fmt: str = getattr(args, "format", "text")

    _ensure_adapter_bindings(adapter_name)

    # Locate the contract definition.
    contract = ALL_CONTRACTS.get(handler_id)
    if contract is None:
        msg = f"No global contract defined for handler '{handler_id}'"
        _emit_test_result(fmt, handler_id, adapter_name, passed=False, detail=msg)
        return _EXIT_ERROR

    # Verify the handler is bound for this adapter.
    try:
        registry.get_binding(handler_id, adapter_name)
    except KeyError:
        msg = f"Handler '{handler_id}' is not bound for adapter '{adapter_name}'"
        _emit_test_result(fmt, handler_id, adapter_name, passed=False, detail=msg)
        return _EXIT_UNBOUND

    # Validate that the contract schemas are structurally valid JSON Schemas.
    import jsonschema

    schema_errors: list[str] = []
    for schema_name, schema_val in [
        ("input_schema", contract.input_schema),
        ("output_schema", contract.output_schema),
    ]:
        try:
            jsonschema.Draft7Validator.check_schema(schema_val)
        except Exception as exc:  # noqa: BLE001
            schema_errors.append(f"{schema_name}: {exc}")

    if schema_errors:
        detail = "Contract schema validation failed: " + "; ".join(schema_errors)
        _emit_test_result(fmt, handler_id, adapter_name, passed=False, detail=detail)
        return _EXIT_ERROR

    detail = (
        f"Handler '{handler_id}' is bound for adapter '{adapter_name}'. "
        "Contract schemas are structurally valid."
    )
    _emit_test_result(fmt, handler_id, adapter_name, passed=True, detail=detail)
    return _EXIT_OK


def _emit_test_result(
    fmt: str,
    handler_id: str,
    adapter_name: str,
    passed: bool,
    detail: str,
) -> None:
    """Print a test result in the requested format.

    Args:
        fmt: Output format ("json" or "text").
        handler_id: Handler being tested.
        adapter_name: Adapter the handler was tested against.
        passed: Whether the test passed.
        detail: Human-readable result description.
    """
    if fmt == "json":
        print(
            json.dumps(
                {
                    "handler_id": handler_id,
                    "adapter": adapter_name,
                    "passed": passed,
                    "detail": detail,
                },
                indent=2,
            )
        )
        return

    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {handler_id} ({adapter_name})")
    print(f"  {detail}")
