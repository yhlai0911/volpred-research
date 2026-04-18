#!/usr/bin/env python3
"""
K874: Joint HAR-Overnight Model — Division of Labor for Full-Day Volatility
============================================================================

Research Question (EMPIRICAL):
  Does a joint model (HAR for intraday + regression for overnight gap) predict
  TOTAL daily volatility better than either component alone?

Background:
  - K849: HAR-RV crushes GJR on RV target (DM t=-11.14) — expected, HAR natively
    predicts intraday RV
  - K847: 61% of overnight gap is tradable via TAIFEX night session
  - K848: Night vol share grew from 24%→57% (2017→2026)
  - K850: Prediction-VaR mismatch — neither model alone covers full day
  - User's idea: TWO specialized models, each on its native target, then combine

Methodology:
  Model A: HAR for intraday vol
    log(RV_intra_{t+1}) = α + β₁·log(RV_intra_t) + β₅·log(RV_5d)
                          + β₂₂·log(RV_22d) + γ·r²_overnight_t + ε

  Model B: HAR for night session vol (with external regressors)
    log(RV_night_{t+1}) = α + β₁·log(RV_night_t) + β₂·log(RV_night_5d)
                          + β₃·log(RV_night_22d) + β₄·log(RV_intra_t)
                          + β₅·VIX_t + β₆·|SPY_ret_t| + ε

  Combined: h_total = w₁·ĥ_intra + w₂·ĥ_overnight (weights from training MSE)

  Benchmarks: HAR-RV only (standard), GJR-GARCH (close-to-close), EWMA

  OOS: IS first 60%, OOS last 40%. Rolling refit every 63 days.
  Evaluation: QLIKE, MSE, MAE, Spearman, DM test (Harvey |t|>3.0)

Data:
  - TAIFEX TX tick (2017-05 to 2025-12, night session era)
  - yfinance: ^VIX, SPY

Error log rules:
  - DM test: Newey-West HAC (not custom)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - 0050.TW: must use clean_tw50_data
  - signal.shift(1): all features at t use info from t-1

References:
  - Corsi (2009): HAR-RV model
  - Hansen & Lunde (2005): Optimal weighting for RV_total
  - Patton (2011): QLIKE proxy-robust loss
  - Andersen, Bollerslev, Diebold (2007): HAR-RV-J
  - Barndorff-Nielsen & Shephard (2004): Bipower variation

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

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k874_results.json")
CHARTS_DIR = os.path.join(SCRIPT_DIR, "k874_charts")
os.makedirs(CHARTS_DIR, exist_ok=True)

# Session boundaries (HHMMSS integer)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# OOS config
REFIT_FREQ = 63       # Refit every 63 trading days (~1 quarter)
MIN_TRAIN = 250       # Minimum training observations
IS_FRACTION = 0.60    # In-sample fraction

# Night session started 2017-05-15
NIGHT_SESSION_START_DATE = "2017-05-15"


# ============================================================
# Step 1: Build 5-min RV from tick data (adapted from K849)
# ============================================================

def time_to_5min_bucket(time_int):
    """Convert HHMMSS integer to a 5-minute bucket label."""
    h = time_int // 10000
    m = (time_int % 10000) // 100
    m5 = (m // 5) * 5
    return h * 100 + m5


def compute_rv_bpv(returns):
    """Compute RV and BPV from an array of 5-min log returns."""
    if len(returns) < 1:
        return np.nan, np.nan
    rv = np.sum(returns ** 2)
    if len(returns) >= 2:
        bpv = (np.pi / 2) * np.sum(np.abs(returns[1:]) * np.abs(returns[:-1]))
    else:
        bpv = np.nan
    return float(rv), float(bpv)


def safe_volume(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def process_single_file(filepath):
    """
    Process one TX file -> compute session-level returns and RV.

    Returns:
      - rv_day: 5-min RV for regular session (8:45-13:45)
      - rv_night: 5-min RV for night session (15:00-05:00)
      - day_open, day_close: first/last price in regular session
      - night_close: last price in night session (for overnight gap calc)
      - day_return: log(day_close / day_open) = intraday return
    """
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

    # Use TX with volume-based contract selection (NOT TX1)
    df['delivery'] = df.iloc[:, 2].astype(str).str.strip()
    vol_by_delivery = df.groupby('delivery')['volume'].sum()
    if len(vol_by_delivery) > 0:
        near_month = vol_by_delivery.idxmax()
        df = df[df['delivery'] == near_month]

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

    # Compute 5-min RV for each session
    day_rets = build_5min_returns(t[day_mask], p[day_mask])
    night_pm_rets = build_5min_returns(t[night_pm_mask], p[night_pm_mask])
    night_am_rets = build_5min_returns(t[night_am_mask], p[night_am_mask])

    if len(night_pm_rets) > 0 or len(night_am_rets) > 0:
        night_rets = np.concatenate([night_pm_rets, night_am_rets])
    else:
        night_rets = np.array([])

    rv_day, bpv_day = compute_rv_bpv(day_rets)
    rv_night, bpv_night = compute_rv_bpv(night_rets)

    # Key prices for overnight gap calculation
    day_p = p[day_mask]
    night_pm_p = p[night_pm_mask]
    night_am_p = p[night_am_mask]

    day_open = float(day_p[0]) if len(day_p) > 0 else np.nan
    day_close = float(day_p[-1]) if len(day_p) > 0 else np.nan

    # Night close = last trade in AM session (before 05:00), or last PM if no AM
    if len(night_am_p) > 0:
        night_close = float(night_am_p[-1])
    elif len(night_pm_p) > 0:
        night_close = float(night_pm_p[-1])
    else:
        night_close = np.nan

    # Night open = first trade in PM session (15:00+)
    night_open = float(night_pm_p[0]) if len(night_pm_p) > 0 else np.nan

    # Day session return (intraday)
    if not np.isnan(day_open) and not np.isnan(day_close) and day_open > 0:
        day_return = np.log(day_close / day_open)
    else:
        day_return = np.nan

    # Jump component
    jump_day = max(rv_day - bpv_day, 0) if (not np.isnan(rv_day) and not np.isnan(bpv_day)) else np.nan

    # RV total
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
        'bpv_day': bpv_day if not np.isnan(bpv_day) else None,
        'jump_day': jump_day if not np.isnan(jump_day) else None,
        'day_open': day_open if not np.isnan(day_open) else None,
        'day_close': day_close if not np.isnan(day_close) else None,
        'night_open': night_open if not np.isnan(night_open) else None,
        'night_close': night_close if not np.isnan(night_close) else None,
        'day_return': day_return if not np.isnan(day_return) else None,
    }


def load_all_rv_data():
    """Load TX files (night session era) and compute 5-min RV."""
    # Use TX files (not TX1) for volume-based contract selection
    pattern = os.path.join(DATA_DIR, "Daily_*TX.csv")
    all_files = sorted(glob.glob(pattern))

    # Filter to night session era (2017-05+) through end 2025
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

    # Convert to float
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


# ============================================================
# Step 2: Compute overnight gap (r²_overnight)
# ============================================================

def compute_overnight_gap(rv_df):
    """
    Overnight gap return: log(day_open_t / day_close_{t-1})
    This is the gap between yesterday's regular-session close and today's open.

    Also computes: night-session return = log(night_close_t / night_open_t)
    where night_open is at 15:00 after day close at 13:45.
    """
    df = rv_df.copy()

    # Overnight gap = log(today_day_open / yesterday_day_close)
    df['prev_day_close'] = df['day_close'].shift(1)
    df['overnight_gap'] = np.log(df['day_open'] / df['prev_day_close'])
    df['r2_overnight'] = df['overnight_gap'] ** 2

    # Night session return (15:00 to 05:00 next morning)
    # night_open and night_close are from the SAME file (same day session date)
    # night_open is 15:00 (after 13:45 close), night_close is ~05:00 next morning
    mask = df['night_open'].notna() & df['night_close'].notna() & (df['night_open'] > 0)
    df['night_return'] = np.nan
    df.loc[mask, 'night_return'] = np.log(df.loc[mask, 'night_close'] / df.loc[mask, 'night_open'])
    df['r2_night_return'] = df['night_return'] ** 2

    return df


# ============================================================
# Step 3: Load external data (VIX, SPY)
# ============================================================

def load_external_data(start_date, end_date):
    """Load VIX and SPY daily data from yfinance."""
    import yfinance as yf

    print("  Loading VIX and SPY from yfinance...")
    vix = yf.download('^VIX', start=start_date, end=end_date, progress=False)
    spy = yf.download('SPY', start=start_date, end=end_date, progress=False)

    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    ext = pd.DataFrame(index=vix.index)
    ext.index = pd.to_datetime(ext.index).tz_localize(None)
    ext['vix_close'] = vix['Close'].values
    ext['spy_close'] = spy['Close'].reindex(vix.index).values
    ext['spy_ret'] = np.log(ext['spy_close'] / ext['spy_close'].shift(1))
    ext['spy_abs_ret'] = ext['spy_ret'].abs()

    print(f"  VIX: {len(ext)} days")
    return ext


# ============================================================
# Step 4: OLS fitting
# ============================================================

def fit_ols(y, X):
    """OLS fit: y = X @ beta + e. Returns beta, y_hat, R²."""
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


def newey_west_tstats(y, X, beta, y_hat):
    """Compute Newey-West HAC t-stats for OLS regression."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    resid = y - y_hat
    max_lag = int(np.ceil(n ** (1/3)))

    S = np.zeros((X_c.shape[1], X_c.shape[1]))
    for lag in range(max_lag + 1):
        weight = 1.0 if lag == 0 else (1 - lag / (max_lag + 1))
        if lag == 0:
            Gamma = (X_c * resid[:, None]).T @ (X_c * resid[:, None]) / n
        else:
            Gamma = (X_c[lag:] * resid[lag:, None]).T @ (X_c[:-lag] * resid[:-lag, None]) / n
            S += weight * (Gamma + Gamma.T)
            continue
        S += weight * Gamma

    try:
        XtX_inv = np.linalg.inv(X_c.T @ X_c / n)
        V = XtX_inv @ S @ XtX_inv / n
        se = np.sqrt(np.diag(V))
        t_stats = beta / se
        return se, t_stats
    except Exception:
        return np.full_like(beta, np.nan), np.full_like(beta, np.nan)


