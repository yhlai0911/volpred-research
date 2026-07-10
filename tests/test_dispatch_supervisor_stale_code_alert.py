"""Dead-man switch for "the fix was written but never went live".

2026-07-10: three fixes (quota no-retry, gmail fire-request double-dispatch race,
restart-alert noise) were written, committed, and their tasks closed as solved,
while the daemon kept running code it had imported hours earlier. Nobody noticed
for 3+ hours — a daemon on stale code is indistinguishable from a healthy one:
fresh heartbeat, jobs completing, zero alerts.

`.claude/rules/control-plane.md` gained the rule "程式碼寫完不等於上線" that same
morning. It was violated three times before the day ended. Prose does not survive
a handoff between agents.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import (
    DISPATCH_SUPERVISOR_STALE_CODE_CRITICAL_MINUTES,
    DISPATCH_SUPERVISOR_STALE_CODE_WARN_MINUTES,
    _parse_dispatch_supervisor_stale_code_state,
)

NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


def _setup(tmp_path: Path, *, boot_minutes_ago: float, edits: dict[str, float]) -> tuple[str, Path]:
    """`edits` maps filename -> minutes ago it was edited (relative to NOW)."""
    ops = tmp_path / "storage" / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    (ops / "dispatch_state.json").write_text(
        json.dumps({
            "version": 1,
            "supervisor_started_at": (NOW - timedelta(minutes=boot_minutes_ago)).isoformat(),
            "last_heartbeat_at": NOW.isoformat(),
            "current_job": None,
            "completions": [],
        }),
        encoding="utf-8",
    )
    src = tmp_path / "scripts" / "dispatch_supervisor"
    src.mkdir(parents=True, exist_ok=True)
    for name, minutes_ago in edits.items():
        f = src / name
        f.write_text("# noop\n", encoding="utf-8")
        ts = (NOW - timedelta(minutes=minutes_ago)).timestamp()
        os.utime(f, (ts, ts))
    return str(tmp_path / "storage"), src


def test_all_code_older_than_boot_is_ok(tmp_path: Path) -> None:
    storage, src = _setup(tmp_path, boot_minutes_ago=30, edits={"state.py": 90.0})

    out = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)

    assert out["breached"] is False
    assert out["level"] == "info"
    assert out["details"]["stale_files"] == []


def test_todays_incident_reproduces_as_critical(tmp_path: Path) -> None:
    """The real shape: daemon booted 13:48, fixes landed 16:12 / 16:38 / 17:17,
    still running old code at 17:20. Boot 212 min ago; edits 68/42/3 min ago.
    """
    storage, src = _setup(
        tmp_path,
        boot_minutes_ago=212,
        edits={"worker.py": 68.0, "scheduler.py": 42.0, "alerts.py": 3.0},
    )

    out = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)

    assert out["breached"] is True
    names = {s["file"] for s in out["details"]["stale_files"]}
    # alerts.py was edited 3 min ago — an agent may still be mid-edit, so it is
    # tracked but must NOT be what raises the alarm.
    assert names == {"worker.py", "scheduler.py"}
    assert [s["file"] for s in out["details"]["unsettled_files"]] == ["alerts.py"]


def test_a_settled_edit_beyond_warn_is_warn(tmp_path: Path) -> None:
    storage, src = _setup(
        tmp_path, boot_minutes_ago=60,
        edits={"health.py": DISPATCH_SUPERVISOR_STALE_CODE_WARN_MINUTES + 5.0},
    )

    out = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)

    assert out["breached"] is True
    assert out["level"] == "warn"


def test_long_undeployed_edit_escalates_to_critical(tmp_path: Path) -> None:
    storage, src = _setup(
        tmp_path, boot_minutes_ago=300,
        edits={"health.py": DISPATCH_SUPERVISOR_STALE_CODE_CRITICAL_MINUTES + 10.0},
    )

    out = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)

    assert out["level"] == "critical"


def test_agent_mid_edit_does_not_breach(tmp_path: Path) -> None:
    """An edit seconds old is someone working, not a forgotten deploy. Without
    this grace the alert would fire on every agent that touches the daemon.
    """
    storage, src = _setup(tmp_path, boot_minutes_ago=60, edits={"state.py": 0.5})

    out = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)

    assert out["breached"] is False
    assert [s["file"] for s in out["details"]["unsettled_files"]] == ["state.py"]


def test_reload_clears_the_breach(tmp_path: Path) -> None:
    """The remediation must actually resolve it: after a reload the boot time is
    newer than every edit, so nothing is stale.
    """
    storage, src = _setup(tmp_path, boot_minutes_ago=200, edits={"worker.py": 100.0})
    assert _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)["breached"]

    ops = Path(storage) / "ops" / "dispatch_state.json"
    data = json.loads(ops.read_text())
    data["supervisor_started_at"] = (NOW - timedelta(minutes=1)).isoformat()  # just reloaded
    ops.write_text(json.dumps(data), encoding="utf-8")

    out = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)
    assert out["breached"] is False


def test_beating_daemon_with_no_boot_time_breaches(tmp_path: Path) -> None:
    """The exact shape left behind at 2026-07-10 23:02, when a test wrote
    `_empty_state()` over the canonical file: heartbeat fresh, `completions`
    empty, `supervisor_started_at` null. With `boot is None` the mtime loop finds
    nothing and the old code answered `ok` — blind precisely when it mattered.
    """
    ops = tmp_path / "storage" / "ops"
    ops.mkdir(parents=True)
    (ops / "dispatch_state.json").write_text(
        json.dumps({
            "version": 1,
            "supervisor_pid": 85741,
            "supervisor_started_at": None,   # wiped
            "last_heartbeat_at": NOW.isoformat(),  # still beating
            "current_job": None,
            "completions": [],
        }),
        encoding="utf-8",
    )
    src = tmp_path / "scripts" / "dispatch_supervisor"
    src.mkdir(parents=True)

    out = _parse_dispatch_supervisor_stale_code_state(str(tmp_path / "storage"), NOW, supervisor_dir=src)

    assert out["breached"] is True
    assert out["details"]["supervisor_started_at"] is None
    assert "開機時間" in out["title"]


def test_missing_state_is_not_yet_observed(tmp_path: Path) -> None:
    # `dispatch_supervisor_heartbeat` owns "is the daemon alive"; don't double-alert.
    src = tmp_path / "scripts" / "dispatch_supervisor"
    src.mkdir(parents=True)
    out = _parse_dispatch_supervisor_stale_code_state(str(tmp_path / "storage"), NOW, supervisor_dir=src)

    assert out["breached"] is False
    assert out["details"]["supervisor_started_at"] is None


def test_corrupt_state_degrades_without_raising(tmp_path: Path) -> None:
    ops = tmp_path / "storage" / "ops"
    ops.mkdir(parents=True)
    (ops / "dispatch_state.json").write_text("{not json", encoding="utf-8")
    src = tmp_path / "scripts" / "dispatch_supervisor"
    src.mkdir(parents=True)

    out = _parse_dispatch_supervisor_stale_code_state(str(tmp_path / "storage"), NOW, supervisor_dir=src)

    assert out["breached"] is False


def test_title_is_stable_so_dedup_holds(tmp_path: Path) -> None:
    storage, src = _setup(tmp_path, boot_minutes_ago=200, edits={"worker.py": 60.0})
    first = _parse_dispatch_supervisor_stale_code_state(storage, NOW, supervisor_dir=src)
    storage2, src2 = _setup(tmp_path / "b", boot_minutes_ago=200, edits={"worker.py": 90.0})
    second = _parse_dispatch_supervisor_stale_code_state(storage2, NOW, supervisor_dir=src2)

    assert first["title"] == second["title"]
    assert first["details"]["oldest_age_minutes"] != second["details"]["oldest_age_minutes"]
