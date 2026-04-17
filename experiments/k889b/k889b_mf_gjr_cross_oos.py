#!/usr/bin/env python3
"""
K889b: MF-GJR Cross-OOS Validation
====================================
[提出: Claude, 執行: Claude]

Validates K889 result (MF-GJR beats GJR, DM t=-3.30) across 5 non-overlapping
2-year OOS periods to rule out sample-specific luck.

Models:
  - GJR-GARCH(1,1): baseline
  - MF-GARCH: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1})), g_t = GARCH(1,1)
  - MF-GJR: same long-run, g_t = GJR-GARCH(1,1)

Cross-OOS Design (5 non-overlapping 2-year periods):
  Period 1: IS end 2008-12-31, OOS 2009-01-01 to 2010-12-31 (recovery)
  Period 2: IS end 2010-12-31, OOS 2011-01-01 to 2012-12-31 (Euro crisis)
  Period 3: IS end 2014-12-31, OOS 2015-01-01 to 2016-12-31 (China/oil)
  Period 4: IS end 2018-12-31, OOS 2019-01-01 to 2020-12-31 (COVID)
  Period 5: IS end 2022-12-31, OOS 2023-01-01 to 2024-12-31 (AI boom)

Evaluation per period:
  - QLIKE on r^2 (Patton 2011)
  - DM test vs GJR (Harvey |t| > 3.0)
  - Spearman rank correlation
  - Summary: wins/5, avg QLIKE improvement, Harvey passes

Error Log rules:
  - DM test: use volpred.stats.model_evaluation (not self-written)
  - GARCH OOS: recursive h[t] = f(h[t-1], r^2[t-1]), no stale variance
  - Basel: use standard thresholds

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104

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
from scipy.stats import norm, chi2
from numba import njit

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K889b"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k889b_mf_gjr_cross_oos_results.json')

# Data parameters
DATA_START = '2000-01-01'  # Earlier start for sufficient IS in Period 1
DATA_END = '2025-01-01'
WINDOW = 2000  # Rolling window for estimation
REFIT_EVERY = 63  # Quarterly refit

# 5 non-overlapping 2-year OOS periods
PERIODS = [
    {'name': 'P1_Recovery',    'oos_start': '2009-01-01', 'oos_end': '2010-12-31', 'regime': 'Post-GFC recovery'},
    {'name': 'P2_EuroCrisis',  'oos_start': '2011-01-01', 'oos_end': '2012-12-31', 'regime': 'Euro sovereign debt crisis'},
    {'name': 'P3_ChinaOil',    'oos_start': '2015-01-01', 'oos_end': '2016-12-31', 'regime': 'China devaluation + oil crash'},
    {'name': 'P4_COVID',       'oos_start': '2019-01-01', 'oos_end': '2020-12-31', 'regime': 'Trade war + COVID crash'},
    {'name': 'P5_AIBoom',      'oos_start': '2023-01-01', 'oos_end': '2024-12-31', 'regime': 'AI boom + rate hikes'},
]

MODELS = ['GJR', 'MF-GARCH', 'MF-GJR']

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR Cross-OOS Validation (5 periods)")
print("  Validating K889 SPY result across different market regimes")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Download SPY
print("  Loading SPY...")
spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
spy_prices = spy_raw['Close'].copy()
spy_ret = np.log(spy_prices / spy_prices.shift(1))

# Download VIX
print("  Loading VIX...")
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# Build combined dataframe
df = pd.DataFrame({
    'price': spy_prices,
    'log_ret': spy_ret,
    'VIX': vix_close,
})
df = df.dropna()
df['log_vix'] = np.log(df['VIX'])

print(f"  SPY data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")

# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS (from K889, Numba-accelerated)
# ============================================================
print("\n[2] Model implementations (from K889)...")


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


def fit_mf_model(returns, log_vix, model_type='garch'):
    """Fit MF-GARCH or MF-GJR via joint MLE.

    Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
    Short-run: g_t = GARCH(1,1) or GJR-GARCH(1,1) on u_t = r_t/sqrt(tau_t)
    Total: sigma^2_t = tau_t * g_t
    """
    n = len(returns)
    assert len(log_vix) == n

    # Step 1: OLS for initial theta
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


def reconstruct_gjr_h(params, returns):
    """Reconstruct GJR-GARCH h series for training data."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        h[t] = max(h[t], 1e-10)
    return h


