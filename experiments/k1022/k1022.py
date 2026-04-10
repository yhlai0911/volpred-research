#!/usr/bin/env python3
"""
K1022: A4f Cross-Asset Robustness Verification (Paper 9 Core Robustness Check)
==============================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 established A4f (τ=θ₀+θ₁×VIX², free ω, GJR g_t) as champion for SPY
  (DM t=+4.48 vs GJR). K994 found QQQ PASS, GLD+GVZ PASS, EEM/0050.TW not sig.
  K1021 found Student-t df≈8.5 optimal for SPY/QQQ.

  This experiment extends with:
  - Student-t df=8 fixed (K1021 recommendation) for all models
  - 6 assets: SPY, QQQ, GLD(+GVZ), EEM, TLT (new), 0050.TW
  - Both VIX and local-fear proxies where available
  - VaR 2.5% backtesting (Kupiec)
  - Comprehensive cross-asset summary table

Models per asset (3):
  M1: GJR-t(df=8)              -- baseline
  M2: A4f-VIX-t(df=8)          -- τ = θ₀ + θ₁×VIX², all assets use VIX
  M3: A4f-LocalFear-t(df=8)    -- GLD uses GVZ, others use VIX (=M2)

Data: yfinance 2005-2026. OOS: 2019-01-01 onwards.
Window=2000, refit every 63 days, seed=42.

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test (Harvey t>3.0)
  - VaR 2.5% Kupiec test
  - Spearman rank correlation

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility.
    JBES 33(3):338-358.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.
  - Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement
    Models. Journal of Derivatives 3:73-84.
  - K988: A4f champion for SPY (DM t=+4.48)
  - K994: Cross-asset (QQQ/GLD pass, EEM/0050.TW not sig)
  - K1021: Student-t df≈8.5 optimal, df=8 fixed best QLIKE-VaR balance

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
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1022"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func, spearman_corr
from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1022_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8  # K1021 recommendation

ASSETS = {
    'SPY': {'ticker': 'SPY', 'fear_ticker': '^VIX', 'local_fear': None, 'vix_lag': 0,
            'label': 'US Large Cap (baseline)'},
    'QQQ': {'ticker': 'QQQ', 'fear_ticker': '^VIX', 'local_fear': None, 'vix_lag': 0,
            'label': 'US Tech (high-beta)'},
    'GLD': {'ticker': 'GLD', 'fear_ticker': '^VIX', 'local_fear': '^GVZ', 'vix_lag': 0,
            'label': 'Gold (GVZ available)'},
    'EEM': {'ticker': 'EEM', 'fear_ticker': '^VIX', 'local_fear': None, 'vix_lag': 0,
            'label': 'Emerging Markets'},
    'TLT': {'ticker': 'TLT', 'fear_ticker': '^VIX', 'local_fear': None, 'vix_lag': 0,
            'label': 'US Bonds (new asset)'},
    '0050.TW': {'ticker': '0050.TW', 'fear_ticker': '^VIX', 'local_fear': None, 'vix_lag': 1,
                'label': 'Taiwan ETF (VIX lag+1)'},
}

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Cross-Asset Robustness (6 assets, Student-t df={DF_FIXED})")
print("  Paper 9 Core Robustness Check")
print("=" * 70)


# ============================================================
# NUMBA-ACCELERATED GARCH RECURSIONS
# ============================================================

@njit
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


def _student_t_const(df):
    """Precompute the Student-t log-likelihood constant (cannot use gammaln in numba)."""
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))

# Precompute for df=8
_T_CONST_8 = _student_t_const(DF_FIXED)


@njit
def gjr_nll_t(omega, alpha, gamma, beta, df, t_const, returns):
    """Negative log-likelihood for GJR-GARCH with Student-t(df) innovations."""
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


@njit
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

    # tau[0] uses fear2[0] (first available)
    tau[0] = theta0 + theta1 * fear2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, T):
        # tau_t uses fear²_{t-1} (lag-1, no lookahead)
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


@njit
def a4f_nll_t(theta0, theta1, omega, alpha, gamma, beta, df, t_const, returns, fear2):
    """Negative log-likelihood for A4f with Student-t(df) innovations."""
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


# ============================================================
# MODEL FITTING FUNCTIONS
# ============================================================

def fit_gjr_t(returns, df=DF_FIXED):
    """Fit GJR-GARCH(1,1) with fixed Student-t df."""
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
        persist = alpha + gamma / 2 + beta
        if persist >= 0.999:
            return 1e10
        return gjr_nll_t(omega, alpha, gamma, beta, float(df), _T_CONST_8, returns)

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
    """Fit A4f multiplicative GJR-X with fixed Student-t df and free omega.
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
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
        persist = alpha + gamma_p / 2 + beta
        if persist >= 0.999:
            return 1e10
        if omega_g <= 0:
            return 1e10
        return a4f_nll_t(theta0, theta1, omega_g, alpha, gamma_p, beta,
                         float(df), _T_CONST_8, returns, fear_vals**2)

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
    """Out-of-sample forecasting for GJR-GARCH-t(df)."""
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
            params = fit_gjr_t(train_ret, df)
            if params is None:
                continue
            last_fit = t

            # Rebuild h series
            omega, alpha, gamma, beta = params
            h_series = gjr_recursion(omega, alpha, gamma, beta, train_ret)
            h_prev = h_series[-1]
            r_prev = train_ret[-1]
        else:
            # Recursive update
            omega, alpha, gamma, beta = params
            u2 = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_prev = omega + alpha * u2 + gamma * u2 * ind + beta * h_prev
            h_prev = max(h_prev, 1e-10)
            r_prev = ret[t-1]

        # One-step-ahead forecast
        omega, alpha, gamma, beta = params
        u2 = ret[t-1] ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        forecasts[i] = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)

    return forecasts


