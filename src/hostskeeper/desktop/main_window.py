"""Main workspace window (connection-manager layout)."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QMetaObject, Qt, QThread, Slot
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hostskeeper.desktop.dialogs import (
    AddressDialog,
    CredentialDialog,
    HostDialog,
    NoteDialog,
    RevealSecretDialog,
    RunScriptTargetDialog,
    ScriptDialog,
)
from hostskeeper.desktop.drop_tree import DropTreeWidget
from hostskeeper.desktop.folder_icon import (
    apply_group_folder_icons,
    folder_icon,
    host_icon,
    note_icon,
    script_icon,
)
from hostskeeper.desktop.session_tab import SessionTab, _OpenTabWorker, _public_mcp_host
from hostskeeper.desktop.unlock_dialog import UnlockDialog
from hostskeeper.launchers import discover_launchers, launch_putty, launch_winscp
from hostskeeper.mcp.app_key import cursor_mcp_config
from hostskeeper.runtime.mcp_http import ensure_mcp_http, stop_mcp_http
from hostskeeper.runtime.settings import AppSettings, default_vault_path
from hostskeeper.runtime.state import AppState
from hostskeeper.vault import Group
from hostskeeper.vault.errors import NotFoundError


class NodeKind(str, Enum):
    HOSTS_ROOT = "hosts_root"
    SCRIPTS_ROOT = "scripts_root"
    HOST = "host"
    ADDRESS = "address"
    CREDENTIAL = "credential"
    SCRIPT = "script"
    NOTE = "note"
    VAULT = "vault"
    GROUP = "group"
    VAULT_GROUP = "vault_group"


def _norm_vault_key(path: Path | str) -> str:
    """Case-normalized absolute path for comparing vault identities on Windows."""
    expanded = Path(path).expanduser()
    try:
        resolved = expanded.resolve()
    except OSError:
        resolved = expanded
    return os.path.normcase(str(resolved))


_GROUP_FOLDER_KINDS = frozenset({NodeKind.GROUP.value, NodeKind.VAULT_GROUP.value})


class MainWindow(QMainWindow):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self._state = state
        self._settings = AppSettings.load()
        self._selected_host_id: UUID | None = None
        self._selected_address_id: UUID | None = None
        self._selected_credential_id: UUID | None = None
        self._session_tabs: dict[UUID, SessionTab] = {}
        self._welcome_index: int | None = 0
        self._open_thread: QThread | None = None
        self._pending_script_write: str | None = None
        self._open_worker: object | None = None
        self._shutting_down = False
        self._connect_busy = False
        # Skip persist while rebuilding trees / programmatic expand.
        self._suppress_expand_persist = False
        # Path of the vault that is actually unlocked (selection may differ).
        self._connected_vault_path: Path | None = None
        self.setWindowTitle("HostsKeeper")
        self.resize(1100, 700)

        self._seed_vault_list()
        self._settings.ensure_launcher_paths()
        self._build_toolbar()
        self._build_central()
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._refresh_vault_tree()
        self._set_locked_ui()

    def _seed_vault_list(self) -> None:
        """Ensure settings list has a usable entry; restore last selection."""
        current = Path(self._state.vault_path).expanduser()
        for legacy in (
            Path.home() / ".hostskeeper" / "default.vault",
            Path.home() / ".hostssafe" / "default.vault",
        ):
            if legacy.is_file() and str(legacy) not in self._settings.vault_paths:
                # Keep previously used default visible after AppData migration.
                self._settings.add_vault_path(legacy)
        if not self._settings.vault_paths:
            self._settings.add_vault_path(current)
        elif str(current) not in self._settings.vault_paths:
            self._settings.add_vault_path(current)
        if self._settings.last_vault_path:
            self._state.vault_path = Path(self._settings.last_vault_path)
        else:
            self._state.vault_path = current

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._act_connect = QAction("Connect", self)
        self._act_connect.setCheckable(True)
        self._act_connect.triggered.connect(self._on_connect_triggered)
        tb.addAction(self._act_connect)
        self._sync_connect_action_label(False)

        tb.addSeparator()

        self._act_close_all_tabs = QAction("Close All Tabs", self)
        self._act_close_all_tabs.setToolTip("Close all SSH session tabs (Welcome stays)")
        self._act_close_all_tabs.triggered.connect(self._close_all_tabs)
        tb.addAction(self._act_close_all_tabs)

        tb.addSeparator()
        self._act_options = QAction("Options", self)
        self._act_options.triggered.connect(self._open_options)
        tb.addAction(self._act_options)

    def _open_options(self) -> None:
        from hostskeeper.desktop.options_dialog import OptionsDialog

        dlg = OptionsDialog(
            self._settings,
            parent=self,
            on_copy_mcp_config=self._copy_mcp_config,
            on_change_mcp_key=self._change_mcp_key,
        )
        if dlg.exec() != OptionsDialog.DialogCode.Accepted:
            return
        from hostskeeper.desktop.theme import apply_app_theme

        apply_app_theme(self._settings.ui_theme)
        self._apply_session_connect_timeout()

    def _apply_session_connect_timeout(self) -> None:
        if self._state.sessions is None:
            return
        self._state.sessions.set_connect_timeout_sec(
            self._settings.tab_connect_timeout_sec
        )

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_split = QSplitter(Qt.Orientation.Vertical)

        vaults_wrap = QWidget()
        vaults_layout = QVBoxLayout(vaults_wrap)
        vaults_layout.setContentsMargins(4, 4, 4, 0)
        vaults_layout.addWidget(QLabel("Vaults"))
        self._vault_tree = DropTreeWidget()
        self._vault_tree.setHeaderHidden(True)
        self._vault_tree.setRootIsDecorated(True)
        self._vault_tree.setEditTriggers(DropTreeWidget.EditTrigger.NoEditTriggers)
        self._vault_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._vault_tree.customContextMenuRequested.connect(self._vault_tree_menu)
        self._vault_tree.itemSelectionChanged.connect(self._on_vault_selection)
        # Use itemActivated only: on Windows a double-click also emits
        # itemDoubleClicked, which would open UnlockDialog twice.
        self._vault_tree.itemActivated.connect(self._on_vault_activated)
        self._vault_tree.reparent_requested.connect(self._on_vault_reparent)
        self._vault_tree.itemExpanded.connect(self._on_vault_item_expanded)
        self._vault_tree.itemCollapsed.connect(self._on_vault_item_collapsed)
        vaults_layout.addWidget(self._vault_tree)
        left_split.addWidget(vaults_wrap)

        hosts_wrap = QWidget()
        hosts_layout = QVBoxLayout(hosts_wrap)
        hosts_layout.setContentsMargins(4, 0, 4, 4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search hosts / scripts / notes…")
        self._search.textChanged.connect(self._apply_filter)
        hosts_layout.addWidget(self._search)

        self._tree = DropTreeWidget()
        self._tree.setHeaderLabel("Workspace")
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._tree_menu)
        self._tree.itemDoubleClicked.connect(self._tree_double_click)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        self._tree.reparent_requested.connect(self._on_workspace_reparent)
        self._tree.foreign_drop_requested.connect(self._on_workspace_foreign_drop)
        self._tree.itemExpanded.connect(self._on_workspace_item_expanded)
        self._tree.itemCollapsed.connect(self._on_workspace_item_collapsed)
        self._hosts_root = QTreeWidgetItem(["Hosts"])
        self._hosts_root.setData(0, Qt.ItemDataRole.UserRole, {"kind": NodeKind.HOSTS_ROOT})
        self._hosts_root.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        self._scripts_root = QTreeWidgetItem(["Scripts"])
        self._scripts_root.setData(
            0, Qt.ItemDataRole.UserRole, {"kind": NodeKind.SCRIPTS_ROOT}
        )
        self._scripts_root.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        self._tree.addTopLevelItem(self._hosts_root)
        self._tree.addTopLevelItem(self._scripts_root)
        self._hosts_root.setExpanded(True)
        self._scripts_root.setExpanded(True)
        hosts_layout.addWidget(self._tree)
        left_split.addWidget(hosts_wrap)

        left_split.setStretchFactor(0, 1)
        left_split.setStretchFactor(1, 3)
        left_split.setMinimumWidth(240)
        splitter.addWidget(left_split)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        placeholder = QLabel(
            "No open sessions.\nOpen a host (Edit Host → Tab) or use the context menu."
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.addWidget(placeholder)
        self._welcome_index = self._tabs.addTab(wrap, "Welcome")
        right_layout.addWidget(self._tabs)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _is_connected_vault(self, path: Path | str) -> bool:
        if not self._state.unlocked or self._connected_vault_path is None:
            return False
        return _norm_vault_key(self._connected_vault_path) == _norm_vault_key(path)

    def _refresh_vault_tree(self) -> None:
        self._suppress_expand_persist = True
        try:
            self._refresh_vault_tree_body()
        finally:
            self._suppress_expand_persist = False

    def _refresh_vault_tree_body(self) -> None:
        self._vault_tree.clear()
        select_key = _norm_vault_key(
            self._settings.last_vault_path or self._state.vault_path
        )
        nodes = list(self._settings.vault_nodes)
        by_parent: dict[str | None, list] = {}
        for node in nodes:
            by_parent.setdefault(node.parent_id, []).append(node)

        def add_children(parent_item: QTreeWidgetItem | None, parent_id: str | None) -> None:
            children = sorted(
                by_parent.get(parent_id, []),
                key=lambda n: (
                    0 if n.kind == "group" else 1,
                    (n.name or n.path or "").lower(),
                ),
            )
            for node in children:
                if node.kind == "group":
                    item = QTreeWidgetItem([node.name or "Group"])
                    item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {
                            "kind": NodeKind.VAULT_GROUP,
                            "id": node.id,
                            "parent_id": node.parent_id,
                        },
                    )
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                        | Qt.ItemFlag.ItemIsDropEnabled
                    )
                    if parent_item is None:
                        self._vault_tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    add_children(item, node.id)
                    item.setIcon(0, folder_icon(filled=item.childCount() > 0))
                    item.setExpanded(self._settings.vault_group_expanded(node.id))
                elif node.kind == "vault" and node.path:
                    path = Path(node.path)
                    label = path.name or str(path)
                    exists = path.exists()
                    connected = self._is_connected_vault(path)
                    if connected:
                        text = f"● {label}" if exists else f"● {label} (missing)"
                    else:
                        text = label if exists else f"{label} (missing)"
                    item = QTreeWidgetItem([text])
                    item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {
                            "kind": NodeKind.VAULT,
                            "path": str(path),
                            "id": node.id,
                            "parent_id": node.parent_id,
                        },
                    )
                    item.setToolTip(0, str(path))
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    if parent_item is None:
                        self._vault_tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    if _norm_vault_key(path) == select_key:
                        self._vault_tree.setCurrentItem(item)
                        if not self._state.unlocked:
                            self._state.vault_path = path

        add_children(None, None)

    def _selected_vault_path(self) -> Path | None:
        items = self._vault_tree.selectedItems()
        if not items:
            return None
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("kind") != NodeKind.VAULT:
            return None
        return Path(data["path"])

    def _on_vault_selection(self) -> None:
        path = self._selected_vault_path()
        if path is None:
            return
        if self._state.unlocked and not self._is_connected_vault(path):
            # Selection can move; active connection stays until Switch/Connect.
            return
        if not self._state.unlocked:
            self._state.vault_path = path

    def _on_vault_activated(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        """Enter or double-click on a vault row → connect."""
        if self._connect_busy:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("kind") != NodeKind.VAULT:
            return
        path = Path(data["path"])
        # Already connected to this vault — no-op (no disconnect/password).
        if self._is_connected_vault(path):
            return
        self._switch_to_vault(path)

    def _vault_tree_menu(self, pos) -> None:
        menu = QMenu(self)
        item = self._vault_tree.itemAt(pos)
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        parent_id: str | None = None
        if isinstance(data, dict):
            if data.get("kind") == NodeKind.VAULT_GROUP:
                parent_id = data.get("id")
            elif data.get("kind") == NodeKind.VAULT:
                parent_id = data.get("parent_id")

        menu.addAction(
            "New group…",
            lambda pid=parent_id: self._new_vault_group(pid),
        )
        menu.addAction(
            "Add existing vault…",
            lambda pid=parent_id: self._add_existing_vault(parent_id=pid),
        )
        menu.addAction(
            "Create new vault…",
            lambda pid=parent_id: self._create_new_vault(parent_id=pid),
        )
        if isinstance(data, dict) and data.get("kind") == NodeKind.VAULT:
            path = Path(data["path"])
            menu.addSeparator()
            menu.addAction("Rename…", lambda p=path: self._rename_vault(p))
            if self._is_connected_vault(path):
                menu.addAction("Disconnect", self._menu_disconnect_vault)
            else:
                menu.addAction("Connect…", lambda p=path: self._switch_to_vault(p))
            menu.addAction(
                "Remove from list",
                lambda p=path: self._remove_vault_from_list(p),
            )
        elif isinstance(data, dict) and data.get("kind") == NodeKind.VAULT_GROUP:
            gid = data["id"]
            menu.addSeparator()
            menu.addAction("Rename group…", lambda i=gid: self._rename_vault_group(i))
            menu.addAction("Delete group", lambda i=gid: self._delete_vault_group(i))
        menu.exec(self._vault_tree.viewport().mapToGlobal(pos))

    def _new_vault_group(self, parent_id: str | None) -> None:
        name, ok = QInputDialog.getText(self, "New group", "Group name:")
        if not ok or not name.strip():
            return
        self._settings.add_vault_group(name.strip(), parent_id=parent_id)
        self._refresh_vault_tree()

    def _rename_vault(self, path: Path) -> None:
        current = path.name
        name, ok = QInputDialog.getText(
            self, "Rename vault", "File name:", text=current
        )
        if not ok:
            return
        new_name = name.strip()
        if not new_name:
            return
        if not new_name.lower().endswith(".vault"):
            new_name = f"{new_name}.vault"
        # Disallow path separators in the new file name.
        if Path(new_name).name != new_name:
            QMessageBox.warning(self, "Rename vault", "Enter a file name only.")
            return
        dest = path.with_name(new_name)
        if dest == path:
            return
        if dest.exists():
            QMessageBox.warning(
                self, "Rename vault", f"File already exists:\n{dest}"
            )
            return
        try:
            path.rename(dest)
            self._settings.rename_vault_path(path, dest)
        except OSError as exc:
            QMessageBox.critical(self, "Rename vault", str(exc))
            return
        if self._state.vault is not None and _norm_vault_key(
            self._state.vault.path
        ) == _norm_vault_key(path):
            self._state.vault.path = dest
        if _norm_vault_key(self._state.vault_path) == _norm_vault_key(path):
            self._state.vault_path = dest
        if self._connected_vault_path is not None and _norm_vault_key(
            self._connected_vault_path
        ) == _norm_vault_key(path):
            self._connected_vault_path = dest
            self._refresh_status_sessions()
        self._refresh_vault_tree()

    def _rename_vault_group(self, group_id: str) -> None:
        current = next(
            (
                n.name
                for n in self._settings.vault_nodes
                if n.kind == "group" and n.id == group_id
            ),
            "Group",
        )
        name, ok = QInputDialog.getText(
            self, "Rename group", "Group name:", text=current or "Group"
        )
        if not ok or not name.strip():
            return
        self._settings.rename_vault_group(group_id, name.strip())
        self._refresh_vault_tree()

    def _delete_vault_group(self, group_id: str) -> None:
        counts = self._settings.vault_group_content_counts(group_id)
        dlg = QDialog(self)
        dlg.setWindowTitle("Delete group")
        layout = QVBoxLayout(dlg)
        layout.addWidget(
            QLabel(
                "Delete this group and all contents?\n\n"
                f"{counts['groups']} subgroup(s), {counts['vaults']} vault(s)."
            )
        )
        cb = QCheckBox("Also delete vault files from disk")
        cb.setChecked(False)
        layout.addWidget(cb)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Delete")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        delete_files = cb.isChecked()
        paths = self._settings.delete_vault_group(
            group_id, delete_files=delete_files
        )
        if delete_files:
            for raw in paths:
                path = Path(raw)
                if self._is_connected_vault(path):
                    self._do_disconnect()
                try:
                    if path.is_file():
                        path.unlink()
                except OSError as exc:
                    QMessageBox.warning(
                        self,
                        "Delete group",
                        f"Could not delete file:\n{path}\n{exc}",
                    )
        self._refresh_vault_tree()

    def _on_vault_reparent(
        self, source: QTreeWidgetItem, target: QTreeWidgetItem | None
    ) -> None:
        src = self._node(source)
        if not src:
            return
        if src.get("kind") not in (NodeKind.VAULT, NodeKind.VAULT_GROUP):
            return
        new_parent: str | None = None
        if target is not None:
            dst = self._node(target)
            if not dst:
                return
            if dst.get("kind") == NodeKind.VAULT_GROUP:
                new_parent = dst.get("id")
            elif dst.get("kind") == NodeKind.VAULT:
                new_parent = dst.get("parent_id")
            else:
                return
            if src.get("kind") == NodeKind.VAULT_GROUP and src.get("id") == new_parent:
                return
        self._settings.move_vault_node(src["id"], new_parent)
        self._refresh_vault_tree()

    def _menu_disconnect_vault(self) -> None:
        if self._connect_busy:
            return
        self._connect_busy = True
        try:
            ok = self._do_disconnect()
            self._set_connect_checked(self._state.unlocked)
            if not ok and self._state.unlocked:
                return
        finally:
            self._connect_busy = False

    def _add_existing_vault(self, parent_id: str | None = None) -> None:
        start = str(
            self._selected_vault_path()
            or Path(self._settings.last_vault_path or default_vault_path())
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open vault",
            start,
            "HostsKeeper vault (*.vault);;All files (*.*)",
        )
        if not path:
            return
        self._settings.add_vault_path(path, parent_id=parent_id)
        self._refresh_vault_tree()

    def _create_new_vault(self, parent_id: str | None = None) -> None:
        start_dir = default_vault_path().parent
        start_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Create vault",
            str(default_vault_path()),
            "HostsKeeper vault (*.vault);;All files (*.*)",
        )
        if not path:
            return
        chosen = Path(path)
        if chosen.suffix.lower() != ".vault":
            chosen = chosen.with_suffix(".vault")
        self._settings.add_vault_path(chosen, parent_id=parent_id)
        self._refresh_vault_tree()

    def _remove_vault_from_list(self, path: Path) -> None:
        if self._is_connected_vault(path):
            QMessageBox.information(
                self,
                "Vaults",
                "Disconnect the vault before removing it from the list.",
            )
            return
        self._settings.remove_vault_path(path)
        self._refresh_vault_tree()

    def _highlight_vault_item(self, path: Path) -> None:
        key = _norm_vault_key(path)
        for i in range(self._vault_tree.topLevelItemCount()):
            item = self._vault_tree.topLevelItem(i)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and _norm_vault_key(data.get("path", "")) == key:
                self._vault_tree.setCurrentItem(item)
                break

    def _select_vault_item(self, path: Path) -> None:
        self._highlight_vault_item(path)
        self._state.vault_path = path

    def _switch_to_vault(self, path: Path) -> None:
        """Connect to vault; if another is open, disconnect it first."""
        if self._is_connected_vault(path) or self._connect_busy:
            return
        previous = (
            Path(self._connected_vault_path)
            if self._connected_vault_path is not None
            else None
        )
        # Highlight only — do not treat selection as the connected vault yet.
        self._highlight_vault_item(path)
        self._connect_busy = True
        try:
            ok = self._do_connect(path)
            if not ok:
                if previous is not None and self._state.unlocked:
                    self._highlight_vault_item(previous)
                self._set_connect_checked(self._state.unlocked)
            else:
                self._set_connect_checked(True)
        finally:
            self._connect_busy = False

    def _on_connect_triggered(self, checked: bool) -> None:
        if self._connect_busy:
            return
        self._connect_busy = True
        try:
            if checked:
                path = self._selected_vault_path()
                ok = self._do_connect(path)
                if not ok:
                    self._set_connect_checked(False)
            else:
                ok = self._do_disconnect()
                if not ok:
                    self._set_connect_checked(True)
        finally:
            self._connect_busy = False

    def _do_connect(self, path: Path | None = None) -> bool:
        target = path if path is not None else self._selected_vault_path()
        if target is None:
            QMessageBox.information(
                self,
                "Connect vault",
                "Select a vault in the Vaults list (or add one via right-click).",
            )
            return False
        if self._is_connected_vault(target):
            return True
        if self._state.unlocked:
            # Must disconnect first to switch vault.
            if not self._do_disconnect(
                confirm_message=(
                    "Disconnect the current vault and switch? Open sessions will close."
                )
            ):
                return False
        self._select_vault_item(target)
        dlg = UnlockDialog(self._state, target, self)
        if dlg.exec() != UnlockDialog.DialogCode.Accepted:
            return False
        assert self._state.mcp_service is not None
        self._wire_mcp_vault_refresh()
        ensure_mcp_http(
            self._state.mcp_service,
            self._state.mcp_host,
            self._state.mcp_port,
        )
        self._apply_session_connect_timeout()
        self._connected_vault_path = Path(target)
        self._settings.remember_last(target)
        self._set_unlocked_ui()
        self.refresh_tree()
        self._refresh_vault_tree()
        return True

    def _do_disconnect(self, *, confirm_message: str | None = None) -> bool:
        if not self._state.unlocked:
            self._connected_vault_path = None
            self._set_locked_ui()
            self._refresh_vault_tree()
            return True
        reply = QMessageBox.question(
            self,
            "Disconnect vault",
            confirm_message or "Disconnect vault and close sessions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        self._shutdown_runtime(lock_vault=True)
        self._shutting_down = False
        self._connected_vault_path = None
        self._set_locked_ui()
        self._refresh_vault_tree()
        return True

    def lock_vault(self) -> None:
        """Public lock helper (e.g. tests); mirrors disconnect."""
        self._act_connect.setChecked(False)
        self._on_connect_triggered(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._shutdown_runtime(lock_vault=True)
        super().closeEvent(event)

    def _shutdown_runtime(self, *, lock_vault: bool) -> None:
        """Stop workers, MCP HTTP and optionally lock vault (close SSH sessions)."""
        self._shutting_down = True
        self._stop_open_thread()
        self._clear_session_tabs()
        stop_mcp_http()
        if self._state.mcp_service is not None:
            self._state.mcp_service.set_vault_changed_callback(None)
        if lock_vault and self._state.unlocked:
            self._state.lock()
        if not lock_vault:
            self._shutting_down = False

    def _wire_mcp_vault_refresh(self) -> None:
        """MCP vault mutations refresh workspace tree + open panels/dialogs on GUI thread."""
        svc = self._state.mcp_service
        if svc is None:
            return
        svc.set_vault_changed_callback(self._schedule_tree_refresh)

    def _schedule_tree_refresh(self) -> None:
        # MCP may call from the HTTP worker thread — queue onto the Qt GUI thread.
        QMetaObject.invokeMethod(
            self,
            "_mcp_refresh_tree",
            Qt.ConnectionType.QueuedConnection,
        )

    @Slot()
    def _mcp_refresh_tree(self) -> None:
        if self._shutting_down:
            return
        self.refresh_tree()
        # Open Edit Host Scripts trees, Script/Note dialogs, etc.
        from hostskeeper.desktop.vault_ui_watch import notify_all

        notify_all()

    def _stop_open_thread(self, timeout_ms: int = 5000) -> None:
        thread = self._open_thread
        self._open_thread = None
        self._open_worker = None
        if thread is None:
            return
        if thread.isRunning():
            thread.quit()
            if not thread.wait(timeout_ms):
                thread.terminate()
                thread.wait(1000)

    def _sync_connect_action_label(self, connected: bool | None = None) -> None:
        """Toolbar label: Connect when locked, Disconnect when vault is open."""
        if connected is None:
            connected = bool(self._state.unlocked)
        if connected:
            self._act_connect.setText("Disconnect")
            self._act_connect.setToolTip("Disconnect the current vault and close sessions")
        else:
            self._act_connect.setText("Connect")
            self._act_connect.setToolTip("Unlock the selected vault")

    def _set_connect_checked(self, checked: bool) -> None:
        self._act_connect.blockSignals(True)
        self._act_connect.setChecked(checked)
        self._act_connect.blockSignals(False)
        self._sync_connect_action_label(checked)

    def _set_locked_ui(self) -> None:
        self._connected_vault_path = None
        self._set_connect_checked(False)
        self._act_close_all_tabs.setEnabled(False)
        self._hosts_root.takeChildren()
        self._scripts_root.takeChildren()
        self._hosts_root.addChild(QTreeWidgetItem(["(not connected)"]))
        self._selected_host_id = None
        self._selected_address_id = None
        self._selected_credential_id = None
        self._status.showMessage(
            f"Vault disconnected · MCP :{self._state.mcp_port} (starts after connect)"
        )

    def _set_unlocked_ui(self) -> None:
        if self._connected_vault_path is None and self._state.unlocked:
            self._connected_vault_path = Path(self._state.vault_path)
        self._set_connect_checked(True)
        self._act_close_all_tabs.setEnabled(True)
        name = (
            self._connected_vault_path.name
            if self._connected_vault_path is not None
            else self._state.vault_path.name
        )
        self._status.showMessage(
            f"Vault connected · {name} · MCP :{self._state.mcp_port} (app key)"
        )

    def refresh_tree(self) -> None:
        if not self._state.unlocked or self._state.vault is None:
            return
        self._suppress_expand_persist = True
        try:
            self._refresh_tree_body()
        finally:
            self._suppress_expand_persist = False

    def _refresh_tree_body(self) -> None:
        vault = self._state.vault
        assert vault is not None
        self._hosts_root.takeChildren()
        self._scripts_root.takeChildren()

        host_groups = {
            g.id: g for g in vault.list_groups(kind="hosts", only_templates=True)
        }
        script_groups = {
            g.id: g
            for g in vault.list_groups(kind="scripts", only_templates=True)
        }
        group_items: dict[UUID, QTreeWidgetItem] = {}

        def ensure_group_item(
            group_id: UUID,
            groups: dict[UUID, Group],
            root: QTreeWidgetItem,
            scope: str,
        ) -> QTreeWidgetItem:
            if group_id in group_items:
                return group_items[group_id]
            group = groups[group_id]
            item = QTreeWidgetItem([group.name])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": NodeKind.GROUP,
                    "id": group.id,
                    "scope": scope,
                    "parent_id": group.parent_id,
                },
            )
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            if group.parent_id and group.parent_id in groups:
                parent_item = ensure_group_item(
                    group.parent_id, groups, root, scope
                )
                parent_item.addChild(item)
            else:
                root.addChild(item)
            group_items[group_id] = item
            item.setExpanded(bool(group.expanded))
            return item

        for gid in sorted(host_groups, key=lambda i: host_groups[i].name.lower()):
            ensure_group_item(gid, host_groups, self._hosts_root, "hosts")
        for gid in sorted(script_groups, key=lambda i: script_groups[i].name.lower()):
            ensure_group_item(gid, script_groups, self._scripts_root, "scripts")

        for host in sorted(vault.list_hosts(), key=lambda h: h.name.lower()):
            host_item = QTreeWidgetItem([host.name])
            host_item.setIcon(0, host_icon())
            host_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": NodeKind.HOST,
                    "id": host.id,
                    "group_id": host.group_id,
                },
            )
            host_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            if host.group_id and host.group_id in group_items:
                group_items[host.group_id].addChild(host_item)
            else:
                self._hosts_root.addChild(host_item)

        for script in sorted(
            vault.list_scripts(only_templates=True), key=lambda s: s.name.lower()
        ):
            item = QTreeWidgetItem([script.name])
            item.setIcon(0, script_icon())
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": NodeKind.SCRIPT,
                    "id": script.id,
                    "group_id": script.group_id,
                },
            )
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            if script.group_id and script.group_id in group_items:
                group_items[script.group_id].addChild(item)
            else:
                self._scripts_root.addChild(item)

        for note in sorted(
            vault.list_notes(only_templates=True), key=lambda n: n.name.lower()
        ):
            item = QTreeWidgetItem([note.name])
            item.setIcon(0, note_icon(mcp_enabled=note.mcp_enabled))
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": NodeKind.NOTE,
                    "id": note.id,
                    "group_id": note.group_id,
                },
            )
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            if note.group_id and note.group_id in group_items:
                group_items[note.group_id].addChild(item)
            else:
                self._scripts_root.addChild(item)

        apply_group_folder_icons(self._hosts_root, group_kinds=_GROUP_FOLDER_KINDS)
        apply_group_folder_icons(self._scripts_root, group_kinds=_GROUP_FOLDER_KINDS)
        self._hosts_root.setExpanded(vault.tree_root_expanded("hosts"))
        self._scripts_root.setExpanded(vault.tree_root_expanded("scripts"))
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        q = (text or "").strip().lower()

        def filter_item(item: QTreeWidgetItem) -> bool:
            if not q:
                item.setHidden(False)
                for i in range(item.childCount()):
                    filter_item(item.child(i))
                return True
            self_match = q in item.text(0).lower()
            child_match = False
            for i in range(item.childCount()):
                if filter_item(item.child(i)):
                    child_match = True
            visible = self_match or child_match
            item.setHidden(not visible)
            return visible

        for i in range(self._hosts_root.childCount()):
            filter_item(self._hosts_root.child(i))
        for i in range(self._scripts_root.childCount()):
            filter_item(self._scripts_root.child(i))
        self._hosts_root.setHidden(False)
        self._scripts_root.setHidden(False)

    def _node(self, item: QTreeWidgetItem | None) -> dict | None:
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _select_workspace_item(self, kind: NodeKind, item_id: UUID) -> bool:
        """Restore selection after refresh_tree rebuilds items."""

        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            data = self._node(item)
            if (
                data
                and data.get("kind") == kind
                and data.get("id") == item_id
            ):
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for root in (self._hosts_root, self._scripts_root):
            found = walk(root)
            if found is None:
                continue
            self._suppress_expand_persist = True
            try:
                parent = found.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
            finally:
                self._suppress_expand_persist = False
            self._tree.setCurrentItem(found)
            self._tree.scrollToItem(found)
            return True
        return False

    def _on_workspace_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._persist_workspace_expand(item, True)

    def _on_workspace_item_collapsed(self, item: QTreeWidgetItem) -> None:
        self._persist_workspace_expand(item, False)

    def _persist_workspace_expand(
        self, item: QTreeWidgetItem, expanded: bool
    ) -> None:
        from hostskeeper.runtime.tree_debug_log import log, log_exception

        if self._suppress_expand_persist or not self._state.unlocked:
            log(
                "workspace_expand_skip",
                reason=(
                    "suppress"
                    if self._suppress_expand_persist
                    else "locked"
                ),
                expanded=expanded,
                text=item.text(0),
            )
            return
        node = self._node(item)
        if not node:
            log("workspace_expand_skip", reason="no_node", expanded=expanded)
            return
        kind = node.get("kind")
        log(
            "workspace_expand_begin",
            expanded=expanded,
            kind=getattr(kind, "value", kind),
            id=node.get("id"),
            text=item.text(0),
            unlocked=self._state.unlocked,
        )
        try:
            vault = self._vault()
            if kind == NodeKind.HOSTS_ROOT:
                vault.set_tree_root_expanded("hosts", expanded)
            elif kind == NodeKind.SCRIPTS_ROOT:
                vault.set_tree_root_expanded("scripts", expanded)
            elif kind == NodeKind.GROUP:
                vault.set_group_expanded(node["id"], expanded)
            else:
                log(
                    "workspace_expand_skip",
                    reason="kind",
                    kind=getattr(kind, "value", kind),
                )
                return
            log(
                "workspace_expand_ok",
                expanded=expanded,
                kind=getattr(kind, "value", kind),
                id=node.get("id"),
            )
        except Exception as exc:  # noqa: BLE001
            log_exception(
                "workspace_expand_fail",
                exc,
                expanded=expanded,
                kind=getattr(kind, "value", kind),
                id=node.get("id"),
            )
            return

    def _on_vault_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._persist_vault_expand(item, True)

    def _on_vault_item_collapsed(self, item: QTreeWidgetItem) -> None:
        self._persist_vault_expand(item, False)

    def _persist_vault_expand(
        self, item: QTreeWidgetItem, expanded: bool
    ) -> None:
        from hostskeeper.runtime.tree_debug_log import log, log_exception

        if self._suppress_expand_persist:
            log(
                "vaults_expand_skip",
                reason="suppress",
                expanded=expanded,
                text=item.text(0),
            )
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or data.get("kind") != NodeKind.VAULT_GROUP:
            return
        group_id = data.get("id")
        if not isinstance(group_id, str):
            return
        log(
            "vaults_expand_begin",
            expanded=expanded,
            id=group_id,
            text=item.text(0),
        )
        try:
            self._settings.set_vault_group_expanded(group_id, expanded)
            log("vaults_expand_ok", expanded=expanded, id=group_id)
        except Exception as exc:  # noqa: BLE001
            log_exception(
                "vaults_expand_fail",
                exc,
                expanded=expanded,
                id=group_id,
            )

    def _tree_menu(self, pos) -> None:
        if not self._state.unlocked:
            return
        item = self._tree.itemAt(pos)
        node = self._node(item) if item is not None else None
        menu = QMenu(self)
        # Empty viewport (below items) → same as Scripts root.
        if node is None:
            self._fill_scripts_root_menu(menu)
            menu.exec(self._tree.viewport().mapToGlobal(pos))
            return
        kind = node.get("kind")
        if kind == NodeKind.HOSTS_ROOT:
            self._fill_hosts_new_menu(menu, group_id=None)
        elif kind == NodeKind.SCRIPTS_ROOT:
            self._fill_scripts_new_menu(menu, group_id=None)
        elif kind == NodeKind.GROUP:
            scope = node.get("scope") or "hosts"
            gid = node["id"]
            if scope == "hosts":
                self._fill_hosts_new_menu(menu, group_id=gid)
            else:
                self._fill_scripts_new_menu(menu, group_id=gid)
            menu.addSeparator()
            menu.addAction("Rename group…", lambda g=gid: self._rename_workspace_group(g))
            menu.addAction("Delete group", lambda g=gid: self._delete_workspace_group(g))
        elif kind == NodeKind.HOST:
            self._fill_hosts_new_menu(menu, group_id=node.get("group_id"))
            menu.addSeparator()
            menu.addAction("Open Tab…", self.open_selected_tab)
            menu.addAction("PuTTY…", lambda: self._launch_external("putty"))
            menu.addAction("WinSCP…", lambda: self._launch_external("winscp"))
            menu.addSeparator()
            menu.addAction("Edit Host", lambda: self._edit_host(node["id"]))
            menu.addAction("Delete Host", lambda: self._delete_host(node["id"]))
        elif kind == NodeKind.SCRIPT:
            self._fill_scripts_new_menu(menu, group_id=node.get("group_id"))
            menu.addSeparator()
            menu.addAction("Run…", lambda: self._run_template_script(node["id"]))
            menu.addAction("Copy", lambda: self._copy_script(node["id"]))
            menu.addAction("Edit", lambda: self._edit_script(node["id"]))
            menu.addAction("Delete", lambda: self._delete_script(node["id"]))
        elif kind == NodeKind.NOTE:
            self._fill_scripts_new_menu(menu, group_id=node.get("group_id"))
            menu.addSeparator()
            menu.addAction("Edit", lambda: self._edit_note(node["id"]))
            menu.addAction("Delete", lambda: self._delete_note(node["id"]))
        if not menu.isEmpty():
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _fill_hosts_new_menu(
        self, menu: QMenu, *, group_id: UUID | None
    ) -> None:
        new_menu = menu.addMenu("New")
        act_group = new_menu.addAction(folder_icon(filled=False), "Group")
        act_group.triggered.connect(
            lambda: self._new_workspace_group("hosts", group_id)
        )
        act_host = new_menu.addAction(host_icon(), "Host")
        act_host.triggered.connect(lambda: self._new_host(group_id=group_id))

    def _fill_scripts_new_menu(
        self, menu: QMenu, *, group_id: UUID | None
    ) -> None:
        new_menu = menu.addMenu("New")
        act_group = new_menu.addAction(folder_icon(filled=False), "Group")
        act_group.triggered.connect(
            lambda: self._new_workspace_group("scripts", group_id)
        )
        act_script = new_menu.addAction(script_icon(), "Script")
        act_script.triggered.connect(lambda: self._new_script(group_id=group_id))
        act_note = new_menu.addAction(note_icon(), "Note")
        act_note.triggered.connect(lambda: self._new_note(group_id=group_id))

    def _fill_scripts_root_menu(self, menu: QMenu) -> None:
        self._fill_scripts_new_menu(menu, group_id=None)

    def _new_workspace_group(
        self, kind: str, parent_id: UUID | None
    ) -> None:
        if not self._state.unlocked:
            return
        name, ok = QInputDialog.getText(self, "New group", "Group name:")
        if not ok or not name.strip():
            return
        self._vault().add_group(
            Group(name=name.strip(), kind=kind, parent_id=parent_id)
        )
        self.refresh_tree()

    def _rename_workspace_group(self, group_id: UUID) -> None:
        try:
            group = self._vault().get_group(group_id)
        except NotFoundError:
            return
        name, ok = QInputDialog.getText(
            self, "Rename group", "Group name:", text=group.name
        )
        if not ok or not name.strip():
            return
        group.name = name.strip()
        self._vault().update_group(group)
        self.refresh_tree()

    def _delete_workspace_group(self, group_id: UUID) -> None:
        try:
            counts = self._vault().group_content_counts(group_id)
        except NotFoundError:
            return
        msg = (
            "Delete this group and all contents?\n\n"
            f"{counts['groups']} subgroup(s), {counts['hosts']} host(s), "
            f"{counts['scripts']} script(s), {counts['notes']} note(s)."
        )
        if (
            QMessageBox.warning(
                self,
                "Delete group",
                msg,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._vault().delete_group(group_id)
        except NotFoundError:
            return
        self.refresh_tree()

    def _on_workspace_reparent(
        self, source: QTreeWidgetItem, target: QTreeWidgetItem | None
    ) -> None:
        if not self._state.unlocked:
            return
        src = self._node(source)
        if not src:
            return
        kind = src.get("kind")
        if kind not in (NodeKind.HOST, NodeKind.SCRIPT, NodeKind.NOTE, NodeKind.GROUP):
            return

        new_group_id: UUID | None = None
        dst_scope: str | None = None
        if target is None:
            self.refresh_tree()
            return
        dst = self._node(target)
        if not dst:
            return
        dst_kind = dst.get("kind")
        if dst_kind == NodeKind.HOSTS_ROOT:
            dst_scope = "hosts"
            new_group_id = None
        elif dst_kind == NodeKind.SCRIPTS_ROOT:
            dst_scope = "scripts"
            new_group_id = None
        elif dst_kind == NodeKind.GROUP:
            dst_scope = dst.get("scope")
            new_group_id = dst.get("id")
        elif dst_kind == NodeKind.HOST:
            dst_scope = "hosts"
            new_group_id = dst.get("group_id")
        elif dst_kind in (NodeKind.SCRIPT, NodeKind.NOTE):
            dst_scope = "scripts"
            new_group_id = dst.get("group_id")
        else:
            self.refresh_tree()
            return

        try:
            if kind == NodeKind.HOST:
                if dst_scope != "hosts":
                    self.refresh_tree()
                    return
                host = self._vault().get_host(src["id"])
                host.group_id = new_group_id
                self._vault().update_host(host)
            elif kind == NodeKind.SCRIPT:
                if dst_scope != "scripts":
                    self.refresh_tree()
                    return
                script = self._vault().get_script(src["id"])
                script.group_id = new_group_id
                self._vault().update_script(script)
            elif kind == NodeKind.NOTE:
                if dst_scope != "scripts":
                    self.refresh_tree()
                    return
                note = self._vault().get_note(src["id"])
                note.group_id = new_group_id
                self._vault().update_note(note)
            elif kind == NodeKind.GROUP:
                group = self._vault().get_group(src["id"])
                if dst_scope != group.kind:
                    self.refresh_tree()
                    return
                if new_group_id == group.id:
                    self.refresh_tree()
                    return
                group.parent_id = new_group_id
                self._vault().update_group(group)
        except Exception:  # noqa: BLE001
            self.refresh_tree()
            return
        self.refresh_tree()

    def _tree_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        node = self._node(item)
        if not node or not self._state.unlocked:
            return
        kind = node.get("kind")
        if kind == NodeKind.HOST:
            self._edit_host(node["id"])
        elif kind == NodeKind.SCRIPT:
            self._edit_script(node["id"])
        elif kind == NodeKind.NOTE:
            self._edit_note(node["id"])

    def _vault(self):
        assert self._state.vault is not None
        return self._state.vault

    def _new_host(self, group_id: UUID | None = None) -> None:
        if not self._state.unlocked:
            return
        dlg = HostDialog(self._vault(), parent=self, group_id=group_id)
        if dlg.exec() == HostDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _edit_host(self, host_id: UUID) -> None:
        try:
            host = self._vault().get_host(host_id)
        except NotFoundError:
            return
        dlg = HostDialog(
            self._vault(),
            host=host,
            parent=self,
            on_open_tab=self._open_tab_for,
            on_putty=lambda h, a, c: self._launch_external_for("putty", h, a, c),
            on_winscp=lambda h, a, c: self._launch_external_for("winscp", h, a, c),
            on_run_script=self._run_script_target,
            list_host_sessions=self._list_host_sessions,
        )
        if dlg.exec() == HostDialog.DialogCode.Accepted:
            self.refresh_tree()
            self._select_workspace_item(NodeKind.HOST, host_id)
            self._on_tree_selection()
        elif dlg.result_host is not None:
            # Connect buttons persist host without closing via OK.
            self.refresh_tree()
            self._select_workspace_item(NodeKind.HOST, host_id)
            self._on_tree_selection()

    def _delete_host(self, host_id: UUID) -> None:
        try:
            host = self._vault().get_host(host_id)
        except NotFoundError:
            return
        if (
            QMessageBox.question(
                self,
                "Delete Host",
                f"Delete host «{host.name}» and its addresses/credentials/scripts/notes?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._vault().delete_host(host_id)
        self.refresh_tree()

    def _new_address(self, host_id: UUID) -> None:
        dlg = AddressDialog(self._vault(), host_id, parent=self)
        if dlg.exec() == AddressDialog.DialogCode.Accepted:
            self.refresh_tree()
            self._select_workspace_item(NodeKind.HOST, host_id)
            self._on_tree_selection()

    def _edit_address(self, address_id: UUID) -> None:
        try:
            addr = self._vault().get_address(address_id)
        except NotFoundError:
            return
        dlg = AddressDialog(self._vault(), addr.host_id, address=addr, parent=self)
        if dlg.exec() == AddressDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _delete_address(self, address_id: UUID) -> None:
        if (
            QMessageBox.question(self, "Delete Address", "Delete this address?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._vault().delete_address(address_id)
        self.refresh_tree()

    def _new_credential(self, host_id: UUID) -> None:
        dlg = CredentialDialog(self._vault(), host_id, parent=self)
        if dlg.exec() == CredentialDialog.DialogCode.Accepted:
            self.refresh_tree()
            self._select_workspace_item(NodeKind.HOST, host_id)
            self._on_tree_selection()

    def _edit_credential(self, credential_id: UUID) -> None:
        try:
            cred = self._vault().get_credential(credential_id)
        except NotFoundError:
            return
        dlg = CredentialDialog(
            self._vault(), cred.host_id, credential=cred, parent=self
        )
        if dlg.exec() == CredentialDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _delete_credential(self, credential_id: UUID) -> None:
        if (
            QMessageBox.question(self, "Delete Credential", "Delete this credential?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._vault().delete_credential(credential_id)
        self.refresh_tree()

    def _reveal(self, credential_id: UUID) -> None:
        try:
            cred = self._vault().get_credential(credential_id)
        except NotFoundError:
            return
        ok = QMessageBox.question(
            self,
            "Reveal secret",
            "Show password/key for this credential in a dialog?",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        RevealSecretDialog(cred, self).exec()

    def _new_script(self, group_id: UUID | None = None) -> None:
        if not self._state.unlocked:
            return
        dlg = ScriptDialog(self._vault(), parent=self, group_id=group_id)
        if dlg.exec() == ScriptDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _new_note(self, group_id: UUID | None = None) -> None:
        if not self._state.unlocked:
            return
        dlg = NoteDialog(self._vault(), parent=self, group_id=group_id)
        if dlg.exec() == NoteDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _edit_note(self, note_id: UUID) -> None:
        try:
            note = self._vault().get_note(note_id)
        except NotFoundError:
            return
        dlg = NoteDialog(self._vault(), note=note, parent=self)
        if dlg.exec() == NoteDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _delete_note(self, note_id: UUID) -> None:
        try:
            note = self._vault().get_note(note_id)
        except NotFoundError:
            return
        if (
            QMessageBox.question(
                self, "Delete Note", f"Delete note «{note.name}»?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._vault().delete_note(note_id)
        self.refresh_tree()

    def _edit_script(self, script_id: UUID) -> None:
        try:
            script = self._vault().get_script(script_id)
        except NotFoundError:
            return
        dlg = ScriptDialog(self._vault(), script=script, parent=self)
        if dlg.exec() == ScriptDialog.DialogCode.Accepted:
            self.refresh_tree()

    def _delete_script(self, script_id: UUID) -> None:
        try:
            script = self._vault().get_script(script_id)
        except NotFoundError:
            return
        if (
            QMessageBox.question(
                self, "Delete Script", f"Delete script «{script.name}»?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._vault().delete_script(script_id)
        self.refresh_tree()

    def _copy_script(self, script_id: UUID) -> None:
        from hostskeeper.desktop.script_clipboard import copy_script_to_clipboard

        try:
            script = self._vault().get_script(script_id)
        except NotFoundError:
            return
        copy_script_to_clipboard(script)

    def _run_template_script(self, script_id: UUID) -> None:
        """Run a global Scripts-tree template against a chosen host."""
        from hostskeeper.mcp.errors import McpToolError
        from hostskeeper.mcp.scripts_render import render_script

        if not self._state.unlocked or self._state.sessions is None:
            return
        try:
            script = self._vault().get_script(script_id)
        except NotFoundError:
            return
        if script.host_id is not None:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "Host scripts are run from Edit Host → Scripts.",
            )
            return
        host = self._pick_host_for_script_run()
        if host is None:
            return
        addr_id = host.default_address_id
        cred_id = host.default_credential_id
        if addr_id is None or cred_id is None:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "Set Address and Credential on the host before running a script.",
            )
            return
        sessions = [
            (s.id, s.alias)
            for s in self._state.sessions.list_sessions()
            if s.host_id == host.id
        ]
        dlg = RunScriptTargetDialog(sessions, script=script, parent=self)
        if dlg.exec() != RunScriptTargetDialog.DialogCode.Accepted or dlg.mode is None:
            return
        try:
            rendered = render_script(
                script, {}, use_user_values=dlg.use_user_values
            )
        except McpToolError as exc:
            QMessageBox.warning(self, "Run script", str(exc))
            return
        self._run_script_target(host.id, addr_id, cred_id, rendered, dlg.mode)

    def _pick_host_for_script_run(self):
        """Ask which host to run a template script on. Returns Host or None."""
        from hostskeeper.desktop.dialogs import PickHostDialog

        hosts = sorted(self._vault().list_hosts(), key=lambda h: h.name.lower())
        if not hosts:
            QMessageBox.information(self, "HostsKeeper", "No hosts in vault.")
            return None
        if len(hosts) == 1:
            return hosts[0]
        dlg = PickHostDialog(hosts, parent=self)
        if dlg.exec() != PickHostDialog.DialogCode.Accepted:
            return None
        return dlg.selected_host

    def _on_tree_selection(self) -> None:
        if not self._state.unlocked:
            return
        items = self._tree.selectedItems()
        if not items:
            return
        node = self._node(items[0])
        if not node:
            return
        kind = node.get("kind")
        if kind == NodeKind.HOST:
            self._selected_host_id = node["id"]
            host = self._vault().get_host(node["id"])
            # Strict: only Address/Credential set on the host (Edit Host dialog).
            self._selected_address_id = host.default_address_id
            self._selected_credential_id = host.default_credential_id

    def open_selected_tab(self) -> None:
        self._on_tree_selection()
        self._open_tab_for(
            self._selected_host_id,
            self._selected_address_id,
            self._selected_credential_id,
        )

    def _open_tab_for(
        self,
        host_id: UUID | None,
        address_id: UUID | None,
        credential_id: UUID | None,
    ) -> None:
        if not self._state.unlocked or self._state.sessions is None:
            QMessageBox.information(
                self,
                "Open Tab",
                "Connect a vault first.",
            )
            return
        if self._open_thread is not None and self._open_thread.isRunning():
            return
        if host_id is None or address_id is None or credential_id is None:
            QMessageBox.information(
                self,
                "Open Tab",
                "Select a host and set Address and Credential in Edit Host.",
            )
            return
        self._selected_host_id = host_id
        self._selected_address_id = address_id
        self._selected_credential_id = credential_id
        self._status.showMessage("Connecting…")
        thread = QThread()
        thread.setObjectName("hostskeeper-open-tab")
        worker = _OpenTabWorker(
            self._state.sessions, host_id, address_id, credential_id, None
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            self._on_open_tab_ok, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(
            self._on_open_tab_fail, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_open_thread_finished)
        self._open_worker = worker
        self._open_thread = thread
        thread.start()

    @Slot()
    def _on_open_thread_finished(self) -> None:
        self._open_thread = None
        self._open_worker = None

    @Slot(object)
    def _on_open_tab_ok(self, info) -> None:
        if self._shutting_down:
            return
        self._attach_session_tab(info.id, info.alias)
        pending = self._pending_script_write
        self._pending_script_write = None
        if pending and self._state.sessions is not None:
            try:
                self._state.sessions.write(info.id, pending, submit=True)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Run script", str(exc))
        self._status.showMessage(f"Session {info.alias} · {info.status.value}")

    @Slot(str)
    def _on_open_tab_fail(self, message: str) -> None:
        if self._shutting_down:
            return
        self._pending_script_write = None
        QMessageBox.critical(self, "Open Tab failed", message)
        self._status.showMessage("Connect failed")

    def _attach_session_tab(self, session_id: UUID, alias: str) -> None:
        assert self._state.sessions is not None
        if self._welcome_index is not None:
            self._tabs.removeTab(self._welcome_index)
            self._welcome_index = None
        tab = SessionTab(
            self._state.sessions,
            session_id,
            mcp_host=self._state.mcp_host,
            mcp_port=self._state.mcp_port,
            parent=self._tabs,
        )
        tab.closed.connect(self._on_session_tab_closed)
        tab.status_changed.connect(self._refresh_status_sessions)
        idx = self._tabs.addTab(tab, alias)
        self._tabs.setCurrentIndex(idx)
        self._session_tabs[session_id] = tab

    def _on_session_tab_closed(self, session_id: UUID) -> None:
        tab = self._session_tabs.pop(session_id, None)
        if tab is None:
            return
        idx = self._tabs.indexOf(tab)
        if idx >= 0:
            self._tabs.removeTab(idx)
        tab.deleteLater()
        if self._tabs.count() == 0:
            placeholder = QLabel("No open sessions.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrap = QWidget()
            wrap_layout = QVBoxLayout(wrap)
            wrap_layout.addWidget(placeholder)
            self._welcome_index = self._tabs.addTab(wrap, "Welcome")

    def _on_tab_close_requested(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if isinstance(widget, SessionTab):
            widget.close_session()

    def _clear_session_tabs(self) -> None:
        for sid in list(self._session_tabs.keys()):
            tab = self._session_tabs.pop(sid)
            tab.shutdown_ui()
            idx = self._tabs.indexOf(tab)
            if idx >= 0:
                self._tabs.removeTab(idx)
            tab.deleteLater()
        if self._tabs.count() == 0:
            placeholder = QLabel("No open sessions.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrap = QWidget()
            wrap_layout = QVBoxLayout(wrap)
            wrap_layout.addWidget(placeholder)
            self._welcome_index = self._tabs.addTab(wrap, "Welcome")

    def _refresh_status_sessions(self) -> None:
        if not self._state.unlocked or self._state.sessions is None:
            return
        n = len(self._state.sessions.list_sessions())
        mcp_n = len(self._state.sessions.list_mcp_sessions())
        self._status.showMessage(
            f"Vault connected · {self._state.vault_path.name} · "
            f"sessions:{n} · mcp-on:{mcp_n} · MCP :{self._state.mcp_port}"
        )

    def _launch_external(self, kind: str) -> None:
        self._on_tree_selection()
        self._launch_external_for(
            kind,
            self._selected_host_id,
            self._selected_address_id,
            self._selected_credential_id,
        )

    def _list_host_sessions(self, host_id: UUID) -> list[tuple[UUID, str]]:
        if self._state.sessions is None:
            return []
        return [
            (s.id, s.alias)
            for s in self._state.sessions.list_sessions()
            if s.host_id == host_id
        ]

    def _run_script_target(
        self,
        host_id: UUID,
        address_id: UUID,
        credential_id: UUID,
        rendered: str,
        mode: str,
    ) -> None:
        if mode == "new_tab":
            self._pending_script_write = rendered
            self._open_tab_for(host_id, address_id, credential_id)
            return
        if mode == "putty":
            self._launch_external_for(
                "putty",
                host_id,
                address_id,
                credential_id,
                remote_command=rendered,
            )
            return
        try:
            session_id = UUID(mode)
        except ValueError:
            QMessageBox.warning(self, "Run script", "Invalid session.")
            return
        if self._state.sessions is None:
            return
        try:
            self._state.sessions.write(session_id, rendered, submit=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Run script", str(exc))

    def _on_workspace_foreign_drop(
        self, payload: dict, target: QTreeWidgetItem | None
    ) -> None:
        """Copy host script/group into global Scripts tree (duplicate as template)."""
        if not self._state.unlocked:
            return
        if not payload.get("host_id"):
            return
        kind = str(payload.get("kind") or "")
        try:
            src_id = UUID(str(payload["id"]))
        except (KeyError, ValueError):
            return
        dest_group: UUID | None = None
        if target is not None:
            dst = self._node(target)
            if dst:
                dst_kind = dst.get("kind")
                if dst_kind == NodeKind.SCRIPTS_ROOT:
                    dest_group = None
                elif dst_kind == NodeKind.GROUP and dst.get("scope") == "scripts":
                    dest_group = dst.get("id")
                elif dst_kind == NodeKind.SCRIPT:
                    dest_group = dst.get("group_id")
                else:
                    return
        try:
            if kind == "script":
                src = self._vault().get_script(src_id)
                name = self._vault().suggest_script_name(src.name, host_id=None)
                from hostskeeper.vault import Script

                self._vault().add_script(
                    Script(
                        name=name,
                        body=src.body,
                        description=src.description,
                        tags=list(src.tags),
                        parameters=list(src.parameters),
                        group_id=dest_group,
                        host_id=None,
                    )
                )
            elif kind == "group":
                # Shallow: copy group + nested host scripts as templates.
                self._copy_host_group_to_templates(src_id, dest_group)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.refresh_tree()

    def _copy_host_group_to_templates(
        self, src_id: UUID, dest_parent: UUID | None
    ) -> None:
        from hostskeeper.vault import Script

        vault = self._vault()
        src = vault.get_group(src_id)
        if src.kind != "scripts" or src.host_id is None:
            return
        host_id = src.host_id
        groups = {
            g.id: g for g in vault.list_groups(kind="scripts", host_id=host_id)
        }
        id_map: dict[UUID, UUID] = {}

        def copy_subtree(gid: UUID, parent_new: UUID | None) -> None:
            g = groups[gid]
            created = vault.add_group(
                Group(
                    name=g.name,
                    kind="scripts",
                    parent_id=parent_new,
                    host_id=None,
                )
            )
            id_map[gid] = created.id
            for child_id, child in groups.items():
                if child.parent_id == gid:
                    copy_subtree(child_id, created.id)

        copy_subtree(src_id, dest_parent)

        def under_src(group_id: UUID | None) -> bool:
            walk = group_id
            while walk is not None:
                if walk == src_id or walk in id_map:
                    return True
                parent = groups.get(walk)
                walk = parent.parent_id if parent else None
            return False

        for script in vault.list_scripts(host_id=host_id):
            if not under_src(script.group_id):
                continue
            new_gid = id_map.get(script.group_id) if script.group_id else None
            name = vault.suggest_script_name(script.name, host_id=None)
            vault.add_script(
                Script(
                    name=name,
                    body=script.body,
                    description=script.description,
                    tags=list(script.tags),
                    parameters=list(script.parameters),
                    group_id=new_gid,
                    host_id=None,
                )
            )

    def _launch_external_for(
        self,
        kind: str,
        host_id: UUID | None,
        address_id: UUID | None,
        credential_id: UUID | None,
        *,
        remote_command: str | None = None,
    ) -> None:
        if not self._state.unlocked:
            return
        if host_id is None or address_id is None or credential_id is None:
            QMessageBox.information(
                self,
                kind.upper(),
                "Set Address and Credential for the host in Edit Host first.",
            )
            return
        self._selected_host_id = host_id
        self._selected_address_id = address_id
        self._selected_credential_id = credential_id
        try:
            address = self._vault().get_address(address_id)
            credential = self._vault().get_credential(credential_id)
            if address.host_id != host_id or credential.host_id != host_id:
                raise ValueError("address/credential host mismatch")
            paths = discover_launchers(
                putty=self._settings.putty_path,
                winscp=self._settings.winscp_path,
            )
            if kind == "putty":
                launch_putty(
                    paths, address, credential, remote_command=remote_command
                )
            else:
                launch_winscp(paths, address, credential)
        except FileNotFoundError as exc:
            QMessageBox.critical(self, kind.upper(), str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, kind.upper(), str(exc))

    def _close_all_tabs(self) -> None:
        n = len(self._session_tabs)
        if n == 0:
            QMessageBox.information(self, "Close All Tabs", "No session tabs open.")
            return
        reply = QMessageBox.question(
            self,
            "Close All Tabs",
            f"Close all {n} session tab(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for sid in list(self._session_tabs.keys()):
            tab = self._session_tabs.get(sid)
            if tab is not None:
                tab.close_session()
        self._refresh_status_sessions()

    def _copy_mcp_config(self) -> None:
        if not self._state.mcp_key:
            QMessageBox.information(self, "MCP", "MCP key is not available.")
            return
        host = _public_mcp_host(self._state.mcp_host)
        text = cursor_mcp_config(
            host=host, port=self._state.mcp_port, key=self._state.mcp_key
        )
        QGuiApplication.clipboard().setText(text)
        self._status.showMessage(
            f"MCP config copied · http://{host}:{self._state.mcp_port}/mcp?key=…"
        )

    def _change_mcp_key(self) -> None:
        reply = QMessageBox.warning(
            self,
            "Change MCP Key",
            "Generate a new MCP app key?\n\n"
            "The old key stops working immediately. "
            "Update Cursor mcp.json with Copy MCP config.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._state.rotate_mcp_app_key()
        except OSError as exc:
            QMessageBox.warning(self, "Change MCP Key", f"Could not write key:\n{exc}")
            return
        self._status.showMessage("MCP key changed · use Copy MCP config")
        QMessageBox.information(
            self,
            "Change MCP Key",
            "New MCP key is active.\nUse Copy MCP config to update Cursor.",
        )
