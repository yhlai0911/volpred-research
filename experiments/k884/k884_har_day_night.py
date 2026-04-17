#!/usr/bin/env python3
"""
K884: HAR Day/Night Continuous Decomposition for TAIFEX TX
==========================================================

Research Question (EMPIRICAL):
  Does separating RV into day and night components as HAR regressors
  improve full-day variance forecasting compared to standard HAR-RV?
  K849 showed HAR-RV R² jumps from 0.17 to 0.58 when separating day/night.
  K848 showed night vol share grew from 24% to 57% (2017→2026).

Models:
  1. HAR-RV (standard): log(RV_total) ~ HAR(d, w=5d, m=22d) of RV_total
  2. HAR-DN (Day/Night): log(RV_total) ~ RV_day(d,w,m) + RV_night(d,w,m) — 6 regressors
  3. HAR-DN-Asym: HAR-DN + I(r<0)*RV_day(d) + I(r<0)*RV_night(d) — 8 regressors
  4. GJR-GARCH: benchmark on close-to-close returns
  5. PRG Extended: session-periodic GARCH with leverage (from K883)

Common target: σ²_fullday = r²_gap + RV_intra + RV_night
  (Patton 2011 / Hansen & Lunde 2005 framework)

Evaluation:
  Layer 1: QLIKE on common target for ALL models
  Layer 2: DM tests (pairwise, Harvey |t|>3.0)
  Layer 3: Spearman rank correlation with σ²_fullday
  Layer 4: VaR 1%+5% (Kupiec + Christoffersen + Basel)
  Layer 5: ES (Acerbi-Szekely Z-test)

OOS: IS 60% / OOS 40%, rolling refit every 63 days (quarterly)

Error log rules:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - TX: volume-based contract selection, NOT TX1
  - HAR native advantage on RV is mechanical — must convert to common target
  - Fair comparison: all models evaluated on SAME common target σ²_fullday

Data: TAIFEX TX tick ~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_{YYYY}_{MM}_{DD}TX.csv
  Big5 encoding, 2017-05-15 to 2025-12-31 (night session era)

References:
  - Corsi (2009): HAR-RV model
  - Bollerslev & Ghysels (1996): Periodic GARCH
  - Lai et al. (2024): Periodic GARCH with regime switching
  - Hansen & Lunde (2005): Realized GARCH, optimal RV weighting
  - Patton (2011): QLIKE proxy-robust loss
  - Kupiec (1995): VaR back-testing
  - Christoffersen (1998): Conditional coverage VaR test
  - Acerbi & Szekely (2014): ES back-testing

Author: VolPred Research System
Date: 2026-04-05
"""

import os
import sys
import glob
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats as sp_stats
from scipy.optimize import minimize
from numba import njit

warnings.filterwarnings('ignore')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from volpred.stats.model_evaluation import dm_test

# ============================================================
# Configuration
# ============================================================
DATA_DIR = os.path.expanduser("~/Dropbox/TAIFEXDATA/TAIFEXDATA/python")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k884_har_day_night_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k884_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Session boundaries (HHMMSS integer)
NIGHT_PM_START = 150000
NIGHT_PM_END   = 235959
NIGHT_AM_START = 0
NIGHT_AM_END   = 50000
DAY_START      = 84500
DAY_END        = 134500

# OOS config
IS_FRACTION = 0.60
REFIT_FREQ  = 63   # trading days
REFIT_FREQ_SESS = 126  # sessions (= 63 days * 2 sessions/day)

NIGHT_SESSION_START_DATE = "2017-05-15"


# ============================================================
# Numba-accelerated kernels
# ============================================================

@njit(cache=True)
def _gjr_negll(omega, alpha, gamma_p, beta, r, n):
    """GJR-GARCH negative log-likelihood."""
    h0 = 0.0
    cnt = min(50, n)
    for i in range(cnt):
        h0 += r[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8
    h_prev = h0
    ll = 0.0
    for t in range(1, n):
        indicator = 1.0 if r[t - 1] < 0 else 0.0
        h_t = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * indicator + beta * h_prev
        if h_t <= 0:
            return 1e15
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h_t) - 0.5 * r[t] ** 2 / h_t
        h_prev = h_t
    return -ll


@njit(cache=True)
def _gjr_propagate(omega, alpha, gamma_p, beta, r, h0, start, end):
    """Propagate GJR state."""
    h = h0
    for t in range(start, end):
        indicator = 1.0 if r[t - 1] < 0 else 0.0
        h = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * indicator + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


@njit(cache=True)
def _prg_negll(params, r, x, s, n, extended):
    """PRG negative log-likelihood."""
    if extended:
        omega0, alpha0, beta0, omega1, alpha1, beta1, gamma0, gamma1 = (
            params[0], params[1], params[2], params[3], params[4], params[5], params[6], params[7])
    else:
        omega0, alpha0, beta0, omega1, alpha1, beta1 = (
            params[0], params[1], params[2], params[3], params[4], params[5])
        gamma0, gamma1 = 0.0, 0.0

    h0 = 0.0
    cnt = min(50, n)
    for i in range(cnt):
        h0 += r[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8
    h_prev = h0
    ll = 0.0
    for t in range(1, n):
        st = int(s[t])
        x_prev = x[t - 1]
        r_prev = r[t - 1]
        if st == 0:
            lev = gamma0 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h_t = omega0 + alpha0 * x_prev + lev + beta0 * h_prev
        else:
            lev = gamma1 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h_t = omega1 + alpha1 * x_prev + lev + beta1 * h_prev
        if h_t <= 0:
            return 1e15
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h_t) - 0.5 * r[t] ** 2 / h_t
        h_prev = h_t
    return -ll


@njit(cache=True)
def _prg_recursive(params, r, x, s, n, extended):
    """Full h series for PRG."""
    if extended:
        omega0, alpha0, beta0, omega1, alpha1, beta1, gamma0, gamma1 = (
            params[0], params[1], params[2], params[3], params[4], params[5], params[6], params[7])
    else:
        omega0, alpha0, beta0, omega1, alpha1, beta1 = (
            params[0], params[1], params[2], params[3], params[4], params[5])
        gamma0, gamma1 = 0.0, 0.0

    h = np.empty(n)
    cnt = min(50, n)
    h0 = 0.0
    for i in range(cnt):
        h0 += r[i] ** 2
    h0 /= cnt
    if h0 < 1e-12:
        h0 = 1e-8
    h[0] = h0
    for t in range(1, n):
        st = int(s[t])
        x_prev = x[t - 1]
        r_prev = r[t - 1]
        if st == 0:
            lev = gamma0 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h[t] = omega0 + alpha0 * x_prev + lev + beta0 * h[t - 1]
        else:
            lev = gamma1 * x_prev * (1.0 if r_prev < 0 else 0.0)
            h[t] = omega1 + alpha1 * x_prev + lev + beta1 * h[t - 1]
        if h[t] < 1e-12:
            h[t] = 1e-12
    return h


# ============================================================
# Tick data processing (from K883 pattern)
# ============================================================

