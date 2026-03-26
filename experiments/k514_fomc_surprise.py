#!/usr/bin/env python3
"""
K514: FOMC Surprise Impact on Volatility
[提出: Codex event-surprise 建議, 執行: Claude]

Research Questions:
1. Does FOMC surprise magnitude predict 5-21 day forward vol?
2. Do large surprises (VIX change > 2σ) trigger vol regime shifts?
3. Can a simple FOMC surprise-based strategy improve VT?

Method:
- FOMC surprise proxy: VIX change on FOMC day (ΔVIXₜ)
- Alternative: |SPY return| on FOMC day (surprise magnitude)
- Baseline: lagged RV → next h-day vol
- Test: baseline + FOMC surprise variables

Prior Knowledge:
- K96: Surprise is key driver (R²=0.67), dovish→VIX↑, hawkish→VIX↓
- K513: FOMC day vol +28% higher than normal (significant)
- K414: Fed rate calendar dummy → null (calendar ≠ surprise)
- K498: Calendar dummy approach → null

References:
- Bernanke & Kuttner (2005) JoF — fed funds futures surprise
- Lucca & Moench (2015) — pre-FOMC drift (K96: no longer holds)

Data: SPY + VIX from yfinance, 2005-2025
"""

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────
# 1. FOMC Meeting Dates (2005-2025)
# ──────────────────────────────────────────────────
# Source: Federal Reserve Board of Governors
# https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Using second day of 2-day meetings, single day for 1-day meetings

FOMC_DATES_STR = [
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
]


