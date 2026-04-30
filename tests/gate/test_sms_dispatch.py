"""T031 (spec 087): RED tests for SMS-relay dispatch handler TCPA keyword gate.

Defines the contract for ``clawwrap.gate.dispatch.dispatch_sms_relay`` — the
inbound SMS keyword classifier that enforces TCPA STOP/HELP/START semantics
and writes compliance-audit rows before any normal handler runs.

These tests are expected to RED-fail with ImportError / AttributeError
until T033 implements ``dispatch_sms_relay`` in
``clawwrap/src/clawwrap/gate/dispatch.py``.

Target API (stable contract — do not change without team-lead approval):

    dispatch_sms_relay(
        tenant_id: str,
        phone_e164: str,
        body: str,
        direction: Literal["inbound", "outbound"],
        db_conn: Any,
    ) -> dict[str, Any]

Return dict:
    {
      "action":   "suppress" | "respond_help" | "unsuppress" | "passthrough",
      "keyword":  "STOP" | "HELP" | "START" | None,
      "compliance_event_id": int | None,
      "outbound_text": str | None,   # populated for HELP
      "suppressed":   bool,          # post-dispatch suppression state
    }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

# Intentional import at top-level — we want the *collection* phase to succeed
# so each test reports its own AttributeError when `dispatch_sms_relay` is
# still missing. The import of the module itself is known-good today.
from clawwrap.gate import dispatch as dispatch_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HUB_TENANT = "lumina-hub"
TENANT_A = "tenant-ceremonia"
PHONE_X = "+15551230001"
PHONE_Y = "+15551230002"


@pytest.fixture
def tenant_id() -> str:
    return TENANT_A


@pytest.fixture
def phone_e164() -> str:
    return PHONE_X


@pytest.fixture
def db_conn() -> MagicMock:
    """A fake DB connection with a context-manager cursor.

    Mirrors psycopg's ``conn.cursor()`` shape so dispatch code can do either:
        with conn.cursor() as cur: cur.execute(...); cur.fetchone()
    or:
        cur = conn.cursor(); cur.execute(...); cur.fetchone()
    """
    cur = MagicMock(name="cursor")
    # By default no prior suppression row and no prior HELP row.
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []
    # Simulate RETURNING id for INSERTs.
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock(name="db_conn")
    conn.cursor.return_value = cur
    conn._cursor = cur  # noqa: SLF001 — test convenience handle
    return conn


def _call(
    db_conn: MagicMock,
    tenant_id: str,
    phone_e164: str,
    body: str,
    direction: str = "inbound",
) -> dict[str, Any]:
    """Thin wrapper so every test exercises the same entrypoint."""
    fn = getattr(dispatch_mod, "dispatch_sms_relay")
    return fn(
        tenant_id=tenant_id,
        phone_e164=phone_e164,
        body=body,
        direction=direction,
        db_conn=db_conn,
    )


# ---------------------------------------------------------------------------
# STOP keyword — case / whitespace variants match
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    ["STOP", "stop", "Stop", " STOP ", "stop\n", "\tSTOP\t"],
)
def test_stop_keyword_case_and_whitespace_variants_match(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["keyword"] == "STOP"
    assert result["action"] == "suppress"
    assert result["suppressed"] is True


@pytest.mark.parametrize(
    "body",
    ["STOPPING", "STOPPED", "STOP NOW", "please stop spamming", "unstop"],
)
def test_stop_keyword_rejects_non_exact_matches(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["keyword"] is None
    assert result["action"] == "passthrough"


# ---------------------------------------------------------------------------
# HELP keyword — exact-word match only
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    ["HELP", "help", "Help", " HELP ", "help\n"],
)
def test_help_keyword_case_and_whitespace_variants_match(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["keyword"] == "HELP"
    assert result["action"] == "respond_help"


@pytest.mark.parametrize(
    "body",
    ["help me", "HELP ME", "HELPFUL", "please help"],
)
def test_help_keyword_rejects_non_exact_matches(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["keyword"] is None
    assert result["action"] == "passthrough"


# ---------------------------------------------------------------------------
# START keyword — re-subscribe
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    ["START", "start", "Start", " START ", "start\n"],
)
def test_start_keyword_case_and_whitespace_variants_match(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["keyword"] == "START"
    assert result["action"] == "unsuppress"
    assert result["suppressed"] is False


@pytest.mark.parametrize(
    "body",
    ["STARTING", "STARTED", "start the car", "restart"],
)
def test_start_keyword_rejects_non_exact_matches(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["keyword"] is None
    assert result["action"] == "passthrough"


# ---------------------------------------------------------------------------
# STOP — compliance event row written
# ---------------------------------------------------------------------------

def test_stop_writes_compliance_event_row(
    db_conn: MagicMock, tenant_id: str, phone_e164: str
) -> None:
    before = datetime.now(timezone.utc)
    result = _call(db_conn, tenant_id, phone_e164, "STOP")
    after = datetime.now(timezone.utc)

    assert result["compliance_event_id"] is not None

    cur = db_conn._cursor  # noqa: SLF001
    assert cur.execute.called, "dispatch must execute at least one SQL statement"

    # Collect every SQL+params pair that ran.
    calls = [call.args for call in cur.execute.call_args_list]
    insert_calls = [
        c for c in calls
        if len(c) >= 1 and "sms_compliance_events" in str(c[0]).lower() and "insert" in str(c[0]).lower()
    ]
    assert insert_calls, "dispatch must INSERT into sms_compliance_events on STOP"

    sql, params = insert_calls[0][0], insert_calls[0][1]
    # Params may be tuple/list/dict — normalize to a flat comparable form.
    param_values = list(params.values()) if isinstance(params, dict) else list(params)
    assert tenant_id in param_values
    assert phone_e164 in param_values
    assert "STOP" in param_values
    assert "suppress" in param_values

    # Timestamp, if passed as a param, must be within the call window.
    ts_params = [p for p in param_values if isinstance(p, datetime)]
    for ts in ts_params:
        assert before <= ts <= after, "compliance event timestamp outside call window"


# ---------------------------------------------------------------------------
# HELP — canned TCPA-compliant response
# ---------------------------------------------------------------------------

def test_help_returns_tcpa_compliant_canned_text(
    db_conn: MagicMock, tenant_id: str, phone_e164: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, "HELP")
    outbound = result["outbound_text"]

    assert isinstance(outbound, str) and outbound.strip(), "HELP must return non-empty outbound text"
    lowered = outbound.lower()
    # TCPA HELP reply must include an opt-out reminder (STOP) so the carrier
    # accepts it as a compliant autoresponse.
    assert "stop" in lowered, "HELP response must include STOP opt-out reminder"


def test_help_does_not_mark_phone_suppressed(
    db_conn: MagicMock, tenant_id: str, phone_e164: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, "HELP")
    assert result["suppressed"] is False


# ---------------------------------------------------------------------------
# START — clears prior suppression
# ---------------------------------------------------------------------------

def test_start_after_prior_stop_clears_suppression(
    db_conn: MagicMock, tenant_id: str, phone_e164: str
) -> None:
    # Simulate: a previous STOP row exists for this (tenant, phone).
    cur = db_conn._cursor  # noqa: SLF001
    cur.fetchone.return_value = (1, tenant_id, phone_e164, "STOP", "suppress")

    result = _call(db_conn, tenant_id, phone_e164, "START")

    assert result["action"] == "unsuppress"
    assert result["keyword"] == "START"
    assert result["suppressed"] is False

    calls = [call.args for call in cur.execute.call_args_list]
    unsuppress_calls = [
        c for c in calls
        if len(c) >= 1
        and "sms_compliance_events" in str(c[0]).lower()
        and (
            "insert" in str(c[0]).lower()  # action=unsuppress event row
            or "delete" in str(c[0]).lower()  # suppression row removal
        )
    ]
    assert unsuppress_calls, "START must either INSERT unsuppress event or DELETE suppression row"


# ---------------------------------------------------------------------------
# Non-keyword passthrough
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "body",
    ["hello", "Hi there", "Where's my order?", "yes please", "12345"],
)
def test_ordinary_text_passes_through(
    db_conn: MagicMock, tenant_id: str, phone_e164: str, body: str
) -> None:
    result = _call(db_conn, tenant_id, phone_e164, body)
    assert result["action"] == "passthrough"
    assert result["keyword"] is None
    assert result["compliance_event_id"] is None
    assert result["outbound_text"] is None


def test_passthrough_writes_no_compliance_event(
    db_conn: MagicMock, tenant_id: str, phone_e164: str
) -> None:
    _call(db_conn, tenant_id, phone_e164, "hello world")
    cur = db_conn._cursor  # noqa: SLF001
    calls = [call.args for call in cur.execute.call_args_list]
    compliance_inserts = [
        c for c in calls
        if len(c) >= 1
        and "sms_compliance_events" in str(c[0]).lower()
        and "insert" in str(c[0]).lower()
    ]
    assert not compliance_inserts, "passthrough must NOT write sms_compliance_events rows"


# ---------------------------------------------------------------------------
# Hub vs tenant scoping — suppressions are per (tenant_id, phone_e164)
# ---------------------------------------------------------------------------

def test_stop_on_hub_does_not_suppress_same_phone_on_tenant(
    db_conn: MagicMock,
) -> None:
    # STOP from PHONE_X on the hub tenant.
    hub_result = _call(db_conn, HUB_TENANT, PHONE_X, "STOP")
    assert hub_result["action"] == "suppress"
    assert hub_result["suppressed"] is True

    # Fresh lookup for the tenant scope returns no suppression row.
    cur = db_conn._cursor  # noqa: SLF001
    cur.reset_mock()
    cur.fetchone.return_value = None

    # An ordinary message from the same phone, but scoped to TENANT_A,
    # must be treated as not-suppressed (passthrough).
    tenant_result = _call(db_conn, TENANT_A, PHONE_X, "hello")
    assert tenant_result["action"] == "passthrough"
    assert tenant_result["suppressed"] is False


def test_suppression_query_scoped_by_tenant_and_phone(
    db_conn: MagicMock, tenant_id: str, phone_e164: str
) -> None:
    _call(db_conn, tenant_id, phone_e164, "hello")
    cur = db_conn._cursor  # noqa: SLF001
    calls = [call.args for call in cur.execute.call_args_list]
    # At least one SELECT must filter by BOTH tenant_id and phone_e164 to
    # prove per-tenant scoping (no cross-tenant leakage).
    scoped_selects = [
        c for c in calls
        if len(c) >= 2
        and "select" in str(c[0]).lower()
        and tenant_id in (
            list(c[1].values()) if isinstance(c[1], dict) else list(c[1])
        )
        and phone_e164 in (
            list(c[1].values()) if isinstance(c[1], dict) else list(c[1])
        )
    ]
    assert scoped_selects, (
        "dispatch must SELECT suppression state scoped by (tenant_id, phone_e164)"
    )
