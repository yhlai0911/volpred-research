#!/usr/bin/env python3
"""
K631: Day-of-Week and Calendar Volatility Patterns
====================================================
[提出: K626 feature importance 發現 day_of_week #1, 執行: Claude]

Motivation:
  K626 found day_of_week was the #1 feature for VIX direction prediction
  (importance 0.15). Calendar effects in volatility are well-documented
  (French 1980, Gibbons & Hess 1981, Berument & Kiymaz 2001) but rarely
  tested as forecast overlays in our framework.

Prior Knowledge:
  - K35: VT seasonality null (ANOVA p=0.69) — but tested month-of-year, not day-of-week
  - K153: No month-of-year seasonality
  - K498: Calendar dummy approach → null
  - K513: FOMC day vol +28% higher than normal (significant)
  - K514: FOMC surprise magnitude predicts forward vol
  - K547: Turn-of-month effect exists, but VT overlay marginal
  - K626: day_of_week = #1 feature importance for VIX direction (0.15)

References:
  - French (1980) "Stock Returns and the Weekend Effect" JFE
  - Gibbons & Hess (1981) "Day of the Week Effects" J Business
  - Berument & Kiymaz (2001) "The Day of the Week Effect on Volatility" JIMF
  - Doyle & Chen (2009) "The Wandering Weekday Effect" JBES
  - Hansen & Lunde (2003) "Testing the Significance of Calendar Effects" working paper
  - K626 VIX direction feature importance analysis

Research Questions:
  1. Do squared returns (r²) differ systematically by weekday? (Monday/Friday effect)
  2. Do squared returns differ by month? (January/October effect)
  3. Is vol higher on FOMC days? (reconfirm K513)
  4. Does options expiration (OpEx, 3rd Friday) affect vol?
  5. Is there a turn-of-month vol pattern?
  6. Can a HAR + calendar dummies model beat plain HAR?
  7. Can GJR-GARCH + calendar scaling beat plain GJR-GARCH?
  8. Do these patterns hold cross-asset (SPY, GLD, 0050.TW)?

Data: SPY, GLD, 0050.TW from yfinance (2006-01-01 to 2026-03-27)
"""

import json
import time
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from numpy.linalg import lstsq

warnings.filterwarnings("ignore")

START_TIME = time.time()
EXPERIMENT_ID = "K631"
MAIN_REPO = "/Users/yhlai0911/Desktop/volpred-research"

# ============================================================================
# Configuration
# ============================================================================
DATA_START = "2005-01-01"   # extra warmup for rolling windows
DATA_END = "2026-03-28"
ANALYSIS_START = "2006-01-01"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
ROLLING_WINDOW = 2000
REFIT_EVERY = 21
BOOTSTRAP_REPS = 5000
RANDOM_SEED = 42

ASSETS = {
    "SPY": "SPY",
    "GLD": "GLD",
    "0050.TW": "0050.TW",
}

# FOMC Meeting Dates (2006-2026)
# Source: Federal Reserve Board of Governors
FOMC_DATES_STR = [
    # 2006
    "2006-01-31", "2006-03-28", "2006-05-10", "2006-06-29",
    "2006-08-08", "2006-09-20", "2006-10-25", "2006-12-12",
    # 2007
    "2007-01-31", "2007-03-21", "2007-05-09", "2007-06-28",
    "2007-08-07", "2007-09-18", "2007-10-31", "2007-12-11",
    # 2008
    "2008-01-22", "2008-01-30", "2008-03-18", "2008-04-30",
    "2008-06-25", "2008-08-05", "2008-09-16", "2008-10-08",
    "2008-10-29", "2008-12-16",
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
    "2014-01-29", "2014-03-19", "2014-04-30", "2014-06-18",
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
    "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05",
    "2020-12-16",
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
    "2025-01-29", "2025-03-19",
    # 2026
    "2026-01-28", "2026-03-18",
]

# US Holidays (approximate dates for major holidays, NYSE closed)
US_HOLIDAYS_APPROX = {
    "New Year": (1, 1),
    "MLK Day": (1, 15),       # 3rd Monday of Jan (approx)
    "Presidents Day": (2, 15), # 3rd Monday of Feb (approx)
    "Good Friday": None,       # varies
    "Memorial Day": (5, 25),   # last Monday of May (approx)
    "Independence Day": (7, 4),
    "Labor Day": (9, 1),       # 1st Monday of Sep (approx)
    "Thanksgiving": (11, 25),  # 4th Thursday of Nov (approx)
    "Christmas": (12, 25),
}

print("=" * 72)
print(f"{EXPERIMENT_ID}: Day-of-Week and Calendar Volatility Patterns")
print("  Cross-asset: SPY, GLD, 0050.TW")
print("  Tests: weekday, month, FOMC, OpEx, turn-of-month, quarter-end")
print("  Forecasting: HAR+cal vs HAR, GJR+cal vs GJR")
print("=" * 72)

# ============================================================================
# 1. Data Download
# ============================================================================
print("\n[1] Downloading data...")

def download_with_retry(ticker, start, end, max_retries=3):
    """Download data from yfinance with retry logic."""
    for attempt in range(max_retries):
        try:
            data = yf.download(ticker, start=start, end=end, progress=False)
            if data is not None and len(data) > 0:
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                return data
        except Exception as e:
            print(f"  Attempt {attempt+1} for {ticker} failed: {e}")
        if attempt < max_retries - 1:
            time.sleep(2)
    raise RuntimeError(f"Failed to download {ticker}")


asset_data = {}
for name, ticker in ASSETS.items():
    try:
        raw = download_with_retry(ticker, DATA_START, DATA_END)
        close = raw["Close"].squeeze()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        close = close.dropna()
        # Log returns
        log_ret = np.log(close / close.shift(1)).dropna()
        # Squared returns as vol proxy
        r2 = log_ret ** 2
        asset_data[name] = {
            "close": close,
            "log_ret": log_ret,
            "r2": r2,
        }
        print(f"  {name}: {len(close)} days ({close.index[0].date()} to {close.index[-1].date()})")
        time.sleep(1)
    except Exception as e:
        print(f"  WARNING: Failed to download {name}: {e}")

# Also download VIX for FOMC analysis
try:
    vix_raw = download_with_retry("^VIX", DATA_START, DATA_END)
    vix_close = vix_raw["Close"].squeeze()
    vix_close.index = pd.to_datetime(vix_close.index).tz_localize(None)
    vix_close = vix_close.dropna()
    print(f"  VIX: {len(vix_close)} days")
