#!/usr/bin/env python3
"""
K1032: A4f Cross-Market Validation — Japanese Equity (N225 + EWJ)
=================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  A4f multiplicative GARCH-X has been validated for:
  - SPY (K988/K1000): DM t=+4.48 (champion)
  - European STOXX50E/FEZ (K1030): DM t=-3.64/-3.45 (2/2 sig)
  This experiment extends to Japanese equity.

  Japan is interesting because:
  - N225 has lead-lag with US (US leads, Japan follows)
  - Trading hours 09:00-15:00 JST, no overlap with US
  - EWJ leverage effect weaker (gamma=0.087 < SPY 0.12)
  - Japanese VIX (^JN1, VNKY) NOT available via yfinance
  - Use RV20 (own 20-day realized vol) as local fear proxy

  VIX alignment note for Japan:
  - N225 trades ~16 hours before US market opens
  - VIX from t-1 (previous US trading day) is already known when
    Japanese market opens on day t
  - For EWJ (US-traded Japan ETF), VIX is same-day available (no lag)

Data: yfinance 2005-2026.
OOS: 2019-01-01 onwards, window=2000, refit/63d, seed=42.

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test (Harvey t>3.0)
  - VaR 2.5% and 1% Kupiec test
  - ES backtesting (Acerbi & Szekely 2014)
  - Spearman rank correlation
  - VIX regime-conditional QLIKE

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.
  - Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement
    Models. Journal of Derivatives 3:73-84.
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall.
  - K988: A4f champion for SPY (DM t=+4.48 vs GJR)
  - K994: Cross-asset (QQQ pass, GLD/EEM/0050.TW not sig with US VIX)
  - K997: Local fear indices (GLD+GVZ pass, own RV for EEM/0050.TW)
  - K1022: Cross-asset robustness with Student-t df=8
  - K1030: European A4f-VIX DM t=-3.64/-3.45 (2/2 sig)
  - K756: VIX tested 12 international markets (crude method)

Author: VolPred Research System
Date: 2026-04-10
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
from scipy.special import gammaln
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1032"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1032_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8
RV_WINDOW = 20  # 20-day realized vol window

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Cross-Market — Japanese Equity (N225 + EWJ)")
print("  Testing VIX and own-RV20 as A4f τ drivers")
print("=" * 70)


# ============================================================
# GARCH RECURSIONS
# ============================================================

def gjr_recursion(omega, alpha, gamma, beta, returns):
    """GJR-GARCH(1,1) variance recursion."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns[:min(250, T)])
    for t in range(1, T):
        u2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * u2 + gamma * u2 * ind + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h


def student_t_const(df):
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))

T_CONST_8 = student_t_const(DF_FIXED)


def gjr_nll_t(omega, alpha, gamma, beta, df, t_const, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2):
    """A4f multiplicative GARCH-X recursion.
    τ_t = max(θ₀ + θ₁ × fear²_{t-1}, eps)
    u_{t-1} = r_{t-1} / sqrt(τ_t)
    g_t = ω + α u² + γ u² I(u<0) + β g_{t-1}
    σ²_t = τ_t × g_t
    """
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)

    tau[0] = theta0 + theta1 * fear2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, T):
        tau[t] = theta0 + theta1 * fear2[t-1]
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16

    return h, tau, g


def a4f_nll_t(theta0, theta1, omega, alpha, gamma, beta, df, t_const, returns, fear2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


# ============================================================
# MODEL FITTING
# ============================================================

def fit_gjr_t(returns, df=DF_FIXED):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
        [var0 * 0.01, 0.04, 0.04, 0.92],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def nll(params):
        omega, alpha, gamma, beta = params
        if alpha + gamma / 2 + beta >= 0.999:
            return 1e10
        return gjr_nll_t(omega, alpha, gamma, beta, float(df), T_CONST_8, returns)

    for s in starts:
        try:
            res = optimize.minimize(nll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def fit_a4f_t(returns, fear_vals, df=DF_FIXED):
    var0 = np.var(returns)
    fear2_mean = np.mean(fear_vals**2) + 1e-8
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / fear2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / fear2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / fear2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / fear2_mean * 2.0, 0.08, 0.04, 0.04, 0.92],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def nll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if alpha + gamma_p / 2 + beta >= 0.999 or omega_g <= 0:
            return 1e10
        return a4f_nll_t(theta0, theta1, omega_g, alpha, gamma_p, beta,
                         float(df), T_CONST_8, returns, fear_vals**2)

    for s in starts:
        try:
            res = optimize.minimize(nll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


# ============================================================
# OOS FORECASTING
# ============================================================

def oos_forecast_gjr_t(ret, oos_mask, window, refit_every, df=DF_FIXED):
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every
    h_prev = None
    r_prev = None

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr_t(train_ret, df)
            if params is None:
                continue
            last_fit = t
            omega, alpha, gamma, beta = params
            h_series = gjr_recursion(omega, alpha, gamma, beta, train_ret)
            h_prev = h_series[-1]
            r_prev = train_ret[-1]
        else:
            omega, alpha, gamma, beta = params
            u2 = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_prev = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)
            r_prev = ret[t-1]

        if params is None:
            continue
        omega, alpha, gamma, beta = params
        u2 = ret[t-1] ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        forecasts[i] = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)

    return forecasts


