from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from volpred.ops import next_tasks, task_pool_mode
from volpred.ops.task_pool_mode import (
    TaskPoolAdmissionClosed,
    TaskPoolModeConflict,
    enter_direct_execution_mode,
    load_task_pool_mode,
    load_task_pool_mode_evidence,
    reconcile_direct_execution_pool,
    restore_task_pool_backup,
    task_pool_mode_path,
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


def test_atomic_owner_state_replace_fsyncs_the_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    state.parent.mkdir(parents=True)
    original_open = task_pool_mode.os.open
    original_close = task_pool_mode.os.close
    original_fsync = task_pool_mode.os.fsync
    original_replace = task_pool_mode.os.replace
    directory_fds: set[int] = set()
    events: list[str] = []

    def tracked_open(path: str | bytes | Path, flags: int, *args: object) -> int:
        descriptor = original_open(path, flags, *args)
        if Path(path).resolve() == state.parent.resolve():
            directory_fds.add(descriptor)
        return descriptor

    def tracked_fsync(descriptor: int) -> None:
        events.append(
            "directory_fsync"
            if descriptor in directory_fds
            else "file_fsync"
        )
        original_fsync(descriptor)

    def tracked_close(descriptor: int) -> None:
        directory_fds.discard(descriptor)
        original_close(descriptor)

    def tracked_replace(source: str | Path, target: str | Path) -> None:
        events.append("replace")
        original_replace(source, target)

    monkeypatch.setattr(task_pool_mode.os, "open", tracked_open)
    monkeypatch.setattr(task_pool_mode.os, "close", tracked_close)
    monkeypatch.setattr(task_pool_mode.os, "fsync", tracked_fsync)
    monkeypatch.setattr(task_pool_mode.os, "replace", tracked_replace)

    task_pool_mode._atomic_write_json(
        state,
        {"schema": 1, "enabled": True, "mode": "direct_execution"},
    )

    assert events[-2:] == ["replace", "directory_fsync"]


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


def test_enter_direct_rejects_a_detached_state_path_before_side_effects(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    detached_state = tmp_path / "detached" / "task_pool_mode.json"
    backup_dir = tmp_path / "backups"
    original_bytes = _write_pool(
        queue,
        [{"id": "old-pending", "status": "pending", "priority": 3}],
    )

    with pytest.raises(
        ValueError,
        match="state path does not match the queue-paired owner state",
    ):
        enter_direct_execution_mode(
            queue_path=queue,
            state_path=detached_state,
            backup_dir=backup_dir,
            activated_by="test",
            reason="detached state typo",
            expected_state_sha256=None,
            now="2026-07-23T12:00:00+00:00",
        )

    assert queue.read_bytes() == original_bytes
    assert not detached_state.exists()
    assert not backup_dir.exists()


def test_symlinked_queue_identity_still_pairs_with_the_real_owner_state(
    tmp_path: Path,
) -> None:
    real_queue = tmp_path / "storage" / "next_tasks.json"
    original_bytes = _write_pool(
        real_queue,
        [{"id": "old-pending", "status": "pending", "priority": 3}],
    )
    alias_queue = tmp_path / "alias" / "next_tasks.json"
    alias_queue.parent.mkdir()
    alias_queue.symlink_to(real_queue)
    detached_alias_state = alias_queue.parent / "ops" / "task_pool_mode.json"
    canonical_state = real_queue.parent / "ops" / "task_pool_mode.json"
    backup_dir = tmp_path / "backups"

    assert task_pool_mode_path(alias_queue).resolve() == canonical_state.resolve()
    with pytest.raises(
        ValueError,
        match="state path does not match the queue-paired owner state",
    ):
        enter_direct_execution_mode(
            queue_path=alias_queue,
            state_path=detached_alias_state,
            backup_dir=backup_dir,
            activated_by="test",
            reason="symlink alias state",
            expected_state_sha256=None,
            now="2026-07-23T12:00:00+00:00",
        )

    assert real_queue.read_bytes() == original_bytes
    assert not detached_alias_state.exists()
    assert not canonical_state.exists()
    assert not backup_dir.exists()


def test_enter_direct_rejects_a_sibling_queue_filename_typo(
    tmp_path: Path,
) -> None:
    canonical_queue = tmp_path / "storage" / "next_tasks.json"
    typo_queue = tmp_path / "storage" / "next_task.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup_dir = tmp_path / "backups"
    canonical_bytes = _write_pool(
        canonical_queue,
        [{"id": "canonical", "status": "pending", "priority": 1}],
    )
    typo_bytes = _write_pool(
        typo_queue,
        [{"id": "typo", "status": "pending", "priority": 1}],
    )

    with pytest.raises(
        ValueError,
        match="managed task-pool queue must resolve to next_tasks.json",
    ):
        enter_direct_execution_mode(
            queue_path=typo_queue,
            state_path=state,
            backup_dir=backup_dir,
            activated_by="test",
            reason="filename typo",
            expected_state_sha256=None,
            now="2026-07-23T12:00:00+00:00",
        )

    assert canonical_queue.read_bytes() == canonical_bytes
    assert typo_queue.read_bytes() == typo_bytes
    assert not state.exists()
    assert not backup_dir.exists()


def test_direct_mode_rejects_new_ids_at_canonical_write_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write_pool(
        queue,
        [
            {
                "id": "control-task",
                "status": "in_progress",
                "priority": 3,
            }
        ],
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


def test_direct_mode_allows_idempotent_replay_before_source_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    control = {
        "id": "control-task",
        "status": "in_progress",
        "priority": 3,
    }
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
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)

    existing, created = next_tasks.append_task_record(
        dict(control),
        path=queue,
        semantic_dedupe=False,
    )

    assert created is False
    assert existing == control
    assert json.loads(queue.read_text()) == [control]


def test_direct_mode_allows_existing_task_lifecycle_and_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write_pool(
        queue,
        [
            {
                "id": "control-task",
                "status": "in_progress",
                "priority": 3,
                "issue_ref": "#37",
            }
        ],
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
            [
                {
                    "id": "control-task",
                    "status": "succeeded",
                    "priority": 3,
                    "issue_ref": "#37",
                    "issue_closed_commit": "a" * 40,
                }
            ],
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
    original_bytes = _write_pool(queue, original_rows)
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
    assert queue.read_bytes() == original_bytes
    assert load_task_pool_mode(state).enabled is False


def test_restore_archives_receipt_bound_control_rows_before_overwrite(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_rows = [
        {"id": "old-pending", "status": "pending", "priority": 2},
        {"id": "control-task", "status": "pending", "priority": 1},
    ]
    original_bytes = _write_pool(queue, original_rows)
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        preserve_task_ids=("control-task",),
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    control_bytes = _write_pool(
        queue,
        [
            {
                "id": "control-task",
                "status": "pending",
                "priority": 1,
                "latest_checkpoint": "two-Mac host still offline",
            }
        ],
    )

    receipt = restore_task_pool_backup(
        queue_path=queue,
        state_path=state,
        backup_path=entered.backup_path,
        restored_by="rollback-owner",
        reason="resume queued content",
        expected_state_sha256=load_task_pool_mode_evidence(state).sha256,
        now="2026-07-23T12:05:00+00:00",
    )

    assert queue.read_bytes() == original_bytes
    assert receipt.archived_preserved_task_count == 1
    assert receipt.archived_preserved_rows_path is not None
    archive = Path(receipt.archived_preserved_rows_path)
    assert archive.read_bytes() == control_bytes
    assert receipt.archived_preserved_rows_sha256 == hashlib.sha256(
        control_bytes
    ).hexdigest()
    assert receipt.archived_preserved_rows_bytes == len(control_bytes)
    mode_payload = json.loads(state.read_text())
    assert mode_payload["restored_preserved_rows_path"] == str(archive.resolve())
    assert mode_payload["restored_preserved_rows_sha256"] == hashlib.sha256(
        control_bytes
    ).hexdigest()
    assert mode_payload["restored_preserved_rows_bytes"] == len(control_bytes)
    assert mode_payload["restored_preserved_task_count"] == 1


def test_restore_resume_rejects_a_tampered_preserved_row_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    _write_pool(
        queue,
        [{"id": "control-task", "status": "pending", "priority": 1}],
    )
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        preserve_task_ids=("control-task",),
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    control_bytes = _write_pool(
        queue,
        [
            {
                "id": "control-task",
                "status": "pending",
                "latest_checkpoint": "ready to restore",
            }
        ],
    )
    original_atomic_write = task_pool_mode._atomic_write_json

    def crash_after_prepare(path: Path, payload: dict[str, object]) -> None:
        original_atomic_write(path, payload)
        if payload.get("mode") == "restore_in_progress":
            raise RuntimeError("simulated process death after prepare")

    monkeypatch.setattr(
        task_pool_mode,
        "_atomic_write_json",
        crash_after_prepare,
    )
    with pytest.raises(RuntimeError, match="simulated process death"):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="rollback-owner",
            reason="resume queued content",
            expected_state_sha256=load_task_pool_mode_evidence(state).sha256,
            now="2026-07-23T12:05:00+00:00",
        )
    monkeypatch.setattr(
        task_pool_mode,
        "_atomic_write_json",
        original_atomic_write,
    )
    prepared_payload = json.loads(state.read_text())
    archive = Path(prepared_payload["restore_preserved_rows_path"])
    archive.write_bytes(b"[]\n")
    prepared_bytes = state.read_bytes()

    with pytest.raises(
        ValueError,
        match="preserved-row archive does not match the restore transaction",
    ):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="retry-worker",
            reason="resume prepared restore",
            expected_state_sha256=hashlib.sha256(prepared_bytes).hexdigest(),
            now="2026-07-23T12:10:00+00:00",
        )

    assert queue.read_bytes() == control_bytes
    assert state.read_bytes() == prepared_bytes


def test_restore_rejects_rows_outside_the_direct_mode_preserve_receipt(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_bytes = _write_pool(
        queue,
        [{"id": "control-task", "status": "pending", "priority": 1}],
    )
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        preserve_task_ids=("control-task",),
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    drift_bytes = _write_pool(
        queue,
        [
            {"id": "control-task", "status": "pending", "priority": 1},
            {"id": "writer-leak", "status": "pending", "priority": 2},
        ],
    )
    state_bytes = state.read_bytes()

    with pytest.raises(
        ValueError,
        match="outside the active direct-mode preserve receipt: writer-leak",
    ):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="rollback-owner",
            reason="resume queued content",
            expected_state_sha256=load_task_pool_mode_evidence(state).sha256,
            now="2026-07-23T12:05:00+00:00",
        )

    assert queue.read_bytes() == drift_bytes
    assert state.read_bytes() == state_bytes
    assert Path(entered.backup_path).read_bytes() == original_bytes
    assert list((tmp_path / "backups").glob("*_preserved_rows_*.json")) == []


def test_restore_requires_exact_acknowledgement_of_active_backup_tasks(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_bytes = _write_pool(
        queue,
        [
            {
                "id": "stale-claim",
                "status": "claimed",
                "claimed_by": "offline-worker",
            },
            {
                "id": "stale-run",
                "status": "in_progress",
                "claimed_by": "offline-worker",
            },
        ],
    )
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    active_state_sha = load_task_pool_mode_evidence(state).sha256
    state_bytes = state.read_bytes()

    with pytest.raises(
        ValueError,
        match=(
            "active backup task acknowledgement mismatch: "
            "expected none; observed stale-claim, stale-run"
        ),
    ):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="rollback-owner",
            reason="resume queued content",
            expected_state_sha256=active_state_sha,
            now="2026-07-23T12:05:00+00:00",
        )

    assert json.loads(queue.read_text()) == []
    assert state.read_bytes() == state_bytes

    receipt = restore_task_pool_backup(
        queue_path=queue,
        state_path=state,
        backup_path=entered.backup_path,
        restored_by="rollback-owner",
        reason="resume queued content",
        expected_state_sha256=active_state_sha,
        expected_active_task_ids=("stale-run", "stale-claim"),
        now="2026-07-23T12:05:00+00:00",
    )

    assert queue.read_bytes() == original_bytes
    assert receipt.acknowledged_active_task_ids == ("stale-claim", "stale-run")
    mode_payload = json.loads(state.read_text())
    assert mode_payload["restored_acknowledged_active_task_ids"] == [
        "stale-claim",
        "stale-run",
    ]


def test_restore_cli_accepts_exact_active_backup_task_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_bytes = _write_pool(
        queue,
        [{"id": "stale-run", "status": "in_progress"}],
    )
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_control.py",
            "restore",
            "--queue",
            str(queue),
            "--state",
            str(state),
            "--backup",
            entered.backup_path,
            "--actor",
            "rollback-owner",
            "--reason",
            "resume queued content",
            "--expected-state-sha256",
            load_task_pool_mode_evidence(state).sha256,
            "--expected-active-task-id",
            "stale-run",
            "--now",
            "2026-07-23T12:05:00+00:00",
        ],
    )

    assert task_pool_control.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["acknowledged_active_task_ids"] == ["stale-run"]
    assert queue.read_bytes() == original_bytes


