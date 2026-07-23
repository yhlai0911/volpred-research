"""Read-only compatibility projection for legacy ``next_tasks`` consumers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .work import WorkEventView, WorkItemView, WorkSnapshot
from .work.legacy import LegacySnapshotImporter, LegacySnapshots


NEXT_TASKS_PROJECTION_SCHEMA_VERSION = "next-tasks-read-projection.v1"


@dataclass(frozen=True)
class LegacyNextTasksProjection:
    """Immutable encoded projection; every read returns a detached copy."""

    schema_version: str
    row_count: int
    sha256: str
    _payload: bytes

    def read(self) -> list[dict[str, Any]]:
        return json.loads(self._payload)


_LEGACY_STATUS = {
    "pending": "pending",
    "awaiting_approval": "blocked_on_user",
    "claimed": "claimed",
    "running": "in_progress",
    "blocked": "blocked",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}


def _latest_event(
    events: tuple[WorkEventView, ...],
    *,
    kind: str,
    maximum_version: int,
) -> WorkEventView | None:
    matching = [
        event
        for event in events
        if event.kind == kind and event.version <= maximum_version
    ]
    if not matching:
        return None
    latest_version = max(event.version for event in matching)
    latest = [
        event for event in matching if event.version == latest_version
    ]
    if len(latest) != 1:
        raise ValueError(
            f"ambiguous {kind} event for WorkItem version {latest_version}"
        )
    return latest[0]


def _project_item(
    item: WorkItemView,
    *,
    events: tuple[WorkEventView, ...],
) -> dict[str, Any]:
    legacy_status = _LEGACY_STATUS.get(item.status)
    if legacy_status is None:
        raise ValueError(f"unsupported WorkItem projection status: {item.status}")
    row: dict[str, Any] = {
        "id": item.id,
        "status": legacy_status,
        "task_type": item.kind,
        "title": item.title,
        "priority": item.priority,
        "source": item.source,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "required_capabilities": sorted(item.required_capabilities),
        "required_attestations": sorted(item.required_attestations),
        "risk": item.risk,
        "approval": (
            "required" if item.approval == "approved" else item.approval
        ),
        "coordinator_version": item.version,
    }
    if item.approval == "approved":
        row["approval_state"] = "approved"
    if item.parent_id is not None:
        row["parent_task_id"] = item.parent_id
    if item.deadline is not None:
        row["deadline"] = item.deadline
    if item.status in {"awaiting_approval", "blocked"}:
        row["blocked_reason"] = (
            item.blocked_reason
            or (
                "awaiting_owner_approval"
                if item.status == "awaiting_approval"
                else None
            )
        )
    claimed_event: WorkEventView | None = None
    if item.status in {"claimed", "running"}:
        if item.claimed_by is None or item.claim_expires_at is None:
            raise ValueError(
                f"{item.status} WorkItem {item.id} has incomplete claim identity"
            )
        claimed_event = _latest_event(
            events,
            kind="acquired",
            maximum_version=item.version,
        )
        if claimed_event is None:
            raise ValueError(
                f"{item.status} WorkItem {item.id} has no acquired event"
            )
        row["claimed_by"] = item.claimed_by
        row["claim_expires_at"] = item.claim_expires_at
        row["claimed_at"] = claimed_event.created_at
    if item.status == "running":
        if claimed_event is None:
            raise ValueError(
                f"running WorkItem {item.id} has no acquired event"
            )
        started_event = _latest_event(
            events,
            kind="started",
            maximum_version=item.version,
        )
        if (
            started_event is None
            or started_event.version <= claimed_event.version
        ):
            raise ValueError(
                f"running WorkItem {item.id} has no started event "
                "for its current claim"
            )
        row["started_at"] = started_event.created_at
    if item.status in {"succeeded", "failed", "cancelled"}:
        row["completed_at"] = item.finished_at
        row["result"] = item.result_summary
        row["result_ref"] = item.result_ref
    return row


def project_legacy_next_tasks(
    snapshot: WorkSnapshot,
) -> LegacyNextTasksProjection:
    """Return a detached projection without reading or writing external state."""

    item_ids = [item.id for item in snapshot.items]
    if len(set(item_ids)) != len(item_ids):
        duplicate_id = next(
            item_id
            for index, item_id in enumerate(item_ids)
            if item_id in item_ids[:index]
        )
        raise ValueError(f"duplicate WorkItem id: {duplicate_id}")
    indexed_events: defaultdict[str, list[WorkEventView]] = defaultdict(list)
    for event in snapshot.events:
        indexed_events[event.work_id].append(event)
    rows = [
        _project_item(
            item,
            events=tuple(indexed_events[item.id]),
        )
        for item in sorted(
            snapshot.items,
            key=lambda candidate: (candidate.priority, candidate.id),
        )
    ]
    compatibility = LegacySnapshotImporter().import_snapshot(
        LegacySnapshots(next_tasks=tuple(rows))
    )
    if not compatibility.ready:
        issue = compatibility.issues[0]
        raise ValueError(
            "legacy compatibility projection rejected "
            f"{issue.record_id or '<unknown>'}: {issue.code}: {issue.detail}"
        )
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return LegacyNextTasksProjection(
        schema_version=NEXT_TASKS_PROJECTION_SCHEMA_VERSION,
        row_count=len(rows),
        sha256=hashlib.sha256(payload).hexdigest(),
        _payload=payload,
    )


__all__ = [
    "LegacyNextTasksProjection",
    "NEXT_TASKS_PROJECTION_SCHEMA_VERSION",
    "project_legacy_next_tasks",
]
