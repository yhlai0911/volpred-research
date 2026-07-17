# -*- coding: utf-8 -*-
"""AI capex vs revenue gap — tail-risk pricing asset builder.

Outputs (all in this directory):
  - evidence.json
  - fig_capex_vs_revenue.png
  - fig_skew_snapshot.png

Data sources:
  - Web-sourced capex/revenue figures (hard-coded below, each with source URL)
  - yfinance daily prices 2025-01-01 .. today
  - yfinance option chains (QQQ, NVDA, META, MSFT)

Honesty notes: every number in the figures traces to a field in evidence.json.
Random seed fixed (no stochastic steps used, set anyway).
"""
import json
import math
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import norm

np.random.seed(20260716)

OUT = Path(__file__).resolve().parent
TODAY = dt.date(2026, 7, 16)
RISK_FREE = 0.04  # assumption, see caveats

plt.rcParams["font.sans-serif"] = ["Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

# ----------------------------------------------------------------------
# 1) Web-sourced fundamentals (calendar Q1 2026 unless noted)
# ----------------------------------------------------------------------
FUNDAMENTALS = {
    "MSFT": {
        "label": "Microsoft",
        "quarter": "FY26Q3 (2026-01~03)",
        "capex_q_usd_bn": 31.9,
        "capex_yoy_pct": 49.0,
        "capex_note": "含 finance leases；低於分析師共識 34.9B",
        "fy_capex_guidance": "CY2026 約 1,900 億美元（含約 250 億元件漲價影響）",
        "rev_proxy_label": "Microsoft Cloud 營收",
        "rev_proxy_yoy_pct": 29.0,
        "rev_proxy_level": "54.5B USD",
        "total_rev_yoy_pct": 18.0,
        "sources": [
            "https://www.cnbc.com/2026/04/29/microsoft-msft-q3-earnings-report-2026.html",
            "https://rbnenergy.com/daily-posts/analyst-insight/2026-earnings-calls-microsofts-ai-boom-drives-record-quarter-capital",
        ],
    },
    "GOOGL": {
        "label": "Alphabet",
        "quarter": "2026Q1",
        "capex_q_usd_bn": 35.7,
        "capex_yoy_pct": 107.0,
        "capex_note": "vs 2025Q1 的 17.2B",
        "fy_capex_guidance": "CY2026 指引 1,800–1,900 億美元（自 1,750–1,850 億上修）；2027 預告續增",
        "rev_proxy_label": "Google Cloud 營收",
        "rev_proxy_yoy_pct": 63.0,
        "rev_proxy_level": "20.0B USD",
        "total_rev_yoy_pct": None,
        "sources": [
            "https://www.cnbc.com/2026/04/29/alphabet-googl-q1-2026-earnings.html",
            "https://www.investing.com/news/company-news/alphabet-q1-2026-slides-cloud-surges-63-ai-investments-accelerate-93CH-4654872",
        ],
    },
    "AMZN": {
        "label": "Amazon",
        "quarter": "2026Q1",
        "capex_q_usd_bn": 44.2,
        "capex_yoy_pct": 77.0,
        "capex_note": "vs 2025Q1 約 25B；TTM capex 147.3B (+67%)",
        "fy_capex_guidance": "CY2026 全公司 capex 計畫約 2,000 億美元，絕大多數投向 AWS/AI",
        "rev_proxy_label": "AWS 營收",
        "rev_proxy_yoy_pct": 28.0,
        "rev_proxy_level": "37.6B USD",
        "total_rev_yoy_pct": None,
        "sources": [
            "https://www.cnbc.com/2026/04/29/amazon-amzn-q1-earnings-report-2026.html",
            "https://www.investing.com/news/company-news/amazon-q1-2026-slides-aws-surges-28-record-margins-offset-by-capex-93CH-4647447",
        ],
    },
    "META": {
        "label": "Meta",
        "quarter": "2026Q1",
        "capex_q_usd_bn": 19.84,
        "capex_yoy_pct": 44.9,  # computed: 19.84 vs 13.69 (Meta Q1'25 press release)
        "capex_note": "YoY 為自行計算（19.84 vs 13.69B），基期含 finance-lease 本金",
        "fy_capex_guidance": "CY2026 指引上修至 1,250–1,450 億美元（原 1,150–1,350 億）；盤後股價跌逾 6%",
        "rev_proxy_label": "總營收（無雲端分部）",
        "rev_proxy_yoy_pct": 33.0,
        "rev_proxy_level": "56.3B USD",
        "total_rev_yoy_pct": 33.0,
        "sources": [
            "https://www.cnbc.com/2026/04/29/meta-q1-earnings-report-2026.html",
            "https://fortune.com/2026/04/29/meta-zuckerberg-145-billion-ai-spending-roi/",
        ],
    },
}

# ----------------------------------------------------------------------
# 2) Prices: realized vol + 90d trend
# ----------------------------------------------------------------------
TICKERS = ["MSFT", "GOOGL", "AMZN", "META", "NVDA", "QQQ"]


def download_with_retry(ticker, start, tries=6, pause=8):
    import time
    last_err = None
    for i in range(tries):
        try:
            df = yf.download(ticker, start=start, auto_adjust=True,
                             progress=False, threads=False)
            if df is not None and len(df) > 100:
                return df["Close"][ticker]
            last_err = f"short/empty frame ({0 if df is None else len(df)} rows)"
        except Exception as e:  # noqa: BLE001 — retry any transport failure
            last_err = f"{type(e).__name__}: {e}"
        # A rerun that reproduces the figures must say why it could not: a bad
        # ticker and a rate-limit both end at `tries` exhausted, and only the
        # message tells them apart.
        print(f"  {ticker} attempt {i + 1}/{tries} failed: {last_err}")
        time.sleep(pause)
    raise RuntimeError(
        f"yfinance download failed after {tries} tries: {ticker} — last: {last_err}")


cols = {}
for t in TICKERS:
    cols[t] = download_with_retry(t, "2025-01-01")
    print(f"downloaded {t}: {len(cols[t])} rows, last={cols[t].index[-1].date()}")
px = pd.DataFrame(cols)
px = px.dropna(how="all")
ret = np.log(px / px.shift(1))
rv20 = ret.rolling(20).std() * np.sqrt(252) * 100  # annualized %

price_block = {}
for t in TICKERS:
    s = px[t].dropna()
    r20 = rv20[t].dropna()
    last90 = s[s.index >= s.index[-1] - pd.Timedelta(days=90)]
    price_block[t] = {
        "last_date": str(s.index[-1].date()),
        "last_close": round(float(s.iloc[-1]), 2),
        "rv20_now_pct": round(float(r20.iloc[-1]), 2),
        "rv20_1m_ago_pct": round(float(r20.iloc[-22]), 2) if len(r20) > 22 else None,
        "rv20_2025_median_pct": round(float(r20[r20.index.year == 2025].median()), 2),
        "ret_90d_pct": round(float(s.iloc[-1] / last90.iloc[0] - 1) * 100, 2),
        "ret_ytd_pct": round(float(s.iloc[-1] / s[s.index.year == 2026].iloc[0] - 1) * 100, 2),
        "n_obs": int(len(s)),
    }

# ----------------------------------------------------------------------
# 3) Options: 25-delta skew snapshot
# ----------------------------------------------------------------------
def bs_delta(S, K, T, r, sigma, kind):
    if sigma <= 0 or T <= 0:
        return np.nan
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1) if kind == "call" else norm.cdf(d1) - 1.0


