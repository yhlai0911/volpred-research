#!/usr/bin/env python3
"""
K851: Jump Dynamics — Lagged Jump Features for Next-Day Volatility Prediction
==============================================================================

Purpose:
  K849 showed HAR-RV-J (with same-period jump) was NS vs HAR-RV (DM test).
  This experiment tests whether LAGGED jump features (frequency, size, sign)
  can predict next-day RV beyond what HAR-RV already captures.

Core Question:
  1. Does jump frequency (% days with jumps in past 22d) predict future vol?
  2. Do positive vs negative jumps have asymmetric predictive power?
  3. Can lagged jump size (avg jump magnitude over 5d) improve HAR-RV?

Models (all OOS, Track A = day-only RV, 14 years):
  1. HAR-RV (baseline): RV_t = b0 + b1*RV_{t-1} + b2*RV_w + b3*RV_m
  2. HAR-RV-J: + Jump_{t-1}
  3. HAR-RV-JFreq: + JumpFreq_22d (fraction of days with jump in past 22d)
  4. HAR-RV-JSize: + JumpSize_5d (mean jump size over past 5d)
  5. HAR-RV-SignedJ: + PosJump_{t-1} + NegJump_{t-1} (signed decomposition)
  6. HAR-RV-Full: + Jump_{t-1} + JumpFreq_22d + JumpSize_5d

Data: TAIFEX TX1 tick → 5-min bars → RV, BPV, Jump
  Day session only (08:45-13:45), 2012-2025

OOS: IS 2012-2019, OOS 2020-2024 (Track A, same as K849)
Metrics: QLIKE on RV_day, MSE, MAE, Spearman
DM test: Newey-West HAC, Harvey t>3.0 threshold

Error log rules applied:
  - DM test: Newey-West HAC (implemented below, not from volpred which is for strategies)
  - GARCH OOS: N/A (pure HAR models)
  - Sanity check: verify sign of jump coefficients makes economic sense

References:
  - Andersen, Bollerslev, Diebold (2007): Roughing it up — jump component in HAR
  - Corsi (2009): HAR-RV model
  - Barndorff-Nielsen & Shephard (2004): Bipower variation for jump detection
  - Patton (2011): QLIKE proxy-robust
  - Tauchen & Zhou (2011): Realized jumps on the international stock markets, JFE
  - Busch, Christensen, Nielsen (2011): Role of implied volatility in forecasting future RV

Author: VolPred Research System
Date: 2026-04-03
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

# Session boundaries (HHMMSS) - day session only for Track A
DAY_START = 84500
DAY_END = 134500

# OOS split
OOS_START = '2020-01-01'
REFIT_FREQ = 63       # Refit every quarter
MIN_TRAIN = 250       # Minimum training observations
JUMP_THRESHOLD = 0.0  # Jump = max(RV - BPV, 0), any positive = jump detected


# ============================================================
# Step 1: Build 5-min RV from tick data (reused from K848/K849)
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


def process_single_file(filepath):
    """Process one TX1 file -> compute day-session 5-min RV, BPV, Jump."""
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
        df = df.dropna(subset=['price', 'time_int'])
        df['time_int'] = df['time_int'].astype(int)
    except Exception:
        return None

    if len(df) < 10:
        return None

    t = df['time_int'].values
    p = df['price'].values

    # Day session only
    day_mask = (t >= DAY_START) & (t <= DAY_END)
    session_t = t[day_mask]
    session_p = p[day_mask]

    if len(session_t) < 5:
        return None

    # Build 5-min bars
    buckets = np.array([time_to_5min_bucket(ti) for ti in session_t])
    unique_buckets = np.unique(buckets)
    bar_closes = []
    for b in unique_buckets:
        bucket_mask = buckets == b
        bar_closes.append(session_p[bucket_mask][-1])
    bar_closes = np.array(bar_closes, dtype=float)

    if len(bar_closes) < 2:
        return None

    # 5-min log returns
    log_returns = np.diff(np.log(bar_closes))
    rv, bpv = compute_rv_bpv(log_returns)

    if np.isnan(rv):
        return None

    jump = max(rv - bpv, 0) if not np.isnan(bpv) else 0.0

    # Day return for signed jump decomposition
    day_return = np.log(float(bar_closes[-1]) / float(bar_closes[0]))

    return {
        'date': date_str,
        'rv_day': rv,
        'bpv_day': bpv if not np.isnan(bpv) else None,
        'jump': jump,
        'day_return': day_return,
        'n_bars': len(bar_closes),
    }


def load_all_rv_data():
    """Load TX1 files from 2012 to end 2025, day session only."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    # From 2012 to 2025
    files = [f for f in all_files
             if os.path.basename(f) >= "Daily_2012_01_01"
             and os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files (2012-2025)")

    results = []
    errors = 0

    n_workers = min(8, os.cpu_count() or 4)
    print(f"  Using {n_workers} workers for parallel processing...")

    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_single_file, f): f for f in files}
        done_count = 0
        for future in as_completed(futures):
            done_count += 1
            if done_count % 500 == 0:
                print(f"    Processed {done_count}/{len(files)} files...")
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
                else:
                    errors += 1
            except Exception:
                errors += 1

    print(f"  Loaded: {len(results)}, Errors/skipped: {errors}")

    df = pd.DataFrame(results)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()
    return df


