"""Handler contract: group.identity_matches.

Defines the input/output schemas and semantic description for the
``group.identity_matches`` global handler contract.
"""

from __future__ import annotations

from clawwrap.model.handler import HandlerContract

#: Contract for the group.identity_matches handler.
GROUP_IDENTITY_MATCHES: HandlerContract = HandlerContract(
    handler_id="group.identity_matches",
    contract_version="1.0.0",
    description=(
        "Verify that a WhatsApp group's live identity matches the canonical record. "
        "Uses the wacli CLI to query the group JID and compare its display name "
        "against the expected name supplied in the wrapper's resolved inputs. "
        "Must be used before any outbound message is dispatched to a group target."
    ),
    input_schema={
        "type": "object",
        "required": ["group_jid", "expected_name"],
        "additionalProperties": False,
        "properties": {
            "group_jid": {
                "type": "string",
                "description": "WhatsApp group JID (e.g. 12345678901234567890@g.us).",
                "pattern": r"^\d{7,20}(?:-\d+)?@g\.us$",
            },
            "expected_name": {
                "type": "string",
                "minLength": 1,
                "description": "Expected WhatsApp group display name.",
            },
        },
    },
    output_schema={
        "type": "object",
        "required": ["matched", "detail"],
        "properties": {
            "matched": {
                "type": "boolean",
                "description": "True when the live group identity matches expected_name.",
            },
            "detail": {
                "type": "string",
                "description": "Human-readable verification result or error description.",
            },
        },
    },
)
