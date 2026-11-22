from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session.manager import SessionManager, _SessionState
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.vault import Address, Credential, Group, Host, Note, Script, Vault


def test_groups_list_hosts_only_returns_groups_with_accessible_hosts(tmp_path) -> None:
    vault = Vault.create(tmp_path / "host-groups.vault", "pw")
    root = vault.add_group(Group(name="root", kind="hosts"))
    nested = vault.add_group(Group(name="nested", kind="hosts", parent_id=root.id))
    hidden_only = vault.add_group(Group(name="hidden", kind="hosts"))
    vault.add_group(Group(name="empty", kind="hosts"))
    vault.add_host(Host(name="visible", group_id=nested.id, mcp_enabled=True))
    vault.add_host(Host(name="hidden", group_id=hidden_only.id))
    vault.add_host(Host(name="ungrouped", mcp_enabled=True))
    service = McpToolService(SessionManager(vault), vault)

    listed = service.groups_list(McpAccess(mode="stdio"), kind="hosts")

    assert [group["id"] for group in listed["groups"]] == [
        str(root.id),
        str(nested.id),
    ]


def test_host_data_and_resources_require_host_and_resource_flags(tmp_path) -> None:
    vault = Vault.create(tmp_path / "host-scope.vault", "pw")
    host = vault.add_host(Host(name="lab", profile="Linux"))
    visible_script = vault.add_script(
        Script(name="visible", body="true", host_id=host.id, mcp_enabled=True)
    )
    hidden_script = vault.add_script(
        Script(name="hidden", body="true", host_id=host.id, mcp_enabled=False)
    )
    visible_note = vault.add_note(
        Note(name="visible-note", body="text", host_id=host.id, mcp_enabled=True)
    )
    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault)
    access = McpAccess(mode="stdio")

    assert service.scripts_list(access)["scripts"] == []
    assert service.notes_list(access)["notes"] == []
    with pytest.raises(McpToolError) as disabled:
        service.host_profile_get(access, host_id=str(host.id))
    assert disabled.value.code == "not_found"

    host.mcp_enabled = True
    vault.update_host(host)

    assert [
        item["id"] for item in service.scripts_list(access)["scripts"]
    ] == [str(visible_script.id)]
    assert [
        item["id"] for item in service.notes_list(access)["notes"]
    ] == [str(visible_note.id)]
    assert service.host_profile_get(access, host_id=str(host.id))["profile"] == "Linux"
    assert vault.get_script(hidden_script.id).mcp_enabled is False


def test_disabling_host_revokes_legacy_token_and_approve(tmp_path) -> None:
    vault = Vault.create(tmp_path / "legacy-token.vault", "pw")
    host = vault.add_host(Host(name="lab", mcp_enabled=True))
    sessions = SessionManager(vault)
    info = SessionInfo(
        id=uuid4(),
        alias="lab-admin-1",
        status=SessionStatus.CONNECTING,
        host_id=host.id,
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        approve_enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    with sessions._lock:
        sessions._sessions[info.id] = _SessionState(
            info=info, mcp_token="legacy-token"
        )
    service = McpToolService(sessions, vault)
    access = McpAccess(mode="http", token="legacy-token")

    assert service.session_list(access)["sessions"][0]["session_id"] == str(info.id)

    host.mcp_enabled = False
    vault.update_host(host)
    sessions.sync_host_mcp_access(host.id)

    revoked = sessions.get(info.id)
    assert revoked.mcp_enabled is False
    assert revoked.approve_enabled is False
    with pytest.raises(McpToolError) as denied:
        service.session_list(access)
    assert denied.value.code == "unauthorized"


def test_new_tab_inherits_host_mcp_permission(tmp_path, monkeypatch) -> None:
    vault = Vault.create(tmp_path / "new-tab.vault", "pw")
    host = vault.add_host(Host(name="lab", mcp_enabled=True))
    address = vault.add_address(Address(host_id=host.id, host="example.test"))
    credential = vault.add_credential(
        Credential(host_id=host.id, username="admin", password="pw")
    )
    sessions = SessionManager(vault)
    monkeypatch.setattr(sessions, "_connect_state", lambda state, **kwargs: None)

    info = sessions.open_tab(
        host_id=host.id, address_id=address.id, credential_id=credential.id
    )

    assert info.mcp_enabled is True
    assert sessions.mcp_url(info.id, host="127.0.0.1", port=8765).startswith(
        "http://127.0.0.1:8765/mcp?token="
    )
    sessions.close(info.id)
