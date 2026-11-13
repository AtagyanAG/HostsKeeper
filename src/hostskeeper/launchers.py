"""External PuTTY / WinSCP launchers (human-only, no MCP)."""

from __future__ import annotations

import atexit
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from hostskeeper.session.knock import KnockStep, perform_knock
from hostskeeper.vault.models import Address, Credential


def _maybe_knock(address: Address) -> None:
    if address.knock_enabled and address.knock_steps:
        perform_knock(
            address.host,
            [KnockStep.from_dict(s) for s in address.knock_steps],
            delay_ms=address.knock_delay_ms,
            pause_ms=address.knock_pause_ms,
        )

_TEMP_FILES: list[Path] = []


def _cleanup_temp_files() -> None:
    for path in list(_TEMP_FILES):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    _TEMP_FILES.clear()


atexit.register(_cleanup_temp_files)


@dataclass(frozen=True)
class LauncherPaths:
    putty: Path | None
    winscp: Path | None
    winscp_com: Path | None
    puttygen: Path | None


def discover_launchers(
    putty: str | None = None,
    winscp: str | None = None,
) -> LauncherPaths:
    putty_path = _resolve(
        putty,
        env="HOSTSKEEPER_PUTTY",
        candidates=[
            Path(r"C:\Program Files\PuTTY\putty.exe"),
            Path(r"C:\Program Files (x86)\PuTTY\putty.exe"),
        ],
        which="putty",
    )
    local_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "WinSCP"
    winscp_path = _resolve(
        winscp,
        env="HOSTSKEEPER_WINSCP",
        candidates=[
            local_dir / "WinSCP.exe",
            Path(r"C:\Program Files\WinSCP\WinSCP.exe"),
            Path(r"C:\Program Files (x86)\WinSCP\WinSCP.exe"),
        ],
        which="WinSCP",
    )
    winscp_com = None
    if winscp_path is not None:
        candidate = winscp_path.with_name("WinSCP.com")
        if candidate.is_file():
            winscp_com = candidate
    puttygen = None
    if putty_path is not None:
        candidate = putty_path.with_name("puttygen.exe")
        if candidate.is_file():
            puttygen = candidate
    if puttygen is None:
        puttygen = _resolve(
            None,
            env="HOSTSKEEPER_PUTTYGEN",
            candidates=[
                Path(r"C:\Program Files\PuTTY\puttygen.exe"),
                Path(r"C:\Program Files (x86)\PuTTY\puttygen.exe"),
            ],
            which="puttygen",
        )
    return LauncherPaths(
        putty=putty_path,
        winscp=winscp_path,
        winscp_com=winscp_com,
        puttygen=puttygen,
    )


def _resolve(
    explicit: str | None,
    *,
    env: str,
    candidates: list[Path],
    which: str,
) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    env_names = [env]
    if env.startswith("HOSTSKEEPER_"):
        env_names.append("HOSTSSAFE_" + env[len("HOSTSKEEPER_") :])
    for env_name in env_names:
        env_val = os.environ.get(env_name)
        if env_val:
            path = Path(env_val)
            if path.is_file():
                return path
    for cand in candidates:
        if cand.is_file():
            return cand
    found = shutil.which(which)
    return Path(found) if found else None


def launch_putty(
    paths: LauncherPaths,
    address: Address,
    credential: Credential,
    *,
    remote_command: str | None = None,
) -> None:
    _maybe_knock(address)
    args = build_putty_args(
        paths, address, credential, remote_command=remote_command
    )
    subprocess.Popen(args, close_fds=False)  # noqa: S603


def launch_winscp(paths: LauncherPaths, address: Address, credential: Credential) -> None:
    _maybe_knock(address)
    args = build_winscp_args(paths, address, credential)
    subprocess.Popen(args, close_fds=False)  # noqa: S603


