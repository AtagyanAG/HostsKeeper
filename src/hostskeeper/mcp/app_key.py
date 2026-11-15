"""Stable LAN MCP app key (VS Code HTTP config; no per-tab token)."""

from __future__ import annotations

import hmac
import json
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
    return _write_new_key(path)


def mcp_key_file_path() -> Path:
    """Path used for file-backed key (prefer HostsKeeper; else legacy if present)."""
    if DEFAULT_KEY_PATH.is_file() or not _LEGACY_KEY_PATH.is_file():
        return DEFAULT_KEY_PATH
    return _LEGACY_KEY_PATH


def rotate_mcp_key(*, key_path: Path | None = None) -> str:
    """Generate a new app key and overwrite the key file. Returns the new key."""
    path = key_path or mcp_key_file_path()
    return _write_new_key(path)


def _write_new_key(path: Path) -> str:
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
    """Legacy stable gateway URL with the app key in the query string."""
    return f"http://{host}:{port}/mcp?key={quote(key, safe='')}"


def vscode_mcp_config(
    *, host: str, port: int, key: str, name: str = "hostskeeper"
) -> str:
    """Return a VS Code MCP config using the app key as an HTTP header."""
    config = {
        "servers": {
            name: {
                "type": "http",
                "url": f"http://{host}:{port}/mcp",
                "headers": {"X-HostsKeeper-Key": key},
            }
        }
    }
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def cursor_mcp_config(
    *, host: str, port: int, key: str, name: str = "hostskeeper"
) -> str:
    """Compatibility alias for the former Cursor-named config generator."""
    return vscode_mcp_config(host=host, port=port, key=key, name=name)
