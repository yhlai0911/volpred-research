"""
K: trending_mag7_skew_capex_crosssection_20260705
Task: trending_repost evidence package

Cross-sectional snapshot (2026-07-05) across Mag 7 (AAPL, MSFT, GOOGL, AMZN,
META, NVDA, TSLA):
  1. Current option-implied put-call skew (~10% OTM proxy, per
     .claude/skills/trending-repost brief's explicit fallback rule)
  2. ATM IV vs 30d realized vol (IV-RV gap)
  3. TTM capex / TTM revenue ratio ("capex intensity")
  4. Cross-sectional rank correlation: does higher capex intensity track
     with a steeper (more expensive) downside put skew right now?

All data pulled live from yfinance. This is a descriptive cross-section
snapshot with n=7 -- NOT a hypothesis test. No p-value / significance claim
is made anywhere in the writeup; Spearman rho is reported purely descriptively.

Data source: yfinance (Yahoo Finance), pulled 2026-07-05 (Taipei time).
"""
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import spearmanr

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]

RUN_TS = datetime.now(timezone.utc).isoformat()


def nearest_expiry(expiries, target_days=(30, 45)):
    """Pick the expiry whose day-count falls in [target_days[0], target_days[1]]
    if possible; else the closest one to the midpoint of the target range."""
    today = pd.Timestamp.now(tz="UTC").normalize()
    candidates = []
    for e in expiries:
        d = (pd.Timestamp(e, tz="UTC") - today).days
        candidates.append((e, d))
    in_range = [c for c in candidates if target_days[0] <= c[1] <= target_days[1]]
    if in_range:
        # prefer the one closest to 37 (midpoint)
        return min(in_range, key=lambda c: abs(c[1] - 37))
    # fallback: closest to midpoint overall (must be > 5 days out to avoid weeklies noise)
    valid = [c for c in candidates if c[1] > 5]
    if not valid:
        return candidates[0]
    return min(valid, key=lambda c: abs(c[1] - 37))


def strike_near(chain_df, target_strike):
    if chain_df.empty:
        return None
    idx = (chain_df["strike"] - target_strike).abs().idxmin()
    return chain_df.loc[idx]


def realized_vol_30d(price_hist):
    close = price_hist["Close"].dropna()
    log_ret = np.log(close / close.shift(1)).dropna()
    last30 = log_ret.tail(30)
    if len(last30) < 15:
        return None
    return float(last30.std() * math.sqrt(252) * 100)


def ttm_capex_revenue(tk):
    """Trailing-twelve-month capex and revenue from quarterly statements."""
    try:
        qcf = tk.quarterly_cashflow
        qis = tk.quarterly_financials
    except Exception:
        return None, None, None, None

    capex_row = None
    for label in ["Capital Expenditure", "Capital Expenditures", "PurchaseOfPPE"]:
        if qcf is not None and label in qcf.index:
            capex_row = qcf.loc[label]
            break
    revenue_row = None
    for label in ["Total Revenue", "TotalRevenue"]:
        if qis is not None and label in qis.index:
            revenue_row = qis.loc[label]
            break

    if capex_row is None or revenue_row is None:
        return None, None, None, None

    capex_ttm = float(capex_row.iloc[:4].sum())
    revenue_ttm = float(revenue_row.iloc[:4].sum())
    capex_period_start = str(capex_row.index[3].date()) if len(capex_row) >= 4 else None
    capex_period_end = str(capex_row.index[0].date()) if len(capex_row) >= 1 else None
    return abs(capex_ttm), revenue_ttm, capex_period_start, capex_period_end


