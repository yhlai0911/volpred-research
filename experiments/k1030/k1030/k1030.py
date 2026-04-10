#!/usr/bin/env python3
"""
K1030: VSTOXX-Driven A4f for European Equity Volatility
========================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K994/K997 proved A4f needs asset-specific fear index for cross-market
  generalization. K756 tested 12 international markets but only with US VIX.
  This experiment tests A4f on European equity using VSTOXX (Euro VIX) as the
  τ driver, directly testing the "relevant fear index" hypothesis on a major
  non-US market with its own implied volatility index.

  If VSTOXX + EURO STOXX 50 shows significant A4f improvement, it strengthens
  the Paper 9 cross-asset generalization story beyond US and commodity markets.

Models:
  M1: GJR-t(df=8)               -- baseline
  M2: A4f-VIX-t(df=8)           -- τ = θ₀ + θ₁×VIX² (US fear, control)
  M3: A4f-VSTOXX-t(df=8)        -- τ = θ₀ + θ₁×VSTOXX² (European fear)

Data: yfinance 2010-2026 (VSTOXX available from ~2009).
  - EURO STOXX 50: ^STOXX50E (index) or FEZ (ETF)
  - VSTOXX: ^V2TX or V2TX.DE
  - VIX: ^VIX
OOS: 2019-01-01 onwards, window=2000, refit/63d, seed=42.

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test (Harvey t>3.0)
  - VaR 2.5% Kupiec test
  - Spearman rank correlation
  - Regime analysis: VSTOXX regime-conditional QLIKE

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
  - K988: A4f champion for SPY (DM t=+4.48 vs GJR)
  - K994: Cross-asset (QQQ pass, GLD/EEM/0050.TW not sig with US VIX)
  - K997: Local fear indices (GLD+GVZ pass, EEM/0050.TW still not sig)
  - K1022: Cross-asset robustness with Student-t df=8

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
import matplotlib.ticker as mticker

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1030"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1030_results.json')

# Configuration
DATA_START = '2009-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8  # K1021 recommendation

print("=" * 70)
print(f"{EXPERIMENT_ID}: VSTOXX-Driven A4f for European Equity Volatility")
print("  Testing VSTOXX vs US VIX as A4f τ driver for EURO STOXX 50")
print("=" * 70)


# ============================================================
# GARCH RECURSIONS (no numba to avoid compilation overhead for
# a single-asset experiment; scipy vectorized is fast enough)
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
    """Precompute the Student-t log-likelihood constant."""
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))

T_CONST_8 = student_t_const(DF_FIXED)


def gjr_nll_t(omega, alpha, gamma, beta, df, t_const, returns):
    """Negative log-likelihood for GJR-GARCH with Student-t(df) innovations."""
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
    """Fit A4f multiplicative GJR-X with fixed Student-t df and free omega.
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
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
    """Out-of-sample forecasting for GJR-GARCH-t(df)."""
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

        if params is None:
            continue

        # One-step-ahead forecast
        omega, alpha, gamma, beta = params
        u2 = ret[t-1] ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        forecasts[i] = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)

    return forecasts


def oos_forecast_a4f_t(ret, fear_vals, oos_mask, window, refit_every, df=DF_FIXED):
    """Out-of-sample forecasting for A4f-t(df) with free omega."""
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
            tau_curr = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            u2 = u_prev ** 2
            ind = 1.0 if r_prev_val < 0 else 0.0
            g_prev = omega_g + alpha * u2 + gamma_p * u2 * ind + beta * g_prev
            g_prev = max(g_prev, 1e-10)
            r_prev_val = ret[t-1]

        if params is None:
            continue

        # Forecast σ²_t = τ_t × g_t
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)

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

def var_backtest_kupiec(returns_oos, forecasts, alpha_level=0.025, df=DF_FIXED):
    """VaR backtesting using Kupiec (1995) LR test.
    Uses Student-t quantile with scale correction.
    """
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


# ============================================================
# ES BACKTESTING (Acerbi & Szekely 2014)
# ============================================================

def es_backtest(returns_oos, forecasts, alpha_level=0.025, df=DF_FIXED):
    """ES backtesting using Acerbi & Szekely (2014) Z-test."""
    valid = ~np.isnan(forecasts)
    ret = returns_oos[valid]
    fc = forecasts[valid]
    n = len(ret)

    if n < 100:
        return np.nan, np.nan, np.nan, 'SKIP'

    # Student-t VaR and ES
    t_q = stats.t.ppf(alpha_level, df)
    scale = np.sqrt((df - 2) / df)
    var_series = t_q * scale * np.sqrt(fc)

    # ES for Student-t: E[X | X < VaR] = -(df + t_q^2) / (df - 1) * stats.t.pdf(t_q, df) / alpha * scale * sqrt(h)
    t_pdf = stats.t.pdf(t_q, df)
    es_factor = -(df + t_q**2) / (df - 1) * t_pdf / alpha_level
    es_series = es_factor * scale * np.sqrt(fc)

    # Z-test: Z = 1/(n*alpha) * sum(r_t * I(r_t < VaR_t) / ES_t) + 1
    violations_mask = ret < var_series
    n_viol = violations_mask.sum()

    if n_viol == 0:
        return 0.0, np.nan, np.nan, 'SKIP'

    z_stat = 1 / (n * alpha_level) * np.sum(ret[violations_mask] / es_series[violations_mask]) + 1
    # Under H0, Z ~ N(0, 1/n * Var(..)) -- approximate p-value
    # Simple approach: bootstrap or use asymptotic approximation
    # For simplicity, we test if Z is significantly different from 0
    # Z < 0 means ES underestimates tail risk (bad)
    p_value = stats.norm.cdf(z_stat)  # one-sided: Z < 0 is bad
    pass_flag = 'PASS' if p_value > 0.05 else 'FAIL'

    return float(z_stat), float(p_value), float(n_viol / n), pass_flag


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

