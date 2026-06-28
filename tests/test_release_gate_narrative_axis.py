"""Regression tests for two release-gate behaviours in volpred.ops.content:

1. Narrative-axis waiver (2026-06-24 WIP) — a text-similar pair on DIFFERENT
   reader-facing narrative axes is NOT a real duplicate and must be released;
   a text-similar pair on the SAME (or any unspecified) axis stays blocked.

2. Drought circuit-breaker (2026-06-24) — when a release run produces nothing
   because content-clean drafts were all dedup-blocked AND the feed has drifted
   past the reader-facing drought threshold, force-release exactly ONE blocked
   draft (the least dup-like), with an audit trail and one-override anti-thrash.

Style mirrors tests/test_content_release_pool.py (frozen clock + stubbed
side-effects so nothing hits Supabase / email / live-verify).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops import content


# --- shared helpers (mirrors test_content_release_pool.py) -------------------

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
    from volpred.publisher.email_notifier import EmailNotifier
    from volpred.publisher import live_verify

    monkeypatch.setattr(EmailNotifier, "notify_article_published", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_verify, "verify_article_live", lambda *args, **kwargs: True)
    monkeypatch.setattr(live_verify, "stamp_verified", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_verify, "emit_verify_alert", lambda *args, **kwargs: None)


# Neutral CJK passages: no asset entities, no saturated-theme keywords, and they
# classify to narrative_axis "unspecified" (verified) so the *only* dedup signal
# is surface bigram similarity. This lets us control the axis purely through a
# persisted arc_signature and keep find_arc_duplicates inert (no entity anchor).
_BASE_BODY = (
    "今天天氣晴朗適合到公園散步看見許多花朵盛開蝴蝶在草地上飛舞小朋友在溜滑梯"
    "旁邊嬉戲老人坐在長椅上閱讀報紙享受悠閒的午後時光路邊的小販賣著冰淇淋"
)
_NOVEL_TAIL = (
    "海洋深處的鯨魚緩緩游動珊瑚礁色彩繽紛熱帶魚穿梭其間潛水員拍攝美麗的海底"
    "世界鯊魚在遠處巡遊章魚躲在岩石縫隙海星附著礁岩"
)


def _arc_sig(axis: str) -> dict:
    return {"schema_version": "arc_dedup_v3", "narrative_axis": axis}


# ===========================================================================
# Part 1 — narrative-axis waiver (helper-level unit tests)
# ===========================================================================

def test_is_reader_facing_published_classification():
    assert content._is_reader_facing_published(
        {"status": "published", "audience": "general"}
    )
    assert content._is_reader_facing_published(
        {"status": "published", "audience": "research"}
    )
    # daily templated bulletin must NOT count toward reader-facing cadence
    assert not content._is_reader_facing_published(
        {"status": "published", "audience": "daily", "title": "每日策略建議：VIX 18"}
    )
    # member_qa / event do not count either
    assert not content._is_reader_facing_published(
        {"status": "published", "audience": "member_qa"}
    )
    # the daily digest roundup DOES count
    assert content._is_reader_facing_published(
        {"status": "published", "audience": "daily", "title": content.DIGEST_TITLE_PREFIX + "｜2026"}
    )
    # drafts never count
    assert not content._is_reader_facing_published(
        {"status": "draft", "audience": "general"}
    )


def test_item_narrative_axis_prefers_persisted_signature():
    item = {"id": "x", "title": "中性標題", "content": _BASE_BODY,
            "details": {"arc_signature": _arc_sig("product_myth")}}
    assert content._item_narrative_axis(item) == "product_myth"


def test_item_narrative_axis_falls_back_to_unspecified_for_neutral_text():
    item = {"id": "x", "title": "中性標題", "content": _BASE_BODY}
    assert content._item_narrative_axis(item) == "unspecified"


def test_release_axis_waives_dup_different_specified_axes():
    cand = {"id": "d", "details": {"arc_signature": _arc_sig("product_myth")}}
    block = {"id": "p", "details": {"arc_signature": _arc_sig("market_structure")}}
    assert content._release_axis_waives_dup(cand, [block]) is True


def test_release_axis_does_not_waive_same_axis():
    cand = {"id": "d", "details": {"arc_signature": _arc_sig("market_structure")}}
    block = {"id": "p", "details": {"arc_signature": _arc_sig("market_structure")}}
    assert content._release_axis_waives_dup(cand, [block]) is False


def test_release_axis_does_not_waive_when_any_axis_unspecified():
    cand = {"id": "d", "details": {"arc_signature": _arc_sig("product_myth")}}
    block_unspecified = {"id": "p"}  # no arc_signature -> unspecified
    assert content._release_axis_waives_dup(cand, [block_unspecified]) is False
    # candidate unspecified, blocker specified -> still no waiver
    cand_unspecified = {"id": "d"}
    block = {"id": "p", "details": {"arc_signature": _arc_sig("market_structure")}}
    assert content._release_axis_waives_dup(cand_unspecified, [block]) is False


# ===========================================================================
# Part 1b — narrative-axis waiver (end-to-end through release_pool_articles)
# ===========================================================================

def _published_blocker(frozen_now: datetime, axis: str, *, hours_ago: float = 0.5) -> dict:
    return {
        "id": "mile_pub_blocker",
        "title": "共同主題標題",
        "status": "published",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=hours_ago)).isoformat(),
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "content": _BASE_BODY,
        "details": {"arc_signature": _arc_sig(axis)},
    }


def _draft_candidate(frozen_now: datetime, axis: str | None) -> dict:
    details: dict = {}
    if axis is not None:
        details["arc_signature"] = _arc_sig(axis)
    return {
        "id": "mile_draft_cand",
        "title": "共同主題標題",
        "status": "draft",
        "audience": "general",
        "created_at": (frozen_now - timedelta(days=1)).isoformat(),
        "content": _BASE_BODY,  # Jaccard 1.0 vs blocker -> surface near-dup
        "details": details,
    }


def test_axis_waiver_releases_text_dup_on_different_axis(tmp_path: Path, monkeypatch):
    """Text-identical pair on DIFFERENT narrative axes -> released (not a dup)."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    # Keep find_arc_duplicates inert so the unit under test is the surface
    # (Jaccard / theme-flood) axis waiver added by the WIP.
    monkeypatch.setattr(content, "find_arc_duplicates", lambda *a, **k: [])

    feed = [
        _published_blocker(frozen_now, "market_structure"),
        _draft_candidate(frozen_now, "product_myth"),
    ]
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert [r["id"] for r in res["released"]] == ["mile_draft_cand"]
    assert res["dedup_skipped"] == []
    assert res["drought_override"] is None
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    draft = next(a for a in feed_after if a["id"] == "mile_draft_cand")
    assert draft["status"] == "published"


