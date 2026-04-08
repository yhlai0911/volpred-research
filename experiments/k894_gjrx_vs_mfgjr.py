#!/usr/bin/env python3
"""
K894: GJR-X(VIX) vs MF-GJR — Fair Comparison of VIX Usage
============================================================
[提出: Claude, 執行: Claude]

Background:
  K889 found MF-GJR beats GJR for SPY (DM t=-3.30, Harvey PASS, cross-OOS 5/5).
  MF-GJR uses VIX multiplicatively: sigma^2 = exp(theta_0 + theta_1*VIX) * g_t.

  But is the improvement from the multiplicative STRUCTURE or simply from USING VIX?
  A simpler model, GJR-X, adds VIX directly to the variance equation:
    h_t = omega + alpha * r^2_{t-1} + gamma * r^2_{t-1} * I(r<0) + beta * h_{t-1} + delta * VIX_{t-1}

  If GJR-X also beats GJR with Harvey PASS, then MF-GJR's advantage is just from VIX
  information, not the multiplicative structure. If GJR-X doesn't pass Harvey but MF-GJR
  does, then the multiplicative structure matters.

  This is exactly the "GJR-X benchmark" suggested in the PRG paper's limitations.

Models (5 total):
  1. GJR-GARCH(1,1)         — standard baseline
  2. GJR-X(VIX)             — GJR + delta * VIX_{t-1} in variance equation (additive)
  3. GJR-X(VIX^2)           — GJR + delta * VIX^2_{t-1} (quadratic VIX effect)
  4. MF-GJR                 — multiplicative (from K889): sigma^2 = tau_t * g_t
  5. MF-GARCH               — multiplicative without leverage (from K889)

Data:
  - SPY + VIX from yfinance
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - Expanding window, refit every 63 days

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - Pairwise DM tests (10 pairs) with Harvey (2016) |t| > 3.0
  - Spearman rank correlations
  - MCS (Model Confidence Set)
  - VaR 1% + 5% Trinity (Kupiec + Christoffersen + Basel)

Key Comparison:
  GJR-X vs MF-GJR — does multiplicative structure matter beyond VIX info?

Error Log rules applied:
  - DM test: use volpred.stats.model_evaluation (not self-written)
  - GARCH OOS: recursive h[t] = f(h[t-1], r^2[t-1]), no stale variance
  - Student-t: scale term sqrt((df-2)/df)
  - Basel: use standard thresholds

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Engle & Rangel (2008) RFS 21(3):1187-1222
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - Han & Kristensen (2014) GARCH-X model. J Financial Econometrics 12:3-40.

Author: VolPred Research System
Date: 2026-04-05
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm, t as t_dist, chi2
from numba import njit

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K894"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import (
    dm_test, qlike, qlike_pointwise, spearman_corr, model_confidence_set, var_backtest
)

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k894_gjrx_vs_mfgjr_results.json')

# Data parameters
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]

print("=" * 70)
print(f"{EXPERIMENT_ID}: GJR-X(VIX) vs MF-GJR — Fair Comparison of VIX Usage")
print("  Does multiplicative structure matter, or is it just VIX information?")
print("=" * 70)


# ============================================================
# SECTION 1: DATA LOADING (SPY only for focused comparison)
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Download SPY and VIX
spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

prices = spy_raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_close = vix_raw['Close'].rename('VIX')

df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
df = df.join(vix_close, how='left')
df['VIX'] = df['VIX'].ffill()
df = df.dropna()

print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")
print(f"  VIX range: {df['VIX'].min():.2f} - {df['VIX'].max():.2f}, mean={df['VIX'].mean():.2f}")


# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
ret = df['log_ret'].values
desc = {
    'mean': float(np.mean(ret)),
    'std': float(np.std(ret)),
    'skewness': float(stats.skew(ret)),
    'kurtosis': float(stats.kurtosis(ret)),
    'n': int(len(ret))
}
jb_stat, jb_p = stats.jarque_bera(ret)
# ARCH LM test (10 lags)
ret2 = ret ** 2
n_lm = len(ret2) - 10
X_lm = np.column_stack([np.ones(n_lm)] + [ret2[i:i+n_lm] for i in range(10)])
y_lm = ret2[10:]
b_lm = np.linalg.lstsq(X_lm, y_lm, rcond=None)[0]
r2_lm = 1 - np.var(y_lm - X_lm @ b_lm) / np.var(y_lm)
arch_lm = n_lm * r2_lm

print(f"  SPY: Mean={desc['mean']:.6f} Std={desc['std']:.4f} "
      f"Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.2f} "
      f"JB={jb_stat:.0f}(p={jb_p:.1e}) ARCH_LM={arch_lm:.1f}")


# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


@njit(cache=True)
def gjr_garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood. Returns negative LL for minimization."""
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


