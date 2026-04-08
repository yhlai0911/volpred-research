#!/usr/bin/env python3
"""
K852b: Regime-Dependent HAR Model Coefficients for Taiwan Futures
=================================================================

Purpose:
  Investigate whether HAR-RV model coefficients change across VIX regimes
  and whether regime-dependent models improve prediction. Tests a Smooth
  Transition HAR (ST-HAR) model where HAR coefficients shift between
  low-vol and high-vol states via a logistic transition function.

Research Questions:
  1. Is HAR-RV's predictive power regime-dependent (better in high-vol vs low-vol)?
  2. Does a Smooth Transition HAR (ST-HAR) outperform standard HAR?
  3. Which HAR component (daily/weekly/monthly) varies most across regimes?

Prior Results:
  - K849: HAR-RV QLIKE=0.1808, dominates GJR (DM t=-11.14)
  - K851: BNS jumps add no significant value (DM t=1.10 NS)
  - K783c: Regime-dependent GARCH window sizes, but only 1/14 DM passed Harvey
  - K752: R² varies 0.24-0.64 across eras (regime dependence documented)

Methodology:
  1. Data: TAIFEX TX1 5-min RV (2017-2025, night session era) + VIX from yfinance
  2. VIX Regimes: Low (<15), Medium (15-25), High (>=25)
  3. Models:
     a) HAR-RV (baseline): log(RV_{t+1}) = β0 + β1*log(RV_t) + β5*log(RV_5d) + β22*log(RV_22d)
     b) HAR-RV-VIX: add log(VIX_t) as regressor
     c) Regime-HAR: separate HAR per VIX regime (3 separate OLS, pooled OOS)
     d) ST-HAR: smooth transition using VIX
        log(RV_{t+1}) = (1-G)*[β0_L + β1_L*x] + G*[β0_H + β1_H*x]
        G(VIX) = 1/(1+exp(-γ*(VIX-c)))
  4. OOS: Rolling window, IS first 60%, OOS last 40%. Refit every 63 days.
  5. Evaluation: QLIKE on RV, DM test (Harvey t>3.0), Spearman, R² by regime

Error Log Rules:
  - DM test: Newey-West HAC (K849 implementation)
  - Sanity check: compute actual values, never hard-code
  - Harvey threshold |t| > 3.0 for significance claims
  - All signals use info up to t-1 only (no lookahead)

References:
  - Corsi (2009) "A simple approximate long-memory model of RV" JFE
  - Gonzalez-Rivera, Lee, Mishra (2004) "Forecasting with threshold-HAR"
  - Patton & Sheppard (2015) "Good volatility, bad volatility" RFS
  - Terasvirta (1994) "Specification, estimation, evaluation of smooth transition AR models"
  - Hansen & Lunde (2005) "A forecast comparison of volatility models"
  - Patton (2011) "Volatility forecast comparison using imperfect proxies"

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

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Session boundaries (HHMMSS)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# HAR parameters
REFIT_FREQ = 63
MIN_TRAIN = 250
OOS_RATIO = 0.40  # 60/40 IS/OOS split

# VIX regime thresholds
VIX_LOW = 15.0
VIX_HIGH = 25.0


# ============================================================
# Step 1: Build 5-min RV from TAIFEX tick data (reused from K849/K851)
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
    """Process one TX1 file -> compute 5-min RV for day+night sessions."""
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

    t = df['time_int'].values
    p = df['price'].values

    # Session masks
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

    rv_day, _ = compute_rv_bpv(day_rets)
    rv_night, _ = compute_rv_bpv(night_rets)

    if not np.isnan(rv_day) and not np.isnan(rv_night):
        rv_total = rv_day + rv_night
    elif not np.isnan(rv_day):
        rv_total = rv_day
    else:
        rv_total = np.nan

    return {
        'date': date_str,
        'rv_total': rv_total if not np.isnan(rv_total) else None,
    }


def load_all_rv_data(start_date='2017_05_16'):
    """Load TX1 files from night session era and compute RV."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    all_files = sorted(glob.glob(pattern))

    cutoff = f"Daily_{start_date}"
    files = [f for f in all_files if os.path.basename(f) >= cutoff]
    files = [f for f in files if os.path.basename(f) < "Daily_2026"]
    print(f"  Found {len(files)} TX1 files from {start_date} to end 2025")

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
    df['rv_total'] = pd.to_numeric(df['rv_total'], errors='coerce')
    return df


# ============================================================
# Step 2: Load VIX data
# ============================================================

