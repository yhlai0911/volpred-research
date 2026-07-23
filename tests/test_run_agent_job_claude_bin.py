"""Regression test: the agent runner finds the Claude CLI under a launchd PATH.

2026-07-20 incident (job k528_round5_collection): the job died one second after
start with `FileNotFoundError: [Errno 2] No such file or directory: 'claude'`
and was filed as a failed research job. Nothing was wrong with the research.

launchd hands its jobs a minimal PATH that omits ~/.local/bin, where the CLI
actually lives. `cron_compute_worker.sh` already compensates for this for `uv`
(it spells out /opt/homebrew/bin/uv) but nothing did the same for `claude`, so
every kind=agent job drained by the launchd worker was unrunnable. kind=compute
jobs never exec the CLI, which is why the breakage stayed invisible until an
agent job happened to land on that worker.

Resolution lives in the runner, not the wrapper, so that launchd, cron and
interactive runs all share one answer to "can we exec the CLI".
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_agent_job import _resolve_claude_bin  # noqa: E402


def test_resolves_from_fallback_when_path_omits_local_bin(monkeypatch, tmp_path) -> None:
    """The launchd condition: `claude` is absent from PATH but installed on disk."""
    monkeypatch.delenv("VOLPRED_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")

    installed = tmp_path / "claude"
    installed.write_text("#!/bin/sh\n")
    installed.chmod(0o755)
    monkeypatch.setattr(
        "scripts.run_agent_job._CLAUDE_FALLBACK_PATHS", (installed,)
    )

    assert _resolve_claude_bin() == str(installed)


def test_raises_when_the_cli_is_nowhere(monkeypatch, tmp_path) -> None:
    """A missing CLI must fail loudly here, not as a Popen traceback later.

    Falling back to the bare name `claude` would defer the same FileNotFoundError
    into the agent attempt, where failure_class reads it as a research failure
    and sends a triage agent to inspect a worktree that is perfectly fine.
    """
    monkeypatch.delenv("VOLPRED_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(
        "scripts.run_agent_job._CLAUDE_FALLBACK_PATHS", (tmp_path / "absent",)
    )

    with pytest.raises(FileNotFoundError, match="VOLPRED_CLAUDE_BIN"):
        _resolve_claude_bin()


def test_explicit_override_wins(monkeypatch) -> None:
    monkeypatch.setenv("VOLPRED_CLAUDE_BIN", "/bin/echo")
    assert _resolve_claude_bin() == "/bin/echo"


def test_unresolvable_override_is_a_config_error_not_a_silent_search(
    monkeypatch, tmp_path
) -> None:
    """An override that doesn't resolve must not license searching elsewhere."""
    monkeypatch.setenv("VOLPRED_CLAUDE_BIN", "/nonexistent/claude")
    installed = tmp_path / "claude"
    installed.write_text("#!/bin/sh\n")
    installed.chmod(0o755)
    monkeypatch.setattr(
        "scripts.run_agent_job._CLAUDE_FALLBACK_PATHS", (installed,)
    )

    with pytest.raises(FileNotFoundError, match="not an executable"):
        _resolve_claude_bin()
