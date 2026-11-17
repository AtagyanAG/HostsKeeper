from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from uuid import UUID, uuid4

import paramiko
import pytest

from hostskeeper.session.buffer import OutputBuffer
from hostskeeper.session.script_run_manager import (
    SCRIPT_RUN_MAX_ACTIVE_PROCESS,
    SCRIPT_RUN_MAX_RECORDS,
    SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS,
    ScriptRunCapacityError,
    ScriptRunCapacityReason,
    ScriptRunManager,
    ScriptRunNotFoundError,
)
from hostskeeper.session.script_runs import (
    SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM,
    ScriptRunErrorCode,
    ScriptRunInfo,
    ScriptRunOrigin,
    ScriptRunState,
)
from hostskeeper.session.ssh import SshConnectParams, SshShell


class FakeChannel:
    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int | None = 0,
        recv_chunk_size: int = 4096,
    ) -> None:
        self._stdout = deque(
            stdout[index : index + recv_chunk_size]
            for index in range(0, len(stdout), recv_chunk_size)
        )
        self._stderr = deque(
            stderr[index : index + recv_chunk_size]
            for index in range(0, len(stderr), recv_chunk_size)
        )
        self._exit_code = exit_code
        self.active = True
        self.closed = False
        self.close_calls = 0
        self.command = ""
        self.stdin_closed = False

    def settimeout(self, _timeout: float) -> None:
        del _timeout

    def exec_command(self, command: str) -> None:
        self.command = command

    def shutdown_write(self) -> None:
        self.stdin_closed = True

    def recv_ready(self) -> bool:
        return bool(self._stdout)

    def recv(self, _size: int) -> bytes:
        del _size
        return self._stdout.popleft()

    def recv_stderr_ready(self) -> bool:
        return bool(self._stderr)

    def recv_stderr(self, _size: int) -> bytes:
        del _size
        return self._stderr.popleft()

    def exit_status_ready(self) -> bool:
        return self._exit_code is not None or self.closed

    def recv_exit_status(self) -> int:
        return -1 if self._exit_code is None else self._exit_code

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.active = False


class FakeTransport:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel
        self.open_calls: list[float | None] = []

    def is_active(self) -> bool:
        return True

    def open_session(self, *, timeout: float | None = None) -> FakeChannel:
        self.open_calls.append(timeout)
        return self.channel


class FakeClient:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.closed = False

    def get_transport(self) -> FakeTransport:
        return self.transport

    def close(self) -> None:
        self.closed = True


def _start(
    manager: ScriptRunManager,
    channel: FakeChannel,
    *,
    session_id: UUID | None = None,
    request_id: UUID | None = None,
    open_channel: Callable[[str], FakeChannel] | None = None,
    session_alive: Callable[[], bool] = lambda: True,
    origin: ScriptRunOrigin = ScriptRunOrigin.STDIO,
    command: str = "echo safe",
    display_name: str = "script",
    display_buffer: OutputBuffer | None = None,
) -> tuple[UUID, UUID, ScriptRunInfo]:
    session_id = session_id or uuid4()
    request_id = request_id or uuid4()

    def _open_channel(command: str) -> FakeChannel:
        channel.command = command
        return channel

    info = manager.start(
        session_id=session_id,
        script_id=uuid4(),
        request_id=request_id,
        origin=origin,
        command=command,
        open_channel=open_channel or _open_channel,
        session_alive=session_alive,
        display_name=display_name,
        display_buffer=display_buffer,
    )
    return session_id, request_id, info


def _wait_for_state(
    manager: ScriptRunManager,
    session_id: UUID,
    run_id: UUID,
    expected: ScriptRunState,
) -> ScriptRunInfo:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        info = manager.get(session_id, run_id)
        if info.state == expected:
            return info
        time.sleep(0.01)
    raise AssertionError(f"run did not reach {expected.value}")