def oos_forecast_a4f_t(ret, fear_vals, oos_mask, window, refit_every, df=DF_FIXED):
    """Out-of-sample forecasting for A4f-t(df) with free omega."""
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
            train_fear = fear_vals[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_a4f_t(train_ret, train_fear, df)
            if params is None:
                continue
            last_fit = t

            # Rebuild g series
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            h_series, tau_series, g_series = a4f_recursion(
                theta0, theta1, omega_g, alpha, gamma_p, beta,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
        else:
            # Recursive update
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            # tau for current step uses lagged fear
            tau_curr = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            u2 = u_prev ** 2
            ind = 1.0 if r_prev_val < 0 else 0.0
            g_prev = omega_g + alpha * u2 + gamma_p * u2 * ind + beta * g_prev
            g_prev = max(g_prev, 1e-10)
            r_prev_val = ret[t-1]

        # Forecast σ²_t = τ_t × g_t
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)

        # g forecast using r_{t-1} and tau_t
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        u2_fc = u_prev_fc ** 2
        ind_fc = 1.0 if ret[t-1] < 0 else 0.0
        g_fc = omega_g + alpha * u2_fc + gamma_p * u2_fc * ind_fc + beta * g_prev
        g_fc = max(g_fc, 1e-10)

        forecasts[i] = tau_t * g_fc

    return forecasts


# ============================================================
# VAR BACKTESTING
# ============================================================

def var_backtest_kupiec(returns_oos, forecasts, alpha=0.025, df=DF_FIXED):
    """VaR backtesting using Kupiec (1995) LR test.
    Uses Student-t quantile with scale correction.
    Returns: (violation_rate, expected_rate, kupiec_stat, kupiec_p, pass_flag)
    """
    valid = ~np.isnan(forecasts)
    ret = returns_oos[valid]
    fc = forecasts[valid]
    n = len(ret)

    if n < 100:
        return np.nan, alpha, np.nan, np.nan, 'SKIP'

    # Student-t VaR: q = t_inv(alpha, df) * sqrt(h * (df-2)/df)
    t_q = stats.t.ppf(alpha, df)
    var_series = t_q * np.sqrt(fc * (df - 2) / df)

    violations = (ret < var_series).sum()
    vr = violations / n

    # Kupiec LR test
    if violations == 0:
        lr = -2 * n * np.log(1 - alpha)
    elif violations == n:
        lr = -2 * n * np.log(alpha)
    else:
        lr = -2 * (np.log((1 - alpha)**(n - violations) * alpha**violations)
                    - np.log((1 - vr)**(n - violations) * vr**violations))

    p_value = 1 - stats.chi2.cdf(lr, 1)
    pass_flag = 'PASS' if p_value > 0.05 else 'FAIL'

    return float(vr), alpha, float(lr), float(p_value), pass_flag


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Load VIX (common)
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy() / 100.0  # Convert to decimal
print(f"  VIX: {len(vix_series)} obs ({vix_series.index[0].strftime('%Y-%m-%d')} to {vix_series.index[-1].strftime('%Y-%m-%d')})")

# Load GVZ (for GLD)
gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END, progress=False)
if isinstance(gvz_raw.columns, pd.MultiIndex):
    gvz_raw.columns = gvz_raw.columns.get_level_values(0)
