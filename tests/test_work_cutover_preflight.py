from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from volpred.ops import work_cutover
from volpred.ops.work import WorkEventView, WorkItemView, WorkSnapshot
from volpred.ops.work.legacy import LegacySnapshotImporter, LegacySnapshots
from volpred.ops.work_cutover import prepare_work_ownership_cutover
from volpred.ops.work_projection import project_legacy_next_tasks
from volpred.ops.work_shadow_replay import identify_legacy_snapshots


START = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
FIXED_NOW = START + timedelta(days=7, hours=1)
REQUIRED_DIMENSIONS = (
    "priority",
    "claim_ownership",
    "parent",
    "deadline",
    "terminal_disposition",
)


@pytest.fixture(autouse=True)
def fixed_preflight_clock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(work_cutover, "_cutover_time", lambda: FIXED_NOW)
    monkeypatch.setattr(
        work_cutover,
        "_canonical_queue_path",
        lambda: tmp_path / "next_tasks.json",
    )


def _legacy_row() -> dict[str, object]:
    return {
        "id": "task-1",
        "status": "pending",
        "task_type": "platform_ops",
        "title": "Cut over the queue owner",
        "priority": 1,
        "source": "user",
        "created_at": START.isoformat(),
        "updated_at": START.isoformat(),
        "required_capabilities": ["code"],
        "required_attestations": [],
        "risk": "safe",
        "approval": "auto",
    }


def _legacy_bytes(*rows: dict[str, object]) -> bytes:
    return json.dumps(
        list(rows),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _staged_snapshot() -> WorkSnapshot:
    return WorkSnapshot(
        items=(
            WorkItemView(
                id="task-1",
                idempotency_key="legacy:next_tasks:task-1",
                source="user",
                kind="platform_ops",
                title="Cut over the queue owner",
                priority=1,
                required_capabilities=frozenset({"code"}),
                required_attestations=frozenset(),
                risk="safe",
                approval="auto",
                payload_ref="legacy:next_tasks:task-1",
                status="pending",
                version=1,
                created_at=START.isoformat(),
                updated_at=START.isoformat(),
            ),
        )
    )


def _write_observations(
    directory: Path,
    *,
    snapshots: LegacySnapshots,
    count: int = 8,
    start: datetime = START,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    identity = identify_legacy_snapshots(snapshots)
    for index in range(count):
        observed_at = start + timedelta(days=index)
        snapshot_sha = identity.sha256
        receipt = {
            "schema_version": "work-shadow-replay.v3",
            "observation_id": f"scheduled_{index:02d}",
            "observed_at": observed_at.isoformat(),
            "recorded_at": observed_at.isoformat(),
            "selection_scope": "next_tasks",
            "snapshot": {
                "sha256": snapshot_sha,
                "byte_count": identity.byte_count,
                "source_counts": identity.source_counts,
            },
            "legacy_selection": {
                "policy": "legacy",
                "snapshot_sha256": snapshot_sha,
                "selected_candidate_ref": "next_tasks:task-1",
                "eligible_candidate_refs": ["next_tasks:task-1"],
            },
            "coordinator_selection": {
                "policy": "work_coordinator",
                "snapshot_sha256": snapshot_sha,
                "selected_candidate_ref": "next_tasks:task-1",
                "eligible_candidate_refs": ["next_tasks:task-1"],
            },
            "selection_difference": None,
            "comparisons": [
                {
                    "candidate_ref": "next_tasks:task-1",
                    "legacy_eligible": True,
                    "coordinator_eligible": True,
                    "dimensions": [
                        {
                            "name": name,
                            "legacy": {"value": "same"},
                            "coordinator": {"value": "same"},
                            "matches": True,
                            "classification": None,
                            "classification_reason_code": None,
                            "legacy_reason_codes": [],
                            "coordinator_reason_codes": [],
                            "evidence_refs": [f"contract://{name}"],
                        }
                        for name in REQUIRED_DIMENSIONS
                    ],
                }
            ],
            "reconciliation_issues": [],
        }
        (directory / f"scheduled_{index:02d}.json").write_text(
            json.dumps(receipt),
            encoding="utf-8",
        )


def _write_canonical_queue(
    tmp_path: Path,
    payload: bytes,
    *,
    enabled: bool = False,
) -> None:
    queue_path = tmp_path / "next_tasks.json"
    queue_path.write_bytes(payload)
    path = tmp_path / "ops" / "task_pool_mode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "enabled": enabled,
                "mode": (
                    "direct_execution" if enabled else "queued_execution"
                ),
            }
        ),
        encoding="utf-8",
    )


