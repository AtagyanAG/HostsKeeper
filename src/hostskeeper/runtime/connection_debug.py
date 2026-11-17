"""Opt-in timing records for embedded SSH tab connections."""

from __future__ import annotations

import threading
import time
from uuid import uuid4

from hostskeeper.runtime.tree_debug_log import log


class ConnectionTrace:
    def __init__(self, operation: str) -> None:
        self._operation = operation
        self._attempt_id = uuid4().hex[:8]
        self._started = time.perf_counter()
        self._lock = threading.Lock()
        self._first_output_recorded = False
        self._record("request", "started")

    def stage(self, name: str, duration_ms: float, status: str) -> None:
        self._record(
            name,
            status,
            stage_ms=round(duration_ms, 1),
        )

    def milestone(self, name: str, status: str = "reached") -> None:
        self._record(name, status)

    def first_pty_output(self) -> None:
        with self._lock:
            if self._first_output_recorded:
                return
            self._first_output_recorded = True
        self._record("first_pty_output", "received")

    def _record(
        self,
        stage: str,
        status: str,
        *,
        stage_ms: float | None = None,
    ) -> None:
        with self._lock:
            total_ms = (time.perf_counter() - self._started) * 1000
            fields: dict[str, object] = {
                "attempt": self._attempt_id,
                "operation": self._operation,
                "status": status,
                "total_ms": round(total_ms, 1),
            }
            if stage_ms is not None:
                fields["stage_ms"] = stage_ms
            log("connection_timing", stage, **fields)
