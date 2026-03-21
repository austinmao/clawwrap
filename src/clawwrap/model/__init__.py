"""clawwrap model package — typed dataclasses and enums for all domain entities."""

from __future__ import annotations

from clawwrap.model.adapter import (
    ApprovalIdentityConfig,
    HandlerBinding,
    HostAdapter,
    OwnedSurfaceDeclaration,
)
from clawwrap.model.approval import (
    ApprovalIdentityEvidence,
    ApprovalRecord,
    DriftExceptionRecord,
    compute_approval_hash,
)
from clawwrap.model.handler import HandlerContract
from clawwrap.model.policy import CheckDeclaration, Policy
from clawwrap.model.run import Run, StageTransition
from clawwrap.model.types import (
    ApprovalRole,
    ConformanceStatus,
    FailAction,
    RunPhase,
    RunStatus,
    SurfaceType,
)
from clawwrap.model.wrapper import (
    InputField,
    OutputField,
    PolicyRef,
    ProviderRef,
    StageParticipation,
    Wrapper,
    WrapperRef,
)

__all__ = [
    # types
    "ApprovalRole",
    "ConformanceStatus",
    "FailAction",
    "RunPhase",
    "RunStatus",
    "SurfaceType",
    # wrapper
    "InputField",
    "OutputField",
    "PolicyRef",
    "ProviderRef",
    "StageParticipation",
    "Wrapper",
    "WrapperRef",
    # policy
    "CheckDeclaration",
    "Policy",
    # adapter
    "ApprovalIdentityConfig",
    "HandlerBinding",
    "HostAdapter",
    "OwnedSurfaceDeclaration",
    # handler
    "HandlerContract",
    # run
    "Run",
    "StageTransition",
    # approval
    "ApprovalIdentityEvidence",
    "ApprovalRecord",
    "DriftExceptionRecord",
    "compute_approval_hash",
]
