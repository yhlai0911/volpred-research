from __future__ import annotations

import json
from pathlib import Path

ARTICLE_BODY_FIELDS = ("content", "description", "summary", "analysis")


def _load_feed(feed_path: Path) -> list[dict]:
    if not feed_path.exists():
        return []
    raw = json.loads(feed_path.read_text())
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return [item for item in raw["items"] if isinstance(item, dict)]
    return []


def _extract_article_body(item: dict) -> str:
    for field in ARTICLE_BODY_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def audit_local_article_backups(
    storage_dir: str | Path = "storage",
    *,
    include_non_published: bool = False,
) -> dict:
    storage = Path(storage_dir)
    reports_dir = storage / "reports"
    feed = _load_feed(reports_dir / "feed.json")
    report_files = sorted(
        path.stem
        for path in reports_dir.glob("*.json")
        if path.name != "feed.json"
    )

    tracked_items: list[dict] = []
    missing_report_ids: list[str] = []
    bodyless_ids: list[str] = []
    feed_only_ids: list[str] = []
    skipped_without_id = 0

    for item in feed:
        status = str(item.get("status") or "published")
        if not include_non_published and status != "published":
            continue
        pub_id = str(item.get("id") or item.get("pub_id") or "").strip()
        if not pub_id:
            skipped_without_id += 1
            continue

        tracked_items.append(item)
        report_path = reports_dir / f"{pub_id}.json"
        feed_body = _extract_article_body(item)
        report_body = ""

        if report_path.exists():
            report = json.loads(report_path.read_text())
            if isinstance(report, dict):
                report_body = _extract_article_body(report)
        else:
            missing_report_ids.append(pub_id)
            if feed_body:
                feed_only_ids.append(pub_id)

        if not feed_body and not report_body:
            bodyless_ids.append(pub_id)

    tracked_ids = {
        str(item.get("id") or item.get("pub_id") or "").strip()
        for item in tracked_items
        if str(item.get("id") or item.get("pub_id") or "").strip()
    }

    return {
        "storage_dir": str(storage),
        "total_feed_items": len(feed),
        "published_items": sum(
            1 for item in feed if str(item.get("status") or "published") == "published"
        ),
        "tracked_items": len(tracked_items),
        "report_file_count": len(report_files),
        "missing_report_ids": sorted(missing_report_ids),
        "feed_only_ids": sorted(feed_only_ids),
        "bodyless_ids": sorted(bodyless_ids),
        "extra_report_ids": sorted(set(report_files) - tracked_ids),
        "skipped_without_id": skipped_without_id,
        "recoverable": not bodyless_ids,
        "fully_materialized": not missing_report_ids,
    }


def ensure_local_article_backups(
    storage_dir: str | Path = "storage",
    *,
    repair: bool = False,
    include_non_published: bool = False,
) -> dict:
    audit = audit_local_article_backups(
        storage_dir,
        include_non_published=include_non_published,
    )
    audit["repaired_ids"] = []

    if not repair or not audit["missing_report_ids"]:
        return audit

    storage = Path(storage_dir)
    reports_dir = storage / "reports"
    feed = _load_feed(reports_dir / "feed.json")
    feed_map = {
        str(item.get("id") or item.get("pub_id") or "").strip(): item
        for item in feed
        if isinstance(item, dict) and str(item.get("id") or item.get("pub_id") or "").strip()
    }

    repaired_ids: list[str] = []
    for pub_id in audit["missing_report_ids"]:
        item = feed_map.get(pub_id)
        if not item:
            continue
        if not _extract_article_body(item):
            continue
        payload = dict(item)
        payload.setdefault("id", pub_id)
        report_path = reports_dir / f"{pub_id}.json"
        report_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        )
        repaired_ids.append(pub_id)

    repaired_audit = audit_local_article_backups(
        storage_dir,
        include_non_published=include_non_published,
    )
    repaired_audit["repaired_ids"] = repaired_ids
    repaired_audit["created_count"] = len(repaired_ids)
    return repaired_audit
