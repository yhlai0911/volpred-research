"""Supabase sync utility for v2 website.

Provides functions to sync research data to Supabase DB.
Used by record_and_publish.py and daily_update.py.

Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars
(or uses defaults from .env.local)
"""
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote

try:
    from scripts.article_backups import ensure_local_article_backups
except ImportError:
    from article_backups import ensure_local_article_backups

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # Try loading from .env.local
    _env_file = Path(__file__).resolve().parent.parent / ".env.local"
    if _env_file.exists():
        for line in _env_file.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "SUPABASE_URL" and not SUPABASE_URL:
                SUPABASE_URL = v
            elif k == "SUPABASE_SERVICE_ROLE_KEY" and not SUPABASE_KEY:
                SUPABASE_KEY = v
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. Set env vars or create .env.local")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

_ARTICLE_ID_CACHE: dict[str, str] = {}
_TAG_ID_CACHE: dict[str, int] = {}
_STRATEGY_SIGNAL_CACHE_BY_KEY: dict[str, dict] = {}
_STRATEGY_SIGNAL_CACHE_BY_NAME: dict[str, dict] = {}
_STRATEGY_SIGNAL_CACHE_LOADED = False


CONFLICT_KEYS = {
    "articles": "slug",
    "tags": "name",
    "article_tags": "article_id,tag_id",
    "papers": "id",
    "questions": "id",
    "question_articles": "question_id,article_id",
    "memory_entries": "id",
    "feature_flags": "feature",
    "strategy_signals": "strategy_name",
    "paper_trades": "strategy,trade_date",  # requires migration 018
    "market_daily": "trade_date",  # one row per trade_date (fixes 2026-04-17 bug: silent 400)

}

# Whitelist of columns allowed in market_daily table (migration 019).
# Any other keys (e.g. overnight_gap, gap_alert_level) must be stripped
# before POST or PostgREST returns 400 "column X does not exist".
# Root cause of 2026-04-12..17 silent sync failure.
_MARKET_DAILY_COLUMNS = {
    "trade_date",
    "spy_close", "spy_open",
    "gld_close", "gld_open",
    "tw50_close", "tw50_open",
    "nk225_close", "nk225_open",
    "vix_level",
    "sigma_spy_ann", "sigma_gld_ann",
}


def _post(table: str, data: list | dict) -> bool:
    """POST (upsert) to Supabase table. Returns success.
    Falls back to PATCH on 409 conflict.

    Note: schema-level column filtering is handled by the table-specific
    helpers (e.g. `sync_market_daily`) — `_post` stays generic.
    """
    if not SUPABASE_KEY:
        return False
    conflict = CONFLICT_KEYS.get(table)
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if conflict:
        url += f"?on_conflict={conflict}"
    payload = json.dumps(data if isinstance(data, list) else [data],
                         ensure_ascii=False).encode("utf-8")
    req = Request(url, data=payload, headers=HEADERS, method="POST")
    try:
        urlopen(req, timeout=15)
        return True
    except HTTPError as e:
        code = e.code
        e.read()  # consume error body
        if code == 409 and conflict:
            # Fallback: PATCH (update) existing rows
            return _patch(table, conflict, data)
        print(f"  Supabase {table} error: {code}")
        return False
    except Exception as e:
        print(f"  Supabase {table} error: {e}")
        return False


def _patch(table: str, conflict_key: str, data: list | dict) -> bool:
    """PATCH (update) existing rows by conflict key."""
    rows = data if isinstance(data, list) else [data]
    ok = True
    for row in rows:
        key_val = row.get(conflict_key)
        if key_val is None:
            continue
        url = f"{SUPABASE_URL}/rest/v1/{table}?{conflict_key}=eq.{key_val}"
        payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
        patch_headers = {**HEADERS, "Prefer": "return=minimal"}
        req = Request(url, data=payload, headers=patch_headers, method="PATCH")
        try:
            urlopen(req, timeout=15)
        except Exception:
            ok = False
    return ok


def _build_filter_query(filters: dict[str, object]) -> str:
    parts: list[str] = []
    for key, value in filters.items():
        if value is None:
            continue
        parts.append(f"{key}=eq.{quote(str(value), safe='')}")
    return "&".join(parts)


def _request_json(url: str, method: str = "GET", data: list | dict | None = None) -> list | dict | None:
    payload = None
    headers = {**HEADERS, "Prefer": ""}
    if data is not None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=payload, headers=headers, method=method)
    with urlopen(req, timeout=15) as resp:
        body = resp.read()
        if not body:
            return None
        return json.loads(body)


