"""WS-I actuators — findings must land as queued tasks, idempotently.

Two detectors used to stop at detection: ``reclaim_stale_worktrees`` reported
held (dirty/unmerged) worktrees in a dry-run nobody was scheduled to read, and
``audit_release_settings`` exited 1 on starved drafts with no consumer
(mile_47c4bc3e was skipped 20 times before anything moved). These tests are the
gate on the WS-I fix: each held finding becomes exactly one pending task, a
re-run creates nothing new, and an append failure is loud — never silent.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


reclaim_stale_worktrees = _load("reclaim_stale_worktrees")
audit_release_settings = _load("audit_release_settings")


def _read_queue(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _reclaim_results() -> dict:
    return {
        "apply": False,
        "stale_count": 3,
        "actions": [
            {  # held: dirty
                "worktree": "dispatch-slot-1-aaaa-k9998",
                "branch": "wt/dispatch-slot-1-aaaa-k9998",
                "idle_hours": 30.0,
                "dirty": True,
                "unmerged_commits": 0,
            },
            {  # held: committed but unmerged
                "worktree": "dispatch-slot-2-bbbb-k9999",
                "branch": "wt/dispatch-slot-2-bbbb-k9999",
                "idle_hours": 12.0,
                "dirty": False,
                "unmerged_commits": 4,
            },
            {  # not held: clean and merged — reclaimable, no adjudication needed
                "worktree": "dispatch-slot-3-cccc-clean",
                "branch": "wt/dispatch-slot-3-cccc-clean",
                "idle_hours": 7.0,
                "dirty": False,
                "unmerged_commits": 0,
            },
        ],
    }


def test_salvage_actuator_opens_one_aggregate_task_for_all_held(tmp_path: Path) -> None:
    """incident-lifecycle P3 (plan §2.3/G3): N held worktrees ⇒ 1 incident ⇒ 1 task.

    The per-worktree ``worktree_salvage_<name>`` shape is GONE — 19 of those
    tasks for one root cause was the incident that mandated this refactor.
    """
    from volpred.ops import incident

    queue = tmp_path / "next_tasks.json"
    receipts = reclaim_stale_worktrees.open_salvage_tasks(
        _reclaim_results(), queue_path=queue
    )

    assert len(receipts) == 2  # the clean+merged worktree must NOT register
    tasks = _read_queue(queue)
    assert len(tasks) == 1  # ONE aggregate adjudication task, not one per worktree
    task = tasks[0]
    assert task["status"] == "pending"
    assert task["priority"] == 3
    assert task["dispatch_lane"] == "main_thread"
    assert task["source"] == "incident_adjudication"
    assert "merge_worktree.sh" in task["description"]  # exit path is spelled out
    assert "incidents.json" in task["description"]  # instances live in the store

    store = queue.parent / "ops" / "incidents.json"
    rows = incident.list_incidents(store)
    assert len(rows) == 1
    assert rows[0]["kind"] == "worktree_unmerged"
    assert {i["key"] for i in rows[0]["instances"]} == {
        "dispatch-slot-1-aaaa-k9998",
        "dispatch-slot-2-bbbb-k9999",
    }
    assert task["id"] == rows[0]["current_task_id"]


def test_salvage_actuator_is_idempotent_across_reruns(tmp_path: Path) -> None:
    queue = tmp_path / "next_tasks.json"
    reclaim_stale_worktrees.open_salvage_tasks(_reclaim_results(), queue_path=queue)
    receipts = reclaim_stale_worktrees.open_salvage_tasks(
        _reclaim_results(), queue_path=queue
    )

    assert all(r["created"] is False for r in receipts)
    assert len(_read_queue(queue)) == 1  # no duplicates on the recurring sweep


def test_salvage_append_failure_is_loud_and_does_not_block_others(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    queue = tmp_path / "next_tasks.json"
    from volpred.ops import next_tasks as next_tasks_mod

    real_append = next_tasks_mod.append_task_record
    calls = {"n": 0}

    def flaky_append(record, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk said no")
        return real_append(record, **kwargs)

    monkeypatch.setattr(next_tasks_mod, "append_task_record", flaky_append)
    receipts = reclaim_stale_worktrees.open_salvage_tasks(
        _reclaim_results(), queue_path=queue
    )

    assert receipts[0]["created"] is False
    assert "disk said no" in receipts[0]["error"]
    # The failed append leaves the episode unbound; the next held worktree's
    # routing retries the SAME aggregate task — one failure never aborts the sweep.
    assert receipts[1]["created"] is True
    assert len(_read_queue(queue)) == 1
    err = capsys.readouterr().err
    assert "disk said no" in err  # no-silent-fallback


def test_reclaim_cli_flag_attaches_salvage_receipts(monkeypatch, tmp_path: Path) -> None:
    queue = tmp_path / "next_tasks.json"
    monkeypatch.setattr(
        reclaim_stale_worktrees, "reclaim", lambda apply: _reclaim_results()
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["reclaim_stale_worktrees.py", "--open-tasks", "--queue", str(queue)],
    )
    reclaim_stale_worktrees.main()
    assert len(_read_queue(queue)) == 1


def _starved() -> list[dict]:
    return [
        {"id": "mile_47c4bc3e", "title": "融資衝上去", "skipped": 20},
        {"id": "mile_deadbeef", "title": "另一篇卡池", "skipped": 7},
    ]


def test_starved_draft_actuator_opens_and_dedupes(tmp_path: Path) -> None:
    queue = tmp_path / "next_tasks.json"
    first = audit_release_settings._open_starved_tasks(_starved(), queue_path=queue)
    second = audit_release_settings._open_starved_tasks(_starved(), queue_path=queue)

    assert [r["created"] for r in first] == [True, True]
    assert [r["created"] for r in second] == [False, False]
    tasks = _read_queue(queue)
    assert {t["id"] for t in tasks} == {
        "starved_draft_mile_47c4bc3e",
        "starved_draft_mile_deadbeef",
    }
    for task in tasks:
        assert task["status"] == "pending"
        assert task["priority"] == 3
        # the task must name all three exits so the gate can never dead-end
        assert "修 gate" in task["description"]
        assert "手動釋出" in task["description"]
        assert "retire" in task["description"]


def test_starved_entry_without_id_is_reported_not_silently_skipped(
    tmp_path: Path, capsys
) -> None:
    queue = tmp_path / "next_tasks.json"
    receipts = audit_release_settings._open_starved_tasks(
        [{"title": "no id", "skipped": 9}], queue_path=queue
    )
    assert receipts == [
        {"article_id": None, "created": False, "error": "missing article id"}
    ]
    assert not queue.exists() or _read_queue(queue) == []
    assert "without id" in capsys.readouterr().err
