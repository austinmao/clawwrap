"""Wrapper spec JSON schema (v1)."""

SCHEMA_VERSION = 1

SCHEMA = {
    "type": "object",
    "required": ["name", "version", "schema_version", "description", "inputs", "outputs", "stages"],
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "schema_version": {"type": "integer", "minimum": 1},
        "description": {"type": "string", "minLength": 1},
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "required", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "required": {"type": "boolean"},
                    "description": {"type": "string"},
                },
            },
        },
        "outputs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "stages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["phase", "expects", "produces"],
                "properties": {
                    "phase": {"type": "string", "enum": ["resolve", "verify", "approve", "execute", "audit"]},
                    "expects": {"type": "object"},
                    "produces": {"type": "object"},
                },
            },
        },
        "providers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "config_ref"],
                "properties": {"kind": {"type": "string"}, "config_ref": {"type": "string"}},
            },
        },
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "version_constraint"],
                "properties": {"name": {"type": "string"}, "version_constraint": {"type": "string"}},
            },
        },
        "policies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "version_constraint"],
                "properties": {"name": {"type": "string"}, "version_constraint": {"type": "string"}},
            },
        },
        "approval_role": {"type": "string", "enum": ["operator", "approver", "admin"], "default": "operator"},
    },
}