def download_data():
    """Download SPY and VIX data from yfinance with retry."""
    print("Downloading SPY and VIX data (2004-2025)...")

    def _download_with_retry(ticker, start, end, max_retries=3):
        for attempt in range(max_retries):
            try:
                data = yf.download(ticker, start=start, end=end, progress=False)
                if data is not None and len(data) > 0:
                    return data
            except Exception as e:
                print(f"  Attempt {attempt+1} for {ticker} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
        raise RuntimeError(f"Failed to download {ticker} after {max_retries} attempts")

    spy = _download_with_retry("SPY", "2004-01-01", "2025-12-31")
    time.sleep(1)  # rate limit buffer
    vix = _download_with_retry("^VIX", "2004-01-01", "2025-12-31")

    # Handle MultiIndex columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    spy_close = spy["Close"].squeeze()
    vix_close = vix["Close"].squeeze()

    # Ensure proper datetime index
    spy_close.index = pd.to_datetime(spy_close.index)
    vix_close.index = pd.to_datetime(vix_close.index)

    print(f"  SPY: {len(spy_close)} rows, VIX: {len(vix_close)} rows")
    return spy_close, vix_close


def build_dataset(spy_close, vix_close):
    """Build analysis dataset with FOMC indicators and surprise measures."""
    # SPY returns
    spy_ret = np.log(spy_close / spy_close.shift(1))

    # Realized volatility at different horizons
    rv5 = spy_ret.rolling(5).std() * np.sqrt(252)
    rv10 = spy_ret.rolling(10).std() * np.sqrt(252)
    rv21 = spy_ret.rolling(21).std() * np.sqrt(252)

    # Forward realized volatility (targets)
    fwd_rv5 = spy_ret.shift(-5).rolling(5).std() * np.sqrt(252)
    fwd_rv10 = spy_ret.shift(-10).rolling(10).std() * np.sqrt(252)
    fwd_rv21 = spy_ret.shift(-21).rolling(21).std() * np.sqrt(252)

    # VIX change
    vix_change = vix_close - vix_close.shift(1)  # absolute change
    vix_pct_change = vix_close.pct_change() * 100  # percent change

    # Combine into DataFrame
    df = pd.DataFrame({
        "spy_ret": spy_ret,
        "spy_abs_ret": spy_ret.abs(),
        "vix": vix_close,
        "vix_change": vix_change,
        "vix_pct_change": vix_pct_change,
        "rv5": rv5,
        "rv10": rv10,
        "rv21": rv21,
        "fwd_rv5": fwd_rv5,
        "fwd_rv10": fwd_rv10,
        "fwd_rv21": fwd_rv21,
    })

    # Parse FOMC dates and match to nearest trading day
    fomc_dates = pd.to_datetime(FOMC_DATES_STR)
    trading_days = df.index

    # For each FOMC date, find the nearest trading day (within 3 days)
    matched_fomc = []
    for fd in fomc_dates:
        # Find closest trading day
        diffs = abs(trading_days - fd)
        min_idx = diffs.argmin()
        if diffs[min_idx].days <= 3:
            matched_fomc.append(trading_days[min_idx])

    matched_fomc = pd.DatetimeIndex(matched_fomc).unique()

    # FOMC indicator
    df["is_fomc"] = 0
    df.loc[df.index.isin(matched_fomc), "is_fomc"] = 1

    # FOMC surprise measures (only on FOMC days)
    df["fomc_vix_change"] = np.nan
    df["fomc_vix_pct"] = np.nan
    df["fomc_abs_ret"] = np.nan

    fomc_mask = df["is_fomc"] == 1
    df.loc[fomc_mask, "fomc_vix_change"] = df.loc[fomc_mask, "vix_change"]
    df.loc[fomc_mask, "fomc_vix_pct"] = df.loc[fomc_mask, "vix_pct_change"]
    df.loc[fomc_mask, "fomc_abs_ret"] = df.loc[fomc_mask, "spy_abs_ret"]

    # Forward-fill FOMC surprise for regression (surprise persists until next FOMC)
    df["last_fomc_vix_change"] = df["fomc_vix_change"].ffill()
    df["last_fomc_vix_pct"] = df["fomc_vix_pct"].ffill()
    df["last_fomc_abs_ret"] = df["fomc_abs_ret"].ffill()

    # Days since last FOMC
    fomc_idx = df.index[fomc_mask]
    df["days_since_fomc"] = np.nan
    for i, row_date in enumerate(df.index):
        past_fomc = fomc_idx[fomc_idx <= row_date]
        if len(past_fomc) > 0:
            df.loc[row_date, "days_since_fomc"] = (row_date - past_fomc[-1]).days

    return df, matched_fomc


def descriptive_stats(df, matched_fomc):
    """Step 1: Descriptive statistics and data diagnostics."""
    print("\n" + "=" * 70)
    print("STEP 1: DESCRIPTIVE STATISTICS & DATA DIAGNOSTICS")
    print("=" * 70)

    fomc_df = df[df["is_fomc"] == 1].copy()
    non_fomc_df = df[df["is_fomc"] == 0].copy()

    n_fomc = len(fomc_df)
    date_range = f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}"

    print(f"\nData range: {date_range}")
    print(f"Total trading days: {len(df)}")
    print(f"FOMC days matched: {n_fomc}")
    print(f"Non-FOMC days: {len(non_fomc_df)}")

    # VIX change on FOMC days
    fomc_vix = fomc_df["vix_change"].dropna()
    print(f"\n--- VIX Change on FOMC Days ---")
    print(f"  Mean: {fomc_vix.mean():.3f}")
    print(f"  Std:  {fomc_vix.std():.3f}")
    print(f"  Min:  {fomc_vix.min():.3f}")
    print(f"  Max:  {fomc_vix.max():.3f}")
    print(f"  Skew: {fomc_vix.skew():.3f}")
    print(f"  Kurt: {fomc_vix.kurtosis():.3f}")

    # SPY |return| on FOMC days
    fomc_absret = fomc_df["spy_abs_ret"].dropna()
    non_fomc_absret = non_fomc_df["spy_abs_ret"].dropna()
    print(f"\n--- |SPY Return| on FOMC vs Non-FOMC ---")
    print(f"  FOMC mean:     {fomc_absret.mean()*100:.3f}%")
    print(f"  Non-FOMC mean: {non_fomc_absret.mean()*100:.3f}%")
    t_absret, p_absret = stats.ttest_ind(fomc_absret, non_fomc_absret)
    ratio = fomc_absret.mean() / non_fomc_absret.mean()
    print(f"  Ratio: {ratio:.3f}x")
    print(f"  t-stat: {t_absret:.3f}, p={p_absret:.4f}")

    # Surprise quartiles
    fomc_surprises = fomc_df["vix_change"].dropna()
    q25 = fomc_surprises.quantile(0.25)
    q75 = fomc_surprises.quantile(0.75)
    sigma2 = fomc_surprises.std() * 2
    print(f"\n--- FOMC Surprise Distribution ---")
    print(f"  Q25 (dovish): {q25:.3f}")
    print(f"  Q75 (hawkish): {q75:.3f}")
    print(f"  2σ threshold: ±{sigma2:.3f}")
    n_large_dovish = (fomc_surprises < -sigma2).sum()
    n_large_hawkish = (fomc_surprises > sigma2).sum()
    print(f"  Large dovish (< -2σ): {n_large_dovish}")
    print(f"  Large hawkish (> +2σ): {n_large_hawkish}")

    stats_dict = {
        "date_range": date_range,
        "n_total": len(df),
        "n_fomc": n_fomc,
        "fomc_vix_change_mean": float(fomc_vix.mean()),
        "fomc_vix_change_std": float(fomc_vix.std()),
        "fomc_absret_mean": float(fomc_absret.mean()),
        "non_fomc_absret_mean": float(non_fomc_absret.mean()),
        "absret_ratio": float(ratio),
        "absret_tstat": float(t_absret),
        "absret_pval": float(p_absret),
        "q25_vix_change": float(q25),
        "q75_vix_change": float(q75),
        "sigma2_threshold": float(sigma2),
        "n_large_dovish": int(n_large_dovish),
        "n_large_hawkish": int(n_large_hawkish),
    }

    return stats_dict


