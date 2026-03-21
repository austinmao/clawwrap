"""CLI subcommand group: ``clawwrap run``

Subcommands: start | resume | status | approve | list | inspect
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
    """Register the ``run`` subcommand group onto *subparsers*."""
    run_parser = subparsers.add_parser("run", help="Manage staged wrapper runs")
    run_sub = run_parser.add_subparsers(dest="run_subcommand")

    # run start
    start_p = run_sub.add_parser("start", help="Start a new staged run")
    start_p.add_argument("wrapper", help="Wrapper spec name")
    start_p.add_argument("--adapter", required=True, help="Host adapter name")
    start_p.add_argument(
        "--input",
        dest="inputs",
        action="append",
        metavar="KEY=VALUE",
        default=[],
        help="Input value (repeatable: --input key=value)",
    )
    start_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and validate without creating a persistent run",
    )
    start_p.add_argument("--format", choices=["json", "text"], default="text")

    # run resume
    resume_p = run_sub.add_parser("resume", help="Resume a paused run")
    resume_p.add_argument("run_id", help="Run UUID")
    resume_p.add_argument("--format", choices=["json", "text"], default="text")

    # run status
    status_p = run_sub.add_parser("status", help="Show current run state")
    status_p.add_argument("run_id", help="Run UUID")
    status_p.add_argument("--format", choices=["json", "text"], default="text")

    # run approve
    approve_p = run_sub.add_parser("approve", help="Submit approval for a run")
    approve_p.add_argument("run_id", help="Run UUID")
    approve_p.add_argument(
        "--identity",
        default=".clawwrap/identity.yaml",
        help="Path to identity evidence file (default: .clawwrap/identity.yaml)",
    )
    approve_p.add_argument("--format", choices=["json", "text"], default="text")

    # run list
    list_p = run_sub.add_parser("list", help="List runs")
    list_p.add_argument("--status", default=None, help="Filter by run status")
    list_p.add_argument("--wrapper", default=None, help="Filter by wrapper name")
    list_p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    list_p.add_argument("--format", choices=["json", "text"], default="text")

    # run inspect
    inspect_p = run_sub.add_parser("inspect", help="Full run detail with evidence")
    inspect_p.add_argument("run_id", help="Run UUID")
    inspect_p.add_argument("--phase", default=None, help="Filter to specific phase")
    inspect_p.add_argument("--format", choices=["json", "text"], default="text")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def handle(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate run subcommand handler.

    Args:
        args: Parsed argument namespace (must have ``run_subcommand`` set).

    Returns:
        CLI exit code.
    """
    sub = getattr(args, "run_subcommand", None)
    if sub is None:
        print("Usage: clawwrap run <start|resume|status|approve|list|inspect>", file=sys.stderr)
        return 1

    handlers: dict[str, Any] = {
        "start": _handle_start,
        "resume": _handle_resume,
        "status": _handle_status,
        "approve": _handle_approve,
        "list": _handle_list,
        "inspect": _handle_inspect,
    }
    fn = handlers.get(sub)
    if fn is None:
        print(f"Unknown run subcommand: {sub}", file=sys.stderr)
        return 1
    return fn(args)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _handle_start(args: argparse.Namespace) -> int:
    """Handle ``clawwrap run start``."""
    inputs = _parse_inputs(args.inputs)
    fmt: str = args.format

    if args.dry_run:
        plan: dict[str, Any] = {
            "dry_run": True,
            "wrapper": args.wrapper,
            "adapter": args.adapter,
            "inputs": inputs,
            "phases": ["resolve", "verify", "approve", "execute", "audit"],
        }
        _output(plan, fmt, text_fn=_format_dry_run)
        return 0

    store = _get_store(args)
    if store is None:
        return 8  # database unavailable

    adapter = _get_adapter(args.adapter)
    if adapter is None:
        print(f"Unknown adapter: {args.adapter}", file=sys.stderr)
        return 1

    registry = _get_spec_registry(args)
    wrapper = registry.wrappers.get(args.wrapper) if registry else None
    if wrapper is None:
        print(f"Wrapper '{args.wrapper}' not found in spec registry.", file=sys.stderr)
        return 2

    from clawwrap.engine.runner import Runner, StoreUnavailableError

    runner = Runner(store, adapter)
    try:
        run = runner.start_run(wrapper, inputs=inputs)
    except StoreUnavailableError as exc:
        print(f"Database unavailable: {exc}", file=sys.stderr)
        return 8
    except ValueError as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 2

    _output(
        _run_to_dict(run),
        fmt,
        text_fn=lambda d: f"Run started: {d['id']} (status: {d['status']})",
    )
    return 0


