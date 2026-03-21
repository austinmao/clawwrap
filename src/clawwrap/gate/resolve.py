"""Outbound gate — target resolution.

Resolves shared destinations from config/targets.yaml and direct
destinations from adapter-bound recipient_ref resolvers.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol

import yaml

from clawwrap.engine.gate import ResolvedContext

# Repo root: resolve.py → gate/ → clawwrap pkg/ → src/ → clawwrap dir/ → repo root (5 levels up).
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent.parent

# Legacy default config directory (used when COMPOSIO_USER_ID is not set).
_DEFAULT_CONFIG_DIR: Path = _REPO_ROOT / "clawwrap" / "config"


def _resolve_config_dir(repo_root: Path | None = None) -> Path:
    """Return the config directory for the active tenant.

    Priority:
      1. tenants/{COMPOSIO_USER_ID}/config/  — if COMPOSIO_USER_ID is set
      2. clawwrap/config/                    — legacy fallback (no COMPOSIO_USER_ID)
    """
    root = repo_root or _REPO_ROOT
    user_id = os.environ.get("COMPOSIO_USER_ID")
    if user_id:
        # Sanitize to prevent path traversal
        if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
            raise ValueError(
                f"Invalid COMPOSIO_USER_ID: {user_id!r} — must be alphanumeric, hyphens, underscores only"
            )
        return root / "tenants" / user_id / "config"
    return root / "clawwrap" / "config"


class RecipientResolver(Protocol):
    """Protocol for adapter-bound recipient_ref resolvers."""

    def resolve(self, recipient_ref: str, channel: str) -> tuple[str, str, str]:
        """Resolve a recipient_ref to (target, label, provider_id).

        Args:
            recipient_ref: Canonical reference (e.g. "airtable:contacts/rec123").
            channel: Target channel for address selection.

        Returns:
            Tuple of (target_address, human_label, provider_id).

        Raises:
            ValueError: If the ref cannot be resolved.
        """
        ...


def load_targets(config_dir: Path | None = None, repo_root: Path | None = None) -> dict[str, Any]:
    """Load and parse config/targets.yaml.

    Args:
        config_dir: Directory containing targets.yaml. If provided, used directly.
            If None, resolved via _resolve_config_dir() which honours COMPOSIO_USER_ID.
        repo_root: Override the repo root used by _resolve_config_dir(). Useful in tests.

    Returns:
        Parsed targets dict with 'targets' and 'audience_labels' keys.

    Raises:
        FileNotFoundError: If targets.yaml does not exist.
        yaml.YAMLError: If the file contains invalid YAML.
        ValueError: If the parsed content is not a dict.
    """
    if config_dir is None:
        config_dir = _resolve_config_dir(repo_root)
    targets_path = config_dir / "targets.yaml"

    if not targets_path.exists():
        raise FileNotFoundError(f"targets.yaml not found at {targets_path}")

    raw = targets_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise ValueError(f"targets.yaml must be a YAML mapping, got {type(data).__name__}")

    return data


def resolve_shared(
    context_key: str,
    audience: str,
    channel: str,
    targets_data: dict[str, Any],
) -> ResolvedContext:
    """Resolve a shared destination from targets data.

    Args:
        context_key: Lookup key (e.g. "awaken-apr-2026").
        audience: Intended audience (e.g. "staff").
        channel: Target channel (e.g. "whatsapp").
        targets_data: Parsed targets.yaml content.

    Returns:
        ResolvedContext with target, audience_label, expected_identity, and allowlist_key.
    """
    targets = targets_data.get("targets", {})
    labels = targets_data.get("audience_labels", {})

    # Navigate targets[context_key][audience][channel]
    context_entry = targets.get(context_key, {})
    if not isinstance(context_entry, dict):
        return _empty_resolved(context_key, audience)

    audience_entry = context_entry.get(audience, {})
    if not isinstance(audience_entry, dict):
        return _empty_resolved(context_key, audience)

    channel_entry = audience_entry.get(channel)

    # channel_entry can be: None, a dict with {target, verify}, or null.
    # target may be a single string or a list of strings (email fan-out).
    target: str | list[str] | None = None
    expected_identity: dict[str, Any] | None = None
    verification_supported = False

    if isinstance(channel_entry, dict):
        raw_target = channel_entry.get("target")
        if isinstance(raw_target, list):
            target = raw_target
        elif raw_target is not None:
            target = str(raw_target)
        else:
            target = None
        verify_meta = channel_entry.get("verify")
        if isinstance(verify_meta, dict) and target:
            expected_identity = verify_meta
            # verification_supported is set to False here — it will be
            # upgraded to True by the submit handler only when a live
            # identity checker is actually available for the channel.
            # This prevents false denials when verify metadata exists
            # but the live check backend is not callable.
    # If channel_entry is None or a scalar, target stays None

    # Read audience label
    audience_label = ""
    context_labels = labels.get(context_key, {})
    if isinstance(context_labels, dict):
        audience_label = str(context_labels.get(audience, ""))

    allowlist_key = f"{context_key}.{audience}"

    return ResolvedContext(
        target=target,
        audience_label=audience_label,
        expected_identity=expected_identity,
        allowlist_key=allowlist_key,
        verification_supported=verification_supported,
    )


def resolve_direct(
    recipient_ref: str,
    channel: str,
    resolver_registry: dict[str, RecipientResolver],
) -> ResolvedContext:
    """Resolve a direct recipient via adapter-bound resolver.

    Args:
        recipient_ref: Canonical reference (e.g. "airtable:contacts/rec123").
        channel: Target channel.
        resolver_registry: Map of prefix → resolver implementation.

    Returns:
        ResolvedContext with resolved target and metadata.

    Raises:
        ValueError: If the prefix is unknown or resolution fails.
    """
    if ":" not in recipient_ref:
        raise ValueError(f"recipient_ref must contain a ':' prefix separator: {recipient_ref!r}")

    prefix = recipient_ref.split(":")[0]
    resolver = resolver_registry.get(prefix)
    if resolver is None:
        raise ValueError(f"no resolver registered for prefix {prefix!r}")

    target, label, _provider_id = resolver.resolve(recipient_ref, channel)

    return ResolvedContext(
        target=target,
        audience_label=label,
        expected_identity=None,
        allowlist_key=recipient_ref,
        verification_supported=False,
    )


def fill_empty_target(
    context_key: str,
    audience: str,
    channel: str,
    target: str,
    verify_metadata: dict[str, Any] | None,
    config_dir: Path | None = None,
) -> bool:
    """Write-back a target to targets.yaml if the slot is currently empty.

    Uses atomic file replacement (write to temp, rename) for safety.
    Returns True if the target was written, False if the slot was already filled.

    Raises:
        ValueError: If the slot already has a value (overwrite not allowed).
    """
    config_dir = config_dir or _resolve_config_dir()
    targets_path = config_dir / "targets.yaml"
    data = load_targets(config_dir)

    targets = data.setdefault("targets", {})
    context = targets.setdefault(context_key, {})
    aud = context.setdefault(audience, {})

    existing = aud.get(channel)
    if isinstance(existing, dict) and existing.get("target"):
        raise ValueError(
            f"target already configured for {context_key}.{audience}.{channel}: "
            f"{existing['target']}. Overwrite requires operator review."
        )

    entry: dict[str, Any] = {"target": target}
    if verify_metadata:
        entry["verify"] = verify_metadata
    aud[channel] = entry

    # Atomic write: temp file in same directory, then rename
    fd, tmp_path = tempfile.mkstemp(dir=str(config_dir), suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, str(targets_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return True


def _empty_resolved(context_key: str, audience: str) -> ResolvedContext:
    """Return a ResolvedContext with null target for missing entries."""
    return ResolvedContext(
        target=None,
        audience_label="",
        expected_identity=None,
        allowlist_key=f"{context_key}.{audience}",
        verification_supported=False,
    )
