#!/usr/bin/env python3
"""
K889: Multiplicative Volatility Factor (MVF) Model
====================================================
[提出: Claude, 執行: Claude]

Background:
  Standard GARCH: h_t = omega + alpha * r^2_{t-1} + beta * h_{t-1}  (additive)
  Multiplicative approach: sigma^2_t = tau_t * g_t
  where tau_t = slow-moving (long-run) component, g_t = fast (short-run) component.

  Related to GARCH-MIDAS (Engle, Ghysels, Sohn 2013) and Spline-GARCH
  (Engle & Rangel 2008), but here we test a practical multiplicative
  decomposition using VIX as the macro factor.

  Knowledge base context:
    - K526: GARCH-MIDAS(INDPRO) OOS DM t=-3.21 but sample-specific
    - K526 cross-asset: QQQ/EEM all NS => GARCH-MIDAS has no robust OOS advantage
    - QLIKE ceiling confirmed 5+ times: no daily-frequency model beats GJR OOS
    - Conrad (2025) MF2-GARCH: Multiplicative Factor Multi-Frequency GARCH
      significantly outperforms GJR, GARCH-MIDAS-RV, and log-HAR for S&P 500.
      Uses prediction error pattern. J. Applied Econometrics.

Models:
  M1: MF-GARCH (Multiplicative Factor GARCH)
      Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
      Short-run: g_t follows GARCH(1,1) on standardized returns (r_t / sqrt(tau_t))
      Total: sigma^2_t = tau_t * g_t

  M2: MF-GJR (with leverage in short-run)
      Same as M1 but g_t follows GJR-GARCH(1,1)

  M3: EWMA-Factor
      Long-run: tau_t = EWMA(r^2_t, lambda=0.99)  ~ 250-day window
      Short-run: g_t = EWMA(r^2_t / tau_t, lambda=0.94)
      Total: sigma^2_t = tau_t * g_t

  Benchmarks:
  B1: GJR-GARCH(1,1) — standard
  B2: EWMA(0.94) — simple

Data:
  - Assets: SPY, QQQ, 0050.TW
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - VIX from yfinance (^VIX)
  - 0050.TW: clean_tw50_data (mandatory)
  - 0050.TW: use previous day's VIX (cross-market lag)

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - DM tests with Harvey (2016) |t| > 3.0
  - Spearman rank correlation
  - MCS (Model Confidence Set)
  - VaR 1% + 5% Trinity test (Kupiec + Christoffersen + Basel)

Error Log rules:
  - DM test: use volpred.stats.model_evaluation (not self-written)
  - 0050.TW: must call clean_tw50_data
  - GARCH OOS: recursive h[t] = f(h[t-1], r^2[t-1]), no stale variance
  - Student-t: scale term sqrt((df-2)/df)
  - Basel: use standard thresholds

Key Questions:
  1. Does multiplicative decomposition improve over GJR?
  2. Does VIX as long-run factor add value?
  3. Does short-run still cluster after removing long-run?
  4. Is MF-GJR better than MF-GARCH? (leverage in short-run)

References:
  - Engle, Ghysels & Sohn (2013). Stock market volatility and macroeconomic
    fundamentals. RES 95(3):776-797.
  - Engle & Rangel (2008). The Spline-GARCH model for low-frequency
    volatility and its global macroeconomic causes. RFS 21(3):1187-1222.
  - Conrad & Engle (2025). Two-factor GARCH models. (MF2-GARCH)
  - Patton (2011). Volatility forecast comparison using imperfect
    volatility proxies. J Econometrics 160:246-256.
  - Harvey et al. (2016). Tests for forecast encompassing. JBES 34:92-104.

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
from concurrent.futures import ProcessPoolExecutor, as_completed

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K889"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k889_multiplicative_vol_factor_results.json')

# Data parameters
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
ASSETS = ['SPY', 'QQQ', '0050.TW']

print("=" * 70)
print(f"{EXPERIMENT_ID}: Multiplicative Volatility Factor (MVF) Model")
print("  Separating long-run (VIX-driven) from short-run (GARCH) components")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

def load_asset_data(ticker, vix_data):
    """Load asset data with VIX alignment."""
    print(f"  Loading {ticker}...")
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    # For 0050.TW: clean split artifacts
    if '0050' in ticker:
        prices, log_ret = clean_tw50_data(prices, log_ret)

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
    df = df.dropna(subset=['log_ret'])

    # Merge VIX
    if '0050' in ticker or 'TW' in ticker:
        # Taiwan: use previous day's VIX (cross-market lag)
        vix_shifted = vix_data.shift(1)
        df = df.join(vix_shifted, how='left')
    else:
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
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
for ticker in ASSETS:
    ret = asset_data[ticker]['log_ret'].values
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

    print(f"  {ticker}: Mean={desc['mean']:.6f} Std={desc['std']:.4f} "
          f"Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.2f} "
          f"JB={jb_stat:.0f}(p={jb_p:.1e}) ARCH_LM={arch_lm:.1f}")


# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS (Numba-accelerated)
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
def gjr_garch_forecast_oos(params, returns, h_prev):
    """One-step GJR-GARCH forecast given previous h and return."""
    omega, alpha, gamma, beta = params
    r_prev = returns
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev
    return max(h_next, 1e-10)


@njit(cache=True)
def garch_on_standardized_loglik(params, std_returns):
    """GARCH(1,1) on standardized returns (for MF-GARCH short-run g_t).
    g_t follows: g_t = (1-a-b) + a * u^2_{t-1} + b * g_{t-1}
    where u_t = r_t / sqrt(tau_t) are the standardized returns.
    """
    alpha, beta = params
    omega = 1.0 - alpha - beta  # unconditional mean = 1
    n = len(std_returns)
    g = np.empty(n)
    g[0] = 1.0  # initialize at unconditional mean
    ll = 0.0

    for t in range(1, n):
        g[t] = omega + alpha * std_returns[t-1]**2 + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    for t in range(n):
        if g[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(g[t]) + std_returns[t]**2 / g[t])

    return -ll


@njit(cache=True)
def gjr_on_standardized_loglik(params, std_returns):
    """GJR-GARCH(1,1) on standardized returns (for MF-GJR short-run g_t).
    g_t = (1-a-g/2-b) + a * u^2_{t-1} + gamma * u^2_{t-1}*I(u<0) + b * g_{t-1}
    Unconditional mean = 1 when omega = 1-alpha-gamma/2-beta.
    """
    alpha, gamma, beta = params
    omega = 1.0 - alpha - gamma / 2.0 - beta
    n = len(std_returns)
    g = np.empty(n)
    g[0] = 1.0
    ll = 0.0

    for t in range(1, n):
        asym = gamma * std_returns[t-1]**2 if std_returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * std_returns[t-1]**2 + asym + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    for t in range(n):
        if g[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(g[t]) + std_returns[t]**2 / g[t])

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
    """Fit MF-GARCH or MF-GJR.

    Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
    Short-run: g_t = GARCH(1,1) or GJR-GARCH(1,1) on u_t = r_t/sqrt(tau_t)
    Total: sigma^2_t = tau_t * g_t

    Two-step estimation:
      Step 1: OLS of log(r^2_t) on log(VIX_{t-1}) to get tau_t
      Step 2: MLE of GARCH/GJR on standardized returns u_t = r_t / sqrt(tau_t)
    """
    n = len(returns)
    assert len(log_vix) == n

    # Step 1: Estimate long-run component via regression
    # tau_t = exp(theta_0 + theta_1 * log_vix_{t-1})
    # Use log(r^2_t) ~ theta_0 + theta_1 * log_vix_{t-1} to get starting values
    # Then optimize jointly
    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]  # fill first element

    # OLS for initial theta
    X_ols = np.column_stack([np.ones(n), log_vix_lag])
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    # Joint MLE: [theta_0, theta_1, alpha, (gamma,) beta]
    def neg_loglik(params):
        if model_type == 'gjr':
            theta0, theta1, alpha, gamma, beta = params
        else:
            theta0, theta1, alpha, beta = params
            gamma = 0.0

        # Long-run component
        log_tau = theta0 + theta1 * log_vix_lag
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        # Standardized returns
        u = returns / np.sqrt(tau)

        # Short-run component
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

        # Total variance: sigma^2_t = tau_t * g_t
        sigma2 = tau * g

        # Log-likelihood
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


def forecast_mf_garch(params, returns, log_vix, model_type='garch'):
    """Generate OOS forecasts from MF-GARCH/MF-GJR model.

    Returns array of sigma^2 forecasts (one per OOS day).
    Uses expanding window with periodic refitting.
    """
    n = len(returns)

    if model_type == 'gjr':
        theta0, theta1, alpha, gamma, beta = params
    else:
        theta0, theta1, alpha, beta = params
        gamma = 0.0

    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    # Reconstruct in-sample g_t to get last g
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


def ewma_factor_forecast(returns, lambda_slow=0.99, lambda_fast=0.94):
    """EWMA-Factor model: slow EWMA for long-run, fast EWMA on standardized for short-run."""
    n = len(returns)
    r2 = returns ** 2

    # Long-run: EWMA(0.99) ~ 250-day effective window
    tau = np.empty(n)
    tau[0] = np.mean(r2[:min(50, n)])
    for t in range(1, n):
        tau[t] = lambda_slow * tau[t-1] + (1 - lambda_slow) * r2[t-1]
        tau[t] = max(tau[t], 1e-16)

    # Short-run: EWMA(0.94) on standardized squared returns
    u2 = r2 / tau
    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        g[t] = lambda_fast * g[t-1] + (1 - lambda_fast) * u2[t-1]
        g[t] = max(g[t], 1e-10)

    sigma2 = tau * g
    return sigma2, g, tau


def ewma_forecast(returns, lam=0.94):
    """Simple EWMA(0.94) benchmark."""
    n = len(returns)
    r2 = returns ** 2
    h = np.empty(n)
    h[0] = np.mean(r2[:min(50, n)])
    for t in range(1, n):
        h[t] = lam * h[t-1] + (1 - lam) * r2[t-1]
        h[t] = max(h[t], 1e-10)
    return h


# ============================================================
# SECTION 4: ROLLING OOS EVALUATION
# ============================================================
print("\n[4] Rolling OOS evaluation...")


def run_oos_for_asset(ticker, df):
    """Run all 5 models OOS for a single asset."""
    print(f"\n  === {ticker} ===")

    ret = df['log_ret'].values
    log_vix_raw = np.log(df['VIX'].values)
    r2 = ret ** 2
    dates = df.index

    # Find OOS start index
    oos_mask = dates >= OOS_START
    oos_start_idx = np.argmax(oos_mask)
    if oos_start_idx < WINDOW:
        oos_start_idx = WINDOW
    print(f"    OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")

    n_oos = len(ret) - oos_start_idx
    print(f"    OOS days: {n_oos}")

    # Storage for forecasts
    models = ['GJR', 'MF-GARCH', 'MF-GJR', 'EWMA-Factor', 'EWMA']
    forecasts = {m: np.full(n_oos, np.nan) for m in models}
    oos_returns = ret[oos_start_idx:]
    oos_r2 = r2[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    # Track parameters and components for analysis
    tau_mfgarch = np.full(n_oos, np.nan)
    g_mfgarch = np.full(n_oos, np.nan)
    tau_mfgjr = np.full(n_oos, np.nan)
    g_mfgjr = np.full(n_oos, np.nan)

    # ---- Rolling estimation ----
    last_gjr_params = None
    last_gjr_h = None
    last_mfgarch_params = None
    last_mfgjr_params = None
    last_mfgarch_g = None
    last_mfgjr_g = None

    n_refits = 0
    for t in range(n_oos):
        idx = oos_start_idx + t
        need_refit = (t == 0) or (t % REFIT_EVERY == 0)

        # Training window
        train_start = max(0, idx - WINDOW)
        train_ret = ret[train_start:idx]
        train_vix = log_vix_raw[train_start:idx]

        if need_refit:
            n_refits += 1

            # Fit GJR-GARCH
            gjr_params, gjr_ll = fit_gjr_garch(train_ret)
            if gjr_params is not None:
                last_gjr_params = gjr_params
                # Reconstruct last h
                h_arr = np.empty(len(train_ret))
                h_arr[0] = np.var(train_ret)
                for tt in range(1, len(train_ret)):
                    omega, alpha, gamma_g, beta = gjr_params
                    asym = gamma_g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                    h_arr[tt] = omega + alpha * train_ret[tt-1]**2 + asym + beta * h_arr[tt-1]
                    h_arr[tt] = max(h_arr[tt], 1e-10)
                last_gjr_h = h_arr[-1]

            # Fit MF-GARCH
            mfg_params, mfg_ll = fit_mf_garch(train_ret, train_vix, model_type='garch')
            if mfg_params is not None:
                last_mfgarch_params = mfg_params
                _, g_arr, _ = forecast_mf_garch(mfg_params, train_ret, train_vix, 'garch')
                last_mfgarch_g = g_arr[-1]

            # Fit MF-GJR
            mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_vix, model_type='gjr')
            if mfgjr_params is not None:
                last_mfgjr_params = mfgjr_params
                _, g_arr, _ = forecast_mf_garch(mfgjr_params, train_ret, train_vix, 'gjr')
                last_mfgjr_g = g_arr[-1]

        # === Generate one-step-ahead forecasts ===

        # GJR-GARCH: recursive h[t] = f(h[t-1], r^2[t-1])
        if last_gjr_params is not None and last_gjr_h is not None:
            if t == 0:
                # Use reconstructed h from training
                pass
            else:
                # Update h using yesterday's actual return
                last_gjr_h = gjr_garch_forecast_oos(
                    last_gjr_params, ret[idx-1], last_gjr_h)
            forecasts['GJR'][t] = last_gjr_h

        # MF-GARCH: tau_{t} from VIX_{t-1}, g_{t} = recursive on standardized
        if last_mfgarch_params is not None:
            theta0, theta1, alpha_mf, beta_mf = last_mfgarch_params
            # Long-run from yesterday's VIX
            log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
            tau_t = np.exp(log_tau_t)
            tau_t = max(tau_t, 1e-16)

            if t == 0:
                g_t = last_mfgarch_g if last_mfgarch_g is not None else 1.0
            else:
                # Update g using yesterday's standardized return
                u_prev = ret[idx-1] / np.sqrt(tau_prev_mfgarch)
                omega_g = 1.0 - alpha_mf - beta_mf
                g_t = omega_g + alpha_mf * u_prev**2 + beta_mf * last_mfgarch_g
                g_t = max(g_t, 1e-10)

            tau_prev_mfgarch = tau_t
            last_mfgarch_g = g_t
            forecasts['MF-GARCH'][t] = tau_t * g_t
            tau_mfgarch[t] = tau_t
            g_mfgarch[t] = g_t

        # MF-GJR: same but with leverage in g_t
        if last_mfgjr_params is not None:
            theta0, theta1, alpha_mf, gamma_mf, beta_mf = last_mfgjr_params
            log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
            tau_t = np.exp(log_tau_t)
            tau_t = max(tau_t, 1e-16)

            if t == 0:
                g_t = last_mfgjr_g if last_mfgjr_g is not None else 1.0
            else:
                u_prev = ret[idx-1] / np.sqrt(tau_prev_mfgjr)
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                asym = gamma_mf * u_prev**2 if u_prev < 0 else 0.0
                g_t = omega_g + alpha_mf * u_prev**2 + asym + beta_mf * last_mfgjr_g
                g_t = max(g_t, 1e-10)

            tau_prev_mfgjr = tau_t
            last_mfgjr_g = g_t
            forecasts['MF-GJR'][t] = tau_t * g_t
            tau_mfgjr[t] = tau_t
            g_mfgjr[t] = g_t

        # EWMA-Factor: no fitting needed, just recursive
        if t == 0:
            # Initialize tau and g from training data
            ewma_sigma2, ewma_g_init, ewma_tau_init = ewma_factor_forecast(train_ret)
            last_ewma_tau = ewma_tau_init[-1]
            last_ewma_g = ewma_g_init[-1]

        # Update tau and g
        tau_t = 0.99 * last_ewma_tau + 0.01 * ret[idx-1]**2
        tau_t = max(tau_t, 1e-16)
        u2_prev = ret[idx-1]**2 / last_ewma_tau
        g_t = 0.94 * last_ewma_g + 0.06 * u2_prev
        g_t = max(g_t, 1e-10)
        last_ewma_tau = tau_t
        last_ewma_g = g_t
        forecasts['EWMA-Factor'][t] = tau_t * g_t

        # Simple EWMA: no fitting needed
        if t == 0:
            ewma_h = ewma_forecast(train_ret)
            last_ewma_h = ewma_h[-1]

        last_ewma_h = 0.94 * last_ewma_h + 0.06 * ret[idx-1]**2
        last_ewma_h = max(last_ewma_h, 1e-10)
        forecasts['EWMA'][t] = last_ewma_h

    print(f"    Refits: {n_refits}")

    # ============================================================
    # SECTION 5: EVALUATION
    # ============================================================

    # 5a: QLIKE on r^2 (Patton 2011)
    qlike_results = {}
    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 100:
            qlike_results[m] = qlike(oos_r2[valid], f[valid])
        else:
            qlike_results[m] = np.nan

    # Normalize to GJR baseline
    gjr_qlike = qlike_results['GJR']
    qlike_pct = {}
    for m in models:
        if np.isfinite(qlike_results[m]) and np.isfinite(gjr_qlike) and gjr_qlike > 0:
            qlike_pct[m] = ((qlike_results[m] - gjr_qlike) / gjr_qlike) * 100
        else:
            qlike_pct[m] = np.nan

    print(f"\n    QLIKE on r^2 (Patton 2011):")
    for m in models:
        pct = qlike_pct.get(m, np.nan)
        print(f"      {m:15s}: {qlike_results[m]:.6f} ({pct:+.3f}% vs GJR)")

    # 5b: Spearman rank correlation
    spearman_results = {}
    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 100:
            rho, p = spearman_corr(oos_r2[valid], f[valid])
            spearman_results[m] = {'rho': rho, 'p': p}
        else:
            spearman_results[m] = {'rho': np.nan, 'p': np.nan}

    print(f"\n    Spearman rank correlation:")
    for m in models:
        r = spearman_results[m]
        print(f"      {m:15s}: rho={r['rho']:.4f} (p={r['p']:.2e})")

    # 5c: DM tests (pairwise against GJR)
    gjr_loss = qlike_pointwise(oos_r2, forecasts['GJR'])
    dm_results = {}
    for m in models:
        if m == 'GJR':
            dm_results[m] = {'t': 0.0, 'p': 1.0}
            continue
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0) & np.isfinite(gjr_loss)
        if valid.sum() > 100:
            m_loss = qlike_pointwise(oos_r2[valid], f[valid])
            t_stat, p_val = dm_test(m_loss, gjr_loss[valid])
            dm_results[m] = {'t': float(t_stat), 'p': float(p_val)}
        else:
            dm_results[m] = {'t': np.nan, 'p': np.nan}

    print(f"\n    DM tests vs GJR (negative t = model is better):")
    for m in models:
        r = dm_results[m]
        sig = "***" if abs(r['t']) > 3.0 else ("*" if abs(r['t']) > 1.96 else "NS")
        print(f"      {m:15s}: t={r['t']:+.3f} (p={r['p']:.4f}) {sig}")

    # 5d: MCS (Model Confidence Set)
    # Simple implementation: eliminate models with worst QLIKE one by one
    mcs_models = [m for m in models if np.isfinite(qlike_results.get(m, np.nan))]
    mcs_survived = list(mcs_models)  # All survive initially

    # Pairwise tests: eliminate any model significantly worse than best
    best_model = min(mcs_models, key=lambda m: qlike_results[m])
    best_loss = qlike_pointwise(oos_r2, forecasts[best_model])

    for m in mcs_models:
        if m == best_model:
            continue
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0) & np.isfinite(best_loss)
        if valid.sum() > 100:
            m_loss = qlike_pointwise(oos_r2[valid], f[valid])
            t_stat, p_val = dm_test(m_loss, best_loss[valid])
            # If significantly worse (t > 3.0), eliminate
            if t_stat > 3.0:
                mcs_survived.remove(m)

    print(f"\n    MCS (alpha=0.05, Harvey t>3.0):")
    print(f"      Best model: {best_model}")
    print(f"      Survived: {mcs_survived}")
    print(f"      Eliminated: {[m for m in mcs_models if m not in mcs_survived]}")

    # 5e: VaR Trinity test (1% and 5%)
    var_results = {}
    for alpha in ALPHA_LEVELS:
        var_results[alpha] = {}
        z = norm.ppf(alpha)  # negative for left tail

        for m in models:
            f = forecasts[m]
            valid = np.isfinite(f) & (f > 0)
            if valid.sum() < 100:
                var_results[alpha][m] = {'violations': np.nan, 'rate': np.nan,
                                         'kupiec_p': np.nan, 'cc_p': np.nan,
                                         'basel': 'N/A', 'trinity': False}
                continue

            sigma = np.sqrt(f[valid])
            var_threshold = z * sigma  # negative values
            actual_ret = oos_returns[valid]

            violations = actual_ret < var_threshold
            n_viol = int(np.sum(violations))
            n_total = int(len(actual_ret))
            viol_rate = n_viol / n_total

            # Kupiec (1995) unconditional coverage test
            p_hat = viol_rate
            if 0 < p_hat < 1:
                kupiec_lr = 2 * (n_viol * np.log(p_hat / alpha) +
                                 (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
                kupiec_p = 1 - chi2.cdf(kupiec_lr, 1) if kupiec_lr > 0 else 1.0
            else:
                kupiec_p = 0.0 if p_hat == 0 and alpha > 0 else 1.0

            # Christoffersen (1998) conditional coverage
            # Simple version: test independence of violations
            n00 = n01 = n10 = n11 = 0
            for i in range(1, n_total):
                if not violations.iloc[i-1] if hasattr(violations, 'iloc') else not violations[i-1]:
                    if not (violations.iloc[i] if hasattr(violations, 'iloc') else violations[i]):
                        n00 += 1
                    else:
                        n01 += 1
                else:
                    if not (violations.iloc[i] if hasattr(violations, 'iloc') else violations[i]):
                        n10 += 1
                    else:
                        n11 += 1

            # Independence LR
            if (n00 + n01) > 0 and (n10 + n11) > 0:
                p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
                p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
                p_pool = (n01 + n11) / n_total if n_total > 0 else 0

                if 0 < p_pool < 1 and 0 < p01 < 1 and 0 < p11 < 1:
                    lr_ind = 2 * (
                        n00 * np.log(1 - p01) + n01 * np.log(p01) +
                        n10 * np.log(1 - p11) + n11 * np.log(p11) -
                        (n00 + n10) * np.log(1 - p_pool) -
                        (n01 + n11) * np.log(p_pool)
                    )
                    cc_p = 1 - chi2.cdf(max(0, lr_ind + max(0, kupiec_lr if kupiec_lr > 0 else 0)), 2)
                else:
                    cc_p = 1.0
            else:
                cc_p = 1.0

            # Basel traffic light
            if alpha == 0.01:
                if n_viol <= 4:
                    basel = "GREEN"
                elif n_viol <= 9:
                    basel = "YELLOW"
                else:
                    basel = "RED"
            else:
                # For 5% VaR, scale thresholds
                expected = int(n_total * 0.05)
                if n_viol <= expected + 4:
                    basel = "GREEN"
                elif n_viol <= expected + 9:
                    basel = "YELLOW"
                else:
                    basel = "RED"

            # Trinity: PASS if Kupiec OK + CC OK + Basel GREEN
            trinity_pass = (kupiec_p > 0.05) and (cc_p > 0.05) and (basel == "GREEN")

            var_results[alpha][m] = {
                'violations': n_viol,
                'total': n_total,
                'rate': round(viol_rate, 4),
                'expected_rate': alpha,
                'kupiec_p': round(kupiec_p, 4),
                'cc_p': round(cc_p, 4),
                'basel': basel,
                'trinity': trinity_pass
            }

    for alpha in ALPHA_LEVELS:
        print(f"\n    VaR {int(alpha*100)}% Trinity:")
        for m in models:
            r = var_results[alpha][m]
            print(f"      {m:15s}: {r['violations']}/{r.get('total','?')} "
                  f"({r['rate']:.3f}) Kupiec p={r['kupiec_p']:.3f} "
                  f"CC p={r['cc_p']:.3f} Basel={r['basel']} "
                  f"Trinity={'PASS' if r['trinity'] else 'FAIL'}")

    # 5f: Component analysis (short-run clustering after removing long-run)
    component_analysis = {}
    for m_name, tau_arr, g_arr in [('MF-GARCH', tau_mfgarch, g_mfgarch),
                                    ('MF-GJR', tau_mfgjr, g_mfgjr)]:
        valid = np.isfinite(tau_arr) & np.isfinite(g_arr)
        if valid.sum() > 50:
            # Variance ratios
            total_var = np.var(np.log(tau_arr[valid] * g_arr[valid]))
            tau_var = np.var(np.log(tau_arr[valid]))
            g_var = np.var(np.log(g_arr[valid]))

            # Autocorrelation of g_t (should still cluster)
            g_clean = g_arr[valid]
            if len(g_clean) > 10:
                g_ac1 = np.corrcoef(g_clean[:-1], g_clean[1:])[0, 1]
                g_ac5 = np.corrcoef(g_clean[:-5], g_clean[5:])[0, 1] if len(g_clean) > 5 else np.nan
            else:
                g_ac1 = g_ac5 = np.nan

            component_analysis[m_name] = {
                'tau_var_pct': round(tau_var / total_var * 100, 1) if total_var > 0 else np.nan,
                'g_var_pct': round(g_var / total_var * 100, 1) if total_var > 0 else np.nan,
                'g_autocorr_1': round(g_ac1, 4),
                'g_autocorr_5': round(g_ac5, 4),
                'tau_mean': round(float(np.mean(tau_arr[valid])), 8),
                'g_mean': round(float(np.mean(g_arr[valid])), 4),
            }

    print(f"\n    Component analysis (long-run vs short-run):")
    for m_name, ca in component_analysis.items():
        print(f"      {m_name}: tau_var={ca['tau_var_pct']}% g_var={ca['g_var_pct']}% "
              f"g_AC(1)={ca['g_autocorr_1']:.3f} g_AC(5)={ca['g_autocorr_5']:.3f}")

    # Collect parameters for reporting
    param_report = {}
    if last_gjr_params is not None:
        param_report['GJR'] = {
            'omega': float(last_gjr_params[0]),
            'alpha': float(last_gjr_params[1]),
            'gamma': float(last_gjr_params[2]),
            'beta': float(last_gjr_params[3]),
            'persistence': float(last_gjr_params[1] + last_gjr_params[2]/2 + last_gjr_params[3])
        }
    if last_mfgarch_params is not None:
        param_report['MF-GARCH'] = {
            'theta_0': float(last_mfgarch_params[0]),
            'theta_1': float(last_mfgarch_params[1]),
            'alpha': float(last_mfgarch_params[2]),
            'beta': float(last_mfgarch_params[3]),
            'persistence_g': float(last_mfgarch_params[2] + last_mfgarch_params[3])
        }
    if last_mfgjr_params is not None:
        param_report['MF-GJR'] = {
            'theta_0': float(last_mfgjr_params[0]),
            'theta_1': float(last_mfgjr_params[1]),
            'alpha': float(last_mfgjr_params[2]),
            'gamma': float(last_mfgjr_params[3]),
            'beta': float(last_mfgjr_params[4]),
            'persistence_g': float(last_mfgjr_params[2] + last_mfgjr_params[3]/2 + last_mfgjr_params[4])
        }

    return {
        'ticker': ticker,
        'n_oos': int(n_oos),
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'n_refits': n_refits,
        'qlike': {m: round(v, 6) if np.isfinite(v) else None for m, v in qlike_results.items()},
        'qlike_pct_vs_gjr': {m: round(v, 3) if np.isfinite(v) else None for m, v in qlike_pct.items()},
        'spearman': {m: {'rho': round(v['rho'], 4) if np.isfinite(v['rho']) else None,
                         'p': round(v['p'], 6) if np.isfinite(v['p']) else None}
                     for m, v in spearman_results.items()},
        'dm_vs_gjr': {m: {'t': round(v['t'], 3) if np.isfinite(v['t']) else None,
                          'p': round(v['p'], 4) if np.isfinite(v['p']) else None,
                          'significant_harvey': abs(v['t']) > 3.0 if np.isfinite(v['t']) else False}
                      for m, v in dm_results.items()},
        'mcs': {
            'best_model': best_model,
            'survived': mcs_survived,
            'eliminated': [m for m in mcs_models if m not in mcs_survived]
        },
        'var': {str(a): {m: v for m, v in var_results[a].items()} for a in ALPHA_LEVELS},
        'component_analysis': component_analysis,
        'parameters': param_report
    }


# ============================================================
# SECTION 5: RUN ALL ASSETS
# ============================================================
all_results = {}

for ticker in ASSETS:
    try:
        result = run_oos_for_asset(ticker, asset_data[ticker])
        all_results[ticker] = result
    except Exception as e:
        print(f"  ERROR for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        all_results[ticker] = {'error': str(e)}


# ============================================================
# SECTION 6: CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        print(f"\n{ticker}: ERROR - {all_results[ticker]['error']}")
        continue
    r = all_results[ticker]
    print(f"\n{ticker} (OOS: {r['oos_start']} to {r['oos_end']}, n={r['n_oos']})")
    print(f"  QLIKE (% vs GJR): ", end="")
    for m in ['MF-GARCH', 'MF-GJR', 'EWMA-Factor', 'EWMA']:
        pct = r['qlike_pct_vs_gjr'].get(m)
        print(f"  {m}={pct:+.3f}%" if pct is not None else f"  {m}=N/A", end="")
    print()
    print(f"  DM (t vs GJR):    ", end="")
    for m in ['MF-GARCH', 'MF-GJR', 'EWMA-Factor', 'EWMA']:
        dm = r['dm_vs_gjr'].get(m, {})
        t_val = dm.get('t')
        print(f"  {m}={t_val:+.2f}" if t_val is not None else f"  {m}=N/A", end="")
    print()
    print(f"  MCS survived: {r['mcs']['survived']}")

    # VaR 1% Trinity summary
    var1 = r['var'].get('0.01', {})
    trinity_summary = []
    for m in ['GJR', 'MF-GARCH', 'MF-GJR', 'EWMA-Factor', 'EWMA']:
        v = var1.get(m, {})
        trinity_summary.append(f"{m}={'PASS' if v.get('trinity') else 'FAIL'}")
    print(f"  VaR 1% Trinity: {', '.join(trinity_summary)}")

# ============================================================
# SECTION 7: CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

# Check if any MVF model significantly beats GJR across assets
any_significant = False
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    for m in ['MF-GARCH', 'MF-GJR', 'EWMA-Factor']:
        dm = all_results[ticker]['dm_vs_gjr'].get(m, {})
        if dm.get('significant_harvey', False) and dm.get('t', 0) < 0:
            any_significant = True
            print(f"  SIGNIFICANT: {m} beats GJR on {ticker} (DM t={dm['t']:.3f})")

if not any_significant:
    print("  No multiplicative model significantly beats GJR (Harvey |t|>3.0)")
    print("  → QLIKE ceiling confirmed again (6th+ independent test)")

# ============================================================
# SECTION 8: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Multiplicative Volatility Factor (MVF) Model',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'methodology': {
        'models': ['GJR-GARCH(1,1)', 'MF-GARCH', 'MF-GJR', 'EWMA-Factor', 'EWMA(0.94)'],
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_garch': 'g_t = (1-a-b) + a*u^2_{t-1} + b*g_{t-1}, u=r/sqrt(tau)',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'ewma_factor': 'tau=EWMA(0.99), g=EWMA(0.94) on standardized',
        'estimation': 'Rolling window (w=2000), refit every 63 days, MLE with multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman, MCS, VaR Trinity'
    },
    'data': {
        'source': 'yfinance',
        'assets': ASSETS,
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
    },
    'results': all_results,
    'conclusion': {
        'any_mvf_significant_vs_gjr': any_significant,
        'note': 'Multiplicative decomposition tests whether separating VIX-driven long-run from GARCH short-run improves forecasting'
    },
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Engle & Rangel (2008) RFS 21(3):1187-1222',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104'
    ]
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\nResults saved to: {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s")
print("=" * 70)
