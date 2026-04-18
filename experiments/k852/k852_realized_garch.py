#!/usr/bin/env python3
"""
K852: Realized GARCH — Combining GARCH Structure with 5-min RV Measurement
===========================================================================
[提出: 用戶, 執行: Claude]

Motivation (K849+K850 paradox):
  K849: HAR-RV crushes GJR on vol prediction (DM t=-11.14, QLIKE 66% better)
  K850: GJR+CF still wins on VaR (2/481 vs 17/450 violations)
  Paradox: Better vol prediction ≠ better VaR (residual tail structure matters)

  Realized GARCH may resolve this: use GARCH framework (good residual structure)
  + RV measurement (good prediction accuracy) → best of both worlds?

Models:
  1. GJR-GARCH (baseline): h_t = ω + (α + γI_{t-1<0}) r²_{t-1} + β h_{t-1}
  2. HAR-RV (K849 champion for prediction): RV_t = b0 + b1*RV_{t-1} + b2*RV_w + b3*RV_m
  3. RealGARCH-Simple: h_t = ω + (α + γI_{t-1<0}) RV_{t-1} + β h_{t-1}
     (Replace r² with RV in GJR equation — RV is better σ² proxy)
  4. RealGARCH-Log: log(h_t) = ω + β log(h_{t-1}) + δ log(RV_{t-1})
     (Log-linear version, Hansen et al. 2012 style)
  5. RealGARCH-CF: RealGARCH-Simple + Cornish-Fisher VaR
  6. RealGARCH-HistSim: RealGARCH-Simple + Historical Simulation VaR

Evaluation:
  Track 1 — Vol prediction: QLIKE on RV_total (Patton 2011 proxy-robust)
  Track 2 — VaR quality: 1% VaR Trinity (Kupiec + Christoffersen + Basel)
  Track 3 — DM test (Harvey t>3.0) for all model pairs
  Core question: Can Realized GARCH be best on BOTH tracks?

Data:
  - TAIFEX TX1 tick → 5-min RV (K849 pipeline, 2017/05-2025)
  - 0050.TW daily returns (clean_tw50_data mandatory)

OOS: 2023-01-01 ~ 2024-12-31 (same as K836/K850 for comparability)
IS:  2017-05 ~ 2022-12

Error Log rules applied:
  - 0050.TW: clean_tw50_data (volpred.utils)
  - GARCH OOS: recursive h[t]=f(h[t-1], RV[t-1]), NOT stale
  - DM test: Newey-West HAC
  - VaR: proper distribution conversion (σ × z_α)
  - Student-t: scale term sqrt((df-2)/df) if used

References:
  - Hansen, Huang & Shek (2012): Realized GARCH, J Applied Econometrics
  - Corsi (2009): HAR-RV model, J Financial Econometrics
  - Hansen & Lunde (2005): 5-min RV as gold standard
  - Patton (2011): QLIKE proxy-robust, J Econometrics
  - Cornish & Fisher (1938): CF expansion
  - K849: HAR-RV QLIKE=0.109 vs GJR=0.202 (DM t=-11.14)
  - K850: GJR+CF Trinity PASS (2 viol), HAR+HistSim (17 viol)

Author: VolPred Research System
Date: 2026-04-03
"""

import os
import sys
import glob
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats as sp_stats
from scipy.optimize import minimize
from scipy.stats import norm, skew, kurtosis, chi2
from numba import njit

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k852_realized_garch_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
MIN_TRAIN = 250

# TX session times (HHMMSS)
NIGHT_PM_START, NIGHT_PM_END = 150000, 235959
NIGHT_AM_START, NIGHT_AM_END = 0, 50000
DAY_START, DAY_END = 84500, 134500


# ============================================================
# A. Build 5-min RV from TAIFEX tick data (reused from K849/K850)
# ============================================================

def time_to_5min_bucket(time_int):
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def compute_rv_bpv(returns):
    if len(returns) < 1:
        return np.nan, np.nan
    rv = np.sum(returns ** 2)
    if len(returns) >= 2:
        bpv = (np.pi / 2) * np.sum(np.abs(returns[1:]) * np.abs(returns[:-1]))
    else:
        bpv = np.nan
    return float(rv), float(bpv)


def process_single_file(filepath):
    """Process one TX file -> compute 5-min RV for day and night sessions."""
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

    # Filter to near-month (most volume) for TX files
    if 'TX1' not in basename and 'TX2' not in basename:
        df['delivery'] = df.iloc[:, 2].astype(str).str.strip()
        vol_by_delivery = df.groupby('delivery')['volume'].sum()
        if len(vol_by_delivery) > 0:
            near_month = vol_by_delivery.idxmax()
            df = df[df['delivery'] == near_month]

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

    day_rets = build_5min_returns(t[day_mask], p[day_mask])
    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])

    if len(night_pm_rets) > 0 or len(night_am_rets) > 0:
        night_rets = np.concatenate([night_pm_rets, night_am_rets])
    else:
        night_rets = np.array([])

    rv_day, bpv_day = compute_rv_bpv(day_rets)
    rv_night, bpv_night = compute_rv_bpv(night_rets)

    if not np.isnan(rv_day) and not np.isnan(rv_night):
        rv_total = rv_day + rv_night
        bpv_total = (bpv_day if not np.isnan(bpv_day) else 0) + (bpv_night if not np.isnan(bpv_night) else 0)
    elif not np.isnan(rv_day):
        rv_total = rv_day
        bpv_total = bpv_day if not np.isnan(bpv_day) else np.nan
    else:
        rv_total = np.nan
        bpv_total = np.nan

    day_p_sorted = p[day_mask]
    if len(day_p_sorted) >= 2:
        day_return = np.log(float(day_p_sorted[-1]) / float(day_p_sorted[0]))
    else:
        day_return = np.nan

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'rv_total': rv_total if not np.isnan(rv_total) else None,
        'bpv_total': bpv_total if not np.isnan(bpv_total) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
    }


def load_all_rv_data(start_date=None):
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    if start_date:
        cutoff = f"Daily_{start_date.replace('-', '_')}"
        files = [f for f in all_files if os.path.basename(f) >= cutoff]
    else:
        files = all_files

    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {start_date or 'all'} to end 2025")

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
                if result is not None and result.get('rv_total') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)}, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df


