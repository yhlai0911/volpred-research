"""Actor-attribution instrumentation for the dispatch pipeline (2026-07-10).

Covers the fix for the attribution gap that stalled the pregate enforce flip
(docs/error_log.md 2026-07-10): no automated path exported VOLPRED_ACTOR, so
197/200 recent writer_log lines logged actor="unknown".

Two enforcement points, ONE mechanism (VOLPRED_ACTOR + writer_log — no second
provenance system, per .claude/rules/control-plane.md anti-stacking):
  - worker spawns the agent with a per-fire VOLPRED_ACTOR stamp (extending, not
    replacing, os.environ) so the agent's shared-state writes are attributed.
  - the supervisor daemon defaults VOLPRED_ACTOR=dispatch-supervisor at boot so
    its own writes (writer_log; phase_z runs in-process) are attributed too.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from scripts.dispatch_supervisor import identity, scheduler, supervisor, worker
from volpred.ops import writer_log


class _FakeProc:
    """Minimal Popen stand-in: a real pid (so os.getpgid works) that exits 0."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _neutralize_state(monkeypatch) -> None:
    """Stub the state/procutil side effects of _run_one_attempt so a test can
    drive it without touching real dispatch state."""
    monkeypatch.setattr(worker.state, "reserve_fire", lambda **_kw: None)
    monkeypatch.setattr(worker.state, "attach_process", lambda **_kw: None)
    monkeypatch.setattr(worker.state, "update_started_wall", lambda **_kw: None)
    monkeypatch.setattr(worker.state, "release_reservation", lambda **_kw: None)
    monkeypatch.setattr(worker.procutil, "get_process_start_wall", lambda _pid: None)


# ── _dispatch_actor: value locates the fire ──────────────────────────────────


def test_dispatch_actor_locates_fire() -> None:
    from datetime import datetime

    actor = worker._dispatch_actor(
        "volpred-hourly-dispatch", now=datetime(2026, 7, 10, 14, 7)
    )
    # schedule id (which dispatcher) + HHMM (which fire) — both recoverable.
    assert actor == "dispatch-worker:volpred-hourly-dispatch:1407"


# ── worker spawn env: stamped AND an extension of os.environ ──────────────────


def test_run_one_attempt_env_is_os_environ_extension(tmp_path: Path, monkeypatch) -> None:
    _neutralize_state(monkeypatch)
    monkeypatch.setenv("VOLPRED_ACTOR", "dispatch-supervisor")  # daemon default
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        worker,
        "authorize_provider_spawn",
        lambda **kwargs: SimpleNamespace(
            resolved_executable=kwargs["executable_path"],
            settings_path="/tmp/pinned-claude-settings.json",
            environment=lambda: {
                "VOLPRED_PROVIDER_ID": "claude-cli",
                "VOLPRED_PROVIDER_REGISTRY_SHA256": "a" * 64,
            },
        ),
    )
    monkeypatch.setattr(worker, "verify_spawn_receipt", lambda _receipt: None)

    captured: dict[str, dict[str, str]] = {}

    def _capture_spawn(*, argv, log_path, env=None, cwd=None):
        captured["env"] = env
        return _FakeProc(os.getpid())

    monkeypatch.setattr(worker, "_spawn", _capture_spawn)

    worker._run_one_attempt(
        prompt_text="x",
        model="claude-opus-5",
        timeout_s=10,
        log_path=tmp_path / "worker.log",
        attempt=1,
        schedule_id="volpred-hourly-dispatch",
        state_path=tmp_path / "state.json",
    )

    env = captured["env"]
    assert env is not None, "worker must pass an explicit env, not inherit"
    # per-fire actor OVERRIDES the inherited daemon default so agent writes carry
    # the fire, not the supervisor.
    assert env["VOLPRED_ACTOR"].startswith("dispatch-worker:volpred-hourly-dispatch:")
    # extension, not replacement — PATH (auth, HOME, …) survive or the child
    # would lose its ability to exec / authenticate.
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["VOLPRED_TASK_CLAIM_OWNER"] == "hourly-slot-1-direct-smoke"
    # The keys the worker OWNS: it stamps them to locate the fire. Listing
    # only VOLPRED_ACTOR made this test pass everywhere except inside a real
    # dispatch fire — where VOLPRED_DISPATCH_JOB_ID is already in the ambient
    # environment, so the loop compared the supervisor's job id against the one
    # the worker just stamped. It went red the first time the hourly agent ran
    # the suite (2026-07-14). A test must not depend on who is running it.
    for key, value in os.environ.items():
        if key in (
            "VOLPRED_ACTOR", "VOLPRED_DISPATCH_SLOT",
            "VOLPRED_DISPATCH_JOB_ID", "VOLPRED_TASK_CLAIM_OWNER",
            "VOLPRED_PROVIDER_ID", "VOLPRED_PROVIDER_REGISTRY_SHA256",
        ):
            continue
        assert env.get(key) == value


