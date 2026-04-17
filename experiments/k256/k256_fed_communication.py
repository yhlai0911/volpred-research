"""
K256: Fed Communication Semantic Analysis — Does Fed Language Predict Bond Volatility?
=====================================================================================

Hypothesis:
  Gemini R9#5 suggested quantifying "semantic ambiguity" of Fed communications.
  K207 showed VIX is NOT sufficient for bonds (TLT).
  Can FOMC meeting dynamics fill this gap?

Method (PROXY analysis — no actual NLP on Fed text):
  1. FOMC surprise proxy: |VIX change| on FOMC day (large change = surprising statement)
  2. Pre-FOMC drift: SPY return in 3 days before FOMC (Lucca & Moench 2015)
  3. Post-FOMC vol: TLT realized vol in 5 days after vs 5 days before FOMC
  4. "Uncertainty resolution": does VIX drop AFTER FOMC? (uncertainty resolved)
  5. Predictive test: does pre-FOMC VIX level predict post-FOMC TLT vol?
  6. Strategy backtest: reduce TLT position 3 days before FOMC, restore 3 days after

Data: TLT, SPY, ^VIX daily from yfinance (2003-2026).
FOMC dates: constructed from known 8-meetings/year schedule.

Limitations (must be stated clearly):
  - This is a PROXY analysis, NOT actual NLP on Fed text
  - VIX change is a noisy proxy for "semantic surprise"
  - Pre-FOMC drift captures market expectations, not Fed language per se
  - Real semantic analysis would require FOMC minutes/statements text corpus
  - FOMC dates are reconstructed, minor inaccuracies possible for early years
  - Results reflect VIX-FOMC-TLT dynamics, not direct language→vol channel

[提出: Gemini R9#5, 執行: Claude]
"""

import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2003-01-01"  # TLT inception ~2002-07
DATA_END = "2026-12-31"
ASSETS = {"TLT": "TLT", "SPY": "SPY", "VIX": "^VIX"}
PRE_FOMC_DAYS = 3    # Lucca & Moench (2015) pre-FOMC drift window
POST_FOMC_DAYS = 5   # Post-FOMC volatility measurement window

print("=" * 80)
print("K256: FED COMMUNICATION SEMANTIC ANALYSIS")
print("Does FOMC meeting dynamics predict bond (TLT) volatility?")
print("PROXY ANALYSIS — no actual NLP on Fed text")
print("=" * 80)

# ============================================================
# FOMC MEETING DATES (reconstructed schedule)
# 8 scheduled meetings per year, roughly every 6-7 weeks
# Source: Federal Reserve historical calendar
# ============================================================
FOMC_DATES = [
    # 2003
    "2003-01-29", "2003-03-18", "2003-05-06", "2003-06-25",
    "2003-08-12", "2003-09-16", "2003-10-28", "2003-12-09",
    # 2004
    "2004-01-28", "2004-03-16", "2004-05-04", "2004-06-30",
    "2004-08-10", "2004-09-21", "2004-11-10", "2004-12-14",
    # 2005
    "2005-02-02", "2005-03-22", "2005-05-03", "2005-06-30",
    "2005-08-09", "2005-09-20", "2005-11-01", "2005-12-13",
    # 2006
    "2006-01-31", "2006-03-28", "2006-05-10", "2006-06-29",
    "2006-08-08", "2006-09-20", "2006-10-25", "2006-12-12",
    # 2007
    "2007-01-31", "2007-03-21", "2007-05-09", "2007-06-28",
    "2007-08-07", "2007-09-18", "2007-10-31", "2007-12-11",
    # 2008
    "2008-01-30", "2008-03-18", "2008-04-30", "2008-06-25",
    "2008-08-05", "2008-09-16", "2008-10-29", "2008-12-16",
    # 2009
    "2009-01-28", "2009-03-18", "2009-04-29", "2009-06-24",
    "2009-08-12", "2009-09-23", "2009-11-04", "2009-12-16",
    # 2010
    "2010-01-27", "2010-03-16", "2010-04-28", "2010-06-23",
    "2010-08-10", "2010-09-21", "2010-11-03", "2010-12-14",
    # 2011
    "2011-01-26", "2011-03-15", "2011-04-27", "2011-06-22",
    "2011-08-09", "2011-09-21", "2011-11-02", "2011-12-13",
    # 2012
    "2012-01-25", "2012-03-13", "2012-04-25", "2012-06-20",
    "2012-08-01", "2012-09-13", "2012-10-24", "2012-12-12",
    # 2013
    "2013-01-30", "2013-03-20", "2013-05-01", "2013-06-19",
    "2013-07-31", "2013-09-18", "2013-10-30", "2013-12-18",
    # 2014
    "2014-01-29", "2014-03-19", "2014-05-01", "2014-06-18",
    "2014-07-30", "2014-09-17", "2014-10-29", "2014-12-17",
    # 2015
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
    "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    # 2016
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
    "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",  # extra emergency meeting
    "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    # 2026 (projected)
    "2026-01-28", "2026-03-18",
]

