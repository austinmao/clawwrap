"""CLI subcommand group: ``clawwrap apply``

Subcommands: plan | approve | mark-applied
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
    """Register the ``apply`` subcommand group onto *subparsers*."""
    apply_parser = subparsers.add_parser("apply", help="Manage host apply lifecycle")
    apply_sub = apply_parser.add_subparsers(dest="apply_subcommand")

    # apply plan
    plan_p = apply_sub.add_parser("plan", help="Show semantic apply plan for a run")
    plan_p.add_argument("run_id", help="Run UUID")
    plan_p.add_argument(
        "--format",
        choices=["json", "text", "diff"],
        default="text",
        help="Output format (default: text)",
    )

    # apply approve
    approve_p = apply_sub.add_parser(
        "approve",
        help="Approve the apply plan batch with authenticated identity",
    )
    approve_p.add_argument("run_id", help="Run UUID")
    approve_p.add_argument(
        "--identity",
        default=".clawwrap/identity.yaml",
        help="Path to identity evidence file (default: .clawwrap/identity.yaml)",
    )
    approve_p.add_argument("--format", choices=["json", "text"], default="text")

    # apply mark-applied
    mark_p = apply_sub.add_parser(
        "mark-applied",
        help="Transition run to conformance_pending (mark host apply as done)",
    )
    mark_p.add_argument("run_id", help="Run UUID")
    mark_p.add_argument("--format", choices=["json", "text"], default="text")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def handle(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate apply subcommand handler.

    Args:
        args: Parsed argument namespace.

    Returns:
        CLI exit code.
    """
    sub = getattr(args, "apply_subcommand", None)
    if sub is None:
        print(
            "Usage: clawwrap apply <plan|approve|mark-applied>",
            file=sys.stderr,
        )
        return 1

    dispatch: dict[str, Any] = {
        "plan": _handle_plan,
        "approve": _handle_approve,
        "mark-applied": _handle_mark_applied,
    }
    fn = dispatch.get(sub)
    if fn is None:
        print(f"Unknown apply subcommand: {sub}", file=sys.stderr)
        return 1
    return fn(args)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _handle_plan(args: argparse.Namespace) -> int:
    """Handle ``clawwrap apply plan <run-id>``."""
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

    allowed = {
        RunStatus.planned,
        RunStatus.host_apply_in_progress,
        RunStatus.conformance_pending,
        RunStatus.applied,
        RunStatus.drifted,
        RunStatus.exception_recorded,
    }
    if run.status not in allowed:
        print(
            f"Run {run_id} has no apply plan yet (status: {run.status.value}). "
            "The run must reach 'planned' status first.",
            file=sys.stderr,
        )
        return 1

    adapter = _get_adapter(run.adapter_name)
    if adapter is None:
        print(f"Unknown adapter: {run.adapter_name}", file=sys.stderr)
        return 1

    from clawwrap.engine.planner import ApplyPlan, generate_apply_plan

    try:
        plan: ApplyPlan = generate_apply_plan(run, adapter)
    except Exception as exc:
        print(f"Plan generation error: {exc}", file=sys.stderr)
        return 1

    plan.id = store.save_apply_plan(
        run_id=run.id,
        plan_content=plan.plan_content,
        patch_items=plan.patch_items,
        ownership_manifest=plan.ownership_manifest,
        approval_hash=plan.approval_hash,
    )

    plan_dict = plan.to_dict()
    fmt: str = args.format

    if fmt == "diff":
        _print_plan_diff(plan_dict)
    else:
        _output(plan_dict, fmt, text_fn=_format_plan_text)
    return 0