def regression_analysis(df):
    """Step 2: OLS regression — does FOMC surprise predict forward vol?"""
    print("\n" + "=" * 70)
    print("STEP 2: REGRESSION — FOMC SURPRISE → FORWARD VOLATILITY")
    print("=" * 70)

    results = {}

    for horizon, fwd_col, lag_col in [
        (5, "fwd_rv5", "rv5"),
        (10, "fwd_rv10", "rv10"),
        (21, "fwd_rv21", "rv21"),
    ]:
        print(f"\n--- Forward {horizon}-day RV ---")

        # Clean data: only rows where we have all variables
        cols_needed = [fwd_col, lag_col, "last_fomc_vix_change", "last_fomc_abs_ret", "days_since_fomc"]
        reg_df = df[cols_needed].dropna()

        # Filter to 2005+ and ensure sufficient data
        reg_df = reg_df[reg_df.index >= "2005-01-01"]
        n = len(reg_df)

        if n < 100:
            print(f"  Insufficient data (n={n}), skipping")
            continue

        y = reg_df[fwd_col].values
        X_base = reg_df[[lag_col]].values

        # Model 1: Baseline (lagged RV only)
        X1 = np.column_stack([np.ones(n), X_base])
        beta1 = np.linalg.lstsq(X1, y, rcond=None)[0]
        yhat1 = X1 @ beta1
        resid1 = y - yhat1
        sse1 = np.sum(resid1 ** 2)
        sst = np.sum((y - y.mean()) ** 2)
        r2_base = 1 - sse1 / sst

        # Residual standard error
        se1 = np.sqrt(sse1 / (n - X1.shape[1]))
        cov1 = se1**2 * np.linalg.inv(X1.T @ X1)
        t1 = beta1 / np.sqrt(np.diag(cov1))

        print(f"  Model 1 (baseline): R²={r2_base:.4f}, n={n}")
        print(f"    Intercept: {beta1[0]:.4f} (t={t1[0]:.2f})")
        print(f"    Lagged RV: {beta1[1]:.4f} (t={t1[1]:.2f})")

        # Model 2: + FOMC VIX surprise
        X2 = np.column_stack([np.ones(n), X_base, reg_df["last_fomc_vix_change"].values])
        beta2 = np.linalg.lstsq(X2, y, rcond=None)[0]
        yhat2 = X2 @ beta2
        resid2 = y - yhat2
        sse2 = np.sum(resid2 ** 2)
        r2_m2 = 1 - sse2 / sst

        se2 = np.sqrt(sse2 / (n - X2.shape[1]))
        cov2 = se2**2 * np.linalg.inv(X2.T @ X2)
        t2 = beta2 / np.sqrt(np.diag(cov2))

        # F-test: Model 2 vs Model 1
        df1 = 1  # one additional regressor
        df2 = n - X2.shape[1]
        f_stat = ((sse1 - sse2) / df1) / (sse2 / df2)
        f_pval = 1 - stats.f.cdf(f_stat, df1, df2)

        print(f"  Model 2 (+VIX surprise): R²={r2_m2:.4f}, ΔR²={r2_m2-r2_base:.6f}")
        print(f"    VIX surprise coef: {beta2[2]:.6f} (t={t2[2]:.3f})")
        print(f"    F-test vs baseline: F={f_stat:.3f}, p={f_pval:.4f}")

        # Model 3: + |SPY return| magnitude
        X3 = np.column_stack([
            np.ones(n), X_base,
            reg_df["last_fomc_vix_change"].values,
            reg_df["last_fomc_abs_ret"].values,
        ])
        beta3 = np.linalg.lstsq(X3, y, rcond=None)[0]
        yhat3 = X3 @ beta3
        resid3 = y - yhat3
        sse3 = np.sum(resid3 ** 2)
        r2_m3 = 1 - sse3 / sst

        se3 = np.sqrt(sse3 / (n - X3.shape[1]))
        cov3 = se3**2 * np.linalg.inv(X3.T @ X3)
        t3 = beta3 / np.sqrt(np.diag(cov3))

        # F-test: Model 3 vs Model 1
        f_stat_3 = ((sse1 - sse3) / 2) / (sse3 / (n - X3.shape[1]))
        f_pval_3 = 1 - stats.f.cdf(f_stat_3, 2, n - X3.shape[1])

        print(f"  Model 3 (+VIX surprise + |ret|): R²={r2_m3:.4f}, ΔR²={r2_m3-r2_base:.6f}")
        print(f"    VIX surprise coef:  {beta3[2]:.6f} (t={t3[2]:.3f})")
        print(f"    |SPY ret| coef:     {beta3[3]:.6f} (t={t3[3]:.3f})")
        print(f"    F-test vs baseline: F={f_stat_3:.3f}, p={f_pval_3:.4f}")

        # Model 4: Days since FOMC interaction
        X4 = np.column_stack([
            np.ones(n), X_base,
            reg_df["last_fomc_vix_change"].values,
            reg_df["days_since_fomc"].values,
            reg_df["last_fomc_vix_change"].values * reg_df["days_since_fomc"].values,
        ])
        beta4 = np.linalg.lstsq(X4, y, rcond=None)[0]
        yhat4 = X4 @ beta4
        resid4 = y - yhat4
        sse4 = np.sum(resid4 ** 2)
        r2_m4 = 1 - sse4 / sst

        se4 = np.sqrt(sse4 / (n - X4.shape[1]))
        cov4 = se4**2 * np.linalg.inv(X4.T @ X4)
        t4 = beta4 / np.sqrt(np.diag(cov4))

        print(f"  Model 4 (+decay interaction): R²={r2_m4:.4f}, ΔR²={r2_m4-r2_base:.6f}")
        print(f"    VIX surprise:      {beta4[2]:.6f} (t={t4[2]:.3f})")
        print(f"    Days since FOMC:   {beta4[3]:.6f} (t={t4[3]:.3f})")
        print(f"    Surprise × Days:   {beta4[4]:.8f} (t={t4[4]:.3f})")

        results[f"h{horizon}"] = {
            "n": n,
            "r2_baseline": float(r2_base),
            "r2_m2_vix_surprise": float(r2_m2),
            "r2_m3_full": float(r2_m3),
            "r2_m4_decay": float(r2_m4),
            "delta_r2_m2": float(r2_m2 - r2_base),
            "delta_r2_m3": float(r2_m3 - r2_base),
            "delta_r2_m4": float(r2_m4 - r2_base),
            "vix_surprise_t_m2": float(t2[2]),
            "vix_surprise_t_m3": float(t3[2]),
            "absret_t_m3": float(t3[3]),
            "f_stat_m2": float(f_stat),
            "f_pval_m2": float(f_pval),
            "f_stat_m3": float(f_stat_3),
            "f_pval_m3": float(f_pval_3),
            "decay_interaction_t": float(t4[4]),
        }

    return results


