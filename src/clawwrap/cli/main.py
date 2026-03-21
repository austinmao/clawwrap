"""clawwrap CLI entry point."""

from __future__ import annotations

import argparse
import sys

from clawwrap.cli import apply as apply_cmd
from clawwrap.cli import conformance as conformance_cmd
from clawwrap.cli import handler as handler_cmd
from clawwrap.cli import init as init_cmd
from clawwrap.cli import legacy as legacy_cmd
from clawwrap.cli import migrate as migrate_cmd
from clawwrap.cli import run as run_cmd
from clawwrap.cli import validate as validate_cmd


def build_parser() -> argparse.ArgumentParser:
    """Build the root argument parser with all subcommands registered."""
    parser = argparse.ArgumentParser(
        prog="clawwrap",
        description="Spec-first control plane for typed, policy-enforced wrapper contracts",
    )
    parser.add_argument("--config", default=".clawwrap/config.yaml", help="Config file path")
    parser.add_argument("--db-url", default=None, help="Override database URL")
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase output verbosity")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error output")

    subparsers = parser.add_subparsers(dest="command")

    # version
    subparsers.add_parser("version", help="Show version")

    # Phase 1: init and migrate
    init_cmd.add_subcommands(subparsers)
    migrate_cmd.add_subcommands(subparsers)

    # Phase 3 (US1): validate and graph
    validate_cmd.add_subcommands(subparsers)

    # Phase 4 (US2): run subcommand group
    run_cmd.add_subcommands(subparsers)

    # Phase 5 (US3): apply and conformance subcommand groups
    apply_cmd.add_subcommands(subparsers)
    conformance_cmd.add_subcommands(subparsers)

    # Phase 6 (US4): handler subcommand group
    handler_cmd.add_subcommands(subparsers)

    # Phase 7 (US5): legacy authority
    legacy_cmd.add_subcommands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the clawwrap CLI.

    Args:
        argv: Argument list (defaults to sys.argv when None).

    Returns:
        Exit code (0 = success, non-zero = error per CLI contract).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "version":
        print("clawwrap 0.1.0")
        return 0

    if args.command == "init":
        return init_cmd.handle(args)

    if args.command == "migrate":
        return migrate_cmd.handle(args)

    if args.command == "validate":
        return validate_cmd.handle_validate(args)

    if args.command == "graph":
        return validate_cmd.handle_graph(args)

    if args.command == "run":
        return run_cmd.handle(args)

    if args.command == "apply":
        return apply_cmd.handle(args)

    if args.command == "conformance":
        return conformance_cmd.handle(args)

    if args.command == "handler":
        return handler_cmd.handle(args)

    if args.command == "legacy":
        return legacy_cmd.handle(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
