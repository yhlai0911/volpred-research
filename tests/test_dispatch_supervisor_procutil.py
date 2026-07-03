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


def test_get_process_start_wall_returns_none_on_ps_failure(monkeypatch) -> None:
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ps", timeout=5)

    monkeypatch.setattr(procutil.subprocess, "run", boom)
    assert procutil.get_process_start_wall(123) is None


def test_pid_identity_matches_true_when_fingerprint_matches(monkeypatch) -> None:
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: "Wed Jul  2 00:57:15 2026")
    assert procutil.pid_identity_matches(123, "Wed Jul  2 00:57:15 2026") is True


def test_pid_identity_matches_false_on_pid_reuse(monkeypatch) -> None:
    """The classic PID-reuse case: pid is alive, but it's a DIFFERENT process
    now (different start time) than the one we spawned."""
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: "Thu Jul  3 09:00:00 2026")
    assert procutil.pid_identity_matches(123, "Wed Jul  2 00:57:15 2026") is False


def test_pid_identity_matches_false_when_pid_gone(monkeypatch) -> None:
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: None)
    assert procutil.pid_identity_matches(123, "Wed Jul  2 00:57:15 2026") is False


def test_pid_identity_matches_degrades_to_liveness_without_fingerprint(monkeypatch) -> None:
    """Legacy state entries recorded before this fingerprint existed have no
    `started_wall` — don't punish them as a mismatch, just check liveness."""
    monkeypatch.setattr(procutil, "get_process_start_wall", lambda pid: "anything")
    assert procutil.pid_identity_matches(123, None) is True
    assert procutil.pid_identity_matches(123, "") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
