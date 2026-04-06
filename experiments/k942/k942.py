#!/usr/bin/env python3
"""
K942: MF-GJR(VIX) Subsample Stability — Paper Robustness
=========================================================
[提出: Claude, 執行: Claude]

Tests whether MF-GJR(VIX)'s superiority over GJR is robust across:
  1. Five time subperiods (each ~2 years)
  2. Three VIX regimes (Low/Medium/High)
  3. Five volatility quintiles (20-day rolling sigma)

Key Question: Is the QLIKE improvement from K889 stable across different
market environments, or concentrated in specific conditions?

Data:
  - Asset: SPY (2006-01-03 to 2025-12-31)
  - VIX from yfinance (^VIX)
  - OOS period: 2016-01-01 to 2025-12-31

Models:
  - GARCH(1,1)
  - GJR-GARCH(1,1,1)
  - MF-GJR(VIX): tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1})), short-run GJR

Evaluation:
  - QLIKE on r² (Patton 2011 proxy-robust)
  - DM test (Harvey 2016 |t| > 3.0)
  - Improvement % per subsample

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
from scipy import optimize

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K942"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k942_results.json')

# Data parameters
DATA_START = '2005-01-01'
DATA_END = '2026-01-01'
WINDOW = 2000
REFIT_EVERY = 21  # monthly refit
OOS_START = '2016-01-01'
OOS_END = '2025-12-31'

# Subsample definitions
TIME_PERIODS = {
    '2016-2017': ('2016-01-01', '2017-12-31'),
    '2018-2019': ('2018-01-01', '2019-12-31'),
    '2020-2021': ('2020-01-01', '2021-12-31'),
    '2022-2023': ('2022-01-01', '2023-12-31'),
    '2024-2025': ('2024-01-01', '2025-12-31'),
}

VIX_REGIMES = {
    'Low (VIX<15)': (0, 15),
    'Medium (15-25)': (15, 25),
    'High (VIX>=25)': (25, 999),
}

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR(VIX) Subsample Stability")
print("  Testing robustness across time periods, VIX regimes, vol quintiles")
print("=" * 70)


# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Download SPY
spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
spy_prices = spy_raw['Close'].copy()
spy_ret = np.log(spy_prices / spy_prices.shift(1))

# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# Combine
df = pd.DataFrame({
    'price': spy_prices,
    'log_ret': spy_ret,
    'VIX': vix_close,
})
df = df.dropna()
df['r2'] = df['log_ret'] ** 2
df['log_vix'] = np.log(df['VIX'])
# 20-day rolling realized vol for quintile analysis
df['rvol_20d'] = df['log_ret'].rolling(20).std() * np.sqrt(252)
df = df.dropna()

print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")
print(f"  OOS: {OOS_START} to {OOS_END}")


# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[2] Model implementations...")


def garch_loglik(params, returns):
    """Standard GARCH(1,1) log-likelihood."""
    omega, alpha, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    ll = 0.0
    for t in range(1, n):
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_garch(returns):
    """Fit GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None
    starts = [
        [1e-6, 0.05, 0.90],
        [1e-6, 0.08, 0.85],
        [1e-5, 0.03, 0.93],
        [5e-6, 0.10, 0.85],
    ]
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.5, 0.999)]
    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: garch_loglik(p, returns),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params, (-best_ll if best_params is not None else None)