gvz_series = gvz_raw['Close'].copy() / 100.0 if len(gvz_raw) > 100 else None
if gvz_series is not None:
    print(f"  GVZ: {len(gvz_series)} obs ({gvz_series.index[0].strftime('%Y-%m-%d')} to {gvz_series.index[-1].strftime('%Y-%m-%d')})")
else:
    print("  GVZ: insufficient data, using VIX for GLD")


# ============================================================
# WARM UP NUMBA (compile once before timing)
# ============================================================
print("\n[1b] Warming up numba JIT...")
_dummy_ret = np.random.randn(100) * 0.01
_dummy_fear2 = np.random.rand(100) * 0.04
_ = gjr_recursion(1e-6, 0.05, 0.05, 0.9, _dummy_ret)
_ = gjr_nll_t(1e-6, 0.05, 0.05, 0.9, 8.0, _T_CONST_8, _dummy_ret)
_ = a4f_recursion(1e-4, 1e-4, 0.05, 0.05, 0.05, 0.9, _dummy_ret, _dummy_fear2)
_ = a4f_nll_t(1e-4, 1e-4, 0.05, 0.05, 0.05, 0.9, 8.0, _T_CONST_8, _dummy_ret, _dummy_fear2)
print("  Done.")


# ============================================================
# MAIN LOOP
# ============================================================
all_results = {}

