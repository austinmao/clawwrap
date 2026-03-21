"""Unit tests for the email.verify_receipt handler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from clawwrap.adapters.openclaw.handlers.email_verify_receipt import verify_email_receipt


class TestVerifyEmailReceiptValidation:
    def test_missing_inbox_returns_error(self) -> None:
        result = verify_email_receipt({"subject_contains": "test"})
        assert result["verified"] is False
        assert "inbox is required" in result["detail"]

    def test_missing_subject_contains_returns_error(self) -> None:
        result = verify_email_receipt({"inbox": "qa@agentmail.to"})
        assert result["verified"] is False
        assert "subject_contains is required" in result["detail"]

    def test_missing_api_key_returns_error(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = verify_email_receipt({
                "inbox": "qa@agentmail.to",
                "subject_contains": "test",
            })
        assert result["verified"] is False
        assert "AGENTMAIL_API_KEY" in result["detail"]


class TestVerifyEmailReceiptDryRun:
    def test_dry_run_skips_api(self) -> None:
        with patch("httpx.get") as mock_get:
            result = verify_email_receipt({
                "inbox": "qa@agentmail.to",
                "subject_contains": "test",
                "dry_run": True,
            })
        mock_get.assert_not_called()
        assert result["verified"] is True
        assert result["message_id"] == "dry-run-msg-id"


class TestVerifyEmailReceiptSuccess:
    def _mock_messages(self, messages: list[dict]) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"messages": messages}
        return resp

    def test_finds_matching_subject(self) -> None:
        msg = {
            "message_id": "<msg-001>",
            "subject": "[clawwrap-e2e-abc123] loopback test",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", {"AGENTMAIL_API_KEY": "am_key"}),
            patch("httpx.get", return_value=self._mock_messages([msg])),
        ):
            result = verify_email_receipt({
                "inbox": "qa@agentmail.to",
                "subject_contains": "clawwrap-e2e-abc123",
                "sent_at": "2025-12-31T23:59:00Z",
            })
        assert result["verified"] is True
        assert result["message_id"] == "<msg-001>"
        assert result["attempts"] == 1

    def test_subject_match_is_case_insensitive(self) -> None:
        msg = {
            "message_id": "<msg-002>",
            "subject": "[CLAWWRAP-E2E] Test",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", {"AGENTMAIL_API_KEY": "am_key"}),
            patch("httpx.get", return_value=self._mock_messages([msg])),
        ):
            result = verify_email_receipt({
                "inbox": "qa@agentmail.to",
                "subject_contains": "clawwrap-e2e",
                "sent_at": "2025-12-31T23:59:00Z",
            })
        assert result["verified"] is True

    def test_returns_not_found_after_max_attempts(self) -> None:
        with (
            patch.dict("os.environ", {"AGENTMAIL_API_KEY": "am_key"}),
            patch("httpx.get", return_value=self._mock_messages([])),
            patch("clawwrap.adapters.openclaw.handlers.email_verify_receipt.time") as mock_time,
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            result = verify_email_receipt({
                "inbox": "qa@agentmail.to",
                "subject_contains": "no-such-subject",
            })
        assert result["verified"] is False
        assert result["attempts"] == 4

    def test_api_error_continues_retrying(self) -> None:
        """A transient 500 error should not abort — it continues polling."""
        error_resp = MagicMock()
        error_resp.status_code = 500
        good_msg = {
            "message_id": "<found>",
            "subject": "[test] found",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        good_resp = self._mock_messages([good_msg])
        side_effects = [error_resp, good_resp]

        with (
            patch.dict("os.environ", {"AGENTMAIL_API_KEY": "am_key"}),
            patch("httpx.get", side_effect=side_effects),
            patch("clawwrap.adapters.openclaw.handlers.email_verify_receipt.time") as mock_time,
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            result = verify_email_receipt({
                "inbox": "qa@agentmail.to",
                "subject_contains": "[test] found",
                "sent_at": "2025-12-31T00:00:00Z",
            })
        assert result["verified"] is True
        assert result["attempts"] == 2
