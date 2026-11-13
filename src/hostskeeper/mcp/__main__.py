"""Run HostsKeeper MCP over stdio (requires process wiring by host app)."""

from __future__ import annotations

import asyncio
import os
import sys

from hostskeeper.mcp.context import set_access
from hostskeeper.mcp.server import build_mcp_server
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.vault import Vault


def main() -> int:
    vault_path = os.environ.get("HOSTSKEEPER_VAULT") or os.environ.get(
        "HOSTSSAFE_VAULT"
    )
    password = os.environ.get("HOSTSKEEPER_VAULT_PASSWORD") or os.environ.get(
        "HOSTSSAFE_VAULT_PASSWORD"
    )
    if not vault_path or not password:
        print(
            "HOSTSKEEPER_VAULT and HOSTSKEEPER_VAULT_PASSWORD are required for stdio MCP",
            file=sys.stderr,
        )
        return 2
    vault = Vault(vault_path)
    vault.unlock(password)
    # SessionManager must be shared with the UI process in production.
    # Stdio standalone entry is a stub until the app hosts both.
    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault)
    set_access(McpAccess(mode="stdio"))
    mcp = build_mcp_server(service)
    asyncio.run(mcp.run_stdio_async())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
