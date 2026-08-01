from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import io
import json
import logging
import os
import resource
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import task_pool_claim
from scripts.dispatch_supervisor import (
    auth_lease_reaper,
    claim_release,
    deferred_reload,
    health,
    isolation,
    phase_z,
    procutil,
    scheduler,
    state,
    supervisor,
    worker,
    workspace,
)
from volpred.ops import legacy_retirement_events
from volpred.ops.legacy_retirement import LegacyRetirementInputError


@pytest.fixture(autouse=True)
def _provider_guard_stub(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Scheduler admission now reads the durable reload request.  Every test
    # must use an isolated request root; consulting ~/.volpred here would make
    # a real production deploy change hermetic scheduler expectations.
    monkeypatch.setenv(
        "VOLPRED_DEFERRED_RELOAD_ROOT",
        str(tmp_path / "deferred-reload"),
    )

    def authorize(**kwargs):
        environment = kwargs["environment"]
        forbidden = [
            key
            for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
            if environment.get(key)
        ]
        if forbidden:
            raise worker.ProviderRegistryError(
                f"forbidden API-key variables {forbidden}"
            )
        return SimpleNamespace(
            resolved_executable=kwargs["executable_path"],
            settings_path="/tmp/pinned-claude-settings.json",
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "claude-cli",
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
        )

    monkeypatch.setattr(worker, "authorize_provider_spawn", authorize)
    monkeypatch.setattr(worker, "verify_spawn_receipt", lambda _receipt: None)


def _tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


def _stub_worker_custody(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    custody = {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001],
    }
    monkeypatch.setattr(
        worker.procutil,
        "capture_producer_custody",
        lambda: dict(custody),
    )
    monkeypatch.setattr(
        worker.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(
        worker.state,
        "attach_producer_custody",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        worker.state,
        "mark_producer_spawn_committed",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        worker.state,
        "mark_producer_spawn_aborted",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        worker.workspace_mod,
        "bind_producer_custody",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        worker.custody_receipt,
        "bind_producer_custody",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        worker.custody_receipt,
        "release_producer_custody",
        lambda *_args, **_kwargs: True,
    )
    return custody


def _bind_drained_workspace_custody(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo: Path,
    workspace_receipt: dict,
    job_id: str,
) -> dict[str, object]:
    """Give a sweep fixture the same durable pre-Popen receipt as production."""
    custody = {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001],
    }
    assert workspace.bind_producer_custody(
        repo,
        workspace=workspace_receipt,
        job_id=job_id,
        producer_custody=custody,
        attempt=1,
    )
    monkeypatch.setattr(
        workspace.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    return custody


def _reserve_like_production(kwargs: dict, *, pid: int = 4242, pgid: int = 4242) -> None:
    """Do the slot bookkeeping the real `_run_one_attempt` does before Popen.

    Since the race-winner token landed (2026-07-12, state.record_completion),
    a hang alert is only mailed by whoever atomically clears `current_job` —
    the loser of the race against health.py's watchdog must stay silent, or it
    mails a job it can no longer see. A fake `_run_one_attempt` that never
    reserves the slot leaves nothing to clear, so `record_completion()` hands
    back None and the worker takes the LOSER branch: no alert, on a path
    production always alerts on. That is what turned the three hang tests red —
    a stale fixture, not a regression. Fakes must honor the same state contract
    as production: reserve, then attach.

    The winner/loser contract itself is owned by
    `scripts/tests/test_hang_alert_ownership.py` (both callers, both outcomes,
    exactly-one-mail). Don't re-assert it here — the hang tests below only care
    that a hang short-circuits retry and normalizes its exit code.
    """
    state.attach_process(
        job_id=kwargs["job_id"], expected_attempt=kwargs["attempt"],
        pid=pid, pgid=pgid, started_wall=None, path=kwargs["state_path"],
    )
    state.mark_job_phase(
        job_id=kwargs["job_id"], expected_attempt=kwargs["attempt"],
        expected_phase="running", expected_pid=pid,
        phase="classifying", path=kwargs["state_path"],
    )


def _seed_due(state_path: Path) -> None:
    """Seed a stale last_fire_at so `_due_to_fire()` returns True — a genuinely due tick.

    Since 2026-07-10 (9c4f73e21) a missing/unparseable last_fire_at is NOT due:
    the daemon bootstraps the field and skips, which killed the off-slot
    duplicate-fire bug (unknown state must not mean "fire now"). A fire-path test
    must therefore express due-ness the way production does — a stale timestamp —
    rather than leaning on an empty state file, which would reassert the exact bug
    the commit fixed. Mirrors the `due_state` fixture in test_scheduler_pregate.py.
    """
    with state._locked_state(state_path) as (_fh, data):
        data["last_fire_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


@pytest.fixture(autouse=True)
def _stub_external_alerts_and_custody(monkeypatch) -> None:
    monkeypatch.setattr(
        scheduler.phase_z, "_default_internal_alert",
        lambda **_kwargs: {"sent": True, "test_stub": True},
    )
    monkeypatch.setattr(
        scheduler.custody_receipt,
        "reconcile_pending_producer_custodies",
        lambda _repo_root: {
            "ok": True,
            "pending_count": 0,
            "released": [],
            "unresolved": [],
        },
    )
    monkeypatch.setattr(
        health.custody_receipt,
        "reconcile_pending_producer_custodies",
        lambda _repo_root: {
            "ok": True,
            "pending_count": 0,
            "released": [],
            "unresolved": [],
        },
    )


@pytest.fixture(autouse=True)
def _never_touch_the_real_task_pool(monkeypatch, tmp_path: Path) -> Path:
    """Redirect the canonical claim CLI's pool at an empty tmp file.

    Since WS-A2b a force-kill re-pends the claim its dead fire was holding,
    which means EVERY hang test now reaches a next_tasks.json writer. Against
    the real path that raises CanonicalWriteBlocked (a BaseException the
    production fail-open handler deliberately cannot swallow). Autouse for the
    same reason as the pregate stub above: opt-in protection is not protection.
    """
    pool = tmp_path / "autouse_next_tasks.json"
    pool.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(health._task_pool_claim(), "NEXT_TASKS", pool)
    return pool


def test_worker_transient_retry_then_success(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    sleeps: list[int] = []
    alerts_called: list[tuple] = []
    attempts: list[tuple[int, str]] = []
    outputs = [
        (1, "error: 529 Overloaded"),
        (1, "error: 529 Overloaded again"),
        (0, "ok"),
    ]

    def fake_run_one_attempt(**kwargs):
        attempt = kwargs["attempt"]
        model = kwargs["model"]
        attempts.append((attempt, model))
        exit_code, text = outputs[attempt - 1]
        log_path.write_text(text, encoding="utf-8")
        return exit_code, float(attempt), text

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts,
        "send_completion_failure",
        lambda **kwargs: alerts_called.append(("fail", kwargs)) or True,
    )

    result = worker.run_worker(
        prompt_text="prompt",
        log_path=log_path,
        state_path=state_path,
        sleep_fn=lambda sec: sleeps.append(sec),
    )

    assert result.outcome == "success"
    assert result.attempts == 3
    # 2026-07-05 all-opus directive: every retry attempt is opus (no sonnet drop).
    assert result.final_model == worker.OPUS_MODEL
    assert sleeps == [worker.RETRY_BACKOFF_S, worker.RETRY_BACKOFF_S]
    assert attempts == [
        (1, worker.OPUS_MODEL),
        (2, worker.OPUS_MODEL),
        (3, worker.OPUS_MODEL),
    ]
    assert alerts_called == []


def test_worker_auth_blocks_without_retry(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    attempts: list[int] = []
    auth_alerts: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        state.mark_job_phase(
            job_id=kwargs["job_id"], expected_attempt=kwargs["attempt"],
            phase="classifying", path=kwargs["state_path"],
        )
        log_path.write_text("Not logged in. Please run /login", encoding="utf-8")
        return 1, 1.0, "Not logged in. Please run /login"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts,
        "send_auth_alert",
        lambda **kwargs: auth_alerts.append(kwargs) or True,
    )

    result = worker.run_worker(
        prompt_text="prompt",
        log_path=log_path,
        state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    snap = state.read_state(state_path)
    assert result.outcome == "auth_blocked"
    assert result.attempts == 1
    assert attempts == [1]
    assert snap["auth_blocked"] is True
    assert len(auth_alerts) == 1


def test_worker_hang_alert_and_no_retry(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    hang_alerts: list[dict] = []
    attempts: list[int] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        _reserve_like_production(kwargs)
        kwargs["process_identity_sink"](456)
        log_path.write_text("worker timed out", encoding="utf-8")
        # Our own watchdog kill surfaces as the sentinel (2026-07-21: a raw 137
        # now means an OUTSIDE kill and takes the external_signal path instead).
        return worker.TIMEOUT_KILLED_SENTINEL, 12.0, "worker timed out"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts,
        "send_hang_alert",
        lambda **kwargs: hang_alerts.append(kwargs) or True,
    )

    result = worker.run_worker(
        prompt_text="prompt",
        log_path=log_path,
        state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    assert result.outcome == "killed_timeout"
    assert result.attempts == 1
    assert attempts == [1]
    assert len(hang_alerts) == 1
    assert hang_alerts[0]["job"]["timeout_kind"] == "work_cap"


def test_worker_refuses_when_auth_already_blocked(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    state.set_auth_blocked(True, path=state_path)
    called = {"spawn": 0}

    def fake_run_one_attempt(**kwargs):
        called["spawn"] += 1
        return 0, 1.0, "ok"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)

    result = worker.run_worker(
        prompt_text="prompt",
        log_path=tmp_path / "worker.log",
        state_path=state_path,
    )

    assert result.outcome == "auth_blocked"
    assert result.attempts == 0
    assert called["spawn"] == 0


def test_scheduler_tick_skips_when_auth_blocked(tmp_path: Path) -> None:
    state_path = _tmp_state(tmp_path)
    state.set_auth_blocked(True, path=state_path)

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=tmp_path / "missing.md",
        log_path=tmp_path / "worker.log",
        dry_run=False,
    ))

    assert decision == {"action": "skip", "reason": "auth_blocked"}


def test_scheduler_dry_run_marks_last_fire_without_worker(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    called = {"worker": 0}

    def fake_run_worker(**kwargs):
        called["worker"] += 1
        return None

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=True,
    ))

    snap = state.read_state(state_path)
    assert decision["action"] == "dry_run_fire"
    assert snap["last_fire_at"] is not None
    assert called["worker"] == 0


def test_scheduler_fire_runs_worker_when_due(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    received: list[dict] = []

    def fake_run_worker(**kwargs):
        received.append(kwargs)
        return worker.WorkerResult(
            exit_code=0,
            outcome="success",
            final_model=worker.OPUS_MODEL,
            attempts=1,
            duration_s=2.0,
            log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,  # non-git tmp → phase_z no-ops (status_error); never touch real repo
    ))

    assert decision["action"] == "fired"
    assert decision["outcome"] == "success"
    assert received and received[0]["prompt_text"].endswith("prompt-body")
    assert "worktree_prefix=dispatch-slot-1-" in received[0]["prompt_text"]
    assert "$VOLPRED_TASK_CLAIM_OWNER" in received[0]["prompt_text"]
    assert "禁止退回日期/小時或自訂名稱" in received[0]["prompt_text"]
    assert received[0]["workdir"].is_dir()
    assert tmp_path.resolve() not in received[0]["workdir"].resolve().parents
    scratch_probe = subprocess.run(
        ["git", "-C", str(received[0]["workdir"]), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    assert scratch_probe.returncode != 0
    assert f"launcher_cwd={received[0]['workdir']}" in received[0]["prompt_text"]
    assert "inline task 可用絕對路徑編輯 canonical_root" in received[0]["prompt_text"]


def test_scheduler_carries_generic_preselection_into_prompt_and_worker(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(
        json.dumps({
            "cron_jobs": [
                {"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}
            ],
            "daemons": [{
                "id": "volpred-dispatch-supervisor",
                "max_slots": 1,
                "writer_isolation": {"mode": "pilot", "lanes": ["platform_ops"]},
            }],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scheduler,
        "_preassign_mutating_task",
        lambda **_kwargs: {
            "ok": True,
            "assigned": False,
            "reason": "starved_non_mutating_task",
            "selected_task_id": "article-starved",
        },
    )
    received: list[dict] = []

    def fake_run_worker(**kwargs):
        received.append(kwargs)
        return worker.WorkerResult(
            exit_code=0,
            outcome="success",
            final_model=worker.OPUS_MODEL,
            attempts=1,
            duration_s=1.0,
            log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)
    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
        schedules_path=schedules,
    ))

    assert decision["action"] == "fired"
    assert received[0]["preselected_task_id"] == "article-starved"
    assert "task_id=article-starved" in received[0]["prompt_text"]


def test_scheduler_does_not_admit_next_fire_while_deferred_reload_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #42 regression: a drain request must close the admission gate.

    Production armed request 749b49b3 at 00:59 CST, but the stale process
    admitted job 5738de9c at 01:17 CST after the previous cohort drained.  The
    health loop can activate an immutable release only while both the worker
    and PHASE-Z sets are empty, so admitting another fire here can starve the
    reload forever.
    """
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    before = state.read_state(state_path)
    calls = {"worker": 0, "pre_fire": 0}

    monkeypatch.setattr(
        deferred_reload,
        "active_request_pending",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        scheduler.phase_z,
        "run_pre_fire_guard",
        lambda **_kwargs: calls.__setitem__("pre_fire", calls["pre_fire"] + 1),
    )
    monkeypatch.setattr(
        scheduler.worker,
        "run_worker",
        lambda **_kwargs: calls.__setitem__("worker", calls["worker"] + 1),
    )

    decision = asyncio.run(
        scheduler._tick_once(
            state_path=state_path,
            cron_expr="7 * * * *",
            prompt_path=prompt_path,
            log_path=tmp_path / "worker.log",
            dry_run=False,
            repo_root=tmp_path,
        )
    )

    assert decision == {
        "action": "skip",
        "reason": "deferred_reload_pending",
    }
    assert calls == {"worker": 0, "pre_fire": 0}
    after = state.read_state(state_path)
    assert after["last_fire_at"] == before["last_fire_at"]
    assert after["current_jobs"] == []


def test_reload_winning_final_admission_race_preserves_pending_fire_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reload may arm after the early check but before reservation."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    state.request_fire("owner-urgent-task", path=state_path)
    last_fire_before = state.read_state(state_path)["last_fire_at"]
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")

    monkeypatch.setattr(
        deferred_reload,
        "active_request_pending",
        lambda: False,
    )

    @contextlib.contextmanager
    def reload_wins_at_reservation():
        yield False

    monkeypatch.setattr(
        deferred_reload,
        "admission_gate",
        reload_wins_at_reservation,
    )
    monkeypatch.setattr(
        scheduler.phase_z,
        "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": True,
            "reason": "ok",
            "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    worker_calls: list[dict] = []
    monkeypatch.setattr(
        scheduler.worker,
        "run_worker",
        lambda **kwargs: worker_calls.append(kwargs),
    )

    decision = asyncio.run(
        scheduler._tick_once(
            state_path=state_path,
            cron_expr="7 * * * *",
            prompt_path=prompt_path,
            log_path=tmp_path / "worker.log",
            dry_run=False,
            repo_root=tmp_path,
        )
    )

    assert decision == {
        "action": "skip",
        "reason": "deferred_reload_pending",
    }
    snapshot = state.read_state(state_path)
    assert snapshot["fire_requested_at"] is not None
    assert snapshot["fire_request_reason"] == "owner-urgent-task"
    assert snapshot["current_jobs"] == []
    assert snapshot["last_fire_at"] == last_fire_before
    assert worker_calls == []


def test_atomic_reservation_failure_cannot_consume_pending_fire_request(
    tmp_path: Path,
) -> None:
    """A sibling closeout may make PHASE-Z pending before reservation."""
    state_path = _tmp_state(tmp_path)
    state.request_fire("owner-urgent-task", path=state_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{
            "job_id": "sibling",
            "cohort_id": "cohort-sibling",
            "slot_id": 1,
            "fire_lifecycle": _fire_lifecycle(),
        }]

    with pytest.raises(RuntimeError, match="PHASE-Z drain is pending"):
        state.reserve_fire(
            schedule_id="hourly_dispatch",
            attempt=1,
            model="opus",
            log_path="/tmp/worker.log",
            consume_request=True,
            expected_fire_request="owner-urgent-task",
            path=state_path,
        )

    snapshot = state.read_state(state_path)
    assert snapshot["fire_requested_at"] is not None
    assert snapshot["fire_request_reason"] == "owner-urgent-task"
    assert snapshot["current_jobs"] == []


def test_request_cas_loss_retries_under_single_decision_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disappeared request is re-decided without invoking a retired gate."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    state.request_fire("owner-urgent-task", path=state_path)
    last_fire_before = state.read_state(state_path)["last_fire_at"]
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    monkeypatch.setattr(
        scheduler.phase_z,
        "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": True,
            "reason": "ok",
            "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    reserve_calls = {"count": 0}

    def request_disappears_before_reservation(**_kwargs):
        reserve_calls["count"] += 1
        if reserve_calls["count"] == 1:
            assert state.consume_fire_request(state_path) == "owner-urgent-task"
        raise state.FireRequestChanged(None)

    monkeypatch.setattr(state, "reserve_fire", request_disappears_before_reservation)

    decision = asyncio.run(
        scheduler._tick_once(
            state_path=state_path,
            cron_expr="7 * * * *",
            prompt_path=prompt_path,
            log_path=tmp_path / "worker.log",
            dry_run=False,
            repo_root=tmp_path,
        )
    )

    assert decision == {
        "action": "skip",
        "reason": "fire_request_changed",
    }
    assert reserve_calls["count"] == 2
    snapshot = state.read_state(state_path)
    assert snapshot["current_jobs"] == []
    assert snapshot["last_fire_at"] == last_fire_before


def test_scheduler_scratch_failure_releases_reserved_slot(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    monkeypatch.setattr(
        scheduler,
        "_slot_workdir",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("scratch boom")),
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["reason"] == "scratch_workdir_error"
    assert state.read_state(state_path)["current_jobs"] == []


def test_scheduler_preassignment_timeout_releases_reserved_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-spawn admission timeout must not leave a pid-less active job."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{
            "id": "volpred-dispatch-supervisor",
            "max_slots": 2,
            "writer_isolation": {"mode": "enforce"},
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        scheduler,
        "_preassign_mutating_task",
        lambda **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("dispatch-preassign", 30)
        ),
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
        schedules_path=schedules,
    ))

    assert decision["action"] == "isolation_deferred"
    assert decision["reason"] == "mutating_preassignment_exception"
    snapshot = state.read_state(state_path)
    assert snapshot["current_jobs"] == []
    assert snapshot["fire_requested_at"] is not None
    assert snapshot["fire_request_reason"].startswith(
        "mutating_preassignment_exception:"
    )


# ── PHASE-Z safety net (Deliverable 7 cutover port of cron_hourly_dispatch.sh) ──


def _git_init_repo(root: Path) -> None:
    """Init a hermetic git repo in `root` with one committed file + a .gitignore
    that ignores the flat runtime-state paths PHASE-Z knows how to untrack."""
    def g(*args: str) -> None:
        cp = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=True,
        )
        return cp
    g("init", "-q", "-b", "main")
    g("config", "user.email", "test@volpred.local")
    g("config", "user.name", "phase-z-test")
    g("config", "commit.gpgsign", "false")
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    (root / ".gitignore").write_text(
        "storage/.release_settings.json\n"
        "storage/ops/dashboard_latest.json\n"
        "storage/ops/dispatch_state.json\n",
        encoding="utf-8",
    )
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "seed")


def _git_head_subject(root: Path) -> str:
    cp = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--pretty=%s"],
        capture_output=True, text=True, check=True,
    )
    return cp.stdout.strip()


def _git_head_count(root: Path) -> int:
    cp = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return int(cp.stdout.strip())


def test_phase_z_clean_tree_no_commit(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    before = _git_head_count(tmp_path)
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "clean"
    assert _git_head_count(tmp_path) == before  # no empty commit on clean tree


def test_phase_z_dirty_nonmachine_tree_is_left_for_finalizer(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    before = _git_head_count(tmp_path)
    # A canonical edit appearing during the fire is not proof of authorship.
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments" / "k9999.py").write_text("print('result')\n", encoding="utf-8")
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "nothing_owned"
    assert out["isolation_residue"] == ["experiments/k9999.py"]
    assert _git_head_count(tmp_path) == before
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "experiments/k9999.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == ""
    assert (tmp_path / "experiments" / "k9999.py").exists()


def test_phase_z_does_not_bind_claim_to_unrelated_machine_churn(
    tmp_path: Path, monkeypatch,
) -> None:
    _git_init_repo(tmp_path)
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments" / "repair.py").write_text("FIXED = True\n", encoding="utf-8")
    machine = tmp_path / "storage" / "ops" / "state.json"
    machine.parent.mkdir(parents=True)
    machine.write_text("{}\n", encoding="utf-8")
    calls: list[dict] = []
    issue_calls: list[dict] = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return ["ci-red-123"]

    def fake_issue_settlement(**kwargs):
        issue_calls.append(kwargs)
        return [{"task_id": "linked-ticket", "issue_ref": "#37"}]

    monkeypatch.setattr(phase_z, "backfill_ci_repair_commit", fake_backfill)
    monkeypatch.setattr(
        phase_z,
        "settle_completed_task_issues",
        fake_issue_settlement,
    )
    monkeypatch.setattr(
        phase_z,
        "pending_issue_task_ids_for_owners",
        lambda **_kwargs: {"linked-ticket"},
    )
    owner = "hourly-slot-1-job-ci"
    out = phase_z.run_phase_z(
        repo_root=tmp_path,
        now_hhmm="16:08",
        pre_fire_dirty=set(),
        claim_owners={owner},
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert out["owned"] == []
    assert out["churn"] == ["storage/ops/state.json"]
    assert out["ci_repair_tasks_backfilled"] == []
    assert out["issue_tasks_closed"] == []
    assert calls == []
    assert issue_calls == []
    assert (tmp_path / "experiments" / "repair.py").exists()


def test_phase_z_untracks_leaked_ignored_state_file(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    # A gitignored runtime-state file that has drifted back into tracking
    # (force-added once) — the 2026-07-01 cadence-revert incident scenario.
    (tmp_path / "storage").mkdir()
    leaked = tmp_path / "storage" / ".release_settings.json"
    leaked.write_text('{"interval_minutes": 60}\n', encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", "storage/.release_settings.json"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "force-tracked leaked state"],
        capture_output=True, text=True, check=True,
    )
    # Now the agent leaves BOTH a stale mutation to the leaked file AND real work.
    leaked.write_text('{"interval_minutes": 999}\n', encoding="utf-8")
    (tmp_path / "real_work.md").write_text("real\n", encoding="utf-8")
    machine = tmp_path / "storage" / "ops" / "state.json"
    machine.parent.mkdir(parents=True)
    machine.write_text("{}\n", encoding="utf-8")

    # baseline = clean tree at fire start → everything dirty now is this fire's.
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert "storage/.release_settings.json" in out["untracked"]
    # leaked state file is no longer tracked (its stale mutation cannot be
    # committed back over a canonical directive)
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "storage/.release_settings.json"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == ""
    # Explicit machine state landed, but unrelated real work stayed for its
    # declared workspace finalizer.
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "real_work.md"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == ""
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "storage/ops/state.json"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == "storage/ops/state.json"


def test_phase_z_untracks_leaked_supervisor_dispatch_state(tmp_path: Path) -> None:
    # Codex review #1: the supervisor's OWN runtime state file must be in the
    # untrack list — PHASE-Z runs right after the supervisor mutates it, so a
    # drift-into-tracking would commit heartbeat/last_fire_at every fire.
    _git_init_repo(tmp_path)
    (tmp_path / "storage" / "ops").mkdir(parents=True)
    leaked = tmp_path / "storage" / "ops" / "dispatch_state.json"
    leaked.write_text('{"last_fire_at": "old"}\n', encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", "storage/ops/dispatch_state.json"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "force-tracked dispatch_state"],
        capture_output=True, text=True, check=True,
    )
    leaked.write_text('{"last_fire_at": "new-heartbeat"}\n', encoding="utf-8")
    (tmp_path / "work.md").write_text("real\n", encoding="utf-8")

    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert "storage/ops/dispatch_state.json" in out["untracked"]
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "storage/ops/dispatch_state.json"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == ""


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_phase_z_add_failure_aborts_commit(tmp_path: Path) -> None:
    # Codex review #3: a failed `git add -A` leaves the index in an unknown
    # state — PHASE-Z must NOT proceed to commit a partial tree.
    _git_init_repo(tmp_path)
    machine = tmp_path / "storage" / "ops" / "dirty.txt"
    machine.parent.mkdir(parents=True)
    machine.write_text("state\n", encoding="utf-8")
    commits: list = []

    def fake_runner(argv, **kwargs):
        sub = argv[3]  # ["git", "-C", root, <subcommand>, ...]
        if sub == "add":
            return _FakeCompleted(1, stderr="fatal: index lock held")
        if sub == "commit":
            commits.append(argv)
        return subprocess.run(argv, **kwargs)

    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", runner=fake_runner,
        pre_fire_dirty=set(), alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "add_error"
    assert commits == []  # never reached commit


def test_phase_z_lsfiles_failure_discards_candidate(tmp_path: Path) -> None:
    # The alternate-index transaction is fail-closed: if it cannot inventory
    # leaked tracked state, it cannot prove the candidate tree is complete.
    calls: list[str] = []
    _git_init_repo(tmp_path)
    machine = tmp_path / "storage" / "ops" / "work.txt"
    machine.parent.mkdir(parents=True)
    machine.write_text("state\n", encoding="utf-8")

    def fake_runner(argv, **kwargs):
        sub = argv[3]
        calls.append(sub)
        if sub == "ls-files":
            return _FakeCompleted(128, stderr="fatal: bad revision")
        return subprocess.run(argv, **kwargs)

    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", runner=fake_runner,
        pre_fire_dirty=set(), alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "candidate_index_error"
    assert out["rolled_back"] is True
    assert "commit-tree" not in calls


def test_scheduler_phase_z_runs_even_if_worker_raises(tmp_path: Path, monkeypatch) -> None:
    # Codex review #2: PHASE-Z lives in `finally`, so a worker that RAISES still
    # gets the safety-net (and the exception propagates afterward).
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    ran = {"phase_z": 0}

    def boom(**kwargs):
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": True, "reason": "ok", "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    monkeypatch.setattr(scheduler.worker, "run_worker", boom)
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: ran.__setitem__("phase_z", ran["phase_z"] + 1) or {"committed": True},
    )

    with pytest.raises(RuntimeError, match="worker exploded"):
        asyncio.run(scheduler._tick_once(
            state_path=state_path,
            cron_expr="7 * * * *",
            prompt_path=prompt_path,
            log_path=tmp_path / "worker.log",
            dry_run=False,
            repo_root=tmp_path,
        ))

    assert ran["phase_z"] == 1  # safety-net ran despite the worker crash


def test_phase_z_non_git_dir_is_observable_noop(tmp_path: Path) -> None:
    # repo_root that is not a git repo → git status rc!=0 → must be reported as
    # status_error, NOT misreported as "clean" (which would silently skip a
    # real safety-net if the tree were actually dirty).
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "status_error"


def test_phase_z_git_timeout_does_not_raise(tmp_path: Path) -> None:
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=30)

    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", runner=boom,
        alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "status_error"


def test_scheduler_post_fire_hook_invokes_phase_z(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")

    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": True, "reason": "ok", "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **kwargs: worker.WorkerResult(
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            attempts=1, duration_s=1.0, log_tail="ok",
        ),
    )
    seen: list[Path] = []
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: seen.append(kwargs["repo_root"]) or {"committed": True, "reason": "committed"},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "fired"
    assert decision["phase_z"] == {"committed": True, "reason": "committed"}
    assert seen == [tmp_path]  # hook ran exactly once, against the given repo_root


def test_scheduler_dry_run_skips_phase_z(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    called = {"phase_z": 0}
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: called.__setitem__("phase_z", called["phase_z"] + 1) or {},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=True,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "dry_run_fire"
    assert called["phase_z"] == 0  # dry-run never spawns an agent → nothing to commit


# ── pre-fire git conflict guard ──────────────────────────────────────────────
# Regression suite for the 2026-07-10 rewire of scripts/git_conflict_guard.py,
# orphaned for 6 days by the 7/4 supervisor cutover (its only caller was the
# now-unloaded cron_hourly_dispatch.sh). The invariants below are exactly the
# ones whose absence made the orphaning invisible.


def _ok_worker(**_kwargs) -> worker.WorkerResult:
    return worker.WorkerResult(
        exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
        attempts=1, duration_s=1.0, log_tail="ok",
    )


def test_scheduler_pre_fire_guard_runs_once_before_worker(tmp_path: Path, monkeypatch) -> None:
    # The whole point of the guard: the tree must be clean BEFORE the agent
    # starts writing to it. Ordering, not just presence, is the invariant.
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    order: list[str] = []

    monkeypatch.setattr(
        scheduler.phase_z, "recover_failed_closeout",
        lambda **kwargs: order.append(f"recovery:{kwargs['repo_root']}")
        or {"committed": False, "reason": "no_failed_closeout"},
    )
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **kwargs: order.append(f"guard:{kwargs['repo_root']}") or {
            "ran": True, "reason": "ok", "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **kwargs: order.append("worker") or _ok_worker(),
    )
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: order.append("phase_z") or {"committed": False, "reason": "clean"},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "fired"
    # exactly once, strictly before the worker spawns, against the given repo_root
    assert order == [f"recovery:{tmp_path}", f"guard:{tmp_path}", "worker", "phase_z"]


def test_scheduler_closeout_recovery_crash_does_not_suppress_guard(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    called = {"guard": 0, "worker": 0}

    monkeypatch.setattr(
        scheduler.phase_z,
        "recover_failed_closeout",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("bad closeout receipt")),
    )
    monkeypatch.setattr(
        scheduler.phase_z,
        "run_pre_fire_guard",
        lambda **_kwargs: called.__setitem__("guard", called["guard"] + 1) or {
            "ran": True, "reason": "ok", "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    monkeypatch.setattr(
        scheduler.worker,
        "run_worker",
        lambda **_kwargs: called.__setitem__("worker", called["worker"] + 1) or _ok_worker(),
    )
    monkeypatch.setattr(
        scheduler.phase_z,
        "run_phase_z",
        lambda **_kwargs: {"committed": False, "reason": "clean"},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "fired"
    assert called == {"guard": 1, "worker": 1}


def test_scheduler_pre_fire_guard_crash_does_not_prevent_fire(tmp_path: Path, monkeypatch) -> None:
    # run_pre_fire_guard is no-raise by construction; this pins the scheduler's
    # belt-and-suspenders try/except. A guard must never veto the dispatch it
    # guards — a broken backstop degrades to "unprotected", never to "no fire".
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    ran = {"guard": 0, "worker": 0}

    def exploding_guard(**_kwargs):
        ran["guard"] += 1
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(scheduler.phase_z, "run_pre_fire_guard", exploding_guard)
    monkeypatch.setattr(
        scheduler.phase_z, "_default_internal_alert",
        lambda **_kwargs: {"sent": True},
    )
    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **kwargs: ran.__setitem__("worker", ran["worker"] + 1) or _ok_worker(),
    )
    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", lambda **kwargs: {"committed": False})

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "fired"
    # ran["guard"] pins that the crash path was actually exercised. Without it
    # this test passes vacuously the moment the guard call is orphaned again —
    # which is precisely the failure mode this suite exists to catch.
    assert ran["guard"] == 1
    assert ran["worker"] == 1


def test_scheduler_dry_run_skips_pre_fire_guard(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    called = {"guard": 0}
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **kwargs: called.__setitem__("guard", called["guard"] + 1) or {},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=True,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "dry_run_fire"
    assert called["guard"] == 0  # dry-run mutates no repo → nothing to guard


def test_scheduler_pre_fire_guard_not_run_on_undue_tick(tmp_path: Path, monkeypatch) -> None:
    # 59 of every 60 ticks are not_due. Guarding those would turn a once-hourly
    # git scan into a once-a-minute one.
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["last_fire_at"] = state._now()  # just fired → next slot is an hour away
    called = {"guard": 0}
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **kwargs: called.__setitem__("guard", called["guard"] + 1) or {},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md",
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "skip"
    assert decision["reason"] == "not_due"
    assert called["guard"] == 0


def test_retired_pregate_config_cannot_skip_scheduler_fire(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    called = {"guard": 0, "worker": 0}

    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **kwargs: called.__setitem__("guard", called["guard"] + 1) or {"ran": True, "reason": "ok"},
    )
    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **kwargs: called.__setitem__("worker", called["worker"] + 1) or _ok_worker(),
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path,
        cron_expr="7 * * * *",
        prompt_path=prompt_path,
        log_path=tmp_path / "worker.log",
        dry_run=False,
        repo_root=tmp_path,
    ))

    assert decision["action"] == "fired"
    assert called["guard"] == 1
    assert called["worker"] == 1


def test_pre_fire_guard_invokes_script_quietly_under_timeout(tmp_path: Path) -> None:
    guard = tmp_path / "scripts" / "git_conflict_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("", encoding="utf-8")
    seen: dict = {}

    def fake_runner(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _FakeCompleted(returncode=0)

    out = phase_z.run_pre_fire_guard(repo_root=tmp_path, runner=fake_runner)

    assert out == {"ran": True, "reason": "ok", "dirty_at_fire_start": -1}
    # subprocess (never import) so a guard crash cannot take down the daemon;
    # sys.executable (never `uv run`) so the pure-stdlib guard skips uv's
    # cwd-resolution hang (docs/error_log.md 2026-07-02).
    assert seen["cmd"] == [sys.executable, str(guard), "--quiet"]
    assert seen["kwargs"]["timeout"] == 30  # legacy GIT_CONFLICT_GUARD_TIMEOUT_SEC
    assert seen["kwargs"]["cwd"] == str(tmp_path)
    assert seen["kwargs"]["check"] is False


def test_pre_fire_guard_forwards_output_when_it_acted(tmp_path: Path) -> None:
    guard = tmp_path / "scripts" / "git_conflict_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("", encoding="utf-8")
    stdout = "[git-conflict-guard] restored canonical: storage/reports/feed.json"

    out = phase_z.run_pre_fire_guard(
        repo_root=tmp_path,
        runner=lambda *a, **k: _FakeCompleted(returncode=0, stdout=stdout),
    )

    assert out["ran"] is True
    assert out["reason"] == "ok"
    assert "feed.json" in out["guard_output"]  # which blobs it restored is the record


# dirty_at_fire_start == -1: repo_root is a non-git tmp dir, so the fire-start
# baseline probe cannot run. PHASE-Z then declines to commit rather than guess
# whose files it is looking at (docs/error_log.md 2026-07-10).
def test_pre_fire_guard_missing_script_is_fail_open(tmp_path: Path) -> None:
    # No scripts/ dir under repo_root → nothing spawned, observable no-op.
    out = phase_z.run_pre_fire_guard(repo_root=tmp_path)
    assert out == {"ran": False, "reason": "guard_missing", "dirty_at_fire_start": -1}


def test_pre_fire_guard_timeout_is_fail_open(tmp_path: Path) -> None:
    guard = tmp_path / "scripts" / "git_conflict_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="git_conflict_guard.py", timeout=30)

    out = phase_z.run_pre_fire_guard(repo_root=tmp_path, runner=boom)
    assert out == {"ran": False, "reason": "timeout", "dirty_at_fire_start": -1}  # no raise


def test_pre_fire_guard_spawn_error_is_fail_open(tmp_path: Path) -> None:
    guard = tmp_path / "scripts" / "git_conflict_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("", encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("no fork for you")

    out = phase_z.run_pre_fire_guard(repo_root=tmp_path, runner=boom)
    assert out == {"ran": False, "reason": "spawn_error", "dirty_at_fire_start": -1}


def test_pre_fire_guard_nonzero_exit_is_fail_open(tmp_path: Path) -> None:
    # The guard's main() returns 0 on every path, so a non-zero exit is a crash.
    # Report it (no silent fallback) but never veto the fire.
    guard = tmp_path / "scripts" / "git_conflict_guard.py"
    guard.parent.mkdir(parents=True)
    guard.write_text("", encoding="utf-8")

    out = phase_z.run_pre_fire_guard(
        repo_root=tmp_path,
        runner=lambda *a, **k: _FakeCompleted(returncode=2, stderr="Traceback ..."),
    )

    assert out["ran"] is True
    assert out["reason"] == "nonzero_exit"
    assert out["exit_code"] == 2


def test_pre_fire_guard_is_idempotent_on_a_clean_tree(tmp_path: Path) -> None:
    # End-to-end against the REAL guard script + a real (empty) git repo: it
    # must exit 0, print nothing under --quiet, and mutate nothing.
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    real_guard = Path(__file__).resolve().parents[1] / "scripts" / "git_conflict_guard.py"
    (repo / "scripts" / "git_conflict_guard.py").write_text(
        real_guard.read_text(encoding="utf-8"), encoding="utf-8"
    )
    owner = Path(__file__).resolve().parents[1] / "src/volpred/ops/git_writer_lock.py"
    copied_owner = repo / "src/volpred/ops/git_writer_lock.py"
    copied_owner.parent.mkdir(parents=True)
    copied_owner.write_text(owner.read_text(encoding="utf-8"), encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["add", "-A"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "seed"],
        check=True, capture_output=True,
    )

    first = phase_z.run_pre_fire_guard(repo_root=repo)
    second = phase_z.run_pre_fire_guard(repo_root=repo)

    expected = {"ran": True, "reason": "ok", "dirty_at_fire_start": 0}
    assert {key: first[key] for key in expected} == expected
    assert {key: second[key] for key in expected} == expected
    assert first["fire_lifecycle"]["pre_fire_dirty"] == []
    assert second["fire_lifecycle"]["pre_fire_dirty"] == []
    assert (
        second["fire_lifecycle"]["generation_id"]
        != first["fire_lifecycle"]["generation_id"]
    )
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True,
    )
    assert status.stdout.strip() == ""


def test_failed_new_baseline_capture_removes_previous_singleton(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    assert phase_z._write_pre_fire_snapshot(
        repo, {"previous-fire.txt"}, subprocess.run,
    )

    def fail_only_status(args, **kwargs):
        if "status" in args:
            return subprocess.CompletedProcess(args, 1, "", "probe failed")
        return subprocess.run(args, **kwargs)

    outcome = phase_z.run_pre_fire_guard(
        repo_root=repo, git_runner=fail_only_status,
    )

    assert outcome["dirty_at_fire_start"] == -1
    assert "fire_lifecycle" not in outcome
    snapshot = phase_z._snapshot_path(repo, subprocess.run)
    assert snapshot is not None
    assert not snapshot.exists()


def test_due_to_fire_warns_on_invalid_last_fire_at(capsys) -> None:
    # parse_iso_warn (via volpred.ops.diagnostics) writes structured WARN to
    # stderr, not the std logging module — so we read capsys.err here.
    due, _prev = scheduler._due_to_fire(
        cron_expr="7 * * * *",
        last_fire_at="not-a-date",
    )

    err = capsys.readouterr().err
    # 9c4f73e21: an unparseable last_fire_at is NOT due (it used to be treated as
    # "fire now" — the off-slot duplicate-fire bug). The WARN still fires; only the
    # due verdict flipped True→False.
    assert due is False
    assert "[supervisor] WARN last_fire_at parse failed" in err
    assert "raw=not-a-date" in err


def _begin_fire(
    path: Path, *, pid: int, pgid: int, schedule_id: str, attempt: int,
    model: str, log_path: str, started_wall: str | None = "Wed Jan  1 00:00:00 2026",
) -> None:
    """Mirrors worker.py's reserve_fire()+attach_process() pair — see the
    identical helper in scripts/tests/test_dispatch_state.py for why the old
    single-call `begin_fire` was replaced (§10 #5 atomic fire-claim fix)."""
    state.reserve_fire(schedule_id=schedule_id, attempt=attempt, model=model, log_path=log_path, path=path)
    state.attach_process(pid=pid, pgid=pgid, started_wall=started_wall, path=path)


def test_health_check_kills_overdue_job(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    kills: list[int] = []
    alerts_called: list[dict] = []

    # returns True = kill confirmed. The contract gained a bool on 2026-07-11 so
    # a REFUSED kill can no longer masquerade as a successful one; a mock that
    # returns None would now (correctly) be read as "the orphan survived".
    monkeypatch.setattr(
        health, "_force_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(
        state,
        "get_current_jobs",
        lambda path=state_path: [state.CurrentJob(
            pid=123,
            pgid=456,
            schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00",
            attempt=1,
            model="opus",
            log_path="/tmp/x.log",
            started_wall="Wed Jan  1 00:00:00 2026",
            age_seconds=4000,
        )],
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "killed"
    assert kills == [456]
    assert len(alerts_called) == 1
    assert state.read_state(state_path)["current_job"] is None


def _seed_claimed_task(
    tmp_path: Path, monkeypatch, *, task_id: str, owner: str
) -> Path:
    """Point the canonical claim CLI at a throwaway pool holding one live claim.

    The supervisor imports scripts/task_pool_claim.py by path and caches it in
    sys.modules, so patching that module's NEXT_TASKS is what redirects the
    production write path — no parallel fixture pool.
    """
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": task_id,
                    "status": "in_progress",
                    "claimed_by": owner,
                    "claimed_at": "2026-01-01T00:00:00+00:00",
                    "claim_session_id": "sess-1",
                },
                {"id": "untouched_other_task", "status": "pending"},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(health._task_pool_claim(), "NEXT_TASKS", next_tasks)
    return next_tasks


def _read_task(path: Path, task_id: str) -> dict:
    return next(t for t in json.loads(path.read_text(encoding="utf-8")) if t["id"] == task_id)


def test_health_kill_repends_the_claim_the_dead_fire_was_holding(
    tmp_path: Path, monkeypatch
) -> None:
    """WS-A2b: killing a worker used to free only the dispatch_state slot, so the
    task it had claimed stayed in_progress until the stale sweep hours later."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    job_id = str(state.read_state(state_path)["current_jobs"][0]["job_id"])
    owner = health.identity.task_claim_owner(
        role="hourly", slot_id="slot-1", job_id=job_id,
    )
    next_tasks = _seed_claimed_task(
        tmp_path, monkeypatch, task_id="assign_zombie", owner=owner,
    )

    alerts_called: list[dict] = []
    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid, **_kw: True)
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(
        health.alerts, "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(
        health.procutil, "check_identity",
        lambda pid, started_wall: procutil.IDENTITY_MATCH,
    )
    monkeypatch.setattr(
        state, "get_current_jobs",
        lambda path=state_path: [state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", job_id=job_id, slot_id=1,
            started_wall="Wed Jan  1 00:00:00 2026", age_seconds=4000,
        )],
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "killed"
    task = _read_task(next_tasks, "assign_zombie")
    assert task["status"] == "pending"
    assert "claimed_by" not in task
    assert "claimed_at" not in task
    assert task["last_release_reason"] == f"supervisor_kill_{job_id[:8]}"
    assert task["status_history"][-1]["by"] == owner
    # Untouched sibling proves the release is owner-scoped, not a pool reset.
    assert _read_task(next_tasks, "untouched_other_task")["status"] == "pending"
    # The re-pend is on the receipt, so the hang mail says what was requeued.
    assert alerts_called[0]["job"]["repended_tasks"] == ["assign_zombie"]


def test_health_kill_repends_codex_failover_claim_for_the_same_slot(
    tmp_path: Path, monkeypatch
) -> None:
    """A fire can hand the SAME slot/job to Codex mid-flight; health.py never
    sees which executor claimed, so both role tokens must be released."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    job_id = str(state.read_state(state_path)["current_jobs"][0]["job_id"])
    owner = health.identity.task_claim_owner(
        role="codex-failover", slot_id="slot-1", job_id=job_id,
    )
    next_tasks = _seed_claimed_task(
        tmp_path, monkeypatch, task_id="assign_codex_zombie", owner=owner,
    )

    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid, **_kw: True)
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(health.alerts, "send_hang_alert", lambda **kwargs: True)
    monkeypatch.setattr(
        health.procutil, "check_identity",
        lambda pid, started_wall: procutil.IDENTITY_MATCH,
    )
    monkeypatch.setattr(
        state, "get_current_jobs",
        lambda path=state_path: [state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", job_id=job_id, slot_id=1,
            started_wall="Wed Jan  1 00:00:00 2026", age_seconds=4000,
        )],
    )

    assert health.check_once(state_path=state_path, max_age_s=3000) == "killed"
    assert _read_task(next_tasks, "assign_codex_zombie")["status"] == "pending"


def test_health_kill_completes_even_when_the_task_pool_is_unreadable(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """The kill is the safety-critical act. A broken task pool must degrade to a
    WARNING (stale sweep is the backstop), never abort the kill/close path."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    job_id = str(state.read_state(state_path)["current_jobs"][0]["job_id"])

    kills: list[int] = []
    monkeypatch.setattr(
        health, "_force_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(health.alerts, "send_hang_alert", lambda **kwargs: True)
    monkeypatch.setattr(
        health.procutil, "check_identity",
        lambda pid, started_wall: procutil.IDENTITY_MATCH,
    )

    def _boom(*_args, **_kwargs):
        raise OSError("next_tasks.json is locked")

    monkeypatch.setattr(health._task_pool_claim(), "release_owner_claims", _boom)
    monkeypatch.setattr(
        state, "get_current_jobs",
        lambda path=state_path: [state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", job_id=job_id, slot_id=1,
            started_wall="Wed Jan  1 00:00:00 2026", age_seconds=4000,
        )],
    )

    with caplog.at_level(logging.WARNING):
        action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "killed"
    assert kills == [456]
    assert state.read_state(state_path)["current_job"] is None
    assert "re-pend of task claims" in caplog.text


# --- WS-A2c: worker.py's OWN timeout must re-pend too -----------------------
#
# health.py is the belt-and-suspenders layer (~1s behind); the path that
# actually wins the CAS in production is `worker._run_one_attempt`'s
# `Popen.wait(timeout=)` firing → category "hang" → killed_timeout. WS-A2b only
# closed the health half, so a real hang still stranded its claim.


def _seed_worker_hang(
    tmp_path: Path,
    monkeypatch,
    *,
    task_id: str,
    role: str = "hourly",
    close_first: bool = False,
) -> tuple[Path, Path, list[dict], dict]:
    """Drive run_worker down the hang path with one live claim in the pool.

    The claim owner embeds the job_id, which run_worker mints internally, so the
    pool can only be seeded from inside the fake attempt.
    """
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    hang_alerts: list[dict] = []
    seen: dict = {}

    def fake_run_one_attempt(**kwargs):
        _reserve_like_production(kwargs)
        seen["job_id"] = kwargs["job_id"]
        seen["slot_id"] = kwargs["slot_id"]
        owner = claim_release.identity.task_claim_owner(
            role=role, slot_id=kwargs["slot_id"], job_id=kwargs["job_id"],
        )
        seen["owner"] = owner
        seen["next_tasks"] = _seed_claimed_task(
            tmp_path, monkeypatch, task_id=task_id, owner=owner,
        )
        if close_first:
            # Simulate health.py's watchdog winning the atomic close ~1s ahead
            # of us, so our own record_completion returns None below.
            seen["health_closed"] = state.record_completion(
                job_id=kwargs["job_id"], expected_attempt=kwargs["attempt"],
                expected_phase="classifying", exit_code=-1,
                outcome="silent_death", final_model="opus", path=state_path,
            ) is not None
        return worker.TIMEOUT_KILLED_SENTINEL, 12.0, "timed out — SIGKILL'd by watchdog"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts, "send_hang_alert",
        lambda **kwargs: hang_alerts.append(kwargs) or True,
    )
    return state_path, log_path, hang_alerts, seen


def test_worker_own_timeout_repends_the_claim_the_dead_fire_was_holding(
    tmp_path: Path, monkeypatch
) -> None:
    """WS-A2c (a): the worker's own watchdog kill must hand the claim back."""
    state_path, log_path, hang_alerts, seen = _seed_worker_hang(
        tmp_path, monkeypatch, task_id="assign_worker_zombie",
    )

    result = worker.run_worker(
        prompt_text="prompt", log_path=log_path, state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    assert result.outcome == "killed_timeout"
    assert result.attempts == 1, "hang must NOT trigger retry"
    task = _read_task(seen["next_tasks"], "assign_worker_zombie")
    assert task["status"] == "pending"
    assert "claimed_by" not in task
    assert task["last_release_reason"] == f"supervisor_kill_{seen['job_id'][:8]}"
    assert task["status_history"][-1]["by"] == seen["owner"]
    # Owner-scoped, not a pool reset.
    assert _read_task(seen["next_tasks"], "untouched_other_task")["status"] == "pending"
    # Receipt rides along on the hang mail, same as the health path.
    assert hang_alerts[0]["job"]["repended_tasks"] == ["assign_worker_zombie"]


def test_worker_own_timeout_repends_codex_failover_claim_for_the_same_slot(
    tmp_path: Path, monkeypatch
) -> None:
    """Both role tokens: the fire may have handed the slot to Codex mid-flight."""
    state_path, log_path, _alerts, seen = _seed_worker_hang(
        tmp_path, monkeypatch, task_id="assign_worker_codex_zombie",
        role="codex-failover",
    )

    result = worker.run_worker(
        prompt_text="prompt", log_path=log_path, state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    assert result.outcome == "killed_timeout"
    assert _read_task(seen["next_tasks"], "assign_worker_codex_zombie")["status"] == "pending"


def test_worker_hang_result_and_alert_survive_a_broken_task_pool(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    """WS-A2c (b): re-pend is best-effort. A locked/corrupt pool degrades to a
    WARNING and must never block killed_timeout landing or the hang alert."""
    state_path, log_path, hang_alerts, seen = _seed_worker_hang(
        tmp_path, monkeypatch, task_id="assign_worker_stuck",
    )

    def _boom(*_args, **_kwargs):
        raise OSError("next_tasks.json is locked")

    monkeypatch.setattr(claim_release._task_pool_claim(), "release_owner_claims", _boom)

    with caplog.at_level(logging.WARNING):
        result = worker.run_worker(
            prompt_text="prompt", log_path=log_path, state_path=state_path,
            sleep_fn=lambda sec: None,
        )

    assert result.outcome == "killed_timeout"
    assert result.exit_code == 137
    assert len(hang_alerts) == 1, "a broken pool must not swallow the hang alert"
    assert hang_alerts[0]["job"]["repended_tasks"] == []
    assert "re-pend of task claims" in caplog.text
    # Untouched: the stale-claim sweep remains the backstop for this row.
    assert _read_task(seen["next_tasks"], "assign_worker_stuck")["status"] == "in_progress"


def test_worker_repends_even_when_health_won_the_close(
    tmp_path: Path, monkeypatch
) -> None:
    """WS-A2c (c): losing the CAS (`entry is None`) must NOT skip the re-pend.

    health.py closes some aged-out jobs as silent_death / timeout_unverified
    WITHOUT releasing anything, so a win-only re-pend would leave the claim
    stranded exactly when nobody else is going to hand it back. Releasing
    unconditionally is safe because release_owner_claims is idempotent.
    """
    state_path, log_path, hang_alerts, seen = _seed_worker_hang(
        tmp_path, monkeypatch, task_id="assign_worker_lost_race", close_first=True,
    )

    result = worker.run_worker(
        prompt_text="prompt", log_path=log_path, state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    assert seen["health_closed"] is True
    assert result.outcome == "killed_timeout"
    # Loser of the CAS stays silent on mail (2026-07-12 contract) but still
    # requeues the work.
    assert hang_alerts == []
    assert _read_task(seen["next_tasks"], "assign_worker_lost_race")["status"] == "pending"


def test_release_owner_claims_is_idempotent_for_an_already_pending_task(
    tmp_path: Path, monkeypatch
) -> None:
    """The safety argument for calling the helper from both worker and health:
    a second release matches nothing rather than double-reporting or resetting
    a row a successor fire may already have claimed."""
    owner = claim_release.identity.task_claim_owner(
        role="hourly", slot_id="slot-1", job_id="deadbeefcafe",
    )
    next_tasks = _seed_claimed_task(
        tmp_path, monkeypatch, task_id="assign_twice", owner=owner,
    )

    first = claim_release.repend_killed_job_claims(
        job_id="deadbeefcafe", slot_id="slot-1", source="worker",
    )
    second = claim_release.repend_killed_job_claims(
        job_id="deadbeefcafe", slot_id=1, source="health",
    )

    assert first == ["assign_twice"]
    assert second == [], "a second release must be a no-op, not a re-report"
    assert _read_task(next_tasks, "assign_twice")["status"] == "pending"


def test_health_check_kills_overdue_job_skips_kill_on_identity_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    """§10 #2 regression: an aged-out job whose pid/pgid fingerprint no longer
    matches (already gone, or the OS recycled the pid to an unrelated
    process) must NOT be signalled — recorded as silent_death instead."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    kills: list[int] = []
    alerts_called: list[dict] = []

    # returns True = kill confirmed. The contract gained a bool on 2026-07-11 so
    # a REFUSED kill can no longer masquerade as a successful one; a mock that
    # returns None would now (correctly) be read as "the orphan survived".
    monkeypatch.setattr(
        health, "_force_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_MISMATCH)
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(
        state,
        "get_current_jobs",
        lambda path=state_path: [state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", started_wall="Wed Jan  1 00:00:00 2026",
            age_seconds=4000,
        )],
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "silent_death"
    assert kills == [], "must not signal a pid whose identity no longer matches"
    assert state.read_state(state_path)["completions"][-1]["outcome"] == "silent_death"


def test_health_check_kills_overdue_job_skips_kill_when_unverified(
    tmp_path: Path, monkeypatch
) -> None:
    """2026-07-04 gate-blocking fix #4: a missing fingerprint (attach raced
    ahead of a slow/failed `ps` call) must NOT be treated as "assume it's the
    same process and kill" — that was the exact backwards behavior Codex
    flagged. It must record a distinct `timeout_unverified` outcome and skip
    the kill, same spirit as a confirmed mismatch but distinguishably logged."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log", started_wall=None,
    )
    kills: list[int] = []
    alerts_called: list[dict] = []

    # returns True = kill confirmed. The contract gained a bool on 2026-07-11 so
    # a REFUSED kill can no longer masquerade as a successful one; a mock that
    # returns None would now (correctly) be read as "the orphan survived".
    monkeypatch.setattr(
        health, "_force_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_UNVERIFIED)
    monkeypatch.setattr(
        state,
        "get_current_jobs",
        lambda path=state_path: [state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", started_wall=None, age_seconds=4000,
        )],
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "timeout_unverified"
    assert kills == [], "must not signal a pid with no recorded fingerprint to verify against"
    snap = state.read_state(state_path)
    assert snap["completions"] == []
    assert snap["current_job"]["phase"] == "timeout_unverified"


def test_health_check_marks_silent_death(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log",
    )
    alerts_called: list[dict] = []

    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_MISMATCH)
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(
        health.alerts,
        "send_silent_death_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "silent_death"
    assert len(alerts_called) == 1
    completions = state.read_state(state_path)["completions"]
    assert completions[-1]["outcome"] == "failure"


def test_health_check_leaves_unverified_job_alone_when_not_overdue(
    tmp_path: Path, monkeypatch
) -> None:
    """Within budget + unverified fingerprint must NOT be misdiagnosed as
    silent_death — the job may well be running fine; we just haven't (yet)
    recorded a fingerprint for it."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=123, pgid=456, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/x.log", started_wall=None,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_UNVERIFIED)

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action is None
    assert state.read_state(state_path)["current_job"] is not None


def test_force_kill_pgid_tolerates_process_lookup_races(monkeypatch, tmp_path) -> None:
    calls: list[int] = []

    def missing_pgid(pgid: int, sig: int) -> None:
        calls.append(sig)
        raise ProcessLookupError

    monkeypatch.setattr(procutil.os, "killpg", missing_pgid)
    # The liveness probe must be pinned to the same fiction as killpg: a group
    # that raises ProcessLookupError is gone, so `ps -g` finds nothing. Without
    # this the probe queries the REAL pgid 456 — empty on a dev mac, a live
    # process group on a CI runner, where the kill then escalated to SIGKILL and
    # failed the assert below (run 29372109046).
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [])
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    health._force_kill_pgid(456, state_path=tmp_path / "dispatch_state.json")

    assert calls == [signal.SIGTERM]


def test_force_kill_pgid_tolerates_exit_after_term(monkeypatch, tmp_path) -> None:
    """health._force_kill_pgid delegates to procutil.kill_pgid, which must now
    RETURN whether the group is confirmed gone (2026-07-11) — a refused kill
    used to be indistinguishable from a successful one."""
    sigs: list[int] = []
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: sigs.append(sig))
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [])
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    assert health._force_kill_pgid(
        456, state_path=tmp_path / "dispatch_state.json",
    ) is True
    assert sigs == [signal.SIGTERM]


def test_force_kill_pgid_reports_false_when_orphan_survives(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [456])  # never dies
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    assert health._force_kill_pgid(
        456, state_path=tmp_path / "dispatch_state.json",
    ) is False


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="macOS kernel coalition custody probe",
)
def test_producer_cohort_probe_tracks_detached_process() -> None:
    """A setsid descendant remains attributable after leaving its old PGID."""
    custody = procutil.capture_producer_custody()
    if custody is None:
        pytest.skip("test runner shares a non-quiescent launchd coalition")
    job_id = f"cohort-{os.getpid()}-{time.time_ns()}"
    child = subprocess.Popen(
        ["/bin/sleep", "10"],
        start_new_session=True,
    )
    try:
        members = procutil.producer_cohort_members_checked(
            0,
            job_id=job_id,
            custody=custody,
        )
        assert members is not None
        assert child.pid in members
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_termination_wrappers_use_tree_when_leader_identity_is_known(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Detached descendants are part of the producer cohort, not free agents."""
    tree_calls: list[int] = []
    monkeypatch.setattr(
        procutil,
        "kill_tree",
        lambda pid, **_kwargs: bool(tree_calls.append(pid) or True),
    )
    monkeypatch.setattr(
        procutil,
        "kill_pgid",
        lambda *_args, **_kwargs: pytest.fail("PGID-only fallback used"),
    )
    monkeypatch.setattr(
        procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )

    assert worker._kill_pgid(
        456,
        leader_pid=123,
        state_path=tmp_path / "worker-state.json",
    ) is True
    assert health._force_kill_pgid(
        654,
        leader_pid=321,
        state_path=tmp_path / "health-state.json",
    ) is True
    assert tree_calls == [123, 321]


def test_health_never_closes_dead_leader_with_live_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health cannot win the leader-exit race and bypass workspace quarantine."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path,
        pid=123,
        pgid=456,
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/worker.log",
        started_wall="leader-start",
    )
    job_id = str(
        state.read_state(state_path)["current_jobs"][0]["job_id"]
    )
    monkeypatch.setattr(
        health.procutil,
        "check_identity",
        lambda _pid, _started: procutil.IDENTITY_DEAD,
    )
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [789],
    )
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **_kwargs: None,
    )

    action = health.check_once(
        state_path=state_path,
        max_age_s=99999,
    )

    assert action == "kill_failed_orphan"
    snap = state.read_state(state_path)
    current = next(
        job
        for job in snap["current_jobs"]
        if job["job_id"] == job_id
    )
    assert current["phase"] == "kill_failed_orphan"
    assert not [
        entry
        for entry in snap["completions"]
        if entry.get("job_id") == job_id
    ]


def test_supervisor_set_runtime_env_raises_soft_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []

    monkeypatch.setenv("VOLPRED_HOME_DIR", str(tmp_path / "volpred-home"))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(resource, "getrlimit", lambda which: (256, 65536))
    monkeypatch.setattr(resource, "setrlimit", lambda which, value: calls.append((which, value)))

    supervisor._set_runtime_env()

    assert calls == [(resource.RLIMIT_NOFILE, (65536, 65536))]


def test_supervisor_loads_secure_model_token_for_isolated_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    home = tmp_path / "volpred-home"
    token_path = home / "secrets" / "claude_oauth_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("model-token\n", encoding="utf-8")
    token_path.chmod(0o600)
    monkeypatch.setenv("VOLPRED_HOME_DIR", str(home))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(resource, "getrlimit", lambda which: (65536, 65536))

    supervisor._set_runtime_env()

    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "model-token"


def test_supervisor_rejects_insecure_model_token_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    home = tmp_path / "volpred-home"
    token_path = home / "secrets" / "claude_oauth_token"
    token_path.parent.mkdir(parents=True)
    token_path.write_text("must-not-load\n", encoding="utf-8")
    token_path.chmod(0o644)
    monkeypatch.setenv("VOLPRED_HOME_DIR", str(home))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(resource, "getrlimit", lambda which: (65536, 65536))

    supervisor._set_runtime_env()

    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ


def test_classify_normalizes_negative_signal_codes() -> None:
    # Codex-review §10 #1: signal-killed children return negative codes from
    # subprocess.Popen.wait(); pre-fix `_classify` only checked positive codes
    # so -15 (SIGTERM) was misclassified as hard_failure → unwanted retry.
    # After the fix `_normalize_signal_exit` maps -N → 128+N before classify.
    assert worker._normalize_signal_exit(-15) == 143
    assert worker._normalize_signal_exit(-9) == 137
    assert worker._normalize_signal_exit(-14) == 142
    assert worker._normalize_signal_exit(0) == 0
    assert worker._normalize_signal_exit(1) == 1
    assert worker._normalize_signal_exit(None) == 1
    # 2026-07-21: raw signal exits are by construction OUTSIDE kills (our own
    # kills return sentinels), so they classify as external_signal, not hang.
    assert worker._classify(worker._normalize_signal_exit(-15), "") == "external_signal"
    assert worker._classify(worker._normalize_signal_exit(-9), "") == "external_signal"
    assert worker._classify(worker._normalize_signal_exit(-14), "") == "external_signal"


def test_classify_timeout_sentinel_is_hang() -> None:
    # Belt-and-suspenders: even if our normalisation path was bypassed, the
    # explicit sentinel `_run_one_attempt` returns on TimeoutExpired must
    # classify as hang so the no-retry-on-hang contract holds.
    assert worker._classify(worker.TIMEOUT_KILLED_SENTINEL, "") == "hang"
    # Must NOT be misread as success despite being negative (sentinel uses
    # -1000, far outside any real POSIX status range).
    assert worker.TIMEOUT_KILLED_SENTINEL != 0


def test_run_one_attempt_warns_when_child_survives_sigkill_grace(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    _stub_worker_custody(monkeypatch)

    class StuckProc:
        pid = 123

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

    kills: list[int] = []
    reserve_calls: list[dict] = []
    attach_calls: list[dict] = []
    fingerprint_calls: list[dict] = []

    monkeypatch.setattr(worker, "_spawn", lambda **kwargs: StuckProc())
    monkeypatch.setattr(
        worker, "_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(worker.procutil, "get_process_start_wall", lambda pid: "Wed Jan  1 00:00:00 2026")
    monkeypatch.setattr(
        worker.state, "reserve_fire", lambda **kwargs: reserve_calls.append(kwargs),
    )
    monkeypatch.setattr(
        worker.state, "attach_process", lambda **kwargs: attach_calls.append(kwargs),
    )
    monkeypatch.setattr(
        worker.state, "update_started_wall", lambda **kwargs: fingerprint_calls.append(kwargs),
    )

    with caplog.at_level(logging.WARNING, logger=worker.__name__):
        exit_code, duration, _attempt_output = worker._run_one_attempt(
            prompt_text="prompt",
            model=worker.OPUS_MODEL,
            timeout_s=1,
            log_path=tmp_path / "worker.log",
            attempt=1,
            schedule_id="hourly_dispatch",
            state_path=tmp_path / "dispatch_state.json",
            claude_bin="/tmp/claude",
        )

    assert exit_code == worker.TIMEOUT_KILLED_SENTINEL
    assert duration >= 0
    assert kills == [123]
    assert reserve_calls, "reserve_fire must be called before spawn (§10 #5)"
    # 2026-07-04 gate-blocking fix #2: attach_process() is called IMMEDIATELY
    # after Popen with started_wall=None (fast — no `ps` subprocess call yet)
    # to narrow the pid=None crash-recovery window; the fingerprint is filled
    # in afterwards via a separate update_started_wall() call.
    assert attach_calls and attach_calls[0]["pid"] == 123
    assert attach_calls[0]["started_wall"] is None
    assert fingerprint_calls and fingerprint_calls[0]["pid"] == 123
    assert fingerprint_calls[0]["started_wall"] == "Wed Jan  1 00:00:00 2026"
    assert "still alive after SIGKILL grace" in caplog.text


def test_run_one_attempt_requires_empty_process_group_after_leader_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A returned provider leader is not proof its producer cohort drained."""
    _stub_worker_custody(monkeypatch)

    class ExitedProc:
        pid = 123

    monkeypatch.setattr(
        worker,
        "authorize_provider_spawn",
        lambda **kwargs: SimpleNamespace(
            resolved_executable=kwargs["executable_path"],
            settings_path="/tmp/pinned-settings.json",
            environment=lambda: {},
        ),
    )
    monkeypatch.setattr(worker, "verify_spawn_receipt", lambda _receipt: None)
    monkeypatch.setattr(worker, "_spawn", lambda **_kwargs: ExitedProc())
    monkeypatch.setattr(
        worker,
        "_wait_with_fatal_probe",
        lambda *_args, **_kwargs: ("exited", 0),
    )
    monkeypatch.setattr(worker.state, "begin_attempt", lambda **_kwargs: object())
    monkeypatch.setattr(worker.state, "attach_process", lambda **_kwargs: None)
    monkeypatch.setattr(
        worker.state,
        "update_started_wall",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        worker.procutil,
        "get_process_start_wall",
        lambda _pid: "start-id",
    )
    monkeypatch.setattr(
        worker.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [789],
    )
    monkeypatch.setattr(
        worker.fire_manifest,
        "open_manifest",
        lambda *_args, **_kwargs: None,
    )

    exit_code, _duration, _output = worker._run_one_attempt(
        prompt_text="prompt",
        model=worker.OPUS_MODEL,
        timeout_s=10,
        log_path=tmp_path / "worker.log",
        attempt=1,
        schedule_id="hourly_dispatch",
        state_path=tmp_path / "state.json",
        job_id="job-live-descendant",
        slot_id="slot-1",
    )

    assert exit_code == worker.TIMEOUT_SURVIVED_SENTINEL


def test_run_one_attempt_globally_binds_before_spawn_and_releases_after_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_bind = worker.custody_receipt.bind_producer_custody
    real_release = worker.custody_receipt.release_producer_custody
    _stub_worker_custody(monkeypatch)
    monkeypatch.setattr(worker.custody_receipt, "bind_producer_custody", real_bind)
    monkeypatch.setattr(
        worker.custody_receipt,
        "release_producer_custody",
        real_release,
    )
    monkeypatch.setattr(worker, "PROJECT_ROOT", tmp_path)
    worker.custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    observed_pending_at_spawn: list[int] = []
    spawned_env: dict[str, str] = {}

    class ExitedProc:
        pid = 123

    def fake_spawn(**kwargs):
        spawned_env.update(kwargs["env"])
        observed_pending_at_spawn.append(
            len(
                worker.custody_receipt.read_pending_producer_custodies(
                    tmp_path
                )
            )
        )
        return ExitedProc()

    monkeypatch.setattr(worker, "_spawn", fake_spawn)
    monkeypatch.setattr(
        worker,
        "_wait_with_fatal_probe",
        lambda *_args, **_kwargs: ("exited", 0),
    )
    monkeypatch.setattr(
        worker.procutil,
        "get_process_start_wall",
        lambda _pid: "start-id",
    )

    exit_code, _duration, _output = worker._run_one_attempt(
        prompt_text="prompt",
        model=worker.OPUS_MODEL,
        timeout_s=10,
        log_path=tmp_path / "worker.log",
        attempt=1,
        schedule_id="hourly_dispatch",
        state_path=tmp_path / "state.json",
        preselected_task_id="article-starved",
    )

    assert exit_code == 0
    assert observed_pending_at_spawn == [1]
    assert spawned_env["VOLPRED_PRESELECTED_TASK_ID"] == "article-starved"
    assert (
        worker.custody_receipt.read_pending_producer_custodies(tmp_path)
        == []
    )


def test_worker_timeout_path_short_circuits_retry(tmp_path: Path, monkeypatch) -> None:
    """Real timeout path regression: signal-killed child must abort retry.

    Pre-fix, after `_kill_pgid` the child's negative exit code (-15 / -9) was
    classified as `hard_failure` → retry loop ran (worker.py:251-260 pre-fix).
    Post-fix, `_run_one_attempt` returns TIMEOUT_KILLED_SENTINEL on
    TimeoutExpired, which `_classify` maps to "hang" → record_completion
    outcome=killed_timeout, alert sent, NO retry.
    """
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    attempts: list[int] = []
    hang_alerts: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        _reserve_like_production(kwargs)
        log_path.write_text("timed out — SIGKILL'd by watchdog", encoding="utf-8")
        # Simulate what real `_run_one_attempt` returns when our timeout fires
        return worker.TIMEOUT_KILLED_SENTINEL, 12.0, "timed out — SIGKILL'd by watchdog"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts,
        "send_hang_alert",
        lambda **kwargs: hang_alerts.append(kwargs) or True,
    )

    result = worker.run_worker(
        prompt_text="prompt",
        log_path=log_path,
        state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    assert result.outcome == "killed_timeout"
    assert result.attempts == 1, "hang must NOT trigger retry"
    assert attempts == [1]
    assert len(hang_alerts) == 1
    # Persisted exit code must be canonical SIGKILL hang code (137), not the
    # internal sentinel — external observers/state readers see a real POSIX code.
    assert result.exit_code == 137
    # Note: record_completion no-ops if `current_job` is absent (the mocked
    # `_run_one_attempt` skips `state.reserve_fire`/`attach_process`);
    # WorkerResult.exit_code is the authoritative check for sentinel→137
    # sanitisation.


def test_worker_killed_by_external_signal_is_not_reported_as_a_hang(
    tmp_path: Path, monkeypatch
) -> None:
    """External SIGTERM ≠ hang (2026-07-21 redesign, email-12150).

    Every kill the supervisor initiates returns through a sentinel, so a raw
    143 can ONLY be an outside kill. The old contract classified it "hang" and
    mailed a「卡住 N 分鐘」CRITICAL about a fire that was working to its last
    second — three times in one day. New contract: outcome=unknown_external,
    claims handed back, one WARN via the dedicated alert, NO hang alert, no
    in-fire retry.
    """
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    attempts: list[int] = []
    external_alerts: list[dict] = []
    released: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        _reserve_like_production(kwargs)
        log_path.write_text("Execution error", encoding="utf-8")
        # Externally signal-killed → negative is normalized at the boundary
        return worker._normalize_signal_exit(-15), 7.0, "Execution error"  # → 143

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts, "send_hang_alert",
        lambda **kwargs: pytest.fail(
            "hang alert sent for an external signal — the false CRITICAL is back"
        ),
    )
    monkeypatch.setattr(
        worker.alerts, "send_external_signal_alert",
        lambda **kwargs: external_alerts.append(kwargs) or True,
    )
    monkeypatch.setattr(
        worker.claim_release, "repend_killed_job_claims",
        lambda **kw: released.append(kw) or ["task-under-test"],
    )
    monkeypatch.setattr(
        worker.termination, "wait_for_sent_signal", lambda **_kw: None,
    )

    result = worker.run_worker(
        prompt_text="prompt",
        log_path=log_path,
        state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    assert result.outcome == "unknown_external"
    assert result.attempts == 1, "no in-fire retry — the killer is still out there"
    assert attempts == [1]
    assert result.exit_code == 143
    assert len(external_alerts) == 1
    assert external_alerts[0]["signum"] == 15
    assert released and released[0]["source"] == "worker-unknown-external-signal"


def test_supervisor_initiated_kill_is_still_a_hang() -> None:
    """The sentinel path keeps its no-retry hang contract — only RAW signal
    exits reclassify. If this goes red the redesign leaked onto real hangs."""
    assert worker._classify(worker.TIMEOUT_KILLED_SENTINEL, "") == "hang"
    assert worker._classify(143, "") == "external_signal"
    assert worker._classify(137, "") == "external_signal"
    assert worker._classify(worker._normalize_signal_exit(-14), "") == "external_signal"


def test_raw_signal_with_exact_sent_intent_is_system_terminated(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    released: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        _reserve_like_production(kwargs)
        kwargs["process_identity_sink"](456)
        log_path.write_text("working until signal", encoding="utf-8")
        return worker._normalize_signal_exit(-15), 7.0, "working until signal"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.termination, "wait_for_sent_signal",
        lambda **_kw: {
            "intent_id": "intent-1",
            "reason": "health_max_age_watchdog",
            "status": "sent",
        },
    )
    monkeypatch.setattr(
        worker.alerts, "send_external_signal_alert",
        lambda **_kw: pytest.fail("matched system signal must not send external alert"),
    )
    monkeypatch.setattr(
        worker.claim_release, "repend_killed_job_claims",
        lambda **kw: released.append(kw) or ["task-under-test"],
    )

    result = worker.run_worker(
        prompt_text="prompt", log_path=log_path, state_path=state_path,
        sleep_fn=lambda _sec: None,
    )

    assert result.outcome == "system_terminated"
    assert released[0]["source"] == "worker-system-termination"


def test_health_cas_loss_preserves_raw_signal_for_intent_classification(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_worker_custody(monkeypatch)

    class ExitedProc:
        pid = 123

    seen_pgid: list[int] = []
    monkeypatch.setattr(worker, "_spawn", lambda **_kw: ExitedProc())
    monkeypatch.setattr(
        worker, "_wait_with_fatal_probe", lambda *_a, **_kw: ("exited", -15),
    )
    monkeypatch.setattr(worker.state, "begin_attempt", lambda **_kw: object())
    monkeypatch.setattr(worker.state, "attach_process", lambda **_kw: None)
    monkeypatch.setattr(worker.state, "update_started_wall", lambda **_kw: None)
    monkeypatch.setattr(
        worker.procutil, "get_process_start_wall", lambda _pid: "start-id",
    )
    monkeypatch.setattr(worker.state, "mark_job_phase", lambda **_kw: False)
    monkeypatch.setattr(worker.fire_manifest, "open_manifest", lambda *_a, **_kw: None)

    exit_code, _duration, _output = worker._run_one_attempt(
        prompt_text="prompt", model=worker.OPUS_MODEL, timeout_s=10,
        log_path=tmp_path / "worker.log", attempt=1,
        schedule_id="hourly_dispatch", state_path=tmp_path / "state.json",
        job_id="job-health-race", slot_id="slot-1",
        process_identity_sink=seen_pgid.append,
    )

    assert exit_code == 143
    assert seen_pgid == [123]


def test_worker_registry_denial_happens_before_popen(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(worker.state, "begin_attempt", lambda **_kw: object())
    monkeypatch.setattr(worker.fire_manifest, "open_manifest", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        worker,
        "authorize_provider_spawn",
        lambda **_kw: (_ for _ in ()).throw(
            worker.ProviderRegistryError("metered billing")
        ),
    )
    monkeypatch.setattr(
        worker,
        "_spawn",
        lambda **_kw: pytest.fail("policy denial must precede Popen"),
    )

    with pytest.raises(worker.ProviderRegistryError, match="metered billing"):
        worker._run_one_attempt(
            prompt_text="prompt",
            model=worker.OPUS_MODEL,
            timeout_s=10,
            log_path=tmp_path / "worker.log",
            attempt=1,
            schedule_id="hourly_dispatch",
            state_path=tmp_path / "state.json",
            job_id="job-policy-denial",
            slot_id="slot-1",
        )


def test_worker_api_key_environment_halts_before_popen(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "metered-secret")
    monkeypatch.setattr(worker.state, "begin_attempt", lambda **_kw: object())
    monkeypatch.setattr(worker.fire_manifest, "open_manifest", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        worker,
        "_spawn",
        lambda **_kw: pytest.fail("API key denial must precede Popen"),
    )

    with pytest.raises(worker.ProviderRegistryError, match="API-key"):
        worker._run_one_attempt(
            prompt_text="prompt",
            model=worker.OPUS_MODEL,
            timeout_s=10,
            log_path=tmp_path / "worker.log",
            attempt=1,
            schedule_id="hourly_dispatch",
            state_path=tmp_path / "state.json",
            job_id="job-api-key-denial",
            slot_id="slot-1",
        )


def test_unresolved_system_attempt_is_not_mislabeled_unknown_external(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"

    def fake_run_one_attempt(**kwargs):
        _reserve_like_production(kwargs)
        kwargs["process_identity_sink"](456)
        return 143, 3.0, "working until signal"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.termination, "wait_for_sent_signal", lambda **_kw: None,
    )
    monkeypatch.setattr(
        worker.termination, "match_unresolved_signal_attempt",
        lambda **_kw: {"intent_id": "attempt-only"},
    )
    monkeypatch.setattr(
        worker.alerts, "send_external_signal_alert",
        lambda **_kw: pytest.fail("unresolved system attempt is not external"),
    )
    monkeypatch.setattr(
        worker.claim_release, "repend_killed_job_claims",
        lambda **_kw: ["task-under-test"],
    )

    result = worker.run_worker(
        prompt_text="prompt", log_path=log_path, state_path=state_path,
        sleep_fn=lambda _seconds: None,
    )
    assert result.outcome == "system_termination_unconfirmed"


def test_load_cron_expr_reads_schedule_field_first(tmp_path: Path) -> None:
    """Codex-review §10 #6 fix: canonical field is `schedule`, not `cron`.

    Pre-fix `load_cron_expr` only read `cron`; `volpred-hourly-dispatch` has
    `"cron": null, "schedule": "7 * * * *"` so the supervisor silently fell
    back to its hardcoded default — source drift latent.
    """
    sched_path = tmp_path / "runtime_schedules.json"
    sched_path.write_text(
        json.dumps(
            {
                "cron_jobs": [
                    {
                        "id": "volpred-hourly-dispatch",
                        "cron": None,
                        "schedule": "*/15 * * * *",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert scheduler.load_cron_expr(schedules_path=sched_path) == "*/15 * * * *"


def test_load_cron_expr_falls_back_to_legacy_cron_field(tmp_path: Path) -> None:
    """Legacy schedules with only `cron` populated still work."""
    sched_path = tmp_path / "runtime_schedules.json"
    sched_path.write_text(
        json.dumps(
            {
                "cron_jobs": [
                    {"id": "volpred-hourly-dispatch", "cron": "5 * * * *"}
                ]
            }
        ),
        encoding="utf-8",
    )
    assert scheduler.load_cron_expr(schedules_path=sched_path) == "5 * * * *"


def test_load_cron_expr_returns_fallback_when_both_fields_empty(tmp_path: Path) -> None:
    sched_path = tmp_path / "runtime_schedules.json"
    sched_path.write_text(
        json.dumps(
            {
                "cron_jobs": [
                    {"id": "volpred-hourly-dispatch", "cron": None, "schedule": None}
                ]
            }
        ),
        encoding="utf-8",
    )
    assert scheduler.load_cron_expr(schedules_path=sched_path) == scheduler.FALLBACK_CRON


def test_cli_unblock_auth_and_status(tmp_path: Path, capsys) -> None:
    state_path = _tmp_state(tmp_path)
    state.set_auth_blocked(True, path=state_path)

    from scripts.dispatch_supervisor import cli

    rc = cli.main(["--state-path", str(state_path), "unblock-auth"])
    assert rc == 0
    assert state.read_state(state_path)["auth_blocked"] is False
    capsys.readouterr()

    rc = cli.main(["--state-path", str(state_path), "status"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["auth_blocked"] is False


# ---------------------------------------------------------------------------
# Codex review §10 #3 — restart orphan cleanup (supervisor._handle_restart_orphan)
# ---------------------------------------------------------------------------


def test_handle_restart_orphan_kills_live_identity_matched_job(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall="Wed Jan  1 00:00:00 2026",
    )
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    kills: list[int] = []
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.worker, "_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()

    assert kills == [888]
    assert len(alerts_called) == 1
    assert alerts_called[0]["killed"] is True
    snap = state.read_state(state_path)
    assert snap["current_job"] is None
    assert snap["completions"][-1]["outcome"] == "killed_supervisor_restart"


def test_handle_restart_orphan_skips_kill_on_identity_mismatch(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall="Wed Jan  1 00:00:00 2026",
    )
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    kills: list[int] = []
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.worker, "_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_MISMATCH)
    monkeypatch.setattr(
        supervisor.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()

    assert kills == [], "must not signal a pid whose identity no longer matches"
    assert len(alerts_called) == 1
    assert alerts_called[0]["killed"] is False
    snap = state.read_state(state_path)
    assert snap["completions"][-1]["outcome"] == "orphan_gone_or_reused"


def test_restart_verified_dead_workspace_is_adjudicated_before_state_release(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo, job_id="7" * 32)
    assert ws is not None
    ws["declared_output_paths"] = ["orphan.txt"]
    wt = Path(ws["path"])
    (wt / "orphan.txt").write_text("unique orphan bytes\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "orphan.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "orphan output"],
        check=True,
    )
    unique_sha = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    state_path = _tmp_state(tmp_path)
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/orphan.log",
        path=state_path,
    )
    state.attach_workspace(job_id=lease.job_id, workspace=ws, path=state_path)
    state.attach_process(
        job_id=lease.job_id,
        expected_attempt=1,
        pid=999,
        pgid=888,
        started_wall="Wed Jan  1 00:00:00 2026",
        path=state_path,
    )
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    monkeypatch.setattr(supervisor, "ROOT", repo)
    monkeypatch.setattr(
        supervisor.procutil, "check_identity",
        lambda _pid, _wall: procutil.IDENTITY_MISMATCH,
    )
    monkeypatch.setattr(
        supervisor.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert", lambda **_kwargs: True,
    )
    settlements: list[dict] = []
    monkeypatch.setattr(
        scheduler,
        "_settle_mutating_task",
        lambda **kwargs: settlements.append(kwargs)
        or {"ok": True, "status": "blocked"},
    )

    supervisor._handle_restart_orphan()

    snapshot = state.read_state(state_path)
    assert snapshot["current_jobs"] == []
    assert settlements[0]["workspace"]["task_id"] == ws["task_id"]
    assert settlements[0]["disposition"] == "remediation"
    assert not wt.exists()
    checkpoint = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{unique_sha}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    assert checkpoint.returncode == 0
    released = [
        event for event in _ws_receipt_events(repo)
        if event.get("event") == "released"
    ]
    assert released[-1]["disposition"] == "remediation_opened"


def test_restart_keeps_slot_when_leader_dead_but_pgid_descendant_survives(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
    )
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    monkeypatch.setattr(
        supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_DEAD,
    )
    monkeypatch.setattr(
        supervisor.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [1001],
    )
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert", lambda **kwargs: True,
    )

    supervisor._handle_restart_orphan()

    snap = state.read_state(state_path)
    assert snap["current_job"]["phase"] == "kill_failed_orphan"
    assert snap["current_job"]["pgid"] == 888
    assert snap["completions"] == []


def test_handle_restart_orphan_skips_kill_when_unverified(tmp_path: Path, monkeypatch) -> None:
    """2026-07-04 gate-blocking fix #4: no fingerprint recorded must NOT
    degrade to "assume same process, kill it" — that reopens the exact
    PID-reuse risk the fingerprint mechanism exists to close."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall=None,
    )
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    kills: list[int] = []
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.worker, "_kill_pgid", lambda pgid, **_kw: kills.append(pgid),
    )
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_UNVERIFIED)
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()

    assert kills == [], "must not signal a pid with no recorded fingerprint to verify against"
    assert len(alerts_called) == 1
    assert alerts_called[0]["killed"] is False
    snap = state.read_state(state_path)
    assert snap["current_job"] is not None
    assert snap["current_job"]["phase"] == "orphan_unverified_not_killed"
    assert snap["completions"] == []


def test_handle_restart_orphan_noop_when_no_stale_job(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()

    assert alerts_called == []


def test_handle_restart_orphan_clears_abandoned_pid_none_reservation(
    tmp_path: Path, monkeypatch
) -> None:
    """2026-07-04 gate-blocking fix #2: supervisor crashed between
    reserve_fire() and attach_process() — current_job has pid=None forever
    under the old code. Restart must clear this stuck slot (so the scheduler
    isn't wedged) and record + alert distinctly rather than silently return."""
    state_path = _tmp_state(tmp_path)
    state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/x.log", path=state_path,
    )
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    kills: list[int] = []
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.worker, "_kill_pgid", lambda pgid, **_kw: kills.append(pgid),
    )
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()

    assert kills == [], "no pid was ever recorded — nothing to identity-check or kill"
    assert len(alerts_called) == 1
    assert alerts_called[0]["killed"] is False
    snap = state.read_state(state_path)
    assert snap["current_job"] is None, "slot must not stay wedged forever"
    assert snap["completions"][-1]["outcome"] == "spawn_not_started"
    # PHASE-Z drain is persistent across restart; scheduler clears it before
    # admitting the next fire.
    state.finish_phase_z(
        cohort_id=snap["phase_z_pending"][0]["cohort_id"], path=state_path,
    )
    state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/next.log", path=state_path,
    )


def test_handle_restart_orphan_skips_duplicate_entry_when_cleanup_already_recorded(
    tmp_path: Path, monkeypatch
) -> None:
    """Codex round-2 low finding (2026-07-04): crash AFTER append_completion_entry
    but BEFORE finalize used to duplicate the completion entry on the next
    restart. Now the append atomically sets `cleanup_recorded` on current_job,
    and a retry sees the flag → finalizes without re-appending or re-killing."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall="Wed Jan  1 00:00:00 2026",
    )
    # Simulate attempt #1 that appended + flagged, then crashed pre-finalize.
    orphan = state.mark_restart_orphan_pending(state_path)
    state.append_completion_entry(
        orphan, exit_code=-9, outcome="killed_supervisor_restart",
        final_model="opus", path=state_path, mark_cleanup_recorded=True,
    )
    assert len(state.read_state(state_path)["completions"]) == 1

    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    kills: list[int] = []
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.worker, "_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()  # attempt #2 (the retry)

    snap = state.read_state(state_path)
    assert len(snap["completions"]) == 1, "retry must NOT append a duplicate completion entry"
    assert snap["current_job"] is None, "retry must still complete the deferred finalize"
    assert kills == [], "retry must not re-kill an already-handled orphan"
    assert alerts_called == [], "killed orphan is resolved — retry must not re-alert"


def test_handle_restart_orphan_re_alerts_unverified_on_cleanup_recorded_retry(
    tmp_path: Path, monkeypatch
) -> None:
    """Codex round-3 medium #1 (2026-07-04): if the crash-before-finalize gap
    happens for a NOT-killed unverified orphan (process may still be alive),
    the retry must RE-EMIT the runbook alert — not silently finalize and drop
    the only prompt. (Killed orphans are resolved and must NOT re-alert — see
    the sibling test above.)"""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall=None,
    )
    orphan = state.mark_restart_orphan_pending(state_path)
    state.append_completion_entry(
        orphan, exit_code=-1, outcome="orphan_unverified_not_killed",
        final_model="opus", path=state_path, mark_cleanup_recorded=True,
    )

    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()  # retry

    snap = state.read_state(state_path)
    assert snap["current_job"] is None
    assert len(alerts_called) == 1, "unverified not-killed orphan must re-alert on retry"
    assert alerts_called[0]["outcome"] == "orphan_unverified_not_killed"


def test_completion_entry_persists_pid_pgid_for_orphan_outcomes(tmp_path: Path) -> None:
    """Codex round-3 medium #2 (2026-07-04): the unverified-orphan runbook tells
    the operator to read pid/pgid from completions — so orphan/unverified
    entries must persist them (current_job is cleared right after)."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=4321, pgid=4321, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall="Wed Jan  1 00:00:00 2026",
    )
    orphan = state.mark_restart_orphan_pending(state_path)
    state.append_completion_entry(
        orphan, exit_code=-1, outcome="orphan_unverified_not_killed",
        final_model="opus", path=state_path, mark_cleanup_recorded=True,
    )
    entry = state.read_state(state_path)["completions"][-1]
    assert entry["pid"] == 4321
    assert entry["pgid"] == 4321
    assert entry["started_wall"] == "Wed Jan  1 00:00:00 2026"


def test_handle_restart_orphan_retries_after_partial_crash_mid_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    """2026-07-04 gate-blocking fix #3: the OLD claim_and_clear_current_job()
    cleared current_job to None in the SAME step as returning it — a second
    crash between that clear and kill/record finishing lost the orphan
    entirely. The new mark_restart_orphan_pending() does NOT clear until
    finalize_restart_orphan_cleanup() runs, so simulating "restart happened
    mid-cleanup" (call mark_restart_orphan_pending() directly, as if a first
    _handle_restart_orphan() call crashed right after) must still let a
    SECOND _handle_restart_orphan() call find and process the same orphan."""
    state_path = _tmp_state(tmp_path)
    _begin_fire(
        state_path, pid=999, pgid=888, schedule_id="hourly_dispatch",
        attempt=1, model="opus", log_path="/tmp/orphan.log",
        started_wall="Wed Jan  1 00:00:00 2026",
    )
    # Simulate a first restart attempt that flagged cleanup-pending and then
    # crashed before it could kill/record/finalize.
    state.mark_restart_orphan_pending(state_path)
    assert state.read_state(state_path)["current_job"] is not None

    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    kills: list[int] = []
    alerts_called: list[dict] = []
    monkeypatch.setattr(
        supervisor.worker, "_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(
        supervisor.alerts, "send_orphan_restart_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )

    supervisor._handle_restart_orphan()

    assert kills == [888], "second restart must still find and kill the same orphan"
    assert len(alerts_called) == 1
    snap = state.read_state(state_path)
    assert snap["current_job"] is None
    assert snap["completions"][-1]["outcome"] == "killed_supervisor_restart"


# ---------------------------------------------------------------------------
# Codex review §10 #7 — broad-except loops must escalate, not just log
# ---------------------------------------------------------------------------


def test_scheduler_loop_crash_sends_escalation_alert(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    crash_calls: list[tuple[str, str]] = []
    tick_calls: list[int] = []

    async def fake_sleep(_secs):
        return None

    async def fake_tick_once(**kwargs):
        tick_calls.append(1)
        if len(tick_calls) == 1:
            raise ValueError("boom")
        raise asyncio.CancelledError()

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "_tick_once", fake_tick_once)
    monkeypatch.setattr(scheduler, "load_cron_expr", lambda **kwargs: "7 * * * *")
    monkeypatch.setattr(
        scheduler.alerts, "send_loop_crash",
        lambda component, tb, **kwargs: crash_calls.append((component, tb)) or True,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler.scheduler_loop(state_path=state_path))

    assert tick_calls == [1, 1]
    assert len(crash_calls) == 1
    assert crash_calls[0][0] == "scheduler_loop"
    assert "boom" in crash_calls[0][1]


def test_health_loop_heartbeats_before_each_check(tmp_path: Path, monkeypatch) -> None:
    """Regression (2026-07-10): liveness used to be stamped only by
    `scheduler._tick_once()`, which awaits `worker.run_worker()` to completion —
    so `last_heartbeat_at` froze for the whole dispatch (up to 3x50min with the
    retry ladder) and `dispatch_state.json` reported a busy daemon as a dead one.
    `health_loop` never blocks on a worker, so it owns the beat, and it stamps
    BEFORE `check_once()` so a crashing health pass still leaves proof of life.
    """
    state_path = _tmp_state(tmp_path)
    state.mark_supervisor_started(state_path)
    with state._locked_state(state_path) as (_fh, data):
        data["last_heartbeat_at"] = "2000-01-01T00:00:00+00:00"
        data["supervisor_pid"] = 999_999

    beats: list[dict] = []
    recoveries: list[bool] = []

    async def fake_sleep(_secs):
        return None

    def fake_check_once(**kwargs):
        beats.append(state.read_state(state_path))
        if len(beats) >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(health.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(health, "check_once", fake_check_once)
    monkeypatch.setattr(
        health,
        "_renew_live_dispatch_claims",
        lambda **_kwargs: {"ok": True, "renewed": [], "count": 0},
    )
    monkeypatch.setattr(
        health.isolation,
        "recover_provider_auth_reapers",
        lambda: (
            recoveries.append(True)
            or {"recovered": 0, "active": 0, "invalid": 0}
        ),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(health.health_loop(state_path=state_path))

    assert len(beats) == 2
    assert recoveries == [True]
    assert all(b["last_heartbeat_at"] > "2001" for b in beats), "no beat before check_once"
    assert beats[1]["last_heartbeat_at"] > beats[0]["last_heartbeat_at"], "beat did not advance"
    assert beats[0]["supervisor_pid"] == os.getpid(), "stale pid not re-stamped"


def test_health_loop_defers_child_spawning_maintenance_during_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shared coalition is exclusive before custody capture, not only after."""
    state_path = _tmp_state(tmp_path)
    state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/reserved.log",
        path=state_path,
    )
    checks: list[int] = []
    maintenance: list[str] = []

    async def fake_sleep(_seconds):
        return None

    def fake_check_once(**_kwargs):
        checks.append(1)
        if len(checks) == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(health.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(health, "check_once", fake_check_once)
    monkeypatch.setattr(
        health,
        "_renew_live_dispatch_claims",
        lambda **_kwargs: {"ok": True, "renewed": [], "count": 0},
    )
    monkeypatch.setattr(
        health.isolation,
        "reap_quarantined_provider_auth_leases",
        lambda: maintenance.append("quarantine") or {"cleaned": 0},
    )
    monkeypatch.setattr(
        health.isolation,
        "recover_provider_auth_reapers",
        lambda: maintenance.append("recovery")
        or {"recovered": 0, "active": 0, "invalid": 0},
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(health.health_loop(state_path=state_path))

    assert checks == [1, 1]
    assert maintenance == []


def test_scheduler_tick_defers_all_helpers_during_precapture_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/reserved.log",
        path=state_path,
    )
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "sweep_orphan_workspaces",
        lambda **_kwargs: pytest.fail(
            "scheduler must not spawn/reconcile inside custody capture window"
        ),
    )

    decision = asyncio.run(
        scheduler._tick_once(
            state_path=state_path,
            cron_expr="7 * * * *",
            prompt_path=tmp_path / "prompt.md",
            log_path=tmp_path / "worker.log",
            dry_run=True,
            repo_root=tmp_path,
        )
    )

    assert decision == {
        "action": "skip",
        "reason": "producer_slot_in_flight",
        "active_jobs": 1,
    }


def test_health_renews_only_identity_verified_dispatch_jobs(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["current_jobs"] = [
            {
                "job_id": "verified-job",
                "cohort_id": "verified-job",
                "slot_id": 1,
                "phase": "running",
                "pid": 111,
                "pgid": 111,
                "schedule_id": "test",
                "started_at": "2026-07-27T04:00:00+00:00",
                "attempt_started_at": "2026-07-27T04:00:00+00:00",
                "attempt": 1,
                "model": "test",
                "log_path": "/tmp/test.log",
                "started_wall": "verified-start",
            },
            {
                "job_id": "stale-job",
                "cohort_id": "stale-job",
                "slot_id": 2,
                "phase": "running",
                "pid": 222,
                "pgid": 222,
                "schedule_id": "test",
                "started_at": "2026-07-27T04:00:00+00:00",
                "attempt_started_at": "2026-07-27T04:00:00+00:00",
                "attempt": 1,
                "model": "test",
                "log_path": "/tmp/test.log",
                "started_wall": "stale-start",
            },
        ]
    captured: list[list[str]] = []

    class FakeTaskPool:
        @staticmethod
        def renew_verified_dispatch_claims(job_ids):
            captured.append(list(job_ids))
            return {"ok": True, "renewed": [], "count": 0}

    monkeypatch.setattr(
        health.procutil,
        "check_identity",
        lambda pid, _wall: (
            health.procutil.IDENTITY_MATCH
            if pid == 111
            else health.procutil.IDENTITY_MISMATCH
        ),
    )
    monkeypatch.setattr(health, "_task_pool_claim", lambda: FakeTaskPool)

    result = health._renew_live_dispatch_claims(state_path=state_path)

    assert result["ok"] is True
    assert captured == [["verified-job"]]


def test_heartbeat_advances_while_worker_in_flight(tmp_path: Path, monkeypatch) -> None:
    """Integration regression (2026-07-10): both REAL loops, no mocked internals.

    `_tick_once()` awaits the worker to completion, so when it owned the only
    heartbeat, `last_heartbeat_at` froze for the whole dispatch — observed live
    as a 798s freeze during a healthy 12:07 fire. With `health_loop` owning the
    beat, the timestamp must keep advancing WHILE `current_job` is non-null.
    """
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    observed: dict = {}

    def fake_run_worker(**kwargs):
        # Claim the slot exactly like the real worker does, then block this
        # thread (the scheduler tick is awaiting us) and watch for a beat.
        state.reserve_fire(schedule_id="test", attempt=1, model="opus",
                           log_path=str(tmp_path / "w.log"), path=state_path)
        state.attach_process(pid=os.getpid(), pgid=os.getpgid(0), started_wall=None, path=state_path)
        beat_at_fire = state.read_state(state_path)["last_heartbeat_at"]

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.02)
            snap = state.read_state(state_path)
            if snap["last_heartbeat_at"] > beat_at_fire:
                observed["beat_during_worker"] = snap["last_heartbeat_at"]
                observed["job_was_in_flight"] = snap["current_job"] is not None
                break

        observed["beat_at_fire"] = beat_at_fire
        state.record_completion(exit_code=0, outcome="success", final_model="opus", path=state_path)
        return worker.WorkerResult(
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            attempts=1, duration_s=1.0, log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)
    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", lambda **kwargs: {"committed": False})

    async def drive():
        beat = asyncio.create_task(
            health.health_loop(state_path=state_path, check_interval_s=0.05)
        )
        try:
            return await scheduler._tick_once(
                state_path=state_path, cron_expr="7 * * * *",
                prompt_path=prompt_path, log_path=tmp_path / "worker.log",
                dry_run=False, repo_root=tmp_path,
            )
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    decision = asyncio.run(drive())

    assert decision["action"] == "fired"
    assert "beat_during_worker" in observed, (
        "last_heartbeat_at never advanced while the worker ran — the tick is the "
        "only heartbeat owner again, so a busy daemon looks dead"
    )
    assert observed["job_was_in_flight"], "beat did not land during the in-flight window"
    assert observed["beat_during_worker"] > observed["beat_at_fire"]


def test_health_loop_crash_sends_escalation_alert(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    crash_calls: list[tuple[str, str]] = []
    check_calls: list[int] = []

    async def fake_sleep(_secs):
        return None

    def fake_check_once(**kwargs):
        check_calls.append(1)
        if len(check_calls) == 1:
            raise ValueError("health boom")
        raise asyncio.CancelledError()

    monkeypatch.setattr(health.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(health, "check_once", fake_check_once)
    monkeypatch.setattr(
        health.alerts, "send_loop_crash",
        lambda component, tb, **kwargs: crash_calls.append((component, tb)) or True,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(health.health_loop(state_path=state_path))

    assert check_calls == [1, 1]
    assert len(crash_calls) == 1
    assert crash_calls[0][0] == "health_loop"
    assert "health boom" in crash_calls[0][1]


def test_supervisor_main_top_level_crash_sends_alert_and_reraises(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    crash_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(supervisor, "_set_runtime_env", lambda: None)
    monkeypatch.setattr(supervisor, "_setup_logging", lambda level: None)
    monkeypatch.setattr(supervisor, "_handle_restart_orphan", lambda: None)
    monkeypatch.setattr(supervisor.alerts, "send_supervisor_restart", lambda **kwargs: True)

    def boom_asyncio_run(coro):
        coro.close()  # avoid "coroutine was never awaited" warning
        raise RuntimeError("gather exploded")

    monkeypatch.setattr(supervisor.asyncio, "run", boom_asyncio_run)
    monkeypatch.setattr(
        supervisor.alerts, "send_loop_crash",
        lambda component, tb, **kwargs: crash_calls.append((component, tb)) or True,
    )

    with pytest.raises(RuntimeError, match="gather exploded"):
        supervisor.main([])

    assert len(crash_calls) == 1
    assert crash_calls[0][0] == "supervisor_main"
    assert "gather exploded" in crash_calls[0][1]
    # `main()` must honour the monkeypatched STATE_PATH — see below.
    assert state.read_state(state_path)["supervisor_pid"] == os.getpid()


def test_supervisor_startup_registry_denial_precedes_state_and_provider_io(
    monkeypatch,
) -> None:
    monkeypatch.setattr(supervisor, "_setup_logging", lambda _level: None)
    monkeypatch.setattr(supervisor, "_set_runtime_env", lambda: None)
    monkeypatch.setattr(
        supervisor,
        "load_provider_registry",
        lambda: (_ for _ in ()).throw(
            worker.ProviderRegistryError("credits are forbidden")
        ),
    )
    monkeypatch.setattr(
        supervisor.state,
        "read_state",
        lambda *_a, **_k: pytest.fail(
            "startup policy denial must precede state mutation"
        ),
    )

    with pytest.raises(worker.ProviderRegistryError, match="credits"):
        supervisor.main([])


def test_supervisor_startup_invalid_auth_recovery_runs_after_orphan_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    order: list[str] = []
    monkeypatch.setattr(supervisor, "_setup_logging", lambda _level: None)
    monkeypatch.setattr(supervisor, "_set_runtime_env", lambda: None)
    monkeypatch.setattr(supervisor, "load_provider_registry", lambda: None)
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    monkeypatch.setattr(
        supervisor,
        "_handle_restart_orphan",
        lambda: order.append("orphan_reconciled"),
    )
    monkeypatch.setattr(
        supervisor.isolation,
        "recover_provider_auth_reapers",
        lambda: order.append("auth_recovery")
        or {"recovered": 0, "active": 0, "invalid": 1},
    )
    monkeypatch.setattr(
        supervisor.alerts,
        "send_loop_crash",
        lambda component, _tb, **_kwargs: order.append(f"alert:{component}")
        or True,
    )

    with pytest.raises(
        isolation.IsolationUnavailable,
        match="startup recovery failed closed",
    ):
        supervisor.main([])
    assert order == [
        "orphan_reconciled",
        "auth_recovery",
        "alert:supervisor_startup",
    ]
    assert state_path.exists()


def test_supervisor_startup_custody_failure_alerts_before_reraising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    alerts_seen: list[tuple[str, str]] = []
    monkeypatch.setattr(supervisor, "_setup_logging", lambda _level: None)
    monkeypatch.setattr(supervisor, "_set_runtime_env", lambda: None)
    monkeypatch.setattr(supervisor, "load_provider_registry", lambda: None)
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    monkeypatch.setattr(
        supervisor.custody_receipt,
        "reconcile_pending_producer_custodies",
        lambda _root: (_ for _ in ()).throw(
            supervisor.custody_receipt.CustodyLedgerUnavailable(
                "ledger missing"
            )
        ),
    )
    monkeypatch.setattr(
        supervisor.alerts,
        "send_loop_crash",
        lambda component, tb, **_kwargs: alerts_seen.append((component, tb))
        or True,
    )

    with pytest.raises(
        supervisor.custody_receipt.CustodyLedgerUnavailable,
        match="ledger missing",
    ):
        supervisor.main([])

    assert len(alerts_seen) == 1
    assert alerts_seen[0][0] == "supervisor_startup"
    assert "ledger missing" in alerts_seen[0][1]


def test_supervisor_startup_defers_auth_reaper_while_orphan_is_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/orphan.log",
        path=state_path,
    )
    monkeypatch.setattr(supervisor, "_setup_logging", lambda _level: None)
    monkeypatch.setattr(supervisor, "_set_runtime_env", lambda: None)
    monkeypatch.setattr(supervisor, "load_provider_registry", lambda: None)
    monkeypatch.setattr(supervisor.state, "STATE_PATH", state_path)
    monkeypatch.setattr(supervisor, "_handle_restart_orphan", lambda: None)
    monkeypatch.setattr(
        supervisor.isolation,
        "recover_provider_auth_reapers",
        lambda: pytest.fail("auth reaper must wait for retained orphan drain"),
    )
    monkeypatch.setattr(
        supervisor.alerts,
        "send_supervisor_restart",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        supervisor.state,
        "consume_planned_restart_marker",
        lambda: None,
    )
    monkeypatch.setattr(
        supervisor.asyncio,
        "run",
        lambda coroutine: coroutine.close() or 0,
    )

    assert supervisor.main([]) == 0


def test_supervisor_main_writes_only_to_patched_state_path(tmp_path: Path, monkeypatch) -> None:
    """Regression (2026-07-10): `main()` called `state.read_state()` /
    `state.mark_supervisor_started()` with no argument, so their `path=STATE_PATH`
    default — bound at function-DEFINITION time — ignored a monkeypatched
    `state.STATE_PATH`. Every run of the crash test above therefore stamped a
    dead pytest pid and a fake heartbeat into the LIVE dispatch_state.json,
    masking a genuinely dead daemon. `main()` must resolve STATE_PATH at call
    time and pass it down.
    """
    patched_path = tmp_path / "test_state.json"
    default_path = state.STATE_PATH  # the real production path — must stay untouched
    real_read_state = state.read_state
    real_mark_started = state.mark_supervisor_started
    observed_paths: list[Path] = []

    def guarded_read(path=default_path):
        resolved = Path(path)
        assert resolved == patched_path, f"main read production state: {resolved}"
        observed_paths.append(resolved)
        return real_read_state(resolved)

    def guarded_mark(path=default_path):
        resolved = Path(path)
        assert resolved == patched_path, f"main wrote production state: {resolved}"
        observed_paths.append(resolved)
        return real_mark_started(resolved)

    monkeypatch.setattr(supervisor.state, "STATE_PATH", patched_path)
    monkeypatch.setattr(supervisor.state, "read_state", guarded_read)
    monkeypatch.setattr(supervisor.state, "mark_supervisor_started", guarded_mark)
    monkeypatch.setattr(supervisor.state, "consume_planned_restart_marker", lambda: None)
    monkeypatch.setattr(supervisor, "_set_runtime_env", lambda: None)
    monkeypatch.setattr(supervisor, "_setup_logging", lambda level: None)
    monkeypatch.setattr(supervisor, "_handle_restart_orphan", lambda: None)
    monkeypatch.setattr(supervisor.alerts, "send_supervisor_restart", lambda **kwargs: True)
    monkeypatch.setattr(supervisor.asyncio, "run", lambda coro: coro.close() or 0)

    supervisor.main([])

    # Under the old definition-time default this file was never created, because
    # main() wrote to `default_path` instead.
    assert patched_path.exists(), "main() ignored the patched STATE_PATH"
    assert real_read_state(patched_path)["supervisor_pid"] == os.getpid()
    assert observed_paths == [patched_path, patched_path, patched_path]


# ---------------------------------------------------------------------------
# worker._kill_pgid — liveness-probe PermissionError (found via a REAL smoke
# test spawning a genuine `sleep 30` process under this sandboxed environment;
# not one of the Codex review's 4 numbered items, but a real crash: the
# liveness-probe poll loop only caught ProcessLookupError, so a sandboxed
# `os.killpg(pgid, 0)` raising PermissionError propagated all the way out of
# `_kill_pgid()` — which `supervisor._handle_restart_orphan()` calls directly
# with no caller-side try/except, so this crashed orphan cleanup on boot.
# ---------------------------------------------------------------------------


def test_worker_kill_pgid_falls_back_to_per_pid_when_killpg_denied(
    monkeypatch, tmp_path,
) -> None:
    """worker._kill_pgid delegates to procutil.kill_pgid, so the 2026-07-11
    EPERM fix must hold through this entry point too: a refused `killpg` falls
    back to per-pid signalling instead of leaving the hung worker alive."""
    per_pid: list[tuple[int, int]] = []
    alive = {999}

    def denied_killpg(pgid, sig):
        raise PermissionError("Operation not permitted")

    def kill_one(pid, sig):
        per_pid.append((pid, sig))
        if sig == signal.SIGKILL:
            alive.discard(pid)

    monkeypatch.setattr(worker.os, "killpg", denied_killpg)
    monkeypatch.setattr(worker.os, "kill", kill_one)
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: sorted(alive))
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: f"start-{pid}")
    monkeypatch.setattr(
        procutil, "check_identity", lambda _pid, _expected: procutil.IDENTITY_MATCH,
    )
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)

    worker._kill_pgid(
        999, state_path=tmp_path / "dispatch_state.json", grace_s=1,
    )

    assert signal.SIGKILL in [sig for _, sig in per_pid], \
        "killpg was denied — must escalate per-pid, not give up"


# ---------------------------------------------------------------------------
# quota class — 2026-07-05 weekly-quota outage: "You've hit your weekly limit ·
# resets 4pm" matched no class → hard_failure → the full retry ladder burned on
# every hourly fire for 5h (15 wasted attempts). Quota is its own class:
# no-retry, NO auth_blocked (auto-resolves at reset; next hourly fire's single
# attempt self-resumes), one warn email per outage (4h dedup).
# ---------------------------------------------------------------------------


def test_classify_quota_messages() -> None:
    assert worker._classify(1, "You've hit your weekly limit · resets 4pm") == "quota"
    assert worker._classify(1, "You've hit your 5-hour limit") == "quota"
    assert worker._classify(1, "usage limit reached") == "quota"
    # rate-limit (transient) must NOT be swallowed by quota
    assert worker._classify(1, "429 rate limit exceeded, retry soon") == "transient"
    # auth still wins over quota-ish text
    assert worker._classify(1, "Not logged in. Please run /login") == "auth"


def test_worker_quota_aborts_without_retry_and_without_auth_block(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    attempts: list[int] = []
    quota_alerts: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        state.mark_job_phase(
            job_id=kwargs["job_id"], expected_attempt=kwargs["attempt"],
            phase="classifying", path=kwargs["state_path"],
        )
        log_path.write_text("You've hit your weekly limit · resets 4pm", encoding="utf-8")
        return 1, 1.0, "You've hit your weekly limit · resets 4pm"

    monkeypatch.setattr(worker, "_run_one_attempt", fake_run_one_attempt)
    monkeypatch.setattr(
        worker.alerts, "send_quota_alert",
        lambda **kwargs: quota_alerts.append(kwargs) or True,
    )

    result = worker.run_worker(
        prompt_text="prompt", log_path=log_path, state_path=state_path,
        sleep_fn=lambda sec: None,
    )

    snap = state.read_state(state_path)
    assert result.outcome == "quota_blocked"
    assert result.attempts == 1, "quota must NOT trigger the retry ladder"
    assert attempts == [1]
    assert snap["auth_blocked"] is False, (
        "quota must NOT set auth_blocked — it auto-resolves at reset; "
        "a manual unblock requirement would strand the loop"
    )
    assert len(quota_alerts) == 1
    # Note: record_completion no-ops when current_job is absent (the mocked
    # _run_one_attempt skips reserve_fire/attach_process) — same caveat as the
    # timeout-path test above; WorkerResult.outcome is the authoritative check.


def test_quota_alert_dedup_one_email_per_outage(tmp_path: Path, monkeypatch) -> None:
    """During a multi-hour outage, hourly fires each hit quota — only the FIRST
    should email (4h dedup); the rest silently dedup."""
    state_path = _tmp_state(tmp_path)
    sends: list[str] = []
    monkeypatch.setattr(supervisor.alerts, "_send", lambda level, title, body: sends.append(title) or 0)

    assert supervisor.alerts.send_quota_alert(log_tail="limit", state_path=state_path) is True
    assert supervisor.alerts.send_quota_alert(log_tail="limit", state_path=state_path) is False
    assert supervisor.alerts.send_quota_alert(log_tail="limit", state_path=state_path) is False
    assert len(sends) == 1


# ---------------------------------------------------------------------------
# Cross-fire log contamination (2026-07-05 audit): the shared append-log's
# global tail can hold a PREVIOUS fire's quota/auth lines; classification must
# only see bytes THIS attempt wrote (offset-scoped _read_since), or a stale
# 'Not logged in' would freeze the loop behind a manual unblock.
# ---------------------------------------------------------------------------


def test_read_since_returns_only_bytes_after_offset(tmp_path: Path) -> None:
    log = tmp_path / "w.log"
    log.write_bytes(b"OLD: Not logged in. Please run /login\n")
    offset = worker._log_size(log)
    with log.open("ab") as f:
        f.write(b"NEW: some unrelated hard failure\n")
    out = worker._read_since(log, offset)
    assert "Not logged in" not in out
    assert "unrelated hard failure" in out
    # nothing new after EOF offset → empty
    assert worker._read_since(log, worker._log_size(log)) == ""


def test_stale_auth_line_in_shared_log_does_not_freeze_loop(tmp_path: Path, monkeypatch) -> None:
    """End-to-end: previous fire left 'Not logged in' in the shared log; this
    attempt fails with an unrelated error. Must classify hard_failure (retry),
    NOT auth (which would set auth_blocked and halt all future fires)."""
    state_path = _tmp_state(tmp_path)
    _stub_worker_custody(monkeypatch)
    log_path = tmp_path / "worker.log"
    log_path.write_text("PREVIOUS FIRE: Not logged in. Please run /login\n", encoding="utf-8")

    class FakeProc:
        pid = 4242
        def wait(self, timeout=None):
            with log_path.open("ab") as f:
                f.write(b"boom: unrelated crash\n")
            return 1

    spawned: list[dict] = []
    monkeypatch.setattr(
        worker,
        "_spawn",
        lambda **kwargs: spawned.append(kwargs) or FakeProc(),
    )
    monkeypatch.setattr(worker.procutil, "get_process_start_wall", lambda pid: "Wed Jan  1 00:00:00 2026")

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    exit_code, _dur, attempt_output = worker._run_one_attempt(
        prompt_text="p", model=worker.OPUS_MODEL, timeout_s=5,
        log_path=log_path, attempt=1, schedule_id="hourly_dispatch",
        state_path=state_path, claude_bin="/tmp/claude", workdir=scratch,
    )
    assert spawned[0]["cwd"] == scratch
    assert spawned[0]["argv"][spawned[0]["argv"].index("--add-dir") + 1] == str(worker.PROJECT_ROOT)
    assert (
        spawned[0]["argv"][spawned[0]["argv"].index("--settings") + 1]
        == "/tmp/pinned-claude-settings.json"
    )
    assert "Not logged in" not in attempt_output, "stale auth line must not leak into classification input"
    assert worker._classify(exit_code, attempt_output) == "hard_failure"


# ---------------------------------------------------------------------------
# Fire request (2026-07-05 gmail double-dispatch race fix): external triggers
# write a flag under the state lock; the scheduler consumes it and fires
# through the normal single-slot path.
# ---------------------------------------------------------------------------


def test_fire_request_roundtrip(tmp_path: Path) -> None:
    state_path = _tmp_state(tmp_path)
    assert state.consume_fire_request(state_path) is None
    state.request_fire("email_reply:task_x", path=state_path)
    assert state.read_state(state_path)["fire_requested_at"] is not None
    assert state.consume_fire_request(state_path) == "email_reply:task_x"
    # consumed exactly once
    assert state.consume_fire_request(state_path) is None
    assert state.read_state(state_path)["fire_requested_at"] is None


def test_atomic_reservation_rejects_same_reason_replacement_request(
    tmp_path: Path,
) -> None:
    """Immutable identity closes the same-reason ABA hole in admission CAS."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    state.request_fire("same-owner-reason", path=state_path)
    original = state.read_state(state_path)
    original_request_id = original["fire_request_id"]
    last_fire_before = state.read_state(state_path)["last_fire_at"]

    state.request_fire("same-owner-reason", path=state_path)
    replacement = state.read_state(state_path)
    assert replacement["fire_request_id"] != original_request_id

    with pytest.raises(state.FireRequestChanged) as exc_info:
        state.reserve_fire(
            schedule_id="hourly_dispatch",
            attempt=1,
            model="opus",
            log_path="/tmp/worker.log",
            consume_request=True,
            expected_fire_request="same-owner-reason",
            expected_fire_request_id=original_request_id,
            path=state_path,
        )

    assert exc_info.value.actual == "same-owner-reason"
    assert exc_info.value.actual_request_id == replacement["fire_request_id"]
    snapshot = state.read_state(state_path)
    assert snapshot["fire_request_reason"] == "same-owner-reason"
    assert snapshot["fire_request_id"] == replacement["fire_request_id"]
    assert snapshot["fire_requested_at"] is not None
    assert snapshot["last_fire_at"] == last_fire_before
    assert snapshot["current_jobs"] == []


def test_atomic_reservation_accepts_legacy_timestamp_request_identity(
    tmp_path: Path,
) -> None:
    """A live pre-token state migrates by stable timestamp, never by reset."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    requested_at = "2026-07-29T18:30:00+00:00"
    with state._locked_state(state_path) as (_fh, data):
        data["fire_requested_at"] = requested_at
        data["fire_request_reason"] = "legacy-owner"
        data.pop("fire_request_id", None)
    snapshot = state.read_state(state_path)
    reason, request_id = state.fire_request_snapshot(snapshot)
    assert (reason, request_id) == (
        "legacy-owner",
        f"legacy:{requested_at}",
    )

    handle = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/worker.log",
        consume_request=True,
        expected_fire_request=reason,
        expected_fire_request_id=request_id,
        path=state_path,
    )

    assert handle.job_id
    current = state.read_state(state_path)
    assert current["fire_requested_at"] is None
    assert current["fire_request_reason"] is None
    assert current["fire_request_id"] is None
    assert len(current["current_jobs"]) == 1


def test_legacy_multislot_state_fails_closed_without_consuming_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    for pid in (101, 202):
        handle = state.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path=f"/tmp/{pid}.log", max_slots=2, path=state_path,
        )
        state.attach_process(
            job_id=handle.job_id, expected_attempt=1,
            pid=pid, pgid=pid, started_wall=f"wall-{pid}", path=state_path,
        )
    state.request_fire("email_reply:test", path=state_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    schedules = tmp_path / "runtime_schedules.json"
    schedules.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID,
        "max_slots": 2,
        "producer_custody": {"mode": "per_fire_isolated_coalition"},
    }]}), encoding="utf-8")
    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **_kwargs: pytest.fail("full pool must not spawn"),
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt,
        log_path=tmp_path / "worker.log", dry_run=False, repo_root=tmp_path,
        schedules_path=schedules, max_slots=2, background=True,
    ))

    assert decision == {
        "action": "skip",
        "reason": "producer_slot_in_flight",
        "active_jobs": 2,
    }
    assert state.read_state(state_path)["fire_requested_at"] is not None


def test_unimplemented_isolated_mode_cannot_launch_second_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    lifecycle = _fire_lifecycle("shared-cohort-generation")
    first = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/first.log", max_slots=2, path=state_path,
    )
    state.attach_fire_lifecycle(
        job_id=first.job_id, lifecycle=lifecycle, path=state_path,
    )
    state.attach_process(
        job_id=first.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="wall-101", path=state_path,
    )
    _seed_due(state_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    schedules = tmp_path / "runtime_schedules.json"
    schedules.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID,
        "max_slots": 2,
        "producer_custody": {"mode": "per_fire_isolated_coalition"},
    }]}), encoding="utf-8")
    monkeypatch.setattr(
        scheduler.worker,
        "run_worker",
        lambda **_kwargs: pytest.fail(
            "a config string cannot create an isolated kernel coalition"
        ),
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt,
        log_path=tmp_path / "worker.log", dry_run=False, repo_root=tmp_path,
        schedules_path=schedules, max_slots=2, background=True,
    ))

    assert decision == {
        "action": "skip",
        "reason": "producer_slot_in_flight",
        "active_jobs": 1,
    }
    jobs = state.read_state(state_path)["current_jobs"]
    assert [(job["job_id"], job["fire_lifecycle"]) for job in jobs] == [
        (first.job_id, lifecycle),
    ]


def test_multislot_health_closes_dead_job_without_touching_live_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    handles = []
    for pid in (101, 202):
        handle = state.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path=f"/tmp/{pid}.log", max_slots=2, path=state_path,
        )
        state.attach_process(
            job_id=handle.job_id, expected_attempt=1,
            pid=pid, pgid=pid, started_wall=f"wall-{pid}", path=state_path,
        )
        handles.append(handle)
    monkeypatch.setattr(
        health.procutil, "check_identity",
        lambda pid, _wall: procutil.IDENTITY_DEAD if pid == 101 else procutil.IDENTITY_MATCH,
    )
    monkeypatch.setattr(
        health.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [],
    )
    sent: list[dict] = []
    monkeypatch.setattr(
        health.alerts, "send_silent_death_alert",
        lambda **kwargs: sent.append(kwargs) or True,
    )

    assert health.check_once(state_path=state_path, max_age_s=99999) == "silent_death"
    jobs = state.read_state(state_path)["current_jobs"]
    assert [job["job_id"] for job in jobs] == [handles[1].job_id]
    assert jobs[0]["pid"] == 202
    assert len(sent) == 1


def test_multislot_health_timeout_kills_only_the_overdue_slot_in_same_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout is per slot, never a cohort-wide kill sweep.

    Regression for the 2026-07-20 incident: three workers returned within
    1.5 seconds despite ages of 131s/612s/672s.  If one sibling really crosses
    the watchdog ceiling, health must signal only that sibling's PGID and
    leave younger jobs in the same cohort running.
    """
    state_path = _tmp_state(tmp_path)
    cohort_id = "same-cohort"
    handles = []
    for slot, pid in enumerate((101, 202, 303), start=1):
        handle = state.reserve_fire(
            schedule_id="hourly_dispatch", attempt=1, model="opus",
            log_path=f"/tmp/{pid}.log", max_slots=3, cohort_id=cohort_id,
            path=state_path,
        )
        assert handle.slot_id == slot
        state.attach_process(
            job_id=handle.job_id, expected_attempt=1,
            pid=pid, pgid=pid, started_wall=f"wall-{pid}", path=state_path,
        )
        handles.append(handle)

    jobs = [
        state.CurrentJob(
            pid=pid, pgid=pid, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1,
            model="opus", log_path=f"/tmp/{pid}.log",
            job_id=handle.job_id, cohort_id=cohort_id, slot_id=handle.slot_id,
            started_wall=f"wall-{pid}", age_seconds=age,
        )
        for handle, pid, age in zip(handles, (101, 202, 303), (3001, 672, 131))
    ]
    monkeypatch.setattr(state, "get_current_jobs", lambda _path=state_path: jobs)
    monkeypatch.setattr(
        health.procutil, "check_identity",
        lambda _pid, _wall: procutil.IDENTITY_MATCH,
    )
    kills: list[int] = []
    monkeypatch.setattr(
        health, "_force_kill_pgid", lambda pgid, **_kw: bool(kills.append(pgid) or True),
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda _pgid: [])
    monkeypatch.setattr(health.alerts, "send_hang_alert", lambda **_kwargs: True)

    assert health.check_once(state_path=state_path, max_age_s=3000) == "killed"
    assert kills == [101]
    survivors = state.read_state(state_path)["current_jobs"]
    assert [job["job_id"] for job in survivors] == [
        handles[1].job_id,
        handles[2].job_id,
    ]
    assert [job["cohort_id"] for job in survivors] == [cohort_id, cohort_id]


def test_health_keeps_quarantine_when_leader_dead_but_pgid_descendant_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    handle = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/orphan.log", path=state_path,
    )
    state.attach_process(
        job_id=handle.job_id, expected_attempt=1,
        pid=777, pgid=888, started_wall="wall-777", path=state_path,
    )
    assert state.mark_job_phase(
        job_id=handle.job_id, expected_attempt=1, expected_pid=777,
        expected_phase="running", phase="kill_failed_orphan", path=state_path,
    )
    monkeypatch.setattr(
        health.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_DEAD,
    )
    monkeypatch.setattr(
        health.procutil, "pgid_members_checked", lambda pgid: [999],
    )

    assert health.check_once(state_path=state_path, max_age_s=0) == "kill_failed_orphan"
    snap = state.read_state(state_path)
    assert snap["current_job"]["job_id"] == handle.job_id
    assert snap["current_job"]["pid"] == 777
    assert snap["completions"] == []


def test_scheduler_does_not_close_quarantined_worker_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduler safety net must not erase a worker whose kill failed."""
    state_path = _tmp_state(tmp_path)
    handle = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/quarantine.log", max_slots=2, path=state_path,
    )

    def quarantined_worker(**kwargs):
        state.attach_process(
            job_id=kwargs["job_id"], expected_attempt=1,
            pid=777, pgid=888, started_wall="wall-777", path=state_path,
        )
        assert state.mark_job_phase(
            job_id=kwargs["job_id"], expected_attempt=1,
            expected_phase="running", expected_pid=777,
            phase="kill_failed_orphan", path=state_path,
        )
        return worker.WorkerResult(
            exit_code=137, outcome="kill_failed_orphan", final_model="codex",
            attempts=1, duration_s=1.0, log_tail="kill refused",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", quarantined_worker)
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **_kwargs: pytest.fail("quarantined slot has not drained"),
    )

    result = asyncio.run(scheduler._run_reserved_fire(
        job_id=handle.job_id, cohort_id=handle.cohort_id,
        slot_id=f"slot-{handle.slot_id}", prompt="prompt",
        scheduled_for="2026-07-13T00:07:00+00:00", fire_reason="cron",
        log_path=tmp_path / "worker.log", state_path=state_path,
        repo_root=tmp_path,
    ))

    jobs = state.read_state(state_path)["current_jobs"]
    assert result["outcome"] == "kill_failed_orphan"
    assert result["phase_z"]["reason"] == "deferred_until_cohort_drain"
    assert [(job["job_id"], job["phase"], job["pid"]) for job in jobs] == [
        (handle.job_id, "kill_failed_orphan", 777),
    ]


def test_load_max_slots_stays_one_until_kernel_isolation_exists(tmp_path: Path) -> None:
    cfg = tmp_path / "runtime_schedules.json"
    state_path = _tmp_state(tmp_path)
    cfg.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID, "max_slots": 3,
    }]}), encoding="utf-8")
    assert scheduler.load_max_slots(
        schedules_path=cfg, state_path=state_path,
    ) == scheduler.FAIL_CLOSED_MAX_SLOTS

    cfg.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID, "max_slots": 0,
    }]}), encoding="utf-8")
    assert scheduler.load_max_slots(
        schedules_path=cfg, state_path=state_path,
    ) == scheduler.FAIL_CLOSED_MAX_SLOTS


def test_unknown_custody_mode_fails_closed_shared_and_single_slot(
    tmp_path: Path,
) -> None:
    cfg = tmp_path / "runtime_schedules.json"
    cfg.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID,
        "max_slots": 9,
        "producer_custody": {"mode": "per_fire_isolated_coaltion_typo"},
        "writer_isolation": {"max_active": 9},
    }]}), encoding="utf-8")

    assert scheduler.load_producer_custody_mode(
        schedules_path=cfg,
    ) == scheduler.SHARED_LAUNCHD_COALITION_MODE
    assert scheduler.load_max_slots(schedules_path=cfg) == 1


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "{not-json",
        json.dumps({"daemons": []}),
    ],
)
def test_load_max_slots_ambiguous_config_fails_closed_to_one(
    tmp_path: Path,
    payload: str | None,
) -> None:
    cfg = tmp_path / "runtime_schedules.json"
    if payload is not None:
        cfg.write_text(payload, encoding="utf-8")

    assert scheduler.load_max_slots(
        schedules_path=cfg,
        state_path=_tmp_state(tmp_path),
    ) == scheduler.FAIL_CLOSED_MAX_SLOTS


@pytest.mark.parametrize(
    ("configured_slots", "configured_writer_active"),
    [(4, 2), (0, 2), (True, 1), (1, 9)],
)
def test_load_max_slots_shared_coalition_fails_safe_to_one(
    tmp_path: Path,
    configured_slots: object,
    configured_writer_active: int,
) -> None:
    cfg = tmp_path / "runtime_schedules.json"
    cfg.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID,
        "max_slots": configured_slots,
        "producer_custody": {
            "mode": scheduler.SHARED_LAUNCHD_COALITION_MODE,
        },
        "writer_isolation": {"max_active": configured_writer_active},
    }]}), encoding="utf-8")

    assert scheduler.load_max_slots(schedules_path=cfg) == 1


def test_production_shared_coalition_config_enforces_single_writer() -> None:
    config = json.loads(scheduler.SCHEDULES_PATH.read_text(encoding="utf-8"))
    daemon = next(
        item for item in config["daemons"]
        if item["id"] == scheduler.DAEMON_ID
    )

    assert daemon["producer_custody"]["mode"] == (
        scheduler.SHARED_LAUNCHD_COALITION_MODE
    )
    assert daemon["max_slots"] == 1
    assert daemon["writer_isolation"]["max_active"] == 1
    assert scheduler.load_max_slots() == 1


def test_phase_z_recovery_retains_token_on_nonterminal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    handle = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/a.log", path=state_path,
    )
    state.attach_process(
        job_id=handle.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="wall", path=state_path,
    )
    state.attach_fire_lifecycle(
        job_id=handle.job_id, lifecycle=_fire_lifecycle(), path=state_path,
    )
    state.record_completion(
        job_id=handle.job_id, expected_attempt=1, expected_pid=101,
        exit_code=0, outcome="success", final_model="opus", path=state_path,
    )
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **_kwargs: {"committed": False, "reason": "status_error"},
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "unused.md", log_path=tmp_path / "unused.log",
        dry_run=False, repo_root=tmp_path,
    ))

    assert decision["action"] == "phase_z_recovery_pending"
    assert len(state.read_state(state_path)["phase_z_pending"]) == 1


def test_scheduler_fires_off_cadence_on_fire_request(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    # make cron NOT due: last fire = now
    state.reserve_fire(schedule_id="s", attempt=1, model="m", log_path="/tmp/x", path=state_path)
    state.release_reservation(state_path)  # sets last_fire_at=now, slot free
    fired: list[dict] = []

    def fake_run_worker(**kwargs):
        fired.append(kwargs)
        return worker.WorkerResult(exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
                                   attempts=1, duration_s=1.0, log_tail="ok")

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)

    # without a request → not_due skip
    d1 = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "w.log", dry_run=False, repo_root=tmp_path,
    ))
    assert d1["action"] == "skip" and d1["reason"] == "not_due"

    # with a request → fires immediately, request consumed
    state.request_fire("email_reply:task_y", path=state_path)
    d2 = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "w.log", dry_run=False, repo_root=tmp_path,
    ))
    assert d2["action"] == "fired"
    assert d2["fire_reason"].startswith("requested:email_reply")
    assert len(fired) == 1
    assert state.read_state(state_path)["fire_requested_at"] is None


def test_defer_reserved_fire_atomically_releases_exact_job_and_restores_demand(
    tmp_path: Path,
) -> None:
    state_path = _tmp_state(tmp_path)
    first = state.reserve_fire(
        schedule_id="s",
        attempt=1,
        model="m",
        log_path="/tmp/first",
        max_slots=2,
        path=state_path,
    )
    second = state.reserve_fire(
        schedule_id="s",
        attempt=1,
        model="m",
        log_path="/tmp/second",
        max_slots=2,
        path=state_path,
    )

    snapshot = state.defer_reserved_fire(
        job_id=first.job_id,
        reason="writer_isolation_deferred:test",
        path=state_path,
    )

    assert snapshot is not None
    current = state.read_state(state_path)
    assert [job["job_id"] for job in current["current_jobs"]] == [second.job_id]
    assert current["fire_requested_at"] is not None
    assert current["fire_request_reason"] == "writer_isolation_deferred:test"
    assert state.defer_reserved_fire(
        job_id=first.job_id,
        reason="duplicate",
        path=state_path,
    ) is None


def test_quota_dedup_cleared_on_next_success(tmp_path: Path, monkeypatch) -> None:
    """Outage-scoped semantics: success ends the outage → next outage emails again."""
    state_path = _tmp_state(tmp_path)
    sends: list[str] = []
    monkeypatch.setattr(supervisor.alerts, "_send", lambda level, title, body: sends.append(title) or 0)

    assert supervisor.alerts.send_quota_alert(log_tail="limit", state_path=state_path) is True
    assert supervisor.alerts.send_quota_alert(log_tail="limit", state_path=state_path) is False

    # a successful fire ends the outage
    def ok_attempt(**kwargs):
        return 0, 1.0, "ok"
    monkeypatch.setattr(worker, "_run_one_attempt", ok_attempt)
    result = worker.run_worker(prompt_text="p", log_path=tmp_path / "w.log",
                               state_path=state_path, sleep_fn=lambda s: None)
    assert result.outcome == "success"

    # NEXT outage must email again despite 7d backstop window
    assert supervisor.alerts.send_quota_alert(log_tail="limit again", state_path=state_path) is True
    assert len(sends) == 2


# ---------------------------------------------------------------------------
# Deploy-aware restart-alert suppression (2026-07-10, ops-superv-restart-noise)
# ---------------------------------------------------------------------------
def _tmp_marker(tmp_path: Path) -> Path:
    return tmp_path / "supervisor_restart_marker.json"


def test_planned_restart_marker_roundtrip_fresh(tmp_path: Path) -> None:
    """A fresh marker is consumed once and returns its reason."""
    marker = _tmp_marker(tmp_path)
    state.write_planned_restart_marker(reason="deploy", ttl_s=120, path=marker)
    assert marker.exists()
    assert state.consume_planned_restart_marker(path=marker) == "deploy"
    # consume-once: the file is gone and a second read yields None
    assert not marker.exists()
    assert state.consume_planned_restart_marker(path=marker) is None


def test_planned_restart_marker_expired_treated_as_unexpected(tmp_path: Path) -> None:
    """A stale marker must NOT suppress --- it returns None and is cleaned up."""
    marker = _tmp_marker(tmp_path)
    state.write_planned_restart_marker(reason="deploy", ttl_s=1, path=marker)
    time.sleep(1.2)
    assert state.consume_planned_restart_marker(path=marker) is None
    assert not marker.exists()  # consumed even though stale


def test_planned_restart_marker_corrupt_returns_none(tmp_path: Path) -> None:
    """Corrupt marker JSON is logged and treated as no-marker (alert fires)."""
    marker = _tmp_marker(tmp_path)
    marker.write_text("{not json", encoding="utf-8")
    assert state.consume_planned_restart_marker(path=marker) is None
    assert not marker.exists()


def test_supervisor_restart_planned_reason_suppresses_email(tmp_path: Path, monkeypatch) -> None:
    """planned_reason set --- log-only breadcrumb, NO email, returns False."""
    state_path = _tmp_state(tmp_path)
    sends: list[str] = []
    monkeypatch.setattr(supervisor.alerts, "_send", lambda level, title, body: sends.append(title) or 0)

    sent = supervisor.alerts.send_supervisor_restart(
        prev_started="2026-07-10T05:00:00+00:00",
        planned_reason="deploy",
        state_path=state_path,
    )
    assert sent is False
    assert sends == []  # deploy reload never emails


def test_dispatch_supervisor_email_title_identifies_new_architecture(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(supervisor.alerts.subprocess, "run", run)

    assert supervisor.alerts._send("info", "supervisor restart", "# body") == 0

    command = calls[0]
    title_index = command.index("--title") + 1
    assert command[title_index] == "[新架構派發] supervisor restart"
    assert "--force" not in command


def test_loop_crash_transport_identity_groups_same_trace_and_separates_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sends: list[str] = []
    monkeypatch.setattr(
        supervisor.alerts,
        "_send",
        lambda _level, title, _body: sends.append(title) or 0,
    )

    supervisor.alerts.send_loop_crash(
        "health_loop",
        "Traceback\nRuntimeError: database unavailable",
        state_path=tmp_path / "first.json",
    )
    supervisor.alerts.send_loop_crash(
        "health_loop",
        "Traceback\nRuntimeError: database unavailable",
        state_path=tmp_path / "same-root.json",
    )
    supervisor.alerts.send_loop_crash(
        "health_loop",
        "Traceback\nPermissionError: lease denied",
        state_path=tmp_path / "different-root.json",
    )

    assert sends[0] == sends[1]
    assert sends[2] != sends[0]
    assert all("episode=" in title for title in sends)


def test_loop_crash_transport_identity_ignores_occurrence_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sends: list[str] = []
    monkeypatch.setattr(
        supervisor.alerts,
        "_send",
        lambda _level, title, _body: sends.append(title) or 0,
    )
    first = """Traceback (most recent call last):
  File "/private/var/folders/aa/run-101/scheduler.py", line 417, in health_tick
    await check_task("task-101")
RuntimeError: task assign_01a5feda failed at 2026-07-30T03:20:01Z
"""
    same_root_new_occurrence = """Traceback (most recent call last):
  File "/private/var/folders/bb/run-999/scheduler.py", line 611, in health_tick
    await check_task("task-999")
RuntimeError: task assign_99bbccdd failed at 2026-07-30T03:24:59Z
"""
    different_frame = """Traceback (most recent call last):
  File "/private/var/folders/bb/run-999/scheduler.py", line 611, in scheduler_tick
    await check_task("task-999")
RuntimeError: task assign_99bbccdd failed at 2026-07-30T03:24:59Z
"""
    different_reason_same_frame = """Traceback (most recent call last):
  File "/private/var/folders/cc/run-777/scheduler.py", line 733, in health_tick
    await check_task("task-777")
RuntimeError: task-pool schema corrupt
"""

    supervisor.alerts.send_loop_crash(
        "health_loop", first, state_path=tmp_path / "first.json",
    )
    supervisor.alerts.send_loop_crash(
        "health_loop",
        same_root_new_occurrence,
        state_path=tmp_path / "same-root.json",
    )
    supervisor.alerts.send_loop_crash(
        "health_loop",
        different_frame,
        state_path=tmp_path / "different-frame.json",
    )
    supervisor.alerts.send_loop_crash(
        "health_loop",
        different_reason_same_frame,
        state_path=tmp_path / "different-reason.json",
    )

    assert sends[0] == sends[1]
    assert sends[2] != sends[0]
    assert sends[3] != sends[0]


def test_hang_transport_identity_groups_same_outcome_and_separates_survivors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sends: list[str] = []
    monkeypatch.setattr(
        supervisor.alerts,
        "_send",
        lambda _level, title, _body: sends.append(title) or 0,
    )

    base_job = {
        "pid": 101,
        "pgid": 101,
        "started_at": "2026-07-30T00:00:00+00:00",
        "attempt": 1,
        "model": "claude-opus-5",
        "log_path": "",
    }
    supervisor.alerts.send_hang_alert(
        job={**base_job, "job_id": "job-a"},
        log_tail="same worker tail",
        state_path=tmp_path / "job-a.json",
    )
    supervisor.alerts.send_hang_alert(
        job={**base_job, "job_id": "job-b", "pid": 102, "pgid": 102},
        log_tail="same worker tail",
        state_path=tmp_path / "job-b.json",
    )
    supervisor.alerts.send_hang_alert(
        job={
            **base_job,
            "job_id": "job-c",
            "pid": 103,
            "pgid": 103,
            "survivors": [103],
            "slot_quarantined": True,
        },
        log_tail="same worker tail",
        state_path=tmp_path / "job-c.json",
    )

    assert sends[0] == sends[1]
    assert sends[2] != sends[0]
    assert sends == [
        "supervisor hang_killed outcome=reaped",
        "supervisor hang_killed outcome=reaped",
        "supervisor hang_killed outcome=survivors",
    ]


def test_supervisor_transport_titles_separate_actionable_outcome_classes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sends: list[str] = []
    monkeypatch.setattr(
        supervisor.alerts,
        "_send",
        lambda _level, title, _body: sends.append(title) or 0,
    )

    supervisor.alerts.send_silent_death_alert(
        job={"job_id": "a", "schedule_id": "hourly_dispatch"},
        state_path=tmp_path / "silent-hourly.json",
    )
    supervisor.alerts.send_silent_death_alert(
        job={"job_id": "b", "schedule_id": "maintenance"},
        state_path=tmp_path / "silent-maintenance.json",
    )
    supervisor.alerts.send_completion_failure(
        entry={"exit_code": 1, "outcome": "auth_blocked"},
        state_path=tmp_path / "failure-auth.json",
    )
    supervisor.alerts.send_completion_failure(
        entry={"exit_code": 1, "outcome": "test_failure"},
        state_path=tmp_path / "failure-test.json",
    )
    supervisor.alerts.send_orphan_restart_alert(
        job={"job_id": "c"},
        killed=False,
        outcome="orphan_gone_or_reused",
        state_path=tmp_path / "orphan-gone.json",
    )
    supervisor.alerts.send_orphan_restart_alert(
        job={"job_id": "d"},
        killed=False,
        outcome="orphan_unverified_not_killed",
        state_path=tmp_path / "orphan-unverified.json",
    )

    assert sends[0] != sends[1]
    assert sends[2] != sends[3]
    assert sends[4] != sends[5]
    assert "schedule=hourly_dispatch" in sends[0]
    assert "outcome=auth_blocked" in sends[2]
    assert "outcome=orphan_unverified_not_killed" in sends[5]
    assert "action=not_killed" in sends[5]


def test_completion_failure_transport_identity_uses_stable_log_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sends: list[str] = []
    monkeypatch.setattr(
        supervisor.alerts,
        "_send",
        lambda _level, title, _body: sends.append(title) or 0,
    )
    first = """Traceback (most recent call last):
  File "/tmp/run-101/worker.py", line 10, in execute
RuntimeError: task-101 failed
"""
    same_root = """Traceback (most recent call last):
  File "/tmp/run-999/worker.py", line 88, in execute
RuntimeError: task-999 failed
"""
    different_root = """Traceback (most recent call last):
  File "/tmp/run-999/worker.py", line 88, in execute
RuntimeError: task-pool schema corrupt
"""

    for index, tail in enumerate((first, same_root, different_root)):
        supervisor.alerts.send_completion_failure(
            entry={"exit_code": 1, "outcome": "failure"},
            log_tail=tail,
            state_path=tmp_path / f"failure-{index}.json",
        )

    assert sends[0] == sends[1]
    assert sends[2] != sends[0]
    assert all("outcome=failure" in title for title in sends)
    assert all("root=" in title for title in sends)


def test_slot_prompt_labels_all_external_reports_and_preserves_incident_timeline(
    tmp_path: Path,
) -> None:
    prompt = scheduler._slot_prompt(
        "original task",
        slot_id="slot-1",
        job_id="job-123",
        workdir=tmp_path / "scratch",
        repo_root=tmp_path / "repo",
    )

    assert "所有對外 Email、Telegram 與最終回報" in prompt
    assert "[新架構派發]" in prompt
    assert "現在健康只能證明已恢復" in prompt
    assert "不能把先前告警改稱誤報" in prompt


def test_slot_prompt_binds_supervisor_selected_generic_task(
    tmp_path: Path,
) -> None:
    prompt = scheduler._slot_prompt(
        "original task",
        slot_id="slot-1",
        job_id="job-123",
        workdir=tmp_path / "scratch",
        repo_root=tmp_path / "repo",
        selected_task_id="article-starved",
    )

    assert "[Supervisor-selected generic task]" in prompt
    assert "task_id=article-starved" in prompt
    assert "$VOLPRED_PRESELECTED_TASK_ID" in prompt
    assert "唯一可 claim" in prompt


def test_supervisor_restart_unexpected_still_emails(tmp_path: Path, monkeypatch) -> None:
    """No marker (planned_reason=None) --- genuine restart still alerts once."""
    state_path = _tmp_state(tmp_path)
    sends: list[str] = []
    monkeypatch.setattr(supervisor.alerts, "_send", lambda level, title, body: sends.append(title) or 0)

    first = supervisor.alerts.send_supervisor_restart(
        prev_started="2026-07-10T05:00:00+00:00", planned_reason=None, state_path=state_path,
    )
    assert first is True
    assert sends == ["supervisor restart"]
    # 60s dedup: an immediate second unexpected restart does not re-email
    second = supervisor.alerts.send_supervisor_restart(
        prev_started="2026-07-10T05:00:30+00:00", planned_reason=None, state_path=state_path,
    )
    assert second is False
    assert len(sends) == 1


# -- WS-B producer-scoped workspaces (execution isolation pilot) --------------
# Ownership must be produced by execution isolation, not inferred by a cleanup
# layer afterwards (external adjudication; refactor_plan_ops_master §WS-B).
# These tests pin: machine-built registered worktree, receipt-bound identity,
# gate-green-only integration, and the no-deadlock exit (red output ALWAYS
# ends up as a claimable P2 remediation task, never rots in a worktree).


def _iso_cfg(**overrides) -> dict:
    cfg = {"mode": "pilot", "lanes": ["platform_ops"], "max_active": 1,
           "max_total": 3,
           "disk_floor_gib": 0.0}
    cfg.update(overrides)
    return cfg


def _assigned_mutating_task() -> dict:
    return {
        "ok": True,
        "assigned": True,
        "session": "claim-fixed",
        "contract": {
            "task_id": "task-fixed",
            "claim_session_id": "claim-fixed",
            "write_intent": "repo_patch",
            "declared_output_paths": ["scripts", "tests"],
            "post_merge_actions": [],
            "title": "Fix dispatch",
            "description": "Only edit the declared dispatch paths.",
        },
        "blocked_contracts": [],
    }


def _prepared_isolation(tmp_path: Path) -> isolation.PreparedIsolation:
    run_dir = tmp_path / "isolation-run"
    run_dir.mkdir(exist_ok=True)
    profile = run_dir / "sandbox.sb"
    profile.write_text("(version 1)\n(allow default)\n", encoding="utf-8")
    return isolation.PreparedIsolation(
        profile_path=str(profile),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path),
    )


def _ws_allocate(repo: Path, *, job_id: str = "a" * 32, slot: str = "slot-1",
                 config: dict | None = None, active_isolated: int = 0,
                 task_binding: dict | None = None):
    binding = task_binding or {
        "task_id": f"task-{job_id[:8]}",
        "claim_session_id": f"claim-{job_id[:8]}",
        "dispatch_job_id": job_id,
        "write_intent": "repo_patch",
        "declared_output_paths": [
            "scripts",
            "src",
            "tests",
            "docs",
            "config",
            "README.md",
            "file.txt",
            "conflict.txt",
            "clean.txt",
            "broken.py",
            "candidate.py",
            "change.py",
            "integrated.py",
            "merged.py",
            "not-integrated.py",
            "only-copy.py",
            "needs_owner.py",
            "partial.py",
            "recoverable.py",
            "retry.py",
        ],
        "post_merge_actions": [],
    }
    return workspace.allocate_workspace(
        repo_root=repo, slot_id=slot, job_id=job_id,
        config=config or _iso_cfg(), task_binding=binding,
        active_isolated=active_isolated,
    )


def test_observe_only_workspace_accepts_empty_output_contract(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)

    allocated = _ws_allocate(
        repo,
        job_id="0" * 32,
        task_binding={
            "task_id": "observe-only",
            "claim_session_id": "observe-session",
            "dispatch_job_id": "0" * 32,
            "write_intent": "observe_only",
            "declared_output_paths": [],
            "post_merge_actions": [],
            "title": "Observe only",
            "description": "Do not modify repository files.",
        },
    )

    assert allocated is not None
    assert allocated["write_intent"] == "observe_only"
    assert allocated["declared_output_paths"] == []
    assert workspace._output_contract_violations(
        allocated, ["unexpected.txt"]
    )["undeclared"] == ["unexpected.txt"]


def test_observe_only_settlement_requires_clean_success() -> None:
    clean = {"disposition": "empty_removed"}

    assert scheduler._settlement_disposition(
        clean,
        write_intent="observe_only",
        worker_outcome="success",
    ) == "observed"
    assert scheduler._settlement_disposition(
        clean,
        write_intent="observe_only",
        worker_outcome="system_terminated",
    ) is None
    assert scheduler._settlement_disposition(
        clean,
        write_intent="observe_only",
        worker_outcome="failure",
    ) == "retry"


def test_workspace_rejects_task_binding_for_different_dispatch_job(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)

    allocated = _ws_allocate(
        repo,
        job_id="actual-job",
        task_binding={
            "task_id": "wrong-job-binding",
            "claim_session_id": "wrong-job-session",
            "dispatch_job_id": "different-job",
            "write_intent": "observe_only",
            "declared_output_paths": [],
            "post_merge_actions": [],
        },
    )

    assert allocated is None


def _ws_receipt_events(repo: Path) -> list[dict]:
    dest = repo / workspace.RECEIPTS_RELPATH
    if not dest.exists():
        return []
    return [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]


def _tmp_queue(tmp_path: Path) -> Path:
    queue = tmp_path / "queue" / "next_tasks.json"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text("[]", encoding="utf-8")
    return queue


def test_workspace_allocate_creates_registered_worktree(tmp_path: Path) -> None:
    from volpred.ops.git_writer_lock import is_registered_linked_worktree

    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    assert ws is not None
    path = Path(ws["path"])
    assert path == repo / ".claude" / "worktrees" / "dispatch-slot-1-aaaaaaaa"
    assert path.is_dir()
    assert ws["branch"] == "worktree-dispatch-slot-1-aaaaaaaa"
    # identity is machine-derived and mechanically verifiable -- the same door
    # run_agent_job/compute_queue already use for the experiment lane.
    assert is_registered_linked_worktree(repo, path)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert ws["base_sha"] == head
    events = _ws_receipt_events(repo)
    assert [e["event"] for e in events] == ["allocation_intent", "allocated"]
    allocated = events[1]
    assert allocated["branch"] == ws["branch"]
    assert isinstance(allocated["free_gib_after"], float)
    assert isinstance(allocated["disk_delta_gib"], float)
    assert isinstance(allocated["disk_bytes"], int)
    assert allocated["wall_start"] <= allocated["wall_end"]
    assert allocated["base_sha"] == ws["base_sha"]
    assert allocated["task_binding_status"] == "bound"
    assert allocated["task_id"] == "task-aaaaaaaa"
    assert allocated["claim_session_id"] == "claim-aaaaaaaa"
    assert isinstance(ws["setup_s"], float)


def test_workspace_allocate_disk_floor_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo, config=_iso_cfg(disk_floor_gib=10**9))
    assert ws is None
    events = _ws_receipt_events(repo)
    assert events and events[0]["event"] == "allocation_skipped"
    assert events[0]["reason"] == "disk_floor"
    assert not (repo / ".claude" / "worktrees").exists()


def test_workspace_allocate_respects_live_cap_but_artifact_cap_is_advisory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    # active cap: never a second concurrent isolated fire
    assert _ws_allocate(repo, active_isolated=1) is None
    # Artifact custody never consumes execution capacity.  The historical
    # total cap remains telemetry, while disk floor is the physical backstop.
    first = _ws_allocate(repo, job_id="b" * 32)
    assert first is not None
    second = _ws_allocate(repo, job_id="c" * 32, config=_iso_cfg(max_total=1))
    assert second is not None
    reasons = [e.get("reason") for e in _ws_receipt_events(repo)
               if e["event"] == "allocation_skipped"]
    assert reasons == ["active_cap"]
    assert any(
        event.get("event") == "allocation_advisory"
        and event.get("reason") == "artifact_backlog"
        for event in _ws_receipt_events(repo)
    )


def test_workspace_artifact_backlog_requires_durable_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    first = _ws_allocate(repo, job_id="b" * 32)
    assert first is not None
    real_append = workspace._append_receipt

    def fail_advisory(root: Path, payload: dict) -> bool:
        if payload.get("event") == "allocation_advisory":
            return False
        return real_append(root, payload)

    monkeypatch.setattr(workspace, "_append_receipt", fail_advisory)
    second = _ws_allocate(repo, job_id="c" * 32, config=_iso_cfg(max_total=1))

    assert second is None
    assert not (
        repo / ".claude" / "worktrees" / "dispatch-slot-1-cccccccc"
    ).exists()


def test_workspace_enforce_allows_two_isolated_slots_with_configured_cap(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    cfg = _iso_cfg(mode="enforce", max_active=2, max_total=3)

    first = _ws_allocate(
        tmp_path, job_id="1" * 32, slot="slot-1",
        config=cfg, active_isolated=0,
    )
    second = _ws_allocate(
        tmp_path, job_id="2" * 32, slot="slot-2",
        config=cfg, active_isolated=1,
    )

    assert first is not None
    assert second is not None
    assert first["path"] != second["path"]
    assert first["branch"] != second["branch"]
    assert first["isolation_mode"] == "enforce"
    assert second["isolation_mode"] == "enforce"


def test_workspace_capacity_ignores_worktrees_owned_by_other_dispatch_lanes(
    tmp_path: Path,
) -> None:
    """The isolation cap covers this module's live workspaces, not every
    dispatch-named worktree in the repository.

    Experiment/compute lanes append a task slug to the same historical path
    prefix. Counting those paths made the pilot permanently hit ``total_cap``
    and silently fall back to the shared checkout.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    foreign = (
        repo / ".claude" / "worktrees" / "dispatch-slot-2-deadbeef-k9999"
    )
    subprocess.run(
        [
            "git", "-C", str(repo), "worktree", "add", "-q", "-b",
            "wt/dispatch-slot-2-deadbeef-k9999", str(foreign), "HEAD",
        ],
        check=True,
        capture_output=True,
    )

    ws = _ws_allocate(
        repo,
        job_id="a" * 32,
        config=_iso_cfg(max_total=1),
    )

    assert ws is not None
    assert Path(ws["path"]).name == "dispatch-slot-1-aaaaaaaa"
    assert not [
        event
        for event in _ws_receipt_events(repo)
        if event.get("reason") == "total_cap"
    ]


def test_workspace_capacity_counts_only_receipt_declared_ownership(
    tmp_path: Path,
) -> None:
    """An allocator receipt, not a path regex, is the ownership proof."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    owned_name = "dispatch-slot-2-deadbeef-k9999"
    owned = repo / ".claude" / "worktrees" / owned_name
    subprocess.run(
        [
            "git", "-C", str(repo), "worktree", "add", "-q", "-b",
            f"worktree-{owned_name}", str(owned), "HEAD",
        ],
        check=True,
        capture_output=True,
    )
    assert workspace._append_receipt(
        repo,
        {
            "event": "allocated",
            "workspace": owned_name,
            "path": str(owned),
            "branch": f"worktree-{owned_name}",
        },
    )

    ws = _ws_allocate(
        repo,
        job_id="a" * 32,
        config=_iso_cfg(max_total=1),
    )

    assert ws is not None
    assert any(
        event.get("event") == "allocation_advisory"
        and event.get("reason") == "artifact_backlog"
        for event in _ws_receipt_events(repo)
    )


def test_workspace_allocated_receipt_failure_has_durable_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    real_append = workspace._append_receipt

    def fail_allocated(root: Path, payload: dict) -> bool:
        if payload.get("event") == "allocated":
            return False
        return real_append(root, payload)

    monkeypatch.setattr(workspace, "_append_receipt", fail_allocated)
    ws = _ws_allocate(repo)

    assert ws is None
    path = repo / ".claude" / "worktrees" / "dispatch-slot-1-aaaaaaaa"
    assert not path.exists()
    assert [event["event"] for event in _ws_receipt_events(repo)] == [
        "allocation_intent",
        "allocation_aborted",
    ]


def test_workspace_registration_failure_never_mutates_unverified_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    _bind_drained_workspace_custody(
        monkeypatch,
        repo=repo,
        workspace_receipt=ws,
        job_id="a" * 32,
    )
    real_registration_check = workspace.is_registered_linked_worktree
    monkeypatch.setattr(
        workspace,
        "is_registered_linked_worktree",
        lambda *_args, **_kwargs: False,
    )

    swept = workspace.sweep_orphan_workspaces(
        repo_root=repo,
        protected_job_ids=[],
        queue_path=queue,
    )

    assert swept[0]["reason"] == "registration_verify_failed"
    assert swept[0]["remediation"]["task_id"]
    assert Path(ws["path"]).exists()
    assert not any(
        event["event"] == "released" for event in _ws_receipt_events(repo)
    )
    monkeypatch.setattr(
        workspace,
        "is_registered_linked_worktree",
        real_registration_check,
    )
    replacement = _ws_allocate(
        repo,
        job_id="b" * 32,
        config=_iso_cfg(max_total=1),
    )
    assert replacement is not None
    assert any(
        event.get("event") == "allocation_advisory"
        and event.get("reason") == "artifact_backlog"
        for event in _ws_receipt_events(repo)
    )


def test_workspace_replaced_by_independent_repo_is_never_executed_or_removed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(wt)],
        check=True,
        capture_output=True,
    )
    wt.mkdir(parents=True)
    subprocess.run(["git", "-C", str(wt), "init", "-q"], check=True)
    sentinel = wt / "independent-only.txt"
    sentinel.write_text("do not touch\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="orphaned",
        queue_path=queue,
    )

    assert out["reason"] == "registration_verify_failed"
    assert out["checkpoint"]["released"] is False
    assert sentinel.read_text(encoding="utf-8") == "do not touch\n"
    assert wt.exists()


def test_workspace_finalize_empty_removed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
    )
    assert out["disposition"] == "empty_removed"
    assert not Path(ws["path"]).exists()
    branch_probe = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", ws["branch"]],
        capture_output=True, text=True, check=False,
    )
    assert branch_probe.returncode != 0  # branch cleaned up with the worktree
    assert [e["event"] for e in _ws_receipt_events(repo)] == [
        "allocation_intent",
        "allocated",
        "task_settlement_pending",
        "terminal_intent",
        "finalized",
    ]


def test_workspace_empty_intent_must_persist_before_remove(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    real_append = workspace._append_receipt

    def fail_terminal_intent(root: Path, payload: dict) -> bool:
        if payload.get("event") == "terminal_intent":
            return False
        return real_append(root, payload)

    monkeypatch.setattr(workspace, "_append_receipt", fail_terminal_intent)
    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["reason"] == "empty_intent_not_durable"
    assert Path(ws["path"]).exists()


def test_workspace_empty_terminal_receipt_recovers_after_remove(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    real_append = workspace._append_receipt
    fail_once = {"armed": True}

    def fail_first_finalized(root: Path, payload: dict) -> bool:
        if payload.get("event") == "finalized" and fail_once["armed"]:
            fail_once["armed"] = False
            return False
        return real_append(root, payload)

    monkeypatch.setattr(workspace, "_append_receipt", fail_first_finalized)
    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
    )
    assert first["disposition"] == "empty_removed"
    assert not Path(ws["path"]).exists()

    second = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
    )

    assert second["disposition"] == "empty_removed"
    assert second["replayed"] is True
    assert len([
        event for event in _ws_receipt_events(repo)
        if event["event"] == "finalized"
    ]) == 1


def test_terminal_generation_replays_before_missing_custody_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed generation cannot become nonterminal after a daemon restart."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    job_id = "a" * 32
    ws = _ws_allocate(repo, job_id=job_id)
    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        job_id=job_id,
        producer_drain_confirmed=True,
        queue_path=_tmp_queue(tmp_path),
    )
    assert first["disposition"] == "empty_removed"
    monkeypatch.setattr(
        workspace.procutil,
        "producer_cohort_members_checked",
        lambda *_args, **_kwargs: pytest.fail(
            "terminal generation must replay before custody probing"
        ),
    )

    replay = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="timeout_unverified",
        job_id=job_id,
        queue_path=_tmp_queue(tmp_path),
    )

    assert replay["disposition"] == "empty_removed"
    assert replay["replayed"] is True


def test_terminal_replay_fails_closed_on_partial_receipt_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    job_id = "a" * 32
    ws = _ws_allocate(repo, job_id=job_id)
    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        job_id=job_id,
        producer_drain_confirmed=True,
        queue_path=_tmp_queue(tmp_path),
    )
    assert first["disposition"] == "empty_removed"
    with (repo / workspace.RECEIPTS_RELPATH).open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write('{"event":')
    monkeypatch.setattr(
        workspace.procutil,
        "producer_cohort_members_checked",
        lambda *_args, **_kwargs: None,
    )

    retry = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="timeout_unverified",
        job_id=job_id,
        queue_path=_tmp_queue(tmp_path),
    )

    assert retry["disposition"] == "producer_active"
    assert retry["cohort_status"] == "unverified"


def test_workspace_finalize_gate_green_merges(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "scripts").mkdir(exist_ok=True)
    (wt / "scripts" / "wsb_pilot_change.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-qm", "pilot change"],
                   check=True, capture_output=True)
    merges: list[str] = []

    def fake_gate(**kwargs):
        return {"verdict": "green", "rc": 0, "targets": ["tests/test_x.py"],
                "duration_s": 0.1, "output_tail": ""}

    def fake_merge(**kwargs):
        merges.append(kwargs["workspace"]["name"])
        subprocess.run(
            ["git", "-C", str(repo), "merge", "--ff-only", ws["branch"]],
            check=True,
            capture_output=True,
        )
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=_tmp_queue(tmp_path), gate_fn=fake_gate, merge_fn=fake_merge,
    )
    assert out["disposition"] == "merged"
    assert merges == ["dispatch-slot-1-aaaaaaaa"]
    assert out["gate"]["verdict"] == "green"


def test_workspace_merge_false_success_never_emits_merged(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "not-integrated.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "not-integrated.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"],
        check=True,
    )

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=queue,
        gate_fn=lambda **_kwargs: {
            "verdict": "green",
            "rc": 0,
            "targets": ["tests/test_x.py"],
            "duration_s": 0.1,
        },
        merge_fn=lambda **_kwargs: {
            "ok": True,
            "rc": 0,
            "reason": "merged",
            "output_tail": "",
        },
    )

    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "merge_readback_failed"
    assert not any(
        event.get("event") == "finalized"
        and event.get("disposition") == "merged"
        for event in _ws_receipt_events(repo)
    )


def test_workspace_false_success_without_path_creates_recovery_ref(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "lost-path.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "lost-path.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"],
        check=True,
    )
    gated_sha = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def false_success_and_delete(**_kwargs):
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(wt)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "branch", "-D", ws["branch"]],
            check=True,
            capture_output=True,
        )
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=queue,
        gate_fn=lambda **_kwargs: {
            "verdict": "green",
            "rc": 0,
            "targets": ["tests/test_x.py"],
            "duration_s": 0.1,
        },
        merge_fn=false_success_and_delete,
    )

    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "merge_readback_failed"
    recovery_branch = out["branch"]
    assert recovery_branch.startswith(f"recovery-{ws['name']}-")
    recovered_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", recovery_branch],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert recovered_sha == gated_sha
    assert out["remediation"]["task_id"]


@pytest.mark.parametrize("failure_mode", ["queue", "released_receipt"])
def test_workspace_missing_path_recovery_exit_retries_until_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "retry.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "retry.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"],
        check=True,
    )
    real_append = workspace._append_receipt
    fail_once = {"armed": failure_mode == "released_receipt"}

    def fail_first_release(root: Path, payload: dict) -> bool:
        if payload.get("event") == "released" and fail_once["armed"]:
            fail_once["armed"] = False
            return False
        return real_append(root, payload)

    if failure_mode == "released_receipt":
        monkeypatch.setattr(workspace, "_append_receipt", fail_first_release)
    invalid_queue = tmp_path / "queue-directory"
    invalid_queue.mkdir()
    first_queue = invalid_queue if failure_mode == "queue" else queue

    def delete_without_integrating(**_kwargs):
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(wt)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "branch", "-D", ws["branch"]],
            check=True,
            capture_output=True,
        )
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=first_queue,
        gate_fn=lambda **_kwargs: {
            "verdict": "green",
            "rc": 0,
            "targets": ["tests/test_x.py"],
            "duration_s": 0.1,
        },
        merge_fn=delete_without_integrating,
    )
    assert first["disposition"] == "reconcile_pending"
    assert first["reason"] in {
        "remediation_not_durable",
        "release_receipt_failed",
    }

    second = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=queue,
    )

    assert second["disposition"] == "remediation_opened"
    assert second["checkpoint"]["released"] is True
    assert second["remediation"]["task_id"]


def test_workspace_merged_terminal_receipt_recovers_from_gated_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "merged.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "merged.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"],
        check=True,
    )
    real_append = workspace._append_receipt
    fail_once = {"armed": True}

    def fail_first_finalized(root: Path, payload: dict) -> bool:
        if payload.get("event") == "finalized" and fail_once["armed"]:
            fail_once["armed"] = False
            return False
        return real_append(root, payload)

    def merge_and_cleanup(**_kwargs):
        subprocess.run(
            ["git", "-C", str(repo), "merge", "--ff-only", ws["branch"]],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(wt)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "branch", "-d", ws["branch"]],
            check=True,
            capture_output=True,
        )
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    monkeypatch.setattr(workspace, "_append_receipt", fail_first_finalized)
    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
        gate_fn=lambda **_kwargs: {
            "verdict": "green",
            "rc": 0,
            "targets": ["tests/test_x.py"],
            "duration_s": 0.1,
        },
        merge_fn=merge_and_cleanup,
    )
    assert first["disposition"] == "merged"
    assert not wt.exists()

    second = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
    )

    assert second["disposition"] == "merged"
    assert second["gated_head_sha"] == first["gated_head_sha"]
    assert second["replayed"] is True


def test_workspace_reconciles_integrated_head_before_empty_classification(
    tmp_path: Path,
) -> None:
    """Crash after merge but before cleanup retains the merged lineage."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "integrated.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "integrated.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"],
        check=True,
    )
    head_sha = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert workspace._append_receipt(
        repo,
        {
            "event": "terminal_intent",
            "workspace": ws["name"],
            "branch": ws["branch"],
            "target_disposition": "merged",
            "head_sha": head_sha,
        },
    )
    subprocess.run(
        ["git", "-C", str(repo), "merge", "--ff-only", ws["branch"]],
        check=True,
        capture_output=True,
    )

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["disposition"] == "merged"
    assert out["gated_head_sha"] == head_sha
    assert out["replayed"] is True
    assert not wt.exists()


def test_workspace_stale_merged_intent_never_cleans_advanced_branch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    ws["declared_output_paths"] = ["candidate.py"]
    wt = Path(ws["path"])
    (wt / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "candidate.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "gated candidate"],
        check=True,
    )
    gated_sha = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert workspace._append_receipt(
        repo,
        {
            "event": "terminal_intent",
            "workspace": ws["name"],
            "branch": ws["branch"],
            "target_disposition": "merged",
            "head_sha": gated_sha,
        },
    )
    subprocess.run(
        ["git", "-C", str(repo), "merge", "--ff-only", ws["branch"]],
        check=True,
        capture_output=True,
    )
    (wt / "candidate.py").write_text("VALUE = 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "candidate.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "post-gate advance"],
        check=True,
    )
    advanced_sha = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=queue,
    )

    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "post_gate_branch_advanced"
    assert out["checkpoint"]["commit"] == advanced_sha
    assert not wt.exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", advanced_sha, "main"],
        check=False,
    ).returncode != 0


def test_workspace_finalize_gate_red_opens_remediation_and_keeps_branch(
    tmp_path: Path,
) -> None:
    """The no-deadlock invariant: a red gate NEVER strands the output. It must
    become a pending P2 task the normal dispatch loop is guaranteed to pick up,
    with a durable branch checkpoint -- and re-running the finalizer must not
    duplicate the task."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "broken.py").write_text("x = 1\n", encoding="utf-8")

    def red_gate(**kwargs):
        return {"verdict": "red", "rc": 1, "targets": ["tests/test_y.py"],
                "duration_s": 0.1, "output_tail": "FAILED tests/test_y.py::t"}

    def never_merge(**kwargs):  # pragma: no cover - gate red must block merging
        raise AssertionError("merge must not run on a red gate")

    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=queue, gate_fn=red_gate, merge_fn=never_merge,
    )
    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "gate_red"
    assert out["checkpoint"]["ok"] is True
    assert not wt.exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show", f"{ws['branch']}:broken.py"],
        check=True, capture_output=True, text=True,
    ).stdout == "x = 1\n"
    tasks = json.loads(queue.read_text(encoding="utf-8"))
    assert len(tasks) == 1
    task = tasks[0]
    # incident-lifecycle P3: per-workspace wsb_remed_<name> ids are GONE — the
    # workspace registers as an instance of the worker_orphaned incident and the
    # queue carries ONE aggregate adjudication task (plan §2.3/G3).
    assert task["priority"] == 2
    assert task["status"] == "pending"
    assert task["task_type"] == "platform_ops"
    assert task["dispatch_lane"] == "main_thread"
    assert task["source"] == "incident_adjudication"
    assert "merge_worktree.sh" in task["description"]
    assert "incidents.json" in task["description"]
    assert "git worktree add" in task["description"]
    from volpred.ops import incident as incident_store

    rows = incident_store.list_incidents(repo / "storage" / "ops" / "incidents.json")
    assert len(rows) == 1
    assert rows[0]["kind"] == "worker_orphaned"
    assert {i["key"] for i in rows[0]["instances"]} == {"dispatch-slot-1-aaaaaaaa"}
    assert rows[0]["current_task_id"] == task["id"]
    # idempotent: a second finalize pass (orphan sweep rerun) files nothing new
    out2 = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=queue, gate_fn=red_gate, merge_fn=never_merge,
    )
    assert out2["disposition"] == "remediation_opened"
    assert out2["replayed"] is True
    tasks2 = json.loads(queue.read_text(encoding="utf-8"))
    assert len(tasks2) == 1
    terminal = [
        event for event in _ws_receipt_events(repo)
        if event["event"] in {"finalized", "released"}
    ]
    assert len(terminal) == 1
    assert terminal[0]["event"] == "released"


def test_workspace_finalize_gate_red_checkpoints_branch_and_releases_capacity(
    tmp_path: Path,
) -> None:
    """A failed fire keeps recoverable bytes, not a permanently live checkout.

    The durable branch is the remediation artifact.  Releasing the registered
    worktree directory prevents three failures from exhausting ``max_total``
    and sending every later writer back to shared main.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 'checkpointed'\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        queue_path=queue,
        gate_fn=lambda **_kwargs: {
            "verdict": "red",
            "rc": 1,
            "targets": ["tests/test_recoverable.py"],
            "duration_s": 0.1,
            "output_tail": "FAILED",
        },
        merge_fn=lambda **_kwargs: pytest.fail("red output must not merge"),
    )

    assert out["disposition"] == "remediation_opened"
    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["branch"] == ws["branch"]
    assert out["checkpoint"]["commit"]
    assert not wt.exists()
    recovered = subprocess.run(
        [
            "git", "-C", str(repo), "show",
            f"{ws['branch']}:recoverable.py",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert recovered.stdout == "VALUE = 'checkpointed'\n"

    replacement = _ws_allocate(
        repo,
        job_id="b" * 32,
        config=_iso_cfg(max_total=1),
    )
    assert replacement is not None


def test_workspace_remediation_checkpoints_undeclared_bytes_without_landing_them(
    tmp_path: Path,
) -> None:
    """Integration contracts reject undeclared output; quarantine must preserve it.

    A failed worker can write outside its declared paths.  Those bytes must
    never auto-merge, but leaving the checkout live forever exhausts
    ``max_total``.  Remediation therefore checkpoints the complete
    non-canonical workspace, binds the aggregate adjudication task, and releases
    the checkout while keeping the undeclared bytes recoverable on the branch.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(
        repo,
        task_binding={
            "task_id": "undeclared-output",
            "claim_session_id": "undeclared-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["declared.py"],
            "post_merge_actions": [],
        },
    )
    wt = Path(ws["path"])
    (wt / "undeclared.py").write_text("RECOVER_ME = True\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=queue,
    )

    assert out["disposition"] == "remediation_opened"
    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["released"] is True
    assert out["checkpoint"]["checkpoint_changed_paths"] == ["undeclared.py"]
    assert out["checkpoint"]["quarantined_undeclared_paths"] == ["undeclared.py"]
    assert out["checkpoint"]["task_binding_missing"] is False
    assert not wt.exists()
    recovered = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ws['branch']}:undeclared.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert recovered.stdout == "RECOVER_ME = True\n"


@pytest.mark.parametrize(
    "worker_outcome",
    [
        "kill_failed_orphan",
        "timeout_unverified",
        "orphan_unverified_not_killed",
        "orphan_unverified_no_pid",
    ],
)
def test_workspace_live_or_unverified_producer_is_never_finalized(
    tmp_path: Path,
    worker_outcome: str,
) -> None:
    """Positive producer-death proof precedes every checkpoint and release."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(
        repo,
        config=_iso_cfg(max_total=1),
        task_binding={
            "task_id": "live-producer",
            "claim_session_id": "live-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["partial.py"],
            "post_merge_actions": [],
        },
    )
    wt = Path(ws["path"])
    (wt / "partial.py").write_text("PARTIAL = True\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome=worker_outcome,
        queue_path=queue,
    )

    assert out["disposition"] == "producer_active"
    assert out["reason"] == "producer_liveness_unverified"
    assert out["checkpoint"]["released"] is False
    assert wt.exists()
    assert not [
        event
        for event in _ws_receipt_events(repo)
        if event["event"] in {"checkpointed", "released"}
        and event["workspace"] == ws["name"]
    ]
    assert workspace.pending_task_settlements(repo) == []
    replacement = _ws_allocate(
        repo,
        job_id="e" * 32,
        config=_iso_cfg(max_total=1),
    )
    assert replacement is not None
    assert any(
        event.get("event") == "allocation_advisory"
        and event.get("reason") == "artifact_backlog"
        for event in _ws_receipt_events(repo)
    )


def test_workspace_remediation_releases_clean_legacy_branch_without_binding(
    tmp_path: Path,
) -> None:
    """Pre-contract clean branches are durable evidence, not permanent capacity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = workspace.allocate_workspace(
        repo_root=repo,
        slot_id="slot-1",
        job_id="b" * 32,
        config=_iso_cfg(mode="pilot", max_total=1),
        task_binding=None,
    )
    assert ws is not None
    wt = Path(ws["path"])
    (wt / "legacy_fix.py").write_text("PRESERVED = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "legacy_fix.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "legacy preserved fix",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    legacy_head = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="orphaned",
        queue_path=queue,
    )

    assert out["disposition"] == "remediation_opened"
    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["commit"] == legacy_head
    assert out["checkpoint"]["released"] is True
    assert out["checkpoint"]["checkpoint_changed_paths"] == ["legacy_fix.py"]
    assert out["checkpoint"]["quarantined_undeclared_paths"] == ["legacy_fix.py"]
    assert out["checkpoint"]["task_binding_missing"] is True
    assert not wt.exists()
    replacement = _ws_allocate(
        repo,
        job_id="c" * 32,
        config=_iso_cfg(max_total=1),
    )
    assert replacement is not None


def test_workspace_remediation_still_refuses_canonical_only_paths(
    tmp_path: Path,
) -> None:
    """Quarantine may widen task paths, never the canonical storage boundary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    forbidden = wt / "storage" / "ops" / "forbidden.json"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("{}\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["disposition"] == "remediation_opened"
    assert out["checkpoint"]["ok"] is False
    assert out["checkpoint"]["reason"] == "canonical_path_denied"
    assert out["checkpoint"]["paths"] == ["storage/ops/forbidden.json"]
    assert wt.exists()


def test_workspace_remediation_refuses_committed_canonical_path_with_newline(
    tmp_path: Path,
) -> None:
    """Git's quoted display form must not disguise an exact denied pathname."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    rel = "storage/ops/forbidden\n.json"
    forbidden = wt / rel
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "--", rel], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "commit disguised canonical path",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["checkpoint"]["ok"] is False
    assert out["checkpoint"]["reason"] == "canonical_path_denied"
    assert out["checkpoint"]["paths"] == [rel]
    assert wt.exists()


def test_workspace_remediation_rechecks_denied_paths_under_writer_lock(
    tmp_path: Path,
) -> None:
    """A late producer write cannot race past the quarantine storage fence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    status_calls = 0

    def runner(args, **kwargs):
        nonlocal status_calls
        if "status" in args and str(wt) in args:
            status_calls += 1
            if status_calls == 3:
                raced = wt / "storage" / "ops" / "raced.json"
                raced.parent.mkdir(parents=True)
                raced.write_text("{}\n", encoding="utf-8")
        return subprocess.run(args, **kwargs)

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
        runner=runner,
    )

    assert status_calls >= 2
    assert out["disposition"] == "remediation_opened"
    assert out["checkpoint"]["ok"] is False
    assert out["checkpoint"]["reason"] == "canonical_path_denied"
    assert out["checkpoint"]["paths"] == ["storage/ops/raced.json"]
    assert wt.exists()
    committed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "cat-file",
            "-e",
            f"{ws['branch']}:storage/ops/raced.json",
        ],
        capture_output=True,
        text=True,
    )
    assert committed.returncode != 0


def test_workspace_remediation_marks_partial_binding_missing(
    tmp_path: Path,
) -> None:
    """Declared paths do not make a task binding without its ownership ids."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = workspace.allocate_workspace(
        repo_root=repo,
        slot_id="slot-1",
        job_id="d" * 32,
        config=_iso_cfg(mode="pilot"),
        task_binding={
            "write_intent": "repo_patch",
            "declared_output_paths": ["declared.py"],
        },
    )
    assert ws is not None
    Path(ws["path"], "declared.py").write_text("VALUE = 1\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["released"] is True
    assert out["checkpoint"]["task_binding_missing"] is True
    assert out["checkpoint"]["checkpoint_changed_paths"] == ["declared.py"]
    assert out["checkpoint"]["quarantined_undeclared_paths"] == []


def test_workspace_remediation_refuses_secret_candidate_before_git_write(
    tmp_path: Path,
) -> None:
    """Opaque credentials remain in the checkout and never enter its branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(
        repo,
        task_binding={
            "task_id": "secret-output",
            "claim_session_id": "secret-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["declared.py"],
            "post_merge_actions": [],
        },
    )
    wt = Path(ws["path"])
    secret_path = wt / "debug_credentials.txt"
    secret_text = (
        "access_token=oauth_" + ("A1b2C3d4" * 8) + "\n"
    )
    secret_path.write_text(secret_text, encoding="utf-8")
    candidate_oid = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "--stdin"],
        input=secret_text,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["checkpoint"]["ok"] is False
    assert out["checkpoint"]["reason"] == "secret_candidate_detected"
    assert out["checkpoint"]["paths"] == ["debug_credentials.txt"]
    assert wt.exists()
    committed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "cat-file",
            "-e",
            f"{ws['branch']}:debug_credentials.txt",
        ],
        capture_output=True,
        text=True,
    )
    assert committed.returncode != 0
    loose_object = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", candidate_oid],
        capture_output=True,
        text=True,
    )
    assert loose_object.returncode != 0


def test_workspace_remediation_scans_committed_secret_path_with_newline(
    tmp_path: Path,
) -> None:
    """Secret readback uses exact NUL-delimited paths, not quoted Git output."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    rel = "notes/line\nbreak.txt"
    secret = wt / rel
    secret.parent.mkdir(parents=True)
    secret.write_text(
        "access_token=oauth_" + ("Z9y8X7w6" * 8) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(wt), "add", "--", rel], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "commit disguised secret path",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["checkpoint"]["ok"] is False
    assert out["checkpoint"]["reason"] == "secret_candidate_detected"
    assert out["checkpoint"]["paths"] == [rel]
    assert wt.exists()


def test_workspace_remediation_streams_large_snapshot_with_bounded_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot memory stays constant while the exact large blob is preserved."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(
        repo,
        task_binding={
            "task_id": "large-output",
            "claim_session_id": "large-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["large.bin"],
            "post_merge_actions": [],
        },
    )
    wt = Path(ws["path"])
    large = wt / "large.bin"
    expected_size = 8 * 1024 * 1024
    with large.open("wb") as handle:
        handle.seek(expected_size - 1)
        handle.write(b"\0")
    observed_windows: list[int] = []
    real_scan = workspace._secret_candidate_rules

    def bounded_scan(data: bytes) -> list[str]:
        observed_windows.append(len(data))
        return real_scan(data)

    monkeypatch.setattr(workspace, "_secret_candidate_rules", bounded_scan)

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["released"] is True
    assert observed_windows
    assert max(observed_windows) <= (
        workspace._SECRET_SCAN_CHUNK_BYTES
        + workspace._SECRET_SCAN_OVERLAP_BYTES
    )
    blob_size = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "cat-file",
            "-s",
            f"{ws['branch']}:large.bin",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert int(blob_size) == expected_size


def test_workspace_remediation_streams_large_committed_blob_with_bounded_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed-branch secret readback also avoids capture_output growth."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    large = wt / "large-committed.bin"
    expected_size = 8 * 1024 * 1024
    with large.open("wb") as handle:
        handle.seek(expected_size - 1)
        handle.write(b"\0")
    subprocess.run(
        ["git", "-C", str(wt), "add", "large-committed.bin"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "large committed checkpoint candidate",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    observed_windows: list[int] = []
    real_scan = workspace._secret_candidate_rules

    def bounded_scan(data: bytes) -> list[str]:
        observed_windows.append(len(data))
        return real_scan(data)

    monkeypatch.setattr(workspace, "_secret_candidate_rules", bounded_scan)

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["released"] is True
    assert observed_windows
    assert max(observed_windows) <= (
        workspace._SECRET_SCAN_CHUNK_BYTES
        + workspace._SECRET_SCAN_OVERLAP_BYTES
    )


def test_workspace_stream_scan_matches_long_runtime_credential_across_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact env credentials do not depend on a fixed overlap length."""
    token = ("R7vP3xQ9" * 8750).encode("ascii")
    assert len(token) > workspace._SECRET_SCAN_OVERLAP_BYTES
    monkeypatch.setenv("VOLPRED_REVIEW_TOKEN", token.decode("ascii"))
    prefix = b"x" * (workspace._SECRET_SCAN_CHUNK_BYTES - 66_000)
    payload = prefix + token + b"\n"

    whole = workspace._secret_candidate_rules(payload)
    streamed = workspace._scan_secret_stream(io.BytesIO(payload))

    assert "runtime_credential" in whole
    assert "runtime_credential" in streamed


def test_workspace_stream_scan_matches_long_jwt_across_chunks() -> None:
    """Unbounded JWT segments retain whole-buffer detection semantics."""
    jwt = b"eyJ" + (b"A" * 70_000) + b"." + (b"B" * 12) + b"." + (b"C" * 12)
    prefix = (
        b"x" * (workspace._SECRET_SCAN_CHUNK_BYTES - 66_001)
        + b" "
    )
    payload = prefix + jwt + b"\n"

    whole = workspace._secret_candidate_rules(payload)
    streamed = workspace._scan_secret_stream(io.BytesIO(payload))

    assert "jwt" in whole
    assert "jwt" in streamed


def test_workspace_stream_scan_preserves_jwt_word_boundary() -> None:
    """Streaming detection must not widen the whole-buffer regex contract."""
    payload = (
        b"xeyJ"
        + (b"A" * 12)
        + b"."
        + (b"B" * 12)
        + b"."
        + (b"C" * 12)
    )

    whole = workspace._secret_candidate_rules(payload)
    streamed = workspace._scan_secret_stream(io.BytesIO(payload))

    assert "jwt" not in whole
    assert "jwt" not in streamed


def test_workspace_pipe_scan_enforces_deadline_before_eof() -> None:
    """A child that keeps stdout open cannot bypass the scan timeout."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    started = time.monotonic()
    try:
        with pytest.raises(workspace._ScanDeadlineExceeded):
            workspace._scan_secret_pipe(
                proc.stdout,
                deadline=time.monotonic() + 0.05,
            )
    finally:
        proc.kill()
        proc.wait()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.stdout.close()

    assert time.monotonic() - started < 0.5


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="production APFS clonefile behavior",
)
def test_workspace_snapshot_clone_preserves_sparse_allocation(
    tmp_path: Path,
) -> None:
    """A low-cost huge sparse artifact cannot materialize onto system disk."""
    source = tmp_path / "source.bin"
    snapshot = tmp_path / "snapshot.bin"
    logical_size = 1024 * 1024 * 1024
    with source.open("wb") as handle:
        handle.truncate(logical_size)
    source_fd = os.open(source, os.O_RDONLY)
    try:
        error, fallback_used = workspace._clone_file_snapshot(
            source_fd,
            snapshot,
            fallback_budget=workspace._SNAPSHOT_FALLBACK_BUDGET_BYTES,
            deadline=time.monotonic() + 10,
        )
    finally:
        os.close(source_fd)

    assert error == ""
    assert fallback_used == 0
    assert snapshot.stat().st_size == logical_size
    assert snapshot.stat().st_blocks <= source.stat().st_blocks + 16


def test_workspace_snapshot_clamps_extents_to_pinned_fstat_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-place grow after fstat cannot widen the snapshot boundary."""
    source = tmp_path / "source.bin"
    snapshot = tmp_path / "snapshot.bin"
    source.write_bytes(b"safe")
    source_fd = os.open(source, os.O_RDWR)
    real_lseek = workspace.os.lseek
    grew = False

    def growing_lseek(fd: int, offset: int, whence: int) -> int:
        nonlocal grew
        if fd == source_fd and whence == os.SEEK_DATA:
            if not grew:
                os.ftruncate(
                    source_fd,
                    workspace._CHECKPOINT_SCAN_LOGICAL_BYTES + 1,
                )
                grew = True
            return 0
        if fd == source_fd and whence == os.SEEK_HOLE:
            return workspace._CHECKPOINT_SCAN_LOGICAL_BYTES + 1
        return real_lseek(fd, offset, whence)

    monkeypatch.setattr(workspace.os, "lseek", growing_lseek)
    try:
        error, _fallback_used = workspace._clone_file_snapshot(
            source_fd,
            snapshot,
            fallback_budget=workspace._SNAPSHOT_FALLBACK_BUDGET_BYTES,
            deadline=time.monotonic() + 10,
        )
    finally:
        os.close(source_fd)

    assert error == ""
    assert snapshot.read_bytes() == b"safe"


def test_workspace_oversized_artifact_stays_quarantined_without_using_capacity(
    tmp_path: Path,
) -> None:
    """Unscanned bytes stay intact but do not become execution capacity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(
        repo,
        config=_iso_cfg(max_total=1),
        task_binding={
            "task_id": "oversized-output",
            "claim_session_id": "oversized-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["oversized.bin"],
            "post_merge_actions": [],
        },
    )
    wt = Path(ws["path"])
    oversized = wt / "oversized.bin"
    with oversized.open("wb") as handle:
        handle.truncate(workspace._CHECKPOINT_SCAN_LOGICAL_BYTES + 1)

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert out["disposition"] == "remediation_opened"
    assert out["checkpoint"]["ok"] is False
    assert out["checkpoint"]["released"] is False
    assert (
        out["checkpoint"]["reason"]
        == "oversized_artifact_quarantine_required"
    )
    assert wt.exists()
    assert oversized.exists()
    terminal = [
        event
        for event in _ws_receipt_events(repo)
        if event["event"] == "released"
        and event["workspace"] == ws["name"]
    ]
    assert terminal == []

    replacement = _ws_allocate(
        repo,
        job_id="e" * 32,
        config=_iso_cfg(max_total=1),
    )
    assert replacement is not None
    assert any(
        event.get("event") == "allocation_advisory"
        and event.get("reason") == "artifact_backlog"
        for event in _ws_receipt_events(repo)
    )


def test_workspace_snapshot_rechecks_logical_cap_on_pinned_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file growing after pathname preflight is rejected before cloning."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    artifact = worktree / "growing.bin"
    artifact.write_bytes(b"x")
    real_snapshot = workspace._snapshot_workspace_paths

    def grow_before_open(*args, **kwargs):
        with artifact.open("r+b") as handle:
            handle.truncate(workspace._CHECKPOINT_SCAN_LOGICAL_BYTES + 1)
        return real_snapshot(*args, **kwargs)

    def clone_must_not_run(*_args, **_kwargs):
        raise AssertionError("oversized pinned FD reached clone")

    monkeypatch.setattr(
        workspace,
        "_snapshot_workspace_paths",
        grow_before_open,
    )
    monkeypatch.setattr(
        workspace,
        "_clone_file_snapshot",
        clone_must_not_run,
    )

    result = workspace._stage_dirty_checkpoint(
        worktree,
        ["growing.bin"],
    )

    assert result["ok"] is False
    assert result["reason"] == "oversized_artifact_quarantine_required"
    assert result["logical_bytes"] == (
        workspace._CHECKPOINT_SCAN_LOGICAL_BYTES + 1
    )


def test_workspace_release_rejects_branch_advance_after_checkpoint(
    tmp_path: Path,
) -> None:
    """A durable checkpoint is a CAS token, not permission to remove any HEAD."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    checkpoint = workspace._checkpoint_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
    )
    assert checkpoint["ok"] is True

    raced = wt / "storage" / "ops" / "raced.json"
    raced.parent.mkdir(parents=True)
    raced.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "storage/ops/raced.json"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "raced branch advance",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    released = workspace._release_checkpointed_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
        checkpoint=checkpoint,
        remediation={
            "incident_id": "inc_test",
            "task_id": "task_test",
            "created": True,
        },
    )

    assert released["released"] is False
    assert released["reason"] == "checkpoint_branch_advanced"
    assert wt.exists()
    assert not [
        event
        for event in _ws_receipt_events(repo)
        if event["event"] == "released" and event["workspace"] == ws["name"]
    ]


def test_workspace_release_ref_lock_blocks_commit_during_remove(
    tmp_path: Path,
) -> None:
    """The destructive window fences even Git writers that ignore our mutex."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    checkpoint = workspace._checkpoint_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
    )
    assert checkpoint["ok"] is True
    raced_commit_rc: list[int] = []

    def runner(args, **kwargs):
        if (
            "worktree" in args
            and "remove" in args
            and not raced_commit_rc
        ):
            raced = wt / "storage" / "ops" / "raced.json"
            raced.parent.mkdir(parents=True)
            raced.write_text("{}\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(wt), "add", "storage/ops/raced.json"],
                check=True,
            )
            attempted = subprocess.run(
                [
                    "git",
                    "-C",
                    str(wt),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "attempt branch advance under release lock",
                ],
                capture_output=True,
                text=True,
            )
            raced_commit_rc.append(attempted.returncode)
        return subprocess.run(args, **kwargs)

    released = workspace._release_checkpointed_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
        checkpoint=checkpoint,
        remediation={
            "incident_id": "inc_test",
            "task_id": "task_test",
            "created": True,
        },
        runner=runner,
    )

    assert raced_commit_rc and raced_commit_rc[0] != 0
    assert released["released"] is False
    assert released["reason"] == "checkpoint_remove_failed"
    assert wt.exists()
    branch_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ws["branch"]],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch_head == checkpoint["commit"]


def test_workspace_release_reclaims_dead_owned_ref_lock_after_restart(
    tmp_path: Path,
) -> None:
    """A crash-owned lock has durable identity and cannot exhaust capacity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    checkpoint = workspace._checkpoint_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
    )
    assert checkpoint["ok"] is True
    common = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (repo / common_path).resolve()
    lock_path = (
        common_path
        / "refs"
        / "heads"
        / f"{ws['branch']}.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "kind": workspace._REF_LOCK_OWNER_KIND,
                "pid": 2**31 - 1,
                "pid_started_wall": "Mon Jan  1 00:00:00 2001",
                "token": "crashed-owner",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    released = workspace._release_checkpointed_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
        checkpoint=checkpoint,
        remediation={
            "incident_id": "inc_test",
            "task_id": "task_test",
            "created": True,
        },
    )

    assert released["released"] is True
    assert not wt.exists()
    assert not lock_path.exists()


def test_workspace_release_never_reclaims_live_owned_ref_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An identity match stays fail-closed even when another pass wants space."""
    lock_path = tmp_path / "branch.lock"
    lock_path.write_text(
        json.dumps(
            {
                "kind": workspace._REF_LOCK_OWNER_KIND,
                "pid": 1234,
                "pid_started_wall": "live-start",
                "token": "live-owner",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workspace.procutil,
        "check_identity",
        lambda _pid, _started: workspace.procutil.IDENTITY_MATCH,
    )

    reclaimed = workspace._reclaim_stale_release_ref_lock(lock_path)

    assert reclaimed is False
    assert lock_path.exists()


def test_workspace_absent_release_race_is_never_recovered_as_success(
    tmp_path: Path,
) -> None:
    """A prior failed CAS outranks the older remediation binding on replay."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    checkpoint = workspace._checkpoint_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
    )
    assert checkpoint["ok"] is True
    assert workspace._append_receipt(
        repo,
        {
            "event": "remediation_bound",
            "workspace": ws["name"],
            "branch": ws["branch"],
            "checkpoint_commit": checkpoint["commit"],
            "incident_id": "inc_test",
            "task_id": "task_test",
            "reason": "test_checkpoint",
        },
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(wt)],
        check=True,
    )
    assert workspace._append_receipt(
        repo,
        {
            "event": "release_race_detected",
            "workspace": ws["name"],
            "branch": ws["branch"],
            "checkpoint_commit": checkpoint["commit"],
            "branch_head": "f" * 40,
            "reason": "post_release_branch_advanced",
        },
    )

    replay = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert replay["disposition"] == "reconcile_pending"
    assert replay["reason"] == "post_release_branch_advanced"
    assert replay["checkpoint"]["released"] is False
    assert not [
        event
        for event in _ws_receipt_events(repo)
        if event["event"] == "released" and event["workspace"] == ws["name"]
    ]


def test_workspace_absent_recovery_rechecks_bound_branch_head(
    tmp_path: Path,
) -> None:
    """A crash-window binding cannot release a subsequently moved branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    checkpoint = workspace._checkpoint_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
    )
    assert checkpoint["ok"] is True
    assert workspace._append_receipt(
        repo,
        {
            "event": "remediation_bound",
            "workspace": ws["name"],
            "branch": ws["branch"],
            "checkpoint_commit": checkpoint["commit"],
            "incident_id": "inc_test",
            "task_id": "task_test",
            "reason": "test_checkpoint",
        },
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(wt)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "branch", "-f", ws["branch"], "main"],
        check=True,
    )

    replay = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="failure",
        queue_path=_tmp_queue(tmp_path),
    )

    assert replay["disposition"] == "reconcile_pending"
    assert replay["reason"] == "post_release_branch_advanced"
    assert replay["checkpoint"]["released"] is False
    assert not [
        event
        for event in _ws_receipt_events(repo)
        if event["event"] == "released" and event["workspace"] == ws["name"]
    ]


def test_workspace_checkpoint_receipt_must_persist_before_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receipt write failure leaves the recoverable checkout registered."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    real_append = workspace._append_receipt

    def fail_checkpoint_receipt(root: Path, payload: dict) -> bool:
        if payload.get("event") == "checkpointed":
            return False
        return real_append(root, payload)

    monkeypatch.setattr(workspace, "_append_receipt", fail_checkpoint_receipt)

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=queue,
    )

    assert out["checkpoint"]["reason"] == "checkpoint_receipt_failed"
    assert out["checkpoint"]["released"] is False
    assert wt.exists()


def test_workspace_release_receipt_is_recovered_without_duplicate_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after remove is closed from the pre-cleanup task binding."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    real_append = workspace._append_receipt
    fail_once = {"armed": True}

    def fail_first_release(root: Path, payload: dict) -> bool:
        if payload.get("event") == "released" and fail_once["armed"]:
            fail_once["armed"] = False
            return False
        return real_append(root, payload)

    monkeypatch.setattr(workspace, "_append_receipt", fail_first_release)
    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=queue,
    )

    assert first["checkpoint"]["reason"] == "release_receipt_failed"
    assert first["checkpoint"]["released"] is False
    assert not wt.exists()

    second = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=queue,
    )

    assert second["disposition"] == "remediation_opened"
    assert second["checkpoint"]["released"] is True
    assert second["replayed"] is True
    assert len(json.loads(queue.read_text(encoding="utf-8"))) == 1
    assert [
        event["event"] for event in _ws_receipt_events(repo)
        if event["event"] == "released"
    ] == ["released"]


def test_workspace_absent_recovery_locks_ref_through_release_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recovered release fsync and branch HEAD form one native-ref CAS."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    checkpoint = workspace._checkpoint_workspace(
        repo_root=repo,
        workspace=ws,
        reason="test_checkpoint",
    )
    assert checkpoint["ok"] is True
    assert workspace._append_receipt(
        repo,
        {
            "event": "remediation_bound",
            "workspace": ws["name"],
            "branch": ws["branch"],
            "checkpoint_commit": checkpoint["commit"],
            "incident_id": "inc_test",
            "task_id": "task_test",
            "reason": "test_checkpoint",
        },
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", str(wt)],
        check=True,
    )
    real_append = workspace._append_receipt
    raced_rc: list[int] = []

    def race_before_release_receipt(root: Path, payload: dict) -> bool:
        if payload.get("event") == "released" and not raced_rc:
            attempted = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "branch",
                    "-f",
                    ws["branch"],
                    "main",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            raced_rc.append(attempted.returncode)
        return real_append(root, payload)

    monkeypatch.setattr(
        workspace,
        "_append_receipt",
        race_before_release_receipt,
    )

    replay = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=_tmp_queue(tmp_path),
    )

    assert replay["checkpoint"]["released"] is True
    assert raced_rc and raced_rc[0] != 0
    branch_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ws["branch"]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert branch_head == checkpoint["commit"]


def test_workspace_branch_advance_requires_new_remediation_binding(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")
    fail_remove_once = {"armed": True}

    def runner(args, **kwargs):
        if (
            fail_remove_once["armed"]
            and "worktree" in args
            and "remove" in args
        ):
            fail_remove_once["armed"] = False
            return subprocess.CompletedProcess(args, 1, "", "injected remove failure")
        return subprocess.run(args, **kwargs)

    first = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=queue,
        runner=runner,
    )
    assert first["checkpoint"]["reason"] == "checkpoint_remove_failed"
    first_sha = first["checkpoint"]["commit"]
    assert wt.exists()

    (wt / "recoverable.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=queue,
    )

    second_sha = second["checkpoint"]["commit"]
    assert second_sha != first_sha
    bindings = [
        event for event in _ws_receipt_events(repo)
        if event["event"] == "remediation_bound"
    ]
    assert [event["checkpoint_commit"] for event in bindings] == [
        first_sha,
        second_sha,
    ]
    assert second["checkpoint"]["released"] is True


def test_workspace_adjudication_exit_is_not_blocked_by_auto_remediation_cap(
    tmp_path: Path,
) -> None:
    """The global repair cap may stop repair-task floods, not the aggregate
    main-thread adjudication that gives an unmergeable branch a human exit.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    now = datetime.now(timezone.utc).isoformat()
    queue.write_text(
        json.dumps(
            [
                {
                    "id": f"alert_auto_{index}",
                    "title": f"repair {index}",
                    "description": "automatic repair",
                    "task_type": "platform_ops",
                    "priority": 2,
                    "status": "pending",
                    "source": "incident_router",
                    "incident_id": f"inc_auto_{index}",
                    "created_at": now,
                }
                for index in range(8)
            ]
        ),
        encoding="utf-8",
    )
    ws = _ws_allocate(repo)
    (Path(ws["path"]) / "needs_owner.py").write_text("VALUE = 1\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=queue,
    )

    assert out["remediation"]["created"] is True
    tasks = json.loads(queue.read_text(encoding="utf-8"))
    adjudications = [
        task for task in tasks if task.get("incident_id") == out["remediation"]["incident_id"]
    ]
    assert len(adjudications) == 1
    assert adjudications[0]["source"] == "incident_adjudication"
    assert adjudications[0]["dispatch_lane"] == "main_thread"


def test_workspace_keeps_live_checkout_when_remediation_exit_is_not_durable(
    tmp_path: Path,
) -> None:
    """Never release the only discoverable copy when the queue exit failed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    invalid_queue = tmp_path / "queue-is-a-directory"
    invalid_queue.mkdir()
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "only-copy.py").write_text("VALUE = 1\n", encoding="utf-8")

    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="killed_timeout",
        queue_path=invalid_queue,
    )

    assert out["remediation"]["created"] is False
    assert out["remediation"]["error"]
    assert out["checkpoint"]["ok"] is True
    assert out["checkpoint"]["released"] is False
    assert out["checkpoint"]["reason"] == "remediation_not_durable"
    assert out["checkpoint"]["commit"]
    assert wt.exists()
    assert (wt / "only-copy.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_workspace_finalize_unclean_worker_never_merges(tmp_path: Path) -> None:
    """A hang/failure fire's bytes are unverified -- they go to remediation,
    never through the gate to main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    (Path(ws["path"]) / "partial.py").write_text("x = 1\n", encoding="utf-8")
    called = {"gate": 0, "merge": 0}

    def spy_gate(**kwargs):  # pragma: no cover - must not run
        called["gate"] += 1
        return {"verdict": "green", "rc": 0, "targets": [], "duration_s": 0}

    def spy_merge(**kwargs):  # pragma: no cover - must not run
        called["merge"] += 1
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="killed_timeout",
        queue_path=queue, gate_fn=spy_gate, merge_fn=spy_merge,
    )
    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "worker_killed_timeout"
    assert called == {"gate": 0, "merge": 0}
    assert out["checkpoint"]["ok"] is True
    assert not Path(ws["path"]).exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show", f"{ws['branch']}:partial.py"],
        check=True, capture_output=True, text=True,
    ).stdout == "x = 1\n"
    tasks = json.loads(queue.read_text(encoding="utf-8"))
    assert len(tasks) == 1 and tasks[0]["status"] == "pending"


def test_workspace_finalize_merge_failure_opens_remediation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    wt = Path(ws["path"])
    (wt / "change.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "change.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"], check=True,
    )
    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success", queue_path=queue,
        gate_fn=lambda **kw: {"verdict": "green", "rc": 0, "targets": [],
                              "duration_s": 0.0, "output_tail": ""},
        merge_fn=lambda **kw: {"ok": False, "rc": 1, "reason": "merge_failed",
                               "output_tail": "[ABORT] conflict"},
    )
    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "merge_failed"
    assert out["checkpoint"]["ok"] is True
    assert not Path(ws["path"]).exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show", f"{ws['branch']}:change.py"],
        check=True, capture_output=True, text=True,
    ).stdout == "x = 1\n"
    assert len(json.loads(queue.read_text(encoding="utf-8"))) == 1


def test_workspace_finalize_unregistered_dir_untouched(tmp_path: Path) -> None:
    """A directory squatting on the namespace is not ours -- never removed,
    never merged (independent-repo impersonation defence, error_log §C)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    fake = repo / ".claude" / "worktrees" / "dispatch-slot-1-deadbeef"
    fake.mkdir(parents=True)
    (fake / "loot.txt").write_text("x", encoding="utf-8")
    out = workspace.finalize_workspace(
        repo_root=repo,
        workspace={"name": fake.name, "path": str(fake),
                   "branch": "worktree-dispatch-slot-1-deadbeef", "base_sha": ""},
        worker_outcome="success", queue_path=_tmp_queue(tmp_path),
    )
    assert out["disposition"] == "unregistered"
    assert (fake / "loot.txt").exists()


def test_workspace_sweep_closes_true_orphans_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    protected_ws = _ws_allocate(repo, job_id="b" * 32)
    orphan_ws = _ws_allocate(repo, job_id="c" * 32, slot="slot-2")
    assert protected_ws is not None and orphan_ws is not None
    _bind_drained_workspace_custody(
        monkeypatch,
        repo=repo,
        workspace_receipt=orphan_ws,
        job_id="c" * 32,
    )
    results = workspace.sweep_orphan_workspaces(
        repo_root=repo, protected_job_ids=["b" * 32], queue_path=queue,
    )
    # orphan (empty) removed; protected workspace untouched
    assert [r["disposition"] for r in results] == ["empty_removed"]
    assert not Path(orphan_ws["path"]).exists()
    assert Path(protected_ws["path"]).exists()
    events = legacy_retirement_events.load_verified_orphan_work_events(repo)
    assert [event["workspace"] for event in events] == [orphan_ws["name"]]


def test_workspace_sweep_uses_cutover_drain_for_pre_custody_orphan(
    tmp_path: Path,
) -> None:
    """A proven global cutover drain closes workspaces created before custody.

    These workspaces cannot have a per-job custody receipt because the receipt
    contract did not exist when their provider started.  The installer drains
    the complete legacy supervisor coalition, then durably binds that proof to
    the exact pre-cutover workspace names so they do not consume ``max_total``
    forever.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    orphan_ws = workspace.allocate_workspace(
        repo_root=repo,
        slot_id="slot-1",
        job_id="9" * 32,
        config=_iso_cfg(mode="pilot", max_total=1),
        task_binding=None,
    )
    assert orphan_ws is not None
    generations = workspace.active_allocated_workspace_generations(repo)
    assert workspace.record_legacy_workspace_producer_drain(
        repo,
        workspace_generations=generations,
        cutover_request_id="cutover-proof-1",
        cutover_completed_at="2099-07-29T00:00:00+00:00",
        complete_coalition_drained=True,
        release_commit="b" * 40,
    )
    assert workspace.legacy_workspace_producer_drain_confirmed(
        repo,
        workspace_name=orphan_ws["name"],
        job_id="9" * 32,
    )
    assert not workspace.legacy_workspace_producer_drain_confirmed(
        repo,
        workspace_name=orphan_ws["name"],
        job_id="9" * 31 + "8",
    )

    results = workspace.sweep_orphan_workspaces(
        repo_root=repo,
        protected_job_ids=[],
        queue_path=queue,
    )

    assert [result["disposition"] for result in results] == ["empty_removed"]
    assert not Path(orphan_ws["path"]).exists()
    assert _ws_allocate(
        repo,
        job_id="8" * 32,
        config=_iso_cfg(max_total=1),
    ) is not None


def test_installer_backfills_from_exact_prior_cutover_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import install_dispatch_supervisor_release as installer
    from scripts.dispatch_supervisor import custody_receipt

    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo, job_id="7" * 32)
    assert ws is not None
    ledger = repo / custody_receipt.RECEIPTS_RELPATH
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.touch()
    run_root = tmp_path / "run"
    receipts = run_root / "cutover_receipts"
    receipts.mkdir(parents=True)
    paired = {
        "schema_version": 1,
        "request_id": "c" * 64,
        "release_sha256": "a" * 64,
        "release_commit": "b" * 40,
        "completed_at": "2099-07-29T00:00:00+00:00",
    }
    monkeypatch.setattr(
        installer,
        "_release_has_verified_coalition_drain",
        lambda *_args, **_kwargs: True,
    )
    (receipts / "in_progress.json").write_text(
        json.dumps({**paired, "status": "completed_verified"}),
        encoding="utf-8",
    )
    (receipts / "latest.json").write_text(
        json.dumps({**paired, "status": "completed"}),
        encoding="utf-8",
    )

    migrated = installer._backfill_pre_custody_workspace_drain(
        repo_root=repo,
        request_root=run_root,
    )

    assert migrated == 1
    assert workspace.legacy_workspace_producer_drain_confirmed(
        repo,
        workspace_name=ws["name"],
        job_id="7" * 32,
    )
    assert installer._backfill_pre_custody_workspace_drain(
        repo_root=repo,
        request_root=run_root,
    ) == 0


def test_workspace_sweep_fails_closed_when_orphan_evidence_cannot_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    orphan_ws = _ws_allocate(repo, job_id="d" * 32)
    assert orphan_ws is not None
    monkeypatch.setattr(
        legacy_retirement_events,
        "append_orphan_work_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LegacyRetirementInputError("injected append failure")
        ),
    )

    with pytest.raises(LegacyRetirementInputError, match="injected append failure"):
        workspace.sweep_orphan_workspaces(
            repo_root=repo,
            protected_job_ids=[],
            queue_path=_tmp_queue(tmp_path),
        )

    assert Path(orphan_ws["path"]).exists()


def test_workspace_sweep_restart_does_not_double_count_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    orphan_ws = _ws_allocate(repo, job_id="e" * 32)
    assert orphan_ws is not None
    _bind_drained_workspace_custody(
        monkeypatch,
        repo=repo,
        workspace_receipt=orphan_ws,
        job_id="e" * 32,
    )
    real_finalize = workspace.finalize_workspace
    calls = 0

    def crash_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected crash after evidence append")
        return real_finalize(**kwargs)

    monkeypatch.setattr(workspace, "finalize_workspace", crash_once)
    with pytest.raises(RuntimeError, match="injected crash"):
        workspace.sweep_orphan_workspaces(
            repo_root=repo,
            protected_job_ids=[],
            queue_path=_tmp_queue(tmp_path),
        )
    assert len(legacy_retirement_events.load_verified_orphan_work_events(repo)) == 1

    results = workspace.sweep_orphan_workspaces(
        repo_root=repo,
        protected_job_ids=[],
        queue_path=_tmp_queue(tmp_path),
    )

    assert [result["disposition"] for result in results] == ["empty_removed"]
    assert len(legacy_retirement_events.load_verified_orphan_work_events(repo)) == 1


def test_workspace_sweep_ignores_unowned_dispatch_shaped_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    path = repo / ".claude" / "worktrees" / "dispatch-slot-3-feedface"
    path.parent.mkdir(parents=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "-b",
            "worktree-dispatch-slot-3-feedface",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    results = workspace.sweep_orphan_workspaces(
        repo_root=repo,
        protected_job_ids=[],
        queue_path=_tmp_queue(tmp_path),
    )

    assert results == []
    assert path.exists()
    assert legacy_retirement_events.load_verified_orphan_work_events(repo) == []


def test_workspace_sweep_ignores_durable_remediation_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    orphan_ws = _ws_allocate(repo, job_id="a" * 32)
    assert orphan_ws is not None
    producer_custody = _bind_drained_workspace_custody(
        monkeypatch,
        repo=repo,
        workspace_receipt=orphan_ws,
        job_id="a" * 32,
    )
    wt = Path(orphan_ws["path"])
    (wt / "recoverable.py").write_text("VALUE = 1\n", encoding="utf-8")

    def fail_remove(args, **kwargs):
        if "worktree" in args and "remove" in args:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "injected remediation release failure",
            )
        kwargs["check"] = False
        return subprocess.run(args, **kwargs)

    outcome = workspace.finalize_workspace(
        repo_root=repo,
        workspace=orphan_ws,
        worker_outcome="killed_timeout",
        job_id="a" * 8,
        producer_custody=producer_custody,
        queue_path=queue,
        runner=fail_remove,
    )
    assert outcome["checkpoint"]["reason"] == "checkpoint_remove_failed"
    assert wt.exists()

    results = workspace.sweep_orphan_workspaces(
        repo_root=repo,
        protected_job_ids=[],
        queue_path=queue,
    )

    assert results == []
    assert wt.exists()
    assert legacy_retirement_events.load_verified_orphan_work_events(repo) == []


def test_workspace_sweep_records_unreadable_branch_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    orphan_ws = _ws_allocate(repo, job_id="f" * 32)
    assert orphan_ws is not None
    _bind_drained_workspace_custody(
        monkeypatch,
        repo=repo,
        workspace_receipt=orphan_ws,
        job_id="f" * 32,
    )

    def fail_branch_probe(args, **kwargs):
        if "rev-parse" in args and "--abbrev-ref" in args:
            return subprocess.CompletedProcess(args, 1, "", "injected branch failure")
        kwargs["check"] = False
        return subprocess.run(args, **kwargs)

    with pytest.raises(
        LegacyRetirementInputError,
        match="branch is unreadable",
    ):
        workspace.sweep_orphan_workspaces(
            repo_root=repo,
            protected_job_ids=[],
            queue_path=_tmp_queue(tmp_path),
            runner=fail_branch_probe,
        )

    assert Path(orphan_ws["path"]).exists()
    events = legacy_retirement_events.load_verified_orphan_work_events(repo)
    assert len(events) == 1
    assert events[0]["workspace"] == orphan_ws["name"]
    assert events[0]["branch"] == "unresolved"

    results = workspace.sweep_orphan_workspaces(
        repo_root=repo,
        protected_job_ids=[],
        queue_path=_tmp_queue(tmp_path),
    )
    events = legacy_retirement_events.load_verified_orphan_work_events(repo)

    assert len(results) == 1
    assert not Path(orphan_ws["path"]).exists()
    assert [event["branch"] for event in events] == [
        "unresolved",
        orphan_ws["branch"],
    ]


def test_workspace_isolation_config_defaults_off(tmp_path: Path) -> None:
    missing = workspace.load_isolation_config(schedules_path=tmp_path / "nope.json")
    assert missing["mode"] == "off"
    no_daemon = tmp_path / "sched.json"
    no_daemon.write_text(json.dumps({"cron_jobs": []}), encoding="utf-8")
    assert workspace.load_isolation_config(schedules_path=no_daemon)["mode"] == "off"
    pilot = tmp_path / "sched2.json"
    pilot.write_text(json.dumps({"daemons": [{
        "id": "volpred-dispatch-supervisor",
        "writer_isolation": {"mode": "pilot", "lanes": ["platform_ops"],
                             "max_active": 2, "max_total": 3,
                             "disk_floor_gib": 5},
    }]}), encoding="utf-8")
    cfg = workspace.load_isolation_config(schedules_path=pilot)
    assert cfg == {"mode": "pilot", "lanes": ["platform_ops"],
                   "max_active": 2, "max_total": 3, "disk_floor_gib": 5.0}


def test_workspace_isolation_config_accepts_enforce_mode(tmp_path: Path) -> None:
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({"daemons": [{
        "id": "volpred-dispatch-supervisor",
        "writer_isolation": {"mode": "enforce", "lanes": ["platform_ops"]},
    }]}), encoding="utf-8")

    assert workspace.load_isolation_config(schedules_path=schedules)["mode"] == "enforce"


@pytest.mark.parametrize("payload", [None, "{broken", '{"daemons": []}'])
def test_workspace_isolation_required_fence_fails_closed_on_bad_config(
    tmp_path: Path, monkeypatch, payload: str | None,
) -> None:
    schedules = tmp_path / "sched.json"
    if payload is not None:
        schedules.write_text(payload, encoding="utf-8")
    monkeypatch.setenv("VOLPRED_WRITER_ISOLATION_REQUIRED", "1")

    config = workspace.load_isolation_config(schedules_path=schedules)

    assert config["mode"] == "enforce"


def test_workspace_allocation_refused_on_canonical_checkout_under_test_gate() -> None:
    """Class gate (project_canonical_write_test_leak_gate): a pytest process --
    conftest arms VOLPRED_NO_CANONICAL_WRITE=1 -- must never grow worktrees on
    the real checkout through this module."""
    assert os.environ.get("VOLPRED_NO_CANONICAL_WRITE") == "1"
    assert workspace.allocate_workspace(
        repo_root=workspace.ROOT, slot_id="slot-1", job_id="f" * 32,
        config=_iso_cfg(),
    ) is None
    assert workspace.sweep_orphan_workspaces(
        repo_root=workspace.ROOT, protected_job_ids=[],
    ) == []


def test_scheduler_fire_attaches_workspace_and_finalizes(tmp_path: Path, monkeypatch) -> None:
    """Fire-path integration: pilot config -> allocate -> receipt on the state
    job + prompt section -> finalize after the worker -> workspace receipt rides
    the completions ring (ownership audit trail)."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{"id": "volpred-dispatch-supervisor", "max_slots": 2,
                     "writer_isolation": {"mode": "pilot", "lanes": ["platform_ops"]}}],
    }), encoding="utf-8")
    fake_ws = {"name": "dispatch-slot-1-fixed", "path": str(tmp_path / "ws"),
               "branch": "worktree-dispatch-slot-1-fixed", "base_sha": "abc",
               "lanes": ["platform_ops"], "created_at": "2026-07-20T00:00:00+00:00",
               "setup_s": 1.0}
    allocated: list[dict] = []
    finalized: list[dict] = []
    monkeypatch.setattr(
        scheduler, "_preassign_mutating_task",
        lambda **_kw: _assigned_mutating_task(),
    )
    monkeypatch.setattr(
        scheduler.isolation, "prepare",
        lambda **_kw: _prepared_isolation(tmp_path),
    )
    monkeypatch.setattr(
        scheduler, "_settle_mutating_task",
        lambda **_kw: {"ok": True, "status": "pending"},
    )
    monkeypatch.setattr(scheduler.workspace_mod, "sweep_orphan_workspaces",
                        lambda **kw: [])
    monkeypatch.setattr(
        scheduler.workspace_mod, "allocate_workspace",
        lambda **kw: allocated.append(kw) or {
            **fake_ws,
            **kw["task_binding"],
            "task_title": kw["task_binding"]["title"],
            "task_description": kw["task_binding"]["description"],
        },
    )
    monkeypatch.setattr(
        scheduler.workspace_mod, "finalize_workspace",
        lambda **kw: finalized.append(kw) or {"disposition": "empty_removed"},
    )
    received: list[dict] = []

    def fake_run_worker(**kwargs):
        received.append(kwargs)
        # the worker owns the normal completion close, like production
        state.record_completion(
            job_id=kwargs["job_id"], exit_code=0, outcome="success",
            final_model=worker.OPUS_MODEL, path=kwargs["state_path"],
        )
        return worker.WorkerResult(
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            attempts=1, duration_s=1.0, log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "worker.log", dry_run=False,
        repo_root=tmp_path, schedules_path=schedules,
    ))

    assert result["action"] == "fired"
    assert result["workspace"] == {"disposition": "empty_removed"}
    # allocation happened once, machine-side, before the worker
    assert len(allocated) == 1
    # prompt carries the binding instructions
    prompt_text = received[0]["prompt_text"]
    assert "Producer-scoped workspace" in prompt_text
    assert fake_ws["path"] in prompt_text
    assert fake_ws["branch"] in prompt_text
    assert "不得自行 merge" in prompt_text
    # finalize ran with the worker's outcome
    assert len(finalized) == 1
    assert finalized[0]["worker_outcome"] == "success"
    assert finalized[0]["workspace"]["name"] == "dispatch-slot-1-fixed"
    # ownership audit trail: the completion entry carries the workspace receipt
    snap = state.read_state(state_path)
    assert snap["completions"][-1]["workspace"]["name"] == "dispatch-slot-1-fixed"
    assert snap["completions"][-1]["workspace"]["branch"] == fake_ws["branch"]


def test_task_settlement_reconciler_retries_after_merge_response_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state_path = _tmp_state(tmp_path)
    ws = {
        "name": "dispatch-slot-1-settle",
        "path": str(repo / ".claude/worktrees/dispatch-slot-1-settle"),
        "branch": "worktree-dispatch-slot-1-settle",
        "base_sha": "abc",
        "task_id": "task-settle",
        "claim_session_id": "claim-settle",
    }
    assert workspace.ensure_task_settlement_pending(
        repo, workspace=ws, job_id="job-settle", worker_outcome="success"
    )
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "finalize_workspace",
        lambda **_kw: {"disposition": "merged", "main_sha": "landed"},
    )
    settlements = iter([
        {"ok": False, "reason": "simulated_response_loss"},
        {"ok": True, "status": "succeeded"},
    ])
    calls: list[dict] = []

    def settle(**kwargs):
        calls.append(kwargs)
        return next(settlements)

    monkeypatch.setattr(scheduler, "_settle_mutating_task", settle)

    first = scheduler.reconcile_task_settlements(
        repo_root=repo, state_path=state_path
    )
    assert first[0]["settlement_completed"] is False
    assert len(workspace.pending_task_settlements(repo)) == 1

    second = scheduler.reconcile_task_settlements(
        repo_root=repo, state_path=state_path
    )
    assert second[0]["settlement_completed"] is True
    assert workspace.pending_task_settlements(repo) == []
    assert scheduler.reconcile_task_settlements(
        repo_root=repo, state_path=state_path
    ) == []
    assert len(calls) == 2


def test_task_settlement_reconciler_recovers_completion_before_finalizer(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state_path = _tmp_state(tmp_path)
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/completed.log",
        path=state_path,
    )
    ws = {
        "name": "dispatch-slot-1-completed",
        "path": str(repo / ".claude/worktrees/dispatch-slot-1-completed"),
        "branch": "worktree-dispatch-slot-1-completed",
        "base_sha": "abc",
        "task_id": "task-completed",
        "claim_session_id": "claim-completed",
    }
    assert state.attach_workspace(
        job_id=lease.job_id, workspace=ws, path=state_path
    )
    state.record_completion(
        job_id=lease.job_id,
        exit_code=0,
        outcome="success",
        final_model="opus",
        path=state_path,
    )
    finalized: list[dict] = []
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "finalize_workspace",
        lambda **kwargs: finalized.append(kwargs)
        or {"disposition": "empty_removed"},
    )
    monkeypatch.setattr(
        scheduler,
        "_settle_mutating_task",
        lambda **_kw: {"ok": True, "status": "pending"},
    )

    result = scheduler.reconcile_task_settlements(
        repo_root=repo, state_path=state_path
    )

    assert result[0]["settlement_completed"] is True
    assert finalized[0]["job_id"] == lease.job_id
    assert workspace.pending_task_settlements(repo) == []


def test_task_settlement_reconciler_uses_cutover_workspace_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    state_path = _tmp_state(tmp_path)
    job_id = "abcd1234" * 4
    ws = _ws_allocate(
        repo,
        job_id=job_id,
        task_binding={
            "task_id": "task-migrated",
            "claim_session_id": "claim-migrated",
            "write_intent": "repo_patch",
            "declared_output_paths": ["scripts"],
            "post_merge_actions": [],
        },
    )
    assert ws is not None
    ws = {
        **ws,
        "task_id": "task-migrated",
        "claim_session_id": "claim-migrated",
    }
    assert workspace.ensure_task_settlement_pending(
        repo,
        workspace=ws,
        job_id=job_id,
        worker_outcome="success",
    )
    assert workspace.record_legacy_workspace_producer_drain(
        repo,
        workspace_generations=workspace.active_allocated_workspace_generations(
            repo
        ),
        cutover_request_id="cutover-proof-2",
        cutover_completed_at="2099-07-29T00:00:00+00:00",
        complete_coalition_drained=True,
        release_commit="c" * 40,
    )
    finalized: list[dict] = []
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "finalize_workspace",
        lambda **kwargs: finalized.append(kwargs)
        or {"disposition": "empty_removed"},
    )
    monkeypatch.setattr(
        scheduler,
        "_settle_mutating_task",
        lambda **_kwargs: {"ok": True, "status": "succeeded"},
    )

    result = scheduler.reconcile_task_settlements(
        repo_root=repo,
        state_path=state_path,
    )

    assert result[0]["settlement_completed"] is True
    assert finalized[0]["producer_drain_confirmed"] is True


def test_restart_finalizer_uses_generation_bound_cutover_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = "abcd1234" * 4
    finalizations: list[dict] = []
    confirmations: list[dict] = []
    monkeypatch.setattr(supervisor, "ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor.workspace_mod,
        "legacy_workspace_producer_drain_confirmed",
        lambda repo_root, **kwargs: confirmations.append(
            {"repo_root": repo_root, **kwargs}
        )
        or True,
    )
    monkeypatch.setattr(
        supervisor.workspace_mod,
        "finalize_workspace",
        lambda **kwargs: finalizations.append(kwargs)
        or {"disposition": "empty_removed"},
    )

    terminal = supervisor._finalize_restart_workspace(
        {
            "job_id": job_id,
            "workspace": {
                "name": "dispatch-slot-1-abcd1234",
                "path": str(tmp_path / "workspace"),
                "branch": "worktree-dispatch-slot-1-abcd1234",
            },
        },
        outcome="orphaned",
    )

    assert terminal is True
    assert confirmations == [{
        "repo_root": tmp_path,
        "workspace_name": "dispatch-slot-1-abcd1234",
        "job_id": job_id,
    }]
    assert finalizations[0]["producer_drain_confirmed"] is True


def test_admission_outbox_requeues_task_after_preassign_crash(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    commands: list[list[str]] = []

    def command(*, repo_root, args):
        commands.append(args)
        if args[0] == "dispatch-pending":
            return {
                "ok": True,
                "pending": [{
                    "task_id": "task-preassign-crash",
                    "claim_session_id": "claim-preassign-crash",
                    "dispatch_job_id": "dead-job",
                    "intent": {"phase": "admission"},
                }],
            }
        assert args[0] == "dispatch-settle"
        return {"ok": True, "status": "pending"}

    monkeypatch.setattr(scheduler, "_task_pool_command", command)

    result = scheduler.reconcile_admission_settlements(
        repo_root=tmp_path, state_path=state_path
    )

    assert result == [{"ok": True, "status": "pending"}]
    assert commands[1][0] == "dispatch-settle"
    assert commands[1][commands[1].index("--job-id") + 1] == "dead-job"
    assert commands[1][commands[1].index("--disposition") + 1] == "retry"


def test_task_pool_cli_failure_preserves_subprocess_stderr(
    tmp_path: Path, monkeypatch,
) -> None:
    """A control-plane crash must remain diagnosable at the scheduler boundary."""

    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["python", "task_pool_claim.py"],
            returncode=1,
            stdout="",
            stderr="InvalidUnblockGate: issue42 lifecycle shape",
        ),
    )

    result = scheduler._task_pool_command(
        repo_root=tmp_path,
        args=["dispatch-pending", "--limit", "20"],
    )

    assert result == {
        "ok": False,
        "reason": "task_pool_cli_failed",
        "rc": 1,
        "detail": "InvalidUnblockGate: issue42 lifecycle shape",
    }


def test_task_pool_structured_failure_still_preserves_subprocess_stderr(
    tmp_path: Path, monkeypatch,
) -> None:
    """A JSON error payload must not make the process traceback disappear."""

    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["python", "task_pool_claim.py"],
            returncode=2,
            stdout='{"ok": false, "reason": "invalid_state"}',
            stderr="traceback details from canonical child",
        ),
    )

    result = scheduler._task_pool_command(
        repo_root=tmp_path,
        args=["dispatch-pending", "--limit", "20"],
    )

    assert result == {
        "ok": False,
        "reason": "invalid_state",
        "rc": 2,
        "detail": "traceback details from canonical child",
    }


def test_task_pool_cli_child_scrubs_all_supervisor_private_environment(
    tmp_path: Path, monkeypatch,
) -> None:
    captured: dict[str, str] = {}
    for key in (
        "VOLPRED_SUPERVISOR_RELEASE_ID",
        "VOLPRED_SUPERVISOR_BOOTSTRAP_SHA256",
        "VOLPRED_SUPERVISOR_FUTURE_MARKER",
        "VOLPRED_DEFERRED_RELOAD_ROOT",
        "VOLPRED_DEFERRED_RELOAD_FUTURE_MARKER",
        "VOLPRED_CANONICAL_REPO_ROOT",
    ):
        monkeypatch.setenv(key, f"private-{key.lower()}")
    monkeypatch.setenv("VOLPRED_ACTOR", "dispatch-supervisor")

    def run(*_args, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args=["python", "task_pool_claim.py"],
            returncode=0,
            stdout='{"ok": false, "reason": "no_work"}',
            stderr="",
        )

    monkeypatch.setattr(scheduler.subprocess, "run", run)

    result = scheduler._task_pool_command(
        repo_root=tmp_path,
        args=["dispatch-pending", "--limit", "1"],
    )

    assert result == {"ok": False, "reason": "no_work"}
    assert captured["VOLPRED_ACTOR"] == "dispatch-supervisor"
    assert not any(
        key.startswith(("VOLPRED_SUPERVISOR_", "VOLPRED_DEFERRED_RELOAD_"))
        for key in captured
    )
    assert "VOLPRED_CANONICAL_REPO_ROOT" not in captured


def test_task_pool_cli_child_does_not_inherit_release_identity(
    monkeypatch,
) -> None:
    """Canonical child CLIs must not masquerade as the immutable supervisor."""

    for key in (
        "VOLPRED_SUPERVISOR_RELEASE_ID",
        "VOLPRED_SUPERVISOR_RELEASE_SHA256",
        "VOLPRED_SUPERVISOR_RELEASE_COMMIT",
        "VOLPRED_SUPERVISOR_RELEASE_ARCHIVE",
        "VOLPRED_CANONICAL_REPO_ROOT",
    ):
        monkeypatch.setenv(key, f"test-{key.lower()}")

    repo_root = Path(__file__).resolve().parents[1]
    result = scheduler._task_pool_command(
        repo_root=repo_root,
        args=["dispatch-pending", "--limit", "1"],
    )

    assert result["ok"] is False
    assert result["reason"] == "supervisor_capability_required"
    assert result["rc"] == 1
    assert (
        "supervisor_capability_required" in result["detail"]
        or "supervisor capability proof unavailable" in result["detail"]
    )
    assert "ModuleNotFoundError" not in result["detail"]


def test_admission_outbox_waits_for_live_job_or_workspace_owner(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/live.log",
        path=state_path,
    )
    rows = [
        {
            "task_id": "task-live",
            "claim_session_id": "claim-live",
            "dispatch_job_id": lease.job_id,
        },
        {
            "task_id": "task-workspace",
            "claim_session_id": "claim-workspace",
            "dispatch_job_id": "completed-job",
        },
    ]
    monkeypatch.setattr(
        scheduler,
        "_task_pool_command",
        lambda **_kw: {"ok": True, "pending": rows},
    )
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "task_settlement_ownership",
        lambda *_args, **_kw: {"ok": True, "pending": [{
            "task_id": "task-workspace",
            "claim_session_id": "claim-workspace",
        }]},
    )

    assert scheduler.reconcile_admission_settlements(
        repo_root=tmp_path, state_path=state_path
    ) == []


def test_admission_ownership_is_unbounded_and_observation_fail_closed(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    target = {
        "task_id": "task-24",
        "claim_session_id": "claim-24",
        "dispatch_job_id": "dead-job",
    }
    monkeypatch.setattr(
        scheduler,
        "_task_pool_command",
        lambda **_kw: {"ok": True, "pending": [target]},
    )
    pending = [
        {
            "task_id": f"task-{index}",
            "claim_session_id": f"claim-{index}",
        }
        for index in range(25)
    ]
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "task_settlement_ownership",
        lambda _repo: {"ok": True, "pending": pending},
    )
    assert scheduler.reconcile_admission_settlements(
        repo_root=tmp_path, state_path=state_path, limit=20
    ) == []

    monkeypatch.setattr(
        scheduler.workspace_mod,
        "task_settlement_ownership",
        lambda _repo: {
            "ok": False,
            "reason": "receipt_observation_unavailable",
        },
    )
    assert scheduler.reconcile_admission_settlements(
        repo_root=tmp_path, state_path=state_path
    ) == [{
        "ok": False,
        "reason": "receipt_observation_unavailable",
    }]


def test_completion_receipt_failure_blocks_admission_reconciliation(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/completion.log",
        path=state_path,
    )
    ws = {
        "name": "dispatch-completion-failure",
        "path": str(tmp_path / "ws"),
        "branch": "worktree-completion-failure",
        "base_sha": "abc",
        "task_id": "task-completion",
        "claim_session_id": "claim-completion",
    }
    assert state.attach_workspace(
        job_id=lease.job_id, workspace=ws, path=state_path
    )
    state.record_completion(
        job_id=lease.job_id,
        exit_code=0,
        outcome="success",
        final_model="opus",
        path=state_path,
    )
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "ensure_task_settlement_pending",
        lambda *_args, **_kwargs: False,
    )

    assert scheduler.reconcile_task_settlements(
        repo_root=tmp_path, state_path=state_path
    ) == [{
        "ok": False,
        "reason": "completion_settlement_intent_not_durable",
    }]


def test_scheduler_non_mutating_fire_does_not_allocate_workspace(
    tmp_path: Path, monkeypatch,
) -> None:
    """A fire with no preassigned repo patch remains on its non-mutating lane."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{"id": "volpred-dispatch-supervisor", "max_slots": 2,
                     "writer_isolation": {"mode": "pilot"}}],
    }), encoding="utf-8")
    monkeypatch.setattr(
        scheduler, "_preassign_mutating_task",
        lambda **_kw: {"ok": True, "assigned": False, "blocked_contracts": []},
    )
    allocations: list[dict] = []
    monkeypatch.setattr(
        scheduler.workspace_mod, "allocate_workspace",
        lambda **kw: allocations.append(kw),
    )
    finalized: list[dict] = []
    monkeypatch.setattr(scheduler.workspace_mod, "finalize_workspace",
                        lambda **kw: finalized.append(kw))
    received: list[dict] = []

    def fake_run_worker(**kwargs):
        received.append(kwargs)
        return worker.WorkerResult(
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            attempts=1, duration_s=1.0, log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)
    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "worker.log", dry_run=False,
        repo_root=tmp_path, schedules_path=schedules,
    ))
    assert result["action"] == "fired"
    assert result["workspace"] is None
    assert "Producer-scoped workspace" not in received[0]["prompt_text"]
    assert finalized == []  # nothing allocated -> nothing finalized
    assert allocations == []


@pytest.mark.parametrize("allocation_failure", ["declined", "raised"])
def test_scheduler_enforce_requeues_instead_of_firing_unisolated(
    tmp_path: Path, monkeypatch, allocation_failure: str,
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{"id": "volpred-dispatch-supervisor", "max_slots": 2,
                     "writer_isolation": {"mode": "enforce"}}],
    }), encoding="utf-8")
    monkeypatch.setattr(scheduler.workspace_mod, "sweep_orphan_workspaces",
                        lambda **kw: [])
    monkeypatch.setattr(
        scheduler, "_preassign_mutating_task",
        lambda **_kw: _assigned_mutating_task(),
    )
    monkeypatch.setattr(
        scheduler, "_settle_mutating_task",
        lambda **_kw: {"ok": True, "status": "pending"},
    )
    if allocation_failure == "raised":
        def allocation_result(**_kwargs):
            raise RuntimeError("allocator unavailable")
    else:
        def allocation_result(**_kwargs):
            return None
    monkeypatch.setattr(
        scheduler.workspace_mod, "allocate_workspace", allocation_result,
    )
    spawned: list[dict] = []
    monkeypatch.setattr(
        scheduler.worker, "run_worker", lambda **kwargs: spawned.append(kwargs),
    )

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "worker.log", dry_run=False,
        repo_root=tmp_path, schedules_path=schedules,
    ))

    assert result["action"] == "isolation_deferred"
    assert result["reason"] == "workspace_unavailable"
    assert spawned == []
    snap = state.read_state(state_path)
    assert snap["current_jobs"] == []
    assert snap["fire_requested_at"] is not None
    assert snap["fire_request_reason"].startswith("writer_isolation_deferred:")


@pytest.mark.parametrize(
    ("failure_stage", "final_disposition"),
    (
        ("preflight", "remove_failed"),
        ("preflight", "receipt_failed"),
        ("attach", "receipt_failed"),
    ),
)
def test_admission_failure_never_requeues_before_workspace_is_terminal(
    tmp_path: Path, monkeypatch, failure_stage: str, final_disposition: str,
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{
            "id": "volpred-dispatch-supervisor",
            "max_slots": 2,
            "writer_isolation": {"mode": "enforce"},
        }],
    }), encoding="utf-8")
    fake_path = tmp_path / "workspace"
    fake_path.mkdir()
    fake_ws = {
        "name": "dispatch-slot-1-terminality",
        "path": str(fake_path),
        "branch": "worktree-dispatch-slot-1-terminality",
        "base_sha": "abc",
        **_assigned_mutating_task()["contract"],
    }
    monkeypatch.setattr(
        scheduler, "_preassign_mutating_task",
        lambda **_kw: _assigned_mutating_task(),
    )
    monkeypatch.setattr(
        scheduler.workspace_mod, "sweep_orphan_workspaces",
        lambda **_kw: [],
    )
    monkeypatch.setattr(
        scheduler.workspace_mod, "allocate_workspace",
        lambda **_kw: dict(fake_ws),
    )
    monkeypatch.setattr(
        scheduler.workspace_mod, "finalize_workspace",
        lambda **_kw: {
            "disposition": final_disposition,
            "reason": "injected_nonterminal",
        },
    )
    monkeypatch.setattr(
        scheduler.isolation, "prepare",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("preflight failed")),
    )
    if failure_stage == "attach":
        monkeypatch.setattr(
            scheduler.state, "attach_workspace", lambda **_kw: False
        )
    settlements: list[dict] = []
    monkeypatch.setattr(
        scheduler, "_settle_mutating_task",
        lambda **kwargs: settlements.append(kwargs)
        or {"ok": True, "status": "pending"},
    )
    spawned: list[dict] = []
    monkeypatch.setattr(
        scheduler.worker, "run_worker", lambda **kwargs: spawned.append(kwargs)
    )

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=prompt_path, log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path, schedules_path=schedules,
    ))

    assert result["reason"] == "workspace_finalize_pending"
    assert settlements == []
    assert spawned == []
    if failure_stage == "preflight":
        current = state.read_state(state_path)["current_jobs"]
        assert current and current[0]["workspace"]["task_id"] == fake_ws["task_id"]


def test_scheduler_spawns_isolated_worker_from_workspace_cwd(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{"id": "volpred-dispatch-supervisor", "max_slots": 2,
                     "writer_isolation": {"mode": "enforce"}}],
    }), encoding="utf-8")
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    fake_ws = {
        "name": "dispatch-slot-1-fixed", "path": str(workspace_path),
        "branch": "worktree-dispatch-slot-1-fixed", "base_sha": "abc",
        "lanes": ["platform_ops"], "created_at": "2026-07-20T00:00:00+00:00",
        "setup_s": 1.0, "denied_canonical_paths": ["storage/**"],
    }
    monkeypatch.setattr(
        scheduler, "_preassign_mutating_task",
        lambda **_kw: _assigned_mutating_task(),
    )
    monkeypatch.setattr(
        scheduler.isolation, "prepare",
        lambda **_kw: _prepared_isolation(tmp_path),
    )
    monkeypatch.setattr(
        scheduler, "_settle_mutating_task",
        lambda **_kw: {"ok": True, "status": "pending"},
    )
    monkeypatch.setattr(scheduler.workspace_mod, "sweep_orphan_workspaces",
                        lambda **kw: [])
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "allocate_workspace",
        lambda **kw: {
            **fake_ws,
            **kw["task_binding"],
            "task_title": kw["task_binding"]["title"],
            "task_description": kw["task_binding"]["description"],
        },
    )
    monkeypatch.setattr(scheduler.workspace_mod, "finalize_workspace",
                        lambda **kw: {"disposition": "empty_removed"})
    received: list[dict] = []

    def fake_run_worker(**kwargs):
        received.append(kwargs)
        state.record_completion(
            job_id=kwargs["job_id"], exit_code=0, outcome="success",
            final_model=worker.OPUS_MODEL, path=kwargs["state_path"],
        )
        return worker.WorkerResult(
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            attempts=1, duration_s=1.0, log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "worker.log", dry_run=False,
        repo_root=tmp_path, schedules_path=schedules,
    ))

    assert result["action"] == "fired"
    assert received[0]["workdir"] == workspace_path
    assert "OS sandbox 綁定 producer workspace" in received[0]["prompt_text"]
    assert "inline task 可用絕對路徑編輯 canonical_root" not in received[0]["prompt_text"]


def test_workspace_os_sandbox_denies_canonical_repo_bytes_but_allows_contract_paths(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin" or not isolation.SANDBOX_EXEC.is_file():
        pytest.skip("production isolation substrate is macOS sandbox-exec")
    # pytest owns cleanup of this fixture.  A nested TemporaryDirectory made
    # shutil emit dir_fd-relative audit paths that CIParity correctly cannot
    # resolve without the missing dir_fd context.
    with contextlib.nullcontext(tmp_path) as root:
        repo = root / "repo"
        repo.mkdir()
        _git_init_repo(repo)
        ws = _ws_allocate(repo, job_id="1" * 32, slot="slot-1")
        assert ws is not None
        wt = Path(ws["path"])
        prepared = isolation.prepare(
            canonical_root=repo,
            workspace=wt,
            job_id="sandbox-test",
            profile_root=root / "profiles",
        )
        profile = Path(prepared.profile_path)
        authority_home = root / "authority"
        authority_auth = authority_home / ".codex" / "auth.json"
        authority_auth.parent.mkdir(parents=True)
        authority_auth.write_text(
            json.dumps({
                "OPENAI_API_KEY": None,
                "tokens": {
                    "access_token": "sandbox-access",
                    "refresh_token": "sandbox-refresh",
                    "id_token": "sandbox-id",
                    "account_id": "sandbox-account",
                },
            }),
            encoding="utf-8",
        )
        authority_auth.chmod(0o600)
        codex_auth_lease = isolation.materialize_provider_auth(
            prepared,
            provider_id="codex-cli",
            credential_home=authority_home,
        )
        assert codex_auth_lease is not None

        denied = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c", f"printf denied > {repo / 'forbidden.txt'}",
            ],
            capture_output=True, text=True, check=False,
        )
        allowed_workspace = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c", f"printf allowed > {wt / 'allowed.txt'}",
            ],
            capture_output=True, text=True, check=False,
        )
        denied_state = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c",
                f"mkdir -p {repo / 'storage' / 'ops'} && "
                f"printf denied > {repo / 'storage' / 'ops' / 'denied.json'}",
            ],
            capture_output=True, text=True, check=False,
        )
        (wt / "git-mutation.txt").write_text("producer bytes\n", encoding="utf-8")
        git_mutation = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/usr/bin/git",
                "-C", str(wt), "add", "git-mutation.txt",
            ],
            capture_output=True, text=True, check=False,
        )
        credential_probe = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c",
                f"/bin/cat {Path.home() / '.config' / 'gh' / 'hosts.yml'} "
                f"> {wt / 'credential-copy'}",
            ],
            capture_output=True, text=True, check=False,
        )
        volpred_secret_probe = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c",
                f"/bin/cat {Path.home() / '.volpred' / 'secrets' / 'claude_oauth_token'} "
                f"> {wt / 'volpred-secret-copy'}",
            ],
            capture_output=True, text=True, check=False,
        )
        codex_host_auth_probe = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c",
                f"/bin/cat {Path.home() / '.codex' / 'auth.json'} "
                f"> {wt / 'codex-auth-copy'}",
            ],
            capture_output=True, text=True, check=False,
        )
        codex_synthetic_auth_probe = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC), "-f", str(profile), "/bin/sh",
                "-c",
                f"/bin/cat {codex_auth_lease.destination_path} > /dev/null",
            ],
            capture_output=True, text=True, check=False,
        )
        log_path = root / "sandbox-inherited-fd-test.log"
        log_file = log_path.open("w", encoding="utf-8")
        try:
            inherited_log_fd = subprocess.run(
                [
                    str(isolation.SANDBOX_EXEC), "-f", str(profile),
                    "/bin/sh", "-c", "test -w /dev/fd/1 && printf ok",
                ],
                stdout=log_file, stderr=subprocess.PIPE, text=True,
                check=False,
            )
            log_file.flush()
            inherited_log_size = log_file.tell()
        finally:
            log_file.close()
            log_path.unlink(missing_ok=True)

        assert denied.returncode != 0
        assert not (repo / "forbidden.txt").exists()
        assert allowed_workspace.returncode == 0
        assert denied_state.returncode != 0
        assert not (repo / "storage" / "ops" / "denied.json").exists()
        assert git_mutation.returncode != 0
        assert credential_probe.returncode != 0
        assert volpred_secret_probe.returncode != 0
        assert codex_host_auth_probe.returncode != 0
        assert codex_synthetic_auth_probe.returncode == 0
        assert inherited_log_fd.returncode == 0
        assert inherited_log_size == 2
        # The shell may create the redirection target before the denied
        # credential read, but no credential bytes may cross the fence.
        copied = wt / "credential-copy"
        assert not copied.exists() or copied.read_bytes() == b""
        volpred_copied = wt / "volpred-secret-copy"
        assert not volpred_copied.exists() or volpred_copied.read_bytes() == b""
        codex_auth_copied = wt / "codex-auth-copy"
        assert (
            not codex_auth_copied.exists()
            or codex_auth_copied.read_bytes() == b""
        )
        close_receipt = codex_auth_lease.close()
        assert close_receipt.ok is True
        assert close_receipt.cleaned is True


def test_observe_only_sandbox_denies_workspace_writes(
    tmp_path: Path,
) -> None:
    if sys.platform != "darwin" or not isolation.SANDBOX_EXEC.is_file():
        pytest.skip("production isolation substrate is macOS sandbox-exec")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo, job_id="0" * 32, slot="slot-1")
    assert ws is not None
    wt = Path(ws["path"])
    prepared = isolation.prepare(
        canonical_root=repo,
        workspace=wt,
        job_id="observe-only-sandbox-test",
        profile_root=tmp_path / "profiles",
        allow_workspace_write=False,
    )

    denied_workspace = subprocess.run(
        [
            str(isolation.SANDBOX_EXEC),
            "-f",
            prepared.profile_path,
            "/bin/sh",
            "-c",
            f"printf denied > {wt / 'forbidden-observer-output.txt'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    allowed_tmp = subprocess.run(
        [
            str(isolation.SANDBOX_EXEC),
            "-f",
            prepared.profile_path,
            "/bin/sh",
            "-c",
            f"printf allowed > {Path(prepared.tmp_dir) / 'scratch.txt'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert denied_workspace.returncode != 0
    assert not (wt / "forbidden-observer-output.txt").exists()
    assert allowed_tmp.returncode == 0


def test_workspace_os_sandbox_allows_worker_to_terminate_its_own_child(
    tmp_path: Path,
) -> None:
    """Producer isolation must not turn normal child cleanup into orphan work."""
    if sys.platform != "darwin" or not isolation.SANDBOX_EXEC.is_file():
        pytest.skip("production isolation substrate is macOS sandbox-exec")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo, job_id="2" * 32, slot="slot-1")
    assert ws is not None
    prepared = isolation.prepare(
        canonical_root=repo,
        workspace=Path(ws["path"]),
        job_id="sandbox-child-signal-test",
        profile_root=tmp_path / "profiles",
    )
    probe = (
        "import subprocess, sys; "
        "child = subprocess.Popen("
        "[sys.executable, '-c', 'import time; time.sleep(2)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "child.terminate(); "
        "raise SystemExit(child.wait(timeout=5) not in (-15, 143))"
    )
    result = subprocess.run(
        [
            str(isolation.SANDBOX_EXEC),
            "-f",
            prepared.profile_path,
            sys.executable,
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_workspace_os_sandbox_cannot_signal_unrelated_host_process(
    tmp_path: Path,
) -> None:
    """Child cleanup capability must not extend to sibling host processes."""
    if sys.platform != "darwin" or not isolation.SANDBOX_EXEC.is_file():
        pytest.skip("production isolation substrate is macOS sandbox-exec")
    outside = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git_init_repo(repo)
        ws = _ws_allocate(repo, job_id="3" * 32, slot="slot-1")
        assert ws is not None
        prepared = isolation.prepare(
            canonical_root=repo,
            workspace=Path(ws["path"]),
            job_id="sandbox-signal-boundary-test",
            profile_root=tmp_path / "profiles",
        )
        probe = (
            "import os, signal, sys; "
            "\ntry: os.kill(int(sys.argv[1]), signal.SIGTERM)"
            "\nexcept PermissionError: raise SystemExit(0)"
            "\nraise SystemExit(1)"
        )
        result = subprocess.run(
            [
                str(isolation.SANDBOX_EXEC),
                "-f",
                prepared.profile_path,
                sys.executable,
                "-c",
                probe,
                str(outside.pid),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert outside.poll() is None
    finally:
        outside.terminate()
        outside.wait(timeout=5)


def test_workspace_os_sandbox_can_terminate_multiprocessing_pool(
    tmp_path: Path,
) -> None:
    """Regression: Pool cleanup previously leaked children after sandbox EPERM."""
    if sys.platform != "darwin" or not isolation.SANDBOX_EXEC.is_file():
        pytest.skip("production isolation substrate is macOS sandbox-exec")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    ws = _ws_allocate(repo, job_id="4" * 32, slot="slot-1")
    assert ws is not None
    prepared = isolation.prepare(
        canonical_root=repo,
        workspace=Path(ws["path"]),
        job_id="sandbox-pool-signal-test",
        profile_root=tmp_path / "profiles",
    )
    probe = (
        "import multiprocessing as mp, time; "
        "pool = mp.get_context('fork').Pool(2); "
        "workers = tuple(pool._pool); "
        "pool.map_async(time.sleep, [2, 2]); "
        "time.sleep(0.1); "
        "pool.terminate(); pool.join(); "
        "raise SystemExit(any("
        "proc.exitcode not in (-15, -9) for proc in workers))"
    )
    result = subprocess.run(
        [
            str(isolation.SANDBOX_EXEC),
            "-f",
            prepared.profile_path,
            sys.executable,
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_isolated_environment_scopes_subscription_auth_to_provider(
    tmp_path: Path,
) -> None:
    prepared = isolation.PreparedIsolation(
        profile_path=str(tmp_path / "sandbox.sb"),
        run_dir=str(tmp_path / "run"),
        synthetic_home=str(tmp_path / "home"),
        tmp_dir=str(tmp_path / "tmp"),
        pycache_dir=str(tmp_path / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    base = {
        "PATH": "/usr/bin",
        "LANG": "en_US.UTF-8",
        "CLAUDE_CODE_OAUTH_TOKEN": "model-only",
        "ANTHROPIC_API_KEY": "metered-anthropic",
        "OPENAI_API_KEY": "metered-openai",
        "CODEX_API_KEY": "metered-codex",
        "OPENAI_ORG_ID": "must-not-pass",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
        "GIT_ASKPASS": "/tmp/askpass",
        "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/gcp.json",
        "TELEGRAM_BOT_TOKEN": "external-effect",
        "VOLPRED_ACTOR": "dispatch-supervisor",
        "VOLPRED_TASK_CLAIM_OWNER": "dispatch-eff32f3b",
        "VOLPRED_DISPATCH_JOB_ID": "eff32f3b",
        "VOLPRED_FIRE_ID": "fire-43",
    }
    claude_env = isolation.isolated_environment(
        base,
        prepared,
        provider_id="claude-cli",
    )
    codex_env = isolation.isolated_environment(
        base,
        prepared,
        provider_id="codex-cli",
    )

    assert claude_env["PATH"] == "/usr/bin"
    assert claude_env["CLAUDE_CODE_OAUTH_TOKEN"] == "model-only"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in codex_env
    assert claude_env["HOME"] == str(tmp_path / "home")
    assert claude_env["TMPDIR"] == str(tmp_path / "tmp")
    assert claude_env["CLAUDE_CODE_TMPDIR"] == str(tmp_path / "tmp")
    assert claude_env["CLAUDE_TMPDIR"] == str(tmp_path / "tmp")
    assert "CLAUDE_CODE_TMPDIR" not in codex_env
    assert "CLAUDE_TMPDIR" not in codex_env
    assert claude_env["VOLPRED_ACTOR"] == "dispatch-supervisor"
    assert claude_env["VOLPRED_TASK_CLAIM_OWNER"] == "dispatch-eff32f3b"
    assert claude_env["VOLPRED_DISPATCH_JOB_ID"] == "eff32f3b"
    assert claude_env["VOLPRED_FIRE_ID"] == "fire-43"
    for env in (claude_env, codex_env):
        for denied in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "OPENAI_ORG_ID",
            "SSH_AUTH_SOCK",
            "GIT_ASKPASS",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "TELEGRAM_BOT_TOKEN",
        ):
            assert denied not in env


def test_codex_subscription_auth_is_materialized_into_synthetic_home(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": "subscription-access",
                "refresh_token": "subscription-refresh",
                "id_token": "subscription-id",
                "account_id": "account",
            },
            "last_refresh": "2026-07-28T00:00:00Z",
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)
    (tmp_path / "run" / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(tmp_path / "sandbox.sb"),
        run_dir=str(tmp_path / "run"),
        synthetic_home=str(tmp_path / "run" / "home"),
        tmp_dir=str(tmp_path / "run" / "tmp"),
        pycache_dir=str(tmp_path / "run" / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )

    lease = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert lease is not None
    destination = Path(lease.destination_path)

    assert destination == Path(prepared.synthetic_home) / ".codex" / "auth.json"
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.parent.stat().st_mode & 0o777 == 0o700
    receipt = lease.close()
    assert receipt.ok is True
    assert receipt.cleaned is True
    assert not destination.exists()


def test_codex_auth_lease_reconciles_rotation_then_cleans(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source_payload = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": "access-a",
            "refresh_token": "refresh-a",
            "id_token": "id-a",
            "account_id": "account",
        },
    }
    source.write_text(json.dumps(source_payload), encoding="utf-8")
    source.chmod(0o600)
    run_dir = tmp_path / "run"
    for path in (run_dir, run_dir / "home"):
        path.mkdir(mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    lease = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert lease is not None
    destination = Path(lease.destination_path)
    rotated = {
        **source_payload,
        "tokens": {
            **source_payload["tokens"],
            "access_token": "access-b",
            "refresh_token": "refresh-b",
            "id_token": "id-b",
        },
    }
    destination.write_text(json.dumps(rotated), encoding="utf-8")
    destination.chmod(0o600)

    receipt = lease.close()

    assert receipt.ok is True
    assert receipt.reconciled is True
    assert json.loads(source.read_text(encoding="utf-8")) == rotated
    assert not destination.exists()


def test_codex_auth_authority_allows_only_one_live_lease(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)

    def prepared(name: str) -> isolation.PreparedIsolation:
        run_dir = tmp_path / name
        (run_dir / "home").mkdir(parents=True, mode=0o700, exist_ok=True)
        return isolation.PreparedIsolation(
            profile_path=str(run_dir / "sandbox.sb"),
            run_dir=str(run_dir),
            synthetic_home=str(run_dir / "home"),
            tmp_dir=str(run_dir / "tmp"),
            pycache_dir=str(run_dir / "pycache"),
            workspace=str(tmp_path / f"{name}-workspace"),
            canonical_root=str(tmp_path / "repo"),
        )

    first = isolation.materialize_provider_auth(
        prepared("run-a"),
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert first is not None

    with pytest.raises(
        isolation.IsolationUnavailable,
        match="credential authority is already leased",
    ):
        isolation.materialize_provider_auth(
            prepared("run-b"),
            provider_id="codex-cli",
            credential_home=source_home,
        )

    assert first.close().ok is True
    second = isolation.materialize_provider_auth(
        prepared("run-b"),
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert second is not None
    assert second.close().ok is True


def test_child_lease_close_does_not_unlock_parent_quarantine_descriptor(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    source.chmod(0o600)
    run_dir = tmp_path / "run"
    (run_dir / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    parent = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert parent is not None and parent._authority_lock_fd is not None
    child_fd = os.dup(parent._authority_lock_fd)
    child = isolation.ProviderAuthLease(
        source_home=parent.source_home,
        run_dir=parent.run_dir,
        destination_path=parent.destination_path,
        baseline_sha256=parent.baseline_sha256,
        lease_id=parent.lease_id,
        _authority_lock_fd=child_fd,
    )

    assert child.close().ok is True

    contender_fd = os.open(
        source.parent / isolation._PROVIDER_AUTH_LOCK_NAME,
        os.O_RDWR,
    )
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(
                contender_fd,
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
    finally:
        os.close(contender_fd)
        isolation._release_provider_auth_lock(parent._authority_lock_fd)
        parent._authority_lock_fd = None


def test_codex_auth_close_failure_remains_retryable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)
    run_dir = tmp_path / "run"
    (run_dir / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    lease = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert lease is not None
    destination = Path(lease.destination_path)
    real_unlink = isolation.os.unlink
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected cleanup failure")
        return real_unlink(*args, **kwargs)

    monkeypatch.setattr(isolation.os, "unlink", fail_once)

    first = lease.close()
    assert first.ok is False
    assert first.cleaned is False
    assert destination.exists()

    second = lease.close()
    assert second.ok is True
    assert second.cleaned is True
    assert not destination.exists()
    assert lease.close() == second


def test_codex_auth_close_retries_after_unlink_fsync_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)
    run_dir = tmp_path / "run"
    (run_dir / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    lease = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert lease is not None
    real_fsync = isolation.os.fsync
    fail_next = True

    def fail_once(fd: int) -> None:
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise OSError("injected post-unlink fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(isolation.os, "fsync", fail_once)
    first = lease.close()
    assert first.ok is False
    assert not Path(lease.destination_path).exists()
    assert Path(lease.destination_path).parent.is_dir()

    second = lease.close()
    assert second.ok is True
    assert second.cleaned is True


def test_codex_auth_close_revalidates_secret_recreated_after_recovery_snapshot(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    baseline = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "access_token": "access-a",
            "refresh_token": "refresh-a",
            "id_token": "id-a",
            "account_id": "account",
        },
    }
    source.write_text(json.dumps(baseline), encoding="utf-8")
    source.chmod(0o600)
    run_dir = tmp_path / "run"
    (run_dir / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    lease = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=source_home,
    )
    assert lease is not None
    rotated = {
        **baseline,
        "tokens": {
            **baseline["tokens"],
            "access_token": "access-b",
            "refresh_token": "refresh-b",
            "id_token": "id-b",
        },
    }
    destination = Path(lease.destination_path)
    destination.write_text(json.dumps(rotated), encoding="utf-8")
    destination.chmod(0o600)
    # Recovery's earlier snapshot saw the file absent; a descendant recreated
    # it before the process group drained.
    lease._destination_unlinked = True

    receipt = lease.close()

    assert receipt.ok is True
    assert receipt.reconciled is True
    assert json.loads(source.read_text(encoding="utf-8")) == rotated
    assert not destination.exists()


def test_default_codex_authority_is_not_the_interactive_codex_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(isolation.Path, "home", lambda: tmp_path)

    authority = isolation._credential_home()

    assert authority == (
        tmp_path / ".volpred" / "secrets" / "provider-auth" / "codex-home"
    )
    assert authority != tmp_path


def test_codex_authority_bootstrap_is_verified_and_never_overwrites(
    tmp_path: Path,
) -> None:
    interactive_home = tmp_path / "interactive"
    authority_home = tmp_path / "authority"
    source = interactive_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": "access-a",
                "refresh_token": "refresh-a",
                "id_token": "id-a",
                "account_id": "account",
            },
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)

    first = isolation.bootstrap_codex_auth_authority(
        interactive_home=interactive_home,
        authority_home=authority_home,
    )
    target = authority_home / ".codex" / "auth.json"

    assert first["action"] == "provisioned"
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert isolation.bootstrap_codex_auth_authority(
        interactive_home=interactive_home,
        authority_home=authority_home,
    )["action"] == "already_provisioned"

    changed = json.loads(source.read_text(encoding="utf-8"))
    changed["tokens"]["access_token"] = "access-b"
    source.write_text(json.dumps(changed), encoding="utf-8")
    source.chmod(0o600)
    with pytest.raises(
        isolation.IsolationUnavailable,
        match="refusing to overwrite",
    ):
        isolation.bootstrap_codex_auth_authority(
            interactive_home=interactive_home,
            authority_home=authority_home,
        )


def test_codex_authority_bootstrap_holds_authority_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    interactive_home = tmp_path / "interactive"
    authority_home = tmp_path / "authority"
    source = interactive_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    source.chmod(0o600)
    events: list[str] = []
    real_acquire = isolation._acquire_provider_auth_lock
    real_release = isolation._release_provider_auth_lock

    def acquire(directory_fd: int) -> int:
        events.append("acquire")
        return real_acquire(directory_fd)

    def release(fd: int | None) -> None:
        events.append("release")
        real_release(fd)

    monkeypatch.setattr(isolation, "_acquire_provider_auth_lock", acquire)
    monkeypatch.setattr(isolation, "_release_provider_auth_lock", release)

    isolation.bootstrap_codex_auth_authority(
        interactive_home=interactive_home,
        authority_home=authority_home,
    )

    assert events == ["acquire", "release"]


def test_auth_lease_reaper_requires_two_consecutive_empty_group_reads(
    monkeypatch,
) -> None:
    observations = iter([[777], [], None, [], []])
    sleeps: list[float] = []
    monkeypatch.setattr(
        auth_lease_reaper.procutil,
        "pgid_members_checked",
        lambda _pgid: next(observations),
    )
    monkeypatch.setattr(
        auth_lease_reaper.time,
        "sleep",
        lambda seconds: sleeps.append(seconds),
    )

    auth_lease_reaper.wait_until_process_group_drained(888)

    assert len(sleeps) == 5


def test_auth_lease_reaper_retries_close_until_terminal_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    close_attempts = iter([
        isolation.ProviderAuthCloseReceipt(
            False, False, False, False, "injected cleanup failure",
        ),
        isolation.ProviderAuthCloseReceipt(
            True, False, False, True, "closed",
        ),
    ])
    written: list[dict] = []

    class FakeLease:
        def __init__(self, **_kwargs):
            pass

        def close(self, **_kwargs):
            return next(close_attempts)

    monkeypatch.setattr(
        auth_lease_reaper,
        "wait_until_process_group_drained",
        lambda _pgid, **_kwargs: None,
    )
    monkeypatch.setattr(
        auth_lease_reaper.isolation,
        "ProviderAuthLease",
        FakeLease,
    )
    def transition(_path, payload):
        written.append(payload)
        return payload

    monkeypatch.setattr(
        auth_lease_reaper.isolation,
        "_transition_provider_auth_reaper_receipt",
        transition,
    )
    attempt_numbers = iter([2])

    def begin_attempt(*_args, **_kwargs):
        attempt = next(attempt_numbers)
        payload = {"state": "cleanup_started", "attempts": attempt}
        written.append(payload)
        return attempt, payload

    monkeypatch.setattr(
        auth_lease_reaper.isolation,
        "_reconcile_lease_from_provider_auth_receipt",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        auth_lease_reaper.isolation,
        "_begin_provider_auth_cleanup_attempt",
        begin_attempt,
    )
    monkeypatch.setattr(auth_lease_reaper.time, "sleep", lambda _seconds: None)
    args = SimpleNamespace(
        receipt_path=str(tmp_path / "receipt.json"),
        pgid=888,
        source_home=str(tmp_path / "source"),
        run_dir=str(tmp_path / "run"),
        destination_path=str(tmp_path / "run" / "home" / ".codex" / "auth.json"),
        baseline_sha256="a" * 64,
        lock_fd=99,
        lease_id="lease-test",
        ack_fd=None,
        leader_pid=888,
        leader_started_wall="start",
    )

    assert auth_lease_reaper.reap(args) == 0
    assert [item["state"] for item in written] == [
        "waiting_for_process_group",
        "cleanup_started",
        "cleanup_retry",
        "cleanup_started",
        "cleaned",
    ]
    assert written[-1]["attempts"] == 2


def test_reaper_receipt_allows_new_attempt_phase_after_cleanup_retry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "receipt.json"
    isolation._transition_provider_auth_reaper_receipt(
        path,
        {
            "schema_version": "provider-auth-reaper.v2",
            "state": "cleanup_retry",
            "attempts": 1,
        },
    )

    isolation._transition_provider_auth_reaper_receipt(
        path,
        {
            "state": "cleanup_started",
            "attempts": 2,
            "close_phase": "unlink_intent",
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["state"] == "cleanup_started"
    assert payload["attempts"] == 2
    assert payload["close_phase"] == "unlink_intent"


def test_reaper_quarantine_custody_survives_later_cleanup_phase(
    tmp_path: Path,
) -> None:
    path = tmp_path / "receipt.json"
    isolation._transition_provider_auth_reaper_receipt(
        path,
        {
            "schema_version": "provider-auth-reaper.v2",
            "state": "cleanup_retry",
            "attempts": 2,
            "custody_state": "reaper",
            "custody_generation": 5,
            "custody_owner": "reaper:999",
        },
    )

    isolation._mark_provider_auth_quarantine(
        path,
        attempt=1,
        reaper_pid=999,
        reaper_started_wall="Mon Jul 28 12:00:01 2026",
        reason="injected no-ACK child",
    )
    isolation._transition_provider_auth_reaper_receipt(
        path,
        {
            "state": "cleanup_retry",
            "attempts": 2,
            "custody_state": "reaper",
            "custody_generation": 5,
            "custody_owner": "reaper:999",
        },
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["state"] == "cleanup_retry"
    assert payload["attempts"] == 2
    assert payload["custody_state"] == "quarantined"
    assert payload["custody_generation"] == 6
    assert payload["custody_owner"].startswith("quarantine-parent:")
    assert payload["reaper_pid"] == 999


def test_post_spawn_receipt_failure_quarantines_without_unlock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / "authority.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    lease = isolation.ProviderAuthLease(
        source_home=str(tmp_path / "authority"),
        run_dir=str(tmp_path / "run"),
        destination_path=str(
            tmp_path / "run" / "home" / ".codex" / "auth.json"
        ),
        baseline_sha256="a" * 64,
        lease_id="post-spawn-failure",
        _authority_lock_fd=lock_fd,
    )

    sent_signals: list[int] = []

    class UnreapableChild:
        """A child that swallows every signal and never exits.

        It stands in for ``subprocess.Popen``, so it has to answer the same
        questions the no-ACK reap path asks of a real handle: ``poll()`` is how
        that path proves the pid it is about to signal is still the child it
        spawned, and ``send_signal`` is the syscall the durable-intent owner
        delegates to. Stubbing only ``terminate``/``kill`` modelled the private
        shortcut rather than the contract.
        """

        pid = 999

        def poll(self):
            return None

        def send_signal(self, signum):
            sent_signals.append(signum)

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("reaper", timeout)

    monkeypatch.setattr(
        isolation.subprocess,
        "Popen",
        lambda *_a, **_k: UnreapableChild(),
    )
    monkeypatch.setattr(
        procutil,
        "get_process_start_wall",
        lambda _pid: "Mon Jul 28 12:00:01 2026",
    )
    transition = isolation._transition_provider_auth_reaper_receipt
    transition_calls = 0

    def fail_post_spawn_transition(path, payload):
        nonlocal transition_calls
        transition_calls += 1
        if transition_calls == 1:
            raise OSError("injected receipt failure after spawn")
        return transition(path, payload)

    monkeypatch.setattr(
        isolation,
        "_transition_provider_auth_reaper_receipt",
        fail_post_spawn_transition,
    )
    receipt_path = tmp_path / "receipts" / "lease.json"

    with pytest.raises(isolation.ProviderAuthHandoffQuarantined):
        isolation.defer_provider_auth_cleanup(
            lease,
            pgid=888,
            leader_pid=888,
            leader_started_wall="Mon Jul 28 12:00:00 2026",
            receipt_path=receipt_path,
        )

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["attempts"] == 1
    assert payload["custody_state"] == "quarantined"
    assert payload["reaper_pid"] == 999
    assert sent_signals == [signal.SIGTERM, signal.SIGKILL, signal.SIGKILL]
    termination_events = [
        json.loads(line)
        for line in (receipt_path.parent / "termination_intents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [
        event["event"] for event in termination_events
    ] == [
        "intent_armed",
        "signal_attempted",
        "signal_result",
    ] * 3
    assert [
        event["signum"]
        for event in termination_events
        if event["event"] == "signal_result"
    ] == [signal.SIGTERM, signal.SIGKILL, signal.SIGKILL]
    assert all(
        event["status"] == "sent"
        for event in termination_events
        if event["event"] == "signal_result"
    )
    assert {
        event["target_identity"]
        for event in termination_events
    } == {"Mon Jul 28 12:00:01 2026"}
    competing_fd = os.open(lock_path, os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(competing_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(competing_fd)
        isolation._release_provider_auth_lock(lock_fd)


def test_synchronous_auth_custody_ignores_receipt_io_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    close_calls: list[bool] = []

    class FakeLease:
        def close(self, *, checkpoint=None):
            assert checkpoint is not None
            checkpoint("unlink_intent")
            close_calls.append(True)
            return isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    monkeypatch.setattr(
        isolation,
        "wait_for_process_group_generation_drained",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        isolation,
        "_transition_provider_auth_reaper_receipt",
        lambda *_a, **_k: (_ for _ in ()).throw(
            OSError("receipt filesystem unavailable")
        ),
    )

    receipt = isolation.reap_provider_auth_lease_in_process(
        FakeLease(),
        pgid=888,
        leader_pid=888,
        leader_started_wall="Mon Jul 28 12:00:00 2026",
        receipt_path=tmp_path / "receipt.json",
    )

    assert receipt.ok is True
    assert close_calls == [True]


def test_health_reaps_quarantined_auth_after_child_and_group_are_gone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    close_calls: list[bool] = []

    class FakeLease:
        lease_id = "quarantine-health-test"

        def close(self, *, checkpoint=None):
            assert checkpoint is not None
            checkpoint("destination_unlinked")
            close_calls.append(True)
            return isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    class DeadReaper:
        def poll(self):
            return 1

    monkeypatch.setattr(
        procutil,
        "pgid_members_checked",
        lambda _pgid: [],
    )
    monkeypatch.setattr(
        isolation,
        "_transition_provider_auth_reaper_receipt",
        lambda _path, payload: payload,
    )
    monkeypatch.setattr(
        isolation,
        "_reconcile_lease_from_provider_auth_receipt",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        isolation,
        "_begin_provider_auth_cleanup_attempt",
        lambda *_a, **_k: (
            1,
            {"state": "cleanup_started", "attempts": 1},
        ),
    )
    isolation.quarantine_provider_auth_lease(
        FakeLease(),
        pgid=888,
        leader_pid=888,
        leader_started_wall="Mon Jul 28 12:00:00 2026",
        receipt_path=tmp_path / "receipt.json",
        reaper_process=DeadReaper(),
    )

    first = isolation.reap_quarantined_provider_auth_leases()
    second = isolation.reap_quarantined_provider_auth_leases()

    assert first == {"pending": 1, "cleaned": 0}
    assert second == {"pending": 0, "cleaned": 1}
    assert close_calls == [True]


def test_provider_auth_recovery_reclaims_nonterminal_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authority = tmp_path / "authority"
    codex_dir = authority / ".codex"
    codex_dir.mkdir(parents=True, mode=0o700)
    auth = codex_dir / "auth.json"
    auth.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    auth.chmod(0o600)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    destination = tmp_path / "run" / "home" / ".codex" / "auth.json"
    destination.parent.mkdir(parents=True, mode=0o700)
    destination.write_bytes(auth.read_bytes())
    destination.chmod(0o600)
    receipt_path = receipts / "lease.json"
    receipt_path.write_text(
        json.dumps({
            "schema_version": "provider-auth-reaper.v2",
            "state": "handoff_failed",
            "lease_id": "lease-id",
            "source_home": str(authority),
            "run_dir": str(tmp_path / "run"),
            "destination_path": str(
                destination
            ),
            "baseline_sha256": "a" * 64,
            "pgid": 888,
            "leader_pid": 888,
            "leader_started_wall": "Mon Jul 28 12:00:00 2026",
        }),
        encoding="utf-8",
    )
    deferred: list[tuple[str, int, int, str, Path]] = []

    def defer(
        lease,
        *,
        pgid,
        leader_pid,
        leader_started_wall,
        receipt_path,
    ):
        deferred.append(
            (
                lease.lease_id,
                pgid,
                leader_pid,
                leader_started_wall,
                receipt_path,
            )
        )
        isolation._release_provider_auth_lock(lease._authority_lock_fd)
        lease._authority_lock_fd = None

    monkeypatch.setattr(isolation, "defer_provider_auth_cleanup", defer)

    result = isolation.recover_provider_auth_reapers(
        authority_home=authority,
        receipt_root=receipts,
    )

    assert result == {"recovered": 1, "active": 0, "invalid": 0}
    assert deferred == [
        (
            "lease-id",
            888,
            888,
            "Mon Jul 28 12:00:00 2026",
            receipt_path,
        ),
    ]


def test_provider_auth_recovery_preserves_quarantined_reaper_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authority = tmp_path / "authority"
    (authority / ".codex").mkdir(parents=True)
    receipt_path = tmp_path / "receipts" / "lease.json"
    receipt_path.parent.mkdir()
    payload = {
        "lease_id": "lease-id",
        "run_dir": str(tmp_path / "run"),
        "destination_path": str(tmp_path / "run" / "auth.json"),
        "baseline_sha256": "a" * 64,
        "pgid": 888,
        "leader_pid": 888,
        "leader_started_wall": "Mon Jul 28 12:00:00 2026",
    }
    reaper = object()
    reaper_started_wall = "Mon Jul 28 12:00:01 2026"
    quarantined: list[dict[str, object]] = []

    monkeypatch.setattr(
        isolation,
        "_load_recoverable_provider_auth_receipts",
        lambda **_kwargs: ([(receipt_path, payload, False)], 0),
    )
    monkeypatch.setattr(
        isolation,
        "defer_provider_auth_cleanup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            isolation.ProviderAuthHandoffQuarantined(
                "injected no-ACK child",
                receipt_path=receipt_path,
                reaper_process=reaper,
                reaper_started_wall=reaper_started_wall,
            )
        ),
    )

    def capture_quarantine(lease, **kwargs):
        quarantined.append(kwargs)
        isolation._release_provider_auth_lock(lease._authority_lock_fd)
        lease._authority_lock_fd = None

    monkeypatch.setattr(
        isolation,
        "quarantine_provider_auth_lease",
        capture_quarantine,
    )

    result = isolation.recover_provider_auth_reapers(
        authority_home=authority,
        receipt_root=receipt_path.parent,
    )

    assert result == {"recovered": 0, "active": 1, "invalid": 0}
    assert quarantined[0]["reaper_process"] is reaper
    assert quarantined[0]["reaper_started_wall"] == reaper_started_wall


def test_provider_auth_recovery_never_signals_reused_quarantine_pid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authority = tmp_path / "authority"
    (authority / ".codex").mkdir(parents=True)
    receipt_path = tmp_path / "receipts" / "lease.json"
    receipt_path.parent.mkdir()
    payload = {
        "state": "quarantined",
        "custody_state": "quarantined",
        "lease_id": "lease-id",
        "run_dir": str(tmp_path / "run"),
        "destination_path": str(tmp_path / "run" / "auth.json"),
        "baseline_sha256": "a" * 64,
        "pgid": 888,
        "leader_pid": 888,
        "leader_started_wall": "Mon Jul 28 12:00:00 2026",
        "reaper_pid": 999,
        "reaper_started_wall": "Mon Jul 28 12:00:01 2026",
    }
    sent: list[tuple[int, int]] = []

    monkeypatch.setattr(
        isolation,
        "_load_recoverable_provider_auth_receipts",
        lambda **_kwargs: ([(receipt_path, payload, False)], 0),
    )
    monkeypatch.setattr(
        isolation,
        "_acquire_provider_auth_lock",
        lambda _fd: (_ for _ in ()).throw(
            isolation.IsolationUnavailable("provider auth is already leased")
        ),
    )
    monkeypatch.setattr(
        procutil,
        "check_identity",
        lambda _pid, _started_wall: procutil.IDENTITY_MISMATCH,
    )
    monkeypatch.setattr(
        isolation.termination.os,
        "kill",
        lambda pid, signum: sent.append((pid, signum)),
    )
    monkeypatch.setattr(isolation.time, "sleep", lambda _seconds: None)

    result = isolation.recover_provider_auth_reapers(
        authority_home=authority,
        receipt_root=receipt_path.parent,
    )

    assert result == {"recovered": 0, "active": 1, "invalid": 0}
    assert sent == []
    assert not (receipt_path.parent / "termination_intents.jsonl").exists()


def test_provider_auth_recovery_is_idempotent_after_unlink_crash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authority = tmp_path / "authority"
    auth = authority / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, mode=0o700)
    auth.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    auth.chmod(0o600)
    run_dir = tmp_path / "run"
    (run_dir / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(run_dir / "home"),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    lease = isolation.materialize_provider_auth(
        prepared,
        provider_id="codex-cli",
        credential_home=authority,
    )
    assert lease is not None
    phases: list[str] = []

    def crash_before_phase_commit(phase: str) -> None:
        if phase == "destination_unlinked":
            raise OSError("reaper crashed before phase receipt")
        phases.append(phase)

    first = lease.close(checkpoint=crash_before_phase_commit)
    assert first.ok is False
    assert phases == ["unlink_intent"]
    assert not Path(lease.destination_path).exists()
    isolation._release_provider_auth_lock(lease._authority_lock_fd)
    lease._authority_lock_fd = None

    receipts = tmp_path / "receipts"
    receipts.mkdir()
    receipt_path = receipts / "crashed.json"
    receipt_path.write_text(
        json.dumps({
            "schema_version": "provider-auth-reaper.v2",
            "state": "cleanup_started",
            "close_phase": "unlink_intent",
            "lease_id": lease.lease_id,
            "source_home": str(authority),
            "run_dir": str(run_dir),
            "destination_path": lease.destination_path,
            "baseline_sha256": lease.baseline_sha256,
            "pgid": 888,
            "leader_pid": 888,
            "leader_started_wall": "Mon Jul 28 12:00:00 2026",
        }),
        encoding="utf-8",
    )
    recovered_close: list[isolation.ProviderAuthCloseReceipt] = []

    def defer(recovered_lease, **_kwargs):
        recovered_close.append(recovered_lease.close())

    monkeypatch.setattr(isolation, "defer_provider_auth_cleanup", defer)

    recovery = isolation.recover_provider_auth_reapers(
        authority_home=authority,
        receipt_root=receipts,
    )

    assert recovery == {"recovered": 1, "active": 0, "invalid": 0}
    assert recovered_close[0].ok is True
    assert recovered_close[0].cleaned is True


def test_provider_auth_admission_fences_nonterminal_crashed_lease(
    tmp_path: Path,
    monkeypatch,
) -> None:
    authority = tmp_path / "authority"
    auth = authority / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, mode=0o700)
    auth.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    auth.chmod(0o600)
    old_run = tmp_path / "old-run"
    old_destination = old_run / "home" / ".codex" / "auth.json"
    old_destination.parent.mkdir(parents=True, mode=0o700)
    old_destination.write_bytes(auth.read_bytes())
    old_destination.chmod(0o600)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    receipt_path = receipts / "waiting.json"
    receipt_path.write_text(
        json.dumps({
            "schema_version": "provider-auth-reaper.v2",
            "state": "waiting_for_process_group",
            "lease_id": "old-lease",
            "source_home": str(authority),
            "run_dir": str(old_run),
            "destination_path": str(old_destination),
            "baseline_sha256": hashlib.sha256(auth.read_bytes()).hexdigest(),
            "pgid": 888,
            "leader_pid": 888,
            "leader_started_wall": "Mon Jul 28 12:00:00 2026",
        }),
        encoding="utf-8",
    )
    new_run = tmp_path / "new-run"
    (new_run / "home").mkdir(parents=True, mode=0o700)
    prepared = isolation.PreparedIsolation(
        profile_path=str(new_run / "sandbox.sb"),
        run_dir=str(new_run),
        synthetic_home=str(new_run / "home"),
        tmp_dir=str(new_run / "tmp"),
        pycache_dir=str(new_run / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    recovery_handoffs: list[str] = []

    def defer(lease, **_kwargs):
        recovery_handoffs.append(lease.lease_id)
        isolation._release_provider_auth_lock(lease._authority_lock_fd)
        lease._authority_lock_fd = None

    monkeypatch.setattr(isolation, "_provider_auth_reaper_root", lambda: receipts)
    monkeypatch.setattr(isolation, "defer_provider_auth_cleanup", defer)

    with pytest.raises(
        isolation.IsolationUnavailable,
        match="previous provider auth lease recovery is in progress",
    ):
        isolation.materialize_provider_auth(
            prepared,
            provider_id="codex-cli",
            credential_home=authority,
        )

    assert recovery_handoffs == ["old-lease"]
    assert not (new_run / "home" / ".codex" / "auth.json").exists()


def test_provider_auth_forged_cleaned_receipt_fails_closed(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority"
    auth = authority / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, mode=0o700)
    auth.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    auth.chmod(0o600)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "forged.json").write_text(
        '{"state":"cleaned"}',
        encoding="utf-8",
    )

    result = isolation.recover_provider_auth_reapers(
        authority_home=authority,
        receipt_root=receipts,
    )

    assert result == {"recovered": 0, "active": 0, "invalid": 1}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("leader_started_wall", None),
        ("reaper_started_wall", None),
        ("handoff_parent_started_wall", None),
    ],
)
def test_provider_auth_quarantine_receipt_rejects_null_process_identity(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    authority = tmp_path / "authority"
    auth = authority / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, mode=0o700)
    auth.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"a",'
        '"refresh_token":"r","id_token":"i","account_id":"account"}}',
        encoding="utf-8",
    )
    auth.chmod(0o600)
    run_dir = tmp_path / "old-run"
    destination = run_dir / "home" / ".codex" / "auth.json"
    destination.parent.mkdir(parents=True, mode=0o700)
    destination.write_bytes(auth.read_bytes())
    destination.chmod(0o600)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    payload = {
        "schema_version": "provider-auth-reaper.v2",
        "state": "quarantined",
        "lease_id": "old-lease",
        "source_home": str(authority),
        "run_dir": str(run_dir),
        "destination_path": str(destination),
        "baseline_sha256": hashlib.sha256(auth.read_bytes()).hexdigest(),
        "pgid": 888,
        "leader_pid": 888,
        "leader_started_wall": "Mon Jul 28 12:00:00 2026",
        "reaper_pid": 999,
        "reaper_started_wall": "Mon Jul 28 12:00:01 2026",
        "handoff_parent_pid": 777,
        "handoff_parent_started_wall": "Mon Jul 28 11:59:59 2026",
    }
    payload[field] = value
    (receipts / "quarantined.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    result = isolation.recover_provider_auth_reapers(
        authority_home=authority,
        receipt_root=receipts,
    )

    assert result == {"recovered": 0, "active": 0, "invalid": 1}


def test_codex_auth_materialization_rejects_symlink_destination(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "id_token": "id",
                "account_id": "account",
            },
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)
    run_dir = tmp_path / "run"
    synthetic_home = run_dir / "home"
    target = tmp_path / "credential-leak-target"
    for path in (run_dir, synthetic_home, target):
        path.mkdir(mode=0o700)
    (synthetic_home / ".codex").symlink_to(target, target_is_directory=True)
    prepared = isolation.PreparedIsolation(
        profile_path=str(run_dir / "sandbox.sb"),
        run_dir=str(run_dir),
        synthetic_home=str(synthetic_home),
        tmp_dir=str(run_dir / "tmp"),
        pycache_dir=str(run_dir / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )

    with pytest.raises(isolation.IsolationUnavailable, match="symlink"):
        isolation.materialize_provider_auth(
            prepared,
            provider_id="codex-cli",
            credential_home=source_home,
        )

    assert not (target / "auth.json").exists()


def test_codex_auth_materialization_rejects_api_key_and_partial_receipt(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source-home"
    source = source_home / ".codex" / "auth.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({
            "OPENAI_API_KEY": "metered-key",
            "tokens": {"access_token": "oauth"},
        }),
        encoding="utf-8",
    )
    source.chmod(0o600)
    partial = {
        "profile_path": str(tmp_path / "sandbox.sb"),
        "run_dir": str(tmp_path / "run"),
        "synthetic_home": str(tmp_path / "run" / "home"),
    }

    with pytest.raises(isolation.IsolationUnavailable, match="missing fields"):
        isolation.materialize_provider_auth(
            partial,
            provider_id="codex-cli",
            credential_home=source_home,
        )

    prepared = isolation.PreparedIsolation(
        profile_path=str(tmp_path / "sandbox.sb"),
        run_dir=str(tmp_path / "run"),
        synthetic_home=str(tmp_path / "run" / "home"),
        tmp_dir=str(tmp_path / "run" / "tmp"),
        pycache_dir=str(tmp_path / "run" / "pycache"),
        workspace=str(tmp_path / "workspace"),
        canonical_root=str(tmp_path / "repo"),
    )
    with pytest.raises(isolation.IsolationUnavailable, match="API key"):
        isolation.materialize_provider_auth(
            prepared,
            provider_id="codex-cli",
            credential_home=source_home,
        )


def test_isolated_claude_scrubs_before_authorize_and_spawn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _stub_worker_custody(monkeypatch)

    workdir = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    for path in (workdir, run_dir / "home", run_dir / "tmp", run_dir / "pycache"):
        path.mkdir(parents=True)
    profile = run_dir / "sandbox.sb"
    profile.write_text("(version 1)\n", encoding="utf-8")
    isolated_workspace = {
        "path": str(workdir),
        "isolation_profile_path": str(profile),
        "isolation_run_dir": str(run_dir),
        "isolation_synthetic_home": str(run_dir / "home"),
        "isolation_tmp_dir": str(run_dir / "tmp"),
        "isolation_pycache_dir": str(run_dir / "pycache"),
        "isolation_workspace": str(workdir),
        "isolation_canonical_root": str(tmp_path / "repo"),
    }
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.setenv(key, "metered-secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "subscription-oauth")
    authorized: list[dict[str, str]] = []
    spawned: list[dict[str, str]] = []

    def authorize(**kwargs):
        authorized.append(dict(kwargs["environment"]))
        return SimpleNamespace(
            resolved_executable=kwargs["executable_path"],
            settings_path="/tmp/pinned-claude-settings.json",
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "claude-cli",
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
        )

    class ExitedProc:
        pid = 123

    monkeypatch.setattr(worker, "authorize_provider_spawn", authorize)
    monkeypatch.setattr(worker, "verify_spawn_receipt", lambda _receipt: None)
    monkeypatch.setattr(
        worker,
        "_spawn",
        lambda **kwargs: spawned.append({
            "env": dict(kwargs["env"]),
            "argv": list(kwargs["argv"]),
        }) or ExitedProc(),
    )
    monkeypatch.setattr(worker, "_wait_with_fatal_probe", lambda *_a, **_kw: ("exited", 0))
    monkeypatch.setattr(worker.state, "begin_attempt", lambda **_kw: object())
    monkeypatch.setattr(worker.state, "attach_process", lambda **_kw: None)
    monkeypatch.setattr(worker.state, "update_started_wall", lambda **_kw: None)
    monkeypatch.setattr(worker.state, "mark_job_phase", lambda **_kw: True)
    monkeypatch.setattr(worker.procutil, "get_process_start_wall", lambda _pid: "start")
    monkeypatch.setattr(worker.fire_manifest, "open_manifest", lambda *_a, **_kw: None)

    worker._run_one_attempt(
        prompt_text="prompt",
        model=worker.OPUS_MODEL,
        timeout_s=10,
        log_path=tmp_path / "worker.log",
        attempt=1,
        schedule_id="hourly_dispatch",
        state_path=tmp_path / "state.json",
        job_id="job-provider-order",
        slot_id="slot-1",
        workdir=workdir,
        isolated_workspace=isolated_workspace,
    )

    assert len(authorized) == len(spawned) == 1
    for env in (authorized[0], spawned[0]["env"]):
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "subscription-oauth"
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
            assert key not in env
    assert spawned[0]["argv"][:4] == [
        str(isolation.SANDBOX_EXEC),
        "-f",
        str(profile),
        worker.CLAUDE_BIN,
    ]


def test_workspace_merge_gate_rejects_canonical_only_paths(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    repo = tmp_path
    wt_info = _ws_allocate(repo, job_id="d" * 32, slot="slot-1")
    assert wt_info is not None
    wt = Path(wt_info["path"])
    (wt / "storage" / "ops").mkdir(parents=True, exist_ok=True)
    (wt / "storage" / "ops" / "forbidden.json").write_text("{}\n", encoding="utf-8")

    result = workspace._run_merge_gate(repo_root=repo, workspace=wt_info)

    assert result["verdict"] == "red"
    assert result["reason"] == "canonical_path_denied"
    assert result["denied"] == ["storage/ops/forbidden.json"]


def test_workspace_merge_gate_rejects_path_outside_task_contract(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    ws = _ws_allocate(
        tmp_path,
        job_id="9" * 32,
        task_binding={
            "task_id": "exact-task",
            "claim_session_id": "exact-claim",
            "write_intent": "repo_patch",
            "declared_output_paths": ["scripts/dispatch_supervisor"],
            "post_merge_actions": [],
        },
    )
    assert ws is not None
    wt = Path(ws["path"])
    (wt / "docs").mkdir()
    (wt / "docs" / "foreign.md").write_text("foreign\n", encoding="utf-8")

    result = workspace._run_merge_gate(repo_root=tmp_path, workspace=ws)

    assert result["verdict"] == "red"
    assert result["reason"] == "undeclared_output_path"
    assert result["undeclared"] == ["docs/foreign.md"]


def test_machine_finalizer_commits_only_declared_workspace_output(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    ws = _ws_allocate(
        tmp_path,
        task_binding={
            "task_id": "machine-commit",
            "claim_session_id": "machine-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["change.py"],
            "post_merge_actions": [],
        },
    )
    assert ws is not None
    wt = Path(ws["path"])
    (wt / "change.py").write_text("MACHINE = True\n", encoding="utf-8")

    committed = workspace._commit_declared_workspace_output(
        repo_root=tmp_path, workspace=ws
    )

    assert committed["ok"] is True
    assert committed["changed"] == ["change.py"]
    assert subprocess.run(
        ["git", "-C", str(wt), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout == ""
    assert subprocess.run(
        ["git", "-C", str(wt), "show", "HEAD:change.py"],
        check=True, capture_output=True, text=True,
    ).stdout == "MACHINE = True\n"


def test_workspace_changed_path_probe_failure_is_gate_red(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    ws = _ws_allocate(tmp_path)
    assert ws is not None

    def failed_runner(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 1, "", "probe failed")

    result = workspace._run_merge_gate(
        repo_root=tmp_path, workspace=ws, runner=failed_runner
    )

    assert result["verdict"] == "red"
    assert result["reason"] == "changed_path_probe_failed"


def test_workspace_gate_pass_is_invalid_when_candidate_head_drifts(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    repo = tmp_path
    ws = _ws_allocate(repo, job_id="e" * 32, slot="slot-1")
    assert ws is not None
    wt = Path(ws["path"])
    (wt / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "candidate.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"], check=True,
    )
    merge_calls: list[dict] = []

    def drifting_gate(**_kwargs):
        (wt / "candidate.py").write_text("VALUE = 2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(wt), "add", "candidate.py"], check=True)
        subprocess.run(
            ["git", "-C", str(wt), "commit", "-qm", "post-gate drift"],
            check=True,
        )
        return {"verdict": "green", "rc": 0, "targets": [],
                "duration_s": 0.1}

    result = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        gate_fn=drifting_gate,
        merge_fn=lambda **kwargs: merge_calls.append(kwargs) or {"ok": True},
    )

    assert result["disposition"] == "remediation_opened"
    assert result["reason"] == "candidate_head_drift"
    assert merge_calls == []


def test_workspace_main_advance_rebases_and_regates_before_integration(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    repo = tmp_path
    ws = _ws_allocate(repo, job_id="f" * 32, slot="slot-1")
    assert ws is not None
    wt = Path(ws["path"])
    (wt / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "candidate.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"], check=True,
    )
    gate_calls: list[str] = []

    def advancing_gate(**_kwargs):
        gate_calls.append(subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip())
        if len(gate_calls) == 1:
            (repo / "other.txt").write_text("concurrent main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "other.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "advance main"],
                check=True,
            )
        return {"verdict": "green", "rc": 0, "targets": [],
                "duration_s": 0.1}

    def fenced_merge(**kwargs):
        assert kwargs["expected_main_sha"] == subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "main"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        assert kwargs["expected_candidate_sha"] == subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(repo), "merge", "--ff-only", ws["branch"]],
            check=True, capture_output=True,
        )
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    result = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        gate_fn=advancing_gate, merge_fn=fenced_merge,
    )

    assert result["disposition"] == "merged"
    assert len(gate_calls) == 2
    assert gate_calls[0] != gate_calls[1]
    gate_receipts = [
        event for event in _ws_receipt_events(repo)
        if event["event"] == "gate_passed"
    ]
    assert gate_receipts[-1]["gate_attempt"] == 2
    assert gate_receipts[-1]["candidate_head_sha"] == gate_calls[-1]


def test_workspace_gate_to_merge_cas_loss_rebuilds_and_regates(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    repo = tmp_path
    ws = _ws_allocate(repo, job_id="4" * 32, slot="slot-1")
    assert ws is not None
    wt = Path(ws["path"])
    (wt / "candidate.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(wt), "add", "candidate.py"], check=True)
    subprocess.run(
        ["git", "-C", str(wt), "commit", "-qm", "candidate"], check=True,
    )
    gated: list[str] = []
    merge_calls = 0

    def green_gate(**_kwargs):
        gated.append(subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip())
        return {"verdict": "green", "rc": 0, "targets": [], "duration_s": 0.1}

    def cas_then_merge(**_kwargs):
        nonlocal merge_calls
        merge_calls += 1
        if merge_calls == 1:
            (repo / "concurrent.txt").write_text("advance\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "concurrent.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "concurrent main"],
                check=True,
            )
            return {
                "ok": False,
                "reason": "integration_cas_lost",
                "output_tail": "main advanced after gate receipt",
            }
        subprocess.run(
            ["git", "-C", str(repo), "merge", "--ff-only", ws["branch"]],
            check=True, capture_output=True,
        )
        return {"ok": True, "reason": "merged", "output_tail": ""}

    result = workspace.finalize_workspace(
        repo_root=repo,
        workspace=ws,
        worker_outcome="success",
        gate_fn=green_gate,
        merge_fn=cas_then_merge,
    )

    assert result["disposition"] == "merged"
    assert merge_calls == 2
    assert len(gated) == 2
    assert gated[0] != gated[1]
    events = _ws_receipt_events(repo)
    assert any(event["event"] == "integration_cas_retry" for event in events)
    gate_events = [event for event in events if event["event"] == "gate_passed"]
    assert gate_events[-1]["candidate_head_sha"] == gated[-1]


def test_workspace_integrator_child_inherits_the_single_writer_lease(
    tmp_path: Path,
) -> None:
    _git_init_repo(tmp_path)
    repo = tmp_path
    ws = _ws_allocate(repo, job_id="3" * 32, slot="slot-1")
    assert ws is not None
    script = repo / workspace.MERGE_SCRIPT_RELPATH
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)
    main_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "main"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    candidate_sha = subprocess.run(
        ["git", "-C", ws["path"], "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    child_calls: list[dict] = []

    def runner(argv, **kwargs):
        if argv[0] == "/bin/bash":
            child_calls.append(kwargs)
            for fd in kwargs["pass_fds"]:
                os.fstat(fd)
            assert kwargs["env"]["VOLPRED_GIT_WRITER_LOCK_TOKEN"]
            assert kwargs["env"]["VOLPRED_GIT_WRITER_LOCK_FD"]
            return subprocess.CompletedProcess(argv, 1, "", "expected stop")
        return subprocess.run(argv, **kwargs)

    result = workspace._run_merge_script(
        repo_root=repo,
        workspace=ws,
        runner=runner,
        expected_main_sha=main_sha,
        expected_candidate_sha=candidate_sha,
    )

    assert result["reason"] == "merge_failed"
    assert len(child_calls) == 1


# -- Issue #44: PHASE-Z baseline guessing retired for every cohort ------------
# Issue #43 made all automated mutating lanes isolated-or-requeued. A legacy
# token flag can no longer authorize canonical non-machine bytes by timing.
# Machine-state churn keeps its explicit namespace + byte-identity adoption.


def test_phase_z_isolated_cohort_demotes_non_machine_owned(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    before = _git_head_count(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("residue\n", encoding="utf-8")
    (tmp_path / "storage" / "ops").mkdir(parents=True)
    (tmp_path / "storage" / "ops" / "some_state.json").write_text("{}\n", encoding="utf-8")
    alerts_seen: list[dict] = []
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        isolated_cohort=True,
        alert_fn=lambda **kwargs: alerts_seen.append(kwargs) or {},
    )
    # machine state still adopted; the doc path is demoted, not committed
    assert out["committed"] is True
    assert out["owned"] == []
    assert out["churn"] == ["storage/ops/some_state.json"]
    assert out["isolation_residue"] == ["docs/note.md"]
    assert _git_head_count(tmp_path) == before + 1
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "docs/note.md"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == ""  # never entered history
    assert (tmp_path / "docs" / "note.md").exists()  # and never deleted
    assert not any("canonical checkout 殘留" in a.get("title", "") for a in alerts_seen), (
        "canonical residue is tracked, not warned before it is actionable"
    )
    assert out["foreign_ownership"]["risk"] == ["docs/note.md"]


def test_phase_z_commit_carries_durable_generation_trailer(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    (tmp_path / "storage" / "ops").mkdir(parents=True)
    (tmp_path / "storage" / "ops" / "some_state.json").write_text(
        "{}\n", encoding="utf-8",
    )

    out = phase_z.run_phase_z(
        repo_root=tmp_path,
        now_hhmm="16:07",
        pre_fire_dirty=set(),
        closeout_generation="generation-terminal-trailer",
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is True
    assert out["commit_sha"]
    body = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", "--format=%B"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert (
        "VolPred-Phase-Z-Generation: generation-terminal-trailer" in body
    )


def test_phase_z_head_adoption_with_downstream_failure_is_not_terminal(
    tmp_path: Path, monkeypatch,
) -> None:
    _git_init_repo(tmp_path)
    machine = tmp_path / "storage" / "ops" / "some_state.json"
    machine.parent.mkdir(parents=True)
    machine.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        phase_z,
        "_refresh_shared_index_cas",
        lambda *_args, **_kwargs: {
            "ok": False, "reason": "injected_refresh_failure",
        },
    )

    out = phase_z.run_phase_z(
        repo_root=tmp_path,
        now_hhmm="16:07",
        pre_fire_dirty=set(),
        closeout_generation="generation-refresh-failed",
        alert_fn=lambda **_kwargs: {},
    )

    assert out["committed"] is False
    assert out["head_committed"] is True
    assert out["reason"] == "committed_recovery_index_failed"
    assert out["commit_sha"]
    assert scheduler._phase_z_terminal(out) is False


def test_committed_closeout_recovery_finishes_every_downstream_handoff(
    tmp_path: Path, monkeypatch,
) -> None:
    _git_init_repo(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "recovered.py").write_text(
        "VALUE = 1\n", encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "scripts/recovered.py"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        [
            "git", "-C", str(tmp_path), "commit",
            "-m", "phase-z recovered commit",
            "-m", (
                "VolPred-Phase-Z-Generation: generation-downstream\n"
                'VolPred-Phase-Z-Owned-Paths: ["scripts/recovered.py"]'
            ),
        ],
        capture_output=True, text=True, check=True,
    )
    commit_sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    events: list[str] = []
    monkeypatch.setattr(
        phase_z, "_refresh_shared_index_cas",
        lambda *_args, **_kwargs: events.append("index") or {
            "ok": True, "refreshed": ["scripts/recovered.py"], "preserved": [],
        },
    )
    monkeypatch.setattr(
        phase_z, "_consume_pre_fire_snapshot",
        lambda *_args, **_kwargs: events.append("snapshot"),
    )
    monkeypatch.setattr(
        phase_z, "backfill_ci_repair_commit",
        lambda **_kwargs: events.append("task_commit") or ["task-a"],
    )
    monkeypatch.setattr(
        phase_z, "pending_issue_task_ids_for_owners",
        lambda **_kwargs: events.append("issue_lookup") or ["task-a"],
    )
    monkeypatch.setattr(
        phase_z, "settle_completed_task_issues",
        lambda **_kwargs: events.append("issue_settlement")
        or [{"task_id": "task-a", "issue": 42}],
    )
    monkeypatch.setattr(
        phase_z, "_post_commit_test_gate",
        lambda *_args, **_kwargs: events.append("test_gate") or {
            "passed": True, "reason": "green",
        },
    )

    out = phase_z.recover_committed_closeout(
        repo_root=tmp_path,
        commit_sha=commit_sha,
        generation_id="generation-downstream",
        claim_owners={"codex-vscode"},
    )

    assert out["committed"] is True
    assert events == [
        "index",
        "snapshot",
        "task_commit",
        "issue_lookup",
        "issue_settlement",
        "test_gate",
    ]
    assert out["ci_repair_tasks_backfilled"] == ["task-a"]
    assert out["issue_tasks_closed"] == [{"task_id": "task-a", "issue": 42}]

    monkeypatch.setattr(
        phase_z, "settle_completed_task_issues", lambda **_kwargs: [],
    )
    incomplete = phase_z.recover_committed_closeout(
        repo_root=tmp_path,
        commit_sha=commit_sha,
        generation_id="generation-downstream",
        claim_owners={"codex-vscode"},
    )
    assert incomplete["committed"] is False
    assert incomplete["head_committed"] is True
    assert (
        incomplete["reason"]
        == "committed_recovery_issue_readback_incomplete"
    )
    assert incomplete["missing_task_ids"] == ["task-a"]


def test_committed_machine_churn_recovery_never_settles_worker_claim(
    tmp_path: Path, monkeypatch,
) -> None:
    _git_init_repo(tmp_path)
    machine = tmp_path / "storage" / "ops" / "state.json"
    machine.parent.mkdir(parents=True)
    machine.write_text("{}\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "storage/ops/state.json"],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        [
            "git", "-C", str(tmp_path), "commit",
            "-m", "phase-z machine churn",
            "-m", (
                "VolPred-Phase-Z-Generation: generation-machine\n"
                "VolPred-Phase-Z-Owned-Paths: []"
            ),
        ],
        capture_output=True, text=True, check=True,
    )
    commit_sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    monkeypatch.setattr(
        phase_z, "_refresh_shared_index_cas",
        lambda *_args, **_kwargs: {"ok": True, "refreshed": [], "preserved": []},
    )
    monkeypatch.setattr(phase_z, "_consume_pre_fire_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        phase_z,
        "backfill_ci_repair_commit",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("machine churn must not bind a worker claim")
        ),
    )
    monkeypatch.setattr(
        phase_z,
        "settle_completed_task_issues",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("machine churn must not close a worker issue")
        ),
    )
    monkeypatch.setattr(
        phase_z, "_post_commit_test_gate",
        lambda *_args, **_kwargs: {"passed": None, "reason": "skipped_non_code"},
    )

    out = phase_z.recover_committed_closeout(
        repo_root=tmp_path,
        commit_sha=commit_sha,
        generation_id="generation-machine",
        claim_owners={"hourly-slot-1-job-a"},
    )

    assert out["committed"] is True
    assert out["ci_repair_tasks_backfilled"] == []
    assert out["issue_tasks_closed"] == []


def test_phase_z_isolated_cohort_all_residue_is_terminal(tmp_path: Path) -> None:
    """All-residue outcome must land on a TERMINAL reason (nothing_owned) so
    the scheduler releases the drain token -- no livelock behind the demotion."""
    _git_init_repo(tmp_path)
    before = _git_head_count(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("residue\n", encoding="utf-8")
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        isolated_cohort=True, alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "nothing_owned"
    assert out["isolation_residue"] == ["docs/note.md"]
    assert scheduler._phase_z_terminal(out) is True
    assert _git_head_count(tmp_path) == before
    assert (tmp_path / "docs" / "note.md").exists()


def test_phase_z_unisolated_token_cannot_restore_legacy_adoption(tmp_path: Path) -> None:
    """A stale/unisolated token is an isolation breach, not commit authority."""
    _git_init_repo(tmp_path)
    before = _git_head_count(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text("agent output\n", encoding="utf-8")
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is False
    assert out["reason"] == "nothing_owned"
    assert out["isolation_residue"] == ["docs/note.md"]
    assert _git_head_count(tmp_path) == before
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "docs/note.md"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == ""
    assert (tmp_path / "docs" / "note.md").read_text() == "agent output\n"


def test_record_completion_stamps_isolated_on_pending(tmp_path: Path) -> None:
    state_path = _tmp_state(tmp_path)
    # isolated fire
    lease = state.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                               log_path="/tmp/a.log", path=state_path)
    state.attach_process(job_id=lease.job_id, expected_attempt=1, pid=1, pgid=1,
                         started_wall=None, path=state_path)
    state.attach_workspace(job_id=lease.job_id, workspace={
        "name": "dispatch-slot-1-aaaaaaaa", "path": "/tmp/wt", "branch": "b",
        "base_sha": "s", "lanes": ["platform_ops"],
        "created_at": "2026-07-20T00:00:00+00:00", "setup_s": 1.0,
    }, path=state_path)
    state.record_completion(job_id=lease.job_id, exit_code=0, outcome="success",
                            final_model="opus", path=state_path)
    pending = state.read_state(state_path)["phase_z_pending"]
    assert [item["isolated"] for item in pending] == [True]
    state.finish_phase_z(cohort_id=lease.cohort_id, path=state_path)
    # unisolated fire
    lease2 = state.reserve_fire(schedule_id="hourly_dispatch", attempt=1, model="opus",
                                log_path="/tmp/b.log", path=state_path)
    state.attach_process(job_id=lease2.job_id, expected_attempt=1, pid=2, pgid=2,
                         started_wall=None, path=state_path)
    state.record_completion(job_id=lease2.job_id, exit_code=0, outcome="success",
                            final_model="opus", path=state_path)
    pending2 = state.read_state(state_path)["phase_z_pending"]
    assert [item["isolated"] for item in pending2] == [False]


def _seed_pending_drain(state_path: Path, isolated_flags: list[bool]) -> None:
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [
            {"job_id": f"job{i}", "cohort_id": f"cohort{i}", "slot_id": i + 1,
             "created_at": "2026-07-20T00:00:00+00:00", "isolated": flag,
             "fire_lifecycle": _fire_lifecycle()}
            for i, flag in enumerate(isolated_flags)
        ]


def _fire_lifecycle(generation_id: str = "generation-a") -> dict:
    return {
        "generation_id": generation_id,
        "captured_at": "2026-07-27T00:00:00+00:00",
        "pre_fire_dirty": ["already-dirty.txt"],
    }


@pytest.mark.parametrize("restart_point", ["pre_fire", "worker_running", "worker_complete"])
def test_fire_lifecycle_survives_process_restart_at_every_closeout_boundary(
    tmp_path: Path, restart_point: str,
) -> None:
    """Issue #42: process memory must never be the PHASE-Z baseline owner."""
    state_path = _tmp_state(tmp_path)
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/worker.log", path=state_path,
    )
    assert state.attach_fire_lifecycle(
        job_id=lease.job_id, lifecycle=_fire_lifecycle(), path=state_path,
    )

    if restart_point in {"worker_running", "worker_complete"}:
        state.attach_process(
            job_id=lease.job_id, expected_attempt=1, pid=123, pgid=123,
            started_wall="Mon Jul 27 00:00:00 2026", path=state_path,
        )
    if restart_point == "worker_complete":
        state.record_completion(
            job_id=lease.job_id, expected_attempt=1, expected_pid=123,
            exit_code=0, outcome="success", final_model="opus", path=state_path,
        )

    # A new interpreter would reconstruct all authority from this file.
    restarted = state.read_state(state_path)
    records = (
        restarted["phase_z_pending"]
        if restart_point == "worker_complete"
        else restarted["current_jobs"]
    )
    assert records[0]["fire_lifecycle"] == _fire_lifecycle()


def test_restart_closeout_uses_matching_durable_generation(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{
            "job_id": "job-a", "cohort_id": "cohort-a", "slot_id": 1,
            "created_at": "2026-07-27T00:00:01+00:00", "isolated": False,
            "fire_lifecycle": _fire_lifecycle(),
        }]
    captured: list[dict] = []
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: captured.append(kwargs)
        or {"committed": False, "reason": "clean"},
    )
    scheduler._PHASE_Z_LOCK = None

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path,
    ))

    assert result["action"] == "phase_z_recovered"
    assert captured[0]["pre_fire_dirty"] == {"already-dirty.txt"}
    assert state.read_state(state_path)["phase_z_pending"] == []


def test_background_tick_acks_while_phase_z_closeout_runs_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow closeout must not turn every Operations Core tick into timeout."""
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{
            "job_id": "job-a", "cohort_id": "cohort-a", "slot_id": 1,
            "created_at": "2026-07-27T00:00:01+00:00", "isolated": False,
            "fire_lifecycle": _fire_lifecycle(),
        }]
    closeout_calls = 0

    def slow_closeout(**_kwargs):
        nonlocal closeout_calls
        closeout_calls += 1
        time.sleep(0.3)
        return {"committed": False, "reason": "clean"}

    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", slow_closeout)
    monkeypatch.setattr(scheduler, "_PHASE_Z_LOCK", None)
    monkeypatch.setattr(
        scheduler, "_ACTIVE_PHASE_Z_RECOVERY_TASK", None, raising=False
    )

    async def scenario() -> tuple[dict, dict, float]:
        started = time.monotonic()
        first = await scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *",
            prompt_path=tmp_path / "prompt.md",
            log_path=tmp_path / "worker.log",
            dry_run=False, repo_root=tmp_path, background=True,
        )
        elapsed = time.monotonic() - started
        second = await scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *",
            prompt_path=tmp_path / "prompt.md",
            log_path=tmp_path / "worker.log",
            dry_run=False, repo_root=tmp_path, background=True,
        )
        recovery = scheduler._ACTIVE_PHASE_Z_RECOVERY_TASK
        assert recovery is not None
        await recovery
        return first, second, elapsed

    first, second, elapsed = asyncio.run(scenario())

    assert elapsed < 0.15
    assert first["action"] == "phase_z_recovery_started"
    assert second == {
        "action": "skip",
        "reason": "phase_z_recovery_in_progress",
        "phase_z_pending": 1,
    }
    assert closeout_calls == 1
    assert state.read_state(state_path)["phase_z_pending"] == []


def test_background_closeout_exception_alert_does_not_block_next_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{
            "job_id": "job-a", "cohort_id": "cohort-a", "slot_id": 1,
            "created_at": "2026-07-27T00:00:01+00:00", "isolated": False,
            "fire_lifecycle": _fire_lifecycle(),
        }]
    closeout_calls = 0

    def flaky_closeout(**_kwargs):
        nonlocal closeout_calls
        closeout_calls += 1
        if closeout_calls == 1:
            raise RuntimeError("injected closeout crash")
        return {"committed": False, "reason": "clean"}

    alert_started = False

    def slow_alert(*_args, **_kwargs):
        nonlocal alert_started
        alert_started = True
        time.sleep(0.3)
        return True

    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", flaky_closeout)
    monkeypatch.setattr(scheduler.alerts, "send_loop_crash", slow_alert)
    monkeypatch.setattr(scheduler, "_PHASE_Z_LOCK", None)
    monkeypatch.setattr(scheduler, "_ACTIVE_PHASE_Z_RECOVERY_TASK", None)
    monkeypatch.setattr(scheduler, "_BACKGROUND_ALERT_TASKS", set())

    async def scenario() -> tuple[dict, float]:
        first = await scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *",
            prompt_path=tmp_path / "prompt.md",
            log_path=tmp_path / "worker.log",
            dry_run=False, repo_root=tmp_path, background=True,
        )
        assert first["action"] == "phase_z_recovery_started"
        failed = scheduler._ACTIVE_PHASE_Z_RECOVERY_TASK
        assert failed is not None
        with pytest.raises(RuntimeError, match="injected closeout crash"):
            await failed
        await asyncio.sleep(0)

        started = time.monotonic()
        second = await scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *",
            prompt_path=tmp_path / "prompt.md",
            log_path=tmp_path / "worker.log",
            dry_run=False, repo_root=tmp_path, background=True,
        )
        elapsed = time.monotonic() - started
        recovered = scheduler._ACTIVE_PHASE_Z_RECOVERY_TASK
        assert recovered is not None
        await recovered
        await asyncio.gather(*scheduler._BACKGROUND_ALERT_TASKS)
        return second, elapsed

    second, elapsed = asyncio.run(scenario())

    assert elapsed < 0.15
    assert second["action"] == "phase_z_recovery_started"
    assert closeout_calls == 2
    assert alert_started is True
    assert state.read_state(state_path)["phase_z_pending"] == []


def test_running_worker_restart_orphan_cleanup_preserves_generation_to_recovery(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/worker.log", path=state_path,
    )
    state.attach_fire_lifecycle(
        job_id=lease.job_id, lifecycle=_fire_lifecycle(), path=state_path,
    )
    state.attach_process(
        job_id=lease.job_id, expected_attempt=1, pid=123, pgid=123,
        started_wall="Mon Jul 27 00:00:00 2026", path=state_path,
    )

    # This is the actual supervisor restart-orphan transition, distinct from
    # normal worker record_completion().
    orphan = state.mark_restart_orphans_pending(state_path)[0]
    state.append_completion_entry(
        orphan, exit_code=-9, outcome="killed_supervisor_restart",
        final_model="opus", path=state_path, mark_cleanup_recorded=True,
    )
    assert state.finalize_restart_orphan_cleanup(
        state_path, job_id=lease.job_id,
    )
    pending = state.read_state(state_path)["phase_z_pending"]
    assert pending[0]["fire_lifecycle"] == _fire_lifecycle()

    captured: list[dict] = []
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: captured.append(kwargs)
        or {"committed": False, "reason": "clean"},
    )
    scheduler._PHASE_Z_LOCK = None
    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path,
    ))

    assert result["action"] == "phase_z_recovered"
    assert captured[0]["pre_fire_dirty"] == {"already-dirty.txt"}


def test_scheduler_binds_guard_generation_before_worker_and_closes_with_it(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    schedules = tmp_path / "schedules.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{
            "id": "volpred-dispatch-supervisor", "max_slots": 1,
            "writer_isolation": {"mode": "off"},
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        scheduler.phase_z, "recover_failed_closeout",
        lambda **_kwargs: {"committed": False, "reason": "no_failed_closeout"},
    )
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": True, "reason": "ok", "dirty_at_fire_start": 1,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    observed_worker_lifecycle: list[dict] = []

    def fake_worker(**kwargs):
        live = state.read_state(kwargs["state_path"])["current_jobs"][0]
        observed_worker_lifecycle.append(live["fire_lifecycle"])
        state.record_completion(
            job_id=kwargs["job_id"], expected_attempt=1,
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            path=kwargs["state_path"],
        )
        return _ok_worker()

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_worker)
    captured: list[dict] = []
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **kwargs: captured.append(kwargs)
        or {"committed": False, "reason": "clean"},
    )
    scheduler._PHASE_Z_LOCK = None

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=prompt_path, log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path, schedules_path=schedules,
    ))

    assert result["action"] == "fired"
    assert observed_worker_lifecycle == [_fire_lifecycle()]
    assert captured[0]["pre_fire_dirty"] == {"already-dirty.txt"}


def test_in_process_fire_without_lifecycle_rejects_instead_of_reading_singleton(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    schedules = tmp_path / "schedules.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{
            "id": "volpred-dispatch-supervisor", "max_slots": 1,
            "writer_isolation": {"mode": "off"},
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        scheduler.phase_z, "recover_failed_closeout",
        lambda **_kwargs: {"committed": False, "reason": "no_failed_closeout"},
    )
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": False, "reason": "status_error", "dirty_at_fire_start": -1,
        },
    )

    def fake_worker(**kwargs):
        state.record_completion(
            job_id=kwargs["job_id"], expected_attempt=1,
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            path=kwargs["state_path"],
        )
        return _ok_worker()

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_worker)
    called = {"phase_z": 0}
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **_kwargs: called.__setitem__("phase_z", called["phase_z"] + 1),
    )
    monkeypatch.setattr(
        scheduler.phase_z, "_default_internal_alert",
        lambda **_kwargs: {"sent": True},
    )
    scheduler._PHASE_Z_LOCK = None

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=prompt_path, log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path, schedules_path=schedules,
    ))

    assert result["phase_z"]["reason"] == "missing_generation"
    assert result["phase_z"]["generation_rejected"] is True
    assert called["phase_z"] == 0
    rejected = state.read_state(state_path)["phase_z_rejections"]
    assert len(rejected) == 1
    assert rejected[0]["rejection_reason"] == "missing_generation"


def test_restart_never_executes_closeout_without_matching_generation(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [
            {"job_id": "job-a", "cohort_id": "cohort-a", "slot_id": 1,
             "created_at": "2026-07-27T00:00:01+00:00", "isolated": False,
             "fire_lifecycle": _fire_lifecycle("generation-a")},
            {"job_id": "job-b", "cohort_id": "cohort-a", "slot_id": 2,
             "created_at": "2026-07-27T00:00:02+00:00", "isolated": False,
             "fire_lifecycle": _fire_lifecycle("different-generation")},
        ]
    called = {"phase_z": 0}
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **_kwargs: called.__setitem__("phase_z", called["phase_z"] + 1),
    )
    alerts: list[dict] = []
    monkeypatch.setattr(
        scheduler.phase_z, "_default_internal_alert",
        lambda **kwargs: alerts.append(kwargs) or {"sent": True},
    )
    scheduler._PHASE_Z_LOCK = None

    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path,
    ))

    assert result["action"] == "phase_z_generation_rejected"
    assert called["phase_z"] == 0
    assert state.read_state(state_path)["phase_z_pending"] == []
    rejected = state.read_state(state_path)["phase_z_rejections"]
    assert {item["job_id"] for item in rejected} == {"job-a", "job-b"}
    assert {item["rejection_reason"] for item in rejected} == {"generation_mismatch"}
    assert alerts[0]["alert_key"] == "phase_z_generation_rejected"
    assert alerts[0]["fingerprint"] == [
        "phase_z_generation_rejected:generation_mismatch"
    ]


def test_closeout_failure_restart_reuses_same_generation_until_terminal(
    tmp_path: Path, monkeypatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{
            "job_id": "job-a", "cohort_id": "cohort-a", "slot_id": 1,
            "created_at": "2026-07-27T00:00:01+00:00", "isolated": False,
            "fire_lifecycle": _fire_lifecycle(),
        }]
    observed: list[set[str]] = []
    outcomes = iter([
        {"committed": False, "reason": "status_error"},
        {"committed": False, "reason": "clean"},
    ])

    def flaky_closeout(**kwargs):
        observed.append(kwargs["pre_fire_dirty"])
        return next(outcomes)

    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", flaky_closeout)
    scheduler._PHASE_Z_LOCK = None
    first = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path,
    ))
    assert first["action"] == "phase_z_recovery_pending"
    pending = state.read_state(state_path)["phase_z_pending"]
    assert pending[0]["fire_lifecycle"] == _fire_lifecycle()

    # A new event loop/process continues from state, not the first call frame.
    scheduler._PHASE_Z_LOCK = None
    second = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path,
    ))
    assert second["action"] == "phase_z_recovered"
    assert observed == [{"already-dirty.txt"}, {"already-dirty.txt"}]
    assert state.read_state(state_path)["phase_z_pending"] == []


def test_restart_after_terminal_commit_recovers_receipt_without_rerunning_closeout(
    tmp_path: Path, monkeypatch,
) -> None:
    """Issue #42: a crash after HEAD adoption but before token release must
    recover the exact generation from git history, not execute PHASE-Z twice."""
    _git_init_repo(tmp_path)
    state_path = _tmp_state(tmp_path)
    with state._locked_state(state_path) as (_fh, data):
        data["phase_z_pending"] = [{
            "job_id": "job-a", "cohort_id": "cohort-a", "slot_id": 1,
            "created_at": "2026-07-27T00:00:01+00:00", "isolated": False,
            "fire_lifecycle": _fire_lifecycle(),
        }]

    closeout_calls: list[dict] = []

    def commit_closeout(**kwargs):
        closeout_calls.append(kwargs)
        generation = kwargs["closeout_generation"]
        subprocess.run(
            [
                "git", "-C", str(tmp_path), "commit", "--allow-empty",
                "-m", "phase-z terminal canary",
                "-m", (
                    f"VolPred-Phase-Z-Generation: {generation}\n"
                    "VolPred-Phase-Z-Owned-Paths: []"
                ),
            ],
            capture_output=True, text=True, check=True,
        )
        commit_sha = subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return {
            "committed": True,
            "reason": "committed",
            "commit_sha": commit_sha,
        }

    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", commit_closeout)
    real_finish = state.finish_phase_z
    finish_calls = {"count": 0}

    def crash_once(**kwargs):
        finish_calls["count"] += 1
        if finish_calls["count"] == 1:
            raise SystemExit("injected crash after terminal commit")
        return real_finish(**kwargs)

    monkeypatch.setattr(scheduler.state, "finish_phase_z", crash_once)
    scheduler._PHASE_Z_LOCK = None
    with pytest.raises(SystemExit, match="injected crash"):
        asyncio.run(scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *",
            prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
            dry_run=False, repo_root=tmp_path,
        ))
    assert len(closeout_calls) == 1
    assert state.read_state(state_path)["phase_z_pending"]

    scheduler._PHASE_Z_LOCK = None
    recovered = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *",
        prompt_path=tmp_path / "prompt.md", log_path=tmp_path / "worker.log",
        dry_run=False, repo_root=tmp_path,
    ))

    assert recovered["action"] == "phase_z_receipt_recovered"
    assert recovered["generation_id"] == "generation-a"
    assert len(closeout_calls) == 1
    snap = state.read_state(state_path)
    assert snap["phase_z_pending"] == []
    assert snap["phase_z_receipts"][-1]["generation_id"] == "generation-a"
    assert snap["phase_z_receipts"][-1]["reason"] == "committed"


def test_scheduler_recovery_drain_passes_isolated_cohort(tmp_path: Path, monkeypatch) -> None:
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("p", encoding="utf-8")
    captured: list[dict] = []

    def spy_run_phase_z(**kwargs):
        captured.append(kwargs)
        return {"committed": False, "reason": "clean"}

    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", spy_run_phase_z)
    for flags, expected in (([True, True], True), ([True, False], False)):
        state_path = _tmp_state(tmp_path / f"case_{expected}")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        _seed_pending_drain(state_path, flags)
        scheduler._PHASE_Z_LOCK = None  # fresh loop per asyncio.run
        result = asyncio.run(scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
            log_path=tmp_path / "worker.log", dry_run=False, repo_root=tmp_path,
        ))
        assert result["action"] == "phase_z_recovered"
        assert captured[-1]["isolated_cohort"] is expected


def test_scheduler_fire_drain_passes_isolated_cohort(tmp_path: Path, monkeypatch) -> None:
    """End-to-end wiring: an isolated fire's completion stamps the pending
    item, and the fire task's own cohort drain hands isolated_cohort=True to
    run_phase_z."""
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    schedules = tmp_path / "sched.json"
    schedules.write_text(json.dumps({
        "cron_jobs": [{"id": "volpred-hourly-dispatch", "schedule": "7 * * * *"}],
        "daemons": [{"id": "volpred-dispatch-supervisor", "max_slots": 2,
                     "writer_isolation": {"mode": "pilot", "lanes": ["platform_ops"]}}],
    }), encoding="utf-8")
    fake_ws = {"name": "dispatch-slot-1-fixed", "path": str(tmp_path / "ws"),
               "branch": "worktree-dispatch-slot-1-fixed", "base_sha": "abc",
               "lanes": ["platform_ops"], "created_at": "2026-07-20T00:00:00+00:00",
               "setup_s": 1.0}
    monkeypatch.setattr(
        scheduler, "_preassign_mutating_task",
        lambda **_kw: _assigned_mutating_task(),
    )
    monkeypatch.setattr(
        scheduler.isolation, "prepare",
        lambda **_kw: _prepared_isolation(tmp_path),
    )
    monkeypatch.setattr(
        scheduler, "_settle_mutating_task",
        lambda **_kw: {"ok": True, "status": "pending"},
    )
    monkeypatch.setattr(scheduler.workspace_mod, "sweep_orphan_workspaces",
                        lambda **kw: [])
    monkeypatch.setattr(
        scheduler.workspace_mod,
        "allocate_workspace",
        lambda **kw: {
            **fake_ws,
            **kw["task_binding"],
            "task_title": kw["task_binding"]["title"],
            "task_description": kw["task_binding"]["description"],
        },
    )
    monkeypatch.setattr(scheduler.workspace_mod, "finalize_workspace",
                        lambda **kw: {"disposition": "empty_removed"})
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **_kwargs: {
            "ran": True, "reason": "ok", "dirty_at_fire_start": 0,
            "fire_lifecycle": _fire_lifecycle(),
        },
    )
    captured: list[dict] = []

    def spy_run_phase_z(**kwargs):
        captured.append(kwargs)
        return {"committed": False, "reason": "clean"}

    monkeypatch.setattr(scheduler.phase_z, "run_phase_z", spy_run_phase_z)

    def fake_run_worker(**kwargs):
        state.record_completion(
            job_id=kwargs["job_id"], exit_code=0, outcome="success",
            final_model=worker.OPUS_MODEL, path=kwargs["state_path"],
        )
        return worker.WorkerResult(
            exit_code=0, outcome="success", final_model=worker.OPUS_MODEL,
            attempts=1, duration_s=1.0, log_tail="ok",
        )

    monkeypatch.setattr(scheduler.worker, "run_worker", fake_run_worker)
    scheduler._PHASE_Z_LOCK = None  # fresh loop per asyncio.run
    result = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt_path,
        log_path=tmp_path / "worker.log", dry_run=False,
        repo_root=tmp_path, schedules_path=schedules,
    ))
    assert result["action"] == "fired"
    assert captured and captured[-1]["isolated_cohort"] is True


def _e2e_cas_merge(**kwargs) -> dict:
    """Hermetic integrator: atomic expected-main CAS for orchestration tests."""
    proc = subprocess.run(
        [
            "git", "-C", str(kwargs["repo_root"]), "update-ref",
            "refs/heads/main",
            kwargs["expected_candidate_sha"],
            kwargs["expected_main_sha"],
        ],
        capture_output=True, text=True, check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "reason": "merged" if proc.returncode == 0 else "integration_cas_lost",
        "output_tail": (proc.stderr or "")[-300:],
    }


def test_mutating_e2e_two_slots_different_paths_land_and_settle(
    tmp_path: Path, monkeypatch,
) -> None:
    """Contract→workspace→machine commit→gate→CAS→queue settlement."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = tmp_path / "next_tasks.json"
    queue.write_text(
        json.dumps([
                {
                    "id": "slot-a", "status": "pending", "priority": 1,
                    "task_type": "platform_ops", "dispatch_lane": "agent",
                    "write_intent": "repo_patch",
                "declared_output_paths": ["scripts/slot_a.py"],
                "post_merge_actions": [],
            },
                {
                    "id": "slot-b", "status": "pending", "priority": 2,
                    "task_type": "governance", "dispatch_lane": "agent",
                    "write_intent": "repo_patch",
                "declared_output_paths": ["docs/slot_b.md"],
                "post_merge_actions": [],
            },
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", queue)
    first = task_pool_claim.cmd_dispatch_preassign(
        argparse.Namespace(
            owner="dispatch-slot-1", session="session-a", job_id="job-a"
        )
    )
    second = task_pool_claim.cmd_dispatch_preassign(
        argparse.Namespace(
            owner="dispatch-slot-2", session="session-b", job_id="job-b"
        )
    )
    ws_a = _ws_allocate(
        repo, job_id="job-a", slot="slot-1",
        task_binding=first["contract"],
    )
    ws_b = _ws_allocate(
        repo, job_id="job-b", slot="slot-2",
        task_binding=second["contract"],
    )
    assert ws_a is not None and ws_b is not None
    Path(ws_a["path"], "scripts").mkdir(exist_ok=True)
    Path(ws_a["path"], "scripts", "slot_a.py").write_text(
        "SLOT = 'a'\n", encoding="utf-8"
    )
    Path(ws_b["path"], "docs").mkdir(exist_ok=True)
    Path(ws_b["path"], "docs", "slot_b.md").write_text(
        "slot b\n", encoding="utf-8"
    )
    green = lambda **_kw: {
        "verdict": "green", "rc": 0, "targets": [], "duration_s": 0.01
    }
    out_a = workspace.finalize_workspace(
        repo_root=repo, workspace=ws_a, worker_outcome="success",
        queue_path=tmp_path / "remediation.json",
        gate_fn=green, merge_fn=_e2e_cas_merge,
    )
    out_b = workspace.finalize_workspace(
        repo_root=repo, workspace=ws_b, worker_outcome="success",
        queue_path=tmp_path / "remediation.json",
        gate_fn=green, merge_fn=_e2e_cas_merge,
    )
    assert out_a["disposition"] == out_b["disposition"] == "merged"
    for contract, outcome in (
        (first["contract"], out_a), (second["contract"], out_b),
    ):
        settled = task_pool_claim.cmd_dispatch_settle(
            argparse.Namespace(
                id=contract["task_id"],
                session=contract["claim_session_id"],
                job_id=contract["dispatch_job_id"],
                disposition="merged",
                result=f"main_sha={outcome['main_sha']}",
            )
        )
        assert settled["status"] == "succeeded"
    rows = json.loads(queue.read_text(encoding="utf-8"))
    assert {row["status"] for row in rows} == {"succeeded"}
    assert subprocess.run(
        ["git", "-C", str(repo), "show", "main:scripts/slot_a.py"],
        check=True, capture_output=True, text=True,
    ).stdout == "SLOT = 'a'\n"
    assert subprocess.run(
        ["git", "-C", str(repo), "show", "main:docs/slot_b.md"],
        check=True, capture_output=True, text=True,
    ).stdout == "slot b\n"


def test_mutating_e2e_two_slots_same_path_conflict_is_adjudicated(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)

    def binding(suffix: str) -> dict:
        return {
            "task_id": f"conflict-{suffix}",
            "claim_session_id": f"session-{suffix}",
            "write_intent": "repo_patch",
            "declared_output_paths": ["conflict.txt"],
            "post_merge_actions": [],
        }

    ws_a = _ws_allocate(
        repo, job_id="3" * 32, slot="slot-1", task_binding=binding("a")
    )
    ws_b = _ws_allocate(
        repo, job_id="4" * 32, slot="slot-2", task_binding=binding("b")
    )
    assert ws_a is not None and ws_b is not None
    Path(ws_a["path"], "conflict.txt").write_text("slot-a\n", encoding="utf-8")
    Path(ws_b["path"], "conflict.txt").write_text("slot-b\n", encoding="utf-8")
    green = lambda **_kw: {
        "verdict": "green", "rc": 0, "targets": [], "duration_s": 0.01
    }
    first = workspace.finalize_workspace(
        repo_root=repo, workspace=ws_a, worker_outcome="success",
        queue_path=queue, gate_fn=green, merge_fn=_e2e_cas_merge,
    )
    second = workspace.finalize_workspace(
        repo_root=repo, workspace=ws_b, worker_outcome="success",
        queue_path=queue, gate_fn=green, merge_fn=_e2e_cas_merge,
    )

    assert first["disposition"] == "merged"
    assert second["disposition"] == "remediation_opened"
    assert second["reason"] == "rebase_conflict"
    assert subprocess.run(
        ["git", "-C", str(repo), "show", "main:conflict.txt"],
        check=True, capture_output=True, text=True,
    ).stdout == "slot-a\n"
    assert second["checkpoint"]["commit"]


def test_mutating_e2e_pre_dirty_target_is_fail_closed(
    tmp_path: Path,
) -> None:
    """Actual production integrator refuses overlapping canonical WIP."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "scripts").mkdir()
    shutil.copy2(
        workspace.ROOT / "scripts" / "merge_worktree.sh",
        repo / "scripts" / "merge_worktree.sh",
    )
    shutil.copy2(
        workspace.ROOT / "scripts" / "git_writer_lock.py",
        repo / "scripts" / "git_writer_lock.py",
    )
    _git_init_repo(repo)
    ws = _ws_allocate(
        repo,
        job_id="5" * 32,
        task_binding={
            "task_id": "pre-dirty",
            "claim_session_id": "pre-dirty-session",
            "write_intent": "repo_patch",
            "declared_output_paths": ["target.py"],
            "post_merge_actions": [],
        },
    )
    assert ws is not None
    Path(ws["path"], "target.py").write_text("candidate\n", encoding="utf-8")
    (repo / "target.py").write_text("owner-wip\n", encoding="utf-8")
    green = lambda **_kw: {
        "verdict": "green", "rc": 0, "targets": [], "duration_s": 0.01
    }

    result = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=_tmp_queue(tmp_path), gate_fn=green,
    )

    assert result["disposition"] == "remediation_opened"
    assert result["reason"] == "merge_failed"
    assert (repo / "target.py").read_text(encoding="utf-8") == "owner-wip\n"
    assert result["checkpoint"]["commit"]


def test_mutating_e2e_worker_crash_routes_to_terminal_remediation(
    tmp_path: Path, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = tmp_path / "next_tasks.json"
    queue.write_text(json.dumps([{
        "id": "worker-crash",
        "status": "pending",
        "task_type": "platform_ops",
        "write_intent": "repo_patch",
        "declared_output_paths": ["partial.py"],
        "post_merge_actions": [],
    }]), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", queue)
    assigned = task_pool_claim.cmd_dispatch_preassign(
        argparse.Namespace(
            owner="dispatch-slot-crash",
            session="crash-session",
            job_id="crash-job",
        )
    )
    ws = _ws_allocate(
        repo, job_id="crash-job", task_binding=assigned["contract"]
    )
    assert ws is not None
    Path(ws["path"], "partial.py").write_text(
        "INCOMPLETE = True\n", encoding="utf-8"
    )

    final = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="failure",
        queue_path=tmp_path / "remediation.json",
    )
    settled = task_pool_claim.cmd_dispatch_settle(
        argparse.Namespace(
            id="worker-crash",
            session="crash-session",
            job_id="crash-job",
            disposition="remediation",
            result=f"workspace={final['disposition']}",
        )
    )

    assert final["disposition"] == "remediation_opened"
    assert final["reason"] == "worker_failure"
    assert settled["status"] == "blocked"
    assert json.loads(queue.read_text(encoding="utf-8"))[0]["status"] == "blocked"
