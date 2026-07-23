"""Public read-only migration seam for legacy work snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from .work.legacy import (
    LegacySnapshotImporter,
    LegacySnapshots,
    LegacyWorkCandidate,
    ReconciliationIssue,
    ReconciliationReport,
)


class LegacySnapshotLoadError(ValueError):
    """Stable validation failure for one supplied legacy snapshot."""

    code = "invalid_snapshot"

    def __init__(self, *, source_system: str, detail: str) -> None:
        self.source_system = source_system
        self.detail = detail
        super().__init__(f"{source_system} [{self.code}]: {detail}")

    def as_issue(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "source_system": self.source_system,
            "record_id": None,
            "detail": self.detail,
        }


def _load_snapshot(path: Path, *, source_system: str) -> tuple[dict, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise LegacySnapshotLoadError(
            source_system=source_system,
            detail="snapshot is not readable UTF-8 JSON",
        ) from exc
    except OSError as exc:
        raise LegacySnapshotLoadError(
            source_system=source_system,
            detail="snapshot is not readable",
        ) from exc
    except json.JSONDecodeError as exc:
        raise LegacySnapshotLoadError(
            source_system=source_system,
            detail="snapshot is not valid JSON",
        ) from exc
    if not isinstance(payload, list):
        raise LegacySnapshotLoadError(
            source_system=source_system,
            detail="snapshot must be a JSON array",
        )
    if not all(isinstance(record, dict) for record in payload):
        raise LegacySnapshotLoadError(
            source_system=source_system,
            detail="snapshot items must be JSON objects",
        )
    return tuple(payload)


def load_legacy_snapshots(
    *,
    next_tasks_path: Path,
    task_records_path: Path,
    ops_jobs_path: Path,
) -> LegacySnapshots:
    """Load the three explicit legacy snapshot files."""

    return LegacySnapshots(
        next_tasks=_load_snapshot(
            next_tasks_path,
            source_system="next_tasks",
        ),
        task_records=_load_snapshot(
            task_records_path,
            source_system="task_records",
        ),
        ops_jobs=_load_snapshot(
            ops_jobs_path,
            source_system="ops_jobs",
        ),
    )


def preview_legacy_snapshots(
    snapshots: LegacySnapshots,
) -> ReconciliationReport:
    """Map and reconcile supplied snapshots without reading or writing sources."""
    return LegacySnapshotImporter().import_snapshot(snapshots)


__all__ = [
    "LegacySnapshotLoadError",
    "LegacySnapshots",
    "LegacyWorkCandidate",
    "ReconciliationIssue",
    "ReconciliationReport",
    "load_legacy_snapshots",
    "preview_legacy_snapshots",
]