def large_surprise_analysis(df):
    """Step 3: Large surprise events — regime shift analysis."""
    print("\n" + "=" * 70)
    print("STEP 3: LARGE SURPRISE ANALYSIS (TOP/BOTTOM QUARTILE)")
    print("=" * 70)

    fomc_df = df[df["is_fomc"] == 1].dropna(subset=["vix_change", "fwd_rv5", "fwd_rv21"]).copy()
    vix_changes = fomc_df["vix_change"]

    # Quartile thresholds
    q25 = vix_changes.quantile(0.25)
    q75 = vix_changes.quantile(0.75)

    # Also 2σ threshold
    sigma = vix_changes.std()
    sigma2 = 2 * sigma

    results = {}

    for label, mask_func, threshold_desc in [
        ("top_quartile_hawkish", lambda x: x > q75, f"VIX Δ > {q75:.2f} (Q75)"),
        ("bottom_quartile_dovish", lambda x: x < q25, f"VIX Δ < {q25:.2f} (Q25)"),
        ("large_hawkish_2sigma", lambda x: x > sigma2, f"VIX Δ > {sigma2:.2f} (2σ)"),
        ("large_dovish_2sigma", lambda x: x < -sigma2, f"VIX Δ < {-sigma2:.2f} (-2σ)"),
        ("middle_50pct", lambda x: (x >= q25) & (x <= q75), f"Q25 ≤ VIX Δ ≤ Q75"),
    ]:
        subset = fomc_df[mask_func(vix_changes)]
        n = len(subset)

        if n < 5:
            print(f"\n{label}: n={n}, insufficient data")
            results[label] = {"n": n, "note": "insufficient data"}
            continue

        # Forward vol after these events
        fwd5_mean = subset["fwd_rv5"].mean()
        fwd21_mean = subset["fwd_rv21"].mean()

        # Compare to all FOMC
        all_fwd5 = fomc_df["fwd_rv5"].mean()
        all_fwd21 = fomc_df["fwd_rv21"].mean()

        # Compare to middle 50%
        middle = fomc_df[(vix_changes >= q25) & (vix_changes <= q75)]
        mid_fwd5 = middle["fwd_rv5"].mean()
        mid_fwd21 = middle["fwd_rv21"].mean()

        # t-test: subset vs middle
        if label != "middle_50pct" and len(middle) > 5:
            t5, p5 = stats.ttest_ind(subset["fwd_rv5"], middle["fwd_rv5"])
            t21, p21 = stats.ttest_ind(subset["fwd_rv21"], middle["fwd_rv21"])
        else:
            t5, p5, t21, p21 = 0, 1, 0, 1

        print(f"\n{label} ({threshold_desc}): n={n}")
        print(f"  Fwd 5d RV:  {fwd5_mean:.4f} (all FOMC: {all_fwd5:.4f}, mid: {mid_fwd5:.4f})")
        print(f"  Fwd 21d RV: {fwd21_mean:.4f} (all FOMC: {all_fwd21:.4f}, mid: {mid_fwd21:.4f})")
        if label != "middle_50pct":
            print(f"  vs middle t-test (5d):  t={t5:.3f}, p={p5:.4f}")
            print(f"  vs middle t-test (21d): t={t21:.3f}, p={p21:.4f}")

        results[label] = {
            "n": int(n),
            "threshold": threshold_desc,
            "fwd_rv5_mean": float(fwd5_mean),
            "fwd_rv21_mean": float(fwd21_mean),
            "all_fomc_fwd5": float(all_fwd5),
            "all_fomc_fwd21": float(all_fwd21),
            "vs_middle_t5": float(t5),
            "vs_middle_p5": float(p5),
            "vs_middle_t21": float(t21),
            "vs_middle_p21": float(p21),
        }

    return results


