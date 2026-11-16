"""Host-local Scripts tree for Edit Host → Scripts tab."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from hostskeeper.desktop.dialogs import NoteDialog, ScriptDialog
from hostskeeper.desktop.drop_tree import DropTreeWidget
from hostskeeper.desktop.folder_icon import (
    apply_group_folder_icons,
    folder_icon,
    note_icon,
    script_icon,
)
from hostskeeper.vault import Group, Script
from hostskeeper.vault.errors import NotFoundError
from hostskeeper.vault.store import Vault

NodePayload = dict

_SCRIPT_GROUP_KINDS = frozenset({"group"})


class HostScriptsPanel(QWidget):
    """Tree of host-scoped script groups + scripts with CRUD / Run / DnD copy-in."""

    def __init__(
        self,
        vault: Vault,
        host_id: UUID | None,
        parent=None,
        *,
        on_run: Callable[[Script], None] | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(parent)
        self._vault = vault
        self._host_id = host_id
        self._on_run = on_run
        self._enabled = enabled and host_id is not None
        self._compact_hint: QSize | None = None
        self._suppress_expand_persist = False

        self._hint = QLabel("Save the host first to manage its scripts.")
        self._hint.setWordWrap(True)
        self._hint.setVisible(host_id is None)

        self._tree = DropTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.reparent_requested.connect(self._on_reparent)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.itemSelectionChanged.connect(self._sync_selection_actions)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)
        # Modal dialog: no cross-window DnD from main Scripts tree.

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("Add Script")
        self._btn_note = QPushButton("Add Note")
        self._btn_group = QPushButton("New group")
        self._btn_edit = QPushButton("Edit")
        self._btn_run = QPushButton("Run")
        self._btn_del = QPushButton("Delete")
        self._btn_add.clicked.connect(self._add_script)
        self._btn_note.clicked.connect(self._add_note)
        self._btn_group.clicked.connect(self._add_group)
        self._btn_edit.clicked.connect(self._edit_selected)
        self._btn_run.clicked.connect(self._run_selected)
        self._btn_del.clicked.connect(self._delete_selected)
        for b in (
            self._btn_group,
            self._btn_add,
            self._btn_note,
            self._btn_edit,
            self._btn_del,
            self._btn_run,
        ):
            btn_row.addWidget(b)
        btn_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._hint)
        layout.addWidget(self._tree, stretch=1)
        layout.addLayout(btn_row)
        self._set_actions_enabled(self._enabled)
        if self._enabled:
            self.refresh()
        from hostskeeper.desktop.vault_ui_watch import register

        register(self)

    def on_vault_externally_changed(self) -> None:
        """MCP (or other) mutated vault — refresh if this host tree is on screen."""
        if not self._enabled or self._host_id is None:
            return
        if not self.isVisible():
            return
        self.refresh()

    def set_compact_size_hint(self, hint: QSize | None) -> None:
        """When set, sizeHint matches Host tab so the dialog is not inflated."""
        self._compact_hint = hint
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._compact_hint is not None:
            return QSize(self._compact_hint)
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        if self._compact_hint is not None:
            return QSize(self._compact_hint)
        return super().minimumSizeHint()

    def set_host_id(self, host_id: UUID | None) -> None:
        self._host_id = host_id
        self._enabled = host_id is not None
        self._hint.setVisible(host_id is None)
        self._set_actions_enabled(self._enabled)
        if self._enabled:
            self.refresh()
        else:
            self._tree.clear()

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._btn_add.setEnabled(enabled)
        self._btn_note.setEnabled(enabled)
        self._btn_group.setEnabled(enabled)
        self._tree.setEnabled(enabled)
        self._sync_selection_actions()

    def _sync_selection_actions(self) -> None:
        """Edit/Run for scripts; Edit for notes/groups; Delete for any leaf/group."""
        payload = self._selected_payload() if self._enabled else None
        kind = payload.get("kind") if payload else None
        on_script = kind == "script"
        on_note = kind == "note"
        on_group = kind == "group"
        self._btn_edit.setEnabled(on_script or on_note or on_group)
        self._btn_del.setEnabled(on_script or on_note or on_group)
        self._btn_run.setEnabled(on_script and self._on_run is not None)

    def refresh(
        self, *, select: tuple[str, UUID] | None = None
    ) -> None:
        """Rebuild tree; keep current selection or select ``(kind, id)`` if given."""
        restore = select
        if restore is None:
            payload = self._selected_payload()
            if payload and payload.get("kind") is not None and payload.get("id") is not None:
                try:
                    restore = (str(payload["kind"]), UUID(str(payload["id"])))
                except (TypeError, ValueError):
                    restore = None
        self._suppress_expand_persist = True
        try:
            self._refresh_body()
            if restore is not None:
                self._select_item(restore[0], restore[1])
        finally:
            self._suppress_expand_persist = False

    def _select_item(self, kind: str, item_id: UUID) -> bool:
        """Select tree node by kind+id after rebuild; expand parents."""

        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if (
                isinstance(data, dict)
                and str(data.get("kind")) == kind
                and data.get("id") is not None
                and UUID(str(data["id"])) == item_id
            ):
                return item
            for i in range(item.childCount()):
                child = item.child(i)
                if child is not None:
                    found = walk(child)
                    if found is not None:
                        return found
            return None

        found: QTreeWidgetItem | None = None
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top is None:
                continue
            found = walk(top)
            if found is not None:
                break
        if found is None:
            self._sync_selection_actions()
            return False
        parent = found.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self._tree.setCurrentItem(found)
        found.setSelected(True)
        self._tree.scrollToItem(found)
        self._sync_selection_actions()
        return True

    def _refresh_body(self) -> None:
        self._tree.clear()
        if self._host_id is None:
            self._sync_selection_actions()
            return
        host_id = self._host_id
        groups = {
            g.id: g
            for g in self._vault.list_groups(kind="scripts", host_id=host_id)
        }
        group_items: dict[UUID, QTreeWidgetItem] = {}

        def ensure_group(gid: UUID) -> QTreeWidgetItem:
            if gid in group_items:
                return group_items[gid]
            group = groups[gid]
            item = QTreeWidgetItem([group.name])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": "group",
                    "id": group.id,
                    "host_id": str(host_id),
                    "parent_id": str(group.parent_id) if group.parent_id else None,
                },
            )
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            if group.parent_id and group.parent_id in groups:
                ensure_group(group.parent_id).addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            group_items[gid] = item
            item.setExpanded(bool(group.expanded))
            return item

        for gid in sorted(groups, key=lambda i: groups[i].name.lower()):
            ensure_group(gid)

        for script in sorted(
            self._vault.list_scripts(host_id=host_id), key=lambda s: s.name.lower()
        ):
            item = QTreeWidgetItem([script.name])
            item.setIcon(0, script_icon(mcp_enabled=script.mcp_enabled))
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": "script",
                    "id": script.id,
                    "host_id": str(host_id),
                    "group_id": str(script.group_id) if script.group_id else None,
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
                self._tree.addTopLevelItem(item)

        for note in sorted(
            self._vault.list_notes(host_id=host_id), key=lambda n: n.name.lower()
        ):
            item = QTreeWidgetItem([note.name])
            item.setIcon(0, note_icon(mcp_enabled=note.mcp_enabled))
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "kind": "note",
                    "id": note.id,
                    "host_id": str(host_id),
                    "group_id": str(note.group_id) if note.group_id else None,
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
                self._tree.addTopLevelItem(item)

        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top is not None:
                apply_group_folder_icons(top, group_kinds=_SCRIPT_GROUP_KINDS)
        self._sync_selection_actions()

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._persist_expand(item, True)

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        self._persist_expand(item, False)

    def _persist_expand(self, item: QTreeWidgetItem, expanded: bool) -> None:
        from hostskeeper.runtime.tree_debug_log import log, log_exception

        if self._suppress_expand_persist or not self._vault.is_unlocked:
            log(
                "host_scripts_expand_skip",
                reason=(
                    "suppress"
                    if self._suppress_expand_persist
                    else "locked"
                ),
                expanded=expanded,
                text=item.text(0),
            )
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict) or payload.get("kind") != "group":
            return
        try:
            gid = payload["id"]
            group_id = UUID(str(gid)) if not isinstance(gid, UUID) else gid
            log(
                "host_scripts_expand_begin",
                expanded=expanded,
                id=str(group_id),
                text=item.text(0),
            )
            self._vault.set_group_expanded(group_id, expanded)
            log(
                "host_scripts_expand_ok",
                expanded=expanded,
                id=str(group_id),
            )
        except Exception as exc:  # noqa: BLE001
            log_exception(
                "host_scripts_expand_fail",
                exc,
                expanded=expanded,
                text=item.text(0),
            )
            return

    def _selected_payload(self) -> NodePayload | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _target_group_id(self) -> UUID | None:
        payload = self._selected_payload()
        if payload is None:
            return None
        if payload.get("kind") == "group":
            return UUID(payload["id"]) if isinstance(payload["id"], str) else payload["id"]
        gid = payload.get("group_id")
        if gid:
            return UUID(gid) if isinstance(gid, str) else gid
        return None

    def _add_script(self) -> None:
        if self._host_id is None:
            return
        dlg = ScriptDialog(
            self._vault,
            parent=self,
            group_id=self._target_group_id(),
            host_id=self._host_id,
        )
        if dlg.exec() == ScriptDialog.DialogCode.Accepted:
            created = dlg.result_script
            if created is not None:
                self.refresh(select=("script", created.id))
            else:
                self.refresh()

    def _add_note(self) -> None:
        if self._host_id is None:
            return
        dlg = NoteDialog(
            self._vault,
            parent=self,
            group_id=self._target_group_id(),
            host_id=self._host_id,
        )
        if dlg.exec() == NoteDialog.DialogCode.Accepted:
            created = dlg.result_note
            if created is not None:
                self.refresh(select=("note", created.id))
            else:
                self.refresh()

    def _add_group(self) -> None:
        if self._host_id is None:
            return
        name, ok = QInputDialog.getText(self, "New group", "Group name:")
        if not ok or not name.strip():
            return
        parent_id = self._target_group_id()
        try:
            group = self._vault.add_group(
                Group(
                    name=name.strip(),
                    kind="scripts",
                    parent_id=parent_id,
                    host_id=self._host_id,
                )
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.refresh(select=("group", group.id))

    def _edit_selected(self) -> None:
        payload = self._selected_payload()
        if payload is None:
            return
        if payload.get("kind") == "script":
            try:
                script = self._vault.get_script(UUID(str(payload["id"])))
            except (NotFoundError, ValueError):
                return
            script_id = script.id
            dlg = ScriptDialog(self._vault, script=script, parent=self)
            if dlg.exec() == ScriptDialog.DialogCode.Accepted:
                self.refresh(select=("script", script_id))
        elif payload.get("kind") == "note":
            try:
                note = self._vault.get_note(UUID(str(payload["id"])))
            except (NotFoundError, ValueError):
                return
            note_id = note.id
            dlg = NoteDialog(self._vault, note=note, parent=self)
            if dlg.exec() == NoteDialog.DialogCode.Accepted:
                self.refresh(select=("note", note_id))
        elif payload.get("kind") == "group":
            try:
                group = self._vault.get_group(UUID(str(payload["id"])))
            except (NotFoundError, ValueError):
                return
            group_id = group.id
            name, ok = QInputDialog.getText(
                self, "Rename group", "Group name:", text=group.name
            )
            if not ok or not name.strip():
                return
            group.name = name.strip()
            try:
                self._vault.update_group(group)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "HostsKeeper", str(exc))
                return
            self.refresh(select=("group", group_id))

    def _run_selected(self) -> None:
        payload = self._selected_payload()
        if payload is None or payload.get("kind") != "script" or self._on_run is None:
            return
        try:
            script = self._vault.get_script(UUID(str(payload["id"])))
        except (NotFoundError, ValueError):
            return
        self._on_run(script)

    def _delete_selected(self) -> None:
        payload = self._selected_payload()
        if payload is None:
            return
        kind = payload.get("kind")
        if kind == "group":
            try:
                counts = self._vault.group_content_counts(UUID(str(payload["id"])))
            except (NotFoundError, ValueError):
                return
            msg = (
                "Delete this group and all contents?\n\n"
                f"{counts['groups']} subgroup(s), {counts['scripts']} script(s), "
                f"{counts['notes']} note(s)."
            )
        elif kind == "note":
            msg = "Delete this note?"
        else:
            msg = "Delete this script?"
        if (
            QMessageBox.question(self, "Delete", msg)
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            eid = UUID(str(payload["id"]))
            if kind == "script":
                self._vault.delete_script(eid)
            elif kind == "note":
                self._vault.delete_note(eid)
            elif kind == "group":
                self._vault.delete_group(eid)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.refresh()

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self._edit_selected()

    def _context_menu(self, pos) -> None:
        if not self._enabled:
            return
        menu = QMenu(self)
        payload = self._selected_payload()
        on_script = payload is not None and payload.get("kind") == "script"
        new_menu = menu.addMenu("New")
        act_group = new_menu.addAction(folder_icon(filled=False), "Group")
        act_group.triggered.connect(self._add_group)
        act_script = new_menu.addAction(script_icon(), "Script")
        act_script.triggered.connect(self._add_script)
        act_note = new_menu.addAction(note_icon(mcp_enabled=True), "Note")
        act_note.triggered.connect(self._add_note)
        if payload:
            menu.addSeparator()
            menu.addAction("Edit", self._edit_selected)
            if on_script:
                menu.addAction("Copy", self._copy_selected)
            menu.addAction("Delete", self._delete_selected)
            if on_script:
                menu.addAction("Run", self._run_selected)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _copy_selected(self) -> None:
        from hostskeeper.desktop.script_clipboard import copy_script_to_clipboard

        payload = self._selected_payload()
        if payload is None or payload.get("kind") != "script":
            return
        try:
            script = self._vault.get_script(UUID(str(payload["id"])))
        except (NotFoundError, ValueError):
            return
        copy_script_to_clipboard(script)

    def _on_reparent(self, source: QTreeWidgetItem, target: QTreeWidgetItem | None) -> None:
        if self._host_id is None:
            return
        src = source.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(src, dict):
            return
        new_parent: UUID | None = None
        if target is not None:
            dst = target.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(dst, dict):
                if dst.get("kind") == "group":
                    new_parent = UUID(str(dst["id"]))
                elif dst.get("kind") in ("script", "note") and dst.get("group_id"):
                    new_parent = UUID(str(dst["group_id"]))
        try:
            if src.get("kind") == "script":
                script = self._vault.get_script(UUID(str(src["id"])))
                script.group_id = new_parent
                self._vault.update_script(script)
            elif src.get("kind") == "note":
                note = self._vault.get_note(UUID(str(src["id"])))
                note.group_id = new_parent
                self._vault.update_note(note)
            elif src.get("kind") == "group":
                group = self._vault.get_group(UUID(str(src["id"])))
                if new_parent == group.id:
                    return
                group.parent_id = new_parent
                self._vault.update_group(group)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.refresh()

    def _on_foreign_drop(
        self, payload: dict, target: QTreeWidgetItem | None
    ) -> None:
        """Copy template script/group subtree into this host (duplicate)."""
        if self._host_id is None:
            return
        # Only accept global templates (host_id null) from main Scripts tree.
        if payload.get("host_id"):
            return
        kind = str(payload.get("kind") or "")
        try:
            src_id = UUID(str(payload["id"]))
        except (KeyError, ValueError):
            return
        dest_group: UUID | None = None
        if target is not None:
            dst = target.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(dst, dict):
                if dst.get("kind") == "group":
                    dest_group = UUID(str(dst["id"]))
                elif dst.get("group_id"):
                    dest_group = UUID(str(dst["group_id"]))
        try:
            if kind == "script":
                self._copy_script_in(src_id, dest_group)
            elif kind == "group":
                group = self._vault.get_group(src_id)
                if group.kind != "scripts" or group.host_id is not None:
                    return
                self._copy_group_in(src_id, dest_group)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.refresh()

    def _copy_script_in(self, src_id: UUID, dest_group: UUID | None) -> None:
        assert self._host_id is not None
        src = self._vault.get_script(src_id)
        name = self._vault.suggest_script_name(src.name, host_id=self._host_id)
        self._vault.add_script(
            Script(
                name=name,
                body=src.body,
                description=src.description,
                tags=list(src.tags),
                parameters=list(src.parameters),
                group_id=dest_group,
                host_id=self._host_id,
                mcp_enabled=src.mcp_enabled,
            )
        )

    def _copy_group_in(self, src_id: UUID, dest_parent: UUID | None) -> None:
        """Deep-copy a template group subtree + nested scripts into this host."""
        assert self._host_id is not None
        templates = {
            g.id: g
            for g in self._vault.list_groups(kind="scripts", only_templates=True)
        }
        if src_id not in templates:
            return
        id_map: dict[UUID, UUID] = {}

        def copy_subtree(gid: UUID, parent_new: UUID | None) -> None:
            g = templates[gid]
            created = self._vault.add_group(
                Group(
                    name=g.name,
                    kind="scripts",
                    parent_id=parent_new,
                    host_id=self._host_id,
                )
            )
            id_map[gid] = created.id
            for child_id, child in templates.items():
                if child.parent_id == gid:
                    copy_subtree(child_id, created.id)

        copy_subtree(src_id, dest_parent)

        def under_src(group_id: UUID | None) -> bool:
            walk = group_id
            while walk is not None:
                if walk == src_id or walk in id_map:
                    return True
                parent = templates.get(walk)
                walk = parent.parent_id if parent else None
            return False

        for script in self._vault.list_scripts(only_templates=True):
            if not under_src(script.group_id):
                continue
            new_gid = id_map.get(script.group_id) if script.group_id else None
            name = self._vault.suggest_script_name(script.name, host_id=self._host_id)
            self._vault.add_script(
                Script(
                    name=name,
                    body=script.body,
                    description=script.description,
                    tags=list(script.tags),
                    parameters=list(script.parameters),
                    group_id=new_gid,
                    host_id=self._host_id,
                    mcp_enabled=script.mcp_enabled,
                )
            )
