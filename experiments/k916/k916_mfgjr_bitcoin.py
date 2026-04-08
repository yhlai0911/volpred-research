#!/usr/bin/env python3
"""
K916: MF-GJR on Bitcoin — Does Multiplicative VIX Structure Work for Crypto?
=============================================================================
[提出: Claude (research_program.md cross-asset extension), 執行: Claude]

Research Question:
  MF-GJR(VIX) is the best model for SPY (K889v2: QLIKE -6.6%, DM t=-2.57).
  BTC has 24/7 trading, no overnight gap, positive skewness, regime extremes.
  Does the multiplicative VIX structure still help for crypto volatility?

Key Hypotheses:
  H1: BTC gamma ≈ 0 or positive (no equity-like negative leverage)
  H2: VIX elasticity (theta_1) for BTC < SPY's 2.34
  H3: MF-GJR may be NULL for BTC (VIX not BTC's primary fear factor)
  H4: Post-ETF (2024+) theta_1 may increase (institutionalization)

Models (5):
  1. GARCH(1,1) — symmetric baseline
  2. GJR-GARCH(1,1) — with gamma
  3. MF-GARCH(VIX) — tau(VIX) * g_t, no asymmetry
  4. MF-GJR(VIX) — tau(VIX) * g_t, with gamma (SPY champion)
  5. EWMA(0.94) — simple benchmark

Data:
  - BTC-USD daily (yfinance), 2015-01-01 to 2026-04-01
  - ^VIX from yfinance, business days only
  - Also runs SPY for direct comparison of theta_1

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - DM test vs GARCH (Harvey |t| > 3.0)
  - Spearman rank correlation
  - MCS (Hansen-Lunde-Nason 2011)
  - VaR 1% + 5% Trinity (Normal + HistSim)
  - Component analysis (tau vs g variance ratios)
  - Pre/Post ETF subsample analysis

OOS: 2021-01-01 to latest (window=1000, refit=63)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Engle & Rangel (2008) RFS 21(3):1187-1222
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497

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
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm, chi2
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K916"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr
from volpred.stats.mcs import model_confidence_set

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k916_mfgjr_bitcoin_results.json')

# Data parameters
DATA_START = '2015-01-01'
DATA_END = '2026-04-01'
OOS_START = '2021-01-01'
ETF_DATE = '2024-01-11'  # BTC ETF approval date
WINDOW = 1000  # BTC history shorter than SPY
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
ASSETS = ['BTC-USD', 'SPY']  # SPY for theta_1 comparison

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR on Bitcoin — Cross-Asset Universality Test")
print("  Does VIX multiplicative structure work for crypto?")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

asset_data = {}
for ticker in ASSETS:
    print(f"  Loading {ticker}...")
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
    df = df.dropna(subset=['log_ret'])

    # Join VIX (only business days where VIX exists)
    df = df.join(vix_data, how='inner')  # inner join: only days with VIX
    df['VIX'] = df['VIX'].ffill()
    df = df.dropna()

    asset_data[ticker] = df
    print(f"    {ticker}: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")


# ============================================================
# SECTION 2: BTC vs SPY VOLATILITY CHARACTERISTICS
# ============================================================
print("\n[2] BTC vs SPY Volatility Characteristics...")
diagnostics = {}

for ticker in ASSETS:
    ret = asset_data[ticker]['log_ret'].values
    vix_vals = asset_data[ticker]['VIX'].values

    desc = {
        'mean': float(np.mean(ret)),
        'std': float(np.std(ret)),
        'annual_vol': float(np.std(ret) * np.sqrt(252)),
        'skewness': float(stats.skew(ret)),
        'kurtosis': float(stats.kurtosis(ret)),
        'min': float(np.min(ret)),
        'max': float(np.max(ret)),
        'n': int(len(ret)),
    }

    # Jarque-Bera
    jb_stat, jb_p = stats.jarque_bera(ret)
    desc['jb_stat'] = float(jb_stat)
    desc['jb_p'] = float(jb_p)

    # ADF test
    from statsmodels.tsa.stattools import adfuller
    adf_result = adfuller(ret, maxlag=20)
    desc['adf_stat'] = float(adf_result[0])
    desc['adf_p'] = float(adf_result[1])

    # ARCH LM test (10 lags)
    ret2 = ret ** 2
    n_lm = len(ret2) - 10
    X_lm = np.column_stack([np.ones(n_lm)] + [ret2[i:i+n_lm] for i in range(10)])
    y_lm = ret2[10:]
    b_lm = np.linalg.lstsq(X_lm, y_lm, rcond=None)[0]
    r2_lm = 1 - np.var(y_lm - X_lm @ b_lm) / np.var(y_lm)
    arch_lm = n_lm * r2_lm
    desc['arch_lm'] = float(arch_lm)
    desc['arch_lm_p'] = float(1 - chi2.cdf(arch_lm, 10))

    # BTC-VIX correlation
    corr_ret_vix = float(np.corrcoef(ret, np.log(vix_vals))[0, 1])
    desc['corr_ret_logvix'] = corr_ret_vix

    # Correlation of |ret| with VIX
    corr_absret_vix = float(np.corrcoef(np.abs(ret), np.log(vix_vals))[0, 1])
    desc['corr_absret_logvix'] = corr_absret_vix

    # Leverage effect: corr(r_t, sigma^2_{t+1}) approximated by corr(r_t, r^2_{t+1})
    leverage_corr = float(np.corrcoef(ret[:-1], ret[1:]**2)[0, 1])
    desc['leverage_corr'] = leverage_corr

    diagnostics[ticker] = desc

    print(f"  {ticker}:")
    print(f"    Mean={desc['mean']:.6f} Std={desc['std']:.4f} "
          f"AnnVol={desc['annual_vol']:.2%}")
    print(f"    Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.2f}")
    print(f"    JB={jb_stat:.0f}(p={jb_p:.1e}) ADF={desc['adf_stat']:.2f}(p={desc['adf_p']:.4f})")
    print(f"    ARCH_LM={arch_lm:.1f}(p={desc['arch_lm_p']:.1e})")
    print(f"    Corr(r,logVIX)={corr_ret_vix:.4f} Corr(|r|,logVIX)={corr_absret_vix:.4f}")
    print(f"    Leverage corr(r_t, r^2_{{t+1}})={leverage_corr:.4f}")

# Vol ratio
btc_vol = diagnostics['BTC-USD']['annual_vol']
spy_vol = diagnostics['SPY']['annual_vol']
vol_ratio = btc_vol / spy_vol
print(f"\n  Vol ratio (BTC/SPY): {vol_ratio:.2f}x")
print(f"  BTC leverage effect: {diagnostics['BTC-USD']['leverage_corr']:.4f} "
      f"(SPY: {diagnostics['SPY']['leverage_corr']:.4f})")
print(f"  BTC VIX sensitivity: corr(|r|,logVIX)={diagnostics['BTC-USD']['corr_absret_logvix']:.4f} "
      f"(SPY: {diagnostics['SPY']['corr_absret_logvix']:.4f})")


# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations (numba-accelerated)...")


@njit(cache=True)
def garch_loglik(params, returns):
    """GARCH(1,1) log-likelihood. Returns negative LL."""
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


@njit(cache=True)
def garch_forecast_oos(params, r_prev, h_prev):
    """One-step GARCH forecast."""
    omega, alpha, beta = params
    h_next = omega + alpha * r_prev**2 + beta * h_prev
    return max(h_next, 1e-10)


@njit(cache=True)
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


@njit(cache=True)
def gjr_garch_forecast_oos(params, r_prev, h_prev):
    """One-step GJR-GARCH forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev
    return max(h_next, 1e-10)


