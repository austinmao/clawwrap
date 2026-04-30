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
        """After spec 085, WA DMs route to the new whatsapp.send_gateway handler."""
        mock_handler = MagicMock(return_value={
            "messageId": "msg-1",
            "channel": "whatsapp",
            "toJid": "13039992222@s.whatsapp.net",
            "status": "sent",
        })
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "+13039992222", "whatsapp", "Hello", dry_run=False, bind_handler=mock_bind
        )
        mock_bind.assert_called_with("whatsapp.send_gateway")
        assert result["messageId"] == "msg-1"

    def test_email_calls_email_handler(self) -> None:
        mock_handler = MagicMock(return_value={"message_id": "email-1", "sent_at": "2026-01-01", "detail": "ok"})
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel("user@example.com", "email", "Body text", dry_run=False, bind_handler=mock_bind)
        mock_bind.assert_called_with("email.send")
        assert result["message_id"] == "email-1"

    def test_imessage_routes_to_bluebubbles(self) -> None:
        """After spec 085, imessage is an alias for bluebubbles.send."""
        mock_handler = MagicMock(return_value={
            "messageId": "bb-1",
            "channel": "bluebubbles",
            "status": "sent",
        })
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "+14155550100", "imessage", "test", dry_run=False, bind_handler=mock_bind
        )
        mock_bind.assert_called_with("bluebubbles.send")
        assert result["messageId"] == "bb-1"

    def test_sms_routes_to_sms_relay_send(self) -> None:
        """Spec 087 T033: sms channel now resolved; unimplemented set shrinks to {telegram}."""
        mock_handler = MagicMock(return_value={"message_id": "sms-1", "sent_at": "2026-04-20", "detail": "ok"})
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "+14155550199", "sms", "test", dry_run=False, bind_handler=mock_bind
        )
        mock_bind.assert_called_with("sms_relay.send")
        assert result["message_id"] == "sms-1"

    def test_telegram_still_unimplemented(self) -> None:
        result = dispatch_to_channel("+1234", "telegram", "test", dry_run=False, bind_handler=MagicMock())
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


class TestSpec085Routing:
    """T020+T021 — spec 085 channel routing + existing-channel regression."""

    def test_dispatch_bluebubbles(self) -> None:
        """T020-a: channel 'bluebubbles' → handler_id 'bluebubbles.send'."""
        mock_handler = MagicMock(return_value={
            "messageId": "bb-9", "channel": "bluebubbles", "status": "sent",
        })
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "+14155550100", "bluebubbles", "hello",
            dry_run=False, bind_handler=mock_bind,
        )
        mock_bind.assert_called_with("bluebubbles.send")
        assert result["messageId"] == "bb-9"

    def test_dispatch_imessage_alias(self) -> None:
        """T020-b: channel 'imessage' → handler_id 'bluebubbles.send' (alias)."""
        mock_handler = MagicMock(return_value={
            "messageId": "bb-10", "channel": "bluebubbles", "status": "sent",
        })
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "+14155550100", "imessage", "hello",
            dry_run=False, bind_handler=mock_bind,
        )
        mock_bind.assert_called_with("bluebubbles.send")
        assert result["messageId"] == "bb-10"

    def test_dispatch_whatsapp_gateway(self) -> None:
        """T020-c: WA DM (non-group) → new 'whatsapp.send_gateway' handler."""
        mock_handler = MagicMock(return_value={
            "messageId": "wa-1", "channel": "whatsapp",
            "toJid": "14155550100@s.whatsapp.net", "status": "sent",
        })
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "+14155550100", "whatsapp", "hello",
            dry_run=False, bind_handler=mock_bind,
        )
        mock_bind.assert_called_with("whatsapp.send_gateway")
        assert result["messageId"] == "wa-1"

    def test_existing_channel_handler_ids_unchanged(self) -> None:
        """T021: regression — email/slack/mailchimp/lumina-relay/resend-broadcast
        handler IDs are unchanged after the spec 085 dispatch patch."""
        from clawwrap.gate.dispatch import _CHANNEL_HANDLERS
        expected = {
            "email": "email.send",
            "slack": "slack.post",
            "mailchimp": "mailchimp.send_campaign",
            "lumina-relay": "relay.send",
            "resend-broadcast": "resend.send_broadcast",
        }
        for channel, handler_id in expected.items():
            assert _CHANNEL_HANDLERS.get(channel) == handler_id, (
                f"existing channel {channel!r} handler_id changed — regression"
            )


