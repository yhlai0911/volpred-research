from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import redirect_stderr
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import terminate_dispatch_job, termination_signal
from scripts.dispatch_supervisor import state as supervisor_state
from volpred.ops import termination

ROOT = Path(__file__).resolve().parents[2]
STANDALONE_SCRIPT = ROOT / "scripts" / "termination_signal.py"


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stderr: str


@pytest.fixture
def spawn_process():
    processes: list[subprocess.Popen[bytes]] = []

    def spawn(
        argv: list[str] | None = None,
    ) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            argv or ["sleep", "30"],
            start_new_session=True,
        )
        processes.append(proc)
        return proc

    yield spawn

    for proc in processes:
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
            proc.wait(timeout=5)


def _started_wall(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return result.stdout.strip()


def _write_dispatch_state(
    path: Path,
    *,
    proc: subprocess.Popen[bytes],
    job_id: str = "job-a",
    attempt: int = 2,
    started_wall: str | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    job = {
        "job_id": job_id,
        "cohort_id": "cohort-a",
        "slot_id": 1,
        "phase": "running",
        "pid": proc.pid,
        "pgid": os.getpgid(proc.pid),
        "schedule_id": "agent_dispatch_tick",
        "started_at": now,
        "attempt_started_at": now,
        "attempt": attempt,
        "model": "test-model",
        "log_path": str(path.with_suffix(".log")),
        "started_wall": (
            _started_wall(proc.pid) if started_wall is None else started_wall
        ),
    }
    _write_state(path, [job])


def _write_state(path: Path, jobs: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "current_jobs": jobs,
                "current_job": jobs[0] if jobs else None,
            }
        ),
        encoding="utf-8",
    )


def _events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _run_formal_cli(
    *,
    target_id: int,
    state_path: Path,
    job_id: str | None = "job-a",
    attempt: int | None = 2,
    signal_name: str = "TERM",
    grace_seconds: float = 0.05,
    extra: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> CliResult:
    argv = [
        "--target-kind",
        "pgid",
        "--target-id",
        str(target_id),
        "--signal",
        signal_name,
        "--grace-seconds",
        str(grace_seconds),
        "--reason",
        "operator-drain",
        "--actor",
        "operations-manager",
    ]
    if job_id is not None:
        argv.extend(["--job-id", job_id])
    if attempt is not None:
        argv.extend(["--attempt", str(attempt)])
    argv.extend(extra or [])
    command_env = dict(os.environ) if env is None else dict(env)
    if env is None:
        command_env.pop(termination.LEDGER_PATH_ENV, None)
    stderr = StringIO()
    with patch.dict(os.environ, command_env, clear=True), redirect_stderr(stderr):
        try:
            returncode = terminate_dispatch_job.main(
                argv,
                state_path=state_path,
            )
        except SystemExit as exc:
            returncode = int(exc.code)
    return CliResult(returncode=returncode, stderr=stderr.getvalue())


def test_exact_dispatch_binding_records_identity_and_matches_worker_classifier(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    expected_identity = _started_wall(proc.pid)
    _write_dispatch_state(
        state_path,
        proc=proc,
        started_wall=expected_identity,
    )

    result = _run_formal_cli(target_id=pgid, state_path=state_path)

    assert result.returncode == 0, result.stderr
    proc.wait(timeout=5)
    ledger = termination.ledger_for_state(state_path)
    events = _events(ledger)
    assert [event["event"] for event in events] == [
        "intent_armed",
        "signal_attempted",
        "signal_result",
    ]
    assert {event["job_id"] for event in events} == {"job-a"}
    assert {event["attempt"] for event in events} == {2}
    assert events[-1]["status"] == "sent"
    assert events[-1]["target_identity"] == expected_identity
    matched = termination.match_sent_signal_for_job(
        target_kind="pgid",
        signum=signal.SIGTERM,
        job_id="job-a",
        attempt=2,
        ledger_path=ledger,
    )
    assert matched is not None
    assert matched["target_id"] == pgid


def test_formal_command_requires_complete_identity_before_arm(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)

    missing = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
        job_id=None,
        attempt=None,
    )
    partial = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
        attempt=None,
    )

    assert missing.returncode == 2
    assert partial.returncode == 2
    assert "--job-id" in missing.stderr
    assert "--attempt" in partial.stderr
    assert proc.poll() is None
    assert not termination.ledger_for_state(state_path).exists()


