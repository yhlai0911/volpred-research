"""Hermetic tests for terminal-task tombstone compaction (WS2a 2026-07-14).

Runs scripts/unblock_expired_blocked_tasks.py in a throwaway cwd so the
canonical storage/next_tasks.json is never touched (per
project_canonical_write_test_leak_gate).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "unblock_expired_blocked_tasks.py"


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _fixture() -> list[dict]:
    return [
        {"id": "old_ok", "status": "succeeded", "task_type": "experiment",
         "title": "K900 old", "priority": 3, "completed_at": _iso(60),
         "description": "x" * 500, "result": "y" * 500},
        {"id": "recent_ok", "status": "succeeded", "task_type": "experiment",
         "title": "K901 recent", "priority": 3, "completed_at": _iso(1),
         "description": "keep me"},
        {"id": "pend", "status": "pending", "task_type": "daily_article",
         "title": "live", "priority": 2, "created_at": _iso(3)},
        # 27 legacy frozen rows are out-of-vocab — must never be compacted
        {"id": "legacy", "status": "completed", "task_type": "experiment",
         "title": "legacy row", "completed_at": _iso(200), "description": "frozen"},
        {"id": "no_ts", "status": "failed", "task_type": "experiment",
         "title": "failed row without any timestamp"},
        {"id": "internal_unresolved", "status": "failed", "task_type": "platform_ops",
         "title": "repair still needed", "completed_at": _iso(60),
         "internal_remediable": True, "alert_key": "git_push_backup_hold",
         "internal_alert_state": {"episode_id": "e1", "attempt_number": 1}},
        {"id": "expired_block", "status": "blocked", "task_type": "event_article",
         "title": "nfp", "priority": 1, "blocked_reason": "awaiting_external_data",
         "blocked_until": _iso(2)},
    ]


def _run(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    (tmp / "storage").mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=tmp, capture_output=True, text=True, timeout=60,
    )


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    qf = tmp_path / "storage" / "next_tasks.json"
    (tmp_path / "storage").mkdir()
    qf.write_text(json.dumps(_fixture()))
    before = qf.read_text()
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "would compact 1" in r.stdout  # only old_ok qualifies
    assert "would unblock 1" in r.stdout
    assert qf.read_text() == before
    assert not (tmp_path / "storage" / "next_tasks_archive").exists()


def test_apply_compacts_and_archives(tmp_path: Path) -> None:
    qf = tmp_path / "storage" / "next_tasks.json"
    (tmp_path / "storage").mkdir()
    qf.write_text(json.dumps(_fixture()))
    r = _run(tmp_path, "--apply")
    assert r.returncode == 0, r.stderr

    tasks = {t["id"]: t for t in json.loads(qf.read_text())}
    # old terminal → tombstone: id/dedup preserved, heavy fields gone
    assert tasks["old_ok"]["tombstone"] is True
    assert "description" not in tasks["old_ok"]
    assert "result" not in tasks["old_ok"]
    assert tasks["old_ok"]["status"] == "succeeded"
    # recent terminal / pending / legacy / no-timestamp / unresolved internal rows untouched
    assert "tombstone" not in tasks["recent_ok"]
    assert tasks["recent_ok"]["description"] == "keep me"
    assert "tombstone" not in tasks["legacy"]
    assert tasks["legacy"]["description"] == "frozen"
    assert "tombstone" not in tasks["no_ts"]
    assert "tombstone" not in tasks["internal_unresolved"]
    assert tasks["internal_unresolved"]["internal_alert_state"]["episode_id"] == "e1"
    # expired blocked flipped to pending
    assert tasks["expired_block"]["status"] == "pending"
    assert "blocked_until" not in tasks["expired_block"]

    # archive holds the FULL original record
    arch_files = list((tmp_path / "storage" / "next_tasks_archive").glob("*.jsonl"))
    assert len(arch_files) == 1
    recs = [json.loads(line) for line in arch_files[0].read_text().splitlines()]
    assert len(recs) == 1
    assert recs[0]["id"] == "old_ok"
    assert recs[0]["description"] == "x" * 500


def test_second_pass_idempotent(tmp_path: Path) -> None:
    qf = tmp_path / "storage" / "next_tasks.json"
    (tmp_path / "storage").mkdir()
    qf.write_text(json.dumps(_fixture()))
    _run(tmp_path, "--apply")
    arch = next((tmp_path / "storage" / "next_tasks_archive").glob("*.jsonl"))
    n_lines_1 = len(arch.read_text().splitlines())
    r2 = _run(tmp_path, "--apply")
    assert r2.returncode == 0, r2.stderr
    n_lines_2 = len(arch.read_text().splitlines())
    assert n_lines_1 == n_lines_2 == 1  # tombstone 不會重複歸檔
