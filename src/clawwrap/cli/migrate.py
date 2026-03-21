"""clawwrap migrate — Alembic migration management."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def add_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    migrate_parser = subparsers.add_parser("migrate", help="Manage database migrations")
    migrate_sub = migrate_parser.add_subparsers(dest="migrate_action")

    migrate_sub.add_parser("up", help="Apply all pending migrations")

    down_parser = migrate_sub.add_parser("down", help="Rollback N migrations")
    down_parser.add_argument("count", type=int, nargs="?", default=1, help="Number of migrations to rollback")

    migrate_sub.add_parser("status", help="Show current migration status")


def handle(args: argparse.Namespace) -> int:
    alembic_ini = Path(__file__).resolve().parents[3] / "alembic.ini"
    if not alembic_ini.exists():
        print(f"Error: alembic.ini not found at {alembic_ini}", file=sys.stderr)
        return 1

    base_cmd = ["alembic", "-c", str(alembic_ini)]

    if args.migrate_action == "up":
        cmd = [*base_cmd, "upgrade", "head"]
    elif args.migrate_action == "down":
        count = getattr(args, "count", 1)
        cmd = [*base_cmd, "downgrade", f"-{count}"]
    elif args.migrate_action == "status":
        cmd = [*base_cmd, "current"]
    else:
        print("Usage: clawwrap migrate {up|down|status}", file=sys.stderr)
        return 1

    result = subprocess.run(cmd, capture_output=False)
    return result.returncode