# ============================================================
# B. GJR-GARCH (standard, using r²) — numba accelerated
# ============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """Standard GJR: h[t] = omega + (alpha + gamma*I) * r[t-1]² + beta * h[t-1]"""
    T = len(r)
    s2 = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    s2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


@njit(cache=True)
def real_garch_filter(r, rv, omega, alpha, beta, gamma):
    """
    Realized GARCH-Simple: h[t] = omega + (alpha + gamma*I) * RV[t-1] + beta * h[t-1]
    Uses RV instead of r² for variance updating.
    r: returns (for sign indicator only)
    rv: realized variance from 5-min data
    """
    T = len(r)
    s2 = np.empty(T)
    # Initialize with mean RV
    mean_rv = 0.0
    count = 0
    for i in range(T):
        if rv[i] > 0 and not np.isnan(rv[i]):
            mean_rv += rv[i]
            count += 1
    mean_rv = mean_rv / count if count > 0 else 1e-6
    s2[0] = mean_rv
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        rv_prev = rv[t - 1] if (rv[t - 1] > 0 and not np.isnan(rv[t - 1])) else s2[t - 1]
        s2[t] = omega + (alpha + gamma * ind) * rv_prev + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


def fit_gjr(returns, n_starts=4):
    """Fit standard GJR-GARCH via QMLE."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 100)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.98)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


def fit_real_garch_simple(returns, rv_arr, n_starts=4):
    """
    Fit Realized GARCH-Simple: h[t] = omega + (alpha + gamma*I) * RV[t-1] + beta * h[t-1]
    QMLE with RV replacing r² as the innovation proxy.
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = np.ascontiguousarray(rv_arr, dtype=np.float64)
    if len(r) < 100:
        return None
    mean_rv = np.nanmean(rv[rv > 0])

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = real_garch_filter(r, rv, omega, alpha, beta, gamma)
        # Gaussian QMLE: log-likelihood ∝ -0.5 Σ [log(h_t) + r_t²/h_t]
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 200)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.5)
        b0 = np.clip(0.85 + 0.05 * np.random.randn(), 0.3, 0.98)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.4)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = max(1e-8, mean_rv * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.8), (0, 0.999), (0, 0.8)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


def fit_real_garch_log(returns, rv_arr, n_starts=4):
    """
    Fit Realized GARCH-Log: log(h_t) = omega + beta * log(h_{t-1}) + delta * log(RV_{t-1})
    Hansen, Huang & Shek (2012) style log-linear specification.
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = np.ascontiguousarray(rv_arr, dtype=np.float64)
    if len(r) < 100:
        return None

    # Replace invalid RV with running mean
    rv_clean = rv.copy()
    running_mean = np.nanmean(rv[rv > 0])
    for i in range(len(rv_clean)):
        if rv_clean[i] <= 0 or np.isnan(rv_clean[i]):
            rv_clean[i] = running_mean

    log_rv = np.log(rv_clean)

    def negll(params):
        omega, beta, delta = params
        if beta < -0.999 or beta > 0.999 or delta < 0 or delta > 2.0:
            return 1e10
        T = len(r)
        log_h = np.empty(T)
        log_h[0] = omega / (1 - beta) + delta / (1 - beta) * np.mean(log_rv[:min(22, T)])
        for t in range(1, T):
            log_h[t] = omega + beta * log_h[t - 1] + delta * log_rv[t - 1]
        h = np.exp(log_h)
        h = np.maximum(h, 1e-16)
        ll = -0.5 * np.sum(log_h[1:] + r[1:] ** 2 / h[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 300)
        omega0 = -0.1 + 0.05 * np.random.randn()
        beta0 = np.clip(0.6 + 0.1 * np.random.randn(), 0.1, 0.95)
        delta0 = np.clip(0.3 + 0.1 * np.random.randn(), 0.05, 0.9)
        res = minimize(negll, [omega0, beta0, delta0],
                       method='L-BFGS-B',
                       bounds=[(-5, 5), (-0.999, 0.999), (0.001, 2.0)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, beta, delta = best.x
    return {'omega': float(omega), 'beta': float(beta),
            'delta': float(delta),
            'persistence': float(beta)}


def compute_std_residuals_gjr(returns, params):
    """GJR standardized residuals: z_t = r_t / sqrt(h_t)"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]


def compute_std_residuals_real_simple(returns, rv_arr, params):
    """RealGARCH-Simple standardized residuals: z_t = r_t / sqrt(h_t)"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = np.ascontiguousarray(rv_arr, dtype=np.float64)
    s2 = real_garch_filter(r, rv, params['omega'], params['alpha'],
                           params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]


def compute_std_residuals_real_log(returns, rv_arr, params):
    """RealGARCH-Log standardized residuals: z_t = r_t / sqrt(h_t)"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv_clean = rv_arr.copy()
    running_mean = np.nanmean(rv_clean[rv_clean > 0])
    for i in range(len(rv_clean)):
        if rv_clean[i] <= 0 or np.isnan(rv_clean[i]):
            rv_clean[i] = running_mean
    log_rv = np.log(rv_clean)

    T = len(r)
    log_h = np.empty(T)
    log_h[0] = params['omega'] / (1 - params['beta']) + params['delta'] / (1 - params['beta']) * np.mean(log_rv[:min(22, T)])
    for t in range(1, T):
        log_h[t] = params['omega'] + params['beta'] * log_h[t - 1] + params['delta'] * log_rv[t - 1]
    h = np.exp(log_h)
    h = np.maximum(h, 1e-16)
    sigma = np.sqrt(h)
    z = r / sigma
    return z[1:]


# ============================================================
# C. HAR-RV OOS forecasts (reused from K849/K850)
# ============================================================

def fit_har_ols(y, X):
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


