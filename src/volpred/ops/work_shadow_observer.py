"""Scheduled, read-only producer for Work Coordinator shadow receipts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
import fcntl
import json
from pathlib import Path
from typing import Any

from .work import WorkerOffer
from .work.legacy import LegacySnapshots
from .work_shadow_replay import (
    append_shadow_observation,
    freeze_legacy_snapshots,
    replay_legacy_selection,
)


SnapshotReader = Callable[[], Sequence[Mapping[str, Any]]]
_ACTIVE_TASK_RECORD_STATUSES = frozenset(
    {
        "queued",
        "claimed",
        "running",
        "awaiting_approval",
        "awaiting_retry",
        "pending",
    }
)
_ACTIVE_OPS_JOB_STATUSES = frozenset({"queued", "running"})


def _record_identity(record: Mapping[str, Any]) -> str | None:
    raw = record.get("id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _parent_identity(record: Mapping[str, Any]) -> str | None:
    for field in ("parent_task_id", "parent_id"):
        raw = record.get(field)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _scope_receipt_sources(
    *,
    next_tasks: Sequence[Mapping[str, Any]],
    task_records: Sequence[Mapping[str, Any]],
    ops_jobs: Sequence[Mapping[str, Any]],
) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
]:
    """Keep pending owners, duplicate identities, and parent dependencies."""

    relevant_ids = {
        identity
        for record in next_tasks
        if (identity := _record_identity(record)) is not None
    }
    relevant_ids.update(
        identity
        for record in next_tasks
        if (identity := _parent_identity(record)) is not None
    )

    scoped_task_records: tuple[Mapping[str, Any], ...] = ()
    while True:
        scoped_task_records = tuple(
            record
            for record in task_records
            if (
                _record_identity(record) in relevant_ids
                or str(record.get("status") or "").strip().lower()
                in _ACTIVE_TASK_RECORD_STATUSES
            )
        )
        expanded_ids = set(relevant_ids)
        expanded_ids.update(
            identity
            for record in scoped_task_records
            if (identity := _parent_identity(record)) is not None
        )
        if expanded_ids == relevant_ids:
            break
        relevant_ids = expanded_ids

    scoped_ops_jobs = tuple(
        record
        for record in ops_jobs
        if (
            _record_identity(record) in relevant_ids
            or str(record.get("status") or "").strip().lower()
            in _ACTIVE_OPS_JOB_STATUSES
        )
    )
    return scoped_task_records, scoped_ops_jobs


def observe_work_shadow(
    *,
    next_tasks_reader: SnapshotReader,
    task_records_reader: SnapshotReader,
    ops_jobs_reader: SnapshotReader,
    observation_directory: Path,
    observation_id: str,
    observed_at: datetime,
    offer: WorkerOffer,
) -> Path:
    """Freeze three legacy sources once, replay them, and append one receipt."""

    snapshots = freeze_legacy_snapshots(
        LegacySnapshots(
            next_tasks=tuple(next_tasks_reader()),
            task_records=tuple(task_records_reader()),
            ops_jobs=tuple(ops_jobs_reader()),
        )
    )
    ledger = replay_legacy_selection(
        snapshots,
        offer=offer,
        observed_at=observed_at,
        observation_id=observation_id,
    )
    return append_shadow_observation(
        ledger,
        directory=observation_directory,
    )


def observe_canonical_work_shadow(
    *,
    project_root: Path,
    task_records_reader: SnapshotReader,
    ops_jobs_reader: SnapshotReader,
    observed_at: datetime,
    observation_id: str,
) -> Path:
    """Observe the canonical pending queue plus its two legacy receipt stores."""

    queue_path = project_root / "storage" / "next_tasks.json"

    with queue_path.open("rb") as queue_handle:
        fcntl.flock(queue_handle.fileno(), fcntl.LOCK_SH)
        try:
            payload = json.loads(queue_handle.read())
        finally:
            fcntl.flock(queue_handle.fileno(), fcntl.LOCK_UN)
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(
            "canonical next_tasks snapshot must be an array of objects"
        )
    next_tasks = tuple(payload)
    task_records = tuple(task_records_reader())
    ops_jobs = tuple(ops_jobs_reader())
    scoped_task_records, scoped_ops_jobs = _scope_receipt_sources(
        next_tasks=next_tasks,
        task_records=task_records,
        ops_jobs=ops_jobs,
    )

    return observe_work_shadow(
        next_tasks_reader=lambda: next_tasks,
        task_records_reader=lambda: scoped_task_records,
        ops_jobs_reader=lambda: scoped_ops_jobs,
        observation_directory=(
            project_root
            / "storage"
            / "ops"
            / "work_shadow_observations"
        ),
        observation_id=observation_id,
        observed_at=observed_at,
        offer=WorkerOffer(
            worker_id="scheduled-shadow",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        ),
    )


__all__ = ["observe_canonical_work_shadow", "observe_work_shadow"]
