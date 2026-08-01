"""Slot cap + occupancy invariants.

2026-07-13 incident (`ops_slot_capacity_and_zombie_worktrees`): four worktrees
pinned the dispatcher at "occupied=4/4, NO agent dispatch candidates" for hours
while 34 tasks sat pending, six of them P1. Two failures stacked:

  1. Two sources of truth for the cap. `continue_task_dispatch.SLOT_CAP = 4` was
     a literal; `dispatch_slot_budget.budget()` computed 4/6/2 dynamically. The
     literal won, because it was the one the dispatcher read.
  2. Occupancy meant "a directory exists under .claude/worktrees/". A hung agent
     therefore held a slot forever. Note that a process-liveness check would NOT
     have caught it: both zombies still had live claude processes holding the
     worktree as cwd, two days after their last commit. Liveness is not progress.

These tests pin both. Keep them mechanical — prose in a rule file is what failed.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import dispatch_slot_budget as sb


@pytest.fixture(autouse=True)
def isolate_live_occupancy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cap tests must not inspect developer-only worktrees or agent receipts."""
    monkeypatch.setattr(sb, "WORKTREES_DIR", tmp_path / "no-live-worktrees")
    monkeypatch.setattr(sb, "AGENTS_DIR", tmp_path / "no-live-agents")
    monkeypatch.setattr(sb, "AGENT_JOBS_DIR", tmp_path / "no-agent-jobs")


# --- 1. cap has exactly one owner -------------------------------------------

def test_dispatcher_has_no_hardcoded_slot_cap():
    """The dispatcher must import the cap, never redeclare it."""
    src = (ROOT / "scripts" / "continue_task_dispatch.py").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in src.splitlines()
        if line.lstrip().startswith("SLOT_CAP") and "=" in line
    ]
    assert not offenders, (
        "`SLOT_CAP` literal is back in continue_task_dispatch.py — the cap has one "
        f"owner (dispatch_slot_budget.budget()). Offending: {offenders}"
    )


def test_budget_surges_on_p1_backlog_and_derates_when_auth_blocked(tmp_path):
    tasks = tmp_path / "next_tasks.json"
    state = tmp_path / "dispatch_state.json"

    tasks.write_text('[{"status":"pending","priority":1}]')
    state.write_text("{}")
    assert sb.budget(tasks, state)["cap"] == sb.BASE_CAP

    tasks.write_text(
        "[" + ",".join(['{"status":"pending","priority":1}'] * sb.P1_SURGE_AT) + "]"
    )
    surged = sb.budget(tasks, state)
    assert surged["cap"] == sb.SURGE_CAP
    assert surged["p1_only_slots"] == sb.SURGE_CAP - sb.BASE_CAP

    # A quota outage takes down the whole loop, not one fire — never surge into it.
    state.write_text('{"auth_blocked": true}')
    assert sb.budget(tasks, state)["cap"] == sb.DERATE_CAP


# --- 2. occupancy is progress, not directory existence, not liveness ---------

def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def fake_worktrees(tmp_path):
    """Two git repos standing in for worktrees: one fresh, one long-idle."""
    root = tmp_path / "worktrees"
    root.mkdir()
    made = {}
    for name in ("fresh", "idle"):
        wt = root / name
        wt.mkdir()
        _git("init", "-q", cwd=wt)
        _git("config", "user.email", "t@t", cwd=wt)
        _git("config", "user.name", "t", cwd=wt)
        (wt / "f.txt").write_text("x")
        _git("add", "-A", cwd=wt)
        _git("commit", "-qm", "c", cwd=wt)
        made[name] = wt
    return root, made


def test_worktree_artifact_never_holds_a_slot_without_execution_lease(
    fake_worktrees, monkeypatch,
):
    root, _ = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)

    # A checkout is artifact custody, not an execution lease.
    slots = {w["name"]: w for w in sb.worktree_slots()}
    assert not slots["fresh"]["live"] and not slots["idle"]["live"]
    assert slots["fresh"]["release_reason"] == "artifact_without_execution_lease"

    # Fast-forward past the threshold: with no new progress, both go stale.
    later = time.time() + (sb.STALE_HOURS + 1) * 3600
    slots = {w["name"]: w for w in sb.worktree_slots(now=later)}
    assert not slots["fresh"]["live"]
    assert not slots["idle"]["live"]