def time_to_5min_bucket(time_int):
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def safe_volume(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def process_single_file(filepath):
    """Process one TX daily file -> session-level RV, prices, returns."""
    basename = os.path.basename(filepath)
    try:
        parts = basename.replace("Daily_", "").replace("TX.csv", "").split("_")
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
        df['volume'] = df.iloc[:, 5].apply(safe_volume)
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    # --- Volume-based contract selection (TX, NOT TX1) ---
    df['delivery'] = df.iloc[:, 2].astype(str).str.strip()
    vol_by_delivery = df.groupby('delivery')['volume'].sum()
    best_contract = None
    if len(vol_by_delivery) > 0:
        best_contract = vol_by_delivery.idxmax()
        df = df[df['delivery'] == best_contract]

    t = df['time_int'].values
    p = df['price'].values

    night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
    night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
    day_mask = (t >= DAY_START) & (t <= DAY_END)

    def build_5min_returns(session_t, session_p):
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

    def compute_rv(rets):
        if len(rets) < 1:
            return np.nan
        return float(np.sum(rets ** 2))

    day_rets = build_5min_returns(t[day_mask], p[day_mask])
    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])
    night_rets = np.concatenate([night_pm_rets, night_am_rets]) \
        if (len(night_pm_rets) > 0 or len(night_am_rets) > 0) else np.array([])

    rv_day = compute_rv(day_rets)
    rv_night = compute_rv(night_rets)

    day_p = p[day_mask]
    night_pm_p = p[night_pm_mask]
    night_am_p = p[night_am_mask]

    day_open = float(day_p[0]) if len(day_p) > 0 else np.nan
    day_close = float(day_p[-1]) if len(day_p) > 0 else np.nan

    if len(night_am_p) > 0:
        night_close = float(night_am_p[-1])
    elif len(night_pm_p) > 0:
        night_close = float(night_pm_p[-1])
    else:
        night_close = np.nan

    night_open = float(night_pm_p[0]) if len(night_pm_p) > 0 else np.nan

    day_return = np.log(day_close / day_open) if (
        day_open > 0 and not np.isnan(day_open) and not np.isnan(day_close)
    ) else np.nan

    night_return = np.log(night_close / night_open) if (
        night_open > 0 and not np.isnan(night_open) and not np.isnan(night_close)
    ) else np.nan

    n_day_bars = len(day_rets)
    n_night_bars = len(night_rets)

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'day_open': day_open if not np.isnan(day_open) else None,
        'day_close': day_close if not np.isnan(day_close) else None,
        'night_open': night_open if not np.isnan(night_open) else None,
        'night_close': night_close if not np.isnan(night_close) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
        'night_return': night_return if not np.isnan(night_return) else None,
        'n_day_bars': n_day_bars,
        'n_night_bars': n_night_bars,
        'contract': best_contract,
    }


