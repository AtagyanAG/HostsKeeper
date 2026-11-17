from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.options_dialog import OptionsDialog
from hostskeeper.runtime.settings import AppSettings


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_debug_log_is_transient(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    settings = AppSettings()
    dialog = OptionsDialog(settings, debug_log_enabled=True)
    try:
        assert dialog.debug_log_enabled
        dialog._save()

        raw = json.loads(
            (tmp_path / "HostsKeeper" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        assert "debug_log" not in raw
        assert "debug_log_enabled" not in raw

        reopened = OptionsDialog(AppSettings.load())
        try:
            assert not reopened.debug_log_enabled
        finally:
            reopened.close()
    finally:
        dialog.close()