def test_exec_channel_uses_existing_transport_and_never_uses_pty() -> None:
    channel = FakeChannel(exit_code=None)
    transport = FakeTransport(channel)
    client = FakeClient(transport)
    shell = SshShell(
        SshConnectParams("unused", 22, "user", connect_timeout_sec=1),
        OutputBuffer(),
    )
    shell._client = client
    shell._channel = FakeChannel()

    opened = shell.open_exec_channel("printf 'isolated'")

    assert opened is channel
    assert transport.open_calls == [1]
    assert channel.command == "printf 'isolated'"
    assert channel.stdin_closed is True
    assert shell._channel is not channel

    shell.close()
    assert channel.close_calls == 1
    assert client.closed is True


def test_exec_channel_closes_failed_request_without_leaking_error() -> None:
    class RejectingChannel(FakeChannel):
        def exec_command(self, command: str) -> None:
            del command
            raise paramiko.SSHException("private server detail")

    channel = RejectingChannel()
    shell = SshShell(
        SshConnectParams("unused", 22, "user", connect_timeout_sec=1),
        OutputBuffer(),
    )
    shell._client = FakeClient(FakeTransport(channel))
    shell._channel = FakeChannel()

    with pytest.raises(paramiko.SSHException, match="private server detail"):
        shell.open_exec_channel("command")
    assert channel.closed is True
    assert not shell._exec_channels


def test_run_captures_separate_streams_and_confirmed_exit_status() -> None:
    manager = ScriptRunManager()
    channel = FakeChannel(stdout="Привет\n".encode(), stderr=b"warning\n", exit_code=3, recv_chunk_size=1)
    session_id, _, started = _start(manager, channel)

    result = manager.wait(
        session_id,
        started.run_id,
        timeout_sec=1,
        max_chars=SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS,
    )

    assert result.info.state == ScriptRunState.FAILED
    assert result.info.exit_code == 3
    assert result.info.completed_at is not None
    assert result.stdout.data == "Привет\n"
    assert result.stderr.data == "warning\n"
    assert result.info.output.stdout_chars_retained == len("Привет\n")


def test_run_output_is_bounded_sanitized_and_cursor_readable() -> None:
    manager = ScriptRunManager()
    original = b"x" * (SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM + 100)
    channel = FakeChannel(stdout=original, exit_code=0)
    session_id, _, started = _start(manager, channel)
    completed = _wait_for_state(
        manager, session_id, started.run_id, ScriptRunState.SUCCEEDED
    )
    result = manager.read_output(
        session_id, started.run_id, max_chars=SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS
    )

    assert result.info.run_id == completed.run_id
    assert result.info.output.stdout_chars_retained == SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM
    assert result.info.output.stdout_truncated is True
    assert len(result.stdout.data) + len(result.stderr.data) <= 65536

    tail = manager.read_output(
        session_id,
        started.run_id,
        stdout_cursor=str(len(result.stdout.data)),
        stderr_cursor=result.stderr.cursor,
        max_chars=65536,
    )
    assert tail.stdout.data
    assert len(tail.stdout.data) + len(tail.stderr.data) <= 65536

    control_channel = FakeChannel(stdout=b"hello\x1b[31m", exit_code=0)
    other_session, _, control_run = _start(manager, control_channel)
    safe = manager.wait(other_session, control_run.run_id, timeout_sec=1)
    assert "\x1b" not in safe.stdout.data
    assert "hello" in safe.stdout.data


@pytest.mark.parametrize(
    ("origin", "initiator"),
    [
        (ScriptRunOrigin.STDIO, "MCP client"),
        (ScriptRunOrigin.USER_INTERFACE, "user"),
    ],
)
def test_run_transcript_is_shared_and_never_echoes_script_body(
    origin: ScriptRunOrigin, initiator: str
) -> None:
    manager = ScriptRunManager()
    display_buffer = OutputBuffer()
    channel = FakeChannel(
        stdout=b"result line\r\n", stderr=b"warning line\r\n", exit_code=0
    )
    session_id, _, started = _start(
        manager,
        channel,
        origin=origin,
        command="sensitive shell body",
        display_name="iptables-status",
        display_buffer=display_buffer,
    )

    completed = _wait_for_state(
        manager, session_id, started.run_id, ScriptRunState.SUCCEEDED
    )
    transcript = display_buffer.snapshot()

    assert completed.exit_code == 0
    assert f"Run script: iptables-status [{started.run_id}]" in transcript
    assert f"initiator: {initiator}" in transcript
    assert "result line\r\n" in transcript
    assert "warning line\r\n" in transcript
    assert f"finished: succeeded; exit_code=0" in transcript
    assert "sensitive shell body" not in transcript


