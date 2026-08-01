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

from volpred.ops.execution.registry import (
    ProviderExecutionContract,
    load_provider_registry,
)

from scripts.dispatch_supervisor import (
    codex_failover,
    custody_receipt,
    state,
    worker,
)

VALID_PRODUCER_CUSTODY = {
    "version": 2,
    "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
    "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
    "resource_coalition_id": 73,
    "trusted_unique_ids": [1001],
}


@pytest.fixture(autouse=True)
def _provider_guard_stub(monkeypatch):
    def authorize(
        codex_bin,
        environment,
        *,
        contract_id,
    ):
        forbidden = [
            key
            for key in ("OPENAI_API_KEY", "CODEX_API_KEY")
            if environment.get(key)
        ]
        if forbidden:
            raise codex_failover.ProviderRegistryError(
                f"forbidden API-key variables {forbidden}"
            )
        reasoning_effort_profile = (
            "probe"
            if contract_id == codex_failover.CODEX_PROBE_CONTRACT_ID
            else "work"
        )
        effort = {"probe": "low", "work": "ultra"}[
            reasoning_effort_profile
        ]
        registry_sha256 = "a" * 64
        provider_environment = {
            "VOLPRED_PROVIDER_ID": "codex-cli",
            "VOLPRED_PROVIDER_LAUNCH_CONTRACT": contract_id,
            "VOLPRED_PROVIDER_MODEL_ID": codex_failover.CODEX_MODEL,
            "VOLPRED_PROVIDER_REGISTRY_SHA256": registry_sha256,
        }
        if reasoning_effort_profile is not None:
            provider_environment.update({
                "VOLPRED_PROVIDER_REASONING_EFFORT_PROFILE": (
                    reasoning_effort_profile
                ),
                "VOLPRED_PROVIDER_REASONING_EFFORT": effort,
            })
        return SimpleNamespace(
            resolved_executable=codex_bin,
            model_id=codex_failover.CODEX_MODEL,
            reasoning_effort=effort,
            reasoning_effort_profile=reasoning_effort_profile,
            environment=lambda: provider_environment,
            execution_contract=lambda: ProviderExecutionContract(
                provider_id="codex-cli",
                launch_contract_id=contract_id,
                model_id=codex_failover.CODEX_MODEL,
                reasoning_effort_profile=reasoning_effort_profile,
                reasoning_effort=effort,
                registry_sha256=registry_sha256,
            ),
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
    assert calls[1][calls[1].index("-c") + 1] == (
        'model_reasoning_effort="low"'
    )
    assert calls[2][calls[2].index("-c") + 1] == (
        'model_reasoning_effort="ultra"'
    )
    assert result.execution_contract is not None
    assert result.execution_contract.model_id == codex_failover.CODEX_MODEL
    assert result.execution_contract.reasoning_effort == "ultra"
    assert "claimed task X" in result.output_tail
    assert len(work_envs) == 1
    assert work_envs[0]["VOLPRED_PROVIDER_ID"] == "codex-cli"
    assert work_envs[0]["VOLPRED_PROVIDER_MODEL_ID"] == codex_failover.CODEX_MODEL
    assert len(work_envs[0]["VOLPRED_PROVIDER_REGISTRY_SHA256"]) == 64


def test_all_codex_boundaries_scrub_supervisor_private_environment(
    monkeypatch,
) -> None:
    environments: list[dict[str, str]] = []
    for key in (
        "VOLPRED_SUPERVISOR_RELEASE_ID",
        "VOLPRED_SUPERVISOR_FUTURE_MARKER",
        "VOLPRED_DEFERRED_RELOAD_ROOT",
        "VOLPRED_CANONICAL_REPO_ROOT",
    ):
        monkeypatch.setenv(key, f"private-{key.lower()}")
    monkeypatch.setenv("VOLPRED_ACTOR", "dispatch-supervisor")

    inner = _fake_codex(
        probe=_PROBE_OK,
        work=SimpleNamespace(returncode=0, stdout="done", stderr=""),
    )

    def run(argv, **kwargs):
        environments.append(dict(kwargs["env"]))
        return inner(argv, **kwargs)

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover.subprocess, "run", run)

    result = codex_failover.run_codex_failover(reason="quota", enabled=True)

    assert result.recovered is True
    assert len(environments) == 3
    for environment in environments:
        assert environment["VOLPRED_ACTOR"] == "dispatch-supervisor"
        assert not any(
            key.startswith(
                ("VOLPRED_SUPERVISOR_", "VOLPRED_DEFERRED_RELOAD_")
            )
            for key in environment
        )
        assert "VOLPRED_CANONICAL_REPO_ROOT" not in environment