def build_putty_args(
    paths: LauncherPaths,
    address: Address,
    credential: Credential,
    *,
    remote_command: str | None = None,
) -> list[str]:
    """Build PuTTY argv. May start a named-pipe server for ``-pwfile``."""
    if paths.putty is None:
        raise FileNotFoundError("putty.exe not found")
    # Never put password on CLI (visible in process list).
    target = f"{credential.username}@{address.host}"
    args = [str(paths.putty), "-ssh", target, "-P", str(address.port)]
    if credential.private_key:
        key_path = _materialize_ppk(paths, credential.private_key, credential.passphrase)
        args.extend(["-i", str(key_path)])
    elif credential.password:
        pipe_path = serve_named_pipe_bytes(
            (credential.password + "\n").encode("utf-8")
        )
        args.extend(["-pwfile", pipe_path])
    if remote_command:
        # -m closes the session when the remote command exits; keep an
        # interactive shell so the user can read output and close PuTTY.
        cmd_path = _write_temp_text(
            _putty_remote_keep_open(remote_command), suffix=".cmd"
        )
        args.extend(["-t", "-m", str(cmd_path)])
    return args


def _putty_remote_keep_open(script: str) -> str:
    """Wrap script so PuTTY stays open after it finishes (interactive shell)."""
    body = script.rstrip("\n")
    # Single remote command: run body, then replace process with a login shell.
    inner = body + "\nexec \"$SHELL\" -l"
    return "bash -lc " + shlex.quote(inner)


def build_winscp_args(
    paths: LauncherPaths, address: Address, credential: Credential
) -> list[str]:
    """Build WinSCP argv for GUI (Explorer/Commander), no secrets in argv.

    Passwords/passphrases go through named pipes with ``/passwordsfromfiles``
    (WinSCP reads ``/password=`` / ``/passphrase=`` as file paths).
    """
    if paths.winscp is None:
        raise FileNotFoundError("WinSCP.exe not found")
    user = quote(credential.username, safe="")
    host = address.host
    port = address.port
    url = f"sftp://{user}@{host}:{port}/"
    args = [str(paths.winscp), url, "/hostkey=acceptnew"]

    need_secret_files = False
    if credential.private_key:
        key_path = _materialize_ppk(
            paths, credential.private_key, credential.passphrase
        )
        args.append(f"/privatekey={key_path}")
        if credential.passphrase:
            # No trailing newline — WinSCP uses the file contents as the secret.
            pipe = serve_named_pipe_bytes(credential.passphrase.encode("utf-8"))
            args.append(f"/passphrase={pipe}")
            need_secret_files = True
    elif credential.password:
        pipe = serve_named_pipe_bytes(credential.password.encode("utf-8"))
        args.append(f"/password={pipe}")
        need_secret_files = True

    if need_secret_files:
        args.append("/passwordsfromfiles")
    return args