except Exception as e:
    print(f"  WARNING: VIX download failed: {e}")
    vix_close = None


# ============================================================================
# 2. Calendar Feature Engineering
# ============================================================================
print("\n[2] Engineering calendar features...")

FOMC_DATES = set(pd.to_datetime(FOMC_DATES_STR))

def add_calendar_features(df_index):
    """Create calendar indicator DataFrame from a DatetimeIndex."""
    cal = pd.DataFrame(index=df_index)
    cal["weekday"] = cal.index.weekday          # 0=Mon, 4=Fri
    cal["weekday_name"] = cal.index.day_name()
    cal["month"] = cal.index.month
    cal["month_name"] = cal.index.month_name()
    cal["year"] = cal.index.year
    cal["quarter"] = cal.index.quarter
    cal["day_of_month"] = cal.index.day

    # FOMC day indicator
    cal["is_fomc"] = cal.index.isin(FOMC_DATES).astype(int)
    # Day before/after FOMC
    fomc_set = FOMC_DATES
    cal["is_fomc_prev"] = cal.index.isin(
        {d - pd.Timedelta(days=1) for d in fomc_set} |
        {d - pd.Timedelta(days=3) for d in fomc_set}  # Friday before Monday FOMC
    ).astype(int)

    # Options Expiration: 3rd Friday of each month
    opex_dates = set()
    for y in range(cal.index.year.min(), cal.index.year.max() + 1):
        for m in range(1, 13):
            # Find 3rd Friday
            first_day = pd.Timestamp(y, m, 1)
            # First Friday
            days_until_fri = (4 - first_day.weekday()) % 7
            first_fri = first_day + pd.Timedelta(days=days_until_fri)
            third_fri = first_fri + pd.Timedelta(days=14)
            opex_dates.add(third_fri)
    cal["is_opex"] = cal.index.isin(opex_dates).astype(int)
    # Day before OpEx (Thursday before 3rd Friday)
    cal["is_opex_week"] = 0
    for d in opex_dates:
        # OpEx week: Tue-Fri of OpEx week
        for offset in range(-3, 1):
            target = d + pd.Timedelta(days=offset)
            if target in cal.index:
                cal.loc[target, "is_opex_week"] = 1

    # Turn-of-Month: last 1 + first 3 trading days
    # Use trading day rank within month
    cal["td_in_month"] = cal.groupby([cal.index.year, cal.index.month]).cumcount() + 1
    cal["td_total_month"] = cal.groupby([cal.index.year, cal.index.month])["td_in_month"].transform("max")
    cal["days_from_end"] = cal["td_total_month"] - cal["td_in_month"]
    cal["is_tom"] = ((cal["td_in_month"] <= 3) | (cal["days_from_end"] <= 0)).astype(int)
    cal["is_mid_month"] = (1 - cal["is_tom"]).astype(int)

    # Quarter-end: last 5 trading days of quarter
    cal["is_quarter_end"] = 0
    for y in range(cal.index.year.min(), cal.index.year.max() + 1):
        for qm in [3, 6, 9, 12]:
            q_mask = (cal.index.year == y) & (cal.index.month == qm)
            q_days = cal.index[q_mask]
            if len(q_days) >= 5:
                last5 = q_days[-5:]
                cal.loc[last5, "is_quarter_end"] = 1

    # Pre-holiday: day before NYSE holidays
    # Approximate: day before July 4, day before Christmas, day before Thanksgiving, etc.
    cal["is_pre_holiday"] = 0
    for d in cal.index:
        next_day = d + pd.Timedelta(days=1)
        # Check if next day is a common holiday
        if next_day.month == 1 and next_day.day == 1:  # New Year
            cal.loc[d, "is_pre_holiday"] = 1
        elif next_day.month == 7 and next_day.day == 4:  # Independence Day
            cal.loc[d, "is_pre_holiday"] = 1
        elif next_day.month == 12 and next_day.day == 25:  # Christmas
            cal.loc[d, "is_pre_holiday"] = 1
        # Also check if next trading day is 2+ days away (suggests market holiday)
        if d != cal.index[-1]:
            idx_pos = cal.index.get_loc(d)
            if idx_pos < len(cal.index) - 1:
                next_td = cal.index[idx_pos + 1]
                gap = (next_td - d).days
                if gap >= 3:  # 3+ calendar days gap → likely holiday
                    cal.loc[d, "is_pre_holiday"] = 1

    return cal


# ============================================================================
# 3. Pattern Analysis Functions
# ============================================================================

def bootstrap_mean_ci(data, n_boot=BOOTSTRAP_REPS, ci=0.95, seed=RANDOM_SEED):
    """Bootstrap confidence interval for the mean."""
    rng = np.random.RandomState(seed)
    n = len(data)
    if n == 0:
        return np.nan, np.nan, np.nan
    means = np.zeros(n_boot)
    for i in range(n_boot):
        sample = data[rng.randint(0, n, size=n)]
        means[i] = np.mean(sample)
    alpha = (1 - ci) / 2
    return np.mean(data), np.percentile(means, alpha * 100), np.percentile(means, (1 - alpha) * 100)


def bootstrap_ratio_ci(data1, data2, n_boot=BOOTSTRAP_REPS, ci=0.95, seed=RANDOM_SEED):
    """Bootstrap CI for ratio of means (data1 / data2)."""
    rng = np.random.RandomState(seed)
    n1, n2 = len(data1), len(data2)
    if n1 == 0 or n2 == 0:
        return np.nan, np.nan, np.nan
    ratios = np.zeros(n_boot)
    for i in range(n_boot):
        m1 = np.mean(data1[rng.randint(0, n1, size=n1)])
        m2 = np.mean(data2[rng.randint(0, n2, size=n2)])
        ratios[i] = m1 / m2 if m2 != 0 else np.nan
    alpha = (1 - ci) / 2
    return np.nanmean(ratios), np.nanpercentile(ratios, alpha * 100), np.nanpercentile(ratios, (1 - alpha) * 100)