def oos_forecast_a4f_t(ret, fear_vals, oos_mask, window, refit_every, df=DF_FIXED):
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every
    g_prev = None
    r_prev_val = None

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            train_fear = fear_vals[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_a4f_t(train_ret, train_fear, df)
            if params is None:
                continue
            last_fit = t
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            _, _, g_series = a4f_recursion(
                theta0, theta1, omega_g, alpha, gamma_p, beta,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
        else:
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            tau_curr = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            u2 = u_prev ** 2
            ind = 1.0 if r_prev_val < 0 else 0.0
            g_prev = max(omega_g + alpha * u2 + gamma_p * u2 * ind + beta * g_prev, 1e-10)
            r_prev_val = ret[t-1]

        if params is None:
            continue
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        u2_fc = u_prev_fc ** 2
        ind_fc = 1.0 if ret[t-1] < 0 else 0.0
        g_fc = max(omega_g + alpha * u2_fc + gamma_p * u2_fc * ind_fc + beta * g_prev, 1e-10)
        forecasts[i] = tau_t * g_fc

    return forecasts


# ============================================================
# VAR / ES BACKTESTING
# ============================================================

def var_backtest_kupiec(returns_oos, forecasts, alpha_level=0.025, df=DF_FIXED):
    valid = ~np.isnan(forecasts)
    ret = returns_oos[valid]
    fc = forecasts[valid]
    n = len(ret)
    if n < 100:
        return np.nan, alpha_level, np.nan, np.nan, 'SKIP'

    t_q = stats.t.ppf(alpha_level, df)
    var_series = t_q * np.sqrt(fc * (df - 2) / df)
    violations = (ret < var_series).sum()
    vr = violations / n

    if violations == 0:
        lr = -2 * n * np.log(1 - alpha_level)
    elif violations == n:
        lr = -2 * n * np.log(alpha_level)
    else:
        lr = -2 * (np.log((1 - alpha_level)**(n - violations) * alpha_level**violations)
                    - np.log((1 - vr)**(n - violations) * vr**violations))

    p_value = 1 - stats.chi2.cdf(lr, 1)
    pass_flag = 'PASS' if p_value > 0.05 else 'FAIL'
    return float(vr), alpha_level, float(lr), float(p_value), pass_flag


def es_backtest(returns_oos, forecasts, alpha_level=0.025, df=DF_FIXED):
    valid = ~np.isnan(forecasts)
    ret = returns_oos[valid]
    fc = forecasts[valid]
    n = len(ret)
    if n < 100:
        return np.nan, np.nan, np.nan, 'SKIP'

    t_q = stats.t.ppf(alpha_level, df)
    scale = np.sqrt((df - 2) / df)
    var_series = t_q * scale * np.sqrt(fc)

    t_pdf = stats.t.pdf(t_q, df)
    es_factor = -(df + t_q**2) / (df - 1) * t_pdf / alpha_level
    es_series = es_factor * scale * np.sqrt(fc)

    violations_mask = ret < var_series
    n_viol = violations_mask.sum()
    if n_viol == 0:
        return 0.0, np.nan, np.nan, 'SKIP'

    z_stat = 1 / (n * alpha_level) * np.sum(ret[violations_mask] / es_series[violations_mask]) + 1
    p_value = stats.norm.cdf(z_stat)
    pass_flag = 'PASS' if p_value > 0.05 else 'FAIL'
    return float(z_stat), float(p_value), float(n_viol / n), pass_flag


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

# Load VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy() / 100.0
print(f"  VIX: {len(vix_series)} obs ({vix_series.index[0].strftime('%Y-%m-%d')} to {vix_series.index[-1].strftime('%Y-%m-%d')})")

# Assets to test
# N225: Japanese index, trades 09:00-15:00 JST.
#   VIX from t-1 is already known (US market closed hours before Japan opens)
#   Use vix_lag=1 to shift VIX by 1 day (previous US close predicts today's Japan vol)
# EWJ: US-traded Japan ETF, trades during US hours. VIX is same-day (lag=0).
ASSETS = {
    '^N225': {
        'label': 'Nikkei 225 Index',
        'vix_lag': 1,  # Japan opens after US closes; use previous day VIX
    },
    'EWJ': {
        'label': 'iShares MSCI Japan ETF (US-traded)',
        'vix_lag': 0,  # Trades in US hours, same-day VIX available
    },
}

all_results = {}

for asset_key, asset_info in ASSETS.items():
    label = asset_info['label']
    vix_lag = asset_info['vix_lag']

    print(f"\n{'='*60}")
    print(f"  Asset: {asset_key} ({label})")
    print(f"  VIX lag: {vix_lag} day(s)")
    print(f"{'='*60}")

    # Download price data
    raw = yf.download(asset_key, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    if len(raw) < 1000:
        print(f"  SKIP: insufficient data ({len(raw)} obs)")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient data ({len(raw)})'}
        continue

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    # Compute 20d realized volatility (annualized std of returns)
    rv20 = log_ret.rolling(RV_WINDOW).std() * np.sqrt(252)

    # Align with VIX — use shift for lag
    vix_aligned = vix_series.shift(vix_lag) if vix_lag > 0 else vix_series

    # For N225: trading calendars differ (Japan holidays vs US holidays)
    # Use reindex + ffill to align VIX to asset trading days
    vix_reindexed = vix_aligned.reindex(prices.index, method='ffill')

    df_data = pd.DataFrame({
        'price': prices,
        'log_ret': log_ret,
        'VIX': vix_reindexed,
        'RV20': rv20,
    })
    df_data = df_data.dropna()
    n_total = len(df_data)

    print(f"  Raw data: {len(raw)} obs ({raw.index[0].strftime('%Y-%m-%d')} to {raw.index[-1].strftime('%Y-%m-%d')})")
    print(f"  Aligned data: {df_data.index[0].strftime('%Y-%m-%d')} to {df_data.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

    if n_total < WINDOW + 252:
        print(f"  SKIP: insufficient aligned data ({n_total} obs, need {WINDOW+252})")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient aligned data ({n_total})'}
        continue

    oos_mask = np.array(df_data.index >= OOS_START)
    n_oos = oos_mask.sum()
    print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

    if n_oos < 252:
        print(f"  SKIP: insufficient OOS ({n_oos})")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient OOS ({n_oos})'}
        continue

    ret = df_data['log_ret'].values
    vix_vals = df_data['VIX'].values
    rv20_vals = df_data['RV20'].values
    r2 = ret ** 2

    # ---- Descriptive statistics ----
    oos_ret = ret[oos_mask]
    oos_r2 = r2[oos_mask]

    corr_vix_r2 = np.corrcoef(vix_vals[oos_mask], oos_r2)[0, 1]
    corr_rv20_r2 = np.corrcoef(rv20_vals[oos_mask], oos_r2)[0, 1]
    corr_vix_rv20 = np.corrcoef(vix_vals[oos_mask], rv20_vals[oos_mask])[0, 1]

    desc = {
        'n_total': int(n_total),
        'n_oos': int(n_oos),
        'data_start': df_data.index[0].strftime('%Y-%m-%d'),
        'data_end': df_data.index[-1].strftime('%Y-%m-%d'),
        'oos_mean_return_ann': float(np.mean(oos_ret) * 252),
        'oos_vol_ann': float(np.std(oos_ret) * np.sqrt(252)),
        'oos_skewness': float(stats.skew(oos_ret)),
        'oos_kurtosis': float(stats.kurtosis(oos_ret)),
        'corr_vix_r2_oos': float(corr_vix_r2),
        'corr_rv20_r2_oos': float(corr_rv20_r2),
        'corr_vix_rv20_oos': float(corr_vix_rv20),
        'vix_lag_used': vix_lag,
    }

    print(f"  OOS mean ret (ann.): {desc['oos_mean_return_ann']:.4f}")
    print(f"  OOS vol (ann.): {desc['oos_vol_ann']:.4f}")
    print(f"  OOS skew: {desc['oos_skewness']:.3f}, kurtosis: {desc['oos_kurtosis']:.3f}")
    print(f"  VIX-r² corr (OOS):  {corr_vix_r2:.4f}")
    print(f"  RV20-r² corr (OOS): {corr_rv20_r2:.4f}")
    print(f"  VIX-RV20 corr (OOS): {corr_vix_rv20:.4f}")

    # ---- Model 1: GJR-t ----
    print(f"\n  [M1] GJR-t(df={DF_FIXED})...")
    t0 = time.time()
    fc_gjr = oos_forecast_gjr_t(ret, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
    t_gjr = time.time() - t0
    valid_gjr = int(np.sum(~np.isnan(fc_gjr)))
    print(f"    Done in {t_gjr:.1f}s, valid={valid_gjr}")

    # ---- Model 2: A4f-VIX-t ----
    print(f"\n  [M2] A4f-VIX-t(df={DF_FIXED})...")
    t0 = time.time()
    fc_a4f_vix = oos_forecast_a4f_t(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
    t_a4f_vix = time.time() - t0
    valid_a4f_vix = int(np.sum(~np.isnan(fc_a4f_vix)))
    print(f"    Done in {t_a4f_vix:.1f}s, valid={valid_a4f_vix}")

    # ---- Model 3: A4f-RV20-t ----
    print(f"\n  [M3] A4f-RV20-t(df={DF_FIXED})...")
    t0 = time.time()
    fc_a4f_rv20 = oos_forecast_a4f_t(ret, rv20_vals, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
    t_a4f_rv20 = time.time() - t0
    valid_a4f_rv20 = int(np.sum(~np.isnan(fc_a4f_rv20)))
    print(f"    Done in {t_a4f_rv20:.1f}s, valid={valid_a4f_rv20}")

    # ---- Evaluation ----
    print(f"\n  --- Evaluation ---")
    oos_indices = np.where(oos_mask)[0]
    oos_r2_vals = r2[oos_indices]

    valid = ~np.isnan(fc_gjr) & ~np.isnan(fc_a4f_vix) & ~np.isnan(fc_a4f_rv20)
    fc_gjr_v = fc_gjr[valid]
    fc_vix_v = fc_a4f_vix[valid]
    fc_rv20_v = fc_a4f_rv20[valid]
    r2_v = oos_r2_vals[valid]
    ret_v = ret[oos_indices][valid]
    n_valid = len(r2_v)
    print(f"  Valid aligned obs: {n_valid}")

    # QLIKE
    qlike_gjr = float(qlike_func(r2_v, fc_gjr_v))
    qlike_vix = float(qlike_func(r2_v, fc_vix_v))
    qlike_rv20 = float(qlike_func(r2_v, fc_rv20_v))
    print(f"  QLIKE GJR:      {qlike_gjr:.6f}")
    print(f"  QLIKE A4f-VIX:  {qlike_vix:.6f}")
    print(f"  QLIKE A4f-RV20: {qlike_rv20:.6f}")

    # Compute QLIKE losses for DM test
    loss_gjr = np.log(fc_gjr_v) + r2_v / fc_gjr_v
    loss_vix = np.log(fc_vix_v) + r2_v / fc_vix_v
    loss_rv20 = np.log(fc_rv20_v) + r2_v / fc_rv20_v

    # DM tests: negative t → first model better
    dm_vix_t, dm_vix_p = dm_test(loss_vix, loss_gjr)
    dm_rv20_t, dm_rv20_p = dm_test(loss_rv20, loss_gjr)
    dm_rv20_vs_vix_t, dm_rv20_vs_vix_p = dm_test(loss_rv20, loss_vix)

    print(f"\n  DM Tests (Harvey |t|>3.0):")
    print(f"    A4f-VIX vs GJR:     t={dm_vix_t:.3f}, p={dm_vix_p:.4f}, {'SIG' if abs(dm_vix_t)>3.0 else 'n.s.'}")
    print(f"    A4f-RV20 vs GJR:    t={dm_rv20_t:.3f}, p={dm_rv20_p:.4f}, {'SIG' if abs(dm_rv20_t)>3.0 else 'n.s.'}")
    print(f"    A4f-RV20 vs A4f-VIX: t={dm_rv20_vs_vix_t:.3f}, p={dm_rv20_vs_vix_p:.4f}")

    # Spearman (returns tuple: rho, p_value)
    sp_gjr, sp_gjr_p = spearman_corr(r2_v, fc_gjr_v)
    sp_vix, sp_vix_p = spearman_corr(r2_v, fc_vix_v)
    sp_rv20, sp_rv20_p = spearman_corr(r2_v, fc_rv20_v)
    sp_gjr = float(sp_gjr)
    sp_vix = float(sp_vix)
    sp_rv20 = float(sp_rv20)
    print(f"\n  Spearman rank corr:")
    print(f"    GJR:      {sp_gjr:.4f}")
    print(f"    A4f-VIX:  {sp_vix:.4f}")
    print(f"    A4f-RV20: {sp_rv20:.4f}")

    # VaR/ES backtesting
    var_es = {}
    print(f"\n  VaR/ES Backtesting:")
    for alpha_label, alpha_val in [('2.5%', 0.025), ('1%', 0.01)]:
        var_es[f'VaR_{alpha_label}'] = {}
        var_es[f'ES_{alpha_label}'] = {}

        for model_name, fc_arr in [('GJR', fc_gjr_v), ('A4f_VIX', fc_vix_v), ('A4f_RV20', fc_rv20_v)]:
            vr, _, lr, pv, pf = var_backtest_kupiec(ret_v, fc_arr, alpha_val, DF_FIXED)
            var_es[f'VaR_{alpha_label}'][model_name] = {'violation_rate': vr, 'kupiec_p': pv, 'pass': pf}

            z, pv_es, vr_es, pf_es = es_backtest(ret_v, fc_arr, alpha_val, DF_FIXED)
            var_es[f'ES_{alpha_label}'][model_name] = {'z_stat': z, 'p_value': pv_es, 'pass': pf_es}

            print(f"    {model_name} VaR{alpha_label}: VR={vr:.4f}, Kupiec p={pv:.4f} [{pf}] | ES: Z={z:.4f} [{pf_es}]")

    # VIX regime analysis
    print(f"\n  VIX Regime Analysis:")
    vix_oos = vix_vals[oos_indices][valid] * 100  # to percentage
    regime_results = {}
    for rname, lo, hi in [('Low (<20)', 0, 20), ('Med (20-30)', 20, 30), ('High (>30)', 30, 200)]:
        mask = (vix_oos >= lo) & (vix_oos < hi)
        n_r = mask.sum()
        if n_r < 50:
            regime_results[rname] = {'n': int(n_r), 'status': 'skipped'}
            print(f"    {rname}: n={n_r} (skip)")
            continue

        q_gjr_r = float(qlike_func(r2_v[mask], fc_gjr_v[mask]))
        q_vix_r = float(qlike_func(r2_v[mask], fc_vix_v[mask]))
        q_rv20_r = float(qlike_func(r2_v[mask], fc_rv20_v[mask]))

        loss_vix_r = loss_vix[mask]
        loss_gjr_r = loss_gjr[mask]
        dm_r_t, dm_r_p = dm_test(loss_vix_r, loss_gjr_r)

        regime_results[rname] = {
            'n': int(n_r),
            'qlike_gjr': q_gjr_r,
            'qlike_a4f_vix': q_vix_r,
            'qlike_a4f_rv20': q_rv20_r,
            'dm_t_vix_vs_gjr': float(dm_r_t),
        }
        print(f"    {rname}: n={n_r}, QLIKE GJR={q_gjr_r:.4f} VIX={q_vix_r:.4f} RV20={q_rv20_r:.4f}, DM(VIX/GJR) t={dm_r_t:.2f}")

    # QLIKE improvement %
    improve_vix = (qlike_gjr - qlike_vix) / qlike_gjr * 100
    improve_rv20 = (qlike_gjr - qlike_rv20) / qlike_gjr * 100

    # Compile per-asset results
    asset_result = {
        'status': 'completed',
        'label': label,
        'vix_lag': vix_lag,
        'descriptive_stats': desc,
        'models': {
            'GJR-t': {
                'qlike': qlike_gjr,
                'spearman': sp_gjr,
                'n_valid': valid_gjr,
                'time_s': round(t_gjr, 1),
            },
            'A4f-VIX-t': {
                'qlike': qlike_vix,
                'spearman': sp_vix,
                'n_valid': valid_a4f_vix,
                'time_s': round(t_a4f_vix, 1),
                'dm_vs_gjr_t': round(float(dm_vix_t), 4),
                'dm_vs_gjr_p': round(float(dm_vix_p), 4),
                'sig_harvey': abs(dm_vix_t) > 3.0,
            },
            'A4f-RV20-t': {
                'qlike': qlike_rv20,
                'spearman': sp_rv20,
                'n_valid': valid_a4f_rv20,
                'time_s': round(t_a4f_rv20, 1),
                'dm_vs_gjr_t': round(float(dm_rv20_t), 4),
                'dm_vs_gjr_p': round(float(dm_rv20_p), 4),
                'sig_harvey': abs(dm_rv20_t) > 3.0,
                'dm_vs_a4f_vix_t': round(float(dm_rv20_vs_vix_t), 4),
                'dm_vs_a4f_vix_p': round(float(dm_rv20_vs_vix_p), 4),
            },
        },
        'dm_tests': {
            'A4f_VIX_vs_GJR': {'dm_t': round(float(dm_vix_t), 4), 'dm_p': round(float(dm_vix_p), 4),
                                'significant_harvey': abs(dm_vix_t) > 3.0},
            'A4f_RV20_vs_GJR': {'dm_t': round(float(dm_rv20_t), 4), 'dm_p': round(float(dm_rv20_p), 4),
                                 'significant_harvey': abs(dm_rv20_t) > 3.0},
            'A4f_RV20_vs_A4f_VIX': {'dm_t': round(float(dm_rv20_vs_vix_t), 4), 'dm_p': round(float(dm_rv20_vs_vix_p), 4)},
        },
        'qlike_improvement_pct': {
            'A4f_VIX_vs_GJR': round(float(improve_vix), 2),
            'A4f_RV20_vs_GJR': round(float(improve_rv20), 2),
        },
        'var_es_backtesting': var_es,
        'regime_analysis': regime_results,
    }

    all_results[asset_key] = asset_result


# ============================================================
# SUMMARY & CHARTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")

# Count results
n_completed = sum(1 for r in all_results.values() if r.get('status') == 'completed')
n_vix_sig = 0
n_rv20_sig = 0
for akey, r in all_results.items():
    if r.get('status') != 'completed':
        continue
    qg = r['models']['GJR-t']['qlike']
    qv = r['models']['A4f-VIX-t']['qlike']
    qr = r['models']['A4f-RV20-t']['qlike']
    dt_vix = r['dm_tests']['A4f_VIX_vs_GJR']['dm_t']
    dt_rv20 = r['dm_tests']['A4f_RV20_vs_GJR']['dm_t']
    sig_vix = r['dm_tests']['A4f_VIX_vs_GJR']['significant_harvey']
    sig_rv20 = r['dm_tests']['A4f_RV20_vs_GJR']['significant_harvey']

    imp_vix = r['qlike_improvement_pct']['A4f_VIX_vs_GJR']
    imp_rv20 = r['qlike_improvement_pct']['A4f_RV20_vs_GJR']

    print(f"\n  {akey} ({r['label']}):")
    print(f"    QLIKE: GJR={qg:.4f} | A4f-VIX={qv:.4f} ({imp_vix:+.1f}%) | A4f-RV20={qr:.4f} ({imp_rv20:+.1f}%)")
    print(f"    DM(VIX/GJR): t={dt_vix:.3f} {'***SIG***' if sig_vix else '(n.s.)'}")
    print(f"    DM(RV20/GJR): t={dt_rv20:.3f} {'***SIG***' if sig_rv20 else '(n.s.)'}")

    if sig_vix:
        n_vix_sig += 1
    if sig_rv20:
        n_rv20_sig += 1

# Conclusion
conclusion_parts = []
if n_completed > 0:
    n225_r = all_results.get('^N225', {})
    ewj_r = all_results.get('EWJ', {})

    for asset_name, ar in [('N225', n225_r), ('EWJ', ewj_r)]:
        if ar.get('status') != 'completed':
            continue
        dm_vix = ar['dm_tests']['A4f_VIX_vs_GJR']['dm_t']
        dm_rv20 = ar['dm_tests']['A4f_RV20_vs_GJR']['dm_t']
        imp_vix = ar['qlike_improvement_pct']['A4f_VIX_vs_GJR']
        imp_rv20 = ar['qlike_improvement_pct']['A4f_RV20_vs_GJR']

        if abs(dm_vix) > 3.0:
            conclusion_parts.append(f"A4f-VIX significantly improves vol forecasting for {asset_name} (DM t={dm_vix:.3f}, QLIKE improvement {imp_vix:+.1f}%)")
        elif abs(dm_vix) > 2.0:
            conclusion_parts.append(f"A4f-VIX marginally improves for {asset_name} (DM t={dm_vix:.3f}, below Harvey threshold)")
        else:
            conclusion_parts.append(f"A4f-VIX does NOT significantly improve for {asset_name} (DM t={dm_vix:.3f})")

        if abs(dm_rv20) > 3.0:
            conclusion_parts.append(f"A4f-RV20 significant for {asset_name} (DM t={dm_rv20:.3f})")
        elif abs(dm_rv20) > 2.0:
            conclusion_parts.append(f"A4f-RV20 marginal for {asset_name} (DM t={dm_rv20:.3f})")
        else:
            conclusion_parts.append(f"A4f-RV20 not significant for {asset_name} (DM t={dm_rv20:.3f})")

    conclusion = "; ".join(conclusion_parts)
else:
    conclusion = "No assets completed successfully."

print(f"\n  CONCLUSION: {conclusion}")
print(f"\n  Total time: {elapsed:.1f}s")

# Save results
final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'A4f Cross-Market Validation: Japanese Equity (N225 + EWJ)',
    'status': 'completed',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': round(elapsed, 1),
    'seed': 42,
    'config': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'df_fixed': DF_FIXED,
        'rv_window': RV_WINDOW,
        'n225_vix_lag': 1,
        'ewj_vix_lag': 0,
        'note': 'Japanese VIX unavailable from yfinance; used own 20d RV as local fear proxy. N225 uses VIX lag=1 (previous US close), EWJ uses lag=0 (same-day US).',
    },
    'assets': all_results,
    'summary': {
        'n_completed': n_completed,
        'n_vix_sig_harvey': n_vix_sig,
        'n_rv20_sig_harvey': n_rv20_sig,
        'conclusion': conclusion,
    },
    'data_source': 'yfinance: ^N225, EWJ, ^VIX',
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey et al. (2016). t > 3.0 threshold for multiple testing.',
        'Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement Models.',
        'Acerbi & Szekely (2014). Back-testing Expected Shortfall.',
        'K988: A4f champion for SPY (DM t=+4.48)',
        'K994: Cross-asset (QQQ pass, others not sig with US VIX)',
        'K997: Local fear indices (GLD+GVZ pass)',
        'K1022: Cross-asset robustness with Student-t df=8',
        'K1030: European A4f-VIX DM t=-3.64/-3.45 (2/2 sig)',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")

# ============================================================
# CHARTS
# ============================================================
print("\n[CHARTS] Generating...")

completed_assets = [a for a in ASSETS if a in all_results and all_results[a].get('status') == 'completed']

if completed_assets:
    # Chart 1: QLIKE comparison grouped bar
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(completed_assets))
    width = 0.25

    gjr_qlikes = [all_results[a]['models']['GJR-t']['qlike'] for a in completed_assets]
    vix_qlikes = [all_results[a]['models']['A4f-VIX-t']['qlike'] for a in completed_assets]
    rv20_qlikes = [all_results[a]['models']['A4f-RV20-t']['qlike'] for a in completed_assets]

    b1 = ax.bar(x - width, gjr_qlikes, width, label='GJR-t(8)', color='#2196F3', edgecolor='black', linewidth=0.5)
    b2 = ax.bar(x, vix_qlikes, width, label='A4f-VIX-t(8)', color='#FF9800', edgecolor='black', linewidth=0.5)
    b3 = ax.bar(x + width, rv20_qlikes, width, label='A4f-RV20-t(8)', color='#4CAF50', edgecolor='black', linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{a}\n({all_results[a]['label'][:25]})" for a in completed_assets], fontsize=9)
    ax.set_ylabel('QLIKE (lower = better)', fontsize=11)
    ax.set_title(f'K1032: A4f Japanese Equity — QLIKE Comparison\n'
                 f'(OOS: {OOS_START} to {DATA_END}, window={WINDOW}, df={DF_FIXED})',
                 fontsize=12, fontweight='bold')
    ax.legend(fontsize=10)

    # Annotate DM values
    for i, a in enumerate(completed_assets):
        dt = all_results[a]['dm_tests']['A4f_VIX_vs_GJR']['dm_t']
        sig = "***" if abs(dt) > 3.0 else ""
        ax.annotate(f"DM={dt:.1f}{sig}", (x[i], max(gjr_qlikes[i], vix_qlikes[i], rv20_qlikes[i]) + 0.005),
                    ha='center', fontsize=8, color='#e65100')

    plt.tight_layout()
    chart1 = os.path.join(SCRIPT_DIR, 'k1032_qlike_comparison.png')
    plt.savefig(chart1, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {chart1}")

    # Chart 2: DM test summary
    fig, ax = plt.subplots(figsize=(8, 5))
    dm_labels = []
    dm_vals = []
    dm_colors = []
    for a in completed_assets:
        for test_name, color in [('A4f_VIX_vs_GJR', '#FF9800'), ('A4f_RV20_vs_GJR', '#4CAF50')]:
            dt = all_results[a]['dm_tests'][test_name]['dm_t']
            short_name = test_name.replace('_vs_GJR', '').replace('A4f_', '')
            dm_labels.append(f"{a}\n{short_name} vs GJR")
            dm_vals.append(dt)
            dm_colors.append(color)

    y_pos = np.arange(len(dm_labels))
    bars = ax.barh(y_pos, dm_vals, color=dm_colors, edgecolor='black', linewidth=0.5)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(dm_labels, fontsize=9)
    ax.axvline(3.0, color='red', linestyle='--', alpha=0.7, label='Harvey |t|=3.0')
    ax.axvline(-3.0, color='red', linestyle='--', alpha=0.7)
    ax.axvline(0, color='gray', linestyle='-', alpha=0.3)
    ax.set_xlabel('DM t-statistic (negative = A4f better)', fontsize=10)
    ax.set_title('K1032: DM Test Summary — Japanese Equity', fontsize=12, fontweight='bold')
    ax.legend(fontsize=9)

    for bar, val in zip(bars, dm_vals):
        x_pos = val + 0.1 if val >= 0 else val - 0.1
        ha = 'left' if val >= 0 else 'right'
        ax.text(x_pos, bar.get_y() + bar.get_height()/2, f'{val:.2f}',
                ha=ha, va='center', fontsize=9, fontweight='bold')

    plt.tight_layout()
    chart2 = os.path.join(SCRIPT_DIR, 'k1032_dm_summary.png')
    plt.savefig(chart2, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {chart2}")

    # Chart 3: VaR/ES scorecard heatmap (show both assets if available)
    for a in completed_assets:
        r = all_results[a]
        fig, ax = plt.subplots(figsize=(10, 4))
        models = ['GJR', 'A4f_VIX', 'A4f_RV20']
        tests = ['VaR_2.5%', 'VaR_1%', 'ES_2.5%', 'ES_1%']

        scorecard = np.zeros((len(models), len(tests)))
        for j, test in enumerate(tests):
            for i, model in enumerate(models):
                if test in r['var_es_backtesting'] and model in r['var_es_backtesting'][test]:
                    pf = r['var_es_backtesting'][test][model]['pass']
                    scorecard[i, j] = 1 if pf == 'PASS' else 0

        im = ax.imshow(scorecard, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto')
        ax.set_xticks(np.arange(len(tests)))
        ax.set_yticks(np.arange(len(models)))
        ax.set_xticklabels(tests, fontsize=10)
        ax.set_yticklabels(models, fontsize=10)
        short_name = a.replace('^', '')
        ax.set_title(f'K1032: VaR/ES Scorecard — {short_name} ({r["label"][:30]})', fontsize=12, fontweight='bold')

        for i in range(len(models)):
            for j in range(len(tests)):
                text = 'PASS' if scorecard[i, j] > 0.5 else 'FAIL'
                color = 'white' if scorecard[i, j] < 0.5 else 'black'
                ax.text(j, i, text, ha='center', va='center', fontsize=10, fontweight='bold', color=color)

        plt.tight_layout()
        chart_name = f'k1032_var_es_scorecard_{short_name}.png'
        chart_path = os.path.join(SCRIPT_DIR, chart_name)
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Saved: {chart_path}")

print(f"\n{'='*70}")
print(f"K1032 COMPLETE. Total time: {elapsed:.1f}s")
print(f"{'='*70}")
