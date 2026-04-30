"""Unit tests for the BlueBubbles REST channel handler (spec 085 US2).

T012: transport-path tests — success, 4xx, timeout, malformed response.
T013: escape-hatch tests — direct-call denied, emergency bypass logs WARN,
      via-gate calls succeed.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from clawwrap.engine.rate_limit import EscapeHatchError
from clawwrap.gate import _gate_context
from clawwrap.handlers.contracts import bluebubbles as bb
from clawwrap.handlers.contracts.errors import DispatchError

_VALID_CONFIG = {
    "serverUrl": "http://localhost:1234",
    "password": "test-password",
}

_TEST_TARGET = "+14155550100"  # reserved test E.164
_TEST_MESSAGE = "ping from test"


@pytest.fixture(autouse=True)
def _reset_gate_context():
    """Each test starts with the gate context inactive; restore on exit."""
    prev = getattr(_gate_context, "active", False)
    _gate_context.active = False
    yield
    _gate_context.active = prev


@pytest.fixture
def _via_gate():
    """Flip _gate_context.active=True so escape-hatch guard is bypassed."""
    _gate_context.active = True
    yield
    _gate_context.active = False


def _response(status_code: int, json_body=None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    if json_body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = json_body
    return resp


# ---------------------------------------------------------------------------
# T012: transport-path tests
# ---------------------------------------------------------------------------


class TestBluebubblesTransport:
    def test_send_success(self, _via_gate) -> None:
        """T012-a: 200 + well-formed body returns spec'd result dict."""
        bb_payload = {
            "status": 200,
            "message": "Success",
            "data": {"guid": "ABCD-1234"},
        }
        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            mock_post.return_value = _response(200, json_body=bb_payload)
            result = bb.send({
                "target": _TEST_TARGET,
                "message": _TEST_MESSAGE,
                "config": _VALID_CONFIG,
            })

        assert result == {
            "messageId": "ABCD-1234",
            "channel": "bluebubbles",
            "status": "sent",
        }
        # Called with correct URL + chat_guid shape
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chatGuid"] == f"iMessage;-;{_TEST_TARGET}"
        assert call_kwargs["json"]["method"] == "apple-script"
        assert call_kwargs["params"]["password"] == "test-password"

    def test_send_4xx(self, _via_gate) -> None:
        """T012-b: BB returns 4xx → DispatchError."""
        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            mock_post.return_value = _response(403, text="forbidden")
            with pytest.raises(DispatchError, match="HTTP 403"):
                bb.send({
                    "target": _TEST_TARGET,
                    "message": _TEST_MESSAGE,
                    "config": _VALID_CONFIG,
                })

    def test_send_timeout(self, _via_gate) -> None:
        """T012-c: requests.Timeout → DispatchError."""
        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            mock_post.side_effect = requests.Timeout("simulated timeout")
            with pytest.raises(DispatchError, match="timed out"):
                bb.send({
                    "target": _TEST_TARGET,
                    "message": _TEST_MESSAGE,
                    "config": _VALID_CONFIG,
                })

    def test_send_malformed_response(self, _via_gate) -> None:
        """T012-d: non-dict / empty body → DispatchError."""
        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            # Case 1: empty dict
            mock_post.return_value = _response(200, json_body={})
            with pytest.raises(DispatchError, match="malformed"):
                bb.send({
                    "target": _TEST_TARGET,
                    "message": _TEST_MESSAGE,
                    "config": _VALID_CONFIG,
                })

            # Case 2: list instead of dict
            mock_post.return_value = _response(200, json_body=[1, 2, 3])
            with pytest.raises(DispatchError, match="malformed"):
                bb.send({
                    "target": _TEST_TARGET,
                    "message": _TEST_MESSAGE,
                    "config": _VALID_CONFIG,
                })


# ---------------------------------------------------------------------------
# T013: escape-hatch tests
# ---------------------------------------------------------------------------


class TestBluebubblesEscapeHatch:
    def test_direct_call_no_env_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """T013-a: active=False + CLAWWRAP_EMERGENCY unset → EscapeHatchError."""
        monkeypatch.delenv("CLAWWRAP_EMERGENCY", raising=False)
        _gate_context.active = False

        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            with pytest.raises(EscapeHatchError, match="outbound.submit"):
                bb.send({
                    "target": _TEST_TARGET,
                    "message": _TEST_MESSAGE,
                    "config": _VALID_CONFIG,
                })
            # HTTP must NEVER fire on escape-hatch denial
            mock_post.assert_not_called()

    def test_direct_call_emergency_env_warns(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """T013-b: active=False + CLAWWRAP_EMERGENCY=1 → WARN logged, send proceeds."""
        monkeypatch.setenv("CLAWWRAP_EMERGENCY", "1")
        monkeypatch.chdir(tmp_path)  # logs written under tmp_path/memory/logs/outbound
        _gate_context.active = False

        bb_payload = {"status": 200, "data": {"guid": "EMRG-9999"}}
        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            mock_post.return_value = _response(200, json_body=bb_payload)
            result = bb.send({
                "target": _TEST_TARGET,
                "message": _TEST_MESSAGE,
                "config": _VALID_CONFIG,
            })

        assert result["messageId"] == "EMRG-9999"
        # WARN line appended to today's emergency log
        log_files = list((tmp_path / "memory" / "logs" / "outbound").glob("emergency-*.log"))
        assert len(log_files) == 1, f"expected 1 emergency log, found {log_files}"
        contents = log_files[0].read_text()
        assert "[WARN]" in contents
        assert "CLAWWRAP_EMERGENCY override" in contents
        # Target must be redacted (not full phone number)
        assert _TEST_TARGET not in contents
        assert "***" in contents

    def test_via_gate_no_error(self, _via_gate) -> None:
        """T013-c: active=True → no escape-hatch error, send proceeds normally."""
        bb_payload = {"status": 200, "data": {"guid": "GATE-0001"}}
        with patch("clawwrap.handlers.contracts.bluebubbles.requests.post") as mock_post:
            mock_post.return_value = _response(200, json_body=bb_payload)
            result = bb.send({
                "target": _TEST_TARGET,
                "message": _TEST_MESSAGE,
                "config": _VALID_CONFIG,
            })

        assert result["messageId"] == "GATE-0001"
        mock_post.assert_called_once()