def reconstruct_mf_g(params, returns, log_vix, model_type='garch'):
    """Reconstruct MF-model g series for training data."""
    if model_type == 'gjr':
        theta0, theta1, alpha, gamma, beta = params
    else:
        theta0, theta1, alpha, beta = params
        gamma = 0.0

    n = len(returns)
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

    return g, tau


# ============================================================
# SECTION 3: CROSS-OOS EVALUATION
# ============================================================
print("\n[3] Cross-OOS evaluation across 5 periods...")

ret_all = df['log_ret'].values
log_vix_all = df['log_vix'].values
r2_all = ret_all ** 2
dates_all = df.index

period_results = []

for pi, period in enumerate(PERIODS):
    pname = period['name']
    oos_start = period['oos_start']
    oos_end = period['oos_end']
    regime = period['regime']

    print(f"\n  {'='*60}")
    print(f"  Period {pi+1}: {pname} ({oos_start} to {oos_end})")
    print(f"  Regime: {regime}")
    print(f"  {'='*60}")

    # Find OOS indices
    oos_mask = (dates_all >= oos_start) & (dates_all <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        print(f"    WARNING: No data for period {pname}")
        period_results.append({'name': pname, 'error': 'No data'})
        continue

    oos_start_idx = oos_indices[0]
    oos_end_idx = oos_indices[-1]
    n_oos = len(oos_indices)

    print(f"    OOS: idx {oos_start_idx}-{oos_end_idx}, "
          f"date {dates_all[oos_start_idx].strftime('%Y-%m-%d')} to "
          f"{dates_all[oos_end_idx].strftime('%Y-%m-%d')}, n={n_oos}")

    # IS data: everything before OOS start (expanding window, but min WINDOW)
    is_end_idx = oos_start_idx  # exclusive
    is_n = is_end_idx
    print(f"    IS: n={is_n} (from {dates_all[0].strftime('%Y-%m-%d')} to "
          f"{dates_all[is_end_idx-1].strftime('%Y-%m-%d')})")

    if is_n < WINDOW:
        print(f"    WARNING: IS ({is_n}) < WINDOW ({WINDOW}), using all available IS data")

    # Storage for OOS forecasts
    forecasts = {m: np.full(n_oos, np.nan) for m in MODELS}

    # Track state for recursive forecasting
    last_gjr_params = None
    last_gjr_h = None
    last_mfgarch_params = None
    last_mfgjr_params = None
    last_mfgarch_g = None
    last_mfgjr_g = None
    tau_prev_mfgarch = None
    tau_prev_mfgjr = None

    n_refits = 0

    for t in range(n_oos):
        idx = oos_start_idx + t  # actual index in full dataset
        need_refit = (t == 0) or (t % REFIT_EVERY == 0)

        # Training window: expanding from beginning, but capped at WINDOW most recent
        train_end = idx  # exclusive
        train_start = max(0, train_end - WINDOW)
        train_ret = ret_all[train_start:train_end]
        train_vix = log_vix_all[train_start:train_end]

        if need_refit:
            n_refits += 1

            # Fit GJR-GARCH
            gjr_params, gjr_ll = fit_gjr_garch(train_ret)
            if gjr_params is not None:
                last_gjr_params = gjr_params
                h_arr = reconstruct_gjr_h(gjr_params, train_ret)
                last_gjr_h = h_arr[-1]

            # Fit MF-GARCH
            mfg_params, mfg_ll = fit_mf_model(train_ret, train_vix, model_type='garch')
            if mfg_params is not None:
                last_mfgarch_params = mfg_params
                g_arr, tau_arr = reconstruct_mf_g(mfg_params, train_ret, train_vix, 'garch')
                last_mfgarch_g = g_arr[-1]
                tau_prev_mfgarch = tau_arr[-1]

            # Fit MF-GJR
            mfgjr_params, mfgjr_ll = fit_mf_model(train_ret, train_vix, model_type='gjr')
            if mfgjr_params is not None:
                last_mfgjr_params = mfgjr_params
                g_arr, tau_arr = reconstruct_mf_g(mfgjr_params, train_ret, train_vix, 'gjr')
                last_mfgjr_g = g_arr[-1]
                tau_prev_mfgjr = tau_arr[-1]

        # === One-step-ahead forecasts ===

        # GJR-GARCH: recursive h[t] = f(h[t-1], r^2[t-1])
        if last_gjr_params is not None and last_gjr_h is not None:
            if t > 0:
                last_gjr_h = gjr_garch_forecast_oos(
                    last_gjr_params, ret_all[idx-1], last_gjr_h)
            forecasts['GJR'][t] = last_gjr_h

        # MF-GARCH: tau from VIX_{t-1}, g recursive on standardized
        if last_mfgarch_params is not None and tau_prev_mfgarch is not None:
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

        # MF-GJR: tau from VIX_{t-1}, g recursive with leverage
        if last_mfgjr_params is not None and tau_prev_mfgjr is not None:
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

    print(f"    Refits: {n_refits}")

    # ---- Evaluation ----
    oos_r2 = r2_all[oos_start_idx:oos_end_idx+1]
    oos_returns = ret_all[oos_start_idx:oos_end_idx+1]

    # Ensure arrays match
    assert len(oos_r2) == n_oos, f"Length mismatch: oos_r2={len(oos_r2)}, n_oos={n_oos}"

    # QLIKE
    qlike_results = {}
    for m in MODELS:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 50:
            qlike_results[m] = float(qlike(oos_r2[valid], f[valid]))
        else:
            qlike_results[m] = np.nan

    gjr_qlike = qlike_results.get('GJR', np.nan)
    qlike_pct = {}
    for m in MODELS:
        if np.isfinite(qlike_results.get(m, np.nan)) and np.isfinite(gjr_qlike) and gjr_qlike > 0:
            qlike_pct[m] = round(((qlike_results[m] - gjr_qlike) / gjr_qlike) * 100, 3)
        else:
            qlike_pct[m] = np.nan

    print(f"\n    QLIKE on r^2:")
    for m in MODELS:
        pct = qlike_pct.get(m, np.nan)
        pct_str = f"{pct:+.3f}%" if np.isfinite(pct) else "N/A"
        ql = qlike_results.get(m, np.nan)
        ql_str = f"{ql:.6f}" if np.isfinite(ql) else "N/A"
        print(f"      {m:15s}: {ql_str} ({pct_str} vs GJR)")

    # Spearman
    spearman_results = {}
    for m in MODELS:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 50:
            rho, p = spearman_corr(oos_r2[valid], f[valid])
            spearman_results[m] = {'rho': round(float(rho), 4), 'p': round(float(p), 6)}
        else:
            spearman_results[m] = {'rho': np.nan, 'p': np.nan}

    print(f"\n    Spearman rank correlation:")
    for m in MODELS:
        r = spearman_results[m]
        rho_str = f"{r['rho']:.4f}" if np.isfinite(r['rho']) else "N/A"
        print(f"      {m:15s}: rho={rho_str}")

    # DM tests vs GJR
    gjr_loss = qlike_pointwise(oos_r2, forecasts['GJR'])
    dm_results = {}
    for m in MODELS:
        if m == 'GJR':
            dm_results[m] = {'t': 0.0, 'p': 1.0, 'significant_harvey': False}
            continue
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0) & np.isfinite(gjr_loss)
        if valid.sum() > 50:
            m_loss = qlike_pointwise(oos_r2[valid], f[valid])
            t_stat, p_val = dm_test(m_loss, gjr_loss[valid])
            dm_results[m] = {
                't': round(float(t_stat), 3),
                'p': round(float(p_val), 4),
                'significant_harvey': bool(abs(float(t_stat)) > 3.0)
            }
        else:
            dm_results[m] = {'t': np.nan, 'p': np.nan, 'significant_harvey': False}

    print(f"\n    DM tests vs GJR (negative t = model is better):")
    for m in MODELS:
        r = dm_results[m]
        t_val = r['t']
        if np.isfinite(t_val):
            sig = "HARVEY PASS" if abs(t_val) > 3.0 else ("*" if abs(t_val) > 1.96 else "NS")
            print(f"      {m:15s}: t={t_val:+.3f} (p={r['p']:.4f}) {sig}")
        else:
            print(f"      {m:15s}: N/A")

    # Determine winner
    mf_models = ['MF-GARCH', 'MF-GJR']
    winner = 'GJR'
    for m in mf_models:
        ql = qlike_results.get(m, np.nan)
        ql_gjr = qlike_results.get('GJR', np.nan)
        if np.isfinite(ql) and np.isfinite(ql_gjr) and ql < ql_gjr:
            winner = m
            break  # Take first MF that beats GJR

    # Actually pick best model by QLIKE
    valid_models = {m: q for m, q in qlike_results.items() if np.isfinite(q)}
    if valid_models:
        winner = min(valid_models, key=valid_models.get)

    # Store results
    result = {
        'name': pname,
        'regime': regime,
        'oos_start': str(dates_all[oos_start_idx].date()),
        'oos_end': str(dates_all[oos_end_idx].date()),
        'n_oos': n_oos,
        'n_is': is_n,
        'n_refits': n_refits,
        'qlike': {m: round(v, 6) if np.isfinite(v) else None for m, v in qlike_results.items()},
        'qlike_pct_vs_gjr': {m: v if np.isfinite(v) else None for m, v in qlike_pct.items()},
        'spearman': spearman_results,
        'dm_vs_gjr': dm_results,
        'winner_qlike': winner,
        'mfgjr_wins': bool(qlike_results.get('MF-GJR', np.inf) < qlike_results.get('GJR', np.inf)),
        'mfgarch_wins': bool(qlike_results.get('MF-GARCH', np.inf) < qlike_results.get('GJR', np.inf)),
    }

    # Report last-fit parameters
    params_report = {}
    if last_gjr_params is not None:
        params_report['GJR'] = {
            'omega': round(float(last_gjr_params[0]), 8),
            'alpha': round(float(last_gjr_params[1]), 6),
            'gamma': round(float(last_gjr_params[2]), 6),
            'beta': round(float(last_gjr_params[3]), 6),
            'persistence': round(float(last_gjr_params[1] + last_gjr_params[2]/2 + last_gjr_params[3]), 6)
        }
    if last_mfgarch_params is not None:
        params_report['MF-GARCH'] = {
            'theta_0': round(float(last_mfgarch_params[0]), 4),
            'theta_1': round(float(last_mfgarch_params[1]), 4),
            'alpha': round(float(last_mfgarch_params[2]), 6),
            'beta': round(float(last_mfgarch_params[3]), 6),
            'persistence_g': round(float(last_mfgarch_params[2] + last_mfgarch_params[3]), 6)
        }
    if last_mfgjr_params is not None:
        params_report['MF-GJR'] = {
            'theta_0': round(float(last_mfgjr_params[0]), 4),
            'theta_1': round(float(last_mfgjr_params[1]), 4),
            'alpha': round(float(last_mfgjr_params[2]), 6),
            'gamma': round(float(last_mfgjr_params[3]), 6),
            'beta': round(float(last_mfgjr_params[4]), 6),
            'persistence_g': round(float(last_mfgjr_params[2] + last_mfgjr_params[3]/2 + last_mfgjr_params[4]), 6)
        }
    result['parameters'] = params_report

    period_results.append(result)

    print(f"\n    Winner by QLIKE: {winner}")
    print(f"    MF-GJR beats GJR? {'YES' if result['mfgjr_wins'] else 'NO'}")
    print(f"    MF-GARCH beats GJR? {'YES' if result['mfgarch_wins'] else 'NO'}")


