"""End-to-end loopback test: send a WhatsApp DM to Lumina's own number and verify receipt.

Target: +1 (303) 332-4741  ->  JID: 13033324741@s.whatsapp.net

Production path (dm.send_via_gateway):
  resolve (dm.resolve_jid) -> execute (dm.send_via_gateway) -> audit (dm.verify_receipt)

Secondary path (dm.send_text / wacli):
  Kept for wacli-specific integration testing. wacli is currently CONNECTED: false so
  this path will fail a live send. Use dry_run=True for structural tests only.

Run:
    CLAWWRAP_E2E=1 pytest tests/e2e/test_whatsapp_loopback.py -v -s

Pre-conditions (gateway path):
  - OpenClaw gateway is running: openclaw gateway status
  - Gateway has active WhatsApp session (+13033324741)
  - Rate limit lockfile allows a send (max 3/day; min 60s interval)

Pre-conditions (wacli path — dry-run only):
  - wacli installed at /opt/homebrew/bin/wacli
"""
from __future__ import annotations

import time

from clawwrap.adapters.openclaw.adapter import OpenClawAdapter
from tests.e2e.conftest import skip_unless_e2e

# Lumina's own WhatsApp number — the loopback target.
_LUMINA_JID = "13033324741@s.whatsapp.net"
_LUMINA_PHONE = "+1 (303) 332-4741"


@skip_unless_e2e
class TestWhatsAppLoopback:
    """Full handler-chain loopback: send to self, verify delivery (gateway path)."""

    def setup_method(self) -> None:
        self.adapter = OpenClawAdapter()

    def test_resolve_lumina_jid(self) -> None:
        """dm.resolve_jid normalises Lumina's number correctly."""
        resolve = self.adapter.bind_handler("dm.resolve_jid")
        result = resolve({"to_jid": _LUMINA_PHONE})
        assert result["valid"] is True, result["detail"]
        assert result["normalized_jid"] == _LUMINA_JID
        assert result["jid_type"] == "individual"

    def test_dry_run_gateway_send(self) -> None:
        """dm.send_via_gateway dry_run=True completes without touching openclaw CLI."""
        send = self.adapter.bind_handler("dm.send_via_gateway")
        result = send({
            "normalized_jid": _LUMINA_JID,
            "message": "[clawwrap-test] dry-run only",
            "dry_run": True,
        })
        assert result["dry_run"] is True
        assert result["rate_limit_applied"] is True
        assert result["channel"] == "whatsapp"

    def test_full_loopback_send_and_verify(self) -> None:
        """Full E2E: send one message via OpenClaw gateway and verify receipt.

        This test performs a LIVE WhatsApp send via the OpenClaw native channel.
        It:
        1. Enforces rate limits (10-15s jitter + lockfile check)
        2. Sends a single text message via openclaw message send --channel whatsapp
        3. Polls for receipt up to 30 seconds via wacli messages list
        4. Reports round-trip latency
        """
        test_id = f"cw-loopback-{int(time.time())}"
        message = f"[clawwrap-e2e] Loopback test {test_id}. Ignore this message."

        print(f"\n[E2E] Sending to {_LUMINA_JID} via gateway — test_id={test_id}")
        print("[E2E] Waiting for rate-limit jitter (10-15s)...")

        # Phase 1: Resolve
        resolve = self.adapter.bind_handler("dm.resolve_jid")
        resolve_result = resolve({"to_jid": _LUMINA_JID})
        assert resolve_result["valid"] is True, f"Resolve failed: {resolve_result['detail']}"
        jid = resolve_result["normalized_jid"]

        # Phase 2: Execute via OpenClaw gateway (rate guard fires here)
        send = self.adapter.bind_handler("dm.send_via_gateway")
        send_start = time.time()
        send_result = send({
            "normalized_jid": jid,
            "message": message,
            "dry_run": False,
        })
        send_elapsed = time.time() - send_start

        assert "rate limit" not in send_result["detail"].lower(), (
            f"Rate limit blocked send: {send_result['detail']}"
        )
        assert send_result["sent_at"], f"Send failed: {send_result['detail']}"
        assert send_result["channel"] == "whatsapp"

        message_id = send_result["message_id"]
        sent_at = send_result["sent_at"]
        print(f"[E2E] Sent! message_id={message_id!r}  sent_at={sent_at}  elapsed={send_elapsed:.1f}s")

        # Phase 3: Audit (verify receipt — polls up to 30s)
        verify = self.adapter.bind_handler("dm.verify_receipt")
        verify_result = verify({
            "normalized_jid": jid,
            "message_id": message_id,
            "sent_at": sent_at,
            "dry_run": False,
        })

        print(
            f"[E2E] Verify: verified={verify_result['verified']}  "
            f"round_trip_ms={verify_result['round_trip_ms']}  "
            f"attempts={verify_result['attempts']}  "
            f"detail={verify_result['detail']!r}"
        )

        assert verify_result["verified"] is True, (
            f"Message not found in wacli store after {verify_result['attempts']} attempts. "
            f"Detail: {verify_result['detail']}\n"
            "Check manually: wacli messages list --chat 13033324741@s.whatsapp.net --json"
        )
        assert verify_result["round_trip_ms"] < 60_000, (
            f"Round trip too slow: {verify_result['round_trip_ms']}ms"
        )

        print(f"[E2E] PASS — round trip {verify_result['round_trip_ms']}ms")


@skip_unless_e2e
class TestWacliPathDryRun:
    """Structural tests for the wacli (dm.send_text) path.

    wacli is currently CONNECTED: false — do not attempt live sends.
    These tests validate the handler contract without invoking wacli.
    """

    def setup_method(self) -> None:
        self.adapter = OpenClawAdapter()

    def test_dry_run_send_does_not_call_wacli(self) -> None:
        """dm.send_text dry_run=True completes without touching wacli."""
        send = self.adapter.bind_handler("dm.send_text")
        result = send({
            "normalized_jid": _LUMINA_JID,
            "message": "[clawwrap-test] dry-run only",
            "dry_run": True,
        })
        assert result["dry_run"] is True
        assert result["rate_limit_applied"] is True
        assert result["message_id"] == ""
