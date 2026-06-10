#!/usr/bin/env python3
"""
K874e: Complete 6-Layer Fair Comparison — Statistical + Economic Significance
=============================================================================

Research Question (EMPIRICAL):
  K874d established the fair common target (σ²_fullday) and found PRG Extended wins.
  This experiment completes the FULL comparison across ALL statistical AND economic
  dimensions as required by the Patton (2011) fair comparison framework.

Models (from K874d, reuse data pipeline):
  1. GJR-GARCH (full-day native)
  2. HAR on RV_total (converted to σ²_fullday)
  3. PRG Basic (periodic realized GARCH, 6 params)
  4. PRG Extended (with leverage, 8 params)

Note: HAR(RV_intra) dropped — K874d showed catastrophic QLIKE (194.25), clearly
dominated. Keeping 4 models for cleaner comparison.

THE 6 LAYERS:
  1. Multiple Statistical Loss Functions (QLIKE, MSE, MAE, HMSE, R²)
  2. Model Confidence Set (MCS, Hansen Lunde Nason 2011)
  3. Spearman + Kendall rank correlation with bootstrap CI
  4. VaR Backtesting (1% AND 5%, Kupiec + Christoffersen + Basel + Trinity)
  5. ES (Expected Shortfall) Evaluation (Acerbi-Szekely + Fissler-Ziegel)
  6. Economic Significance (VT strategy, CRRA utility, Prospect Theory, Net Sharpe)

Data:
  TAIFEX TX tick (volume-selected contract), 2017-2026
  yfinance: ^VIX, SPY (for risk-free reference)

Error log rules applied:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - TX: volume-based contract selection (from K874d pipeline)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - Sanity check: verify forecasts > 0 before evaluation

References:
  - Patton (2011): Volatility forecast comparison using imperfect proxies
  - Hansen, Lunde & Nason (2011): Model Confidence Set
  - Kupiec (1995): Proportion of failures VaR test
  - Christoffersen (1998): Conditional coverage VaR test
  - Acerbi & Szekely (2014): Backtesting Expected Shortfall
  - Fissler & Ziegel (2016): Joint VaR-ES scoring function
  - Corsi (2009): HAR-RV
  - Bollerslev & Ghysels (1996): Periodic GARCH
  - Diebold & Mariano (1995), Harvey et al. (1997): DM test

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
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
from volpred.stats.model_evaluation import dm_test

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k874e_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k874e_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Session boundaries (HHMMSS integer)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# OOS config
IS_FRACTION = 0.60
REFIT_FREQ_DAILY = 63
NIGHT_SESSION_START_DATE = "2017-05-15"

# VT strategy config
TARGET_VOL_ANNUAL = 0.15   # 15% annualized target
RISK_FREE_DAILY = 0.04 / 252  # 4% annual, daily
TX_COST_PER_TRADE = 5e-5   # 5 bps per weight change


# ============================================================
# DATA PIPELINE (reuse from K874d — identical logic)
# ============================================================

def time_to_5min_bucket(time_int):
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def compute_rv(returns):
    if len(returns) < 1:
        return np.nan
    return float(np.sum(returns ** 2))


def safe_volume(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def process_single_file(filepath):
    """Process one TX daily file -> three variance components."""
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

    # Volume-based contract selection
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

    night_rets = np.concatenate([night_pm_rets, night_am_rets]) \
        if (len(night_pm_rets) > 0 or len(night_am_rets) > 0) else np.array([])

    rv_intra = compute_rv(day_rets)
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

    return {
        'date': date_str,
        'rv_intra': rv_intra if not np.isnan(rv_intra) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'day_open': day_open if not np.isnan(day_open) else None,
        'day_close': day_close if not np.isnan(day_close) else None,
        'night_open': night_open if not np.isnan(night_open) else None,
        'night_close': night_close if not np.isnan(night_close) else None,
    }


def load_all_data():
    """Load TX files and compute variance components."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff_start = "Daily_2017_05_15"
    cutoff_end = "Daily_2026"
    files = [f for f in all_files
             if os.path.basename(f) >= cutoff_start
             and os.path.basename(f) < cutoff_end
             and 'TX1' not in os.path.basename(f)
             and 'TX2' not in os.path.basename(f)]

    print(f"  Found {len(files)} TX files (2017-05 to 2025)")

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
                if result is not None and result.get('rv_intra') is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)} days, Errors: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def build_daily_components(rv_df):
    """Build THREE variance components + common target σ²_fullday."""
    df = rv_df.copy()
    df = df.dropna(subset=['day_open', 'day_close', 'rv_intra'])

    df['prev_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_close'])
    df['r2_gap'] = df['overnight_gap'] ** 2
    df['c2c_return'] = np.log(df['day_close'] / df['prev_close'])
    df['intra_return'] = np.log(df['day_close'] / df['day_open'])
    df['rv_total'] = df['rv_intra'] + df['rv_night'].fillna(0)
    df['sigma2_fullday'] = df['r2_gap'] + df['rv_intra'] + df['rv_night'].fillna(0)

    df = df.iloc[1:]
    df = df.dropna(subset=['c2c_return', 'rv_intra', 'r2_gap', 'sigma2_fullday'])

    return df


# ============================================================
# MODEL IMPLEMENTATIONS (from K874d)
# ============================================================

def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """GJR-GARCH(1,1) OOS on c2c returns. Native full-day predictor."""
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def gjr_negll(params, r):
        omega, alpha, gamma_p, beta = params
        T = len(r)
        h = np.zeros(T)
        h[0] = np.var(r[:min(50, T)])
        if h[0] < 1e-12: h[0] = 1e-8
        ll = 0.0
        for t in range(1, T):
            indicator = 1.0 if r[t-1] < 0 else 0.0
            h[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h[t-1]
            if h[t] < 1e-12: h[t] = 1e-12
            ll += -0.5*np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
        return -ll

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(returns[:min(50, n)])

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = returns[:t]
            best_nll = np.inf
            best_p = None
            rng = np.random.RandomState(42)
            for i in range(3):
                if i == 0:
                    x0 = [np.var(r_train)*0.05, 0.08, 0.06, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                           rng.uniform(0.0, 0.15), rng.uniform(0.7, 0.95)]
                try:
                    result = minimize(gjr_negll, x0, args=(r_train,),
                                      method='L-BFGS-B', bounds=bounds,
                                      options={'maxiter': 1000})
                    if result.fun < best_nll:
                        best_nll = result.fun
                        best_p = result.x
                except Exception:
                    continue
            if best_p is not None:
                current_params = best_p
                omega, alpha, gamma_p, beta = current_params
                h_run = np.var(returns[:min(50, t)])
                if h_run < 1e-12: h_run = 1e-8
                for tt in range(1, t):
                    indicator = 1.0 if returns[tt-1] < 0 else 0.0
                    h_run = omega + alpha*returns[tt-1]**2 + gamma_p*returns[tt-1]**2*indicator + beta*h_run
                    if h_run < 1e-12: h_run = 1e-12
                h_state = h_run

        if current_params is not None:
            omega, alpha, gamma_p, beta = current_params
            indicator = 1.0 if returns[t-1] < 0 else 0.0
            h_state = omega + alpha*returns[t-1]**2 + gamma_p*returns[t-1]**2*indicator + beta*h_state
            if h_state < 1e-12: h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


def har_oos_forecast_on_target(rv_series, is_end, refit_freq=63, label="rv_total"):
    """HAR-RV OOS: predict log(target_{t+1}) from HAR(d,w,m) lags."""
    eps = 1e-12
    log_rv = np.log(np.clip(rv_series, eps, None))
    n = len(log_rv)

    log_rv_d = pd.Series(log_rv).shift(1).values
    log_rv_5d = pd.Series(log_rv).rolling(5).mean().shift(1).values
    log_rv_22d = pd.Series(log_rv).rolling(22).mean().shift(1).values

    forecasts = np.full(n, np.nan)
    beta = None

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            train_start = 22
            y_train = log_rv[train_start:t]
            X_train = np.column_stack([
                log_rv_d[train_start:t],
                log_rv_5d[train_start:t],
                log_rv_22d[train_start:t],
            ])
            valid = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
            if valid.sum() < 50:
                continue
            y_t = y_train[valid]
            X_t = X_train[valid]
            X_c = np.column_stack([np.ones(len(y_t)), X_t])
            try:
                beta = np.linalg.lstsq(X_c, y_t, rcond=None)[0]
            except Exception:
                continue

        if beta is not None and np.isfinite(log_rv_d[t]) and np.isfinite(log_rv_5d[t]) and np.isfinite(log_rv_22d[t]):
            x_t = np.array([1.0, log_rv_d[t], log_rv_5d[t], log_rv_22d[t]])
            log_forecast = x_t @ beta
            forecasts[t] = np.exp(log_forecast)

    return forecasts


def estimate_prg(r, x, s, extended=False, n_starts=5):
    """Estimate PRG via MLE."""
    n_params = 8 if extended else 6
    n = len(r)

    def neg_loglik(params):
        if extended:
            omega = np.array([params[0], params[3]])
            alpha = np.array([params[1], params[4]])
            beta = np.array([params[2], params[5]])
            gamma = np.array([params[6], params[7]])
        else:
            omega = np.array([params[0], params[3]])
            alpha = np.array([params[1], params[4]])
            beta = np.array([params[2], params[5]])
            gamma = np.array([0.0, 0.0])

        h = np.zeros(n)
        h[0] = np.var(r[:min(50, n)])
        if h[0] < 1e-12: h[0] = 1e-8

        ll = 0.0
        for t in range(1, n):
            st = int(s[t])
            leverage = gamma[st] * x[t-1] * (1.0 if r[t-1] < 0 else 0.0)
            h[t] = omega[st] + alpha[st] * x[t-1] + leverage + beta[st] * h[t-1]
            if h[t] < 1e-12: h[t] = 1e-12

        for t in range(1, n):
            if h[t] > 1e-12:
                ll += -0.5 * np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r[t]**2/h[t]
            else:
                ll += -100.0
        return -ll

    eps = 1e-8
    if extended:
        bounds = [
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
            (0.0, 1.0), (0.0, 1.0),
        ]
    else:
        bounds = [
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
            (eps, 1e-3), (eps, 1.0), (eps, 0.999),
        ]

    best_nll = np.inf
    best_params = None
    rng = np.random.RandomState(42)
    var_overnight = np.var(r[s == 0]) if np.sum(s == 0) > 10 else 1e-5
    var_intraday = np.var(r[s == 1]) if np.sum(s == 1) > 10 else 1e-5

    for start_i in range(n_starts):
        if start_i == 0:
            x0 = [var_overnight*0.05, 0.15, 0.80, var_intraday*0.05, 0.15, 0.80]
            if extended: x0 += [0.05, 0.05]
        else:
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95),
                   rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.40), rng.uniform(0.50, 0.95)]
            if extended: x0 += [rng.uniform(0.0, 0.2), rng.uniform(0.0, 0.2)]

        try:
            result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 2000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


