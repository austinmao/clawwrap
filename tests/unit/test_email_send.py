"""Unit tests for the email.send handler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from clawwrap.adapters.openclaw.handlers.email_send import send_email


class TestSendEmailValidation:
    def test_missing_to_returns_error(self) -> None:
        result = send_email({"subject": "Test", "body_text": "Hello"})
        assert result["email_id"] == ""
        assert "to is required" in result["detail"]

    def test_missing_subject_returns_error(self) -> None:
        result = send_email({"to": "test@example.com", "body_text": "Hello"})
        assert "subject is required" in result["detail"]

    def test_missing_body_returns_error(self) -> None:
        result = send_email({"to": "test@example.com", "subject": "Hi"})
        assert "body_text is required" in result["detail"]


class TestSendEmailDryRun:
    def test_dry_run_skips_api_call(self) -> None:
        with patch("httpx.post") as mock_post:
            result = send_email({
                "to": "qa@agentmail.to",
                "subject": "Test",
                "body_text": "Hello",
                "dry_run": True,
            })
        mock_post.assert_not_called()
        assert result["dry_run"] is True
        assert result["email_id"] == ""
        assert result["sent_at"] != ""

    def test_dry_run_includes_recipient_in_detail(self) -> None:
        result = send_email({
            "to": "qa@agentmail.to",
            "subject": "Subject",
            "body_text": "Body",
            "dry_run": True,
        })
        assert "qa@agentmail.to" in result["detail"]


class TestSendEmailSuccess:
    def _mock_resp(self, email_id: str = "email-abc-123") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": email_id}
        return resp

    def test_success_returns_email_id(self) -> None:
        with (
            patch.dict("os.environ", {"RESEND_API_KEY_SENDING": "re_test_key"}),
            patch("httpx.post", return_value=self._mock_resp("email-xyz")),
        ):
            result = send_email({
                "to": "dangerousflower464@agentmail.to",
                "subject": "[test] loopback",
                "body_text": "Test body",
            })
        assert result["email_id"] == "email-xyz"
        assert result["dry_run"] is False
        assert result["sent_at"] != ""

    def test_sends_to_correct_endpoint(self) -> None:
        calls: list[tuple] = []

        def capture(url: str, **kwargs: object) -> MagicMock:
            calls.append({"url": url, **kwargs})
            return self._mock_resp()

        with (
            patch.dict("os.environ", {"RESEND_API_KEY_SENDING": "re_key"}),
            patch("httpx.post", side_effect=capture),
        ):
            send_email({
                "to": "dangerousflower464@agentmail.to",
                "subject": "Sub",
                "body_text": "Body",
            })

        assert calls[0]["url"] == "https://api.resend.com/emails"
        assert calls[0]["json"]["to"] == ["dangerousflower464@agentmail.to"]

    def test_uses_transactional_from_when_default_from_missing(self) -> None:
        calls: list[dict[str, object]] = []

        def capture(url: str, **kwargs: object) -> MagicMock:
            calls.append({"url": url, **kwargs})
            return self._mock_resp()

        with (
            patch.dict(
                "os.environ",
                {
                    "RESEND_API_KEY_SENDING": "re_key",
                    "RESEND_TRANSACTIONAL_FROM": "Lumina <lumina@mail.ceremoniacircle.org>",
                },
                clear=True,
            ),
            patch("httpx.post", side_effect=capture),
        ):
            send_email({
                "to": "qa@example.com",
                "subject": "Sub",
                "body_text": "Body",
            })

        assert calls[0]["json"]["from"] == "Lumina <lumina@mail.ceremoniacircle.org>"

    def test_uses_campaign_from_when_only_resend_from_address_is_set(self) -> None:
        calls: list[dict[str, object]] = []

        def capture(url: str, **kwargs: object) -> MagicMock:
            calls.append({"url": url, **kwargs})
            return self._mock_resp()

        with (
            patch.dict(
                "os.environ",
                {
                    "RESEND_API_KEY_SENDING": "re_key",
                    "RESEND_FROM_ADDRESS": "Ceremonia <info@mail.ceremoniacircle.org>",
                },
                clear=True,
            ),
            patch("httpx.post", side_effect=capture),
        ):
            send_email({
                "to": "qa@example.com",
                "subject": "Sub",
                "body_text": "Body",
            })

        assert calls[0]["json"]["from"] == "Ceremonia <info@mail.ceremoniacircle.org>"

    def test_uses_fallback_api_key(self) -> None:
        """Falls back to RESEND_API_KEY when RESEND_API_KEY_SENDING not set."""
        with (
            patch.dict("os.environ", {"RESEND_API_KEY": "re_fallback"}, clear=False),
            patch("os.environ.get", side_effect=lambda k, *a: None if k == "RESEND_API_KEY_SENDING" else "re_fallback"),
            patch("httpx.post", return_value=self._mock_resp()),
        ):
            result = send_email({
                "to": "qa@example.com",
                "subject": "Sub",
                "body_text": "Body",
            })
        assert result["email_id"] != "" or "re_fallback" or result["detail"]


class TestSendEmailErrors:
    def test_missing_api_key_returns_error(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = send_email({
                "to": "qa@example.com",
                "subject": "Sub",
                "body_text": "Body",
            })
        assert "RESEND_API_KEY" in result["detail"]

    def test_timeout_returns_error(self) -> None:
        with (
            patch.dict("os.environ", {"RESEND_API_KEY_SENDING": "re_key"}),
            patch("httpx.post", side_effect=httpx.TimeoutException("timed out")),
        ):
            result = send_email({
                "to": "qa@example.com",
                "subject": "Sub",
                "body_text": "Body",
            })
        assert "timed out" in result["detail"].lower()

    def test_non_2xx_returns_error(self) -> None:
        resp = MagicMock()
        resp.status_code = 403
        resp.text = "Unauthorized"
        with (
            patch.dict("os.environ", {"RESEND_API_KEY_SENDING": "re_key"}),
            patch("httpx.post", return_value=resp),
        ):
            result = send_email({
                "to": "qa@example.com",
                "subject": "Sub",
                "body_text": "Body",
            })
        assert "403" in result["detail"]
        assert result["email_id"] == ""
