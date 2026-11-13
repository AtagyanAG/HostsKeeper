"""Process-wide app state for UI + MCP."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hostskeeper.mcp.app_key import resolve_mcp_key
from hostskeeper.mcp.service import McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.vault import Vault


@dataclass
class AppState:
    vault_path: Path
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8765
    mcp_key: str = ""
    vault: Vault | None = None
    sessions: SessionManager | None = None
    mcp_service: McpToolService | None = None

    def __post_init__(self) -> None:
        if not self.mcp_key:
            self.mcp_key = resolve_mcp_key()

    @property
    def unlocked(self) -> bool:
        return self.vault is not None and self.vault.is_unlocked

    def unlock(self, password: str) -> None:
        vault = Vault(self.vault_path)
        if not self.vault_path.exists():
            vault = Vault.create(self.vault_path, password)
        else:
            vault.unlock(password)
        self.vault = vault
        self.sessions = SessionManager(vault)
        self.mcp_service = McpToolService(
            self.sessions, vault, app_key=self.mcp_key
        )

    def lock(self) -> None:
        if self.sessions is not None:
            for s in list(self.sessions.list_sessions()):
                self.sessions.close(s.id)
        if self.vault is not None and self.vault.is_unlocked:
            self.vault.lock()
        self.vault = None
        self.sessions = None
        self.mcp_service = None

    def require_unlocked(self) -> tuple[Vault, SessionManager, McpToolService]:
        if (
            not self.unlocked
            or self.vault is None
            or self.sessions is None
            or self.mcp_service is None
        ):
            raise RuntimeError("vault_locked")
        return self.vault, self.sessions, self.mcp_service
