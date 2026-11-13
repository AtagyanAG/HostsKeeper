"""Fix stdio for frozen windowed builds (PyInstaller --noconsole)."""

from __future__ import annotations

import os
import sys


def ensure_stdio() -> None:
    """Replace None stdio streams so logging/uvicorn ``isatty()`` does not crash.

    With ``console=False`` PyInstaller sets ``sys.stdout`` / ``stderr`` to ``None``.
    uvicorn's DefaultFormatter then fails during MCP HTTP start on unlock.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r", encoding="utf-8", errors="replace")
