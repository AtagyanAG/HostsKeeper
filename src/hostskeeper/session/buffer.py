"""Sequential output buffer with opaque cursor for session_read."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class BufferRead:
    data: str
    cursor: str
    truncated: bool = False


class OutputBuffer:
    """Append-only text buffer; cursor is a decimal character offset."""

    def __init__(self, max_chars: int = 1_000_000) -> None:
        self._lock = threading.Lock()
        self._chunks: list[str] = []
        self._size = 0
        self._max_chars = max_chars
        self._dropped = 0

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._chunks.append(text)
            self._size += len(text)
            while self._size > self._max_chars and self._chunks:
                dropped = self._chunks.pop(0)
                self._size -= len(dropped)
                self._dropped += len(dropped)

    def snapshot(self) -> str:
        with self._lock:
            return "".join(self._chunks)

    def read_since(self, cursor: str | None = None, max_chars: int = 65536) -> BufferRead:
        with self._lock:
            start = self._parse_cursor(cursor)
            absolute_start = self._dropped
            if start < absolute_start:
                start = absolute_start
            relative = start - absolute_start
            blob = "".join(self._chunks)
            if relative > len(blob):
                relative = len(blob)
                start = absolute_start + relative
            piece = blob[relative : relative + max_chars]
            truncated = (relative + len(piece)) < len(blob)
            new_cursor = str(start + len(piece))
            return BufferRead(data=piece, cursor=new_cursor, truncated=truncated)

    def cursor_end(self) -> str:
        with self._lock:
            return str(self._dropped + self._size)

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None or cursor == "":
            return 0
        try:
            value = int(cursor)
        except ValueError as exc:
            raise ValueError(f"invalid cursor: {cursor!r}") from exc
        if value < 0:
            raise ValueError(f"invalid cursor: {cursor!r}")
        return value
