"""
K1429 — EAV (Earnings Announcement Volatility) Effect
Analysis of realized volatility patterns around earnings announcements.
Universe: NVDA (primary) + AAPL, MSFT (controls)
Period: 2024-01-01 to 2026-06-08
"""

import json
import os
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')

np.random.seed(42)

OUT_DIR = Path("experiments/k1429")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Earnings announcement dates
# ---------------------------------------------------------------------------
# NVDA earnings release dates (after-hours or pre-market, use next trading day
# as the "event day T" for daily close-based analysis)
# Sources: NVDA investor relations press releases
NVDA_EARNINGS = [
    "2024-02-21",  # Q4 FY24 (results day)
    "2024-05-22",  # Q1 FY25
    "2024-08-28",  # Q2 FY25
    "2024-11-20",  # Q3 FY25
    "2025-02-26",  # Q4 FY25
    "2025-05-28",  # Q1 FY26
    "2025-08-27",  # Q2 FY26
    "2025-11-19",  # Q3 FY26
    "2026-05-28",  # Q1 FY27
]

AAPL_EARNINGS = [
    "2024-02-01",  # Q1 FY24
    "2024-05-02",  # Q2 FY24
    "2024-08-01",  # Q3 FY24
    "2024-10-31",  # Q4 FY24
    "2025-01-30",  # Q1 FY25
    "2025-05-01",  # Q2 FY25
    "2025-07-31",  # Q3 FY25
    "2025-10-30",  # Q4 FY25
    "2026-01-30",  # Q1 FY26
]

MSFT_EARNINGS = [
    "2024-01-30",  # Q2 FY24
    "2024-04-25",  # Q3 FY24
    "2024-07-30",  # Q4 FY24
    "2024-10-30",  # Q1 FY25
    "2025-01-29",  # Q2 FY25
    "2025-04-30",  # Q3 FY25
    "2025-07-29",  # Q4 FY25
    "2025-10-29",  # Q1 FY26
    "2026-01-29",  # Q2 FY26
]

EARNINGS_DATES = {
    "NVDA": [pd.Timestamp(d) for d in NVDA_EARNINGS],
    "AAPL": [pd.Timestamp(d) for d in AAPL_EARNINGS],
    "MSFT": [pd.Timestamp(d) for d in MSFT_EARNINGS],
}

TICKERS = ["NVDA", "AAPL", "MSFT"]

# ---------------------------------------------------------------------------
# 2. Download price data
# ---------------------------------------------------------------------------
print("Downloading price data via yfinance...")
import yfinance as yf

START = "2023-12-01"  # buffer for RV calculation
END = "2026-06-08"

raw = yf.download(TICKERS, start=START, end=END, group_by='ticker', auto_adjust=True)

# Extract close prices
close_dict = {}
for ticker in TICKERS:
    try:
        close_dict[ticker] = raw[ticker]["Close"].dropna()
    except Exception:
        close_dict[ticker] = raw["Close"][ticker].dropna()

# Confirm data coverage
for t, s in close_dict.items():
    print(f"  {t}: {s.index[0].date()} → {s.index[-1].date()}, n={len(s)}")

# ---------------------------------------------------------------------------
# 3. Compute log returns and 5-day rolling RV
# ---------------------------------------------------------------------------
RV_WINDOW = 5  # trading days

rv_dict = {}
for ticker, prices in close_dict.items():
    log_ret = np.log(prices).diff()
    # 5-day rolling annualised RV: sqrt(252) * std(log_ret over [t-4, t])
    rv = log_ret.rolling(RV_WINDOW).std() * np.sqrt(252)
    rv_dict[ticker] = rv

# Filter to main analysis window
ANALYSIS_START = pd.Timestamp("2024-01-01")
ANALYSIS_END = pd.Timestamp("2026-06-08")

for ticker in TICKERS:
    rv_dict[ticker] = rv_dict[ticker].loc[ANALYSIS_START:ANALYSIS_END].dropna()

