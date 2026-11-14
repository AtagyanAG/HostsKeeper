"""Desktop application bootstrap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.main_window import MainWindow
from hostskeeper.resources import app_icon_path
from hostskeeper.runtime.mcp_http import stop_mcp_http
from hostskeeper.runtime.settings import AppSettings, default_vault_path
from hostskeeper.runtime.state import AppState


def run_desktop(
    *,
    vault_path: Path | str | None = None,
    mcp_host: str = "0.0.0.0",
    mcp_port: int = 8765,
    mcp_key: str | None = None,
) -> int:
    settings = AppSettings.load()
    if vault_path is not None:
        path = Path(vault_path)
    elif os.environ.get("HOSTSKEEPER_VAULT") or os.environ.get("HOSTSSAFE_VAULT"):
        path = Path(
            os.environ.get("HOSTSKEEPER_VAULT") or os.environ["HOSTSSAFE_VAULT"]
        )
    elif settings.last_vault_path:
        path = Path(settings.last_vault_path)
    else:
        path = default_vault_path()

    state = AppState(
        vault_path=path,
        mcp_host=mcp_host,
        mcp_port=mcp_port,
        mcp_key=mcp_key or "",
    )

    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(sys.argv)
        app.setApplicationName("HostsKeeper")
        app.setOrganizationName("HostsKeeper")

    assert app is not None

    icon_file = app_icon_path()
    if icon_file is not None:
        icon = QIcon(str(icon_file))
        app.setWindowIcon(icon)
    else:
        icon = None

    def _on_quit() -> None:
        # Safety net if window closeEvent was skipped.
        stop_mcp_http()
        if state.unlocked:
            state.lock()

    app.aboutToQuit.connect(_on_quit)

    from hostskeeper.runtime.tree_debug_log import log, log_path

    log("app_start", f"tree log at {log_path()}")

    window = MainWindow(state)
    if icon is not None:
        window.setWindowIcon(icon)
    window.show()
    if owns_app:
        return int(app.exec())
    return 0
