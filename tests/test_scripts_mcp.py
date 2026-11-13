"""Scripts MCP CRUD/run and placeholder rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.scripts_render import render_script
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.vault import Address, Credential, Host, Script, ScriptParameter, Vault
from tests.lab_env import (
    HOST,
    KEY_PATH,
    PORT,
    USER,
    VAULT_HOST_NAME,
    lab_key_available,
)


def test_render_missing_and_unknown() -> None:
    script = Script(
        name="x",
        body="echo {{iface}} {{missing}}",
        parameters=[ScriptParameter(name="iface", required=True)],
    )
    with pytest.raises(McpToolError) as missing:
        render_script(script, {})
    assert missing.value.code == "missing_param"
    with pytest.raises(McpToolError) as unknown:
        render_script(script, {"iface": "eth0"})
    assert unknown.value.code == "unknown_placeholder"


def test_render_defaults() -> None:
    script = Script(
        name="x",
        body="echo {{iface}}",
        parameters=[ScriptParameter(name="iface", required=False, default="lo")],
    )
    assert render_script(script, {}) == "echo lo"


@pytest.mark.skipif(
    not lab_key_available(),
    reason="set HOSTSKEEPER_TEST_SSH_KEY to a readable private key for live SSH tests",
)
def test_scripts_create_run_http_scope(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "scripts.vault", "test-pass")
    host = vault.add_host(Host(name=VAULT_HOST_NAME))
    address = vault.add_address(
        Address(host_id=host.id, host=HOST, port=PORT, label="lan")
    )
    credential = vault.add_credential(
        Credential(
            host_id=host.id,
            username=USER,
            private_key=KEY_PATH.read_text(encoding="utf-8"),
        )
    )
    host.default_address_id = address.id
    host.default_credential_id = credential.id
    vault.update_host(host)

    sessions = SessionManager(vault)
    service = McpToolService(sessions, vault)
    info = sessions.open_tab(
        host_id=host.id,
        address_id=address.id,
        credential_id=credential.id,
    )
    token = sessions.enable_mcp(info.id)
    sessions.set_approve(info.id, enabled=True)
    stdio = McpAccess(mode="stdio")
    http = McpAccess(mode="http", token=token)

    created = service.scripts_create(
        stdio,
        name="say",
        body="echo hostskeeper-{{tag}}",
        parameters=[
            {
                "name": "tag",
                "required": True,
                "description": "marker",
            }
        ],
    )
    assert created["name"] == "say"
    listed = service.scripts_list(http)
    assert any(s["name"] == "say" for s in listed["scripts"])

    marker = "scripts-ok"
    service.scripts_run(
        http,
        name="say",
        params={"tag": marker},
    )
    got = sessions.wait_for_output(info.id, f"hostskeeper-{marker}", timeout=15.0)
    assert f"hostskeeper-{marker}" in got.data

    # HTTP cannot target another session id
    with pytest.raises(McpToolError) as scope:
        service.scripts_run(
            http,
            name="say",
            params={"tag": "x"},
            session_id="00000000-0000-0000-0000-000000000099",
        )
    assert scope.value.code == "client_scope"

    service.scripts_delete(stdio, name="say")
    sessions.close(info.id)
