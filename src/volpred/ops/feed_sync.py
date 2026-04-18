"""Feed ↔ Supabase one-way sync (Contentlayer pattern).

storage/reports/feed.json is the canonical source of truth.
Supabase `articles` table is a read-only projection.

This module:
  1. reads feed.json
  2. queries Supabase articles
  3. computes INSERT / UPDATE / DELETE diff
  4. applies diff (or reports it in dry-run)

It never reads Supabase as authority; it only writes projection.
Reverse writes (Supabase -> feed.json) are forbidden by design.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


def _norm_ts(value: str | None) -> str:
    """Normalize a timestamp string for cross-store comparison.

    Postgres returns timestamps with trailing microsecond zeros stripped
    (e.g. '...862770+00:00' -> '...86277+00:00'), which breaks naive
    string equality against feed.json's Python-isoformat timestamps.
    Parse both sides to datetime so equal instants compare equal.
    """
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.isoformat()
    except Exception:
        return str(value or "")


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from supabase_sync import (  # noqa: E402
    _select_rows,
    _delete_where,
    sync_article,
)


def _feed_path(storage_dir: str | Path = "storage") -> Path:
    return Path(storage_dir) / "reports" / "feed.json"


def _load_feed(storage_dir: str | Path = "storage") -> list[dict]:
    p = _feed_path(storage_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text())


def _fetch_supabase_articles() -> dict[str, dict]:
    """Return slug -> minimal row for diff comparison."""
    rows = _select_rows(
        "articles",
        select="slug,status,title,published_at,updated_at",
    )
    return {r["slug"]: r for r in rows if r.get("slug")}


def _item_fingerprint(item: dict) -> str:
    """Stable fingerprint for a feed item (for change detection)."""
    parts = [
        str(item.get("title") or ""),
        str(item.get("status") or ""),
        str(item.get("published_at") or ""),
        str(item.get("audience") or ""),
        # content hash (cheap)
        hashlib.md5(
            (item.get("content") or item.get("description") or "").encode("utf-8")
        ).hexdigest(),
    ]
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _row_fingerprint(row: dict) -> str:
    parts = [
        str(row.get("title") or ""),
        str(row.get("status") or ""),
        str(row.get("published_at") or ""),
    ]
    # content hash not available from minimal query; caller triggers UPDATE
    # only when any visible field differs — content drift is detected by
    # status/title/published_at change on the feed side.
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()[:16]


def compute_diff(storage_dir: str | Path = "storage") -> dict:
    """Compare feed.json (canonical) against Supabase articles (projection).

    Returns dict with:
      - insert: slugs in feed but not DB
      - update: slugs in both but differ on (status/title/published_at)
      - delete: slugs in DB but not feed
      - feed_count, db_count
    """
    feed = _load_feed(storage_dir)
    feed_by_slug: dict[str, dict] = {
        a["id"]: a for a in feed if isinstance(a, dict) and a.get("id")
    }
    db_by_slug = _fetch_supabase_articles()

    feed_keys = set(feed_by_slug)
    db_keys = set(db_by_slug)

    to_insert = sorted(feed_keys - db_keys)
    to_delete = sorted(db_keys - feed_keys)

    to_update: list[str] = []
    for slug in sorted(feed_keys & db_keys):
        f = feed_by_slug[slug]
        d = db_by_slug[slug]
        if (
            (f.get("title") or "") != (d.get("title") or "")
            or (f.get("status") or "") != (d.get("status") or "")
            or _norm_ts(f.get("published_at")) != _norm_ts(d.get("published_at"))
        ):
            to_update.append(slug)

    return {
        "insert": to_insert,
        "update": to_update,
        "delete": to_delete,
        "feed_count": len(feed_by_slug),
        "db_count": len(db_by_slug),
    }


def apply_diff(
    diff: dict,
    *,
    storage_dir: str | Path = "storage",
    allow_delete: bool = False,
) -> dict:
    """Apply computed diff to Supabase.

    Args:
      diff: output of compute_diff()
      allow_delete: if False, deletes are skipped (safety default).
        feed.json is canonical, so a slug disappearing from feed means
        it was explicitly removed — but we still require an explicit
        flag to run destructive DELETE against production.

    Returns dict of counters: {inserted, updated, deleted, failed}.
    """
    feed = _load_feed(storage_dir)
    feed_by_slug: dict[str, dict] = {
        a["id"]: a for a in feed if isinstance(a, dict) and a.get("id")
    }

    inserted = updated = deleted = failed = 0
    failures: list[dict] = []

    for slug in diff.get("insert", []):
        item = feed_by_slug.get(slug)
        if not item:
            continue
        ok = sync_article(item, storage_dir=storage_dir)
        if ok:
            inserted += 1
        else:
            failed += 1
            failures.append({"slug": slug, "op": "insert"})

    for slug in diff.get("update", []):
        item = feed_by_slug.get(slug)
        if not item:
            continue
        # sync_article uses on_conflict=slug, so POST doubles as UPSERT.
        ok = sync_article(item, storage_dir=storage_dir)
        if ok:
            updated += 1
        else:
            failed += 1
            failures.append({"slug": slug, "op": "update"})

    if allow_delete:
        for slug in diff.get("delete", []):
            ok = _delete_where("articles", {"slug": slug})
            if ok:
                deleted += 1
            else:
                failed += 1
                failures.append({"slug": slug, "op": "delete"})

    return {
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped_deletes": 0 if allow_delete else len(diff.get("delete", [])),
        "failed": failed,
        "failures": failures,
    }


def reconcile_content_from_singles(
    *,
    storage_dir: str | Path = "storage",
    dry_run: bool = True,
    min_gain: int = 100,
) -> dict:
    """Pre-Phase-3 one-shot: merge longer content from mile_*.json singles
    back into feed.json before the single files are archived.

    Singles have historically been written as a second source (Phase 0 bug).
    For 25+ items the single has more complete content than the feed entry.
    Once feed.json holds the complete content, singles can be safely archived.

    Only updates feed entries where the single's content is at least
    `min_gain` chars longer than the feed's current content (safe default,
    avoids noisy small-diff updates).

    Returns counters; writes feed.json only when dry_run=False.
    """
    from urllib.parse import quote as _q  # noqa: F401 (future use)

    feed_path = _feed_path(storage_dir)
    feed = _load_feed(storage_dir)
    feed_by_id: dict[str, dict] = {
        a["id"]: a for a in feed if isinstance(a, dict) and a.get("id")
    }

    singles_dir = Path(storage_dir) / "reports"
    updated: list[dict] = []
    for single_path in singles_dir.glob("mile_*.json"):
        try:
            single = json.loads(single_path.read_text())
        except Exception:
            continue
        sid = single.get("id")
        if not sid or sid not in feed_by_id:
            continue
        fc = feed_by_id[sid].get("content") or ""
        sc = single.get("content") or ""
        if len(sc) >= len(fc) + min_gain:
            updated.append({
                "id": sid,
                "feed_len": len(fc),
                "single_len": len(sc),
                "gain": len(sc) - len(fc),
            })
            if not dry_run:
                feed_by_id[sid]["content"] = sc
                # also hydrate description if it's much shorter
                fd = feed_by_id[sid].get("description") or ""
                sd = single.get("description") or ""
                if len(sd) > len(fd):
                    feed_by_id[sid]["description"] = sd

    if not dry_run and updated:
        # Preserve original feed order (feed list carries same dict refs,
        # so mutations are already in place).
        feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2))

    return {
        "checked_singles": len(list(singles_dir.glob("mile_*.json"))),
        "updated": len(updated),
        "examples": updated[:5],
        "mode": "dry_run" if dry_run else "apply",
    }


def sync_feed_to_supabase(
    *,
    storage_dir: str | Path = "storage",
    dry_run: bool = True,
    allow_delete: bool = False,
    verbose: bool = True,
) -> dict:
    """Top-level one-way sync entrypoint.

    Canonical flow: feed.json changes -> call this -> Supabase projection updated.
    Never call anything that writes back to feed.json from DB.
    """
    diff = compute_diff(storage_dir=storage_dir)

    if verbose:
        print(
            f"[feed-sync] feed={diff['feed_count']} db={diff['db_count']} "
            f"insert={len(diff['insert'])} update={len(diff['update'])} "
            f"delete={len(diff['delete'])}"
        )
        sample_cap = 5
        if diff["insert"]:
            print(f"  sample insert: {diff['insert'][:sample_cap]}")
        if diff["update"]:
            print(f"  sample update: {diff['update'][:sample_cap]}")
        if diff["delete"]:
            print(f"  sample delete: {diff['delete'][:sample_cap]}")

    if dry_run:
        if verbose:
            print("[feed-sync] dry-run: no writes performed")
        return {"mode": "dry_run", "diff": diff}

    result = apply_diff(diff, storage_dir=storage_dir, allow_delete=allow_delete)
    if verbose:
        print(
            f"[feed-sync] applied: inserted={result['inserted']} "
            f"updated={result['updated']} deleted={result['deleted']} "
            f"skipped_deletes={result['skipped_deletes']} failed={result['failed']}"
        )
    return {"mode": "apply", "diff": diff, "result": result}
