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
from datetime import datetime, timezone
from pathlib import Path

from volpred.canonical_write import guard_canonical_write


def _norm_ts(value: str | None) -> str:
    """Normalize a timestamp string for cross-store comparison.

    Postgres returns timestamps with trailing microsecond zeros stripped
    (e.g. '...862770+00:00' -> '...86277+00:00'), which breaks naive
    string equality against feed.json's Python-isoformat timestamps.
    Parse both sides to datetime so equal instants compare equal.

    2026-07-20 (WS-C2): also normalize the UTC offset. feed.json stores
    Asia/Taipei-offset timestamps ('...T17:03:26+08:00') while Supabase
    returns the same instant as '...T09:03:26+00:00'. Comparing raw
    isoformat() strings marked those rows changed on every run, so the
    hourly reconcile job would re-UPDATE them forever (non-idempotent,
    permanently noisy). Convert to UTC before formatting so equal
    instants compare equal regardless of the stored offset.
    """
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat()
    except Exception:
        return str(value or "")


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from supabase_sync import (  # noqa: E402
    SERVER_RESIDENT_DETAILS_KEYS,
    _select_rows,
    classify_audience,
    projected_category,
    projected_content,
    projected_details,
    reconcile_article_deletes,
    sync_article,
)


def _fetch_supabase_article_tags() -> dict[str, list[str]]:
    """Return slug -> sorted list of tag names for every article.

    Tags live in a separate `article_tags` join table on Supabase, so
    title/status/published_at projections never reflect tag drift on
    their own. compute_diff needs explicit tag comparison or it will
    silently miss tag-only changes (e.g. K-id retroactive migration on
    2026-04-26 moved K-ids from tags into details.experiment_refs but
    feed-sync reported update=0 because no projected field changed).
    """
    article_rows = _select_rows("articles", select="id,slug", order_by="id")
    article_id_to_slug: dict[str, str] = {
        str(row["id"]): row["slug"]
        for row in article_rows
        if row.get("id") and row.get("slug")
    }
    if not article_id_to_slug:
        return {}

    join_rows = _select_rows(
        "article_tags", select="article_id,tag_id", order_by="article_id,tag_id"
    )
    tag_rows = _select_rows("tags", select="id,name", order_by="id")
    tag_id_to_name: dict[str, str] = {
        str(row["id"]): str(row["name"])
        for row in tag_rows
        if row.get("id") and row.get("name") is not None
    }

    slug_to_tags: dict[str, list[str]] = {}
    for join in join_rows:
        article_id = str(join.get("article_id") or "")
        tag_id = str(join.get("tag_id") or "")
        slug = article_id_to_slug.get(article_id)
        name = tag_id_to_name.get(tag_id)
        if not slug or not name:
            continue
        slug_to_tags.setdefault(slug, []).append(name)

    return {slug: sorted(names) for slug, names in slug_to_tags.items()}


def _feed_path(storage_dir: str | Path = "storage") -> Path:
    return Path(storage_dir) / "reports" / "feed.json"


def _load_feed(storage_dir: str | Path = "storage") -> list[dict]:
    feed, _feed_sha256 = _load_feed_snapshot(storage_dir)
    return feed


def _load_feed_snapshot(
    storage_dir: str | Path = "storage",
) -> tuple[list[dict], str]:
    """Parse feed objects and hash the exact same canonical byte snapshot."""

    p = _feed_path(storage_dir)
    payload = p.read_bytes() if p.exists() else b"[]"
    return (
        json.loads(payload),
        hashlib.sha256(payload).hexdigest(),
    )


def _warn_feed_sync(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[feed_sync] WARN {message}: "
        f"path={path} error={type(exc).__name__}: {exc}"
    )