@njit(cache=True)
def gjr_garch_forecast_oos(params, r_prev, h_prev):
    """One-step GJR-GARCH forecast given previous h and return."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev
    return max(h_next, 1e-10)


@njit(cache=True)
def gjrx_loglik(params, returns, exog):
    """GJR-X log-likelihood with exogenous variable in variance equation.

    h_t = omega + alpha * r^2_{t-1} + gamma * r^2_{t-1} * I(r<0) + beta * h_{t-1} + delta * exog_{t-1}

    The exog is VIX (level) or VIX^2 (quadratic).
    Constraint: delta >= 0 enforced via bounds, not here.
    """
    omega, alpha, gamma, beta, delta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    ll = 0.0

    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1] + delta * exog[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])

    return -ll


@njit(cache=True)
def gjrx_forecast_oos(params, r_prev, h_prev, exog_prev):
    """One-step GJR-X forecast."""
    omega, alpha, gamma, beta, delta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev + delta * exog_prev
    return max(h_next, 1e-10)


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


def fit_gjrx(returns, exog):
    """Fit GJR-X model with exogenous variable in variance equation.

    h_t = omega + alpha * r^2_{t-1} + gamma * r^2_{t-1} * I(r<0) + beta * h_{t-1} + delta * exog_{t-1}

    The exog variable is pre-scaled (VIX level scaled to variance units, or VIX^2).
    """
    best_ll = np.inf
    best_params = None

    # Scale delta initial values based on typical VIX level (~20) and variance (~0.0002)
    # delta * VIX ~ delta * 20 should be on the order of 1e-5 to 1e-4
    # So delta ~ 1e-6 to 1e-5

    starts = [
        [1e-6, 0.05, 0.05, 0.88, 1e-7],
        [1e-6, 0.08, 0.10, 0.85, 5e-7],
        [1e-5, 0.03, 0.03, 0.90, 1e-6],
        [5e-6, 0.06, 0.08, 0.86, 2e-7],
        [1e-6, 0.04, 0.06, 0.89, 5e-8],
        [1e-6, 0.05, 0.05, 0.88, 1e-8],
    ]

    # delta >= 0: VIX should increase, not decrease, conditional variance
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.0, 0.3), (0.3, 0.999), (0.0, 1e-3)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: gjrx_loglik(p, returns, exog),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 1000}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, -best_ll


def fit_mf_garch(returns, log_vix, model_type='garch'):
    """Fit MF-GARCH or MF-GJR via joint MLE.

    Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
    Short-run: g_t = GARCH(1,1) or GJR on standardized returns u_t = r_t/sqrt(tau_t)
    Total: sigma^2_t = tau_t * g_t
    """
    n = len(returns)
    assert len(log_vix) == n

    # OLS for initial theta
    r2_positive = np.maximum(returns ** 2, 1e-16)
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
            [-16.0, 2.3, 0.001, 0.09, 0.87],  # near K889 SPY solution
        ]
        bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]
    else:
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.85],
            [-8.0, 0.5, 0.05, 0.90],
            [-7.0, 0.8, 0.03, 0.93],
            [-18.0, 3.0, 0.03, 0.96],  # near K889 SPY solution
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


def reconstruct_gjr_h(params, returns):
    """Reconstruct full in-sample h series for GJR-GARCH."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        h[t] = max(h[t], 1e-10)
    return h


def reconstruct_gjrx_h(params, returns, exog):
    """Reconstruct full in-sample h series for GJR-X."""
    omega, alpha, gamma, beta, delta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1] + delta * exog[t-1]
        h[t] = max(h[t], 1e-10)
    return h


def reconstruct_mf_components(params, returns, log_vix, model_type='garch'):
    """Reconstruct in-sample tau, g, sigma^2 for MF model."""
    n = len(returns)
    if model_type == 'gjr':
        theta0, theta1, alpha, gamma, beta = params
    else:
        theta0, theta1, alpha, beta = params
        gamma = 0.0

    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]
    log_tau = theta0 + theta1 * log_vix_lag
    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)

    u = returns / np.sqrt(tau)
    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
        g[t] = max(g[t], 1e-10)

    sigma2 = tau * g
    return sigma2, g, tau


# ============================================================
# SECTION 4: ROLLING OOS EVALUATION
# ============================================================
print("\n[4] Rolling OOS evaluation...")

ret_all = df['log_ret'].values
vix_all = df['VIX'].values
log_vix_all = np.log(vix_all)
vix_sq_all = (vix_all / 100.0) ** 2  # VIX^2 scaled: VIX=20 -> (0.20)^2=0.04 -> delta * 0.04
r2_all = ret_all ** 2
dates = df.index

