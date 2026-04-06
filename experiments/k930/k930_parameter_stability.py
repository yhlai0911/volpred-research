#!/usr/bin/env python3
"""
K930: MF-GJR Parameter Stability Over Time
============================================
[提出: Claude, 執行: Claude]

Analyzes whether MF-GJR model parameters are temporally stable across
rolling estimation windows. K889v2 confirmed MF-GJR(VIX) beats GJR for
SPY/QQQ, but parameter stability has not been examined.

Key Questions:
  1. Are theta_1 (VIX elasticity) and other parameters stable over time?
  2. Is there a structural break around COVID-19?
  3. Do parameters differ systematically across assets?
  4. Is there a parameter-performance relationship?

Method:
  - Rolling window (w=2000, step=63) estimation of MF-GJR and GJR
  - Same architecture as K889v2 (bug-fixed)
  - Stability tests: CV, ADF, Chow, CUSUM
  - Parameter-performance correlation analysis

Data:
  - Assets: SPY, QQQ, 0050.TW
  - Period: 2005-01-01 to 2026-04-01
  - VIX from yfinance (^VIX)
  - 0050.TW: clean_tw50_data (mandatory)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104

Author: VolPred Research System
Date: 2026-04-06
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K930"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import qlike

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k930_parameter_stability_results.json')

# Data parameters (same as K889v2 for comparability)
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
WINDOW = 2000
REFIT_EVERY = 63
ASSETS = ['SPY', 'QQQ', '0050.TW']

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR Parameter Stability Over Time")
print("  Rolling window estimation, stability tests, cross-asset comparison")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf


def load_asset_data(ticker, vix_data):
    """Load asset data with VIX alignment (same as K889v2)."""
    print(f"  Loading {ticker}...")
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    if '0050' in ticker:
        prices, log_ret = clean_tw50_data(prices, log_ret)

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
    df = df.dropna(subset=['log_ret'])
    df = df.join(vix_data, how='left')
    df['VIX'] = df['VIX'].ffill()
    df = df.dropna()

    return df


# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

asset_data = {}
for ticker in ASSETS:
    asset_data[ticker] = load_asset_data(ticker, vix_data)
    d = asset_data[ticker]
    print(f"    {ticker}: {d.index[0].strftime('%Y-%m-%d')} to "
          f"{d.index[-1].strftime('%Y-%m-%d')}, n={len(d)}")


# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS (from K889v2)
# ============================================================
print("\n[2] Model implementations...")


def gjr_garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    ll = 0.0

    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])

    return -ll


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-6, 0.05, 0.05, 0.90],
        [1e-6, 0.08, 0.10, 0.85],
        [1e-5, 0.03, 0.03, 0.93],
        [5e-6, 0.06, 0.08, 0.88],
    ]
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: gjr_garch_loglik(p, returns),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, -best_ll


def fit_mf_garch(returns, log_vix, model_type='garch'):
    """Fit MF-GARCH or MF-GJR (same as K889v2).

    Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
    Short-run: g_t = GARCH(1,1) or GJR-GARCH(1,1) on u_t = r_t/sqrt(tau_t)
    """
    n = len(returns)
    assert len(log_vix) == n

    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    X_ols = np.column_stack([np.ones(n), log_vix_lag])
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    def neg_loglik(params):
        if model_type == 'gjr':
            theta0, theta1, alpha, gamma, beta = params
        else:
            theta0, theta1, alpha, beta = params
            gamma = 0.0

        log_tau = theta0 + theta1 * log_vix_lag
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)
        u = returns / np.sqrt(tau)

        omega_g = 1.0 - alpha - gamma / 2.0 - beta
        if omega_g <= 0 or alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        g = np.empty(n)
        g[0] = 1.0
        for t in range(1, n):
            asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
            g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)

        if not np.isfinite(ll):
            return 1e10
        return -ll

    best_ll = np.inf
    best_params = None

    if model_type == 'gjr':
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.10, 0.85],
            [-8.0, 0.5, 0.05, 0.05, 0.90],
            [-7.0, 0.8, 0.03, 0.03, 0.93],
        ]
        bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]
    else:
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.85],
            [-8.0, 0.5, 0.05, 0.90],
            [-7.0, 0.8, 0.03, 0.93],
        ]
        bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 1000}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None, None

    return best_params, -best_ll


def forecast_mf_garch_insample(params, returns, log_vix, model_type='garch'):
    """Generate in-sample sigma^2 from MF-GARCH/MF-GJR model."""
    n = len(returns)
    if model_type == 'gjr':
        theta0, theta1, alpha, gamma, beta = params
    else:
        theta0, theta1, alpha, beta = params
        gamma = 0.0

    omega_g = 1.0 - alpha - gamma / 2.0 - beta
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]
    log_tau = theta0 + theta1 * log_vix_lag
    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)
    u = returns / np.sqrt(tau)

    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return sigma2, g, tau


# ============================================================
# SECTION 3: ROLLING PARAMETER EXTRACTION
# ============================================================
print("\n[3] Rolling parameter extraction...")


def extract_rolling_parameters(ticker, df):
    """Extract MF-GJR and GJR parameters at each rolling window position."""
    ret = df['log_ret'].values
    log_vix_raw = np.log(df['VIX'].values)
    r2 = ret ** 2
    dates = df.index

    # Determine all refit points (every REFIT_EVERY from WINDOW onwards)
    refit_indices = list(range(WINDOW, len(ret), REFIT_EVERY))
    n_refits = len(refit_indices)
    print(f"  {ticker}: {n_refits} refit points from index {WINDOW} to {len(ret)}")

    # Storage for parameters
    mfgjr_params_list = []
    gjr_params_list = []
    refit_dates = []
    convergence_flags = []

    # Also compute rolling 63-day QLIKE for performance correlation
    rolling_qlike_gjr = []
    rolling_qlike_mfgjr = []

    for i, idx in enumerate(refit_indices):
        train_start = max(0, idx - WINDOW)
        train_ret = ret[train_start:idx]
        train_vix = log_vix_raw[train_start:idx]
        refit_date = dates[idx]
        refit_dates.append(refit_date)

        # Fit GJR-GARCH
        gjr_params, gjr_ll = fit_gjr_garch(train_ret)
        if gjr_params is not None:
            omega_gjr, alpha_gjr, gamma_gjr, beta_gjr = gjr_params
            persistence_gjr = alpha_gjr + gamma_gjr / 2.0 + beta_gjr
            gjr_params_list.append({
                'date': refit_date.strftime('%Y-%m-%d'),
                'omega': float(omega_gjr),
                'alpha': float(alpha_gjr),
                'gamma': float(gamma_gjr),
                'beta': float(beta_gjr),
                'persistence': float(persistence_gjr),
                'loglik': float(gjr_ll),
            })
        else:
            gjr_params_list.append(None)

        # Fit MF-GJR
        mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_vix, model_type='gjr')
        converged = mfgjr_params is not None
        convergence_flags.append(converged)

        if converged:
            theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
            persistence_g = alpha_mf + gamma_mf / 2.0 + beta_mf
            mfgjr_params_list.append({
                'date': refit_date.strftime('%Y-%m-%d'),
                'theta_0': float(theta0),
                'theta_1': float(theta1),
                'alpha': float(alpha_mf),
                'gamma': float(gamma_mf),
                'beta': float(beta_mf),
                'persistence_g': float(persistence_g),
                'loglik': float(mfgjr_ll),
            })
        else:
            mfgjr_params_list.append(None)

        # Compute rolling QLIKE over the next 63 days (if available)
        oos_end = min(idx + REFIT_EVERY, len(ret))
        if oos_end > idx and gjr_params is not None and mfgjr_params is not None:
            oos_ret = ret[idx:oos_end]
            oos_r2 = r2[idx:oos_end]
            oos_vix = log_vix_raw[idx:oos_end]

            # GJR forecast for this period
            h_arr = np.empty(len(train_ret))
            h_arr[0] = np.var(train_ret)
            for tt in range(1, len(train_ret)):
                o, a, g, b = gjr_params
                asym = g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                h_arr[tt] = o + a * train_ret[tt-1]**2 + asym + b * h_arr[tt-1]
                h_arr[tt] = max(h_arr[tt], 1e-10)

            gjr_h = h_arr[-1]
            gjr_forecasts = np.empty(len(oos_ret))
            for tt in range(len(oos_ret)):
                r_prev = ret[idx + tt - 1] if (idx + tt - 1) >= 0 else train_ret[-1]
                asym = gjr_params[2] * r_prev**2 if r_prev < 0 else 0.0
                gjr_h = gjr_params[0] + gjr_params[1] * r_prev**2 + asym + gjr_params[3] * gjr_h
                gjr_h = max(gjr_h, 1e-10)
                gjr_forecasts[tt] = gjr_h

            # MF-GJR forecast for this period
            _, g_arr, tau_arr = forecast_mf_garch_insample(
                mfgjr_params, train_ret, train_vix, 'gjr')
            last_g = g_arr[-1]
            last_tau = tau_arr[-1]

            mfgjr_forecasts = np.empty(len(oos_ret))
            theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
            omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf

            for tt in range(len(oos_ret)):
                # tau from VIX
                vix_idx = idx + tt - 1
                if vix_idx >= 0:
                    log_tau_t = theta0 + theta1 * log_vix_raw[vix_idx]
                else:
                    log_tau_t = theta0 + theta1 * train_vix[-1]
                tau_t = np.exp(log_tau_t)
                tau_t = max(tau_t, 1e-16)

                # g update
                if tt == 0:
                    u_last = train_ret[-1] / np.sqrt(last_tau)
                    asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
                    g_t = omega_g + alpha_mf * u_last**2 + asym + beta_mf * last_g
                else:
                    prev_vix_idx = idx + tt - 2
                    if prev_vix_idx >= 0:
                        prev_log_tau = theta0 + theta1 * log_vix_raw[prev_vix_idx]
                    else:
                        prev_log_tau = theta0 + theta1 * train_vix[-1]
                    prev_tau = np.exp(prev_log_tau)
                    prev_tau = max(prev_tau, 1e-16)
                    u_prev = ret[idx + tt - 1] / np.sqrt(prev_tau)
                    asym = gamma_mf * u_prev**2 if u_prev < 0 else 0.0
                    g_t = omega_g + alpha_mf * u_prev**2 + asym + beta_mf * last_g

                g_t = max(g_t, 1e-10)
                last_g = g_t
                last_tau = tau_t
                mfgjr_forecasts[tt] = tau_t * g_t

            # Compute QLIKE
            valid_gjr = np.isfinite(gjr_forecasts) & (gjr_forecasts > 0)
            valid_mf = np.isfinite(mfgjr_forecasts) & (mfgjr_forecasts > 0)
            if valid_gjr.sum() > 10 and valid_mf.sum() > 10:
                q_gjr = qlike(oos_r2[valid_gjr], gjr_forecasts[valid_gjr])
                q_mfgjr = qlike(oos_r2[valid_mf], mfgjr_forecasts[valid_mf])
                rolling_qlike_gjr.append(float(q_gjr))
                rolling_qlike_mfgjr.append(float(q_mfgjr))
            else:
                rolling_qlike_gjr.append(np.nan)
                rolling_qlike_mfgjr.append(np.nan)
        else:
            rolling_qlike_gjr.append(np.nan)
            rolling_qlike_mfgjr.append(np.nan)

        if (i + 1) % 10 == 0:
            print(f"    Refit {i+1}/{n_refits} done")

    print(f"    Convergence rate: {sum(convergence_flags)}/{n_refits} "
          f"({100*sum(convergence_flags)/max(n_refits,1):.1f}%)")

    return {
        'refit_dates': refit_dates,
        'mfgjr_params': mfgjr_params_list,
        'gjr_params': gjr_params_list,
        'convergence_flags': convergence_flags,
        'rolling_qlike_gjr': rolling_qlike_gjr,
        'rolling_qlike_mfgjr': rolling_qlike_mfgjr,
        'n_refits': n_refits,
    }


# Run for all assets
all_results = {}
for ticker in ASSETS:
    print(f"\n  === {ticker} ===")
    all_results[ticker] = extract_rolling_parameters(ticker, asset_data[ticker])


# ============================================================
# SECTION 4: STABILITY ANALYSIS
# ============================================================
print("\n[4] Stability analysis...")


def analyze_parameter_stability(ticker, result):
    """Compute stability metrics for parameter series."""
    mfgjr_params = result['mfgjr_params']
    gjr_params = result['gjr_params']

    # Extract valid MF-GJR parameter series
    valid_mf = [p for p in mfgjr_params if p is not None]
    if len(valid_mf) < 5:
        print(f"  {ticker}: Too few valid MF-GJR fits ({len(valid_mf)}), skipping")
        return None

    mf_dates = [p['date'] for p in valid_mf]
    theta0_series = np.array([p['theta_0'] for p in valid_mf])
    theta1_series = np.array([p['theta_1'] for p in valid_mf])
    alpha_series = np.array([p['alpha'] for p in valid_mf])
    gamma_series = np.array([p['gamma'] for p in valid_mf])
    beta_series = np.array([p['beta'] for p in valid_mf])
    persistence_series = np.array([p['persistence_g'] for p in valid_mf])

    # Extract valid GJR parameter series
    valid_gjr = [p for p in gjr_params if p is not None]
    gjr_alpha_series = np.array([p['alpha'] for p in valid_gjr])
    gjr_gamma_series = np.array([p['gamma'] for p in valid_gjr])
    gjr_beta_series = np.array([p['beta'] for p in valid_gjr])
    gjr_persistence_series = np.array([p['persistence'] for p in valid_gjr])

    param_names = ['theta_0', 'theta_1', 'alpha', 'gamma', 'beta', 'persistence_g']
    param_series = [theta0_series, theta1_series, alpha_series,
                    gamma_series, beta_series, persistence_series]

    stability = {}
    for name, series in zip(param_names, param_series):
        mean_val = float(np.mean(series))
        std_val = float(np.std(series))
        cv = float(std_val / abs(mean_val)) if abs(mean_val) > 1e-10 else np.nan
        min_val = float(np.min(series))
        max_val = float(np.max(series))
        range_val = max_val - min_val

        # ADF test on parameter series (is it stationary?)
        if len(series) >= 10:
            from statsmodels.tsa.stattools import adfuller
            try:
                adf_result = adfuller(series, maxlag=4, autolag=None)
                adf_stat = float(adf_result[0])
                adf_p = float(adf_result[1])
            except Exception:
                adf_stat = np.nan
                adf_p = np.nan
        else:
            adf_stat = np.nan
            adf_p = np.nan

        # Trend test: simple linear regression on index
        x_idx = np.arange(len(series))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x_idx, series)

        stability[name] = {
            'mean': mean_val,
            'std': std_val,
            'cv': cv,
            'min': min_val,
            'max': max_val,
            'range': range_val,
            'adf_stat': adf_stat,
            'adf_p': adf_p,
            'adf_stationary': bool(adf_p < 0.05) if np.isfinite(adf_p) else None,
            'trend_slope': float(slope),
            'trend_p': float(p_value),
            'trend_significant': bool(p_value < 0.05),
            'trend_r2': float(r_value**2),
        }

    # GJR baseline stability (for comparison)
    gjr_stability = {}
    gjr_param_names = ['alpha', 'gamma', 'beta', 'persistence']
    gjr_series_list = [gjr_alpha_series, gjr_gamma_series,
                       gjr_beta_series, gjr_persistence_series]
    for name, series in zip(gjr_param_names, gjr_series_list):
        mean_val = float(np.mean(series))
        std_val = float(np.std(series))
        cv = float(std_val / abs(mean_val)) if abs(mean_val) > 1e-10 else np.nan
        gjr_stability[name] = {
            'mean': mean_val,
            'std': std_val,
            'cv': cv,
        }

    # ---- Chow test: pre/post COVID (2020-03-01) ----
    covid_date = '2020-03-01'
    pre_mask = np.array([d < covid_date for d in mf_dates])
    post_mask = ~pre_mask
    n_pre = pre_mask.sum()
    n_post = post_mask.sum()

    chow_results = {}
    if n_pre >= 3 and n_post >= 3:
        for name, series in zip(param_names, param_series):
            pre_vals = series[pre_mask]
            post_vals = series[post_mask]

            # Welch's t-test (unequal variances)
            t_stat, p_val = stats.ttest_ind(pre_vals, post_vals, equal_var=False)
            chow_results[name] = {
                'pre_mean': float(np.mean(pre_vals)),
                'post_mean': float(np.mean(post_vals)),
                'pre_std': float(np.std(pre_vals)),
                'post_std': float(np.std(post_vals)),
                'n_pre': int(n_pre),
                'n_post': int(n_post),
                't_stat': float(t_stat),
                'p_value': float(p_val),
                'significant': bool(p_val < 0.05),
                'mean_change_pct': float(
                    (np.mean(post_vals) - np.mean(pre_vals)) / abs(np.mean(pre_vals)) * 100
                ) if abs(np.mean(pre_vals)) > 1e-10 else np.nan,
            }

    # ---- CUSUM test ----
    cusum_results = {}
    for name, series in zip(param_names, param_series):
        demeaned = series - np.mean(series)
        cusum = np.cumsum(demeaned) / (np.std(series) * np.sqrt(len(series)))
        max_cusum = float(np.max(np.abs(cusum)))
        # Critical value at 5%: ~1.36 (Kolmogorov-Smirnov)
        cusum_results[name] = {
            'max_cusum': max_cusum,
            'exceeds_5pct': bool(max_cusum > 1.36),
            'break_index': int(np.argmax(np.abs(cusum))),
            'break_date': mf_dates[int(np.argmax(np.abs(cusum)))],
        }

    # ---- Parameter-Performance Correlation ----
    rolling_qlike_gjr = np.array(result['rolling_qlike_gjr'])
    rolling_qlike_mfgjr = np.array(result['rolling_qlike_mfgjr'])

    # QLIKE improvement (negative = MF-GJR better)
    qlike_improvement = rolling_qlike_gjr - rolling_qlike_mfgjr
    valid_q = np.isfinite(qlike_improvement)

    perf_correlation = {}
    if valid_q.sum() >= 5:
        # We need to align the parameter series with the QLIKE series
        # Both have the same length (one per refit), but some params may be None
        # Use indices where both are valid
        for name, series in zip(param_names, param_series):
            # The param series only has valid entries, need to map back
            valid_param_idx = [i for i, p in enumerate(mfgjr_params) if p is not None]
            # Intersect with valid QLIKE
            common_idx = [j for j in valid_param_idx if j < len(qlike_improvement) and np.isfinite(qlike_improvement[j])]
            if len(common_idx) >= 5:
                p_vals = np.array([param_series[param_names.index(name)][valid_param_idx.index(j)] for j in common_idx])
                q_vals = np.array([qlike_improvement[j] for j in common_idx])
                rho, p_val = stats.spearmanr(p_vals, q_vals)
                perf_correlation[name] = {
                    'spearman_rho': float(rho),
                    'p_value': float(p_val),
                    'significant': bool(p_val < 0.05),
                    'n': len(common_idx),
                }

    print(f"  {ticker}: Stability analysis complete")
    print(f"    theta_1 CV={stability['theta_1']['cv']:.4f}, "
          f"ADF p={stability['theta_1']['adf_p']:.4f}")

    return {
        'mfgjr_stability': stability,
        'gjr_stability': gjr_stability,
        'chow_test': chow_results,
        'cusum_test': cusum_results,
        'parameter_performance': perf_correlation,
        'n_valid_fits': len(valid_mf),
        'n_total': result['n_refits'],
        'convergence_rate': len(valid_mf) / result['n_refits'],
    }


# Run stability analysis
stability_results = {}
for ticker in ASSETS:
    stability_results[ticker] = analyze_parameter_stability(ticker, all_results[ticker])


# ============================================================
# SECTION 5: CROSS-ASSET COMPARISON
# ============================================================
print("\n[5] Cross-asset parameter comparison...")

cross_asset = {}
for param in ['theta_0', 'theta_1', 'alpha', 'gamma', 'beta', 'persistence_g']:
    vals = {}
    for ticker in ASSETS:
        if stability_results[ticker] is not None:
            s = stability_results[ticker]['mfgjr_stability'].get(param)
            if s:
                vals[ticker] = {
                    'mean': s['mean'],
                    'std': s['std'],
                    'cv': s['cv'],
                }
    cross_asset[param] = vals

    if len(vals) >= 2:
        ticker_vals = {t: v for t, v in vals.items() if isinstance(v, dict)}
        means = [v['mean'] for v in ticker_vals.values()]
        cross_cv = np.std(means) / abs(np.mean(means)) if abs(np.mean(means)) > 1e-10 else np.nan
        means_str = ', '.join(f'{t}={v["mean"]:.4f}' for t, v in ticker_vals.items())
        cross_asset[param]['cross_asset_cv'] = float(cross_cv)
        print(f"  {param}: cross-asset CV = {cross_cv:.4f} (means: {means_str})")


# ============================================================
# SECTION 6: VISUALIZATION
# ============================================================
print("\n[6] Creating plots...")


def plot_parameter_trends(all_results, stability_results, save_path):
    """Plot parameter time series for all assets."""
    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle('K930: MF-GJR Parameter Stability Over Time',
                 fontsize=14, fontweight='bold')

    param_names = ['theta_0', 'theta_1', 'alpha', 'gamma', 'beta', 'persistence_g']
    param_labels = [r'$\theta_0$ (intercept)', r'$\theta_1$ (VIX elasticity)',
                    r'$\alpha$ (ARCH)', r'$\gamma$ (leverage/GJR)',
                    r'$\beta$ (GARCH)', r'Persistence $(\alpha+\gamma/2+\beta)$']

    colors = {'SPY': '#2196F3', 'QQQ': '#FF5722', '0050.TW': '#4CAF50'}

    for ax_idx, (param, label) in enumerate(zip(param_names, param_labels)):
        ax = axes[ax_idx // 2, ax_idx % 2]

        for ticker in ASSETS:
            mfgjr_params = all_results[ticker]['mfgjr_params']
            valid = [(i, p) for i, p in enumerate(mfgjr_params) if p is not None]
            if not valid:
                continue

            dates_valid = [pd.Timestamp(p[param.replace('persistence_g', 'date').replace('theta_0', 'date').replace('theta_1', 'date').replace('alpha', 'date').replace('gamma', 'date').replace('beta', 'date')]) if param == 'date' else all_results[ticker]['refit_dates'][p[0]] for p in valid]
            # Actually, extract properly
            dates_arr = [all_results[ticker]['refit_dates'][idx] for idx, _ in valid]
            if param == 'persistence_g':
                vals = [p['persistence_g'] for _, p in valid]
            else:
                vals = [p[param] for _, p in valid]

            ax.plot(dates_arr, vals, '-o', markersize=3, color=colors[ticker],
                    label=ticker, alpha=0.8, linewidth=1.2)

        # Add COVID line
        covid = pd.Timestamp('2020-03-01')
        ax.axvline(covid, color='red', linestyle='--', alpha=0.5, label='COVID')

        ax.set_title(label, fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.xaxis.set_major_locator(mdates.YearLocator(2))
        if ax_idx == 0:
            ax.legend(fontsize=8, loc='best')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_cross_asset_comparison(stability_results, save_path):
    """Plot cross-asset parameter comparison (box plots)."""
    fig, axes = plt.subplots(2, 3, figsize=(16, 10))
    fig.suptitle('K930: Cross-Asset MF-GJR Parameter Distribution',
                 fontsize=14, fontweight='bold')

    param_names = ['theta_0', 'theta_1', 'alpha', 'gamma', 'beta', 'persistence_g']
    param_labels = [r'$\theta_0$', r'$\theta_1$', r'$\alpha$',
                    r'$\gamma$', r'$\beta$', 'Persistence']
    colors = {'SPY': '#2196F3', 'QQQ': '#FF5722', '0050.TW': '#4CAF50'}

    for ax_idx, (param, label) in enumerate(zip(param_names, param_labels)):
        ax = axes[ax_idx // 3, ax_idx % 3]

        box_data = []
        box_labels = []
        box_colors = []

        for ticker in ASSETS:
            mfgjr_params = all_results[ticker]['mfgjr_params']
            valid = [p for p in mfgjr_params if p is not None]
            if not valid:
                continue

            if param == 'persistence_g':
                vals = [p['persistence_g'] for p in valid]
            else:
                vals = [p[param] for p in valid]

            box_data.append(vals)
            box_labels.append(ticker)
            box_colors.append(colors[ticker])

        if box_data:
            bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True)
            for patch, color in zip(bp['boxes'], box_colors):
                patch.set_facecolor(color)
                patch.set_alpha(0.5)

        ax.set_title(label, fontsize=12)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_theta1_vs_qlike(all_results, save_path):
    """Plot theta_1 vs QLIKE improvement for each asset."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle('K930: VIX Elasticity vs Forecast Improvement',
                 fontsize=14, fontweight='bold')

    colors = {'SPY': '#2196F3', 'QQQ': '#FF5722', '0050.TW': '#4CAF50'}

    for ax_idx, ticker in enumerate(ASSETS):
        ax = axes[ax_idx]
        result = all_results[ticker]
        mfgjr_params = result['mfgjr_params']
        qlike_gjr = np.array(result['rolling_qlike_gjr'])
        qlike_mfgjr = np.array(result['rolling_qlike_mfgjr'])

        # QLIKE improvement (positive = MF-GJR better)
        improvement = qlike_gjr - qlike_mfgjr

        # Extract theta_1 for valid indices
        theta1_vals = []
        improve_vals = []
        for i, p in enumerate(mfgjr_params):
            if p is not None and i < len(improvement) and np.isfinite(improvement[i]):
                theta1_vals.append(p['theta_1'])
                improve_vals.append(improvement[i])

        if len(theta1_vals) >= 5:
            ax.scatter(theta1_vals, improve_vals, color=colors[ticker],
                       alpha=0.6, s=30, edgecolors='black', linewidth=0.5)

            # Add regression line
            slope, intercept, r_value, p_value, _ = stats.linregress(
                theta1_vals, improve_vals)
            x_line = np.linspace(min(theta1_vals), max(theta1_vals), 50)
            ax.plot(x_line, intercept + slope * x_line, 'k--', alpha=0.5,
                    label=f'r={r_value:.3f}, p={p_value:.3f}')

            ax.axhline(0, color='gray', linestyle=':', alpha=0.5)
            ax.legend(fontsize=9)

        ax.set_xlabel(r'$\theta_1$ (VIX elasticity)')
        ax.set_ylabel('QLIKE improvement\n(GJR - MF-GJR, positive = MF-GJR better)')
        ax.set_title(ticker, fontsize=12, color=colors[ticker])
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


