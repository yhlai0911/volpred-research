#!/usr/bin/env python3
"""
K850: HAR-RV based VaR for Taiwan — Replace GJR σ with HAR-RV σ in VaR
========================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K849: HAR-RV crushes GJR-GARCH on vol prediction (DM t=-11.14, QLIKE 66% better)
  K836: GJR+Cornish-Fisher is the ONLY 0050.TW 1% VaR Trinity PASS (3/481)
  Question: If we use HAR-RV σ (from TAIFEX 5-min RV) instead of GJR σ, can we
  get better VaR — both more accurate coverage AND better prediction quality?

Models (5 total):
  M1: GJR + Normal          (K829 baseline, FAIL)
  M2: GJR + Cornish-Fisher  (K836 champion, 3/481 Trinity PASS)
  M3: HAR-RV + Normal       (σ = sqrt(HAR_forecast), VaR = σ × z_α)
  M4: HAR-RV + CF           (HAR σ + Cornish-Fisher adjusted quantile)
  M5: HAR-RV + HistSim      (HAR σ × empirical quantile of HAR residuals)

Data:
  - TAIFEX TX1 tick data → 5-min RV (reused K849 pipeline)
  - 0050.TW daily returns (clean_tw50_data mandatory)

OOS: 2023-01-01 ~ 2024-12-31 (same as K836 for direct comparison)
IS:  2017-05 ~ 2022-12 (Track B: full day+night RV)
HAR: expanding window, refit every 63 trading days

Evaluation:
  - Kupiec + Christoffersen + Basel traffic light + Trinity (1% and 5%)
  - QLIKE on RV_total (HAR advantage metric)
  - DM test (QLIKE loss)
  - Average VaR level comparison

Error Log rules:
  - 0050.TW: clean_tw50_data (volpred.utils)
  - HAR regressors: RV_{t-1}, RV_{t-1:5}, RV_{t-1:22}
  - Date alignment: inner join on trading days with both TX RV and 0050.TW returns
  - Student-t: scale=sqrt((df-2)/df) for GJR methods

References:
  - Corsi (2009): HAR-RV model
  - Hansen & Lunde (2005): 5-min RV as gold standard
  - McNeil & Frey (2000): EVT-POT for VaR
  - Cornish & Fisher (1938): CF expansion
  - K836: GJR+CF Trinity PASS (3/481 at 1%)
  - K849: HAR-RV QLIKE=0.109 vs GJR=0.202 (Track B)
  - Patton (2011): QLIKE proxy-robust

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

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k850_har_rv_var_taiwan_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
HAR_MIN_TRAIN = 250

# TX session times (HHMMSS)
NIGHT_PM_START, NIGHT_PM_END = 150000, 235959
NIGHT_AM_START, NIGHT_AM_END = 0, 50000
DAY_START, DAY_END = 84500, 134500


# ============================================================
# A. Build 5-min RV from TAIFEX tick data (K849 pipeline)
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

    # Filter to near-month by volume
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
    """Load TX1 files from start_date onwards, compute 5-min RV."""
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
    # Convert to float
    for col in ['rv_day', 'rv_night', 'rv_total']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


# ============================================================
# B. HAR-RV Model (OOS expanding window)
# ============================================================

def fit_har_ols(y, X):
    """OLS: y = [1, X] @ beta. Returns beta, y_hat, R-squared."""
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
    """
    HAR-RV OOS forecasts: expanding window, refit every refit_freq days.
    Returns forecasts Series only (residuals computed separately from returns).
    """
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

            # Build features
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

        # Build features for t (using data up to t-1)
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
    """
    Compute standardized return residuals using HAR σ:
      z_t = r_t / sqrt(HAR_forecast_t)

    These are in RETURN space (not RV space), suitable for CF/HistSim VaR.
    Only uses data up to (but not including) up_to_idx for expanding window.
    """
    z_list = []
    for i in range(up_to_idx):
        date = common_dates[i]
        r_t = returns.get(date, np.nan)
        h_t = har_forecasts.get(date, np.nan)
        if np.isfinite(r_t) and np.isfinite(h_t) and h_t > 0:
            z_list.append(r_t / np.sqrt(h_t))
    return np.array(z_list) if z_list else np.array([])


# ============================================================
# C. GJR-GARCH(1,1) — numba accelerated (from K836)
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
# H. Main experiment
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K850: HAR-RV based VaR for Taiwan")
    print("  Question: Can HAR-RV σ replace GJR σ for better 0050.TW VaR?")
    print(f"  Models: GJR+Normal, GJR+CF, HAR+Normal, HAR+CF, HAR+HistSim")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print(f"  Refit: every {REFIT_EVERY} trading days")
    print("=" * 70)

    # -------------------------------------------------------
    # 1. Load TAIFEX TX 5-min RV
    # -------------------------------------------------------
    print("\n[1] Loading TAIFEX TX1 tick data → 5-min RV...")
    rv_df = load_all_rv_data(start_date='2017-01-01')
    print(f"  RV data: {len(rv_df)} days ({rv_df.index[0].date()} ~ {rv_df.index[-1].date()})")

    # Descriptive stats for RV
    rv_total = rv_df['rv_total'].dropna()
    print(f"  RV_total: mean={rv_total.mean():.2e}, std={rv_total.std():.2e}, "
          f"median={rv_total.median():.2e}")
    ann_vol = np.sqrt(rv_total.mean() * 252) * 100
    print(f"  Annualized vol (from mean RV): {ann_vol:.1f}%")

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
    # 4. HAR-RV OOS forecasts
    # -------------------------------------------------------
    print("\n[4] Running HAR-RV OOS forecasts (expanding window)...")
    har_forecasts = har_oos_forecasts(
        rv_aligned, oos_start=OOS_START, refit_freq=REFIT_EVERY, min_train=HAR_MIN_TRAIN
    )
    har_oos = har_forecasts.loc[oos_dates]
    har_valid = har_oos.dropna()
    print(f"  HAR valid forecasts in OOS: {len(har_valid)}/{n_oos}")

    # -------------------------------------------------------
    # 5. GJR-GARCH OOS forecasts (expanding window on ETF returns)
    # -------------------------------------------------------
    print("\n[5] Running GJR-GARCH OOS forecasts...")
    all_returns_arr = ret_aligned.values
    all_dates_arr = common_dates

    oos_start_idx = int(np.searchsorted(all_dates_arr, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(all_dates_arr, pd.Timestamp(OOS_END), side='right'))

    gjr_forecasts = np.full(len(common_dates), np.nan)
    gjr_std_residuals = {}  # refit_idx -> z array
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

        # Recursive one-step forecast
        sigma2_f = gjr_one_step_forecast(all_returns_arr[:i], current_gjr_params)
        gjr_forecasts[i] = sigma2_f

    gjr_forecasts_series = pd.Series(gjr_forecasts, index=common_dates, name='GJR')
    gjr_oos = gjr_forecasts_series.loc[oos_dates]
    gjr_valid = gjr_oos.dropna()
    print(f"  GJR refits: {n_gjr_refits}, valid OOS: {len(gjr_valid)}/{n_oos}")

    # -------------------------------------------------------
    # 6. Compute VaR for all 5 methods
    # -------------------------------------------------------
    print("\n[6] Computing VaR for all 5 methods...")

    method_keys = ['gjr_normal', 'gjr_cf', 'har_normal', 'har_cf', 'har_histsim']
    method_display = {
        'gjr_normal': 'GJR+Normal',
        'gjr_cf': 'GJR+CF',
        'har_normal': 'HAR+Normal',
        'har_cf': 'HAR+CF',
        'har_histsim': 'HAR+HistSim',
    }

    var_forecasts = {alpha: {m: np.full(n_oos, np.nan) for m in method_keys}
                     for alpha in ALPHA_LEVELS}

    # Pre-compute HAR in-sample forecasts for return-residual computation
    # For each OOS day t, we need z_i = r_i / sqrt(HAR_forecast_i) for all i < t
    # We'll expand these as we go, refitting HAR return-residuals periodically
    last_gjr_z = None
    last_har_return_z = None  # r_t / sqrt(HAR_t) in RETURN space
    last_har_refit_oos_idx = -REFIT_EVERY

    # Pre-sort GJR refit indices for efficient lookup
    gjr_refit_indices = sorted(gjr_std_residuals.keys())

    for i_oos, date in enumerate(oos_dates):
        global_idx = np.searchsorted(common_dates, date)

        # Update GJR residuals if refitted at or before this date
        for refit_idx in gjr_refit_indices:
            if refit_idx <= global_idx:
                last_gjr_z = gjr_std_residuals[refit_idx]

        # Update HAR return-residuals periodically (every REFIT_EVERY OOS days)
        # z_t = r_t / sqrt(HAR_forecast_t) for all t where both exist, up to current date
        if i_oos - last_har_refit_oos_idx >= REFIT_EVERY or last_har_return_z is None:
            har_return_z = compute_har_return_residuals(
                ret_aligned, har_forecasts, common_dates, global_idx
            )
            if len(har_return_z) > 30:
                last_har_return_z = har_return_z
                last_har_refit_oos_idx = i_oos

        gjr_sigma2 = gjr_forecasts[global_idx] if global_idx < len(gjr_forecasts) else np.nan
        har_rv_f = har_forecasts.iloc[global_idx] if global_idx < len(har_forecasts) else np.nan

        for alpha in ALPHA_LEVELS:
            # --- GJR-based methods ---
            if not np.isnan(gjr_sigma2) and last_gjr_z is not None and len(last_gjr_z) > 30:
                gjr_sigma = np.sqrt(gjr_sigma2)

                # M1: GJR + Normal
                z_normal = norm.ppf(alpha)
                var_forecasts[alpha]['gjr_normal'][i_oos] = gjr_sigma * z_normal

                # M2: GJR + Cornish-Fisher (using GJR std residuals)
                z_cf = cornish_fisher_quantile(last_gjr_z, alpha)
                var_forecasts[alpha]['gjr_cf'][i_oos] = gjr_sigma * z_cf

            # --- HAR-based methods ---
            # σ from HAR-RV, but quantile adjustments from RETURN-space residuals
            if not np.isnan(har_rv_f) and last_har_return_z is not None and len(last_har_return_z) > 30:
                har_sigma = np.sqrt(har_rv_f)

                # M3: HAR + Normal
                z_normal = norm.ppf(alpha)
                var_forecasts[alpha]['har_normal'][i_oos] = har_sigma * z_normal

                # M4: HAR + CF (using return-space residuals z_t = r_t/sqrt(HAR_t))
                z_cf_har = cornish_fisher_quantile(last_har_return_z, alpha)
                var_forecasts[alpha]['har_cf'][i_oos] = har_sigma * z_cf_har

                # M5: HAR + HistSim (empirical quantile of return-space residuals)
                z_hist = np.percentile(last_har_return_z, alpha * 100)
                var_forecasts[alpha]['har_histsim'][i_oos] = har_sigma * z_hist

    # -------------------------------------------------------
    # 7. Backtest all methods
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("RESULTS: VaR Backtest for 0050.TW")
    print(f"{'='*70}")

    var_results = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f"{int(alpha*100)}%"
        var_results[alpha_key] = {}
        print(f"\n  --- {alpha_key} VaR ---")

        for method_key in method_keys:
            method_name = method_display[method_key]
            var_arr = var_forecasts[alpha][method_key]
            valid = np.isfinite(var_arr)

            if valid.sum() < 50:
                var_results[alpha_key][method_name] = {'error': 'insufficient forecasts',
                                                        'n_valid': int(valid.sum())}
                print(f"  {method_name:15s}: SKIP (only {valid.sum()} valid)")
                continue

            bt = var_backtest(oos_ret[valid], var_arr[valid], alpha_var=alpha)
            var_results[alpha_key][method_name] = bt

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"  {method_name:15s}: {bt['n_violations']:2d}/{bt['n_total']} "
                  f"({bt['violation_rate']:.4f}), Basel={bt['basel_traffic_light']:6s}, "
                  f"Kupiec p={bt['kupiec']['p_value']:.3f}, "
                  f"Christ p={bt['christoffersen']['p_value']:.3f}, "
                  f"Trinity={status}")

    # -------------------------------------------------------
    # 8. QLIKE comparison (vol prediction quality)
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("QLIKE on RV_total (volatility prediction quality)")
    print(f"{'='*70}")

    rv_oos = rv_aligned.loc[oos_dates].values
    qlike_results = {}

    # HAR forecast
    har_oos_vals = har_forecasts.loc[oos_dates].values
    valid_har = np.isfinite(har_oos_vals) & np.isfinite(rv_oos) & (rv_oos > 0) & (har_oos_vals > 0)
    if valid_har.sum() > 10:
        ql_har = qlike(rv_oos[valid_har], har_oos_vals[valid_har])
        qlike_results['HAR-RV'] = ql_har
        print(f"  HAR-RV QLIKE:  {ql_har:.6f}")

    # GJR forecast (need to convert to σ² comparable with RV)
    gjr_oos_vals = gjr_forecasts_series.loc[oos_dates].values
    valid_gjr = np.isfinite(gjr_oos_vals) & np.isfinite(rv_oos) & (rv_oos > 0) & (gjr_oos_vals > 0)
    if valid_gjr.sum() > 10:
        ql_gjr = qlike(rv_oos[valid_gjr], gjr_oos_vals[valid_gjr])
        qlike_results['GJR-GARCH'] = ql_gjr
        print(f"  GJR-GARCH QLIKE: {ql_gjr:.6f}")

    # DM test: HAR vs GJR
    dm_results = {}
    if valid_har.sum() > 10 and valid_gjr.sum() > 10:
        common_valid = valid_har & valid_gjr
        if common_valid.sum() > 10:
            loss_har = qlike_loss_series(rv_oos[common_valid], har_oos_vals[common_valid])
            loss_gjr = qlike_loss_series(rv_oos[common_valid], gjr_oos_vals[common_valid])
            t_stat, p_val = dm_test(loss_har, loss_gjr)
            dm_results['HAR-RV_vs_GJR'] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'n_obs': int(common_valid.sum()),
                'significant': bool(abs(t_stat) > 3.0),
                'interpretation': 'HAR better' if t_stat < -3.0 else ('GJR better' if t_stat > 3.0 else 'no significant difference')
            }
            print(f"\n  DM test (QLIKE, HAR vs GJR): t={t_stat:.4f}, p={p_val:.6f}")
            print(f"    → {'HAR significantly better' if t_stat < -3.0 else 'No significant diff' if abs(t_stat) < 3.0 else 'GJR significantly better'}")

    # -------------------------------------------------------
    # 9. Average VaR level comparison
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("Average VaR Level Comparison (1%)")
    print(f"{'='*70}")

    avg_var = {}
    for method_key in method_keys:
        var_arr = var_forecasts[0.01][method_key]
        valid = np.isfinite(var_arr)
        if valid.sum() > 0:
            avg = float(np.mean(var_arr[valid]))
            avg_var[method_display[method_key]] = avg
            print(f"  {method_display[method_key]:15s}: mean VaR(1%) = {avg:.6f} ({avg*100:.3f}%)")

    # -------------------------------------------------------
    # 10. Summary
    # -------------------------------------------------------
    print(f"\n{'='*70}")
    print("SUMMARY: 1% VaR — Which method fixes 0050.TW?")
    print(f"{'='*70}")
    print(f"  {'Method':15s} {'Viol':>5s} {'Rate':>7s} {'Basel':>7s} {'Trinity':>8s}")
    print(f"  {'-'*15} {'-'*5} {'-'*7} {'-'*7} {'-'*8}")

    if '1%' in var_results:
        for method_key in method_keys:
            method_name = method_display[method_key]
            if method_name in var_results['1%'] and 'error' not in var_results['1%'][method_name]:
                bt = var_results['1%'][method_name]
                status = "PASS" if bt['trinity_pass'] else "FAIL"
                print(f"  {method_name:15s} {bt['n_violations']:5d} "
                      f"{bt['violation_rate']:7.4f} {bt['basel_traffic_light']:>7s} "
                      f"{status:>8s}")

    # Determine champion
    best_method_1pct = None
    best_violations = 999
    for method_key in method_keys:
        mn = method_display[method_key]
        if mn in var_results.get('1%', {}) and 'error' not in var_results['1%'][mn]:
            bt = var_results['1%'][mn]
            if bt['trinity_pass']:
                if bt['n_violations'] < best_violations or best_method_1pct is None:
                    best_method_1pct = mn
                    best_violations = bt['n_violations']

    if best_method_1pct is None:
        # Find closest to pass
        for method_key in method_keys:
            mn = method_display[method_key]
            if mn in var_results.get('1%', {}) and 'error' not in var_results['1%'][mn]:
                bt = var_results['1%'][mn]
                if bt['n_violations'] < best_violations:
                    best_method_1pct = mn
                    best_violations = bt['n_violations']

    conclusion_lines = []
    # Check if any HAR method achieves Trinity PASS
    har_pass = any(
        var_results.get('1%', {}).get(method_display[mk], {}).get('trinity_pass', False)
        for mk in ['har_normal', 'har_cf', 'har_histsim']
    )
    gjr_cf_pass = var_results.get('1%', {}).get('GJR+CF', {}).get('trinity_pass', False)

    if har_pass and gjr_cf_pass:
        conclusion_lines.append("Both HAR-RV and GJR+CF achieve Trinity PASS at 1%")
    elif har_pass:
        conclusion_lines.append("HAR-RV methods achieve Trinity PASS, GJR+CF does NOT — HAR-RV is BETTER")
    elif gjr_cf_pass:
        conclusion_lines.append("GJR+CF remains champion — HAR-RV methods fail Trinity at 1%")
    else:
        conclusion_lines.append("NEITHER method achieves Trinity PASS at 1% in this OOS period")

    if 'HAR-RV' in qlike_results and 'GJR-GARCH' in qlike_results:
        improvement = (qlike_results['GJR-GARCH'] - qlike_results['HAR-RV']) / qlike_results['GJR-GARCH'] * 100
        conclusion_lines.append(
            f"HAR-RV QLIKE={qlike_results['HAR-RV']:.4f} vs GJR={qlike_results['GJR-GARCH']:.4f} "
            f"({improvement:+.1f}% improvement)")

    if best_method_1pct:
        conclusion_lines.append(f"Best 1% VaR method: {best_method_1pct} ({best_violations} violations)")

    for line in conclusion_lines:
        print(f"\n  >>> {line}")

    elapsed = time.time() - t0

    # -------------------------------------------------------
    # 11. Save results
    # -------------------------------------------------------
    results = {
        'experiment_id': 'K850',
        'title': 'K850: HAR-RV based VaR for Taiwan — HAR σ vs GJR σ for 0050.TW VaR',
        'method': 'HAR-RV (TAIFEX 5-min RV) + Cornish-Fisher/Normal/HistSim vs GJR-GARCH',
        'asset': '0050.TW',
        'rv_source': 'TAIFEX TX1 tick data (5-min RV)',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'data_source': 'TAIFEX TX tick data (5-min RV) + yfinance (0050.TW returns)',
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'HAR: RV_{t-1}, RV_{t-1:5}, RV_{t-1:22} (no lookahead)',
            'GJR: recursive h[t]=f(h[t-1], r²[t-1])',
            'Date alignment: inner join (TX RV ∩ 0050.TW returns)',
        ],
        'references': [
            'Corsi (2009) - HAR-RV model, J Financial Econometrics',
            'Hansen & Lunde (2005) - 5-min RV gold standard',
            'Cornish & Fisher (1938) - CF expansion',
            'McNeil & Frey (2000) - EVT-POT for VaR, J Empirical Finance',
            'Patton (2011) - QLIKE proxy-robust, J Econometrics',
            'K836: GJR+CF Trinity PASS (3/481 at 1%)',
            'K849: HAR-RV QLIKE=0.109 vs GJR=0.202 (Track B)',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(elapsed, 1),
        'n_oos': n_oos,
        'n_common_dates': len(common_dates),
        'n_gjr_refits': n_gjr_refits,
        'oos_stats': oos_stats,
        'var_results': var_results,
        'qlike_results': qlike_results,
        'dm_test': dm_results,
        'avg_var_1pct': avg_var,
        'best_method_1pct': best_method_1pct,
        'conclusions': conclusion_lines,
    }

    results = make_serializable(results)

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to {RESULTS_PATH}")
    print(f"  Elapsed: {elapsed:.1f}s")

    return results


if __name__ == '__main__':
    main()
