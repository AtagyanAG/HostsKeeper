"""SSH session tab: pyte terminal + session chrome."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from hostskeeper.desktop.terminal_widget import TerminalWidget
from hostskeeper.runtime.connection_debug import ConnectionTrace
from hostskeeper.session.manager import SessionManager, SessionStateError
from hostskeeper.session.models import SessionStatus


def _public_mcp_host(bind_host: str) -> str:
    if bind_host in ("0.0.0.0", "::", ""):
        return "127.0.0.1"
    return bind_host


class _OpenTabWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        sessions: SessionManager,
        host_id: UUID,
        address_id: UUID,
        credential_id: UUID,
        alias: str | None,
        *,
        trace: ConnectionTrace | None = None,
    ) -> None:
        super().__init__()
        self._sessions = sessions
        self._host_id = host_id
        self._address_id = address_id
        self._credential_id = credential_id
        self._alias = alias
        self._trace = trace

    @Slot()
    def run(self) -> None:
        try:
            info = self._sessions.open_tab(
                host_id=self._host_id,
                address_id=self._address_id,
                credential_id=self._credential_id,
                alias=self._alias,
                on_stage=self._trace.stage if self._trace is not None else None,
                on_first_output=(
                    self._trace.first_pty_output
                    if self._trace is not None
                    else None
                ),
            )
            self.finished.emit(info)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _ReconnectWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        sessions: SessionManager,
        session_id: UUID,
        *,
        trace: ConnectionTrace | None = None,
    ) -> None:
        super().__init__()
        self._sessions = sessions
        self._session_id = session_id
        self._trace = trace

    @Slot()
    def run(self) -> None:
        try:
            info = self._sessions.reconnect(
                self._session_id,
                on_stage=self._trace.stage if self._trace is not None else None,
                on_first_output=(
                    self._trace.first_pty_output
                    if self._trace is not None
                    else None
                ),
            )
            self.finished.emit(info)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SessionTab(QWidget):
    closed = Signal(object)  # session_id
    status_changed = Signal()

    def __init__(
        self,
        sessions: SessionManager,
        session_id: UUID,
        *,
        mcp_host: str = "0.0.0.0",
        mcp_port: int = 8765,
        connection_trace: ConnectionTrace | None = None,
        connection_debug_enabled: Callable[[], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._sessions = sessions
        self.session_id = session_id
        self._mcp_host = mcp_host
        self._mcp_port = mcp_port
        self._connection_trace = connection_trace
        self._connection_debug_enabled = (
            connection_debug_enabled or (lambda: False)
        )
        self._cursor = "0"
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._mcp_busy = False
        self._approve_busy = False
        self._chrome_tick = 0

        self._status = QLabel()
        self._status.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._status.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        # Fixed width for longest label so chrome/layout does not jump.
        _status_w = max(
            self._status.fontMetrics().horizontalAdvance(t)
            for t in ("disconnected", "connected", "connecting")
        )
        self._status.setFixedWidth(_status_w + 8)
        self._mcp = QPushButton("MCP")
        self._mcp.setObjectName("sessionMcpToggle")
        self._mcp.setCheckable(True)
        self._mcp.setToolTip("Enable MCP for this tab.")
        self._mcp.toggled.connect(self._on_mcp_toggled)
        self._approve = QPushButton("Approve")
        self._approve.setObjectName("sessionApproveToggle")
        self._approve.setCheckable(True)
        self._approve.setToolTip(
            "Allow MCP session_write / scripts_run. Off = read-only for the model."
        )
        self._approve.toggled.connect(self._on_approve_toggled)
        self._btn_save_log = QPushButton("Save log…")
        self._btn_save_log.setToolTip(
            "Save full terminal scrollback as UTF-8 text.\n"
            "May include secrets that appeared on screen (env dumps, tokens, etc.)."
        )
        self._btn_save_log.clicked.connect(self._save_log)
        self._btn_reconnect = QPushButton("Reconnect")
        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_close = QPushButton("Close")
        self._btn_reconnect.clicked.connect(self.reconnect)
        self._btn_disconnect.clicked.connect(self.disconnect)
        self._btn_close.clicked.connect(self.close_session)

        chrome = QHBoxLayout()
        chrome.addWidget(self._status)
        chrome.addWidget(self._mcp)
        chrome.addWidget(self._approve)
        chrome.addWidget(self._btn_save_log)
        chrome.addStretch(1)
        chrome.addWidget(self._btn_reconnect)
        chrome.addWidget(self._btn_disconnect)
        chrome.addWidget(self._btn_close)

        self._term = TerminalWidget()
        self._term.data_out.connect(self._on_term_data)
        self._term.size_changed.connect(self._on_term_resize)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(chrome)
        layout.addWidget(self._term, stretch=1)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self.refresh_chrome()
        QTimer.singleShot(0, self._term.setFocus)

    def _apply_status_label(self, status: SessionStatus) -> None:
        if status == SessionStatus.LIVE:
            text, color = "connected", "#2ecc71"
        elif status == SessionStatus.CONNECTING:
            text, color = "connecting", "#f39c12"
        else:
            text, color = "disconnected", "#e74c3c"
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color};")

    def refresh_chrome(self) -> None:
        try:
            info = self._sessions.get(self.session_id)
        except Exception:  # noqa: BLE001
            self._apply_status_label(SessionStatus.CLOSED)
            self._term.set_live(False)
            return
        self._apply_status_label(info.status)
        live = info.status == SessionStatus.LIVE
        self._btn_disconnect.setEnabled(live)
        self._btn_reconnect.setEnabled(info.status != SessionStatus.CLOSED)
        self._term.set_live(live)
        if not self._mcp_busy and self._mcp.isChecked() != info.mcp_enabled:
            self._mcp_busy = True
            self._mcp.setChecked(info.mcp_enabled)
            self._mcp_busy = False
        if not self._approve_busy and self._approve.isChecked() != info.approve_enabled:
            self._approve_busy = True
            self._approve.setChecked(info.approve_enabled)
            self._approve_busy = False

    def _on_mcp_toggled(self, checked: bool) -> None:
        if self._mcp_busy:
            return
        try:
            if checked:
                self._sessions.enable_mcp(self.session_id)
            else:
                self._sessions.disable_mcp(self.session_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "MCP", str(exc))
        self.refresh_chrome()
        self.status_changed.emit()

    def _on_approve_toggled(self, checked: bool) -> None:
        if self._approve_busy:
            return
        try:
            self._sessions.set_approve(self.session_id, enabled=checked)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Approve", str(exc))
        self.refresh_chrome()

    def _save_log(self) -> None:
        try:
            info = self._sessions.get(self.session_id)
            alias = info.alias
        except Exception:  # noqa: BLE001
            alias = "session"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = re.sub(r"[^\w.\-]+", "_", alias, flags=re.UNICODE).strip("._") or "session"
        suggested = f"{safe}-{stamp}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save terminal log",
            suggested,
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return
        text = self._term.scrollback_text()
        try:
            Path(path).write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "HostsKeeper", f"Cannot save log:\n{exc}")
            return
        self.status_changed.emit()

    def _on_term_data(self, text: str) -> None:
        try:
            self._sessions.write(self.session_id, text, submit=False)
        except SessionStateError as exc:
            QMessageBox.warning(self, "HostsKeeper", str(exc))

    def _on_term_resize(self, cols: int, rows: int) -> None:
        try:
            self._sessions.resize(self.session_id, cols, rows)
        except Exception:  # noqa: BLE001
            pass
        self._publish_screen_snapshot()

    def _publish_screen_snapshot(self) -> None:
        try:
            self._sessions.update_screen_snapshot(
                self.session_id,
                screen_tail=self._term.screen_text(),
                alt_screen=self._term.alt_screen,
            )
        except Exception:  # noqa: BLE001
            pass

    def _poll(self) -> None:
        try:
            buf = self._sessions.read(self.session_id, cursor=self._cursor)
        except Exception:  # noqa: BLE001
            self._timer.stop()
            return
        if buf.data:
            self._term.feed(buf.data)
            self._publish_screen_snapshot()
        self._cursor = buf.cursor
        self._chrome_tick += 1
        if buf.data or self._chrome_tick >= 15:
            self._chrome_tick = 0
            self.refresh_chrome()
            if not buf.data:
                self._publish_screen_snapshot()

    def _skip_buffer_to_end(self) -> None:
        """Advance read cursor without feeding UI (used after reconnect)."""
        try:
            while True:
                buf = self._sessions.read(
                    self.session_id, cursor=self._cursor, max_chars=1_000_000
                )
                self._cursor = buf.cursor
                if not buf.data or not buf.truncated:
                    break
        except Exception:  # noqa: BLE001
            pass

    def disconnect(self) -> None:
        try:
            self._sessions.disconnect(self.session_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "HostsKeeper", str(exc))
        self.refresh_chrome()
        self.status_changed.emit()

    def reconnect(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._status.setText("connecting…")
        # No QObject parent; keep Python refs so GC cannot kill the worker.
        thread = QThread()
        thread.setObjectName("hostskeeper-reconnect")
        trace = (
            ConnectionTrace("tab_reconnect")
            if self._connection_debug_enabled()
            else None
        )
        self._connection_trace = trace
        worker = _ReconnectWorker(
            self._sessions,
            self.session_id,
            trace=trace,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # QueuedConnection: plain Python lambdas run on the emitter thread and
        # crash when they touch QMessageBox / widgets (see tree log AV in _err).
        worker.finished.connect(
            self._on_reconnect_ok, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(
            self._on_reconnect_fail, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_reconnect_thread_finished)
        self._worker = worker
        self._thread = thread
        thread.start()

    @Slot(object)
    def _on_reconnect_ok(self, _info: object) -> None:
        self._term.reset()
        self._skip_buffer_to_end()
        self._on_term_resize(self._term.cols, self._term.rows)
        if self._connection_trace is not None:
            self._connection_trace.milestone("tab_ready")
        self.refresh_chrome()
        self.status_changed.emit()
        self._term.setFocus()

    @Slot(str)
    def _on_reconnect_fail(self, msg: str) -> None:
        if self._connection_trace is not None:
            self._connection_trace.milestone("connect_failed", "failed")
        QMessageBox.critical(self, "Reconnect failed", msg)
        self.refresh_chrome()

    @Slot()
    def _on_reconnect_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def shutdown_ui(self) -> None:
        self._timer.stop()
        self._stop_worker_thread()

    def _stop_worker_thread(self, timeout_ms: int = 5000) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is None:
            return
        if thread.isRunning():
            thread.quit()
            if not thread.wait(timeout_ms):
                thread.terminate()
                thread.wait(1000)

    def close_session(self) -> None:
        self.shutdown_ui()
        try:
            self._sessions.close(self.session_id)
        except Exception:  # noqa: BLE001
            pass
        self.closed.emit(self.session_id)
