from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.drop_tree import DropTreeWidget
from hostskeeper.desktop.main_window import MainWindow
from hostskeeper.runtime.state import AppState


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_workspace_has_independent_host_and_script_tree_panes(
    qapp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    state = AppState(vault_path=tmp_path / "test.vault", mcp_key="test-key")
    window = MainWindow(state)
    try:
        window.show()
        qapp.processEvents()
        assert window._hosts_tree is not window._scripts_tree
        assert window._hosts_tree.topLevelItemCount() == 1
        assert window._hosts_root.text(0) == "Hosts"
        assert window._scripts_tree.topLevelItemCount() == 1
        assert window._scripts_root.text(0) == "Scripts"
        assert window._workspace_splitter.orientation() == Qt.Orientation.Vertical
        assert window._workspace_splitter.count() == 2
        assert (
            window._workspace_splitter.sizes()[0]
            > window._workspace_splitter.sizes()[1]
        )
        assert not window._workspace_splitter.styleSheet()
        assert (
            window._workspace_splitter.widget(0).findChild(DropTreeWidget)
            is window._hosts_tree
        )
        assert (
            window._workspace_splitter.widget(1).findChild(DropTreeWidget)
            is window._scripts_tree
        )
    finally:
        window.close()