def test_registry_denial_prevents_any_codex_subprocess(monkeypatch) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover,
        "_authorize_codex",
        lambda *_a, **_k: (_ for _ in ()).throw(
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
    source_home = tmp_path / "source-home"
    auth_source = source_home / ".codex" / "auth.json"
    auth_source.parent.mkdir(parents=True)
    auth_source.write_text(
        '{"OPENAI_API_KEY":null,"tokens":{"access_token":"subscription",'
        '"refresh_token":"refresh","id_token":"id","account_id":"account"}}',
        encoding="utf-8",
    )
    auth_source.chmod(0o600)
    monkeypatch.setattr(
        codex_failover.isolation,
        "_credential_home",
        lambda: source_home,
    )

    def authorize(
        codex_bin,
        environment,
        *,
        contract_id,
    ):
        authorized.append(dict(environment))
        reasoning_effort_profile = (
            "probe"
            if contract_id == codex_failover.CODEX_PROBE_CONTRACT_ID
            else "work"
        )
        effort = {"probe": "low", "work": "ultra"}[
            reasoning_effort_profile
        ]
        return SimpleNamespace(
            resolved_executable=codex_bin,
            model_id=codex_failover.CODEX_MODEL,
            reasoning_effort=effort,
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "codex-cli",
                "VOLPRED_PROVIDER_MODEL_ID": codex_failover.CODEX_MODEL,
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
            execution_contract=lambda: ProviderExecutionContract(
                provider_id="codex-cli",
                launch_contract_id=contract_id,
                model_id=codex_failover.CODEX_MODEL,
                reasoning_effort_profile=reasoning_effort_profile,
                reasoning_effort=effort,
                registry_sha256="a" * 64,
            ),
        )

    def run(argv, **kwargs):
        spawned.append(dict(kwargs["env"]))
        assert (
            Path(kwargs["env"]["HOME"]) / ".codex" / "auth.json"
        ).is_file()
        if argv[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout="codex-cli", stderr="")
        return _PROBE_OK

    class FakeProc:
        pid = 777
        returncode = 0

        def communicate(self, timeout=None):
            return "done", None

    def popen(argv, **kwargs):
        spawned.append(dict(kwargs["env"]))
        assert _is_work_call(argv)
        assert (
            Path(kwargs["env"]["HOME"]) / ".codex" / "auth.json"
        ).is_file()
        return FakeProc()

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(codex_failover, "_authorize_codex", authorize)
    monkeypatch.setattr(codex_failover.subprocess, "run", run)
    monkeypatch.setattr(codex_failover.subprocess, "Popen", popen)
    monkeypatch.setattr(codex_failover.os, "getpgid", lambda _pid: 777)
    monkeypatch.setattr(
        codex_failover.procutil,
        "get_process_start_wall",
        lambda _pid: "Mon Jul 28 12:00:00 2026",
    )
    monkeypatch.setattr(
        codex_failover.procutil,
        "pgid_members_checked",
        lambda _pgid: [],
    )
    monkeypatch.setattr(
        codex_failover.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody: [],
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="abcdef123456",
        on_process_started=lambda _pid, _pgid: True,
        producer_custody=VALID_PRODUCER_CUSTODY,
        provider_auth_receipt_root=tmp_path / "provider-auth-receipts",
    )

    assert result.recovered is True
    assert len(authorized) == len(spawned) == 3
    for env in (*authorized, *spawned):
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
            assert key not in env
    assert not (run_dir / "home" / ".codex" / "auth.json").exists()


def test_isolated_codex_unexpected_exception_still_closes_auth_lease(
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
    closed: list[bool] = []

    class FakeLease:
        def close(self):
            closed.append(True)
            return codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover.isolation,
        "materialize_provider_auth",
        lambda *_a, **_k: FakeLease(),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "isolated_environment",
        lambda env, *_a, **_k: dict(env),
    )
    monkeypatch.setattr(
        codex_failover,
        "preflight",
        lambda *_a, **_k: (True, 0, "codex"),
    )
    monkeypatch.setattr(
        codex_failover,
        "check_reachable",
        lambda *_a, **_k: (True, 0, "ok"),
    )
    monkeypatch.setattr(
        codex_failover,
        "_read_prompt",
        lambda _path: (_ for _ in ()).throw(RuntimeError("injected prompt error")),
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="abcdef123456",
        producer_custody=VALID_PRODUCER_CUSTODY,
    )

    assert result.recovered is False
    assert result.exit_code == codex_failover.RC_DISABLED
    assert "injected prompt error" in result.detail
    assert closed == [True]


def test_isolated_codex_materialization_binds_exact_custody_identity(
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
    custody = {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001],
    }
    captured: list[dict] = []

    class FakeLease:
        recovery_receipt_path = str(tmp_path / "lease.json")

        def close(self):
            return codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    def materialize(*_args, **kwargs):
        captured.append(kwargs)
        return FakeLease()

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover.isolation, "materialize_provider_auth", materialize,
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "isolated_environment",
        lambda env, *_a, **_k: dict(env),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "reap_provider_auth_lease_for_custody_in_process",
        lambda _lease, **_kwargs: (
            codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )
        ),
    )
    monkeypatch.setattr(
        codex_failover,
        "preflight",
        lambda *_a, **_k: (False, 9, "stop after materialization"),
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="d" * 32,
        attempt=3,
        producer_custody=custody,
    )

    assert result.exit_code == 9
    assert captured == [{
        "provider_id": "codex-cli",
            "job_id": "d" * 32,
            "attempt": 3,
            "producer_custody": custody,
            "receipt_root": None,
            "live_writer_state_path": state.STATE_PATH,
        }]