def test_axis_waiver_blocks_text_dup_on_same_axis(tmp_path: Path, monkeypatch):
    """Text-identical pair on the SAME narrative axis -> still a duplicate."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    monkeypatch.setattr(content, "find_arc_duplicates", lambda *a, **k: [])

    feed = [
        _published_blocker(frozen_now, "market_structure"),
        _draft_candidate(frozen_now, "market_structure"),
    ]
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert res["released"] == []
    assert [s["id"] for s in res["dedup_skipped"]] == ["mile_draft_cand"]
    # gap to the blocker (published 0.5h ago) is < threshold -> no drought rescue
    assert res["drought_override"] is None
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    draft = next(a for a in feed_after if a["id"] == "mile_draft_cand")
    assert draft["status"] == "draft"
    assert draft["details"]["release_dedup_skipped"] is True


def test_axis_waiver_blocks_text_dup_when_axis_unspecified(tmp_path: Path, monkeypatch):
    """Text-identical pair where the draft axis is unspecified -> stays a dup
    (the waiver only ever relaxes a near-dup on two SPECIFIED different axes)."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    monkeypatch.setattr(content, "find_arc_duplicates", lambda *a, **k: [])

    feed = [
        _published_blocker(frozen_now, "market_structure"),
        _draft_candidate(frozen_now, None),  # no arc_signature -> unspecified
    ]
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert res["released"] == []
    assert [s["id"] for s in res["dedup_skipped"]] == ["mile_draft_cand"]
    assert res["drought_override"] is None


