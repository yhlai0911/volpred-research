#!/usr/bin/env python3
"""
K854: Common Sample VaR — Fix K850's 450 vs 481 Unfair Comparison
===================================================================
[提出: Codex H2, 執行: Claude]

Motivation:
  K850: GJR used 481 OOS days, HAR only 450 (22-day burn-in).
  Codex flagged this as unfair comparison. K854 fixes it:
  ALL models evaluated on the SAME 450-day OOS window.

Models (7 total, all on identical 450 days):
  M1: GJR + Normal
  M2: GJR + Cornish-Fisher
  M3: GJR + Skewed Student-t (Fernandez-Steel 1998)
  M4: HAR + Normal
  M5: HAR + CF
  M6: HAR + HistSim
  M7: RealGARCH-Log + CF (K852 showed RGL+CF = Trinity PASS)

Data:
  - TAIFEX TX1 tick → 5-min RV (reused K849/K850 pipeline)
  - 0050.TW daily returns (clean_tw50_data mandatory)

OOS: Last 450 days where HAR has valid forecasts (common sample)
IS:  All prior data (expanding window)
Refit: every 63 trading days

Evaluation:
  - 1% VaR: Kupiec + Christoffersen + Basel + Trinity
  - 5% VaR: same tests
  - QLIKE on RV_total (vol prediction quality)
  - DM test (QLIKE loss) for all pairs
  - Core question: On identical sample, does the paradox persist?
    (HAR better QLIKE but worse VaR?)

Error Log rules:
  - 0050.TW: clean_tw50_data (volpred.utils)
  - HAR: RV_{t-1}, RV_{t-1:5}, RV_{t-1:22} (no lookahead)
  - GJR OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - RealGARCH-Log: log(h[t]) = omega + beta*log(h[t-1]) + delta*log(RV[t-1])
  - Date alignment: inner join on trading days with both TX RV and 0050.TW
  - Student-t scale: sqrt((df-2)/df) for proper standardization
  - Skewed-t: Fernandez-Steel (1998) parametrization

References:
  - Corsi (2009): HAR-RV model, J Financial Econometrics
  - Hansen & Lunde (2005): 5-min RV gold standard
  - Hansen, Huang & Shek (2012): Realized GARCH, J Applied Econometrics
  - Cornish & Fisher (1938): CF expansion
  - Fernandez & Steel (1998): Skewed-t distribution, JASA
  - Patton (2011): QLIKE proxy-robust, J Econometrics
  - K850: GJR+CF Trinity PASS on 481 days, HAR 450 days (UNFAIR)
  - K852: RealGARCH-Log+CF also Trinity PASS on 481 days

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
from scipy.stats import norm, t as t_dist, chi2, skew, kurtosis
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

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k854_common_sample_var_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
HAR_MIN_TRAIN = 250
TARGET_OOS_DAYS = 450  # Common sample size (HAR's available days)

# TX session times (HHMMSS)
NIGHT_PM_START, NIGHT_PM_END = 150000, 235959
NIGHT_AM_START, NIGHT_AM_END = 0, 50000
DAY_START, DAY_END = 84500, 134500


# ============================================================
# A. Build 5-min RV from TAIFEX tick data
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
    elif not np.isnan(rv_day):
        rv_total = rv_day
    else:
        rv_total = np.nan

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'rv_total': rv_total if not np.isnan(rv_total) else None,
    }


def load_all_rv_data(start_date='2017-01-01'):
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))
    cutoff = f"Daily_{start_date.replace('-', '_')}"
    files = [f for f in all_files if os.path.basename(f) >= cutoff]
    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {start_date}")

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
    for col in ['rv_day', 'rv_night', 'rv_total']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


# ============================================================
# B. HAR-RV Model (OOS expanding window)
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


def compute_har_return_residuals(returns, har_forecasts, common_dates, up_to_idx):
    """z_t = r_t / sqrt(HAR_forecast_t) for all t < up_to_idx."""
    z_list = []
    for i in range(up_to_idx):
        date = common_dates[i]
        r_t = returns.get(date, np.nan)
        h_t = har_forecasts.get(date, np.nan)
        if np.isfinite(r_t) and np.isfinite(h_t) and h_t > 0:
            z_list.append(r_t / np.sqrt(h_t))
    return np.array(z_list) if z_list else np.array([])


# ============================================================
# C. GJR-GARCH(1,1) — numba accelerated
# ============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
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


def fit_gjr(returns, n_starts=4):
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


def gjr_one_step_forecast(returns, params):
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params):
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]


# ============================================================
# D. RealGARCH-Log (from K852)
# ============================================================

def fit_real_garch_log(returns, rv_arr, n_starts=4):
    """
    Fit RealGARCH-Log: log(h_t) = omega + beta * log(h_{t-1}) + delta * log(RV_{t-1})
    Hansen, Huang & Shek (2012) style.
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = np.ascontiguousarray(rv_arr, dtype=np.float64)
    if len(r) < 100:
        return None

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
            'delta': float(delta), 'persistence': float(beta)}


