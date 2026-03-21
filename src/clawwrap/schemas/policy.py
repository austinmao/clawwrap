"""Policy spec JSON schema (v1)."""

SCHEMA_VERSION = 1

SCHEMA = {
    "type": "object",
    "required": ["name", "version", "schema_version", "description", "checks"],
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "schema_version": {"type": "integer", "minimum": 1},
        "description": {"type": "string", "minLength": 1},
        "checks": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["handler_id", "phase", "fail_action"],
                "properties": {
                    "handler_id": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"},
                    "phase": {"type": "string", "enum": ["resolve", "verify", "approve", "execute", "audit"]},
                    "params": {"type": "object", "default": {}},
                    "fail_action": {"type": "string", "enum": ["block", "warn"]},
                },
            },
        },
        "approval_role": {"type": "string", "enum": ["operator", "approver", "admin"]},
    },
}
