"""Terminal key mapping (no SSH)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyte")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.terminal_widget import TerminalWidget, qt_key_to_pty
import pyte


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _key(key: int, text: str = "", *, ctrl: bool = False) -> QKeyEvent:
    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    return QKeyEvent(QKeyEvent.Type.KeyPress, key, mods, text)


def test_qt_key_to_pty_basics(qapp) -> None:
    assert qt_key_to_pty(_key(Qt.Key.Key_Return)) == "\r"
    assert qt_key_to_pty(_key(Qt.Key.Key_Backspace)) == "\x7f"
    assert qt_key_to_pty(_key(Qt.Key.Key_Up)) == "\x1b[A"
    assert qt_key_to_pty(_key(Qt.Key.Key_C, "c", ctrl=True)) == "\x03"
    assert qt_key_to_pty(_key(Qt.Key.Key_A, "a")) == "a"
    assert qt_key_to_pty(_key(0, "ж")) == "ж"


def test_qt_key_to_pty_function_keys(qapp) -> None:
    assert qt_key_to_pty(_key(Qt.Key.Key_F1)) == "\x1bOP"
    assert qt_key_to_pty(_key(Qt.Key.Key_F5)) == "\x1b[15~"
    assert qt_key_to_pty(_key(Qt.Key.Key_F10)) == "\x1b[21~"
    assert qt_key_to_pty(_key(Qt.Key.Key_F12)) == "\x1b[24~"


def test_terminal_feed_ansi_colors(qapp) -> None:
    w = TerminalWidget()
    w.feed("\x1b[1;32mOK\x1b[0m\r\n")
    line = w._screen.display[0]
    assert "OK" in line
    ch = w._screen.buffer[0][0]
    assert ch.data == "O"
    assert ch.fg == "green"
    assert ch.bold is True


def test_pyte_clears_for_cup(qapp) -> None:
    """Cursor addressing used by top-like UIs."""
    screen = pyte.Screen(40, 10)
    stream = pyte.Stream(screen)
    stream.feed("aaaa\r\nbbbb\r\n")
    stream.feed("\x1b[H\x1b[2J")  # home + clear
    assert all(row.strip() == "" for row in screen.display)
