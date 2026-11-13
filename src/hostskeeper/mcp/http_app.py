"""Streamable HTTP ASGI app: app key (gateway) or legacy per-tab token."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount
from starlette.types import ASGIApp

from hostskeeper.mcp.context import set_access
from hostskeeper.mcp.errors import McpToolError
from hostskeeper.mcp.server import build_mcp_server
from hostskeeper.mcp.service import McpAccess, McpToolService


def _header(request: Request, *names: str) -> str | None:
    for name in names:
        value = request.headers.get(name)
        if value:
            return value.strip()
    return None


def _extract_app_key(request: Request) -> str | None:
    key = request.query_params.get("key")
    if key:
        return key
    header = _header(request, "x-hostskeeper-key", "x-hostssafe-key")
    if header:
        return header
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def _client_id(request: Request) -> str:
    # Prefer MCP streamable session id so gateway pins survive multipartite HTTP.
    return (
        request.headers.get("mcp-session-id")
        or _header(request, "x-hostskeeper-client-id", "x-hostssafe-client-id")
        or str(uuid.uuid4())
    )


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, service: McpToolService) -> None:
        super().__init__(app)
        self._service = service

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        token = request.query_params.get("token")
        app_key = _extract_app_key(request)
        client_id = _client_id(request)

        if token:
            try:
                self._service.bind_http_client(token, client_id)
            except McpToolError as exc:
                status = 409 if exc.code == "client_busy" else 401
                return JSONResponse(exc.as_dict(), status_code=status)
            set_access(
                McpAccess(
                    mode="http",
                    token=token,
                    client_id=client_id,
                    gateway=False,
                )
            )
            request.state.hostskeeper_token = token
            request.state.hostskeeper_client_id = client_id
            request.state.hostskeeper_gateway = False
            try:
                return await call_next(request)
            finally:
                # Hold slot across multipartite MCP HTTP session when requested.
                hold = _header(request, "x-hostskeeper-hold", "x-hostssafe-hold")
                if hold != "1":
                    self._service.unbind_http_client(token, client_id)

        if self._service.check_app_key(app_key):
            set_access(
                McpAccess(
                    mode="http",
                    token=None,
                    client_id=client_id,
                    gateway=True,
                )
            )
            request.state.hostskeeper_client_id = client_id
            request.state.hostskeeper_gateway = True
            return await call_next(request)

        return JSONResponse(
            {
                "error": "unauthorized",
                "message": "app key (?key= / X-HostsKeeper-Key) or tab token (?token=) required",
            },
            status_code=401,
        )


def create_http_app(
    service: McpToolService,
    *,
    host: str = "0.0.0.0",
) -> Starlette:
    """Build Streamable HTTP ASGI app.

    ``host`` must match the uvicorn bind address. MCP SDK auto-enables DNS
    rebinding protection (localhost-only Host allowlist) when ``host`` is
    127.0.0.1/localhost — that rejects LAN clients with Host: <lan-ip>:port.
    Binding ``0.0.0.0`` keeps protection off (auth is app key / tab token).
    """
    mcp = build_mcp_server(service)
    inner = mcp.streamable_http_app(host=host)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/", app=inner)], lifespan=lifespan)
    app.add_middleware(AuthMiddleware, service=service)
    app.state.mcp = mcp
    app.state.service = service
    return app


def run_http(
    service: McpToolService,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
) -> None:
    import uvicorn

    uvicorn.run(
        create_http_app(service, host=host), host=host, port=port, log_level="info"
    )