def test_run_transcript_marks_output_truncation() -> None:
    manager = ScriptRunManager()
    display_buffer = OutputBuffer()
    channel = FakeChannel(
        stdout=b"z" * (SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM + 100),
        exit_code=0,
    )
    session_id, _, started = _start(
        manager, channel, display_buffer=display_buffer
    )

    _wait_for_state(manager, session_id, started.run_id, ScriptRunState.SUCCEEDED)
    transcript = display_buffer.snapshot()

    assert transcript.count("z") == SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM
    assert transcript.count("Run output truncated at capture limit.") == 1


def test_transcript_normalizes_bare_line_feeds_for_terminal_display() -> None:
    manager = ScriptRunManager()
    display_buffer = OutputBuffer()
    channel = FakeChannel(
        stdout=b"first\r\nsecond\nthird\r",
        exit_code=0,
        recv_chunk_size=1,
    )
    session_id, _, started = _start(
        manager, channel, display_buffer=display_buffer
    )

    _wait_for_state(manager, session_id, started.run_id, ScriptRunState.SUCCEEDED)
    result = manager.read_output(session_id, started.run_id)

    assert result.stdout.data == "first\r\nsecond\nthird\r"
    assert "first\r\nsecond\r\nthird\r" in display_buffer.snapshot()


def test_wait_timeout_does_not_change_run_state() -> None:
    manager = ScriptRunManager()
    channel = FakeChannel(exit_code=None)
    session_id, _, started = _start(manager, channel)

    waited = manager.wait(session_id, started.run_id, timeout_sec=0)

    assert waited.wait_timed_out is True
    assert waited.info.state == ScriptRunState.RUNNING
    assert waited.info.exit_code is None

    manager.cancel(session_id, started.run_id)


def test_cancel_and_approve_revoke_never_claim_confirmed_cancellation() -> None:
    manager = ScriptRunManager()
    channel = FakeChannel(exit_code=None)
    session_id, _, started = _start(manager, channel)

    info = manager.cancel(session_id, started.run_id)

    assert info.state == ScriptRunState.UNKNOWN
    assert info.error_code == ScriptRunErrorCode.CANCEL_UNCONFIRMED
    assert info.completed_at is None
    assert info.exit_code is None
    assert info.process_may_continue is True
    assert channel.closed is True

    next_channel = FakeChannel(exit_code=None)
    next_session, _, next_run = _start(manager, next_channel)
    manager.on_execution_access_revoked(next_session)
    revoked = manager.get(next_session, next_run.run_id)
    assert revoked.state == ScriptRunState.UNKNOWN
    assert revoked.error_code == ScriptRunErrorCode.CANCEL_UNCONFIRMED
    assert revoked.process_may_continue is True


def test_session_loss_and_missing_exit_status_are_not_success() -> None:
    manager = ScriptRunManager()
    channel = FakeChannel(exit_code=None)
    session_id, _, started = _start(manager, channel)

    manager.on_session_lost(session_id)
    lost = manager.get(session_id, started.run_id)
    assert lost.state == ScriptRunState.SESSION_LOST
    assert lost.exit_code is None
    assert lost.process_may_continue is True

    missing_status_channel = FakeChannel(exit_code=None)
    alive = [True]
    other_session, _, other_run = _start(
        manager,
        missing_status_channel,
        session_alive=lambda: alive[0],
    )
    alive[0] = False
    missing_status_channel.close()
    lost_without_status = _wait_for_state(
        manager, other_session, other_run.run_id, ScriptRunState.SESSION_LOST
    )
    assert lost_without_status.exit_code is None


def test_execution_timeout_is_uncertain_not_cancelled() -> None:
    manager = ScriptRunManager(execution_timeout_sec=0.03)
    channel = FakeChannel(exit_code=None)
    session_id, _, started = _start(manager, channel)

    info = _wait_for_state(
        manager, session_id, started.run_id, ScriptRunState.EXECUTION_TIMED_OUT
    )

    assert info.error_code == ScriptRunErrorCode.EXECUTION_TIMEOUT
    assert info.exit_code is None
    assert info.completed_at is None
    assert info.process_may_continue is True