@pytest.mark.parametrize("queue_already_restored", [False, True])
def test_restore_resumes_a_prepared_transaction_across_queue_write(
    tmp_path: Path,
    queue_already_restored: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup = tmp_path / "backups" / "next_tasks.json"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    backup_bytes = _write_pool(backup, original_rows)
    _write_pool(queue, original_rows if queue_already_restored else [])
    digest = hashlib.sha256(backup_bytes).hexdigest()
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema": 2,
                "enabled": True,
                "mode": "restore_in_progress",
                "activated_at": "2026-07-23T12:00:00+00:00",
                "activated_by": "cutover-owner",
                "reason": "direct mode",
                "queue_path": str(queue.resolve()),
                "backup_path": str(backup.resolve()),
                "backup_sha256": digest,
                "backup_bytes": len(backup_bytes),
                "backup_task_count": 1,
                "preserve_task_ids": [],
                "restore_started_at": "2026-07-23T12:05:00+00:00",
                "restore_requested_by": "rollback-owner",
                "restore_reason": "rollback rehearsal",
                "restore_source_state_sha256": "a" * 64,
                "restore_target_sha256": digest,
                "restore_target_bytes": len(backup_bytes),
                "restore_target_task_count": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prepared_sha256 = load_task_pool_mode_evidence(state).sha256
    queue_identity = (queue.stat().st_dev, queue.stat().st_ino)
    original_fsync = task_pool_mode.os.fsync
    original_atomic_write = task_pool_mode._atomic_write_json
    durability_events: list[str] = []

    def track_fsync(descriptor: int) -> None:
        stat = task_pool_mode.os.fstat(descriptor)
        if (stat.st_dev, stat.st_ino) == queue_identity:
            durability_events.append("queue_fsync")
        original_fsync(descriptor)

    def track_final_state(path: Path, payload: dict[str, object]) -> None:
        if payload.get("mode") == "queued_execution":
            durability_events.append("final_state")
        original_atomic_write(path, payload)

    monkeypatch.setattr(task_pool_mode.os, "fsync", track_fsync)
    monkeypatch.setattr(task_pool_mode, "_atomic_write_json", track_final_state)

    restored = restore_task_pool_backup(
        queue_path=queue,
        state_path=state,
        backup_path=backup,
        restored_by="retry-worker",
        reason="resume prepared restore",
        expected_state_sha256=prepared_sha256,
        now="2026-07-23T12:10:00+00:00",
    )

    assert restored.restored_task_count == 1
    assert queue.read_bytes() == backup_bytes
    final_state = json.loads(state.read_text())
    assert final_state["enabled"] is False
    assert final_state["mode"] == "queued_execution"
    assert final_state["restored_by"] == "rollback-owner"
    assert final_state["queue_path"] == str(queue.resolve())
    assert final_state["restored_transaction_state_sha256"] == prepared_sha256
    assert final_state["restored_source_state_sha256"] == "a" * 64
    assert durability_events.index("queue_fsync") < durability_events.index(
        "final_state"
    )


def test_restore_rejects_malformed_prepared_receipt_without_touching_queue(
    tmp_path: Path,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup = tmp_path / "backups" / "next_tasks.json"
    backup_bytes = _write_pool(
        backup,
        [{"id": "old-pending", "status": "pending", "priority": 2}],
    )
    queue_bytes = _write_pool(queue, [])
    digest = hashlib.sha256(backup_bytes).hexdigest()
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema": 2,
                "enabled": True,
                "mode": "restore_in_progress",
                "queue_path": str(queue.resolve()),
                "backup_path": str(backup.resolve()),
                "backup_sha256": digest,
                "backup_bytes": len(backup_bytes),
                "backup_task_count": 1,
                "preserve_task_ids": [],
                "restore_started_at": "2026-07-23T12:05:00+00:00",
                "restore_requested_by": "rollback-owner",
                "restore_reason": "rollback rehearsal",
                "restore_source_state_sha256": "not-a-sha",
                "restore_target_sha256": digest,
                "restore_target_bytes": len(backup_bytes),
                "restore_target_task_count": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prepared_bytes = state.read_bytes()

    with pytest.raises(
        ValueError,
        match="restore_source_state_sha256 must be 64 lowercase hexadecimal",
    ):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=backup,
            restored_by="retry-worker",
            reason="resume prepared restore",
            expected_state_sha256=hashlib.sha256(prepared_bytes).hexdigest(),
            now="2026-07-23T12:10:00+00:00",
        )

    assert queue.read_bytes() == queue_bytes
    assert state.read_bytes() == prepared_bytes


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    [
        ("restore_started_at", " ", "restore_started_at must not be empty"),
        ("restore_requested_by", "", "restore_requested_by must not be empty"),
        ("restore_reason", " ", "restore_reason must not be empty"),
    ],
)
def test_restore_rejects_empty_prepared_provenance(
    tmp_path: Path,
    field: str,
    invalid_value: str,
    message: str,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup = tmp_path / "backups" / "next_tasks.json"
    backup_bytes = _write_pool(
        backup,
        [{"id": "old-pending", "status": "pending", "priority": 2}],
    )
    queue_bytes = _write_pool(queue, [])
    digest = hashlib.sha256(backup_bytes).hexdigest()
    payload: dict[str, object] = {
        "schema": 2,
        "enabled": True,
        "mode": "restore_in_progress",
        "queue_path": str(queue.resolve()),
        "backup_path": str(backup.resolve()),
        "backup_sha256": digest,
        "backup_bytes": len(backup_bytes),
        "backup_task_count": 1,
        "preserve_task_ids": [],
        "restore_started_at": "2026-07-23T12:05:00+00:00",
        "restore_requested_by": "rollback-owner",
        "restore_reason": "rollback rehearsal",
        "restore_source_state_sha256": "a" * 64,
        "restore_target_sha256": digest,
        "restore_target_bytes": len(backup_bytes),
        "restore_target_task_count": 1,
    }
    payload[field] = invalid_value
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    state_bytes = state.read_bytes()

    with pytest.raises(ValueError, match=message):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=backup,
            restored_by="retry-worker",
            reason="resume prepared restore",
            expected_state_sha256=hashlib.sha256(state_bytes).hexdigest(),
            now="2026-07-23T12:10:00+00:00",
        )

    assert queue.read_bytes() == queue_bytes
    assert state.read_bytes() == state_bytes