@pytest.mark.parametrize("producer_custody", [None, {}])
def test_isolated_codex_missing_or_invalid_custody_fails_before_materialization(
    monkeypatch,
    tmp_path: Path,
    producer_custody,
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
    materialized: list[bool] = []

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover.isolation,
        "materialize_provider_auth",
        lambda *_a, **_k: materialized.append(True),
    )
    monkeypatch.setattr(
        codex_failover.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("invalid custody must fail before spawn"),
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="f" * 32,
        producer_custody=producer_custody,
    )

    assert result.exit_code == codex_failover.RC_DISABLED
    assert "exact producer custody" in result.detail
    assert materialized == []


def test_failover_guard_uses_full_custody_before_auth_close(monkeypatch) -> None:
    custody = {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001],
    }
    closed: list[bool] = []
    reaped: list[tuple[str, dict]] = []

    class FakeLease:
        recovery_receipt_path = "/tmp/provider-auth-v3.json"

        def close(self):
            closed.append(True)
            return codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    monkeypatch.setattr(
        codex_failover.isolation,
        "reap_provider_auth_lease_for_custody_in_process",
        lambda _lease, *, job_id, producer_custody: (
            reaped.append((job_id, producer_custody))
            or codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )
        ),
    )
    guard = codex_failover._ProviderAuthLeaseGuard(
        lease=FakeLease(),
        job_id="e" * 32,
        producer_custody=custody,
    )
    guard.mark_process_started(pid=777, pgid=777, started_wall="start")

    result = guard.finish(codex_failover.FailoverResult(
        attempted=True,
        recovered=False,
        exit_code=codex_failover.RC_WORK_TIMEOUT,
        detail="descendant alive",
        process_active=True,
    ))

    assert result.process_active is False
    assert reaped == [("e" * 32, custody)]
    assert closed == []