def load_all_rv_data():
    """Load TX files (night session era) and compute 5-min RV."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff_start = "Daily_2017_05_15"
    cutoff_end = "Daily_2026"
    files = [f for f in all_files
             if os.path.basename(f) >= cutoff_start
             and os.path.basename(f) < cutoff_end
             and 'TX1' not in os.path.basename(f)
             and 'TX2' not in os.path.basename(f)]

    print(f"  Found {len(files)} TX files (2017-05-15 to 2025-12-31)")

    results = []
    errors = 0
    n_workers = min(8, os.cpu_count() or 4)
    print(f"  Using {n_workers} parallel workers...")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_file, f): f for f in files}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 500 == 0:
                print(f"    Processed {done_count}/{len(files)} files...")
            try:
                result = future.result()
                if result is not None and result.get('rv_day') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)} days, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    for col in ['rv_day', 'rv_night', 'day_open', 'day_close',
                'night_open', 'night_close', 'day_return', 'night_return']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


# ============================================================
# Build daily data with all components needed
# ============================================================

def build_daily_data(rv_df):
    """
    Build daily DataFrame with:
    - RV components: rv_day, rv_night, rv_total
    - Gap returns and squared gap
    - Common target: σ²_fullday = r²_gap + rv_day + rv_night
    - Close-to-close return for GJR
    - Session-level data for PRG

    TAIFEX file structure for date D:
      - Night session: starts ~15:00 on trading day D-1, ends ~05:00 on day D
      - Day session: 08:45-13:45 on day D
    """
    df = rv_df.copy()
    df = df.dropna(subset=['day_open', 'day_close', 'rv_day'])

    # Previous day close for overnight gap
    df['prev_day_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_day_close'])
    df['r2_gap'] = df['overnight_gap'] ** 2

    # Close-to-close return for GJR
    df['c2c_return'] = np.log(df['day_close'] / df['prev_day_close'])

    # RV total = RV_day + RV_night
    df['rv_total'] = df['rv_day'] + df['rv_night'].fillna(0)

    # Common target: σ²_fullday = r²_gap + RV_day + RV_night
    df['sigma2_fullday'] = df['r2_gap'] + df['rv_day'] + df['rv_night'].fillna(0)

    # Session gap returns for PRG
    df['gap1'] = np.log(df['night_open'] / df['prev_day_close'])  # close->night_open
    df['r2_gap1'] = df['gap1'] ** 2
    df['gap2'] = np.log(df['day_open'] / df['night_close'])  # night_close->day_open
    df['r2_gap2'] = df['gap2'] ** 2

    # x_overnight = rv_night + r²_gap1 + r²_gap2
    df['x_overnight'] = df['rv_night'].fillna(0) + df['r2_gap1'].fillna(0) + df['r2_gap2'].fillna(0)
    mask_no_night = df['rv_night'].isna()
    df.loc[mask_no_night, 'x_overnight'] = df.loc[mask_no_night, 'r2_gap']

    # x_intraday = rv_day (5-min RV from day session)
    df['x_intraday'] = df['rv_day']

    # rv_fullday (for PRG common target)
    df['rv_fullday'] = df['x_overnight'] + df['x_intraday']

    # Drop first row (needs previous close)
    df = df.iloc[1:]
    df = df.dropna(subset=['c2c_return', 'rv_day', 'r2_gap', 'sigma2_fullday'])

    return df


# ============================================================
# HAR Models
# ============================================================

def build_har_features(log_rv, shift_lag=1):
    """Build HAR features: daily, weekly (5d), monthly (22d) averages of log RV.
    All properly lagged by shift_lag to avoid lookahead."""
    s = pd.Series(log_rv)
    d = s.shift(shift_lag).values
    w = s.rolling(5).mean().shift(shift_lag).values
    m = s.rolling(22).mean().shift(shift_lag).values
    return d, w, m


def har_standard_oos(rv_total, is_end, refit_freq=63):
    """
    Model 1: Standard HAR-RV on log(RV_total).
    Predicts RV_total (= RV_day + RV_night). Returns forecasts in LEVEL.
    """
    eps = 1e-12
    log_rv = np.log(np.clip(rv_total, eps, None))
    n = len(log_rv)

    log_d, log_w, log_m = build_har_features(log_rv)
    forecasts = np.full(n, np.nan)
    beta = None

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            train_start = 22
            y_train = log_rv[train_start:t]
            X_train = np.column_stack([log_d[train_start:t], log_w[train_start:t], log_m[train_start:t]])
            valid = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
            if valid.sum() < 50:
                continue
            X_c = np.column_stack([np.ones(valid.sum()), X_train[valid]])
            try:
                beta = np.linalg.lstsq(X_c, y_train[valid], rcond=None)[0]
            except Exception:
                continue

        if beta is not None and np.isfinite(log_d[t]) and np.isfinite(log_w[t]) and np.isfinite(log_m[t]):
            x_t = np.array([1.0, log_d[t], log_w[t], log_m[t]])
            forecasts[t] = np.exp(x_t @ beta)

    return forecasts


def har_dn_oos(rv_day, rv_night, is_end, refit_freq=63, asymmetric=False, c2c_returns=None):
    """
    Model 2/3: HAR-DN (Day/Night decomposed).
    Predicts log(RV_total) from separate day and night HAR lags.

    If asymmetric=True (Model 3), adds I(r<0)*log_rv_day(d) and I(r<0)*log_rv_night(d).
    Returns forecasts of RV_total in LEVEL.
    """
    eps = 1e-12
    rv_total = rv_day + rv_night
    log_rv_total = np.log(np.clip(rv_total, eps, None))
    log_rv_day = np.log(np.clip(rv_day, eps, None))
    log_rv_night = np.log(np.clip(rv_night, eps, None))
    n = len(log_rv_total)

    # Build separate day and night HAR features
    day_d, day_w, day_m = build_har_features(log_rv_day)
    night_d, night_w, night_m = build_har_features(log_rv_night)

    # Asymmetry indicator: I(r_{t-1} < 0) — using close-to-close return
    if asymmetric and c2c_returns is not None:
        neg_ind = (pd.Series(c2c_returns).shift(1) < 0).astype(float).values
    else:
        neg_ind = None

    forecasts = np.full(n, np.nan)
    beta = None

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            train_start = 22
            y_train = log_rv_total[train_start:t]

            # 6 regressors: day(d,w,m) + night(d,w,m)
            X_base = np.column_stack([
                day_d[train_start:t], day_w[train_start:t], day_m[train_start:t],
                night_d[train_start:t], night_w[train_start:t], night_m[train_start:t],
            ])

            if asymmetric and neg_ind is not None:
                # Add 2 asymmetric terms: I(r<0) * log_rv_day(d), I(r<0) * log_rv_night(d)
                asym_day = neg_ind[train_start:t] * day_d[train_start:t]
                asym_night = neg_ind[train_start:t] * night_d[train_start:t]
                X_base = np.column_stack([X_base, asym_day, asym_night])

            valid = np.all(np.isfinite(X_base), axis=1) & np.isfinite(y_train)
            if valid.sum() < 50:
                continue
            X_c = np.column_stack([np.ones(valid.sum()), X_base[valid]])
            try:
                beta = np.linalg.lstsq(X_c, y_train[valid], rcond=None)[0]
            except Exception:
                continue

        if beta is not None:
            # Build feature vector for time t
            feats = [day_d[t], day_w[t], day_m[t], night_d[t], night_w[t], night_m[t]]
            if asymmetric and neg_ind is not None:
                feats.append(neg_ind[t] * day_d[t])
                feats.append(neg_ind[t] * night_d[t])

            if all(np.isfinite(f) for f in feats):
                x_t = np.array([1.0] + feats)
                forecasts[t] = np.exp(x_t @ beta)

    return forecasts


def get_har_betas(rv_day, rv_night, end_idx, asymmetric=False, c2c_returns=None):
    """Get HAR-DN regression coefficients for interpretability."""
    eps = 1e-12
    rv_total = rv_day + rv_night
    log_rv_total = np.log(np.clip(rv_total, eps, None))
    log_rv_day = np.log(np.clip(rv_day, eps, None))
    log_rv_night = np.log(np.clip(rv_night, eps, None))

    day_d, day_w, day_m = build_har_features(log_rv_day)
    night_d, night_w, night_m = build_har_features(log_rv_night)

    train_start = 22
    y = log_rv_total[train_start:end_idx]
    X_base = np.column_stack([
        day_d[train_start:end_idx], day_w[train_start:end_idx], day_m[train_start:end_idx],
        night_d[train_start:end_idx], night_w[train_start:end_idx], night_m[train_start:end_idx],
    ])

    col_names = ['day_d', 'day_w', 'day_m', 'night_d', 'night_w', 'night_m']

    if asymmetric and c2c_returns is not None:
        neg_ind = (pd.Series(c2c_returns).shift(1) < 0).astype(float).values
        asym_d = neg_ind[train_start:end_idx] * day_d[train_start:end_idx]
        asym_n = neg_ind[train_start:end_idx] * night_d[train_start:end_idx]
        X_base = np.column_stack([X_base, asym_d, asym_n])
        col_names += ['asym_day_d', 'asym_night_d']

    valid = np.all(np.isfinite(X_base), axis=1) & np.isfinite(y)
    X_c = np.column_stack([np.ones(valid.sum()), X_base[valid]])
    y_v = y[valid]

    try:
        beta = np.linalg.lstsq(X_c, y_v, rcond=None)[0]
        # Compute R²
        y_hat = X_c @ beta
        ss_res = np.sum((y_v - y_hat) ** 2)
        ss_tot = np.sum((y_v - np.mean(y_v)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Compute t-stats (OLS standard errors)
        n_obs = len(y_v)
        k = X_c.shape[1]
        mse = ss_res / (n_obs - k) if n_obs > k else ss_res
        try:
            var_beta = mse * np.linalg.inv(X_c.T @ X_c).diagonal()
            se_beta = np.sqrt(np.clip(var_beta, 0, None))
            t_stats = beta / np.where(se_beta > 0, se_beta, 1e-15)
        except Exception:
            t_stats = np.full(len(beta), np.nan)
            se_beta = np.full(len(beta), np.nan)

        result = {'const': float(beta[0]), 'R2': float(r2), 'n_obs': int(n_obs)}
        for i, name in enumerate(col_names):
            result[name] = float(beta[i + 1])
            result[f'{name}_t'] = float(t_stats[i + 1])
            result[f'{name}_se'] = float(se_beta[i + 1])
        return result
    except Exception:
        return None


# ============================================================
# GJR-GARCH (daily, close-to-close)
# ============================================================

def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """GJR-GARCH(1,1) on daily close-to-close returns with rolling refit."""
    n = len(returns)
    r = returns.astype(np.float64)
    forecasts = np.full(n, np.nan)

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(r[:min(50, n)])

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = r[:t]
            best_nll = np.inf
            best_p = None
            rng = np.random.RandomState(42)

            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_train) * 0.05, 0.08, 0.06, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.0, 0.15), rng.uniform(0.7, 0.95)]
                try:
                    def obj(params, r_t=r_train):
                        return _gjr_negll(params[0], params[1], params[2], params[3],
                                          r_t, len(r_t))
                    result = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                                      options={'maxiter': 1000})
                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_p = result.x
                except Exception:
                    continue

            if best_p is not None:
                current_params = best_p
                h_state = _gjr_propagate(
                    current_params[0], current_params[1], current_params[2], current_params[3],
                    r[:t], np.var(r[:min(50, t)]), 1, t)

        if current_params is not None:
            omega, alpha, gamma_p, beta = current_params
            indicator = 1.0 if r[t - 1] < 0 else 0.0
            h_state = omega + alpha * r[t - 1] ** 2 + gamma_p * r[t - 1] ** 2 * indicator + beta * h_state
            if h_state < 1e-12:
                h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


# ============================================================
# PRG Extended (session-periodic GARCH with leverage) — from K883
# ============================================================

def estimate_prg(r, x, s, extended=True, n_starts=5):
    """Estimate PRG via MLE with numba-accelerated kernel."""
    n = len(r)
    eps = 1e-8

    if extended:
        bounds = [
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),
            (0.0, 2.0), (0.0, 2.0),
        ]
    else:
        bounds = [
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),
            (eps, 1e-2), (eps, 2.0), (eps, 0.999),
        ]

    best_nll = np.inf
    best_params = None
    rng = np.random.RandomState(42)

    var_ov = np.var(r[s == 0]) if np.sum(s == 0) > 10 else 1e-5
    var_in = np.var(r[s == 1]) if np.sum(s == 1) > 10 else 1e-5

    r_f = r.astype(np.float64)
    x_f = x.astype(np.float64)
    s_f = s.astype(np.float64)

    for start_i in range(n_starts):
        if start_i == 0:
            x0 = [var_ov * 0.05, 0.15, 0.80, var_in * 0.05, 0.15, 0.80]
            if extended:
                x0 += [0.05, 0.05]
        else:
            x0 = [
                rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
            ]
            if extended:
                x0 += [rng.uniform(0.0, 0.2), rng.uniform(0.0, 0.2)]

        try:
            def obj(params, r_f_=r_f, x_f_=x_f, s_f_=s_f, n_=n, ext_=extended):
                p = np.array(params, dtype=np.float64)
                return _prg_negll(p, r_f_, x_f_, s_f_, n_, ext_)

            result = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 2000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def prg_oos_daily_forecast(daily_df, is_end, refit_freq_sess=126):
    """
    Run PRG Extended OOS forecast at session level, aggregate to daily.
    Returns daily forecasts: h_day[t] = h_overnight[t] + h_intraday[t].
    """
    # Build session-level arrays
    sessions = []
    dates = daily_df.index.tolist()
    for dt in dates:
        row = daily_df.loc[dt]
        if pd.isna(row['overnight_gap']) or pd.isna(row['day_return']) or pd.isna(row['rv_day']):
            continue
        sessions.append({'date': dt, 'session_type': 0, 'r': float(row['overnight_gap']),
                         'x': float(row['x_overnight'])})
        sessions.append({'date': dt, 'session_type': 1, 'r': float(row['day_return']),
                         'x': float(row['x_intraday'])})

    sess_df = pd.DataFrame(sessions)
    if len(sess_df) == 0:
        return np.full(len(daily_df), np.nan), None

    r_arr = sess_df['r'].values.astype(np.float64)
    x_arr = sess_df['x'].values.astype(np.float64)
    s_arr = sess_df['session_type'].values.astype(np.float64)
    n_sessions = len(sess_df)
    n_days = n_sessions // 2

    is_end_sess = is_end * 2
    if is_end_sess > n_sessions:
        is_end_sess = n_sessions

    # Initial estimation on IS data
    params_ext, ll_ext = estimate_prg(r_arr[:is_end_sess], x_arr[:is_end_sess],
                                       s_arr[:is_end_sess], extended=True, n_starts=5)
    if params_ext is None:
        return np.full(len(daily_df), np.nan), None

    # Full h series
    h_all = np.full(n_sessions, np.nan)
    current_params = params_ext.copy()

    h_full = _prg_recursive(np.array(current_params, dtype=np.float64),
                            r_arr, x_arr, s_arr, n_sessions, True)
    h_all[:is_end_sess] = h_full[:is_end_sess]

    # OOS with rolling refit
    for t in range(is_end_sess, n_sessions):
        if (t - is_end_sess) % refit_freq_sess == 0:
            p_new, ll_new = estimate_prg(r_arr[:t], x_arr[:t], s_arr[:t],
                                          extended=True, n_starts=3)
            if p_new is not None:
                current_params = p_new
            h_tmp = _prg_recursive(np.array(current_params, dtype=np.float64),
                                   r_arr[:t+1], x_arr[:t+1], s_arr[:t+1], t+1, True)
            h_all[t] = h_tmp[t]
        else:
            st = int(s_arr[t])
            omega = np.array([current_params[0], current_params[3]])
            alpha = np.array([current_params[1], current_params[4]])
            beta_p = np.array([current_params[2], current_params[5]])
            gamma = np.array([current_params[6], current_params[7]])
            h_prev = h_all[t - 1] if not np.isnan(h_all[t - 1]) else 1e-8
            lev = gamma[st] * x_arr[t - 1] * (1.0 if r_arr[t - 1] < 0 else 0.0)
            h_all[t] = omega[st] + alpha[st] * x_arr[t - 1] + lev + beta_p[st] * h_prev
            if h_all[t] < 1e-12:
                h_all[t] = 1e-12

    # Aggregate to daily
    h_daily = np.full(n_days, np.nan)
    for d in range(n_days):
        i_ov = 2 * d
        i_in = 2 * d + 1
        if i_in < n_sessions:
            h_ov = h_all[i_ov] if not np.isnan(h_all[i_ov]) else 0
            h_in = h_all[i_in] if not np.isnan(h_all[i_in]) else 0
            h_daily[d] = h_ov + h_in

    # Align h_daily to daily_df index
    # sessions may have fewer days if some rows had NaN
    h_out = np.full(len(daily_df), np.nan)
    session_dates = [sessions[2*d]['date'] for d in range(n_days)]
    for d_idx, dt in enumerate(session_dates):
        try:
            pos = daily_df.index.get_loc(dt)
            if d_idx < len(h_daily):
                h_out[pos] = h_daily[d_idx]
        except KeyError:
            continue

    return h_out, params_ext


# ============================================================
# Conversion Functions (HAR predicts RV_total, missing gap)
# ============================================================

def compute_scaling_ratios(daily_df, is_end):
    """Compute scaling ratios from IS data for model conversions."""
    df_is = daily_df.iloc[:is_end]
    sigma2 = df_is['sigma2_fullday'].values
    r2_gap = df_is['r2_gap'].values
    rv_day = df_is['rv_day'].values
    rv_night = df_is['rv_night'].fillna(0).values
    rv_total = df_is['rv_total'].values

    valid = sigma2 > 0
    gap_share = np.mean(r2_gap[valid] / sigma2[valid])
    rv_total_share = np.mean(rv_total[valid] / sigma2[valid])

    # Regression: r²_gap = a + b * RV_total
    valid_reg = np.isfinite(rv_total) & np.isfinite(r2_gap)
    X_reg = np.column_stack([np.ones(valid_reg.sum()), rv_total[valid_reg]])
    y_reg = r2_gap[valid_reg]
    try:
        gap_reg_beta = np.linalg.lstsq(X_reg, y_reg, rcond=None)[0]
    except Exception:
        gap_reg_beta = np.array([np.mean(r2_gap[valid_reg]), 0.0])

    mean_gap = np.mean(r2_gap[valid])

    # PRG native = x_overnight + x_intraday (not same as sigma2_fullday)
    prg_native = df_is['x_overnight'].values + df_is['x_intraday'].values
    prg_share = np.mean(prg_native[valid] / sigma2[valid])

    return {
        'gap_share': float(gap_share),
        'rv_total_share': float(rv_total_share),
        'mean_gap': float(mean_gap),
        'gap_reg_intercept': float(gap_reg_beta[0]),
        'gap_reg_slope': float(gap_reg_beta[1]),
        'prg_native_share': float(prg_share),
    }


def convert_har_to_fullday(har_forecasts, ratios, method='additive'):
    """
    HAR predicts RV_total = RV_day + RV_night. Missing r²_gap.
    additive: ĥ_fullday = ĥ_HAR + mean_gap
    regression: ĥ_fullday = ĥ_HAR + (a + b * ĥ_HAR)
    """
    converted = np.full_like(har_forecasts, np.nan)
    valid = np.isfinite(har_forecasts) & (har_forecasts > 0)
    if method == 'additive':
        converted[valid] = har_forecasts[valid] + ratios['mean_gap']
    elif method == 'regression':
        a = ratios['gap_reg_intercept']
        b = ratios['gap_reg_slope']
        converted[valid] = har_forecasts[valid] + a + b * har_forecasts[valid]
    return converted


def convert_prg_to_fullday(prg_forecasts, ratios):
    """PRG predicts h_gap + h_intra. Scale to full-day."""
    converted = np.full_like(prg_forecasts, np.nan)
    valid = np.isfinite(prg_forecasts) & (prg_forecasts > 0)
    converted[valid] = prg_forecasts[valid] / ratios['prg_native_share']
    return converted


# ============================================================
# Evaluation Metrics
# ============================================================

def qlike(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r, f = realized[valid], forecast[valid]
    if len(r) == 0:
        return np.nan, 0
    return float(np.mean(r / f - np.log(r / f) - 1)), int(len(r))


def qlike_loss_array(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r, f = realized[valid], forecast[valid]
    loss[valid] = r / f - np.log(r / f) - 1
    return loss


def mse_val(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    if valid.sum() == 0:
        return np.nan
    return float(np.mean((realized[valid] - forecast[valid]) ** 2))


def mae_val(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    if valid.sum() == 0:
        return np.nan
    return float(np.mean(np.abs(realized[valid] - forecast[valid])))


def hmse_val(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    if valid.sum() == 0:
        return np.nan
    r, f = realized[valid], forecast[valid]
    return float(np.mean((1 - r / f) ** 2))


def spearman_corr(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    if valid.sum() < 10:
        return np.nan, np.nan
    rho, p = sp_stats.spearmanr(realized[valid], forecast[valid])
    return float(rho), float(p)


# ============================================================
# VaR + ES Back-testing
# ============================================================

def compute_var_es(sigma2_forecast, alpha_level, df_t=5):
    """VaR and ES from Student-t distribution with scale correction."""
    sigma = np.sqrt(np.clip(sigma2_forecast, 1e-12, None))
    scale = np.sqrt((df_t - 2) / df_t)
    z_alpha = sp_stats.t.ppf(alpha_level, df_t)
    var_t = sigma * z_alpha / scale
    f_val = sp_stats.t.pdf(z_alpha, df_t)
    es_t = sigma / scale * (-f_val * (df_t + z_alpha ** 2) / ((df_t - 1) * alpha_level))
    return var_t, es_t


def kupiec_test(violations, n_obs, alpha):
    n_viol = np.sum(violations)
    p_hat = n_viol / n_obs if n_obs > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return np.nan, np.nan
    lr = 2 * (n_viol * np.log(p_hat / alpha) + (n_obs - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
    p_value = 1 - sp_stats.chi2.cdf(lr, 1)
    return float(lr), float(p_value)


def christoffersen_test(violations):
    n = len(violations)
    if n < 4:
        return np.nan, np.nan
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i - 1] == 0 and violations[i] == 0: n00 += 1
        elif violations[i - 1] == 0 and violations[i] == 1: n01 += 1
        elif violations[i - 1] == 1 and violations[i] == 0: n10 += 1
        else: n11 += 1
    if (n00 + n01) == 0 or (n10 + n11) == 0 or n01 + n11 == 0:
        return np.nan, np.nan
    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11)
    p_hat = (n01 + n11) / n
    try:
        lr_ind = 2 * (
            n00 * np.log(max(1 - p01, 1e-15) / max(1 - p_hat, 1e-15))
            + n01 * np.log(max(p01, 1e-15) / max(p_hat, 1e-15))
            + n10 * np.log(max(1 - p11, 1e-15) / max(1 - p_hat, 1e-15))
            + n11 * np.log(max(p11, 1e-15) / max(p_hat, 1e-15))
        )
    except (ValueError, ZeroDivisionError):
        return np.nan, np.nan
    p_value = 1 - sp_stats.chi2.cdf(lr_ind, 1)
    return float(lr_ind), float(p_value)


def acerbi_szekely_test(returns, var_forecast, es_forecast, alpha, n_boot=1000):
    """Acerbi & Szekely (2014) ES back-test (Z2 statistic)."""
    violations = returns < var_forecast
    n_viol = np.sum(violations)
    if n_viol < 3:
        return np.nan, np.nan
    es_safe = np.where(np.abs(es_forecast) > 1e-15, es_forecast, -1e-15)
    z2 = np.mean(returns * violations / (alpha * es_safe)) + 1

    rng = np.random.RandomState(42)
    z2_boot = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.choice(len(returns), len(returns), replace=True)
        r_b = returns[idx]
        v_b = var_forecast[idx]
        es_b = es_forecast[idx]
        viol_b = r_b < v_b
        es_safe_b = np.where(np.abs(es_b) > 1e-15, es_b, -1e-15)
        z2_boot[b] = np.mean(r_b * viol_b / (alpha * es_safe_b)) + 1

    p_value = np.mean(z2_boot <= z2)
    return float(z2), float(p_value)


def basel_traffic_light(violation_rate, alpha):
    ratio = violation_rate / alpha
    if ratio <= 1.0:
        return "GREEN"
    elif ratio <= 1.5:
        return "YELLOW"
    else:
        return "RED"


def run_var_backtest(returns, sigma2_forecast, alpha_level=0.01, df_t=5):
    """Full VaR + ES back-test."""
    valid = np.isfinite(returns) & np.isfinite(sigma2_forecast) & (sigma2_forecast > 0)
    r = returns[valid]
    s2 = sigma2_forecast[valid]
    n_obs = len(r)
    if n_obs < 50:
        return None
    var_f, es_f = compute_var_es(s2, alpha_level, df_t)
    violations = (r < var_f).astype(int)
    viol_rate = np.mean(violations)
    kup_lr, kup_p = kupiec_test(violations, n_obs, alpha_level)
    cc_lr, cc_p = christoffersen_test(violations)
    as_z2, as_p = acerbi_szekely_test(r, var_f, es_f, alpha_level)
    traffic = basel_traffic_light(viol_rate, alpha_level)
    return {
        'alpha': alpha_level,
        'n_obs': n_obs,
        'n_violations': int(np.sum(violations)),
        'violation_rate': float(viol_rate),
        'expected_rate': alpha_level,
        'kupiec_LR': kup_lr if np.isfinite(kup_lr) else None,
        'kupiec_p': kup_p if np.isfinite(kup_p) else None,
        'christoffersen_LR': cc_lr if np.isfinite(cc_lr) else None,
        'christoffersen_p': cc_p if np.isfinite(cc_p) else None,
        'acerbi_szekely_Z2': as_z2 if np.isfinite(as_z2) else None,
        'acerbi_szekely_p': as_p if np.isfinite(as_p) else None,
        'basel_traffic_light': traffic,
    }


# ============================================================
# Charts
# ============================================================

def make_charts(model_results, daily_df_oos, charts_dir, daily_df_full, is_end):
    """Generate comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE comparison bar chart (main result)
    fig, ax = plt.subplots(figsize=(12, 7))
    names = []
    qlikes = []
    for name, data in model_results.items():
        if 'qlike_fullday' in data and data['qlike_fullday'] is not None:
            names.append(name)
            qlikes.append(data['qlike_fullday'])

    if len(names) > 0:
        sorted_idx = np.argsort(qlikes)
        names = [names[i] for i in sorted_idx]
        qlikes = [qlikes[i] for i in sorted_idx]
        colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(names))]
        bars = ax.barh(range(len(names)), qlikes, color=colors)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=11)
        ax.set_xlabel('QLIKE on common target (lower = better)', fontsize=12)
        ax.set_title('K884: HAR Day/Night Decomposition\n'
                      'All models on common target sigma2_fullday = r2_gap + RV_day + RV_night', fontsize=12)
        for bar, val in zip(bars, qlikes):
            ax.text(bar.get_width() + max(qlikes) * 0.01, bar.get_y() + bar.get_height() / 2,
                    f'{val:.4f}', va='center', fontsize=10, fontweight='bold')
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'qlike_comparison.png'), dpi=150)
        plt.close()

    # Chart 2: Spearman correlation
    fig, ax = plt.subplots(figsize=(12, 7))
    names_sp = []
    rhos = []
    for name, data in model_results.items():
        if 'spearman_fullday' in data and data['spearman_fullday'] is not None:
            names_sp.append(name)
            rhos.append(data['spearman_fullday'])
    if names_sp:
        sorted_idx = np.argsort(rhos)[::-1]
        names_sp = [names_sp[i] for i in sorted_idx]
        rhos = [rhos[i] for i in sorted_idx]
        colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(names_sp))]
        bars = ax.barh(range(len(names_sp)), rhos, color=colors)
        ax.set_yticks(range(len(names_sp)))
        ax.set_yticklabels(names_sp, fontsize=11)
        ax.set_xlabel('Spearman rho (higher = better)', fontsize=12)
        ax.set_title('K884: Spearman Rank Correlation with sigma2_fullday', fontsize=12)
        for bar, val in zip(bars, rhos):
            ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
                    f'{val:.4f}', va='center', fontsize=10)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'spearman_comparison.png'), dpi=150)
        plt.close()

    # Chart 3: HAR-DN coefficient comparison (day vs night)
    har_dn_betas = model_results.get('HAR_DN', {}).get('betas_is', None)
    if har_dn_betas is not None:
        fig, ax = plt.subplots(figsize=(10, 6))
        day_coefs = [har_dn_betas.get('day_d', 0), har_dn_betas.get('day_w', 0), har_dn_betas.get('day_m', 0)]
        night_coefs = [har_dn_betas.get('night_d', 0), har_dn_betas.get('night_w', 0), har_dn_betas.get('night_m', 0)]
        x_pos = np.arange(3)
        width = 0.35
        bars1 = ax.bar(x_pos - width/2, day_coefs, width, label='Day Session', color='#f39c12')
        bars2 = ax.bar(x_pos + width/2, night_coefs, width, label='Night Session', color='#2c3e50')
        ax.set_xticks(x_pos)
        ax.set_xticklabels(['Daily (d)', 'Weekly (w)', 'Monthly (m)'], fontsize=11)
        ax.set_ylabel('Coefficient', fontsize=12)
        ax.set_title('K884: HAR-DN Coefficients — Day vs Night Session\n'
                      '(Predicting log(RV_total))', fontsize=12)
        ax.legend(fontsize=11)
        ax.axhline(0, color='gray', linestyle='--', linewidth=0.5)
        for bars in [bars1, bars2]:
            for bar in bars:
                val = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2, val + 0.005,
                        f'{val:.3f}', ha='center', va='bottom', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'har_dn_coefficients.png'), dpi=150)
        plt.close()

    # Chart 4: VaR backtest summary
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    for ax_i, alpha in enumerate([0.01, 0.05]):
        ax = axes[ax_i]
        names_var = []
        viol_rates = []
        bar_colors = []
        zone_map = {'GREEN': '#2ecc71', 'YELLOW': '#f39c12', 'RED': '#e74c3c'}
        for name, data in model_results.items():
            var_key = f'var_backtest_{int(alpha*100)}pct'
            if var_key in data and data[var_key] is not None:
                names_var.append(name)
                viol_rates.append(data[var_key]['violation_rate'])
                bar_colors.append(zone_map.get(data[var_key]['basel_traffic_light'], '#95a5a6'))
        if names_var:
            bars = ax.barh(range(len(names_var)), viol_rates, color=bar_colors)
            ax.axvline(alpha, color='black', linestyle='--', label=f'Expected {alpha*100:.0f}%')
            ax.set_yticks(range(len(names_var)))
            ax.set_yticklabels(names_var, fontsize=9)
            ax.set_xlabel('Violation Rate', fontsize=11)
            ax.set_title(f'VaR {int(alpha*100)}% Back-test', fontsize=12)
            ax.legend(fontsize=9)
            for bar, val in zip(bars, viol_rates):
                ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height() / 2,
                        f'{val:.4f}', va='center', fontsize=9)
    plt.suptitle('K884: VaR Back-testing — Kupiec + Basel Traffic Light', fontsize=13, y=1.01)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'var_backtest.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # Chart 5: Night vol share over time (from K848 context)
    fig, ax = plt.subplots(figsize=(14, 5))
    rv_day_roll = daily_df_full['rv_day'].rolling(252).mean()
    rv_night_roll = daily_df_full['rv_night'].fillna(0).rolling(252).mean()
    night_share_roll = rv_night_roll / (rv_day_roll + rv_night_roll)
    ax.plot(daily_df_full.index, night_share_roll, color='#2c3e50', linewidth=1.5)
    ax.axvline(daily_df_full.index[is_end], color='red', linestyle='--', label='IS/OOS split')
    ax.set_ylabel('Night Session Vol Share (252-day MA)', fontsize=12)
    ax.set_title('K884: Night Session Volatility Share Over Time\n'
                 '(Motivation: night share growing => separate modeling matters)', fontsize=12)
    ax.legend(fontsize=10)
    ax.set_ylim(0, 1)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'night_vol_share.png'), dpi=150)
    plt.close()

    # Chart 6: DM test heatmap
    model_names = list(model_results.keys())
    n_models = len(model_names)
    dm_matrix = np.zeros((n_models, n_models))
    for i, name_i in enumerate(model_names):
        for j, name_j in enumerate(model_names):
            if i == j:
                continue
            key = f'{name_i}_vs_{name_j}'
            dm_data = model_results.get(name_i, {}).get('dm_tests', {}).get(key, {})
            dm_matrix[i, j] = dm_data.get('t_stat', 0)

    if n_models > 1:
        fig, ax = plt.subplots(figsize=(9, 8))
        im = ax.imshow(dm_matrix, cmap='RdBu_r', vmin=-6, vmax=6)
        ax.set_xticks(range(n_models))
        ax.set_yticks(range(n_models))
        ax.set_xticklabels(model_names, rotation=45, ha='right', fontsize=9)
        ax.set_yticklabels(model_names, fontsize=9)
        for i in range(n_models):
            for j in range(n_models):
                txt = f'{dm_matrix[i, j]:.2f}'
                color = 'white' if abs(dm_matrix[i, j]) > 3 else 'black'
                ax.text(j, i, txt, ha='center', va='center', fontsize=8, color=color)
        ax.set_title('K884: DM Test t-statistics (QLIKE)\nnegative = row better than column\n'
                      '|t| > 3.0 = significant (Harvey 2016)', fontsize=11)
        plt.colorbar(im, ax=ax, shrink=0.8)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'dm_heatmap.png'), dpi=150)
        plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# Main
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K884: HAR Day/Night Continuous Decomposition for TAIFEX TX")
    print("      Volume-Based Rollover (TX, NOT TX1)")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Load tick data
    # ----------------------------------------------------------
    print("\n[1/8] Loading TAIFEX TX tick data...")
    rv_df = load_all_rv_data()
    print(f"  Loaded {len(rv_df)} trading days: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")

    # ----------------------------------------------------------
    # 2. Build daily data
    # ----------------------------------------------------------
    print("\n[2/8] Building daily data with variance components...")
    daily_df = build_daily_data(rv_df)
    n_daily = len(daily_df)
    is_end = int(n_daily * IS_FRACTION)
    oos_n = n_daily - is_end

    print(f"  Total days: {n_daily}")
    print(f"  IS: {is_end} days ({daily_df.index[0].date()} to {daily_df.index[is_end-1].date()})")
    print(f"  OOS: {oos_n} days ({daily_df.index[is_end].date()} to {daily_df.index[-1].date()})")

    # Descriptive statistics
    for period, start, end in [('IS', 0, is_end), ('OOS', is_end, n_daily)]:
        sub = daily_df.iloc[start:end]
        s2 = sub['sigma2_fullday']
        rv_d = sub['rv_day']
        rv_n = sub['rv_night'].fillna(0)
        gap = sub['r2_gap']
        print(f"\n  {period} Variance Decomposition:")
        print(f"    sigma2_fullday  = {s2.mean():.2e}")
        print(f"    r2_gap          = {gap.mean():.2e} ({gap.mean()/s2.mean():.1%})")
        print(f"    RV_day          = {rv_d.mean():.2e} ({rv_d.mean()/s2.mean():.1%})")
        print(f"    RV_night        = {rv_n.mean():.2e} ({rv_n.mean()/s2.mean():.1%})")

        # Night share evolution
        night_share_early = rv_n.iloc[:min(252, len(rv_n))].mean() / \
            (rv_d.iloc[:min(252, len(rv_d))].mean() + rv_n.iloc[:min(252, len(rv_n))].mean())
        night_share_late = rv_n.iloc[-min(252, len(rv_n)):].mean() / \
            (rv_d.iloc[-min(252, len(rv_d)):].mean() + rv_n.iloc[-min(252, len(rv_n)):].mean())
        print(f"    Night share (first yr): {night_share_early:.1%}")
        print(f"    Night share (last yr):  {night_share_late:.1%}")

    # ----------------------------------------------------------
    # 3. Scaling ratios
    # ----------------------------------------------------------
    print("\n[3/8] Computing scaling ratios from IS data...")
    ratios = compute_scaling_ratios(daily_df, is_end)
    print(f"  gap_share     = {ratios['gap_share']:.4f}")
    print(f"  rv_total_share = {ratios['rv_total_share']:.4f}")
    print(f"  prg_native_share = {ratios['prg_native_share']:.4f}")
    print(f"  mean_gap      = {ratios['mean_gap']:.2e}")

    # ----------------------------------------------------------
    # 4. HAR Standard (Model 1)
    # ----------------------------------------------------------
    print("\n[4/8] HAR-RV Standard (3 regressors)...")
    rv_total = daily_df['rv_total'].values
    h_har_std_rv = har_standard_oos(rv_total, is_end, refit_freq=REFIT_FREQ)
    h_har_std_fullday = convert_har_to_fullday(h_har_std_rv, ratios, method='additive')
    print(f"  OOS forecasts: {np.sum(np.isfinite(h_har_std_fullday[is_end:]))} days")

    # Get IS R²
    har_std_betas = get_har_betas(
        daily_df['rv_day'].values[:is_end],
        daily_df['rv_night'].fillna(0).values[:is_end],
        is_end)  # Using standard HAR on rv_total — need a variant
    # Actually for standard HAR, we just run on rv_total
    eps = 1e-12
    log_rv_total = np.log(np.clip(rv_total[:is_end], eps, None))
    d_, w_, m_ = build_har_features(log_rv_total)
    train_start = 22
    y_is = log_rv_total[train_start:]
    X_is = np.column_stack([d_[train_start:], w_[train_start:], m_[train_start:]])
    valid_is = np.all(np.isfinite(X_is), axis=1) & np.isfinite(y_is)
    X_c_is = np.column_stack([np.ones(valid_is.sum()), X_is[valid_is]])
    beta_is = np.linalg.lstsq(X_c_is, y_is[valid_is], rcond=None)[0]
    y_hat_is = X_c_is @ beta_is
    ss_res = np.sum((y_is[valid_is] - y_hat_is) ** 2)
    ss_tot = np.sum((y_is[valid_is] - np.mean(y_is[valid_is])) ** 2)
    r2_har_std = 1 - ss_res / ss_tot
    print(f"  IS R² (log scale): {r2_har_std:.4f}")
    print(f"  Coefficients: const={beta_is[0]:.4f}, d={beta_is[1]:.4f}, w={beta_is[2]:.4f}, m={beta_is[3]:.4f}")

    # ----------------------------------------------------------
    # 5. HAR-DN (Model 2) and HAR-DN-Asym (Model 3)
    # ----------------------------------------------------------
    print("\n[5/8] HAR-DN (6 regressors) and HAR-DN-Asym (8 regressors)...")
    rv_day = daily_df['rv_day'].values
    rv_night_filled = daily_df['rv_night'].fillna(0).values
    c2c_returns = daily_df['c2c_return'].values

    # HAR-DN
    h_har_dn_rv = har_dn_oos(rv_day, rv_night_filled, is_end, refit_freq=REFIT_FREQ,
                              asymmetric=False)
    h_har_dn_fullday = convert_har_to_fullday(h_har_dn_rv, ratios, method='additive')
    print(f"  HAR-DN OOS forecasts: {np.sum(np.isfinite(h_har_dn_fullday[is_end:]))} days")

    # HAR-DN IS coefficients
    har_dn_betas = get_har_betas(rv_day[:is_end], rv_night_filled[:is_end], is_end,
                                  asymmetric=False)
    if har_dn_betas:
        print(f"  HAR-DN IS R² (log): {har_dn_betas['R2']:.4f}")
        print(f"  Day  coefficients: d={har_dn_betas['day_d']:.4f} (t={har_dn_betas['day_d_t']:.2f}), "
              f"w={har_dn_betas['day_w']:.4f} (t={har_dn_betas['day_w_t']:.2f}), "
              f"m={har_dn_betas['day_m']:.4f} (t={har_dn_betas['day_m_t']:.2f})")
        print(f"  Night coefficients: d={har_dn_betas['night_d']:.4f} (t={har_dn_betas['night_d_t']:.2f}), "
              f"w={har_dn_betas['night_w']:.4f} (t={har_dn_betas['night_w_t']:.2f}), "
              f"m={har_dn_betas['night_m']:.4f} (t={har_dn_betas['night_m_t']:.2f})")

    # HAR-DN-Asym
    h_har_dn_asym_rv = har_dn_oos(rv_day, rv_night_filled, is_end, refit_freq=REFIT_FREQ,
                                    asymmetric=True, c2c_returns=c2c_returns)
    h_har_dn_asym_fullday = convert_har_to_fullday(h_har_dn_asym_rv, ratios, method='additive')
    print(f"  HAR-DN-Asym OOS forecasts: {np.sum(np.isfinite(h_har_dn_asym_fullday[is_end:]))} days")

    # HAR-DN-Asym IS coefficients
    har_dn_asym_betas = get_har_betas(rv_day[:is_end], rv_night_filled[:is_end], is_end,
                                       asymmetric=True, c2c_returns=c2c_returns[:is_end])
    if har_dn_asym_betas:
        print(f"  HAR-DN-Asym IS R² (log): {har_dn_asym_betas['R2']:.4f}")
        if 'asym_day_d' in har_dn_asym_betas:
            print(f"  Asymmetry: day_asym={har_dn_asym_betas['asym_day_d']:.4f} (t={har_dn_asym_betas['asym_day_d_t']:.2f}), "
                  f"night_asym={har_dn_asym_betas['asym_night_d']:.4f} (t={har_dn_asym_betas['asym_night_d_t']:.2f})")

    # ----------------------------------------------------------
    # 6. GJR-GARCH benchmark
    # ----------------------------------------------------------
    print("\n[6/8] GJR-GARCH on close-to-close returns...")
    c2c_clean = np.where(np.isfinite(c2c_returns), c2c_returns, 0.0)
    h_gjr_daily = gjr_oos_forecast(c2c_clean, is_end, refit_freq=REFIT_FREQ)
    print(f"  GJR OOS forecasts: {np.sum(np.isfinite(h_gjr_daily[is_end:]))} days")

    # ----------------------------------------------------------
    # 7. PRG Extended
    # ----------------------------------------------------------
    print("\n[7/8] PRG Extended (8 params with leverage)...")
    h_prg_daily, prg_params = prg_oos_daily_forecast(daily_df, is_end, refit_freq_sess=REFIT_FREQ_SESS)
    h_prg_fullday = convert_prg_to_fullday(h_prg_daily, ratios)
    print(f"  PRG Extended OOS forecasts: {np.sum(np.isfinite(h_prg_fullday[is_end:]))} days")
    if prg_params is not None:
        print(f"  PRG params: omega0={prg_params[0]:.2e}, alpha0={prg_params[1]:.4f}, beta0={prg_params[2]:.4f}")
        print(f"              omega1={prg_params[3]:.2e}, alpha1={prg_params[4]:.4f}, beta1={prg_params[5]:.4f}")
        print(f"              gamma0={prg_params[6]:.4f}, gamma1={prg_params[7]:.4f}")

    # ----------------------------------------------------------
    # 8. Evaluation
    # ----------------------------------------------------------
    print("\n[8/8] Evaluation on OOS period...")

    target_oos = daily_df['sigma2_fullday'].values[is_end:]
    c2c_oos = c2c_clean[is_end:]

    model_forecasts = {
        'HAR_Standard': h_har_std_fullday[is_end:],
        'HAR_DN': h_har_dn_fullday[is_end:],
        'HAR_DN_Asym': h_har_dn_asym_fullday[is_end:],
        'GJR_GARCH': h_gjr_daily[is_end:],
        'PRG_Extended': h_prg_fullday[is_end:],
    }

    model_results = {}

    # Compute metrics for each model
    for name, forecast in model_forecasts.items():
        result = {}
        valid = np.isfinite(target_oos) & np.isfinite(forecast) & (forecast > 0) & (target_oos > 0)
        n_valid = int(valid.sum())
        result['n_oos'] = n_valid

        if n_valid < 50:
            print(f"  {name}: insufficient OOS data ({n_valid})")
            model_results[name] = result
            continue

        q, q_n = qlike(target_oos, forecast)
        result['qlike_fullday'] = q
        result['mse_fullday'] = mse_val(target_oos, forecast)
        result['mae_fullday'] = mae_val(target_oos, forecast)
        result['hmse_fullday'] = hmse_val(target_oos, forecast)

        rho, p_sp = spearman_corr(target_oos, forecast)
        result['spearman_fullday'] = rho
        result['spearman_p'] = p_sp

        # Also store native QLIKE (HAR on RV_total, before gap conversion)
        if name.startswith('HAR'):
            rv_total_oos = daily_df['rv_total'].values[is_end:]
            if name == 'HAR_Standard':
                q_native, _ = qlike(rv_total_oos, h_har_std_rv[is_end:])
            elif name == 'HAR_DN':
                q_native, _ = qlike(rv_total_oos, h_har_dn_rv[is_end:])
            elif name == 'HAR_DN_Asym':
                q_native, _ = qlike(rv_total_oos, h_har_dn_asym_rv[is_end:])
            else:
                q_native = None
            result['qlike_native_rv_total'] = q_native

        # VaR + ES backtest at 1% and 5%
        for alpha in [0.01, 0.05]:
            var_result = run_var_backtest(c2c_oos, forecast, alpha_level=alpha, df_t=5)
            result[f'var_backtest_{int(alpha*100)}pct'] = var_result

        model_results[name] = result
        print(f"  {name}: QLIKE={q:.6f}, Spearman={rho:.4f}, n={n_valid}")

    # Store HAR-DN betas for charts
    if har_dn_betas:
        model_results['HAR_DN']['betas_is'] = har_dn_betas
    if har_dn_asym_betas:
        model_results['HAR_DN_Asym']['betas_is'] = har_dn_asym_betas

    # Store HAR standard info
    model_results['HAR_Standard']['is_r2_log'] = float(r2_har_std)
    model_results['HAR_Standard']['is_betas'] = {
        'const': float(beta_is[0]), 'd': float(beta_is[1]),
        'w': float(beta_is[2]), 'm': float(beta_is[3])
    }

    # DM tests (pairwise)
    print("\n  DM Tests (pairwise, Harvey |t|>3.0):")
    model_names = list(model_forecasts.keys())
    dm_all = {}

    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            name_i = model_names[i]
            name_j = model_names[j]
            loss_i = qlike_loss_array(target_oos, model_forecasts[name_i])
            loss_j = qlike_loss_array(target_oos, model_forecasts[name_j])
            valid_both = np.isfinite(loss_i) & np.isfinite(loss_j)
            if valid_both.sum() < 50:
                continue
            t_stat, p_val = dm_test(loss_i[valid_both], loss_j[valid_both], h=1)
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
            winner = name_i if t_stat < 0 else name_j
            print(f"    {name_i} vs {name_j}: t={t_stat:.3f}, p={p_val:.4f} {sig} (winner: {winner})")

            dm_entry = {
                't_stat': float(t_stat), 'p_value': float(p_val),
                'significant_harvey': abs(t_stat) > 3.0, 'winner': winner,
            }
            key_ij = f'{name_i}_vs_{name_j}'
            key_ji = f'{name_j}_vs_{name_i}'

            model_results.setdefault(name_i, {}).setdefault('dm_tests', {})[key_ij] = dm_entry
            dm_entry_rev = dm_entry.copy()
            dm_entry_rev['t_stat'] = -float(t_stat)
            model_results.setdefault(name_j, {}).setdefault('dm_tests', {})[key_ji] = dm_entry_rev
            dm_all[key_ij] = dm_entry

    # Key comparison: HAR-DN vs HAR-Standard (the main research question)
    print("\n  KEY COMPARISON: HAR-DN vs HAR-Standard")
    key_dn_vs_std = 'HAR_Standard_vs_HAR_DN'
    if key_dn_vs_std in dm_all:
        dm = dm_all[key_dn_vs_std]
        print(f"    DM t = {dm['t_stat']:.3f} (winner: {dm['winner']})")
        q_std = model_results['HAR_Standard'].get('qlike_fullday', np.nan)
        q_dn = model_results['HAR_DN'].get('qlike_fullday', np.nan)
        pct_improvement = (q_std - q_dn) / q_std * 100 if q_std > 0 else 0
        print(f"    QLIKE improvement: {pct_improvement:.2f}%")
    else:
        # Try the reverse key
        key_alt = 'HAR_DN_vs_HAR_Standard'
        for key in dm_all:
            if 'HAR_Standard' in key and 'HAR_DN' in key and 'Asym' not in key:
                dm = dm_all[key]
                print(f"    DM t = {dm['t_stat']:.3f} (winner: {dm['winner']})")
                break

    # ----------------------------------------------------------
    # Charts
    # ----------------------------------------------------------
    print("\n  Generating charts...")
    try:
        make_charts(model_results, daily_df.iloc[is_end:], CHARTS_DIR, daily_df, is_end)
    except Exception as e:
        print(f"  Chart generation error: {e}")
        import traceback
        traceback.print_exc()

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    elapsed = time.time() - t0

    # Clean model_results for JSON
    for name in model_results:
        for key in list(model_results[name].keys()):
            val = model_results[name][key]
            if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
                model_results[name][key] = None

    # Find winner
    qlikes_all = {name: model_results[name].get('qlike_fullday')
                  for name in model_results if model_results[name].get('qlike_fullday') is not None}
    winner = min(qlikes_all, key=qlikes_all.get) if qlikes_all else "N/A"

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY: K884 HAR Day/Night Decomposition")
    print("=" * 70)
    print(f"\n{'Model':<18} {'QLIKE':>10} {'Spearman':>10} {'HMSE':>10} {'VaR1% zone':>12}")
    print("-" * 62)
    for name in model_names:
        r = model_results.get(name, {})
        q = r.get('qlike_fullday', None)
        sp = r.get('spearman_fullday', None)
        hm = r.get('hmse_fullday', None)
        v1 = r.get('var_backtest_1pct', {})
        zone = v1.get('basel_traffic_light', '?') if v1 else '?'
        q_str = f"{q:.6f}" if q is not None else "N/A"
        sp_str = f"{sp:.4f}" if sp is not None else "N/A"
        hm_str = f"{hm:.6f}" if hm is not None else "N/A"
        marker = " <-- BEST" if name == winner else ""
        print(f"  {name:<16} {q_str:>10} {sp_str:>10} {hm_str:>10} {zone:>12}{marker}")

    print(f"\n  Winner (QLIKE): {winner}")
    print(f"  Elapsed: {elapsed:.1f}s")

    output = {
        'experiment_id': 'K884',
        'title': 'HAR Day/Night Continuous Decomposition for TAIFEX TX',
        'date': datetime.now().isoformat(),
        'data_source': 'TAIFEX TX tick data (volume-based rollover)',
        'data_period': f"{daily_df.index[0].date()} to {daily_df.index[-1].date()}",
        'n_trading_days': n_daily,
        'is_days': is_end,
        'oos_days': oos_n,
        'is_period': f"{daily_df.index[0].date()} to {daily_df.index[is_end-1].date()}",
        'oos_period': f"{daily_df.index[is_end].date()} to {daily_df.index[-1].date()}",
        'common_target': 'sigma2_fullday = r2_gap + RV_day + RV_night',
        'scaling_ratios': ratios,
        'model_results': model_results,
        'dm_tests': dm_all,
        'winner_qlike': winner,
        'har_standard_is_r2': float(r2_har_std),
        'har_dn_is_r2': har_dn_betas.get('R2') if har_dn_betas else None,
        'har_dn_asym_is_r2': har_dn_asym_betas.get('R2') if har_dn_asym_betas else None,
        'prg_params': {
            f'param_{i}': float(prg_params[i]) for i in range(len(prg_params))
        } if prg_params is not None else None,
        'descriptive_stats': {
            'is_mean_sigma2': float(daily_df['sigma2_fullday'].iloc[:is_end].mean()),
            'oos_mean_sigma2': float(daily_df['sigma2_fullday'].iloc[is_end:].mean()),
            'is_night_share': float(daily_df['rv_night'].fillna(0).iloc[:is_end].mean() /
                                    daily_df['sigma2_fullday'].iloc[:is_end].mean()),
            'oos_night_share': float(daily_df['rv_night'].fillna(0).iloc[is_end:].mean() /
                                     daily_df['sigma2_fullday'].iloc[is_end:].mean()),
        },
        'elapsed_seconds': elapsed,
        'references': [
            'Corsi (2009): HAR-RV model',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Lai et al. (2024): PRG with regime switching',
            'Hansen & Lunde (2005): Realized GARCH',
            'Patton (2011): QLIKE proxy-robust loss',
            'Harvey (2016): t > 3.0 threshold',
        ],
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
