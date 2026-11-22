from __future__ import annotations

import os
from uuid import uuid4

import pytest
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.dialogs import HostDialog
from hostskeeper.desktop.session_tab import SessionTab
from hostskeeper.session.manager import SessionManager, _SessionState
from hostskeeper.session.models import SessionInfo, SessionStatus, SessionTarget
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
        assert [
            edit_dialog._tabs.tabText(index)
            for index in range(edit_dialog._tabs.count())
        ] == ["Host", "Scripts", "Description"]
    finally:
        edit_dialog.close()
        new_dialog.close()


def test_host_dialog_mcp_permission_defaults_off_and_saves(
    qapp, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vault = Vault.create(tmp_path / "host-mcp.vault", "test-password")
    dialog = HostDialog(vault)
    try:
        assert not dialog._mcp.isChecked()
        dialog._name.setText("allowed")
        dialog._mcp.setChecked(True)
        dialog._save()
        assert dialog.result_host is not None
        assert dialog.result_host.mcp_enabled is True
        assert vault.get_host(dialog.result_host.id).mcp_enabled is True
    finally:
        dialog.close()


def test_disabling_host_mcp_disables_and_unchecks_approve(
    qapp, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vault = Vault.create(tmp_path / "approve.vault", "test-password")
    host = vault.add_host(Host(name="lab", mcp_enabled=True))
    sessions = SessionManager(vault)
    info = SessionInfo(
        id=uuid4(),
        alias="lab-admin-1",
        status=SessionStatus.CONNECTING,
        host_id=host.id,
        address_id=uuid4(),
        credential_id=uuid4(),
        target=SessionTarget.TAB,
        mcp_enabled=True,
        approve_enabled=True,
    )
    with sessions._lock:
        sessions._sessions[info.id] = _SessionState(info=info)

    tab = SessionTab(sessions, info.id)
    dialog = HostDialog(
        vault,
        host=host,
        on_host_mcp_changed=lambda changed: sessions.sync_host_mcp_access(
            changed.id
        ),
    )
    tab._timer.stop()
    try:
        assert tab._approve.isEnabled()
        assert tab._approve.isChecked()

        dialog._mcp.setChecked(False)
        tab.refresh_chrome()

        assert vault.get_host(host.id).mcp_enabled is False
        assert not tab._approve.isEnabled()
        assert not tab._approve.isChecked()
        assert sessions.get(info.id).approve_enabled is False
    finally:
        tab._timer.stop()
        tab.close()
        dialog.close()
        sessions.close(info.id)
