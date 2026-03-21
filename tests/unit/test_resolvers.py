"""Unit tests for adapter-owned recipient resolvers (airtable + retreat_guru)."""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from clawwrap.adapters.openclaw.resolvers.airtable import AirtableContactsResolver
from clawwrap.adapters.openclaw.resolvers.retreat_guru import RetreatGuruRegistrationsResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response with JSON body."""
    response = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "https://example.com"),
    )
    return response


def _mock_error_response(status_code: int = 404) -> httpx.Response:
    """Build a fake httpx.Response that raises on raise_for_status."""
    response = httpx.Response(
        status_code=status_code,
        request=httpx.Request("GET", "https://example.com"),
    )
    return response


# ---------------------------------------------------------------------------
# Airtable resolver
# ---------------------------------------------------------------------------


class TestAirtableResolver:
    def test_resolve_returns_correct_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIRTABLE_API_KEY", "fake-key")
        payload = {
            "id": "rec123",
            "fields": {
                "Email": "jane@example.com",
                "Name": "Jane Doe",
            },
        }
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = AirtableContactsResolver()
            target, label, provider_id = resolver.resolve("airtable:contacts/rec123", "email")

        assert target == "jane@example.com"
        assert "Jane Doe" in label
        assert "rec123" in label
        assert provider_id == "rec123"

    def test_resolve_whatsapp_returns_phone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIRTABLE_API_KEY", "fake-key")
        payload = {
            "id": "rec456",
            "fields": {
                "Phone": "+15551234567",
                "Name": "John Smith",
            },
        }
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = AirtableContactsResolver()
            target, label, provider_id = resolver.resolve("airtable:contacts/rec456", "whatsapp")

        assert target == "+15551234567"
        assert "John Smith" in label
        assert provider_id == "rec456"

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
        resolver = AirtableContactsResolver()
        with pytest.raises(ValueError, match="AIRTABLE_API_KEY is not set"):
            resolver.resolve("airtable:contacts/rec123", "email")

    def test_api_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIRTABLE_API_KEY", "fake-key")
        with patch(
            "clawwrap.adapters.openclaw.resolvers._helpers.httpx.get",
            return_value=_mock_error_response(404),
        ):
            resolver = AirtableContactsResolver()
            with pytest.raises(ValueError, match="HTTP 404"):
                resolver.resolve("airtable:contacts/rec123", "email")

    def test_missing_email_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AIRTABLE_API_KEY", "fake-key")
        payload = {
            "id": "rec123",
            "fields": {"Name": "No Email Person"},
        }
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = AirtableContactsResolver()
            with pytest.raises(ValueError, match="missing an email"):
                resolver.resolve("airtable:contacts/rec123", "email")

    def test_invalid_ref_prefix_raises(self) -> None:
        resolver = AirtableContactsResolver()
        with pytest.raises(ValueError, match="must start with"):
            resolver.resolve("wrong:contacts/rec123", "email")


# ---------------------------------------------------------------------------
# Retreat Guru resolver
# ---------------------------------------------------------------------------


class TestRetreatGuruResolver:
    def test_resolve_returns_correct_tuple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETREAT_GURU_API_KEY", "fake-rg-key")
        payload = {
            "id": 42,
            "email": "participant@example.com",
            "first_name": "Alice",
            "last_name": "Johnson",
        }
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = RetreatGuruRegistrationsResolver()
            target, label, provider_id = resolver.resolve("retreat_guru:registrations/42", "email")

        assert target == "participant@example.com"
        assert "Alice Johnson" in label
        assert provider_id == "42"

    def test_resolve_whatsapp_from_questions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETREAT_GURU_API_KEY", "fake-rg-key")
        payload = {
            "id": 99,
            "email": "bob@example.com",
            "first_name": "Bob",
            "last_name": "Lee",
            "questions": {"phone": "+14155551234"},
        }
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = RetreatGuruRegistrationsResolver()
            target, label, provider_id = resolver.resolve("retreat_guru:registrations/99", "whatsapp")

        assert target == "+14155551234"
        assert "Bob Lee" in label
        assert provider_id == "99"

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RETREAT_GURU_API_KEY", raising=False)
        resolver = RetreatGuruRegistrationsResolver()
        with pytest.raises(ValueError, match="RETREAT_GURU_API_KEY is not set"):
            resolver.resolve("retreat_guru:registrations/42", "email")

    def test_api_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETREAT_GURU_API_KEY", "fake-rg-key")
        with patch(
            "clawwrap.adapters.openclaw.resolvers._helpers.httpx.get",
            return_value=_mock_error_response(500),
        ):
            resolver = RetreatGuruRegistrationsResolver()
            with pytest.raises(ValueError, match="HTTP 500"):
                resolver.resolve("retreat_guru:registrations/42", "email")

    def test_missing_email_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RETREAT_GURU_API_KEY", "fake-rg-key")
        payload = {
            "id": 42,
            "first_name": "No",
            "last_name": "Email",
        }
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = RetreatGuruRegistrationsResolver()
            with pytest.raises(ValueError, match="missing an email"):
                resolver.resolve("retreat_guru:registrations/42", "email")

    def test_invalid_ref_prefix_raises(self) -> None:
        resolver = RetreatGuruRegistrationsResolver()
        with pytest.raises(ValueError, match="must start with"):
            resolver.resolve("wrong:registrations/42", "email")

    def test_list_response_unwrapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Retreat Guru API can return a list; resolver should unwrap first element."""
        monkeypatch.setenv("RETREAT_GURU_API_KEY", "fake-rg-key")
        payload = [
            {
                "id": 42,
                "email": "wrapped@example.com",
                "first_name": "Wrapped",
                "last_name": "User",
            }
        ]
        with patch("clawwrap.adapters.openclaw.resolvers._helpers.httpx.get", return_value=_mock_response(payload)):
            resolver = RetreatGuruRegistrationsResolver()
            target, label, provider_id = resolver.resolve("retreat_guru:registrations/42", "email")

        assert target == "wrapped@example.com"
        assert provider_id == "42"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestBuildResolverRegistry:
    def test_registry_contains_both_resolvers(self) -> None:
        from clawwrap.adapters.openclaw.resolvers import build_resolver_registry

        registry = build_resolver_registry()
        assert "airtable" in registry
        assert "retreat_guru" in registry
        assert isinstance(registry["airtable"], AirtableContactsResolver)
        assert isinstance(registry["retreat_guru"], RetreatGuruRegistrationsResolver)
