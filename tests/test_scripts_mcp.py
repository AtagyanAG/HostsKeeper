"""Scripts MCP CRUD/run and placeholder rendering."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.scripts_render import render_script
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.vault import (
    Address,
    Credential,
    Host,
    Script,
    ScriptParameter,
    Vault,
)
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


def test_render_user_values() -> None:
    script = Script(
        name="x",
        body="echo {{iface}}",
        parameters=[
            ScriptParameter(
                name="iface",
                required=False,
                default="lo",
                user_value="eth0",
            )
        ],
    )
    assert render_script(script, {}) == "echo lo"
    assert render_script(script, {}, use_user_values=True) == "echo eth0"
    assert render_script(script, {"iface": "wlan0"}, use_user_values=True) == "echo eth0"

    empty = Script(
        name="y",
        body="echo {{iface}}",
        parameters=[
            ScriptParameter(name="iface", required=True, user_value=""),
        ],
    )
    assert render_script(empty, {}, use_user_values=True) == "echo "

    missing = Script(
        name="z",
        body="echo {{iface}}",
        parameters=[ScriptParameter(name="iface", required=True, default="lo")],
    )
    with pytest.raises(McpToolError) as exc:
        render_script(missing, {}, use_user_values=True)
    assert exc.value.code == "missing_param"


def test_mcp_redacts_and_preserves_user_value(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "uv.vault", "test-pass")
    script = vault.add_script(
        Script(
            name="say",
            body="echo {{tag}}",
            parameters=[
                ScriptParameter(
                    name="tag",
                    required=True,
                    default="public",
                    user_value="secret-uv",
                )
            ],
        )
    )
    service = McpToolService(SessionManager(vault), vault)
    access = McpAccess(mode="stdio")

    listed = service.scripts_list(access)
    row = next(s for s in listed["scripts"] if s["name"] == "say")
    assert row["parameters"][0]["name"] == "tag"
    assert "user_value" not in row["parameters"][0]

    got = service.scripts_get(access, id=str(script.id))
    assert "user_value" not in got["parameters"][0]
    assert "secret-uv" not in str(got)

    # MCP cannot inject user_value; existing value for same name is kept.
    updated = service.scripts_update(
        access,
        id=str(script.id),
        parameters=[
            {
                "name": "tag",
                "required": True,
                "default": "public2",
                "user_value": "hacked",
            }
        ],
    )
    assert "user_value" not in updated["parameters"][0]
    stored = vault.get_script(script.id)
    assert stored.parameters[0].default == "public2"
    assert stored.parameters[0].user_value == "secret-uv"

    created = service.scripts_create(
        access,
        name="other",
        body="echo {{x}}",
        parameters=[
            {
                "name": "x",
                "required": True,
                "default": "from-default",
                "user_value": "nope",
            }
        ],
    )
    assert "user_value" not in created["parameters"][0]
    other = vault.get_script_by_name("other")
    # Inbound user_value ignored; seeded from default on create.
    assert other.parameters[0].user_value == "from-default"


def test_scripts_list_scope_and_duplicate_name_requires_selector(
    tmp_path: Path,
) -> None:
    vault = Vault.create(tmp_path / "duplicate.vault", "test-pass")
    host = vault.add_host(Host(name="lab"))
    template = vault.add_script(Script(name="deploy", body="echo template"))
    host_script = vault.add_script(
        Script(name="deploy", body="echo host", host_id=host.id)
    )
    sessions = SessionManager(vault)
    session = SessionInfo(
        id=uuid4(),
        alias="lab-user-1",
        status=SessionStatus.LIVE,
        host_id=host.id,
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
    )
    sessions.list_mcp_sessions = lambda: [session]
    service = McpToolService(sessions, vault)
    access = McpAccess(mode="stdio")

    listed = service.scripts_list(access)["scripts"]
    by_id = {entry["id"]: entry for entry in listed}
    assert by_id[str(template.id)]["scope"] == "template"
    assert by_id[str(template.id)]["host_alias"] is None
    assert by_id[str(host_script.id)]["scope"] == "host"
    assert by_id[str(host_script.id)]["host_alias"] == "lab-user-1"

    with pytest.raises(McpToolError, match="ambiguous script name") as exc:
        service.scripts_get(access, name="deploy")
    assert exc.value.code == "invalid_args"
    assert service.scripts_get(access, id=str(host_script.id))["id"] == str(
        host_script.id
    )


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
