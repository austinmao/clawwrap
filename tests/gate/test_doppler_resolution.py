"""T032 RED — Doppler credential resolution contract for SMS-relay (spec 087).

Defines the contract for `resolve_twilio_credentials()` which selects Twilio
credentials from env (Doppler-injected) based on hub vs tenant mode.

Expected RED failure: `clawwrap.gate.sms_credentials` does not exist yet.
T033 implements it.

Hub mode env vars:
  - TWILIO_ACCOUNT_SID_HUB
  - TWILIO_AUTH_TOKEN_HUB

Tenant mode env vars (tenant_id normalized: upper + dash->underscore):
  - TWILIO_ACCOUNT_SID_<TENANT_ID_UPPER>
  - TWILIO_AUTH_TOKEN_<TENANT_ID_UPPER>
"""
from __future__ import annotations

import logging

import pytest

from clawwrap.gate.sms_credentials import (  # noqa: F401 — RED until T033
    CredentialResolutionError,
    resolve_twilio_credentials,
)

# Sentinel fake secrets — never real Twilio values. Used only to verify the
# resolver plumbs env values through, and to guard against accidental leaks
# in error messages.
_FAKE_HUB_SID = "AC_fake_hub_sid_0000000000000000"
_FAKE_HUB_TOKEN = "fake_hub_token_0000000000000000"
_FAKE_TENANT_SID = "AC_fake_tenant_sid_00000000000000"
_FAKE_TENANT_TOKEN = "fake_tenant_token_00000000000000"


@pytest.mark.unit
def test_hub_resolves_hub_scoped_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hub mode reads TWILIO_ACCOUNT_SID_HUB and TWILIO_AUTH_TOKEN_HUB."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID_HUB", _FAKE_HUB_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_HUB", _FAKE_HUB_TOKEN)

    creds = resolve_twilio_credentials(mode="hub", tenant_id=None)

    assert creds["account_sid"] == _FAKE_HUB_SID
    assert creds["auth_token"] == _FAKE_HUB_TOKEN
    assert creds["mode"] == "hub"
    assert creds["tenant_id"] is None


@pytest.mark.unit
def test_tenant_resolves_tenant_scoped_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenant mode reads TWILIO_*_<TENANT_UPPER> env vars."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID_CEREMONIA", _FAKE_TENANT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_CEREMONIA", _FAKE_TENANT_TOKEN)

    creds = resolve_twilio_credentials(mode="tenant", tenant_id="ceremonia")

    assert creds["account_sid"] == _FAKE_TENANT_SID
    assert creds["auth_token"] == _FAKE_TENANT_TOKEN
    assert creds["mode"] == "tenant"
    assert creds["tenant_id"] == "ceremonia"


@pytest.mark.unit
def test_tenant_id_normalization_dash_to_underscore_and_upper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tenant_id 'Ceremonia-Circle' -> env key suffix 'CEREMONIA_CIRCLE'."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID_CEREMONIA_CIRCLE", _FAKE_TENANT_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_CEREMONIA_CIRCLE", _FAKE_TENANT_TOKEN)

    creds = resolve_twilio_credentials(mode="tenant", tenant_id="Ceremonia-Circle")

    assert creds["account_sid"] == _FAKE_TENANT_SID
    assert creds["auth_token"] == _FAKE_TENANT_TOKEN


@pytest.mark.unit
def test_missing_hub_credentials_raises_with_var_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset hub vars -> CredentialResolutionError naming the missing var."""
    monkeypatch.delenv("TWILIO_ACCOUNT_SID_HUB", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN_HUB", raising=False)

    with pytest.raises(CredentialResolutionError, match=r"TWILIO_ACCOUNT_SID_HUB"):
        resolve_twilio_credentials(mode="hub", tenant_id=None)


@pytest.mark.unit
def test_missing_tenant_credentials_raises_with_tenant_in_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset tenant vars -> error message names the tenant id."""
    monkeypatch.delenv("TWILIO_ACCOUNT_SID_ACME", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN_ACME", raising=False)

    with pytest.raises(CredentialResolutionError, match=r"acme"):
        resolve_twilio_credentials(mode="tenant", tenant_id="acme")


@pytest.mark.unit
def test_tenant_mode_without_tenant_id_raises_value_error() -> None:
    """mode='tenant' with tenant_id=None must raise ValueError before env lookup."""
    with pytest.raises(ValueError, match=r"tenant_id"):
        resolve_twilio_credentials(mode="tenant", tenant_id=None)


@pytest.mark.unit
def test_hub_mode_with_tenant_id_ignores_tenant_and_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hub mode ignores passed tenant_id but emits a warning log."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID_HUB", _FAKE_HUB_SID)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_HUB", _FAKE_HUB_TOKEN)
    # Ensure a tenant-scoped var exists that SHOULD NOT be selected.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID_SOMEONE", "AC_should_not_be_read")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN_SOMEONE", "token_should_not_be_read")

    with caplog.at_level(logging.WARNING):
        creds = resolve_twilio_credentials(mode="hub", tenant_id="someone")

    assert creds["account_sid"] == _FAKE_HUB_SID
    assert creds["auth_token"] == _FAKE_HUB_TOKEN
    assert creds["mode"] == "hub"
    assert creds["tenant_id"] is None
    # Warning mentions that tenant_id was ignored in hub mode.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("tenant_id" in r.getMessage().lower() for r in warnings), (
        f"expected a warning mentioning tenant_id, got: {[r.getMessage() for r in warnings]}"
    )


@pytest.mark.unit
def test_no_credential_leakage_in_error_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error messages mention env var names but never secret values.

    Guard: if a future implementation accidentally includes partial values
    (e.g. via f-string of locals), this test fails before it hits logs.
    """
    # Set SID but deliberately leave token missing so the error fires on token.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID_HUB", _FAKE_HUB_SID)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN_HUB", raising=False)

    with pytest.raises(CredentialResolutionError) as exc_info:
        resolve_twilio_credentials(mode="hub", tenant_id=None)

    message = str(exc_info.value)
    # Env var NAME must appear so operators can fix it.
    assert "TWILIO_AUTH_TOKEN_HUB" in message
    # Secret VALUE must NEVER appear.
    assert _FAKE_HUB_SID not in message
    assert _FAKE_HUB_TOKEN not in message


@pytest.mark.unit
def test_explicit_env_mapping_parameter_overrides_os_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller can pass `env=` to bypass os.environ — useful for tests/sandbox."""
    # Make sure real env does not satisfy the call.
    monkeypatch.delenv("TWILIO_ACCOUNT_SID_HUB", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN_HUB", raising=False)

    explicit_env = {
        "TWILIO_ACCOUNT_SID_HUB": _FAKE_HUB_SID,
        "TWILIO_AUTH_TOKEN_HUB": _FAKE_HUB_TOKEN,
    }

    creds = resolve_twilio_credentials(mode="hub", tenant_id=None, env=explicit_env)

    assert creds["account_sid"] == _FAKE_HUB_SID
    assert creds["auth_token"] == _FAKE_HUB_TOKEN