def test_recent_commit_is_visible_but_does_not_hold_a_slot(
    fake_worktrees, monkeypatch,
):
    """Recent commits remain visible but cannot manufacture a capacity lease."""
    root, made = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)

    later = time.time() + (sb.STALE_HOURS + 1) * 3600
    (made["fresh"] / "g.txt").write_text("progress")
    _git("add", "-A", cwd=made["fresh"])
    _git("commit", "-qm", "progress", cwd=made["fresh"])

    # `fresh` committed just now, so relative to `later` it is only ~0h idle...
    # simulate by evaluating at real now: it is live, and `idle` (old commit) is
    # only stale once we look from the future.
    slots_now = {w["name"]: w for w in sb.worktree_slots()}
    assert slots_now["fresh"]["live"] is False
    assert slots_now["fresh"]["progress_at"] is not None

    slots_later = {w["name"]: w for w in sb.worktree_slots(now=later)}
    assert not slots_later["idle"]["live"], "no-progress worktree must release its slot"


def test_uncommitted_work_counts_as_progress(fake_worktrees, monkeypatch):
    """Dirty artifacts stay visible for salvage but own no scheduler capacity."""
    root, made = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)

    scratch = made["idle"] / "wip.py"
    scratch.write_text("# agent is writing right now")

    slots = {w["name"]: w for w in sb.worktree_slots()}
    assert slots["idle"]["live"] is False
    assert slots["idle"]["release_reason"] == "artifact_without_execution_lease"
    assert slots["idle"]["progress_at"] is not None


def _write_terminal_agent_job(path: Path, *, cwd: Path, finished_epoch: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "execution_id": path.stem,
            "state": "terminal",
            "cwd": str(cwd),
            "runner_pid": 123,
            "started_at": datetime.fromtimestamp(
                finished_epoch - 60, UTC,
            ).isoformat(),
            "finished_at": datetime.fromtimestamp(
                finished_epoch, UTC,
            ).isoformat(),
            "timed_out": True,
            "termination_confirmed": True,
            "exit_code": -1,
            "runner_exit_code": 1,
            "result_artifact_exists": True,
        }),
        encoding="utf-8",
    )


def _write_running_agent_job(path: Path, *, cwd: Path, started_epoch: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "execution_id": path.stem,
            "state": "running",
            "cwd": str(cwd),
            "runner_pid": 456,
            "started_at": datetime.fromtimestamp(started_epoch, UTC).isoformat(),
            "finished_at": None,
            "timed_out": False,
            "termination_confirmed": None,
            "exit_code": None,
            "runner_exit_code": None,
        }),
        encoding="utf-8",
    )


def test_terminal_agent_receipt_releases_fresh_worktree_slot_immediately(
    fake_worktrees,
):
    """Artifact custody survives, but a finished execution owns no capacity."""
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    finished = time.time() + 1
    _write_terminal_agent_job(
        jobs / "k1735.json", cwd=made["fresh"], finished_epoch=finished,
    )

    slots = {
        item["name"]: item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
    }

    assert slots["fresh"]["live"] is False
    assert slots["fresh"]["release_reason"] == "terminal_agent_job"
    assert slots["fresh"]["terminal_job"]["timed_out"] is True
    assert slots["idle"]["live"] is False
    assert slots["idle"]["release_reason"] == "artifact_without_execution_lease"

    occupancy = sb.occupancy(
        worktrees_dir=root,
        agents_dir=root.parent / "no-agents",
        agent_jobs_dir=jobs,
    )
    assert occupancy["occupied"] == 0
    assert occupancy["worktrees"] == []
    assert any(
        item["name"] == "fresh"
        and item.get("release_reason") == "terminal_agent_job"
        for item in occupancy["stale"]
    ), "released artifacts remain visible for salvage; only capacity is freed"


