"""Handler contract: audit.log_resolution_path.

Defines the input/output schema and semantic description for the
``audit.log_resolution_path`` global handler contract.
"""

from __future__ import annotations

from clawwrap.model.handler import HandlerContract

#: Contract for the audit.log_resolution_path handler.
AUDIT_LOG_RESOLUTION_PATH: HandlerContract = HandlerContract(
    handler_id="audit.log_resolution_path",
    contract_version="1.0.0",
    description=(
        "Append a structured audit record to the daily send log "
        "(memory/logs/sends/YYYY-MM-DD.md) documenting how an outbound "
        "WhatsApp target was resolved during a wrapper run. "
        "Must be called in the audit phase after every Ceremonia-bound outbound "
        "send to maintain the Constitution Principle V send audit trail. "
        "Records: run_id, wrapper_name, group_name, resolved_jid, resolution_source, timestamp."
    ),
    input_schema={
        "type": "object",
        "required": ["run_id", "wrapper_name", "group_name", "resolution_source"],
        "additionalProperties": False,
        "properties": {
            "run_id": {
                "type": "string",
                "minLength": 1,
                "description": "Stable run identifier (UUID).",
            },
            "wrapper_name": {
                "type": "string",
                "minLength": 1,
                "description": "Name of the wrapper being audited.",
            },
            "group_name": {
                "type": "string",
                "minLength": 1,
                "description": "Canonical group name that was resolved.",
            },
            "resolved_jid": {
                "type": ["string", "null"],
                "description": "The JID that was resolved, or null if resolution failed.",
            },
            "resolution_source": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "How the target was resolved "
                    "(e.g. 'canonical_registry', 'unknown')."
                ),
            },
            "workspace_root": {
                "type": "string",
                "description": (
                    "Optional workspace root directory override. "
                    "Defaults to current working directory."
                ),
            },
        },
    },
    output_schema={
        "type": "object",
        "required": ["logged", "log_path", "detail"],
        "properties": {
            "logged": {
                "type": "boolean",
                "description": "True when the audit entry was successfully written.",
            },
            "log_path": {
                "type": "string",
                "description": "Path to the log file that was written.",
            },
            "detail": {
                "type": "string",
                "description": "Human-readable result or error description.",
            },
        },
    },
)