# ============================================================
# Step 5: Model A — HAR for intraday vol (log scale)
# ============================================================

def model_a_features(log_rv_intra, r2_overnight, idx):
    """
    Build HAR features for Model A at index idx (using data up to idx-1).
    log(RV_intra_{t+1}) = α + β₁·log(RV_d) + β₂·log(RV_5d) + β₃·log(RV_22d) + γ·r²_overnight_t

    All features use data from t-1 or earlier (no lookahead).
    """
    if idx < 22:
        return None

    rv_d = log_rv_intra[idx - 1]
    rv_w = np.mean(log_rv_intra[max(0, idx - 5):idx])
    rv_m = np.mean(log_rv_intra[max(0, idx - 22):idx])
    r2_on = r2_overnight[idx - 1] if idx >= 1 else np.nan

    if any(np.isnan([rv_d, rv_w, rv_m, r2_on])):
        return None

    return np.array([rv_d, rv_w, rv_m, r2_on])


def model_a_oos(rv_df, oos_start_idx, refit_freq=REFIT_FREQ, min_train=MIN_TRAIN):
    """
    OOS forecasting for Model A (HAR for intraday vol).
    Predicts log(RV_intra_{t+1}), returns exp() as forecast in level space.
    """
    log_rv = np.log(rv_df['rv_day'].values.clip(min=1e-12))
    r2_on = rv_df['r2_overnight'].values
    n = len(rv_df)

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq

    for t in range(oos_start_idx, n):
        # Refit periodically
        if t - last_fit_idx >= refit_freq or last_beta is None:
            # Build training features
            y_list, x_list = [], []
            for i in range(22, t):
                feat = model_a_features(log_rv, r2_on, i)
                if feat is not None and not np.isnan(log_rv[i]):
                    y_list.append(log_rv[i])
                    x_list.append(feat)

            if len(y_list) < min_train:
                continue

            y_train = np.array(y_list)
            X_train = np.array(x_list)
            beta, _, _ = fit_ols(y_train, X_train)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        feat_t = model_a_features(log_rv, r2_on, t)
        if feat_t is None:
            continue

        x_t = np.concatenate([[1.0], feat_t])
        log_fc = x_t @ last_beta
        # Bias correction for log-to-level: exp(log_fc + σ²/2) ≈ exp(log_fc)
        # We skip bias correction for simplicity (consistent with Corsi 2009 practice)
        forecasts[t] = np.exp(log_fc)

    return pd.Series(forecasts, index=rv_df.index, name='Model_A_HAR_Intra')


# ============================================================
# Step 6: Model B — Overnight gap vol prediction
# ============================================================

def model_b_features(log_rv_night, log_rv_intra, vix, spy_abs_ret, idx):
    """
    Build features for Model B at index idx (using data up to idx-1).
    log(RV_night_{t+1}) = α + β₁·log(RV_night_t) + β₂·log(RV_night_5d)
                          + β₃·log(RV_night_22d) + β₄·log(RV_intra_t)
                          + β₅·VIX_t + β₆·|SPY_ret_t|

    Predicts NIGHT SESSION RV (5-min RV from 15:00-05:00), NOT the overnight gap.
    This is the correct target for division of labor:
      rv_total ≈ rv_day + rv_night
    So Model A predicts rv_day, Model B predicts rv_night.

    Uses HAR-like structure (d/w/m lags) for long memory.
    Cross-terms: log(RV_intra) captures intraday→overnight spillover.
    VIX and |SPY_ret| capture global risk (US market drives Taiwan night session).
    """
    if idx < 22:
        return None

    rv_d = log_rv_night[idx - 1]
    rv_w = np.mean(log_rv_night[max(0, idx - 5):idx])
    rv_m = np.mean(log_rv_night[max(0, idx - 22):idx])
    rv_i_lag = log_rv_intra[idx - 1]
    vix_lag = vix[idx - 1]
    spy_lag = spy_abs_ret[idx - 1]

    if any(np.isnan([rv_d, rv_w, rv_m, rv_i_lag, vix_lag, spy_lag])):
        return None

    return np.array([rv_d, rv_w, rv_m, rv_i_lag, vix_lag, spy_lag])