def bs_price(S, K, T, r, sigma, kind):
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(price, S, K, T, r, kind):
    """Invert BS from last traded price (pre-market: Yahoo IV field is broken)."""
    from scipy.optimize import brentq
    intrinsic = max(S - K * math.exp(-r * T), 0) if kind == "call" else max(K * math.exp(-r * T) - S, 0)
    if price <= intrinsic + 1e-6 or price >= S:
        return np.nan
    try:
        return brentq(lambda sig: bs_price(S, K, T, r, sig, kind) - price, 1e-3, 3.0, xtol=1e-6)
    except ValueError:
        return np.nan


def clean_chain(df, S, T, kind, last_session):
    """Keep contracts actually traded on the last session; recompute IV from lastPrice."""
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["lastTradeDate"]).dt.tz_convert("America/New_York").dt.date
    df = df[df["trade_date"] == last_session]
    df = df[(df["lastPrice"] > 0.05) & (df["volume"].fillna(0) >= 1)]
    df = df[(df["strike"] > 0.65 * S) & (df["strike"] < 1.35 * S)]
    df["iv_recomputed"] = [implied_vol(p, S, k, T, RISK_FREE, kind)
                           for p, k in zip(df["lastPrice"], df["strike"])]
    df = df.dropna(subset=["iv_recomputed"])
    df = df[(df["iv_recomputed"] > 0.03) & (df["iv_recomputed"] < 2.5)]
    df["impliedVolatility"] = df["iv_recomputed"]
    return df.sort_values("strike")