# Find OOS start
oos_mask = dates >= OOS_START
oos_start_idx = np.argmax(oos_mask)
if oos_start_idx < WINDOW:
    oos_start_idx = WINDOW
n_oos = len(ret_all) - oos_start_idx

print(f"  OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")
print(f"  OOS days: {n_oos}")

# Model names
MODELS = ['GJR', 'GJR-X(VIX)', 'GJR-X(VIX^2)', 'MF-GJR', 'MF-GARCH']

# Storage
forecasts = {m: np.full(n_oos, np.nan) for m in MODELS}
oos_returns = ret_all[oos_start_idx:]
oos_r2 = r2_all[oos_start_idx:]
oos_dates = dates[oos_start_idx:]

# For VIX exog in GJR-X: use VIX level (already lagged in the variance equation)
# For GJR-X(VIX^2): use squared VIX level

# Rolling estimation state
last_gjr_params = None
last_gjr_h = None

last_gjrx_vix_params = None
last_gjrx_vix_h = None

last_gjrx_vix2_params = None
last_gjrx_vix2_h = None

last_mfgjr_params = None
last_mfgjr_g = None
tau_prev_mfgjr = None

last_mfgarch_params = None
last_mfgarch_g = None
tau_prev_mfgarch = None

n_refits = 0

print("  Running rolling OOS...")
for t in range(n_oos):
    idx = oos_start_idx + t
    need_refit = (t == 0) or (t % REFIT_EVERY == 0)

    # Training window (expanding with max WINDOW)
    train_start = max(0, idx - WINDOW)
    train_ret = ret_all[train_start:idx]
    train_vix = vix_all[train_start:idx]
    train_log_vix = log_vix_all[train_start:idx]
    train_vix_sq = vix_sq_all[train_start:idx]

    if need_refit:
        n_refits += 1
        if t % (REFIT_EVERY * 5) == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{n_refits} at t={t}/{n_oos} ({elapsed:.0f}s)")

        # ---- Fit GJR-GARCH ----
        gjr_params, gjr_ll = fit_gjr_garch(train_ret)
        if gjr_params is not None:
            last_gjr_params = gjr_params
            h_arr = reconstruct_gjr_h(gjr_params, train_ret)
            last_gjr_h = h_arr[-1]

        # ---- Fit GJR-X(VIX) ----
        gjrx_vix_params, gjrx_vix_ll = fit_gjrx(train_ret, train_vix)
        if gjrx_vix_params is not None:
            last_gjrx_vix_params = gjrx_vix_params
            h_arr = reconstruct_gjrx_h(gjrx_vix_params, train_ret, train_vix)
            last_gjrx_vix_h = h_arr[-1]

        # ---- Fit GJR-X(VIX^2) ----
        gjrx_vix2_params, gjrx_vix2_ll = fit_gjrx(train_ret, train_vix_sq)
        if gjrx_vix2_params is not None:
            last_gjrx_vix2_params = gjrx_vix2_params
            h_arr = reconstruct_gjrx_h(gjrx_vix2_params, train_ret, train_vix_sq)
            last_gjrx_vix2_h = h_arr[-1]

        # ---- Fit MF-GJR ----
        mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_log_vix, model_type='gjr')
        if mfgjr_params is not None:
            last_mfgjr_params = mfgjr_params
            _, g_arr, _ = reconstruct_mf_components(mfgjr_params, train_ret, train_log_vix, 'gjr')
            last_mfgjr_g = g_arr[-1]

        # ---- Fit MF-GARCH ----
        mfg_params, mfg_ll = fit_mf_garch(train_ret, train_log_vix, model_type='garch')
        if mfg_params is not None:
            last_mfgarch_params = mfg_params
            _, g_arr, _ = reconstruct_mf_components(mfg_params, train_ret, train_log_vix, 'garch')
            last_mfgarch_g = g_arr[-1]

    # ======= Generate one-step-ahead forecasts =======

    # --- GJR-GARCH: recursive h[t] = f(h[t-1], r^2[t-1]) ---
    if last_gjr_params is not None and last_gjr_h is not None:
        if t > 0:
            last_gjr_h = gjr_garch_forecast_oos(last_gjr_params, ret_all[idx-1], last_gjr_h)
        forecasts['GJR'][t] = last_gjr_h

    # --- GJR-X(VIX): recursive h[t] = f(h[t-1], r^2[t-1], VIX[t-1]) ---
    if last_gjrx_vix_params is not None and last_gjrx_vix_h is not None:
        if t > 0:
            last_gjrx_vix_h = gjrx_forecast_oos(
                last_gjrx_vix_params, ret_all[idx-1], last_gjrx_vix_h, vix_all[idx-1]
            )
        forecasts['GJR-X(VIX)'][t] = last_gjrx_vix_h

    # --- GJR-X(VIX^2): recursive h[t] = f(h[t-1], r^2[t-1], VIX^2[t-1]) ---
    if last_gjrx_vix2_params is not None and last_gjrx_vix2_h is not None:
        if t > 0:
            last_gjrx_vix2_h = gjrx_forecast_oos(
                last_gjrx_vix2_params, ret_all[idx-1], last_gjrx_vix2_h, vix_sq_all[idx-1]
            )
        forecasts['GJR-X(VIX^2)'][t] = last_gjrx_vix2_h

    # --- MF-GJR: tau from VIX, g recursive on standardized ---
    if last_mfgjr_params is not None:
        theta0, theta1, alpha_mf, gamma_mf, beta_mf = last_mfgjr_params
        log_tau_t = theta0 + theta1 * log_vix_all[idx-1]
        tau_t = np.exp(log_tau_t)
        tau_t = max(tau_t, 1e-16)

        if t == 0:
            g_t = last_mfgjr_g if last_mfgjr_g is not None else 1.0
        else:
            u_prev = ret_all[idx-1] / np.sqrt(tau_prev_mfgjr)
            omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
            asym = gamma_mf * u_prev**2 if u_prev < 0 else 0.0
            g_t = omega_g + alpha_mf * u_prev**2 + asym + beta_mf * last_mfgjr_g
            g_t = max(g_t, 1e-10)

        tau_prev_mfgjr = tau_t
        last_mfgjr_g = g_t
        forecasts['MF-GJR'][t] = tau_t * g_t

    # --- MF-GARCH: same without leverage ---
    if last_mfgarch_params is not None:
        theta0, theta1, alpha_mf, beta_mf = last_mfgarch_params
        log_tau_t = theta0 + theta1 * log_vix_all[idx-1]
        tau_t = np.exp(log_tau_t)
        tau_t = max(tau_t, 1e-16)

        if t == 0:
            g_t = last_mfgarch_g if last_mfgarch_g is not None else 1.0
        else:
            u_prev = ret_all[idx-1] / np.sqrt(tau_prev_mfgarch)
            omega_g = 1.0 - alpha_mf - beta_mf
            g_t = omega_g + alpha_mf * u_prev**2 + beta_mf * last_mfgarch_g
            g_t = max(g_t, 1e-10)

        tau_prev_mfgarch = tau_t
        last_mfgarch_g = g_t
        forecasts['MF-GARCH'][t] = tau_t * g_t

