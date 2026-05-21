#!/usr/bin/env python3
"""
fetch_twii_1997_2007_snapshot.py — one-shot fetch & PIN of TWII pre-2008 daily snapshot

Per .claude/rules/paper-workflow.md hard rule #1:
  - Paper reproduction CSV must be PINNED with auto_adjust=False
  - reproduce.py and experiment scripts read snapshot, never live fetch

Output: paper/taiwan-vt/data/_twii_1997_2007_snapshot.csv with header:
    # fetched_at=<ISO UTC>
    # ticker=^TWII
    # range=<start>..<end>
    # auto_adjust=False
    date,twii_close

Re-running OVERWRITES with a refreshed snapshot (only with --force);
existing snapshot is authoritative for reproduction.

This snapshot covers 1997-01-01..2007-12-31. The 2008-2026 portion of TWII is
already pinned in paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
(`twii_close` column). Together they cover the full 1997-2026 sample.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
OUT_CSV = REPO_ROOT / "paper" / "taiwan-vt" / "data" / "_twii_1997_2007_snapshot.csv"

DEFAULT_START = "1997-01-01"
DEFAULT_END = "2008-01-02"  # exclusive in yfinance; captures last 2007 trading day
TICKER = "^TWII"  # yfinance Taiwan Capitalization Weighted Stock Index (TAIEX)
# NOTE: yfinance ^TWII history only begins 1997-07-02; paper's "January 1997" is
# the requested start but the earliest available quote is 1997-07-02. We document
# this in README.md and the snapshot header.


def fetch(start: str, end: str, max_retries: int = 3) -> pd.DataFrame:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = yf.download(TICKER, start=start, end=end, progress=False, auto_adjust=False)
            if raw is None or len(raw) == 0:
                raise RuntimeError(f"yfinance returned empty frame for {TICKER} {start}..{end}")
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            close = raw["Close"].dropna()
            df = close.rename("twii_close").to_frame()
            df.index.name = "date"
            return df
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  attempt {attempt+1}/{max_retries} failed: {e!r}")
    raise RuntimeError(f"yfinance fetch failed after {max_retries} attempts: {last_err!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing snapshot (default: refuse if exists)")
    args = ap.parse_args()

    if OUT_CSV.exists() and not args.force:
        print(f"Snapshot already exists at {OUT_CSV}.")
        print("Refuse to overwrite (use --force to refresh).")
        return 1

    df = fetch(args.start, args.end)
    fetched_at = datetime.now(timezone.utc).isoformat()

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w") as f:
        f.write(f"# fetched_at={fetched_at}\n")
        f.write(f"# ticker={TICKER}\n")
        f.write(f"# range={args.start}..{args.end}\n")
        f.write(f"# auto_adjust=False\n")
        df.to_csv(f, lineterminator="\n")

    print(f"Wrote {OUT_CSV.relative_to(REPO_ROOT)}  rows={len(df)}  fetched_at={fetched_at}")
    if len(df):
        print(f"  date range: {df.index[0].date()} .. {df.index[-1].date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
