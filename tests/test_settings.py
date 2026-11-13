"""App settings persistence (no secrets)."""

from __future__ import annotations

import json
from pathlib import Path

from hostskeeper.runtime import settings as settings_mod


def test_settings_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = settings_mod.AppSettings.load()
    assert s.vault_paths == []
    assert s.last_vault_path is None

    vault = tmp_path / "HostsKeeper" / "a.vault"
    s.add_vault_path(vault)
    assert s.last_vault_path == str(vault)
    assert str(vault) in s.vault_paths

    loaded = settings_mod.AppSettings.load()
    assert loaded.last_vault_path == str(vault)
    assert loaded.vault_paths == [str(vault)]

    other = tmp_path / "HostsKeeper" / "b.vault"
    loaded.add_vault_path(other)
    loaded.remove_vault_path(vault)
    again = settings_mod.AppSettings.load()
    assert again.vault_paths == [str(other)]
    assert again.last_vault_path == str(other)


def test_default_vault_path_under_appdata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert settings_mod.default_vault_path() == Path(tmp_path) / "HostsKeeper" / "default.vault"
    assert settings_mod.settings_path() == Path(tmp_path) / "HostsKeeper" / "settings.json"


def test_settings_load_legacy_hostssafe_appdata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy_dir = tmp_path / "HostsSafe"
    legacy_dir.mkdir(parents=True)
    vault = legacy_dir / "old.vault"
    (legacy_dir / "settings.json").write_text(
        json.dumps(
            {
                "vault_nodes": [
                    {
                        "id": "v1",
                        "kind": "vault",
                        "path": str(vault),
                    }
                ],
                "last_vault_path": str(vault),
            }
        ),
        encoding="utf-8",
    )
    loaded = settings_mod.AppSettings.load()
    assert loaded.last_vault_path == str(vault)
    loaded.save()
    assert (tmp_path / "HostsKeeper" / "settings.json").is_file()


def test_rename_vault_path_updates_list_and_last(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = settings_mod.AppSettings.load()
    old = tmp_path / "HostsKeeper" / "old.vault"
    new = tmp_path / "HostsKeeper" / "new.vault"
    s.add_vault_path(old)
    assert s.last_vault_path == str(old)
    s.rename_vault_path(old, new)
    loaded = settings_mod.AppSettings.load()
    assert loaded.vault_paths == [str(new)]
    assert loaded.last_vault_path == str(new)


def test_tab_connect_timeout_default_and_persist(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = settings_mod.AppSettings.load()
    assert s.tab_connect_timeout_sec == 3
    s.tab_connect_timeout_sec = 10
    s.save()
    loaded = settings_mod.AppSettings.load()
    assert loaded.tab_connect_timeout_sec == 10


def test_tab_connect_timeout_migrates_legacy_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = settings_mod.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"vault_nodes": [], "tab_approve_timeout_sec": 7}',
        encoding="utf-8",
    )
    loaded = settings_mod.AppSettings.load()
    assert loaded.tab_connect_timeout_sec == 7


def test_launcher_paths_persist_and_ensure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    fake_putty = tmp_path / "putty.exe"
    fake_putty.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOSTSKEEPER_PUTTY", str(fake_putty))
    monkeypatch.delenv("HOSTSKEEPER_WINSCP", raising=False)

    s = settings_mod.AppSettings.load()
    assert s.putty_path is None
    s.ensure_launcher_paths()
    assert s.putty_path == str(fake_putty)
    loaded = settings_mod.AppSettings.load()
    assert loaded.putty_path == str(fake_putty)

    # Saved path is not overwritten by ensure.
    other = tmp_path / "other-putty.exe"
    other.write_text("", encoding="utf-8")
    loaded.putty_path = str(other)
    loaded.save()
    monkeypatch.setenv("HOSTSKEEPER_PUTTY", str(fake_putty))
    again = settings_mod.AppSettings.load()
    again.ensure_launcher_paths()
    assert again.putty_path == str(other)


def test_vault_groups_and_move(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    s = settings_mod.AppSettings.load()
    vault = tmp_path / "HostsKeeper" / "a.vault"
    s.add_vault_path(vault)
    group = s.add_vault_group("Lab")
    node = next(n for n in s.vault_nodes if n.kind == "vault")
    s.move_vault_node(node.id, group.id)
    loaded = settings_mod.AppSettings.load()
    moved = next(n for n in loaded.vault_nodes if n.kind == "vault")
    assert moved.parent_id == group.id
    loaded.delete_vault_group(group.id)
    again = settings_mod.AppSettings.load()
    assert all(n.kind != "group" for n in again.vault_nodes)
    assert next(n for n in again.vault_nodes if n.kind == "vault").parent_id is None
