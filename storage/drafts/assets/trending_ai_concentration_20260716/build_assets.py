"""
AI 溢價下的極端權重集中與尾部風險 — 素材計算腳本
輸出: storage/drafts/assets/trending_ai_concentration_20260716/
  - evidence.json
  - fig1_concentration_volgap.png (集中度 + 個股-指數波動缺口時序)
  - fig2_hedge_cost.png (裸 put vs put spread 避險成本)

方法摘要 (誠實原則, 全部記入 evidence.json):
- 前五大成分 (2026-07-16, Yahoo Finance funds_data.top_holdings):
  NVDA 7.4997%, AAPL 6.5769%, MSFT 4.2882%, AMZN 3.6106%, GOOGL 3.2429% (+GOOG 2.5845%)
  以「公司」計前五大 = NVDA, AAPL, Alphabet(A+C), MSFT, AMZN, 合計 27.8028%
- 權重時序近似: W5(t) = TOP5總市值(t) / (K * ^GSPC(t))
  市值 = 未調整收盤價 * 流通股數(get_shares_full, 前向填補)
  K 以最新交易日校準, 使 W5(latest) = 官方 27.8028%
  假設: S&P 500 divisor 在樣本期近似常數 (實際會隨買回/成分變動漂移, 記 caveat)
- 波動缺口: 20 日已實現波動 (log return, 年化 sqrt(252)), 個股平均(5 家, Alphabet 用 GOOGL)
  減 SPY 指數波動
- 避險成本: SPY option chain 最近月與次月月度到期,
  5% OTM put (strike ~= 0.95*spot) 與 5%/10% put spread (buy 95%, sell 90%)
  premium 用 bid/ask mid (無報價 fallback lastPrice), 年化 = premium/spot * 365/DTE
"""
import json, time, sys
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

np.random.seed(42)  # 本腳本無隨機程序, 仍依規定固定 seed

OUT = Path("/Users/yhlai0911/volpred-research/storage/drafts/assets/trending_ai_concentration_20260716")
OUT.mkdir(parents=True, exist_ok=True)

TODAY = "2026-07-16"
START = "2020-01-01"
TOP5_TICKERS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"]      # 波動計算用 (Alphabet 用 GOOGL)
CAP_TICKERS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG"]  # 市值合計用 (A+C 都算)
OFFICIAL_W5 = 0.074997 + 0.065769 + 0.042882 + 0.036106 + 0.032429 + 0.025845  # 0.278028

def retry(fn, n=4, wait=8, label=""):
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            last = e
            print(f"[retry] {label} attempt {i+1} failed: {type(e).__name__} {str(e)[:100]}", flush=True)
            time.sleep(wait)
    raise last

# ---------- 1. 價格資料 ----------
all_tickers = ["SPY", "QQQ", "^GSPC"] + CAP_TICKERS
print("downloading prices...", flush=True)
px = retry(lambda: yf.download(all_tickers, start=START, end="2026-07-17",
                               auto_adjust=False, progress=False, threads=False),
           label="prices")
close = px["Close"].dropna(how="all")
adj = px["Adj Close"].dropna(how="all")
# 個別 ticker 失敗時補抓
for tk in all_tickers:
    if tk not in close.columns or close[tk].dropna().empty:
        print(f"re-downloading {tk} individually...", flush=True)
        one = retry(lambda tk=tk: yf.download(tk, start=START, end="2026-07-17",
                                              auto_adjust=False, progress=False, threads=False),
                    label=f"price {tk}")
        c1 = one["Close"];  a1 = one["Adj Close"]
        if isinstance(c1, pd.DataFrame): c1 = c1.iloc[:, 0]
        if isinstance(a1, pd.DataFrame): a1 = a1.iloc[:, 0]
        if c1.dropna().empty:
            raise RuntimeError(f"{tk} price still empty after retries")
        close[tk] = c1.reindex(close.index)
        adj[tk] = a1.reindex(adj.index)
print("price rows:", len(close), "last date:", close.index[-1], flush=True)

