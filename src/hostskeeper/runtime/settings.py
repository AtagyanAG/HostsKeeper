"""User settings under %APPDATA%/HostsKeeper (not secrets)."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_LEGACY_APPDATA_NAME = "HostsSafe"


def _roaming_base() -> Path:
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Roaming"


def appdata_dir() -> Path:
    return _roaming_base() / "HostsKeeper"


def _legacy_appdata_dir() -> Path:
    return _roaming_base() / _LEGACY_APPDATA_NAME


def settings_path() -> Path:
    """Read path: prefer HostsKeeper; fall back to legacy HostsSafe settings."""
    primary = appdata_dir() / "settings.json"
    if primary.is_file():
        return primary
    legacy = _legacy_appdata_dir() / "settings.json"
    if legacy.is_file():
        return legacy
    return primary


def default_vault_path() -> Path:
    primary = appdata_dir() / "default.vault"
    if primary.is_file():
        return primary
    legacy = _legacy_appdata_dir() / "default.vault"
    if legacy.is_file():
        return legacy
    return primary


def _norm_path(path: Path | str) -> str:
    return str(Path(path).expanduser())


@dataclass
class VaultNode:
    """Vault list entry: a folder group or a vault file reference."""

    id: str
    kind: str  # "group" | "vault"
    name: str | None = None
    path: str | None = None
    parent_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> VaultNode:
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            kind=str(data.get("kind") or "vault"),
            name=data.get("name"),
            path=_norm_path(data["path"]) if data.get("path") else None,
            parent_id=data.get("parent_id"),
        )


@dataclass
class AppSettings:
    """Known vaults (with optional groups), last vault, launcher paths."""

    vault_nodes: list[VaultNode] = field(default_factory=list)
    last_vault_path: str | None = None
    putty_path: str | None = None
    winscp_path: str | None = None
    # SSH connect timeout for Tab sessions (PuTTY/WinSCP use their own).
    tab_connect_timeout_sec: int = 3
    # Vaults sidebar: group id → expanded (default True when missing).
    vault_tree_expanded: dict[str, bool] = field(default_factory=dict)

    @property
    def vault_paths(self) -> list[str]:
        return [n.path for n in self.vault_nodes if n.kind == "vault" and n.path]

    @classmethod
    def load(cls) -> AppSettings:
        path = settings_path()
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()

        nodes: list[VaultNode] = []
        nodes_raw = raw.get("vault_nodes")
        if isinstance(nodes_raw, list) and nodes_raw:
            for item in nodes_raw:
                if isinstance(item, dict):
                    node = VaultNode.from_dict(item)
                    if node.kind == "vault" and not node.path:
                        continue
                    if node.kind == "group" and not (node.name or "").strip():
                        continue
                    nodes.append(node)
        else:
            # Migrate legacy flat vault_paths.
            paths_raw = raw.get("vault_paths") or []
            if isinstance(paths_raw, list):
                seen: set[str] = set()
                for item in paths_raw:
                    if isinstance(item, str) and item.strip():
                        key = _norm_path(item.strip())
                        if key in seen:
                            continue
                        seen.add(key)
                        nodes.append(
                            VaultNode(
                                id=str(uuid.uuid4()),
                                kind="vault",
                                path=key,
                            )
                        )

        last = raw.get("last_vault_path")
        last_s = _norm_path(last) if isinstance(last, str) and last.strip() else None
        if last_s and not any(n.kind == "vault" and n.path == last_s for n in nodes):
            nodes.insert(
                0,
                VaultNode(id=str(uuid.uuid4()), kind="vault", path=last_s),
            )
        putty = raw.get("putty_path")
        winscp = raw.get("winscp_path")
        putty_s = (
            _norm_path(putty) if isinstance(putty, str) and putty.strip() else None
        )
        winscp_s = (
            _norm_path(winscp) if isinstance(winscp, str) and winscp.strip() else None
        )
        # Prefer new key; accept legacy tab_approve_timeout_sec once.
        timeout_raw = raw.get(
            "tab_connect_timeout_sec",
            raw.get("tab_approve_timeout_sec", 3),
        )
        try:
            timeout_sec = int(timeout_raw)
        except (TypeError, ValueError):
            timeout_sec = 3
        if timeout_sec < 1:
            timeout_sec = 1
        expanded_raw = raw.get("vault_tree_expanded") or {}
        vault_tree_expanded: dict[str, bool] = {}
        if isinstance(expanded_raw, dict):
            for key, val in expanded_raw.items():
                if isinstance(key, str) and key.strip():
                    vault_tree_expanded[key] = bool(val)
        return cls(
            vault_nodes=nodes,
            last_vault_path=last_s,
            putty_path=putty_s,
            winscp_path=winscp_s,
            tab_connect_timeout_sec=timeout_sec,
            vault_tree_expanded=vault_tree_expanded,
        )

    def save(self) -> None:
        directory = appdata_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "vault_nodes": [n.to_dict() for n in self.vault_nodes],
            # Keep legacy key for older tools / readability.
            "vault_paths": self.vault_paths,
            "last_vault_path": self.last_vault_path,
            "putty_path": self.putty_path,
            "winscp_path": self.winscp_path,
            "tab_connect_timeout_sec": int(self.tab_connect_timeout_sec),
            "vault_tree_expanded": {
                k: bool(v) for k, v in self.vault_tree_expanded.items()
            },
        }
        # Always write under HostsKeeper (migrate off legacy HostsSafe folder).
        path = directory / "settings.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def ensure_launcher_paths(self) -> bool:
        """If putty/winscp unset, discover (env / Program Files / PATH) and save.

        Returns True if settings were updated.
        """
        from hostskeeper.launchers import discover_launchers

        changed = False
        found = discover_launchers(
            putty=self.putty_path,
            winscp=self.winscp_path,
        )
        # Only fill when settings field is empty (do not overwrite saved paths).
        if not self.putty_path and found.putty is not None:
            self.putty_path = _norm_path(found.putty)
            changed = True
        if not self.winscp_path and found.winscp is not None:
            self.winscp_path = _norm_path(found.winscp)
            changed = True
        if changed:
            self.save()
        return changed

    def _find_vault_node(self, path: Path | str) -> VaultNode | None:
        key = _norm_path(path)
        for node in self.vault_nodes:
            if node.kind == "vault" and node.path == key:
                return node
        return None

    def add_vault_path(
        self, path: Path | str, *, parent_id: str | None = None
    ) -> Path:
        resolved = Path(path).expanduser()
        key = _norm_path(resolved)
        existing = self._find_vault_node(key)
        if existing is None:
            self.vault_nodes.append(
                VaultNode(
                    id=str(uuid.uuid4()),
                    kind="vault",
                    path=key,
                    parent_id=parent_id,
                )
            )
        elif parent_id is not None:
            existing.parent_id = parent_id
        self.last_vault_path = key
        self.save()
        return resolved

    def remove_vault_path(self, path: Path | str) -> None:
        key = _norm_path(path)
        self.vault_nodes = [
            n
            for n in self.vault_nodes
            if not (n.kind == "vault" and n.path == key)
        ]
        if self.last_vault_path == key:
            paths = self.vault_paths
            self.last_vault_path = paths[0] if paths else None
        self.save()

    def rename_vault_path(self, old_path: Path | str, new_path: Path | str) -> Path:
        """Update vault list entry after the file was renamed on disk."""
        old_key = _norm_path(old_path)
        new_resolved = Path(new_path).expanduser()
        new_key = _norm_path(new_resolved)
        node = self._find_vault_node(old_key)
        if node is None:
            raise FileNotFoundError(f"vault not in list: {old_key}")
        if old_key != new_key and self._find_vault_node(new_key) is not None:
            raise FileExistsError(f"vault already in list: {new_key}")
        node.path = new_key
        if self.last_vault_path == old_key:
            self.last_vault_path = new_key
        self.save()
        return new_resolved

    def remember_last(self, path: Path | str) -> None:
        key = _norm_path(path)
        if self._find_vault_node(key) is None:
            self.vault_nodes.append(
                VaultNode(id=str(uuid.uuid4()), kind="vault", path=key)
            )
        self.last_vault_path = key
        self.save()

    def vault_group_expanded(self, group_id: str) -> bool:
        return bool(self.vault_tree_expanded.get(group_id, True))

    def set_vault_group_expanded(self, group_id: str, expanded: bool) -> None:
        prev = self.vault_tree_expanded.get(group_id, True)
        if bool(prev) == bool(expanded):
            return
        self.vault_tree_expanded[group_id] = bool(expanded)
        self.save()

    def add_vault_group(
        self, name: str, *, parent_id: str | None = None
    ) -> VaultNode:
        node = VaultNode(
            id=str(uuid.uuid4()),
            kind="group",
            name=name.strip() or "Group",
            parent_id=parent_id,
        )
        self.vault_nodes.append(node)
        self.vault_tree_expanded[node.id] = True
        self.save()
        return node

    def rename_vault_group(self, group_id: str, name: str) -> None:
        for node in self.vault_nodes:
            if node.kind == "group" and node.id == group_id:
                node.name = name.strip() or node.name or "Group"
                self.save()
                return

    def delete_vault_group(self, group_id: str) -> None:
        target = next(
            (n for n in self.vault_nodes if n.kind == "group" and n.id == group_id),
            None,
        )
        if target is None:
            return
        new_parent = target.parent_id
        for node in self.vault_nodes:
            if node.parent_id == group_id:
                node.parent_id = new_parent
        self.vault_nodes = [n for n in self.vault_nodes if n.id != group_id]
        self.vault_tree_expanded.pop(group_id, None)
        self.save()

    def move_vault_node(self, node_id: str, parent_id: str | None) -> None:
        node = next((n for n in self.vault_nodes if n.id == node_id), None)
        if node is None:
            return
        if parent_id == node_id:
            return
        if parent_id is not None:
            parent = next((n for n in self.vault_nodes if n.id == parent_id), None)
            if parent is None or parent.kind != "group":
                return
            # Prevent dropping into own descendant.
            walk = parent.parent_id
            while walk is not None:
                if walk == node_id:
                    return
                nxt = next((n for n in self.vault_nodes if n.id == walk), None)
                walk = nxt.parent_id if nxt else None
        node.parent_id = parent_id
        self.save()
