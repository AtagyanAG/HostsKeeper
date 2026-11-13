"""Static assets (app icon, etc.)."""

from __future__ import annotations

import sys
from pathlib import Path


def app_icon_path() -> Path | None:
    """Path to hostskeeper.ico (dev package or PyInstaller bundle)."""
    name = "hostskeeper.ico"
    candidates: list[Path] = [Path(__file__).resolve().parent / name]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        candidates.extend(
            [
                base / "hostskeeper" / "resources" / name,
                base / "resources" / name,
                base / name,
            ]
        )
    for path in candidates:
        if path.is_file():
            return path
    return None
