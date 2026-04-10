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


def _safe_ticker(ticker):
    """Convert ticker to filesystem-safe name (e.g., 0050.TW -> 0050_TW)."""
    return ticker.replace('.', '_')


def _detect_gap_days(ticker, output_dir):
    """Always fetch max window (59 days) — expanding window strategy.

    yfinance only keeps ~60 days of 5-min data. If we miss a day, it's gone forever.
    So we always request the full 59-day window and skip files we already have.
    The cost is one slightly larger API call; the benefit is zero data loss risk.
    """
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
    safe = _safe_ticker(ticker)
    for date, group in data.groupby(data.index.date):
        filename = output_dir / f"{safe}_5min_{date}.csv"
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
    rv_file = output_dir / f"{safe}_daily_rv.csv"
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
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'SPY'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else None
    collect_5min(ticker, days_back=days)
    print("\nDone.")