def _handle_resume(args: argparse.Namespace) -> int:
    """Handle ``clawwrap run resume``."""
    run_id = _parse_uuid(args.run_id)
    if run_id is None:
        return 1

    store = _get_store(args)
    if store is None:
        return 8

    adapter = _get_adapter(_get_adapter_name_from_args(args))

    from clawwrap.engine.runner import Runner

    runner = Runner(store, adapter)
    try:
        run = runner.resume(run_id)
    except KeyError:
        print(f"Run {run_id} not found.", file=sys.stderr)
        return 1

    _output(
        _run_to_dict(run),
        args.format,
        text_fn=lambda d: f"Run {d['id']} resumed at phase '{d['current_phase']}' (status: {d['status']})",
    )
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    """Handle ``clawwrap run status``."""
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

    _output(
        _run_to_dict(run),
        args.format,
        text_fn=_format_run_status,
    )
    return 0


def _handle_approve(args: argparse.Namespace) -> int:
    """Handle ``clawwrap run approve``."""
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

    if run.status != RunStatus.awaiting_approval:
        print(
            f"Run {run_id} is not awaiting approval (current status: {run.status.value}).",
            file=sys.stderr,
        )
        return 5  # approval required (wrong state)

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

    registry = _get_spec_registry(args)
    wrapper = registry.wrappers.get(run.wrapper_name) if registry else None
    if wrapper is None:
        print(f"Wrapper '{run.wrapper_name}' not found in spec registry.", file=sys.stderr)
        return 2

    from clawwrap.engine.approval import ApprovalError, InsufficientRoleError, submit_approval

    try:
        record = submit_approval(
            run_id=run_id,
            identity_evidence=evidence,
            store=store,
            adapter=adapter,
            wrapper=wrapper,
        )
    except InsufficientRoleError as exc:
        print(f"Insufficient role: {exc}", file=sys.stderr)
        return 6
    except ApprovalError as exc:
        print(f"Approval error: {exc}", file=sys.stderr)
        return 6

    # Advance run to 'approved' status.
    from clawwrap.model.types import RunStatus

    store.update_run_status(run_id, RunStatus.approved)

    result: dict[str, Any] = {
        "run_id": str(run_id),
        "approval_id": str(record.id),
        "role": record.role.name,
        "subject_id": record.subject_id,
        "approval_hash": record.approval_hash,
    }
    _output(
        result,
        args.format,
        text_fn=lambda d: (
            f"Approved run {d['run_id']} "
            f"(role: {d['role']}, subject: {d['subject_id']})"
        ),
    )
    return 0


def _handle_list(args: argparse.Namespace) -> int:
    """Handle ``clawwrap run list``."""
    store = _get_store(args)
    if store is None:
        return 8

    from clawwrap.model.types import RunStatus

    status_filter = None
    if args.status:
        try:
            status_filter = RunStatus(args.status)
        except ValueError:
            print(f"Unknown status: {args.status}", file=sys.stderr)
            return 1

    runs = store.list_runs(
        status=status_filter,
        wrapper=args.wrapper,
        limit=args.limit,
    )
    runs_data = [_run_to_dict(r) for r in runs]

    _output(
        runs_data,
        args.format,
        text_fn=_format_run_table,
    )
    return 0


