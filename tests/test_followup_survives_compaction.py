"""A follow-up declared at completion must outlive tombstone compaction.

Replays the 2026-07-28 loss. ``snapaudit_quantify_unmeasured_exposure`` succeeded
and put its one real loose end at the end of ``result``: the statistics-rerun
brief was written but never enqueued, because the agent read "free_slots=0" as
"cannot enqueue". Three days later ``compact_terminal_tasks`` tombstoned the row
and ``_TOMBSTONE_KEEP_FIELDS`` does not carry ``result``, so the sentence was
deleted. All three blockers cleared on their own over the next week; nothing went
back for it, and two published articles are still missing corrected numbers.

Two halves are pinned here, and the first is the load-bearing one:

* capture -- ``--follow-up`` turns the declaration into a real pending row inside
  the same locked write. Enqueueing takes no dispatch slot, so a saturated queue
  is never a reason to leave it in prose. Once it is a pending row it is its own
  evidence and no reader has to go excavating tombstones.
* survival -- the ``follow_ups`` edge is kept on the tombstone, so a compacted
  parent can still say what it spawned.

The gate on the success path is deliberately escapable in one flag. A miss costs
what the old behaviour cost; a false positive costs one flag. Anything stricter
would be a deadlock on the completion path (memory
``feedback_gates_smooth_no_deadlock``).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import task_pool_claim  # noqa: E402
from volpred.ops.next_tasks import (  # noqa: E402
    _TOMBSTONE_KEEP_FIELDS,
    compact_terminal_tasks,
)

# The real sentence, from storage/next_tasks_archive/2026-07.jsonl.
LOST_DECLARATION = (
    "統計量變化重跑 brief 已寫好但 enqueue-agent 需 registered worktree 而 "
    "free_slots=0（assign_1aa8f31a 未關），未入列"
)


def _run(pool: Path, **kwargs) -> dict:
    """Call the real completion path in-process against a throwaway pool.

    In-process on purpose. The first version of this module shelled out with a
    hand-built ``env={...}``, which dropped ``VOLPRED_NO_CANONICAL_WRITE`` (armed
    for the whole suite in conftest.py) -- so ``_locked_load``'s
    ``guard_canonical_write`` saw an unarmed process and every test wrote to the
    live storage/next_tasks.json. Monkeypatching the module constant keeps the
    guard armed and needs no environment surgery at all.
    """
    args = argparse.Namespace(
        id=kwargs.pop("id"),
        status=kwargs.pop("status", "succeeded"),
        result=kwargs.pop("result", None),
        follow_up=kwargs.pop("follow_up", None),
        follow_up_waived=kwargs.pop("follow_up_waived", None),
        repair_verification_json=None,
        issue_disposition="contained",
        gate_decision=None,
        gate_live_readback=None,
    )
    assert not kwargs, f"unexpected kwargs {sorted(kwargs)}"
    out, _burst = task_pool_claim._complete_locked(args, completion_base_commit="0" * 40)
    return out


@pytest.fixture()
def pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "next_tasks.json"
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", path)
    path.write_text(
        json.dumps(
            [
                {
                    "id": "snapaudit_quantify_unmeasured_exposure",
                    "task_type": "platform_ops",
                    "status": "in_progress",
                    "priority": 2,
                    "title": "snapaudit: quantify unmeasured exposure",
                    "source": "discovered",
                    "created_at": "2026-07-28T00:00:00+00:00",
                    "claimed_by": "hourly-28",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _tasks(pool: Path) -> list[dict]:
    return json.loads(pool.read_text(encoding="utf-8"))


def _find(pool: Path, task_id: str) -> dict | None:
    return next((t for t in _tasks(pool) if t.get("id") == task_id), None)


def test_prose_only_completion_is_refused_with_a_one_flag_remedy(pool: Path) -> None:
    """The 2026-07-28 completion, replayed verbatim, no longer goes through."""
    out = _run(
        pool,
        id="snapaudit_quantify_unmeasured_exposure",
        status="succeeded",
        result=f"曝險量化完成。{LOST_DECLARATION}",
    )
    assert out["ok"] is False
    assert out["reason"] == "undischarged_followup_in_result"
    assert out["matched"] == "未入列"
    # Escapable, and the message must say how -- a gate with no printed exit is
    # the deadlock this repo has been burned by before.
    assert "--follow-up" in out["hint"]
    assert "--follow-up-waived" in out["hint"]
    # Refusal must not half-complete the row.
    assert _find(pool, "snapaudit_quantify_unmeasured_exposure")["status"] == "in_progress"


def test_follow_up_becomes_a_real_pending_row_and_survives_compaction(pool: Path) -> None:
    """The whole point: the declaration ends up as work, not as a sentence."""
    out = _run(
        pool,
        id="snapaudit_quantify_unmeasured_exposure",
        status="succeeded",
        result=f"曝險量化完成。{LOST_DECLARATION}",
        follow_up=["k1308/k1399 統計量變化重跑；兩篇已發佈文章的更正數字等它"],
    )
    assert out["ok"] is True
    assert len(out["follow_ups"]) == 1
    child_id = out["follow_ups"][0]["id"]
    assert out["follow_ups"][0]["created"] is True

    child = _find(pool, child_id)
    assert child is not None, "follow-up did not become a real row"
    assert child["status"] == "pending"
    assert child["follows_up_on"] == "snapaudit_quantify_unmeasured_exposure"
    assert "k1308/k1399" in child["description"]

    # Now age the parent past the compaction threshold and compact for real.
    tasks = _tasks(pool)
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    for task in tasks:
        if task["id"] == "snapaudit_quantify_unmeasured_exposure":
            task["completed_at"] = old
    count, _archived = compact_terminal_tasks(tasks, age_days=30)
    assert count == 1, "parent should have been tombstoned"

    parent = next(t for t in tasks if t["id"] == "snapaudit_quantify_unmeasured_exposure")
    assert parent.get("tombstone") is True
    # The prose is gone, exactly as before -- that part was never the bug.
    assert "result" not in parent
    # What changed: the work outlived it as a pending row...
    survivor = next(t for t in tasks if t["id"] == child_id)
    assert survivor["status"] == "pending"
    # ...and the tombstone can still say what it spawned.
    assert parent["follow_ups"][0]["task_id"] == child_id


def test_waiver_records_a_judgement_instead_of_blocking(pool: Path) -> None:
    """False positives must cost one flag, never a stuck completion."""
    out = _run(
        pool,
        id="snapaudit_quantify_unmeasured_exposure",
        status="succeeded",
        result="全部完成，沒有待補項目。",  # '待補' matches, but is negated in context
        follow_up_waived="the phrase appears inside a negation; nothing is owed",
    )
    assert out["ok"] is True
    parent = _find(pool, "snapaudit_quantify_unmeasured_exposure")
    assert parent["status"] == "succeeded"
    assert "negation" in parent["follow_up_waived"]["reason"]


def test_clean_result_needs_no_extra_flag(pool: Path) -> None:
    """The gate must stay off the path of completions that owe nothing."""
    out = _run(
        pool,
        id="snapaudit_quantify_unmeasured_exposure",
        status="succeeded",
        result="Exposure quantified; all gates passed and read back clean.",
    )
    assert out["ok"] is True
    assert "follow_ups" not in out


def test_rerunning_the_same_completion_does_not_double_enqueue(pool: Path) -> None:
    """Deterministic child ids; a retried completion must be idempotent."""
    call = dict(
        id="snapaudit_quantify_unmeasured_exposure",
        status="succeeded",
        result=f"完成。{LOST_DECLARATION}",
        follow_up=["k1308/k1399 統計量變化重跑"],
    )
    first = _run(pool, **call)
    child_id = first["follow_ups"][0]["id"]
    # Force the row back to in_progress so completion runs its full path again,
    # rather than short-circuiting on the idempotent-terminal branch.
    tasks = _tasks(pool)
    for task in tasks:
        if task["id"] == "snapaudit_quantify_unmeasured_exposure":
            task["status"] = "in_progress"
    pool.write_text(json.dumps(tasks), encoding="utf-8")

    second = _run(pool, **call)
    assert second["ok"] is True
    assert second["follow_ups"][0]["created"] is False
    assert second["follow_ups"][0]["reason"] == "already_exists"
    assert sum(1 for t in _tasks(pool) if t["id"] == child_id) == 1


def test_blank_entries_do_not_misalign_the_tombstone_edges(pool: Path) -> None:
    """Each kept edge must name the text it actually came from.

    The first implementation built ``follow_ups`` by zipping the receipt list
    against the input list, but blank entries are skipped when building receipts,
    so a blank in the middle shifted every later edge onto the wrong text -- a
    tombstone confidently pointing at the wrong task.

    Driven at the function, not through ``complete``: the CLI path filters blanks
    before calling, so the desync is unreachable from there. The function still
    defends internally, and this pins that its defence stays aligned -- exercising
    it through ``complete`` would assert an input that path cannot produce.
    """
    tasks: list[dict] = []
    parent = {"id": "parent_task", "task_type": "platform_ops", "priority": 2}
    tasks.append(parent)
    receipts = task_pool_claim._materialize_follow_ups(
        tasks, parent, ["first thing owed", "   ", "second thing owed"]
    )
    assert len(receipts) == 2, "blank entry must not become a task"
    edges = {e["text"]: e["task_id"] for e in parent["follow_ups"]}
    assert set(edges) == {"first thing owed", "second thing owed"}
    for text, child_id in edges.items():
        child = next((t for t in tasks if t.get("id") == child_id), None)
        assert child is not None, f"edge for {text!r} points at a nonexistent row"
        assert text in child["description"], f"edge {child_id} names the wrong text"


def test_followup_of_a_boss_p1_does_not_inherit_p1(pool: Path) -> None:
    """A follow-up is machine-created, whatever the parent was.

    Caught live: the first version inherited both `priority` and `source` from the
    parent, so completing a boss P1 minted a P1 successor from a "user" source --
    which `is_urgent_source` waves straight past the admission clamp. The follow-up
    here could not even be started for four days, and it would have sat at the head
    of the P1 FIFO lane the whole time. P1 means "what the boss wants right now";
    a follow-up is by definition not that.
    """
    tasks = _tasks(pool)
    tasks[0].update(priority=1, source="user", status="in_progress")
    pool.write_text(json.dumps(tasks), encoding="utf-8")

    out = _run(
        pool,
        id="snapaudit_quantify_unmeasured_exposure",
        status="succeeded",
        result=f"完成。{LOST_DECLARATION}",
        follow_up=["something owed but not urgent"],
    )
    child = _find(pool, out["follow_ups"][0]["id"])
    assert child["priority"] == 2, "machine-created follow-up must be clamped off P1"
    assert child["priority_capped_from"] == 1
    assert child["source"] == "followup", (
        "inheriting the parent's boss source would launder a machine row past the clamp"
    )
    # Lineage still readable -- it moved to the field that means lineage.
    assert child["follows_up_on"] == "snapaudit_quantify_unmeasured_exposure"


def test_failed_completions_are_not_gated(pool: Path) -> None:
    """A failure report is *expected* to describe unfinished work."""
    out = _run(
        pool,
        id="snapaudit_quantify_unmeasured_exposure",
        status="failed",
        result=f"未完成。{LOST_DECLARATION}",
    )
    assert out["ok"] is True
    assert out["status"] == "failed"


def test_keep_fields_carry_the_followup_edge() -> None:
    """Pins the survival half against a future prune of the keep list."""
    assert "follow_ups" in _TOMBSTONE_KEEP_FIELDS
    assert "follow_up_waived" in _TOMBSTONE_KEEP_FIELDS
    # And pins the premise the whole module rests on: result is NOT kept.
    assert "result" not in _TOMBSTONE_KEEP_FIELDS
