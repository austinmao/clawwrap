"""OpenClaw handler binding: target.resolve_from_canonical.

Resolves a WhatsApp target JID from the canonical group registry stored in the
OpenClaw config mapping, rather than accepting a hardcoded JID from caller input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clawwrap.handlers.registry import handler

# Default path to openclaw.json relative to repo root.
_DEFAULT_CONFIG_PATH: Path = Path(".openclaw") / "openclaw.json"

# Mapping key path within openclaw.json where group JIDs live.
_GROUPS_MAPPING_KEY: str = "tools.mappings.whatsapp.groups"


def _read_config(config_path: Path) -> dict[str, Any]:
    """Read and parse openclaw.json.

    Args:
        config_path: Path to the openclaw config JSON file.

    Returns:
        Parsed config dict, or empty dict on read/parse failure.
    """
    if not config_path.exists():
        return {}
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _navigate(data: dict[str, Any], dotted_key: str) -> Any:
    """Traverse a nested dict using a dotted key path.

    Args:
        data: Root dict to traverse.
        dotted_key: Dot-separated path (e.g. ``tools.mappings.whatsapp.groups``).

    Returns:
        Value at the path, or None if any segment is missing.
    """
    node: Any = data
    for segment in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(segment)
    return node


@handler("target.resolve_from_canonical", adapter_name="openclaw")
def resolve_from_canonical(inputs: dict[str, Any]) -> dict[str, Any]:
    """Resolve a WhatsApp group JID from the canonical config mapping.

    Contract inputs:
        group_name (str): Canonical group name key to look up.
        config_path (str, optional): Override path to openclaw.json.

    Contract outputs:
        resolved_jid (str | None): JID if found.
        found (bool): True when a JID was resolved.
        detail (str): Human-readable result.

    Args:
        inputs: Handler input dict conforming to the target.resolve_from_canonical contract.

    Returns:
        Dict with ``resolved_jid``, ``found``, and ``detail``.
    """
    group_name: str = str(inputs.get("group_name", ""))
    config_path_override: str = str(inputs.get("config_path", ""))

    if not group_name:
        return {"resolved_jid": None, "found": False, "detail": "group_name is required"}

    config_path = Path(config_path_override) if config_path_override else _DEFAULT_CONFIG_PATH
    config = _read_config(config_path)

    groups_map = _navigate(config, _GROUPS_MAPPING_KEY)
    if not isinstance(groups_map, dict):
        return {
            "resolved_jid": None,
            "found": False,
            "detail": f"groups mapping not found at {_GROUPS_MAPPING_KEY}",
        }

    jid = groups_map.get(group_name)
    if jid is None:
        return {
            "resolved_jid": None,
            "found": False,
            "detail": f"group '{group_name}' not in canonical registry",
        }

    return {"resolved_jid": str(jid), "found": True, "detail": "resolved from canonical registry"}
