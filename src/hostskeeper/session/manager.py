"""Session manager: open tab SSH sessions backed by vault entities."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from hostskeeper.session.buffer import BufferRead, OutputBuffer
from hostskeeper.session.diagnostics import (
    ConnectionStageCallback,
    FirstOutputCallback,
    measure_stage,
)
from hostskeeper.session.models import (
    SessionInfo,
    SessionStatus,
    SessionTarget,
    new_session_id,
)
from hostskeeper.session.knock import KnockStep, perform_knock
from hostskeeper.session.script_run_manager import (
    ScriptRunCapacityError,
    ScriptRunManager,
    ScriptRunNotFoundError,
    ScriptRunSnapshot,
)
from hostskeeper.session.script_runs import ScriptRunInfo, ScriptRunOrigin
from hostskeeper.session.ssh import SshConnectParams, SshShell
from hostskeeper.vault.models import (
    AUTH_KEY_PAIR,
    AUTH_OPENSSH_CONFIG,
    AUTH_PASSWORD,
)
from hostskeeper.vault.errors import NotFoundError
from hostskeeper.vault.script_render import render_script
from hostskeeper.vault.store import Vault


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionError(Exception):
    """Session manager error."""


class SessionNotFoundError(SessionError):
    pass


class SessionStateError(SessionError):
    pass


class ScriptRunStartError(SessionError):
    """Safe, stable reason a saved MCP script run could not be started."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class McpClientBusyError(SessionError):
    """HTTP MCP client slot for this token is already taken."""


class McpUnauthorizedError(SessionError):
    """Invalid or missing MCP token."""


@dataclass
class _SessionState:
    info: SessionInfo
    buffer: OutputBuffer = field(default_factory=OutputBuffer)
    shell: SshShell | None = None
    mcp_token: str | None = None
    mcp_client_id: str | None = None
    # Published by UI TerminalWidget (plain screen + alt-screen flag).
    screen_tail: str = ""
    alt_screen: bool = False