def fit_garch(returns):
    """Fit GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-5, 0.05, 0.90],
        [1e-5, 0.08, 0.85],
        [1e-4, 0.10, 0.80],  # Higher omega for BTC
        [5e-5, 0.06, 0.88],
    ]

    bounds = [(1e-8, 1e-2), (1e-4, 0.3), (0.5, 0.999)]

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

    return best_params, -best_ll


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-5, 0.05, 0.05, 0.90],
        [1e-5, 0.08, 0.10, 0.85],
        [1e-4, 0.10, 0.05, 0.80],  # Higher omega for BTC
        [5e-5, 0.06, 0.08, 0.88],
        [1e-4, 0.05, 0.00, 0.85],  # Near-zero gamma (BTC might not have leverage)
    ]

    # Allow negative gamma for reverse leverage effect
    bounds = [(1e-8, 1e-2), (1e-4, 0.3), (-0.1, 0.3), (0.5, 0.999)]

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

    Joint MLE estimation.
    """
    n = len(returns)
    assert len(log_vix) == n

    # Step 1: OLS initial theta
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

        # Long-run component
        log_tau = theta0 + theta1 * log_vix_lag
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        # Standardized returns
        u = returns / np.sqrt(tau)

        # Short-run component: g_t with unit unconditional mean
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

        # Total variance
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
            [-9.0, 1.0, 0.05, 0.00, 0.90],  # Near-zero gamma for BTC
            [-8.0, 1.5, 0.08, 0.02, 0.85],  # Higher theta_1 for BTC
        ]
        bounds = [(-20, 0), (-1, 4), (1e-4, 0.3), (-0.1, 0.3), (0.5, 0.999)]
    else:
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.85],
            [-8.0, 0.5, 0.05, 0.90],
            [-7.0, 0.8, 0.03, 0.93],
            [-9.0, 1.0, 0.05, 0.90],  # For BTC
            [-8.0, 1.5, 0.08, 0.85],  # Higher theta_1 for BTC
        ]
        bounds = [(-20, 0), (-1, 4), (1e-4, 0.3), (0.5, 0.999)]

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
    """Generate in-sample sigma^2, g, tau from MF model."""
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


