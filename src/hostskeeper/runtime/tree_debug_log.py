"""Append-only debug log for tree expand/collapse (crash hunting).

Log file: ``hostskeeper-tree.log`` in the application launch directory
(frozen: next to the exe; otherwise process cwd). Every line is flushed.
``faulthandler`` is also enabled on the same file for native crashes.
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

_LOG_NAME = "hostskeeper-tree.log"
_fp = None
_lock = threading.Lock()
_faulthandler_on = False
_session_logged = False


def launch_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def log_path() -> Path:
    return launch_dir() / _LOG_NAME


def _write_line_unlocked(line: str) -> None:
    global _fp
    if _fp is None or _fp.closed:
        return
    _fp.write(line + "\n")
    _fp.flush()


def _ensure_open_unlocked() -> None:
    global _fp, _faulthandler_on, _session_logged
    if _fp is not None and not _fp.closed:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _fp = path.open("a", encoding="utf-8", buffering=1)  # line-buffered
    if not _faulthandler_on:
        try:
            faulthandler.enable(file=_fp, all_threads=True)
            _faulthandler_on = True
        except Exception:  # noqa: BLE001
            pass
    if not _session_logged:
        _session_logged = True
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        tid = threading.current_thread().name
        _write_line_unlocked(
            f"{ts} {tid} session tree debug log opened "
            f"path={path} cwd={Path.cwd()} argv0={sys.argv[0]!r} "
            f"frozen={getattr(sys, 'frozen', False)}"
        )


def log(event: str, message: str = "", **fields: object) -> None:
    """Write one timestamped line; never raises to callers."""
    try:
        with _lock:
            _ensure_open_unlocked()
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            tid = threading.current_thread().name
            extra = " ".join(f"{k}={v!r}" for k, v in fields.items())
            parts = [ts, tid, event]
            if message:
                parts.append(message)
            if extra:
                parts.append(extra)
            _write_line_unlocked(" ".join(parts))
    except Exception:  # noqa: BLE001
        return


def log_exception(event: str, exc: BaseException, **fields: object) -> None:
    log(
        event,
        f"{type(exc).__name__}: {exc}",
        traceback="".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).replace("\n", " | "),
        **fields,
    )