def load_vix_data(start_year=2016, end_year=2026):
    """Download VIX from yfinance and return as series."""
    import yfinance as yf
    vix = yf.download('^VIX', start=f'{start_year}-01-01', end=f'{end_year}-01-01', progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix['Close'].squeeze()
    vix_close.index = pd.to_datetime(vix_close.index).tz_localize(None)
    return vix_close


# ============================================================
# Step 3: HAR Feature Construction
# ============================================================

def build_har_features(log_rv, include_vix=False, vix_series=None):
    """
    Build HAR features from log RV series.
    Returns: feature matrix (n x k), target (n,), valid mask

    Features (all lagged, no lookahead):
      - log(RV_{t-1}): daily
      - log(RV_{t-5:t-1}): weekly average
      - log(RV_{t-22:t-1}): monthly average
      - optional: log(VIX_{t-1})

    Target: log(RV_t)
    """
    n = len(log_rv)
    rv_vals = log_rv.values
    dates = log_rv.index

    rv_d = np.full(n, np.nan)  # lag-1
    rv_w = np.full(n, np.nan)  # lag-1:5 average
    rv_m = np.full(n, np.nan)  # lag-1:22 average

    for i in range(1, n):
        rv_d[i] = rv_vals[i - 1]
    for i in range(5, n):
        rv_w[i] = np.mean(rv_vals[i - 5:i])
    for i in range(22, n):
        rv_m[i] = np.mean(rv_vals[i - 22:i])

    if include_vix and vix_series is not None:
        # Align VIX to RV dates (VIX from previous US trading day)
        # For Taiwan t, use VIX from t-1 (previous day close)
        vix_log = np.full(n, np.nan)
        for i in range(1, n):
            dt = dates[i - 1]
            # Find nearest VIX date <= dt
            mask = vix_series.index <= dt
            if mask.any():
                vix_val = vix_series.loc[mask].iloc[-1]
                if vix_val > 0:
                    vix_log[i] = np.log(vix_val)
        feat = np.column_stack([rv_d, rv_w, rv_m, vix_log])
    else:
        feat = np.column_stack([rv_d, rv_w, rv_m])

    valid = ~np.any(np.isnan(feat), axis=1) & ~np.isnan(rv_vals)

    return feat, rv_vals, valid, dates


# ============================================================
# Step 4: OLS HAR fitting
# ============================================================

def fit_har_ols(y, X):
    """OLS: y = [1, X] @ beta. Returns beta, y_hat, R²."""
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


def fit_har_ols_with_se(y, X):
    """OLS with Newey-West standard errors."""
    n = len(y)
    X_c = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_c, y, rcond=None)[0]
        y_hat = X_c @ beta
        resid = y - y_hat
        ss_res = np.sum(resid ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Newey-West HAC SE
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

        XtX_inv = np.linalg.inv(X_c.T @ X_c / n)
        V = XtX_inv @ S @ XtX_inv / n
        se = np.sqrt(np.diag(V))
        t_stats = beta / se

        return beta, y_hat, r2, se, t_stats
    except Exception:
        return None, None, None, None, None


# ============================================================
# Step 5: Regime-dependent in-sample analysis
# ============================================================

def regime_insample_analysis(log_rv, vix_aligned):
    """
    Fit separate HAR-RV models per VIX regime and analyze coefficient variation.
    """
    feat, target, valid, dates = build_har_features(log_rv)

    results = {}
    regime_labels = {
        'Low (VIX<15)': (0, VIX_LOW),
        'Medium (15<=VIX<25)': (VIX_LOW, VIX_HIGH),
        'High (VIX>=25)': (VIX_HIGH, 999),
    }

    coeff_names = ['const', 'rv_daily', 'rv_weekly', 'rv_monthly']

    # Full sample first
    valid_idx = np.where(valid)[0]
    y_full = target[valid_idx]
    X_full = feat[valid_idx]

    beta_f, _, r2_f, se_f, t_f = fit_har_ols_with_se(y_full, X_full)
    if beta_f is not None:
        results['Full Sample'] = {
            'n': len(y_full),
            'R2': round(float(r2_f), 4),
            'coefficients': {}
        }
        for i, name in enumerate(coeff_names):
            results['Full Sample']['coefficients'][name] = {
                'estimate': round(float(beta_f[i]), 6),
                'se': round(float(se_f[i]), 6),
                't_stat': round(float(t_f[i]), 3),
            }

    # Per-regime
    for regime_name, (vix_lo, vix_hi) in regime_labels.items():
        regime_mask = np.zeros(len(log_rv), dtype=bool)
        for i in range(len(log_rv)):
            dt = dates[i]
            # VIX at t-1 determines regime for predicting t
            if i > 0:
                dt_prev = dates[i - 1]
                mask_vix = vix_aligned.index <= dt_prev
                if mask_vix.any():
                    v = vix_aligned.loc[mask_vix].iloc[-1]
                    if vix_lo <= v < vix_hi:
                        regime_mask[i] = True

        regime_valid = valid & regime_mask
        valid_idx_r = np.where(regime_valid)[0]

        if len(valid_idx_r) < 50:
            results[regime_name] = {'n': len(valid_idx_r), 'R2': None, 'note': 'Too few obs'}
            continue

        y_r = target[valid_idx_r]
        X_r = feat[valid_idx_r]

        beta_r, _, r2_r, se_r, t_r = fit_har_ols_with_se(y_r, X_r)
        if beta_r is not None:
            results[regime_name] = {
                'n': len(y_r),
                'R2': round(float(r2_r), 4),
                'coefficients': {}
            }
            for i, name in enumerate(coeff_names):
                results[regime_name]['coefficients'][name] = {
                    'estimate': round(float(beta_r[i]), 6),
                    'se': round(float(se_r[i]), 6),
                    't_stat': round(float(t_r[i]), 3),
                }

    return results


# ============================================================
# Step 6: OOS forecasting models
# ============================================================

def har_oos_forecast(log_rv, oos_start_idx, model_type='HAR-RV',
                     vix_aligned=None, refit_freq=REFIT_FREQ, min_train=MIN_TRAIN):
    """
    Rolling OOS forecast for HAR models (works in log-RV space).

    model_type:
      'HAR-RV': standard HAR
      'HAR-RV-VIX': HAR + log(VIX)
      'Regime-HAR': separate coefficients per VIX regime

    Returns forecasts in LEVEL space (exp(log_forecast))
    """
    n = len(log_rv)
    rv_vals = log_rv.values
    dates = log_rv.index

    forecasts = np.full(n, np.nan)
    last_beta = None
    last_betas_regime = {r: None for r in ['low', 'med', 'high']}
    last_fit_idx = -refit_freq

    include_vix = model_type in ('HAR-RV-VIX', 'Regime-HAR')

    for t in range(oos_start_idx, n):
        # Refit periodically
        if t - last_fit_idx >= refit_freq or (model_type != 'Regime-HAR' and last_beta is None):
            train_rv = rv_vals[:t]
            if len(train_rv) < min_train:
                continue

            # Build training features
            feat_t, tgt_t, valid_t, _ = build_har_features(
                log_rv.iloc[:t],
                include_vix=(model_type == 'HAR-RV-VIX'),
                vix_series=vix_aligned
            )

            valid_idx = np.where(valid_t)[0]
            if len(valid_idx) < 50:
                continue

            if model_type == 'Regime-HAR':
                # Fit separate models per regime
                for regime_key, (vlo, vhi) in [('low', (0, VIX_LOW)),
                                                 ('med', (VIX_LOW, VIX_HIGH)),
                                                 ('high', (VIX_HIGH, 999))]:
                    regime_mask = np.zeros(t, dtype=bool)
                    for i in range(1, t):
                        dt_prev = dates[i - 1]
                        m = vix_aligned.index <= dt_prev
                        if m.any():
                            v = vix_aligned.loc[m].iloc[-1]
                            if vlo <= v < vhi:
                                regime_mask[i] = True

                    r_valid = valid_t & regime_mask
                    r_idx = np.where(r_valid)[0]
                    if len(r_idx) >= 30:
                        y_r = tgt_t[r_idx]
                        X_r = feat_t[r_idx, :3]  # Only HAR features (no VIX)
                        beta_r, _, _ = fit_har_ols(y_r, X_r)
                        if beta_r is not None:
                            last_betas_regime[regime_key] = beta_r

                last_fit_idx = t
            else:
                y_tr = tgt_t[valid_idx]
                X_tr = feat_t[valid_idx]
                beta, _, _ = fit_har_ols(y_tr, X_tr)
                if beta is not None:
                    last_beta = beta
                    last_fit_idx = t

        # Build features for time t
        if t < 22:
            continue

        rv_d_t = rv_vals[t - 1]
        rv_w_t = np.mean(rv_vals[max(0, t - 5):t])
        rv_m_t = np.mean(rv_vals[max(0, t - 22):t])

        if np.isnan(rv_d_t) or np.isnan(rv_w_t) or np.isnan(rv_m_t):
            continue

        if model_type == 'HAR-RV-VIX':
            if last_beta is None:
                continue
            # Get VIX at t-1
            dt_prev = dates[t - 1]
            m = vix_aligned.index <= dt_prev
            if not m.any():
                continue
            vix_val = vix_aligned.loc[m].iloc[-1]
            if vix_val <= 0:
                continue
            x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t, np.log(vix_val)])
            log_fc = x_t @ last_beta

        elif model_type == 'Regime-HAR':
            # Determine regime
            dt_prev = dates[t - 1]
            m = vix_aligned.index <= dt_prev
            if not m.any():
                continue
            vix_val = vix_aligned.loc[m].iloc[-1]

            if vix_val < VIX_LOW:
                beta_use = last_betas_regime['low']
            elif vix_val < VIX_HIGH:
                beta_use = last_betas_regime['med']
            else:
                beta_use = last_betas_regime['high']

            if beta_use is None:
                # Fallback to any available regime
                for rk in ['med', 'low', 'high']:
                    if last_betas_regime[rk] is not None:
                        beta_use = last_betas_regime[rk]
                        break
            if beta_use is None:
                continue

            x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t])
            log_fc = x_t @ beta_use

        else:  # HAR-RV
            if last_beta is None:
                continue
            x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t])
            log_fc = x_t @ last_beta

        # Convert from log-RV to RV level
        forecasts[t] = max(np.exp(log_fc), 1e-12)

    return pd.Series(forecasts, index=dates, name=model_type)


