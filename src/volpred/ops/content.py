from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

from scripts.article_backups import ensure_local_article_backups
from volpred.publisher.publisher import Publisher

from .common import dump_json, load_json, project_path, write_ops_snapshot
from scripts.supabase_sync import _patch_where, _select_rows, delete_article, sync_article

DEFAULT_RELEASE_SETTINGS = {
    "mode": "manual",
    "interval_minutes": 1440,
    "max_articles_per_run": 1,
    "due_only": True,
    "include_drafts": False,
    "preferred_audiences": [],
    "last_released_at": None,
    "updated_at": None,
}


def _feed_path(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "reports", "feed.json")


def _report_path(pub_id: str, storage_dir: str = "storage") -> Path:
    return project_path(storage_dir, "reports", f"{pub_id}.json")


def load_feed(storage_dir: str = "storage") -> list[dict]:
    return load_json(_feed_path(storage_dir), [])


def get_feed_item(pub_id: str, storage_dir: str = "storage") -> dict | None:
    for item in load_feed(storage_dir):
        if item.get("id") == pub_id:
            return item
    return None


def publish_milestone_article(
    title: str,
    description: str,
    *,
    phase: str,
    details: dict | None = None,
    tags: list[str] | None = None,
    status: str = "published",
    publish_at: str | None = None,
    audience: str | None = None,
    category: str | None = None,
    storage_dir: str = "storage",
) -> str:
    publisher = Publisher(storage_dir=storage_dir)
    return publisher.publish_milestone(
        title=title,
        description=description,
        phase=phase,
        details=details,
        tags=tags,
        status=status,
        publish_at=publish_at,
        audience=audience,
        category=category,
    )


def _normalize_release_settings(row: dict | None = None) -> dict:
    data = {**DEFAULT_RELEASE_SETTINGS, **(row or {})}
    mode = str(data.get("mode") or "manual").strip().lower()
    interval_minutes = data.get("interval_minutes")
    max_articles_per_run = data.get("max_articles_per_run")
    preferred_audiences = data.get("preferred_audiences") or []

    return {
        "mode": mode if mode in ("scheduled", "auto") else "manual",
        "interval_minutes": max(5, min(int(interval_minutes or 1440), 24 * 60 * 14)),
        "max_articles_per_run": max(1, min(int(max_articles_per_run or 1), 20)),
        "due_only": bool(data.get("due_only", True)),
        "include_drafts": bool(data.get("include_drafts", False)),
        "preferred_audiences": [
            str(value).strip()
            for value in preferred_audiences
            if isinstance(value, str) and value.strip()
        ],
        "last_released_at": data.get("last_released_at"),
        "updated_at": data.get("updated_at"),
    }


def _local_release_settings_path() -> Path:
    return project_path("storage", ".release_settings.json")


def get_content_release_settings() -> dict:
    """Read release settings from local JSON (no Supabase hit)."""
    local = _local_release_settings_path()
    data = load_json(local, None)
    if data is not None:
        return _normalize_release_settings(data)
    # First run or missing file: try Supabase once, then cache locally
    try:
        rows = _select_rows("content_release_settings", id="default")
        row = rows[0] if rows else None
    except Exception:
        row = None
    settings = _normalize_release_settings(row)
    dump_json(local, settings)
    return settings


def _update_content_release_settings(fields: dict) -> bool:
    """Update release settings in local JSON and optionally sync to Supabase."""
    local = _local_release_settings_path()
    current = load_json(local, {**DEFAULT_RELEASE_SETTINGS})
    payload = {**current, **fields, "updated_at": datetime.now(timezone.utc).isoformat()}
    dump_json(local, payload)
    # Best-effort Supabase sync (don't fail if DB is down)
    try:
        return _patch_where("content_release_settings", {"id": "default"}, payload)
    except Exception:
        return False


def _parse_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _article_audience(item: dict) -> str:
    audience = item.get("audience") or (item.get("details") or {}).get("audience")
    if isinstance(audience, str) and audience.strip():
        return audience.strip()
    return "uncategorized"


