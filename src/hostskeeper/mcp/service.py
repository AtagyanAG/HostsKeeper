"""MCP tool business logic (stdio + HTTP gateway / legacy tab token)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from difflib import unified_diff
from typing import Any, Literal
from uuid import UUID

from hostskeeper.mcp.app_key import keys_match
from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.scripts_render import analyze_script, render_script
from hostskeeper.session.manager import (
    McpClientBusyError,
    McpUnauthorizedError,
    SessionManager,
    SessionStateError,
    ScriptRunStartError,
)
from hostskeeper.session.models import SessionInfo, SessionStatus
from hostskeeper.session.script_runs import ScriptRunInfo, ScriptRunOrigin
from hostskeeper.vault.errors import NotFoundError, ValidationError
from hostskeeper.vault.models import Group, Host, Note, Script, ScriptParameter
from hostskeeper.vault.script_render import ScriptRenderError
from hostskeeper.vault.store import Vault


AccessMode = Literal["stdio", "http"]
_UNSET = object()
_SCRIPT_NOT_FOUND_MESSAGE = (
    "script not found or not visible to this client; refresh scripts_list. "
    "Host scripts require an MCP-enabled open tab for that host."
)
_SCRIPT_DIFF_MAX_CHARS = 20_000


@dataclass
class McpAccess:
    mode: AccessMode
    token: str | None = None
    client_id: str | None = None
    # True when authenticated with stable LAN app key (sees all mcp-enabled tabs).
    gateway: bool = False


class McpToolService:
    def __init__(
        self,
        sessions: SessionManager,
        vault: Vault,
        *,
        app_key: str | None = None,
        on_vault_changed: Callable[[], None] | None = None,
    ) -> None:
        self._sessions = sessions
        self._vault = vault
        self._app_key = app_key or ""
        # Fired after vault mutations (scripts/groups/host profile) so UI can refresh.
        self._on_vault_changed = on_vault_changed
        # Gateway / stdio pin: client_id → session_id
        self._pins: dict[str, UUID] = {}

    @property
    def app_key(self) -> str:
        return self._app_key

    def set_app_key(self, key: str) -> None:
        self._app_key = key or ""

    def set_vault_changed_callback(
        self, callback: Callable[[], None] | None
    ) -> None:
        self._on_vault_changed = callback

    def _notify_vault_changed(self) -> None:
        cb = self._on_vault_changed
        if cb is None:
            return
        try:
            cb()
        except Exception:  # noqa: BLE001 — UI refresh must not break MCP tools
            pass

    def check_app_key(self, provided: str | None) -> bool:
        if not self._app_key:
            return False
        return keys_match(provided, self._app_key)

    def session_list(self, access: McpAccess) -> dict[str, Any]:
        sessions = self._visible_sessions(access)
        return {
            "sessions": [
                {
                    "session_id": str(s.id),
                    "alias": s.alias,
                    "status": s.status.value,
                }
                for s in sessions
            ]
        }

    def session_attach(
        self,
        access: McpAccess,
        *,
        session_id: str | None = None,
        alias: str | None = None,
        tab_token: str | None = None,
    ) -> dict[str, Any]:
        """Pin default session for subsequent tools (gateway/stdio). Legacy HTTP token is already bound."""
        if access.mode == "http" and not access.gateway:
            info = self._resolve_session(access, session_id=None, alias=None)
            if session_id and str(info.id) != session_id:
                raise McpToolError("client_scope", "HTTP token is bound to another session")
            if alias and info.alias != alias:
                raise McpToolError("client_scope", "HTTP token is bound to another session")
            if tab_token and access.token and tab_token != access.token:
                raise McpToolError("client_scope", "HTTP token is bound to another session")
            return {
                "ok": True,
                "alias": info.alias,
                "session_id": str(info.id),
                "pinned": False,
            }

        info: SessionInfo | None = None
        if tab_token:
            try:
                info = self._sessions.resolve_mcp_token(tab_token)
            except McpUnauthorizedError as exc:
                raise McpToolError("unauthorized") from exc
            if not info.mcp_enabled:
                raise McpToolError("not_found", "session not found in MCP scope")
        else:
            info = self._resolve_among(
                self._visible_sessions(access),
                session_id=session_id,
                alias=alias,
                require_selector=True,
            )

        pin_key = access.client_id or "default"
        self._pins[pin_key] = info.id
        return {
            "ok": True,
            "alias": info.alias,
            "session_id": str(info.id),
            "pinned": True,
        }

    def session_info(
        self,
        access: McpAccess,
        *,
        session_id: str | None = None,
        alias: str | None = None,
    ) -> dict[str, Any]:
        info = self._resolve_session(access, session_id=session_id, alias=alias)
        screen_tail, alt_screen = self._sessions.get_screen_snapshot(info.id)
        profile = ""
        try:
            profile = (self._vault.get_host(info.host_id).profile or "").strip()
        except NotFoundError:
            profile = ""
        return {
            "session_id": str(info.id),
            "alias": info.alias,
            "status": info.status.value,
            "approve_enabled": info.approve_enabled,
            "alt_screen": alt_screen,
            "screen_tail": screen_tail,
            "host_id": str(info.host_id),
            "host_profile_present": bool(profile),
            "host_profile_chars": len(profile),
            "host_profile_hint": (
                "After attach, call host_profile_get. If empty or thin, ask the user "
                "to fill Host Notes; on consent gather facts via the PTY (Approve on) "
                "and save with host_profile_set."
            ),
        }

    def session_read(
        self,
        access: McpAccess,
        *,
        session_id: str | None = None,
        alias: str | None = None,
        cursor: str | None = None,
        max_bytes: int = 65536,
    ) -> dict[str, Any]:
        info = self._resolve_session(access, session_id=session_id, alias=alias)
        if info.status == SessionStatus.DISCONNECTED:
            raise McpToolError("disconnected")
        if info.status != SessionStatus.LIVE:
            raise McpToolError("disconnected", f"session status is {info.status.value}")
        result = self._sessions.read(info.id, cursor=cursor, max_chars=max_bytes)
        info = self._sessions.get(info.id)
        return {
            "alias": info.alias,
            "status": info.status.value,
            "cursor": result.cursor,
            "data": result.data,
            "truncated": result.truncated,
        }

    def session_write(
        self,
        access: McpAccess,
        *,
        text: str,
        session_id: str | None = None,
        alias: str | None = None,
        submit: bool = True,
    ) -> dict[str, Any]:
        info = self._resolve_session(access, session_id=session_id, alias=alias)
        if info.status != SessionStatus.LIVE:
            raise McpToolError("disconnected")
        if not info.approve_enabled:
            raise McpToolError("approve_required")
        try:
            self._sessions.write(info.id, text, submit=submit)
        except SessionStateError as exc:
            raise McpToolError("disconnected", str(exc)) from exc
        return {"ok": True, "alias": info.alias}

    def session_subscribe(
        self,
        access: McpAccess,
        *,
        session_id: str | None = None,
        alias: str | None = None,
        cursor: str | None = None,
        timeout_sec: float = 30.0,
    ) -> dict[str, Any]:
        """Long-poll until new output, status change, or timeout."""
        info = self._resolve_session(access, session_id=session_id, alias=alias)
        deadline = time.time() + max(0.1, timeout_sec)
        current = cursor
        while time.time() < deadline:
            info = self._sessions.get(info.id)
            if info.status != SessionStatus.LIVE:
                return {
                    "type": "status",
                    "alias": info.alias,
                    "status": info.status.value,
                }
            chunk = self._sessions.read(info.id, cursor=current, max_chars=65536)
            if chunk.data:
                return {
                    "type": "output",
                    "alias": info.alias,
                    "cursor": chunk.cursor,
                    "data": chunk.data,
                }
            current = chunk.cursor
            time.sleep(0.1)
        info = self._sessions.get(info.id)
        empty = self._sessions.read(info.id, cursor=current, max_chars=0)
        return {
            "type": "output",
            "alias": info.alias,
            "cursor": empty.cursor,
            "data": "",
        }

    def bind_http_client(self, token: str, client_id: str) -> SessionInfo:
        try:
            return self._sessions.acquire_mcp_client(token, client_id)
        except McpUnauthorizedError as exc:
            raise McpToolError("unauthorized") from exc
        except McpClientBusyError as exc:
            raise McpToolError("client_busy") from exc

    def unbind_http_client(self, token: str, client_id: str) -> None:
        self._sessions.release_mcp_client(token, client_id)

    def host_profile_get(
        self,
        access: McpAccess,
        *,
        session_id: str | None = None,
        alias: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        """Read Host Notes (profile). Requires open MCP tab for that host."""
        host = self._resolve_accessible_host(
            access, session_id=session_id, alias=alias, host_id=host_id
        )
        text = host.profile or ""
        return {
            "host_id": str(host.id),
            "name": host.name,
            "profile": text,
            "chars": len(text),
            "present": bool(text.strip()),
            "updated_at": host.updated_at.isoformat(),
        }

    def host_profile_set(
        self,
        access: McpAccess,
        *,
        profile: str,
        session_id: str | None = None,
        alias: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        """Write Host Notes (profile). No Approve. Requires open MCP tab for host."""
        host = self._resolve_accessible_host(
            access, session_id=session_id, alias=alias, host_id=host_id
        )
        host.profile = (profile or "").strip() or None
        saved = self._vault.update_host(host)
        self._notify_vault_changed()
        text = saved.profile or ""
        return {
            "ok": True,
            "host_id": str(saved.id),
            "name": saved.name,
            "chars": len(text),
            "present": bool(text.strip()),
            "updated_at": saved.updated_at.isoformat(),
        }

    def scripts_list(self, access: McpAccess) -> dict[str, Any]:
        self._assert_access(access)
        visible_sessions = self._visible_sessions(access)
        visible_hosts = {session.host_id for session in visible_sessions}
        host_aliases: dict[UUID, str] = {}
        for session in visible_sessions:
            host_aliases.setdefault(session.host_id, session.alias)
        scripts = []
        for script in self._vault.list_scripts():
            if not script.mcp_enabled:
                continue
            if script.host_id is not None and script.host_id not in visible_hosts:
                continue
            scripts.append(
                {
                    "id": str(script.id),
                    "name": script.name,
                    "scope": "host" if script.host_id is not None else "template",
                    "host_alias": (
                        host_aliases.get(script.host_id)
                        if script.host_id is not None
                        else None
                    ),
                    "description": script.description,
                    "tags": list(script.tags),
                    "parameters": [p.to_mcp_dict() for p in script.parameters],
                    "host_id": str(script.host_id) if script.host_id else None,
                    "group_id": str(script.group_id) if script.group_id else None,
                    "mcp_enabled": True,
                }
            )
        return {"scripts": scripts}

    def scripts_get(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        script = self._find_script(access, id=id, name=name, host_id=host_id)
        return script.to_mcp_dict()

    def scripts_compare(
        self,
        access: McpAccess,
        *,
        left_script_id: str,
        right_script_id: str,
    ) -> dict[str, Any]:
        """Compare two scripts visible to this client without modifying the vault."""
        self._assert_access(access)
        left = self._find_script(access, id=left_script_id, name=None)
        right = self._find_script(access, id=right_script_id, name=None)

        left_parameters = [parameter.to_mcp_dict() for parameter in left.parameters]
        right_parameters = [parameter.to_mcp_dict() for parameter in right.parameters]
        metadata: dict[str, Any] = {}
        for field, left_value, right_value in (
            ("name", left.name, right.name),
            ("description", left.description, right.description),
            ("parameters", left_parameters, right_parameters),
        ):
            if left_value != right_value:
                metadata[field] = {"left": left_value, "right": right_value}

        def diff_input(body: str) -> list[str]:
            lines = body.splitlines(keepends=True)
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += "\n"
            return lines

        diff_lines = unified_diff(
            diff_input(left.body),
            diff_input(right.body),
            fromfile=str(left.id),
            tofile=str(right.id),
        )
        diff_parts: list[str] = []
        diff_length = 0
        truncated = False
        for line in diff_lines:
            if diff_length + len(line) > _SCRIPT_DIFF_MAX_CHARS:
                truncated = True
                break
            diff_parts.append(line)
            diff_length += len(line)

        body_diff = "".join(diff_parts)
        if truncated:
            marker = "\n... diff truncated; compare smaller script sections ...\n"
            while diff_parts and diff_length + len(marker) > _SCRIPT_DIFF_MAX_CHARS:
                diff_length -= len(diff_parts.pop())
            body_diff = "".join(diff_parts) + marker

        return {
            "left": {"id": str(left.id), "name": left.name},
            "right": {"id": str(right.id), "name": right.name},
            "metadata_differences": metadata,
            "body_diff": body_diff,
            "body_diff_truncated": truncated,
        }

    def scripts_validate(
        self,
        access: McpAccess,
        *,
        body: str,
        parameters: list[dict[str, Any]] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """Validate a script draft without saving, rendering, or writing to a PTY."""
        self._assert_access(access)
        try:
            parsed_parameters = [
                ScriptParameter.from_mcp_dict(parameter)
                for parameter in (parameters or [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise McpToolError("invalid_args", "invalid script parameters") from exc
        return analyze_script(body, parsed_parameters, params).to_dict()

    def scripts_create(
        self,
        access: McpAccess,
        *,
        name: str,
        body: str,
        description: str | None = None,
        tags: list[str] | None = None,
        parameters: list[dict[str, Any]] | None = None,
        host_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        resolved_host: UUID | None = None
        if host_id:
            try:
                resolved_host = UUID(host_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid host_id") from exc
            if resolved_host not in self._accessible_host_ids(access):
                raise McpToolError(
                    "client_scope",
                    "host scripts require an open MCP tab on that host",
                )
        resolved_group: UUID | None = None
        if group_id:
            try:
                resolved_group = UUID(group_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid group_id") from exc
        script = Script(
            name=name,
            body=body,
            description=description,
            tags=list(tags or []),
            parameters=[
                ScriptParameter.from_mcp_dict(p) for p in (parameters or [])
            ],
            host_id=resolved_host,
            group_id=resolved_group,
            mcp_enabled=True,
        )
        self._validate_script_placeholders(script)
        try:
            stored = self._vault.add_script(script)
        except ValidationError as exc:
            raise McpToolError("invalid_args", str(exc)) from exc
        self._notify_vault_changed()
        return stored.to_mcp_dict()

    def scripts_update(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        body: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        parameters: list[dict[str, Any]] | None = None,
        new_name: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        script = self._find_script(access, id=id, name=name, host_id=host_id)
        if new_name is not None:
            script.name = new_name
        if body is not None:
            script.body = body
        if description is not None:
            script.description = description
        if tags is not None:
            script.tags = list(tags)
        if parameters is not None:
            previous = {p.name: p for p in script.parameters}
            script.parameters = [
                ScriptParameter.from_mcp_dict(p, preserve=previous.get(p.get("name")))
                for p in parameters
                if isinstance(p, dict)
            ]
        if group_id is not None:
            script.group_id = UUID(group_id) if group_id else None
        self._validate_script_placeholders(script)
        try:
            stored = self._vault.update_script(script)
        except (ValidationError, ValueError) as exc:
            raise McpToolError("invalid_args", str(exc)) from exc
        self._notify_vault_changed()
        return stored.to_mcp_dict()

    @staticmethod
    def _validate_script_placeholders(script: Script) -> None:
        analysis = analyze_script(script.body, script.parameters)
        if not analysis.errors:
            return
        details = []
        for issue in analysis.errors:
            if issue.code == "unknown_placeholder":
                details.append(
                    f"unknown placeholder {issue.name} at position {issue.position}"
                )
            elif issue.code == "malformed_placeholder":
                details.append(
                    f"malformed placeholder at position {issue.position}"
                )
            elif issue.code == "invalid_parameter_name":
                details.append(
                    f"invalid parameter name at index {issue.parameter_index}"
                )
            else:
                details.append(
                    f"duplicate parameter at index {issue.parameter_index}"
                )
        raise McpToolError("invalid_args", "; ".join(details))

    def scripts_delete(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        script = self._find_script(access, id=id, name=name, host_id=host_id)
        self._vault.delete_script(script.id)
        self._notify_vault_changed()
        return {"ok": True, "id": str(script.id), "name": script.name}

    def notes_list(self, access: McpAccess) -> dict[str, Any]:
        self._assert_access(access)
        visible_hosts = self._accessible_host_ids(access)
        notes = []
        for note in self._vault.list_notes():
            if not note.mcp_enabled:
                continue
            if note.host_id is not None and note.host_id not in visible_hosts:
                continue
            notes.append(
                {
                    "id": str(note.id),
                    "name": note.name,
                    "host_id": str(note.host_id) if note.host_id else None,
                    "group_id": str(note.group_id) if note.group_id else None,
                    "mcp_enabled": True,
                    "chars": len(note.body or ""),
                }
            )
        return {"notes": notes}

    def notes_get(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        note = self._find_note(access, id=id, name=name, host_id=host_id)
        return note.to_mcp_dict()

    def notes_create(
        self,
        access: McpAccess,
        *,
        name: str,
        body: str = "",
        host_id: str | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        """Create note; mcp_enabled always True (model cannot set the flag)."""
        self._assert_access(access)
        resolved_host: UUID | None = None
        if host_id:
            try:
                resolved_host = UUID(host_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid host_id") from exc
            if resolved_host not in self._accessible_host_ids(access):
                raise McpToolError(
                    "client_scope",
                    "host notes require an open MCP tab on that host",
                )
        resolved_group: UUID | None = None
        if group_id:
            try:
                resolved_group = UUID(group_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid group_id") from exc
        note = Note(
            name=name,
            body=body or "",
            host_id=resolved_host,
            group_id=resolved_group,
            mcp_enabled=True,
        )
        try:
            stored = self._vault.add_note(note)
        except ValidationError as exc:
            raise McpToolError("invalid_args", str(exc)) from exc
        self._notify_vault_changed()
        return stored.to_mcp_dict()

    def notes_update(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        body: str | None = None,
        new_name: str | None = None,
        group_id: object = _UNSET,
    ) -> dict[str, Any]:
        """Update note body/name/group; mcp_enabled is not changed via MCP."""
        self._assert_access(access)
        note = self._find_note(access, id=id, name=name, host_id=host_id)
        if body is not None:
            note.body = body
        if new_name is not None:
            note.name = new_name
        if group_id is not _UNSET:
            if group_id is None or group_id == "":
                note.group_id = None
            else:
                try:
                    note.group_id = UUID(str(group_id))
                except ValueError as exc:
                    raise McpToolError("invalid_args", "invalid group_id") from exc
        try:
            stored = self._vault.update_note(note)
        except (ValidationError, ValueError) as exc:
            raise McpToolError("invalid_args", str(exc)) from exc
        self._notify_vault_changed()
        return stored.to_mcp_dict()

    def notes_delete(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        note = self._find_note(access, id=id, name=name, host_id=host_id)
        self._vault.delete_note(note.id)
        self._notify_vault_changed()
        return {"ok": True, "id": str(note.id), "name": note.name}

    def scripts_run(
        self,
        access: McpAccess,
        *,
        script_id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        params: dict[str, str] | None = None,
        session_id: str | None = None,
        alias: str | None = None,
        submit: bool = True,
    ) -> dict[str, Any]:
        script = self._find_script(
            access, id=script_id, name=name, host_id=host_id
        )
        rendered = render_script(script, params)
        if script.host_id is not None:
            info = self._resolve_session(
                access, session_id=session_id, alias=alias
            )
            if info.host_id != script.host_id:
                raise McpToolError(
                    "client_scope",
                    "host script can only run in a session of that host",
                )
            return self.session_write(
                access,
                text=rendered,
                session_id=str(info.id),
                alias=None,
                submit=submit,
            )
        return self.session_write(
            access,
            text=rendered,
            session_id=session_id,
            alias=alias,
            submit=submit,
        )

    def _start_script_run(
        self,
        access: McpAccess,
        *,
        request_id: str,
        script_id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        params: dict[str, str] | None = None,
        session_id: str | None = None,
        alias: str | None = None,
    ) -> ScriptRunInfo:
        """Internal isolated-run path; not registered as an MCP tool yet."""
        try:
            request_uuid = UUID(request_id)
        except ValueError as exc:
            raise McpToolError("invalid_args", "invalid request_id") from exc

        info = self._resolve_session(
            access, session_id=session_id, alias=alias
        )
        try:
            existing = self._sessions.find_script_run_by_request(
                info.id, request_uuid
            )
        except ScriptRunStartError as exc:
            raise McpToolError(exc.code) from exc
        if existing is not None:
            return existing

        script = self._find_script(
            access, id=script_id, name=name, host_id=host_id
        )
        if script.host_id is not None and info.host_id != script.host_id:
            raise McpToolError(
                "client_scope",
                "host script can only run in a session of that host",
            )
        origin = (
            ScriptRunOrigin.STDIO
            if access.mode == "stdio"
            else ScriptRunOrigin.HTTP_GATEWAY
            if access.gateway
            else ScriptRunOrigin.HTTP_LEGACY
        )
        try:
            return self._sessions.start_script_run(
                info.id,
                script.id,
                request_uuid,
                params=params,
                origin=origin,
            )
        except ScriptRenderError as exc:
            raise McpToolError(exc.code, str(exc)) from exc
        except ScriptRunStartError as exc:
            raise McpToolError(exc.code) from exc

    def groups_list(
        self,
        access: McpAccess,
        *,
        kind: str = "scripts",
    ) -> dict[str, Any]:
        self._assert_access(access)
        if kind not in ("hosts", "scripts"):
            raise McpToolError("invalid_args", "kind must be hosts or scripts")
        visible_hosts = self._accessible_host_ids(access)
        groups = []
        for group in self._vault.list_groups(kind=kind):
            if group.host_id is not None and group.host_id not in visible_hosts:
                continue
            if kind == "hosts" and group.host_id is not None:
                continue
            groups.append(
                {
                    "id": str(group.id),
                    "name": group.name,
                    "kind": group.kind,
                    "parent_id": str(group.parent_id) if group.parent_id else None,
                    "host_id": str(group.host_id) if group.host_id else None,
                }
            )
        return {"groups": groups}

    def groups_create(
        self,
        access: McpAccess,
        *,
        name: str,
        kind: str = "scripts",
        parent_id: str | None = None,
        host_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        if kind not in ("hosts", "scripts"):
            raise McpToolError("invalid_args", "kind must be hosts or scripts")
        resolved_host: UUID | None = None
        if host_id:
            if kind != "scripts":
                raise McpToolError("invalid_args", "host_id only for scripts groups")
            try:
                resolved_host = UUID(host_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid host_id") from exc
            if resolved_host not in self._accessible_host_ids(access):
                raise McpToolError(
                    "client_scope",
                    "host groups require an open MCP tab on that host",
                )
        resolved_parent: UUID | None = None
        if parent_id:
            try:
                resolved_parent = UUID(parent_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid parent_id") from exc
        try:
            stored = self._vault.add_group(
                Group(
                    name=name,
                    kind=kind,
                    parent_id=resolved_parent,
                    host_id=resolved_host,
                )
            )
        except ValidationError as exc:
            raise McpToolError("invalid_args", str(exc)) from exc
        self._notify_vault_changed()
        return stored.to_mcp_dict()

    def groups_update(
        self,
        access: McpAccess,
        *,
        id: str,
        name: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        self._assert_access(access)
        group = self._require_group_access(access, id)
        if name is not None:
            group.name = name
        if parent_id is not None:
            group.parent_id = UUID(parent_id) if parent_id else None
        try:
            stored = self._vault.update_group(group)
        except (ValidationError, ValueError) as exc:
            raise McpToolError("invalid_args", str(exc)) from exc
        self._notify_vault_changed()
        return stored.to_mcp_dict()

    def groups_delete(self, access: McpAccess, *, id: str) -> dict[str, Any]:
        """Delete group and all nested content (hosts/scripts/notes/groups)."""
        self._assert_access(access)
        group = self._require_group_access(access, id)
        counts = self._vault.group_content_counts(group.id)
        self._vault.delete_group(group.id)
        self._notify_vault_changed()
        return {
            "ok": True,
            "id": str(group.id),
            "name": group.name,
            "deleted": counts,
        }

    def _assert_access(self, access: McpAccess) -> None:
        # stdio trusted; HTTP must have valid token or gateway key.
        if access.mode == "http":
            self._visible_sessions(access)

    def _accessible_host_ids(self, access: McpAccess) -> set[UUID]:
        try:
            return {s.host_id for s in self._visible_sessions(access)}
        except McpToolError:
            return set()

    def _resolve_accessible_host(
        self,
        access: McpAccess,
        *,
        session_id: str | None,
        alias: str | None,
        host_id: str | None,
    ) -> Host:
        accessible = self._accessible_host_ids(access)
        if not accessible:
            raise McpToolError(
                "not_found", "no MCP-enabled tab; open a tab and enable MCP"
            )
        resolved: UUID | None = None
        if host_id:
            try:
                resolved = UUID(host_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid host_id") from exc
            if resolved not in accessible:
                raise McpToolError("not_found", "host not in MCP scope")
        else:
            info = self._resolve_session(
                access, session_id=session_id, alias=alias
            )
            resolved = info.host_id
            if resolved not in accessible:
                raise McpToolError("not_found", "host not in MCP scope")
        try:
            return self._vault.get_host(resolved)
        except NotFoundError as exc:
            raise McpToolError("not_found", "host not found") from exc

    def _script_visible(self, access: McpAccess, script: Script) -> bool:
        if not script.mcp_enabled:
            return False
        if script.host_id is None:
            return True
        return script.host_id in self._accessible_host_ids(access)

    def _require_group_access(self, access: McpAccess, id: str) -> Group:
        try:
            group = self._vault.get_group(UUID(id))
        except (ValueError, NotFoundError) as exc:
            raise McpToolError("not_found", "group not found") from exc
        if group.host_id is not None and group.host_id not in self._accessible_host_ids(
            access
        ):
            raise McpToolError("not_found", "group not found")
        return group

    def _find_note(
        self,
        access: McpAccess,
        *,
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> Note:
        visible_hosts = self._accessible_host_ids(access)
        if id:
            try:
                note = self._vault.get_note(UUID(id))
            except (ValueError, NotFoundError) as exc:
                raise McpToolError("not_found", "note not found") from exc
            if not note.mcp_enabled:
                raise McpToolError("not_found", "note not found")
            if note.host_id is not None and note.host_id not in visible_hosts:
                raise McpToolError(
                    "client_scope",
                    "host notes require an open MCP tab on that host",
                )
            return note
        if name:
            resolved_host: UUID | None = None
            if host_id:
                try:
                    resolved_host = UUID(host_id)
                except ValueError as exc:
                    raise McpToolError("invalid_args", "invalid host_id") from exc
            matches = [
                n
                for n in self._vault.list_notes()
                if n.mcp_enabled
                and n.name == name
                and (n.host_id is None or n.host_id in visible_hosts)
            ]
            if host_id is not None:
                matches = [n for n in matches if n.host_id == resolved_host]
            else:
                templates = [n for n in matches if n.host_id is None]
                if templates:
                    matches = templates
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise McpToolError("not_found", "note not found")
            raise McpToolError(
                "invalid_args",
                "ambiguous note name; pass id or host_id",
            )
        raise McpToolError("invalid_args", "id or name required")

    def _find_script(
        self,
        access: McpAccess,
        *,
        id: str | None,
        name: str | None,
        host_id: str | None = None,
    ) -> Script:
        resolved_host: UUID | None | object = _UNSET
        if host_id is not None:
            if host_id == "":
                resolved_host = None
            else:
                try:
                    resolved_host = UUID(host_id)
                except ValueError as exc:
                    raise McpToolError("invalid_args", "invalid host_id") from exc
        if id:
            try:
                script = self._vault.get_script(UUID(id))
            except (ValueError, NotFoundError) as exc:
                raise McpToolError("not_found", _SCRIPT_NOT_FOUND_MESSAGE) from exc
            if not self._script_visible(access, script):
                raise McpToolError("not_found", _SCRIPT_NOT_FOUND_MESSAGE)
            return script
        if name:
            if resolved_host is not _UNSET:
                try:
                    script = self._vault.get_script_by_name(
                        name, host_id=resolved_host  # type: ignore[arg-type]
                    )
                except NotFoundError as exc:
                    raise McpToolError(
                        "not_found", _SCRIPT_NOT_FOUND_MESSAGE
                    ) from exc
                if not self._script_visible(access, script):
                    raise McpToolError("not_found", _SCRIPT_NOT_FOUND_MESSAGE)
                return script
            matches = [
                s
                for s in self._vault.list_scripts()
                if s.name == name and self._script_visible(access, s)
            ]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                raise McpToolError("not_found", _SCRIPT_NOT_FOUND_MESSAGE)
            raise McpToolError(
                "invalid_args",
                "ambiguous script name; pass id or host_id",
            )
        raise McpToolError("invalid_args", "id or name required")

    def _visible_sessions(self, access: McpAccess) -> list[SessionInfo]:
        if access.mode == "stdio" or access.gateway:
            return self._sessions.list_mcp_sessions()
        if not access.token:
            raise McpToolError("unauthorized")
        try:
            info = self._sessions.resolve_mcp_token(access.token)
        except McpUnauthorizedError as exc:
            raise McpToolError("unauthorized") from exc
        return [info]

    def _resolve_session(
        self,
        access: McpAccess,
        *,
        session_id: str | None,
        alias: str | None,
    ) -> SessionInfo:
        visible = self._visible_sessions(access)
        if access.mode == "http" and not access.gateway:
            if not visible:
                raise McpToolError("unauthorized")
            info = visible[0]
            if session_id and str(info.id) != session_id:
                raise McpToolError("client_scope", "HTTP token is bound to another session")
            if alias and info.alias != alias:
                raise McpToolError("client_scope", "HTTP token is bound to another session")
            return info

        # stdio or HTTP gateway: alias / session_id / pin / single visible
        if not session_id and not alias:
            pin_key = access.client_id or "default"
            pinned = self._pins.get(pin_key)
            if pinned is not None:
                for item in visible:
                    if item.id == pinned:
                        return item
                # Stale pin
                self._pins.pop(pin_key, None)

        return self._resolve_among(
            visible,
            session_id=session_id,
            alias=alias,
            require_selector=False,
        )

    def _resolve_among(
        self,
        visible: list[SessionInfo],
        *,
        session_id: str | None,
        alias: str | None,
        require_selector: bool,
    ) -> SessionInfo:
        if session_id:
            try:
                sid = UUID(session_id)
            except ValueError as exc:
                raise McpToolError("invalid_args", "invalid session_id") from exc
            for item in visible:
                if item.id == sid:
                    return item
            raise McpToolError("not_found", "session not found in MCP scope")
        if alias:
            for item in visible:
                if item.alias == alias:
                    return item
            raise McpToolError("not_found", "session not found in MCP scope")
        if require_selector:
            raise McpToolError("invalid_args", "session_id, alias, or tab_token required")
        if len(visible) == 1:
            return visible[0]
        raise McpToolError("invalid_args", "session_id or alias required")
