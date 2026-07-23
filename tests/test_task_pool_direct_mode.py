from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from volpred.ops import next_tasks
from volpred.ops.task_pool_mode import (
    TaskPoolAdmissionClosed,
    TaskPoolModeConflict,
    enter_direct_execution_mode,
    load_task_pool_mode,
    load_task_pool_mode_evidence,
    reconcile_direct_execution_pool,
    restore_task_pool_backup,
)


CONTROL_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "task_pool_control.py"
)
CONTROL_SPEC = importlib.util.spec_from_file_location(
    "task_pool_control",
    CONTROL_MODULE_PATH,
)
task_pool_control = importlib.util.module_from_spec(CONTROL_SPEC)
assert CONTROL_SPEC and CONTROL_SPEC.loader
CONTROL_SPEC.loader.exec_module(task_pool_control)


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
        expected_state_sha256=None,
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
        expected_state_sha256=None,
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
        expected_state_sha256=None,
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
        expected_state_sha256=None,
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
        expected_state_sha256=load_task_pool_mode_evidence(state).sha256,
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
            expected_state_sha256=None,
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
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )

    restored = restore_task_pool_backup(
        queue_path=queue,
        state_path=state,
        backup_path=entered.backup_path,
        restored_by="test",
        reason="rollback rehearsal",
        expected_state_sha256=load_task_pool_mode_evidence(state).sha256,
        now="2026-07-23T12:05:00+00:00",
    )

    assert restored.restored_task_count == 1
    assert json.loads(queue.read_text()) == original_rows
    assert load_task_pool_mode(state).enabled is False


