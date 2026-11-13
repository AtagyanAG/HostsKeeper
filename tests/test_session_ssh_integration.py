"""Live SSH integration against lab host (safe read-only commands only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hostskeeper.session import SessionManager, SessionStatus
from hostskeeper.vault import Address, Credential, Host, Vault
from tests.lab_env import (
    HOST,
    KEY_PATH,
    PORT,
    USER,
    VAULT_HOST_NAME,
    lab_key_available,
)

pytestmark = pytest.mark.skipif(
    not lab_key_available(),
    reason="set HOSTSKEEPER_TEST_SSH_KEY to a readable private key for live SSH tests",
)


@pytest.fixture()
def vault_with_lab(tmp_path: Path) -> Vault:
    vault = Vault.create(tmp_path / "lab.vault", "test-pass")
    host = vault.add_host(Host(name=VAULT_HOST_NAME, tags=["lab"]))
    address = vault.add_address(
        Address(host_id=host.id, host=HOST, port=PORT, label="lan")
    )
    key_pem = KEY_PATH.read_text(encoding="utf-8")
    credential = vault.add_credential(
        Credential(host_id=host.id, username=USER, private_key=key_pem, label="key")
    )
    host.default_address_id = address.id
    host.default_credential_id = credential.id
    vault.update_host(host)
    return vault


def test_open_write_echo_and_reconnect(vault_with_lab: Vault) -> None:
    host = vault_with_lab.list_hosts()[0]
    assert host.default_address_id and host.default_credential_id
    mgr = SessionManager(vault_with_lab)

    info = mgr.open_tab(
        host_id=host.id,
        address_id=host.default_address_id,
        credential_id=host.default_credential_id,
    )
    assert info.status == SessionStatus.LIVE
    assert info.alias.startswith(f"{VAULT_HOST_NAME}-{USER}-")
    # Public repr must not leak address or key material (alias may include username).
    text = repr(info)
    assert HOST not in text
    assert "BEGIN" not in text
    assert "PRIVATE" not in text

    marker = "hostskeeper-stage2-ok"
    mgr.write(info.id, f"echo {marker}", submit=True)
    got = mgr.wait_for_output(info.id, marker, timeout=15.0)
    assert marker in got.data

    mgr.disconnect(info.id)
    assert mgr.get(info.id).status == SessionStatus.DISCONNECTED

    again = mgr.reconnect(info.id)
    assert again.status == SessionStatus.LIVE
    assert again.alias == info.alias
    assert again.id == info.id

    marker2 = "hostskeeper-stage2-reok"
    mgr.write(again.id, f"echo {marker2}", submit=True)
    got2 = mgr.wait_for_output(again.id, marker2, timeout=15.0)
    assert marker2 in got2.data

    mgr.close(again.id)
    assert again.id not in {s.id for s in mgr.list_sessions()}
