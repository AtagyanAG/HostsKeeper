"""MCP protocol metadata and tool result shape."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.responses import Response
from starlette.testclient import TestClient

from hostskeeper import __version__
from hostskeeper.mcp.http_app import create_http_app
from hostskeeper.mcp.service import McpToolService
from hostskeeper.session import SessionManager
from hostskeeper.vault import Vault


APP_KEY = "protocol-test-key"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _event_payload(response: Response) -> dict[str, Any]:
    data = next(
        line.removeprefix("data: ")
        for line in response.text.splitlines()
        if line.startswith("data: ")
    )
    return json.loads(data)


def test_streamable_http_metadata_errors_and_structured_results(
    tmp_path: Path,
) -> None:
    vault = Vault.create(tmp_path / "protocol.vault", "test-pass")
    service = McpToolService(SessionManager(vault), vault, app_key=APP_KEY)

    with TestClient(create_http_app(service)) as client:
        initialized = client.post(
            "/mcp?key=protocol-test-key",
            headers=HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        session_id = initialized.headers["mcp-session-id"]
        init_result = _event_payload(initialized)["result"]
        assert init_result["instructions"]
        assert "static validation only" in init_result["instructions"]
        assert "tool discovery and selection are client behavior" in init_result["instructions"]
        assert "duplicate display, not a second execution" in init_result["instructions"]
        assert "do not report the mirrored text as a separate result" in init_result["instructions"]
        assert init_result["serverInfo"]["version"] == __version__

        request_headers = {**HEADERS, "Mcp-Session-Id": session_id}
        notification = client.post(
            "/mcp?key=protocol-test-key",
            headers=request_headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert notification.status_code == 202
        assert notification.content == b""

        listed = client.post(
            "/mcp?key=protocol-test-key",
            headers=request_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        tools = _event_payload(listed)["result"]["tools"]
        assert all(tool["description"] for tool in tools)
        assert all(
            "description" in property_schema
            for tool in tools
            for property_schema in tool["inputSchema"].get("properties", {}).values()
        )
        by_name = {tool["name"]: tool for tool in tools}
        groups_description = " ".join(
            by_name["groups_list"]["description"].split()
        )
        run_description = " ".join(by_name["scripts_run"]["description"].split())
        read_description = " ".join(by_name["session_read"]["description"].split())
        subscribe_description = " ".join(
            by_name["session_subscribe"]["description"].split()
        )
        assert {
            "scripts_run",
            "scripts_run_status",
            "scripts_run_wait",
            "scripts_run_cancel",
        } <= by_name.keys()
        assert by_name["session_list"]["outputSchema"]["type"] == "object"
        assert by_name["session_list"]["annotations"]["readOnlyHint"] is True
        assert by_name["scripts_compare"]["annotations"]["readOnlyHint"] is True
        assert by_name["scripts_validate"]["annotations"]["readOnlyHint"] is True
        assert "groups containing MCP-accessible hosts" in groups_description
        validate_description = by_name["scripts_validate"]["description"].lower()
        assert "statically check" in validate_description
        assert "does not parse or run" in validate_description
        assert "explicitly request" in validate_description
        assert by_name["groups_delete"]["annotations"]["destructiveHint"] is True
        run_tool = by_name["scripts_run"]
        assert "mirrored into the shared session buffer" in run_description
        assert "not a second execution" in run_description
        assert "source of truth" in run_description
        assert "mirrored saved-script transcripts" in read_description
        assert "not a separate execution" in read_description
        assert "mirrored here" in subscribe_description
        assert "request_id" in run_tool["inputSchema"]["required"]
        assert "submit" not in run_tool["inputSchema"]["properties"]
        assert run_tool["annotations"]["destructiveHint"] is True
        assert run_tool["annotations"]["idempotentHint"] is True
        assert by_name["scripts_run_status"]["annotations"]["readOnlyHint"] is True
        wait_properties = by_name["scripts_run_wait"]["inputSchema"]["properties"]
        assert wait_properties["timeout_sec"]["maximum"] == 30
        assert wait_properties["max_chars"]["maximum"] == 65536
        assert by_name["scripts_run_cancel"]["annotations"]["readOnlyHint"] is False

        success = client.post(
            "/mcp?key=protocol-test-key",
            headers=request_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "session_list", "arguments": {}},
            },
        )
        success_result = _event_payload(success)["result"]
        assert success_result["isError"] is False
        assert success_result["structuredContent"] == {"sessions": []}

        failure = client.post(
            "/mcp?key=protocol-test-key",
            headers=request_headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "scripts_get", "arguments": {}},
            },
        )
        failure_result = _event_payload(failure)["result"]
        assert failure_result["isError"] is True
        assert "invalid_args" in failure_result["content"][0]["text"]
        assert "Traceback" not in failure_result["content"][0]["text"]

        validation = client.post(
            "/mcp?key=protocol-test-key",
            headers=request_headers,
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "scripts_validate",
                    "arguments": {
                        "body": "echo {{token}}",
                        "parameters": [
                            {
                                "name": "token",
                                "required": True,
                                "default": "sensitive-default",
                            }
                        ],
                        "params": {"token": "sensitive-input"},
                    },
                },
            },
        )
        validation_result = _event_payload(validation)["result"]
        assert validation_result["isError"] is False
        assert validation_result["structuredContent"]["ready_to_run"] is True
        assert "sensitive-default" not in validation.text
        assert "sensitive-input" not in validation.text

        unknown = client.post(
            "/mcp?key=protocol-test-key",
            headers=request_headers,
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "not_a_tool", "arguments": {}},
            },
        )
        unknown_result = _event_payload(unknown)["result"]
        assert unknown_result["isError"] is True
        assert "Unknown tool" in unknown_result["content"][0]["text"]
