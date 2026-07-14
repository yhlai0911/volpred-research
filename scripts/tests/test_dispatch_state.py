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
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import state as st
from volpred.canonical_write import CanonicalWriteBlocked


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
    assert snap["current_jobs"] == []
    assert snap["completions"] == []
    assert snap["auth_blocked"] is False


def test_writer_gate_refuses_the_canonical_state_under_test(tmp_path: Path) -> None:
    """A test that forgets to redirect STATE_PATH must fail loudly, not write the
    LIVE daemon state. `conftest.py` sets VOLPRED_NO_CANONICAL_WRITE=1 for the
    whole session; this asserts the writer honours it.
    """
    # This is a control-flow sentinel, deliberately outside Exception so the
    # supervisor's best-effort broad catches cannot turn the violation green.
    assert issubclass(CanonicalWriteBlocked, BaseException)
    assert not issubclass(CanonicalWriteBlocked, Exception)
    with pytest.raises(CanonicalWriteBlocked, match="blocks write to canonical state"):
        st._atomic_write_json(st._CANONICAL_STATE_PATH, st._empty_state())


def test_writer_gate_leaves_tmp_paths_alone(tmp_state: Path) -> None:
    """The gate must compare against the path captured at import, not against a
    monkeypatched `STATE_PATH` — otherwise redirecting to tmp would trip it and
    every test in this file would fail.
    """
    st.mark_supervisor_started(tmp_state)
    assert st.read_state(tmp_state)["supervisor_pid"] == os.getpid()


def test_side_effect_guards_are_armed_outside_the_tests_tree() -> None:
    """This file lives under `scripts/tests/`, not `tests/`.

    Until 2026-07-10 the four side-effect guards were set in `tests/conftest.py`
    only, and a pytest conftest applies to its own directory tree — so every test
    here ran free to send real email, write production Supabase, and rewrite
    canonical `storage/` state. They now live in the repo-root `conftest.py`.
    Asserting them from THIS tree is the point: a guard set in the other tree
    would let the two tests above pass vacuously.
    """
    for flag in (
        "VOLPRED_NO_EMAIL",
        "VOLPRED_NO_REMOTE_WRITE",
        "VOLPRED_NO_REMOTE_READ",
        "VOLPRED_NO_CANONICAL_WRITE",
    ):
        assert os.environ.get(flag) == "1", f"{flag} not armed under scripts/tests/"


def test_versioned_root_conftest_is_single_pytest_guard_owner() -> None:
    """CI env vars can make the test above pass even if root conftest vanishes.

    Pin the versioned distribution artifact independently, and prohibit the
    nested duplicate that used to mask an unarmed scripts/tests worktree.
    """
    root = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "conftest.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, "repo-root conftest.py must be Git-tracked"

    owner_path = root / "conftest.py"
    assert owner_path.is_file(), "repo-root conftest.py must exist"
    owner = owner_path.read_text(encoding="utf-8")
    nested = (root / "tests/conftest.py").read_text(encoding="utf-8")
    for flag in (
        "VOLPRED_NO_EMAIL",
        "VOLPRED_NO_REMOTE_WRITE",
        "VOLPRED_NO_REMOTE_READ",
        "VOLPRED_NO_CANONICAL_WRITE",
    ):
        assignment = f'os.environ["{flag}"] = "1"'
        assert assignment in owner, f"root conftest does not own {flag}"
        assert assignment not in nested, f"nested conftest duplicates {flag}"


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


def test_append_completion_entry_marks_cleanup_recorded_atomically(tmp_state: Path) -> None:
    """Codex round-2 low finding (2026-07-04): the append + `cleanup_recorded`
    flag must land in ONE locked transaction, so a crash after it leaves a
    retryable-but-deduplicated orphan (next restart sees the flag and skips
    straight to finalize instead of appending a duplicate entry)."""
    _begin_fire(
        tmp_state, pid=777, pgid=777, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
    )
    orphan = st.mark_restart_orphan_pending(tmp_state)
    assert not orphan.get("cleanup_recorded")
    st.append_completion_entry(
        orphan, exit_code=-9, outcome="killed_supervisor_restart",
        final_model="opus", path=tmp_state, mark_cleanup_recorded=True,
    )
    snap = st.read_state(tmp_state)
    assert len(snap["completions"]) == 1
    assert snap["current_job"]["cleanup_recorded"] is True
    # A retry (simulating crash before finalize) must surface the flag.
    again = st.mark_restart_orphan_pending(tmp_state)
    assert again["cleanup_recorded"] is True


