"""Terminal selection / clipboard helpers (no SSH)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyte")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.terminal_widget import (
    TerminalWidget,
    normalize_selection,
    qt_key_to_pty,
    selection_plain_text,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_normalize_selection_order() -> None:
    assert normalize_selection((5, 2), (1, 0)) == ((1, 0), (5, 2))
    assert normalize_selection((1, 1), (3, 1)) == ((1, 1), (3, 1))


def test_selection_plain_text_single_line() -> None:
    lines = ["hello world", "second"]
    assert selection_plain_text(lines, (0, 0), (4, 0)) == "hello"
    assert selection_plain_text(lines, (6, 0), (10, 0)) == "world"


def test_selection_plain_text_multiline() -> None:
    lines = ["abcde", "fghij", "klmno"]
    assert selection_plain_text(lines, (2, 0), (1, 2)) == "cde\nfghij\nkl"


def test_selection_strips_trailing_spaces() -> None:
    lines = ["hi   "]
    assert selection_plain_text(lines, (0, 0), (4, 0)) == "hi"


def test_qt_key_insert_clipboard_not_pty(qapp) -> None:
    shift = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Insert,
        Qt.KeyboardModifier.ShiftModifier,
    )
    ctrl = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Insert,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert qt_key_to_pty(shift) is None
    assert qt_key_to_pty(ctrl) is None


def test_widget_selected_text_from_feed(qapp) -> None:
    w = TerminalWidget()
    w.feed("hello\r\nworld\r\n")
    w._sel_anchor = (0, 0)
    w._sel_end = (4, 0)
    assert w.selected_text() == "hello"
    w._sel_anchor = (0, 0)
    w._sel_end = (4, 1)
    assert w.selected_text() == "hello\nworld"


def test_paste_emits_data_out(qapp) -> None:
    from PySide6.QtGui import QGuiApplication

    w = TerminalWidget()
    got: list[str] = []
    w.data_out.connect(got.append)
    QGuiApplication.clipboard().setText("a\r\nb")
    w._paste_clipboard()
    assert got == ["a\rb"]