def test_new_progress_after_terminal_is_unowned_not_a_capacity_lease(
    fake_worktrees,
):
    """An old receipt cannot release a later execution that reused the path."""
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    _write_terminal_agent_job(
        jobs / "old-run.json",
        cwd=made["fresh"],
        finished_epoch=time.time() - 3600,
    )
    scratch = made["fresh"] / "new-run.py"
    scratch.write_text("# later execution progress", encoding="utf-8")

    slots = {
        item["name"]: item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
    }

    assert slots["fresh"]["live"] is False
    assert slots["fresh"].get("terminal_job") is None
    assert slots["fresh"]["release_reason"] == "unowned_progress_after_terminal"


def test_new_running_generation_supersedes_old_terminal_before_first_mutation(
    fake_worktrees,
):
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    now = time.time()
    _write_terminal_agent_job(
        jobs / "old.json", cwd=made["fresh"], finished_epoch=now - 60,
    )
    _write_running_agent_job(
        jobs / "new.json", cwd=made["fresh"], started_epoch=now,
    )

    slot = next(
        item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
        if item["name"] == "fresh"
    )

    assert slot["live"] is True
    assert slot["active_job"]["state"] == "running"
    assert slot["active_job"]["execution_id"] == "new"
    assert slot.get("terminal_job") is None


def test_unverified_termination_receipt_keeps_lease_held(fake_worktrees):
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    finished = time.time()
    _write_terminal_agent_job(
        jobs / "uncertain.json", cwd=made["fresh"], finished_epoch=finished,
    )
    payload = json.loads((jobs / "uncertain.json").read_text())
    payload["state"] = "termination_unverified"
    payload["termination_confirmed"] = False
    (jobs / "uncertain.json").write_text(json.dumps(payload), encoding="utf-8")

    slot = next(
        item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
        if item["name"] == "fresh"
    )

    assert slot["live"] is True
    assert slot["active_job"]["state"] == "termination_unverified"
    assert slot.get("terminal_job") is None


def test_newer_malformed_generation_quarantines_old_terminal_release(
    fake_worktrees,
):
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    now = time.time()
    _write_terminal_agent_job(
        jobs / "old.json", cwd=made["fresh"], finished_epoch=now - 60,
    )
    malformed = {
        "schema_version": 2,
        "execution_id": "new",
        "state": "running",
        "cwd": str(made["fresh"]),
        # runner_pid intentionally absent: newest generation is not trustworthy.
        "started_at": datetime.fromtimestamp(now, UTC).isoformat(),
        "finished_at": None,
        "timed_out": False,
        "termination_confirmed": None,
        "exit_code": None,
        "runner_exit_code": None,
    }
    (jobs / "new.json").write_text(json.dumps(malformed), encoding="utf-8")

    slot = next(
        item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
        if item["name"] == "fresh"
    )

    assert slot["live"] is True
    assert slot["active_job"]["state"] == "invalid"
    assert slot["active_job"]["execution_id"] == "new"
    assert slot.get("terminal_job") is None


def test_same_second_clean_commit_after_receipt_is_not_misattributed_terminal(
    fake_worktrees,
):
    """Git's second-resolution commit timestamp cannot erase event ordering."""
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    while time.time() % 1 > 0.5:
        time.sleep(0.01)
    finished = time.time()
    _write_terminal_agent_job(
        jobs / "old-run.json",
        cwd=made["fresh"],
        finished_epoch=finished,
    )
    (made["fresh"] / "new-commit.py").write_text("# later execution\n")
    _git("add", "-A", cwd=made["fresh"])
    _git("commit", "-qm", "same-second later progress", cwd=made["fresh"])
    assert math.floor(sb._last_commit_epoch(made["fresh"])) == math.floor(finished)

    slot = next(
        item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
        if item["name"] == "fresh"
    )

    assert slot["live"] is False
    assert slot.get("terminal_job") is None
    assert slot["release_reason"] == "unowned_progress_after_terminal"