print(f"  Total refits: {n_refits}")


# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

# 5a: QLIKE on r^2 (Patton 2011)
print("\n  [5a] QLIKE on r^2:")
qlike_results = {}
for m in MODELS:
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0)
    if valid.sum() > 100:
        qlike_results[m] = qlike(oos_r2[valid], f[valid])
    else:
        qlike_results[m] = np.nan

gjr_qlike = qlike_results['GJR']
qlike_pct = {}
for m in MODELS:
    if np.isfinite(qlike_results[m]) and np.isfinite(gjr_qlike) and gjr_qlike > 0:
        qlike_pct[m] = round(((qlike_results[m] - gjr_qlike) / gjr_qlike) * 100, 3)
    else:
        qlike_pct[m] = np.nan

for m in MODELS:
    marker = " ***" if m != 'GJR' and qlike_results.get(m, np.nan) < gjr_qlike else ""
    print(f"    {m:20s}: QLIKE={qlike_results.get(m, np.nan):.6f}  "
          f"({qlike_pct.get(m, 0):+.3f}% vs GJR){marker}")

# 5b: Spearman rank correlation
print("\n  [5b] Spearman rank correlation:")
spearman_results = {}
for m in MODELS:
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0)
    if valid.sum() > 100:
        rho, p = spearman_corr(oos_r2[valid], f[valid])
        spearman_results[m] = {'rho': round(rho, 4), 'p': round(p, 6)}
    else:
        spearman_results[m] = {'rho': np.nan, 'p': np.nan}
    print(f"    {m:20s}: rho={spearman_results[m]['rho']:.4f}  p={spearman_results[m]['p']:.1e}")

# 5c: DM tests (all pairwise)
print("\n  [5c] Pairwise DM tests (Harvey |t|>3.0):")

# Compute pointwise QLIKE losses for DM
pw_losses = {}
for m in MODELS:
    f = forecasts[m]
    pw_losses[m] = qlike_pointwise(oos_r2, f)

