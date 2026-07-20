"""Supabase sync utility for v2 website.

Provides functions to sync research data to Supabase DB.
Used by record_and_publish.py and daily_update.py.

Requires: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars
(or uses defaults from .env.local)
"""
import hashlib
import json
import os
import re
import socket
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

try:
    from scripts.article_backups import ensure_local_article_backups
except ImportError:
    from article_backups import ensure_local_article_backups

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")


def _all_remote_access_blocked() -> bool:
    """True when the process is forbidden from both reading and writing Supabase.

    Pytest sets both guards before collection. Loading production credentials in
    that state is unnecessary and makes collection depend on the gitignored
    `.env.local` that a clean CI checkout cannot have.
    """
    return (
        os.environ.get("VOLPRED_NO_REMOTE_WRITE") == "1"
        and os.environ.get("VOLPRED_NO_REMOTE_READ") == "1"
    )


if (not SUPABASE_URL or not SUPABASE_KEY) and not _all_remote_access_blocked():
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

_MISSING_CREDS = (
    "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY. Set env vars or create .env.local"
)


def require_creds() -> None:
    """Raise if Supabase credentials are absent. Call before any remote request.

    Importing this module used to `raise` here (2026-07-10 and earlier). That made
    the module un-importable without credentials, and since `volpred.ops.__init__`
    imports it transitively, **pytest collection died in any environment without
    `.env.local`** — which is why CI has never been able to run the test suite.
    Credentials are a *request-time* requirement, not an *import-time* one.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(_MISSING_CREDS)


def _remote_writes_blocked() -> bool:
    """Test-mode kill switch for ALL Supabase writes.

    conftest.py sets VOLPRED_NO_REMOTE_WRITE=1 so no test can POST/PATCH
    production Supabase even when creds are present (loaded from .env.local at
    import) and a per-test sync stub is missing. 2026-06-23 incident:
    test_daily_digest_dup_exemption.py published two stub daily_digest rows
    (mile_46918766 / mile_6d06f91c, phase='test', identical MOVE-VIX content) to
    PROD because its supabase_sync stub failed to apply — they leaked onto the
    live 精選導讀 feed and had to be retracted. This is the structural backstop,
    mirroring VOLPRED_NO_EMAIL for SMTP (conftest set at 2026-04-20)."""
    return os.environ.get("VOLPRED_NO_REMOTE_WRITE") == "1"


def _remote_reads_blocked() -> bool:
    """Test-mode kill switch for ALL Supabase reads.

    VOLPRED_NO_REMOTE_WRITE stops tests corrupting prod. It does nothing about reads,
    so a test with an incomplete stub silently queries LIVE production and its verdict
    then tracks today's prod data. 2026-04-26: tests/test_feed_sync.py stubbed
    `_fetch_supabase_articles` but not `_fetch_supabase_article_tags`, whose
    `_select_rows` calls went to prod. Two of its tests were still flipping between
    pass and fail across runs 40 minutes apart on 2026-07-10, with no code change on
    that path.

    Reads fail LOUD rather than returning an empty result: a silent empty read is
    indistinguishable from "nothing in the DB" and would turn a missing stub into a
    green test asserting the wrong thing (.claude/rules/no-silent-fallback.md).
    """
    return os.environ.get("VOLPRED_NO_REMOTE_READ") == "1"


_RETRY_MAX_ATTEMPTS = 3
_RETRY_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_replay_safe(req) -> bool:
    """Whether re-sending this request can add a second row.

    GET/PATCH/DELETE address rows by filter and a POST carrying ``on_conflict``
    is an upsert, so replaying any of them converges on the same state. A bare
    POST does not: if the timeout struck after the server had committed the
    insert, a retry would duplicate the row.
    """
    method = req.get_method()
    if method in {"GET", "PATCH", "DELETE"}:
        return True
    if method == "POST":
        return "on_conflict=" in req.full_url
    return False


def _is_transient(exc: BaseException) -> bool:
    """Whether the failure is the network flaking rather than a real rejection."""
    if isinstance(exc, HTTPError):  # subclass of URLError — must be checked first
        return exc.code in _RETRY_HTTP_STATUS
    if isinstance(exc, URLError):
        return isinstance(exc.reason, (socket.timeout, TimeoutError, ConnectionError, OSError))
    return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError))


def _urlopen(req, timeout: int = 15):
    """Single egress chokepoint for every Supabase HTTP call.

    Gating here rather than at each of the seven request helpers means a newly added
    read cannot forget the switch — the same reasoning as the HEADERS guard below.

    The same chokepoint absorbs transient network failures. A single timed-out
    socket used to abort whichever caller happened to be running: on 2026-07-16
    it exited `paper_sync_all` non-zero (raising a critical host_cron_fail for a
    blip that cured itself) and failed the publish read-back of an article that
    had in fact synced. Only replay-safe requests are retried, so absorbing a
    flake can never duplicate a row.
    """
    if req.get_method() == "GET" and _remote_reads_blocked():
        raise RuntimeError(
            f"Blocked live Supabase read of {req.full_url.split('?')[0]} because "
            "VOLPRED_NO_REMOTE_READ=1 (set by root conftest.py). A test reached "
            "production Supabase, which makes its result depend on live data. Stub "
            "the fetch helper this call path uses instead of relaxing the switch."
        )
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            return urlopen(req, timeout=timeout)
        except Exception as exc:
            last = attempt == _RETRY_MAX_ATTEMPTS
            if last or not _is_transient(exc) or not _is_replay_safe(req):
                raise
            delay = 2 ** (attempt - 1)
            print(
                f"  [supabase_sync] WARN transient {type(exc).__name__} on "
                f"{req.get_method()} {req.full_url.split('?')[0]} "
                f"(attempt {attempt}/{_RETRY_MAX_ATTEMPTS}, retry in {delay}s): {exc}"
            )
            time.sleep(delay)

class _GuardedHeaders(Mapping):
    """Request headers that refuse to materialise without credentials.

    A single choke point beats sprinkling `require_creds()` into all seven
    request helpers — helper #8 would silently skip the check.

    Deliberately **not** a `dict` subclass. CPython's `{**d}` and `dict(d)` take
    a C fast path that copies a dict subclass's internal storage directly,
    bypassing any overridden `__getitem__`/`keys()`. Five of the seven helpers
    build their headers with `{**HEADERS, "Prefer": ...}`, so a dict-subclass
    guard would be bypassed exactly where it is needed. `Mapping` has no such
    fast path — unpacking goes through `keys()` + `__getitem__`.
    (Measured 2026-07-10, not assumed: `{**GuardDict()}` returned the payload
    without ever calling the override.)
    """

    def _payload(self) -> dict[str, str]:
        require_creds()
        return {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }

    def __getitem__(self, key: str) -> str:
        return self._payload()[key]

    def __iter__(self):
        return iter(self._payload())

    def __len__(self) -> int:
        return len(self._payload())

    def __repr__(self) -> str:  # never leak the service-role key into a traceback
        return "<supabase HEADERS (credential-guarded)>"


HEADERS = _GuardedHeaders()

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
# MUST mirror the live Supabase `market_daily` table schema exactly. A key
# here that the table lacks → every row carrying it 400s with PGRST204
# ("could not find column ... in schema cache"). nk225_* were listed but the
# table never had them → 14/30 rows 400'd for ~5 weeks unnoticed (collection
# also stopped 2026-04-10). If you add a key here, ALTER the table first.
_MARKET_DAILY_COLUMNS = {
    "trade_date",
    "spy_close", "spy_open",
    "gld_close", "gld_open",
    "spy_data_date", "gld_data_date",
    "spy_stale", "gld_stale",
    "tw50_close", "tw50_open",
    "vix_level",
    "sigma_spy_ann", "sigma_gld_ann",
}


def _post(table: str, data: list | dict) -> bool:
    """POST (upsert) to Supabase table. Returns success.
    Falls back to PATCH on 409 conflict.

    Note: schema-level column filtering is handled by the table-specific
    helpers (e.g. `sync_market_daily`) — `_post` stays generic.
    """
    if _remote_writes_blocked():
        return False
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
        _urlopen(req, timeout=15)
        return True
    except HTTPError as e:
        code = e.code
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            body = "<unreadable>"
        if code == 409 and conflict:
            # Fallback: PATCH (update) existing rows
            return _patch(table, conflict, data)
        # Print the PostgREST error body — without it a 400 is opaque and
        # every diagnosis is blind (2026-05-20: market_daily 14/30 rows 400'd
        # for weeks with no visible reason).
        print(f"  Supabase {table} error: {code} — {body}")
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
            _urlopen(req, timeout=15)
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
    with _urlopen(req, timeout=15) as resp:
        body = resp.read()
        if not body:
            return None
        return json.loads(body)


def _select_rows(
    table: str,
    *,
    select: str = "*",
    order_by: str | None = None,
    **filters: object,
) -> list[dict]:
    # PostgREST caps a single response at max-rows (default 1000). Without
    # pagination, tables larger than the cap silently return only the first
    # page — which made feed_sync.compute_diff() treat every article beyond
    # row 1000 as a spurious INSERT and every real DB row missing from the
    # truncated view as a false DELETE (2026-07-09 content-erratum incident:
    # feed=1766 db=1000 → 892 fake inserts / 126 fake deletes). Page through
    # with limit/offset until a short page signals the end.
    #
    # order_by: stable sort key(s) for race-safe offset pagination. Without a
    # deterministic ORDER BY, a concurrent insert/delete before the current
    # offset boundary can silently skip or duplicate exactly one row across
    # page requests — reintroducing the same "row missing from DB view" symptom
    # this fix targets. Multi-page callers MUST pass a primary/unique key
    # (e.g. "id", or composite "article_id,tag_id"). Single-page tables
    # (<1000 rows) are unaffected either way.
    query = _build_filter_query(filters)
    base = f"{SUPABASE_URL}/rest/v1/{table}?select={quote(select, safe=',*')}"
    if query:
        base = f"{base}&{query}"
    if order_by:
        base = f"{base}&order={quote(order_by, safe=',.')}"
    page_size = 1000
    offset = 0
    rows: list[dict] = []
    while True:
        url = f"{base}&limit={page_size}&offset={offset}"
        data = _request_json(url, method="GET")
        page = data if isinstance(data, list) else []
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


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
    if _remote_writes_blocked():
        return False
    query = _build_filter_query(filters)
    if not query:
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
    headers = {**HEADERS, "Prefer": "return=minimal"}
    req = Request(url, data=payload, headers=headers, method="PATCH")
    try:
        _urlopen(req, timeout=15)
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
    if _remote_writes_blocked():
        return []
    query = _build_filter_query(filters)
    if not query:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}?{query}"
    payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
    headers = {**HEADERS, "Prefer": "return=representation"}
    req = Request(url, data=payload, headers=headers, method="PATCH")
    try:
        resp = _urlopen(req, timeout=15)
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
        _urlopen(req, timeout=15)
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


# --- Frontend cache purge (2026-07-19, assign_sync_cache_purge) -------------
#
# Defect: this module writes articles straight to Supabase REST, bypassing the
# frontend's /api/sync/[...path] route -- the only place that calls
# revalidateTag('article') / revalidateTag(`article-<slug>`). A retraction done
# via feed.json + sync_full() therefore updated the DB but never purged the
# frontend cache, and getArticleInternal *throws* for a retracted row, so
# unstable_cache's background revalidation had no new value to write and kept
# re-serving the stale published body forever (mile_ebb5d6f5: HTTP 200 with full
# content for >15min, far past `revalidate: 60` / page `revalidate = 300`).
# Only a redeploy cleared it -- the other 12 retracted articles 404 by accident
# of deploy history, not by mechanism.
#
# This module is the single enforcement owner for that purge (anti-stacking:
# the frontend's getArticleInternal deliberately still throws; the report pages
# already catch -> notFound()).
_REVALIDATE_FAILURES: list[str] = []


def _mirror_base_url() -> str:
    from volpred.config.runtime import get_default_remote_url

    return os.environ.get("VOLPRED_REMOTE_URL") or get_default_remote_url()


def revalidate_article_cache(slug: str) -> bool:
    """Purge the frontend unstable_cache tags for one article slug.

    Returns True on success. Failures are recorded in _REVALIDATE_FAILURES and
    printed LOUDLY -- an auth failure here silently disabling every purge is
    exactly the 2026-06-11 incident (mirror writes 401'd unnoticed for a month),
    so 401/403 gets its own explicit banner and sync_full()/the CLI surface it.
    """
    if not slug:
        return True
    # Same test-mode kill switch as every other outbound write in this module.
    if _remote_writes_blocked():
        return True

    from volpred.mirror_auth import ops_admin_headers, ops_admin_token

    url = f"{_mirror_base_url()}/api/sync/revalidate/article/{quote(str(slug), safe='')}"
    if not ops_admin_token():
        print(
            f"  [supabase_sync] CACHE PURGE FAILED for {slug}: OPS_ADMIN_TOKEN is "
            "unset, so /api/sync would 401. Retracted/unpublished articles will "
            "keep being served from the frontend cache until a redeploy."
        )
        _REVALIDATE_FAILURES.append(slug)
        return False

    req = Request(
        url,
        data=b"",
        headers={"Content-Type": "application/json", **ops_admin_headers()},
        method="POST",
    )
    try:
        # Routed through _urlopen like every other egress: neither of its two
        # behaviours touches this call (the read gate only blocks GET, and a
        # bare POST is not replay-safe so it is never retried), so the mirror
        # host keeps its exact semantics while the chokepoint stays the single
        # place a future outbound call can be gated from.
        with _urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                return True
            reason = f"HTTP {resp.status}"
    except HTTPError as exc:
        reason = f"HTTP {exc.code}"
        if exc.code in (401, 403):
            reason += " UNAUTHORIZED (OPS_ADMIN_TOKEN rejected by the mirror)"
    except Exception as exc:  # URLError, timeout, DNS...
        reason = f"{type(exc).__name__}: {exc}"

    print(
        f"  [supabase_sync] CACHE PURGE FAILED for {slug}: {reason} ({url}). "
        "Supabase row is correct but readers may still see the cached old "
        "version -- rerun the sync once the mirror is reachable."
    )
    _REVALIDATE_FAILURES.append(slug)
    return False


def projected_content(item: dict, *, verbose: bool = True) -> str:
    """Return the exact `content` string sync_article() writes to Supabase.

    Split out 2026-07-20 (WS-C2). The write path sanitizes content before
    POSTing (markdown-table pipe escaping + CJK-appositive em-dash → comma),
    so the stored projection is deliberately NOT byte-identical to the
    canonical feed.json text. `feed_sync.compute_diff` used to hash the raw
    feed content against the stored content, which meant every article whose
    feed text still contained a CJK appositive em-dash was reported "changed"
    on every single run — 137 of 1852 articles, forever, converging never.
    That is fatal for the hourly reconcile job (WS-C2): a safety net that
    always reports drift is a safety net nobody reads.

    Both the writer and the differ now call this one function, so "what the
    projection should contain" has a single definition (anti-stacking) and
    the reconcile loop is idempotent by construction.

    `verbose=False` for the diff path: it is asking a question, not
    performing a repair, so it must not narrate.
    """
    content = item.get("content") or item.get("description") or ""
    if not content:
        return ""

    def _say(msg: str) -> None:
        if verbose:
            print(msg)

    try:
        from volpred.publisher.markdown_table_sanitizer import (
            sanitize_markdown_tables,
        )
        sanitized, report = sanitize_markdown_tables(content)
        if report.changed:
            content = sanitized
            _say(
                f"  [supabase_sync] markdown_table_sanitizer auto-fixed "
                f"{len(report.fixed_lines)} row(s) for "
                f"{item.get('id', 'unknown')}: {report.summary()}"
            )
        if report.has_unfixed:
            _say(
                f"  [supabase_sync] WARN unfixable table rows for "
                f"{item.get('id', 'unknown')}: lines={report.unfixed_lines}"
            )
    except Exception as exc:
        _say(f"  [supabase_sync] markdown_table_sanitizer error: {exc}")

    # Secondary anti-AI-style em-dash normalizer (2026-05-29): same
    # belt-and-suspenders rationale — catches manual edits / legacy
    # entries / hot-fix scripts that bypassed publisher._append_to_feed.
    # Conservative CJK-appositive-only rewrite (landmine 9 fix (b)).
    try:
        from volpred.publisher.emdash_normalizer import normalize_emdash

        normalized, emrep = normalize_emdash(content)
        if emrep.changed:
            content = normalized
            _say(
                f"  [supabase_sync] emdash_normalizer auto-fixed "
                f"{emrep.replaced} em-dash(es) for "
                f"{item.get('id', 'unknown')}: {emrep.summary()}"
            )
    except Exception as exc:
        _say(f"  [supabase_sync] emdash_normalizer error: {exc}")

    return content


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
    markdown table cells before Supabase write. Same secondary pass also
    runs the anti-AI-style em-dash normalizer (CJK appositive `——`/`—` →
    comma) so manual/legacy/hot-fix content gets the landmine-9 fix too.
    """
    # 2026-07-20 (WS-C2): the sanitize pipeline that used to be inlined here
    # now lives in projected_content(), which feed_sync.compute_diff also
    # calls. One definition of "what the projection should contain" keeps the
    # hourly reconcile idempotent — when the writer and the differ normalize
    # differently, every affected row reports drift forever.
    content = projected_content(item, verbose=True)
    # last_updated_at is not a column on the articles table, so carry it inside the
    # synced `details` JSON blob (the frontend reads details.last_updated_at to show
    # "更新於 <date hh:mm>" when content was edited after publish — boss 2026-07-01).
    details = item.get("details")
    if not isinstance(details, dict):
        details = {} if details is None else {"_legacy": details}
    if item.get("last_updated_at"):
        details = {**details, "last_updated_at": item.get("last_updated_at")}
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
        "details": details,
        "published_at": item.get("published_at"),
    }
    ok = _post("articles", row)
    # Single retry on _post failure (transient HTTP error / network blip)
    # before falling through to read-back verification. release_pool used to
    # silently lose K1021 here because _post returned False and nobody
    # checked the value.
    if not ok and row["slug"]:
        print(f"  [supabase_sync] _post failed for {row['slug']}, retrying once")
        ok = _post("articles", row)
        if not ok:
            print(f"  [supabase_sync] _post retry FAILED for {row['slug']} -- caller must handle")
    # Read-back verification (2026-04-30 architectural fix): _post returns
    # True on HTTP 2xx but PostgREST upsert with `Prefer: return=minimal` does
    # not echo body, so we cannot confirm row state from POST alone. K1021
    # incident (release_pool's second sync_article call left Supabase status
    # at 'draft' while local feed was 'published') showed _post can succeed
    # at the HTTP layer while the row state diverges. Read the row back and
    # if `status` / `published_at` / `audience` mismatch the row we sent, force an
    # explicit PATCH via _patch_where as recovery.
    if ok and row["slug"]:
        try:
            actual = _select_rows(
                "articles",
                select="slug,status,published_at,audience",
                slug=row["slug"],
            )
            if actual:
                got = actual[0]
                want_status = row["status"]
                want_pub = row.get("published_at")
                want_audience = row["audience"]
                status_diverged = got.get("status") != want_status
                pub_diverged = (
                    want_pub is not None and got.get("published_at") != want_pub
                )
                audience_diverged = got.get("audience") != want_audience
                if status_diverged or pub_diverged or audience_diverged:
                    print(
                        f"  [supabase_sync] read-back diverged for {row['slug']}: "
                        f"got status={got.get('status')!r} published_at={got.get('published_at')!r} "
                        f"audience={got.get('audience')!r} "
                        f"want status={want_status!r} published_at={want_pub!r} "
                        f"audience={want_audience!r} -- patching"
                    )
                    fix = {"status": want_status, "audience": want_audience}
                    if want_pub is not None:
                        fix["published_at"] = want_pub
                    patched = _patch_where("articles", {"slug": row["slug"]}, fix)
                    if not patched:
                        print(
                            f"  [supabase_sync] read-back PATCH fallback FAILED for {row['slug']}"
                        )
                        ok = False
        except Exception as exc:
            print(f"  [supabase_sync] read-back verification error for {row['slug']}: {exc}")
    if ok:
        # Sync tags
        tags = item.get("tags") or []
        if tags:
            tag_ok = _sync_article_tags(row["slug"], tags)
            if not tag_ok:
                print(f"  Warning: article synced but tags missing for {row['slug']}")
        # Purge the frontend cache for this slug. Required for EVERY sync, not
        # just retractions: content edits were equally invisible for up to 60s,
        # and status downgrades (published -> retracted/unpublished) were
        # invisible indefinitely. Does not flip `ok` -- the DB write is this
        # function's contract -- but sync_full() refuses to record the content
        # hash for a slug whose purge failed, so the next run retries it.
        revalidate_article_cache(row["slug"])
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

    from volpred.ops.strategy_gate import StrategyGateError, assert_activation_allowed

    # Look up current state once — reused for metadata preservation AND the
    # activation gate. `_find_strategy_signal` returns None only on a genuine
    # not-found (query succeeded, empty result); a backend query failure
    # propagates as an exception. That distinction is what lets the gate tell
    # "new strategy" apart from "Supabase unreachable" below.
    try:
        existing = _find_strategy_signal(strategy_key, strategy_name) or {}
    except Exception as e:
        if is_active:
            # Indeterminate current state on an activation write => fail-closed.
            # A transient lookup failure is indistinguishable from a brand-new
            # strategy; allowing the write would be an activation backdoor.
            # Distinct message so this is not mistaken for a missing-receipt block.
            raise StrategyGateError(
                f"Cannot verify activation gate for strategy "
                f"'{strategy_key or strategy_name}': strategy_signals lookup "
                f"failed ({e}). Refusing to activate while the current active "
                f"state is indeterminate. This is NOT a missing-receipt error — "
                f"retry once Supabase is reachable."
            ) from e
        raise  # deactivation / metadata-only: propagate the original error unchanged
    resolved_key = strategy_key or existing.get("strategy_key") or _slugify_strategy_key(strategy_name)

    # Gate the inactive->active transition only. An already-active strategy being
    # re-synced (daily_update.py full-sync, the most common path) is a no-op
    # transition and passes without a receipt, so live cards never disappear.
    if is_active and not existing.get("is_active"):
        assert_activation_allowed(resolved_key, strategy_name)

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
    from volpred.ops.strategy_gate import StrategyGateError, assert_activation_allowed

    try:
        existing = _find_strategy_signal(identifier, identifier)
    except Exception as e:
        if active:
            # Same fail-closed reasoning as sync_strategy_signal: an indeterminate
            # lookup on an activation request must not fall through to the PATCH.
            raise StrategyGateError(
                f"Cannot verify activation gate for strategy '{identifier}': "
                f"strategy_signals lookup failed ({e}). Refusing to activate "
                f"while the current active state is indeterminate. This is NOT a "
                f"missing-receipt error — retry once Supabase is reachable."
            ) from e
        raise  # deactivation: propagate the original error unchanged
    if not existing:
        print(f"  Supabase strategy_signals error: strategy not found ({identifier})")
        return False
    # Gate only the inactive->active transition; deactivation always passes.
    if active and not existing.get("is_active"):
        assert_activation_allowed(
            existing.get("strategy_key") or identifier,
            existing.get("strategy_name") or identifier,
        )
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
    if ok:
        revalidate_article_cache(slug)
    return ok