def _handle_inspect(args: argparse.Namespace) -> int:
    """Handle ``clawwrap run inspect``.

    Uses get_run_detail() for full evidence including transitions,
    approvals, apply plans, conformance results, and drift exceptions.
    Supports --phase filter to show specific phase evidence only.
    """
    run_id = _parse_uuid(args.run_id)
    if run_id is None:
        return 1

    store = _get_store(args)
    if store is None:
        return 8

    detail = store.get_run_detail(run_id)
    if detail is None:
        print(f"Run {run_id} not found.", file=sys.stderr)
        return 1

    phase_filter = getattr(args, "phase", None)
    if phase_filter:
        detail["transitions"] = [
            t for t in detail.get("transitions", [])
            if t.get("to_phase") == phase_filter or t.get("from_phase") == phase_filter
        ]

    _output(
        detail,
        args.format,
        text_fn=_format_run_detail_full,
    )
    return 0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _run_to_dict(run: Any) -> dict[str, Any]:
    """Convert a Run dataclass to a serialisable dict."""
    return {
        "id": str(run.id),
        "wrapper_name": run.wrapper_name,
        "wrapper_version": run.wrapper_version,
        "adapter_name": run.adapter_name,
        "current_phase": run.current_phase.value,
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "resolved_inputs": run.resolved_inputs,
    }


def _format_dry_run(plan: dict[str, Any]) -> str:
    lines = [
        "[dry-run] Would start run:",
        f"  wrapper : {plan['wrapper']}",
        f"  adapter : {plan['adapter']}",
        f"  inputs  : {plan['inputs']}",
        f"  phases  : {' → '.join(plan['phases'])}",
        "(no run created)",
    ]
    return "\n".join(lines)


def _format_run_status(d: dict[str, Any]) -> str:
    return (
        f"Run {d['id']}\n"
        f"  wrapper : {d['wrapper_name']} v{d['wrapper_version']}\n"
        f"  adapter : {d['adapter_name']}\n"
        f"  phase   : {d['current_phase']}\n"
        f"  status  : {d['status']}\n"
        f"  created : {d['created_at']}"
    )


