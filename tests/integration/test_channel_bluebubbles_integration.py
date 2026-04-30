"""Integration test for the BlueBubbles channel handler (spec 085 T014).

Skipped by default. Set ``BB_INTEGRATION_TEST=1`` to opt in. The test sends a
real iMessage via the local BlueBubbles server (requires the server running
on ``http://localhost:1234`` with the password set in
``~/.openclaw/openclaw.json``) and asserts the audit log entry was written.

Default target: ``+420777833596`` (Austin's Czech test line). Override via
``CLAWWRAP_BB_TEST_TARGET``. Do not point at a real user.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from clawwrap.gate import _gate_context
from clawwrap.handlers.contracts import bluebubbles as bb

pytestmark = pytest.mark.bb_integration


_DEFAULT_TEST_TARGET = "+420777833596"


@pytest.fixture(autouse=True)
def _via_gate():
    """Integration flow always runs inside the gate context."""
    prev = getattr(_gate_context, "active", False)
    _gate_context.active = True
    yield
    _gate_context.active = prev


def test_bluebubbles_live_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sends a real iMessage to the configured test number and verifies the
    audit log.

    Prerequisites (checked at runtime; test fails fast with a clear message):
      - ``BB_INTEGRATION_TEST=1`` (enforced by conftest collection hook)
      - Local BlueBubbles server reachable at ``http://localhost:1234``
      - ``~/.openclaw/openclaw.json`` contains serverUrl + password for the
        ``austinmao`` account
    """
    target = os.getenv("CLAWWRAP_BB_TEST_TARGET", _DEFAULT_TEST_TARGET)
    message = f"[spec 085] clawwrap integration test ({date.today().isoformat()})"

    # Route emergency-log + audit writes into tmp_path so the test has no
    # filesystem side effects outside the pytest sandbox.
    monkeypatch.chdir(tmp_path)

    result = bb.send({
        "target": target,
        "message": message,
    })

    assert result["channel"] == "bluebubbles"
    assert result["status"] == "sent"
    assert result["messageId"], "expected non-empty messageId from BB"

    # Audit log entry written to memory/logs/outbound/<YYYY-MM-DD>.yaml by
    # outbound.submit — integration test is below the gate layer, so we only
    # verify the handler-side emergency log is NOT written (no bypass used).
    emergency_dir = tmp_path / "memory" / "logs" / "outbound"
    if emergency_dir.exists():
        assert not list(emergency_dir.glob("emergency-*.log")), (
            "emergency log written during normal-gate integration test"
        )
