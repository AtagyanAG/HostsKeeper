"""Runtime session models (no network secrets in public views)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    CONNECTING = "connecting"
    LIVE = "live"
    DISCONNECTED = "disconnected"
    CLOSED = "closed"


class SessionTarget(str, Enum):
    TAB = "tab"
    PUTTY = "putty"
    WINSCP = "winscp"


@dataclass(frozen=True)
class SessionInfo:
    """Safe session snapshot for UI/MCP (no host/user/secrets)."""

    id: UUID
    alias: str
    status: SessionStatus
    host_id: UUID
    address_id: UUID
    credential_id: UUID
    target: SessionTarget
    mcp_enabled: bool = False
    mcp_client_connected: bool = False
    # Standing permission: MCP may session_write / scripts_run.
    approve_enabled: bool = False
    created_at: datetime = field(default_factory=_utcnow)

    def __repr__(self) -> str:
        return (
            f"SessionInfo(id={self.id!r}, alias={self.alias!r}, "
            f"status={self.status.value!r}, target={self.target.value!r})"
        )


def new_session_id() -> UUID:
    return uuid4()
