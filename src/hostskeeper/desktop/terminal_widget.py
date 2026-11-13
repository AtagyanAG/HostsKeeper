"""VT100-ish terminal view: pyte screen + Qt paint; publishes screen to MCP via UI."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QScrollBar, QWidget

import pyte
from pyte.screens import Char

from hostskeeper.desktop.alt_screen import AltAwareScreen

# Selection highlight (PuTTY-like inverse blue).
_SEL_BG = QColor("#264f78")
_SEL_FG = QColor("#ffffff")

# ANSI named colors used by pyte → QColor
_FG: dict[str, QColor] = {
    "black": QColor("#0c0c0c"),
    "red": QColor("#c50f1f"),
    "green": QColor("#13a10e"),
    "brown": QColor("#c19c00"),
    "yellow": QColor("#c19c00"),
    "blue": QColor("#0037da"),
    "magenta": QColor("#881798"),
    "cyan": QColor("#3a96dd"),
    "white": QColor("#cccccc"),
    "default": QColor("#cccccc"),
}
_BG: dict[str, QColor] = {
    "black": QColor("#0c0c0c"),
    "red": QColor("#c50f1f"),
    "green": QColor("#13a10e"),
    "brown": QColor("#c19c00"),
    "yellow": QColor("#c19c00"),
    "blue": QColor("#0037da"),
    "magenta": QColor("#881798"),
    "cyan": QColor("#3a96dd"),
    "white": QColor("#cccccc"),
    "default": QColor("#0c0c0c"),
}
_BRIGHT: dict[str, QColor] = {
    "black": QColor("#767676"),
    "red": QColor("#e74856"),
    "green": QColor("#16c60c"),
    "brown": QColor("#f9f1a5"),
    "yellow": QColor("#f9f1a5"),
    "blue": QColor("#3b78ff"),
    "magenta": QColor("#b4009e"),
    "cyan": QColor("#61d6d6"),
    "white": QColor("#f2f2f2"),
}


# xterm / TERM=xterm function keys (htop, less, mc, …).
_FKEY_TO_PTY: dict[int, str] = {
    Qt.Key.Key_F1: "\x1bOP",
    Qt.Key.Key_F2: "\x1bOQ",
    Qt.Key.Key_F3: "\x1bOR",
    Qt.Key.Key_F4: "\x1bOS",
    Qt.Key.Key_F5: "\x1b[15~",
    Qt.Key.Key_F6: "\x1b[17~",
    Qt.Key.Key_F7: "\x1b[18~",
    Qt.Key.Key_F8: "\x1b[19~",
    Qt.Key.Key_F9: "\x1b[20~",
    Qt.Key.Key_F10: "\x1b[21~",
    Qt.Key.Key_F11: "\x1b[23~",
    Qt.Key.Key_F12: "\x1b[24~",
}


def normalize_selection(
    a: tuple[int, int], b: tuple[int, int]
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Order two (col, row) cells so start <= end in reading order."""
    ax, ay = a
    bx, by = b
    if (ay, ax) <= (by, bx):
        return (ax, ay), (bx, by)
    return (bx, by), (ax, ay)


def selection_plain_text(
    lines: list[str],
    start: tuple[int, int],
    end: tuple[int, int],
) -> str:
    """Extract rectangular-by-line selection from plain lines (cols may be shorter).

    ``start``/``end`` are inclusive (col, row) in view coordinates.
    Trailing spaces on each selected segment are stripped; multi-line uses ``\\n``.
    """
    (x0, y0), (x1, y1) = normalize_selection(start, end)
    if not lines or y0 > y1:
        return ""
    y0 = max(0, y0)
    y1 = min(len(lines) - 1, y1)
    out: list[str] = []
    for y in range(y0, y1 + 1):
        line = lines[y]
        if y0 == y1:
            seg = line[x0 : x1 + 1]
        elif y == y0:
            seg = line[x0:]
        elif y == y1:
            seg = line[: x1 + 1]
        else:
            seg = line
        out.append(seg.rstrip(" "))
    return "\n".join(out)


