"""Scripts MCP CRUD/run and placeholder rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.scripts_render import analyze_script, render_script
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.session.manager import _SessionState
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


def test_analyze_script_reports_errors_warnings_and_safe_missing_values() -> None:
    analysis = analyze_script(
        "echo {{iface}} {{missing}} {{bad name}}",
        [
            ScriptParameter(
                name="iface",
                required=True,
                default="sensitive-default",
            ),
            ScriptParameter(name="unused", required=True),
        ],
    )
    result = analysis.to_dict()

    assert result["valid"] is False
    assert result["ready_to_run"] is False
    assert result["placeholders"][0] == {"name": "iface", "position": 5}
    assert {item["code"] for item in result["errors"]} == {
        "malformed_placeholder",
        "unknown_placeholder",
    }
    malformed_position = len("echo {{iface}} {{missing}} ")
    assert {
        item["position"]
        for item in result["errors"]
        if item["code"] == "malformed_placeholder"
    } == {malformed_position}
    assert result["warnings"] == [{"code": "unused_parameter", "name": "unused"}]
    assert "sensitive-default" not in str(result)

    missing = analyze_script(
        "echo {{token}}",
        [ScriptParameter(name="token", required=True)],
    ).to_dict()
    assert missing["valid"] is True
    assert missing["ready_to_run"] is False
    assert missing["missing_parameters"] == ["token"]

    invalid_parameters = analyze_script(
        "echo ready",
        [
            ScriptParameter(name="invalid-name"),
            ScriptParameter(name="duplicate"),
            ScriptParameter(name="duplicate"),
        ],
    ).to_dict()
    assert {item["code"] for item in invalid_parameters["errors"]} == {
        "invalid_parameter_name",
        "duplicate_parameter",
    }


def test_unused_required_parameters_do_not_block_rendering() -> None:
    script = Script(
        name="x",
        body="echo ready",
        parameters=[ScriptParameter(name="unused", required=True)],
    )

    assert render_script(script) == "echo ready"


def test_scripts_validate_and_validate_before_saving(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "validate.vault", "test-pass")
    service = McpToolService(SessionManager(vault), vault)
    access = McpAccess(mode="stdio")

    ready = service.scripts_validate(
        access,
        body="echo {{token}}",
        parameters=[
            {
                "name": "token",
                "required": True,
                "default": "sensitive-default",
            }
        ],
        params={"token": "sensitive-input"},
    )
    assert ready["valid"] is True
    assert ready["ready_to_run"] is True
    assert "sensitive-default" not in str(ready)
    assert "sensitive-input" not in str(ready)

    script = service.scripts_create(
        access,
        name="valid",
        body="echo {{iface}}",
        parameters=[{"name": "iface", "required": True}],
    )
    before = vault.get_script_by_name("valid")

    with pytest.raises(McpToolError) as create_error:
        service.scripts_create(
            access,
            name="invalid",
            body="echo {{missing}}",
        )
    assert create_error.value.code == "invalid_args"
    assert [item.name for item in vault.list_scripts()] == ["valid"]

    with pytest.raises(McpToolError) as malformed_error:
        service.scripts_create(
            access,
            name="malformed",
            body="echo {{iface",
            parameters=[{"name": "iface", "required": True}],
        )
    assert malformed_error.value.code == "invalid_args"
    assert [item.name for item in vault.list_scripts()] == ["valid"]

    with pytest.raises(McpToolError) as update_error:
        service.scripts_update(
            access,
            id=script["id"],
            body="echo {{new_iface}}",
        )
    assert update_error.value.code == "invalid_args"
    assert vault.get_script(before.id).body == before.body

    updated = service.scripts_update(
        access,
        id=script["id"],
        body="echo {{new_iface}}",
        parameters=[{"name": "new_iface", "required": True}],
    )
    assert updated["body"] == "echo {{new_iface}}"
    assert updated["parameters"][0]["name"] == "new_iface"


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
            mcp_enabled=True,
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
    host = vault.add_host(Host(name="lab", mcp_enabled=True))
    hidden_host = vault.add_host(Host(name="hidden"))
    template = vault.add_script(
        Script(name="deploy", body="echo template", mcp_enabled=True)
    )
    host_script = vault.add_script(
        Script(
            name="deploy",
            body="echo host",
            mcp_enabled=True,
            description="host-specific deployment",
            parameters=[
                ScriptParameter(
                    name="port",
                    default="2222",
                    user_value="private-user-value",
                )
            ],
            host_id=host.id,
        )
    )
    hidden_script = vault.add_script(
        Script(
            name="private",
            body="echo hidden",
            host_id=hidden_host.id,
            mcp_enabled=True,
        )
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
    sessions.resolve_mcp_token = lambda token: session
    service = McpToolService(sessions, vault)
    access = McpAccess(mode="http", token="tab-token")

    listed = service.scripts_list(access)["scripts"]
    by_id = {entry["id"]: entry for entry in listed}
    assert by_id[str(template.id)]["scope"] == "template"
    assert by_id[str(template.id)]["host_alias"] is None
    assert by_id[str(host_script.id)]["scope"] == "host"
    assert by_id[str(host_script.id)]["host_alias"] == "lab-user-1"
    assert str(hidden_script.id) not in by_id
    for entry in listed:
        assert service.scripts_get(access, id=entry["id"])["id"] == entry["id"]

    before_template = vault.get_script(template.id).to_dict()
    before_host_script = vault.get_script(host_script.id).to_dict()
    compared = service.scripts_compare(
        access,
        left_script_id=str(template.id),
        right_script_id=str(host_script.id),
    )
    assert compared["left"] == {"id": str(template.id), "name": "deploy"}
    assert compared["right"] == {"id": str(host_script.id), "name": "deploy"}
    assert compared["metadata_differences"]["description"] == {
        "left": None,
        "right": "host-specific deployment",
    }
    assert (
        compared["metadata_differences"]["parameters"]["right"][0]["default"]
        == "2222"
    )
    assert "private-user-value" not in str(compared)
    assert f"-echo template\n+echo host\n" in compared["body_diff"]
    assert compared["body_diff_truncated"] is False
    assert vault.get_script(template.id).to_dict() == before_template
    assert vault.get_script(host_script.id).to_dict() == before_host_script

    with pytest.raises(McpToolError, match="ambiguous script name") as exc:
        service.scripts_get(access, name="deploy")
    assert exc.value.code == "invalid_args"

    unavailable_messages = []
    for script_id in (str(hidden_script.id), str(uuid4())):
        with pytest.raises(McpToolError) as unavailable:
            service.scripts_get(access, id=script_id)
        assert unavailable.value.code == "not_found"
        unavailable_messages.append(str(unavailable.value))
    assert unavailable_messages[0] == unavailable_messages[1]
    assert "refresh scripts_list" in unavailable_messages[0]
    assert "access to their host" in unavailable_messages[0]
    assert str(hidden_script.id) not in unavailable_messages[0]
    compare_errors = []
    for script_id in (str(hidden_script.id), str(uuid4())):
        with pytest.raises(McpToolError) as compare_unavailable:
            service.scripts_compare(
                access,
                left_script_id=str(host_script.id),
                right_script_id=script_id,
            )
        assert compare_unavailable.value.code == "not_found"
        compare_errors.append(str(compare_unavailable.value))
    assert compare_errors[0] == compare_errors[1]
    assert str(hidden_script.id) not in compare_errors[0]


def test_scripts_compare_bounds_body_diff(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "compare-large.vault", "test-pass")
    left = vault.add_script(
        Script(name="left", body=("left line\n" * 2500), mcp_enabled=True)
    )
    right = vault.add_script(
        Script(name="right", body=("right line\n" * 2500), mcp_enabled=True)
    )
    service = McpToolService(SessionManager(vault), vault)

    compared = service.scripts_compare(
        McpAccess(mode="stdio"),
        left_script_id=str(left.id),
        right_script_id=str(right.id),
    )

    assert compared["body_diff_truncated"] is True
    assert len(compared["body_diff"]) <= 20_000
    assert "diff truncated" in compared["body_diff"]


def test_scripts_visibility_flag_gates_mcp_access(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "visibility.vault", "test-pass")
    hidden = vault.add_script(
        Script(name="private", body="echo private", mcp_enabled=False)
    )
    visible = vault.add_script(
        Script(name="public", body="echo public", mcp_enabled=True)
    )
    sessions = SessionManager(vault)
    session = SessionInfo(
        id=uuid4(),
        alias="test-session",
        status=SessionStatus.LIVE,
        host_id=None,
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        approve_enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    with sessions._lock:
        sessions._sessions[session.id] = _SessionState(info=session)
    service = McpToolService(sessions, vault)
    access = McpAccess(mode="stdio")

    listed = service.scripts_list(access)["scripts"]
    assert [script["id"] for script in listed] == [str(visible.id)]
    assert listed[0]["mcp_enabled"] is True

    with pytest.raises(McpToolError) as get_error:
        service.scripts_get(access, id=str(hidden.id))
    assert get_error.value.code == "not_found"

    with pytest.raises(McpToolError) as compare_error:
        service.scripts_compare(
            access,
            left_script_id=str(hidden.id),
            right_script_id=str(visible.id),
        )
    assert compare_error.value.code == "not_found"

    with pytest.raises(McpToolError) as update_error:
        service.scripts_update(access, id=str(hidden.id), new_name="renamed")
    assert update_error.value.code == "not_found"

    with pytest.raises(McpToolError) as run_error:
        service.scripts_run(
            access,
            request_id=str(uuid4()),
            script_id=str(hidden.id),
            alias=session.alias,
        )
    assert run_error.value.code == "not_found"

    with pytest.raises(McpToolError) as delete_error:
        service.scripts_delete(access, id=str(hidden.id))
    assert delete_error.value.code == "not_found"
    assert vault.get_script(hidden.id).name == "private"

    created = service.scripts_create(access, name="from-mcp", body="echo ok")
    assert created["mcp_enabled"] is True
    assert vault.get_script_by_name("from-mcp").mcp_enabled is True


@pytest.mark.skipif(
    not lab_key_available(),
    reason="set HOSTSKEEPER_TEST_SSH_KEY to a readable private key for live SSH tests",
)
def test_scripts_create_run_http_scope(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "scripts.vault", "test-pass")
    host = vault.add_host(Host(name=VAULT_HOST_NAME, mcp_enabled=True))
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
    accepted = service.scripts_run(
        http,
        request_id=str(uuid4()),
        name="say",
        params={"tag": marker},
    )
    assert accepted["state"] == "accepted"
    result = service.scripts_run_wait(
        http,
        run_id=accepted["run_id"],
        timeout_sec=15,
    )
    assert result["state"] == "succeeded"
    assert f"hostskeeper-{marker}" in result["stdout"]["data"]

    # HTTP cannot target another session id
    with pytest.raises(McpToolError) as scope:
        service.scripts_run(
            http,
            request_id=str(uuid4()),
            name="say",
            params={"tag": "x"},
            session_id="00000000-0000-0000-0000-000000000099",
        )
    assert scope.value.code == "client_scope"

    service.scripts_delete(stdio, name="say")
    sessions.close(info.id)
