"""Quick staleness diagnostic probe for k1619 asset selection.

Fetches hourly bars (period=730d) for a liquid benchmark + candidate illiquid
ETFs, computes the fraction of exact-zero and near-zero hourly close-to-close
log returns (Bandi-Pirino-Reno idle-time proxy), and the number of usable
trading days. Used only to SELECT the 3 illiquid assets; not part of the final
result. Reproducible: no randomness.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import yfinance as yf

CANDIDATES = [
    "SPY",   # liquid benchmark
    "EWZ",   # Brazil
    "THD",   # Thailand
    "EPHE",  # Philippines
    "FM",    # Frontier Markets
    "EPU",   # Peru
    "NGE",   # Nigeria
    "ARGT",  # Argentina
    "EIS",   # Israel
    "PAK",   # Pakistan
    "VNM",   # Vietnam
    "FRN",   # Frontier 100
    "GXG",   # Colombia
    "EWM",   # Malaysia
    "TUR",   # Turkey
]

NEAR_ZERO_EPS = 1e-4  # 1 bp

def analyze(sym: str) -> dict | None:
    try:
        df = yf.download(sym, period="730d", interval="1h",
                         auto_adjust=True, progress=False, threads=False)
    except Exception as e:  # noqa: BLE001
        print(f"{sym}: download error {e}")
        return None
    if df is None or len(df) == 0:
        print(f"{sym}: empty")
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].dropna()
    if len(close) < 50:
        print(f"{sym}: too few bars {len(close)}")
        return None
    idx = close.index
    day = idx.normalize()
    logret = np.log(close / close.shift(1))
    # within-day returns only (drop first bar of each day = overnight gap)
    same_day = (day == day.to_series().shift(1).values)
    r = logret[same_day].dropna()
    day_of_r = r.index.normalize()
    n = len(r)
    zero_frac = float((r == 0).mean())
    nearzero_frac = float((r.abs() < NEAR_ZERO_EPS).mean())
    n_days = int(pd.Series(day_of_r).nunique())
    bars_per_day = n / max(n_days, 1)
    return {
        "symbol": sym,
        "n_intraday_returns": n,
        "n_days": n_days,
        "bars_per_day": round(bars_per_day, 2),
        "zero_return_frac": round(zero_frac, 5),
        "nearzero_return_frac": round(nearzero_frac, 5),
        "first": str(idx.min().date()),
        "last": str(idx.max().date()),
    }

if __name__ == "__main__":
    rows = []
    for s in CANDIDATES:
        res = analyze(s)
        if res:
            rows.append(res)
            print(res)
    out = pd.DataFrame(rows).sort_values("zero_return_frac", ascending=False)
    print("\n=== SORTED BY ZERO-RETURN FRACTION (staleness) ===")
    print(out.to_string(index=False))
