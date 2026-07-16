"""TSM 期權：用 7/15 收盤最後成交價自行反推 BS 隱含波動率.

盤前 yfinance 的 impliedVolatility 欄位是壞的 (bid/ask=0, IV 3%)，
改用 lastPrice(7/15 成交) + spot=7/15 收盤 419.48 反推 IV。
含 7/17 到期 ATM straddle 隱含 move。無隨機程序。
"""
import json
from datetime import datetime, timezone
from math import erf, exp, log, sqrt

import pandas as pd
import yfinance as yf

OUT = "/Users/yhlai0911/volpred-research/storage/drafts/assets/trending_tsmc_call_20260716"
SPOT = 419.48          # TSM 2026-07-15 收盤 (auto-adjusted, yfinance)
R = 0.04               # 無風險利率近似
NOW = datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc)  # 定價時點=7/15 收盤(美東16:00; tz僅記號)

def norm_cdf(x):
    return 0.5 * (1 + erf(x / sqrt(2)))

def bs_price(S, K, T, sigma, r, kind):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if kind == "c" else (K - S))
    d1 = (log(S / K) + (r + sigma**2 / 2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if kind == "c":
        return S * norm_cdf(d1) - K * exp(-r * T) * norm_cdf(d2)
    return K * exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

def implied_vol(price, S, K, T, r, kind):
    lo, hi = 0.01, 4.0
    if not (bs_price(S, K, T, lo, r, kind) <= price <= bs_price(S, K, T, hi, r, kind)):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, mid, r, kind) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

t = yf.Ticker("TSM")
res = {"method": "BS bisection on 7/15 lastPrice, spot=419.48, r=4%",
       "computed_at_utc": datetime.now(timezone.utc).isoformat()}

for exp_s, label in [("2026-07-17", "front_incl_earnings_aftermath"),
                     ("2026-07-24", "next_week"),
                     ("2026-08-21", "monthly_aug")]:
    ch = t.option_chain(exp_s)
    expiry = datetime.strptime(exp_s, "%Y-%m-%d").replace(hour=20, tzinfo=timezone.utc)
    T = max((expiry - NOW).total_seconds(), 0) / (365.0 * 86400)
    entry = {"expiry": exp_s, "T_years": round(T, 5), "strikes": {}}
    for side, df, kind in (("call", ch.calls, "c"), ("put", ch.puts, "p")):
        df = df.dropna(subset=["lastPrice", "strike"]).copy()
        # 只用 7/15 當天有成交的合約
        df["lastTradeDate"] = pd.to_datetime(df["lastTradeDate"], utc=True)
        df = df[df["lastTradeDate"].dt.date == pd.Timestamp("2026-07-15").date()]
        df["dist"] = (df["strike"] - SPOT).abs()
        df = df.nsmallest(3, "dist").sort_values("strike")
        rows = []
        for _, r_ in df.iterrows():
            iv = implied_vol(float(r_["lastPrice"]), SPOT, float(r_["strike"]), T, R, kind)
            rows.append({
                "strike": float(r_["strike"]),
                "lastPrice": float(r_["lastPrice"]),
                "lastTrade": str(r_["lastTradeDate"]),
                "volume": None if pd.isna(r_.get("volume")) else int(r_["volume"]),
                "bs_iv_pct": None if iv is None else round(iv * 100, 2),
            })
        entry["strikes"][side] = rows
    # ATM straddle 隱含 move: 用最接近 SPOT 的同一 strike call+put
    try:
        cs = {r_["strike"]: r_ for r_ in entry["strikes"]["call"]}
        ps = {r_["strike"]: r_ for r_ in entry["strikes"]["put"]}
        common = sorted(set(cs) & set(ps), key=lambda k: abs(k - SPOT))
        if common:
            k = common[0]
            strad = cs[k]["lastPrice"] + ps[k]["lastPrice"]
            entry["atm_straddle"] = {
                "strike": k,
                "price": round(strad, 2),
                "implied_move_pct_of_spot": round(strad / SPOT * 100, 2),
            }
    except Exception as e:  # noqa: BLE001
        entry["straddle_error"] = str(e)
    res[label] = entry

# TSM 20 日已實現波動率 (至 7/15)
import numpy as np
px = pd.read_csv(f"{OUT}/tsm_daily.csv", index_col=0, parse_dates=True)["Close"].dropna()
lr = np.log(px / px.shift(1)).dropna()
res["tsm_realized_vol"] = {
    "rv20_annualized_pct": round(float(lr.tail(20).std(ddof=1) * np.sqrt(252) * 100), 1),
    "rv5_annualized_pct": round(float(lr.tail(5).std(ddof=1) * np.sqrt(252) * 100), 1),
    "window_end": str(px.index[-1].date()),
}

with open(f"{OUT}/options_iv.json", "w") as f:
    json.dump(res, f, indent=2, ensure_ascii=False)
print(json.dumps(res, indent=2, ensure_ascii=False))