def _select_rows(table: str, *, select: str = "*", **filters: object) -> list[dict]:
    query = _build_filter_query(filters)
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={quote(select, safe=',*')}"
    if query:
        url = f"{url}&{query}"
    data = _request_json(url, method="GET")
    return data if isinstance(data, list) else []


def _select_rows_in(table: str, column: str, values: list[str], *, select: str = "*") -> list[dict]:
    if not values:
        return []
    encoded_values = ",".join(quote(str(value), safe='') for value in values)
    url = (
        f"{SUPABASE_URL}/rest/v1/{table}"
        f"?select={quote(select, safe=',*')}"
        f"&{column}=in.({encoded_values})"
    )
    data = _request_json(url, method="GET")
    return data if isinstance(data, list) else []


def _patch_where(table: str, filters: dict[str, object], row: dict) -> bool:
    query = _build_filter_query(filters)
    if not query:
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
    headers = {**HEADERS, "Prefer": "return=minimal"}
    req = Request(url, data=payload, headers=headers, method="PATCH")
    try:
        urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"  Supabase {table} patch error: {e}")
        return False


def _patch_where_returning(
    table: str, filters: dict[str, object], row: dict
) -> list[dict]:
    """PATCH rows matching filters, returning the affected rows.

    Empty list means no rows matched (useful for atomic conditional updates
    and cross-session race protection). Differs from _patch_where which
    returns True on any HTTP success regardless of rows affected.
    """
    query = _build_filter_query(filters)
    if not query:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
    headers = {**HEADERS, "Prefer": "return=representation"}
    req = Request(url, data=payload, headers=headers, method="PATCH")
    try:
        resp = urlopen(req, timeout=15)
        body = resp.read().decode("utf-8")
        if not body:
            return []
        data = json.loads(body)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  Supabase {table} patch-returning error: {e}")
        return []


def _delete_where(table: str, filters: dict[str, object]) -> bool:
    query = _build_filter_query(filters)
    if not query:
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    req = Request(url, headers={**HEADERS, "Prefer": "return=minimal"}, method="DELETE")
    try:
        urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"  Supabase {table} delete error: {e}")
        return False


