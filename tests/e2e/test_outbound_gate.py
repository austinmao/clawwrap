"""End-to-end test for the outbound gate.

Tests the full pipeline: submit → resolve → verify → dispatch → audit.
Uses dry_run for WhatsApp (no live wacli needed), live send for email.

Run:
    CLAWWRAP_E2E=1 pytest tests/e2e/test_outbound_gate.py -v -s

Pre-conditions:
  - RESEND_API_KEY_SENDING (or RESEND_API_KEY) in environment (for email)
  - AGENTMAIL_API_KEY in environment (for email verification)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from clawwrap.adapters.openclaw.handlers.outbound_submit import submit
from tests.e2e.conftest import skip_unless_e2e


def _setup_e2e_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create config with real Ceremonia targets for E2E testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    targets = {
        "targets": {
            "awaken-apr-2026": {
                "staff": {
                    "whatsapp": {
                        "target": "120363405933229321@g.us",
                        "verify": {"title": "Awaken Apr 2026 Staff"},
                    },
                    "email": {"target": "dangerousflower464@agentmail.to"},
                },
                "participant": {
                    "whatsapp": {
                        "target": "120363426287919417@g.us",
                        "verify": {"title": "Ceremonia Awaken Apr 2026"},
                    },
                },
            }
        },
        "audience_labels": {
            "awaken-apr-2026": {
                "staff": "Awaken Apr 2026 — staff only",
                "participant": "Awaken Apr 2026 — participant Full Circle Chat",
            }
        },
    }
    (config_dir / "targets.yaml").write_text(yaml.safe_dump(targets, default_flow_style=False))

    policy = {
        "version": "1",
        "default": "deny",
        "allowlists": {
            "shared": {
                "whatsapp": ["awaken-apr-2026.staff", "awaken-apr-2026.participant"],
                "email": ["awaken-apr-2026.staff"],
            },
        },
        "checks": [],
    }
    (config_dir / "outbound-policy.yaml").write_text(yaml.safe_dump(policy, default_flow_style=False))

    gateway_dir = tmp_path / "gateway"
    gateway_dir.mkdir()
    gateway_path = gateway_dir / "openclaw.json"
    gateway_path.write_text(json.dumps({
        "channels": {
            "whatsapp": {"enabled": True},
            "email": {"enabled": True},
        }
    }))

    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    return config_dir, gateway_path, log_dir


@skip_unless_e2e
class TestOutboundGateE2E:
    """Full pipeline E2E tests through the outbound gate."""

    def test_whatsapp_dry_run_resolves_and_verifies(self, tmp_path: Path) -> None:
        """Gate resolves WhatsApp group target and passes all checks in dry_run mode."""
        config_dir, gateway_path, log_dir = _setup_e2e_config(tmp_path)

        result = submit({
            "route_mode": "shared",
            "context_key": "awaken-apr-2026",
            "audience": "staff",
            "channel": "whatsapp",
            "message": "[gate-e2e] dry run test",
            "requested_by": "test-outbound-gate",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })

        print(f"\n[E2E] Gate verdict: allowed={result['allowed']}")
        print(f"[E2E] Target: {result['target']}")
        print(f"[E2E] Audience: {result['audience_label']}")
        for check in result.get("checks", []):
            print(f"[E2E]   {check['name']}: {'PASS' if check['passed'] else 'FAIL'} — {check['detail']}")

        assert result["allowed"] is True
        assert result["target"] == "120363405933229321@g.us"
        assert result["audience_label"] == "Awaken Apr 2026 — staff only"
        assert result["send_result"] is None  # dry_run

        # Verify audit log was written
        log_files = list(log_dir.glob("*.yaml"))
        assert len(log_files) == 1

    def test_email_live_send_through_gate(self, tmp_path: Path) -> None:
        """Gate sends a live email to AgentMail QA inbox and verifies."""
        config_dir, gateway_path, log_dir = _setup_e2e_config(tmp_path)

        test_id = f"gate-e2e-{int(time.time())}"
        message = f"[outbound-gate-e2e-{test_id}] Live email test. Ignore this message."

        print(f"\n[E2E] Sending email through gate — test_id={test_id}")

        result = submit({
            "route_mode": "shared",
            "context_key": "awaken-apr-2026",
            "audience": "staff",
            "channel": "email",
            "message": message,
            "requested_by": "test-outbound-gate",
            "dry_run": False,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })

        print(f"[E2E] Gate verdict: allowed={result['allowed']}")
        print(f"[E2E] Target: {result['target']}")
        if result.get("send_result"):
            print(f"[E2E] Send result: {result['send_result']}")

        assert result["allowed"] is True
        assert result["target"] == "dangerousflower464@agentmail.to"
        assert result["send_result"] is not None
        assert result["send_result"].get("sent_at") or result["send_result"].get("email_id")

        print(f"[E2E] PASS — email sent through gate to {result['target']}")

    def test_deny_for_unconfigured_target(self, tmp_path: Path) -> None:
        """Gate denies sends to unconfigured targets."""
        config_dir, gateway_path, log_dir = _setup_e2e_config(tmp_path)

        result = submit({
            "route_mode": "shared",
            "context_key": "heal-jun-2026",
            "audience": "staff",
            "channel": "whatsapp",
            "message": "should be denied",
            "requested_by": "test-outbound-gate",
            "dry_run": True,
            "config_dir": str(config_dir),
            "gateway_path": str(gateway_path),
            "log_dir": str(log_dir),
        })

        assert result["allowed"] is False
        assert result["denied_by"] == "target_exists"
        print(f"[E2E] Correctly denied: {result['reason']}")