def oos_prediction_test(df):
    """Step 4: Out-of-sample prediction test — expanding window."""
    print("\n" + "=" * 70)
    print("STEP 4: OUT-OF-SAMPLE PREDICTION TEST (EXPANDING WINDOW)")
    print("=" * 70)

    # Focus on 21-day forward vol (most policy-relevant)
    cols = ["fwd_rv21", "rv21", "last_fomc_vix_change"]
    reg_df = df[cols].dropna()
    reg_df = reg_df[reg_df.index >= "2005-01-01"]

    # IS: 2005-2015, OOS: 2016-2024
    is_end = "2015-12-31"
    oos_start = "2016-01-01"

    is_df = reg_df[reg_df.index <= is_end]
    oos_df = reg_df[reg_df.index >= oos_start]

    n_is = len(is_df)
    n_oos = len(oos_df)

    print(f"\nIS period: 2005-2015, n={n_is}")
    print(f"OOS period: 2016-2024+, n={n_oos}")

    if n_oos < 100:
        print("Insufficient OOS data")
        return {"error": "insufficient OOS data"}

    # Expanding window OOS forecasts
    base_errors = []
    surprise_errors = []

    all_data = reg_df.copy()
    all_idx = all_data.index

    # Find where OOS starts
    oos_mask = all_idx >= oos_start
    oos_indices = all_idx[oos_mask]

    # Use vectorized approach for speed: re-estimate every 21 days
    reestimate_freq = 21
    current_beta_base = None
    current_beta_surp = None

    for i, oos_date in enumerate(oos_indices):
        # Re-estimate parameters periodically
        if i % reestimate_freq == 0:
            train = all_data[all_data.index < oos_date]
            if len(train) < 252:
                continue

            y_tr = train["fwd_rv21"].values
            X_base_tr = np.column_stack([np.ones(len(train)), train["rv21"].values])
            X_surp_tr = np.column_stack([
                np.ones(len(train)),
                train["rv21"].values,
                train["last_fomc_vix_change"].values,
            ])

            current_beta_base = np.linalg.lstsq(X_base_tr, y_tr, rcond=None)[0]
            current_beta_surp = np.linalg.lstsq(X_surp_tr, y_tr, rcond=None)[0]

        if current_beta_base is None:
            continue

        row = all_data.loc[oos_date]
        y_actual = row["fwd_rv21"]

        # Baseline forecast
        x_base = np.array([1, row["rv21"]])
        yhat_base = x_base @ current_beta_base

        # Surprise forecast
        x_surp = np.array([1, row["rv21"], row["last_fomc_vix_change"]])
        yhat_surp = x_surp @ current_beta_surp

        # QLIKE loss: log(σ²_hat) + actual²/σ²_hat (using σ not σ²)
        # Since we predict annualized vol, use it directly
        if yhat_base > 0 and yhat_surp > 0:
            ql_base = np.log(yhat_base**2) + (y_actual**2) / (yhat_base**2)
            ql_surp = np.log(yhat_surp**2) + (y_actual**2) / (yhat_surp**2)
            base_errors.append(ql_base)
            surprise_errors.append(ql_surp)

    base_errors = np.array(base_errors)
    surprise_errors = np.array(surprise_errors)

    n_oos_used = len(base_errors)
    mean_base = base_errors.mean()
    mean_surp = surprise_errors.mean()

    # Diebold-Mariano test
    # loss_diff = surprise - base: positive means surprise WORSE (higher QLIKE loss)
    loss_diff = surprise_errors - base_errors
    dm_mean = loss_diff.mean()
    dm_se = loss_diff.std() / np.sqrt(len(loss_diff))
    dm_t = dm_mean / dm_se if dm_se > 0 else 0
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))

    # For QLIKE, lower = better. Improvement = (base - surprise) / |base| * 100
    # Positive improvement means surprise is better (lower QLIKE)
    pct_improve = (mean_base - mean_surp) / abs(mean_base) * 100
    surprise_is_better = mean_surp < mean_base

    print(f"\nOOS Results (n={n_oos_used}):")
    print(f"  Baseline QLIKE:  {mean_base:.6f}")
    print(f"  Surprise QLIKE:  {mean_surp:.6f}")
    print(f"  Surprise {'BETTER' if surprise_is_better else 'WORSE'} by {abs(pct_improve):.4f}%")
    print(f"  DM test (surprise-base): t={dm_t:.3f}, p={dm_p:.4f}")
    print(f"  Direction: {'surprise WORSE' if dm_t > 0 else 'surprise BETTER'}")
    print(f"  {'SIGNIFICANT' if abs(dm_t) > 1.96 else 'NOT SIGNIFICANT'}")

    results = {
        "n_is": n_is,
        "n_oos": n_oos_used,
        "qlike_baseline": float(mean_base),
        "qlike_surprise": float(mean_surp),
        "qlike_pct_diff": float(pct_improve),
        "surprise_is_better_oos": bool(surprise_is_better),
        "dm_t_surp_minus_base": float(dm_t),
        "dm_p": float(dm_p),
        "significant_at_005": bool(abs(dm_t) > 1.96),
        "interpretation": "positive DM t = surprise worse; negative DM t = surprise better",
    }

    return results