def qt_key_to_pty(event: QKeyEvent) -> str | None:
    """Map Qt key event to bytes/chars for an xterm-like PTY."""
    key = event.key()
    mods = event.modifiers()
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)

    # Clipboard shortcuts are handled by TerminalWidget (PuTTY-style).
    if key == Qt.Key.Key_Insert and (shift or ctrl):
        return None

    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return "\r"
    if key == Qt.Key.Key_Backspace:
        return "\x7f"
    if key == Qt.Key.Key_Delete:
        return "\x1b[3~"
    if key == Qt.Key.Key_Tab:
        return "\t"
    if key == Qt.Key.Key_Escape:
        return "\x1b"
    if key == Qt.Key.Key_Home:
        return "\x1b[H" if not ctrl else "\x1b[1;5H"
    if key == Qt.Key.Key_End:
        return "\x1b[F" if not ctrl else "\x1b[1;5F"
    if key == Qt.Key.Key_PageUp:
        return "\x1b[5~"
    if key == Qt.Key.Key_PageDown:
        return "\x1b[6~"
    if key == Qt.Key.Key_Insert:
        return "\x1b[2~"
    if key == Qt.Key.Key_Up:
        return "\x1b[A"
    if key == Qt.Key.Key_Down:
        return "\x1b[B"
    if key == Qt.Key.Key_Right:
        return "\x1b[C"
    if key == Qt.Key.Key_Left:
        return "\x1b[D"

    fseq = _FKEY_TO_PTY.get(key)
    if fseq is not None:
        return fseq

    if ctrl and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(key - Qt.Key.Key_A + 1)
    if ctrl and key in (Qt.Key.Key_BracketLeft,):
        return "\x1b"  # Ctrl+[
    if ctrl and key == Qt.Key.Key_Backslash:
        return "\x1c"
    if ctrl and key == Qt.Key.Key_Space:
        return "\x00"

    text = event.text()
    if not text:
        return None
    if alt and len(text) == 1:
        return "\x1b" + text
    # Printable / UTF-8 characters (incl. Cyrillic)
    if text == "\n":
        return "\r"
    return text


def _fg_color(ch: Char) -> QColor:
    name = (ch.fg or "default").lower()
    if ch.bold and name in _BRIGHT:
        return _BRIGHT[name]
    if name.startswith("#") and len(name) == 7:
        return QColor(name)
    return _FG.get(name, _FG["default"])


def _bg_color(ch: Char) -> QColor:
    name = (ch.bg or "default").lower()
    if name.startswith("#") and len(name) == 7:
        return QColor(name)
    return _BG.get(name, _BG["default"])