def test_acquire_lock_retries_when_lockfile_replaced_under_us(tmp_state: Path, monkeypatch) -> None:
    """Round-2 hardening: if the lockfile is deleted+recreated between our
    open() and flock() (external cleanup / stray rm), the locked fd points at
    a detached inode and serializes nothing — _acquire_lock must detect the
    inode mismatch and retry against the file now at the path."""
    lock_path = st._lock_path(tmp_state)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch()

    real_flock = st.fcntl.flock
    swapped = {"done": False}

    def flock_with_swap(fd, op):
        real_flock(fd, op)
        # After the FIRST exclusive acquisition, simulate an external process
        # deleting and recreating the lockfile — detaching our inode.
        if not swapped["done"] and op == st.fcntl.LOCK_EX:
            swapped["done"] = True
            lock_path.unlink()
            lock_path.touch()

    monkeypatch.setattr(st.fcntl, "flock", flock_with_swap)
    fh = st._acquire_lock(lock_path, shared=False)
    try:
        # The returned fd must match the CURRENT inode at the path.
        import os as _os
        assert _os.fstat(fh.fileno()).st_ino == _os.stat(lock_path).st_ino
        assert swapped["done"] is True, "the swap scenario must actually have been exercised"
    finally:
        real_flock(fh.fileno(), st.fcntl.LOCK_UN)
        fh.close()


def test_acquire_lock_gives_up_after_max_attempts(tmp_state: Path, monkeypatch) -> None:
    lock_path = st._lock_path(tmp_state)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch()

    real_flock = st.fcntl.flock

    def always_swap(fd, op):
        real_flock(fd, op)
        if op in (st.fcntl.LOCK_EX, st.fcntl.LOCK_SH):
            lock_path.unlink()
            lock_path.touch()

    monkeypatch.setattr(st.fcntl, "flock", always_swap)
    with pytest.raises(RuntimeError, match="stable lock"):
        st._acquire_lock(lock_path, shared=False, max_attempts=3)


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
    with pytest.raises(RuntimeError, match="slots at max_slots=1"):
        st.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path="/tmp/b.log", max_slots=1, path=tmp_state,
        )


def test_multislot_completion_cas_does_not_clear_sibling(tmp_state: Path) -> None:
    first = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", max_slots=2, path=tmp_state,
    )
    st.attach_process(
        job_id=first.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="a", path=tmp_state,
    )
    second = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/b.log", max_slots=2, path=tmp_state,
    )
    st.attach_process(
        job_id=second.job_id, expected_attempt=1,
        pid=202, pgid=202, started_wall="b", path=tmp_state,
    )

    won = st.record_completion(
        job_id=first.job_id, expected_attempt=1, expected_pid=101,
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )
    assert won is not None
    snap = st.read_state(tmp_state)
    assert [job["job_id"] for job in snap["current_jobs"]] == [second.job_id]
    assert snap["current_job"]["job_id"] == second.job_id

    # A late callback for A must not infer "the only remaining job" and clear B.
    assert st.record_completion(
        job_id=first.job_id, expected_attempt=1, expected_pid=101,
        exit_code=-9, outcome="killed_timeout", final_model="opus", path=tmp_state,
    ) is None
    assert st.read_state(tmp_state)["current_jobs"][0]["job_id"] == second.job_id


def test_reserve_fire_rejects_duplicate_cron_fire_key(tmp_state: Path) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", max_slots=2,
        fire_key="cron:2026-07-13T07:07:00", path=tmp_state,
    )
    with pytest.raises(RuntimeError, match="duplicate fire_key"):
        st.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path="/tmp/b.log", max_slots=2,
            fire_key="cron:2026-07-13T07:07:00", path=tmp_state,
        )


def test_retry_retains_job_slot_and_stale_attempt_cannot_close_it(tmp_state: Path) -> None:
    handle = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a1.log", path=tmp_state,
    )
    st.attach_process(
        job_id=handle.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="a", path=tmp_state,
    )
    first = st.record_completion(
        job_id=handle.job_id, expected_attempt=1, expected_pid=101,
        exit_code=1, outcome="failure", final_model="opus",
        release_slot=False, path=tmp_state,
    )
    assert first is not None
    waiting = st.read_state(tmp_state)["current_jobs"][0]
    assert waiting["phase"] == "retry_wait"
    assert waiting["slot_id"] == handle.slot_id
    assert waiting["pid"] is None

    retry = st.begin_attempt(
        job_id=handle.job_id, attempt=2, expected_previous_attempt=1,
        model="opus", log_path="/tmp/a2.log", path=tmp_state,
    )
    assert retry == handle
    st.attach_process(
        job_id=handle.job_id, expected_attempt=2,
        pid=202, pgid=202, started_wall="b", path=tmp_state,
    )
    assert st.record_completion(
        job_id=handle.job_id, expected_attempt=1, expected_pid=101,
        exit_code=-9, outcome="killed_timeout", final_model="opus", path=tmp_state,
    ) is None
    current = st.read_state(tmp_state)["current_jobs"][0]
    assert current["attempt"] == 2
    assert current["pid"] == 202


