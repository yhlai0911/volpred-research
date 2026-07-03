"""Unit tests for `scripts.dispatch_supervisor.procutil` — PID-reuse-safe
identity checks (Codex review §10 #2 fix, 2026-06-15/2026-07-04).
"""
from __future__ import annotations

import subprocess

import pytest

from scripts.dispatch_supervisor import procutil


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


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


def test_kill_pgid_sigterm_then_sigkill_after_grace(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_killpg(pgid, sig):
        kind = {15: "SIGTERM", 0: "PROBE", 9: "SIGKILL"}[sig]
        calls.append((kind, pgid))
        if kind == "PROBE":
            raise ProcessLookupError  # dies right after SIGTERM

    monkeypatch.setattr(procutil.os, "killpg", fake_killpg)
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    procutil.kill_pgid(456, grace_s=1)

    kinds = [c[0] for c in calls]
    assert kinds == ["SIGTERM", "PROBE"]


def test_kill_pgid_survives_permission_error_on_liveness_probe(monkeypatch) -> None:
    """The real bug found via a live (non-mocked) smoke test: a sandboxed
    `os.killpg(pgid, 0)` liveness probe can raise PermissionError, not just
    ProcessLookupError. Must fall through to attempt SIGKILL, not crash."""
    calls: list[tuple[str, int]] = []

    def fake_killpg(pgid, sig):
        kind = {15: "SIGTERM", 0: "PROBE", 9: "SIGKILL"}[sig]
        calls.append((kind, pgid))
        if kind == "PROBE":
            raise PermissionError("sandbox denied signal-0 probe")

    monkeypatch.setattr(procutil.os, "killpg", fake_killpg)
    monkeypatch.setattr(procutil.time, "sleep", lambda s: None)

    procutil.kill_pgid(999, grace_s=1)

    kinds = [c[0] for c in calls]
    assert "SIGTERM" in kinds
    assert "PROBE" in kinds
    assert "SIGKILL" in kinds, "must fall through to SIGKILL after the probe is denied, not crash"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
