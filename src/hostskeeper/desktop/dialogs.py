"""Property dialogs for vault entities."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from hostskeeper.desktop.ipv4_input import (
    is_valid_ipv4,
    looks_like_ipv4,
    normalize_ipv4_commas,
)
from hostskeeper.desktop.syntax_edit import install_json_editor, install_shell_editor
from hostskeeper.session.knock import (
    KnockStep,
    format_knock_sequence,
    parse_knock_sequence,
)
from hostskeeper.vault import Address, Credential, Host, Note, Script, ScriptParameter
from hostskeeper.vault.errors import NotFoundError
from hostskeeper.vault.models import (
    AUTH_KEY_PAIR,
    AUTH_OPENSSH_CONFIG,
    AUTH_PASSWORD,
    infer_auth_type,
)
from hostskeeper.vault.store import Vault


def _tags_from_text(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def _tags_to_text(tags: list[str]) -> str:
    return ", ".join(tags)


def _format_ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    local = dt.astimezone() if dt.tzinfo is not None else dt
    return local.strftime("%d.%m.%Y %H:%M")


def _timestamps_label(
    created_at: datetime | None, updated_at: datetime | None
) -> QLabel:
    """One-line read-only Created / Modified (dd.mm.yyyy HH:MM)."""
    lab = QLabel(
        f"Created: {_format_ts(created_at)}    Modified: {_format_ts(updated_at)}"
    )
    lab.setStyleSheet("color: #666;")
    return lab


ConnectTarget = Callable[[UUID, UUID, UUID], None]
# host_id, address_id, credential_id, rendered_body, mode, script_id
RunScriptTarget = Callable[[UUID, UUID, UUID, str, str, UUID], None]
ListHostSessions = Callable[[UUID], list[tuple[UUID, str]]]  # (session_id, alias)
HostMcpChanged = Callable[[Host], None]


class HostDialog(QDialog):
    def __init__(
        self,
        vault: Vault,
        host: Host | None = None,
        parent=None,
        *,
        group_id=None,
        on_open_tab: ConnectTarget | None = None,
        on_putty: ConnectTarget | None = None,
        on_winscp: ConnectTarget | None = None,
        on_run_script: RunScriptTarget | None = None,
        list_host_sessions: ListHostSessions | None = None,
        on_host_mcp_changed: HostMcpChanged | None = None,
    ) -> None:
        super().__init__(parent)
        from hostskeeper.desktop.host_scripts_panel import HostScriptsPanel

        self._vault = vault
        self._host = host
        self._group_id = group_id if host is None else None
        self._on_open_tab = on_open_tab
        self._on_putty = on_putty
        self._on_winscp = on_winscp
        self._on_run_script = on_run_script
        self._list_host_sessions = list_host_sessions
        self._on_host_mcp_changed = on_host_mcp_changed
        self.setWindowTitle(host.name if host else "New Host")
        self._name = QLineEdit(host.name if host else "")
        self._description = QLineEdit(host.description or "" if host else "")
        self._tags = QLineEdit(_tags_to_text(host.tags) if host else "")
        self._mcp = QCheckBox("MCP")
        self._mcp.setToolTip(
            "Allow MCP access to this host, its data, and its open SSH tabs."
        )
        self._mcp.setChecked(bool(host.mcp_enabled) if host else False)
        self._mcp.toggled.connect(self._on_host_mcp_toggled)
        self._default_addr = QComboBox()
        self._default_cred = QComboBox()
        self._edit_addr_btn = QPushButton("Edit")
        self._add_addr_btn = QPushButton("Add")
        self._edit_cred_btn = QPushButton("Edit")
        self._add_cred_btn = QPushButton("Add")
        btn_w = max(self._edit_addr_btn.sizeHint().width(), 48)
        for b in (
            self._edit_addr_btn,
            self._add_addr_btn,
            self._edit_cred_btn,
            self._add_cred_btn,
        ):
            b.setFixedWidth(btn_w)
        self._edit_addr_btn.clicked.connect(self._edit_selected_address)
        self._add_addr_btn.clicked.connect(self._create_address)
        self._edit_cred_btn.clicked.connect(self._edit_selected_credential)
        self._add_cred_btn.clicked.connect(self._create_credential)
        if host is not None:
            self._reload_address_combo(selected=host.default_address_id)
            self._reload_credential_combo(selected=host.default_credential_id)
        self._sync_edit_buttons()
        self._default_addr.currentIndexChanged.connect(self._on_address_index_changed)
        self._default_cred.currentIndexChanged.connect(self._on_credential_index_changed)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        form.addRow("Tags", self._tags)
        if host is not None:
            addr_row = QHBoxLayout()
            addr_row.addWidget(self._default_addr, stretch=1)
            addr_row.addWidget(self._edit_addr_btn)
            addr_row.addWidget(self._add_addr_btn)
            cred_row = QHBoxLayout()
            cred_row.addWidget(self._default_cred, stretch=1)
            cred_row.addWidget(self._edit_cred_btn)
            cred_row.addWidget(self._add_cred_btn)
            form.addRow("Address", addr_row)
            form.addRow("Credential", cred_row)

        host_page = QWidget()
        host_layout = QVBoxLayout(host_page)
        host_layout.addLayout(form)

        if host is not None:
            connect_row = QHBoxLayout()
            btn_tab = QPushButton("Tab")
            btn_putty = QPushButton("PuTTY")
            btn_winscp = QPushButton("WinSCP")
            btn_tab.clicked.connect(lambda: self._launch_connect("tab"))
            btn_putty.clicked.connect(lambda: self._launch_connect("putty"))
            btn_winscp.clicked.connect(lambda: self._launch_connect("winscp"))
            connect_row.addStretch(1)
            connect_row.addWidget(btn_tab)
            connect_row.addWidget(btn_putty)
            connect_row.addWidget(btn_winscp)
            connect_row.addStretch(1)
            host_layout.addSpacing(12)
            host_layout.addLayout(connect_row)

        self._scripts_panel = HostScriptsPanel(
            vault,
            host.id if host is not None else None,
            parent=self,
            on_run=self._run_host_script,
            enabled=host is not None,
        )
        # Don't let Scripts tree inflate Host tab default height.
        self._scripts_panel.set_compact_size_hint(host_page.sizeHint())

        notes_page = QWidget()
        notes_layout = QVBoxLayout(notes_page)
        notes_bar = QHBoxLayout()
        notes_bar.addStretch(1)
        self._notes_preview = QCheckBox("Preview")
        self._notes_preview.setToolTip("Toggle Markdown preview / edit")
        self._notes_preview.toggled.connect(self._on_notes_preview_toggled)
        notes_bar.addWidget(self._notes_preview)
        notes_layout.addLayout(notes_bar)

        self._profile = QPlainTextEdit()
        self._profile.setPlaceholderText(
            "Host description (Markdown): OS/version, package managers, python/npm/docker, "
            "last package update, and other useful facts for the AI."
        )
        self._profile.setPlainText(host.profile or "" if host else "")
        self._profile.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._profile.customContextMenuRequested.connect(self._notes_context_menu)

        self._profile_preview = QTextBrowser()
        self._profile_preview.setOpenExternalLinks(True)
        self._profile_preview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._profile_preview.customContextMenuRequested.connect(
            self._notes_preview_context_menu
        )

        self._notes_stack = QStackedWidget()
        self._notes_stack.addWidget(self._profile)  # 0 = edit
        self._notes_stack.addWidget(self._profile_preview)  # 1 = preview
        notes_layout.addWidget(self._notes_stack)
        # Restore per-host Preview (New Host stays off until OK).
        preview_on = bool(host.notes_preview) if host is not None else False
        self._notes_preview.blockSignals(True)
        self._notes_preview.setChecked(preview_on)
        self._notes_preview.blockSignals(False)
        if preview_on:
            self._refresh_notes_preview()
            self._notes_stack.setCurrentIndex(1)

        tabs = QTabWidget()
        tabs.addTab(host_page, "Host")
        tabs.addTab(self._scripts_panel, "Scripts")
        tabs.addTab(notes_page, "Description")
        tabs.currentChanged.connect(self._on_host_tab_changed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        # Timestamps and host MCP permission above tabs.
        self._ts_label = _timestamps_label(
            host.created_at if host is not None else None,
            host.updated_at if host is not None else None,
        )
        metadata = QHBoxLayout()
        metadata.addWidget(self._ts_label)
        metadata.addStretch(1)
        metadata.addWidget(self._mcp)
        layout.addLayout(metadata)
        layout.addWidget(tabs)
        layout.addSpacing(8)
        layout.addWidget(buttons)
        self._result: Host | None = None
        self._tabs = tabs
        self._host_page = host_page
        # Edit Host: same ~1.4× as before, plus one Add button width.
        hint_w = self.sizeHint().width()
        if host is not None:
            base_w = max(hint_w - btn_w, 280)
            self._dialog_width = int(base_w * 1.4) + btn_w
        else:
            self._dialog_width = int(max(hint_w, 280) * 1.4)
        self.setMinimumWidth(self._dialog_width)
        self._fit_host_height()
        from hostskeeper.desktop.vault_ui_watch import register

        register(self)

    def on_vault_externally_changed(self) -> None:
        """Sync host fields / Notes when MCP updates this host (Scripts panel self-refreshes)."""
        if self._host is None or not self.isVisible():
            return
        try:
            host = self._vault.get_host(self._host.id)
        except NotFoundError:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "This host was deleted externally (e.g. by MCP).",
            )
            self.reject()
            return
        self._host = host
        self._name.setText(host.name)
        self._description.setText(host.description or "")
        self._tags.setText(_tags_to_text(host.tags))
        self._mcp.blockSignals(True)
        self._mcp.setChecked(host.mcp_enabled)
        self._mcp.blockSignals(False)
        self._profile.setPlainText(host.profile or "")
        if self._notes_preview.isChecked():
            self._refresh_notes_preview()
        self._ts_label.setText(
            f"Created: {_format_ts(host.created_at)}    "
            f"Modified: {_format_ts(host.updated_at)}"
        )

    def _fit_host_height(self) -> None:
        self._scripts_panel.set_compact_size_hint(self._host_page.sizeHint())
        self.adjustSize()
        self.resize(self._dialog_width, self.sizeHint().height())

    def _notes_context_menu(self, pos) -> None:
        menu = self._profile.createStandardContextMenu()
        menu.exec(self._profile.mapToGlobal(pos))

    def _notes_preview_context_menu(self, pos) -> None:
        menu = self._profile_preview.createStandardContextMenu()
        menu.exec(self._profile_preview.mapToGlobal(pos))

    def _on_notes_preview_toggled(self, preview: bool) -> None:
        if preview:
            self._refresh_notes_preview()
            self._notes_stack.setCurrentIndex(1)
        else:
            self._notes_stack.setCurrentIndex(0)

    def _refresh_notes_preview(self) -> None:
        import markdown

        raw = self._profile.toPlainText()
        if not raw.strip():
            self._profile_preview.setHtml(
                "<p style='color:#888'><i>Empty notes</i></p>"
            )
            return
        body = markdown.markdown(
            raw,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )
        self._profile_preview.setHtml(
            "<html><head><style>"
            "body{font-family:Segoe UI,sans-serif;font-size:13px;}"
            "pre,code{font-family:Consolas,monospace;}"
            "pre{background:#2b2b2b;color:#ddd;padding:8px;border-radius:4px;}"
            "code{background:#2b2b2b;color:#ddd;padding:1px 4px;border-radius:3px;}"
            "table{border-collapse:collapse;} th,td{border:1px solid #666;padding:4px 8px;}"
            "</style></head><body>"
            f"{body}"
            "</body></html>"
        )

    def _on_host_tab_changed(self, index: int) -> None:
        if index == 0:
            self._fit_host_height()
        else:
            self._scripts_panel.set_compact_size_hint(None)
            self.resize(
                self._dialog_width,
                max(self.sizeHint().height(), self.height()),
            )

    def _selected_uuid(self, combo: QComboBox) -> UUID | None:
        data = combo.currentData()
        return data if isinstance(data, UUID) else None

    def _sync_edit_buttons(self) -> None:
        self._edit_addr_btn.setEnabled(self._selected_uuid(self._default_addr) is not None)
        self._edit_cred_btn.setEnabled(self._selected_uuid(self._default_cred) is not None)
        # Add stays enabled whenever host exists (New Host has no combos).
        if self._host is not None:
            self._add_addr_btn.setEnabled(True)
            self._add_cred_btn.setEnabled(True)

    def _reload_address_combo(self, *, selected: UUID | None) -> None:
        assert self._host is not None
        self._default_addr.blockSignals(True)
        self._default_addr.clear()
        addresses = self._vault.list_addresses(host_id=self._host.id)
        chosen = 0
        for a in addresses:
            label = a.label or f"{a.host}:{a.port}"
            self._default_addr.addItem(label, a.id)
            if selected == a.id:
                chosen = self._default_addr.count() - 1
        if addresses:
            self._default_addr.setCurrentIndex(chosen)
            self._default_addr.setEnabled(True)
        else:
            self._default_addr.setEnabled(False)
        self._default_addr.blockSignals(False)
        self._sync_edit_buttons()

    def _reload_credential_combo(self, *, selected: UUID | None) -> None:
        assert self._host is not None
        self._default_cred.blockSignals(True)
        self._default_cred.clear()
        credentials = self._vault.list_credentials(host_id=self._host.id)
        chosen = 0
        for c in credentials:
            label = c.label or c.username
            self._default_cred.addItem(label, c.id)
            if selected == c.id:
                chosen = self._default_cred.count() - 1
        if credentials:
            self._default_cred.setCurrentIndex(chosen)
            self._default_cred.setEnabled(True)
        else:
            self._default_cred.setEnabled(False)
        self._default_cred.blockSignals(False)
        self._sync_edit_buttons()

    def _persist_default_ids(self) -> None:
        """Write current Address/Credential selection as host defaults immediately."""
        if self._host is None:
            return
        try:
            h = self._vault.get_host(self._host.id)
        except NotFoundError:
            return
        h.default_address_id = self._selected_uuid(self._default_addr)
        h.default_credential_id = self._selected_uuid(self._default_cred)
        self._host = self._vault.update_host(h)
        self._result = self._host

    def _on_host_mcp_toggled(self, enabled: bool) -> None:
        if self._host is None:
            return
        try:
            host = self._vault.get_host(self._host.id)
            if host.mcp_enabled == enabled:
                return
            host.mcp_enabled = enabled
            saved = self._vault.update_host(host)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "MCP permissions", str(exc))
            self._mcp.blockSignals(True)
            self._mcp.setChecked(not enabled)
            self._mcp.blockSignals(False)
            return
        self._host = saved
        self._result = saved
        self._ts_label.setText(
            f"Created: {_format_ts(saved.created_at)}    "
            f"Modified: {_format_ts(saved.updated_at)}"
        )
        if self._on_host_mcp_changed is not None:
            try:
                self._on_host_mcp_changed(saved)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(
                    self,
                    "MCP permissions",
                    f"Permission was saved, but open sessions could not be updated:\n{exc}",
                )

    def _on_address_index_changed(self, index: int) -> None:
        if index < 0 or self._selected_uuid(self._default_addr) is None:
            self._sync_edit_buttons()
            return
        self._persist_default_ids()
        self._sync_edit_buttons()

    def _on_credential_index_changed(self, index: int) -> None:
        if index < 0 or self._selected_uuid(self._default_cred) is None:
            self._sync_edit_buttons()
            return
        self._persist_default_ids()
        self._sync_edit_buttons()

    def _create_address(self) -> None:
        if self._host is None:
            return
        dlg = AddressDialog(self._vault, self._host.id, parent=self)
        if dlg.exec() == AddressDialog.DialogCode.Accepted and dlg.result_address is not None:
            self._reload_address_combo(selected=dlg.result_address.id)
            self._persist_default_ids()

    def _create_credential(self) -> None:
        if self._host is None:
            return
        dlg = CredentialDialog(self._vault, self._host.id, parent=self)
        if (
            dlg.exec() == CredentialDialog.DialogCode.Accepted
            and dlg.result_credential is not None
        ):
            self._reload_credential_combo(selected=dlg.result_credential.id)
            self._persist_default_ids()

    def _edit_selected_address(self) -> None:
        addr_id = self._selected_uuid(self._default_addr)
        if addr_id is None or self._host is None:
            return
        try:
            addr = self._vault.get_address(addr_id)
        except NotFoundError:
            return
        dlg = AddressDialog(self._vault, self._host.id, address=addr, parent=self)
        if dlg.exec() == AddressDialog.DialogCode.Accepted:
            if dlg.was_deleted:
                self._host = self._vault.get_host(self._host.id)
                self._reload_address_combo(selected=self._host.default_address_id)
                self._persist_default_ids()
            else:
                self._reload_address_combo(selected=addr_id)

    def _edit_selected_credential(self) -> None:
        cred_id = self._selected_uuid(self._default_cred)
        if cred_id is None or self._host is None:
            return
        try:
            cred = self._vault.get_credential(cred_id)
        except NotFoundError:
            return
        dlg = CredentialDialog(
            self._vault, self._host.id, credential=cred, parent=self
        )
        if dlg.exec() == CredentialDialog.DialogCode.Accepted:
            if dlg.was_deleted:
                self._host = self._vault.get_host(self._host.id)
                self._reload_credential_combo(selected=self._host.default_credential_id)
                self._persist_default_ids()
            else:
                self._reload_credential_combo(selected=cred_id)

    def _persist_host_fields(self) -> Host | None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "HostsKeeper", "Name is required.")
            return None
        if self._host is None:
            saved = self._vault.add_host(
                Host(
                    name=name,
                    description=self._description.text().strip() or None,
                    profile=self._profile.toPlainText().strip() or None,
                    mcp_enabled=self._mcp.isChecked(),
                    notes_preview=self._notes_preview.isChecked(),
                    tags=_tags_from_text(self._tags.text()),
                    group_id=self._group_id,
                )
            )
            if self._on_host_mcp_changed is not None:
                self._on_host_mcp_changed(saved)
            return saved
        h = self._host
        h.name = name
        h.description = self._description.text().strip() or None
        h.profile = self._profile.toPlainText().strip() or None
        h.mcp_enabled = self._mcp.isChecked()
        h.notes_preview = self._notes_preview.isChecked()
        h.tags = _tags_from_text(self._tags.text())
        h.default_address_id = self._selected_uuid(self._default_addr)
        h.default_credential_id = self._selected_uuid(self._default_cred)
        saved = self._vault.update_host(h)
        if self._on_host_mcp_changed is not None:
            self._on_host_mcp_changed(saved)
        return saved

    def _launch_connect(self, kind: str) -> None:
        if self._host is None:
            return
        addr_id = self._selected_uuid(self._default_addr)
        cred_id = self._selected_uuid(self._default_cred)
        if addr_id is None or cred_id is None:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "Set Address and Credential before connecting.",
            )
            return
        saved = self._persist_host_fields()
        if saved is None:
            return
        self._result = saved
        self._host = saved
        cb = {
            "tab": self._on_open_tab,
            "putty": self._on_putty,
            "winscp": self._on_winscp,
        }.get(kind)
        if cb is not None:
            cb(saved.id, addr_id, cred_id)

    def _run_host_script(self, script: Script) -> None:
        if self._host is None or self._on_run_script is None:
            return
        addr_id = self._selected_uuid(self._default_addr)
        cred_id = self._selected_uuid(self._default_cred)
        if addr_id is None or cred_id is None:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "Set Address and Credential before running a script.",
            )
            return
        from hostskeeper.mcp.errors import McpToolError
        from hostskeeper.mcp.scripts_render import render_script

        sessions: list[tuple[UUID, str]] = []
        if self._list_host_sessions is not None:
            sessions = self._list_host_sessions(self._host.id)
        dlg = RunScriptTargetDialog(sessions, script=script, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.mode is None:
            return
        try:
            rendered = render_script(
                script, {}, use_user_values=dlg.use_user_values
            )
        except McpToolError as exc:
            QMessageBox.warning(self, "HostsKeeper", str(exc))
            return
        saved = self._persist_host_fields()
        if saved is None:
            return
        self._result = saved
        self._host = saved
        self._on_run_script(
            saved.id, addr_id, cred_id, rendered, dlg.mode, script.id
        )

    def _save(self) -> None:
        saved = self._persist_host_fields()
        if saved is None:
            return
        self._result = saved
        self.accept()

    @property
    def result_host(self) -> Host | None:
        return self._result


class PickHostDialog(QDialog):
    """Choose a host to run a template script against."""

    def __init__(self, hosts: list[Host], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run script — choose host")
        self.selected_host: Host | None = None
        self._list = QListWidget()
        for host in hosts:
            item = QListWidgetItem(host.name)
            item.setData(Qt.ItemDataRole.UserRole, host)
            self._list.addItem(item)
        if hosts:
            self._list.setCurrentRow(0)
        self._list.itemDoubleClicked.connect(self._accept)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Host:"))
        layout.addWidget(self._list)
        layout.addWidget(buttons)
        self.resize(360, 320)

    def _accept(self) -> None:
        item = self._list.currentItem()
        if item is None:
            QMessageBox.warning(self, "HostsKeeper", "Select a host.")
            return
        host = item.data(Qt.ItemDataRole.UserRole)
        if host is None:
            return
        self.selected_host = host
        self.accept()


class RunScriptTargetDialog(QDialog):
    """Choose where to run a host script: open tab / new Tab / PuTTY."""

    def __init__(
        self,
        sessions: list[tuple[UUID, str]],
        parent=None,
        *,
        script: Script | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Run script")
        self.mode: str | None = None
        self.use_user_values = False
        self._script = script
        self._sessions = sessions

        self._has_params = bool(script.parameters) if script is not None else False

        self._use_user = QCheckBox("Use user values")
        self._use_user.setToolTip(
            "Substitute {{param}} from parameter user_value. "
            "When the script has parameters, launch only via PuTTY "
            "(not visible to MCP tabs)."
        )
        self._use_user.toggled.connect(self._apply_user_mode)
        # No parameters → nothing to substitute; keep Tab / Open tab available.
        self._use_user.setEnabled(self._has_params)
        if not self._has_params:
            self._use_user.setToolTip(
                "This script has no parameters; user values do not apply."
            )

        self._hint = QLabel(
            "Script contains user parameters. Launch only in PuTTY."
        )
        self._hint.setWordWrap(True)
        self._hint.setVisible(False)

        self._radio_new = QRadioButton("New Tab")
        self._radio_putty = QRadioButton("PuTTY")
        self._radio_existing = QRadioButton("Open tab")
        # Different parents (targets wrap vs dialog) — need an explicit group.
        self._target_group = QButtonGroup(self)
        self._target_group.setExclusive(True)
        self._target_group.addButton(self._radio_existing)
        self._target_group.addButton(self._radio_new)
        self._target_group.addButton(self._radio_putty)
        self._list = QListWidget()
        for sid, alias in sessions:
            item = QListWidgetItem(alias)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self._list.addItem(item)
        if sessions:
            self._radio_existing.setChecked(True)
            self._list.setCurrentRow(0)
        else:
            self._radio_existing.setEnabled(False)
            self._list.setEnabled(False)
            self._radio_new.setChecked(True)

        self._targets = QWidget()
        targets_layout = QVBoxLayout(self._targets)
        targets_layout.setContentsMargins(0, 0, 0, 0)
        targets_layout.addWidget(self._radio_existing)
        targets_layout.addWidget(self._list)
        targets_layout.addWidget(self._radio_new)

        layout = QVBoxLayout(self)
        layout.addWidget(self._use_user)
        layout.addWidget(self._hint)
        layout.addWidget(self._targets)
        layout.addWidget(self._radio_putty)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setToolTip(
            "Copy script to clipboard with user_value substitutions."
        )
        self._copy_btn.setVisible(False)
        self._copy_btn.clicked.connect(self._copy_rendered)
        row = QHBoxLayout()
        row.addWidget(self._copy_btn)
        row.addStretch(1)
        row.addWidget(buttons)
        layout.addLayout(row)

    def _putty_only_user_mode(self) -> bool:
        return self._use_user.isChecked() and self._has_params

    def _apply_user_mode(self, enabled: bool) -> None:
        putty_only = enabled and self._has_params
        self.use_user_values = putty_only
        self._hint.setVisible(putty_only)
        self._targets.setVisible(not putty_only)
        self._copy_btn.setVisible(putty_only)
        if putty_only:
            self._radio_putty.setChecked(True)
        elif self._sessions:
            self._radio_existing.setChecked(True)
        else:
            self._radio_new.setChecked(True)

    def _copy_rendered(self) -> None:
        if self._script is None:
            return
        from hostskeeper.mcp.errors import McpToolError
        from hostskeeper.mcp.scripts_render import render_script

        try:
            text = render_script(self._script, {}, use_user_values=True)
        except McpToolError as exc:
            QMessageBox.warning(self, "HostsKeeper", str(exc))
            return
        QGuiApplication.clipboard().setText(text)

    def _accept(self) -> None:
        if self._putty_only_user_mode():
            if self._script is not None:
                from hostskeeper.mcp.errors import McpToolError
                from hostskeeper.mcp.scripts_render import render_script

                try:
                    render_script(self._script, {}, use_user_values=True)
                except McpToolError as exc:
                    QMessageBox.warning(self, "HostsKeeper", str(exc))
                    return
            self.use_user_values = True
            self.mode = "putty"
            self.accept()
            return
        self.use_user_values = False
        if self._radio_new.isChecked():
            self.mode = "new_tab"
        elif self._radio_putty.isChecked():
            self.mode = "putty"
        elif self._radio_existing.isChecked():
            item = self._list.currentItem()
            if item is None:
                QMessageBox.warning(self, "HostsKeeper", "Select an open tab.")
                return
            sid = item.data(Qt.ItemDataRole.UserRole)
            self.mode = str(sid)
        else:
            return
        self.accept()


class AddressDialog(QDialog):
    def __init__(
        self,
        vault: Vault,
        host_id: UUID,
        address: Address | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._vault = vault
        self._host_id = host_id
        self._address = address
        self.setWindowTitle("Edit Address" if address else "New Address")
        self._label = QLineEdit(address.label or "" if address else "")
        self._host = QLineEdit(address.host if address else "")
        self._host.editingFinished.connect(self._on_host_editing_finished)
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(address.port if address else 22)
        self._description = QLineEdit(address.description or "" if address else "")
        self._tags = QLineEdit(_tags_to_text(address.tags) if address else "")
        self._knock_enabled = QCheckBox("Port knocking before connect")
        self._knock_enabled.setChecked(bool(address.knock_enabled) if address else False)
        initial_steps = (
            [KnockStep.from_dict(s) for s in address.knock_steps] if address else []
        )
        self._knock_ports = QLineEdit(format_knock_sequence(initial_steps))
        self._knock_ports.setPlaceholderText("4011,5022:udp,6033")
        self._knock_delay = QSpinBox()
        self._knock_delay.setRange(0, 5000)
        self._knock_delay.setSuffix(" ms")
        self._knock_delay.setValue(
            int(address.knock_delay_ms) if address else 200
        )
        self._knock_pause = QSpinBox()
        self._knock_pause.setRange(0, 10000)
        self._knock_pause.setSuffix(" ms")
        self._knock_pause.setValue(
            int(address.knock_pause_ms) if address else 300
        )
        self._knock_enabled.toggled.connect(self._apply_knock_ui)
        self._apply_knock_ui(self._knock_enabled.isChecked())

        form = QFormLayout()
        form.addRow("Label", self._label)
        form.addRow("Host / IP", self._host)
        form.addRow("Port", self._port)
        form.addRow("Description", self._description)
        form.addRow("Tags", self._tags)
        form.addRow("", self._knock_enabled)
        form.addRow("Knock sequence", self._knock_ports)
        form.addRow("Delay between knocks", self._knock_delay)
        form.addRow("Pause before SSH", self._knock_pause)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        if address is not None:
            delete_btn = buttons.addButton(
                "Delete", QDialogButtonBox.ButtonRole.DestructiveRole
            )
            delete_btn.clicked.connect(self._delete)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._result: Address | None = None
        self._deleted = False

    def _on_host_editing_finished(self) -> None:
        raw = self._host.text()
        normalized = normalize_ipv4_commas(raw)
        if normalized != raw:
            self._host.setText(normalized)
            raw = normalized
        text = raw.strip()
        if looks_like_ipv4(text) and not is_valid_ipv4(text):
            pos = self._host.mapToGlobal(QPoint(0, self._host.height()))
            QToolTip.showText(
                pos,
                "Invalid IPv4 address (0–255 per octet).",
                self._host,
                self._host.rect(),
                4000,
            )
        else:
            QToolTip.hideText()

    def _apply_knock_ui(self, enabled: bool) -> None:
        self._knock_ports.setEnabled(enabled)
        self._knock_delay.setEnabled(enabled)
        self._knock_pause.setEnabled(enabled)

    def _read_knock_fields(
        self,
    ) -> tuple[bool, list[dict[str, object]], int, int] | None:
        enabled = self._knock_enabled.isChecked()
        if not enabled:
            return False, [], int(self._knock_delay.value()), int(self._knock_pause.value())
        try:
            steps = parse_knock_sequence(self._knock_ports.text())
        except ValueError as exc:
            QMessageBox.warning(self, "HostsKeeper", str(exc))
            return None
        if not steps:
            QMessageBox.warning(
                self,
                "HostsKeeper",
                "Knock sequence is required when port knocking is enabled "
                "(example: 4011,5022:udp,6033).",
            )
            return None
        return (
            True,
            [s.to_dict() for s in steps],
            int(self._knock_delay.value()),
            int(self._knock_pause.value()),
        )

    def _delete(self) -> None:
        if self._address is None:
            return
        if (
            QMessageBox.question(
                self,
                "Delete Address",
                "Delete this address?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._vault.delete_address(self._address.id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self._deleted = True
        self._result = None
        self.accept()

    def _save(self) -> None:
        self._on_host_editing_finished()
        host = self._host.text().strip()
        if not host:
            QMessageBox.warning(self, "HostsKeeper", "Host / IP is required.")
            return
        knock = self._read_knock_fields()
        if knock is None:
            return
        knock_enabled, knock_steps, knock_delay_ms, knock_pause_ms = knock
        if self._address is None:
            self._result = self._vault.add_address(
                Address(
                    host_id=self._host_id,
                    host=host,
                    port=int(self._port.value()),
                    label=self._label.text().strip() or None,
                    description=self._description.text().strip() or None,
                    tags=_tags_from_text(self._tags.text()),
                    knock_enabled=knock_enabled,
                    knock_steps=knock_steps,
                    knock_delay_ms=knock_delay_ms,
                    knock_pause_ms=knock_pause_ms,
                )
            )
        else:
            a = self._address
            a.host = host
            a.port = int(self._port.value())
            a.label = self._label.text().strip() or None
            a.description = self._description.text().strip() or None
            a.tags = _tags_from_text(self._tags.text())
            a.knock_enabled = knock_enabled
            a.knock_steps = knock_steps
            a.knock_delay_ms = knock_delay_ms
            a.knock_pause_ms = knock_pause_ms
            self._result = self._vault.update_address(a)
        self.accept()

    @property
    def result_address(self) -> Address | None:
        return self._result

    @property
    def was_deleted(self) -> bool:
        return self._deleted


class CredentialDialog(QDialog):
    def __init__(
        self,
        vault: Vault,
        host_id: UUID,
        credential: Credential | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._vault = vault
        self._host_id = host_id
        self._credential = credential
        self.setWindowTitle("Edit Credential" if credential else "New Credential")
        self._label = QLineEdit(credential.label or "" if credential else "")
        self._username = QLineEdit(credential.username if credential else "")
        self._auth_type = QComboBox()
        self._auth_type.addItem("Password", AUTH_PASSWORD)
        self._auth_type.addItem("Key pair", AUTH_KEY_PAIR)  # OpenSSH / PEM
        self._auth_type.addItem("OpenSSH config", AUTH_OPENSSH_CONFIG)
        initial_type = (
            infer_auth_type(
                auth_type=credential.auth_type if credential else None,
                password=credential.password if credential else None,
                private_key=credential.private_key if credential else None,
            )
            if credential is not None
            else AUTH_PASSWORD
        )
        idx = self._auth_type.findData(initial_type)
        self._auth_type.setCurrentIndex(idx if idx >= 0 else 0)
        self._auth_type.currentIndexChanged.connect(self._apply_auth_type_ui)

        self._password = QLineEdit(credential.password or "" if credential else "")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._passphrase = QLineEdit(credential.passphrase or "" if credential else "")
        self._passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self._private_key = QPlainTextEdit(credential.private_key or "" if credential else "")
        self._private_key.setPlaceholderText("Paste OpenSSH / PEM private key")
        self._private_key.setFixedHeight(120)
        self._browse_key_btn = QPushButton("Browse…")
        self._browse_key_btn.clicked.connect(self._browse_private_key)
        key_col = QVBoxLayout()
        key_col.setContentsMargins(0, 0, 0, 0)
        key_col.setSpacing(4)
        key_col.addWidget(self._private_key)
        browse_row = QHBoxLayout()
        browse_row.addStretch(1)
        browse_row.addWidget(self._browse_key_btn)
        key_col.addLayout(browse_row)
        self._private_key_wrap = QWidget()
        self._private_key_wrap.setLayout(key_col)
        self._openssh_hint = QLabel(
            "Uses SSH agent and ~/.ssh/config for connect. "
            "Previously saved password/key stay in the vault for other types."
        )
        self._openssh_hint.setWordWrap(True)
        self._description = QLineEdit(credential.description or "" if credential else "")
        self._tags = QLineEdit(_tags_to_text(credential.tags) if credential else "")
        self._show = QCheckBox("Show secrets in this dialog")
        self._show.toggled.connect(self._toggle_echo)

        self._form = QFormLayout()
        self._form.addRow("Label", self._label)
        self._form.addRow("Username", self._username)
        self._form.addRow("Type", self._auth_type)
        self._form.addRow("Password", self._password)
        self._form.addRow("Key passphrase", self._passphrase)
        self._form.addRow("Private key", self._private_key_wrap)
        self._form.addRow("", self._openssh_hint)
        self._form.addRow("Description", self._description)
        self._form.addRow("Tags", self._tags)
        self._form.addRow("", self._show)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        if credential is not None:
            delete_btn = buttons.addButton(
                "Delete", QDialogButtonBox.ButtonRole.DestructiveRole
            )
            delete_btn.clicked.connect(self._delete)
        layout = QVBoxLayout(self)
        layout.addLayout(self._form)
        layout.addWidget(buttons)
        self._result: Credential | None = None
        self._deleted = False
        # Same width rule as HostDialog (~1.4× content); height follows auth Type.
        base_w = max(self.sizeHint().width(), 280)
        self._dialog_width = int(base_w * 1.4)
        self.setMinimumWidth(self._dialog_width)
        self._apply_auth_type_ui()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        # After first paint, sizeHint reflects hidden Type rows correctly.
        QTimer.singleShot(0, self._fit_to_content)

    def _fit_to_content(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self.resize(self._dialog_width, self.sizeHint().height())

    def _set_row_visible(self, field, visible: bool) -> None:
        field.setVisible(visible)
        label = self._form.labelForField(field)
        if label is not None:
            label.setVisible(visible)

    def _apply_auth_type_ui(self) -> None:
        kind = self._auth_type.currentData()
        self._set_row_visible(self._password, kind == AUTH_PASSWORD)
        self._set_row_visible(self._passphrase, kind == AUTH_KEY_PAIR)
        self._set_row_visible(self._private_key_wrap, kind == AUTH_KEY_PAIR)
        self._set_row_visible(self._openssh_hint, kind == AUTH_OPENSSH_CONFIG)
        self._show.setVisible(kind in (AUTH_PASSWORD, AUTH_KEY_PAIR))
        show_label = self._form.labelForField(self._show)
        if show_label is not None:
            show_label.setVisible(kind in (AUTH_PASSWORD, AUTH_KEY_PAIR))
        self._fit_to_content()

    def _browse_private_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select private key",
            "",
            "Private key (*.pem *.key id_* *);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self._private_key.setPlainText(text)

    def _delete(self) -> None:
        if self._credential is None:
            return
        if (
            QMessageBox.question(
                self,
                "Delete Credential",
                "Delete this credential?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self._vault.delete_credential(self._credential.id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self._deleted = True
        self._result = None
        self.accept()

    def _toggle_echo(self, checked: bool) -> None:
        mode = (
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self._password.setEchoMode(mode)
        self._passphrase.setEchoMode(mode)

    def _save(self) -> None:
        username = self._username.text().strip()
        if not username:
            QMessageBox.warning(self, "HostsKeeper", "Username is required.")
            return
        auth_type = self._auth_type.currentData()
        # Keep values for every auth type on the same Credential so switching
        # Type does not wipe the other method's secrets (fields stay filled
        # while hidden; inactive types are still written through).
        password = self._password.text() or None
        private_key = self._private_key.toPlainText().strip() or None
        passphrase = self._passphrase.text() or None
        if auth_type == AUTH_PASSWORD and not password:
            QMessageBox.warning(self, "HostsKeeper", "Password is required.")
            return
        if auth_type == AUTH_KEY_PAIR and not private_key:
            QMessageBox.warning(self, "HostsKeeper", "Private key is required.")
            return
        try:
            if self._credential is None:
                self._result = self._vault.add_credential(
                    Credential(
                        host_id=self._host_id,
                        username=username,
                        auth_type=auth_type,
                        password=password,
                        private_key=private_key,
                        passphrase=passphrase,
                        label=self._label.text().strip() or None,
                        description=self._description.text().strip() or None,
                        tags=_tags_from_text(self._tags.text()),
                    )
                )
            else:
                c = self._credential
                c.username = username
                c.auth_type = auth_type
                c.password = password
                c.private_key = private_key
                c.passphrase = passphrase
                c.label = self._label.text().strip() or None
                c.description = self._description.text().strip() or None
                c.tags = _tags_from_text(self._tags.text())
                self._result = self._vault.update_credential(c)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.accept()

    @property
    def result_credential(self) -> Credential | None:
        return self._result

    @property
    def was_deleted(self) -> bool:
        return self._deleted


class RevealSecretDialog(QDialog):
    def __init__(self, credential: Credential, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reveal secret")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Username: {credential.username}"))
        pwd = QPlainTextEdit(credential.password or "")
        pwd.setReadOnly(True)
        pwd.setFixedHeight(40)
        key = QPlainTextEdit(credential.private_key or "")
        key.setReadOnly(True)
        key.setFixedHeight(120)
        phr = QLineEdit(credential.passphrase or "")
        phr.setReadOnly(True)
        form = QFormLayout()
        form.addRow("Password", pwd)
        form.addRow("Passphrase", phr)
        form.addRow("Private key", key)
        layout.addLayout(form)
        note = QLabel("Shown only in this dialog. Not written to status bar or logs.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)


class ScriptDialog(QDialog):
    def __init__(
        self,
        vault: Vault,
        script: Script | None = None,
        parent=None,
        *,
        group_id=None,
        host_id: UUID | None = None,
    ) -> None:
        super().__init__(parent)
        self._vault = vault
        self._script = script
        self._group_id = group_id if script is None else None
        self._host_id = (
            script.host_id if script is not None else host_id
        )
        self.setWindowTitle("Edit Script" if script else "New Script")
        self._mcp = QCheckBox("MCP")
        self._mcp.setToolTip(
            "When checked, this script is available via MCP. "
            "Host scripts also require MCP access to their host."
        )
        self._mcp.setChecked(bool(script.mcp_enabled) if script else False)
        self._name = QLineEdit(script.name if script else "")
        self._description = QLineEdit(script.description or "" if script else "")
        self._tags = QLineEdit(_tags_to_text(script.tags) if script else "")
        self._body = QPlainTextEdit(script.body if script else "")
        self._body.setPlaceholderText("echo hello-{{name}}")
        self._params = QPlainTextEdit(
            json.dumps(
                [p.to_dict() for p in (script.parameters if script else [])],
                ensure_ascii=False,
                indent=2,
            )
        )
        self._params.setPlaceholderText(
            '[{"name":"tag","required":true,"default":"",'
            '"description":null,"user_value":""}]'
        )
        # Keep refs so highlighters/matchers are not garbage-collected.
        self._body_syntax = install_shell_editor(self._body)
        self._params_syntax = install_json_editor(self._params)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Description", self._description)
        form.addRow("Tags", self._tags)

        body_wrap = QWidget()
        body_col = QVBoxLayout(body_wrap)
        body_col.setContentsMargins(0, 0, 0, 0)
        body_col.addWidget(QLabel("Body"))
        body_col.addWidget(self._body)

        params_wrap = QWidget()
        params_col = QVBoxLayout(params_wrap)
        params_col.setContentsMargins(0, 0, 0, 0)
        params_col.addWidget(QLabel("Parameters JSON"))
        params_col.addWidget(self._params)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(body_wrap)
        splitter.addWidget(params_wrap)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        self._ts_label = _timestamps_label(
            script.created_at if script is not None else None,
            script.updated_at if script is not None else None,
        )
        metadata_row = QHBoxLayout()
        metadata_row.addWidget(self._ts_label)
        metadata_row.addStretch(1)
        metadata_row.addWidget(self._mcp)
        layout.addLayout(metadata_row)
        layout.addLayout(form)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(buttons)
        self.resize(520, 560)
        self._result: Script | None = None
        from hostskeeper.desktop.vault_ui_watch import register

        register(self)

    @property
    def result_script(self) -> Script | None:
        return self._result

    def on_vault_externally_changed(self) -> None:
        """Reload or close if MCP changed/deleted this script while dialog is open."""
        if self._script is None or not self.isVisible():
            return
        try:
            script = self._vault.get_script(self._script.id)
        except NotFoundError:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "This script was deleted externally (e.g. by MCP).",
            )
            self.reject()
            return
        self._script = script
        self._name.setText(script.name)
        self._mcp.setChecked(bool(script.mcp_enabled))
        self._description.setText(script.description or "")
        self._tags.setText(_tags_to_text(script.tags))
        self._body.setPlainText(script.body)
        self._params.setPlainText(
            json.dumps(
                [p.to_dict() for p in script.parameters],
                ensure_ascii=False,
                indent=2,
            )
        )
        self._ts_label.setText(
            f"Created: {_format_ts(script.created_at)}    "
            f"Modified: {_format_ts(script.updated_at)}"
        )

    def _save(self) -> None:
        name = self._name.text().strip()
        body = self._body.toPlainText()
        if not name or not body.strip():
            QMessageBox.warning(self, "HostsKeeper", "Name and body are required.")
            return
        try:
            raw = self._params.toPlainText().strip() or "[]"
            raw_list = json.loads(raw)
            if not isinstance(raw_list, list):
                raise TypeError("parameters must be a JSON array")
            previous = {
                p.name: p for p in (self._script.parameters if self._script else [])
            }
            params: list[ScriptParameter] = []
            for item in raw_list:
                if not isinstance(item, dict):
                    raise TypeError("each parameter must be an object")
                payload = dict(item)
                # Omitting user_value on edit keeps the previous secret; on create
                # from_dict seeds it from default.
                pname = payload.get("name")
                if "user_value" not in payload and pname in previous:
                    payload["user_value"] = previous[pname].user_value
                params.append(ScriptParameter.from_dict(payload))
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            QMessageBox.warning(self, "HostsKeeper", f"Invalid parameters JSON:\n{exc}")
            return
        try:
            if self._script is None:
                self._result = self._vault.add_script(
                    Script(
                        name=name,
                        body=body,
                        description=self._description.text().strip() or None,
                        tags=_tags_from_text(self._tags.text()),
                        parameters=params,
                        group_id=self._group_id,
                        host_id=self._host_id,
                        mcp_enabled=self._mcp.isChecked(),
                    )
                )
            else:
                s = self._script
                s.name = name
                s.body = body
                s.description = self._description.text().strip() or None
                s.tags = _tags_from_text(self._tags.text())
                s.parameters = params
                s.mcp_enabled = self._mcp.isChecked()
                self._result = self._vault.update_script(s)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.accept()


class NoteDialog(QDialog):
    """Markdown Note editor with Preview and MCP checkbox."""

    def __init__(
        self,
        vault: Vault,
        note: Note | None = None,
        parent=None,
        *,
        group_id: UUID | None = None,
        host_id: UUID | None = None,
    ) -> None:
        super().__init__(parent)
        self._vault = vault
        self._note = note
        self._group_id = note.group_id if note is not None else group_id
        self._host_id = note.host_id if note is not None else host_id
        self.setWindowTitle("Edit Note" if note is not None else "New Note")

        self._name = QLineEdit(note.name if note is not None else "")
        self._name.setPlaceholderText("Name")
        self._mcp = QCheckBox("MCP")
        self._mcp.setToolTip(
            "When checked, this note is available via MCP notes_* tools (no Approve)."
        )
        self._mcp.setChecked(bool(note.mcp_enabled) if note is not None else False)

        self._preview = QCheckBox("Preview")
        self._preview.setToolTip("Toggle Markdown preview / edit")
        self._preview.toggled.connect(self._on_preview_toggled)

        top = QHBoxLayout()
        top.addWidget(QLabel("Name"))
        top.addWidget(self._name, stretch=1)
        top.addWidget(self._mcp)
        top.addWidget(self._preview)

        self._body = QPlainTextEdit()
        self._body.setPlaceholderText("Markdown note…")
        self._body.setPlainText(note.body if note is not None else "")
        self._body_preview = QTextBrowser()
        self._body_preview.setOpenExternalLinks(True)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._body)
        self._stack.addWidget(self._body_preview)
        preview_on = bool(note.preview) if note is not None else False
        self._preview.blockSignals(True)
        self._preview.setChecked(preview_on)
        self._preview.blockSignals(False)
        if preview_on:
            self._refresh_preview()
            self._stack.setCurrentIndex(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        self._ts_label = _timestamps_label(
            note.created_at if note is not None else None,
            note.updated_at if note is not None else None,
        )
        layout.addWidget(self._ts_label)
        layout.addLayout(top)
        layout.addWidget(self._stack, stretch=1)
        layout.addWidget(buttons)
        self.setMinimumSize(480, 360)
        self._result: Note | None = None
        from hostskeeper.desktop.vault_ui_watch import register

        register(self)

    def on_vault_externally_changed(self) -> None:
        """Reload or close if MCP changed/deleted this note while dialog is open."""
        if self._note is None or not self.isVisible():
            return
        try:
            note = self._vault.get_note(self._note.id)
        except NotFoundError:
            QMessageBox.information(
                self,
                "HostsKeeper",
                "This note was deleted externally (e.g. by MCP).",
            )
            self.reject()
            return
        self._note = note
        self._name.setText(note.name)
        self._mcp.setChecked(bool(note.mcp_enabled))
        self._body.setPlainText(note.body)
        self._ts_label.setText(
            f"Created: {_format_ts(note.created_at)}    "
            f"Modified: {_format_ts(note.updated_at)}"
        )
        if self._preview.isChecked():
            self._refresh_preview()
        self.setWindowTitle("Edit Note")

    def _on_preview_toggled(self, preview: bool) -> None:
        if preview:
            self._refresh_preview()
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)

    def _refresh_preview(self) -> None:
        import markdown

        raw = self._body.toPlainText()
        if not raw.strip():
            self._body_preview.setHtml(
                "<p style='color:#888'><i>Empty note</i></p>"
            )
            return
        html = markdown.markdown(
            raw,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )
        self._body_preview.setHtml(html)

    def _save(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Note", "Name is required.")
            return
        body = self._body.toPlainText()
        mcp_enabled = self._mcp.isChecked()
        try:
            preview = self._preview.isChecked()
            if self._note is None:
                self._result = self._vault.add_note(
                    Note(
                        name=name,
                        body=body,
                        group_id=self._group_id,
                        host_id=self._host_id,
                        mcp_enabled=mcp_enabled,
                        preview=preview,
                    )
                )
            else:
                n = self._note
                n.name = name
                n.body = body
                n.mcp_enabled = mcp_enabled
                n.preview = preview
                self._result = self._vault.update_note(n)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "HostsKeeper", str(exc))
            return
        self.accept()
