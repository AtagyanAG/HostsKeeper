"""Application Options (launcher paths)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from hostskeeper.runtime.settings import AppSettings


class OptionsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Options")
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
        form.addRow("PuTTY", putty_row)
        form.addRow("WinSCP", winscp_row)
        form.addRow("Tab connect timeout", self._tab_timeout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setMinimumWidth(520)

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
