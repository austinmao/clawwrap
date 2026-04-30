"""Unit tests for outbound.submit handler — full pipeline integration."""
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
        # Spec 085 test fixtures — spec 085 BB/WA flows use rec-bb-1.
        if recipient_ref == "airtable:contacts/rec-bb-1" and channel in (
            "bluebubbles", "imessage",
        ):
            return "+14155550100", "Test BB contact (rec-bb-1)", "rec-bb-1"
        if recipient_ref == "airtable:contacts/rec-wa-1" and channel == "whatsapp":
            return "+14155550101", "Test WA contact (rec-wa-1)", "rec-wa-1"
        if recipient_ref != "airtable:contacts/rec123":
            raise ValueError("unexpected ref")
        if channel != "email":
            raise ValueError("unexpected channel")
        return "jane@example.com", "Jane Doe (airtable:contacts/rec123)", "rec123"


class _FakeAdapter:
    def __init__(
        self,
        verifier_result: dict[str, Any] | None = None,
        handler_results: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._verifier_result = verifier_result or {"matched": True, "detail": "identity verified"}
        self._handler_results = handler_results or {}

    def bind_handler(self, handler_id: str) -> Any:
        if handler_id == "group.identity_matches":
            return lambda inputs: self._verifier_result
        if handler_id in self._handler_results:
            result = self._handler_results[handler_id]
            return lambda inputs: result
        raise AssertionError(f"unexpected handler bind: {handler_id}")


def _setup_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create config dir, gateway config, and log dir for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # targets.yaml
    targets = {
        "targets": {
            "retreat-x": {
                "staff": {
                    "whatsapp": {
                        "target": "group-jid@g.us",
                        "verify": {"title": "Staff Group"},
                    },
                    "email": {"target": "staff@example.com"},
                },
                "participant": {"whatsapp": None},
            },
            "ceremonia": {
                "ops-onboarding": {
                    "slack": {
                        "target": "C0AHSENHJHG",
                        "verify": {"name": "ops-onboarding"},
                    },
                },
            },
        },
        "audience_labels": {
            "retreat-x": {
                "staff": "Retreat X — staff only",
                "participant": "Retreat X — participants",
            },
            "ceremonia": {
                "ops-onboarding": "Ceremonia — ops onboarding",
            },
        },
    }
    (config_dir / "targets.yaml").write_text(yaml.safe_dump(targets, default_flow_style=False))

    # outbound-policy.yaml
    policy = {
        "version": "1",
        "default": "deny",
        "allowlists": {
            "shared": {
                "whatsapp": ["retreat-x.staff"],
                "email": ["retreat-x.staff"],
                "slack": ["ceremonia.ops-onboarding"],
            },
            "direct": {"email": ["airtable:contacts/*"]},
        },
        "checks": [],
    }
    (config_dir / "outbound-policy.yaml").write_text(yaml.safe_dump(policy, default_flow_style=False))

    # gateway config
    gateway_dir = tmp_path / "gateway"
    gateway_dir.mkdir()
    gateway_path = gateway_dir / "openclaw.json"
    gateway_path.write_text(json.dumps({
        "channels": {
            "whatsapp": {"enabled": True},
            "email": {"enabled": True},
            "slack": {"enabled": True},
            "bluebubbles": {"enabled": True},
            "imessage": {"enabled": True},
        },
    }))

    # log dir
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    return config_dir, gateway_path, log_dir


@pytest.fixture(autouse=True)
def _patch_adapter_and_resolvers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: _FakeAdapter())
    monkeypatch.setattr(outbound_submit, "_build_resolver_registry", lambda: {"airtable": _StubResolver()})


class TestSubmitValidation:
    def test_missing_route_mode_denied(self, tmp_path: Path) -> None:
        result = submit({"channel": "whatsapp", "message": "hi", "requested_by": "test", "log_dir": str(tmp_path)})
        assert result["allowed"] is False
        assert "route_mode" in result["reason"]

    def test_shared_missing_context_key_denied(self, tmp_path: Path) -> None:
        result = submit({
            "route_mode": "shared", "audience": "staff", "channel": "whatsapp",
            "message": "hi", "requested_by": "test", "log_dir": str(tmp_path),
        })
        assert result["allowed"] is False
        assert "context_key" in result["reason"]

    def test_direct_missing_recipient_ref_denied(self, tmp_path: Path) -> None:
        result = submit({
            "route_mode": "direct", "channel": "email",
            "message": "hi", "requested_by": "test", "log_dir": str(tmp_path),
        })
        assert result["allowed"] is False
        assert "recipient_ref" in result["reason"]


