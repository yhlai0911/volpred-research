#!/usr/bin/env python3
"""K1174 — scan-only helper.

Operates on whatever GKG zip files are already cached in data/gkg_files/.
Produces data/per_stock_window_counts.csv and data/per_day_ticker_counts.csv
so that k1174.py can run.

This is useful when the fetch loop was interrupted before completion — only
events whose full 5-day window falls inside the cached date range will have
complete PCR. k1174.py drops incomplete events automatically.

Random seed: 42 (not used; scan is deterministic).
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Dict, List

import pandas as pd

# Reuse the STOCK_NAME_MAP from the fetch script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from k1174_fetch_gdelt_files import (
    STOCK_NAME_MAP, build_pattern, scan_file_for_tickers,
    window_dates, GKG_DIR, DATA, HERE,
)


def main() -> int:
    # Load events (already written by a prior fetch-script invocation)
    events_path = DATA / "earnings_dates.csv"
    if not events_path.exists():
        print("ERROR: earnings_dates.csv not found; run fetch script first.",
              file=sys.stderr)
        return 2
    events = pd.read_csv(events_path)
    events["event_date_utc"] = pd.to_datetime(events["event_date_utc"]).dt.date

    # Patterns
    patterns = {t: build_pattern(info["names"]) for t, info in STOCK_NAME_MAP.items()}

    # Scan every cached file
    print(f"[K1174 scan] STOCK_NAME_MAP size: {len(patterns)}")
    cached = sorted(GKG_DIR.glob("*.gkg.csv.zip"))
    print(f"[K1174 scan] cached files: {len(cached)}")

    per_day_counts: Dict[str, Dict[str, int]] = {}
    t_start = time.time()
    for i, zp in enumerate(cached):
        # Extract date from filename: e.g., 20240125120000.gkg.csv.zip
        stem = zp.name.split(".")[0]  # 20240125120000 or 20240125114500
        day_str = stem[:8]
        day_iso = f"{day_str[:4]}-{day_str[4:6]}-{day_str[6:8]}"
        counts = scan_file_for_tickers(zp, patterns)
        # Merge with any prior entries (if multiple files per day)
        d = per_day_counts.setdefault(day_iso, {t: 0 for t in patterns})
        for t, c in counts.items():
            d[t] = max(d[t], c)  # take max when multiple slices same day
        if (i + 1) % 20 == 0:
            el = time.time() - t_start
            print(f"[K1174 scan] scanned {i+1}/{len(cached)} in {el:.0f}s")

    # per-day output
    rows = []
    for day, counts in per_day_counts.items():
        for t, c in counts.items():
            rows.append({"date_utc": day, "ticker": t, "count": int(c)})
    pd.DataFrame(rows).to_csv(DATA / "per_day_ticker_counts.csv", index=False)

    # per-event 5-day window
    ev_rows = []
    for _, ev in events.iterrows():
        win = window_dates(ev["event_date_utc"])
        for offset, d in enumerate(win, start=-2):
            c = per_day_counts.get(d.isoformat(), {}).get(ev["ticker"])
            ev_rows.append({
                "ticker": ev["ticker"],
                "event_date": ev["event_date_utc"],
                "day_offset": offset,
                "date_utc": d.isoformat(),
                "count": (int(c) if c is not None else None),
            })
    ev_df = pd.DataFrame(ev_rows)
    ev_df.to_csv(DATA / "per_stock_window_counts.csv", index=False)

    print(f"[K1174 scan] {len(rows)} day-ticker rows")
    print(f"[K1174 scan] {len(ev_df)} event-day rows")

    # stock_company_map (re-emit for safety)
    pd.DataFrame([
        {"ticker": t, "market": info["market"], "names": "|".join(info["names"])}
        for t, info in STOCK_NAME_MAP.items()
    ]).to_csv(DATA / "stock_company_map.csv", index=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
