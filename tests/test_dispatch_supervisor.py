from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import resource
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import (
    claim_release, health, phase_z, procutil, scheduler, state, supervisor, worker,
    workspace,
)


def _tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


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


_REAL_RUN_PREGATE = scheduler._run_pregate


def _stub_pregate(monkeypatch) -> None:
    """Keep fire-path tests off the REAL scripts/hourly_dispatch_pregate.py.

    `_run_pregate` resolves the script from the module-level ROOT (the real
    checkout), not from the test's `repo_root`. The pregate is live in
    mode=shadow, so an un-stubbed fire-path test spawns it for real and appends
    a synthetic decision to storage/logs/hourly_pregate.jsonl — the very log the
    shadow→enforce flip is judged on. Observed 2026-07-10: 4 rows within 2s per
    pytest run. Returns False = "do not skip".
    """
    monkeypatch.setattr(scheduler, "_run_pregate", lambda **_kwargs: False)


@pytest.fixture(autouse=True)
def _never_spawn_the_real_pregate(monkeypatch) -> None:
    """Autouse, because opt-in protection is not protection.

    2026-07-10: `_stub_pregate()` landed as a helper each fire-path test had to
    remember to call. Five did. The integration test added later that same day
    (`test_heartbeat_advances_while_worker_in_flight`) did not, and every run of
    it appended a row to the production shadow log — stamped `invoker=supervisor`,
    because `_run_pregate` hardcodes that flag, so the row was indistinguishable
    from a real dispatch decision except by its parent pid. Proven by running
    that single test and watching the log grow by one.

    The existing explicit `_stub_pregate(monkeypatch)` calls stay valid (they
    just re-apply the same patch); a new test can no longer forget.
    """
    _stub_pregate(monkeypatch)


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


def test_pregate_is_stubbed_for_every_test_in_this_module() -> None:
    """If `_never_spawn_the_real_pregate` ever loses `autouse=True`, this fails
    here instead of quietly resuming writes to the production shadow log — the
    failure mode is invisible otherwise: tests pass, the log just grows.
    """
    assert scheduler._run_pregate is not _REAL_RUN_PREGATE, (
        "the real _run_pregate is live during tests — a fire-path test will spawn "
        "scripts/hourly_dispatch_pregate.py and append a synthetic row to "
        "storage/logs/hourly_pregate.jsonl, the log the shadow→enforce flip is judged on"
    )


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
        log_path.write_text("worker timed out", encoding="utf-8")
        return 137, 12.0, "worker timed out"

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
    _stub_pregate(monkeypatch)
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