class TestSubmitSharedDryRun:
    def test_default_config_dir_points_to_repo_config(self) -> None:
        assert outbound_submit._DEFAULT_CONFIG_DIR.name == "config"
        assert outbound_submit._DEFAULT_CONFIG_DIR.parent.name == "clawwrap"

    def test_dry_run_resolves_and_verifies(self, tmp_path: Path) -> None:
        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "whatsapp",
            "message": "Test message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert result["target"] == "group-jid@g.us"
        assert result["audience_label"] == "Retreat X — staff only"
        assert result["verification_supported"] is True
        live_check = next(check for check in result["checks"] if check["name"] == "live_identity_matches")
        assert live_check["passed"] is True
        assert result["send_result"] is None

    def test_dry_run_denied_for_unconfigured(self, tmp_path: Path) -> None:
        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "participant",
            "channel": "whatsapp",
            "message": "Test",
            "requested_by": "test",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is False
        assert result["denied_by"] == "target_exists"

    def test_denied_for_unlisted_audience(self, tmp_path: Path) -> None:
        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        # Add kitchen target but don't add to allowlist
        targets_data = yaml.safe_load((config_dir / "targets.yaml").read_text())
        targets_data["targets"]["retreat-x"]["kitchen"] = {"whatsapp": {"target": "kitchen@g.us"}}
        (config_dir / "targets.yaml").write_text(yaml.safe_dump(targets_data, default_flow_style=False))

        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "kitchen",
            "channel": "whatsapp",
            "message": "Test",
            "requested_by": "test",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is False
        assert result["denied_by"] == "target_in_gate_allowlist"

    def test_denied_when_live_group_identity_mismatches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            outbound_submit,
            "_build_adapter",
            lambda: _FakeAdapter({"matched": False, "detail": "expected Staff Group, got Wrong Group"}),
        )
        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "whatsapp",
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
        live_check = next(check for check in result["checks"] if check["name"] == "live_identity_matches")
        assert live_check["passed"] is False


