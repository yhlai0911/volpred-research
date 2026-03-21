"""Daily 5-min data collector for future Realized GARCH.

Run daily via cron: 0 22 * * 1-5 uv run python scripts/collect_5min_data.py

Collects SPY 5-min data from yfinance (free, but only ~60 days history).
After 60+ days of collection, we'll have enough for Realized GARCH OOS testing.

Storage: data/intraday/SPY_5min_YYYY-MM-DD.csv
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf


def _detect_gap_days(ticker, output_dir):
    """Detect how many days back we need to fetch based on existing files.

    Checks two conditions:
    1. Gap since latest file (e.g. system was down for a few days)
    2. Coverage start too recent (e.g. only 7 days of data when 59 are possible)
    """
    pattern = f"{ticker}_5min_*.csv"
    existing = sorted(output_dir.glob(pattern))
    if not existing:
        return 59  # No data at all — fetch max (yfinance 5-min limit ~60 days)
    today = datetime.now().date()
    try:
        # Check gap since latest file
        latest_str = existing[-1].stem.split("_5min_")[-1]
        latest_date = datetime.strptime(latest_str, "%Y-%m-%d").date()
        gap_latest = (today - latest_date).days

        # Check if earliest file is much newer than 59 days ago (incomplete backfill)
        earliest_str = existing[0].stem.split("_5min_")[-1]
        earliest_date = datetime.strptime(earliest_str, "%Y-%m-%d").date()
        gap_earliest = (today - earliest_date).days

        # If we have less than ~40 trading days and could fetch more, do a full backfill
        if gap_earliest < 55 and len(existing) < 40:
            return 59

        # Otherwise just fill the gap since latest file
        return min(max(gap_latest + 2, 7), 59)
    except ValueError:
        return 59


def collect_5min(ticker='SPY', days_back=None):
    """Collect recent 5-min data and save to CSV.

    If days_back is None, auto-detect gap from existing files and backfill.
    yfinance free tier keeps ~60 days of 5-min data.
    """
    output_dir = Path('data/intraday')
    output_dir.mkdir(parents=True, exist_ok=True)

    if days_back is None:
        days_back = _detect_gap_days(ticker, output_dir)
        print(f"  Auto-detected: fetching {days_back} days back for {ticker}")

    end = datetime.now()
    start = end - timedelta(days=days_back)

    data = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                       end=end.strftime('%Y-%m-%d'),
                       interval='5m', progress=False)

    if len(data) == 0:
        print(f"No 5-min data for {ticker}")
        return

    # Save each trading day as separate file
    for date, group in data.groupby(data.index.date):
        filename = output_dir / f"{ticker}_5min_{date}.csv"
        if not filename.exists():
            group.to_csv(filename)
            print(f"  Saved {filename.name} ({len(group)} bars)")
        else:
            pass  # Already collected

    # Compute daily RV from 5-min returns
    data['returns'] = data['Close'].pct_change()
    daily_rv = data.groupby(data.index.date)['returns'].apply(
        lambda x: (x.dropna()**2).sum()
    )

    # Save/append to cumulative RV file
    rv_file = output_dir / f"{ticker}_daily_rv.csv"
    if rv_file.exists():
        existing = pd.read_csv(rv_file, index_col=0, parse_dates=True)
        new_rv = pd.DataFrame({'rv_5min': daily_rv})
        new_rv.index = pd.DatetimeIndex(daily_rv.index)
        combined = pd.concat([existing, new_rv])
        combined = combined[~combined.index.duplicated(keep='last')]
        combined.sort_index().to_csv(rv_file)
    else:
        rv_df = pd.DataFrame({'rv_5min': daily_rv})
        rv_df.index = pd.DatetimeIndex(daily_rv.index)
        rv_df.to_csv(rv_file)

    total_rv = pd.read_csv(rv_file, index_col=0)
    print(f"\n{ticker} 5-min RV: {len(total_rv)} days total")
    print(f"Latest: {total_rv.index[-1]}")


if __name__ == '__main__':
    collect_5min('SPY')  # Auto-detect gap and backfill (up to ~60 days)
    print("\nDone.")
