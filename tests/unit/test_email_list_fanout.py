"""Unit tests for email list fan-out — list targets in targets.yaml."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from clawwrap.adapters.openclaw.handlers import outbound_submit
from clawwrap.adapters.openclaw.handlers.outbound_submit import submit
from clawwrap.gate.resolve import load_targets, resolve_shared


class _StubResolver:
    def resolve(self, recipient_ref: str, channel: str) -> tuple[str, str, str]:
        raise ValueError("unexpected ref")


class _FakeAdapter:
    """Fake adapter that captures dispatch calls."""

    def __init__(self) -> None:
        self._call_count = 0

    def bind_handler(self, handler_id: str) -> Any:
        if handler_id == "email.send":
            def _send(inputs: dict[str, Any]) -> dict[str, Any]:
                self._call_count += 1
                return {
                    "email_id": f"email-{self._call_count}",
                    "sent_at": "2026-03-15T00:00:00Z",
                    "dry_run": False,
                    "detail": f"sent to {inputs['to']}",
                }
            return _send
        raise AssertionError(f"unexpected handler bind: {handler_id}")


def _setup_config(
    tmp_path: Path,
    *,
    email_target: str | list[str] = "staff@example.com",
) -> tuple[Path, Path, Path]:
    """Create config dir with email target (single or list)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    targets = {
        "targets": {
            "retreat-x": {
                "staff": {
                    "email": {"target": email_target},
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
            "shared": {"email": ["retreat-x.staff"]},
            "direct": {},
        },
        "checks": [],
    }
    (config_dir / "outbound-policy.yaml").write_text(yaml.safe_dump(policy, default_flow_style=False))

    gateway_dir = tmp_path / "gateway"
    gateway_dir.mkdir()
    gateway_path = gateway_dir / "openclaw.json"
    gateway_path.write_text(json.dumps({"channels": {"email": {"enabled": True}}}))

    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    return config_dir, gateway_path, log_dir


@pytest.fixture(autouse=True)
def _patch_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound_submit, "_build_resolver_registry", lambda: {"airtable": _StubResolver()})


class TestListTargetResolution:
    """List target in targets.yaml resolves correctly."""

    def test_resolve_shared_returns_list_target(self, tmp_path: Path) -> None:
        config_dir, _, _ = _setup_config(
            tmp_path,
            email_target=["alice@example.com", "bob@example.com"],
        )
        targets_data = load_targets(config_dir)
        resolved = resolve_shared("retreat-x", "staff", "email", targets_data)
        assert resolved.target == ["alice@example.com", "bob@example.com"]
        assert resolved.audience_label == "Retreat X — staff only"

    def test_resolve_shared_returns_single_string_target(self, tmp_path: Path) -> None:
        config_dir, _, _ = _setup_config(tmp_path, email_target="staff@example.com")
        targets_data = load_targets(config_dir)
        resolved = resolve_shared("retreat-x", "staff", "email", targets_data)
        assert resolved.target == "staff@example.com"
        assert isinstance(resolved.target, str)


class TestListTargetDispatch:
    """Dispatch iterates over list targets and sends to each."""

    def test_dispatch_sends_to_each_address(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter()
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(
            tmp_path,
            email_target=["alice@example.com", "bob@example.com", "carol@example.com"],
        )
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "email",
            "message": "Team update",
            "requested_by": "test-script",
            "dry_run": False,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert isinstance(result["send_result"], list)
        assert len(result["send_result"]) == 3
        assert result["send_result"][0]["email_id"] == "email-1"
        assert result["send_result"][1]["email_id"] == "email-2"
        assert result["send_result"][2]["email_id"] == "email-3"
        assert result["target"] == ["alice@example.com", "bob@example.com", "carol@example.com"]


class TestListTargetDryRun:
    """Dry run with list target returns allowed=True, send_result=None."""

    def test_dry_run_with_list_target(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter()
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(
            tmp_path,
            email_target=["alice@example.com", "bob@example.com"],
        )
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "email",
            "message": "Team update",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert result["send_result"] is None
        assert result["target"] == ["alice@example.com", "bob@example.com"]
