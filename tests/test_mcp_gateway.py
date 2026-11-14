"""HTTP MCP gateway (stable app key) without lab SSH."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from starlette.testclient import TestClient

from hostskeeper.mcp.app_key import (
    cursor_mcp_config,
    mcp_gateway_url,
    resolve_mcp_key,
    rotate_mcp_key,
)
from hostskeeper.mcp.http_app import create_http_app
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session.manager import SessionManager, _SessionState
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.vault import Vault


APP_KEY = "test-gateway-key-abc"


def _inject_live_mcp_session(sessions: SessionManager, *, alias: str) -> SessionInfo:
    sid = uuid4()
    info = SessionInfo(
        id=sid,
        alias=alias,
        status=SessionStatus.LIVE,
        host_id=uuid4(),
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    state = _SessionState(info=info, mcp_token="tab-token-" + alias)
    with sessions._lock:
        sessions._sessions[sid] = state
    return info


def test_resolve_mcp_key_file(tmp_path: Path) -> None:
    path = tmp_path / "mcp.key"
    k1 = resolve_mcp_key(key_path=path)
    assert path.is_file()
    k2 = resolve_mcp_key(key_path=path)
    assert k1 == k2
    assert resolve_mcp_key(explicit="override", key_path=path) == "override"


def test_rotate_mcp_key_file(tmp_path: Path) -> None:
    path = tmp_path / "mcp.key"
    k1 = resolve_mcp_key(key_path=path)
    k2 = rotate_mcp_key(key_path=path)
    assert k2 != k1
    assert resolve_mcp_key(key_path=path) == k2


def test_gateway_url_and_cursor_snippet() -> None:
    url = mcp_gateway_url(host="127.0.0.1", port=8765, key=APP_KEY)
    assert url == f"http://127.0.0.1:8765/mcp?key={APP_KEY}"
    snip = cursor_mcp_config(host="127.0.0.1", port=8765, key=APP_KEY)
    assert '"url"' in snip
    assert APP_KEY in snip
    assert "token=" not in snip


def test_gateway_list_attach_and_middleware(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "g.vault", "pass")
    sessions = SessionManager(vault)
    a = _inject_live_mcp_session(sessions, alias="lab-a-1")
    b = _inject_live_mcp_session(sessions, alias="lab-b-1")
    service = McpToolService(sessions, vault, app_key=APP_KEY)

    access = McpAccess(mode="http", client_id="cursor-1", gateway=True)
    listed = service.session_list(access)
    aliases = {s["alias"] for s in listed["sessions"]}
    assert aliases == {"lab-a-1", "lab-b-1"}

    pinned = service.session_attach(access, alias="lab-b-1")
    assert pinned["ok"] is True
    assert pinned["alias"] == "lab-b-1"
    assert pinned["pinned"] is True

    meta = service.session_info(access)
    assert meta["alias"] == "lab-b-1"
    assert meta["session_id"] == str(b.id)

    # Wrong key / no auth
    app = create_http_app(service, host="0.0.0.0")
    with TestClient(app) as client:
        r0 = client.get("/mcp")
        assert r0.status_code == 401
        r1 = client.get("/mcp", params={"key": "wrong"})
        assert r1.status_code == 401
        # Valid key: not unauthorized (MCP negotiate may be 4xx for GET, but not 401)
        r2 = client.get("/mcp", params={"key": APP_KEY})
        assert r2.status_code != 401
        # Header auth
        r3 = client.get("/mcp", headers={"X-HostsKeeper-Key": APP_KEY})
        assert r3.status_code != 401
        # LAN Host must not be rejected (DNS rebinding allowlist)
        r_lan = client.get(
            "/mcp",
            params={"key": APP_KEY},
            headers={"Host": "192.0.2.50:8765"},
        )
        assert r_lan.status_code != 421
        assert r_lan.status_code != 401
        # Legacy tab token still works and scopes to one session
        r4 = client.get(
            "/mcp",
            params={"token": "tab-token-lab-a-1"},
            headers={"x-hostskeeper-hold": "1", "x-hostskeeper-client-id": "legacy-1"},
        )
        assert r4.status_code != 401
        service.unbind_http_client("tab-token-lab-a-1", "legacy-1")

    # Legacy access still single-session
    legacy = McpAccess(mode="http", token="tab-token-lab-a-1", client_id="c")
    only = service.session_list(legacy)
    assert len(only["sessions"]) == 1
    assert only["sessions"][0]["alias"] == a.alias
