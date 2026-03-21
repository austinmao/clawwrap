"""Ownership manifest — validates that patch targets are owned by the adapter.

Loaded from an adapter's ``owned_surfaces`` declarations.  Provides stable
selector validation and collision detection across multiple manifests.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any

from clawwrap.model.adapter import OwnedSurfaceDeclaration
from clawwrap.model.types import SurfaceType

# Characters that indicate an ambiguous selector.
_AMBIGUOUS_PATTERN = re.compile(r"^[*?]+$")

# Wildcard characters that make a selector non-specific when used alone.
_WILDCARD_CHARS = frozenset({"*", "?"})


@dataclass
class CollisionError:
    """Two ownership manifests claim the same surface path."""

    surface_path: str
    first_owner: str
    second_owner: str

    def __str__(self) -> str:
        return (
            f"Ownership collision on '{self.surface_path}': "
            f"claimed by '{self.first_owner}' and '{self.second_owner}'"
        )


class AmbiguousSelectorError(ValueError):
    """Raised when a selector is structurally ambiguous (e.g. bare ``*``)."""


class OwnershipManifest:
    """Ownership manifest loaded from an adapter's owned_surfaces declarations.

    Provides surface ownership testing and collision detection.

    Args:
        adapter_name: Identifier for the adapter that owns these surfaces.
        declarations: Ordered list of OwnedSurfaceDeclaration entries.
    """

    def __init__(
        self,
        adapter_name: str,
        declarations: list[OwnedSurfaceDeclaration],
    ) -> None:
        self._adapter_name = adapter_name
        self._declarations = declarations
        self._validate_selectors()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def from_adapter(
        cls,
        adapter_name: str,
        owned_surfaces: list[OwnedSurfaceDeclaration],
    ) -> OwnershipManifest:
        """Build a manifest from an adapter's owned_surfaces list.

        Args:
            adapter_name: Name of the owning adapter.
            owned_surfaces: Declarations from the adapter spec.

        Returns:
            Constructed OwnershipManifest.

        Raises:
            AmbiguousSelectorError: If any declaration has an ambiguous selector.
        """
        return cls(adapter_name, owned_surfaces)

    def is_owned(self, surface_path: str) -> bool:
        """Return True if *surface_path* matches at least one owned declaration.

        Matching uses ``fnmatch`` semantics for wildcard patterns.

        Args:
            surface_path: The surface selector to test (e.g. a file path or config key).

        Returns:
            True if owned; False otherwise.
        """
        for decl in self._declarations:
            if fnmatch.fnmatch(surface_path, decl.selector_pattern):
                return True
        return False

    def check_collision(
        self,
        patch_items: list[dict[str, Any]],
        other_manifests: list[OwnershipManifest] | None = None,
    ) -> list[CollisionError]:
        """Detect ownership collisions in *patch_items* against other manifests.

        A collision occurs when two different adapters both claim ownership of
        the same concrete surface path in a patch item.

        Args:
            patch_items: List of patch item dicts, each with a ``surface_path`` key.
            other_manifests: Other OwnershipManifest instances to check against.

        Returns:
            List of CollisionError instances (empty means no collisions).
        """
        if not other_manifests:
            return []

        errors: list[CollisionError] = []
        for item in patch_items:
            path = str(item.get("surface_path", ""))
            if not path:
                continue
            if not self.is_owned(path):
                continue
            for other in other_manifests:
                if other.is_owned(path):
                    errors.append(
                        CollisionError(
                            surface_path=path,
                            first_owner=self._adapter_name,
                            second_owner=other._adapter_name,
                        )
                    )
        return errors

    def validate_patch_target(self, surface_path: str) -> None:
        """Assert that *surface_path* is owned by this manifest.

        Args:
            surface_path: Surface selector string from a patch item.

        Raises:
            AmbiguousSelectorError: If the selector is structurally ambiguous.
            PermissionError: If the surface is not owned by this manifest.
        """
        _assert_not_ambiguous(surface_path)
        if not self.is_owned(surface_path):
            raise PermissionError(
                f"Surface '{surface_path}' is not owned by adapter "
                f"'{self._adapter_name}'. Check owned_surfaces declarations."
            )

    @property
    def adapter_name(self) -> str:
        """Name of the adapter that owns this manifest."""
        return self._adapter_name

    @property
    def declarations(self) -> list[OwnedSurfaceDeclaration]:
        """Owned surface declarations (read-only view)."""
        return list(self._declarations)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the manifest for storage in an apply plan."""
        return {
            "adapter_name": self._adapter_name,
            "owned_surfaces": [
                {
                    "surface_type": decl.surface_type.value,
                    "selector_pattern": decl.selector_pattern,
                }
                for decl in self._declarations
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_selectors(self) -> None:
        """Validate all selector patterns at construction time."""
        for decl in self._declarations:
            _assert_not_ambiguous(decl.selector_pattern)


def _assert_not_ambiguous(selector: str) -> None:
    """Raise AmbiguousSelectorError if *selector* is a bare wildcard.

    A selector is ambiguous if it consists entirely of wildcard characters
    (e.g. ``*``, ``**``, ``?``).

    Args:
        selector: Selector string to validate.

    Raises:
        AmbiguousSelectorError: If the selector is ambiguous.
    """
    stripped = selector.strip()
    if not stripped:
        raise AmbiguousSelectorError("Selector must not be empty.")
    if all(c in _WILDCARD_CHARS for c in stripped):
        raise AmbiguousSelectorError(
            f"Selector '{selector}' is ambiguous: bare wildcard selectors "
            "are not allowed. Use a specific path prefix, e.g. 'config/*'."
        )


def build_ownership_manifest(
    adapter_name: str,
    owned_surfaces: list[OwnedSurfaceDeclaration],
) -> OwnershipManifest:
    """Convenience constructor for building a manifest from raw declarations.

    Args:
        adapter_name: Name of the owning adapter.
        owned_surfaces: List of OwnedSurfaceDeclaration from the adapter spec.

    Returns:
        Constructed OwnershipManifest.

    Raises:
        AmbiguousSelectorError: If any selector is ambiguous.
    """
    return OwnershipManifest.from_adapter(adapter_name, owned_surfaces)


def surface_type_for_path(path: str) -> SurfaceType:
    """Heuristically determine the SurfaceType for a given path string.

    Args:
        path: Surface path or key string.

    Returns:
        Inferred SurfaceType.
    """
    if "/" in path or path.endswith(".md") or path.endswith(".yaml") or path.endswith(".json"):
        return SurfaceType.file
    if "." in path and not path.startswith("."):
        return SurfaceType.config_key
    return SurfaceType.mapping_entry