def _prepare(
    tmp_path: Path,
    *,
    legacy_rows: tuple[dict[str, object], ...] | None = None,
    legacy_bytes: bytes | None = None,
    projection=None,
):
    rows = legacy_rows or (_legacy_row(),)
    snapshots = LegacySnapshots(next_tasks=rows)
    raw = legacy_bytes if legacy_bytes is not None else _legacy_bytes(*rows)
    _write_canonical_queue(tmp_path, raw)
    observations = tmp_path / "observations"
    _write_observations(observations, snapshots=snapshots)
    return prepare_work_ownership_cutover(
        observation_directory=observations,
        legacy_snapshots=snapshots,
        projection=projection or project_legacy_next_tasks(_staged_snapshot()),
    )


def test_preflight_derives_manifest_from_raw_evidence(
    tmp_path: Path,
) -> None:
    raw = _legacy_bytes(_legacy_row())

    manifest = _prepare(tmp_path, legacy_bytes=raw)

    assert manifest.schema_version == "work-owner-cutover-manifest.v3"
    assert manifest.legacy_row_count == 1
    assert manifest.coordinator_row_count == 1
    assert (
        manifest.projection_schema_version
        == "next-tasks-read-projection.v1"
    )
    assert manifest.legacy_snapshot_sha256 == hashlib.sha256(raw).hexdigest()
    assert manifest.prepared_at == FIXED_NOW.isoformat()
    assert manifest.valid_until == (
        FIXED_NOW + timedelta(minutes=15)
    ).isoformat()
    assert (
        hashlib.sha256(manifest.canonical_bytes()).hexdigest()
        == manifest.sha256
    )
    assert len(manifest.sha256) == 64


