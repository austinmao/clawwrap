"""OpenClaw handler binding: dm.resolve_jid.

Validates and normalises a WhatsApp direct-message JID before sending.
Does not call wacli — pure validation.
"""
from __future__ import annotations

import re
from typing import Any

from clawwrap.handlers.registry import handler

# Individual number JID: 13033324741@s.whatsapp.net
_DM_JID_RE = re.compile(r"^\d{7,15}@s\.whatsapp\.net$")
# US phone (E.164): +13033324741, 13033324741, (303) 332-4741, etc.
_PHONE_RE = re.compile(r"^\+?1?(\d{10})$")


def _normalise(raw: str) -> tuple[str, str]:
    """Return (normalised_jid, jid_type) or raise ValueError."""
    raw = raw.strip()
    if _DM_JID_RE.match(raw):
        return raw, "individual"
    cleaned = raw.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    m = _PHONE_RE.match(cleaned)
    if m:
        return f"1{m.group(1)}@s.whatsapp.net", "individual"
    raise ValueError(f"Cannot normalise to a WhatsApp DM JID: {raw!r}")


@handler("dm.resolve_jid", adapter_name="openclaw")
def resolve_jid(inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise a DM target JID.

    Contract inputs:
        to_jid (str): Phone number or JID of the recipient.

    Contract outputs:
        normalized_jid (str): Canonical JID (e.g. 13033324741@s.whatsapp.net).
        jid_type (str): "individual" (DMs only; groups are rejected).
        valid (bool): True when normalisation succeeded.
        detail (str): Human-readable result.
    """
    raw: str = str(inputs.get("to_jid", ""))
    if not raw:
        return {"normalized_jid": "", "jid_type": "", "valid": False, "detail": "to_jid is required"}

    try:
        jid, jid_type = _normalise(raw)
    except ValueError as exc:
        return {"normalized_jid": "", "jid_type": "", "valid": False, "detail": str(exc)}

    return {"normalized_jid": jid, "jid_type": jid_type, "valid": True, "detail": "jid normalised"}