def realgarch_log_filter(returns, rv_arr, params):
    """Run RealGARCH-Log filter, return h array."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv_clean = rv_arr.copy()
    running_mean = np.nanmean(rv_clean[rv_clean > 0])
    for i in range(len(rv_clean)):
        if rv_clean[i] <= 0 or np.isnan(rv_clean[i]):
            rv_clean[i] = running_mean
    log_rv = np.log(rv_clean)

    T = len(r)
    log_h = np.empty(T)
    log_h[0] = (params['omega'] / (1 - params['beta'])
                + params['delta'] / (1 - params['beta'])
                * np.mean(log_rv[:min(22, T)]))
    for t in range(1, T):
        log_h[t] = (params['omega']
                     + params['beta'] * log_h[t - 1]
                     + params['delta'] * log_rv[t - 1])
    h = np.exp(log_h)
    h = np.maximum(h, 1e-16)
    return h


def compute_std_residuals_real_log(returns, rv_arr, params):
    """RealGARCH-Log standardized residuals: z_t = r_t / sqrt(h_t)"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    h = realgarch_log_filter(r, rv_arr, params)
    sigma = np.sqrt(h)
    z = r / sigma
    return z[1:]


def realgarch_log_one_step_forecast(returns, rv_arr, params):
    """One-step-ahead forecast from RealGARCH-Log."""
    h = realgarch_log_filter(returns, rv_arr, params)
    rv_clean = rv_arr.copy()
    running_mean = np.nanmean(rv_clean[rv_clean > 0])
    for i in range(len(rv_clean)):
        if rv_clean[i] <= 0 or np.isnan(rv_clean[i]):
            rv_clean[i] = running_mean
    log_rv_last = np.log(rv_clean[-1])
    log_h_last = np.log(max(h[-1], 1e-16))
    log_h_next = params['omega'] + params['beta'] * log_h_last + params['delta'] * log_rv_last
    return max(np.exp(log_h_next), 1e-16)


# ============================================================
# E. Cornish-Fisher quantile
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
# F. Skewed Student-t (Fernandez-Steel 1998) for GJR
# ============================================================

