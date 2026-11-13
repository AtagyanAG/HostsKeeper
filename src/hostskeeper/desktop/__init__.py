"""PySide6 desktop UI for HostsKeeper."""

from __future__ import annotations

__all__ = ["run_desktop"]


def run_desktop(
    *,
    vault_path=None,
    mcp_host: str = "0.0.0.0",
    mcp_port: int = 8765,
    mcp_key: str | None = None,
) -> int:
    from hostskeeper.desktop.app import run_desktop as _run

    return _run(
        vault_path=vault_path,
        mcp_host=mcp_host,
        mcp_port=mcp_port,
        mcp_key=mcp_key,
    )