# ============================================================
# SECTION 4: CROSS-PERIOD SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-PERIOD SUMMARY")
print("=" * 70)

# Count wins
mfgjr_wins = sum(1 for r in period_results if r.get('mfgjr_wins', False))
mfgarch_wins = sum(1 for r in period_results if r.get('mfgarch_wins', False))
n_periods = len([r for r in period_results if 'error' not in r])

print(f"\n  MF-GJR beats GJR: {mfgjr_wins}/{n_periods} periods")
print(f"  MF-GARCH beats GJR: {mfgarch_wins}/{n_periods} periods")

# Average QLIKE improvement
mfgjr_pcts = [r['qlike_pct_vs_gjr'].get('MF-GJR', np.nan) for r in period_results
              if 'error' not in r and r['qlike_pct_vs_gjr'].get('MF-GJR') is not None]
mfgarch_pcts = [r['qlike_pct_vs_gjr'].get('MF-GARCH', np.nan) for r in period_results
                if 'error' not in r and r['qlike_pct_vs_gjr'].get('MF-GARCH') is not None]

if mfgjr_pcts:
    avg_mfgjr_pct = np.mean(mfgjr_pcts)
    std_mfgjr_pct = np.std(mfgjr_pcts)
    print(f"\n  MF-GJR avg QLIKE improvement: {avg_mfgjr_pct:+.3f}% (std={std_mfgjr_pct:.3f}%)")
    for pi, r in enumerate(period_results):
        if 'error' not in r:
            pct = r['qlike_pct_vs_gjr'].get('MF-GJR', 'N/A')
            pct_str = f"{pct:+.3f}%" if isinstance(pct, (int, float)) else "N/A"
            print(f"    P{pi+1} ({r['name']}): {pct_str}")