# ===========================================================================
# Part 2 — drought circuit-breaker
# ===========================================================================

def _blocked_draft(draft_id: str, frozen_now: datetime, *, body: str, created_days: float) -> dict:
    return {
        "id": draft_id,
        "title": "共同主題標題",
        "status": "draft",
        "audience": "general",
        "created_at": (frozen_now - timedelta(days=created_days)).isoformat(),
        "content": body,
    }


def test_drought_forces_one_release_when_all_blocked_and_gap_exceeds_threshold(
    tmp_path: Path, monkeypatch
):
    """All drafts dedup-blocked + reader-facing gap > 4h -> force-release the
    least dup-like draft exactly once, stamped with the override audit trail."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    blocker = {
        "id": "mile_pub_old",
        "title": "共同主題標題",
        "status": "published",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=6)).isoformat(),  # gap 6h > 4h
        "created_at": (frozen_now - timedelta(hours=6)).isoformat(),
        "content": _BASE_BODY,
    }
    # Both drafts are surface near-dups of the blocker (Jaccard >= 0.45) so both
    # are dedup-blocked. d_low has the LOWER max-Jaccard (0.557 vs 1.0) so the
    # breaker must pick it as the least dup-like.
    d_high = _blocked_draft("mile_draft_high", frozen_now, body=_BASE_BODY, created_days=2)
    d_low = _blocked_draft("mile_draft_low", frozen_now, body=_BASE_BODY + _NOVEL_TAIL, created_days=2)
    _write_json(storage_dir / "reports" / "feed.json", [blocker, d_high, d_low])

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert res["released_count"] == 1
    assert res["released"][0]["id"] == "mile_draft_low"
    assert res["released"][0]["drought_override"] is True
    override = res["drought_override"]
    assert override is not None
    assert override["id"] == "mile_draft_low"
    assert override["gap_hours"] == 6.0
    # least dup-like: strictly below the byte-identical draft's 1.0 max-Jaccard
    assert content._RELEASE_DEDUP_JACCARD <= override["max_jaccard"] < 1.0
    assert override["blocked_pool_size"] == 2

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    chosen = next(a for a in feed_after if a["id"] == "mile_draft_low")
    other = next(a for a in feed_after if a["id"] == "mile_draft_high")
    assert chosen["status"] == "published"
    assert chosen["published_at"] == frozen_now.isoformat()
    assert chosen["details"]["release_drought_override"] is True
    assert chosen["details"]["release_drought_override_at"] == frozen_now.isoformat()
    assert "drought" in chosen["details"]["release_drought_override_reason"].lower()
    # cooldown flag cleared on the intentionally-published draft
    assert "release_dedup_skipped" not in chosen["details"]
    # only ONE draft is rescued; the more dup-like one stays a draft
    assert other["status"] == "draft"
    assert other["details"]["release_dedup_skipped"] is True


def test_drought_breaks_tie_on_newest_created_at(tmp_path: Path, monkeypatch):
    """When blocked drafts tie on max-Jaccard, pick the newest created_at."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    blocker = {
        "id": "mile_pub_old",
        "title": "共同主題標題",
        "status": "published",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=6)).isoformat(),
        "content": _BASE_BODY,
    }
    older = _blocked_draft("mile_draft_older", frozen_now, body=_BASE_BODY, created_days=5)
    newer = _blocked_draft("mile_draft_newer", frozen_now, body=_BASE_BODY, created_days=1)
    _write_json(storage_dir / "reports" / "feed.json", [blocker, older, newer])

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert res["released_count"] == 1
    assert res["drought_override"]["id"] == "mile_draft_newer"


