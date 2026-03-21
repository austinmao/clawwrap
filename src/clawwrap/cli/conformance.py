"""CLI subcommand group: ``clawwrap conformance``

Subcommands: check | exception
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Sub-parser registration
# ---------------------------------------------------------------------------


def add_subcommands(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the ``conformance`` subcommand group onto *subparsers*."""
    conf_parser = subparsers.add_parser(
        "conformance",
        help="Post-apply conformance checking and drift exception management",
    )
    conf_sub = conf_parser.add_subparsers(dest="conformance_subcommand")

    # conformance check
    check_p = conf_sub.add_parser("check", help="Run conformance check for a run")
    check_p.add_argument("run_id", help="Run UUID")
    check_p.add_argument("--format", choices=["json", "text"], default="text")

    # conformance exception
    exc_p = conf_sub.add_parser(
        "exception",
        help="Record a drift exception for a drifted run",
    )
    exc_p.add_argument("run_id", help="Run UUID")
    exc_p.add_argument(
        "--reason",
        required=True,
        help="Reason for accepting the drift exception",
    )
    exc_p.add_argument(
        "--identity",
        default=".clawwrap/identity.yaml",
        help="Path to identity evidence file (default: .clawwrap/identity.yaml)",
    )
    exc_p.add_argument("--format", choices=["json", "text"], default="text")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def handle(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate conformance subcommand handler.

    Args:
        args: Parsed argument namespace.

    Returns:
        CLI exit code.
    """
    sub = getattr(args, "conformance_subcommand", None)
    if sub is None:
        print(
            "Usage: clawwrap conformance <check|exception>",
            file=sys.stderr,
        )
        return 1

    dispatch: dict[str, Any] = {
        "check": _handle_check,
        "exception": _handle_exception,
    }
    fn = dispatch.get(sub)
    if fn is None:
        print(f"Unknown conformance subcommand: {sub}", file=sys.stderr)
        return 1
    return fn(args)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _handle_check(args: argparse.Namespace) -> int:
    """Handle ``clawwrap conformance check <run-id>``."""
    run_id = _parse_uuid(args.run_id)
    if run_id is None:
        return 1

    store = _get_store(args)
    if store is None:
        return 8

    run = store.get_run(run_id)
    if run is None:
        print(f"Run {run_id} not found.", file=sys.stderr)
        return 1

    from clawwrap.model.types import RunStatus

    if run.status != RunStatus.conformance_pending:
        print(
            f"Run {run_id} is not in 'conformance_pending' status "
            f"(current: {run.status.value}).",
            file=sys.stderr,
        )
        return 1

    adapter = _get_adapter(run.adapter_name)
    if adapter is None:
        print(f"Unknown adapter: {run.adapter_name}", file=sys.stderr)
        return 1

    from clawwrap.engine.conformance import ConformanceResult, check_conformance
    from clawwrap.model.types import ConformanceStatus

    try:
        result: ConformanceResult = check_conformance(run, adapter, store)
    except Exception as exc:
        print(f"Conformance check failed: {exc}", file=sys.stderr)
        return 1

    result_dict = result.to_dict()
    fmt: str = args.format
    _output(result_dict, fmt, text_fn=_format_conformance_text)

    if result.status == ConformanceStatus.drifted:
        return 7  # drift detected — per CLI contract
    return 0


def _handle_exception(args: argparse.Namespace) -> int:
    """Handle ``clawwrap conformance exception <run-id>``."""
    run_id = _parse_uuid(args.run_id)
    if run_id is None:
        return 1

    store = _get_store(args)
    if store is None:
        return 8

    run = store.get_run(run_id)
    if run is None:
        print(f"Run {run_id} not found.", file=sys.stderr)
        return 1

    identity_path = Path(args.identity)
    from clawwrap.adapters.local_cli.identity import IdentityFileError, load_identity

    try:
        evidence = load_identity(identity_path)
    except IdentityFileError as exc:
        print(f"Identity error: {exc}", file=sys.stderr)
        return 6

    adapter = _get_adapter(run.adapter_name)
    if adapter is None:
        print(f"Unknown adapter: {run.adapter_name}", file=sys.stderr)
        return 1

    from clawwrap.engine.conformance import (
        InsufficientExceptionRoleError,
        NoDriftToExceptError,
        record_exception,
    )

    try:
        exc_record = record_exception(
            run_id=run_id,
            reason=args.reason,
            identity_evidence=evidence,
            store=store,
            adapter=adapter,
        )
    except NoDriftToExceptError as exc:
        print(f"Not drifted: {exc}", file=sys.stderr)
        return 1
    except InsufficientExceptionRoleError as exc:
        print(f"Insufficient role: {exc}", file=sys.stderr)
        return 6
    except Exception as exc:
        print(f"Exception recording failed: {exc}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "run_id": str(run_id),
        "exception_id": str(exc_record.id),
        "reason": exc_record.reason,
        "role": exc_record.role.name,
        "subject_id": exc_record.subject_id,
        "recorded_at": exc_record.recorded_at.isoformat(),
        "status": "exception_recorded",
    }
    _output(
        result,
        args.format,
        text_fn=lambda d: (
            f"Drift exception recorded for run {d['run_id']} "
            f"(role: {d['role']}, subject: {d['subject_id']})\n"
            f"  reason: {d['reason']}"
        ),
    )
    return 0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_conformance_text(result: dict[str, Any]) -> str:
    """Format a conformance result as human-readable text."""
    lines = [
        f"Conformance Result: {result.get('id', 'unknown')}",
        f"  run_id  : {result.get('run_id', 'unknown')}",
        f"  status  : {result.get('status', 'unknown')}",
        f"  checked : {result.get('checked_at', 'unknown')}",
    ]
    surfaces = result.get("surfaces", [])
    if surfaces:
        lines.append(f"  surfaces: {len(surfaces)} checked")
        for surf in surfaces:
            icon = "OK" if surf.get("status") == "matching" else "DRIFT"
            lines.append(f"    [{icon}] {surf.get('surface_path', '?')}")
            if surf.get("detail"):
                lines.append(f"           {surf['detail']}")
    else:
        lines.append("  surfaces: (none checked)")
    return "\n".join(lines)


def _output(
    data: Any,
    fmt: str,
    text_fn: Any = None,
) -> None:
    """Print data in the requested format."""
    if fmt == "json":
        print(json.dumps(data, indent=2))
    else:
        if text_fn is not None:
            print(text_fn(data))
        else:
            print(str(data))


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _parse_uuid(value: str) -> uuid.UUID | None:
    """Parse a UUID string, printing an error on failure."""
    try:
        return uuid.UUID(value)
    except ValueError:
        print(f"Invalid UUID: {value!r}", file=sys.stderr)
        return None


def _get_store(args: argparse.Namespace) -> Any | None:
    """Build a RunStore from CLI args."""
    db_url: str | None = getattr(args, "db_url", None)
    if db_url is None:
        config_path = Path(getattr(args, "config", ".clawwrap/config.yaml"))
        if config_path.exists():
            try:
                import yaml

                cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                db_url = cfg.get("db_url")
            except Exception:
                pass
    if not db_url:
        print(
            "Database URL not configured. Use --db-url or set db_url in .clawwrap/config.yaml.",
            file=sys.stderr,
        )
        return None

    from clawwrap.store.postgres import PostgresRunStore

    try:
        store = PostgresRunStore(db_url)
        store.list_runs(limit=1)
        return store
    except Exception as exc:
        print(f"Database unavailable: {exc}", file=sys.stderr)
        return None


def _get_adapter(adapter_name: str | None) -> Any | None:
    """Return an adapter instance for the given name."""
    if adapter_name in ("local-cli", "local_cli", None):
        from clawwrap.adapters.local_cli.adapter import LocalCliAdapter

        return LocalCliAdapter()
    if adapter_name in ("openclaw", "open_claw"):
        from clawwrap.adapters.openclaw.adapter import OpenClawAdapter

        return OpenClawAdapter()
    return None
