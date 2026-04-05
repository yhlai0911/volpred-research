#!/usr/bin/env python3
"""
K890: Path Signatures for Volatility Forecasting (TAIFEX)
=========================================================

Research Question (EMPIRICAL):
  Do path signature features—capturing trajectory shape beyond RV—improve
  volatility forecasting on TAIFEX TX futures?

Background:
  Path signatures are a mathematical tool from rough path theory that extract
  hierarchical features from sequential data. For a price path, the signature
  captures not just the endpoint (return) but the entire trajectory shape.
  K529 confirmed rough volatility (H=0.1) for SPY. K806 tested multivariate
  fBm but got NULL on daily data. Path signatures may capture the rough
  structure better using high-frequency data.

Method:
  Truncated path signature features from 5-min intraday returns:
  - S1_return = Σᵢ rᵢ (total return — trivial)
  - S_quadvar = Σᵢ rᵢ² (realized variance — standard)
  - S2_serial = Σᵢ<ⱼ rᵢ·rⱼ (depth-2: serial dependence)
  - S_leadlag = Σᵢ<ⱼ (rᵢ·rⱼ - rⱼ·rᵢ) (antisymmetric: trend asymmetry)
    Note: For 1D path, S_leadlag = 0 always. We use a 2D path (time, price)
    to get non-trivial lead-lag: area under price path vs time.
  - S_cubicvar = Σᵢ rᵢ³ (realized skewness proxy)
  - S_quarticvar = Σᵢ rᵢ⁴ (realized kurtosis proxy)

  For the 2D path (time, cumulative return):
  - S2_area = Σᵢ<ⱼ (tᵢ·rⱼ - rᵢ·tⱼ) (signed area = trend measure)
    where tᵢ = i/N (normalized time) and rᵢ = cumulative return at step i

Models:
  1. HAR-RV (standard): log(RV_d), log(RV_w), log(RV_m) → predict log(σ²_fullday)
  2. HAR-Sig: HAR + S2_serial_d + S2_area_d → predict log(σ²_fullday)
  3. HAR-Sig-Full: HAR + all sig features (d, 5d, 22d averages) → predict log(σ²_fullday)
  4. Sig-Only: S_quadvar, S2_serial, S2_area, S_cubicvar, S_quarticvar
     (daily + 5d + 22d averages) → predict log(σ²_fullday)
  5. GJR-GARCH: Standard benchmark on close-to-close returns

Common target: σ²_fullday = r²_gap + RV_intra + RV_night
Evaluation: QLIKE, MSE, MAE, Spearman rank correlation, DM test (Harvey |t|>3.0)

Error log rules:
  - DM test: use dm_test from volpred.stats.model_evaluation
  - TX: volume-based contract selection (NOT TX1)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - Student-t: scale term sqrt((df-2)/df)

Data:
  - TAIFEX TX tick (volume-selected contract, 2017-05-15 to 2025-12-31)
  - Night session available from 2017-05-15

References:
  - Lyons (1998): Differential equations driven by rough signals (signature theory)
  - Chevyrev & Kormilitzin (2016): A primer on the signature method
  - Kidger & Lyons (2021): Signatory: differentiable computations of the signature
  - Perez Arribas et al. (2020): Signatures in finance
  - Corsi (2009): HAR-RV model
  - Patton (2011): QLIKE proxy-robust loss
  - Hansen & Lunde (2005): 5-min RV as gold standard
  - Diebold & Mariano (1995) / Harvey (2016): DM test with |t|>3.0

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
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k890_path_signatures_vol_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k890_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Session boundaries (HHMMSS integer)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# OOS config
IS_FRACTION = 0.60      # 60% in-sample
REFIT_FREQ = 63          # Refit every ~63 trading days (quarterly)
NIGHT_SESSION_START_DATE = "2017-05-15"


# ============================================================
# Step 1: Build daily data from TAIFEX tick files
# ============================================================

def time_to_5min_bucket(time_int):
    """Convert HHMMSS integer to a 5-minute bucket label."""
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def compute_rv(returns):
    """Compute realized variance from returns."""
    if len(returns) < 1:
        return np.nan
    return float(np.sum(returns ** 2))


def compute_signature_features(returns):
    """
    Compute truncated path signature features from intraday 5-min returns.

    For a 1D return stream r_1, ..., r_N:
      - S_quadvar = Σ rᵢ² (realized variance)
      - S_return = Σ rᵢ (total return)
      - S2_serial = Σᵢ<ⱼ rᵢ·rⱼ (depth-2 iterated integral = serial covariance)
        Note: S2_serial = 0.5 * ((Σ rᵢ)² - Σ rᵢ²) = 0.5*(S_return² - S_quadvar)
      - S_cubicvar = Σ rᵢ³ (signed cubic variation — realized skewness proxy)
      - S_quarticvar = Σ rᵢ⁴ (quartic variation — realized kurtosis proxy)

    For 2D path (normalized_time, cumulative_return):
      - S2_area = Σᵢ<ⱼ (Δtᵢ·Δcumrⱼ - Δcumrᵢ·Δtⱼ)
        = signed area enclosed by path vs diagonal
        This captures trend/mean-reversion structure

    Returns dict of features, or None if insufficient data.
    """
    if len(returns) < 3:
        return None

    r = np.asarray(returns, dtype=np.float64)
    N = len(r)

    # Basic signature features (1D)
    S_return = np.sum(r)
    S_quadvar = np.sum(r ** 2)
    # S2_serial = Σᵢ<ⱼ rᵢ·rⱼ = 0.5*((Σrᵢ)² - Σrᵢ²)
    S2_serial = 0.5 * (S_return ** 2 - S_quadvar)
    S_cubicvar = np.sum(r ** 3)
    S_quarticvar = np.sum(r ** 4)

    # 2D path signature: (time, cumulative return)
    # Path increments: Δt = 1/N for each step, Δcumr = r_i
    dt = 1.0 / N  # normalized time increment
    # S2_area = Σᵢ<ⱼ (Δtᵢ·Δcumrⱼ - Δcumrᵢ·Δtⱼ)
    # Since Δtᵢ = dt for all i, and Δcumrⱼ = rⱼ:
    # S2_area = dt * Σᵢ<ⱼ rⱼ - dt * Σᵢ<ⱼ rᵢ = dt * Σᵢ<ⱼ(rⱼ - rᵢ)
    # Equivalently: S2_area = dt * (Σⱼ (j*rⱼ) - Σᵢ ((N-1-i)*rᵢ))
    # = dt * Σᵢ rᵢ * (i - (N-1-i)) = dt * Σᵢ rᵢ * (2i - N + 1)
    # This can be computed efficiently:
    indices = np.arange(N)
    weights = 2.0 * indices - (N - 1.0)
    S2_area = dt * np.sum(r * weights)

    return {
        'S_return': float(S_return),
        'S_quadvar': float(S_quadvar),
        'S2_serial': float(S2_serial),
        'S_cubicvar': float(S_cubicvar),
        'S_quarticvar': float(S_quarticvar),
        'S2_area': float(S2_area),
    }


def safe_volume(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def process_single_file(filepath):
    """Process one TX daily file -> RV components + signature features."""
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

    rv_intra = compute_rv(day_rets)
    rv_night = compute_rv(night_rets)

    # Signature features from day session
    sig_day = compute_signature_features(day_rets)
    # Signature features from night session (if available)
    sig_night = compute_signature_features(night_rets)

    # Prices for gap/return computation
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

    result = {
        'date': date_str,
        'rv_intra': rv_intra if not np.isnan(rv_intra) else None,
        'rv_night': rv_night if not np.isnan(rv_night) else None,
        'day_open': day_open if not np.isnan(day_open) else None,
        'day_close': day_close if not np.isnan(day_close) else None,
        'night_open': night_open if not np.isnan(night_open) else None,
        'night_close': night_close if not np.isnan(night_close) else None,
        'n_5min_bars_day': len(day_rets),
        'n_5min_bars_night': len(night_rets),
    }

    # Add signature features
    if sig_day is not None:
        for k, v in sig_day.items():
            result[f'sig_day_{k}'] = v
    if sig_night is not None:
        for k, v in sig_night.items():
            result[f'sig_night_{k}'] = v

    return result


def load_all_data():
    """Load TX files (night session era) and compute RV + signature features."""
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
    Build variance components and signature feature columns.

    Common target: σ²_fullday = r²_gap + RV_intra + RV_night
    """
    df = rv_df.copy()
    df = df.dropna(subset=['day_open', 'day_close', 'rv_intra'])

    # Overnight gap: previous day close -> today's open
    df['prev_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_close'])
    df['r2_gap'] = df['overnight_gap'] ** 2

    # Close-to-close return for GJR
    df['c2c_return'] = np.log(df['day_close'] / df['prev_close'])

    # RV total
    df['rv_total'] = df['rv_intra'] + df['rv_night'].fillna(0)

    # Full-day variance = r²_gap + RV_intra + RV_night
    df['sigma2_fullday'] = df['r2_gap'] + df['rv_intra'] + df['rv_night'].fillna(0)

    # Drop first row (no previous close)
    df = df.iloc[1:]

    # Drop rows missing critical data
    df = df.dropna(subset=['c2c_return', 'rv_intra', 'r2_gap', 'sigma2_fullday'])

    return df


