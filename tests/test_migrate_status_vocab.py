"""Tests for the one-time WS-A3 vocab migration (scripts/migrate_status_vocab.py).

Covers: value-level and row-level status mapping with original preservation,
blocked_reason mapping with note backfill, ambiguity -> needs_review (never
force-converted), idempotency, full convergence against the real queue, and
the all-or-nothing baseline-constant flip.
"""
from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import pytest

from volpred.ops import next_tasks as nt

migrate = importlib.import_module("scripts.migrate_status_vocab")

ROOT = Path(__file__).resolve().parents[1]
REAL_NEXT_TASKS = ROOT / "storage" / "next_tasks.json"


# ------------------------------------------------------------- value mapping --

def test_value_map_converts_and_preserves_original():
    tasks = [
        {"id": "a1", "status": "completed", "priority": 3},
        {"id": "a2", "status": "superseded_audience_null_fix", "priority": 4},
        {"id": "a3", "status": "completed_null", "priority": 3},
        {"id": "a4", "status": "fail_no_data_data_source_blocker", "priority": 2},
        {"id": "a5", "status": "dropped_false_positive", "priority": 4},
        {"id": "ok", "status": "pending", "priority": 3},
    ]
    report = migrate.migrate_tasks(tasks, now_iso="2026-07-20T00:00:00+00:00")

    assert report["n_status_mapped"] == 5
    by_id = {t["id"]: t for t in tasks}
    assert by_id["a1"]["status"] == "succeeded"
    assert by_id["a1"]["status_original"] == "completed"
    assert by_id["a1"]["vocab_migrated_at"] == "2026-07-20T00:00:00+00:00"
    assert by_id["a2"]["status"] == "superseded"
    assert by_id["a3"]["status"] == "succeeded_null_result"
    assert by_id["a4"]["status"] == "failed"
    assert by_id["a5"]["status"] == "closed_no_action"
    # untouched in-vocab row
    assert by_id["ok"]["status"] == "pending"
    assert "status_original" not in by_id["ok"]
    # every target is in-vocab
    for t in tasks:
        assert nt.is_valid_status(t["status"])


def test_row_map_requires_expected_original_else_needs_review():
    # right id, WRONG original status -> not converted, parked for review
    tasks = [{"id": "rewrite_mile_0c1f9687_citation_fix", "status": "partially_completed"}]
    report = migrate.migrate_tasks(tasks)
    assert report["n_status_mapped"] == 0
    assert tasks[0]["status"] == "partially_completed"
    assert len(report["needs_review"]) == 1
    assert "expected original" in report["needs_review"][0]["reason"]


def test_row_map_converts_partial_rows_with_rationale():
    tasks = [
        {"id": "rewrite_mile_0c1f9687_citation_fix", "status": "partial"},
        {"id": "paper3_vt_fix_review_v2_5HIGH", "status": "partial_success"},
    ]
    report = migrate.migrate_tasks(tasks)
    assert report["n_status_mapped"] == 2
    assert tasks[0]["status"] == "failed"
    assert tasks[0]["status_original"] == "partial"
    assert "vocab_migration_rationale" in tasks[0]
    assert tasks[1]["status"] == "succeeded"


def test_unmapped_out_of_vocab_value_is_never_force_converted():
    tasks = [{"id": "mystery", "status": "some_new_pollution"}]
    report = migrate.migrate_tasks(tasks)
    assert report["n_status_mapped"] == 0
    assert tasks[0]["status"] == "some_new_pollution"
    assert report["needs_review"] == [
        {"id": "mystery", "field": "status", "value": "some_new_pollution",
         "reason": "no mapping defined -- not force-converted"}
    ]


# ------------------------------------------------------- blocked_reason rows --

def test_blocked_reason_row_map_preserves_original_and_backfills_note():
    free_text = "Awaiting owner sign-off on narrative reframe (email 9adb9e49)"
    tasks = [
        {"id": "paper2_taiwan_vt_rolling_block_reestimate",
         "status": "blocked_on_user", "blocked_reason": free_text},
        {"id": "fable0711_abm_honesty_pass", "status": "blocked",
         "blocked_reason": "decomposed_into_subtasks",
         "blocked_note": "already has a note"},
    ]
    report = migrate.migrate_tasks(tasks)
    assert report["n_blocked_reason_mapped"] == 2
    assert tasks[0]["blocked_reason"] == "awaiting_owner_decision"
    assert tasks[0]["blocked_reason_original"] == free_text
    assert tasks[0]["blocked_note"] == free_text, "empty note backfilled with original"
    assert tasks[1]["blocked_reason"] == "deprecated"
    assert tasks[1]["blocked_note"] == "already has a note", "existing note untouched"
    for t in tasks:
        assert nt.is_valid_blocked_reason(t["blocked_reason"])


