"""MCP notes_* tools (mcp_enabled gate, no Approve)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session.manager import SessionManager
from hostskeeper.vault import Group, Note, Vault


def test_notes_mcp_gate_and_crud(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "n.vault", "pw")
    group = vault.add_group(Group(name="Docs", kind="scripts"))
    hidden = vault.add_note(
        Note(name="secret", body="no", group_id=group.id, mcp_enabled=False)
    )
    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault, app_key="k")
    access = McpAccess(mode="stdio")

    listed = service.notes_list(access)
    assert listed["notes"] == []

    created = service.notes_create(
        access, name="runbook", body="# Steps", group_id=str(group.id)
    )
    assert created["mcp_enabled"] is True
    assert created["name"] == "runbook"

    listed = service.notes_list(access)
    assert len(listed["notes"]) == 1
    assert listed["notes"][0]["name"] == "runbook"

    got = service.notes_get(access, id=created["id"])
    assert got["body"] == "# Steps"

    with pytest.raises(McpToolError, match="not found"):
        service.notes_get(access, id=str(hidden.id))

    updated = service.notes_update(
        access, id=created["id"], body="## Updated", new_name="runbook2"
    )
    assert updated["body"] == "## Updated"
    assert updated["name"] == "runbook2"
    assert updated["mcp_enabled"] is True

    deleted = service.notes_delete(access, id=created["id"])
    assert deleted["ok"] is True
    assert service.notes_list(access)["notes"] == []


def test_groups_delete_removes_notes(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "g.vault", "pw")
    group = vault.add_group(Group(name="G", kind="scripts"))
    vault.add_note(Note(name="n1", body="x", group_id=group.id, mcp_enabled=True))
    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault, app_key="k")
    access = McpAccess(mode="stdio")
    out = service.groups_delete(access, id=str(group.id))
    assert out["ok"] is True
    assert out["deleted"]["notes"] == 1
    assert vault.list_notes() == []
