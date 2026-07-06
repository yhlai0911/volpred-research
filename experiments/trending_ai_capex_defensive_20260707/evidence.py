"""
Evidence package for trending_repost: AI capex 變現疑慮 × 科技 vs 防禦板塊波動率黃金交叉
- QQQ (tech proxy) vs XLV/XLP/XLU (defensive sectors)
- Rolling 20-day annualized realized volatility divergence
- Cumulative return cross-section over lookback window
- VIX level + ^SKEW tail-risk pricing
Data source: yfinance (Yahoo Finance) daily adjusted closes. Seed fixed.
All numbers traceable to results.json.
"""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

matplotlib.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS"]
matplotlib.rcParams["axes.unicode_minus"] = False

np.random.seed(42)

HERE = "/Users/yhlai0911/volpred-research/experiments/trending_ai_capex_defensive_20260707"
ASSETS = "/Users/yhlai0911/volpred-research/storage/drafts/assets"

TICKERS = ["QQQ", "XLK", "XLV", "XLP", "XLU", "^VIX", "^SKEW"]
END = "2026-07-07"
START = "2025-10-01"   # ~9 months, enough for 20d rolling + 1-3 month window

raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False)
close = raw["Close"].dropna(how="all")

# --- realized vol: rolling 20-day annualized on log returns ---
logret = np.log(close / close.shift(1))
ANN = np.sqrt(252)
rv20 = logret.rolling(20).std() * ANN * 100  # in percent

# defensive basket = equal weight XLV/XLP/XLU
def_basket_ret = logret[["XLV", "XLP", "XLU"]].mean(axis=1)
rv20_def = def_basket_ret.rolling(20).std() * ANN * 100

# --- cumulative returns over trailing windows ---
def cum_ret(series, days):
    s = series.dropna()
    if len(s) < days + 1:
        return np.nan
    return (s.iloc[-1] / s.iloc[-days - 1] - 1) * 100

windows = {"1M": 21, "3M": 63}
cum = {}
for name, d in windows.items():
    cum[name] = {t: round(cum_ret(close[t], d), 2) for t in ["QQQ", "XLK", "XLV", "XLP", "XLU"]}

# --- latest RV snapshot ---
latest_rv = {
    "QQQ": round(float(rv20["QQQ"].dropna().iloc[-1]), 2),
    "XLK": round(float(rv20["XLK"].dropna().iloc[-1]), 2),
    "XLV": round(float(rv20["XLV"].dropna().iloc[-1]), 2),
    "XLP": round(float(rv20["XLP"].dropna().iloc[-1]), 2),
    "XLU": round(float(rv20["XLU"].dropna().iloc[-1]), 2),
    "DEF_BASKET": round(float(rv20_def.dropna().iloc[-1]), 2),
}
# RV 1 month ago
def rv_ago(series, days=21):
    s = series.dropna()
    return round(float(s.iloc[-days - 1]), 2)

rv_1m_ago = {
    "QQQ": rv_ago(rv20["QQQ"]),
    "XLV": rv_ago(rv20["XLV"]),
    "XLP": rv_ago(rv20["XLP"]),
    "XLU": rv_ago(rv20["XLU"]),
    "DEF_BASKET": rv_ago(rv20_def),
}

# --- spread: QQQ RV minus defensive basket RV ---
spread = (rv20["QQQ"] - rv20_def).dropna()
spread_now = round(float(spread.iloc[-1]), 2)
spread_1m_ago = round(float(spread.iloc[-22]), 2)
spread_3m_ago = round(float(spread.iloc[-64]), 2)
spread_max = round(float(spread.max()), 2)
spread_min = round(float(spread.min()), 2)
spread_mean = round(float(spread.mean()), 2)

# --- correlation of QQQ vs defensive daily returns (rolling 60d) ---
corr60 = def_basket_ret.rolling(60).corr(logret["QQQ"])
corr_now = round(float(corr60.dropna().iloc[-1]), 3)
corr_3m_ago = round(float(corr60.dropna().iloc[-64]), 3)

# --- VIX / SKEW ---
vix_now = round(float(close["^VIX"].dropna().iloc[-1]), 2)
vix_1m_ago = round(float(close["^VIX"].dropna().iloc[-22]), 2)
vix_3m_ago = round(float(close["^VIX"].dropna().iloc[-64]), 2)
vix_mean = round(float(close["^VIX"].dropna().iloc[-63:].mean()), 2)
skew_series = close["^SKEW"].dropna()
skew_now = round(float(skew_series.iloc[-1]), 2)
skew_1m_ago = round(float(skew_series.iloc[-22]), 2)
skew_3m_ago = round(float(skew_series.iloc[-64]), 2)
skew_mean = round(float(skew_series.iloc[-63:].mean()), 2)
skew_max = round(float(skew_series.iloc[-63:].max()), 2)

