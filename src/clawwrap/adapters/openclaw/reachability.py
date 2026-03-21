"""OpenClaw reachability rules for legacy authority verification.

Provides selector rules, precedence rules, and reachability tests
for OpenClaw prompt/config surfaces. Required by FR-021 before
shadowed_unreachable status can be claimed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# OpenClaw prompt/config surface selectors
SELECTOR_RULES = {
    "prompt": {
        "pattern": "agents/*/SOUL.md",
        "match_type": "glob",
        "description": "Agent SOUL.md files containing prompt routing instructions",
    },
    "config": {
        "pattern": "tools.mappings.whatsapp.*",
        "match_type": "json_path",
        "description": "WhatsApp mapping entries in openclaw.json",
    },
}

# Precedence: when multiple candidate surfaces exist for the same flow
PRECEDENCE_RULES = [
    {
        "rule": "config_over_prompt",
        "description": "Config mappings take precedence over prompt-embedded routing",
        "order": ["config", "prompt"],
    },
    {
        "rule": "specific_over_wildcard",
        "description": "Specific flow mappings take precedence over wildcard patterns",
        "order": ["exact_match", "prefix_match", "wildcard"],
    },
]


def get_selector_rules() -> dict[str, Any]:
    """Return the selector rules for OpenClaw surfaces."""
    return dict(SELECTOR_RULES)


def get_precedence_rules() -> list[dict[str, Any]]:
    """Return the precedence rules for OpenClaw surfaces."""
    return list(PRECEDENCE_RULES)


def test_reachability(source_path: str, config_key: str | None = None) -> bool:
    """Test whether a legacy source can still influence live flow selection.

    For prompt sources: checks if the file exists and contains routing instructions.
    For config sources: checks if the config key exists and is not shadowed by
    a clawwrap-managed entry.
    """
    source_file = Path(source_path).expanduser()

    if config_key:
        return _test_config_reachability(config_key)

    return _test_prompt_reachability(source_file)


def _test_prompt_reachability(source_file: Path) -> bool:
    """Test if a prompt source file still contains reachable routing."""
    if not source_file.exists():
        return False

    content = source_file.read_text()

    # Check for clawwrap-managed markers that indicate the section is shadowed
    if "# clawwrap-managed" in content:
        return False

    # Check for common routing indicators
    routing_indicators = [
        "WhatsApp group",
        "group JID",
        "wacli",
        "send to group",
        "group routing",
    ]
    return any(indicator.lower() in content.lower() for indicator in routing_indicators)


def _test_config_reachability(config_key: str) -> bool:
    """Test if a config key is still reachable in openclaw.json."""
    config_path = Path("~/.openclaw/openclaw.json").expanduser()
    if not config_path.exists():
        return False

    with open(config_path) as f:
        config = json.load(f)

    # Navigate the dotted path
    parts = config_key.split(".")
    current: Any = config
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]

    # Key exists — check if it's been marked as clawwrap-managed
    if isinstance(current, dict) and current.get("__managed_by") == "clawwrap":
        return False

    return True
