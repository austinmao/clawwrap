"""Policy spec dataclasses loaded from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawwrap.model.types import ApprovalRole, FailAction, RunPhase


@dataclass
class CheckDeclaration:
    """A single check step declared within a policy."""

    handler_id: str
    phase: RunPhase
    params: dict[str, Any]
    fail_action: FailAction

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckDeclaration:
        """Construct a CheckDeclaration from a raw dict."""
        return cls(
            handler_id=data["handler_id"],
            phase=RunPhase(data["phase"]),
            params=dict(data.get("params", {})),
            fail_action=FailAction(data["fail_action"]),
        )


@dataclass
class Policy:
    """Parsed policy spec loaded from YAML."""

    name: str
    version: str
    schema_version: int
    description: str
    checks: list[CheckDeclaration]
    approval_role: ApprovalRole = ApprovalRole.operator

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        """Construct a Policy from a raw dict (e.g. yaml.safe_load output)."""
        raw_role = data.get("approval_role", "operator")
        return cls(
            name=data["name"],
            version=data["version"],
            schema_version=int(data["schema_version"]),
            description=data["description"],
            checks=[CheckDeclaration.from_dict(c) for c in data.get("checks", [])],
            approval_role=ApprovalRole[raw_role] if isinstance(raw_role, str) else ApprovalRole(raw_role),
        )
