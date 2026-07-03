"""Unit tests for `scripts.dispatch_supervisor.state`.

Covers Deliverable 2 scaffold + Deliverable 5 Codex-review-fix state module —
verifies:
  * empty-state bootstrap & schema version
  * reserve_fire → attach_process → record_completion lifecycle (§10 #5 atomic
    claim replaced the old single-call begin_fire)
  * reserve_fire refuses when current_job in-flight
  * mark_supervisor_started no longer clears current_job (§10 #3); orphan
    handling is mark_restart_orphan_pending() + append_completion_entry() +
    finalize_restart_orphan_cleanup() (two-phase — 2026-07-04 gate-blocking fix)
  * heartbeat updates last_heartbeat_at
  * completions ring buffer caps at COMPLETIONS_MAX
  * auth-blocked toggle
  * alert dedup window

Run::
    uv run pytest scripts/tests/test_dispatch_state.py -v
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import state as st


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


def _begin_fire(
    path: Path, *, pid: int, pgid: int, schedule_id: str, attempt: int,
    model: str, log_path: str, started_wall: str | None = "Wed Jan  1 00:00:00 2026",
) -> None:
    """Test helper mirroring worker.py's reserve_fire()+attach_process() pair
    (the old single-call `begin_fire` was removed as part of the §10 #5 atomic
    fire-claim fix — production code now reserves the slot BEFORE Popen spawn
    and attaches the real pid/pgid/identity-fingerprint after)."""
    st.reserve_fire(schedule_id=schedule_id, attempt=attempt, model=model, log_path=log_path, path=path)
    st.attach_process(pid=pid, pgid=pgid, started_wall=started_wall, path=path)


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


def test_mark_supervisor_started_no_longer_clears_current_job(tmp_state: Path) -> None:
    """§10 #3 fix: mark_supervisor_started must NOT silently discard a stale
    current_job — that responsibility moved to mark_restart_orphan_pending()
    so the caller can identity-check + kill + record before losing it."""
    _begin_fire(
        tmp_state, pid=12345, pgid=12345, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    st.mark_supervisor_started(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is not None
    assert snap["current_job"]["pid"] == 12345


def test_mark_restart_orphan_pending_flags_without_clearing(tmp_state: Path) -> None:
    """2026-07-04 gate-blocking fix #3: unlike the old claim_and_clear_current_job()
    (removed), current_job must stay non-null (with restart_cleanup_pending=True)
    until finalize_restart_orphan_cleanup() explicitly runs — so a second crash
    mid-cleanup can retry against the SAME orphan instead of losing it."""
    _begin_fire(
        tmp_state, pid=12345, pgid=12345, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    orphan = st.mark_restart_orphan_pending(tmp_state)
    assert orphan is not None
    assert orphan["pid"] == 12345
    assert orphan["restart_cleanup_pending"] is True
    # NOT cleared yet — current_job must still reflect the same orphan.
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is not None
    assert snap["current_job"]["pid"] == 12345
    assert snap["current_job"]["restart_cleanup_pending"] is True
    # Re-entrant: a second call (simulating a retry after a crash mid-cleanup)
    # must see the SAME orphan again, not None.
    again = st.mark_restart_orphan_pending(tmp_state)
    assert again is not None
    assert again["pid"] == 12345


def test_mark_restart_orphan_pending_none_when_idle(tmp_state: Path) -> None:
    assert st.mark_restart_orphan_pending(tmp_state) is None


def test_finalize_restart_orphan_cleanup_clears_slot(tmp_state: Path) -> None:
    _begin_fire(
        tmp_state, pid=12345, pgid=12345, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    st.mark_restart_orphan_pending(tmp_state)
    st.finalize_restart_orphan_cleanup(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is None
    # slot is free again — a fresh reserve must succeed
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/next.log", path=tmp_state,
    )


def test_append_completion_entry_for_pending_orphan(tmp_state: Path) -> None:
    _begin_fire(
        tmp_state, pid=777, pgid=777, schedule_id="hourly_dispatch",
        attempt=2, model="opus", log_path="/tmp/orphan.log",
    )
    orphan = st.mark_restart_orphan_pending(tmp_state)
    entry = st.append_completion_entry(
        orphan, exit_code=-9, outcome="killed_supervisor_restart",
        final_model="opus", path=tmp_state,
    )
    assert entry["exit_code"] == -9
    assert entry["outcome"] == "killed_supervisor_restart"
    assert entry["attempts"] == 2
    snap = st.read_state(tmp_state)
    assert len(snap["completions"]) == 1
    assert snap["completions"][0]["outcome"] == "killed_supervisor_restart"
    # append_completion_entry alone must NOT have cleared current_job —
    # finalize_restart_orphan_cleanup() is the only thing that does.
    assert snap["current_job"] is not None


def test_reserve_fire_records_job(tmp_state: Path) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/h.log", path=tmp_state,
    )
    snap = st.read_state(tmp_state)
    job = snap["current_job"]
    assert job["pid"] is None  # not yet attached
    assert job["model"] == "opus"
    assert job["attempt"] == 1
    assert snap["last_fire_at"] is not None


def test_reserve_fire_refuses_when_in_flight(tmp_state: Path) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=tmp_state,
    )
    with pytest.raises(RuntimeError, match="current_job in-flight"):
        st.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path="/tmp/b.log", path=tmp_state,
        )


def test_attach_process_fills_identity(tmp_state: Path) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=tmp_state,
    )
    st.attach_process(pid=555, pgid=555, started_wall="Wed Jan  1 00:00:00 2026", path=tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["current_job"]["pid"] == 555
    assert snap["current_job"]["started_wall"] == "Wed Jan  1 00:00:00 2026"


def test_attach_process_raises_without_reservation(tmp_state: Path) -> None:
    with pytest.raises(RuntimeError, match="no active reservation"):
        st.attach_process(pid=1, pgid=1, started_wall=None, path=tmp_state)


def test_update_started_wall_fills_fingerprint_after_attach(tmp_state: Path) -> None:
    """2026-07-04 gate-blocking fix #2: attach_process() now attaches pid/pgid
    with started_wall=None immediately after Popen() returns; the (slower,
    `ps`-based) fingerprint is filled in afterwards via update_started_wall()
    so the pid=None crash-recovery blind spot is as small as possible."""
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=tmp_state,
    )
    st.attach_process(pid=555, pgid=555, started_wall=None, path=tmp_state)
    assert st.read_state(tmp_state)["current_job"]["started_wall"] is None
    st.update_started_wall(pid=555, started_wall="Wed Jan  1 00:00:00 2026", path=tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["current_job"]["started_wall"] == "Wed Jan  1 00:00:00 2026"


def test_update_started_wall_noop_if_pid_no_longer_current(tmp_state: Path) -> None:
    """If the job already completed (or was replaced) by the time the slow
    `ps` fingerprint call returns, updating a stale pid must not resurrect or
    corrupt whatever current_job is now."""
    st.update_started_wall(pid=999, started_wall="irrelevant", path=tmp_state)
    assert st.read_state(tmp_state)["current_job"] is None  # still idle, no crash


def test_release_reservation_frees_slot(tmp_state: Path) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=tmp_state,
    )
    st.release_reservation(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["current_job"] is None
    # slot is free again — a fresh reserve must succeed
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a2.log", path=tmp_state,
    )


def test_record_completion_moves_to_ring_buffer(tmp_state: Path) -> None:
    _begin_fire(
        tmp_state, pid=1, pgid=1, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/c.log",
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


def test_record_completion_accepts_naive_started_at(tmp_state: Path) -> None:
    _begin_fire(
        tmp_state, pid=1, pgid=1, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/c.log",
    )
    snap = st.read_state(tmp_state)
    snap["current_job"]["started_at"] = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    )
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    entry = st.record_completion(
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )

    assert entry is not None
    assert entry["duration_s"] >= 0


def test_record_completion_warns_on_invalid_started_at(
    tmp_state: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _begin_fire(
        tmp_state, pid=1, pgid=1, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/c.log",
    )
    snap = st.read_state(tmp_state)
    snap["current_job"]["started_at"] = "not-a-date"
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=st.__name__):
        entry = st.record_completion(
            exit_code=0, outcome="success", final_model="opus", path=tmp_state,
        )

    assert entry is not None
    assert entry["duration_s"] == -1.0
    assert "invalid current_job.started_at for completion" in caplog.text
    assert "not-a-date" in caplog.text


def test_record_completion_noop_when_no_job(tmp_state: Path) -> None:
    entry = st.record_completion(
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )
    assert entry is None


def test_completions_ring_buffer_caps(tmp_state: Path) -> None:
    cap = st.COMPLETIONS_MAX
    for i in range(cap + 5):
        _begin_fire(
            tmp_state, pid=i + 1, pgid=i + 1, schedule_id="hourly_dispatch",
            attempt=1, model="opus", log_path=f"/tmp/{i}.log",
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


def test_alert_dedup_accepts_naive_timestamp(tmp_state: Path) -> None:
    snap = st.read_state(tmp_state)
    snap["alerts_dedup"] = {
        "auth_blocked": (
            datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        )
    }
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    assert st.should_dedup_alert("auth_blocked", 60, tmp_state) is True


def test_alert_dedup_warns_on_invalid_timestamp(
    tmp_state: Path, caplog: pytest.LogCaptureFixture
) -> None:
    snap = st.read_state(tmp_state)
    snap["alerts_dedup"] = {"auth_blocked": "not-a-date"}
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=st.__name__):
        deduped = st.should_dedup_alert("auth_blocked", 60, tmp_state)

    assert deduped is False
    assert "invalid alerts_dedup timestamp" in caplog.text
    assert "auth_blocked" in caplog.text
    assert "not-a-date" in caplog.text


def test_get_current_job_returns_dataclass(tmp_state: Path) -> None:
    assert st.get_current_job(tmp_state) is None
    _begin_fire(
        tmp_state, pid=42, pgid=42, schedule_id="hourly_dispatch",
        attempt=2, model="sonnet", log_path="/tmp/d.log",
        started_wall="Thu Jul  2 00:00:00 2026",
    )
    job = st.get_current_job(tmp_state)
    assert job is not None
    assert job.pid == 42
    assert job.attempt == 2
    assert job.model == "sonnet"
    assert job.started_wall == "Thu Jul  2 00:00:00 2026"
    assert job.age_seconds >= 0


def test_get_current_job_returns_none_while_reserved_only(tmp_state: Path) -> None:
    """§10 #5: between reserve_fire() and attach_process() pid is None — the
    reservation window is real (spans the Popen() call) but must never crash
    get_current_job()'s int(pid) conversion; treat as "nothing to inspect"."""
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/d.log", path=tmp_state,
    )
    assert st.get_current_job(tmp_state) is None


