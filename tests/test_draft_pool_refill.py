"""Regression tests for the draft-pool refill signal.

History:
- 2026-07-01 (3-STRIKE): `_maybe_refill` only reacted to the next_tasks.json
  agentable-task-count signal (REFILL_FLOOR), which can stay healthy while
  composed entirely of non-article task types, so feed.json's `draft` buffer
  could run dry unnoticed. Fixed by `_draft_pool_deficit()` / `_maybe_refill_draft_pool()`.

- 2026-07-04 ROOTFIX (release-layer deadlock; boss telegram msg114
  「頭痛醫頭腳痛醫腳」): `_draft_pool_deficit()` counted RAW status=="draft"
  items, which is BLIND to releasability. A pool of 6 arc-dup / dedup-flagged
  drafts (all unreleasable) read as fully stocked (deficit=0), so the proactive
  refill never fired, the release cadence released nothing, and publishing
  droughted (07-03 blocked_pool=6, eligible=0). Root fix: stock = release path's
  own post-dedup `eligible` count (`_releasable_draft_count`) + in-flight
  daily_article tasks (`_in_flight_article_task_count`), so the draft-floor
  signal agrees with what release can actually publish and self-limits against
  re-refill pile-up. Fail-open to the legacy raw draft count on any error.

These tests lock in:
1. `_draft_pool_deficit()` measures RELEASABLE stock (not raw draft count):
   a pool full of unreleasable drafts still reports a positive deficit.
2. In-flight daily_article tasks count as pipeline stock (anti-pileup).
3. Fail-open to raw draft count when the releasable-count path is unavailable.
4. `_maybe_refill_draft_pool()` no-ops when deficit <= 0 or auto_refill=False,
   and reports accurate `by_type` when refill falls back to a non-article type.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "continue_task_dispatch.py"
SPEC = importlib.util.spec_from_file_location("continue_task_dispatch", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _set_stock(monkeypatch, *, releasable: int | None, in_flight: int = 0) -> None:
    """Pin the two stock signals `_draft_pool_deficit` composes."""
    monkeypatch.setattr(MODULE, "_releasable_draft_count", lambda: releasable)
    monkeypatch.setattr(MODULE, "_in_flight_article_task_count", lambda: in_flight)


def _write_feed(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


# --- deficit: releasability-aware -----------------------------------------


def test_deficit_zero_when_releasable_at_floor(monkeypatch):
    _set_stock(monkeypatch, releasable=MODULE.DRAFT_POOL_FLOOR)
    assert MODULE._draft_pool_deficit() == 0


def test_deficit_zero_when_releasable_above_floor(monkeypatch):
    _set_stock(monkeypatch, releasable=MODULE.DRAFT_POOL_FLOOR + 3)
    assert MODULE._draft_pool_deficit() == 0


def test_deficit_positive_when_releasable_below_floor(monkeypatch):
    _set_stock(monkeypatch, releasable=1)
    assert MODULE._draft_pool_deficit() == MODULE.DRAFT_POOL_FLOOR - 1


def test_deficit_full_when_pool_all_unreleasable(monkeypatch):
    """THE 07-03 root cause: pool has FLOOR raw drafts but ALL are arc-dup /
    dedup-flagged (eligible=0). The old raw-count code read deficit=0 and never
    refilled → drought. The fix must report a full deficit so fresh content is
    produced.
    """
    _set_stock(monkeypatch, releasable=0)
    assert MODULE._draft_pool_deficit() == MODULE.DRAFT_POOL_FLOOR


def test_deficit_discounts_in_flight_article_tasks(monkeypatch):
    """Fresh daily_article tasks already queued count as pipeline stock so the
    refill self-limits and does not pile up dozens of pending tasks while the
    first fresh draft is still being generated.
    """
    _set_stock(monkeypatch, releasable=0, in_flight=MODULE.DRAFT_POOL_FLOOR)
    assert MODULE._draft_pool_deficit() == 0
    _set_stock(monkeypatch, releasable=1, in_flight=2)
    assert MODULE._draft_pool_deficit() == MODULE.DRAFT_POOL_FLOOR - 3


# --- deficit: fail-open fallback to raw draft count ------------------------


def test_deficit_falls_back_to_raw_count_when_releasable_unavailable(tmp_path, monkeypatch):
    """When the release-preview path can't compute `eligible` (returns None),
    fall back to the legacy raw draft count rather than crashing / over-refilling.
    """
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, [{"id": f"d{i}", "status": "draft"} for i in range(2)])
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    monkeypatch.setattr(MODULE, "_releasable_draft_count", lambda: None)
    monkeypatch.setattr(MODULE, "_in_flight_article_task_count", lambda: 0)
    assert MODULE._draft_pool_deficit() == MODULE.DRAFT_POOL_FLOOR - 2


def test_raw_draft_count_fail_open_on_missing_feed(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "FEED_PATH", tmp_path / "does_not_exist.json")
    assert MODULE._raw_draft_count() == 0


def test_releasable_count_returns_none_when_preview_raises(monkeypatch):
    """Codex CONDITIONAL_PASS finding: a preview/import failure must degrade to
    None (→ raw-count fallback), never propagate a raise that the deficit's outer
    except would swallow into a silent 0 (no refill → re-drought).
    """
    import volpred.ops.content as content_mod

    def boom(*_a, **_k):
        raise RuntimeError("preview boom")

    monkeypatch.setattr(content_mod, "preview_release_pool_by_settings", boom)
    assert MODULE._releasable_draft_count() is None


def test_deficit_falls_back_to_raw_on_preview_raise(tmp_path, monkeypatch):
    """End-to-end of the Codex finding: when the releasable path fails, the
    deficit uses the raw draft count (2 drafts → deficit FLOOR-2), NOT 0.
    """
    import volpred.ops.content as content_mod

    def boom(*_a, **_k):
        raise RuntimeError("preview boom")

    monkeypatch.setattr(content_mod, "preview_release_pool_by_settings", boom)
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, [{"id": f"d{i}", "status": "draft"} for i in range(2)])
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    monkeypatch.setattr(MODULE, "_in_flight_article_task_count", lambda: 0)
    assert MODULE._draft_pool_deficit() == MODULE.DRAFT_POOL_FLOOR - 2


def test_deficit_fail_open_on_compute_error(monkeypatch):
    def boom():
        raise RuntimeError("preview exploded")

    monkeypatch.setattr(MODULE, "_releasable_draft_count", boom)
    assert MODULE._draft_pool_deficit() == 0


# --- in-flight article task counting --------------------------------------


def test_in_flight_counts_only_active_daily_article_tasks(tmp_path, monkeypatch):
    tasks = [
        {"id": "a", "task_type": "daily_article", "status": "pending"},
        {"id": "b", "task_type": "daily_article", "status": "in_progress"},
        {"id": "c", "task_type": "daily_article", "status": "succeeded"},  # done — not stock
        {"id": "d", "task_type": "experiment", "status": "pending"},       # wrong type
        {"id": "e", "task_type": "daily_article", "status": "claimed"},
    ]
    nt = tmp_path / "next_tasks.json"
    nt.write_text(json.dumps(tasks), encoding="utf-8")
    monkeypatch.setattr(MODULE, "NEXT_TASKS", nt)
    assert MODULE._in_flight_article_task_count() == 3


# --- _maybe_refill_draft_pool wiring --------------------------------------


def test_maybe_refill_noop_when_auto_refill_false(monkeypatch):
    _set_stock(monkeypatch, releasable=0)
    assert MODULE._maybe_refill_draft_pool(auto_refill=False) is None


def test_maybe_refill_noop_when_deficit_zero(monkeypatch):
    _set_stock(monkeypatch, releasable=MODULE.DRAFT_POOL_FLOOR)

    def fail_refill(*_args, **_kwargs):
        raise AssertionError("_run_article_refill must not run when deficit is zero")

    monkeypatch.setattr(MODULE, "_run_article_refill", fail_refill)
    assert MODULE._maybe_refill_draft_pool(auto_refill=True) is None


def test_maybe_refill_fires_when_pool_all_unreleasable(monkeypatch):
    """End-to-end of the fix: unreleasable pool → positive deficit → refill runs."""
    _set_stock(monkeypatch, releasable=0)
    captured = {}

    def fake_article_refill(target, dry_run=False, reader_facing_only=False):
        captured["target"] = target
        captured["reader_facing_only"] = reader_facing_only
        return {"ok": True, "added": 1, "added_ids": ["K9999_article_general"]}

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)
    monkeypatch.setattr(
        MODULE,
        "load_pending_tasks",
        lambda: [{"id": "K9999_article_general", "task_type": "daily_article"}],
    )
    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert captured["target"] == MODULE.DRAFT_POOL_FLOOR
    # ROOTFIX: draft-pool refill must be reader-facing (no experiment fallback)
    assert captured["reader_facing_only"] is True
    assert result["by_type"] == {"daily_article": 1}
    assert result["note"] is None


def test_maybe_refill_reports_accurate_by_type_on_fallback(monkeypatch):
    """When refill falls back to task_type='experiment' (article pool exhausted),
    the report must reflect that — not claim daily_article — so downstream
    dreaming / dashboard don't get a false 'draft pool solved' signal.
    """
    _set_stock(monkeypatch, releasable=0)

    def fake_article_refill(target, dry_run=False, reader_facing_only=False):
        return {"ok": True, "added": 1, "added_ids": ["research_fallback_x"]}

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)
    monkeypatch.setattr(
        MODULE,
        "load_pending_tasks",
        lambda: [{"id": "research_fallback_x", "task_type": "experiment"}],
    )
    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert result["added"] == 1
    assert result["by_type"] == {"experiment": 1}
    assert result["note"] is not None
    assert "NOT closed" in result["note"]


def test_maybe_refill_handles_refill_failure(monkeypatch):
    _set_stock(monkeypatch, releasable=0)

    def fake_article_refill(target, dry_run=False, reader_facing_only=False):
        return {"ok": False, "added": 0, "reason": "publication_candidates.json missing"}

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)
    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert result["ok"] is False
    assert "publication_candidates" in result["reason"]


def test_maybe_refill_handles_timeout(monkeypatch):
    _set_stock(monkeypatch, releasable=0)

    def fake_article_refill(target, dry_run=False, reader_facing_only=False):
        raise MODULE.ArticleRefillTimeoutError("timed out after 45s")

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)
    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert result["ok"] is False
    assert "timeout" in result["reason"]
