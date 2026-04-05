#!/usr/bin/env python3
"""
K874d: Fair Comparison Framework — All Models Predict the SAME Full-Day σ²
==========================================================================

Research Question (EMPIRICAL):
  K874c compared HAR (predicts RV_total = RV_intra + RV_night) vs PRG (predicts
  gap variance + intraday variance only). These predict DIFFERENT targets.
  The QLIKE comparison is therefore invalid / unfair.

  THIS experiment defines ONE common target and converts ALL models' predictions
  to that target before comparing.

The Common Target:
  σ²_fullday = r²_overnight_gap + RV_intra + RV_night

  where:
    r²_overnight_gap = squared overnight gap return (close-to-open)
    RV_intra         = 5-min realized variance during regular session (8:45-13:45)
    RV_night         = 5-min realized variance during night session (15:00-05:00)

  This is the TOTAL daily variance decomposed into three additive components.

Model Conversions to Full-Day σ²:
  1. GJR-GARCH: predicts h_t = E[r²_daily | info]. Already full-day. Use h_t directly.
  2. HAR on RV_total: predicts E[RV_intra + RV_night]. Missing gap.
     Convert: ĥ_HAR_fullday = ĥ_HAR + E[r²_gap | ĥ_HAR] via ratio scaling.
  3. HAR on RV_intra only: predicts E[RV_intra]. Missing night + gap.
     Convert: ĥ_intra_fullday = ĥ_intra / mean(RV_intra / σ²_fullday).
  4. PRG (K874c): predicts h_gap + h_intra (no night RV).
     Convert: ĥ_PRG_fullday = (h_gap + h_intra) / mean((gap+intra) / σ²_fullday).

Evaluation:
  - QLIKE(σ²_fullday, ĥ_model_fullday) for ALL models on the SAME target
  - Spearman rank correlation
  - DM test pairwise with Harvey |t| > 3.0
  - VaR backtesting (Kupiec + Christoffersen)

Error log rules:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - TX: volume-based contract selection
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])

Data:
  - TAIFEX TX tick (volume-selected contract, 2017-05 to 2025-12)
  - yfinance: ^VIX (for GJR context)

References:
  - Hansen & Lunde (2005): Optimal RV weighting for daily σ²
  - Patton (2011): QLIKE proxy-robust loss
  - Corsi (2009): HAR-RV model
  - Bollerslev & Ghysels (1996): Periodic GARCH
  - Diebold & Mariano (1995): DM test
  - Harvey, Leybourne & Newbold (1997): Modified DM test

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
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k874d_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k874d_charts")
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
REFIT_FREQ_DAILY = 63   # Refit every ~63 trading days (quarterly)
NIGHT_SESSION_START_DATE = "2017-05-15"


# ============================================================
# Step 1: Build daily data with THREE variance components
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

    # Volume-based contract selection (TX, not TX1)
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

    rv_intra = compute_rv(day_rets)      # 5-min RV during regular session
    rv_night = compute_rv(night_rets)     # 5-min RV during night session

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
    """Load TX files (night session era) and compute three variance components."""
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
    """
    Build the THREE variance components for each trading day:
      1. r²_gap: squared overnight gap return (prev_close -> day_open)
      2. RV_intra: 5-min realized variance during regular session
      3. RV_night: 5-min realized variance during night session

    And the COMMON TARGET:
      σ²_fullday = r²_gap + RV_intra + RV_night

    Also compute close-to-close return for GJR benchmark.
    """
    df = rv_df.copy()
    df = df.dropna(subset=['day_open', 'day_close', 'rv_intra'])

    # Overnight gap: previous day close -> today's open
    df['prev_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_close'])
    df['r2_gap'] = df['overnight_gap'] ** 2

    # Close-to-close return for GJR
    df['c2c_return'] = np.log(df['day_close'] / df['prev_close'])

    # Intraday return for PRG
    df['intra_return'] = np.log(df['day_close'] / df['day_open'])

    # RV_total = RV_intra + RV_night (when night is available)
    df['rv_total'] = df['rv_intra'] + df['rv_night'].fillna(0)

    # Full-day variance = r²_gap + RV_intra + RV_night
    df['sigma2_fullday'] = df['r2_gap'] + df['rv_intra'] + df['rv_night'].fillna(0)

    # Drop first row (no previous close)
    df = df.iloc[1:]

    # Drop rows missing critical data
    df = df.dropna(subset=['c2c_return', 'rv_intra', 'r2_gap', 'sigma2_fullday'])

    return df


# ============================================================
# Step 2: Model implementations
# ============================================================

# --- Model 1: GJR-GARCH on close-to-close returns ---

def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """
    GJR-GARCH(1,1) on daily close-to-close returns.
    h_t = omega + alpha*r²_{t-1} + gamma*r²_{t-1}*I(r_{t-1}<0) + beta*h_{t-1}

    Predicts full-day σ² natively (through c2c returns).
    No conversion needed.
    """
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
                # Recompute h state through all data
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


# --- Model 2: HAR-RV on RV_total (= RV_intra + RV_night) ---

def har_oos_forecast_on_target(rv_series, is_end, refit_freq=63, label="rv_total"):
    """
    HAR-RV OOS: predict log(target_{t+1}) from HAR(d,w,m) lags of target.
    Returns forecasts in LEVEL (not log).
    """
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


# --- Model 3: PRG (Periodic Realized GARCH) from K874c ---

def estimate_prg(r, x, s, extended=False, n_starts=5):
    """
    Estimate PRG via MLE. Sessions alternate: 0=overnight, 1=intraday.
    h_n = omega_{s_n} + alpha_{s_n} * x_{n-1} + [gamma_{s_n}*x_{n-1}*I(r<0)] + beta_{s_n} * h_{n-1}
    """
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


def prg_recursive_oos_daily(params, r_sessions, x_sessions, s_sessions,
                            is_end_sessions, dates_sessions, extended=False):
    """
    Run PRG OOS at session level, then aggregate to daily.
    Returns daily forecasts: h_daily[t] = h_overnight[t] + h_intraday[t].

    This is the PRG's NATIVE prediction (gap + intraday, no night RV).
    """
    n = len(r_sessions)

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
    h[0] = np.var(r_sessions[:min(50, n)])
    if h[0] < 1e-12: h[0] = 1e-8

    for t in range(1, n):
        st = int(s_sessions[t])
        leverage = gamma[st] * x_sessions[t-1] * (1.0 if r_sessions[t-1] < 0 else 0.0)
        h[t] = omega[st] + alpha[st] * x_sessions[t-1] + leverage + beta[st] * h[t-1]
        if h[t] < 1e-12: h[t] = 1e-12

    # Aggregate to daily: pair (overnight, intraday)
    daily_h = []
    daily_dates = []
    for i in range(0, n - 1, 2):
        if i + 1 >= n:
            break
        if s_sessions[i] == 0 and s_sessions[i + 1] == 1:
            daily_h.append(h[i] + h[i + 1])
            daily_dates.append(dates_sessions[i])
        else:
            daily_h.append(np.nan)
            daily_dates.append(dates_sessions[i])

    return np.array(daily_h), daily_dates


# ============================================================
# Step 3: Conversion functions
# ============================================================

def compute_scaling_ratios(daily_df, is_end):
    """
    Compute scaling ratios from in-sample data for model conversions.

    Returns dict with:
      - gap_share: mean(r²_gap / σ²_fullday)
      - intra_share: mean(RV_intra / σ²_fullday)
      - night_share: mean(RV_night / σ²_fullday)
      - rv_total_share: mean(RV_total / σ²_fullday)
      - prg_native_share: mean((r²_gap + RV_intra) / σ²_fullday)
      - mean_gap_given_rv: regression E[r²_gap | RV_total]
    """
    df_is = daily_df.iloc[:is_end]

    sigma2 = df_is['sigma2_fullday'].values
    r2_gap = df_is['r2_gap'].values
    rv_intra = df_is['rv_intra'].values
    rv_night = df_is['rv_night'].fillna(0).values
    rv_total = df_is['rv_total'].values

    # Simple ratio scaling
    valid = sigma2 > 0
    gap_share = np.mean(r2_gap[valid] / sigma2[valid])
    intra_share = np.mean(rv_intra[valid] / sigma2[valid])
    night_share = np.mean(rv_night[valid] / sigma2[valid])
    rv_total_share = np.mean(rv_total[valid] / sigma2[valid])
    prg_native = r2_gap + rv_intra
    prg_native_share = np.mean(prg_native[valid] / sigma2[valid])

    # Regression-based: r²_gap = a + b * RV_total + eps
    # For converting HAR(RV_total) -> add expected gap
    valid_reg = np.isfinite(rv_total) & np.isfinite(r2_gap)
    X_reg = np.column_stack([np.ones(valid_reg.sum()), rv_total[valid_reg]])
    y_reg = r2_gap[valid_reg]
    try:
        gap_reg_beta = np.linalg.lstsq(X_reg, y_reg, rcond=None)[0]
    except Exception:
        gap_reg_beta = np.array([np.mean(r2_gap[valid_reg]), 0.0])

    # Mean gap variance (unconditional)
    mean_gap = np.mean(r2_gap[valid])

    return {
        'gap_share': float(gap_share),
        'intra_share': float(intra_share),
        'night_share': float(night_share),
        'rv_total_share': float(rv_total_share),
        'prg_native_share': float(prg_native_share),
        'mean_gap': float(mean_gap),
        'gap_reg_intercept': float(gap_reg_beta[0]),
        'gap_reg_slope': float(gap_reg_beta[1]),
    }


def convert_gjr_to_fullday(gjr_forecasts):
    """GJR already predicts full-day σ². No conversion needed."""
    return gjr_forecasts.copy()


def convert_har_rv_total_to_fullday(har_forecasts, ratios, method='regression'):
    """
    HAR predicts RV_total = RV_intra + RV_night. Missing r²_gap.
    Method 1 (ratio): ĥ_fullday = ĥ_HAR / rv_total_share
    Method 2 (regression): ĥ_fullday = ĥ_HAR + (a + b * ĥ_HAR)
    Method 3 (additive): ĥ_fullday = ĥ_HAR + mean_gap
    """
    converted = np.full_like(har_forecasts, np.nan)
    valid = np.isfinite(har_forecasts) & (har_forecasts > 0)

    if method == 'ratio':
        converted[valid] = har_forecasts[valid] / ratios['rv_total_share']
    elif method == 'regression':
        a = ratios['gap_reg_intercept']
        b = ratios['gap_reg_slope']
        converted[valid] = har_forecasts[valid] + a + b * har_forecasts[valid]
    elif method == 'additive':
        converted[valid] = har_forecasts[valid] + ratios['mean_gap']

    return converted


def convert_har_intra_to_fullday(har_intra_forecasts, ratios):
    """
    HAR on RV_intra only. Missing night RV + gap.
    ĥ_fullday = ĥ_intra / intra_share
    """
    converted = np.full_like(har_intra_forecasts, np.nan)
    valid = np.isfinite(har_intra_forecasts) & (har_intra_forecasts > 0)
    converted[valid] = har_intra_forecasts[valid] / ratios['intra_share']
    return converted


def convert_prg_to_fullday(prg_daily_forecasts, ratios):
    """
    PRG predicts h_gap + h_intra. Missing night RV.
    ĥ_fullday = (h_gap + h_intra) / prg_native_share
    """
    converted = np.full_like(prg_daily_forecasts, np.nan)
    valid = np.isfinite(prg_daily_forecasts) & (prg_daily_forecasts > 0)
    converted[valid] = prg_daily_forecasts[valid] / ratios['prg_native_share']
    return converted


# ============================================================
# Step 4: Evaluation
# ============================================================

def qlike(realized, forecast):
    """QLIKE loss: realized/forecast - log(realized/forecast) - 1."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    return float(np.mean(r/f - np.log(r/f) - 1)), valid.sum()