def test_stale_health_snapshot_cannot_close_classifying_attempt(tmp_state: Path) -> None:
    handle = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=tmp_state,
    )
    st.attach_process(
        job_id=handle.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="a", path=tmp_state,
    )
    assert st.mark_job_phase(
        job_id=handle.job_id, expected_attempt=1, expected_pid=101,
        expected_phase="running", phase="classifying", path=tmp_state,
    )

    assert st.record_completion(
        job_id=handle.job_id, expected_attempt=1, expected_pid=101,
        expected_phase="running", exit_code=-1, outcome="failure",
        final_model="opus", path=tmp_state,
    ) is None
    current = st.read_state(tmp_state)["current_jobs"][0]
    assert current["job_id"] == handle.job_id
    assert current["phase"] == "classifying"


def test_phase_z_pending_holds_slot_until_exact_cohort_finish(tmp_state: Path) -> None:
    handle = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", max_slots=1, path=tmp_state,
    )
    st.attach_process(
        job_id=handle.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="a", path=tmp_state,
    )
    token = st.record_completion(
        job_id=handle.job_id, expected_attempt=1, expected_pid=101,
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )
    assert token is not None
    assert token["cohort_drained"] is True
    assert token["phase_z_pending"] is True
    assert st.read_state(tmp_state)["phase_z_pending"][0]["slot_id"] == handle.slot_id

    with pytest.raises(RuntimeError, match="PHASE-Z drain is pending"):
        st.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path="/tmp/b.log", max_slots=1, path=tmp_state,
        )
    assert st.finish_phase_z(cohort_id="wrong", path=tmp_state) == 0
    assert st.finish_phase_z(cohort_id=handle.cohort_id, path=tmp_state) == 1
    assert st.finish_phase_z(cohort_id=handle.cohort_id, path=tmp_state) == 0
    st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/b.log", max_slots=1, path=tmp_state,
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


def test_record_completion_preserves_slot_and_fire_reason(tmp_state: Path) -> None:
    st.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/c.log",
        scheduled_for="2026-07-11T01:07:00",
        fire_reason="requested:email_reply:test",
        path=tmp_state,
    )
    st.attach_process(pid=1, pgid=1, started_wall="w", path=tmp_state)

    entry = st.record_completion(
        exit_code=0, outcome="success", final_model="opus", path=tmp_state,
    )

    assert entry is not None
    assert entry["scheduled_for"] == "2026-07-11T01:07:00"
    assert entry["fire_reason"] == "requested:email_reply:test"


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
    snap["current_job"]["attempt_started_at"] = "not-a-date"
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
    snap["current_job"]["attempt_started_at"] = "not-a-date"
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


def test_empty_state_declares_supervisor_pid(tmp_state: Path) -> None:
    # Declared-but-unset must be a PRESENT key, so a reader can tell it apart
    # from a phantom field (a `jq` miss also yields null).
    snap = st.read_state(tmp_state)
    assert "supervisor_pid" in snap
    assert snap["supervisor_pid"] is None


def test_mark_supervisor_started_records_own_pid(tmp_state: Path) -> None:
    st.mark_supervisor_started(tmp_state)
    snap = st.read_state(tmp_state)
    assert snap["supervisor_pid"] == os.getpid()
    assert snap["supervisor_started_at"] is not None


def test_heartbeat_restamps_supervisor_pid(tmp_state: Path) -> None:
    # A stale pid (state reset, or a hand-run `--once` stamping its own
    # short-lived pid) must self-heal on the next beat, not persist until the
    # daemon happens to restart.
    st.mark_supervisor_started(tmp_state)
    with st._locked_state(tmp_state) as (_fh, data):
        data["supervisor_pid"] = 999_999
    assert st.read_state(tmp_state)["supervisor_pid"] == 999_999

    st.heartbeat(tmp_state)
    assert st.read_state(tmp_state)["supervisor_pid"] == os.getpid()