def ewma_forecast(returns, lam=0.94):
    """EWMA(0.94) benchmark."""
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

    # Storage
    models = ['GARCH', 'GJR', 'MF-GARCH', 'MF-GJR', 'EWMA']
    forecasts = {m: np.full(n_oos, np.nan) for m in models}
    oos_returns = ret[oos_start_idx:]
    oos_r2 = r2[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    # Track MF components
    tau_mfgarch = np.full(n_oos, np.nan)
    g_mfgarch = np.full(n_oos, np.nan)
    tau_mfgjr = np.full(n_oos, np.nan)
    g_mfgjr = np.full(n_oos, np.nan)

    # State variables
    last_garch_params = None
    last_garch_h = None
    last_gjr_params = None
    last_gjr_h = None
    last_mfgarch_params = None
    last_mfgjr_params = None
    last_mfgarch_g = None
    last_mfgjr_g = None
    tau_prev_mfgarch = None
    tau_prev_mfgjr = None
    last_ewma_h = None

    # Track all fitted parameters for analysis
    all_fitted_params = {m: [] for m in models}

    n_refits = 0
    for t in range(n_oos):
        idx = oos_start_idx + t
        need_refit = (t == 0) or (t % REFIT_EVERY == 0)

        train_start = max(0, idx - WINDOW)
        train_ret = ret[train_start:idx]
        train_vix = log_vix_raw[train_start:idx]

        if need_refit:
            n_refits += 1

            # Fit GARCH(1,1)
            garch_params, garch_ll = fit_garch(train_ret)
            if garch_params is not None:
                last_garch_params = garch_params
                h_arr = np.empty(len(train_ret))
                h_arr[0] = np.var(train_ret)
                for tt in range(1, len(train_ret)):
                    omega, alpha, beta = garch_params
                    h_arr[tt] = omega + alpha * train_ret[tt-1]**2 + beta * h_arr[tt-1]
                    h_arr[tt] = max(h_arr[tt], 1e-10)
                last_garch_h = garch_forecast_oos(
                    garch_params, train_ret[-1], h_arr[-1])
                all_fitted_params['GARCH'].append({
                    'date': str(dates[idx].date()),
                    'omega': float(garch_params[0]),
                    'alpha': float(garch_params[1]),
                    'beta': float(garch_params[2]),
                    'persistence': float(garch_params[1] + garch_params[2])
                })

            # Fit GJR-GARCH(1,1)
            gjr_params, gjr_ll = fit_gjr_garch(train_ret)
            if gjr_params is not None:
                last_gjr_params = gjr_params
                h_arr = np.empty(len(train_ret))
                h_arr[0] = np.var(train_ret)
                for tt in range(1, len(train_ret)):
                    omega, alpha, gamma_g, beta = gjr_params
                    asym = gamma_g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                    h_arr[tt] = omega + alpha * train_ret[tt-1]**2 + asym + beta * h_arr[tt-1]
                    h_arr[tt] = max(h_arr[tt], 1e-10)
                last_gjr_h = gjr_garch_forecast_oos(
                    gjr_params, train_ret[-1], h_arr[-1])
                all_fitted_params['GJR'].append({
                    'date': str(dates[idx].date()),
                    'omega': float(gjr_params[0]),
                    'alpha': float(gjr_params[1]),
                    'gamma': float(gjr_params[2]),
                    'beta': float(gjr_params[3]),
                    'persistence': float(gjr_params[1] + gjr_params[2]/2 + gjr_params[3])
                })

            # Fit MF-GARCH
            mfg_params, mfg_ll = fit_mf_garch(train_ret, train_vix, model_type='garch')
            if mfg_params is not None:
                last_mfgarch_params = mfg_params
                _, g_arr, tau_arr = forecast_mf_garch(mfg_params, train_ret, train_vix, 'garch')
                theta0, theta1, alpha_mf, beta_mf = mfg_params
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                omega_g = 1.0 - alpha_mf - beta_mf
                last_mfgarch_g = omega_g + alpha_mf * u_last**2 + beta_mf * g_arr[-1]
                last_mfgarch_g = max(last_mfgarch_g, 1e-10)
                all_fitted_params['MF-GARCH'].append({
                    'date': str(dates[idx].date()),
                    'theta_0': float(mfg_params[0]),
                    'theta_1': float(mfg_params[1]),
                    'alpha': float(mfg_params[2]),
                    'beta': float(mfg_params[3]),
                    'persistence_g': float(mfg_params[2] + mfg_params[3])
                })

            # Fit MF-GJR
            mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_vix, model_type='gjr')
            if mfgjr_params is not None:
                last_mfgjr_params = mfgjr_params
                _, g_arr, tau_arr = forecast_mf_garch(mfgjr_params, train_ret, train_vix, 'gjr')
                theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
                last_mfgjr_g = omega_g + alpha_mf * u_last**2 + asym + beta_mf * g_arr[-1]
                last_mfgjr_g = max(last_mfgjr_g, 1e-10)
                all_fitted_params['MF-GJR'].append({
                    'date': str(dates[idx].date()),
                    'theta_0': float(mfgjr_params[0]),
                    'theta_1': float(mfgjr_params[1]),
                    'alpha': float(mfgjr_params[2]),
                    'gamma': float(mfgjr_params[3]),
                    'beta': float(mfgjr_params[4]),
                    'persistence_g': float(mfgjr_params[2] + mfgjr_params[3]/2 + mfgjr_params[4])
                })

        # === Generate one-step-ahead forecasts ===

        # GARCH(1,1)
        if last_garch_params is not None and last_garch_h is not None:
            if not need_refit and t > 0:
                last_garch_h = garch_forecast_oos(
                    last_garch_params, ret[idx-1], last_garch_h)
            forecasts['GARCH'][t] = last_garch_h

        # GJR-GARCH
        if last_gjr_params is not None and last_gjr_h is not None:
            if not need_refit and t > 0:
                last_gjr_h = gjr_garch_forecast_oos(
                    last_gjr_params, ret[idx-1], last_gjr_h)
            forecasts['GJR'][t] = last_gjr_h

        # MF-GARCH
        if last_mfgarch_params is not None:
            theta0, theta1, alpha_mf, beta_mf = last_mfgarch_params
            log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
            tau_t = np.exp(log_tau_t)
            tau_t = max(tau_t, 1e-16)

            if need_refit:
                g_t = last_mfgarch_g
            else:
                u_prev = ret[idx-1] / np.sqrt(tau_prev_mfgarch)
                omega_g = 1.0 - alpha_mf - beta_mf
                g_t = omega_g + alpha_mf * u_prev**2 + beta_mf * last_mfgarch_g
                g_t = max(g_t, 1e-10)

            tau_prev_mfgarch = tau_t
            last_mfgarch_g = g_t
            forecasts['MF-GARCH'][t] = tau_t * g_t
            tau_mfgarch[t] = tau_t
            g_mfgarch[t] = g_t

        # MF-GJR
        if last_mfgjr_params is not None:
            theta0, theta1, alpha_mf, gamma_mf, beta_mf = last_mfgjr_params
            log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
            tau_t = np.exp(log_tau_t)
            tau_t = max(tau_t, 1e-16)

            if need_refit:
                g_t = last_mfgjr_g
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

        # EWMA
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

    # 5a: QLIKE on r^2
    qlike_results = {}
    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 100:
            qlike_results[m] = qlike(oos_r2[valid], f[valid])
        else:
            qlike_results[m] = np.nan

    # Normalize to GARCH baseline
    garch_qlike = qlike_results['GARCH']
    qlike_pct = {}
    for m in models:
        if np.isfinite(qlike_results[m]) and np.isfinite(garch_qlike) and garch_qlike > 0:
            qlike_pct[m] = ((qlike_results[m] - garch_qlike) / garch_qlike) * 100
        else:
            qlike_pct[m] = np.nan

    print(f"\n    QLIKE on r^2 (Patton 2011):")
    for m in models:
        pct = qlike_pct.get(m, np.nan)
        print(f"      {m:15s}: {qlike_results[m]:.6f} ({pct:+.3f}% vs GARCH)")

    # 5b: Spearman
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

    # 5c: DM tests vs GARCH baseline
    garch_loss = qlike_pointwise(oos_r2, forecasts['GARCH'])
    dm_results = {}
    for m in models:
        if m == 'GARCH':
            dm_results[m] = {'t': 0.0, 'p': 1.0}
            continue
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0) & np.isfinite(garch_loss)
        if valid.sum() > 100:
            m_loss = qlike_pointwise(oos_r2[valid], f[valid])
            t_stat, p_val = dm_test(m_loss, garch_loss[valid])
            dm_results[m] = {'t': float(t_stat), 'p': float(p_val)}
        else:
            dm_results[m] = {'t': np.nan, 'p': np.nan}

    print(f"\n    DM tests vs GARCH (negative t = model is better):")
    for m in models:
        r = dm_results[m]
        sig = "***" if abs(r['t']) > 3.0 else ("*" if abs(r['t']) > 1.96 else "NS")
        print(f"      {m:15s}: t={r['t']:+.3f} (p={r['p']:.4f}) {sig}")

    # 5d: MCS
    all_valid = np.ones(n_oos, dtype=bool)
    for m in models:
        f = forecasts[m]
        all_valid &= np.isfinite(f) & (f > 0)

    if all_valid.sum() > 100:
        aligned_losses = {m: qlike_pointwise(oos_r2[all_valid], forecasts[m][all_valid])
                          for m in models}
        mcs_result = model_confidence_set(aligned_losses, alpha=0.10, n_boot=5000, seed=42)
        mcs_survived = mcs_result['mcs_models']
        mcs_eliminated = [m for m, _ in mcs_result['eliminated']]
        mcs_p_values = mcs_result['p_values']
    else:
        mcs_survived = models
        mcs_eliminated = []
        mcs_p_values = {m: 1.0 for m in models}

    best_model = min(
        [m for m in models if np.isfinite(qlike_results.get(m, np.nan))],
        key=lambda m: qlike_results[m]
    )

    print(f"\n    MCS (Hansen-Lunde-Nason 2011, alpha=0.10, 5000 bootstrap):")
    print(f"      Best model: {best_model}")
    print(f"      Survived: {mcs_survived}")
    print(f"      Eliminated: {mcs_eliminated}")

    # 5e: VaR Trinity (Normal + HistSim)
    var_results = {}
    for alpha in ALPHA_LEVELS:
        var_results[alpha] = {}

        for m in models:
            f = forecasts[m]
            valid = np.isfinite(f) & (f > 0)
            if valid.sum() < 100:
                var_results[alpha][m] = {
                    'normal': {'violations': 'N/A', 'rate': 'N/A', 'kupiec_p': 'N/A',
                               'cc_p': 'N/A', 'basel': 'N/A', 'trinity': False},
                    'histsim': {'violations': 'N/A', 'rate': 'N/A', 'kupiec_p': 'N/A',
                                'cc_p': 'N/A', 'basel': 'N/A', 'trinity': False}
                }
                continue

            f_valid = f[valid]
            actual_ret = oos_returns[valid]
            n_total = int(len(actual_ret))

            # --- Normal VaR ---
            z = norm.ppf(alpha)
            sigma_norm = np.sqrt(f_valid)
            var_norm = z * sigma_norm
            violations_norm = actual_ret < var_norm
            var_results[alpha][m] = {}
            var_results[alpha][m]['normal'] = _compute_var_trinity(
                violations_norm, n_total, alpha)

            # --- HistSim VaR (K908 best for fat tails) ---
            # Use standardized residuals from training to compute VaR quantile
            # For simplicity, use rolling 252-day empirical quantile of standardized residuals
            std_resid = actual_ret / np.sqrt(f_valid)
            histsim_var = np.full(n_total, np.nan)
            window_hs = min(252, n_total // 2)
            for i in range(window_hs, n_total):
                q = np.percentile(std_resid[max(0, i-window_hs):i], alpha * 100)
                histsim_var[i] = q * np.sqrt(f_valid[i])
            valid_hs = ~np.isnan(histsim_var)
            if valid_hs.sum() > 50:
                violations_hs = actual_ret[valid_hs] < histsim_var[valid_hs]
                var_results[alpha][m]['histsim'] = _compute_var_trinity(
                    violations_hs, int(valid_hs.sum()), alpha)
            else:
                var_results[alpha][m]['histsim'] = {
                    'violations': 'N/A', 'rate': 'N/A', 'kupiec_p': 'N/A',
                    'cc_p': 'N/A', 'basel': 'N/A', 'trinity': False}

    for alpha in ALPHA_LEVELS:
        print(f"\n    VaR {int(alpha*100)}% Trinity:")
        for m in models:
            rn = var_results[alpha][m]['normal']
            rh = var_results[alpha][m]['histsim']
            if isinstance(rn.get('violations'), (int, float)):
                print(f"      {m:15s}: Normal {rn['violations']}/{rn.get('total','?')} "
                      f"({rn['rate']:.3f}) Basel={rn['basel']} "
                      f"Trinity={'PASS' if rn['trinity'] else 'FAIL'}")
                if isinstance(rh.get('violations'), (int, float)):
                    print(f"      {' ':15s}  HistSim {rh['violations']}/{rh.get('total','?')} "
                          f"({rh['rate']:.3f}) Basel={rh['basel']} "
                          f"Trinity={'PASS' if rh['trinity'] else 'FAIL'}")

    # 5f: Component analysis
    component_analysis = {}
    for m_name, tau_arr, g_arr in [('MF-GARCH', tau_mfgarch, g_mfgarch),
                                    ('MF-GJR', tau_mfgjr, g_mfgjr)]:
        valid = np.isfinite(tau_arr) & np.isfinite(g_arr)
        if valid.sum() > 50:
            total_var = np.var(np.log(tau_arr[valid] * g_arr[valid]))
            tau_var = np.var(np.log(tau_arr[valid]))
            g_var = np.var(np.log(g_arr[valid]))

            g_clean = g_arr[valid]
            if len(g_clean) > 10:
                g_ac1 = np.corrcoef(g_clean[:-1], g_clean[1:])[0, 1]
                g_ac5 = np.corrcoef(g_clean[:-5], g_clean[5:])[0, 1] if len(g_clean) > 5 else np.nan
            else:
                g_ac1 = g_ac5 = np.nan

            component_analysis[m_name] = {
                'tau_var_pct': round(tau_var / total_var * 100, 1) if total_var > 0 else None,
                'g_var_pct': round(g_var / total_var * 100, 1) if total_var > 0 else None,
                'g_autocorr_1': round(float(g_ac1), 4),
                'g_autocorr_5': round(float(g_ac5), 4),
                'tau_mean': round(float(np.mean(tau_arr[valid])), 8),
                'g_mean': round(float(np.mean(g_arr[valid])), 4),
            }

    print(f"\n    Component analysis:")
    for m_name, ca in component_analysis.items():
        print(f"      {m_name}: tau_var={ca['tau_var_pct']}% g_var={ca['g_var_pct']}% "
              f"g_AC(1)={ca['g_autocorr_1']:.3f}")

    # 5g: VIX elasticity analysis (theta_1 over time)
    theta1_series = {'MF-GARCH': [], 'MF-GJR': []}
    for m_name in ['MF-GARCH', 'MF-GJR']:
        for p in all_fitted_params[m_name]:
            theta1_series[m_name].append({
                'date': p['date'],
                'theta_1': p['theta_1']
            })

    # Pre vs post ETF theta_1
    theta1_pre_post = {}
    for m_name in ['MF-GARCH', 'MF-GJR']:
        pre = [p['theta_1'] for p in theta1_series[m_name] if p['date'] < ETF_DATE]
        post = [p['theta_1'] for p in theta1_series[m_name] if p['date'] >= ETF_DATE]
        theta1_pre_post[m_name] = {
            'pre_etf_mean': round(float(np.mean(pre)), 4) if pre else None,
            'post_etf_mean': round(float(np.mean(post)), 4) if post else None,
            'pre_etf_n': len(pre),
            'post_etf_n': len(post),
        }
        if pre and post:
            t_stat, p_val = stats.ttest_ind(pre, post)
            theta1_pre_post[m_name]['ttest_t'] = round(float(t_stat), 3)
            theta1_pre_post[m_name]['ttest_p'] = round(float(p_val), 4)
            print(f"\n    {m_name} theta_1: pre-ETF={theta1_pre_post[m_name]['pre_etf_mean']:.4f} "
                  f"post-ETF={theta1_pre_post[m_name]['post_etf_mean']:.4f} "
                  f"(t={theta1_pre_post[m_name]['ttest_t']:.3f})")

    # 5h: Pre vs Post ETF QLIKE subsample analysis
    etf_subsample = {}
    etf_mask = oos_dates >= ETF_DATE
    pre_etf_mask = ~etf_mask
    for period_name, mask in [('pre_etf', pre_etf_mask), ('post_etf', etf_mask)]:
        if mask.sum() > 100:
            sub_qlike = {}
            for m in models:
                f = forecasts[m][mask]
                r = oos_r2[mask]
                valid = np.isfinite(f) & (f > 0)
                if valid.sum() > 50:
                    sub_qlike[m] = round(qlike(r[valid], f[valid]), 6)
                else:
                    sub_qlike[m] = None
            etf_subsample[period_name] = {
                'n': int(mask.sum()),
                'qlike': sub_qlike
            }

    if etf_subsample:
        print(f"\n    Pre/Post ETF subsample QLIKE:")
        for period, data in etf_subsample.items():
            print(f"      {period} (n={data['n']}):")
            for m in models:
                v = data['qlike'].get(m)
                if v is not None:
                    print(f"        {m:15s}: {v:.6f}")

    # Collect last parameters
    param_report = {}
    if last_garch_params is not None:
        param_report['GARCH'] = {
            'omega': float(last_garch_params[0]),
            'alpha': float(last_garch_params[1]),
            'beta': float(last_garch_params[2]),
            'persistence': float(last_garch_params[1] + last_garch_params[2])
        }
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
        'qlike_pct_vs_garch': {m: round(v, 3) if np.isfinite(v) else None for m, v in qlike_pct.items()},
        'spearman': {m: {'rho': round(v['rho'], 4) if np.isfinite(v['rho']) else None,
                         'p': round(v['p'], 6) if np.isfinite(v['p']) else None}
                     for m, v in spearman_results.items()},
        'dm_vs_garch': {m: {'t': round(v['t'], 3) if np.isfinite(v['t']) else None,
                            'p': round(v['p'], 4) if np.isfinite(v['p']) else None,
                            'significant_harvey': abs(v['t']) > 3.0 if np.isfinite(v['t']) else False}
                        for m, v in dm_results.items()},
        'mcs': {
            'best_model': best_model,
            'survived': mcs_survived,
            'eliminated': mcs_eliminated,
            'p_values': {m: round(v, 4) for m, v in mcs_p_values.items()},
        },
        'var': {str(a): {m: v for m, v in var_results[a].items()} for a in ALPHA_LEVELS},
        'component_analysis': component_analysis,
        'parameters': param_report,
        'theta1_pre_post_etf': theta1_pre_post,
        'etf_subsample_qlike': etf_subsample,
    }