def test_dispatch_remediation_pollution_rows_converge_with_provenance():
    free_text = "worker=success; workspace=remediation_opened; main_sha="
    tasks = [
        {
            "id": task_id,
            "status": "blocked",
            "blocked_reason": free_text,
            "blocked_until": "2026-08-11T13:07:51+00:00",
            "result": free_text,
        }
        for task_id in ("ci-red-30339013855", "ci-red-30361505394")
    ]

    report = migrate.migrate_tasks(
        tasks, now_iso="2026-07-29T00:00:00+00:00"
    )

    assert report["n_blocked_reason_mapped"] == 2
    assert report["needs_review"] == []
    for task in tasks:
        assert task["blocked_reason"] == "awaiting_prerequisite_fix"
        assert task["blocked_reason_original"] == free_text
        assert task["blocked_note"] == free_text
        assert task["result"] == free_text
        assert task["blocked_until"] == "2026-08-11T13:07:51+00:00"
        assert task["vocab_migrated_at"] == "2026-07-29T00:00:00+00:00"


def test_in_vocab_blocked_reason_is_untouched():
    tasks = [{"id": "K1330", "status": "succeeded", "blocked_reason": "awaiting_codex_review"}]
    report = migrate.migrate_tasks(tasks)
    assert report["n_blocked_reason_mapped"] == 0
    assert tasks[0]["blocked_reason"] == "awaiting_codex_review"
    assert "blocked_reason_original" not in tasks[0]


# ------------------------------------------------------------- idempotency --

def test_migration_is_idempotent():
    tasks = [
        {"id": "a1", "status": "completed", "priority": 3},
        {"id": "fable0711_abm_honesty_pass", "status": "blocked",
         "blocked_reason": "decomposed_into_subtasks"},
    ]
    first = migrate.migrate_tasks(tasks, now_iso="2026-07-20T00:00:00+00:00")
    assert first["n_status_mapped"] == 1
    assert first["n_blocked_reason_mapped"] == 1
    snapshot = json.dumps(tasks, sort_keys=True)
    second = migrate.migrate_tasks(tasks, now_iso="2026-07-21T00:00:00+00:00")
    assert second["n_status_mapped"] == 0
    assert second["n_blocked_reason_mapped"] == 0
    assert json.dumps(tasks, sort_keys=True) == snapshot, "second run must not touch rows"


# --------------------------------------------------- real-queue convergence --

@pytest.mark.real_queue
def test_dry_run_on_real_queue_copy_converges_to_zero_residue(tmp_path):
    """The mapping tables must cover the ENTIRE frozen population: running the
    migration on a copy of the canonical queue leaves zero out-of-vocab
    statuses and zero out-of-vocab blocked_reasons (needs_review empty)."""
    copy = tmp_path / "next_tasks.json"
    shutil.copyfile(REAL_NEXT_TASKS, copy)
    tasks = json.loads(copy.read_text(encoding="utf-8"))
    before = migrate._residual_counts(tasks)
    migrated_at = "2026-07-21T00:00:00+00:00"
    report = migrate.migrate_tasks(tasks, now_iso=migrated_at)
    after = migrate._residual_counts(tasks)
    assert after == (0, 0), (
        f"residue {after} after migration (before {before}); "
        f"needs_review={report['needs_review']}"
    )
    assert report["needs_review"] == []
    # Every row converted by *this invocation* kept its invalid original value.
    # Historical provenance may legitimately contain a value that later became
    # canonical (for example K1715's earlier in_progress transition).
    for t in tasks:
        if (
            isinstance(t, dict)
            and t.get("vocab_migrated_at") == migrated_at
            and "status_original" in t
        ):
            assert not nt.is_valid_status(t["status_original"])
            assert nt.is_valid_status(t["status"])


# ------------------------------------------------------------ baseline flip --

def _stage_tmp_root(tmp_path: Path) -> Path:
    for rel, _ in migrate._BASELINE_EDITS:
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return tmp_path


def test_update_baselines_flips_all_six_constants(tmp_path):
    root = _stage_tmp_root(tmp_path)
    files = migrate.update_baselines(root, status_count=0, reason_count=0)
    assert len(files) == 3
    nt_text = (root / "src/volpred/ops/next_tasks.py").read_text(encoding="utf-8")
    assert "\nLEGACY_OUT_OF_VOCAB_BASELINE = 0\n" in nt_text
    assert "\nLEGACY_OUT_OF_VOCAB_BLOCKED_REASON_BASELINE = 0\n" in nt_text
    v_text = (root / "scripts/validate_next_tasks_status.py").read_text(encoding="utf-8")
    assert "\nDEFAULT_BASELINE = 0\n" in v_text
    assert "\nDEFAULT_BLOCKED_REASON_BASELINE = 0\n" in v_text
    t_text = (root / "tests/test_task_status_vocab.py").read_text(encoding="utf-8")
    assert "\nBASELINE = 0\n" in t_text
    assert "\nBLOCKED_REASON_BASELINE = 0\n" in t_text
    # the untouched sibling constant must survive
    assert "BLOCKED_NO_UNTIL_BASELINE = 0" in t_text


def test_update_baselines_aborts_all_or_nothing_when_pattern_missing(tmp_path):
    root = _stage_tmp_root(tmp_path)
    target = root / "tests/test_task_status_vocab.py"
    original_validator = (root / "scripts/validate_next_tasks_status.py").read_text(encoding="utf-8")
    target.write_text(
        target.read_text(encoding="utf-8").replace("BLOCKED_REASON_BASELINE = ", "RENAMED = "),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        migrate.update_baselines(root, status_count=0, reason_count=0)
    # earlier files in the edit list must NOT have been written (no partial flip)
    assert (root / "scripts/validate_next_tasks_status.py").read_text(encoding="utf-8") == original_validator