def test_new_optional_key_does_not_reset_preexisting_state(tmp_state: Path) -> None:
    """A state file written before `supervisor_pid` existed is still version 1,
    so it must survive untouched — bumping SCHEMA_VERSION for a new optional key
    would wipe `current_job` (orphaning a live worker) and the completions ring.
    """
    legacy = st._empty_state()
    del legacy["supervisor_pid"]  # exactly what a pre-2026-07-10 file looks like
    legacy["completions"] = [{"outcome": "success", "exit_code": 0}]
    legacy["current_job"] = {"pid": 4242, "pgid": 4242, "attempt": 1, "model": "opus"}
    tmp_state.write_text(json.dumps(legacy), encoding="utf-8")

    snap = st.read_state(tmp_state)
    assert snap["current_job"]["pid"] == 4242, "live worker orphaned by a schema reset"
    assert snap["completions"] == [{"outcome": "success", "exit_code": 0}]
    assert snap.get("supervisor_pid") is None  # absent until the first beat

    st.heartbeat(tmp_state)
    healed = st.read_state(tmp_state)
    assert healed["supervisor_pid"] == os.getpid()
    assert healed["current_job"]["pid"] == 4242  # still intact


def test_rollout_migration_trusts_legacy_reserve_over_stale_empty_list(tmp_state: Path) -> None:
    """A pre-reload daemon preserves unknown current_jobs=[] while writing A
    into current_job. The new reader must not orphan that live A."""
    mixed = st._empty_state()
    mixed["current_job"] = {
        "pid": 4242, "pgid": 4242, "attempt": 1, "model": "opus",
        "schedule_id": "hourly_dispatch", "started_at": datetime.now(timezone.utc).isoformat(),
        "log_path": "/tmp/legacy.log",
    }
    tmp_state.write_text(json.dumps(mixed), encoding="utf-8")

    snap = st.read_state(tmp_state)
    assert len(snap["current_jobs"]) == 1
    assert snap["current_jobs"][0]["pid"] == 4242
    assert snap["current_jobs"][0]["job_id"].startswith("legacy-")


def test_rollout_migration_trusts_legacy_completion_over_stale_list(tmp_state: Path) -> None:
    """The inverse mixed-version write is old record_completion clearing
    current_job while preserving a stale current_jobs[A]. A must stay closed."""
    handle = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=tmp_state,
    )
    mixed = st.read_state(tmp_state)
    assert mixed["current_jobs"][0]["job_id"] == handle.job_id
    mixed["current_job"] = None
    tmp_state.write_text(json.dumps(mixed), encoding="utf-8")

    snap = st.read_state(tmp_state)
    assert snap["current_jobs"] == []
    assert snap["current_job"] is None


def test_rollout_legacy_completion_preserves_new_sibling(tmp_state: Path) -> None:
    first = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", max_slots=2, path=tmp_state,
    )
    second = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/b.log", max_slots=2, cohort_id=first.cohort_id,
        path=tmp_state,
    )
    mixed = st.read_state(tmp_state)
    mixed["current_job"] = None  # old daemon completed projected slot 1
    tmp_state.write_text(json.dumps(mixed), encoding="utf-8")

    snap = st.read_state(tmp_state)
    assert [job["job_id"] for job in snap["current_jobs"]] == [second.job_id]


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
            pass  # silent-ok: the atomic-write temp may already have been removed
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


# --- schema contract gate (幽靈欄位 strike 3, 2026-07-10) ---------------------
# 根因（error_log 2026-07-10）：state 檔沒有 reader/writer 共享的 schema 契約。
# `dict.get()` 對「打錯的名字」「從未實作的欄位」「宣告但未設值」一律回 null，
# 三者不可分辨 → 幽靈欄位已累積 3 例（last_dispatch_at / supervisor_pid /
# last_completion）。當時的處置只有 module docstring 的一段散文 "Reader's field
# map"。散文擋不住第四個。以下把那段散文升級成機械 gate：
#
#   writer 寫的 key ⊆ _empty_state() 宣告的 key == docstring schema 區塊列的 key
#
# **守得住什麼**：三者任一漂移即 fail。抓得到 fire_requested_at 那一類（有 writer、
# _empty_state 沒宣告）與 supervisor_pid 那一類（宣告漏了）。效果是讓 docstring
# schema 成為**可信**的 field map — 它自稱「沒列的就是幽靈」，這句話現在由測試背書。
#
# **守不住什麼（誠實聲明）**：本 gate **不掃 reader**。今天的 last_completion
# （reader 讀一個哪裡都不存在的 key）不會被它擋下。試過做 reader 側 AST gate 後
# 放棄：ops_dashboard 走泛用 `_load(path)` helper 綁不到變數名；cron_review 的
# `state` 同時綁 LAST_RUN_PATH 與 DISPATCH_STATE_PATH，name-based 掃描必假陽性。
# 硬上啟發式只會製造假確信 —— 那正是本 entry 的病灶（docstring 曾宣稱
# check_alerts.py 是 consumer，實際零 reader）。reader 側仍靠 code review + field map。

import ast
import re
import inspect