def serve_named_pipe_bytes(payload: bytes, *, connect_timeout_ms: int = 30_000) -> str:
    """Create a local Windows named pipe and serve ``payload`` once to the next reader.

    Returns ``\\\\.\\pipe\\...`` path for PuTTY ``-pwfile`` /
    WinSCP ``/password=`` + ``/passwordsfromfiles``.
    """
    if os.name != "nt":
        raise RuntimeError("named-pipe password handoff is only supported on Windows")

    import ctypes
    from ctypes import wintypes

    pipe_name = rf"\\.\pipe\hostskeeper-{uuid.uuid4().hex}"

    PIPE_ACCESS_OUTBOUND = 0x00000002
    FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
    PIPE_TYPE_BYTE = 0x00000000
    PIPE_WAIT = 0x00000000
    PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    ERROR_PIPE_CONNECTED = 535

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.ConnectNamedPipe.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    kernel32.DisconnectNamedPipe.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.CancelIoEx.restype = wintypes.BOOL

    created = threading.Event()
    errors: list[BaseException] = []
    handle_box: list[int] = []

    def _worker() -> None:
        handle = kernel32.CreateNamedPipeW(
            pipe_name,
            PIPE_ACCESS_OUTBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            1,
            max(len(payload), 4096),
            4096,
            connect_timeout_ms,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            errors.append(OSError(ctypes.get_last_error(), "CreateNamedPipeW failed"))
            created.set()
            return
        handle_box.append(int(handle))
        created.set()
        try:
            ok = kernel32.ConnectNamedPipe(handle, None)
            if not ok:
                err = ctypes.get_last_error()
                if err != ERROR_PIPE_CONNECTED:
                    errors.append(OSError(err, "ConnectNamedPipe failed"))
                    return
            written = wintypes.DWORD(0)
            buf = (ctypes.c_char * len(payload)).from_buffer_copy(payload)
            if not kernel32.WriteFile(
                handle, buf, len(payload), ctypes.byref(written), None
            ):
                errors.append(OSError(ctypes.get_last_error(), "WriteFile failed"))
                return
            kernel32.FlushFileBuffers(handle)
        finally:
            kernel32.DisconnectNamedPipe(handle)
            kernel32.CloseHandle(handle)

    thread = threading.Thread(target=_worker, name="hostskeeper-pw-pipe", daemon=True)
    thread.start()
    if not created.wait(timeout=3.0):
        raise RuntimeError("timed out creating password named pipe")
    if errors:
        raise errors[0]

    def _watchdog() -> None:
        thread.join(timeout=connect_timeout_ms / 1000.0)
        if thread.is_alive() and handle_box:
            # Unblock ConnectNamedPipe if no client arrived.
            kernel32.CancelIoEx(wintypes.HANDLE(handle_box[0]), None)
            kernel32.CloseHandle(wintypes.HANDLE(handle_box[0]))

    threading.Thread(target=_watchdog, name="hostskeeper-pw-pipe-wd", daemon=True).start()
    return pipe_name


def read_named_pipe_bytes(pipe_path: str, *, timeout_sec: float = 5.0) -> bytes:
    """Test/helper: open a HostsKeeper outbound pipe as a client and read all bytes."""
    if os.name != "nt":
        raise RuntimeError("named pipes only on Windows")

    import ctypes
    import time
    from ctypes import wintypes

    GENERIC_READ = 0x80000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL

    deadline = time.time() + timeout_sec
    last_err = 0
    while time.time() < deadline:
        kernel32.WaitNamedPipeW(pipe_path, 500)
        handle = kernel32.CreateFileW(
            pipe_path,
            GENERIC_READ,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            last_err = ctypes.get_last_error()
            time.sleep(0.05)
            continue
        try:
            chunks: list[bytes] = []
            while True:
                buf = ctypes.create_string_buffer(4096)
                read_n = wintypes.DWORD(0)
                ok = kernel32.ReadFile(handle, buf, 4096, ctypes.byref(read_n), None)
                if not ok or read_n.value == 0:
                    break
                chunks.append(buf.raw[: read_n.value])
            return b"".join(chunks)
        finally:
            kernel32.CloseHandle(handle)
    raise OSError(last_err, f"cannot read named pipe {pipe_path!r}")


def _write_temp_text(content: str, *, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix="hostskeeper-", suffix=suffix)
    path = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content if content.endswith("\n") else content + "\n")
    _TEMP_FILES.append(path)
    return path


def _looks_like_ppk(text: str) -> bool:
    return "PuTTY-User-Key-File-" in text


def _materialize_ppk(
    paths: LauncherPaths,
    key_text: str,
    passphrase: str | None,
) -> Path:
    """Return a temp .ppk path for PuTTY/WinSCP (convert OpenSSH PEM when needed)."""
    if _looks_like_ppk(key_text):
        return _write_temp_text(key_text, suffix=".ppk")

    openssh_path = _write_temp_text(key_text, suffix=".pem")
    fd, ppk_name = tempfile.mkstemp(prefix="hostskeeper-", suffix=".ppk")
    os.close(fd)
    ppk_path = Path(ppk_name)
    _TEMP_FILES.append(ppk_path)

    if paths.winscp_com is not None:
        cmd = [
            str(paths.winscp_com),
            "/keygen",
            str(openssh_path),
            f"/output={ppk_path}",
        ]
        completed = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and ppk_path.is_file():
            return ppk_path

    if paths.puttygen is not None:
        cmd = [str(paths.puttygen), str(openssh_path), "-o", str(ppk_path), "-O", "private"]
        if passphrase:
            cmd.extend(["-P", passphrase])
        completed = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and ppk_path.is_file():
            return ppk_path

    raise RuntimeError(
        "cannot convert OpenSSH key to PuTTY .ppk (need WinSCP.com /keygen or puttygen)"
    )
