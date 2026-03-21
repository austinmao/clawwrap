"""OpenClaw handler binding: audit.log_resolution_path.

Appends a structured audit entry recording how an outbound target was resolved.
Writes to ``memory/logs/sends/YYYY-MM-DD.md`` under the workspace root.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawwrap.handlers.registry import handler

# Directory under workspace root where send logs are written.
_AUDIT_LOG_DIR: str = "memory/logs/sends"

# ISO-8601 timestamp format for log entries.
_TIMESTAMP_FORMAT: str = "%Y-%m-%dT%H:%M:%SZ"


def _audit_log_path(workspace_root: Path, now: datetime) -> Path:
    """Compute the daily audit log path for the given datetime.

    Args:
        workspace_root: Workspace root directory.
        now: Current UTC datetime.

    Returns:
        Path to the daily Markdown log file.
    """
    date_str = now.strftime("%Y-%m-%d")
    return workspace_root / _AUDIT_LOG_DIR / f"{date_str}.md"


def _format_entry(entry: dict[str, Any]) -> str:
    """Format a single audit entry as a Markdown fenced JSON block.

    Args:
        entry: Dict of audit fields.

    Returns:
        Markdown string ready to append to the log file.
    """
    body = json.dumps(entry, indent=2, sort_keys=True)
    return f"\n```json\n{body}\n```\n"


@handler("audit.log_resolution_path", adapter_name="openclaw")
def log_resolution_path(inputs: dict[str, Any]) -> dict[str, Any]:
    """Append a structured audit record of an outbound target resolution.

    Contract inputs:
        run_id (str): Run identifier.
        wrapper_name (str): Name of the wrapper being executed.
        group_name (str): Canonical group name used as the lookup key.
        resolved_jid (str | None): JID that was resolved (may be null on failure).
        resolution_source (str): How the target was resolved.
        workspace_root (str, optional): Override workspace root directory.
            Defaults to the current working directory.

    Contract outputs:
        logged (bool): True when the entry was written successfully.
        log_path (str): Path to the log file that was written.
        detail (str): Human-readable result.

    Args:
        inputs: Handler input dict conforming to the audit.log_resolution_path contract.

    Returns:
        Dict with ``logged`` (bool), ``log_path`` (str), and ``detail`` (str).
    """
    run_id: str = str(inputs.get("run_id", ""))
    wrapper_name: str = str(inputs.get("wrapper_name", ""))
    group_name: str = str(inputs.get("group_name", ""))
    resolved_jid: str | None = inputs.get("resolved_jid")
    resolution_source: str = str(inputs.get("resolution_source", "unknown"))
    workspace_root_str: str = str(inputs.get("workspace_root", "."))

    workspace_root = Path(workspace_root_str)
    now = datetime.now(tz=timezone.utc)
    log_path = _audit_log_path(workspace_root, now)

    entry: dict[str, Any] = {
        "timestamp": now.strftime(_TIMESTAMP_FORMAT),
        "run_id": run_id,
        "wrapper_name": wrapper_name,
        "group_name": group_name,
        "resolved_jid": resolved_jid,
        "resolution_source": resolution_source,
    }

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(_format_entry(entry))
    except OSError as exc:
        return {
            "logged": False,
            "log_path": str(log_path),
            "detail": f"Failed to write audit log: {exc}",
        }

    return {
        "logged": True,
        "log_path": str(log_path),
        "detail": f"Audit entry written to {log_path}",
    }
