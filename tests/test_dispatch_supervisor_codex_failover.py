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


@pytest.fixture(autouse=True)
def _provider_guard_stub(monkeypatch):
    def authorize(codex_bin, environment):
        forbidden = [
            key
            for key in ("OPENAI_API_KEY", "CODEX_API_KEY")
            if environment.get(key)
        ]
        if forbidden:
            raise codex_failover.ProviderRegistryError(
                f"forbidden API-key variables {forbidden}"
            )
        return SimpleNamespace(
            resolved_executable=codex_bin,
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "codex-cli",
                "VOLPRED_PROVIDER_MODEL_ID": codex_failover.CODEX_MODEL,
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
        )

    monkeypatch.setattr(codex_failover, "_authorize_codex", authorize)
    monkeypatch.setattr(
        codex_failover, "verify_spawn_receipt", lambda _receipt: None
    )


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


# The handover makes three distinct calls, and the tests below have to tell them
# apart because the whole 2026-07-12 bug was the code failing to:
#   1. `codex --version`   — is the binary here?           (local, says nothing about the API)
#   2. `codex exec <probe>`— does ChatGPT answer?          (the only call that knows)
#   3. `codex exec -s danger-full-access <task>` — do the work from an isolated cwd.
def _is_work_call(argv: list[str]) -> bool:
    return "danger-full-access" in argv


def _fake_codex(*, probe=None, work=None):
    """Route a faked subprocess.run to the right leg of the handover."""
    def _run(argv, **_kwargs):
        if argv[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="codex-cli 0.144.1", stderr="")
        leg = work if _is_work_call(argv) else probe
        if isinstance(leg, BaseException):
            raise leg
        return leg
    return _run


_PROBE_OK = SimpleNamespace(returncode=0, stdout="OK", stderr="")


def test_exec_success_marks_recovered(monkeypatch) -> None:
    calls: list[list[str]] = []
    work_envs: list[dict[str, str]] = []

    inner = _fake_codex(
        probe=_PROBE_OK,
        work=SimpleNamespace(returncode=0, stdout="claimed task X; done", stderr=""),
    )

    def _run(argv, **kwargs):
        calls.append(argv)
        if _is_work_call(argv):
            work_envs.append(kwargs["env"])
        return inner(argv, **kwargs)

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _run)

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)
    assert (result.attempted, result.recovered, result.exit_code) == (True, True, 0)
    assert calls[1][1] == "exec", "reachability is probed before the slot is bet on it"
    assert "danger-full-access" not in calls[1], "the probe must not be able to write"
    assert "danger-full-access" in calls[2]
    assert "--ignore-user-config" in calls[1]
    assert "--ignore-user-config" in calls[2]
    assert calls[1][calls[1].index("-m") + 1] == codex_failover.CODEX_MODEL
    assert calls[2][calls[2].index("-m") + 1] == codex_failover.CODEX_MODEL
    assert "claimed task X" in result.output_tail
    assert len(work_envs) == 1
    assert work_envs[0]["VOLPRED_PROVIDER_ID"] == "codex-cli"
    assert work_envs[0]["VOLPRED_PROVIDER_MODEL_ID"] == codex_failover.CODEX_MODEL
    assert len(work_envs[0]["VOLPRED_PROVIDER_REGISTRY_SHA256"]) == 64


def test_registry_denial_prevents_any_codex_subprocess(monkeypatch) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover,
        "_authorize_codex",
        lambda *_a: (_ for _ in ()).throw(
            codex_failover.ProviderRegistryError("paid overflow")
        ),
    )
    monkeypatch.setattr(
        codex_failover.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("policy denial must precede provider I/O"),
    )

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)

    assert result.attempted is False
    assert result.exit_code == codex_failover.RC_POLICY_DENIED
    assert "paid overflow" in result.detail


def test_api_key_environment_prevents_all_codex_subprocesses(
    monkeypatch,
) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "metered-secret")
    monkeypatch.setattr(
        codex_failover.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("API key denial must precede provider I/O"),
    )

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)

    assert result.exit_code == codex_failover.RC_POLICY_DENIED


