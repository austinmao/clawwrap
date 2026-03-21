"""T062: Unit tests for clawwrap.engine.validation.

Covers:
- Valid wrapper spec passes validation
- Invalid wrapper spec (missing required field) fails
- Valid policy spec passes
- Invalid policy spec fails
- Spec type detection (wrapper/policy/adapter)
- Version compatibility checks
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from clawwrap.engine.compatibility import check_compatibility
from clawwrap.engine.validation import (
    UNKNOWN_SPEC_TYPE,
    _detect_spec_type,
    validate_spec,
)

# ---------------------------------------------------------------------------
# validate_spec — wrapper
# ---------------------------------------------------------------------------


class TestValidateSpecWrapper:
    """Tests for wrapper YAML validation."""

    def test_valid_wrapper_spec_passes(self, wrapper_yaml_file: Path) -> None:
        """Valid wrapper YAML must produce a valid ValidationResult with a Wrapper model."""
        result = validate_spec(wrapper_yaml_file)
        assert result.valid is True
        assert result.spec_type == "wrapper"
        assert result.model is not None
        assert not result.errors

    def test_invalid_wrapper_spec_missing_stages_fails(self, invalid_wrapper_yaml_file: Path) -> None:
        """Wrapper YAML without required 'stages' field must fail schema validation."""
        result = validate_spec(invalid_wrapper_yaml_file)
        assert result.valid is False
        assert result.model is None
        assert len(result.errors) > 0

    def test_invalid_wrapper_spec_contains_error_message(self, invalid_wrapper_yaml_file: Path) -> None:
        """Validation errors must include a descriptive message."""
        result = validate_spec(invalid_wrapper_yaml_file)
        # The combined error text should mention 'stages'
        combined = " ".join(result.errors)
        assert "stages" in combined.lower()

    def test_wrapper_spec_missing_name_fails(self, tmp_path: Path, sample_wrapper_dict: dict[str, Any]) -> None:
        """Wrapper YAML without 'name' must fail schema validation."""
        data = dict(sample_wrapper_dict)
        del data["name"]
        spec_file = tmp_path / "no-name.yaml"
        spec_file.write_text(yaml.dump(data), encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False

    def test_wrapper_spec_invalid_version_pattern_fails(
        self, tmp_path: Path, sample_wrapper_dict: dict[str, Any]
    ) -> None:
        """Wrapper YAML with non-semver version string must fail."""
        data = dict(sample_wrapper_dict)
        data["version"] = "not-a-version"
        spec_file = tmp_path / "bad-version.yaml"
        spec_file.write_text(yaml.dump(data), encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False

    def test_wrapper_spec_invalid_name_pattern_fails(
        self, tmp_path: Path, sample_wrapper_dict: dict[str, Any]
    ) -> None:
        """Wrapper YAML with uppercase name must fail."""
        data = dict(sample_wrapper_dict)
        data["name"] = "BadName"
        spec_file = tmp_path / "bad-name.yaml"
        spec_file.write_text(yaml.dump(data), encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False

    def test_wrapper_spec_empty_stages_fails(
        self, tmp_path: Path, sample_wrapper_dict: dict[str, Any]
    ) -> None:
        """Wrapper YAML with empty stages array must fail (minItems=1)."""
        data = dict(sample_wrapper_dict)
        data["stages"] = []
        spec_file = tmp_path / "empty-stages.yaml"
        spec_file.write_text(yaml.dump(data), encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False


# ---------------------------------------------------------------------------
# validate_spec — policy
# ---------------------------------------------------------------------------


class TestValidateSpecPolicy:
    """Tests for policy YAML validation."""

    def test_valid_policy_spec_passes(self, policy_yaml_file: Path) -> None:
        """Valid policy YAML must produce a valid ValidationResult."""
        result = validate_spec(policy_yaml_file)
        assert result.valid is True
        assert result.spec_type == "policy"
        assert result.model is not None
        assert not result.errors

    def test_invalid_policy_spec_missing_checks_fails(self, invalid_policy_yaml_file: Path) -> None:
        """Policy YAML without 'checks' field must fail schema validation."""
        result = validate_spec(invalid_policy_yaml_file)
        assert result.valid is False
        assert result.model is None

    def test_policy_spec_invalid_handler_id_pattern_fails(
        self, tmp_path: Path, sample_policy_dict: dict[str, Any]
    ) -> None:
        r"""Policy check handler_id must match pattern ^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$."""
        data = dict(sample_policy_dict)
        data["checks"] = [
            {
                "handler_id": "BadHandler",
                "phase": "resolve",
                "params": {},
                "fail_action": "block",
            }
        ]
        spec_file = tmp_path / "bad-handler.yaml"
        spec_file.write_text(yaml.dump(data), encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False

    def test_policy_spec_invalid_fail_action_fails(
        self, tmp_path: Path, sample_policy_dict: dict[str, Any]
    ) -> None:
        """Policy check with unknown fail_action value must fail."""
        data = dict(sample_policy_dict)
        data["checks"] = [
            {
                "handler_id": "target.some_handler",
                "phase": "resolve",
                "params": {},
                "fail_action": "explode",
            }
        ]
        spec_file = tmp_path / "bad-fail-action.yaml"
        spec_file.write_text(yaml.dump(data), encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False


# ---------------------------------------------------------------------------
# validate_spec — adapter
# ---------------------------------------------------------------------------


class TestValidateSpecAdapter:
    """Tests for adapter YAML validation."""

    def test_valid_adapter_spec_passes(self, adapter_yaml_file: Path) -> None:
        """Valid adapter YAML must produce a valid ValidationResult."""
        result = validate_spec(adapter_yaml_file)
        assert result.valid is True
        assert result.spec_type == "adapter"
        assert result.model is not None
        assert not result.errors


# ---------------------------------------------------------------------------
# validate_spec — edge cases
# ---------------------------------------------------------------------------


class TestValidateSpecEdgeCases:
    """Edge case tests for validate_spec."""

    def test_nonexistent_file_returns_invalid(self, tmp_path: Path) -> None:
        """Missing file must return invalid with a descriptive error."""
        result = validate_spec(tmp_path / "ghost.yaml")
        assert result.valid is False
        assert any("not found" in e.lower() or "File not found" in e for e in result.errors)

    def test_invalid_yaml_syntax_returns_invalid(self, tmp_path: Path) -> None:
        """Malformed YAML must return invalid with a parse error."""
        spec_file = tmp_path / "bad.yaml"
        spec_file.write_text("name: [unclosed bracket", encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False
        assert any("yaml" in e.lower() for e in result.errors)

    def test_non_mapping_yaml_returns_invalid(self, tmp_path: Path) -> None:
        """YAML that is a list (not a mapping) must return invalid."""
        spec_file = tmp_path / "list.yaml"
        spec_file.write_text("- item1\n- item2\n", encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False

    def test_unknown_spec_type_returns_invalid(self, tmp_path: Path) -> None:
        """YAML with no recognisable structure must return unknown spec type."""
        spec_file = tmp_path / "unknown.yaml"
        spec_file.write_text("foo: bar\nbaz: 42\n", encoding="utf-8")

        result = validate_spec(spec_file)
        assert result.valid is False
        assert result.spec_type == UNKNOWN_SPEC_TYPE


# ---------------------------------------------------------------------------
# Spec type detection
# ---------------------------------------------------------------------------


class TestDetectSpecType:
    """Tests for _detect_spec_type heuristics."""

    def test_detects_wrapper_by_stages(self) -> None:
        """Dict with 'stages' key must be detected as wrapper."""
        data: dict[str, Any] = {"stages": [], "name": "x"}
        assert _detect_spec_type(data) == "wrapper"

    def test_detects_wrapper_by_inputs(self) -> None:
        """Dict with 'inputs' key must be detected as wrapper."""
        data: dict[str, Any] = {"inputs": [], "name": "x"}
        assert _detect_spec_type(data) == "wrapper"

    def test_detects_wrapper_by_outputs(self) -> None:
        """Dict with 'outputs' key must be detected as wrapper."""
        data: dict[str, Any] = {"outputs": [], "name": "x"}
        assert _detect_spec_type(data) == "wrapper"

    def test_detects_policy_by_checks(self) -> None:
        """Dict with 'checks' key (no adapter keys) must be detected as policy."""
        data: dict[str, Any] = {"checks": [], "name": "x"}
        assert _detect_spec_type(data) == "policy"

    def test_detects_adapter_by_supported_handlers_and_approval_identity(self) -> None:
        """Dict with both 'supported_handlers' and 'approval_identity' must be detected as adapter."""
        data: dict[str, Any] = {
            "supported_handlers": [],
            "approval_identity": {},
            "name": "x",
        }
        assert _detect_spec_type(data) == "adapter"

    def test_unknown_for_empty_dict(self) -> None:
        """Empty dict must be detected as unknown."""
        assert _detect_spec_type({}) == UNKNOWN_SPEC_TYPE

    def test_unknown_for_unrecognised_keys(self) -> None:
        """Dict with none of the distinguishing keys must return unknown."""
        data: dict[str, Any] = {"foo": 1, "bar": 2}
        assert _detect_spec_type(data) == UNKNOWN_SPEC_TYPE


# ---------------------------------------------------------------------------
# Version compatibility checks
# ---------------------------------------------------------------------------


class TestVersionCompatibility:
    """Tests for check_compatibility."""

    def test_identical_versions_are_compatible(self) -> None:
        """Same semver string on both sides must be compatible."""
        result = check_compatibility("1.0.0", "1.0.0", schema_version=1)
        assert result.compatible is True

    def test_patch_difference_is_compatible(self) -> None:
        """PATCH version difference must remain compatible."""
        result = check_compatibility("1.0.0", "1.0.3", schema_version=1)
        assert result.compatible is True
        assert not result.warnings

    def test_minor_difference_is_compatible_with_warning(self) -> None:
        """MINOR version difference must be compatible but include a warning."""
        result = check_compatibility("1.0.0", "1.2.0", schema_version=1)
        assert result.compatible is True
        assert len(result.warnings) > 0

    def test_major_difference_is_incompatible(self) -> None:
        """MAJOR version difference must be incompatible."""
        result = check_compatibility("1.0.0", "2.0.0", schema_version=1)
        assert result.compatible is False
        assert "major" in result.reason.lower()

    def test_schema_version_mismatch_is_incompatible(self) -> None:
        """Differing schema_version integers must be incompatible."""
        result = check_compatibility("1.0.0", "1.0.0", schema_version=1, other_schema_version=2)
        assert result.compatible is False
        assert "schema" in result.reason.lower()

    def test_schema_version_match_is_compatible(self) -> None:
        """Same schema_version integer must be compatible."""
        result = check_compatibility("1.0.0", "1.0.0", schema_version=1, other_schema_version=1)
        assert result.compatible is True

    def test_invalid_semver_spec_is_incompatible(self) -> None:
        """Invalid semver string must produce an incompatible result."""
        result = check_compatibility("not-a-version", "1.0.0", schema_version=1)
        assert result.compatible is False

    def test_invalid_semver_target_is_incompatible(self) -> None:
        """Invalid target version string must produce an incompatible result."""
        result = check_compatibility("1.0.0", "1.0", schema_version=1)
        assert result.compatible is False
