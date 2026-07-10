"""Pins `dispatch_binary_health` to the binary the daemon actually uses.

Until 2026-07-10 this alert grepped `CLAUDE_BIN` out of
`~/.volpred/bin/cron_hourly_dispatch.sh` — the legacy shell wrapper retired by
the 2026-07-04 daemon cutover. The wrapper file still exists on disk (its
LaunchAgent is unloaded), so the read silently succeeded and the alert was right
only by coincidence: both named `~/.local/bin/claude`. Same failure mode as the
2026-07-08 false stale-dispatch alert — a monitor pointed at a post-cutover
corpse.

`volpred.ops.alerts` cannot import the daemon's constant at runtime
(`check_alerts.py` lives in `scripts/`, which has no `__init__.py`), so the two
declarations are kept in sync mechanically here rather than by comment.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import worker
from volpred.ops.alerts import (
    DISPATCH_CLAUDE_BIN_DEFAULT,
    _parse_dispatch_health_state,
)


def test_alerts_default_matches_worker() -> None:
    """The single source of truth is `worker.CLAUDE_BIN`. If you change it there,
    this fails until `DISPATCH_CLAUDE_BIN_DEFAULT` is changed too — otherwise the
    alert would keep validating a binary the dispatcher no longer runs.
    """
    assert DISPATCH_CLAUDE_BIN_DEFAULT == worker.CLAUDE_BIN


def test_no_longer_reads_the_retired_shell_wrapper(tmp_path: Path, monkeypatch) -> None:
    # The wrapper is dead. Even if its contents named a bogus binary, the alert
    # must ignore it and report on what the daemon really shells out to.
    monkeypatch.setenv("CLAUDE_BIN", str(tmp_path / "real-claude"))
    (tmp_path / "real-claude").write_text("#!/bin/sh\n", encoding="utf-8")

    state = _parse_dispatch_health_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["details"]["claude_bin"] == str(tmp_path / "real-claude")
    assert state["breached"] is False


def test_missing_binary_breaches_critical(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_BIN", str(tmp_path / "nope"))

    state = _parse_dispatch_health_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is True
    assert state["level"] == "critical"
    assert state["details"]["exists"] is False


@pytest.mark.skipif(
    not Path(os.path.expanduser("~/.local/bin/claude")).exists(),
    reason="dispatch binary not installed on this host",
)
def test_live_default_binary_resolves(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_BIN", raising=False)

    state = _parse_dispatch_health_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is False