def test_active_descendant_hands_auth_lease_to_reaper_before_return(
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
    closed: list[bool] = []
    deferred: list[tuple[object, int, int, str]] = []

    class FakeLease:
        def close(self):
            closed.append(True)
            return codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    lease = FakeLease()

    class FakeProc:
        pid = 777
        returncode = None
        calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd="codex exec",
                    timeout=timeout or 1,
                    output="timed out",
                )
            self.returncode = 137
            return "descendant survived", None

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover.isolation,
        "materialize_provider_auth",
        lambda *_a, **_k: lease,
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "isolated_environment",
        lambda env, *_a, **_k: dict(env),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "wrap_prepared",
        lambda argv, _receipt: list(argv),
    )
    monkeypatch.setattr(
        codex_failover,
        "preflight",
        lambda *_a, **_k: (True, 0, "codex"),
    )
    monkeypatch.setattr(
        codex_failover,
        "check_reachable",
        lambda *_a, **_k: (True, 0, "ok"),
    )
    monkeypatch.setattr(codex_failover.subprocess, "Popen", lambda *_a, **_k: FakeProc())
    monkeypatch.setattr(codex_failover.os, "getpgid", lambda _pid: 888)
    monkeypatch.setattr(
        codex_failover.procutil,
        "get_process_start_wall",
        lambda _pid: "Mon Jul 28 12:00:00 2026",
    )
    monkeypatch.setattr(
        codex_failover.procutil,
        "kill_producer_cohort",
        lambda _custody, **_kwargs: False,
    )
    monkeypatch.setattr(
        codex_failover.termination,
        "capture_target_identity",
        lambda kind, target: f"{kind}:{target}:start",
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "defer_provider_auth_cleanup",
        lambda auth_lease, *, pgid, leader_pid, leader_started_wall: (
            deferred.append(
                (auth_lease, pgid, leader_pid, leader_started_wall)
            )
        ),
        raising=False,
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="abcdef123456",
        on_process_started=lambda _pid, _pgid: True,
        producer_custody=VALID_PRODUCER_CUSTODY,
        state_path=tmp_path / "dispatch_state.json",
    )

    assert result.process_active is True
    assert closed == []
    assert deferred == [
        (lease, 888, 777, "Mon Jul 28 12:00:00 2026"),
    ]


def test_reaper_handoff_failure_retains_parent_custody_until_cleanup(
    monkeypatch,
    tmp_path: Path,
) -> None:
    close_receipt = codex_failover.isolation.ProviderAuthCloseReceipt(
        True, False, False, True, "closed",
    )

    class FakeLease:
        pass

    lease = FakeLease()
    guard = codex_failover._ProviderAuthLeaseGuard()
    guard.bind(lease)
    guard.mark_process_started(
        pid=777,
        pgid=888,
        started_wall="Mon Jul 28 12:00:00 2026",
    )
    custody: list[tuple[object, int, int, str]] = []

    def fail_handoff(*_args, **_kwargs):
        raise OSError("injected raw handoff failure")

    monkeypatch.setattr(
        codex_failover.isolation,
        "defer_provider_auth_cleanup",
        fail_handoff,
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "reap_provider_auth_lease_in_process",
        lambda auth_lease, *, pgid, leader_pid, leader_started_wall,
        receipt_path=None: (
            custody.append(
                (auth_lease, pgid, leader_pid, leader_started_wall)
            )
            or close_receipt
        ),
    )

    result = guard.finish(
        codex_failover.FailoverResult(
            True,
            False,
            codex_failover.RC_WORK_TIMEOUT,
            "timeout",
            process_active=True,
        ),
    )

    assert custody == [
        (lease, 888, 777, "Mon Jul 28 12:00:00 2026"),
    ]
    assert result.process_active is False
    assert guard.lease is None


