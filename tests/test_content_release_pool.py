from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops import content


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


def test_release_pool_by_settings_updates_last_released_and_gates_followup_run(
    tmp_path: Path,
    monkeypatch,
):
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 120,
            "max_articles_per_run": 1,
            "due_only": True,
            "include_drafts": False,
            "preferred_audiences": [],
            "last_released_at": (frozen_now - timedelta(hours=3)).isoformat(),
            "updated_at": (frozen_now - timedelta(hours=3)).isoformat(),
        },
    )
    first_item = {
        "id": "mile_sched_1",
        "title": "Scheduled article 1",
        "status": "scheduled",
        "published_at": (frozen_now - timedelta(minutes=1)).isoformat(),
        "created_at": (frozen_now - timedelta(days=1)).isoformat(),
        "category": "general",
    }
    _write_json(storage_dir / "reports" / "feed.json", [first_item])

    result = content.release_pool_by_settings(storage_dir=str(storage_dir))
    settings = json.loads((storage_dir / ".release_settings.json").read_text(encoding="utf-8"))
    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))

    assert result["released_count"] == 1
    assert result["settings"]["last_released_at"] == frozen_now.isoformat()
    assert settings["last_released_at"] == frozen_now.isoformat()
    assert feed[0]["status"] == "published"
    assert feed[0]["published_at"] == frozen_now.isoformat()

    second_item = {
        "id": "mile_sched_2",
        "title": "Scheduled article 2",
        "status": "scheduled",
        "published_at": (frozen_now + timedelta(minutes=1)).isoformat(),
        "created_at": frozen_now.isoformat(),
        "category": "general",
    }
    _write_json(storage_dir / "reports" / "feed.json", feed + [second_item])

    followup_now = frozen_now + timedelta(hours=1)
    _freeze_content_now(monkeypatch, followup_now)
    followup = content.release_pool_by_settings(storage_dir=str(storage_dir))

    assert followup["skipped"] is True
    assert followup["reason"] == "interval_not_due"
    assert followup["next_release_at"] == (frozen_now + timedelta(hours=2)).isoformat()


def test_preview_release_pool_self_heals_stale_settings_from_feed_ignoring_member_qa(
    tmp_path: Path,
    monkeypatch,
):
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    published_general_at = datetime(2026, 4, 19, 5, 50, tzinfo=timezone.utc)
    published_member_qa_at = datetime(2026, 4, 19, 7, 50, tzinfo=timezone.utc)
    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "scheduled",
            "interval_minutes": 120,
            "max_articles_per_run": 1,
            "due_only": True,
            "include_drafts": False,
            "preferred_audiences": [],
            "last_released_at": "2026-04-19T01:27:42+00:00",
            "updated_at": "2026-04-19T01:28:01+00:00",
        },
    )
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_general_latest",
                "title": "General article",
                "status": "published",
                "published_at": published_general_at.isoformat(),
                "created_at": published_general_at.isoformat(),
                "category": "general",
            },
            {
                "id": "mile_member_qa_newer",
                "title": "Member QA article",
                "status": "published",
                "published_at": published_member_qa_at.isoformat(),
                "created_at": published_member_qa_at.isoformat(),
                "category": "member_qa",
            },
        ],
    )

    preview = content.preview_release_pool_by_settings(storage_dir=str(storage_dir))
    settings = json.loads((storage_dir / ".release_settings.json").read_text(encoding="utf-8"))

    assert settings["last_released_at"] == published_general_at.isoformat()
    assert preview["settings"]["last_released_at"] == published_general_at.isoformat()
    assert preview["next_release_at"] == (published_general_at + timedelta(hours=2)).isoformat()
    assert preview["due_now"] is True


def test_preview_release_pool_self_heals_ignores_daily_audience_articles(
    tmp_path: Path,
    monkeypatch,
):
    """2026-04-25 fix: daily strategy/position articles are emitted by
    daily_update.py at fixed cron times, never enter the release pool.
    They must NOT count toward last_released_at, otherwise they perpetually
    reset the 12h pool interval and starve real research/general drafts.
    """
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    published_general_at = datetime(2026, 4, 24, 13, 0, tzinfo=timezone.utc)
    published_daily_newer_at = datetime(2026, 4, 25, 1, 0, tzinfo=timezone.utc)
    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 720,
            "max_articles_per_run": 1,
            "due_only": True,
            "include_drafts": True,
            "preferred_audiences": [],
            "last_released_at": "2026-04-24T13:00:00+00:00",
            "updated_at": "2026-04-24T13:00:01+00:00",
        },
    )
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_general_pool_release",
                "title": "Real pool release (general)",
                "status": "published",
                "published_at": published_general_at.isoformat(),
                "created_at": published_general_at.isoformat(),
                "category": "general",
                "audience": "general",
            },
            {
                "id": "mile_daily_strategy",
                "title": "每日策略建議",
                "status": "published",
                "published_at": published_daily_newer_at.isoformat(),
                "created_at": published_daily_newer_at.isoformat(),
                "category": "general",
                "audience": "daily",
            },
        ],
    )

    preview = content.preview_release_pool_by_settings(storage_dir=str(storage_dir))
    settings = json.loads((storage_dir / ".release_settings.json").read_text(encoding="utf-8"))

    # last_released_at must reflect the general (pool) release at 04-24 13:00,
    # NOT the daily article at 04-25 01:00 — even though the daily is newer.
    assert settings["last_released_at"] == published_general_at.isoformat()
    assert preview["settings"]["last_released_at"] == published_general_at.isoformat()
    # 12h interval: 04-24 13:00 + 12h = 04-25 01:00; frozen now = 04-25 08:00 → due
    assert preview["due_now"] is True


