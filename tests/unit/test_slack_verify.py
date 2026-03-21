"""Unit tests for Slack channel-name verification in outbound.submit pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from clawwrap.adapters.openclaw.handlers import outbound_submit
from clawwrap.adapters.openclaw.handlers.outbound_submit import submit


class _StubResolver:
    def resolve(self, recipient_ref: str, channel: str) -> tuple[str, str, str]:
        raise ValueError("unexpected ref")


class _FakeAdapter:
    """Fake adapter that returns configurable results for handler bindings."""

    def __init__(self, handler_results: dict[str, dict[str, Any]] | None = None) -> None:
        self._handler_results = handler_results or {}

    def bind_handler(self, handler_id: str) -> Any:
        if handler_id in self._handler_results:
            result = self._handler_results[handler_id]
            return lambda inputs: result
        raise AssertionError(f"unexpected handler bind: {handler_id}")


def _setup_config(
    tmp_path: Path,
    *,
    slack_verify: dict[str, Any] | None = None,
    slack_target: str = "C0123456789",
) -> tuple[Path, Path, Path]:
    """Create config dir with Slack target and optional verify metadata."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    slack_entry: dict[str, Any] = {"target": slack_target}
    if slack_verify is not None:
        slack_entry["verify"] = slack_verify

    targets = {
        "targets": {
            "retreat-x": {
                "staff": {
                    "slack": slack_entry,
                },
            }
        },
        "audience_labels": {
            "retreat-x": {
                "staff": "Retreat X — staff only",
            }
        },
    }
    (config_dir / "targets.yaml").write_text(yaml.safe_dump(targets, default_flow_style=False))

    policy = {
        "version": "1",
        "default": "deny",
        "allowlists": {
            "shared": {"slack": ["retreat-x.staff"]},
            "direct": {},
        },
        "checks": [],
    }
    (config_dir / "outbound-policy.yaml").write_text(yaml.safe_dump(policy, default_flow_style=False))

    gateway_dir = tmp_path / "gateway"
    gateway_dir.mkdir()
    gateway_path = gateway_dir / "openclaw.json"
    gateway_path.write_text(json.dumps({"channels": {"slack": {"enabled": True}}}))

    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    return config_dir, gateway_path, log_dir


@pytest.fixture(autouse=True)
def _patch_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound_submit, "_build_resolver_registry", lambda: {"airtable": _StubResolver()})


class TestSlackVerifyMatch:
    """Slack channel with verify.name triggers channel_info check and matches."""

    def test_matched_sets_verification_supported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter(handler_results={
            "slack.channel_info": {"matched": True, "detail": "matched channel name 'staff-chat'"},
        })
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(
            tmp_path, slack_verify={"name": "staff-chat"}
        )
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "slack",
            "message": "Test message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert result["verification_supported"] is True
        live_check = next(c for c in result["checks"] if c["name"] == "live_identity_matches")
        assert live_check["passed"] is True


class TestSlackVerifyMismatch:
    """Slack channel with verify.name where channel_info returns matched=False."""

    def test_mismatch_denies(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter(handler_results={
            "slack.channel_info": {"matched": False, "detail": "expected 'staff-chat', got 'random'"},
        })
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(
            tmp_path, slack_verify={"name": "staff-chat"}
        )
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "slack",
            "message": "Test message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is False
        assert result["denied_by"] == "live_identity_matches"
        assert result["verification_supported"] is True
        live_check = next(c for c in result["checks"] if c["name"] == "live_identity_matches")
        assert live_check["passed"] is False


class TestSlackNoVerifyMetadata:
    """Slack channel without verify metadata skips live identity check."""

    def test_no_verify_skips_identity_check(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Adapter should not need to handle any identity handler.
        adapter = _FakeAdapter(handler_results={})
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(tmp_path, slack_verify=None)
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "slack",
            "message": "Test message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert result["verification_supported"] is False
        live_check = next(c for c in result["checks"] if c["name"] == "live_identity_matches")
        assert live_check["passed"] is True  # skipped = passes