# ---------------------------------------------------------------------------
# 4. Event window analysis
# ---------------------------------------------------------------------------
PRE_WINDOW = 5    # T-5 to T-1
POST_WINDOW = 5   # T+1 to T+5
BASELINE_EXCL = 10  # exclude ±10 days around earnings

def get_trading_days_offset(date, rv_series, offset):
    """Return the date that is `offset` trading days from `date` in rv_series index."""
    idx = rv_series.index
    pos = idx.searchsorted(date)
    target_pos = pos + offset
    if 0 <= target_pos < len(idx):
        return idx[target_pos]
    return None


results = {}
event_rv_all = {}  # {ticker: list of arrays of RV per event, indexed -10..+10}

for ticker in TICKERS:
    rv = rv_dict[ticker]
    earnings = [d for d in EARNINGS_DATES[ticker] if ANALYSIS_START <= d <= ANALYSIS_END]

    pre_rvs = []    # one value per event: mean RV over [T-5, T-1]
    post_rvs = []   # one value per event: mean RV over [T+1, T+5]
    event_rvs = []  # T=0

    # For event study plot: relative day -10 to +10
    event_windows = []

    # Baseline: all trading days NOT within ±BASELINE_EXCL of any earnings
    all_earnings_set = set()
    for d in earnings:
        idx = rv.index.searchsorted(d)
        for offset in range(-BASELINE_EXCL, BASELINE_EXCL + 1):
            pos = idx + offset
            if 0 <= pos < len(rv.index):
                all_earnings_set.add(rv.index[pos])

    baseline_rv = rv[~rv.index.isin(all_earnings_set)]
    baseline_mean = baseline_rv.mean()

    valid_events = 0
    for earn_date in earnings:
        idx_pos = rv.index.searchsorted(earn_date)

        # Find T=0 (event day or first trading day on/after)
        if idx_pos >= len(rv.index):
            continue
        t0 = rv.index[idx_pos]

        # Build -10 to +10 window
        window_rv = []
        for offset in range(-10, 11):
            pos = idx_pos + offset
            if 0 <= pos < len(rv.index):
                window_rv.append((offset, rv.iloc[pos]))
            else:
                window_rv.append((offset, np.nan))

        offsets = [x[0] for x in window_rv]
        values = [x[1] for x in window_rv]
        event_windows.append(values)

        # Pre: T-5 to T-1 (offsets -5 to -1)
        pre_vals = [v for o, v in window_rv if -5 <= o <= -1 and not np.isnan(v)]
        # Post: T+1 to T+5
        post_vals = [v for o, v in window_rv if 1 <= o <= 5 and not np.isnan(v)]
        # Event day
        event_val = [v for o, v in window_rv if o == 0 and not np.isnan(v)]

        if len(pre_vals) >= 3 and len(post_vals) >= 3:
            pre_rvs.append(np.mean(pre_vals))
            post_rvs.append(np.mean(post_vals))
            event_rvs.append(np.mean(event_val) if event_val else np.nan)
            valid_events += 1

    pre_rvs = np.array(pre_rvs)
    post_rvs = np.array(post_rvs)
    n_events = len(pre_rvs)

    # Paired t-test: pre vs baseline (replicate baseline value for each event)
    baseline_arr = np.full(n_events, baseline_mean)

    t_pre, p_pre = stats.ttest_rel(pre_rvs, baseline_arr)
    t_post, p_post = stats.ttest_rel(post_rvs, baseline_arr)

    pre_mean_diff = np.mean(pre_rvs) - baseline_mean
    post_mean_diff = np.mean(post_rvs) - baseline_mean

    pre_premium_pct = (pre_mean_diff / baseline_mean) * 100
    post_premium_pct = (post_mean_diff / baseline_mean) * 100

    results[ticker] = {
        "baseline_mean_rv": round(float(baseline_mean), 4),
        "pre_mean_rv": round(float(np.mean(pre_rvs)), 4),
        "post_mean_rv": round(float(np.mean(post_rvs)), 4),
        "pre_mean_diff": round(float(pre_mean_diff), 4),
        "post_mean_diff": round(float(post_mean_diff), 4),
        "pre_premium_pct": round(float(pre_premium_pct), 2),
        "post_premium_pct": round(float(post_premium_pct), 2),
        "t_pre": round(float(t_pre), 3),
        "p_pre": round(float(p_pre), 4),
        "t_post": round(float(t_post), 3),
        "p_post": round(float(p_post), 4),
        "n_events": n_events,
        "significant_pre": bool(p_pre < 0.05),
        "significant_post": bool(p_post < 0.05),
    }

    # Store for event study plot: shape (n_events, 21)
    if event_windows:
        event_rv_all[ticker] = np.array(event_windows)  # shape (n_events, 21)

    print(f"\n{ticker}:")
    print(f"  n_events={n_events}, baseline_rv={baseline_mean:.4f}")
    print(f"  pre:  mean_rv={np.mean(pre_rvs):.4f}, premium={pre_premium_pct:.1f}%, t={t_pre:.3f}, p={p_pre:.4f}")
    print(f"  post: mean_rv={np.mean(post_rvs):.4f}, premium={post_premium_pct:.1f}%, t={t_post:.3f}, p={p_post:.4f}")

