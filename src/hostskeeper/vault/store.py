"""Encrypted vault store with CRUD for Host/Address/Credential/Script."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID

from hostskeeper.vault import crypto
from hostskeeper.vault.errors import (
    NotFoundError,
    ValidationError,
    VaultExistsError,
    VaultLockedError,
)
from hostskeeper.vault.models import (
    AUTH_KEY_PAIR,
    AUTH_PASSWORD,
    AUTH_TYPES,
    Address,
    Credential,
    Group,
    Host,
    Script,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Vault:
    """In-memory vault document persisted as Scrypt+AES-GCM file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._password: str | None = None
        self._hosts: dict[UUID, Host] = {}
        self._addresses: dict[UUID, Address] = {}
        self._credentials: dict[UUID, Credential] = {}
        self._scripts: dict[UUID, Script] = {}
        self._groups: dict[UUID, Group] = {}
        # UI tree chrome (encrypted with vault). Roots default expanded.
        self._ui_tree: dict[str, bool] = {
            "hosts_root_expanded": True,
            "scripts_root_expanded": True,
        }

    @property
    def is_unlocked(self) -> bool:
        return self._password is not None

    def _require_unlocked(self) -> None:
        if not self.is_unlocked:
            raise VaultLockedError("vault is locked")

    @classmethod
    def create(cls, path: Path | str, password: str) -> Vault:
        vault = cls(path)
        if vault.path.exists():
            raise VaultExistsError(f"vault already exists: {vault.path}")
        if not password:
            raise ValidationError("password must not be empty")
        vault.path.parent.mkdir(parents=True, exist_ok=True)
        vault._password = password
        vault.save()
        return vault

    def unlock(self, password: str) -> None:
        raw = self.path.read_bytes()
        plaintext = crypto.open_sealed(raw, password)
        payload = json.loads(plaintext.decode("utf-8"))
        if int(payload.get("version", 0)) != 1:
            raise ValidationError(f"unsupported vault version: {payload.get('version')}")
        self._hosts = {
            UUID(k): Host.from_dict(v) for k, v in (payload.get("hosts") or {}).items()
        }
        self._addresses = {
            UUID(k): Address.from_dict(v)
            for k, v in (payload.get("addresses") or {}).items()
        }
        self._credentials = {
            UUID(k): Credential.from_dict(v)
            for k, v in (payload.get("credentials") or {}).items()
        }
        self._scripts = {
            UUID(k): Script.from_dict(v)
            for k, v in (payload.get("scripts") or {}).items()
        }
        self._groups = {
            UUID(k): Group.from_dict(v)
            for k, v in (payload.get("groups") or {}).items()
        }
        ui_raw = payload.get("ui_tree") or {}
        self._ui_tree = {
            "hosts_root_expanded": bool(
                ui_raw.get("hosts_root_expanded", True)
            ),
            "scripts_root_expanded": bool(
                ui_raw.get("scripts_root_expanded", True)
            ),
        }
        self._password = password

    def lock(self) -> None:
        self._password = None
        self._hosts.clear()
        self._addresses.clear()
        self._credentials.clear()
        self._scripts.clear()
        self._groups.clear()
        self._ui_tree = {
            "hosts_root_expanded": True,
            "scripts_root_expanded": True,
        }

    def save(self) -> None:
        self._require_unlocked()
        assert self._password is not None
        payload = {
            "version": 1,
            "hosts": {str(k): v.to_dict() for k, v in self._hosts.items()},
            "addresses": {str(k): v.to_dict() for k, v in self._addresses.items()},
            "credentials": {
                str(k): v.to_dict() for k, v in self._credentials.items()
            },
            "scripts": {str(k): v.to_dict() for k, v in self._scripts.items()},
            "groups": {str(k): v.to_dict() for k, v in self._groups.items()},
            "ui_tree": {
                "hosts_root_expanded": bool(
                    self._ui_tree.get("hosts_root_expanded", True)
                ),
                "scripts_root_expanded": bool(
                    self._ui_tree.get("scripts_root_expanded", True)
                ),
            },
        }
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        blob = crypto.seal(plaintext, self._password)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(blob)
        tmp.replace(self.path)

    # --- Host ---

    def _validate_group_ref(
        self,
        group_id: UUID | None,
        *,
        kind: str,
        host_id: UUID | None = None,
    ) -> None:
        if group_id is None:
            return
        group = self._groups.get(group_id)
        if group is None:
            raise ValidationError(f"unknown group_id: {group_id}")
        if group.kind != kind:
            raise ValidationError(f"group kind must be {kind!r}")
        if group.host_id != host_id:
            raise ValidationError("group host_id mismatch")

    def _script_name_taken(
        self,
        name: str,
        *,
        host_id: UUID | None,
        exclude_id: UUID | None = None,
    ) -> bool:
        for script in self._scripts.values():
            if (
                script.name == name
                and script.host_id == host_id
                and script.id != exclude_id
            ):
                return True
        return False

    def suggest_script_name(self, name: str, *, host_id: UUID | None) -> str:
        """Return name or «name (n)» unique within host_id scope."""
        self._require_unlocked()
        if not self._script_name_taken(name, host_id=host_id):
            return name
        n = 2
        while self._script_name_taken(f"{name} ({n})", host_id=host_id):
            n += 1
        return f"{name} ({n})"

    def add_host(self, host: Host) -> Host:
        self._require_unlocked()
        if host.id in self._hosts:
            raise ValidationError(f"host already exists: {host.id}")
        self._validate_group_ref(host.group_id, kind="hosts", host_id=None)
        stored = deepcopy(host)
        self._hosts[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def get_host(self, host_id: UUID) -> Host:
        self._require_unlocked()
        try:
            return deepcopy(self._hosts[host_id])
        except KeyError as exc:
            raise NotFoundError(f"host not found: {host_id}") from exc

    def list_hosts(self) -> list[Host]:
        self._require_unlocked()
        return [deepcopy(h) for h in self._hosts.values()]

    def update_host(self, host: Host) -> Host:
        self._require_unlocked()
        if host.id not in self._hosts:
            raise NotFoundError(f"host not found: {host.id}")
        if host.default_address_id is not None:
            addr = self._addresses.get(host.default_address_id)
            if addr is None or addr.host_id != host.id:
                raise ValidationError("default_address_id must belong to this host")
        if host.default_credential_id is not None:
            cred = self._credentials.get(host.default_credential_id)
            if cred is None or cred.host_id != host.id:
                raise ValidationError("default_credential_id must belong to this host")
        self._validate_group_ref(host.group_id, kind="hosts", host_id=None)
        stored = replace(deepcopy(host), updated_at=_utcnow())
        self._hosts[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def delete_host(self, host_id: UUID) -> None:
        self._require_unlocked()
        if host_id not in self._hosts:
            raise NotFoundError(f"host not found: {host_id}")
        for addr_id in [a.id for a in self._addresses.values() if a.host_id == host_id]:
            del self._addresses[addr_id]
        for cred_id in [
            c.id for c in self._credentials.values() if c.host_id == host_id
        ]:
            del self._credentials[cred_id]
        for script_id in [
            s.id for s in self._scripts.values() if s.host_id == host_id
        ]:
            del self._scripts[script_id]
        for group_id in [
            g.id for g in self._groups.values() if g.host_id == host_id
        ]:
            del self._groups[group_id]
        del self._hosts[host_id]
        self.save()

    # --- Address ---

    def add_address(self, address: Address) -> Address:
        self._require_unlocked()
        if address.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {address.host_id}")
        if address.id in self._addresses:
            raise ValidationError(f"address already exists: {address.id}")
        stored = deepcopy(address)
        self._addresses[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def get_address(self, address_id: UUID) -> Address:
        self._require_unlocked()
        try:
            return deepcopy(self._addresses[address_id])
        except KeyError as exc:
            raise NotFoundError(f"address not found: {address_id}") from exc

    def list_addresses(self, host_id: UUID | None = None) -> list[Address]:
        self._require_unlocked()
        items: Iterable[Address] = self._addresses.values()
        if host_id is not None:
            items = [a for a in items if a.host_id == host_id]
        return [deepcopy(a) for a in items]

    def update_address(self, address: Address) -> Address:
        self._require_unlocked()
        if address.id not in self._addresses:
            raise NotFoundError(f"address not found: {address.id}")
        if address.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {address.host_id}")
        stored = replace(deepcopy(address), updated_at=_utcnow())
        self._addresses[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def delete_address(self, address_id: UUID) -> None:
        self._require_unlocked()
        if address_id not in self._addresses:
            raise NotFoundError(f"address not found: {address_id}")
        for host in self._hosts.values():
            if host.default_address_id == address_id:
                host.default_address_id = None
                host.updated_at = _utcnow()
        del self._addresses[address_id]
        self.save()

    # --- Credential ---

    def _validate_credential_secrets(self, credential: Credential) -> None:
        if credential.auth_type not in AUTH_TYPES:
            raise ValidationError(f"invalid auth_type: {credential.auth_type}")
        if credential.auth_type == AUTH_PASSWORD and not credential.password:
            raise ValidationError("password auth requires a password")
        if credential.auth_type == AUTH_KEY_PAIR and not credential.private_key:
            raise ValidationError("key pair auth requires a private key")
        # openssh_config: agent / ~/.ssh/config — secrets optional

    def add_credential(self, credential: Credential) -> Credential:
        self._require_unlocked()
        if credential.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {credential.host_id}")
        if credential.id in self._credentials:
            raise ValidationError(f"credential already exists: {credential.id}")
        self._validate_credential_secrets(credential)
        stored = deepcopy(credential)
        self._credentials[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def get_credential(self, credential_id: UUID) -> Credential:
        self._require_unlocked()
        try:
            return deepcopy(self._credentials[credential_id])
        except KeyError as exc:
            raise NotFoundError(f"credential not found: {credential_id}") from exc

    def list_credentials(self, host_id: UUID | None = None) -> list[Credential]:
        self._require_unlocked()
        items: Iterable[Credential] = self._credentials.values()
        if host_id is not None:
            items = [c for c in items if c.host_id == host_id]
        return [deepcopy(c) for c in items]

    def update_credential(self, credential: Credential) -> Credential:
        self._require_unlocked()
        if credential.id not in self._credentials:
            raise NotFoundError(f"credential not found: {credential.id}")
        if credential.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {credential.host_id}")
        self._validate_credential_secrets(credential)
        stored = replace(deepcopy(credential), updated_at=_utcnow())
        self._credentials[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def delete_credential(self, credential_id: UUID) -> None:
        self._require_unlocked()
        if credential_id not in self._credentials:
            raise NotFoundError(f"credential not found: {credential_id}")
        for host in self._hosts.values():
            if host.default_credential_id == credential_id:
                host.default_credential_id = None
                host.updated_at = _utcnow()
        del self._credentials[credential_id]
        self.save()

    # --- Script ---

    def add_script(self, script: Script) -> Script:
        self._require_unlocked()
        if script.id in self._scripts:
            raise ValidationError(f"script already exists: {script.id}")
        if script.host_id is not None and script.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {script.host_id}")
        if self._script_name_taken(script.name, host_id=script.host_id):
            raise ValidationError(f"script name already exists: {script.name}")
        self._validate_group_ref(
            script.group_id, kind="scripts", host_id=script.host_id
        )
        stored = deepcopy(script)
        self._scripts[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def get_script(self, script_id: UUID) -> Script:
        self._require_unlocked()
        try:
            return deepcopy(self._scripts[script_id])
        except KeyError as exc:
            raise NotFoundError(f"script not found: {script_id}") from exc

    def get_script_by_name(
        self, name: str, *, host_id: UUID | None = None
    ) -> Script:
        self._require_unlocked()
        for script in self._scripts.values():
            if script.name == name and script.host_id == host_id:
                return deepcopy(script)
        raise NotFoundError(f"script not found: {name}")

    def list_scripts(
        self,
        *,
        host_id: UUID | None = None,
        only_templates: bool = False,
    ) -> list[Script]:
        self._require_unlocked()
        items: Iterable[Script] = self._scripts.values()
        if only_templates:
            items = [s for s in items if s.host_id is None]
        elif host_id is not None:
            items = [s for s in items if s.host_id == host_id]
        return [deepcopy(s) for s in items]

    def update_script(self, script: Script) -> Script:
        self._require_unlocked()
        if script.id not in self._scripts:
            raise NotFoundError(f"script not found: {script.id}")
        if script.host_id is not None and script.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {script.host_id}")
        if self._script_name_taken(
            script.name, host_id=script.host_id, exclude_id=script.id
        ):
            raise ValidationError(f"script name already exists: {script.name}")
        self._validate_group_ref(
            script.group_id, kind="scripts", host_id=script.host_id
        )
        stored = replace(deepcopy(script), updated_at=_utcnow())
        self._scripts[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def delete_script(self, script_id: UUID) -> None:
        self._require_unlocked()
        if script_id not in self._scripts:
            raise NotFoundError(f"script not found: {script_id}")
        del self._scripts[script_id]
        self.save()

    # --- Group ---

    def _validate_group_entity(self, group: Group) -> None:
        if group.kind not in ("hosts", "scripts"):
            raise ValidationError("group kind must be 'hosts' or 'scripts'")
        if group.kind == "hosts" and group.host_id is not None:
            raise ValidationError("hosts groups cannot have host_id")
        if group.host_id is not None and group.host_id not in self._hosts:
            raise ValidationError(f"unknown host_id: {group.host_id}")
        if group.parent_id is not None:
            parent = self._groups.get(group.parent_id)
            if parent is None:
                raise ValidationError(f"unknown parent_id: {group.parent_id}")
            if parent.kind != group.kind:
                raise ValidationError("parent group kind mismatch")
            if parent.host_id != group.host_id:
                raise ValidationError("parent group host_id mismatch")

    def tree_root_expanded(self, root: str) -> bool:
        """Expand state for workspace Hosts/Scripts roots (default True)."""
        self._require_unlocked()
        if root == "hosts":
            return bool(self._ui_tree.get("hosts_root_expanded", True))
        if root == "scripts":
            return bool(self._ui_tree.get("scripts_root_expanded", True))
        raise ValidationError(f"unknown tree root: {root}")

    def set_tree_root_expanded(self, root: str, expanded: bool) -> None:
        from hostskeeper.runtime.tree_debug_log import log, log_exception

        self._require_unlocked()
        if root == "hosts":
            key = "hosts_root_expanded"
        elif root == "scripts":
            key = "scripts_root_expanded"
        else:
            raise ValidationError(f"unknown tree root: {root}")
        prev = bool(self._ui_tree.get(key, True))
        if prev == bool(expanded):
            log("vault_root_expand_noop", root=root, expanded=expanded)
            return
        log(
            "vault_root_expand_save_begin",
            root=root,
            expanded=expanded,
            prev=prev,
            path=str(self.path),
        )
        self._ui_tree[key] = bool(expanded)
        try:
            self.save()
            log("vault_root_expand_save_ok", root=root, expanded=expanded)
        except Exception as exc:  # noqa: BLE001
            log_exception(
                "vault_root_expand_save_fail",
                exc,
                root=root,
                expanded=expanded,
            )
            raise

    def set_group_expanded(self, group_id: UUID, expanded: bool) -> None:
        """Persist group expand state without bumping updated_at."""
        from hostskeeper.runtime.tree_debug_log import log, log_exception

        self._require_unlocked()
        group = self._groups.get(group_id)
        if group is None:
            raise NotFoundError(f"group not found: {group_id}")
        prev = bool(group.expanded)
        if prev == bool(expanded):
            log(
                "vault_group_expand_noop",
                id=str(group_id),
                name=group.name,
                expanded=expanded,
            )
            return
        log(
            "vault_group_expand_save_begin",
            id=str(group_id),
            name=group.name,
            expanded=expanded,
            prev=prev,
            path=str(self.path),
        )
        group.expanded = bool(expanded)
        try:
            self.save()
            log(
                "vault_group_expand_save_ok",
                id=str(group_id),
                name=group.name,
                expanded=expanded,
            )
        except Exception as exc:  # noqa: BLE001
            log_exception(
                "vault_group_expand_save_fail",
                exc,
                id=str(group_id),
                name=group.name,
                expanded=expanded,
            )
            raise

    def add_group(self, group: Group) -> Group:
        self._require_unlocked()
        if group.id in self._groups:
            raise ValidationError(f"group already exists: {group.id}")
        self._validate_group_entity(group)
        stored = deepcopy(group)
        # New groups default to expanded unless caller set otherwise.
        stored.expanded = bool(getattr(stored, "expanded", True))
        self._groups[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def get_group(self, group_id: UUID) -> Group:
        self._require_unlocked()
        try:
            return deepcopy(self._groups[group_id])
        except KeyError as exc:
            raise NotFoundError(f"group not found: {group_id}") from exc

    def list_groups(
        self,
        kind: str | None = None,
        *,
        host_id: UUID | None = None,
        only_templates: bool = False,
    ) -> list[Group]:
        self._require_unlocked()
        items = list(self._groups.values())
        if kind is not None:
            items = [g for g in items if g.kind == kind]
        if only_templates:
            items = [g for g in items if g.host_id is None]
        elif host_id is not None:
            items = [g for g in items if g.host_id == host_id]
        return [deepcopy(g) for g in items]

    def update_group(self, group: Group) -> Group:
        self._require_unlocked()
        if group.id not in self._groups:
            raise NotFoundError(f"group not found: {group.id}")
        self._validate_group_entity(group)
        if group.parent_id == group.id:
            raise ValidationError("group cannot be its own parent")
        if group.parent_id is not None:
            # Prevent cycles.
            walk = self._groups[group.parent_id].parent_id
            seen = {group.id}
            while walk is not None:
                if walk in seen:
                    raise ValidationError("group parent cycle")
                seen.add(walk)
                nxt = self._groups.get(walk)
                walk = nxt.parent_id if nxt else None
        stored = replace(deepcopy(group), updated_at=_utcnow())
        self._groups[stored.id] = stored
        self.save()
        return deepcopy(stored)

    def delete_group(self, group_id: UUID) -> None:
        """Delete group; children move to its parent (or root)."""
        self._require_unlocked()
        group = self._groups.get(group_id)
        if group is None:
            raise NotFoundError(f"group not found: {group_id}")
        new_parent = group.parent_id
        for child in self._groups.values():
            if child.parent_id == group_id:
                child.parent_id = new_parent
                child.updated_at = _utcnow()
        if group.kind == "hosts":
            for host in self._hosts.values():
                if host.group_id == group_id:
                    host.group_id = new_parent
                    host.updated_at = _utcnow()
        else:
            for script in self._scripts.values():
                if script.group_id == group_id:
                    script.group_id = new_parent
                    script.updated_at = _utcnow()
        del self._groups[group_id]
        self.save()