class TestSubmitAudit:
    def test_audit_log_written(self, tmp_path: Path) -> None:
        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        submit({
            "route_mode": "shared",
            "context_key": "retreat-x",
            "audience": "staff",
            "channel": "whatsapp",
            "message": "Test",
            "requested_by": "test",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        log_files = list(log_dir.glob("*.yaml"))
        assert len(log_files) == 1
        entries = yaml.safe_load(log_files[0].read_text())
        assert entries[0]["allowed"] is True


class TestSubmitDirectDryRun:
    def test_direct_route_resolves_via_internal_registry(self, tmp_path: Path) -> None:
        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "direct",
            "recipient_ref": "airtable:contacts/rec123",
            "channel": "email",
            "message": "Test direct message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert result["target"] == "jane@example.com"
        assert result["audience_label"] == "Jane Doe (airtable:contacts/rec123)"
        assert result["send_result"] is None


class TestSubmitSlackDryRun:
    """Slack channel integration tests through the outbound.submit pipeline."""

    def test_slack_dry_run_resolves_correctly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter(handler_results={
            "slack.channel_info": {"matched": True, "detail": "channel name matches"},
        })
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "shared",
            "context_key": "ceremonia",
            "audience": "ops-onboarding",
            "channel": "slack",
            "message": "Test slack message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is True
        assert result["target"] == "C0AHSENHJHG"

    def test_slack_denied_for_unlisted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter(handler_results={
            "slack.channel_info": {"matched": True, "detail": "channel name verified"},
        })
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "shared",
            "context_key": "ceremonia",
            "audience": "unknown",
            "channel": "slack",
            "message": "Test slack message",
            "requested_by": "test-script",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        assert result["allowed"] is False
        assert result["denied_by"] == "target_exists"

    def test_slack_verify_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = _FakeAdapter(handler_results={
            "slack.channel_info": {"matched": True, "detail": "channel name verified"},
        })
        monkeypatch.setattr(outbound_submit, "_build_adapter", lambda: adapter)

        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "shared",
            "context_key": "ceremonia",
            "audience": "ops-onboarding",
            "channel": "slack",
            "message": "Test slack verify message",
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


class TestSpec085RateLimit:
    """T024-T026: rate-limit integration in outbound.submit (spec 085 US5)."""

    def test_rate_limit_blocks_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T024: guard raises RateLimitError → deny verdict, dispatch not called."""
        from clawwrap.engine.rate_limit import RateLimitError

        dispatch_spy = {"called": False}

        def _boom_dispatch(*args, **kwargs):
            dispatch_spy["called"] = True
            raise AssertionError("dispatch must not be called when rate-limited")

        class _ExhaustedGuard:
            def check_and_record(self, *, dry_run: bool = False):
                raise RateLimitError(
                    "daily limit of 20 test sends reached. Reset tomorrow."
                )

        monkeypatch.setattr(
            outbound_submit.RateLimitGuard,
            "for_channel",
            classmethod(lambda cls, channel, org_config: _ExhaustedGuard()),
        )
        monkeypatch.setattr(outbound_submit, "dispatch_to_channel", _boom_dispatch)

        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        # Add bluebubbles to policy allowlist for this test.
        policy = yaml.safe_load((config_dir / "outbound-policy.yaml").read_text())
        policy["allowlists"]["direct"]["bluebubbles"] = ["*"]
        (config_dir / "outbound-policy.yaml").write_text(yaml.safe_dump(policy))

        result = submit({
            "route_mode": "direct",
            "recipient_ref": "airtable:contacts/rec-bb-1",
            "channel": "bluebubbles",
            "message": "hi",
            "requested_by": "spec-085-test",
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })

        assert result["allowed"] is False
        assert result["denied_by"] == "rate_limit"
        assert "daily limit" in result["reason"]
        assert dispatch_spy["called"] is False

    def test_gate_context_toggled_around_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T025: _gate_context.active is True during dispatch and False afterwards.

        Also confirms audit log entry is written to the configured log_dir.
        """
        from clawwrap.engine.rate_limit import CheckResult
        from clawwrap.gate import _gate_context

        captured: dict[str, bool] = {}

        def _fake_dispatch(*args, **kwargs):
            captured["active_during_dispatch"] = getattr(_gate_context, "active", False)
            return {
                "messageId": "spy-1",
                "channel": kwargs.get("channel", "bluebubbles"),
                "status": "sent",
            }

        class _OkGuard:
            def check_and_record(self, *, dry_run: bool = False):
                return CheckResult(allowed=True, jitter_seconds=0.0, reason="ok")

        monkeypatch.setattr(
            outbound_submit.RateLimitGuard,
            "for_channel",
            classmethod(lambda cls, channel, org_config: _OkGuard()),
        )
        monkeypatch.setattr(outbound_submit, "dispatch_to_channel", _fake_dispatch)

        _gate_context.active = False  # baseline

        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        policy = yaml.safe_load((config_dir / "outbound-policy.yaml").read_text())
        policy["allowlists"]["direct"]["bluebubbles"] = ["*"]
        (config_dir / "outbound-policy.yaml").write_text(yaml.safe_dump(policy))

        result = submit({
            "route_mode": "direct",
            "recipient_ref": "airtable:contacts/rec-bb-1",
            "channel": "bluebubbles",
            "message": "hi",
            "requested_by": "spec-085-test",
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })

        assert result["allowed"] is True
        # Gate was active inside the dispatch callsite…
        assert captured["active_during_dispatch"] is True
        # …and reset afterwards (finally block ran).
        assert getattr(_gate_context, "active", True) is False
        # Audit log entry written.
        log_files = list(log_dir.glob("*.yaml"))
        assert log_files, "expected audit entry in log_dir"

    def test_email_channel_not_rate_limited(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T026: email (and slack/mailchimp) bypass the rate-limit guard entirely."""
        # If RateLimitGuard.for_channel gets called for email, we fail loudly.
        def _never_called(*args, **kwargs):
            raise AssertionError(
                "RateLimitGuard.for_channel must NOT be called for email"
            )

        monkeypatch.setattr(
            outbound_submit.RateLimitGuard, "for_channel", _never_called
        )

        config_dir, gateway_path, log_dir = _setup_config(tmp_path)
        result = submit({
            "route_mode": "direct",
            "recipient_ref": "airtable:contacts/rec123",
            "channel": "email",
            "message": "hi",
            "requested_by": "spec-085-test",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })
        # Email flow executes without touching the rate-limit guard.
        assert result["channel"] == "email"