def test_isolated_codex_scrubs_before_every_authorize_and_spawn(
    monkeypatch,
    tmp_path: Path,
) -> None:
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
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "claude-only")
    authorized: list[dict[str, str]] = []
    spawned: list[dict[str, str]] = []

    def authorize(codex_bin, environment):
        authorized.append(dict(environment))
        return SimpleNamespace(
            resolved_executable=codex_bin,
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "codex-cli",
                "VOLPRED_PROVIDER_MODEL_ID": codex_failover.CODEX_MODEL,
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
        )

    def run(argv, **kwargs):
        spawned.append(dict(kwargs["env"]))
        if argv[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="codex-cli", stderr="")
        if _is_work_call(argv):
            return SimpleNamespace(returncode=0, stdout="done", stderr="")
        return _PROBE_OK

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover, "_authorize_codex", authorize)
    monkeypatch.setattr(codex_failover.subprocess, "run", run)

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="abcdef123456",
    )

    assert result.recovered is True
    assert len(authorized) == len(spawned) == 3
    for env in (*authorized, *spawned):
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
            assert key not in env


def test_tracked_failover_reports_popen_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover, "preflight", lambda *_a, **_k: (True, 0, "codex"))
    monkeypatch.setattr(codex_failover, "check_reachable", lambda *_a, **_k: (True, 0, "ok"))

    class FakeProc:
        pid = 777
        returncode = 0

        def communicate(self, timeout=None):
            return "tracked work", None

    launched: dict = {}

    def _popen(*args, **kwargs):
        launched.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(codex_failover.subprocess, "Popen", _popen)
    monkeypatch.setattr(codex_failover.os, "getpgid", lambda pid: 888)
    monkeypatch.setattr(codex_failover.procutil, "pgid_members_checked", lambda pgid: [])
    seen: list[tuple] = []

    result = codex_failover.run_codex_failover(
        reason="quota", enabled=True, slot_id="slot-2", job_id="abcdef123456",
        on_process_started=lambda pid, pgid: bool(seen.append(("start", pid, pgid)) or True),
        on_process_finished=lambda pid: seen.append(("finish", pid)),
    )

    assert result.recovered is True
    assert seen == [("start", 777, 888), ("finish", 777)]
    assert launched["env"]["VOLPRED_TASK_CLAIM_OWNER"] == (
        "codex-failover-slot-2-abcdef123456"
    )


def test_tracked_failover_keeps_pid_attached_when_timeout_kill_is_unverified(
    monkeypatch, tmp_path,
) -> None:
    """A refused SIGKILL must leave the Codex child visible to the watchdog."""
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover, "preflight", lambda *_a, **_k: (True, 0, "codex"))
    monkeypatch.setattr(codex_failover, "check_reachable", lambda *_a, **_k: (True, 0, "ok"))

    class FakeProc:
        pid = 777
        returncode = None
        calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd="codex exec", timeout=timeout or 1, output="timed out",
                )
            self.returncode = 137
            return "parent exited; descendant survived", None

    monkeypatch.setattr(codex_failover.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(codex_failover.os, "getpgid", lambda pid: 888)
    monkeypatch.setattr(
        codex_failover.termination, "_target_identity",
        lambda kind, target: f"{kind}:{target}:start",
    )
    monkeypatch.setattr(
        codex_failover.procutil, "kill_pgid", lambda pgid, **_kwargs: False,
    )
    seen: list[tuple] = []

    result = codex_failover.run_codex_failover(
        reason="quota", enabled=True, slot_id="slot-2", job_id="abcdef123456",
        on_process_started=lambda pid, pgid: bool(seen.append(("start", pid, pgid)) or True),
        on_process_finished=lambda pid: seen.append(("finish", pid)),
        state_path=tmp_path / "dispatch_state.json",
    )

    assert result.recovered is False
    assert result.process_active is True
    assert seen == [("start", 777, 888)], "unverified live pid must not be detached"


def test_tracked_failover_keeps_pid_when_parent_exits_but_descendant_survives(
    monkeypatch,
) -> None:
    """A dead CLI leader is not proof that its process group drained."""
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover, "preflight", lambda *_a, **_k: (True, 0, "codex"))
    monkeypatch.setattr(codex_failover, "check_reachable", lambda *_a, **_k: (True, 0, "ok"))

    class FakeProc:
        pid = 777
        returncode = 0

        def communicate(self, timeout=None):
            return "parent done", None

    monkeypatch.setattr(codex_failover.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(codex_failover.os, "getpgid", lambda pid: 888)
    monkeypatch.setattr(codex_failover.procutil, "pgid_members_checked", lambda pgid: [999])
    seen: list[tuple] = []

    result = codex_failover.run_codex_failover(
        reason="quota", enabled=True, slot_id="slot-2", job_id="abcdef123456",
        on_process_started=lambda pid, pgid: bool(seen.append(("start", pid, pgid)) or True),
        on_process_finished=lambda pid: seen.append(("finish", pid)),
    )

    assert result.recovered is False
    assert result.process_active is True
    assert seen == [("start", 777, 888)]


def test_exec_failure_is_attempted_but_not_recovered(monkeypatch) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _fake_codex(
        probe=_PROBE_OK,
        work=SimpleNamespace(returncode=1, stdout="", stderr="401 unauthorized"),
    ))

    result = codex_failover.run_codex_failover(reason="auth", enabled=True)
    assert (result.attempted, result.recovered, result.exit_code) == (True, False, 1)


