"""Legacy FastAPI UI module — retired after PySide6 migration (stage 14).

MCP HTTP: ``hostskeeper.runtime.mcp_http`` / ``hostskeeper.mcp.http_app``.
Desktop: ``python -m hostskeeper``.
"""

from __future__ import annotations

from pathlib import Path

from hostskeeper.api.state import AppState

DEFAULT_VAULT = Path.home() / ".hostskeeper" / "default.vault"
_state = AppState(vault_path=DEFAULT_VAULT)


def get_state() -> AppState:
    return _state


def create_app(state: AppState | None = None) -> None:
    raise RuntimeError(
        "Browser UI (FastAPI+static) was retired in stage 14. "
        "Run: python -m hostskeeper   # PySide6 desktop"
    )
