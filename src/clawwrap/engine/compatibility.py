"""Version compatibility checker enforcing semver rules for clawwrap specs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompatibilityResult:
    """Result of a compatibility check between two spec versions."""

    compatible: bool
    reason: str
    warnings: list[str] = field(default_factory=list)


def _parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch) integers.

    Raises:
        ValueError: If the version string does not conform to ``MAJOR.MINOR.PATCH``.
    """
    parts = version.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid semver '{version}': expected MAJOR.MINOR.PATCH")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as exc:
        raise ValueError(f"Invalid semver '{version}': {exc}") from exc


def _check_spec_version_compat(spec_version: str, target_version: str) -> CompatibilityResult:
    """Check runtime/spec version compatibility using semver rules.

    Rules (per data-model.md):
    - PATCH diff  → fully compatible (no API change)
    - MINOR diff  → backwards compatible (new optional fields / deprecations only)
    - MAJOR diff  → breaking (new required fields, removals, type changes)
    """
    try:
        s_major, s_minor, _s_patch = _parse_semver(spec_version)
        t_major, t_minor, _t_patch = _parse_semver(target_version)
    except ValueError as exc:
        return CompatibilityResult(compatible=False, reason=str(exc))

    if s_major != t_major:
        return CompatibilityResult(
            compatible=False,
            reason=(
                f"Major version mismatch: spec={spec_version}, target={target_version}. "
                "Major version changes are breaking (new required fields, removals, or type changes)."
            ),
        )

    warnings: list[str] = []
    if s_minor != t_minor:
        warnings.append(
            f"Minor version difference: spec={spec_version}, target={target_version}. "
            "New optional fields or deprecations may be present; "
            "older consumers may ignore new fields."
        )

    return CompatibilityResult(
        compatible=True,
        reason=(
            f"Compatible: spec={spec_version}, target={target_version} "
            f"(same major version {s_major})"
        ),
        warnings=warnings,
    )


def _check_schema_version_compat(spec_schema: int, other_schema: int) -> CompatibilityResult:
    """Check cross-entity schema_version integer compatibility.

    A wrapper at schema_version N can reference a policy at schema_version M only when
    both are on the same integer version (no mixing of schema generations).
    """
    if spec_schema == other_schema:
        return CompatibilityResult(
            compatible=True,
            reason=f"Schema versions match: both at schema_version {spec_schema}",
        )

    return CompatibilityResult(
        compatible=False,
        reason=(
            f"Schema version mismatch: spec uses schema_version {spec_schema}, "
            f"other entity uses schema_version {other_schema}. "
            "Cross-schema-version references are not supported."
        ),
    )


def check_compatibility(
    spec_version: str,
    target_version: str,
    schema_version: int,
    other_schema_version: int | None = None,
) -> CompatibilityResult:
    """Check version compatibility between two spec entities.

    Args:
        spec_version: Semver string of the spec being validated (e.g. ``"1.2.0"``).
        target_version: Semver string of the target/reference spec (e.g. ``"1.3.0"``).
        schema_version: The ``schema_version`` integer of the current spec.
        other_schema_version: Optional ``schema_version`` of the referenced entity.
            When provided, cross-entity schema compatibility is also checked.

    Returns:
        CompatibilityResult indicating whether the versions are compatible.
    """
    version_result = _check_spec_version_compat(spec_version, target_version)
    if not version_result.compatible:
        return version_result

    if other_schema_version is not None:
        schema_result = _check_schema_version_compat(schema_version, other_schema_version)
        if not schema_result.compatible:
            return schema_result
        # Merge warnings from both checks.
        return CompatibilityResult(
            compatible=True,
            reason=version_result.reason,
            warnings=version_result.warnings + schema_result.warnings,
        )

    return version_result
