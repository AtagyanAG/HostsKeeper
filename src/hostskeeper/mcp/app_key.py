"""Stable LAN MCP app key (Cursor mcp.json — без per-tab token)."""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from urllib.parse import quote


DEFAULT_KEY_PATH = Path.home() / ".hostskeeper" / "mcp.key"
_LEGACY_KEY_PATH = Path.home() / ".hostssafe" / "mcp.key"


def resolve_mcp_key(
    *,
    explicit: str | None = None,
    key_path: Path | None = None,
) -> str:
    """Resolve app key: CLI/explicit → env → file (create if missing)."""
    if explicit and explicit.strip():
        return explicit.strip()
    for env_name in ("HOSTSKEEPER_MCP_KEY", "HOSTSSAFE_MCP_KEY"):
        env = os.environ.get(env_name, "").strip()
        if env:
            return env
    if key_path is not None:
        candidates = [key_path]
    else:
        candidates = [DEFAULT_KEY_PATH, _LEGACY_KEY_PATH]
    for path in candidates:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    path = key_path or DEFAULT_KEY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(24)
    path.write_text(value + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def keys_match(provided: str | None, expected: str) -> bool:
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def mcp_gateway_url(*, host: str, port: int, key: str) -> str:
    """Stable Cursor URL (query key)."""
    return f"http://{host}:{port}/mcp?key={quote(key, safe='')}"


def cursor_mcp_config(*, host: str, port: int, key: str, name: str = "hostskeeper") -> str:
    """Snippet for Cursor mcp.json (url only — no per-tab edits)."""
    url = mcp_gateway_url(host=host, port=port, key=key)
    # Compact JSON suitable for clipboard.
    return (
        '{\n'
        f'  "mcpServers": {{\n'
        f'    "{name}": {{\n'
        f'      "url": "{url}"\n'
        f'    }}\n'
        f'  }}\n'
        f'}}\n'
    )