def test_restore_rejects_a_stale_owner_state_without_touching_the_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        preserve_task_ids=(),
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    stale_sha256 = load_task_pool_mode_evidence(state).sha256
    concurrent_state = json.loads(state.read_text())
    concurrent_state["reason"] = "newer owner transition"
    state.write_text(
        json.dumps(concurrent_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    concurrent_bytes = state.read_bytes()

    with pytest.raises(TaskPoolModeConflict, match="compare-and-set"):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="stale-worker",
            reason="stale rollback",
            expected_state_sha256=stale_sha256,
            now="2026-07-23T12:05:00+00:00",
        )

    assert json.loads(queue.read_text()) == []
    assert state.read_bytes() == concurrent_bytes


def test_stale_restore_does_not_create_a_missing_queue_before_cas(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup = tmp_path / "backups" / "next_tasks.json"
    backup.parent.mkdir(parents=True)
    backup_bytes = (
        json.dumps(
            [{"id": "old-pending", "status": "pending", "priority": 2}],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode()
    backup.write_bytes(backup_bytes)
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema": 1,
                "enabled": True,
                "mode": "direct_execution",
                "backup_path": str(backup.resolve()),
                "backup_sha256": hashlib.sha256(backup_bytes).hexdigest(),
                "preserve_task_ids": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stale_sha256 = load_task_pool_mode_evidence(state).sha256
    concurrent_state = json.loads(state.read_text())
    concurrent_state["reason"] = "newer owner transition"
    state.write_text(
        json.dumps(concurrent_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TaskPoolModeConflict, match="compare-and-set"):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=backup,
            restored_by="stale-worker",
            reason="stale rollback",
            expected_state_sha256=stale_sha256,
            now="2026-07-23T12:05:00+00:00",
        )

    assert not queue.exists()


def test_reconcile_rejects_a_stale_owner_state_without_removing_rows(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    control = {"id": "control-task", "status": "in_progress", "priority": 3}
    leaked = {"id": "leaked-task", "status": "pending", "priority": 2}
    _write_pool(queue, [control])
    enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="test",
        reason="test",
        preserve_task_ids=("control-task",),
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    stale_sha256 = load_task_pool_mode_evidence(state).sha256
    _write_pool(queue, [control, leaked])
    concurrent_state = json.loads(state.read_text())
    concurrent_state["reason"] = "newer owner transition"
    state.write_text(
        json.dumps(concurrent_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    concurrent_bytes = state.read_bytes()

    with pytest.raises(TaskPoolModeConflict, match="compare-and-set"):
        reconcile_direct_execution_pool(
            queue_path=queue,
            state_path=state,
            reconciled_by="stale-worker",
            reason="remove stale-writer leak",
            expected_state_sha256=stale_sha256,
            now="2026-07-23T12:05:00+00:00",
        )

    assert json.loads(queue.read_text()) == [control, leaked]
    assert state.read_bytes() == concurrent_bytes


def test_enter_direct_rejects_a_stale_owner_state_before_backup_or_clear(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup_dir = tmp_path / "backups"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    original_bytes = _write_pool(queue, original_rows)
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"schema": 1, "enabled": False, "mode": "queued_execution"})
        + "\n",
        encoding="utf-8",
    )
    stale_sha256 = load_task_pool_mode_evidence(state).sha256
    state.write_text(
        json.dumps(
            {
                "schema": 1,
                "enabled": False,
                "mode": "queued_execution",
                "reason": "newer owner transition",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    concurrent_bytes = state.read_bytes()

    with pytest.raises(TaskPoolModeConflict, match="compare-and-set"):
        enter_direct_execution_mode(
            queue_path=queue,
            state_path=state,
            backup_dir=backup_dir,
            activated_by="stale-worker",
            reason="stale cutover",
            preserve_task_ids=(),
            expected_state_sha256=stale_sha256,
            now="2026-07-23T12:00:00+00:00",
        )

    assert queue.read_bytes() == original_bytes
    assert state.read_bytes() == concurrent_bytes
    assert not backup_dir.exists()


def test_stale_enter_does_not_create_a_missing_queue_before_cas(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"schema": 1, "enabled": False, "mode": "queued_execution"})
        + "\n",
        encoding="utf-8",
    )
    stale_sha256 = load_task_pool_mode_evidence(state).sha256
    state.write_text(
        json.dumps(
            {
                "schema": 1,
                "enabled": False,
                "mode": "queued_execution",
                "reason": "newer owner transition",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TaskPoolModeConflict, match="compare-and-set"):
        enter_direct_execution_mode(
            queue_path=queue,
            state_path=state,
            backup_dir=tmp_path / "backups",
            activated_by="stale-worker",
            reason="stale cutover",
            expected_state_sha256=stale_sha256,
            now="2026-07-23T12:00:00+00:00",
        )

    assert not queue.exists()


def test_enter_direct_rejects_reentry_without_replacing_the_restore_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backups = tmp_path / "backups"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    _write_pool(queue, original_rows)
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=backups,
        activated_by="first-owner",
        reason="first cutover",
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    active_bytes = state.read_bytes()
    active_sha256 = load_task_pool_mode_evidence(state).sha256
    backup_inventory = {
        path.name: path.read_bytes() for path in backups.iterdir()
    }

    with pytest.raises(ValueError, match="already in direct-execution mode"):
        enter_direct_execution_mode(
            queue_path=queue,
            state_path=state,
            backup_dir=backups,
            activated_by="second-owner",
            reason="replace receipt",
            expected_state_sha256=active_sha256,
            now="2026-07-23T12:05:00+00:00",
        )

    assert json.loads(queue.read_text()) == []
    assert state.read_bytes() == active_bytes
    assert {
        path.name: path.read_bytes() for path in backups.iterdir()
    } == backup_inventory

    restored = restore_task_pool_backup(
        queue_path=queue,
        state_path=state,
        backup_path=entered.backup_path,
        restored_by="rollback-owner",
        reason="verify original receipt",
        expected_state_sha256=active_sha256,
        now="2026-07-23T12:10:00+00:00",
    )
    assert restored.restored_task_count == 1
    assert json.loads(queue.read_text()) == original_rows


def test_status_returns_the_owner_state_cas_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    queue.parent.mkdir(parents=True)
    queue.write_text("[]\n", encoding="utf-8")
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    state.parent.mkdir(parents=True)
    state_bytes = (
        json.dumps(
            {
                "schema": 1,
                "enabled": True,
                "mode": "direct_execution",
                "preserve_task_ids": [],
            },
            indent=2,
        )
        + "\n"
    ).encode()
    state.write_bytes(state_bytes)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_control.py",
            "status",
            "--queue",
            str(queue),
            "--state",
            str(state),
        ],
    )

    assert task_pool_control.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["state_sha256"] == hashlib.sha256(state_bytes).hexdigest()
    assert payload["state_bytes"] == len(state_bytes)
    assert payload["mode"]["mode"] == "direct_execution"
