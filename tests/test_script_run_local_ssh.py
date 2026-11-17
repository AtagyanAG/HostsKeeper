from __future__ import annotations

import socket
import threading
import time
from uuid import uuid4

import paramiko

from hostskeeper.session.buffer import OutputBuffer
from hostskeeper.session.script_run_manager import ScriptRunManager
from hostskeeper.session.script_runs import ScriptRunOrigin, ScriptRunState
from hostskeeper.session.ssh import SshConnectParams, SshShell


class _ExecServer(paramiko.ServerInterface):
    def get_allowed_auths(self, _username: str) -> str:
        return "password"

    def check_auth_password(self, _username: str, _password: str) -> int:
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind: str, _chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(
        self,
        _channel: paramiko.Channel,
        _term: bytes,
        _width: int,
        _height: int,
        _pixelwidth: int,
        _pixelheight: int,
        _modes: bytes,
    ) -> bool:
        return True

    def check_channel_shell_request(self, _channel: paramiko.Channel) -> bool:
        return True

    def check_channel_exec_request(
        self, channel: paramiko.Channel, command: bytes
    ) -> bool:
        if command != b"saved-script-body":
            return False

        def _respond() -> None:
            channel.sendall(b"isolated stdout\n")
            channel.send_stderr(b"isolated stderr\n")
            channel.send_exit_status(7)
            channel.close()

        threading.Thread(target=_respond, daemon=True).start()
        return True


class _ExistingTransportClient:
    def __init__(self, transport: paramiko.Transport) -> None:
        self.transport = transport

    def get_transport(self) -> paramiko.Transport:
        return self.transport

    def close(self) -> None:
        self.transport.close()


def test_real_paramiko_exec_channel_isolated_from_interactive_buffer() -> None:
    client_socket, server_socket = socket.socketpair()
    server_transport = paramiko.Transport(server_socket)
    server_transport.add_server_key(paramiko.RSAKey.generate(2048))
    client_transport: paramiko.Transport | None = None
    shell: SshShell | None = None
    accepting: threading.Thread | None = None
    try:
        server_ready = threading.Event()
        server_transport.start_server(event=server_ready, server=_ExecServer())
        accepting = threading.Thread(
            target=_accept_channels, args=(server_transport,), daemon=True
        )
        accepting.start()

        client_transport = paramiko.Transport(client_socket)
        client_transport.start_client(timeout=3)
        client_transport.auth_password("test-user", "test-password")
        assert server_ready.wait(timeout=3)
        interactive_channel = client_transport.open_session(timeout=3)
        interactive_channel.get_pty()
        interactive_channel.invoke_shell()

        buffer = OutputBuffer()
        shell = SshShell(
            SshConnectParams("unused", 22, "test-user", connect_timeout_sec=3),
            buffer,
        )
        shell._client = _ExistingTransportClient(client_transport)  # type: ignore[assignment]
        shell._channel = interactive_channel
        runs = ScriptRunManager(execution_timeout_sec=5)
        session_id = uuid4()
        request_id = uuid4()
        started = runs.start(
            session_id=session_id,
            script_id=uuid4(),
            request_id=request_id,
            origin=ScriptRunOrigin.STDIO,
            command="saved-script-body",
            open_channel=shell.open_exec_channel,
            session_alive=lambda: shell.alive,
        )
        deadline = time.monotonic() + 5
        result = runs.read_output(session_id, started.run_id, max_chars=65536)
        while time.monotonic() < deadline:
            result = runs.read_output(
                session_id,
                started.run_id,
                max_chars=65536,
            )
            if result.info.state in {ScriptRunState.SUCCEEDED, ScriptRunState.FAILED}:
                break
            time.sleep(0.01)

        assert result.info.state == ScriptRunState.FAILED
        assert result.info.exit_code == 7
        assert result.stdout.data == "isolated stdout\n"
        assert result.stderr.data == "isolated stderr\n"
        assert buffer.snapshot() == ""
    finally:
        if shell is not None:
            shell.close()
        elif client_transport is not None:
            client_transport.close()
        server_transport.close()
        client_socket.close()
        if accepting is not None:
            accepting.join(timeout=1)


def _accept_channels(transport: paramiko.Transport) -> None:
    while transport.is_active():
        channel = transport.accept(timeout=0.2)
        if channel is None and not transport.is_active():
            return
