"""Headless smoke: Open Tab (SSH) + MCP HTTP like the Qt desktop path.

Uses the same AppState / ensure_mcp_http stack as PySide6.
Does not show GUI. Lab defaults match tests/test_session_ssh_integration.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
from pathlib import Path

# Ensure src on path when run as script
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from hostskeeper.runtime.mcp_http import ensure_mcp_http, stop_mcp_http  # noqa: E402
from hostskeeper.runtime.state import AppState  # noqa: E402
from hostskeeper.session.models import SessionStatus  # noqa: E402
from hostskeeper.vault import Address, Credential, Host  # noqa: E402

# Lab via env only — never hardcode private paths or site-specific hosts.
def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


HOST = _env("HOSTSKEEPER_TEST_SSH_HOST", "HOSTSSAFE_TEST_SSH_HOST", default="127.0.0.1")
PORT = int(_env("HOSTSKEEPER_TEST_SSH_PORT", "HOSTSSAFE_TEST_SSH_PORT", default="22"))
USER = _env("HOSTSKEEPER_TEST_SSH_USER", "HOSTSSAFE_TEST_SSH_USER", default="labuser")
KEY_PATH = Path(_env("HOSTSKEEPER_TEST_SSH_KEY", "HOSTSSAFE_TEST_SSH_KEY", default=""))
PASSWORD = _env("HOSTSKEEPER_TEST_SSH_PASSWORD", "HOSTSSAFE_TEST_SSH_PASSWORD")
VAULT_HOST_NAME = "lab-host"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _mcp_call(url: str, tool: str, arguments: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as streams:
        read, write = (
            (streams.read, streams.write)
            if hasattr(streams, "read")
            else (streams[0], streams[1])
        )
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            text = "".join(getattr(b, "text", "") for b in result.content)
            return json.loads(text)


def main() -> int:
    results: dict[str, str] = {}
    tmp = Path(tempfile.mkdtemp()) / "check.vault"
    mcp_port = _free_port()
    state = AppState(vault_path=tmp, mcp_host="127.0.0.1", mcp_port=mcp_port)
    state.unlock("check-tab-mcp")

    assert state.vault is not None and state.sessions is not None
    host = state.vault.add_host(Host(name=VAULT_HOST_NAME, tags=["lab"]))
    addr = state.vault.add_address(
        Address(host_id=host.id, host=HOST, port=PORT, label="lan")
    )
    if KEY_PATH.is_file():
        cred = state.vault.add_credential(
            Credential(
                host_id=host.id,
                username=USER,
                private_key=KEY_PATH.read_text(encoding="utf-8"),
                label="key",
            )
        )
        results["AUTH"] = "key"
    elif PASSWORD:
        cred = state.vault.add_credential(
            Credential(host_id=host.id, username=USER, password=PASSWORD, label="pw")
        )
        results["AUTH"] = "password"
    else:
        print("ERROR=no lab key and HOSTSKEEPER_TEST_SSH_PASSWORD unset")
        return 2

    host.default_address_id = addr.id
    host.default_credential_id = cred.id
    state.vault.update_host(host)

    # --- Open Tab ---
    info = state.sessions.open_tab(
        host_id=host.id, address_id=addr.id, credential_id=cred.id
    )
    results["TAB_STATUS"] = info.status.value
    results["TAB_ALIAS"] = info.alias
    results["TAB_NO_IP"] = str(HOST not in repr(info))

    marker = f"hostskeeper-tab-{int(time.time()) % 100000}"
    state.sessions.write(info.id, f"echo {marker}", submit=True)
    got = state.sessions.wait_for_output(info.id, marker, timeout=15.0)
    results["TAB_ECHO"] = str(marker in got.data)

    # --- MCP HTTP (same as Qt unlock) ---
    assert state.mcp_service is not None
    ensure_mcp_http(state.mcp_service, state.mcp_host, state.mcp_port)
    token = state.sessions.enable_mcp(info.id)
    url = state.sessions.mcp_url(info.id, host="127.0.0.1", port=mcp_port)
    results["MCP_URL_HAS_TOKEN"] = str(token in url and "token=" in url)
    results["MCP_TOKEN_NOT_IN_ALIAS"] = str(token not in info.alias)

    # session_info — no secrets
    info_json = asyncio.run(_mcp_call(url, "session_info", {}))
    blob = json.dumps(info_json)
    results["MCP_INFO_ALIAS"] = str(info_json.get("alias"))
    results["MCP_INFO_NO_IP"] = str(HOST not in blob)
    results["MCP_INFO_NO_KEYMAT"] = str(
        ("BEGIN" not in blob) and ("private_key" not in blob) and ("password" not in blob)
    )

    # write with Approve off — must be rejected immediately
    state.sessions.set_approve(info.id, enabled=False)
    marker_deny = f"mcp-deny-{int(time.time()) % 100000}"
    before = state.sessions.read(info.id).cursor
    deny_res = asyncio.run(
        _mcp_call(
            url, "session_write", {"text": f"echo {marker_deny}", "submit": True}
        )
    )
    results["MCP_WRITE_DENIED"] = str(
        deny_res.get("error") == "approve_required"
        or (isinstance(deny_res.get("error"), dict)
            and deny_res["error"].get("code") == "approve_required")
        or "approve_required" in json.dumps(deny_res)
    )
    after = state.sessions.read(info.id, cursor=before)
    results["MCP_DENY_NO_ECHO"] = str(marker_deny not in after.data)

    # write with Approve on
    state.sessions.set_approve(info.id, enabled=True)
    marker_w = f"mcp-w-{int(time.time()) % 100000}"
    write_res = asyncio.run(
        _mcp_call(url, "session_write", {"text": f"echo {marker_w}", "submit": True})
    )
    results["MCP_WRITE_OK"] = str(write_res.get("ok") is True or "error" not in write_res)
    try:
        state.sessions.wait_for_output(info.id, marker_w, timeout=10.0)
        results["MCP_WRITE_ECHO"] = "True"
    except TimeoutError:
        results["MCP_WRITE_ECHO"] = "False"

    # scripts CRUD/run (Approve still on)
    created = asyncio.run(
        _mcp_call(
            url,
            "scripts_create",
            {
                "name": "check-say",
                "body": "echo hostskeeper-{{tag}}",
                "parameters": [{"name": "tag", "required": True}],
            },
        )
    )
    results["SCRIPT_NAME"] = str(created.get("name"))
    marker_s = f"scripts-{int(time.time()) % 100000}"
    asyncio.run(
        _mcp_call(
            url,
            "scripts_run",
            {"name": "check-say", "params": {"tag": marker_s}, "submit": True},
        )
    )
    try:
        state.sessions.wait_for_output(info.id, f"hostskeeper-{marker_s}", timeout=12.0)
        results["SCRIPT_ECHO"] = "True"
    except TimeoutError:
        results["SCRIPT_ECHO"] = "False"
    asyncio.run(_mcp_call(url, "scripts_delete", {"name": "check-say"}))

    # reconnect keeps token
    token_before = token
    state.sessions.disconnect(info.id)
    assert state.sessions.get(info.id).status == SessionStatus.DISCONNECTED
    state.sessions.reconnect(info.id)
    assert state.sessions.get(info.id).status == SessionStatus.LIVE
    # token stored on session — enable_mcp returns same if already enabled
    token_after = state.sessions.enable_mcp(info.id)
    results["TOKEN_SAME_AFTER_RECONNECT"] = str(token_before == token_after)

    # cleanup
    state.sessions.close(info.id)
    stop_mcp_http()
    state.lock()

    for k, v in results.items():
        print(f"{k}={v}")

    failed = [
        k
        for k, v in results.items()
        if k.endswith(("_ECHO", "_OK", "_NO_IP", "_NO_KEYMAT", "TIMEOUT_NO_ECHO", "SAME_AFTER_RECONNECT"))
        and v not in ("True", "true")
    ]
    # also require TAB_STATUS live
    if results.get("TAB_STATUS") != "live":
        failed.append("TAB_STATUS")
    if results.get("TAB_ECHO") != "True":
        failed.append("TAB_ECHO")
    if failed:
        print("FAILED=" + ",".join(failed))
        return 1
    print("ALL_OK=True")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print("ERROR=" + type(exc).__name__ + ":" + str(exc)[:500])
        stop_mcp_http()
        raise SystemExit(2)