# Try VSTOXX tickers
vstoxx_data = None
for vstoxx_ticker in ['^V2TX', 'V2TX.DE', '^VSTOXX']:
    print(f"  Trying VSTOXX ticker: {vstoxx_ticker}...")
    try:
        raw_vstoxx = yf.download(vstoxx_ticker, start=DATA_START, end=DATA_END, progress=False)
        if isinstance(raw_vstoxx.columns, pd.MultiIndex):
            raw_vstoxx.columns = raw_vstoxx.columns.get_level_values(0)
        if len(raw_vstoxx) > 100:
            vstoxx_data = raw_vstoxx['Close'].copy() / 100.0  # Convert to decimal
            print(f"    SUCCESS: {len(vstoxx_data)} obs ({vstoxx_data.index[0].strftime('%Y-%m-%d')} to {vstoxx_data.index[-1].strftime('%Y-%m-%d')})")
            break
        else:
            print(f"    Too few observations: {len(raw_vstoxx)}")
    except Exception as e:
        print(f"    Failed: {e}")

if vstoxx_data is None:
    print("  WARNING: VSTOXX data unavailable. Will use EWG (Germany ETF) + VIX as fallback.")

# Load VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy() / 100.0
print(f"  VIX: {len(vix_series)} obs ({vix_series.index[0].strftime('%Y-%m-%d')} to {vix_series.index[-1].strftime('%Y-%m-%d')})")

# Try EURO STOXX 50 tickers
euro_stoxx_data = None
euro_stoxx_ticker_used = None
for ticker in ['^STOXX50E', 'FEZ']:
    print(f"  Trying EURO STOXX 50 ticker: {ticker}...")
    try:
        raw_es = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
        if isinstance(raw_es.columns, pd.MultiIndex):
            raw_es.columns = raw_es.columns.get_level_values(0)
        if len(raw_es) > 1000:
            euro_stoxx_data = raw_es['Close'].copy()
            euro_stoxx_ticker_used = ticker
            print(f"    SUCCESS: {len(euro_stoxx_data)} obs ({euro_stoxx_data.index[0].strftime('%Y-%m-%d')} to {euro_stoxx_data.index[-1].strftime('%Y-%m-%d')})")
            break
        else:
            print(f"    Too few observations: {len(raw_es)}")
    except Exception as e:
        print(f"    Failed: {e}")

# Fallback: EWG (iShares Germany ETF)
if euro_stoxx_data is None:
    print("  Trying fallback: EWG (iShares MSCI Germany ETF)...")
    raw_ewg = yf.download('EWG', start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw_ewg.columns, pd.MultiIndex):
        raw_ewg.columns = raw_ewg.columns.get_level_values(0)
    if len(raw_ewg) > 1000:
        euro_stoxx_data = raw_ewg['Close'].copy()
        euro_stoxx_ticker_used = 'EWG'
        print(f"    SUCCESS: {len(euro_stoxx_data)} obs")

