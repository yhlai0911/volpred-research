#!/usr/bin/env python3
"""Backfill invalid task ``created_at`` values from verifiable evidence.

This migration never invents an exact creation timestamp.  When legacy rows
lack that fact, it records an explicit ``created_at_observed_not_after`` upper
bound from the earliest timezone-aware lifecycle event or a reviewed Git
snapshot.  Every changed row retains evidence, and apply mode emits a
hash-bound receipt for the whole queue transition.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.next_tasks import write_tasks_to_handle

NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
DEFAULT_RECEIPT = (
    ROOT
    / "storage"
    / "ops"
    / "task_pool_provenance_migrations"
    / "issue9_shadow_reconciliation_closure_20260727.json"
)
LIFECYCLE_FIELDS = (
    "claimed_at",
    "started_at",
    "blocked_at",
    "updated_at",
    "completed_at",
)


class ProvenanceMigrationError(RuntimeError):
    """Raised when a timestamp cannot be repaired without fabrication."""


class InjectedMigrationCrash(RuntimeError):
    """Test-only failure injected after the durable queue write."""


@dataclass(frozen=True)
class GitEvidence:
    commit: str
    committed_at: str


_UNSET = object()


@dataclass(frozen=True)
class FieldEvidence:
    value: Any
    evidence_ref: str
    replace: bool = False
    expected: Any = _UNSET


REVIEWED_GIT_EVIDENCE: dict[str, GitEvidence] = {
    "K1161b_paid_options_data": GitEvidence(
        "72c1c7bc9b2635b7804a18e97c3bfc6c6e255b4c",
        "2026-04-17T14:25:09+08:00",
    ),
    "Paper2_section5_decision": GitEvidence(
        "aa9d8c98fa3ea047a74a6c1232fc62d9409dbe2c",
        "2026-04-17T12:40:46+08:00",
    ),
    "Paper4_channel_specific_pivot": GitEvidence(
        "2922e1ff67b15b4efee5e3ba8876abd606551c53",
        "2026-04-17T13:25:41+08:00",
    ),
    "paper3_E3_commodities_copula_rerun_20260721": GitEvidence(
        "bdd7c3f608ef8331e6305dff3a4be0b6a7ab6b4a",
        "2026-07-21T23:28:05+08:00",
    ),
    "ops_quota_anchor_recalibrate_20260722": GitEvidence(
        "d5586ac11232e2a1ca64a1a30fb2e2684a1ecaa2",
        "2026-07-22T09:40:08+08:00",
    ),
    "task_pool_awaiting_agent_job_state_gap": GitEvidence(
        "d2c6bcc9f7b4a33d6afba40bf0c21e19b031672a",
        "2026-07-22T11:09:09+08:00",
    ),
}
REVIEWED_FIELD_EVIDENCE: dict[str, dict[str, FieldEvidence]] = {
    "K1161b_paid_options_data": {
        "source": FieldEvidence(
            "user",
            "git:72c1c7bc9b2635b7804a18e97c3bfc6c6e255b4c"
            "#task/K1161b_paid_options_data-owner-decision",
        ),
        "blocked_reason": FieldEvidence(
            "paid_data_source_decision_pending",
            "git:72c1c7bc9b2635b7804a18e97c3bfc6c6e255b4c"
            "#task/K1161b_paid_options_data-description",
        ),
    },
    "Paper2_section5_decision": {
        "source": FieldEvidence(
            "user",
            "git:aa9d8c98fa3ea047a74a6c1232fc62d9409dbe2c"
            "#task/Paper2_section5_decision-user-confirmed",
        ),
        "blocked_reason": FieldEvidence(
            "awaiting_main_thread_body_rewrite",
            "git:aa9d8c98fa3ea047a74a6c1232fc62d9409dbe2c"
            "#task/Paper2_section5_decision-status",
        ),
    },
    "Paper4_channel_specific_pivot": {
        "source": FieldEvidence(
            "user",
            "git:2922e1ff67b15b4efee5e3ba8876abd606551c53"
            "#task/Paper4_channel_specific_pivot-user-confirmed",
        ),
        "blocked_reason": FieldEvidence(
            "awaiting_main_thread_body_rewrite",
            "git:2922e1ff67b15b4efee5e3ba8876abd606551c53"
            "#task/Paper4_channel_specific_pivot-status",
        ),
    },
    "paper2_taiwan_vt_rolling_block_reestimate": {
        "source": FieldEvidence(
            "user",
            "task://paper2_taiwan_vt_rolling_block_reestimate"
            "#blocked_reason_original-owner-sign-off",
        ),
    },
    "k1380_stage_refactor_collect": {
        "parent_task_id": FieldEvidence(
            None,
            "file:storage/ops/compute_queue/"
            "agent-brief_k1380_stage-68dea3.json#completed_at",
            replace=True,
        ),
        "upstream_receipt_ref": FieldEvidence(
            "storage/ops/compute_queue/agent-brief_k1380_stage-68dea3.json",
            "file:storage/ops/compute_queue/"
            "agent-brief_k1380_stage-68dea3.json#followup_next_task_id",
        ),
    },
    "snapdup_cert_fallback_codex_usage_limit_20260721": {
        "parent_task_id": FieldEvidence(
            None,
            "task://snapdup_cert_fallback_codex_usage_limit_20260721"
            "#description-worktree-harvest-batch",
            replace=True,
        ),
        "upstream_receipt_ref": FieldEvidence(
            "legacy-batch:worktree_harvest_wave3_dirty_stale_20260721",
            "task://snapdup_cert_fallback_codex_usage_limit_20260721"
            "#description-worktree-harvest-batch",
        ),
    },
    "k1707_pseudo_stress_branch_path_collision_20260721": {
        "parent_task_id": FieldEvidence(
            None,
            "task://k1707_pseudo_stress_branch_path_collision_20260721"
            "#description-worktree-harvest-batch",
            replace=True,
        ),
        "upstream_receipt_ref": FieldEvidence(
            "legacy-batch:worktree_harvest_wave3_dirty_stale_20260721",
            "task://k1707_pseudo_stress_branch_path_collision_20260721"
            "#description-worktree-harvest-batch",
        ),
    },
    "K1438_vix1d_spy_intraday_vol_covariate": {
        "claimed_by": FieldEvidence(
            None,
            "task://K1438_vix1d_spy_intraday_vol_covariate"
            "#blocked_note-data-unavailable",
            replace=True,
            expected="hourly-slot-1-805f4d4c32b442af8ed385c83b595ce3",
        ),
        "claimed_at": FieldEvidence(
            None,
            "task://K1438_vix1d_spy_intraday_vol_covariate"
            "#status_history-reopened-claim",
            replace=True,
            expected="2026-07-21T09:36:35.216554+00:00",
        ),
        "started_at": FieldEvidence(
            None,
            "task://K1438_vix1d_spy_intraday_vol_covariate"
            "#status_history-reopened-start",
            replace=True,
            expected="2026-07-21T09:36:36.312051+00:00",
        ),
        "completed_at": FieldEvidence(
            None,
            "task://K1438_vix1d_spy_intraday_vol_covariate"
            "#historical-terminal-trace-precedes-reopen",
            replace=True,
            expected="2026-06-09T10:28:11.725039+00:00",
        ),
    },
    "K1715": {
        "status": FieldEvidence(
            "awaiting_agent_job",
            "file:storage/ops/compute_queue/"
            "agent-brief_k1715_adjudicate-27247d.json#status",
            replace=True,
            expected="in_progress",
        ),
        "blocked_reason": FieldEvidence(
            "external_compute_receipt_pending_collection",
            "file:storage/ops/compute_queue/"
            "agent-brief_k1715_adjudicate-27247d.json#completed_at",
        ),
        "external_execution_ref": FieldEvidence(
            "storage/ops/compute_queue/"
            "agent-brief_k1715_adjudicate-27247d.json",
            "file:storage/ops/compute_queue/"
            "agent-brief_k1715_adjudicate-27247d.json#id",
        ),
    },
    "k_reruns_0050_snapshot_contaminated_20260719": {
        "blocked_reason": FieldEvidence(
            "awaiting_prerequisite_fix",
            "task://k_reruns_0050_snapshot_contaminated_20260719"
            "#result-detect_price_split_breaks_false_negative",
        ),
    },
}
REVIEWED_TARGET_IDS = frozenset(
    {
        *REVIEWED_GIT_EVIDENCE,
        *REVIEWED_FIELD_EVIDENCE,
        "issue9_shadow_reconciliation_closure_20260727",
    }
)


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:  # silent-ok: caller treats malformed timestamps as absent evidence.
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _earliest_lifecycle_evidence(task: Mapping[str, Any]) -> tuple[str, str] | None:
    candidates: list[tuple[datetime, str, str]] = []
    for field in LIFECYCLE_FIELDS:
        raw = task.get(field)
        parsed = _aware_datetime(raw)
        if parsed is not None:
            candidates.append((parsed, field, raw))
    if not candidates:
        return None
    _when, field, raw = min(candidates, key=lambda item: item[0])
    return field, raw


def migrate_records(
    tasks: list[Any],
    *,
    git_evidence: Mapping[str, GitEvidence],
    target_ids: frozenset[str] | None = None,
    reviewed_fields: Mapping[
        str, Mapping[str, FieldEvidence]
    ] = REVIEWED_FIELD_EVIDENCE,
) -> list[dict[str, Any]]:
    """Mutate invalid rows using evidence, failing closed if any row is unproven."""

    changes: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if target_ids is not None and task.get("id") not in target_ids:
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ProvenanceMigrationError("invalid row without task id cannot be migrated")

        if (
            _aware_datetime(task.get("created_at")) is None
            and _aware_datetime(task.get("created_at_observed_not_after"))
            is None
        ):
            original = task.get("created_at")
            lifecycle = _earliest_lifecycle_evidence(task)
            if lifecycle is not None:
                field, replacement = lifecycle
                evidence = {"kind": "lifecycle", "field": field}
                migration_metadata = {
                    "method": "lifecycle_observation_upper_bound",
                    "evidence_field": field,
                }
            else:
                git_item = git_evidence.get(task_id)
                if (
                    git_item is None
                    or _aware_datetime(git_item.committed_at) is None
                ):
                    raise ProvenanceMigrationError(
                        f"{task_id}: missing timezone-aware lifecycle or "
                        "reviewed Git evidence"
                    )
                replacement = git_item.committed_at
                evidence = {"kind": "git", "commit": git_item.commit}
                migration_metadata = {
                    "method": "reviewed_git_snapshot_observation",
                    "evidence_commit": git_item.commit,
                }

            if original is not None:
                task["created_at_original"] = original
                task.pop("created_at", None)
            task["created_at_observed_not_after"] = replacement
            task["creation_time_evidence"] = migration_metadata
            changes.append(
                {
                    "id": task_id,
                    "field": "created_at_observed_not_after",
                    "from": original,
                    "to": replacement,
                    "evidence": evidence,
                }
            )

        for field, item in reviewed_fields.get(task_id, {}).items():
            current = task.get(field)
            if item.expected is not _UNSET and current != item.expected:
                raise ProvenanceMigrationError(
                    f"{task_id}.{field}: reviewed preimage drift "
                    f"({current!r} != {item.expected!r})"
                )
            if not item.replace and current is not None and current != "":
                continue
            if item.replace and current == item.value:
                continue
            if item.replace and current is not None:
                task[f"{field}_original"] = current
            if item.value is None:
                task.pop(field, None)
            else:
                task[field] = item.value
            migration_log = task.setdefault("provenance_migration", {})
            migration_log[field] = {
                "method": "reviewed_field_backfill",
                "evidence_ref": item.evidence_ref,
            }
            changes.append(
                {
                    "id": task_id,
                    "field": field,
                    "from": current,
                    "to": item.value,
                    "evidence": {
                        "kind": "reviewed_field",
                        "ref": item.evidence_ref,
                    },
                }
            )
    return changes


def verify_reviewed_git_evidence(
    evidence: Mapping[str, GitEvidence] = REVIEWED_GIT_EVIDENCE,
) -> dict[str, GitEvidence]:
    """Verify each reviewed commit snapshot really contains its asserted task."""

    verified: dict[str, GitEvidence] = {}
    for task_id, item in evidence.items():
        payload = subprocess.run(
            ["git", "show", f"{item.commit}:storage/next_tasks.json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        rows = json.loads(payload)
        if not any(isinstance(row, dict) and row.get("id") == task_id for row in rows):
            raise ProvenanceMigrationError(
                f"{task_id}: not present in reviewed Git snapshot {item.commit}"
            )
        actual_commit_time = subprocess.run(
            ["git", "show", "-s", "--format=%cI", item.commit],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual_commit_time != item.committed_at:
            raise ProvenanceMigrationError(
                f"{task_id}: reviewed commit time drift "
                f"({item.committed_at!r} != {actual_commit_time!r})"
            )
        verified[task_id] = item
    return verified


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def intent_path_for(receipt_path: Path) -> Path:
    return receipt_path.with_name(f"{receipt_path.name}.intent.json")


def _create_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = _load_object(path)
            identity_fields = (
                "schema_version",
                "migration",
                "before_sha256",
                "after_sha256",
                "intent_sha256",
            )
            if any(
                key in payload and existing.get(key) != payload.get(key)
                for key in identity_fields
            ):
                raise ProvenanceMigrationError(
                    f"{path}: immutable receipt identity conflict"
                )
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProvenanceMigrationError(f"{path}: expected a JSON object")
    return payload


def _serialized_tasks(tasks: list[Any]) -> tuple[list[Any], bytes]:
    normalized = copy.deepcopy(tasks)
    buffer = io.StringIO()
    write_tasks_to_handle(buffer, normalized)
    return normalized, buffer.getvalue().encode("utf-8")


def _validate_completion_receipt(
    receipt: Mapping[str, Any],
    *,
    intent_path: Path,
) -> None:
    intent = _load_object(intent_path)
    expected = {
        "migration": intent.get("migration"),
        "before_sha256": intent.get("before_sha256"),
        "after_sha256": intent.get("after_sha256"),
        "intent_sha256": _sha256(intent_path.read_bytes()),
    }
    mismatches = {
        field: (receipt.get(field), value)
        for field, value in expected.items()
        if receipt.get(field) != value
    }
    if mismatches:
        raise ProvenanceMigrationError(
            f"completion receipt does not match durable intent: {mismatches}"
        )


def _preserve_torn_receipt(path: Path) -> Path:
    digest = _sha256(path.read_bytes())
    preserved = path.with_name(f"{path.name}.corrupt-{digest}.json")
    try:
        os.link(path, preserved)
    except FileExistsError:
        if preserved.read_bytes() != path.read_bytes():
            raise ProvenanceMigrationError(
                f"{path}: corrupt receipt preservation collision"
            )
    path.unlink()
    return preserved


def run(
    *,
    path: Path = NEXT_TASKS,
    apply: bool = False,
    receipt_path: Path = DEFAULT_RECEIPT,
    fail_after_queue_write: bool = False,
) -> dict[str, Any]:
    intent_path = intent_path_for(receipt_path)
    if apply and receipt_path.exists():
        try:
            existing_receipt = _load_object(receipt_path)
            _validate_completion_receipt(
                existing_receipt,
                intent_path=intent_path,
            )
        except (json.JSONDecodeError, ProvenanceMigrationError):
            if not intent_path.exists():
                raise
            _preserve_torn_receipt(receipt_path)
        else:
            return existing_receipt
    verified = verify_reviewed_git_evidence()
    prepared_intent: dict[str, Any] | None = None
    recovered_from_intent = False
    with path.open("r+" if apply else "r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if apply else fcntl.LOCK_SH)
        try:
            before_bytes = handle.read().encode("utf-8")
            tasks = json.loads(before_bytes)
            if not isinstance(tasks, list):
                raise ProvenanceMigrationError("next_tasks root must be a list")
            current_sha = _sha256(before_bytes)
            expected_after: Any = None
            if apply and intent_path.exists():
                prepared_intent = _load_object(intent_path)
                expected_before = prepared_intent.get("before_sha256")
                expected_after = prepared_intent.get("after_sha256")
                if current_sha == expected_after:
                    recovered_from_intent = True
                    changes = list(prepared_intent.get("changes") or [])
                    proposed_tasks = tasks
                    proposed_bytes = before_bytes
                    proposed_sha = current_sha
                elif current_sha != expected_before:
                    raise ProvenanceMigrationError(
                        "queue drifted away from both prepared intent hashes"
                    )
            if not (apply and current_sha == expected_after):
                proposed_tasks = copy.deepcopy(tasks)
                changes = migrate_records(
                    proposed_tasks,
                    git_evidence=verified,
                    target_ids=REVIEWED_TARGET_IDS,
                    reviewed_fields=REVIEWED_FIELD_EVIDENCE,
                )
                proposed_tasks, proposed_bytes = _serialized_tasks(
                    proposed_tasks
                )
                proposed_sha = _sha256(proposed_bytes)

            if apply and prepared_intent is not None and current_sha != expected_after:
                if (
                    proposed_sha != expected_after
                    or changes != prepared_intent.get("changes")
                ):
                    raise ProvenanceMigrationError(
                        "prepared migration intent no longer reproduces"
                    )
                recovered_from_intent = True
            elif apply and prepared_intent is None:
                prepared_intent = {
                    "schema_version": 1,
                    "migration": "task_pool_creation_provenance_v2",
                    "prepared_at": datetime.now(UTC).isoformat(),
                    "queue_path": str(path.resolve()),
                    "before_sha256": current_sha,
                    "after_sha256": proposed_sha,
                    "changes": changes,
                    "reviewed_git_evidence": {
                        task_id: asdict(item)
                        for task_id, item in sorted(verified.items())
                    },
                }
                _create_immutable_json(intent_path, prepared_intent)

            if apply and current_sha != proposed_sha:
                handle.seek(0)
                write_tasks_to_handle(handle, proposed_tasks)
                handle.flush()
                os.fsync(handle.fileno())
                handle.seek(0)
                after_bytes = handle.read().encode("utf-8")
                if _sha256(after_bytes) != proposed_sha:
                    raise ProvenanceMigrationError(
                        "canonical writer output disagrees with prepared intent"
                    )
            elif not apply:
                after_bytes = proposed_bytes
            else:
                after_bytes = before_bytes
            if apply and fail_after_queue_write:
                raise InjectedMigrationCrash("after durable queue write")
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "migration": "task_pool_creation_provenance_v2",
        "mode": "apply" if apply else "dry_run",
        "recorded_at": datetime.now(UTC).isoformat(),
        "queue_path": str(path.resolve()),
        "before_sha256": _sha256(before_bytes),
        "after_sha256": _sha256(after_bytes),
        "changes": changes,
        "recovered_from_intent": recovered_from_intent,
        "reviewed_git_evidence": {
            task_id: asdict(item) for task_id, item in sorted(verified.items())
        },
    }
    if apply:
        if prepared_intent is None:
            raise ProvenanceMigrationError("apply completed without durable intent")
        receipt["before_sha256"] = prepared_intent["before_sha256"]
        receipt["after_sha256"] = prepared_intent["after_sha256"]
        receipt["changes"] = prepared_intent["changes"]
        receipt["intent_path"] = str(intent_path.resolve())
        receipt["intent_sha256"] = _sha256(intent_path.read_bytes())
        _create_immutable_json(receipt_path, receipt)
        receipt = _load_object(receipt_path)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the queue and receipt")
    parser.add_argument("--path", type=Path, default=NEXT_TASKS)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    receipt = run(path=args.path, apply=args.apply, receipt_path=args.receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