def iv_at_delta(df, S, T, target_delta, kind):
    """Interpolate IV at a target BS delta using the chain's own IVs."""
    rows = []
    for _, row in df.iterrows():
        d = bs_delta(S, row["strike"], T, RISK_FREE, row["impliedVolatility"], kind)
        if not np.isnan(d):
            rows.append((d, row["impliedVolatility"], row["strike"]))
    if len(rows) < 3:
        return None
    arr = pd.DataFrame(rows, columns=["delta", "iv", "strike"])
    # delta monotone-ish in strike; interpolate iv on delta
    arr = arr.sort_values("delta")
    if not (arr["delta"].min() <= target_delta <= arr["delta"].max()):
        return None
    iv = float(np.interp(target_delta, arr["delta"], arr["iv"]))
    k = float(np.interp(target_delta, arr["delta"], arr["strike"]))
    return {"iv_pct": round(iv * 100, 2), "strike_approx": round(k, 1)}


def pick_expiry(tk, lo=20, hi=45):
    exps = tk.options
    if not exps:
        raise RuntimeError("empty expiry list")
    best, best_dte = None, None
    for e in exps:
        dte = (dt.date.fromisoformat(e) - TODAY).days
        if lo <= dte <= hi:
            return e, dte
        if dte > 5 and (best is None or abs(dte - 30) < abs(best_dte - 30)):
            best, best_dte = e, dte
    return best, best_dte


def retry(fn, tries=5, pause=8, label=""):
    import time
    last = None
    for _ in range(tries):
        try:
            out = fn()
            if out is not None:
                return out
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(pause)
    raise RuntimeError(f"retry exhausted for {label}: {last}")


opt_block = {}
opt_caveats = []
for t in ["QQQ", "NVDA", "META", "MSFT"]:
    try:
        tk = yf.Ticker(t)
        S = float(px[t].dropna().iloc[-1])
        exp, dte = retry(lambda: pick_expiry(tk), label=f"{t} expiries")
        if exp is None:
            opt_caveats.append(f"{t}: 無可用到期日，跳過")
            continue
        T = dte / 365.0
        ch = retry(lambda: tk.option_chain(exp), label=f"{t} chain {exp}")
        last_session = px[t].dropna().index[-1].date()
        calls = clean_chain(ch.calls, S, T, "call", last_session)
        puts = clean_chain(ch.puts, S, T, "put", last_session)
        if len(calls) < 3 or len(puts) < 3:
            opt_caveats.append(f"{t}: 鏈清理後樣本不足 (calls={len(calls)}, puts={len(puts)})，跳過")
            continue
        c25 = iv_at_delta(calls, S, T, 0.25, "call")
        p25 = iv_at_delta(puts, S, T, -0.25, "put")
        # ATM: strike closest to spot, average call/put IV
        c_atm = calls.iloc[(calls["strike"] - S).abs().argsort()[:1]]["impliedVolatility"].mean()
        p_atm = puts.iloc[(puts["strike"] - S).abs().argsort()[:1]]["impliedVolatility"].mean()
        atm_iv = round(float((c_atm + p_atm) / 2) * 100, 2)

        # moneyness-based skew for comparability with 2026-07-02 snapshot
        def iv_at_m(df, m):
            d = df.assign(mny=df["strike"] / S).sort_values("mny")
            if not (d["mny"].min() <= m <= d["mny"].max()):
                return None
            return round(float(np.interp(m, d["mny"], d["impliedVolatility"])) * 100, 2)

        p90 = iv_at_m(puts, 0.90)
        c110 = iv_at_m(calls, 1.10)
        entry = {
            "spot": round(S, 2),
            "expiry": exp,
            "dte": dte,
            "atm_iv_pct": atm_iv,
            "call25d": c25,
            "put25d": p25,
            "n_calls_used": int(len(calls)),
            "n_puts_used": int(len(puts)),
            "put_iv_90m_pct": p90,
            "call_iv_110m_pct": c110,
            "skew_90_110_pp": round(p90 - c110, 2) if (p90 and c110) else None,
        }
        if c25 and p25:
            entry["skew_25d_pp"] = round(p25["iv_pct"] - c25["iv_pct"], 2)
            entry["skew_norm_pct_of_atm"] = round((p25["iv_pct"] - c25["iv_pct"]) / atm_iv * 100, 1)
        else:
            opt_caveats.append(f"{t}: 25-delta 內插失敗 (call={bool(c25)}, put={bool(p25)})，僅存 ATM")
        opt_block[t] = entry
    except Exception as e:  # noqa: BLE001
        opt_caveats.append(f"{t}: 期權抓取失敗 — {type(e).__name__}: {e}")

