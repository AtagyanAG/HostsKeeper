"""Vault encrypt/decrypt and CRUD tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hostskeeper.vault import (
    Address,
    Credential,
    Group,
    Host,
    InvalidPasswordError,
    Note,
    Script,
    ScriptParameter,
    Vault,
)


def test_create_roundtrip_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "demo.vault"
    vault = Vault.create(path, "correct-horse")

    host = vault.add_host(Host(name="lab", tags=["test"]))
    address = vault.add_address(
        Address(host_id=host.id, host="10.0.0.1", port=22, label="lan")
    )
    credential = vault.add_credential(
        Credential(
            host_id=host.id,
            username="labuser",
            password="s3cret",
            private_key="-----BEGIN KEY-----\nabc\n-----END KEY-----",
            passphrase="key-pass",
        )
    )
    host.default_address_id = address.id
    host.default_credential_id = credential.id
    vault.update_host(host)
    vault.add_script(
        Script(
            name="uptime",
            body="uptime",
            parameters=[ScriptParameter(name="unused", required=False, default="")],
        )
    )
    vault.lock()

    again = Vault(path)
    again.unlock("correct-horse")
    hosts = again.list_hosts()
    assert len(hosts) == 1
    assert hosts[0].name == "lab"
    assert hosts[0].mcp_enabled is False
    assert hosts[0].default_address_id == address.id
    assert hosts[0].default_credential_id == credential.id
    assert again.get_address(address.id).host == "10.0.0.1"
    cred = again.get_credential(credential.id)
    assert cred.password == "s3cret"
    assert cred.private_key is not None
    assert cred.auth_type == "password"
    assert again.get_script_by_name("uptime").body == "uptime"


def test_host_mcp_defaults_off_and_migrates_legacy_dict() -> None:
    host = Host(name="legacy")
    assert host.mcp_enabled is False

    legacy_data = host.to_dict()
    legacy_data.pop("mcp_enabled")
    restored = Host.from_dict(legacy_data)
    assert restored.mcp_enabled is False


def test_bulk_set_mcp_flags_persists_all_entity_types(tmp_path: Path) -> None:
    path = tmp_path / "bulk-mcp.vault"
    vault = Vault.create(path, "pw")
    host = vault.add_host(Host(name="lab"))
    script = vault.add_script(Script(name="run", body="true"))
    note = vault.add_note(Note(name="docs", body="text"))

    changed = vault.bulk_set_mcp_flags(
        enabled=True,
        host_ids=[host.id],
        script_ids=[script.id],
        note_ids=[note.id],
    )
    assert changed is True
    assert vault.bulk_set_mcp_flags(enabled=True, host_ids=[host.id]) is False
    vault.lock()

    reopened = Vault(path)
    reopened.unlock("pw")
    assert reopened.get_host(host.id).mcp_enabled is True
    assert reopened.get_script(script.id).mcp_enabled is True
    assert reopened.get_note(note.id).mcp_enabled is True


def test_credential_auth_type_validation(tmp_path: Path) -> None:
    from hostskeeper.vault.errors import ValidationError
    from hostskeeper.vault.models import AUTH_KEY_PAIR, AUTH_OPENSSH_CONFIG

    vault = Vault.create(tmp_path / "auth.vault", "pw")
    host = vault.add_host(Host(name="h"))
    with pytest.raises(ValidationError, match="password auth requires"):
        vault.add_credential(Credential(host_id=host.id, username="u"))
    key_cred = vault.add_credential(
        Credential(
            host_id=host.id,
            username="u",
            private_key="-----BEGIN KEY-----\nx\n-----END KEY-----",
        )
    )
    assert key_cred.auth_type == AUTH_KEY_PAIR
    agent = vault.add_credential(
        Credential(
            host_id=host.id,
            username="u",
            auth_type=AUTH_OPENSSH_CONFIG,
            label="agent",
        )
    )
    assert agent.auth_type == AUTH_OPENSSH_CONFIG
    assert agent.password is None
    assert agent.private_key is None


def test_credential_keeps_unused_secrets_when_auth_type_changes(tmp_path: Path) -> None:
    from hostskeeper.vault.models import (
        AUTH_KEY_PAIR,
        AUTH_OPENSSH_CONFIG,
        AUTH_PASSWORD,
    )

    vault = Vault.create(tmp_path / "keep.vault", "pw")
    host = vault.add_host(Host(name="h"))
    cred = vault.add_credential(
        Credential(
            host_id=host.id,
            username="u",
            auth_type=AUTH_PASSWORD,
            password="keep-me",
            private_key="-----BEGIN KEY-----\nold\n-----END KEY-----",
            passphrase="pp",
        )
    )
    cred.auth_type = AUTH_KEY_PAIR
    updated = vault.update_credential(cred)
    assert updated.auth_type == AUTH_KEY_PAIR
    assert updated.password == "keep-me"
    assert updated.private_key is not None
    assert updated.passphrase == "pp"

    updated.auth_type = AUTH_OPENSSH_CONFIG
    agent = vault.update_credential(updated)
    assert agent.auth_type == AUTH_OPENSSH_CONFIG
    assert agent.password == "keep-me"
    assert agent.private_key is not None
    assert agent.passphrase == "pp"

    agent.auth_type = AUTH_PASSWORD
    back = vault.update_credential(agent)
    assert back.auth_type == AUTH_PASSWORD
    assert back.password == "keep-me"


def test_wrong_password_rejected(tmp_path: Path) -> None:
    path = tmp_path / "demo.vault"
    Vault.create(path, "right-password")
    with pytest.raises(InvalidPasswordError):
        Vault(path).unlock("wrong-password")


def test_script_parameter_user_value_seeds_from_default() -> None:
    seeded = ScriptParameter.from_dict(
        {"name": "t", "required": True, "default": "seed-me"}
    )
    assert seeded.user_value == "seed-me"
    explicit = ScriptParameter.from_dict(
        {
            "name": "t",
            "required": True,
            "default": "seed-me",
            "user_value": "mine",
        }
    )
    assert explicit.user_value == "mine"
    cleared = ScriptParameter.from_dict(
        {
            "name": "t",
            "required": True,
            "default": "seed-me",
            "user_value": None,
        }
    )
    assert cleared.user_value is None


def test_script_parameter_user_value_roundtrip(tmp_path: Path) -> None:
    vault = Vault.create(tmp_path / "uv.vault", "pw")
    script = vault.add_script(
        Script(
            name="s",
            body="echo {{t}}",
            parameters=[
                ScriptParameter(
                    name="t",
                    required=True,
                    default="d",
                    user_value="secret-user",
                )
            ],
        )
    )
    vault.lock()
    again = Vault(tmp_path / "uv.vault")
    again.unlock("pw")
    loaded = again.get_script(script.id)
    assert loaded.parameters[0].default == "d"
    assert loaded.parameters[0].user_value == "secret-user"
    assert "secret-user" not in repr(loaded.parameters[0])
    assert "user_value=***" in repr(loaded.parameters[0])


def test_credential_repr_redacts_secrets() -> None:
    cred = Credential(
        host_id=Host(name="x").id,
        username="user",
        password="plain-password",
        private_key="PRIVATEKEYMATERIAL",
        passphrase="key-secret-99",
    )
    text = repr(cred)
    assert "plain-password" not in text
    assert "PRIVATEKEYMATERIAL" not in text
    assert "key-secret-99" not in text
    assert "password=***" in text
    assert "private_key=***" in text
    assert "passphrase=***" in text
    assert "user" in text


def test_groups_host_recursive_delete(tmp_path: Path) -> None:
    path = tmp_path / "g.vault"
    vault = Vault.create(path, "pw")
    group = vault.add_group(Group(name="Lab", kind="hosts"))
    child = vault.add_group(Group(name="Nested", kind="hosts", parent_id=group.id))
    host = vault.add_host(Host(name="h1", group_id=child.id))
    assert host.group_id == child.id
    counts = vault.group_content_counts(group.id)
    assert counts["hosts"] == 1
    assert counts["groups"] == 1
    vault.delete_group(group.id)
    assert vault.list_groups() == []
    assert vault.list_hosts() == []


def test_notes_crud_and_group_cascade(tmp_path: Path) -> None:
    from hostskeeper.vault import Note

    path = tmp_path / "notes.vault"
    vault = Vault.create(path, "pw")
    group = vault.add_group(Group(name="Docs", kind="scripts"))
    note = vault.add_note(
        Note(
            name="readme",
            body="# Hi",
            group_id=group.id,
            mcp_enabled=False,
            preview=True,
        )
    )
    assert note.name == "readme"
    assert note.preview is True
    assert "preview" not in note.to_mcp_dict()
    vault.lock()
    again = Vault(path)
    again.unlock("pw")
    assert again.get_note(note.id).body == "# Hi"
    assert again.get_note(note.id).preview is True
    again.delete_group(group.id)
    assert again.list_notes() == []
    assert again.list_groups() == []


def test_legacy_script_without_mcp_flag_remains_visible() -> None:
    from hostskeeper.vault import Script

    script = Script(name="legacy", body="echo legacy", mcp_enabled=False)
    legacy_data = script.to_dict()
    legacy_data.pop("mcp_enabled")

    assert Script.from_dict(legacy_data).mcp_enabled is True


def test_script_mcp_visibility_persists(tmp_path: Path) -> None:
    from hostskeeper.vault import Script

    path = tmp_path / "script-visibility.vault"
    vault = Vault.create(path, "pw")
    hidden = vault.add_script(
        Script(name="hidden", body="echo hidden", mcp_enabled=False)
    )
    visible = vault.add_script(
        Script(name="visible", body="echo visible", mcp_enabled=True)
    )

    vault.lock()
    reloaded = Vault(path)
    reloaded.unlock("pw")

    assert reloaded.get_script(hidden.id).mcp_enabled is False
    assert reloaded.get_script(visible.id).mcp_enabled is True


def test_host_notes_preview_persists(tmp_path: Path) -> None:
    path = tmp_path / "hp.vault"
    vault = Vault.create(path, "pw")
    host = vault.add_host(Host(name="h1", notes_preview=True))
    assert host.notes_preview is True
    vault.lock()
    again = Vault(path)
    again.unlock("pw")
    assert again.get_host(host.id).notes_preview is True


def test_tree_expand_state_persists_in_vault(tmp_path: Path) -> None:
    path = tmp_path / "expand.vault"
    vault = Vault.create(path, "pw")
    group = vault.add_group(Group(name="Lab", kind="hosts"))
    assert group.expanded is True
    assert vault.tree_root_expanded("hosts") is True
    assert vault.tree_root_expanded("scripts") is True

    vault.set_group_expanded(group.id, False)
    vault.set_tree_root_expanded("hosts", False)
    vault.set_tree_root_expanded("scripts", False)
    vault.lock()

    again = Vault(path)
    again.unlock("pw")
    assert again.get_group(group.id).expanded is False
    assert again.tree_root_expanded("hosts") is False
    assert again.tree_root_expanded("scripts") is False
    mcp = again.get_group(group.id).to_mcp_dict()
    assert "expanded" not in mcp
