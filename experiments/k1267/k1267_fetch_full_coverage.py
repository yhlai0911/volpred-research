#!/usr/bin/env python3
"""K1267 — Full 96-files-per-day GDELT GKG fetch (scope-up of K1174).

K1174 sampled 1/96 (only `120000` UTC slice) per calendar day across 132 days
(Jan 9 – Jul 10 2024) for 31 top-analyst stocks across 9 markets. The sample
gave EU n=3 / JP n=2 with the K1170 EU-JP gap collapsing from +0.450 to
+0.005 (Welch p=0.98), but the verdict was `INSUFFICIENT_COVERAGE`.

K1267 scopes K1174 up to **all 96 fifteen-minute slices per day** for the
SAME 132 calendar days, using the public GDELT bulk endpoint
(http://data.gdeltproject.org/gdeltv2/), no GCP auth required.

Strategy
--------
- Load earnings_dates + stock_company_map + already-cached 12:00 UTC counts
  from K1174 (so we only need to fetch the missing 95 slices/day).
- For each calendar day in the K1174 window, iterate all 96 stamps. Skip the
  120000 stamp if K1174 already counted it (we keep its number to avoid
  double-fetch).
- **STREAMING design**: for each file we (a) download to a tmp path, (b)
  scan the V2Persons + V2Organizations columns substring-matched against
  the per-ticker pattern, (c) **delete the zip immediately**. We never keep
  more than ~10 MB on disk at once. This avoids the ~63 GB blow-up that
  full download would otherwise produce (132 days × 95 slices × 5 MB).
- Parallelism: ThreadPoolExecutor with ~6 workers. GDELT bulk endpoint is
  Google Cloud Storage backed; concurrent fetches are friendly.
- Per-file scan accumulates into per_day_ticker_counts (sum across the 96
  slices in that day).
- Retries: 3 attempts per file with 3s sleep. After 3 fails the slice is
  logged as MISS and skipped; we expect ~0.1 % miss rate from GDELT
  occasional 404s.

Lookahead / seed discipline
---------------------------
- Earnings windows are backward-looking T-2..T+2 around an already-elapsed
  earnings date — no future data leakage.
- All randomness uses np.random.default_rng(42) downstream (no random in
  the fetch itself; fetch is deterministic by file timestamp).

Output
------
data/per_day_ticker_counts_full.csv      — per (date_utc, ticker, count) summed
                                            across all 96 slices fetched
data/per_day_slice_counts.csv            — per (date_utc, hhmm, ticker, count)
                                            (so per-slice contribution can be
                                            audited / weighed)
data/fetch_status_full.json              — per (date_utc, hhmm) OK / MISS

Usage
-----
  uv run python experiments/k1267/k1267_fetch_full_coverage.py [--max-days N]
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (VolPredResearch; K1267 full-coverage GDELT scan, scale-up of K1174)"
BASE_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"

# GKG 2.1 column positions (0-indexed)
COL_V2PERSONS = 12
COL_V2ORGS = 14

# All 96 fifteen-minute stamps in a day
ALL_HHMM: List[str] = [f"{h:02d}{m:02d}00" for h in range(24) for m in (0, 15, 30, 45)]


def load_inputs() -> Tuple[pd.DataFrame, Dict[str, Dict], pd.DataFrame]:
    """Load earnings, stock map, and K1174 12:00 UTC cache."""
    events = pd.read_csv(DATA / "earnings_dates_from_k1174.csv")
    events["event_date_utc"] = pd.to_datetime(events["event_date_utc"]).dt.date

    smap = pd.read_csv(DATA / "stock_company_map.csv")
    stock_map: Dict[str, Dict] = {}
    for _, r in smap.iterrows():
        stock_map[r["ticker"]] = {
            "market": r["market"],
            "names": [n for n in str(r["names"]).split("|") if n.strip()],
        }

    k1174_cache = pd.read_csv(DATA / "per_day_ticker_counts_k1174_120000.csv")
    return events, stock_map, k1174_cache


def window_dates(event_date) -> List[date]:
    ed = pd.Timestamp(event_date)
    return [(ed + pd.Timedelta(days=d)).date() for d in range(-2, 3)]


def collect_unique_dates(events: pd.DataFrame) -> List[date]:
    days: set = set()
    for _, row in events.iterrows():
        for d in window_dates(row["event_date_utc"]):
            days.add(d)
    return sorted(days)


def build_pattern(names: List[str]) -> re.Pattern:
    parts = [re.escape(n.strip().lower()) for n in names if n.strip()]
    return re.compile("|".join(parts), flags=re.IGNORECASE)


def scan_zip_bytes(content: bytes, patterns: Dict[str, re.Pattern]) -> Dict[str, int]:
    """Scan an in-memory GKG zip, count rows per ticker. Stream — no disk write."""
    counts: Dict[str, int] = {t: 0 for t in patterns}
    try:
        with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
            name = zf.namelist()[0]
            with zf.open(name) as f:
                for raw in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                    cols = raw.split("\t")
                    if len(cols) < 16:
                        continue
                    hay = (cols[COL_V2PERSONS] + " " + cols[COL_V2ORGS]).lower()
                    for t, pat in patterns.items():
                        if pat.search(hay):
                            counts[t] += 1
    except Exception as ex:
        print(f"  scan FAIL: {ex}", file=sys.stderr)
    return counts


def fetch_and_scan_one(stamp: str, patterns: Dict[str, re.Pattern],
                        max_retries: int = 3) -> Tuple[str, Dict[str, int] | None]:
    """Download one GKG file, scan it, discard the bytes. Return per-ticker counts."""
    url = BASE_URL.format(stamp=stamp)
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=45)
            if r.status_code == 200 and len(r.content) > 10_000:
                counts = scan_zip_bytes(r.content, patterns)
                return ("OK", counts)
            elif r.status_code == 404:
                return ("MISS_404", None)
            else:
                # transient / other; retry
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                return (f"MISS_{r.status_code}", None)
        except Exception as ex:
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
            return (f"FAIL_{type(ex).__name__}", None)
    return ("MISS", None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=int, default=None,
                    help="Cap number of unique calendar days (debug).")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--start-day-idx", type=int, default=0)
    args = ap.parse_args()

    events, stock_map, k1174_cache = load_inputs()
    print(f"[K1267] {len(events)} earnings events, {len(stock_map)} stocks", flush=True)

    unique_days = collect_unique_dates(events)
    if args.max_days is not None:
        unique_days = unique_days[args.start_day_idx:args.start_day_idx + args.max_days]
    else:
        unique_days = unique_days[args.start_day_idx:]
    print(f"[K1267] {len(unique_days)} unique calendar days to process", flush=True)

    patterns = {t: build_pattern(info["names"]) for t, info in stock_map.items()}
    n_tickers = len(patterns)

    # K1174 cached 120000 counts: index by (date_iso, ticker)
    k1174_lookup: Dict[Tuple[str, str], int] = {}
    for _, r in k1174_cache.iterrows():
        k1174_lookup[(str(r["date_utc"]), r["ticker"])] = int(r["count"])

    # Output buffers
    slice_rows: List[Dict] = []   # per (day, hhmm, ticker, count) — for audit
    day_status: Dict[str, Dict[str, str]] = {}   # day_iso -> hhmm -> status
    failed_files = 0
    ok_files = 0
    total_files_attempted = 0

    out_slice_path = DATA / "per_day_slice_counts.csv"
    out_status_path = DATA / "fetch_status_full.json"
    progress_path = DATA / "progress.json"

    # CSV streaming write (one row per slice per ticker with non-zero count)
    # Header
    with open(out_slice_path, "w", encoding="utf-8") as fout:
        fout.write("date_utc,hhmm,ticker,count\n")

        # First, push K1174 cached 120000 rows so we don't re-fetch
        for (d_iso, tk), c in k1174_lookup.items():
            if c > 0:
                fout.write(f"{d_iso},120000,{tk},{c}\n")

        t_start = time.time()
        for day_i, d in enumerate(unique_days):
            d_iso = d.isoformat()
            day_status[d_iso] = {}
            stamps_to_fetch = [s for s in ALL_HHMM if s != "120000"]
            # Mark 120000 status from K1174 — OK if any cached row exists for this day
            # (K1174 either fetched this day's 120000 or not)
            day_120000_ok = any((d_iso, tk) in k1174_lookup for tk in patterns)
            day_status[d_iso]["120000"] = "OK_FROM_K1174" if day_120000_ok else "MISS_K1174"

            # Per-day fetch all 95 missing slices, parallelized
            day_t0 = time.time()
            day_counts_acc: Dict[str, int] = {t: 0 for t in patterns}
            # carry K1174 counts into the accumulator
            for tk in patterns:
                day_counts_acc[tk] += k1174_lookup.get((d_iso, tk), 0)

            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                futures = {}
                for hhmm in stamps_to_fetch:
                    stamp = d.strftime("%Y%m%d") + hhmm
                    fut = ex.submit(fetch_and_scan_one, stamp, patterns)
                    futures[fut] = hhmm
                for fut in as_completed(futures):
                    hhmm = futures[fut]
                    total_files_attempted += 1
                    status, counts = fut.result()
                    day_status[d_iso][hhmm] = status
                    if status == "OK" and counts is not None:
                        ok_files += 1
                        for tk, c in counts.items():
                            if c > 0:
                                fout.write(f"{d_iso},{hhmm},{tk},{c}\n")
                                day_counts_acc[tk] += c
                    else:
                        failed_files += 1

            day_dt = time.time() - day_t0
            elapsed = time.time() - t_start
            eta = elapsed / (day_i + 1) * (len(unique_days) - day_i - 1)
            print(
                f"[K1267] day {day_i+1}/{len(unique_days)} {d_iso} "
                f"in {day_dt:.0f}s; cum ok={ok_files} miss={failed_files}; "
                f"elapsed={elapsed/60:.1f}m eta={eta/60:.1f}m",
                flush=True,
            )
            # progress checkpoint every 5 days
            if (day_i + 1) % 5 == 0:
                progress = {
                    "days_done": day_i + 1,
                    "days_total": len(unique_days),
                    "files_ok": ok_files,
                    "files_miss": failed_files,
                    "elapsed_seconds": elapsed,
                }
                progress_path.write_text(json.dumps(progress, indent=2),
                                          encoding="utf-8")

    # Save final status
    out_status_path.write_text(json.dumps({
        "n_days": len(unique_days),
        "n_files_attempted": total_files_attempted,
        "n_files_ok": ok_files,
        "n_files_miss": failed_files,
        "miss_rate": failed_files / max(total_files_attempted, 1),
        "expected_files_per_day": 96,
        "per_day": day_status,
    }, indent=2, default=str), encoding="utf-8")

    # Aggregate per-day-per-ticker counts (sum across slices) and write CSV
    print("[K1267] aggregating per-day counts...", flush=True)
    slice_df = pd.read_csv(out_slice_path)
    agg = (slice_df.groupby(["date_utc", "ticker"], as_index=False)["count"].sum())
    agg.to_csv(DATA / "per_day_ticker_counts_full.csv", index=False)

    print(f"[K1267] DONE: {ok_files}/{total_files_attempted} slices OK "
          f"(miss rate {failed_files/max(total_files_attempted,1):.4f})",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