# ---------------------------------------------------------------------------
# 5. Event study plot
# ---------------------------------------------------------------------------
COLORS = {"NVDA": "#76b900", "AAPL": "#555555", "MSFT": "#00a4ef"}

fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
offsets_plot = list(range(-10, 11))

for ticker in TICKERS:
    ev = event_rv_all.get(ticker)
    if ev is None:
        continue
    mean_rv = np.nanmean(ev, axis=0)
    sem_rv = np.nanstd(ev, axis=0) / np.sqrt(np.sum(~np.isnan(ev), axis=0))
    ci95 = 1.96 * sem_rv

    ax.plot(offsets_plot, mean_rv, color=COLORS[ticker], linewidth=2, label=ticker, marker='o', markersize=3)
    ax.fill_between(offsets_plot, mean_rv - ci95, mean_rv + ci95, color=COLORS[ticker], alpha=0.15)

ax.axvline(0, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='Earnings Day (T=0)')
ax.axvspan(-5, -1, alpha=0.05, color='orange', label='Pre-earnings window')
ax.axvspan(1, 5, alpha=0.05, color='blue', label='Post-earnings window')
ax.set_xlabel("Trading Days Relative to Earnings (T=0)", fontsize=12)
ax.set_ylabel("5-Day Rolling Annualised RV", fontsize=12)
ax.set_title("EAV Effect: Realized Volatility Around Earnings Announcements\n(NVDA, AAPL, MSFT | 2024–2026)", fontsize=13)
ax.legend(fontsize=10)
ax.grid(True, alpha=0.3)
ax.set_xticks(range(-10, 11, 2))

plt.tight_layout()
fig.savefig(OUT_DIR / "fig_rv_event_study.png", dpi=100, bbox_inches='tight')
plt.close()
print("\nSaved: fig_rv_event_study.png")

# ---------------------------------------------------------------------------
# 6. Bar chart: pre/post premium
# ---------------------------------------------------------------------------
fig2, ax2 = plt.subplots(figsize=(10, 6), dpi=100)

x = np.arange(len(TICKERS))
width = 0.35

pre_premiums = [results[t]["pre_premium_pct"] for t in TICKERS]
post_premiums = [results[t]["post_premium_pct"] for t in TICKERS]

bars1 = ax2.bar(x - width/2, pre_premiums, width, label='Pre-earnings Premium (%)', color=['#76b900', '#555555', '#00a4ef'], alpha=0.85, edgecolor='black', linewidth=0.5)
bars2 = ax2.bar(x + width/2, post_premiums, width, label='Post-earnings Premium (%)', color=['#c8e000', '#999999', '#80d2f7'], alpha=0.85, edgecolor='black', linewidth=0.5)

