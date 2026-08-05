"""Regression gate for the Telegram → operations-manager seam.

Before this wiring the responder answered the boss in the chat and the platform's
only coordinator never learned the boss had spoken. An instruction with an
organizational consequence ("研究部先停，把 draft 池補起來") reached a session whose
entire remit was to reply and exit; the manager found out on whatever 30-minute
tick happened to notice something downstream, if ever.

急件直達 is a standing owner rule (`feedback_urgent_bypasses_scheduler_by_design`),
so the seam has to hold two invariants that unit-testing org_intake alone cannot
cover: the poll loop actually calls intake, and it hands over enough identity for
intake to stay idempotent and to name the reply's real owner.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.telegram_poll as poll


@pytest.fixture(autouse=True)
def _quiet_log(monkeypatch, tmp_path):
    monkeypatch.setattr(poll, "TELEGRAM_POLL_LOG", tmp_path / "telegram_poll.log")


@pytest.fixture()
def spawned(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: calls.append(cmd))
    return calls


def test_boss_message_is_handed_to_the_coordinator(spawned) -> None:
    assert poll._mirror_to_org("研究部先停，把 draft 池補起來", 1701, "telegram-1701") is True

    assert len(spawned) == 1, "the coordinator must learn about the boss's instruction"
    argv = spawned[0]
    assert argv[1].endswith("scripts/org/org_intake.py")
    assert "研究部先停，把 draft 池補起來" in argv, "the coordinator needs the boss's own words"


def test_the_handover_carries_the_identity_intake_needs(spawned) -> None:
    """Without the message id a restart replay re-files and re-wakes; without
    the task id the coordinator cannot tell who owns the chat reply."""
    poll._mirror_to_org("進度如何", 1702, "telegram-1702")
    argv = spawned[0]

    assert argv[argv.index("--msg-id") + 1] == "1702"
    assert argv[argv.index("--canonical-task-id") + 1] == "telegram-1702"
    assert argv[argv.index("--channel") + 1] == "telegram"
    assert "--no-wake" not in argv, "急件直達: the boss must not queue behind the tick"


def test_the_org_can_never_break_the_reply_path(monkeypatch) -> None:
    """A broken org layer costs the coordinator a notification, not the reply."""
    def _explode(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(subprocess, "Popen", _explode)

    assert poll._mirror_to_org("急件", 1703, "telegram-1703") is False


def test_intake_is_spawned_with_a_resolved_interpreter(spawned) -> None:
    """The daemon inherits launchd's narrow PATH: `uv` and a bare `python3` are
    not reliably on it, so a seam that resolves the interpreter at call time
    would fail only in production."""
    import sys

    poll._mirror_to_org("x", 1704, "telegram-1704")

    assert spawned[0][0] == sys.executable
    assert Path(spawned[0][0]).is_absolute()