def test_scheduler_scratch_failure_releases_reserved_slot(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt-body", encoding="utf-8")
    _stub_pregate(monkeypatch)
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


def test_phase_z_dirty_tree_commits_with_correct_message(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    before = _git_head_count(tmp_path)
    # Simulate an agent that produced real work but forgot to commit it.
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments" / "k9999.py").write_text("print('result')\n", encoding="utf-8")
    out = phase_z.run_phase_z(
        repo_root=tmp_path, now_hhmm="16:07", pre_fire_dirty=set(),
        alert_fn=lambda **_kwargs: {},
    )
    assert out["committed"] is True
    assert out["reason"] == "committed"
    assert _git_head_count(tmp_path) == before + 1
    # A receipt-less fire still owes the reader a WHAT. The subject names the diff
    # groups (_generated_subject) rather than only stating that the account is
    # missing — 「本班產出未附說明」 told the reader nothing, which is what made the
    # audit gap read as a system fault in `git log` (boss, msg 886).
    assert _git_head_subject(tmp_path) == (
        "dispatch(16:07): 自動摘要（agent 未留 receipt）: 動到 experiments(1)"
    )
    # the real work is now tracked
    tracked = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "experiments/k9999.py"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == "experiments/k9999.py"


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
    # ...but the real work WAS committed
    assert subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "real_work.md"],
        capture_output=True, text=True, check=True,
    ).stdout.strip() == "real_work.md"


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
    commits: list = []

    def fake_runner(argv, **kwargs):
        sub = argv[3]  # ["git", "-C", root, <subcommand>, ...]
        if sub == "status":
            return _FakeCompleted(0, stdout=" M dirty.txt\0")
        if sub == "ls-files":
            return _FakeCompleted(0, stdout="")
        if sub == "add":
            return _FakeCompleted(1, stderr="fatal: index lock held")
        if sub == "commit":
            commits.append(argv)
            return _FakeCompleted(0)
        return _FakeCompleted(0)

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

    def fake_runner(argv, **kwargs):
        sub = argv[3]
        calls.append(sub)
        if sub == "status":
            return _FakeCompleted(0, stdout=" M work.txt\0")
        if sub == "ls-files":
            return _FakeCompleted(128, stderr="fatal: bad revision")
        if sub == "add":
            return _FakeCompleted(0)
        return _FakeCompleted(0)

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
    _stub_pregate(monkeypatch)
    ran = {"phase_z": 0}

    def boom(**kwargs):
        raise RuntimeError("worker exploded")

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
    _stub_pregate(monkeypatch)

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
    _stub_pregate(monkeypatch)
    order: list[str] = []

    monkeypatch.setattr(
        scheduler.phase_z, "recover_failed_closeout",
        lambda **kwargs: order.append(f"recovery:{kwargs['repo_root']}")
        or {"committed": False, "reason": "no_failed_closeout"},
    )
    monkeypatch.setattr(
        scheduler.phase_z, "run_pre_fire_guard",
        lambda **kwargs: order.append(f"guard:{kwargs['repo_root']}") or {"ran": True, "reason": "ok"},
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
    _stub_pregate(monkeypatch)
    called = {"guard": 0, "worker": 0}

    monkeypatch.setattr(
        scheduler.phase_z,
        "recover_failed_closeout",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("bad closeout receipt")),
    )
    monkeypatch.setattr(
        scheduler.phase_z,
        "run_pre_fire_guard",
        lambda **_kwargs: called.__setitem__("guard", called["guard"] + 1) or {},
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
    _stub_pregate(monkeypatch)
    ran = {"guard": 0, "worker": 0}

    def exploding_guard(**_kwargs):
        ran["guard"] += 1
        raise RuntimeError("guard exploded")

    monkeypatch.setattr(scheduler.phase_z, "run_pre_fire_guard", exploding_guard)
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


def test_scheduler_pre_fire_guard_runs_even_when_pregate_skips(tmp_path: Path, monkeypatch) -> None:
    # Deliberate ordering (guard BEFORE pregate), mirroring the legacy shell:
    # the files the guard repairs are read by the live site and by the pregate
    # itself, so a slot the pregate declines still deserves a clean tree.
    state_path = _tmp_state(tmp_path)
    _seed_due(state_path)
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("prompt", encoding="utf-8")
    called = {"guard": 0, "worker": 0}

    monkeypatch.setattr(
        scheduler, "load_pregate_config",
        lambda **_kwargs: {"mode": "enforce", "window_hours": 3.0},
    )
    monkeypatch.setattr(scheduler, "_run_pregate", lambda **_kwargs: True)  # SKIP this fire
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

    assert decision["action"] == "pregate_skip"
    assert called["guard"] == 1   # tree still cleaned...
    assert called["worker"] == 0  # ...even though no agent ran


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

    assert first == {"ran": True, "reason": "ok", "dirty_at_fire_start": 0}
    assert second == first  # idempotent: no-op on a clean tree, twice
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True,
    )
    assert status.stdout.strip() == ""


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
        health, "_force_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
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
    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid: True)
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

    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid: True)
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
        health, "_force_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
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
        health, "_force_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(health.procutil, "pgid_members", lambda pgid: [])
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_MISMATCH)
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
        health, "_force_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
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


def test_force_kill_pgid_tolerates_process_lookup_races(monkeypatch) -> None:
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
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    health._force_kill_pgid(456)

    assert calls == [signal.SIGTERM]


def test_force_kill_pgid_tolerates_exit_after_term(monkeypatch) -> None:
    """health._force_kill_pgid delegates to procutil.kill_pgid, which must now
    RETURN whether the group is confirmed gone (2026-07-11) — a refused kill
    used to be indistinguishable from a successful one."""
    sigs: list[int] = []
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: sigs.append(sig))
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [])
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    assert health._force_kill_pgid(456) is True
    assert sigs == [signal.SIGTERM]


