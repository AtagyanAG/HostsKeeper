"""pyte HistoryScreen with DEC alternate-screen (CSI ?1049/1047/47)."""

from __future__ import annotations

from typing import Any

import pyte
from pyte.screens import Char, HistoryScreen


_ALT_MODES = frozenset({47, 1047, 1049})

# Scrollback lines kept in history.top (overflow drops oldest).
DEFAULT_HISTORY = 10_000


class AltAwareScreen(HistoryScreen):
    """Restores primary buffer on alt-screen exit (htop/vim/less).

    Scrollback uses :class:`~pyte.screens.HistoryScreen` (``history.top``).
    While ``alt_screen`` is active, ``index`` does not push into history so
    full-screen TUIs do not pollute scrollback.
    """

    def __init__(
        self,
        columns: int,
        lines: int,
        history: int = DEFAULT_HISTORY,
    ) -> None:
        super().__init__(columns, lines, history=history)
        self.alt_screen = False
        self._saved_buffer: dict[int, dict[int, Char]] | None = None
        self._saved_cursor: tuple[int, int, bool] | None = None

    def screen_text(self) -> str:
        """Visible screen as plain text (no CSI), one line per row."""
        return "\n".join(line.rstrip() for line in self.display)

    def history_len(self) -> int:
        return len(self.history.top)

    def set_mode(self, *modes: int, **kwargs: Any) -> None:
        if kwargs.get("private") and _ALT_MODES.intersection(modes):
            self._enter_alt()
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs: Any) -> None:
        leaving = bool(kwargs.get("private") and _ALT_MODES.intersection(modes))
        super().reset_mode(*modes, **kwargs)
        if leaving:
            self._leave_alt()

    def clear_alt_state(self) -> None:
        self.alt_screen = False
        self._saved_buffer = None
        self._saved_cursor = None

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        super().resize(lines=lines, columns=columns)
        # Primary snapshot may no longer match geometry.
        if self._saved_buffer is not None:
            self._saved_buffer = None
            self._saved_cursor = None

    def index(self) -> None:
        if self.alt_screen:
            pyte.Screen.index(self)
            return
        HistoryScreen.index(self)

    def reverse_index(self) -> None:
        if self.alt_screen:
            pyte.Screen.reverse_index(self)
            return
        HistoryScreen.reverse_index(self)

    def _enter_alt(self) -> None:
        if self.alt_screen:
            return
        self._saved_buffer, self._saved_cursor = self._snapshot()
        self.alt_screen = True
        self.erase_in_display(2)
        self.cursor_position()
        self.dirty.update(range(self.lines))

    def _leave_alt(self) -> None:
        if not self.alt_screen:
            return
        saved = self._saved_buffer
        cursor = self._saved_cursor
        self._saved_buffer = None
        self._saved_cursor = None
        self.alt_screen = False
        if saved is None or cursor is None:
            self.erase_in_display(2)
            self.cursor_position()
        else:
            self._restore(saved, cursor)
        self.dirty.update(range(self.lines))

    def _snapshot(self) -> tuple[dict[int, dict[int, Char]], tuple[int, int, bool]]:
        buf: dict[int, dict[int, Char]] = {}
        for y in range(self.lines):
            line = self.buffer[y]
            buf[y] = {x: line[x] for x in range(self.columns)}
        cur = (self.cursor.x, self.cursor.y, bool(self.cursor.hidden))
        return buf, cur

    def _restore(
        self,
        saved: dict[int, dict[int, Char]],
        cursor: tuple[int, int, bool],
    ) -> None:
        self.erase_in_display(2)
        for y, line in saved.items():
            if y >= self.lines:
                continue
            dest = self.buffer[y]
            for x, ch in line.items():
                if x < self.columns:
                    dest[x] = ch
        x, y, hidden = cursor
        self.cursor.x = min(max(0, x), max(0, self.columns - 1))
        self.cursor.y = min(max(0, y), max(0, self.lines - 1))
        self.cursor.hidden = hidden
