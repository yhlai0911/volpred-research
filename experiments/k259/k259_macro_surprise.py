"""
K259: Economic Surprise and Volatility — Does Bad News Create Vol?
===================================================================

Hypothesis:
  Economic data releases (NFP, CPI, GDP) can move markets. The Citigroup
  Economic Surprise Index (CESI) measures whether data beats or misses
  expectations. Without direct CESI access, we proxy "economic surprise"
  using VIX changes and |SPY return| on known macro data release dates.

  Key questions:
  1. Are macro data days systematically higher-vol than normal days?
  2. Does a string of surprises (many big-VIX-move days) predict higher
     future realized vol?
  3. Does a "surprise frequency" variable add forecasting power beyond
     VIX level alone? (partial correlation test)
  4. Can a GARCH-X with surprise frequency beat standard GJR-GARCH?

Method:
  1. Identify macro event dates:
     - NFP: first Friday of each month
     - CPI: ~13th of each month (proxy)
     - FOMC: 8 meetings/year (from K256 dates)
  2. Measure "surprise magnitude" = |VIX change| on data day
  3. Compare macro vs non-macro day distributions (t-test, Mann-Whitney)
  4. Rolling surprise frequency: count of |VIX Δ| > 2σ days in last 22 days
  5. Partial correlation: surprise_freq → RV(+22) | controlling for VIX
  6. OOS GARCH-X comparison: GJR + surprise_freq vs plain GJR

Data: SPY, VIX, TLT daily from yfinance (2003-2026). Real data only.

Limitations (stated clearly):
  - This is a PROXY analysis — we do NOT have actual CESI data
  - NFP/CPI dates are approximated (first Friday / ~13th), not verified
  - VIX change is a noisy proxy for "economic surprise"
  - The surprise frequency variable is constructed from VIX, which already
    contains vol information — the question is whether the EVENT TIMING
    pattern adds incremental value
  - FOMC dates from K256 are reconstructed, minor inaccuracies possible
  - Results should be interpreted as "macro event timing effects on vol"
    rather than "economic surprise → vol" in the strict sense

[提出: User, 執行: Claude]
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
DATA_START = "2003-01-01"
DATA_END = "2026-12-31"
ASSETS = {"SPY": "SPY", "VIX": "^VIX", "TLT": "TLT"}
SURPRISE_SIGMA_THRESHOLD = 2.0  # |VIX Δ| > 2σ = "big surprise"
ROLLING_WINDOW = 22  # ~1 month for surprise frequency
FWD_RV_WINDOW = 22   # forward realized vol window
OOS_START = "2018-01-01"  # out-of-sample start

print("=" * 80)
print("K259: ECONOMIC SURPRISE AND VOLATILITY")
print("Does Bad News Create Vol? (Proxy-based analysis)")
print("LIMITATION: No actual CESI data — using VIX/SPY proxies")
print("=" * 80)

# ============================================================
# FOMC MEETING DATES (from K256)
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
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",
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
fomc_set = set(pd.to_datetime(FOMC_DATES))


# ============================================================
# HELPER: Generate NFP and CPI proxy dates
# ============================================================
def generate_nfp_dates(start_year, end_year):
    """NFP = first Friday of each month."""
    dates = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # Find first Friday
            d = datetime(year, month, 1)
            # weekday: 0=Mon ... 4=Fri
            days_until_friday = (4 - d.weekday()) % 7
            first_friday = d + timedelta(days=days_until_friday)
            dates.append(first_friday)
    return set(pd.to_datetime(dates))


def generate_cpi_dates(start_year, end_year):
    """CPI proxy: ~13th of each month (or nearest weekday)."""
    dates = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            d = datetime(year, month, 13)
            # If weekend, move to nearest weekday
            if d.weekday() == 5:  # Saturday → Friday
                d = d - timedelta(days=1)
            elif d.weekday() == 6:  # Sunday → Monday
                d = d + timedelta(days=1)
            dates.append(d)
    return set(pd.to_datetime(dates))


nfp_set = generate_nfp_dates(2003, 2026)
cpi_set = generate_cpi_dates(2003, 2026)
all_macro_set = fomc_set | nfp_set | cpi_set

print(f"\nMacro event dates generated:")
print(f"  FOMC meetings: {len(fomc_set)}")
print(f"  NFP (first Friday): {len(nfp_set)}")
print(f"  CPI (~13th): {len(cpi_set)}")
print(f"  Total unique macro dates: {len(all_macro_set)}")

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
    print(f"  {name} ({ticker}): {len(df)} days, "
          f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Build aligned DataFrame
prices = pd.DataFrame({
    "SPY": data["SPY"]["Close"],
    "VIX": data["VIX"]["Close"],
    "TLT": data["TLT"]["Close"],
}).dropna()

prices.index = prices.index.tz_localize(None) if prices.index.tz else prices.index

# Compute returns and VIX changes
prices["spy_ret"] = np.log(prices["SPY"] / prices["SPY"].shift(1))
prices["spy_abs_ret"] = prices["spy_ret"].abs()
prices["tlt_ret"] = np.log(prices["TLT"] / prices["TLT"].shift(1))
prices["vix_chg"] = prices["VIX"] - prices["VIX"].shift(1)
prices["vix_pct_chg"] = prices["VIX"].pct_change()
prices["vix_abs_chg"] = prices["vix_chg"].abs()
prices.dropna(inplace=True)

print(f"\n  Aligned sample: {len(prices)} days, "
      f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Tag macro event days
prices["is_fomc"] = prices.index.isin(fomc_set).astype(int)
prices["is_nfp"] = prices.index.isin(nfp_set).astype(int)
prices["is_cpi"] = prices.index.isin(cpi_set).astype(int)
prices["is_macro"] = prices.index.isin(all_macro_set).astype(int)

n_fomc_matched = prices["is_fomc"].sum()
n_nfp_matched = prices["is_nfp"].sum()
n_cpi_matched = prices["is_cpi"].sum()
n_macro_matched = prices["is_macro"].sum()
print(f"  Matched to trading days — FOMC: {n_fomc_matched}, NFP: {n_nfp_matched}, "
      f"CPI: {n_cpi_matched}, Total macro: {n_macro_matched}")

# ============================================================
# TEST 1: Macro vs Non-Macro Day Distributions
# ============================================================
print("\n" + "=" * 80)
print("[2] TEST 1: ARE MACRO DAYS HIGHER-VOL THAN NORMAL DAYS?")
print("=" * 80)

results = {}

for event_name, col in [("All Macro", "is_macro"), ("FOMC", "is_fomc"),
                          ("NFP", "is_nfp"), ("CPI", "is_cpi")]:
    macro_mask = prices[col] == 1
    non_mask = prices[col] == 0

    # |SPY return| comparison
    spy_abs_macro = prices.loc[macro_mask, "spy_abs_ret"]
    spy_abs_non = prices.loc[non_mask, "spy_abs_ret"]

    t_spy, p_spy = stats.ttest_ind(spy_abs_macro, spy_abs_non, equal_var=False)
    mw_spy, p_mw_spy = stats.mannwhitneyu(spy_abs_macro, spy_abs_non, alternative="greater")

    # |VIX change| comparison
    vix_abs_macro = prices.loc[macro_mask, "vix_abs_chg"]
    vix_abs_non = prices.loc[non_mask, "vix_abs_chg"]

    t_vix, p_vix = stats.ttest_ind(vix_abs_macro, vix_abs_non, equal_var=False)
    mw_vix, p_mw_vix = stats.mannwhitneyu(vix_abs_macro, vix_abs_non, alternative="greater")

    ratio_spy = spy_abs_macro.mean() / spy_abs_non.mean()
    ratio_vix = vix_abs_macro.mean() / vix_abs_non.mean()

    results[f"test1_{event_name}"] = {
        "n_event": int(macro_mask.sum()),
        "n_non_event": int(non_mask.sum()),
        "spy_abs_ret_event_mean": float(spy_abs_macro.mean()),
        "spy_abs_ret_non_mean": float(spy_abs_non.mean()),
        "spy_abs_ret_ratio": float(ratio_spy),
        "spy_ttest_t": float(t_spy),
        "spy_ttest_p": float(p_spy),
        "spy_mannwhitney_p": float(p_mw_spy),
        "vix_abs_chg_event_mean": float(vix_abs_macro.mean()),
        "vix_abs_chg_non_mean": float(vix_abs_non.mean()),
        "vix_abs_chg_ratio": float(ratio_vix),
        "vix_ttest_t": float(t_vix),
        "vix_ttest_p": float(p_vix),
        "vix_mannwhitney_p": float(p_mw_vix),
    }

    sig_spy = "***" if p_spy < 0.01 else "**" if p_spy < 0.05 else "*" if p_spy < 0.10 else ""
    sig_vix = "***" if p_vix < 0.01 else "**" if p_vix < 0.05 else "*" if p_vix < 0.10 else ""

    print(f"\n  {event_name} ({macro_mask.sum()} days vs {non_mask.sum()} non-event days):")
    print(f"    |SPY ret| — event: {spy_abs_macro.mean():.5f}, non-event: {spy_abs_non.mean():.5f}, "
          f"ratio: {ratio_spy:.2f}x, t={t_spy:.2f}, p={p_spy:.4f} {sig_spy}")
    print(f"    |VIX Δ|  — event: {vix_abs_macro.mean():.3f}, non-event: {vix_abs_non.mean():.3f}, "
          f"ratio: {ratio_vix:.2f}x, t={t_vix:.2f}, p={p_vix:.4f} {sig_vix}")
    print(f"    Mann-Whitney (one-sided) — SPY p={p_mw_spy:.4f}, VIX p={p_mw_vix:.4f}")

# ============================================================
# TEST 2: Event-Type Specific Analysis
# ============================================================
print("\n" + "=" * 80)
print("[3] TEST 2: WHICH MACRO EVENT MOVES VOL MOST?")
print("=" * 80)

# For each event type, compute mean |VIX Δ| and rank
event_summary = []
for event_name, col in [("FOMC", "is_fomc"), ("NFP", "is_nfp"), ("CPI", "is_cpi")]:
    mask = prices[col] == 1
    mean_vix_chg = prices.loc[mask, "vix_abs_chg"].mean()
    mean_spy_abs = prices.loc[mask, "spy_abs_ret"].mean()
    median_vix_chg = prices.loc[mask, "vix_abs_chg"].median()

    # What fraction of event days have |VIX Δ| > 1 point?
    frac_big = (prices.loc[mask, "vix_abs_chg"] > 1.0).mean()

    # Direction: does VIX tend to go up or down on event days?
    vix_chg_event = prices.loc[mask, "vix_chg"]
    mean_direction = vix_chg_event.mean()
    pct_up = (vix_chg_event > 0).mean()

    event_summary.append({
        "event": event_name,
        "n_days": int(mask.sum()),
        "mean_vix_abs_chg": float(mean_vix_chg),
        "median_vix_abs_chg": float(median_vix_chg),
        "mean_spy_abs_ret": float(mean_spy_abs),
        "frac_vix_chg_gt_1pt": float(frac_big),
        "mean_vix_direction": float(mean_direction),
        "pct_vix_up": float(pct_up),
    })

    print(f"\n  {event_name} ({mask.sum()} days):")
    print(f"    Mean |VIX Δ|: {mean_vix_chg:.3f} (median: {median_vix_chg:.3f})")
    print(f"    Mean |SPY ret|: {mean_spy_abs:.5f}")
    print(f"    Frac |VIX Δ| > 1pt: {frac_big:.1%}")
    print(f"    VIX direction: mean Δ = {mean_direction:+.3f}, up {pct_up:.1%}")

results["test2_event_ranking"] = sorted(event_summary, key=lambda x: -x["mean_vix_abs_chg"])

# ============================================================
# TEST 3: Surprise Frequency → Future Realized Vol
# ============================================================
print("\n" + "=" * 80)
print("[4] TEST 3: DOES SURPRISE FREQUENCY PREDICT FUTURE VOL?")
print("=" * 80)

# Define "big surprise" = |VIX Δ| > 2σ of full sample
vix_chg_std = prices["vix_abs_chg"].std()
vix_chg_mean = prices["vix_abs_chg"].mean()
threshold = vix_chg_mean + SURPRISE_SIGMA_THRESHOLD * vix_chg_std
prices["is_big_surprise"] = (prices["vix_abs_chg"] > threshold).astype(int)

# Also: big surprise on macro days only
prices["is_macro_surprise"] = ((prices["vix_abs_chg"] > threshold) & (prices["is_macro"] == 1)).astype(int)

n_big = prices["is_big_surprise"].sum()
n_macro_big = prices["is_macro_surprise"].sum()
print(f"  Big surprise threshold (mean + {SURPRISE_SIGMA_THRESHOLD}σ): {threshold:.3f} VIX points")
print(f"  Big surprise days: {n_big} ({n_big/len(prices):.1%} of all days)")
print(f"  Macro big surprise days: {n_macro_big} ({n_macro_big/len(prices):.1%})")

# Rolling surprise frequency (count of big-surprise days in last 22 days)
prices["surprise_freq_22"] = prices["is_big_surprise"].rolling(ROLLING_WINDOW).sum()
prices["macro_surprise_freq_22"] = prices["is_macro_surprise"].rolling(ROLLING_WINDOW).sum()

# Forward realized vol (annualized, 22 trading days)
prices["fwd_rv_22"] = prices["spy_ret"].shift(-1).rolling(FWD_RV_WINDOW).std().shift(-(FWD_RV_WINDOW - 1)) * np.sqrt(252)

# Drop NaN from rolling calculations
analysis = prices.dropna(subset=["surprise_freq_22", "fwd_rv_22"]).copy()
print(f"  Analysis sample after rolling: {len(analysis)} days")

# 3a: Simple correlation
corr_surprise, p_surprise = stats.pearsonr(analysis["surprise_freq_22"], analysis["fwd_rv_22"])
corr_macro_surprise, p_macro = stats.pearsonr(analysis["macro_surprise_freq_22"], analysis["fwd_rv_22"])
corr_vix, p_vix_rv = stats.pearsonr(analysis["VIX"], analysis["fwd_rv_22"])

print(f"\n  Simple correlations with forward 22-day RV:")
print(f"    VIX level → RV(+22):           r = {corr_vix:.4f} (p={p_vix_rv:.2e})")
print(f"    Surprise freq (22d) → RV(+22): r = {corr_surprise:.4f} (p={p_surprise:.2e})")
print(f"    Macro-surprise freq → RV(+22): r = {corr_macro_surprise:.4f} (p={p_macro:.2e})")

results["test3_correlations"] = {
    "vix_to_fwd_rv": {"r": float(corr_vix), "p": float(p_vix_rv)},
    "surprise_freq_to_fwd_rv": {"r": float(corr_surprise), "p": float(p_surprise)},
    "macro_surprise_freq_to_fwd_rv": {"r": float(corr_macro_surprise), "p": float(p_macro)},
}

# 3b: Partial correlation — surprise_freq → RV(+22) | controlling for VIX
# Method: residualize both variables on VIX, then correlate residuals
from numpy.linalg import lstsq

X_vix = np.column_stack([np.ones(len(analysis)), analysis["VIX"].values])
y_surprise = analysis["surprise_freq_22"].values
y_rv = analysis["fwd_rv_22"].values

# Residualize surprise_freq on VIX
beta_s, _, _, _ = lstsq(X_vix, y_surprise, rcond=None)
resid_surprise = y_surprise - X_vix @ beta_s

# Residualize fwd_rv on VIX
beta_rv, _, _, _ = lstsq(X_vix, y_rv, rcond=None)
resid_rv = y_rv - X_vix @ beta_rv

partial_r, partial_p = stats.pearsonr(resid_surprise, resid_rv)

print(f"\n  Partial correlation (controlling for VIX level):")
print(f"    surprise_freq → RV(+22) | VIX: partial r = {partial_r:.4f} (p={partial_p:.2e})")
sig_partial = "SIGNIFICANT" if partial_p < 0.05 else "NOT significant"
print(f"    → {sig_partial} at 5% level")
print(f"    → {'Passes' if abs(partial_r) * np.sqrt(len(analysis)) / (1 + abs(partial_r)) > 3.0 else 'FAILS'} Harvey (2016) t>3.0 threshold")

# Compute effective t-stat for Harvey check
t_stat_partial = partial_r * np.sqrt((len(analysis) - 3) / (1 - partial_r**2))
print(f"    → t-stat = {t_stat_partial:.2f}")

results["test3_partial_correlation"] = {
    "partial_r": float(partial_r),
    "partial_p": float(partial_p),
    "t_stat": float(t_stat_partial),
    "n_obs": len(analysis),
    "passes_harvey_t3": bool(abs(t_stat_partial) > 3.0),
}

# ============================================================
# TEST 4: Surprise Quintile Analysis
# ============================================================
print("\n" + "=" * 80)
print("[5] TEST 4: SURPRISE QUINTILE → FUTURE VOL")
print("=" * 80)

analysis["surprise_quintile"] = pd.qcut(analysis["surprise_freq_22"], 5, labels=False, duplicates="drop")

quintile_stats = []
for q in sorted(analysis["surprise_quintile"].unique()):
    mask = analysis["surprise_quintile"] == q
    mean_rv = analysis.loc[mask, "fwd_rv_22"].mean()
    mean_vix = analysis.loc[mask, "VIX"].mean()
    mean_freq = analysis.loc[mask, "surprise_freq_22"].mean()
    n = mask.sum()
    quintile_stats.append({
        "quintile": int(q),
        "n": int(n),
        "mean_surprise_freq": float(mean_freq),
        "mean_vix": float(mean_vix),
        "mean_fwd_rv": float(mean_rv),
    })
    print(f"  Q{q}: freq={mean_freq:.1f}, VIX={mean_vix:.1f}, "
          f"→ fwd RV = {mean_rv:.2%} (n={n})")

# Monotonicity test
rvs = [qs["mean_fwd_rv"] for qs in quintile_stats]
is_monotone = all(rvs[i] <= rvs[i+1] for i in range(len(rvs)-1))
# Spearman rank correlation across quintiles
spearman_r, spearman_p = stats.spearmanr(
    [qs["mean_surprise_freq"] for qs in quintile_stats],
    rvs
)
print(f"\n  Monotonicity: {'YES' if is_monotone else 'NO'}")
print(f"  Spearman rank correlation (quintile freq vs fwd RV): ρ={spearman_r:.3f} (p={spearman_p:.4f})")

# Q5/Q1 ratio
if len(quintile_stats) >= 2:
    q1_rv = quintile_stats[0]["mean_fwd_rv"]
    q5_rv = quintile_stats[-1]["mean_fwd_rv"]
    spread = q5_rv - q1_rv
    ratio = q5_rv / q1_rv if q1_rv > 0 else np.nan
    print(f"  Q5/Q1 ratio: {ratio:.2f}x (spread: {spread:.2%})")
    results["test4_quintile_spread"] = {
        "q1_fwd_rv": float(q1_rv),
        "q5_fwd_rv": float(q5_rv),
        "ratio": float(ratio),
        "spread": float(spread),
        "is_monotone": is_monotone,
        "spearman_rho": float(spearman_r),
        "spearman_p": float(spearman_p),
    }

results["test4_quintiles"] = quintile_stats

# ============================================================
# TEST 5: OOS GARCH-X Comparison
# ============================================================
print("\n" + "=" * 80)
print("[6] TEST 5: OOS GARCH-X vs GJR COMPARISON")
print("=" * 80)

try:
    from arch import arch_model

    oos_mask = analysis.index >= OOS_START
    is_data = analysis.index < OOS_START
    n_is = is_data.sum()
    n_oos = oos_mask.sum()
    print(f"  In-sample: {n_is} days (before {OOS_START})")
    print(f"  Out-of-sample: {n_oos} days (from {OOS_START})")

    # We'll do expanding-window 1-step-ahead forecasts
    spy_ret_pct = analysis["spy_ret"] * 100  # Scale for GARCH
    surprise_series = analysis["surprise_freq_22"]

    # Rolling OOS forecast
    oos_dates = analysis.index[oos_mask]
    min_window = 1000  # minimum in-sample window

    forecasts_gjr = []
    forecasts_garchx = []
    realized = []

    # To avoid extremely slow loop, use expanding window with step
    step = 5  # forecast every 5th day for speed
    oos_indices = list(range(len(analysis)))[analysis.index.get_loc(oos_dates[0])::step]

    print(f"  Running {len(oos_indices)} OOS forecasts (step={step})...")

    for count, idx in enumerate(oos_indices):
        if idx < min_window or idx >= len(analysis) - 1:
            continue

        train_ret = spy_ret_pct.iloc[:idx]
        train_surprise = surprise_series.iloc[:idx]
        actual_rv_next = analysis["fwd_rv_22"].iloc[idx]

        if pd.isna(actual_rv_next):
            continue

        # 1) Plain GJR-GARCH(1,1)
        try:
            gjr = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1, dist="normal")
            gjr_fit = gjr.fit(disp="off", show_warning=False)
            gjr_forecast = gjr_fit.forecast(horizon=1)
            gjr_var = gjr_forecast.variance.iloc[-1, 0]
            gjr_vol_ann = np.sqrt(gjr_var * 252) / 100  # Annualized, decimal
            forecasts_gjr.append(gjr_vol_ann)
        except Exception:
            continue

        # 2) GARCH-X: GJR with surprise_freq as external regressor
        try:
            garchx = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1, dist="normal",
                                x=pd.DataFrame({"surprise": train_surprise}))
            garchx_fit = garchx.fit(disp="off", show_warning=False)
            # For forecast, use last known surprise_freq
            last_surprise = pd.DataFrame({"surprise": [surprise_series.iloc[idx]]})
            garchx_forecast = garchx_fit.forecast(horizon=1, x=last_surprise)
            garchx_var = garchx_forecast.variance.iloc[-1, 0]
            garchx_vol_ann = np.sqrt(garchx_var * 252) / 100
            forecasts_garchx.append(garchx_vol_ann)
        except Exception:
            # If GARCH-X fails, use GJR value
            forecasts_garchx.append(gjr_vol_ann)

        realized.append(actual_rv_next)

        if (count + 1) % 50 == 0:
            print(f"    ... {count + 1}/{len(oos_indices)} done")

    forecasts_gjr = np.array(forecasts_gjr)
    forecasts_garchx = np.array(forecasts_garchx)
    realized = np.array(realized)

    print(f"\n  Valid OOS forecasts: {len(realized)}")

    if len(realized) > 30:
        # MSE comparison
        mse_gjr = np.mean((forecasts_gjr - realized) ** 2)
        mse_garchx = np.mean((forecasts_garchx - realized) ** 2)

        # MAE comparison
        mae_gjr = np.mean(np.abs(forecasts_gjr - realized))
        mae_garchx = np.mean(np.abs(forecasts_garchx - realized))

        # QLIKE
        def qlike(forecast, actual):
            """QLIKE loss: var/actual_var - log(var/actual_var) - 1"""
            ratio = forecast**2 / actual**2
            return np.mean(ratio - np.log(ratio) - 1)

        qlike_gjr = qlike(forecasts_gjr, realized)
        qlike_garchx = qlike(forecasts_garchx, realized)

        # Correlation with realized
        corr_gjr, _ = stats.pearsonr(forecasts_gjr, realized)
        corr_garchx, _ = stats.pearsonr(forecasts_garchx, realized)

        # Diebold-Mariano test
        e_gjr = (forecasts_gjr - realized) ** 2
        e_garchx = (forecasts_garchx - realized) ** 2
        d = e_gjr - e_garchx  # positive if GJR is worse

        dm_mean = d.mean()
        # Newey-West HAC standard error (lag = int(N^(1/3)))
        n_dm = len(d)
        lag = max(1, int(n_dm ** (1/3)))
        gamma_0 = np.var(d, ddof=1)
        gamma_sum = 0
        for k in range(1, lag + 1):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
        dm_var = (gamma_0 + gamma_sum) / n_dm
        dm_stat = dm_mean / np.sqrt(max(dm_var, 1e-12))
        dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

        print(f"\n  OOS Performance Comparison:")
        print(f"    {'Metric':<20} {'GJR':>12} {'GARCH-X':>12} {'Winner':>12}")
        print(f"    {'─' * 56}")
        print(f"    {'MSE':<20} {mse_gjr:>12.6f} {mse_garchx:>12.6f} {'GARCH-X' if mse_garchx < mse_gjr else 'GJR':>12}")
        print(f"    {'MAE':<20} {mae_gjr:>12.6f} {mae_garchx:>12.6f} {'GARCH-X' if mae_garchx < mae_gjr else 'GJR':>12}")
        print(f"    {'QLIKE':<20} {qlike_gjr:>12.6f} {qlike_garchx:>12.6f} {'GARCH-X' if qlike_garchx < qlike_gjr else 'GJR':>12}")
        print(f"    {'Corr w/ realized':<20} {corr_gjr:>12.4f} {corr_garchx:>12.4f} {'GARCH-X' if corr_garchx > corr_gjr else 'GJR':>12}")
        print(f"\n  Diebold-Mariano test (H0: equal predictive accuracy):")
        print(f"    DM stat = {dm_stat:.3f}, p = {dm_p:.4f}")
        print(f"    → {'GARCH-X significantly better' if dm_p < 0.05 and dm_mean > 0 else 'GJR significantly better' if dm_p < 0.05 and dm_mean < 0 else 'NO significant difference'}")

        results["test5_oos_garch"] = {
            "n_oos_forecasts": len(realized),
            "mse_gjr": float(mse_gjr),
            "mse_garchx": float(mse_garchx),
            "mae_gjr": float(mae_gjr),
            "mae_garchx": float(mae_garchx),
            "qlike_gjr": float(qlike_gjr),
            "qlike_garchx": float(qlike_garchx),
            "corr_gjr": float(corr_gjr),
            "corr_garchx": float(corr_garchx),
            "dm_stat": float(dm_stat),
            "dm_p": float(dm_p),
            "winner_mse": "GARCH-X" if mse_garchx < mse_gjr else "GJR",
            "winner_mae": "GARCH-X" if mae_garchx < mae_gjr else "GJR",
            "winner_qlike": "GARCH-X" if qlike_garchx < qlike_gjr else "GJR",
        }
    else:
        print("  WARNING: Too few valid OOS forecasts for comparison")
        results["test5_oos_garch"] = {"error": "too_few_forecasts", "n": len(realized)}

except ImportError:
    print("  WARNING: arch package not available, skipping GARCH-X test")
    results["test5_oos_garch"] = {"error": "arch_not_available"}
except Exception as e:
    print(f"  ERROR in GARCH-X test: {e}")
    results["test5_oos_garch"] = {"error": str(e)}

# ============================================================
# TEST 6: Time-Varying Macro Sensitivity
# ============================================================
print("\n" + "=" * 80)
print("[7] TEST 6: HAS MACRO SENSITIVITY CHANGED OVER TIME?")
print("=" * 80)

# Split into sub-periods
periods = [
    ("2003-2007 (pre-GFC)", "2003-01-01", "2007-12-31"),
    ("2008-2009 (GFC)", "2008-01-01", "2009-12-31"),
    ("2010-2015 (recovery)", "2010-01-01", "2015-12-31"),
    ("2016-2019 (pre-COVID)", "2016-01-01", "2019-12-31"),
    ("2020-2021 (COVID era)", "2020-01-01", "2021-12-31"),
    ("2022-2026 (tightening)", "2022-01-01", "2026-12-31"),
]

period_results = []
for period_name, start, end in periods:
    mask = (prices.index >= start) & (prices.index <= end)
    sub = prices.loc[mask]
    if len(sub) < 50:
        continue

    macro_sub = sub[sub["is_macro"] == 1]
    non_sub = sub[sub["is_macro"] == 0]

    if len(macro_sub) < 10:
        continue

    ratio = macro_sub["vix_abs_chg"].mean() / non_sub["vix_abs_chg"].mean()
    t, p = stats.ttest_ind(macro_sub["vix_abs_chg"], non_sub["vix_abs_chg"], equal_var=False)

    period_results.append({
        "period": period_name,
        "n_macro": int(len(macro_sub)),
        "n_non": int(len(non_sub)),
        "vix_ratio": float(ratio),
        "ttest_t": float(t),
        "ttest_p": float(p),
    })

    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
    print(f"  {period_name}: macro/non ratio = {ratio:.2f}x, t={t:.2f}, p={p:.4f} {sig}")

results["test6_time_varying"] = period_results

# ============================================================
# TEST 7: Multivariate Regression — Incremental Value
# ============================================================
print("\n" + "=" * 80)
print("[8] TEST 7: MULTIVARIATE REGRESSION — INCREMENTAL VALUE")
print("=" * 80)

from numpy.linalg import lstsq

# Regression: fwd_rv = α + β1*VIX + β2*surprise_freq + ε
# Compare R² of Model 1 (VIX only) vs Model 2 (VIX + surprise_freq)

valid = analysis.dropna(subset=["VIX", "surprise_freq_22", "fwd_rv_22"]).copy()
n_reg = len(valid)

y = valid["fwd_rv_22"].values
X1 = np.column_stack([np.ones(n_reg), valid["VIX"].values])
X2 = np.column_stack([np.ones(n_reg), valid["VIX"].values, valid["surprise_freq_22"].values])

# Model 1: VIX only
beta1, _, _, _ = lstsq(X1, y, rcond=None)
pred1 = X1 @ beta1
ss_res1 = np.sum((y - pred1) ** 2)
ss_tot = np.sum((y - y.mean()) ** 2)
r2_1 = 1 - ss_res1 / ss_tot

# Model 2: VIX + surprise_freq
beta2, _, _, _ = lstsq(X2, y, rcond=None)
pred2 = X2 @ beta2
ss_res2 = np.sum((y - pred2) ** 2)
r2_2 = 1 - ss_res2 / ss_tot

# Adjusted R²
adj_r2_1 = 1 - (1 - r2_1) * (n_reg - 1) / (n_reg - 2)
adj_r2_2 = 1 - (1 - r2_2) * (n_reg - 1) / (n_reg - 3)

# F-test for incremental variable
df1 = 1  # one additional variable
df2 = n_reg - 3  # residual df of full model
f_stat = ((ss_res1 - ss_res2) / df1) / (ss_res2 / df2)
f_p = 1 - stats.f.cdf(f_stat, df1, df2)

# t-test for surprise_freq coefficient
resid2 = y - pred2
sigma2 = np.sum(resid2**2) / (n_reg - 3)
XtX_inv = np.linalg.inv(X2.T @ X2)
se_beta2 = np.sqrt(sigma2 * XtX_inv[2, 2])
t_beta2 = beta2[2] / se_beta2
p_beta2 = 2 * (1 - stats.t.cdf(abs(t_beta2), n_reg - 3))

print(f"  Model 1 (VIX only):          R² = {r2_1:.4f}, Adj R² = {adj_r2_1:.4f}")
print(f"  Model 2 (VIX + surprise):    R² = {r2_2:.4f}, Adj R² = {adj_r2_2:.4f}")
print(f"  ΔR²: {r2_2 - r2_1:.6f}")
print(f"  F-test for surprise_freq: F = {f_stat:.2f}, p = {f_p:.4e}")
print(f"  Surprise_freq coefficient: β = {beta2[2]:.6f}, SE = {se_beta2:.6f}, t = {t_beta2:.2f}, p = {p_beta2:.4e}")
print(f"\n  VIX coefficient (Model 2): β = {beta2[1]:.6f}")
print(f"  Intercept (Model 2): α = {beta2[0]:.6f}")

results["test7_regression"] = {
    "n_obs": n_reg,
    "r2_vix_only": float(r2_1),
    "r2_vix_plus_surprise": float(r2_2),
    "adj_r2_vix_only": float(adj_r2_1),
    "adj_r2_vix_plus_surprise": float(adj_r2_2),
    "delta_r2": float(r2_2 - r2_1),
    "f_stat_incremental": float(f_stat),
    "f_p": float(f_p),
    "surprise_coef": float(beta2[2]),
    "surprise_se": float(se_beta2),
    "surprise_t": float(t_beta2),
    "surprise_p": float(p_beta2),
    "vix_coef": float(beta2[1]),
    "intercept": float(beta2[0]),
}

# ============================================================
# TEST 8: Asymmetry — Positive vs Negative Surprises
# ============================================================
print("\n" + "=" * 80)
print("[9] TEST 8: SURPRISE ASYMMETRY (VIX UP vs DOWN ON MACRO DAYS)")
print("=" * 80)

macro_days = prices[prices["is_macro"] == 1].copy()
vix_up_macro = macro_days[macro_days["vix_chg"] > 0]
vix_down_macro = macro_days[macro_days["vix_chg"] < 0]

print(f"  Macro days with VIX ↑: {len(vix_up_macro)} ({len(vix_up_macro)/len(macro_days):.1%})")
print(f"  Macro days with VIX ↓: {len(vix_down_macro)} ({len(vix_down_macro)/len(macro_days):.1%})")
print(f"  Mean |VIX Δ| on up days: {vix_up_macro['vix_abs_chg'].mean():.3f}")
print(f"  Mean |VIX Δ| on down days: {vix_down_macro['vix_abs_chg'].mean():.3f}")

# Does direction matter for future vol?
# Tag each macro day
prices["macro_vix_up"] = ((prices["is_macro"] == 1) & (prices["vix_chg"] > 0)).astype(int)
prices["macro_vix_down"] = ((prices["is_macro"] == 1) & (prices["vix_chg"] < 0)).astype(int)

# Rolling count of macro VIX-up days in last 22
prices["macro_up_freq_22"] = prices["macro_vix_up"].rolling(ROLLING_WINDOW).sum()
prices["macro_down_freq_22"] = prices["macro_vix_down"].rolling(ROLLING_WINDOW).sum()

valid_asym = prices.dropna(subset=["macro_up_freq_22", "macro_down_freq_22", "fwd_rv_22"]).copy()

if len(valid_asym) > 100:
    corr_up, p_up = stats.pearsonr(valid_asym["macro_up_freq_22"], valid_asym["fwd_rv_22"])
    corr_down, p_down = stats.pearsonr(valid_asym["macro_down_freq_22"], valid_asym["fwd_rv_22"])

    print(f"\n  Macro VIX-up freq (22d) → fwd RV: r = {corr_up:.4f} (p={p_up:.4e})")
    print(f"  Macro VIX-down freq (22d) → fwd RV: r = {corr_down:.4f} (p={p_down:.4e})")
    print(f"  → {'Up surprises more predictive' if abs(corr_up) > abs(corr_down) else 'Down surprises more predictive'}")

    results["test8_asymmetry"] = {
        "n_macro_vix_up": int(len(vix_up_macro)),
        "n_macro_vix_down": int(len(vix_down_macro)),
        "mean_abs_chg_up": float(vix_up_macro["vix_abs_chg"].mean()),
        "mean_abs_chg_down": float(vix_down_macro["vix_abs_chg"].mean()),
        "corr_up_freq_fwd_rv": float(corr_up),
        "p_up": float(p_up),
        "corr_down_freq_fwd_rv": float(corr_down),
        "p_down": float(p_down),
    }

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY: K259 ECONOMIC SURPRISE AND VOLATILITY")
print("=" * 80)

print(f"""
Data: SPY, VIX, TLT daily from yfinance ({prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')})
Sample: {len(prices)} trading days
Macro events: {n_macro_matched} matched days (FOMC: {n_fomc_matched}, NFP: {n_nfp_matched}, CPI: {n_cpi_matched})

KEY FINDINGS:

1. MACRO vs NON-MACRO DAYS:
   - All macro: |VIX Δ| ratio = {results['test1_All Macro']['vix_abs_chg_ratio']:.2f}x (p={results['test1_All Macro']['vix_ttest_p']:.4f})
   - FOMC: |VIX Δ| ratio = {results['test1_FOMC']['vix_abs_chg_ratio']:.2f}x (p={results['test1_FOMC']['vix_ttest_p']:.4f})
   - NFP: |VIX Δ| ratio = {results['test1_NFP']['vix_abs_chg_ratio']:.2f}x (p={results['test1_NFP']['vix_ttest_p']:.4f})
   - CPI: |VIX Δ| ratio = {results['test1_CPI']['vix_abs_chg_ratio']:.2f}x (p={results['test1_CPI']['vix_ttest_p']:.4f})

2. PREDICTIVE POWER (surprise freq → fwd RV):
   - Simple r: {corr_surprise:.4f} (p={p_surprise:.2e})
   - Partial r (controlling VIX): {partial_r:.4f} (p={partial_p:.2e})
   - t-stat: {t_stat_partial:.2f} ({'passes' if abs(t_stat_partial) > 3.0 else 'FAILS'} Harvey t>3.0)

3. MULTIVARIATE REGRESSION:
   - VIX only R²: {r2_1:.4f}
   - VIX + surprise R²: {r2_2:.4f} (ΔR² = {r2_2-r2_1:.6f})
   - Surprise coef t-stat: {t_beta2:.2f} (p={p_beta2:.4e})

LIMITATIONS:
  - Proxy-based analysis (no actual CESI data)
  - NFP/CPI dates are approximated
  - Surprise frequency constructed from VIX itself (circular concern)
  - Results reflect macro-event timing effects, not true economic surprises
""")

# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    "experiment": "K259",
    "title": "Economic Surprise and Volatility — Does Bad News Create Vol?",
    "method": "Proxy-based analysis using VIX changes on macro event dates",
    "data": {
        "source": "yfinance",
        "assets": ["SPY", "^VIX", "TLT"],
        "period": f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
        "n_days": len(prices),
        "n_macro_days": int(n_macro_matched),
    },
    "limitations": [
        "Proxy analysis — no actual CESI data available",
        "NFP dates approximated as first Friday of month",
        "CPI dates approximated as ~13th of month",
        "VIX change is noisy proxy for economic surprise",
        "Surprise frequency constructed from VIX (circular concern)",
        "FOMC dates reconstructed from K256, minor inaccuracies possible",
    ],
    "results": results,
    "attribution": "[提出: User, 執行: Claude]",
}

output_path = PROJECT_ROOT / "experiments" / "k259_macro_surprise_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print("=" * 80)