class TerminalWidget(QWidget):
    """Interactive terminal surface bound to a session PTY via signals."""

    data_out = Signal(str)  # raw text to write to PTY (submit=False)
    size_changed = Signal(int, int)  # cols, rows

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._font = QFont("Consolas")
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setPointSize(10)
        self.setFont(self._font)
        self._fm = QFontMetrics(self._font)
        self._cell_w = max(1, self._fm.horizontalAdvance("M"))
        self._cell_h = max(1, self._fm.height())
        self._cols = 80
        self._rows = 24
        self._screen = AltAwareScreen(self._cols, self._rows)
        self._stream = pyte.Stream(self._screen)
        self._live = True
        # Lines scrolled up from live bottom (0 = following output).
        self._view_offset = 0
        self._scroll_updating = False
        self._scroll = QScrollBar(Qt.Orientation.Vertical, self)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll.valueChanged.connect(self._on_scroll_value)
        self._scroll.hide()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._emit_size)
        self.setMinimumSize(self._cell_w * 40, self._cell_h * 10)
        # PuTTY-style selection: drag LMB → copy on release; RMB / Shift+Ins paste.
        self._sel_anchor: tuple[int, int] | None = None
        self._sel_end: tuple[int, int] | None = None
        self._selecting = False

    @property
    def cols(self) -> int:
        return self._cols

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def view_offset(self) -> int:
        return self._view_offset

    def set_live(self, live: bool) -> None:
        self._live = live

    @property
    def alt_screen(self) -> bool:
        return bool(self._screen.alt_screen)

    def screen_text(self) -> str:
        """Plain-text visible screen (no CSI). Live buffer, not scrolled view."""
        return self._screen.screen_text()

    def reset(self) -> None:
        self._view_offset = 0
        self._screen.reset()
        self._screen.clear_alt_state()
        self._screen.dirty.update(range(self._screen.lines))
        self._sync_scrollbar()
        self.update()

    def feed(self, text: str) -> None:
        if not text:
            return
        at_bottom = self._view_offset == 0
        self._stream.feed(text)
        if self._screen.alt_screen or at_bottom:
            self._view_offset = 0
        else:
            self._view_offset = min(self._view_offset, self._max_offset())
        self._sync_scrollbar()
        self.update()

    def scroll_by(self, lines: int) -> None:
        """Scroll view by ``lines`` (positive = toward older history)."""
        if self._screen.alt_screen or lines == 0:
            return
        self._set_view_offset(self._view_offset + lines)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.MouseButton.RightButton:
            self._paste_clipboard()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._paste_clipboard()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._pos_to_cell(event.position().toPoint())
            self._sel_anchor = cell
            self._sel_end = cell
            self._selecting = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._selecting and self._sel_anchor is not None:
            cell = self._pos_to_cell(event.position().toPoint())
            if cell != self._sel_end:
                self._sel_end = cell
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            if self._sel_anchor is not None:
                self._sel_end = self._pos_to_cell(event.position().toPoint())
            text = self.selected_text()
            if text:
                QGuiApplication.clipboard().setText(text)
            else:
                self.clear_selection()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # PuTTY: Ctrl+Insert = copy selection; Shift+Insert = paste.
        if key == Qt.Key.Key_Insert and ctrl and not shift:
            text = self.selected_text()
            if text:
                QGuiApplication.clipboard().setText(text)
            event.accept()
            return
        if key == Qt.Key.Key_Insert and shift and not ctrl:
            self._paste_clipboard()
            event.accept()
            return

        if not self._live:
            super().keyPressEvent(event)
            return
        payload = qt_key_to_pty(event)
        if payload is None:
            super().keyPressEvent(event)
            return
        self.data_out.emit(payload)
        event.accept()

    def clear_selection(self) -> None:
        self._sel_anchor = None
        self._sel_end = None
        self._selecting = False

    def selected_text(self) -> str:
        """Plain text of the current selection (empty if none)."""
        if self._sel_anchor is None or self._sel_end is None:
            return ""
        lines = self._view_plain_lines()
        return selection_plain_text(lines, self._sel_anchor, self._sel_end)

    def _paste_clipboard(self) -> None:
        if not self._live:
            return
        clip = QGuiApplication.clipboard()
        text = clip.text() if clip is not None else ""
        if not text:
            return
        # Normalize Windows newlines for PTY (CRLF → CR; bare LF → CR).
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r")
        self.data_out.emit(text)

    def _pos_to_cell(self, pos: QPoint) -> tuple[int, int]:
        col = max(0, min(self._cols - 1, pos.x() // self._cell_w))
        row = max(0, min(self._rows - 1, pos.y() // self._cell_h))
        return col, row

    def _view_plain_lines(self) -> list[str]:
        """Visible rows as plain strings (same mapping as paint)."""
        screen = self._screen
        hlen = 0 if screen.alt_screen else screen.history_len()
        offset = 0 if screen.alt_screen else self._view_offset
        view_start = hlen - offset
        lines: list[str] = []
        for y in range(screen.lines):
            virt = view_start + y
            if virt < hlen:
                line = screen.history.top[virt]
            else:
                sy = virt - hlen
                if not (0 <= sy < screen.lines):
                    lines.append("")
                    continue
                line = screen.buffer[sy]
            chars: list[str] = []
            for x in range(screen.columns):
                ch = line[x]
                chars.append(ch.data if ch.data else " ")
            lines.append("".join(chars))
        return lines

    def _cell_selected(self, x: int, y: int) -> bool:
        if self._sel_anchor is None or self._sel_end is None:
            return False
        (x0, y0), (x1, y1) = normalize_selection(self._sel_anchor, self._sel_end)
        if y < y0 or y > y1:
            return False
        if y0 == y1:
            return x0 <= x <= x1
        if y == y0:
            return x >= x0
        if y == y1:
            return x <= x1
        return True

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._screen.alt_screen:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        # Wheel up → older history (increase offset).
        steps = max(1, abs(delta) // 120)
        if delta > 0:
            self._set_view_offset(self._view_offset + steps)
        else:
            self._set_view_offset(self._view_offset - steps)
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_scrollbar()
        self._resize_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._layout_scrollbar()
        self._apply_geometry_size(emit=True)

    def _emit_size(self) -> None:
        self._apply_geometry_size(emit=True)

    def _scrollbar_width(self) -> int:
        if not self._scroll.isVisible():
            return 0
        return max(self._scroll.sizeHint().width(), self._scroll.width())

    def _content_width(self) -> int:
        return max(0, self.width() - self._scrollbar_width())

    def _layout_scrollbar(self) -> None:
        w = max(self._scroll.sizeHint().width(), 12)
        self._scroll.setGeometry(self.width() - w, 0, w, self.height())

    def _max_offset(self) -> int:
        if self._screen.alt_screen:
            return 0
        return self._screen.history_len()

    def _set_view_offset(self, offset: int) -> None:
        offset = max(0, min(int(offset), self._max_offset()))
        if offset == self._view_offset:
            self._sync_scrollbar()
            return
        self._view_offset = offset
        self._sync_scrollbar()
        self.update()

    def _sync_scrollbar(self) -> None:
        max_off = self._max_offset()
        self._scroll_updating = True
        try:
            self._scroll.setRange(0, max_off)
            self._scroll.setPageStep(max(1, self._rows))
            self._scroll.setSingleStep(1)
            # Qt: 0 = top (oldest). Our offset: 0 = live bottom.
            self._scroll.setValue(max_off - self._view_offset)
            if max_off > 0:
                self._scroll.show()
            else:
                self._scroll.hide()
        finally:
            self._scroll_updating = False
        self._layout_scrollbar()

    def _on_scroll_value(self, value: int) -> None:
        if self._scroll_updating:
            return
        max_off = self._max_offset()
        self._view_offset = max(0, max_off - int(value))
        self.update()

    def _apply_geometry_size(self, *, emit: bool) -> None:
        cols = max(20, self._content_width() // self._cell_w)
        rows = max(5, self.height() // self._cell_h)
        if cols == self._cols and rows == self._rows:
            if emit:
                self.size_changed.emit(cols, rows)
            return
        self._cols = cols
        self._rows = rows
        self._screen.resize(lines=rows, columns=cols)
        self._view_offset = min(self._view_offset, self._max_offset())
        self._sync_scrollbar()
        self.update()
        if emit:
            self.size_changed.emit(cols, rows)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), _BG["default"])
        painter.setFont(self._font)
        screen = self._screen
        cursor = screen.cursor
        hlen = 0 if screen.alt_screen else screen.history_len()
        offset = 0 if screen.alt_screen else self._view_offset
        view_start = hlen - offset
        paint_cols = min(screen.columns, max(1, self._content_width() // self._cell_w))

        for y in range(screen.lines):
            virt = view_start + y
            if virt < hlen:
                line = screen.history.top[virt]
            else:
                sy = virt - hlen
                if not (0 <= sy < screen.lines):
                    continue
                line = screen.buffer[sy]
            for x in range(paint_cols):
                ch = line[x]
                data = ch.data if ch.data else " "
                fg = _fg_color(ch)
                bg = _bg_color(ch)
                if ch.reverse:
                    fg, bg = bg, fg
                selected = self._cell_selected(x, y)
                if selected:
                    fg, bg = _SEL_FG, _SEL_BG
                rect_x = x * self._cell_w
                rect_y = y * self._cell_h
                if bg != _BG["default"] or ch.reverse or selected:
                    painter.fillRect(rect_x, rect_y, self._cell_w, self._cell_h, bg)
                painter.setPen(fg)
                painter.drawText(
                    rect_x,
                    rect_y + self._fm.ascent(),
                    data,
                )

        # Block cursor only on the live edge (not while scrolled back).
        if offset == 0 and not cursor.hidden:
            cx, cy = cursor.x, cursor.y
            if 0 <= cy < screen.lines and 0 <= cx < paint_cols:
                painter.fillRect(
                    cx * self._cell_w,
                    cy * self._cell_h,
                    self._cell_w,
                    self._cell_h,
                    QColor(204, 204, 204, 160),
                )
        painter.end()
