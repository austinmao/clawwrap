"""clawwrap init — Project initialization."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "adapter": "local-cli",
    "db_url": "postgresql://localhost/openclaw",
    "specs_dir": "specs",
}


def add_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    init_parser = subparsers.add_parser("init", help="Initialize clawwrap in a project")
    init_parser.add_argument("--adapter", default="local-cli", help="Default host adapter (default: local-cli)")
    init_parser.add_argument("--db-url", default=None, help="Postgres connection string")


def handle(args: argparse.Namespace) -> int:
    config_dir = Path(".clawwrap")
    config_file = config_dir / "config.yaml"

    if config_file.exists():
        print(f"Config already exists at {config_file}")
        return 0

    config_dir.mkdir(parents=True, exist_ok=True)

    config = dict(DEFAULT_CONFIG)
    if args.adapter:
        config["adapter"] = args.adapter
    if args.db_url:
        config["db_url"] = args.db_url

    with open(config_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"Initialized clawwrap config at {config_file}")
    print(f"  adapter: {config['adapter']}")
    print(f"  db_url:  {config['db_url']}")
    print(f"  specs:   {config['specs_dir']}/")
    return 0