# ============================================================
# Step 2: Prepare signature feature time series
# ============================================================

def prepare_signature_features(df):
    """
    Create daily + rolling 5d and 22d averages of signature features.
    Also create combined (day + night) signature features.
    """
    # Day session signature features
    sig_cols_day = ['sig_day_S_return', 'sig_day_S_quadvar', 'sig_day_S2_serial',
                    'sig_day_S_cubicvar', 'sig_day_S_quarticvar', 'sig_day_S2_area']

    # Night session signature features (may have NaN if no night data)
    sig_cols_night = ['sig_night_S_return', 'sig_night_S_quadvar', 'sig_night_S2_serial',
                      'sig_night_S_cubicvar', 'sig_night_S_quarticvar', 'sig_night_S2_area']

    # Combined signature features (day + night)
    for base in ['S_return', 'S_quadvar', 'S2_serial', 'S_cubicvar', 'S_quarticvar', 'S2_area']:
        day_col = f'sig_day_{base}'
        night_col = f'sig_night_{base}'
        comb_col = f'sig_{base}'
        if day_col in df.columns and night_col in df.columns:
            df[comb_col] = df[day_col].fillna(0) + df[night_col].fillna(0)
        elif day_col in df.columns:
            df[comb_col] = df[day_col]

    # Rolling averages of combined signature features
    sig_combined = ['sig_S_return', 'sig_S_quadvar', 'sig_S2_serial',
                    'sig_S_cubicvar', 'sig_S_quarticvar', 'sig_S2_area']

    for col in sig_combined:
        if col in df.columns:
            df[f'{col}_5d'] = df[col].rolling(5).mean()
            df[f'{col}_22d'] = df[col].rolling(22).mean()

    return df