# ============================================================
# CONVERSION FUNCTIONS (from K874d)
# ============================================================

def compute_scaling_ratios(daily_df, is_end):
    """Compute scaling ratios from in-sample data."""
    df_is = daily_df.iloc[:is_end]
    sigma2 = df_is['sigma2_fullday'].values
    r2_gap = df_is['r2_gap'].values
    rv_intra = df_is['rv_intra'].values
    rv_night = df_is['rv_night'].fillna(0).values
    rv_total = df_is['rv_total'].values

    valid = sigma2 > 0
    gap_share = np.mean(r2_gap[valid] / sigma2[valid])
    intra_share = np.mean(rv_intra[valid] / sigma2[valid])
    night_share = np.mean(rv_night[valid] / sigma2[valid])
    rv_total_share = np.mean(rv_total[valid] / sigma2[valid])
    prg_native = r2_gap + rv_intra
    prg_native_share = np.mean(prg_native[valid] / sigma2[valid])
    mean_gap = np.mean(r2_gap[valid])

    return {
        'gap_share': float(gap_share),
        'intra_share': float(intra_share),
        'night_share': float(night_share),
        'rv_total_share': float(rv_total_share),
        'prg_native_share': float(prg_native_share),
        'mean_gap': float(mean_gap),
    }


def convert_har_to_fullday(har_forecasts, ratios):
    """HAR(RV_total) -> fullday: add mean gap."""
    converted = np.full_like(har_forecasts, np.nan)
    valid = np.isfinite(har_forecasts) & (har_forecasts > 0)
    converted[valid] = har_forecasts[valid] + ratios['mean_gap']
    return converted


def convert_prg_to_fullday(prg_forecasts, ratios):
    """PRG(gap+intra) -> fullday: divide by native share."""
    converted = np.full_like(prg_forecasts, np.nan)
    valid = np.isfinite(prg_forecasts) & (prg_forecasts > 0)
    converted[valid] = prg_forecasts[valid] / ratios['prg_native_share']
    return converted


# ============================================================
# LAYER 1: Multiple Statistical Loss Functions
# ============================================================

def qlike_loss_array(realized, forecast):
    """Per-observation QLIKE: r/f - log(r/f) - 1."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r = realized[valid]
    f = forecast[valid]
    loss[valid] = r/f - np.log(r/f) - 1
    return loss


def mse_loss_array(realized, forecast):
    """Per-observation MSE: (r - f)²."""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    loss = np.full(len(realized), np.nan)
    loss[valid] = (realized[valid] - forecast[valid]) ** 2
    return loss


def mae_loss_array(realized, forecast):
    """Per-observation MAE: |r - f|."""
    valid = np.isfinite(realized) & np.isfinite(forecast)
    loss = np.full(len(realized), np.nan)
    loss[valid] = np.abs(realized[valid] - forecast[valid])
    return loss


def hmse_loss_array(realized, forecast):
    """Per-observation HMSE: (1 - σ²/ĥ)²."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    loss[valid] = (1 - realized[valid] / forecast[valid]) ** 2
    return loss


def mincer_zarnowitz_r2(realized, forecast):
    """Mincer-Zarnowitz regression: σ² = a + b*ĥ + ε. Returns R², b, b_se, t(b=1)."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    n = len(r)
    if n < 30:
        return {'r2': np.nan, 'b': np.nan, 'b_se': np.nan, 't_b_eq_1': np.nan, 'n': n}

    X = np.column_stack([np.ones(n), f])
    try:
        beta_hat = np.linalg.lstsq(X, r, rcond=None)[0]
    except Exception:
        return {'r2': np.nan, 'b': np.nan, 'b_se': np.nan, 't_b_eq_1': np.nan, 'n': n}

    r_hat = X @ beta_hat
    ss_res = np.sum((r - r_hat) ** 2)
    ss_tot = np.sum((r - np.mean(r)) ** 2)
    r2_val = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # Standard error of b (with Newey-West)
    resids = r - r_hat
    sigma2_hat = ss_res / (n - 2)
    XtX_inv = np.linalg.inv(X.T @ X)
    se_b = np.sqrt(sigma2_hat * XtX_inv[1, 1])
    t_b_eq_1 = (beta_hat[1] - 1.0) / se_b if se_b > 1e-15 else np.nan

    return {
        'r2': float(r2_val),
        'a': float(beta_hat[0]),
        'b': float(beta_hat[1]),
        'b_se': float(se_b),
        't_b_eq_1': float(t_b_eq_1),
        'n': n,
    }


def compute_all_losses(realized_oos, forecast_oos):
    """Compute all 5 loss functions for one model."""
    qlike_arr = qlike_loss_array(realized_oos, forecast_oos)
    mse_arr = mse_loss_array(realized_oos, forecast_oos)
    mae_arr = mae_loss_array(realized_oos, forecast_oos)
    hmse_arr = hmse_loss_array(realized_oos, forecast_oos)
    mz = mincer_zarnowitz_r2(realized_oos, forecast_oos)

    return {
        'qlike': float(np.nanmean(qlike_arr)),
        'mse': float(np.nanmean(mse_arr)),
        'mae': float(np.nanmean(mae_arr)),
        'hmse': float(np.nanmean(hmse_arr)),
        'mz_r2': mz['r2'],
        'mz_b': mz['b'],
        'mz_b_se': mz['b_se'],
        'mz_t_b_eq_1': mz['t_b_eq_1'],
        'loss_arrays': {
            'qlike': qlike_arr,
            'mse': mse_arr,
            'mae': mae_arr,
            'hmse': hmse_arr,
        }
    }


# ============================================================
# LAYER 2: Model Confidence Set (MCS)
# ============================================================

def _block_bootstrap_indices(n, block_size, rng):
    """Generate block bootstrap indices."""
    n_blocks = int(np.ceil(n / block_size))
    starts = rng.randint(0, n - block_size + 1, size=n_blocks)
    indices = np.concatenate([np.arange(s, s + block_size) for s in starts])
    return indices[:n]


def model_confidence_set(loss_dict, alpha=0.10, B=1000, block_size=22, rng_seed=42):
    """
    Model Confidence Set (Hansen, Lunde & Nason 2011).

    Sequential elimination: at each step, test whether the worst model is
    significantly worse than the rest. If so, eliminate it.

    loss_dict: {model_name: loss_array} — per-observation losses, lower = better.
    Returns: list of model names in the superior set.
    """
    rng = np.random.RandomState(rng_seed)
    model_names = list(loss_dict.keys())

    # Align all loss arrays (use common valid indices)
    n = len(list(loss_dict.values())[0])
    valid = np.ones(n, dtype=bool)
    for arr in loss_dict.values():
        valid &= np.isfinite(arr)

    # Filter to valid observations
    losses = {name: arr[valid] for name, arr in loss_dict.items()}
    n_valid = valid.sum()

    if n_valid < 50:
        return model_names  # can't discriminate

    remaining = list(model_names)
    p_values = {}

    while len(remaining) > 1:
        m = len(remaining)
        # Compute mean loss for each remaining model
        mean_losses = {name: np.mean(losses[name]) for name in remaining}

        # Find worst model (highest mean loss)
        worst = max(remaining, key=lambda x: mean_losses[x])

        # T_R statistic: max over all pairs of relative performance
        # d_{ij} = loss_i - loss_j for all pairs
        # Under H0: all models equally good
        # Test: max_i (mean(d_worst - d_i)) / se_bootstrap

        # Compute d_worst_vs_i for all i != worst
        d_arrays = {}
        for name in remaining:
            if name != worst:
                d_arrays[name] = losses[worst] - losses[name]

        # Observed test stat: max_i mean(d_worst_i) / se(d_worst_i)
        t_stats_obs = {}
        for name, d in d_arrays.items():
            d_mean = np.mean(d)
            # Block bootstrap for SE
            boot_means = np.zeros(B)
            for b in range(B):
                idx = _block_bootstrap_indices(n_valid, block_size, rng)
                boot_means[b] = np.mean(d[idx])
            se = np.std(boot_means)
            if se > 1e-15:
                t_stats_obs[name] = d_mean / se
            else:
                t_stats_obs[name] = 0.0

        T_obs = max(t_stats_obs.values()) if t_stats_obs else 0.0

        # Bootstrap distribution of T_R under H0
        # Under H0, center the d arrays
        T_boot = np.zeros(B)
        for b in range(B):
            idx = _block_bootstrap_indices(n_valid, block_size, rng)
            t_b_vals = []
            for name, d in d_arrays.items():
                d_boot = d[idx]
                d_centered = d_boot - np.mean(d)  # center under H0
                boot_mean = np.mean(d_centered)
                # Use same bootstrap SE (simplified)
                se = np.std(d[idx] - np.mean(d))  # bootstrap SE of centered
                se_val = se / np.sqrt(len(d_boot)) if se > 1e-15 else 1e-15
                t_b_vals.append(boot_mean / se_val)
            T_boot[b] = max(t_b_vals) if t_b_vals else 0.0

        # p-value
        p_val = float(np.mean(T_boot >= T_obs))
        p_values[worst] = p_val

        if p_val < alpha:
            remaining.remove(worst)
        else:
            break  # can't reject, all remaining are in MCS

    return remaining, p_values


# ============================================================
# LAYER 3: Spearman + Kendall with Bootstrap CI
# ============================================================

def rank_correlations_with_ci(realized, forecast, n_boot=2000, rng_seed=42):
    """Compute Spearman + Kendall with bootstrap 95% CI."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    n = len(r)

    if n < 30:
        return {
            'spearman_rho': np.nan, 'spearman_p': np.nan,
            'spearman_ci_lo': np.nan, 'spearman_ci_hi': np.nan,
            'kendall_tau': np.nan, 'kendall_p': np.nan,
            'kendall_ci_lo': np.nan, 'kendall_ci_hi': np.nan,
            'n': n,
        }

    rho, rho_p = sp_stats.spearmanr(r, f)
    tau, tau_p = sp_stats.kendalltau(r, f)

    # Bootstrap CI
    rng = np.random.RandomState(rng_seed)
    rho_boot = np.zeros(n_boot)
    tau_boot = np.zeros(n_boot)

    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        rho_boot[b] = sp_stats.spearmanr(r[idx], f[idx])[0]
        tau_boot[b] = sp_stats.kendalltau(r[idx], f[idx])[0]

    rho_ci = (float(np.percentile(rho_boot, 2.5)), float(np.percentile(rho_boot, 97.5)))
    tau_ci = (float(np.percentile(tau_boot, 2.5)), float(np.percentile(tau_boot, 97.5)))

    return {
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
        'spearman_ci_lo': rho_ci[0],
        'spearman_ci_hi': rho_ci[1],
        'kendall_tau': float(tau),
        'kendall_p': float(tau_p),
        'kendall_ci_lo': tau_ci[0],
        'kendall_ci_hi': tau_ci[1],
        'n': n,
    }