def release_pool_articles(
    *,
    pub_id: str | None = None,
    limit: int = 1,
    due_only: bool = True,
    include_drafts: bool | None = None,
    preferred_audiences: list[str] | None = None,
    update_last_released: bool = False,
    storage_dir: str = "storage",
) -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    feed = load_feed(storage_dir)
    now = datetime.now(timezone.utc)
    effective_include_drafts = include_drafts if include_drafts is not None else (not due_only)
    audience_priority = {
        audience: index
        for index, audience in enumerate(preferred_audiences or [])
    }

    def is_due(item: dict) -> bool:
        published_at = item.get("published_at")
        if item.get("status") == "draft":
            return effective_include_drafts
        if not due_only:
            return True
        if not isinstance(published_at, str) or not published_at.strip():
            return True
        try:
            return datetime.fromisoformat(published_at.replace("Z", "+00:00")) <= now
        except Exception:
            return True

    def sort_key(item: dict) -> tuple:
        published_at = str(item.get("published_at") or "")
        created_at = str(item.get("created_at") or "")
        audience = _article_audience(item)
        preferred_rank = audience_priority.get(audience, len(audience_priority))
        status = str(item.get("status") or "")
        # Sort: scheduled first, then audience priority, then FIFO (oldest created_at first)
        return (preferred_rank, 0 if status == "scheduled" else 1, created_at)

    candidates = [
        item for item in feed
        if item.get("status") in ({"scheduled", "draft"} if effective_include_drafts else {"scheduled"}) and is_due(item)
    ]
    candidates.sort(key=sort_key)

    if pub_id:
        candidates = [item for item in candidates if item.get("id") == pub_id]

    selected = candidates[: max(int(limit), 1)]
    released: list[dict] = []
    released_at = now.isoformat()

    for item in feed:
        if item not in selected:
            continue
        item["status"] = "published"
        item["published_at"] = released_at
        report_path = _report_path(str(item["id"]), storage_dir)
        if report_path.exists():
            report = load_json(report_path, {})
            report["status"] = "published"
            report["published_at"] = released_at
            dump_json(report_path, report)
            item = report
        released.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "status": item.get("status"),
            "published_at": item.get("published_at"),
        })
        publisher._sync_report_to_remote(str(item["id"]), item)
        sync_article(item, storage_dir=publisher.reports_dir.parent)
        try:
            from volpred.publisher.email_notifier import EmailNotifier

            EmailNotifier(storage_dir=str(publisher.reports_dir.parent)).notify_article_published(
                item,
                reason="release_pool",
            )
        except Exception:
            pass

    if released:
        dump_json(_feed_path(storage_dir), feed)
        publisher._sync_feed_to_remote()
        if update_last_released:
            _update_content_release_settings({"last_released_at": released_at})

    return {
        "requested_id": pub_id,
        "released_count": len(released),
        "released": released,
        "due_only": due_only,
        "include_drafts": effective_include_drafts,
        "preferred_audiences": list(preferred_audiences or []),
        "limit": max(int(limit), 1),
    }


def release_pool_by_settings(
    *,
    force: bool = False,
    storage_dir: str = "storage",
) -> dict:
    settings = get_content_release_settings()
    now = datetime.now(timezone.utc)
    last_released_at = _parse_datetime(settings.get("last_released_at"))
    next_release_at = None

    if last_released_at is not None:
        # Truncate last_released_at to minute precision to avoid sub-second
        # timing mismatches with cron (which fires at :00 seconds).
        last_minute = last_released_at.replace(second=0, microsecond=0)
        next_release_at = last_minute + timedelta(minutes=int(settings["interval_minutes"]))

    if not force:
        if settings["mode"] not in ("scheduled", "auto"):
            return {
                "mode": settings["mode"],
                "released_count": 0,
                "released": [],
                "skipped": True,
                "reason": "manual_mode",
                "settings": settings,
            }
        if next_release_at is not None and next_release_at > now:
            return {
                "mode": settings["mode"],
                "released_count": 0,
                "released": [],
                "skipped": True,
                "reason": "interval_not_due",
                "next_release_at": next_release_at.isoformat(),
                "settings": settings,
            }

    result = release_pool_articles(
        limit=int(settings["max_articles_per_run"]),
        due_only=bool(settings["due_only"]),
        include_drafts=bool(settings["include_drafts"]),
        preferred_audiences=list(settings["preferred_audiences"]),
        update_last_released=True,
        storage_dir=storage_dir,
    )
    return {
        **result,
        "mode": settings["mode"],
        "force": force,
        "skipped": False,
        "settings": settings,
    }


def preview_release_pool_by_settings(
    *,
    storage_dir: str = "storage",
) -> dict:
    settings = get_content_release_settings()
    now = datetime.now(timezone.utc)
    last_released_at = _parse_datetime(settings.get("last_released_at"))
    next_release_at = None
    if last_released_at is not None:
        last_minute = last_released_at.replace(second=0, microsecond=0)
        next_release_at = last_minute + timedelta(minutes=int(settings["interval_minutes"]))

    feed = load_feed(storage_dir)
    include_drafts = bool(settings["include_drafts"])
    due_only = bool(settings["due_only"])
    preferred_audiences = list(settings["preferred_audiences"])
    audience_priority = {
        audience: index
        for index, audience in enumerate(preferred_audiences)
    }

    def is_due(item: dict) -> bool:
        published_at = item.get("published_at")
        if item.get("status") == "draft":
            return include_drafts
        if not due_only:
            return True
        if not isinstance(published_at, str) or not published_at.strip():
            return True
        try:
            return datetime.fromisoformat(published_at.replace("Z", "+00:00")) <= now
        except Exception:
            return True

    def sort_key(item: dict) -> tuple:
        published_at = str(item.get("published_at") or "")
        created_at = str(item.get("created_at") or "")
        audience = _article_audience(item)
        preferred_rank = audience_priority.get(audience, len(audience_priority))
        status = str(item.get("status") or "")
        # Sort: scheduled first, then audience priority, then FIFO (oldest created_at first)
        return (preferred_rank, 0 if status == "scheduled" else 1, created_at)

    eligible_statuses = {"scheduled", "draft"} if include_drafts else {"scheduled"}
    pool_items = [item for item in feed if item.get("status") in {"draft", "scheduled"}]
    candidates = [item for item in pool_items if item.get("status") in eligible_statuses and is_due(item)]
    candidates.sort(key=sort_key)

    due_now = settings["mode"] == "scheduled" and (
        next_release_at is None or next_release_at <= now
    )

    next_candidates = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "status": item.get("status"),
            "audience": _article_audience(item),
            "published_at": item.get("published_at"),
            "created_at": item.get("created_at"),
        }
        for item in candidates[: max(int(settings["max_articles_per_run"]), 1)]
    ]

    return {
        "mode": settings["mode"],
        "settings": settings,
        "due_now": due_now,
        "next_release_at": next_release_at.isoformat() if next_release_at else None,
        "pool_counts": {
            "draft": sum(1 for item in pool_items if item.get("status") == "draft"),
            "scheduled": sum(1 for item in pool_items if item.get("status") == "scheduled"),
            "eligible": len(candidates),
        },
        "next_candidates": next_candidates,
    }