def delete_article(slug: str) -> bool:
    """Hard-delete an article row by slug.

    FK note: migration 021 (2026-04-18) set article_impressions.article_id to
    ON DELETE CASCADE, so the DB now removes impressions automatically. The
    explicit pre-delete below is kept as defence-in-depth (idempotent no-op when
    the cascade is present; a safety net if 021 was not applied to some row).
    article_reactions / question_articles / article_tags / comments are ON
    DELETE CASCADE (schema 001), so the final articles DELETE handles them.

    Returns True iff articles row is actually gone; False on any HTTP error.
    """
    # Resolve UUID first (article_impressions uses article_id uuid FK)
    article_id = _get_article_id(slug)
    if article_id:
        # Pre-delete the impressions FK reference (belt-and-suspenders; BUG-001
        # fix 2026-04-18 / migration 021 made this ON DELETE CASCADE at the DB).
        _delete_where("article_impressions", {"article_id": article_id})
    ok = _delete_where("articles", {"slug": slug})
    if not ok:
        # 409 / other error — don't silently succeed. Caller (cleanup_test_post)
        # must surface this to user.
        print(f"  [BUG-001 guard] articles DELETE for slug={slug} FAILED; row may still exist with FK blocker.")
    else:
        # A hard delete is the strongest possible visibility change; without the
        # purge the frontend keeps serving the deleted body from unstable_cache.
        revalidate_article_cache(slug)
    return ok


