#!/usr/bin/env python3
"""
fetch_usdtwd_snapshot.py — one-shot fetch & PIN of USDTWD daily snapshot

Per .claude/rules/paper-workflow.md hard rule #1:
  - Paper reproduction CSV must be PINNED with auto_adjust=False
  - reproduce.py and experiment scripts read snapshot, never live fetch

Output: paper/taiwan-vt/data/_usdtwd_snapshot.csv with header:
    # fetched_at=<ISO UTC>
    # ticker=TWD=X
    # range=<start>..<end>
    # auto_adjust=False
    date,usdtwd_close

Re-running OVERWRITES with a refreshed snapshot — do not run unintentionally;
existing snapshot is authoritative for reproduction.
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
OUT_CSV = REPO_ROOT / "paper" / "taiwan-vt" / "data" / "_usdtwd_snapshot.csv"

DEFAULT_START = "2008-01-01"
DEFAULT_END = "2026-03-31"
TICKER = "TWD=X"  # yfinance USDTWD spot FX


def fetch(start: str, end: str) -> pd.DataFrame:
    raw = yf.download(TICKER, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close = raw["Close"].dropna()
    df = close.rename("usdtwd_close").to_frame()
    df.index.name = "date"
    return df


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
    print(f"  date range: {df.index[0].date()} .. {df.index[-1].date()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