def test_force_kill_pgid_reports_false_when_orphan_survives(monkeypatch) -> None:
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [456])  # never dies
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    assert health._force_kill_pgid(456) is False


def test_supervisor_set_runtime_env_raises_soft_limit(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []

    monkeypatch.setattr(resource, "getrlimit", lambda which: (256, 65536))
    monkeypatch.setattr(resource, "setrlimit", lambda which, value: calls.append((which, value)))

    supervisor._set_runtime_env()

    assert calls == [(resource.RLIMIT_NOFILE, (65536, 65536))]


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
    assert worker._classify(worker._normalize_signal_exit(-15), "") == "hang"
    assert worker._classify(worker._normalize_signal_exit(-9), "") == "hang"
    assert worker._classify(worker._normalize_signal_exit(-14), "") == "hang"


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
    class StuckProc:
        pid = 123

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

    kills: list[int] = []
    reserve_calls: list[dict] = []
    attach_calls: list[dict] = []
    fingerprint_calls: list[dict] = []

    monkeypatch.setattr(worker, "_spawn", lambda **kwargs: StuckProc())
    monkeypatch.setattr(worker.os, "getpgid", lambda pid: 456)
    monkeypatch.setattr(
        worker, "_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
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
    assert kills == [456]
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


def test_worker_signal_killed_outside_timeout_also_classified_as_hang(
    tmp_path: Path, monkeypatch
) -> None:
    """If the child dies from SIGTERM/SIGKILL/SIGALRM by external means (not
    our own watchdog), `_run_one_attempt` still receives a negative wait()
    return. `_normalize_signal_exit` converts to 128+signum so HANG_EXIT_CODES
    set membership triggers and `_classify` returns "hang" → no retry.
    """
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    attempts: list[int] = []
    hang_alerts: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        _reserve_like_production(kwargs)
        log_path.write_text("external SIGTERM (e.g. launchd kill)", encoding="utf-8")
        # Externally signal-killed → negative is normalized at the boundary
        return worker._normalize_signal_exit(-15), 7.0, "external SIGTERM"  # → 143 SIGTERM

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
    assert result.exit_code == 143  # not sentinel — normalized POSIX code


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
        supervisor.worker, "_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
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
        supervisor.worker, "_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
    )
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_MISMATCH)
    monkeypatch.setattr(supervisor.procutil, "pgid_members_checked", lambda pgid: [])
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
        supervisor.procutil, "pgid_members_checked", lambda pgid: [1001],
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
    monkeypatch.setattr(supervisor.worker, "_kill_pgid", lambda pgid: kills.append(pgid))
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
    monkeypatch.setattr(supervisor.worker, "_kill_pgid", lambda pgid: kills.append(pgid))
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
    assert snap["completions"][-1]["outcome"] == "reservation_abandoned_no_pid"
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
        supervisor.worker, "_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
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
        supervisor.worker, "_kill_pgid", lambda pgid: bool(kills.append(pgid) or True)
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

    async def fake_sleep(_secs):
        return None

    def fake_check_once(**kwargs):
        beats.append(state.read_state(state_path))
        if len(beats) >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(health.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(health, "check_once", fake_check_once)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(health.health_loop(state_path=state_path))

    assert len(beats) == 2
    assert all(b["last_heartbeat_at"] > "2001" for b in beats), "no beat before check_once"
    assert beats[1]["last_heartbeat_at"] > beats[0]["last_heartbeat_at"], "beat did not advance"
    assert beats[0]["supervisor_pid"] == os.getpid(), "stale pid not re-stamped"


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
    assert observed_paths == [patched_path, patched_path]


# ---------------------------------------------------------------------------
# worker._kill_pgid — liveness-probe PermissionError (found via a REAL smoke
# test spawning a genuine `sleep 30` process under this sandboxed environment;
# not one of the Codex review's 4 numbered items, but a real crash: the
# liveness-probe poll loop only caught ProcessLookupError, so a sandboxed
# `os.killpg(pgid, 0)` raising PermissionError propagated all the way out of
# `_kill_pgid()` — which `supervisor._handle_restart_orphan()` calls directly
# with no caller-side try/except, so this crashed orphan cleanup on boot.
# ---------------------------------------------------------------------------


def test_worker_kill_pgid_falls_back_to_per_pid_when_killpg_denied(monkeypatch) -> None:
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
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)

    worker._kill_pgid(999, grace_s=1)

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
    monkeypatch.setattr(worker.os, "getpgid", lambda pid: 4242)
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
    assert spawned[0]["argv"][spawned[0]["argv"].index("--settings") + 1] == str(
        worker.PROJECT_ROOT / ".claude" / "settings.json"
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


def test_multislot_full_pool_skips_without_consuming_request(
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
    monkeypatch.setattr(
        scheduler.worker, "run_worker",
        lambda **_kwargs: pytest.fail("full pool must not spawn"),
    )

    decision = asyncio.run(scheduler._tick_once(
        state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt,
        log_path=tmp_path / "worker.log", dry_run=False, repo_root=tmp_path,
        max_slots=2, background=True,
    ))

    assert decision["reason"] == "slots_full"
    assert state.read_state(state_path)["fire_requested_at"] is not None


def test_multislot_half_pool_launches_second_without_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = _tmp_state(tmp_path)
    first = state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/first.log", max_slots=2, path=state_path,
    )
    state.attach_process(
        job_id=first.job_id, expected_attempt=1,
        pid=101, pgid=101, started_wall="wall-101", path=state_path,
    )
    _seed_due(state_path)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("prompt", encoding="utf-8")
    _stub_pregate(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def blocking_worker(**_kwargs):
        started.set()
        assert release.wait(2)
        return _ok_worker()

    monkeypatch.setattr(scheduler.worker, "run_worker", blocking_worker)
    monkeypatch.setattr(
        scheduler.phase_z, "run_phase_z",
        lambda **_kwargs: {"committed": False, "reason": "clean"},
    )

    async def scenario():
        decision = await scheduler._tick_once(
            state_path=state_path, cron_expr="7 * * * *", prompt_path=prompt,
            log_path=tmp_path / "worker.log", dry_run=False, repo_root=tmp_path,
            max_slots=2, background=True,
        )
        assert decision["action"] == "launched"
        assert decision["slot_id"] == "slot-2"
        assert await asyncio.to_thread(started.wait, 1)
        assert len(state.read_state(state_path)["current_jobs"]) == 2
        release.set()
        await asyncio.gather(*list(scheduler._ACTIVE_FIRE_TASKS.values()))

    asyncio.run(scenario())


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


def test_load_max_slots_uses_daemon_config_and_bounds_invalid(tmp_path: Path) -> None:
    cfg = tmp_path / "runtime_schedules.json"
    cfg.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID, "max_slots": 3,
    }]}), encoding="utf-8")
    assert scheduler.load_max_slots(schedules_path=cfg) == 3

    cfg.write_text(json.dumps({"daemons": [{
        "id": scheduler.DAEMON_ID, "max_slots": 0,
    }]}), encoding="utf-8")
    assert scheduler.load_max_slots(schedules_path=cfg) == scheduler.DEFAULT_MAX_SLOTS


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
    cfg = {"mode": "pilot", "lanes": ["platform_ops"], "max_total": 3,
           "disk_floor_gib": 0.0}
    cfg.update(overrides)
    return cfg