for asset_key, asset_info in ASSETS.items():
    ticker = asset_info['ticker']
    vix_lag_extra = asset_info['vix_lag']
    label = asset_info['label']
    local_fear_ticker = asset_info['local_fear']

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

    # Clean 0050.TW data
    if asset_key == '0050.TW':
        prices, _ = clean_tw50_data(prices)

    log_ret = np.log(prices / prices.shift(1))

    # Align with VIX
    if vix_lag_extra > 0:
        vix_aligned = vix_series.shift(vix_lag_extra)
    else:
        vix_aligned = vix_series

    df_data = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_aligned})
    df_data = df_data.dropna()

    # Also align local fear if available
    has_local_fear = False
    if local_fear_ticker == '^GVZ' and gvz_series is not None:
        df_data['LocalFear'] = gvz_series.reindex(df_data.index).ffill()
        df_data = df_data.dropna(subset=['LocalFear'])
        has_local_fear = True
        print(f"  Local fear proxy: GVZ ({len(df_data)} obs after alignment)")

    # Check sufficient data
    if len(df_data) < WINDOW + 252:
        print(f"  SKIP: insufficient aligned data ({len(df_data)} obs, need {WINDOW+252})")
        all_results[asset_key] = {'status': 'skipped',
                                  'reason': f'insufficient aligned data ({len(df_data)})'}
        continue

    oos_mask = np.array(df_data.index >= OOS_START)
    n_total = len(df_data)
    n_oos = oos_mask.sum()

    print(f"  Data: {df_data.index[0].strftime('%Y-%m-%d')} to {df_data.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
    print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

    if n_oos < 252:
        print(f"  SKIP: insufficient OOS data ({n_oos} obs)")
        all_results[asset_key] = {'status': 'skipped', 'reason': f'insufficient OOS ({n_oos})'}
        continue

    ret = df_data['log_ret'].values
    vix_vals = df_data['VIX'].values  # already in decimal
    r2 = ret ** 2

    # Diagnostics
    oos_ret = ret[oos_mask]
    print(f"  OOS mean return (ann.): {np.mean(oos_ret)*252:.4f}")
    print(f"  OOS vol (ann.): {np.std(oos_ret)*np.sqrt(252):.4f}")
    print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
    print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
    corr_vix_r2 = np.corrcoef(vix_vals[oos_mask], r2[oos_mask])[0, 1]
    print(f"  VIX-r² correlation (OOS): {corr_vix_r2:.4f}")

    # === Model 1: GJR-t(df=8) ===
    print(f"\n  [M1] GJR-t(df={DF_FIXED})...")
    t0 = time.time()
    fc_gjr = oos_forecast_gjr_t(ret, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
    t_gjr = time.time() - t0
    print(f"    Done in {t_gjr:.1f}s, valid={np.sum(~np.isnan(fc_gjr))}")

    # === Model 2: A4f-VIX-t(df=8) ===
    print(f"  [M2] A4f-VIX-t(df={DF_FIXED})...")
    t0 = time.time()
    fc_a4f_vix = oos_forecast_a4f_t(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
    t_a4f_vix = time.time() - t0
    print(f"    Done in {t_a4f_vix:.1f}s, valid={np.sum(~np.isnan(fc_a4f_vix))}")

    # === Model 3: A4f-LocalFear-t(df=8) ===
    if has_local_fear:
        local_fear_vals = df_data['LocalFear'].values
        print(f"  [M3] A4f-LocalFear-t(df={DF_FIXED})...")
        t0 = time.time()
        fc_a4f_local = oos_forecast_a4f_t(ret, local_fear_vals, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
        t_a4f_local = time.time() - t0
        print(f"    Done in {t_a4f_local:.1f}s, valid={np.sum(~np.isnan(fc_a4f_local))}")
    else:
        fc_a4f_local = fc_a4f_vix.copy()  # Same as M2 when no local fear
        t_a4f_local = 0.0

    # === Evaluation ===
    oos_r2 = r2[oos_mask]

    # Valid mask: all models have forecasts and oos_r2 > 0
    valid = (~np.isnan(fc_gjr) & ~np.isnan(fc_a4f_vix) & ~np.isnan(fc_a4f_local)
             & (oos_r2 > 0) & (fc_gjr > 0) & (fc_a4f_vix > 0) & (fc_a4f_local > 0))

    n_valid = int(valid.sum())
    if n_valid < 252:
        print(f"  WARNING: only {n_valid} valid OOS obs")

    # QLIKE (lower = better)
    qlike_gjr = qlike_func(oos_r2[valid], fc_gjr[valid])
    qlike_a4f_vix = qlike_func(oos_r2[valid], fc_a4f_vix[valid])
    qlike_a4f_local = qlike_func(oos_r2[valid], fc_a4f_local[valid])

    # Spearman
    rho_gjr, p_rho_gjr = spearman_corr(oos_r2[valid], fc_gjr[valid])
    rho_a4f_vix, p_rho_a4f_vix = spearman_corr(oos_r2[valid], fc_a4f_vix[valid])
    rho_a4f_local, p_rho_a4f_local = spearman_corr(oos_r2[valid], fc_a4f_local[valid])

    # Pointwise QLIKE loss for DM test
    loss_gjr = np.log(fc_gjr[valid]) + oos_r2[valid] / fc_gjr[valid]
    loss_a4f_vix = np.log(fc_a4f_vix[valid]) + oos_r2[valid] / fc_a4f_vix[valid]
    loss_a4f_local = np.log(fc_a4f_local[valid]) + oos_r2[valid] / fc_a4f_local[valid]

    # DM tests: negative t means first model better
    dm_t_vix, dm_p_vix = dm_test(loss_a4f_vix, loss_gjr)
    dm_t_local, dm_p_local = dm_test(loss_a4f_local, loss_gjr)
    dm_t_local_vs_vix, dm_p_local_vs_vix = dm_test(loss_a4f_local, loss_a4f_vix)

    # VaR backtesting (2.5%)
    var_gjr = var_backtest_kupiec(oos_ret, fc_gjr, alpha=0.025, df=DF_FIXED)
    var_a4f_vix = var_backtest_kupiec(oos_ret, fc_a4f_vix, alpha=0.025, df=DF_FIXED)
    var_a4f_local = var_backtest_kupiec(oos_ret, fc_a4f_local, alpha=0.025, df=DF_FIXED)

    # QLIKE improvement %
    qlike_improve_vix = (qlike_gjr - qlike_a4f_vix) / abs(qlike_gjr) * 100
    qlike_improve_local = (qlike_gjr - qlike_a4f_local) / abs(qlike_gjr) * 100

    # Get final params for reporting
    train_end = np.where(oos_mask)[0][0]
    train_ret_final = ret[max(0, train_end - WINDOW):train_end]
    train_vix_final = vix_vals[max(0, train_end - WINDOW):train_end]

    params_gjr_final = fit_gjr_t(train_ret_final, DF_FIXED)
    params_a4f_vix_final = fit_a4f_t(train_ret_final, train_vix_final, DF_FIXED)

    # Check persistence
    if params_gjr_final is not None:
        gjr_persist = params_gjr_final[1] + params_gjr_final[2] / 2 + params_gjr_final[3]
    else:
        gjr_persist = None

    if params_a4f_vix_final is not None:
        a4f_persist = params_a4f_vix_final[3] + params_a4f_vix_final[4] / 2 + params_a4f_vix_final[5]
    else:
        a4f_persist = None

    print(f"\n  === Results for {asset_key} ===")
    print(f"  {'Model':<18} {'QLIKE':>10} {'Spearman':>10} {'DM t':>10} {'Harvey':>8} {'VaR vr':>8} {'VaR':>6}")
    print(f"  {'-'*70}")
    print(f"  {'GJR-t(8)':<18} {qlike_gjr:>10.4f} {rho_gjr:>10.4f} {'(base)':>10} {'-':>8} "
          f"{var_gjr[0]:>8.4f} {var_gjr[4]:>6}")
    print(f"  {'A4f-VIX-t(8)':<18} {qlike_a4f_vix:>10.4f} {rho_a4f_vix:>10.4f} {dm_t_vix:>10.4f} "
          f"{'YES' if abs(dm_t_vix) > 3.0 else 'NO':>8} {var_a4f_vix[0]:>8.4f} {var_a4f_vix[4]:>6}")
    if has_local_fear:
        print(f"  {'A4f-GVZ-t(8)':<18} {qlike_a4f_local:>10.4f} {rho_a4f_local:>10.4f} {dm_t_local:>10.4f} "
              f"{'YES' if abs(dm_t_local) > 3.0 else 'NO':>8} {var_a4f_local[0]:>8.4f} {var_a4f_local[4]:>6}")
    print(f"  QLIKE improvement (A4f-VIX vs GJR): {qlike_improve_vix:+.2f}%")
    if has_local_fear:
        print(f"  QLIKE improvement (A4f-Local vs GJR): {qlike_improve_local:+.2f}%")
    if gjr_persist is not None:
        print(f"  GJR persistence: {gjr_persist:.4f}")
    if a4f_persist is not None:
        print(f"  A4f persistence: {a4f_persist:.4f}")

    # Store results
    asset_result = {
        'status': 'completed',
        'label': label,
        'n_total': n_total,
        'n_oos': n_oos,
        'n_valid': n_valid,
        'has_local_fear': has_local_fear,
        'local_fear_proxy': 'GVZ' if has_local_fear else 'VIX (same as M2)',
        'vix_r2_corr_oos': round(float(corr_vix_r2), 4),
        'diagnostics': {
            'oos_mean_return_ann': round(float(np.mean(oos_ret) * 252), 4),
            'oos_vol_ann': round(float(np.std(oos_ret) * np.sqrt(252)), 4),
            'oos_skewness': round(float(stats.skew(oos_ret)), 3),
            'oos_kurtosis': round(float(stats.kurtosis(oos_ret)), 3),
        },
        'models': {
            'GJR-t': {
                'qlike': round(float(qlike_gjr), 6),
                'spearman_rho': round(float(rho_gjr), 4),
                'params': [round(float(p), 8) for p in params_gjr_final] if params_gjr_final is not None else None,
                'persistence': round(float(gjr_persist), 4) if gjr_persist is not None else None,
                'var_025': {
                    'violation_rate': round(float(var_gjr[0]), 4) if not np.isnan(var_gjr[0]) else None,
                    'kupiec_stat': round(float(var_gjr[2]), 4) if not np.isnan(var_gjr[2]) else None,
                    'kupiec_p': round(float(var_gjr[3]), 4) if not np.isnan(var_gjr[3]) else None,
                    'pass': var_gjr[4],
                },
                'elapsed_s': round(t_gjr, 1),
            },
            'A4f-VIX-t': {
                'qlike': round(float(qlike_a4f_vix), 6),
                'spearman_rho': round(float(rho_a4f_vix), 4),
                'params': [round(float(p), 8) for p in params_a4f_vix_final] if params_a4f_vix_final is not None else None,
                'persistence': round(float(a4f_persist), 4) if a4f_persist is not None else None,
                'var_025': {
                    'violation_rate': round(float(var_a4f_vix[0]), 4) if not np.isnan(var_a4f_vix[0]) else None,
                    'kupiec_stat': round(float(var_a4f_vix[2]), 4) if not np.isnan(var_a4f_vix[2]) else None,
                    'kupiec_p': round(float(var_a4f_vix[3]), 4) if not np.isnan(var_a4f_vix[3]) else None,
                    'pass': var_a4f_vix[4],
                },
                'elapsed_s': round(t_a4f_vix, 1),
            },
            'A4f-LocalFear-t': {
                'qlike': round(float(qlike_a4f_local), 6),
                'spearman_rho': round(float(rho_a4f_local), 4),
                'var_025': {
                    'violation_rate': round(float(var_a4f_local[0]), 4) if not np.isnan(var_a4f_local[0]) else None,
                    'kupiec_stat': round(float(var_a4f_local[2]), 4) if not np.isnan(var_a4f_local[2]) else None,
                    'kupiec_p': round(float(var_a4f_local[3]), 4) if not np.isnan(var_a4f_local[3]) else None,
                    'pass': var_a4f_local[4],
                },
                'elapsed_s': round(t_a4f_local, 1),
            },
        },
        'dm_tests': {
            'A4f_VIX_vs_GJR': {
                'dm_t': round(float(dm_t_vix), 4),
                'dm_p': float(dm_p_vix),
                'significant_harvey': abs(dm_t_vix) > 3.0,
                'direction': 'A4f better' if dm_t_vix < 0 else 'GJR better',
            },
            'A4f_Local_vs_GJR': {
                'dm_t': round(float(dm_t_local), 4),
                'dm_p': float(dm_p_local),
                'significant_harvey': abs(dm_t_local) > 3.0,
                'direction': 'A4f-Local better' if dm_t_local < 0 else 'GJR better',
            },
            'A4f_Local_vs_A4f_VIX': {
                'dm_t': round(float(dm_t_local_vs_vix), 4),
                'dm_p': float(dm_p_local_vs_vix),
                'significant_harvey': abs(dm_t_local_vs_vix) > 3.0,
            },
        },
        'qlike_improvement_pct': {
            'A4f_VIX_vs_GJR': round(float(qlike_improve_vix), 2),
            'A4f_Local_vs_GJR': round(float(qlike_improve_local), 2),
        },
        'elapsed_seconds': round(t_gjr + t_a4f_vix + t_a4f_local, 1),
    }
    all_results[asset_key] = asset_result


# ============================================================
# SUMMARY TABLE
# ============================================================
print("\n" + "=" * 80)
print("CROSS-ASSET SUMMARY: A4f Robustness with Student-t(df=8)")
print("=" * 80)

n_tested = 0
n_a4f_vix_sig = 0
n_a4f_local_sig = 0
n_a4f_vix_var_pass = 0
n_a4f_vix_better_qlike = 0

summary_rows = []

print(f"\n{'Asset':<10} {'GJR QL':>8} {'A4f-VIX QL':>11} {'DM t':>8} {'Harvey':>7} {'QL +%':>7} {'VaR GJR':>8} {'VaR A4f':>8}")
print("-" * 78)

for asset_key in ASSETS:
    if asset_key not in all_results or all_results[asset_key].get('status') != 'completed':
        print(f"{asset_key:<10} {'SKIPPED':>58}")
        continue

    r = all_results[asset_key]
    qg = r['models']['GJR-t']['qlike']
    qa = r['models']['A4f-VIX-t']['qlike']
    dt = r['dm_tests']['A4f_VIX_vs_GJR']['dm_t']
    sig = r['dm_tests']['A4f_VIX_vs_GJR']['significant_harvey']
    improve = r['qlike_improvement_pct']['A4f_VIX_vs_GJR']
    var_gjr_pass = r['models']['GJR-t']['var_025']['pass']
    var_a4f_pass = r['models']['A4f-VIX-t']['var_025']['pass']

    n_tested += 1
    if sig:
        n_a4f_vix_sig += 1
    if qa < qg:
        n_a4f_vix_better_qlike += 1
    if var_a4f_pass == 'PASS':
        n_a4f_vix_var_pass += 1

    if r['dm_tests']['A4f_Local_vs_GJR']['significant_harvey']:
        n_a4f_local_sig += 1

    print(f"{asset_key:<10} {qg:>8.4f} {qa:>11.4f} {dt:>8.3f} {'YES' if sig else 'NO':>7} "
          f"{improve:>+7.2f} {var_gjr_pass:>8} {var_a4f_pass:>8}")

    summary_rows.append({
        'asset': asset_key,
        'qlike_gjr': qg,
        'qlike_a4f': qa,
        'dm_t': dt,
        'harvey_sig': sig,
        'qlike_improve_pct': improve,
        'var_gjr': var_gjr_pass,
        'var_a4f': var_a4f_pass,
    })

print(f"\nA4f-VIX significant wins (Harvey |t|>3.0): {n_a4f_vix_sig}/{n_tested}")
print(f"A4f-VIX QLIKE better (any): {n_a4f_vix_better_qlike}/{n_tested}")
print(f"A4f-VIX VaR 2.5% PASS: {n_a4f_vix_var_pass}/{n_tested}")
print(f"A4f-Local significant wins: {n_a4f_local_sig}/{n_tested}")

# Classify robustness
if n_a4f_vix_sig >= 4:
    conclusion = f"STRONG robustness: A4f significantly beats GJR in {n_a4f_vix_sig}/{n_tested} assets"
elif n_a4f_vix_sig >= 3:
    conclusion = f"GOOD robustness: A4f significant in {n_a4f_vix_sig}/{n_tested} assets"
elif n_a4f_vix_sig >= 2:
    conclusion = f"MODERATE robustness: A4f significant in {n_a4f_vix_sig}/{n_tested} — equity-specific"
else:
    conclusion = f"LIMITED robustness: A4f significant in only {n_a4f_vix_sig}/{n_tested} — may be SPY/QQQ specific"

print(f"\nConclusion: {conclusion}")


# ============================================================
# CHARTS
# ============================================================
print("\n[Charts] Generating figures...")

# Chart 1: DM t-statistic bar chart
fig, ax = plt.subplots(figsize=(10, 6))
completed_assets = [a for a in ASSETS if a in all_results and all_results[a].get('status') == 'completed']
dm_t_vals = [all_results[a]['dm_tests']['A4f_VIX_vs_GJR']['dm_t'] for a in completed_assets]

colors = ['#2ecc71' if abs(t) > 3.0 else '#e74c3c' if abs(t) < 1.96 else '#f39c12'
          for t in dm_t_vals]

bars = ax.bar(range(len(completed_assets)), dm_t_vals, color=colors, edgecolor='black', linewidth=0.5)
ax.set_xticks(range(len(completed_assets)))
ax.set_xticklabels(completed_assets, fontsize=11, fontweight='bold')
ax.axhline(y=-3.0, color='green', linestyle='--', linewidth=1.5, label='Harvey threshold (|t|=3.0)')
ax.axhline(y=3.0, color='green', linestyle='--', linewidth=1.5)
ax.axhline(y=0, color='black', linewidth=0.5)
ax.set_ylabel('DM t-statistic', fontsize=12)
ax.set_title(f'K1022: A4f vs GJR-t(df={DF_FIXED}) — Cross-Asset DM Test\n'
             f'(Negative = A4f better)', fontsize=13, fontweight='bold')
ax.legend(loc='upper right', fontsize=10)

for bar, val in zip(bars, dm_t_vals):
    ypos = val - 0.3 if val > 0 else val + 0.15
    ax.text(bar.get_x() + bar.get_width()/2, ypos, f'{val:.2f}',
            ha='center', va='bottom' if val < 0 else 'top', fontsize=10, fontweight='bold')

ax.set_ylim(min(dm_t_vals) - 1.5, max(dm_t_vals) + 1.5)
plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1022_dm_t_bar.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")

# Chart 2: QLIKE improvement % heatmap-style bar chart
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# Left: QLIKE improvement %
improve_vals = [all_results[a]['qlike_improvement_pct']['A4f_VIX_vs_GJR'] for a in completed_assets]
colors2 = ['#2ecc71' if v > 0 else '#e74c3c' for v in improve_vals]
bars2 = ax1.barh(range(len(completed_assets)), improve_vals, color=colors2, edgecolor='black', linewidth=0.5)
ax1.set_yticks(range(len(completed_assets)))
ax1.set_yticklabels(completed_assets, fontsize=11, fontweight='bold')
ax1.axvline(x=0, color='black', linewidth=0.8)
ax1.set_xlabel('QLIKE Improvement (%)', fontsize=12)
ax1.set_title('A4f-VIX vs GJR: QLIKE Change', fontsize=12, fontweight='bold')

for bar, val in zip(bars2, improve_vals):
    xpos = val + 0.1 if val >= 0 else val - 0.1
    ax1.text(xpos, bar.get_y() + bar.get_height()/2, f'{val:+.2f}%',
             va='center', ha='left' if val >= 0 else 'right', fontsize=10, fontweight='bold')

# Right: VaR 2.5% violation rates comparison
var_gjr_vr = [all_results[a]['models']['GJR-t']['var_025']['violation_rate'] for a in completed_assets]
var_a4f_vr = [all_results[a]['models']['A4f-VIX-t']['var_025']['violation_rate'] for a in completed_assets]

x_pos = np.arange(len(completed_assets))
width = 0.35
bars_gjr = ax2.bar(x_pos - width/2, var_gjr_vr, width, label='GJR-t(8)', color='#3498db', edgecolor='black', linewidth=0.5)
bars_a4f = ax2.bar(x_pos + width/2, var_a4f_vr, width, label='A4f-VIX-t(8)', color='#e67e22', edgecolor='black', linewidth=0.5)
ax2.axhline(y=0.025, color='red', linestyle='--', linewidth=1.5, label='Target (2.5%)')
ax2.set_xticks(x_pos)
ax2.set_xticklabels(completed_assets, fontsize=10, fontweight='bold')
ax2.set_ylabel('Violation Rate', fontsize=12)
ax2.set_title('VaR 2.5% Violation Rates', fontsize=12, fontweight='bold')
ax2.legend(fontsize=9)
ax2.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=1))

plt.suptitle(f'K1022: Cross-Asset Robustness — A4f vs GJR (Student-t df={DF_FIXED})',
             fontsize=14, fontweight='bold', y=1.02)
plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1022_qlike_var_comparison.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")


# ============================================================
# SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\nTotal elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")

results = {
    'experiment_id': EXPERIMENT_ID,
    'assets': all_results,
    'summary': {
        'n_assets_tested': n_tested,
        'a4f_vix_significant_wins': n_a4f_vix_sig,
        'a4f_vix_qlike_better': n_a4f_vix_better_qlike,
        'a4f_vix_var_pass': n_a4f_vix_var_pass,
        'a4f_local_significant_wins': n_a4f_local_sig,
        'conclusion': conclusion,
        'summary_table': summary_rows,
    },
    'metadata': {
        'experiment_id': EXPERIMENT_ID,
        'base_experiments': ['K988', 'K994', 'K1004', 'K1021'],
        'model_spec': 'A4f: τ=θ₀+θ₁×X², free ω, GJR g_t, Student-t(df=8)',
        'data_source': 'yfinance',
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'df_fixed': DF_FIXED,
        'evaluation': 'QLIKE on r² (Patton 2011), DM test (Harvey t>3.0), VaR 2.5% Kupiec',
        'charts': ['k1022_dm_t_bar.png', 'k1022_qlike_var_comparison.png'],
        'elapsed_seconds': round(elapsed, 1),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'seed': 42,
        'references': [
            'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
            'Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.',
            'Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
            'Harvey et al. (2016). t > 3.0 threshold.',
            'Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement Models. J Deriv 3:73-84.',
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