def _fetch_supabase_articles() -> dict[str, dict]:
    """Return slug -> minimal row for diff comparison.

    2026-04-20: added `content` to projection so compute_diff can detect
    content drift — previously only title/status/published_at were compared,
    meaning post-publish content extensions (e.g. K1257 article 1625→2107
    CJK) would never trigger Supabase UPDATE. Cost trade-off: content per
    article averages ~5KB so ~5MB total for 1000 articles per sync pass,
    acceptable vs the correctness gain.

    2026-04-26: added `details` so compute_diff also catches changes inside
    the `details` jsonb (notably `experiment_refs` after the K-id retroactive
    migration). tags live in a separate join table — fetched by
    _fetch_supabase_article_tags().

    2026-07-15: added `audience`. Audience is reader-facing routing metadata,
    and a local audience correction must propagate even when title, status,
    timestamps, body, tags, and experiment refs are otherwise unchanged.

    2026-07-20 (WS-C3): added `category` and `phase`. compute_diff became the
    single change-detection engine for sync_full as well, so it must cover
    everything engine A's _article_hash covered — category was hash-covered
    but never compared here (a category fix would sync only via the hash
    engine), and phase is a written column both engines missed.
    """
    rows = _select_rows(
        "articles",
        select=(
            "slug,status,title,published_at,updated_at,content,details,"
            "audience,category,phase"
        ),
        order_by="id",
    )
    return {r["slug"]: r for r in rows if r.get("slug")}


