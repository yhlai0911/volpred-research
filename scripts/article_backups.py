"""Deprecated as of 2026-04-18 (Contentlayer pattern rollout).

Legacy module that backed up each feed item as an individual
`storage/reports/mile_*.json` file, or audited for missing singles.

Under the new Contentlayer pattern, `storage/reports/feed.json` is the
single canonical source of truth for all articles; individual mile_*.json
singles are archived under `storage/reports/_archive_mile_files/` and are
no longer written or read as a live source.

Both public functions are now safe no-op stubs that return the same
shape they used to, so existing callers (`supabase_sync.py`,
`src/volpred/ops/content.py::ensure_article_local_backups`) keep
working without behavior change.

Remove this file once no caller imports it.
"""
from __future__ import annotations

from pathlib import Path

ARTICLE_BODY_FIELDS = ("content", "description", "summary", "analysis")


def audit_local_article_backups(
    storage_dir: str | Path = "storage",
    *,
    include_non_published: bool = False,
) -> dict:
    """No-op stub (Contentlayer cutover). Returns a deprecation marker.

    Previously audited `storage/reports/mile_*.json` presence. Under
    Contentlayer these singles are archived and irrelevant.
    """
    return {
        "deprecated": True,
        "message": (
            "article_backups is deprecated after 2026-04-18 Contentlayer "
            "cutover; feed.json is the only canonical source."
        ),
        "storage_dir": str(Path(storage_dir)),
        "total_feed_items": 0,
        "published_items": 0,
        "tracked_items": 0,
        "report_file_count": 0,
        "missing_report_ids": [],
        "feed_only_ids": [],
        "bodyless_ids": [],
        "extra_report_ids": [],
        "skipped_without_id": 0,
        "recoverable": True,
        "fully_materialized": True,
    }


def ensure_local_article_backups(
    storage_dir: str | Path = "storage",
    *,
    repair: bool = False,
    include_non_published: bool = False,
) -> dict:
    """No-op stub (Contentlayer cutover). Never writes new singles.

    Under the Contentlayer pattern feed.json is canonical; individual
    mile_*.json singles have been archived. Attempting to "repair" them
    would reintroduce the very divergence problem this cutover fixed.
    """
    audit = audit_local_article_backups(
        storage_dir,
        include_non_published=include_non_published,
    )
    audit["repaired_ids"] = []
    audit["created_count"] = 0
    return audit
