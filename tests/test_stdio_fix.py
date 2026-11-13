"""stdio fix for windowed frozen builds."""

from __future__ import annotations

import sys

from hostskeeper.runtime.stdio_fix import ensure_stdio


def test_ensure_stdio_replaces_none(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdin", None)
    ensure_stdio()
    assert sys.stdout is not None
    assert sys.stderr is not None
    assert sys.stdin is not None
    # Must be callable — uvicorn ColorFormatter crashes if stream is None.
    assert callable(getattr(sys.stdout, "isatty", None))
    sys.stdout.isatty()
    sys.stderr.isatty()