class SessionManager:
    def __init__(
        self,
        vault: Vault,
        *,
        connect_timeout_sec: float = 3.0,
    ) -> None:
        self._vault = vault
        self._lock = threading.RLock()
        self._sessions: dict[UUID, _SessionState] = {}
        self._alias_counts: dict[str, int] = {}
        self._connect_timeout_sec = max(1.0, float(connect_timeout_sec))
        self._script_runs = ScriptRunManager()

    def set_connect_timeout_sec(self, timeout_sec: float) -> None:
        self._connect_timeout_sec = max(1.0, float(timeout_sec))

    def suggest_alias(self, host_id: UUID, credential_id: UUID) -> str:
        host = self._vault.get_host(host_id)
        cred = self._vault.get_credential(credential_id)
        base = f"{host.name}-{cred.username}".replace(" ", "-").lower()
        with self._lock:
            n = self._alias_counts.get(base, 0) + 1
            self._alias_counts[base] = n
            return f"{base}-{n}"

    def open_tab(
        self,
        *,
        host_id: UUID,
        address_id: UUID,
        credential_id: UUID,
        alias: str | None = None,
        on_stage: ConnectionStageCallback | None = None,
        on_first_output: FirstOutputCallback | None = None,
    ) -> SessionInfo:
        with measure_stage(on_stage, "validate_selection"):
            self._vault.get_host(host_id)
            address = self._vault.get_address(address_id)
            credential = self._vault.get_credential(credential_id)
        if address.host_id != host_id or credential.host_id != host_id:
            raise SessionError("address/credential must belong to host")

        session_id = new_session_id()
        chosen_alias = alias or self.suggest_alias(host_id, credential_id)
        info = SessionInfo(
            id=session_id,
            alias=chosen_alias,
            status=SessionStatus.CONNECTING,
            host_id=host_id,
            address_id=address_id,
            credential_id=credential_id,
            target=SessionTarget.TAB,
            created_at=_utcnow(),
        )
        state = _SessionState(info=info)
        with self._lock:
            self._sessions[session_id] = state

        try:
            self._connect_state(
                state,
                on_stage=on_stage,
                on_first_output=on_first_output,
            )
        except Exception:
            with self._lock:
                state.info = SessionInfo(
                    id=info.id,
                    alias=info.alias,
                    status=SessionStatus.CLOSED,
                    host_id=info.host_id,
                    address_id=info.address_id,
                    credential_id=info.credential_id,
                    target=info.target,
                    mcp_enabled=info.mcp_enabled,
                    approve_enabled=info.approve_enabled,
                    created_at=info.created_at,
                )
                self._sessions.pop(session_id, None)
            raise
        return self.get(session_id)

    def get(self, session_id: UUID) -> SessionInfo:
        with self._lock:
            state = self._require(session_id)
            self._refresh_status(state)
            return state.info

    def list_sessions(self) -> list[SessionInfo]:
        with self._lock:
            result = []
            for state in self._sessions.values():
                self._refresh_status(state)
                result.append(state.info)
            return result

    def read(
        self,
        session_id: UUID,
        cursor: str | None = None,
        max_chars: int = 65536,
    ) -> BufferRead:
        with self._lock:
            state = self._require(session_id)
            self._refresh_status(state)
            return state.buffer.read_since(cursor, max_chars=max_chars)

    def write(self, session_id: UUID, text: str, *, submit: bool = False) -> None:
        payload = text
        if submit and not payload.endswith("\n"):
            payload += "\n"
        with self._lock:
            state = self._require(session_id)
            self._refresh_status(state)
            if state.info.status != SessionStatus.LIVE or state.shell is None:
                raise SessionStateError("session is not live")
            state.shell.write(payload)

    def find_script_run_by_request(
        self, session_id: UUID, request_id: UUID
    ) -> ScriptRunInfo | None:
        with self._lock:
            state = self._require(session_id)
            if (
                state.info.target != SessionTarget.TAB
                or not state.info.mcp_enabled
            ):
                raise ScriptRunStartError("not_found")
            run = self._script_runs.find_by_request(session_id, request_id)
            if run is not None and run.origin == ScriptRunOrigin.USER_INTERFACE:
                return None
            return run

    def start_script_run(
        self,
        session_id: UUID,
        script_id: UUID,
        request_id: UUID,
        *,
        params: Mapping[str, str] | None,
        origin: ScriptRunOrigin,
    ) -> ScriptRunInfo:
        """Start a visible saved script without using or modifying the PTY."""
        with self._lock:
            state = self._require(session_id)
            if (
                state.info.target != SessionTarget.TAB
                or not state.info.mcp_enabled
            ):
                raise ScriptRunStartError("not_found")

            existing = self._script_runs.find_by_request(session_id, request_id)
            if existing is not None:
                if existing.origin == ScriptRunOrigin.USER_INTERFACE:
                    raise ScriptRunStartError("not_found")
                return existing

            self._refresh_status(state)
            if state.info.status != SessionStatus.LIVE or state.shell is None:
                raise ScriptRunStartError("disconnected")
            if not state.info.approve_enabled:
                raise ScriptRunStartError("approve_required")

            try:
                script = self._vault.get_script(script_id)
            except NotFoundError as exc:
                raise ScriptRunStartError("not_found") from exc
            if not script.mcp_enabled or (
                script.host_id is not None and script.host_id != state.info.host_id
            ):
                raise ScriptRunStartError("not_found")

            command = render_script(script, params)
            shell = state.shell
            try:
                return self._script_runs.start(
                    session_id=session_id,
                    script_id=script_id,
                    request_id=request_id,
                    origin=origin,
                    command=command,
                    open_channel=shell.open_exec_channel,
                    session_alive=lambda: shell.alive,
                    display_name=script.name,
                    display_buffer=state.buffer,
                )
            except ScriptRunCapacityError as exc:
                raise ScriptRunStartError("run_capacity", str(exc)) from exc

    def start_user_script_run(
        self, session_id: UUID, script_id: UUID
    ) -> ScriptRunInfo:
        """Run a saved script from an explicit UI action and mirror its transcript."""
        with self._lock:
            state = self._require(session_id)
            if state.info.target != SessionTarget.TAB:
                raise SessionStateError("script execution requires a session tab")
            self._refresh_status(state)
            if state.info.status != SessionStatus.LIVE or state.shell is None:
                raise SessionStateError("session is not live")
            try:
                script = self._vault.get_script(script_id)
            except NotFoundError as exc:
                raise SessionStateError("script no longer exists") from exc
            if script.host_id is not None and script.host_id != state.info.host_id:
                raise SessionStateError("script belongs to another host")
            command = render_script(script, None)
            shell = state.shell
            try:
                return self._script_runs.start(
                    session_id=session_id,
                    script_id=script.id,
                    request_id=uuid4(),
                    origin=ScriptRunOrigin.USER_INTERFACE,
                    command=command,
                    open_channel=shell.open_exec_channel,
                    session_alive=lambda: shell.alive,
                    display_name=script.name,
                    display_buffer=state.buffer,
                )
            except ScriptRunCapacityError as exc:
                raise SessionStateError(str(exc)) from exc

    def get_script_run(self, session_id: UUID, run_id: UUID) -> ScriptRunInfo:
        with self._lock:
            state = self._require(session_id)
            if (
                state.info.target != SessionTarget.TAB
                or not state.info.mcp_enabled
            ):
                raise ScriptRunNotFoundError
            return self._require_mcp_script_run(session_id, run_id)

    def read_script_run_output(
        self,
        session_id: UUID,
        run_id: UUID,
        *,
        stdout_cursor: str | None = None,
        stderr_cursor: str | None = None,
        max_chars: int = 16_384,
    ) -> ScriptRunSnapshot:
        with self._lock:
            state = self._require(session_id)
            if (
                state.info.target != SessionTarget.TAB
                or not state.info.mcp_enabled
            ):
                raise ScriptRunNotFoundError
            self._require_mcp_script_run(session_id, run_id)
            return self._script_runs.read_output(
                session_id,
                run_id,
                stdout_cursor=stdout_cursor,
                stderr_cursor=stderr_cursor,
                max_chars=max_chars,
            )

    def wait_script_run(
        self,
        session_id: UUID,
        run_id: UUID,
        *,
        timeout_sec: float = 30.0,
        stdout_cursor: str | None = None,
        stderr_cursor: str | None = None,
        max_chars: int = 16_384,
    ) -> ScriptRunSnapshot:
        with self._lock:
            state = self._require(session_id)
            if (
                state.info.target != SessionTarget.TAB
                or not state.info.mcp_enabled
            ):
                raise ScriptRunNotFoundError
            self._require_mcp_script_run(session_id, run_id)
        return self._script_runs.wait(
            session_id,
            run_id,
            timeout_sec=timeout_sec,
            stdout_cursor=stdout_cursor,
            stderr_cursor=stderr_cursor,
            max_chars=max_chars,
        )

    def cancel_script_run(self, session_id: UUID, run_id: UUID) -> ScriptRunInfo:
        with self._lock:
            state = self._require(session_id)
            if (
                state.info.target != SessionTarget.TAB
                or not state.info.mcp_enabled
            ):
                raise ScriptRunNotFoundError
            self._require_mcp_script_run(session_id, run_id)
        return self._script_runs.cancel(session_id, run_id)

    def _require_mcp_script_run(
        self, session_id: UUID, run_id: UUID
    ) -> ScriptRunInfo:
        info = self._script_runs.get(session_id, run_id)
        if info.origin == ScriptRunOrigin.USER_INTERFACE:
            raise ScriptRunNotFoundError
        return info

    def resize(self, session_id: UUID, cols: int, rows: int) -> None:
        with self._lock:
            state = self._require(session_id)
            self._refresh_status(state)
            if state.info.status != SessionStatus.LIVE or state.shell is None:
                return
            state.shell.resize(cols, rows)

    def disconnect(self, session_id: UUID) -> SessionInfo:
        with self._lock:
            state = self._require(session_id)
            self._script_runs.on_session_lost(session_id)
            if state.shell is not None:
                state.shell.close()
                state.shell = None
            state.info = self._with_status(state.info, SessionStatus.DISCONNECTED)
            return state.info

    def reconnect(
        self,
        session_id: UUID,
        *,
        on_stage: ConnectionStageCallback | None = None,
        on_first_output: FirstOutputCallback | None = None,
    ) -> SessionInfo:
        with self._lock:
            state = self._require(session_id)
            if state.info.status == SessionStatus.CLOSED:
                raise SessionStateError("session is closed")
            self._script_runs.on_session_lost(session_id)
            if state.shell is not None:
                state.shell.close()
                state.shell = None
            state.info = self._with_status(state.info, SessionStatus.CONNECTING)
        self._connect_state(
            state,
            on_stage=on_stage,
            on_first_output=on_first_output,
        )
        return self.get(session_id)

    def close(self, session_id: UUID) -> None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return
            self._script_runs.on_session_lost(session_id)
            if state.shell is not None:
                state.shell.close()
                state.shell = None
            state.mcp_token = None
            state.mcp_client_id = None
            state.info = self._copy_info(
                state.info, status=SessionStatus.CLOSED, mcp_enabled=False
            )
            del self._sessions[session_id]

    def enable_mcp(self, session_id: UUID) -> str:
        """Enable MCP for tab session; return durable per-tab token."""
        with self._lock:
            state = self._require(session_id)
            if state.info.target != SessionTarget.TAB:
                raise SessionStateError("MCP is only available for tab sessions")
            if state.mcp_token is None:
                state.mcp_token = secrets.token_urlsafe(24)
            state.info = self._copy_info(state.info, mcp_enabled=True)
            return state.mcp_token

    def disable_mcp(self, session_id: UUID) -> SessionInfo:
        with self._lock:
            state = self._require(session_id)
            self._script_runs.on_execution_access_revoked(session_id)
            state.mcp_token = None
            state.mcp_client_id = None
            state.info = self._copy_info(state.info, mcp_enabled=False)
            return state.info

    def enable_mcp_all(self) -> list[str]:
        tokens: list[str] = []
        with self._lock:
            for session_id, state in list(self._sessions.items()):
                if state.info.target == SessionTarget.TAB:
                    tokens.append(self.enable_mcp(session_id))
        return tokens

    def disable_mcp_all(self) -> None:
        with self._lock:
            for session_id in list(self._sessions.keys()):
                self.disable_mcp(session_id)

    def set_approve(self, session_id: UUID, *, enabled: bool) -> SessionInfo:
        """Standing MCP write permission (Approve checkbox)."""
        with self._lock:
            state = self._require(session_id)
            state.info = self._copy_info(state.info, approve_enabled=enabled)
            if not enabled:
                self._script_runs.on_execution_access_revoked(session_id)
            return state.info

    def update_screen_snapshot(
        self,
        session_id: UUID,
        *,
        screen_tail: str,
        alt_screen: bool,
    ) -> None:
        """UI publishes visible pyte screen for MCP session_info."""
        with self._lock:
            state = self._require(session_id)
            state.screen_tail = screen_tail
            state.alt_screen = bool(alt_screen)

    def get_screen_snapshot(self, session_id: UUID) -> tuple[str, bool]:
        with self._lock:
            state = self._require(session_id)
            return state.screen_tail, state.alt_screen

    def mcp_url(self, session_id: UUID, *, host: str, port: int) -> str:
        with self._lock:
            state = self._require(session_id)
            if not state.info.mcp_enabled or not state.mcp_token:
                raise SessionStateError("MCP is not enabled for this session")
            token = state.mcp_token
        return f"http://{host}:{port}/mcp?token={token}"

    def resolve_mcp_token(self, token: str) -> SessionInfo:
        with self._lock:
            state = self._find_by_token(token)
            self._refresh_status(state)
            return state.info

    def acquire_mcp_client(self, token: str, client_id: str) -> SessionInfo:
        with self._lock:
            state = self._find_by_token(token)
            if state.mcp_client_id is not None and state.mcp_client_id != client_id:
                raise McpClientBusyError("client_busy")
            state.mcp_client_id = client_id
            self._refresh_status(state)
            info = state.info
            return self._copy_info(info, mcp_client_connected=True)

    def release_mcp_client(self, token: str, client_id: str) -> None:
        with self._lock:
            try:
                state = self._find_by_token(token)
            except McpUnauthorizedError:
                return
            if state.mcp_client_id == client_id:
                state.mcp_client_id = None

    def list_mcp_sessions(self) -> list[SessionInfo]:
        with self._lock:
            result = []
            for state in self._sessions.values():
                self._refresh_status(state)
                if state.info.mcp_enabled:
                    result.append(state.info)
            return result

    def wait_for_output(
        self,
        session_id: UUID,
        needle: str,
        *,
        timeout: float = 10.0,
        cursor: str | None = None,
    ) -> BufferRead:
        """Poll buffer until needle appears or timeout (for tests)."""
        deadline = time.time() + timeout
        current = cursor
        collected = ""
        last = BufferRead(data="", cursor=current or "0")
        while time.time() < deadline:
            last = self.read(session_id, cursor=current)
            collected += last.data
            current = last.cursor
            if needle in collected:
                return BufferRead(data=collected, cursor=current, truncated=last.truncated)
            time.sleep(0.1)
        raise TimeoutError(f"timeout waiting for {needle!r}; got: {collected!r}")

    def _connect_state(
        self,
        state: _SessionState,
        *,
        on_stage: ConnectionStageCallback | None = None,
        on_first_output: FirstOutputCallback | None = None,
    ) -> None:
        with measure_stage(on_stage, "load_connection_parameters"):
            address = self._vault.get_address(state.info.address_id)
            credential = self._vault.get_credential(state.info.credential_id)
        if address.knock_enabled and address.knock_steps:
            with measure_stage(on_stage, "port_knock"):
                perform_knock(
                    address.host,
                    [KnockStep.from_dict(s) for s in address.knock_steps],
                    delay_ms=address.knock_delay_ms,
                    pause_ms=address.knock_pause_ms,
                )
        elif on_stage is not None:
            on_stage("port_knock", 0.0, "skipped")
        use_agent = credential.auth_type == AUTH_OPENSSH_CONFIG
        params = SshConnectParams(
            hostname=address.host,
            port=address.port,
            username=credential.username,
            password=credential.password
            if credential.auth_type == AUTH_PASSWORD
            else None,
            private_key_pem=credential.private_key
            if credential.auth_type == AUTH_KEY_PAIR
            else None,
            passphrase=credential.passphrase
            if credential.auth_type == AUTH_KEY_PAIR
            else None,
            allow_agent=use_agent,
            look_for_keys=use_agent,
            connect_timeout_sec=self._connect_timeout_sec,
        )
        shell = SshShell(
            params,
            state.buffer,
            on_stage=on_stage,
            on_first_output=on_first_output,
        )
        shell.connect()
        with self._lock:
            state.shell = shell
            state.info = self._with_status(state.info, SessionStatus.LIVE)

    def _require(self, session_id: UUID) -> _SessionState:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(f"session not found: {session_id}") from exc

    def _find_by_token(self, token: str) -> _SessionState:
        if not token:
            raise McpUnauthorizedError("unauthorized")
        for state in self._sessions.values():
            if state.info.mcp_enabled and state.mcp_token == token:
                return state
        raise McpUnauthorizedError("unauthorized")

    def _refresh_status(self, state: _SessionState) -> None:
        if state.info.status in (SessionStatus.CLOSED, SessionStatus.CONNECTING):
            return
        if state.info.status == SessionStatus.LIVE:
            if state.shell is None or not state.shell.alive:
                self._script_runs.on_session_lost(state.info.id)
                if state.shell is not None:
                    state.shell.close()
                    state.shell = None
                state.info = self._copy_info(state.info, status=SessionStatus.DISCONNECTED)

    @staticmethod
    def _copy_info(
        info: SessionInfo,
        *,
        status: SessionStatus | None = None,
        mcp_enabled: bool | None = None,
        mcp_client_connected: bool | None = None,
        approve_enabled: bool | None = None,
    ) -> SessionInfo:
        return SessionInfo(
            id=info.id,
            alias=info.alias,
            status=status if status is not None else info.status,
            host_id=info.host_id,
            address_id=info.address_id,
            credential_id=info.credential_id,
            target=info.target,
            mcp_enabled=info.mcp_enabled if mcp_enabled is None else mcp_enabled,
            mcp_client_connected=(
                info.mcp_client_connected
                if mcp_client_connected is None
                else mcp_client_connected
            ),
            approve_enabled=(
                info.approve_enabled if approve_enabled is None else approve_enabled
            ),
            created_at=info.created_at,
        )

    def _with_status(self, info: SessionInfo, status: SessionStatus) -> SessionInfo:
        return self._copy_info(info, status=status)
