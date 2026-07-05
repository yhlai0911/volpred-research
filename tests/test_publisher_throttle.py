"""Tests for the pre-publish throttle gate (2026-06-30 boss email-12281).

Covers `src/volpred/publisher/throttle.py` + its integration into
`Publisher._append_to_feed`. The gate prevents two discretionary reader-facing
articles from publishing within RHYTHM_BURST_GAP_MIN; fixtures (digest /
daily_update) and event-driven (trending_repost / event_article) bypass.

Bar (from task description platform_ops_publish_rhythm_pre_publish_throttle):
  * 連續派兩篇 reader-facing 第二篇被 gate 擋
  * alert publish_rhythm:burst 不再觸發（前提：第二篇被 gate reject）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.publisher.throttle import (
    PublishThrottleError,
    RHYTHM_BURST_GAP_MIN,
    check_publish_throttle,
    find_most_recent_rhythm_published,
    is_rhythm_controlled,
)


# ----------------------------------------------------------------------------
# is_rhythm_controlled — domain model: which items are "discretionary"
# ----------------------------------------------------------------------------


def test_research_general_is_rhythm_controlled():
    assert is_rhythm_controlled({"audience": "research", "category": "milestone"}) is True
    assert is_rhythm_controlled({"audience": "general", "category": "general"}) is True


def test_daily_audience_bypasses():
    assert is_rhythm_controlled({"audience": "daily"}) is False
    # case-insensitive
    assert is_rhythm_controlled({"audience": "DAILY"}) is False


@pytest.mark.parametrize(
    "phase",
    ["digest", "daily_update", "daily_recommendation", "trending_repost", "event", "event_article"],
)
def test_non_rhythm_phases_bypass(phase):
    assert is_rhythm_controlled({"audience": "general", "phase": phase}) is False


def test_non_rhythm_categories_bypass():
    assert is_rhythm_controlled({"category": "event_article"}) is False
    assert is_rhythm_controlled({"category": "trending_repost"}) is False


# ----------------------------------------------------------------------------
# find_most_recent_rhythm_published — feed scan helper
# ----------------------------------------------------------------------------


def _entry(*, id_, ts: datetime, status="published", audience="general", phase=None, category="general"):
    item = {
        "id": id_,
        "status": status,
        "audience": audience,
        "category": category,
        "published_at": ts.isoformat(),
    }
    if phase is not None:
        item["phase"] = phase
    return item


def test_find_skips_non_published():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    feed = [_entry(id_="a", ts=now, status="draft")]
    assert find_most_recent_rhythm_published(feed) is None


def test_find_skips_non_rhythm():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    feed = [_entry(id_="d", ts=now, phase="digest")]
    assert find_most_recent_rhythm_published(feed) is None


def test_find_returns_newest_rhythm():
    base = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    feed = [
        _entry(id_="old", ts=base - timedelta(hours=2)),
        _entry(id_="newest", ts=base - timedelta(minutes=5)),
        _entry(id_="digest", ts=base - timedelta(minutes=1), phase="digest"),  # skipped
    ]
    found = find_most_recent_rhythm_published(feed)
    assert found is not None
    assert found[0]["id"] == "newest"


def test_find_excludes_self_id():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    feed = [_entry(id_="me", ts=now)]
    assert find_most_recent_rhythm_published(feed, exclude_id="me") is None


# ----------------------------------------------------------------------------
# check_publish_throttle — gate decision
# ----------------------------------------------------------------------------


def test_bypass_when_not_rhythm_controlled(tmp_path: Path):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    feed = [_entry(id_="prev", ts=now - timedelta(minutes=5))]
    new = {"id": "trending_new", "audience": "general", "phase": "trending_repost"}
    # Must NOT raise — trending bypasses
    check_publish_throttle(new, feed, storage_dir=tmp_path, now=now)
    log = (tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()
    rec = json.loads(log[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"] == "not_rhythm_controlled"


def test_bypass_when_no_prior_rhythm_publish(tmp_path: Path):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    feed: list = []
    new = {"id": "first", "audience": "research", "category": "milestone"}
    check_publish_throttle(new, feed, storage_dir=tmp_path, now=now)
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"] == "no_prior_rhythm_publish"


def test_bypass_when_paired_sibling(tmp_path: Path):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    prev = _entry(id_="prev", ts=now - timedelta(minutes=5))
    prev["details"] = {"paired_sibling_group": "daily_update_20260630"}
    new = {
        "id": "sibling",
        "audience": "research",
        "category": "milestone",
        "details": {"paired_sibling_group": "daily_update_20260630"},
    }
    check_publish_throttle(new, [prev], storage_dir=tmp_path, now=now)
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"].startswith("paired_sibling_group:")


def test_bypass_when_gap_above_threshold(tmp_path: Path):
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    prev = _entry(id_="prev", ts=now - timedelta(minutes=RHYTHM_BURST_GAP_MIN + 1))
    new = {"id": "new", "audience": "research", "category": "milestone"}
    check_publish_throttle(new, [prev], storage_dir=tmp_path, now=now)
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"] == "gap_above_threshold"
    assert rec["gap_minutes"] == pytest.approx(RHYTHM_BURST_GAP_MIN + 1, abs=0.1)


def test_block_when_gap_below_threshold(tmp_path: Path):
    """Bar case: 連續派兩篇 reader-facing 第二篇被 gate 擋."""
    now = datetime(2026, 6, 30, 2, 56, 42, tzinfo=timezone.utc)
    # Mimic the mile_44ab1acc / mile_f5f4cb43 incident timing (2.73 min gap)
    prev = _entry(id_="mile_first", ts=now - timedelta(minutes=2, seconds=44))
    new = {"id": "mile_second", "audience": "general", "category": "general"}
    with pytest.raises(PublishThrottleError) as exc:
        check_publish_throttle(new, [prev], storage_dir=tmp_path, now=now)
    assert exc.value.previous_id == "mile_first"
    assert exc.value.gap_minutes < RHYTHM_BURST_GAP_MIN
    assert exc.value.threshold_minutes == RHYTHM_BURST_GAP_MIN
    # audit trail records the block
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "block"
    assert rec["target_id"] == "mile_second"
    assert rec["previous_id"] == "mile_first"


def test_draft_ingestion_bypasses_even_within_window(tmp_path: Path):
    """Draft entering the pool is not reader-facing — release_pool gates its
    release. A published rhythm article 5 min ago must NOT block a draft.
    (2026-07-05: K1633 general draft blocked 13min after a publish, agent burned
    ~700s waiting; throttle-on-draft is double-gating.)"""
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    prev = _entry(id_="mile_published_recent", ts=now - timedelta(minutes=5))
    draft = {"id": "mile_draft", "status": "draft", "audience": "general", "category": "general"}
    # Must NOT raise — draft ingestion bypasses the burst gate.
    check_publish_throttle(draft, [prev], storage_dir=tmp_path, now=now)
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"].startswith("non_published_ingestion:draft")


def test_scheduled_ingestion_bypasses(tmp_path: Path):
    """status=scheduled is likewise not reader-facing at ingestion."""
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    prev = _entry(id_="mile_pub", ts=now - timedelta(minutes=2))
    sched = {"id": "mile_sched", "status": "scheduled", "audience": "research", "category": "milestone"}
    check_publish_throttle(sched, [prev], storage_dir=tmp_path, now=now)
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"].startswith("non_published_ingestion:scheduled")


def test_missing_status_still_gated(tmp_path: Path):
    """Missing status defaults to 'published' (codebase convention) so a
    reader-facing publish attempt without an explicit status is still blocked."""
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    prev = _entry(id_="prev_pub", ts=now - timedelta(minutes=3))
    new = {"id": "new_no_status", "audience": "general", "category": "general"}  # no status
    with pytest.raises(PublishThrottleError):
        check_publish_throttle(new, [prev], storage_dir=tmp_path, now=now)


def test_block_skipped_when_prev_is_non_rhythm(tmp_path: Path):
    """Trending fired 5 min ago does not block a subsequent research publish."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    prev = _entry(id_="trending_recent", ts=now - timedelta(minutes=5), phase="trending_repost")
    new = {"id": "research_new", "audience": "research", "category": "milestone"}
    # Must NOT raise — previous publish was not rhythm-controlled
    check_publish_throttle(new, [prev], storage_dir=tmp_path, now=now)
    rec = json.loads((tmp_path / "logs" / "dedup_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["decision"] == "pass"
    assert rec["reason"] == "no_prior_rhythm_publish"


# ----------------------------------------------------------------------------
# Constants-mirror guard — prevent drift vs content_quality.py
# ----------------------------------------------------------------------------


def test_throttle_uses_shared_release_cadence_policy():
    """Throttle and content-quality patrol share one cadence policy module."""
    from volpred.publisher import throttle as th
    from volpred.ops import content_quality as cq
    from volpred.ops import release_cadence as rc

    assert th.RHYTHM_BURST_GAP_MIN == rc.RHYTHM_BURST_GAP_MIN
    assert cq.RHYTHM_BURST_GAP_MIN == rc.RHYTHM_BURST_GAP_MIN
    assert set(th._NON_RHYTHM_PHASES) == set(rc.NON_RHYTHM_PHASES)
    assert set(th._NON_RHYTHM_CATEGORIES) == set(rc.NON_RHYTHM_CATEGORIES)
    assert th.is_rhythm_controlled is rc.is_rhythm_controlled


# ----------------------------------------------------------------------------
# Integration: _append_to_feed raises PublishThrottleError on burst
# ----------------------------------------------------------------------------


def test_publisher_append_raises_on_burst(tmp_path: Path, monkeypatch):
    """Integration test — Publisher._append_to_feed surfaces PublishThrottleError."""
    storage = tmp_path / "storage"
    (storage / "reports").mkdir(parents=True)
    (storage / "logs").mkdir(parents=True)

    # Seed feed with a recent rhythm-controlled publish (~5 min ago).
    now_iso = datetime.now(timezone.utc) - timedelta(minutes=5)
    seed = [
        {
            "id": "mile_seed",
            "title": "seed article",
            "status": "published",
            "audience": "research",
            "category": "milestone",
            "published_at": now_iso.isoformat(),
            "tags": ["研究"],
            "content": "seed content body for the throttle integration test.",
        }
    ]
    (storage / "reports" / "feed.json").write_text(json.dumps(seed))

    from volpred.publisher.publisher import Publisher

    pub = Publisher(storage_dir=str(storage))

    new_item = {
        "id": "mile_followup",
        "title": "follow-up article",
        "status": "published",
        "audience": "research",
        "category": "milestone",
        "tags": ["研究"],
        "content": "follow-up body content for the throttle integration test.",
    }
    with pytest.raises(PublishThrottleError):
        pub._append_to_feed(new_item)

    # Feed must remain at 1 entry — burst was rejected.
    feed_after = json.loads((storage / "reports" / "feed.json").read_text())
    assert len(feed_after) == 1
    assert feed_after[0]["id"] == "mile_seed"