def strategy_backtest(df):
    """Step 5: Simple FOMC surprise strategy overlay on 12/VIX."""
    print("\n" + "=" * 70)
    print("STEP 5: FOMC SURPRISE STRATEGY OVERLAY")
    print("=" * 70)

    # Baseline: 12/VIX
    strat_df = df[["spy_ret", "vix", "last_fomc_vix_change", "days_since_fomc"]].dropna().copy()
    strat_df = strat_df[strat_df.index >= "2006-01-01"]  # need history for FOMC

    # Baseline 12/VIX weight (lagged)
    strat_df["w_base"] = (12.0 / strat_df["vix"]).clip(0, 1).shift(1)

    # Strategy: adjust weight based on last FOMC surprise
    # Dovish surprise (VIX dropped) → more confident → higher weight
    # Hawkish surprise (VIX rose) → less confident → lower weight
    # Only apply within 21 days of FOMC
    surprise_z = strat_df["last_fomc_vix_change"] / strat_df["last_fomc_vix_change"].rolling(252).std()

    # Adjustment: clip surprise effect, decay with time
    decay = np.exp(-strat_df["days_since_fomc"] / 10)  # half-life ~7 days
    adjustment = -0.1 * surprise_z * decay  # dovish (neg VIX change) → positive adj

    strat_df["w_surprise"] = (strat_df["w_base"] + adjustment.shift(1)).clip(0, 1)

    # Returns
    strat_df["ret_base"] = strat_df["w_base"] * strat_df["spy_ret"]
    strat_df["ret_surprise"] = strat_df["w_surprise"] * strat_df["spy_ret"]
    strat_df["ret_bh"] = strat_df["spy_ret"]

    # Drop NaN
    strat_df = strat_df.dropna(subset=["ret_base", "ret_surprise"])

    n_days = len(strat_df)
    n_years = n_days / 252

    # Performance metrics
    def compute_metrics(returns, label):
        ann_ret = returns.mean() * 252
        ann_vol = returns.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + returns).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        return {
            "label": label,
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "mdd": float(mdd),
        }

    base_m = compute_metrics(strat_df["ret_base"], "12/VIX baseline")
    surp_m = compute_metrics(strat_df["ret_surprise"], "12/VIX + FOMC surprise")
    bh_m = compute_metrics(strat_df["ret_bh"], "Buy & Hold SPY")

    print(f"\n{'Strategy':<30} {'Sharpe':>8} {'Ann.Ret':>10} {'Ann.Vol':>10} {'MDD':>8}")
    print("-" * 68)
    for m in [bh_m, base_m, surp_m]:
        print(f"{m['label']:<30} {m['sharpe']:>8.3f} {m['ann_return']:>9.2%} {m['ann_vol']:>9.2%} {m['mdd']:>7.2%}")

    # DM test on daily returns: surprise vs base
    diff = strat_df["ret_surprise"] - strat_df["ret_base"]
    dm_mean = diff.mean()
    dm_se = diff.std() / np.sqrt(len(diff))
    dm_t = dm_mean / dm_se if dm_se > 0 else 0

    print(f"\nSurprise overlay vs baseline:")
    print(f"  Mean daily Δreturn: {dm_mean*10000:.2f} bps")
    print(f"  t-stat: {dm_t:.3f}")
    print(f"  {'SIGNIFICANT' if abs(dm_t) > 3.0 else 'NOT SIGNIFICANT (Harvey t>3.0)'}")

    # Weight difference statistics
    w_diff = strat_df["w_surprise"] - strat_df["w_base"]
    print(f"\nWeight adjustment stats:")
    print(f"  Mean Δw: {w_diff.mean():.4f}")
    print(f"  Std Δw:  {w_diff.std():.4f}")
    print(f"  Max Δw:  {w_diff.max():.4f}")
    print(f"  Min Δw:  {w_diff.min():.4f}")

    results = {
        "n_days": n_days,
        "n_years": float(n_years),
        "buy_hold": bh_m,
        "baseline_12vix": base_m,
        "surprise_overlay": surp_m,
        "dm_t_vs_baseline": float(dm_t),
        "mean_weight_adjustment": float(w_diff.mean()),
        "std_weight_adjustment": float(w_diff.std()),
        "harvey_threshold_pass": bool(abs(dm_t) > 3.0),
    }

    return results


