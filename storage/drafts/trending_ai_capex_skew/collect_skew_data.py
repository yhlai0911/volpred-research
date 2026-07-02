"""
Trending repost evidence package: mega-cap crowded-trade tail-risk pricing
via implied-vol skew + put/call ratio.

Data source: yfinance option chains + price history (public, verifiable).
Date: 2026-07-03. No random process (no seed needed).

For each ticker computes (nearest monthly expiry ~30 DTE):
  - spot
  - ATM implied vol (IV interpolated at moneyness=1.0)
  - moneyness-based skew = IV(90% put) - IV(110% call)   [transparent proxy for 25d RR]
  - put/call open-interest ratio
  - put/call volume ratio
  - RV20 (20-day close-to-close realized vol, annualized)
  - IV-RV gap = ATM_IV - RV20
"""
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

TICKERS = ["NVDA", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA", "QQQ", "SPY"]
TARGET_DTE = 30


def annualized_rv20(hist: pd.DataFrame) -> float:
    close = hist["Close"].dropna()
    if len(close) < 21:
        return float("nan")
    logret = np.log(close / close.shift(1)).dropna()
    rv = logret.tail(20).std(ddof=1) * math.sqrt(252)
    return float(rv)


def interp_iv_at_moneyness(df: pd.DataFrame, spot: float, target_m: float) -> float:
    """Interpolate impliedVolatility at target moneyness (strike/spot)."""
    d = df[["strike", "impliedVolatility"]].dropna()
    d = d[(d["impliedVolatility"] > 0.01) & (d["impliedVolatility"] < 5.0)]
    if d.empty:
        return float("nan")
    d = d.assign(m=d["strike"] / spot).sort_values("m")
    m = d["m"].values
    iv = d["impliedVolatility"].values
    if target_m <= m[0]:
        return float(iv[0])
    if target_m >= m[-1]:
        return float(iv[-1])
    return float(np.interp(target_m, m, iv))


def nearest_expiry(tk: yf.Ticker) -> str:
    exps = tk.options
    if not exps:
        return None
    today = datetime.now(timezone.utc).date()
    best, best_gap = None, 1e9
    for e in exps:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (d - today).days
        if dte < 7:  # skip near-dated noise
            continue
        gap = abs(dte - TARGET_DTE)
        if gap < best_gap:
            best, best_gap = e, gap
    return best


def collect(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    hist = tk.history(period="3mo")
    spot = float(hist["Close"].dropna().iloc[-1])
    rv20 = annualized_rv20(hist)

    exp = nearest_expiry(tk)
    if exp is None:
        raise RuntimeError(f"no usable expiry for {ticker}")
    today = datetime.now(timezone.utc).date()
    dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days

    chain = tk.option_chain(exp)
    calls, puts = chain.calls, chain.puts

    atm_iv = np.nanmean([
        interp_iv_at_moneyness(calls, spot, 1.0),
        interp_iv_at_moneyness(puts, spot, 1.0),
    ])
    put_iv_90 = interp_iv_at_moneyness(puts, spot, 0.90)
    call_iv_110 = interp_iv_at_moneyness(calls, spot, 1.10)
    skew = put_iv_90 - call_iv_110

    put_oi = float(puts["openInterest"].fillna(0).sum())
    call_oi = float(calls["openInterest"].fillna(0).sum())
    put_vol = float(puts["volume"].fillna(0).sum())
    call_vol = float(calls["volume"].fillna(0).sum())

    return {
        "ticker": ticker,
        "spot": round(spot, 2),
        "expiry": exp,
        "dte": dte,
        "atm_iv": round(float(atm_iv), 4),
        "put_iv_90": round(float(put_iv_90), 4),
        "call_iv_110": round(float(call_iv_110), 4),
        "skew_90_110": round(float(skew), 4),
        "put_call_oi_ratio": round(put_oi / call_oi, 3) if call_oi else None,
        "put_call_vol_ratio": round(put_vol / call_vol, 3) if call_vol else None,
        "rv20": round(rv20, 4),
        "iv_rv_gap": round(float(atm_iv) - rv20, 4),
    }


def main():
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "target_dte": TARGET_DTE, "results": [], "errors": {}}
    for t in TICKERS:
        try:
            r = collect(t)
            out["results"].append(r)
            print(f"OK  {t}: spot={r['spot']} ATM_IV={r['atm_iv']:.1%} "
                  f"skew={r['skew_90_110']:+.1%} P/C_OI={r['put_call_oi_ratio']} "
                  f"IV-RV={r['iv_rv_gap']:+.1%}")
        except Exception as e:  # noqa
            out["errors"][t] = str(e)
            print(f"ERR {t}: {e}")

    path = "storage/drafts/trending_ai_capex_skew/skew_results.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {path}  ({len(out['results'])} ok, {len(out['errors'])} err)")


if __name__ == "__main__":
    main()
