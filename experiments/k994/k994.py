#!/usr/bin/env python3
"""
K994: Cross-Asset Validation of Multiplicative GJR-X (A4f Specification)
========================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988/K988b found A4f (τ=θ₀+θ₁VIX², free ω, GJR g_t, τ_t denominator) as the
  champion specification for SPY (QLIKE=-8.3608, DM t=+4.48 vs GJR).
  This experiment validates generalizability across 4 assets:
    1. QQQ  (high-beta tech)   + ^VIX
    2. EEM  (emerging markets)  + ^VIX
    3. GLD  (gold, low VIX correlation) + ^VIX
    4. 0050.TW (Taiwan ETF)    + ^VIX (lagged +1 day for timezone)

  Each asset tested with: A4f (free omega), A4 (constrained), GJR benchmark
  OOS: 2019-2026, window=2000, refit every 63 days
  Evaluation: QLIKE on r² (Patton 2011), DM test (Harvey t>3.0), Spearman ρ

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
EXPERIMENT_ID = "K994"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func, spearman_corr
from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k994_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit

ASSETS = {
    'QQQ': {'ticker': 'QQQ', 'vix_lag': 0, 'label': 'High-beta tech'},
    'EEM': {'ticker': 'EEM', 'vix_lag': 0, 'label': 'Emerging markets'},
    'GLD': {'ticker': 'GLD', 'vix_lag': 0, 'label': 'Gold (low VIX corr)'},
    '0050.TW': {'ticker': '0050.TW', 'vix_lag': 1, 'label': 'Taiwan ETF (VIX lag+1)'},
}

print("=" * 70)
print(f"{EXPERIMENT_ID}: Cross-Asset Validation of MF-GJR-X (A4f)")
print("  Testing A4f vs A4 vs GJR on QQQ/EEM/GLD/0050.TW")
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


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_mfgjr_x(returns, vix_vals, free_omega=False):
    """
    Fit multiplicative GJR-X model with τ_t = max(θ₀ + θ₁ × VIX²_{t-1}, eps).

    denom_mode = 'tau_t' (consistent with K988 A4f winner).
    free_omega: if True, ω is free; if False, ω = 1 - α - γ/2 - β.

    Parameters:
      returns: array of log returns
      vix_vals: array of VIX values (already aligned, same length as returns)
    """
    n = len(returns)

    # Lagged VIX (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    # OLS initial guess for theta
    r2_pos = np.maximum(returns**2, 1e-16)
    log_r2 = np.log(r2_pos)
    X = np.column_stack([np.ones(n), vix_lag**2])
    theta_init = np.linalg.lstsq(X, log_r2, rcond=None)[0]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8

    def neg_loglik(params):
        if free_omega:
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
        else:
            theta0, theta1, alpha, gamma_p, beta = params
            omega_g = 1.0 - alpha - gamma_p / 2.0 - beta

        if omega_g <= 0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10

        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg if free_omega else 1.0
        ll = 0.0

        for t in range(1, n):
            # denom_mode = tau_t (current period tau)
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

    if free_omega:
        starts = [
            [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        ]
        bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
                  (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    else:
        starts = [
            [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.5, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 1.5, 0.08, 0.10, 0.80],
        ]
        bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
                  (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

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


def compute_tau_vix2(theta0, theta1, vix_lag):
    """Compute τ = max(θ₀ + θ₁ × VIX²_lag, eps)."""
    return np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)


def oos_forecast_gjr(ret, vix, oos_mask, window, refit_every):
    """OOS forecasting for GJR-GARCH."""
    n = len(ret)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every  # force initial fit

    for i, t in enumerate(oos_indices):
        # Refit?
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr(train_ret)
            if params is None:
                continue
            last_fit = t

            # Rebuild h series up to t
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
            # Update h recursively with actual return
            h_prev = gjr_forecast_1step(params, h_prev, r_prev)
            r_prev = ret[t-1]

        # Forecast for t
        forecasts[i] = gjr_forecast_1step(params, h_prev, r_prev)

    return forecasts


def oos_forecast_mfgjr(ret, vix, oos_mask, window, refit_every, free_omega=False):
    """OOS forecasting for Multiplicative GJR-X (A4/A4f)."""
    n = len(ret)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every

    for i, t in enumerate(oos_indices):
        # Refit?
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            train_vix = vix[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_mfgjr_x(train_ret, train_vix, free_omega=free_omega)
            if params is None:
                continue
            last_fit = t

            # Rebuild g series up to end of training
            if free_omega:
                theta0, theta1, omega_g, alpha, gamma_p, beta = params
            else:
                theta0, theta1, alpha, gamma_p, beta = params
                omega_g = 1.0 - alpha - gamma_p / 2.0 - beta

            n_train = len(train_ret)
            vix_lag_train = np.empty(n_train)
            vix_lag_train[0] = train_vix[0]
            vix_lag_train[1:] = train_vix[:-1]
            tau_train = compute_tau_vix2(theta0, theta1, vix_lag_train)

            persist = alpha + gamma_p / 2.0 + beta
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g_series = np.empty(n_train)
            g_series[0] = eg if free_omega else 1.0

            for s in range(1, n_train):
                u_prev = train_ret[s-1] / np.sqrt(tau_train[s])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g_series[s] = omega_g + alpha * u_prev**2 + asym + beta * g_series[s-1]
                g_series[s] = max(g_series[s], 1e-10)

            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
            vix_prev = train_vix[-1]
        else:
            # Recursive update with actual return
            if free_omega:
                theta0, theta1, omega_g, alpha, gamma_p, beta = params
            else:
                theta0, theta1, alpha, gamma_p, beta = params
                omega_g = 1.0 - alpha - gamma_p / 2.0 - beta

            # tau for current step uses lagged VIX
            tau_curr = max(theta0 + theta1 * vix[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_prev = omega_g + alpha * u_prev**2 + asym + beta * g_prev
            g_prev = max(g_prev, 1e-10)
            r_prev_val = ret[t-1]
            vix_prev = vix[t-1]

        # Forecast sigma²_t = tau_t × g_t
        # tau_t uses VIX_{t-1} (lagged)
        if free_omega:
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
        else:
            theta0, theta1, alpha, gamma_p, beta = params
            omega_g = 1.0 - alpha - gamma_p / 2.0 - beta

        tau_t = max(theta0 + theta1 * vix[t-1]**2, 1e-16)

        # g forecast: use r_{t-1} and tau_t
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        asym_fc = gamma_p * u_prev_fc**2 if u_prev_fc < 0 else 0.0
        g_fc = omega_g + alpha * u_prev_fc**2 + asym_fc + beta * g_prev
        g_fc = max(g_fc, 1e-10)

        forecasts[i] = tau_t * g_fc

    return forecasts


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Load VIX first (common across all assets)
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy()
print(f"  VIX: {len(vix_series)} observations")

# ============================================================
# MAIN LOOP: Each asset
# ============================================================
all_results = {}

for asset_key, asset_info in ASSETS.items():
    ticker = asset_info['ticker']
    vix_lag_extra = asset_info['vix_lag']
    label = asset_info['label']

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

    # Clean 0050.TW data if needed
    if asset_key == '0050.TW':
        prices, _ = clean_tw50_data(prices)

    log_ret = np.log(prices / prices.shift(1))

    # Align with VIX
    if vix_lag_extra > 0:
        # For Taiwan: use VIX from vix_lag_extra days earlier
        vix_aligned = vix_series.shift(vix_lag_extra)
        df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_aligned})
    else:
        df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_series})

    df = df.dropna()

    # Check sufficient data
    if len(df) < WINDOW + 252:
        print(f"  SKIP: insufficient aligned data ({len(df)} obs, need {WINDOW+252})")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient aligned data ({len(df)})'}
        continue

    oos_mask = np.array(df.index >= OOS_START)
    n_total = len(df)
    n_oos = oos_mask.sum()

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
    print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

    if n_oos < 252:
        print(f"  SKIP: insufficient OOS data ({n_oos} obs)")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient OOS ({n_oos})'}
        continue

    ret = df['log_ret'].values
    vix_vals = df['VIX'].values
    r2 = ret ** 2

    # Diagnostics
    oos_ret = ret[oos_mask]
    print(f"  OOS mean return (ann.): {np.mean(oos_ret)*252:.4f}")
    print(f"  OOS vol (ann.): {np.std(oos_ret)*np.sqrt(252):.4f}")
    print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
    print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
    corr_vix_r2 = np.corrcoef(vix_vals[oos_mask], r2[oos_mask])[0, 1]
    print(f"  VIX-r² correlation (OOS): {corr_vix_r2:.4f}")

    # --- Model 1: GJR-GARCH ---
    print(f"\n  [GJR] Fitting OOS forecasts...")
    t0 = time.time()
    fc_gjr = oos_forecast_gjr(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY)
    t_gjr = time.time() - t0
    print(f"    Done in {t_gjr:.1f}s")

    # --- Model 2: A4 (constrained omega) ---
    print(f"  [A4] Fitting OOS forecasts...")
    t0 = time.time()
    fc_a4 = oos_forecast_mfgjr(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY, free_omega=False)
    t_a4 = time.time() - t0
    print(f"    Done in {t_a4:.1f}s")

    # --- Model 3: A4f (free omega) ---
    print(f"  [A4f] Fitting OOS forecasts...")
    t0 = time.time()
    fc_a4f = oos_forecast_mfgjr(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY, free_omega=True)
    t_a4f = time.time() - t0
    print(f"    Done in {t_a4f:.1f}s")

    # --- Evaluation ---
    oos_r2 = r2[oos_mask]
    valid = ~np.isnan(fc_gjr) & ~np.isnan(fc_a4) & ~np.isnan(fc_a4f) & (oos_r2 > 0)

    if valid.sum() < 252:
        print(f"  WARNING: only {valid.sum()} valid OOS obs, results may be unreliable")

    # QLIKE (lower = better)
    qlike_gjr = qlike_func(oos_r2[valid], fc_gjr[valid])
    qlike_a4 = qlike_func(oos_r2[valid], fc_a4[valid])
    qlike_a4f = qlike_func(oos_r2[valid], fc_a4f[valid])

    # Spearman
    rho_gjr, p_gjr = spearman_corr(oos_r2[valid], fc_gjr[valid])
    rho_a4, p_a4 = spearman_corr(oos_r2[valid], fc_a4[valid])
    rho_a4f, p_a4f = spearman_corr(oos_r2[valid], fc_a4f[valid])

    # DM tests vs GJR
    # Pointwise QLIKE loss: l_t = log(h_t) + r²_t / h_t
    loss_gjr = np.log(fc_gjr[valid]) + oos_r2[valid] / fc_gjr[valid]
    loss_a4 = np.log(fc_a4[valid]) + oos_r2[valid] / fc_a4[valid]
    loss_a4f = np.log(fc_a4f[valid]) + oos_r2[valid] / fc_a4f[valid]

    # DM test: positive t = model better than GJR
    dm_t_a4, dm_p_a4 = dm_test(loss_a4, loss_gjr)
    dm_t_a4f, dm_p_a4f = dm_test(loss_a4f, loss_gjr)
    dm_t_a4f_vs_a4, dm_p_a4f_vs_a4 = dm_test(loss_a4f, loss_a4)

    n_valid = int(valid.sum())

    # Refit to get final parameters for reporting
    train_end = np.where(oos_mask)[0][0]
    train_ret_final = ret[max(0, train_end - WINDOW):train_end]
    train_vix_final = vix_vals[max(0, train_end - WINDOW):train_end]

    params_a4f_final = fit_mfgjr_x(train_ret_final, train_vix_final, free_omega=True)
    params_a4_final = fit_mfgjr_x(train_ret_final, train_vix_final, free_omega=False)
    params_gjr_final = fit_gjr(train_ret_final)

    print(f"\n  === Results for {asset_key} ===")
    print(f"  {'Model':<10} {'QLIKE':>10} {'Spearman ρ':>12} {'DM t vs GJR':>14} {'Harvey sig':>12}")
    print(f"  {'-'*58}")
    print(f"  {'GJR':<10} {qlike_gjr:>10.4f} {rho_gjr:>12.4f} {'(baseline)':>14} {'-':>12}")
    print(f"  {'A4':<10} {qlike_a4:>10.4f} {rho_a4:>12.4f} {dm_t_a4:>14.4f} {'YES' if abs(dm_t_a4)>3.0 else 'NO':>12}")
    print(f"  {'A4f':<10} {qlike_a4f:>10.4f} {rho_a4f:>12.4f} {dm_t_a4f:>14.4f} {'YES' if abs(dm_t_a4f)>3.0 else 'NO':>12}")
    print(f"  A4f vs A4: DM t = {dm_t_a4f_vs_a4:.4f} ({'sig' if abs(dm_t_a4f_vs_a4)>3.0 else 'not sig'})")

    # Store results
    asset_result = {
        'status': 'completed',
        'label': label,
        'n_total': n_total,
        'n_oos': n_oos,
        'n_valid': n_valid,
        'vix_r2_corr_oos': round(float(corr_vix_r2), 4),
        'diagnostics': {
            'oos_mean_return_ann': round(float(np.mean(oos_ret) * 252), 4),
            'oos_vol_ann': round(float(np.std(oos_ret) * np.sqrt(252)), 4),
            'oos_skewness': round(float(stats.skew(oos_ret)), 3),
            'oos_kurtosis': round(float(stats.kurtosis(oos_ret)), 3),
        },
        'models': {
            'GJR': {
                'qlike': round(float(qlike_gjr), 6),
                'spearman_rho': round(float(rho_gjr), 4),
                'spearman_p': float(p_gjr),
                'params': [round(float(p), 8) for p in params_gjr_final] if params_gjr_final is not None else None,
            },
            'A4': {
                'qlike': round(float(qlike_a4), 6),
                'spearman_rho': round(float(rho_a4), 4),
                'spearman_p': float(p_a4),
                'params': [round(float(p), 8) for p in params_a4_final] if params_a4_final is not None else None,
            },
            'A4f': {
                'qlike': round(float(qlike_a4f), 6),
                'spearman_rho': round(float(rho_a4f), 4),
                'spearman_p': float(p_a4f),
                'params': [round(float(p), 8) for p in params_a4f_final] if params_a4f_final is not None else None,
            },
        },
        'dm_tests': {
            'A4_vs_GJR': {
                'dm_t': round(float(dm_t_a4), 4),
                'dm_p': float(dm_p_a4),
                'significant_harvey': str(abs(dm_t_a4) > 3.0),
                'direction': 'model_better' if dm_t_a4 > 0 else 'gjr_better',
            },
            'A4f_vs_GJR': {
                'dm_t': round(float(dm_t_a4f), 4),
                'dm_p': float(dm_p_a4f),
                'significant_harvey': str(abs(dm_t_a4f) > 3.0),
                'direction': 'model_better' if dm_t_a4f > 0 else 'gjr_better',
            },
            'A4f_vs_A4': {
                'dm_t': round(float(dm_t_a4f_vs_a4), 4),
                'dm_p': float(dm_p_a4f_vs_a4),
                'significant_harvey': str(abs(dm_t_a4f_vs_a4) > 3.0),
            },
        },
        'elapsed_seconds': round(t_gjr + t_a4 + t_a4f, 1),
    }
    all_results[asset_key] = asset_result


# ============================================================
# SUMMARY TABLE
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: Cross-Asset Validation of A4f Specification")
print("=" * 70)

# Count Harvey-significant wins
n_tested = 0
n_a4f_sig = 0
n_a4_sig = 0

print(f"\n{'Asset':<10} {'GJR QLIKE':>10} {'A4 QLIKE':>10} {'A4f QLIKE':>10} {'DM t(A4f)':>10} {'Harvey sig':>12}")
print("-" * 62)

for asset_key in ASSETS:
    if asset_key not in all_results or all_results[asset_key].get('status') != 'completed':
        print(f"{asset_key:<10} {'SKIPPED':>42}")
        continue

    r = all_results[asset_key]
    qg = r['models']['GJR']['qlike']
    qa = r['models']['A4']['qlike']
    qaf = r['models']['A4f']['qlike']
    dt = r['dm_tests']['A4f_vs_GJR']['dm_t']
    sig = r['dm_tests']['A4f_vs_GJR']['significant_harvey']
    n_tested += 1
    if sig == 'True':
        n_a4f_sig += 1
    if r['dm_tests']['A4_vs_GJR']['significant_harvey'] == 'True':
        n_a4_sig += 1

    print(f"{asset_key:<10} {qg:>10.4f} {qa:>10.4f} {qaf:>10.4f} {dt:>10.4f} {sig:>12}")

print(f"\nA4f significant wins: {n_a4f_sig}/{n_tested}")
print(f"A4  significant wins: {n_a4_sig}/{n_tested}")

if n_a4f_sig >= 3:
    conclusion = "A4f generalizes well — significant improvement over GJR in >= 3/4 assets"
elif n_a4f_sig >= 2:
    conclusion = "A4f shows moderate generalization — significant in 2/4 assets"
elif n_a4f_sig >= 1:
    conclusion = "A4f shows limited generalization — significant in only 1/4 assets"
else:
    conclusion = "A4f does NOT generalize — no significant improvement in other assets, may be SPY-specific"

print(f"\nConclusion: {conclusion}")

# ============================================================
# SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\nTotal elapsed time: {elapsed:.1f}s ({elapsed/60:.1f}m)")

results = {
    'assets': all_results,
    'summary': {
        'n_assets_tested': n_tested,
        'a4f_significant_wins': n_a4f_sig,
        'a4_significant_wins': n_a4_sig,
        'conclusion': conclusion,
    },
    'metadata': {
        'experiment_id': EXPERIMENT_ID,
        'base_experiment': 'K988/K988b',
        'model_spec': 'A4f: τ=θ₀+θ₁VIX², free ω, GJR g_t, τ_t denominator',
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'evaluation': 'QLIKE on r² (Patton 2011)',
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
        return super().default(obj)

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
print(f"\nResults saved to {RESULTS_PATH}")
print("Done!")
