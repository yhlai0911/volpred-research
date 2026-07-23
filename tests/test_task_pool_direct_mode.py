from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from volpred.ops import next_tasks
from volpred.ops.task_pool_mode import (
    TaskPoolAdmissionClosed,
    enter_direct_execution_mode,
    load_task_pool_mode,
    load_task_pool_mode_evidence,
    reconcile_direct_execution_pool,
    restore_task_pool_backup,
)


def _write_pool(path: Path, rows: list[dict[str, object]]) -> bytes:
    payload = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def test_mode_evidence_parses_and_hashes_one_identical_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    state.parent.mkdir(parents=True)
    queued_bytes = json.dumps(
        {"enabled": False, "mode": "queued_execution"}
    ).encode()
    direct_bytes = json.dumps(
        {"enabled": True, "mode": "direct_execution"}
    ).encode()
    state.write_bytes(queued_bytes)
    original_read_bytes = Path.read_bytes
    reads = 0

    def racing_read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path != state:
            return original_read_bytes(path)
        reads += 1
        return queued_bytes if reads == 1 else direct_bytes

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)

    evidence = load_task_pool_mode_evidence(state)

    assert reads == 1
    assert evidence.mode.mode == "queued_execution"
    assert evidence.mode.enabled is False
    assert evidence.sha256 == hashlib.sha256(queued_bytes).hexdigest()
    assert evidence.byte_count == len(queued_bytes)


def test_enter_direct_mode_backs_up_exact_bytes_then_clears_atomically(tmp_path: Path) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup_dir = tmp_path / "storage" / "backups" / "task_pool"
    original = _write_pool(
        queue,
        [
            {"id": "old-pending", "status": "pending", "priority": 3},
            {"id": "control-task", "status": "in_progress", "priority": 3},
        ],
    )

    receipt = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=backup_dir,
        activated_by="test",
        reason="owner requested direct execution",
        preserve_task_ids=("control-task",),
        now="2026-07-23T12:00:00+00:00",
    )

    backup = Path(receipt.backup_path)
    assert backup.read_bytes() == original
    assert receipt.backup_sha256 == hashlib.sha256(original).hexdigest()
    assert receipt.backup_bytes == len(original)
    assert receipt.backup_task_count == 2
    assert json.loads(queue.read_text()) == [
        {"id": "control-task", "status": "in_progress", "priority": 3}
    ]
    mode = load_task_pool_mode(state)
    assert mode.enabled is True
    assert mode.mode == "direct_execution"
    assert mode.preserve_task_ids == ("control-task",)
    assert mode.backup_sha256 == receipt.backup_sha256


def test_direct_mode_rejects_new_ids_at_canonical_write_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write_pool(
        queue, [{"id": "control-task", "status": "in_progress", "priority": 3}]
    )
    enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="test",
        reason="test",
        preserve_task_ids=("control-task",),
        now="2026-07-23T12:00:00+00:00",
    )
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)

    with pytest.raises(TaskPoolAdmissionClosed, match="new-task"):
        next_tasks.append_task_record(
            {"id": "new-task", "status": "pending", "priority": 2},
            path=queue,
            semantic_dedupe=False,
        )

    assert json.loads(queue.read_text()) == [
        {"id": "control-task", "status": "in_progress", "priority": 3}
    ]


def test_direct_mode_allows_existing_task_lifecycle_and_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write_pool(
        queue, [{"id": "control-task", "status": "in_progress", "priority": 3}]
    )
    enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="test",
        reason="test",
        preserve_task_ids=("control-task",),
        now="2026-07-23T12:00:00+00:00",
    )
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)

    with queue.open("r+", encoding="utf-8") as handle:
        next_tasks.write_tasks_to_handle(
            handle,
            [{"id": "control-task", "status": "succeeded", "priority": 3}],
        )
    with queue.open("r+", encoding="utf-8") as handle:
        next_tasks.write_tasks_to_handle(handle, [])

    assert json.loads(queue.read_text()) == []


def test_reconcile_direct_mode_removes_only_ids_outside_the_receipt(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    control = {"id": "control-task", "status": "in_progress", "priority": 3}
    _write_pool(queue, [control])
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="test",
        reason="test",
        preserve_task_ids=("control-task",),
        now="2026-07-23T12:00:00+00:00",
    )
    # Model a pre-cutover process that retained the old append function in
    # memory and wrote after the admission guard was activated.
    _write_pool(
        queue,
        [
            control,
            {"id": "leaked-task", "status": "pending", "priority": 2},
        ],
    )

    receipt = reconcile_direct_execution_pool(
        queue_path=queue,
        state_path=state,
        reconciled_by="test",
        reason="remove stale-writer leak",
        now="2026-07-23T12:05:00+00:00",
    )

    assert receipt.removed_task_ids == ("leaked-task",)
    assert receipt.retained_task_ids == ("control-task",)
    assert json.loads(queue.read_text()) == [control]
    mode = load_task_pool_mode(state)
    assert mode.enabled is True
    assert mode.backup_path == entered.backup_path
    assert mode.backup_sha256 == entered.backup_sha256


def test_malformed_direct_mode_state_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write_pool(queue, [])
    state.parent.mkdir(parents=True)
    state.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)

    with pytest.raises(TaskPoolAdmissionClosed, match="unreadable"):
        next_tasks.append_task_record(
            {"id": "new-task", "status": "pending", "priority": 2},
            path=queue,
            semantic_dedupe=False,
        )

    assert json.loads(queue.read_text()) == []


def test_invalid_pool_does_not_activate_mode_or_create_backup(tmp_path: Path) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup_dir = tmp_path / "backups"
    queue.parent.mkdir(parents=True)
    queue.write_text("{not-a-list}", encoding="utf-8")

    with pytest.raises(ValueError, match="unreadable"):
        enter_direct_execution_mode(
            queue_path=queue,
            state_path=state,
            backup_dir=backup_dir,
            activated_by="test",
            reason="test",
            now="2026-07-23T12:00:00+00:00",
        )

    assert not state.exists()
    assert not list(backup_dir.glob("*"))


def test_verified_backup_is_a_working_restore_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    _write_pool(queue, original_rows)
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="test",
        reason="test",
        now="2026-07-23T12:00:00+00:00",
    )

    restored = restore_task_pool_backup(
        queue_path=queue,
        state_path=state,
        backup_path=entered.backup_path,
        restored_by="test",
        reason="rollback rehearsal",
        now="2026-07-23T12:05:00+00:00",
    )

    assert restored.restored_task_count == 1
    assert json.loads(queue.read_text()) == original_rows
    assert load_task_pool_mode(state).enabled is False
