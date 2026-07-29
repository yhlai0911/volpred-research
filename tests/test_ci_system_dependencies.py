import signal
from pathlib import Path

from scripts import ci_install_system_test_dependencies as deps

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pytest.yml"


def test_workflow_delegates_system_dependencies_to_bounded_installer() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "sudo python3 scripts/ci_install_system_test_dependencies.py" in workflow
    assert (
        "sudo apt-get update && sudo apt-get install -y ripgrep fonts-noto-cjk"
        not in workflow
    )
    assert "timeout-minutes: 30" in workflow


def test_dependency_commands_keep_real_runtime_requirements_and_network_bounds() -> None:
    command = " ".join(deps.INSTALL_COMMAND)

    assert "ripgrep" in deps.INSTALL_COMMAND
    assert "fonts-noto-cjk" in deps.INSTALL_COMMAND
    assert "Acquire::Retries=2" in command
    assert "Acquire::http::Timeout=20" in command
    assert "Acquire::https::Timeout=20" in command
    assert "DPkg::Lock::Timeout=20" in command
    assert deps.INSTALL_COMMAND[0] == "apt-get"
    assert "sudo" not in deps.INSTALL_COMMAND


def test_dependency_retry_budget_is_bounded_below_six_minutes() -> None:
    cleanup_budget = deps.TERM_GRACE_SECONDS + deps.KILL_GRACE_SECONDS
    worst_case = (
        deps.ATTEMPTS * (deps.UPDATE_TIMEOUT_SECONDS + cleanup_budget)
        + deps.ATTEMPTS * (deps.INSTALL_TIMEOUT_SECONDS + cleanup_budget)
        + 2 * (deps.ATTEMPTS - 1) * deps.BACKOFF_SECONDS
    )

    assert worst_case <= 6 * 60


def test_retry_reuses_partial_download_after_timeout() -> None:
    attempts: list[tuple[tuple[str, ...], int]] = []
    sleeps: list[float] = []
    outcomes = iter(
        [
            deps.AttemptResult(returncode=124, timed_out=True),
            deps.AttemptResult(returncode=0),
        ]
    )

    def runner(command: tuple[str, ...], *, timeout_seconds: int) -> deps.AttemptResult:
        attempts.append((tuple(command), timeout_seconds))
        return next(outcomes)

    ok = deps.run_with_retry(
        "runtime-packages",
        deps.INSTALL_COMMAND,
        timeout_seconds=deps.INSTALL_TIMEOUT_SECONDS,
        runner=runner,
        sleeper=sleeps.append,
    )

    assert ok is True
    assert attempts == [
        (deps.INSTALL_COMMAND, deps.INSTALL_TIMEOUT_SECONDS),
        (deps.INSTALL_COMMAND, deps.INSTALL_TIMEOUT_SECONDS),
    ]
    assert sleeps == [deps.BACKOFF_SECONDS]


def test_retry_fails_closed_after_finite_attempts() -> None:
    calls = 0

    def runner(command: tuple[str, ...], *, timeout_seconds: int) -> deps.AttemptResult:
        del command, timeout_seconds
        nonlocal calls
        calls += 1
        return deps.AttemptResult(returncode=100)

    ok = deps.run_with_retry(
        "apt-index",
        deps.UPDATE_COMMAND,
        timeout_seconds=deps.UPDATE_TIMEOUT_SECONDS,
        runner=runner,
        sleeper=lambda _seconds: None,
    )

    assert ok is False
    assert calls == deps.ATTEMPTS


def test_retry_stops_immediately_when_prior_process_group_survives() -> None:
    calls = 0
    sleeps: list[float] = []

    def runner(command: tuple[str, ...], *, timeout_seconds: int) -> deps.AttemptResult:
        del command, timeout_seconds
        nonlocal calls
        calls += 1
        return deps.AttemptResult(
            returncode=deps.PROCESS_GROUP_CLEANUP_FAILED,
            timed_out=True,
        )

    ok = deps.run_with_retry(
        "runtime-packages",
        deps.INSTALL_COMMAND,
        timeout_seconds=deps.INSTALL_TIMEOUT_SECONDS,
        runner=runner,
        sleeper=sleeps.append,
    )

    assert ok is False
    assert calls == 1
    assert sleeps == []


def test_timeout_kills_surviving_process_group_after_leader_exits(monkeypatch) -> None:
    signals: list[tuple[int, int]] = []
    waits = iter([False, True])

    class ExitedLeader:
        pid = 4321

        def poll(self) -> int:
            return -signal.SIGTERM

    monkeypatch.setattr(
        deps.os,
        "killpg",
        lambda process_group_id, sent_signal: signals.append(
            (process_group_id, sent_signal)
        ),
    )
    monkeypatch.setattr(
        deps,
        "_wait_for_process_group_exit",
        lambda _process, *, timeout_seconds: (
            next(waits)
            if timeout_seconds
            in (deps.TERM_GRACE_SECONDS, deps.KILL_GRACE_SECONDS)
            else False
        ),
    )

    terminated = deps._terminate_process_group(ExitedLeader())

    assert terminated is True
    assert signals == [
        (4321, signal.SIGTERM),
        (4321, signal.SIGKILL),
    ]


def test_group_wait_reaps_leader_before_each_liveness_probe(monkeypatch) -> None:
    poll_calls = 0
    group_exists = iter([True, False])

    class ZombieLeader:
        pid = 2468

        def poll(self) -> int:
            nonlocal poll_calls
            poll_calls += 1
            return -signal.SIGTERM

    monkeypatch.setattr(
        deps,
        "_process_group_exists",
        lambda process_group_id: (
            next(group_exists) if process_group_id == 2468 else True
        ),
    )
    monkeypatch.setattr(deps.time, "sleep", lambda _seconds: None)

    terminated = deps._wait_for_process_group_exit(
        ZombieLeader(),
        timeout_seconds=deps.TERM_GRACE_SECONDS,
    )

    assert terminated is True
    assert poll_calls == 2


def test_timeout_cleanup_failure_is_bounded_and_reported(monkeypatch) -> None:
    signals: list[int] = []

    class StuckLeader:
        pid = 9876

        def poll(self) -> None:
            return None

    monkeypatch.setattr(
        deps.os,
        "killpg",
        lambda _process_group_id, sent_signal: signals.append(sent_signal),
    )
    monkeypatch.setattr(
        deps,
        "_wait_for_process_group_exit",
        lambda _process, *, timeout_seconds: False,
    )

    terminated = deps._terminate_process_group(StuckLeader())

    assert terminated is False
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_signal_permission_failure_is_reported_as_incomplete_cleanup(
    monkeypatch,
) -> None:
    class RootOwnedLeader:
        pid = 1357

        def poll(self) -> None:
            return None

    monkeypatch.setattr(
        deps.os,
        "killpg",
        lambda _process_group_id, _sent_signal: (_ for _ in ()).throw(
            PermissionError
        ),
    )

    assert deps._terminate_process_group(RootOwnedLeader()) is False


def test_main_refuses_unprivileged_supervisor(monkeypatch) -> None:
    monkeypatch.setattr(deps.os, "geteuid", lambda: 501)

    assert deps.main() == 2
