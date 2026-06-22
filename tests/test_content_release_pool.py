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


def test_get_content_release_settings_warns_when_supabase_read_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    storage_dir = tmp_path / "storage"

    def fail_select(*args, **kwargs):
        raise RuntimeError("remote unavailable")

    monkeypatch.setattr(content, "_select_rows", fail_select)

    settings = content.get_content_release_settings(storage_dir=str(storage_dir))

    captured = capsys.readouterr()
    assert settings["mode"] == "manual"
    assert settings["interval_minutes"] == 1440
    assert (storage_dir / ".release_settings.json").exists()
    assert "[content_release_settings] WARN Supabase read failed" in captured.out
    assert "RuntimeError: remote unavailable" in captured.out


def test_update_content_release_settings_warns_when_supabase_patch_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    storage_dir = tmp_path / "storage"
    _write_json(storage_dir / ".release_settings.json", {"mode": "manual"})

    def fail_patch(*args, **kwargs):
        raise RuntimeError("patch denied")

    monkeypatch.setattr(content, "_patch_where", fail_patch)

    ok = content._update_content_release_settings(
        {"mode": "auto"},
        storage_dir=str(storage_dir),
    )

    settings = json.loads((storage_dir / ".release_settings.json").read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert ok is False
    assert settings["mode"] == "auto"
    assert "[content_release_settings] WARN Supabase patch failed" in captured.out
    assert "RuntimeError: patch denied" in captured.out


def test_release_pool_notification_failure_warns_without_blocking(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 4, 19, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    from volpred.publisher.email_notifier import EmailNotifier

    def fail_notify(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(EmailNotifier, "notify_article_published", fail_notify)
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
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_notify_fail",
                "title": "Scheduled article",
                "status": "scheduled",
                "published_at": (frozen_now - timedelta(minutes=1)).isoformat(),
                "created_at": (frozen_now - timedelta(days=1)).isoformat(),
                "category": "general",
            }
        ],
    )

    result = content.release_pool_by_settings(storage_dir=str(storage_dir))

    captured = capsys.readouterr()
    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert result["released_count"] == 1
    assert feed[0]["status"] == "published"
    assert "[email_notify] article notification failed for mile_notify_fail" in captured.out
    assert "(release_pool): smtp down" in captured.out


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


def test_preview_release_pool_excludes_active_dedup_flags(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 22, 9, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 180,
            "max_articles_per_run": 2,
            "due_only": True,
            "include_drafts": True,
            "preferred_audiences": [],
            "last_released_at": (frozen_now - timedelta(hours=7)).isoformat(),
            "updated_at": (frozen_now - timedelta(hours=7)).isoformat(),
        },
    )
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_active_dedup",
                "title": "Active dedup draft",
                "status": "draft",
                "created_at": (frozen_now - timedelta(days=3)).isoformat(),
                "category": "general",
                "details": {
                    "release_dedup_skipped": True,
                    "release_dedup_skipped_at": (frozen_now - timedelta(days=1)).isoformat(),
                },
            },
            {
                "id": "mile_expired_dedup",
                "title": "Expired dedup draft",
                "status": "draft",
                "created_at": (frozen_now - timedelta(days=2)).isoformat(),
                "category": "general",
                "details": {
                    "release_dedup_skipped": True,
                    "release_dedup_skipped_at": (frozen_now - timedelta(days=22)).isoformat(),
                },
            },
        ],
    )

    preview = content.preview_release_pool_by_settings(storage_dir=str(storage_dir))

    assert preview["pool_counts"]["eligible_before_dedup"] == 2
    assert preview["pool_counts"]["dedup_flagged"] == 1
    assert preview["pool_counts"]["eligible"] == 1
    assert [item["id"] for item in preview["next_candidates"]] == ["mile_expired_dedup"]


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


