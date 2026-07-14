"""Regression: a registered series must release at its own pacing, in episode order.

Incident 2026-07-14 (boss escalation): the cluster-gate exemption (2bd97c1f7) fixed
the 無人載具 series deadlock but removed the only brake — the release pool then
drained the 6-episode series at pool cadence (~4h): five episodes in ~20 hours,
EP4 published before EP3. The intended shape was a week-long arc (one episode/day).

Domain fix: registered-series **release pacing** at release-pool selection
(`_series_pacing_hold` in volpred.ops.content — single enforcement owner):
- min_gap: next episode only after `min_hours_between_episodes` (default 24h for
  episodic series) since the series' latest published episode.
- ordered: the registry members ARRAY ORDER is the canonical episode order; a later
  episode cannot ship while an earlier one is still pending in the feed.
- held episodes never reach the release loop (so the drought breaker cannot force
  them); an explicit pub_id (manual operator release) bypasses pacing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops import content
from volpred.publisher import arc_dedup

NOW = datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)

_TEST_SPEC = {
    "display_name": "測試連載",
    "branding": "title_prefix",
    "prefix": "🧪 測試連載｜",
    "no_episode_numbers": False,
    "release_pacing": {"min_hours_between_episodes": 24, "ordered": True},
    "members": ["mile_tser_ep0", "mile_tser_ep1", "mile_tser_ep2", "mile_tser_ep3"],
}


def _patch_registry(monkeypatch, spec: dict | None = None) -> None:
    spec = spec if spec is not None else _TEST_SPEC
    monkeypatch.setattr(
        arc_dedup, "_SERIES_SPEC_CACHE", [(spec["prefix"], "test_serial", spec)]
    )


def _episode(ep: int, status: str, published_at: str | None = None) -> dict:
    item = {
        "id": f"mile_tser_ep{ep}",
        "title": f"🧪 測試連載｜EP{ep}：第 {ep} 章",
        "tags": ["測試"],
        "status": status,
        "audience": "research",
        "created_at": f"2026-07-10T0{ep}:00:00+00:00",
    }
    if published_at:
        item["published_at"] = published_at
    return item


def test_min_gap_holds_next_episode(monkeypatch):
    """EP0 出刊 4 小時後，EP1 必須被 hold（不足 24h 間隔）。"""
    _patch_registry(monkeypatch)
    feed = [
        _episode(0, "published", (NOW - timedelta(hours=4)).isoformat()),
        _episode(1, "draft"),
    ]
    hold = content._series_pacing_hold(feed[1], feed, NOW)
    assert hold is not None and hold["reason"] == "min_gap"
    expected_next = (NOW - timedelta(hours=4) + timedelta(hours=24)).isoformat()
    assert hold["next_eligible_at"] == expected_next


def test_min_gap_elapsed_releases_next_in_order(monkeypatch):
    """間隔滿 24h 後，只有『下一集』可出 — 後面的集數仍被 order hold。"""
    _patch_registry(monkeypatch)
    feed = [
        _episode(0, "published", (NOW - timedelta(hours=25)).isoformat()),
        _episode(1, "draft"),
        _episode(2, "draft"),
    ]
    assert content._series_pacing_hold(feed[1], feed, NOW) is None
    hold = content._series_pacing_hold(feed[2], feed, NOW)
    assert hold is not None and hold["reason"] == "out_of_order"
    assert hold["next_in_series"] == "mile_tser_ep1"


def test_retired_and_missing_members_do_not_block_order(monkeypatch):
    """unpublished（除役）與 feed 缺席的集數不擋後續集數（不會把系列鎖死）。"""
    _patch_registry(monkeypatch)
    feed = [
        _episode(0, "published", (NOW - timedelta(hours=30)).isoformat()),
        _episode(1, "unpublished"),
        # ep2 not in feed at all (unwritten)
        _episode(3, "draft"),
    ]
    assert content._series_pacing_hold(feed[2], feed, NOW) is None


def test_episodic_series_paced_by_default(monkeypatch):
    """有集數的系列（no_episode_numbers=false）沒寫 release_pacing 也要有預設節奏。"""
    spec = {k: v for k, v in _TEST_SPEC.items() if k != "release_pacing"}
    _patch_registry(monkeypatch, spec)
    feed = [
        _episode(0, "published", (NOW - timedelta(hours=4)).isoformat()),
        _episode(1, "draft"),
    ]
    hold = content._series_pacing_hold(feed[1], feed, NOW)
    assert hold is not None and hold["reason"] == "min_gap"


def test_non_episodic_series_unpaced_by_default(monkeypatch):
    """無集數系列（迷思實驗室型）預設不 paced — 各篇獨立，交給既有 gate 管。"""
    spec = {k: v for k, v in _TEST_SPEC.items() if k != "release_pacing"}
    spec["no_episode_numbers"] = True
    _patch_registry(monkeypatch, spec)
    feed = [
        _episode(0, "published", (NOW - timedelta(hours=1)).isoformat()),
        _episode(1, "draft"),
    ]
    assert content._series_pacing_hold(feed[1], feed, NOW) is None


# ---------------------------------------------------------------------------
# Integration: the release pool itself honours the hold / bypasses on pub_id.
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _freeze_content_now(monkeypatch, frozen_now: datetime) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen_now.replace(tzinfo=None)
            return frozen_now.astimezone(tz)

    monkeypatch.setattr(content, "datetime", FrozenDateTime)


def _stub_release_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(content, "sync_article", lambda *args, **kwargs: None)
    monkeypatch.setattr(content, "_mark_questions_answered_on_publish", lambda *args, **kwargs: 0)
    monkeypatch.setattr(content, "_patch_where", lambda *args, **kwargs: True)
    monkeypatch.setattr(content.Publisher, "_sync_feed_to_remote", lambda self: None)
    monkeypatch.setattr(content, "_run_publish_anti_ai_gate", lambda *args, **kwargs: [])
    from volpred.publisher.email_notifier import EmailNotifier
    from volpred.publisher import live_verify

    monkeypatch.setattr(EmailNotifier, "notify_article_published", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_verify, "verify_article_live", lambda *args, **kwargs: True)
    monkeypatch.setattr(live_verify, "stamp_verified", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_verify, "emit_verify_alert", lambda *args, **kwargs: None)


def _pool_fixture(tmp_path: Path) -> Path:
    storage_dir = tmp_path / "storage"
    feed = [
        _episode(0, "published", (NOW - timedelta(hours=4)).isoformat()),
        _episode(1, "draft"),
        {
            "id": "mile_other_topic",
            "title": "與連載無關的一篇研究筆記",
            "tags": ["其他"],
            "status": "draft",
            "audience": "research",
            "created_at": "2026-07-12T00:00:00+00:00",
        },
    ]
    _write_json(storage_dir / "reports" / "feed.json", feed)
    return storage_dir


def test_release_pool_holds_paced_episode_and_releases_other(tmp_path, monkeypatch):
    _patch_registry(monkeypatch)
    _freeze_content_now(monkeypatch, NOW)
    _stub_release_side_effects(monkeypatch)
    storage_dir = _pool_fixture(tmp_path)

    result = content.release_pool_articles(
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )
    released_ids = [r["id"] for r in result["released"]]
    assert released_ids == ["mile_other_topic"], result
    held_ids = [h["id"] for h in result["series_pacing_held"]]
    assert "mile_tser_ep1" in held_ids
    held = next(h for h in result["series_pacing_held"] if h["id"] == "mile_tser_ep1")
    assert held["reason"] == "min_gap"


def test_release_pool_manual_pub_id_bypasses_pacing(tmp_path, monkeypatch):
    _patch_registry(monkeypatch)
    _freeze_content_now(monkeypatch, NOW)
    _stub_release_side_effects(monkeypatch)
    storage_dir = _pool_fixture(tmp_path)

    result = content.release_pool_articles(
        pub_id="mile_tser_ep1",
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )
    released_ids = [r["id"] for r in result["released"]]
    assert released_ids == ["mile_tser_ep1"], result
    assert result["series_pacing_held"] == []
