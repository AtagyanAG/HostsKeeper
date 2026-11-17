from __future__ import annotations

from hostskeeper.session.manager import SessionManager
from hostskeeper.vault import Credential, Host, Vault


def test_suggested_alias_preserves_host_name_case(tmp_path) -> None:
    vault = Vault.create(tmp_path / "alias.vault", "pw")
    host = vault.add_host(Host(name="Alum"))
    credential = vault.add_credential(
        Credential(host_id=host.id, username="Admin", password="pw")
    )
    sessions = SessionManager(vault)

    assert sessions.suggest_alias(host.id, credential.id) == "Alum-admin-1"
