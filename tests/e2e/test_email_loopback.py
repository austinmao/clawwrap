"""End-to-end loopback test: send an email and verify receipt via AgentMail.

Target inbox: dangerousflower464@agentmail.to (active QA inbox)
Sender:       info@mail.ceremoniacircle.org (via Resend)

Handler chain:
  execute (email.send) -> audit (email.verify_receipt)

Run:
    CLAWWRAP_E2E=1 pytest tests/e2e/test_email_loopback.py -v -s

Pre-conditions:
  - RESEND_API_KEY_SENDING (or RESEND_API_KEY) in environment
  - AGENTMAIL_API_KEY in environment
  - Both keys valid (test with: curl -s -H "Authorization: Bearer $AGENTMAIL_API_KEY"
    https://api.agentmail.to/v0/inboxes/dangerousflower464@agentmail.to/messages)
"""
from __future__ import annotations

import time

from clawwrap.adapters.openclaw.adapter import OpenClawAdapter
from tests.e2e.conftest import skip_unless_e2e

_QA_INBOX = "dangerousflower464@agentmail.to"


@skip_unless_e2e
class TestEmailLoopback:
    """Send → verify loopback through Resend + AgentMail."""

    def setup_method(self) -> None:
        self.adapter = OpenClawAdapter()

    def test_dry_run_send_skips_api(self) -> None:
        """email.send dry_run=True completes without touching Resend API."""
        send = self.adapter.bind_handler("email.send")
        result = send({
            "to": _QA_INBOX,
            "subject": "[clawwrap-test] dry-run only",
            "body_text": "This is a dry-run test.",
            "dry_run": True,
        })
        assert result["dry_run"] is True
        assert result["email_id"] == ""
        assert _QA_INBOX in result["detail"]

    def test_dry_run_verify_skips_api(self) -> None:
        """email.verify_receipt dry_run=True returns mock success without polling."""
        verify = self.adapter.bind_handler("email.verify_receipt")
        result = verify({
            "inbox": _QA_INBOX,
            "subject_contains": "test",
            "dry_run": True,
        })
        assert result["verified"] is True

    def test_full_loopback_send_and_verify(self) -> None:
        """Full E2E: send one email via Resend and verify receipt in AgentMail inbox.

        This test performs a LIVE email send. It:
        1. Sends a test email via Resend to dangerousflower464@agentmail.to
        2. Polls AgentMail for the message (up to 40s, 4 attempts at 10s intervals)
        3. Reports round-trip latency
        """
        test_id = f"cw-email-{int(time.time())}"
        subject = f"[clawwrap-e2e-{test_id}] Email loopback test"
        body = f"Clawwrap E2E email loopback test. test_id={test_id}. Ignore this message."

        print(f"\n[E2E] Sending email to {_QA_INBOX} — test_id={test_id}")

        # Phase 1: Send
        send = self.adapter.bind_handler("email.send")
        send_start = time.time()
        send_result = send({
            "to": _QA_INBOX,
            "subject": subject,
            "body_text": body,
            "dry_run": False,
        })
        send_elapsed = time.time() - send_start

        assert send_result["sent_at"], f"Send failed: {send_result['detail']}"
        assert "error" not in send_result["detail"].lower() or send_result["email_id"], (
            f"Send returned error: {send_result['detail']}"
        )

        email_id = send_result["email_id"]
        sent_at = send_result["sent_at"]
        print(f"[E2E] Sent! email_id={email_id!r}  sent_at={sent_at}  elapsed={send_elapsed:.1f}s")

        # Phase 2: Verify receipt
        verify = self.adapter.bind_handler("email.verify_receipt")
        verify_result = verify({
            "inbox": _QA_INBOX,
            "subject_contains": test_id,  # unique per run
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
            f"Email not found in AgentMail after {verify_result['attempts']} attempts. "
            f"Detail: {verify_result['detail']}\n"
            f"Check manually: curl -s -H \"Authorization: Bearer $AGENTMAIL_API_KEY\" "
            f"\"https://api.agentmail.to/v0/inboxes/{_QA_INBOX}/messages\""
        )
        assert verify_result["round_trip_ms"] < 90_000, (
            f"Round trip too slow: {verify_result['round_trip_ms']}ms"
        )

        print(f"[E2E] PASS — round trip {verify_result['round_trip_ms']}ms")