def qlike_loss_array(realized, forecast):
    """Per-observation QLIKE losses for DM test."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r = realized[valid]
    f = forecast[valid]
    loss[valid] = r/f - np.log(r/f) - 1
    return loss


def spearman_corr(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    if valid.sum() < 10:
        return np.nan, np.nan
    rho, p = sp_stats.spearmanr(realized[valid], forecast[valid])
    return float(rho), float(p)


def var_backtest(returns, sigma_forecasts, alpha=0.01):
    """
    VaR backtesting: VaR = sigma * z_alpha (Normal).
    Returns Kupiec LR stat + p-value, Christoffersen CC stat + p-value,
    violation rate, and Basel zone.
    """
    valid = np.isfinite(returns) & np.isfinite(sigma_forecasts) & (sigma_forecasts > 0)
    r = returns[valid]
    sigma = sigma_forecasts[valid]
    n = len(r)
    if n < 50:
        return None

    z_alpha = sp_stats.norm.ppf(alpha)
    var_threshold = sigma * z_alpha  # negative number

    violations = (r < var_threshold).astype(float)
    n_violations = int(violations.sum())
    violation_rate = n_violations / n

    # Kupiec Proportion of Failures (POF) test
    if n_violations == 0 or n_violations == n:
        kupiec_lr = np.nan
        kupiec_p = np.nan
    else:
        lr = 2 * (n_violations * np.log(violation_rate / alpha) +
                   (n - n_violations) * np.log((1 - violation_rate) / (1 - alpha)))
        kupiec_lr = float(lr)
        kupiec_p = float(1 - sp_stats.chi2.cdf(lr, 1))

    # Christoffersen conditional coverage test (independence)
    # Count transitions
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i-1] == 0 and violations[i] == 0: n00 += 1
        elif violations[i-1] == 0 and violations[i] == 1: n01 += 1
        elif violations[i-1] == 1 and violations[i] == 0: n10 += 1
        elif violations[i-1] == 1 and violations[i] == 1: n11 += 1

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
        cc_stat = float(lr_ind) + (kupiec_lr if np.isfinite(kupiec_lr) else 0)
        cc_p = float(1 - sp_stats.chi2.cdf(cc_stat, 2))
    else:
        cc_stat = np.nan
        cc_p = np.nan

    # Basel traffic light
    if violation_rate <= 0.04:
        zone = "GREEN"
    elif violation_rate <= 0.065:
        zone = "YELLOW"
    else:
        zone = "RED"

    return {
        'n_obs': n,
        'n_violations': n_violations,
        'violation_rate': round(violation_rate, 6),
        'expected_rate': alpha,
        'kupiec_lr': round(kupiec_lr, 4) if np.isfinite(kupiec_lr) else None,
        'kupiec_p': round(kupiec_p, 4) if np.isfinite(kupiec_p) else None,
        'cc_stat': round(cc_stat, 4) if np.isfinite(cc_stat) else None,
        'cc_p': round(cc_p, 4) if np.isfinite(cc_p) else None,
        'basel_zone': zone,
    }


# ============================================================
# Step 5: Charts
# ============================================================

def make_charts(model_results, daily_df, oos_start, charts_dir):
    """Generate comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE on common target (main result)
    fig, ax = plt.subplots(figsize=(12, 7))
    names = []
    qlikes = []
    for name, data in model_results.items():
        if 'qlike_fullday' in data and data['qlike_fullday'] is not None:
            names.append(name)
            qlikes.append(data['qlike_fullday'])

    if len(names) > 0:
        # Sort by QLIKE (best first)
        sorted_idx = np.argsort(qlikes)
        names = [names[i] for i in sorted_idx]
        qlikes = [qlikes[i] for i in sorted_idx]

        colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(names))]
        bars = ax.barh(range(len(names)), qlikes, color=colors)
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names, fontsize=11)
        ax.set_xlabel('QLIKE on σ²_fullday (lower = better)', fontsize=12)
        ax.set_title('K874d: Fair Comparison — All Models on SAME Target (σ²_fullday)\n'
                      'σ²_fullday = r²_gap + RV_intra + RV_night', fontsize=13)
        for bar, val in zip(bars, qlikes):
            ax.text(bar.get_width() + 0.002, bar.get_y() + bar.get_height()/2,
                    f'{val:.4f}', va='center', fontsize=10, fontweight='bold')
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'fair_qlike_comparison.png'), dpi=150)
        plt.close()

    # Chart 2: Native vs Converted QLIKE (transparency)
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    # Left: Native target QLIKE
    ax = axes[0]
    names_native = []
    qlikes_native = []
    for name, data in model_results.items():
        if 'qlike_native' in data and data['qlike_native'] is not None:
            names_native.append(name)
            qlikes_native.append(data['qlike_native'])
    if names_native:
        sorted_idx = np.argsort(qlikes_native)
        names_native = [names_native[i] for i in sorted_idx]
        qlikes_native = [qlikes_native[i] for i in sorted_idx]
        ax.barh(range(len(names_native)), qlikes_native, color='#95a5a6')
        ax.set_yticks(range(len(names_native)))
        ax.set_yticklabels(names_native, fontsize=10)
        ax.set_xlabel('QLIKE (native target)', fontsize=11)
        ax.set_title('Native Target QLIKE\n(each model on its own target — NOT comparable)', fontsize=11)
        for i, val in enumerate(qlikes_native):
            ax.text(val + 0.002, i, f'{val:.4f}', va='center', fontsize=9)

    # Right: Common target QLIKE (repeated for contrast)
    ax = axes[1]
    names_common = []
    qlikes_common = []
    for name, data in model_results.items():
        if 'qlike_fullday' in data and data['qlike_fullday'] is not None:
            names_common.append(name)
            qlikes_common.append(data['qlike_fullday'])
    if names_common:
        sorted_idx = np.argsort(qlikes_common)
        names_common = [names_common[i] for i in sorted_idx]
        qlikes_common = [qlikes_common[i] for i in sorted_idx]
        colors = ['#e74c3c' if i == 0 else '#2ecc71' for i in range(len(names_common))]
        ax.barh(range(len(names_common)), qlikes_common, color=colors)
        ax.set_yticks(range(len(names_common)))
        ax.set_yticklabels(names_common, fontsize=10)
        ax.set_xlabel('QLIKE (common target σ²_fullday)', fontsize=11)
        ax.set_title('Common Target QLIKE\n(ALL models on σ²_fullday — FAIR comparison)', fontsize=11)
        for i, val in enumerate(qlikes_common):
            ax.text(val + 0.002, i, f'{val:.4f}', va='center', fontsize=9)

    plt.suptitle('K874d: Native vs Common Target — Why Fair Comparison Matters', fontsize=13, y=1.01)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'native_vs_common.png'), dpi=150, bbox_inches='tight')
    plt.close()

    # Chart 3: Spearman rank correlation
    fig, ax = plt.subplots(figsize=(12, 7))
    names_sp = []
    rhos = []
    for name, data in model_results.items():
        if 'spearman_fullday' in data and data['spearman_fullday'] is not None:
            names_sp.append(name)
            rhos.append(data['spearman_fullday'])
    if names_sp:
        sorted_idx = np.argsort(rhos)[::-1]  # highest first
        names_sp = [names_sp[i] for i in sorted_idx]
        rhos = [rhos[i] for i in sorted_idx]
        colors = ['#e74c3c' if i == 0 else '#3498db' for i in range(len(names_sp))]
        bars = ax.barh(range(len(names_sp)), rhos, color=colors)
        ax.set_yticks(range(len(names_sp)))
        ax.set_yticklabels(names_sp, fontsize=11)
        ax.set_xlabel('Spearman Rank Correlation (higher = better)', fontsize=12)
        ax.set_title('K874d: Spearman Correlation with σ²_fullday', fontsize=13)
        for bar, val in zip(bars, rhos):
            ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height()/2,
                    f'{val:.4f}', va='center', fontsize=10)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'spearman_comparison.png'), dpi=150)
        plt.close()

    # Chart 4: VaR backtesting summary
    fig, ax = plt.subplots(figsize=(12, 7))
    names_var = []
    viol_rates = []
    zone_colors = {'GREEN': '#2ecc71', 'YELLOW': '#f39c12', 'RED': '#e74c3c'}
    bar_colors = []
    for name, data in model_results.items():
        if 'var_backtest' in data and data['var_backtest'] is not None:
            names_var.append(name)
            viol_rates.append(data['var_backtest']['violation_rate'])
            bar_colors.append(zone_colors.get(data['var_backtest']['basel_zone'], '#95a5a6'))
    if names_var:
        bars = ax.barh(range(len(names_var)), viol_rates, color=bar_colors)
        ax.axvline(0.01, color='black', linestyle='--', label='Expected 1%')
        ax.axvline(0.04, color='orange', linestyle=':', label='Green/Yellow boundary')
        ax.set_yticks(range(len(names_var)))
        ax.set_yticklabels(names_var, fontsize=11)
        ax.set_xlabel('VaR Violation Rate', fontsize=12)
        ax.set_title('K874d: 1% VaR Backtesting (Kupiec)', fontsize=13)
        ax.legend(fontsize=10)
        for bar, val in zip(bars, viol_rates):
            ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height()/2,
                    f'{val:.4f}', va='center', fontsize=10)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'var_backtest.png'), dpi=150)
        plt.close()

    # Chart 5: Variance components share
    df_oos = daily_df.iloc[oos_start:]
    shares = {
        'r²_gap': df_oos['r2_gap'].mean() / df_oos['sigma2_fullday'].mean(),
        'RV_intra': df_oos['rv_intra'].mean() / df_oos['sigma2_fullday'].mean(),
        'RV_night': df_oos['rv_night'].fillna(0).mean() / df_oos['sigma2_fullday'].mean(),
    }
    fig, ax = plt.subplots(figsize=(8, 8))
    labels = list(shares.keys())
    sizes = [shares[k] for k in labels]
    colors_pie = ['#e74c3c', '#3498db', '#2ecc71']
    ax.pie(sizes, labels=[f'{l}\n{s:.1%}' for l, s in zip(labels, sizes)],
           colors=colors_pie, autopct='', startangle=90, textprops={'fontsize': 13})
    ax.set_title('K874d: Full-Day Variance Decomposition (OOS)\nσ²_fullday = r²_gap + RV_intra + RV_night',
                 fontsize=13)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'variance_decomposition.png'), dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K874d: Fair Comparison Framework")
    print("All Models Predict the SAME Full-Day σ²")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Load data
    # ----------------------------------------------------------
    print("\n[1/9] Loading TAIFEX TX tick data...")
    rv_df = load_all_data()
    print(f"  Loaded {len(rv_df)} trading days: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")

    # ----------------------------------------------------------
    # 2. Build daily components
    # ----------------------------------------------------------
    print("\n[2/9] Building daily variance components...")
    daily_df = build_daily_components(rv_df)
    n_daily = len(daily_df)
    is_end = int(n_daily * IS_FRACTION)
    oos_n = n_daily - is_end

    print(f"  Total days: {n_daily}")
    print(f"  IS: {is_end} days ({daily_df.index[0].date()} to {daily_df.index[is_end-1].date()})")
    print(f"  OOS: {oos_n} days ({daily_df.index[is_end].date()} to {daily_df.index[-1].date()})")

    # Descriptive stats on variance components
    for period, start, end in [('IS', 0, is_end), ('OOS', is_end, n_daily)]:
        sub = daily_df.iloc[start:end]
        s2 = sub['sigma2_fullday']
        print(f"\n  {period} Variance Decomposition (means):")
        print(f"    σ²_fullday  = {s2.mean():.2e}")
        print(f"    r²_gap      = {sub['r2_gap'].mean():.2e} ({sub['r2_gap'].mean()/s2.mean():.1%})")
        print(f"    RV_intra    = {sub['rv_intra'].mean():.2e} ({sub['rv_intra'].mean()/s2.mean():.1%})")
        rv_night_mean = sub['rv_night'].fillna(0).mean()
        print(f"    RV_night    = {rv_night_mean:.2e} ({rv_night_mean/s2.mean():.1%})")

    # ----------------------------------------------------------
    # 3. Compute scaling ratios from IS data
    # ----------------------------------------------------------
    print("\n[3/9] Computing scaling ratios from in-sample data...")
    ratios = compute_scaling_ratios(daily_df, is_end)
    print(f"  gap_share   = {ratios['gap_share']:.4f}")
    print(f"  intra_share = {ratios['intra_share']:.4f}")
    print(f"  night_share = {ratios['night_share']:.4f}")
    print(f"  rv_total_share (intra+night) = {ratios['rv_total_share']:.4f}")
    print(f"  prg_native_share (gap+intra) = {ratios['prg_native_share']:.4f}")
    print(f"  mean_gap    = {ratios['mean_gap']:.2e}")
    print(f"  gap_reg: intercept={ratios['gap_reg_intercept']:.2e}, slope={ratios['gap_reg_slope']:.4f}")

    # ----------------------------------------------------------
    # 4. Run all models
    # ----------------------------------------------------------

    # Extract arrays
    sigma2_fullday = daily_df['sigma2_fullday'].values
    rv_total = daily_df['rv_total'].values
    rv_intra = daily_df['rv_intra'].values
    c2c_returns = daily_df['c2c_return'].values
    r2_gap = daily_df['r2_gap'].values

    # --- Model 1: GJR-GARCH ---
    print("\n[4/9] Running GJR-GARCH on close-to-close returns...")
    gjr_forecasts_raw = gjr_oos_forecast(c2c_returns, is_end, REFIT_FREQ_DAILY)
    gjr_forecasts_fullday = convert_gjr_to_fullday(gjr_forecasts_raw)
    n_gjr = np.sum(np.isfinite(gjr_forecasts_fullday[is_end:]))
    print(f"  GJR: {n_gjr} OOS forecasts (native full-day, no conversion)")

    # --- Model 2: HAR on RV_total ---
    print("\n[5/9] Running HAR-RV on RV_total (= RV_intra + RV_night)...")
    har_total_raw = har_oos_forecast_on_target(rv_total, is_end, REFIT_FREQ_DAILY, "rv_total")
    har_total_fullday = convert_har_rv_total_to_fullday(har_total_raw, ratios, method='additive')
    n_har_total = np.sum(np.isfinite(har_total_fullday[is_end:]))
    print(f"  HAR(RV_total): {n_har_total} OOS forecasts")
    print(f"    Conversion: ĥ_fullday = ĥ_HAR + mean_gap ({ratios['mean_gap']:.2e})")

    # --- Model 3: HAR on RV_intra only ---
    print("\n[6/9] Running HAR-RV on RV_intra only...")
    har_intra_raw = har_oos_forecast_on_target(rv_intra, is_end, REFIT_FREQ_DAILY, "rv_intra")
    har_intra_fullday = convert_har_intra_to_fullday(har_intra_raw, ratios)
    n_har_intra = np.sum(np.isfinite(har_intra_fullday[is_end:]))
    print(f"  HAR(RV_intra): {n_har_intra} OOS forecasts")
    print(f"    Conversion: ĥ_fullday = ĥ_intra / intra_share ({ratios['intra_share']:.4f})")

    # --- Model 4 & 5: PRG Basic and Extended ---
    print("\n[7/9] Running PRG (Periodic Realized GARCH)...")

    # Build session-level series for PRG
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
        sessions.append({
            'date': dt, 'session_type': 0,
            'r': row['overnight_gap'], 'x': row['r2_overnight'],
        })
        sessions.append({
            'date': dt, 'session_type': 1,
            'r': row['intra_return'], 'x': row['rv_intra'],
        })

    sess_df = pd.DataFrame(sessions)
    r_sess = sess_df['r'].values
    x_sess = sess_df['x'].values
    s_sess = sess_df['session_type'].values
    dates_sess = sess_df['date'].values
    n_sessions = len(sess_df)
    is_end_sess = int(n_sessions * IS_FRACTION)
    if is_end_sess % 2 != 0:
        is_end_sess += 1

    print(f"  Session series: {n_sessions} sessions, IS={is_end_sess}, OOS={n_sessions - is_end_sess}")

    # PRG Basic
    print("  Estimating PRG Basic (6 params)...")
    params_basic, ll_basic = estimate_prg(r_sess[:is_end_sess], x_sess[:is_end_sess],
                                           s_sess[:is_end_sess], extended=False, n_starts=5)

    prg_basic_daily = np.full(n_daily, np.nan)
    prg_basic_fullday = np.full(n_daily, np.nan)

    if params_basic is not None:
        print(f"    omega_0={params_basic[0]:.2e}, alpha_0={params_basic[1]:.4f}, beta_0={params_basic[2]:.4f}")
        print(f"    omega_1={params_basic[3]:.2e}, alpha_1={params_basic[4]:.4f}, beta_1={params_basic[5]:.4f}")

        # Run with refitting
        cur_p = params_basic
        h_run = np.var(r_sess[:50])
        if h_run < 1e-12: h_run = 1e-8
        h_all_sessions = np.zeros(n_sessions)
        h_all_sessions[0] = h_run

        refit_freq_sess = 126  # ~63 days
        for t in range(1, n_sessions):
            st = int(s_sess[t])
            omega = np.array([cur_p[0], cur_p[3]])
            alpha = np.array([cur_p[1], cur_p[4]])
            beta = np.array([cur_p[2], cur_p[5]])
            h_run = omega[st] + alpha[st] * x_sess[t-1] + beta[st] * h_run
            if h_run < 1e-12: h_run = 1e-12
            h_all_sessions[t] = h_run

            if t >= is_end_sess and (t - is_end_sess) % refit_freq_sess == 0 and t > is_end_sess:
                new_p, _ = estimate_prg(r_sess[:t], x_sess[:t], s_sess[:t], extended=False, n_starts=3)
                if new_p is not None:
                    cur_p = new_p

        # Aggregate to daily: h_daily = h_overnight + h_intraday
        # Need to align with daily_df dates
        daily_dates = daily_df.index
        session_dates_unique = pd.to_datetime(pd.Series([d for d in dates_sess[::2]]))

        day_idx = 0
        for i in range(0, n_sessions - 1, 2):
            if i + 1 >= n_sessions: break
            sess_date = pd.Timestamp(dates_sess[i])
            # Find matching daily_df index
            if sess_date in daily_df.index:
                loc = daily_df.index.get_loc(sess_date)
                if loc >= is_end:
                    prg_basic_daily[loc] = h_all_sessions[i] + h_all_sessions[i+1]

        # Convert to full-day
        prg_basic_fullday = convert_prg_to_fullday(prg_basic_daily, ratios)
        n_prg_basic = np.sum(np.isfinite(prg_basic_fullday[is_end:]))
        print(f"  PRG Basic: {n_prg_basic} OOS forecasts")
        print(f"    Conversion: ĥ_fullday = (h_gap + h_intra) / prg_native_share ({ratios['prg_native_share']:.4f})")

    # PRG Extended
    print("  Estimating PRG Extended (8 params, with leverage)...")
    params_ext, ll_ext = estimate_prg(r_sess[:is_end_sess], x_sess[:is_end_sess],
                                       s_sess[:is_end_sess], extended=True, n_starts=5)

    prg_ext_daily = np.full(n_daily, np.nan)
    prg_ext_fullday = np.full(n_daily, np.nan)

    if params_ext is not None:
        print(f"    omega_0={params_ext[0]:.2e}, alpha_0={params_ext[1]:.4f}, beta_0={params_ext[2]:.4f}")
        print(f"    omega_1={params_ext[3]:.2e}, alpha_1={params_ext[4]:.4f}, beta_1={params_ext[5]:.4f}")
        print(f"    gamma_0={params_ext[6]:.4f}, gamma_1={params_ext[7]:.4f}")

        cur_p_ext = params_ext
        h_run_ext = np.var(r_sess[:50])
        if h_run_ext < 1e-12: h_run_ext = 1e-8
        h_ext_sessions = np.zeros(n_sessions)
        h_ext_sessions[0] = h_run_ext

        for t in range(1, n_sessions):
            st = int(s_sess[t])
            omega = np.array([cur_p_ext[0], cur_p_ext[3]])
            alpha = np.array([cur_p_ext[1], cur_p_ext[4]])
            beta = np.array([cur_p_ext[2], cur_p_ext[5]])
            gamma = np.array([cur_p_ext[6], cur_p_ext[7]])
            leverage = gamma[st] * x_sess[t-1] * (1.0 if r_sess[t-1] < 0 else 0.0)
            h_run_ext = omega[st] + alpha[st] * x_sess[t-1] + leverage + beta[st] * h_run_ext
            if h_run_ext < 1e-12: h_run_ext = 1e-12
            h_ext_sessions[t] = h_run_ext

            if t >= is_end_sess and (t - is_end_sess) % refit_freq_sess == 0 and t > is_end_sess:
                new_p, _ = estimate_prg(r_sess[:t], x_sess[:t], s_sess[:t], extended=True, n_starts=3)
                if new_p is not None:
                    cur_p_ext = new_p

        for i in range(0, n_sessions - 1, 2):
            if i + 1 >= n_sessions: break
            sess_date = pd.Timestamp(dates_sess[i])
            if sess_date in daily_df.index:
                loc = daily_df.index.get_loc(sess_date)
                if loc >= is_end:
                    prg_ext_daily[loc] = h_ext_sessions[i] + h_ext_sessions[i+1]

        prg_ext_fullday = convert_prg_to_fullday(prg_ext_daily, ratios)
        n_prg_ext = np.sum(np.isfinite(prg_ext_fullday[is_end:]))
        print(f"  PRG Extended: {n_prg_ext} OOS forecasts")

    # ----------------------------------------------------------
    # 5. Evaluate ALL on σ²_fullday (the SAME target)
    # ----------------------------------------------------------
    print("\n[8/9] Evaluating ALL models on the SAME target (σ²_fullday)...")

    target_oos = sigma2_fullday[is_end:]
    returns_oos = c2c_returns[is_end:]

    all_models = {
        'GJR-GARCH': {
            'forecasts_fullday': gjr_forecasts_fullday,
            'forecasts_native': gjr_forecasts_raw,
            'native_target': sigma2_fullday,  # same as fullday (c2c r² proxy)
            'native_label': 'r²_c2c (daily)',
            'conversion': 'None (native full-day)',
        },
        'HAR(RV_total)': {
            'forecasts_fullday': har_total_fullday,
            'forecasts_native': har_total_raw,
            'native_target': rv_total,
            'native_label': 'RV_intra + RV_night',
            'conversion': 'ĥ + mean_gap',
        },
        'HAR(RV_intra)': {
            'forecasts_fullday': har_intra_fullday,
            'forecasts_native': har_intra_raw,
            'native_target': rv_intra,
            'native_label': 'RV_intra only',
            'conversion': 'ĥ / intra_share',
        },
        'PRG Basic': {
            'forecasts_fullday': prg_basic_fullday,
            'forecasts_native': prg_basic_daily,
            'native_target': r2_gap + rv_intra,
            'native_label': 'r²_gap + RV_intra',
            'conversion': '(h_gap + h_intra) / prg_native_share',
        },
        'PRG Extended': {
            'forecasts_fullday': prg_ext_fullday,
            'forecasts_native': prg_ext_daily,
            'native_target': r2_gap + rv_intra,
            'native_label': 'r²_gap + RV_intra',
            'conversion': '(h_gap + h_intra) / prg_native_share',
        },
    }

    model_results = {}

    for name, mdata in all_models.items():
        print(f"\n  === {name} ===")
        f_fullday = mdata['forecasts_fullday'][is_end:]
        f_native = mdata['forecasts_native'][is_end:]
        native_t = mdata['native_target'][is_end:]

        # QLIKE on common target
        ql_fullday, n_ql = qlike(target_oos, f_fullday)
        print(f"    QLIKE(σ²_fullday): {ql_fullday:.6f}  (n={n_ql})")

        # QLIKE on native target (for transparency)
        ql_native, n_native = qlike(native_t, f_native)
        print(f"    QLIKE(native {mdata['native_label']}): {ql_native:.6f}  (n={n_native})")

        # Spearman on common target
        rho, p_rho = spearman_corr(target_oos, f_fullday)
        print(f"    Spearman(σ²_fullday): {rho:.4f}  (p={p_rho:.2e})")

        # VaR backtest
        sigma_forecasts = np.sqrt(np.clip(f_fullday, 0, None))
        vbt = var_backtest(returns_oos, sigma_forecasts, alpha=0.01)
        if vbt:
            print(f"    VaR 1%: violations={vbt['n_violations']}/{vbt['n_obs']}, "
                  f"rate={vbt['violation_rate']:.4f}, zone={vbt['basel_zone']}, "
                  f"Kupiec p={vbt['kupiec_p']}")

        model_results[name] = {
            'qlike_fullday': ql_fullday,
            'qlike_native': ql_native,
            'native_target_label': mdata['native_label'],
            'conversion_formula': mdata['conversion'],
            'spearman_fullday': rho,
            'spearman_p': p_rho,
            'n_oos': n_ql,
            'var_backtest': vbt,
        }

    # ----------------------------------------------------------
    # DM tests (pairwise)
    # ----------------------------------------------------------
    print("\n  === DM Tests (pairwise, Harvey |t| > 3.0) ===")

    model_names = list(all_models.keys())
    dm_results = {}

    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            name_i = model_names[i]
            name_j = model_names[j]

            f_i = all_models[name_i]['forecasts_fullday'][is_end:]
            f_j = all_models[name_j]['forecasts_fullday'][is_end:]

            loss_i = qlike_loss_array(target_oos, f_i)
            loss_j = qlike_loss_array(target_oos, f_j)

            # Align valid observations
            valid = np.isfinite(loss_i) & np.isfinite(loss_j)
            if valid.sum() < 50:
                continue

            try:
                t_stat, p_val = dm_test(loss_i[valid], loss_j[valid], h=1)
                winner = name_i if t_stat < 0 else name_j
                sig = abs(t_stat) > 3.0

                key = f"{name_i} vs {name_j}"
                dm_results[key] = {
                    't_stat': round(float(t_stat), 4),
                    'p_value': round(float(p_val), 6),
                    'significant': sig,
                    'winner': winner,
                }

                sig_mark = " ***" if sig else ""
                print(f"    {key}: t={t_stat:.4f}, p={p_val:.6f} → {winner}{sig_mark}")
            except Exception as e:
                print(f"    {name_i} vs {name_j}: DM test failed ({e})")

    # ----------------------------------------------------------
    # 6. Charts
    # ----------------------------------------------------------
    print("\n[9/9] Generating charts...")
    make_charts(model_results, daily_df, is_end, CHARTS_DIR)

    # ----------------------------------------------------------
    # 7. Save results
    # ----------------------------------------------------------

    # Variance decomposition stats
    df_oos = daily_df.iloc[is_end:]
    s2_oos_mean = df_oos['sigma2_fullday'].mean()
    var_decomp = {
        'sigma2_fullday_mean': float(s2_oos_mean),
        'r2_gap_mean': float(df_oos['r2_gap'].mean()),
        'rv_intra_mean': float(df_oos['rv_intra'].mean()),
        'rv_night_mean': float(df_oos['rv_night'].fillna(0).mean()),
        'gap_share_oos': float(df_oos['r2_gap'].mean() / s2_oos_mean),
        'intra_share_oos': float(df_oos['rv_intra'].mean() / s2_oos_mean),
        'night_share_oos': float(df_oos['rv_night'].fillna(0).mean() / s2_oos_mean),
    }

    results_json = {
        'experiment_id': 'K874d',
        'title': 'Fair Comparison Framework — All Models Predict the SAME Full-Day σ²',
        'date': '2026-04-05',
        'data_source': 'TAIFEX TX tick (volume-selected contract, 2017-05 to 2025-12)',
        'data_period': f"{daily_df.index[0].isoformat()} to {daily_df.index[-1].isoformat()}",
        'n_daily': n_daily,
        'is_days': is_end,
        'oos_days': oos_n,
        'is_period': f"{daily_df.index[0].date()} to {daily_df.index[is_end-1].date()}",
        'oos_period': f"{daily_df.index[is_end].date()} to {daily_df.index[-1].date()}",
        'common_target': 'σ²_fullday = r²_gap + RV_intra + RV_night',
        'common_target_description': (
            'Full-day variance decomposed into three additive components: '
            '(1) squared overnight gap return (prev close -> today open), '
            '(2) 5-min realized variance during regular session (8:45-13:45), '
            '(3) 5-min realized variance during night session (15:00-05:00).'
        ),
        'variance_decomposition_oos': var_decomp,
        'scaling_ratios_is': ratios,
        'methodology': {
            'GJR-GARCH': 'GJR-GARCH(1,1) on c2c returns. Predicts h_t=E[r²_daily]. Conversion: NONE (native).',
            'HAR(RV_total)': 'HAR-RV on log(RV_intra+RV_night). Conversion: ĥ + mean_gap.',
            'HAR(RV_intra)': 'HAR-RV on log(RV_intra only). Conversion: ĥ / intra_share.',
            'PRG_Basic': 'Periodic Realized GARCH (6 params). Predicts h_gap+h_intra. Conversion: native/prg_native_share.',
            'PRG_Extended': 'PRG + leverage (8 params). Predicts h_gap+h_intra. Conversion: native/prg_native_share.',
            'refit_freq_daily': REFIT_FREQ_DAILY,
            'is_fraction': IS_FRACTION,
        },
        'model_results': model_results,
        'dm_tests': dm_results,
        'key_finding': '',  # filled below
        'conclusions': {},  # filled below
        'references': [
            'Hansen & Lunde (2005): Optimal realized variance weighting',
            'Patton (2011): QLIKE proxy-robust loss',
            'Corsi (2009): HAR-RV model',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
            'Diebold & Mariano (1995), Harvey et al. (1997): DM test',
            'Kupiec (1995): Proportion of failures test for VaR',
            'Christoffersen (1998): Conditional coverage test for VaR',
        ],
    }

    # Determine best model
    qlikes_all = {name: data['qlike_fullday'] for name, data in model_results.items()
                  if data['qlike_fullday'] is not None}
    if qlikes_all:
        best_model = min(qlikes_all, key=qlikes_all.get)
        best_qlike = qlikes_all[best_model]

        results_json['conclusions'] = {
            'best_model_common_target': best_model,
            'best_qlike_fullday': best_qlike,
            'all_qlike_fullday': {k: round(v, 6) for k, v in sorted(qlikes_all.items(), key=lambda x: x[1])},
            'ranking': list(dict(sorted(qlikes_all.items(), key=lambda x: x[1])).keys()),
        }

        # K874c claimed HAR >> GJR with t=-11.14. Check if that still holds on fair target.
        har_vs_gjr = None
        for key, val in dm_results.items():
            if 'HAR(RV_total)' in key and 'GJR-GARCH' in key:
                har_vs_gjr = val

        k874c_finding = ("K874c claimed HAR >> GJR (DM t=-11.14) but compared on different targets. ")
        if har_vs_gjr:
            k874c_finding += (f"On the FAIR common target: DM t={har_vs_gjr['t_stat']:.4f}, "
                             f"winner={har_vs_gjr['winner']}, significant={har_vs_gjr['significant']}.")

        results_json['key_finding'] = (
            f"Best model on σ²_fullday: {best_model} (QLIKE={best_qlike:.6f}). "
            f"{k874c_finding} "
            f"Variance decomposition (OOS): gap={var_decomp['gap_share_oos']:.1%}, "
            f"intra={var_decomp['intra_share_oos']:.1%}, night={var_decomp['night_share_oos']:.1%}."
        )

    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {OUTPUT_FILE}")

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY: Fair Comparison on σ²_fullday")
    print("=" * 70)
    if qlikes_all:
        print(f"\nRanking (QLIKE on common target σ²_fullday):")
        for rank, (name, ql) in enumerate(sorted(qlikes_all.items(), key=lambda x: x[1]), 1):
            sp = model_results[name]['spearman_fullday']
            vbt = model_results[name].get('var_backtest', {})
            zone = vbt.get('basel_zone', 'N/A') if vbt else 'N/A'
            print(f"  #{rank}: {name:20s} QLIKE={ql:.6f}  Spearman={sp:.4f}  VaR zone={zone}")

    print(f"\nVariance decomposition (OOS):")
    print(f"  r²_gap:    {var_decomp['gap_share_oos']:.1%}")
    print(f"  RV_intra:  {var_decomp['intra_share_oos']:.1%}")
    print(f"  RV_night:  {var_decomp['night_share_oos']:.1%}")

    if dm_results:
        print(f"\nDM tests (Harvey |t| > 3.0):")
        for key, val in dm_results.items():
            sig_mark = "***" if val['significant'] else "   "
            print(f"  {sig_mark} {key:40s} t={val['t_stat']:+7.4f}  → {val['winner']}")

    print(f"\n{'='*70}")
    print("K874d: FAIR comparison done. All models evaluated on SAME σ²_fullday target.")
    print(f"{'='*70}")


if __name__ == '__main__':
    main()
