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
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.dispatch_supervisor import scheduler, state as st

CRON = "7 * * * *"


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


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


def test_request_consumed_on_due_cron_bypasses_pregate(
    tmp_path, tmp_state, prompt_file, worker_calls, monkeypatch
) -> None:
    """Cron due AND a pending request: the request is consumed by the same
    fire — it must mark the fire as requested so pregate cannot eat it."""
    schedules = _schedules_file(tmp_path, {"mode": "enforce", "window_hours": 3.0})
    st.request_fire("boss-email", path=tmp_state)  # last_fire_at None -> due

    def pregate_must_not_run(**kw):  # pragma: no cover - failure path
        raise AssertionError("pregate must never gate a requested fire")

    monkeypatch.setattr(scheduler, "_run_pregate", pregate_must_not_run)
    result = _tick(tmp_state, prompt_file, schedules)
    assert result["action"] == "fired"
    assert result["fire_reason"] == "cron+requested:boss-email"
    assert len(worker_calls) == 1


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