def _schema_keys_from_module_docstring() -> set[str]:
    """抓 module docstring 裡 schema 區塊的**頂層**欄位（縮排 6 空格）。

    巢狀子鍵（current_job 的 8 空格、completions entry 的 10 空格）刻意排除 —
    它們不是頂層 state key。
    """
    doc = inspect.getdoc(st) or ""
    return set(re.findall(r'^ {6}"(\w+)"\s*:', doc, flags=re.MULTILINE))


def _writer_sources() -> list[Path]:
    """所有可能寫 state 的模組 — 整個 dispatch_supervisor package，不只 state.py。

    `_locked_state()` 是公開給 package 內部用的（`scheduler.py:305` 就直接在裡面
    寫 `data["last_fire_at"]`）。只掃 state.py 會留下盲區：任何模組在 locked
    context 裡新增一個未宣告的 key，gate 都會靜默放行 —— 那正是本 gate 要防的病。
    """
    pkg = Path(st.__file__).parent
    return sorted(p for p in pkg.glob("*.py") if p.name != "__init__.py")


def _toplevel_keys_written_by_writers() -> set[str]:
    """AST 掃整個 package：所有 `data["X"] = ...` 形式的頂層寫入。

    `data` 是 `_locked_state()` yield 出來的 state dict — package 內一致的慣例。
    """
    keys: set[str] = set()
    for src_path in _writer_sources():
        src = src_path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, (ast.Assign, ast.AugAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "data"
                        and isinstance(tgt.slice, ast.Constant)
                        and isinstance(tgt.slice.value, str)):
                    keys.add(tgt.slice.value)
    return keys


def test_empty_state_matches_module_docstring_schema():
    """docstring schema 是 reader 的唯一權威（它自稱「沒列的就是幽靈」）。
    它必須與 `_empty_state()` 逐鍵相等 —— 否則讀者會把真欄位當幽靈，或反之。"""
    declared = set(st._empty_state().keys())
    documented = _schema_keys_from_module_docstring()
    assert documented, "docstring schema 區塊解析失敗（縮排改了？）"
    assert declared == documented, (
        f"schema 契約漂移：\n"
        f"  _empty_state 有但 docstring 沒列（讀者會誤判為幽靈）: {sorted(declared - documented)}\n"
        f"  docstring 列了但 _empty_state 沒宣告（幽靈欄位本體）: {sorted(documented - declared)}"
    )


def test_every_written_field_is_declared_in_empty_state():
    """有 writer 就必須在 `_empty_state()` 宣告 —— 「宣告即存在」才能讓 reader
    區分 null=未設值 與 key-absent=從未實作。supervisor_pid（2026-07-10）與
    fire_requested_at/fire_request_reason 都是漏了這一步才變成觀察性缺陷。"""
    written = _toplevel_keys_written_by_writers()
    declared = set(st._empty_state().keys())
    assert written, "AST 沒掃到任何 data[...] 寫入（_locked_state 慣例改了？）"
    # 掃描範圍自檢：scheduler.py 確實在 _locked_state 內寫 last_fire_at。掃不到它
    # 代表 glob/AST 比對壞了而不是「沒有違規」—— 空結果的 silent pass 是假綠燈。
    assert "last_fire_at" in written, (
        "掃描沒涵蓋 scheduler.py 的 data['last_fire_at'] 寫入 → gate 範圍已失效"
    )
    undeclared = written - declared
    assert not undeclared, (
        f"這些欄位有 writer 但 _empty_state() 沒宣告，會產生 null/absent 不可分辨："
        f" {sorted(undeclared)}"
    )


def _subblock_keys_from_docstring(anchor: str, closer: str) -> set[str]:
    """切出 docstring schema 裡某個巢狀 block，回傳它列出的欄位。

    不能只靠縮排全域掃：`alerts_dedup` 的示例子鍵與 current_job 的欄位同為 8 空格，
    必須先切 block。也**不可錨定行首** —— completions entry 是一行兩個 key
    （`"fire_at": "<ISO>", "completed_at": "<ISO>",`），錨行首只抓得到每行第一個，
    會把 completed_at / duration_s / final_model 誤報成「有 writer 沒文件」。
    2026-07-10 實測踩過此坑，差點產出 6 個假發現（真正漏的只有 pid/pgid/started_wall）。
    """
    doc = inspect.getdoc(st) or ""
    lines = doc.splitlines()
    start = next(i for i, ln in enumerate(lines) if anchor in ln)
    end = next(i for i in range(start + 1, len(lines)) if re.match(closer, lines[i]))
    return set(re.findall(r'"(\w+)"\s*:', "\n".join(lines[start + 1:end])))


def _current_job_keys_from_docstring() -> set[str]:
    return _subblock_keys_from_docstring('"current_job"', r'^ {6}\},')