def model_b_oos(rv_df, ext_df, oos_start_idx, refit_freq=REFIT_FREQ, min_train=MIN_TRAIN):
    """
    OOS forecasting for Model B (night session RV).
    Predicts log(RV_night_{t+1}), returns exp() as forecast in level space.
    Uses HAR-like structure with external regressors (VIX, |SPY_ret|).
    """
    log_rv_night = np.log(rv_df['rv_night'].values.clip(min=1e-12))
    log_rv_intra = np.log(rv_df['rv_day'].values.clip(min=1e-12))
    vix = rv_df['vix_close'].values
    spy_abs = rv_df['spy_abs_ret'].values
    n = len(rv_df)

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq

    for t in range(oos_start_idx, n):
        if t - last_fit_idx >= refit_freq or last_beta is None:
            y_list, x_list = [], []
            for i in range(22, t):
                feat = model_b_features(log_rv_night, log_rv_intra, vix, spy_abs, i)
                if feat is not None and not np.isnan(log_rv_night[i]):
                    y_list.append(log_rv_night[i])
                    x_list.append(feat)

            if len(y_list) < min_train:
                continue

            y_train = np.array(y_list)
            X_train = np.array(x_list)
            beta, _, _ = fit_ols(y_train, X_train)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        feat_t = model_b_features(log_rv_night, log_rv_intra, vix, spy_abs, t)
        if feat_t is None:
            continue

        x_t = np.concatenate([[1.0], feat_t])
        log_fc = x_t @ last_beta
        forecasts[t] = np.exp(log_fc)

    return pd.Series(forecasts, index=rv_df.index, name='Model_B_Night')


# ============================================================
# Step 7: Combined model + benchmarks
# ============================================================

def combined_forecast(fc_a, fc_b, rv_df, oos_start_idx, refit_freq=REFIT_FREQ):
    """
    Combined models. Since rv_total ≈ rv_day + rv_night (by construction),
    the natural combination is sum.

    Methods:
    1. Joint_Sum: simple sum of component forecasts
    2. Joint_OLS: regress rv_total on component forecasts (free OLS weights)
    3. Joint_Constrained: OLS weights clamped to [0, 2] (prevent blow-up)
    """
    rv_total = rv_df['rv_total'].values
    n = len(rv_df)

    # Method 1: Simple sum (w₁=1, w₂=1)
    fc_sum = fc_a.values + fc_b.values

    # Method 2: OLS-optimal weights (refit)
    fc_ols_w = np.full(n, np.nan)
    last_beta_comb = None
    last_fit_comb = -refit_freq

    for t in range(oos_start_idx, n):
        if t - last_fit_comb >= refit_freq or last_beta_comb is None:
            valid = (np.isfinite(fc_a.values[:t]) & np.isfinite(fc_b.values[:t])
                     & np.isfinite(rv_total[:t]))
            if np.sum(valid) > MIN_TRAIN:
                y_tr = rv_total[:t][valid]
                X_tr = np.column_stack([fc_a.values[:t][valid], fc_b.values[:t][valid]])
                beta_c, _, _ = fit_ols(y_tr, X_tr)
                if beta_c is not None:
                    last_beta_comb = beta_c
                    last_fit_comb = t

        if last_beta_comb is not None:
            if np.isfinite(fc_a.values[t]) and np.isfinite(fc_b.values[t]):
                x = np.array([1.0, fc_a.values[t], fc_b.values[t]])
                fc_ols_w[t] = max(x @ last_beta_comb, 1e-12)

    # Method 3: Constrained — clamp OLS weights to [0, 2]
    fc_constrained = np.full(n, np.nan)
    last_beta_con = None
    last_fit_con = -refit_freq

    for t in range(oos_start_idx, n):
        if t - last_fit_con >= refit_freq or last_beta_con is None:
            valid = (np.isfinite(fc_a.values[:t]) & np.isfinite(fc_b.values[:t])
                     & np.isfinite(rv_total[:t]))
            if np.sum(valid) > MIN_TRAIN:
                y_tr = rv_total[:t][valid]
                X_tr = np.column_stack([fc_a.values[:t][valid], fc_b.values[:t][valid]])
                beta_c, _, _ = fit_ols(y_tr, X_tr)
                if beta_c is not None:
                    b0 = beta_c[0]
                    b1 = np.clip(beta_c[1], 0, 2)
                    b2 = np.clip(beta_c[2], 0, 2)
                    last_beta_con = np.array([b0, b1, b2])
                    last_fit_con = t

        if last_beta_con is not None:
            if np.isfinite(fc_a.values[t]) and np.isfinite(fc_b.values[t]):
                x = np.array([1.0, fc_a.values[t], fc_b.values[t]])
                fc_constrained[t] = max(x @ last_beta_con, 1e-12)

    return {
        'Joint_Sum': pd.Series(fc_sum, index=rv_df.index, name='Joint_Sum'),
        'Joint_OLS': pd.Series(fc_ols_w, index=rv_df.index, name='Joint_OLS'),
        'Joint_Constrained': pd.Series(fc_constrained, index=rv_df.index, name='Joint_Constrained'),
    }


def standard_har_oos(rv_df, oos_start_idx, refit_freq=REFIT_FREQ, min_train=MIN_TRAIN):
    """
    Standard HAR-RV predicting rv_total (benchmark).
    log(RV_total_{t+1}) = α + β₁·log(RV_d) + β₂·log(RV_5d) + β₃·log(RV_22d)
    """
    rv_total = rv_df['rv_total'].values
    log_rv = np.log(rv_total.clip(min=1e-12))
    n = len(rv_df)

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq

    for t in range(oos_start_idx, n):
        if t - last_fit_idx >= refit_freq or last_beta is None:
            y_list, x_list = [], []
            for i in range(22, t):
                rv_d = log_rv[i - 1]
                rv_w = np.mean(log_rv[max(0, i - 5):i])
                rv_m = np.mean(log_rv[max(0, i - 22):i])
                if not any(np.isnan([rv_d, rv_w, rv_m, log_rv[i]])):
                    y_list.append(log_rv[i])
                    x_list.append([rv_d, rv_w, rv_m])

            if len(y_list) < min_train:
                continue

            y_train = np.array(y_list)
            X_train = np.array(x_list)
            beta, _, _ = fit_ols(y_train, X_train)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        rv_d = log_rv[t - 1]
        rv_w = np.mean(log_rv[max(0, t - 5):t])
        rv_m = np.mean(log_rv[max(0, t - 22):t])

        if any(np.isnan([rv_d, rv_w, rv_m])):
            continue

        x_t = np.array([1.0, rv_d, rv_w, rv_m])
        forecasts[t] = np.exp(x_t @ last_beta)

    return pd.Series(forecasts, index=rv_df.index, name='HAR_RV_Total')


