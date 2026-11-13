"""CLI entry smoke (no GUI)."""

from hostskeeper import __version__
from hostskeeper.__main__ import main


def test_version_flag(capsys) -> None:
    assert main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == f"HostsKeeper {__version__}"


def test_web_ui_retired() -> None:
    assert main(["--ui", "web"]) == 2


def test_runtime_app_state_roundtrip(tmp_path) -> None:
    from hostskeeper.runtime import AppState

    path = tmp_path / "t.vault"
    state = AppState(vault_path=path)
    state.unlock("secret-pass")
    assert state.unlocked
    assert state.sessions is not None
    assert state.mcp_service is not None
    state.lock()
    assert not state.unlocked
    assert state.sessions is None