def test_unreapable_no_ack_child_moves_lease_to_supervisor_quarantine(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeLease:
        lease_id = "lease-quarantine"

    class FakeProc:
        pid = 999

    lease = FakeLease()
    proc = FakeProc()
    guard = codex_failover._ProviderAuthLeaseGuard()
    guard.bind(lease)
    guard.mark_process_started(
        pid=888,
        pgid=888,
        started_wall="Mon Jul 28 12:00:00 2026",
    )
    receipt_path = tmp_path / "receipt.json"
    reaper_started_wall = "Mon Jul 28 12:00:01 2026"
    quarantined: list[tuple] = []

    monkeypatch.setattr(
        codex_failover.isolation,
        "defer_provider_auth_cleanup",
        lambda *_a, **_k: (_ for _ in ()).throw(
            codex_failover.isolation.ProviderAuthHandoffQuarantined(
                "injected no-ACK child",
                receipt_path=receipt_path,
                reaper_process=proc,
                reaper_started_wall=reaper_started_wall,
            )
        ),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "quarantine_provider_auth_lease",
        lambda auth_lease, **kwargs: quarantined.append(
            (auth_lease, kwargs)
        ),
    )

    result = guard.finish(
        codex_failover.FailoverResult(
            True,
            False,
            codex_failover.RC_WORK_TIMEOUT,
            "timeout",
            process_active=True,
        ),
    )

    assert result.process_active is True
    assert guard.lease is None
    assert quarantined[0][0] is lease
    assert quarantined[0][1]["reaper_process"] is proc
    assert (
        quarantined[0][1]["reaper_started_wall"]
        == reaper_started_wall
    )


def test_spawn_post_popen_probe_error_never_closes_live_auth_early(
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
    early_close: list[bool] = []
    custody: list[tuple[int, int, str | None]] = []

    class FakeLease:
        def close(self):
            early_close.append(True)
            return codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )

    class FakeProc:
        pid = 777

    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover.isolation,
        "materialize_provider_auth",
        lambda *_a, **_k: FakeLease(),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "isolated_environment",
        lambda env, *_a, **_k: dict(env),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "wrap_prepared",
        lambda argv, _receipt: list(argv),
    )
    monkeypatch.setattr(
        codex_failover,
        "preflight",
        lambda *_a, **_k: (True, 0, "codex"),
    )
    monkeypatch.setattr(
        codex_failover,
        "check_reachable",
        lambda *_a, **_k: (True, 0, "ok"),
    )
    monkeypatch.setattr(
        codex_failover.subprocess,
        "Popen",
        lambda *_a, **_k: FakeProc(),
    )
    monkeypatch.setattr(
        codex_failover.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(OSError("injected PGID probe")),
    )
    monkeypatch.setattr(
        codex_failover.isolation,
        "reap_provider_auth_lease_in_process",
        lambda _lease, *, pgid, leader_pid, leader_started_wall: (
            custody.append((pgid, leader_pid, leader_started_wall))
            or codex_failover.isolation.ProviderAuthCloseReceipt(
                True, False, False, True, "closed",
            )
        ),
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=workdir,
        isolated_workspace=isolated_workspace,
        slot_id="slot-1",
        job_id="abcdef123456",
        on_process_started=lambda _pid, _pgid: True,
        producer_custody=VALID_PRODUCER_CUSTODY,
    )

    assert result.exit_code == codex_failover.RC_DISABLED
    assert early_close == []
    assert custody == [(777, 777, None)]