def gjr_loglik(params, returns):
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


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1,1) via MLE with multi-start."""
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
                lambda p: gjr_loglik(p, returns),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params, (-best_ll if best_params is not None else None)


def fit_mf_gjr(returns, log_vix):
    """Fit MF-GJR: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1})), short-run GJR."""
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
        theta0, theta1, alpha, gamma, beta = params
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

    starts = [
        [theta_init[0], theta_init[1], 0.05, 0.05, 0.90],
        [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.10, 0.85],
        [-8.0, 0.5, 0.05, 0.05, 0.90],
        [-7.0, 0.8, 0.03, 0.03, 0.93],
    ]
    bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

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


# ============================================================
# SECTION 3: OOS FORECASTING (Recursive, day-by-day)
# ============================================================
print("\n[3] OOS forecasting (recursive, refit every 21 days)...")

ret_arr = df['log_ret'].values
r2_arr = df['r2'].values
vix_arr = df['VIX'].values
log_vix_arr = df['log_vix'].values
dates_arr = df.index
rvol_arr = df['rvol_20d'].values

# Find OOS start/end index
oos_mask = (dates_arr >= pd.Timestamp(OOS_START)) & (dates_arr <= pd.Timestamp(OOS_END))
oos_indices = np.where(oos_mask)[0]
oos_start_idx = oos_indices[0]
oos_end_idx = oos_indices[-1]

print(f"  OOS indices: {oos_start_idx} to {oos_end_idx} ({len(oos_indices)} days)")
print(f"  Training window: {WINDOW} days, refit every {REFIT_EVERY} days")

# Storage for OOS forecasts
n_oos = len(oos_indices)
forecasts_garch = np.full(n_oos, np.nan)
forecasts_gjr = np.full(n_oos, np.nan)
forecasts_mfgjr = np.full(n_oos, np.nan)
oos_dates = dates_arr[oos_indices]
oos_r2 = r2_arr[oos_indices]
oos_vix = vix_arr[oos_indices]
oos_rvol = rvol_arr[oos_indices]

# Current model parameters (to be updated at refit points)
garch_params = None
gjr_params = None
mfgjr_params = None

# Running variance states
h_garch = None
h_gjr = None
h_mfgjr_g = None  # short-run component

last_refit = -999  # force immediate refit
n_refits = 0

for i, t in enumerate(oos_indices):
    # Check if refit needed
    if t - last_refit >= REFIT_EVERY or garch_params is None:
        train_start = max(0, t - WINDOW)
        train_ret = ret_arr[train_start:t]
        train_log_vix = log_vix_arr[train_start:t]

        # Fit all three models
        garch_params, _ = fit_garch(train_ret)
        gjr_params, _ = fit_gjr(train_ret)
        mfgjr_params, _ = fit_mf_gjr(train_ret, train_log_vix)

        # Initialize variance states from training data
        if garch_params is not None:
            o, a, b = garch_params
            h = np.var(train_ret)
            for tt in range(1, len(train_ret)):
                h = o + a * train_ret[tt-1]**2 + b * h
                h = max(h, 1e-10)
            h_garch = h

        if gjr_params is not None:
            o, a, g, b = gjr_params
            h = np.var(train_ret)
            for tt in range(1, len(train_ret)):
                asym = g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                h = o + a * train_ret[tt-1]**2 + asym + b * h
                h = max(h, 1e-10)
            h_gjr = h

        if mfgjr_params is not None:
            th0, th1, a_mf, g_mf, b_mf = mfgjr_params
            omega_g = 1.0 - a_mf - g_mf / 2.0 - b_mf
            log_vix_lag_train = np.roll(train_log_vix, 1)
            log_vix_lag_train[0] = train_log_vix[0]
            tau_train = np.exp(th0 + th1 * log_vix_lag_train)
            tau_train = np.maximum(tau_train, 1e-16)
            u_train = train_ret / np.sqrt(tau_train)
            g_state = 1.0
            for tt in range(1, len(train_ret)):
                asym = g_mf * u_train[tt-1]**2 if u_train[tt-1] < 0 else 0.0
                g_state = omega_g + a_mf * u_train[tt-1]**2 + asym + b_mf * g_state
                g_state = max(g_state, 1e-10)
            h_mfgjr_g = g_state

        last_refit = t
        n_refits += 1
        if n_refits % 10 == 0:
            print(f"    Refit #{n_refits} at {dates_arr[t].strftime('%Y-%m-%d')}")

    # Day-by-day recursive forecast using PREVIOUS day's return
    r_prev = ret_arr[t - 1]

    # GARCH forecast
    if garch_params is not None and h_garch is not None:
        o, a, b = garch_params
        h_garch = o + a * r_prev**2 + b * h_garch
        h_garch = max(h_garch, 1e-10)
        forecasts_garch[i] = h_garch

    # GJR forecast
    if gjr_params is not None and h_gjr is not None:
        o, a, g, b = gjr_params
        asym = g * r_prev**2 if r_prev < 0 else 0.0
        h_gjr = o + a * r_prev**2 + asym + b * h_gjr
        h_gjr = max(h_gjr, 1e-10)
        forecasts_gjr[i] = h_gjr

    # MF-GJR forecast (uses VIX from t-1)
    if mfgjr_params is not None and h_mfgjr_g is not None:
        th0, th1, a_mf, g_mf, b_mf = mfgjr_params
        omega_g = 1.0 - a_mf - g_mf / 2.0 - b_mf
        # tau uses lagged VIX
        tau_t = np.exp(th0 + th1 * log_vix_arr[t - 1])
        tau_t = max(tau_t, 1e-16)
        # Update short-run g with standardized return
        u_prev = r_prev / np.sqrt(np.exp(th0 + th1 * log_vix_arr[max(0, t - 2)]))
        asym = g_mf * u_prev**2 if u_prev < 0 else 0.0
        h_mfgjr_g = omega_g + a_mf * u_prev**2 + asym + b_mf * h_mfgjr_g
        h_mfgjr_g = max(h_mfgjr_g, 1e-10)
        forecasts_mfgjr[i] = tau_t * h_mfgjr_g

print(f"  Total refits: {n_refits}")

# Drop any NaN forecasts
valid = np.isfinite(forecasts_garch) & np.isfinite(forecasts_gjr) & np.isfinite(forecasts_mfgjr) & (oos_r2 > 0)
print(f"  Valid forecasts: {valid.sum()} / {n_oos}")

# Apply validity mask
f_garch = forecasts_garch[valid]
f_gjr = forecasts_gjr[valid]
f_mfgjr = forecasts_mfgjr[valid]
target = oos_r2[valid]
dates_valid = oos_dates[valid]
vix_valid = oos_vix[valid]
rvol_valid = oos_rvol[valid]


# ============================================================
# SECTION 4: FULL OOS RESULTS
# ============================================================
print("\n[4] Full OOS results...")

qlike_garch_full = qlike(target, f_garch)
qlike_gjr_full = qlike(target, f_gjr)
qlike_mfgjr_full = qlike(target, f_mfgjr)

# DM tests (pointwise QLIKE losses)
loss_garch = qlike_pointwise(target, f_garch)
loss_gjr = qlike_pointwise(target, f_gjr)
loss_mfgjr = qlike_pointwise(target, f_mfgjr)

dm_mfgjr_vs_gjr_t, dm_mfgjr_vs_gjr_p = dm_test(loss_mfgjr, loss_gjr)
dm_mfgjr_vs_garch_t, dm_mfgjr_vs_garch_p = dm_test(loss_mfgjr, loss_garch)
dm_gjr_vs_garch_t, dm_gjr_vs_garch_p = dm_test(loss_gjr, loss_garch)

improv_mfgjr_vs_gjr = (qlike_gjr_full - qlike_mfgjr_full) / qlike_gjr_full * 100
improv_mfgjr_vs_garch = (qlike_garch_full - qlike_mfgjr_full) / qlike_garch_full * 100

print(f"  QLIKE: GARCH={qlike_garch_full:.6f}, GJR={qlike_gjr_full:.6f}, MF-GJR={qlike_mfgjr_full:.6f}")
print(f"  MF-GJR vs GJR: improvement {improv_mfgjr_vs_gjr:.2f}%, DM t={dm_mfgjr_vs_gjr_t:.3f}, p={dm_mfgjr_vs_gjr_p:.4f}")
print(f"  MF-GJR vs GARCH: improvement {improv_mfgjr_vs_garch:.2f}%, DM t={dm_mfgjr_vs_garch_t:.3f}, p={dm_mfgjr_vs_garch_p:.4f}")
print(f"  GJR vs GARCH: DM t={dm_gjr_vs_garch_t:.3f}, p={dm_gjr_vs_garch_p:.4f}")


# ============================================================
# SECTION 5: TIME PERIOD SUBSAMPLES
# ============================================================
print("\n[5] Time period subsamples...")

time_results = {}
for period_name, (start, end) in TIME_PERIODS.items():
    mask = (dates_valid >= pd.Timestamp(start)) & (dates_valid <= pd.Timestamp(end))
    n_obs = mask.sum()
    if n_obs < 50:
        print(f"  {period_name}: insufficient data ({n_obs} obs)")
        continue

    t_sub = target[mask]
    fg_sub = f_garch[mask]
    fj_sub = f_gjr[mask]
    fm_sub = f_mfgjr[mask]

    ql_garch = qlike(t_sub, fg_sub)
    ql_gjr = qlike(t_sub, fj_sub)
    ql_mfgjr = qlike(t_sub, fm_sub)

    # DM test within subsample
    l_gjr = qlike_pointwise(t_sub, fj_sub)
    l_mfgjr = qlike_pointwise(t_sub, fm_sub)
    l_garch = qlike_pointwise(t_sub, fg_sub)
    dm_t, dm_p = dm_test(l_mfgjr, l_gjr)
    dm_garch_t, dm_garch_p = dm_test(l_mfgjr, l_garch)

    improv_vs_gjr = (ql_gjr - ql_mfgjr) / ql_gjr * 100
    improv_vs_garch = (ql_garch - ql_mfgjr) / ql_garch * 100

    time_results[period_name] = {
        'n_obs': int(n_obs),
        'qlike_garch': float(ql_garch),
        'qlike_gjr': float(ql_gjr),
        'qlike_mfgjr': float(ql_mfgjr),
        'improvement_vs_gjr_pct': float(improv_vs_gjr),
        'improvement_vs_garch_pct': float(improv_vs_garch),
        'dm_mfgjr_vs_gjr_t': float(dm_t),
        'dm_mfgjr_vs_gjr_p': float(dm_p),
        'dm_mfgjr_vs_garch_t': float(dm_garch_t),
        'dm_mfgjr_vs_garch_p': float(dm_garch_p),
        'mfgjr_wins': bool(ql_mfgjr < ql_gjr),
    }

    sig = "***" if abs(dm_t) > 3.0 else ("**" if abs(dm_t) > 2.0 else ("*" if abs(dm_t) > 1.65 else ""))
    print(f"  {period_name}: n={n_obs}, QLIKE G={ql_garch:.6f} GJR={ql_gjr:.6f} MF-GJR={ql_mfgjr:.6f}")
    print(f"    MF-GJR vs GJR: {improv_vs_gjr:+.2f}%, DM t={dm_t:.3f} {sig}")

# Count wins
wins = sum(1 for r in time_results.values() if r['mfgjr_wins'])
print(f"\n  MF-GJR wins in {wins}/{len(time_results)} periods")


# ============================================================
# SECTION 6: VIX REGIME SUBSAMPLES
# ============================================================
print("\n[6] VIX regime subsamples...")

regime_results = {}
for regime_name, (vix_low, vix_high) in VIX_REGIMES.items():
    mask = (vix_valid >= vix_low) & (vix_valid < vix_high)
    n_obs = mask.sum()
    if n_obs < 50:
        print(f"  {regime_name}: insufficient data ({n_obs} obs)")
        continue

    t_sub = target[mask]
    fg_sub = f_garch[mask]
    fj_sub = f_gjr[mask]
    fm_sub = f_mfgjr[mask]

    ql_garch = qlike(t_sub, fg_sub)
    ql_gjr = qlike(t_sub, fj_sub)
    ql_mfgjr = qlike(t_sub, fm_sub)

    l_gjr = qlike_pointwise(t_sub, fj_sub)
    l_mfgjr = qlike_pointwise(t_sub, fm_sub)
    l_garch = qlike_pointwise(t_sub, fg_sub)
    dm_t, dm_p = dm_test(l_mfgjr, l_gjr)
    dm_garch_t, dm_garch_p = dm_test(l_mfgjr, l_garch)

    improv_vs_gjr = (ql_gjr - ql_mfgjr) / ql_gjr * 100
    improv_vs_garch = (ql_garch - ql_mfgjr) / ql_garch * 100

    regime_results[regime_name] = {
        'n_obs': int(n_obs),
        'qlike_garch': float(ql_garch),
        'qlike_gjr': float(ql_gjr),
        'qlike_mfgjr': float(ql_mfgjr),
        'improvement_vs_gjr_pct': float(improv_vs_gjr),
        'improvement_vs_garch_pct': float(improv_vs_garch),
        'dm_mfgjr_vs_gjr_t': float(dm_t),
        'dm_mfgjr_vs_gjr_p': float(dm_p),
        'dm_mfgjr_vs_garch_t': float(dm_garch_t),
        'dm_mfgjr_vs_garch_p': float(dm_garch_p),
        'mfgjr_wins': bool(ql_mfgjr < ql_gjr),
    }

    sig = "***" if abs(dm_t) > 3.0 else ("**" if abs(dm_t) > 2.0 else ("*" if abs(dm_t) > 1.65 else ""))
    print(f"  {regime_name}: n={n_obs}, QLIKE G={ql_garch:.6f} GJR={ql_gjr:.6f} MF-GJR={ql_mfgjr:.6f}")
    print(f"    MF-GJR vs GJR: {improv_vs_gjr:+.2f}%, DM t={dm_t:.3f} {sig}")


# ============================================================
# SECTION 7: VOLATILITY QUINTILE SUBSAMPLES
# ============================================================
print("\n[7] Volatility quintile subsamples...")

quintile_breaks = np.percentile(rvol_valid, [0, 20, 40, 60, 80, 100])
quintile_labels = ['Q1 (Lowest)', 'Q2', 'Q3', 'Q4', 'Q5 (Highest)']

quintile_results = {}
for q in range(5):
    mask = (rvol_valid >= quintile_breaks[q]) & (rvol_valid < quintile_breaks[q+1] + 1e-10)
    n_obs = mask.sum()
    if n_obs < 30:
        print(f"  {quintile_labels[q]}: insufficient data ({n_obs} obs)")
        continue

    t_sub = target[mask]
    fg_sub = f_garch[mask]
    fj_sub = f_gjr[mask]
    fm_sub = f_mfgjr[mask]

    ql_garch = qlike(t_sub, fg_sub)
    ql_gjr = qlike(t_sub, fj_sub)
    ql_mfgjr = qlike(t_sub, fm_sub)

    l_gjr = qlike_pointwise(t_sub, fj_sub)
    l_mfgjr = qlike_pointwise(t_sub, fm_sub)
    l_garch = qlike_pointwise(t_sub, fg_sub)
    dm_t, dm_p = dm_test(l_mfgjr, l_gjr)
    dm_garch_t, dm_garch_p = dm_test(l_mfgjr, l_garch)

    improv_vs_gjr = (ql_gjr - ql_mfgjr) / ql_gjr * 100
    improv_vs_garch = (ql_garch - ql_mfgjr) / ql_garch * 100
    rvol_range = f"{quintile_breaks[q]*100:.1f}%-{quintile_breaks[q+1]*100:.1f}%"

    quintile_results[quintile_labels[q]] = {
        'n_obs': int(n_obs),
        'rvol_range': rvol_range,
        'qlike_garch': float(ql_garch),
        'qlike_gjr': float(ql_gjr),
        'qlike_mfgjr': float(ql_mfgjr),
        'improvement_vs_gjr_pct': float(improv_vs_gjr),
        'improvement_vs_garch_pct': float(improv_vs_garch),
        'dm_mfgjr_vs_gjr_t': float(dm_t),
        'dm_mfgjr_vs_gjr_p': float(dm_p),
        'dm_mfgjr_vs_garch_t': float(dm_garch_t),
        'dm_mfgjr_vs_garch_p': float(dm_garch_p),
        'mfgjr_wins': bool(ql_mfgjr < ql_gjr),
    }

    sig = "***" if abs(dm_t) > 3.0 else ("**" if abs(dm_t) > 2.0 else ("*" if abs(dm_t) > 1.65 else ""))
    print(f"  {quintile_labels[q]} ({rvol_range}): n={n_obs}, QLIKE GJR={ql_gjr:.6f} MF-GJR={ql_mfgjr:.6f}")
    print(f"    MF-GJR vs GJR: {improv_vs_gjr:+.2f}%, DM t={dm_t:.3f} {sig}")


# ============================================================
# SECTION 8: ROLLING QLIKE DIFFERENCE (63-day window)
# ============================================================
print("\n[8] Rolling QLIKE difference (63-day)...")

roll_window = 63
n_valid = len(target)
rolling_diff_gjr = np.full(n_valid, np.nan)  # positive = MF-GJR better
rolling_diff_garch = np.full(n_valid, np.nan)

for i in range(roll_window, n_valid):
    window_slice = slice(i - roll_window, i)
    t_w = target[window_slice]
    fg_w = f_garch[window_slice]
    fj_w = f_gjr[window_slice]
    fm_w = f_mfgjr[window_slice]

    ql_gjr_w = qlike(t_w, fj_w)
    ql_mfgjr_w = qlike(t_w, fm_w)
    ql_garch_w = qlike(t_w, fg_w)

    rolling_diff_gjr[i] = ql_gjr_w - ql_mfgjr_w  # positive = MF-GJR better
    rolling_diff_garch[i] = ql_garch_w - ql_mfgjr_w

# Count fraction of time MF-GJR wins
valid_rolling = ~np.isnan(rolling_diff_gjr)
frac_mfgjr_wins_rolling = np.mean(rolling_diff_gjr[valid_rolling] > 0)
print(f"  MF-GJR wins {frac_mfgjr_wins_rolling*100:.1f}% of 63-day rolling windows (vs GJR)")


# ============================================================
# SECTION 9: FIGURES
# ============================================================
print("\n[9] Generating figures...")

# --- Figure 1: Rolling QLIKE Difference ---
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

ax1 = axes[0]
ax1.plot(dates_valid[valid_rolling], rolling_diff_gjr[valid_rolling],
         color='#2196F3', linewidth=0.8, alpha=0.8, label='QLIKE(GJR) - QLIKE(MF-GJR)')
ax1.axhline(y=0, color='black', linewidth=0.5, linestyle='--')
ax1.fill_between(dates_valid[valid_rolling], 0, rolling_diff_gjr[valid_rolling],
                 where=rolling_diff_gjr[valid_rolling] > 0, alpha=0.3, color='#4CAF50', label='MF-GJR better')
ax1.fill_between(dates_valid[valid_rolling], 0, rolling_diff_gjr[valid_rolling],
                 where=rolling_diff_gjr[valid_rolling] <= 0, alpha=0.3, color='#F44336', label='GJR better')
ax1.set_ylabel('QLIKE Difference')
ax1.set_title(f'K942: Rolling 63-Day QLIKE Difference — MF-GJR(VIX) vs GJR\n'
              f'MF-GJR wins {frac_mfgjr_wins_rolling*100:.1f}% of windows', fontsize=13)
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)

# Add period boundaries
for _, (start, end) in TIME_PERIODS.items():
    ax1.axvline(x=pd.Timestamp(start), color='gray', linewidth=0.5, linestyle=':')

ax2 = axes[1]
ax2.plot(dates_valid, vix_valid, color='#FF9800', linewidth=0.7, alpha=0.8)
ax2.axhline(y=15, color='green', linewidth=0.5, linestyle='--', alpha=0.5)
ax2.axhline(y=25, color='red', linewidth=0.5, linestyle='--', alpha=0.5)
ax2.fill_between(dates_valid, 0, vix_valid, where=vix_valid < 15, alpha=0.15, color='green')
ax2.fill_between(dates_valid, 0, vix_valid, where=(vix_valid >= 15) & (vix_valid < 25), alpha=0.15, color='orange')
ax2.fill_between(dates_valid, 0, vix_valid, where=vix_valid >= 25, alpha=0.15, color='red')
ax2.set_ylabel('VIX Level')
ax2.set_xlabel('Date')
ax2.set_title('VIX Regime Context', fontsize=11)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k942_subsample.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k942_subsample.png")

# --- Figure 2: VIX Regime Bar Chart ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Panel A: QLIKE by regime
regime_names = list(regime_results.keys())
n_regimes = len(regime_names)
x_reg = np.arange(n_regimes)
width = 0.25

bars_garch = [regime_results[r]['qlike_garch'] for r in regime_names]
bars_gjr = [regime_results[r]['qlike_gjr'] for r in regime_names]
bars_mfgjr = [regime_results[r]['qlike_mfgjr'] for r in regime_names]

ax = axes[0]
ax.bar(x_reg - width, bars_garch, width, label='GARCH', color='#9E9E9E', alpha=0.8)
ax.bar(x_reg, bars_gjr, width, label='GJR', color='#2196F3', alpha=0.8)
ax.bar(x_reg + width, bars_mfgjr, width, label='MF-GJR', color='#4CAF50', alpha=0.8)
ax.set_xticks(x_reg)
ax.set_xticklabels(regime_names, fontsize=9)
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('QLIKE by VIX Regime', fontsize=12)
ax.legend(fontsize=9)
ax.grid(True, alpha=0.3, axis='y')

# Panel B: Improvement % and DM t-stat
ax2 = axes[1]
improv_vals = [regime_results[r]['improvement_vs_gjr_pct'] for r in regime_names]
dm_vals = [regime_results[r]['dm_mfgjr_vs_gjr_t'] for r in regime_names]

colors = ['#4CAF50' if v > 0 else '#F44336' for v in improv_vals]
bars = ax2.bar(x_reg - 0.15, improv_vals, 0.3, color=colors, alpha=0.8, label='Improvement %')
ax2.axhline(y=0, color='black', linewidth=0.5)
ax2.set_ylabel('QLIKE Improvement % (MF-GJR vs GJR)', color='#333')

# DM t-stat on secondary axis
ax3 = ax2.twinx()
ax3.scatter(x_reg + 0.15, dm_vals, color='#FF5722', marker='D', s=80, zorder=5, label='DM t-stat')
ax3.axhline(y=-3.0, color='red', linewidth=0.8, linestyle='--', alpha=0.5, label='Harvey |t|>3')
ax3.axhline(y=3.0, color='red', linewidth=0.8, linestyle='--', alpha=0.5)
ax3.set_ylabel('DM t-statistic', color='#FF5722')

ax2.set_xticks(x_reg)
ax2.set_xticklabels(regime_names, fontsize=9)
ax2.set_title('Improvement & DM Test by VIX Regime', fontsize=12)

# Combined legend
lines1, labels1 = ax2.get_legend_handles_labels()
lines2, labels2 = ax3.get_legend_handles_labels()
ax2.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)

ax2.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k942_regime.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k942_regime.png")

# --- Figure 3: Comprehensive subsample summary ---
fig, axes = plt.subplots(1, 3, figsize=(18, 6))

# Panel A: Time periods
period_names = list(time_results.keys())
n_periods = len(period_names)
x_per = np.arange(n_periods)

improv_time = [time_results[p]['improvement_vs_gjr_pct'] for p in period_names]
dm_time = [time_results[p]['dm_mfgjr_vs_gjr_t'] for p in period_names]
colors_time = ['#4CAF50' if v > 0 else '#F44336' for v in improv_time]

ax = axes[0]
ax.bar(x_per, improv_time, color=colors_time, alpha=0.8, edgecolor='white')
ax.axhline(y=0, color='black', linewidth=0.5)
# Add DM t-stat labels
for j, (imp, dm) in enumerate(zip(improv_time, dm_time)):
    sig = "***" if abs(dm) > 3.0 else ("**" if abs(dm) > 2.0 else ("*" if abs(dm) > 1.65 else ""))
    ax.text(j, imp + (0.3 if imp > 0 else -0.5), f't={dm:.1f}{sig}', ha='center', fontsize=8)
ax.set_xticks(x_per)
ax.set_xticklabels(period_names, fontsize=9, rotation=15)
ax.set_ylabel('QLIKE Improvement % (MF-GJR vs GJR)')
ax.set_title('A. Time Periods', fontsize=12, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')

# Panel B: VIX regimes
improv_regime = [regime_results[r]['improvement_vs_gjr_pct'] for r in regime_names]
dm_regime = [regime_results[r]['dm_mfgjr_vs_gjr_t'] for r in regime_names]
colors_regime = ['#4CAF50' if v > 0 else '#F44336' for v in improv_regime]

ax = axes[1]
ax.bar(x_reg, improv_regime, color=colors_regime, alpha=0.8, edgecolor='white')
ax.axhline(y=0, color='black', linewidth=0.5)
for j, (imp, dm) in enumerate(zip(improv_regime, dm_regime)):
    sig = "***" if abs(dm) > 3.0 else ("**" if abs(dm) > 2.0 else ("*" if abs(dm) > 1.65 else ""))
    ax.text(j, imp + (0.3 if imp > 0 else -0.5), f't={dm:.1f}{sig}', ha='center', fontsize=8)
ax.set_xticks(x_reg)
ax.set_xticklabels([r.split('(')[1].rstrip(')') for r in regime_names], fontsize=9)
ax.set_ylabel('QLIKE Improvement %')
ax.set_title('B. VIX Regimes', fontsize=12, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')

# Panel C: Vol quintiles
q_names = list(quintile_results.keys())
n_q = len(q_names)
x_q = np.arange(n_q)

improv_quint = [quintile_results[q]['improvement_vs_gjr_pct'] for q in q_names]
dm_quint = [quintile_results[q]['dm_mfgjr_vs_gjr_t'] for q in q_names]
colors_quint = ['#4CAF50' if v > 0 else '#F44336' for v in improv_quint]

ax = axes[2]
ax.bar(x_q, improv_quint, color=colors_quint, alpha=0.8, edgecolor='white')
ax.axhline(y=0, color='black', linewidth=0.5)
for j, (imp, dm) in enumerate(zip(improv_quint, dm_quint)):
    sig = "***" if abs(dm) > 3.0 else ("**" if abs(dm) > 2.0 else ("*" if abs(dm) > 1.65 else ""))
    ax.text(j, imp + (0.3 if imp > 0 else -0.5), f't={dm:.1f}{sig}', ha='center', fontsize=8)
ax.set_xticks(x_q)
ax.set_xticklabels(q_names, fontsize=8, rotation=15)
ax.set_ylabel('QLIKE Improvement %')
ax.set_title('C. Volatility Quintiles', fontsize=12, fontweight='bold')
ax.grid(True, alpha=0.3, axis='y')

plt.suptitle(f'K942: MF-GJR(VIX) Subsample Stability — SPY OOS {OOS_START}~{OOS_END}',
             fontsize=14, fontweight='bold', y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k942_summary.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k942_summary.png")


# ============================================================
# SECTION 10: ROBUSTNESS ASSESSMENT
# ============================================================
print("\n[10] Robustness assessment...")

# Time period wins
time_wins = sum(1 for r in time_results.values() if r['mfgjr_wins'])
time_sig_wins = sum(1 for r in time_results.values()
                    if r['mfgjr_wins'] and abs(r['dm_mfgjr_vs_gjr_t']) > 3.0)
# VIX regime wins
regime_wins = sum(1 for r in regime_results.values() if r['mfgjr_wins'])
regime_sig_wins = sum(1 for r in regime_results.values()
                      if r['mfgjr_wins'] and abs(r['dm_mfgjr_vs_gjr_t']) > 3.0)
# Vol quintile wins
quint_wins = sum(1 for r in quintile_results.values() if r['mfgjr_wins'])
quint_sig_wins = sum(1 for r in quintile_results.values()
                     if r['mfgjr_wins'] and abs(r['dm_mfgjr_vs_gjr_t']) > 3.0)

total_subsamples = len(time_results) + len(regime_results) + len(quintile_results)
total_wins = time_wins + regime_wins + quint_wins
total_sig_wins = time_sig_wins + regime_sig_wins + quint_sig_wins

robust_time = time_wins >= 4  # >= 4/5
robust_regime = regime_wins >= 2  # >= 2/3
robust_overall = robust_time and robust_regime

print(f"  Time periods: MF-GJR wins {time_wins}/{len(time_results)} (sig: {time_sig_wins})")
print(f"  VIX regimes: MF-GJR wins {regime_wins}/{len(regime_results)} (sig: {regime_sig_wins})")
print(f"  Vol quintiles: MF-GJR wins {quint_wins}/{len(quintile_results)} (sig: {quint_sig_wins})")
print(f"  Total: MF-GJR wins {total_wins}/{total_subsamples} subsamples (sig: {total_sig_wins})")
print(f"  Rolling 63-day: MF-GJR wins {frac_mfgjr_wins_rolling*100:.1f}% of windows")
print(f"  Overall robust: {'YES' if robust_overall else 'CONDITIONAL'}")


# ============================================================
# SECTION 11: SAVE RESULTS
# ============================================================
print("\n[11] Saving results...")

elapsed = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR(VIX) Subsample Stability — Paper Robustness',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': float(elapsed),
    'data': {
        'asset': 'SPY',
        'source': 'yfinance',
        'data_period': f'{DATA_START} to {DATA_END}',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'n_oos': int(valid.sum()),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'n_refits': n_refits,
        'seed': 42,
    },
    'full_oos': {
        'qlike_garch': float(qlike_garch_full),
        'qlike_gjr': float(qlike_gjr_full),
        'qlike_mfgjr': float(qlike_mfgjr_full),
        'improvement_mfgjr_vs_gjr_pct': float(improv_mfgjr_vs_gjr),
        'improvement_mfgjr_vs_garch_pct': float(improv_mfgjr_vs_garch),
        'dm_mfgjr_vs_gjr': {
            't_stat': float(dm_mfgjr_vs_gjr_t),
            'p_value': float(dm_mfgjr_vs_gjr_p),
            'significant_harvey': bool(abs(dm_mfgjr_vs_gjr_t) > 3.0),
        },
        'dm_mfgjr_vs_garch': {
            't_stat': float(dm_mfgjr_vs_garch_t),
            'p_value': float(dm_mfgjr_vs_garch_p),
            'significant_harvey': bool(abs(dm_mfgjr_vs_garch_t) > 3.0),
        },
        'dm_gjr_vs_garch': {
            't_stat': float(dm_gjr_vs_garch_t),
            'p_value': float(dm_gjr_vs_garch_p),
        },
    },
    'time_periods': time_results,
    'vix_regimes': regime_results,
    'volatility_quintiles': quintile_results,
    'rolling_qlike': {
        'window_days': 63,
        'mfgjr_win_fraction': float(frac_mfgjr_wins_rolling),
    },
    'robustness_summary': {
        'time_period_wins': f'{time_wins}/{len(time_results)}',
        'time_period_sig_wins': time_sig_wins,
        'regime_wins': f'{regime_wins}/{len(regime_results)}',
        'regime_sig_wins': regime_sig_wins,
        'quintile_wins': f'{quint_wins}/{len(quintile_results)}',
        'quintile_sig_wins': quint_sig_wins,
        'total_wins': f'{total_wins}/{total_subsamples}',
        'total_sig_wins': total_sig_wins,
        'rolling_win_pct': float(frac_mfgjr_wins_rolling * 100),
        'robust_time': robust_time,
        'robust_regime': robust_regime,
        'robust_overall': robust_overall,
    },
    'conclusion': (
        f"MF-GJR(VIX) wins in {total_wins}/{total_subsamples} subsamples "
        f"({total_sig_wins} significant at Harvey |t|>3.0). "
        f"Time periods: {time_wins}/{len(time_results)}, "
        f"VIX regimes: {regime_wins}/{len(regime_results)}, "
        f"Vol quintiles: {quint_wins}/{len(quintile_results)}. "
        f"Rolling 63-day win rate: {frac_mfgjr_wins_rolling*100:.1f}%. "
        f"Overall assessment: {'ROBUST' if robust_overall else 'CONDITIONAL'}."
    ),
    'references': [
        'Engle, Ghysels & Sohn (2013) Stock market volatility and macroeconomic fundamentals, RES 95(3):776-797',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) Volatility forecast comparison using imperfect volatility proxies, J Econometrics 160:246-256',
        'Harvey, Leybourne, Newbold (2016) Tests for forecast encompassing, JBES 34:92-104',
    ],
    'figures': [
        'k942_subsample.png',
        'k942_regime.png',
        'k942_summary.png',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {RESULTS_PATH}")

# Print summary table for paper
print("\n" + "=" * 70)
print("PAPER TABLE: MF-GJR(VIX) Subsample Stability Results")
print("=" * 70)
print(f"\n{'Subsample':<20} {'N':>5} {'QLIKE(GJR)':>12} {'QLIKE(MF)':>12} {'Impr%':>8} {'DM t':>8} {'Sig':>5}")
print("-" * 75)

print("--- Time Periods ---")
for p in period_names:
    r = time_results[p]
    sig = "***" if abs(r['dm_mfgjr_vs_gjr_t']) > 3.0 else ("**" if abs(r['dm_mfgjr_vs_gjr_t']) > 2.0 else ("*" if abs(r['dm_mfgjr_vs_gjr_t']) > 1.65 else ""))
    print(f"  {p:<18} {r['n_obs']:>5} {r['qlike_gjr']:>12.6f} {r['qlike_mfgjr']:>12.6f} {r['improvement_vs_gjr_pct']:>+7.2f}% {r['dm_mfgjr_vs_gjr_t']:>8.3f} {sig:>5}")

print("\n--- VIX Regimes ---")
for reg in regime_names:
    r = regime_results[reg]
    sig = "***" if abs(r['dm_mfgjr_vs_gjr_t']) > 3.0 else ("**" if abs(r['dm_mfgjr_vs_gjr_t']) > 2.0 else ("*" if abs(r['dm_mfgjr_vs_gjr_t']) > 1.65 else ""))
    print(f"  {reg:<18} {r['n_obs']:>5} {r['qlike_gjr']:>12.6f} {r['qlike_mfgjr']:>12.6f} {r['improvement_vs_gjr_pct']:>+7.2f}% {r['dm_mfgjr_vs_gjr_t']:>8.3f} {sig:>5}")

print("\n--- Vol Quintiles ---")
for q in q_names:
    r = quintile_results[q]
    sig = "***" if abs(r['dm_mfgjr_vs_gjr_t']) > 3.0 else ("**" if abs(r['dm_mfgjr_vs_gjr_t']) > 2.0 else ("*" if abs(r['dm_mfgjr_vs_gjr_t']) > 1.65 else ""))
    print(f"  {q:<18} {r['n_obs']:>5} {r['qlike_gjr']:>12.6f} {r['qlike_mfgjr']:>12.6f} {r['improvement_vs_gjr_pct']:>+7.2f}% {r['dm_mfgjr_vs_gjr_t']:>8.3f} {sig:>5}")

print(f"\nFull OOS: QLIKE GJR={qlike_gjr_full:.6f}, MF-GJR={qlike_mfgjr_full:.6f}, "
      f"Impr={improv_mfgjr_vs_gjr:+.2f}%, DM t={dm_mfgjr_vs_gjr_t:.3f}")
print(f"Runtime: {elapsed:.1f}s")
print("\nDone!")
