from __future__ import annotations

import ast
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import procutil
from volpred.ops import termination

ROOT = Path(__file__).resolve().parents[2]


def _events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _raw_shell_termination_lines(path: Path) -> list[int]:
    violations: list[int] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        code = line.split("#", 1)[0]
        without_probes = re.sub(
            r"(^|[;&|()\s])(?:[^\s;&|()]*/)?kill\s+-0\b[^;&|()]*",
            r"\1",
            code,
        )
        raw_kill = re.search(
            r"(^|[;&|()\s])(?:[^\s;&|()]*/)?kill(?:\s|$)",
            without_probes,
        )
        raw_kickstart = re.search(
            r"launchctl\s+kickstart\s+-k(?:\s|$)", code,
        )
        if raw_kill or raw_kickstart:
            violations.append(lineno)
    return violations


def _raw_python_termination_lines(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    raw_names = {"kill", "killpg", "terminate", "pthread_kill"}
    guarded_names = {"kill_pgid", "kill_tree"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        for imported in node.names:
            local_name = imported.asname or imported.name
            if (
                module == "os" and imported.name in {"kill", "killpg"}
            ) or (
                module == "signal" and imported.name == "pthread_kill"
            ):
                raw_names.add(local_name)
            if module.endswith("procutil") and imported.name in guarded_names:
                guarded_names.add(local_name)

    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            if node.func.id in guarded_names:
                if not any(keyword.arg == "intent" for keyword in node.keywords):
                    violations.append(f"{node.lineno}:missing-intent")
            elif node.func.id in raw_names:
                violations.append(str(node.lineno))
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        raw_os_signal = node.func.attr in {
            "kill", "killpg", "terminate", "pthread_kill",
        }
        procutil_signal = (
            node.func.attr in {"kill_pgid", "kill_tree"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "procutil"
        )
        if raw_os_signal:
            is_probe = (
                node.func.attr == "killpg"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == 0
            )
            if is_probe:
                continue
        subprocess_argv = (
            node.func.attr in {"run", "Popen", "call", "check_call"}
            and node.args
            and isinstance(node.args[0], (ast.List, ast.Tuple))
            and node.args[0].elts
            and isinstance(node.args[0].elts[0], ast.Constant)
        )
        executable = str(node.args[0].elts[0].value) if subprocess_argv else ""
        subprocess_kill = (
            subprocess_argv
            and (executable == "kill" or executable.endswith("/kill"))
        )
        launchctl_kill = (
            subprocess_argv
            and executable.endswith("launchctl")
            and any(
                isinstance(item, ast.Constant) and item.value == "-k"
                for item in node.args[0].elts[1:]
            )
        )
        if raw_os_signal or subprocess_kill or launchctl_kill:
            violations.append(str(node.lineno))
        if procutil_signal and not any(
            keyword.arg == "intent" for keyword in node.keywords
        ):
            violations.append(f"{node.lineno}:missing-intent")
    return violations


def test_signal_is_impossible_without_a_durable_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: sent.append((pgid, sig)))

    with pytest.raises(termination.TerminationIntentRequired):
        procutil.kill_pgid(4321, grace_s=0)

    assert sent == []


def test_attempt_receipt_is_fsynced_before_signal_syscall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pgid",
        target_id=4321,
        reason="worker_timeout",
        actor="dispatch-supervisor",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        job_id="job-1",
        attempt=2,
        ledger_path=ledger,
    )
    observed_at_syscall: list[list[str]] = []

    def fake_killpg(pgid: int, signum: int) -> None:
        observed_at_syscall.append([event["event"] for event in _events(ledger)])

    monkeypatch.setattr(termination.os, "killpg", fake_killpg)

    termination.send_pgid(
        intent,
        signal.SIGTERM,
        ledger_path=ledger,
    )

    assert observed_at_syscall == [["intent_armed", "signal_attempted"]]
    events = _events(ledger)
    assert [event["event"] for event in events] == [
        "intent_armed",
        "signal_attempted",
        "signal_result",
    ]
    assert events[-1]["status"] == "sent"


def test_match_requires_a_sent_exact_job_target_and_signal(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    armed_only = termination.arm(
        target_kind="pgid",
        target_id=111,
        reason="never_sent",
        actor="test",
        signal_sequence=[signal.SIGTERM],
        job_id="job-a",
        attempt=1,
        ledger_path=ledger,
    )
    assert armed_only.intent_id
    assert termination.match_sent_signal(
        target_kind="pgid",
        target_id=111,
        signum=signal.SIGTERM,
        job_id="job-a",
        attempt=1,
        ledger_path=ledger,
    ) is None

    sent = termination.arm(
        target_kind="pgid",
        target_id=222,
        reason="health_timeout",
        actor="health",
        signal_sequence=[signal.SIGTERM],
        job_id="job-b",
        attempt=3,
        ledger_path=ledger,
    )
    termination.send_pgid(
        sent,
        signal.SIGTERM,
        ledger_path=ledger,
        sender=lambda _target, _signal: None,
    )

    assert termination.match_sent_signal(
        target_kind="pgid",
        target_id=222,
        signum=signal.SIGTERM,
        job_id="job-b",
        attempt=3,
        ledger_path=ledger,
    )["reason"] == "health_timeout"
    assert termination.match_sent_signal(
        target_kind="pgid",
        target_id=222,
        signum=signal.SIGKILL,
        job_id="job-b",
        attempt=3,
        ledger_path=ledger,
    ) is None
    assert termination.match_sent_signal_for_job(
        target_kind="pgid", signum=signal.SIGTERM,
        job_id="job-b", attempt=3, ledger_path=ledger,
    )["target_id"] == 222


def test_job_match_fails_closed_when_same_attempt_has_two_targets(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    for pgid in (222, 333):
        intent = termination.arm(
            target_kind="pgid", target_id=pgid, reason="duplicate",
            actor="health", signal_sequence=[signal.SIGTERM],
            job_id="job-b", attempt=3, ledger_path=ledger,
        )
        termination.send_pgid(
            intent, signal.SIGTERM, ledger_path=ledger,
            sender=lambda _target, _signal: None,
        )
    assert termination.match_sent_signal_for_job(
        target_kind="pgid", signum=signal.SIGTERM,
        job_id="job-b", attempt=3, ledger_path=ledger,
    ) is None


def test_malformed_integer_fields_fail_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    ledger.write_text(
        json.dumps({
            "event": "signal_result", "status": "sent",
            "target_kind": "pgid", "target_id": "not-an-int",
            "signum": "also-bad", "job_id": "job", "attempt": {},
            "observed_at": "2026-07-27T00:00:00+00:00",
        }) + "\n",
        encoding="utf-8",
    )
    assert termination.match_sent_signal(
        target_kind="pgid", target_id=1, signum=signal.SIGTERM,
        job_id="job", attempt=1, ledger_path=ledger,
    ) is None


def test_sent_result_without_armed_attempt_lineage_is_rejected(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    ledger.write_text(
        json.dumps({
            "event": "signal_result", "status": "sent",
            "intent_id": "forged", "target_kind": "pgid", "target_id": 123,
            "actual_target_kind": "pgid", "actual_target_id": 123,
            "signum": signal.SIGTERM, "job_id": "job", "attempt": 1,
            "observed_at": "2026-07-27T00:00:00+00:00",
        }) + "\n",
        encoding="utf-8",
    )
    assert termination.match_sent_signal(
        target_kind="pgid", target_id=123, signum=signal.SIGTERM,
        job_id="job", attempt=1, ledger_path=ledger,
    ) is None


def test_symlinked_ledger_cannot_inject_sent_receipt(tmp_path: Path) -> None:
    target = tmp_path / "attacker.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    ledger = tmp_path / "termination_intents.jsonl"
    ledger.symlink_to(target)
    assert termination.match_sent_signal(
        target_kind="pgid", target_id=1, signum=signal.SIGTERM,
        job_id="job", attempt=1, ledger_path=ledger,
    ) is None


def test_root_identity_drift_blocks_signal(tmp_path: Path, monkeypatch) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pid", target_id=9876, reason="test", actor="pytest",
        signal_sequence=[signal.SIGTERM], ledger_path=ledger,
        target_identity="old-generation",
    )
    monkeypatch.setattr(
        termination,
        "capture_target_identity",
        lambda _kind, _target: "new-generation",
    )
    calls: list[tuple[int, int]] = []
    with pytest.raises(termination.TerminationIntentMismatch):
        termination.send_pid(
            intent, signal.SIGTERM, ledger_path=ledger,
            sender=lambda pid, sig: calls.append((pid, sig)),
        )
    assert calls == []


def test_pre_signal_authorization_drift_is_receipted_without_syscall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pid",
        target_id=9876,
        reason="operator-drain",
        actor="pytest",
        signal_sequence=[signal.SIGTERM],
        ledger_path=ledger,
        target_identity="same-generation",
        job_id="job-a",
        attempt=2,
    )
    monkeypatch.setattr(
        termination,
        "capture_target_identity",
        lambda _kind, _target: "same-generation",
    )
    calls: list[tuple[int, int]] = []

    def reject_stale_binding() -> None:
        raise termination.TerminationIntentMismatch(
            "dispatch identity changed after intent arm"
        )

    with pytest.raises(
        termination.TerminationIntentMismatch,
        match="dispatch identity changed",
    ):
        termination.send_pid(
            intent,
            signal.SIGTERM,
            ledger_path=ledger,
            sender=lambda pid, sig: calls.append((pid, sig)),
            pre_signal_verifier=reject_stale_binding,
        )

    assert calls == []
    events = _events(ledger)
    assert [event["event"] for event in events] == [
        "intent_armed",
        "signal_attempted",
        "signal_result",
    ]
    assert events[-1]["status"] == "error"
    assert events[-1]["job_id"] == "job-a"
    assert events[-1]["attempt"] == 2


def test_exact_intent_target_signal_is_one_use(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pid", target_id=9876, reason="test", actor="pytest",
        signal_sequence=[signal.SIGTERM], ledger_path=ledger,
    )
    termination.send_pid(
        intent, signal.SIGTERM, ledger_path=ledger,
        sender=lambda _pid, _sig: None,
    )
    with pytest.raises(termination.TerminationIntentMismatch, match="already attempted"):
        termination.send_pid(
            intent, signal.SIGTERM, ledger_path=ledger,
            sender=lambda _pid, _sig: None,
        )


def test_pgid_escalation_survives_leader_exit_while_group_remains(
    tmp_path: Path, monkeypatch,
) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pgid", target_id=777, reason="timeout", actor="pytest",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL], ledger_path=ledger,
        target_identity="leader-start",
    )
    identities = iter(["leader-start", "absent:pgid:777"])
    monkeypatch.setattr(
        termination,
        "capture_target_identity",
        lambda _kind, _target: next(identities),
    )
    monkeypatch.setattr(termination, "_pgid_has_members", lambda _pgid: True)
    sent: list[int] = []
    termination.send_pgid(
        intent, signal.SIGTERM, ledger_path=ledger,
        sender=lambda _target, signum: sent.append(signum),
    )
    termination.send_pgid(
        intent, signal.SIGKILL, ledger_path=ledger,
        sender=lambda _target, signum: sent.append(signum),
    )
    assert sent == [signal.SIGTERM, signal.SIGKILL]


def test_term_result_does_not_hide_unresolved_kill_attempt(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pgid", target_id=888, reason="timeout", actor="pytest",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        job_id="job", attempt=1, ledger_path=ledger,
    )
    termination.send_pgid(
        intent, signal.SIGTERM, ledger_path=ledger,
        sender=lambda _target, _signum: None,
    )
    termination._append_event(
        ledger,
        {
            "event": "signal_attempted",
            "observed_at": termination._now_iso(),
            **termination._intent_fields(intent),
            "actual_target_kind": "pgid",
            "actual_target_id": 888,
            "signum": signal.SIGKILL,
        },
        reject_duplicate_attempt=True,
    )
    match = termination.match_unresolved_signal_attempt(
        target_kind="pgid", target_id=888, signum=signal.SIGKILL,
        job_id="job", attempt=1, ledger_path=ledger,
    )
    assert match is not None
    assert match["signum"] == signal.SIGKILL


def test_wait_for_sent_signal_closes_publication_race(monkeypatch) -> None:
    calls = 0

    def eventually(**_kwargs):
        nonlocal calls
        calls += 1
        return None if calls < 3 else {"status": "sent"}

    monkeypatch.setattr(termination, "match_sent_signal", eventually)
    assert termination.wait_for_sent_signal(
        target_kind="pgid", target_id=123, signum=signal.SIGTERM,
        job_id="job", attempt=1, wait_s=0.1, poll_s=0.001,
    ) == {"status": "sent"}
    assert calls == 3


def test_partial_tail_is_repaired_before_next_fsynced_event(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    termination.arm(
        target_kind="pid", target_id=111, reason="first", actor="pytest",
        signal_sequence=[signal.SIGTERM], ledger_path=ledger,
    )
    with ledger.open("ab") as handle:
        handle.write(b'{"event":"partial"')
    termination.arm(
        target_kind="pid", target_id=222, reason="second", actor="pytest",
        signal_sequence=[signal.SIGTERM], ledger_path=ledger,
    )
    assert [event["reason"] for event in termination._read_events(ledger)] == [
        "first", "second",
    ]
    assert termination.match_sent_signal(
        target_kind="pgid",
        target_id=222,
        signum=signal.SIGTERM,
        job_id="different-job",
        attempt=3,
        ledger_path=ledger,
    ) is None


def test_intent_target_and_signal_sequence_are_fail_closed(tmp_path: Path) -> None:
    ledger = tmp_path / "termination_intents.jsonl"
    intent = termination.arm(
        target_kind="pgid",
        target_id=444,
        reason="timeout",
        actor="test",
        signal_sequence=[signal.SIGTERM],
        ledger_path=ledger,
    )

    with pytest.raises(termination.TerminationIntentMismatch):
        termination.send_pid(intent, signal.SIGTERM, ledger_path=ledger)
    with pytest.raises(termination.TerminationIntentMismatch):
        termination.send_pgid(intent, signal.SIGKILL, ledger_path=ledger)

    assert [event["event"] for event in _events(ledger)] == ["intent_armed"]


def test_signal_is_not_sent_when_attempt_receipt_cannot_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "termination.jsonl"
    intent = termination.arm(
        target_kind="pid", target_id=4321, reason="test",
        actor="pytest", signal_sequence=[signal.SIGTERM], ledger_path=ledger,
    )
    calls: list[tuple[int, int]] = []

    def fail_before_signal(_path: Path, event: dict, **_kwargs) -> None:
        if event["event"] == "signal_attempted":
            raise OSError("disk full")

    monkeypatch.setattr(termination, "_append_event", fail_before_signal)
    with pytest.raises(OSError, match="disk full"):
        termination.send_pid(
            intent, signal.SIGTERM, ledger_path=ledger,
            sender=lambda pid, sig: calls.append((pid, sig)),
        )
    assert calls == [], "no durable attempted receipt means no signal syscall"


def test_post_write_fsync_failure_rolls_back_attempt_before_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "termination.jsonl"
    intent = termination.arm(
        target_kind="pid", target_id=4321, reason="test",
        actor="pytest", signal_sequence=[signal.SIGTERM], ledger_path=ledger,
    )
    calls: list[tuple[int, int]] = []
    real_fsync = termination.os.fsync
    fsync_calls = 0

    def fail_first_attempt_fsync(fd: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("injected post-write fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(termination.os, "fsync", fail_first_attempt_fsync)
    with pytest.raises(OSError, match="injected post-write"):
        termination.send_pid(
            intent, signal.SIGTERM, ledger_path=ledger,
            sender=lambda pid, sig: calls.append((pid, sig)),
        )

    assert calls == []
    assert [event["event"] for event in _events(ledger)] == ["intent_armed"]
    assert termination.match_unresolved_signal_attempt(
        target_kind="pid", target_id=4321, signum=signal.SIGTERM,
        job_id="", attempt=1, ledger_path=ledger,
    ) is None


def test_parent_fsync_failure_rolls_back_new_ledger_epoch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = tmp_path / "termination.jsonl"
    real_fsync = termination.os.fsync
    parent_fsync_calls = 0

    def fail_parent_fsync(fd: int) -> None:
        nonlocal parent_fsync_calls
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            parent_fsync_calls += 1
            if parent_fsync_calls == 1:
                raise OSError("injected parent fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(termination.os, "fsync", fail_parent_fsync)
    with pytest.raises(OSError, match="injected parent"):
        termination.arm(
            target_kind="pid", target_id=4321, reason="test",
            actor="pytest", signal_sequence=[signal.SIGTERM],
            ledger_path=ledger,
        )

    assert termination._read_events(ledger) == []
    retry = termination.arm(
        target_kind="pid", target_id=4321, reason="retry",
        actor="pytest", signal_sequence=[signal.SIGTERM],
        ledger_path=ledger,
    )
    assert retry.reason == "retry"
    assert parent_fsync_calls == 2
    assert [event["reason"] for event in _events(ledger)] == ["retry"]


def test_production_has_no_raw_termination_bypass() -> None:
    """Only the durable-intent owner may issue a terminating syscall."""
    violations: list[str] = []
    for base in (ROOT / "scripts", ROOT / "src" / "volpred"):
        for path in base.rglob("*.py"):
            relative = path.relative_to(ROOT)
            if "tests" in relative.parts or path == Path(termination.__file__):
                continue
            violations.extend(
                f"{relative}:{finding}"
                for finding in _raw_python_termination_lines(path)
            )
    assert violations == [], f"raw termination bypasses: {violations}"

    shell_violations: list[str] = []
    for path in (ROOT / "scripts").rglob("*.sh"):
        if (
            "tests" in path.relative_to(ROOT).parts
            or "_legacy" in path.relative_to(ROOT).parts
        ):
            continue
        shell_violations.extend(
            f"{path.relative_to(ROOT)}:{lineno}"
            for lineno in _raw_shell_termination_lines(path)
        )
    assert shell_violations == [], f"raw shell termination bypasses: {shell_violations}"


def test_shell_gate_detects_term_but_exempts_liveness_probe(tmp_path: Path) -> None:
    script = tmp_path / "probe.sh"
    script.write_text(
        "#!/bin/sh\n"
        "kill -0 123 && kill -TERM 123\n"
        "/bin/kill -KILL 456\n"
        "kill -0 789\n",
        encoding="utf-8",
    )
    assert _raw_shell_termination_lines(script) == [2, 3]


def test_python_gate_detects_renamed_kill_import(tmp_path: Path) -> None:
    script = tmp_path / "bypass.py"
    script.write_text(
        "from os import kill as send_signal\n"
        "send_signal(123, 15)\n",
        encoding="utf-8",
    )
    assert _raw_python_termination_lines(script) == ["2"]


def test_live_process_group_rehearsal_round_trips_sent_receipt(tmp_path: Path) -> None:
    ledger = tmp_path / "termination.jsonl"
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    pgid = os.getpgid(proc.pid)
    intent = termination.arm(
        target_kind="pgid", target_id=pgid,
        reason="production_rehearsal", actor="pytest",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        job_id="rehearsal-job", attempt=1, ledger_path=ledger,
    )
    try:
        assert procutil.kill_pgid(
            pgid, intent=intent, ledger_path=ledger, grace_s=0.05,
        ) is True
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            termination.send_pgid(intent, signal.SIGKILL, ledger_path=ledger)
            proc.wait(timeout=5)

    receipt = termination.match_sent_signal(
        target_kind="pgid", target_id=pgid, signum=signal.SIGTERM,
        job_id="rehearsal-job", attempt=1, ledger_path=ledger,
    )
    assert receipt is not None
    assert receipt["reason"] == "production_rehearsal"


def test_shell_adapter_uses_one_generation_for_term_kill(tmp_path: Path) -> None:
    ledger = tmp_path / "termination.jsonl"
    proc = subprocess.Popen(
        [
            sys.executable, "-c",
            "import signal,time; signal.signal(signal.SIGTERM, lambda *_: None); time.sleep(30)",
        ],
        start_new_session=True,
    )
    try:
        time.sleep(0.1)
        env = {
            **os.environ,
            termination.LEDGER_PATH_ENV: str(ledger),
        }
        subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "termination_signal.py"),
                "--target-kind", "pgid", "--target-id", str(proc.pid),
                "--signal", "TERM_KILL", "--grace-seconds", "0.05",
                "--reason", "adapter-rehearsal", "--actor", "pytest",
            ],
            cwd=ROOT, env=env, timeout=10, check=True,
        )
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
    events = _events(ledger)
    attempts = [event for event in events if event["event"] == "signal_attempted"]
    assert [event["signum"] for event in attempts] == [
        signal.SIGTERM, signal.SIGKILL,
    ]
    assert len({event["intent_id"] for event in attempts}) == 1
