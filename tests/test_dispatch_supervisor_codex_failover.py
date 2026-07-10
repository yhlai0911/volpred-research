"""Codex failover — the hourly slot must survive a Claude quota/auth outage.

Regression cover for the 2026-07-04 cutover gap: `cron_hourly_dispatch.sh` handed
the slot to `codex exec` when Claude died, the supervisor that replaced it did
not, so every quota outage silently dropped its hourly fires.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.dispatch_supervisor import codex_failover, worker


# ── codex_failover unit ────────────────────────────────────────────────────

def test_disabled_by_env_flag() -> None:
    result = codex_failover.run_codex_failover(reason="quota", enabled=False)
    assert (result.attempted, result.recovered) == (False, False)
    assert result.exit_code == codex_failover.RC_DISABLED


def test_suppressed_under_pytest_by_default(monkeypatch) -> None:
    """`codex exec` claims a task and commits — a test run must never trigger it.

    Every other test in this file opts in with `enabled=True`. Anything that
    drives worker.run_worker() down the quota/auth branch without patching this
    module relies on THIS guard (2026-07-10: the pre-existing
    `test_worker_auth_blocks_without_retry` did exactly that and hung the suite
    spawning a real codex).
    """
    monkeypatch.setattr(
        codex_failover.subprocess, "run",
        lambda *a, **k: pytest.fail("codex must never be exec'd from a test"),
    )
    result = codex_failover.run_codex_failover(reason="quota")
    assert (result.attempted, result.recovered) == (False, False)
    assert result.exit_code == codex_failover.RC_DISABLED


def test_missing_binary_aborts_without_calling_exec(monkeypatch) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: None)
    monkeypatch.setattr(
        codex_failover.subprocess, "run",
        lambda *a, **k: pytest.fail("must not exec codex when binary is missing"),
    )
    result = codex_failover.run_codex_failover(reason="quota", enabled=True)
    assert (result.attempted, result.recovered) == (False, False)
    assert result.exit_code == codex_failover.RC_BINARY_MISSING


def test_preflight_timeout_is_not_reported_as_broken_binary(monkeypatch) -> None:
    """A loaded host makes `codex --version` slow; that is not a broken binary.

    The shell version misdiagnosed this and emailed a critical binary-broken
    alert (2026-07-02 incident). Keep the distinction.
    """
    def _timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="codex --version", timeout=30)

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _timeout)

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)
    assert result.attempted is False
    assert result.exit_code == codex_failover.RC_PREFLIGHT_TIMEOUT
    assert "逾時" in result.detail
    assert "不是 binary 損壞" in result.detail

    # …and the genuinely-broken branch says the opposite, so an operator reading
    # the alert can tell the two apart.
    monkeypatch.setattr(
        codex_failover.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=3, stdout="", stderr="segfault"),
    )
    broken = codex_failover.run_codex_failover(reason="quota", enabled=True)
    assert broken.exit_code == 3
    assert "可能損壞" in broken.detail


def test_exec_success_marks_recovered(monkeypatch) -> None:
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(argv)
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.144.1", stderr="")
        return SimpleNamespace(returncode=0, stdout="claimed task X; done", stderr="")

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _run)

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)
    assert (result.attempted, result.recovered, result.exit_code) == (True, True, 0)
    assert calls[1][1] == "exec"
    assert "workspace-write" in calls[1]
    assert "claimed task X" in result.output_tail


def test_exec_failure_is_attempted_but_not_recovered(monkeypatch) -> None:
    def _run(argv, **kwargs):
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.144.1", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="401 unauthorized")

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _run)

    result = codex_failover.run_codex_failover(reason="auth", enabled=True)
    assert (result.attempted, result.recovered, result.exit_code) == (True, False, 1)


def test_exec_timeout_is_attempted_but_not_recovered(monkeypatch) -> None:
    def _run(argv, **kwargs):
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.144.1", stderr="")
        raise subprocess.TimeoutExpired(cmd="codex exec", timeout=600, output="partial work")

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _run)

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)
    assert (result.attempted, result.recovered) == (True, False)
    assert "partial work" in result.output_tail


def test_missing_prompt_file_falls_back_and_logs(monkeypatch, caplog, tmp_path) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger=codex_failover.__name__):
        prompt = codex_failover._read_prompt(tmp_path / "nope.md")
    assert prompt == codex_failover.FALLBACK_PROMPT
    assert "failover prompt unreadable" in caplog.text


def test_shipped_prompt_file_exists() -> None:
    """The failover prompt is the contract with Codex — losing it degrades the slot."""
    assert codex_failover.PROMPT_PATH.is_file()


# ── worker wiring ──────────────────────────────────────────────────────────

class _FailoverStub:
    def __init__(self, recovered: bool) -> None:
        self.recovered = recovered
        self.seen_reasons: list[str] = []

    def __call__(self, *, reason: str):
        self.seen_reasons.append(reason)
        return codex_failover.FailoverResult(
            attempted=True, recovered=self.recovered, exit_code=0 if self.recovered else 1,
            detail="stub", duration_s=1.0, output_tail="codex output",
        )


@pytest.fixture
def _quiet_state_and_alerts(monkeypatch, tmp_path: Path):
    sent: list[dict] = []
    monkeypatch.setattr(worker.state, "record_completion", lambda **k: {})
    monkeypatch.setattr(worker.state, "set_auth_blocked", lambda *a, **k: None)
    monkeypatch.setattr(worker.state, "clear_alert_dedup", lambda *a, **k: None)
    monkeypatch.setattr(worker.state, "read_state", lambda *a, **k: {})
    monkeypatch.setattr(worker.alerts, "send_auth_alert", lambda **k: True)
    monkeypatch.setattr(worker.alerts, "send_quota_alert", lambda **k: True)
    monkeypatch.setattr(
        worker.alerts, "send_codex_failover_alert",
        lambda **k: (sent.append(k), True)[1],
    )
    return sent


def _stub_attempt(monkeypatch, output: str, exit_code: int = 1) -> None:
    monkeypatch.setattr(
        worker, "_run_one_attempt",
        lambda **kwargs: (exit_code, 1.0, output),
    )


QUOTA_OUTPUT = "You've hit your weekly limit · resets 4pm"
AUTH_OUTPUT = "Not logged in. Please run /login"


def test_quota_outage_hands_slot_to_codex(monkeypatch, tmp_path, _quiet_state_and_alerts):
    _stub_attempt(monkeypatch, QUOTA_OUTPUT)
    stub = _FailoverStub(recovered=True)
    monkeypatch.setattr(worker.codex_failover, "run_codex_failover", stub)

    result = worker.run_worker(
        prompt_text="tick", log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json", sleep_fn=lambda _s: None,
    )

    assert stub.seen_reasons == ["quota"]
    assert result.outcome == "codex_failover_recovered"
    assert result.exit_code == 0
    assert result.final_model == worker.CODEX_MODEL_LABEL


def test_quota_outage_without_codex_still_reports_quota_blocked(
    monkeypatch, tmp_path, _quiet_state_and_alerts
):
    _stub_attempt(monkeypatch, QUOTA_OUTPUT)
    monkeypatch.setattr(worker.codex_failover, "run_codex_failover", _FailoverStub(recovered=False))

    result = worker.run_worker(
        prompt_text="tick", log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json", sleep_fn=lambda _s: None,
    )
    assert result.outcome == "quota_blocked"
    assert result.exit_code != 0


def test_auth_break_hands_slot_to_codex_but_keeps_auth_blocked(
    monkeypatch, tmp_path, _quiet_state_and_alerts
):
    blocked: list[bool] = []
    monkeypatch.setattr(worker.state, "set_auth_blocked", lambda v, **k: blocked.append(v))
    _stub_attempt(monkeypatch, AUTH_OUTPUT)
    stub = _FailoverStub(recovered=True)
    monkeypatch.setattr(worker.codex_failover, "run_codex_failover", stub)

    result = worker.run_worker(
        prompt_text="tick", log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json", sleep_fn=lambda _s: None,
    )

    assert stub.seen_reasons == ["auth"]
    assert blocked == [True], "failover buys back the hour; it does not repair the credential"
    assert result.outcome == "codex_failover_recovered"


def test_failover_exception_never_escapes_worker(monkeypatch, tmp_path, _quiet_state_and_alerts):
    _stub_attempt(monkeypatch, QUOTA_OUTPUT)

    def _boom(*, reason: str):
        raise RuntimeError("codex module blew up")

    monkeypatch.setattr(worker.codex_failover, "run_codex_failover", _boom)

    result = worker.run_worker(
        prompt_text="tick", log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json", sleep_fn=lambda _s: None,
    )
    assert result.outcome == "quota_blocked"


def test_success_path_never_calls_failover(monkeypatch, tmp_path, _quiet_state_and_alerts):
    _stub_attempt(monkeypatch, "all good", exit_code=0)
    monkeypatch.setattr(
        worker.codex_failover, "run_codex_failover",
        lambda **k: pytest.fail("failover must not fire on a healthy Claude run"),
    )
    result = worker.run_worker(
        prompt_text="tick", log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json", sleep_fn=lambda _s: None,
    )
    assert result.outcome == "success"