def test_release_pool_theme_flood_gate_throttles_saturated_theme(tmp_path: Path, monkeypatch):
    """2026-06-19 follow-up: saturated themes are throttled, not sealed.

    4 published model-comparison articles already exist. The oldest same-theme
    draft gets one per-run valve release; a second same-theme draft is skipped,
    while a distinct-theme draft releases normally.
    """
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})

    model_body = "模型擂台賽：越複雜的模型不一定更準，老方法 GARCH 沒被淘汰，花俏的新版本沒贏。" * 4
    valve_body = "越複雜的預測模型不一定比較準，更多參數常常只是增加估計噪音，簡單基準仍要留在檯面上。" * 4
    second_body = "模型加權和集成看似更聰明，但若樣本外沒有改善，複雜度本身不能算真的贏。" * 4
    feed = []
    for i in range(4):
        feed.append({
            "id": f"mile_pubmodel{i}", "status": "published", "audience": "general",
            "published_at": (frozen_now - timedelta(days=1)).isoformat(),
            "title": f"模型擂台賽第{i}場：複雜模型沒更準", "content": model_body,
        })
    feed.append({
        "id": "mile_draftmodel_old", "status": "draft", "audience": "general",
        "created_at": (frozen_now - timedelta(days=4)).isoformat(),
        "title": "又一場模型擂台賽：花俏不等於更準", "content": valve_body,
    })
    feed.append({
        "id": "mile_draftdistinct", "status": "draft", "audience": "general",
        "created_at": (frozen_now - timedelta(days=3)).isoformat(),
        "title": "鈾礦 ETF 的流動性與庫存週期",
        "content": "URA 基金 AUM 與鈾礦現貨庫存的關係，鈾礦 ETF 投資人結構與流動性主因。" * 4,
    })
    feed.append({
        "id": "mile_draftmodel_new", "status": "draft", "audience": "general",
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "title": "模型加在一起也不一定打敗老方法", "content": second_body,
    })
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        limit=5, due_only=False, include_drafts=True, storage_dir=str(storage_dir),
    )
    skipped_ids = {s["id"] for s in res["dedup_skipped"]}
    released_ids = {r["id"] for r in res["released"]}
    valve_ids = {v["id"] for v in res["theme_valves"]}
    assert "mile_draftmodel_old" in released_ids, "oldest saturated-theme draft gets valve release"
    assert "mile_draftmodel_old" in valve_ids
    assert "mile_draftmodel_new" in skipped_ids, "second same-theme draft must be throttled"
    assert "mile_draftdistinct" in released_ids, "distinct-theme draft must release normally"

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    valve = next(a for a in feed_after if a["id"] == "mile_draftmodel_old")
    flagged = next(a for a in feed_after if a["id"] == "mile_draftmodel_new")
    assert valve["status"] == "published"
    assert valve.get("details", {}).get("release_theme_valve") is True
    assert flagged.get("details", {}).get("release_dedup_skipped") is True
    assert flagged.get("status") == "draft"


def test_release_pool_by_settings_releases_oldest_saturated_theme_via_valve(
    tmp_path: Path,
    monkeypatch,
):
    """2026-06-19 follow-up: max_articles_per_run=1 should not seal a
    saturated theme forever. The oldest same-theme draft gets the per-run
    valve release; later fresh-theme drafts wait for the next scheduled run.
    """
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 120,
            "max_articles_per_run": 1,
            "due_only": True,
            "include_drafts": True,
            "preferred_audiences": [],
            "last_released_at": (frozen_now - timedelta(hours=3)).isoformat(),
            "updated_at": (frozen_now - timedelta(hours=3)).isoformat(),
        },
    )

    model_body = "模型擂台賽：越複雜的模型不一定更準，老方法沒被淘汰，花俏的新版本沒贏。" * 4
    valve_body = "越複雜的預測模型不一定比較準，更多參數常常只是增加估計噪音，簡單基準仍要留在檯面上。" * 4
    feed = []
    for i in range(4):
        feed.append({
            "id": f"mile_pubmodel{i}",
            "status": "published",
            "audience": "general",
            "published_at": (frozen_now - timedelta(days=1, minutes=i)).isoformat(),
            "created_at": (frozen_now - timedelta(days=1, minutes=i)).isoformat(),
            "title": f"模型擂台賽第{i}場：複雜模型沒更準",
            "content": model_body,
        })
    feed.extend(
        [
            {
                "id": "mile_old_saturated",
                "status": "draft",
                "audience": "general",
                "created_at": (frozen_now - timedelta(days=5)).isoformat(),
                "title": "又一場模型擂台賽：花俏不等於更準",
                "content": valve_body,
            },
            {
                "id": "mile_fresh_theme",
                "status": "draft",
                "audience": "general",
                "created_at": (frozen_now - timedelta(days=4)).isoformat(),
                "title": "鈾礦 ETF 的庫存週期與流動性",
                "content": "URA 基金 AUM、鈾礦現貨庫存、ETF 投資人結構與流動性條件的關係。" * 4,
            },
        ]
    )
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_by_settings(storage_dir=str(storage_dir))

    assert res["released_count"] == 1
    assert [item["id"] for item in res["released"]] == ["mile_old_saturated"]
    assert [item["id"] for item in res["theme_valves"]] == ["mile_old_saturated"]
    assert res["dedup_skipped"] == []
    assert res["settings"]["last_released_at"] == frozen_now.isoformat()

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    saturated = next(item for item in feed_after if item["id"] == "mile_old_saturated")
    fresh = next(item for item in feed_after if item["id"] == "mile_fresh_theme")
    assert saturated["status"] == "published"
    assert saturated["details"]["release_theme_valve"] is True
    assert saturated["details"]["release_theme_valve_theme"] == "model_complexity"
    assert saturated["published_at"] == frozen_now.isoformat()
    assert fresh["status"] == "draft"


