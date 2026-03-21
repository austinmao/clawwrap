"""Host adapter spec JSON schema (v1)."""

SCHEMA_VERSION = 1

SCHEMA = {
    "type": "object",
    "required": [
        "name", "version", "schema_version", "description",
        "supported_handlers", "approval_identity", "owned_surfaces", "capabilities",
    ],
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
        "schema_version": {"type": "integer", "minimum": 1},
        "description": {"type": "string", "minLength": 1},
        "supported_handlers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["handler_id", "contract_version", "binding_module"],
                "properties": {
                    "handler_id": {"type": "string", "pattern": r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"},
                    "contract_version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"},
                    "binding_module": {"type": "string"},
                },
            },
        },
        "approval_identity": {
            "type": "object",
            "required": ["source_type", "subject_key", "trust_basis"],
            "properties": {
                "source_type": {"type": "string"},
                "subject_key": {"type": "string"},
                "trust_basis": {"type": "string"},
            },
        },
        "owned_surfaces": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["surface_type", "selector_pattern"],
                "properties": {
                    "surface_type": {
                        "type": "string",
                        "enum": ["file", "config_key", "mapping_entry", "prompt_fragment"],
                    },
                    "selector_pattern": {"type": "string"},
                },
            },
        },
        "capabilities": {"type": "array", "items": {"type": "string"}},
    },
}