def build_platform_cycle_summary(
    *,
    storage_dir: str = "storage",
    source: str = "user",
    limit: int = 20,
    write_latest: bool = False,
) -> dict:
    from .questions import build_question_rerank_workflow

    release_preview = preview_release_pool_by_settings(storage_dir=storage_dir)
    ranking_workflow = build_question_rerank_workflow(
        source=source,
        limit=limit,
        storage_dir=storage_dir,
        write_latest=write_latest,
    )

    summary = {
        "workflow_name": "platform_cycle_summary",
        "generated_at": ranking_workflow.get("generated_at"),
        "release_preview": release_preview,
        "question_ranking": ranking_workflow,
        "suggestions": [],
    }

    if release_preview.get("due_now"):
        summary["suggestions"].append("內容池已到節奏釋出時間，可評估執行 release-pool-by-settings。")
    elif release_preview.get("mode") == "manual":
        summary["suggestions"].append("目前內容池為 manual 模式，如需自動節奏發布需先切換設定。")

    pending = (ranking_workflow.get("health") or {}).get("pending_evaluation", 0)
    if pending:
        summary["suggestions"].append(f"目前有 {pending} 題待評分會員問題，適合執行 6 小時重排流程。")

    if write_latest:
        target = write_ops_snapshot(
            "platform-cycle-summary-latest",
            summary,
            storage_dir=storage_dir,
        )
        summary["snapshot_path"] = str(target.relative_to(project_path()))

    return summary


def send_article_notification(
    pub_id: str,
    *,
    force_send: bool = False,
    storage_dir: str = "storage",
) -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    return publisher.send_article_notification(pub_id, force_send=force_send)


def send_daily_digest(
    *,
    target_date: str | None = None,
    force_send: bool = False,
    storage_dir: str = "storage",
) -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    parsed = None
    if target_date:
        parsed = datetime.fromisoformat(target_date).date()
    return publisher.send_daily_digest(target_date=parsed, force_send=force_send)


def unpublish_article(pub_id: str, storage_dir: str = "storage") -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    success = publisher.unpublish(pub_id)
    return {
        "id": pub_id,
        "found": success,
        "status": "unpublished" if success else "missing",
    }


def cleanup_test_post(pub_id: str, *, hard_delete: bool = False, storage_dir: str = "storage") -> dict:
    publisher = Publisher(storage_dir=storage_dir)
    feed = load_feed(storage_dir)
    had_feed_item = any(item.get("id") == pub_id for item in feed)
    report_path = _report_path(pub_id, storage_dir)
    had_report = report_path.exists()

    if not had_feed_item and not had_report:
        return {"id": pub_id, "found": False, "hard_delete": hard_delete}

    result = {
        "id": pub_id,
        "found": True,
        "hard_delete": hard_delete,
        "unpublished": publisher.unpublish(pub_id),
        "local_feed_removed": False,
        "local_report_deleted": False,
        "supabase_deleted": False,
    }

    if not hard_delete:
        return result

    trimmed_feed = [item for item in feed if item.get("id") != pub_id]
    if len(trimmed_feed) != len(feed):
        dump_json(_feed_path(storage_dir), trimmed_feed)
        result["local_feed_removed"] = True
        publisher._sync_feed_to_remote()  # internal use: keep remote feed in sync

    if report_path.exists():
        report_path.unlink()
        result["local_report_deleted"] = True

    result["supabase_deleted"] = delete_article(pub_id)
    return result


def ensure_article_local_backups(
    *,
    repair: bool = False,
    include_non_published: bool = False,
    storage_dir: str = "storage",
) -> dict:
    result = ensure_local_article_backups(
        storage_dir=storage_dir,
        repair=repair,
        include_non_published=include_non_published,
    )
    write_ops_snapshot("article-backups", result, storage_dir=storage_dir)
    return result