def analyze_day_of_week(r2, cal):
    """Analyze day-of-week patterns in squared returns."""
    print("\n  --- Day-of-Week Volatility ---")
    results = {}
    weekday_groups = []
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    for wd in range(5):
        mask = cal["weekday"] == wd
        vals = r2[mask].dropna().values
        mean, ci_lo, ci_hi = bootstrap_mean_ci(vals)
        results[weekday_names[wd]] = {
            "mean_r2": float(mean),
            "ci_95_lo": float(ci_lo),
            "ci_95_hi": float(ci_hi),
            "n_days": int(len(vals)),
            "median_r2": float(np.median(vals)),
            "std_r2": float(np.std(vals)),
        }
        weekday_groups.append(vals)
        print(f"    {weekday_names[wd]:12s}: mean r²={mean:.6f}  "
              f"CI=[{ci_lo:.6f}, {ci_hi:.6f}]  n={len(vals)}")

    # Kruskal-Wallis test (non-parametric ANOVA)
    kw_stat, kw_p = stats.kruskal(*weekday_groups)
    results["kruskal_wallis"] = {"statistic": float(kw_stat), "p_value": float(kw_p)}
    print(f"    Kruskal-Wallis: H={kw_stat:.4f}, p={kw_p:.4f}")

    # Monday vs rest
    mon_vals = weekday_groups[0]
    rest_vals = np.concatenate(weekday_groups[1:])
    t_mon, p_mon = stats.ttest_ind(mon_vals, rest_vals, equal_var=False)
    mon_ratio, mr_lo, mr_hi = bootstrap_ratio_ci(mon_vals, rest_vals)
    results["monday_effect"] = {
        "t_stat": float(t_mon), "p_value": float(p_mon),
        "monday_vs_rest_ratio": float(mon_ratio),
        "ratio_ci_lo": float(mr_lo), "ratio_ci_hi": float(mr_hi),
    }
    print(f"    Monday vs Rest: t={t_mon:.3f}, p={p_mon:.4f}, ratio={mon_ratio:.4f}")

    # Friday vs rest
    fri_vals = weekday_groups[4]
    rest_no_fri = np.concatenate(weekday_groups[:4])
    t_fri, p_fri = stats.ttest_ind(fri_vals, rest_no_fri, equal_var=False)
    fri_ratio, fr_lo, fr_hi = bootstrap_ratio_ci(fri_vals, rest_no_fri)
    results["friday_effect"] = {
        "t_stat": float(t_fri), "p_value": float(p_fri),
        "friday_vs_rest_ratio": float(fri_ratio),
        "ratio_ci_lo": float(fr_lo), "ratio_ci_hi": float(fr_hi),
    }
    print(f"    Friday vs Rest: t={t_fri:.3f}, p={p_fri:.4f}, ratio={fri_ratio:.4f}")

    return results


def analyze_month_of_year(r2, cal):
    """Analyze month-of-year patterns in squared returns."""
    print("\n  --- Month-of-Year Volatility ---")
    results = {}
    month_groups = []
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for m in range(1, 13):
        mask = cal["month"] == m
        vals = r2[mask].dropna().values
        mean, ci_lo, ci_hi = bootstrap_mean_ci(vals)
        results[month_names[m-1]] = {
            "mean_r2": float(mean),
            "ci_95_lo": float(ci_lo),
            "ci_95_hi": float(ci_hi),
            "n_days": int(len(vals)),
        }
        month_groups.append(vals)
        print(f"    {month_names[m-1]:4s}: mean r²={mean:.6f}  "
              f"CI=[{ci_lo:.6f}, {ci_hi:.6f}]  n={len(vals)}")

    # Kruskal-Wallis
    kw_stat, kw_p = stats.kruskal(*month_groups)
    results["kruskal_wallis"] = {"statistic": float(kw_stat), "p_value": float(kw_p)}
    print(f"    Kruskal-Wallis: H={kw_stat:.4f}, p={kw_p:.4f}")

    # October effect (historically high vol month)
    oct_vals = month_groups[9]
    rest_vals = np.concatenate(month_groups[:9] + month_groups[10:])
    t_oct, p_oct = stats.ttest_ind(oct_vals, rest_vals, equal_var=False)
    results["october_effect"] = {"t_stat": float(t_oct), "p_value": float(p_oct)}
    print(f"    October vs Rest: t={t_oct:.3f}, p={p_oct:.4f}")

    # January effect
    jan_vals = month_groups[0]
    rest_no_jan = np.concatenate(month_groups[1:])
    t_jan, p_jan = stats.ttest_ind(jan_vals, rest_no_jan, equal_var=False)
    results["january_effect"] = {"t_stat": float(t_jan), "p_value": float(p_jan)}
    print(f"    January vs Rest: t={t_jan:.3f}, p={p_jan:.4f}")

    return results


def analyze_fomc_effect(r2, cal):
    """Analyze FOMC day effect on volatility."""
    print("\n  --- FOMC Day Effect ---")
    fomc_vals = r2[cal["is_fomc"] == 1].dropna().values
    non_fomc_vals = r2[cal["is_fomc"] == 0].dropna().values

    if len(fomc_vals) == 0:
        print("    No FOMC days found in this asset's trading calendar")
        return {"note": "no FOMC overlap"}

    mean_fomc, ci_lo_f, ci_hi_f = bootstrap_mean_ci(fomc_vals)
    mean_non, ci_lo_n, ci_hi_n = bootstrap_mean_ci(non_fomc_vals)

    t_stat, p_val = stats.ttest_ind(fomc_vals, non_fomc_vals, equal_var=False)
    ratio, r_lo, r_hi = bootstrap_ratio_ci(fomc_vals, non_fomc_vals)

    results = {
        "fomc_mean_r2": float(mean_fomc),
        "non_fomc_mean_r2": float(mean_non),
        "fomc_ci": [float(ci_lo_f), float(ci_hi_f)],
        "non_fomc_ci": [float(ci_lo_n), float(ci_hi_n)],
        "t_stat_welch": float(t_stat),
        "p_value": float(p_val),
        "fomc_vs_nonfomc_ratio": float(ratio),
        "ratio_ci": [float(r_lo), float(r_hi)],
        "n_fomc": int(len(fomc_vals)),
        "n_non_fomc": int(len(non_fomc_vals)),
        "pct_increase": float((mean_fomc / mean_non - 1) * 100) if mean_non > 0 else None,
    }

    print(f"    FOMC days:     mean r²={mean_fomc:.6f}  n={len(fomc_vals)}")
    print(f"    Non-FOMC days: mean r²={mean_non:.6f}  n={len(non_fomc_vals)}")
    print(f"    Ratio: {ratio:.4f}  CI=[{r_lo:.4f}, {r_hi:.4f}]")
    print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")
    if mean_non > 0:
        print(f"    FOMC vol increase: {(mean_fomc/mean_non - 1)*100:.1f}%")

    return results