class TestDispatchRelay:
    """Tests for the lumina-relay channel dispatch handler (_dispatch_relay)."""

    def test_relay_returns_error_when_hub_endpoint_missing(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        monkeypatch.delenv("LUMINA_RELAY_HUB_ENDPOINT", raising=False)
        monkeypatch.setenv("LUMINA_RELAY_OUTBOUND_SECRET", "secret")
        payload = {"tenant_id": "cer", "message_id": "msg-1", "sequence": 1}
        result = dispatch_to_channel("+15551234567", "lumina-relay", "Hi", dry_run=False, bind_handler=MagicMock(), payload=payload)
        assert "missing" in result["detail"].lower()
        assert result["message_id"] == ""

    def test_relay_returns_error_when_outbound_secret_missing(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        monkeypatch.setenv("LUMINA_RELAY_HUB_ENDPOINT", "https://hub.example.com")
        monkeypatch.delenv("LUMINA_RELAY_OUTBOUND_SECRET", raising=False)
        payload = {"tenant_id": "cer", "message_id": "msg-1", "sequence": 1}
        result = dispatch_to_channel("+15551234567", "lumina-relay", "Hi", dry_run=False, bind_handler=MagicMock(), payload=payload)
        assert "missing" in result["detail"].lower()

    def test_relay_posts_correct_payload_and_headers(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        import urllib.request
        monkeypatch.setenv("LUMINA_RELAY_HUB_ENDPOINT", "https://hub.example.com")
        monkeypatch.setenv("LUMINA_RELAY_OUTBOUND_SECRET", "test-secret-123")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen = MagicMock(return_value=mock_response)
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        payload = {"tenant_id": "ceremonia", "message_id": "msg-abc", "sequence": 2}
        result = dispatch_to_channel(
            "+15551234567", "lumina-relay", "Hello from agent",
            dry_run=False, bind_handler=MagicMock(), payload=payload,
        )

        assert result["message_id"] == "msg-abc"
        assert "delivered" in result["detail"]

        # Verify the urllib.request.Request was constructed correctly
        req_obj = mock_urlopen.call_args[0][0]
        assert req_obj.full_url == "https://hub.example.com/lumina-relay/outbound"
        assert req_obj.get_header("Authorization") == "Bearer test-secret-123"
        assert req_obj.get_header("Content-type") == "application/json"
        assert req_obj.method == "POST"

        import json
        body = json.loads(req_obj.data.decode("utf-8"))
        assert body["tenant_id"] == "ceremonia"
        assert body["message_id"] == "msg-abc"
        assert body["recipient_phone"] == "+15551234567"
        assert body["reply"] == "Hello from agent"
        assert body["sequence"] == 2

    def test_relay_handles_http_error(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        import urllib.request
        import urllib.error
        monkeypatch.setenv("LUMINA_RELAY_HUB_ENDPOINT", "https://hub.example.com")
        monkeypatch.setenv("LUMINA_RELAY_OUTBOUND_SECRET", "secret")
        mock_urlopen = MagicMock(side_effect=urllib.error.HTTPError(
            "https://hub.example.com/lumina-relay/outbound", 500, "Server Error", {}, None
        ))
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        payload = {"tenant_id": "cer", "message_id": "msg-1", "sequence": 1}
        result = dispatch_to_channel("+15551234567", "lumina-relay", "Hi", dry_run=False, bind_handler=MagicMock(), payload=payload)
        assert "failed" in result["detail"].lower()
        assert "500" in result["detail"]

    def test_relay_handles_network_error(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        import urllib.request
        monkeypatch.setenv("LUMINA_RELAY_HUB_ENDPOINT", "https://hub.example.com")
        monkeypatch.setenv("LUMINA_RELAY_OUTBOUND_SECRET", "secret")
        mock_urlopen = MagicMock(side_effect=ConnectionError("ECONNREFUSED"))
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        payload = {"tenant_id": "cer", "message_id": "msg-1", "sequence": 1}
        result = dispatch_to_channel("+15551234567", "lumina-relay", "Hi", dry_run=False, bind_handler=MagicMock(), payload=payload)
        assert "error" in result["detail"].lower() or "ECONNREFUSED" in result["detail"]

    def test_relay_dry_run_skips_actual_send(self) -> None:
        result = dispatch_to_channel("+15551234567", "lumina-relay", "Hi", dry_run=True, bind_handler=MagicMock())
        assert result["detail"].startswith("dry_run")