# Generate all plots
trends_path = os.path.join(SCRIPT_DIR, 'k930_parameter_trends.png')
cross_path = os.path.join(SCRIPT_DIR, 'k930_cross_asset.png')
perf_path = os.path.join(SCRIPT_DIR, 'k930_theta1_vs_qlike.png')

plot_parameter_trends(all_results, stability_results, trends_path)
plot_cross_asset_comparison(stability_results, cross_path)
plot_theta1_vs_qlike(all_results, perf_path)


# ============================================================
# SECTION 7: SUMMARY & RESULTS
# ============================================================
print("\n[7] Summary...")

# Build final results dict
final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR Parameter Stability Over Time',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(time.time() - START_TIME, 1),
    'methodology': {
        'models': ['MF-GJR', 'GJR-GARCH (baseline)'],
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'estimation': f'Rolling window (w={WINDOW}), refit every {REFIT_EVERY} days',
        'stability_tests': ['Coefficient of Variation (CV)', 'ADF test',
                           'Welch t-test (pre/post COVID)', 'CUSUM test',
                           'Linear trend test'],
    },
    'data': {
        'source': 'yfinance',
        'assets': ASSETS,
        'period': f'{DATA_START} to {DATA_END}',
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
    },
    'results': {},
    'cross_asset_comparison': cross_asset,
}