if mfgarch_pcts:
    avg_mfgarch_pct = np.mean(mfgarch_pcts)
    std_mfgarch_pct = np.std(mfgarch_pcts)
    print(f"\n  MF-GARCH avg QLIKE improvement: {avg_mfgarch_pct:+.3f}% (std={std_mfgarch_pct:.3f}%)")
    for pi, r in enumerate(period_results):
        if 'error' not in r:
            pct = r['qlike_pct_vs_gjr'].get('MF-GARCH', 'N/A')
            pct_str = f"{pct:+.3f}%" if isinstance(pct, (int, float)) else "N/A"
            print(f"    P{pi+1} ({r['name']}): {pct_str}")

# Harvey significant DM tests
print(f"\n  Harvey-significant DM tests (|t| > 3.0):")
mfgjr_harvey_pass = 0
mfgarch_harvey_pass = 0
for pi, r in enumerate(period_results):
    if 'error' in r:
        continue
    for m in ['MF-GJR', 'MF-GARCH']:
        dm = r['dm_vs_gjr'].get(m, {})
        t_val = dm.get('t', np.nan)
        if np.isfinite(t_val) and abs(t_val) > 3.0:
            direction = "better" if t_val < 0 else "worse"
            print(f"    P{pi+1} ({r['name']}): {m} t={t_val:+.3f} ({direction} than GJR)")
            if t_val < 0:
                if m == 'MF-GJR':
                    mfgjr_harvey_pass += 1
                else:
                    mfgarch_harvey_pass += 1

