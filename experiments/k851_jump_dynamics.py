#!/usr/bin/env python3
"""
K851: Jump Dynamics from TAIFEX Tick Data
==========================================

Purpose:
  Investigate whether jump metrics (frequency, intensity, signed jumps) from
  TAIFEX tick data improve next-day realized volatility prediction beyond
  the standard HAR-RV model. Tests the HAR-CJ model (Andersen, Bollerslev,
  Diebold 2007) which separately tracks Continuous and Jump components.

Research Questions:
  1. Does yesterday's jump component predict tomorrow's RV better than
     continuous component alone?
  2. Does HAR-CJ outperform standard HAR-RV?
  3. Is jump asymmetry (negative vs positive jumps) informative for Taiwan?

Prior Results:
  - K848: 74.9% of days have jumps, night vol 24%->57% (2017->2026)
  - K849: HAR-RV QLIKE=0.1808, HAR-RV-J QLIKE=0.1803 (DM t=0.83, not sig)
  - K849's jump was simple max(RV-BPV,0) without formal BNS test
  - K850: Better prediction != better VaR

Methodology (Andersen, Bollerslev, Diebold 2007):
  1. Data: TAIFEX TX1 tick data -> 5-min returns (day+night, 2017-2025)
  2. Jump detection via BNS (2006) bipower variation test:
     - RV_t = sum r^2_i
     - BV_t = (pi/2) * sum |r_i| * |r_{i-1}|
     - TQ_t = N * mu_{4/3}^{-3} * sum |r_i|^{4/3} * |r_{i-1}|^{4/3} * |r_{i-2}|^{4/3}
       where mu_{4/3} = 2^{2/3} * Gamma(7/6) / Gamma(1/2)
     - z_t = (RV - BV) / sqrt(vartheta * max(TQ/BV^2, 1/N)) / sqrt(N)
     - Significant jump at alpha=0.001 (Phi^{-1}(0.999)=3.09)
     - C_t = BV_t if jump detected, RV_t if not; J_t = (RV-BV)*I(z>crit)
  3. Models (all in log-form for normality):
     a) HAR-RV: log(RV_{t+1}) = b0 + b1 log(RV_t) + b5 log(RV_w) + b22 log(RV_m) + e
     b) HAR-CJ: log(RV_{t+1}) = b0 + bC1 log(C_t) + bC5 log(C_w) + bC22 log(C_m)
                                     + bJ1 sqrt(J_t) + bJ5 sqrt(J_w) + bJ22 sqrt(J_m) + e
     c) HAR-CJ-A: HAR-CJ + asymmetric jump (negative vs positive day return)
     d) HAR-CJ-Night: HAR-CJ + separate night jump component
  4. OOS: 70/30 split with rolling refit every 63 days
  5. Metrics: QLIKE on RV (Patton 2011), MSE, MAE, Spearman, R^2
  6. DM test with Newey-West HAC (Harvey t>3.0)

Error Log Rules:
  - DM test: Newey-West HAC
  - Sanity check: compute actual values, don't hard-code
  - Student-t: scale term sqrt((df-2)/df)
  - All signals use info up to t-1 only (no lookahead)

References:
  - Andersen, Bollerslev, Diebold (2007) "Roughing it up" RES
  - Barndorff-Nielsen & Shephard (2004, 2006) "Power/bipower variation"
  - Corsi (2009) "A simple approximate long-memory model of realized volatility"
  - Patton (2011) "Volatility forecast comparison using imperfect proxies"
  - Hansen & Lunde (2005) "A forecast comparison of volatility models"
  - Huang & Tauchen (2005) "The relative contribution of jumps to total price variance"

Author: VolPred Research System
Date: 2026-04-05
"""

import os
import sys
import glob
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats as sp_stats
from scipy.special import gamma as gamma_func

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Session boundaries (HHMMSS)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# BNS test significance level (conservative, as in ABD 2007)
JUMP_ALPHA = 0.001
JUMP_CRIT = sp_stats.norm.ppf(1 - JUMP_ALPHA)  # ~3.09

# HAR refit frequency
REFIT_FREQ = 63
MIN_TRAIN = 250

# OOS split
OOS_RATIO = 0.30


# ============================================================
# Step 1: Build 5-min RV from TAIFEX tick data (adapted from K849)
# ============================================================

def time_to_5min_bucket(time_int):
    """Convert HHMMSS integer to a 5-minute bucket label."""
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def compute_rv_bpv_tq(returns):
    """
    Compute RV, BPV, and Tripower Quarticity from 5-min log returns.

    RV = sum r^2
    BPV = (pi/2) * sum |r_i| * |r_{i-1}|
    TQ = N * mu_{4/3}^{-3} * sum |r_i|^{4/3} * |r_{i-1}|^{4/3} * |r_{i-2}|^{4/3}

    mu_p = 2^{p/2} * Gamma((p+1)/2) / Gamma(1/2) = E[|Z|^p] for Z ~ N(0,1)
    mu_{4/3} = 2^{2/3} * Gamma(7/6) / sqrt(pi)
    """
    n = len(returns)
    if n < 1:
        return np.nan, np.nan, np.nan

    rv = np.sum(returns ** 2)

    if n < 2:
        return float(rv), np.nan, np.nan

    abs_r = np.abs(returns)
    bpv = (np.pi / 2) * np.sum(abs_r[1:] * abs_r[:-1])

    if n < 3:
        return float(rv), float(bpv), np.nan

    # Tripower Quarticity (Barndorff-Nielsen & Shephard 2006)
    # mu_{4/3} = 2^{2/3} * Gamma(7/6) / Gamma(1/2)
    mu_43 = (2 ** (2.0 / 3.0)) * gamma_func(7.0 / 6.0) / gamma_func(0.5)
    tq_sum = np.sum(abs_r[2:] ** (4.0 / 3.0) *
                    abs_r[1:-1] ** (4.0 / 3.0) *
                    abs_r[:-2] ** (4.0 / 3.0))
    tq = n * (mu_43 ** (-3)) * tq_sum

    return float(rv), float(bpv), float(tq)