dm_results = {}
for i, m1 in enumerate(MODELS):
    dm_results[m1] = {}
    for j, m2 in enumerate(MODELS):
        if i == j:
            dm_results[m1][m2] = {'t': 0.0, 'p': 1.0, 'significant_harvey': False}
            continue
        if i < j:
            t_stat, p_val = dm_test(pw_losses[m1], pw_losses[m2])
            sig = abs(t_stat) > 3.0
            dm_results[m1][m2] = {
                't': round(t_stat, 3),
                'p': round(p_val, 4),
                'significant_harvey': sig
            }
        else:
            # Reverse sign from already computed pair
            t_stat = -dm_results[m2][m1]['t']
            p_val = dm_results[m2][m1]['p']
            sig = abs(t_stat) > 3.0
            dm_results[m1][m2] = {
                't': round(t_stat, 3),
                'p': round(p_val, 4),
                'significant_harvey': sig
            }

# Print DM test table
print(f"\n    {'':20s} ", end="")
for m in MODELS:
    print(f"{m:>14s}", end="")
print()
for m1 in MODELS:
    print(f"    {m1:20s} ", end="")
    for m2 in MODELS:
        if m1 == m2:
            print(f"{'---':>14s}", end="")
        else:
            t = dm_results[m1][m2]['t']
            marker = " ***" if dm_results[m1][m2]['significant_harvey'] else ""
            print(f"{t:>10.3f}{marker:4s}", end="")
    print()

# Key comparison: GJR-X(VIX) vs MF-GJR
print("\n    KEY COMPARISONS:")

# vs GJR baseline
for m in ['GJR-X(VIX)', 'GJR-X(VIX^2)', 'MF-GJR', 'MF-GARCH']:
    t = dm_results[m]['GJR']['t']
    p = dm_results[m]['GJR']['p']
    sig = dm_results[m]['GJR']['significant_harvey']
    print(f"    {m} vs GJR: DM t={t:.3f}, p={p:.4f}, Harvey={'PASS' if sig else 'FAIL'}")

# GJR-X vs MF-GJR
t = dm_results['GJR-X(VIX)']['MF-GJR']['t']
p = dm_results['GJR-X(VIX)']['MF-GJR']['p']
sig = dm_results['GJR-X(VIX)']['MF-GJR']['significant_harvey']
print(f"\n    GJR-X(VIX) vs MF-GJR: DM t={t:.3f}, p={p:.4f}, Harvey={'PASS' if sig else 'FAIL'}")

t = dm_results['GJR-X(VIX^2)']['MF-GJR']['t']
p = dm_results['GJR-X(VIX^2)']['MF-GJR']['p']
sig = dm_results['GJR-X(VIX^2)']['MF-GJR']['significant_harvey']
print(f"    GJR-X(VIX^2) vs MF-GJR: DM t={t:.3f}, p={p:.4f}, Harvey={'PASS' if sig else 'FAIL'}")


# 5d: Model Confidence Set
print("\n  [5d] Model Confidence Set (alpha=0.10):")
mcs_result = model_confidence_set(pw_losses, alpha=0.10, n_boot=5000, seed=42)
print(f"    MCS members: {mcs_result['members']}")
print(f"    MCS size: {mcs_result['size']}")


# 5e: VaR Trinity Test (1% and 5%)
print("\n  [5e] VaR backtesting (Kupiec + Christoffersen + Basel):")
var_results = {}

