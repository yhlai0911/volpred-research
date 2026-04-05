#!/usr/bin/env python3
"""
K874c: Periodic Realized GARCH — Unified Recursive System with Session Switching
=================================================================================

Research Question (EMPIRICAL):
  Does a SINGLE unified variance recursion with session-switching parameters
  outperform separate models (HAR, GJR, separate-session GARCH)?

  KEY INSIGHT from K874/K874b:
  - K874: Cross-session info is REAL (overnight→intraday t=8.08)
  - K874b: Adding cross-info as HAR regressors → NO OOS improvement
  - The information must flow through the RECURSION ITSELF, not regressors

The Model: Periodic Realized GARCH (PRG):
  For each observation n (alternating sessions):
    h_n = ω_{s_n} + α_{s_n} · x_{n-1} + β_{s_n} · h_{n-1}

  Where:
  - s_n = session type (0=overnight, 1=intraday)
  - x_{n-1} = realized measure from PREVIOUS session
  - h_{n-1} = variance from PREVIOUS session (CARRIES OVER)
  - Parameters switch based on current session type

  Extended with leverage:
    h_n = ω_{s_n} + α_{s_n}·x_{n-1} + γ_{s_n}·x_{n-1}·I(r_{n-1}<0) + β_{s_n}·h_{n-1}

Benchmarks:
  a. HAR-RV on log(RV_total) — daily frequency
  b. GJR-GARCH on close-to-close returns — daily frequency
  c. Separate GARCH per session (NO cross-recursion) — isolates cross-info value
  d. PRG (this model) — session frequency with cross-recursion

Data:
  - TAIFEX TX tick (2017-05 to 2025-12, volume-selected contract)
  - Session-level time series: overnight gap + intraday RV

Error log rules:
  - DM test: use dm_test from volpred.stats.model_evaluation (Newey-West HAC)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1]) — THE CORE OF THIS MODEL
  - TX: volume-based contract selection, not TX1
  - shift(1) equivalent: predict next session from current

References:
  - Lai et al. (2024): Periodic GARCH with regime switching (PRS inspiration)
  - Corsi (2009): HAR-RV model
  - Hansen & Lunde (2005): Realized GARCH, optimal RV weighting
  - Patton (2011): QLIKE proxy-robust loss
  - Bollerslev & Ghysels (1996): Periodic GARCH

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
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k874c_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k874c_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Session boundaries (HHMMSS integer)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# OOS config
MIN_SESSIONS = 500   # Minimum training sessions (~250 trading days)
IS_FRACTION = 0.60
REFIT_FREQ = 126     # Refit every 126 sessions (~63 trading days)

NIGHT_SESSION_START_DATE = "2017-05-15"

# ============================================================
# Step 1: Build session-level RV from tick data
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
    """Process one TX daily file -> session-level RV and prices."""
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

    # Intraday return
    day_return = np.log(day_close / day_open) if (day_open > 0 and not np.isnan(day_open) and not np.isnan(day_close)) else np.nan
    # Night return (15:00 open to ~05:00 close)
    night_return = np.log(night_close / night_open) if (night_open > 0 and not np.isnan(night_open) and not np.isnan(night_close)) else np.nan

    rv_total = rv_day + rv_night if (not np.isnan(rv_day) and not np.isnan(rv_night)) else (rv_day if not np.isnan(rv_day) else np.nan)

    return {
        'date': date_str,
        'rv_day': rv_day if not np.isnan(rv_day) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'rv_total': rv_total if not np.isnan(rv_total) else None,
        'day_open': day_open if not np.isnan(day_open) else None,
        'day_close': day_close if not np.isnan(day_close) else None,
        'night_open': night_open if not np.isnan(night_open) else None,
        'night_close': night_close if not np.isnan(night_close) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
        'night_return': night_return if not np.isnan(night_return) else None,
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
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


# ============================================================
# Step 2: Build session-level alternating series
# ============================================================

def build_session_series(rv_df):
    """
    Build alternating session series from daily data.
    For each trading day t:
      - Session 2*t (type=0, overnight):
        r = overnight gap = log(day_open_t / day_close_{t-1})
        x = r² (squared overnight return)
      - Session 2*t+1 (type=1, intraday):
        r = log(day_close_t / day_open_t) = intraday return
        x = RV_intra (5-min realized variance)

    Returns DataFrame with columns:
      date, session_type (0/1), r, x (realized measure), target_variance
    """
    df = rv_df.copy()
    df = df.dropna(subset=['day_open', 'day_close', 'rv_day'])

    # Compute overnight gap
    df['prev_day_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_day_close'])
    df['r2_overnight'] = df['overnight_gap'] ** 2

    # Drop first row (no previous close for overnight gap)
    df = df.iloc[1:]

    sessions = []
    dates = df.index.tolist()

    for i, dt in enumerate(dates):
        row = df.loc[dt]

        # Only include if we have valid data for both sessions
        if pd.isna(row['overnight_gap']) or pd.isna(row['day_return']) or pd.isna(row['rv_day']):
            continue

        # Session type 0: overnight (gap)
        sessions.append({
            'date': dt,
            'session_type': 0,  # overnight
            'r': row['overnight_gap'],
            'x': row['r2_overnight'],  # realized measure = r²_overnight
            'target': row['r2_overnight'],  # target for evaluation
        })

        # Session type 1: intraday
        sessions.append({
            'date': dt,
            'session_type': 1,  # intraday
            'r': row['day_return'],
            'x': row['rv_day'],  # realized measure = 5-min RV
            'target': row['rv_day'],  # target for evaluation
        })

    sess_df = pd.DataFrame(sessions)
    print(f"  Built session series: {len(sess_df)} sessions from {len(dates)} days")
    print(f"    Overnight sessions: {(sess_df['session_type']==0).sum()}")
    print(f"    Intraday sessions: {(sess_df['session_type']==1).sum()}")

    return sess_df


# ============================================================
# Step 3: Periodic Realized GARCH - MLE Estimation
# ============================================================

def prg_loglik(params, r, x, s, extended=False):
    """
    Periodic Realized GARCH negative log-likelihood.

    params (basic 6): [omega_0, alpha_0, beta_0, omega_1, alpha_1, beta_1]
    params (extended 8): + [gamma_0, gamma_1]

    r: return series (session-level)
    x: realized measure series (session-level)
    s: session type series (0 or 1)

    Returns negative log-likelihood (for minimization).
    """
    n = len(r)

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

    # Initialize h with unconditional variance
    h = np.zeros(n)
    h[0] = np.var(r[:min(50, n)])  # start from sample variance
    if h[0] < 1e-12:
        h[0] = 1e-8

    ll = 0.0
    for t in range(1, n):
        st = int(s[t])
        # Cross-session recursion: h_t depends on x_{t-1} and h_{t-1}
        # x_{t-1} is from the PREVIOUS session (different type!)
        leverage = gamma[st] * x[t-1] * (1.0 if r[t-1] < 0 else 0.0)
        h[t] = omega[st] + alpha[st] * x[t-1] + leverage + beta[st] * h[t-1]

        # Floor
        if h[t] < 1e-12:
            h[t] = 1e-12

    # Log-likelihood: Normal(r_t | 0, h_t)
    # ll = sum(-0.5 * log(2*pi) - 0.5*log(h_t) - 0.5*r_t^2/h_t)
    for t in range(1, n):
        if h[t] > 1e-12:
            ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h[t]) - 0.5 * r[t]**2 / h[t]
        else:
            ll += -100.0  # penalty for degenerate variance

    return -ll  # negative for minimization


def prg_forecast(params, r, x, s, h_prev, extended=False):
    """
    Given parameters and previous session info, forecast next session variance.

    h_prev: variance from previous session
    r[-1], x[-1]: return and realized measure from previous session
    s_next: session type of next session

    Returns h_next.
    """
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

    s_next = int(s)
    leverage = gamma[s_next] * x * (1.0 if r < 0 else 0.0)
    h_next = omega[s_next] + alpha[s_next] * x + leverage + beta[s_next] * h_prev
    return max(h_next, 1e-12)


def estimate_prg(r, x, s, extended=False, n_starts=5):
    """
    Estimate PRG via MLE with multiple random starts.

    Returns: best_params, best_loglik
    """
    n_params = 8 if extended else 6

    # Bounds
    eps = 1e-8
    if extended:
        bounds = [
            (eps, 1e-3),    # omega_0
            (eps, 1.0),     # alpha_0
            (eps, 0.999),   # beta_0
            (eps, 1e-3),    # omega_1
            (eps, 1.0),     # alpha_1
            (eps, 0.999),   # beta_1
            (0.0, 1.0),     # gamma_0 (leverage for overnight)
            (0.0, 1.0),     # gamma_1 (leverage for intraday)
        ]
    else:
        bounds = [
            (eps, 1e-3),    # omega_0
            (eps, 1.0),     # alpha_0
            (eps, 0.999),   # beta_0
            (eps, 1e-3),    # omega_1
            (eps, 1.0),     # alpha_1
            (eps, 0.999),   # beta_1
        ]

    best_nll = np.inf
    best_params = None

    # Sample variances for initialization
    var_overnight = np.var(r[s == 0]) if np.sum(s == 0) > 10 else 1e-5
    var_intraday = np.var(r[s == 1]) if np.sum(s == 1) > 10 else 1e-5

    rng = np.random.RandomState(42)

    for start_i in range(n_starts):
        if start_i == 0:
            # Default sensible start
            x0 = [
                var_overnight * 0.05,  # omega_0
                0.15,                   # alpha_0
                0.80,                   # beta_0
                var_intraday * 0.05,   # omega_1
                0.15,                   # alpha_1
                0.80,                   # beta_1
            ]
            if extended:
                x0 += [0.05, 0.05]
        else:
            # Random perturbation
            x0 = [
                rng.uniform(1e-8, 5e-4),
                rng.uniform(0.05, 0.40),
                rng.uniform(0.50, 0.95),
                rng.uniform(1e-8, 5e-4),
                rng.uniform(0.05, 0.40),
                rng.uniform(0.50, 0.95),
            ]
            if extended:
                x0 += [rng.uniform(0.0, 0.2), rng.uniform(0.0, 0.2)]

        try:
            result = minimize(
                prg_loglik, x0, args=(r, x, s, extended),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 2000, 'ftol': 1e-10}
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def prg_recursive_oos(params, r_all, x_all, s_all, start_idx, extended=False):
    """
    Run recursive OOS forecast from start_idx to end.
    Returns array of h forecasts aligned with observations.

    CRITICAL: h[t] is the forecast BEFORE observing session t.
    We use x[t-1], r[t-1], h[t-1] to forecast h[t].
    """
    n = len(r_all)
    h = np.full(n, np.nan)

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

    # Initialize from in-sample: compute h through training period
    h[0] = np.var(r_all[:min(50, start_idx)])
    if h[0] < 1e-12:
        h[0] = 1e-8

    for t in range(1, n):
        st = int(s_all[t])
        leverage = gamma[st] * x_all[t-1] * (1.0 if r_all[t-1] < 0 else 0.0)
        h[t] = omega[st] + alpha[st] * x_all[t-1] + leverage + beta[st] * h[t-1]
        if h[t] < 1e-12:
            h[t] = 1e-12

    return h


# ============================================================
# Step 4: Separate GARCH per session (benchmark)
# ============================================================

def estimate_separate_garch(r, x, s, session_type):
    """
    Estimate a standard GARCH(1,1) on ONE session type only.
    h_t = omega + alpha * x_{t-1} + beta * h_{t-1}
    where x_{t-1} is the realized measure from the SAME session type (skip other type).
    """
    # Extract only this session type
    mask = s == session_type
    r_sess = r[mask]
    x_sess = x[mask]

    n = len(r_sess)
    if n < 30:
        return None, None

    def neg_loglik(params):
        omega, alpha, beta = params
        h = np.zeros(n)
        h[0] = np.var(r_sess[:min(30, n)])
        if h[0] < 1e-12:
            h[0] = 1e-8

        ll = 0.0
        for t in range(1, n):
            h[t] = omega + alpha * x_sess[t-1] + beta * h[t-1]
            if h[t] < 1e-12:
                h[t] = 1e-12
            ll += -0.5 * np.log(2*np.pi) - 0.5*np.log(h[t]) - 0.5*r_sess[t]**2/h[t]
        return -ll

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 1.0), (eps, 0.999)]

    best_nll = np.inf
    best_params = None
    var_sess = np.var(r_sess)
    rng = np.random.RandomState(42)

    for i in range(5):
        if i == 0:
            x0 = [var_sess * 0.05, 0.15, 0.80]
        else:
            x0 = [rng.uniform(1e-8, 5e-4), rng.uniform(0.05, 0.4), rng.uniform(0.5, 0.95)]

        try:
            result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 1000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_params = result.x
        except Exception:
            continue

    return best_params, -best_nll if best_params is not None else None


def separate_garch_recursive_oos(params_0, params_1, r_all, x_all, s_all):
    """
    Run separate GARCH for each session type.
    NO cross-session recursion: each session's h only depends on same-type history.
    """
    n = len(r_all)
    h = np.full(n, np.nan)

    # Track separate h for each session type
    h_state = {0: 1e-6, 1: 1e-6}

    # Initialize from first observations
    mask0 = s_all == 0
    mask1 = s_all == 1
    h_state[0] = np.var(r_all[mask0][:min(50, mask0.sum())]) if mask0.sum() > 10 else 1e-6
    h_state[1] = np.var(r_all[mask1][:min(50, mask1.sum())]) if mask1.sum() > 10 else 1e-6

    if h_state[0] < 1e-12: h_state[0] = 1e-8
    if h_state[1] < 1e-12: h_state[1] = 1e-8

    # Counters for each session type to track previous same-type observation
    prev_x = {0: None, 1: None}

    for t in range(n):
        st = int(s_all[t])
        params = params_0 if st == 0 else params_1

        if params is None:
            h[t] = h_state[st]
            prev_x[st] = x_all[t]
            continue

        omega, alpha, beta = params

        if prev_x[st] is not None:
            h_new = omega + alpha * prev_x[st] + beta * h_state[st]
            h_new = max(h_new, 1e-12)
            h_state[st] = h_new
            h[t] = h_new
        else:
            h[t] = h_state[st]

        prev_x[st] = x_all[t]

    return h


# ============================================================
# Step 5: HAR-RV benchmark (daily frequency)
# ============================================================

def har_oos_forecast(rv_total, is_end, refit_freq=63):
    """
    HAR-RV OOS: predict log(RV_total_{t+1}) from HAR(d,w,m) lags.
    """
    eps = 1e-12
    log_rv = np.log(np.clip(rv_total, eps, None))
    n = len(log_rv)

    # Build features
    log_rv_d = pd.Series(log_rv).shift(1).values
    log_rv_5d = pd.Series(log_rv).rolling(5).mean().shift(1).values
    log_rv_22d = pd.Series(log_rv).rolling(22).mean().shift(1).values

    forecasts = np.full(n, np.nan)

    for t in range(is_end, n):
        # Refit check
        if (t - is_end) % refit_freq == 0 or t == is_end:
            # Fit on data up to t
            train_end = t
            train_start = 22  # need 22-day lag

            y_train = log_rv[train_start:train_end]
            X_train = np.column_stack([
                log_rv_d[train_start:train_end],
                log_rv_5d[train_start:train_end],
                log_rv_22d[train_start:train_end],
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

        # Forecast
        if np.isfinite(log_rv_d[t]) and np.isfinite(log_rv_5d[t]) and np.isfinite(log_rv_22d[t]):
            x_t = np.array([1.0, log_rv_d[t], log_rv_5d[t], log_rv_22d[t]])
            log_forecast = x_t @ beta
            forecasts[t] = np.exp(log_forecast)  # back to level

    return forecasts


# ============================================================
# Step 6: GJR-GARCH benchmark (daily, on close-to-close)
# ============================================================

def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """
    GJR-GARCH(1,1) on daily close-to-close returns.
    h_t = omega + alpha*r²_{t-1} + gamma*r²_{t-1}*I(r_{t-1}<0) + beta*h_{t-1}
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


