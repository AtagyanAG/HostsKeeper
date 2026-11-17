from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpAccess, McpToolService
from hostskeeper.session.manager import (
    SessionManager,
    SessionStateError,
    _SessionState,
)
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.session.script_runs import ScriptRunState
from hostskeeper.vault import Host, Script, ScriptParameter, Vault


class FakeExecChannel:
    def __init__(self) -> None:
        self.active = True
        self.closed = False
        self._exit_code = 0
        self.stdout = bytearray()
        self.stderr = bytearray()

    def recv_ready(self) -> bool:
        return bool(self.stdout)

    def recv(self, size: int) -> bytes:
        data = bytes(self.stdout[:size])
        del self.stdout[:size]
        return data

    def recv_stderr_ready(self) -> bool:
        return bool(self.stderr)

    def recv_stderr(self, size: int) -> bytes:
        data = bytes(self.stderr[:size])
        del self.stderr[:size]
        return data

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
    transcript = sessions.read(info.id).data
    assert f"Run script: {script.name} [{started.run_id}]" in transcript
    assert "initiator: MCP client" in transcript
    assert shell.commands[0] not in transcript


def test_user_start_is_explicit_and_uses_same_transcript_without_mcp_gates(
    stack,
) -> None:
    vault, sessions, _, _, script, info, shell = stack
    script.mcp_enabled = False
    vault.update_script(script)
    sessions.disable_mcp(info.id)
    sessions.set_approve(info.id, enabled=False)

    started = sessions.start_user_script_run(info.id, script.id)
    completed = sessions._script_runs.wait(info.id, started.run_id, timeout_sec=1).info
    transcript = sessions.read(info.id).data

    assert completed.state == ScriptRunState.SUCCEEDED
    assert shell.commands == ["printf 'default'"]
    assert shell.writes == []
    assert f"Run script: {script.name} [{started.run_id}]" in transcript
    assert "initiator: user" in transcript
    assert f"finished: succeeded; exit_code=0" in transcript
    assert shell.commands[0] not in transcript


def test_user_start_still_enforces_host_scope(stack) -> None:
    vault, sessions, _, _, _, info, shell = stack
    other_host = vault.add_host(Host(name="other-host"))
    script = vault.add_script(
        Script(name="other-host-script", body="true", host_id=other_host.id)
    )

    with pytest.raises(SessionStateError, match="another host"):
        sessions.start_user_script_run(info.id, script.id)

    assert shell.commands == []


def test_mcp_lifecycle_cannot_cancel_ui_run_but_can_read_its_transcript(stack) -> None:
    _, sessions, service, _, script, info, shell = stack
    shell.channel.exit_status_ready = lambda: False
    started = sessions.start_user_script_run(info.id, script.id)

    with pytest.raises(McpToolError) as hidden:
        service.scripts_run_cancel(
            McpAccess(mode="stdio"),
            run_id=str(started.run_id),
            alias=info.alias,
        )

    assert hidden.value.code == "not_found"
    assert shell.channel.closed is False
    assert f"Run script: {script.name} [{started.run_id}]" in sessions.read(
        info.id
    ).data
    sessions._script_runs.cancel(info.id, started.run_id)


def test_public_run_lifecycle_returns_acceptance_and_bounded_output(stack) -> None:
    _, sessions, service, _, script, info, shell = stack
    access = McpAccess(mode="stdio")
    request_id = str(uuid4())
    rendered = "printf 'ok'"
    shell.channel.stdout.extend(b"output line\r\n")

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
    assert accepted["replayed"] is False
    assert accepted["current_state"] in {
        "starting",
        "running",
        "succeeded",
    }

    retried = service.scripts_run(
        access,
        request_id=request_id,
        script_id=str(uuid4()),
        alias=info.alias,
    )
    assert retried["run_id"] == accepted["run_id"]
    assert retried["state"] == "accepted"
    assert retried["replayed"] is True
    assert retried["current_state"] in {
        "starting",
        "running",
        "succeeded",
    }
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
        "cursor": str(len("output line\r\n")),
        "data": "output line\r\n",
        "truncated": False,
    }
    assert result["stdout"]["data"].count("output line") == 1
    assert result["stderr"]["data"] == ""
    assert result["wait_timed_out"] is False
    completed_retry = service.scripts_run(
        access,
        request_id=request_id,
        script_id=str(uuid4()),
        alias=info.alias,
    )
    assert completed_retry["run_id"] == accepted["run_id"]
    assert completed_retry["state"] == "accepted"
    assert completed_retry["replayed"] is True
    assert completed_retry["current_state"] == "succeeded"
    assert len(shell.commands) == 1
    status = service.scripts_run_status(
        access,
        run_id=accepted["run_id"],
        alias=info.alias,
    )
    assert status["state"] == "succeeded"
    assert rendered not in str(status)
    assert shell.writes == []
    transcript = sessions.read(info.id).data
    assert f"Run script: {script.name} [{accepted['run_id']}]" in transcript
    assert "output line\r\n" in transcript
    assert f"finished: succeeded; exit_code=0" in transcript
    assert rendered not in transcript


def test_run_capacity_error_explains_session_limit_without_sensitive_details(
    stack,
) -> None:
    _, sessions, service, _, script, info, shell = stack
    shell.channel.exit_status_ready = lambda: False
    access = McpAccess(mode="stdio")
    started = service.scripts_run(
        access,
        request_id=str(uuid4()),
        script_id=str(script.id),
        alias=info.alias,
    )

    with pytest.raises(McpToolError) as capacity:
        service.scripts_run(
            access,
            request_id=str(uuid4()),
            script_id=str(script.id),
            alias=info.alias,
        )

    assert capacity.value.code == "run_capacity"
    assert "limit is 1 per session" in str(capacity.value)
    assert "No queue is configured" in str(capacity.value)
    assert script.body not in str(capacity.value)
    assert len(shell.commands) == 1
    with pytest.raises(SessionStateError, match="limit is 1 per session"):
        sessions.start_user_script_run(info.id, script.id)
    sessions.cancel_script_run(info.id, UUID(started["run_id"]))


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