def main():
    rows = []
    for sym in TICKERS:
        print(f"=== {sym} ===")
        tk = yf.Ticker(sym)
        hist = tk.history(period="6mo", interval="1d", auto_adjust=True)
        if hist.empty:
            print(f"  no price history, skip")
            continue
        spot = float(hist["Close"].iloc[-1])
        rv30 = realized_vol_30d(hist)
        close = hist["Close"].dropna()
        ret_90d = float((close.iloc[-1] / close.iloc[-63] - 1) * 100) if len(close) >= 63 else None

        expiries = tk.options
        if not expiries:
            print(f"  no options, skip")
            continue
        expiry, dte = nearest_expiry(expiries)
        chain = tk.option_chain(expiry)
        calls, puts = chain.calls, chain.puts

        atm_call = strike_near(calls, spot)
        atm_put = strike_near(puts, spot)
        atm_iv = None
        if atm_call is not None and atm_put is not None:
            atm_iv = float((atm_call["impliedVolatility"] + atm_put["impliedVolatility"]) / 2 * 100)

        put_otm = strike_near(puts, spot * 0.90)
        call_otm = strike_near(calls, spot * 1.10)
        put_iv_otm = float(put_otm["impliedVolatility"] * 100) if put_otm is not None else None
        call_iv_otm = float(call_otm["impliedVolatility"] * 100) if call_otm is not None else None
        skew_10pct = (put_iv_otm - call_iv_otm) if (put_iv_otm is not None and call_iv_otm is not None) else None

        capex_ttm, revenue_ttm, capex_start, capex_end = ttm_capex_revenue(tk)
        capex_ratio = (capex_ttm / revenue_ttm * 100) if (capex_ttm and revenue_ttm) else None

        row = {
            "ticker": sym,
            "spot": round(spot, 2),
            "expiry": expiry,
            "dte": dte,
            "atm_iv_pct": round(atm_iv, 1) if atm_iv is not None else None,
            "put_strike_90pct": round(spot * 0.90, 1),
            "call_strike_110pct": round(spot * 1.10, 1),
            "put_iv_10otm_pct": round(put_iv_otm, 1) if put_iv_otm is not None else None,
            "call_iv_10otm_pct": round(call_iv_otm, 1) if call_iv_otm is not None else None,
            "skew_10pct_otm_pp": round(skew_10pct, 1) if skew_10pct is not None else None,
            "rv30_annualized_pct": round(rv30, 1) if rv30 is not None else None,
            "iv_rv_gap_pp": round(atm_iv - rv30, 1) if (atm_iv is not None and rv30 is not None) else None,
            "capex_ttm_usd_b": round(capex_ttm / 1e9, 1) if capex_ttm else None,
            "revenue_ttm_usd_b": round(revenue_ttm / 1e9, 1) if revenue_ttm else None,
            "capex_intensity_pct": round(capex_ratio, 1) if capex_ratio is not None else None,
            "capex_period_start": capex_start,
            "capex_period_end": capex_end,
            "return_90d_pct": round(ret_90d, 1) if ret_90d is not None else None,
        }
        print(json.dumps(row, indent=2, ensure_ascii=False))
        rows.append(row)

    df = pd.DataFrame(rows)

    # Cross-sectional rank correlation: capex intensity vs skew, n=7 (or fewer if any NaN)
    valid = df.dropna(subset=["capex_intensity_pct", "skew_10pct_otm_pp"])
    rho_skew, p_skew = (None, None)
    rho_gap, p_gap = (None, None)
    if len(valid) >= 4:
        rho_skew, p_skew = spearmanr(valid["capex_intensity_pct"], valid["skew_10pct_otm_pp"])
    valid_gap = df.dropna(subset=["capex_intensity_pct", "iv_rv_gap_pp"])
    if len(valid_gap) >= 4:
        rho_gap, p_gap = spearmanr(valid_gap["capex_intensity_pct"], valid_gap["iv_rv_gap_pp"])

    rho_mom, p_mom = (None, None)
    valid_mom = df.dropna(subset=["return_90d_pct", "skew_10pct_otm_pp"])
    if len(valid_mom) >= 4:
        rho_mom, p_mom = spearmanr(valid_mom["return_90d_pct"], valid_mom["skew_10pct_otm_pp"])

    results = {
        "run_timestamp_utc": RUN_TS,
        "data_source": "yfinance (Yahoo Finance), live pull",
        "as_of_note": "Spot/IV/option-chain data reflects live yfinance pull at run time; capex/revenue reflect latest available quarterly filings as of run date.",
        "tickers": TICKERS,
        "n": len(df),
        "cross_section": df.to_dict(orient="records"),
        "spearman_capex_vs_skew": {
            "rho": round(float(rho_skew), 3) if rho_skew is not None else None,
            "p_value": round(float(p_skew), 3) if p_skew is not None else None,
            "n": int(len(valid)),
            "note": "n=7 (or fewer after NaN drop) -- descriptive cross-section only, NOT a statistically powered hypothesis test. No causal or significance claim.",
        },
        "spearman_capex_vs_iv_rv_gap": {
            "rho": round(float(rho_gap), 3) if rho_gap is not None else None,
            "p_value": round(float(p_gap), 3) if p_gap is not None else None,
            "n": int(len(valid_gap)),
            "note": "Same n-limitation caveat as above.",
        },
        "spearman_momentum_vs_skew": {
            "rho": round(float(rho_mom), 3) if rho_mom is not None else None,
            "p_value": round(float(p_mom), 3) if p_mom is not None else None,
            "n": int(len(valid_mom)),
            "note": "90d price return vs skew, same n-limitation caveat.",
        },
    }

    with open("experiments/trending_mag7_skew_capex_crosssection_20260705/results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    df.to_csv("experiments/trending_mag7_skew_capex_crosssection_20260705/cross_section.csv", index=False)
    print("\n=== Saved results.json + cross_section.csv ===")
    print(df.to_string())
    print("\nSpearman capex_intensity vs skew_10pct_otm:", results["spearman_capex_vs_skew"])
    print("Spearman capex_intensity vs iv_rv_gap:", results["spearman_capex_vs_iv_rv_gap"])


if __name__ == "__main__":
    main()