def test_get_current_job_accepts_naive_started_at(tmp_state: Path) -> None:
    _begin_fire(
        tmp_state, pid=42, pgid=42, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/d.log",
    )
    snap = st.read_state(tmp_state)
    snap["current_job"]["started_at"] = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    )
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    job = st.get_current_job(tmp_state)

    assert job is not None
    assert job.age_seconds >= 0


def test_get_current_job_warns_on_invalid_started_at(
    tmp_state: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _begin_fire(
        tmp_state, pid=42, pgid=42, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/d.log",
    )
    snap = st.read_state(tmp_state)
    snap["current_job"]["started_at"] = "not-a-date"
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=st.__name__):
        job = st.get_current_job(tmp_state)

    assert job is not None
    assert job.age_seconds == -1.0
    assert "invalid current_job.started_at" in caplog.text
    assert "not-a-date" in caplog.text


def test_corrupt_state_warns_and_falls_back_to_empty(
    tmp_state: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tmp_state.write_text("{ not valid json")
    with caplog.at_level(logging.WARNING, logger=st.__name__):
        snap = st.read_state(tmp_state)

    assert snap["version"] == st.SCHEMA_VERSION
    assert snap["current_job"] is None
    assert "dispatch state reset to empty" in caplog.text
    assert "json_decode_failed" in caplog.text


def test_old_schema_version_warns_and_is_reset(
    tmp_state: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tmp_state.write_text(json.dumps({"version": 999, "stuff": "old"}))
    with caplog.at_level(logging.WARNING, logger=st.__name__):
        # Locked-write path bootstraps fresh state on version mismatch.
        st.heartbeat(tmp_state)
        snap = st.read_state(tmp_state)

    assert snap["version"] == st.SCHEMA_VERSION
    assert "stuff" not in snap
    assert "dispatch state reset to empty" in caplog.text
    assert "schema_invalid" in caplog.text


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


def test_get_supervisor_age_seconds_accepts_naive_heartbeat(tmp_state: Path) -> None:
    st.mark_supervisor_started(tmp_state)
    snap = st.read_state(tmp_state)
    snap["last_heartbeat_at"] = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    )
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    age = st.get_supervisor_age_seconds(tmp_state)

    assert age is not None
    assert age >= 0


def test_get_supervisor_age_seconds_warns_on_invalid_heartbeat(
    tmp_state: Path, caplog: pytest.LogCaptureFixture
) -> None:
    st.mark_supervisor_started(tmp_state)
    snap = st.read_state(tmp_state)
    snap["last_heartbeat_at"] = "not-a-date"
    tmp_state.write_text(json.dumps(snap), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger=st.__name__):
        age = st.get_supervisor_age_seconds(tmp_state)

    assert age is None
    assert "invalid last_heartbeat_at" in caplog.text
    assert "not-a-date" in caplog.text


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
    _begin_fire(
        tmp_state, pid=4242, pgid=4242, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/log",
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


# ---------------------------------------------------------------------------
# Codex review fix #1 (2026-07-04, gate-blocking) — lockfile TOCTOU regression
# ---------------------------------------------------------------------------


def test_lock_path_is_stable_sibling_never_the_replaced_file(tmp_state: Path) -> None:
    """The old design flocked `path` itself, which `os.replace()` swaps to a
    new inode every write — a second writer that had already `open()`ed the
    OLD inode before the replace could then flock it (uncontended, since the
    real mutex moved to the new inode) and clobber the first writer's update.
    Codex reproduced this with two overlapping `_locked_state()` writers. The
    fix locks a dedicated sibling file that is opened in append mode and NEVER
    unlinked/replaced, so every contender always flocks the same inode."""
    lock_path = st._lock_path(tmp_state)
    assert lock_path != tmp_state
    assert lock_path.name == tmp_state.name + ".lock"
    st.mark_supervisor_started(tmp_state)
    assert lock_path.exists()
    # the lockfile itself must never be the thing os.replace() swaps —
    # confirm its inode is stable across a write cycle.
    inode_before = lock_path.stat().st_ino
    st.heartbeat(tmp_state)
    assert lock_path.stat().st_ino == inode_before


def test_no_lost_updates_under_concurrent_read_modify_write(tmp_state: Path) -> None:
    """Codex review fix #1 regression: stress many threads each doing a full
    `_locked_state()` read-increment-write cycle. Under the old bug (flock on
    the canonical file that `os.replace()` swaps out from under the lock),
    some increments could be silently lost because a second writer could read
    stale pre-write content and clobber the first writer's replace. Every
    increment must be observed exactly once with the new stable-lockfile design.
    """
    import threading

    st.mark_supervisor_started(tmp_state)
    n_threads, n_iters = 8, 25
    errors: list[BaseException] = []

    def bump():
        with st._locked_state(tmp_state) as (_fh, data):
            dedup = data.get("alerts_dedup") or {}
            dedup["stress_counter"] = str(int(dedup.get("stress_counter", "0")) + 1)
            data["alerts_dedup"] = dedup

    def run():
        try:
            for _ in range(n_iters):
                bump()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent bump raised: {errors}"
    snap = st.read_state(tmp_state)
    assert int(snap["alerts_dedup"]["stress_counter"]) == n_threads * n_iters
