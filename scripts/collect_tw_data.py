"""台股數據收集（台股收盤後 14:00 執行）

收集：
- 0050.TW 日線（yfinance）
- 0050.TW 5-min data（yfinance，用於 Realized Volatility）
- VIXTWN（TAIFEX）

Cron: 0 14 * * 1-5
"""
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

PROJECT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT / ".venv" / "bin" / "python"


def _detect_gap_days(ticker, output_dir):
    """Detect how many days back we need to fetch based on existing files.

    Checks two conditions:
    1. Gap since latest file (e.g. system was down for a few days)
    2. Coverage start too recent (e.g. only 7 days of data when 59 are possible)
    """
    safe_ticker = ticker.replace('.', '_')
    pattern = f"{safe_ticker}_5min_*.csv"
    existing = sorted(output_dir.glob(pattern))
    if not existing:
        return 59
    today = datetime.now().date()
    try:
        latest_str = existing[-1].stem.split("_5min_")[-1]
        latest_date = datetime.strptime(latest_str, "%Y-%m-%d").date()
        gap_latest = (today - latest_date).days

        earliest_str = existing[0].stem.split("_5min_")[-1]
        earliest_date = datetime.strptime(earliest_str, "%Y-%m-%d").date()
        gap_earliest = (today - earliest_date).days

        if gap_earliest < 55 and len(existing) < 40:
            return 59

        return min(max(gap_latest + 2, 7), 59)
    except ValueError:
        return 59


def collect_5min(ticker, output_dir):
    """Collect recent 5-min data and save to CSV + compute RV.

    Auto-detects gap from existing files and backfills up to 59 days.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    days_back = _detect_gap_days(ticker, output_dir)
    print(f"  Auto-detected: fetching {days_back} days back for {ticker}")

    end = datetime.now()
    start = end - timedelta(days=days_back)

    data = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                       end=end.strftime('%Y-%m-%d'),
                       interval='5m', progress=False)

    if len(data) == 0:
        print(f"  No 5-min data for {ticker}")
        return

    # Save each trading day as separate file
    for date, group in data.groupby(data.index.date):
        filename = output_dir / f"{ticker.replace('.', '_')}_5min_{date}.csv"
        if not filename.exists():
            group.to_csv(filename)
            print(f"  Saved {filename.name} ({len(group)} bars)")

    # Compute daily RV
    data['returns'] = data['Close'].pct_change()
    daily_rv = data.groupby(data.index.date)['returns'].apply(
        lambda x: (x.dropna()**2).sum()
    )

    rv_file = output_dir / f"{ticker.replace('.', '_')}_daily_rv.csv"
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
    print(f"  {ticker} 5-min RV: {len(total_rv)} days total")


def main():
    now = datetime.now()
    print(f"=== 台股數據收集: {now.strftime('%Y-%m-%d %H:%M')} ===")

    # 1. VIXTWN（TAIFEX 來源）
    print("\n--- VIXTWN ---")
    try:
        subprocess.run(
            [str(VENV_PYTHON), str(PROJECT / "scripts" / "collect_vixtwn.py")],
            cwd=str(PROJECT),
            timeout=60,
        )
    except Exception as e:
        print(f"  VIXTWN error: {e}")

    # 2. 0050.TW 日線快取更新
    print("\n--- 0050.TW 日線 ---")
    try:
        sys.path.insert(0, str(PROJECT / "src"))
        from volpred.data.manager import DataManager
        dm = DataManager()
        tw50 = dm.get_model_data("0050.TW", "2020-01-01", "2026-12-31")
        print(f"  0050.TW: {tw50.index[-1].date()} close={float(tw50.iloc[-1]['close']):.2f} ({len(tw50)} rows)")
    except Exception as e:
        print(f"  0050.TW 日線 error: {e}")

    # 3. 0050.TW 5-min data
    print("\n--- 0050.TW 5-min ---")
    try:
        collect_5min("0050.TW", PROJECT / "data" / "intraday")
    except Exception as e:
        print(f"  0050.TW 5-min error: {e}")

    print("\n✓ 台股數據收集完成")


if __name__ == "__main__":
    main()