def subsample_robustness(df):
    """Step 6: Subsample robustness — does the relationship change over time?"""
    print("\n" + "=" * 70)
    print("STEP 6: SUBSAMPLE ROBUSTNESS")
    print("=" * 70)

    periods = [
        ("2005-2009 (GFC)", "2005-01-01", "2009-12-31"),
        ("2010-2014 (Recovery)", "2010-01-01", "2014-12-31"),
        ("2015-2019 (Normal+)", "2015-01-01", "2019-12-31"),
        ("2020-2025 (COVID+)", "2020-01-01", "2025-12-31"),
    ]

    results = {}

    for label, start, end in periods:
        sub = df[(df.index >= start) & (df.index <= end)]
        fomc_sub = sub[sub["is_fomc"] == 1].dropna(subset=["vix_change", "fwd_rv21"])

        if len(fomc_sub) < 10:
            print(f"\n{label}: n={len(fomc_sub)}, insufficient")
            continue

        # Correlation: FOMC VIX change → forward 21d RV
        corr_5, p_5 = stats.pearsonr(fomc_sub["vix_change"], fomc_sub["fwd_rv5"].dropna().reindex(fomc_sub.index).dropna())
        common = fomc_sub.dropna(subset=["vix_change", "fwd_rv21"])
        if len(common) < 10:
            continue
        corr_21, p_21 = stats.pearsonr(common["vix_change"], common["fwd_rv21"])

        n_fomc = len(fomc_sub)
        mean_surprise = fomc_sub["vix_change"].mean()

        print(f"\n{label}: {n_fomc} FOMC meetings")
        print(f"  Mean VIX surprise: {mean_surprise:.3f}")
        print(f"  Corr(surprise, fwd_5d_RV):  r={corr_5:.3f}, p={p_5:.4f}")
        print(f"  Corr(surprise, fwd_21d_RV): r={corr_21:.3f}, p={p_21:.4f}")

        results[label] = {
            "n_fomc": n_fomc,
            "mean_vix_surprise": float(mean_surprise),
            "corr_fwd5_r": float(corr_5),
            "corr_fwd5_p": float(p_5),
            "corr_fwd21_r": float(corr_21),
            "corr_fwd21_p": float(p_21),
        }

    return results


def direction_analysis(df):
    """Step 7: Dovish vs Hawkish direction — asymmetric impact?"""
    print("\n" + "=" * 70)
    print("STEP 7: DOVISH vs HAWKISH ASYMMETRY")
    print("=" * 70)

    fomc_df = df[df["is_fomc"] == 1].dropna(subset=["vix_change", "fwd_rv5", "fwd_rv21"]).copy()

    dovish = fomc_df[fomc_df["vix_change"] < 0]  # VIX dropped (market relieved)
    hawkish = fomc_df[fomc_df["vix_change"] > 0]  # VIX rose (market surprised)

    print(f"\nDovish FOMC (VIX ↓): n={len(dovish)}")
    print(f"  Mean VIX Δ:    {dovish['vix_change'].mean():.3f}")
    print(f"  Fwd 5d RV:     {dovish['fwd_rv5'].mean():.4f}")
    print(f"  Fwd 21d RV:    {dovish['fwd_rv21'].mean():.4f}")

    print(f"\nHawkish FOMC (VIX ↑): n={len(hawkish)}")
    print(f"  Mean VIX Δ:    {hawkish['vix_change'].mean():.3f}")
    print(f"  Fwd 5d RV:     {hawkish['fwd_rv5'].mean():.4f}")
    print(f"  Fwd 21d RV:    {hawkish['fwd_rv21'].mean():.4f}")

    # t-test: hawkish vs dovish
    t5, p5 = stats.ttest_ind(hawkish["fwd_rv5"], dovish["fwd_rv5"])
    t21, p21 = stats.ttest_ind(hawkish["fwd_rv21"], dovish["fwd_rv21"])

    print(f"\nHawkish vs Dovish t-test:")
    print(f"  5d fwd RV:  t={t5:.3f}, p={p5:.4f}")
    print(f"  21d fwd RV: t={t21:.3f}, p={p21:.4f}")

    results = {
        "dovish": {
            "n": len(dovish),
            "mean_vix_change": float(dovish["vix_change"].mean()),
            "fwd_rv5": float(dovish["fwd_rv5"].mean()),
            "fwd_rv21": float(dovish["fwd_rv21"].mean()),
        },
        "hawkish": {
            "n": len(hawkish),
            "mean_vix_change": float(hawkish["vix_change"].mean()),
            "fwd_rv5": float(hawkish["fwd_rv5"].mean()),
            "fwd_rv21": float(hawkish["fwd_rv21"].mean()),
        },
        "hawk_vs_dove_t5": float(t5),
        "hawk_vs_dove_p5": float(p5),
        "hawk_vs_dove_t21": float(t21),
        "hawk_vs_dove_p21": float(p21),
    }

    return results


