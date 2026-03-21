"""Wrapper spec dataclasses loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clawwrap.model.types import ApprovalRole, RunPhase


@dataclass
class InputField:
    """Typed input declaration for a wrapper."""

    name: str
    type: str
    required: bool
    description: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InputField:
        """Construct an InputField from a raw dict."""
        return cls(
            name=data["name"],
            type=data["type"],
            required=bool(data["required"]),
            description=data["description"],
        )


@dataclass
class OutputField:
    """Typed output declaration for a wrapper."""

    name: str
    type: str
    description: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutputField:
        """Construct an OutputField from a raw dict."""
        return cls(
            name=data["name"],
            type=data["type"],
            description=data["description"],
        )


@dataclass
class StageParticipation:
    """Declares which run phase this wrapper participates in and what it expects/produces."""

    phase: RunPhase
    expects: dict[str, Any]
    produces: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageParticipation:
        """Construct a StageParticipation from a raw dict."""
        return cls(
            phase=RunPhase(data["phase"]),
            expects=dict(data["expects"]),
            produces=dict(data["produces"]),
        )


@dataclass
class WrapperRef:
    """Reference to another wrapper as a dependency."""

    name: str
    version_constraint: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WrapperRef:
        """Construct a WrapperRef from a raw dict."""
        return cls(
            name=data["name"],
            version_constraint=data["version_constraint"],
        )


@dataclass
class PolicyRef:
    """Reference to a policy attached to a wrapper."""

    name: str
    version_constraint: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyRef:
        """Construct a PolicyRef from a raw dict."""
        return cls(
            name=data["name"],
            version_constraint=data["version_constraint"],
        )


@dataclass
class ProviderRef:
    """Reference to a required provider or transport."""

    kind: str
    config_ref: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderRef:
        """Construct a ProviderRef from a raw dict."""
        return cls(
            kind=data["kind"],
            config_ref=data["config_ref"],
        )


@dataclass
class Wrapper:
    """Parsed wrapper spec loaded from YAML."""

    name: str
    version: str
    schema_version: int
    description: str
    inputs: list[InputField]
    outputs: list[OutputField]
    stages: list[StageParticipation]
    providers: list[ProviderRef] = field(default_factory=list)
    dependencies: list[WrapperRef] = field(default_factory=list)
    policies: list[PolicyRef] = field(default_factory=list)
    approval_role: ApprovalRole = ApprovalRole.operator

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Wrapper:
        """Construct a Wrapper from a raw dict (e.g. yaml.safe_load output)."""
        raw_role = data.get("approval_role", "operator")
        return cls(
            name=data["name"],
            version=data["version"],
            schema_version=int(data["schema_version"]),
            description=data["description"],
            inputs=[InputField.from_dict(f) for f in data.get("inputs", [])],
            outputs=[OutputField.from_dict(f) for f in data.get("outputs", [])],
            stages=[StageParticipation.from_dict(s) for s in data.get("stages", [])],
            providers=[ProviderRef.from_dict(p) for p in data.get("providers", [])],
            dependencies=[WrapperRef.from_dict(d) for d in data.get("dependencies", [])],
            policies=[PolicyRef.from_dict(p) for p in data.get("policies", [])],
            approval_role=ApprovalRole[raw_role] if isinstance(raw_role, str) else ApprovalRole(raw_role),
        )
