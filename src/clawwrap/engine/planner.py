"""Semantic apply plan generator.

Produces an ``ApplyPlan`` from a completed run + host adapter.  Each plan item
is validated against the adapter's ownership manifest before being accepted.
Patches targeting non-owned or ambiguous surfaces are rejected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from clawwrap.adapters.base import AdapterProtocol
from clawwrap.engine.ownership import (
    AmbiguousSelectorError,
    OwnershipManifest,
    build_ownership_manifest,
)
from clawwrap.model.approval import compute_approval_hash
from clawwrap.model.run import Run

if TYPE_CHECKING:
    pass


class PlannerError(RuntimeError):
    """Base error raised by the planner."""


class NonOwnedSurfaceError(PlannerError):
    """A patch target references a surface not owned by the adapter."""


class AmbiguousPatchTargetError(PlannerError):
    """A patch item uses a structurally ambiguous selector."""


@dataclass
class ApplyPlan:
    """Semantic apply plan produced after a run completes.

    Attributes:
        id: Stable plan identifier.
        run_id: Parent run UUID.
        plan_content: Semantic description of the changes to be applied.
        patch_items: Host-native patch descriptors (list of dicts).
        ownership_manifest: Serialised ownership labels per patch item.
        created_at: When the plan was generated.
        approval_hash: Optional hash binding this plan to an approval record.
    """

    id: uuid.UUID
    run_id: uuid.UUID
    plan_content: dict[str, Any]
    patch_items: list[dict[str, Any]]
    ownership_manifest: dict[str, Any]
    created_at: datetime
    approval_hash: str | None = None

    @classmethod
    def new(
        cls,
        run_id: uuid.UUID,
        plan_content: dict[str, Any],
        patch_items: list[dict[str, Any]],
        ownership_manifest: dict[str, Any],
        approval_hash: str | None = None,
    ) -> ApplyPlan:
        """Construct a new ApplyPlan with a generated UUID and current timestamp."""
        return cls(
            id=uuid.uuid4(),
            run_id=run_id,
            plan_content=plan_content,
            patch_items=patch_items,
            ownership_manifest=ownership_manifest,
            created_at=datetime.utcnow(),
            approval_hash=approval_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "plan_content": self.plan_content,
            "patch_items": self.patch_items,
            "ownership_manifest": self.ownership_manifest,
            "created_at": self.created_at.isoformat(),
            "approval_hash": self.approval_hash,
        }


def generate_apply_plan(run: Run, adapter: AdapterProtocol) -> ApplyPlan:
    """Produce a semantic apply plan from a completed run.

    Steps:
    1. Collect adapter's owned_surfaces to build an OwnershipManifest.
    2. Ask the adapter to generate artifacts (semantic plan items).
    3. Derive host-native patch items from those artifacts.
    4. Validate every patch target against the manifest.
    5. Assemble and return the ApplyPlan.

    Args:
        run: Completed Run (should be in ``planned`` status or later).
        adapter: Host adapter providing owned surfaces and artifact generation.

    Returns:
        ApplyPlan with all items ownership-validated.

    Raises:
        AmbiguousPatchTargetError: If any patch item uses an ambiguous selector.
        NonOwnedSurfaceError: If any patch target is not owned by the adapter.
    """
    manifest = _build_manifest(adapter)
    artifacts = adapter.generate_artifacts(run)
    patch_items = _derive_patch_items(artifacts, run)
    _validate_all_patches(patch_items, manifest)
    plan_content = _build_plan_content(run, artifacts)
    approval_hash = _compute_plan_approval_hash(run)

    return ApplyPlan.new(
        run_id=run.id,
        plan_content=plan_content,
        patch_items=patch_items,
        ownership_manifest=manifest.as_dict(),
        approval_hash=approval_hash,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_manifest(adapter: AdapterProtocol) -> OwnershipManifest:
    """Extract owned_surfaces from the adapter and build a manifest.

    Adapters that implement ``AdapterProtocol`` expose owned surfaces via
    ``get_approval_identity_config`` (config metadata) or via their spec.
    For the manifest, we check if the adapter has a ``get_owned_surfaces``
    method (a common pattern for spec-backed adapters); otherwise we build
    a minimal stub manifest.

    Args:
        adapter: Host adapter instance.

    Returns:
        OwnershipManifest for the adapter.
    """
    from clawwrap.model.adapter import OwnedSurfaceDeclaration

    owned_surfaces: list[OwnedSurfaceDeclaration] = []
    if hasattr(adapter, "get_owned_surfaces"):
        result = getattr(adapter, "get_owned_surfaces")()
        if isinstance(result, list):
            owned_surfaces = result
    elif hasattr(adapter, "_spec") and hasattr(adapter._spec, "owned_surfaces"):  # noqa: SLF001
        raw = getattr(adapter._spec, "owned_surfaces")  # noqa: SLF001
        if isinstance(raw, list):
            owned_surfaces = raw

    config = adapter.get_approval_identity_config()
    adapter_name = config.source_type

    return build_ownership_manifest(adapter_name, owned_surfaces)


def _derive_patch_items(
    artifacts: list[dict[str, Any]],
    run: Run,
) -> list[dict[str, Any]]:
    """Convert adapter artifacts into flat patch item descriptors.

    Each artifact may already contain a ``surface_path`` and ``patch_type``.
    If not, we synthesise a surface_path from the run and artifact index.

    Args:
        artifacts: List of artifact dicts from ``adapter.generate_artifacts()``.
        run: The parent Run (used for fallback naming).

    Returns:
        List of patch item dicts, each with at minimum ``surface_path``,
        ``patch_type``, and ``content`` keys.
    """
    items: list[dict[str, Any]] = []
    for idx, artifact in enumerate(artifacts):
        item: dict[str, Any] = dict(artifact)
        if "surface_path" not in item:
            item["surface_path"] = f"runs/{run.id}/artifact_{idx}"
        if "patch_type" not in item:
            item["patch_type"] = _infer_patch_type(item)
        items.append(item)
    return items


def _infer_patch_type(item: dict[str, Any]) -> str:
    """Infer patch type from artifact content keys.

    Args:
        item: Artifact dict.

    Returns:
        Inferred patch type string.
    """
    if "content" in item:
        return "file_write"
    if "key" in item and "value" in item:
        return "config_set"
    return "unknown"


def _validate_all_patches(
    patch_items: list[dict[str, Any]],
    manifest: OwnershipManifest,
) -> None:
    """Validate every patch item against the ownership manifest.

    Args:
        patch_items: List of patch item dicts.
        manifest: Ownership manifest to validate against.

    Raises:
        AmbiguousPatchTargetError: On structurally ambiguous selectors.
        NonOwnedSurfaceError: On surfaces not owned by the manifest.
    """
    for item in patch_items:
        surface_path = str(item.get("surface_path", ""))
        try:
            manifest.validate_patch_target(surface_path)
        except AmbiguousSelectorError as exc:
            raise AmbiguousPatchTargetError(
                f"Patch item has ambiguous selector: {exc}"
            ) from exc
        except PermissionError as exc:
            raise NonOwnedSurfaceError(str(exc)) from exc


def _build_plan_content(
    run: Run,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the semantic plan_content dict from run metadata and artifacts.

    Args:
        run: The parent Run.
        artifacts: List of adapter artifacts.

    Returns:
        Semantic plan content dict.
    """
    return {
        "wrapper_name": run.wrapper_name,
        "wrapper_version": run.wrapper_version,
        "adapter_name": run.adapter_name,
        "run_id": str(run.id),
        "resolved_inputs": run.resolved_inputs or {},
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def _compute_plan_approval_hash(run: Run) -> str | None:
    """Compute approval hash over the run's resolved inputs.

    Args:
        run: Run whose resolved_inputs drive the hash.

    Returns:
        SHA-256 hex digest, or None if there are no resolved inputs.
    """
    resolved = run.resolved_inputs
    if not resolved:
        return None
    return compute_approval_hash(resolved)