def analyze_opex_effect(r2, cal):
    """Analyze options expiration effect on volatility."""
    print("\n  --- Options Expiration (OpEx) Effect ---")
    opex_vals = r2[cal["is_opex"] == 1].dropna().values
    non_opex_vals = r2[cal["is_opex"] == 0].dropna().values

    if len(opex_vals) == 0:
        return {"note": "no OpEx days found"}

    mean_opex, ci_lo, ci_hi = bootstrap_mean_ci(opex_vals)
    mean_non, _, _ = bootstrap_mean_ci(non_opex_vals)
    t_stat, p_val = stats.ttest_ind(opex_vals, non_opex_vals, equal_var=False)
    ratio, r_lo, r_hi = bootstrap_ratio_ci(opex_vals, non_opex_vals)

    # OpEx week effect
    opex_week_vals = r2[cal["is_opex_week"] == 1].dropna().values
    non_opex_week_vals = r2[cal["is_opex_week"] == 0].dropna().values
    t_week, p_week = stats.ttest_ind(opex_week_vals, non_opex_week_vals, equal_var=False)

    results = {
        "opex_day_mean_r2": float(mean_opex),
        "non_opex_mean_r2": float(mean_non),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "opex_vs_nonopex_ratio": float(ratio),
        "ratio_ci": [float(r_lo), float(r_hi)],
        "n_opex": int(len(opex_vals)),
        "opex_week_t_stat": float(t_week),
        "opex_week_p_value": float(p_week),
        "pct_change": float((mean_opex / mean_non - 1) * 100) if mean_non > 0 else None,
    }

    print(f"    OpEx day:  mean r²={mean_opex:.6f}  n={len(opex_vals)}")
    print(f"    Non-OpEx:  mean r²={mean_non:.6f}")
    print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}, ratio={ratio:.4f}")
    print(f"    OpEx week: t={t_week:.3f}, p={p_week:.4f}")

    return results


def analyze_tom_effect(r2, cal):
    """Analyze turn-of-month effect on volatility."""
    print("\n  --- Turn-of-Month Effect ---")
    tom_vals = r2[cal["is_tom"] == 1].dropna().values
    mid_vals = r2[cal["is_mid_month"] == 1].dropna().values

    mean_tom, ci_lo_t, ci_hi_t = bootstrap_mean_ci(tom_vals)
    mean_mid, ci_lo_m, ci_hi_m = bootstrap_mean_ci(mid_vals)
    t_stat, p_val = stats.ttest_ind(tom_vals, mid_vals, equal_var=False)
    ratio, r_lo, r_hi = bootstrap_ratio_ci(tom_vals, mid_vals)

    results = {
        "tom_mean_r2": float(mean_tom),
        "mid_month_mean_r2": float(mean_mid),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "tom_vs_mid_ratio": float(ratio),
        "ratio_ci": [float(r_lo), float(r_hi)],
        "n_tom": int(len(tom_vals)),
        "n_mid": int(len(mid_vals)),
    }

    print(f"    Turn-of-Month: mean r²={mean_tom:.6f}  n={len(tom_vals)}")
    print(f"    Mid-Month:     mean r²={mean_mid:.6f}  n={len(mid_vals)}")
    print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}, ratio={ratio:.4f}")

    return results


def analyze_quarter_end(r2, cal):
    """Analyze quarter-end effect on volatility."""
    print("\n  --- Quarter-End Effect ---")
    qe_vals = r2[cal["is_quarter_end"] == 1].dropna().values
    non_qe_vals = r2[cal["is_quarter_end"] == 0].dropna().values

    if len(qe_vals) == 0:
        return {"note": "no quarter-end days found"}

    mean_qe, ci_lo, ci_hi = bootstrap_mean_ci(qe_vals)
    mean_non, _, _ = bootstrap_mean_ci(non_qe_vals)
    t_stat, p_val = stats.ttest_ind(qe_vals, non_qe_vals, equal_var=False)

    results = {
        "quarter_end_mean_r2": float(mean_qe),
        "non_quarter_end_mean_r2": float(mean_non),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "n_quarter_end": int(len(qe_vals)),
        "pct_change": float((mean_qe / mean_non - 1) * 100) if mean_non > 0 else None,
    }

    print(f"    Quarter-End: mean r²={mean_qe:.6f}  n={len(qe_vals)}")
    print(f"    Non-QE:      mean r²={mean_non:.6f}")
    print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")

    return results


def analyze_pre_holiday(r2, cal):
    """Analyze pre-holiday effect on volatility."""
    print("\n  --- Pre-Holiday Effect ---")
    pre_vals = r2[cal["is_pre_holiday"] == 1].dropna().values
    non_pre_vals = r2[cal["is_pre_holiday"] == 0].dropna().values

    if len(pre_vals) == 0:
        return {"note": "no pre-holiday days found"}

    mean_pre, ci_lo, ci_hi = bootstrap_mean_ci(pre_vals)
    mean_non, _, _ = bootstrap_mean_ci(non_pre_vals)
    t_stat, p_val = stats.ttest_ind(pre_vals, non_pre_vals, equal_var=False)

    results = {
        "pre_holiday_mean_r2": float(mean_pre),
        "non_pre_holiday_mean_r2": float(mean_non),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "n_pre_holiday": int(len(pre_vals)),
        "pct_change": float((mean_pre / mean_non - 1) * 100) if mean_non > 0 else None,
    }

    print(f"    Pre-Holiday: mean r²={mean_pre:.6f}  n={len(pre_vals)}")
    print(f"    Non-Pre-Hol: mean r²={mean_non:.6f}")
    print(f"    Welch t={t_stat:.3f}, p={p_val:.4f}")

    return results


# ============================================================================
# 4. Forecasting Models
# ============================================================================

def compute_rv_components(r2):
    """Compute HAR-RV components: daily, weekly (5d), monthly (22d)."""
    rv_d = r2.copy()
    rv_w = r2.rolling(5).mean()
    rv_m = r2.rolling(22).mean()
    return rv_d, rv_w, rv_m


def fit_har(X, y):
    """Fit HAR model via OLS. Returns coefficients and residuals."""
    # Add constant
    X_c = np.column_stack([np.ones(len(X)), X])
    # OLS via least squares
    coefs, residuals, rank, sv = lstsq(X_c, y, rcond=None)
    return coefs