def _completion_entry_keys_from_docstring() -> set[str]:
    return _subblock_keys_from_docstring('"completions"', r'^ {6}\],')


def test_current_job_shape_matches_docstring(tmp_state):
    """**Runtime** shape gate（不是 AST）：跑真正的 writer，檢查它們產出的
    `current_job` 只含 docstring 列出的欄位。

    為什麼不用 AST：current_job 有三種寫入形式 —— `data["current_job"] = {literal}`、
    `data["current_job"]["k"] = v`、以及先取別名 `job["k"] = v` 再整包指派。要用
    AST 穩健涵蓋第三種需要 dataflow 分析；靠變數命名慣例（`job`）猜就是啟發式，
    換個名字就靜默漏掉。改成驅動真 writer、檢查真產物 —— sound，且別名寫法藏不住。

    2026-07-10 實測抓到：`cleanup_recorded` / `cleanup_outcome` 由
    `append_completion_entry(mark_cleanup_recorded=True)` 寫入 current_job，
    但 docstring 從未列出（與 fire_requested_at 同一病：有 writer、無文件）。
    """
    documented = _current_job_keys_from_docstring()
    assert documented, "current_job block 解析失敗（docstring 結構改了？）"

    def observed() -> set[str]:
        cj = st.read_state(tmp_state).get("current_job")
        return set(cj.keys()) if cj else set()

    def check(stage: str) -> None:
        undocumented = observed() - documented
        assert not undocumented, (
            f"[{stage}] current_job 出現 docstring 沒列的欄位: {sorted(undocumented)}"
        )

    st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                    log_path="/tmp/x.log", path=tmp_state)
    check("reserve_fire")

    st.attach_process(pid=4242, pgid=4242, started_wall="Fri Jul 10 12:00:00 2026",
                      path=tmp_state)
    check("attach_process")

    job = st.mark_restart_orphan_pending(path=tmp_state)
    check("mark_restart_orphan_pending")
    assert job is not None

    st.append_completion_entry(job, exit_code=0, outcome="orphan_gone_or_reused",
                               final_model="opus", path=tmp_state,
                               mark_cleanup_recorded=True)
    check("append_completion_entry(mark_cleanup_recorded=True)")


def test_completion_entry_shape_matches_docstring(tmp_state):
    """同一個 runtime shape gate，往下一層：completions[] entry。

    `append_completion_entry()` 在 job 有 pid 時額外蓋 `pid`/`pgid`/`started_wall`
    （orphan 路徑專用，一般 `record_completion()` 的 entry 沒有）。2026-07-10 實測
    這三個欄位有 writer 但 docstring 從未列出 —— 與 fire_requested_at /
    cleanup_recorded 同一病，只是深一層。兩條 entry 產生路徑都要驗。
    """
    documented = _completion_entry_keys_from_docstring()
    assert documented, "completions block 解析失敗（docstring 結構改了？）"

    # 路徑 1：orphan — append_completion_entry（會多蓋 pid/pgid/started_wall）
    st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                    log_path="/tmp/x.log", path=tmp_state)
    st.attach_process(pid=4242, pgid=4242, started_wall="Fri Jul 10 12:00:00 2026",
                      path=tmp_state)
    job = st.mark_restart_orphan_pending(path=tmp_state)
    st.append_completion_entry(job, exit_code=0, outcome="orphan_gone_or_reused",
                               final_model="opus", path=tmp_state)
    entry = st.read_state(tmp_state)["completions"][-1]
    undocumented = set(entry) - documented
    assert not undocumented, f"[append_completion_entry] 未文件化欄位: {sorted(undocumented)}"
    assert {"pid", "pgid", "started_wall"} <= set(entry), (
        "orphan 路徑沒蓋上 pid/pgid/started_wall → 掃描範圍自檢失效（假綠燈）"
    )

    # 路徑 2：正常收班 — record_completion
    st.finalize_restart_orphan_cleanup(path=tmp_state)
    st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                    log_path="/tmp/y.log", path=tmp_state)
    st.attach_process(pid=99, pgid=99, started_wall="w", path=tmp_state)
    st.record_completion(exit_code=0, outcome="success", final_model="opus",
                         path=tmp_state)
    entry2 = st.read_state(tmp_state)["completions"][-1]
    undocumented2 = set(entry2) - documented
    assert not undocumented2, f"[record_completion] 未文件化欄位: {sorted(undocumented2)}"


