"""Re-pend paths must leave a task in a *clean* pending lifecycle.

Live symptom that produced this suite (2026-08-02): the Work Coordinator shadow
observer recorded ``invalid_lifecycle`` / "unclaimed status carries active claim
trace" for ``assign_ae004ae2`` at ``2026-08-02T08:15:48Z``, ten minutes after the
expiry sweeper re-pended it at ``08:05:18Z``.  That single blocking receipt reset
the Issue #9 seven-day clean soak from ``2026-08-03`` to ``2026-08-09``.

Root cause: ``task_pool_claim._repend_task`` documents itself as the "single
mutation site" for blocked/claimed -> pending, but that invariant is scoped to
one module.  Three other modules perform the same lifecycle transition with their
own field handling, and none of them cleared the claim-ownership markers.

These tests pin the *class*, not the one record.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from volpred.ops.next_tasks import (  # noqa: E402
    CLAIM_OWNERSHIP_FIELDS,
    clear_claim_ownership,
)
from volpred.ops.work.legacy import (  # noqa: E402
    LegacySnapshots,
    LegacySnapshotImporter,
)


def _load_script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _claimed_blocked_task(**overrides):
    """A row that was claimed, then blocked, and still carries the claim trace."""
    task = {
        "id": "task_under_test",
        "title": "claimed then blocked",
        "task_type": "platform_ops",
        "priority": 2,
        "status": "blocked",
        "source": "agent",
        "created_at": "2026-08-01T00:00:00+00:00",
        "blocked_reason": "awaiting_prerequisite_fix",
        "blocked_at": "2026-08-01T01:00:00+00:00",
        "blocked_until": "2026-08-01T02:00:00+00:00",
        "claimed_by": "hourly-slot-1-deadbeef",
        "claimed_at": "2026-08-01T00:30:00+00:00",
        "claim_session_id": "session-abc",
        "claim_expires_at": "2026-08-01T03:00:00+00:00",
        "started_at": "2026-08-01T00:31:00+00:00",
    }
    task.update(overrides)
    return task


# --------------------------------------------------------------------------
# 1. The canonical helper itself
# --------------------------------------------------------------------------


def test_clear_claim_ownership_removes_every_declared_field():
    task = _claimed_blocked_task()
    for field in CLAIM_OWNERSHIP_FIELDS:
        task.setdefault(field, "present")

    cleared = clear_claim_ownership(task)

    assert set(cleared) == set(CLAIM_OWNERSHIP_FIELDS)
    for field in CLAIM_OWNERSHIP_FIELDS:
        assert field not in task, f"{field} survived clear_claim_ownership"
    # Non-ownership state is untouched: clearing ownership is not a status change.
    assert task["status"] == "blocked"
    assert task["blocked_reason"] == "awaiting_prerequisite_fix"


def test_clear_claim_ownership_is_idempotent_and_reports_only_what_it_removed():
    task = {"id": "x", "status": "pending", "started_at": "2026-08-01T00:00:00+00:00"}

    assert clear_claim_ownership(task) == ("started_at",)
    assert clear_claim_ownership(task) == ()


def test_claim_ownership_fields_cover_every_field_the_reconciler_inspects():
    """The helper must clear at least what work.legacy flags as a claim trace."""
    # volpred.ops.work.legacy: pending/awaiting_approval rows are rejected when
    # any of these is not None.
    reconciler_inspected = {"claimed_by", "claimed_at", "started_at"}
    assert reconciler_inspected <= set(CLAIM_OWNERSHIP_FIELDS)


# --------------------------------------------------------------------------
# 2. Each re-pend path, bound to the live symptom via the real reconciler
# --------------------------------------------------------------------------


def _reconciliation_issues_for(task):
    """Run the real Work Coordinator reconciler over a one-row next_tasks snapshot."""
    report = LegacySnapshotImporter().import_snapshot(
        LegacySnapshots(next_tasks=(task,), task_records=(), ops_jobs=())
    )
    return [issue for issue in report.issues if issue.record_id == task["id"]]


def test_reconciler_rejects_a_pending_row_carrying_claim_trace():
    """Guard the guard: the assertion below must be able to fail."""
    dirty = _claimed_blocked_task(status="pending")
    dirty.pop("blocked_reason")
    dirty.pop("blocked_at")
    dirty.pop("blocked_until")

    issues = _reconciliation_issues_for(dirty)

    assert any(
        issue.code == "invalid_lifecycle"
        and "unclaimed status carries active claim trace" in issue.detail
        for issue in issues
    ), "reconciler no longer detects the 2026-08-02 symptom; this suite is blind"


def test_expiry_sweeper_repend_leaves_no_claim_trace(tmp_path, monkeypatch):
    """scripts/unblock_expired_blocked_tasks.py — the path that broke the soak."""
    module = _load_script("unblock_expired_blocked_tasks")
    task = _claimed_blocked_task()

    swept, gated = module._sweep_unblock([task], apply=True)

    assert [entry["id"] for entry in swept] == ["task_under_test"]
    assert gated == []
    assert task["status"] == "pending"
    assert _reconciliation_issues_for(task) == []


def test_mark_task_blocked_unblock_leaves_no_claim_trace():
    """scripts/mark_task_blocked.py --unblock — same transition, same duty."""
    import argparse

    module = _load_script("mark_task_blocked")
    task = _claimed_blocked_task()

    args = argparse.Namespace(
        id="task_under_test",
        unblock=True,
        reason=None,
        note=None,
        until=None,
        gate=None,
        incident=None,
    )
    assert module._mutate_tasks(args, [task]) == 0

    assert task["status"] == "pending"
    assert _reconciliation_issues_for(task) == []


def test_task_pool_claim_repend_still_leaves_no_claim_trace():
    """The one path that was already correct must stay correct after refactor."""
    module = _load_script("task_pool_claim")
    task = _claimed_blocked_task(status="claimed")
    task.pop("blocked_reason")
    task.pop("blocked_at")
    task.pop("blocked_until")

    module._repend_task(task, note="regression", reason="test")

    assert task["status"] == "pending"
    assert _reconciliation_issues_for(task) == []


def _compute_queue_tpc_stub():
    class Stub:
        TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "archived"}

        @staticmethod
        def _record_status_history(task, **kwargs):
            task.setdefault("status_history", []).append(dict(kwargs))

    return Stub()


def _compute_owned_task(*, job_id: str, blocked_reason: str):
    task = _claimed_blocked_task(
        status="awaiting_agent_job",
        blocked_reason=blocked_reason,
        compute_job_id=job_id,
    )
    task.pop("blocked_at", None)
    task.pop("blocked_until", None)
    return task


def test_compute_queue_collected_release_clears_claim_ownership():
    module = _load_script("compute_queue")
    task = _compute_owned_task(
        job_id="compute-job-1",
        blocked_reason="external_compute_receipt_pending_collection",
    )
    job = {
        "id": "compute-job-1",
        "source_task_id": "task_under_test",
        "status": "completed",
    }
    settlement = module._release_collected_source_task(
        task,
        job,
        next_task_id="followup-1",
        tpc=_compute_queue_tpc_stub(),
    )
    assert settlement and settlement["state"] == "pending_queue_commit"
    assert task["status"] == "pending"
    assert _reconciliation_issues_for(task) == []


def test_compute_queue_cancel_release_clears_claim_ownership():
    module = _load_script("compute_queue")
    task = _compute_owned_task(
        job_id="compute-job-2",
        blocked_reason="external_compute_job_active",
    )
    job = {
        "id": "compute-job-2",
        "source_task_id": "task_under_test",
        "cancel_reason": "operator_cancelled_test",
    }
    assert module._release_cancelled_source_task(
        task,
        job,
        tpc=_compute_queue_tpc_stub(),
    ) is True
    assert task["status"] == "pending"
    assert _reconciliation_issues_for(task) == []


# --------------------------------------------------------------------------
# 3. Mechanical class gate — a new re-pend site cannot silently reintroduce this
# --------------------------------------------------------------------------

#: Re-pend sites that are NOT yet routed through ``clear_claim_ownership``.
#: Each entry must name a live owner and a tracking issue; the gate asserts the
#: set is exactly this, so landing a fix forces the entry to be deleted rather
#: than letting it rot as a permanent exemption.
KNOWN_UNCONVERTED_REPEND_SITES: set[tuple[str, str]] = set()

#: Files whose ``status = "pending"`` assignments are queue-task lifecycle
#: transitions.  check_alerts.py is excluded on purpose: its ``notice["status"]``
#: rows are alert notices, not next_tasks rows.
_REPEND_SCRIPTS = (
    "scripts/unblock_expired_blocked_tasks.py",
    "scripts/mark_task_blocked.py",
    "scripts/task_pool_claim.py",
    "scripts/compute_queue.py",
)


def _repend_sites(path: Path):
    """Yield (function_name, calls_clear_helper) for each task status=pending write."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def enclosing_function(node):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current
            current = parents.get(current)
        return None

    seen = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Constant) and node.value.value == "pending"
        ):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            key = target.slice
            if not (isinstance(key, ast.Constant) and key.value == "status"):
                continue
            # notice["status"] = "pending" is an alert notice, not a queue task.
            if isinstance(target.value, ast.Name) and target.value.id == "notice":
                continue
            func = enclosing_function(node)
            if func is None:
                continue
            calls_helper = any(
                isinstance(inner, ast.Call)
                and (
                    (isinstance(inner.func, ast.Name)
                     and inner.func.id == "clear_claim_ownership")
                    or (isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "clear_claim_ownership")
                    # _repend_task is itself a converted wrapper.
                    or (isinstance(inner.func, ast.Name)
                        and inner.func.id == "_repend_task")
                    or (isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "_repend_task")
                )
                for inner in ast.walk(func)
            )
            seen[func.name] = seen.get(func.name, False) or calls_helper
    return seen


def test_every_repend_site_clears_claim_ownership():
    unconverted = set()
    for rel in _REPEND_SCRIPTS:
        path = REPO_ROOT / rel
        for func_name, converted in _repend_sites(path).items():
            if not converted:
                unconverted.add((rel, func_name))

    assert unconverted == KNOWN_UNCONVERTED_REPEND_SITES, (
        "re-pend sites drifted from the declared set.\n"
        f"  unconverted now: {sorted(unconverted)}\n"
        f"  declared       : {sorted(KNOWN_UNCONVERTED_REPEND_SITES)}\n"
        "A NEW entry means a re-pend path was added without clearing claim "
        "ownership (see 2026-08-02 Issue #9 soak reset). A MISSING entry means "
        "a tracked site was fixed -- delete it from "
        "KNOWN_UNCONVERTED_REPEND_SITES in the same commit."
    )


def test_repend_site_scanner_actually_finds_sites():
    """A scanner that silently matches nothing would make the gate vacuous."""
    found = _repend_sites(REPO_ROOT / "scripts" / "unblock_expired_blocked_tasks.py")
    assert found, "AST scanner found no status=pending site; the gate is vacuous"
