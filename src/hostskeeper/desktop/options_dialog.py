"""Application Options (settings path, launcher paths, MCP)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from hostskeeper.runtime.settings import AppSettings, settings_path


class OptionsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent=None,
        *,
        on_copy_mcp_config: Callable[[], None] | None = None,
        on_change_mcp_key: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._on_copy_mcp_config = on_copy_mcp_config
        self._on_change_mcp_key = on_change_mcp_key
        self.setWindowTitle("Options")
        self._settings_file = QLineEdit(str(settings_path()))
        self._settings_file.setReadOnly(True)
        self._settings_file.setToolTip(
            "Fixed location of settings.json (cannot be changed here)."
        )
        self._putty = QLineEdit(settings.putty_path or "")
        self._winscp = QLineEdit(settings.winscp_path or "")
        self._putty.setPlaceholderText("putty.exe")
        self._winscp.setPlaceholderText("WinSCP.exe")
        self._tab_timeout = QSpinBox()
        self._tab_timeout.setRange(1, 600)
        self._tab_timeout.setSuffix(" s")
        self._tab_timeout.setValue(int(settings.tab_connect_timeout_sec or 3))
        self._tab_timeout.setToolTip(
            "Abort Tab SSH connect if the server does not answer in time (default 3 s)."
        )

        settings_row = QHBoxLayout()
        settings_row.addWidget(self._settings_file, stretch=1)
        btn_settings_folder = QPushButton("Open Folder")
        btn_settings_folder.setToolTip("Open Explorer with settings.json selected.")
        btn_settings_folder.clicked.connect(self._open_settings_folder)
        btn_settings_edit = QPushButton("Edit")
        btn_settings_edit.setToolTip("Open settings.json in Notepad.")
        btn_settings_edit.clicked.connect(self._edit_settings)
        settings_row.addWidget(btn_settings_folder)
        settings_row.addWidget(btn_settings_edit)

        putty_row = QHBoxLayout()
        putty_row.addWidget(self._putty, stretch=1)
        btn_putty = QPushButton("Browse…")
        btn_putty.clicked.connect(self._browse_putty)
        btn_putty_clear = QPushButton("Clear")
        btn_putty_clear.clicked.connect(self._putty.clear)
        putty_row.addWidget(btn_putty)
        putty_row.addWidget(btn_putty_clear)

        winscp_row = QHBoxLayout()
        winscp_row.addWidget(self._winscp, stretch=1)
        btn_winscp = QPushButton("Browse…")
        btn_winscp.clicked.connect(self._browse_winscp)
        btn_winscp_clear = QPushButton("Clear")
        btn_winscp_clear.clicked.connect(self._winscp.clear)
        winscp_row.addWidget(btn_winscp)
        winscp_row.addWidget(btn_winscp_clear)

        form = QFormLayout()
        form.addRow("Settings", settings_row)
        form.addRow("PuTTY", putty_row)
        form.addRow("WinSCP", winscp_row)
        form.addRow("Tab connect timeout", self._tab_timeout)

        mcp_row = QHBoxLayout()
        btn_mcp = QPushButton("Copy MCP config")
        btn_mcp.setToolTip(
            "Copy Cursor MCP JSON (HTTP URL + app key) to the clipboard."
        )
        btn_mcp.clicked.connect(self._copy_mcp)
        if on_copy_mcp_config is None:
            btn_mcp.setEnabled(False)
        btn_change_key = QPushButton("Change MCP Key")
        btn_change_key.setToolTip(
            "Generate a new app key (old Cursor mcp.json URL stops working)."
        )
        btn_change_key.clicked.connect(self._change_mcp_key)
        if on_change_mcp_key is None:
            btn_change_key.setEnabled(False)
        mcp_row.addWidget(btn_mcp)
        mcp_row.addWidget(btn_change_key)
        mcp_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("MCP"))
        layout.addLayout(mcp_row)
        layout.addWidget(buttons)
        self.setMinimumWidth(520)

    def _copy_mcp(self) -> None:
        if self._on_copy_mcp_config is not None:
            self._on_copy_mcp_config()

    def _change_mcp_key(self) -> None:
        if self._on_change_mcp_key is not None:
            self._on_change_mcp_key()

    def _open_settings_folder(self) -> None:
        path = settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                self._settings.save()
            # Highlight the file in Explorer (Windows).
            subprocess.Popen(  # noqa: S603
                ["explorer", f"/select,{path}"],
                close_fds=False,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Settings", f"Could not open folder:\n{exc}")

    def _edit_settings(self) -> None:
        path = settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                self._settings.save()
            subprocess.Popen(  # noqa: S603
                ["notepad.exe", str(path)],
                close_fds=False,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Settings", f"Could not open Notepad:\n{exc}")

    def _browse_putty(self) -> None:
        start = self._putty.text().strip() or r"C:\Program Files\PuTTY"
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select putty.exe",
            start,
            "Executable (*.exe);;All files (*.*)",
        )
        if path:
            self._putty.setText(path)

    def _browse_winscp(self) -> None:
        start = self._winscp.text().strip() or ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select WinSCP.exe",
            start,
            "Executable (*.exe);;All files (*.*)",
        )
        if path:
            self._winscp.setText(path)

    def _save(self) -> None:
        putty = self._putty.text().strip() or None
        winscp = self._winscp.text().strip() or None
        if putty:
            putty = str(Path(putty).expanduser())
        if winscp:
            winscp = str(Path(winscp).expanduser())
        self._settings.putty_path = putty
        self._settings.winscp_path = winscp
        self._settings.tab_connect_timeout_sec = int(self._tab_timeout.value())
        self._settings.save()
        self.accept()