if euro_stoxx_data is None:
    print("FATAL: Could not obtain European equity data. Exiting.")
    results = {
        'experiment_id': EXPERIMENT_ID,
        'status': 'failed',
        'reason': 'No European equity data available from yfinance',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    sys.exit(1)

# Compute log returns
log_ret = np.log(euro_stoxx_data / euro_stoxx_data.shift(1))

# Determine fear index to use
if vstoxx_data is not None:
    # Use VSTOXX as European fear index
    fear_source = 'VSTOXX'
    european_fear = vstoxx_data
else:
    # Fallback: use VIX for everything (will likely show weak result, as expected)
    fear_source = 'VIX_only'
    european_fear = None

# Build main dataframe
df_data = pd.DataFrame({
    'price': euro_stoxx_data,
    'log_ret': log_ret,
    'VIX': vix_series,
})

if european_fear is not None:
    df_data['VSTOXX'] = european_fear

df_data = df_data.dropna()

if european_fear is not None:
    # Also ensure VSTOXX column has no NaN
    df_data = df_data.dropna(subset=['VSTOXX'])

n_total = len(df_data)
print(f"\n[2] Aligned data: {df_data.index[0].strftime('%Y-%m-%d')} to {df_data.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  European equity ticker: {euro_stoxx_ticker_used}")
print(f"  Fear index source: {fear_source}")

if n_total < WINDOW + 252:
    print(f"FATAL: insufficient aligned data ({n_total} obs, need {WINDOW+252})")
    results = {
        'experiment_id': EXPERIMENT_ID,
        'status': 'failed',
        'reason': f'Insufficient aligned data: {n_total} obs',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    sys.exit(1)

oos_mask = np.array(df_data.index >= OOS_START)
n_oos = oos_mask.sum()
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

if n_oos < 252:
    print(f"FATAL: insufficient OOS data ({n_oos} obs)")
    results = {
        'experiment_id': EXPERIMENT_ID,
        'status': 'failed',
        'reason': f'Insufficient OOS data: {n_oos} obs',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2)
    sys.exit(1)

ret = df_data['log_ret'].values
vix_vals = df_data['VIX'].values
r2 = ret ** 2

has_vstoxx = 'VSTOXX' in df_data.columns
if has_vstoxx:
    vstoxx_vals = df_data['VSTOXX'].values

# ============================================================
# DESCRIPTIVE STATISTICS
# ============================================================
print("\n[3] Descriptive statistics...")
oos_ret = ret[oos_mask]
oos_r2 = r2[oos_mask]

desc_stats = {
    'n_total': int(n_total),
    'n_oos': int(n_oos),
    'data_start': df_data.index[0].strftime('%Y-%m-%d'),
    'data_end': df_data.index[-1].strftime('%Y-%m-%d'),
    'oos_start': OOS_START,
    'ticker': euro_stoxx_ticker_used,
    'fear_source': fear_source,
    'oos_mean_return_ann': float(np.mean(oos_ret) * 252),
    'oos_vol_ann': float(np.std(oos_ret) * np.sqrt(252)),
    'oos_skewness': float(stats.skew(oos_ret)),
    'oos_kurtosis': float(stats.kurtosis(oos_ret)),
}

# Correlation diagnostics
corr_vix_r2 = np.corrcoef(vix_vals[oos_mask], oos_r2)[0, 1]
desc_stats['corr_vix_r2_oos'] = float(corr_vix_r2)
print(f"  OOS mean return (ann.): {desc_stats['oos_mean_return_ann']:.4f}")
print(f"  OOS vol (ann.): {desc_stats['oos_vol_ann']:.4f}")
print(f"  OOS skewness: {desc_stats['oos_skewness']:.3f}")
print(f"  OOS kurtosis: {desc_stats['oos_kurtosis']:.3f}")
print(f"  VIX-r² correlation (OOS): {corr_vix_r2:.4f}")

if has_vstoxx:
    corr_vstoxx_r2 = np.corrcoef(vstoxx_vals[oos_mask], oos_r2)[0, 1]
    corr_vstoxx_vix = np.corrcoef(vstoxx_vals[oos_mask], vix_vals[oos_mask])[0, 1]
    desc_stats['corr_vstoxx_r2_oos'] = float(corr_vstoxx_r2)
    desc_stats['corr_vstoxx_vix_oos'] = float(corr_vstoxx_vix)
    print(f"  VSTOXX-r² correlation (OOS): {corr_vstoxx_r2:.4f}")
    print(f"  VSTOXX-VIX correlation (OOS): {corr_vstoxx_vix:.4f}")

    # Rolling correlation stability
    roll_window = 63  # quarterly
    vstoxx_oos = vstoxx_vals[oos_mask]
    vix_oos = vix_vals[oos_mask]
    roll_corr_vstoxx = []
    roll_corr_vix = []
    for j in range(roll_window, len(oos_r2)):
        rc_vs = np.corrcoef(vstoxx_oos[j-roll_window:j], oos_r2[j-roll_window:j])[0, 1]
        rc_vx = np.corrcoef(vix_oos[j-roll_window:j], oos_r2[j-roll_window:j])[0, 1]
        roll_corr_vstoxx.append(rc_vs)
        roll_corr_vix.append(rc_vx)
    desc_stats['roll_corr_vstoxx_r2_mean'] = float(np.mean(roll_corr_vstoxx))
    desc_stats['roll_corr_vstoxx_r2_std'] = float(np.std(roll_corr_vstoxx))
    desc_stats['roll_corr_vix_r2_mean'] = float(np.mean(roll_corr_vix))
    desc_stats['roll_corr_vix_r2_std'] = float(np.std(roll_corr_vix))
    print(f"  Rolling corr VSTOXX-r² (63d): mean={np.mean(roll_corr_vstoxx):.4f}, std={np.std(roll_corr_vstoxx):.4f}")
    print(f"  Rolling corr VIX-r² (63d): mean={np.mean(roll_corr_vix):.4f}, std={np.std(roll_corr_vix):.4f}")


# ============================================================
# MODEL 1: GJR-t(df=8) BASELINE
# ============================================================
print(f"\n[4] Model 1: GJR-t(df={DF_FIXED}) baseline...")
t0 = time.time()
fc_gjr = oos_forecast_gjr_t(ret, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
t_gjr = time.time() - t0
valid_gjr = np.sum(~np.isnan(fc_gjr))
print(f"  Done in {t_gjr:.1f}s, valid forecasts: {valid_gjr}/{len(fc_gjr)}")


# ============================================================
# MODEL 2: A4f-VIX-t(df=8) — US VIX as control
# ============================================================
print(f"\n[5] Model 2: A4f-VIX-t(df={DF_FIXED}) — US VIX as τ driver...")
t0 = time.time()
fc_a4f_vix = oos_forecast_a4f_t(ret, vix_vals, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
t_a4f_vix = time.time() - t0
valid_a4f_vix = np.sum(~np.isnan(fc_a4f_vix))
print(f"  Done in {t_a4f_vix:.1f}s, valid forecasts: {valid_a4f_vix}/{len(fc_a4f_vix)}")


# ============================================================
# MODEL 3: A4f-VSTOXX-t(df=8) — European fear index
# ============================================================
if has_vstoxx:
    print(f"\n[6] Model 3: A4f-VSTOXX-t(df={DF_FIXED}) — VSTOXX as τ driver...")
    t0 = time.time()
    fc_a4f_vstoxx = oos_forecast_a4f_t(ret, vstoxx_vals, oos_mask, WINDOW, REFIT_EVERY, DF_FIXED)
    t_a4f_vstoxx = time.time() - t0
    valid_a4f_vstoxx = np.sum(~np.isnan(fc_a4f_vstoxx))
    print(f"  Done in {t_a4f_vstoxx:.1f}s, valid forecasts: {valid_a4f_vstoxx}/{len(fc_a4f_vstoxx)}")
else:
    fc_a4f_vstoxx = None


# ============================================================
# EVALUATION
# ============================================================
print("\n[7] Evaluation...")

oos_indices = np.where(oos_mask)[0]
oos_r2_vals = r2[oos_indices]

# Align valid forecasts
valid_all = ~np.isnan(fc_gjr) & ~np.isnan(fc_a4f_vix)
if has_vstoxx and fc_a4f_vstoxx is not None:
    valid_all = valid_all & ~np.isnan(fc_a4f_vstoxx)

fc_gjr_v = fc_gjr[valid_all]
fc_a4f_vix_v = fc_a4f_vix[valid_all]
r2_v = oos_r2_vals[valid_all]
ret_v = oos_ret[valid_all] if len(oos_ret) == len(fc_gjr) else ret[oos_indices][valid_all]

if has_vstoxx and fc_a4f_vstoxx is not None:
    fc_a4f_vstoxx_v = fc_a4f_vstoxx[valid_all]

n_valid = len(r2_v)
print(f"  Valid aligned observations: {n_valid}")

# QLIKE
qlike_gjr = float(qlike_func(r2_v, fc_gjr_v))
qlike_a4f_vix = float(qlike_func(r2_v, fc_a4f_vix_v))
print(f"  QLIKE GJR:      {qlike_gjr:.6f}")
print(f"  QLIKE A4f-VIX:  {qlike_a4f_vix:.6f}")

if has_vstoxx and fc_a4f_vstoxx is not None:
    qlike_a4f_vstoxx = float(qlike_func(r2_v, fc_a4f_vstoxx_v))
    print(f"  QLIKE A4f-VSTOXX: {qlike_a4f_vstoxx:.6f}")

# DM tests
print("\n  DM Tests (Harvey |t| > 3.0):")
# A4f-VIX vs GJR
dm_vix = dm_test(r2_v, fc_gjr_v, fc_a4f_vix_v, loss='QLIKE')
print(f"    A4f-VIX vs GJR:    DM t={dm_vix['t_stat']:.3f}, p={dm_vix['p_value']:.4f}")

if has_vstoxx and fc_a4f_vstoxx is not None:
    # A4f-VSTOXX vs GJR
    dm_vstoxx = dm_test(r2_v, fc_gjr_v, fc_a4f_vstoxx_v, loss='QLIKE')
    print(f"    A4f-VSTOXX vs GJR: DM t={dm_vstoxx['t_stat']:.3f}, p={dm_vstoxx['p_value']:.4f}")

    # A4f-VSTOXX vs A4f-VIX (head-to-head)
    dm_vstoxx_vs_vix = dm_test(r2_v, fc_a4f_vix_v, fc_a4f_vstoxx_v, loss='QLIKE')
    print(f"    A4f-VSTOXX vs A4f-VIX: DM t={dm_vstoxx_vs_vix['t_stat']:.3f}, p={dm_vstoxx_vs_vix['p_value']:.4f}")

# Spearman rank correlation
spearman_gjr = float(spearman_corr(r2_v, fc_gjr_v))
spearman_a4f_vix = float(spearman_corr(r2_v, fc_a4f_vix_v))
print(f"\n  Spearman rank correlation:")
print(f"    GJR:        {spearman_gjr:.4f}")
print(f"    A4f-VIX:    {spearman_a4f_vix:.4f}")

if has_vstoxx and fc_a4f_vstoxx is not None:
    spearman_a4f_vstoxx = float(spearman_corr(r2_v, fc_a4f_vstoxx_v))
    print(f"    A4f-VSTOXX: {spearman_a4f_vstoxx:.4f}")


# VaR backtesting (2.5% and 1%)
print("\n  VaR Backtesting:")
ret_oos_valid = ret_v

for alpha_label, alpha_val in [('2.5%', 0.025), ('1%', 0.01)]:
    print(f"\n  --- VaR {alpha_label} ---")
    vr_gjr, _, lr_gjr, p_gjr, pf_gjr = var_backtest_kupiec(ret_oos_valid, fc_gjr_v, alpha_val, DF_FIXED)
    vr_vix, _, lr_vix, p_vix, pf_vix = var_backtest_kupiec(ret_oos_valid, fc_a4f_vix_v, alpha_val, DF_FIXED)
    print(f"    GJR:      VR={vr_gjr:.4f} (exp={alpha_val:.4f}), Kupiec p={p_gjr:.4f} [{pf_gjr}]")
    print(f"    A4f-VIX:  VR={vr_vix:.4f} (exp={alpha_val:.4f}), Kupiec p={p_vix:.4f} [{pf_vix}]")

    if has_vstoxx and fc_a4f_vstoxx is not None:
        vr_vs, _, lr_vs, p_vs, pf_vs = var_backtest_kupiec(ret_oos_valid, fc_a4f_vstoxx_v, alpha_val, DF_FIXED)
        print(f"    A4f-VSTOXX: VR={vr_vs:.4f} (exp={alpha_val:.4f}), Kupiec p={p_vs:.4f} [{pf_vs}]")

# ES backtesting
print("\n  ES Backtesting (Acerbi-Szekely 2014):")
for alpha_label, alpha_val in [('2.5%', 0.025), ('1%', 0.01)]:
    print(f"\n  --- ES {alpha_label} ---")
    z_gjr, p_gjr_es, vr_gjr_es, pf_gjr_es = es_backtest(ret_oos_valid, fc_gjr_v, alpha_val, DF_FIXED)
    z_vix, p_vix_es, vr_vix_es, pf_vix_es = es_backtest(ret_oos_valid, fc_a4f_vix_v, alpha_val, DF_FIXED)
    print(f"    GJR:      Z={z_gjr:.4f}, p={p_gjr_es:.4f} [{pf_gjr_es}]")
    print(f"    A4f-VIX:  Z={z_vix:.4f}, p={p_vix_es:.4f} [{pf_vix_es}]")

    if has_vstoxx and fc_a4f_vstoxx is not None:
        z_vs, p_vs_es, vr_vs_es, pf_vs_es = es_backtest(ret_oos_valid, fc_a4f_vstoxx_v, alpha_val, DF_FIXED)
        print(f"    A4f-VSTOXX: Z={z_vs:.4f}, p={p_vs_es:.4f} [{pf_vs_es}]")


# ============================================================
# REGIME ANALYSIS: VSTOXX regime-conditional QLIKE
# ============================================================
if has_vstoxx:
    print("\n[8] Regime Analysis (VSTOXX-based)...")
    vstoxx_oos = vstoxx_vals[oos_indices][valid_all]

    # Define regimes based on VSTOXX levels
    # Low: < 20% (decimal 0.20), Medium: 20-30%, High: > 30%
    vstoxx_pct = vstoxx_oos * 100  # back to percentage for interpretation
    regime_low = vstoxx_pct < 20
    regime_med = (vstoxx_pct >= 20) & (vstoxx_pct < 30)
    regime_high = vstoxx_pct >= 30

    regime_results = {}
    for regime_name, regime_mask in [('Low (<20)', regime_low), ('Medium (20-30)', regime_med), ('High (>30)', regime_high)]:
        n_regime = regime_mask.sum()
        if n_regime < 50:
            print(f"  {regime_name}: n={n_regime} (too few, skip)")
            regime_results[regime_name] = {'n': int(n_regime), 'status': 'skipped'}
            continue

        q_gjr_r = float(qlike_func(r2_v[regime_mask], fc_gjr_v[regime_mask]))
        q_vix_r = float(qlike_func(r2_v[regime_mask], fc_a4f_vix_v[regime_mask]))
        q_vs_r = float(qlike_func(r2_v[regime_mask], fc_a4f_vstoxx_v[regime_mask]))

        # DM within regime
        dm_r = dm_test(r2_v[regime_mask], fc_gjr_v[regime_mask], fc_a4f_vstoxx_v[regime_mask], loss='QLIKE')

        regime_results[regime_name] = {
            'n': int(n_regime),
            'qlike_gjr': q_gjr_r,
            'qlike_a4f_vix': q_vix_r,
            'qlike_a4f_vstoxx': q_vs_r,
            'dm_t_vstoxx_vs_gjr': float(dm_r['t_stat']),
            'dm_p_vstoxx_vs_gjr': float(dm_r['p_value']),
        }
        print(f"  {regime_name}: n={n_regime}")
        print(f"    QLIKE GJR={q_gjr_r:.6f}, A4f-VIX={q_vix_r:.6f}, A4f-VSTOXX={q_vs_r:.6f}")
        print(f"    DM(VSTOXX vs GJR): t={dm_r['t_stat']:.3f}")


# ============================================================
# COMPILE RESULTS
# ============================================================
print("\n[9] Compiling results...")

elapsed = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': f'VSTOXX-Driven A4f for European Equity Volatility ({euro_stoxx_ticker_used})',
    'status': 'completed',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': float(elapsed),
    'seed': 42,
    'config': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'df_fixed': DF_FIXED,
        'equity_ticker': euro_stoxx_ticker_used,
        'fear_source': fear_source,
        'has_vstoxx': has_vstoxx,
    },
    'descriptive_stats': desc_stats,
    'models': {
        'M1_GJR_t': {
            'description': f'GJR-GARCH(1,1)-t(df={DF_FIXED})',
            'qlike': qlike_gjr,
            'spearman': spearman_gjr,
            'n_valid': int(valid_gjr),
            'time_seconds': float(t_gjr),
        },
        'M2_A4f_VIX_t': {
            'description': f'A4f(VIX)-t(df={DF_FIXED}) — US fear as control',
            'qlike': qlike_a4f_vix,
            'spearman': spearman_a4f_vix,
            'n_valid': int(valid_a4f_vix),
            'time_seconds': float(t_a4f_vix),
            'dm_vs_gjr_t': float(dm_vix['t_stat']),
            'dm_vs_gjr_p': float(dm_vix['p_value']),
            'dm_sig_harvey': abs(dm_vix['t_stat']) > 3.0,
        },
    },
    'data_source': f'yfinance: {euro_stoxx_ticker_used}, ^VIX' + (', ^V2TX (VSTOXX)' if has_vstoxx else ''),
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey et al. (2016). t > 3.0 threshold for multiple testing.',
        'Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement Models.',
        'Acerbi & Szekely (2014). Back-testing Expected Shortfall.',
        'K988: A4f champion for SPY (DM t=+4.48)',
        'K994: Cross-asset QQQ pass, others not sig with US VIX',
        'K997: GLD+GVZ pass, EEM/0050.TW not sig',
    ],
}

# Add VSTOXX model results if available
if has_vstoxx and fc_a4f_vstoxx is not None:
    results['models']['M3_A4f_VSTOXX_t'] = {
        'description': f'A4f(VSTOXX)-t(df={DF_FIXED}) — European fear',
        'qlike': qlike_a4f_vstoxx,
        'spearman': spearman_a4f_vstoxx,
        'n_valid': int(valid_a4f_vstoxx),
        'time_seconds': float(t_a4f_vstoxx),
        'dm_vs_gjr_t': float(dm_vstoxx['t_stat']),
        'dm_vs_gjr_p': float(dm_vstoxx['p_value']),
        'dm_sig_harvey': abs(dm_vstoxx['t_stat']) > 3.0,
        'dm_vs_a4f_vix_t': float(dm_vstoxx_vs_vix['t_stat']),
        'dm_vs_a4f_vix_p': float(dm_vstoxx_vs_vix['p_value']),
    }
    results['regime_analysis'] = regime_results

# VaR/ES results
var_es_results = {}
for alpha_label, alpha_val in [('2.5%', 0.025), ('1%', 0.01)]:
    var_es_results[f'VaR_{alpha_label}'] = {}
    var_es_results[f'ES_{alpha_label}'] = {}

    vr_gjr, _, lr_gjr, p_gjr, pf_gjr = var_backtest_kupiec(ret_oos_valid, fc_gjr_v, alpha_val, DF_FIXED)
    vr_vix, _, lr_vix, p_vix, pf_vix = var_backtest_kupiec(ret_oos_valid, fc_a4f_vix_v, alpha_val, DF_FIXED)
    var_es_results[f'VaR_{alpha_label}']['GJR'] = {'violation_rate': vr_gjr, 'kupiec_p': p_gjr, 'pass': pf_gjr}
    var_es_results[f'VaR_{alpha_label}']['A4f_VIX'] = {'violation_rate': vr_vix, 'kupiec_p': p_vix, 'pass': pf_vix}

    z_gjr, p_gjr_es, _, pf_gjr_es = es_backtest(ret_oos_valid, fc_gjr_v, alpha_val, DF_FIXED)
    z_vix, p_vix_es, _, pf_vix_es = es_backtest(ret_oos_valid, fc_a4f_vix_v, alpha_val, DF_FIXED)
    var_es_results[f'ES_{alpha_label}']['GJR'] = {'z_stat': z_gjr, 'p_value': p_gjr_es, 'pass': pf_gjr_es}
    var_es_results[f'ES_{alpha_label}']['A4f_VIX'] = {'z_stat': z_vix, 'p_value': p_vix_es, 'pass': pf_vix_es}

    if has_vstoxx and fc_a4f_vstoxx is not None:
        vr_vs, _, lr_vs, p_vs, pf_vs = var_backtest_kupiec(ret_oos_valid, fc_a4f_vstoxx_v, alpha_val, DF_FIXED)
        var_es_results[f'VaR_{alpha_label}']['A4f_VSTOXX'] = {'violation_rate': vr_vs, 'kupiec_p': p_vs, 'pass': pf_vs}

        z_vs, p_vs_es, _, pf_vs_es = es_backtest(ret_oos_valid, fc_a4f_vstoxx_v, alpha_val, DF_FIXED)
        var_es_results[f'ES_{alpha_label}']['A4f_VSTOXX'] = {'z_stat': z_vs, 'p_value': p_vs_es, 'pass': pf_vs_es}

results['var_es_backtesting'] = var_es_results

# ============================================================
# CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSION:")
print("=" * 70)

# Determine conclusion
if has_vstoxx and fc_a4f_vstoxx is not None:
    dm_t_vstoxx = dm_vstoxx['t_stat']
    dm_t_vix = dm_vix['t_stat']
    dm_t_head2head = dm_vstoxx_vs_vix['t_stat']

    if abs(dm_t_vstoxx) > 3.0 and qlike_a4f_vstoxx < qlike_gjr:
        conclusion = f"A4f-VSTOXX significantly beats GJR (DM t={dm_t_vstoxx:.3f}, |t|>3.0). VSTOXX is an effective European fear driver."
        significance = "SIGNIFICANT"
    elif qlike_a4f_vstoxx < qlike_gjr and abs(dm_t_vstoxx) > 2.0:
        conclusion = f"A4f-VSTOXX improves over GJR (DM t={dm_t_vstoxx:.3f}) but does not reach Harvey threshold (|t|>3.0)."
        significance = "MARGINAL"
    else:
        conclusion = f"A4f-VSTOXX does not significantly improve over GJR (DM t={dm_t_vstoxx:.3f})."
        significance = "NOT_SIGNIFICANT"

    if abs(dm_t_head2head) > 2.0:
        if qlike_a4f_vstoxx < qlike_a4f_vix:
            conclusion += f" VSTOXX outperforms US VIX as τ driver (DM t={dm_t_head2head:.3f})."
        else:
            conclusion += f" US VIX outperforms VSTOXX as τ driver (DM t={dm_t_head2head:.3f})."
    else:
        conclusion += f" VSTOXX and US VIX are similar as τ drivers (DM t={dm_t_head2head:.3f})."

    results['conclusion'] = conclusion
    results['significance'] = significance
else:
    conclusion = "VSTOXX data unavailable. Only US VIX tested as control."
    results['conclusion'] = conclusion
    results['significance'] = 'N/A'

print(f"  {conclusion}")
print(f"  Total time: {elapsed:.1f}s")

# Save results
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")


# ============================================================
# CHARTS
# ============================================================
print("\n[10] Generating charts...")

# Chart 1: QLIKE comparison bar chart
fig, ax = plt.subplots(figsize=(8, 5))
models = ['GJR-t', 'A4f-VIX-t']
qlikes = [qlike_gjr, qlike_a4f_vix]
colors = ['#2196F3', '#FF9800']
if has_vstoxx and fc_a4f_vstoxx is not None:
    models.append('A4f-VSTOXX-t')
    qlikes.append(qlike_a4f_vstoxx)
    colors.append('#4CAF50')

bars = ax.bar(models, qlikes, color=colors, edgecolor='black', linewidth=0.5)
ax.set_ylabel('QLIKE (lower is better)', fontsize=12)
ax.set_title(f'K1030: QLIKE Comparison — {euro_stoxx_ticker_used}\n'
             f'(OOS: {OOS_START}–{df_data.index[-1].strftime("%Y-%m-%d")}, n={n_valid})',
             fontsize=13, fontweight='bold')

# Add value labels
for bar, val in zip(bars, qlikes):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
            f'{val:.4f}', ha='center', va='bottom', fontsize=10)

