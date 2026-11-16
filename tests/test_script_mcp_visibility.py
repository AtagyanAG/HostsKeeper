from __future__ import annotations

import os

import pytest
from PySide6.QtWidgets import QApplication

from hostskeeper.desktop.dialogs import ScriptDialog
from hostskeeper.desktop.folder_icon import note_icon, script_icon
from hostskeeper.vault import Script, Vault


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _red_pixel_count(icon) -> int:
    image = icon.pixmap(16, 16).toImage()
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if (color := image.pixelColor(x, y)).red() > 150
        and color.green() < 100
        and color.blue() < 100
    )


def test_disabled_mcp_icons_have_thin_red_frames(qapp) -> None:
    assert _red_pixel_count(script_icon(mcp_enabled=False)) > 0
    assert _red_pixel_count(note_icon(mcp_enabled=False)) > 0
    assert _red_pixel_count(script_icon(mcp_enabled=True)) == 0
    assert _red_pixel_count(note_icon(mcp_enabled=True)) == 0


def test_script_dialog_persists_mcp_visibility(
    qapp, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    vault = Vault.create(tmp_path / "visibility.vault", "test-password")
    script = vault.add_script(
        Script(name="existing", body="echo old", mcp_enabled=True)
    )
    edit_dialog = ScriptDialog(vault, script=script)
    new_dialog = ScriptDialog(vault)
    try:
        assert edit_dialog._mcp.isChecked()
        edit_dialog._mcp.setChecked(False)
        edit_dialog._save()
        assert vault.get_script(script.id).mcp_enabled is False

        assert not new_dialog._mcp.isChecked()
        new_dialog._name.setText("new")
        new_dialog._body.setPlainText("echo new")
        new_dialog._mcp.setChecked(True)
        new_dialog._save()
        assert new_dialog.result_script is not None
        assert new_dialog.result_script.mcp_enabled is True
    finally:
        edit_dialog.close()
        new_dialog.close()
