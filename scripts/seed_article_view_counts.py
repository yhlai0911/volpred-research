#!/usr/bin/env python3
"""One-time seeding of reader-facing article view counts (boss email-12160, 2026-07-18).

Boss request, verbatim:
    每篇文章可以顯示瀏覽次數嗎？首次開始顯示的數字 請隨機推估一個數字 之後就照實計算。
    首次推估的方式是依照現在的真實瀏覽次數高低去做排序 然後隨機顯示一個不超過1000的
    數字（排序不能變）。

So the displayed number is:

    displayed(article) = seed + max(0, real_views_now - real_views_at_seed_time)

Ceiling history: v1 used 1000 (the boss's literal wording). He then asked for 1417
(email-12163) — a round 1000 as the visible maximum is itself a tell that the number
was picked by a human, so an odd ceiling reads as measured rather than chosen.

`seed` is frozen once per article; every view AFTER seeding is counted for real.
The seeds are drawn at random in [1, MAX_SEED] and then assigned in rank order, so
the displayed ranking is identical to the true-impression ranking — the boss's
"排序不能變" constraint is satisfied by construction, not by hope. See
`assign_seeds()` for the monotonicity argument and tests/test_seed_article_view_counts.py
for the property test.

HONESTY BOUNDARY (deliberate, do not erode):
  - The seed is a reader-facing display baseline ONLY. It is a product decision by
    the site owner, not a measurement.
  - Internal analytics and research inputs — scripts/pull_reader_metrics.py,
    scripts/analyze_reader_preferences.py, scripts/build_publication_candidates.py —
    MUST keep reading raw `article_impressions`. Nothing here writes to that table.
  - Seeds live in `articles.details.view_display`, clearly namespaced and stamped,
    so any future reader of the data can tell a seeded baseline from a real count.

Storage: `articles.details` JSONB (no DDL needed — PostgREST cannot run DDL, and
`details` is the schema's documented "保留彈性欄位"). Shape:

    details.view_display = {
      "seed": 742,
      "baseline_real": 38,
      "seeded_at": "2026-07-18T08:00:00+00:00",
      "algo_version": 1
    }

Usage:
  uv run python scripts/seed_article_view_counts.py --dry-run        # inspect, write nothing
  uv run python scripts/seed_article_view_counts.py --apply          # freeze seeds
  uv run python scripts/seed_article_view_counts.py --report         # show displayed counts
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from supabase_sync import SUPABASE_URL, SUPABASE_KEY, HEADERS  # noqa: E402

MAX_SEED = 1417  # boss email-12163: "上限不要1000 改1417 看起來比較不假"
MIN_SEED = 1
TAIL_TARGET = 12  # roughly where the lowest-ranked article should land (see assign_seeds)
ALGO_VERSION = 2  # v1 = ceiling 1000; v2 = ceiling 1417 (round numbers read as fabricated)
PAGE_SIZE = 1000  # PostgREST implicit row cap — must page past it
REQUEST_TIMEOUT = 20


# ─────────────────────────── pure logic (unit-tested) ───────────────────────────


def rank_articles(articles: list[dict], real_views: dict[str, int]) -> list[dict]:
    """Order articles by true view count, descending, with a deterministic tiebreak.

    Ties are broken by published_at (older first) then id, so a re-run produces the
    same ordering — important because the seeds are frozen against this ordering.
    """
    def key(a: dict):
        return (-real_views.get(a["id"], 0), a.get("published_at") or "", a["id"])

    return sorted(articles, key=key)


def assign_seeds(
    n: int,
    rng: random.Random,
    max_seed: int = MAX_SEED,
    tail_target: int = TAIL_TARGET,
) -> list[int]:
    """Draw `n` plausible view counts in [MIN_SEED, max_seed], sorted descending.

    Monotonicity argument: the caller pairs seeds[i] with the i-th ranked article,
    where rank is descending by true views. Since seeds is non-increasing, we get
    real_views[i] >= real_views[j]  =>  seed[i] >= seed[j]  for all i < j.
    No pair is ever inverted, so the displayed ranking matches the true ranking.

    Why a power-law curve and not a flat uniform draw: with 1,634 articles and a
    ceiling of 1,000, drawing uniformly and sorting yields order statistics that
    pile up at both ends — the real first run produced 1000, 1000, 999, 999, 998
    for the top five and single digits across the whole tail. That reads as
    obviously synthetic. Real article traffic is long-tailed, so we sample from a
    long tail instead: base_i = max_seed * (i+1)^(-alpha), with alpha chosen so the
    last article lands near `tail_target`, then multiplicative jitter, then sort.
    Same ceiling, same ordering guarantee, a shape that does not announce itself.
    """
    if n <= 0:
        return []
    if n == 1:
        return [max(MIN_SEED, min(max_seed, round(max_seed * rng.uniform(0.85, 1.0))))]

    alpha = math.log(max_seed / max(tail_target, MIN_SEED)) / math.log(n)
    vals = []
    for i in range(n):
        base = max_seed * (i + 1) ** (-alpha)
        vals.append(max(MIN_SEED, min(max_seed, round(base * rng.uniform(0.85, 1.15)))))
    return sorted(vals, reverse=True)


def displayed_views(view_display: dict | None, real_now: int) -> int | None:
    """The number a reader should see: frozen seed + real growth since seeding.

    Returns None for an un-seeded article so callers can decide (hide vs seed-on-read)
    instead of silently showing a bare real count that would contradict its neighbours.
    """
    if not view_display:
        return None
    seed = int(view_display.get("seed", 0))
    baseline = int(view_display.get("baseline_real", 0))
    return seed + max(0, real_now - baseline)


# ─────────────────────────────── Supabase I/O ───────────────────────────────


def _get(url: str) -> list:
    req = Request(url, headers={**HEADERS, "Prefer": ""}, method="GET")
    with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        body = resp.read()
        return json.loads(body) if body else []


def _paged(table: str, select: str, filters: str = "") -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/{table}?select={quote(select, safe=',')}"
            f"{'&' + filters if filters else ''}&limit={PAGE_SIZE}&offset={offset}"
        )
        batch = _get(url)
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def fetch_published_articles() -> list[dict]:
    return _paged("articles", "id,slug,title,audience,published_at,details", "status=eq.published")


def fetch_real_views() -> dict[str, int]:
    """All-time impression count per article_id (not the 30-day analytics window)."""
    rows = _paged("article_impressions", "article_id")
    return Counter(r["article_id"] for r in rows if r.get("article_id"))


def patch_details(article_id: str, details: dict) -> None:
    url = f"{SUPABASE_URL}/rest/v1/articles?id=eq.{article_id}"
    payload = json.dumps({"details": details}).encode()
    req = Request(url, data=payload, headers={**HEADERS, "Prefer": "return=minimal"}, method="PATCH")
    urlopen(req, timeout=REQUEST_TIMEOUT)


# ─────────────────────────────────── main ───────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write seeds to Supabase")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, write nothing")
    ap.add_argument("--report", action="store_true", help="show current displayed counts")
    ap.add_argument("--reseed", action="store_true", help="overwrite existing seeds (destructive)")
    ap.add_argument("--random-seed", type=int, default=None, help="RNG seed for reproducibility")
    ap.add_argument("--limit-preview", type=int, default=15)
    args = ap.parse_args()

    if not (args.apply or args.dry_run or args.report):
        ap.error("pick one of --dry-run / --apply / --report")

    articles = fetch_published_articles()
    real = fetch_real_views()
    ranked = rank_articles(articles, real)

    seeded = [a for a in ranked if (a.get("details") or {}).get("view_display")]
    unseeded = [a for a in ranked if not (a.get("details") or {}).get("view_display")]

    print(f"published articles : {len(ranked)}")
    print(f"all-time impressions: {sum(real.values())} rows across {len(real)} articles")
    print(f"already seeded      : {len(seeded)}")
    print(f"needs seeding       : {len(unseeded)}")

    if args.report:
        print("\nrank  displayed  real  slug")
        for i, a in enumerate(ranked[: args.limit_preview], 1):
            vd = (a.get("details") or {}).get("view_display")
            d = displayed_views(vd, real.get(a["id"], 0))
            print(f"{i:>4}  {str(d) if d is not None else '—':>9}  {real.get(a['id'], 0):>4}  {a['slug']}")
        return 0

    targets = ranked if args.reseed else unseeded
    if not targets:
        print("\nnothing to seed (all published articles already have a frozen baseline)")
        return 0

    rng = random.Random(args.random_seed)
    if args.reseed:
        # Full re-freeze: the ceiling is spread across the whole corpus.
        seeds = assign_seeds(len(targets), rng)
    else:
        # Incremental: a newly published article has ~0 real views, so it belongs at
        # the BOTTOM of the ranking. Drawing from the full curve would hand it the
        # ceiling and park a brand-new post at rank 1 — exactly the "obviously fake"
        # failure the boss is trying to avoid. Cap it below every frozen neighbour.
        floor = min(
            ((a.get("details") or {}).get("view_display", {}).get("seed", MAX_SEED) for a in seeded),
            default=MAX_SEED,
        )
        cap = max(MIN_SEED, min(MAX_SEED, floor))
        print(f"\nincremental seeding: capping new seeds at {cap} (lowest frozen seed)")
        hot = [a for a in targets if real.get(a["id"], 0) > 0]
        if hot:
            print(f"  note: {len(hot)} unseeded article(s) already have real views — "
                  f"run --reseed to re-freeze the whole corpus if their true rank is not last")
        seeds = assign_seeds(len(targets), rng, max_seed=cap, tail_target=min(TAIL_TARGET, cap))
    now = datetime.now(timezone.utc).isoformat()

    plan = []
    for a, seed in zip(targets, seeds):
        plan.append((a, {"seed": seed, "baseline_real": real.get(a["id"], 0),
                         "seeded_at": now, "algo_version": ALGO_VERSION}))

    print(f"\nplan ({len(plan)} articles, showing first {args.limit_preview}):")
    print("rank  seed  real  slug")
    for i, (a, vd) in enumerate(plan[: args.limit_preview], 1):
        print(f"{i:>4}  {vd['seed']:>4}  {vd['baseline_real']:>4}  {a['slug']}")

    prev = None
    for a, vd in plan:
        assert prev is None or vd["seed"] <= prev, "seed ordering inverted"
        prev = vd["seed"]
    print("\nmonotonicity check: PASS (displayed ranking == true-impression ranking)")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    written = 0
    for a, vd in plan:
        details = dict(a.get("details") or {})
        details["view_display"] = vd
        try:
            patch_details(a["id"], details)
            written += 1
        except (HTTPError, URLError) as exc:
            print(f"FAILED {a['slug']}: {exc}", file=sys.stderr)
    print(f"\nwrote {written}/{len(plan)} seeds")
    return 0 if written == len(plan) else 1


if __name__ == "__main__":
    raise SystemExit(main())