print(f"\n  MF-GJR Harvey PASS (negative t): {mfgjr_harvey_pass}/{n_periods}")
print(f"  MF-GARCH Harvey PASS (negative t): {mfgarch_harvey_pass}/{n_periods}")

# DM t-stats across periods
print(f"\n  DM t-stats across periods:")
print(f"  {'Period':<20s} {'MF-GARCH':>10s} {'MF-GJR':>10s}")
print(f"  {'-'*40}")
for pi, r in enumerate(period_results):
    if 'error' in r:
        continue
    mfg_t = r['dm_vs_gjr'].get('MF-GARCH', {}).get('t', np.nan)
    mfgjr_t = r['dm_vs_gjr'].get('MF-GJR', {}).get('t', np.nan)
    mfg_str = f"{mfg_t:+.3f}" if np.isfinite(mfg_t) else "N/A"
    mfgjr_str = f"{mfgjr_t:+.3f}" if np.isfinite(mfgjr_t) else "N/A"
    print(f"  {r['name']:<20s} {mfg_str:>10s} {mfgjr_str:>10s}")

# Spearman summary
print(f"\n  Spearman rho across periods:")
print(f"  {'Period':<20s} {'GJR':>8s} {'MF-GARCH':>10s} {'MF-GJR':>10s}")
print(f"  {'-'*50}")
for pi, r in enumerate(period_results):
    if 'error' in r:
        continue
    gjr_rho = r['spearman'].get('GJR', {}).get('rho', np.nan)
    mfg_rho = r['spearman'].get('MF-GARCH', {}).get('rho', np.nan)
    mfgjr_rho = r['spearman'].get('MF-GJR', {}).get('rho', np.nan)
    gjr_str = f"{gjr_rho:.4f}" if np.isfinite(gjr_rho) else "N/A"
    mfg_str = f"{mfg_rho:.4f}" if np.isfinite(mfg_rho) else "N/A"
    mfgjr_str = f"{mfgjr_rho:.4f}" if np.isfinite(mfgjr_rho) else "N/A"
    print(f"  {r['name']:<20s} {gjr_str:>8s} {mfg_str:>10s} {mfgjr_str:>10s}")

# Average Spearman
spearman_avgs = {}
for m in MODELS:
    rhos = [r['spearman'].get(m, {}).get('rho', np.nan) for r in period_results
            if 'error' not in r]
    rhos_valid = [x for x in rhos if np.isfinite(x)]
    if rhos_valid:
        spearman_avgs[m] = np.mean(rhos_valid)