def _handle_approve(args: argparse.Namespace) -> int:
    """Handle ``clawwrap apply approve <run-id>``."""
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

    if run.status != RunStatus.planned:
        print(
            f"Run {run_id} is not in 'planned' status (current: {run.status.value}). "
            "Apply approval requires a planned run.",
            file=sys.stderr,
        )
        return 5

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
        print(
            f"Wrapper '{run.wrapper_name}' not found in spec registry.",
            file=sys.stderr,
        )
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

    result: dict[str, Any] = {
        "run_id": str(run_id),
        "approval_id": str(record.id),
        "role": record.role.name,
        "subject_id": record.subject_id,
        "approval_hash": record.approval_hash,
        "status": "apply_approved",
    }
    _output(
        result,
        args.format,
        text_fn=lambda d: (
            f"Apply plan approved for run {d['run_id']} "
            f"(role: {d['role']}, subject: {d['subject_id']})"
        ),
    )
    return 0


def _handle_mark_applied(args: argparse.Namespace) -> int:
    """Handle ``clawwrap apply mark-applied <run-id>``.

    Checks that an apply approval is recorded before transitioning.
    Transitions: planned → host_apply_in_progress → conformance_pending.
    """
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

    if run.status != RunStatus.planned:
        print(
            f"Run {run_id} is not in 'planned' status (current: {run.status.value}). "
            "Use 'apply approve' first.",
            file=sys.stderr,
        )
        return 1

    adapter = _get_adapter(run.adapter_name)
    if adapter is None:
        print(f"Unknown adapter: {run.adapter_name}", file=sys.stderr)
        return 1

    from clawwrap.engine.runner import InvalidTransitionError, Runner

    runner = Runner(store, adapter)
    try:
        run = runner.mark_host_apply_started(run_id)
        run = runner.mark_host_apply_done(run.id)
    except InvalidTransitionError as exc:
        print(f"Transition error: {exc}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "run_id": str(run_id),
        "status": run.status.value,
    }
    _output(
        result,
        args.format,
        text_fn=lambda d: (
            f"Run {d['run_id']} marked as applied. "
            f"Status: {d['status']}. Ready for conformance check."
        ),
    )
    return 0


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_plan_text(plan: dict[str, Any]) -> str:
    """Format an apply plan as human-readable text."""
    content = plan.get("plan_content", {})
    patch_items = plan.get("patch_items", [])
    lines = [
        f"Apply Plan: {plan.get('id', 'unknown')}",
        f"  run_id  : {plan.get('run_id', 'unknown')}",
        f"  wrapper : {content.get('wrapper_name', 'unknown')} "
        f"v{content.get('wrapper_version', '?')}",
        f"  patches : {len(patch_items)} item(s)",
    ]
    if patch_items:
        lines.append("  items:")
        for item in patch_items:
            lines.append(
                f"    [{item.get('patch_type', 'unknown')}] {item.get('surface_path', '?')}"
            )
    if plan.get("approval_hash"):
        lines.append(f"  hash    : {plan['approval_hash'][:12]}...")
    return "\n".join(lines)


def _print_plan_diff(plan: dict[str, Any]) -> None:
    """Print a diff-style view of the apply plan."""
    patch_items = plan.get("patch_items", [])
    print(f"--- expected (run: {plan.get('run_id', '?')})")
    print("+++ host apply")
    for item in patch_items:
        path = item.get("surface_path", "?")
        patch_type = item.get("patch_type", "unknown")
        content = item.get("content", item.get("value", ""))
        print(f"@@ {path} [{patch_type}] @@")
        if content:
            for line in str(content).splitlines():
                print(f"+ {line}")


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
    """Build a RunStore from CLI args (mirrors run.py helper)."""
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


def _get_spec_registry(args: argparse.Namespace) -> Any | None:
    """Load the SpecRegistry from the specs directory in config."""
    config_path = Path(getattr(args, "config", ".clawwrap/config.yaml"))
    specs_dir: Path | None = None

    if config_path.exists():
        try:
            import yaml

            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            specs_dir = Path(cfg.get("specs_dir", "specs"))
        except Exception:
            pass

    if specs_dir is None:
        specs_dir = Path("specs")

    if not specs_dir.is_dir():
        return None

    from clawwrap.engine.loader import load_specs

    return load_specs(specs_dir)
