"""Public read-only migration seam for legacy work snapshots."""

from __future__ import annotations

from .work.legacy import (
    LegacySnapshotImporter,
    LegacySnapshots,
    LegacyWorkCandidate,
    ReconciliationIssue,
    ReconciliationReport,
)


def preview_legacy_snapshots(
    snapshots: LegacySnapshots,
) -> ReconciliationReport:
    """Map and reconcile supplied snapshots without reading or writing sources."""
    return LegacySnapshotImporter().import_snapshot(snapshots)


__all__ = [
    "LegacySnapshots",
    "LegacyWorkCandidate",
    "ReconciliationIssue",
    "ReconciliationReport",
    "preview_legacy_snapshots",
]
