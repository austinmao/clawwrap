"""Unit tests for mailchimp channel — payload passthrough + identity verification."""
from __future__ import annotations

from unittest.mock import MagicMock

from clawwrap.engine.gate import OutboundRequest, ResolvedContext


class TestMailchimpPayloadPassthrough:
    def test_payload_reaches_dispatch(self) -> None:
        payload = {
            "subject": "Sunday Service",
            "html": "<h1>Hello</h1>",
            "plain_text": "Hello",
            "from_name": "Ceremonia",
            "from_email": "info@mail.ceremoniacircle.org",
            "reply_to": "info@ceremoniacircle.org",
        }
        req = OutboundRequest(
            route_mode="shared",
            channel="mailchimp",
            message="Sunday Service",
            requested_by="newsletter-deliver",
            context_key="newsletter",
            audience="full-list",
            payload=payload,
        )
        assert req.validate() is None
        assert req.payload is not None
        assert req.payload["subject"] == "Sunday Service"
        assert req.payload["html"] == "<h1>Hello</h1>"


class TestMailchimpIdentityVerification:
    def test_mailchimp_identity_returns_deferred(self) -> None:
        from clawwrap.adapters.openclaw.handlers.outbound_submit import (
            _verify_mailchimp_identity,
        )

        resolved = ResolvedContext(
            target="9b70ef06f1",
            audience_label="Ceremonia -- full newsletter subscriber list",
            expected_identity={"name": "Ceremonia"},
            allowlist_key="newsletter.full-list",
            verification_supported=False,
        )
        result = _verify_mailchimp_identity(resolved, MagicMock())
        assert result.verification_supported is False
        assert result.live_identity is not None
        assert result.live_identity["expected_name"] == "Ceremonia"
