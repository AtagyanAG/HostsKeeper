"""Approve standing permission for MCP session_write / scripts_run."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.vault import Host, Vault


def _live_info(*, approve_enabled: bool, host_id=None) -> SessionInfo:
    return SessionInfo(
        id=uuid4(),
        alias="host-user-1",
        status=SessionStatus.LIVE,
        host_id=host_id or uuid4(),
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        approve_enabled=approve_enabled,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def service(tmp_path) -> tuple[SessionManager, McpToolService]:
    vault = Vault.create(tmp_path / "approve.vault", "test-pass")
    sessions = SessionManager(vault)
    return sessions, McpToolService(sessions, vault)


def test_write_denied_when_approve_off(service, monkeypatch) -> None:
    sessions, svc = service
    info = _live_info(approve_enabled=False)
    monkeypatch.setattr(svc, "_resolve_session", lambda *a, **k: info)
    wrote: list[str] = []
    monkeypatch.setattr(
        sessions, "write", lambda *a, **k: wrote.append("x")
    )
    with pytest.raises(McpToolError) as exc:
        svc.session_write(McpAccess(mode="stdio"), text="echo no", alias=info.alias)
    assert exc.value.code == "approve_required"
    assert wrote == []


def test_write_allowed_when_approve_on(service, monkeypatch) -> None:
    sessions, svc = service
    info = _live_info(approve_enabled=True)
    monkeypatch.setattr(svc, "_resolve_session", lambda *a, **k: info)
    wrote: list[tuple[str, bool]] = []

    def _write(session_id, text, *, submit=False):
        wrote.append((text, submit))

    monkeypatch.setattr(sessions, "write", _write)
    out = svc.session_write(
        McpAccess(mode="stdio"), text="echo ok", alias=info.alias, submit=True
    )
    assert out["ok"] is True
    assert wrote == [("echo ok", True)]


def test_set_approve_toggles_enabled(service) -> None:
    sessions, _svc = service
    host = sessions._vault.add_host(Host(name="lab", mcp_enabled=True))
    # Inject a closed-enough session state without SSH.
    info = _live_info(approve_enabled=False, host_id=host.id)
    from hostskeeper.session.manager import _SessionState

    with sessions._lock:
        sessions._sessions[info.id] = _SessionState(info=info)
    updated = sessions.set_approve(info.id, enabled=True)
    assert updated.approve_enabled is True
    updated = sessions.set_approve(info.id, enabled=False)
    assert updated.approve_enabled is False
    sessions.close(info.id)