def _format_run_table(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "No runs found."
    header = f"{'ID':<38}  {'WRAPPER':<25}  {'STATUS':<22}  CREATED"
    sep = "-" * len(header)
    rows = [header, sep]
    for r in runs:
        rows.append(
            f"{r['id']:<38}  {r['wrapper_name']:<25}  {r['status']:<22}  {r['created_at']}"
        )
    return "\n".join(rows)


def _format_run_detail(d: dict[str, Any]) -> str:
    lines = [
        f"Run {d['id']}",
        f"  wrapper : {d['wrapper_name']} v{d['wrapper_version']}",
        f"  adapter : {d['adapter_name']}",
        f"  phase   : {d['current_phase']}",
        f"  status  : {d['status']}",
        f"  created : {d['created_at']}",
        f"  updated : {d['updated_at']}",
    ]
    if d.get("resolved_inputs"):
        lines.append(f"  inputs  : {json.dumps(d['resolved_inputs'], indent=4)}")
    return "\n".join(lines)


def _format_run_detail_full(d: dict[str, Any]) -> str:
    """Format full run detail with all evidence."""
    run = d.get("run", d)
    lines = [
        f"Run {run.get('id', 'unknown')}",
        f"  wrapper : {run.get('wrapper_name', '')} v{run.get('wrapper_version', '')}",
        f"  adapter : {run.get('adapter_name', '')}",
        f"  phase   : {run.get('current_phase', '')}",
        f"  status  : {run.get('status', '')}",
        f"  created : {run.get('created_at', '')}",
        f"  updated : {run.get('updated_at', '')}",
    ]
    if run.get("resolved_inputs"):
        lines.append(f"  inputs  : {json.dumps(run['resolved_inputs'], indent=4)}")

    transitions = d.get("transitions", [])
    if transitions:
        lines.append("")
        lines.append(f"  Stage Transitions ({len(transitions)}):")
        for t in transitions:
            from_p = t.get("from_phase", "—")
            to_p = t.get("to_phase", "?")
            at = t.get("transitioned_at", "")
            lines.append(f"    {from_p} → {to_p}  ({at})")

    approvals = d.get("approvals", [])
    if approvals:
        lines.append("")
        lines.append(f"  Approvals ({len(approvals)}):")
        for a in approvals:
            lines.append(f"    identity_source : {a.get('identity_source', '')}")
            lines.append(f"    subject_id      : {a.get('subject_id', '')}")
            lines.append(f"    issued_at       : {a.get('issued_at', '')}")
            lines.append(f"    trust_basis     : {a.get('trust_basis', '')}")
            lines.append(f"    role            : {a.get('role', '')}")
            lines.append(f"    approval_hash   : {a.get('approval_hash', '')}")
            lines.append(f"    valid           : {a.get('valid', '')}")

    plans = d.get("apply_plans", [])
    if plans:
        lines.append("")
        lines.append(f"  Apply Plans ({len(plans)}):")
        for p in plans:
            lines.append(f"    plan_id    : {p.get('id', '')}")
            lines.append(f"    created_at : {p.get('created_at', '')}")

    conformance = d.get("conformance_results", [])
    if conformance:
        lines.append("")
        lines.append(f"  Conformance Results ({len(conformance)}):")
        for c in conformance:
            lines.append(f"    status     : {c.get('status', '')}")
            lines.append(f"    checked_at : {c.get('checked_at', '')}")

    exceptions = d.get("drift_exceptions", [])
    if exceptions:
        lines.append("")
        lines.append(f"  Drift Exceptions ({len(exceptions)}):")
        for e in exceptions:
            lines.append(f"    reason     : {e.get('reason', '')}")
            lines.append(f"    role       : {e.get('role', '')}")
            lines.append(f"    recorded_at: {e.get('recorded_at', '')}")

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
# Dependency helpers (store, adapter, registry)
# ---------------------------------------------------------------------------


def _parse_uuid(value: str) -> uuid.UUID | None:
    """Parse a UUID string, printing an error and returning None on failure."""
    try:
        return uuid.UUID(value)
    except ValueError:
        print(f"Invalid UUID: {value!r}", file=sys.stderr)
        return None


def _parse_inputs(raw: list[str]) -> dict[str, Any]:
    """Parse ``KEY=VALUE`` strings into a dict."""
    result: dict[str, Any] = {}
    for item in raw:
        if "=" not in item:
            print(f"Warning: ignoring malformed input '{item}' (expected KEY=VALUE)", file=sys.stderr)
            continue
        key, _, value = item.partition("=")
        result[key.strip()] = value.strip()
    return result


def _get_store(args: argparse.Namespace) -> Any | None:
    """Build a RunStore from CLI args (db-url or config file)."""
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
        store.list_runs(limit=1)  # probe
        return store
    except Exception as exc:
        print(f"Database unavailable: {exc}", file=sys.stderr)
        return None


def _get_adapter(adapter_name: str | None) -> Any:
    """Return an adapter instance for the given name."""
    if adapter_name in ("local-cli", "local_cli", None):
        from clawwrap.adapters.local_cli.adapter import LocalCliAdapter

        return LocalCliAdapter()
    if adapter_name in ("openclaw", "open_claw"):
        from clawwrap.adapters.openclaw.adapter import OpenClawAdapter

        return OpenClawAdapter()
    return None


def _get_adapter_name_from_args(args: argparse.Namespace) -> str | None:
    """Extract adapter name from args if present."""
    return getattr(args, "adapter", None)


def _get_spec_registry(args: argparse.Namespace) -> Any | None:
    """Load the SpecRegistry from the specs directory in config."""
    config_path = Path(getattr(args, "config", ".clawwrap/config.yaml"))
    specs_dir: Path | None = None

    if config_path.exists():
        try:
            import yaml

            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            specs_dir_raw = cfg.get("specs_dir", "specs")
            specs_dir = Path(specs_dir_raw)
        except Exception:
            pass

    if specs_dir is None:
        specs_dir = Path("specs")

    if not specs_dir.is_dir():
        return None

    from clawwrap.engine.loader import load_specs

    return load_specs(specs_dir)