def _get_article_id(slug: str) -> str | None:
    """Fetch article UUID by slug (for FK cascade pre-delete)."""
    url = f"{SUPABASE_URL}/rest/v1/articles?select=id&slug=eq.{slug}"
    req = Request(url, headers=HEADERS, method="GET")
    try:
        with _urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data[0]["id"] if data else None
    except Exception:
        return None  # silent-ok: best-effort id lookup; None = caller treats as not-found


def _reconcile_dump_path(storage_dir: str | Path, stamp: str | None = None) -> Path:
    """storage/ops/supabase_reconcile_removed_YYYYMMDD.jsonl (recovery dump)."""
    from datetime import datetime
    stamp = stamp or datetime.now().strftime("%Y%m%d")
    return Path(storage_dir) / "ops" / f"supabase_reconcile_removed_{stamp}.jsonl"


def reconcile_article_deletes(
    storage_dir: str | Path = "storage",
    *,
    apply: bool = True,
    floor: int = 500,
    max_deletes: int = 300,
) -> dict:
    """Delete Supabase `articles` rows whose slug is absent from local feed.json.

    Closes the push-only mirror drift: sync_full()/sync_article() only ever
    UPSERT, never DELETE. A row for an article that was pruned from — or never
    existed in — the canonical feed.json therefore accumulates as a "ghost" on
    Supabase (2026-07-14 incident: 200 ghosts ~= 156 draft + 44 retracted,
    inflating the admin content count to 2003 vs the local 1803). feed.json is
    the single source of truth (a one-way projection to Supabase), so any remote
    slug not present locally IS drift.

    This is the single guarded delete owner for the articles mirror. Both the
    scheduled push path (sync_full) and the manual diff tool
    (feed_sync.apply_diff) route destructive article deletes through here rather
    than calling _delete_where("articles", ...) directly, so the floor/cap/dump
    invariants below can never be bypassed.

    Safety invariants (any breach => delete NOTHING, aborted=True):
      floor:       refuse unless local feed loaded >= `floor` articles. Guards an
                   empty / corrupt / half-written feed.json from wiping the table.
      max_deletes: abort if the drift exceeds `max_deletes`. Guards canonical
                   corruption (e.g. a bad edit dropping most articles) from
                   triggering a mass delete instead of a targeted reconcile.
      dump:        every row to be removed — plus its article_impressions, which
                   ON DELETE CASCADE (migration 021) would otherwise destroy — is
                   appended to storage/ops/supabase_reconcile_removed_YYYYMMDD.jsonl
                   BEFORE any DELETE, so a mistaken removal is fully recoverable.

    apply=False performs a read-only preview (computes ghosts, writes nothing).

    Returns counters: {local_count, remote_count, ghost_count, deleted, failed,
    impressions_dumped, dump_path, aborted, reason, sample}.
    """
    storage = Path(storage_dir)
    result = {
        "local_count": 0,
        "remote_count": 0,
        "ghost_count": 0,
        "deleted": 0,
        "failed": 0,
        "impressions_dumped": 0,
        "dump_path": None,
        "aborted": False,
        "reason": "",
        "sample": [],
    }

    # --- local canonical id set (source of truth) ---
    feed_path = storage / "reports" / "feed.json"
    try:
        feed = json.loads(feed_path.read_text())
    except Exception as e:
        result["aborted"] = True
        result["reason"] = "canonical_load_failed"
        print(
            f"[reconcile] WARN abort: cannot load {feed_path}: "
            f"{type(e).__name__}: {e}"
        )
        return result
    if isinstance(feed, dict):
        feed = feed.get("items", [])
    local_ids = {
        a.get("id") for a in feed if isinstance(a, dict) and a.get("id")
    }
    result["local_count"] = len(local_ids)

    # floor guard — refuse to delete against a suspiciously small canonical set
    if len(local_ids) < floor:
        result["aborted"] = True
        result["reason"] = f"canonical_below_floor(<{floor})"
        print(
            f"[reconcile] WARN abort: local feed has {len(local_ids)} articles "
            f"(< floor {floor}); refusing to delete (guards empty/corrupt feed)."
        )
        return result

    # --- remote projection (paginates past the 1000-row cap) ---
    remote_rows = _select_rows(
        "articles",
        select="id,slug,status,title,published_at,updated_at",
        order_by="id",
    )
    result["remote_count"] = len(remote_rows)
    ghosts = [
        r for r in remote_rows if r.get("slug") and r["slug"] not in local_ids
    ]
    result["ghost_count"] = len(ghosts)
    result["sample"] = [
        {"slug": g.get("slug"), "status": g.get("status")} for g in ghosts[:5]
    ]

    if not ghosts:
        result["reason"] = "no_drift"
        return result

    # cap guard — a drift larger than max_deletes smells like canonical corruption
    if len(ghosts) > max_deletes:
        result["aborted"] = True
        result["reason"] = f"exceeds_max_deletes({len(ghosts)}>{max_deletes})"
        print(
            f"[reconcile] WARN abort: {len(ghosts)} ghosts exceed max_deletes "
            f"{max_deletes}; refusing bulk delete (suspected canonical "
            f"corruption). Investigate feed.json before re-running."
        )
        return result

    if not apply:
        result["reason"] = "preview"
        return result

    # --- dump-before-delete (recoverable), incl. cascade-impacted impressions ---
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    ghost_uuids = [str(g["id"]) for g in ghosts if g.get("id")]
    impressions_by_article: dict[str, list] = {}
    for i in range(0, len(ghost_uuids), 100):
        chunk = ghost_uuids[i:i + 100]
        try:
            imp_rows = _select_rows_in(
                "article_impressions", "article_id", chunk, select="*"
            )
        except Exception as e:
            imp_rows = []
            print(
                f"[reconcile] WARN impressions fetch failed for a chunk "
                f"(dump proceeds without them): {type(e).__name__}: {e}"
            )
        for row in imp_rows:
            aid = str(row.get("article_id") or "")
            impressions_by_article.setdefault(aid, []).append(row)

    dump_path = _reconcile_dump_path(storage)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    imp_total = 0
    with dump_path.open("a", encoding="utf-8") as fh:
        for g in ghosts:
            imps = impressions_by_article.get(str(g.get("id")), [])
            imp_total += len(imps)
            fh.write(
                json.dumps(
                    {
                        "deleted_at": now_iso,
                        "reason": "supabase_reconcile_ghost_not_in_feed",
                        "article": g,
                        "impressions": imps,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    result["impressions_dumped"] = imp_total
    result["dump_path"] = str(dump_path)

    # --- delete (FK-safe via delete_article: impressions pre-delete + loud fail) ---
    for g in ghosts:
        slug = g.get("slug")
        if not slug:
            continue
        if delete_article(slug):
            result["deleted"] += 1
        else:
            result["failed"] += 1

    print(
        f"[reconcile] local={result['local_count']} "
        f"remote={result['remote_count']} ghosts={result['ghost_count']} "
        f"deleted={result['deleted']} failed={result['failed']} "
        f"impressions_dumped={imp_total} dump={dump_path}"
    )
    return result


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
    # 2026-05-04 finding #4 修整：whitelist 早已 enforce (上面 row=)，但 stripped 欄位
    # 不可見導致 audit agent 誤判「未 enforce」+ caller 不知 schema mismatch。
    # 補 print warning 提升可觀察性 — caller 可看到 daily_update 在塞 unknown keys。
    stripped = {k for k in market.keys() if k not in _MARKET_DAILY_COLUMNS and k != "trade_date"}
    if stripped:
        print(
            f"  [sync_market_daily] schema-mismatch warning: trade_date={trade_date} "
            f"stripped {len(stripped)} unknown keys (not in _MARKET_DAILY_COLUMNS): "
            f"{sorted(stripped)} — update _MARKET_DAILY_COLUMNS if these should sync"
        )
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


# Syncable article fields whose change must trigger a re-sync, regardless of
# whether any timestamp was bumped. 2026-06-03 3-strike (refactor plan
# docs/refactor_plan_prepublish_content_gate.md, 根因 B): the prior incremental
# filter was timestamp-gated only — editing content without bumping updated_at
# silently skipped the row (the K1413 correction was silent-dropped until
# updated_at was force-bumped). Content-hash-based detection catches any
# syncable-field change and is decoupled from timestamps.
_ARTICLE_HASH_FIELDS = (
    "content", "title", "excerpt", "status", "audience", "category", "details",
)


def _article_hash(item: dict) -> str:
    """Stable sha256 over the syncable fields of an article.

    Uses sort_keys + ensure_ascii=False so equal content always produces an
    equal digest (idempotent) and any field change flips it.
    """
    payload = {k: item.get(k) for k in _ARTICLE_HASH_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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


def sync_full(storage_dir: str | Path = "storage", *, reconcile_deletes: bool = True) -> dict:
    """Incremental sync: only upsert items changed since last sync.
    Falls back to full sync on first run or if state file is missing.

    reconcile_deletes: after pushing, run reconcile_article_deletes() to remove
    Supabase `articles` rows whose slug is absent from the canonical feed.json.
    The push is upsert-only, so without this the mirror drifts upward forever
    (ghost drafts/retracted rows never leave). Guarded (floor/cap/dump) so a
    corrupt feed can never trigger a mass delete. Default on for the scheduled
    path; pass False to skip (e.g. a push-only smoke test)."""
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
            article_hashes = state.get("article_hashes")
            if not isinstance(article_hashes, dict):
                article_hashes = {}
            # 2026-06-03 3-strike (根因 B): content-hash-based change detection.
            # 2026-06-29 correction: feed.json is the article source of truth.
            # Legacy reports/<id>.json files are intentionally ignored here; a
            # stale single file must never overwrite a corrected feed entry.
            # Selection condition (OR'd, defence-in-depth):
            #   (a) article content hash differs from last-synced hash, OR
            #   (b) legacy timestamp condition (back-compat; updated_at/published_at/
            #       created_at after last_sync_ts — kept as fallback, not removed), OR
            #   (c) no last_sync_ts (first run -> full).
            to_sync = []
            for item in feed:
                slug = item.get("id")
                cur_hash = _article_hash(item)
                hash_changed = article_hashes.get(slug) != cur_hash
                ts_changed = (
                    (item.get("published_at") or item.get("created_at") or "") > last_sync_ts
                    or (item.get("updated_at") or "") > last_sync_ts
                )
                if hash_changed or ts_changed or not last_sync_ts:
                    to_sync.append(item)
            ok = 0
            purge_mark = len(_REVALIDATE_FAILURES)
            for item in to_sync:
                if sync_article(item, storage_dir=storage):
                    ok += 1
                    # Only record the hash after a successful sync so a failed
                    # push retries next run. A failed frontend cache purge counts
                    # as "not fully synced": the DB is right but readers may still
                    # see the old body, so withhold the hash to force a retry.
                    if item.get("id") not in _REVALIDATE_FAILURES[purge_mark:]:
                        article_hashes[item.get("id")] = _article_hash(item)
            counts["articles"] = ok
            failed_purges = _REVALIDATE_FAILURES[purge_mark:]
            if failed_purges:
                counts["cache_purge_failed"] = failed_purges
            state["feed_mtime"] = feed_mtime
            state["article_hashes"] = article_hashes
            if feed:
                state["articles_last_ts"] = max(
                    (item.get("updated_at") or item.get("published_at") or item.get("created_at") or "")
                    for item in feed
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

    # Delete reconcile — the push above is upsert-only, so remote rows for
    # articles absent from canonical feed.json accumulate as ghosts. Close the
    # drift here (guarded: floor/cap/dump). Skipped when reads are blocked so a
    # test that reaches sync_full without stubbing does not crash.
    if reconcile_deletes and not _remote_reads_blocked():
        try:
            counts["reconcile"] = reconcile_article_deletes(storage)
        except Exception as e:
            counts["reconcile"] = {"aborted": True, "reason": f"error:{type(e).__name__}"}
            print(f"[reconcile] WARN sync_full reconcile step failed: {type(e).__name__}: {e}")

    _save_sync_state(storage, state)
    return counts


def _report_counts(counts: dict) -> int:
    """Print sync counts; return the process exit code.

    A failed frontend cache purge exits non-zero so a broken/expired
    OPS_ADMIN_TOKEN cannot hide behind a green 'Done.' the way the mirror 401s
    did for a month in 2026-06.
    """
    for k, v in counts.items():
        print(f"  {k}: {v}")
    failed = counts.get("cache_purge_failed") or []
    if failed:
        print(
            f"ERROR: frontend cache purge FAILED for {len(failed)} article(s): "
            f"{failed}. Supabase is correct but readers may still be served the "
            "cached old version. Check OPS_ADMIN_TOKEN and mirror reachability."
        )
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "full":
        print("Running incremental sync to Supabase...")
        sys.exit(_report_counts(sync_full()))
    elif len(sys.argv) > 1 and sys.argv[1] == "force-full":
        # Delete state file to force full resync
        state_path = Path("storage") / ".supabase_sync_state.json"
        if state_path.exists():
            state_path.unlink()
        print("Running FULL resync (state cleared)...")
        sys.exit(_report_counts(sync_full()))
    else:
        print("Usage: python scripts/supabase_sync.py full          # incremental")
        print("       python scripts/supabase_sync.py force-full    # full resync")
