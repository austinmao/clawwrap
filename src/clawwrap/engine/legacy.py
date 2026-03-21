"""Legacy authority inventory and cutover verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from clawwrap.model.types import ConformanceStatus


@dataclass
class LegacySource:
    source_type: str  # "prompt" or "config"
    source_path: str
    expected_status: str  # "removed", "disabled", "shadowed_unreachable"
    section: str | None = None
    config_key: str | None = None


@dataclass
class LegacyInventory:
    flow_name: str
    description: str
    sources: list[LegacySource]


@dataclass
class SourceVerification:
    source: LegacySource
    observed_status: str
    matches: bool
    detail: str


@dataclass
class CutoverResult:
    flow_name: str
    status: ConformanceStatus
    verifications: list[SourceVerification]
    errors: list[str]


def build_inventory(flow_name: str, legacy_dir: Path | None = None) -> LegacyInventory:
    """Load a flow's legacy authority inventory from its YAML file."""
    if legacy_dir is None:
        legacy_dir = Path("specs/legacy")

    inventory_file = legacy_dir / f"{flow_name}.yaml"
    if not inventory_file.exists():
        msg = f"Legacy inventory not found: {inventory_file}"
        raise FileNotFoundError(msg)

    with open(inventory_file) as f:
        data = yaml.safe_load(f)

    sources = []
    for src in data.get("legacy_sources", []):
        sources.append(LegacySource(
            source_type=src["source_type"],
            source_path=src["source_path"],
            expected_status=src["expected_status"],
            section=src.get("section"),
            config_key=src.get("config_key"),
        ))

    return LegacyInventory(
        flow_name=data["flow_name"],
        description=data.get("description", ""),
        sources=sources,
    )


def verify_cutover(flow_name: str, adapter: Any, legacy_dir: Path | None = None) -> CutoverResult:
    """Verify cutover completeness for a migrated flow."""
    inventory = build_inventory(flow_name, legacy_dir)
    verifications: list[SourceVerification] = []
    errors: list[str] = []

    for source in inventory.sources:
        verification = _verify_source(source, adapter)
        verifications.append(verification)
        if not verification.matches:
            errors.append(verification.detail)

    status = ConformanceStatus.matching if not errors else ConformanceStatus.drifted
    return CutoverResult(
        flow_name=flow_name,
        status=status,
        verifications=verifications,
        errors=errors,
    )


def _verify_source(source: LegacySource, adapter: Any) -> SourceVerification:
    """Verify a single legacy source against its expected post-cutover status."""
    if source.expected_status == "shadowed_unreachable":
        return _verify_shadowed_unreachable(source, adapter)

    if source.expected_status == "removed":
        return _verify_removed(source, adapter)

    if source.expected_status == "disabled":
        return _verify_disabled(source, adapter)

    return SourceVerification(
        source=source,
        observed_status="unknown",
        matches=False,
        detail=f"Unknown expected status: {source.expected_status}",
    )


def _verify_removed(source: LegacySource, adapter: Any) -> SourceVerification:
    """Verify a legacy source has been removed."""
    host_state = adapter.read_host_state([source.source_path])

    path_key = source.source_path
    if path_key in host_state and host_state[path_key] is not None:
        return SourceVerification(
            source=source,
            observed_status="present",
            matches=False,
            detail=f"Legacy source still present: {source.source_path}",
        )

    return SourceVerification(
        source=source,
        observed_status="removed",
        matches=True,
        detail="Legacy source confirmed removed",
    )


def _verify_disabled(source: LegacySource, adapter: Any) -> SourceVerification:
    """Verify a legacy source has been disabled."""
    key = source.config_key or source.source_path
    host_state = adapter.read_host_state([key])
    value = host_state.get(key)
    if value is not None and value != "__disabled__":
        return SourceVerification(
            source=source,
            observed_status="active",
            matches=False,
            detail=f"Legacy source still active: {key}",
        )

    return SourceVerification(
        source=source,
        observed_status="disabled",
        matches=True,
        detail="Legacy source confirmed disabled",
    )


def _verify_shadowed_unreachable(source: LegacySource, adapter: Any) -> SourceVerification:
    """Verify a legacy source is shadowed and unreachable.

    Per FR-021: requires selector, precedence, and reachability tests
    before shadowed_unreachable can be claimed.
    """
    if not _adapter_has_reachability_support(adapter):
        return SourceVerification(
            source=source,
            observed_status="not_verified",
            matches=False,
            detail=(
                f"Cannot verify shadowed_unreachable for {source.source_path}: "
                "adapter does not provide selector, precedence, and reachability tests"
            ),
        )

    reachable = test_reachability(source, adapter)
    if reachable:
        return SourceVerification(
            source=source,
            observed_status="reachable",
            matches=False,
            detail=f"Legacy source still reachable: {source.source_path}",
        )

    return SourceVerification(
        source=source,
        observed_status="shadowed_unreachable",
        matches=True,
        detail="Legacy source confirmed shadowed and unreachable",
    )


def _adapter_has_reachability_support(adapter: Any) -> bool:
    """Check if adapter supports reachability testing."""
    return (
        hasattr(adapter, "get_selector_rules")
        and hasattr(adapter, "get_precedence_rules")
        and hasattr(adapter, "test_reachability")
    )


def test_reachability(source: LegacySource, adapter: Any) -> bool:
    """Test whether a legacy source can still influence live flow selection.

    Delegates to the adapter's reachability testing if available.
    """
    if hasattr(adapter, "test_reachability"):
        result: bool = getattr(adapter, "test_reachability")(source.source_path, source.config_key)
        return result
    return True  # Assume reachable if no test available