for alpha_var in ALPHA_LEVELS:
    var_results[str(alpha_var)] = {}
    z_normal = norm.ppf(alpha_var)

    for m in MODELS:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() < 100:
            var_results[str(alpha_var)][m] = {'error': 'insufficient data'}
            continue

        sigma = np.sqrt(f)
        var_threshold = sigma * z_normal  # negative
        violations = oos_returns < var_threshold
        n_violations = int(violations.sum())
        n_total = int(valid.sum())
        rate = n_violations / n_total
        expected = alpha_var

        # Kupiec LR test (unconditional coverage)
        # LR = -2 * [n0*log(1-p0) + n1*log(p0) - n0*log(1-p_hat) - n1*log(p_hat)]
        # where p0 = expected, p_hat = observed rate, n0 = no-violation, n1 = violations
        n0 = n_total - n_violations
        n1 = n_violations
        if n1 == 0 or n1 == n_total:
            kupiec_p = 0.0
        else:
            ll_null = n0 * np.log(1 - expected) + n1 * np.log(expected)
            ll_alt = n0 * np.log(1 - rate) + n1 * np.log(rate)
            lr = -2 * (ll_null - ll_alt)
            lr = max(lr, 0)
            kupiec_p = 1 - chi2.cdf(lr, 1)

        # Christoffersen conditional coverage
        v = violations.astype(int)
        n00 = int(np.sum((v[:-1] == 0) & (v[1:] == 0)))
        n01 = int(np.sum((v[:-1] == 0) & (v[1:] == 1)))
        n10 = int(np.sum((v[:-1] == 1) & (v[1:] == 0)))
        n11 = int(np.sum((v[:-1] == 1) & (v[1:] == 1)))

        if (n00 + n01) > 0 and (n10 + n11) > 0 and n01 > 0 and n10 > 0:
            p01 = n01 / (n00 + n01)
            p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0
            p_hat = (n01 + n11) / (n00 + n01 + n10 + n11)

            if 0 < p_hat < 1 and 0 < p01 < 1:
                ll_ind = (n00 + n10) * np.log(1 - p_hat) + (n01 + n11) * np.log(p_hat)
                ll_dep = n00 * np.log(1 - p01) + n01 * np.log(p01)
                if (n10 + n11) > 0 and 0 < p11 < 1:
                    ll_dep += n10 * np.log(1 - p11) + n11 * np.log(p11)
                elif n10 > 0:
                    ll_dep += n10 * np.log(1.0)
                lr_cc = -2 * (ll_ind - ll_dep)
                lr_cc = max(lr_cc, 0)
                cc_p = 1 - chi2.cdf(lr_cc, 1)
            else:
                cc_p = 1.0
        else:
            cc_p = 1.0

        # Basel traffic light (250-day lookback standard)
        if alpha_var == 0.01:
            if n_violations <= int(0.01 * n_total * 1.5):
                basel = "GREEN"
            elif n_violations <= int(0.01 * n_total * 2.5):
                basel = "YELLOW"
            else:
                basel = "RED"
        else:
            if n_violations <= int(0.05 * n_total * 1.3):
                basel = "GREEN"
            elif n_violations <= int(0.05 * n_total * 1.8):
                basel = "YELLOW"
            else:
                basel = "RED"

        # Trinity: all three pass
        trinity = kupiec_p > 0.05 and cc_p > 0.05 and basel == "GREEN"

        var_results[str(alpha_var)][m] = {
            'violations': n_violations,
            'total': n_total,
            'rate': round(rate, 4),
            'expected_rate': alpha_var,
            'kupiec_p': round(kupiec_p, 4),
            'cc_p': round(cc_p, 4),
            'basel': basel,
            'trinity': trinity
        }

    print(f"\n    VaR {alpha_var*100:.0f}%:")
    for m in MODELS:
        r = var_results[str(alpha_var)][m]
        if 'error' in r:
            print(f"      {m:20s}: ERROR - {r['error']}")
        else:
            print(f"      {m:20s}: violations={r['violations']}/{r['total']} "
                  f"(rate={r['rate']:.4f}, exp={alpha_var}) "
                  f"Kupiec p={r['kupiec_p']:.4f} CC p={r['cc_p']:.4f} "
                  f"Basel={r['basel']} Trinity={r['trinity']}")


# ============================================================
# SECTION 6: PARAMETER ANALYSIS
# ============================================================
print("\n[6] Final parameter estimates...")

# Get the last fitted parameters
param_summary = {}

if last_gjr_params is not None:
    o, a, g, b = last_gjr_params
    param_summary['GJR'] = {
        'omega': float(o), 'alpha': float(a), 'gamma': float(g), 'beta': float(b),
        'persistence': float(a + g/2 + b)
    }
    print(f"  GJR: omega={o:.2e} alpha={a:.4f} gamma={g:.4f} beta={b:.4f} "
          f"persist={a+g/2+b:.4f}")

if last_gjrx_vix_params is not None:
    o, a, g, b, d = last_gjrx_vix_params
    param_summary['GJR-X(VIX)'] = {
        'omega': float(o), 'alpha': float(a), 'gamma': float(g),
        'beta': float(b), 'delta': float(d),
        'persistence': float(a + g/2 + b),
        'delta_contribution_at_VIX20': float(d * 20),
        'delta_contribution_at_VIX30': float(d * 30),
    }
    print(f"  GJR-X(VIX): omega={o:.2e} alpha={a:.4f} gamma={g:.4f} beta={b:.4f} "
          f"delta={d:.2e} persist={a+g/2+b:.4f}")
    print(f"    delta*VIX contribution: at VIX=20: {d*20:.2e}, at VIX=30: {d*30:.2e}, "
          f"at VIX=50: {d*50:.2e}")

if last_gjrx_vix2_params is not None:
    o, a, g, b, d = last_gjrx_vix2_params
    param_summary['GJR-X(VIX^2)'] = {
        'omega': float(o), 'alpha': float(a), 'gamma': float(g),
        'beta': float(b), 'delta': float(d),
        'persistence': float(a + g/2 + b),
    }
    print(f"  GJR-X(VIX^2): omega={o:.2e} alpha={a:.4f} gamma={g:.4f} beta={b:.4f} "
          f"delta={d:.2e} persist={a+g/2+b:.4f}")

