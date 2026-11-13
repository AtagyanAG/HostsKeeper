"""Host Notes (profile) vault + MCP tools."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session.manager import SessionManager, _SessionState
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.vault import Host, Vault


def test_host_profile_persists(tmp_path) -> None:
    path = tmp_path / "p.vault"
    vault = Vault.create(path, "pass")
    host = vault.add_host(Host(name="lab", profile="OS: Linux\npython 3.12"))
    assert host.profile and "python 3.12" in host.profile
    vault.lock()
    vault.unlock("pass")
    loaded = vault.get_host(host.id)
    assert loaded.profile == "OS: Linux\npython 3.12"


def test_host_profile_mcp_get_set(tmp_path) -> None:
    vault = Vault.create(tmp_path / "m.vault", "pass")
    host = vault.add_host(Host(name="lab"))
    sessions = SessionManager(vault)
    sid = uuid4()
    info = SessionInfo(
        id=sid,
        alias="lab-user-1",
        status=SessionStatus.LIVE,
        host_id=host.id,
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    with sessions._lock:
        sessions._sessions[sid] = _SessionState(info=info)

    service = McpToolService(sessions, vault)
    access = McpAccess(mode="stdio")

    got = service.host_profile_get(access, alias=info.alias)
    assert got["present"] is False
    assert got["profile"] == ""

    set_out = service.host_profile_set(
        access, profile="docker 24\nnpm 10", alias=info.alias
    )
    assert set_out["ok"] is True
    assert set_out["present"] is True

    got2 = service.host_profile_get(access, host_id=str(host.id))
    assert "docker 24" in got2["profile"]

    meta = service.session_info(access, alias=info.alias)
    assert meta["host_id"] == str(host.id)
    assert meta["host_profile_present"] is True
    assert meta["host_profile_chars"] > 0
    assert "host_profile_get" in meta["host_profile_hint"]

    sessions.close(sid)


def test_host_profile_requires_mcp_scope(tmp_path) -> None:
    vault = Vault.create(tmp_path / "n.vault", "pass")
    host = vault.add_host(Host(name="lab", profile="x"))
    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault)
    with pytest.raises(McpToolError) as exc:
        service.host_profile_get(McpAccess(mode="stdio"), host_id=str(host.id))
    assert exc.value.code == "not_found"
