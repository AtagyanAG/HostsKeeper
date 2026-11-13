"""MCP HTTP runtime start/stop frees the bind port."""

from __future__ import annotations

import socket
from pathlib import Path

from hostskeeper.runtime.mcp_http import McpHttpRuntime
from hostskeeper.runtime.state import AppState


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def test_mcp_http_stop_releases_port(tmp_path: Path) -> None:
    port = _free_port()
    state = AppState(vault_path=tmp_path / "rt.vault", mcp_host="127.0.0.1", mcp_port=port)
    state.unlock("rt-pass")
    assert state.mcp_service is not None

    runtime = McpHttpRuntime()
    runtime.ensure_started(state.mcp_service, "127.0.0.1", port)
    assert runtime.running
    assert _port_in_use(port)

    runtime.stop(timeout=5.0)
    assert not runtime.running
    assert not _port_in_use(port)

    # Restart after stop must succeed on the same port.
    runtime.ensure_started(state.mcp_service, "127.0.0.1", port)
    assert runtime.running
    assert _port_in_use(port)
    runtime.stop(timeout=5.0)
    assert not _port_in_use(port)