# ============================================================
# Step 7: Evaluation metrics
# ============================================================

def qlike(realized, forecast):
    """QLIKE loss: realized/forecast - log(realized/forecast) - 1."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    r = realized[valid]
    f = forecast[valid]
    return float(np.mean(r/f - np.log(r/f) - 1))


def mse(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean((realized[valid] - forecast[valid])**2))


def mae(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    return float(np.mean(np.abs(realized[valid] - forecast[valid])))


def spearman_corr(realized, forecast):
    valid = np.isfinite(realized) & np.isfinite(forecast)
    if valid.sum() < 10:
        return np.nan, np.nan
    rho, p = sp_stats.spearmanr(realized[valid], forecast[valid])
    return float(rho), float(p)


def qlike_loss_array(realized, forecast):
    """Per-observation QLIKE losses for DM test."""
    valid = np.isfinite(realized) & np.isfinite(forecast) & (forecast > 0) & (realized > 0)
    loss = np.full(len(realized), np.nan)
    r = realized[valid]
    f = forecast[valid]
    loss[valid] = r/f - np.log(r/f) - 1
    return loss


# ============================================================
# Step 8: Charts
# ============================================================

def make_charts(results_dict, daily_df, charts_dir):
    """Generate comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    models = []
    qlikes = []
    for name, data in results_dict.items():
        if 'qlike_total' in data and data['qlike_total'] is not None:
            models.append(name)
            qlikes.append(data['qlike_total'])

    if len(models) > 0:
        colors = ['#e74c3c' if q == min(qlikes) else '#3498db' for q in qlikes]
        bars = ax.barh(range(len(models)), qlikes, color=colors)
        ax.set_yticks(range(len(models)))
        ax.set_yticklabels(models, fontsize=10)
        ax.set_xlabel('QLIKE (lower = better)', fontsize=12)
        ax.set_title('K874c: Total Daily QLIKE Comparison\nPeriodic Realized GARCH vs Benchmarks', fontsize=13)
        ax.invert_yaxis()
        for bar, val in zip(bars, qlikes):
            ax.text(bar.get_width() + 0.001, bar.get_y() + bar.get_height()/2,
                    f'{val:.4f}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'qlike_comparison.png'), dpi=150)
        plt.close()

    # Chart 2: Session-level QLIKE
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax_i, (sess_name, key) in enumerate([('Overnight', 'qlike_overnight'), ('Intraday', 'qlike_intraday')]):
        models_s = []
        qlikes_s = []
        for name, data in results_dict.items():
            if key in data and data[key] is not None:
                models_s.append(name)
                qlikes_s.append(data[key])

        if len(models_s) > 0:
            colors = ['#e74c3c' if q == min(qlikes_s) else '#95a5a6' for q in qlikes_s]
            axes[ax_i].barh(range(len(models_s)), qlikes_s, color=colors)
            axes[ax_i].set_yticks(range(len(models_s)))
            axes[ax_i].set_yticklabels(models_s, fontsize=9)
            axes[ax_i].set_xlabel('QLIKE', fontsize=11)
            axes[ax_i].set_title(f'{sess_name} Session QLIKE', fontsize=12)
            axes[ax_i].invert_yaxis()

    plt.suptitle('K874c: Session-Level QLIKE Comparison', fontsize=13)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'session_qlike.png'), dpi=150)
    plt.close()

    # Chart 3: Spearman rank correlation comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    models_sp = []
    rhos = []
    for name, data in results_dict.items():
        if 'spearman_total' in data and data['spearman_total'] is not None:
            models_sp.append(name)
            rhos.append(data['spearman_total'])

    if len(models_sp) > 0:
        colors = ['#e74c3c' if r == max(rhos) else '#3498db' for r in rhos]
        bars = ax.barh(range(len(models_sp)), rhos, color=colors)
        ax.set_yticks(range(len(models_sp)))
        ax.set_yticklabels(models_sp, fontsize=10)
        ax.set_xlabel('Spearman Rank Correlation (higher = better)', fontsize=12)
        ax.set_title('K874c: Spearman Correlation on Total Daily Variance', fontsize=13)
        ax.invert_yaxis()
        for bar, val in zip(bars, rhos):
            ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height()/2,
                    f'{val:.4f}', va='center', fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(charts_dir, 'spearman_comparison.png'), dpi=150)
        plt.close()

    # Chart 4: Rolling QLIKE (252-session ≈ 126-day window)
    fig, ax = plt.subplots(figsize=(14, 6))
    for name, data in results_dict.items():
        if 'daily_qlike_series' in data and data['daily_qlike_series'] is not None:
            series = np.array(data['daily_qlike_series'])
            dates = data.get('daily_dates', [])
            if len(series) > 63:
                rolling = pd.Series(series).rolling(63, min_periods=30).mean().values
                ax.plot(range(len(rolling)), rolling, label=name, alpha=0.8)

    ax.set_xlabel('OOS Trading Day', fontsize=12)
    ax.set_ylabel('Rolling 63-day Mean QLIKE', fontsize=12)
    ax.set_title('K874c: Rolling QLIKE Over OOS Period', fontsize=13)
    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(charts_dir, 'rolling_qlike.png'), dpi=150)
    plt.close()

    print(f"  Charts saved to {charts_dir}")


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K874c: Periodic Realized GARCH — Unified Recursive System")
    print("=" * 70)

    # ----------------------------------------------------------
    # 1. Load tick data and compute session-level RV
    # ----------------------------------------------------------
    print("\n[1/8] Loading TAIFEX TX tick data...")
    rv_df = load_all_rv_data()
    print(f"  Loaded {len(rv_df)} trading days: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")

    # ----------------------------------------------------------
    # 2. Build alternating session series
    # ----------------------------------------------------------
    print("\n[2/8] Building alternating session series...")
    sess_df = build_session_series(rv_df)

    # Descriptive stats
    r_arr = sess_df['r'].values
    x_arr = sess_df['x'].values
    s_arr = sess_df['session_type'].values
    dates_arr = sess_df['date'].values
    targets_arr = sess_df['target'].values

    desc_stats = {}
    for stype, sname in [(0, 'overnight'), (1, 'intraday')]:
        mask = s_arr == stype
        r_s = r_arr[mask]
        x_s = x_arr[mask]
        desc_stats[sname] = {
            'n': int(mask.sum()),
            'r_mean': float(np.nanmean(r_s)),
            'r_std': float(np.nanstd(r_s)),
            'r_skew': float(sp_stats.skew(r_s[np.isfinite(r_s)])),
            'r_kurt': float(sp_stats.kurtosis(r_s[np.isfinite(r_s)])),
            'x_mean': float(np.nanmean(x_s)),
            'x_median': float(np.nanmedian(x_s)),
            'x_std': float(np.nanstd(x_s)),
        }
        print(f"\n  {sname.upper()} session (n={desc_stats[sname]['n']}):")
        print(f"    Return: mean={desc_stats[sname]['r_mean']:.6f}, std={desc_stats[sname]['r_std']:.6f}")
        print(f"    Realized: mean={desc_stats[sname]['x_mean']:.2e}, median={desc_stats[sname]['x_median']:.2e}")

    # ----------------------------------------------------------
    # 3. Define OOS split (session-level)
    # ----------------------------------------------------------
    n_sessions = len(sess_df)
    is_end = int(n_sessions * IS_FRACTION)
    # Make sure IS ends at an even index (complete day)
    if is_end % 2 != 0:
        is_end += 1
    oos_n = n_sessions - is_end

    print(f"\n[3/8] OOS split: IS={is_end} sessions, OOS={oos_n} sessions")
    print(f"  IS dates: {dates_arr[0]} to {dates_arr[is_end-1]}")
    print(f"  OOS dates: {dates_arr[is_end]} to {dates_arr[-1]}")

    # ----------------------------------------------------------
    # 4. Estimate PRG (basic and extended)
    # ----------------------------------------------------------
    print("\n[4/8] Estimating Periodic Realized GARCH models...")

    # 4a. PRG Basic (6 parameters)
    print("  PRG Basic (6 params)...")
    r_is = r_arr[:is_end]
    x_is = x_arr[:is_end]
    s_is = s_arr[:is_end]

    params_basic, ll_basic = estimate_prg(r_is, x_is, s_is, extended=False, n_starts=5)
    if params_basic is not None:
        print(f"    omega_0={params_basic[0]:.2e}, alpha_0={params_basic[1]:.4f}, beta_0={params_basic[2]:.4f}")
        print(f"    omega_1={params_basic[3]:.2e}, alpha_1={params_basic[4]:.4f}, beta_1={params_basic[5]:.4f}")
        pers_0 = params_basic[1] + params_basic[2]
        pers_1 = params_basic[4] + params_basic[5]
        print(f"    Persistence: overnight={pers_0:.4f}, intraday={pers_1:.4f}")
        print(f"    Log-likelihood: {ll_basic:.2f}")
    else:
        print("    FAILED to estimate PRG Basic!")

    # 4b. PRG Extended (8 parameters with leverage)
    print("  PRG Extended (8 params, with leverage)...")
    params_ext, ll_ext = estimate_prg(r_is, x_is, s_is, extended=True, n_starts=5)
    if params_ext is not None:
        print(f"    omega_0={params_ext[0]:.2e}, alpha_0={params_ext[1]:.4f}, beta_0={params_ext[2]:.4f}")
        print(f"    omega_1={params_ext[3]:.2e}, alpha_1={params_ext[4]:.4f}, beta_1={params_ext[5]:.4f}")
        print(f"    gamma_0={params_ext[6]:.4f}, gamma_1={params_ext[7]:.4f}")
        pers_0e = params_ext[1] + params_ext[2]
        pers_1e = params_ext[4] + params_ext[5]
        print(f"    Persistence: overnight={pers_0e:.4f}, intraday={pers_1e:.4f}")
        print(f"    Log-likelihood: {ll_ext:.2f}")
    else:
        print("    FAILED to estimate PRG Extended!")

    # 4c. Separate GARCH per session
    print("  Separate GARCH (per session, no cross-recursion)...")
    sep_params_0, sep_ll_0 = estimate_separate_garch(r_is, x_is, s_is, session_type=0)
    sep_params_1, sep_ll_1 = estimate_separate_garch(r_is, x_is, s_is, session_type=1)
    if sep_params_0 is not None:
        print(f"    Overnight: omega={sep_params_0[0]:.2e}, alpha={sep_params_0[1]:.4f}, beta={sep_params_0[2]:.4f}")
    if sep_params_1 is not None:
        print(f"    Intraday: omega={sep_params_1[0]:.2e}, alpha={sep_params_1[1]:.4f}, beta={sep_params_1[2]:.4f}")

    # ----------------------------------------------------------
    # 5. OOS Forecasting with periodic refitting
    # ----------------------------------------------------------
    print("\n[5/8] OOS Forecasting (recursive, with periodic refitting)...")

    # PRG Basic OOS with refitting
    h_basic_all = np.full(n_sessions, np.nan)
    current_params_basic = params_basic

    for t in range(is_end, n_sessions):
        # Refit check
        if (t - is_end) % REFIT_FREQ == 0 and t > is_end:
            print(f"    PRG Basic refit at session {t}...")
            r_train = r_arr[:t]
            x_train = x_arr[:t]
            s_train = s_arr[:t]
            new_params, new_ll = estimate_prg(r_train, x_train, s_train, extended=False, n_starts=3)
            if new_params is not None:
                current_params_basic = new_params

    # Run full recursive forecast with final params
    if current_params_basic is not None:
        h_basic_all = prg_recursive_oos(params_basic, r_arr, x_arr, s_arr, is_end, extended=False)
        # Re-run with refitting: track params changes
        h_basic_refit = np.full(n_sessions, np.nan)
        cur_p = params_basic
        # Initialize h through IS
        h_tmp = np.var(r_arr[:50])
        if h_tmp < 1e-12: h_tmp = 1e-8
        h_run = h_tmp

        for t in range(1, n_sessions):
            st = int(s_arr[t])
            omega = np.array([cur_p[0], cur_p[3]])
            alpha = np.array([cur_p[1], cur_p[4]])
            beta = np.array([cur_p[2], cur_p[5]])
            h_run = omega[st] + alpha[st] * x_arr[t-1] + beta[st] * h_run
            if h_run < 1e-12: h_run = 1e-12
            h_basic_refit[t] = h_run

            # Refit periodically in OOS
            if t >= is_end and (t - is_end) % REFIT_FREQ == 0 and t > is_end:
                new_p, _ = estimate_prg(r_arr[:t], x_arr[:t], s_arr[:t], extended=False, n_starts=3)
                if new_p is not None:
                    cur_p = new_p

        h_basic_all = h_basic_refit
        print(f"  PRG Basic: {np.sum(np.isfinite(h_basic_all[is_end:]))} OOS forecasts")

    # PRG Extended OOS with refitting
    h_ext_all = np.full(n_sessions, np.nan)
    if params_ext is not None:
        cur_p_ext = params_ext
        h_run_ext = np.var(r_arr[:50])
        if h_run_ext < 1e-12: h_run_ext = 1e-8

        for t in range(1, n_sessions):
            st = int(s_arr[t])
            omega = np.array([cur_p_ext[0], cur_p_ext[3]])
            alpha = np.array([cur_p_ext[1], cur_p_ext[4]])
            beta = np.array([cur_p_ext[2], cur_p_ext[5]])
            gamma = np.array([cur_p_ext[6], cur_p_ext[7]])
            leverage = gamma[st] * x_arr[t-1] * (1.0 if r_arr[t-1] < 0 else 0.0)
            h_run_ext = omega[st] + alpha[st] * x_arr[t-1] + leverage + beta[st] * h_run_ext
            if h_run_ext < 1e-12: h_run_ext = 1e-12
            h_ext_all[t] = h_run_ext

            if t >= is_end and (t - is_end) % REFIT_FREQ == 0 and t > is_end:
                new_p, _ = estimate_prg(r_arr[:t], x_arr[:t], s_arr[:t], extended=True, n_starts=3)
                if new_p is not None:
                    cur_p_ext = new_p

        print(f"  PRG Extended: {np.sum(np.isfinite(h_ext_all[is_end:]))} OOS forecasts")

    # Separate GARCH OOS with refitting
    h_sep_all = np.full(n_sessions, np.nan)
    cur_sep_0 = sep_params_0
    cur_sep_1 = sep_params_1

    # For separate: track h per session type independently
    h_state_sep = {0: np.var(r_arr[s_arr==0][:50]) if (s_arr==0).sum() > 10 else 1e-6,
                   1: np.var(r_arr[s_arr==1][:50]) if (s_arr==1).sum() > 10 else 1e-6}
    prev_x_sep = {0: None, 1: None}

    for t in range(n_sessions):
        st = int(s_arr[t])
        p_sep = cur_sep_0 if st == 0 else cur_sep_1

        if p_sep is not None and prev_x_sep[st] is not None:
            omega, alpha, beta = p_sep
            h_new = omega + alpha * prev_x_sep[st] + beta * h_state_sep[st]
            h_new = max(h_new, 1e-12)
            h_state_sep[st] = h_new
            h_sep_all[t] = h_new
        else:
            h_sep_all[t] = h_state_sep[st]

        prev_x_sep[st] = x_arr[t]

        # Refit periodically in OOS
        if t >= is_end and (t - is_end) % REFIT_FREQ == 0 and t > is_end:
            new_0, _ = estimate_separate_garch(r_arr[:t], x_arr[:t], s_arr[:t], 0)
            new_1, _ = estimate_separate_garch(r_arr[:t], x_arr[:t], s_arr[:t], 1)
            if new_0 is not None: cur_sep_0 = new_0
            if new_1 is not None: cur_sep_1 = new_1

    print(f"  Separate GARCH: {np.sum(np.isfinite(h_sep_all[is_end:]))} OOS forecasts")

    # ----------------------------------------------------------
    # 6. Daily-level benchmarks (HAR-RV, GJR-GARCH)
    # ----------------------------------------------------------
    print("\n[6/8] Daily-level benchmarks (HAR-RV, GJR-GARCH)...")

    # Prepare daily data
    daily_df = rv_df.copy()
    daily_df = daily_df.dropna(subset=['rv_day', 'rv_total', 'day_open', 'day_close'])
    daily_df['prev_close'] = daily_df['day_close'].shift(1)
    daily_df['c2c_return'] = np.log(daily_df['day_close'] / daily_df['prev_close'])
    daily_df = daily_df.dropna(subset=['c2c_return', 'rv_total'])

    n_daily = len(daily_df)
    is_end_daily = int(n_daily * IS_FRACTION)

    rv_total_daily = daily_df['rv_total'].values
    c2c_returns = daily_df['c2c_return'].values
    daily_dates = daily_df.index.tolist()

    print(f"  Daily data: {n_daily} days, IS={is_end_daily}, OOS={n_daily - is_end_daily}")

    # HAR-RV
    print("  HAR-RV OOS...")
    har_forecasts = har_oos_forecast(rv_total_daily, is_end_daily, refit_freq=63)
    print(f"    HAR-RV: {np.sum(np.isfinite(har_forecasts[is_end_daily:]))} OOS forecasts")

    # GJR-GARCH
    print("  GJR-GARCH OOS...")
    gjr_forecasts = gjr_oos_forecast(c2c_returns, is_end_daily, refit_freq=63)
    print(f"    GJR-GARCH: {np.sum(np.isfinite(gjr_forecasts[is_end_daily:]))} OOS forecasts")

    # ----------------------------------------------------------
    # 7. Aggregate session-level forecasts to daily
    # ----------------------------------------------------------
    print("\n[7/8] Aggregating session-level forecasts to daily...")

    # For each day: h_daily = h_overnight + h_intraday
    # Session series alternates: overnight, intraday, overnight, intraday, ...
    # So sessions 2k (even) = overnight, 2k+1 (odd) = intraday

    # Map session forecasts to daily
    n_days_sess = n_sessions // 2

    def aggregate_to_daily(h_sessions, s_types, date_list):
        """Sum overnight + intraday h for each day."""
        h_daily = []
        dates_daily = []
        realized_daily = []
        realized_overnight = []
        realized_intraday = []
        h_overnight_list = []
        h_intraday_list = []

        for i in range(0, len(h_sessions) - 1, 2):
            if i + 1 >= len(h_sessions):
                break
            # i = overnight, i+1 = intraday (same date)
            if s_types[i] == 0 and s_types[i+1] == 1:
                h_ov = h_sessions[i]
                h_id = h_sessions[i+1]
                if np.isfinite(h_ov) and np.isfinite(h_id):
                    h_daily.append(h_ov + h_id)
                    h_overnight_list.append(h_ov)
                    h_intraday_list.append(h_id)
                else:
                    h_daily.append(np.nan)
                    h_overnight_list.append(h_ov)
                    h_intraday_list.append(h_id)
                dates_daily.append(date_list[i])
                realized_overnight.append(targets_arr[i])
                realized_intraday.append(targets_arr[i+1])
                realized_daily.append(targets_arr[i] + targets_arr[i+1])

        return (np.array(h_daily), np.array(dates_daily), np.array(realized_daily),
                np.array(realized_overnight), np.array(realized_intraday),
                np.array(h_overnight_list), np.array(h_intraday_list))

    h_basic_daily, dates_basic, rv_realized, rv_overnight, rv_intraday, h_basic_ov, h_basic_id = \
        aggregate_to_daily(h_basic_all, s_arr, dates_arr)
    h_ext_daily, _, _, _, _, h_ext_ov, h_ext_id = \
        aggregate_to_daily(h_ext_all, s_arr, dates_arr)
    h_sep_daily, _, _, _, _, h_sep_ov, h_sep_id = \
        aggregate_to_daily(h_sep_all, s_arr, dates_arr)

    # Determine OOS mask for daily aggregated data
    is_end_agg = is_end // 2
    oos_mask = np.arange(len(h_basic_daily)) >= is_end_agg

    print(f"  Aggregated: {len(h_basic_daily)} days, IS={is_end_agg}, OOS={oos_mask.sum()}")

    # ----------------------------------------------------------
    # 8. Evaluation
    # ----------------------------------------------------------
    print("\n[8/8] Evaluation...")

    results = {}

    # Session-level evaluation (PRG, Separate on their native targets)
    oos_sessions = np.arange(n_sessions) >= is_end

    for model_name, h_all in [('PRG_Basic', h_basic_all), ('PRG_Extended', h_ext_all), ('Separate_GARCH', h_sep_all)]:
        h_oos = h_all[oos_sessions]
        t_oos = targets_arr[oos_sessions]
        s_oos = s_arr[oos_sessions]

        # Overall session QLIKE
        q_all = qlike(t_oos, h_oos)

        # Per-session QLIKE
        mask_ov = s_oos == 0
        mask_id = s_oos == 1

        q_ov = qlike(t_oos[mask_ov], h_oos[mask_ov])
        q_id = qlike(t_oos[mask_id], h_oos[mask_id])

        sp_ov, sp_ov_p = spearman_corr(t_oos[mask_ov], h_oos[mask_ov])
        sp_id, sp_id_p = spearman_corr(t_oos[mask_id], h_oos[mask_id])

        results[model_name] = {
            'qlike_session_all': q_all,
            'qlike_overnight': q_ov,
            'qlike_intraday': q_id,
            'spearman_overnight': sp_ov,
            'spearman_intraday': sp_id,
            'n_oos_sessions': int(oos_sessions.sum()),
        }
        print(f"\n  {model_name}:")
        print(f"    Session QLIKE: all={q_all:.4f}, overnight={q_ov:.4f}, intraday={q_id:.4f}")
        print(f"    Spearman: overnight={sp_ov:.4f}, intraday={sp_id:.4f}")

    # Daily-level evaluation (all models including HAR and GJR)
    print("\n  --- Daily Total Variance Evaluation ---")

    # Session-based models: aggregate
    for model_name, h_daily, h_ov, h_id in [
        ('PRG_Basic', h_basic_daily, h_basic_ov, h_basic_id),
        ('PRG_Extended', h_ext_daily, h_ext_ov, h_ext_id),
        ('Separate_GARCH', h_sep_daily, h_sep_ov, h_sep_id)
    ]:
        h_oos_d = h_daily[oos_mask]
        rv_oos_d = rv_realized[oos_mask]

        q_total = qlike(rv_oos_d, h_oos_d)
        sp_total, sp_total_p = spearman_corr(rv_oos_d, h_oos_d)
        mse_total = mse(rv_oos_d, h_oos_d)
        mae_total = mae(rv_oos_d, h_oos_d)

        results[model_name]['qlike_total'] = q_total
        results[model_name]['spearman_total'] = sp_total
        results[model_name]['mse_total'] = mse_total
        results[model_name]['mae_total'] = mae_total

        # Daily QLIKE series for rolling chart
        daily_q = qlike_loss_array(rv_oos_d, h_oos_d)
        results[model_name]['daily_qlike_series'] = [float(v) if np.isfinite(v) else None for v in daily_q]

        print(f"\n  {model_name} (daily total):")
        print(f"    QLIKE={q_total:.4f}, Spearman={sp_total:.4f}")
        print(f"    MSE={mse_total:.2e}, MAE={mae_total:.2e}")

    # HAR-RV and GJR (already daily)
    for model_name, forecasts_d in [('HAR_RV', har_forecasts), ('GJR_GARCH', gjr_forecasts)]:
        h_oos_d = forecasts_d[is_end_daily:]
        rv_oos_d = rv_total_daily[is_end_daily:]

        q_total = qlike(rv_oos_d, h_oos_d)
        sp_total, sp_total_p = spearman_corr(rv_oos_d, h_oos_d)
        mse_total = mse(rv_oos_d, h_oos_d)
        mae_total = mae(rv_oos_d, h_oos_d)

        # Daily QLIKE series
        daily_q = qlike_loss_array(rv_oos_d, h_oos_d)

        results[model_name] = {
            'qlike_total': q_total,
            'spearman_total': sp_total,
            'mse_total': mse_total,
            'mae_total': mae_total,
            'qlike_overnight': None,
            'qlike_intraday': None,
            'daily_qlike_series': [float(v) if np.isfinite(v) else None for v in daily_q],
            'n_oos_days': int(len(rv_oos_d)),
        }

        print(f"\n  {model_name} (daily total):")
        print(f"    QLIKE={q_total:.4f}, Spearman={sp_total:.4f}")
        print(f"    MSE={mse_total:.2e}, MAE={mae_total:.2e}")

    # ----------------------------------------------------------
    # DM Tests (QLIKE loss, daily total)
    # ----------------------------------------------------------
    print("\n  --- DM Tests (QLIKE on total daily variance) ---")

    # Build aligned QLIKE loss arrays for DM tests
    # Session-based models use aggregated daily dates; daily models use daily_dates
    # We need to align them on common dates

    # Get OOS dates from session-based models
    sess_oos_dates = pd.to_datetime(dates_basic[oos_mask])

    # Get OOS dates from daily models
    daily_oos_dates = pd.DatetimeIndex(daily_dates[is_end_daily:])

    # Find common dates
    common_dates = sess_oos_dates.intersection(daily_oos_dates)
    print(f"  Common OOS dates: {len(common_dates)}")

    # Build loss arrays on common dates
    loss_arrays = {}

    for model_name, h_daily_arr in [('PRG_Basic', h_basic_daily), ('PRG_Extended', h_ext_daily), ('Separate_GARCH', h_sep_daily)]:
        all_dates = pd.to_datetime(dates_basic)
        h_series = pd.Series(h_daily_arr, index=all_dates)
        rv_series = pd.Series(rv_realized, index=all_dates)
        h_common = h_series.reindex(common_dates)
        rv_common = rv_series.reindex(common_dates)
        valid = np.isfinite(h_common.values) & np.isfinite(rv_common.values) & (h_common.values > 0) & (rv_common.values > 0)
        loss = np.full(len(common_dates), np.nan)
        loss[valid] = rv_common.values[valid]/h_common.values[valid] - np.log(rv_common.values[valid]/h_common.values[valid]) - 1
        loss_arrays[model_name] = loss

    for model_name, forecasts_d in [('HAR_RV', har_forecasts), ('GJR_GARCH', gjr_forecasts)]:
        all_dates = pd.DatetimeIndex(daily_dates)
        h_series = pd.Series(forecasts_d, index=all_dates)
        rv_series = pd.Series(rv_total_daily, index=all_dates)
        h_common = h_series.reindex(common_dates)
        rv_common = rv_series.reindex(common_dates)
        valid = np.isfinite(h_common.values) & np.isfinite(rv_common.values) & (h_common.values > 0) & (rv_common.values > 0)
        loss = np.full(len(common_dates), np.nan)
        loss[valid] = rv_common.values[valid]/h_common.values[valid] - np.log(rv_common.values[valid]/h_common.values[valid]) - 1
        loss_arrays[model_name] = loss

    # Pairwise DM tests
    dm_results = {}
    model_list = ['PRG_Basic', 'PRG_Extended', 'Separate_GARCH', 'HAR_RV', 'GJR_GARCH']

    for i, m1 in enumerate(model_list):
        for j, m2 in enumerate(model_list):
            if i >= j:
                continue
            l1 = loss_arrays.get(m1)
            l2 = loss_arrays.get(m2)
            if l1 is not None and l2 is not None:
                t_stat, p_val = dm_test(l1, l2, h=1)
                dm_results[f"{m1}_vs_{m2}"] = {
                    't_stat': round(t_stat, 4),
                    'p_value': round(p_val, 6),
                    'significant': abs(t_stat) > 3.0,
                    'winner': m1 if t_stat < 0 else m2,
                }
                marker = "***" if abs(t_stat) > 3.0 else ""
                print(f"    {m1} vs {m2}: t={t_stat:.4f}, p={p_val:.6f} {marker}")
                if t_stat < 0:
                    print(f"      → {m1} better (lower QLIKE loss)")
                else:
                    print(f"      → {m2} better (lower QLIKE loss)")

    # ----------------------------------------------------------
    # KEY TEST: PRG vs Separate (value of cross-recursion)
    # ----------------------------------------------------------
    print("\n  ★ KEY TEST: Value of cross-session recursion")
    l_prg = loss_arrays.get('PRG_Basic')
    l_sep = loss_arrays.get('Separate_GARCH')
    if l_prg is not None and l_sep is not None:
        t_stat, p_val = dm_test(l_prg, l_sep, h=1)
        print(f"    PRG_Basic vs Separate_GARCH: t={t_stat:.4f}, p={p_val:.6f}")
        if t_stat < -3.0:
            print(f"    → Cross-recursion SIGNIFICANTLY improves prediction (|t|>3.0)")
        elif t_stat < 0:
            print(f"    → Cross-recursion helps but NOT significant at Harvey threshold")
        else:
            print(f"    → Cross-recursion does NOT help (Separate GARCH is better or equal)")

    # ----------------------------------------------------------
    # Charts
    # ----------------------------------------------------------
    print("\n  Generating charts...")
    make_charts(results, daily_df, CHARTS_DIR)

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    output = {
        'experiment_id': 'K874c',
        'title': 'Periodic Realized GARCH — Unified Recursive System with Session Switching',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'TAIFEX TX tick (volume-selected contract, 2017-05 to 2025-12)',
        'data_period': f"{dates_arr[0]} to {dates_arr[-1]}",
        'n_sessions': n_sessions,
        'n_days': n_sessions // 2,
        'is_sessions': is_end,
        'oos_sessions': oos_n,
        'is_days': is_end_agg,
        'oos_days': int(oos_mask.sum()),
        'methodology': {
            'PRG_Basic': 'h_n = ω_{s_n} + α_{s_n}·x_{n-1} + β_{s_n}·h_{n-1} (6 params)',
            'PRG_Extended': 'h_n = ω_{s_n} + α_{s_n}·x_{n-1} + γ_{s_n}·x_{n-1}·I(r<0) + β_{s_n}·h_{n-1} (8 params)',
            'Separate_GARCH': 'Independent GARCH per session (no cross-recursion, 3+3=6 params)',
            'HAR_RV': 'Standard HAR-RV on log(RV_total) (daily)',
            'GJR_GARCH': 'GJR-GARCH(1,1) on close-to-close returns (daily)',
            'key_feature': 'h_{n-1} carries over between session types — overnight info feeds intraday and vice versa',
            'refit_freq_sessions': REFIT_FREQ,
            'refit_freq_daily': REFIT_FREQ // 2,
        },
        'descriptive_stats': desc_stats,
        'parameter_estimates': {},
        'oos_results': results,
        'dm_tests': dm_results,
        'conclusions': {},
        'references': [
            'Lai et al. (2024): PRS model (inspiration for periodic recursion)',
            'Corsi (2009): HAR-RV model',
            'Hansen & Lunde (2005): Realized GARCH',
            'Patton (2011): QLIKE proxy-robust loss',
            'Bollerslev & Ghysels (1996): Periodic GARCH',
        ],
    }

    # Add parameter estimates
    if params_basic is not None:
        output['parameter_estimates']['PRG_Basic'] = {
            'omega_0': float(params_basic[0]), 'alpha_0': float(params_basic[1]), 'beta_0': float(params_basic[2]),
            'omega_1': float(params_basic[3]), 'alpha_1': float(params_basic[4]), 'beta_1': float(params_basic[5]),
            'persistence_overnight': float(params_basic[1] + params_basic[2]),
            'persistence_intraday': float(params_basic[4] + params_basic[5]),
            'log_likelihood': float(ll_basic) if ll_basic else None,
        }
    if params_ext is not None:
        output['parameter_estimates']['PRG_Extended'] = {
            'omega_0': float(params_ext[0]), 'alpha_0': float(params_ext[1]), 'beta_0': float(params_ext[2]),
            'omega_1': float(params_ext[3]), 'alpha_1': float(params_ext[4]), 'beta_1': float(params_ext[5]),
            'gamma_0': float(params_ext[6]), 'gamma_1': float(params_ext[7]),
            'persistence_overnight': float(params_ext[1] + params_ext[2]),
            'persistence_intraday': float(params_ext[4] + params_ext[5]),
            'log_likelihood': float(ll_ext) if ll_ext else None,
        }

    # Clean up results for JSON serialization
    for model_name in results:
        if 'daily_qlike_series' in results[model_name]:
            del results[model_name]['daily_qlike_series']  # too large for JSON

    # Add conclusions
    # Find best model by QLIKE total
    qlike_totals = {k: v.get('qlike_total') for k, v in results.items() if v.get('qlike_total') is not None}
    if qlike_totals:
        best_model = min(qlike_totals, key=qlike_totals.get)
        output['conclusions']['best_model_total_qlike'] = best_model
        output['conclusions']['best_qlike'] = qlike_totals[best_model]
        output['conclusions']['all_qlike'] = qlike_totals

    # Cross-recursion value
    prg_q = qlike_totals.get('PRG_Basic')
    sep_q = qlike_totals.get('Separate_GARCH')
    if prg_q is not None and sep_q is not None:
        improvement = (sep_q - prg_q) / sep_q * 100
        output['conclusions']['cross_recursion_improvement_pct'] = round(improvement, 2)
        dm_key = 'PRG_Basic_vs_Separate_GARCH'
        if dm_key in dm_results:
            output['conclusions']['cross_recursion_significant'] = dm_results[dm_key]['significant']
            output['conclusions']['cross_recursion_dm_t'] = dm_results[dm_key]['t_stat']

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to {OUTPUT_FILE}")
    print("\n" + "=" * 70)
    print("K874c COMPLETE")
    print("=" * 70)

    return output


if __name__ == '__main__':
    main()
