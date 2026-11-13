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
    assert hosts[0].default_address_id == address.id
    assert hosts[0].default_credential_id == credential.id
    assert again.get_address(address.id).host == "10.0.0.1"
    cred = again.get_credential(credential.id)
    assert cred.password == "s3cret"
    assert cred.private_key is not None
    assert cred.auth_type == "password"
    assert again.get_script_by_name("uptime").body == "uptime"


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


def test_groups_host_move_and_delete(tmp_path: Path) -> None:
    path = tmp_path / "g.vault"
    vault = Vault.create(path, "pw")
    group = vault.add_group(Group(name="Lab", kind="hosts"))
    host = vault.add_host(Host(name="h1", group_id=group.id))
    assert host.group_id == group.id
    vault.lock()

    again = Vault(path)
    again.unlock("pw")
    assert again.list_groups(kind="hosts")[0].name == "Lab"
    h = again.get_host(host.id)
    assert h.group_id == group.id
    again.delete_group(group.id)
    assert again.get_host(host.id).group_id is None
    assert again.list_groups() == []
