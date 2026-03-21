"""OpenClaw handler binding: group.identity_matches.

Uses wacli to verify that a WhatsApp group's actual identity matches the
canonical record stored in the wrapper's resolved inputs.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from clawwrap.handlers.registry import handler

# Exit-code returned by wacli when the group is found and identity matches.
_WACLI_SUCCESS: int = 0

# Maximum bytes read from wacli stdout to avoid unbounded buffering.
_MAX_OUTPUT_BYTES: int = 4096


def _run_wacli(group_jid: str, expected_name: str) -> tuple[bool, str]:
    """Invoke wacli to verify group identity.

    Returns a (matched, detail) pair.  On subprocess failure the function
    returns (False, error_description) rather than propagating an exception,
    so the caller can decide the fail_action.

    Args:
        group_jid: WhatsApp group JID to look up (e.g. ``12345678@g.us``).
        expected_name: Display name expected to match the group record.

    Returns:
        Tuple of (matched: bool, detail: str).
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["wacli", "groups", "info", "--jid", group_jid, "--json"],
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False, "wacli binary not found"
    except subprocess.TimeoutExpired:
        return False, "wacli timed out"
    except OSError as exc:
        return False, f"wacli OS error: {exc}"

    stdout = result.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
    if result.returncode != _WACLI_SUCCESS:
        return False, stdout or f"wacli exit {result.returncode}"

    actual_name = _extract_group_name(stdout)
    if not actual_name:
        return False, "wacli response did not contain a group name"
    if actual_name != expected_name:
        return False, f"expected {expected_name!r}, got {actual_name!r}"
    return True, f"matched group title {actual_name!r}"


def _extract_group_name(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    name = data.get("Name")
    if name is None:
        return None
    text = str(name).strip()
    return text or None


@handler("group.identity_matches", adapter_name="openclaw")
def group_identity_matches(inputs: dict[str, Any]) -> dict[str, Any]:
    """Verify that a WhatsApp group's live identity matches the canonical record.

    Contract inputs:
        group_jid (str): WhatsApp group JID.
        expected_name (str): Expected group display name.

    Contract outputs:
        matched (bool): True when identity confirmed.
        detail (str): Human-readable result or error description.

    Args:
        inputs: Handler input dict conforming to the group.identity_matches contract.

    Returns:
        Dict with ``matched`` (bool) and ``detail`` (str).
    """
    group_jid: str = str(inputs.get("group_jid", ""))
    expected_name: str = str(inputs.get("expected_name", ""))

    if not group_jid:
        return {"matched": False, "detail": "group_jid is required"}
    if not expected_name:
        return {"matched": False, "detail": "expected_name is required"}

    matched, detail = _run_wacli(group_jid, expected_name)
    return {"matched": matched, "detail": detail}
