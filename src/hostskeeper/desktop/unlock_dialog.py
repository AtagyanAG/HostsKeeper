"""Password dialog to connect (unlock/create) a selected vault path."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from hostskeeper.runtime.state import AppState
from hostskeeper.vault.errors import InvalidPasswordError


class UnlockDialog(QDialog):
    """Ask password for a fixed vault path (create if file missing)."""

    def __init__(self, state: AppState, vault_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._state = state
        self._vault_path = Path(vault_path)
        self.setWindowTitle("HostsKeeper — Connect vault")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._path_label = QLabel(str(self._vault_path))
        self._path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._path_label.setWordWrap(True)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        # Do not connect returnPressed: Enter already activates the default
        # OK button (accepted), so a second handler would show errors twice.

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        if self._vault_path.exists():
            self._hint.setText("Enter password to unlock the vault.")
        else:
            self._hint.setText(
                "Vault file not found — a new vault will be created at this path."
            )

        form = QFormLayout()
        form.addRow("Vault", self._path_label)
        form.addRow("Password", self._password)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_unlock)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Connect")
            ok.setDefault(True)
            ok.setAutoDefault(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)

        self._password.setFocus(Qt.FocusReason.OtherFocusReason)
        self._busy = False

    def _try_unlock(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            password = self._password.text()
            if not password:
                QMessageBox.warning(self, "HostsKeeper", "Password is required.")
                return
            self._state.vault_path = self._vault_path
            try:
                self._vault_path.parent.mkdir(parents=True, exist_ok=True)
                self._state.unlock(password)
            except InvalidPasswordError:
                QMessageBox.critical(
                    self, "HostsKeeper", "Invalid password or corrupt vault."
                )
                self._password.selectAll()
                self._password.setFocus(Qt.FocusReason.OtherFocusReason)
                return
            except OSError as exc:
                QMessageBox.critical(self, "HostsKeeper", f"Cannot open vault:\n{exc}")
                return
            self.accept()
        finally:
            self._busy = False

