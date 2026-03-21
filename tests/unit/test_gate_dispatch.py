"""Unit tests for gate/dispatch.py — channel routing."""
from __future__ import annotations

from unittest.mock import MagicMock

from clawwrap.gate.dispatch import dispatch_to_channel


class TestDispatchToChannel:
    def test_dry_run_skips_send(self) -> None:
        result = dispatch_to_channel("jid@g.us", "whatsapp", "test", dry_run=True, bind_handler=MagicMock())
        assert result["detail"].startswith("dry_run")
        assert result["message_id"] == ""

    def test_whatsapp_group_calls_group_capable_handler(self) -> None:
        mock_handler = MagicMock(return_value={"message_id": "msg-1", "sent_at": "2026-01-01", "detail": "ok"})
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel("jid@g.us", "whatsapp", "Hello", dry_run=False, bind_handler=mock_bind)
        mock_bind.assert_called_with("dm.send_text")
        assert result["message_id"] == "msg-1"

    def test_whatsapp_direct_calls_gateway_handler(self) -> None:
        mock_handler = MagicMock(return_value={"message_id": "msg-1", "sent_at": "2026-01-01", "detail": "ok"})
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel("+13039992222", "whatsapp", "Hello", dry_run=False, bind_handler=mock_bind)
        mock_bind.assert_called_with("dm.send_via_gateway")
        assert result["message_id"] == "msg-1"

    def test_email_calls_email_handler(self) -> None:
        mock_handler = MagicMock(return_value={"message_id": "email-1", "sent_at": "2026-01-01", "detail": "ok"})
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel("user@example.com", "email", "Body text", dry_run=False, bind_handler=mock_bind)
        mock_bind.assert_called_with("email.send")
        assert result["message_id"] == "email-1"

    def test_imessage_returns_unimplemented(self) -> None:
        result = dispatch_to_channel("+1234", "imessage", "test", dry_run=False, bind_handler=MagicMock())
        assert "not yet implemented" in result["detail"]

    def test_sms_returns_unimplemented(self) -> None:
        result = dispatch_to_channel("+1234", "sms", "test", dry_run=False, bind_handler=MagicMock())
        assert "not yet implemented" in result["detail"]

    def test_mailchimp_dispatch_passes_payload_to_handler(self) -> None:
        payload = {
            "subject": "Sunday Service",
            "html": "<h1>Hello</h1>",
            "plain_text": "Hello",
            "from_name": "Ceremonia",
            "from_email": "info@mail.ceremoniacircle.org",
            "reply_to": "info@ceremoniacircle.org",
        }
        mock_handler = MagicMock(return_value={"message_id": "mc-1", "sent_at": "2026-03-15", "detail": "ok"})
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "9b70ef06f1", "mailchimp", "Sunday Service",
            dry_run=False, bind_handler=mock_bind, payload=payload,
        )
        mock_bind.assert_called_with("mailchimp.send_campaign")
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args[0][0]
        assert call_args["list_id"] == "9b70ef06f1"
        assert call_args["subject"] == "Sunday Service"
        assert call_args["html"] == "<h1>Hello</h1>"
        assert result["message_id"] == "mc-1"

    def test_mailchimp_without_payload_returns_error(self) -> None:
        mock_handler = MagicMock()
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "9b70ef06f1", "mailchimp", "Sunday Service",
            dry_run=False, bind_handler=mock_bind,
        )
        assert "requires a payload" in result["detail"]
        mock_handler.assert_not_called()

    def test_unknown_channel_returns_error(self) -> None:
        result = dispatch_to_channel("x", "fax", "test", dry_run=False, bind_handler=MagicMock())
        assert "unknown channel" in result["detail"]
