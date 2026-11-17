"""MCPServer wiring for HostsKeeper session tools."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, NoReturn, NotRequired, TypedDict

from mcp.types import ToolAnnotations
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from hostskeeper import __version__
from hostskeeper.mcp.context import get_access
from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.service import McpToolService
from hostskeeper.session.script_run_manager import (
    SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS,
    SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS,
    SCRIPT_RUN_WAIT_MAX_SEC,
)


SessionId = Annotated[
    str | None,
    Field(description="Session ID from session_list; omit when using alias or a pinned session."),
]
SessionAlias = Annotated[
    str | None,
    Field(description="Session alias from session_list; alternative to session_id."),
]
HostId = Annotated[
    str | None,
    Field(description="Host ID from a visible session or script; only visible MCP hosts are accessible."),
]
GroupId = Annotated[str | None, Field(description="Group ID from groups_list.")]
ScriptId = Annotated[str | None, Field(description="Script ID from scripts_list.")]
NoteId = Annotated[str | None, Field(description="Note ID from notes_list.")]
RunId = Annotated[str, Field(description="Run ID returned by scripts_run.")]
RequestId = Annotated[
    str,
    Field(
        description=(
            "Client-generated UUID for this launch intent. Reuse it only to safely "
            "retry the same launch request."
        )
    ),
]
Cursor = Annotated[
    str | None,
    Field(description="Cursor returned by the previous session_read/session_subscribe call."),
]


class ScriptParameterInput(TypedDict):
    name: Annotated[str, Field(description="Placeholder name used as {{name}} in the body.")]
    required: NotRequired[Annotated[bool, Field(description="Whether the caller must supply a value.")]]
    default: NotRequired[
        Annotated[str | None, Field(description="Value used when params omits this name.")]
    ]
    description: NotRequired[Annotated[str | None, Field(description="Parameter help text.")]]


_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_MUTATING = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
_DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
_PIN_SESSION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_PTY_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)
_SCRIPT_RUN = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)
_RUN_CANCEL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


_INSTRUCTIONS = (
    "HostsKeeper MCP. Call session_list first. Select a session by session_id or "
    "alias; call session_attach to pin it when multiple sessions are visible, or "
    "pass the selector to each session tool. session_info reports status and the "
    "current screen snapshot. session_read starts at the retained buffer beginning "
    "when cursor is omitted; pass its returned cursor to continue reading. "
    "session_write requires Approve and sends text to the interactive PTY; it "
    "does not report command completion. scripts_run also requires Approve, but "
    "runs only a saved, visible script on an isolated SSH exec channel and returns "
    "a run_id, not a completion result. Label it Run script: <name>; "
    "use scripts_run_wait/status for its separate bounded stdout/stderr and state. "
    "scripts_run returns replayed and current_state; reusing a request_id returns "
    "the same run and never executes it again. "
    "Do not infer script output from the shared PTY. scripts_run_cancel cannot "
    "guarantee the remote process stopped; an unconfirmed cancel remains unknown "
    "and is not reconciled later. Such runs reserve capacity until their records "
    "expire. Use session_read or session_subscribe "
    "only for the shared PTY. submit=true sends Enter; submit=false types without Enter. "
    "Use scripts_list and select a script by id before scripts_get or scripts_run. "
    "Use scripts_validate before saving or running a draft to check placeholder "
    "and parameter structure. This is static validation only; it does not execute "
    "the script, assess shell security, or guarantee compatibility with the target "
    "shell or host. If needed, explicitly ask the MCP client to call "
    "scripts_validate; tool discovery and selection are client behavior. "
    "Host-bound scripts require an MCP-enabled open tab for that host. "
    "Tool failures are returned with isError=true; use "
    "the error code and message to correct the request."
)


def _raise_tool_error(exc: McpToolError) -> NoReturn:
    message = json.dumps(exc.as_dict(), ensure_ascii=False)
    raise ToolError(message) from exc


def build_mcp_server(service: McpToolService, *, name: str = "HostsKeeper") -> MCPServer:
    mcp = MCPServer(name, version=__version__, instructions=_INSTRUCTIONS)

    @mcp.tool(annotations=_READ_ONLY)
    def session_list() -> dict[str, Any]:
        """List sessions whose MCP access is enabled for this client.

        Call first to obtain session_id and alias. Only existing UI tabs appear;
        this tool never opens an SSH connection.
        """
        try:
            return service.session_list(get_access())
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_PIN_SESSION)
    def session_attach(
        session_id: SessionId = None,
        alias: SessionAlias = None,
        tab_token: Annotated[
            str | None,
            Field(description="Legacy per-tab MCP token; normally use session_id or alias."),
        ] = None,
    ) -> dict[str, Any]:
        """Pin the default session for this MCP client.

        Choose the session_id or alias returned by session_list. For legacy
        single-tab HTTP access the token already determines the session.
        """
        try:
            return service.session_attach(
                get_access(),
                session_id=session_id,
                alias=alias,
                tab_token=tab_token,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def session_info(
        session_id: SessionId = None, alias: SessionAlias = None
    ) -> dict[str, Any]:
        """Read a session's status, visible screen snapshot, and host Notes hints.

        Select with session_id or alias, or use the session pinned by session_attach.
        Call host_profile_get to read the full Host Notes text.
        """
        try:
            return service.session_info(
                get_access(), session_id=session_id, alias=alias
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def host_profile_get(
        session_id: SessionId = None,
        alias: SessionAlias = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Read Host Notes for a host with an MCP-enabled open tab.

        Select by session_id or alias, or by a visible host_id. The result is
        free-form Notes text and contains no connection address or credentials.
        """
        try:
            return service.host_profile_get(
                get_access(),
                session_id=session_id,
                alias=alias,
                host_id=host_id,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def host_profile_set(
        profile: Annotated[
            str,
            Field(description="Full replacement text for the host's Notes field."),
        ],
        session_id: SessionId = None,
        alias: SessionAlias = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Replace Host Notes for a host with an MCP-enabled open tab.

        This overwrites the entire Notes field; obtain user consent before changing it.
        """
        try:
            return service.host_profile_set(
                get_access(),
                profile=profile,
                session_id=session_id,
                alias=alias,
                host_id=host_id,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def session_read(
        session_id: SessionId = None,
        alias: SessionAlias = None,
        cursor: Cursor = None,
        max_bytes: Annotated[
            int,
            Field(
                ge=1,
                le=1048576,
                description=(
                    "Maximum characters to return (historical parameter name says bytes); "
                    "default 65536, allowed range 1..1048576."
                ),
            ),
        ] = 65536,
    ) -> dict[str, Any]:
        """Read terminal output from a buffer cursor.

        With no cursor, reading starts at the beginning of retained output. Save
        the returned cursor and pass it to the next call; truncated=true means
        more buffered output remains.
        """
        try:
            return service.session_read(
                get_access(),
                session_id=session_id,
                alias=alias,
                cursor=cursor,
                max_bytes=max_bytes,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_PTY_WRITE)
    def session_write(
        text: Annotated[str, Field(description="Exact text to send to the session PTY.")],
        session_id: SessionId = None,
        alias: SessionAlias = None,
        submit: Annotated[
            bool,
            Field(description="When true, send Enter after the text; false types without Enter."),
        ] = True,
    ) -> dict[str, Any]:
        """Write text to an existing live session.

        Requires Approve enabled for the selected session. Success confirms that
        text was sent to the PTY; it does not mean the command completed or
        succeeded. Use session_read or session_subscribe to inspect shared output.
        """
        try:
            return service.session_write(
                get_access(),
                text=text,
                session_id=session_id,
                alias=alias,
                submit=submit,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def session_subscribe(
        session_id: SessionId = None,
        alias: SessionAlias = None,
        cursor: Cursor = None,
        timeout_sec: Annotated[
            float,
            Field(gt=0, le=300, description="Long-poll duration in seconds; default 30, maximum 300."),
        ] = 30.0,
    ) -> dict[str, Any]:
        """Wait for output or a session status change.

        Use instead of repeated rapid session_read calls. The result type is
        output (with cursor and data) or status; timeout returns empty output.
        """
        try:
            return service.session_subscribe(
                get_access(),
                session_id=session_id,
                alias=alias,
                cursor=cursor,
                timeout_sec=timeout_sec,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def scripts_list() -> dict[str, Any]:
        """List scripts visible to this client.

        Lists MCP-enabled scripts in the client's host scope. Each entry has an
        id, name, host_id (null for a template), parameters, tags, group_id,
        and mcp_enabled. Use the id to disambiguate same-name scripts, then call
        scripts_get.
        """
        try:
            return service.scripts_list(get_access())
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def scripts_get(
        id: ScriptId = None,
        name: Annotated[str | None, Field(description="Exact script name; use id when names may be duplicated.")] = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Read a script and its shell body.

        Identify by id, or by name and optionally host_id. Scripts must have
        MCP enabled; host-bound scripts also require an MCP-enabled tab for
        that host.
        """
        try:
            return service.scripts_get(
                get_access(), id=id, name=name, host_id=host_id
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def scripts_compare(
        left_script_id: Annotated[str, Field(description="First script ID from scripts_list.")],
        right_script_id: Annotated[str, Field(description="Second script ID from scripts_list.")],
    ) -> dict[str, Any]:
        """Compare two scripts visible to this client without changing either.

        Reports differences in name, description, and parameter metadata, plus a
        bounded unified diff of their bodies. Both IDs must be visible in the
        current MCP scope; unavailable and nonexistent scripts are not
        distinguished.
        """
        try:
            return service.scripts_compare(
                get_access(),
                left_script_id=left_script_id,
                right_script_id=right_script_id,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def scripts_validate(
        body: Annotated[
            str,
            Field(
                description=(
                    "Draft shell text for static placeholder analysis only; never "
                    "saved or executed. This does not assess shell security or "
                    "guarantee target-shell/host compatibility."
                )
            ),
        ],
        parameters: Annotated[
            list[ScriptParameterInput] | None,
            Field(
                description=(
                    "Placeholder declarations to check against the draft body; "
                    "this is not runtime validation."
                )
            ),
        ] = None,
        params: Annotated[
            dict[str, str] | None,
            Field(
                description=(
                    "Optional values used only to report whether placeholders are "
                    "satisfied; values are never returned. They do not prove the "
                    "script will execute successfully."
                )
            ),
        ] = None,
    ) -> dict[str, object]:
        """Statically check placeholder syntax and parameter readiness.

        The result includes placeholder names and character positions, structural
        errors, unused-parameter warnings, and missing value names. It never
        includes the body, defaults, or supplied values. It does not parse or run
        shell commands, audit their safety, or guarantee host/shell compatibility.
        Use it before saving or running a draft; explicitly request this tool if
        the MCP client does not select it automatically.
        """
        try:
            return service.scripts_validate(
                get_access(),
                body=body,
                parameters=parameters,
                params=params,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_MUTATING)
    def scripts_create(
        name: Annotated[str, Field(description="Script name; unique within its template/host scope.")],
        body: Annotated[str, Field(description="Shell text with optional {{parameter}} placeholders.")],
        description: Annotated[str | None, Field(description="Human-readable purpose of the script.")] = None,
        tags: Annotated[list[str] | None, Field(description="Search tags.")] = None,
        parameters: Annotated[
            list[ScriptParameterInput] | None,
            Field(description="Placeholder declarations; each requires name and may define required/default/description."),
        ] = None,
        host_id: HostId = None,
        group_id: GroupId = None,
    ) -> dict[str, Any]:
        """Create a reusable script template or host-bound script.

        Omit host_id for a template. A host-bound script requires an MCP-enabled
        open tab on that host. MCP-created scripts are immediately visible to MCP.
        Creating or editing scripts does not require Approve.
        """
        try:
            return service.scripts_create(
                get_access(),
                name=name,
                body=body,
                description=description,
                tags=tags,
                parameters=parameters,
                host_id=host_id,
                group_id=group_id,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def scripts_update(
        id: ScriptId = None,
        name: Annotated[str | None, Field(description="Current exact name, if id is not supplied.")] = None,
        host_id: HostId = None,
        body: Annotated[str | None, Field(description="Replacement shell body.")] = None,
        description: Annotated[str | None, Field(description="Replacement description.")] = None,
        tags: Annotated[list[str] | None, Field(description="Replacement tag list.")] = None,
        parameters: Annotated[
            list[ScriptParameterInput] | None,
            Field(description="Replacement placeholder declarations."),
        ] = None,
        new_name: Annotated[str | None, Field(description="Replacement script name.")] = None,
        group_id: Annotated[str | None, Field(description="Move to this group; empty string clears the group.")] = None,
    ) -> dict[str, Any]:
        """Update selected script fields without requiring Approve.

        Identify by id, or by name and host_id when needed. Omitted fields are
        unchanged; supplied tags/parameters replace their current lists. This
        tool does not change MCP visibility.
        """
        try:
            return service.scripts_update(
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
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def scripts_delete(
        id: ScriptId = None,
        name: Annotated[str | None, Field(description="Exact script name if id is not supplied.")] = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Delete a script from the vault.

        Prefer id to avoid ambiguity. This is irreversible and does not require
        the session Approve toggle.
        """
        try:
            return service.scripts_delete(
                get_access(), id=id, name=name, host_id=host_id
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_SCRIPT_RUN)
    def scripts_run(
        request_id: RequestId,
        script_id: ScriptId = None,
        name: Annotated[str | None, Field(description="Exact script name if script_id is not supplied.")] = None,
        host_id: HostId = None,
        params: Annotated[
            dict[str, str] | None,
            Field(description="Values for {{placeholder}} names; defaults fill omitted optional values."),
        ] = None,
        session_id: SessionId = None,
        alias: SessionAlias = None,
    ) -> dict[str, Any]:
        """Start a saved MCP-visible script in an isolated SSH exec channel.

        Requires Approve on the selected live MCP-enabled tab. Only saved scripts
        can run; arbitrary commands cannot be supplied. Host-bound scripts are
        restricted to a tab for the same host. `request_id` must be a UUID and
        makes retries idempotent. The accepted response is not an execution result;
        use scripts_run_wait/status to inspect completion and bounded output.
        The response includes `replayed` and `current_state`; a retry returns the
        same run without executing it again.
        `run_capacity` means a per-session limit of 1, a process limit of 8, or
        a retained-record limit of 100; no queue is configured. Unconfirmed runs
        reserve capacity until their records expire.
        """
        try:
            return service.scripts_run(
                get_access(),
                request_id=request_id,
                script_id=script_id,
                name=name,
                host_id=host_id,
                params=params,
                session_id=session_id,
                alias=alias,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def scripts_run_status(
        run_id: RunId,
        session_id: SessionId = None,
        alias: SessionAlias = None,
    ) -> dict[str, Any]:
        """Read a saved script run's lifecycle metadata.

        The run's original session must still be visible to this client. Approve
        is not required for status; use session_id/alias when a session selector
        is needed.
        """
        try:
            return service.scripts_run_status(
                get_access(),
                run_id=run_id,
                session_id=session_id,
                alias=alias,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def scripts_run_wait(
        run_id: RunId,
        session_id: SessionId = None,
        alias: SessionAlias = None,
        timeout_sec: Annotated[
            float,
            Field(
                ge=0,
                le=SCRIPT_RUN_WAIT_MAX_SEC,
                description=(
                    f"Maximum wait in seconds; default {SCRIPT_RUN_WAIT_MAX_SEC:g}, "
                    f"allowed range 0..{SCRIPT_RUN_WAIT_MAX_SEC:g}."
                ),
            ),
        ] = SCRIPT_RUN_WAIT_MAX_SEC,
        stdout_cursor: Annotated[
            str | None,
            Field(description="Cursor from the previous stdout chunk; omit to read from the beginning."),
        ] = None,
        stderr_cursor: Annotated[
            str | None,
            Field(description="Cursor from the previous stderr chunk; omit to read from the beginning."),
        ] = None,
        max_chars: Annotated[
            int,
            Field(
                ge=1,
                le=SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS,
                description=(
                    "Combined stdout/stderr characters to return; default "
                    f"{SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS}, maximum "
                    f"{SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS}."
                ),
            ),
        ] = SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS,
    ) -> dict[str, Any]:
        """Wait briefly for run state/output changes and return bounded new output.

        A wait timeout does not change run state. stdout and stderr have separate
        cursors. This tool is read-only and does not require Approve.
        """
        try:
            return service.scripts_run_wait(
                get_access(),
                run_id=run_id,
                session_id=session_id,
                alias=alias,
                timeout_sec=timeout_sec,
                stdout_cursor=stdout_cursor,
                stderr_cursor=stderr_cursor,
                max_chars=max_chars,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_RUN_CANCEL)
    def scripts_run_cancel(
        run_id: RunId,
        session_id: SessionId = None,
        alias: SessionAlias = None,
    ) -> dict[str, Any]:
        """Request cancellation of a script run without using the shared PTY.

        Closing the local SSH channel does not prove that the remote process
        stopped; the record remains unknown with process_may_continue=true and
        is not reconciled later. Unconfirmed runs reserve capacity until record
        expiry.
        This request does not require Approve but remains scoped to the original
        MCP-enabled session.
        """
        try:
            return service.scripts_run_cancel(
                get_access(),
                run_id=run_id,
                session_id=session_id,
                alias=alias,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def groups_list(
        kind: Annotated[
            Literal["scripts", "hosts"],
            Field(description="Group tree to list; defaults to scripts."),
        ] = "scripts",
    ) -> dict[str, Any]:
        """List visible groups as a tree using parent_id.

        kind is scripts or hosts; host-local script groups require a visible
        MCP-enabled tab for that host.
        """
        try:
            return service.groups_list(get_access(), kind=kind)
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_MUTATING)
    def groups_create(
        name: Annotated[str, Field(description="Name of the new group.")],
        kind: Annotated[
            str,
            Field(description="Group tree: scripts or hosts; default scripts."),
        ] = "scripts",
        parent_id: GroupId = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Create a group in the selected tree.

        For a host-local scripts group, provide host_id and keep an MCP-enabled
        tab open for that host. parent_id nests the new group.
        """
        try:
            return service.groups_create(
                get_access(),
                name=name,
                kind=kind,
                parent_id=parent_id,
                host_id=host_id,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def groups_update(
        id: Annotated[str, Field(description="Group ID from groups_list.")],
        name: Annotated[str | None, Field(description="Replacement group name.")] = None,
        parent_id: Annotated[
            str | None,
            Field(description="New parent group ID; empty string moves the group to the root."),
        ] = None,
    ) -> dict[str, Any]:
        """Rename or move a group in its existing tree."""
        try:
            return service.groups_update(
                get_access(), id=id, name=name, parent_id=parent_id
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def groups_delete(
        id: Annotated[str, Field(description="Group ID from groups_list.")]
    ) -> dict[str, Any]:
        """Recursively delete a group and all nested content.

        This can delete nested groups, hosts, scripts, and notes; inspect the
        target group before calling.
        """
        try:
            return service.groups_delete(get_access(), id=id)
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def notes_list() -> dict[str, Any]:
        """List MCP-enabled notes visible to this client.

        Includes templates and host-local notes for hosts with open MCP-enabled tabs.
        """
        try:
            return service.notes_list(get_access())
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_READ_ONLY)
    def notes_get(
        id: NoteId = None,
        name: Annotated[str | None, Field(description="Exact note name if id is not supplied.")] = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Read an MCP-enabled note and its Markdown body.

        Identify by id, or by name and optionally host_id to resolve duplicates.
        """
        try:
            return service.notes_get(
                get_access(), id=id, name=name, host_id=host_id
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_MUTATING)
    def notes_create(
        name: Annotated[str, Field(description="Note name; unique within its template/host scope.")],
        body: Annotated[str, Field(description="Markdown text for the note.")] = "",
        host_id: HostId = None,
        group_id: GroupId = None,
    ) -> dict[str, Any]:
        """Create an MCP-enabled Markdown note.

        Omit host_id for a template. Host-local notes require an MCP-enabled open
        tab for that host. This vault edit does not require session Approve.
        """
        try:
            return service.notes_create(
                get_access(),
                name=name,
                body=body,
                host_id=host_id,
                group_id=group_id,
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def notes_update(
        id: NoteId = None,
        name: Annotated[str | None, Field(description="Current exact note name if id is not supplied.")] = None,
        host_id: HostId = None,
        body: Annotated[str | None, Field(description="Replacement Markdown body.")] = None,
        new_name: Annotated[str | None, Field(description="Replacement note name.")] = None,
        group_id: Annotated[str | None, Field(description="Move to this group; empty string clears the group.")] = None,
    ) -> dict[str, Any]:
        """Update note content, name, or group without changing mcp_enabled.

        Identify by id, or by name and host_id when needed. Omitted fields are
        unchanged; this vault edit does not require session Approve.
        """
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
            return service.notes_update(get_access(), **kwargs)
        except McpToolError as exc:
            _raise_tool_error(exc)

    @mcp.tool(annotations=_DESTRUCTIVE)
    def notes_delete(
        id: NoteId = None,
        name: Annotated[str | None, Field(description="Exact note name if id is not supplied.")] = None,
        host_id: HostId = None,
    ) -> dict[str, Any]:
        """Delete an MCP-enabled note from the vault.

        Prefer id to avoid ambiguity. This edit does not require session Approve.
        """
        try:
            return service.notes_delete(
                get_access(), id=id, name=name, host_id=host_id
            )
        except McpToolError as exc:
            _raise_tool_error(exc)

    return mcp