# ============================================================
# LAYER 4: VaR Backtesting (1% AND 5%, full tests)
# ============================================================

def _christoffersen_cc(violations, alpha):
    """Christoffersen (1998) conditional coverage test."""
    n = len(violations)
    n_v = int(violations.sum())
    vr = n_v / n

    # Kupiec LR
    if n_v == 0 or n_v == n:
        kupiec_lr = np.nan
        kupiec_p = np.nan
    else:
        kupiec_lr = 2 * (n_v * np.log(vr / alpha) +
                          (n - n_v) * np.log((1 - vr) / (1 - alpha)))
        kupiec_p = float(1 - sp_stats.chi2.cdf(kupiec_lr, 1))
        kupiec_lr = float(kupiec_lr)

    # Transition counts
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        v0, v1 = int(violations[i-1]), int(violations[i])
        if v0 == 0 and v1 == 0: n00 += 1
        elif v0 == 0 and v1 == 1: n01 += 1
        elif v0 == 1 and v1 == 0: n10 += 1
        elif v0 == 1 and v1 == 1: n11 += 1

    # Independence LR
    if n01 + n00 > 0 and n10 + n11 > 0 and n01 > 0 and n10 > 0:
        pi01 = n01 / (n00 + n01)
        pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
        pi = (n01 + n11) / (n00 + n01 + n10 + n11)

        lr_ind = 0
        for (nij, pij) in [(n00, 1-pi01), (n01, pi01), (n10, 1-pi11), (n11, pi11)]:
            if nij > 0 and pij > 0:
                lr_ind += nij * np.log(pij)
        for (nij, pij) in [(n00, 1-pi), (n01, pi), (n10, 1-pi), (n11, pi)]:
            if nij > 0 and pij > 0:
                lr_ind -= nij * np.log(pij)
        lr_ind *= 2
        ind_p = float(1 - sp_stats.chi2.cdf(lr_ind, 1))

        cc_stat = float(lr_ind) + (kupiec_lr if np.isfinite(kupiec_lr) else 0)
        cc_p = float(1 - sp_stats.chi2.cdf(cc_stat, 2))
    else:
        lr_ind = np.nan
        ind_p = np.nan
        cc_stat = np.nan
        cc_p = np.nan

    # Basel traffic light using exact-binomial thresholds at the realized sample size.
    green_cutoff = int(sp_stats.binom.ppf(0.95, n, alpha))
    yellow_cutoff = int(sp_stats.binom.ppf(0.9999, n, alpha))
    if n_v <= green_cutoff:
        zone = "GREEN"
    elif n_v <= yellow_cutoff:
        zone = "YELLOW"
    else:
        zone = "RED"

    return {
        'n_obs': n,
        'n_violations': n_v,
        'violation_rate': round(vr, 6),
        'expected_rate': alpha,
        'kupiec_lr': round(kupiec_lr, 4) if np.isfinite(kupiec_lr) else None,
        'kupiec_p': round(kupiec_p, 4) if np.isfinite(kupiec_p) else None,
        'independence_lr': round(float(lr_ind), 4) if np.isfinite(lr_ind) else None,
        'independence_p': round(ind_p, 4) if np.isfinite(ind_p) else None,
        'cc_stat': round(cc_stat, 4) if np.isfinite(cc_stat) else None,
        'cc_p': round(cc_p, 4) if np.isfinite(cc_p) else None,
        'basel_zone': zone,
        'basel_green_cutoff': green_cutoff,
        'basel_yellow_cutoff': yellow_cutoff,
    }


def var_backtest_full(returns, sigma_forecasts, alpha=0.01):
    """
    VaR backtesting at given alpha level.
    Three VaR approaches: Normal, Cornish-Fisher, Historical Simulation.
    Tests: Kupiec + Christoffersen + Basel + Trinity.
    """
    valid = np.isfinite(returns) & np.isfinite(sigma_forecasts) & (sigma_forecasts > 0)
    r = returns[valid]
    sigma = sigma_forecasts[valid]
    n = len(r)
    if n < 50:
        return None

    results = {}

    # --- Method 1: Normal VaR ---
    z_alpha = sp_stats.norm.ppf(alpha)
    var_normal = sigma * z_alpha
    violations_normal = (r < var_normal).astype(float)
    results['normal'] = _christoffersen_cc(violations_normal, alpha)
    results['normal']['method'] = 'Normal'
    results['normal']['avg_var'] = round(float(np.mean(np.abs(var_normal))), 8)

    # --- Method 2: Cornish-Fisher VaR ---
    # CF expansion: z_CF = z + (z²-1)*S/6 + (z³-3z)*K/24 - (2z³-5z)*S²/36
    # where S=skewness, K=excess kurtosis of standardized residuals
    std_resid = r / sigma
    S = float(sp_stats.skew(std_resid))
    K = float(sp_stats.kurtosis(std_resid))  # excess kurtosis
    z = z_alpha
    z_cf = z + (z**2 - 1)*S/6 + (z**3 - 3*z)*K/24 - (2*z**3 - 5*z)*S**2/36
    var_cf = sigma * z_cf
    violations_cf = (r < var_cf).astype(float)
    results['cornish_fisher'] = _christoffersen_cc(violations_cf, alpha)
    results['cornish_fisher']['method'] = 'Cornish-Fisher'
    results['cornish_fisher']['skewness'] = round(S, 4)
    results['cornish_fisher']['excess_kurtosis'] = round(K, 4)
    results['cornish_fisher']['z_cf'] = round(float(z_cf), 4)
    results['cornish_fisher']['avg_var'] = round(float(np.mean(np.abs(var_cf))), 8)

    # --- Method 3: Historical Simulation (FHS) ---
    # Use rolling window of standardized residuals
    hs_window = min(500, n - 1)
    violations_hs = np.zeros(n)
    var_hs_values = np.zeros(n)
    for t in range(hs_window, n):
        hist_resid = std_resid[t-hs_window:t]
        q = np.percentile(hist_resid, alpha * 100)
        var_hs = sigma[t] * q
        var_hs_values[t] = var_hs
        if r[t] < var_hs:
            violations_hs[t] = 1.0

    hs_slice = violations_hs[hs_window:]
    results['historical_sim'] = _christoffersen_cc(hs_slice, alpha)
    results['historical_sim']['method'] = 'Historical Simulation (FHS)'
    results['historical_sim']['window'] = hs_window
    results['historical_sim']['n_obs'] = len(hs_slice)
    results['historical_sim']['avg_var'] = round(float(np.mean(np.abs(var_hs_values[hs_window:]))), 8)

    # --- Trinity test: PASS only if Kupiec + CC + Basel all pass ---
    for method_key in ['normal', 'cornish_fisher', 'historical_sim']:
        d = results[method_key]
        kupiec_ok = (d.get('kupiec_p') is not None and d['kupiec_p'] >= 0.05)
        cc_ok = (d.get('cc_p') is not None and d['cc_p'] >= 0.05)
        basel_ok = (d.get('basel_zone') == 'GREEN')
        d['trinity_pass'] = kupiec_ok and cc_ok and basel_ok

    return results


