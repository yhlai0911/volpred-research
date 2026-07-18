"""Trending 2026-07-18: Big Tech capex vs 費半(SOX) 波動率 + VIX 對沖 evidence package.
只做 descriptive + realized-vol + correlation + hedge-cost，皆 primary source(yfinance/FRED-free)。
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf

OUT = "experiments/trending_20260718_sox_capex/evidence.json"
END = "2026-07-18"
START = "2025-01-01"

# 費半 proxy: ^SOX (Philadelphia Semiconductor), SMH ETF
# hyperscaler capex 主力: MSFT GOOGL AMZN META
# 半導體成分代表: NVDA AVGO AMD TSM MU
tickers = ["^SOX", "SMH", "^VIX", "^GSPC", "NVDA", "AVGO", "AMD", "TSM", "MU",
           "MSFT", "GOOGL", "AMZN", "META"]

raw = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)
px = raw["Close"].dropna(how="all")
px = px.ffill()

ret = np.log(px / px.shift(1)).dropna()

def ann_vol(series, window):
    return series.rolling(window).std() * np.sqrt(252) * 100

res = {"as_of": END, "data_last_date": str(px.index[-1].date()), "n_obs": len(px)}

# --- 1. SOX / SMH July pullback ---
def pullback(sym):
    s = px[sym].dropna()
    # July high vs latest
    jul = s[s.index >= "2026-07-01"]
    recent = s[s.index >= "2026-06-15"]
    peak = recent.max()
    peak_date = str(recent.idxmax().date())
    last = s.iloc[-1]
    return {
        "sym": sym,
        "recent_peak": round(float(peak), 2),
        "peak_date": peak_date,
        "last": round(float(last), 2),
        "last_date": str(s.index[-1].date()),
        "drawdown_from_peak_pct": round(float((last / peak - 1) * 100), 2),
        "mtd_pct": round(float((last / jul.iloc[0] - 1) * 100), 2) if len(jul) else None,
    }

res["pullback"] = {sym: pullback(sym) for sym in ["^SOX", "SMH", "^GSPC"]}

# --- 2. Realized vol: pre-pullback vs current ---
rv20 = {}
for sym in ["^SOX", "SMH", "NVDA", "AVGO", "AMD", "TSM", "MU"]:
    v = ann_vol(ret[sym], 20)
    # 一個月前(6/15前後) vs 最新
    cur = float(v.iloc[-1])
    prev = float(v[v.index <= "2026-06-16"].iloc[-1])
    rv20[sym] = {
        "rv20_now_pct": round(cur, 1),
        "rv20_mid_june_pct": round(prev, 1),
        "delta_pct_pts": round(cur - prev, 1),
        "ratio": round(cur / prev, 2),
    }
res["realized_vol_20d"] = rv20

# --- 3. VIX level & regime ---
vix = px["^VIX"].dropna()
res["vix"] = {
    "last": round(float(vix.iloc[-1]), 2),
    "mid_june": round(float(vix[vix.index <= "2026-06-16"].iloc[-1]), 2),
    "ytd_mean": round(float(vix[vix.index >= "2026-01-01"].mean()), 2),
    "ytd_pctile_of_last": round(float((vix[vix.index >= "2026-01-01"] <= vix.iloc[-1]).mean() * 100), 1),
}

# --- 4. Correlation: hyperscaler capex-heavy names vs SOX (rolling + full) ---
# proxy for "capex sentiment" = equal-weight return of MSFT GOOGL AMZN META
hyper = ret[["MSFT", "GOOGL", "AMZN", "META"]].mean(axis=1)
sox = ret["^SOX"]
smh = ret["SMH"]
joined = pd.concat([hyper.rename("hyper"), sox.rename("sox"), smh.rename("smh"),
                    ret["^VIX"].rename("vix")], axis=1).dropna()
# last 60d and last 120d correlations
def corr(a, b, n):
    sub = joined.tail(n)
    return round(float(sub[a].corr(sub[b])), 2)
res["correlation"] = {
    "hyper_vs_sox_60d": corr("hyper", "sox", 60),
    "hyper_vs_sox_120d": corr("hyper", "sox", 120),
    "sox_vs_vix_60d": corr("sox", "vix", 60),
    "smh_vs_vix_60d": corr("smh", "vix", 60),
    "hyper_vs_vix_60d": corr("hyper", "vix", 60),
}

# --- 5. VIX-hedge: beta of SMH daily return to VIX daily change (down-capture) ---
d = joined.tail(120).copy()
d["dvix"] = px["^VIX"].reindex(joined.index).diff().tail(120)
d = d.dropna()
# regress smh ret on dvix
X = np.vstack([np.ones(len(d)), d["dvix"].values]).T
beta = np.linalg.lstsq(X, d["smh"].values, rcond=None)[0]
res["vix_hedge"] = {
    "smh_ret_on_dvix_beta": round(float(beta[1]), 4),
    "interpretation": "SMH 單日報酬對 VIX 單日變動(點)的敏感度",
    "n": int(len(d)),
    # down-day capture: on days SMH<0, avg VIX change
    "avg_dvix_on_smh_down_days": round(float(d.loc[d["smh"] < 0, "dvix"].mean()), 3),
}

with open(OUT, "w") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
print(json.dumps(res, ensure_ascii=False, indent=2))