# ---------- 2. 流通股數歷史 ----------
shares = {}
for tk in CAP_TICKERS:
    def _get(tk=tk):
        s = yf.Ticker(tk).get_shares_full(start=START)
        if s is None or len(s) == 0:
            raise RuntimeError("empty shares")
        s = s[~s.index.duplicated(keep="last")]
        s.index = s.index.tz_localize(None).normalize()
        s = s[~s.index.duplicated(keep="last")]
        return s
    shares[tk] = retry(_get, label=f"shares {tk}")
    print(f"shares {tk}: {len(shares[tk])} obs, {shares[tk].index[0].date()} ~ {shares[tk].index[-1].date()}", flush=True)

# 分割基準統一: yfinance Close 是分割調整價(今日基準), get_shares_full 是當時申報股數(當時基準)
# -> 股數須乘上「t 之後所有分割倍率」換算到今日基準, 否則 NVDA(40x)/AMZN(20x)/GOOGL(20x) 市值嚴重低估
split_factors = {}
split_jump_dates = {}
cap = pd.DataFrame(index=close.index)
for tk in CAP_TICKERS:
    sp = retry(lambda tk=tk: yf.Ticker(tk).splits, label=f"splits {tk}")
    sp = sp[sp.index.tz_localize(None) >= pd.Timestamp(START)]
    sp.index = sp.index.tz_localize(None).normalize()
    split_factors[tk] = {str(k.date()): float(v) for k, v in sp.items()}
    # 申報股數轉今日分割基準: 切點用「股數序列實際跳升日」而非除權日
    # (AAPL 4:1 除權 2020-08-31, 但申報股數 2020-10-22 才跳升 -> 用除權日會產生 7 週 4x 低估窗口)
    s_rep = shares[tk].sort_index().astype(float)
    adj_s = s_rep.copy()
    split_jump_dates[tk] = {}
    for exd, ratio in sp.items():
        win = s_rep.loc[exd - pd.Timedelta(days=45): exd + pd.Timedelta(days=300)]
        jump_date = None
        prev = None
        for dt, v in win.items():
            if prev is not None and prev > 0 and v / prev > ratio * 0.6:
                jump_date = dt
                break
            prev = v
        if jump_date is None:
            jump_date = exd  # fallback
        split_jump_dates[tk][str(exd.date())] = str(jump_date.date())
        adj_s.loc[adj_s.index < jump_date] *= ratio
    s = adj_s.reindex(close.index.union(adj_s.index)).ffill().reindex(close.index)
    cap[tk] = close[tk] * s
cap = cap.dropna()
print("splits applied:", {k: v for k, v in split_factors.items() if v}, flush=True)
print("shares jump dates:", split_jump_dates, flush=True)
top5cap = cap.sum(axis=1)

# ---------- 3. 權重近似時序 ----------
gspc = close["^GSPC"].reindex(top5cap.index).ffill()
latest = top5cap.index[-1]
K = top5cap.loc[latest] / (OFFICIAL_W5 * gspc.loc[latest])
w5 = top5cap / (K * gspc)
print(f"calibration date {latest.date()}, K={K:.4e}, w5 range {w5.min():.4f} ~ {w5.max():.4f}", flush=True)

# ---------- 4. 波動缺口 ----------
logret = np.log(adj / adj.shift(1))
rv = logret.rolling(20).std() * np.sqrt(252) * 100  # %
idx_vol = rv["SPY"]
qqq_vol = rv["QQQ"]
stock_avg_vol = rv[TOP5_TICKERS].mean(axis=1)
vol_gap = (stock_avg_vol - idx_vol).dropna()

# ---------- 5. 避險成本 (SPY options) ----------
tk_spy = yf.Ticker("SPY")
spot = float(close["SPY"].iloc[-1])
spot_date = str(close.index[-1].date())
exps = retry(lambda: tk_spy.options, label="expirations")
exps = pd.to_datetime(list(exps))
today = pd.Timestamp(TODAY)
# 月度到期 = 每月第三個星期五附近; 取「該月 15~21 日的星期五」為 monthly
monthly = [e for e in exps if e.weekday() == 4 and 15 <= e.day <= 21 and (e - today).days >= 7]
front, back = monthly[0], monthly[1]
print("monthly expiries chosen:", front.date(), back.date(), flush=True)