def test_request_id_is_idempotent_and_runs_are_session_bound() -> None:
    manager = ScriptRunManager()
    session_id = uuid4()
    request_id = uuid4()
    first_channel = FakeChannel(exit_code=None)
    other_channel = FakeChannel(exit_code=0)
    first_session, _, first = _start(
        manager,
        first_channel,
        session_id=session_id,
        request_id=request_id,
    )
    duplicate = manager.start(
        session_id=session_id,
        script_id=uuid4(),
        request_id=request_id,
        origin=ScriptRunOrigin.HTTP_GATEWAY,
        command="different command",
        open_channel=lambda command: _return_channel(command, other_channel),
        session_alive=lambda: True,
    )

    assert duplicate.run_id == first.run_id
    assert other_channel.command == ""
    with pytest.raises(ScriptRunNotFoundError):
        manager.get(uuid4(), first.run_id)
    manager.cancel(first_session, first.run_id)


def test_active_run_limits_reject_a_second_session_run() -> None:
    manager = ScriptRunManager()
    session_id, _, first = _start(manager, FakeChannel(exit_code=None))

    with pytest.raises(ScriptRunCapacityError) as capacity:
        manager.start(
            session_id=session_id,
            script_id=uuid4(),
            request_id=uuid4(),
            origin=ScriptRunOrigin.STDIO,
            command="another",
            open_channel=lambda command: _return_channel(
                command, FakeChannel()
            ),
            session_alive=lambda: True,
        )
    assert capacity.value.reason == ScriptRunCapacityReason.SESSION_LIMIT
    manager.cancel(session_id, first.run_id)
    with pytest.raises(ScriptRunCapacityError) as uncertain_capacity:
        manager.start(
            session_id=session_id,
            script_id=uuid4(),
            request_id=uuid4(),
            origin=ScriptRunOrigin.STDIO,
            command="must not overlap uncertain run",
            open_channel=lambda command: _return_channel(command, FakeChannel()),
            session_alive=lambda: True,
        )
    assert uncertain_capacity.value.reason == ScriptRunCapacityReason.SESSION_LIMIT


def test_process_run_limit_reports_its_scope() -> None:
    manager = ScriptRunManager()
    runs = [
        _start(manager, FakeChannel(exit_code=None))
        for _ in range(SCRIPT_RUN_MAX_ACTIVE_PROCESS)
    ]

    with pytest.raises(ScriptRunCapacityError) as capacity:
        _start(manager, FakeChannel(exit_code=None))

    assert capacity.value.reason == ScriptRunCapacityReason.PROCESS_LIMIT
    for session_id, _, run in runs:
        manager.cancel(session_id, run.run_id)


def test_retained_record_limit_is_distinct_from_concurrency_limit() -> None:
    manager = ScriptRunManager()
    for _ in range(SCRIPT_RUN_MAX_RECORDS):
        session_id, _, started = _start(manager, FakeChannel(exit_code=0))
        _wait_for_state(
            manager, session_id, started.run_id, ScriptRunState.SUCCEEDED
        )

    with pytest.raises(ScriptRunCapacityError) as capacity:
        _start(manager, FakeChannel(exit_code=0))

    assert capacity.value.reason == ScriptRunCapacityReason.RECORD_LIMIT


def test_start_failure_is_reported_without_raw_exception() -> None:
    manager = ScriptRunManager()

    def _fail_start(command: str) -> FakeChannel:
        del command
        raise RuntimeError("private host and credential details")

    session_id, _, info = _start(
        manager, FakeChannel(), open_channel=_fail_start
    )

    assert info.state == ScriptRunState.UNKNOWN
    assert info.error_code == ScriptRunErrorCode.START_FAILED
    assert info.exit_code is None
    assert "private" not in repr(info)
    assert manager.get(session_id, info.run_id).state == ScriptRunState.UNKNOWN


def _return_channel(command: str, channel: FakeChannel) -> FakeChannel:
    channel.command = command
    return channel
