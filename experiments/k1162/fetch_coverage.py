#!/usr/bin/env python3
"""
K1162 helper: fetch analyst coverage + market cap for the K1147/K1151 US
N=30 pool via yfinance, and persist to coverage.json for downstream use.

Coverage proxies considered:
  1. numberOfAnalystOpinions (current snapshot, from Ticker.info)
  2. marketCap (fallback if numberOfAnalystOpinions missing)

Trailing 12M coverage is not directly available from yfinance free API,
so we use the current snapshot as the cross-sectional classifier. This
still introduces a minor lookahead concern (coverage may have drifted),
but K1162 is a mechanism-isolation experiment; we document the
limitation in README.

If yfinance API fails, the script falls back to marketCap-only mode.
"""
import json
import os
import time
from pathlib import Path

import yfinance as yf

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = SCRIPT_DIR / 'data' / 'coverage.json'

TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]


def fetch_one(tk_str):
    """Return dict with numAnalysts + marketCap (None if missing)."""
    out = {'ticker': tk_str, 'numAnalysts': None, 'marketCap': None,
           'recMean': None, 'source': None}
    try:
        info = yf.Ticker(tk_str).info
        out['numAnalysts'] = info.get('numberOfAnalystOpinions')
        out['marketCap'] = info.get('marketCap')
        out['recMean'] = info.get('recommendationMean')
        out['source'] = 'yfinance.info'
    except Exception as e:
        out['error'] = str(e)
    return out


def main():
    print(f'Fetching analyst coverage for {len(TICKERS)} tickers ...')
    results = []
    for i, t in enumerate(TICKERS, 1):
        r = fetch_one(t)
        results.append(r)
        print(f'  [{i:2d}/30] {t:8s}: analysts={r["numAnalysts"]}, '
              f'cap={r["marketCap"]}')
        time.sleep(0.6)  # gentle rate limit
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'\nSaved to {OUT_PATH}')

    # summary
    with_analyst = sum(1 for r in results if r['numAnalysts'] is not None)
    with_cap = sum(1 for r in results if r['marketCap'] is not None)
    print(f'  Have numAnalysts: {with_analyst}/30')
    print(f'  Have marketCap:   {with_cap}/30')


if __name__ == '__main__':
    main()