# ── the 2026-07-12 misdiagnosis ──────────────────────────────────────────────
# `codex exec` answered a smoke prompt in 13 seconds the same morning the platform
# emailed the owner that it was unavailable. Nothing was wrong with Codex: the slot
# handed it a whole hourly task (claim → finish → commit) inside a 600s cap, killed
# it mid-flight, and reported the one thing it had never measured — 「ChatGPT 端可能
# 同時不可用」. The owner went looking for a CLI regression that did not exist.

def test_work_timeout_does_not_accuse_an_api_that_just_answered(monkeypatch) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _fake_codex(
        probe=_PROBE_OK,  # ChatGPT demonstrably alive, seconds earlier
        work=subprocess.TimeoutExpired(cmd="codex exec", timeout=2400, output="partial work"),
    ))

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)

    assert (result.attempted, result.recovered) == (True, False)
    assert result.exit_code == codex_failover.RC_WORK_TIMEOUT
    assert "partial work" in result.output_tail
    assert "不可用" not in result.detail, "the probe proved otherwise — do not guess"
    assert "沒在" in result.detail and "分鐘內做完" in result.detail


def test_unreachable_api_skips_the_slot_rather_than_blaming_the_task(monkeypatch) -> None:
    """The other half: when ChatGPT really is down, the probe says so in seconds and
    no task is claimed — `attempted=False`, a skipped slot, not a failed handover."""
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", _fake_codex(
        probe=SimpleNamespace(returncode=1, stdout="", stderr="quota exceeded"),
        work=SimpleNamespace(returncode=0, stdout="should never run", stderr=""),
    ))

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)

    assert result.attempted is False, "nothing was claimed — the slot was skipped"
    assert result.exit_code == codex_failover.RC_UNREACHABLE
    assert "額度" in result.detail
    assert "quota exceeded" in result.detail, "say what ChatGPT actually replied"


def test_work_cap_fits_the_work_it_hands_over(monkeypatch) -> None:
    """The cap that caused the incident. The handover prompt is a full hourly task,
    and real tasks run 20-60 minutes; 600s could only ever kill healthy work. If a
    future edit shrinks this back under the task it dispatches, it fails here."""
    assert codex_failover.FAILOVER_CAP_S >= 1800, "a real task does not fit in 10 minutes"
    assert codex_failover.FAILOVER_CAP_S <= 3000, "must still end inside the fire's ceiling"
    assert codex_failover.REACHABILITY_TIMEOUT_S <= 120, "liveness is a question of seconds"


def test_missing_prompt_file_falls_back_and_logs(monkeypatch, caplog, tmp_path) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger=codex_failover.__name__):
        prompt = codex_failover._read_prompt(tmp_path / "nope.md")
    assert prompt == codex_failover.FALLBACK_PROMPT
    assert "failover prompt unreadable" in caplog.text


def test_shipped_prompt_file_exists() -> None:
    """The failover prompt is the contract with Codex — losing it degrades the slot."""
    assert codex_failover.PROMPT_PATH.is_file()


def test_shipped_and_fallback_prompts_share_external_report_contract(
    tmp_path: Path,
) -> None:
    shipped = codex_failover._read_prompt(codex_failover.PROMPT_PATH)
    fallback = codex_failover._read_prompt(tmp_path / "missing.md")

    for prompt in (shipped, fallback):
        assert "所有對外 Email、Telegram 與最終回報" in prompt
        assert "[新架構派發]" in prompt
        assert "現在健康只能證明已恢復" in prompt
        assert "不能把先前告警改稱誤報" in prompt


# ── worker wiring ──────────────────────────────────────────────────────────

class _FailoverStub:
    def __init__(self, recovered: bool) -> None:
        self.recovered = recovered
        self.seen_reasons: list[str] = []

    def __call__(self, *, reason: str, **_kwargs):
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
    def _attempt(**kwargs):
        worker.state.mark_job_phase(
            job_id=kwargs["job_id"], phase="classifying",
            expected_attempt=kwargs["attempt"], path=kwargs["state_path"],
        )
        return exit_code, 1.0, output

    monkeypatch.setattr(
        worker, "_run_one_attempt",
        _attempt,
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

    def _boom(*, reason: str, **_kwargs):
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
