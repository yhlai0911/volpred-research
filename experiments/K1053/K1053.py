#!/usr/bin/env python3
"""
K1053: VIX Term Structure Slope as Volatility Predictor
=======================================================
[提出: Claude, 執行: Claude]

Motivation:
  K975 found "VIX term structure slope ★ — significant vol predictor" but details unclear.
  K976 found "MF2+VIX slope — NULL at daily freq (horizon mismatch)".
  K1015 found VIX9D+VIX3M dual-factor NULL (collinear with VIX).
  Paper 9 Table 8 shows VIX/VIX3M ratio has DM t=3.53 (Harvey PASS) in sensitivity analysis.

  Key question: Does the slope add INCREMENTAL information beyond VIX level in A4f?
  When VIX/VIX3M > 1 (backwardation), near-term fear is elevated relative to 3-month.
  When VIX/VIX3M < 1 (contango), near-term is calm relative to 3-month expectations.

Method:
  Compare 5 models (SPY, OOS 2019-2026, window=2000, refit/63d, seed=42):

  M1: A4f-VIX (baseline):        tau_t = theta0 + theta1 * VIX^2_{t-1}
  M2: A4f-VIX + Slope Ratio:     tau_t = theta0 + theta1 * VIX^2_{t-1} + theta2 * (VIX/VIX3M)_{t-1}
  M3: A4f-VIX + Spread Squared:  tau_t = theta0 + theta1 * VIX^2_{t-1} + theta3 * (VIX - VIX3M)^2_{t-1}
  M4: A4f-VIX9D (best variant):  tau_t = theta0 + theta1 * VIX9D^2_{t-1}
  M5: GJR-GARCH(1,1) (benchmark)

References:
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.
  - Mixon (2007). The implied volatility term structure. J Deriv 15(2):29-46.
  - Campa & Chang (1995). Testing the expectations hypothesis on the term
    structure of volatilities. J Finance 50(2):529-547.
  - Lu & Zhu (2010). Volatility components. J Financial Econometrics 8(4):431-456.

Data: SPY 2005-2026, ^VIX, ^VIX3M, ^VIX9D from yfinance. OOS: 2019-01-01 to latest.
Evaluation: QLIKE on r^2 (Patton 2011), DM test (Harvey |t| > 3.0), Spearman rho.

Author: VolPred Research System
Date: 2026-04-11
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

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1053"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'K1053_results.json')
CHART_PATH = os.path.join(SCRIPT_DIR, 'K1053_term_structure.png')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-11'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print(f"{EXPERIMENT_ID}: VIX Term Structure Slope as Volatility Predictor")
print("  Does VIX/VIX3M slope add info beyond VIX level in A4f?")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

tickers = ['SPY', '^VIX', '^VIX3M', '^VIX9D']
raw_data = {}
for tkr in tickers:
    d = yf.download(tkr, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    raw_data[tkr] = d['Close'].copy()
    print(f"  {tkr}: {d.index[0].strftime('%Y-%m-%d')} to {d.index[-1].strftime('%Y-%m-%d')}, n={len(d)}")

# Build aligned DataFrame
df = pd.DataFrame({
    'price': raw_data['SPY'],
    'VIX': raw_data['^VIX'],
    'VIX3M': raw_data['^VIX3M'],
    'VIX9D': raw_data['^VIX9D'],
})
df['log_ret'] = np.log(df['price'] / df['price'].shift(1))

# Drop rows where essential columns are NaN
df = df.dropna(subset=['log_ret', 'VIX', 'VIX3M'])
print(f"\n  Aligned dataset (VIX+VIX3M): {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")

# Also track VIX9D availability
vix9d_available = df['VIX9D'].notna()
print(f"  VIX9D available: {vix9d_available.sum()} of {len(df)} days")

# Compute derived features
df['slope_ratio'] = df['VIX'] / df['VIX3M']           # VIX/VIX3M
df['spread'] = df['VIX'] - df['VIX3M']                # VIX - VIX3M
df['spread_sq'] = df['spread'] ** 2                    # (VIX - VIX3M)^2
df['r2'] = df['log_ret'] ** 2

# Descriptive statistics
print("\n[1b] Descriptive statistics of term structure features (full sample):")
for col in ['VIX', 'VIX3M', 'slope_ratio', 'spread']:
    vals = df[col].dropna()
    print(f"  {col}: mean={vals.mean():.4f}, std={vals.std():.4f}, "
          f"min={vals.min():.4f}, max={vals.max():.4f}, skew={vals.skew():.3f}")

# Contango/Backwardation stats
backwardation_pct = (df['slope_ratio'] > 1.0).mean() * 100
print(f"\n  Backwardation (VIX > VIX3M): {backwardation_pct:.1f}% of days")
print(f"  Contango (VIX < VIX3M):      {100 - backwardation_pct:.1f}% of days")

# Correlation of slope with next-day r^2
slope_lag = df['slope_ratio'].shift(1)
spread_lag = df['spread'].shift(1)
corr_slope_r2 = df['r2'].corr(slope_lag)
corr_spread_r2 = df['r2'].corr(spread_lag)
corr_vix_r2 = df['r2'].corr(df['VIX'].shift(1))
print(f"\n  Pearson corr(VIX_lag, r^2):       {corr_vix_r2:.4f}")
print(f"  Pearson corr(slope_lag, r^2):     {corr_slope_r2:.4f}")
print(f"  Pearson corr(spread_lag, r^2):    {corr_spread_r2:.4f}")

# OOS mask
oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"\n  OOS: {OOS_START} onwards, n_oos={n_oos}")

# Arrays for model fitting
ret = df['log_ret'].values
vix_arr = df['VIX'].values
vix3m_arr = df['VIX3M'].values
vix9d_arr = df['VIX9D'].values
slope_arr = df['slope_ratio'].values
spread_sq_arr = df['spread_sq'].values
r2_arr = df['r2'].values
log_vix = np.log(np.maximum(vix_arr, 1.0))

# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[2] Model implementations...")


# --- GJR-GARCH(1,1) (M5) ---
def gjr_loglik(params, returns):
    """Standard GJR-GARCH(1,1) negative log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    ll = 0.0
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) with multiple starting points."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_filter(params, returns):
    """Run GJR filter, return variance series."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f base: tau = theta0 + theta1 * X^2, multiplicative GARCH-X ---
def fit_a4f_generic(returns, x_vals, n_tau_params, tau_func, param_starts, param_bounds):
    """
    Generic A4f fitter for multiplicative GARCH-X.

    sigma2_t = tau_t * g_t
    g_t = omega_g + alpha * u_{t-1}^2 + gamma * I(u<0) * u_{t-1}^2 + beta * g_{t-1}
    u_t = r_t / sqrt(tau_t)  (demeaned by tau)

    tau_func(params[:n_tau_params], x_lagged) -> tau array
    Remaining params: [omega_g, alpha, gamma, beta]
    """
    n = len(returns)

    def neg_loglik(params):
        tau_params = params[:n_tau_params]
        omega_g, alpha_p, gamma_p, beta_p = params[n_tau_params:]

        # Compute tau (already lagged x_vals should be passed)
        tau = tau_func(tau_params, x_vals)

        if omega_g <= 0 or alpha_p < 0 or gamma_p < 0 or beta_p < 0:
            return 1e10
        persist = alpha_p + gamma_p / 2.0 + beta_p
        if persist >= 0.999:
            return 1e10

        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg

        for t in range(1, n):
            tau_t = tau[t]
            if tau_t < 1e-16:
                tau_t = 1e-16
            u_prev = returns[t-1] / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha_p * u_prev**2 + asym + beta_p * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

        return -ll

    best_ll = np.inf
    best_params = None

    for s in param_starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=param_bounds, options={'maxiter': 1000})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params


def a4f_filter_generic(params, returns, x_vals, n_tau_params, tau_func):
    """Run A4f filter with generic tau, return (tau, g, sigma2) arrays."""
    n = len(returns)
    tau_params = params[:n_tau_params]
    omega_g, alpha_p, gamma_p, beta_p = params[n_tau_params:]

    tau = tau_func(tau_params, x_vals)
    persist = alpha_p + gamma_p / 2.0 + beta_p
    eg = omega_g / (1.0 - min(persist, 0.998))

    g = np.empty(n)
    g[0] = eg

    for t in range(1, n):
        tau_t = max(tau[t], 1e-16)
        u_prev = returns[t-1] / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g[t] = omega_g + alpha_p * u_prev**2 + asym + beta_p * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return tau, g, sigma2


# --- Tau functions for each model ---
def tau_m1(params, x):
    """M1: tau = theta0 + theta1 * VIX^2"""
    theta0, theta1 = params
    return np.maximum(theta0 + theta1 * x[:, 0]**2, 1e-16)


def tau_m2(params, x):
    """M2: tau = theta0 + theta1 * VIX^2 + theta2 * (VIX/VIX3M)"""
    theta0, theta1, theta2 = params
    return np.maximum(theta0 + theta1 * x[:, 0]**2 + theta2 * x[:, 1], 1e-16)


def tau_m3(params, x):
    """M3: tau = theta0 + theta1 * VIX^2 + theta3 * (VIX-VIX3M)^2"""
    theta0, theta1, theta3 = params
    return np.maximum(theta0 + theta1 * x[:, 0]**2 + theta3 * x[:, 2], 1e-16)


def tau_m4(params, x):
    """M4: tau = theta0 + theta1 * VIX9D^2"""
    theta0, theta1 = params
    return np.maximum(theta0 + theta1 * x[:, 3]**2, 1e-16)


# ============================================================
# SECTION 3: OOS FORECASTING
# ============================================================
print("\n[3] OOS forecasting (this will take several minutes)...")

oos_start_idx = np.where(oos_mask)[0][0]
oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)

print(f"  OOS observations: {n_oos_actual}")
print(f"  Refit every {REFIT_EVERY} days")

# Forecast arrays for all 5 models
fc_m1 = np.full(n_oos_actual, np.nan)  # A4f-VIX
fc_m2 = np.full(n_oos_actual, np.nan)  # A4f-VIX + slope
fc_m3 = np.full(n_oos_actual, np.nan)  # A4f-VIX + spread^2
fc_m4 = np.full(n_oos_actual, np.nan)  # A4f-VIX9D
fc_m5 = np.full(n_oos_actual, np.nan)  # GJR

# State tracking
states = {
    'm1': {'params': None, 'g_prev': None, 'tau_prev': None},
    'm2': {'params': None, 'g_prev': None, 'tau_prev': None},
    'm3': {'params': None, 'g_prev': None, 'tau_prev': None},
    'm4': {'params': None, 'g_prev': None, 'tau_prev': None},
    'm5': {'params': None, 'h_prev': None},
}

refit_count = 0
m4_available_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix_arr[train_start:abs_idx]
        train_vix3m = vix3m_arr[train_start:abs_idx]
        train_vix9d = vix9d_arr[train_start:abs_idx]
        train_slope = slope_arr[train_start:abs_idx]
        train_spread_sq = spread_sq_arr[train_start:abs_idx]
        n_train = len(train_ret)

        # Build lagged feature matrix: [VIX, slope_ratio, spread_sq, VIX9D]
        # Lag by 1 day (no lookahead)
        x_lagged = np.empty((n_train, 4))
        x_lagged[0, 0] = train_vix[0]
        x_lagged[1:, 0] = train_vix[:-1]
        x_lagged[0, 1] = train_slope[0]
        x_lagged[1:, 1] = train_slope[:-1]
        x_lagged[0, 2] = train_spread_sq[0]
        x_lagged[1:, 2] = train_spread_sq[:-1]
        x_lagged[0, 3] = np.nanmean(train_vix9d[:10]) if np.any(np.isfinite(train_vix9d[:10])) else train_vix[0]
        x_lagged[1:, 3] = np.where(np.isfinite(train_vix9d[:-1]), train_vix9d[:-1], train_vix[:-1])

        # --- M5: GJR ---
        gjr_p = fit_gjr(train_ret)
        if gjr_p is not None:
            states['m5']['params'] = gjr_p
            h = gjr_filter(gjr_p, train_ret)
            states['m5']['h_prev'] = h[-1]

        # --- M1: A4f-VIX ---
        garch_defaults = [0.05, 0.05, 0.05, 0.88]
        m1_starts = [
            [1e-6, 1e-6] + garch_defaults,
            [1e-5, 5e-7, 0.03, 0.03, 0.08, 0.85],
            [5e-6, 1e-6, 0.08, 0.08, 0.10, 0.80],
        ]
        m1_bounds = [(-0.01, 0.01), (1e-8, 1e-4),
                     (1e-4, 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
        m1_p = fit_a4f_generic(train_ret, x_lagged, 2, tau_m1, m1_starts, m1_bounds)
        if m1_p is not None:
            states['m1']['params'] = m1_p
            tau, g, _ = a4f_filter_generic(m1_p, train_ret, x_lagged, 2, tau_m1)
            states['m1']['g_prev'] = g[-1]
            states['m1']['tau_prev'] = tau[-1]

        # --- M2: A4f-VIX + Slope ---
        m2_starts = [
            [1e-6, 1e-6, 1e-5] + garch_defaults,
            [1e-5, 5e-7, -1e-5, 0.03, 0.03, 0.08, 0.85],
            [5e-6, 1e-6, 5e-6, 0.08, 0.08, 0.10, 0.80],
        ]
        m2_bounds = [(-0.01, 0.01), (1e-8, 1e-4), (-0.01, 0.01),
                     (1e-4, 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
        m2_p = fit_a4f_generic(train_ret, x_lagged, 3, tau_m2, m2_starts, m2_bounds)
        if m2_p is not None:
            states['m2']['params'] = m2_p
            tau, g, _ = a4f_filter_generic(m2_p, train_ret, x_lagged, 3, tau_m2)
            states['m2']['g_prev'] = g[-1]
            states['m2']['tau_prev'] = tau[-1]

        # --- M3: A4f-VIX + Spread^2 ---
        m3_starts = [
            [1e-6, 1e-6, 1e-6] + garch_defaults,
            [1e-5, 5e-7, 5e-7, 0.03, 0.03, 0.08, 0.85],
            [5e-6, 1e-6, 1e-7, 0.08, 0.08, 0.10, 0.80],
        ]
        m3_bounds = [(-0.01, 0.01), (1e-8, 1e-4), (-1e-4, 1e-4),
                     (1e-4, 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
        m3_p = fit_a4f_generic(train_ret, x_lagged, 3, tau_m3, m3_starts, m3_bounds)
        if m3_p is not None:
            states['m3']['params'] = m3_p
            tau, g, _ = a4f_filter_generic(m3_p, train_ret, x_lagged, 3, tau_m3)
            states['m3']['g_prev'] = g[-1]
            states['m3']['tau_prev'] = tau[-1]

        # --- M4: A4f-VIX9D (only if VIX9D available in training window) ---
        vix9d_avail_train = np.isfinite(train_vix9d).sum()
        if vix9d_avail_train > n_train * 0.8:
            m4_starts = [
                [1e-6, 1e-6] + garch_defaults,
                [1e-5, 5e-7, 0.03, 0.03, 0.08, 0.85],
                [5e-6, 1e-6, 0.08, 0.08, 0.10, 0.80],
            ]
            m4_bounds = [(-0.01, 0.01), (1e-8, 1e-4),
                         (1e-4, 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
            m4_p = fit_a4f_generic(train_ret, x_lagged, 2, tau_m4, m4_starts, m4_bounds)
            if m4_p is not None:
                states['m4']['params'] = m4_p
                tau, g, _ = a4f_filter_generic(m4_p, train_ret, x_lagged, 2, tau_m4)
                states['m4']['g_prev'] = g[-1]
                states['m4']['tau_prev'] = tau[-1]

    # ---- One-step-ahead forecasts ----
    # Get lagged values (from t-1 for forecasting t)
    vix_prev = vix_arr[abs_idx - 1]
    vix3m_prev = vix3m_arr[abs_idx - 1]
    slope_prev = slope_arr[abs_idx - 1]
    spread_sq_prev = spread_sq_arr[abs_idx - 1]
    vix9d_prev = vix9d_arr[abs_idx - 1] if np.isfinite(vix9d_arr[abs_idx - 1]) else vix_arr[abs_idx - 1]
    r_prev = ret[abs_idx - 1]

    # M5: GJR
    if states['m5']['params'] is not None and states['m5']['h_prev'] is not None:
        h_new = gjr_forecast_1step(states['m5']['params'], states['m5']['h_prev'], r_prev)
        fc_m5[t_idx] = h_new
        states['m5']['h_prev'] = h_new

    # Helper: one-step A4f forecast
    def a4f_1step(state_key, tau_val, params_key='params'):
        st = states[state_key]
        if st['params'] is None or st['g_prev'] is None:
            return np.nan
        p = st['params']
        n_tp = len(p) - 4  # tau params
        omega_g, alpha_p, gamma_p, beta_p = p[n_tp:]

        tau_t = max(tau_val, 1e-16)
        u_prev = r_prev / np.sqrt(max(st['tau_prev'], 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * st['g_prev']
        g_new = max(g_new, 1e-10)

        sigma2 = tau_t * g_new
        st['g_prev'] = g_new
        st['tau_prev'] = tau_t
        return sigma2

    # M1: A4f-VIX
    if states['m1']['params'] is not None:
        p = states['m1']['params']
        tau_val = max(p[0] + p[1] * vix_prev**2, 1e-16)
        fc_m1[t_idx] = a4f_1step('m1', tau_val)

    # M2: A4f-VIX + Slope
    if states['m2']['params'] is not None:
        p = states['m2']['params']
        tau_val = max(p[0] + p[1] * vix_prev**2 + p[2] * slope_prev, 1e-16)
        fc_m2[t_idx] = a4f_1step('m2', tau_val)

    # M3: A4f-VIX + Spread^2
    if states['m3']['params'] is not None:
        p = states['m3']['params']
        tau_val = max(p[0] + p[1] * vix_prev**2 + p[2] * spread_sq_prev, 1e-16)
        fc_m3[t_idx] = a4f_1step('m3', tau_val)

    # M4: A4f-VIX9D
    if states['m4']['params'] is not None:
        p = states['m4']['params']
        tau_val = max(p[0] + p[1] * vix9d_prev**2, 1e-16)
        fc_m4[t_idx] = a4f_1step('m4', tau_val)
        m4_available_count += 1

elapsed_forecast = time.time() - START_TIME
print(f"\n  Forecasting complete: {refit_count} refits, {elapsed_forecast:.0f}s total")
print(f"  M4 (VIX9D) available for {m4_available_count}/{n_oos_actual} OOS days")

# ============================================================
# SECTION 4: EVALUATION
# ============================================================
print("\n[4] Evaluation on OOS r^2...")

oos_r2 = r2_arr[oos_indices]

# Valid mask: all models have forecasts
valid_all = np.isfinite(fc_m1) & np.isfinite(fc_m2) & np.isfinite(fc_m3) & np.isfinite(fc_m5)
valid_m4 = valid_all & np.isfinite(fc_m4)

print(f"  Valid observations (all models): {valid_all.sum()}")
print(f"  Valid with M4 (VIX9D): {valid_m4.sum()}")

# QLIKE on common valid set
target = oos_r2[valid_all]
models = {
    'M1_A4f_VIX': fc_m1[valid_all],
    'M2_A4f_VIX_Slope': fc_m2[valid_all],
    'M3_A4f_VIX_SpreadSq': fc_m3[valid_all],
    'M5_GJR': fc_m5[valid_all],
}

print("\n  --- QLIKE (lower = better) ---")
qlike_results = {}
for name, fc in models.items():
    ql = qlike(target, fc)
    rho, rho_p = spearman_corr(target, fc)
    qlike_results[name] = {'qlike': ql, 'spearman_rho': rho, 'spearman_p': rho_p}
    print(f"  {name:25s}: QLIKE={ql:.6f}, Spearman rho={rho:.4f} (p={rho_p:.2e})")

# M4 on its own valid set
if valid_m4.sum() > 100:
    target_m4 = oos_r2[valid_m4]
    ql_m4 = qlike(target_m4, fc_m4[valid_m4])
    rho_m4, rho_m4_p = spearman_corr(target_m4, fc_m4[valid_m4])
    qlike_results['M4_A4f_VIX9D'] = {'qlike': ql_m4, 'spearman_rho': rho_m4, 'spearman_p': rho_m4_p}
    print(f"  {'M4_A4f_VIX9D':25s}: QLIKE={ql_m4:.6f}, Spearman rho={rho_m4:.4f} (p={rho_m4_p:.2e})")
    print(f"    (evaluated on {valid_m4.sum()} days where VIX9D available)")

# DM tests
print("\n  --- DM Tests (Harvey |t| > 3.0 for significance) ---")
dm_results = {}

# Key comparisons
comparisons = [
    ('M2 vs M1', fc_m2[valid_all], fc_m1[valid_all], target, 'M2_vs_M1'),
    ('M3 vs M1', fc_m3[valid_all], fc_m1[valid_all], target, 'M3_vs_M1'),
    ('M1 vs M5', fc_m1[valid_all], fc_m5[valid_all], target, 'M1_vs_M5'),
    ('M2 vs M5', fc_m2[valid_all], fc_m5[valid_all], target, 'M2_vs_M5'),
    ('M3 vs M5', fc_m3[valid_all], fc_m5[valid_all], target, 'M3_vs_M5'),
]

for label, fc_a, fc_b, tgt, key in comparisons:
    loss_a = qlike_pointwise(tgt, fc_a)
    loss_b = qlike_pointwise(tgt, fc_b)
    t_stat, p_val = dm_test(loss_a, loss_b)
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else "NS"))
    dm_results[key] = {'t_stat': float(t_stat), 'p_value': float(p_val), 'sig': sig}
    winner = label.split(' vs ')[0] if t_stat < 0 else label.split(' vs ')[1]
    print(f"  {label:15s}: DM t={t_stat:+.3f}, p={p_val:.4f} [{sig}] → {winner}")

# M4 comparisons (on valid_m4 subset)
if valid_m4.sum() > 100:
    target_m4 = oos_r2[valid_m4]
    m4_comparisons = [
        ('M4 vs M1', fc_m4[valid_m4], fc_m1[valid_m4], target_m4, 'M4_vs_M1'),
        ('M2 vs M4', fc_m2[valid_m4], fc_m4[valid_m4], target_m4, 'M2_vs_M4'),
        ('M4 vs M5', fc_m4[valid_m4], fc_m5[valid_m4], target_m4, 'M4_vs_M5'),
    ]
    for label, fc_a, fc_b, tgt, key in m4_comparisons:
        loss_a = qlike_pointwise(tgt, fc_a)
        loss_b = qlike_pointwise(tgt, fc_b)
        t_stat, p_val = dm_test(loss_a, loss_b)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else "NS"))
        dm_results[key] = {'t_stat': float(t_stat), 'p_value': float(p_val), 'sig': sig}
        winner = label.split(' vs ')[0] if t_stat < 0 else label.split(' vs ')[1]
        print(f"  {label:15s}: DM t={t_stat:+.3f}, p={p_val:.4f} [{sig}] → {winner}")

# ============================================================
# SECTION 5: PARAMETER ANALYSIS
# ============================================================
print("\n[5] Parameter analysis (last fit)...")

# Report tau parameters for term structure models
for model_key, model_name in [('m1', 'M1: A4f-VIX'), ('m2', 'M2: A4f-VIX+Slope'),
                                ('m3', 'M3: A4f-VIX+Spread^2'), ('m4', 'M4: A4f-VIX9D')]:
    p = states[model_key]['params']
    if p is not None:
        print(f"\n  {model_name}:")
        if model_key == 'm1':
            print(f"    theta0={p[0]:.6e}, theta1={p[1]:.6e}")
            print(f"    omega_g={p[2]:.6e}, alpha={p[3]:.4f}, gamma={p[4]:.4f}, beta={p[5]:.4f}")
            print(f"    persist={p[3]+p[4]/2+p[5]:.4f}")
        elif model_key in ('m2', 'm3'):
            print(f"    theta0={p[0]:.6e}, theta1={p[1]:.6e}, theta2/3={p[2]:.6e}")
            print(f"    omega_g={p[3]:.6e}, alpha={p[4]:.4f}, gamma={p[5]:.4f}, beta={p[6]:.4f}")
            print(f"    persist={p[4]+p[5]/2+p[6]:.4f}")
            # Is theta2/3 economically meaningful?
            if model_key == 'm2':
                # theta2 * (typical slope change) vs theta1 * (typical VIX^2 change)
                slope_std = np.nanstd(slope_arr)
                vix_sq_std = np.nanstd(vix_arr**2)
                contrib_slope = abs(p[2]) * slope_std
                contrib_vix = abs(p[1]) * vix_sq_std
                print(f"    Economic magnitude: theta2*std(slope)={contrib_slope:.6e} vs theta1*std(VIX^2)={contrib_vix:.6e}")
                print(f"    Slope contribution ratio: {contrib_slope/max(contrib_vix, 1e-16)*100:.2f}%")
            elif model_key == 'm3':
                spread_sq_std = np.nanstd(spread_sq_arr)
                vix_sq_std = np.nanstd(vix_arr**2)
                contrib_spread = abs(p[2]) * spread_sq_std
                contrib_vix = abs(p[1]) * vix_sq_std
                print(f"    Economic magnitude: theta3*std(spread^2)={contrib_spread:.6e} vs theta1*std(VIX^2)={contrib_vix:.6e}")
                print(f"    Spread^2 contribution ratio: {contrib_spread/max(contrib_vix, 1e-16)*100:.2f}%")
        elif model_key == 'm4':
            print(f"    theta0={p[0]:.6e}, theta1={p[1]:.6e}")
            print(f"    omega_g={p[2]:.6e}, alpha={p[3]:.4f}, gamma={p[4]:.4f}, beta={p[5]:.4f}")
            print(f"    persist={p[3]+p[4]/2+p[5]:.4f}")

# ============================================================
# SECTION 6: REGIME ANALYSIS (Backwardation vs Contango)
# ============================================================
print("\n[6] Regime analysis: Backwardation vs Contango OOS performance...")

oos_slope = slope_arr[oos_indices]
backwardation = oos_slope > 1.0
contango = oos_slope <= 1.0

for regime_name, regime_mask in [('Backwardation', backwardation), ('Contango', contango)]:
    rm = regime_mask & valid_all
    if rm.sum() < 50:
        print(f"  {regime_name}: insufficient data ({rm.sum()} days)")
        continue

    tgt_r = oos_r2[rm]
    print(f"\n  {regime_name} ({rm.sum()} days, mean slope={oos_slope[rm].mean():.4f}):")

    for name, fc_full in [('M1', fc_m1), ('M2', fc_m2), ('M3', fc_m3), ('M5', fc_m5)]:
        fc_r = fc_full[rm]
        ql = qlike(tgt_r, fc_r)
        print(f"    {name}: QLIKE={ql:.6f}")

    # DM: M2 vs M1 in this regime
    loss_m2_r = qlike_pointwise(tgt_r, fc_m2[rm])
    loss_m1_r = qlike_pointwise(tgt_r, fc_m1[rm])
    t_r, p_r = dm_test(loss_m2_r, loss_m1_r)
    sig_r = "***" if abs(t_r) > 3.0 else ("**" if abs(t_r) > 2.0 else ("*" if abs(t_r) > 1.65 else "NS"))
    print(f"    M2 vs M1: DM t={t_r:+.3f} [{sig_r}]")

# ============================================================
# SECTION 7: CHART
# ============================================================
print("\n[7] Generating chart...")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1053: VIX Term Structure Slope as Volatility Predictor', fontsize=14, fontweight='bold')

oos_dates = df.index[oos_indices]

# Panel A: QLIKE comparison bar chart
ax = axes[0, 0]
model_names = list(qlike_results.keys())
qlike_vals = [qlike_results[m]['qlike'] for m in model_names]
short_names = [m.replace('A4f_', '').replace('_', '\n') for m in model_names]
colors = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#F44336']
bars = ax.bar(range(len(model_names)), qlike_vals, color=colors[:len(model_names)])
ax.set_xticks(range(len(model_names)))
ax.set_xticklabels(short_names, fontsize=8)
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('A: OOS QLIKE Comparison')
for i, v in enumerate(qlike_vals):
    ax.text(i, v + 0.001, f'{v:.4f}', ha='center', va='bottom', fontsize=8)

# Panel B: VIX Term Structure time series
ax = axes[0, 1]
ax.plot(oos_dates, oos_slope, alpha=0.5, linewidth=0.5, color='blue', label='VIX/VIX3M')
ax.axhline(y=1.0, color='red', linestyle='--', linewidth=1, label='Contango/Backwardation boundary')
ax.fill_between(oos_dates, 1.0, oos_slope, where=oos_slope > 1.0,
                alpha=0.3, color='red', label='Backwardation')
ax.fill_between(oos_dates, oos_slope, 1.0, where=oos_slope <= 1.0,
                alpha=0.3, color='green', label='Contango')
ax.set_ylabel('VIX / VIX3M')
ax.set_title('B: VIX Term Structure Slope (OOS)')
ax.legend(fontsize=7, loc='upper right')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax.xaxis.set_major_locator(mdates.YearLocator())

# Panel C: DM test results
ax = axes[1, 0]
dm_labels = list(dm_results.keys())
dm_t_vals = [dm_results[k]['t_stat'] for k in dm_labels]
dm_colors = ['green' if abs(t) > 3.0 else ('orange' if abs(t) > 2.0 else 'gray') for t in dm_t_vals]
ax.barh(range(len(dm_labels)), dm_t_vals, color=dm_colors)
ax.axvline(x=3.0, color='red', linestyle='--', linewidth=1, label='Harvey threshold (+)')
ax.axvline(x=-3.0, color='red', linestyle='--', linewidth=1, label='Harvey threshold (-)')
ax.set_yticks(range(len(dm_labels)))
ax.set_yticklabels(dm_labels, fontsize=8)
ax.set_xlabel('DM t-statistic')
ax.set_title('C: DM Test Results')
for i, t in enumerate(dm_t_vals):
    ax.text(t + (0.1 if t >= 0 else -0.1), i, f'{t:+.2f}',
            ha='left' if t >= 0 else 'right', va='center', fontsize=8)

# Panel D: Spearman rho comparison
ax = axes[1, 1]
rho_vals = [qlike_results[m]['spearman_rho'] for m in model_names]
bars = ax.bar(range(len(model_names)), rho_vals, color=colors[:len(model_names)])
ax.set_xticks(range(len(model_names)))
ax.set_xticklabels(short_names, fontsize=8)
ax.set_ylabel('Spearman rho')
ax.set_title('D: Forecast-Actual Rank Correlation')
for i, v in enumerate(rho_vals):
    ax.text(i, v + 0.002, f'{v:.4f}', ha='center', va='bottom', fontsize=8)

plt.tight_layout()
plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved: {CHART_PATH}")

# ============================================================
# SECTION 8: RESULTS JSON
# ============================================================
print("\n[8] Saving results...")

elapsed_total = time.time() - START_TIME

# Determine conclusion
m2_vs_m1_t = dm_results.get('M2_vs_M1', {}).get('t_stat', 0)
m3_vs_m1_t = dm_results.get('M3_vs_M1', {}).get('t_stat', 0)

if abs(m2_vs_m1_t) > 3.0 or abs(m3_vs_m1_t) > 3.0:
    conclusion = "SIGNIFICANT — Term structure slope adds incremental info beyond VIX level"
    status = "significant"
else:
    conclusion = "NULL — Term structure slope does NOT add incremental info beyond VIX level in A4f"
    status = "null"

results = {
    "experiment_id": EXPERIMENT_ID,
    "title": "VIX Term Structure Slope as Volatility Predictor",
    "status": status,
    "conclusion": conclusion,
    "data": {
        "asset": "SPY",
        "source": "yfinance",
        "period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_total": n_total,
        "n_oos": int(n_oos_actual),
        "oos_start": OOS_START,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "n_refits": refit_count,
    },
    "descriptive": {
        "backwardation_pct": float(backwardation_pct),
        "contango_pct": float(100 - backwardation_pct),
        "corr_vix_lag_r2": float(corr_vix_r2),
        "corr_slope_lag_r2": float(corr_slope_r2),
        "corr_spread_lag_r2": float(corr_spread_r2),
    },
    "qlike": {k: float(v['qlike']) for k, v in qlike_results.items()},
    "spearman": {k: {"rho": float(v['spearman_rho']), "p": float(v['spearman_p'])} for k, v in qlike_results.items()},
    "dm_tests": dm_results,
    "models": {
        "M1": "A4f: tau = theta0 + theta1*VIX^2",
        "M2": "A4f: tau = theta0 + theta1*VIX^2 + theta2*(VIX/VIX3M)",
        "M3": "A4f: tau = theta0 + theta1*VIX^2 + theta3*(VIX-VIX3M)^2",
        "M4": "A4f: tau = theta0 + theta1*VIX9D^2",
        "M5": "GJR-GARCH(1,1)",
    },
    "parameters_last_fit": {},
    "references": [
        "Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.",
        "Harvey et al. (2016). Multiple testing threshold t > 3.0.",
        "Mixon (2007). The implied volatility term structure. J Deriv 15(2):29-46.",
        "Campa & Chang (1995). Expectations hypothesis on vol term structure. J Finance 50(2):529-547.",
        "Lu & Zhu (2010). Volatility components. J Financial Econometrics 8(4):431-456.",
    ],
    "runtime_seconds": float(elapsed_total),
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "seed": 42,
}

# Add last-fit parameters
for model_key, model_name in [('m1', 'M1'), ('m2', 'M2'), ('m3', 'M3'), ('m4', 'M4')]:
    p = states[model_key]['params']
    if p is not None:
        results['parameters_last_fit'][model_name] = [float(x) for x in p]

gjr_p = states['m5']['params']
if gjr_p is not None:
    results['parameters_last_fit']['M5_GJR'] = [float(x) for x in gjr_p]

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2)
print(f"  Results saved: {RESULTS_PATH}")

# ============================================================
# SECTION 9: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print(f"K1053 SUMMARY")
print("=" * 70)
print(f"\n  Conclusion: {conclusion}")
print(f"\n  QLIKE ranking (lower = better):")
sorted_ql = sorted(qlike_results.items(), key=lambda x: x[1]['qlike'])
for i, (name, vals) in enumerate(sorted_ql):
    print(f"    {i+1}. {name}: {vals['qlike']:.6f}")
print(f"\n  Key DM tests:")
for key in ['M2_vs_M1', 'M3_vs_M1', 'M1_vs_M5']:
    if key in dm_results:
        d = dm_results[key]
        print(f"    {key}: t={d['t_stat']:+.3f} [{d['sig']}]")
print(f"\n  Runtime: {elapsed_total:.0f}s")
print("=" * 70)