print(f"\n  Average Spearman rho:")
for m, avg in spearman_avgs.items():
    print(f"    {m}: {avg:.4f}")


# ============================================================
# SECTION 5: CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

# Robustness verdict
mfgjr_robust = mfgjr_wins >= 3
mfgarch_robust = mfgarch_wins >= 3

if mfgjr_robust:
    print(f"\n  MF-GJR is ROBUST: wins {mfgjr_wins}/{n_periods} periods (>= 3 required)")
else:
    print(f"\n  MF-GJR is NOT ROBUST: wins only {mfgjr_wins}/{n_periods} periods (>= 3 required)")

if mfgarch_robust:
    print(f"  MF-GARCH is ROBUST: wins {mfgarch_wins}/{n_periods} periods (>= 3 required)")
else:
    print(f"  MF-GARCH is NOT ROBUST: wins only {mfgarch_wins}/{n_periods} periods (>= 3 required)")

# K889 validation
k889_validated = mfgjr_robust or mfgarch_robust
if k889_validated:
    print(f"\n  K889 VALIDATED: Multiplicative factor model advantage is robust across regimes")
else:
    print(f"\n  K889 NOT VALIDATED: Result may be sample-specific to 2019-2026 OOS period")

# Harvey significance rate
total_harvey = mfgjr_harvey_pass + mfgarch_harvey_pass
print(f"\n  Harvey |t|>3.0 significance rate: {total_harvey}/{n_periods*2} tests")
print(f"  (K889 original: MF-GJR DM t=-3.30 on 2019-2026)")


# ============================================================
# SECTION 6: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

# Compute summary stats
summary = {
    'n_periods': n_periods,
    'mfgjr_wins_vs_gjr': mfgjr_wins,
    'mfgarch_wins_vs_gjr': mfgarch_wins,
    'mfgjr_harvey_passes': mfgjr_harvey_pass,
    'mfgarch_harvey_passes': mfgarch_harvey_pass,
    'mfgjr_robust': mfgjr_robust,
    'mfgarch_robust': mfgarch_robust,
    'k889_validated': k889_validated,
    'avg_mfgjr_qlike_pct': round(float(avg_mfgjr_pct), 3) if mfgjr_pcts else None,
    'avg_mfgarch_qlike_pct': round(float(avg_mfgarch_pct), 3) if mfgarch_pcts else None,
    'std_mfgjr_qlike_pct': round(float(std_mfgjr_pct), 3) if mfgjr_pcts else None,
    'std_mfgarch_qlike_pct': round(float(std_mfgarch_pct), 3) if mfgarch_pcts else None,
    'avg_spearman': {m: round(v, 4) for m, v in spearman_avgs.items()},
}

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR Cross-OOS Validation',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'methodology': {
        'models': ['GJR-GARCH(1,1)', 'MF-GARCH', 'MF-GJR'],
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_garch': 'g_t = (1-a-b) + a*u^2_{t-1} + b*g_{t-1}, u=r/sqrt(tau)',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'estimation': f'Rolling window (w={WINDOW}), refit every {REFIT_EVERY} days, MLE with multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman',
        'cross_oos': '5 non-overlapping 2-year OOS periods (2009-2024)',
        'robustness_criterion': 'Must win >= 3/5 periods by QLIKE to be considered robust',
    },
    'data': {
        'source': 'yfinance',
        'asset': 'SPY',
        'period': f'{DATA_START} to {DATA_END}',
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
    },
    'k889_original': {
        'oos_period': '2019-01-01 to 2026-04-01',
        'mfgjr_dm_t': -3.302,
        'mfgjr_qlike_pct': -6.078,
        'mfgjr_harvey_pass': True,
    },
    'periods': period_results,
    'summary': summary,
    'conclusion': {
        'k889_validated': k889_validated,
        'mfgjr_robust': mfgjr_robust,
        'mfgarch_robust': mfgarch_robust,
        'note': ('Cross-OOS validation of K889 MF-GJR result across '
                 '5 non-overlapping 2-year periods (2009-2024). '
                 f'MF-GJR wins {mfgjr_wins}/{n_periods}, '
                 f'MF-GARCH wins {mfgarch_wins}/{n_periods}.')
    },
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104'
    ]
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\n\nResults saved to: {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s")
print(f"\nDone!")
