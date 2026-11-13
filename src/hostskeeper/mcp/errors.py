"""MCP tool error codes."""

from __future__ import annotations


class McpToolError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)

    def as_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": str(self)}