# ----------------------------------------------------------------------
# 4) Figure (a): capex growth vs revenue growth
# ----------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5.6), dpi=150)
names = ["MSFT", "GOOGL", "AMZN", "META"]
x = np.arange(len(names))
capex_g = [FUNDAMENTALS[n]["capex_yoy_pct"] for n in names]
rev_g = [FUNDAMENTALS[n]["rev_proxy_yoy_pct"] for n in names]
b1 = ax.bar(x - 0.2, capex_g, width=0.38, color="#c0504d", label="資本支出年增率（2026Q1）")
b2 = ax.bar(x + 0.2, rev_g, width=0.38, color="#4f81bd", label="AI/雲端營收年增率（同季）")
for b in list(b1) + list(b2):
    ax.annotate(f"{b.get_height():.0f}%", (b.get_x() + b.get_width() / 2, b.get_height() + 1.5),
                ha="center", fontsize=10, fontweight="bold")
labels = [f"{FUNDAMENTALS[n]['label']}\n({FUNDAMENTALS[n]['rev_proxy_label'].split('（')[0].replace(' 營收','')})" for n in names]
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=10)
ax.set_ylabel("年增率（%）")
ax.set_title("AI 資本支出增速 vs 營收實現增速 — 2026Q1（曆年）", fontsize=13)
ax.legend(frameon=False)
ax.spines[["top", "right"]].set_visible(False)
ax.set_ylim(0, max(capex_g) * 1.18)
fig.text(0.01, 0.012,
         "資料來源：各公司 2026Q1（MSFT 為 FY26Q3，2026 年 1–3 月）財報與 CNBC / Investing.com 報導（2026-04-29）。\n"
         "Meta 無雲端分部，營收列總營收；Meta capex 年增率為自行計算（單季 198.4 億 vs 前一年同季 136.9 億美元）。",
         fontsize=7.5, color="#555555")
fig.tight_layout(rect=[0, 0.07, 1, 1])
fig.savefig(OUT / "fig_capex_vs_revenue.png")
plt.close(fig)