def _ws_allocate(repo: Path, *, job_id: str = "a" * 32, slot: str = "slot-1",
                 config: dict | None = None, active_isolated: int = 0):
    return workspace.allocate_workspace(
        repo_root=repo, slot_id=slot, job_id=job_id,
        config=config or _iso_cfg(), active_isolated=active_isolated,
    )


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
    assert [e["event"] for e in events] == ["allocated"]
    assert events[0]["branch"] == ws["branch"]
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


def test_workspace_allocate_respects_caps(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    # active cap: never a second concurrent isolated fire
    assert _ws_allocate(repo, active_isolated=1) is None
    # total cap counts kept worktrees too
    first = _ws_allocate(repo, job_id="b" * 32)
    assert first is not None
    second = _ws_allocate(repo, job_id="c" * 32, config=_iso_cfg(max_total=1))
    assert second is None
    reasons = [e.get("reason") for e in _ws_receipt_events(repo)
               if e["event"] == "allocation_skipped"]
    assert reasons == ["active_cap", "total_cap"]


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
    assert [e["event"] for e in _ws_receipt_events(repo)] == ["allocated", "finalized"]


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
        return {"ok": True, "rc": 0, "reason": "merged", "output_tail": ""}

    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=_tmp_queue(tmp_path), gate_fn=fake_gate, merge_fn=fake_merge,
    )
    assert out["disposition"] == "merged"
    assert merges == ["dispatch-slot-1-aaaaaaaa"]
    assert out["gate"]["verdict"] == "green"


