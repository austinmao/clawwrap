"""T067: Unit tests for clawwrap model from_dict constructors.

Covers:
- Wrapper.from_dict constructs correctly
- Policy.from_dict constructs correctly
- HostAdapter.from_dict constructs correctly
- Missing required fields raise errors
- Default approval_role is operator
"""

from __future__ import annotations

from typing import Any

import pytest

from clawwrap.model.adapter import HostAdapter
from clawwrap.model.policy import Policy
from clawwrap.model.types import ApprovalRole, FailAction, RunPhase, SurfaceType
from clawwrap.model.wrapper import Wrapper

# ---------------------------------------------------------------------------
# Wrapper.from_dict
# ---------------------------------------------------------------------------


class TestWrapperFromDict:
    """Tests for Wrapper.from_dict."""

    def test_constructs_basic_fields(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must set name, version, schema_version, description."""
        wrapper = Wrapper.from_dict(sample_wrapper_dict)

        assert wrapper.name == "test-wrapper"
        assert wrapper.version == "1.0.0"
        assert wrapper.schema_version == 1
        assert wrapper.description == "A test wrapper for unit tests"

    def test_constructs_inputs(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must parse inputs list correctly."""
        wrapper = Wrapper.from_dict(sample_wrapper_dict)

        assert len(wrapper.inputs) == 1
        assert wrapper.inputs[0].name == "target_group"
        assert wrapper.inputs[0].type == "string"
        assert wrapper.inputs[0].required is True

    def test_constructs_outputs(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must parse outputs list correctly."""
        wrapper = Wrapper.from_dict(sample_wrapper_dict)

        assert len(wrapper.outputs) == 1
        assert wrapper.outputs[0].name == "result"
        assert wrapper.outputs[0].type == "string"

    def test_constructs_stages(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must parse stages list with correct RunPhase."""
        wrapper = Wrapper.from_dict(sample_wrapper_dict)

        assert len(wrapper.stages) == 1
        assert wrapper.stages[0].phase == RunPhase.resolve

    def test_default_approval_role_is_operator(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must default approval_role to operator when not specified."""
        data = dict(sample_wrapper_dict)
        data.pop("approval_role", None)
        wrapper = Wrapper.from_dict(data)

        assert wrapper.approval_role == ApprovalRole.operator

    def test_explicit_approval_role_parsed(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must accept an explicit approval_role value."""
        data = dict(sample_wrapper_dict)
        data["approval_role"] = "admin"
        wrapper = Wrapper.from_dict(data)

        assert wrapper.approval_role == ApprovalRole.admin

    def test_empty_lists_default(self, sample_wrapper_dict: dict[str, Any]) -> None:
        """from_dict must default providers, dependencies, policies to empty lists."""
        data = dict(sample_wrapper_dict)
        # Ensure these keys are absent
        data.pop("providers", None)
        data.pop("dependencies", None)
        data.pop("policies", None)
        wrapper = Wrapper.from_dict(data)

        assert wrapper.providers == []
        assert wrapper.dependencies == []
        assert wrapper.policies == []

    def test_missing_name_raises_key_error(self) -> None:
        """from_dict without 'name' must raise KeyError."""
        data: dict[str, Any] = {
            "version": "1.0.0",
            "schema_version": 1,
            "description": "No name",
            "inputs": [],
            "outputs": [],
            "stages": [],
        }
        with pytest.raises(KeyError):
            Wrapper.from_dict(data)

    def test_missing_version_raises_key_error(self) -> None:
        """from_dict without 'version' must raise KeyError."""
        data: dict[str, Any] = {
            "name": "test",
            "schema_version": 1,
            "description": "No version",
            "inputs": [],
            "outputs": [],
            "stages": [],
        }
        with pytest.raises(KeyError):
            Wrapper.from_dict(data)

    def test_invalid_stage_phase_raises_value_error(self) -> None:
        """from_dict with unknown stage phase must raise ValueError."""
        data: dict[str, Any] = {
            "name": "test",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "Bad stage",
            "inputs": [],
            "outputs": [],
            "stages": [
                {"phase": "nonexistent", "expects": {}, "produces": {}}
            ],
        }
        with pytest.raises(ValueError):
            Wrapper.from_dict(data)

    def test_dependency_parsed(self) -> None:
        """from_dict must parse dependencies list into WrapperRef objects."""
        data: dict[str, Any] = {
            "name": "test-wrapper",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "Has deps",
            "inputs": [],
            "outputs": [],
            "stages": [{"phase": "resolve", "expects": {}, "produces": {}}],
            "dependencies": [
                {"name": "other-wrapper", "version_constraint": ">=1.0.0"}
            ],
        }
        wrapper = Wrapper.from_dict(data)

        assert len(wrapper.dependencies) == 1
        assert wrapper.dependencies[0].name == "other-wrapper"
        assert wrapper.dependencies[0].version_constraint == ">=1.0.0"

    def test_policy_ref_parsed(self) -> None:
        """from_dict must parse policies list into PolicyRef objects."""
        data: dict[str, Any] = {
            "name": "test-wrapper",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "Has policy",
            "inputs": [],
            "outputs": [],
            "stages": [{"phase": "resolve", "expects": {}, "produces": {}}],
            "policies": [
                {"name": "my-policy", "version_constraint": ">=1.0.0"}
            ],
        }
        wrapper = Wrapper.from_dict(data)

        assert len(wrapper.policies) == 1
        assert wrapper.policies[0].name == "my-policy"


# ---------------------------------------------------------------------------
# Policy.from_dict
# ---------------------------------------------------------------------------


class TestPolicyFromDict:
    """Tests for Policy.from_dict."""

    def test_constructs_basic_fields(self, sample_policy_dict: dict[str, Any]) -> None:
        """from_dict must set name, version, schema_version, description."""
        policy = Policy.from_dict(sample_policy_dict)

        assert policy.name == "test-policy"
        assert policy.version == "1.0.0"
        assert policy.schema_version == 1

    def test_constructs_checks(self, sample_policy_dict: dict[str, Any]) -> None:
        """from_dict must parse checks list with handler_id, phase, fail_action."""
        policy = Policy.from_dict(sample_policy_dict)

        assert len(policy.checks) == 1
        assert policy.checks[0].handler_id == "target.resolve_from_canonical"
        assert policy.checks[0].phase == RunPhase.resolve
        assert policy.checks[0].fail_action == FailAction.block

    def test_default_approval_role_is_operator(self, sample_policy_dict: dict[str, Any]) -> None:
        """from_dict must default approval_role to operator."""
        data = dict(sample_policy_dict)
        data.pop("approval_role", None)
        policy = Policy.from_dict(data)

        assert policy.approval_role == ApprovalRole.operator

    def test_approver_role_parsed(self, sample_policy_dict: dict[str, Any]) -> None:
        """from_dict must parse approval_role=approver correctly."""
        data = dict(sample_policy_dict)
        data["approval_role"] = "approver"
        policy = Policy.from_dict(data)

        assert policy.approval_role == ApprovalRole.approver

    def test_missing_name_raises_key_error(self) -> None:
        """from_dict without 'name' must raise KeyError."""
        data: dict[str, Any] = {
            "version": "1.0.0",
            "schema_version": 1,
            "description": "No name",
            "checks": [{"handler_id": "target.x", "phase": "resolve", "fail_action": "block"}],
        }
        with pytest.raises(KeyError):
            Policy.from_dict(data)

    def test_check_default_params_is_empty_dict(self) -> None:
        """CheckDeclaration.from_dict must default params to empty dict."""
        data: dict[str, Any] = {
            "name": "p",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "test",
            "checks": [
                {
                    "handler_id": "target.something",
                    "phase": "verify",
                    "fail_action": "warn",
                    # params intentionally absent
                }
            ],
        }
        policy = Policy.from_dict(data)

        assert policy.checks[0].params == {}

    def test_warn_fail_action_parsed(self, sample_policy_dict: dict[str, Any]) -> None:
        """from_dict must parse fail_action=warn correctly."""
        data = dict(sample_policy_dict)
        data["checks"] = [
            {
                "handler_id": "target.something",
                "phase": "audit",
                "fail_action": "warn",
            }
        ]
        policy = Policy.from_dict(data)

        assert policy.checks[0].fail_action == FailAction.warn


# ---------------------------------------------------------------------------
# HostAdapter.from_dict
# ---------------------------------------------------------------------------


class TestHostAdapterFromDict:
    """Tests for HostAdapter.from_dict."""

    def test_constructs_basic_fields(self, sample_adapter_dict: dict[str, Any]) -> None:
        """from_dict must set name, version, schema_version."""
        adapter = HostAdapter.from_dict(sample_adapter_dict)

        assert adapter.name == "test-adapter"
        assert adapter.version == "1.0.0"
        assert adapter.schema_version == 1

    def test_constructs_supported_handlers(self, sample_adapter_dict: dict[str, Any]) -> None:
        """from_dict must parse supported_handlers list."""
        adapter = HostAdapter.from_dict(sample_adapter_dict)

        assert len(adapter.supported_handlers) == 1
        assert adapter.supported_handlers[0].handler_id == "target.resolve_from_canonical"
        assert adapter.supported_handlers[0].contract_version == "1.0.0"
        assert adapter.supported_handlers[0].binding_module == "clawwrap.adapters.test.handlers"

    def test_constructs_approval_identity(self, sample_adapter_dict: dict[str, Any]) -> None:
        """from_dict must parse approval_identity correctly."""
        adapter = HostAdapter.from_dict(sample_adapter_dict)

        assert adapter.approval_identity.source_type == "local-cli"
        assert adapter.approval_identity.subject_key == "subject_id"
        assert adapter.approval_identity.trust_basis == "local-cli-development"

    def test_constructs_owned_surfaces(self, sample_adapter_dict: dict[str, Any]) -> None:
        """from_dict must parse owned_surfaces with correct SurfaceType."""
        adapter = HostAdapter.from_dict(sample_adapter_dict)

        assert len(adapter.owned_surfaces) == 1
        assert adapter.owned_surfaces[0].surface_type == SurfaceType.file
        assert adapter.owned_surfaces[0].selector_pattern == "**/*.yaml"

    def test_constructs_capabilities(self, sample_adapter_dict: dict[str, Any]) -> None:
        """from_dict must parse capabilities list."""
        adapter = HostAdapter.from_dict(sample_adapter_dict)

        assert "read" in adapter.capabilities
        assert "write" in adapter.capabilities

    def test_empty_capabilities_defaults(self) -> None:
        """from_dict must default capabilities to empty list when absent."""
        data: dict[str, Any] = {
            "name": "minimal-adapter",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "Minimal",
            "supported_handlers": [],
            "approval_identity": {
                "source_type": "test",
                "subject_key": "id",
                "trust_basis": "test",
            },
            "owned_surfaces": [],
            # capabilities intentionally absent
        }
        adapter = HostAdapter.from_dict(data)

        assert adapter.capabilities == []

    def test_missing_approval_identity_raises(self) -> None:
        """from_dict without approval_identity must raise KeyError."""
        data: dict[str, Any] = {
            "name": "bad-adapter",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "No identity",
            "supported_handlers": [],
            "owned_surfaces": [],
            "capabilities": [],
            # approval_identity intentionally absent
        }
        with pytest.raises(KeyError):
            HostAdapter.from_dict(data)

    def test_invalid_surface_type_raises_value_error(self) -> None:
        """from_dict with an unknown surface_type must raise ValueError."""
        data: dict[str, Any] = {
            "name": "bad-surface",
            "version": "1.0.0",
            "schema_version": 1,
            "description": "Bad surface",
            "supported_handlers": [],
            "approval_identity": {
                "source_type": "test",
                "subject_key": "id",
                "trust_basis": "test",
            },
            "owned_surfaces": [
                {"surface_type": "unknown_surface", "selector_pattern": "**"}
            ],
            "capabilities": [],
        }
        with pytest.raises(ValueError):
            HostAdapter.from_dict(data)