sample_n = int(len(close))
date_first = str(close.index[0].date())
date_last = str(close.index[-1].date())

results = {
    "meta": {
        "generated": "2026-07-07",
        "data_source": "yfinance (Yahoo Finance) daily adjusted close",
        "period": f"{date_first} to {date_last}",
        "trading_days": sample_n,
        "seed": 42,
        "rv_method": "20-day rolling std of log returns, annualized sqrt(252), in percent",
        "def_basket": "equal-weight XLV/XLP/XLU",
    },
    "latest_rv20_pct": latest_rv,
    "rv20_1m_ago_pct": rv_1m_ago,
    "cumulative_return_pct": cum,
    "qqq_minus_defensive_rv_spread": {
        "now": spread_now,
        "1m_ago": spread_1m_ago,
        "3m_ago": spread_3m_ago,
        "window_max": spread_max,
        "window_min": spread_min,
        "window_mean": spread_mean,
    },
    "rolling60_corr_qqq_vs_defensive": {"now": corr_now, "3m_ago": corr_3m_ago},
    "vix": {"now": vix_now, "1m_ago": vix_1m_ago, "3m_ago": vix_3m_ago, "3m_mean": vix_mean},
    "skew_index": {
        "now": skew_now, "1m_ago": skew_1m_ago, "3m_ago": skew_3m_ago,
        "3m_mean": skew_mean, "3m_max": skew_max,
    },
}

with open(f"{HERE}/results.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

# ================= CHART 1: RV divergence =================
fig, ax = plt.subplots(figsize=(10, 5.5))
tail = rv20.dropna().iloc[-90:]
tail_def = rv20_def.dropna().iloc[-90:]
ax.plot(tail.index, tail["QQQ"], color="#d62728", lw=2.2, label="QQQ 科技（那斯達克100）")
ax.plot(tail_def.index, tail_def, color="#2ca02c", lw=2.2, label="防禦籃 XLV/XLP/XLU 等權")
ax.fill_between(tail.index, tail["QQQ"], tail_def.reindex(tail.index),
                where=(tail["QQQ"] > tail_def.reindex(tail.index)),
                color="#d62728", alpha=0.10, interpolate=True)
ax.set_title("科技 vs 防禦板塊：20日已實現波動率背離（近90交易日）", fontsize=13, fontweight="bold")
ax.set_ylabel("年化已實現波動率 (%)", fontsize=11)
ax.legend(loc="upper left", fontsize=10, frameon=False)
ax.grid(alpha=0.25)
ax.spines[["top", "right"]].set_visible(False)
fig.text(0.99, 0.01, f"資料：yfinance {date_first}~{date_last}｜seed=42", ha="right", fontsize=7, color="gray")
fig.tight_layout()
fig.savefig(f"{ASSETS}/ai_capex_rv_divergence_20260707.png", dpi=140)
plt.close(fig)

# ================= CHART 2: cumulative return cross-section =================
fig, ax = plt.subplots(figsize=(9, 5))
labels = ["QQQ\n科技", "XLK\n科技", "XLV\n醫療", "XLP\n必需消費", "XLU\n公用事業"]
tickers_ord = ["QQQ", "XLK", "XLV", "XLP", "XLU"]
r1m = [cum["1M"][t] for t in tickers_ord]
r3m = [cum["3M"][t] for t in tickers_ord]
x = np.arange(len(tickers_ord))
w = 0.38
b1 = ax.bar(x - w / 2, r1m, w, label="近1個月", color="#1f77b4")
b2 = ax.bar(x + w / 2, r3m, w, label="近3個月", color="#ff7f0e")
ax.axhline(0, color="black", lw=0.8)
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("累積報酬 (%)", fontsize=11)
ax.set_title("科技 vs 防禦板塊：累積報酬橫斷面", fontsize=13, fontweight="bold")
ax.legend(fontsize=10, frameon=False)
ax.grid(axis="y", alpha=0.25)
ax.spines[["top", "right"]].set_visible(False)
for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:.1f}", (bar.get_x() + bar.get_width() / 2, h),
                    ha="center", va="bottom" if h >= 0 else "top", fontsize=8)
fig.text(0.99, 0.01, f"資料：yfinance {date_first}~{date_last}｜seed=42", ha="right", fontsize=7, color="gray")
fig.tight_layout()
fig.savefig(f"{ASSETS}/ai_capex_return_crosssection_20260707.png", dpi=140)
plt.close(fig)

# find CJK font
print(json.dumps(results, indent=2, ensure_ascii=False))