# ----------------------------------------------------------------------
# 5) Figure (b): skew snapshot
# ----------------------------------------------------------------------
sk_names = [t for t in ["QQQ", "NVDA", "META", "MSFT"] if t in opt_block and "skew_25d_pp" in opt_block[t]]
if sk_names:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5.2), dpi=150,
                                   gridspec_kw={"width_ratios": [1.6, 1]})
    x = np.arange(len(sk_names))
    put_iv = [opt_block[t]["put25d"]["iv_pct"] for t in sk_names]
    atm_iv = [opt_block[t]["atm_iv_pct"] for t in sk_names]
    call_iv = [opt_block[t]["call25d"]["iv_pct"] for t in sk_names]
    ax1.bar(x - 0.27, put_iv, width=0.26, color="#c0504d", label="25Δ Put IV（下檔保險）")
    ax1.bar(x, atm_iv, width=0.26, color="#9e9e9e", label="ATM IV")
    ax1.bar(x + 0.27, call_iv, width=0.26, color="#4f81bd", label="25Δ Call IV（上檔樂透）")
    for xi, (p, a, c) in enumerate(zip(put_iv, atm_iv, call_iv)):
        for off, v in [(-0.27, p), (0, a), (0.27, c)]:
            ax1.annotate(f"{v:.1f}", (xi + off, v + 0.4), ha="center", fontsize=8.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{t}\n({opt_block[t]['expiry']}, {opt_block[t]['dte']}天)" for t in sk_names], fontsize=9)
    ax1.set_ylabel("隱含波動率（%，年化）")
    ax1.set_title("近月期權 IV 快照：下檔 vs 上檔", fontsize=12)
    ax1.legend(frameon=False, fontsize=9)
    ax1.spines[["top", "right"]].set_visible(False)

    skews = [opt_block[t]["skew_25d_pp"] for t in sk_names]
    colors = ["#c0504d" if s > 0 else "#4f81bd" for s in skews]
    ax2.bar(x, skews, width=0.5, color=colors)
    for xi, s in enumerate(skews):
        ax2.annotate(f"{s:+.1f}pp", (xi, s + (0.1 if s >= 0 else -0.35)), ha="center",
                     fontsize=10, fontweight="bold")
    ax2.axhline(0, color="#333333", lw=0.8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(sk_names, fontsize=10)
    ax2.set_title("25Δ Skew（Put IV − Call IV）\n= 尾部保費", fontsize=12)
    ax2.set_ylabel("百分點（pp）")
    ax2.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.012,
             f"資料來源：yfinance 期權鏈（2026-07-15 實際成交價，快照製作 {TODAY}）。"
             f"IV 由成交價以 Black-Scholes 反推（r={RISK_FREE:.0%}、未調股息），25Δ 對 delta 內插。",
             fontsize=7.5, color="#555555")
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(OUT / "fig_skew_snapshot.png")
    plt.close(fig)

# ----------------------------------------------------------------------
# 6) evidence.json
# ----------------------------------------------------------------------
evidence = {
    "asset_id": "trending_ai_capex_20260716",
    "generated_at_taipei": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "angle": "AI 資本支出 vs 營收落差的尾部風險定價",
    "fundamentals_q1_2026": FUNDAMENTALS,
    "prices": {
        "source": "yfinance daily close (auto_adjust=True), 2025-01-01 起",
        "tickers": price_block,
    },
    "options_snapshot": {
        "source": "yfinance option_chain",
        "method": ("IV 由合約 lastPrice 以 Black-Scholes 反推（brentq，r=0.04、無股息；"
                   "盤前時段 Yahoo 鏈上 IV/bid/ask/OI 欄位無效，故用前一交易日實際成交價）；"
                   "僅保留 2026-07-15 有成交的合約，spot 用同日收盤價保持 timing 一致；"
                   "25-delta 由 BS delta 對 delta 內插；ATM 取最近 spot 履約價 call/put IV 平均；"
                   "另計 90/110 moneyness skew 以與 2026-07-02 舊快照可比"),
        "risk_free_assumption": RISK_FREE,
        "tickers": opt_block,
        "caveats": opt_caveats,
    },
    "historical_skew_comparison": {
        "source": "storage/data/skew_series/mega_cap_skew_series.json（2026-07-02 快照，同 90/110 moneyness 定義）",
        "note": "7/02 快照約 29 DTE、本次 22 DTE，非嚴格同 maturity；方向對比仍有效",
        "skew_90_110_pp_2026_07_02": {"QQQ": 11.05, "NVDA": 4.51, "META": -3.09, "MSFT": -1.8},
        "skew_90_110_pp_2026_07_16": {
            t: opt_block[t].get("skew_90_110_pp") for t in opt_block
        },
    },
    "caveats": [
        "期權 IV 由前一交易日（2026-07-15）合約 lastPrice 以 BS 反推：盤前時段 Yahoo 鏈上 IV/bid/ask/OI 欄位無效。last trade 時間非同步，低流動性履約價可能 stale。",
        "BS 反推假設 r=4%、無股息；對 22 DTE 短天期影響小。",
        "MSFT 季度 capex 為含 finance leases 口徑（31.9B, +49%）；四家公司 capex 口徑不完全一致。",
        "Meta capex 年增率 44.9% 為自行計算：2026Q1 19.84B vs 2025Q1 13.69B（Meta 2025Q1 財報，含 finance-lease 本金）。",
        "2026-08-07 到期鏈涵蓋 MSFT/META 等 7 月底財報日，個股 ATM IV 含財報事件溢價（MSFT ATM 51%、META 61% 遠高於 QQQ 24% 的部分原因）。",
        "put/call OI ratio 本次無法計算（盤前 OI 欄位為 0）。",
        "與 2026-07-02 歷史快照對比時 DTE 不同（29 vs 22 天）。",
    ],
    "figures": ["fig_capex_vs_revenue.png", "fig_skew_snapshot.png"],
}
(OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
print(json.dumps({"prices": price_block, "options": opt_block, "opt_caveats": opt_caveats},
                 ensure_ascii=False, indent=2))
