"""Terminal scrollback (HistoryScreen) — no SSH."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyte")

import pyte
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.alt_screen import DEFAULT_HISTORY, AltAwareScreen
from hostskeeper.desktop.terminal_widget import TerminalWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _hist_line(screen: AltAwareScreen, idx: int) -> str:
    line = screen.history.top[idx]
    return "".join(line[x].data for x in range(screen.columns)).rstrip()


def test_history_accumulates_and_preserves_on_disconnect_semantics() -> None:
    screen = AltAwareScreen(40, 5, history=20)
    stream = pyte.Stream(screen)
    for i in range(12):
        stream.feed(f"line-{i}\r\n")
    assert screen.history_len() == 8
    assert _hist_line(screen, 0) == "line-0"
    assert "line-11" in screen.screen_text()
    # reset clears history (reconnect / close path)
    screen.reset()
    assert screen.history_len() == 0


def test_history_limit_drops_oldest() -> None:
    screen = AltAwareScreen(20, 3, history=5)
    stream = pyte.Stream(screen)
    for i in range(20):
        stream.feed(f"L{i}\r\n")
    assert screen.history_len() == 5
    assert screen.history.top.maxlen == 5
    assert _hist_line(screen, 0).startswith("L")


def test_default_history_limit_is_10000() -> None:
    assert DEFAULT_HISTORY == 10_000
    screen = AltAwareScreen(10, 4)
    assert screen.history.top.maxlen == 10_000


def test_alt_screen_does_not_pollute_history() -> None:
    screen = AltAwareScreen(40, 6, history=50)
    stream = pyte.Stream(screen)
    stream.feed("before-alt\r\n")
    for _ in range(8):
        stream.feed("keep\r\n")
    hist_before = screen.history_len()
    assert hist_before > 0

    stream.feed("\x1b[?1049h")
    assert screen.alt_screen is True
    for i in range(30):
        stream.feed(f"alt-{i}\r\n")
    assert screen.history_len() == hist_before

    stream.feed("\x1b[?1049l")
    assert screen.alt_screen is False
    assert screen.history_len() == hist_before
    assert "before-alt" in screen.screen_text() or hist_before > 0


def test_scrollback_text_includes_history_and_screen() -> None:
    screen = AltAwareScreen(40, 4, history=20)
    stream = pyte.Stream(screen)
    for i in range(10):
        stream.feed(f"hist-{i}\r\n")
    text = screen.scrollback_text()
    assert "hist-0" in text
    assert "hist-9" in text
    # Live rows after overflow into history still present.
    assert text.count("\n") >= 3


def test_widget_scrollback_text(qapp) -> None:
    w = TerminalWidget()
    w.resize(80 * w._cell_w + 20, 6 * w._cell_h)
    w._apply_geometry_size(emit=False)
    for i in range(20):
        w.feed(f"row-{i}\r\n")
    blob = w.scrollback_text()
    assert "row-0" in blob
    assert "row-19" in blob


def test_widget_scroll_offset_and_alt_disables(qapp) -> None:
    w = TerminalWidget()
    w.resize(80 * w._cell_w + 20, 8 * w._cell_h)
    w._apply_geometry_size(emit=False)
    for i in range(30):
        w.feed(f"row-{i}\r\n")
    assert w._screen.history_len() > 0
    assert w.view_offset == 0

    w.scroll_by(5)
    assert w.view_offset == 5

    w.feed("\x1b[?1049h")
    assert w.alt_screen is True
    assert w.view_offset == 0
    w.scroll_by(3)
    assert w.view_offset == 0

    w.feed("\x1b[?1049l")
    assert w.alt_screen is False
    w.scroll_by(4)
    assert w.view_offset == 4

    w.reset()
    assert w.view_offset == 0
    assert w._screen.history_len() == 0