@pytest.mark.parametrize("metadata_field", ["backup_bytes", "backup_task_count"])
def test_restore_rejects_prepared_backup_metadata_drift(
    tmp_path: Path,
    metadata_field: str,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup = tmp_path / "backups" / "next_tasks.json"
    backup_bytes = _write_pool(
        backup,
        [{"id": "old-pending", "status": "pending", "priority": 2}],
    )
    queue_bytes = _write_pool(queue, [])
    digest = hashlib.sha256(backup_bytes).hexdigest()
    payload: dict[str, object] = {
        "schema": 2,
        "enabled": True,
        "mode": "restore_in_progress",
        "queue_path": str(queue.resolve()),
        "backup_path": str(backup.resolve()),
        "backup_sha256": digest,
        "backup_bytes": len(backup_bytes),
        "backup_task_count": 1,
        "preserve_task_ids": [],
        "restore_started_at": "2026-07-23T12:05:00+00:00",
        "restore_requested_by": "rollback-owner",
        "restore_reason": "rollback rehearsal",
        "restore_source_state_sha256": "a" * 64,
        "restore_target_sha256": digest,
        "restore_target_bytes": len(backup_bytes),
        "restore_target_task_count": 1,
    }
    payload[metadata_field] = int(payload[metadata_field]) + 1
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    state_bytes = state.read_bytes()

    with pytest.raises(
        ValueError,
        match="backup metadata does not match the active direct-mode receipt",
    ):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=backup,
            restored_by="retry-worker",
            reason="resume prepared restore",
            expected_state_sha256=hashlib.sha256(state_bytes).hexdigest(),
            now="2026-07-23T12:10:00+00:00",
        )

    assert queue.read_bytes() == queue_bytes
    assert state.read_bytes() == state_bytes


