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

from scripts.dispatch_supervisor import codex_failover, worker
from volpred.ops.alerts import (
    CODEX_FAILOVER_BIN_DEFAULT,
    DISPATCH_CLAUDE_BIN_DEFAULT,
    _parse_codex_failover_ready_state,
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


# ── codex_failover_ready ─────────────────────────────────────────────────────
# The Claude→Codex failover only executes during a quota/auth outage, so a broken
# one is indistinguishable from an idle one. It was orphaned by the 2026-07-04
# cutover for six days on exactly that blind spot. These pin the probe that makes
# it observable on a healthy day.


def test_alerts_codex_default_matches_failover() -> None:
    """Single source of truth is `codex_failover._NVM_CODEX`. Bump the nvm node
    version there and this fails until the alert's literal is bumped too —
    otherwise the probe would validate a path the failover no longer uses, which
    is the 2026-07-08 "monitor pointed at a corpse" failure all over again.
    """
    assert CODEX_FAILOVER_BIN_DEFAULT == codex_failover._NVM_CODEX


def _write_fake_codex(path: Path, *, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_working_codex_is_not_a_breach(tmp_path: Path, monkeypatch) -> None:
    bin_path = _write_fake_codex(tmp_path / "codex", body="#!/bin/sh\necho 'codex-cli 0.144.1'\n")
    monkeypatch.setenv("CODEX_BIN", str(bin_path))

    state = _parse_codex_failover_ready_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is False
    assert state["details"]["reason"] == "ok"
    assert "0.144.1" in state["details"]["version"]


def test_missing_codex_binary_breaches_warn_not_critical(tmp_path: Path, monkeypatch) -> None:
    # warn: the primary dispatch path still works; only the quota-window backup is gone.
    monkeypatch.setenv("CODEX_BIN", str(tmp_path / "nope"))
    monkeypatch.setattr("volpred.ops.alerts.shutil.which", lambda _n: None)
    monkeypatch.setattr("volpred.ops.alerts.CODEX_FAILOVER_BIN_DEFAULT", str(tmp_path / "also-nope"))

    state = _parse_codex_failover_ready_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is True
    assert state["level"] == "warn"
    assert state["details"]["reason"] == "binary_missing"


def test_broken_node_runtime_breaches_even_though_the_file_exists(tmp_path: Path, monkeypatch) -> None:
    # The real binary is a `#!/usr/bin/env node` shebang script. An existence check
    # alone would call a corrupt node runtime healthy; running --version catches it.
    bin_path = _write_fake_codex(tmp_path / "codex", body="#!/bin/sh\nexit 7\n")
    monkeypatch.setenv("CODEX_BIN", str(bin_path))

    state = _parse_codex_failover_ready_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is True
    assert state["details"]["reason"] == "version_nonzero"
    assert state["details"]["rc"] == 7


def test_hanging_codex_breaches_rather_than_stalling_the_monitor(tmp_path: Path, monkeypatch) -> None:
    bin_path = _write_fake_codex(tmp_path / "codex", body="#!/bin/sh\nsleep 30\n")
    monkeypatch.setenv("CODEX_BIN", str(bin_path))
    monkeypatch.setattr("volpred.ops.alerts.CODEX_FAILOVER_PROBE_TIMEOUT_S", 1)

    state = _parse_codex_failover_ready_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is True
    assert state["details"]["reason"] == "version_timeout"


def test_condition_is_wired_into_the_report() -> None:
    # A condition nobody calls is the very bug this file exists to prevent.
    import inspect

    from volpred.ops import alerts as alerts_mod

    src = inspect.getsource(alerts_mod.build_alert_condition_report)
    assert "_parse_codex_failover_ready_state" in src


@pytest.mark.skipif(
    not Path(os.path.expanduser("~/.local/bin/claude")).exists(),
    reason="dispatch binary not installed on this host",
)
def test_live_default_binary_resolves(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CLAUDE_BIN", raising=False)

    state = _parse_dispatch_health_state(str(tmp_path), datetime.now(timezone.utc))

    assert state["breached"] is False
