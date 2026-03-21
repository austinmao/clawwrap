"""OpenClaw patch generator — ownership-aware patches for config and file surfaces.

Generates patches for:
- Mapping entries in openclaw.json (e.g. tools.mappings.whatsapp.groups.*)
- Generated file artifacts (e.g. agents/*/generated/*.yaml)
- Runtime prompt/config fragments (e.g. agents/*/SOUL.md#clawwrap-managed-*)

Key-level ownership is enforced: any patch targeting a surface path not covered
by the adapter's owned_surfaces patterns is refused with a CollisionError.

Governance files (SOUL.md base content, AGENTS.md, USER.md) are never targeted.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any

# Surface types used in patch dicts.
_PT_MAPPING: str = "mapping_entry"
_PT_FILE: str = "file"
_PT_FRAGMENT: str = "prompt_fragment"

# Governance files that must never be patched.
_GOVERNANCE_SUFFIXES: tuple[str, ...] = (
    "AGENTS.md",
    "USER.md",
    "MEMORY.md",
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
)

# SOUL.md is protected except for clawwrap-managed fragment sections.
_SOUL_BASE_PATTERN: str = "*/SOUL.md"
_SOUL_MANAGED_PREFIX: str = "#clawwrap-managed-"


@dataclass
class CollisionError(Exception):
    """Raised when a patch targets a surface not owned by this adapter.

    Attributes:
        surface: The surface path or key that caused the collision.
        reason: Human-readable explanation.
    """

    surface: str
    reason: str

    def __str__(self) -> str:
        """Return a human-readable error message."""
        return f"Ownership collision on '{self.surface}': {self.reason}"


def _matches_any(pattern_list: list[str], surface: str) -> bool:
    """Return True when ``surface`` matches at least one fnmatch pattern.

    Args:
        pattern_list: List of fnmatch-compatible glob patterns.
        surface: Surface path or key to test.

    Returns:
        True if any pattern matches.
    """
    return any(fnmatch.fnmatch(surface, p) for p in pattern_list)


def _assert_owned(surface: str, owned_patterns: list[str]) -> None:
    """Raise CollisionError when ``surface`` is not covered by an owned pattern.

    Args:
        surface: Surface path or key.
        owned_patterns: Patterns declared in the adapter's owned_surfaces.

    Raises:
        CollisionError: If the surface is not owned.
    """
    if not _matches_any(owned_patterns, surface):
        raise CollisionError(
            surface=surface,
            reason=(
                f"Surface '{surface}' is not covered by any owned_surfaces pattern. "
                "Only adapter-owned surfaces may be patched."
            ),
        )


def _assert_not_governance(surface: str) -> None:
    """Raise CollisionError when ``surface`` targets a governance file.

    Args:
        surface: Surface path or key.

    Raises:
        CollisionError: If the surface is a protected governance file.
    """
    # Block pure SOUL.md patches (non-fragment sections).
    if fnmatch.fnmatch(surface, _SOUL_BASE_PATTERN):
        if _SOUL_MANAGED_PREFIX not in surface:
            raise CollisionError(
                surface=surface,
                reason=(
                    "SOUL.md may not be patched directly. "
                    "Use a clawwrap-managed fragment selector "
                    f"(e.g. path{_SOUL_MANAGED_PREFIX}section-name)."
                ),
            )

    for suffix in _GOVERNANCE_SUFFIXES:
        if surface.endswith(suffix):
            raise CollisionError(
                surface=surface,
                reason=f"Governance file '{suffix}' must not be targeted by automated patches.",
            )


def _build_mapping_patch(dotted_key: str, value: str) -> dict[str, Any]:
    """Build a config mapping patch dict.

    Args:
        dotted_key: Fully qualified dotted config key.
        value: String value to set at this key.

    Returns:
        Patch dict describing the mapping entry change.
    """
    return {
        "type": _PT_MAPPING,
        "key": dotted_key,
        "value": value,
        "action": "set",
    }


def _build_file_patch(path: str, content: str) -> dict[str, Any]:
    """Build a file write patch dict.

    Args:
        path: Relative path to the file to write.
        content: File content.

    Returns:
        Patch dict describing the file write.
    """
    return {
        "type": _PT_FILE,
        "path": path,
        "content": content,
        "action": "write",
    }


def _build_fragment_patch(selector: str, content: str) -> dict[str, Any]:
    """Build a prompt/config fragment injection patch dict.

    Args:
        selector: Fragment selector string (e.g. ``agents/*/SOUL.md#clawwrap-managed-foo``).
        content: Fragment content to inject.

    Returns:
        Patch dict describing the fragment injection.
    """
    return {
        "type": _PT_FRAGMENT,
        "selector": selector,
        "content": content,
        "action": "inject",
    }


def generate_patches(
    mapping_entries: dict[str, str],
    file_artifacts: list[dict[str, Any]],
    prompt_fragments: dict[str, str],
    owned_patterns: list[str],
) -> list[dict[str, Any]]:
    """Generate all ownership-validated patches for this OpenClaw adapter run.

    Validates every patch target against ``owned_patterns`` before adding it
    to the output list.  Raises ``CollisionError`` on the first violation
    rather than producing a partial patch set.

    Args:
        mapping_entries: Dict mapping dotted config keys to their new values.
            E.g. ``{"tools.mappings.whatsapp.groups.my-group": "123@g.us"}``.
        file_artifacts: List of dicts with ``path`` (str) and ``content`` (str)
            keys describing files to write.
        prompt_fragments: Dict mapping fragment selectors to content strings.
        owned_patterns: Fnmatch patterns from the adapter's owned_surfaces.

    Returns:
        Ordered list of patch dicts ready for the apply engine.

    Raises:
        CollisionError: If any target surface is not owned or is a governance file.
    """
    patches: list[dict[str, Any]] = []

    for key, value in mapping_entries.items():
        _assert_not_governance(key)
        _assert_owned(key, owned_patterns)
        patches.append(_build_mapping_patch(key, value))

    for artifact in file_artifacts:
        path: str = str(artifact.get("path", ""))
        content: str = str(artifact.get("content", ""))
        _assert_not_governance(path)
        _assert_owned(path, owned_patterns)
        patches.append(_build_file_patch(path, content))

    for selector, fragment_content in prompt_fragments.items():
        _assert_not_governance(selector)
        _assert_owned(selector, owned_patterns)
        patches.append(_build_fragment_patch(selector, fragment_content))

    return patches