def put_cost(exp_ts):
    exp_str = exp_ts.strftime("%Y-%m-%d")
    chain = retry(lambda: tk_spy.option_chain(exp_str), label=f"chain {exp_str}")
    puts = chain.puts.copy()
    dte = (exp_ts - today).days
    out = {"expiry": exp_str, "dte": int(dte)}
    for tag, m in [("p95", 0.95), ("p90", 0.90)]:
        target = m * spot
        row = puts.iloc[(puts["strike"] - target).abs().argsort().iloc[0]]
        bid, ask, last = float(row["bid"]), float(row["ask"]), float(row["lastPrice"])
        if bid > 0 and ask > 0:
            prem, src = (bid + ask) / 2, "bid_ask_mid"
        else:
            prem, src = last, "lastPrice"
        out[tag] = {
            "strike": float(row["strike"]), "moneyness_pct": round(float(row["strike"]) / spot * 100, 2),
            "bid": bid, "ask": ask, "lastPrice": last, "premium_used": round(prem, 4),
            "premium_source": src, "impliedVolatility": round(float(row["impliedVolatility"]), 4),
            "openInterest": int(row["openInterest"]) if pd.notna(row["openInterest"]) else None,
            "lastTradeDate": str(row["lastTradeDate"]),
        }
    p95, p90 = out["p95"]["premium_used"], out["p90"]["premium_used"]
    ann = 365.0 / dte
    out["naked_put_cost_pct_of_spot"] = round(p95 / spot * 100, 4)
    out["naked_put_annualized_pct"] = round(p95 / spot * 100 * ann, 3)
    out["spread_cost"] = round(p95 - p90, 4)
    out["spread_cost_pct_of_spot"] = round((p95 - p90) / spot * 100, 4)
    out["spread_annualized_pct"] = round((p95 - p90) / spot * 100 * ann, 3)
    out["cost_saving_pct"] = round((1 - (p95 - p90) / p95) * 100, 2)
    # spread 最大保護 = 5% 寬 (95%~90%), 扣成本後淨最大理賠
    out["spread_max_payoff_pct_of_spot"] = round((out["p95"]["strike"] - out["p90"]["strike"]) / spot * 100, 2)
    return out

front_res = put_cost(front)
back_res = put_cost(back)

# ---------- 6. 序列化 ----------
def ser(s, r=4):
    s = s.dropna()
    return {str(k.date()): round(float(v), r) for k, v in s.items()}

# 月末取樣以縮小 JSON (完整日資料存 csv)
w5_m = w5.resample("ME").last()
volgap_m = vol_gap.resample("ME").last()
pd.DataFrame({"w5_approx": w5, "spy_rv20": idx_vol, "qqq_rv20": qqq_vol,
              "top5_avg_rv20": stock_avg_vol, "vol_gap": stock_avg_vol - idx_vol}
             ).to_csv(OUT / "daily_series.csv")