# Significance stars
for i, ticker in enumerate(TICKERS):
    r = results[ticker]
    if r["significant_pre"]:
        ax2.text(x[i] - width/2, pre_premiums[i] + 0.5, '*', ha='center', fontsize=14, color='darkred')
    if r["significant_post"]:
        ax2.text(x[i] + width/2, post_premiums[i] + 0.5, '*', ha='center', fontsize=14, color='darkred')

ax2.axhline(0, color='black', linewidth=0.8)
ax2.set_xlabel("Ticker", fontsize=12)
ax2.set_ylabel("RV Premium vs Baseline (%)", fontsize=12)
ax2.set_title("Pre vs Post Earnings RV Premium over Baseline\n(* = p<0.05, paired t-test | 2024–2026)", fontsize=13)
ax2.set_xticks(x)
ax2.set_xticklabels(TICKERS, fontsize=12)
ax2.legend(fontsize=10)
ax2.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
fig2.savefig(OUT_DIR / "fig_premium_compare.png", dpi=100, bbox_inches='tight')
plt.close()
print("Saved: fig_premium_compare.png")

# ---------------------------------------------------------------------------
# 7. Save results JSON
# ---------------------------------------------------------------------------
output = {
    "experiment_id": "K1429",
    "title": "EAV Effect: Realized Volatility Around Earnings Announcements (NVDA, AAPL, MSFT)",
    "description": "Event-window study of 5-day rolling annualised RV patterns around earnings for NVDA, AAPL, MSFT (2024-2026). Paired t-tests vs baseline RV.",
    "metadata": {
        "tickers": TICKERS,
        "analysis_start": str(ANALYSIS_START.date()),
        "analysis_end": str(ANALYSIS_END.date()),
        "rv_window_days": RV_WINDOW,
        "pre_window": "T-5 to T-1",
        "post_window": "T+1 to T+5",
        "baseline_excl_window": f"±{BASELINE_EXCL} days around earnings",
        "test_method": "scipy.stats.ttest_rel (paired t-test vs baseline mean)",
        "significance_threshold": 0.05,
        "data_source": "yfinance daily adjusted close",
        "seed": 42,
        "nvda_earnings_dates": NVDA_EARNINGS,
        "aapl_earnings_dates": AAPL_EARNINGS,
        "msft_earnings_dates": MSFT_EARNINGS,
    },
    "results_by_ticker": results,
    "figures": [
        "fig_rv_event_study.png",
        "fig_premium_compare.png",
    ],
    "verdict": None,  # filled below
    "verdict_rationale": None,
}

# Determine verdict
nvda = results["NVDA"]
aapl = results["AAPL"]
msft = results["MSFT"]

sig_count = sum([
    nvda["significant_pre"], nvda["significant_post"],
    aapl["significant_pre"], aapl["significant_post"],
    msft["significant_pre"], msft["significant_post"],
])

if sig_count >= 4 and nvda["significant_pre"]:
    verdict = "PASS"
    rationale = "NVDA pre-earnings premium statistically significant (p<0.05) + majority of tests significant across 3 tickers."
elif sig_count >= 2:
    verdict = "CONDITIONAL_PASS"
    rationale = f"{sig_count}/6 tests significant. NVDA pre: p={nvda['p_pre']:.4f}, post: p={nvda['p_post']:.4f}."
else:
    verdict = "MIXED"
    rationale = f"Only {sig_count}/6 tests significant. EAV signal present but weak."

output["verdict"] = verdict
output["verdict_rationale"] = rationale

print(f"\nVerdict: {verdict}")
print(f"Rationale: {rationale}")

with open(OUT_DIR / "k1429_results.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print("Saved: k1429_results.json")

print("\nDONE")
