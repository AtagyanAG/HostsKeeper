from __future__ import annotations

import pytest

from hostskeeper.runtime import connection_debug
from hostskeeper.session.buffer import OutputBuffer
from hostskeeper.session.diagnostics import measure_stage
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