# Determine overall conclusions
all_theta1_stable = True
any_structural_break = False

for ticker in ASSETS:
    sr = stability_results[ticker]
    if sr is None:
        final_results['results'][ticker] = {'error': 'Insufficient convergence'}
        continue

    final_results['results'][ticker] = {
        'mfgjr_stability': sr['mfgjr_stability'],
        'gjr_stability': sr['gjr_stability'],
        'chow_test': sr['chow_test'],
        'cusum_test': sr['cusum_test'],
        'parameter_performance': sr['parameter_performance'],
        'convergence_rate': sr['convergence_rate'],
        'n_valid_fits': sr['n_valid_fits'],
        'n_total': sr['n_total'],
    }

    # Check theta_1 stability
    theta1 = sr['mfgjr_stability'].get('theta_1', {})
    if theta1.get('cv', 1.0) > 0.5:  # CV > 50% = unstable
        all_theta1_stable = False

    # Check for structural breaks
    chow_theta1 = sr['chow_test'].get('theta_1', {})
    if chow_theta1.get('significant', False):
        any_structural_break = True

    # Print summary table
    print(f"\n  === {ticker} ===")
    print(f"    Convergence: {sr['convergence_rate']:.1%} ({sr['n_valid_fits']}/{sr['n_total']})")
    print(f"    {'Parameter':15s} {'Mean':>10s} {'Std':>10s} {'CV':>8s} {'ADF p':>8s} {'Trend p':>8s} {'Chow p':>8s}")
    print(f"    {'-'*70}")
    for param in ['theta_0', 'theta_1', 'alpha', 'gamma', 'beta', 'persistence_g']:
        s = sr['mfgjr_stability'].get(param, {})
        chow = sr['chow_test'].get(param, {})
        print(f"    {param:15s} {s.get('mean',0):10.4f} {s.get('std',0):10.4f} "
              f"{s.get('cv',0):8.4f} {s.get('adf_p',1):8.4f} "
              f"{s.get('trend_p',1):8.4f} {chow.get('p_value',1):8.4f}")

    # CUSUM
    print(f"\n    CUSUM tests:")
    for param in ['theta_0', 'theta_1', 'alpha', 'gamma', 'beta']:
        cusum = sr['cusum_test'].get(param, {})
        print(f"      {param}: max={cusum.get('max_cusum',0):.3f} "
              f"{'BREAK' if cusum.get('exceeds_5pct') else 'stable'} "
              f"(peak at {cusum.get('break_date', 'N/A')})")


# Overall conclusion
conclusion = {
    'theta1_stable_across_time': all_theta1_stable,
    'structural_break_detected': any_structural_break,
    'summary': [],
}

for ticker in ASSETS:
    sr = stability_results[ticker]
    if sr is None:
        continue
    theta1 = sr['mfgjr_stability'].get('theta_1', {})
    conclusion['summary'].append(
        f"{ticker}: theta_1 CV={theta1.get('cv', np.nan):.4f}, "
        f"ADF p={theta1.get('adf_p', np.nan):.4f}, "
        f"Chow p={sr['chow_test'].get('theta_1', {}).get('p_value', np.nan):.4f}"
    )

final_results['conclusion'] = conclusion
final_results['references'] = [
    'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
    'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
    'Patton (2011) J Econometrics 160:246-256',
    'Harvey et al. (2016) JBES 34:92-104',
]

# Save results
with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"\nResults saved to: {RESULTS_PATH}")

elapsed = time.time() - START_TIME
print(f"\n{'='*70}")
print(f"K930 completed in {elapsed:.1f}s ({elapsed/60:.1f} min)")
print(f"{'='*70}")
