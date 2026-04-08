#!/usr/bin/env python3
"""
K997: MF-GJR-X with Local Fear Indices for Cross-Market Prediction
===================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 found A4f (τ=θ₀+θ₁VIX², free ω) as champion for SPY (DM t=+4.48 vs GJR).
  K994 cross-asset validation showed: QQQ passes (t=-3.71), but EEM/GLD/0050.TW
  fail with US VIX alone. Likely cause: VIX-r² correlation too low for non-US assets
  (EEM 0.499, GLD 0.126, 0050.TW 0.275).

  This experiment tests local fear indices as τ drivers:
    - EEM: VXEEM (^VXEEM), own 20d RV
    - GLD: GVZ (^GVZ), own 20d RV
    - 0050.TW: own 20d RV, VIX lag+2, VIX + TW_RV combined
    - Multi-factor: τ = θ₀ + θ₁X₁² + θ₂X₂² (VIX + local index)

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility.
    JBES 33(3):338-358.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.

Data: yfinance 2005-2026. OOS: 2019-01-01 to latest.
Author: VolPred Research System
Date: 2026-04-08
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
EXPERIMENT_ID = "K997"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func, spearman_corr
from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k997_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit
RV_WINDOW = 20    # 20-day rolling realized vol

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR-X with Local Fear Indices")
print("  Testing local fear indices vs US VIX for EEM/GLD/0050.TW")
print("=" * 70)


# ============================================================
# MODEL IMPLEMENTATIONS
# ============================================================

def fit_gjr(returns):
    """Fit GJR-GARCH(1,1)."""
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
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


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


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_mfgjr_x_single(returns, x_vals):
    """
    Fit MF-GJR-X (A4f) with single external variable:
    τ_t = max(θ₀ + θ₁ × X²_{t-1}, eps)
    g_t = ω + α u²_{t-1} + γ u²_{t-1} 1_{u<0} + β g_{t-1}
    u_{t-1} = r_{t-1} / sqrt(τ_t), ω free
    """
    n = len(returns)
    x_lag = np.empty(n)
    x_lag[0] = x_vals[0]
    x_lag[1:] = x_vals[:-1]

    var0 = np.var(returns)
    x2_mean = np.mean(x_lag**2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10

        tau = np.maximum(theta0 + theta1 * x_lag**2, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / x2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def fit_mfgjr_x_dual(returns, x1_vals, x2_vals):
    """
    Fit MF-GJR-X (A4f) with TWO external variables:
    τ_t = max(θ₀ + θ₁ × X1²_{t-1} + θ₂ × X2²_{t-1}, eps)
    g_t = ω + α u²_{t-1} + γ u²_{t-1} 1_{u<0} + β g_{t-1}
    u_{t-1} = r_{t-1} / sqrt(τ_t), ω free
    """
    n = len(returns)
    x1_lag = np.empty(n)
    x1_lag[0] = x1_vals[0]
    x1_lag[1:] = x1_vals[:-1]
    x2_lag = np.empty(n)
    x2_lag[0] = x2_vals[0]
    x2_lag[1:] = x2_vals[:-1]

    var0 = np.var(returns)
    x1_2_mean = np.mean(x1_lag**2) + 1e-8
    x2_2_mean = np.mean(x2_lag**2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10

        tau = np.maximum(theta0 + theta1 * x1_lag**2 + theta2 * x2_lag**2, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    best_ll = np.inf
    best_params = None
    starts = [
        [var0*0.1, var0/x1_2_mean*0.5, var0/x2_2_mean*0.5, 0.05, 0.05, 0.05, 0.90],
        [var0*0.05, var0/x1_2_mean*0.3, var0/x2_2_mean*0.3, 0.10, 0.03, 0.08, 0.88],
        [var0*0.2, var0/x1_2_mean, var0/x2_2_mean, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


# ============================================================
# OOS FORECASTING
# ============================================================

def oos_forecast_gjr(ret, oos_mask, window, refit_every):
    """OOS forecasting for GJR-GARCH."""
    n = len(ret)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr(train_ret)
            if params is None:
                continue
            last_fit = t
            omega, alpha, gamma, beta = params
            h_series = np.empty(len(train_ret))
            h_series[0] = np.var(train_ret[:min(250, len(train_ret))])
            for s in range(1, len(train_ret)):
                asym_val = gamma * train_ret[s-1]**2 if train_ret[s-1] < 0 else 0.0
                h_series[s] = omega + alpha * train_ret[s-1]**2 + asym_val + beta * h_series[s-1]
                h_series[s] = max(h_series[s], 1e-10)
            h_prev = h_series[-1]
            r_prev = train_ret[-1]
        else:
            h_prev = gjr_forecast_1step(params, h_prev, r_prev)
            r_prev = ret[t-1]

        forecasts[i] = gjr_forecast_1step(params, h_prev, r_prev)

    return forecasts


def oos_forecast_mfgjr_single(ret, x_vals, oos_mask, window, refit_every):
    """OOS forecasting for MF-GJR-X with single external variable (A4f)."""
    n = len(ret)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            train_x = x_vals[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_mfgjr_x_single(train_ret, train_x)
            if params is None:
                continue
            last_fit = t

            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            n_train = len(train_ret)
            x_lag_train = np.empty(n_train)
            x_lag_train[0] = train_x[0]
            x_lag_train[1:] = train_x[:-1]
            tau_train = np.maximum(theta0 + theta1 * x_lag_train**2, 1e-16)

            persist = alpha + gamma_p / 2.0 + beta
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g_series = np.empty(n_train)
            g_series[0] = eg
            for s in range(1, n_train):
                u_prev = train_ret[s-1] / np.sqrt(tau_train[s])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g_series[s] = omega_g + alpha * u_prev**2 + asym + beta * g_series[s-1]
                g_series[s] = max(g_series[s], 1e-10)

            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
        else:
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            tau_curr = max(theta0 + theta1 * x_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_prev = omega_g + alpha * u_prev**2 + asym + beta * g_prev
            g_prev = max(g_prev, 1e-10)
            r_prev_val = ret[t-1]

        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * x_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        asym_fc = gamma_p * u_prev_fc**2 if u_prev_fc < 0 else 0.0
        g_fc = omega_g + alpha * u_prev_fc**2 + asym_fc + beta * g_prev
        g_fc = max(g_fc, 1e-10)
        forecasts[i] = tau_t * g_fc

    return forecasts


def oos_forecast_mfgjr_dual(ret, x1_vals, x2_vals, oos_mask, window, refit_every):
    """OOS forecasting for MF-GJR-X with TWO external variables."""
    n = len(ret)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            train_x1 = x1_vals[train_start:t]
            train_x2 = x2_vals[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_mfgjr_x_dual(train_ret, train_x1, train_x2)
            if params is None:
                continue
            last_fit = t

            theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
            n_train = len(train_ret)
            x1_lag = np.empty(n_train)
            x1_lag[0] = train_x1[0]
            x1_lag[1:] = train_x1[:-1]
            x2_lag = np.empty(n_train)
            x2_lag[0] = train_x2[0]
            x2_lag[1:] = train_x2[:-1]
            tau_train = np.maximum(theta0 + theta1 * x1_lag**2 + theta2 * x2_lag**2, 1e-16)

            persist = alpha + gamma_p / 2.0 + beta
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g_series = np.empty(n_train)
            g_series[0] = eg
            for s in range(1, n_train):
                u_prev = train_ret[s-1] / np.sqrt(tau_train[s])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g_series[s] = omega_g + alpha * u_prev**2 + asym + beta * g_series[s-1]
                g_series[s] = max(g_series[s], 1e-10)

            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
        else:
            theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
            tau_curr = max(theta0 + theta1 * x1_vals[t-1]**2 + theta2 * x2_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_prev = omega_g + alpha * u_prev**2 + asym + beta * g_prev
            g_prev = max(g_prev, 1e-10)
            r_prev_val = ret[t-1]

        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * x1_vals[t-1]**2 + theta2 * x2_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        asym_fc = gamma_p * u_prev_fc**2 if u_prev_fc < 0 else 0.0
        g_fc = omega_g + alpha * u_prev_fc**2 + asym_fc + beta * g_prev
        g_fc = max(g_fc, 1e-10)
        forecasts[i] = tau_t * g_fc

    return forecasts


def compute_rv20(returns_series, window=20):
    """Compute 20-day rolling realized variance (annualized as daily σ²)."""
    r2 = returns_series ** 2
    rv = r2.rolling(window=window, min_periods=window).mean()
    # Convert to annualized implied vol level (like VIX in % terms)
    # RV is mean daily r², to get VIX-like scale: sqrt(rv * 252) * 100
    rv_vix_scale = np.sqrt(rv * 252) * 100
    return rv_vix_scale


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Load VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy()
print(f"  VIX: {len(vix_series)} observations ({vix_series.index[0].strftime('%Y-%m-%d')} to {vix_series.index[-1].strftime('%Y-%m-%d')})")

# Load VXEEM (EM VIX)
vxeem_raw = yf.download('^VXEEM', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vxeem_raw.columns, pd.MultiIndex):
    vxeem_raw.columns = vxeem_raw.columns.get_level_values(0)
if len(vxeem_raw) > 100:
    vxeem_series = vxeem_raw['Close'].copy()
    print(f"  VXEEM: {len(vxeem_series)} observations ({vxeem_series.index[0].strftime('%Y-%m-%d')} to {vxeem_series.index[-1].strftime('%Y-%m-%d')})")
else:
    vxeem_series = None
    print(f"  VXEEM: insufficient data ({len(vxeem_raw)} obs), will use RV proxy")

# Load GVZ (Gold VIX)
gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END, progress=False)
if isinstance(gvz_raw.columns, pd.MultiIndex):
    gvz_raw.columns = gvz_raw.columns.get_level_values(0)
if len(gvz_raw) > 100:
    gvz_series = gvz_raw['Close'].copy()
    print(f"  GVZ: {len(gvz_series)} observations ({gvz_series.index[0].strftime('%Y-%m-%d')} to {gvz_series.index[-1].strftime('%Y-%m-%d')})")
else:
    gvz_series = None
    print(f"  GVZ: insufficient data ({len(gvz_raw)} obs), will use RV proxy")


# ============================================================
# DEFINE ASSET CONFIGURATIONS
# ============================================================

# Each asset has multiple model configurations to test
ASSET_CONFIGS = {}

# --- EEM ---
ASSET_CONFIGS['EEM'] = {
    'ticker': 'EEM',
    'label': 'Emerging Markets ETF',
    'models': {}  # populated after data loading
}

# --- GLD ---
ASSET_CONFIGS['GLD'] = {
    'ticker': 'GLD',
    'label': 'Gold ETF',
    'models': {}
}

# --- 0050.TW ---
ASSET_CONFIGS['0050.TW'] = {
    'ticker': '0050.TW',
    'label': 'Taiwan ETF',
    'models': {}
}


# ============================================================
# HELPER: Run one model config and return evaluation metrics
# ============================================================

def evaluate_model(model_name, forecasts, oos_r2, fc_gjr):
    """Evaluate a model's forecasts vs GJR baseline."""
    valid = ~np.isnan(forecasts) & ~np.isnan(fc_gjr) & (oos_r2 > 0)
    n_valid = int(valid.sum())

    if n_valid < 252:
        return {
            'status': 'insufficient_data',
            'n_valid': n_valid,
        }

    qlike_model = qlike_func(oos_r2[valid], forecasts[valid])
    qlike_gjr_val = qlike_func(oos_r2[valid], fc_gjr[valid])

    rho_model, p_model = spearman_corr(oos_r2[valid], forecasts[valid])
    rho_gjr_val, p_gjr_val = spearman_corr(oos_r2[valid], fc_gjr[valid])

    # DM test: negative t means model is better
    loss_model = np.log(forecasts[valid]) + oos_r2[valid] / forecasts[valid]
    loss_gjr_dm = np.log(fc_gjr[valid]) + oos_r2[valid] / fc_gjr[valid]
    dm_t_val, dm_p_val = dm_test(loss_model, loss_gjr_dm)

    return {
        'status': 'completed',
        'n_valid': n_valid,
        'qlike': round(float(qlike_model), 6),
        'qlike_gjr': round(float(qlike_gjr_val), 6),
        'qlike_improvement': round(float(qlike_gjr_val - qlike_model), 6),
        'spearman_rho': round(float(rho_model), 4),
        'spearman_rho_gjr': round(float(rho_gjr_val), 4),
        'dm_t_vs_gjr': round(float(dm_t_val), 4),
        'dm_p_vs_gjr': float(dm_p_val),
        'significant_harvey': abs(dm_t_val) > 3.0,
        'model_better': dm_t_val < 0,  # negative = model has lower loss
    }


