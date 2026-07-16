"""TSMC 2026 Q2 法說會 T+0 素材：價格 + 期權數據拉取與計算.

研究誠實：所有數字實際下載計算；seed 不涉及（無隨機程序）。
輸出: prices.json (中間數據), 後續 make_figs.py 畫圖, evidence.json 彙整。
"""
import json
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

OUT = "/Users/yhlai0911/volpred-research/storage/drafts/assets/trending_tsmc_call_20260716"

out = {"pulled_at_utc": datetime.now(timezone.utc).isoformat()}

# ---------- 1. daily prices ----------
tsm = yf.download("TSM", start="2026-06-01", auto_adjust=True, progress=False)
twn = yf.download("2330.TW", start="2026-06-01", auto_adjust=True, progress=False)
for df in (tsm, twn):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

tsm.to_csv(f"{OUT}/tsm_daily.csv")
twn.to_csv(f"{OUT}/twn2330_daily.csv")

def series_info(df, name):
    c = df["Close"].dropna()
    r = c.pct_change().dropna()
    return {
        "name": name,
        "first_date": str(c.index[0].date()),
        "last_date": str(c.index[-1].date()),
        "n_days": int(len(c)),
        "last_close": round(float(c.iloc[-1]), 2),
    }

out["tsm_daily"] = series_info(tsm, "TSM ADR")
out["twn_daily"] = series_info(twn, "2330.TW")

# 法說前 5 日累積報酬：TSM 以 7/15 收盤為終點, 起點 = 再往前 5 個交易日
def cum_ret_5d(df, end_date):
    c = df["Close"].dropna()
    c = c[c.index.date <= end_date]
    if len(c) < 6:
        return None
    return float(c.iloc[-1] / c.iloc[-6] - 1)

from datetime import date
tsm_pre5 = cum_ret_5d(tsm, date(2026, 7, 15))
twn_pre5 = cum_ret_5d(twn, date(2026, 7, 15))
out["pre_call_5d_cumret"] = {
    "tsm_through_0715": round(tsm_pre5 * 100, 2) if tsm_pre5 is not None else None,
    "twn2330_through_0715": round(twn_pre5 * 100, 2) if twn_pre5 is not None else None,
    "note": "5 個交易日累積報酬(%), 終點 2026-07-15 收盤",
}

# 2330 今日 (7/16, 盤中皆在 14:00 法說前) 表現
c = twn["Close"].dropna()
if c.index[-1].date() == date(2026, 7, 16) and len(c) >= 2:
    out["twn2330_0716"] = {
        "close": round(float(c.iloc[-1]), 2),
        "pct_change": round(float(c.iloc[-1] / c.iloc[-2] - 1) * 100, 2),
        "note": "台股 13:30 收盤早於 14:00 法說, 此為法說前交易; 真正反應日=7/17",
    }
else:
    out["twn2330_0716"] = {"note": f"yfinance 最後日期 {c.index[-1].date()}, 無 7/16 資料"}

tc = tsm["Close"].dropna()
out["tsm_prev_close_0715"] = (
    round(float(tc.iloc[-1]), 2) if tc.index[-1].date() == date(2026, 7, 15) else
    {"last_date": str(tc.index[-1].date()), "close": round(float(tc.iloc[-1]), 2)}
)

# ---------- 2. TSM 盤前/即時 ----------
t = yf.Ticker("TSM")
try:
    info = t.info
    pre = {k: info.get(k) for k in [
        "preMarketPrice", "preMarketChangePercent", "regularMarketPrice",
        "regularMarketPreviousClose", "marketState",
    ]}
    out["tsm_premarket"] = pre
except Exception as e:  # noqa: BLE001
    out["tsm_premarket"] = {"error": str(e)}

# ---------- 3. TSM options: 最近到期 ATM IV ----------
def atm_iv(ticker, expiry, spot):
    ch = ticker.option_chain(expiry)
    res = {}
    for side, df in (("call", ch.calls), ("put", ch.puts)):
        df = df.dropna(subset=["impliedVolatility", "strike"]).copy()
        df = df[(df["impliedVolatility"] > 0.01) & (df["impliedVolatility"] < 5)]
        if df.empty:
            res[side] = None
            continue
        df["dist"] = (df["strike"] - spot).abs()
        row = df.nsmallest(1, "dist").iloc[0]
        res[side] = {
            "strike": float(row["strike"]),
            "iv": round(float(row["impliedVolatility"]) * 100, 2),
            "lastTradeDate": str(row.get("lastTradeDate", "")),
            "bid": float(row.get("bid", float("nan"))),
            "ask": float(row.get("ask", float("nan"))),
        }
    return res

opt = {"expiries_available": []}
try:
    exps = list(t.options)
    opt["expiries_available"] = exps[:6]
    spot = None
    pm = out.get("tsm_premarket", {})
    spot = pm.get("preMarketPrice") or pm.get("regularMarketPrice")
    if spot is None:
        spot = float(tc.iloc[-1])
    opt["spot_used"] = float(spot)
    for exp in exps[:3]:
        opt[f"atm_{exp}"] = atm_iv(t, exp, float(spot))
except Exception as e:  # noqa: BLE001
    opt["error"] = str(e)
out["tsm_options"] = opt

with open(f"{OUT}/prices.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False, default=str)
print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
