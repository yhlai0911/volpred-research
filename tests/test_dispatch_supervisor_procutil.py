"""Unit tests for `scripts.dispatch_supervisor.procutil` — PID-reuse-safe
identity checks (Codex review §10 #2 fix, 2026-06-15/2026-07-04).
"""
from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import procutil
from volpred.ops import termination


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _armed_pgid(pgid: int, ledger: Path) -> termination.TerminationIntent:
    return termination.arm(
        target_kind="pgid",
        target_id=pgid,
        reason="unit_test",
        actor="pytest",
        signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        ledger_path=ledger,
    )


def test_get_process_start_wall_returns_none_for_nonpositive_pid() -> None:
    assert procutil.get_process_start_wall(0) is None
    assert procutil.get_process_start_wall(-5) is None


def test_get_process_start_wall_parses_ps_output(monkeypatch) -> None:
    monkeypatch.setattr(
        procutil.subprocess, "run",
        lambda *a, **k: _FakeCompleted(0, "Wed Jul  2 00:57:15 2026\n"),
    )
    assert procutil.get_process_start_wall(123) == "Wed Jul  2 00:57:15 2026"


def test_get_process_start_wall_returns_none_when_pid_missing(monkeypatch) -> None:
    monkeypatch.setattr(procutil.subprocess, "run", lambda *a, **k: _FakeCompleted(1, ""))
    assert procutil.get_process_start_wall(123) is None


def test_get_process_start_wall_returns_probe_failed_sentinel_on_ps_failure(monkeypatch) -> None:
    """Codex review round-2 finding (2026-07-04, medium): a transient `ps`
    invocation failure (OSError/timeout) must be distinguishable from a
    confirmed-dead pid (`ps` ran fine and reported not-found) — conflating
    both into a bare `None` made `check_identity()` misclassify a probe
    hiccup as IDENTITY_DEAD, which could make health.py kill/clear a live job."""
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ps", timeout=5)

    monkeypatch.setattr(procutil.subprocess, "run", boom)
    result = procutil.get_process_start_wall(123)
    assert result is procutil.PROBE_FAILED
    assert result is not None
    assert not result  # falsy — worker.py's `if started_wall:` guard must skip it


def test_check_identity_match_when_fingerprint_matches(monkeypatch) -> None:
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: "Wed Jul  2 00:57:15 2026")
    assert procutil.check_identity(123, "Wed Jul  2 00:57:15 2026") == procutil.IDENTITY_MATCH


def test_check_identity_mismatch_on_pid_reuse(monkeypatch) -> None:
    """The classic PID-reuse case: pid is alive, but it's a DIFFERENT process
    now (different start time) than the one we spawned."""
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: "Thu Jul  3 09:00:00 2026")
    assert procutil.check_identity(123, "Wed Jul  2 00:57:15 2026") == procutil.IDENTITY_MISMATCH


def test_check_identity_dead_when_pid_gone(monkeypatch) -> None:
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: None)
    assert procutil.check_identity(123, "Wed Jul  2 00:57:15 2026") == procutil.IDENTITY_DEAD


def test_check_identity_unverified_without_fingerprint(monkeypatch) -> None:
    """2026-07-04 gate-blocking fix #4: a missing `expected_start_wall` (no
    fingerprint was ever recorded — attach raced ahead of a slow/failed `ps`
    call, or a supervisor crash landed mid-attach) must be its own distinct
    state, NOT silently folded into "assume same process" (the prior bare-bool
    `pid_identity_matches()` degraded to True here — backwards for a kill
    decision, since it would let a caller signal an unverified target as if
    verified). Every kill-decision call site must handle IDENTITY_UNVERIFIED
    explicitly instead of blindly killing on absent evidence."""
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: "anything")
    assert procutil.check_identity(123, None) == procutil.IDENTITY_UNVERIFIED
    assert procutil.check_identity(123, "") == procutil.IDENTITY_UNVERIFIED


def test_check_identity_dead_takes_precedence_over_unverified(monkeypatch) -> None:
    """A dead pid with no fingerprint to compare is still DEAD, not
    UNVERIFIED — liveness is checked before the fingerprint comparison."""
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: None)
    assert procutil.check_identity(123, None) == procutil.IDENTITY_DEAD


def test_check_identity_probe_failed_maps_to_unverified_not_dead(monkeypatch) -> None:
    """Codex review round-2 finding (2026-07-04, medium): a transient `ps`
    probe failure must NOT be treated as confirmed-dead — that would let
    health.py's overdue-kill branch skip a kill decision correctly (both
    UNVERIFIED and DEAD avoid the unsafe kill), but critically also let the
    NOT-overdue branch wrongly declare `silent_death` and clear a perfectly
    healthy job on a one-off `ps` hiccup, well before it's actually aged out."""
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: procutil.PROBE_FAILED)
    assert procutil.check_identity(123, "Wed Jul  2 00:57:15 2026") == procutil.IDENTITY_UNVERIFIED
    assert procutil.check_identity(123, "Wed Jul  2 00:57:15 2026") != procutil.IDENTITY_DEAD


# ---------------------------------------------------------------------------
# kill_pgid — Codex review fix #5 (2026-07-04, gate-blocking): worker.py and
# health.py each had a near-duplicate kill routine; a PermissionError fix
# (found via a live smoke test) landed in worker's copy but not health's.
# Now both delegate to this single shared implementation.
# ---------------------------------------------------------------------------