def test_release_pool_audit_skip_materializes_fix_task_after_three_strikes(
    tmp_path: Path,
    monkeypatch,
):
    """Repeated audit-skip drafts should become visible work, not cron noise."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_audit_bad",
                "status": "draft",
                "audience": "general",
                "created_at": (frozen_now - timedelta(days=2)).isoformat(),
                "title": "一般讀者文章仍混入研究術語",
                "description": "本文仍寫 Harvey threshold、t=3.2、p=0.01，應先修稿再釋出。",
                "tags": ["一般讀者", "FOMC"],
                "details": {"release_audit_skipped_count": 2},
            }
        ],
    )

    res = content.release_pool_articles(
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )

    assert res["released_count"] == 0
    assert res["audit_materialized"] == [
        {
            "id": "mile_audit_bad",
            "title": "一般讀者文章仍混入研究術語",
            "task_id": "platform_ops_release_audit_fix_mile_audit_bad",
            "skip_count": 3,
        }
    ]
    skipped = res["audit_skipped"][0]
    assert skipped["skip_count"] == 3
    assert skipped["materialized_task"] == {
        "created": True,
        "task_id": "platform_ops_release_audit_fix_mile_audit_bad",
    }

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    draft = feed_after[0]
    assert draft["status"] == "draft"
    assert draft["details"]["release_audit_skipped_count"] == 3
    assert draft["details"]["release_audit_task_id"] == "platform_ops_release_audit_fix_mile_audit_bad"
    assert "禁用統計術語" in draft["details"]["release_audit_issues"][0]

    tasks = json.loads((storage_dir / "next_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "platform_ops_release_audit_fix_mile_audit_bad"
    assert task["task_type"] == "platform_ops"
    assert task["dispatch_lane"] == "agent"
    assert task["priority"] == 3
    assert task["status"] == "pending"
    assert task["article_id"] == "mile_audit_bad"
    assert "release_pool skipped draft `mile_audit_bad` 3 times" in task["description"]

    rerun = content.release_pool_articles(
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )
    tasks_after = json.loads((storage_dir / "next_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks_after) == 1
    assert rerun["audit_skipped"][0]["skip_count"] == 4
    assert rerun["audit_skipped"][0]["materialized_task"] == {
        "created": False,
        "reason": "task_already_exists",
        "task_id": "platform_ops_release_audit_fix_mile_audit_bad",
    }


def test_release_pool_audit_skip_before_materialize_stays_draft(
    tmp_path: Path,
    monkeypatch,
):
    """Audit failures below the materialize threshold must not fall through."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_audit_first_strike",
                "status": "draft",
                "audience": "general",
                "created_at": (frozen_now - timedelta(days=2)).isoformat(),
                "title": "第一次 audit fail 不能釋出",
                "description": "本文仍寫 t=3.2、p=0.01，應該先留在草稿。",
                "tags": ["一般讀者", "FOMC"],
            }
        ],
    )

    res = content.release_pool_articles(
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )

    assert res["released_count"] == 0
    assert res["audit_materialized"] == []
    assert res["audit_skipped"][0]["id"] == "mile_audit_first_strike"
    assert res["audit_skipped"][0]["skip_count"] == 1
    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert feed_after[0]["status"] == "draft"
    assert feed_after[0]["details"]["release_audit_skipped_count"] == 1


