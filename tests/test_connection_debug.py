from __future__ import annotations

import pytest

from hostskeeper.runtime import connection_debug
from hostskeeper.runtime import tree_debug_log
from hostskeeper.session.buffer import OutputBuffer
from hostskeeper.session.diagnostics import measure_stage
from hostskeeper.session import ssh as ssh_module
from hostskeeper.session.ssh import SshConnectParams, SshShell


def test_measure_stage_reports_elapsed_and_failure() -> None:
    records: list[tuple[str, float, str]] = []
    callback = lambda name, duration, status: records.append(
        (name, duration, status)
    )

    with measure_stage(callback, "ssh_connect"):
        pass

    with pytest.raises(RuntimeError):
        with measure_stage(callback, "pty_setup"):
            raise RuntimeError("connection failed")

    assert [record[0] for record in records] == ["ssh_connect", "pty_setup"]
    assert all(record[1] >= 0 for record in records)
    assert [record[2] for record in records] == ["ok", "failed"]


def test_connection_trace_logs_only_timing_metadata(monkeypatch) -> None:
    records: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(
        connection_debug,
        "log",
        lambda event, message="", **fields: records.append(
            (event, message, fields)
        ),
    )

    trace = connection_debug.ConnectionTrace("tab_open")
    trace.stage("ssh_transport_and_auth", 1234.5, "ok")
    trace.first_pty_output()
    trace.first_pty_output()
    trace.milestone("tab_attached")

    assert [record[1] for record in records] == [
        "request",
        "ssh_transport_and_auth",
        "first_pty_output",
        "tab_attached",
    ]
    assert records[1][2]["stage_ms"] == 1234.5
    assert records[2][2]["status"] == "received"
    assert all(record[0] == "connection_timing" for record in records)
    assert all(
        "host" not in record[2] and "password" not in record[2]
        for record in records
    )


def test_ssh_reader_reports_only_the_first_pty_output() -> None:
    class FakeChannel:
        def __init__(self) -> None:
            self.closed = False
            self._chunks = [b"banner", b"prompt"]

        def recv_ready(self) -> bool:
            return bool(self._chunks)

        def recv(self, _size: int) -> bytes:
            chunk = self._chunks.pop(0)
            if not self._chunks:
                self.closed = True
            return chunk

        def recv_stderr_ready(self) -> bool:
            return False

    events: list[None] = []
    shell = SshShell(
        SshConnectParams(hostname="unused", port=22, username="unused"),
        OutputBuffer(),
        on_first_output=lambda: events.append(None),
    )
    shell._channel = FakeChannel()

    shell._read_loop()

    assert events == [None]


def test_ssh_connect_measures_channel_pty_and_shell_separately(
    monkeypatch,
) -> None:
    calls: list[str] = []
    stages: list[tuple[str, float, str]] = []

    class FakeChannel:
        closed = True

        def settimeout(self, _timeout: float) -> None:
            pass

        def get_pty(self, **_kwargs) -> None:
            calls.append("request_pty")

        def invoke_shell(self) -> None:
            calls.append("request_shell")

        def close(self) -> None:
            pass

    class FakeTransport:
        def open_session(self):
            calls.append("open_ssh_channel")
            return FakeChannel()

    class FakeClient:
        def set_missing_host_key_policy(self, _policy) -> None:
            pass

        def connect(self, **_kwargs) -> None:
            calls.append("ssh_transport_and_auth")

        def get_transport(self):
            return FakeTransport()

        def close(self) -> None:
            pass

    monkeypatch.setattr(ssh_module.paramiko, "SSHClient", FakeClient)
    shell = SshShell(
        SshConnectParams(hostname="unused", port=22, username="unused"),
        OutputBuffer(),
        on_stage=lambda name, duration, status: stages.append(
            (name, duration, status)
        ),
    )

    shell.connect()
    shell.close()

    assert calls == [
        "ssh_transport_and_auth",
        "open_ssh_channel",
        "request_pty",
        "request_shell",
    ]
    assert [stage[0] for stage in stages] == [
        "prepare_authentication",
        "ssh_transport_and_auth",
        "open_ssh_channel",
        "request_pty",
        "request_shell",
        "start_output_reader",
    ]
    assert all(stage[1] >= 0 and stage[2] == "ok" for stage in stages)


@pytest.mark.parametrize(("keep", "expected_exists"), [(True, True), (False, False)])
def test_tree_log_retention_on_clean_shutdown(
    tmp_path, monkeypatch, keep: bool, expected_exists: bool
) -> None:
    path = tmp_path / "hostskeeper-tree-test.log"
    log_file = path.open("w", encoding="utf-8")
    monkeypatch.setattr(tree_debug_log, "log_path", lambda: path)
    monkeypatch.setattr(tree_debug_log, "_fp", log_file)
    monkeypatch.setattr(tree_debug_log, "_faulthandler_on", False)
    monkeypatch.setattr(tree_debug_log, "_removed", False)
    monkeypatch.setattr(tree_debug_log, "_keep_on_exit", False)

    if keep:
        tree_debug_log.keep_log_on_exit()
    tree_debug_log.close_and_remove()

    assert log_file.closed
    assert path.exists() is expected_exists
