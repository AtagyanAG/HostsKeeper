"""Alternate screen restore + session snapshot publish."""

from __future__ import annotations

from uuid import uuid4

import pyte
import pytest

from hostskeeper.desktop.alt_screen import AltAwareScreen
from hostskeeper.session.manager import SessionManager
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
from hostskeeper.session.manager import _SessionState
from hostskeeper.vault import Vault


def test_alt_screen_restores_primary() -> None:
    screen = AltAwareScreen(40, 8)
    stream = pyte.Stream(screen)
    stream.feed("shell-prompt>\r\n")
    assert "shell-prompt>" in screen.screen_text()
    assert screen.alt_screen is False

    stream.feed("\x1b[?1049h")
    assert screen.alt_screen is True
    stream.feed("\x1b[H\x1b[2JHTOP-UI")
    assert "HTOP-UI" in screen.screen_text()
    assert "shell-prompt>" not in screen.screen_text()

    stream.feed("\x1b[?1049l")
    assert screen.alt_screen is False
    text = screen.screen_text()
    assert "shell-prompt>" in text
    assert "HTOP-UI" not in text


def test_update_screen_snapshot_roundtrip(tmp_path) -> None:
    vault = Vault.create(tmp_path / "snap.vault", "pass")
    sessions = SessionManager(vault)
    info = SessionInfo(
        id=uuid4(),
        alias="t-1",
        status=SessionStatus.LIVE,
        host_id=uuid4(),
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
    )
    with sessions._lock:
        sessions._sessions[info.id] = _SessionState(info=info)

    sessions.update_screen_snapshot(
        info.id, screen_tail="line1\nline2", alt_screen=True
    )
    tail, alt = sessions.get_screen_snapshot(info.id)
    assert tail == "line1\nline2"
    assert alt is True
    sessions.close(info.id)


@pytest.mark.parametrize("seq", ["\x1b[?1049h", "\x1b[?1047h", "\x1b[?47h"])
def test_alt_modes_enter(seq: str) -> None:
    screen = AltAwareScreen(20, 5)
    stream = pyte.Stream(screen)
    stream.feed("abc")
    stream.feed(seq)
    assert screen.alt_screen is True