def test_locked_state_binding_is_always_named_data():
    """AST gate（`_toplevel_keys_written_by_writers`）假設 `_locked_state()` 綁出的
    state dict 永遠叫 `data`。那是慣例不是保證 —— 換個名字，gate 靜默漏掉整個模組。
    把這個假設本身變成斷言。"""
    bad: list[str] = []
    for src_path in _writer_sources():
        for node in ast.walk(ast.parse(src_path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.With):
                continue
            for item in node.items:
                call = item.context_expr
                if not (isinstance(call, ast.Call) and _is_locked_state_call(call)):
                    continue
                var = item.optional_vars
                if not (isinstance(var, ast.Tuple) and len(var.elts) == 2
                        and isinstance(var.elts[1], ast.Name)
                        and var.elts[1].id == "data"):
                    bad.append(f"{src_path.name}:{node.lineno}")
    assert not bad, (
        f"_locked_state() 綁定不叫 (_fh, data) → AST gate 會漏掉這些位置: {bad}"
    )


def _is_locked_state_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr == "_locked_state"
    return isinstance(f, ast.Name) and f.id == "_locked_state"


def _drive_every_writer(path: Path) -> None:
    """跑過每一個會寫 state 的 public writer，讓 state 樹長到最完整的形狀。

    「每一個」由 `test_drive_every_writer_covers_all_public_writers` 機械保證 ——
    不是靠這行註解。初版漏了 `release_reservation` / `clear_alert_dedup` 卻在
    commit message 宣稱「驅動每一個」（2026-07-10）。
    """
    st.mark_supervisor_started(path=path)
    st.heartbeat(path=path)
    st.request_fire(reason="manual", path=path)
    st.consume_fire_request(path=path)
    st.set_auth_blocked(True, path=path)
    st.set_auth_blocked(False, path=path)
    st.mark_alert_sent("stale_alert", path=path)
    st.clear_alert_dedup("stale_alert", path=path)
    st.mark_alert_sent("auth_blocked", path=path)  # 留一筆，扁平性斷言才有東西可驗

    # spawn 失敗路徑：reserve 之後還沒有 pid 就 release，slot 必須回收
    released = st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                               log_path="/tmp/w.log", path=path)
    st.release_reservation(path=path, job_id=released.job_id)

    orphan_handle = st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                                    log_path="/tmp/x.log", path=path)
    st.attach_process(job_id=orphan_handle.job_id, expected_attempt=1,
                      pid=4242, pgid=4242, started_wall="w1", path=path)
    st.update_started_wall(job_id=orphan_handle.job_id, expected_attempt=1,
                           pid=4242, started_wall="w2", path=path)
    jobs = st.mark_restart_orphans_pending(path=path)
    job = st.mark_restart_orphan_pending(path=path)
    assert jobs and job is not None
    st.append_completion_entry(job, exit_code=0, outcome="orphan_gone_or_reused",
                               final_model="opus", path=path, mark_cleanup_recorded=True)
    st.finalize_restart_orphan_cleanup(path=path, job_id=orphan_handle.job_id)
    st.finish_phase_z(cohort_id=orphan_handle.cohort_id, path=path)
    retry_handle = st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                                   log_path="/tmp/y.log", path=path)
    st.attach_process(job_id=retry_handle.job_id, expected_attempt=1,
                      pid=99, pgid=99, started_wall="w3", path=path)
    st.record_completion(job_id=retry_handle.job_id, expected_attempt=1, expected_pid=99,
                         exit_code=1, outcome="failure", final_model="opus",
                         release_slot=False, path=path)
    st.begin_attempt(job_id=retry_handle.job_id, attempt=2, expected_previous_attempt=1,
                     model="opus", log_path="/tmp/y2.log", path=path)
    st.mark_job_phase(job_id=retry_handle.job_id, expected_attempt=2,
                      phase="phase_z", path=path)
    st.release_reservation(path=path, job_id=retry_handle.job_id, expected_attempt=2)

    done = st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                           log_path="/tmp/done.log", path=path)
    st.attach_process(job_id=done.job_id, expected_attempt=1,
                      pid=100, pgid=100, started_wall="wd", path=path)
    token = st.record_completion(job_id=done.job_id, expected_attempt=1, expected_pid=100,
                                 exit_code=0, outcome="success", final_model="opus", path=path)
    assert token is not None
    st.finish_phase_z(cohort_id=done.cohort_id, path=path)

    pending = st.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                              log_path="/tmp/pending.log", path=path)
    st.attach_process(job_id=pending.job_id, expected_attempt=1,
                      pid=101, pgid=101, started_wall="wp", path=path)
    # 第二槽先進 cohort；第一槽完成後留下 phase_z_pending，但 sibling
    # 仍在 current_jobs，正是 multi-slot drain 的 nested shape。
    sibling = st.reserve_fire(
        schedule_id="hourly_dispatch", attempt=2, model="opus",
        log_path="/tmp/z.log", cohort_id=pending.cohort_id, path=path,
    )
    st.record_completion(job_id=pending.job_id, expected_attempt=1, expected_pid=101,
                         exit_code=0, outcome="success", final_model="opus", path=path)
    assert sibling.job_id == st.read_state(path)["current_job"]["job_id"]