def _slugify_strategy_key(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "strategy"


def _cache_strategy_signal(row: dict) -> dict:
    strategy_key = row.get("strategy_key")
    strategy_name = row.get("strategy_name")
    if isinstance(strategy_key, str) and strategy_key:
        _STRATEGY_SIGNAL_CACHE_BY_KEY[strategy_key] = row
    if isinstance(strategy_name, str) and strategy_name:
        _STRATEGY_SIGNAL_CACHE_BY_NAME[strategy_name] = row
    return row


def _load_strategy_signal_cache() -> None:
    global _STRATEGY_SIGNAL_CACHE_LOADED
    if _STRATEGY_SIGNAL_CACHE_LOADED:
        return
    try:
        rows = _select_rows(
            "strategy_signals",
            select="id,strategy_key,strategy_name,howto,description,color,articles,display_order,is_active",
        )
    except Exception:
        return
    for row in rows:
        _cache_strategy_signal(row)
    _STRATEGY_SIGNAL_CACHE_LOADED = True


def _get_article_id(slug: str) -> str | None:
    if slug in _ARTICLE_ID_CACHE:
        return _ARTICLE_ID_CACHE[slug]
    rows = _select_rows("articles", select="id", slug=slug)
    if not rows:
        return None
    article_id = rows[0].get("id")
    if isinstance(article_id, str) and article_id:
        _ARTICLE_ID_CACHE[slug] = article_id
        return article_id
    return None


def _get_tag_ids(tag_names: list[str]) -> dict[str, int]:
    normalized = [name.strip() for name in tag_names if isinstance(name, str) and name.strip()]
    missing = [name for name in normalized if name not in _TAG_ID_CACHE]
    if missing:
        try:
            rows = _select_rows_in("tags", "name", missing, select="id,name")
            for row in rows:
                name = row.get("name")
                tag_id = row.get("id")
                if isinstance(name, str) and name and isinstance(tag_id, int):
                    _TAG_ID_CACHE[name] = tag_id
                elif isinstance(name, str) and name and isinstance(tag_id, str) and tag_id.isdigit():
                    _TAG_ID_CACHE[name] = int(tag_id)
        except Exception as e:
            print(f"  Supabase tags lookup error: {e}")
    return {name: _TAG_ID_CACHE[name] for name in normalized if name in _TAG_ID_CACHE}


def _find_strategy_signal(strategy_key: str | None, strategy_name: str | None) -> dict | None:
    _load_strategy_signal_cache()

    if strategy_key and strategy_key in _STRATEGY_SIGNAL_CACHE_BY_KEY:
        return _STRATEGY_SIGNAL_CACHE_BY_KEY[strategy_key]

    if strategy_name and strategy_name in _STRATEGY_SIGNAL_CACHE_BY_NAME:
        return _STRATEGY_SIGNAL_CACHE_BY_NAME[strategy_name]

    if strategy_key:
        rows = _select_rows(
            "strategy_signals",
            select="id,strategy_key,strategy_name,howto,description,color,articles,display_order,is_active",
            strategy_key=strategy_key,
        )
        if rows:
            return _cache_strategy_signal(rows[0])

    if strategy_name:
        rows = _select_rows(
            "strategy_signals",
            select="id,strategy_key,strategy_name,howto,description,color,articles,display_order,is_active",
            strategy_name=strategy_name,
        )
        if rows:
            return _cache_strategy_signal(rows[0])

    return None


def classify_audience(item: dict) -> str:
    # Explicit audience in item or details takes priority
    explicit = item.get("audience") or (item.get("details") or {}).get("audience")
    if explicit and explicit != "general":  # "general" in details is legacy default, ignore
        return explicit
    phase = (item.get("phase") or "").lower()
    tags = [t.lower() for t in (item.get("tags") or [])]
    if phase == "member_qa" or "會員提問" in tags:
        return "member_qa"
    if phase == "general_content" or phase == "general_article" or "一般讀者" in tags:
        return "general"
    if "daily" in phase or "daily_update" in tags or "每日更新" in tags:
        return "daily"
    if "diary" in phase or "研究日記" in tags:
        return "diary"
    return "research"


def extract_proposer(item: dict) -> str | None:
    for field in ["content", "description"]:
        text = item.get(field) or ""
        match = re.search(r'\[提出:\s*(\w+)', text)
        if match:
            return match.group(1)
    return None


def sync_article(item: dict, storage_dir: str | Path = "storage") -> bool:
    """Sync a single article (feed item) to Supabase.

    Contentlayer pattern (2026-04-18): feed.json is canonical and now
    holds the complete content directly (post reconcile_content_from_singles).
    We no longer read mile_*.json singles as a content fallback.

    Defensive markdown-table sanitization (2026-04-29): even though
    publisher._append_to_feed is the primary sanitizer, this is the
    secondary belt-and-suspenders catch for content that bypassed the
    publisher path (legacy entries, manual edits, hot-fix scripts).
    Auto-escapes unescaped statistical-notation pipes like `|t|` inside
    markdown table cells before Supabase write.
    """
    content = item.get("content") or item.get("description") or ""
    if content:
        try:
            from volpred.publisher.markdown_table_sanitizer import (
                sanitize_markdown_tables,
            )
            sanitized, report = sanitize_markdown_tables(content)
            if report.changed:
                content = sanitized
                print(
                    f"  [supabase_sync] markdown_table_sanitizer auto-fixed "
                    f"{len(report.fixed_lines)} row(s) for "
                    f"{item.get('id', 'unknown')}: {report.summary()}"
                )
            if report.has_unfixed:
                print(
                    f"  [supabase_sync] WARN unfixable table rows for "
                    f"{item.get('id', 'unknown')}: lines={report.unfixed_lines}"
                )
        except Exception as exc:
            print(f"  [supabase_sync] markdown_table_sanitizer error: {exc}")
    row = {
        "slug": item.get("id", ""),
        "title": item.get("title", ""),
        "content": content,
        "excerpt": content[:200] + "..." if len(content) > 200 else content,
        "audience": classify_audience(item),
        "phase": item.get("phase"),
        "status": item.get("status", "published"),
        "category": item.get("category") or ("member_qa" if classify_audience(item) == "member_qa" else "milestone"),
        "proposer": extract_proposer(item),
        "author_id": "claude",
        "details": item.get("details"),
        "published_at": item.get("published_at"),
    }
    ok = _post("articles", row)
    if ok:
        # Sync tags
        tags = item.get("tags") or []
        if tags:
            tag_ok = _sync_article_tags(row["slug"], tags)
            if not tag_ok:
                print(f"  Warning: article synced but tags missing for {row['slug']}")
    return ok


def _sync_article_tags(slug: str, tags: list[str]) -> bool:
    """Sync tags for an article."""
    tag_names = list(dict.fromkeys(tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()))
    if not tag_names:
        return True

    # Upsert tags
    tag_rows = [{"name": tag_name} for tag_name in tag_names]
    if not _post("tags", tag_rows):
        print(f"  Supabase tag upsert failed for {slug}: {tag_names}")
        return False

    try:
        article_id = _get_article_id(slug)
        if not article_id:
            print(f"  Supabase article tag sync skipped for {slug}: article_id not found")
            return False
        tag_map = _get_tag_ids(tag_names)
        if len(tag_map) != len(tag_names):
            missing = [name for name in tag_names if name not in tag_map]
            print(f"  Supabase article tag sync incomplete for {slug}: missing tag ids for {missing}")
            return False

        # Delete existing article_tags then insert current set
        # (prevents stale tags from persisting after tag changes)
        _delete_where("article_tags", {"article_id": article_id})
        at_rows = []
        for tag_name in tag_names:
            tag_id = tag_map.get(tag_name)
            if tag_id:
                at_rows.append({"article_id": article_id, "tag_id": tag_id})
        if at_rows:
            return _post("article_tags", at_rows)
        print(f"  Supabase article tag sync skipped for {slug}: no article_tags rows built")
        return False
    except Exception as e:
        print(f"  Supabase article tag sync error for {slug}: {e}")
        return False


def sync_risk_forecast(data: dict) -> bool:
    """Sync risk forecast to Supabase."""
    return _post("risk_forecasts", {"data": data})


def sync_strategy_signal(
    strategy_name: str,
    weights: dict,
    vix_level: float | None = None,
    sigma_ann: float | None = None,
    display_order: int = 0,
    is_active: bool = True,
    *,
    strategy_key: str | None = None,
    howto: str | None = None,
    description: str | None = None,
    color: str | None = None,
    articles: list | None = None,
) -> bool:
    """Sync a strategy signal to Supabase while preserving metadata."""
    from datetime import datetime, timezone

    existing = _find_strategy_signal(strategy_key, strategy_name) or {}
    resolved_key = strategy_key or existing.get("strategy_key") or _slugify_strategy_key(strategy_name)

    row = {
        "strategy_key": resolved_key,
        "strategy_name": strategy_name,
        "weights": weights,
        "vix_level": vix_level,
        "sigma_ann": sigma_ann,
        "display_order": display_order if display_order is not None else existing.get("display_order", 0),
        "is_active": is_active,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "howto": howto if howto is not None else existing.get("howto") or "",
        "description": description if description is not None else existing.get("description") or "",
        "color": color if color is not None else existing.get("color") or "#6B7280",
        "articles": articles if articles is not None else existing.get("articles") or [],
    }

    if existing.get("id") is not None:
        ok = _patch_where("strategy_signals", {"id": existing["id"]}, row)
        if ok:
            _cache_strategy_signal({**existing, **row, "id": existing["id"]})
        return ok

    ok = _post("strategy_signals", row)
    if ok:
        _STRATEGY_SIGNAL_CACHE_BY_KEY.pop(resolved_key, None)
        _STRATEGY_SIGNAL_CACHE_BY_NAME.pop(strategy_name, None)
    return ok


def set_strategy_active(identifier: str, active: bool) -> bool:
    """Activate/deactivate strategy by key first, then by display name."""
    existing = _find_strategy_signal(identifier, identifier)
    if not existing:
        print(f"  Supabase strategy_signals error: strategy not found ({identifier})")
        return False
    return _patch_where("strategy_signals", {"id": existing["id"]}, {"is_active": active})


def sync_article_status(slug: str, status: str) -> bool:
    """Update article status (e.g. published/unpublished) by slug.

    Side effects:
    - If status becomes 'unpublished': auto-removes question_articles links
    - If status becomes 'published': auto-marks linked questions as 'answered'
    """
    ok = _patch_where("articles", {"slug": slug}, {"status": status})
    if ok and status == "unpublished":
        # Clean up question_articles links so questions page doesn't show dead links
        article_id = _get_article_id(slug)
        if article_id:
            rows = _select_rows("question_articles", select="question_id", article_id=article_id)
            for row in rows:
                _delete_where("question_articles", {"question_id": row.get("question_id"), "article_id": article_id})
    elif ok and status == "published":
        # Auto-mark linked questions as answered
        article_id = _get_article_id(slug)
        if article_id:
            rows = _select_rows("question_articles", select="question_id", article_id=article_id)
            import datetime
            now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for row in rows:
                qid = row.get("question_id")
                if qid:
                    q_rows = _select_rows("questions", select="id,status", id=qid)
                    if q_rows and q_rows[0].get("status") == "researching":
                        _patch_where("questions", {"id": qid}, {"status": "answered", "answered_at": now_utc})
    return ok


def delete_article(slug: str) -> bool:
    """Hard-delete an article row by slug. Manual cascade: article_impressions
    has NO ON DELETE CASCADE (per migrations/001), so we must pre-delete it.

    Returns True iff articles row is actually gone; False on any HTTP error.
    """
    # Resolve UUID first (article_impressions uses article_id uuid FK)
    article_id = _get_article_id(slug)
    if article_id:
        # Pre-delete the only non-CASCADE FK reference (BUG-001 fix 2026-04-18)
        _delete_where("article_impressions", {"article_id": article_id})
        # article_reactions / question_articles / article_tags / comments are
        # ON DELETE CASCADE (schema 001), so the final articles DELETE handles them.
    ok = _delete_where("articles", {"slug": slug})
    if not ok:
        # 409 / other error — don't silently succeed. Caller (cleanup_test_post)
        # must surface this to user.
        print(f"  [BUG-001 guard] articles DELETE for slug={slug} FAILED; row may still exist with FK blocker.")
    return ok


def _get_article_id(slug: str) -> str | None:
    """Fetch article UUID by slug (for FK cascade pre-delete)."""
    url = f"{SUPABASE_URL}/rest/v1/articles?select=id&slug=eq.{slug}"
    req = Request(url, headers=HEADERS, method="GET")
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data[0]["id"] if data else None
    except Exception:
        return None


def sync_paper_trade(strategy: str, entry: dict, trade_date: str) -> bool:
    """Sync a paper trade entry to Supabase paper_trades table.

    Uses upsert via on_conflict=strategy,trade_date (migration 018 added
    the unique constraint). Idempotent: same (strategy, trade_date) → one row.
    """
    if not SUPABASE_KEY or not trade_date:
        return False
    # Strip market data — prices live in market_daily table, not per-entry
    _MARKET_KEYS = {"spy_close", "spy_open", "gld_close", "gld_open", "tw50_close",
                    "tw50_open", "nk225_close", "nk225_open", "vix_close",
                    "sigma_spy_ann", "sigma_gld_ann"}
    clean_entry = {k: v for k, v in entry.items() if k not in _MARKET_KEYS}
    row = {
        "strategy": strategy,
        "entry": clean_entry,
        "trade_date": trade_date,
    }
    return _post("paper_trades", row)


def sync_market_daily(trade_date: str, market: dict) -> bool:
    """Upsert a single market_daily row. Strips unknown columns so we don't
    get silent PostgREST 400 when daily_update adds new keys (overnight_gap,
    gap_alert_level etc.).

    Root cause fix for 2026-04-12..17 outage: daily_update.py only sync'd
    `today` and included unknown keys; every request 400'd → market_daily
    table stuck at 2026-04-11 → frontend /portfolio trade log prices blank
    for all 10 active strategies.
    """
    if not SUPABASE_KEY or not trade_date or not isinstance(market, dict):
        return False
    row = {k: v for k, v in market.items() if k in _MARKET_DAILY_COLUMNS}
    row["trade_date"] = trade_date
    return _post("market_daily", row)


def sync_market_daily_backfill(market_daily: dict, since: str | None = None) -> tuple[int, int]:
    """Backfill market_daily from a local {trade_date: {...}} mapping.

    Returns (ok_count, fail_count). Iterating in date order lets the server
    idempotently upsert each row; any previous skipped day (e.g. due to the
    400 bug) is reconciled automatically on the next daily_update run.
    """
    if not SUPABASE_KEY or not market_daily:
        return (0, 0)
    ok = 0
    fail = 0
    for d in sorted(market_daily.keys()):
        if since and d < since:
            continue
        if sync_market_daily(d, market_daily[d]):
            ok += 1
        else:
            fail += 1
    return (ok, fail)


def sync_memory_entry(entry_id: str, entry_type: str, content: dict) -> bool:
    """Sync a single memory entry to Supabase."""
    row = {
        "id": entry_id,
        "type": entry_type,
        "content": content,
    }
    return _post("memory_entries", row)


def _load_sync_state(storage: Path) -> dict:
    """Load last sync timestamp per category."""
    state_path = storage / ".supabase_sync_state.json"
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {}


def _save_sync_state(storage: Path, state: dict):
    """Save sync state."""
    state_path = storage / ".supabase_sync_state.json"
    state_path.write_text(json.dumps(state, indent=2))


def sync_full(storage_dir: str | Path = "storage") -> dict:
    """Incremental sync: only upsert items changed since last sync.
    Falls back to full sync on first run or if state file is missing."""
    storage = Path(storage_dir)
    counts = {}
    backup_audit = ensure_local_article_backups(storage, repair=True)
    counts["article_backup_repairs"] = backup_audit.get("created_count", 0)
    counts["article_backup_bodyless"] = len(backup_audit.get("bodyless_ids", []))
    state = _load_sync_state(storage)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Articles — sync from reports/feed.json (SINGLE source of truth)
    # storage/feed.json is DEPRECATED — do not read from it
    feed = []
    feed_mtime = 0
    for fp in [storage / "reports" / "feed.json"]:
        if fp.exists():
            feed_mtime = max(feed_mtime, fp.stat().st_mtime)
            items = json.loads(fp.read_text())
            if isinstance(items, dict):
                items = items.get("items", [])
            seen_ids = {a.get("id") for a in feed if isinstance(a, dict)}
            for item in items:
                if isinstance(item, dict) and item.get("id") not in seen_ids:
                    feed.append(item)
    if feed:
        last_feed_sync = state.get("feed_mtime", 0)
        if feed_mtime > last_feed_sync:
            last_sync_ts = state.get("articles_last_ts", "")
            # Sync articles published/updated after last sync, OR drafts with created_at after last sync
            to_sync = [item for item in feed
                       if (item.get("published_at") or item.get("created_at") or "") > last_sync_ts
                       or not last_sync_ts]
            ok = 0
            for item in to_sync:
                report_path = storage / "reports" / f"{item['id']}.json"
                if report_path.exists():
                    report = json.loads(report_path.read_text())
                    if report.get("content"):
                        item["content"] = report["content"]
                if sync_article(item, storage_dir=storage):
                    ok += 1
            counts["articles"] = ok
            state["feed_mtime"] = feed_mtime
            if feed:
                state["articles_last_ts"] = max(
                    (item.get("published_at") or item.get("created_at") or "") for item in feed
                )
        else:
            counts["articles"] = 0  # skipped, unchanged

    # Risk forecast — always sync (small, 1 row)
    rf_path = storage / "risk_forecast.json"
    if rf_path.exists():
        rf = json.loads(rf_path.read_text())
        sync_risk_forecast(rf)
        counts["risk_forecast"] = 1

    # Memory — only sync entries added since last sync count
    memory_dir = storage / "memory"
    sources = {
        "thinking": "thinking_journal.json",
        "knowledge": "knowledge.json",
        "experiment": "experiments.json",
        "log": "research_log.json",
    }
    for mem_type, filename in sources.items():
        path = memory_dir / filename
        if path.exists():
            entries = json.loads(path.read_text())
            last_count = state.get(f"{mem_type}_count", 0)
            # Only sync new entries (appended at the end)
            new_entries = entries[last_count:] if last_count < len(entries) else []
            ok = 0
            for i, entry in enumerate(new_entries):
                idx = last_count + i
                eid = str(entry.get("id") or entry.get("item_id") or f"{mem_type}_{idx:04d}")
                if sync_memory_entry(eid, mem_type, entry):
                    ok += 1
            counts[mem_type] = ok
            state[f"{mem_type}_count"] = len(entries)

    _save_sync_state(storage, state)
    return counts


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "full":
        print("Running incremental sync to Supabase...")
        counts = sync_full()
        for k, v in counts.items():
            print(f"  {k}: {v}")
        print("Done.")
    elif len(sys.argv) > 1 and sys.argv[1] == "force-full":
        # Delete state file to force full resync
        state_path = Path("storage") / ".supabase_sync_state.json"
        if state_path.exists():
            state_path.unlink()
        print("Running FULL resync (state cleared)...")
        counts = sync_full()
        for k, v in counts.items():
            print(f"  {k}: {v}")
        print("Done.")
    else:
        print("Usage: python scripts/supabase_sync.py full          # incremental")
        print("       python scripts/supabase_sync.py force-full    # full resync")