def test_workspace_finalize_gate_red_opens_remediation_and_keeps_worktree(
    tmp_path: Path,
) -> None:
    """The no-deadlock invariant: a red gate NEVER strands the output. It must
    become a pending P2 task the normal dispatch loop is guaranteed to pick up,
    with the worktree preserved -- and re-running the finalizer must not
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
    assert wt.exists()  # output preserved, never force-removed
    tasks = json.loads(queue.read_text(encoding="utf-8"))
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "wsb_remed_dispatch-slot-1-aaaaaaaa"
    assert task["priority"] == 2
    assert task["status"] == "pending"
    assert task["task_type"] == "platform_ops"
    assert task["payload"]["worktree"] == ws["path"]
    assert task["payload"]["branch"] == ws["branch"]
    assert "merge_worktree.sh" in task["description"]
    # idempotent: a second finalize pass (orphan sweep rerun) files nothing new
    out2 = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success",
        queue_path=queue, gate_fn=red_gate, merge_fn=never_merge,
    )
    assert out2["disposition"] == "remediation_opened"
    tasks2 = json.loads(queue.read_text(encoding="utf-8"))
    assert len(tasks2) == 1


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
    assert Path(ws["path"]).exists()
    tasks = json.loads(queue.read_text(encoding="utf-8"))
    assert len(tasks) == 1 and tasks[0]["status"] == "pending"


def test_workspace_finalize_merge_failure_opens_remediation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    ws = _ws_allocate(repo)
    (Path(ws["path"]) / "change.py").write_text("x = 1\n", encoding="utf-8")
    out = workspace.finalize_workspace(
        repo_root=repo, workspace=ws, worker_outcome="success", queue_path=queue,
        gate_fn=lambda **kw: {"verdict": "green", "rc": 0, "targets": [],
                              "duration_s": 0.0, "output_tail": ""},
        merge_fn=lambda **kw: {"ok": False, "rc": 1, "reason": "merge_failed",
                               "output_tail": "[ABORT] conflict"},
    )
    assert out["disposition"] == "remediation_opened"
    assert out["reason"] == "merge_failed"
    assert Path(ws["path"]).exists()
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


def test_workspace_sweep_closes_true_orphans_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init_repo(repo)
    queue = _tmp_queue(tmp_path)
    protected_ws = _ws_allocate(repo, job_id="b" * 32)
    orphan_ws = _ws_allocate(repo, job_id="c" * 32, slot="slot-2")
    assert protected_ws is not None and orphan_ws is not None
    results = workspace.sweep_orphan_workspaces(
        repo_root=repo, protected_job_ids=["b" * 32], queue_path=queue,
    )
    # orphan (empty) removed; protected workspace untouched
    assert [r["disposition"] for r in results] == ["empty_removed"]
    assert not Path(orphan_ws["path"]).exists()
    assert Path(protected_ws["path"]).exists()


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
                             "max_total": 2, "disk_floor_gib": 5},
    }]}), encoding="utf-8")
    cfg = workspace.load_isolation_config(schedules_path=pilot)
    assert cfg == {"mode": "pilot", "lanes": ["platform_ops"], "max_total": 2,
                   "disk_floor_gib": 5.0}


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
    monkeypatch.setattr(scheduler.workspace_mod, "sweep_orphan_workspaces",
                        lambda **kw: [])
    monkeypatch.setattr(
        scheduler.workspace_mod, "allocate_workspace",
        lambda **kw: allocated.append(kw) or dict(fake_ws),
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


def test_scheduler_fire_unisolated_when_allocation_declined(tmp_path: Path, monkeypatch) -> None:
    """Allocation refusal (caps/disk/lock) must never veto the fire."""
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
    monkeypatch.setattr(scheduler.workspace_mod, "sweep_orphan_workspaces",
                        lambda **kw: [])
    monkeypatch.setattr(scheduler.workspace_mod, "allocate_workspace",
                        lambda **kw: None)
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
