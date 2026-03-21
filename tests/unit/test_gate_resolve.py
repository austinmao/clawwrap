"""Unit tests for gate/resolve.py — target resolution."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clawwrap.gate.resolve import fill_empty_target, load_targets, resolve_shared


def _write_targets(tmp_path: Path, data: dict) -> Path:
    """Write a targets.yaml to tmp_path and return the dir."""
    targets_path = tmp_path / "targets.yaml"
    targets_path.write_text(yaml.safe_dump(data, default_flow_style=False))
    return tmp_path


class TestLoadTargets:
    def test_valid_yaml(self, tmp_path: Path) -> None:
        config_dir = _write_targets(tmp_path, {"targets": {}, "audience_labels": {}})
        data = load_targets(config_dir)
        assert "targets" in data

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_targets(tmp_path)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        (tmp_path / "targets.yaml").write_text("!!invalid: [")
        with pytest.raises(Exception):
            load_targets(tmp_path)

    def test_non_dict_raises(self, tmp_path: Path) -> None:
        (tmp_path / "targets.yaml").write_text("- just a list")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_targets(tmp_path)


class TestResolveShared:
    def _seed(self) -> dict:
        return {
            "targets": {
                "retreat-x": {
                    "staff": {
                        "whatsapp": {
                            "target": "group-jid@g.us",
                            "verify": {"title": "Staff Group"},
                        },
                        "email": {"target": "staff@example.com"},
                    },
                    "participant": {
                        "whatsapp": None,
                    },
                }
            },
            "audience_labels": {
                "retreat-x": {
                    "staff": "Staff label",
                    "participant": "Participant label",
                }
            },
        }

    def test_resolves_target_and_label(self) -> None:
        ctx = resolve_shared("retreat-x", "staff", "whatsapp", self._seed())
        assert ctx.target == "group-jid@g.us"
        assert ctx.audience_label == "Staff label"
        assert ctx.allowlist_key == "retreat-x.staff"

    def test_resolves_verify_metadata(self) -> None:
        ctx = resolve_shared("retreat-x", "staff", "whatsapp", self._seed())
        assert ctx.expected_identity == {"title": "Staff Group"}
        # verification_supported is False at resolve time — the submit handler
        # upgrades it to True only when a live identity checker is available.
        assert ctx.verification_supported is False

    def test_no_verify_metadata_for_email(self) -> None:
        ctx = resolve_shared("retreat-x", "staff", "email", self._seed())
        assert ctx.target == "staff@example.com"
        assert ctx.verification_supported is False

    def test_null_target_for_unconfigured(self) -> None:
        ctx = resolve_shared("retreat-x", "participant", "whatsapp", self._seed())
        assert ctx.target is None

    def test_null_target_for_missing_context(self) -> None:
        ctx = resolve_shared("nonexistent", "staff", "whatsapp", self._seed())
        assert ctx.target is None

    def test_null_target_for_missing_audience(self) -> None:
        ctx = resolve_shared("retreat-x", "kitchen", "whatsapp", self._seed())
        assert ctx.target is None

    def test_audience_label_empty_for_missing(self) -> None:
        ctx = resolve_shared("retreat-x", "kitchen", "whatsapp", self._seed())
        assert ctx.audience_label == ""

    def test_resolve_newsletter_mailchimp_target(self, tmp_path: Path) -> None:
        data = {
            "targets": {
                "newsletter": {
                    "full-list": {
                        "mailchimp": {
                            "target": "9b70ef06f1",
                            "verify": {"name": "Ceremonia"},
                        }
                    }
                }
            },
            "audience_labels": {
                "newsletter": {"full-list": "Ceremonia -- full newsletter subscriber list"}
            },
        }
        config_dir = _write_targets(tmp_path, data)
        targets_data = load_targets(config_dir)
        resolved = resolve_shared("newsletter", "full-list", "mailchimp", targets_data)
        assert resolved.target == "9b70ef06f1"
        assert resolved.audience_label == "Ceremonia -- full newsletter subscriber list"
        assert resolved.expected_identity == {"name": "Ceremonia"}
        assert resolved.allowlist_key == "newsletter.full-list"


class TestFillEmptyTarget:
    def test_fills_null_mapping(self, tmp_path: Path) -> None:
        _write_targets(tmp_path, {
            "targets": {"ctx": {"aud": {"ch": None}}},
            "audience_labels": {},
        })
        result = fill_empty_target("ctx", "aud", "ch", "new-target", {"title": "New"}, tmp_path)
        assert result is True
        reloaded = load_targets(tmp_path)
        assert reloaded["targets"]["ctx"]["aud"]["ch"]["target"] == "new-target"

    def test_raises_on_existing_mapping(self, tmp_path: Path) -> None:
        _write_targets(tmp_path, {
            "targets": {"ctx": {"aud": {"ch": {"target": "existing"}}}},
            "audience_labels": {},
        })
        with pytest.raises(ValueError, match="already configured"):
            fill_empty_target("ctx", "aud", "ch", "new-target", None, tmp_path)

    def test_creates_missing_path(self, tmp_path: Path) -> None:
        _write_targets(tmp_path, {"targets": {}, "audience_labels": {}})
        fill_empty_target("new-ctx", "new-aud", "whatsapp", "jid@g.us", None, tmp_path)
        reloaded = load_targets(tmp_path)
        assert reloaded["targets"]["new-ctx"]["new-aud"]["whatsapp"]["target"] == "jid@g.us"