# ============================================================
# Step 2: Build jump features
# ============================================================

def build_jump_features(rv_df):
    """
    Build all jump-related features from RV/BPV/Jump data.
    All features are LAGGED (use information up to t-1 to forecast t).
    """
    df = rv_df.copy()

    # Basic jump
    df['jump_lag1'] = df['jump'].shift(1)

    # Jump frequency: fraction of days with jump > 0 in past 22 trading days
    # A "jump day" = jump > 0 (already thresholded at max(RV-BPV, 0))
    df['jump_indicator'] = (df['jump'] > 0).astype(float)
    df['jump_freq_22d'] = df['jump_indicator'].rolling(22, min_periods=15).mean().shift(1)

    # Jump size: average jump magnitude over past 5 trading days
    df['jump_size_5d'] = df['jump'].rolling(5, min_periods=3).mean().shift(1)

    # Signed jump decomposition:
    # Positive jump: jump on up days (day_return > 0)
    # Negative jump: jump on down days (day_return < 0)
    df['pos_jump'] = df['jump'] * (df['day_return'] > 0).astype(float)
    df['neg_jump'] = df['jump'] * (df['day_return'] <= 0).astype(float)
    df['pos_jump_lag1'] = df['pos_jump'].shift(1)
    df['neg_jump_lag1'] = df['neg_jump'].shift(1)

    # HAR components (all lagged)
    df['rv_lag1'] = df['rv_day'].shift(1)
    df['rv_5d'] = df['rv_day'].rolling(5, min_periods=3).mean().shift(1)
    df['rv_22d'] = df['rv_day'].rolling(22, min_periods=15).mean().shift(1)

    return df


# ============================================================
# Step 3: HAR-RV OLS + OOS forecasting
# ============================================================

