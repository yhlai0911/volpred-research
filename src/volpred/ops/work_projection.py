"""Read-only compatibility projection for legacy ``next_tasks`` consumers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .work import WorkEventView, WorkItemView, WorkSnapshot


_SCHEMA_VERSION = "next-tasks-read-projection.v1"


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
    "succeeded": "succeeded",
}


def _latest_event_at(
    events: tuple[WorkEventView, ...],
    *,
    kind: str,
    maximum_version: int,
) -> str | None:
    matching = [
        event
        for event in events
        if event.kind == kind and event.version <= maximum_version
    ]
    if not matching:
        return None
    return max(matching, key=lambda event: event.version).created_at


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
    if item.status == "awaiting_approval":
        row["blocked_reason"] = (
            item.blocked_reason or "awaiting_owner_approval"
        )
    if item.status in {"claimed", "running"}:
        if item.claimed_by is None or item.claim_expires_at is None:
            raise ValueError(
                f"{item.status} WorkItem {item.id} has incomplete claim identity"
            )
        claimed_at = _latest_event_at(
            events,
            kind="acquired",
            maximum_version=item.version,
        )
        if claimed_at is None:
            raise ValueError(
                f"{item.status} WorkItem {item.id} has no acquired event"
            )
        row["claimed_by"] = item.claimed_by
        row["claim_expires_at"] = item.claim_expires_at
        row["claimed_at"] = claimed_at
    if item.status == "running":
        started_at = _latest_event_at(
            events,
            kind="started",
            maximum_version=item.version,
        )
        if started_at is None:
            raise ValueError(
                f"running WorkItem {item.id} has no started event"
            )
        row["started_at"] = started_at
    if item.status == "succeeded":
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
    events_by_work_id = {
        item.id: tuple(
            event
            for event in snapshot.events
            if event.work_id == item.id
        )
        for item in snapshot.items
    }
    rows = [
        _project_item(
            item,
            events=events_by_work_id[item.id],
        )
        for item in sorted(
            snapshot.items,
            key=lambda candidate: (candidate.priority, candidate.id),
        )
    ]
    payload = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return LegacyNextTasksProjection(
        schema_version=_SCHEMA_VERSION,
        row_count=len(rows),
        sha256=hashlib.sha256(payload).hexdigest(),
        _payload=payload,
    )


__all__ = [
    "LegacyNextTasksProjection",
    "project_legacy_next_tasks",
]