# ============================================================
# MAIN PROCESSING
# ============================================================
all_results = {}

for asset_key, config in ASSET_CONFIGS.items():
    ticker = config['ticker']
    label = config['label']

    print(f"\n{'='*60}")
    print(f"  Asset: {asset_key} ({label})")
    print(f"{'='*60}")

    # Download price data
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if len(raw) < 1000:
        print(f"  SKIP: insufficient data ({len(raw)} obs)")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient data ({len(raw)})'}
        continue

    prices = raw['Close'].copy()

    # Clean 0050.TW
    if asset_key == '0050.TW':
        prices, _ = clean_tw50_data(prices)

    log_ret_series = np.log(prices / prices.shift(1))

    # Compute own 20d RV (VIX-scale)
    own_rv = compute_rv20(log_ret_series, window=RV_WINDOW)

    # Prepare base DataFrame with VIX
    if asset_key == '0050.TW':
        vix_aligned = vix_series.shift(1)  # lag+1 for timezone
        vix_aligned_2 = vix_series.shift(2)  # lag+2 for extra delay test
    else:
        vix_aligned = vix_series
        vix_aligned_2 = None

    df_base = pd.DataFrame({
        'price': prices,
        'log_ret': log_ret_series,
        'VIX': vix_aligned,
        'own_rv': own_rv,
    })

    if vix_aligned_2 is not None:
        df_base['VIX_lag2'] = vix_aligned_2

    # Add asset-specific indices
    if asset_key == 'EEM' and vxeem_series is not None:
        df_base['VXEEM'] = vxeem_series
    if asset_key == 'GLD' and gvz_series is not None:
        df_base['GVZ'] = gvz_series

    # Drop NaN rows (need all base columns valid)
    base_cols = ['log_ret', 'VIX', 'own_rv']
    df_base = df_base.dropna(subset=base_cols)

    if len(df_base) < WINDOW + 252:
        print(f"  SKIP: insufficient aligned data ({len(df_base)} obs)")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient aligned data'}
        continue

    oos_mask = np.array(df_base.index >= OOS_START)
    n_total = len(df_base)
    n_oos = oos_mask.sum()

    print(f"  Data: {df_base.index[0].strftime('%Y-%m-%d')} to {df_base.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
    print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

    if n_oos < 252:
        print(f"  SKIP: insufficient OOS ({n_oos})")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient OOS ({n_oos})'}
        continue

    ret = df_base['log_ret'].values
    vix_vals = df_base['VIX'].values
    own_rv_vals = df_base['own_rv'].values
    r2 = ret ** 2
    oos_r2 = r2[oos_mask]
    oos_ret = ret[oos_mask]

    # Diagnostics
    corr_vix_r2 = np.corrcoef(vix_vals[oos_mask], r2[oos_mask])[0, 1]
    corr_rv_r2 = np.corrcoef(own_rv_vals[oos_mask], r2[oos_mask])[0, 1]
    print(f"  OOS vol (ann.): {np.std(oos_ret)*np.sqrt(252):.4f}")
    print(f"  VIX-r² corr (OOS): {corr_vix_r2:.4f}")
    print(f"  own_RV-r² corr (OOS): {corr_rv_r2:.4f}")

    # ---- GJR Baseline ----
    print(f"\n  [GJR] Fitting OOS forecasts...")
    t0 = time.time()
    fc_gjr = oos_forecast_gjr(ret, oos_mask, WINDOW, REFIT_EVERY)
    t_gjr = time.time() - t0
    print(f"    Done in {t_gjr:.1f}s")

    asset_result = {
        'status': 'completed',
        'label': label,
        'n_total': n_total,
        'n_oos': n_oos,
        'diagnostics': {
            'oos_vol_ann': round(float(np.std(oos_ret) * np.sqrt(252)), 4),
            'vix_r2_corr_oos': round(float(corr_vix_r2), 4),
            'own_rv_r2_corr_oos': round(float(corr_rv_r2), 4),
        },
        'models': {},
    }

    # ---- Model 1: A4f with US VIX (K994 replication) ----
    print(f"  [A4f-VIX] Fitting...")
    t0 = time.time()
    fc_vix = oos_forecast_mfgjr_single(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY)
    t_vix = time.time() - t0
    print(f"    Done in {t_vix:.1f}s")
    eval_vix = evaluate_model('A4f-VIX', fc_vix, oos_r2, fc_gjr)
    asset_result['models']['A4f_VIX'] = eval_vix
    print(f"    QLIKE={eval_vix.get('qlike','N/A')}, DM t={eval_vix.get('dm_t_vs_gjr','N/A')}, sig={eval_vix.get('significant_harvey','N/A')}")

    # ---- Model 2: A4f with own RV (self-exciting) ----
    print(f"  [A4f-OwnRV] Fitting...")
    t0 = time.time()
    fc_rv = oos_forecast_mfgjr_single(ret, own_rv_vals, oos_mask, WINDOW, REFIT_EVERY)
    t_rv = time.time() - t0
    print(f"    Done in {t_rv:.1f}s")
    eval_rv = evaluate_model('A4f-OwnRV', fc_rv, oos_r2, fc_gjr)
    asset_result['models']['A4f_OwnRV'] = eval_rv
    print(f"    QLIKE={eval_rv.get('qlike','N/A')}, DM t={eval_rv.get('dm_t_vs_gjr','N/A')}, sig={eval_rv.get('significant_harvey','N/A')}")

    # ---- Model 3: A4f with VIX + own RV (dual factor) ----
    print(f"  [A4f-VIX+RV] Fitting dual-factor...")
    t0 = time.time()
    fc_dual = oos_forecast_mfgjr_dual(ret, vix_vals, own_rv_vals, oos_mask, WINDOW, REFIT_EVERY)
    t_dual = time.time() - t0
    print(f"    Done in {t_dual:.1f}s")
    eval_dual = evaluate_model('A4f-VIX+RV', fc_dual, oos_r2, fc_gjr)
    asset_result['models']['A4f_VIX_RV'] = eval_dual
    print(f"    QLIKE={eval_dual.get('qlike','N/A')}, DM t={eval_dual.get('dm_t_vs_gjr','N/A')}, sig={eval_dual.get('significant_harvey','N/A')}")

    # ---- Asset-specific models ----
    if asset_key == 'EEM' and vxeem_series is not None:
        # VXEEM available
        vxeem_vals_in_df = df_base.get('VXEEM')
        if vxeem_vals_in_df is not None:
            df_vxeem = df_base.dropna(subset=['VXEEM'])
            if len(df_vxeem) > WINDOW + 252:
                oos_mask_vxeem = np.array(df_vxeem.index >= OOS_START)
                if oos_mask_vxeem.sum() >= 252:
                    ret_vxeem = df_vxeem['log_ret'].values
                    vxeem_v = df_vxeem['VXEEM'].values
                    vix_v = df_vxeem['VIX'].values
                    r2_vxeem = ret_vxeem ** 2
                    oos_r2_vxeem = r2_vxeem[oos_mask_vxeem]

                    print(f"  [A4f-VXEEM] Fitting with VXEEM...")
                    t0 = time.time()
                    fc_gjr_vxeem = oos_forecast_gjr(ret_vxeem, oos_mask_vxeem, WINDOW, REFIT_EVERY)
                    fc_vxeem = oos_forecast_mfgjr_single(ret_vxeem, vxeem_v, oos_mask_vxeem, WINDOW, REFIT_EVERY)
                    t_vxeem = time.time() - t0
                    print(f"    Done in {t_vxeem:.1f}s")
                    eval_vxeem = evaluate_model('A4f-VXEEM', fc_vxeem, oos_r2_vxeem, fc_gjr_vxeem)
                    asset_result['models']['A4f_VXEEM'] = eval_vxeem
                    print(f"    QLIKE={eval_vxeem.get('qlike','N/A')}, DM t={eval_vxeem.get('dm_t_vs_gjr','N/A')}, sig={eval_vxeem.get('significant_harvey','N/A')}")

                    # VIX + VXEEM dual
                    print(f"  [A4f-VIX+VXEEM] Fitting dual...")
                    t0 = time.time()
                    fc_vix_vxeem = oos_forecast_mfgjr_dual(ret_vxeem, vix_v, vxeem_v, oos_mask_vxeem, WINDOW, REFIT_EVERY)
                    t_vv = time.time() - t0
                    print(f"    Done in {t_vv:.1f}s")
                    eval_vix_vxeem = evaluate_model('A4f-VIX+VXEEM', fc_vix_vxeem, oos_r2_vxeem, fc_gjr_vxeem)
                    asset_result['models']['A4f_VIX_VXEEM'] = eval_vix_vxeem
                    print(f"    QLIKE={eval_vix_vxeem.get('qlike','N/A')}, DM t={eval_vix_vxeem.get('dm_t_vs_gjr','N/A')}, sig={eval_vix_vxeem.get('significant_harvey','N/A')}")

                    corr_vxeem_r2 = np.corrcoef(vxeem_v[oos_mask_vxeem], r2_vxeem[oos_mask_vxeem])[0, 1]
                    asset_result['diagnostics']['vxeem_r2_corr_oos'] = round(float(corr_vxeem_r2), 4)
                    asset_result['diagnostics']['n_vxeem_obs'] = int(oos_mask_vxeem.sum())

    if asset_key == 'GLD' and gvz_series is not None:
        gvz_vals_in_df = df_base.get('GVZ')
        if gvz_vals_in_df is not None:
            df_gvz = df_base.dropna(subset=['GVZ'])
            if len(df_gvz) > WINDOW + 252:
                oos_mask_gvz = np.array(df_gvz.index >= OOS_START)
                if oos_mask_gvz.sum() >= 252:
                    ret_gvz = df_gvz['log_ret'].values
                    gvz_v = df_gvz['GVZ'].values
                    vix_v_gvz = df_gvz['VIX'].values
                    r2_gvz = ret_gvz ** 2
                    oos_r2_gvz = r2_gvz[oos_mask_gvz]

                    print(f"  [A4f-GVZ] Fitting with GVZ...")
                    t0 = time.time()
                    fc_gjr_gvz = oos_forecast_gjr(ret_gvz, oos_mask_gvz, WINDOW, REFIT_EVERY)
                    fc_gvz = oos_forecast_mfgjr_single(ret_gvz, gvz_v, oos_mask_gvz, WINDOW, REFIT_EVERY)
                    t_gvz = time.time() - t0
                    print(f"    Done in {t_gvz:.1f}s")
                    eval_gvz = evaluate_model('A4f-GVZ', fc_gvz, oos_r2_gvz, fc_gjr_gvz)
                    asset_result['models']['A4f_GVZ'] = eval_gvz
                    print(f"    QLIKE={eval_gvz.get('qlike','N/A')}, DM t={eval_gvz.get('dm_t_vs_gjr','N/A')}, sig={eval_gvz.get('significant_harvey','N/A')}")

                    # VIX + GVZ dual
                    print(f"  [A4f-VIX+GVZ] Fitting dual...")
                    t0 = time.time()
                    fc_vix_gvz = oos_forecast_mfgjr_dual(ret_gvz, vix_v_gvz, gvz_v, oos_mask_gvz, WINDOW, REFIT_EVERY)
                    t_vg = time.time() - t0
                    print(f"    Done in {t_vg:.1f}s")
                    eval_vix_gvz = evaluate_model('A4f-VIX+GVZ', fc_vix_gvz, oos_r2_gvz, fc_gjr_gvz)
                    asset_result['models']['A4f_VIX_GVZ'] = eval_vix_gvz
                    print(f"    QLIKE={eval_vix_gvz.get('qlike','N/A')}, DM t={eval_vix_gvz.get('dm_t_vs_gjr','N/A')}, sig={eval_vix_gvz.get('significant_harvey','N/A')}")

                    corr_gvz_r2 = np.corrcoef(gvz_v[oos_mask_gvz], r2_gvz[oos_mask_gvz])[0, 1]
                    asset_result['diagnostics']['gvz_r2_corr_oos'] = round(float(corr_gvz_r2), 4)
                    asset_result['diagnostics']['n_gvz_obs'] = int(oos_mask_gvz.sum())

    if asset_key == '0050.TW':
        # VIX lag+2 test
        if 'VIX_lag2' in df_base.columns:
            df_lag2 = df_base.dropna(subset=['VIX_lag2'])
            if len(df_lag2) > WINDOW + 252:
                oos_mask_lag2 = np.array(df_lag2.index >= OOS_START)
                if oos_mask_lag2.sum() >= 252:
                    ret_lag2 = df_lag2['log_ret'].values
                    vix_lag2_v = df_lag2['VIX_lag2'].values
                    r2_lag2 = ret_lag2 ** 2
                    oos_r2_lag2 = r2_lag2[oos_mask_lag2]

                    print(f"  [A4f-VIX_lag2] Fitting with VIX lag+2...")
                    t0 = time.time()
                    fc_gjr_lag2 = oos_forecast_gjr(ret_lag2, oos_mask_lag2, WINDOW, REFIT_EVERY)
                    fc_lag2 = oos_forecast_mfgjr_single(ret_lag2, vix_lag2_v, oos_mask_lag2, WINDOW, REFIT_EVERY)
                    t_lag2 = time.time() - t0
                    print(f"    Done in {t_lag2:.1f}s")
                    eval_lag2 = evaluate_model('A4f-VIX_lag2', fc_lag2, oos_r2_lag2, fc_gjr_lag2)
                    asset_result['models']['A4f_VIX_lag2'] = eval_lag2
                    print(f"    QLIKE={eval_lag2.get('qlike','N/A')}, DM t={eval_lag2.get('dm_t_vs_gjr','N/A')}, sig={eval_lag2.get('significant_harvey','N/A')}")

    all_results[asset_key] = asset_result

    # Print asset summary
    print(f"\n  --- Summary for {asset_key} ---")
    print(f"  {'Model':<20} {'QLIKE':>10} {'DM t':>10} {'Harvey sig':>12} {'Better?':>8}")
    print(f"  {'-'*62}")
    for m_name, m_eval in asset_result['models'].items():
        if m_eval.get('status') == 'completed':
            q = m_eval['qlike']
            dt = m_eval['dm_t_vs_gjr']
            sig = m_eval['significant_harvey']
            better = m_eval['model_better']
            print(f"  {m_name:<20} {q:>10.4f} {dt:>10.4f} {'YES' if sig else 'NO':>12} {'YES' if better else 'NO':>8}")
        else:
            print(f"  {m_name:<20} {'INSUFFICIENT DATA':>42}")


# ============================================================
# CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY: Local Fear Indices for MF-GJR-X")
print("=" * 70)

sig_wins = []
best_per_asset = {}

for asset_key in ASSET_CONFIGS:
    if asset_key not in all_results or all_results[asset_key].get('status') != 'completed':
        continue

    models = all_results[asset_key]['models']
    best_model = None
    best_dm = 0

    for m_name, m_eval in models.items():
        if m_eval.get('status') != 'completed':
            continue
        dm_t = m_eval['dm_t_vs_gjr']
        if m_eval['significant_harvey'] and m_eval['model_better']:
            sig_wins.append(f"{asset_key}/{m_name} (DM t={dm_t:.2f})")
        # Track best (most negative DM t = biggest improvement)
        if dm_t < best_dm:
            best_dm = dm_t
            best_model = m_name

    best_per_asset[asset_key] = (best_model, best_dm)

print(f"\nSignificant wins (Harvey |t|>3.0, model better):")
if sig_wins:
    for w in sig_wins:
        print(f"  * {w}")
else:
    print("  (none)")

print(f"\nBest model per asset:")
for asset_key, (model, dm) in best_per_asset.items():
    if model:
        print(f"  {asset_key}: {model} (DM t={dm:.4f})")
    else:
        print(f"  {asset_key}: no improvement over GJR")

n_sig = len(sig_wins)
n_assets = len([k for k in ASSET_CONFIGS if all_results.get(k, {}).get('status') == 'completed'])

if n_sig >= 3:
    conclusion = f"Local fear indices significantly improve MF-GJR-X in {n_sig}/{n_assets} asset-model combinations. Local implied vol is key for cross-market generalization."
elif n_sig >= 1:
    conclusion = f"Partial success: {n_sig}/{n_assets} significant improvements. Local fear indices help some but not all markets."
else:
    conclusion = "NULL result: No local fear index achieves Harvey-significant improvement over GJR. The multiplicative structure may inherently depend on high-quality implied vol data."

print(f"\nConclusion: {conclusion}")

# ============================================================
# SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\nTotal elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")

results = {
    'assets': all_results,
    'summary': {
        'n_assets_tested': n_assets,
        'significant_wins': sig_wins,
        'n_significant_wins': n_sig,
        'best_per_asset': {k: {'model': v[0], 'dm_t': round(v[1], 4) if v[1] else None}
                           for k, v in best_per_asset.items()},
        'conclusion': conclusion,
    },
    'metadata': {
        'experiment_id': EXPERIMENT_ID,
        'base_experiments': 'K988/K994',
        'research_question': 'Can local fear indices improve MF-GJR-X for non-US assets where US VIX fails?',
        'model_spec': 'A4f: τ=θ₀+θ₁X², free ω; dual: τ=θ₀+θ₁X₁²+θ₂X₂²',
        'fear_indices_tested': {
            'EEM': ['US VIX', 'own 20d RV', 'VIX+RV dual', 'VXEEM (if available)', 'VIX+VXEEM dual'],
            'GLD': ['US VIX', 'own 20d RV', 'VIX+RV dual', 'GVZ (if available)', 'VIX+GVZ dual'],
            '0050.TW': ['US VIX (lag+1)', 'own 20d RV', 'VIX+RV dual', 'VIX lag+2'],
        },
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'rv_window': RV_WINDOW,
        'evaluation': 'QLIKE on r² (Patton 2011), DM test (Harvey t>3.0)',
        'elapsed_seconds': round(elapsed, 1),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'references': [
            'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
            'Harvey et al. (2016). t > 3.0 threshold.',
            'Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.',
        ],
    },
}


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        return super().default(obj)


with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
print(f"\nResults saved to {RESULTS_PATH}")
print("Done!")
