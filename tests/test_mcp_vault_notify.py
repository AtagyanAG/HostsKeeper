"""MCP vault mutations notify UI callback."""

from __future__ import annotations

from pathlib import Path

from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.vault import Vault


def test_scripts_create_notifies_vault_changed(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "n.vault", "pass")
    sessions = SessionManager(vault)
    hits: list[str] = []
    service = McpToolService(
        sessions, vault, on_vault_changed=lambda: hits.append("x")
    )
    access = McpAccess(mode="stdio")
    created = service.scripts_create(access, name="tpl", body="echo ok")
    assert created["name"] == "tpl"
    assert hits == ["x"]

    service.scripts_update(access, id=created["id"], body="echo 2")
    assert hits == ["x", "x"]

    service.scripts_delete(access, id=created["id"])
    assert hits == ["x", "x", "x"]


def test_groups_crud_notifies(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "g.vault", "pass")
    sessions = SessionManager(vault)
    hits: list[int] = []
    service = McpToolService(sessions, vault)
    service.set_vault_changed_callback(lambda: hits.append(1))
    access = McpAccess(mode="stdio")
    g = service.groups_create(access, name="sec", kind="scripts")
    service.groups_update(access, id=g["id"], name="security")
    service.groups_delete(access, id=g["id"])
    assert hits == [1, 1, 1]


def test_notify_exception_swallowed(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "e.vault", "pass")
    sessions = SessionManager(vault)

    def boom() -> None:
        raise RuntimeError("ui down")

    service = McpToolService(sessions, vault, on_vault_changed=boom)
    access = McpAccess(mode="stdio")
    # Must not raise despite callback failure.
    service.scripts_create(access, name="ok", body="true")
