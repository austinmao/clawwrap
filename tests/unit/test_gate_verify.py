"""Unit tests for gate/verify.py — policy check evaluator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from clawwrap.engine.gate import ResolvedContext
from clawwrap.gate.verify import (
    check_gate_allowlist,
    evaluate_checks,
    get_enabled_channels,
    load_gateway_config,
    load_policy,
)


def _write_policy(tmp_path: Path, data: dict) -> Path:
    (tmp_path / "outbound-policy.yaml").write_text(yaml.safe_dump(data, default_flow_style=False))
    return tmp_path


def _write_gateway(tmp_path: Path, data: dict) -> Path:
    cfg_path = tmp_path / "openclaw.json"
    cfg_path.write_text(json.dumps(data))
    return cfg_path


class TestLoadPolicy:
    def test_valid_yaml(self, tmp_path: Path) -> None:
        config_dir = _write_policy(tmp_path, {"version": "1", "checks": []})
        data = load_policy(config_dir)
        assert data["version"] == "1"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_policy(tmp_path)

    def test_non_dict_raises(self, tmp_path: Path) -> None:
        (tmp_path / "outbound-policy.yaml").write_text("- list")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_policy(tmp_path)


class TestLoadGatewayConfig:
    def test_valid_json(self, tmp_path: Path) -> None:
        cfg_path = _write_gateway(tmp_path, {"channels": {"whatsapp": {"enabled": True}}})
        data = load_gateway_config(cfg_path)
        assert "channels" in data

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        data = load_gateway_config(tmp_path / "nonexistent.json")
        assert data == {}


class TestGetEnabledChannels:
    def test_extracts_enabled(self) -> None:
        cfg = {"channels": {"whatsapp": {"enabled": True}, "telegram": {"enabled": False}}}
        assert get_enabled_channels(cfg) == {"whatsapp"}

    def test_default_enabled(self) -> None:
        cfg = {"channels": {"email": {}}}
        assert "email" in get_enabled_channels(cfg)


class TestCheckGateAllowlist:
    def _policy(self) -> dict:
        return {
            "allowlists": {
                "shared": {"whatsapp": ["retreat-x.staff", "retreat-x.participant"]},
                "direct": {"email": ["airtable:contacts/*"]},
            }
        }

    def test_shared_allowed(self) -> None:
        assert check_gate_allowlist("retreat-x.staff", "shared", "whatsapp", self._policy()) is True

    def test_shared_denied(self) -> None:
        assert check_gate_allowlist("retreat-x.kitchen", "shared", "whatsapp", self._policy()) is False

    def test_direct_glob_allowed(self) -> None:
        assert check_gate_allowlist("airtable:contacts/rec123", "direct", "email", self._policy()) is True

    def test_direct_glob_denied(self) -> None:
        assert check_gate_allowlist("unknown:ref/1", "direct", "email", self._policy()) is False


class TestEvaluateChecks:
    def _valid_resolved(self) -> ResolvedContext:
        return ResolvedContext(
            target="group-jid@g.us",
            audience_label="Staff label",
            expected_identity=None,
            allowlist_key="retreat-x.staff",
            verification_supported=False,
        )

    def _policy(self) -> dict:
        return {
            "allowlists": {"shared": {"whatsapp": ["retreat-x.staff"]}},
            "checks": [],
        }

    def _gateway(self) -> dict:
        return {"channels": {"whatsapp": {"enabled": True}}}

    def test_all_pass_for_valid_context(self) -> None:
        results = evaluate_checks(self._valid_resolved(), "shared", "whatsapp", self._policy(), self._gateway())
        assert all(r.passed for r in results), [r for r in results if not r.passed]

    def test_target_exists_fails_for_null(self) -> None:
        resolved = ResolvedContext(
            target=None, audience_label="label", expected_identity=None,
            allowlist_key="x.y", verification_supported=False,
        )
        results = evaluate_checks(resolved, "shared", "whatsapp", self._policy(), self._gateway())
        target_check = next(r for r in results if r.name == "target_exists")
        assert target_check.passed is False

    def test_allowlist_fails_for_unlisted(self) -> None:
        resolved = ResolvedContext(
            target="some-jid", audience_label="label", expected_identity=None,
            allowlist_key="retreat-x.kitchen", verification_supported=False,
        )
        results = evaluate_checks(resolved, "shared", "whatsapp", self._policy(), self._gateway())
        al_check = next(r for r in results if r.name == "target_in_gate_allowlist")
        assert al_check.passed is False

    def test_channel_disabled_fails(self) -> None:
        gateway = {"channels": {"whatsapp": {"enabled": False}}}
        results = evaluate_checks(self._valid_resolved(), "shared", "whatsapp", self._policy(), gateway)
        ch_check = next(r for r in results if r.name == "channel_enabled")
        assert ch_check.passed is False

    def test_live_identity_skipped_when_not_supported(self) -> None:
        results = evaluate_checks(self._valid_resolved(), "shared", "whatsapp", self._policy(), self._gateway())
        live_check = next(r for r in results if r.name == "live_identity_matches")
        assert live_check.passed is True
        assert "skipped" in live_check.detail

    def test_live_identity_passes_when_matched(self) -> None:
        resolved = ResolvedContext(
            target="jid@g.us", audience_label="label", expected_identity={"title": "Staff"},
            allowlist_key="retreat-x.staff", verification_supported=True,
            live_identity_match=True, live_identity={"title": "Staff"},
        )
        results = evaluate_checks(resolved, "shared", "whatsapp", self._policy(), self._gateway())
        live_check = next(r for r in results if r.name == "live_identity_matches")
        assert live_check.passed is True

    def test_live_identity_fails_when_mismatched(self) -> None:
        resolved = ResolvedContext(
            target="jid@g.us", audience_label="label", expected_identity={"title": "Staff"},
            allowlist_key="retreat-x.staff", verification_supported=True,
            live_identity_match=False, live_identity={"title": "Wrong Name"},
        )
        results = evaluate_checks(resolved, "shared", "whatsapp", self._policy(), self._gateway())
        live_check = next(r for r in results if r.name == "live_identity_matches")
        assert live_check.passed is False

    def test_live_identity_fails_when_unavailable(self) -> None:
        resolved = ResolvedContext(
            target="jid@g.us", audience_label="label", expected_identity={"title": "Staff"},
            allowlist_key="retreat-x.staff", verification_supported=True,
            live_identity_match=None,
        )
        results = evaluate_checks(resolved, "shared", "whatsapp", self._policy(), self._gateway())
        live_check = next(r for r in results if r.name == "live_identity_matches")
        assert live_check.passed is False