def test_formal_command_rejects_wrong_job_attempt_and_generation(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)

    wrong_job = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
        job_id="job-b",
    )
    wrong_attempt = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
        attempt=3,
    )
    _write_dispatch_state(
        state_path,
        proc=proc,
        started_wall="Mon Jan  1 00:00:00 2001",
    )
    stale_generation = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
    )

    assert wrong_job.returncode == 2
    assert wrong_attempt.returncode == 2
    assert stale_generation.returncode == 2
    assert "exactly one current dispatch job" in wrong_job.stderr
    assert "exactly one current dispatch job" in wrong_attempt.stderr
    assert "process generation differs" in stale_generation.stderr
    assert proc.poll() is None
    assert not termination.ledger_for_state(state_path).exists()


def test_state_loss_and_replay_fail_before_new_intent(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)
    state_path.unlink()

    lost_state = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
    )

    assert lost_state.returncode == 2
    assert "exactly one current dispatch job" in lost_state.stderr
    assert proc.poll() is None
    assert not termination.ledger_for_state(state_path).exists()

    _write_dispatch_state(state_path, proc=proc)
    sent = _run_formal_cli(target_id=pgid, state_path=state_path)
    assert sent.returncode == 0
    proc.wait(timeout=5)
    ledger = termination.ledger_for_state(state_path)
    before_replay = _events(ledger)

    replay = _run_formal_cli(target_id=pgid, state_path=state_path)

    assert replay.returncode == 2
    assert "process generation differs" in replay.stderr
    assert _events(ledger) == before_replay


def test_formal_cli_exposes_no_state_path_override(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    alternate = tmp_path / "alternate.json"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)
    _write_dispatch_state(alternate, proc=proc, job_id="forged", attempt=7)

    result = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
        extra=["--state-path", str(alternate)],
    )

    assert result.returncode == 2
    assert "unrecognized arguments: --state-path" in result.stderr
    assert proc.poll() is None
    assert not termination.ledger_for_state(state_path).exists()
    assert not termination.ledger_for_state(alternate).exists()


def test_formal_command_rejects_ledger_environment_override(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    override = tmp_path / "wrong_ledger.jsonl"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)

    result = _run_formal_cli(
        target_id=pgid,
        state_path=state_path,
        env={
            **os.environ,
            termination.LEDGER_PATH_ENV: str(override),
        },
    )

    assert result.returncode == 2
    assert "ledger override" in result.stderr
    assert proc.poll() is None
    assert not override.exists()
    assert not termination.ledger_for_state(state_path).exists()


def test_bound_term_kill_escalates_after_state_row_disappears(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    proc = spawn_process(
        [
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "time.sleep(30)"
            ),
        ]
    )
    time.sleep(0.1)
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)
    ledger = termination.ledger_for_state(state_path)
    real_sender = termination.send_pgid
    observed_signals: list[int] = []

    def synchronized_sender(intent, signum, **kwargs):
        if signum == signal.SIGKILL:
            assert supervisor_state.get_current_jobs(state_path) == []
        result = real_sender(intent, signum, **kwargs)
        observed_signals.append(signum)
        if signum == signal.SIGTERM:
            _write_state(state_path, [])
        return result

    with patch.object(
        terminate_dispatch_job.termination_command.termination,
        "send_pgid",
        side_effect=synchronized_sender,
    ):
        result = _run_formal_cli(
            target_id=pgid,
            state_path=state_path,
            signal_name="TERM_KILL",
            grace_seconds=0.05,
        )

    assert result.returncode == 0, result.stderr
    proc.wait(timeout=5)
    assert observed_signals == [signal.SIGTERM, signal.SIGKILL]
    assert supervisor_state.get_current_jobs(state_path) == []
    attempts = [
        event
        for event in _events(ledger)
        if event["event"] == "signal_attempted"
    ]
    assert [event["signum"] for event in attempts] == [
        signal.SIGTERM,
        signal.SIGKILL,
    ]
    assert len({event["intent_id"] for event in attempts}) == 1


