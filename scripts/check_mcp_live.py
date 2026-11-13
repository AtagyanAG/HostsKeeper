"""Live MCP checks against local HostsKeeper HTTP MCP (token via HS_MCP_TOKEN)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


async def _session(url: str):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as streams:
        if hasattr(streams, "read"):
            read, write = streams.read, streams.write
        else:
            read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call(tool: str, arguments: dict) -> dict:
    key = (
        os.environ.get("HS_MCP_KEY")
        or os.environ.get("HOSTSKEEPER_MCP_KEY")
        or os.environ.get("HOSTSSAFE_MCP_KEY")
        or ""
    )
    token = os.environ.get("HS_MCP_TOKEN", "")
    if key:
        url = f"http://127.0.0.1:8765/mcp?key={key}"
    elif token:
        url = f"http://127.0.0.1:8765/mcp?token={token}"
    else:
        raise SystemExit(
            "HS_MCP_KEY (or HOSTSKEEPER_MCP_KEY) or HS_MCP_TOKEN required"
        )
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as streams:
        read, write = (
            (streams.read, streams.write)
            if hasattr(streams, "read")
            else (streams[0], streams[1])
        )
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            text = "".join(getattr(b, "text", "") for b in result.content)
            return json.loads(text)


async def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "info"
    if mode == "info":
        data = await call("session_info", {})
        blob = json.dumps(data)
        print("INFO_ALIAS=" + str(data.get("alias")))
        print("INFO_STATUS=" + str(data.get("status")))
        print("INFO_NO_IP=" + str(_IPV4.search(blob) is None))
        print("INFO_NO_KEYMAT=" + str(("BEGIN" not in blob) and ("private_key" not in blob)))
        return 0
    if mode == "write":
        marker = os.environ.get("HS_MARKER", "marker")
        data = await call("session_write", {"text": f"echo {marker}", "submit": True})
        print("WRITE_JSON=" + json.dumps(data, ensure_ascii=False))
        return 0
    if mode == "scripts":
        created = await call(
            "scripts_create",
            {
                "name": "check-say",
                "body": "echo hostskeeper-{{tag}}",
                "parameters": [{"name": "tag", "required": True}],
            },
        )
        print("SCRIPT_NAME=" + str(created.get("name")))
        marker = os.environ.get("HS_MARKER", "scripts-live")
        ran = await call(
            "scripts_run",
            {"name": "check-say", "params": {"tag": marker}, "submit": True},
        )
        print("SCRIPT_RUN=" + json.dumps(ran, ensure_ascii=False))
        deleted = await call("scripts_delete", {"name": "check-say"})
        print("SCRIPT_DEL=" + json.dumps(deleted, ensure_ascii=False))
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print("ERROR=" + type(exc).__name__ + ":" + str(exc)[:400])
        raise SystemExit(2)
