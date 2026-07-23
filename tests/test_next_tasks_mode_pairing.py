from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops import next_tasks
from volpred.ops.task_pool_mode import TaskPoolAdmissionClosed


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_rebound_canonical_queue_uses_its_paired_mode_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    mode = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write(queue, [])
    _write(
        mode,
        {
            "enabled": True,
            "mode": "direct_execution",
            "backup_path": str(tmp_path / "backup.json"),
            "backup_sha256": "a" * 64,
            "backup_bytes": 2,
            "backup_task_count": 1,
        },
    )
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)

    with pytest.raises(TaskPoolAdmissionClosed, match="admission is closed"):
        next_tasks.append_task_record(
            {"id": "must-not-land", "status": "pending", "priority": 1},
            path=queue,
        )


def test_rebound_canonical_queue_does_not_read_live_mode_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    live_mode = tmp_path / "live" / "task_pool_mode.json"
    _write(queue, [])
    _write(
        live_mode,
        {
            "enabled": True,
            "mode": "direct_execution",
            "backup_path": str(tmp_path / "backup.json"),
            "backup_sha256": "a" * 64,
            "backup_bytes": 2,
            "backup_task_count": 1,
        },
    )
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", live_mode)
    monkeypatch.setattr(
        next_tasks,
        "_DEFAULT_TASK_POOL_MODE_PATH",
        live_mode,
    )

    record, created = next_tasks.append_task_record(
        {"id": "isolated", "status": "pending", "priority": 1},
        path=queue,
    )

    assert created is True
    assert record["id"] == "isolated"
