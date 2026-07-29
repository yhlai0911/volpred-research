from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import state


def _reserved_attempt(path: Path) -> state.JobHandle:
    handle = state.reserve_fire(
        schedule_id="custody-test",
        attempt=1,
        model="opus",
        log_path="/tmp/custody-test.log",
        scheduled_for=None,
        fire_reason="test",
        path=path,
    )
    assert handle is not None
    started = state.begin_attempt(
        job_id=handle.job_id,
        attempt=1,
        model="opus",
        log_path="/tmp/custody-test.log",
        expected_previous_attempt=1,
        path=path,
    )
    assert started == handle
    return handle


def _custody() -> dict[str, object]:
    return {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001, 1002],
    }


def test_attempt_custody_round_trips_into_job_and_completion(tmp_path: Path) -> None:
    state_path = tmp_path / "dispatch-state.json"
    handle = _reserved_attempt(state_path)

    assert state.attach_producer_custody(
        job_id=handle.job_id,
        custody=_custody(),
        expected_attempt=1,
        path=state_path,
    )
    state.attach_process(
        job_id=handle.job_id,
        expected_attempt=1,
        pid=os.getpid(),
        pgid=os.getpgid(0),
        started_wall="test-generation",
        path=state_path,
    )

    current = state.get_current_jobs(state_path)
    assert len(current) == 1
    assert current[0].producer_custody == _custody()

    entry = state.record_completion(
        job_id=handle.job_id,
        expected_attempt=1,
        exit_code=0,
        outcome="success",
        final_model="opus",
        path=state_path,
    )
    assert entry is not None
    assert entry["producer_custody"] == _custody()
    snap = state.read_state(state_path)
    assert snap["completions"][-1]["producer_custody"] == _custody()
    assert snap["phase_z_pending"][-1]["producer_custody"] == _custody()


def test_attempt_custody_is_immutable_and_must_precede_process_attach(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch-state.json"
    handle = _reserved_attempt(state_path)
    assert state.attach_producer_custody(
        job_id=handle.job_id,
        custody=_custody(),
        expected_attempt=1,
        path=state_path,
    )
    with pytest.raises(RuntimeError, match="another baseline"):
        state.attach_producer_custody(
            job_id=handle.job_id,
            custody={**_custody(), "trusted_unique_ids": [9999]},
            expected_attempt=1,
            path=state_path,
        )

    state.attach_process(
        job_id=handle.job_id,
        expected_attempt=1,
        pid=os.getpid(),
        pgid=os.getpgid(0),
        started_wall="test-generation",
        path=state_path,
    )
    with pytest.raises(RuntimeError, match="after process attach"):
        state.attach_producer_custody(
            job_id=handle.job_id,
            custody=_custody(),
            expected_attempt=1,
            path=state_path,
        )


def test_retry_clears_attempt_scoped_custody(tmp_path: Path) -> None:
    state_path = tmp_path / "dispatch-state.json"
    handle = _reserved_attempt(state_path)
    assert state.attach_producer_custody(
        job_id=handle.job_id,
        custody=_custody(),
        expected_attempt=1,
        path=state_path,
    )

    retried = state.begin_attempt(
        job_id=handle.job_id,
        attempt=2,
        model="opus",
        log_path="/tmp/custody-test-retry.log",
        expected_previous_attempt=1,
        path=state_path,
    )

    assert retried == handle
    raw = state.read_state(state_path)["current_jobs"][0]
    assert raw["producer_custody"] is None