def process_single_file(filepath):
    """
    Process one TX1 file -> compute 5-min RV, BPV, TQ, and signed returns
    for day and night sessions separately.
    """
    basename = os.path.basename(filepath)
    try:
        parts = basename.replace("Daily_", "").replace("TX1.csv", "").replace("TX.csv", "").split("_")
        date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
    except Exception:
        return None

    if os.path.getsize(filepath) < 100:
        return None

    try:
        df = pd.read_csv(filepath, encoding='big5', dtype=str, low_memory=False)
    except Exception:
        try:
            df = pd.read_csv(filepath, encoding='cp950', dtype=str, low_memory=False)
        except Exception:
            return None

    if len(df) < 10:
        return None

    try:
        df['time_int'] = pd.to_numeric(df.iloc[:, 3], errors='coerce').astype('Int64')
        df['price'] = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        df['volume'] = pd.to_numeric(df.iloc[:, 5], errors='coerce').fillna(0)
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    # TX1 files are already near-month only
    t = df['time_int'].values
    p = df['price'].values

    # Session masks
    night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
    night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
    day_mask = (t >= DAY_START) & (t <= DAY_END)

    def build_5min_returns(session_t, session_p):
        """Build 5-min bar closes and compute log returns."""
        if len(session_t) < 5:
            return np.array([])
        buckets = np.array([time_to_5min_bucket(ti) for ti in session_t])
        unique_buckets = np.unique(buckets)
        bar_closes = []
        for b in unique_buckets:
            bucket_mask = buckets == b
            bar_closes.append(session_p[bucket_mask][-1])
        bar_closes = np.array(bar_closes, dtype=float)
        if len(bar_closes) >= 2:
            return np.diff(np.log(bar_closes))
        return np.array([])

    # Compute returns for each session
    day_rets = build_5min_returns(t[day_mask], p[day_mask])

    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])
    if len(night_pm_rets) > 0 or len(night_am_rets) > 0:
        night_rets = np.concatenate([night_pm_rets, night_am_rets])
    else:
        night_rets = np.array([])

    # Full session returns (day + night)
    all_rets_list = []
    if len(night_rets) > 0:
        all_rets_list.append(night_rets)
    if len(day_rets) > 0:
        all_rets_list.append(day_rets)
    if len(all_rets_list) > 0:
        full_rets = np.concatenate(all_rets_list)
    else:
        full_rets = np.array([])

    # Compute RV, BPV, TQ for each session
    rv_day, bpv_day, tq_day = compute_rv_bpv_tq(day_rets)
    rv_night, bpv_night, tq_night = compute_rv_bpv_tq(night_rets)
    rv_full, bpv_full, tq_full = compute_rv_bpv_tq(full_rets)

    # Day session return for sign detection
    day_p_sorted = p[day_mask]
    if len(day_p_sorted) >= 2:
        day_return = np.log(float(day_p_sorted[-1]) / float(day_p_sorted[0]))
    else:
        day_return = np.nan

    # Night session return for sign detection
    night_p = []
    if np.any(night_pm_mask):
        night_p.extend(p[night_pm_mask].tolist())
    if np.any(night_am_mask):
        night_p.extend(p[night_am_mask].tolist())
    if len(night_p) >= 2:
        night_return = np.log(float(night_p[-1]) / float(night_p[0]))
    else:
        night_return = np.nan

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'rv_full': rv_full if not np.isnan(rv_full) else None,
        'bpv_day': bpv_day if not np.isnan(bpv_day) else None,
        'bpv_night': bpv_night if not np.isnan(bpv_night) else None,
        'bpv_full': bpv_full if not np.isnan(bpv_full) else None,
        'tq_day': tq_day if not np.isnan(tq_day) else None,
        'tq_night': tq_night if not np.isnan(tq_night) else None,
        'tq_full': tq_full if not np.isnan(tq_full) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
        'night_return': night_return if not np.isnan(night_return) else None,
        'n_day_rets': len(day_rets),
        'n_night_rets': len(night_rets),
        'n_full_rets': len(full_rets),
    }