if last_mfgjr_params is not None:
    t0, t1, a, g, b = last_mfgjr_params
    param_summary['MF-GJR'] = {
        'theta_0': float(t0), 'theta_1': float(t1),
        'alpha': float(a), 'gamma': float(g), 'beta': float(b),
        'persistence_g': float(a + g/2 + b)
    }
    print(f"  MF-GJR: theta_0={t0:.3f} theta_1={t1:.3f} alpha={a:.4f} gamma={g:.4f} "
          f"beta={b:.4f} persist_g={a+g/2+b:.4f}")

if last_mfgarch_params is not None:
    t0, t1, a, b = last_mfgarch_params
    param_summary['MF-GARCH'] = {
        'theta_0': float(t0), 'theta_1': float(t1),
        'alpha': float(a), 'beta': float(b),
        'persistence_g': float(a + b)
    }
    print(f"  MF-GARCH: theta_0={t0:.3f} theta_1={t1:.3f} alpha={a:.4f} "
          f"beta={b:.4f} persist_g={a+b:.4f}")


# ============================================================
# SECTION 7: INTERPRETATION
# ============================================================
print("\n" + "=" * 70)
print("[7] INTERPRETATION: Does multiplicative structure matter?")
print("=" * 70)

# Key question: GJR-X(VIX) vs GJR — does simply adding VIX help?
gjrx_vs_gjr_t = dm_results['GJR-X(VIX)']['GJR']['t']
gjrx_vs_gjr_sig = dm_results['GJR-X(VIX)']['GJR']['significant_harvey']
gjrx_qlike_improve = qlike_pct.get('GJR-X(VIX)', 0)

# Key question: GJR-X(VIX) vs MF-GJR — structure or information?
gjrx_vs_mfgjr_t = dm_results['GJR-X(VIX)']['MF-GJR']['t']
gjrx_vs_mfgjr_sig = dm_results['GJR-X(VIX)']['MF-GJR']['significant_harvey']

# MF-GJR vs GJR (replication check from K889)
mfgjr_vs_gjr_t = dm_results['MF-GJR']['GJR']['t']
mfgjr_vs_gjr_sig = dm_results['MF-GJR']['GJR']['significant_harvey']

print(f"\n  (A) Does simply adding VIX to GJR help?")
print(f"      GJR-X(VIX) vs GJR: DM t={gjrx_vs_gjr_t:.3f}, "
      f"Harvey {'PASS' if gjrx_vs_gjr_sig else 'FAIL'}")
print(f"      QLIKE improvement: {gjrx_qlike_improve:+.3f}%")

if gjrx_vs_gjr_sig:
    print(f"      --> YES, additive VIX alone is enough to beat GJR at Harvey level")
else:
    print(f"      --> NO, additive VIX alone is NOT enough at Harvey level")

print(f"\n  (B) MF-GJR vs GJR (replication from K889):")
print(f"      DM t={mfgjr_vs_gjr_t:.3f}, Harvey {'PASS' if mfgjr_vs_gjr_sig else 'FAIL'}")

print(f"\n  (C) Does multiplicative structure improve over additive VIX?")
print(f"      GJR-X(VIX) vs MF-GJR: DM t={gjrx_vs_mfgjr_t:.3f}, "
      f"Harvey {'PASS' if gjrx_vs_mfgjr_sig else 'FAIL'}")
if gjrx_vs_mfgjr_t > 0:
    print(f"      --> MF-GJR is BETTER (negative loss diff)")
    if gjrx_vs_mfgjr_sig:
        print(f"      --> SIGNIFICANTLY better — multiplicative structure adds value beyond VIX info")
    else:
        print(f"      --> But NOT significantly at Harvey level")
elif gjrx_vs_mfgjr_t < 0:
    print(f"      --> GJR-X is BETTER (or indistinguishable)")
    print(f"      --> Multiplicative structure does NOT improve over simple additive VIX")

# Summary determination
if gjrx_vs_gjr_sig and mfgjr_vs_gjr_sig:
    if gjrx_vs_mfgjr_sig:
        conclusion = "Both VIX info AND multiplicative structure matter. MF-GJR > GJR-X > GJR."
    else:
        conclusion = "VIX information matters. Multiplicative vs additive structure is NS. Both GJR-X and MF-GJR beat GJR."
elif not gjrx_vs_gjr_sig and mfgjr_vs_gjr_sig:
    conclusion = "Multiplicative STRUCTURE matters. Simply adding VIX is not enough — the decomposition is key."
