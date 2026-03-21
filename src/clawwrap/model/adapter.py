"""Host adapter spec dataclasses loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clawwrap.model.types import SurfaceType


@dataclass
class HandlerBinding:
    """Binding from a global handler ID to an adapter-specific implementation module."""

    handler_id: str
    contract_version: str
    binding_module: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandlerBinding:
        """Construct a HandlerBinding from a raw dict."""
        return cls(
            handler_id=data["handler_id"],
            contract_version=data["contract_version"],
            binding_module=data["binding_module"],
        )


@dataclass
class ApprovalIdentityConfig:
    """Configuration describing how the adapter resolves approval identity evidence."""

    source_type: str
    subject_key: str
    trust_basis: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalIdentityConfig:
        """Construct an ApprovalIdentityConfig from a raw dict."""
        return cls(
            source_type=data["source_type"],
            subject_key=data["subject_key"],
            trust_basis=data["trust_basis"],
        )


@dataclass
class OwnedSurfaceDeclaration:
    """Declares a host surface type and selector pattern owned by this adapter."""

    surface_type: SurfaceType
    selector_pattern: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OwnedSurfaceDeclaration:
        """Construct an OwnedSurfaceDeclaration from a raw dict."""
        return cls(
            surface_type=SurfaceType(data["surface_type"]),
            selector_pattern=data["selector_pattern"],
        )


@dataclass
class HostAdapter:
    """Parsed host adapter spec loaded from YAML."""

    name: str
    version: str
    schema_version: int
    supported_handlers: list[HandlerBinding]
    approval_identity: ApprovalIdentityConfig
    owned_surfaces: list[OwnedSurfaceDeclaration]
    capabilities: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HostAdapter:
        """Construct a HostAdapter from a raw dict (e.g. yaml.safe_load output)."""
        return cls(
            name=data["name"],
            version=data["version"],
            schema_version=int(data["schema_version"]),
            supported_handlers=[HandlerBinding.from_dict(h) for h in data.get("supported_handlers", [])],
            approval_identity=ApprovalIdentityConfig.from_dict(data["approval_identity"]),
            owned_surfaces=[OwnedSurfaceDeclaration.from_dict(s) for s in data.get("owned_surfaces", [])],
            capabilities=list(data.get("capabilities", [])),
        )