def fit_har_ols(y, X):
    """OLS fit: y = X @ beta + e. Returns beta, y_hat, R2, residuals."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        y_hat = X_c @ beta
        resid = y - y_hat
        ss_res = np.sum(resid ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        # Standard errors (OLS, no HAC for speed)
        sigma2 = ss_res / max(n - X_c.shape[1], 1)
        try:
            cov = sigma2 * np.linalg.inv(X_c.T @ X_c)
            se = np.sqrt(np.diag(cov))
        except Exception:
            se = np.full(len(beta), np.nan)
        return beta, y_hat, r2, se
    except Exception:
        return None, None, None, None


MODEL_FEATURES = {
    'HAR-RV':       ['rv_lag1', 'rv_5d', 'rv_22d'],
    'HAR-RV-J':     ['rv_lag1', 'rv_5d', 'rv_22d', 'jump_lag1'],
    'HAR-RV-JFreq': ['rv_lag1', 'rv_5d', 'rv_22d', 'jump_freq_22d'],
    'HAR-RV-JSize': ['rv_lag1', 'rv_5d', 'rv_22d', 'jump_size_5d'],
    'HAR-RV-SignedJ': ['rv_lag1', 'rv_5d', 'rv_22d', 'pos_jump_lag1', 'neg_jump_lag1'],
    'HAR-RV-Full':  ['rv_lag1', 'rv_5d', 'rv_22d', 'jump_lag1', 'jump_freq_22d', 'jump_size_5d'],
}


def har_oos_forecast(df, model_name, oos_start, refit_freq=REFIT_FREQ, min_train=MIN_TRAIN):
    """
    Rolling OOS forecast for a given HAR model variant.
    Features defined in MODEL_FEATURES dict.
    """
    feature_cols = MODEL_FEATURES[model_name]
    target_col = 'rv_day'

    # Get valid data
    required = [target_col] + feature_cols
    valid_df = df[required].dropna()

    rv = valid_df[target_col].values
    X_all = valid_df[feature_cols].values
    dates = valid_df.index
    n = len(rv)

    oos_idx = np.searchsorted(dates, pd.Timestamp(oos_start))
    if oos_idx < min_train:
        oos_idx = min_train

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_fit_idx = -refit_freq

    for t in range(oos_idx, n):
        # Refit periodically
        if t - last_fit_idx >= refit_freq or last_beta is None:
            y_train = rv[:t]
            X_train = X_all[:t]
            beta, _, _, _ = fit_har_ols(y_train, X_train)
            if beta is not None:
                last_beta = beta
                last_fit_idx = t

        if last_beta is None:
            continue

        # Forecast for time t using features at t (which are all lagged)
        x_t = np.concatenate([[1.0], X_all[t]])
        forecast = x_t @ last_beta
        forecasts[t] = max(forecast, 1e-12)  # Floor at small positive

    return pd.Series(forecasts, index=dates, name=model_name)


# ============================================================
# Step 4: Evaluation metrics
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


def qlike_loss_series(target, forecast):
    """Per-observation QLIKE loss for DM test."""
    t = np.asarray(target, dtype=float)
    f = np.asarray(forecast, dtype=float)
    ratio = t / f
    loss = ratio - np.log(ratio) - 1
    loss[~np.isfinite(loss)] = np.nan
    loss[(t <= 0) | (f <= 0)] = np.nan
    return loss


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
# Step 5: In-sample diagnostics
# ============================================================

def insample_diagnostics(df, model_name, end_date):
    """Fit HAR model on IS data and return coefficient info."""
    feature_cols = MODEL_FEATURES[model_name]
    target_col = 'rv_day'

    required = [target_col] + feature_cols
    is_df = df.loc[:end_date, required].dropna()

    y = is_df[target_col].values
    X = is_df[feature_cols].values

    if len(y) < 50:
        return None

    beta, y_hat, r2, se = fit_har_ols(y, X)
    if beta is None:
        return None

    coef_names = ['const'] + feature_cols
    result = {
        'model': model_name,
        'n': len(y),
        'R2': round(r2, 6),
        'coefficients': {}
    }
    for i, name in enumerate(coef_names):
        t_stat = beta[i] / se[i] if not np.isnan(se[i]) and se[i] > 0 else np.nan
        result['coefficients'][name] = {
            'estimate': round(float(beta[i]), 8),
            'se': round(float(se[i]), 8) if not np.isnan(se[i]) else None,
            't_stat': round(float(t_stat), 4) if not np.isnan(t_stat) else None,
        }

    return result


# ============================================================
# Step 6: Jump descriptive statistics
# ============================================================

def jump_descriptive_stats(df):
    """Compute descriptive statistics for jump features."""
    stats = {}

    # Jump statistics
    jumps = df['jump'].dropna()
    jump_days = (jumps > 0).sum()
    total_days = len(jumps)

    stats['jump_summary'] = {
        'total_days': int(total_days),
        'jump_days': int(jump_days),
        'jump_freq_pct': round(100 * jump_days / total_days, 1),
        'mean_jump_all': float(jumps.mean()),
        'mean_jump_when_positive': float(jumps[jumps > 0].mean()) if jump_days > 0 else None,
        'std_jump_when_positive': float(jumps[jumps > 0].std()) if jump_days > 0 else None,
        'jump_as_pct_of_rv': round(100 * jumps.mean() / df['rv_day'].mean(), 1),
    }

    # Signed jump stats
    pos = df['pos_jump'].dropna()
    neg = df['neg_jump'].dropna()
    stats['signed_jump'] = {
        'pos_jump_mean': float(pos.mean()),
        'neg_jump_mean': float(neg.mean()),
        'pos_jump_days': int((pos > 0).sum()),
        'neg_jump_days': int((neg > 0).sum()),
        'pos_neg_ratio': round(float(pos.mean()) / float(neg.mean()), 3) if neg.mean() > 0 else None,
    }

    # Jump frequency distribution
    jf = df['jump_freq_22d'].dropna()
    stats['jump_freq_22d_stats'] = {
        'mean': round(float(jf.mean()), 4),
        'std': round(float(jf.std()), 4),
        'min': round(float(jf.min()), 4),
        'max': round(float(jf.max()), 4),
        'median': round(float(jf.median()), 4),
    }

    # Correlation between jump features and future RV
    rv_next = df['rv_day']
    corr_features = ['jump_lag1', 'jump_freq_22d', 'jump_size_5d', 'pos_jump_lag1', 'neg_jump_lag1']
    stats['correlation_with_future_rv'] = {}
    for feat in corr_features:
        if feat in df.columns:
            valid = df[[feat, 'rv_day']].dropna()
            if len(valid) > 30:
                rho, pval = sp_stats.spearmanr(valid[feat], valid['rv_day'])
                stats['correlation_with_future_rv'][feat] = {
                    'spearman_rho': round(float(rho), 4),
                    'p_value': float(pval),
                    'significant_5pct': pval < 0.05,
                }

    return stats


# ============================================================
# Main execution
# ============================================================

def main():
    print("=" * 70)
    print("K851: Jump Dynamics — Lagged Jump Features for Next-Day Vol Prediction")
    print("=" * 70)
    t0 = datetime.now()

    # ----------------------------------------------------------
    # 1. Load tick data and compute RV/BPV/Jump
    # ----------------------------------------------------------
    print("\n[1] Loading TAIFEX TX1 tick data and computing 5-min RV...")
    rv_df = load_all_rv_data()
    print(f"    Total trading days: {len(rv_df)}")
    print(f"    Date range: {rv_df.index.min().date()} to {rv_df.index.max().date()}")

    # ----------------------------------------------------------
    # 2. Build jump features
    # ----------------------------------------------------------
    print("\n[2] Building jump features...")
    df = build_jump_features(rv_df)
    print(f"    Features built. Columns: {list(df.columns)}")

    # ----------------------------------------------------------
    # 3. Jump descriptive statistics
    # ----------------------------------------------------------
    print("\n[3] Jump descriptive statistics...")
    jump_stats = jump_descriptive_stats(df)
    print(f"    Jump frequency: {jump_stats['jump_summary']['jump_freq_pct']}% of days")
    print(f"    Jump as % of RV: {jump_stats['jump_summary']['jump_as_pct_of_rv']}%")
    print(f"    Pos jump days: {jump_stats['signed_jump']['pos_jump_days']}, "
          f"Neg jump days: {jump_stats['signed_jump']['neg_jump_days']}")

    # Print correlations
    print("\n    Correlation of lagged jump features with future RV:")
    for feat, vals in jump_stats.get('correlation_with_future_rv', {}).items():
        sig = "***" if vals['p_value'] < 0.001 else ("**" if vals['p_value'] < 0.01 else ("*" if vals['p_value'] < 0.05 else ""))
        print(f"      {feat}: rho={vals['spearman_rho']:.4f} {sig}")

    # ----------------------------------------------------------
    # 4. In-sample diagnostics (IS: < 2020)
    # ----------------------------------------------------------
    print("\n[4] In-sample diagnostics (2012-2019)...")
    is_results = {}
    for model_name in MODEL_FEATURES:
        result = insample_diagnostics(df, model_name, '2019-12-31')
        if result:
            is_results[model_name] = result
            print(f"    {model_name}: R2={result['R2']:.4f}, n={result['n']}")
            for coef_name, coef_val in result['coefficients'].items():
                if coef_name not in ['const', 'rv_lag1', 'rv_5d', 'rv_22d']:
                    t_str = f"t={coef_val['t_stat']:.2f}" if coef_val['t_stat'] else "t=N/A"
                    print(f"      {coef_name}: β={coef_val['estimate']:.6f} ({t_str})")

    # ----------------------------------------------------------
    # 5. OOS forecasting for all models
    # ----------------------------------------------------------
    print(f"\n[5] OOS forecasting (OOS start: {OOS_START})...")
    forecasts = {}
    for model_name in MODEL_FEATURES:
        print(f"    Running {model_name}...")
        fc = har_oos_forecast(df, model_name, OOS_START)
        forecasts[model_name] = fc
        n_valid = fc.notna().sum()
        print(f"      {n_valid} valid OOS forecasts")

    # ----------------------------------------------------------
    # 6. Evaluate OOS metrics
    # ----------------------------------------------------------
    print(f"\n[6] Evaluating OOS metrics...")

    # Get OOS target — use df's rv_day column, filter by date
    rv_all = df['rv_day']

    oos_metrics = {}
    loss_series = {}

    for model_name, fc in forecasts.items():
        # Filter to OOS period by date comparison on forecast's own index
        fc_oos = fc[fc.index >= OOS_START].dropna()

        # Align with rv_day
        common = rv_all.index.intersection(fc_oos.index)
        target = rv_all.loc[common].values
        pred = fc_oos.loc[common].values

        ql = qlike(target, pred)
        ms = mse_metric(target, pred)
        ma = mae_metric(target, pred)
        rho, pval = spearman_corr(target, pred)

        oos_metrics[model_name] = {
            'QLIKE': round(ql, 6) if not np.isnan(ql) else None,
            'MSE': float(f"{ms:.6e}") if not np.isnan(ms) else None,
            'MAE': float(f"{ma:.6e}") if not np.isnan(ma) else None,
            'Spearman': round(rho, 4) if not np.isnan(rho) else None,
            'Spearman_p': float(pval) if not np.isnan(pval) else None,
            'n_oos': len(common),
        }

        loss_series[model_name] = qlike_loss_series(target, pred)
        print(f"    {model_name}: QLIKE={ql:.6f}, Spearman={rho:.4f}, n={len(common)}")

    # ----------------------------------------------------------
    # 7. DM tests (all models vs HAR-RV baseline)
    # ----------------------------------------------------------
    print(f"\n[7] DM tests vs HAR-RV baseline...")
    dm_results = {}
    baseline_loss = loss_series['HAR-RV']

    for model_name in MODEL_FEATURES:
        if model_name == 'HAR-RV':
            continue
        t_stat, p_val = dm_test(loss_series[model_name], baseline_loss)
        # Negative t -> model better than baseline (lower QLIKE loss)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.64 else ""))
        direction = "BETTER" if t_stat < 0 else "WORSE"
        dm_results[model_name + '_vs_HAR-RV'] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'Harvey_significant': abs(t_stat) > 3.0,
            'direction': direction,
        }
        print(f"    {model_name} vs HAR-RV: t={t_stat:.4f} ({direction}) {sig}")

    # Also test: HAR-RV-Full vs HAR-RV-J
    t_stat, p_val = dm_test(loss_series['HAR-RV-Full'], loss_series['HAR-RV-J'])
    direction = "BETTER" if t_stat < 0 else "WORSE"
    dm_results['HAR-RV-Full_vs_HAR-RV-J'] = {
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 6),
        'Harvey_significant': abs(t_stat) > 3.0,
        'direction': direction,
    }
    print(f"    HAR-RV-Full vs HAR-RV-J: t={t_stat:.4f} ({direction})")

    # Also test: HAR-RV-SignedJ vs HAR-RV-J
    t_stat, p_val = dm_test(loss_series['HAR-RV-SignedJ'], loss_series['HAR-RV-J'])
    direction = "BETTER" if t_stat < 0 else "WORSE"
    dm_results['HAR-RV-SignedJ_vs_HAR-RV-J'] = {
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 6),
        'Harvey_significant': abs(t_stat) > 3.0,
        'direction': direction,
    }
    print(f"    HAR-RV-SignedJ vs HAR-RV-J: t={t_stat:.4f} ({direction})")

    # ----------------------------------------------------------
    # 8. Cross-OOS stability (5 non-overlapping 2-year periods)
    # ----------------------------------------------------------
    print(f"\n[8] Cross-OOS stability check...")
    # Sub-period stability: split the OOS period (2020-2024) into yearly chunks
    cross_oos_periods = [
        ('2020-01-01', '2020-12-31'),
        ('2021-01-01', '2021-12-31'),
        ('2022-01-01', '2022-12-31'),
        ('2023-01-01', '2023-12-31'),
        ('2024-01-01', '2024-12-31'),
    ]

    cross_oos_results = {}
    for period_start, period_end in cross_oos_periods:
        period_key = f"{period_start[:4]}-{period_end[:4]}"
        mask = (df.index >= period_start) & (df.index <= period_end)
        rv_period = df.loc[mask, 'rv_day']

        period_results = {}
        for model_name, fc in forecasts.items():
            fc_period = fc[(fc.index >= period_start) & (fc.index <= period_end)].dropna()
            common = rv_period.index.intersection(fc_period.index)
            if len(common) < 30:
                continue
            target = rv_period.loc[common].values
            pred = fc_period.loc[common].values
            ql = qlike(target, pred)
            rho, _ = spearman_corr(target, pred)
            period_results[model_name] = {
                'QLIKE': round(ql, 6) if not np.isnan(ql) else None,
                'Spearman': round(rho, 4) if not np.isnan(rho) else None,
                'n': len(common),
            }

        cross_oos_results[period_key] = period_results
        # Print summary
        if period_results:
            best_model = min(period_results, key=lambda m: period_results[m].get('QLIKE', 999))
            print(f"    {period_key}: Best={best_model} (QLIKE={period_results[best_model]['QLIKE']})")
        else:
            print(f"    {period_key}: No valid forecasts")

    # Count wins per model
    win_counts = {m: 0 for m in MODEL_FEATURES}
    for period_key, period_res in cross_oos_results.items():
        if period_res:
            best = min(period_res, key=lambda m: period_res[m].get('QLIKE', 999))
            win_counts[best] += 1
    print(f"\n    Cross-OOS wins: {win_counts}")

    # ----------------------------------------------------------
    # 9. Summary and conclusions
    # ----------------------------------------------------------
    elapsed = (datetime.now() - t0).total_seconds()
    print(f"\n{'=' * 70}")
    print(f"Elapsed: {elapsed:.1f}s")

    # Determine best model
    best_model = min(oos_metrics, key=lambda m: oos_metrics[m].get('QLIKE', 999))
    best_qlike = oos_metrics[best_model]['QLIKE']
    baseline_qlike = oos_metrics['HAR-RV']['QLIKE']
    improvement = (baseline_qlike - best_qlike) / baseline_qlike * 100

    print(f"\nBest model: {best_model} (QLIKE={best_qlike:.6f})")
    print(f"HAR-RV baseline QLIKE: {baseline_qlike:.6f}")
    print(f"Improvement: {improvement:.2f}%")

    # Any significant DM results?
    significant_models = [k for k, v in dm_results.items() if v.get('Harvey_significant')]
    print(f"Harvey-significant (|t|>3.0): {significant_models if significant_models else 'NONE'}")

    # ----------------------------------------------------------
    # 10. Save results
    # ----------------------------------------------------------
    results = {
        'experiment_id': 'K851',
        'title': 'Jump Dynamics — Lagged Jump Features for Next-Day Volatility Prediction (TAIFEX)',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'TAIFEX TX1 tick data (day session, 5-min bars)',
        'data_period': '2012-01 to 2025-12',
        'oos_period': f'{OOS_START} to 2025-12',
        'n_total_days': int(len(rv_df)),
        'methodology': {
            'models': list(MODEL_FEATURES.keys()),
            'model_features': {k: v for k, v in MODEL_FEATURES.items()},
            'target': '5-min RV (day session)',
            'oos_method': f'Rolling with refit every {REFIT_FREQ} days, min_train={MIN_TRAIN}',
            'metrics': 'QLIKE (Patton 2011), MSE, MAE, Spearman',
            'dm_test': 'Newey-West HAC, Harvey threshold |t|>3.0',
        },
        'references': [
            'Andersen, Bollerslev, Diebold (2007): Roughing it up — HAR-RV-J, RES',
            'Corsi (2009): HAR-RV model, J. Financial Econometrics',
            'Barndorff-Nielsen & Shephard (2004): Bipower variation, J. Financial Econometrics',
            'Patton (2011): QLIKE proxy-robust, J. Econometrics',
            'Tauchen & Zhou (2011): Realized jumps on international stock markets, JFE',
            'Busch, Christensen, Nielsen (2011): Role of implied volatility in forecasting RV',
        ],
        'jump_descriptive_stats': jump_stats,
        'is_diagnostics': is_results,
        'oos_metrics': oos_metrics,
        'dm_tests': dm_results,
        'cross_oos_stability': cross_oos_results,
        'cross_oos_wins': win_counts,
        'conclusions': {
            'best_model': best_model,
            'best_qlike': best_qlike,
            'baseline_qlike': baseline_qlike,
            'improvement_pct': round(improvement, 2),
            'any_harvey_significant': len(significant_models) > 0,
            'significant_models': significant_models,
        },
        'elapsed_seconds': round(elapsed, 1),
    }

    output_path = os.path.join(SCRIPT_DIR, 'k851_jump_dynamics_results.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == '__main__':
    main()
