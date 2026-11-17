from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session.manager import SessionManager, _SessionState
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.session.script_runs import ScriptRunState
from hostskeeper.vault import Host, Script, ScriptParameter, Vault


class FakeExecChannel:
    def __init__(self) -> None:
        self.active = True
        self.closed = False
        self._exit_code = 0

    def recv_ready(self) -> bool:
        return False

    def recv(self, _size: int) -> bytes:
        return b""

    def recv_stderr_ready(self) -> bool:
        return False

    def recv_stderr(self, _size: int) -> bytes:
        return b""

    def exit_status_ready(self) -> bool:
        return True

    def recv_exit_status(self) -> int:
        return self._exit_code

    def close(self) -> None:
        self.closed = True
        self.active = False


class FakeShell:
    def __init__(self) -> None:
        self.channel = FakeExecChannel()
        self.commands: list[str] = []
        self.writes: list[str] = []
        self.alive = True

    def open_exec_channel(self, command: str) -> FakeExecChannel:
        self.commands.append(command)
        return self.channel

    def write(self, text: str) -> None:
        self.writes.append(text)

    def close(self) -> None:
        self.alive = False
        self.channel.close()


@pytest.fixture()
def stack(tmp_path):
    vault = Vault.create(tmp_path / "runs.vault", "test-pass")
    host = vault.add_host(Host(name="host"))
    script = vault.add_script(
        Script(
            name="safe-script",
            body="printf '{{value}}'",
            parameters=[ScriptParameter(name="value", default="default")],
            mcp_enabled=True,
        )
    )
    info = SessionInfo(
        id=uuid4(),
        alias="host-user-1",
        status=SessionStatus.LIVE,
        host_id=host.id,
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        approve_enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    sessions = SessionManager(vault)
    shell = FakeShell()
    state = _SessionState(info=info, shell=shell)  # type: ignore[arg-type]
    with sessions._lock:
        sessions._sessions[info.id] = state
    service = McpToolService(sessions, vault)
    return vault, sessions, service, host, script, info, shell


def _wait_for_terminal(sessions: SessionManager, session_id, run_id):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        info = sessions.get_script_run(session_id, run_id)
        if info.state in {
            ScriptRunState.SUCCEEDED,
            ScriptRunState.FAILED,
            ScriptRunState.UNKNOWN,
        }:
            return info
        time.sleep(0.01)
    raise AssertionError("script run did not finish")


def test_internal_start_uses_saved_script_and_isolated_channel(stack) -> None:
    _, sessions, service, _, script, info, shell = stack

    started = service._start_script_run(
        McpAccess(mode="stdio"),
        request_id=str(uuid4()),
        script_id=str(script.id),
        params={"value": "ok"},
        alias=info.alias,
    )
    completed = _wait_for_terminal(sessions, info.id, started.run_id)

    assert completed.state == ScriptRunState.SUCCEEDED
    assert shell.commands == ["printf 'ok'"]
    assert shell.writes == []
    assert sessions.read(info.id).data == ""


def test_public_run_lifecycle_returns_acceptance_and_bounded_output(stack) -> None:
    _, sessions, service, _, script, info, shell = stack
    access = McpAccess(mode="stdio")
    request_id = str(uuid4())

    accepted = service.scripts_run(
        access,
        request_id=request_id,
        script_id=str(script.id),
        params={"value": "ok"},
        alias=info.alias,
    )
    assert accepted["state"] == "accepted"
    assert accepted["run_id"]
    assert accepted["accepted_at"]

    retried = service.scripts_run(
        access,
        request_id=request_id,
        script_id=str(uuid4()),
        alias=info.alias,
    )
    assert retried["run_id"] == accepted["run_id"]
    assert len(shell.commands) == 1

    result = service.scripts_run_wait(
        access,
        run_id=accepted["run_id"],
        alias=info.alias,
        timeout_sec=1,
        max_chars=64,
    )
    assert result["state"] == "succeeded"
    assert result["exit_code"] == 0
    assert result["stdout"] == {
        "cursor": "0",
        "data": "",
        "truncated": False,
    }
    assert result["stderr"]["data"] == ""
    assert result["wait_timed_out"] is False
    assert service.scripts_run_status(
        access,
        run_id=accepted["run_id"],
        alias=info.alias,
    )["state"] == "succeeded"
    assert sessions.read(info.id).data == ""


def test_run_wait_validates_timeout_and_inspection_is_scoped(stack) -> None:
    _, _, service, _, script, info, _shell = stack
    access = McpAccess(mode="stdio")
    accepted = service.scripts_run(
        access,
        request_id=str(uuid4()),
        script_id=str(script.id),
        alias=info.alias,
    )

    with pytest.raises(McpToolError) as invalid_timeout:
        service.scripts_run_wait(
            access,
            run_id=accepted["run_id"],
            alias=info.alias,
            timeout_sec=31,
        )
    assert invalid_timeout.value.code == "invalid_args"

    with pytest.raises(McpToolError) as not_found:
        service.scripts_run_status(
            access,
            run_id=str(uuid4()),
            alias=info.alias,
        )
    assert not_found.value.code == "not_found"


def test_cancel_is_scoped_and_does_not_require_approve(stack) -> None:
    _, sessions, service, _, script, info, shell = stack
    shell.channel._exit_code = None
    access = McpAccess(mode="stdio")
    accepted = service.scripts_run(
        access,
        request_id=str(uuid4()),
        script_id=str(script.id),
        alias=info.alias,
    )

    sessions.set_approve(info.id, enabled=False)
    cancelled = service.scripts_run_cancel(
        access,
        run_id=accepted["run_id"],
        alias=info.alias,
    )
    assert cancelled["state"] == "unknown"
    assert cancelled["exit_code"] is None
    assert shell.channel.closed is True


def test_start_requires_approve_and_disabled_script_is_not_visible(stack) -> None:
    vault, sessions, service, _, script, info, shell = stack
    sessions.set_approve(info.id, enabled=False)

    with pytest.raises(McpToolError) as denied:
        service._start_script_run(
            McpAccess(mode="stdio"),
            request_id=str(uuid4()),
            script_id=str(script.id),
            alias=info.alias,
        )
    assert denied.value.code == "approve_required"
    assert shell.commands == []

    sessions.set_approve(info.id, enabled=True)
    hidden = vault.get_script(script.id)
    hidden.mcp_enabled = False
    vault.update_script(hidden)
    with pytest.raises(McpToolError) as not_found:
        service._start_script_run(
            McpAccess(mode="stdio"),
            request_id=str(uuid4()),
            script_id=str(script.id),
            alias=info.alias,
        )
    assert not_found.value.code == "not_found"
    assert shell.commands == []


def test_start_requires_mcp_enabled_tab(stack) -> None:
    _vault, sessions, service, _, script, info, shell = stack
    sessions.disable_mcp(info.id)

    with pytest.raises(McpToolError) as not_found:
        service._start_script_run(
            McpAccess(mode="stdio"),
            request_id=str(uuid4()),
            script_id=str(script.id),
            alias=info.alias,
        )
    assert not_found.value.code == "not_found"
    assert shell.commands == []


def test_host_script_is_bound_to_matching_tab(stack) -> None:
    vault, sessions, service, host, _, info, shell = stack
    host_script = vault.add_script(
        Script(
            name="host-only",
            body="true",
            host_id=host.id,
            mcp_enabled=True,
        )
    )
    other_host = vault.add_host(Host(name="other-host"))
    changed = SessionInfo(
        id=info.id,
        alias=info.alias,
        status=SessionStatus.LIVE,
        host_id=other_host.id,
        address_id=info.address_id,
        credential_id=info.credential_id,
        target=SessionTarget.TAB,
        mcp_enabled=True,
        approve_enabled=True,
        created_at=info.created_at,
    )
    with sessions._lock:
        sessions._sessions[info.id] = _SessionState(
            info=changed, shell=shell  # type: ignore[arg-type]
        )

    with pytest.raises(McpToolError) as not_found:
        service._start_script_run(
            McpAccess(mode="stdio"),
            request_id=str(uuid4()),
            script_id=str(host_script.id),
            alias=info.alias,
        )
    assert not_found.value.code == "not_found"
    assert shell.commands == []


def test_approve_revoke_marks_active_run_unknown_and_retry_is_idempotent(stack) -> None:
    _, sessions, service, _, script, info, shell = stack
    shell.channel._exit_code = None
    request_id = str(uuid4())
    started = service._start_script_run(
        McpAccess(mode="stdio"),
        request_id=request_id,
        script_id=str(script.id),
        alias=info.alias,
    )

    sessions.set_approve(info.id, enabled=False)
    revoked = sessions.get_script_run(info.id, started.run_id)
    assert revoked.state == ScriptRunState.UNKNOWN
    assert revoked.exit_code is None
    assert revoked.process_may_continue is True
    assert shell.channel.closed is True

    retried = service._start_script_run(
        McpAccess(mode="stdio"),
        request_id=request_id,
        script_id=str(uuid4()),
        alias=info.alias,
    )
    assert retried.run_id == started.run_id
    assert len(shell.commands) == 1