def test_isolated_codex_partial_receipt_returns_typed_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(codex_failover, "resolve_codex_bin", lambda: "/bin/codex")
    monkeypatch.setattr(
        codex_failover.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("malformed receipt must fail before spawn"),
    )

    result = codex_failover.run_codex_failover(
        reason="quota",
        enabled=True,
        workdir=tmp_path,
        isolated_workspace={
            "path": str(tmp_path),
            "isolation_profile_path": str(tmp_path / "sandbox.sb"),
            "isolation_run_dir": str(tmp_path / "run"),
        },
        slot_id="slot-1",
        job_id="abcdef123456",
    )

    assert result.exit_code == codex_failover.RC_DISABLED
    assert "missing fields" in result.detail


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
        launched["args"] = args
        launched.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(codex_failover.subprocess, "Popen", _popen)
    monkeypatch.setattr(codex_failover.os, "getpgid", lambda pid: 888)
    monkeypatch.setattr(codex_failover.procutil, "pgid_members_checked", lambda pgid: [])
    seen: list[tuple] = []

    result = codex_failover.run_codex_failover(
        reason="quota", enabled=True, slot_id="slot-2", job_id="abcdef123456",
        preselected_task_id="article-starved",
        on_process_started=lambda pid, pgid: bool(seen.append(("start", pid, pgid)) or True),
        on_process_finished=lambda pid: seen.append(("finish", pid)),
    )

    assert result.recovered is True
    assert seen == [("start", 777, 888), ("finish", 777)]
    assert launched["env"]["VOLPRED_TASK_CLAIM_OWNER"] == (
        "codex-failover-slot-2-abcdef123456"
    )
    assert launched["env"]["VOLPRED_PRESELECTED_TASK_ID"] == "article-starved"
    argv = launched["args"][0]
    prompt = argv[-1]
    assert "task_id=article-starved" in prompt
    assert "$VOLPRED_PRESELECTED_TASK_ID" in prompt


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
        codex_failover.termination, "capture_target_identity",
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
    assert result.execution_contract is not None
    assert result.execution_contract.reasoning_effort == "ultra"


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
    assert result.execution_contract is not None
    assert result.execution_contract.reasoning_effort == "ultra"
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
    assert result.execution_contract is None
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
    def __init__(
        self,
        recovered: bool,
        *,
        attempted: bool | None = None,
        exit_code: int | None = None,
    ) -> None:
        self.recovered = recovered
        self.attempted = recovered if attempted is None else attempted
        self.exit_code = (
            0 if recovered else 1
        ) if exit_code is None else exit_code
        self.seen_reasons: list[str] = []
        self.seen_kwargs: list[dict] = []

    def __call__(self, *, reason: str, **kwargs):
        self.seen_reasons.append(reason)
        self.seen_kwargs.append(kwargs)
        execution_contract = (
            ProviderExecutionContract(
                provider_id="codex-cli",
                launch_contract_id="dispatch-supervisor.codex-failover",
                model_id=codex_failover.CODEX_MODEL,
                reasoning_effort_profile="work",
                reasoning_effort="ultra",
                registry_sha256=load_provider_registry().sha256,
            )
            if self.attempted
            else None
        )
        return codex_failover.FailoverResult(
            attempted=self.attempted,
            recovered=self.recovered,
            exit_code=self.exit_code,
            detail="stub", duration_s=1.0, output_tail="codex output",
            execution_contract=execution_contract,
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
        preselected_task_id="article-starved",
    )

    assert stub.seen_reasons == ["quota"]
    assert stub.seen_kwargs[0]["preselected_task_id"] == "article-starved"
    assert result.outcome == "codex_failover_recovered"
    assert result.exit_code == 0
    assert result.final_model == worker.CODEX_MODEL_LABEL


def test_codex_recovery_completion_receipt_records_model_and_effort(
    monkeypatch,
    tmp_path,
    _quiet_state_and_alerts,
) -> None:
    receipts: list[dict] = []
    monkeypatch.setattr(
        worker.state,
        "record_completion",
        lambda **kwargs: receipts.append(kwargs) or {},
    )
    _stub_attempt(monkeypatch, QUOTA_OUTPUT)
    monkeypatch.setattr(
        worker.codex_failover,
        "run_codex_failover",
        _FailoverStub(recovered=True),
    )

    result = worker.run_worker(
        prompt_text="tick",
        log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json",
        sleep_fn=lambda _s: None,
    )

    assert result.outcome == "codex_failover_recovered"
    contract = receipts[-1]["provider_execution_contract"]
    assert contract.model_id == codex_failover.CODEX_MODEL
    assert contract.reasoning_effort == "ultra"


def test_failed_codex_work_persists_its_execution_contract(
    monkeypatch,
    tmp_path,
    _quiet_state_and_alerts,
) -> None:
    receipts: list[dict] = []
    monkeypatch.setattr(
        worker.state,
        "record_completion",
        lambda **kwargs: receipts.append(kwargs) or {},
    )
    _stub_attempt(monkeypatch, QUOTA_OUTPUT)
    monkeypatch.setattr(
        worker.codex_failover,
        "run_codex_failover",
        _FailoverStub(recovered=False, attempted=True, exit_code=9),
    )

    result = worker.run_worker(
        prompt_text="tick",
        log_path=tmp_path / "d.log",
        state_path=tmp_path / "s.json",
        sleep_fn=lambda _s: None,
    )

    assert result.outcome == "codex_failover_failed"
    assert result.exit_code == 9
    assert receipts[-1]["outcome"] == "codex_failover_failed"
    contract = receipts[-1]["provider_execution_contract"]
    assert contract.model_id == codex_failover.CODEX_MODEL
    assert contract.reasoning_effort == "ultra"