def gjr_garch_oos(rv_df, oos_start_idx, refit_freq=REFIT_FREQ, init_window=500):
    """
    GJR-GARCH(1,1) on 0050.TW daily close-to-close returns.
    OOS recursive: h[t] = omega + (alpha + gamma*I)*r²[t-1] + beta*h[t-1]
    """
    import arch

    sys.path.insert(0, os.path.join(SCRIPT_DIR, '..', 'src'))
    from volpred.utils import clean_tw50_data
    import yfinance as yf

    print("  GJR-GARCH: loading 0050.TW...")
    raw = yf.download('0050.TW', start='2016-01-01', end='2026-01-01', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close_series = raw['Close'].squeeze()
    clean_prices, clean_returns = clean_tw50_data(close_series)
    etf = pd.DataFrame({'Close': clean_prices, 'Return': clean_returns})
    etf['log_ret'] = np.log(etf['Close'] / etf['Close'].shift(1))
    etf = etf.dropna(subset=['log_ret'])
    etf.index = pd.to_datetime(etf.index).tz_localize(None)

    common_dates = rv_df.index.intersection(etf.index)
    print(f"  GJR-GARCH: {len(common_dates)} common dates")

    returns_pct = etf.loc[common_dates, 'log_ret'] * 100
    returns_raw = etf.loc[common_dates, 'log_ret']

    oos_idx = np.searchsorted(common_dates, rv_df.index[oos_start_idx])
    if oos_idx < init_window:
        oos_idx = init_window

    forecasts = pd.Series(np.nan, index=common_dates, name='GJR_GARCH')
    r_squared = pd.Series(returns_raw.values ** 2, index=common_dates, name='r_squared')

    last_params = None
    last_fit_idx = -refit_freq
    last_h = None

    for t in range(oos_idx, len(common_dates)):
        if t - last_fit_idx >= refit_freq or last_params is None:
            train = returns_pct.iloc[:t]
            if len(train) < init_window:
                continue
            try:
                model = arch.arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='t')
                res = model.fit(disp='off', show_warning=False)
                if res.convergence_flag == 0:
                    last_params = {
                        'omega': res.params['omega'],
                        'alpha': res.params['alpha[1]'],
                        'gamma': res.params['gamma[1]'],
                        'beta': res.params['beta[1]'],
                        'nu': res.params['nu'],
                    }
                    last_h = res.conditional_volatility.iloc[-1] ** 2
                    last_fit_idx = t
            except Exception:
                pass

        if last_params is None or last_h is None:
            continue

        r_prev = returns_pct.iloc[t - 1]
        I_neg = 1.0 if r_prev < 0 else 0.0
        r2_prev = r_prev ** 2

        h_t = (last_params['omega'] +
               (last_params['alpha'] + last_params['gamma'] * I_neg) * r2_prev +
               last_params['beta'] * last_h)
        last_h = h_t
        forecasts.iloc[t] = h_t / 10000.0  # pct² → decimal²

    return forecasts, r_squared


def ewma_forecast(r_squared_series, lam=0.94):
    """EWMA: h[t] = λ·h[t-1] + (1-λ)·r²[t-1]"""
    r2 = r_squared_series.values.copy()
    n = len(r2)
    h = np.full(n, np.nan)
    h[0] = r2[0] if not np.isnan(r2[0]) else np.nanmean(r2[:20])

    for t in range(1, n):
        if np.isnan(r2[t - 1]):
            h[t] = h[t - 1] if not np.isnan(h[t - 1]) else h[0]
        else:
            h_prev = h[t - 1] if not np.isnan(h[t - 1]) else r2[t - 1]
            h[t] = lam * h_prev + (1 - lam) * r2[t - 1]

    return pd.Series(h, index=r_squared_series.index, name='EWMA')


# ============================================================
# Step 8: Evaluation metrics
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
    t, f = np.asarray(target, dtype=float), np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    return float(np.mean((t[valid] - f[valid]) ** 2)) if np.sum(valid) > 10 else np.nan


def mae_metric(target, forecast):
    t, f = np.asarray(target, dtype=float), np.asarray(forecast, dtype=float)
    valid = np.isfinite(t) & np.isfinite(f)
    return float(np.mean(np.abs(t[valid] - f[valid]))) if np.sum(valid) > 10 else np.nan


def spearman_corr(target, forecast):
    t, f = np.asarray(target, dtype=float), np.asarray(forecast, dtype=float)
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
# Step 9: In-sample diagnostics
# ============================================================

def insample_diagnostics(rv_df, ext_df):
    """Full-sample regression diagnostics for both models."""
    results = {}

    # Model A: log(RV_intra) ~ log(RV_d) + log(RV_5d) + log(RV_22d) + r²_overnight
    log_rv = np.log(rv_df['rv_day'].values.clip(min=1e-12))
    r2_on = rv_df['r2_overnight'].values
    n = len(rv_df)

    y_list, x_list = [], []
    for i in range(22, n):
        feat = model_a_features(log_rv, r2_on, i)
        if feat is not None and not np.isnan(log_rv[i]):
            y_list.append(log_rv[i])
            x_list.append(feat)

    if len(y_list) > 50:
        y = np.array(y_list)
        X = np.array(x_list)
        beta, y_hat, r2 = fit_ols(y, X)
        if beta is not None:
            se, t_stats = newey_west_tstats(y, X, beta, y_hat)
            names_a = ['const', 'log(RV_d)', 'log(RV_5d)', 'log(RV_22d)', 'r²_overnight']
            coeffs = {}
            for i, nm in enumerate(names_a):
                coeffs[nm] = {
                    'estimate': round(float(beta[i]), 8),
                    'se': round(float(se[i]), 8),
                    't_stat': round(float(t_stats[i]), 4),
                }
            results['Model_A'] = {
                'n': len(y),
                'R2': round(float(r2), 6),
                'coefficients': coeffs,
                'description': 'HAR for intraday vol (log scale) with overnight cross-term',
            }

    # Model B: log(RV_night) ~ HAR structure + log(RV_intra) + VIX + |SPY_ret|
    log_rv_night_v = np.log(rv_df['rv_night'].values.clip(min=1e-12))
    log_rv_intra_v = np.log(rv_df['rv_day'].values.clip(min=1e-12))
    vix_v = rv_df['vix_close'].values
    spy_abs_v = rv_df['spy_abs_ret'].values

    y_list_b, x_list_b = [], []
    for i in range(22, n):
        feat = model_b_features(log_rv_night_v, log_rv_intra_v, vix_v, spy_abs_v, i)
        if feat is not None and not np.isnan(log_rv_night_v[i]):
            y_list_b.append(log_rv_night_v[i])
            x_list_b.append(feat)

    if len(y_list_b) > 50:
        y = np.array(y_list_b)
        X = np.array(x_list_b)
        beta, y_hat, r2 = fit_ols(y, X)
        if beta is not None:
            se, t_stats = newey_west_tstats(y, X, beta, y_hat)
            names_b = ['const', 'log(RV_night_d)', 'log(RV_night_5d)', 'log(RV_night_22d)',
                        'log(RV_intra)', 'VIX', '|SPY_ret|']
            coeffs = {}
            for i, nm in enumerate(names_b):
                coeffs[nm] = {
                    'estimate': round(float(beta[i]), 8),
                    'se': round(float(se[i]), 8),
                    't_stat': round(float(t_stats[i]), 4),
                }
            results['Model_B'] = {
                'n': len(y),
                'R2': round(float(r2), 6),
                'coefficients': coeffs,
                'description': 'HAR for night session RV with cross-regressors (intraday RV + VIX + SPY)',
            }

    return results


# ============================================================
# Step 10: Charting
# ============================================================