def load_all_rv_data(start_date='2017_05_16'):
    """Load TX1 files from night session era and compute RV/BPV/TQ."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff = f"Daily_{start_date}"
    files = [f for f in all_files if os.path.basename(f) >= cutoff]
    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {start_date} to end 2025")

    results = []
    errors = 0
    n_workers = min(8, os.cpu_count() or 4)
    print(f"  Using {n_workers} workers...")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_file, f): f for f in files}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 500 == 0:
                print(f"    Processed {done_count}/{len(files)} files...")
            try:
                result = future.result()
                if result is not None and result.get('rv_full') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)}, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()

    # Convert to float
    for col in ['rv_day', 'rv_night', 'rv_full', 'bpv_day', 'bpv_night', 'bpv_full',
                'tq_day', 'tq_night', 'tq_full', 'day_return', 'night_return']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


# ============================================================
# Step 2: BNS Jump Detection Test
# ============================================================

def bns_jump_test(rv, bpv, tq, n_returns):
    """
    Barndorff-Nielsen & Shephard (2006) jump test.

    z = sqrt(N) * (RV - BV) / sqrt(vartheta * max(TQ/BV^2, 1/N) * BV^2)

    where vartheta = (pi/2)^2 + pi - 5 ~ 0.6091

    Returns: z_stat, is_significant (at JUMP_ALPHA level)
    """
    if np.isnan(rv) or np.isnan(bpv) or np.isnan(tq) or bpv <= 0 or n_returns < 3:
        return np.nan, False

    # vartheta from ABD (2007) eq. 14
    vartheta = (np.pi / 2) ** 2 + np.pi - 5  # ~ 0.6091

    # Ratio test: (RV - BV) relative to sampling noise
    ratio = tq / (bpv ** 2)
    # Floor ratio at small value to avoid numerical issues
    ratio = max(ratio, 1.0 / n_returns)

    # z = sqrt(N) * (RV - BV) / (sqrt(vartheta * ratio) * BV)
    denominator = np.sqrt(vartheta * ratio / n_returns) * bpv
    if denominator <= 0:
        return np.nan, False

    z = (rv - bpv) / denominator
    is_sig = z > JUMP_CRIT

    return float(z), bool(is_sig)


def compute_jump_components(df):
    """
    For each day, run BNS test and decompose RV = C + J.

    C_t = BV_t (continuous component) if jump detected
    C_t = RV_t if no jump detected (all variance is continuous)
    J_t = (RV_t - BV_t) * I(z_t > critical) (jump only if significant)

    Also compute signed jumps:
      J_pos_t = J_t if day_return > 0 else 0
      J_neg_t = J_t if day_return <= 0 else 0
    """
    n = len(df)
    results = {
        'z_stat': np.full(n, np.nan),
        'jump_sig': np.zeros(n, dtype=bool),
        'C_full': np.full(n, np.nan),
        'J_full': np.full(n, np.nan),
        'J_pos': np.full(n, np.nan),
        'J_neg': np.full(n, np.nan),
        'C_day': np.full(n, np.nan),
        'J_day': np.full(n, np.nan),
        'C_night': np.full(n, np.nan),
        'J_night': np.full(n, np.nan),
    }

    for i in range(n):
        row = df.iloc[i]
        rv = row['rv_full']
        bpv = row['bpv_full']
        tq = row['tq_full']
        n_rets = row['n_full_rets']

        if np.isnan(rv) or np.isnan(bpv):
            continue

        z, is_sig = bns_jump_test(rv, bpv, tq, n_rets)
        results['z_stat'][i] = z

        if is_sig:
            results['jump_sig'][i] = True
            results['J_full'][i] = max(rv - bpv, 0)
            results['C_full'][i] = bpv
        else:
            results['J_full'][i] = 0.0
            results['C_full'][i] = rv  # No significant jump -> all continuous

        # Signed jumps (based on day return sign)
        day_ret = row.get('day_return', np.nan)
        j_val = results['J_full'][i]
        if not np.isnan(j_val):
            if not np.isnan(day_ret) and day_ret > 0:
                results['J_pos'][i] = j_val
                results['J_neg'][i] = 0.0
            elif not np.isnan(day_ret):
                results['J_pos'][i] = 0.0
                results['J_neg'][i] = j_val
            else:
                # Unknown sign -> split evenly (conservative)
                results['J_pos'][i] = j_val / 2
                results['J_neg'][i] = j_val / 2

        # Day-only decomposition
        rv_d = row['rv_day']
        bpv_d = row['bpv_day']
        tq_d = row['tq_day']
        n_d = row['n_day_rets']
        if not np.isnan(rv_d) and not np.isnan(bpv_d):
            z_d, sig_d = bns_jump_test(rv_d, bpv_d, tq_d, n_d)
            if sig_d:
                results['J_day'][i] = max(rv_d - bpv_d, 0)
                results['C_day'][i] = bpv_d
            else:
                results['J_day'][i] = 0.0
                results['C_day'][i] = rv_d

        # Night decomposition
        rv_n = row['rv_night']
        bpv_n = row['bpv_night']
        tq_n = row['tq_night']
        n_n = row['n_night_rets']
        if not np.isnan(rv_n) and not np.isnan(bpv_n):
            z_n, sig_n = bns_jump_test(rv_n, bpv_n, tq_n, n_n)
            if sig_n:
                results['J_night'][i] = max(rv_n - bpv_n, 0)
                results['C_night'][i] = bpv_n
            else:
                results['J_night'][i] = 0.0
                results['C_night'][i] = rv_n

    # Add to dataframe
    for key, vals in results.items():
        df[key] = vals

    return df


# ============================================================
# Step 3: HAR Model Family (all log-transformed)
# ============================================================

def fit_har_ols(y, X):
    """OLS fit: y = [1, X] @ beta. Returns beta, y_hat, R^2."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        y_hat = X_c @ beta
        resid = y - y_hat
        ss_res = np.sum(resid ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        return beta, y_hat, r2
    except Exception:
        return None, None, None


def _get_features_at(model_name, t, log_rv, log_C, sqrt_J,
                     sqrt_J_pos, sqrt_J_neg, sqrt_J_night):
    """
    Get feature vector at time t using info up to t-1.
    Features are lagged: daily=t-1, weekly=mean(t-5:t), monthly=mean(t-22:t).
    """
    if t < 22:
        return None

    # HAR daily/weekly/monthly for log_rv
    lr_d = log_rv[t - 1]
    lr_w = np.mean(log_rv[max(0, t - 5):t])
    lr_m = np.mean(log_rv[max(0, t - 22):t])

    if model_name == 'HAR-RV':
        feat = [lr_d, lr_w, lr_m]
        if any(np.isnan(feat)):
            return None
        return np.array(feat)

    # For CJ models, use continuous and jump components
    lc_d = log_C[t - 1]
    lc_w = np.mean(log_C[max(0, t - 5):t])
    lc_m = np.mean(log_C[max(0, t - 22):t])

    sj_d = sqrt_J[t - 1]
    sj_w = np.mean(sqrt_J[max(0, t - 5):t])
    sj_m = np.mean(sqrt_J[max(0, t - 22):t])

    if model_name == 'HAR-CJ':
        feat = [lc_d, lc_w, lc_m, sj_d, sj_w, sj_m]
        if any(np.isnan(feat)):
            return None
        return np.array(feat)

    if model_name == 'HAR-CJ-A':
        # Add asymmetric jump: separate negative jump
        sjn_d = sqrt_J_neg[t - 1]
        sjn_w = np.mean(sqrt_J_neg[max(0, t - 5):t])
        feat = [lc_d, lc_w, lc_m, sj_d, sj_w, sj_m, sjn_d, sjn_w]
        if any(np.isnan(feat)):
            return None
        return np.array(feat)

    if model_name == 'HAR-CJ-Night':
        # Add night jump component
        sjnight_d = sqrt_J_night[t - 1]
        sjnight_w = np.mean(sqrt_J_night[max(0, t - 5):t])
        feat = [lc_d, lc_w, lc_m, sj_d, sj_w, sj_m, sjnight_d, sjnight_w]
        if any(np.isnan(feat)):
            return None
        return np.array(feat)

    return None


def har_oos_forecast(df, model_name, oos_start_idx, refit_freq=REFIT_FREQ,
                     min_train=MIN_TRAIN):
    """
    Rolling OOS forecast for HAR model variants.

    Models:
      HAR-RV: log(RV) ~ log(RV_d), log(RV_w), log(RV_m)
      HAR-CJ: log(RV) ~ log(C_d), log(C_w), log(C_m), sqrt(J_d), sqrt(J_w), sqrt(J_m)
      HAR-CJ-A: HAR-CJ + sqrt(J_neg_d), sqrt(J_neg_w)
      HAR-CJ-Night: HAR-CJ + sqrt(J_night_d), sqrt(J_night_w)

    Returns: forecasts as pandas Series (in level space, already exp'd back)
    """
    rv_full = df['rv_full'].values.astype(float)
    log_rv = np.log(np.maximum(rv_full, 1e-12))
    n = len(df)

    # Pre-compute component series
    C = df['C_full'].values.astype(float)
    J = df['J_full'].values.astype(float)
    J_pos = df['J_pos'].values.astype(float)
    J_neg = df['J_neg'].values.astype(float)
    J_night = df['J_night'].values.astype(float)

    log_C = np.log(np.maximum(C, 1e-12))
    sqrt_J = np.sqrt(np.maximum(J, 0))
    sqrt_J_pos = np.sqrt(np.maximum(J_pos, 0))
    sqrt_J_neg = np.sqrt(np.maximum(J_neg, 0))
    sqrt_J_night = np.sqrt(np.maximum(J_night, 0))

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq

    for t in range(oos_start_idx, n):
        # Refit periodically
        if t - last_fit_idx >= refit_freq or last_beta is None:
            if t < min_train:
                continue

            # Build training features (using info up to t-1 for each obs)
            y_train = []
            X_train = []

            for i in range(22, t):
                # Target: log(RV_{i})
                if np.isnan(log_rv[i]):
                    continue

                feat = _get_features_at(
                    model_name, i, log_rv, log_C, sqrt_J,
                    sqrt_J_pos, sqrt_J_neg, sqrt_J_night
                )
                if feat is None:
                    continue

                y_train.append(log_rv[i])
                X_train.append(feat)

            if len(y_train) < 50:
                continue

            y_arr = np.array(y_train)
            X_arr = np.array(X_train)

            beta, _, _ = fit_har_ols(y_arr, X_arr)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        # Build features for forecasting at time t (using info up to t-1)
        feat_t = _get_features_at(
            model_name, t, log_rv, log_C, sqrt_J,
            sqrt_J_pos, sqrt_J_neg, sqrt_J_night
        )
        if feat_t is None:
            continue

        x_t = np.concatenate([[1.0], feat_t])
        if len(x_t) != len(last_beta):
            continue

        log_rv_hat = x_t @ last_beta
        # Convert back from log space: RV_hat = exp(log_rv_hat)
        forecasts[t] = np.exp(log_rv_hat)

    return pd.Series(forecasts, index=df.index, name=model_name)


# ============================================================
# Step 4: Metrics and Statistical Tests
# ============================================================

def qlike(target, forecast):
    """QLIKE = mean(target/forecast - log(target/forecast) - 1)"""
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f) & (t > 0) & (f > 0)
    t, f = t[valid], f[valid]
    if len(t) < 10:
        return np.nan
    ratio = t / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def mse_metric(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    return float(np.mean((t[valid] - f[valid]) ** 2)) if np.sum(valid) > 10 else np.nan


def mae_metric(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    return float(np.mean(np.abs(t[valid] - f[valid]))) if np.sum(valid) > 10 else np.nan


def spearman_corr(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    if np.sum(valid) < 10:
        return np.nan, np.nan
    rho, pval = sp_stats.spearmanr(t[valid], f[valid])
    return float(rho), float(pval)


def qlike_loss_series(target, forecast):
    """Per-observation QLIKE loss for DM test."""
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    ratio = t / f
    loss = ratio - np.log(ratio) - 1
    loss[~np.isfinite(loss)] = np.nan
    loss[(t <= 0) | (f <= 0)] = np.nan
    return loss


def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t -> model 1 better."""
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0

    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l

    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
# Step 5: In-sample diagnostics with Newey-West standard errors
# ============================================================

def insample_diagnostics(df, model_name, end_idx=None):
    """
    Fit model on in-sample data, report coefficients + NW t-stats + R^2.
    """
    if end_idx is None:
        end_idx = len(df)

    rv_full = df['rv_full'].values[:end_idx].astype(float)
    log_rv = np.log(np.maximum(rv_full, 1e-12))

    C = df['C_full'].values[:end_idx].astype(float)
    J = df['J_full'].values[:end_idx].astype(float)
    J_pos = df['J_pos'].values[:end_idx].astype(float)
    J_neg = df['J_neg'].values[:end_idx].astype(float)
    J_night = df['J_night'].values[:end_idx].astype(float)

    log_C = np.log(np.maximum(C, 1e-12))
    sqrt_J = np.sqrt(np.maximum(J, 0))
    sqrt_J_pos = np.sqrt(np.maximum(J_pos, 0))
    sqrt_J_neg = np.sqrt(np.maximum(J_neg, 0))
    sqrt_J_night = np.sqrt(np.maximum(J_night, 0))

    y_list = []
    X_list = []
    for i in range(22, end_idx):
        if np.isnan(log_rv[i]):
            continue
        feat = _get_features_at(
            model_name, i, log_rv, log_C, sqrt_J,
            sqrt_J_pos, sqrt_J_neg, sqrt_J_night
        )
        if feat is None:
            continue
        y_list.append(log_rv[i])
        X_list.append(feat)

    if len(y_list) < 50:
        return None

    y = np.array(y_list)
    X = np.array(X_list)
    n_obs = len(y)

    beta, y_hat, r2 = fit_har_ols(y, X)
    if beta is None:
        return None

    # Newey-West standard errors
    X_c = np.column_stack([np.ones(n_obs), X])
    resid = y - y_hat
    k = X_c.shape[1]
    max_lag = int(np.ceil(n_obs ** (1 / 3)))

    # HAC covariance
    S = np.zeros((k, k))
    for lag in range(max_lag + 1):
        weight = 1.0 if lag == 0 else (1 - lag / (max_lag + 1))
        if lag == 0:
            Gamma = (X_c * resid[:, None]).T @ (X_c * resid[:, None]) / n_obs
        else:
            Gamma = (X_c[lag:] * resid[lag:, None]).T @ (X_c[:-lag] * resid[:-lag, None]) / n_obs
        S += weight * (Gamma + Gamma.T) if lag > 0 else Gamma

    try:
        XtX_inv = np.linalg.inv(X_c.T @ X_c / n_obs)
        V = XtX_inv @ S @ XtX_inv / n_obs
        se = np.sqrt(np.diag(V))
    except Exception:
        se = np.full(k, np.nan)

    t_stats = beta / se

    # Feature names
    if model_name == 'HAR-RV':
        names = ['const', 'log_rv_d', 'log_rv_w', 'log_rv_m']
    elif model_name == 'HAR-CJ':
        names = ['const', 'log_C_d', 'log_C_w', 'log_C_m', 'sqrt_J_d', 'sqrt_J_w', 'sqrt_J_m']
    elif model_name == 'HAR-CJ-A':
        names = ['const', 'log_C_d', 'log_C_w', 'log_C_m', 'sqrt_J_d', 'sqrt_J_w', 'sqrt_J_m',
                 'sqrt_Jneg_d', 'sqrt_Jneg_w']
    elif model_name == 'HAR-CJ-Night':
        names = ['const', 'log_C_d', 'log_C_w', 'log_C_m', 'sqrt_J_d', 'sqrt_J_w', 'sqrt_J_m',
                 'sqrt_Jnight_d', 'sqrt_Jnight_w']
    else:
        names = [f'x{i}' for i in range(k)]

    coefs = {}
    for i, name in enumerate(names):
        coefs[name] = {
            'estimate': round(float(beta[i]), 6),
            'se': round(float(se[i]), 6) if not np.isnan(se[i]) else None,
            't_stat': round(float(t_stats[i]), 4) if not np.isnan(t_stats[i]) else None,
        }

    return {
        'model': model_name,
        'n': n_obs,
        'R2': round(float(r2), 6),
        'coefficients': coefs,
    }


# ============================================================
# Step 6: Cross-OOS Stability (5-fold)
# ============================================================

def cross_oos_evaluation(df, model_name, n_folds=5):
    """
    Split OOS period into n_folds sub-periods and evaluate each.
    Returns per-fold QLIKE and Spearman for stability assessment.
    """
    n = len(df)
    oos_start = int(n * (1 - OOS_RATIO))

    # Run full OOS forecast
    forecasts = har_oos_forecast(df, model_name, oos_start)

    rv = df['rv_full'].values
    fc = forecasts.values

    # Only OOS period
    oos_rv = rv[oos_start:]
    oos_fc = fc[oos_start:]
    valid = np.isfinite(oos_rv) & np.isfinite(oos_fc) & (oos_rv > 0) & (oos_fc > 0)

    if np.sum(valid) < 50:
        return None, forecasts

    # Split into folds
    valid_indices = np.where(valid)[0]
    fold_size = len(valid_indices) // n_folds
    fold_results = []

    for fold in range(n_folds):
        start = fold * fold_size
        end = (fold + 1) * fold_size if fold < n_folds - 1 else len(valid_indices)
        idx = valid_indices[start:end]

        fold_rv = oos_rv[idx]
        fold_fc = oos_fc[idx]

        q = qlike(fold_rv, fold_fc)
        rho, _ = spearman_corr(fold_rv, fold_fc)
        fold_results.append({
            'fold': fold + 1,
            'n': len(idx),
            'QLIKE': round(q, 6) if not np.isnan(q) else None,
            'Spearman': round(rho, 4) if not np.isnan(rho) else None,
        })

    return fold_results, forecasts


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("K851: Jump Dynamics from TAIFEX Tick Data")
    print("=" * 70)
    start_time = datetime.now()

    # ------------------------------------------------------------------
    # Part 1: Load data
    # ------------------------------------------------------------------
    print("\n[1] Loading TAIFEX TX1 tick data and computing RV/BPV/TQ...")
    df = load_all_rv_data(start_date='2017_05_16')
    print(f"  Total trading days: {len(df)}")
    print(f"  Date range: {df.index.min().date()} to {df.index.max().date()}")

    # Require both day and night data
    df = df.dropna(subset=['rv_full', 'bpv_full'])
    print(f"  After filtering for complete data: {len(df)} days")

    # ------------------------------------------------------------------
    # Part 2: BNS Jump Test and Decomposition
    # ------------------------------------------------------------------
    print("\n[2] Running BNS jump detection test (alpha=0.001)...")
    df = compute_jump_components(df)

    n_jump_days = int(df['jump_sig'].sum())
    n_total = len(df)
    jump_pct = 100.0 * n_jump_days / n_total

    print(f"  Jump days (BNS significant): {n_jump_days}/{n_total} ({jump_pct:.1f}%)")
    print(f"  z-stat: mean={df['z_stat'].mean():.3f}, median={df['z_stat'].dropna().median():.3f}")

    # Jump descriptive statistics
    j_full = df['J_full'].values
    c_full = df['C_full'].values
    rv_full = df['rv_full'].values

    valid_j = j_full[np.isfinite(j_full)]
    valid_c = c_full[np.isfinite(c_full)]

    # Jump contribution to total variance
    j_mean = float(np.mean(valid_j))
    c_mean = float(np.mean(valid_c))
    rv_mean = float(np.mean(rv_full[np.isfinite(rv_full)]))
    jump_contrib_pct = 100.0 * j_mean / rv_mean if rv_mean > 0 else 0.0

    print(f"\n  Jump contribution to total RV: {jump_contrib_pct:.1f}%")
    print(f"  Mean C (continuous): {c_mean:.2e} (ann vol: {np.sqrt(c_mean * 252) * 100:.1f}%)")
    print(f"  Mean J (jump): {j_mean:.2e} (ann vol: {np.sqrt(j_mean * 252) * 100:.1f}%)")
    print(f"  Mean RV (total): {rv_mean:.2e} (ann vol: {np.sqrt(rv_mean * 252) * 100:.1f}%)")

    # Signed jumps
    j_pos = df['J_pos'].values
    j_neg = df['J_neg'].values
    valid_jp = j_pos[np.isfinite(j_pos)]
    valid_jn = j_neg[np.isfinite(j_neg)]

    print(f"\n  Positive jump days (of jump days): {int(np.sum(valid_jp > 0))}")
    print(f"  Negative jump days (of jump days): {int(np.sum(valid_jn > 0))}")
    print(f"  Mean J+: {np.mean(valid_jp):.2e}")
    print(f"  Mean J-: {np.mean(valid_jn):.2e}")

    # Night jumps
    j_night = df['J_night'].values
    valid_jnight = j_night[np.isfinite(j_night)]
    j_day_vals = df['J_day'].values
    valid_jday = j_day_vals[np.isfinite(j_day_vals)]
    print(f"\n  Mean J_day: {np.mean(valid_jday):.2e}")
    print(f"  Mean J_night: {np.mean(valid_jnight):.2e}")
    mean_jday = float(np.mean(valid_jday))
    mean_jnight = float(np.mean(valid_jnight))
    night_jump_ratio = mean_jnight / (mean_jday + mean_jnight) * 100 if (mean_jday + mean_jnight) > 0 else 0.0
    print(f"  Night jump share: {night_jump_ratio:.1f}%")

    # ------------------------------------------------------------------
    # Part 3: OOS Split
    # ------------------------------------------------------------------
    n = len(df)
    oos_start_idx = int(n * (1 - OOS_RATIO))
    oos_start_date = df.index[oos_start_idx]
    print(f"\n[3] OOS split:")
    print(f"  IS: {df.index[0].date()} to {df.index[oos_start_idx - 1].date()} ({oos_start_idx} days)")
    print(f"  OOS: {oos_start_date.date()} to {df.index[-1].date()} ({n - oos_start_idx} days)")

    # ------------------------------------------------------------------
    # Part 4: In-sample diagnostics
    # ------------------------------------------------------------------
    print("\n[4] In-sample diagnostics...")
    models = ['HAR-RV', 'HAR-CJ', 'HAR-CJ-A', 'HAR-CJ-Night']
    is_results = {}

    for model_name in models:
        diag = insample_diagnostics(df, model_name, end_idx=oos_start_idx)
        if diag is not None:
            is_results[model_name] = diag
            print(f"\n  {model_name}: R2={diag['R2']:.4f}, n={diag['n']}")
            for coef_name, coef_data in diag['coefficients'].items():
                t_val = coef_data['t_stat']
                sig = "***" if t_val is not None and abs(t_val) > 3.0 else \
                      "**" if t_val is not None and abs(t_val) > 2.0 else \
                      "*" if t_val is not None and abs(t_val) > 1.65 else ""
                if t_val is not None:
                    print(f"    {coef_name:15s}: {coef_data['estimate']:12.6f}  "
                          f"(t={t_val:7.3f}) {sig}")
                else:
                    print(f"    {coef_name:15s}: {coef_data['estimate']:12.6f}  (t=   N/A)")
        else:
            print(f"\n  {model_name}: FAILED")

    # ------------------------------------------------------------------
    # Part 5: OOS forecasts and evaluation
    # ------------------------------------------------------------------
    print("\n[5] Running OOS forecasts...")
    oos_forecasts = {}
    oos_metrics = {}

    rv = df['rv_full'].values

    for model_name in models:
        print(f"  Forecasting {model_name}...")
        fc = har_oos_forecast(df, model_name, oos_start_idx)
        oos_forecasts[model_name] = fc

        # Evaluate
        oos_rv = rv[oos_start_idx:]
        oos_fc = fc.values[oos_start_idx:]
        valid = np.isfinite(oos_rv) & np.isfinite(oos_fc) & (oos_rv > 0) & (oos_fc > 0)

        q = qlike(oos_rv[valid], oos_fc[valid])
        m = mse_metric(oos_rv[valid], oos_fc[valid])
        a = mae_metric(oos_rv[valid], oos_fc[valid])
        rho, rho_p = spearman_corr(oos_rv[valid], oos_fc[valid])

        oos_metrics[model_name] = {
            'QLIKE': round(q, 6) if not np.isnan(q) else None,
            'MSE': f"{m:.4e}" if not np.isnan(m) else None,
            'MAE': f"{a:.4e}" if not np.isnan(a) else None,
            'Spearman': round(rho, 4) if not np.isnan(rho) else None,
            'Spearman_p': round(rho_p, 6) if not np.isnan(rho_p) else None,
            'n_oos': int(np.sum(valid)),
        }
        print(f"    QLIKE={q:.6f}, Spearman={rho:.4f}, n={int(np.sum(valid))}")

    # ------------------------------------------------------------------
    # Part 6: DM Tests (all pairs)
    # ------------------------------------------------------------------
    print("\n[6] DM tests (Newey-West HAC)...")
    dm_results = {}

    for i_m, m1 in enumerate(models):
        for m2 in models[i_m + 1:]:
            oos_rv = rv[oos_start_idx:]
            fc1 = oos_forecasts[m1].values[oos_start_idx:]
            fc2 = oos_forecasts[m2].values[oos_start_idx:]

            loss1 = qlike_loss_series(oos_rv, fc1)
            loss2 = qlike_loss_series(oos_rv, fc2)

            t_stat, p_val = dm_test(loss1, loss2)
            winner = m1 if t_stat < 0 else m2
            sig = abs(t_stat) > 3.0

            key = f"{m1} vs {m2}"
            dm_results[key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'winner': winner,
                'significant_harvey': sig,
            }
            star = " ***" if sig else ""
            print(f"  {key}: t={t_stat:.4f}, p={p_val:.4f}, winner={winner}{star}")

    # ------------------------------------------------------------------
    # Part 7: Cross-OOS Stability
    # ------------------------------------------------------------------
    print("\n[7] Cross-OOS stability (5-fold)...")
    cross_oos_results = {}

    for model_name in models:
        fold_results, _ = cross_oos_evaluation(df, model_name)
        if fold_results is not None:
            cross_oos_results[model_name] = fold_results
            qlikes = [f['QLIKE'] for f in fold_results if f['QLIKE'] is not None]
            if qlikes:
                print(f"  {model_name}: QLIKE range [{min(qlikes):.4f}, {max(qlikes):.4f}], "
                      f"std={np.std(qlikes):.4f}")

    # ------------------------------------------------------------------
    # Part 8: Jump Persistence Analysis
    # ------------------------------------------------------------------
    print("\n[8] Jump persistence analysis...")
    # Autocorrelation of jump indicator
    jump_sig = df['jump_sig'].astype(int).values
    j_vals = df['J_full'].values

    # Jump clustering: P(jump at t | jump at t-1)
    n_total_j = len(jump_sig)
    jump_after_jump = 0
    no_jump_after_jump = 0
    jump_after_no_jump = 0
    no_jump_after_no_jump = 0

    for i in range(1, n_total_j):
        if jump_sig[i - 1] == 1:
            if jump_sig[i] == 1:
                jump_after_jump += 1
            else:
                no_jump_after_jump += 1
        else:
            if jump_sig[i] == 1:
                jump_after_no_jump += 1
            else:
                no_jump_after_no_jump += 1

    total_after_jump = jump_after_jump + no_jump_after_jump
    total_after_no = jump_after_no_jump + no_jump_after_no_jump

    p_jump_given_jump = jump_after_jump / total_after_jump if total_after_jump > 0 else 0.0
    p_jump_given_no = jump_after_no_jump / total_after_no if total_after_no > 0 else 0.0

    print(f"  P(jump|jump_prev): {p_jump_given_jump:.3f}")
    print(f"  P(jump|no_jump_prev): {p_jump_given_no:.3f}")
    if p_jump_given_no > 0:
        clustering_ratio = p_jump_given_jump / p_jump_given_no
        print(f"  Jump clustering ratio: {clustering_ratio:.2f}x")
    else:
        clustering_ratio = None
        print("  Jump clustering ratio: N/A")

    # Autocorrelation of jump magnitude
    j_valid = j_vals[np.isfinite(j_vals)]
    if len(j_valid) > 10:
        j_ac1 = float(np.corrcoef(j_valid[1:], j_valid[:-1])[0, 1])
        print(f"  Jump magnitude AC(1): {j_ac1:.4f}")
    else:
        j_ac1 = np.nan

    # Jump size distribution on jump days
    j_on_jump_days = j_vals[df['jump_sig'].values & np.isfinite(j_vals)]
    if len(j_on_jump_days) > 0:
        j_mean_jump = float(np.mean(j_on_jump_days))
        j_median_jump = float(np.median(j_on_jump_days))
        j_std_jump = float(np.std(j_on_jump_days))
        j_skew = float(sp_stats.skew(j_on_jump_days))
        j_kurt = float(sp_stats.kurtosis(j_on_jump_days))
        print(f"\n  Jump size (on jump days):")
        print(f"    Mean: {j_mean_jump:.2e}, Median: {j_median_jump:.2e}")
        print(f"    Std: {j_std_jump:.2e}")
        print(f"    Skew: {j_skew:.3f}, Kurtosis: {j_kurt:.3f}")
    else:
        j_mean_jump = j_median_jump = j_std_jump = j_skew = j_kurt = np.nan

    # ------------------------------------------------------------------
    # Part 9: Yearly jump frequency analysis
    # ------------------------------------------------------------------
    print("\n[9] Yearly jump frequency...")
    df_copy = df.copy()
    df_copy['year'] = df_copy.index.year
    yearly_stats = []
    for year, grp in df_copy.groupby('year'):
        n_days = len(grp)
        n_jumps = int(grp['jump_sig'].sum())
        pct = 100.0 * n_jumps / n_days if n_days > 0 else 0.0
        mean_j = float(grp['J_full'].mean())
        mean_rv = float(grp['rv_full'].mean())
        j_share = 100.0 * mean_j / mean_rv if mean_rv > 0 else 0.0
        yearly_stats.append({
            'year': int(year),
            'n_days': int(n_days),
            'n_jumps': n_jumps,
            'jump_pct': round(pct, 1),
            'j_share_pct': round(j_share, 1),
            'ann_vol_pct': round(float(np.sqrt(mean_rv * 252) * 100), 1),
        })
        print(f"  {year}: {n_jumps}/{n_days} ({pct:.1f}%), J share={j_share:.1f}%, "
              f"ann vol={np.sqrt(mean_rv * 252) * 100:.1f}%")

    # ------------------------------------------------------------------
    # Part 10: Compile Results
    # ------------------------------------------------------------------
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n[10] Compiling results... (elapsed: {elapsed:.0f}s)")

    # Determine best model
    valid_metrics = {m: v for m, v in oos_metrics.items() if v.get('QLIKE') is not None}
    best_model = min(valid_metrics, key=lambda m: valid_metrics[m]['QLIKE'])
    har_rv_qlike = oos_metrics.get('HAR-RV', {}).get('QLIKE')

    # Improvement over HAR-RV
    improvements = {}
    for m in models:
        q = oos_metrics[m].get('QLIKE')
        if q is not None and har_rv_qlike is not None and har_rv_qlike > 0:
            imp = 100.0 * (har_rv_qlike - q) / har_rv_qlike
            improvements[m] = round(imp, 2)

    jump_stats = {
        'n_jump_days': n_jump_days,
        'n_total_days': n_total,
        'jump_pct': round(jump_pct, 1),
        'z_stat_mean': round(float(df['z_stat'].mean()), 3),
        'z_stat_median': round(float(df['z_stat'].dropna().median()), 3),
        'jump_contribution_pct': round(jump_contrib_pct, 1),
        'mean_C': c_mean,
        'mean_J': j_mean,
        'mean_RV': rv_mean,
        'ann_vol_C_pct': round(float(np.sqrt(c_mean * 252) * 100), 1),
        'ann_vol_J_pct': round(float(np.sqrt(j_mean * 252) * 100), 1),
        'ann_vol_RV_pct': round(float(np.sqrt(rv_mean * 252) * 100), 1),
        'mean_J_pos': float(np.mean(valid_jp)),
        'mean_J_neg': float(np.mean(valid_jn)),
        'night_jump_share_pct': round(night_jump_ratio, 1),
        'P_jump_given_jump': round(p_jump_given_jump, 3),
        'P_jump_given_no_jump': round(p_jump_given_no, 3),
        'jump_clustering_ratio': round(clustering_ratio, 2) if clustering_ratio is not None else None,
        'jump_magnitude_AC1': round(j_ac1, 4) if not np.isnan(j_ac1) else None,
        'jump_size_on_jump_days': {
            'mean': f"{j_mean_jump:.2e}" if not np.isnan(j_mean_jump) else None,
            'median': f"{j_median_jump:.2e}" if not np.isnan(j_median_jump) else None,
            'std': f"{j_std_jump:.2e}" if not np.isnan(j_std_jump) else None,
            'skew': round(j_skew, 3) if not np.isnan(j_skew) else None,
            'kurtosis': round(j_kurt, 3) if not np.isnan(j_kurt) else None,
        },
    }

    results = {
        'experiment_id': 'K851',
        'title': 'Jump Dynamics from TAIFEX Tick Data -- HAR-CJ Model Comparison',
        'date': '2026-04-05',
        'data_source': 'TAIFEX TX1 tick data (Big5 CSV)',
        'data_period': f'{df.index.min().date()} to {df.index.max().date()}',
        'n_trading_days': n,
        'methodology': {
            'jump_test': 'Barndorff-Nielsen & Shephard (2006) bipower variation, alpha=0.001',
            'models': {
                'HAR-RV': 'Corsi (2009): log(RV_t) ~ log(RV_d, RV_w, RV_m)',
                'HAR-CJ': 'ABD (2007): log(RV_t) ~ log(C_d, C_w, C_m) + sqrt(J_d, J_w, J_m)',
                'HAR-CJ-A': 'HAR-CJ + asymmetric negative jump component',
                'HAR-CJ-Night': 'HAR-CJ + separate night session jump component',
            },
            'target': '5-min Realized Volatility (full session, day+night)',
            'metrics': 'QLIKE (Patton 2011), MSE, MAE, Spearman rank correlation',
            'dm_test': 'Newey-West HAC, Harvey (2016) threshold |t|>3.0',
            'refit_freq': '63 trading days',
            'oos_split': f'{int((1-OOS_RATIO)*100)}/{int(OOS_RATIO*100)} (IS/OOS)',
            'log_transform': 'All models estimated in log space for normality',
        },
        'references': [
            'Andersen, Bollerslev, Diebold (2007) "Roughing it up" - Review of Economics and Statistics',
            'Barndorff-Nielsen & Shephard (2004, 2006) "Power and bipower variation" - J. Financial Econometrics',
            'Corsi (2009) "A simple approximate long-memory model of realized volatility" - J. Financial Econometrics',
            'Patton (2011) "Volatility forecast comparison using imperfect volatility proxies" - J. Econometrics',
            'Hansen & Lunde (2005) "A forecast comparison of volatility models" - J. Applied Econometrics',
            'Huang & Tauchen (2005) "The relative contribution of jumps to total price variance" - J. Financial Econometrics',
        ],
        'jump_statistics': jump_stats,
        'yearly_stats': yearly_stats,
        'insample_diagnostics': is_results,
        'oos_split': {
            'IS': f'{df.index[0].date()} to {df.index[oos_start_idx-1].date()}',
            'OOS': f'{oos_start_date.date()} to {df.index[-1].date()}',
            'n_is': oos_start_idx,
            'n_oos': n - oos_start_idx,
        },
        'oos_metrics': oos_metrics,
        'qlike_improvement_vs_HAR_RV_pct': improvements,
        'dm_tests': dm_results,
        'cross_oos_stability': cross_oos_results,
        'best_model': best_model,
        'conclusion': '',  # Filled below
        'elapsed_seconds': round(elapsed, 1),
    }

    # Write conclusion
    best_q = oos_metrics[best_model]['QLIKE']
    har_q = oos_metrics['HAR-RV']['QLIKE']
    cj_q = oos_metrics.get('HAR-CJ', {}).get('QLIKE')

    dm_key_cj = 'HAR-RV vs HAR-CJ'
    dm_cj = dm_results.get(dm_key_cj, {})
    dm_cj_t = dm_cj.get('t_stat', 0)
    dm_cj_sig = dm_cj.get('significant_harvey', False)

    conclusion_parts = [
        f"BNS jump test (alpha=0.001) detects significant jumps on {jump_pct:.1f}% of trading days.",
        f"Jumps contribute {jump_contrib_pct:.1f}% of total realized variance.",
    ]

    if p_jump_given_no > 0:
        conclusion_parts.append(
            f"Jump clustering ratio = {p_jump_given_jump/p_jump_given_no:.2f}x "
            f"(P(jump|jump)={p_jump_given_jump:.3f} vs P(jump|no_jump)={p_jump_given_no:.3f})."
        )

    conclusion_parts.append(f"Night jump share = {night_jump_ratio:.1f}%.")

    if cj_q is not None and har_q is not None:
        imp = improvements.get('HAR-CJ', 0)
        conclusion_parts.append(
            f"HAR-CJ QLIKE={cj_q:.6f} vs HAR-RV QLIKE={har_q:.6f} "
            f"({'+' if imp > 0 else ''}{imp:.2f}% improvement)."
        )
        conclusion_parts.append(
            f"DM test HAR-RV vs HAR-CJ: t={dm_cj_t:.4f} "
            f"({'SIGNIFICANT' if dm_cj_sig else 'not significant'} at Harvey t>3.0)."
        )

    conclusion_parts.append(f"Best OOS model: {best_model} (QLIKE={best_q:.6f}).")

    results['conclusion'] = ' '.join([p for p in conclusion_parts if p])

    # Save results
    results_path = os.path.join(SCRIPT_DIR, 'k851_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {results_path}")

    print(f"\n{'='*70}")
    print(f"CONCLUSION: {results['conclusion']}")
    print(f"{'='*70}")
    print(f"Total time: {elapsed:.0f}s")

    return results


if __name__ == '__main__':
    main()
