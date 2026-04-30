"""Twilio credential resolver for the SMS-relay channel (spec 087).

Resolves Twilio account SID + auth token from Doppler-injected environment
variables. Supports two modes:

* ``hub``    — shared Lumina hub Twilio account (TWILIO_*_HUB env vars).
* ``tenant`` — per-tenant Twilio account (TWILIO_*_<TENANT_UPPER> env vars).

Tenant IDs are normalized for env key lookup by uppercasing and replacing
any ``-`` with ``_`` (e.g. ``"Ceremonia-Circle"`` -> ``CEREMONIA_CIRCLE``).

Security:
    * Never includes resolved secret values in exceptions or log records.
    * Emits a warning (not an error) when ``mode="hub"`` is called with a
      non-None ``tenant_id`` — the tenant is ignored and hub vars are used.
"""
from __future__ import annotations

import logging
import os
from typing import Literal, Mapping, TypedDict

logger = logging.getLogger(__name__)

HubOrTenant = Literal["hub", "tenant"]


class TwilioCredentials(TypedDict):
    """Resolved Twilio credentials for a single send/receive.

    Never log or serialize this dict — ``auth_token`` is a secret.
    """

    account_sid: str
    auth_token: str
    mode: HubOrTenant
    tenant_id: str | None


class CredentialResolutionError(Exception):
    """Raised when required Twilio env vars are missing.

    Error messages name the missing env var so operators can fix the
    Doppler configuration, but never include any secret value.
    """


def _normalize_tenant_suffix(tenant_id: str) -> str:
    """Tenant id -> env var suffix (upper, dash->underscore)."""
    return tenant_id.replace("-", "_").upper()


def _require(env: Mapping[str, str], var_name: str) -> str:
    value = env.get(var_name)
    if not value:
        raise CredentialResolutionError(f"missing env var: {var_name}")
    return value


def resolve_twilio_credentials(
    mode: HubOrTenant,
    tenant_id: str | None,
    env: Mapping[str, str] | None = None,
) -> TwilioCredentials:
    """Resolve Twilio credentials for ``mode`` + optional ``tenant_id``.

    Args:
        mode: ``"hub"`` for shared Lumina hub, ``"tenant"`` for per-tenant.
        tenant_id: Required when ``mode="tenant"``; ignored (with warning)
            when ``mode="hub"``.
        env: Optional explicit mapping. Defaults to ``os.environ``.

    Returns:
        Resolved :class:`TwilioCredentials`.

    Raises:
        ValueError: ``mode="tenant"`` with ``tenant_id=None``.
        CredentialResolutionError: Required env var missing. Message names
            the env var (and tenant id for tenant mode) but never includes
            the secret value itself.
    """
    if mode == "tenant" and tenant_id is None:
        raise ValueError("tenant_id is required when mode='tenant'")

    if mode == "hub" and tenant_id is not None:
        logger.warning(
            "resolve_twilio_credentials called with mode='hub' and non-None "
            "tenant_id=%r; tenant_id is ignored in hub mode",
            tenant_id,
        )
        tenant_id = None

    resolved_env: Mapping[str, str] = env if env is not None else os.environ

    if mode == "hub":
        try:
            sid = _require(resolved_env, "TWILIO_ACCOUNT_SID_HUB")
            token = _require(resolved_env, "TWILIO_AUTH_TOKEN_HUB")
        except CredentialResolutionError:
            raise
        return TwilioCredentials(
            account_sid=sid,
            auth_token=token,
            mode="hub",
            tenant_id=None,
        )

    # mode == "tenant"
    assert tenant_id is not None  # narrowed above
    suffix = _normalize_tenant_suffix(tenant_id)
    sid_var = f"TWILIO_ACCOUNT_SID_{suffix}"
    token_var = f"TWILIO_AUTH_TOKEN_{suffix}"

    try:
        sid = _require(resolved_env, sid_var)
        token = _require(resolved_env, token_var)
    except CredentialResolutionError as exc:
        # Re-raise with tenant context so ops can identify the tenant.
        raise CredentialResolutionError(
            f"{exc} (tenant={tenant_id!r})"
        ) from None

    return TwilioCredentials(
        account_sid=sid,
        auth_token=token,
        mode="tenant",
        tenant_id=tenant_id,
    )
