#!/usr/bin/env python3
"""K1157 helper: prefetch earnings surprise data for 30 TOPIX JP tickers.

Mirrors K1151 fetch_surprises.py but for JP tickers. Writes
experiments/k1157/data/earnings_surprises.json with:
  { ticker: [ {"date": "YYYY-MM-DD", "estimate": float, "reported": float,
               "surprise_pct": float}, ... ] }

Only past announcements (date < today) with non-NaN Surprise(%).
yfinance returns Surprise(%) for JP tickers (verified for 7203.T/6758.T/9984.T).
Note: 9984.T (SoftBank) has extreme estimate magnitudes (raw |surprise|
can reach 1000%+), so winsorization at p99 is essential.
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_PATH = SCRIPT_DIR / 'data' / 'earnings_surprises.json'
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

TICKERS = [
    '7203.T', '6758.T', '9984.T', '8306.T', '6861.T', '9432.T',
    '6098.T', '7974.T', '6594.T', '8035.T', '4063.T', '6501.T',
    '9433.T', '8316.T', '8411.T', '6902.T', '6367.T', '8001.T',
    '8058.T', '4502.T', '6273.T', '7741.T', '6981.T', '8801.T',
    '6178.T', '7267.T', '8031.T', '4503.T', '8002.T', '6701.T',
]

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'


def fetch_one(ticker):
    tk = yf.Ticker(ticker)
    df = tk.get_earnings_dates(limit=100)
    if df is None or len(df) == 0:
        return []
    today = pd.Timestamp.now(tz=df.index.tz if df.index.tz else None)
    past = df[df.index < today]
    past = past.dropna(subset=['Surprise(%)'])
    start_ts = pd.Timestamp(DATA_START)
    end_ts = pd.Timestamp(DATA_END)
    if df.index.tz is not None:
        start_ts = start_ts.tz_localize(df.index.tz)
        end_ts = end_ts.tz_localize(df.index.tz)
    past = past[past.index >= start_ts]
    past = past[past.index <= end_ts]
    records = []
    for dt, row in past.iterrows():
        records.append({
            'date': dt.tz_localize(None).normalize().isoformat(),
            'estimate': float(row['EPS Estimate']) if pd.notna(row['EPS Estimate']) else None,
            'reported': float(row['Reported EPS']) if pd.notna(row['Reported EPS']) else None,
            'surprise_pct': float(row['Surprise(%)']),
        })
    records.sort(key=lambda r: r['date'])
    return records


def main():
    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            cache = json.load(f)
    for tk in TICKERS:
        if tk in cache and len(cache[tk]) > 0:
            print(f'[skip] {tk}: already cached ({len(cache[tk])} events)')
            continue
        try:
            recs = fetch_one(tk)
            cache[tk] = recs
            if len(recs) > 0:
                surp = np.array([abs(r['surprise_pct']) for r in recs])
                print(f'[ok]   {tk}: {len(recs)} events, |surp| mean={surp.mean():.2f}% std={surp.std():.2f}% max={surp.max():.2f}%')
            else:
                print(f'[ok]   {tk}: 0 events')
            with open(CACHE_PATH, 'w') as f:
                json.dump(cache, f, indent=2)
            time.sleep(1.5)
        except Exception as e:
            print(f'[fail] {tk}: {e}')
    print(f'\nCache -> {CACHE_PATH}')
    total = sum(len(v) for v in cache.values())
    print(f'Total records: {total}')


if __name__ == '__main__':
    main()