def har_oos_forecasts(rv_series, oos_start, refit_freq=63, min_train=250):
    rv = rv_series.values.copy()
    dates = rv_series.index
    n = len(rv)

    oos_idx = np.searchsorted(dates, pd.Timestamp(oos_start))
    if oos_idx < min_train:
        oos_idx = min_train

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq

    for t in range(oos_idx, n):
        if t - last_fit_idx >= refit_freq or last_beta is None:
            train_rv = rv[:t]
            if len(train_rv) < min_train:
                continue

            nn = len(train_rv)
            rv_d = np.full(nn, np.nan)
            rv_w = np.full(nn, np.nan)
            rv_m = np.full(nn, np.nan)
            for i in range(1, nn):
                rv_d[i] = train_rv[i - 1]
            for i in range(5, nn):
                rv_w[i] = np.mean(train_rv[i - 5:i])
            for i in range(22, nn):
                rv_m[i] = np.mean(train_rv[i - 22:i])

            feat = np.column_stack([rv_d, rv_w, rv_m])
            valid_mask = ~np.any(np.isnan(feat), axis=1) & ~np.isnan(train_rv)
            if np.sum(valid_mask) < 50:
                continue

            y_train = train_rv[valid_mask]
            X_train = feat[valid_mask]

            beta, y_hat, r2 = fit_har_ols(y_train, X_train)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        rv_d_t = rv[t - 1]
        rv_w_t = np.mean(rv[max(0, t - 5):t]) if t >= 5 else np.nan
        rv_m_t = np.mean(rv[max(0, t - 22):t]) if t >= 22 else np.nan

        if np.isnan(rv_d_t) or np.isnan(rv_w_t) or np.isnan(rv_m_t):
            continue

        x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t])
        forecast = x_t @ last_beta
        forecasts[t] = max(forecast, 1e-10)

    return pd.Series(forecasts, index=dates, name='HAR-RV')


# ============================================================
# D. Cornish-Fisher quantile
# ============================================================

def cornish_fisher_quantile(std_residuals, alpha):
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    S = float(skew(z))
    K = float(kurtosis(z, fisher=True))
    z_alpha = norm.ppf(alpha)
    z_cf = (z_alpha
            + (z_alpha ** 2 - 1) * S / 6.0
            + (z_alpha ** 3 - 3.0 * z_alpha) * K / 24.0
            - (2.0 * z_alpha ** 3 - 5.0 * z_alpha) * S ** 2 / 36.0)
    return float(z_cf)


# ============================================================
# E. VaR Backtest: Kupiec + Christoffersen + Basel
# ============================================================

def basel_traffic_light_250(violations_array, n_lookback=250, alpha_var=0.01):
    v = np.asarray(violations_array, dtype=int)
    n = len(v)
    window = min(n, n_lookback)
    v_window = v[-window:]
    n_viol = int(v_window.sum())

    alpha_scale = alpha_var / 0.01
    if window >= 250:
        green_max = int(np.floor(4 * alpha_scale))
        yellow_max = int(np.floor(9 * alpha_scale))
    else:
        green_max = int(np.floor(window * 4.0 * alpha_scale / 250.0))
        yellow_max = int(np.floor(window * 9.0 * alpha_scale / 250.0))

    green_max = max(green_max, 0)
    yellow_max = max(yellow_max, max(green_max + 1, 1))

    if n_viol <= green_max:
        color = 'green'
    elif n_viol <= yellow_max:
        color = 'yellow'
    else:
        color = 'red'
    return color, n_viol, window


def var_backtest(returns, var_series, alpha_var=0.01):
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen
    try:
        t00 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 0)))
        t01 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 1)))
        t10 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 0)))
        t11 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 1)))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all)
                           + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    traffic, n_viol_window, window_size = basel_traffic_light_250(violations, alpha_var=alpha_var)

    return {
        'violation_rate': round(float(pi_hat), 6),
        'expected_rate': float(alpha_var),
        'n_violations': int(n1),
        'n_total': int(n),
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': traffic,
        'basel_violations_in_window': int(n_viol_window),
        'basel_window_size': int(window_size),
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ============================================================
# F. QLIKE and DM test
# ============================================================

def qlike(target, forecast):
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f) & (t > 0) & (f > 0)
    t, f = t[valid], f[valid]
    if len(t) < 10:
        return np.nan
    ratio = t / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_series(target, forecast):
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
    max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
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
# G. JSON serialization helper
# ============================================================

