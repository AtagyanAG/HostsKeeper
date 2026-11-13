from pathlib import Path
from uuid import uuid4

from hostskeeper.launchers import (
    _materialize_ppk,
    _putty_remote_keep_open,
    build_putty_args,
    build_winscp_args,
    discover_launchers,
    read_named_pipe_bytes,
    serve_named_pipe_bytes,
)
from hostskeeper.vault.models import Address, Credential
from tests.lab_env import KEY_PATH, lab_key_available

_LAB_USER = "labuser"


def test_discover_launchers_on_this_machine() -> None:
    paths = discover_launchers()
    assert paths.putty is not None
    assert paths.putty.name.lower() == "putty.exe"
    assert paths.winscp is not None
    assert paths.winscp.name.lower() == "winscp.exe"
    assert paths.winscp_com is not None or paths.puttygen is not None


def test_convert_openssh_to_ppk() -> None:
    if not lab_key_available():
        return
    paths = discover_launchers()
    pem = KEY_PATH.read_text(encoding="utf-8")
    ppk = _materialize_ppk(paths, pem, None)
    assert ppk.is_file()
    text = ppk.read_text(encoding="utf-8", errors="replace")
    assert "PuTTY-User-Key-File-" in text


def test_named_pipe_roundtrip() -> None:
    secret = b"pipe-secret-value\n"
    path = serve_named_pipe_bytes(secret, connect_timeout_ms=5_000)
    assert path.startswith(r"\\.\pipe\hostskeeper-")
    got = read_named_pipe_bytes(path)
    assert got == secret


def test_putty_password_uses_pwfile_not_argv() -> None:
    paths = discover_launchers()
    if paths.putty is None:
        return
    password = f"s3cret-{uuid4().hex}"
    host_id = uuid4()
    address = Address(host_id=host_id, host="192.0.2.10", port=22, label="lab")
    credential = Credential(host_id=host_id, username=_LAB_USER, password=password)
    args = build_putty_args(paths, address, credential)
    joined = " ".join(args)
    assert "-pwfile" in args
    assert password not in joined
    assert "-pw" not in args
    pipe = args[args.index("-pwfile") + 1]
    payload = read_named_pipe_bytes(pipe)
    assert payload.decode("utf-8") == password + "\n"


def test_winscp_password_uses_gui_passwordsfromfiles() -> None:
    paths = discover_launchers()
    if paths.winscp is None:
        return
    password = f"s3cret-{uuid4().hex}"
    host_id = uuid4()
    address = Address(host_id=host_id, host="192.0.2.10", port=22, label="lab")
    credential = Credential(host_id=host_id, username=_LAB_USER, password=password)
    args = build_winscp_args(paths, address, credential)
    joined = " ".join(args)
    assert "/console" not in args
    assert "/passwordsfromfiles" in args
    assert any(a.startswith("/password=") for a in args)
    assert password not in joined
    assert any(a.startswith(f"sftp://{_LAB_USER}@") for a in args)
    pw_arg = next(a for a in args if a.startswith("/password="))
    pipe = pw_arg.split("=", 1)[1]
    payload = read_named_pipe_bytes(pipe)
    assert payload.decode("utf-8") == password


def test_putty_remote_command_keeps_shell_open() -> None:
    wrapped = _putty_remote_keep_open("echo hello\nuptime")
    assert wrapped.startswith("bash -lc ")
    assert 'exec "$SHELL" -l' in wrapped
    assert "echo hello" in wrapped
    paths = discover_launchers()
    if paths.putty is None:
        return
    host_id = uuid4()
    address = Address(host_id=host_id, host="192.0.2.10", port=22)
    credential = Credential(host_id=host_id, username=_LAB_USER, password="x")
    args = build_putty_args(
        paths, address, credential, remote_command="echo hi"
    )
    assert "-t" in args
    assert "-m" in args
    cmd_file = Path(args[args.index("-m") + 1])
    text = cmd_file.read_text(encoding="utf-8")
    assert 'exec "$SHELL" -l' in text


def test_winscp_key_without_passphrase_uses_gui_url() -> None:
    paths = discover_launchers()
    if paths.winscp is None or (paths.winscp_com is None and paths.puttygen is None):
        return
    if not lab_key_available():
        return
    host_id = uuid4()
    address = Address(host_id=host_id, host="192.0.2.10", port=22, label="lab")
    credential = Credential(
        host_id=host_id,
        username=_LAB_USER,
        private_key=KEY_PATH.read_text(encoding="utf-8"),
    )
    args = build_winscp_args(paths, address, credential)
    assert "/console" not in args
    assert "/passwordsfromfiles" not in args
    assert any(a.startswith(f"sftp://{_LAB_USER}@") for a in args)
    assert any(a.startswith("/privatekey=") for a in args)
    assert not any(a.startswith("/password=") for a in args)
