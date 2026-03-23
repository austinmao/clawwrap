"""T065: Unit tests for conformance-related data model aspects.

The conformance engine itself may not yet be written.
These tests cover the data model: ConformanceStatus enum values
and DriftExceptionRecord lattice constraints (already tested in depth
in test_approval.py — this file focuses on the conformance status enum
and its use in CutoverResult from legacy.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from clawwrap.engine.conformance import check_conformance
from clawwrap.model.types import ConformanceStatus

# ---------------------------------------------------------------------------
# ConformanceStatus enum values
# ---------------------------------------------------------------------------


class TestConformanceStatusEnum:
    """Tests for ConformanceStatus enum."""

    def test_matching_value(self) -> None:
        """ConformanceStatus.matching must have value 'matching'."""
        assert ConformanceStatus.matching.value == "matching"

    def test_drifted_value(self) -> None:
        """ConformanceStatus.drifted must have value 'drifted'."""
        assert ConformanceStatus.drifted.value == "drifted"

    def test_not_checked_value(self) -> None:
        """ConformanceStatus.not_checked must have value 'not_checked'."""
        assert ConformanceStatus.not_checked.value == "not_checked"

    def test_three_values_exist(self) -> None:
        """ConformanceStatus must have exactly three members."""
        members = list(ConformanceStatus)
        assert len(members) == 3

    def test_round_trip_by_value(self) -> None:
        """ConformanceStatus must be constructible from its string value."""
        for status in ConformanceStatus:
            assert ConformanceStatus(status.value) == status

    def test_invalid_value_raises(self) -> None:
        """Unknown string must raise ValueError."""
        with pytest.raises(ValueError):
            ConformanceStatus("unknown_status")


# ---------------------------------------------------------------------------
# DriftExceptionRecord role constraint (conformance-domain perspective)
# ---------------------------------------------------------------------------


class TestDriftExceptionRoleConstraint:
    """Verify the lattice constraint from the conformance exception perspective."""

    def test_operator_cannot_approve_exception_for_admin_run(self) -> None:
        """operator role must not be permitted to override an admin-approved run."""
        from clawwrap.model.approval import DriftExceptionRecord
        from clawwrap.model.types import ApprovalRole

        with pytest.raises(ValueError):
            DriftExceptionRecord.new(
                run_id=uuid.uuid4(),
                conformance_id=uuid.uuid4(),
                reason="Attempting to approve with insufficient role",
                identity_source="test",
                subject_id="user@test.com",
                role=ApprovalRole.operator,
                original_apply_role=ApprovalRole.admin,
            )

    def test_admin_can_approve_exception_for_operator_run(self) -> None:
        """admin role must be permitted to override an operator-approved run."""
        from clawwrap.model.approval import DriftExceptionRecord
        from clawwrap.model.types import ApprovalRole

        record = DriftExceptionRecord.new(
            run_id=uuid.uuid4(),
            conformance_id=uuid.uuid4(),
            reason="Admin override",
            identity_source="test",
            subject_id="admin@test.com",
            role=ApprovalRole.admin,
            original_apply_role=ApprovalRole.operator,
        )
        assert record.role == ApprovalRole.admin

    def test_approver_can_approve_exception_for_approver_run(self) -> None:
        """approver role == approver must be permitted (same level)."""
        from clawwrap.model.approval import DriftExceptionRecord
        from clawwrap.model.types import ApprovalRole

        record = DriftExceptionRecord.new(
            run_id=uuid.uuid4(),
            conformance_id=uuid.uuid4(),
            reason="Peer approval",
            identity_source="test",
            subject_id="approver@test.com",
            role=ApprovalRole.approver,
            original_apply_role=ApprovalRole.approver,
        )
        assert record.role == ApprovalRole.approver


# ---------------------------------------------------------------------------
# Legacy build_inventory — conformance-adjacent behaviour
# ---------------------------------------------------------------------------


class TestBuildInventory:
    """Tests for legacy.build_inventory YAML loading."""

    def test_build_inventory_loads_yaml(self, tmp_path: Path) -> None:
        """build_inventory must load a valid legacy YAML file."""
        import yaml

        from clawwrap.engine.legacy import build_inventory

        data: dict[str, Any] = {
            "flow_name": "test-flow",
            "description": "A test flow",
            "legacy_sources": [
                {
                    "source_type": "prompt",
                    "source_path": "agents/test/SOUL.md",
                    "expected_status": "removed",
                }
            ],
        }
        legacy_dir = tmp_path / "specs" / "legacy"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "test-flow.yaml").write_text(yaml.dump(data), encoding="utf-8")

        inventory = build_inventory("test-flow", legacy_dir=legacy_dir)

        assert inventory.flow_name == "test-flow"
        assert len(inventory.sources) == 1
        assert inventory.sources[0].source_path == "agents/test/SOUL.md"

    def test_build_inventory_missing_file_raises(self, tmp_path: Path) -> None:
        """build_inventory must raise FileNotFoundError when the YAML does not exist."""
        from clawwrap.engine.legacy import build_inventory

        with pytest.raises(FileNotFoundError):
            build_inventory("nonexistent-flow", legacy_dir=tmp_path)


# ---------------------------------------------------------------------------
# verify_cutover — conformance status mapping
# ---------------------------------------------------------------------------


class TestVerifyCutoverStatus:
    """Tests for legacy.verify_cutover conformance status mapping."""

    def test_all_sources_match_produces_matching_status(self, tmp_path: Path) -> None:
        """When all sources match, CutoverResult.status must be ConformanceStatus.matching."""
        import yaml

        from clawwrap.engine.legacy import verify_cutover

        data: dict[str, Any] = {
            "flow_name": "clean-flow",
            "description": "All removed",
            "legacy_sources": [
                {
                    "source_type": "prompt",
                    "source_path": "agents/old/SOUL.md",
                    "expected_status": "removed",
                }
            ],
        }
        legacy_dir = tmp_path
        (legacy_dir / "clean-flow.yaml").write_text(yaml.dump(data), encoding="utf-8")

        # Adapter reports path as absent (None)
        mock_adapter = MagicMock()
        mock_adapter.read_host_state.return_value = {"agents/old/SOUL.md": None}

        result = verify_cutover("clean-flow", mock_adapter, legacy_dir=legacy_dir)

        assert result.status == ConformanceStatus.matching
        assert result.errors == []

    def test_source_still_present_produces_drifted_status(self, tmp_path: Path) -> None:
        """When a removed source is still present, status must be ConformanceStatus.drifted."""
        import yaml

        from clawwrap.engine.legacy import verify_cutover

        data: dict[str, Any] = {
            "flow_name": "drifted-flow",
            "description": "Still present",
            "legacy_sources": [
                {
                    "source_type": "prompt",
                    "source_path": "agents/old/SOUL.md",
                    "expected_status": "removed",
                }
            ],
        }
        legacy_dir = tmp_path
        (legacy_dir / "drifted-flow.yaml").write_text(yaml.dump(data), encoding="utf-8")

        # Adapter reports the path as present
        mock_adapter = MagicMock()
        mock_adapter.read_host_state.return_value = {
            "agents/old/SOUL.md": "# Still here"
        }

        result = verify_cutover("drifted-flow", mock_adapter, legacy_dir=legacy_dir)

        assert result.status == ConformanceStatus.drifted
        assert len(result.errors) > 0

    def test_removed_and_disabled_checks_pass_string_selectors(self, tmp_path: Path) -> None:
        """Removed and disabled legacy checks must call read_host_state with string keys."""
        import yaml

        from clawwrap.engine.legacy import verify_cutover

        data: dict[str, Any] = {
            "flow_name": "selector-flow",
            "description": "Removed and disabled sources",
            "legacy_sources": [
                {
                    "source_type": "prompt",
                    "source_path": "agents/old/SOUL.md",
                    "expected_status": "removed",
                },
                {
                    "source_type": "config",
                    "source_path": "legacy/path",
                    "config_key": "hooks.mappings.legacy_flow",
                    "expected_status": "disabled",
                },
            ],
        }
        legacy_dir = tmp_path
        (legacy_dir / "selector-flow.yaml").write_text(yaml.dump(data), encoding="utf-8")

        seen_selectors: list[list[str]] = []

        def _read_host_state(selectors: list[str]) -> dict[str, Any]:
            seen_selectors.append(selectors)
            assert all(isinstance(selector, str) for selector in selectors)
            key = selectors[0]
            if key == "hooks.mappings.legacy_flow":
                return {key: "__disabled__"}
            return {key: None}

        mock_adapter = MagicMock()
        mock_adapter.read_host_state.side_effect = _read_host_state

        result = verify_cutover("selector-flow", mock_adapter, legacy_dir=legacy_dir)

        assert result.status == ConformanceStatus.matching
        assert seen_selectors == [
            ["agents/old/SOUL.md"],
            ["hooks.mappings.legacy_flow"],
        ]


class TestCheckConformance:
    """Tests for conformance checks against persisted apply plans."""

    def test_check_conformance_uses_persisted_apply_plan_surfaces(self) -> None:
        """check_conformance must compare the surfaces from the stored apply plan."""
        from clawwrap.model.run import Run
        from clawwrap.model.types import RunPhase, RunStatus

        run = Run(
            id=uuid.uuid4(),
            wrapper_name="verified-send",
            wrapper_version="1.0.0",
            adapter_name="openclaw",
            current_phase=RunPhase.audit,
            status=RunStatus.conformance_pending,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            resolved_inputs={},
        )
        store = MagicMock()
        store.get_apply_plan.return_value = {
            "run_id": str(run.id),
            "patch_items": [
                {
                    "surface_path": "agents/generated/verified-send-runtime.yaml",
                    "content": "expected runtime content",
                }
            ],
        }
        store.save_conformance.return_value = uuid.uuid4()

        adapter = MagicMock()
        adapter.read_host_state.return_value = {
            "agents/generated/verified-send-runtime.yaml": "expected runtime content"
        }

        result = check_conformance(run, adapter, store)

        adapter.read_host_state.assert_called_once_with(
            ["agents/generated/verified-send-runtime.yaml"]
        )
        store.update_run_status.assert_called_once()
        assert store.update_run_status.call_args.args[1] == RunStatus.applied
        assert result.status == ConformanceStatus.matching
