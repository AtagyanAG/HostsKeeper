"""Host-scoped scripts and groups."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.vault import Group, Host, Script, Vault
from hostskeeper.vault.errors import ValidationError


def test_script_name_unique_per_host(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "h.vault", "pw")
    h1 = vault.add_host(Host(name="a"))
    h2 = vault.add_host(Host(name="b"))
    vault.add_script(Script(name="uptime", body="uptime", host_id=None))
    vault.add_script(Script(name="uptime", body="uptime -p", host_id=h1.id))
    vault.add_script(Script(name="uptime", body="uptime -s", host_id=h2.id))
    with pytest.raises(ValidationError):
        vault.add_script(Script(name="uptime", body="x", host_id=h1.id))
    assert len(vault.list_scripts(only_templates=True)) == 1
    assert len(vault.list_scripts(host_id=h1.id)) == 1


def test_delete_host_cascades_scripts_and_groups(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "c.vault", "pw")
    host = vault.add_host(Host(name="h"))
    g = vault.add_group(
        Group(name="ops", kind="scripts", host_id=host.id)
    )
    vault.add_script(
        Script(name="s", body="echo 1", host_id=host.id, group_id=g.id)
    )
    vault.delete_host(host.id)
    assert vault.list_scripts(host_id=host.id) == []
    assert vault.list_groups(kind="scripts", host_id=host.id) == []


def test_mcp_host_script_visibility_without_tab(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "m.vault", "pw")
    host = vault.add_host(Host(name="h"))
    vault.add_script(
        Script(name="tpl", body="echo t", host_id=None, mcp_enabled=True)
    )
    vault.add_script(
        Script(name="local", body="echo h", host_id=host.id, mcp_enabled=True)
    )
    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault)
    stdio = McpAccess(mode="stdio")
    listed = service.scripts_list(stdio)["scripts"]
    names = {s["name"] for s in listed}
    assert "tpl" in names
    assert "local" not in names
    with pytest.raises(McpToolError) as err:
        service.scripts_create(
            stdio, name="x", body="echo", host_id=str(host.id)
        )
    assert err.value.code == "client_scope"


def test_group_host_id_mismatch_rejected(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "g.vault", "pw")
    host = vault.add_host(Host(name="h"))
    other = uuid4()
    with pytest.raises(ValidationError):
        vault.add_group(
            Group(name="x", kind="scripts", host_id=other)
        )
    g = vault.add_group(Group(name="ok", kind="scripts", host_id=host.id))
    with pytest.raises(ValidationError):
        vault.add_script(
            Script(name="s", body="x", host_id=None, group_id=g.id)
        )
