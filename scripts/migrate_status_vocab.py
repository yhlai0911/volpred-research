#!/usr/bin/env python3
"""One-time WS-A3 migration: map polluted next_tasks terminal statuses and
out-of-vocab blocked_reason values back to the controlled vocabularies.

Context (docs/refactor_plan_ops_master_2026_07.md WS-A3): before the vocab gate
existed, 15 writers each json.dump-ed storage/next_tasks.json with no shared
status check, accumulating 27 free-text terminal statuses (completed x11,
superseded_audience_null_fix x5, a long one-off tail) plus 3 out-of-vocab
blocked_reason values. The PROCESS is fixed first (all writers on the canonical
helper since A1b; strict validate_task_status / validate_blocked_reason; audits
in write_tasks_to_handle; CI gate in scripts/validate_next_tasks_status.py).
This script is the one-time data convergence that follows the process fix,
per 「永遠修流程，不修資料 -- 一次性 migration 只在流程修復後做、且記錄原值」.

Every converted row preserves its exact original value in
``status_original`` / ``blocked_reason_original`` plus a ``vocab_migrated_at``
timestamp, so no evidence is destroyed. Ambiguous rows are NOT force-converted:
anything not covered by the maps below lands on the needs_review report and is
left untouched.

Usage:
    # rehearse against a scratch copy (never writes):
    uv run python scripts/migrate_status_vocab.py --path /tmp/queue_copy.json

    # real apply on the canonical queue (main thread, post-merge) + flip the
    # three mirrored baseline constants to the post-migration residue:
    uv run python scripts/migrate_status_vocab.py --apply --update-baselines

Idempotent: a second run maps 0 rows (all values already in-vocab).
After apply, run the validator + vocab tests before committing:
    uv run python scripts/validate_next_tasks_status.py
    uv run pytest tests/test_task_status_vocab.py tests/test_task_pool_claim.py -q
Archive candidate once the baselines read 0 in CI (keep for provenance).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

from volpred.ops.next_tasks import (  # noqa: E402
    is_valid_blocked_reason,
    is_valid_status,
    validate_blocked_reason,
    validate_task_status,
    write_tasks_locked,
)

# --------------------------------------------------------------- mapping table
# Value-level map: unambiguous free-text terminal statuses -> controlled vocab.
# Semantics adjudicated 2026-07-20 against the actual rows (all evidence in the
# rows themselves; see also the per-row map below for the partial* tail).
STATUS_VALUE_MAP: dict[str, str] = {
    # plain synonyms for "done, real result"
    "completed": "succeeded",
    "completed_local": "succeeded",          # work done locally; platform sync tracked separately in row findings
    # explicit null-result completion (K1387 verdict=NULL)
    "completed_null": "succeeded_null_result",
    # superseded variants
    "superseded_audience_null_fix": "superseded",
    "phase1_failed_codex_review_superseded_by_v2": "superseded",
    "setup_done_superseded_by_v2": "superseded",
    # genuine failure (GDELT bulk source had no usable data)
    "fail_no_data_data_source_blocker": "failed",
    # task itself was a false positive (K400 came from a range expression) --
    # closed with nothing to do
    "dropped_false_positive": "closed_no_action",
}

# Per-row map for values too ambiguous to convert by value alone
# ("partial*" tail). Key: task id. Value: (expected_original_status, target,
# rationale). The rationale is the recorded adjudication evidence; the row is
# only converted when its current status still equals the expected original.
STATUS_ROW_MAP: dict[str, tuple[str, str, str]] = {
    "Paper_folders_backfill_selfcontained": (
        "partially_completed",
        "succeeded",
        "Committed batch delivered (Paper 9 + Paper 4 self-contained indexes, "
        "commits 5b785551/3ba96c4b recorded in-row); remainder explicitly "
        "re-scoped in-row to later checkpoints (body drafting / pre-submission "
        "completeness check). Partial-scope close with real durable output.",
    ),
    "VolAbsorption_missing_scripts_recovery": (
        "partially_completed",
        "succeeded",
        "Core deliverable done per in-row DONE note (commit 86d10c7b: 7 scripts "
        "reconstructed; K716 MATCHED within 1%, K717-K722 approximate with all "
        "qualitative findings confirmed). Residual divergences documented "
        "honestly in-row, not hidden.",
    ),
    "rewrite_mile_0c1f9687_citation_fix": (
        "partial",
        "failed",
        "Primary purpose (Harvey citation research-integrity fix) explicitly "
        "NOT achieved per findings (sanitizer corrupted the citation; "
        "structural follow-up queued). Secondary items landing does not make "
        "the task's stated goal met.",
    ),
    "paper3_vt_fix_review_v2_5HIGH": (
        "partial_success",
        "succeeded",
        "3/5 HIGH fixes delivered here; remaining 2 explicitly re-tasked as "
        "K1371/K1372 per in-row notes -- this row's own share completed with "
        "successor tasks owning the rest.",
    ),
    "Paper2_G12_G20_Section6_formal_experiments": (
        "partially_resolved_K1180_done_awaiting_K1179",
        "succeeded",
        "Awaited condition has since completed: experiments/k1179 AND "
        "experiments/k1180 both exist with results + diff audits "
        "(k1179_vs_paper2_section6_1_diff.md verdict NO_MATCH 0/3, k1180 3/5). "
        "The task's deliverable was the formal experiments + replication "
        "audit, which is complete; the surfaced divergence is a real recorded "
        "finding, and paper-side correction is tracked separately "
        "(paper2_taiwan_vt_rolling_block_reestimate).",
    ),
}

# Rows deliberately NOT converted (kept out-of-vocab with a recorded reason).
# Empty after the 2026-07-20 adjudication -- all 27 rows had decidable
# evidence -- but the mechanism stays so a future re-run can park rows here
# instead of force-converting.
STATUS_NEEDS_REVIEW: dict[str, str] = {}

# Out-of-vocab blocked_reason rows. Key: task id. Value: (target, rationale).
# Only applied when the row's current blocked_reason is set and out-of-vocab
# (idempotent). Original preserved in blocked_reason_original; free-text
# originals are additionally copied to blocked_note when the row has none, so
# the human-readable context stays on the row surface.
# NOTE: K1330's `awaiting_codex_review` needs no migration -- it was written by
# the sanctioned sync_next_tasks_status.py review-gate flow and is legitimized
# by adding it to BLOCKED_REASONS (process fix, not data fix).
BLOCKED_REASON_ROW_MAP: dict[str, tuple[str, str]] = {
    "experiment_scaffold_k400": (
        "deprecated",
        "Free-text explanation of why the task was invalid (K400 extracted "
        "from a range expression, not a real K-id; source filter fixed "
        "2026-05-08). Task no longer relevant -> deprecated.",
    ),
    "paper2_taiwan_vt_rolling_block_reestimate": (
        "awaiting_owner_decision",
        "Long free-text prose is an owner-sign-off wait (email 9adb9e49) on a "
        "status=blocked_on_user row -> the new canonical "
        "awaiting_owner_decision. Full prose (incl. corrected canonical "
        "values) preserved in blocked_reason_original + blocked_note.",
    ),
    "fable0711_abm_honesty_pass": (
        "deprecated",
        "Hand-written `decomposed_into_subtasks` (no sanctioned writer): "
        "parent superseded by abm_p0_1..5 subtasks for execution, kept as "
        "tracking row per its own blocked_note -> deprecated.",
    ),
}

BLOCKED_REASON_NEEDS_REVIEW: dict[str, str] = {}


# ------------------------------------------------------------------ migration

def migrate_tasks(tasks: list[Any], *, now_iso: str | None = None) -> dict[str, Any]:
    """Mutate ``tasks`` in place; return the migration report dict.

    Report keys: status_mapped (Counter-like dict "orig -> target": n),
    blocked_reason_mapped, needs_review (list of dicts), totals.
    """
    now = now_iso or datetime.now(timezone.utc).isoformat(timespec="seconds")
    status_mapped: dict[str, int] = {}
    reason_mapped: dict[str, int] = {}
    needs_review: list[dict[str, str]] = []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        tid = str(task.get("id") or "<no-id>")

        # ---- status ----
        status = task.get("status")
        if status is not None and not is_valid_status(status):
            target: str | None = None
            rationale = ""
            if tid in STATUS_NEEDS_REVIEW:
                needs_review.append(
                    {"id": tid, "field": "status", "value": str(status),
                     "reason": STATUS_NEEDS_REVIEW[tid]}
                )
            elif tid in STATUS_ROW_MAP:
                expected, target, rationale = STATUS_ROW_MAP[tid]
                if str(status) != expected:
                    needs_review.append(
                        {"id": tid, "field": "status", "value": str(status),
                         "reason": f"row-map expected original {expected!r}, found {status!r}"}
                    )
                    target = None
            elif str(status) in STATUS_VALUE_MAP:
                target = STATUS_VALUE_MAP[str(status)]
                rationale = "value-level map"
            else:
                needs_review.append(
                    {"id": tid, "field": "status", "value": str(status),
                     "reason": "no mapping defined -- not force-converted"}
                )
            if target is not None:
                validate_task_status(target)  # typo-proof: raise before touching the row
                task.setdefault("status_original", str(status))
                task["status"] = target
                task["vocab_migrated_at"] = now
                if rationale and rationale != "value-level map":
                    task.setdefault("vocab_migration_rationale", rationale)
                key = f"{status} -> {target}"
                status_mapped[key] = status_mapped.get(key, 0) + 1

        # ---- blocked_reason ----
        reason = task.get("blocked_reason")
        if isinstance(reason, str) and reason.strip() and not is_valid_blocked_reason(reason):
            if tid in BLOCKED_REASON_NEEDS_REVIEW:
                needs_review.append(
                    {"id": tid, "field": "blocked_reason", "value": reason[:80],
                     "reason": BLOCKED_REASON_NEEDS_REVIEW[tid]}
                )
            elif tid in BLOCKED_REASON_ROW_MAP:
                r_target, r_rationale = BLOCKED_REASON_ROW_MAP[tid]
                validate_blocked_reason(r_target)
                task.setdefault("blocked_reason_original", reason)
                if not str(task.get("blocked_note") or "").strip():
                    task["blocked_note"] = reason
                task["blocked_reason"] = r_target
                task["vocab_migrated_at"] = now
                task.setdefault("vocab_migration_rationale", r_rationale)
                key = f"{reason[:50]} -> {r_target}"
                reason_mapped[key] = reason_mapped.get(key, 0) + 1
            else:
                needs_review.append(
                    {"id": tid, "field": "blocked_reason", "value": reason[:80],
                     "reason": "no mapping defined -- not force-converted"}
                )

    return {
        "status_mapped": status_mapped,
        "blocked_reason_mapped": reason_mapped,
        "needs_review": needs_review,
        "n_status_mapped": sum(status_mapped.values()),
        "n_blocked_reason_mapped": sum(reason_mapped.values()),
    }


def _residual_counts(tasks: list[Any]) -> tuple[int, int]:
    n_status = sum(
        1 for t in tasks
        if isinstance(t, dict) and t.get("status") is not None and not is_valid_status(t.get("status"))
    )
    n_reason = sum(
        1 for t in tasks
        if isinstance(t, dict)
        and isinstance(t.get("blocked_reason"), str)
        and t.get("blocked_reason").strip()
        and not is_valid_blocked_reason(t.get("blocked_reason"))
    )
    return n_status, n_reason


# ------------------------------------------------------------ baseline flips

#: (file, [(line-anchored regex, template)]) -- each pattern must match exactly
#: once or the whole update aborts with no file touched.
_BASELINE_EDITS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "src/volpred/ops/next_tasks.py",
        [
            (r"^LEGACY_OUT_OF_VOCAB_BASELINE = \d+$",
             "LEGACY_OUT_OF_VOCAB_BASELINE = {status}"),
            (r"^LEGACY_OUT_OF_VOCAB_BLOCKED_REASON_BASELINE = \d+$",
             "LEGACY_OUT_OF_VOCAB_BLOCKED_REASON_BASELINE = {reason}"),
        ],
    ),
    (
        "scripts/validate_next_tasks_status.py",
        [
            (r"^DEFAULT_BASELINE = \d+$", "DEFAULT_BASELINE = {status}"),
            (r"^DEFAULT_BLOCKED_REASON_BASELINE = \d+$",
             "DEFAULT_BLOCKED_REASON_BASELINE = {reason}"),
        ],
    ),
    (
        "tests/test_task_status_vocab.py",
        [
            (r"^BASELINE = \d+$", "BASELINE = {status}"),
            (r"^BLOCKED_REASON_BASELINE = \d+$",
             "BLOCKED_REASON_BASELINE = {reason}"),
        ],
    ),
]


def update_baselines(root: Path, *, status_count: int, reason_count: int) -> list[str]:
    """Flip the mirrored baseline constants to the post-migration residue.

    All replacements are computed in memory first; any pattern matching != 1
    time aborts loudly before a single file is written (no partial flip).
    Returns the list of files rewritten.
    """
    staged: list[tuple[Path, str]] = []
    for rel, patterns in _BASELINE_EDITS:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        for pattern, template in patterns:
            new_line = template.format(status=status_count, reason=reason_count)
            text, n = re.subn(pattern, new_line, text, flags=re.MULTILINE)
            if n != 1:
                raise SystemExit(
                    f"[migrate-status-vocab] ABORT: pattern {pattern!r} matched "
                    f"{n} times in {path} (expected exactly 1); no files written"
                )
        staged.append((path, text))
    for path, text in staged:
        path.write_text(text, encoding="utf-8")
    return [str(p) for p, _ in staged]


# -------------------------------------------------------------------- report

def _print_report(report: dict[str, Any], before: tuple[int, int], after: tuple[int, int]) -> None:
    print("[migrate-status-vocab] status mappings:")
    for key, n in sorted(report["status_mapped"].items()):
        print(f"  {n:3d}  {key}")
    print(f"[migrate-status-vocab] status rows mapped: {report['n_status_mapped']}")
    print("[migrate-status-vocab] blocked_reason mappings:")
    for key, n in sorted(report["blocked_reason_mapped"].items()):
        print(f"  {n:3d}  {key}")
    print(f"[migrate-status-vocab] blocked_reason rows mapped: {report['n_blocked_reason_mapped']}")
    print(f"[migrate-status-vocab] needs_review: {len(report['needs_review'])}")
    for item in report["needs_review"]:
        print(f"  - {item['id']} [{item['field']}] {item['value']!r}: {item['reason']}")
    print(
        "[migrate-status-vocab] out-of-vocab residue: "
        f"status {before[0]} -> {after[0]}, blocked_reason {before[1]} -> {after[1]}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(NEXT_TASKS),
                    help="queue file (default: canonical; point at a copy to rehearse)")
    ap.add_argument("--apply", action="store_true",
                    help="write the migrated queue back (default: dry-run, no write)")
    ap.add_argument("--update-baselines", action="store_true",
                    help="after --apply, flip the mirrored baseline constants to the residue")
    args = ap.parse_args()

    if args.update_baselines and not args.apply:
        print("[migrate-status-vocab] --update-baselines requires --apply", file=sys.stderr)
        return 2

    path = Path(args.path)
    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[migrate-status-vocab] FAIL: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(tasks, list):
        print(f"[migrate-status-vocab] FAIL: {path} is not a list", file=sys.stderr)
        return 2

    before = _residual_counts(tasks)
    report = migrate_tasks(tasks)
    after = _residual_counts(tasks)
    _print_report(report, before, after)

    if not args.apply:
        print("[migrate-status-vocab] DRY-RUN: no write performed (use --apply)")
        return 0

    write_tasks_locked(path, tasks)
    print(f"[migrate-status-vocab] APPLIED: wrote {path}")

    if args.update_baselines:
        files = update_baselines(ROOT, status_count=after[0], reason_count=after[1])
        for f in files:
            print(f"[migrate-status-vocab] baseline flipped in {f}")
        print(
            "[migrate-status-vocab] now run: uv run python scripts/validate_next_tasks_status.py "
            "&& uv run pytest tests/test_task_status_vocab.py tests/test_task_pool_claim.py -q"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
