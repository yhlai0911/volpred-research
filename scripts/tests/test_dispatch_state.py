"""Unit tests for `scripts.dispatch_supervisor.state`.

Covers Deliverable 2 scaffold state module — verifies:
  * empty-state bootstrap & schema version
  * begin_fire → record_completion lifecycle
  * begin_fire refuses when current_job in-flight
  * orphan cleanup on mark_supervisor_started (simulates supervisor restart)
  * heartbeat updates last_heartbeat_at
  * completions ring buffer caps at COMPLETIONS_MAX
  * auth-blocked toggle
  * alert dedup window

Run::
    uv run pytest scripts/tests/test_dispatch_state.py -v
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import state as st


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


def test_read_state_bootstraps_empty(tmp_state: Path) -> None:
    snap = st.read_state(tmp_state)
    assert snap["version"] == st.SCHEMA_VERSION
    assert snap["current_job"] is None
    assert snap["completions"] == []
    assert snap["auth_blocked"] is False


def test_mark_supervisor_started_sets_timestamps(tmp_state: Path) -> None:
    st.mark_supervisor_started(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["supervisor_started_at"] is not None
    assert snap["last_heartbeat_at"] is not None


def test_mark_supervisor_started_clears_orphan_job(tmp_state: Path) -> None:
    # Simulate: previous supervisor died mid-job, current_job stuck in state.
    st.begin_fire(
        pid=12345, pgid=12345, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log", path=tmp_state,
    )
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is not None
    # Restart supervisor → orphan cleaned.
    st.mark_supervisor_started(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is None


def test_begin_fire_records_job(tmp_state: Path) -> None:
    st.begin_fire(
        pid=9999, pgid=9999, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/h.log", path=tmp_state,
    )
    snap = st.read_state(tmp_state)
    job = snap["current_job"]
    assert job["pid"] == 9999
    assert job["model"] == "opus"
    assert job["attempt"] == 1
    assert snap["last_fire_at"] is not None


def test_begin_fire_refuses_when_in_flight(tmp_state: Path) -> None:
    st.begin_fire(
        pid=1, pgid=1, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/a.log", path=tmp_state,
    )
    with pytest.raises(RuntimeError, match="current_job in-flight"):
        st.begin_fire(
            pid=2, pgid=2, schedule_id="hourly_dispatch",
            attempt=1, model="opus", log_path="/tmp/b.log", path=tmp_state,
        )


def test_record_completion_moves_to_ring_buffer(tmp_state: Path) -> None:
    st.begin_fire(
        pid=1, pgid=1, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/c.log", path=tmp_state,
    )
    entry = st.record_completion(
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )
    assert entry is not None
    assert entry["exit_code"] == 0
    assert entry["outcome"] == "success"
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is None
    assert len(snap["completions"]) == 1


def test_record_completion_noop_when_no_job(tmp_state: Path) -> None:
    entry = st.record_completion(
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )
    assert entry is None


def test_completions_ring_buffer_caps(tmp_state: Path) -> None:
    cap = st.COMPLETIONS_MAX
    for i in range(cap + 5):
        st.begin_fire(
            pid=i + 1, pgid=i + 1, schedule_id="hourly_dispatch",
            attempt=1, model="opus", log_path=f"/tmp/{i}.log", path=tmp_state,
        )
        st.record_completion(
            exit_code=0, outcome="success", final_model="opus", path=tmp_state,
        )
    snap = st.read_state(tmp_state)
    assert len(snap["completions"]) == cap


def test_auth_blocked_toggle(tmp_state: Path) -> None:
    st.set_auth_blocked(True, tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["auth_blocked"] is True
    assert snap["auth_blocked_at"] is not None
    st.set_auth_blocked(False, tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["auth_blocked"] is False
    assert snap["auth_blocked_at"] is None


def test_alert_dedup_window(tmp_state: Path) -> None:
    # First send — not deduped.
    assert st.should_dedup_alert("auth_blocked", 60, tmp_state) is False
    st.mark_alert_sent("auth_blocked", tmp_state)
    # Immediately after — deduped (within 60s window).
    assert st.should_dedup_alert("auth_blocked", 60, tmp_state) is True
    # Zero window — not deduped.
    assert st.should_dedup_alert("auth_blocked", 0, tmp_state) is False


def test_get_current_job_returns_dataclass(tmp_state: Path) -> None:
    assert st.get_current_job(tmp_state) is None
    st.begin_fire(
        pid=42, pgid=42, schedule_id="hourly_dispatch",
        attempt=2, model="sonnet", log_path="/tmp/d.log", path=tmp_state,
    )
    job = st.get_current_job(tmp_state)
    assert job is not None
    assert job.pid == 42
    assert job.attempt == 2
    assert job.model == "sonnet"
    assert job.age_seconds >= 0


def test_corrupt_state_falls_back_to_empty(tmp_state: Path) -> None:
    tmp_state.write_text("{ not valid json")
    snap = st.read_state(tmp_state)
    assert snap["version"] == st.SCHEMA_VERSION
    assert snap["current_job"] is None


def test_old_schema_version_is_reset(tmp_state: Path) -> None:
    tmp_state.write_text(json.dumps({"version": 999, "stuff": "old"}))
    # Locked-write path bootstraps fresh state on version mismatch.
    st.heartbeat(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["version"] == st.SCHEMA_VERSION
    assert "stuff" not in snap


def test_heartbeat_updates_timestamp(tmp_state: Path) -> None:
    st.mark_supervisor_started(tmp_state)
    first = st.read_state(tmp_state)["last_heartbeat_at"]
    time.sleep(0.01)
    st.heartbeat(tmp_state)
    second = st.read_state(tmp_state)["last_heartbeat_at"]
    assert second > first


def test_get_supervisor_age_seconds_when_alive(tmp_state: Path) -> None:
    st.mark_supervisor_started(tmp_state)
    age = st.get_supervisor_age_seconds(tmp_state)
    assert age is not None
    assert age >= 0
    assert age < 10  # just set


def test_get_supervisor_age_seconds_none_when_unset(tmp_state: Path) -> None:
    assert st.get_supervisor_age_seconds(tmp_state) is None


# ---------------------------------------------------------------------------
# Codex review fix #4 — atomic write regression tests
# ---------------------------------------------------------------------------


def test_atomic_write_replaces_file_via_os_replace(tmp_state: Path, monkeypatch) -> None:
    """Writes must go through os.replace() — not seek/truncate/dump on the
    canonical file directly. Spy on os.replace to prove the new pattern.
    """
    import os as _os

    calls: list[tuple[str, str]] = []
    real_replace = _os.replace

    def spy_replace(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(st.os, "replace", spy_replace)
    st.mark_supervisor_started(tmp_state)
    assert calls, "expected at least one os.replace() call from _atomic_write_json"
    # last replace destination must be the canonical state path
    assert calls[-1][1] == str(tmp_state)
    # src is the temp file (same dir, name starts with .<canonical>.tmp.)
    assert calls[-1][0].startswith(str(tmp_state.parent / f".{tmp_state.name}.tmp."))


def test_write_failure_does_not_corrupt_existing_state(tmp_state: Path, monkeypatch) -> None:
    """If os.replace() raises mid-write, the canonical file must still hold
    the prior valid state (the old seek/truncate path would leave it empty).
    """
    # Bootstrap with a non-empty state so we can detect corruption.
    st.mark_supervisor_started(tmp_state)
    st.begin_fire(
        pid=4242,
        pgid=4242,
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/log",
        path=tmp_state,
    )
    before = st.read_state(tmp_state)
    assert before["current_job"]["pid"] == 4242

    # Force os.replace to fail on the next write.
    def boom(src, dst):
        # Clean up the temp file so we don't leak it.
        try:
            Path(src).unlink()
        except FileNotFoundError:
            pass
        raise OSError("simulated atomic-write failure")

    monkeypatch.setattr(st.os, "replace", boom)

    with pytest.raises(OSError):
        st.heartbeat(tmp_state)

    # Canonical state must be intact — neither empty nor partially written.
    after = st.read_state(tmp_state)
    assert after["current_job"] is not None
    assert after["current_job"]["pid"] == 4242
    # Heartbeat must NOT have updated because the write failed.
    assert after["last_heartbeat_at"] == before["last_heartbeat_at"]


def test_no_temp_files_left_on_success(tmp_state: Path) -> None:
    """Successful writes must leave zero `.dispatch_state.json.tmp.*` siblings."""
    st.mark_supervisor_started(tmp_state)
    st.heartbeat(tmp_state)
    st.heartbeat(tmp_state)
    leftover = list(tmp_state.parent.glob(f".{tmp_state.name}.tmp.*"))
    assert leftover == [], f"unexpected temp files: {leftover}"


def test_no_temp_files_left_on_failure(tmp_state: Path, monkeypatch) -> None:
    """Failed writes must also clean up their temp file (exception path)."""
    st.mark_supervisor_started(tmp_state)

    def boom(src, dst):
        raise OSError("simulated atomic-write failure")

    monkeypatch.setattr(st.os, "replace", boom)
    with pytest.raises(OSError):
        st.heartbeat(tmp_state)
    leftover = list(tmp_state.parent.glob(f".{tmp_state.name}.tmp.*"))
    assert leftover == [], f"temp files leaked after failure: {leftover}"


def test_concurrent_writes_serialized_under_lock(tmp_state: Path) -> None:
    """fcntl.LOCK_EX must still serialize writes after the atomic-write switch.

    Spawn N threads each calling heartbeat() and verify the final file parses
    cleanly with version intact — i.e. no torn writes and no schema reset.
    """
    import threading

    st.mark_supervisor_started(tmp_state)
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(20):
                st.heartbeat(tmp_state)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent heartbeat raised: {errors}"
    snap = st.read_state(tmp_state)
    assert snap["version"] == st.SCHEMA_VERSION
    assert snap["supervisor_started_at"] is not None
    assert snap["last_heartbeat_at"] is not None