def estimate_skewt_params(std_residuals, df_min=2.1, df_max=30.0):
    """Fit Fernandez-Steel (1998) skewed-t to GJR standardized residuals."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return {'df': 5.0, 'xi': 0.85}

    def skewt_logpdf(x, df, xi):
        c = 2.0 / (xi + 1.0 / xi)
        y = np.where(x >= 0, x / xi, x * xi)
        return np.log(c) + t_dist.logpdf(y, df=df)

    def neg_loglik(params):
        log_df, log_xi = params
        df = np.exp(log_df)
        xi = np.exp(log_xi)
        if df < df_min or df > df_max:
            return 1e10
        if xi <= 0:
            return 1e10
        ll = np.sum(skewt_logpdf(z, df, xi))
        return -ll if np.isfinite(ll) else 1e10

    res = minimize(neg_loglik,
                   x0=[np.log(5.0), np.log(0.85)],
                   method='L-BFGS-B',
                   bounds=[(np.log(df_min), np.log(df_max)),
                           (np.log(0.3), np.log(3.0))],
                   options={'maxiter': 1000})
    df_est = float(np.exp(res.x[0]))
    xi_est = float(np.exp(res.x[1]))
    return {'df': float(np.clip(df_est, df_min, df_max)),
            'xi': float(np.clip(xi_est, 0.3, 3.0))}


def skewt_ppf(p, df, xi):
    """
    Quantile function of Fernandez-Steel (1998) skewed-t.
    xi < 1 → left-skewed (longer left tail).
    """
    c = 2.0 / (xi + 1.0 / xi)
    p0 = 1.0 / (1.0 + xi ** 2)

    if p <= p0:
        inner = p * xi / c
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = float(t_dist.ppf(inner, df=df)) / xi
    else:
        inner = 0.5 + (p - p0) / (xi * c)
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = xi * float(t_dist.ppf(inner, df=df))

    return z


# ============================================================
# G. VaR Backtest: Kupiec + Christoffersen + Basel
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
# H. QLIKE and DM test
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
# I. JSON serialization helper
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
# J. Main experiment
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K854: Common Sample VaR — Fix K850's Unfair 450 vs 481 Comparison")
    print("  ALL 7 models evaluated on IDENTICAL OOS dates")
    print(f"  Models: GJR+Normal, GJR+CF, GJR+Skewed-t, HAR+Normal,")
    print(f"          HAR+CF, HAR+HistSim, RealGARCH-Log+CF")
    print(f"  OOS window: {OOS_START} ~ {OOS_END}")
    print(f"  Refit: every {REFIT_EVERY} trading days")
    print("=" * 70)

    # -------------------------------------------------------
    # 1. Load TAIFEX TX 5-min RV
    # -------------------------------------------------------
    print("\n[1] Loading TAIFEX TX1 tick data -> 5-min RV...")
    rv_df = load_all_rv_data(start_date='2017-01-01')
    print(f"  RV data: {len(rv_df)} days ({rv_df.index[0].date()} ~ {rv_df.index[-1].date()})")

    rv_total = rv_df['rv_total'].dropna()
    ann_vol = np.sqrt(rv_total.mean() * 252) * 100
    print(f"  RV_total: mean={rv_total.mean():.2e}, ann vol={ann_vol:.1f}%")

    # -------------------------------------------------------
    # 2. Load 0050.TW returns
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
    # 3. Align dates: inner join on trading days
    # -------------------------------------------------------
    common_dates = rv_total.index.intersection(etf_returns.index)
    common_dates = common_dates.sort_values()
    print(f"\n[3] Common dates (RV + ETF): {len(common_dates)}")

    rv_aligned = rv_total.loc[common_dates]
    ret_aligned = etf_returns.loc[common_dates]

    # Full OOS mask (before trimming to common sample)
    oos_mask_full = (common_dates >= OOS_START) & (common_dates <= OOS_END)
    n_oos_full = int(oos_mask_full.sum())
    oos_dates_full = common_dates[oos_mask_full]
    print(f"  Full OOS: {n_oos_full} days ({oos_dates_full[0].date()} ~ {oos_dates_full[-1].date()})")

    # -------------------------------------------------------
    # 4. HAR-RV OOS forecasts (to determine common sample)
    # -------------------------------------------------------
    print("\n[4] Running HAR-RV OOS forecasts...")
    har_forecasts = har_oos_forecasts(
        rv_aligned, oos_start=OOS_START, refit_freq=REFIT_EVERY, min_train=HAR_MIN_TRAIN
    )

    # Find the first OOS date where HAR has a valid forecast
    har_oos_full = har_forecasts.loc[oos_dates_full]
    har_valid_mask = har_oos_full.notna()
    first_har_valid_idx = har_valid_mask.values.argmax()  # first True
    if not har_valid_mask.iloc[first_har_valid_idx]:
        print("  ERROR: HAR has no valid OOS forecasts!")
        return None

    # Common OOS = from first HAR valid date to end
    common_oos_dates = oos_dates_full[first_har_valid_idx:]
    n_common_oos = len(common_oos_dates)
    print(f"  HAR first valid OOS: {common_oos_dates[0].date()}")
    print(f"  Common OOS sample: {n_common_oos} days "
          f"({common_oos_dates[0].date()} ~ {common_oos_dates[-1].date()})")
    print(f"  Trimmed from K850: {n_oos_full} -> {n_common_oos} days "
          f"(removed {n_oos_full - n_common_oos} days where HAR was unavailable)")

    # OOS descriptive stats (common sample only)
    oos_ret = ret_aligned.loc[common_oos_dates].values
    oos_stats = {
        'mean': float(np.mean(oos_ret)),
        'std': float(np.std(oos_ret)),
        'skewness': float(skew(oos_ret)),
        'kurtosis': float(kurtosis(oos_ret, fisher=True)),
        'min': float(np.min(oos_ret)),
        'max': float(np.max(oos_ret)),
        'n_oos': n_common_oos,
    }
    print(f"  OOS stats: mean={oos_stats['mean']:.6f}, std={oos_stats['std']:.4f}, "
          f"skew={oos_stats['skewness']:.3f}, kurt={oos_stats['kurtosis']:.2f}")

    # -------------------------------------------------------
    # 5. GJR-GARCH OOS forecasts
    # -------------------------------------------------------
    print("\n[5] Running GJR-GARCH OOS forecasts...")
    all_returns_arr = ret_aligned.values
    all_rv_arr = rv_aligned.values
    all_dates_arr = common_dates

    oos_start_idx = int(np.searchsorted(all_dates_arr, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(all_dates_arr, pd.Timestamp(OOS_END), side='right'))

    gjr_forecasts = np.full(len(common_dates), np.nan)
    gjr_std_residuals = {}
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
                z = compute_standardized_residuals(train_r, params)
                gjr_std_residuals[i] = z
                n_gjr_refits += 1
                last_gjr_refit = day_idx
                if n_gjr_refits <= 2 or day_idx % (REFIT_EVERY * 2) == 0:
                    print(f"    GJR refit @day {day_idx}: pers={params['persistence']:.4f}")

        if current_gjr_params is None:
            continue
        sigma2_f = gjr_one_step_forecast(all_returns_arr[:i], current_gjr_params)
        gjr_forecasts[i] = sigma2_f

    gjr_forecasts_series = pd.Series(gjr_forecasts, index=common_dates, name='GJR')
    print(f"  GJR refits: {n_gjr_refits}")

    # -------------------------------------------------------
    # 6. RealGARCH-Log OOS forecasts
    # -------------------------------------------------------
    print("\n[6] Running RealGARCH-Log OOS forecasts...")
    rgl_forecasts = np.full(len(common_dates), np.nan)
    rgl_std_residuals = {}
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
                rgl_std_residuals[i] = z
                n_rgl_refits += 1
                last_rgl_refit = day_idx
                if n_rgl_refits <= 2 or day_idx % (REFIT_EVERY * 2) == 0:
                    print(f"    RGL refit @day {day_idx}: beta={params['beta']:.4f}, "
                          f"delta={params['delta']:.4f}")

        if current_rgl_params is None:
            continue
        sigma2_f = realgarch_log_one_step_forecast(
            all_returns_arr[:i], all_rv_arr[:i], current_rgl_params
        )
        rgl_forecasts[i] = sigma2_f

    rgl_forecasts_series = pd.Series(rgl_forecasts, index=common_dates, name='RGL')
    print(f"  RGL refits: {n_rgl_refits}")

    # -------------------------------------------------------
    # 7. Compute VaR for all 7 methods ON COMMON SAMPLE
    # -------------------------------------------------------
    print(f"\n[7] Computing VaR for 7 methods on common {n_common_oos}-day sample...")

    method_keys = [
        'gjr_normal', 'gjr_cf', 'gjr_skewedt',
        'har_normal', 'har_cf', 'har_histsim',
        'rgl_cf'
    ]
    method_display = {
        'gjr_normal': 'GJR+Normal',
        'gjr_cf': 'GJR+CF',
        'gjr_skewedt': 'GJR+Skewed-t',
        'har_normal': 'HAR+Normal',
        'har_cf': 'HAR+CF',
        'har_histsim': 'HAR+HistSim',
        'rgl_cf': 'RGL+CF',
    }

    var_forecasts = {alpha: {m: np.full(n_common_oos, np.nan) for m in method_keys}
                     for alpha in ALPHA_LEVELS}

    # Track sigma² forecasts for QLIKE
    sigma2_forecasts = {
        'gjr': np.full(n_common_oos, np.nan),
        'har': np.full(n_common_oos, np.nan),
        'rgl': np.full(n_common_oos, np.nan),
    }

    last_gjr_z = None
    last_gjr_skewt = None
    last_har_return_z = None
    last_rgl_z = None
    last_har_refit_oos_idx = -REFIT_EVERY

    gjr_refit_indices = sorted(gjr_std_residuals.keys())
    rgl_refit_indices = sorted(rgl_std_residuals.keys())

    for i_oos, date in enumerate(common_oos_dates):
        global_idx = int(np.searchsorted(common_dates, date))

        # Update GJR residuals
        for refit_idx in gjr_refit_indices:
            if refit_idx <= global_idx:
                last_gjr_z = gjr_std_residuals[refit_idx]
                # Fit skewed-t to GJR residuals at each refit
                last_gjr_skewt = estimate_skewt_params(last_gjr_z)

        # Update RealGARCH-Log residuals
        for refit_idx in rgl_refit_indices:
            if refit_idx <= global_idx:
                last_rgl_z = rgl_std_residuals[refit_idx]

        # Update HAR return-residuals periodically
        if i_oos - last_har_refit_oos_idx >= REFIT_EVERY or last_har_return_z is None:
            har_return_z = compute_har_return_residuals(
                ret_aligned, har_forecasts, common_dates, global_idx
            )
            if len(har_return_z) > 30:
                last_har_return_z = har_return_z
                last_har_refit_oos_idx = i_oos

        gjr_sigma2 = gjr_forecasts[global_idx] if global_idx < len(gjr_forecasts) else np.nan
        har_rv_f = har_forecasts.iloc[global_idx] if global_idx < len(har_forecasts) else np.nan
        rgl_sigma2 = rgl_forecasts[global_idx] if global_idx < len(rgl_forecasts) else np.nan

        # Store sigma² for QLIKE
        sigma2_forecasts['gjr'][i_oos] = gjr_sigma2
        sigma2_forecasts['har'][i_oos] = har_rv_f
        sigma2_forecasts['rgl'][i_oos] = rgl_sigma2

        for alpha in ALPHA_LEVELS:
            # --- GJR methods ---
            if not np.isnan(gjr_sigma2) and last_gjr_z is not None and len(last_gjr_z) > 30:
                gjr_sigma = np.sqrt(gjr_sigma2)

                # M1: GJR + Normal
                var_forecasts[alpha]['gjr_normal'][i_oos] = gjr_sigma * norm.ppf(alpha)

                # M2: GJR + CF
                z_cf = cornish_fisher_quantile(last_gjr_z, alpha)
                var_forecasts[alpha]['gjr_cf'][i_oos] = gjr_sigma * z_cf

                # M3: GJR + Skewed-t
                if last_gjr_skewt is not None:
                    z_st = skewt_ppf(alpha, df=last_gjr_skewt['df'],
                                      xi=last_gjr_skewt['xi'])
                    var_forecasts[alpha]['gjr_skewedt'][i_oos] = gjr_sigma * z_st

            # --- HAR methods ---
            if not np.isnan(har_rv_f) and last_har_return_z is not None and len(last_har_return_z) > 30:
                har_sigma = np.sqrt(har_rv_f)

                # M4: HAR + Normal
                var_forecasts[alpha]['har_normal'][i_oos] = har_sigma * norm.ppf(alpha)

                # M5: HAR + CF
                z_cf_har = cornish_fisher_quantile(last_har_return_z, alpha)
                var_forecasts[alpha]['har_cf'][i_oos] = har_sigma * z_cf_har

                # M6: HAR + HistSim
                z_hist = np.percentile(last_har_return_z, alpha * 100)
                var_forecasts[alpha]['har_histsim'][i_oos] = har_sigma * z_hist

            # --- RealGARCH-Log methods ---
            if not np.isnan(rgl_sigma2) and last_rgl_z is not None and len(last_rgl_z) > 30:
                rgl_sigma = np.sqrt(rgl_sigma2)

                # M7: RGL + CF
                z_cf_rgl = cornish_fisher_quantile(last_rgl_z, alpha)
                var_forecasts[alpha]['rgl_cf'][i_oos] = rgl_sigma * z_cf_rgl

    # -------------------------------------------------------
    # 8. Find TRULY common sample: days where ALL 7 methods have valid VaR
    # -------------------------------------------------------
    # Use 1% VaR to determine the common valid mask (same for all alpha)
    print(f"\n[8] Finding truly common sample (all 7 methods valid)...")
    all_valid_mask = np.ones(n_common_oos, dtype=bool)
    per_method_valid = {}
    for method_key in method_keys:
        valid = np.isfinite(var_forecasts[0.01][method_key])
        per_method_valid[method_key] = int(valid.sum())
        all_valid_mask &= valid
        print(f"    {method_display[method_key]:17s}: {valid.sum()}/{n_common_oos} valid")

    n_truly_common = int(all_valid_mask.sum())
    print(f"\n  Truly common sample (ALL 7 valid): {n_truly_common}/{n_common_oos}")
    print(f"  Dropped {n_common_oos - n_truly_common} days where at least 1 method had NaN")

    # Extract common-sample returns and dates
    common_ret = oos_ret[all_valid_mask]
    common_dates_subset = common_oos_dates[all_valid_mask]
    print(f"  Common period: {common_dates_subset[0].date()} ~ {common_dates_subset[-1].date()}")

    # -------------------------------------------------------
    # 9. Backtest all methods ON TRULY COMMON SAMPLE
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"RESULTS: VaR Backtest — Truly Common {n_truly_common}-Day Sample")
    print(f"{'='*70}")

    var_results = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f"{int(alpha*100)}%"
        var_results[alpha_key] = {}
        print(f"\n  --- {alpha_key} VaR ---")
        print(f"  {'Method':17s} {'Viol':>5s} {'N':>5s} {'Rate':>7s} {'Kupiec':>8s} {'Christ':>8s} "
              f"{'Basel':>7s} {'Trinity':>8s}")
        print(f"  {'-'*17} {'-'*5} {'-'*5} {'-'*7} {'-'*8} {'-'*8} {'-'*7} {'-'*8}")

        for method_key in method_keys:
            method_name = method_display[method_key]
            # Extract VaR only for common sample
            var_arr = var_forecasts[alpha][method_key][all_valid_mask]

            bt = var_backtest(common_ret, var_arr, alpha_var=alpha)
            var_results[alpha_key][method_name] = bt

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"  {method_name:17s} {bt['n_violations']:5d} "
                  f"{bt['n_total']:5d} "
                  f"{bt['violation_rate']:7.4f} "
                  f"p={bt['kupiec']['p_value']:.3f}  "
                  f"p={bt['christoffersen']['p_value']:.3f}  "
                  f"{bt['basel_traffic_light']:>7s} "
                  f"{status:>8s}")

    # -------------------------------------------------------
    # 10. QLIKE comparison on truly common sample
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"QLIKE on RV_total (common {n_truly_common}-day sample)")
    print(f"{'='*70}")

    rv_oos = rv_aligned.loc[common_oos_dates].values[all_valid_mask]
    qlike_results = {}
    qlike_loss_arrays = {}

    model_sigma2 = {
        'HAR-RV': sigma2_forecasts['har'][all_valid_mask],
        'GJR-GARCH': sigma2_forecasts['gjr'][all_valid_mask],
        'RealGARCH-Log': sigma2_forecasts['rgl'][all_valid_mask],
    }

    for model_name, forecasts in model_sigma2.items():
        valid = np.isfinite(forecasts) & np.isfinite(rv_oos) & (rv_oos > 0) & (forecasts > 0)
        if valid.sum() > 10:
            ql = qlike(rv_oos[valid], forecasts[valid])
            qlike_results[model_name] = {'qlike': ql, 'n_valid': int(valid.sum())}
            # Full loss series (for DM test)
            full_loss = np.full(n_truly_common, np.nan)
            full_loss[valid] = qlike_loss_series(rv_oos[valid], forecasts[valid])
            qlike_loss_arrays[model_name] = full_loss
            print(f"  {model_name:17s}: QLIKE={ql:.6f} (n={valid.sum()})")

    # DM tests between all pairs
    print(f"\n  DM tests (QLIKE, Harvey t>3.0):")
    dm_results = {}
    model_names = list(qlike_loss_arrays.keys())
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            t_stat, p_val = dm_test(qlike_loss_arrays[m1], qlike_loss_arrays[m2])
            key = f"{m1}_vs_{m2}"
            if t_stat < -3.0:
                interp = f"{m1} better"
            elif t_stat > 3.0:
                interp = f"{m2} better"
            else:
                interp = "no sig diff"
            dm_results[key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'n_obs': int(min(
                    np.isfinite(qlike_loss_arrays[m1]).sum(),
                    np.isfinite(qlike_loss_arrays[m2]).sum()
                )),
                'significant': bool(abs(t_stat) > 3.0),
                'interpretation': interp
            }
            print(f"    {m1} vs {m2}: t={t_stat:.4f}, p={p_val:.6f} -> {interp}")

    # -------------------------------------------------------
    # 11. Average VaR level (on common sample)
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"Average VaR Level Comparison (1%, common {n_truly_common}-day sample)")
    print(f"{'='*70}")

    avg_var = {}
    for method_key in method_keys:
        var_arr = var_forecasts[0.01][method_key][all_valid_mask]
        avg = float(np.mean(var_arr))
        avg_var[method_display[method_key]] = avg
        print(f"  {method_display[method_key]:17s}: mean VaR(1%) = {avg:.6f} ({avg*100:.3f}%)")

    # -------------------------------------------------------
    # 12. Summary and Paradox Assessment
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print(f"SUMMARY: K854 Common-Sample ({n_truly_common} days) — Paradox Assessment")
    print(f"{'='*70}")

    conclusion_lines = []

    # Check 1% VaR Trinity results
    trinity_passes = {}
    for method_key in method_keys:
        mn = method_display[method_key]
        r = var_results.get('1%', {}).get(mn, {})
        if 'error' not in r:
            trinity_passes[mn] = r.get('trinity_pass', False)

    passes = [m for m, v in trinity_passes.items() if v]
    fails = [m for m, v in trinity_passes.items() if not v]

    conclusion_lines.append(f"Common sample: {n_truly_common} days (K850 used 481 GJR / 450 HAR)")
    if passes:
        conclusion_lines.append(f"1% VaR Trinity PASS: {', '.join(passes)}")
    if fails:
        conclusion_lines.append(f"1% VaR Trinity FAIL: {', '.join(fails)}")

    # Paradox check
    har_pass_any = any(trinity_passes.get(method_display[mk], False)
                       for mk in ['har_normal', 'har_cf', 'har_histsim'])
    gjr_pass_any = any(trinity_passes.get(method_display[mk], False)
                       for mk in ['gjr_normal', 'gjr_cf', 'gjr_skewedt'])

    if 'HAR-RV' in qlike_results and 'GJR-GARCH' in qlike_results:
        har_ql = qlike_results['HAR-RV']['qlike']
        gjr_ql = qlike_results['GJR-GARCH']['qlike']
        improvement = (gjr_ql - har_ql) / gjr_ql * 100
        conclusion_lines.append(
            f"QLIKE: HAR={har_ql:.4f} vs GJR={gjr_ql:.4f} ({improvement:+.1f}% better)"
        )

    if har_pass_any and gjr_pass_any:
        conclusion_lines.append("PARADOX RESOLVED: Both HAR and GJR pass on common sample")
    elif gjr_pass_any and not har_pass_any:
        conclusion_lines.append("PARADOX PERSISTS: GJR+CF passes, HAR methods fail, even on common sample")
        conclusion_lines.append("  -> Better vol prediction (HAR) != better VaR (GJR has better residual tails)")
    elif har_pass_any and not gjr_pass_any:
        conclusion_lines.append("PARADOX REVERSED: HAR passes, GJR fails on common sample")
    else:
        conclusion_lines.append("NEITHER passes Trinity on common sample")

    # Best method
    best_method = None
    best_violations = 999
    for mk in method_keys:
        mn = method_display[mk]
        r = var_results.get('1%', {}).get(mn, {})
        if 'error' not in r and r.get('trinity_pass', False):
            if r['n_violations'] < best_violations:
                best_method = mn
                best_violations = r['n_violations']
    if best_method is None:
        for mk in method_keys:
            mn = method_display[mk]
            r = var_results.get('1%', {}).get(mn, {})
            if 'error' not in r and r['n_violations'] < best_violations:
                best_method = mn
                best_violations = r['n_violations']

    if best_method:
        conclusion_lines.append(f"Best 1% VaR: {best_method} ({best_violations} violations)")

    for line in conclusion_lines:
        print(f"\n  >>> {line}")

    elapsed = time.time() - t0

    # -------------------------------------------------------
    # 13. Save results
    # -------------------------------------------------------
    results = {
        'experiment_id': 'K854',
        'title': 'K854: Common Sample VaR — Fix K850 Unfair 450 vs 481 Comparison',
        'proposer': '[提出: Codex H2, 執行: Claude]',
        'method': '7 models on identical OOS window (truly common sample)',
        'asset': '0050.TW',
        'rv_source': 'TAIFEX TX1 tick data (5-min RV)',
        'oos_period': f'{common_dates_subset[0].date()} to {common_dates_subset[-1].date()}',
        'oos_period_requested': f'{OOS_START} to {OOS_END}',
        'n_truly_common_oos': n_truly_common,
        'n_oos_before_common_filter': n_common_oos,
        'n_oos_original_full': n_oos_full,
        'n_days_trimmed': n_oos_full - n_truly_common,
        'common_sample_start': str(common_dates_subset[0].date()),
        'common_sample_end': str(common_dates_subset[-1].date()),
        'per_method_valid_counts': {method_display[k]: v for k, v in per_method_valid.items()},
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'models': list(method_display.values()),
        'data_source': 'TAIFEX TX tick data (5-min RV) + yfinance (0050.TW returns)',
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'HAR: RV_{t-1}, RV_{t-1:5}, RV_{t-1:22} (no lookahead)',
            'GJR OOS: recursive h[t]=f(h[t-1], r^2[t-1])',
            'RealGARCH-Log: log(h[t]) = omega + beta*log(h[t-1]) + delta*log(RV[t-1])',
            'Skewed-t: Fernandez-Steel (1998), fitted to GJR std residuals',
            'Date alignment: inner join (TX RV intersect 0050.TW returns)',
            'COMMON SAMPLE: All models evaluated on identical dates',
        ],
        'references': [
            'Corsi (2009) - HAR-RV model, J Financial Econometrics',
            'Hansen & Lunde (2005) - 5-min RV gold standard',
            'Hansen, Huang & Shek (2012) - Realized GARCH, J Applied Econometrics',
            'Cornish & Fisher (1938) - CF expansion',
            'Fernandez & Steel (1998) - Skewed-t distribution, JASA',
            'Patton (2011) - QLIKE proxy-robust, J Econometrics',
            'K850: GJR+CF Trinity PASS on 481d, HAR 450d (UNFAIR)',
            'K852: RealGARCH-Log+CF also Trinity PASS on 481d',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(elapsed, 1),
        'n_common_dates': len(common_dates),
        'n_gjr_refits': n_gjr_refits,
        'n_rgl_refits': n_rgl_refits,
        'oos_stats_common_sample': {
            'mean': float(np.mean(common_ret)),
            'std': float(np.std(common_ret)),
            'skewness': float(skew(common_ret)),
            'kurtosis': float(kurtosis(common_ret, fisher=True)),
            'min': float(np.min(common_ret)),
            'max': float(np.max(common_ret)),
            'n': n_truly_common,
        },
        'oos_stats_full_481': oos_stats,
        'var_results': var_results,
        'qlike_results': qlike_results,
        'dm_test': dm_results,
        'avg_var_1pct': avg_var,
        'best_method_1pct': best_method,
        'conclusions': conclusion_lines,
        'k850_comparison': {
            'k850_gjr_cf_1pct': '2 violations / 481 days (Trinity PASS)',
            'k850_har_histsim_1pct': '9 violations / 450 days (Trinity FAIL)',
            'k850_unfairness': 'GJR had 31 more days than HAR',
            'k854_fix': f'All 7 models now on {n_truly_common} truly common days',
        }
    }

    results = make_serializable(results)

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to {RESULTS_PATH}")
    print(f"  Elapsed: {elapsed:.1f}s")

    return results


if __name__ == '__main__':
    main()
