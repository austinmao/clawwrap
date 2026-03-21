"""Unit tests for Slack dispatch — channel routing via slack.post handler."""
from __future__ import annotations

from unittest.mock import MagicMock

from clawwrap.gate.dispatch import dispatch_to_channel


class TestSlackDispatch:
    def test_dry_run_skips_send(self) -> None:
        result = dispatch_to_channel(
            "C0123456789", "slack", "hello", dry_run=True, bind_handler=MagicMock()
        )
        assert result["detail"].startswith("dry_run")
        assert result["message_id"] == ""

    def test_slack_calls_slack_post_handler(self) -> None:
        mock_handler = MagicMock(
            return_value={"message_id": "1234.5678", "sent_at": "2026-03-15T00:00:00Z", "detail": "ok"}
        )
        mock_bind = MagicMock(return_value=mock_handler)
        result = dispatch_to_channel(
            "C0123456789", "slack", "Hello team", dry_run=False, bind_handler=mock_bind
        )
        mock_bind.assert_called_with("slack.post")
        mock_handler.assert_called_once_with({
            "channel_id": "C0123456789",
            "text": "Hello team",
            "dry_run": False,
        })
        assert result["message_id"] == "1234.5678"

    def test_unknown_channel_returns_error(self) -> None:
        result = dispatch_to_channel(
            "x", "carrier_pigeon", "test", dry_run=False, bind_handler=MagicMock()
        )
        assert "unknown channel" in result["detail"]
        assert result["message_id"] == ""
