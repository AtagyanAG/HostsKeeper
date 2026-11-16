from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.dialogs import HostDialog
from hostskeeper.vault import Host, Vault


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_host_dialog_title_uses_host_name(
    qapp, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vault = Vault.create(tmp_path / "test.vault", "test-password")
    host = vault.add_host(Host(name="Alum"))

    edit_dialog = HostDialog(vault, host=host)
    new_dialog = HostDialog(vault)
    try:
        assert edit_dialog.windowTitle() == "Alum"
        assert new_dialog.windowTitle() == "New Host"
    finally:
        edit_dialog.close()
        new_dialog.close()