def st_har_oos_forecast(log_rv, oos_start_idx, vix_aligned,
                        refit_freq=REFIT_FREQ, min_train=MIN_TRAIN):
    """
    Smooth Transition HAR (ST-HAR) OOS forecast.

    log(RV_{t+1}) = (1-G(VIX_t))*[β_L' x_t] + G(VIX_t)*[β_H' x_t]
    G(VIX) = 1/(1+exp(-γ*(VIX-c)))

    Estimated via NLS (grid search on γ,c, then conditional OLS for β_L, β_H).
    """
    n = len(log_rv)
    rv_vals = log_rv.values
    dates = log_rv.index

    forecasts = np.full(n, np.nan)
    last_params = None
    last_fit_idx = -refit_freq

    def _get_vix_for_t(t_idx):
        """Get VIX value at time t-1 (lagged, no lookahead)."""
        if t_idx < 1:
            return np.nan
        dt_prev = dates[t_idx - 1]
        m = vix_aligned.index <= dt_prev
        if not m.any():
            return np.nan
        return float(vix_aligned.loc[m].iloc[-1])

    def _fit_st_har(rv_train, feat_train, vix_train, valid_mask):
        """
        Fit ST-HAR via grid search over (gamma, c).
        For each (gamma, c), compute G, then solve conditional OLS for beta_L, beta_H.
        """
        idx = np.where(valid_mask)[0]
        if len(idx) < 80:
            return None

        y = rv_train[idx]
        X = feat_train[idx, :3]  # daily, weekly, monthly (no VIX)
        vix_vals = vix_train[idx]

        # Remove any NaN VIX
        vix_valid = np.isfinite(vix_vals)
        y = y[vix_valid]
        X = X[vix_valid]
        vix_vals = vix_vals[vix_valid]

        if len(y) < 80:
            return None

        n_obs = len(y)
        X_with_const = np.column_stack([np.ones(n_obs), X])
        k = X_with_const.shape[1]

        best_sse = np.inf
        best_params = None

        # Grid search over gamma and c
        # gamma: controls steepness (0.1 = gradual, 2.0 = sharp)
        # c: threshold (percentiles of VIX)
        gamma_grid = [0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0]
        c_grid = np.percentile(vix_vals, [20, 30, 40, 50, 60, 70, 80])

        for gamma in gamma_grid:
            for c in c_grid:
                # Compute transition function
                G = 1.0 / (1.0 + np.exp(-gamma * (vix_vals - c)))

                # Build expanded design matrix: [(1-G)*X, G*X]
                X_low = X_with_const * (1 - G)[:, None]
                X_high = X_with_const * G[:, None]
                X_full = np.column_stack([X_low, X_high])

                # OLS
                try:
                    beta_full = np.linalg.lstsq(X_full, y, rcond=None)[0]
                    y_hat = X_full @ beta_full
                    sse = np.sum((y - y_hat) ** 2)

                    if sse < best_sse:
                        best_sse = sse
                        best_params = {
                            'gamma': gamma,
                            'c': c,
                            'beta_low': beta_full[:k].copy(),
                            'beta_high': beta_full[k:].copy(),
                            'sse': sse,
                            'r2': 1 - sse / np.sum((y - np.mean(y)) ** 2),
                        }
                except Exception:
                    continue

        return best_params

    for t in range(oos_start_idx, n):
        # Refit periodically
        if t - last_fit_idx >= refit_freq or last_params is None:
            if t < min_train:
                continue

            # Build features for training period
            feat_t, tgt_t, valid_t, _ = build_har_features(log_rv.iloc[:t])

            # Build VIX array aligned to training dates
            vix_train = np.full(t, np.nan)
            for i in range(1, t):
                vix_train[i] = _get_vix_for_t(i)

            valid_t = valid_t & np.isfinite(vix_train)

            params = _fit_st_har(tgt_t, feat_t, vix_train, valid_t)
            if params is not None:
                last_params = params
                last_fit_idx = t

        if last_params is None:
            continue

        # Build features for time t
        if t < 22:
            continue

        rv_d_t = rv_vals[t - 1]
        rv_w_t = np.mean(rv_vals[max(0, t - 5):t])
        rv_m_t = np.mean(rv_vals[max(0, t - 22):t])
        vix_t = _get_vix_for_t(t)

        if np.isnan(rv_d_t) or np.isnan(rv_w_t) or np.isnan(rv_m_t) or np.isnan(vix_t):
            continue

        x_t = np.array([1, rv_d_t, rv_w_t, rv_m_t])
        G_t = 1.0 / (1.0 + np.exp(-last_params['gamma'] * (vix_t - last_params['c'])))

        log_fc = (1 - G_t) * (x_t @ last_params['beta_low']) + G_t * (x_t @ last_params['beta_high'])
        forecasts[t] = max(np.exp(log_fc), 1e-12)

    return pd.Series(forecasts, index=dates, name='ST-HAR')