def compute_diff(storage_dir: str | Path = "storage") -> dict:
    """Compare feed.json (canonical) against Supabase articles (projection).

    WS-C3 (2026-07-20): this is the SINGLE canonical change-detection engine.
    scripts/supabase_sync.py::sync_full delegates its per-article selection
    here; the parallel _article_hash/timestamp criterion was deleted. The
    invariant is: **compare every non-derived column sync_article() writes**
    (excerpt and proposer derive from content; author_id is constant; slug is
    the key), each via the same projection helper the writer uses.

    Returns dict with:
      - insert: slugs in feed but not DB
      - update: slugs in both but differ on (status/title/published_at/
        content/tags/audience/category/phase/details)
      - delete: slugs in DB but not feed
      - feed_count, db_count
    """
    feed = _load_feed(storage_dir)
    feed_by_slug: dict[str, dict] = {
        a["id"]: a for a in feed if isinstance(a, dict) and a.get("id")
    }
    db_by_slug = _fetch_supabase_articles()
    db_tags_by_slug = _fetch_supabase_article_tags()

    feed_keys = set(feed_by_slug)
    db_keys = set(db_by_slug)

    to_insert = sorted(feed_keys - db_keys)
    to_delete = sorted(db_keys - feed_keys)

    to_update: list[str] = []
    for slug in sorted(feed_keys & db_keys):
        f = feed_by_slug[slug]
        d = db_by_slug[slug]
        # 2026-04-20: include content hash in diff so post-publish content
        # extensions propagate to Supabase (K1257 article incident).
        # 2026-07-20 (WS-C2): hash the content sync_article() would actually
        # WRITE, not the raw feed text. The write path sanitizes markdown
        # table pipes and CJK-appositive em-dashes, so the stored projection
        # is deliberately not byte-identical to feed.json. Hashing raw feed
        # text marked 137/1854 articles changed on every run — the hourly
        # reconcile re-UPDATEd them forever and --quiet-when-clean was never
        # quiet, which is fatal for a safety net nobody then reads.
        feed_content = projected_content(f, verbose=False)
        db_content = d.get("content") or ""
        content_changed = (
            hashlib.md5(feed_content.encode("utf-8")).hexdigest()
            != hashlib.md5(db_content.encode("utf-8")).hexdigest()
        )

        # 2026-04-26: detect tag drift (article_tags join table). Without this
        # the K-id retroactive migration's tag changes never sync.
        feed_tags = sorted(
            str(t)
            for t in (f.get("tags") or [])
            if isinstance(t, str) and t.strip()
        )
        db_tags = db_tags_by_slug.get(slug, [])
        tags_changed = feed_tags != db_tags

        # Compare the exact projection sync_article() writes, rather than the
        # raw optional field. Seventy-five legacy published feed entries omit
        # top-level audience and are classified during sync; comparing raw
        # None to that derived remote value would enqueue them forever.
        feed_audience = classify_audience(f)
        db_audience = str(d.get("audience") or "")
        audience_changed = feed_audience != db_audience

        # WS-C3 (2026-07-20): engine-A parity fills. category was covered by
        # sync_full's _article_hash but never compared here — a category-only
        # fix would have stopped syncing once the hash engine was deleted.
        # details is now compared as the FULL projected jsonb (supersedes the
        # experiment_refs-only check: refs live inside details), so edits like
        # fb_post_url / event_series_slot / last_updated_at propagate. phase
        # is a written column BOTH engines missed; covered for the invariant
        # "every non-derived written column is compared". Projection helpers
        # are shared with the writer so the reconcile stays idempotent.
        category_changed = projected_category(f) != str(d.get("category") or "")
        phase_changed = str(f.get("phase") or "") != str(d.get("phase") or "")
        # Server-resident keys (view_display view-count seeds, PATCHed straight
        # into the DB by seed_article_view_counts.py) are legitimately absent
        # from canonical feed.json — stripped from BOTH sides so they are
        # neither reported as drift (first full-details dry-run: 1576/1854
        # rows flagged solely by them) nor kept alive by a stray feed copy.
        # A non-dict DB value (pre-_legacy-wrap rows) is compared as-is: it
        # can never equal the always-dict projection, so the row re-syncs
        # once and converges to the wrapped form the writer produces.
        strip = SERVER_RESIDENT_DETAILS_KEYS
        feed_details = {
            k: v for k, v in projected_details(f).items() if k not in strip
        }
        db_details = d.get("details")
        if db_details is None:
            db_details = {}
        if isinstance(db_details, dict):
            db_details = {k: v for k, v in db_details.items() if k not in strip}
        details_changed = feed_details != db_details

        if (
            (f.get("title") or "") != (d.get("title") or "")
            # Mirror the writer's missing-key default ("published") so a feed
            # entry without an explicit status compares equal to its own
            # stored projection instead of re-updating forever.
            or (f.get("status", "published") or "") != (d.get("status") or "")
            or audience_changed
            or _norm_ts(f.get("published_at")) != _norm_ts(d.get("published_at"))
            or content_changed
            or tags_changed
            or category_changed
            or phase_changed
            or details_changed
        ):
            to_update.append(slug)

    # Split to_delete into real drift (published in DB but missing from feed)
    # vs benign drafts (DB-only drafts that correctly don't belong in feed).
    # feed.json canonically contains only published articles, so drafts in DB
    # being "missing" from feed is expected state, not drift.
    real_deletes: list[str] = []
    draft_only: list[str] = []
    for slug in to_delete:
        db_status = (db_by_slug[slug].get("status") or "").lower()
        if db_status in ("draft", "scheduled"):
            draft_only.append(slug)
        else:
            real_deletes.append(slug)

    return {
        "insert": to_insert,
        "update": to_update,
        "delete": to_delete,
        "real_delete": real_deletes,
        "draft_only": draft_only,
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
    feed, canonical_feed_sha256 = _load_feed_snapshot(storage_dir)
    feed_by_slug: dict[str, dict] = {
        a["id"]: a for a in feed if isinstance(a, dict) and a.get("id")
    }

    upserts = _apply_safe_projection_upserts(
        diff,
        feed_by_slug=feed_by_slug,
        canonical_feed_sha256=canonical_feed_sha256,
        storage_dir=storage_dir,
    )
    inserted = upserts["inserted"]
    updated = upserts["updated"]
    deleted = 0
    failed = upserts["failed"]
    failures: list[dict] = list(upserts["failures"])

    # Destructive deletes are delegated to the single guarded owner
    # (supabase_sync.reconcile_article_deletes) rather than looping raw
    # _delete_where here. That owner enforces the floor/cap/dump invariants and
    # is also the step sync_full() runs, so both paths share one delete
    # implementation (anti-stacking). It recomputes ghosts from the same
    # feed.json/remote source of truth as compute_diff, so the removed set
    # matches diff["delete"] barring concurrent edits.
    reconcile: dict | None = None
    if allow_delete:
        reconcile = reconcile_article_deletes(storage_dir, apply=True)
        deleted = reconcile.get("deleted", 0)
        # An abort (floor/cap breach) means nothing was deleted — surface the
        # attempted-but-skipped count so the caller does not read it as success.
        if reconcile.get("aborted"):
            failed += reconcile.get("ghost_count", 0)
            failures.append({"op": "delete", "aborted": reconcile.get("reason")})
        else:
            failed += reconcile.get("failed", 0)

    return {
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "skipped_deletes": 0 if allow_delete else len(diff.get("delete", [])),
        "failed": failed,
        "failures": failures,
        "reconcile": reconcile,
        "safe_effect": upserts["safe_effect"],
    }


def _apply_safe_projection_upserts(
    diff: dict,
    *,
    feed_by_slug: dict[str, dict],
    canonical_feed_sha256: str,
    storage_dir: str | Path,
) -> dict:
    """Route safe upserts through the database-selected family owner.

    The legacy owner retains the established per-article path. The
    Operations Core owner receives one immutable, payload-bound batch; owner
    generation, WorkItem, EffectRequest/outbox, Primary Authority, provider
    read-back and settlement remain behind one formal interface. Deletes are
    intentionally absent from this module and continue through the guarded
    destructive owner in ``reconcile_article_deletes``.
    """

    insert_items = tuple(
        feed_by_slug[slug]
        for slug in diff.get("insert", ())
        if slug in feed_by_slug
    )
    update_items = tuple(
        feed_by_slug[slug]
        for slug in diff.get("update", ())
        if slug in feed_by_slug
    )
    if not insert_items and not update_items:
        return {
            "inserted": 0,
            "updated": 0,
            "failed": 0,
            "failures": [],
            "safe_effect": None,
        }

    from volpred.ops.delivery import (
        OwnedPublisherArticleReconcile,
        OwnedPublisherReconcileCommand,
        PublisherArticleReconcileEffectAdapter,
        PublisherArticleReconcileOwnershipLost,
        SupabaseArticleProjectionAdapter,
        SupabaseOwnedPublisherReconcileStore,
        encode_publisher_article_reconcile_payload,
    )

    store = SupabaseOwnedPublisherReconcileStore.from_environment()
    owner = store.read_owner()
    if owner.effect_family != "publisher.article.supabase.reconcile":
        raise PublisherArticleReconcileOwnershipLost(
            "publisher reconcile owner read returned the wrong effect family"
        )
    if owner.owner == "legacy":
        inserted = updated = failed = 0
        failures: list[dict] = []
        for operation, items in (
            ("insert", insert_items),
            ("update", update_items),
        ):
            for item in items:
                ok = sync_article(item, storage_dir=storage_dir)
                if ok:
                    if operation == "insert":
                        inserted += 1
                    else:
                        updated += 1
                else:
                    failed += 1
                    failures.append({"slug": item["id"], "op": operation})
        return {
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
            "failures": failures,
            "safe_effect": {
                "owner": owner.owner,
                "owner_generation": owner.generation,
                "mode": "legacy_per_article",
            },
        }
    if owner.owner != "operations_core":
        raise PublisherArticleReconcileOwnershipLost(
            f"unsupported publisher reconcile owner: {owner.owner}"
        )

    articles = tuple(
        sorted(
            (*insert_items, *update_items),
            key=lambda article: str(article["id"]),
        )
    )
    payload = encode_publisher_article_reconcile_payload(
        canonical_feed_sha256=canonical_feed_sha256,
        articles=articles,
    )
    effect_sha256 = hashlib.sha256(payload).hexdigest()
    worker_id = "effect-worker:publisher-article-reconcile"

    from volpred.ops.authority import build_supabase_host_authority_keepalive

    keepalive = build_supabase_host_authority_keepalive(
        authority_key="publisher:article.supabase.reconcile",
        holder_ref=worker_id,
    )
    keepalive.start()
    try:
        receipt = OwnedPublisherArticleReconcile(
            store=store,
            provider=PublisherArticleReconcileEffectAdapter(
                projection=SupabaseArticleProjectionAdapter(
                    storage_dir=storage_dir
                )
            ),
            primary_authority=keepalive,
            worker_id=worker_id,
        ).reconcile(
            OwnedPublisherReconcileCommand(
                idempotency_key=(
                    f"publisher:article-reconcile:{effect_sha256}"
                ),
                canonical_feed_sha256=canonical_feed_sha256,
                articles=articles,
                actor_ref="feed-sync:hourly-safe-reconcile",
            )
        )
    finally:
        keepalive.stop()

    if receipt.delivered:
        return {
            "inserted": len(insert_items),
            "updated": len(update_items),
            "failed": 0,
            "failures": [],
            "safe_effect": {
                "owner": owner.owner,
                "owner_generation": receipt.owner_generation,
                "effect_id": receipt.effect_id,
                "attempt_count": receipt.attempt_count,
                "disposition": receipt.disposition,
                "evidence_ref": receipt.evidence_ref,
                "evidence_sha256": receipt.evidence_sha256,
            },
        }

    failures = [
        {"slug": item["id"], "op": "reconcile"}
        for item in articles
    ]
    return {
        "inserted": 0,
        "updated": 0,
        "failed": len(failures),
        "failures": failures,
        "safe_effect": {
            "owner": owner.owner,
            "owner_generation": receipt.owner_generation,
            "effect_id": receipt.effect_id,
            "attempt_count": receipt.attempt_count,
            "disposition": receipt.disposition,
            "evidence_ref": receipt.evidence_ref,
            "evidence_sha256": receipt.evidence_sha256,
        },
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
    invalid_singles: list[str] = []
    single_paths = list(singles_dir.glob("mile_*.json"))
    for single_path in single_paths:
        try:
            single = json.loads(single_path.read_text(encoding="utf-8"))
        except Exception as exc:
            invalid_singles.append(str(single_path))
            _warn_feed_sync("single article JSON read failed; skipping", single_path, exc)
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
        guard_canonical_write(feed_path)
        feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2))

    return {
        "checked_singles": len(single_paths),
        "invalid_singles": len(invalid_singles),
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
    quiet_when_clean: bool = False,
) -> dict:
    """Top-level one-way sync entrypoint.

    Canonical flow: feed.json changes -> call this -> Supabase projection updated.
    Never call anything that writes back to feed.json from DB.

    `quiet_when_clean` (WS-C2): for the hourly reconcile job. When the diff is
    empty there is nothing to say, so suppress all output — an hourly safety
    net that prints a banner every run trains operators to ignore its log.
    Drift, and only drift, is worth a line.
    """
    diff = compute_diff(storage_dir=storage_dir)

    clean = not (diff["insert"] or diff["update"] or diff["real_delete"])
    if quiet_when_clean and clean:
        verbose = False

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
        return {
            "mode": "dry_run",
            "clean": clean,
            "acknowledged": None,
            "diff": diff,
        }

    result = apply_diff(diff, storage_dir=storage_dir, allow_delete=allow_delete)
    acknowledged = result.get("failed") == 0
    if verbose:
        print(
            f"[feed-sync] applied: inserted={result['inserted']} "
            f"updated={result['updated']} deleted={result['deleted']} "
            f"skipped_deletes={result['skipped_deletes']} failed={result['failed']}"
        )
    return {
        "mode": "apply",
        "clean": clean,
        "acknowledged": acknowledged,
        "diff": diff,
        "result": result,
    }