@pytest.mark.parametrize(
    "payload",
    [
        {"cwd": "{cwd}", "finished_at": "2099-01-01T00:00:00+00:00"},
        {
            "schema_version": 2,
            "execution_id": "naive-time",
            "state": "terminal",
            "cwd": "{cwd}",
            "runner_pid": 123,
            "started_at": "2026-08-01T00:00:00",
            "finished_at": "2026-08-01T01:00:00",
            "timed_out": False,
            "termination_confirmed": True,
            "exit_code": 0,
            "runner_exit_code": 0,
        },
        {
            "schema_version": 2,
            "execution_id": "future-time",
            "state": "terminal",
            "cwd": "{cwd}",
            "runner_pid": 123,
            "started_at": "2099-01-01T00:00:00+00:00",
            "finished_at": "2099-01-01T01:00:00+00:00",
            "timed_out": False,
            "termination_confirmed": True,
            "exit_code": 0,
            "runner_exit_code": 0,
        },
        {
            "cwd": "\x00",
            "started_at": "2026-08-01T00:00:00+00:00",
            "finished_at": "2026-08-01T01:00:00+00:00",
            "timed_out": True,
            "exit_code": -1,
            "runner_exit_code": 1,
        },
    ],
)
def test_malformed_terminal_receipt_warns_and_cannot_release(
    fake_worktrees,
    capsys,
    payload,
):
    root, made = fake_worktrees
    jobs = root.parent / "agent_jobs"
    jobs.mkdir()
    materialized = {
        key: (str(made["fresh"]) if value == "{cwd}" else value)
        for key, value in payload.items()
    }
    (jobs / "partial.json").write_text(json.dumps(materialized), encoding="utf-8")

    slot = next(
        item
        for item in sb.worktree_slots(worktrees_dir=root, agent_jobs_dir=jobs)
        if item["name"] == "fresh"
    )

    assert slot.get("terminal_job") is None
    if slot.get("active_job"):
        assert slot["live"] is True
        assert slot["active_job"]["state"] == "invalid"
    else:
        assert slot["live"] is False
        assert slot["release_reason"] == "artifact_without_execution_lease"
    assert "不用它釋放 slot" in capsys.readouterr().err


def test_occupancy_reports_unleased_artifacts_without_counting_them(
    fake_worktrees, monkeypatch,
):
    root, _ = fake_worktrees
    monkeypatch.setattr(sb, "WORKTREES_DIR", root)
    monkeypatch.setattr(sb, "AGENTS_DIR", root / "does-not-exist")

    occ = sb.occupancy()
    assert occ["occupied"] == 0
    assert len(occ["stale"]) == 2
    assert all(
        item["release_reason"] == "artifact_without_execution_lease"
        for item in occ["stale"]
    )

    later = time.time() + (sb.STALE_HOURS + 1) * 3600
    occ = sb.occupancy(now=later)
    assert occ["occupied"] == 0, "stale worktrees must not consume capacity"
    assert len(occ["stale"]) == 2, "…but they must still be reported, not silently dropped"


def test_monkeypatched_agent_root_also_isolates_execution_receipts(
    tmp_path, monkeypatch,
):
    """The long-standing AGENTS_DIR fixture contract must isolate all ops state."""
    isolated_agents = tmp_path / "isolated" / "agents"
    live_jobs = tmp_path / "live" / "agent_jobs"
    live_worktree = tmp_path / "worktree"
    isolated_agents.mkdir(parents=True)
    live_jobs.mkdir(parents=True)
    live_worktree.mkdir()
    (live_jobs / "running.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "execution_id": "must-not-leak",
                "state": "running",
                "cwd": str(live_worktree),
                "runner_pid": 123,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "timed_out": False,
                "termination_confirmed": None,
                "exit_code": None,
                "runner_exit_code": None,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sb, "AGENTS_DIR", isolated_agents)
    monkeypatch.setattr(sb, "AGENT_JOBS_DIR", live_jobs)
    monkeypatch.setattr(sb, "WORKTREES_DIR", tmp_path / "no-worktrees")

    occ = sb.occupancy()

    assert occ["occupied"] == 0
    assert occ["worktree_detail"] == []


