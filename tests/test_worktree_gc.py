"""Tests for scripts/worktree_gc.py — the mechanical worktree reclamation gate.

The point of these tests is NOT that the happy path passes; it is that every
"I could not determine this" path BLOCKS. A GC gate that fails open deletes an
agent's only copy of its work (docs/error_log.md 2026-07-19, k1709).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "worktree_gc", ROOT / "scripts" / "worktree_gc.py"
)
worktree_gc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worktree_gc)

PASS = worktree_gc.PASS
BLOCK = worktree_gc.BLOCK


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ── gate 1: no process ──────────────────────────────────────────────────────


def test_gate1_passes_when_no_handles(tmp_path, monkeypatch):
    monkeypatch.setattr(
        worktree_gc.subprocess, "run", lambda *a, **k: _Proc(stdout="", returncode=1)
    )
    gate = worktree_gc.gate_no_process(tmp_path)
    assert gate["status"] == PASS
    assert gate["holder_pids"] == []


def test_gate1_blocks_when_a_process_holds_the_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        worktree_gc.subprocess, "run", lambda *a, **k: _Proc(stdout="23534\n23535\n")
    )
    gate = worktree_gc.gate_no_process(tmp_path)
    assert gate["status"] == BLOCK
    assert gate["holder_pids"] == [23534, 23535]


def test_gate1_lsof_timeout_is_fail_closed(tmp_path, monkeypatch):
    """lsof is slowest exactly when the tree is busy — timeout must never pass."""

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="lsof", timeout=25)

    monkeypatch.setattr(worktree_gc.subprocess, "run", _boom)
    gate = worktree_gc.gate_no_process(tmp_path)
    assert gate["status"] == BLOCK
    assert "逾時" in gate["reason"]
    assert gate["holder_pids"] is None


def test_gate1_lsof_missing_binary_is_fail_closed(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("lsof not found")

    monkeypatch.setattr(worktree_gc.subprocess, "run", _boom)
    assert worktree_gc.gate_no_process(tmp_path)["status"] == BLOCK


def test_gate1_unexpected_exit_code_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        worktree_gc.subprocess, "run",
        lambda *a, **k: _Proc(stdout="", stderr="permission denied", returncode=9),
    )
    assert worktree_gc.gate_no_process(tmp_path)["status"] == BLOCK


def test_gate1_missing_path_is_fail_closed(tmp_path):
    assert worktree_gc.gate_no_process(tmp_path / "nope")["status"] == BLOCK


# ── gate 2: no unmerged commits ─────────────────────────────────────────────


def test_gate2_passes_when_fully_merged(monkeypatch):
    monkeypatch.setattr(
        worktree_gc.subprocess, "run", lambda *a, **k: _Proc(stdout="0\n")
    )
    gate = worktree_gc.gate_no_unmerged("wt/foo")
    assert gate["status"] == PASS
    assert gate["unmerged_commits"] == 0


def test_gate2_blocks_on_unmerged_commits(monkeypatch):
    monkeypatch.setattr(
        worktree_gc.subprocess, "run", lambda *a, **k: _Proc(stdout="4\n")
    )
    gate = worktree_gc.gate_no_unmerged("wt/foo")
    assert gate["status"] == BLOCK
    assert gate["unmerged_commits"] == 4


def test_gate2_git_failure_is_fail_closed(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.CalledProcessError(128, "git", stderr="bad revision")

    monkeypatch.setattr(worktree_gc.subprocess, "run", _boom)
    gate = worktree_gc.gate_no_unmerged("wt/foo")
    assert gate["status"] == BLOCK
    assert gate["unmerged_commits"] is None


def test_gate2_git_timeout_is_fail_closed(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=30)

    monkeypatch.setattr(worktree_gc.subprocess, "run", _boom)
    assert worktree_gc.gate_no_unmerged("wt/foo")["status"] == BLOCK


def test_gate2_unparseable_output_is_fail_closed(monkeypatch):
    monkeypatch.setattr(
        worktree_gc.subprocess, "run", lambda *a, **k: _Proc(stdout="fatal: whoops\n")
    )
    assert worktree_gc.gate_no_unmerged("wt/foo")["status"] == BLOCK


def test_gate2_detached_head_is_fail_closed():
    """No branch means no way to prove the commits landed."""
    assert worktree_gc.gate_no_unmerged(None)["status"] == BLOCK


# ── gate 3: no open receipt ─────────────────────────────────────────────────


def _queue(tmp_path: Path, tasks: list[dict]) -> Path:
    path = tmp_path / "next_tasks.json"
    path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    return path


def test_gate3_passes_when_no_task_mentions_the_worktree(tmp_path):
    path = _queue(tmp_path, [
        {"id": "t1", "status": "pending", "title": "unrelated", "description": ""},
        {"id": "t2", "status": "succeeded", "title": "wt-alpha done", "description": ""},
    ])
    gate = worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)
    assert gate["status"] == PASS
    assert gate["open_tasks"] == []


@pytest.mark.parametrize("status", ["pending", "claimed", "in_progress"])
def test_gate3_blocks_on_each_open_status(tmp_path, status):
    path = _queue(tmp_path, [
        {"id": "t1", "status": status, "title": "collect wt-alpha", "description": ""},
    ])
    gate = worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)
    assert gate["status"] == BLOCK
    assert [h["id"] for h in gate["open_tasks"]] == ["t1"]


def test_gate3_matches_description_not_only_title(tmp_path):
    path = _queue(tmp_path, [
        {"id": "t1", "status": "pending", "title": "collect",
         "description": "merge .claude/worktrees/wt-alpha then remove"},
    ])
    assert worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)["status"] == BLOCK


def test_gate3_terminal_statuses_do_not_block(tmp_path):
    path = _queue(tmp_path, [
        {"id": "t1", "status": "succeeded", "title": "wt-alpha", "description": ""},
        {"id": "t2", "status": "failed", "title": "wt-alpha", "description": ""},
        {"id": "t3", "status": "cancelled", "title": "wt-alpha", "description": ""},
    ])
    assert worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)["status"] == PASS


def test_gate3_exclude_task_id_is_honored(tmp_path):
    """The task ordering the cleanup names its own targets — else it deadlocks."""
    path = _queue(tmp_path, [
        {"id": "assign_self", "status": "in_progress",
         "title": "reclaim wt-alpha", "description": ""},
    ])
    assert worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)["status"] == BLOCK
    gate = worktree_gc.gate_no_open_task(
        "wt-alpha", tasks_path=path, exclude_task_ids={"assign_self"}
    )
    assert gate["status"] == PASS


def test_gate3_missing_queue_file_is_fail_closed(tmp_path):
    gate = worktree_gc.gate_no_open_task("wt-alpha", tasks_path=tmp_path / "absent.json")
    assert gate["status"] == BLOCK
    assert gate["open_tasks"] is None


def test_gate3_malformed_queue_is_fail_closed(tmp_path):
    path = tmp_path / "next_tasks.json"
    path.write_text("{not json", encoding="utf-8")
    gate = worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)
    assert gate["status"] == BLOCK
    assert gate["open_tasks"] is None


def test_gate3_wrong_shape_queue_is_fail_closed(tmp_path):
    path = tmp_path / "next_tasks.json"
    path.write_text(json.dumps({"tasks": "not-a-list"}), encoding="utf-8")
    assert worktree_gc.gate_no_open_task("wt-alpha", tasks_path=path)["status"] == BLOCK


# ── evaluate(): conjunction + queue-level fail-closed ────────────────────────


def _stub_gates(monkeypatch, *, g1, g2):
    monkeypatch.setattr(
        worktree_gc, "gate_no_process",
        lambda path, **k: worktree_gc._gate(g1, "stub", holder_pids=[]),
    )
    monkeypatch.setattr(
        worktree_gc, "gate_no_unmerged",
        lambda branch, **k: worktree_gc._gate(g2, "stub", unmerged_commits=0),
    )


def _one_wt(tmp_path):
    wt = tmp_path / "wt-alpha"
    wt.mkdir(exist_ok=True)
    return [{"name": "wt-alpha", "path": wt, "branch": "wt/alpha"}]


def test_evaluate_requires_all_three_gates(tmp_path, monkeypatch):
    path = _queue(tmp_path, [])
    _stub_gates(monkeypatch, g1=PASS, g2=PASS)
    rows = worktree_gc.evaluate(tasks_path=path, worktrees=_one_wt(tmp_path))
    assert rows[0]["reclaimable"] is True

    _stub_gates(monkeypatch, g1=PASS, g2=BLOCK)
    rows = worktree_gc.evaluate(tasks_path=path, worktrees=_one_wt(tmp_path))
    assert rows[0]["reclaimable"] is False
    assert rows[0]["blocked_by"] == ["gate2_no_unmerged"]


def test_evaluate_blocks_everything_when_queue_unreadable(tmp_path, monkeypatch):
    """One unreadable queue must not silently clear gate3 for every worktree."""
    _stub_gates(monkeypatch, g1=PASS, g2=PASS)
    rows = worktree_gc.evaluate(
        tasks_path=tmp_path / "absent.json", worktrees=_one_wt(tmp_path)
    )
    assert rows[0]["reclaimable"] is False
    assert rows[0]["blocked_by"] == ["gate3_no_open_task"]
    assert rows[0]["gates"]["gate3_no_open_task"]["open_tasks"] is None


def test_run_dry_run_never_reclaims(tmp_path, monkeypatch):
    path = _queue(tmp_path, [])
    _stub_gates(monkeypatch, g1=PASS, g2=PASS)
    monkeypatch.setattr(worktree_gc, "discover_worktrees", lambda: _one_wt(tmp_path))

    def _explode(row):
        raise AssertionError("dry-run must never call _reclaim_one")

    monkeypatch.setattr(worktree_gc, "_reclaim_one", _explode)
    report = worktree_gc.run(apply=False, tasks_path=path)
    assert report["reclaimable_count"] == 1
    assert report["worktrees"][0]["action"] == "would_reclaim"


def test_apply_rechecks_gates_before_removing(tmp_path, monkeypatch):
    """A process can attach between the dry-run and --apply; recheck must win."""
    path = _queue(tmp_path, [])
    monkeypatch.setattr(worktree_gc, "discover_worktrees", lambda: _one_wt(tmp_path))
    monkeypatch.setattr(
        worktree_gc, "gate_no_unmerged",
        lambda branch, **k: worktree_gc._gate(PASS, "stub", unmerged_commits=0),
    )
    calls = {"n": 0}

    def _flaky_gate1(p, **k):
        calls["n"] += 1
        status = PASS if calls["n"] == 1 else BLOCK  # attaches after first look
        return worktree_gc._gate(status, "stub", holder_pids=[])

    monkeypatch.setattr(worktree_gc, "gate_no_process", _flaky_gate1)

    def _explode(row):
        raise AssertionError("must not reclaim after recheck blocked")

    monkeypatch.setattr(worktree_gc, "_reclaim_one", _explode)
    report = worktree_gc.run(apply=True, tasks_path=path)
    assert report["worktrees"][0]["action"] == "skip"
    assert report["worktrees"][0]["recheck_blocked_by"] == ["gate1_no_process"]


def test_reclaim_never_uses_force():
    """CLAUDE.md hard rule; the L1 hook also blocks it. Pin it in source."""
    src = (ROOT / "scripts" / "worktree_gc.py").read_text(encoding="utf-8")
    # Prose may discuss the ban; no string literal may ever pass it to git.
    assert '"--force"' not in src
    assert "'--force'" not in src