def _public_writers_of_state_module() -> set[str]:
    """AST 導出：state.py 裡所有會開 `_locked_state()` 的 public function。"""
    tree = ast.parse(Path(st.__file__).read_text(encoding="utf-8"))
    writers: set[str] = set()
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef) or fn.name.startswith("_"):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.With) and any(
                isinstance(it.context_expr, ast.Call)
                and _is_locked_state_call(it.context_expr)
                for it in node.items
            ):
                writers.add(fn.name)
    return writers


def _writers_driven_by_helper() -> set[str]:
    """AST 導出：`_drive_every_writer` 實際呼叫了哪些 `st.<name>()`。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    fn = next(f for f in tree.body
              if isinstance(f, ast.FunctionDef) and f.name == "_drive_every_writer")
    return {
        node.func.attr for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "st"
    }


def test_drive_every_writer_covers_all_public_writers():
    """窮舉 gate 的前提是「真的驅動了每一個 writer」。那個前提本身必須被檢查。

    否則新增一個 writer 時，`test_no_undocumented_nested_container` 會**靜默地
    不再窮舉** —— 它仍然綠燈，只是不再覆蓋那個 writer 可能長出的新容器。
    2026-07-10 初版就漏了兩個（release_reservation / clear_alert_dedup），而
    commit message 寫著「驅動每一個 public writer」。對程式驗證、對描述不驗證，
    是本 session 反覆復發的病 —— 這條測試把描述也納入驗證。
    """
    writers = _public_writers_of_state_module()
    driven = _writers_driven_by_helper()
    assert writers, "AST 沒抓到任何 public writer（_locked_state 慣例改了？）"
    missed = writers - driven
    assert not missed, (
        f"_drive_every_writer 沒驅動這些 public writer: {sorted(missed)} → "
        f"窮舉 gate 已不再窮舉。請補上呼叫。"
    )


def _container_shapes(node, path="$"):
    """走整棵 state 樹，回傳所有 dict 容器的形狀（list index 正規化成 `[]`）。"""
    if isinstance(node, dict):
        yield path
        for k, v in node.items():
            yield from _container_shapes(v, f"{path}.{k}")
    elif isinstance(node, list):
        for v in node:
            yield from _container_shapes(v, f"{path}[]")


# state 樹的**完整**容器清單。前三個各有 schema 契約 gate 守著；`alerts_dedup`
# 是動態 map（key = alert 名稱，由 caller 決定），沒有固定欄位可 gate，但它必須
# 保持扁平 —— 一旦有人往裡面塞巢狀 dict，就是一個沒人 gate 的新層。
KNOWN_CONTAINERS = {
    "$", "$.current_job", "$.current_jobs[]", "$.phase_z_pending[]",
    "$.completions[]", "$.alerts_dedup",
}


def test_no_undocumented_nested_container(tmp_state):
    """窮舉 gate：state 樹**只能**有已知的四個 dict 容器。

    2026-07-10 的教訓：schema 契約 bug 一層一層被人工發現（頂層 → current_job →
    completions entry），每輪都以為是最後一層。這條測試把「還有沒有下一層」從人的
    信心轉成機械檢查 —— 新增任何巢狀 dict 都會 fail，逼作者去補文件與 gate。
    """
    _drive_every_writer(tmp_state)
    state = st.read_state(tmp_state)
    shapes = set(_container_shapes(state))

    # 範圍自檢：四個容器都得真的長出來，否則「沒有未知容器」只是驅動失敗的假綠燈。
    assert KNOWN_CONTAINERS <= shapes, (
        f"驅動沒長出全部已知容器（假綠燈風險）: 缺 {sorted(KNOWN_CONTAINERS - shapes)}"
    )
    unknown = shapes - KNOWN_CONTAINERS
    assert not unknown, (
        f"state 樹出現未知的巢狀容器 {sorted(unknown)} —— 它沒有 schema 契約 gate。"
        f" 請補進 docstring schema + 對應 shape gate，再加進 KNOWN_CONTAINERS。"
    )

    # alerts_dedup 的 key 是動態的（alert 名稱），不 gate 欄位名；但值必須是純量。
    for k, v in state["alerts_dedup"].items():
        assert not isinstance(v, (dict, list)), (
            f"alerts_dedup[{k!r}] 是 {type(v).__name__} —— 動態 map 必須保持扁平"
        )
