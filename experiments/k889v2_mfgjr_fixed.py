#!/usr/bin/env python3
"""
K889v2: Multiplicative Volatility Factor (MVF) Model — Bug-Fixed Version
=========================================================================
[提出: Codex adversarial review, 執行: Claude]

This is a VERIFICATION experiment. K889 found MF-GJR beats GJR for SPY
(DM t=-3.30, Harvey PASS). Codex adversarial review found 3 bugs:

Bug Fixes Applied:
  1. [HIGH] Fake MCS → replaced with proper Hansen-Lunde-Nason (2011) MCS
     from volpred.stats.mcs.model_confidence_set (stationary bootstrap,
     T_R elimination, correct centering).
  2. [HIGH] 0050.TW double-lag → removed pre-shift of VIX in load_asset_data.
     The model already lags VIX internally (log_vix_raw[idx-1] in OOS loop,
     np.roll in fit_mf_garch). Pre-shifting caused VIX_{t-2} instead of VIX_{t-1}.
  3. [MEDIUM] Stale forecast on refit dates → after refitting, advance latent
     state one step with the most recent return before storing forecast.
     Previously, on refit dates with t==0, the code used the last in-sample h/g
     directly without updating with ret[idx-1]. EWMA did this correctly;
     now GJR and MF models do too.

Key Question: Does K889's conclusion (MF-GJR beats GJR, DM t=-3.30 for SPY)
survive these bug fixes?

Data:
  - Assets: SPY, QQQ, 0050.TW
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - VIX from yfinance (^VIX)
  - 0050.TW: clean_tw50_data (mandatory)

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - DM tests with Harvey (2016) |t| > 3.0
  - Spearman rank correlation
  - MCS (proper Hansen-Lunde-Nason 2011)
  - VaR 1% + 5% Trinity test (Kupiec + Christoffersen + Basel)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Engle & Rangel (2008) RFS 21(3):1187-1222
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497

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
EXPERIMENT_ID = "K889v2"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr
from volpred.stats.mcs import model_confidence_set  # BUG FIX #1: proper MCS

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k889v2_mfgjr_fixed_results.json')

# Data parameters (same as K889 for comparability)
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
ASSETS = ['SPY', 'QQQ', '0050.TW']

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR Bug-Fixed Verification")
print("  Fixes: proper MCS, 0050.TW lag, stale forecast on refit")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf


def load_asset_data(ticker, vix_data):
    """Load asset data with VIX alignment.

    BUG FIX #2: For 0050.TW, do NOT pre-shift VIX here.
    The model already handles the lag internally:
      - fit_mf_garch: log_vix_lag = np.roll(log_vix, 1)
      - OOS loop: log_vix_raw[idx-1]
    Pre-shifting caused double-lag (VIX_{t-2} instead of VIX_{t-1}).
    """
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

    # BUG FIX #2: Always join VIX directly (no pre-shift for Taiwan)
    # The cross-market lag is handled in the model's VIX lag mechanism
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
    """Generate in-sample sigma^2 from MF-GARCH/MF-GJR model.

    Returns arrays of sigma^2, g, and tau.
    """
    n = len(returns)

    if model_type == 'gjr':
        theta0, theta1, alpha, gamma, beta = params
    else:
        theta0, theta1, alpha, beta = params
        gamma = 0.0

    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    # Reconstruct in-sample g_t
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
    # Track tau from previous step for MF models
    tau_prev_mfgarch = None
    tau_prev_mfgjr = None

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
                # Reconstruct last h from in-sample
                h_arr = np.empty(len(train_ret))
                h_arr[0] = np.var(train_ret)
                for tt in range(1, len(train_ret)):
                    omega, alpha, gamma_g, beta = gjr_params
                    asym = gamma_g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                    h_arr[tt] = omega + alpha * train_ret[tt-1]**2 + asym + beta * h_arr[tt-1]
                    h_arr[tt] = max(h_arr[tt], 1e-10)
                # BUG FIX #3: Advance h one step with the last training return
                # h_arr[-1] is h for the last training day (based on info up to day before last)
                # We need h for the first OOS day, which requires ret[idx-1]
                last_gjr_h = gjr_garch_forecast_oos(
                    gjr_params, train_ret[-1], h_arr[-1])

            # Fit MF-GARCH
            mfg_params, mfg_ll = fit_mf_garch(train_ret, train_vix, model_type='garch')
            if mfg_params is not None:
                last_mfgarch_params = mfg_params
                _, g_arr, tau_arr = forecast_mf_garch(mfg_params, train_ret, train_vix, 'garch')
                # BUG FIX #3: Advance g one step with the last training return
                # g_arr[-1] is g for the last training day
                # Advance to get g for the first OOS day after refit
                theta0, theta1, alpha_mf, beta_mf = mfg_params
                # tau for the last training day (using second-to-last VIX via internal lag)
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                omega_g = 1.0 - alpha_mf - beta_mf
                last_mfgarch_g = omega_g + alpha_mf * u_last**2 + beta_mf * g_arr[-1]
                last_mfgarch_g = max(last_mfgarch_g, 1e-10)

            # Fit MF-GJR
            mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_vix, model_type='gjr')
            if mfgjr_params is not None:
                last_mfgjr_params = mfgjr_params
                _, g_arr, tau_arr = forecast_mf_garch(mfgjr_params, train_ret, train_vix, 'gjr')
                # BUG FIX #3: Advance g one step with the last training return
                theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
                last_mfgjr_g = omega_g + alpha_mf * u_last**2 + asym + beta_mf * g_arr[-1]
                last_mfgjr_g = max(last_mfgjr_g, 1e-10)

        # === Generate one-step-ahead forecasts ===

        # GJR-GARCH: recursive h[t] = f(h[t-1], r^2[t-1])
        if last_gjr_params is not None and last_gjr_h is not None:
            # BUG FIX #3: On refit dates, last_gjr_h was already advanced
            # On non-refit dates with t>0, update with yesterday's return
            if not need_refit and t > 0:
                last_gjr_h = gjr_garch_forecast_oos(
                    last_gjr_params, ret[idx-1], last_gjr_h)
            # On refit dates (including t==0), last_gjr_h was already advanced
            forecasts['GJR'][t] = last_gjr_h

        # MF-GARCH: tau_{t} from VIX_{t-1}, g_{t} = recursive on standardized
        if last_mfgarch_params is not None:
            theta0, theta1, alpha_mf, beta_mf = last_mfgarch_params
            # Long-run from yesterday's VIX
            log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
            tau_t = np.exp(log_tau_t)
            tau_t = max(tau_t, 1e-16)

            if need_refit:
                # BUG FIX #3: g was already advanced after refit
                g_t = last_mfgarch_g
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

            if need_refit:
                # BUG FIX #3: g was already advanced after refit
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

        # EWMA-Factor: no fitting needed, just recursive
        if t == 0:
            # Initialize tau and g from training data
            ewma_sigma2, ewma_g_init, ewma_tau_init = ewma_factor_forecast(train_ret)
            last_ewma_tau = ewma_tau_init[-1]
            last_ewma_g = ewma_g_init[-1]

        # Update tau and g (EWMA always updates — this was correct in K889)
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

    # 5d: MCS (Model Confidence Set) — BUG FIX #1: Proper Hansen-Lunde-Nason (2011)
    # Compute pointwise QLIKE losses for each model
    mcs_losses = {}
    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 100:
            mcs_losses[m] = qlike_pointwise(oos_r2, f)
        # Note: if a model has NaN forecasts, its losses will have NaN entries
        # MCS will handle this via the valid mask

    # Align losses — use only indices where all models have valid forecasts
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
    print(f"      P-values: {', '.join(f'{m}={mcs_p_values.get(m, 0):.3f}' for m in models)}")

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
            'eliminated': mcs_eliminated,
            'p_values': {m: round(v, 4) for m, v in mcs_p_values.items()},
        },
        'var': {str(a): {m: v for m, v in var_results[a].items()} for a in ALPHA_LEVELS},
        'component_analysis': component_analysis,
        'parameters': param_report,
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
# SECTION 7: COMPARISON WITH K889
# ============================================================
print("\n" + "=" * 70)
print("K889v2 vs K889 COMPARISON (Bug Fix Impact)")
print("=" * 70)

# K889 original results for comparison
k889_dm = {
    'SPY': {'MF-GARCH': -2.855, 'MF-GJR': -3.302},
    'QQQ': {'MF-GARCH': -2.480, 'MF-GJR': -2.949},
    '0050.TW': {'MF-GARCH': -0.556, 'MF-GJR': -0.086},
}
k889_qlike_pct = {
    'SPY': {'MF-GARCH': -5.442, 'MF-GJR': -6.078},
    'QQQ': {'MF-GARCH': -4.531, 'MF-GJR': -5.024},
    '0050.TW': {'MF-GARCH': -1.053, 'MF-GJR': -0.106},
}

for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    print(f"\n{ticker}:")
    for m in ['MF-GARCH', 'MF-GJR']:
        old_t = k889_dm.get(ticker, {}).get(m)
        new_t = r['dm_vs_gjr'].get(m, {}).get('t')
        old_q = k889_qlike_pct.get(ticker, {}).get(m)
        new_q = r['qlike_pct_vs_gjr'].get(m)
        print(f"  {m}:")
        if old_t is not None and new_t is not None:
            print(f"    DM t: {old_t:+.3f} (K889) → {new_t:+.3f} (K889v2)  "
                  f"{'STILL PASSES Harvey' if abs(new_t) > 3.0 else 'NO LONGER passes Harvey'}")
        if old_q is not None and new_q is not None:
            print(f"    QLIKE %: {old_q:+.3f}% (K889) → {new_q:+.3f}% (K889v2)")


# ============================================================
# SECTION 8: CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

# Check if any MVF model significantly beats GJR across assets
any_significant = False
significant_list = []
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    for m in ['MF-GARCH', 'MF-GJR', 'EWMA-Factor']:
        dm = all_results[ticker]['dm_vs_gjr'].get(m, {})
        if dm.get('significant_harvey', False) and dm.get('t', 0) < 0:
            any_significant = True
            significant_list.append(f"{m} on {ticker} (DM t={dm['t']:.3f})")
            print(f"  SIGNIFICANT: {m} beats GJR on {ticker} (DM t={dm['t']:.3f})")

if not any_significant:
    print("  No multiplicative model significantly beats GJR (Harvey |t|>3.0)")
    print("  → Bug fixes eliminated the K889 significant result")
else:
    print(f"\n  K889v2 CONFIRMS significance for: {', '.join(significant_list)}")


# ============================================================
# SECTION 9: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR Bug-Fixed Verification (K889v2)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'bug_fixes': [
        'FIX #1 [HIGH]: Replaced fake pairwise-DM MCS with proper Hansen-Lunde-Nason (2011) MCS from volpred.stats.mcs',
        'FIX #2 [HIGH]: Removed 0050.TW VIX pre-shift (was causing double-lag VIX_{t-2})',
        'FIX #3 [MEDIUM]: After refit, advance latent state one step with most recent return before using as forecast',
    ],
    'methodology': {
        'models': ['GJR-GARCH(1,1)', 'MF-GARCH', 'MF-GJR', 'EWMA-Factor', 'EWMA(0.94)'],
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_garch': 'g_t = (1-a-b) + a*u^2_{t-1} + b*g_{t-1}, u=r/sqrt(tau)',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'ewma_factor': 'tau=EWMA(0.99), g=EWMA(0.94) on standardized',
        'estimation': 'Rolling window (w=2000), refit every 63 days, MLE with multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman, proper MCS (HLN 2011), VaR Trinity',
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
    'k889_comparison': {
        'k889_spy_mfgjr_dm_t': -3.302,
        'k889v2_spy_mfgjr_dm_t': all_results.get('SPY', {}).get('dm_vs_gjr', {}).get('MF-GJR', {}).get('t'),
        'conclusion_survives': any_significant,
        'significant_results': significant_list,
    },
    'conclusion': {
        'any_mvf_significant_vs_gjr': any_significant,
        'k889_result_survives_bug_fixes': any_significant,
        'bug_fix_impact': 'TBD — see comparison section above',
    },
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Engle & Rangel (2008) RFS 21(3):1187-1222',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104',
        'Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497',
    ]
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\nResults saved to: {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s")
print("=" * 70)
