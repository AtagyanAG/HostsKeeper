"""Runtime records for isolated MCP script executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM = 131_072


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScriptRunOrigin(str, Enum):
    USER_INTERFACE = "user_interface"
    STDIO = "stdio"
    HTTP_GATEWAY = "http_gateway"
    HTTP_LEGACY = "http_legacy"


class ScriptRunState(str, Enum):
    ACCEPTED = "accepted"
    STARTING = "starting"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SESSION_LOST = "session_lost"
    EXECUTION_TIMED_OUT = "execution_timed_out"
    UNKNOWN = "unknown"
    NOT_SUPPORTED = "not_supported"


class ScriptRunErrorCode(str, Enum):
    START_FAILED = "start_failed"
    SESSION_LOST = "session_lost"
    EXECUTION_TIMEOUT = "execution_timeout"
    CANCEL_UNCONFIRMED = "cancel_unconfirmed"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScriptRunOutputInfo:
    """Bounded-output metadata; actual stream contents are stored separately."""

    stdout_chars_retained: int = 0
    stderr_chars_retained: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def __post_init__(self) -> None:
        for count in (self.stdout_chars_retained, self.stderr_chars_retained):
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                or count > SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM
            ):
                raise ValueError("retained output size is outside the configured limit")


@dataclass(frozen=True)
class ScriptRunInfo:
    """Safe run snapshot; never stores the SSH token, command, or raw exception."""

    run_id: UUID
    request_id: UUID
    session_id: UUID
    script_id: UUID
    origin: ScriptRunOrigin
    state: ScriptRunState = ScriptRunState.ACCEPTED
    accepted_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    updated_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None
    exit_code: int | None = None
    error_code: ScriptRunErrorCode | None = None
    output: ScriptRunOutputInfo = field(default_factory=ScriptRunOutputInfo)

    def __post_init__(self) -> None:
        timestamps = (
            self.accepted_at,
            self.updated_at,
            self.started_at,
            self.completed_at,
        )
        for timestamp in timestamps:
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("run timestamps must be timezone-aware")

        if self.updated_at < self.accepted_at:
            raise ValueError("updated_at cannot precede accepted_at")
        if self.started_at is not None and self.started_at < self.accepted_at:
            raise ValueError("started_at cannot precede accepted_at")
        if self.state in {
            ScriptRunState.RUNNING,
            ScriptRunState.SUCCEEDED,
            ScriptRunState.FAILED,
            ScriptRunState.EXECUTION_TIMED_OUT,
        } and self.started_at is None:
            raise ValueError("this run state requires started_at")
        if self.completed_at is not None:
            if self.completed_at < self.accepted_at:
                raise ValueError("completed_at cannot precede accepted_at")
            if self.started_at is not None and self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")
            if self.state not in {
                ScriptRunState.SUCCEEDED,
                ScriptRunState.FAILED,
                ScriptRunState.CANCELLED,
            }:
                raise ValueError("completion time requires a confirmed terminal state")
            if self.updated_at < self.completed_at:
                raise ValueError("updated_at cannot precede completed_at")

        if self.exit_code is not None and (
            isinstance(self.exit_code, bool)
            or not isinstance(self.exit_code, int)
            or self.exit_code < 0
        ):
            raise ValueError("exit_code must be a non-negative integer")
        if self.state == ScriptRunState.SUCCEEDED:
            if self.exit_code != 0 or self.completed_at is None:
                raise ValueError(
                    "succeeded runs require exit code 0 and completion time"
                )
        elif self.state == ScriptRunState.FAILED:
            if (
                self.exit_code is None
                or self.exit_code == 0
                or self.completed_at is None
            ):
                raise ValueError(
                    "failed runs require a nonzero exit code and completion time"
                )
        elif self.exit_code is not None:
            raise ValueError("exit_code is only valid for succeeded or failed runs")

        if self.state == ScriptRunState.CANCELLED and self.completed_at is None:
            raise ValueError("cancelled runs require confirmed completion time")
        if self.state in {
            ScriptRunState.ACCEPTED,
            ScriptRunState.STARTING,
            ScriptRunState.RUNNING,
            ScriptRunState.CANCEL_REQUESTED,
        } and self.completed_at is not None:
            raise ValueError("active runs cannot have a completion time")

    @property
    def process_may_continue(self) -> bool:
        return self.state in {
            ScriptRunState.STARTING,
            ScriptRunState.RUNNING,
            ScriptRunState.CANCEL_REQUESTED,
            ScriptRunState.SESSION_LOST,
            ScriptRunState.EXECUTION_TIMED_OUT,
            ScriptRunState.UNKNOWN,
        }