def make_charts(rv_df, all_forecasts, oos_start_idx, results_dict):
    """Generate diagnostic charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    oos_dates = rv_df.index[oos_start_idx:]

    # Chart 1: QLIKE comparison bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    model_names = list(results_dict['oos_metrics_rv_total'].keys())
    qlikes = [results_dict['oos_metrics_rv_total'][m].get('QLIKE', np.nan) for m in model_names]
    colors = ['#2196F3' if 'Joint' in m else '#FF9800' if 'HAR' in m
              else '#4CAF50' if 'GJR' in m else '#9E9E9E' for m in model_names]
    bars = ax.bar(range(len(model_names)), qlikes, color=colors, edgecolor='black', linewidth=0.5)
    ax.set_xticks(range(len(model_names)))
    ax.set_xticklabels(model_names, rotation=30, ha='right', fontsize=9)
    ax.set_ylabel('QLIKE (lower = better)')
    ax.set_title('K874: QLIKE on RV_total — Joint vs Single Models (OOS)')
    ax.grid(axis='y', alpha=0.3)
    for bar, q in zip(bars, qlikes):
        if not np.isnan(q):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                    f'{q:.4f}', ha='center', va='bottom', fontsize=8)
    plt.tight_layout()
    path1 = os.path.join(CHARTS_DIR, 'qlike_comparison.png')
    plt.savefig(path1, dpi=150)
    plt.close()
    print(f"  Chart saved: {path1}")

    # Chart 2: Component vs target time series (OOS period)
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # Panel A: Intraday RV
    ax = axes[0]
    rv_day_oos = rv_df['rv_day'].loc[oos_dates]
    ax.plot(rv_day_oos.index, rv_day_oos.values * 1e4, 'k-', alpha=0.4, linewidth=0.5, label='RV_intra (actual)')
    if 'Model_A_HAR_Intra' in all_forecasts:
        fc_a = all_forecasts['Model_A_HAR_Intra'].loc[oos_dates]
        ax.plot(fc_a.index, fc_a.values * 1e4, 'b-', alpha=0.7, linewidth=0.8, label='Model A forecast')
    ax.set_ylabel('RV_intra (×10⁴)')
    ax.set_title('Panel A: Model A — HAR for Intraday Volatility')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)

    # Panel B: Night session RV
    ax = axes[1]
    rv_night_oos = rv_df['rv_night'].loc[oos_dates]
    ax.plot(rv_night_oos.index, rv_night_oos.values * 1e4, 'k-', alpha=0.4, linewidth=0.5, label='RV_night (actual)')
    if 'Model_B_Night' in all_forecasts:
        fc_b = all_forecasts['Model_B_Night'].loc[oos_dates]
        ax.plot(fc_b.index, fc_b.values * 1e4, 'r-', alpha=0.7, linewidth=0.8, label='Model B forecast')
    ax.set_ylabel('RV_night (×10⁴)')
    ax.set_title('Panel B: Model B — Night Session Volatility (HAR)')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)

    # Panel C: Total RV
    ax = axes[2]
    rv_total_oos = rv_df['rv_total'].loc[oos_dates]
    ax.plot(rv_total_oos.index, rv_total_oos.values * 1e4, 'k-', alpha=0.4, linewidth=0.5, label='RV_total (actual)')
    for name in ['Joint_Sum', 'Joint_OLS', 'HAR_RV_Total']:
        if name in all_forecasts:
            fc = all_forecasts[name].loc[oos_dates]
            style = {'Joint_Sum': ('g-', 0.8), 'Joint_OLS': ('m-', 0.8), 'HAR_RV_Total': ('b--', 0.6)}
            ax.plot(fc.index, fc.values * 1e4, style.get(name, ('c-', 0.5))[0],
                    alpha=style.get(name, ('c-', 0.5))[1], linewidth=0.8, label=name)
    ax.set_ylabel('RV_total (×10⁴)')
    ax.set_title('Panel C: Combined Models vs Standard HAR on RV_total')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.tight_layout()
    path2 = os.path.join(CHARTS_DIR, 'component_forecasts.png')
    plt.savefig(path2, dpi=150)
    plt.close()
    print(f"  Chart saved: {path2}")

    # Chart 3: Spearman rank comparison
    fig, ax = plt.subplots(figsize=(10, 6))
    spearmans = [results_dict['oos_metrics_rv_total'][m].get('Spearman_rho', np.nan) for m in model_names]
    bars = ax.bar(range(len(model_names)), spearmans, color=colors, edgecolor='black', linewidth=0.5)
    ax.set_xticks(range(len(model_names)))
    ax.set_xticklabels(model_names, rotation=30, ha='right', fontsize=9)
    ax.set_ylabel('Spearman ρ (higher = better)')
    ax.set_title('K874: Spearman Rank Correlation with RV_total (OOS)')
    ax.grid(axis='y', alpha=0.3)
    for bar, s in zip(bars, spearmans):
        if not np.isnan(s):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                    f'{s:.3f}', ha='center', va='bottom', fontsize=8)
    plt.tight_layout()
    path3 = os.path.join(CHARTS_DIR, 'spearman_comparison.png')
    plt.savefig(path3, dpi=150)
    plt.close()
    print(f"  Chart saved: {path3}")

    # Chart 4: Cross-information scatter
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    # Left: overnight gap → next-day intraday vol
    valid = rv_df['r2_overnight'].notna() & rv_df['rv_day'].shift(-1).notna()
    if valid.sum() > 50:
        x = rv_df.loc[valid, 'r2_overnight'].values * 1e4
        y = rv_df['rv_day'].shift(-1).loc[valid].values * 1e4
        ax = axes[0]
        ax.scatter(x, y, alpha=0.15, s=5, c='blue')
        rho, p = sp_stats.spearmanr(x, y)
        ax.set_xlabel('r²_overnight_t (×10⁴)')
        ax.set_ylabel('RV_intra_{t+1} (×10⁴)')
        ax.set_title(f'Overnight → Next-Day Intraday\nSpearman ρ={rho:.3f} (p={p:.3e})')
        ax.grid(alpha=0.2)

    # Right: intraday vol → next-day overnight gap
    valid2 = rv_df['rv_day'].notna() & rv_df['r2_overnight'].shift(-1).notna()
    if valid2.sum() > 50:
        x2 = rv_df.loc[valid2, 'rv_day'].values * 1e4
        y2 = rv_df['r2_overnight'].shift(-1).loc[valid2].values * 1e4
        ax = axes[1]
        ax.scatter(x2, y2, alpha=0.15, s=5, c='red')
        rho2, p2 = sp_stats.spearmanr(x2, y2)
        ax.set_xlabel('RV_intra_t (×10⁴)')
        ax.set_ylabel('r²_overnight_{t+1} (×10⁴)')
        ax.set_title(f'Intraday → Next-Day Overnight\nSpearman ρ={rho2:.3f} (p={p2:.3e})')
        ax.grid(alpha=0.2)

    plt.suptitle('K874: Cross-Information Between Sessions', fontsize=12, y=1.02)
    plt.tight_layout()
    path4 = os.path.join(CHARTS_DIR, 'cross_information.png')
    plt.savefig(path4, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {path4}")

    return [path1, path2, path3, path4]


# ============================================================
# Main Execution
# ============================================================

def main():
    print("=" * 70)
    print("K874: Joint HAR-Overnight Model — Division of Labor")
    print("=" * 70)
    start_time = datetime.now()

    # ── Step 1: Load tick data and compute RV ──
    print("\n[Step 1] Loading TAIFEX TX tick data and computing 5-min RV...")
    rv_df = load_all_rv_data()
    print(f"  Period: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")
    print(f"  Total days: {len(rv_df)}")

    # ── Step 2: Compute overnight gap ──
    print("\n[Step 2] Computing overnight gap returns...")
    rv_df = compute_overnight_gap(rv_df)
    n_gap = rv_df['r2_overnight'].notna().sum()
    print(f"  Overnight gap computed: {n_gap} days")

    # ── Step 3: Load external data ──
    print("\n[Step 3] Loading VIX and SPY data...")
    start_str = str(rv_df.index[0].date())
    end_str = '2026-01-01'
    ext_df = load_external_data(start_str, end_str)

    # Merge external data with rv_df (US data has different trading days)
    # Use forward-fill: for Taiwan trading days without US data, use last known US data
    # This is correct because Taiwan sees yesterday's US close before opening
    for col in ['vix_close', 'spy_abs_ret']:
        rv_df[col] = ext_df[col].reindex(rv_df.index, method='ffill')

    # Drop rows with missing critical data
    mask = (rv_df['rv_day'].notna() & rv_df['rv_night'].notna()
            & rv_df['rv_total'].notna() & rv_df['vix_close'].notna()
            & rv_df['spy_abs_ret'].notna() & rv_df['r2_overnight'].notna())
    rv_df_clean = rv_df[mask].copy()
    print(f"  Clean dataset: {len(rv_df_clean)} days ({rv_df_clean.index[0].date()} to {rv_df_clean.index[-1].date()})")

    # ── Step 4: Descriptive statistics ──
    print("\n[Step 4] Descriptive statistics...")
    desc_stats = {}
    for col in ['rv_day', 'rv_night', 'rv_total', 'r2_overnight']:
        s = rv_df_clean[col].dropna()
        desc_stats[col] = {
            'mean': round(float(s.mean()), 8),
            'std': round(float(s.std()), 8),
            'median': round(float(s.median()), 8),
            'skewness': round(float(s.skew()), 4),
            'kurtosis': round(float(s.kurtosis()), 4),
            'n': int(len(s)),
        }
        print(f"  {col}: mean={s.mean():.6f}, std={s.std():.6f}, skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

    # Cross-session correlations
    print("\n  Cross-session correlations (Spearman):")
    corr_pairs = [
        ('r2_overnight', 'rv_day', 'shift(-1)'),  # overnight_t → next-day intraday
        ('rv_day', 'r2_overnight', 'shift(-1)'),   # intraday_t → next-day overnight
        ('rv_day', 'rv_night', 'same day'),         # same-day intraday vs night
    ]
    cross_corr = {}
    for c1, c2, desc in corr_pairs:
        if 'shift' in desc:
            s1 = rv_df_clean[c1]
            s2 = rv_df_clean[c2].shift(-1)
        else:
            s1 = rv_df_clean[c1]
            s2 = rv_df_clean[c2]
        valid = s1.notna() & s2.notna()
        if valid.sum() > 50:
            rho, p = sp_stats.spearmanr(s1[valid], s2[valid])
            cross_corr[f'{c1}_to_{c2}_{desc}'] = {
                'rho': round(rho, 4), 'p': round(p, 6), 'n': int(valid.sum())
            }
            print(f"  {c1} → {c2} ({desc}): ρ={rho:.4f} (p={p:.4e})")

    # ── Step 5: In-sample diagnostics ──
    print("\n[Step 5] In-sample diagnostics (full sample)...")
    is_diag = insample_diagnostics(rv_df_clean, ext_df)
    for model_name, diag in is_diag.items():
        print(f"\n  {model_name} (R²={diag['R2']:.4f}, n={diag['n']}):")
        for coeff_name, coeff in diag['coefficients'].items():
            sig = '***' if abs(coeff['t_stat']) > 3.0 else '**' if abs(coeff['t_stat']) > 2.0 else ''
            print(f"    {coeff_name}: β={coeff['estimate']:.6f} (t={coeff['t_stat']:.2f}) {sig}")

    # ── Step 6: OOS forecasting ──
    n_total = len(rv_df_clean)
    oos_start_idx = int(n_total * IS_FRACTION)
    oos_date = rv_df_clean.index[oos_start_idx]
    print(f"\n[Step 6] OOS Forecasting (IS: {rv_df_clean.index[0].date()} to {rv_df_clean.index[oos_start_idx-1].date()}, "
          f"OOS: {oos_date.date()} to {rv_df_clean.index[-1].date()})...")
    print(f"  IS: {oos_start_idx} days, OOS: {n_total - oos_start_idx} days")

    # Model A: HAR for intraday
    print("\n  Running Model A (HAR for intraday)...")
    fc_a = model_a_oos(rv_df_clean, oos_start_idx)
    n_a = fc_a.notna().sum()
    print(f"    Model A: {n_a} OOS forecasts")

    # Model B: Overnight gap
    print("  Running Model B (Overnight gap)...")
    fc_b = model_b_oos(rv_df_clean, ext_df, oos_start_idx)
    n_b = fc_b.notna().sum()
    print(f"    Model B: {n_b} OOS forecasts")

    # Combined models
    print("  Running combined models...")
    combined = combined_forecast(fc_a, fc_b, rv_df_clean, oos_start_idx)

    # Benchmark: Standard HAR on RV_total
    print("  Running standard HAR-RV (benchmark)...")
    fc_har = standard_har_oos(rv_df_clean, oos_start_idx)
    n_har = fc_har.notna().sum()
    print(f"    Standard HAR: {n_har} OOS forecasts")

    # Benchmark: GJR-GARCH
    print("  Running GJR-GARCH (benchmark)...")
    fc_gjr, r_sq = gjr_garch_oos(rv_df_clean, oos_start_idx)
    # Reindex to match rv_df_clean
    fc_gjr = fc_gjr.reindex(rv_df_clean.index)
    r_sq = r_sq.reindex(rv_df_clean.index)
    n_gjr = fc_gjr.notna().sum()
    print(f"    GJR-GARCH: {n_gjr} OOS forecasts")

    # Benchmark: EWMA
    print("  Running EWMA (benchmark)...")
    # EWMA on close-to-close r²
    day_ret_sq = rv_df_clean['day_return'] ** 2
    fc_ewma = ewma_forecast(day_ret_sq, lam=0.94)

    # Collect all forecasts
    all_forecasts = {
        'Model_A_HAR_Intra': fc_a,
        'Model_B_Night': fc_b,
        'Joint_Sum': combined['Joint_Sum'],
        'Joint_OLS': combined['Joint_OLS'],
        'Joint_Constrained': combined['Joint_Constrained'],
        'HAR_RV_Total': fc_har,
        'GJR_GARCH': fc_gjr,
        'EWMA': fc_ewma,
    }

    # ── Step 7: Evaluation ──
    print("\n[Step 7] Evaluation...")

    # 7a: Each component on its native target
    print("\n  7a: Component models on native targets:")
    native_metrics = {}

    # Model A vs RV_intra
    oos_mask = rv_df_clean.index >= oos_date
    rv_day_oos = rv_df_clean.loc[oos_mask, 'rv_day']
    fc_a_oos = fc_a[oos_mask]
    valid = rv_day_oos.notna() & fc_a_oos.notna()
    if valid.sum() > 10:
        native_metrics['Model_A_on_RV_intra'] = {
            'QLIKE': round(qlike(rv_day_oos[valid], fc_a_oos[valid]), 6),
            'MSE': round(mse_metric(rv_day_oos[valid], fc_a_oos[valid]), 10),
            'MAE': round(mae_metric(rv_day_oos[valid], fc_a_oos[valid]), 8),
            'Spearman_rho': round(spearman_corr(rv_day_oos[valid], fc_a_oos[valid])[0], 4),
            'n': int(valid.sum()),
        }
        print(f"    Model A on RV_intra: QLIKE={native_metrics['Model_A_on_RV_intra']['QLIKE']:.4f}, "
              f"Spearman={native_metrics['Model_A_on_RV_intra']['Spearman_rho']:.4f}")

    # Model B vs RV_night (its native target)
    rv_night_oos = rv_df_clean.loc[oos_mask, 'rv_night']
    fc_b_oos = fc_b[oos_mask]
    valid_b = rv_night_oos.notna() & fc_b_oos.notna()
    if valid_b.sum() > 10:
        native_metrics['Model_B_on_RV_night'] = {
            'QLIKE': round(qlike(rv_night_oos[valid_b], fc_b_oos[valid_b]), 6),
            'MSE': round(mse_metric(rv_night_oos[valid_b], fc_b_oos[valid_b]), 10),
            'MAE': round(mae_metric(rv_night_oos[valid_b], fc_b_oos[valid_b]), 8),
            'Spearman_rho': round(spearman_corr(rv_night_oos[valid_b], fc_b_oos[valid_b])[0], 4),
            'n': int(valid_b.sum()),
        }
        print(f"    Model B on RV_night: QLIKE={native_metrics['Model_B_on_RV_night']['QLIKE']:.4f}, "
              f"Spearman={native_metrics['Model_B_on_RV_night']['Spearman_rho']:.4f}")

    # 7b: All models on RV_total
    print("\n  7b: All models on RV_total (unified comparison):")
    rv_total_oos = rv_df_clean.loc[oos_mask, 'rv_total']
    metrics_rv_total = {}

    for name, fc in all_forecasts.items():
        fc_oos = fc[oos_mask] if hasattr(fc, '__getitem__') else fc.loc[oos_mask]
        valid = rv_total_oos.notna() & pd.Series(fc_oos).notna()
        if isinstance(valid, pd.Series):
            valid = valid.values
        # Ensure alignment
        target_vals = rv_total_oos.values
        fc_vals = fc_oos.values if hasattr(fc_oos, 'values') else np.asarray(fc_oos)
        valid = np.isfinite(target_vals) & np.isfinite(fc_vals)

        if valid.sum() > 10:
            metrics_rv_total[name] = {
                'QLIKE': round(qlike(target_vals[valid], fc_vals[valid]), 6),
                'MSE': round(mse_metric(target_vals[valid], fc_vals[valid]), 10),
                'MAE': round(mae_metric(target_vals[valid], fc_vals[valid]), 8),
                'Spearman_rho': round(spearman_corr(target_vals[valid], fc_vals[valid])[0], 4),
                'n': int(valid.sum()),
            }
            print(f"    {name:25s}: QLIKE={metrics_rv_total[name]['QLIKE']:.4f}, "
                  f"MSE={metrics_rv_total[name]['MSE']:.2e}, "
                  f"Spearman={metrics_rv_total[name]['Spearman_rho']:.4f}, "
                  f"n={metrics_rv_total[name]['n']}")

    # 7c: DM tests (Joint vs each benchmark)
    print("\n  7c: DM tests (QLIKE loss, negative t = first model better):")
    dm_results = {}
    # Select best joint model by QLIKE on RV_total
    joint_candidates = ['Joint_Constrained', 'Joint_Sum', 'Joint_OLS']
    best_joint = 'Joint_Sum'  # default
    best_qlike_val = float('inf')
    for jc in joint_candidates:
        if jc in metrics_rv_total:
            q = metrics_rv_total[jc].get('QLIKE', float('inf'))
            if q < best_qlike_val:
                best_qlike_val = q
                best_joint = jc
    print(f"\n  Best joint model (by QLIKE): {best_joint} (QLIKE={best_qlike_val:.4f})")

    target_vals_full = rv_total_oos.values
    fc_joint_vals = all_forecasts[best_joint][oos_mask].values

    for benchmark_name in ['HAR_RV_Total', 'GJR_GARCH', 'EWMA', 'Model_A_HAR_Intra', 'Model_B_Night']:
        if benchmark_name not in all_forecasts:
            continue
        fc_bench_vals = all_forecasts[benchmark_name][oos_mask].values

        # Aligned valid
        valid = (np.isfinite(target_vals_full) & np.isfinite(fc_joint_vals)
                 & np.isfinite(fc_bench_vals) & (target_vals_full > 0)
                 & (fc_joint_vals > 0) & (fc_bench_vals > 0))

        if valid.sum() > 50:
            loss_joint = qlike_loss_series(target_vals_full[valid], fc_joint_vals[valid])
            loss_bench = qlike_loss_series(target_vals_full[valid], fc_bench_vals[valid])
            t_stat, p_val = dm_test(loss_joint, loss_bench)
            dm_results[f'{best_joint}_vs_{benchmark_name}'] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'n': int(valid.sum()),
                'significant_Harvey': abs(t_stat) > 3.0,
                'winner': best_joint if t_stat < 0 else benchmark_name,
            }
            sig = '***' if abs(t_stat) > 3.0 else '**' if abs(t_stat) > 2.0 else ''
            winner = best_joint if t_stat < 0 else benchmark_name
            print(f"    {best_joint} vs {benchmark_name:25s}: t={t_stat:+.4f} (p={p_val:.4e}) {sig} → {winner}")

    # Also: Joint_Sum vs Joint_OLS
    if 'Joint_Sum' in all_forecasts and 'Joint_OLS' in all_forecasts:
        fc_sum_vals = all_forecasts['Joint_Sum'][oos_mask].values
        fc_ols_vals = all_forecasts['Joint_OLS'][oos_mask].values
        valid = (np.isfinite(target_vals_full) & np.isfinite(fc_sum_vals)
                 & np.isfinite(fc_ols_vals) & (target_vals_full > 0)
                 & (fc_sum_vals > 0) & (fc_ols_vals > 0))
        if valid.sum() > 50:
            loss_sum = qlike_loss_series(target_vals_full[valid], fc_sum_vals[valid])
            loss_ols = qlike_loss_series(target_vals_full[valid], fc_ols_vals[valid])
            t_stat, p_val = dm_test(loss_sum, loss_ols)
            dm_results['Joint_Sum_vs_Joint_OLS'] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'n': int(valid.sum()),
                'significant_Harvey': abs(t_stat) > 3.0,
                'winner': 'Joint_Sum' if t_stat < 0 else 'Joint_OLS',
            }
            sig = '***' if abs(t_stat) > 3.0 else ''
            winner = 'Joint_Sum' if t_stat < 0 else 'Joint_OLS'
            print(f"    Joint_Sum vs Joint_OLS: t={t_stat:+.4f} (p={p_val:.4e}) {sig} → {winner}")

    # 7d: Also compare on QLIKE with r² (Patton 2011 proxy-robust)
    print("\n  7d: All models on r² (Patton 2011 proxy-robust):")
    day_ret_sq_oos = (rv_df_clean.loc[oos_mask, 'day_return'] ** 2).values
    metrics_r2 = {}
    for name, fc in all_forecasts.items():
        fc_vals = fc[oos_mask].values
        valid = np.isfinite(day_ret_sq_oos) & np.isfinite(fc_vals) & (day_ret_sq_oos > 0) & (fc_vals > 0)
        if valid.sum() > 10:
            metrics_r2[name] = {
                'QLIKE': round(qlike(day_ret_sq_oos[valid], fc_vals[valid]), 6),
                'Spearman_rho': round(spearman_corr(day_ret_sq_oos[valid], fc_vals[valid])[0], 4),
                'n': int(valid.sum()),
            }
            print(f"    {name:25s}: QLIKE={metrics_r2[name]['QLIKE']:.4f}, "
                  f"Spearman={metrics_r2[name]['Spearman_rho']:.4f}")

    # ── Step 8: Cross-OOS stability ──
    print("\n[Step 8] Cross-OOS stability (5 folds)...")
    oos_rv_total = rv_df_clean.loc[oos_mask, 'rv_total']
    fold_forecasts = {}
    for name in ['Joint_Constrained', 'Joint_OLS', 'Joint_Sum', 'HAR_RV_Total', 'GJR_GARCH']:
        if name in all_forecasts:
            fold_forecasts[name] = all_forecasts[name][oos_mask]

    n_oos = len(oos_rv_total)
    n_folds = 5
    fold_size = n_oos // n_folds
    cross_oos_results = []

    for f_idx in range(n_folds):
        s = f_idx * fold_size
        e = (f_idx + 1) * fold_size if f_idx < n_folds - 1 else n_oos
        fold_dates = oos_rv_total.index[s:e]
        target_fold = oos_rv_total.iloc[s:e].values

        fold_r = {
            'fold': f_idx + 1,
            'start': str(fold_dates[0].date()),
            'end': str(fold_dates[-1].date()),
            'n': len(fold_dates),
        }

        for name, fc in fold_forecasts.items():
            fc_fold = fc.iloc[s:e].values
            valid = np.isfinite(target_fold) & np.isfinite(fc_fold) & (target_fold > 0) & (fc_fold > 0)
            if valid.sum() > 10:
                fold_r[f'{name}_QLIKE'] = round(qlike(target_fold[valid], fc_fold[valid]), 6)
                rho, _ = spearman_corr(target_fold[valid], fc_fold[valid])
                fold_r[f'{name}_Spearman'] = round(rho, 4)

        cross_oos_results.append(fold_r)
        print(f"  Fold {f_idx+1} ({fold_r['start']} to {fold_r['end']}, n={fold_r['n']}):")
        for name in fold_forecasts:
            q = fold_r.get(f'{name}_QLIKE', np.nan)
            s_rho = fold_r.get(f'{name}_Spearman', np.nan)
            print(f"    {name:20s}: QLIKE={q}, Spearman={s_rho}")

    # ── Step 9: Charts ──
    print("\n[Step 9] Generating charts...")
    results_for_charts = {
        'oos_metrics_rv_total': metrics_rv_total,
    }
    chart_paths = make_charts(rv_df_clean, all_forecasts, oos_start_idx, results_for_charts)

    # ── Step 10: Compile results ──
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n[Step 10] Compiling results (elapsed: {elapsed:.1f}s)...")

    # Key question answer
    joint_better = False
    har_qlike = metrics_rv_total.get('HAR_RV_Total', {}).get('QLIKE', 999)
    joint_ols_qlike = metrics_rv_total.get('Joint_OLS', {}).get('QLIKE', 999)
    joint_sum_qlike = metrics_rv_total.get('Joint_Sum', {}).get('QLIKE', 999)
    joint_con_qlike = metrics_rv_total.get('Joint_Constrained', {}).get('QLIKE', 999)
    best_joint_qlike = min(joint_ols_qlike, joint_sum_qlike, joint_con_qlike)
    if best_joint_qlike < har_qlike:
        # Check if DM significant
        for dm_key, dm_val in dm_results.items():
            if 'HAR_RV_Total' in dm_key and dm_val.get('significant_Harvey'):
                joint_better = True

    results = {
        'experiment_id': 'K874',
        'title': 'Joint HAR-Overnight Model — Division of Labor for Full-Day Volatility',
        'date': '2026-04-05',
        'data_source': 'TAIFEX TX tick (volume-selected contract) + yfinance (^VIX, SPY)',
        'data_period': f"{rv_df_clean.index[0].date()} to {rv_df_clean.index[-1].date()}",
        'n_days': len(rv_df_clean),
        'is_period': f"{rv_df_clean.index[0].date()} to {rv_df_clean.index[oos_start_idx-1].date()}",
        'oos_period': f"{oos_date.date()} to {rv_df_clean.index[-1].date()}",
        'is_n': oos_start_idx,
        'oos_n': n_total - oos_start_idx,
        'methodology': {
            'Model_A': 'HAR for intraday vol: log(RV_intra) ~ log(RV_d) + log(RV_5d) + log(RV_22d) + r²_overnight',
            'Model_B': 'HAR for night session RV: log(RV_night) ~ HAR(d,w,m) + log(RV_intra) + VIX + |SPY_ret|',
            'Joint_Sum': 'h_total = Model_A_forecast + Model_B_forecast (additive)',
            'Joint_OLS': 'h_total = α + w₁·Model_A + w₂·Model_B (OLS-optimized weights)',
            'Joint_Constrained': 'h_total = α + w₁·Model_A + w₂·Model_B (OLS weights clamped to [0,2])',
            'Benchmark_HAR': 'Standard HAR-RV on log(RV_total)',
            'Benchmark_GJR': 'GJR-GARCH(1,1) on 0050.TW close-to-close returns',
            'Benchmark_EWMA': 'EWMA λ=0.94 on daily r²',
            'refit_freq': REFIT_FREQ,
            'min_train': MIN_TRAIN,
        },
        'descriptive_stats': desc_stats,
        'cross_session_correlations': cross_corr,
        'insample_diagnostics': is_diag,
        'native_target_metrics': native_metrics,
        'oos_metrics_rv_total': metrics_rv_total,
        'oos_metrics_r_squared': metrics_r2,
        'dm_tests': dm_results,
        'cross_oos_stability': cross_oos_results,
        'key_finding': {
            'joint_better_than_HAR': joint_better,
            'best_joint_QLIKE': round(best_joint_qlike, 6),
            'HAR_total_QLIKE': round(har_qlike, 6),
            'interpretation': (
                'The joint model combines specialized predictions: HAR for intraday '
                'and a regression for overnight gap. The key empirical question is whether '
                'the cross-information (overnight→intraday and vice versa) adds value '
                'compared to a single HAR model predicting total RV directly.'
            ),
        },
        'charts': [os.path.basename(p) for p in chart_paths],
        'references': [
            'Corsi (2009): HAR-RV model',
            'Hansen & Lunde (2005): 5-min RV as gold standard, optimal weighting',
            'Patton (2011): QLIKE proxy-robust loss function',
            'Andersen, Bollerslev, Diebold (2007): HAR-RV-J with jumps',
        ],
        'runtime_seconds': round(elapsed, 1),
    }

    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved: {OUTPUT_FILE}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  OOS Period: {results['oos_period']} ({results['oos_n']} days)")
    print(f"\n  QLIKE on RV_total (lower = better):")
    for name in ['Joint_Constrained', 'Joint_Sum', 'Joint_OLS', 'HAR_RV_Total', 'GJR_GARCH', 'EWMA']:
        if name in metrics_rv_total:
            print(f"    {name:25s}: {metrics_rv_total[name]['QLIKE']:.4f}")
    print(f"\n  Key Finding: Joint model {'BETTER' if joint_better else 'NOT significantly better'} "
          f"than standard HAR (Harvey |t|>3.0)")
    print(f"  Runtime: {elapsed:.1f}s")

    return results


if __name__ == '__main__':
    results = main()