# Add DM annotation
if has_vstoxx and fc_a4f_vstoxx is not None:
    dm_text = f"DM(VSTOXX vs GJR): t={dm_vstoxx['t_stat']:.2f}\n"
    dm_text += f"DM(VSTOXX vs VIX): t={dm_vstoxx_vs_vix['t_stat']:.2f}"
    ax.text(0.98, 0.95, dm_text, transform=ax.transAxes, ha='right', va='top',
            fontsize=9, bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', edgecolor='gray'))

plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1030_qlike_comparison.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")

# Chart 2: Rolling VSTOXX-r² correlation + VIX-r² correlation
if has_vstoxx:
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    oos_dates = df_data.index[oos_mask][valid_all]
    dates_roll = oos_dates[roll_window:]

    ax1 = axes[0]
    ax1.plot(dates_roll, roll_corr_vstoxx, color='#4CAF50', alpha=0.8, label='VSTOXX-r² corr')
    ax1.plot(dates_roll, roll_corr_vix, color='#FF9800', alpha=0.8, label='VIX-r² corr')
    ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)
    ax1.set_ylabel('Rolling Correlation (63d)', fontsize=11)
    ax1.set_title(f'K1030: Fear Index — Return² Correlation ({euro_stoxx_ticker_used})', fontsize=13, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    # Plot VSTOXX level over time
    vstoxx_oos_plot = vstoxx_vals[oos_indices][valid_all] * 100  # back to %
    ax2.fill_between(oos_dates, vstoxx_oos_plot, alpha=0.3, color='#4CAF50', label='VSTOXX level (%)')
    ax2.axhline(20, color='green', linestyle='--', alpha=0.5, label='Low/Med (20%)')
    ax2.axhline(30, color='red', linestyle='--', alpha=0.5, label='Med/High (30%)')
    ax2.set_ylabel('VSTOXX (%)', fontsize=11)
    ax2.set_xlabel('Date', fontsize=11)
    ax2.legend(fontsize=9, loc='upper right')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    chart2_path = os.path.join(SCRIPT_DIR, 'k1030_correlation_dynamics.png')
    plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {chart2_path}")

# Chart 3: Regime analysis bar chart
if has_vstoxx and 'regime_analysis' in results:
    fig, ax = plt.subplots(figsize=(9, 5))
    regime_names = []
    qlike_gjr_vals = []
    qlike_vix_vals = []
    qlike_vstoxx_vals = []
    dm_vals = []

    for rname, rdata in results['regime_analysis'].items():
        if rdata.get('status') == 'skipped':
            continue
        regime_names.append(f"{rname}\n(n={rdata['n']})")
        qlike_gjr_vals.append(rdata['qlike_gjr'])
        qlike_vix_vals.append(rdata['qlike_a4f_vix'])
        qlike_vstoxx_vals.append(rdata['qlike_a4f_vstoxx'])
        dm_vals.append(rdata['dm_t_vstoxx_vs_gjr'])

    x = np.arange(len(regime_names))
    width = 0.25

    bars1 = ax.bar(x - width, qlike_gjr_vals, width, label='GJR-t', color='#2196F3', edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x, qlike_vix_vals, width, label='A4f-VIX-t', color='#FF9800', edgecolor='black', linewidth=0.5)
    bars3 = ax.bar(x + width, qlike_vstoxx_vals, width, label='A4f-VSTOXX-t', color='#4CAF50', edgecolor='black', linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(regime_names, fontsize=10)
    ax.set_ylabel('QLIKE (lower is better)', fontsize=11)
    ax.set_title(f'K1030: Regime-Conditional QLIKE — {euro_stoxx_ticker_used}', fontsize=13, fontweight='bold')
    ax.legend(fontsize=10)

    # Add DM annotations
    for i, dm_t in enumerate(dm_vals):
        sig = "***" if abs(dm_t) > 3.0 else "**" if abs(dm_t) > 2.0 else ""
        ax.text(x[i] + width, min(qlike_vstoxx_vals[i], qlike_gjr_vals[i]) * 0.95,
                f't={dm_t:.1f}{sig}', ha='center', fontsize=8, color='darkgreen')

    plt.tight_layout()
    chart3_path = os.path.join(SCRIPT_DIR, 'k1030_regime_qlike.png')
    plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {chart3_path}")

# Chart 4: DM test summary
fig, ax = plt.subplots(figsize=(7, 4))
dm_labels = ['A4f-VIX vs GJR']
dm_t_values = [dm_vix['t_stat']]
dm_colors = ['#FF9800']

if has_vstoxx and fc_a4f_vstoxx is not None:
    dm_labels.extend(['A4f-VSTOXX vs GJR', 'A4f-VSTOXX vs A4f-VIX'])
    dm_t_values.extend([dm_vstoxx['t_stat'], dm_vstoxx_vs_vix['t_stat']])
    dm_colors.extend(['#4CAF50', '#9C27B0'])

bars = ax.barh(dm_labels, dm_t_values, color=dm_colors, edgecolor='black', linewidth=0.5)
ax.axvline(3.0, color='red', linestyle='--', alpha=0.7, label='Harvey |t|=3.0')
ax.axvline(-3.0, color='red', linestyle='--', alpha=0.7)
ax.axvline(0, color='gray', linestyle='-', alpha=0.3)
ax.set_xlabel('DM t-statistic (positive = first model better)', fontsize=11)
ax.set_title(f'K1030: DM Test Summary — {euro_stoxx_ticker_used}', fontsize=13, fontweight='bold')
ax.legend(fontsize=9)

for bar, val in zip(bars, dm_t_values):
    x_pos = val + 0.1 if val > 0 else val - 0.1
    ha = 'left' if val > 0 else 'right'
    ax.text(x_pos, bar.get_y() + bar.get_height()/2, f'{val:.2f}',
            ha=ha, va='center', fontsize=10, fontweight='bold')

plt.tight_layout()
chart4_path = os.path.join(SCRIPT_DIR, 'k1030_dm_test_summary.png')
plt.savefig(chart4_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart4_path}")

print(f"\n{'='*70}")
print(f"K1030 COMPLETE. Total time: {elapsed:.1f}s")
print(f"{'='*70}")
