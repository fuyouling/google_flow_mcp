from typing import Any
from pydantic import BaseModel


class ToolResponse(BaseModel):
    """Unified response format returned by all MCP tools."""

    success: bool
    data: Any | None = None
    error: str | None = None

    def to_json(self) -> str:
        """Serialize response to JSON string."""
        return self.model_dump_json(indent=2)