def test_task_claim_owner_is_unique_across_same_hour_slots_and_stable_on_retry() -> None:
    slot_1_attempt_1 = identity.task_claim_owner(
        role="hourly", slot_id="slot-1", job_id="job-a",
    )
    slot_1_attempt_2 = identity.task_claim_owner(
        role="hourly", slot_id="slot-1", job_id="job-a",
    )
    slot_2_same_hour = identity.task_claim_owner(
        role="hourly", slot_id="slot-2", job_id="job-b",
    )
    assert slot_1_attempt_1 == slot_1_attempt_2
    assert slot_1_attempt_1 != slot_2_same_hour
    assert slot_1_attempt_1 == "hourly-slot-1-job-a"


def test_codex_failover_owner_retains_codex_eligibility_prefix() -> None:
    owner = identity.task_claim_owner(
        role="codex-failover", slot_id="slot-2", job_id="abcdef123456",
    )
    assert owner == "codex-failover-slot-2-abcdef123456"


def test_phase_z_cohort_maps_to_both_possible_executor_owners() -> None:
    owners = scheduler._phase_z_claim_owners([
        {"slot_id": 2, "job_id": "abcdef123456"},
    ])
    assert owners == {
        "hourly-slot-2-abcdef123456",
        "codex-failover-slot-2-abcdef123456",
    }


def test_dispatch_prompts_use_only_supervisor_issued_claim_owner() -> None:
    root = Path(__file__).resolve().parents[1]
    primary = (root / "scripts" / "cron_hourly_dispatch_prompt.md").read_text(
        encoding="utf-8",
    )
    failover = (
        root / "scripts" / "cron_hourly_dispatch_codex_failover_prompt.md"
    ).read_text(encoding="utf-8")
    assert "VOLPRED_TASK_CLAIM_OWNER" in primary
    assert "VOLPRED_TASK_CLAIM_OWNER" in failover
    assert "hourly-$(date +%H)" not in primary
    assert "--owner codex-failover" not in failover
    assert "--actor codex-failover" not in failover


def test_spawn_env_reaches_child_process(tmp_path: Path) -> None:
    """End-to-end: the env dict handed to _spawn actually lands in the child."""
    import sys

    log_path = tmp_path / "child.log"
    child_env = {**os.environ, "VOLPRED_ACTOR": "dispatch-worker:test:0000"}
    proc = worker._spawn(
        argv=[sys.executable, "-c", "import os,sys; sys.stdout.write(os.environ['VOLPRED_ACTOR'])"],
        log_path=log_path,
        env=child_env,
    )
    assert proc.wait(timeout=30) == 0
    assert log_path.read_text(encoding="utf-8") == "dispatch-worker:test:0000"


# ── writer_log: env-driven actor, unchanged fallback ─────────────────────────


def _read_last_writer_log(storage_dir: str) -> dict:
    path = Path(storage_dir) / "ops" / "writer_log.jsonl"
    return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])


def test_writer_log_stamps_actor_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VOLPRED_ACTOR", "dispatch-worker:volpred-hourly-dispatch:1407")
    writer_log.append_writer_log(
        "memory", "memory/knowledge.json", record_id="K999", storage_dir=str(tmp_path)
    )
    assert _read_last_writer_log(str(tmp_path))["actor"] == (
        "dispatch-worker:volpred-hourly-dispatch:1407"
    )


def test_writer_log_falls_back_to_unknown_without_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VOLPRED_ACTOR", raising=False)
    writer_log.append_writer_log(
        "memory", "memory/knowledge.json", record_id="K999", storage_dir=str(tmp_path)
    )
    # pre-fix behaviour preserved: no env, no explicit actor → "unknown".
    assert _read_last_writer_log(str(tmp_path))["actor"] == "unknown"


# ── supervisor / phase_z: daemon self-attribution ────────────────────────────


def test_set_runtime_env_defaults_actor(monkeypatch) -> None:
    monkeypatch.delenv("VOLPRED_ACTOR", raising=False)
    supervisor._set_runtime_env()
    assert os.environ["VOLPRED_ACTOR"] == "dispatch-supervisor"


def test_set_runtime_env_respects_operator_override(monkeypatch) -> None:
    monkeypatch.setenv("VOLPRED_ACTOR", "operator-override")
    supervisor._set_runtime_env()
    # setdefault — an explicit env wins over the daemon default.
    assert os.environ["VOLPRED_ACTOR"] == "operator-override"


def test_supervisor_actor_flows_to_writer_log(tmp_path: Path, monkeypatch) -> None:
    """After boot, any shared-state write from the supervisor process (writer_log;
    phase_z runs in-process) is attributed to the daemon, not 'unknown'."""
    monkeypatch.delenv("VOLPRED_ACTOR", raising=False)
    supervisor._set_runtime_env()
    writer_log.append_writer_log(
        "control_plane", "ops/dispatch_state.json", storage_dir=str(tmp_path)
    )
    assert _read_last_writer_log(str(tmp_path))["actor"] == "dispatch-supervisor"
