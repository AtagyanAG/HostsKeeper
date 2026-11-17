"""In-memory lifecycle and bounded output capture for isolated script runs."""

from __future__ import annotations

import codecs
import threading
import time
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Callable
from uuid import UUID, uuid4

import paramiko

from hostskeeper.session.buffer import BufferRead, OutputBuffer
from hostskeeper.session.script_runs import (
    SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM,
    ScriptRunErrorCode,
    ScriptRunInfo,
    ScriptRunOrigin,
    ScriptRunOutputInfo,
    ScriptRunState,
)

SCRIPT_RUN_EXECUTION_TIMEOUT_SEC = 600.0
SCRIPT_RUN_MAX_ACTIVE_PER_SESSION = 1
SCRIPT_RUN_MAX_ACTIVE_PROCESS = 8
SCRIPT_RUN_MAX_RECORDS = 100
SCRIPT_RUN_RETENTION = timedelta(hours=24)
SCRIPT_RUN_WAIT_MAX_SEC = 30.0
SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS = 65_536
SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS = 16_384

_ACTIVE_STATES = {
    ScriptRunState.STARTING,
    ScriptRunState.RUNNING,
    ScriptRunState.CANCEL_REQUESTED,
}
_CAPACITY_STATES = _ACTIVE_STATES | {
    ScriptRunState.SESSION_LOST,
    ScriptRunState.EXECUTION_TIMED_OUT,
    ScriptRunState.UNKNOWN,
}
_MAX_CHANNEL_READ_BYTES_PER_CYCLE = 65_536
_TERMINAL_STATES = {
    ScriptRunState.SUCCEEDED,
    ScriptRunState.FAILED,
    ScriptRunState.CANCELLED,
    ScriptRunState.SESSION_LOST,
    ScriptRunState.EXECUTION_TIMED_OUT,
    ScriptRunState.UNKNOWN,
    ScriptRunState.NOT_SUPPORTED,
}


class ScriptRunNotFoundError(Exception):
    """Run does not belong to the requested session or is no longer retained."""


class ScriptRunCapacityError(Exception):
    """A fixed v1 run or retention limit has been reached."""


@dataclass(frozen=True)
class ScriptRunSnapshot:
    info: ScriptRunInfo
    stdout: BufferRead
    stderr: BufferRead
    wait_timed_out: bool = False


class _BoundedOutputBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._chunks: list[str] = []
        self._size = 0
        self._truncated = False

    def append(self, text: str) -> str:
        if not text:
            return ""
        with self._lock:
            remaining = SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM - self._size
            kept = text[:remaining]
            if kept:
                self._chunks.append(kept)
                self._size += len(kept)
            if len(kept) != len(text):
                self._truncated = True
            return kept

    def read_since(self, cursor: str | None, max_chars: int) -> BufferRead:
        start = self._parse_cursor(cursor)
        with self._lock:
            text = "".join(self._chunks)
            start = min(start, len(text))
            piece = text[start : start + max_chars]
            end = start + len(piece)
            return BufferRead(
                data=piece,
                cursor=str(end),
                truncated=end < len(text),
            )

    @property
    def size(self) -> int:
        with self._lock:
            return self._size

    @property
    def truncated(self) -> bool:
        with self._lock:
            return self._truncated

    @staticmethod
    def _parse_cursor(cursor: str | None) -> int:
        if cursor is None or cursor == "":
            return 0
        try:
            value = int(cursor)
        except ValueError as exc:
            raise ValueError("invalid output cursor") from exc
        if value < 0:
            raise ValueError("invalid output cursor")
        return value


@dataclass
class _ScriptRunRecord:
    info: ScriptRunInfo
    display_name: str
    display_buffer: OutputBuffer | None
    stdout: _BoundedOutputBuffer = field(default_factory=_BoundedOutputBuffer)
    stderr: _BoundedOutputBuffer = field(default_factory=_BoundedOutputBuffer)
    display_output_truncation_notified: bool = False
    display_last_char_was_cr: bool = False
    channel: paramiko.Channel | None = None
    session_alive: Callable[[], bool] = lambda: False
    deadline: float | None = None
    sequence: int = 0
    stdout_decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
    )
    stderr_decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
    )