def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ============================================================
# H. Main Experiment
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K852: Realized GARCH — GARCH Structure + 5-min RV Measurement")
    print("  Core question: Can Realized GARCH be best on BOTH vol prediction AND VaR?")
    print(f"  Models: GJR, HAR-RV, RealGARCH-Simple, RealGARCH-Log")
    print(f"  VaR methods: +Normal, +CF, +HistSim for each model")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print(f"  Refit: every {REFIT_EVERY} trading days")
    print("=" * 70)

    # -------------------------------------------------------
    # 1. Load TAIFEX TX 5-min RV
    # -------------------------------------------------------
    print("\n[1] Loading TAIFEX TX1 tick data -> 5-min RV...")
    rv_df = load_all_rv_data(start_date='2017-01-01')
    print(f"  RV data: {len(rv_df)} days ({rv_df.index[0].date()} ~ {rv_df.index[-1].date()})")

    rv_total = rv_df['rv_total'].dropna()
    print(f"  RV_total: mean={rv_total.mean():.2e}, std={rv_total.std():.2e}, "
          f"median={rv_total.median():.2e}")
    ann_vol = np.sqrt(rv_total.mean() * 252) * 100
    print(f"  Annualized vol (from mean RV): {ann_vol:.1f}%")

    # -------------------------------------------------------
    # 2. Load 0050.TW returns (mandatory: clean_tw50_data)
    # -------------------------------------------------------
    print("\n[2] Loading 0050.TW returns...")
    import yfinance as yf
    raw = yf.download('0050.TW', start='2016-01-01', end='2026-01-01', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    close_series = raw['Close'].squeeze()
    clean_prices, clean_returns = clean_tw50_data(close_series)
    etf_returns = clean_returns.dropna()
    etf_returns.index = pd.to_datetime(etf_returns.index).tz_localize(None)
    print(f"  0050.TW returns: {len(etf_returns)} days")

    # -------------------------------------------------------
    # 3. Align dates
    # -------------------------------------------------------
    common_dates = rv_total.index.intersection(etf_returns.index)
    common_dates = common_dates.sort_values()
    print(f"\n[3] Common dates (RV ∩ ETF returns): {len(common_dates)}")

    rv_aligned = rv_total.loc[common_dates]
    ret_aligned = etf_returns.loc[common_dates]

    # OOS subset
    oos_mask = (common_dates >= OOS_START) & (common_dates <= OOS_END)
    n_oos = int(oos_mask.sum())
    oos_dates = common_dates[oos_mask]
    print(f"  OOS: {n_oos} days ({oos_dates[0].date()} ~ {oos_dates[-1].date()})")

    # OOS descriptive stats
    oos_ret = ret_aligned.loc[oos_dates].values
    oos_stats = {
        'mean': float(np.mean(oos_ret)),
        'std': float(np.std(oos_ret)),
        'skewness': float(skew(oos_ret)),
        'kurtosis': float(kurtosis(oos_ret, fisher=True)),
        'min': float(np.min(oos_ret)),
        'max': float(np.max(oos_ret)),
        'n_oos': n_oos,
    }
    print(f"  OOS stats: mean={oos_stats['mean']:.6f}, std={oos_stats['std']:.4f}, "
          f"skew={oos_stats['skewness']:.3f}, kurt={oos_stats['kurtosis']:.2f}")

    # -------------------------------------------------------
    # 4. Run all OOS forecasts
    # -------------------------------------------------------
    all_returns_arr = ret_aligned.values
    all_rv_arr = rv_aligned.values
    all_dates_arr = common_dates

    oos_start_idx = int(np.searchsorted(all_dates_arr, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(all_dates_arr, pd.Timestamp(OOS_END), side='right'))

    # --- 4a. HAR-RV forecasts ---
    print("\n[4a] Running HAR-RV OOS forecasts (expanding window)...")
    har_forecasts = har_oos_forecasts(
        rv_aligned, oos_start=OOS_START, refit_freq=REFIT_EVERY, min_train=MIN_TRAIN
    )
    har_oos = har_forecasts.loc[oos_dates]
    har_valid = har_oos.dropna()
    print(f"  HAR valid forecasts in OOS: {len(har_valid)}/{n_oos}")

    # --- 4b. GJR-GARCH forecasts ---
    print("\n[4b] Running GJR-GARCH OOS forecasts (recursive)...")
    gjr_forecasts = np.full(len(common_dates), np.nan)
    gjr_std_residuals_dict = {}
    current_gjr_params = None
    last_gjr_refit = -REFIT_EVERY
    n_gjr_refits = 0

    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        if day_idx - last_gjr_refit >= REFIT_EVERY or current_gjr_params is None:
            train_r = all_returns_arr[:i]
            if len(train_r) < 500:
                continue
            params = fit_gjr(train_r)
            if params is not None:
                current_gjr_params = params
                z = compute_std_residuals_gjr(train_r, params)
                gjr_std_residuals_dict[i] = z
                n_gjr_refits += 1
                last_gjr_refit = day_idx
                if n_gjr_refits <= 2:
                    print(f"    GJR refit @day {day_idx}: pers={params['persistence']:.4f}")

        if current_gjr_params is None:
            continue

        # Recursive one-step: h[t] = omega + (alpha + gamma*I) * r²[t-1] + beta * h[t-1]
        train_r_arr = all_returns_arr[:i]
        s2 = gjr_filter(np.ascontiguousarray(train_r_arr, dtype=np.float64),
                        current_gjr_params['omega'], current_gjr_params['alpha'],
                        current_gjr_params['beta'], current_gjr_params['gamma'])
        ind = 1.0 if train_r_arr[-1] < 0 else 0.0
        h_t = (current_gjr_params['omega']
               + (current_gjr_params['alpha'] + current_gjr_params['gamma'] * ind) * train_r_arr[-1] ** 2
               + current_gjr_params['beta'] * s2[-1])
        gjr_forecasts[i] = max(h_t, 1e-12)

    gjr_forecasts_series = pd.Series(gjr_forecasts, index=common_dates, name='GJR')
    gjr_oos = gjr_forecasts_series.loc[oos_dates]
    gjr_valid = gjr_oos.dropna()
    print(f"  GJR refits: {n_gjr_refits}, valid OOS: {len(gjr_valid)}/{n_oos}")

    # --- 4c. RealGARCH-Simple forecasts ---
    print("\n[4c] Running RealGARCH-Simple OOS forecasts (recursive)...")
    rgarch_simple_forecasts = np.full(len(common_dates), np.nan)
    rgarch_simple_resid_dict = {}
    current_rgs_params = None
    last_rgs_refit = -REFIT_EVERY
    n_rgs_refits = 0

    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        if day_idx - last_rgs_refit >= REFIT_EVERY or current_rgs_params is None:
            train_r = all_returns_arr[:i]
            train_rv = all_rv_arr[:i]
            if len(train_r) < 500:
                continue
            params = fit_real_garch_simple(train_r, train_rv)
            if params is not None:
                current_rgs_params = params
                z = compute_std_residuals_real_simple(train_r, train_rv, params)
                rgarch_simple_resid_dict[i] = z
                n_rgs_refits += 1
                last_rgs_refit = day_idx
                if n_rgs_refits <= 2:
                    print(f"    RealGARCH-Simple refit @day {day_idx}: pers={params['persistence']:.4f}")

        if current_rgs_params is None:
            continue

        # Recursive: h[t] = omega + (alpha + gamma*I) * RV[t-1] + beta * h[t-1]
        train_r_arr = all_returns_arr[:i]
        train_rv_arr = all_rv_arr[:i]
        s2 = real_garch_filter(
            np.ascontiguousarray(train_r_arr, dtype=np.float64),
            np.ascontiguousarray(train_rv_arr, dtype=np.float64),
            current_rgs_params['omega'], current_rgs_params['alpha'],
            current_rgs_params['beta'], current_rgs_params['gamma']
        )
        ind = 1.0 if train_r_arr[-1] < 0 else 0.0
        rv_prev = train_rv_arr[-1] if (train_rv_arr[-1] > 0 and not np.isnan(train_rv_arr[-1])) else s2[-1]
        h_t = (current_rgs_params['omega']
               + (current_rgs_params['alpha'] + current_rgs_params['gamma'] * ind) * rv_prev
               + current_rgs_params['beta'] * s2[-1])
        rgarch_simple_forecasts[i] = max(h_t, 1e-12)

    rgarch_simple_series = pd.Series(rgarch_simple_forecasts, index=common_dates, name='RealGARCH-Simple')
    rgs_oos = rgarch_simple_series.loc[oos_dates]
    rgs_valid = rgs_oos.dropna()
    print(f"  RealGARCH-Simple refits: {n_rgs_refits}, valid OOS: {len(rgs_valid)}/{n_oos}")

    # --- 4d. RealGARCH-Log forecasts ---
    print("\n[4d] Running RealGARCH-Log OOS forecasts (recursive)...")
    rgarch_log_forecasts = np.full(len(common_dates), np.nan)
    rgarch_log_resid_dict = {}
    current_rgl_params = None
    last_rgl_refit = -REFIT_EVERY
    n_rgl_refits = 0

    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        if day_idx - last_rgl_refit >= REFIT_EVERY or current_rgl_params is None:
            train_r = all_returns_arr[:i]
            train_rv = all_rv_arr[:i]
            if len(train_r) < 500:
                continue
            params = fit_real_garch_log(train_r, train_rv)
            if params is not None:
                current_rgl_params = params
                z = compute_std_residuals_real_log(train_r, train_rv, params)
                rgarch_log_resid_dict[i] = z
                n_rgl_refits += 1
                last_rgl_refit = day_idx
                if n_rgl_refits <= 2:
                    print(f"    RealGARCH-Log refit @day {day_idx}: beta={params['beta']:.4f}, delta={params['delta']:.4f}")

        if current_rgl_params is None:
            continue

        # Recursive log-linear: log(h_t) = omega + beta * log(h_{t-1}) + delta * log(RV_{t-1})
        train_r_arr = all_returns_arr[:i]
        train_rv_arr = all_rv_arr[:i]
        rv_clean = train_rv_arr.copy()
        running_mean = np.nanmean(rv_clean[rv_clean > 0])
        for k in range(len(rv_clean)):
            if rv_clean[k] <= 0 or np.isnan(rv_clean[k]):
                rv_clean[k] = running_mean
        log_rv = np.log(rv_clean)

        T = len(train_r_arr)
        log_h = np.empty(T)
        log_h[0] = current_rgl_params['omega'] / (1 - current_rgl_params['beta']) + \
                    current_rgl_params['delta'] / (1 - current_rgl_params['beta']) * np.mean(log_rv[:min(22, T)])
        for t_idx in range(1, T):
            log_h[t_idx] = current_rgl_params['omega'] + current_rgl_params['beta'] * log_h[t_idx - 1] + \
                           current_rgl_params['delta'] * log_rv[t_idx - 1]

        # One-step-ahead forecast: use last h and last RV
        h_last = np.exp(log_h[-1])
        rv_last = rv_clean[-1]
        log_h_next = current_rgl_params['omega'] + current_rgl_params['beta'] * log_h[-1] + \
                     current_rgl_params['delta'] * np.log(rv_last)
        rgarch_log_forecasts[i] = max(np.exp(log_h_next), 1e-12)

    rgarch_log_series = pd.Series(rgarch_log_forecasts, index=common_dates, name='RealGARCH-Log')
    rgl_oos = rgarch_log_series.loc[oos_dates]
    rgl_valid = rgl_oos.dropna()
    print(f"  RealGARCH-Log refits: {n_rgl_refits}, valid OOS: {len(rgl_valid)}/{n_oos}")

    # -------------------------------------------------------
    # 5. QLIKE on RV_total (vol prediction track)
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("TRACK 1: Volatility Prediction (QLIKE on RV_total)")
    print(f"{'='*70}")

    rv_oos_vals = rv_aligned.loc[oos_dates].values
    qlike_results = {}

    model_forecast_map = {
        'GJR-GARCH': gjr_oos.values,
        'HAR-RV': har_oos.values,
        'RealGARCH-Simple': rgs_oos.values,
        'RealGARCH-Log': rgl_oos.values,
    }

    for model_name, forecast_vals in model_forecast_map.items():
        valid = np.isfinite(forecast_vals) & np.isfinite(rv_oos_vals) & (rv_oos_vals > 0) & (forecast_vals > 0)
        if valid.sum() > 10:
            ql = qlike(rv_oos_vals[valid], forecast_vals[valid])
            qlike_results[model_name] = ql
            print(f"  {model_name:20s} QLIKE = {ql:.6f}  (n={valid.sum()})")
        else:
            print(f"  {model_name:20s} SKIP (insufficient data)")

    # DM tests between all pairs
    print(f"\n  DM test matrix (QLIKE loss, Harvey t>3.0):")
    model_names = list(model_forecast_map.keys())
    dm_results = {}

    for i_m in range(len(model_names)):
        for j_m in range(i_m + 1, len(model_names)):
            m1, m2 = model_names[i_m], model_names[j_m]
            f1 = model_forecast_map[m1]
            f2 = model_forecast_map[m2]
            valid = (np.isfinite(f1) & np.isfinite(f2) &
                     np.isfinite(rv_oos_vals) & (rv_oos_vals > 0) & (f1 > 0) & (f2 > 0))
            if valid.sum() < 20:
                continue
            loss1 = qlike_loss_series(rv_oos_vals[valid], f1[valid])
            loss2 = qlike_loss_series(rv_oos_vals[valid], f2[valid])
            t_stat, p_val = dm_test(loss1, loss2)
            sig = abs(t_stat) > 3.0
            interp = f'{m1} better' if t_stat < -3.0 else (f'{m2} better' if t_stat > 3.0 else 'no sig diff')
            dm_key = f'{m1}_vs_{m2}'
            dm_results[dm_key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'significant': bool(sig),
                'interpretation': interp,
            }
            sig_mark = "***" if sig else ""
            print(f"    {m1} vs {m2}: t={t_stat:+.4f}  {sig_mark}  ({interp})")

    # Spearman rank correlations
    print(f"\n  Spearman rank correlation with RV_total:")
    spearman_results = {}
    for model_name, forecast_vals in model_forecast_map.items():
        valid = np.isfinite(forecast_vals) & np.isfinite(rv_oos_vals) & (rv_oos_vals > 0) & (forecast_vals > 0)
        if valid.sum() > 10:
            rho, pval = sp_stats.spearmanr(rv_oos_vals[valid], forecast_vals[valid])
            spearman_results[model_name] = {'rho': round(float(rho), 4), 'p_value': round(float(pval), 6)}
            print(f"    {model_name:20s}: rho={rho:.4f}, p={pval:.2e}")

    # -------------------------------------------------------
    # 6. VaR computation for all model x quantile combinations
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("TRACK 2: VaR Quality (1% and 5% Trinity Test)")
    print(f"{'='*70}")

    # Model abbreviations for VaR methods
    # For each "sigma model" we test Normal, CF, HistSim VaR approaches
    sigma_models = {
        'GJR': {
            'forecasts': gjr_forecasts,
            'series': gjr_forecasts_series,
            'resid_dict': gjr_std_residuals_dict,
            'resid_getter': lambda idx, d: d.get(max([k for k in d.keys() if k <= idx], default=-1), None),
        },
        'RGS': {
            'forecasts': rgarch_simple_forecasts,
            'series': rgarch_simple_series,
            'resid_dict': rgarch_simple_resid_dict,
            'resid_getter': lambda idx, d: d.get(max([k for k in d.keys() if k <= idx], default=-1), None),
        },
        'RGL': {
            'forecasts': rgarch_log_forecasts,
            'series': rgarch_log_series,
            'resid_dict': rgarch_log_resid_dict,
            'resid_getter': lambda idx, d: d.get(max([k for k in d.keys() if k <= idx], default=-1), None),
        },
    }

    # For HAR, residuals are return-based: z_t = r_t / sqrt(HAR_forecast_t)
    # We compute them on the fly using expanding window

    var_method_keys = []
    for sm in ['GJR', 'RGS', 'RGL']:
        for vt in ['Normal', 'CF', 'HistSim']:
            var_method_keys.append(f'{sm}+{vt}')
    for vt in ['Normal', 'CF', 'HistSim']:
        var_method_keys.append(f'HAR+{vt}')

    var_forecasts_all = {alpha: {m: np.full(n_oos, np.nan) for m in var_method_keys}
                         for alpha in ALPHA_LEVELS}

    # Pre-sort refit indices for each model
    for sm_key in sigma_models:
        sigma_models[sm_key]['refit_sorted'] = sorted(sigma_models[sm_key]['resid_dict'].keys())

    # Track last residuals for each model
    last_resid = {sm: None for sm in sigma_models}
    last_har_return_z = None
    last_har_refit_oos_idx = -REFIT_EVERY

    print("\n  Computing VaR for all methods across OOS...")
    for i_oos, date in enumerate(oos_dates):
        global_idx = np.searchsorted(common_dates, date)

        # Update residuals for GARCH-family models
        for sm_key, sm_info in sigma_models.items():
            for refit_idx in sm_info['refit_sorted']:
                if refit_idx <= global_idx:
                    last_resid[sm_key] = sm_info['resid_dict'][refit_idx]

        # Update HAR return-space residuals
        if i_oos - last_har_refit_oos_idx >= REFIT_EVERY or last_har_return_z is None:
            z_list = []
            for idx in range(global_idx):
                dd = common_dates[idx]
                r_val = ret_aligned.get(dd, np.nan)
                h_val = har_forecasts.get(dd, np.nan)
                if np.isfinite(r_val) and np.isfinite(h_val) and h_val > 0:
                    z_list.append(r_val / np.sqrt(h_val))
            if len(z_list) > 30:
                last_har_return_z = np.array(z_list)
                last_har_refit_oos_idx = i_oos

        # Compute VaR for each model x quantile method
        for alpha in ALPHA_LEVELS:
            z_normal = norm.ppf(alpha)

            # GARCH-family models (GJR, RGS, RGL)
            for sm_key in sigma_models:
                sigma2_f = sigma_models[sm_key]['forecasts'][global_idx] if global_idx < len(sigma_models[sm_key]['forecasts']) else np.nan
                if np.isnan(sigma2_f):
                    continue
                sigma_f = np.sqrt(sigma2_f)
                z_arr = last_resid[sm_key]

                # Normal
                var_forecasts_all[alpha][f'{sm_key}+Normal'][i_oos] = sigma_f * z_normal

                # CF and HistSim need residuals
                if z_arr is not None and len(z_arr) > 30:
                    z_cf = cornish_fisher_quantile(z_arr, alpha)
                    var_forecasts_all[alpha][f'{sm_key}+CF'][i_oos] = sigma_f * z_cf

                    z_hist = np.percentile(z_arr, alpha * 100)
                    var_forecasts_all[alpha][f'{sm_key}+HistSim'][i_oos] = sigma_f * z_hist

            # HAR-RV model
            har_rv_f = har_forecasts.iloc[global_idx] if global_idx < len(har_forecasts) else np.nan
            if not np.isnan(har_rv_f):
                har_sigma = np.sqrt(har_rv_f)
                var_forecasts_all[alpha][f'HAR+Normal'][i_oos] = har_sigma * z_normal

                if last_har_return_z is not None and len(last_har_return_z) > 30:
                    z_cf_har = cornish_fisher_quantile(last_har_return_z, alpha)
                    var_forecasts_all[alpha][f'HAR+CF'][i_oos] = har_sigma * z_cf_har

                    z_hist_har = np.percentile(last_har_return_z, alpha * 100)
                    var_forecasts_all[alpha][f'HAR+HistSim'][i_oos] = har_sigma * z_hist_har

    # -------------------------------------------------------
    # 7. Backtest all methods
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("VaR BACKTEST RESULTS")
    print(f"{'='*70}")

    var_results = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f"{int(alpha*100)}%"
        var_results[alpha_key] = {}
        print(f"\n  --- {alpha_key} VaR ---")
        print(f"  {'Method':20s} {'Viol':>5s} {'Rate':>7s} {'Basel':>7s} {'Kupiec':>8s} {'Christ':>8s} {'Trinity':>8s}")
        print(f"  {'-'*20} {'-'*5} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

        for method_key in var_method_keys:
            var_arr = var_forecasts_all[alpha][method_key]
            valid = np.isfinite(var_arr)

            if valid.sum() < 50:
                var_results[alpha_key][method_key] = {'error': 'insufficient forecasts',
                                                       'n_valid': int(valid.sum())}
                continue

            bt = var_backtest(oos_ret[valid], var_arr[valid], alpha_var=alpha)
            var_results[alpha_key][method_key] = bt

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"  {method_key:20s} {bt['n_violations']:5d} "
                  f"{bt['violation_rate']:7.4f} {bt['basel_traffic_light']:>7s} "
                  f"p={bt['kupiec']['p_value']:.3f}  "
                  f"p={bt['christoffersen']['p_value']:.3f}  "
                  f"{status:>8s}")

    # -------------------------------------------------------
    # 8. Summary table: 1% VaR
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("SUMMARY: 1% VaR Ranking")
    print(f"{'='*70}")

    if '1%' in var_results:
        trinity_pass_methods = []
        all_1pct = []
        for mk in var_method_keys:
            if mk in var_results['1%'] and 'error' not in var_results['1%'][mk]:
                bt = var_results['1%'][mk]
                all_1pct.append((mk, bt['n_violations'], bt['trinity_pass']))
                if bt['trinity_pass']:
                    trinity_pass_methods.append((mk, bt['n_violations']))

        all_1pct.sort(key=lambda x: (not x[2], x[1]))  # Trinity pass first, then by violations
        print(f"  {'Rank':>4s}  {'Method':20s} {'Viol':>5s} {'Trinity':>8s}")
        print(f"  {'-'*4}  {'-'*20} {'-'*5} {'-'*8}")
        for rank, (mk, viol, tp) in enumerate(all_1pct, 1):
            status = "PASS" if tp else "FAIL"
            print(f"  {rank:4d}  {mk:20s} {viol:5d} {status:>8s}")

    # -------------------------------------------------------
    # 9. Core question answer
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("CORE QUESTION: Can Realized GARCH be best on BOTH tracks?")
    print(f"{'='*70}")

    conclusions = []

    # Track 1: Best QLIKE
    if qlike_results:
        best_qlike_model = min(qlike_results, key=qlike_results.get)
        best_qlike_val = qlike_results[best_qlike_model]
        conclusions.append(f"Track 1 (Vol Prediction): {best_qlike_model} has best QLIKE={best_qlike_val:.6f}")
        print(f"  Vol prediction champion: {best_qlike_model} (QLIKE={best_qlike_val:.6f})")

        # Check if RealGARCH beats both GJR and HAR
        rgs_ql = qlike_results.get('RealGARCH-Simple', np.inf)
        rgl_ql = qlike_results.get('RealGARCH-Log', np.inf)
        gjr_ql = qlike_results.get('GJR-GARCH', np.inf)
        har_ql = qlike_results.get('HAR-RV', np.inf)
        best_rg = min(rgs_ql, rgl_ql)
        rg_beats_gjr = best_rg < gjr_ql
        rg_beats_har = best_rg < har_ql
        conclusions.append(f"RealGARCH beats GJR on QLIKE: {rg_beats_gjr}")
        conclusions.append(f"RealGARCH beats HAR on QLIKE: {rg_beats_har}")
        print(f"  RealGARCH vs GJR (QLIKE): {'YES' if rg_beats_gjr else 'NO'}")
        print(f"  RealGARCH vs HAR (QLIKE): {'YES' if rg_beats_har else 'NO'}")

    # Track 2: Best VaR
    if '1%' in var_results:
        trinity_methods = [mk for mk in var_method_keys
                          if mk in var_results['1%']
                          and 'error' not in var_results['1%'][mk]
                          and var_results['1%'][mk].get('trinity_pass', False)]
        if trinity_methods:
            best_var = min(trinity_methods, key=lambda mk: var_results['1%'][mk]['n_violations'])
            viol = var_results['1%'][best_var]['n_violations']
            conclusions.append(f"Track 2 (1% VaR Trinity PASS): {best_var} ({viol} violations)")
            print(f"  1% VaR champion: {best_var} ({viol} violations)")

            rg_pass = any(mk.startswith('RG') for mk in trinity_methods)
            conclusions.append(f"Any RealGARCH passes 1% VaR Trinity: {rg_pass}")
            print(f"  Any RealGARCH passes Trinity: {'YES' if rg_pass else 'NO'}")
        else:
            conclusions.append("Track 2: NO method passes 1% VaR Trinity")
            print(f"  1% VaR: NO method passes Trinity")

            # Best among non-passing
            all_viol = [(mk, var_results['1%'][mk]['n_violations'])
                       for mk in var_method_keys
                       if mk in var_results['1%'] and 'error' not in var_results['1%'][mk]]
            if all_viol:
                best_near = min(all_viol, key=lambda x: x[1])
                conclusions.append(f"Closest to pass: {best_near[0]} ({best_near[1]} violations)")
                print(f"  Closest to pass: {best_near[0]} ({best_near[1]} violations)")

    # K849/K850 paradox resolution check
    conclusions.append("---")
    conclusions.append("K849+K850 Paradox Resolution Assessment:")
    rg_best_both = False
    if qlike_results and '1%' in var_results:
        # Check if any RealGARCH variant is top-3 on BOTH tracks
        qlike_ranking = sorted(qlike_results.items(), key=lambda x: x[1])
        top3_qlike = [x[0] for x in qlike_ranking[:3]]

        trinity_methods_set = set(trinity_methods) if 'trinity_methods' in dir() else set()
        all_viol_sorted = sorted(
            [(mk, var_results['1%'][mk].get('n_violations', 999))
             for mk in var_method_keys
             if mk in var_results['1%'] and 'error' not in var_results['1%'][mk]],
            key=lambda x: x[1]
        )
        top3_var = [x[0] for x in all_viol_sorted[:3]]

        # Map model names to VaR method prefix
        # e.g., 'RealGARCH-Simple' -> 'RGS+...'
        for rg_name in ['RealGARCH-Simple', 'RealGARCH-Log']:
            prefix = 'RGS' if 'Simple' in rg_name else 'RGL'
            in_top3_qlike = rg_name in top3_qlike
            in_top3_var = any(mk.startswith(prefix) for mk in top3_var)
            if in_top3_qlike and in_top3_var:
                rg_best_both = True
                conclusions.append(f"{rg_name}: Top-3 on BOTH vol prediction AND VaR")
                print(f"  {rg_name}: Top-3 on BOTH tracks!")

    if not rg_best_both:
        conclusions.append("RealGARCH does NOT resolve the K849+K850 paradox (not top-3 on both)")
        print(f"  RealGARCH does NOT resolve the paradox")

    # -------------------------------------------------------
    # 10. Model parameter summary
    # -------------------------------------------------------
    model_params = {}
    # Get last-fitted params
    if current_gjr_params:
        model_params['GJR-GARCH'] = current_gjr_params
    if current_rgs_params:
        model_params['RealGARCH-Simple'] = current_rgs_params
    if current_rgl_params:
        model_params['RealGARCH-Log'] = current_rgl_params

    print(f"\n{'='*70}")
    print("Model Parameters (last refit)")
    print(f"{'='*70}")
    for mname, mparams in model_params.items():
        print(f"  {mname}: {mparams}")

    # -------------------------------------------------------
    # 11. Residual diagnostics
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("Residual Diagnostics (standardized residuals from last refit)")
    print(f"{'='*70}")

    resid_diagnostics = {}
    resid_sources = {
        'GJR-GARCH': max(gjr_std_residuals_dict.keys(), default=None),
        'RealGARCH-Simple': max(rgarch_simple_resid_dict.keys(), default=None),
        'RealGARCH-Log': max(rgarch_log_resid_dict.keys(), default=None),
    }

    for mname, refit_key in resid_sources.items():
        if refit_key is None:
            continue
        if mname == 'GJR-GARCH':
            z = gjr_std_residuals_dict[refit_key]
        elif mname == 'RealGARCH-Simple':
            z = rgarch_simple_resid_dict[refit_key]
        else:
            z = rgarch_log_resid_dict[refit_key]

        z_clean = z[np.isfinite(z)]
        if len(z_clean) < 30:
            continue

        diag = {
            'n': len(z_clean),
            'mean': round(float(np.mean(z_clean)), 4),
            'std': round(float(np.std(z_clean)), 4),
            'skewness': round(float(skew(z_clean)), 4),
            'kurtosis': round(float(kurtosis(z_clean, fisher=True)), 4),
            'min': round(float(np.min(z_clean)), 4),
            'max': round(float(np.max(z_clean)), 4),
            'pct_1': round(float(np.percentile(z_clean, 1)), 4),
            'pct_5': round(float(np.percentile(z_clean, 5)), 4),
        }
        resid_diagnostics[mname] = diag
        print(f"  {mname}: mean={diag['mean']}, std={diag['std']}, "
              f"skew={diag['skewness']}, kurt={diag['kurtosis']}, "
              f"1st pct={diag['pct_1']}, 5th pct={diag['pct_5']}")

    # Also do HAR return-space residuals
    if last_har_return_z is not None and len(last_har_return_z) > 30:
        z_clean = last_har_return_z[np.isfinite(last_har_return_z)]
        diag = {
            'n': len(z_clean),
            'mean': round(float(np.mean(z_clean)), 4),
            'std': round(float(np.std(z_clean)), 4),
            'skewness': round(float(skew(z_clean)), 4),
            'kurtosis': round(float(kurtosis(z_clean, fisher=True)), 4),
            'min': round(float(np.min(z_clean)), 4),
            'max': round(float(np.max(z_clean)), 4),
            'pct_1': round(float(np.percentile(z_clean, 1)), 4),
            'pct_5': round(float(np.percentile(z_clean, 5)), 4),
        }
        resid_diagnostics['HAR-RV (return-space)'] = diag
        print(f"  HAR-RV (return-space): mean={diag['mean']}, std={diag['std']}, "
              f"skew={diag['skewness']}, kurt={diag['kurtosis']}, "
              f"1st pct={diag['pct_1']}, 5th pct={diag['pct_5']}")

    # -------------------------------------------------------
    # 12. Save results
    # -------------------------------------------------------
    elapsed = time.time() - t0

    results = {
        'experiment_id': 'K852',
        'title': 'K852: Realized GARCH — GARCH Structure + 5-min RV Measurement',
        'proposer': '[提出: 用戶, 執行: Claude]',
        'method': 'Realized GARCH (Simple + Log) vs GJR-GARCH vs HAR-RV',
        'asset': '0050.TW',
        'rv_source': 'TAIFEX TX1 tick data (5-min RV)',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'data_source': 'TAIFEX TX tick data (5-min RV) + yfinance (0050.TW returns)',
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'GARCH OOS: recursive h[t]=f(h[t-1], RV[t-1] or r^2[t-1])',
            'RealGARCH-Simple: h[t] = omega + (alpha+gamma*I)*RV[t-1] + beta*h[t-1]',
            'RealGARCH-Log: log(h[t]) = omega + beta*log(h[t-1]) + delta*log(RV[t-1])',
            'DM test: Newey-West HAC, Harvey t>3.0',
            'VaR: sigma * z_alpha (proper distribution conversion)',
            'Date alignment: inner join (TX RV intersect 0050.TW returns)',
        ],
        'references': [
            'Hansen, Huang & Shek (2012) - Realized GARCH, J Applied Econometrics',
            'Corsi (2009) - HAR-RV model, J Financial Econometrics',
            'Hansen & Lunde (2005) - 5-min RV gold standard',
            'Patton (2011) - QLIKE proxy-robust, J Econometrics',
            'Cornish & Fisher (1938) - CF expansion',
            'K849: HAR-RV QLIKE=0.109 vs GJR=0.202 (DM t=-11.14)',
            'K850: GJR+CF Trinity PASS (2 viol), HAR+HistSim (17 viol)',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(elapsed, 1),
        'n_oos': n_oos,
        'n_common_dates': len(common_dates),
        'n_refits': {
            'GJR': n_gjr_refits,
            'RealGARCH-Simple': n_rgs_refits,
            'RealGARCH-Log': n_rgl_refits,
        },
        'oos_stats': oos_stats,
        'track1_vol_prediction': {
            'qlike_on_rv_total': qlike_results,
            'spearman_rank_corr': spearman_results,
            'dm_test': dm_results,
        },
        'track2_var_backtest': var_results,
        'model_params_last_refit': model_params,
        'residual_diagnostics': resid_diagnostics,
        'conclusions': conclusions,
    }

    results = make_serializable(results)

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to {RESULTS_PATH}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"\n{'='*70}")
    print("K852 COMPLETE")
    print(f"{'='*70}")

    return results


if __name__ == '__main__':
    main()