def test_reclaimer_only_targets_expired_formal_execution_leases(
    tmp_path, monkeypatch,
):
    """Artifact custody is not permission to kill or remove a worktree."""
    import reclaim_stale_worktrees as reclaimer

    monkeypatch.setattr(reclaimer.slot_budget, "WORKTREES_DIR", tmp_path)
    monkeypatch.setattr(
        reclaimer.slot_budget,
        "worktree_slots",
        lambda: [
            {
                "name": "artifact-only",
                "idle_hours": 100.0,
                "release_reason": "artifact_without_execution_lease",
            },
            {
                "name": "expired-lease",
                "idle_hours": 3.0,
                "release_reason": "no_progress_timeout",
            },
        ],
    )
    monkeypatch.setattr(reclaimer, "_branch_of", lambda path: f"branch/{path.name}")
    monkeypatch.setattr(reclaimer, "_is_dirty", lambda path: False)
    monkeypatch.setattr(reclaimer, "_holder_pids", lambda path: [])
    monkeypatch.setattr(reclaimer, "_unmerged_count", lambda branch: 0)

    report = reclaimer.reclaim(apply=False)

    assert report["stale_count"] == 1
    assert [item["worktree"] for item in report["actions"]] == ["expired-lease"]


def test_unreadable_agent_record_warns_and_holds_no_slot(tmp_path, monkeypatch, capsys):
    """A corrupt agent record must not be swallowed: it frees the slot AND says so.

    Moved here from tests/test_dispatch_type_rotation.py on 2026-07-13. There it
    patched `continue_task_dispatch.{WORKTREES_DIR,AGENTS_DIR}` — globals that
    stopped being read when occupancy moved into this module. The patch became a
    no-op, so the test read the real `.claude/worktrees` and went red in CI.
    """
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "bad-agent.json").write_text("{bad-json", encoding="utf-8")
    monkeypatch.setattr(sb, "WORKTREES_DIR", tmp_path / "no-worktrees")
    monkeypatch.setattr(sb, "AGENTS_DIR", agents)

    occ = sb.occupancy()

    assert occ["occupied"] == 0 and occ["active_agents"] == []
    err = capsys.readouterr().err
    assert "[slot-budget] WARN" in err and "bad-agent.json" in err, (
        "an unparseable agent record must leave a trace (.claude/rules/"
        f"no-silent-fallback.md); stderr was: {err!r}"
    )


@pytest.mark.parametrize(
    ("payload", "warning"),
    [
        (b"[]", "root \u4e0d\u662f object"),
        (b'"text"', "root \u4e0d\u662f object"),
        (b'{"status":[]}', "status \u4e0d\u662f string"),
        (b'{"status":"\xff"}', "UnicodeDecodeError"),
    ],
)
def test_invalid_agent_schema_warns_and_holds_no_slot(
    tmp_path,
    monkeypatch,
    capsys,
    payload,
    warning,
):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "bad-agent.json").write_bytes(payload)
    monkeypatch.setattr(sb, "WORKTREES_DIR", tmp_path / "no-worktrees")
    monkeypatch.setattr(sb, "AGENTS_DIR", agents)

    occ = sb.occupancy()

    assert occ["occupied"] == 0
    assert occ["active_agents"] == []
    assert occ["agent_detail"] == []
    err = capsys.readouterr().err
    assert "[slot-budget] WARN" in err
    assert "bad-agent.json" in err
    assert warning in err


def test_dispatcher_keeps_no_occupancy_paths_of_its_own():
    """The dispatcher must not re-declare the paths occupancy is measured from.

    A global nothing reads is worse than no global: `monkeypatch.setattr` still
    succeeds against it, so a test patches a dead name, silently falls through to
    the real repo, and only fails once the return shape drifts. That is the exact
    2026-07-13 CI red. Cap and occupancy have one owner — this module.
    """
    src = (ROOT / "scripts" / "continue_task_dispatch.py").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in src.splitlines()
        if line.lstrip().startswith(("WORKTREES_DIR", "AGENTS_DIR")) and "=" in line
    ]
    assert not offenders, (
        "continue_task_dispatch.py re-declared an occupancy path. Read it from "
        f"dispatch_slot_budget instead. Offending: {offenders}"
    )
