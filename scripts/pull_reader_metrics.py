#!/usr/bin/env python3
"""Pull reader engagement metrics from Supabase and land a daily analytics snapshot.

Closes the "which content actually gets read" feedback loop (Mission 1 把文章寫好
+ Mission 5 把曝光流量拉高): aggregates `article_impressions` (views / read_time)
and `article_reactions` (likes / bookmarks / shares) per article, joins to
`articles` for title/slug/audience, ranks a composite-score top-N, and writes:

    storage/analytics/reader_metrics_<YYYY-MM-DD>.json   (dated daily snapshot)
    storage/analytics/latest.json                        (overwritten; consumers read this)

Consumers:
  - scripts/daily_checkup.py::check_reader_metrics   (freshness gate + top-3 summary)
  - scripts/build_publication_candidates.py          (soft `reader_signal` metadata
    attached per candidate, matched via covering-article slug — does NOT alter the
    existing score/sort key)

Research-honesty constraints (per CLAUDE.md 研究誠實原則):
  - Every number here comes from a live Supabase query. No fabricated data.
  - `article_impressions` has no explicit "finished reading" column, so read
    completion is APPROXIMATED from the read_time_sec distribution:
    engaged := read_time_sec >= ENGAGED_THRESHOLD_SEC (30s, a documented
    assumption, not a measured ground truth). Every output row and the
    top-level methodology_notes carry `read_time_is_proxy: true` so no
    downstream reader mistakes this for an actual completion metric.
  - Read-only against Supabase (no writes, no INSERT/PATCH/DELETE).
  - Client construction reuses scripts/supabase_sync.py's established pattern
    (urllib + SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY env, with its existing
    .env.local fallback) instead of introducing a new client library — the
    `supabase` python package is not a project dependency.

Usage:
  uv run python scripts/pull_reader_metrics.py --top 20 --days 30
  uv run python scripts/pull_reader_metrics.py --top 10 --days 30 --dry-run
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from supabase_sync import SUPABASE_URL, SUPABASE_KEY, HEADERS  # noqa: E402  reuse established client/env pattern
from volpred.ops.diagnostics import warn  # noqa: E402

ANALYTICS_DIR = ROOT / "storage" / "analytics"

# --- Documented assumptions (proxy, not measured ground truth) -------------
BOUNCE_THRESHOLD_SEC = 5     # mirrors frontend-v2-fix/src/lib/admin-analytics.ts
                             # filter (`row.read_time_sec > 5`) when computing avg read time.
ENGAGED_THRESHOLD_SEC = 30   # our own proxy threshold for "engaged read" — no
                             # ground-truth completion column exists on
                             # article_impressions, so this is an assumption.
MAX_READ_TIME_SEC = 1200     # 20 min outlier cap. Empirically verified against a
                             # real 30-day pull (2026-07-05): median read_time_sec
                             # was 52s but p90 jumped to ~11,700s and max to
                             # ~176,000s (49h) — classic "left the browser tab
                             # open in background" artifacts, not genuine reading
                             # time (frontend has no visibility/blur-based cutoff
                             # on the read-time timer). Left uncapped, a single
                             # such session dominates a low-impression article's
                             # score/rank, which would make this feedback loop
                             # actively misleading for topic selection. Rows above
                             # the cap are excluded from avg/median/engagement but
                             # the raw impression is still counted; excluded counts
                             # are surfaced in the output for transparency.

REQUEST_TIMEOUT = 20
PAGE_SIZE = 1000  # PostgREST implicit row cap (docs/error_log.md 2026-06-23
                   # "Supabase 1000-row cap" incident) — must page past this.


def _get(url: str) -> list:
    req = Request(url, headers={**HEADERS, "Prefer": ""}, method="GET")
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        body = resp.read()
        if not body:
            return []
        data = json.loads(body)
        return data if isinstance(data, list) else []


def _paged_select(table: str, select: str, filters: str) -> tuple[list[dict], str | None]:
    """GET all rows for a filtered query, paging past PostgREST's 1000-row cap.

    Returns (rows, error). `error` is None on full success; a non-None error
    string means the query failed partway (rows collected so far are still
    returned — partial data, not fabricated — but the caller must surface the
    error rather than treat it as "genuinely zero rows").
    """
    rows: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/{table}?select={quote(select, safe=',')}"
            f"&{filters}&limit={PAGE_SIZE}&offset={offset}"
        )
        try:
            batch = _get(url)
        except (HTTPError, URLError) as exc:
            warn("pull_reader_metrics", f"{table} query failed", err=str(exc), offset=offset)
            return rows, str(exc)
        except Exception as exc:  # noqa: BLE001 — surfaced via warn(), not swallowed
            warn("pull_reader_metrics", f"{table} query failed (unexpected)", err=str(exc), offset=offset)
            return rows, str(exc)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows, None


def fetch_impressions(since_date: str) -> tuple[list[dict], str | None]:
    filters = f"impression_date=gte.{since_date}"
    return _paged_select(
        "article_impressions", "article_id,impression_date,read_time_sec,created_at", filters
    )


def fetch_reactions(since_iso: str) -> tuple[list[dict], str | None]:
    filters = f"created_at=gte.{quote(since_iso, safe='')}"
    return _paged_select("article_reactions", "article_id,reaction,created_at", filters)


def fetch_article_meta(article_ids: list[str]) -> dict[str, dict]:
    """Map Supabase articles.id (uuid) -> {slug, title, audience}.

    `articles.slug` is the canonical id used everywhere else in this repo
    (feed.json entry "id", experiment refs, etc.) — see
    scripts/supabase_sync.py::sync_article() which writes
    row["slug"] = item.get("id", "").
    """
    meta: dict[str, dict] = {}
    ids = [a for a in article_ids if a]
    chunk = 50
    for i in range(0, len(ids), chunk):
        batch_ids = ids[i : i + chunk]
        encoded = ",".join(quote(str(v), safe="") for v in batch_ids)
        url = f"{SUPABASE_URL}/rest/v1/articles?select=id,slug,title,audience&id=in.({encoded})"
        try:
            rows = _get(url)
        except (HTTPError, URLError) as exc:
            warn("pull_reader_metrics", "articles meta query failed", err=str(exc), batch_start=i)
            continue
        except Exception as exc:  # noqa: BLE001
            warn("pull_reader_metrics", "articles meta query failed (unexpected)", err=str(exc), batch_start=i)
            continue
        for row in rows:
            aid = row.get("id")
            if aid:
                meta[aid] = row
    return meta


def aggregate(impressions: list[dict], reactions: list[dict]) -> dict[str, dict]:
    agg: dict[str, dict] = {}
    outliers_excluded_total = 0

    def _bucket(article_id: str) -> dict:
        return agg.setdefault(
            article_id,
            {
                "impressions": 0,
                "read_times": [],
                "outliers_excluded": 0,
                "reactions": {"like": 0, "bookmark": 0, "share": 0},
            },
        )

    for row in impressions:
        aid = row.get("article_id")
        if not aid:
            continue
        b = _bucket(aid)
        b["impressions"] += 1
        rt = row.get("read_time_sec")
        if isinstance(rt, (int, float)) and rt > BOUNCE_THRESHOLD_SEC:
            if rt <= MAX_READ_TIME_SEC:
                b["read_times"].append(rt)
            else:
                b["outliers_excluded"] += 1
                outliers_excluded_total += 1

    for row in reactions:
        aid = row.get("article_id")
        reaction = row.get("reaction")
        if not aid or reaction not in ("like", "bookmark", "share"):
            continue
        b = _bucket(aid)
        b["reactions"][reaction] += 1

    return agg, outliers_excluded_total


def build_rows(agg: dict[str, dict], meta: dict[str, dict]) -> list[dict]:
    rows = []
    for aid, b in agg.items():
        m = meta.get(aid) or {}
        read_times = b["read_times"]
        avg_rt = statistics.mean(read_times) if read_times else None
        med_rt = statistics.median(read_times) if read_times else None
        engaged = sum(1 for t in read_times if t >= ENGAGED_THRESHOLD_SEC)
        completion_proxy = (engaged / b["impressions"]) if b["impressions"] else None
        reactions = b["reactions"]
        # Mirrors frontend-v2-fix/src/lib/admin-analytics.ts weighted_views
        # formula (viewCount*10 + likes*25 + bookmarks*40 + shares*60 + avgReadBonus)
        # so this ranking is consistent with the admin analytics page's own
        # notion of "high-value content".
        score = (
            b["impressions"] * 10
            + reactions["like"] * 25
            + reactions["bookmark"] * 40
            + reactions["share"] * 60
            + round((avg_rt or 0) / 10)
        )
        rows.append(
            {
                "article_id": aid,
                "slug": m.get("slug"),
                "title": m.get("title"),
                "audience": m.get("audience"),
                "impressions": b["impressions"],
                "avg_read_time_sec": round(avg_rt, 1) if avg_rt is not None else None,
                "median_read_time_sec": round(med_rt, 1) if med_rt is not None else None,
                "read_completion_rate_proxy": round(completion_proxy, 4) if completion_proxy is not None else None,
                "read_time_is_proxy": True,
                "read_time_outliers_excluded": b["outliers_excluded"],
                "reactions": reactions,
                "score": score,
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=20, help="top-N articles to keep in output (default 20)")
    ap.add_argument("--days", type=int, default=30, help="lookback window in days (default 30)")
    ap.add_argument("--dry-run", action="store_true", help="print summary only; do not write storage/analytics/")
    args = ap.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (checked env + .env.local)", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=args.days)).date().isoformat()
    since_iso = f"{since_date}T00:00:00+00:00"

    impressions, impressions_error = fetch_impressions(since_date)
    reactions, reactions_error = fetch_reactions(since_iso)

    agg, outliers_excluded_total = aggregate(impressions, reactions)
    article_ids = list(agg.keys())
    meta = fetch_article_meta(article_ids)

    rows = build_rows(agg, meta)
    rows.sort(key=lambda r: r["score"], reverse=True)
    top_rows = rows[: args.top]

    output = {
        "generated_at": now.isoformat(),
        "window_days": args.days,
        "since_date": since_date,
        "top_n": args.top,
        "articles_with_activity": len(rows),
        "raw_impression_rows": len(impressions),
        "raw_reaction_rows": len(reactions),
        "data_source_errors": {
            "article_impressions": impressions_error,
            "article_reactions": reactions_error,
        },
        "methodology_notes": {
            "read_time_is_proxy": True,
            "read_time_bounce_filter_sec": BOUNCE_THRESHOLD_SEC,
            "read_time_outlier_cap_sec": MAX_READ_TIME_SEC,
            "read_time_outliers_excluded_total": outliers_excluded_total,
            "engaged_threshold_sec": ENGAGED_THRESHOLD_SEC,
            "score_formula": (
                "impressions*10 + likes*25 + bookmarks*40 + shares*60 + "
                "avg_read_time_sec/10 (mirrors frontend admin-analytics.ts weighted_views)"
            ),
        },
        "top_articles": top_rows,
    }

    print(
        f"[pull_reader_metrics] window={since_date}..today  "
        f"impressions_rows={len(impressions)} (error={impressions_error})  "
        f"reactions_rows={len(reactions)} (error={reactions_error})  "
        f"distinct_articles_with_activity={len(rows)}"
    )
    for r in top_rows[:5]:
        print(
            f"  score={r['score']:>6}  impressions={r['impressions']:>4}  "
            f"read_completion_proxy={r['read_completion_rate_proxy']}  "
            f"slug={r['slug']}  title={r['title']}"
        )

    if args.dry_run:
        print("[pull_reader_metrics] --dry-run: not writing to storage/analytics/")
        return 0

    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = ANALYTICS_DIR / f"reader_metrics_{now.date().isoformat()}.json"
    latest_path = ANALYTICS_DIR / "latest.json"
    dated_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pull_reader_metrics] wrote {dated_path}")
    print(f"[pull_reader_metrics] wrote {latest_path}")

    # Total failure (both source tables errored AND yielded no rows) is a
    # distinct outcome from "genuinely no activity yet" — surface via exit
    # code so the caller / cron doesn't mistake this for a clean empty run.
    if impressions_error and reactions_error and not rows:
        print("[pull_reader_metrics] BLOCKED: both article_impressions and "
              "article_reactions queries failed — see data_source_errors above", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
