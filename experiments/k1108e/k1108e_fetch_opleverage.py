#!/usr/bin/env python3
"""K1108e helper: fetch operating leverage covariates for 5-foundry pool.

Pool (matching K1108b): TSMC 2330.TW, UMC 2303.TW, TSM (ADR), GFS, SMIC 0981.HK.

Data source
-----------
yfinance `Ticker(x).balance_sheet` (annual) + `.financials` (annual) — these
are the only reliably free cross-foundry sources. We also capture quarterly
where available but fall back to annual when quarterly is sparse.

**Known yfinance coverage limitation** (tested 2026-04-17): annual balance
sheet + income statement cover **2021-2025 only** (5 fiscal years) for all
5 foundries. Quarterly is limited to 4-6 most recent quarters. The
2014-2020 range that K1108c events span is NOT available from yfinance.

Consequence for K1108e: op_leverage covariate only available for events in
2021-2025. We accept this reduced sample and document the restriction in
README; the D3 operating-leverage hypothesis is testable on the 2021-2025
sub-window only.

Op leverage definitions
-----------------------
Given annual fiscal-year figures at year-end t:
  op_leverage_1  := Net PPE_t / Total Revenue_t                 (asset intensity)
  op_leverage_2  := Total Debt_t / Stockholders Equity_t        (financial leverage)
  op_leverage_3  := (Net PPE_t + SG&A_t) / Total Revenue_t      (combined cost rigidity)

Event-day matching
------------------
For an earnings event on date d, use the **most recent fiscal-year-end
published at least 45 days before d**:
  fy_end(d)  = max{ t | t + 45 days <= d }
This ensures PIT (point-in-time) alignment — at the time of event d the
FY-t annual report has been released (typical publication lag for Taiwan
TWSE is 90 days after fiscal year-end; US Form 10-K is 60-90 days; HKEX
~120 days; 45 days is CONSERVATIVE — most fiscal-year-end-based matches
will use the report from 12+ months earlier, which is safely published).

Source of truth: public 10-K / annual reports via yfinance API.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 5-foundry pool per K1108b convention
POOL = ['2330.TW', '2303.TW', 'TSM', 'GFS', '0981.HK']

# Balance-sheet / income-statement item candidates (yfinance sometimes
# renames these between releases; we try a cascade).
PPE_KEYS = ['Net PPE', 'Property Plant And Equipment Net',
            'Net Property Plant And Equipment']
REVENUE_KEYS = ['Total Revenue', 'Operating Revenue', 'Revenue']
DEBT_KEYS = ['Total Debt', 'Long Term Debt And Capital Lease Obligation',
             'Long Term Debt']
EQUITY_KEYS = ['Stockholders Equity', 'Common Stock Equity',
               'Total Equity Gross Minority Interest']
SGA_KEYS = ['Selling General And Administration',
            'Selling General And Administrative Expense',
            'Operating Expense']  # OpEx as a fallback superset


def _first_available(df, keys, col):
    """Return float value from df[col] using first matching key; nan if none."""
    for k in keys:
        try:
            v = df.loc[k, col]
            if pd.notna(v):
                return float(v)
        except KeyError:
            continue
    return np.nan


def fetch_one(ticker, max_retries=2):
    """Fetch annual balance sheet + income statement for one ticker.
    Returns a dataframe indexed by fiscal-year-end date with cols:
      ppe, revenue, debt, equity, sga, op_leverage_1/2/3.
    """
    print(f"\n>>> Fetching {ticker} ...")
    t = yf.Ticker(ticker)
    bs = None; fs = None
    for attempt in range(max_retries):
        try:
            bs = t.balance_sheet
            fs = t.financials
            if bs is None or len(bs.columns) == 0 or fs is None or len(fs.columns) == 0:
                raise RuntimeError("empty data")
            break
        except Exception as e:
            print(f"   attempt {attempt+1} failed: {e}")
            time.sleep(2.0)

    if bs is None or fs is None or len(bs.columns) == 0:
        print(f"   {ticker}: NO DATA (yfinance empty)")
        return pd.DataFrame()

    # Align columns — intersect BS and IS on fiscal-year-end dates
    common_cols = sorted(set(bs.columns).intersection(fs.columns), reverse=True)
    rows = []
    for col in common_cols:
        fy_end = pd.Timestamp(col).tz_localize(None)
        ppe = _first_available(bs, PPE_KEYS, col)
        rev = _first_available(fs, REVENUE_KEYS, col)
        debt = _first_available(bs, DEBT_KEYS, col)
        equity = _first_available(bs, EQUITY_KEYS, col)
        sga = _first_available(fs, SGA_KEYS, col)

        op_lev_1 = ppe / rev if rev > 0 else np.nan
        op_lev_2 = debt / equity if equity > 0 else np.nan
        op_lev_3 = (ppe + sga) / rev if (rev > 0 and not np.isnan(ppe) and not np.isnan(sga)) else np.nan

        rows.append({
            'ticker': ticker,
            'fy_end': fy_end,
            'ppe': ppe,
            'revenue': rev,
            'debt': debt,
            'equity': equity,
            'sga': sga,
            'op_leverage_1': op_lev_1,   # PPE / Rev
            'op_leverage_2': op_lev_2,   # Debt / Equity
            'op_leverage_3': op_lev_3,   # (PPE + SG&A) / Rev
        })
    df = pd.DataFrame(rows).sort_values('fy_end').reset_index(drop=True)
    print(f"   {ticker}: {len(df)} fiscal years  "
          f"({df['fy_end'].min().date() if len(df) else 'N/A'} → "
          f"{df['fy_end'].max().date() if len(df) else 'N/A'})")
    if len(df):
        print(f"     op_lev_1 (PPE/Rev): "
              f"min={df['op_leverage_1'].min():.3f} max={df['op_leverage_1'].max():.3f} "
              f"mean={df['op_leverage_1'].mean():.3f}")
        print(f"     op_lev_2 (Debt/Eq): "
              f"min={df['op_leverage_2'].min():.3f} max={df['op_leverage_2'].max():.3f} "
              f"mean={df['op_leverage_2'].mean():.3f}")
        print(f"     op_lev_3 ((PPE+SGA)/Rev): "
              f"min={df['op_leverage_3'].min():.3f} max={df['op_leverage_3'].max():.3f} "
              f"mean={df['op_leverage_3'].mean():.3f}")
    return df


def main():
    t0 = time.time()
    print(f"K1108e — fetch op_leverage for 5-foundry pool at {time.strftime('%H:%M:%S')}")
    all_rows = []
    for ticker in POOL:
        df_t = fetch_one(ticker)
        if len(df_t):
            all_rows.append(df_t)
    pool = pd.concat(all_rows, ignore_index=True)
    pool = pool.sort_values(['ticker', 'fy_end']).reset_index(drop=True)
    out_path = SCRIPT_DIR / 'k1108e_opleverage_pool.csv'
    pool.to_csv(out_path, index=False)
    print(f"\n>>> Wrote {out_path}: {len(pool)} firm-year rows for "
          f"{pool['ticker'].nunique()} firms")
    print(f"    Fiscal-year-end span: "
          f"{pool['fy_end'].min().date()} → {pool['fy_end'].max().date()}")
    print(f"    Runtime: {time.time() - t0:.1f}s")
    return pool


if __name__ == '__main__':
    main()
