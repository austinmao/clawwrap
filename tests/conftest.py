"""T061: Shared pytest fixtures for clawwrap test suite.

Provides sample dicts and tmp_path-based YAML file fixtures.
No Postgres fixtures are included — those require a live DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# ---------------------------------------------------------------------------
# Sample raw dicts (as yaml.safe_load would return)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_wrapper_dict() -> dict[str, Any]:
    """Minimal valid wrapper spec dict."""
    return {
        "name": "test-wrapper",
        "version": "1.0.0",
        "schema_version": 1,
        "description": "A test wrapper for unit tests",
        "inputs": [
            {
                "name": "target_group",
                "type": "string",
                "required": True,
                "description": "Target group name",
            }
        ],
        "outputs": [
            {
                "name": "result",
                "type": "string",
                "description": "Operation result",
            }
        ],
        "stages": [
            {
                "phase": "resolve",
                "expects": {"target_group": "string"},
                "produces": {"canonical_name": "string"},
            }
        ],
        "approval_role": "operator",
    }


@pytest.fixture
def sample_policy_dict() -> dict[str, Any]:
    """Minimal valid policy spec dict."""
    return {
        "name": "test-policy",
        "version": "1.0.0",
        "schema_version": 1,
        "description": "A test policy for unit tests",
        "checks": [
            {
                "handler_id": "target.resolve_from_canonical",
                "phase": "resolve",
                "params": {"allow_ambiguous": False},
                "fail_action": "block",
            }
        ],
        "approval_role": "operator",
    }


@pytest.fixture
def sample_adapter_dict() -> dict[str, Any]:
    """Minimal valid host adapter spec dict."""
    return {
        "name": "test-adapter",
        "version": "1.0.0",
        "schema_version": 1,
        "description": "A test host adapter for unit tests",
        "supported_handlers": [
            {
                "handler_id": "target.resolve_from_canonical",
                "contract_version": "1.0.0",
                "binding_module": "clawwrap.adapters.test.handlers",
            }
        ],
        "approval_identity": {
            "source_type": "local-cli",
            "subject_key": "subject_id",
            "trust_basis": "local-cli-development",
        },
        "owned_surfaces": [
            {
                "surface_type": "file",
                "selector_pattern": "**/*.yaml",
            }
        ],
        "capabilities": ["read", "write"],
    }


# ---------------------------------------------------------------------------
# tmp_path YAML file fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wrapper_yaml_file(tmp_path: Path, sample_wrapper_dict: dict[str, Any]) -> Path:
    """Write a valid wrapper YAML file and return its path."""
    spec_file = tmp_path / "test-wrapper.yaml"
    spec_file.write_text(yaml.dump(sample_wrapper_dict), encoding="utf-8")
    return spec_file


@pytest.fixture
def policy_yaml_file(tmp_path: Path, sample_policy_dict: dict[str, Any]) -> Path:
    """Write a valid policy YAML file and return its path."""
    spec_file = tmp_path / "test-policy.yaml"
    spec_file.write_text(yaml.dump(sample_policy_dict), encoding="utf-8")
    return spec_file


@pytest.fixture
def adapter_yaml_file(tmp_path: Path, sample_adapter_dict: dict[str, Any]) -> Path:
    """Write a valid adapter YAML file and return its path."""
    spec_file = tmp_path / "test-adapter.yaml"
    spec_file.write_text(yaml.dump(sample_adapter_dict), encoding="utf-8")
    return spec_file


@pytest.fixture
def invalid_wrapper_yaml_file(tmp_path: Path) -> Path:
    """Write a wrapper YAML file missing required 'stages' field."""
    data = {
        "name": "bad-wrapper",
        "version": "1.0.0",
        "schema_version": 1,
        "description": "Missing stages field",
        "inputs": [],
        "outputs": [],
        # stages intentionally omitted
    }
    spec_file = tmp_path / "bad-wrapper.yaml"
    spec_file.write_text(yaml.dump(data), encoding="utf-8")
    return spec_file


@pytest.fixture
def invalid_policy_yaml_file(tmp_path: Path) -> Path:
    """Write a policy YAML file missing required 'checks' field."""
    data = {
        "name": "bad-policy",
        "version": "1.0.0",
        "schema_version": 1,
        "description": "Missing checks field",
        # checks intentionally omitted
    }
    spec_file = tmp_path / "bad-policy.yaml"
    spec_file.write_text(yaml.dump(data), encoding="utf-8")
    return spec_file


@pytest.fixture
def specs_dir(tmp_path: Path, sample_wrapper_dict: dict[str, Any], sample_policy_dict: dict[str, Any]) -> Path:
    """Build a minimal specs directory tree with one wrapper and one policy."""
    wrappers_dir = tmp_path / "wrappers"
    policies_dir = tmp_path / "policies"
    wrappers_dir.mkdir()
    policies_dir.mkdir()

    (wrappers_dir / "test-wrapper.yaml").write_text(
        yaml.dump(sample_wrapper_dict), encoding="utf-8"
    )
    (policies_dir / "test-policy.yaml").write_text(
        yaml.dump(sample_policy_dict), encoding="utf-8"
    )
    return tmp_path