def test_release_pool_by_settings_keeps_legacy_missing_last_released_first_run_behavior(
    tmp_path: Path,
    monkeypatch,
):
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 120,
            "max_articles_per_run": 1,
            "due_only": True,
            "include_drafts": False,
            "preferred_audiences": [],
            "updated_at": "2026-04-19T01:28:01+00:00",
        },
    )
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_first_run",
                "title": "First run scheduled article",
                "status": "scheduled",
                "published_at": None,
                "created_at": (frozen_now - timedelta(days=1)).isoformat(),
                "category": "general",
            }
        ],
    )

    result = content.release_pool_by_settings(storage_dir=str(storage_dir))
    settings = json.loads((storage_dir / ".release_settings.json").read_text(encoding="utf-8"))

    assert result["released_count"] == 1
    assert settings["last_released_at"] == frozen_now.isoformat()


def test_release_pool_theme_flood_gate_skips_saturated_theme(tmp_path: Path, monkeypatch):
    """2026-06-16 incident regression: release_pool must NOT flood the feed with
    same-theme general articles. 4 published 'model-comparison' articles already
    out — a 5th same-theme draft is dedup-skipped (flagged, kept draft), while a
    distinct-theme draft releases normally."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})

    model_body = "模型擂台賽：越複雜的模型不一定更準，老方法 GARCH 沒被淘汰，花俏的新版本沒贏。" * 4
    feed = []
    for i in range(4):
        feed.append({
            "id": f"mile_pubmodel{i}", "status": "published", "audience": "general",
            "published_at": (frozen_now - timedelta(days=1)).isoformat(),
            "title": f"模型擂台賽第{i}場：複雜模型沒更準", "content": model_body,
        })
    feed.append({
        "id": "mile_draftmodel", "status": "draft", "audience": "general",
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "title": "又一場模型擂台賽：花俏不等於更準", "content": model_body,
    })
    feed.append({
        "id": "mile_draftdistinct", "status": "draft", "audience": "general",
        "created_at": (frozen_now - timedelta(days=3)).isoformat(),
        "title": "鈾礦 ETF 的流動性與庫存週期",
        "content": "URA 基金 AUM 與鈾礦現貨庫存的關係，鈾礦 ETF 投資人結構與流動性主因。" * 4,
    })
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        limit=5, due_only=False, include_drafts=True, storage_dir=str(storage_dir),
    )
    skipped_ids = {s["id"] for s in res["dedup_skipped"]}
    released_ids = {r["id"] for r in res["released"]}
    assert "mile_draftmodel" in skipped_ids, "saturated-theme draft must be dedup-skipped"
    assert "mile_draftdistinct" in released_ids, "distinct-theme draft must release normally"

    # flag persisted — excluded from a subsequent release run (no infinite re-skip)
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    flagged = next(a for a in feed_after if a["id"] == "mile_draftmodel")
    assert flagged.get("details", {}).get("release_dedup_skipped") is True
    assert flagged.get("status") == "draft"


def test_release_pool_last3_narrative_cluster_filters_saturated_cluster(tmp_path: Path, monkeypatch):
    """Boss email-11752 regression: if 2 of last 3 published general/research
    articles are the same narrative cluster, release_pool should filter that
    cluster out of the next pick and backfill with a different-cluster draft.

    This intentionally uses generic titles and details.experiment_refs so the
    gate must consult knowledge.json K-id provenance rather than title keywords.
    """
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 16, 11, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    _write_json(
        storage_dir / "memory" / "knowledge.json",
        [
            {"experiment_id": "K431", "content": "GARCH model comparison result."},
            {"experiment_id": "K998", "content": "GJR-GARCH and EGARCH forecast comparison."},
            {"experiment_id": "K491", "content": "STGARCH model complexity follow-up."},
            {"experiment_id": "K800", "content": "VRP variance risk premium regime study."},
        ],
    )
    feed = [
        {
            "id": "mile_recent_garch_1",
            "status": "published",
            "audience": "general",
            "published_at": (frozen_now - timedelta(minutes=10)).isoformat(),
            "title": "近期模型文章一",
            "details": {"experiment_refs": ["K431"]},
        },
        {
            "id": "mile_recent_vrp",
            "status": "published",
            "audience": "general",
            "published_at": (frozen_now - timedelta(minutes=20)).isoformat(),
            "title": "近期風險溢酬文章",
            "details": {"experiment_refs": ["K800"]},
        },
        {
            "id": "mile_recent_garch_2",
            "status": "published",
            "audience": "research",
            "published_at": (frozen_now - timedelta(minutes=30)).isoformat(),
            "title": "近期模型文章二",
            "details": {"experiment_refs": ["K998"]},
        },
        {
            "id": "mile_draft_garch",
            "status": "draft",
            "audience": "general",
            "created_at": (frozen_now - timedelta(days=3)).isoformat(),
            "title": "下一篇候選一",
            "details": {"experiment_refs": ["K491"]},
        },
        {
            "id": "mile_draft_vrp",
            "status": "draft",
            "audience": "general",
            "created_at": (frozen_now - timedelta(days=2)).isoformat(),
            "title": "下一篇候選二",
            "details": {"experiment_refs": ["K800"]},
        },
    ]
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )

    assert res["narrative_cluster_pressure"]["blocked_clusters"] == ["garch"]
    assert [item["id"] for item in res["narrative_cluster_filtered"]] == ["mile_draft_garch"]
    assert [item["id"] for item in res["released"]] == ["mile_draft_vrp"]

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    garch = next(item for item in feed_after if item["id"] == "mile_draft_garch")
    vrp = next(item for item in feed_after if item["id"] == "mile_draft_vrp")
    assert garch["status"] == "draft"
    assert not garch.get("details", {}).get("release_dedup_skipped")
    assert vrp["status"] == "published"
