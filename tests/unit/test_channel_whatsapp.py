"""Unit tests for the WhatsApp gateway channel handler (spec 085 US3).

T017: 4 unit tests — success, auth fail, timeout, invalid params — with the
gateway transport mocked via ``subprocess.run``.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from clawwrap.gate import _gate_context
from clawwrap.handlers.contracts import whatsapp_gateway as wa
from clawwrap.handlers.contracts.errors import DispatchError

_TEST_TARGET = "+14155550101"
_TEST_MESSAGE = "ping from test (whatsapp)"


@pytest.fixture(autouse=True)
def _reset_gate_context():
    prev = getattr(_gate_context, "active", False)
    _gate_context.active = True  # tests run inside the gate by default
    yield
    _gate_context.active = prev


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = returncode
    result.stdout = stdout.encode("utf-8")
    result.stderr = stderr.encode("utf-8")
    return result


class TestWhatsAppGateway:
    def test_send_success(self) -> None:
        """T017-a: gateway returns JSON with id + toJid → spec'd result."""
        gateway_response = {
            "id": "WAMSG-2001",
            "toJid": "14155550101@s.whatsapp.net",
            "status": "sent",
        }
        with patch(
            "clawwrap.handlers.contracts.whatsapp_gateway.subprocess.run"
        ) as mock_run:
            mock_run.return_value = _proc(0, stdout=json.dumps(gateway_response))
            result = wa.send({
                "to": _TEST_TARGET,
                "message": _TEST_MESSAGE,
            })

        assert result == {
            "messageId": "WAMSG-2001",
            "channel": "whatsapp",
            "toJid": "14155550101@s.whatsapp.net",
            "status": "sent",
        }
        # Verify command shape — channel, to, message, idempotencyKey in params
        cmd = mock_run.call_args.args[0]
        assert "openclaw" in cmd
        assert "gateway" in cmd
        assert "call" in cmd
        # CLI args must reference send RPC
        assert "send" in cmd

    def test_send_auth_fail(self) -> None:
        """T017-b: non-zero return with unauthorized → DispatchError."""
        with patch(
            "clawwrap.handlers.contracts.whatsapp_gateway.subprocess.run"
        ) as mock_run:
            mock_run.return_value = _proc(
                1,
                stderr="unauthorized: gateway token mismatch",
            )
            with pytest.raises(DispatchError, match="unauthorized"):
                wa.send({"to": _TEST_TARGET, "message": _TEST_MESSAGE})

    def test_send_timeout(self) -> None:
        """T017-c: subprocess.TimeoutExpired after configured window → DispatchError."""
        with patch(
            "clawwrap.handlers.contracts.whatsapp_gateway.subprocess.run"
        ) as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["openclaw"], timeout=90
            )
            with pytest.raises(DispatchError, match="timed out"):
                wa.send({"to": _TEST_TARGET, "message": _TEST_MESSAGE})

    def test_send_invalid_params(self) -> None:
        """T017-d: missing `to` → DispatchError before subprocess is invoked."""
        with patch(
            "clawwrap.handlers.contracts.whatsapp_gateway.subprocess.run"
        ) as mock_run:
            with pytest.raises(DispatchError, match="'to' is required"):
                wa.send({"message": _TEST_MESSAGE})
            mock_run.assert_not_called()
