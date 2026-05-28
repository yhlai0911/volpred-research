from __future__ import annotations

import asyncio
import json
import resource
from pathlib import Path

from scripts.dispatch_supervisor import health, scheduler, state, supervisor, worker


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


def test_health_check_kills_overdue_job(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    state.begin_fire(
        pid=123,
        pgid=456,
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/x.log",
        path=state_path,
    )
    kills: list[int] = []
    alerts_called: list[dict] = []

    monkeypatch.setattr(health, "_force_kill_pgid", lambda pgid: kills.append(pgid))
    monkeypatch.setattr(
        health.alerts,
        "send_hang_alert",
        lambda **kwargs: alerts_called.append(kwargs) or True,
    )
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
            age_seconds=4000,
        ),
    )

    action = health.check_once(state_path=state_path, max_age_s=3000)

    assert action == "killed"
    assert kills == [456]
    assert len(alerts_called) == 1
    assert state.read_state(state_path)["current_job"] is None


def test_health_check_marks_silent_death(tmp_path: Path, monkeypatch) -> None:
    state_path = _tmp_state(tmp_path)
    state.begin_fire(
        pid=123,
        pgid=456,
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/x.log",
        path=state_path,
    )
    alerts_called: list[dict] = []

    monkeypatch.setattr(health, "_pid_alive", lambda pid: False)
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


def test_supervisor_set_runtime_env_raises_soft_limit(monkeypatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []

    monkeypatch.setattr(resource, "getrlimit", lambda which: (256, 65536))
    monkeypatch.setattr(resource, "setrlimit", lambda which, value: calls.append((which, value)))

    supervisor._set_runtime_env()

    assert calls == [(resource.RLIMIT_NOFILE, (65536, 65536))]


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