# ============================================================
# Step 7: Metrics and DM test (from K849)
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
# Step 8: Regime-specific OOS evaluation
# ============================================================

def regime_oos_evaluation(rv_series, model_forecasts, vix_aligned, oos_dates):
    """
    Compute metrics per VIX regime in OOS period.
    """
    regime_labels = {
        'Low (VIX<15)': (0, VIX_LOW),
        'Medium (15<=VIX<25)': (VIX_LOW, VIX_HIGH),
        'High (VIX>=25)': (VIX_HIGH, 999),
    }

    results = {}

    for regime_name, (vlo, vhi) in regime_labels.items():
        # Find OOS dates in this regime
        regime_dates = []
        for dt in oos_dates:
            m = vix_aligned.index <= dt
            if m.any():
                v = vix_aligned.loc[m].iloc[-1]
                if vlo <= v < vhi:
                    regime_dates.append(dt)

        if len(regime_dates) < 20:
            results[regime_name] = {'n': len(regime_dates), 'note': 'Too few obs'}
            continue

        regime_dates = pd.DatetimeIndex(regime_dates)
        target = rv_series.loc[regime_dates].values

        regime_res = {'n': len(regime_dates)}
        for mn, fc in model_forecasts.items():
            fc_vals = fc.loc[regime_dates].values
            q = qlike(target, fc_vals)
            rho, _ = spearman_corr(target, fc_vals)
            regime_res[f'{mn}_QLIKE'] = round(q, 6) if not np.isnan(q) else None
            regime_res[f'{mn}_Spearman'] = round(rho, 4) if not np.isnan(rho) else None

        results[regime_name] = regime_res

    return results


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K852b: Regime-Dependent HAR Model Coefficients for Taiwan Futures")
    print("=" * 70)
    start_time = datetime.now()

    # ------------------------------------------------------------------
    # Part 1: Load data
    # ------------------------------------------------------------------
    print("\n[1] Loading TAIFEX TX1 tick data and computing 5-min RV...")
    rv_df = load_all_rv_data(start_date='2017_05_16')
    rv_df = rv_df.dropna(subset=['rv_total'])
    print(f"  Total trading days: {len(rv_df)}")
    print(f"  Date range: {rv_df.index.min().date()} to {rv_df.index.max().date()}")

    # Descriptive statistics
    rv_vals = rv_df['rv_total'].values
    rv_ann_vol = np.sqrt(rv_vals * 252) * 100
    print(f"  RV: mean={np.mean(rv_vals):.2e}, median={np.median(rv_vals):.2e}")
    print(f"  Ann vol: mean={np.mean(rv_ann_vol):.1f}%, median={np.median(rv_ann_vol):.1f}%")

    # Log transform
    log_rv = np.log(rv_df['rv_total'].clip(lower=1e-12))
    log_rv.name = 'log_rv'
    print(f"  log(RV): mean={log_rv.mean():.3f}, std={log_rv.std():.3f}")

    # ------------------------------------------------------------------
    # Part 2: Load VIX
    # ------------------------------------------------------------------
    print("\n[2] Loading VIX data...")
    vix_series = load_vix_data(start_year=2016, end_year=2026)
    print(f"  VIX: {len(vix_series)} obs, {vix_series.index[0].date()} to {vix_series.index[-1].date()}")
    print(f"  VIX: mean={vix_series.mean():.1f}, median={vix_series.median():.1f}")

    # Align VIX to TAIFEX dates
    common_start = max(rv_df.index.min(), vix_series.index.min())
    common_end = min(rv_df.index.max(), vix_series.index.max())
    log_rv = log_rv.loc[common_start:common_end]
    rv_df = rv_df.loc[common_start:common_end]
    print(f"  Common period: {common_start.date()} to {common_end.date()}, {len(log_rv)} days")

    # VIX regime distribution
    vix_for_dates = []
    for dt in rv_df.index:
        m = vix_series.index <= dt
        if m.any():
            vix_for_dates.append(float(vix_series.loc[m].iloc[-1]))
        else:
            vix_for_dates.append(np.nan)
    vix_aligned_arr = np.array(vix_for_dates)

    n_low = np.sum(vix_aligned_arr < VIX_LOW)
    n_med = np.sum((vix_aligned_arr >= VIX_LOW) & (vix_aligned_arr < VIX_HIGH))
    n_high = np.sum(vix_aligned_arr >= VIX_HIGH)
    n_total = len(vix_aligned_arr)
    print(f"\n  VIX Regime Distribution:")
    print(f"    Low (VIX<15):    {n_low} days ({100*n_low/n_total:.1f}%)")
    print(f"    Medium (15-25):  {n_med} days ({100*n_med/n_total:.1f}%)")
    print(f"    High (VIX>=25):  {n_high} days ({100*n_high/n_total:.1f}%)")

    # ------------------------------------------------------------------
    # Part 3: In-sample regime analysis
    # ------------------------------------------------------------------
    print("\n[3] In-sample HAR coefficient analysis by VIX regime...")
    regime_is = regime_insample_analysis(log_rv, vix_series)

    print("\n  HAR-RV Coefficients by VIX Regime:")
    print(f"  {'Regime':<25s} {'N':>6s} {'R²':>7s} {'β_day':>10s} {'β_week':>10s} {'β_month':>10s}")
    print("  " + "-" * 70)
    for rname, rdata in regime_is.items():
        if rdata.get('R2') is not None:
            c = rdata['coefficients']
            print(f"  {rname:<25s} {rdata['n']:>6d} {rdata['R2']:>7.4f} "
                  f"{c['rv_daily']['estimate']:>10.4f} "
                  f"{c['rv_weekly']['estimate']:>10.4f} "
                  f"{c['rv_monthly']['estimate']:>10.4f}")
        else:
            print(f"  {rname:<25s} {rdata.get('n', 0):>6d}   {'N/A':>5s}   {rdata.get('note', '')}")

    # T-stat table
    print("\n  T-statistics (Newey-West HAC):")
    print(f"  {'Regime':<25s} {'t(const)':>10s} {'t(day)':>10s} {'t(week)':>10s} {'t(month)':>10s}")
    print("  " + "-" * 70)
    for rname, rdata in regime_is.items():
        if rdata.get('R2') is not None:
            c = rdata['coefficients']
            print(f"  {rname:<25s} "
                  f"{c['const']['t_stat']:>10.2f} "
                  f"{c['rv_daily']['t_stat']:>10.2f} "
                  f"{c['rv_weekly']['t_stat']:>10.2f} "
                  f"{c['rv_monthly']['t_stat']:>10.2f}")

    # Coefficient variation analysis
    print("\n  Coefficient Variation Across Regimes:")
    regime_coeffs = {}
    for rname, rdata in regime_is.items():
        if rdata.get('R2') is not None and rname != 'Full Sample':
            regime_coeffs[rname] = rdata['coefficients']

    if len(regime_coeffs) >= 2:
        for coeff_name in ['rv_daily', 'rv_weekly', 'rv_monthly']:
            vals = [rc[coeff_name]['estimate'] for rc in regime_coeffs.values()]
            print(f"    {coeff_name}: range={max(vals)-min(vals):.4f}, "
                  f"min={min(vals):.4f}, max={max(vals):.4f}")

    # ------------------------------------------------------------------
    # Part 4: OOS Forecasts
    # ------------------------------------------------------------------
    n_total = len(log_rv)
    oos_start_idx = int(n_total * (1 - OOS_RATIO))
    oos_start_date = log_rv.index[oos_start_idx]
    print(f"\n[4] OOS Forecasts (start: {oos_start_date.date()}, {n_total - oos_start_idx} obs)")

    # Model 1: HAR-RV (baseline)
    print("  [4a] HAR-RV (baseline)...")
    fc_har = har_oos_forecast(log_rv, oos_start_idx, 'HAR-RV')
    n_fc = fc_har.dropna().shape[0]
    print(f"    HAR-RV: {n_fc} OOS forecasts")

    # Model 2: HAR-RV-VIX
    print("  [4b] HAR-RV-VIX...")
    fc_har_vix = har_oos_forecast(log_rv, oos_start_idx, 'HAR-RV-VIX', vix_aligned=vix_series)
    n_fc = fc_har_vix.dropna().shape[0]
    print(f"    HAR-RV-VIX: {n_fc} OOS forecasts")

    # Model 3: Regime-HAR
    print("  [4c] Regime-HAR...")
    fc_regime = har_oos_forecast(log_rv, oos_start_idx, 'Regime-HAR', vix_aligned=vix_series)
    n_fc = fc_regime.dropna().shape[0]
    print(f"    Regime-HAR: {n_fc} OOS forecasts")

    # Model 4: ST-HAR
    print("  [4d] ST-HAR (smooth transition)...")
    fc_st = st_har_oos_forecast(log_rv, oos_start_idx, vix_series)
    n_fc = fc_st.dropna().shape[0]
    print(f"    ST-HAR: {n_fc} OOS forecasts")

    # ------------------------------------------------------------------
    # Part 5: Evaluation
    # ------------------------------------------------------------------
    print("\n[5] OOS Evaluation")

    rv_level = rv_df['rv_total']
    model_forecasts = {
        'HAR-RV': fc_har,
        'HAR-RV-VIX': fc_har_vix,
        'Regime-HAR': fc_regime,
        'ST-HAR': fc_st,
    }

    # Find common valid OOS dates
    oos_all = log_rv.index[oos_start_idx:]
    common = oos_all
    for mn, fc in model_forecasts.items():
        valid = fc.dropna().index
        common = common.intersection(valid)
    common = common.intersection(rv_level.dropna().index)
    common = common.sort_values()

    print(f"  Common OOS dates: {len(common)}")
    if len(common) < 30:
        print("  ERROR: Too few common dates!")
        return

    target = rv_level.loc[common].values

    # Full OOS metrics
    print(f"\n  Full OOS Metrics ({common[0].date()} to {common[-1].date()}):")
    print(f"  {'Model':<15s} {'QLIKE':>10s} {'MSE':>12s} {'MAE':>12s} {'Spearman':>10s}")
    print("  " + "-" * 60)

    oos_results = {}
    loss_series = {}

    for mn, fc in model_forecasts.items():
        fc_vals = fc.loc[common].values
        q = qlike(target, fc_vals)
        m = mse_metric(target, fc_vals)
        ma = mae_metric(target, fc_vals)
        rho, p = spearman_corr(target, fc_vals)

        oos_results[mn] = {
            'QLIKE': round(q, 6) if not np.isnan(q) else None,
            'MSE': float(f"{m:.4e}") if not np.isnan(m) else None,
            'MAE': float(f"{ma:.4e}") if not np.isnan(ma) else None,
            'Spearman': round(rho, 4) if not np.isnan(rho) else None,
            'n_oos': len(common),
        }
        loss_series[mn] = qlike_loss_series(target, fc_vals)

        print(f"  {mn:<15s} {q:>10.6f} {m:>12.2e} {ma:>12.2e} {rho:>10.4f}")

    # ------------------------------------------------------------------
    # Part 6: DM Tests
    # ------------------------------------------------------------------
    print(f"\n[6] DM Tests (QLIKE loss, Harvey |t|>3.0):")
    print(f"  {'Pair':<30s} {'t-stat':>10s} {'p-value':>10s} {'Winner':>15s} {'Sig':>5s}")
    print("  " + "-" * 75)

    dm_results = {}
    model_names = list(model_forecasts.keys())
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            t_stat, p_val = dm_test(loss_series[m1], loss_series[m2])
            key = f"{m1} vs {m2}"
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.645 else ""))
            winner = m1 if t_stat < 0 else m2
            dm_results[key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'winner': winner,
                'significant_harvey': abs(t_stat) > 3.0,
            }
            print(f"  {key:<30s} {t_stat:>10.3f} {p_val:>10.4f} {winner:>15s} {sig:>5s}")

    # ------------------------------------------------------------------
    # Part 7: Regime-specific OOS evaluation
    # ------------------------------------------------------------------
    print(f"\n[7] Regime-Specific OOS Performance:")
    regime_oos = regime_oos_evaluation(rv_level, model_forecasts, vix_series, common)

    for regime_name, rdata in regime_oos.items():
        print(f"\n  {regime_name} (n={rdata.get('n', 0)}):")
        if rdata.get('note'):
            print(f"    {rdata['note']}")
            continue
        for mn in model_names:
            q = rdata.get(f'{mn}_QLIKE', None)
            rho = rdata.get(f'{mn}_Spearman', None)
            if q is not None:
                print(f"    {mn:<15s}: QLIKE={q:.6f}, Spearman={rho:.4f}" if rho else f"    {mn:<15s}: QLIKE={q:.6f}")

    # Regime DM tests (HAR-RV vs each alternative, per regime)
    print(f"\n  Regime DM Tests (HAR-RV vs alternatives):")
    regime_dm = {}
    for regime_name, rdata in regime_oos.items():
        if rdata.get('note'):
            continue

        # Get regime dates
        regime_dates = []
        for dt in common:
            m = vix_series.index <= dt
            if m.any():
                v = vix_series.loc[m].iloc[-1]
                rg_map = {
                    'Low (VIX<15)': (0, VIX_LOW),
                    'Medium (15<=VIX<25)': (VIX_LOW, VIX_HIGH),
                    'High (VIX>=25)': (VIX_HIGH, 999),
                }
                vlo, vhi = rg_map.get(regime_name, (0, 999))
                if vlo <= v < vhi:
                    regime_dates.append(dt)

        if len(regime_dates) < 30:
            continue

        regime_dates = pd.DatetimeIndex(regime_dates)
        tgt_r = rv_level.loc[regime_dates].values
        loss_har_r = qlike_loss_series(tgt_r, fc_har.loc[regime_dates].values)

        regime_dm[regime_name] = {}
        for mn in ['HAR-RV-VIX', 'Regime-HAR', 'ST-HAR']:
            fc_r = model_forecasts[mn].loc[regime_dates].values
            loss_alt_r = qlike_loss_series(tgt_r, fc_r)
            t_s, p_v = dm_test(loss_har_r, loss_alt_r)
            sig = "***" if abs(t_s) > 3.0 else ("**" if abs(t_s) > 2.0 else "")
            winner = 'HAR-RV' if t_s < 0 else mn
            regime_dm[regime_name][f'HAR-RV vs {mn}'] = {
                't_stat': round(t_s, 3), 'p_value': round(p_v, 4),
                'winner': winner, 'sig_harvey': abs(t_s) > 3.0
            }
            print(f"    {regime_name}: HAR-RV vs {mn}: t={t_s:.3f} p={p_v:.4f} -> {winner} {sig}")

    # ------------------------------------------------------------------
    # Part 8: ST-HAR parameter analysis
    # ------------------------------------------------------------------
    print(f"\n[8] ST-HAR Parameter Analysis:")
    # Refit on full sample for interpretation
    feat_full, tgt_full, valid_full, dates_full = build_har_features(log_rv)
    vix_full = np.full(len(log_rv), np.nan)
    for i in range(1, len(log_rv)):
        dt_prev = log_rv.index[i - 1]
        m = vix_series.index <= dt_prev
        if m.any():
            vix_full[i] = float(vix_series.loc[m].iloc[-1])

    valid_full = valid_full & np.isfinite(vix_full)
    idx_valid = np.where(valid_full)[0]

    if len(idx_valid) >= 80:
        y_all = tgt_full[idx_valid]
        X_all = feat_full[idx_valid, :3]
        vix_all = vix_full[idx_valid]
        n_all = len(y_all)
        X_with_const = np.column_stack([np.ones(n_all), X_all])
        k = X_with_const.shape[1]

        best_sse = np.inf
        best_st_params = None
        gamma_grid = [0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0]
        c_grid = np.percentile(vix_all, [15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85])

        for gamma in gamma_grid:
            for c in c_grid:
                G = 1.0 / (1.0 + np.exp(-gamma * (vix_all - c)))
                X_low = X_with_const * (1 - G)[:, None]
                X_high = X_with_const * G[:, None]
                X_full_st = np.column_stack([X_low, X_high])
                try:
                    beta_full = np.linalg.lstsq(X_full_st, y_all, rcond=None)[0]
                    y_hat = X_full_st @ beta_full
                    sse = np.sum((y_all - y_hat) ** 2)
                    if sse < best_sse:
                        best_sse = sse
                        best_st_params = {
                            'gamma': gamma, 'c': c,
                            'beta_low': beta_full[:k].tolist(),
                            'beta_high': beta_full[k:].tolist(),
                            'r2': 1 - sse / np.sum((y_all - np.mean(y_all)) ** 2),
                        }
                except Exception:
                    continue

        if best_st_params:
            print(f"  Best γ = {best_st_params['gamma']:.2f}, c = {best_st_params['c']:.1f}")
            print(f"  IS R² = {best_st_params['r2']:.4f}")
            coeff_names = ['const', 'rv_daily', 'rv_weekly', 'rv_monthly']
            print(f"\n  {'Coefficient':<15s} {'Low-VIX β':>12s} {'High-VIX β':>12s} {'Difference':>12s}")
            print("  " + "-" * 55)
            st_coeff_details = {}
            for i, name in enumerate(coeff_names):
                bl = best_st_params['beta_low'][i]
                bh = best_st_params['beta_high'][i]
                diff = bh - bl
                st_coeff_details[name] = {
                    'low': round(bl, 6), 'high': round(bh, 6), 'diff': round(diff, 6)
                }
                print(f"  {name:<15s} {bl:>12.4f} {bh:>12.4f} {diff:>12.4f}")
    else:
        best_st_params = None
        st_coeff_details = None

    # ------------------------------------------------------------------
    # Part 9: Summary
    # ------------------------------------------------------------------
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")

    # Best model
    qlikes = {mn: r['QLIKE'] for mn, r in oos_results.items() if r['QLIKE'] is not None}
    best_model = min(qlikes, key=qlikes.get)
    print(f"  Best OOS model (QLIKE): {best_model} ({qlikes[best_model]:.6f})")

    # Check if any alternative beats HAR-RV at Harvey threshold
    har_qlike = qlikes.get('HAR-RV', np.inf)
    improvements = {}
    for mn in ['HAR-RV-VIX', 'Regime-HAR', 'ST-HAR']:
        if mn in qlikes:
            pct_change = (qlikes[mn] - har_qlike) / har_qlike * 100
            improvements[mn] = pct_change
            print(f"  {mn} vs HAR-RV: {pct_change:+.2f}% QLIKE change")

    # Key findings
    any_significant = any(v['significant_harvey'] for v in dm_results.values())
    print(f"\n  Any DM significant at Harvey |t|>3.0: {any_significant}")

    if regime_is.get('Full Sample', {}).get('R2') and regime_is.get('High (VIX>=25)', {}).get('R2'):
        r2_full = regime_is['Full Sample']['R2']
        r2_high = regime_is['High (VIX>=25)']['R2']
        print(f"  IS R² (full vs high-VIX): {r2_full:.4f} vs {r2_high:.4f}")

    print(f"\n  Elapsed: {elapsed:.0f}s")

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------
    results = {
        'experiment_id': 'K852b',
        'title': 'Regime-Dependent HAR Model Coefficients for Taiwan Futures',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'data_source': 'TAIFEX TX1 tick data (5-min RV) + CBOE VIX via yfinance',
        'data_period': f"{rv_df.index.min().date()} to {rv_df.index.max().date()}",
        'n_trading_days': len(rv_df),
        'oos_start': str(oos_start_date.date()),
        'n_oos': len(common),
        'vix_regime_distribution': {
            'Low (VIX<15)': {'n': int(n_low), 'pct': round(100*n_low/n_total, 1)},
            'Medium (15-25)': {'n': int(n_med), 'pct': round(100*n_med/n_total, 1)},
            'High (VIX>=25)': {'n': int(n_high), 'pct': round(100*n_high/n_total, 1)},
        },
        'insample_regime_analysis': regime_is,
        'oos_metrics': oos_results,
        'dm_tests': dm_results,
        'regime_oos_performance': regime_oos,
        'regime_dm_tests': regime_dm,
        'st_har_params': best_st_params,
        'st_har_coefficient_details': st_coeff_details,
        'conclusions': {
            'best_model': best_model,
            'best_qlike': qlikes[best_model],
            'any_dm_significant_harvey': any_significant,
            'qlike_improvements_vs_har': improvements,
        },
        'elapsed_seconds': round(elapsed, 1),
        'references': [
            'Corsi (2009) JFE: HAR-RV model',
            'Patton (2011): QLIKE proxy-robust loss',
            'Hansen & Lunde (2005): 5-min RV as gold standard',
            'Terasvirta (1994): Smooth transition models',
            'Gonzalez-Rivera, Lee, Mishra (2004): Threshold HAR',
            'Patton & Sheppard (2015) RFS: Good vol, bad vol',
        ],
    }

    results_path = os.path.join(SCRIPT_DIR, 'k852b_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {results_path}")

    return results


if __name__ == '__main__':
    main()
