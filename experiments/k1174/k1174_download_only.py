#!/usr/bin/env python3
"""K1174 — pure download helper (no yfinance, no scanning).

Reads data/earnings_dates.csv (produced by the fetch script), builds the list
of unique T-2..T+2 days, and downloads any missing GKG 12:00 UTC zip files.

Usage:
  uv run python experiments/k1174/k1174_download_only.py [max_minutes]

If max_minutes is provided the script stops after that wall-clock budget
and prints the partial completion state. Default 15 minutes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
GKG_DIR = DATA / "gkg_files"
UA = "Mozilla/5.0 (VolPredResearch; K1174 per-stock PCR fetch)"
BASE_URL = "http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"


def window_dates(event_date):
    ed = pd.Timestamp(event_date)
    return [(ed + pd.Timedelta(days=d)).date() for d in range(-2, 3)]


def fetch_one(date_obj, hhmm="120000") -> bool:
    stamp = date_obj.strftime("%Y%m%d") + hhmm
    out = GKG_DIR / f"{stamp}.gkg.csv.zip"
    if out.exists() and out.stat().st_size > 10_000:
        return True
    url = BASE_URL.format(stamp=stamp)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        if r.status_code == 200 and len(r.content) > 10_000:
            out.write_bytes(r.content)
            return True
        else:
            return False
    except Exception as ex:
        print(f"err {stamp}: {ex}", file=sys.stderr)
        return False


def main() -> int:
    max_minutes = int(sys.argv[1]) if len(sys.argv) > 1 else 15

    events = pd.read_csv(DATA / "earnings_dates.csv")
    events["event_date_utc"] = pd.to_datetime(events["event_date_utc"]).dt.date

    unique_days = set()
    for _, r in events.iterrows():
        for d in window_dates(r["event_date_utc"]):
            unique_days.add(d)
    unique_days = sorted(unique_days)
    print(f"[dl] unique days to check: {len(unique_days)}")

    already = sum(1 for d in unique_days
                  if (GKG_DIR / f"{d.strftime('%Y%m%d')}120000.gkg.csv.zip").exists())
    print(f"[dl] already cached: {already}")

    t0 = time.time()
    ok = 0
    miss = 0
    for i, d in enumerate(unique_days):
        if (time.time() - t0) / 60 > max_minutes:
            print(f"[dl] budget {max_minutes}m exhausted at {i}/{len(unique_days)}")
            break
        r = fetch_one(d)
        if r:
            ok += 1
        else:
            miss += 1
        if (i + 1) % 20 == 0:
            el = time.time() - t0
            total = len(list(GKG_DIR.glob("*.gkg.csv.zip")))
            print(f"[dl] iter {i+1}/{len(unique_days)} in {el:.0f}s cached={total}")
        time.sleep(0.2)
    total = len(list(GKG_DIR.glob("*.gkg.csv.zip")))
    print(f"[dl] final cached: {total}, session ok={ok} miss={miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