def test_drought_does_not_trigger_when_gap_below_threshold(tmp_path: Path, monkeypatch):
    """Same all-blocked setup but gap < 4h -> no override, drafts stay draft."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    blocker = {
        "id": "mile_pub_recent",
        "title": "共同主題標題",
        "status": "published",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=2)).isoformat(),  # gap 2h < 4h
        "content": _BASE_BODY,
    }
    d1 = _blocked_draft("mile_draft_1", frozen_now, body=_BASE_BODY, created_days=2)
    _write_json(storage_dir / "reports" / "feed.json", [blocker, d1])

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert res["released"] == []
    assert res["drought_override"] is None
    assert [s["id"] for s in res["dedup_skipped"]] == ["mile_draft_1"]
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert next(a for a in feed_after if a["id"] == "mile_draft_1")["status"] == "draft"


def test_drought_not_triggered_when_normal_eligible_draft_releases(tmp_path: Path, monkeypatch):
    """A normally-eligible (non-dup) draft releases on the normal path; the
    drought breaker stays dormant (it only fires when nothing was released)."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    # A published article on a DIFFERENT topic (Jaccard < 0.45) so the draft is
    # not a dup and releases normally.
    blocker = {
        "id": "mile_pub_unrelated",
        "title": "完全不同的主題",
        "status": "published",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=6)).isoformat(),
        "content": _NOVEL_TAIL,
    }
    fresh = _blocked_draft("mile_draft_fresh", frozen_now, body=_BASE_BODY, created_days=2)
    _write_json(storage_dir / "reports" / "feed.json", [blocker, fresh])

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert [r["id"] for r in res["released"]] == ["mile_draft_fresh"]
    assert res["drought_override"] is None
    assert res["dedup_skipped"] == []
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    fresh_after = next(a for a in feed_after if a["id"] == "mile_draft_fresh")
    assert fresh_after["status"] == "published"
    assert "release_drought_override" not in fresh_after.get("details", {})


def test_drought_anti_thrash_skips_when_recent_override_in_window(tmp_path: Path, monkeypatch):
    """A prior drought override still inside the anti-thrash window must block a
    second override even though the reader-facing gap exceeds the threshold."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    # Newest reader-facing published article is 6h old -> gap 6h > 4h (drought).
    blocker = {
        "id": "mile_pub_old",
        "title": "共同主題標題",
        "status": "published",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=6)).isoformat(),
        "content": _BASE_BODY,
    }
    # A recently-overridden article that was later retracted: it no longer counts
    # toward the reader-facing gap, but its override stamp (1h ago, < 4h window)
    # must still suppress a second override this run.
    recently_overridden = {
        "id": "mile_prev_override",
        "title": "先前被強制釋出後撤回",
        "status": "retracted",
        "audience": "general",
        "published_at": (frozen_now - timedelta(hours=1)).isoformat(),
        "details": {
            "release_drought_override": True,
            "release_drought_override_at": (frozen_now - timedelta(hours=1)).isoformat(),
        },
    }
    d1 = _blocked_draft("mile_draft_1", frozen_now, body=_BASE_BODY, created_days=2)
    _write_json(
        storage_dir / "reports" / "feed.json",
        [blocker, recently_overridden, d1],
    )

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True, storage_dir=str(storage_dir)
    )

    assert res["released"] == []
    assert res["drought_override"] is None
    assert [s["id"] for s in res["dedup_skipped"]] == ["mile_draft_1"]
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert next(a for a in feed_after if a["id"] == "mile_draft_1")["status"] == "draft"
