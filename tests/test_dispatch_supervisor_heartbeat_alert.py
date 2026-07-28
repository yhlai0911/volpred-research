"""Regression gate for the dispatch-supervisor wedged-daemon dead-man switch.

The supervisor daemon writes `dispatch_state.json:last_heartbeat_at` every 30s
from `health.health_loop()`. Nothing read it until 2026-07-10 —
`state.get_supervisor_age_seconds()` existed for "an external monitor" that was
never built, so a daemon whose process was alive but whose loops had wedged
raised zero alerts (`cron_review.py`'s launchctl check only sees a process that
has vanished, and launchd's KeepAlive restarts that case anyway).

Arming this switch was only safe once the heartbeat stopped freezing for the
duration of each dispatch — see `test_dispatch_supervisor.py`'s
`test_heartbeat_advances_while_worker_in_flight`.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import (
    DISPATCH_SUPERVISOR_HEARTBEAT_CRITICAL_MINUTES,
    DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES,
    _parse_dispatch_supervisor_heartbeat_state,
)


def _write_state(
    storage_dir: Path,
    now: datetime,
    *,
    age_minutes: float | None,
    current_job: dict | None = None,
) -> None:
    ops = storage_dir / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    state: dict = {
        "version": 1,
        "supervisor_pid": 4242,
        "supervisor_started_at": (now - timedelta(days=1)).isoformat(),
        "current_job": current_job,
        "completions": [],
    }
    if age_minutes is not None:
        state["last_heartbeat_at"] = (now - timedelta(minutes=age_minutes)).isoformat()
    (ops / "dispatch_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_fresh_heartbeat_no_breach(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    _write_state(tmp_path, now, age_minutes=0.5)

    state = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert state["breached"] is False
    assert state["level"] == "info"
    assert state["details"]["supervisor_pid"] == 4242


def test_heartbeat_stays_fresh_during_a_long_dispatch(tmp_path: Path) -> None:
    """The exact false-positive that kept this switch unwired: a healthy fire
    ran 798s. With the beat owned by the non-blocking health loop it stays
    fresh, so an in-flight job must NOT breach.
    """
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    _write_state(
        tmp_path, now, age_minutes=0.4,
        current_job={"pid": 92746, "attempt": 1, "model": "claude-opus-5"},
    )

    state = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert state["breached"] is False
    assert state["details"]["current_job_running"] is True


def test_stale_heartbeat_beyond_warn_breaches_warn(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    _write_state(tmp_path, now, age_minutes=DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES + 1.0)

    state = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert state["breached"] is True
    assert state["level"] == "warn"


def test_wedged_daemon_with_job_in_flight_breaches_critical(tmp_path: Path) -> None:
    """Process alive, job claimed, loops dead — the case launchctl cannot see."""
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    _write_state(
        tmp_path, now,
        age_minutes=DISPATCH_SUPERVISOR_HEARTBEAT_CRITICAL_MINUTES + 5.0,
        current_job={"pid": 92746, "attempt": 1, "model": "claude-opus-5"},
    )

    state = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert state["breached"] is True
    assert state["level"] == "critical"
    assert state["details"]["current_job_running"] is True


def test_missing_state_file_is_not_yet_observed_info(tmp_path: Path) -> None:
    # A live daemon recreates the file within one 30s beat, so absence means it
    # is not running — cron_review.py's launchctl check owns that, not this one.
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)

    state = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert state["breached"] is False
    assert state["level"] == "info"
    assert state["details"]["age_minutes"] is None


def test_corrupt_state_file_degrades_without_raising(tmp_path: Path) -> None:
    # Must never take the whole alert report down with it.
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    ops = tmp_path / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    (ops / "dispatch_state.json").write_text("{not json", encoding="utf-8")

    state = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert state["breached"] is False
    assert state["details"]["age_minutes"] is None


def test_title_is_stable_so_dedup_holds(tmp_path: Path) -> None:
    # sha256(level+title) drives the 24h dedup — a dynamic age in the title
    # would re-send the same breach every hour.
    now = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
    _write_state(tmp_path, now, age_minutes=DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES + 1.0)
    first = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    _write_state(tmp_path, now, age_minutes=DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES + 4.0)
    second = _parse_dispatch_supervisor_heartbeat_state(str(tmp_path), now)

    assert first["title"] == second["title"]
    assert first["details"]["age_minutes"] != second["details"]["age_minutes"]
