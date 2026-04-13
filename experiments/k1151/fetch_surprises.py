#!/usr/bin/env python3
"""K1151 helper: prefetch earnings surprise data for 30 US tickers.

Writes experiments/k1151/data/earnings_surprises.json with:
  { ticker: [ {"date": "YYYY-MM-DD", "estimate": float, "reported": float,
               "surprise_pct": float}, ... ] }

Only past announcements (date < today) with non-NaN Surprise(%).
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
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
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
    # Drop rows with missing Surprise (e.g., very old or future)
    past = past.dropna(subset=['Surprise(%)'])
    past = past[past.index >= pd.Timestamp(DATA_START).tz_localize(df.index.tz)]
    past = past[past.index <= pd.Timestamp(DATA_END).tz_localize(df.index.tz)]
    records = []
    for dt, row in past.iterrows():
        records.append({
            'date': dt.tz_localize(None).normalize().isoformat(),
            'estimate': float(row['EPS Estimate']) if pd.notna(row['EPS Estimate']) else None,
            'reported': float(row['Reported EPS']) if pd.notna(row['Reported EPS']) else None,
            'surprise_pct': float(row['Surprise(%)']),
        })
    # Sort ascending by date
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
            surp = np.array([abs(r['surprise_pct']) for r in recs])
            print(f'[ok]   {tk}: {len(recs)} events, |surprise| mean={surp.mean():.2f}% std={surp.std():.2f}%')
            with open(CACHE_PATH, 'w') as f:
                json.dump(cache, f, indent=2)
            time.sleep(1.2)
        except Exception as e:
            print(f'[fail] {tk}: {e}')
    print(f'\nCache -> {CACHE_PATH}')
    total = sum(len(v) for v in cache.values())
    print(f'Total records: {total}')


if __name__ == '__main__':
    main()
