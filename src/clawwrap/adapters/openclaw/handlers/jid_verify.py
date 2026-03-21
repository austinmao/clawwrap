"""OpenClaw handler binding: target.verify_no_hardcoded_jid.

Verifies that the outbound target was resolved from the canonical registry
and does not contain a raw hardcoded JID supplied directly by the caller.
"""

from __future__ import annotations

import re
from typing import Any

from clawwrap.handlers.registry import handler

# Pattern that matches a raw WhatsApp JID in typical formats:
#   1234567890@s.whatsapp.net  (individual)
#   1234567890-1234567890@g.us (group, old format)
#   12345678901234567890@g.us  (group, new format)
_JID_PATTERN: re.Pattern[str] = re.compile(
    r"^\d{7,20}(?:-\d+)?@(?:s\.whatsapp\.net|g\.us)$"
)

# Source tag that the canonical resolver stamps on its output.
_CANONICAL_SOURCE: str = "canonical_registry"


def _looks_like_raw_jid(value: str) -> bool:
    """Return True when *value* matches the raw JID format.

    Args:
        value: String to test.

    Returns:
        True if value matches the WhatsApp JID pattern.
    """
    return bool(_JID_PATTERN.match(value.strip()))


@handler("target.verify_no_hardcoded_jid", adapter_name="openclaw")
def verify_no_hardcoded_jid(inputs: dict[str, Any]) -> dict[str, Any]:
    """Verify that the outbound target was not supplied as a hardcoded JID.

    Contract inputs:
        target_value (str): The resolved target to inspect.
        resolution_source (str, optional): How the target was resolved.
            Should be ``canonical_registry`` for legitimate resolutions.

    Contract outputs:
        safe (bool): True when no hardcoded JID is detected.
        detail (str): Human-readable result or violation description.

    Args:
        inputs: Handler input dict conforming to the target.verify_no_hardcoded_jid contract.

    Returns:
        Dict with ``safe`` (bool) and ``detail`` (str).
    """
    target_value: str = str(inputs.get("target_value", ""))
    resolution_source: str = str(inputs.get("resolution_source", ""))

    if not target_value:
        return {"safe": False, "detail": "target_value is required"}

    if _looks_like_raw_jid(target_value):
        return {
            "safe": False,
            "detail": (
                f"Hardcoded JID detected in target_value: {target_value!r}. "
                "Targets must be resolved from the canonical registry, not supplied directly."
            ),
        }

    if resolution_source and resolution_source != _CANONICAL_SOURCE:
        return {
            "safe": False,
            "detail": (
                f"Target was resolved via '{resolution_source}', "
                f"expected '{_CANONICAL_SOURCE}'."
            ),
        }

    return {"safe": True, "detail": "target verified — no hardcoded JID"}
