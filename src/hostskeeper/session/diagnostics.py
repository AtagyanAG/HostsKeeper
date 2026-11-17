"""Optional timing hooks for interactive session connection stages."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

ConnectionStageCallback = Callable[[str, float, str], None]
FirstOutputCallback = Callable[[], None]


@contextmanager
def measure_stage(
    callback: ConnectionStageCallback | None,
    stage: str,
) -> Iterator[None]:
    if callback is None:
        yield
        return

    started = time.perf_counter()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "failed"
        raise
    finally:
        callback(stage, (time.perf_counter() - started) * 1000, status)
