"""clawwrap legacy — Legacy authority inventory and cutover verification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from clawwrap.engine.legacy import build_inventory, verify_cutover
from clawwrap.model.types import ConformanceStatus


def add_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register legacy subcommands."""
    legacy_parser = subparsers.add_parser("legacy", help="Legacy authority management")
    legacy_sub = legacy_parser.add_subparsers(dest="legacy_action")

    inv_parser = legacy_sub.add_parser("inventory", help="Show legacy authority inventory for a flow")
    inv_parser.add_argument("flow_name", help="Migrated flow name")
    inv_parser.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    inv_parser.add_argument("--legacy-dir", default=None, help="Legacy specs directory")

    ver_parser = legacy_sub.add_parser("verify", help="Verify cutover for a migrated flow")
    ver_parser.add_argument("flow_name", help="Migrated flow name")
    ver_parser.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    ver_parser.add_argument("--legacy-dir", default=None, help="Legacy specs directory")


def handle(args: argparse.Namespace) -> int:
    """Handle legacy subcommands."""
    if args.legacy_action == "inventory":
        return _handle_inventory(args)
    if args.legacy_action == "verify":
        return _handle_verify(args)
    print("Usage: clawwrap legacy {inventory|verify} <flow-name>", file=sys.stderr)
    return 1


def _handle_inventory(args: argparse.Namespace) -> int:
    legacy_dir = Path(args.legacy_dir) if args.legacy_dir else None
    try:
        inventory = build_inventory(args.flow_name, legacy_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        data = {
            "flow_name": inventory.flow_name,
            "description": inventory.description,
            "sources": [
                {
                    "source_type": s.source_type,
                    "source_path": s.source_path,
                    "expected_status": s.expected_status,
                    "section": s.section,
                    "config_key": s.config_key,
                }
                for s in inventory.sources
            ],
        }
        print(json.dumps(data, indent=2))
    else:
        print(f"Legacy Authority Inventory: {inventory.flow_name}")
        print(f"  {inventory.description}")
        print()
        for i, src in enumerate(inventory.sources, 1):
            print(f"  [{i}] {src.source_type}: {src.source_path}")
            if src.section:
                print(f"      section: {src.section}")
            if src.config_key:
                print(f"      config_key: {src.config_key}")
            print(f"      expected: {src.expected_status}")

    return 0


def _handle_verify(args: argparse.Namespace) -> int:
    legacy_dir = Path(args.legacy_dir) if args.legacy_dir else None

    # For now, use a stub adapter for verification
    # In production, this would be resolved from config
    from clawwrap.adapters.local_cli.adapter import LocalCliAdapter
    adapter = LocalCliAdapter()

    try:
        result = verify_cutover(args.flow_name, adapter, legacy_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        data = {
            "flow_name": result.flow_name,
            "status": result.status.value,
            "verifications": [
                {
                    "source_path": v.source.source_path,
                    "expected": v.source.expected_status,
                    "observed": v.observed_status,
                    "matches": v.matches,
                    "detail": v.detail,
                }
                for v in result.verifications
            ],
            "errors": result.errors,
        }
        print(json.dumps(data, indent=2))
    else:
        status_label = "PASS" if result.status == ConformanceStatus.matching else "FAIL"
        print(f"Cutover Verification: {result.flow_name} [{status_label}]")
        print()
        for v in result.verifications:
            icon = "OK" if v.matches else "FAIL"
            print(f"  [{icon}] {v.source.source_path}")
            print(f"        expected: {v.source.expected_status}, observed: {v.observed_status}")
            if not v.matches:
                print(f"        {v.detail}")

    return 7 if result.status == ConformanceStatus.drifted else 0