evidence = {
    "prepared_at_taipei": time.strftime("%Y-%m-%d %H:%M:%S"),
    "topic": "AI 溢價下的極端權重集中與尾部風險",
    "data_sources": {
        "prices": f"yfinance daily OHLCV, {START} ~ {spot_date}, auto_adjust=False; 波動用 Adj Close, 市值用未調整 Close",
        "shares_outstanding": "yfinance Ticker.get_shares_full(start=2020-01-01), 前向填補到交易日",
        "official_weights": "Yahoo Finance SPY funds_data.top_holdings, 抓取日 2026-07-16",
        "options": f"yfinance SPY option chain, 抓取日 2026-07-16 (台灣時間晚間, 美股前一交易日 {spot_date} 收盤報價)",
    },
    "top5_official_weights_pct": {
        "NVDA": 7.4997, "AAPL": 6.5769, "MSFT": 4.2882, "AMZN": 3.6106,
        "GOOGL_classA": 3.2429, "GOOG_classC": 2.5845,
        "top5_companies_combined": round(OFFICIAL_W5 * 100, 4),
        "note": "以公司計前五大 = NVDA, AAPL, Alphabet(A+C), MSFT, AMZN; Alphabet 雙股權類合併計",
    },
    "method_weight_series": {
        "formula": "W5(t) = sum(Close_i(t)*SharesTodayBasis_i(t)) / (K * GSPC(t)); K 校準使最新日等於官方 27.8028%",
        "calibration_date": str(latest.date()),
        "K": float(K),
        "shares_basis": "get_shares_full 為當時申報股數(已驗證 NVDA 2020-01-02=612M), 換算到今日分割基準以匹配 yfinance 分割調整價; 換算切點用股數序列實際跳升日(非除權日), 避免申報滯後窗口的低估 (AAPL 案例: 除權 2020-08-31 vs 申報跳升 2020-10-22)",
        "split_factors_applied": split_factors,
        "split_shares_jump_dates": split_jump_dates,
        "assumption": "S&P 500 divisor 樣本期內近似常數; 股數前向填補",
        "basket_definition": "固定為 2026-07 當前前五大公司 (NVDA/AAPL/Alphabet A+C/MSFT/AMZN) 回溯, 非各歷史時點的前五大 — 2020 年當時前五大含 FB(META)、不含 NVDA, 故 2020 年真實前五大權重會略高於本序列",
    },
    "weight_series_monthly": ser(w5_m),
    "weight_stats": {
        "start": {"date": str(w5.dropna().index[0].date()), "w5_pct": round(float(w5.dropna().iloc[0]) * 100, 2)},
        "latest": {"date": str(latest.date()), "w5_pct": round(float(w5.loc[latest]) * 100, 2)},
        "min": {"date": str(w5.idxmin().date()), "w5_pct": round(float(w5.min()) * 100, 2)},
        "max": {"date": str(w5.idxmax().date()), "w5_pct": round(float(w5.max()) * 100, 2)},
        "n_days": int(w5.dropna().shape[0]),
    },
    "method_vol_gap": "20 日滾動 std of log returns (Adj Close), 年化 sqrt(252), 單位 %; 個股平均為 5 家等權 (Alphabet 用 GOOGL); gap = 個股平均 - SPY",
    "vol_gap_monthly": ser(volgap_m, 2),
    "vol_gap_stats": {
        "latest_date": str(vol_gap.index[-1].date()),
        "latest_spy_rv20_pct": round(float(idx_vol.dropna().iloc[-1]), 2),
        "latest_qqq_rv20_pct": round(float(qqq_vol.dropna().iloc[-1]), 2),
        "latest_top5avg_rv20_pct": round(float(stock_avg_vol.dropna().iloc[-1]), 2),
        "latest_gap_pct": round(float(vol_gap.iloc[-1]), 2),
        "full_sample_mean_gap_pct": round(float(vol_gap.mean()), 2),
        "gap_2026ytd_mean_pct": round(float(vol_gap.loc["2026":].mean()), 2),
        "n_days": int(vol_gap.shape[0]),
    },
    "hedge_cost": {
        "spot": {"value": spot, "date": spot_date, "note": "SPY 收盤價"},
        "front_month": front_res,
        "back_month": back_res,
        "method": "5% OTM put = strike 最接近 0.95*spot; spread = 買 95% put 賣 90% put; premium 用 bid/ask mid, 無報價 fallback lastPrice; 年化 = premium/spot*365/DTE",
    },
    "caveats_runtime": [
        "權重時序為市值近似 (divisor 常數假設 + 股數前向填補), 僅最新日錨定官方值; 歷史點位有 ±1-2pp 誤差空間",
        "籃子固定為今日前五大回溯 — 2020-2021 年當時實際前五大 (含 META、不含 NVDA) 權重會與本序列不同",
        "選擇權報價抓取於台灣時間晚間 (美股盤前), bid/ask 可能為 0 或 stale; premium_source 標明各筆用 mid 或 lastPrice, lastTradeDate 供核對",
        "front month DTE<7 的到期日已跳過 (年化無意義), 實際用的是 DTE>=7 的最近兩個月度合約",
        "波動缺口的個股平均為等權 (非權重加權); Alphabet 波動用 GOOGL 單一類股",
    ],
}

with open(OUT / "evidence.json", "w") as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2)
print("evidence.json written", flush=True)
print(json.dumps(evidence["weight_stats"], ensure_ascii=False))
print(json.dumps(evidence["vol_gap_stats"], ensure_ascii=False))
print(json.dumps({"front": front_res, "back": back_res}, ensure_ascii=False))
