"""Self-reload gate — regression cover for "the fix was committed but never ran".

The incidents this locks down (all 2026-07-13):
  - 15:19  procutil.py fix committed, daemon kept running the old code.
  - 21:53  phase_z.py livelock fix + 22:04 dedup fix, same — and because the old
           code was still live, the owner kept getting the alert those very
           commits had removed.

The dangerous failure mode of the cure is worse than the disease: a self-reload
that fires mid-fire SIGTERMs the daemon while a worker is running, orphaning or
killing an agent's uncommitted work. `test_defers_while_a_job_is_in_flight` is
the one that must never go green-by-accident.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import selfreload, state


@pytest.fixture(autouse=True)
def _rearm():
    """`_ARMED` is process-global (one self-reload per process). Reset per test."""
    selfreload._ARMED = True
    yield
    selfreload._ARMED = True


NOW = datetime(2026, 7, 13, 22, 30, tzinfo=timezone.utc)
BOOT = NOW - timedelta(hours=4)  # daemon booted at 17:58, like the real one


def _src_dir(tmp_path: Path, *, mtimes: dict[str, datetime]) -> Path:
    src = tmp_path / "dispatch_supervisor"
    src.mkdir()
    for name, mtime in mtimes.items():
        f = src / name
        f.write_text("# module\n")
        ts = mtime.timestamp()
        os.utime(f, (ts, ts))
    return src


def _state_file(tmp_path: Path, *, boot: datetime | None, jobs: list[dict]) -> Path:
    import json

    p = tmp_path / "dispatch_state.json"
    payload: dict = {"version": state.SCHEMA_VERSION, "current_jobs": jobs}
    if boot is not None:
        payload["supervisor_started_at"] = boot.isoformat()
    p.write_text(json.dumps(payload))
    return p


def _job() -> dict:
    return {
        "job_id": "abc123", "cohort_id": "c1", "slot_id": 1, "phase": "running",
        "pid": 4242, "pgid": 4242, "started_wall": "Mon Jul 13 22:00:36 2026",
        "started_at": NOW.isoformat(), "attempt": 1,
    }


class _Exit:
    def __init__(self) -> None:
        self.called = 0

    def __call__(self) -> None:
        self.called += 1


def _run(tmp_path, *, mtimes, boot=BOOT, jobs=(), now=NOW, monkeypatch=None):
    src = _src_dir(tmp_path, mtimes=mtimes)
    st = _state_file(tmp_path, boot=boot, jobs=list(jobs))
    exit_fn = _Exit()
    marker = tmp_path / "restart_marker.json"
    if monkeypatch is not None:
        monkeypatch.setattr(state, "RESTART_MARKER_PATH", marker)
    action = selfreload.maybe_self_reload(
        state_path=st, src_dir=src, now=now, exit_fn=exit_fn,
    )
    return action, exit_fn, marker


def test_reloads_when_code_is_newer_than_boot_and_daemon_is_idle(tmp_path, monkeypatch):
    """The 21:53 incident: phase_z.py committed after boot, daemon idle, nothing happened."""
    action, exit_fn, marker = _run(
        tmp_path,
        mtimes={"phase_z.py": NOW - timedelta(minutes=30)},  # edited well after boot, settled
        monkeypatch=monkeypatch,
    )
    assert action == "reload"
    assert exit_fn.called == 1
    # The marker must exist BEFORE we die, or the fresh boot reports itself as a
    # crash and emails the owner deploy noise.
    assert marker.exists()
    assert "self-reload" in marker.read_text()


def test_defers_while_a_job_is_in_flight(tmp_path, monkeypatch):
    """THE dangerous case. Reloading mid-fire SIGTERMs the daemon and takes the
    worker's process group with it — an agent's uncommitted work, destroyed."""
    action, exit_fn, _ = _run(
        tmp_path,
        mtimes={"phase_z.py": NOW - timedelta(minutes=30)},
        jobs=[_job()],
        monkeypatch=monkeypatch,
    )
    assert action == "deferred_in_flight"
    assert exit_fn.called == 0


def test_defers_while_an_agent_is_still_writing(tmp_path, monkeypatch):
    """An agent saves several modules seconds apart. Reloading on the first save
    boots us onto a half-applied change set."""
    action, exit_fn, _ = _run(
        tmp_path,
        mtimes={"phase_z.py": NOW - timedelta(seconds=5)},
        monkeypatch=monkeypatch,
    )
    assert action == "deferred_quiescing"
    assert exit_fn.called == 0


def test_no_reload_when_running_code_matches_disk(tmp_path, monkeypatch):
    action, exit_fn, _ = _run(
        tmp_path,
        mtimes={"phase_z.py": BOOT - timedelta(hours=1)},
        monkeypatch=monkeypatch,
    )
    assert action == "current"
    assert exit_fn.called == 0


def test_future_dated_source_is_not_stale(tmp_path, monkeypatch):
    """Clock skew / a bad `touch` would otherwise keep the comparison true across
    every restart — a boot loop, which is strictly worse than stale code."""
    action, exit_fn, _ = _run(
        tmp_path,
        mtimes={"phase_z.py": NOW + timedelta(hours=1)},
        monkeypatch=monkeypatch,
    )
    assert action == "current"
    assert exit_fn.called == 0


def test_reloads_at_most_once_per_process(tmp_path, monkeypatch):
    src = _src_dir(tmp_path, mtimes={"phase_z.py": NOW - timedelta(minutes=30)})
    st = _state_file(tmp_path, boot=BOOT, jobs=[])
    monkeypatch.setattr(state, "RESTART_MARKER_PATH", tmp_path / "m.json")
    exit_fn = _Exit()

    first = selfreload.maybe_self_reload(state_path=st, src_dir=src, now=NOW, exit_fn=exit_fn)
    # exit_fn is a stub, so control returns here — in production SIGTERM ends us.
    second = selfreload.maybe_self_reload(state_path=st, src_dir=src, now=NOW, exit_fn=exit_fn)

    assert first == "reload"
    assert second == "current"
    assert exit_fn.called == 1


def test_unknown_boot_time_never_reloads(tmp_path, monkeypatch):
    """No `supervisor_started_at` → we cannot judge freshness. Staying on stale
    code is a missed improvement; guessing could restart-loop the daemon."""
    action, exit_fn, _ = _run(
        tmp_path,
        mtimes={"phase_z.py": NOW - timedelta(minutes=30)},
        boot=None,
        monkeypatch=monkeypatch,
    )
    assert action == "current"
    assert exit_fn.called == 0


def test_health_loop_wires_selfreload():
    """Anti-orphan: the detector is worthless if nothing calls it. `git_conflict_guard`
    sat un-wired for six days because 'not running' and 'ran, found nothing' look
    identical from outside (see .claude/rules/control-plane.md)."""
    import inspect

    from scripts.dispatch_supervisor import health

    assert "maybe_self_reload" in inspect.getsource(health.health_loop)