def qlike_loss(actual, forecast):
    """QLIKE loss: log(forecast) + actual/forecast. Lower is better."""
    # Ensure positive
    forecast = np.maximum(forecast, 1e-12)
    actual = np.maximum(actual, 1e-12)
    return np.mean(np.log(forecast) + actual / forecast)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC standard errors.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t.
    Negative t-stat → model 1 is better (lower loss).
    """
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # Newey-West HAC with bandwidth = h-1
    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for lag in range(1, h):
        w = 1 - lag / h
        gamma_lag = np.cov(d[lag:], d[:-lag])[0, 1]
        hac_var += 2 * w * gamma_lag

    se = np.sqrt(hac_var / n) if hac_var > 0 else 1e-10
    t_stat = d_bar / se
    p_val = 2 * stats.norm.sf(abs(t_stat))

    return float(t_stat), float(p_val)


def rolling_oos_forecast(r2, cal, oos_start, oos_end, window=ROLLING_WINDOW,
                         refit=REFIT_EVERY, asset_name="SPY"):
    """
    Rolling OOS comparison:
      Model A: HAR (RV_d, RV_w, RV_m)
      Model B: HAR + calendar dummies (weekday dummies + is_fomc + is_opex + is_tom)
      Model C: GJR-style scaling (plain HAR forecast * day-specific scale factor)

    Returns dict with QLIKE and DM test results.
    """
    print(f"\n  --- Rolling OOS Forecast ({asset_name}) ---")
    print(f"    Window={window}, refit every {refit} days")
    print(f"    OOS: {oos_start} to {oos_end}")

    # Compute HAR components
    rv_d, rv_w, rv_m = compute_rv_components(r2)

    # Build features DataFrame
    feat = pd.DataFrame({
        "rv_d": rv_d,
        "rv_w": rv_w,
        "rv_m": rv_m,
        "target": r2.shift(-1),  # next-day r² as target
    }, index=r2.index)

    # Calendar dummies
    # Weekday dummies (drop Monday as base)
    for wd in range(1, 5):
        feat[f"wd_{wd}"] = (cal["weekday"] == wd).astype(float)
    feat["is_fomc"] = cal["is_fomc"].astype(float)
    feat["is_opex"] = cal["is_opex"].astype(float)
    feat["is_tom"] = cal["is_tom"].astype(float)
    feat["is_quarter_end"] = cal["is_quarter_end"].astype(float)

    feat = feat.dropna()

    # OOS period
    oos_mask = (feat.index >= pd.Timestamp(oos_start)) & (feat.index <= pd.Timestamp(oos_end))
    oos_idx = feat.index[oos_mask]

    if len(oos_idx) < 50:
        print(f"    WARNING: Only {len(oos_idx)} OOS observations, skipping")
        return None

    print(f"    OOS observations: {len(oos_idx)}")

    # HAR features (Model A)
    har_cols = ["rv_d", "rv_w", "rv_m"]
    # HAR + Calendar (Model B)
    cal_cols = har_cols + [f"wd_{wd}" for wd in range(1, 5)] + ["is_fomc", "is_opex", "is_tom", "is_quarter_end"]

    forecasts_a = []  # HAR
    forecasts_b = []  # HAR + Calendar
    forecasts_c = []  # HAR * day-scaling
    actuals = []
    last_refit = -refit  # Force first refit

    coefs_a = None
    coefs_b = None
    day_scale = np.ones(5)  # scaling for each weekday

    for i, date in enumerate(oos_idx):
        pos = feat.index.get_loc(date)

        # Refit?
        if i - last_refit >= refit or coefs_a is None:
            train_start = max(0, pos - window)
            train_data = feat.iloc[train_start:pos]

            if len(train_data) < 100:
                continue

            y_train = train_data["target"].values
            X_a = train_data[har_cols].values
            X_b = train_data[cal_cols].values

            try:
                coefs_a = fit_har(X_a, y_train)
                coefs_b = fit_har(X_b, y_train)
            except Exception:
                continue

            # Compute day-specific scaling factors from training data
            for wd in range(5):
                wd_mask = train_data.index.weekday == wd
                if wd_mask.sum() > 10:
                    wd_actual = train_data.loc[wd_mask, "target"].values
                    # HAR forecast for those days
                    X_wd = train_data.loc[wd_mask, har_cols].values
                    X_wd_c = np.column_stack([np.ones(len(X_wd)), X_wd])
                    har_pred = X_wd_c @ coefs_a
                    har_pred = np.maximum(har_pred, 1e-12)
                    # Scale = mean(actual) / mean(forecast)
                    day_scale[wd] = np.mean(wd_actual) / np.mean(har_pred)

            last_refit = i

        if coefs_a is None:
            continue

        # Forecast
        x_a = feat.loc[date, har_cols].values
        x_b = feat.loc[date, cal_cols].values

        pred_a = np.dot(np.append(1, x_a), coefs_a)
        pred_b = np.dot(np.append(1, x_b), coefs_b)

        # Model C: HAR * day scale
        wd = date.weekday()
        pred_c = pred_a * day_scale[wd]

        # Ensure positive — use median r² as absolute floor to prevent
        # calendar dummies from producing nonsensical negative forecasts
        floor = 1e-8
        pred_a = max(pred_a, floor)
        pred_b = max(pred_b, floor)
        pred_c = max(pred_c, floor)

        actual = feat.loc[date, "target"]
        if np.isnan(actual):
            continue

        forecasts_a.append(pred_a)
        forecasts_b.append(pred_b)
        forecasts_c.append(pred_c)
        actuals.append(actual)

    forecasts_a = np.array(forecasts_a)
    forecasts_b = np.array(forecasts_b)
    forecasts_c = np.array(forecasts_c)
    actuals = np.array(actuals)

    n_oos = len(actuals)
    if n_oos < 50:
        print(f"    Only {n_oos} valid OOS forecasts, insufficient")
        return None

    print(f"    Valid OOS forecasts: {n_oos}")

    # QLIKE losses
    qlike_a = qlike_loss(actuals, forecasts_a)
    qlike_b = qlike_loss(actuals, forecasts_b)
    qlike_c = qlike_loss(actuals, forecasts_c)

    print(f"    QLIKE HAR:          {qlike_a:.6f}")
    print(f"    QLIKE HAR+Calendar: {qlike_b:.6f}")
    print(f"    QLIKE HAR*DayScale: {qlike_c:.6f}")

    # Per-observation losses for DM test
    loss_a = np.log(forecasts_a) + actuals / forecasts_a
    loss_b = np.log(forecasts_b) + actuals / forecasts_b
    loss_c = np.log(forecasts_c) + actuals / forecasts_c

    # DM tests: B vs A, C vs A
    dm_ba_t, dm_ba_p = dm_test(loss_b, loss_a, h=1)
    dm_ca_t, dm_ca_p = dm_test(loss_c, loss_a, h=1)
    dm_bc_t, dm_bc_p = dm_test(loss_b, loss_c, h=1)

    print(f"    DM(HAR+Cal vs HAR): t={dm_ba_t:.4f}, p={dm_ba_p:.4f}")
    print(f"    DM(HAR*Day vs HAR): t={dm_ca_t:.4f}, p={dm_ca_p:.4f}")
    print(f"    DM(HAR+Cal vs HAR*Day): t={dm_bc_t:.4f}, p={dm_bc_p:.4f}")

    # Relative QLIKE improvement
    qlike_pct_b = (qlike_b / qlike_a - 1) * 100
    qlike_pct_c = (qlike_c / qlike_a - 1) * 100

    results = {
        "n_oos": int(n_oos),
        "oos_period": f"{oos_start} to {oos_end}",
        "qlike_har": float(qlike_a),
        "qlike_har_calendar": float(qlike_b),
        "qlike_har_dayscale": float(qlike_c),
        "qlike_pct_change_calendar": float(qlike_pct_b),
        "qlike_pct_change_dayscale": float(qlike_pct_c),
        "dm_test_calendar_vs_har": {
            "t_stat": float(dm_ba_t),
            "p_value": float(dm_ba_p),
            "better_model": "HAR+Calendar" if dm_ba_t < 0 else "HAR",
        },
        "dm_test_dayscale_vs_har": {
            "t_stat": float(dm_ca_t),
            "p_value": float(dm_ca_p),
            "better_model": "HAR*DayScale" if dm_ca_t < 0 else "HAR",
        },
        "dm_test_calendar_vs_dayscale": {
            "t_stat": float(dm_bc_t),
            "p_value": float(dm_bc_p),
        },
        "day_scaling_factors": {
            "Monday": float(day_scale[0]),
            "Tuesday": float(day_scale[1]),
            "Wednesday": float(day_scale[2]),
            "Thursday": float(day_scale[3]),
            "Friday": float(day_scale[4]),
        },
    }

    return results


# ============================================================================
# 5. GJR-GARCH + Calendar Scaling
# ============================================================================

def gjr_garch_calendar_test(r2, log_ret, cal, oos_start, oos_end,
                            window=ROLLING_WINDOW, refit=REFIT_EVERY, asset_name="SPY"):
    """
    Compare GJR-GARCH vs GJR-GARCH with calendar scaling overlay.
    The calendar scaling multiplies GJR forecast by a day-specific factor
    learned from in-sample ratios.
    """
    print(f"\n  --- GJR-GARCH + Calendar Scaling ({asset_name}) ---")

    try:
        from arch import arch_model
    except ImportError:
        print("    arch package not available, skipping GJR test")
        return None

    ret_series = log_ret * 100  # percentage returns for arch

    oos_start_dt = pd.Timestamp(oos_start)
    oos_end_dt = pd.Timestamp(oos_end)

    # Get aligned dates
    common_idx = ret_series.index.intersection(r2.index)
    common_idx = common_idx[(common_idx >= oos_start_dt) & (common_idx <= oos_end_dt)]

    if len(common_idx) < 50:
        print(f"    Only {len(common_idx)} OOS dates, skipping")
        return None

    print(f"    OOS observations: {len(common_idx)}")

    forecasts_gjr = []
    forecasts_gjr_cal = []
    actuals = []
    last_refit = -refit
    gjr_model_res = None
    day_scale_gjr = np.ones(5)

    for i, date in enumerate(common_idx):
        pos = ret_series.index.get_loc(date)

        # Refit
        if i - last_refit >= refit or gjr_model_res is None:
            train_start = max(0, pos - window)
            train_data = ret_series.iloc[train_start:pos]

            if len(train_data) < 500:
                continue

            try:
                am = arch_model(train_data, vol="Garch", p=1, o=1, q=1,
                                mean="Constant", dist="normal")
                gjr_model_res = am.fit(disp="off", show_warning=False)
            except Exception:
                continue

            # Compute day-specific scaling from training data
            train_dates = train_data.index
            train_r2 = r2.reindex(train_dates).dropna()
            # Get conditional variance from fitted model
            cond_var = gjr_model_res.conditional_volatility ** 2 / 10000  # back to decimal
            cond_var = cond_var.reindex(train_r2.index)

            for wd in range(5):
                wd_mask = train_r2.index.weekday == wd
                if wd_mask.sum() > 20:
                    actual_wd = train_r2[wd_mask].values
                    pred_wd = cond_var[wd_mask].dropna().values
                    if len(pred_wd) > 0 and np.mean(pred_wd) > 0:
                        day_scale_gjr[wd] = np.mean(actual_wd[:len(pred_wd)]) / np.mean(pred_wd)

            last_refit = i

        if gjr_model_res is None:
            continue

        # One-step forecast
        try:
            fc = gjr_model_res.forecast(horizon=1, reindex=False)
            var_forecast = fc.variance.values[-1, 0] / 10000  # decimal
        except Exception:
            continue

        var_forecast = max(var_forecast, 1e-12)

        # Calendar-scaled forecast
        wd = date.weekday()
        var_cal = var_forecast * day_scale_gjr[wd]
        var_cal = max(var_cal, 1e-12)

        actual = r2.get(date, np.nan)
        if np.isnan(actual):
            continue

        forecasts_gjr.append(var_forecast)
        forecasts_gjr_cal.append(var_cal)
        actuals.append(actual)

    forecasts_gjr = np.array(forecasts_gjr)
    forecasts_gjr_cal = np.array(forecasts_gjr_cal)
    actuals = np.array(actuals)

    n_oos = len(actuals)
    if n_oos < 50:
        print(f"    Only {n_oos} valid forecasts, insufficient")
        return None

    print(f"    Valid OOS forecasts: {n_oos}")

    qlike_gjr = qlike_loss(actuals, forecasts_gjr)
    qlike_gjr_cal = qlike_loss(actuals, forecasts_gjr_cal)

    print(f"    QLIKE GJR:         {qlike_gjr:.6f}")
    print(f"    QLIKE GJR+CalScale: {qlike_gjr_cal:.6f}")

    loss_gjr = np.log(np.maximum(forecasts_gjr, 1e-12)) + actuals / np.maximum(forecasts_gjr, 1e-12)
    loss_cal = np.log(np.maximum(forecasts_gjr_cal, 1e-12)) + actuals / np.maximum(forecasts_gjr_cal, 1e-12)

    dm_t, dm_p = dm_test(loss_cal, loss_gjr, h=1)
    qlike_pct = (qlike_gjr_cal / qlike_gjr - 1) * 100

    print(f"    DM(GJR+Cal vs GJR): t={dm_t:.4f}, p={dm_p:.4f}")
    print(f"    QLIKE change: {qlike_pct:+.3f}%")

    results = {
        "n_oos": int(n_oos),
        "qlike_gjr": float(qlike_gjr),
        "qlike_gjr_calendar_scale": float(qlike_gjr_cal),
        "qlike_pct_change": float(qlike_pct),
        "dm_test": {
            "t_stat": float(dm_t),
            "p_value": float(dm_p),
            "better_model": "GJR+CalScale" if dm_t < 0 else "GJR",
        },
        "day_scaling_factors": {
            "Monday": float(day_scale_gjr[0]),
            "Tuesday": float(day_scale_gjr[1]),
            "Wednesday": float(day_scale_gjr[2]),
            "Thursday": float(day_scale_gjr[3]),
            "Friday": float(day_scale_gjr[4]),
        },
    }

    return results


# ============================================================================
# 6. Main Analysis
# ============================================================================

print("\n" + "=" * 72)
print("PATTERN ANALYSIS (Full Sample)")
print("=" * 72)

all_results = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Day-of-Week and Calendar Volatility Patterns",
    "data_source": "yfinance",
    "analysis_period": f"{ANALYSIS_START} to {DATA_END}",
    "oos_period": f"{OOS_START} to {OOS_END}",
    "bootstrap_reps": BOOTSTRAP_REPS,
    "rolling_window": ROLLING_WINDOW,
    "refit_every": REFIT_EVERY,
    "assets": {},
    "cross_asset_summary": {},
    "forecasting": {},
    "conclusions": {},
}

# ---- 6a. Pattern analysis per asset ----
for asset_name in ["SPY", "GLD", "0050.TW"]:
    if asset_name not in asset_data:
        print(f"\n  Skipping {asset_name} (data not available)")
        continue

    print(f"\n{'='*72}")
    print(f"  ASSET: {asset_name}")
    print(f"{'='*72}")

    r2 = asset_data[asset_name]["r2"]
    log_ret = asset_data[asset_name]["log_ret"]

    # Filter to analysis period
    mask = r2.index >= pd.Timestamp(ANALYSIS_START)
    r2_a = r2[mask]
    log_ret_a = log_ret[mask]

    cal = add_calendar_features(r2_a.index)

    asset_results = {
        "n_observations": int(len(r2_a)),
        "period": f"{r2_a.index[0].date()} to {r2_a.index[-1].date()}",
        "descriptive": {
            "mean_r2": float(r2_a.mean()),
            "median_r2": float(r2_a.median()),
            "std_r2": float(r2_a.std()),
            "skew_r2": float(r2_a.skew()),
            "kurtosis_r2": float(r2_a.kurtosis()),
        },
    }

    # Pattern analyses
    asset_results["day_of_week"] = analyze_day_of_week(r2_a, cal)
    asset_results["month_of_year"] = analyze_month_of_year(r2_a, cal)
    asset_results["fomc_effect"] = analyze_fomc_effect(r2_a, cal)
    asset_results["opex_effect"] = analyze_opex_effect(r2_a, cal)
    asset_results["turn_of_month"] = analyze_tom_effect(r2_a, cal)
    asset_results["quarter_end"] = analyze_quarter_end(r2_a, cal)
    asset_results["pre_holiday"] = analyze_pre_holiday(r2_a, cal)

    all_results["assets"][asset_name] = asset_results

# ---- 6b. Cross-asset comparison ----
print(f"\n{'='*72}")
print("CROSS-ASSET COMPARISON")
print(f"{'='*72}")

# Compare day-of-week patterns across assets
weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
cross_dow = {}
for wd in weekday_names:
    cross_dow[wd] = {}
    for asset_name in all_results["assets"]:
        dow_data = all_results["assets"][asset_name].get("day_of_week", {})
        if wd in dow_data:
            cross_dow[wd][asset_name] = dow_data[wd]["mean_r2"]

all_results["cross_asset_summary"]["day_of_week_means"] = cross_dow

# Compare significant effects
sig_summary = {}
for asset_name in all_results["assets"]:
    sig = []
    a = all_results["assets"][asset_name]

    # Check day-of-week significance
    kw = a.get("day_of_week", {}).get("kruskal_wallis", {})
    if kw.get("p_value", 1) < 0.05:
        sig.append(f"day_of_week (KW p={kw['p_value']:.4f})")

    # Check Monday effect
    mon = a.get("day_of_week", {}).get("monday_effect", {})
    if mon.get("p_value", 1) < 0.05:
        sig.append(f"Monday effect (p={mon['p_value']:.4f})")

    # Check FOMC
    fomc = a.get("fomc_effect", {})
    if fomc.get("p_value", 1) < 0.05:
        sig.append(f"FOMC (p={fomc['p_value']:.4f})")

    # Check OpEx
    opex = a.get("opex_effect", {})
    if opex.get("p_value", 1) < 0.05:
        sig.append(f"OpEx (p={opex['p_value']:.4f})")

    # Check ToM
    tom = a.get("turn_of_month", {})
    if tom.get("p_value", 1) < 0.05:
        sig.append(f"Turn-of-Month (p={tom['p_value']:.4f})")

    # Check Quarter-end
    qe = a.get("quarter_end", {})
    if qe.get("p_value", 1) < 0.05:
        sig.append(f"Quarter-End (p={qe['p_value']:.4f})")

    # Check pre-holiday
    ph = a.get("pre_holiday", {})
    if ph.get("p_value", 1) < 0.05:
        sig.append(f"Pre-Holiday (p={ph['p_value']:.4f})")

    sig_summary[asset_name] = sig if sig else ["No significant effects at p<0.05"]

all_results["cross_asset_summary"]["significant_effects"] = sig_summary

print("\n  Significant effects (p < 0.05):")
for asset_name, effects in sig_summary.items():
    print(f"    {asset_name}: {', '.join(effects)}")

# ---- 6c. Forecasting tests ----
print(f"\n{'='*72}")
print("FORECASTING TESTS (OOS 2023-2024)")
print(f"{'='*72}")

for asset_name in ["SPY", "GLD", "0050.TW"]:
    if asset_name not in asset_data:
        continue

    r2 = asset_data[asset_name]["r2"]
    log_ret = asset_data[asset_name]["log_ret"]
    cal = add_calendar_features(r2.index)

    # HAR-based test
    har_result = rolling_oos_forecast(r2, cal, OOS_START, OOS_END, asset_name=asset_name)
    if har_result:
        all_results["forecasting"][f"{asset_name}_har"] = har_result

    # GJR-GARCH test (only for SPY to save time)
    if asset_name == "SPY":
        gjr_result = gjr_garch_calendar_test(r2, log_ret, cal, OOS_START, OOS_END, asset_name=asset_name)
        if gjr_result:
            all_results["forecasting"][f"{asset_name}_gjr"] = gjr_result

# ---- 6d. Stability analysis: sub-periods ----
print(f"\n{'='*72}")
print("STABILITY ANALYSIS: Day-of-Week by Sub-Period")
print(f"{'='*72}")

if "SPY" in asset_data:
    r2_spy = asset_data["SPY"]["r2"]
    cal_spy = add_calendar_features(r2_spy.index)

    sub_periods = [
        ("2006-2010 (GFC era)", "2006-01-01", "2010-12-31"),
        ("2011-2015 (Recovery)", "2011-01-01", "2015-12-31"),
        ("2016-2019 (Pre-COVID)", "2016-01-01", "2019-12-31"),
        ("2020-2024 (COVID+)", "2020-01-01", "2024-12-31"),
    ]

    stability = {}
    for period_name, p_start, p_end in sub_periods:
        mask = (r2_spy.index >= pd.Timestamp(p_start)) & (r2_spy.index <= pd.Timestamp(p_end))
        r2_sub = r2_spy[mask]
        cal_sub = add_calendar_features(r2_sub.index)

        print(f"\n  {period_name}:")
        period_result = {}
        for wd in range(5):
            wd_mask = cal_sub["weekday"] == wd
            vals = r2_sub[wd_mask].dropna().values
            period_result[weekday_names[wd]] = {
                "mean_r2": float(np.mean(vals)),
                "n": int(len(vals)),
            }
            print(f"    {weekday_names[wd]:12s}: mean r²={np.mean(vals):.6f}  n={len(vals)}")

        # KW test for this sub-period
        groups = [r2_sub[cal_sub["weekday"] == wd].dropna().values for wd in range(5)]
        kw_stat, kw_p = stats.kruskal(*groups)
        period_result["kruskal_wallis_p"] = float(kw_p)
        print(f"    KW p={kw_p:.4f}")

        stability[period_name] = period_result

    all_results["stability_sub_periods"] = stability

    # Check if pattern is consistent
    pattern_consistent = all(
        stability[p].get("kruskal_wallis_p", 1) < 0.10
        for p in stability
    )
    all_results["cross_asset_summary"]["weekday_pattern_stable"] = pattern_consistent
    print(f"\n  Weekday pattern stable across all sub-periods? {pattern_consistent}")


# ============================================================================
# 7. Conclusions
# ============================================================================
print(f"\n{'='*72}")
print("CONCLUSIONS")
print(f"{'='*72}")

conclusions = []

# Check SPY day-of-week
if "SPY" in all_results["assets"]:
    spy_dow = all_results["assets"]["SPY"].get("day_of_week", {})
    kw_p = spy_dow.get("kruskal_wallis", {}).get("p_value", 1)
    if kw_p < 0.05:
        conclusions.append(f"SPY day-of-week vol differences SIGNIFICANT (KW p={kw_p:.4f})")
    else:
        conclusions.append(f"SPY day-of-week vol differences NOT significant (KW p={kw_p:.4f})")

    # Monday effect
    mon = spy_dow.get("monday_effect", {})
    mon_p = mon.get("p_value", 1)
    mon_ratio = mon.get("monday_vs_rest_ratio", 1)
    if mon_p < 0.05:
        conclusions.append(f"SPY Monday effect SIGNIFICANT: ratio={mon_ratio:.3f} (p={mon_p:.4f})")
    else:
        conclusions.append(f"SPY Monday effect not significant (p={mon_p:.4f})")

    # FOMC
    fomc = all_results["assets"]["SPY"].get("fomc_effect", {})
    fomc_p = fomc.get("p_value", 1)
    fomc_pct = fomc.get("pct_increase")
    if fomc_p < 0.05 and fomc_pct is not None:
        conclusions.append(f"FOMC day vol +{fomc_pct:.1f}% higher (p={fomc_p:.4f}) — confirms K513")

# Forecasting
for key in all_results["forecasting"]:
    fc = all_results["forecasting"][key]
    if fc is None:
        continue
    if "dm_test_calendar_vs_har" in fc:
        dm = fc["dm_test_calendar_vs_har"]
        pct = fc.get("qlike_pct_change_calendar", 0)
        if dm["p_value"] < 0.05:
            conclusions.append(f"{key}: HAR+Calendar {'beats' if pct < 0 else 'loses to'} HAR "
                             f"(QLIKE {pct:+.3f}%, DM p={dm['p_value']:.4f})")
        else:
            conclusions.append(f"{key}: Calendar overlay NO significant improvement "
                             f"(QLIKE {pct:+.3f}%, DM p={dm['p_value']:.4f})")

    if "dm_test" in fc and "qlike_gjr" in fc:
        dm = fc["dm_test"]
        pct = fc.get("qlike_pct_change", 0)
        conclusions.append(f"{key}: GJR+CalScale vs GJR: QLIKE {pct:+.3f}%, DM p={dm['p_value']:.4f}")

all_results["conclusions"] = conclusions

for c in conclusions:
    print(f"  • {c}")

# ============================================================================
# 8. Save Results
# ============================================================================
elapsed = time.time() - START_TIME
all_results["runtime_seconds"] = float(elapsed)
all_results["timestamp"] = datetime.now(timezone.utc).isoformat()

# Find output path (handle worktree)
out_dir = Path(__file__).parent
results_path = out_dir / "k631_results.json"

# Also try main repo
main_results_path = Path(MAIN_REPO) / "experiments" / "k631_results.json"

with open(results_path, "w") as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")

# Copy to main repo if in worktree
if str(out_dir) != str(Path(MAIN_REPO) / "experiments"):
    try:
        import shutil
        main_results_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(results_path, main_results_path)
        # Also copy script
        shutil.copy2(__file__, Path(MAIN_REPO) / "experiments" / "k631_calendar_vol.py")
        print(f"Copied to {main_results_path}")
    except Exception as e:
        print(f"Note: Could not copy to main repo: {e}")

print(f"\nTotal runtime: {elapsed:.1f} seconds")
print(f"\n{'='*72}")
print(f"{EXPERIMENT_ID} COMPLETE")
print(f"{'='*72}")