elif gjrx_vs_gjr_sig and not mfgjr_vs_gjr_sig:
    conclusion = "Additive VIX is sufficient. MF-GJR may have been favored by sample variation in K889."
else:
    conclusion = "Neither approach achieves Harvey significance. The K889 result may not replicate."

print(f"\n  CONCLUSION: {conclusion}")

# Check MCS membership
print(f"\n  MCS membership: {mcs_result['members']}")
mcs_has_gjrx = 'GJR-X(VIX)' in mcs_result['members']
mcs_has_mfgjr = 'MF-GJR' in mcs_result['members']
mcs_has_gjr = 'GJR' in mcs_result['members']
print(f"    GJR in MCS: {mcs_has_gjr}")
print(f"    GJR-X(VIX) in MCS: {mcs_has_gjrx}")
print(f"    MF-GJR in MCS: {mcs_has_mfgjr}")


# ============================================================
# SECTION 8: SAVE RESULTS
# ============================================================
print("\n[8] Saving results...")

runtime = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'GJR-X(VIX) vs MF-GJR: Fair Comparison of VIX Usage',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(runtime, 1),
    'methodology': {
        'models': MODELS,
        'gjr_x': 'h_t = omega + alpha*r^2_{t-1} + gamma*r^2_{t-1}*I(r<0) + beta*h_{t-1} + delta*VIX_{t-1}',
        'gjr_x_vix2': 'h_t = omega + alpha*r^2_{t-1} + gamma*r^2_{t-1}*I(r<0) + beta*h_{t-1} + delta*(VIX/100)^2_{t-1}',
        'mf_gjr_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_gjr_short_run': 'g_t = (1-a-gamma/2-b) + a*u^2_{t-1} + gamma*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'estimation': f'Expanding window (max={WINDOW}), refit every {REFIT_EVERY} days, MLE with multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman, MCS, VaR Trinity',
        'key_question': 'Is MF-GJR improvement from multiplicative STRUCTURE or from USING VIX?'
    },
    'data': {
        'source': 'yfinance',
        'asset': 'SPY',
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'oos_end': str(oos_dates[-1].date()),
        'n_oos': int(n_oos),
        'n_refits': int(n_refits),
        'window': WINDOW,
        'refit_every': REFIT_EVERY
    },
    'diagnostics': desc,
    'results': {
        'qlike': {m: round(v, 6) for m, v in qlike_results.items()},
        'qlike_pct_vs_gjr': qlike_pct,
        'spearman': spearman_results,
        'dm_pairwise': dm_results,
        'mcs': {
            'members': mcs_result['members'],
            'size': mcs_result['size'],
            'method': mcs_result.get('method', 'unknown')
        },
        'var': var_results,
        'parameters': param_summary
    },
    'key_comparisons': {
        'gjrx_vix_vs_gjr': {
            'dm_t': round(gjrx_vs_gjr_t, 3),
            'harvey_pass': gjrx_vs_gjr_sig,
            'qlike_improvement_pct': gjrx_qlike_improve,
            'interpretation': 'Does simply adding VIX help?'
        },
        'mfgjr_vs_gjr': {
            'dm_t': round(mfgjr_vs_gjr_t, 3),
            'harvey_pass': mfgjr_vs_gjr_sig,
            'qlike_improvement_pct': qlike_pct.get('MF-GJR', 0),
            'interpretation': 'MF-GJR vs GJR (K889 replication)'
        },
        'gjrx_vix_vs_mfgjr': {
            'dm_t': round(gjrx_vs_mfgjr_t, 3),
            'harvey_pass': gjrx_vs_mfgjr_sig,
            'interpretation': 'Does multiplicative structure matter beyond VIX info?'
        },
        'gjrx_vix2_vs_mfgjr': {
            'dm_t': round(dm_results['GJR-X(VIX^2)']['MF-GJR']['t'], 3),
            'harvey_pass': dm_results['GJR-X(VIX^2)']['MF-GJR']['significant_harvey'],
            'interpretation': 'Quadratic VIX vs multiplicative'
        }
    },
    'conclusion': conclusion,
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Engle & Rangel (2008) RFS 21(3):1187-1222',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104',
        'Han & Kristensen (2014) GARCH-X model. J Financial Econometrics 12:3-40'
    ]
}

# Convert any numpy types for JSON serialization
def convert_numpy(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, dict):
        return {k: convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy(v) for v in obj]
    return obj

results = convert_numpy(results)

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {RESULTS_PATH}")
print(f"  Runtime: {runtime:.1f}s")

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print(f"  CONCLUSION: {conclusion}")
print("=" * 70)
