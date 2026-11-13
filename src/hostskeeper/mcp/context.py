"""Request-scoped MCP access (HTTP token via contextvar)."""

from __future__ import annotations

from contextvars import ContextVar

from hostskeeper.mcp.service import McpAccess

_access: ContextVar[McpAccess | None] = ContextVar("hostskeeper_mcp_access", default=None)


def set_access(access: McpAccess) -> None:
    _access.set(access)


def get_access() -> McpAccess:
    value = _access.get()
    if value is None:
        return McpAccess(mode="stdio")
    return value
