"""Outbound gate — structured audit logging.

Appends structured YAML entries to daily audit log files.
Best-effort — write failures do not block sends.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_LOG_DIR: Path = Path("memory") / "logs" / "outbound"


def log_verdict(
    verdict_dict: dict[str, Any],
    log_dir: Path | None = None,
) -> dict[str, str | bool]:
    """Append a structured verdict entry to the daily audit log.

    Args:
        verdict_dict: Serialized GateVerdict (from verdict.to_dict()).
        log_dir: Directory for audit log files. Defaults to memory/logs/outbound/.

    Returns:
        Dict with request_id and logged status.
    """
    log_dir = log_dir or _DEFAULT_LOG_DIR
    request_id = str(verdict_dict.get("request_id", "unknown"))
    today = date.today().isoformat()
    log_path = log_dir / f"{today}.yaml"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)

        # Load existing entries or start fresh
        entries: list[dict[str, Any]] = []
        if log_path.exists():
            raw = log_path.read_text(encoding="utf-8")
            parsed = yaml.safe_load(raw)
            if isinstance(parsed, list):
                entries = parsed

        entries.append(verdict_dict)

        # Atomic write
        tmp_path = str(log_path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(entries, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, str(log_path))

        return {"request_id": request_id, "logged": True}

    except Exception as exc:
        # Best-effort — log to stderr, don't raise
        print(f"[outbound-gate] audit log write failed: {exc}", file=sys.stderr)
        return {"request_id": request_id, "logged": False}