def test_release_pool_relocates_internal_review_tag_before_general_audit(
    tmp_path: Path,
    monkeypatch,
):
    """Internal workflow tags must not make a general draft fail tag-cap audit."""
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 21, 11, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "mile_reviewed_general",
                "status": "draft",
                "audience": "general",
                "created_at": (frozen_now - timedelta(days=2)).isoformat(),
                "title": "一般讀者審查標記不應卡住釋出",
                "description": "這是一篇白話文章，沒有禁用統計術語，只有內部審查 tag 需要搬走。",
                "tags": [
                    "一般讀者",
                    "指數調整",
                    "成分股調整",
                    "ETF",
                    "Russell",
                    "收盤競價",
                    "流動性",
                    "風險管理",
                    "codex-24h-rule-reviewed",
                ],
                "details": {
                    "release_audit_skipped_count": 3,
                    "release_audit_issues": ["general tag count 9 > 8"],
                    "release_audit_task_id": "platform_ops_release_audit_fix_mile_reviewed_general",
                },
            }
        ],
    )

    res = content.release_pool_articles(
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )

    assert res["released_count"] == 1
    assert res["audit_skipped"] == []

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    article = feed_after[0]
    assert article["status"] == "published"
    assert "codex-24h-rule-reviewed" not in article["tags"]
    assert len(article["tags"]) == 8
    details = article["details"]
    assert details["release_internal_tags"] == ["codex-24h-rule-reviewed"]
    assert details["codex_24h_rule_reviewed"] is True
    assert details["release_audit_status"] == "resolved"
    assert details["release_audit_resolved_issues"] == ["general tag count 9 > 8"]
    assert "release_audit_issues" not in details


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


def test_release_pool_pub_id_bypasses_narrative_cluster_filter_for_manual_repair(
    tmp_path: Path,
    monkeypatch,
):
    """A requested pub_id is an explicit repair/release target.

    The last-3 narrative valve should still shape automatic pool selection, but
    it must not hide a specific article from release-time audit resolution.
    """
    storage_dir = tmp_path / "storage"
    frozen_now = datetime(2026, 6, 21, 11, 30, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)

    feed = [
        {
            "id": "mile_recent_garch_1",
            "status": "published",
            "audience": "general",
            "published_at": (frozen_now - timedelta(minutes=10)).isoformat(),
            "title": "GARCH 模型近期文章一",
        },
        {
            "id": "mile_recent_vrp",
            "status": "published",
            "audience": "general",
            "published_at": (frozen_now - timedelta(minutes=20)).isoformat(),
            "title": "VRP 近期文章",
        },
        {
            "id": "mile_recent_garch_2",
            "status": "published",
            "audience": "research",
            "published_at": (frozen_now - timedelta(minutes=30)).isoformat(),
            "title": "GARCH 模型近期文章二",
        },
        {
            "id": "mile_target_garch",
            "status": "draft",
            "audience": "general",
            "created_at": (frozen_now - timedelta(days=3)).isoformat(),
            "title": "GARCH 草稿已修正",
            "description": "這篇一般讀者草稿已改成白話統計描述，可以重新釋出。",
            "tags": ["一般讀者", "GARCH", "波動率"],
            "details": {
                "release_audit_skipped_count": 3,
                "release_audit_issues": ["general 內容含禁用統計術語"],
                "release_audit_task_id": "platform_ops_release_audit_fix_mile_target_garch",
            },
        },
    ]
    _write_json(storage_dir / "reports" / "feed.json", feed)

    res = content.release_pool_articles(
        pub_id="mile_target_garch",
        limit=1,
        due_only=False,
        include_drafts=True,
        storage_dir=str(storage_dir),
    )

    assert res["narrative_cluster_pressure"]["blocked_clusters"] == ["garch"]
    assert res["narrative_cluster_filtered"] == []
    assert res["audit_skipped"] == []
    assert [item["id"] for item in res["released"]] == ["mile_target_garch"]

    feed_after = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    target = next(item for item in feed_after if item["id"] == "mile_target_garch")
    assert target["status"] == "published"
    assert target["details"]["release_audit_status"] == "resolved"
    assert target["details"]["release_audit_resolved_issues"] == ["general 內容含禁用統計術語"]
    assert "release_audit_issues" not in target["details"]