def test_completion_receipt_persists_codex_execution_contract(tmp_path) -> None:
    state_path = tmp_path / "dispatch_state.json"
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="claude-opus-5",
        log_path=str(tmp_path / "worker.log"),
        path=state_path,
    )

    contract = ProviderExecutionContract(
        provider_id="codex-cli",
        launch_contract_id="dispatch-supervisor.codex-failover",
        model_id=codex_failover.CODEX_MODEL,
        reasoning_effort_profile="work",
        reasoning_effort="ultra",
        registry_sha256=load_provider_registry().sha256,
    )
    entry = state.record_completion(
        job_id=lease.job_id,
        exit_code=0,
        outcome="codex_failover_recovered",
        final_model=worker.CODEX_MODEL_LABEL,
        provider_execution_contract=contract,
        path=state_path,
    )

    assert entry is not None
    persisted = state.read_state(state_path)["completions"][-1]
    assert persisted["provider_execution_contract"] == contract.as_dict()


def test_completion_receipt_rejects_partial_or_false_codex_contract(
    tmp_path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="claude-opus-5",
        log_path=str(tmp_path / "worker.log"),
        path=state_path,
    )
    valid = ProviderExecutionContract(
        provider_id="codex-cli",
        launch_contract_id="dispatch-supervisor.codex-failover",
        model_id=codex_failover.CODEX_MODEL,
        reasoning_effort_profile="work",
        reasoning_effort="ultra",
        registry_sha256=load_provider_registry().sha256,
    )

    with pytest.raises(TypeError, match="provider_model_id"):
        state.record_completion(
            job_id=lease.job_id,
            exit_code=0,
            outcome="codex_failover_recovered",
            final_model=worker.CODEX_MODEL_LABEL,
            provider_model_id=codex_failover.CODEX_MODEL,
            path=state_path,
        )
    forged = ProviderExecutionContract(
        provider_id="codex-cli",
        launch_contract_id="dispatch-supervisor.codex-failover",
        model_id=codex_failover.CODEX_MODEL,
        reasoning_effort_profile="work",
        reasoning_effort="turbo",
        registry_sha256=valid.registry_sha256,
    )
    with pytest.raises(ValueError, match="reasoning effort"):
        state.record_completion(
            job_id=lease.job_id,
            exit_code=1,
            outcome="codex_failover_failed",
            final_model=worker.CODEX_MODEL_LABEL,
            provider_execution_contract=forged,
            path=state_path,
        )
    probe = ProviderExecutionContract(
        provider_id="codex-cli",
        launch_contract_id="dispatch-supervisor.codex-probe",
        model_id=codex_failover.CODEX_MODEL,
        reasoning_effort_profile="probe",
        reasoning_effort="low",
        registry_sha256=valid.registry_sha256,
    )
    with pytest.raises(ValueError, match="launch contract"):
        state.record_completion(
            job_id=lease.job_id,
            exit_code=0,
            outcome="codex_failover_recovered",
            final_model=worker.CODEX_MODEL_LABEL,
            provider_execution_contract=probe,
            path=state_path,
        )
    for outcome, exit_code in (
        ("codex_failover_recovered", 1),
        ("codex_failover_failed", 0),
        ("codex_failover_timeout", 1),
    ):
        with pytest.raises(ValueError, match="exit code"):
            state.record_completion(
                job_id=lease.job_id,
                exit_code=exit_code,
                outcome=outcome,
                final_model=worker.CODEX_MODEL_LABEL,
                provider_execution_contract=valid,
                path=state_path,
            )
    with pytest.raises(ValueError, match="outcome"):
        state.record_completion(
            job_id=lease.job_id,
            exit_code=1,
            outcome="quota_blocked",
            final_model=worker.CODEX_MODEL_LABEL,
            provider_execution_contract=valid,
            path=state_path,
        )

    persisted = state.read_state(state_path)
    assert persisted["completions"] == []
    assert persisted["current_jobs"][0]["job_id"] == lease.job_id


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


