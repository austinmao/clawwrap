"""Outbound gate — policy check evaluator.

Evaluates outbound-policy.yaml checks against a ResolvedContext.
Fail-closed: any infrastructure error results in deny.
"""
from __future__ import annotations

import json
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from clawwrap.engine.gate import CheckResult, ResolvedContext
from clawwrap.gate.resolve import _resolve_config_dir

_DEFAULT_CONFIG_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent.parent / "clawwrap" / "config"
_DEFAULT_GATEWAY_PATH: Path = Path.home() / ".openclaw" / "openclaw.json"


def load_policy(config_dir: Path | None = None, repo_root: Path | None = None) -> dict[str, Any]:
    """Load and parse config/outbound-policy.yaml.

    Args:
        config_dir: Directory containing outbound-policy.yaml. If provided, used directly.
            If None, resolved via _resolve_config_dir() which honours COMPOSIO_USER_ID.
        repo_root: Override the repo root used by _resolve_config_dir(). Useful in tests.

    Returns:
        Parsed policy dict.

    Raises:
        FileNotFoundError: If policy file does not exist.
        yaml.YAMLError: If the file contains invalid YAML.
        ValueError: If the parsed content is not a dict.
    """
    if config_dir is None:
        config_dir = _resolve_config_dir(repo_root)
    policy_path = config_dir / "outbound-policy.yaml"

    if not policy_path.exists():
        raise FileNotFoundError(f"outbound-policy.yaml not found at {policy_path}")

    raw = policy_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise ValueError(f"outbound-policy.yaml must be a YAML mapping, got {type(data).__name__}")

    return data