def _compute_var_trinity(violations, n_total, alpha):
    """Compute VaR Trinity test from violation array."""
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n_total

    # Kupiec (1995)
    p_hat = viol_rate
    if 0 < p_hat < 1:
        kupiec_lr = 2 * (n_viol * np.log(p_hat / alpha) +
                         (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
        kupiec_p = 1 - chi2.cdf(kupiec_lr, 1) if kupiec_lr > 0 else 1.0
    else:
        kupiec_p = 0.0 if p_hat == 0 and alpha > 0 else 1.0

    # Christoffersen (1998)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n_total):
        if not violations[i-1]:
            if not violations[i]:
                n00 += 1
            else:
                n01 += 1
        else:
            if not violations[i]:
                n10 += 1
            else:
                n11 += 1

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
        expected = int(n_total * 0.05)
        if n_viol <= expected + 4:
            basel = "GREEN"
        elif n_viol <= expected + 9:
            basel = "YELLOW"
        else:
            basel = "RED"

    trinity_pass = (kupiec_p > 0.05) and (cc_p > 0.05) and (basel == "GREEN")

    return {
        'violations': n_viol,
        'total': n_total,
        'rate': round(viol_rate, 4),
        'expected_rate': alpha,
        'kupiec_p': round(kupiec_p, 4),
        'cc_p': round(cc_p, 4),
        'basel': basel,
        'trinity': trinity_pass
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
# SECTION 6: CROSS-ASSET COMPARISON
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET COMPARISON: BTC-USD vs SPY")
print("=" * 70)

# Compare theta_1 (VIX elasticity)
print("\nVIX Elasticity (theta_1) Comparison:")
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    for m in ['MF-GARCH', 'MF-GJR']:
        if m in r['parameters']:
            print(f"  {ticker} {m}: theta_1 = {r['parameters'][m].get('theta_1', 'N/A'):.4f}")

# Compare gamma (leverage effect)
print("\nLeverage Effect (gamma) Comparison:")
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    if 'GJR' in r['parameters']:
        print(f"  {ticker} GJR: gamma = {r['parameters']['GJR'].get('gamma', 'N/A'):.4f}")
    if 'MF-GJR' in r['parameters']:
        print(f"  {ticker} MF-GJR: gamma = {r['parameters']['MF-GJR'].get('gamma', 'N/A'):.4f}")

# Compare QLIKE improvements
print("\nQLIKE Improvements (% vs GARCH):")
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    print(f"  {ticker} (OOS: {r['oos_start']} to {r['oos_end']}, n={r['n_oos']})")
    for m in ['GJR', 'MF-GARCH', 'MF-GJR', 'EWMA']:
        pct = r['qlike_pct_vs_garch'].get(m)
        dm = r['dm_vs_garch'].get(m, {})
        if pct is not None:
            sig = " Harvey***" if dm.get('significant_harvey', False) else ""
            print(f"    {m:15s}: {pct:+.3f}% (DM t={dm.get('t', 'N/A')}{sig})")


# ============================================================
# SECTION 7: CHARTS
# ============================================================
print("\n[7] Generating charts...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Chart 1: BTC vs SPY vol characteristics comparison
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

for i, ticker in enumerate(ASSETS):
    ret = asset_data[ticker]['log_ret'].values

    # Return distribution
    ax = axes[0][i]
    ax.hist(ret, bins=100, density=True, alpha=0.7, color='steelblue' if ticker == 'SPY' else 'orange')
    x_range = np.linspace(ret.min(), ret.max(), 200)
    ax.plot(x_range, norm.pdf(x_range, ret.mean(), ret.std()), 'r-', lw=2, label='Normal')
    ax.set_title(f'{ticker} Return Distribution')
    ax.set_xlabel('Log Return')
    ax.set_ylabel('Density')
    ax.legend()

    # QQ plot
    ax = axes[1][i]
    stats.probplot(ret, plot=ax)
    ax.set_title(f'{ticker} QQ Plot')

plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k916_btc_vol_characteristics.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")

# Chart 2: QLIKE comparison across assets
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
models_for_chart = ['GARCH', 'GJR', 'MF-GARCH', 'MF-GJR', 'EWMA']
colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336', '#9C27B0']

for i, ticker in enumerate(ASSETS):
    if 'error' in all_results[ticker]:
        continue
    ax = axes[i]
    r = all_results[ticker]
    qlike_vals = [r['qlike_pct_vs_garch'].get(m, 0) or 0 for m in models_for_chart]
    bars = ax.bar(range(len(models_for_chart)), qlike_vals, color=colors)
    ax.set_xticks(range(len(models_for_chart)))
    ax.set_xticklabels(models_for_chart, rotation=45, ha='right')
    ax.set_ylabel('QLIKE % change vs GARCH')
    ax.set_title(f'{ticker}: QLIKE Improvement')
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

    # Add value labels
    for bar, val in zip(bars, qlike_vals):
        if val != 0:
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height(),
                    f'{val:+.1f}%', ha='center', va='bottom' if val > 0 else 'top',
                    fontsize=9)

plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k916_model_comparison.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")

# Chart 3: VIX elasticity over time (BTC only)
if 'BTC-USD' in all_results and 'error' not in all_results['BTC-USD']:
    fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    for m_name, color in [('MF-GARCH', '#FF9800'), ('MF-GJR', '#F44336')]:
        btc_r = all_results['BTC-USD']
        pp = btc_r.get('theta1_pre_post_etf', {}).get(m_name, {})
        # Get raw theta_1 from fitted params in all_fitted_params — we don't have these in results
        # So we'll need to track them separately
        pass  # Will be populated from the run

    # Use etf_subsample to show structural break
    if all_results['BTC-USD'].get('etf_subsample_qlike'):
        sub = all_results['BTC-USD']['etf_subsample_qlike']
        period_names = list(sub.keys())
        for m_name in ['MF-GARCH', 'MF-GJR']:
            vals = [sub[p]['qlike'].get(m_name) for p in period_names if sub[p]['qlike'].get(m_name)]
            if vals:
                ax.bar([f"{p}\n{m_name}" for p in period_names], vals,
                       alpha=0.7, label=m_name)

    ax.set_ylabel('QLIKE')
    ax.set_title('BTC-USD: Pre vs Post ETF QLIKE (MF models)')
    ax.legend()
    chart3_path = os.path.join(SCRIPT_DIR, 'k916_btc_etf_structural_break.png')
    plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {chart3_path}")


# ============================================================
# SECTION 8: KEY FINDINGS
# ============================================================
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

findings = []

# BTC gamma analysis
if 'BTC-USD' in all_results and 'error' not in all_results['BTC-USD']:
    btc = all_results['BTC-USD']
    spy = all_results.get('SPY', {})

    # 1. Gamma
    btc_gamma_gjr = btc['parameters'].get('GJR', {}).get('gamma')
    spy_gamma_gjr = spy.get('parameters', {}).get('GJR', {}).get('gamma')
    if btc_gamma_gjr is not None:
        if btc_gamma_gjr < 0.01:
            findings.append(f"BTC GJR gamma={btc_gamma_gjr:.4f} (near zero) — no equity-like negative leverage effect")
        elif btc_gamma_gjr < 0:
            findings.append(f"BTC GJR gamma={btc_gamma_gjr:.4f} (negative) — reverse leverage: BTC vol increases on up moves")
        else:
            findings.append(f"BTC GJR gamma={btc_gamma_gjr:.4f} (positive, SPY={spy_gamma_gjr:.4f})")

    # 2. VIX elasticity
    btc_theta1 = btc['parameters'].get('MF-GJR', {}).get('theta_1')
    spy_theta1 = spy.get('parameters', {}).get('MF-GJR', {}).get('theta_1')
    if btc_theta1 is not None and spy_theta1 is not None:
        findings.append(f"VIX elasticity: BTC theta_1={btc_theta1:.4f} vs SPY theta_1={spy_theta1:.4f} "
                       f"(ratio={btc_theta1/spy_theta1:.2f}x)" if spy_theta1 != 0 else
                       f"VIX elasticity: BTC theta_1={btc_theta1:.4f}, SPY theta_1={spy_theta1:.4f}")

    # 3. MF-GJR effectiveness
    btc_mfgjr_pct = btc['qlike_pct_vs_garch'].get('MF-GJR')
    spy_mfgjr_pct = spy.get('qlike_pct_vs_garch', {}).get('MF-GJR')
    btc_dm = btc['dm_vs_garch'].get('MF-GJR', {})
    if btc_mfgjr_pct is not None:
        findings.append(f"MF-GJR QLIKE: BTC {btc_mfgjr_pct:+.3f}% vs SPY {spy_mfgjr_pct:+.3f}% "
                       f"(BTC DM t={btc_dm.get('t', 'N/A')}, Harvey={'PASS' if btc_dm.get('significant_harvey') else 'FAIL'})")

    # 4. Pre/Post ETF structural break
    pp = btc.get('theta1_pre_post_etf', {}).get('MF-GJR', {})
    if pp.get('pre_etf_mean') is not None and pp.get('post_etf_mean') is not None:
        findings.append(f"ETF structural break: theta_1 pre={pp['pre_etf_mean']:.4f} "
                       f"post={pp['post_etf_mean']:.4f} (t={pp.get('ttest_t', 'N/A')})")

for i, f in enumerate(findings):
    print(f"  {i+1}. {f}")


# ============================================================
# SECTION 9: SAVE RESULTS
# ============================================================
runtime = time.time() - START_TIME
print(f"\n[9] Saving results... (runtime: {runtime:.1f}s)")

# Build key_findings string
kf_parts = []
for i, f in enumerate(findings):
    kf_parts.append(f"{i+1}. {f}")
key_findings_str = "\n".join(kf_parts)

output = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR on Bitcoin: Cross-Asset Universality Test',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(runtime, 1),
    'methodology': {
        'models': ['GARCH(1,1)', 'GJR-GARCH(1,1)', 'MF-GARCH(VIX)', 'MF-GJR(VIX)', 'EWMA(0.94)'],
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_garch': 'g_t = (1-a-b) + a*u^2_{t-1} + b*g_{t-1}, u=r/sqrt(tau)',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'estimation': f'Rolling window (w={WINDOW}), refit every {REFIT_EVERY} days, MLE multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman, MCS (HLN 2011), VaR Trinity (Normal + HistSim)',
        'etf_date': ETF_DATE,
    },
    'data': {
        'source': 'yfinance',
        'assets': ASSETS,
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'btc_note': 'Only business days where VIX available (weekends dropped)',
    },
    'diagnostics': diagnostics,
    'vol_ratio_btc_spy': round(vol_ratio, 2),
    'results': all_results,
    'key_findings': key_findings_str,
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Engle & Rangel (2008) RFS 21(3):1187-1222',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104',
        'Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"  Results saved to: {RESULTS_PATH}")
print(f"\nTotal runtime: {runtime:.1f}s")
print("=" * 70)
print("K916 COMPLETE")
print("=" * 70)
