"""Background MCP HTTP (Streamable) server for Cursor/LAN."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from hostskeeper.mcp.http_app import create_http_app
from hostskeeper.mcp.service import McpToolService
from hostskeeper.runtime.stdio_fix import ensure_stdio

if TYPE_CHECKING:
    from uvicorn import Server

# Plain loggers — avoid uvicorn ColorFormatter / isatty on windowed exe.
_UVICORN_LOG_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "logging.Formatter",
            "fmt": "%(levelname)s:     %(message)s",
        },
        "access": {
            "()": "logging.Formatter",
            "fmt": "%(levelname)s:     %(message)s",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.NullHandler",
        },
        "access": {
            "formatter": "access",
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "uvicorn.error": {
            "handlers": ["default"],
            "level": "WARNING",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["access"],
            "level": "WARNING",
            "propagate": False,
        },
    },
}


class McpHttpRuntime:
    """Embeds uvicorn.Server in a daemon thread; stoppable from the UI thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._server: Server | None = None
        self._started_for: int | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_started(self, service: McpToolService, host: str, port: int) -> None:
        with self._lock:
            key = id(service)
            if self.running and self._started_for == key:
                return
            if self.running:
                # Different service (re-unlock) — stop old listener first.
                self._stop_locked(timeout=5.0)

            import uvicorn

            ensure_stdio()
            config = uvicorn.Config(
                create_http_app(service, host=host),
                host=host,
                port=port,
                log_level="warning",
                log_config=_UVICORN_LOG_CONFIG,
            )
            server = uvicorn.Server(config)
            self._server = server
            self._started_for = key

            def _run() -> None:
                server.run()

            self._thread = threading.Thread(
                target=_run, name="hostskeeper-mcp-http", daemon=True
            )
            self._thread.start()

        # Brief wait so bind failures surface early for callers that care.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if self._server is not None and self._server.started:
                return
            if not self.running:
                return
            time.sleep(0.05)

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            self._stop_locked(timeout=timeout)

    def _stop_locked(self, timeout: float) -> None:
        server = self._server
        thread = self._thread
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._server = None
        self._thread = None
        self._started_for = None


_default_runtime = McpHttpRuntime()


def ensure_mcp_http(service: McpToolService, host: str, port: int) -> McpHttpRuntime:
    _default_runtime.ensure_started(service, host, port)
    return _default_runtime


def stop_mcp_http(timeout: float = 5.0) -> None:
    _default_runtime.stop(timeout=timeout)