class ScriptRunManager:
    """Runs saved script bodies on separate SSH channels and retains safe records."""

    def __init__(
        self,
        *,
        execution_timeout_sec: float = SCRIPT_RUN_EXECUTION_TIMEOUT_SEC,
    ) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._records: dict[UUID, _ScriptRunRecord] = {}
        self._request_index: dict[tuple[UUID, UUID], UUID] = {}
        self._execution_timeout_sec = execution_timeout_sec

    def find_by_request(
        self, session_id: UUID, request_id: UUID
    ) -> ScriptRunInfo | None:
        with self._condition:
            self._prune_expired()
            run_id = self._request_index.get((session_id, request_id))
            record = self._records.get(run_id) if run_id is not None else None
            return self._info_snapshot(record) if record is not None else None

    def start(
        self,
        *,
        session_id: UUID,
        script_id: UUID,
        request_id: UUID,
        origin: ScriptRunOrigin,
        command: str,
        open_channel: Callable[[str], paramiko.Channel],
        session_alive: Callable[[], bool],
        display_name: str = "script",
        display_buffer: OutputBuffer | None = None,
    ) -> ScriptRunInfo:
        key = (session_id, request_id)
        with self._condition:
            self._prune_expired()
            existing_id = self._request_index.get(key)
            if existing_id is not None:
                return self._info_snapshot(self._records[existing_id])
            if len(self._records) >= SCRIPT_RUN_MAX_RECORDS:
                raise ScriptRunCapacityError
            if self._capacity_count(session_id=session_id) >= SCRIPT_RUN_MAX_ACTIVE_PER_SESSION:
                raise ScriptRunCapacityError
            if self._capacity_count() >= SCRIPT_RUN_MAX_ACTIVE_PROCESS:
                raise ScriptRunCapacityError

            now = _utcnow()
            info = ScriptRunInfo(
                run_id=uuid4(),
                request_id=request_id,
                session_id=session_id,
                script_id=script_id,
                origin=origin,
                state=ScriptRunState.STARTING,
                accepted_at=now,
                updated_at=now,
            )
            record = _ScriptRunRecord(
                info=info,
                display_name=_safe_display_name(display_name),
                display_buffer=display_buffer,
                session_alive=session_alive,
            )
            self._records[info.run_id] = record
            self._request_index[key] = info.run_id
            self._changed(record)

        if record.display_buffer is not None:
            initiator = (
                "user"
                if record.info.origin == ScriptRunOrigin.USER_INTERFACE
                else "MCP client"
            )
            _append_display_text(
                record,
                "\r\n"
                f"[HostsKeeper] Run script: {record.display_name} "
                f"[{record.info.run_id}] - starting (initiator: {initiator})\r\n",
            )

        try:
            channel = open_channel(command)
        except Exception:
            self._finish_uncertain(
                record, ScriptRunState.UNKNOWN, ScriptRunErrorCode.START_FAILED
            )
            return self.get(session_id, record.info.run_id)

        with self._condition:
            if record.info.state != ScriptRunState.STARTING:
                _close_channel(channel)
                return self._info_snapshot(record)
            record.channel = channel
            now = max(_utcnow(), record.info.updated_at)
            record.deadline = time.monotonic() + self._execution_timeout_sec
            record.info = replace(
                record.info,
                state=ScriptRunState.RUNNING,
                started_at=now,
                updated_at=now,
            )
            self._changed(record)

        worker = threading.Thread(
            target=self._read_channel,
            args=(record,),
            name="hostskeeper-script-run",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            self._finish_uncertain(
                record, ScriptRunState.UNKNOWN, ScriptRunErrorCode.UNKNOWN
            )
        return self.get(session_id, record.info.run_id)

    def get(self, session_id: UUID, run_id: UUID) -> ScriptRunInfo:
        with self._condition:
            return self._info_snapshot(self._require(session_id, run_id))

    def read_output(
        self,
        session_id: UUID,
        run_id: UUID,
        *,
        stdout_cursor: str | None = None,
        stderr_cursor: str | None = None,
        max_chars: int = SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS,
    ) -> ScriptRunSnapshot:
        budget = self._validate_output_budget(max_chars)
        with self._condition:
            record = self._require(session_id, run_id)
            return self._snapshot(
                record,
                stdout_cursor=stdout_cursor,
                stderr_cursor=stderr_cursor,
                max_chars=budget,
            )

    def wait(
        self,
        session_id: UUID,
        run_id: UUID,
        *,
        timeout_sec: float = SCRIPT_RUN_WAIT_MAX_SEC,
        stdout_cursor: str | None = None,
        stderr_cursor: str | None = None,
        max_chars: int = SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS,
    ) -> ScriptRunSnapshot:
        if (
            isinstance(timeout_sec, bool)
            or not isinstance(timeout_sec, (int, float))
            or not isfinite(timeout_sec)
            or not 0 <= timeout_sec <= SCRIPT_RUN_WAIT_MAX_SEC
        ):
            raise ValueError("timeout_sec is outside the configured limit")
        timeout = float(timeout_sec)
        budget = self._validate_output_budget(max_chars)
        with self._condition:
            record = self._require(session_id, run_id)
            initial_sequence = record.sequence
            woke = self._condition.wait_for(
                lambda: (
                    record.sequence != initial_sequence
                    or self._has_output_after(record, stdout_cursor, stderr_cursor)
                    or record.info.state in _TERMINAL_STATES
                ),
                timeout=timeout,
            )
            return self._snapshot(
                record,
                stdout_cursor=stdout_cursor,
                stderr_cursor=stderr_cursor,
                max_chars=budget,
                wait_timed_out=not woke,
            )

    def cancel(self, session_id: UUID, run_id: UUID) -> ScriptRunInfo:
        with self._condition:
            record = self._require(session_id, run_id)
            if record.info.state not in _ACTIVE_STATES:
                return self._info_snapshot(record)
            channel = record.channel
            self._set_state(
                record,
                ScriptRunState.UNKNOWN,
                error_code=ScriptRunErrorCode.CANCEL_UNCONFIRMED,
            )
        if channel is not None:
            _close_channel(channel)
        return self.get(session_id, run_id)

    def on_execution_access_revoked(self, session_id: UUID) -> None:
        self._mark_uncertain(
            session_id,
            ScriptRunErrorCode.CANCEL_UNCONFIRMED,
        )

    def on_session_lost(self, session_id: UUID) -> None:
        self._mark_uncertain(session_id, ScriptRunErrorCode.SESSION_LOST)

    def _mark_uncertain(
        self,
        session_id: UUID,
        error_code: ScriptRunErrorCode,
    ) -> None:
        with self._condition:
            records = [
                record
                for record in self._records.values()
                if record.info.session_id == session_id
                and record.info.state in _ACTIVE_STATES
            ]
            channels = [record.channel for record in records]
            for record in records:
                state = (
                    ScriptRunState.SESSION_LOST
                    if error_code == ScriptRunErrorCode.SESSION_LOST
                    else ScriptRunState.UNKNOWN
                )
                self._set_state(record, state, error_code=error_code)
        for channel in channels:
            if channel is not None:
                _close_channel(channel)

    def _read_channel(self, record: _ScriptRunRecord) -> None:
        channel = record.channel
        if channel is None:
            return
        try:
            while True:
                if not self._is_running(record):
                    return
                self._drain_channel(record, channel)
                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    self._drain_channel(record, channel)
                    if channel.recv_ready() or channel.recv_stderr_ready():
                        continue
                    exit_code = channel.recv_exit_status()
                    self._flush_decoders(record)
                    if exit_code < 0:
                        if record.session_alive():
                            self._finish_uncertain(
                                record,
                                ScriptRunState.UNKNOWN,
                                ScriptRunErrorCode.UNKNOWN,
                            )
                        else:
                            self._finish_uncertain(
                                record,
                                ScriptRunState.SESSION_LOST,
                                ScriptRunErrorCode.SESSION_LOST,
                            )
                    else:
                        self._finish_with_exit_code(record, exit_code)
                    return
                if not channel.active or channel.closed:
                    self._flush_decoders(record)
                    if record.session_alive():
                        self._finish_uncertain(
                            record,
                            ScriptRunState.UNKNOWN,
                            ScriptRunErrorCode.UNKNOWN,
                        )
                    else:
                        self._finish_uncertain(
                            record,
                            ScriptRunState.SESSION_LOST,
                            ScriptRunErrorCode.SESSION_LOST,
                        )
                    return
                if record.deadline is not None and time.monotonic() >= record.deadline:
                    self._finish_uncertain(
                        record,
                        ScriptRunState.EXECUTION_TIMED_OUT,
                        ScriptRunErrorCode.EXECUTION_TIMEOUT,
                    )
                    return
                time.sleep(0.02)
        except Exception:
            self._finish_uncertain(
                record,
                ScriptRunState.UNKNOWN,
                ScriptRunErrorCode.UNKNOWN,
            )

    def _drain_channel(
        self, record: _ScriptRunRecord, channel: paramiko.Channel
    ) -> None:
        changed = False
        stdout_bytes = 0
        while (
            channel.recv_ready()
            and stdout_bytes < _MAX_CHANNEL_READ_BYTES_PER_CYCLE
        ):
            data = channel.recv(
                min(4096, _MAX_CHANNEL_READ_BYTES_PER_CYCLE - stdout_bytes)
            )
            if not data:
                break
            stdout_bytes += len(data)
            stream_changed = self._append_stream_output(
                record,
                record.stdout,
                record.stdout_decoder.decode(data, final=False),
            )
            changed = changed or stream_changed
        stderr_bytes = 0
        while (
            channel.recv_stderr_ready()
            and stderr_bytes < _MAX_CHANNEL_READ_BYTES_PER_CYCLE
        ):
            data = channel.recv_stderr(
                min(4096, _MAX_CHANNEL_READ_BYTES_PER_CYCLE - stderr_bytes)
            )
            if not data:
                break
            stderr_bytes += len(data)
            stream_changed = self._append_stream_output(
                record,
                record.stderr,
                record.stderr_decoder.decode(data, final=False),
            )
            changed = changed or stream_changed
        if changed:
            with self._condition:
                if record.info.state in _ACTIVE_STATES:
                    self._update_output(record)

    def _flush_decoders(self, record: _ScriptRunRecord) -> None:
        stdout_tail = _sanitize_output(record.stdout_decoder.decode(b"", final=True))
        stderr_tail = _sanitize_output(record.stderr_decoder.decode(b"", final=True))
        stdout_changed = self._append_stream_output(
            record, record.stdout, stdout_tail
        )
        stderr_changed = self._append_stream_output(
            record, record.stderr, stderr_tail
        )
        if stdout_changed or stderr_changed:
            with self._condition:
                self._update_output(record)

    def _append_stream_output(
        self,
        record: _ScriptRunRecord,
        output: _BoundedOutputBuffer,
        text: str,
    ) -> bool:
        safe_text = _sanitize_output(text)
        if not safe_text:
            return False
        with self._condition:
            if record.info.state not in _ACTIVE_STATES:
                return False
            was_truncated = output.truncated
            retained = output.append(safe_text)
            if record.display_buffer is not None and retained:
                _append_display_text(record, retained)
            if (
                record.display_buffer is not None
                and output.truncated
                and not was_truncated
                and not record.display_output_truncation_notified
            ):
                _append_display_text(
                    record,
                    "\r\n[HostsKeeper] Run output truncated at capture limit.\r\n"
                )
                record.display_output_truncation_notified = True
            return True

    def _finish_with_exit_code(
        self, record: _ScriptRunRecord, exit_code: int
    ) -> None:
        with self._condition:
            if record.info.state not in _ACTIVE_STATES:
                return
            channel = record.channel
            now = max(_utcnow(), record.info.updated_at)
            state = (
                ScriptRunState.SUCCEEDED if exit_code == 0 else ScriptRunState.FAILED
            )
            record.info = replace(
                record.info,
                state=state,
                exit_code=exit_code,
                completed_at=now,
                updated_at=now,
                output=self._output_info(record),
            )
            record.channel = None
            self._changed(record)
            self._append_terminal_event(record)
        if channel is not None:
            _close_channel(channel)

    def _finish_uncertain(
        self,
        record: _ScriptRunRecord,
        state: ScriptRunState,
        error_code: ScriptRunErrorCode,
    ) -> None:
        with self._condition:
            if record.info.state not in _ACTIVE_STATES:
                return
            channel = record.channel
            self._set_state(record, state, error_code=error_code)
        if channel is not None:
            _close_channel(channel)

    def _set_state(
        self,
        record: _ScriptRunRecord,
        state: ScriptRunState,
        *,
        error_code: ScriptRunErrorCode,
    ) -> None:
        now = max(_utcnow(), record.info.updated_at)
        record.info = replace(
            record.info,
            state=state,
            updated_at=now,
            error_code=error_code,
            output=self._output_info(record),
        )
        record.channel = None
        self._changed(record)
        self._append_terminal_event(record)

    @staticmethod
    def _append_terminal_event(record: _ScriptRunRecord) -> None:
        if record.display_buffer is None:
            return
        state = record.info.state.value
        if record.info.exit_code is not None:
            detail = f"exit_code={record.info.exit_code}"
        elif record.info.process_may_continue:
            detail = "exit_code=unknown; process_may_continue=true"
        else:
            detail = "exit_code=unknown"
        _append_display_text(
            record,
            f"\r\n[HostsKeeper] Run [{record.info.run_id}] finished: "
            f"{state}; {detail}\r\n",
        )

    def _update_output(self, record: _ScriptRunRecord) -> None:
        now = max(_utcnow(), record.info.updated_at)
        record.info = replace(
            record.info,
            updated_at=now,
            output=self._output_info(record),
        )
        self._changed(record)

    def _changed(self, record: _ScriptRunRecord) -> None:
        record.sequence += 1
        self._condition.notify_all()

    def _is_running(self, record: _ScriptRunRecord) -> bool:
        with self._condition:
            return record.info.state in _ACTIVE_STATES

    def _snapshot(
        self,
        record: _ScriptRunRecord,
        *,
        stdout_cursor: str | None = None,
        stderr_cursor: str | None = None,
        max_chars: int = SCRIPT_RUN_OUTPUT_RESPONSE_DEFAULT_CHARS,
        wait_timed_out: bool = False,
    ) -> ScriptRunSnapshot:
        half = max_chars // 2
        stdout = record.stdout.read_since(stdout_cursor, half)
        stderr = record.stderr.read_since(stderr_cursor, half)
        remaining = max_chars - len(stdout.data) - len(stderr.data)
        if remaining:
            if stdout.truncated:
                stdout = record.stdout.read_since(
                    stdout_cursor, len(stdout.data) + remaining
                )
            elif stderr.truncated:
                stderr = record.stderr.read_since(
                    stderr_cursor, len(stderr.data) + remaining
                )
        return ScriptRunSnapshot(
            info=self._info_snapshot(record),
            stdout=stdout,
            stderr=stderr,
            wait_timed_out=wait_timed_out,
        )

    def _info_snapshot(self, record: _ScriptRunRecord) -> ScriptRunInfo:
        return replace(record.info, output=self._output_info(record))

    @staticmethod
    def _output_info(record: _ScriptRunRecord) -> ScriptRunOutputInfo:
        return ScriptRunOutputInfo(
            stdout_chars_retained=record.stdout.size,
            stderr_chars_retained=record.stderr.size,
            stdout_truncated=record.stdout.truncated,
            stderr_truncated=record.stderr.truncated,
        )

    def _require(self, session_id: UUID, run_id: UUID) -> _ScriptRunRecord:
        self._prune_expired()
        record = self._records.get(run_id)
        if record is None or record.info.session_id != session_id:
            raise ScriptRunNotFoundError
        return record

    def _prune_expired(self) -> None:
        cutoff = _utcnow() - SCRIPT_RUN_RETENTION
        expired = [
            run_id
            for run_id, record in self._records.items()
            if record.info.accepted_at < cutoff and record.info.state not in _ACTIVE_STATES
        ]
        for run_id in expired:
            record = self._records.pop(run_id)
            self._request_index.pop(
                (record.info.session_id, record.info.request_id), None
            )

    def _capacity_count(self, *, session_id: UUID | None = None) -> int:
        return sum(
            record.info.state in _CAPACITY_STATES
            and (session_id is None or record.info.session_id == session_id)
            for record in self._records.values()
        )

    @staticmethod
    def _has_output_after(
        record: _ScriptRunRecord,
        stdout_cursor: str | None,
        stderr_cursor: str | None,
    ) -> bool:
        return (
            _BoundedOutputBuffer._parse_cursor(stdout_cursor) < record.stdout.size
            or _BoundedOutputBuffer._parse_cursor(stderr_cursor) < record.stderr.size
        )

    @staticmethod
    def _validate_output_budget(max_chars: int) -> int:
        if (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or not 1 <= max_chars <= SCRIPT_RUN_OUTPUT_RESPONSE_MAX_CHARS
        ):
            raise ValueError("output max_chars is outside the configured limit")
        return max_chars


def _sanitize_output(text: str) -> str:
    return "".join(
        char
        if char in "\t\r\n" or unicodedata.category(char) != "Cc"
        else "\uFFFD"
        for char in text
    )


def _safe_display_name(name: str) -> str:
    safe = "".join(
        " "
        if char in "\r\n"
        else "\uFFFD"
        if unicodedata.category(char).startswith("C")
        else " "
        if unicodedata.category(char) in {"Zl", "Zp"}
        else char
        for char in name
    )
    return safe[:120] or "script"


def _normalize_terminal_line_endings(
    text: str, previous_char_was_cr: bool
) -> tuple[str, bool]:
    normalized: list[str] = []
    for char in text:
        if char == "\n":
            normalized.append("\n" if previous_char_was_cr else "\r\n")
            previous_char_was_cr = False
        else:
            normalized.append(char)
            previous_char_was_cr = char == "\r"
    return "".join(normalized), previous_char_was_cr


def _append_display_text(record: _ScriptRunRecord, text: str) -> None:
    if record.display_buffer is None:
        return
    normalized, record.display_last_char_was_cr = _normalize_terminal_line_endings(
        text, record.display_last_char_was_cr
    )
    record.display_buffer.append(normalized)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _close_channel(channel: paramiko.Channel) -> None:
    try:
        channel.close()
    except (OSError, paramiko.SSHException, RuntimeError):
        pass
