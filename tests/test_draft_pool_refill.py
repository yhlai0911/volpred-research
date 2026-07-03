"""Regression tests for the draft-pool-specific refill gap fix (2026-07-01 3-STRIKE).

Root cause: `_maybe_refill` in continue_task_dispatch.py only reacts to the
next_tasks.json agentable-task-count signal (REFILL_FLOOR), which can stay
healthy while composed entirely of non-article task types. Meanwhile
feed.json's actual `draft` article buffer (what `draft_pool_low` alert in
src/volpred/ops/alerts.py measures) can run dry unnoticed. See
docs/error_log.md 2026-07-01 entry + dreaming finding
`persistent_alert:9a39f7aa6399dfee` (5 fires / 73 days).

These tests lock in:
1. `_draft_pool_deficit()` reads feed.json directly and computes the gap to
   DRAFT_POOL_FLOOR, independent of next_tasks.json state.
2. `_maybe_refill_draft_pool()` no-ops when deficit <= 0 or auto_refill=False.
3. `_maybe_refill_draft_pool()` triggers `refill_task_pool.refill()` when
   deficit > 0, and accurately reports `by_type` from the real task_type of
   added entries (not blindly labeled "daily_article") — because
   refill_task_pool.refill() can fall back to task_type="experiment" when the
   uncovered-K article pool is exhausted.
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


def _write_feed(path: Path, draft_count: int, other_statuses: list[str] | None = None) -> None:
    entries = [{"id": f"mile_draft_{i}", "status": "draft"} for i in range(draft_count)]
    for i, status in enumerate(other_statuses or []):
        entries.append({"id": f"mile_other_{i}", "status": status})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_draft_pool_deficit_zero_when_at_floor(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=MODULE.DRAFT_POOL_FLOOR)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    assert MODULE._draft_pool_deficit() == 0


def test_draft_pool_deficit_zero_when_above_floor(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=MODULE.DRAFT_POOL_FLOOR + 3)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    assert MODULE._draft_pool_deficit() == 0


def test_draft_pool_deficit_positive_when_below_floor(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=1, other_statuses=["published", "published", "archived"])
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    assert MODULE._draft_pool_deficit() == MODULE.DRAFT_POOL_FLOOR - 1


def test_draft_pool_deficit_fail_open_on_missing_feed(tmp_path, monkeypatch):
    feed_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    assert MODULE._draft_pool_deficit() == 0


def test_draft_pool_deficit_fail_open_on_malformed_json(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    feed_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    assert MODULE._draft_pool_deficit() == 0


def test_maybe_refill_draft_pool_noop_when_auto_refill_false(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=0)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)
    assert MODULE._maybe_refill_draft_pool(auto_refill=False) is None


def test_maybe_refill_draft_pool_noop_when_deficit_zero(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=MODULE.DRAFT_POOL_FLOOR)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)

    def fail_refill(*_args, **_kwargs):
        raise AssertionError("_run_article_refill must not run when draft pool has no deficit")

    monkeypatch.setattr(MODULE, "_run_article_refill", fail_refill)
    assert MODULE._maybe_refill_draft_pool(auto_refill=True) is None


def test_maybe_refill_draft_pool_reports_accurate_by_type(tmp_path, monkeypatch):
    """When refill_task_pool.refill() falls back to task_type='experiment'
    (article candidates exhausted), the report must reflect that — not claim
    daily_article — so downstream dreaming / dashboard consumers don't get a
    false 'draft pool problem solved' signal.
    """
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=0)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)

    def fake_article_refill(target, dry_run=False):
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


def test_maybe_refill_draft_pool_reports_clean_daily_article(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=0)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)

    def fake_article_refill(target, dry_run=False):
        return {"ok": True, "added": 1, "added_ids": ["K9999_article_general"]}

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)
    monkeypatch.setattr(
        MODULE,
        "load_pending_tasks",
        lambda: [{"id": "K9999_article_general", "task_type": "daily_article"}],
    )

    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert result["by_type"] == {"daily_article": 1}
    assert result["note"] is None


def test_maybe_refill_draft_pool_handles_refill_failure(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=0)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)

    def fake_article_refill(target, dry_run=False):
        return {"ok": False, "added": 0, "reason": "publication_candidates.json missing"}

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)

    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert result["ok"] is False
    assert "publication_candidates" in result["reason"]


def test_maybe_refill_draft_pool_handles_timeout(tmp_path, monkeypatch):
    feed_path = tmp_path / "feed.json"
    _write_feed(feed_path, draft_count=0)
    monkeypatch.setattr(MODULE, "FEED_PATH", feed_path)

    def fake_article_refill(target, dry_run=False):
        raise MODULE.ArticleRefillTimeoutError("timed out after 45s")

    monkeypatch.setattr(MODULE, "_run_article_refill", fake_article_refill)

    result = MODULE._maybe_refill_draft_pool(auto_refill=True)
    assert result is not None
    assert result["ok"] is False
    assert "timeout" in result["reason"]