def main():
    t0 = time.time()

    spy_close, vix_close = download_data()
    df, matched_fomc = build_dataset(spy_close, vix_close)

    print(f"\nDataset built: {len(df)} rows, {len(matched_fomc)} FOMC days matched")

    # Run all analyses
    desc_stats = descriptive_stats(df, matched_fomc)
    reg_results = regression_analysis(df)
    large_results = large_surprise_analysis(df)
    oos_results = oos_prediction_test(df)
    strat_results = strategy_backtest(df)
    subsample_results = subsample_robustness(df)
    direction_results = direction_analysis(df)

    elapsed = time.time() - t0

    # ── Summary ──
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Key findings
    findings = []

    # 1. VIX surprise predictive power
    for h in ["h5", "h10", "h21"]:
        if h in reg_results:
            t_val = reg_results[h]["vix_surprise_t_m2"]
            dr2 = reg_results[h]["delta_r2_m2"]
            sig = "***" if abs(t_val) > 3.0 else "**" if abs(t_val) > 2.0 else "*" if abs(t_val) > 1.65 else ""
            findings.append(f"  {h}: VIX surprise t={t_val:.3f}{sig}, ΔR²={dr2:.6f}")

    print("\n1. VIX Surprise → Forward Vol (regression):")
    for f in findings:
        print(f)

    # 2. OOS
    if "error" not in oos_results:
        print(f"\n2. OOS Test (21d horizon):")
        print(f"  Surprise {'BETTER' if oos_results['surprise_is_better_oos'] else 'WORSE'} OOS by {abs(oos_results['qlike_pct_diff']):.4f}%")
        print(f"  DM t-stat (surp-base): {oos_results['dm_t_surp_minus_base']:.3f}")
        print(f"  Significant: {oos_results['significant_at_005']}")

    # 3. Strategy
    print(f"\n3. Strategy overlay:")
    print(f"  Baseline 12/VIX Sharpe:  {strat_results['baseline_12vix']['sharpe']:.3f}")
    print(f"  + Surprise overlay:      {strat_results['surprise_overlay']['sharpe']:.3f}")
    print(f"  DM t vs baseline:        {strat_results['dm_t_vs_baseline']:.3f}")
    print(f"  Harvey threshold (t>3):   {strat_results['harvey_threshold_pass']}")

    # 4. Direction asymmetry
    print(f"\n4. Hawkish vs Dovish asymmetry:")
    print(f"  21d fwd vol t-stat: {direction_results['hawk_vs_dove_t21']:.3f}")

    # Determine overall conclusion
    h21_t = reg_results.get("h21", {}).get("vix_surprise_t_m2", 0)
    oos_better = oos_results.get("surprise_is_better_oos", False)
    oos_sig = oos_results.get("significant_at_005", False)
    strat_sig = strat_results.get("harvey_threshold_pass", False)

    # Strong IS signal (t=-8.18) but does OOS confirm?
    if abs(h21_t) > 3.0 and oos_better and oos_sig and strat_sig:
        conclusion = "STRONG: FOMC surprise predicts vol IS+OOS and improves strategy"
        stars = "★★★"
    elif abs(h21_t) > 3.0 and oos_better and oos_sig:
        conclusion = "STRONG IS + OOS: FOMC surprise predicts vol but no strategy improvement"
        stars = "★★"
    elif abs(h21_t) > 3.0 and not oos_better:
        conclusion = "IS-ONLY: Strong IS signal (t={:.1f}) but OOS WORSE — likely overfitting the forward-filled surprise proxy".format(h21_t)
        stars = "★"
    elif abs(h21_t) > 2.0:
        conclusion = "MODERATE: Some IS predictive power but no practical value"
        stars = "★"
    else:
        conclusion = "NULL: FOMC surprise does not predict forward volatility"
        stars = "—"

    print(f"\nOverall: {stars} {conclusion}")
    print(f"\nElapsed: {elapsed:.1f}s")

    # ── Save results ──
    all_results = {
        "experiment": "K514",
        "title": "FOMC Surprise Impact on Volatility",
        "attribution": "[提出: Codex event-surprise 建議, 執行: Claude]",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, ^VIX)",
        "data_range": desc_stats["date_range"],
        "n_total_days": desc_stats["n_total"],
        "n_fomc_meetings": desc_stats["n_fomc"],
        "method": "OLS regression + OOS expanding window + strategy backtest",
        "references": [
            "Bernanke & Kuttner (2005) JoF — fed funds futures surprise",
            "Lucca & Moench (2015) — pre-FOMC drift",
            "K96: FOMC causal vol effect, surprise R²=0.67",
            "K513: FOMC day vol +28%",
            "K414: Fed rate calendar dummy → null",
        ],
        "prior_knowledge": {
            "K96": "Surprise is key driver (R²=0.67), dovish→VIX↑, hawkish→VIX↓",
            "K513": "FOMC day vol +28% higher (significant)",
            "K414": "Calendar dummy null — need surprise component",
        },
        "descriptive_stats": desc_stats,
        "regression_results": reg_results,
        "large_surprise_analysis": large_results,
        "oos_prediction": oos_results,
        "strategy_backtest": strat_results,
        "subsample_robustness": subsample_results,
        "direction_asymmetry": direction_results,
        "conclusion": conclusion,
        "rating": stars,
        "elapsed_seconds": float(elapsed),
        "limitations": [
            "VIX change is only a proxy for surprise — does not isolate true unexpected component",
            "Forward-filled surprise assumes persistence until next FOMC — may oversmooth",
            "Strategy adjustment (0.1 × z × decay) is ad hoc — not optimized",
            "No fed funds futures data to compute Bernanke-Kuttner style surprise",
            "FOMC dates manually compiled — may have minor matching errors",
        ],
    }

    out_path = Path(__file__).parent / "k514_fomc_surprise_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