def test_restore_rejects_a_different_queue_than_the_active_receipt(
    tmp_path: Path,
) -> None:
    active_queue = tmp_path / "storage" / "next_tasks.json"
    wrong_queue = tmp_path / "storage" / "other_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    original_bytes = _write_pool(active_queue, original_rows)
    wrong_queue_bytes = _write_pool(wrong_queue, [])
    entered = enter_direct_execution_mode(
        queue_path=active_queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    forged_receipt = json.loads(state.read_text())
    forged_receipt["queue_path"] = str(wrong_queue.resolve())
    state.write_text(
        json.dumps(forged_receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    state_bytes = state.read_bytes()
    active_queue_bytes = active_queue.read_bytes()

    with pytest.raises(
        ValueError,
        match="queue path does not match the active direct-mode receipt",
    ):
        restore_task_pool_backup(
            queue_path=active_queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="rollback-owner",
            reason="rollback rehearsal",
            expected_state_sha256=hashlib.sha256(state_bytes).hexdigest(),
            now="2026-07-23T12:05:00+00:00",
        )

    assert active_queue.read_bytes() == active_queue_bytes
    assert wrong_queue.read_bytes() == wrong_queue_bytes
    assert state.read_bytes() == state_bytes
    assert Path(entered.backup_path).read_bytes() == original_bytes


def test_prepared_restore_pins_queue_identity_across_symlink_retarget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    alias = tmp_path / "alias" / "next_tasks.json"
    other_queue = tmp_path / "other" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    backup = tmp_path / "backups" / "next_tasks.json"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    backup_bytes = _write_pool(backup, original_rows)
    queue_bytes = _write_pool(queue, [])
    other_bytes = _write_pool(other_queue, original_rows)
    alias.parent.mkdir()
    alias.symlink_to(queue)
    digest = hashlib.sha256(backup_bytes).hexdigest()
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps(
            {
                "schema": 2,
                "enabled": True,
                "mode": "restore_in_progress",
                "queue_path": str(queue.resolve()),
                "backup_path": str(backup.resolve()),
                "backup_sha256": digest,
                "backup_bytes": len(backup_bytes),
                "backup_task_count": 1,
                "preserve_task_ids": [],
                "restore_started_at": "2026-07-23T12:05:00+00:00",
                "restore_requested_by": "rollback-owner",
                "restore_reason": "rollback rehearsal",
                "restore_source_state_sha256": "a" * 64,
                "restore_target_sha256": digest,
                "restore_target_bytes": len(backup_bytes),
                "restore_target_task_count": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prepared_sha256 = load_task_pool_mode_evidence(state).sha256
    original_require_queue = task_pool_mode._require_receipt_queue

    def retarget_after_receipt_check(
        mode: task_pool_mode.TaskPoolMode,
        observed_queue: Path,
    ) -> str:
        receipt_queue = original_require_queue(mode, observed_queue)
        alias.unlink()
        alias.symlink_to(other_queue)
        return receipt_queue

    monkeypatch.setattr(
        task_pool_mode,
        "_require_receipt_queue",
        retarget_after_receipt_check,
    )

    restored = restore_task_pool_backup(
        queue_path=alias,
        state_path=state,
        backup_path=backup,
        restored_by="retry-worker",
        reason="resume prepared restore",
        expected_state_sha256=prepared_sha256,
        now="2026-07-23T12:10:00+00:00",
    )

    assert restored.restored_task_count == 1
    assert queue.read_bytes() == backup_bytes
    assert queue.read_bytes() != queue_bytes
    assert other_queue.read_bytes() == other_bytes
    assert load_task_pool_mode(state).enabled is False


def test_restore_fails_if_final_owner_state_does_not_read_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    original_rows = [{"id": "old-pending", "status": "pending", "priority": 2}]
    original_bytes = _write_pool(queue, original_rows)
    monkeypatch.setattr(next_tasks, "CANONICAL_NEXT_TASKS", queue)
    monkeypatch.setattr(next_tasks, "TASK_POOL_MODE_PATH", state)
    entered = enter_direct_execution_mode(
        queue_path=queue,
        state_path=state,
        backup_dir=tmp_path / "backups",
        activated_by="cutover-owner",
        reason="direct mode",
        expected_state_sha256=None,
        now="2026-07-23T12:00:00+00:00",
    )
    active_sha256 = load_task_pool_mode_evidence(state).sha256
    original_atomic_write = task_pool_mode._atomic_write_json
    writes = 0

    def corrupt_final_state(path: Path, payload: dict[str, object]) -> None:
        nonlocal writes
        writes += 1
        original_atomic_write(path, payload)
        if writes == 2:
            corrupted = dict(payload)
            corrupted["enabled"] = True
            corrupted["mode"] = "restore_in_progress"
            original_atomic_write(path, corrupted)

    monkeypatch.setattr(task_pool_mode, "_atomic_write_json", corrupt_final_state)

    with pytest.raises(
        RuntimeError,
        match="final owner-state read-back verification failed",
    ):
        restore_task_pool_backup(
            queue_path=queue,
            state_path=state,
            backup_path=entered.backup_path,
            restored_by="rollback-owner",
            reason="rollback rehearsal",
            expected_state_sha256=active_sha256,
            now="2026-07-23T12:05:00+00:00",
        )

    assert queue.read_bytes() == original_bytes
    assert load_task_pool_mode(state).enabled is True


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


def test_status_returns_restore_identity_when_queue_is_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    queue.parent.mkdir(parents=True)
    queue.write_text('[{"id": "partial"', encoding="utf-8")
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    state.parent.mkdir(parents=True)
    state_bytes = (
        json.dumps(
            {
                "schema": 2,
                "enabled": True,
                "mode": "restore_in_progress",
                "queue_path": str(queue.resolve()),
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
    assert payload["mode"]["mode"] == "restore_in_progress"
    assert payload["queue_readable"] is False
    assert payload["pool_count"] is None
    assert "Expecting" in payload["queue_error"]


def test_status_rejects_a_detached_owner_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = tmp_path / "storage" / "next_tasks.json"
    _write_pool(queue, [])
    detached_state = tmp_path / "detached" / "task_pool_mode.json"
    detached_state.parent.mkdir(parents=True)
    detached_state.write_text(
        json.dumps({"enabled": True, "mode": "direct_execution"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_control.py",
            "status",
            "--queue",
            str(queue),
            "--state",
            str(detached_state),
        ],
    )

    with pytest.raises(
        ValueError,
        match="state path does not match the queue-paired owner state",
    ):
        task_pool_control.main()