def load_gateway_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load gateway config from ~/.openclaw/openclaw.json.

    Args:
        config_path: Path to openclaw.json.

    Returns:
        Parsed config dict, or empty dict on failure.
    """
    config_path = config_path or _DEFAULT_GATEWAY_PATH

    if not config_path.exists():
        return {}

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_enabled_channels(gateway_config: dict[str, Any]) -> set[str]:
    """Extract the set of enabled channel names from gateway config.

    Args:
        gateway_config: Parsed openclaw.json content.

    Returns:
        Set of channel names where enabled is true (or not explicitly false).
    """
    channels = gateway_config.get("channels", {})
    if not isinstance(channels, dict):
        return set()

    enabled = set()
    for name, cfg in channels.items():
        if isinstance(cfg, dict):
            if cfg.get("enabled", True):
                enabled.add(name)
        else:
            enabled.add(name)  # assume enabled if not a dict
    return enabled


def check_gate_allowlist(
    allowlist_key: str,
    route_mode: str,
    channel: str,
    policy: dict[str, Any],
) -> bool:
    """Check if the allowlist_key is authorized in the gate policy.

    Args:
        allowlist_key: Key to check (e.g. "awaken-apr-2026.staff" or "airtable:contacts/rec123").
        route_mode: "shared" or "direct".
        channel: Channel name.
        policy: Parsed outbound-policy.yaml.

    Returns:
        True if allowed, False if not.
    """
    allowlists = policy.get("allowlists", {})
    mode_list = allowlists.get(route_mode, {})
    channel_patterns = mode_list.get(channel, [])

    if not isinstance(channel_patterns, list):
        return False

    return any(fnmatch(allowlist_key, pattern) for pattern in channel_patterns)


def evaluate_checks(
    resolved: ResolvedContext,
    route_mode: str,
    channel: str,
    policy: dict[str, Any],
    gateway_config: dict[str, Any],
) -> list[CheckResult]:
    """Evaluate all policy checks against the resolved context.

    Args:
        resolved: The resolved context from the resolve stage.
        route_mode: "shared" or "direct".
        channel: Target channel.
        policy: Parsed outbound-policy.yaml.
        gateway_config: Parsed openclaw.json.

    Returns:
        List of CheckResult objects. All must pass for the send to proceed.
    """
    results: list[CheckResult] = []

    # 1. target_exists
    has_target = bool(resolved.target)
    if isinstance(resolved.target, list):
        has_target = len(resolved.target) > 0
    if has_target:
        results.append(CheckResult("target_exists", True, f"target resolved to {resolved.target}"))
    else:
        results.append(CheckResult("target_exists", False, "resolved target is null"))

    # 2. target_in_gate_allowlist
    if has_target:
        allowed = check_gate_allowlist(resolved.allowlist_key, route_mode, channel, policy)
        if allowed:
            results.append(CheckResult(
                "target_in_gate_allowlist", True,
                f"allowlist_key {resolved.allowlist_key!r} authorized for {route_mode}/{channel}"
            ))
        else:
            results.append(CheckResult(
                "target_in_gate_allowlist", False,
                f"allowlist_key {resolved.allowlist_key!r} not in {route_mode}/{channel} allowlist"
            ))
    else:
        results.append(CheckResult("target_in_gate_allowlist", False, "skipped — no target"))

    # 3. audience_matches
    if resolved.audience_label:
        results.append(CheckResult("audience_matches", True, f"audience label: {resolved.audience_label!r}"))
    else:
        results.append(CheckResult("audience_matches", False, "audience label is empty"))

    # 4. live_identity_matches (skip when verification not supported)
    if resolved.verification_supported:
        if resolved.live_identity_match is True:
            results.append(CheckResult(
                "live_identity_matches", True,
                f"live identity verified: {resolved.live_identity}"
            ))
        elif resolved.live_identity_match is False:
            results.append(CheckResult(
                "live_identity_matches", False,
                f"live identity mismatch: {resolved.live_identity}"
            ))
        else:
            # live_identity_match is None — verification was required but not performed
            results.append(CheckResult(
                "live_identity_matches", False,
                "live verification required but result unavailable"
            ))
    else:
        results.append(CheckResult(
            "live_identity_matches", True,
            "live verification not supported for this channel — skipped"
        ))

    # 5. channel_enabled
    enabled = get_enabled_channels(gateway_config)
    if channel in enabled:
        results.append(CheckResult("channel_enabled", True, f"channel {channel!r} is enabled"))
    else:
        results.append(CheckResult("channel_enabled", False, f"channel {channel!r} not enabled in gateway"))

    # 6. target_passes_gateway_constraints
    if has_target:
        if isinstance(resolved.target, list):
            # For list targets, check each address individually.
            all_pass = True
            details: list[str] = []
            for t in resolved.target:
                passes, detail = _check_gateway_constraints(t, channel, gateway_config)
                details.append(detail)
                if not passes:
                    all_pass = False
            combined_detail = "; ".join(details)
            results.append(CheckResult("target_passes_gateway_constraints", all_pass, combined_detail))
        else:
            passes, detail = _check_gateway_constraints(resolved.target, channel, gateway_config)
            results.append(CheckResult("target_passes_gateway_constraints", passes, detail))
    else:
        results.append(CheckResult("target_passes_gateway_constraints", False, "skipped — no target"))

    return results


def _check_gateway_constraints(
    target: str,
    channel: str,
    gateway_config: dict[str, Any],
) -> tuple[bool, str]:
    """Check if target passes channel-level gateway transport constraints.

    For now, this is a basic check that the channel config exists and
    doesn't explicitly block the target. Future: check sendTo allowlists
    if OpenClaw adds them (issues #25039, #30560).

    Returns:
        Tuple of (passes, detail_string).
    """
    channels = gateway_config.get("channels", {})
    channel_cfg = channels.get(channel, {})

    if not isinstance(channel_cfg, dict):
        return True, "no gateway constraints for this channel"

    # Check if channel has a sendTo allowlist (future OpenClaw feature)
    send_to = channel_cfg.get("sendTo")
    if isinstance(send_to, list) and send_to:
        if target in send_to:
            return True, "target in gateway sendTo allowlist"
        return False, f"target {target!r} not in gateway sendTo allowlist"

    return True, "no gateway sendTo constraints configured"