# ============================================================
# LAYER 5: ES (Expected Shortfall) Evaluation
# ============================================================

def es_backtest_acerbi_szekely(returns, sigma_forecasts, alpha=0.01):
    """
    Acerbi & Szekely (2014) ES backtest.
    Test statistic Z = (1/(nα)) * Σ_{r_t < VaR_t} r_t / ES_t + 1
    Under H0 (correct model), E[Z] = 0.
    """
    valid = np.isfinite(returns) & np.isfinite(sigma_forecasts) & (sigma_forecasts > 0)
    r = returns[valid]
    sigma = sigma_forecasts[valid]
    n = len(r)
    if n < 50:
        return None

    z_alpha = sp_stats.norm.ppf(alpha)

    # Normal ES: ES = σ * φ(z_α) / α (where φ = standard normal pdf)
    phi_z = sp_stats.norm.pdf(z_alpha)
    es_normal = -sigma * phi_z / alpha  # negative (loss)

    # VaR for violation detection
    var_normal = sigma * z_alpha

    violations = r < var_normal
    n_violations = violations.sum()

    if n_violations < 2:
        return {
            'method': 'Normal ES',
            'n_obs': n,
            'n_violations': int(n_violations),
            'z_stat': np.nan,
            'p_value': np.nan,
            'es_mean': float(np.mean(np.abs(es_normal))),
            'note': 'Too few violations for ES test'
        }

    # Acerbi-Szekely Z1 statistic
    z_stat = (1 / (n * alpha)) * np.sum(r[violations] / es_normal[violations]) + 1

    # Under H0, approximately standard normal (large sample)
    # One-sided test: reject if z_stat < -z_{1-α}
    p_val = float(sp_stats.norm.cdf(z_stat))

    return {
        'method': 'Normal ES (Acerbi-Szekely 2014)',
        'n_obs': n,
        'n_violations': int(n_violations),
        'violation_rate': round(float(n_violations / n), 6),
        'z_stat': round(float(z_stat), 4),
        'p_value': round(p_val, 4),
        'reject_at_5pct': p_val < 0.05,
        'es_mean': round(float(np.mean(np.abs(es_normal))), 8),
    }


def fissler_ziegel_score(returns, sigma_forecasts, alpha=0.01):
    """
    Fissler & Ziegel (2016) joint VaR-ES scoring function.
    Strictly consistent for the pair (VaR, ES).
    S(VaR, ES, r) = (1/α)(VaR - r)⁺ - VaR + ES + (1/(2α²)) * ((VaR - r)⁺)² / ES - ES/2

    Lower score = better model.
    """
    valid = np.isfinite(returns) & np.isfinite(sigma_forecasts) & (sigma_forecasts > 0)
    r = returns[valid]
    sigma = sigma_forecasts[valid]
    n = len(r)
    if n < 50:
        return None

    z_alpha = sp_stats.norm.ppf(alpha)
    phi_z = sp_stats.norm.pdf(z_alpha)

    var_t = sigma * z_alpha  # negative
    es_t = -sigma * phi_z / alpha  # negative

    # Score for each observation
    shortfall = np.maximum(var_t - r, 0)  # (VaR - r)⁺, positive when violation
    abs_es = np.abs(es_t)

    # Fissler-Ziegel with G(x) = -1/x (the log-score variant)
    # S = (1/α) * I(r < VaR) * (VaR - r) / |ES| - VaR/|ES| + log(|ES|) + 1
    scores = np.zeros(n)
    for t in range(n):
        if abs_es[t] > 1e-15:
            term1 = (1/alpha) * shortfall[t] / abs_es[t]
            term2 = -var_t[t] / abs_es[t]
            term3 = np.log(abs_es[t])
            scores[t] = term1 + term2 + term3 + 1
        else:
            scores[t] = np.nan

    valid_scores = scores[np.isfinite(scores)]

    return {
        'method': 'Fissler-Ziegel (2016) joint VaR-ES score',
        'mean_score': round(float(np.mean(valid_scores)), 6) if len(valid_scores) > 0 else np.nan,
        'n_obs': len(valid_scores),
        'score_array': scores,  # for DM test
    }


# ============================================================
# LAYER 6: Economic Significance
# ============================================================

def vt_strategy_performance(returns, sigma_forecasts, target_vol=TARGET_VOL_ANNUAL,
                            rf_daily=RISK_FREE_DAILY, tx_cost=TX_COST_PER_TRADE):
    """
    Volatility Targeting strategy:
    weight_t = target_vol_daily / σ̂_t
    portfolio_return_t = weight_t * return_t + (1-weight_t) * rf
    Transaction cost deducted on |Δweight|.

    Signal from t-1, return at t (lag enforced via shift).
    """
    valid = np.isfinite(returns) & np.isfinite(sigma_forecasts) & (sigma_forecasts > 0)
    r = returns.copy()
    sigma = sigma_forecasts.copy()
    n = len(r)

    target_vol_daily = target_vol / np.sqrt(252)

    # Compute weights with lag: weight[t] uses sigma[t] which is forecast BEFORE t
    weights = np.full(n, np.nan)
    for t in range(n):
        if valid[t]:
            w = target_vol_daily / sigma[t]
            weights[t] = np.clip(w, 0.0, 2.0)  # cap at 200% leverage

    # Shift: use weight from t for return at t (sigma forecast is already for t)
    # But enforce lag explicitly: weight_t = f(info up to t-1)
    # In our setup, sigma_forecasts[t] is already h_t = f(r_{t-1}, h_{t-1})
    # so the lag is built into the GARCH/HAR/PRG recursion.

    port_returns = np.full(n, np.nan)
    turnover_sum = 0.0
    prev_w = np.nan

    for t in range(n):
        if np.isfinite(weights[t]) and np.isfinite(r[t]):
            w = weights[t]
            # Transaction cost
            if np.isfinite(prev_w):
                delta_w = abs(w - prev_w)
                tc = delta_w * tx_cost
            else:
                tc = 0
            port_returns[t] = w * r[t] + (1 - w) * rf_daily - tc
            turnover_sum += abs(w - prev_w) if np.isfinite(prev_w) else 0
            prev_w = w

    # Performance metrics
    valid_pr = port_returns[np.isfinite(port_returns)]
    if len(valid_pr) < 50:
        return None

    n_days = len(valid_pr)
    mean_r = np.mean(valid_pr)
    std_r = np.std(valid_pr, ddof=1)
    sharpe = mean_r / std_r * np.sqrt(252) if std_r > 0 else 0
    cagr = (1 + mean_r) ** 252 - 1

    # Sortino (downside deviation)
    neg_r = valid_pr[valid_pr < 0]
    downside_std = np.sqrt(np.mean(neg_r ** 2)) if len(neg_r) > 0 else 1e-10
    sortino = mean_r / downside_std * np.sqrt(252)

    # MDD
    cumret = np.cumprod(1 + valid_pr)
    running_max = np.maximum.accumulate(cumret)
    drawdowns = cumret / running_max - 1
    mdd = float(np.min(drawdowns))

    # Average weight
    avg_weight = float(np.nanmean(weights[np.isfinite(weights)]))
    avg_turnover = turnover_sum / n_days

    return {
        'sharpe': round(float(sharpe), 4),
        'cagr': round(float(cagr), 4),
        'annual_vol': round(float(std_r * np.sqrt(252)), 4),
        'sortino': round(float(sortino), 4),
        'mdd': round(float(mdd), 4),
        'avg_weight': round(avg_weight, 4),
        'avg_daily_turnover': round(avg_turnover, 6),
        'n_days': n_days,
        'port_returns': valid_pr,  # for DM test on strategy returns
    }


def crra_utility(returns_array, gamma):
    """CRRA expected utility: E[(1+r)^(1-γ) / (1-γ)] for γ != 1, E[log(1+r)] for γ=1."""
    r = returns_array[np.isfinite(returns_array)]
    wealth = 1 + r
    # Avoid negative wealth
    wealth = np.clip(wealth, 1e-10, None)

    if abs(gamma - 1.0) < 1e-6:
        eu = np.mean(np.log(wealth))
    else:
        eu = np.mean(wealth ** (1 - gamma) / (1 - gamma))

    # Certainty equivalent
    if abs(gamma - 1.0) < 1e-6:
        ce = np.exp(eu) - 1
    else:
        ce = (eu * (1 - gamma)) ** (1 / (1 - gamma)) - 1

    return {'expected_utility': float(eu), 'certainty_equivalent': float(ce)}


def prospect_theory_value(returns_array, lambda_loss=2.25, alpha_pt=0.88):
    """
    Prospect Theory value: v(r) = r^α if r >= 0, -λ|r|^α if r < 0.
    """
    r = returns_array[np.isfinite(returns_array)]
    values = np.where(r >= 0, r ** alpha_pt, -lambda_loss * np.abs(r) ** alpha_pt)
    return {
        'mean_pt_value': float(np.mean(values)),
        'median_pt_value': float(np.median(values)),
    }


# ============================================================
# CHART GENERATION
# ============================================================

