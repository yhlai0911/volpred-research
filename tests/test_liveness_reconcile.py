"""WS-A4 liveness reconciler — declaration vs disk vs process.

The injected-zombie test is the gate named in
`docs/refactor_plan_ops_master_2026_07.md` §WS-A4: a task declaring itself
in_flight while neither its worktree nor its pid exists must come back to the
pool by itself. The mirror-image tests are the ones that keep it safe — each
single surviving signal (young claim / live pid / worktree on disk) must be
enough to protect a claim on its own.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "liveness_reconcile.py"
SPEC = importlib.util.spec_from_file_location("liveness_reconcile", MODULE_PATH)
liveness_reconcile = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(liveness_reconcile)

REPO_ROOT = MODULE_PATH.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
# Job ids are hex in production (uuid4().hex) and the owner-token regex says so,
# so the fixtures must be hex too or they read as unmappable owners.
DEAD_JOB = "deadbeef" + "0" * 24
LIVE_JOB = "a11ce0de" + "0" * 24
DEAD_OWNER = f"hourly-slot-2-{DEAD_JOB}"
LIVE_OWNER = f"hourly-slot-2-{LIVE_JOB}"


def _task(task_id: str, *, owner: str, claimed_minutes_ago: float, **extra) -> dict:
    return {
        "id": task_id,
        "title": task_id,
        "status": "in_progress",
        "claimed_by": owner,
        "claimed_at": (NOW - timedelta(minutes=claimed_minutes_ago)).isoformat(),
        **extra,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A queue + dispatch_state + worktrees tree with nothing real behind it."""
    next_tasks = tmp_path / "next_tasks.json"
    dispatch_state = tmp_path / "dispatch_state.json"
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()

    # The dead job is retired into the completions ring — exactly what the
    # supervisor does when a fire ends while its claim is still outstanding.
    dispatch_state.write_text(
        json.dumps(
            {
                "current_jobs": [
                    {
                        "job_id": LIVE_JOB,
                        "slot_id": 2,
                        "pid": 4242,
                        "pgid": 4242,
                        "phase": "running",
                        "started_wall": "Mon Jul 20 19:30:00 2026",
                    }
                ],
                "completions": [
                    {
                        "job_id": DEAD_JOB,
                        "completed_at": "2026-07-20T10:00:00+00:00",
                        "outcome": "success",
                        "exit_code": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # `check_identity` must never reach the real `ps`: a test that shells out
    # would pass or fail on whatever pid the host happens to be running.
    monkeypatch.setattr(
        liveness_reconcile.procutil,
        "check_identity",
        lambda pid, wall: liveness_reconcile.procutil.IDENTITY_MATCH,
    )
    return {
        "next_tasks": next_tasks,
        "dispatch_state": dispatch_state,
        "worktrees": worktrees,
    }


def _run(env, tasks, **kwargs):
    env["next_tasks"].write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    return liveness_reconcile.reconcile(
        now=NOW,
        next_tasks_path=env["next_tasks"],
        dispatch_state_path=env["dispatch_state"],
        worktrees_dir=env["worktrees"],
        **kwargs,
    )


def test_detached_in_flight_task_is_repended(env, monkeypatch):
    """Worktree gone + pid gone + past grace => back to pending."""
    task = _task("zombie_task", owner=DEAD_OWNER, claimed_minutes_ago=90)
    report = _run(env, [task])

    assert report["detached_count"] == 1
    assert report["detached_task_ids"] == ["zombie_task"]
    entry = report["detached"][0]
    assert entry["process"] == "dead"
    assert entry["worktree_present"] is False
    assert "no worktree on disk" in entry["rationale"]
    assert report["released_count"] == 0  # dry-run touched nothing

    # …and the apply path hands it back through the canonical helper only.
    calls = []

    class _FakePool:
        @staticmethod
        def release_owner_claims(owners, *, reason, note=None):
            calls.append({"owners": list(owners), "reason": reason, "note": note})
            return {"ok": True, "released": [{"id": "zombie_task", "owner": DEAD_OWNER}]}

    monkeypatch.setattr(liveness_reconcile, "_task_pool_claim", lambda: _FakePool)
    applied = _run(env, [task], apply=True)

    assert applied["released_count"] == 1
    assert calls == [
        {
            "owners": [DEAD_OWNER],
            "reason": f"liveness_reconcile_detached_{DEAD_JOB[:8]}",
            "note": calls[0]["note"],
        }
    ]
    assert "liveness_reconcile" in calls[0]["note"]
    assert applied["detached"][0]["released"] is True
    assert applied["detached"][0]["released_at"]


def test_repend_goes_through_canonical_helper_end_to_end(env, monkeypatch, tmp_path):
    """The real `task_pool_claim` writer, on a throwaway pool, must leave the
    task `pending` with the release reason recorded — not merely be called."""
    import importlib.util as _ilu

    tpc_path = REPO_ROOT / "scripts" / "task_pool_claim.py"
    spec = _ilu.spec_from_file_location("task_pool_claim_a4", tpc_path)
    tpc = _ilu.module_from_spec(spec)
    spec.loader.exec_module(tpc)

    pool = tmp_path / "pool_next_tasks.json"
    task = _task("zombie_task", owner=DEAD_OWNER, claimed_minutes_ago=90)
    pool.write_text(json.dumps([task], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(tpc, "NEXT_TASKS", pool)
    monkeypatch.setattr(liveness_reconcile, "_task_pool_claim", lambda: tpc)

    report = _run(env, [task], apply=True)
    assert report["released_count"] == 1

    written = json.loads(pool.read_text(encoding="utf-8"))[0]
    assert written["status"] == "pending"
    assert "claimed_by" not in written
    assert written["last_release_reason"].startswith("liveness_reconcile_detached_")
    assert written["status_history"][-1]["to"] == "pending"


def test_claim_inside_grace_window_is_not_repended(env):
    """A fire two minutes old has not built its worktree yet — that is not a
    zombie, and re-pending it would race a live agent."""
    task = _task("fresh_task", owner=DEAD_OWNER, claimed_minutes_ago=2)
    report = _run(env, [task], grace_minutes=20)

    assert report["detached_count"] == 0
    assert report["retained"][0]["verdict"] == "in_grace"


def test_live_process_alone_protects_a_claim(env):
    """Missing worktree is the normal state of a healthy main-checkout fire."""
    task = _task("running_task", owner=LIVE_OWNER, claimed_minutes_ago=90)
    report = _run(env, [task])

    assert report["detached_count"] == 0
    assert report["retained"][0]["verdict"] == "process_alive"


def test_surviving_worktree_alone_protects_a_claim(env):
    """Dead pid but a checkout still on disk => bookkeeping problem, not a free
    slot. Re-pending would invite a second agent to redo unmerged work."""
    (env["worktrees"] / f"dispatch-slot-2-{DEAD_JOB[:8]}-k9999").mkdir()
    task = _task("worktree_task", owner=DEAD_OWNER, claimed_minutes_ago=90)
    report = _run(env, [task])

    assert report["detached_count"] == 0
    assert report["retained"][0]["verdict"] == "worktree_on_disk"


def test_unverifiable_pid_probe_is_not_death(env, monkeypatch):
    """A `ps` that could not be completed proves nothing (procutil.PROBE_FAILED)."""
    monkeypatch.setattr(
        liveness_reconcile.procutil,
        "check_identity",
        lambda pid, wall: liveness_reconcile.procutil.IDENTITY_UNVERIFIED,
    )
    task = _task("unverified_task", owner=LIVE_OWNER, claimed_minutes_ago=90)
    report = _run(env, [task])

    assert report["detached_count"] == 0
    assert report["retained"][0]["verdict"] == "process_unknown"


def test_non_supervisor_owner_is_reported_but_never_repended(env):
    """An interactive or ad-hoc owner carries no slot/job, so no pid can be
    resolved for it. Unknown is not dead."""
    task = _task("interactive_task", owner="codex-cli", claimed_minutes_ago=600)
    report = _run(env, [task])

    assert report["detached_count"] == 0
    assert report["unmappable"] == [
        {
            "id": "interactive_task",
            "status": "in_progress",
            "claimed_by": "codex-cli",
            "reason": "owner_not_supervisor_scoped",
        }
    ]


def test_youngest_sibling_claim_protects_the_whole_fire(env):
    """One owner = one fire. A task claimed seconds ago proves the fire is
    alive, so its older siblings must not be swept out from under it."""
    tasks = [
        _task("old_sibling", owner=DEAD_OWNER, claimed_minutes_ago=300),
        _task("new_sibling", owner=DEAD_OWNER, claimed_minutes_ago=1),
    ]
    report = _run(env, tasks)

    assert report["detached_count"] == 0
    assert report["retained"][0]["verdict"] == "in_grace"


def test_receipt_records_task_evidence_and_release_time(env, tmp_path, monkeypatch):
    class _FakePool:
        @staticmethod
        def release_owner_claims(owners, *, reason, note=None):
            return {"ok": True, "released": [{"id": "zombie_task", "owner": DEAD_OWNER}]}

    monkeypatch.setattr(liveness_reconcile, "_task_pool_claim", lambda: _FakePool)
    task = _task("zombie_task", owner=DEAD_OWNER, claimed_minutes_ago=90)
    report = _run(env, [task], apply=True)

    receipts = tmp_path / "receipts"
    path = liveness_reconcile.write_receipt(report, receipts_dir=receipts)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["detached"][0]
    assert payload["mode"] == "apply"
    assert entry["task_ids"] == ["zombie_task"]
    assert entry["process_evidence"]["source"] == "dispatch_state.completions"
    assert entry["disk_evidence"]["pattern_matches"] == []
    assert entry["released_at"]


def test_dry_run_writes_no_receipt(env, tmp_path):
    task = _task("zombie_task", owner=DEAD_OWNER, claimed_minutes_ago=90)
    report = _run(env, [task])

    receipts = tmp_path / "receipts_dry"
    assert liveness_reconcile.write_receipt(report, receipts_dir=receipts) is None
    assert not receipts.exists()


def test_terminal_and_pending_rows_are_out_of_scope(env):
    """The reconciler only ever judges a *declaration* of being in flight."""
    tasks = [
        {"id": "done", "status": "succeeded", "claimed_by": DEAD_OWNER},
        {"id": "waiting", "status": "pending"},
    ]
    report = _run(env, tasks)

    assert report["in_flight_declared"] == 0
    assert report["detached_count"] == 0