def test_failover_descendant_survivor_keeps_global_custody_and_slot_quarantined(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    custody = {
        "version": 2,
        "host_uuid": "92515cc4-ec37-5659-923e-c700da4843a4",
        "boot_session_uuid": "05699489-50d5-4a6d-b11b-7aa4550f48ca",
        "resource_coalition_id": 73,
        "trusted_unique_ids": [1001],
    }
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=1,
        model="opus",
        log_path="/tmp/worker.log",
        path=state_path,
    )
    assert state.attach_producer_custody(
        job_id=lease.job_id,
        custody=custody,
        expected_attempt=1,
        path=state_path,
    )
    assert state.mark_producer_spawn_committed(
        job_id=lease.job_id,
        expected_attempt=1,
        path=state_path,
    )
    state.attach_process(
        job_id=lease.job_id,
        expected_attempt=1,
        pid=123,
        pgid=123,
        started_wall="start",
        path=state_path,
    )
    assert state.mark_job_phase(
        job_id=lease.job_id,
        expected_phase="running",
        expected_attempt=1,
        expected_pid=123,
        phase="codex_failover",
        detach_process=True,
        path=state_path,
    )
    custody_receipt.initialize_producer_custody_ledger(
        tmp_path,
        migration_confirmed_quiescent=True,
    )
    custody_receipt.bind_producer_custody(
        tmp_path,
        job_id=lease.job_id,
        attempt=1,
        custody=custody,
    )
    monkeypatch.setattr(
        worker.codex_failover,
        "run_codex_failover",
        lambda **_kwargs: codex_failover.FailoverResult(
            attempted=False,
            recovered=False,
            exit_code=codex_failover.RC_DISABLED,
            detail="disabled",
        ),
    )
    monkeypatch.setattr(
        worker.alerts,
        "send_codex_failover_alert",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        worker.procutil,
        "producer_cohort_members_checked",
        lambda _pgid, *, job_id, custody=None: [777],
    )
    monkeypatch.setattr(
        worker.procutil,
        "kill_producer_cohort",
        lambda *_args, **_kwargs: False,
    )

    result = worker._attempt_codex_failover(
        reason="quota",
        attempt=1,
        total_duration=5.0,
        fallback_exit=1,
        model="opus",
        log_tail="quota",
        state_path=state_path,
        job_id=lease.job_id,
        slot_id="slot-1",
        isolated_workspace={"isolation_canonical_root": str(tmp_path)},
    )

    assert result is not None
    assert result.outcome == "kill_failed_orphan"
    current = state.read_state(state_path)["current_job"]
    assert current["phase"] == "kill_failed_orphan"
    assert current["pid"] == 777
    assert state.read_state(state_path)["completions"] == []
    assert len(custody_receipt.read_pending_producer_custodies(tmp_path)) == 1


def test_stale_attempt_cannot_reuse_new_custody_or_spawn_failover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    lease = state.reserve_fire(
        schedule_id="hourly_dispatch",
        attempt=2,
        model="opus",
        log_path="/tmp/worker.log",
        path=state_path,
    )
    assert state.attach_producer_custody(
        job_id=lease.job_id,
        custody=VALID_PRODUCER_CUSTODY,
        expected_attempt=2,
        path=state_path,
    )
    provider_calls: list[bool] = []
    kill_calls: list[bool] = []
    alerts: list[dict] = []
    monkeypatch.setattr(
        worker.codex_failover,
        "run_codex_failover",
        lambda **_kwargs: provider_calls.append(True),
    )
    monkeypatch.setattr(
        worker.procutil,
        "kill_producer_cohort",
        lambda *_args, **_kwargs: kill_calls.append(True),
    )
    monkeypatch.setattr(
        worker.alerts,
        "send_codex_failover_alert",
        lambda **kwargs: alerts.append(kwargs) or True,
    )

    result = worker._attempt_codex_failover(
        reason="quota",
        attempt=1,
        total_duration=0,
        fallback_exit=1,
        model="opus",
        log_tail="quota",
        state_path=state_path,
        job_id=lease.job_id,
        slot_id="slot-1",
        workdir=tmp_path / "workspace",
        isolated_workspace={"isolation_canonical_root": str(tmp_path)},
    )

    assert result is None
    assert provider_calls == []
    assert kill_calls == []
    assert len(alerts) == 1
    assert alerts[0]["attempted"] is False
    assert "exact job/attempt producer custody" in alerts[0]["detail"]


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