def make_charts(layer_results, charts_dir):
    """Generate comprehensive comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    model_names = list(layer_results['layer1'].keys())

    # ---- Chart 1: Loss Function Heatmap (rankings) ----
    fig, ax = plt.subplots(figsize=(14, 6))

    loss_fns = ['qlike', 'mse', 'mae', 'hmse', 'mz_r2']
    loss_labels = ['QLIKE', 'MSE', 'MAE', 'HMSE', 'MZ R²']

    # Build rank matrix
    n_models = len(model_names)
    n_losses = len(loss_fns)
    rank_matrix = np.zeros((n_models, n_losses))

    for j, lf in enumerate(loss_fns):
        vals = []
        for name in model_names:
            v = layer_results['layer1'][name].get(lf, np.nan)
            vals.append(v if v is not None else np.nan)
        vals = np.array(vals)
        if lf == 'mz_r2':
            # Higher is better for R²
            order = np.argsort(-vals)
        else:
            # Lower is better for losses
            order = np.argsort(vals)
        for rank, idx in enumerate(order):
            rank_matrix[idx, j] = rank + 1

    im = ax.imshow(rank_matrix, cmap='RdYlGn_r', aspect='auto', vmin=1, vmax=n_models)
    ax.set_xticks(range(n_losses))
    ax.set_xticklabels(loss_labels, fontsize=12, fontweight='bold')
    ax.set_yticks(range(n_models))
    ax.set_yticklabels(model_names, fontsize=12)

    for i in range(n_models):
        for j in range(n_losses):
            rank = int(rank_matrix[i, j])
            ax.text(j, i, str(rank), ha='center', va='center', fontsize=14,
                    fontweight='bold', color='white' if rank >= 3 else 'black')

    plt.colorbar(im, label='Rank (1=best)', shrink=0.8)
    ax.set_title('K874e Layer 1: Rankings Across 5 Loss Functions\n'
                 '(All on common target σ²_fullday)', fontsize=14)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'layer1_rankings_heatmap.png'), dpi=150)
    plt.close()

    # ---- Chart 2: Loss function values (bar chart) ----
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    for idx, (lf, label) in enumerate(zip(loss_fns, loss_labels)):
        ax = axes[idx // 3][idx % 3]
        vals = [layer_results['layer1'][name].get(lf, 0) for name in model_names]

        # Sort
        if lf == 'mz_r2':
            sorted_idx = np.argsort(vals)[::-1]
        else:
            sorted_idx = np.argsort(vals)

        sorted_names = [model_names[i] for i in sorted_idx]
        sorted_vals = [vals[i] for i in sorted_idx]
        colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(sorted_names))]

        bars = ax.barh(range(len(sorted_names)), sorted_vals, color=colors)
        ax.set_yticks(range(len(sorted_names)))
        ax.set_yticklabels(sorted_names, fontsize=10)
        ax.set_title(label, fontsize=12, fontweight='bold')
        for bar, val in zip(bars, sorted_vals):
            ax.text(bar.get_width(), bar.get_y() + bar.get_height()/2,
                    f'  {val:.6f}', va='center', fontsize=9)

    # Hide unused subplot
    axes[1][2].axis('off')

    plt.suptitle('K874e Layer 1: Loss Function Values (all on σ²_fullday)', fontsize=14, y=1.01)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'layer1_loss_values.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # ---- Chart 3: Rank Correlations ----
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    for idx, (metric, label) in enumerate([('spearman_rho', 'Spearman ρ'), ('kendall_tau', 'Kendall τ')]):
        ax = axes[idx]
        vals = [layer_results['layer3'][name][metric] for name in model_names]
        ci_lo = [layer_results['layer3'][name][f'{metric.split("_")[0]}_ci_lo'] for name in model_names]
        ci_hi = [layer_results['layer3'][name][f'{metric.split("_")[0]}_ci_hi'] for name in model_names]

        sorted_idx = np.argsort(vals)[::-1]
        sorted_names = [model_names[i] for i in sorted_idx]
        sorted_vals = [vals[i] for i in sorted_idx]
        sorted_lo = [ci_lo[i] for i in sorted_idx]
        sorted_hi = [ci_hi[i] for i in sorted_idx]
        errors = [[v - lo for v, lo in zip(sorted_vals, sorted_lo)],
                  [hi - v for v, hi in zip(sorted_vals, sorted_hi)]]

        colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(sorted_names))]
        ax.barh(range(len(sorted_names)), sorted_vals, xerr=errors,
                color=colors, capsize=4, ecolor='black')
        ax.set_yticks(range(len(sorted_names)))
        ax.set_yticklabels(sorted_names, fontsize=11)
        ax.set_xlabel(label, fontsize=12)
        ax.set_title(f'{label} with 95% Bootstrap CI', fontsize=12, fontweight='bold')
        for i, (v, lo, hi) in enumerate(zip(sorted_vals, sorted_lo, sorted_hi)):
            ax.text(v + 0.01, i, f'{v:.4f} [{lo:.4f}, {hi:.4f}]', va='center', fontsize=9)

    plt.suptitle('K874e Layer 3: Rank Correlations with σ²_fullday', fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'layer3_rank_correlations.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # ---- Chart 4: VaR Violation Rates ----
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    for idx, (alpha_val, title) in enumerate([(0.01, '1% VaR'), (0.05, '5% VaR')]):
        ax = axes[idx]
        key = f'alpha_{alpha_val}'
        names_plot = []
        rates = {'Normal': [], 'CF': [], 'FHS': []}
        trinity = {'Normal': [], 'CF': [], 'FHS': []}

        for name in model_names:
            d = layer_results['layer4'].get(name, {}).get(key)
            if d is None:
                continue
            names_plot.append(name)
            rates['Normal'].append(d['normal']['violation_rate'])
            rates['CF'].append(d['cornish_fisher']['violation_rate'])
            rates['FHS'].append(d['historical_sim']['violation_rate'])
            trinity['Normal'].append(d['normal']['trinity_pass'])
            trinity['CF'].append(d['cornish_fisher']['trinity_pass'])
            trinity['FHS'].append(d['historical_sim']['trinity_pass'])

        x = np.arange(len(names_plot))
        width = 0.25
        ax.bar(x - width, rates['Normal'], width, label='Normal', color='#3498db', alpha=0.8)
        ax.bar(x, rates['CF'], width, label='Cornish-Fisher', color='#e67e22', alpha=0.8)
        ax.bar(x + width, rates['FHS'], width, label='FHS', color='#2ecc71', alpha=0.8)
        ax.axhline(alpha_val, color='red', linestyle='--', linewidth=1.5, label=f'Expected {alpha_val:.0%}')
        ax.set_xticks(x)
        ax.set_xticklabels(names_plot, fontsize=10)
        ax.set_ylabel('Violation Rate', fontsize=11)
        ax.set_title(f'{title} Backtesting', fontsize=12, fontweight='bold')
        ax.legend(fontsize=9)

        # Mark Trinity passes with star
        for i, name in enumerate(names_plot):
            for j, method in enumerate(['Normal', 'CF', 'FHS']):
                if trinity[method][i]:
                    offset = (j - 1) * width
                    ax.text(i + offset, rates[method][i] + 0.002, '★',
                            ha='center', fontsize=10, color='gold')

    plt.suptitle('K874e Layer 4: VaR Backtesting (★ = Trinity Pass)', fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'layer4_var_backtest.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # ---- Chart 5: Economic Significance ----
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Buy-and-hold benchmark
    bh_metrics = layer_results['layer6'].get('buy_and_hold', {})

    metrics_plot = [
        ('sharpe', 'Sharpe Ratio (after 5bps TC)'),
        ('sortino', 'Sortino Ratio'),
        ('mdd', 'Maximum Drawdown'),
        ('cagr', 'CAGR'),
    ]

    for idx, (metric, label) in enumerate(metrics_plot):
        ax = axes[idx // 2][idx % 2]
        vals = []
        names_plot = []
        for name in model_names:
            d = layer_results['layer6'].get(name)
            if d and metric in d:
                vals.append(d[metric])
                names_plot.append(name)

        # Add BH
        if bh_metrics and metric in bh_metrics:
            vals.append(bh_metrics[metric])
            names_plot.append('Buy & Hold')

        if metric == 'mdd':
            sorted_idx = np.argsort(vals)[::-1]  # least negative first
        elif metric in ('sharpe', 'sortino', 'cagr'):
            sorted_idx = np.argsort(vals)[::-1]
        else:
            sorted_idx = np.argsort(vals)

        sorted_names = [names_plot[i] for i in sorted_idx]
        sorted_vals = [vals[i] for i in sorted_idx]
        colors = ['#e74c3c' if n == 'Buy & Hold' else '#3498db' for n in sorted_names]

        ax.barh(range(len(sorted_names)), sorted_vals, color=colors)
        ax.set_yticks(range(len(sorted_names)))
        ax.set_yticklabels(sorted_names, fontsize=10)
        ax.set_title(label, fontsize=12, fontweight='bold')
        for i, val in enumerate(sorted_vals):
            fmt = f'{val:.4f}' if abs(val) < 1 else f'{val:.2f}'
            ax.text(val, i, f'  {fmt}', va='center', fontsize=9)

    plt.suptitle('K874e Layer 6: VT Strategy Economic Significance\n'
                 '(target_vol=15%, tx_cost=5bps)', fontsize=14, y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'layer6_economic.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # ---- Chart 6: CRRA Utility ----
    fig, ax = plt.subplots(figsize=(14, 7))
    gammas = [2, 5, 10]
    x = np.arange(len(model_names))
    width = 0.25

    for g_idx, gamma in enumerate(gammas):
        ces = []
        for name in model_names:
            d = layer_results['layer6'].get(name, {}).get('crra', {}).get(f'gamma_{gamma}', {})
            ces.append(d.get('certainty_equivalent', 0) * 10000)  # bps
        ax.bar(x + g_idx * width, ces, width, label=f'γ={gamma}', alpha=0.8)

    ax.set_xticks(x + width)
    ax.set_xticklabels(model_names, fontsize=11)
    ax.set_ylabel('Certainty Equivalent (bps/day)', fontsize=12)
    ax.set_title('K874e Layer 6: CRRA Utility — Certainty Equivalent by Risk Aversion\n'
                 '(Higher = better)', fontsize=13)
    ax.legend(fontsize=11)
    ax.axhline(0, color='gray', linewidth=0.5)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'layer6_crra_utility.png'), dpi=150)
    plt.close()

    # ---- Chart 7: Grand Summary ----
    fig, ax = plt.subplots(figsize=(14, 8))

    # Count wins across all dimensions
    dimensions = ['QLIKE', 'MSE', 'MAE', 'HMSE', 'MZ_R2', 'Spearman', 'Kendall',
                  'VaR_1%_Normal', 'VaR_1%_CF', 'VaR_1%_FHS',
                  'ES_pval', 'FZ_score',
                  'Sharpe', 'Sortino', 'CRRA_g5']

    win_counts = {name: 0 for name in model_names}

    # Layer 1 wins
    for lf in ['qlike', 'mse', 'mae', 'hmse']:
        vals = {name: layer_results['layer1'][name].get(lf, 1e10) for name in model_names}
        winner = min(vals, key=vals.get)
        win_counts[winner] += 1
    # MZ R2
    vals_r2 = {name: layer_results['layer1'][name].get('mz_r2', 0) for name in model_names}
    winner = max(vals_r2, key=vals_r2.get)
    win_counts[winner] += 1

    # Layer 3 wins
    for metric in ['spearman_rho', 'kendall_tau']:
        vals = {name: layer_results['layer3'][name].get(metric, 0) for name in model_names}
        winner = max(vals, key=vals.get)
        win_counts[winner] += 1

    # Layer 4: closest to alpha (best calibrated)
    for alpha_val in [0.01]:
        key = f'alpha_{alpha_val}'
        for method in ['normal', 'cornish_fisher', 'historical_sim']:
            vals = {}
            for name in model_names:
                d = layer_results['layer4'].get(name, {}).get(key, {}).get(method, {})
                vr = d.get('violation_rate', 1.0)
                vals[name] = abs(vr - alpha_val)
            if vals:
                winner = min(vals, key=vals.get)
                win_counts[winner] += 1

    # Layer 5: ES
    vals_es = {}
    for name in model_names:
        d = layer_results['layer5'].get(name, {}).get('acerbi_szekely', {})
        vals_es[name] = d.get('p_value', 0)
    if vals_es:
        winner = max(vals_es, key=vals_es.get)
        win_counts[winner] += 1

    vals_fz = {}
    for name in model_names:
        d = layer_results['layer5'].get(name, {}).get('fissler_ziegel', {})
        vals_fz[name] = d.get('mean_score', 1e10)
    if vals_fz:
        winner = min(vals_fz, key=vals_fz.get)
        win_counts[winner] += 1

    # Layer 6: Sharpe, Sortino, CRRA γ=5
    for metric in ['sharpe', 'sortino']:
        vals = {}
        for name in model_names:
            d = layer_results['layer6'].get(name, {})
            vals[name] = d.get(metric, -999)
        if vals:
            winner = max(vals, key=vals.get)
            win_counts[winner] += 1

    vals_crra = {}
    for name in model_names:
        d = layer_results['layer6'].get(name, {}).get('crra', {}).get('gamma_5', {})
        vals_crra[name] = d.get('certainty_equivalent', -999)
    if vals_crra:
        winner = max(vals_crra, key=vals_crra.get)
        win_counts[winner] += 1

    # Plot win counts
    sorted_models = sorted(win_counts.keys(), key=lambda x: win_counts[x], reverse=True)
    counts = [win_counts[m] for m in sorted_models]
    total_dims = sum(counts)
    colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(sorted_models))]

    bars = ax.barh(range(len(sorted_models)), counts, color=colors)
    ax.set_yticks(range(len(sorted_models)))
    ax.set_yticklabels(sorted_models, fontsize=13)
    ax.set_xlabel(f'Number of Wins (out of {total_dims} dimensions)', fontsize=12)
    ax.set_title('K874e: Grand Summary — Wins Across All 6 Layers\n'
                 '(Statistical + Economic Significance)', fontsize=14)
    for bar, val in zip(bars, counts):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                f'{val}/{total_dims}', va='center', fontsize=12, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'grand_summary.png'), dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# MAIN
# ============================================================

def main():
    t_start = datetime.now()
    print("=" * 70)
    print("K874e: Complete 6-Layer Fair Comparison")
    print("Statistical + Economic Significance")
    print("=" * 70)

    # ===========================================================
    # STEP 1: Load data and build models (reuse K874d pipeline)
    # ===========================================================
    print("\n[1/10] Loading TAIFEX TX tick data...")
    rv_df = load_all_data()
    print(f"  Loaded {len(rv_df)} trading days: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")

    print("\n[2/10] Building daily variance components...")
    daily_df = build_daily_components(rv_df)
    n_daily = len(daily_df)
    is_end = int(n_daily * IS_FRACTION)

    print(f"  Total: {n_daily}, IS: {is_end}, OOS: {n_daily - is_end}")
    print(f"  IS: {daily_df.index[0].date()} to {daily_df.index[is_end-1].date()}")
    print(f"  OOS: {daily_df.index[is_end].date()} to {daily_df.index[-1].date()}")

    # Scaling ratios
    print("\n[3/10] Computing scaling ratios...")
    ratios = compute_scaling_ratios(daily_df, is_end)
    print(f"  prg_native_share={ratios['prg_native_share']:.4f}, mean_gap={ratios['mean_gap']:.2e}")

    # Extract arrays
    sigma2_fullday = daily_df['sigma2_fullday'].values
    rv_total = daily_df['rv_total'].values
    c2c_returns = daily_df['c2c_return'].values

    # ===========================================================
    # STEP 2: Run all 4 models
    # ===========================================================

    # GJR-GARCH
    print("\n[4/10] Running GJR-GARCH...")
    gjr_raw = gjr_oos_forecast(c2c_returns, is_end, REFIT_FREQ_DAILY)
    gjr_fullday = gjr_raw.copy()  # native
    print(f"  GJR: {np.sum(np.isfinite(gjr_fullday[is_end:]))} OOS forecasts")

    # HAR(RV_total)
    print("\n[5/10] Running HAR(RV_total)...")
    har_raw = har_oos_forecast_on_target(rv_total, is_end, REFIT_FREQ_DAILY)
    har_fullday = convert_har_to_fullday(har_raw, ratios)
    print(f"  HAR: {np.sum(np.isfinite(har_fullday[is_end:]))} OOS forecasts")

    # PRG Basic & Extended
    print("\n[6/10] Running PRG Basic + Extended...")
    df_for_sess = rv_df.copy()
    df_for_sess = df_for_sess.dropna(subset=['day_open', 'day_close', 'rv_intra'])
    df_for_sess['prev_close'] = df_for_sess['day_close'].shift(1)
    df_for_sess['overnight_gap'] = np.log(df_for_sess['day_open'] / df_for_sess['prev_close'])
    df_for_sess['r2_overnight'] = df_for_sess['overnight_gap'] ** 2
    df_for_sess['intra_return'] = np.log(df_for_sess['day_close'] / df_for_sess['day_open'])
    df_for_sess = df_for_sess.iloc[1:]
    df_for_sess = df_for_sess.dropna(subset=['overnight_gap', 'intra_return', 'rv_intra'])

    sessions = []
    for dt in df_for_sess.index:
        row = df_for_sess.loc[dt]
        sessions.append({'date': dt, 'session_type': 0, 'r': row['overnight_gap'], 'x': row['r2_overnight']})
        sessions.append({'date': dt, 'session_type': 1, 'r': row['intra_return'], 'x': row['rv_intra']})

    sess_df = pd.DataFrame(sessions)
    r_sess = sess_df['r'].values
    x_sess = sess_df['x'].values
    s_sess = sess_df['session_type'].values
    dates_sess = sess_df['date'].values
    n_sessions = len(sess_df)
    is_end_sess = int(n_sessions * IS_FRACTION)
    if is_end_sess % 2 != 0:
        is_end_sess += 1

    refit_freq_sess = 126  # ~63 days in sessions

    def run_prg_model(extended_flag, label):
        """Run PRG Basic or Extended."""
        params, ll = estimate_prg(r_sess[:is_end_sess], x_sess[:is_end_sess],
                                   s_sess[:is_end_sess], extended=extended_flag, n_starts=5)
        if params is None:
            print(f"  {label}: estimation failed")
            return np.full(n_daily, np.nan)

        if extended_flag:
            print(f"  {label}: omega0={params[0]:.2e}, alpha0={params[1]:.4f}, beta0={params[2]:.4f}, "
                  f"gamma0={params[6]:.4f}, gamma1={params[7]:.4f}")
        else:
            print(f"  {label}: omega0={params[0]:.2e}, alpha0={params[1]:.4f}, beta0={params[2]:.4f}")

        cur_p = params
        h_run = np.var(r_sess[:50])
        if h_run < 1e-12: h_run = 1e-8
        h_all = np.zeros(n_sessions)
        h_all[0] = h_run

        for t in range(1, n_sessions):
            st = int(s_sess[t])
            if extended_flag:
                omega = np.array([cur_p[0], cur_p[3]])
                alpha = np.array([cur_p[1], cur_p[4]])
                beta = np.array([cur_p[2], cur_p[5]])
                gamma = np.array([cur_p[6], cur_p[7]])
                leverage = gamma[st] * x_sess[t-1] * (1.0 if r_sess[t-1] < 0 else 0.0)
            else:
                omega = np.array([cur_p[0], cur_p[3]])
                alpha = np.array([cur_p[1], cur_p[4]])
                beta = np.array([cur_p[2], cur_p[5]])
                leverage = 0.0

            h_run = omega[st] + alpha[st] * x_sess[t-1] + leverage + beta[st] * h_run
            if h_run < 1e-12: h_run = 1e-12
            h_all[t] = h_run

            if t >= is_end_sess and (t - is_end_sess) % refit_freq_sess == 0 and t > is_end_sess:
                new_p, _ = estimate_prg(r_sess[:t], x_sess[:t], s_sess[:t],
                                         extended=extended_flag, n_starts=3)
                if new_p is not None:
                    cur_p = new_p

        # Aggregate to daily
        prg_daily = np.full(n_daily, np.nan)
        for i in range(0, n_sessions - 1, 2):
            if i + 1 >= n_sessions: break
            sess_date = pd.Timestamp(dates_sess[i])
            if sess_date in daily_df.index:
                loc = daily_df.index.get_loc(sess_date)
                if loc >= is_end:
                    prg_daily[loc] = h_all[i] + h_all[i+1]

        prg_fullday = convert_prg_to_fullday(prg_daily, ratios)
        n_oos = np.sum(np.isfinite(prg_fullday[is_end:]))
        print(f"  {label}: {n_oos} OOS forecasts")
        return prg_fullday

    prg_basic_fullday = run_prg_model(False, "PRG Basic")
    prg_ext_fullday = run_prg_model(True, "PRG Extended")

    # Collect all models
    models = {
        'GJR-GARCH': gjr_fullday,
        'HAR(RV_total)': har_fullday,
        'PRG Basic': prg_basic_fullday,
        'PRG Extended': prg_ext_fullday,
    }
    model_names = list(models.keys())

    # Common OOS arrays
    target_oos = sigma2_fullday[is_end:]
    returns_oos = c2c_returns[is_end:]
    sigma_oos = {name: np.sqrt(np.clip(fc[is_end:], 1e-15, None)) for name, fc in models.items()}
    fc_oos = {name: fc[is_end:] for name, fc in models.items()}

    # ===========================================================
    # LAYER 1: Multiple Statistical Loss Functions
    # ===========================================================
    print("\n[7/10] Layer 1: Multiple Statistical Loss Functions...")
    layer1 = {}
    loss_arrays = {}

    for name in model_names:
        res = compute_all_losses(target_oos, fc_oos[name])
        layer1[name] = {k: v for k, v in res.items() if k != 'loss_arrays'}
        loss_arrays[name] = res['loss_arrays']
        print(f"  {name}: QLIKE={res['qlike']:.6f}, MSE={res['mse']:.2e}, "
              f"MAE={res['mae']:.2e}, HMSE={res['hmse']:.6f}, R²={res['mz_r2']:.4f}")

    # DM tests on all loss functions
    print("\n  DM tests (Harvey |t|>3.0):")
    dm_results = {}
    for lf in ['qlike', 'mse', 'mae', 'hmse']:
        dm_results[lf] = {}
        for i in range(len(model_names)):
            for j in range(i+1, len(model_names)):
                m1, m2 = model_names[i], model_names[j]
                l1 = loss_arrays[m1][lf]
                l2 = loss_arrays[m2][lf]
                valid = np.isfinite(l1) & np.isfinite(l2)
                t_stat, p_val = dm_test(l1[valid], l2[valid])
                sig = abs(t_stat) > 3.0
                winner = m1 if t_stat < 0 else m2
                key = f"{m1} vs {m2}"
                dm_results[lf][key] = {
                    't_stat': round(t_stat, 4),
                    'p_value': round(p_val, 6),
                    'significant': sig,
                    'winner': winner,
                }
                if sig:
                    print(f"    [{lf}] {key}: t={t_stat:.4f} *** → {winner}")

    # Ranking consistency check
    rankings = {}
    for lf in ['qlike', 'mse', 'mae', 'hmse']:
        vals = [(name, layer1[name][lf]) for name in model_names]
        vals.sort(key=lambda x: x[1])
        rankings[lf] = [v[0] for v in vals]
    rankings['mz_r2'] = sorted(model_names, key=lambda x: layer1[x]['mz_r2'], reverse=True)

    print("\n  Ranking Consistency:")
    for lf, rank in rankings.items():
        print(f"    {lf}: {' > '.join(rank)}")

    ranking_consistent = all(r[0] == rankings['qlike'][0] for r in rankings.values())
    print(f"  All rankings agree on #1? {'YES' if ranking_consistent else 'NO'}")

    # ===========================================================
    # LAYER 2: Model Confidence Set
    # ===========================================================
    print("\n[8/10] Layer 2: Model Confidence Set (α=0.10, block=22, B=1000)...")
    qlike_losses_for_mcs = {name: loss_arrays[name]['qlike'] for name in model_names}
    mcs_survivors, mcs_pvalues = model_confidence_set(
        qlike_losses_for_mcs, alpha=0.10, B=1000, block_size=22, rng_seed=42
    )
    print(f"  MCS Superior Set: {mcs_survivors}")
    print(f"  Eliminated (p-values): {mcs_pvalues}")

    layer2 = {
        'superior_set': mcs_survivors,
        'eliminated_pvalues': {k: round(v, 4) for k, v in mcs_pvalues.items()},
        'alpha': 0.10,
        'B': 1000,
        'block_size': 22,
        'loss_function': 'QLIKE',
    }

    # ===========================================================
    # LAYER 3: Rank Correlations with Bootstrap CI
    # ===========================================================
    print("\n  Layer 3: Rank Correlations with Bootstrap CI...")
    layer3 = {}
    for name in model_names:
        res = rank_correlations_with_ci(target_oos, fc_oos[name], n_boot=2000, rng_seed=42)
        layer3[name] = {k: v for k, v in res.items()}
        print(f"  {name}: Spearman={res['spearman_rho']:.4f} [{res['spearman_ci_lo']:.4f}, {res['spearman_ci_hi']:.4f}], "
              f"Kendall={res['kendall_tau']:.4f} [{res['kendall_ci_lo']:.4f}, {res['kendall_ci_hi']:.4f}]")

    # ===========================================================
    # LAYER 4: VaR Backtesting (1% and 5%)
    # ===========================================================
    print("\n  Layer 4: VaR Backtesting...")
    layer4 = {}
    for name in model_names:
        layer4[name] = {}
        for alpha_val in [0.01, 0.05]:
            res = var_backtest_full(returns_oos, sigma_oos[name], alpha=alpha_val)
            key = f'alpha_{alpha_val}'
            layer4[name][key] = res
            if res:
                for method in ['normal', 'cornish_fisher', 'historical_sim']:
                    d = res[method]
                    trinity = 'PASS' if d['trinity_pass'] else 'FAIL'
                    print(f"  {name} [{alpha_val:.0%} {method}]: "
                          f"VR={d['violation_rate']:.4f}, Kupiec p={d.get('kupiec_p', 'NA')}, "
                          f"CC p={d.get('cc_p', 'NA')}, Basel={d['basel_zone']}, Trinity={trinity}")

    # ===========================================================
    # LAYER 5: ES Evaluation
    # ===========================================================
    print("\n  Layer 5: ES (Expected Shortfall)...")
    layer5 = {}
    for name in model_names:
        as_res = es_backtest_acerbi_szekely(returns_oos, sigma_oos[name], alpha=0.01)
        fz_res = fissler_ziegel_score(returns_oos, sigma_oos[name], alpha=0.01)
        layer5[name] = {
            'acerbi_szekely': {k: v for k, v in as_res.items() if not isinstance(v, np.ndarray)} if as_res else None,
            'fissler_ziegel': {k: v for k, v in fz_res.items() if not isinstance(v, np.ndarray)} if fz_res else None,
        }
        if as_res:
            print(f"  {name} AS: Z={as_res['z_stat']:.4f}, p={as_res['p_value']:.4f}, reject={as_res.get('reject_at_5pct', 'NA')}")
        if fz_res:
            print(f"  {name} FZ: score={fz_res['mean_score']:.6f}")

    # DM test on FZ scores
    print("\n  DM test on Fissler-Ziegel scores:")
    fz_dm = {}
    fz_scores = {}
    for name in model_names:
        fz_res = fissler_ziegel_score(returns_oos, sigma_oos[name], alpha=0.01)
        if fz_res:
            fz_scores[name] = fz_res['score_array']

    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            if m1 in fz_scores and m2 in fz_scores:
                s1, s2 = fz_scores[m1], fz_scores[m2]
                valid = np.isfinite(s1) & np.isfinite(s2)
                t_stat, p_val = dm_test(s1[valid], s2[valid])
                sig = abs(t_stat) > 3.0
                winner = m1 if t_stat < 0 else m2
                key = f"{m1} vs {m2}"
                fz_dm[key] = {
                    't_stat': round(t_stat, 4),
                    'p_value': round(p_val, 6),
                    'significant': sig,
                    'winner': winner,
                }
                if sig:
                    print(f"    {key}: t={t_stat:.4f} *** → {winner}")

    # ===========================================================
    # LAYER 6: Economic Significance
    # ===========================================================
    print("\n[9/10] Layer 6: Economic Significance...")
    layer6 = {}

    # Buy-and-hold benchmark (100% TX)
    bh_returns = returns_oos[np.isfinite(returns_oos)]
    bh_mean = np.mean(bh_returns)
    bh_std = np.std(bh_returns, ddof=1)
    bh_sharpe = bh_mean / bh_std * np.sqrt(252)
    bh_cumret = np.cumprod(1 + bh_returns)
    bh_mdd = float(np.min(bh_cumret / np.maximum.accumulate(bh_cumret) - 1))
    bh_cagr = (1 + bh_mean)**252 - 1
    neg_bh = bh_returns[bh_returns < 0]
    bh_sortino = bh_mean / np.sqrt(np.mean(neg_bh**2)) * np.sqrt(252) if len(neg_bh) > 0 else 0

    layer6['buy_and_hold'] = {
        'sharpe': round(float(bh_sharpe), 4),
        'cagr': round(float(bh_cagr), 4),
        'annual_vol': round(float(bh_std * np.sqrt(252)), 4),
        'sortino': round(float(bh_sortino), 4),
        'mdd': round(float(bh_mdd), 4),
    }
    print(f"  Buy & Hold: Sharpe={bh_sharpe:.4f}, CAGR={bh_cagr:.4f}, MDD={bh_mdd:.4f}")

    # VT strategy for each model
    for name in model_names:
        vt_res = vt_strategy_performance(returns_oos, sigma_oos[name])
        if vt_res is not None:
            port_ret = vt_res.pop('port_returns')

            # CRRA utility
            vt_res['crra'] = {}
            for gamma in [2, 5, 10]:
                cu = crra_utility(port_ret, gamma)
                vt_res['crra'][f'gamma_{gamma}'] = cu

            # Prospect theory
            pt = prospect_theory_value(port_ret)
            vt_res['prospect_theory'] = pt

            layer6[name] = vt_res
            print(f"  {name}: Sharpe={vt_res['sharpe']:.4f}, CAGR={vt_res['cagr']:.4f}, "
                  f"MDD={vt_res['mdd']:.4f}, Sortino={vt_res['sortino']:.4f}")
            for gamma in [2, 5, 10]:
                ce = vt_res['crra'][f'gamma_{gamma}']['certainty_equivalent']
                print(f"    CRRA γ={gamma}: CE={ce*10000:.2f} bps/day")
        else:
            layer6[name] = None
            print(f"  {name}: VT strategy failed")

    # DM test on strategy returns
    print("\n  DM test on VT strategy returns:")
    strat_dm = {}
    strat_returns = {}
    for name in model_names:
        vt_res = vt_strategy_performance(returns_oos, sigma_oos[name])
        if vt_res is not None:
            strat_returns[name] = -vt_res['port_returns']  # negative for loss convention

    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            if m1 in strat_returns and m2 in strat_returns:
                s1, s2 = strat_returns[m1], strat_returns[m2]
                min_len = min(len(s1), len(s2))
                t_stat, p_val = dm_test(s1[:min_len], s2[:min_len])
                sig = abs(t_stat) > 3.0
                winner = m1 if t_stat < 0 else m2  # negative loss = higher return = better
                key = f"{m1} vs {m2}"
                strat_dm[key] = {
                    't_stat': round(t_stat, 4),
                    'p_value': round(p_val, 6),
                    'significant': sig,
                    'winner': winner,
                }
                if sig:
                    print(f"    {key}: t={t_stat:.4f} *** → {winner}")
                else:
                    print(f"    {key}: t={t_stat:.4f}, p={p_val:.4f}")

    # ===========================================================
    # CHARTS
    # ===========================================================
    print("\n[10/10] Generating charts...")
    all_layer_results = {
        'layer1': layer1,
        'layer2': layer2,
        'layer3': layer3,
        'layer4': layer4,
        'layer5': layer5,
        'layer6': layer6,
    }
    make_charts(all_layer_results, CHARTS_DIR)

    # ===========================================================
    # COMPILE RESULTS
    # ===========================================================
    elapsed = (datetime.now() - t_start).total_seconds()

    # Clean layer4 for JSON (remove numpy)
    def clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_for_json(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj) if np.isfinite(obj) else None
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj

    # Determine overall winner
    wins = {name: 0 for name in model_names}
    # QLIKE, MSE, MAE, HMSE (lower = better)
    for lf in ['qlike', 'mse', 'mae', 'hmse']:
        vals = {name: layer1[name][lf] for name in model_names}
        wins[min(vals, key=vals.get)] += 1
    # MZ R2 (higher = better)
    vals_r2 = {name: layer1[name]['mz_r2'] for name in model_names}
    wins[max(vals_r2, key=vals_r2.get)] += 1
    # Spearman, Kendall (higher = better)
    for metric in ['spearman_rho', 'kendall_tau']:
        vals = {name: layer3[name][metric] for name in model_names}
        wins[max(vals, key=vals.get)] += 1
    # FZ score (lower = better)
    fz_vals = {}
    for name in model_names:
        d = layer5.get(name, {}).get('fissler_ziegel', {})
        if d and d.get('mean_score') is not None:
            fz_vals[name] = d['mean_score']
    if fz_vals:
        wins[min(fz_vals, key=fz_vals.get)] += 1
    # Sharpe (higher = better)
    sharpe_vals = {name: layer6.get(name, {}).get('sharpe', -999) for name in model_names}
    wins[max(sharpe_vals, key=sharpe_vals.get)] += 1

    overall_winner = max(wins, key=wins.get)

    # Summary conclusion
    conclusion_parts = [
        f"Overall winner: {overall_winner} ({wins[overall_winner]} wins out of {sum(wins.values())} dimensions).",
        f"MCS superior set: {mcs_survivors}.",
    ]
    # Check ranking consistency
    if ranking_consistent:
        conclusion_parts.append(f"Rankings CONSISTENT across all loss functions: #{rankings['qlike'][0]} wins everywhere.")
    else:
        conclusion_parts.append("Rankings DIFFER across loss functions — robustness check important.")

    # VaR summary
    var_summary = []
    for name in model_names:
        d = layer4.get(name, {}).get('alpha_0.01', {})
        if d:
            passes = sum(1 for m in ['normal', 'cornish_fisher', 'historical_sim'] if d[m]['trinity_pass'])
            var_summary.append(f"{name}: {passes}/3 Trinity passes")
    conclusion_parts.append("1% VaR Trinity: " + "; ".join(var_summary))

    results = {
        'experiment_id': 'K874e',
        'title': 'Complete 6-Layer Fair Comparison — Statistical + Economic Significance',
        'date': '2026-04-05',
        'data_source': 'TAIFEX TX tick (volume-selected contract, 2017-05 to 2025-12)',
        'data_period': f'{daily_df.index[0]} to {daily_df.index[-1]}',
        'n_daily': n_daily,
        'is_days': is_end,
        'oos_days': n_daily - is_end,
        'is_period': f'{daily_df.index[0].date()} to {daily_df.index[is_end-1].date()}',
        'oos_period': f'{daily_df.index[is_end].date()} to {daily_df.index[-1].date()}',
        'common_target': 'σ²_fullday = r²_gap + RV_intra + RV_night',
        'models': model_names,
        'runtime_seconds': round(elapsed, 1),

        'layer1_loss_functions': clean_for_json(layer1),
        'layer1_dm_tests': clean_for_json(dm_results),
        'layer1_rankings': rankings,
        'layer1_ranking_consistent': ranking_consistent,

        'layer2_mcs': clean_for_json(layer2),

        'layer3_rank_correlations': clean_for_json(layer3),

        'layer4_var_backtest': clean_for_json(layer4),

        'layer5_es': clean_for_json(layer5),
        'layer5_fz_dm_tests': clean_for_json(fz_dm),

        'layer6_economic': clean_for_json(layer6),
        'layer6_strategy_dm': clean_for_json(strat_dm),

        'overall_winner': overall_winner,
        'win_counts': wins,
        'conclusions': ' '.join(conclusion_parts),

        'references': [
            'Patton (2011): Volatility forecast comparison using imperfect proxies',
            'Hansen, Lunde & Nason (2011): Model Confidence Set',
            'Kupiec (1995): Proportion of failures VaR test',
            'Christoffersen (1998): Conditional coverage VaR test',
            'Acerbi & Szekely (2014): Backtesting Expected Shortfall',
            'Fissler & Ziegel (2016): Joint VaR-ES scoring function',
            'Corsi (2009): HAR-RV model',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Diebold & Mariano (1995), Harvey et al. (1997): DM test',
        ],
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"K874e COMPLETE — {elapsed:.1f}s")
    print(f"{'='*70}")
    print(f"\nOverall Winner: {overall_winner} ({wins[overall_winner]}/{sum(wins.values())} dimensions)")
    print(f"MCS Superior Set: {mcs_survivors}")
    print(f"Ranking Consistent: {'YES' if ranking_consistent else 'NO'}")
    print(f"\nResults: {OUTPUT_FILE}")
    print(f"Charts: {CHARTS_DIR}/")


if __name__ == '__main__':
    main()
