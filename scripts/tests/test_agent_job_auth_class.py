"""An auth wall must not be filed as a research failure.

2026-07-14: the K1709 rev3 review agent died five seconds in with
`Not logged in · Please run /login`. The runner saw only "exit 1", the queue filed
it `failed`, and the followup brief sent the next fire to comb a worktree for
salvageable results — of an agent that had never started. Meanwhile the same
`claude` CLI was authenticating fine for supervisor fires before and after.

These tests pin the three behaviours that fix costs us nothing to keep:
retry the wall, name it when it does not fall, and never retry a real failure.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import run_agent_job  # noqa: E402
from scripts.dispatch_supervisor import failure_class  # noqa: E402


class _FakeAgent:
    """Stands in for `claude -p`: replays a scripted exit code + banner per attempt."""

    def __init__(self, attempts: list[tuple[int, str]]) -> None:
        self.attempts = attempts
        self.calls = 0

    def __call__(self, argv, workdir, env, timeout):
        exit_code, output = self.attempts[min(self.calls, len(self.attempts) - 1)]
        self.calls += 1
        return exit_code, False, output


AUTH_BANNER = "Not logged in · Please run /login\n"
QUOTA_BANNER = "You've hit your weekly limit · resets 4pm\n"


def _run(monkeypatch, tmp_path, attempts, extra_argv=()):
    fake = _FakeAgent(attempts)
    monkeypatch.setattr(run_agent_job, "_run_attempt", fake)
    monkeypatch.setattr(run_agent_job.time, "sleep", lambda _s: None)  # don't really wait
    # These tests exercise auth-retry classification, not the cwd guard; accept
    # the tmp workdir as if it were a registered linked worktree.
    monkeypatch.setattr(run_agent_job, "is_registered_linked_worktree", lambda *_a, **_k: True)

    brief = tmp_path / "brief.md"
    brief.write_text("do the thing")
    meta = tmp_path / "meta.json"
    argv = [
        "--brief-file", str(brief),
        "--job-metadata", str(meta),
        "--cwd", str(tmp_path),
        "--timeout", "3600",
        *extra_argv,
    ]
    monkeypatch.setattr(sys, "argv", ["run_agent_job.py", *argv])
    rc = run_agent_job.main()
    return rc, json.loads(meta.read_text()), fake


def test_transient_auth_wall_is_retried_and_the_agent_still_runs(monkeypatch, tmp_path):
    """A credential refresh racing the spawn must cost a retry, not the whole job."""
    rc, meta, fake = _run(monkeypatch, tmp_path, [(1, AUTH_BANNER), (0, "done\n")])

    assert fake.calls == 2
    assert rc == 0
    assert meta["failure_class"] is None
    assert meta["attempts"] == 2


def test_persistent_auth_wall_is_named_not_blamed_on_the_research(monkeypatch, tmp_path):
    """A real logout must be reported AS a logout — the work never ran."""
    rc, meta, fake = _run(monkeypatch, tmp_path, [(1, AUTH_BANNER)])

    assert fake.calls == run_agent_job.AUTH_MAX_ATTEMPTS
    assert rc == 1
    assert meta["failure_class"] == "auth"


def test_a_real_failure_is_never_retried(monkeypatch, tmp_path):
    """The agent ran and failed. Retrying would just burn another hour."""
    rc, meta, fake = _run(monkeypatch, tmp_path, [(1, "AssertionError: QLIKE regression\n")])

    assert fake.calls == 1
    assert rc == 1
    assert meta["failure_class"] is None


def test_no_retry_when_the_remaining_budget_cannot_fit_the_work(monkeypatch, tmp_path):
    """Starting an attempt with no room to finish would fail it a second way."""
    import time as _time

    deadline = _time.monotonic() + 30  # less than the backoff + minimum budget
    assert run_agent_job._should_retry_auth("auth", attempts=1, deadline=deadline) is False


@pytest.mark.parametrize(
    "banner,expected",
    [
        (AUTH_BANNER, "auth"),
        (QUOTA_BANNER, "quota"),
        ("Error: 529 Overloaded", "transient"),
        ("AssertionError: QLIKE regression", None),
    ],
)
def test_both_claude_spawners_classify_from_one_definition(banner, expected):
    """The supervisor and the agent-job runner must not drift apart on what auth looks like."""
    from scripts.dispatch_supervisor import worker

    assert failure_class.classify_output(banner) == expected
    # worker keeps its exit-code sentinels but defers the output classes to the same module
    assert worker._classify(1, banner) == (expected or "hard_failure")


def test_the_queue_asks_for_a_re_enqueue_not_a_worktree_autopsy(tmp_path):
    """An auth-killed job has no worktree to triage; the brief must say so."""
    from scripts import compute_queue

    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"failure_class": "auth", "attempts": 3}))
    job = {
        "id": "agent-brief_k1709-x",
        "kind": "agent",
        "status": "failed",
        "exit_code": 1,
        "cwd": ".claude/worktrees/some-wt",
        "job_metadata": str(meta),
        "claude_followup": {"brief": "collect the verdict", "priority": 1},
    }

    row = compute_queue._pending_followup_view(job)

    brief = row["claude_followup"]["brief"]
    assert "BLOCKED ON AUTH" in brief
    assert "RE-ENQUEUE" in brief
    assert "salvage" not in brief.split("Do NOT")[0]  # no salvage instruction before the prohibition


def test_a_genuinely_failed_job_still_gets_the_triage_brief(tmp_path):
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"failure_class": None}))
    job = {
        "id": "agent-brief_k1710-x",
        "kind": "agent",
        "status": "failed",
        "exit_code": 1,
        "cwd": ".claude/worktrees/some-wt",
        "job_metadata": str(meta),
        "claude_followup": {"brief": "collect the verdict", "priority": 1},
    }

    row = compute_queue_followup(job)
    assert "TRIAGE FAILED AGENT JOB" in row["claude_followup"]["brief"]


def compute_queue_followup(job):
    from scripts import compute_queue

    return compute_queue._pending_followup_view(job)
