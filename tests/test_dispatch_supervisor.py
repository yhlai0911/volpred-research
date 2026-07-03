from __future__ import annotations

import asyncio
import json
import logging
import resource
import signal
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import health, procutil, scheduler, state, supervisor, worker


def _tmp_state(tmp_path: Path) -> Path:
    return tmp_path / "dispatch_state.json"


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
        return exit_code, float(attempt)

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
    assert result.final_model == worker.SONNET_MODEL
    assert sleeps == [worker.RETRY_BACKOFF_S, worker.RETRY_BACKOFF_S]
    assert attempts == [
        (1, worker.OPUS_MODEL),
        (2, worker.OPUS_MODEL),
        (3, worker.SONNET_MODEL),
    ]
    assert alerts_called == []


def test_worker_auth_blocks_without_retry(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    log_path = tmp_path / "worker.log"
    attempts: list[int] = []
    auth_alerts: list[dict] = []

    def fake_run_one_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        log_path.write_text("Not logged in. Please run /login", encoding="utf-8")
        return 1, 1.0

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
        log_path.write_text("worker timed out", encoding="utf-8")
        return 137, 12.0

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
        return 0, 1.0

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
    ))

    assert decision["action"] == "fired"
    assert decision["outcome"] == "success"
    assert received and received[0]["prompt_text"] == "prompt-body"


def test_due_to_fire_warns_on_invalid_last_fire_at(capsys) -> None:
    # parse_iso_warn (via volpred.ops.diagnostics) writes structured WARN to
    # stderr, not the std logging module — so we read capsys.err here.
    due, _prev = scheduler._due_to_fire(
        cron_expr="7 * * * *",
        last_fire_at="not-a-date",
    )

    err = capsys.readouterr().err
    assert due is True
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

    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid: kills.append(pgid))
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_MATCH)
    monkeypatch.setattr(
        state,
        "get_current_job",
        lambda path=state_path: state.CurrentJob(
            pid=123,
            pgid=456,
            schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00",
            attempt=1,
            model="opus",
            log_path="/tmp/x.log",
            started_wall="Wed Jan  1 00:00:00 2026",
            age_seconds=4000,
        ),
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "killed"
    assert kills == [456]
    assert len(alerts_called) == 1
    assert state.read_state(state_path)["current_job"] is None


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

    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid: kills.append(pgid))
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_MISMATCH)
    monkeypatch.setattr(
        state,
        "get_current_job",
        lambda path=state_path: state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", started_wall="Wed Jan  1 00:00:00 2026",
            age_seconds=4000,
        ),
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

    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid: kills.append(pgid))
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
    monkeypatch.setattr(health.procutil, "check_identity", lambda pid, started_wall: procutil.IDENTITY_UNVERIFIED)
    monkeypatch.setattr(
        state,
        "get_current_job",
        lambda path=state_path: state.CurrentJob(
            pid=123, pgid=456, schedule_id="hourly_dispatch",
            started_at="2026-01-01T00:00:00+00:00", attempt=1, model="opus",
            log_path="/tmp/x.log", started_wall=None, age_seconds=4000,
        ),
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "timeout_unverified"
    assert kills == [], "must not signal a pid with no recorded fingerprint to verify against"
    assert state.read_state(state_path)["completions"][-1]["outcome"] == "timeout_unverified"


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
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    health._force_kill_pgid(456)

    assert calls == [signal.SIGTERM]


def test_force_kill_pgid_tolerates_exit_between_term_and_probe(monkeypatch) -> None:
    calls: list[int] = []

    def exits_after_term(pgid: int, sig: int) -> None:
        calls.append(sig)
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr(procutil.os, "killpg", exits_after_term)
    monkeypatch.setattr(procutil.time, "sleep", lambda seconds: None)

    health._force_kill_pgid(456)

    assert calls == [signal.SIGTERM, 0]


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

    monkeypatch.setattr(worker, "_spawn", lambda **kwargs: StuckProc())
    monkeypatch.setattr(worker.os, "getpgid", lambda pid: 456)
    monkeypatch.setattr(worker, "_kill_pgid", lambda pgid: kills.append(pgid))
    monkeypatch.setattr(worker.procutil, "get_process_start_wall", lambda pid: "Wed Jan  1 00:00:00 2026")
    monkeypatch.setattr(
        worker.state, "reserve_fire", lambda **kwargs: reserve_calls.append(kwargs),
    )
    monkeypatch.setattr(
        worker.state, "attach_process", lambda **kwargs: attach_calls.append(kwargs),
    )

    with caplog.at_level(logging.WARNING, logger=worker.__name__):
        exit_code, duration = worker._run_one_attempt(
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
    assert attach_calls and attach_calls[0]["pid"] == 123
    assert attach_calls[0]["started_wall"] == "Wed Jan  1 00:00:00 2026"
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
        log_path.write_text("timed out — SIGKILL'd by watchdog", encoding="utf-8")
        # Simulate what real `_run_one_attempt` returns when our timeout fires
        return worker.TIMEOUT_KILLED_SENTINEL, 12.0

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
        log_path.write_text("external SIGTERM (e.g. launchd kill)", encoding="utf-8")
        # Externally signal-killed → negative is normalized at the boundary
        return worker._normalize_signal_exit(-15), 7.0  # → 143 SIGTERM

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
    monkeypatch.setattr(supervisor.worker, "_kill_pgid", lambda pgid: kills.append(pgid))
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
    monkeypatch.setattr(supervisor.worker, "_kill_pgid", lambda pgid: kills.append(pgid))
    monkeypatch.setattr(supervisor.procutil, "check_identity", lambda pid, wall: procutil.IDENTITY_MISMATCH)
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
    assert snap["current_job"] is None
    assert snap["completions"][-1]["outcome"] == "orphan_unverified_not_killed"


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
    # scheduler must be able to fire again immediately after
    state.reserve_fire(
        schedule_id="hourly_dispatch", attempt=1, model="opus",
        log_path="/tmp/next.log", path=state_path,
    )


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
    monkeypatch.setattr(supervisor.worker, "_kill_pgid", lambda pgid: kills.append(pgid))
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


# ---------------------------------------------------------------------------
# worker._kill_pgid — liveness-probe PermissionError (found via a REAL smoke
# test spawning a genuine `sleep 30` process under this sandboxed environment;
# not one of the Codex review's 4 numbered items, but a real crash: the
# liveness-probe poll loop only caught ProcessLookupError, so a sandboxed
# `os.killpg(pgid, 0)` raising PermissionError propagated all the way out of
# `_kill_pgid()` — which `supervisor._handle_restart_orphan()` calls directly
# with no caller-side try/except, so this crashed orphan cleanup on boot.
# ---------------------------------------------------------------------------


def test_kill_pgid_survives_permission_error_on_liveness_probe(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_killpg(pgid, sig):
        calls.append(("SIGTERM" if sig == 15 else ("PROBE" if sig == 0 else "SIGKILL"), pgid))
        if sig == 0:
            raise PermissionError("sandbox denied signal-0 probe")
        return None

    monkeypatch.setattr(worker.os, "killpg", fake_killpg)
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)

    worker._kill_pgid(999, grace_s=1)

    kinds = [c[0] for c in calls]
    assert "SIGTERM" in kinds
    assert "PROBE" in kinds
    assert "SIGKILL" in kinds, "must fall through to SIGKILL after the probe is denied, not crash"
