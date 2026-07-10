"""Regression tests for the 2026-07-10 pregate rewire (scheduler.py).

Covers the topology-audit fix wiring scripts/hourly_dispatch_pregate.py into
the dispatch-supervisor wake decision:

  * enforce + pregate SKIP  -> slot consumed, worker NOT spawned
  * enforce + pregate PROCEED -> fired
  * shadow mode -> pregate invoked with --shadow semantics, never skips
  * requested fires (boss email -> state.request_fire) are NEVER gated,
    both off-cadence and when consumed on a due cron slot
  * missing/invalid pregate config -> mode off (fail-open, no gating)
  * _run_pregate subprocess exit semantics: only exit 0 skips; crash /
    unexpected exit / timeout are fail-open PROCEED

Run::
    uv run pytest scripts/tests/test_scheduler_pregate.py -v
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.dispatch_supervisor import scheduler, state as st

CRON = "7 * * * *"


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    """State with a STALE last_fire_at, i.e. a genuinely due tick.

    2026-07-10: this used to be a bare empty state, relying on
    `last_fire_at is None -> due`. That coupling is exactly the off-slot
    duplicate-fire bug (unknown state must not mean "fire now"), so due-ness is
    now expressed the way production expresses it: an old timestamp.
    Bootstrap-path tests build their own fresh state instead.
    """
    p = tmp_path / "dispatch_state.json"
    with st._locked_state(p) as (_fh, data):
        data["last_fire_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    return p


@pytest.fixture
def fresh_state(tmp_path: Path) -> Path:
    """Never-written state — cold start / external state loss."""
    return tmp_path / "fresh_dispatch_state.json"


@pytest.fixture
def prompt_file(tmp_path: Path) -> Path:
    p = tmp_path / "prompt.md"
    p.write_text("test prompt", encoding="utf-8")
    return p


def _schedules_file(tmp_path: Path, pregate: dict | None) -> Path:
    entry: dict = {"id": "volpred-hourly-dispatch", "schedule": CRON}
    if pregate is not None:
        entry["pregate"] = pregate
    p = tmp_path / "runtime_schedules.json"
    p.write_text(json.dumps({"cron_jobs": [entry]}), encoding="utf-8")
    return p


@pytest.fixture
def worker_calls(monkeypatch: pytest.MonkeyPatch) -> list:
    """Mock worker + phase_z; return the list of run_worker call kwargs."""
    calls: list = []

    def fake_run_worker(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(outcome="succeeded", attempts=1, duration_s=0.1, exit_code=0)

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)
    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", lambda **kw: {"skipped": True})
    return calls


def _tick(tmp_state: Path, prompt_file: Path, schedules_path: Path):
    return asyncio.run(
        scheduler._tick_once(
            state_path=tmp_state, cron_expr=CRON,
            prompt_path=prompt_file, log_path=prompt_file.parent / "worker.log",
            dry_run=False, schedules_path=schedules_path,
        )
    )


# ---------------------------------------------------------------- _tick_once

def test_enforce_skip_consumes_slot_without_worker(
    tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch
) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "enforce", "window_hours": 3.0})
    monkeypatch.setattr(scheduler, "_run_pregate", lambda **kw: True)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "pregate_skip"
    assert worker_calls == []  # no ~95K cold-load spent
    # slot consumed: next tick within the same hour must be not_due
    assert st.read_state(tmp_state)["last_fire_at"] is not None
    result2 = _tick(tmp_state, prompt_file, schedules)
    assert result2 == {"action": "skip", "reason": "not_due", "prev_fire": result2["prev_fire"]}


def test_enforce_proceed_fires(tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "enforce", "window_hours": 3.0})
    monkeypatch.setattr(scheduler, "_run_pregate", lambda **kw: False)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert result["fire_reason"] == "cron"
    assert len(worker_calls) == 1
    assert worker_calls[0]["fire_reason"] == "cron"
    assert worker_calls[0]["scheduled_for"].endswith(":07:00")


def test_shadow_mode_invokes_pregate_but_fires(
    tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch
) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "shadow", "window_hours": 3.0})
    seen: list = []

    def fake_pregate(**kw):
        seen.append(kw)
        return False  # shadow pregate never skips by construction (exit 1)

    monkeypatch.setattr(scheduler, "_run_pregate", fake_pregate)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert seen and seen[0]["mode"] == "shadow"
    assert len(worker_calls) == 1


def test_requested_fire_off_cadence_bypasses_pregate(
    tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch
) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "enforce", "window_hours": 3.0})
    # last_fire_at = now -> cron not due; only the request can fire
    with st._locked_state(tmp_state) as (_fh, data):
        data["last_fire_at"] = st._now()
    st.request_fire("boss-email", path=tmp_state)

    def pregate_must_not_run(**kw):  # pragma: no cover - failure path
        raise AssertionError("pregate must never gate a requested fire")

    monkeypatch.setattr(scheduler, "_run_pregate", pregate_must_not_run)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert result["fire_reason"] == "requested:boss-email"
    assert len(worker_calls) == 1
    assert worker_calls[0]["fire_reason"] == "requested:boss-email"
    assert worker_calls[0]["scheduled_for"].endswith(":07:00")


def test_request_consumed_on_due_cron_bypasses_pregate(
    tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch
) -> None:
    """Cron due AND a pending request: the request is consumed by the same
    fire — it must mark the fire as requested so pregate cannot eat it."""
    schedules = _schedules_file(tmp_path, {"mode": "enforce", "window_hours": 3.0})
    st.request_fire("boss-email", path=tmp_state)  # tmp_state is stale -> cron due

    def pregate_must_not_run(**kw):  # pragma: no cover - failure path
        raise AssertionError("pregate must never gate a requested fire")

    monkeypatch.setattr(scheduler, "_run_pregate", pregate_must_not_run)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert result["fire_reason"] == "cron+requested:boss-email"
    assert len(worker_calls) == 1
    assert worker_calls[0]["fire_reason"] == "cron+requested:boss-email"
    assert worker_calls[0]["scheduled_for"].endswith(":07:00")


def test_mode_off_never_invokes_pregate(
    tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch
) -> None:
    schedules = _schedules_file(tmp_path, pregate=None)

    def pregate_must_not_run(**kw):  # pragma: no cover - failure path
        raise AssertionError("pregate must not run when mode=off")

    monkeypatch.setattr(scheduler, "_run_pregate", pregate_must_not_run)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert len(worker_calls) == 1


# ---------------------------------------------------------- load_pregate_config

def test_load_pregate_config_missing_file_is_off(tmp_path) -> None:
    cfg = scheduler.load_pregate_config(schedules_path=tmp_path / "nope.json")
    assert cfg["mode"] == "off"


def test_load_pregate_config_invalid_mode_is_off(tmp_path) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "yolo", "window_hours": 3.0})
    cfg = scheduler.load_pregate_config(schedules_path=schedules)
    assert cfg["mode"] == "off"


def test_load_pregate_config_invalid_window_defaults(tmp_path) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "enforce", "window_hours": "abc"})
    cfg = scheduler.load_pregate_config(schedules_path=schedules)
    assert cfg == {"mode": "enforce", "window_hours": 3.0}


def test_load_pregate_config_valid(tmp_path) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "shadow", "window_hours": 6})
    cfg = scheduler.load_pregate_config(schedules_path=schedules)
    assert cfg == {"mode": "shadow", "window_hours": 6.0}


def test_load_pregate_config_absent_block_is_off(tmp_path) -> None:
    schedules = _schedules_file(tmp_path, pregate=None)
    cfg = scheduler.load_pregate_config(schedules_path=schedules)
    assert cfg["mode"] == "off"


# --------------------------------------------------------------- _run_pregate

def _fake_run(returncode: int):
    def fake(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")
    return fake


def test_run_pregate_exit0_skips(monkeypatch) -> None:
    monkeypatch.setattr(scheduler.subprocess, "run", _fake_run(0))
    assert scheduler._run_pregate(mode="enforce", window_hours=3.0) is True


def test_run_pregate_exit1_proceeds(monkeypatch) -> None:
    monkeypatch.setattr(scheduler.subprocess, "run", _fake_run(1))
    assert scheduler._run_pregate(mode="enforce", window_hours=3.0) is False


def test_run_pregate_crash_exit_fail_open(monkeypatch) -> None:
    monkeypatch.setattr(scheduler.subprocess, "run", _fake_run(3))
    assert scheduler._run_pregate(mode="enforce", window_hours=3.0) is False


def test_run_pregate_timeout_fail_open(monkeypatch) -> None:
    def fake(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 60))

    monkeypatch.setattr(scheduler.subprocess, "run", fake)
    assert scheduler._run_pregate(mode="enforce", window_hours=3.0) is False


def test_run_pregate_spawn_error_fail_open(monkeypatch) -> None:
    def fake(cmd, **kwargs):
        raise OSError("no such interpreter")

    monkeypatch.setattr(scheduler.subprocess, "run", fake)
    assert scheduler._run_pregate(mode="enforce", window_hours=3.0) is False


def test_run_pregate_shadow_passes_flag(monkeypatch) -> None:
    seen: dict = {}

    def fake(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(scheduler.subprocess, "run", fake)
    assert scheduler._run_pregate(mode="shadow", window_hours=3.0) is False
    assert "--shadow" in seen["cmd"]


def test_run_pregate_stamps_supervisor_invoker(monkeypatch) -> None:
    """2026-07-10 歸因硬規：daemon 呼叫必帶 --invoker supervisor —
    交叉核對只採 supervisor entries，手動/測試 entries 不污染觀察資料。"""
    seen: dict = {}

    def fake(cmd, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(scheduler.subprocess, "run", fake)
    scheduler._run_pregate(mode="enforce", window_hours=3.0)
    cmd = seen["cmd"]
    assert "--invoker" in cmd
    assert cmd[cmd.index("--invoker") + 1] == "supervisor"


# ── 2026-07-10 off-slot duplicate fire root cause ──────────────────────────
# `_due_to_fire` used to `return True` on a missing/unparseable last_fire_at.
# "We don't know when we last fired" is NOT "fire right now" — in a 60s-tick
# daemon that turned every loss of dispatch_state.json into an immediate ~95K
# opus cold-load. Log audit found 9 such off-slot fires in 159 (+24..+54 min
# after their slot). The daemon never logged a reset of its own, so the state
# was clobbered by an external writer.


def test_due_to_fire_missing_last_fire_is_not_due() -> None:
    due, _prev = scheduler._due_to_fire(cron_expr=CRON, last_fire_at=None)
    assert due is False


def test_due_to_fire_unparseable_last_fire_is_not_due() -> None:
    due, _prev = scheduler._due_to_fire(cron_expr=CRON, last_fire_at="not-a-timestamp")
    assert due is False


def test_due_to_fire_still_fires_when_slot_genuinely_missed() -> None:
    """The safety fix must not break normal catch-up of a real missed slot."""
    from datetime import datetime as _dt

    now = _dt(2026, 7, 10, 22, 58, 25)          # naive local, as croniter uses
    stale = "2026-07-10T12:07:51.000000+08:00"  # long before the 22:07 slot
    due, prev = scheduler._due_to_fire(cron_expr=CRON, last_fire_at=stale, now=now)
    assert due is True
    assert prev.hour == 22 and prev.minute == 7


def test_due_to_fire_not_due_when_slot_already_served() -> None:
    """The 22:58 incident: 22:07 slot was already fired at 22:07:51.

    `_due_to_fire` resolves in the daemon's LOCAL timezone: `_parse_last_fire`
    does `.astimezone().replace(tzinfo=None)` on the tz-aware stored value, then
    compares it against croniter's tz-NAIVE prev-slot. The stored value here is
    14:07:51 UTC == 22:07:51 Asia/Taipei, i.e. just after the 22:07 slot — but
    only *in Taipei*. On a UTC runner (CI) it reads as 14:07, hours before the
    slot, so the served slot wrongly looks due (this is the True-is-False CI
    failure). The daemon runs in Asia/Taipei, so pin that here instead of letting
    the machine's zone decide; without tzset this passed only by accident of
    being run in +08. (Production tz-fragility — `_due_to_fire` silently depends
    on the host zone — escalated in docs/error_log.md 2026-07-11.)
    """
    import os
    import time
    from datetime import datetime as _dt

    _orig_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Taipei"
    time.tzset()
    try:
        now = _dt(2026, 7, 10, 22, 58, 25)
        served = "2026-07-10T14:07:51.094696+00:00"  # == 22:07:51 Taipei
        due, _prev = scheduler._due_to_fire(cron_expr=CRON, last_fire_at=served, now=now)
        assert due is False
    finally:
        if _orig_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = _orig_tz
        time.tzset()


def test_tick_bootstraps_missing_last_fire_and_does_not_spawn(
    tmp_path, fresh_state, prompt_file, worker_calls
) -> None:
    """State loss must cost at most a skipped hour — never a stray cold-load."""
    schedules = _schedules_file(tmp_path, {"mode": "off"})
    result = _tick(fresh_state, prompt_file, schedules)
    assert result == {"action": "skip", "reason": "bootstrap_last_fire_at"}
    assert worker_calls == []
    assert st.read_state(fresh_state)["last_fire_at"] is not None


def test_tick_bootstraps_unparseable_last_fire(tmp_path, tmp_state, prompt_file, worker_calls) -> None:
    schedules = _schedules_file(tmp_path, {"mode": "off"})
    with st._locked_state(tmp_state) as (_fh, data):
        data["last_fire_at"] = "garbage"
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["reason"] == "bootstrap_last_fire_at"
    assert worker_calls == []
    # self-healed: the corrupt value is replaced, so the daemon can never stall
    assert scheduler._parse_last_fire(st.read_state(tmp_state)["last_fire_at"]) is not None


def test_daemon_never_stalls_forever_after_bootstrap(
    tmp_path, fresh_state, prompt_file, worker_calls, monkeypatch
) -> None:
    """Bootstrap is a one-tick cost: the next real slot must still fire.

    Guards the failure mode introduced by the fix itself — 'unknown is not due'
    would stall the daemon permanently if nothing ever wrote the field back.
    """
    schedules = _schedules_file(tmp_path, {"mode": "off"})
    assert _tick(fresh_state, prompt_file, schedules)["reason"] == "bootstrap_last_fire_at"
    # time passes -> the stamped value is now older than the latest slot
    with st._locked_state(fresh_state) as (_fh, data):
        data["last_fire_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
    result = _tick(fresh_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert len(worker_calls) == 1
