"""The direction doc must stay machine-checkable, not drift back into free prose.

Regression guard for email-12157 (2026-07-18): the boss asked whether the roadmap
items in his 4-hourly report were ever reconciled. They were not -- the doc had sat
unchanged for 26 days claiming "1-2 weeks to P1 MVP" with zero backing tasks, and
nothing could have noticed, because prose has no status field.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import audit_roadmap_coverage as roadmap  # noqa: E402
from audit_roadmap_coverage import DOC, audit, parse_doc, resolve  # noqa: E402


def test_direction_doc_items_are_all_marker_bound():
    """Every roadmap bullet carries a rid/task marker -- no unbindable prose items."""
    updated, items = parse_doc(DOC.read_text(encoding="utf-8"))
    assert updated is not None, "doc must carry **Updated**: YYYY-MM-DD"
    assert items, "doc has no marker-bound roadmap items -- reconcile is toothless"
    assert len({i["rid"] for i in items}) == len(items), "duplicate rid in doc"


@pytest.mark.real_queue
def test_p1_items_have_live_backing_tasks():
    """A P1 the boss reads as active must exist in the pool. This is the actual gate."""
    report = audit()
    p1_gaps = [f for f in report["findings"] if f["kind"].startswith("p1_")]
    assert not p1_gaps, f"P1 roadmap items with no live task: {p1_gaps}"


def test_stale_doc_is_reported():
    """A doc that stops being updated must surface, since it keeps being mailed out."""
    updated, _ = parse_doc("**Updated**: 2026-06-22\n")
    assert (date(2026, 7, 18) - updated).days == 26


def test_missing_task_id_classified_as_no_task_not_live():
    """`task:none` means not started -- it must never render as progress."""
    items = [{"rid": "x", "task_id": None, "priority": "P2", "section": "s", "text": "t"}]
    assert resolve(items, {}, date(2026, 7, 18))[0]["coverage"] == "no_task"


def test_dangling_task_id_is_not_reported_as_live():
    """A doc pointing at a deleted task is a gap, not coverage."""
    items = [{"rid": "x", "task_id": "gone_123", "priority": "P1", "section": "s", "text": "t"}]
    assert resolve(items, {}, date(2026, 7, 18))[0]["coverage"] == "dangling"


def test_direct_mode_suspends_bound_rows_but_not_task_none():
    items = [
        {
            "rid": "bound",
            "task_id": "removed",
            "priority": "P1",
            "section": "s",
            "text": "t",
        },
        {
            "rid": "never-bound",
            "task_id": None,
            "priority": "P1",
            "section": "s",
            "text": "t",
        },
    ]

    resolved = resolve(
        items,
        {},
        date(2026, 7, 18),
        direct_execution=True,
    )

    assert resolved[0]["coverage"] == "pool_suspended"
    assert resolved[1]["coverage"] == "no_task"


def test_direct_mode_requires_a_complete_backup_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    state = tmp_path / "task_pool_mode.json"
    state.write_text(
        json.dumps({"enabled": True, "mode": "direct_execution"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(roadmap, "TASK_POOL_MODE", state)

    with pytest.raises(ValueError, match="complete backup receipt"):
        roadmap._execution_context()


def test_closed_task_flags_doc_for_update():
    """Finished work should leave the roadmap, so a succeeded task is a doc-drift signal."""
    items = [{"rid": "x", "task_id": "t1", "priority": "P2", "section": "s", "text": "t"}]
    pool = {"t1": {"id": "t1", "status": "succeeded"}}
    assert resolve(items, pool, date(2026, 7, 18))[0]["coverage"] == "closed"