fomc_dates = pd.to_datetime(FOMC_DATES)

# ============================================================
# DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data from yfinance...")

data = {}
for name, ticker in ASSETS.items():
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df
    print(f"  {name} ({ticker}): {len(df)} days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Build aligned DataFrame
prices = pd.DataFrame({
    "TLT": data["TLT"]["Close"],
    "SPY": data["SPY"]["Close"],
    "VIX": data["VIX"]["Close"],
}).dropna()

# Compute returns
prices["TLT_ret"] = np.log(prices["TLT"] / prices["TLT"].shift(1))
prices["SPY_ret"] = np.log(prices["SPY"] / prices["SPY"].shift(1))
prices["VIX_chg"] = prices["VIX"] - prices["VIX"].shift(1)
prices["VIX_pct_chg"] = prices["VIX_chg"] / prices["VIX"].shift(1)
prices["TLT_rv5"] = prices["TLT_ret"].rolling(5).std() * np.sqrt(252)  # annualized
prices["TLT_rv22"] = prices["TLT_ret"].rolling(22).std() * np.sqrt(252)
prices = prices.dropna()

print(f"\n  Aligned dataset: {len(prices)} days")
print(f"  Period: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Filter FOMC dates that fall on trading days (or next trading day)
valid_fomc = []
for d in fomc_dates:
    if d in prices.index:
        valid_fomc.append(d)
    else:
        # Find next trading day
        next_days = prices.index[prices.index > d]
        if len(next_days) > 0:
            valid_fomc.append(next_days[0])

valid_fomc = sorted(set(valid_fomc))
valid_fomc = [d for d in valid_fomc if d in prices.index]
print(f"  Valid FOMC dates matched to trading days: {len(valid_fomc)}")

# ============================================================
# ANALYSIS 1: FOMC SURPRISE PROXY
# |VIX change| on FOMC day as proxy for surprise
# ============================================================
print("\n" + "=" * 80)
print("[2] FOMC SURPRISE PROXY: |VIX change| on FOMC day")
print("=" * 80)

fomc_stats = []
for d in valid_fomc:
    if d not in prices.index:
        continue
    idx = prices.index.get_loc(d)
    if idx < 1:
        continue
    row = {
        "date": d,
        "vix_level": prices.iloc[idx]["VIX"],
        "vix_chg": prices.iloc[idx]["VIX_chg"],
        "vix_abs_chg": abs(prices.iloc[idx]["VIX_chg"]),
        "vix_pct_chg": prices.iloc[idx]["VIX_pct_chg"],
        "tlt_ret": prices.iloc[idx]["TLT_ret"],
        "spy_ret": prices.iloc[idx]["SPY_ret"],
    }
    fomc_stats.append(row)

fomc_df = pd.DataFrame(fomc_stats)
fomc_df["year"] = fomc_df["date"].dt.year

print(f"\n  FOMC days with complete data: {len(fomc_df)}")
print(f"\n  VIX change on FOMC days:")
print(f"    Mean |ΔVIX|: {fomc_df['vix_abs_chg'].mean():.3f}")
print(f"    Median |ΔVIX|: {fomc_df['vix_abs_chg'].median():.3f}")
print(f"    Mean ΔVIX: {fomc_df['vix_chg'].mean():.3f}")
print(f"    Std ΔVIX: {fomc_df['vix_chg'].std():.3f}")

# Compare FOMC days vs non-FOMC days
non_fomc_mask = ~prices.index.isin(fomc_df["date"].values)
non_fomc_vix_abs = prices.loc[non_fomc_mask, "VIX_chg"].abs()
fomc_vix_abs = fomc_df["vix_abs_chg"]

t_stat, p_val = stats.ttest_ind(fomc_vix_abs, non_fomc_vix_abs)
print(f"\n  FOMC vs Non-FOMC |ΔVIX|:")
print(f"    FOMC mean: {fomc_vix_abs.mean():.3f} (N={len(fomc_vix_abs)})")
print(f"    Non-FOMC mean: {non_fomc_vix_abs.mean():.3f} (N={len(non_fomc_vix_abs)})")
print(f"    t-stat: {t_stat:.3f}, p-value: {p_val:.4f}")

# TLT vol on FOMC days vs non-FOMC days
fomc_tlt_absret = fomc_df["tlt_ret"].abs()
non_fomc_tlt_absret = prices.loc[non_fomc_mask, "TLT_ret"].abs()

t_stat2, p_val2 = stats.ttest_ind(fomc_tlt_absret, non_fomc_tlt_absret)
print(f"\n  FOMC vs Non-FOMC |TLT return|:")
print(f"    FOMC mean: {fomc_tlt_absret.mean()*100:.3f}%")
print(f"    Non-FOMC mean: {non_fomc_tlt_absret.mean()*100:.3f}%")
print(f"    t-stat: {t_stat2:.3f}, p-value: {p_val2:.4f}")

# ============================================================
# ANALYSIS 2: PRE-FOMC DRIFT (Lucca & Moench 2015)
# SPY cumulative return in 3 days before FOMC
# ============================================================
print("\n" + "=" * 80)
print("[3] PRE-FOMC DRIFT (Lucca & Moench 2015)")
print("=" * 80)

pre_fomc_returns = []
for d in valid_fomc:
    if d not in prices.index:
        continue
    idx = prices.index.get_loc(d)
    if idx < PRE_FOMC_DAYS:
        continue
    # Cumulative SPY return in PRE_FOMC_DAYS before FOMC
    pre_spy = prices.iloc[idx - PRE_FOMC_DAYS:idx]["SPY_ret"].sum()
    pre_tlt = prices.iloc[idx - PRE_FOMC_DAYS:idx]["TLT_ret"].sum()
    pre_vix = prices.iloc[idx - PRE_FOMC_DAYS]["VIX"] - prices.iloc[idx - PRE_FOMC_DAYS - 1]["VIX"] if idx > PRE_FOMC_DAYS else np.nan
    pre_vix_level = prices.iloc[idx - 1]["VIX"]  # VIX level day before FOMC
    pre_fomc_returns.append({
        "date": d,
        "pre_spy_ret": pre_spy,
        "pre_tlt_ret": pre_tlt,
        "pre_vix_level": pre_vix_level,
        "fomc_spy_ret": prices.iloc[idx]["SPY_ret"],
        "fomc_tlt_ret": prices.iloc[idx]["TLT_ret"],
        "fomc_vix_chg": prices.iloc[idx]["VIX_chg"],
    })

pre_df = pd.DataFrame(pre_fomc_returns)

# Pre-FOMC drift test
pre_spy_mean = pre_df["pre_spy_ret"].mean()
pre_spy_se = pre_df["pre_spy_ret"].std() / np.sqrt(len(pre_df))
pre_spy_t = pre_spy_mean / pre_spy_se

print(f"\n  Pre-FOMC SPY drift ({PRE_FOMC_DAYS} days before):")
print(f"    Mean cumulative return: {pre_spy_mean*100:.3f}%")
print(f"    t-stat: {pre_spy_t:.3f} (p={2*(1-stats.t.cdf(abs(pre_spy_t), len(pre_df)-1)):.4f})")
print(f"    N meetings: {len(pre_df)}")

# Pre-FOMC TLT behavior
pre_tlt_mean = pre_df["pre_tlt_ret"].mean()
pre_tlt_se = pre_df["pre_tlt_ret"].std() / np.sqrt(len(pre_df))
pre_tlt_t = pre_tlt_mean / pre_tlt_se

print(f"\n  Pre-FOMC TLT drift ({PRE_FOMC_DAYS} days before):")
print(f"    Mean cumulative return: {pre_tlt_mean*100:.3f}%")
print(f"    t-stat: {pre_tlt_t:.3f} (p={2*(1-stats.t.cdf(abs(pre_tlt_t), len(pre_df)-1)):.4f})")

# ============================================================
# ANALYSIS 3: POST-FOMC VOLATILITY CHANGE
# TLT realized vol in 5 days after FOMC vs 5 days before
# ============================================================
print("\n" + "=" * 80)
print("[4] POST-FOMC VOLATILITY RESOLUTION")
print("    TLT vol: 5 days after vs 5 days before FOMC")
print("=" * 80)

vol_changes = []
for d in valid_fomc:
    if d not in prices.index:
        continue
    idx = prices.index.get_loc(d)
    if idx < POST_FOMC_DAYS or idx + POST_FOMC_DAYS >= len(prices):
        continue

    pre_vol = prices.iloc[idx - POST_FOMC_DAYS:idx]["TLT_ret"].std() * np.sqrt(252)
    post_vol = prices.iloc[idx + 1:idx + 1 + POST_FOMC_DAYS]["TLT_ret"].std() * np.sqrt(252)

    pre_vix = prices.iloc[idx - 1]["VIX"]
    post_vix = prices.iloc[min(idx + POST_FOMC_DAYS, len(prices) - 1)]["VIX"]
    fomc_vix = prices.iloc[idx]["VIX"]

    vol_changes.append({
        "date": d,
        "pre_tlt_vol": pre_vol,
        "post_tlt_vol": post_vol,
        "vol_change": post_vol - pre_vol,
        "vol_ratio": post_vol / pre_vol if pre_vol > 0 else np.nan,
        "pre_vix": pre_vix,
        "fomc_vix": fomc_vix,
        "post_vix": post_vix,
        "vix_resolution": fomc_vix - post_vix,  # positive = uncertainty resolved
    })

vol_df = pd.DataFrame(vol_changes)
vol_df = vol_df.dropna()

print(f"\n  N meetings with pre/post vol data: {len(vol_df)}")

# Does TLT vol decrease after FOMC? (uncertainty resolution)
vol_chg_mean = vol_df["vol_change"].mean()
vol_chg_se = vol_df["vol_change"].std() / np.sqrt(len(vol_df))
vol_chg_t = vol_chg_mean / vol_chg_se

print(f"\n  Post-FOMC TLT vol change:")
print(f"    Mean Δvol (post - pre): {vol_chg_mean*100:.2f}% ann.")
print(f"    t-stat: {vol_chg_t:.3f} (p={2*(1-stats.t.cdf(abs(vol_chg_t), len(vol_df)-1)):.4f})")
print(f"    % meetings where vol DECREASES: {(vol_df['vol_change'] < 0).mean()*100:.1f}%")

# Vol ratio
vol_ratio_mean = vol_df["vol_ratio"].mean()
print(f"    Mean post/pre vol ratio: {vol_ratio_mean:.3f}")

# ============================================================
# ANALYSIS 4: VIX UNCERTAINTY RESOLUTION
# Does VIX drop after FOMC? (uncertainty resolved)
# ============================================================
print("\n" + "=" * 80)
print("[5] VIX UNCERTAINTY RESOLUTION")
print("    Does VIX drop after FOMC statements?")
print("=" * 80)

vix_resolution_mean = vol_df["vix_resolution"].mean()
vix_resolution_se = vol_df["vix_resolution"].std() / np.sqrt(len(vol_df))
vix_resolution_t = vix_resolution_mean / vix_resolution_se

print(f"\n  VIX resolution (FOMC_day - post_5d):")
print(f"    Mean: {vix_resolution_mean:.3f} pts")
print(f"    t-stat: {vix_resolution_t:.3f} (p={2*(1-stats.t.cdf(abs(vix_resolution_t), len(vol_df)-1)):.4f})")
print(f"    % meetings where VIX DROPS after: {(vol_df['vix_resolution'] > 0).mean()*100:.1f}%")

# By regime: high VIX vs low VIX
vix_median = vol_df["pre_vix"].median()
high_vix = vol_df[vol_df["pre_vix"] > vix_median]
low_vix = vol_df[vol_df["pre_vix"] <= vix_median]

print(f"\n  By VIX regime (median VIX = {vix_median:.1f}):")
print(f"    High VIX (>{vix_median:.0f}): mean resolution = {high_vix['vix_resolution'].mean():.3f}, "
      f"vol drop = {(high_vix['vol_change'] < 0).mean()*100:.0f}% of meetings")
print(f"    Low VIX  (≤{vix_median:.0f}): mean resolution = {low_vix['vix_resolution'].mean():.3f}, "
      f"vol drop = {(low_vix['vol_change'] < 0).mean()*100:.0f}% of meetings")

# ============================================================
# ANALYSIS 5: PREDICTIVE TEST
# Does pre-FOMC VIX level predict post-FOMC TLT vol?
# ============================================================
print("\n" + "=" * 80)
print("[6] PREDICTIVE TEST: Pre-FOMC VIX → Post-FOMC TLT vol")
print("=" * 80)

# Merge pre_df and vol_df on date
merged = pd.merge(pre_df, vol_df, on="date", how="inner", suffixes=("_pre", "_vol"))

# Test 1: Pre-FOMC VIX level → post-FOMC TLT vol
x = merged["pre_vix_level"].values
y = merged["post_tlt_vol"].values
mask = np.isfinite(x) & np.isfinite(y)
x, y = x[mask], y[mask]

slope, intercept, r_value, p_value, se = stats.linregress(x, y)
print(f"\n  Test 1: VIX level (T-1) → Post-FOMC TLT vol")
print(f"    β = {slope:.5f} (se={se:.5f})")
print(f"    t-stat = {slope/se:.3f}, p = {p_value:.4f}")
print(f"    R² = {r_value**2:.4f}")
print(f"    N = {len(x)}")

# Test 2: |FOMC VIX change| → post-FOMC TLT vol
x2 = merged["fomc_vix_chg"].abs().values
y2 = merged["post_tlt_vol"].values
mask2 = np.isfinite(x2) & np.isfinite(y2)
x2, y2 = x2[mask2], y2[mask2]

slope2, intercept2, r2, p2, se2 = stats.linregress(x2, y2)
print(f"\n  Test 2: |ΔVIX on FOMC day| → Post-FOMC TLT vol")
print(f"    β = {slope2:.5f} (se={se2:.5f})")
print(f"    t-stat = {slope2/se2:.3f}, p = {p2:.4f}")
print(f"    R² = {r2**2:.4f}")

# Test 3: Pre-FOMC SPY drift → post-FOMC TLT vol
x3 = merged["pre_spy_ret"].values
y3 = merged["post_tlt_vol"].values
mask3 = np.isfinite(x3) & np.isfinite(y3)
x3, y3 = x3[mask3], y3[mask3]

slope3, intercept3, r3, p3, se3 = stats.linregress(x3, y3)
print(f"\n  Test 3: Pre-FOMC SPY drift → Post-FOMC TLT vol")
print(f"    β = {slope3:.5f} (se={se3:.5f})")
print(f"    t-stat = {slope3/se3:.3f}, p = {p3:.4f}")
print(f"    R² = {r3**2:.4f}")

# Test 4: Pre-FOMC VIX level → post/pre vol ratio
y4 = merged["vol_ratio"].values
x4 = merged["pre_vix_level"].values
mask4 = np.isfinite(x4) & np.isfinite(y4)
x4, y4 = x4[mask4], y4[mask4]

slope4, intercept4, r4, p4, se4 = stats.linregress(x4, y4)
print(f"\n  Test 4: Pre-FOMC VIX → Post/Pre vol ratio")
print(f"    β = {slope4:.5f} (se={se4:.5f})")
print(f"    t-stat = {slope4/se4:.3f}, p = {p4:.4f}")
print(f"    R² = {r4**2:.4f}")

# ============================================================
# ANALYSIS 6: "SURPRISE" QUARTILE ANALYSIS
# Sort FOMC meetings by |VIX change| into quartiles
# ============================================================
print("\n" + "=" * 80)
print("[7] FOMC SURPRISE QUARTILE ANALYSIS")
print("    Sort by |ΔVIX| into quartiles → TLT vol behavior")
print("=" * 80)

merged["vix_abs_chg"] = merged["fomc_vix_chg"].abs()
merged["surprise_quartile"] = pd.qcut(merged["vix_abs_chg"], q=4, labels=["Q1(low)", "Q2", "Q3", "Q4(high)"])

print(f"\n  {'Quartile':<12} {'N':>4} {'Mean |ΔVIX|':>12} {'Post TLT vol':>14} {'Vol change':>12} {'Post SPY ret':>14}")
print(f"  {'-'*70}")
for q in ["Q1(low)", "Q2", "Q3", "Q4(high)"]:
    subset = merged[merged["surprise_quartile"] == q]
    print(f"  {q:<12} {len(subset):>4} {subset['vix_abs_chg'].mean():>12.3f} "
          f"{subset['post_tlt_vol'].mean()*100:>13.2f}% {subset['vol_change'].mean()*100:>11.2f}% "
          f"{subset['fomc_spy_ret'].mean()*100:>13.3f}%")

# Q4 vs Q1 test
q4 = merged[merged["surprise_quartile"] == "Q4(high)"]["post_tlt_vol"]
q1 = merged[merged["surprise_quartile"] == "Q1(low)"]["post_tlt_vol"]
t_q, p_q = stats.ttest_ind(q4, q1)
print(f"\n  Q4 vs Q1 TLT vol: t={t_q:.3f}, p={p_q:.4f}")

# ============================================================
# ANALYSIS 7: FOMC AVOIDANCE STRATEGY
# Reduce TLT position 3 days before FOMC, restore 3 days after
# ============================================================
print("\n" + "=" * 80)
print("[8] FOMC AVOIDANCE STRATEGY BACKTEST")
print("    Reduce TLT to 50% weight 3d before FOMC, restore 3d after")
print("=" * 80)

# Create FOMC proximity indicator
fomc_set = set(valid_fomc)
prices["fomc_proximity"] = 0
for d in valid_fomc:
    if d not in prices.index:
        continue
    idx = prices.index.get_loc(d)
    # Mark PRE_FOMC_DAYS before through POST_FOMC_DAYS after
    for offset in range(-PRE_FOMC_DAYS, POST_FOMC_DAYS + 1):
        target_idx = idx + offset
        if 0 <= target_idx < len(prices):
            prices.iloc[target_idx, prices.columns.get_loc("fomc_proximity")] = 1

# Strategy: Buy-and-hold TLT vs FOMC-aware TLT
prices["bah_tlt"] = prices["TLT_ret"]
prices["fomc_aware_tlt"] = prices["TLT_ret"].copy()
# During FOMC proximity, reduce position to 50%
fomc_mask = prices["fomc_proximity"] == 1
prices.loc[fomc_mask, "fomc_aware_tlt"] = prices.loc[fomc_mask, "TLT_ret"] * 0.5

# Calculate cumulative returns
prices["bah_cum"] = prices["bah_tlt"].cumsum()
prices["fomc_cum"] = prices["fomc_aware_tlt"].cumsum()

# Performance metrics
def calc_metrics(returns, name):
    """Calculate annualized performance metrics."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = returns.cumsum()
    running_max = cum.cummax()
    drawdown = cum - running_max
    mdd = drawdown.min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    return {
        "name": name,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
    }

bah_metrics = calc_metrics(prices["bah_tlt"], "Buy-and-Hold TLT")
fomc_metrics = calc_metrics(prices["fomc_aware_tlt"], "FOMC-Aware TLT (50%)")

print(f"\n  {'Strategy':<30} {'Ann. Ret':>10} {'Ann. Vol':>10} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8}")
print(f"  {'-'*76}")
for m in [bah_metrics, fomc_metrics]:
    print(f"  {m['name']:<30} {m['ann_ret']*100:>9.2f}% {m['ann_vol']*100:>9.2f}% "
          f"{m['sharpe']:>8.3f} {m['mdd']*100:>7.2f}% {m['calmar']:>8.3f}")

# Statistical test: is FOMC-aware better?
diff_ret = prices["fomc_aware_tlt"] - prices["bah_tlt"]
diff_mean = diff_ret.mean() * 252
diff_se = diff_ret.std() * np.sqrt(252) / np.sqrt(len(diff_ret) / 252)
diff_t = diff_mean / diff_se if diff_se > 0 else 0

print(f"\n  Strategy difference (FOMC-aware - BaH):")
print(f"    Ann. return diff: {diff_mean*100:.3f}%")
print(f"    t-stat: {diff_t:.3f}")

# What fraction of days are FOMC-proximity?
fomc_frac = fomc_mask.mean()
print(f"\n  FOMC proximity days: {fomc_mask.sum()} ({fomc_frac*100:.1f}% of all days)")

# ============================================================
# ANALYSIS 8: DECADE ANALYSIS
# Does the FOMC effect change over time?
# ============================================================
print("\n" + "=" * 80)
print("[9] DECADE ANALYSIS: FOMC effect stability")
print("=" * 80)

merged["decade"] = (merged["date"].dt.year // 5) * 5  # 5-year periods
print(f"\n  {'Period':<12} {'N':>4} {'Mean |ΔVIX|':>12} {'Post TLT vol':>14} {'VIX resolution':>16} {'Vol drops %':>12}")
print(f"  {'-'*72}")
for period in sorted(merged["decade"].unique()):
    subset = merged[merged["decade"] == period]
    yr_start = period
    yr_end = period + 4
    label = f"{yr_start}-{yr_end}"
    print(f"  {label:<12} {len(subset):>4} {subset['vix_abs_chg'].mean():>12.3f} "
          f"{subset['post_tlt_vol'].mean()*100:>13.2f}% "
          f"{subset['vix_resolution'].mean():>15.3f} "
          f"{(subset['vol_change'] < 0).mean()*100:>11.0f}%")

# ============================================================
# ANALYSIS 9: FOMC DAY VIX DIRECTION → TLT NEXT-WEEK RETURN
# ============================================================
print("\n" + "=" * 80)
print("[10] FOMC VIX DIRECTION → TLT NEXT-WEEK RETURN")
print("=" * 80)

nextweek_returns = []
for d in valid_fomc:
    if d not in prices.index:
        continue
    idx = prices.index.get_loc(d)
    if idx + POST_FOMC_DAYS >= len(prices):
        continue

    fomc_vix_dir = "DROP" if prices.iloc[idx]["VIX_chg"] < 0 else "RISE"
    next_tlt = prices.iloc[idx + 1:idx + 1 + POST_FOMC_DAYS]["TLT_ret"].sum()
    next_spy = prices.iloc[idx + 1:idx + 1 + POST_FOMC_DAYS]["SPY_ret"].sum()

    nextweek_returns.append({
        "date": d,
        "vix_direction": fomc_vix_dir,
        "next_tlt_5d": next_tlt,
        "next_spy_5d": next_spy,
        "vix_chg": prices.iloc[idx]["VIX_chg"],
    })

nw_df = pd.DataFrame(nextweek_returns)

drop_tlt = nw_df[nw_df["vix_direction"] == "DROP"]["next_tlt_5d"]
rise_tlt = nw_df[nw_df["vix_direction"] == "RISE"]["next_tlt_5d"]

print(f"\n  When VIX DROPS on FOMC day (N={len(drop_tlt)}):")
print(f"    TLT next 5d: {drop_tlt.mean()*100:.3f}% (t={drop_tlt.mean()/drop_tlt.std()*np.sqrt(len(drop_tlt)):.2f})")

print(f"\n  When VIX RISES on FOMC day (N={len(rise_tlt)}):")
print(f"    TLT next 5d: {rise_tlt.mean()*100:.3f}% (t={rise_tlt.mean()/rise_tlt.std()*np.sqrt(len(rise_tlt)):.2f})")

t_nw, p_nw = stats.ttest_ind(drop_tlt, rise_tlt)
print(f"\n  Difference test: t={t_nw:.3f}, p={p_nw:.4f}")

# ============================================================
# ANALYSIS 10: CORRELATION MATRIX — FOMC VARIABLES
# ============================================================
print("\n" + "=" * 80)
print("[11] CORRELATION MATRIX: FOMC PROXY VARIABLES")
print("=" * 80)

corr_vars = merged[["pre_vix_level", "vix_abs_chg", "pre_spy_ret", "pre_tlt_ret",
                      "post_tlt_vol", "vol_change", "vix_resolution"]].copy()
corr_vars.columns = ["VIX_pre", "|ΔVIX|", "SPY_drift", "TLT_drift",
                      "TLT_vol_post", "ΔVol", "VIX_resoln"]

corr_matrix = corr_vars.corr()
print(f"\n  Correlation matrix (N={len(corr_vars)}):")
print(f"\n  {'':>14}", end="")
for c in corr_matrix.columns:
    print(f"{c:>12}", end="")
print()
for r in corr_matrix.index:
    print(f"  {r:>14}", end="")
    for c in corr_matrix.columns:
        val = corr_matrix.loc[r, c]
        print(f"{val:>12.3f}", end="")
    print()

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY: K256 Fed Communication Proxy Analysis")
print("=" * 80)

results = {
    "experiment": "K256",
    "title": "Fed Communication Semantic Analysis — FOMC Proxy",
    "proposed_by": "Gemini R9#5",
    "data_source": "yfinance (TLT, SPY, ^VIX)",
    "period": f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    "n_fomc_meetings": len(fomc_df),
    "proxy_method": "VIX change on FOMC day as surprise proxy (NOT actual NLP)",
    "findings": {},
    "limitations": [
        "PROXY analysis only — no actual NLP on Fed statement text",
        "VIX change is a noisy proxy for semantic surprise",
        "Pre-FOMC drift captures market expectations, not Fed language",
        "FOMC dates are reconstructed from known schedules (minor inaccuracies possible)",
        "Results reflect VIX-FOMC-TLT dynamics, not direct language→vol channel",
        "Real semantic analysis would require FOMC minutes text corpus + NLP pipeline",
    ],
}

# Finding 1: FOMC vs non-FOMC VIX
results["findings"]["fomc_vix_surprise"] = {
    "fomc_mean_abs_vix_chg": round(float(fomc_vix_abs.mean()), 3),
    "non_fomc_mean_abs_vix_chg": round(float(non_fomc_vix_abs.mean()), 3),
    "t_stat": round(float(t_stat), 3),
    "p_value": round(float(p_val), 4),
    "significant": bool(p_val < 0.05),
}

# Finding 2: TLT vol on FOMC days
results["findings"]["fomc_tlt_vol"] = {
    "fomc_mean_abs_tlt_ret": round(float(fomc_tlt_absret.mean()), 5),
    "non_fomc_mean_abs_tlt_ret": round(float(non_fomc_tlt_absret.mean()), 5),
    "t_stat": round(float(t_stat2), 3),
    "p_value": round(float(p_val2), 4),
    "significant": bool(p_val2 < 0.05),
}

# Finding 3: Pre-FOMC drift
results["findings"]["pre_fomc_drift"] = {
    "spy_mean_return_pct": round(float(pre_spy_mean * 100), 3),
    "spy_t_stat": round(float(pre_spy_t), 3),
    "tlt_mean_return_pct": round(float(pre_tlt_mean * 100), 3),
    "tlt_t_stat": round(float(pre_tlt_t), 3),
}

# Finding 4: Post-FOMC vol change
results["findings"]["post_fomc_vol_change"] = {
    "mean_vol_change_ann_pct": round(float(vol_chg_mean * 100), 2),
    "t_stat": round(float(vol_chg_t), 3),
    "pct_meetings_vol_drops": round(float((vol_df['vol_change'] < 0).mean() * 100), 1),
    "mean_vol_ratio": round(float(vol_ratio_mean), 3),
}

# Finding 5: VIX resolution
results["findings"]["vix_resolution"] = {
    "mean_vix_drop_pts": round(float(vix_resolution_mean), 3),
    "t_stat": round(float(vix_resolution_t), 3),
    "pct_meetings_vix_drops": round(float((vol_df['vix_resolution'] > 0).mean() * 100), 1),
}

# Finding 6: Predictive tests
results["findings"]["predictive_tests"] = {
    "vix_level_to_tlt_vol": {
        "beta": round(float(slope), 5),
        "t_stat": round(float(slope / se), 3),
        "R2": round(float(r_value ** 2), 4),
        "p_value": round(float(p_value), 4),
    },
    "abs_vix_chg_to_tlt_vol": {
        "beta": round(float(slope2), 5),
        "t_stat": round(float(slope2 / se2), 3),
        "R2": round(float(r2 ** 2), 4),
        "p_value": round(float(p2), 4),
    },
    "spy_drift_to_tlt_vol": {
        "beta": round(float(slope3), 5),
        "t_stat": round(float(slope3 / se3), 3),
        "R2": round(float(r3 ** 2), 4),
        "p_value": round(float(p3), 4),
    },
}

# Finding 7: Strategy backtest
results["findings"]["fomc_avoidance_strategy"] = {
    "bah_sharpe": round(float(bah_metrics["sharpe"]), 3),
    "bah_mdd_pct": round(float(bah_metrics["mdd"] * 100), 2),
    "fomc_aware_sharpe": round(float(fomc_metrics["sharpe"]), 3),
    "fomc_aware_mdd_pct": round(float(fomc_metrics["mdd"] * 100), 2),
    "return_diff_ann_pct": round(float(diff_mean * 100), 3),
    "diff_t_stat": round(float(diff_t), 3),
    "fomc_proximity_pct": round(float(fomc_frac * 100), 1),
}

# Print summary
print(f"""
Key Findings:

1. FOMC SURPRISE (VIX proxy):
   - |ΔVIX| on FOMC days: {results['findings']['fomc_vix_surprise']['fomc_mean_abs_vix_chg']:.3f} vs non-FOMC: {results['findings']['fomc_vix_surprise']['non_fomc_mean_abs_vix_chg']:.3f}
   - t={results['findings']['fomc_vix_surprise']['t_stat']:.3f}, p={results['findings']['fomc_vix_surprise']['p_value']:.4f}
   - {'*** SIGNIFICANT: FOMC days have larger VIX moves' if results['findings']['fomc_vix_surprise']['significant'] else 'Not significant'}

2. TLT VOLATILITY ON FOMC DAYS:
   - FOMC |TLT ret|: {results['findings']['fomc_tlt_vol']['fomc_mean_abs_tlt_ret']*100:.3f}% vs non-FOMC: {results['findings']['fomc_tlt_vol']['non_fomc_mean_abs_tlt_ret']*100:.3f}%
   - t={results['findings']['fomc_tlt_vol']['t_stat']:.3f}, p={results['findings']['fomc_tlt_vol']['p_value']:.4f}
   - {'*** SIGNIFICANT: TLT is more volatile on FOMC days' if results['findings']['fomc_tlt_vol']['significant'] else 'Not significant'}

3. PRE-FOMC DRIFT:
   - SPY 3-day drift: {results['findings']['pre_fomc_drift']['spy_mean_return_pct']:.3f}% (t={results['findings']['pre_fomc_drift']['spy_t_stat']:.3f})
   - TLT 3-day drift: {results['findings']['pre_fomc_drift']['tlt_mean_return_pct']:.3f}% (t={results['findings']['pre_fomc_drift']['tlt_t_stat']:.3f})

4. POST-FOMC VOLATILITY:
   - Mean vol change: {results['findings']['post_fomc_vol_change']['mean_vol_change_ann_pct']:.2f}% ann.
   - Vol drops in {results['findings']['post_fomc_vol_change']['pct_meetings_vol_drops']:.0f}% of meetings
   - Mean post/pre ratio: {results['findings']['post_fomc_vol_change']['mean_vol_ratio']:.3f}

5. VIX RESOLUTION:
   - Mean VIX drop after FOMC: {results['findings']['vix_resolution']['mean_vix_drop_pts']:.3f} pts (t={results['findings']['vix_resolution']['t_stat']:.3f})
   - VIX drops in {results['findings']['vix_resolution']['pct_meetings_vix_drops']:.0f}% of meetings

6. PREDICTIVE POWER:
   - VIX level → post-FOMC TLT vol: R²={results['findings']['predictive_tests']['vix_level_to_tlt_vol']['R2']:.4f} (t={results['findings']['predictive_tests']['vix_level_to_tlt_vol']['t_stat']:.3f})
   - |ΔVIX| → post-FOMC TLT vol: R²={results['findings']['predictive_tests']['abs_vix_chg_to_tlt_vol']['R2']:.4f} (t={results['findings']['predictive_tests']['abs_vix_chg_to_tlt_vol']['t_stat']:.3f})
   - SPY drift → post-FOMC TLT vol: R²={results['findings']['predictive_tests']['spy_drift_to_tlt_vol']['R2']:.4f} (t={results['findings']['predictive_tests']['spy_drift_to_tlt_vol']['t_stat']:.3f})

7. FOMC AVOIDANCE STRATEGY:
   - Buy-and-hold TLT Sharpe: {results['findings']['fomc_avoidance_strategy']['bah_sharpe']:.3f}
   - FOMC-aware (50%) Sharpe: {results['findings']['fomc_avoidance_strategy']['fomc_aware_sharpe']:.3f}
   - Return difference: {results['findings']['fomc_avoidance_strategy']['return_diff_ann_pct']:.3f}% ann. (t={results['findings']['fomc_avoidance_strategy']['diff_t_stat']:.3f})

LIMITATIONS:
  ⚠️ This is a PROXY analysis — NOT actual NLP on Fed statement text
  ⚠️ VIX change is a noisy proxy for "semantic surprise"
  ⚠️ Real semantic analysis would require FOMC minutes text data + NLP pipeline
  ⚠️ Results reflect VIX-FOMC-TLT dynamics, not direct language→vol channel
  ⚠️ FOMC dates reconstructed from known schedule (minor inaccuracies possible)
""")

# Save results
output_path = PROJECT_ROOT / "experiments" / "k256_fed_communication_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to: {output_path}")

print("\n" + "=" * 80)
print("K256 COMPLETE")
print("=" * 80)
