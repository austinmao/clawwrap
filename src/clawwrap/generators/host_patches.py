"""Host-native patch renderer (T043).

Converts semantic plan items (from an ``ApplyPlan``) into host-native
``HostPatch`` descriptors.  Each patch type maps to a specific host operation:
- ``file_write`` — write a file to a specific path.
- ``config_set`` — set a configuration key to a value.
- ``mapping_entry`` — add or update a mapping entry (e.g. OpenClaw route table).
- ``prompt_fragment`` — write a prompt fragment to a managed location.

The renderer delegates format-specific details to the adapter via
``get_approval_identity_config`` (for adapter identification) or via
any ``render_patch`` method the adapter may expose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clawwrap.adapters.base import AdapterProtocol
from clawwrap.engine.planner import ApplyPlan
from clawwrap.model.types import SurfaceType


@dataclass
class HostPatch:
    """Host-native patch descriptor.

    Attributes:
        surface_path: Target surface selector (file path, config key, etc.).
        surface_type: Inferred or declared surface type.
        patch_type: Operation to perform (file_write, config_set, etc.).
        content: New value or content to write.
        adapter_name: Which adapter owns and must apply this patch.
        metadata: Optional adapter-specific metadata.
    """

    surface_path: str
    surface_type: SurfaceType
    patch_type: str
    content: Any
    adapter_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "surface_path": self.surface_path,
            "surface_type": self.surface_type.value,
            "patch_type": self.patch_type,
            "content": self.content,
            "adapter_name": self.adapter_name,
            "metadata": self.metadata,
        }


def render_patches(apply_plan: ApplyPlan, adapter: AdapterProtocol) -> list[HostPatch]:
    """Convert semantic plan items into host-native HostPatch descriptors.

    Each patch item in the plan is inspected for ``surface_path``,
    ``patch_type``, and ``content``.  The adapter name is read from
    the adapter's identity config.

    Args:
        apply_plan: The ApplyPlan produced by the planner.
        adapter: Host adapter providing identity and optional custom rendering.

    Returns:
        List of HostPatch instances, one per valid patch item.
    """
    config = adapter.get_approval_identity_config()
    adapter_name = config.source_type
    patches: list[HostPatch] = []

    for item in apply_plan.patch_items:
        patch = _render_single_patch(item, adapter_name, adapter)
        if patch is not None:
            patches.append(patch)

    return patches


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_single_patch(
    item: dict[str, Any],
    adapter_name: str,
    adapter: AdapterProtocol,
) -> HostPatch | None:
    """Render a single patch item dict into a HostPatch.

    If the adapter exposes a ``render_patch`` method (adapter-specific
    override), it is called first and its result is used if non-None.

    Args:
        item: Patch item dict from the apply plan.
        adapter_name: Name of the owning adapter.
        adapter: Host adapter instance.

    Returns:
        HostPatch, or None if the item should be skipped.
    """
    if hasattr(adapter, "render_patch"):
        custom: HostPatch | None = getattr(adapter, "render_patch")(item)
        if custom is not None:
            return custom

    surface_path = str(item.get("surface_path", "")).strip()
    if not surface_path:
        return None

    patch_type = str(item.get("patch_type", _infer_patch_type(item)))
    content = _extract_content(item, patch_type)
    surface_type = _infer_surface_type(surface_path, patch_type)
    metadata = {k: v for k, v in item.items() if k not in _RESERVED_KEYS}

    return HostPatch(
        surface_path=surface_path,
        surface_type=surface_type,
        patch_type=patch_type,
        content=content,
        adapter_name=adapter_name,
        metadata=metadata,
    )


def _infer_patch_type(item: dict[str, Any]) -> str:
    """Infer patch type from item keys if not explicitly declared.

    Args:
        item: Patch item dict.

    Returns:
        Inferred patch type string.
    """
    if "content" in item:
        return "file_write"
    if "key" in item and "value" in item:
        return "config_set"
    if "entry_key" in item:
        return "mapping_entry"
    if "fragment" in item:
        return "prompt_fragment"
    return "unknown"


def _extract_content(item: dict[str, Any], patch_type: str) -> Any:
    """Extract the patch content/value based on patch_type.

    Args:
        item: Patch item dict.
        patch_type: Resolved patch type string.

    Returns:
        Content value appropriate for the patch type.
    """
    if patch_type == "file_write":
        return item.get("content", item.get("value", ""))
    if patch_type == "config_set":
        return item.get("value", item.get("content"))
    if patch_type == "mapping_entry":
        return {"key": item.get("entry_key", ""), "value": item.get("entry_value", "")}
    if patch_type == "prompt_fragment":
        return item.get("fragment", item.get("content", ""))
    return item.get("content", item.get("value"))


def _infer_surface_type(surface_path: str, patch_type: str) -> SurfaceType:
    """Infer the SurfaceType from path and patch_type.

    Args:
        surface_path: Surface selector string.
        patch_type: Patch operation type.

    Returns:
        Inferred SurfaceType.
    """
    if patch_type == "prompt_fragment":
        return SurfaceType.prompt_fragment
    if patch_type == "mapping_entry":
        return SurfaceType.mapping_entry
    if patch_type == "config_set":
        return SurfaceType.config_key
    if "/" in surface_path or surface_path.startswith("."):
        return SurfaceType.file
    return SurfaceType.config_key


# Keys that are structural to the patch item and not metadata.
_RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "surface_path",
        "patch_type",
        "content",
        "value",
        "key",
        "entry_key",
        "entry_value",
        "fragment",
    }
)
