"""Handler contracts: target.resolve_from_canonical and target.verify_no_hardcoded_jid.

Defines the input/output schemas and semantic descriptions for both
``target.*`` global handler contracts.
"""

from __future__ import annotations

from clawwrap.model.handler import HandlerContract

#: Contract for the target.resolve_from_canonical handler.
TARGET_RESOLVE_FROM_CANONICAL: HandlerContract = HandlerContract(
    handler_id="target.resolve_from_canonical",
    contract_version="1.0.0",
    description=(
        "Resolve a WhatsApp target JID from the canonical group registry stored in "
        "the host adapter's config mapping (tools.mappings.whatsapp.groups.*). "
        "The group_name key is the stable canonical name; the JID is the derived value. "
        "This handler must be called before any group JID is used as an outbound target."
    ),
    input_schema={
        "type": "object",
        "required": ["group_name"],
        "additionalProperties": False,
        "properties": {
            "group_name": {
                "type": "string",
                "minLength": 1,
                "description": "Canonical group name key to resolve (e.g. 'medical-screening').",
            },
            "config_path": {
                "type": "string",
                "description": (
                    "Optional override path to openclaw.json. "
                    "Defaults to .openclaw/openclaw.json."
                ),
            },
        },
    },
    output_schema={
        "type": "object",
        "required": ["resolved_jid", "found", "detail"],
        "properties": {
            "resolved_jid": {
                "type": ["string", "null"],
                "description": "Resolved WhatsApp group JID, or null if not found.",
            },
            "found": {
                "type": "boolean",
                "description": "True when a JID was successfully resolved.",
            },
            "detail": {
                "type": "string",
                "description": "Human-readable resolution result or error description.",
            },
        },
    },
)

#: Contract for the target.verify_no_hardcoded_jid handler.
TARGET_VERIFY_NO_HARDCODED_JID: HandlerContract = HandlerContract(
    handler_id="target.verify_no_hardcoded_jid",
    contract_version="1.0.0",
    description=(
        "Verify that an outbound target value does not contain a raw hardcoded "
        "WhatsApp JID supplied directly by the caller. "
        "Targets must always be resolved from the canonical registry "
        "(target.resolve_from_canonical) rather than specified inline. "
        "This handler acts as a safety gate to prevent accidental or malicious "
        "direct JID injection into outbound flows."
    ),
    input_schema={
        "type": "object",
        "required": ["target_value"],
        "additionalProperties": False,
        "properties": {
            "target_value": {
                "type": "string",
                "minLength": 1,
                "description": "The resolved target value to inspect for raw JIDs.",
            },
            "resolution_source": {
                "type": "string",
                "description": (
                    "How the target was resolved. "
                    "Expected value: 'canonical_registry' for legitimate resolutions."
                ),
            },
        },
    },
    output_schema={
        "type": "object",
        "required": ["safe", "detail"],
        "properties": {
            "safe": {
                "type": "boolean",
                "description": "True when no hardcoded JID was detected in target_value.",
            },
            "detail": {
                "type": "string",
                "description": "Human-readable verification result or violation description.",
            },
        },
    },
)
