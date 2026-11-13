"""Paramiko interactive shell transport."""

from __future__ import annotations

import io
import socket
import threading
import time
from dataclasses import dataclass

import paramiko

from hostskeeper.session.buffer import OutputBuffer


@dataclass(frozen=True)
class SshConnectParams:
    hostname: str
    port: int
    username: str
    password: str | None = None
    private_key_pem: str | None = None
    passphrase: str | None = None
    allow_agent: bool = False
    look_for_keys: bool = False
    connect_timeout_sec: float = 3.0


class SshShell:
    """Owns Paramiko client + shell channel and a reader thread."""

    def __init__(self, params: SshConnectParams, buffer: OutputBuffer) -> None:
        self._params = params
        self._buffer = buffer
        self._client: paramiko.SSHClient | None = None
        self._channel: paramiko.Channel | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._dead = threading.Event()

    @property
    def alive(self) -> bool:
        if self._dead.is_set():
            return False
        channel = self._channel
        return channel is not None and not channel.closed

    def connect(self) -> None:
        client = paramiko.SSHClient()
        # v1: auto-add host keys for lab use; harden with known_hosts later.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pkey = self._load_pkey()
        timeout = max(1.0, float(self._params.connect_timeout_sec))
        try:
            client.connect(
                hostname=self._params.hostname,
                port=self._params.port,
                username=self._params.username,
                password=self._params.password,
                pkey=pkey,
                look_for_keys=self._params.look_for_keys,
                allow_agent=self._params.allow_agent,
                timeout=timeout,
                banner_timeout=timeout,
                auth_timeout=timeout,
            )
        except (TimeoutError, socket.timeout) as exc:
            client.close()
            raise RuntimeError(
                f"Tab connect timed out after {int(timeout)}s"
            ) from exc
        except paramiko.SSHException as exc:
            client.close()
            detail = str(exc).lower()
            if "timed out" in detail or "timeout" in detail or "banner" in detail:
                raise RuntimeError(
                    f"Tab connect timed out after {int(timeout)}s"
                ) from exc
            raise
        channel = client.invoke_shell(term="xterm", width=120, height=40)
        channel.settimeout(0.0)
        self._client = client
        self._channel = channel
        self._stop.clear()
        self._dead.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name="hostskeeper-ssh-reader", daemon=True
        )
        self._reader.start()

    def write(self, text: str) -> None:
        if not self.alive or self._channel is None:
            raise RuntimeError("ssh shell is not alive")
        self._channel.sendall(text.encode("utf-8", errors="replace"))

    def resize(self, cols: int, rows: int) -> None:
        if not self.alive or self._channel is None:
            return
        cols = max(20, min(int(cols), 500))
        rows = max(5, min(int(rows), 200))
        self._channel.resize_pty(width=cols, height=rows)

    def close(self) -> None:
        self._stop.set()
        channel = self._channel
        client = self._client
        self._channel = None
        self._client = None
        try:
            if channel is not None:
                channel.close()
        finally:
            if client is not None:
                client.close()
        self._dead.set()
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=2.0)

    def _load_pkey(self) -> paramiko.PKey | None:
        pem = self._params.private_key_pem
        if not pem:
            return None
        file_obj = io.StringIO(pem)
        passphrase = self._params.passphrase
        errors: list[Exception] = []
        for loader in (
            paramiko.Ed25519Key.from_private_key,
            paramiko.RSAKey.from_private_key,
            paramiko.ECDSAKey.from_private_key,
        ):
            try:
                file_obj.seek(0)
                return loader(file_obj, password=passphrase)
            except Exception as exc:  # noqa: BLE001 - try next key type
                errors.append(exc)
        raise RuntimeError(f"unable to load private key: {errors[-1]}")

    def _read_loop(self) -> None:
        channel = self._channel
        if channel is None:
            self._dead.set()
            return
        try:
            while not self._stop.is_set():
                if channel.closed:
                    break
                got = False
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if not data:
                        break
                    self._buffer.append(data.decode("utf-8", errors="replace"))
                    got = True
                if channel.recv_stderr_ready():
                    data = channel.recv_stderr(4096)
                    if data:
                        self._buffer.append(data.decode("utf-8", errors="replace"))
                    got = True
                if not got:
                    time.sleep(0.05)
        finally:
            self._dead.set()