def test_kill_pgid_noop_for_nonpositive_pgid(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: calls.append(sig))
    procutil.kill_pgid(0)
    procutil.kill_pgid(-5)
    assert calls == []


def test_pgid_members_excludes_zombies(monkeypatch) -> None:
    """A SIGKILL'd process sits in the table as `Z` until its parent reaps it,
    and `ps -g` lists it. Counting that corpse as a survivor (a) makes every
    successful kill look failed, and (b) is why macOS returned EPERM for the
    2026-07-11 `killpg SIGKILL denied pgid=69948` — the signal was aimed at a
    group whose only member was already dead. Found by a live smoke test; the
    mocked tests all passed while this was broken.
    """
    ps_rows = "  501 Ss\n  502 Z+\n  503 S+\n"

    def fake_run(cmd, **kw):
        assert cmd[:3] == ["ps", "-o", "pid=,stat="], "stat column is required to spot zombies"
        return subprocess.CompletedProcess(cmd, 0, stdout=ps_rows, stderr="")

    monkeypatch.setattr(procutil.subprocess, "run", fake_run)
    assert procutil.pgid_members(999) == [501, 503]


def test_kill_pgid_reports_success_when_only_zombies_remain(monkeypatch, tmp_path) -> None:
    """End of the same story: once the group holds nothing but zombies, the kill
    succeeded and kill_pgid must say so (not raise a false orphan alarm)."""
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: None)
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [])  # zombies filtered out
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    ledger = tmp_path / "termination.jsonl"
    assert procutil.kill_pgid(
        69948, intent=_armed_pgid(69948, ledger), ledger_path=ledger, grace_s=1,
    ) is True


def test_kill_pgid_no_sigkill_when_group_dies_after_sigterm(monkeypatch, tmp_path) -> None:
    """Invariant (unchanged): a group that exits on SIGTERM is never SIGKILL'd.

    2026-07-11: liveness is now observed with `ps -g` rather than an
    `os.killpg(pgid, 0)` probe — that probe was the thing that returned EPERM
    and let a REFUSED kill be reported as a successful one.
    """
    sigs: list[int] = []
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: sigs.append(sig))
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [])  # gone after SIGTERM
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    ledger = tmp_path / "termination.jsonl"
    assert procutil.kill_pgid(
        456, intent=_armed_pgid(456, ledger), ledger_path=ledger, grace_s=1,
    ) is True
    assert sigs == [signal.SIGTERM]


def test_kill_pgid_escalates_to_sigkill_when_group_survives(monkeypatch, tmp_path) -> None:
    sigs: list[int] = []
    monkeypatch.setattr(procutil.os, "killpg", lambda pgid, sig: sigs.append(sig))
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [777])  # never dies
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    # Survivors remain after SIGKILL → the caller must be told the kill FAILED.
    ledger = tmp_path / "termination.jsonl"
    assert procutil.kill_pgid(
        456, intent=_armed_pgid(456, ledger), ledger_path=ledger, grace_s=1,
    ) is False
    assert sigs == [signal.SIGTERM, signal.SIGKILL]


def test_kill_pgid_falls_back_to_per_pid_when_killpg_denied(monkeypatch, tmp_path) -> None:
    """The 2026-07-11 hang: macOS refused `killpg` (EPERM: `killpg SIGKILL
    denied pgid=69948`) so the SIGKILL never landed — yet kill_pgid returned as
    though it had, and the supervisor mailed "SIGKILL'd a worker" about a
    process that may well have still been running.

    A denied group signal must fall back to signalling each member by pid.
    """
    per_pid: list[tuple[int, int]] = []
    alive = {321}

    def denied_killpg(pgid: int, sig: int) -> None:
        raise PermissionError("Operation not permitted")

    def kill_one(pid: int, sig: int) -> None:
        per_pid.append((pid, sig))
        if sig == signal.SIGKILL:
            alive.discard(pid)

    monkeypatch.setattr(procutil.os, "killpg", denied_killpg)
    monkeypatch.setattr(procutil.os, "kill", kill_one)
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: sorted(alive))
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: f"start-{pid}")
    monkeypatch.setattr(
        procutil, "check_identity", lambda _pid, _expected: procutil.IDENTITY_MATCH,
    )
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    ledger = tmp_path / "termination.jsonl"
    assert procutil.kill_pgid(
        999, intent=_armed_pgid(999, ledger), ledger_path=ledger, grace_s=1,
    ) is True, \
        "the per-pid fallback did kill it — that must be reported as success"
    assert (321, signal.SIGTERM) in per_pid
    assert (321, signal.SIGKILL) in per_pid


def test_kill_pgid_reports_failure_when_every_signal_is_denied(monkeypatch, tmp_path) -> None:
    """If the group cannot be signalled at all, kill_pgid must return False so
    health.py records `kill_failed_orphan` instead of claiming a clean kill."""
    def denied(*a, **k):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(procutil.os, "killpg", denied)
    monkeypatch.setattr(procutil.os, "kill", denied)
    monkeypatch.setattr(procutil, "pgid_members_checked", lambda pgid: [4242])
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: f"start-{pid}")
    monkeypatch.setattr(
        procutil, "check_identity", lambda _pid, _expected: procutil.IDENTITY_MATCH,
    )
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    ledger = tmp_path / "termination.jsonl"
    assert procutil.kill_pgid(
        4242, intent=_armed_pgid(4242, ledger), ledger_path=ledger, grace_s=1,
    ) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
