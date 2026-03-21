"""Unit tests for the dm.send_via_gateway handler.

Tests cover:
- JID-to-E.164 conversion (module-level helper)
- Handler error paths (missing inputs, bad JID, CLI not found, non-zero exit)
- Dry-run path (passes --dry-run flag; rate guard still records)
- Output contract shape on success
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clawwrap.adapters.openclaw.handlers.dm_send_gateway import (
    _jid_to_e164,
    send_via_gateway,
)

# ---------------------------------------------------------------------------
# _jid_to_e164
# ---------------------------------------------------------------------------

class TestJidToE164:
    def test_converts_jid(self) -> None:
        assert _jid_to_e164("13033324741@s.whatsapp.net") == "+13033324741"

    def test_passthrough_e164(self) -> None:
        assert _jid_to_e164("+13033324741") == "+13033324741"

    def test_strips_whitespace(self) -> None:
        assert _jid_to_e164("  +13033324741  ") == "+13033324741"

    def test_invalid_jid_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot convert"):
            _jid_to_e164("not-a-jid")

    def test_group_jid_raises(self) -> None:
        with pytest.raises(ValueError):
            _jid_to_e164("120363423692271199@g.us")


# ---------------------------------------------------------------------------
# send_via_gateway — error paths
# ---------------------------------------------------------------------------

class TestSendViaGatewayErrors:
    def test_missing_jid_returns_error(self) -> None:
        result = send_via_gateway({"message": "hello"})
        assert result["message_id"] == ""
        assert "normalized_jid is required" in result["detail"]

    def test_missing_message_returns_error(self) -> None:
        result = send_via_gateway({"normalized_jid": "13033324741@s.whatsapp.net"})
        assert result["message_id"] == ""
        assert "message is required" in result["detail"]

    def test_bad_jid_returns_error(self) -> None:
        result = send_via_gateway({
            "normalized_jid": "bad-jid",
            "message": "hello",
        })
        assert "JID conversion failed" in result["detail"]

    def test_cli_not_found_returns_error(self, tmp_path: Path) -> None:
        from clawwrap.engine.rate_limit import RateLimitGuard
        guard = RateLimitGuard(lockfile=tmp_path / "lock.json")
        with (
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway._guard", guard),
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway.time") as mock_time,
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            result = send_via_gateway({
                "normalized_jid": "13033324741@s.whatsapp.net",
                "message": "hello",
                "dry_run": True,
            })
        assert "openclaw CLI not found" in result["detail"]

    def test_nonzero_exit_returns_error(self, tmp_path: Path) -> None:
        from clawwrap.engine.rate_limit import RateLimitGuard

        guard = RateLimitGuard(lockfile=tmp_path / "lock.json")
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = b"something"
        proc.stderr = b"gateway error: not connected"

        with (
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway._guard", guard),
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway.time") as mock_time,
            patch("subprocess.run", return_value=proc),
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            result = send_via_gateway({
                "normalized_jid": "13033324741@s.whatsapp.net",
                "message": "hello",
                "dry_run": True,
            })
        assert "openclaw exit 1" in result["detail"]
        assert result["message_id"] == ""


# ---------------------------------------------------------------------------
# send_via_gateway — success path
# ---------------------------------------------------------------------------

class TestSendViaGatewaySuccess:
    def _make_proc(self, message_id: str = "msg-abc-123") -> MagicMock:
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = json.dumps({"id": message_id}).encode()
        proc.stderr = b""
        return proc

    def test_success_returns_correct_fields(self, tmp_path: Path) -> None:
        from clawwrap.engine.rate_limit import RateLimitGuard

        guard = RateLimitGuard(lockfile=tmp_path / "lock.json")
        proc = self._make_proc("msg-xyz")

        with (
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway._guard", guard),
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway.time") as mock_time,
            patch("subprocess.run", return_value=proc),
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            result = send_via_gateway({
                "normalized_jid": "13033324741@s.whatsapp.net",
                "message": "Hello Lumina",
                "dry_run": False,
            })

        assert result["message_id"] == "msg-xyz"
        assert result["channel"] == "whatsapp"
        assert result["dry_run"] is False
        assert result["rate_limit_applied"] is True
        assert result["sent_at"] != ""

    def test_dry_run_passes_flag_to_cli(self, tmp_path: Path) -> None:
        from clawwrap.engine.rate_limit import RateLimitGuard

        guard = RateLimitGuard(lockfile=tmp_path / "lock.json")
        proc = self._make_proc()
        calls: list[list[str]] = []

        def capture_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            calls.append(cmd)
            return proc

        with (
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway._guard", guard),
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway.time") as mock_time,
            patch("subprocess.run", side_effect=capture_run),
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            send_via_gateway({
                "normalized_jid": "13033324741@s.whatsapp.net",
                "message": "dry run msg",
                "dry_run": True,
            })

        assert "--dry-run" in calls[0]

    def test_no_dry_run_flag_when_false(self, tmp_path: Path) -> None:
        from clawwrap.engine.rate_limit import RateLimitGuard

        guard = RateLimitGuard(lockfile=tmp_path / "lock.json")
        proc = self._make_proc()
        calls: list[list[str]] = []

        def capture_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            calls.append(cmd)
            return proc

        with (
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway._guard", guard),
            patch("clawwrap.adapters.openclaw.handlers.dm_send_gateway.time") as mock_time,
            patch("subprocess.run", side_effect=capture_run),
        ):
            mock_time.sleep = lambda _: None
            mock_time.time = __import__("time").time
            send_via_gateway({
                "normalized_jid": "13033324741@s.whatsapp.net",
                "message": "live msg",
                "dry_run": False,
            })

        assert "--dry-run" not in calls[0]
        assert "--channel" in calls[0]
        assert "whatsapp" in calls[0]
        assert "+13033324741" in calls[0]