def test_standalone_adapter_rejects_canonical_dispatch_target(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    ledger = tmp_path / "standalone_termination.jsonl"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_dispatch_state(state_path, proc=proc)
    stderr = StringIO()
    argv = [
        "--target-kind",
        "pgid",
        "--target-id",
        str(pgid),
        "--signal",
        "TERM",
        "--reason",
        "bypass-attempt",
        "--actor",
        "pytest",
    ]

    with (
        patch.dict(
            os.environ,
            {**os.environ, termination.LEDGER_PATH_ENV: str(ledger)},
            clear=True,
        ),
        redirect_stderr(stderr),
        pytest.raises(SystemExit) as exc_info,
    ):
        termination_signal.main(argv, state_path=state_path)

    assert exc_info.value.code == 2
    assert "refuses a canonical dispatch target" in stderr.getvalue()
    assert proc.poll() is None
    assert not ledger.exists()


def test_standalone_adapter_revalidates_dispatch_guard_after_arm(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    ledger = tmp_path / "standalone_termination.jsonl"
    proc = spawn_process()
    pgid = os.getpgid(proc.pid)
    _write_state(state_path, [])
    real_arm = termination.arm

    def arm_then_attach(**kwargs):
        intent = real_arm(**kwargs)
        _write_dispatch_state(state_path, proc=proc)
        return intent

    stderr = StringIO()
    with (
        patch.dict(
            os.environ,
            {**os.environ, termination.LEDGER_PATH_ENV: str(ledger)},
            clear=True,
        ),
        patch.object(termination_signal.termination, "arm", side_effect=arm_then_attach),
        redirect_stderr(stderr),
        pytest.raises(SystemExit) as exc_info,
    ):
        termination_signal.main(
            [
                "--target-kind",
                "pgid",
                "--target-id",
                str(pgid),
                "--signal",
                "TERM",
                "--reason",
                "arm-race",
                "--actor",
                "pytest",
            ],
            state_path=state_path,
        )

    assert exc_info.value.code == 2
    assert "refuses a canonical dispatch target" in stderr.getvalue()
    assert proc.poll() is None
    events = _events(ledger)
    assert [event["event"] for event in events] == [
        "intent_armed",
        "signal_attempted",
        "signal_result",
    ]
    assert events[-1]["status"] == "error"
    assert not any(
        event["event"] == "signal_result" and event["status"] == "sent"
        for event in events
    )


def test_standalone_adapter_revalidates_dispatch_guard_before_escalation(
    tmp_path: Path,
    spawn_process,
) -> None:
    state_path = tmp_path / "dispatch_state.json"
    ledger = tmp_path / "standalone_termination.jsonl"
    proc = spawn_process(
        [
            sys.executable,
            "-c",
            (
                "import signal,time;"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
                "time.sleep(30)"
            ),
        ]
    )
    time.sleep(0.1)
    pgid = os.getpgid(proc.pid)
    _write_state(state_path, [])
    real_sender = termination.send_pgid

    def send_then_attach(intent, signum, **kwargs):
        result = real_sender(intent, signum, **kwargs)
        if signum == signal.SIGTERM:
            _write_dispatch_state(state_path, proc=proc)
        return result

    stderr = StringIO()
    with (
        patch.dict(
            os.environ,
            {**os.environ, termination.LEDGER_PATH_ENV: str(ledger)},
            clear=True,
        ),
        patch.object(
            termination_signal.termination_command.termination,
            "send_pgid",
            side_effect=send_then_attach,
        ),
        redirect_stderr(stderr),
        pytest.raises(SystemExit) as exc_info,
    ):
        termination_signal.main(
            [
                "--target-kind",
                "pgid",
                "--target-id",
                str(pgid),
                "--signal",
                "TERM_KILL",
                "--grace-seconds",
                "0.05",
                "--reason",
                "escalation-race",
                "--actor",
                "pytest",
            ],
            state_path=state_path,
        )

    assert exc_info.value.code == 2
    assert "refuses a canonical dispatch target" in stderr.getvalue()
    assert proc.poll() is None
    results = [
        event for event in _events(ledger) if event["event"] == "signal_result"
    ]
    assert [(event["signum"], event["status"]) for event in results] == [
        (signal.SIGTERM, "sent"),
        (signal.SIGKILL, "error"),
    ]


def test_standalone_adapter_preserves_non_dispatch_watchdog_contract(
    tmp_path: Path,
    spawn_process,
) -> None:
    ledger = tmp_path / "standalone_termination.jsonl"
    proc = spawn_process()
    result = subprocess.run(
        [
            sys.executable,
            str(STANDALONE_SCRIPT),
            "--target-kind",
            "pgid",
            "--target-id",
            str(os.getpgid(proc.pid)),
            "--signal",
            "TERM",
            "--reason",
            "standalone-watchdog",
            "--actor",
            "pytest",
        ],
        cwd=ROOT,
        env={
            **os.environ,
            termination.LEDGER_PATH_ENV: str(ledger),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    proc.wait(timeout=5)
    events = _events(ledger)
    assert events[0]["job_id"] is None
    assert events[0]["attempt"] is None
    assert events[-1]["status"] == "sent"
