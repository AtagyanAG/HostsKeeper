from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from hostskeeper.session import (
    SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM,
    ScriptRunErrorCode,
    ScriptRunInfo,
    ScriptRunOrigin,
    ScriptRunOutputInfo,
    ScriptRunState,
)


def _run(
    *,
    state: ScriptRunState = ScriptRunState.ACCEPTED,
    accepted_at: datetime | None = None,
    started_at: datetime | None = None,
    updated_at: datetime | None = None,
    completed_at: datetime | None = None,
    exit_code: int | None = None,
    error_code: ScriptRunErrorCode | None = None,
    output: ScriptRunOutputInfo | None = None,
) -> ScriptRunInfo:
    accepted = accepted_at or datetime.now(timezone.utc)
    return ScriptRunInfo(
        run_id=uuid4(),
        request_id=uuid4(),
        session_id=uuid4(),
        script_id=uuid4(),
        origin=ScriptRunOrigin.HTTP_GATEWAY,
        state=state,
        accepted_at=accepted,
        started_at=started_at,
        updated_at=updated_at or accepted,
        completed_at=completed_at,
        exit_code=exit_code,
        error_code=error_code,
        output=output or ScriptRunOutputInfo(),
    )


def test_script_run_terminal_states_require_confirmed_exit_status() -> None:
    finished_at = datetime.now(timezone.utc)
    succeeded = _run(
        state=ScriptRunState.SUCCEEDED,
        accepted_at=finished_at - timedelta(seconds=2),
        started_at=finished_at - timedelta(seconds=1),
        completed_at=finished_at,
        updated_at=finished_at,
        exit_code=0,
    )
    failed = _run(
        state=ScriptRunState.FAILED,
        accepted_at=finished_at - timedelta(seconds=2),
        started_at=finished_at - timedelta(seconds=1),
        completed_at=finished_at,
        updated_at=finished_at,
        exit_code=2,
    )

    assert succeeded.exit_code == 0
    assert failed.exit_code == 2
    with pytest.raises(ValueError, match="succeeded runs"):
        accepted_at = datetime.now(timezone.utc)
        _run(
            state=ScriptRunState.SUCCEEDED,
            accepted_at=accepted_at,
            started_at=accepted_at,
        )
    with pytest.raises(ValueError, match="failed runs"):
        _run(
            state=ScriptRunState.FAILED,
            accepted_at=finished_at - timedelta(seconds=2),
            started_at=finished_at - timedelta(seconds=1),
            completed_at=finished_at,
            updated_at=finished_at,
            exit_code=0,
        )


def test_unknown_or_cancelled_run_cannot_claim_exit_code() -> None:
    with pytest.raises(ValueError, match="exit_code is only valid"):
        _run(state=ScriptRunState.SESSION_LOST, exit_code=0)
    with pytest.raises(ValueError, match="confirmed completion"):
        _run(state=ScriptRunState.CANCELLED)
    with pytest.raises(ValueError, match="non-negative integer"):
        accepted_at = datetime.now(timezone.utc)
        _run(
            state=ScriptRunState.SUCCEEDED,
            accepted_at=accepted_at,
            started_at=accepted_at,
            completed_at=accepted_at,
            updated_at=accepted_at,
            exit_code=True,
        )


def test_uncertain_run_states_report_that_remote_process_may_continue() -> None:
    assert _run(state=ScriptRunState.ACCEPTED).process_may_continue is False
    for state in (
        ScriptRunState.RUNNING,
        ScriptRunState.CANCEL_REQUESTED,
        ScriptRunState.SESSION_LOST,
        ScriptRunState.EXECUTION_TIMED_OUT,
        ScriptRunState.UNKNOWN,
    ):
        accepted_at = datetime.now(timezone.utc)
        started_at = (
            accepted_at
            if state
            in {
                ScriptRunState.RUNNING,
                ScriptRunState.EXECUTION_TIMED_OUT,
            }
            else None
        )
        assert _run(
            state=state,
            accepted_at=accepted_at,
            started_at=started_at,
        ).process_may_continue is True
    accepted_at = datetime.now(timezone.utc)
    assert _run(
        state=ScriptRunState.CANCELLED,
        accepted_at=accepted_at,
        completed_at=accepted_at,
        updated_at=accepted_at,
    ).process_may_continue is False


def test_run_timestamps_must_be_aware_and_ordered() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _run(accepted_at=datetime.now())

    accepted_at = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="cannot precede"):
        _run(
            accepted_at=accepted_at,
            updated_at=accepted_at - timedelta(seconds=1),
        )


def test_run_output_metadata_enforces_per_stream_bound() -> None:
    output = ScriptRunOutputInfo(
        stdout_chars_retained=SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM,
        stdout_truncated=True,
    )
    assert output.stdout_truncated

    with pytest.raises(ValueError, match="configured limit"):
        ScriptRunOutputInfo(
            stderr_chars_retained=SCRIPT_RUN_OUTPUT_MAX_CHARS_PER_STREAM + 1
        )
    with pytest.raises(ValueError, match="configured limit"):
        ScriptRunOutputInfo(stdout_chars_retained=-1)
    with pytest.raises(ValueError, match="configured limit"):
        ScriptRunOutputInfo(stderr_chars_retained=True)