def test_preflight_rejects_incomplete_raw_observation_ledger(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    snapshots = LegacySnapshots(next_tasks=(_legacy_row(),))
    _write_canonical_queue(tmp_path, _legacy_bytes(_legacy_row()))
    _write_observations(observations, snapshots=snapshots, count=1)

    with pytest.raises(
        ValueError,
        match="shadow assessment is not ready for cutover",
    ):
        prepare_work_ownership_cutover(
            observation_directory=observations,
            legacy_snapshots=snapshots,
            projection=project_legacy_next_tasks(_staged_snapshot()),
        )


def test_preflight_uses_current_time_to_reject_a_stale_ledger(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations"
    snapshots = LegacySnapshots(next_tasks=(_legacy_row(),))
    _write_canonical_queue(tmp_path, _legacy_bytes(_legacy_row()))
    _write_observations(
        observations,
        snapshots=snapshots,
        start=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(
        ValueError,
        match="shadow assessment is not ready for cutover",
    ):
        prepare_work_ownership_cutover(
            observation_directory=observations,
            legacy_snapshots=snapshots,
            projection=project_legacy_next_tasks(_staged_snapshot()),
        )


def test_preflight_rejects_cross_wired_raw_snapshot_bytes(
    tmp_path: Path,
) -> None:
    other = _legacy_row()
    other["priority"] = 2

    with pytest.raises(
        ValueError,
        match="raw legacy snapshot does not match supplied snapshots",
    ):
        _prepare(
            tmp_path,
            legacy_rows=(_legacy_row(),),
            legacy_bytes=_legacy_bytes(other),
        )


def test_preflight_rejects_a_ledger_for_a_different_snapshot(
    tmp_path: Path,
) -> None:
    observed = LegacySnapshots(next_tasks=(_legacy_row(),))
    observations = tmp_path / "observations"
    _write_observations(observations, snapshots=observed)
    replacement = _legacy_row()
    replacement["id"] = "task-2"
    replacement_snapshot = LegacySnapshots(next_tasks=(replacement,))
    _write_canonical_queue(tmp_path, _legacy_bytes(replacement))
    staged = replace(
        _staged_snapshot().items[0],
        id="task-2",
        idempotency_key="legacy:next_tasks:task-2",
    )

    with pytest.raises(
        ValueError,
        match="shadow ledger does not end at the cutover snapshot",
    ):
        prepare_work_ownership_cutover(
            observation_directory=observations,
            legacy_snapshots=replacement_snapshot,
            projection=project_legacy_next_tasks(
                WorkSnapshot(items=(staged,))
            ),
        )


def test_preflight_reads_the_canonical_owner_gate(
    tmp_path: Path,
) -> None:
    snapshots = LegacySnapshots(next_tasks=(_legacy_row(),))
    _write_canonical_queue(
        tmp_path,
        _legacy_bytes(_legacy_row()),
        enabled=True,
    )
    observations = tmp_path / "observations"
    _write_observations(observations, snapshots=snapshots)

    with pytest.raises(
        ValueError,
        match="shadow assessment is not ready for cutover",
    ):
        prepare_work_ownership_cutover(
            observation_directory=observations,
            legacy_snapshots=snapshots,
            projection=project_legacy_next_tasks(_staged_snapshot()),
        )


def test_preflight_rejects_forged_projection_metadata(
    tmp_path: Path,
) -> None:
    projection = project_legacy_next_tasks(_staged_snapshot())
    forged = replace(
        projection,
        row_count=999,
        sha256="d" * 64,
    )

    with pytest.raises(
        ValueError,
        match="coordinator projection metadata does not match payload",
    ):
        _prepare(tmp_path, projection=forged)


def test_preflight_rejects_unknown_projection_schema(
    tmp_path: Path,
) -> None:
    projection = replace(
        project_legacy_next_tasks(_staged_snapshot()),
        schema_version="next-tasks-read-projection.v999",
    )

    with pytest.raises(
        ValueError,
        match="unsupported coordinator projection schema",
    ):
        _prepare(tmp_path, projection=projection)


def test_preflight_rejects_projection_dimension_drift(
    tmp_path: Path,
) -> None:
    staged = _staged_snapshot()
    staged = WorkSnapshot(
        items=(replace(staged.items[0], priority=2),),
    )

    with pytest.raises(
        ValueError,
        match="coordinator projection does not match legacy import",
    ):
        _prepare(
            tmp_path,
            projection=project_legacy_next_tasks(staged),
        )


def test_preflight_rejects_unrepresentable_dispatch_policy(
    tmp_path: Path,
) -> None:
    legacy = _legacy_row()
    legacy.update(
        {
            "dispatch_lane": "main_thread",
            "preferred_agent": "claude",
            "target_agent": "claude",
            "fallback_allowed": False,
        }
    )

    with pytest.raises(
        ValueError,
        match="coordinator projection does not match legacy import",
    ):
        _prepare(tmp_path, legacy_rows=(legacy,))


def test_preflight_freezes_mutable_caller_rows_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutable_row = _legacy_row()
    snapshots = LegacySnapshots(next_tasks=(mutable_row,))
    _write_canonical_queue(tmp_path, _legacy_bytes(mutable_row))
    observations = tmp_path / "observations"
    _write_observations(observations, snapshots=snapshots)
    projection = project_legacy_next_tasks(_staged_snapshot())
    real_import = LegacySnapshotImporter.import_snapshot

    def mutate_caller_then_import(
        importer: LegacySnapshotImporter,
        supplied: LegacySnapshots,
    ):
        mutable_row["priority"] = 2
        return real_import(importer, supplied)

    monkeypatch.setattr(
        LegacySnapshotImporter,
        "import_snapshot",
        mutate_caller_then_import,
    )

    manifest = prepare_work_ownership_cutover(
        observation_directory=observations,
        legacy_snapshots=snapshots,
        projection=projection,
    )

    assert mutable_row["priority"] == 2
    assert manifest.legacy_row_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("created_at", "2026-07-16T11:59:59+00:00"),
        ("updated_at", "2026-07-16T12:00:02+00:00"),
    ),
)
def test_preflight_rejects_projection_timestamp_drift(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    staged = _staged_snapshot()
    staged = WorkSnapshot(
        items=(
            replace(
                staged.items[0],
                **{field: value},
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="coordinator projection does not match legacy import",
    ):
        _prepare(
            tmp_path,
            projection=project_legacy_next_tasks(staged),
        )


def test_preflight_reconciles_running_started_at(
    tmp_path: Path,
) -> None:
    legacy = _legacy_row()
    legacy.update(
        {
            "status": "in_progress",
            "claimed_by": "worker-a",
            "claimed_at": "2026-07-16T12:01:00+00:00",
            "started_at": "2026-07-16T12:02:00+00:00",
            "claim_expires_at": "2026-07-16T13:00:00+00:00",
            "updated_at": "2026-07-16T12:03:00+00:00",
        }
    )
    running = replace(
        _staged_snapshot().items[0],
        status="running",
        version=3,
        claimed_by="worker-a",
        claim_expires_at="2026-07-16T13:00:00+00:00",
        updated_at="2026-07-16T12:03:00+00:00",
    )
    projection = project_legacy_next_tasks(
        WorkSnapshot(
            items=(running,),
            events=(
                WorkEventView(
                    work_id="task-1",
                    kind="acquired",
                    version=2,
                    created_at="2026-07-16T12:01:00+00:00",
                ),
                WorkEventView(
                    work_id="task-1",
                    kind="started",
                    version=3,
                    created_at="2026-07-16T12:02:30+00:00",
                ),
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="coordinator projection does not match legacy import",
    ):
        _prepare(
            tmp_path,
            legacy_rows=(legacy,),
            projection=projection,
        )


@pytest.mark.parametrize(
    ("legacy_status", "coordinator_status", "version", "events"),
    (
        (
            "claimed",
            "claimed",
            2,
            (
                WorkEventView(
                    work_id="task-1",
                    kind="acquired",
                    version=2,
                    created_at="2026-07-16T12:01:00+00:00",
                ),
            ),
        ),
        (
            "in_progress",
            "running",
            3,
            (
                WorkEventView(
                    work_id="task-1",
                    kind="acquired",
                    version=2,
                    created_at="2026-07-16T12:01:00+00:00",
                ),
                WorkEventView(
                    work_id="task-1",
                    kind="started",
                    version=3,
                    created_at="2026-07-16T12:02:00+00:00",
                ),
            ),
        ),
    ),
)
def test_preflight_rejects_active_legacy_leases_even_when_parity_matches(
    tmp_path: Path,
    legacy_status: str,
    coordinator_status: str,
    version: int,
    events: tuple[WorkEventView, ...],
) -> None:
    legacy = _legacy_row()
    legacy.update(
        {
            "status": legacy_status,
            "claimed_by": "worker-a",
            "claimed_at": "2026-07-16T12:01:00+00:00",
            "claim_expires_at": "2026-07-16T13:00:00+00:00",
            "updated_at": (
                "2026-07-16T12:02:00+00:00"
                if coordinator_status == "running"
                else "2026-07-16T12:01:00+00:00"
            ),
        }
    )
    if coordinator_status == "running":
        legacy["started_at"] = "2026-07-16T12:02:00+00:00"
    staged = replace(
        _staged_snapshot().items[0],
        status=coordinator_status,
        version=version,
        claimed_by="worker-a",
        claim_expires_at="2026-07-16T13:00:00+00:00",
        updated_at=legacy["updated_at"],
    )
    projection = project_legacy_next_tasks(
        WorkSnapshot(items=(staged,), events=events)
    )

    with pytest.raises(
        ValueError,
        match="cutover requires a quiescent legacy queue.*task-1",
    ):
        _prepare(
            tmp_path,
            legacy_rows=(legacy,),
            projection=projection,
        )
