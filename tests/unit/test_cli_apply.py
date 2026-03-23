"""Regression tests for CLI adapter dispatch and apply-plan persistence."""

from __future__ import annotations

import uuid
from argparse import Namespace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from clawwrap.adapters.openclaw.adapter import OpenClawAdapter
from clawwrap.cli import apply as apply_cli
from clawwrap.cli import conformance as conformance_cli
from clawwrap.cli import run as run_cli
from clawwrap.engine.planner import ApplyPlan
from clawwrap.model.run import Run
from clawwrap.model.types import RunPhase, RunStatus


def _make_run(status: RunStatus = RunStatus.planned, adapter_name: str = "openclaw") -> Run:
    """Build a minimal Run for CLI tests."""
    now = datetime.now(UTC)
    return Run(
        id=uuid.uuid4(),
        wrapper_name="verified-send",
        wrapper_version="1.0.0",
        adapter_name=adapter_name,
        current_phase=RunPhase.audit,
        status=status,
        created_at=now,
        updated_at=now,
        resolved_inputs={},
    )


@pytest.mark.parametrize("module", [run_cli, apply_cli, conformance_cli])
def test_cli_adapter_helpers_support_openclaw(module: Any) -> None:
    """All CLI helper modules must resolve the production OpenClaw adapter."""
    adapter = module._get_adapter("openclaw")

    assert isinstance(adapter, OpenClawAdapter)


def test_apply_plan_command_persists_generated_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """`clawwrap apply plan` must save the generated plan for later conformance checks."""
    run = _make_run()
    plan = ApplyPlan.new(
        run_id=run.id,
        plan_content={
            "wrapper_name": run.wrapper_name,
            "wrapper_version": run.wrapper_version,
        },
        patch_items=[
            {
                "surface_path": "agents/generated/verified-send-runtime.yaml",
                "patch_type": "file_write",
                "content": "expected runtime content",
            }
        ],
        ownership_manifest={"adapter_name": "openclaw", "owned_surfaces": []},
        approval_hash="test-hash",
    )
    store = MagicMock()
    store.get_run.return_value = run
    store.save_apply_plan.return_value = uuid.uuid4()

    monkeypatch.setattr(apply_cli, "_get_store", lambda args: store)

    import clawwrap.engine.planner as planner

    monkeypatch.setattr(planner, "generate_apply_plan", lambda current_run, adapter: plan)

    exit_code = apply_cli._handle_plan(
        Namespace(
            run_id=str(run.id),
            format="json",
        )
    )

    assert exit_code == 0
    store.save_apply_plan.assert_called_once_with(
        run_id=run.id,
        plan_content=plan.plan_content,
        patch_items=plan.patch_items,
        ownership_manifest=plan.ownership_manifest,
        approval_hash=plan.approval_hash,
    )
