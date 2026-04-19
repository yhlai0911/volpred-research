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
