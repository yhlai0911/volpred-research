#!/usr/bin/env python3
"""Append one scheduled Work Coordinator shadow observation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from volpred.ops.jobs import list_jobs
from volpred.ops.local_control_plane import list_tasks
from volpred.ops.work_shadow_observer import (
    observe_canonical_work_shadow,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_observation(
    *,
    project_root: Path = PROJECT_ROOT,
    observed_at: datetime | None = None,
    observation_id: str | None = None,
) -> dict[str, object]:
    """Capture canonical sources once and return the appended receipt."""

    replay_time = observed_at or datetime.now(timezone.utc)
    receipt_id = observation_id or (
        f"scheduled_{replay_time.strftime('%Y%m%dT%H%M%S%fZ')}_"
        f"{uuid4().hex[:12]}"
    )
    receipt_path = observe_canonical_work_shadow(
        project_root=project_root,
        task_records_reader=lambda: list_tasks(
            storage_dir=str(project_root / "storage")
        ),
        ops_jobs_reader=lambda: list_jobs(limit=100_000),
        observed_at=replay_time,
        observation_id=receipt_id,
    )
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    return {**payload, "receipt_path": str(receipt_path)}


def main() -> int:
    receipt = run_observation()
    snapshot = receipt.get("snapshot")
    source_counts = (
        snapshot.get("source_counts")
        if isinstance(snapshot, dict)
        else None
    )
    difference = receipt.get("selection_difference")
    difference_classification = (
        difference.get("classification")
        if isinstance(difference, dict)
        else None
    )
    issues = receipt.get("reconciliation_issues")
    summary = {
        "schema_version": "work-shadow-observer-run.v1",
        "observation_id": receipt.get("observation_id"),
        "recorded_at": receipt.get("recorded_at"),
        "receipt_path": receipt.get("receipt_path"),
        "source_counts": source_counts,
        "selection_difference_classification": (
            difference_classification
        ),
        "reconciliation_issue_count": (
            len(issues) if isinstance(issues, list) else None
        ),
    }
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
