"""MCP tool service: scope, secrets, client_busy, read/write."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.http_app import create_http_app
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session import SessionManager, SessionStatus
from hostskeeper.vault import Address, Credential, Host, Vault
from tests.lab_env import (
    HOST,
    KEY_PATH,
    PORT,
    USER,
    VAULT_HOST_NAME,
    lab_key_available,
)

pytestmark = pytest.mark.skipif(
    not lab_key_available(),
    reason="set HOSTSKEEPER_TEST_SSH_KEY to a readable private key for live SSH tests",
)


FORBIDDEN_FRAGMENTS = [
    HOST,
    "BEGIN",
    "PRIVATE",
]


@pytest.fixture()
def lab_stack(tmp_path: Path) -> tuple[Vault, SessionManager, McpToolService]:
    vault = Vault.create(tmp_path / "mcp.vault", "test-pass")
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
    return vault, sessions, service


def _assert_no_secrets(payload: dict) -> None:
    blob = json.dumps(payload, ensure_ascii=False)
    for frag in FORBIDDEN_FRAGMENTS:
        assert frag not in blob
    assert "password" not in blob.lower() or '"password"' not in blob
    # username may appear inside alias; address/IP must not


def test_stdio_list_read_write_and_secrets(lab_stack) -> None:
    vault, sessions, service = lab_stack
    host = vault.list_hosts()[0]
    info = sessions.open_tab(
        host_id=host.id,
        address_id=host.default_address_id,
        credential_id=host.default_credential_id,
    )
    token = sessions.enable_mcp(info.id)
    assert token
    sessions.set_approve(info.id, enabled=True)
    access = McpAccess(mode="stdio")

    listed = service.session_list(access)
    _assert_no_secrets(listed)
    assert listed["sessions"][0]["alias"] == info.alias

    meta = service.session_info(access, alias=info.alias)
    _assert_no_secrets(meta)
    assert meta["alias"] == info.alias
    assert meta["status"] == SessionStatus.LIVE.value
    assert meta["approve_enabled"] is True

    marker = "hostskeeper-mcp-stdio"
    written = service.session_write(access, text=f"echo {marker}", alias=info.alias)
    _assert_no_secrets(written)
    got = sessions.wait_for_output(info.id, marker, timeout=15.0)
    assert marker in got.data

    read = service.session_read(access, alias=info.alias, cursor="0")
    _assert_no_secrets(read)
    assert "BEGIN" not in read["data"]

    sessions.close(info.id)


def test_http_token_scope_and_client_busy(lab_stack) -> None:
    vault, sessions, service = lab_stack
    host = vault.list_hosts()[0]
    info = sessions.open_tab(
        host_id=host.id,
        address_id=host.default_address_id,
        credential_id=host.default_credential_id,
    )
    token = sessions.enable_mcp(info.id)
    url = sessions.mcp_url(info.id, host="127.0.0.1", port=8765)
    assert token in url
    assert info.alias

    http_access = McpAccess(mode="http", token=token, client_id="c1")
    service.bind_http_client(token, "c1")
    meta = service.session_info(http_access)
    assert meta["alias"] == info.alias
    _assert_no_secrets(meta)

    with pytest.raises(McpToolError) as busy:
        service.bind_http_client(token, "c2")
    assert busy.value.code == "client_busy"

    service.unbind_http_client(token, "c1")
    service.bind_http_client(token, "c2")
    service.unbind_http_client(token, "c2")

    # HTTP middleware busy check
    app = create_http_app(service)
    with TestClient(app) as client:
        r1 = client.get("/mcp", params={"token": token}, headers={"x-hostskeeper-hold": "1", "x-hostskeeper-client-id": "h1"})
        # May be 406/404/400 depending on MCP negotiate; must not be unauthorized if token ok.
        assert r1.status_code != 401
        r2 = client.get(
            "/mcp",
            params={"token": token},
            headers={"x-hostskeeper-hold": "1", "x-hostskeeper-client-id": "h2"},
        )
        assert r2.status_code == 409
        assert r2.json()["error"] == "client_busy"
        service.unbind_http_client(token, "h1")

    sessions.set_approve(info.id, enabled=True)
    marker = "hostskeeper-mcp-http"
    service.session_write(
        McpAccess(mode="http", token=token), text=f"echo {marker}", submit=True
    )
    sessions.wait_for_output(info.id, marker, timeout=15.0)
    sessions.close(info.id)


def test_disconnected_error(lab_stack) -> None:
    vault, sessions, service = lab_stack
    host = vault.list_hosts()[0]
    info = sessions.open_tab(
        host_id=host.id,
        address_id=host.default_address_id,
        credential_id=host.default_credential_id,
    )
    sessions.enable_mcp(info.id)
    sessions.disconnect(info.id)
    with pytest.raises(McpToolError) as exc:
        service.session_write(McpAccess(mode="stdio"), text="echo x", alias=info.alias)
    assert exc.value.code == "disconnected"
    sessions.close(info.id)
