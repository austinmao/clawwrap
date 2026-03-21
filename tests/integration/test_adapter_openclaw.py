"""T070: Placeholder integration tests for the OpenClaw adapter.

These tests require a running OpenClaw gateway.
They are skipped automatically when the gateway is not available.
"""

from __future__ import annotations

import os

import pytest


def _gateway_available() -> bool:
    """Return True when an OpenClaw gateway URL is configured."""
    return bool(os.environ.get("OPENCLAW_GATEWAY_URL"))


pytestmark = pytest.mark.skipif(
    not _gateway_available(),
    reason="OPENCLAW_GATEWAY_URL not set — OpenClaw adapter integration tests skipped",
)


class TestOpenClawAdapterIntegration:
    """Placeholder tests for the OpenClaw host adapter.

    These document the intended contract for when the gateway is available.
    """

    def test_placeholder_adapter_health_check(self) -> None:
        """PLACEHOLDER: Adapter should be able to reach the OpenClaw gateway.

        Implementation required:
        1. Instantiate the OpenClaw adapter with the gateway URL.
        2. Call a health-check method.
        3. Assert the gateway responds with a 200 OK.
        """
        pytest.skip("Requires running OpenClaw gateway — implement when available")

    def test_placeholder_bind_handler_returns_callable(self) -> None:
        """PLACEHOLDER: bind_handler should return a callable for a known handler_id.

        Implementation required:
        1. Instantiate the adapter.
        2. Call bind_handler('target.resolve_from_canonical').
        3. Assert the returned value is callable.
        """
        pytest.skip("Requires running OpenClaw gateway — implement when available")

    def test_placeholder_resolve_approval_identity(self) -> None:
        """PLACEHOLDER: resolve_approval_identity should return a valid ApprovalRole.

        Implementation required:
        1. Create a test ApprovalIdentityEvidence.
        2. Call adapter.resolve_approval_identity(evidence).
        3. Assert the result is a valid ApprovalRole.
        """
        pytest.skip("Requires running OpenClaw gateway — implement when available")

    def test_placeholder_read_host_state_returns_dict(self) -> None:
        """PLACEHOLDER: read_host_state should return a dict keyed by surface selectors.

        Implementation required:
        1. Call adapter.read_host_state(['agents/test/SOUL.md']).
        2. Assert the result is a dict.
        3. Assert the key matches the provided selector.
        """
        pytest.skip("Requires running OpenClaw gateway — implement when available")

    def test_placeholder_live_send_handler_is_guarded(self) -> None:
        """PLACEHOLDER: In dev mode, live send handlers should raise a guardrail error.

        Implementation required:
        1. Bind 'target.send_whatsapp_message' in dev adapter.
        2. Call the returned handler.
        3. Assert RuntimeError with GUARDRAIL message is raised.
        """
        pytest.skip("Requires running OpenClaw gateway — implement when available")
