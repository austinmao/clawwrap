"""Handler contract dataclass — global semantic contract for a named check handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class HandlerContract:
    """Global semantic contract for a named check handler (dotted notation ID)."""

    handler_id: str
    contract_version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandlerContract:
        """Construct a HandlerContract from a raw dict."""
        return cls(
            handler_id=data["handler_id"],
            contract_version=data["contract_version"],
            description=data["description"],
            input_schema=dict(data["input_schema"]),
            output_schema=dict(data["output_schema"]),
        )