# ============================================================
# Step 3: Model implementations
# ============================================================

def gjr_oos_forecast(returns, is_end, refit_freq=63):
    """
    GJR-GARCH(1,1) on daily close-to-close returns.
    h_t = omega + alpha*r²_{t-1} + gamma*r²_{t-1}*I(r_{t-1}<0) + beta*h_{t-1}

    Predicts full-day σ² natively.
    """
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def gjr_negll(params, r):
        omega, alpha, gamma_p, beta = params
        T = len(r)
        h = np.zeros(T)
        h[0] = np.var(r[:min(50, T)])
        if h[0] < 1e-12:
            h[0] = 1e-8

        ll = 0.0
        for t in range(1, T):
            indicator = 1.0 if r[t-1] < 0 else 0.0
            h[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * h[t-1]
            if h[t] < 1e-12:
                h[t] = 1e-12
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
                # Recompute h state through all training data
                omega, alpha, gamma_p, beta = current_params
                h_run = np.var(returns[:min(50, t)])
                if h_run < 1e-12:
                    h_run = 1e-8
                for tt in range(1, t):
                    indicator = 1.0 if returns[tt-1] < 0 else 0.0
                    h_run = omega + alpha*returns[tt-1]**2 + gamma_p*returns[tt-1]**2*indicator + beta*h_run
                    if h_run < 1e-12:
                        h_run = 1e-12
                h_state = h_run

        if current_params is not None:
            omega, alpha, gamma_p, beta = current_params
            indicator = 1.0 if returns[t-1] < 0 else 0.0
            h_state = omega + alpha*returns[t-1]**2 + gamma_p*returns[t-1]**2*indicator + beta*h_state
            if h_state < 1e-12:
                h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


def har_oos_forecast(target_series, feature_matrix, is_end, refit_freq=63, label="HAR"):
    """
    Generic HAR-style OOS forecast using log-space regression.

    Parameters:
      target_series: np.ndarray of the target variable (e.g., sigma2_fullday)
      feature_matrix: np.ndarray of shape (n, k) — features already lagged by 1
      is_end: int — start of OOS
      refit_freq: int — refit interval
      label: str — model name for logging

    Returns forecasts in LEVEL (not log).
    """
    eps = 1e-12
    log_target = np.log(np.clip(target_series, eps, None))
    n = len(log_target)

    forecasts = np.full(n, np.nan)
    beta = None

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            # Use data up to t for training
            train_start = 22  # need at least 22 days for monthly averages
            y_train = log_target[train_start:t]
            X_train = feature_matrix[train_start:t]

            # Mask valid rows
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

        if beta is not None:
            x_t = feature_matrix[t]
            if np.all(np.isfinite(x_t)):
                x_with_const = np.concatenate([[1.0], x_t])
                log_forecast = x_with_const @ beta
                forecasts[t] = np.exp(log_forecast)

    return forecasts


def build_har_features(target_series):
    """
    Build standard HAR features: lagged 1d, 5d avg, 22d avg (all in log space, lagged 1 day).
    """
    eps = 1e-12
    log_t = np.log(np.clip(target_series, eps, None))
    s = pd.Series(log_t)
    f_d = s.shift(1).values
    f_5d = s.rolling(5).mean().shift(1).values
    f_22d = s.rolling(22).mean().shift(1).values
    return np.column_stack([f_d, f_5d, f_22d])


def build_sig_features_for_model(df, use_5d_22d=True):
    """
    Build signature feature matrix (lagged by 1 day) for regression.

    Features (daily, lagged 1):
      - sig_S2_serial (serial dependence)
      - sig_S2_area (trend measure)
      - sig_S_cubicvar (signed cubic variation)
      - sig_S_quarticvar (quartic variation)

    If use_5d_22d: also include 5d and 22d rolling averages.
    """
    cols = ['sig_S2_serial', 'sig_S2_area', 'sig_S_cubicvar', 'sig_S_quarticvar']

    features = []
    for col in cols:
        if col in df.columns:
            features.append(df[col].shift(1).values)
        else:
            features.append(np.full(len(df), np.nan))

    if use_5d_22d:
        for col in cols:
            col_5d = f'{col}_5d'
            col_22d = f'{col}_22d'
            if col_5d in df.columns:
                features.append(df[col_5d].shift(1).values)
            else:
                features.append(np.full(len(df), np.nan))
            if col_22d in df.columns:
                features.append(df[col_22d].shift(1).values)
            else:
                features.append(np.full(len(df), np.nan))

    return np.column_stack(features)


# ============================================================
# Step 4: Evaluation metrics
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: Patton (2011) proxy-robust."""
    eps = 1e-12
    a = np.clip(actual, eps, None)
    f = np.clip(forecast, eps, None)
    return np.nanmean(a / f - np.log(a / f) - 1)


def compute_metrics(actual, forecast, label=""):
    """Compute QLIKE, MSE, MAE, Spearman for OOS period."""
    valid = np.isfinite(actual) & np.isfinite(forecast) & (forecast > 0)
    a = actual[valid]
    f = forecast[valid]
    if len(a) < 10:
        return {'label': label, 'n_oos': 0, 'qlike': np.nan, 'mse': np.nan,
                'mae': np.nan, 'spearman': np.nan}

    q = qlike(a, f)
    mse = np.mean((a - f) ** 2)
    mae = np.mean(np.abs(a - f))
    spearman, _ = sp_stats.spearmanr(a, f)

    return {
        'label': label,
        'n_oos': int(len(a)),
        'qlike': float(q),
        'mse': float(mse),
        'mae': float(mae),
        'spearman': float(spearman),
    }


def qlike_losses(actual, forecast):
    """Per-observation QLIKE losses for DM test."""
    eps = 1e-12
    a = np.clip(actual, eps, None)
    f = np.clip(forecast, eps, None)
    return a / f - np.log(a / f) - 1


# ============================================================
# Step 5: Visualization
# ============================================================

def generate_charts(results_dict, charts_dir):
    """Generate comparison charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Chart 1: QLIKE comparison bar chart
    models = []
    qlikes = []
    for m in results_dict['model_results']:
        models.append(m['label'])
        qlikes.append(m['qlike'])

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#F44336']
    bars = ax.bar(range(len(models)), qlikes, color=colors[:len(models)], edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, rotation=15, ha='right', fontsize=10)
    ax.set_ylabel('QLIKE Loss (lower = better)', fontsize=12)
    ax.set_title('K890: Path Signatures for Volatility Forecasting — QLIKE Comparison', fontsize=13, fontweight='bold')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Add value labels
    for bar, val in zip(bars, qlikes):
        if not np.isnan(val):
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.001,
                    f'{val:.4f}', ha='center', va='bottom', fontsize=9)

    best_idx = np.nanargmin(qlikes)
    bars[best_idx].set_edgecolor('gold')
    bars[best_idx].set_linewidth(2)

    plt.tight_layout()
    path1 = os.path.join(charts_dir, 'qlike_comparison.png')
    plt.savefig(path1, dpi=150, bbox_inches='tight')
    plt.close()

    # Chart 2: Spearman correlation comparison
    spearmen = [m['spearman'] for m in results_dict['model_results']]
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(range(len(models)), spearmen, color=colors[:len(models)], edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, rotation=15, ha='right', fontsize=10)
    ax.set_ylabel('Spearman Rank Correlation (higher = better)', fontsize=12)
    ax.set_title('K890: Spearman Correlation — Forecast vs Actual σ²', fontsize=13, fontweight='bold')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    for bar, val in zip(bars, spearmen):
        if not np.isnan(val):
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.002,
                    f'{val:.4f}', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    path2 = os.path.join(charts_dir, 'spearman_comparison.png')
    plt.savefig(path2, dpi=150, bbox_inches='tight')
    plt.close()

    # Chart 3: Time series of forecasts vs actual (last 252 days)
    if 'forecast_series' in results_dict:
        fig, ax = plt.subplots(figsize=(14, 6))
        fs = results_dict['forecast_series']
        dates = pd.to_datetime(fs['dates'][-252:])
        actual = np.array(fs['actual'][-252:])
        ax.plot(dates, actual * 1e4, color='black', alpha=0.4, linewidth=0.8, label='Actual σ² (×10⁴)')

        model_colors = {'HAR-RV': '#2196F3', 'HAR-Sig': '#4CAF50',
                        'HAR-Sig-Full': '#FF9800', 'Sig-Only': '#9C27B0', 'GJR-GARCH': '#F44336'}
        for mname, mdata in fs['forecasts'].items():
            fc = np.array(mdata[-252:])
            c = model_colors.get(mname, '#888888')
            ax.plot(dates, fc * 1e4, color=c, linewidth=1.0, alpha=0.8, label=mname)

        ax.set_ylabel('σ² × 10⁴', fontsize=12)
        ax.set_title('K890: Last 252 Days — Forecast vs Actual Full-Day Variance', fontsize=13, fontweight='bold')
        ax.legend(fontsize=9, loc='upper right')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        plt.tight_layout()
        path3 = os.path.join(charts_dir, 'forecast_timeseries.png')
        plt.savefig(path3, dpi=150, bbox_inches='tight')
        plt.close()

    # Chart 4: Signature feature distributions
    if 'sig_stats' in results_dict:
        fig, axes = plt.subplots(2, 3, figsize=(14, 8))
        sig_names = ['S2_serial', 'S2_area', 'S_cubicvar', 'S_quarticvar', 'S_return', 'S_quadvar']
        for i, (ax, name) in enumerate(zip(axes.ravel(), sig_names)):
            if name in results_dict['sig_stats']:
                vals = results_dict['sig_stats'][name]
                ax.hist(vals, bins=50, color=colors[i % len(colors)], alpha=0.7, edgecolor='white')
                ax.set_title(f'sig_{name}', fontsize=10, fontweight='bold')
                ax.axvline(np.nanmean(vals), color='red', linestyle='--', linewidth=1, alpha=0.7)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)

        plt.suptitle('K890: Distribution of Path Signature Features', fontsize=13, fontweight='bold')
        plt.tight_layout()
        path4 = os.path.join(charts_dir, 'sig_distributions.png')
        plt.savefig(path4, dpi=150, bbox_inches='tight')
        plt.close()

    return [path1, path2]


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K890: Path Signatures for Volatility Forecasting (TAIFEX)")
    print("=" * 70)
    print()

    # --------------------------------------------------
    # 1. Load data
    # --------------------------------------------------
    print("[Step 1] Loading TAIFEX TX tick data...")
    rv_df = load_all_data()
    print(f"  Date range: {rv_df.index.min()} to {rv_df.index.max()}")
    print(f"  Total days: {len(rv_df)}")
    print()

    # --------------------------------------------------
    # 2. Build daily components
    # --------------------------------------------------
    print("[Step 2] Building daily variance components + signature features...")
    df = build_daily_components(rv_df)
    df = prepare_signature_features(df)
    print(f"  Usable days: {len(df)}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")

    # Summary stats for signature features
    sig_cols = ['sig_S_return', 'sig_S_quadvar', 'sig_S2_serial',
                'sig_S_cubicvar', 'sig_S_quarticvar', 'sig_S2_area']
    print("\n  Signature feature summary:")
    sig_stats_for_chart = {}
    for col in sig_cols:
        if col in df.columns:
            vals = df[col].dropna()
            print(f"    {col}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
                  f"min={vals.min():.6f}, max={vals.max():.6f}, n={len(vals)}")
            sig_stats_for_chart[col.replace('sig_', '')] = vals.values.tolist()

    # Target stats
    target = df['sigma2_fullday'].values
    print(f"\n  Target σ²_fullday: mean={np.nanmean(target):.6f}, "
          f"std={np.nanstd(target):.6f}, median={np.nanmedian(target):.6f}")
    print()

    # --------------------------------------------------
    # 3. Define IS/OOS split
    # --------------------------------------------------
    n = len(df)
    is_end = int(n * IS_FRACTION)
    oos_start_date = df.index[is_end]
    print(f"[Step 3] IS/OOS split: IS={is_end} days (to {oos_start_date.date()}), "
          f"OOS={n - is_end} days")
    print(f"  OOS period: {oos_start_date.date()} to {df.index[-1].date()}")
    n_oos = n - is_end
    print(f"  OOS days: {n_oos} (>= 252 required: {'PASS' if n_oos >= 252 else 'FAIL'})")
    print()

    # --------------------------------------------------
    # 4. Arrays for modeling
    # --------------------------------------------------
    target_arr = df['sigma2_fullday'].values
    returns_arr = df['c2c_return'].values
    rv_total_arr = df['rv_total'].values

    # --------------------------------------------------
    # 5. Model 1: GJR-GARCH
    # --------------------------------------------------
    print("[Step 4] Running GJR-GARCH OOS forecast...")
    gjr_fc = gjr_oos_forecast(returns_arr, is_end, refit_freq=REFIT_FREQ)
    gjr_metrics = compute_metrics(target_arr[is_end:], gjr_fc[is_end:], "GJR-GARCH")
    print(f"  GJR-GARCH: QLIKE={gjr_metrics['qlike']:.4f}, "
          f"Spearman={gjr_metrics['spearman']:.4f}, n_oos={gjr_metrics['n_oos']}")
    print()

    # --------------------------------------------------
    # 6. Model 2: HAR-RV (standard)
    # --------------------------------------------------
    print("[Step 5] Running HAR-RV OOS forecast (on σ²_fullday)...")
    har_features = build_har_features(target_arr)
    har_fc = har_oos_forecast(target_arr, har_features, is_end, REFIT_FREQ, "HAR-RV")
    har_metrics = compute_metrics(target_arr[is_end:], har_fc[is_end:], "HAR-RV")
    print(f"  HAR-RV: QLIKE={har_metrics['qlike']:.4f}, "
          f"Spearman={har_metrics['spearman']:.4f}, n_oos={har_metrics['n_oos']}")
    print()

    # --------------------------------------------------
    # 7. Model 3: HAR-Sig (HAR + key signature features)
    # --------------------------------------------------
    print("[Step 6] Running HAR-Sig OOS forecast (HAR + S2_serial + S2_area)...")
    # HAR features + 2 key signature features (daily, lagged)
    sig_serial_lag = df['sig_S2_serial'].shift(1).values if 'sig_S2_serial' in df.columns else np.full(n, np.nan)
    sig_area_lag = df['sig_S2_area'].shift(1).values if 'sig_S2_area' in df.columns else np.full(n, np.nan)
    har_sig_features = np.column_stack([har_features, sig_serial_lag, sig_area_lag])

    har_sig_fc = har_oos_forecast(target_arr, har_sig_features, is_end, REFIT_FREQ, "HAR-Sig")
    har_sig_metrics = compute_metrics(target_arr[is_end:], har_sig_fc[is_end:], "HAR-Sig")
    print(f"  HAR-Sig: QLIKE={har_sig_metrics['qlike']:.4f}, "
          f"Spearman={har_sig_metrics['spearman']:.4f}, n_oos={har_sig_metrics['n_oos']}")
    print()

    # --------------------------------------------------
    # 8. Model 4: HAR-Sig-Full (HAR + all sig features, including 5d/22d)
    # --------------------------------------------------
    print("[Step 7] Running HAR-Sig-Full OOS forecast (HAR + all sig features)...")
    sig_full_features = build_sig_features_for_model(df, use_5d_22d=True)
    har_sig_full_features = np.column_stack([har_features, sig_full_features])

    har_sig_full_fc = har_oos_forecast(target_arr, har_sig_full_features, is_end, REFIT_FREQ, "HAR-Sig-Full")
    har_sig_full_metrics = compute_metrics(target_arr[is_end:], har_sig_full_fc[is_end:], "HAR-Sig-Full")
    print(f"  HAR-Sig-Full: QLIKE={har_sig_full_metrics['qlike']:.4f}, "
          f"Spearman={har_sig_full_metrics['spearman']:.4f}, n_oos={har_sig_full_metrics['n_oos']}")
    print()

    # --------------------------------------------------
    # 9. Model 5: Sig-Only (pure signature features)
    # --------------------------------------------------
    print("[Step 8] Running Sig-Only OOS forecast (signature features only)...")
    # Use S_quadvar (lagged) as the "RV equivalent" from signatures
    sig_quadvar_lag = df['sig_S_quadvar'].shift(1).values if 'sig_S_quadvar' in df.columns else np.full(n, np.nan)
    sig_quadvar_5d = df['sig_S_quadvar_5d'].shift(1).values if 'sig_S_quadvar_5d' in df.columns else np.full(n, np.nan)
    sig_quadvar_22d = df['sig_S_quadvar_22d'].shift(1).values if 'sig_S_quadvar_22d' in df.columns else np.full(n, np.nan)

    # Add S2_serial and S2_area (daily, 5d, 22d)
    sig_serial_5d = df['sig_S2_serial_5d'].shift(1).values if 'sig_S2_serial_5d' in df.columns else np.full(n, np.nan)
    sig_serial_22d = df['sig_S2_serial_22d'].shift(1).values if 'sig_S2_serial_22d' in df.columns else np.full(n, np.nan)
    sig_area_5d = df['sig_S2_area_5d'].shift(1).values if 'sig_S2_area_5d' in df.columns else np.full(n, np.nan)
    sig_area_22d = df['sig_S2_area_22d'].shift(1).values if 'sig_S2_area_22d' in df.columns else np.full(n, np.nan)

    sig_only_features = np.column_stack([
        sig_quadvar_lag, sig_quadvar_5d, sig_quadvar_22d,
        sig_serial_lag, sig_serial_5d, sig_serial_22d,
        sig_area_lag, sig_area_5d, sig_area_22d,
    ])

    sig_only_fc = har_oos_forecast(target_arr, sig_only_features, is_end, REFIT_FREQ, "Sig-Only")
    sig_only_metrics = compute_metrics(target_arr[is_end:], sig_only_fc[is_end:], "Sig-Only")
    print(f"  Sig-Only: QLIKE={sig_only_metrics['qlike']:.4f}, "
          f"Spearman={sig_only_metrics['spearman']:.4f}, n_oos={sig_only_metrics['n_oos']}")
    print()

    # --------------------------------------------------
    # 10. DM tests (pairwise)
    # --------------------------------------------------
    print("[Step 9] Pairwise DM tests (Harvey |t| > 3.0 for significance)...")
    all_forecasts = {
        'GJR-GARCH': gjr_fc,
        'HAR-RV': har_fc,
        'HAR-Sig': har_sig_fc,
        'HAR-Sig-Full': har_sig_full_fc,
        'Sig-Only': sig_only_fc,
    }
    model_names = list(all_forecasts.keys())

    dm_results = []
    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            fc1 = all_forecasts[m1][is_end:]
            fc2 = all_forecasts[m2][is_end:]
            actual_oos = target_arr[is_end:]

            valid = np.isfinite(fc1) & np.isfinite(fc2) & np.isfinite(actual_oos) & (fc1 > 0) & (fc2 > 0)
            if valid.sum() < 30:
                dm_results.append({
                    'model_1': m1, 'model_2': m2,
                    'dm_t': np.nan, 'dm_p': np.nan, 'significant': False,
                    'better_model': 'N/A', 'n_valid': int(valid.sum())
                })
                continue

            loss1 = qlike_losses(actual_oos[valid], fc1[valid])
            loss2 = qlike_losses(actual_oos[valid], fc2[valid])

            t_stat, p_val = dm_test(loss1, loss2)

            sig = abs(t_stat) > 3.0
            better = m1 if t_stat < 0 else m2

            dm_results.append({
                'model_1': m1,
                'model_2': m2,
                'dm_t': float(t_stat),
                'dm_p': float(p_val),
                'significant': bool(sig),
                'better_model': better if sig else 'No significant difference',
                'n_valid': int(valid.sum()),
            })

            sig_mark = " ***" if sig else ""
            print(f"  {m1} vs {m2}: DM t={t_stat:.3f}, p={p_val:.4f} "
                  f"→ {better if sig else 'N.S.'}{sig_mark}")

    print()

    # --------------------------------------------------
    # 11. Incremental value analysis
    # --------------------------------------------------
    print("[Step 10] Incremental value analysis...")

    # Does HAR-Sig beat HAR? (key question: do signatures add value?)
    valid_hs = (np.isfinite(har_fc[is_end:]) & np.isfinite(har_sig_fc[is_end:]) &
                np.isfinite(target_arr[is_end:]) & (har_fc[is_end:] > 0) & (har_sig_fc[is_end:] > 0))
    if valid_hs.sum() > 30:
        loss_har = qlike_losses(target_arr[is_end:][valid_hs], har_fc[is_end:][valid_hs])
        loss_har_sig = qlike_losses(target_arr[is_end:][valid_hs], har_sig_fc[is_end:][valid_hs])
        t_inc, p_inc = dm_test(loss_har, loss_har_sig)
        har_qlike = np.nanmean(loss_har)
        har_sig_qlike = np.nanmean(loss_har_sig)
        improvement = (har_qlike - har_sig_qlike) / har_qlike * 100
        print(f"  HAR-RV vs HAR-Sig: DM t={t_inc:.3f}, p={p_inc:.4f}")
        print(f"  QLIKE improvement: {improvement:.2f}%")
        sig_adds_value = abs(t_inc) > 3.0 and har_sig_qlike < har_qlike
        print(f"  Signatures add value to HAR? {'YES' if sig_adds_value else 'NO'}")
    else:
        sig_adds_value = False
        improvement = 0.0
        print("  Insufficient overlapping forecasts for comparison")

    # Does Sig-Only compete with HAR?
    valid_so = (np.isfinite(har_fc[is_end:]) & np.isfinite(sig_only_fc[is_end:]) &
                np.isfinite(target_arr[is_end:]) & (har_fc[is_end:] > 0) & (sig_only_fc[is_end:] > 0))
    if valid_so.sum() > 30:
        loss_har_so = qlike_losses(target_arr[is_end:][valid_so], har_fc[is_end:][valid_so])
        loss_sig_only = qlike_losses(target_arr[is_end:][valid_so], sig_only_fc[is_end:][valid_so])
        t_so, p_so = dm_test(loss_har_so, loss_sig_only)
        print(f"  HAR-RV vs Sig-Only: DM t={t_so:.3f}, p={p_so:.4f}")
        sig_only_competitive = abs(t_so) <= 3.0 or np.nanmean(loss_sig_only) <= np.nanmean(loss_har_so)
        print(f"  Sig-Only competitive with HAR? {'YES (not significantly worse)' if sig_only_competitive else 'NO (significantly worse)'}")
    else:
        sig_only_competitive = False
        print("  Insufficient overlapping forecasts for comparison")

    print()

    # --------------------------------------------------
    # 12. Cross-correlation of signature features with future vol
    # --------------------------------------------------
    print("[Step 11] Signature features vs next-day σ² (Spearman correlation)...")
    sig_corr_results = {}
    next_day_target = df['sigma2_fullday'].values
    for col in sig_cols + [f'{c}_{s}' for c in sig_cols for s in ['5d', '22d']]:
        if col in df.columns:
            x = df[col].shift(1).values  # lag by 1
            valid_corr = np.isfinite(x) & np.isfinite(next_day_target)
            if valid_corr.sum() > 50:
                rho, p = sp_stats.spearmanr(x[valid_corr], next_day_target[valid_corr])
                sig_corr_results[col] = {'spearman': float(rho), 'p_value': float(p), 'n': int(valid_corr.sum())}
                sig_mark = "***" if abs(rho) > 0.1 else ""
                print(f"  {col}: ρ={rho:.4f}, p={p:.4f} {sig_mark}")

    print()

    # --------------------------------------------------
    # 13. Collect results
    # --------------------------------------------------
    all_metrics = [gjr_metrics, har_metrics, har_sig_metrics, har_sig_full_metrics, sig_only_metrics]

    # Prepare forecast series for chart
    forecast_series = {
        'dates': [str(d.date()) for d in df.index[is_end:]],
        'actual': target_arr[is_end:].tolist(),
        'forecasts': {}
    }
    for name, fc in all_forecasts.items():
        forecast_series['forecasts'][name] = fc[is_end:].tolist()

    # --------------------------------------------------
    # 14. Summary
    # --------------------------------------------------
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nData: TAIFEX TX, {df.index.min().date()} to {df.index.max().date()}")
    print(f"OOS period: {oos_start_date.date()} to {df.index[-1].date()} ({n_oos} days)")
    print(f"Target: σ²_fullday = r²_gap + RV_intra + RV_night")
    print(f"\nModel comparison (QLIKE, lower = better):")
    print(f"  {'Model':<20s} {'QLIKE':>10s} {'Spearman':>10s} {'MSE':>12s} {'MAE':>10s} {'n_OOS':>8s}")
    print(f"  {'-'*70}")
    for m in sorted(all_metrics, key=lambda x: x['qlike'] if not np.isnan(x['qlike']) else 999):
        print(f"  {m['label']:<20s} {m['qlike']:>10.4f} {m['spearman']:>10.4f} "
              f"{m['mse']:>12.6f} {m['mae']:>10.6f} {m['n_oos']:>8d}")

    best_model = min(all_metrics, key=lambda x: x['qlike'] if not np.isnan(x['qlike']) else 999)
    print(f"\n  Best model (QLIKE): {best_model['label']}")

    print(f"\nKey finding: Signatures add value to HAR? {'YES' if sig_adds_value else 'NO'}")
    if sig_adds_value:
        print(f"  QLIKE improvement: {improvement:.2f}%")

    # --------------------------------------------------
    # 15. Generate charts
    # --------------------------------------------------
    print("\n[Charts] Generating visualization...")
    results_dict = {
        'model_results': all_metrics,
        'forecast_series': forecast_series,
        'sig_stats': sig_stats_for_chart,
    }
    chart_paths = generate_charts(results_dict, CHARTS_DIR)
    print(f"  Charts saved to: {CHARTS_DIR}")

    # --------------------------------------------------
    # 16. Save results
    # --------------------------------------------------
    output = {
        'experiment_id': 'K890',
        'title': 'Path Signatures for Volatility Forecasting (TAIFEX)',
        'timestamp': datetime.now().isoformat(),
        'data': {
            'source': 'TAIFEX TX tick data (volume-based contract selection)',
            'period': f"{df.index.min().date()} to {df.index.max().date()}",
            'n_days': len(df),
            'night_session_start': NIGHT_SESSION_START_DATE,
        },
        'oos_config': {
            'is_fraction': IS_FRACTION,
            'is_end_idx': is_end,
            'oos_start': str(oos_start_date.date()),
            'oos_end': str(df.index[-1].date()),
            'n_oos': n_oos,
            'refit_freq': REFIT_FREQ,
        },
        'target': 'sigma2_fullday = r2_gap + RV_intra + RV_night',
        'model_results': all_metrics,
        'dm_tests': dm_results,
        'incremental_analysis': {
            'har_vs_har_sig': {
                'qlike_improvement_pct': float(improvement) if sig_adds_value else float(improvement),
                'signatures_add_value': sig_adds_value,
                'dm_t': float(t_inc) if valid_hs.sum() > 30 else None,
                'dm_p': float(p_inc) if valid_hs.sum() > 30 else None,
            },
            'har_vs_sig_only': {
                'sig_only_competitive': sig_only_competitive,
                'dm_t': float(t_so) if valid_so.sum() > 30 else None,
                'dm_p': float(p_so) if valid_so.sum() > 30 else None,
            },
        },
        'signature_correlations': sig_corr_results,
        'signature_feature_summary': {
            col: {
                'mean': float(df[col].mean()) if col in df.columns else None,
                'std': float(df[col].std()) if col in df.columns else None,
                'min': float(df[col].min()) if col in df.columns else None,
                'max': float(df[col].max()) if col in df.columns else None,
            } for col in sig_cols if col in df.columns
        },
        'conclusion': '',  # Will be filled below
        'limitations': [
            'Single asset (TAIFEX TX) — needs cross-asset validation',
            'Signature depth truncated at 2 (higher depths may capture more info)',
            'Linear regression model — nonlinear methods (neural nets, random forests) may better exploit signatures',
            'No jump component in signature models (HAR-RV-J not tested as base)',
            'Night session data only from 2017-05 — shorter sample than desired',
        ],
        'references': [
            'Lyons (1998): Differential equations driven by rough signals',
            'Chevyrev & Kormilitzin (2016): A primer on the signature method',
            'Kidger & Lyons (2021): Signatory: differentiable computations of the signature',
            'Perez Arribas et al. (2020): Signatures in finance',
            'Corsi (2009): HAR-RV model',
            'Patton (2011): QLIKE proxy-robust loss',
            'Hansen & Lunde (2005): 5-min RV as gold standard',
        ],
        'charts': [os.path.basename(p) for p in chart_paths],
    }

    # Build conclusion
    if sig_adds_value:
        output['conclusion'] = (
            f"Path signature features significantly improve HAR-RV volatility forecasting "
            f"on TAIFEX TX futures (QLIKE improvement: {improvement:.2f}%, DM |t|>3.0). "
            f"The depth-2 serial dependence (S2_serial) and signed area (S2_area) features "
            f"capture trajectory shape information beyond realized variance."
        )
    else:
        output['conclusion'] = (
            f"Path signature features do NOT significantly improve HAR-RV volatility forecasting "
            f"on TAIFEX TX futures at the Harvey (2016) |t|>3.0 threshold. "
            f"The standard HAR-RV model using lag structure (daily/weekly/monthly RV) already "
            f"captures most of the predictable variation in full-day variance. "
            f"Signature features may require nonlinear models to unlock their potential."
        )

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[Results] Saved to: {OUTPUT_FILE}")
    print(f"[Script] experiments/k890_path_signatures_vol.py")

    return output


if __name__ == '__main__':
    main()
