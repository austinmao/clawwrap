"""Adapter-owned direct recipient resolvers for the OpenClaw host.

These resolvers back the public ``recipient_ref`` contract used by the outbound
gate. Callers submit canonical refs such as ``airtable:contacts/rec123`` and
the adapter resolves the concrete channel destination against the current
system of record.
"""
from __future__ import annotations

from clawwrap.adapters.openclaw.resolvers.airtable import AirtableContactsResolver
from clawwrap.adapters.openclaw.resolvers.retreat_guru import RetreatGuruRegistrationsResolver
from clawwrap.gate.resolve import RecipientResolver

__all__ = [
    "AirtableContactsResolver",
    "RetreatGuruRegistrationsResolver",
    "build_resolver_registry",
]


def build_resolver_registry() -> dict[str, RecipientResolver]:
    """Return the OpenClaw adapter's direct recipient resolvers."""
    return {
        "airtable": AirtableContactsResolver(),
        "retreat_guru": RetreatGuruRegistrationsResolver(),
    }
