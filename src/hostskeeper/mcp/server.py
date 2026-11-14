"""MCPServer wiring for HostsKeeper session tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from hostskeeper.mcp.context import get_access
from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpToolService


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _tool_error(exc: McpToolError) -> str:
    return _dump(exc.as_dict())


def build_mcp_server(service: McpToolService, *, name: str = "HostsKeeper") -> MCPServer:
    mcp = MCPServer(name)

    @mcp.tool()
    def session_list() -> str:
        """List MCP-enabled sessions visible to this client."""
        try:
            return _dump(service.session_list(get_access()))
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def session_attach(
        session_id: str | None = None,
        alias: str | None = None,
        tab_token: str | None = None,
    ) -> str:
        """Pin default session for gateway/stdio (use after session_list)."""
        try:
            return _dump(
                service.session_attach(
                    get_access(),
                    session_id=session_id,
                    alias=alias,
                    tab_token=tab_token,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def session_info(session_id: str | None = None, alias: str | None = None) -> str:
        """Session status, screen_tail, and host Notes hints (call host_profile_get next)."""
        try:
            return _dump(
                service.session_info(
                    get_access(), session_id=session_id, alias=alias
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def host_profile_get(
        session_id: str | None = None,
        alias: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Read Host Notes (Edit Host → Notes). Call after session_attach; no secrets/IPs."""
        try:
            return _dump(
                service.host_profile_get(
                    get_access(),
                    session_id=session_id,
                    alias=alias,
                    host_id=host_id,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def host_profile_set(
        profile: str,
        session_id: str | None = None,
        alias: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Write Host Notes (free text). No Approve. Ask the user before filling empty Notes."""
        try:
            return _dump(
                service.host_profile_set(
                    get_access(),
                    profile=profile,
                    session_id=session_id,
                    alias=alias,
                    host_id=host_id,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def session_read(
        session_id: str | None = None,
        alias: str | None = None,
        cursor: str | None = None,
        max_bytes: int = 65536,
    ) -> str:
        """Read new terminal output since cursor."""
        try:
            return _dump(
                service.session_read(
                    get_access(),
                    session_id=session_id,
                    alias=alias,
                    cursor=cursor,
                    max_bytes=max_bytes,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def session_write(
        text: str,
        session_id: str | None = None,
        alias: str | None = None,
        submit: bool = True,
    ) -> str:
        """Write text into the session PTY."""
        try:
            return _dump(
                service.session_write(
                    get_access(),
                    text=text,
                    session_id=session_id,
                    alias=alias,
                    submit=submit,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def session_subscribe(
        session_id: str | None = None,
        alias: str | None = None,
        cursor: str | None = None,
        timeout_sec: float = 30.0,
    ) -> str:
        """Long-poll for new terminal output or status change."""
        try:
            return _dump(
                service.session_subscribe(
                    get_access(),
                    session_id=session_id,
                    alias=alias,
                    cursor=cursor,
                    timeout_sec=timeout_sec,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def scripts_list() -> str:
        """List scripts in the vault (no secrets beyond script body metadata)."""
        try:
            return _dump(service.scripts_list(get_access()))
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def scripts_get(
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Get a script including body (templates always; host scripts need open tab)."""
        try:
            return _dump(
                service.scripts_get(
                    get_access(), id=id, name=name, host_id=host_id
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def scripts_create(
        name: str,
        body: str,
        description: str | None = None,
        tags: list[str] | None = None,
        parameters: list[dict] | None = None,
        host_id: str | None = None,
        group_id: str | None = None,
    ) -> str:
        """Create a template or host script (host_id requires open MCP tab on that host)."""
        try:
            return _dump(
                service.scripts_create(
                    get_access(),
                    name=name,
                    body=body,
                    description=description,
                    tags=tags,
                    parameters=parameters,
                    host_id=host_id,
                    group_id=group_id,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def scripts_update(
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        body: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        parameters: list[dict] | None = None,
        new_name: str | None = None,
        group_id: str | None = None,
    ) -> str:
        """Update a script (no approve)."""
        try:
            return _dump(
                service.scripts_update(
                    get_access(),
                    id=id,
                    name=name,
                    host_id=host_id,
                    body=body,
                    description=description,
                    tags=tags,
                    parameters=parameters,
                    new_name=new_name,
                    group_id=group_id,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def scripts_delete(
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Delete a script (no approve)."""
        try:
            return _dump(
                service.scripts_delete(
                    get_access(), id=id, name=name, host_id=host_id
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def scripts_run(
        script_id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        params: dict[str, str] | None = None,
        session_id: str | None = None,
        alias: str | None = None,
        submit: bool = True,
    ) -> str:
        """Render script params and write into PTY (host scripts only on that host's session)."""
        try:
            return _dump(
                service.scripts_run(
                    get_access(),
                    script_id=script_id,
                    name=name,
                    host_id=host_id,
                    params=params,
                    session_id=session_id,
                    alias=alias,
                    submit=submit,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def groups_list(kind: str = "scripts") -> str:
        """List script/host groups visible to this client (tree via parent_id)."""
        try:
            return _dump(service.groups_list(get_access(), kind=kind))
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def groups_create(
        name: str,
        kind: str = "scripts",
        parent_id: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Create a group (host_id requires open MCP tab on that host)."""
        try:
            return _dump(
                service.groups_create(
                    get_access(),
                    name=name,
                    kind=kind,
                    parent_id=parent_id,
                    host_id=host_id,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def groups_update(
        id: str,
        name: str | None = None,
        parent_id: str | None = None,
    ) -> str:
        """Rename or reparent a group."""
        try:
            return _dump(
                service.groups_update(
                    get_access(), id=id, name=name, parent_id=parent_id
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def groups_delete(id: str) -> str:
        """Delete a group and all nested content (hosts/scripts/notes/groups)."""
        try:
            return _dump(service.groups_delete(get_access(), id=id))
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def notes_list() -> str:
        """List MCP-enabled notes (templates + host notes for open MCP tabs)."""
        try:
            return _dump(service.notes_list(get_access()))
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def notes_get(
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Get an MCP-enabled note including Markdown body."""
        try:
            return _dump(
                service.notes_get(
                    get_access(), id=id, name=name, host_id=host_id
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def notes_create(
        name: str,
        body: str = "",
        host_id: str | None = None,
        group_id: str | None = None,
    ) -> str:
        """Create a note (always MCP-enabled; no Approve)."""
        try:
            return _dump(
                service.notes_create(
                    get_access(),
                    name=name,
                    body=body,
                    host_id=host_id,
                    group_id=group_id,
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def notes_update(
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
        body: str | None = None,
        new_name: str | None = None,
        group_id: str | None = None,
    ) -> str:
        """Update note name/body/group (mcp_enabled unchanged; no Approve)."""
        try:
            kwargs: dict = {
                "id": id,
                "name": name,
                "host_id": host_id,
                "body": body,
                "new_name": new_name,
            }
            # Omit group_id when None so it is not cleared unintentionally.
            # Pass empty string to clear group.
            if group_id is not None:
                kwargs["group_id"] = group_id if group_id != "" else None
            return _dump(service.notes_update(get_access(), **kwargs))
        except McpToolError as exc:
            return _tool_error(exc)

    @mcp.tool()
    def notes_delete(
        id: str | None = None,
        name: str | None = None,
        host_id: str | None = None,
    ) -> str:
        """Delete an MCP-enabled note (no Approve)."""
        try:
            return _dump(
                service.notes_delete(
                    get_access(), id=id, name=name, host_id=host_id
                )
            )
        except McpToolError as exc:
            return _tool_error(exc)

    return mcp
