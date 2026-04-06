#!/usr/bin/env python3
"""
K943: Multi-Horizon MF-GJR(VIX) — Multi-step Forecasting Ability
==================================================================
[提出: Claude (research_program), 執行: Claude]

Research Question:
  MF-GJR(VIX) is the best h=1 model (K889, K942). But practitioners care about
  h=5 (weekly) and h=22 (monthly) volatility. Does the VIX factor give MF-GJR
  an advantage at longer horizons?

Hypothesis:
  VIX is forward-looking (options-implied), so it naturally embeds multi-step
  information. MF-GJR should have a larger advantage at h=5 and especially h=22
  compared to h=1.

Data:
  - Asset: SPY (2006-01-01 to 2026-04-01), source: yfinance
  - VIX from yfinance (^VIX)
  - OOS: 2016-01-01 to latest
  - Window: 2000, Refit every 21 days

Multi-step GARCH forecasting formula:
  For GJR: σ²(h) = Σ_{i=1}^{h} σ²_{t+i|t}
  - σ²_{t+1|t} = ω + (α + γ/2) r²_t + β σ²_t  (since E[I(r<0)] = 0.5)
  - σ²_{t+i|t} = ω + (α + γ/2 + β) σ²_{t+i-1|t}  for i >= 2

  For MF-GJR: cumulative = Σ_{i=1}^{h} τ_t × g_{t+i|t}
  - τ_t held constant (latest VIX_{t-1})
  - g_{t+i|t} follows short-run recursion

Targets:
  h=1: r²_t
  h=5: Σ_{j=0}^{4} r²_{t+j}  (weekly cumulative squared return)
  h=22: Σ_{j=0}^{21} r²_{t+j}  (monthly cumulative squared return)

Models:
  1. GARCH(1,1)
  2. GJR-GARCH(1,1,1)
  3. MF-GJR(VIX)

Evaluation (per horizon):
  - QLIKE on cumulative r² (Patton 2011 proxy-robust)
  - OOS R²
  - Spearman ρ
  - DM test: MF-GJR vs GJR (Harvey |t| > 3.0)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - Bollerslev, Engle & Nelson (1994) ARCH models in Handbook of Econometrics

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
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K943"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k943_results.json')
CHART_PATH = os.path.join(SCRIPT_DIR, 'k943_horizon_comparison.png')

# Data parameters
DATA_START = '2006-01-01'
DATA_END = '2026-04-01'
OOS_START = '2016-01-01'
WINDOW = 2000
REFIT_EVERY = 21
HORIZONS = [1, 5, 22]

print("=" * 70)
print(f"{EXPERIMENT_ID}: Multi-Horizon MF-GJR(VIX)")
print(f"  Horizons: h={HORIZONS}")
print(f"  Window={WINDOW}, Refit every {REFIT_EVERY} days")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

ticker = 'SPY'
print(f"  Loading {ticker}...")
raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
df = df.dropna(subset=['log_ret'])
df = df.join(vix_data, how='left')
df['VIX'] = df['VIX'].ffill()
df = df.dropna()

print(f"  {ticker}: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
ret_arr = df['log_ret'].values
desc = {
    'mean': float(np.mean(ret_arr)),
    'std': float(np.std(ret_arr)),
    'skewness': float(stats.skew(ret_arr)),
    'kurtosis': float(stats.kurtosis(ret_arr)),
    'n': int(len(ret_arr))
}
jb_stat, jb_p = stats.jarque_bera(ret_arr)
# ARCH LM test (10 lags)
ret2_diag = ret_arr ** 2
n_lm = len(ret2_diag) - 10
X_lm = np.column_stack([np.ones(n_lm)] + [ret2_diag[i:i+n_lm] for i in range(10)])
y_lm = ret2_diag[10:]
b_lm = np.linalg.lstsq(X_lm, y_lm, rcond=None)[0]
r2_lm = 1 - np.var(y_lm - X_lm @ b_lm) / np.var(y_lm)
arch_lm = n_lm * r2_lm

print(f"  Mean={desc['mean']:.6f} Std={desc['std']:.4f} "
      f"Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.2f} "
      f"JB={jb_stat:.0f}(p={jb_p:.1e}) ARCH_LM={arch_lm:.1f}")

diagnostics = {
    'descriptive_stats': desc,
    'jarque_bera': {'stat': float(jb_stat), 'p_value': float(jb_p)},
    'arch_lm': {'stat': float(arch_lm), 'lags': 10}
}

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


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


def fit_garch(returns):
    """Fit GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None
    starts = [
        [1e-6, 0.05, 0.90],
        [1e-6, 0.08, 0.85],
        [1e-5, 0.03, 0.93],
        [5e-6, 0.10, 0.85],
    ]
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.5, 0.999)]
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


def garch_recursive_h(params, returns):
    """Reconstruct in-sample h series for GARCH(1,1)."""
    omega, alpha, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    for t in range(1, n):
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
        h[t] = max(h[t], 1e-10)
    return h


def garch_multistep_forecast(params, last_r, last_h, horizon):
    """Multi-step cumulative variance forecast for GARCH(1,1).

    σ²_{t+1|t} = ω + α r²_t + β h_t
    σ²_{t+i|t} = ω + (α + β) σ²_{t+i-1|t}  for i >= 2

    Returns: Σ_{i=1}^{h} σ²_{t+i|t}
    """
    omega, alpha, beta = params
    persistence = alpha + beta

    # Step 1: one-step forecast
    h1 = omega + alpha * last_r**2 + beta * last_h
    h1 = max(h1, 1e-10)

    if horizon == 1:
        return h1

    # Steps 2..h: iterate using unconditional E[r²] = σ²
    cumulative = h1
    h_current = h1
    for _ in range(horizon - 1):
        h_current = omega + persistence * h_current
        h_current = max(h_current, 1e-10)
        cumulative += h_current

    return cumulative


def gjr_garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood. Returns negative LL."""
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


def gjr_recursive_h(params, returns):
    """Reconstruct in-sample h series for GJR."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        h[t] = max(h[t], 1e-10)
    return h


def gjr_multistep_forecast(params, last_r, last_h, horizon):
    """Multi-step cumulative variance forecast for GJR-GARCH.

    σ²_{t+1|t} = ω + α r²_t + γ r²_t I(r_t<0) + β h_t
    σ²_{t+i|t} = ω + (α + γ/2 + β) σ²_{t+i-1|t}  for i >= 2
    (since E[I(r<0)] ≈ 0.5)
    """
    omega, alpha, gamma, beta = params
    persistence = alpha + gamma / 2.0 + beta

    # Step 1: actual forecast
    asym = gamma * last_r**2 if last_r < 0 else 0.0
    h1 = omega + alpha * last_r**2 + asym + beta * last_h
    h1 = max(h1, 1e-10)

    if horizon == 1:
        return h1

    cumulative = h1
    h_current = h1
    for _ in range(horizon - 1):
        h_current = omega + persistence * h_current
        h_current = max(h_current, 1e-10)
        cumulative += h_current

    return cumulative


def fit_mf_gjr(returns, log_vix):
    """Fit MF-GJR model.

    Long-run: τ_t = exp(θ₀ + θ₁ × log(VIX_{t-1}))
    Short-run: g_t = GJR on u_t = r_t / √τ_t (unit mean constraint)
    Total: σ²_t = τ_t × g_t
    """
    n = len(returns)
    assert len(log_vix) == n

    # VIX lag
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    # OLS initial theta
    r2 = returns ** 2
    r2_pos = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_pos)
    X_ols = np.column_stack([np.ones(n), log_vix_lag])
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    def neg_loglik(params):
        theta0, theta1, alpha, gamma, beta = params

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
    starts = [
        [theta_init[0], theta_init[1], 0.05, 0.05, 0.90],
        [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.10, 0.85],
        [-8.0, 0.5, 0.05, 0.05, 0.90],
        [-7.0, 0.8, 0.03, 0.03, 0.93],
    ]
    bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

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


def mf_gjr_reconstruct(params, returns, log_vix):
    """Reconstruct in-sample g and tau for MF-GJR."""
    theta0, theta1, alpha, gamma, beta = params
    n = len(returns)
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
        g[t] = max(g[t], 1e-10)

    return g, tau


def mf_gjr_multistep_forecast(params, last_u, last_g, last_log_vix, horizon):
    """Multi-step cumulative variance forecast for MF-GJR.

    τ_t held constant at latest VIX level.
    g recursion: E[g_{t+i}] for i>=2 uses persistence.

    σ²_cumulative = τ_t × Σ_{i=1}^{h} g_{t+i|t}
    """
    theta0, theta1, alpha, gamma, beta = params
    persistence_g = alpha + gamma / 2.0 + beta
    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    # τ_t from latest VIX (held constant)
    tau_t = np.exp(theta0 + theta1 * last_log_vix)
    tau_t = max(tau_t, 1e-16)

    # g_{t+1|t}: one-step forecast with actual last_u
    asym = gamma * last_u**2 if last_u < 0 else 0.0
    g1 = omega_g + alpha * last_u**2 + asym + beta * last_g
    g1 = max(g1, 1e-10)

    if horizon == 1:
        return tau_t * g1

    # g_{t+i|t} for i >= 2: iterate using persistence
    cumulative_g = g1
    g_current = g1
    for _ in range(horizon - 1):
        # E[g_{t+i}|t] = omega_g + persistence_g * g_{t+i-1|t}
        g_current = omega_g + persistence_g * g_current
        g_current = max(g_current, 1e-10)
        cumulative_g += g_current

    return tau_t * cumulative_g


# ============================================================
# SECTION 4: ROLLING OOS EVALUATION
# ============================================================
print("\n[4] Rolling OOS evaluation...")

ret = df['log_ret'].values
log_vix_raw = np.log(df['VIX'].values)
r2 = ret ** 2
dates = df.index

# Find OOS start
oos_mask = dates >= OOS_START
oos_start_idx = np.argmax(oos_mask)
if oos_start_idx < WINDOW:
    oos_start_idx = WINDOW
print(f"  OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")

n_total = len(ret)
# For h=22, we need realized targets up to 21 days ahead
# So effective OOS ends at n_total - max(HORIZONS) + 1
max_h = max(HORIZONS)
n_oos_full = n_total - oos_start_idx
n_oos_effective = n_oos_full - max_h + 1  # can compute target for all horizons
print(f"  OOS days (full): {n_oos_full}")
print(f"  OOS days (effective for h=22): {n_oos_effective}")

# Compute realized cumulative squared returns for all horizons
realized_targets = {}
for h in HORIZONS:
    target = np.full(n_total, np.nan)
    for t in range(n_total - h + 1):
        target[t] = np.sum(r2[t:t+h])
    realized_targets[h] = target

# Storage for forecasts: {model: {horizon: array}}
model_names = ['GARCH', 'GJR', 'MF-GJR']
forecasts = {m: {h: np.full(n_oos_full, np.nan) for h in HORIZONS} for m in model_names}

# Rolling estimation
last_garch_params = None
last_garch_h_val = None
last_gjr_params = None
last_gjr_h_val = None
last_mfgjr_params = None
last_mfgjr_g_val = None

n_refits = 0
t0 = time.time()

for t in range(n_oos_full):
    idx = oos_start_idx + t
    need_refit = (t == 0) or (t % REFIT_EVERY == 0)

    # Training window
    train_start = max(0, idx - WINDOW)
    train_ret = ret[train_start:idx]
    train_vix = log_vix_raw[train_start:idx]

    if need_refit:
        n_refits += 1

        # Fit GARCH(1,1)
        garch_params, _ = fit_garch(train_ret)
        if garch_params is not None:
            last_garch_params = garch_params
            h_arr = garch_recursive_h(garch_params, train_ret)
            # BUG FIX: advance one step with last training return
            omega_g, alpha_g, beta_g = garch_params
            last_garch_h_val = omega_g + alpha_g * train_ret[-1]**2 + beta_g * h_arr[-1]
            last_garch_h_val = max(last_garch_h_val, 1e-10)

        # Fit GJR-GARCH
        gjr_params, _ = fit_gjr_garch(train_ret)
        if gjr_params is not None:
            last_gjr_params = gjr_params
            h_arr = gjr_recursive_h(gjr_params, train_ret)
            omega_j, alpha_j, gamma_j, beta_j = gjr_params
            asym_j = gamma_j * train_ret[-1]**2 if train_ret[-1] < 0 else 0.0
            last_gjr_h_val = omega_j + alpha_j * train_ret[-1]**2 + asym_j + beta_j * h_arr[-1]
            last_gjr_h_val = max(last_gjr_h_val, 1e-10)

        # Fit MF-GJR
        mfgjr_params, _ = fit_mf_gjr(train_ret, train_vix)
        if mfgjr_params is not None:
            last_mfgjr_params = mfgjr_params
            g_arr, tau_arr = mf_gjr_reconstruct(mfgjr_params, train_ret, train_vix)
            theta0, theta1, alpha_m, gamma_m, beta_m = mfgjr_params
            omega_gm = 1.0 - alpha_m - gamma_m / 2.0 - beta_m
            # Advance g one step with last training return
            u_last = train_ret[-1] / np.sqrt(tau_arr[-1])
            asym_m = gamma_m * u_last**2 if u_last < 0 else 0.0
            last_mfgjr_g_val = omega_gm + alpha_m * u_last**2 + asym_m + beta_m * g_arr[-1]
            last_mfgjr_g_val = max(last_mfgjr_g_val, 1e-10)

        if n_refits % 10 == 0:
            elapsed = time.time() - t0
            print(f"    Refit {n_refits}, t={t}/{n_oos_full}, elapsed={elapsed:.1f}s")

    # Generate forecasts for each horizon
    for h in HORIZONS:
        # GARCH multi-step
        if last_garch_params is not None and last_garch_h_val is not None:
            forecasts['GARCH'][h][t] = garch_multistep_forecast(
                last_garch_params, ret[idx-1], last_garch_h_val, h
            )

        # GJR multi-step
        if last_gjr_params is not None and last_gjr_h_val is not None:
            forecasts['GJR'][h][t] = gjr_multistep_forecast(
                last_gjr_params, ret[idx-1], last_gjr_h_val, h
            )

        # MF-GJR multi-step
        if last_mfgjr_params is not None and last_mfgjr_g_val is not None:
            # VIX lag: use VIX_{t-1} for τ_t
            last_log_vix_for_tau = log_vix_raw[idx-1]
            # u_{t-1} for g recursion: ret[idx-1] / sqrt(tau_{t-1})
            tau_prev_for_u = np.exp(
                last_mfgjr_params[0] + last_mfgjr_params[1] * log_vix_raw[max(idx-2, 0)]
            )
            u_prev = ret[idx-1] / np.sqrt(max(tau_prev_for_u, 1e-16))
            forecasts['MF-GJR'][h][t] = mf_gjr_multistep_forecast(
                last_mfgjr_params, u_prev, last_mfgjr_g_val,
                last_log_vix_for_tau, h
            )

    # Update latent states (one-step recursion for next day)
    if last_garch_params is not None:
        omega_g, alpha_g, beta_g = last_garch_params
        last_garch_h_val = omega_g + alpha_g * ret[idx]**2 + beta_g * last_garch_h_val
        last_garch_h_val = max(last_garch_h_val, 1e-10)

    if last_gjr_params is not None:
        omega_j, alpha_j, gamma_j, beta_j = last_gjr_params
        asym_j = gamma_j * ret[idx]**2 if ret[idx] < 0 else 0.0
        last_gjr_h_val = omega_j + alpha_j * ret[idx]**2 + asym_j + beta_j * last_gjr_h_val
        last_gjr_h_val = max(last_gjr_h_val, 1e-10)

    if last_mfgjr_params is not None and last_mfgjr_g_val is not None:
        theta0, theta1, alpha_m, gamma_m, beta_m = last_mfgjr_params
        omega_gm = 1.0 - alpha_m - gamma_m / 2.0 - beta_m
        tau_now = np.exp(theta0 + theta1 * log_vix_raw[idx-1])
        tau_now = max(tau_now, 1e-16)
        u_now = ret[idx] / np.sqrt(tau_now)
        asym_m = gamma_m * u_now**2 if u_now < 0 else 0.0
        last_mfgjr_g_val = omega_gm + alpha_m * u_now**2 + asym_m + beta_m * last_mfgjr_g_val
        last_mfgjr_g_val = max(last_mfgjr_g_val, 1e-10)

elapsed_total = time.time() - t0
print(f"\n  OOS complete: {n_refits} refits, {elapsed_total:.1f}s")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

results_by_horizon = {}

for h in HORIZONS:
    print(f"\n  --- Horizon h={h} ---")

    # Get realized target for this horizon
    target_full = realized_targets[h]
    target_oos = target_full[oos_start_idx:oos_start_idx + n_oos_full]

    # Valid mask: both target and all forecasts available
    valid = np.isfinite(target_oos)
    for m in model_names:
        valid &= np.isfinite(forecasts[m][h])
    # For h>1, also need the cumulative target to be valid
    # (last h-1 days of OOS won't have complete target)

    n_valid = np.sum(valid)
    print(f"    Valid OOS observations: {n_valid}")

    if n_valid < 50:
        print(f"    WARNING: Too few valid observations for h={h}")
        continue

    target_v = target_oos[valid]
    fc = {m: forecasts[m][h][valid] for m in model_names}

    # QLIKE (with floor to avoid inf from near-zero targets/forecasts)
    qlike_scores = {}
    for m in model_names:
        target_safe = np.maximum(target_v, 1e-16)
        fc_safe = np.maximum(fc[m], 1e-16)
        ql_pointwise = target_safe / fc_safe - np.log(target_safe / fc_safe) - 1
        # Cap extreme values
        ql_pointwise = np.minimum(ql_pointwise, 100.0)
        qlike_scores[m] = float(np.mean(ql_pointwise))

    # OOS R²
    r2_scores = {}
    ss_total = np.sum((target_v - np.mean(target_v))**2)
    for m in model_names:
        ss_resid = np.sum((target_v - fc[m])**2)
        r2_oos = 1 - ss_resid / ss_total
        r2_scores[m] = float(r2_oos)

    # Spearman ρ
    spearman_scores = {}
    for m in model_names:
        rho, p_rho = stats.spearmanr(target_v, fc[m])
        spearman_scores[m] = {'rho': float(rho), 'p_value': float(p_rho)}

    # DM tests (pairwise)
    dm_results = {}
    pairs = [('MF-GJR', 'GJR'), ('MF-GJR', 'GARCH'), ('GJR', 'GARCH')]
    for m1, m2 in pairs:
        # QLIKE pointwise losses (with floor)
        target_safe = np.maximum(target_v, 1e-16)
        fc1_safe = np.maximum(fc[m1], 1e-16)
        fc2_safe = np.maximum(fc[m2], 1e-16)
        loss1 = target_safe / fc1_safe - np.log(target_safe / fc1_safe) - 1
        loss2 = target_safe / fc2_safe - np.log(target_safe / fc2_safe) - 1
        # Cap extremes
        loss1 = np.minimum(loss1, 100.0)
        loss2 = np.minimum(loss2, 100.0)
        t_stat, p_val = dm_test(loss1, loss2, h=h)
        dm_results[f'{m1}_vs_{m2}'] = {
            't_stat': float(t_stat),
            'p_value': float(p_val),
            'harvey_pass': abs(t_stat) > 3.0
        }

    # Print summary
    print(f"    QLIKE:   ", {m: f"{v:.6f}" for m, v in qlike_scores.items()})
    print(f"    R²(OOS): ", {m: f"{v:.4f}" for m, v in r2_scores.items()})
    print(f"    Spearman:", {m: f"{v['rho']:.4f}" for m, v in spearman_scores.items()})
    for key, dm in dm_results.items():
        pass_str = "PASS" if dm['harvey_pass'] else "FAIL"
        print(f"    DM {key}: t={dm['t_stat']:.3f}, p={dm['p_value']:.4f} ({pass_str})")

    # QLIKE improvement of MF-GJR over GJR
    if 'GJR' in qlike_scores and 'MF-GJR' in qlike_scores:
        improvement = (qlike_scores['GJR'] - qlike_scores['MF-GJR']) / qlike_scores['GJR'] * 100
        print(f"    QLIKE improvement MF-GJR over GJR: {improvement:.2f}%")

    results_by_horizon[str(h)] = {
        'horizon': h,
        'n_valid': int(n_valid),
        'qlike': qlike_scores,
        'r2_oos': r2_scores,
        'spearman': spearman_scores,
        'dm_tests': dm_results,
        'qlike_improvement_mfgjr_vs_gjr': float(
            (qlike_scores['GJR'] - qlike_scores['MF-GJR']) / qlike_scores['GJR'] * 100
        ) if 'GJR' in qlike_scores and 'MF-GJR' in qlike_scores else None
    }

# ============================================================
# SECTION 6: CROSS-HORIZON SUMMARY
# ============================================================
print("\n[6] Cross-horizon summary...")

summary_table = []
for h in HORIZONS:
    h_str = str(h)
    if h_str not in results_by_horizon:
        continue
    r = results_by_horizon[h_str]
    row = {
        'horizon': h,
        'best_qlike': min(r['qlike'], key=r['qlike'].get),
        'best_r2': max(r['r2_oos'], key=r['r2_oos'].get),
        'mfgjr_qlike': r['qlike'].get('MF-GJR', None),
        'gjr_qlike': r['qlike'].get('GJR', None),
        'garch_qlike': r['qlike'].get('GARCH', None),
        'mfgjr_r2': r['r2_oos'].get('MF-GJR', None),
        'gjr_r2': r['r2_oos'].get('GJR', None),
        'garch_r2': r['r2_oos'].get('GARCH', None),
        'dm_mfgjr_vs_gjr_t': r['dm_tests'].get('MF-GJR_vs_GJR', {}).get('t_stat', None),
        'dm_mfgjr_vs_gjr_pass': r['dm_tests'].get('MF-GJR_vs_GJR', {}).get('harvey_pass', None),
        'qlike_improvement_pct': r.get('qlike_improvement_mfgjr_vs_gjr', None),
    }
    summary_table.append(row)
    print(f"  h={h}: Best QLIKE={row['best_qlike']}, "
          f"MF-GJR improvement={row['qlike_improvement_pct']:.2f}%, "
          f"DM t={row['dm_mfgjr_vs_gjr_t']:.3f} "
          f"({'PASS' if row['dm_mfgjr_vs_gjr_pass'] else 'FAIL'})")

# Check: Does VIX advantage grow with horizon?
if len(summary_table) >= 2:
    improvements = [r['qlike_improvement_pct'] for r in summary_table if r['qlike_improvement_pct'] is not None]
    if len(improvements) >= 2:
        if improvements[-1] > improvements[0]:
            trend = "VIX advantage GROWS with horizon (as hypothesized)"
        else:
            trend = "VIX advantage does NOT grow with horizon (hypothesis rejected)"
        print(f"\n  Trend: {trend}")

# ============================================================
# SECTION 7: VISUALIZATION
# ============================================================
print("\n[7] Creating charts...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K943: Multi-Horizon MF-GJR(VIX) Performance\n(SPY, OOS 2016-2025)',
             fontsize=14, fontweight='bold')

# Panel A: QLIKE across horizons (bar chart)
ax = axes[0, 0]
x_pos = np.arange(len(HORIZONS))
width = 0.25
colors = ['#4472C4', '#ED7D31', '#70AD47']
for i, m in enumerate(model_names):
    vals = [results_by_horizon[str(h)]['qlike'][m] for h in HORIZONS if str(h) in results_by_horizon]
    ax.bar(x_pos + i * width, vals, width, label=m, color=colors[i], alpha=0.85)
ax.set_xlabel('Forecast Horizon (days)')
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('(A) QLIKE by Horizon')
ax.set_xticks(x_pos + width)
ax.set_xticklabels([f'h={h}' for h in HORIZONS])
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

# Panel B: OOS R² across horizons
ax = axes[0, 1]
for i, m in enumerate(model_names):
    vals = [results_by_horizon[str(h)]['r2_oos'][m] for h in HORIZONS if str(h) in results_by_horizon]
    ax.bar(x_pos + i * width, vals, width, label=m, color=colors[i], alpha=0.85)
ax.set_xlabel('Forecast Horizon (days)')
ax.set_ylabel('OOS R²')
ax.set_title('(B) OOS R² by Horizon')
ax.set_xticks(x_pos + width)
ax.set_xticklabels([f'h={h}' for h in HORIZONS])
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

# Panel C: QLIKE improvement of MF-GJR over GJR
ax = axes[1, 0]
improvements_pct = []
dm_t_stats = []
for h in HORIZONS:
    h_str = str(h)
    if h_str in results_by_horizon:
        improvements_pct.append(results_by_horizon[h_str]['qlike_improvement_mfgjr_vs_gjr'])
        dm_t_stats.append(results_by_horizon[h_str]['dm_tests']['MF-GJR_vs_GJR']['t_stat'])
bars = ax.bar(x_pos, improvements_pct, 0.5, color='#70AD47', alpha=0.85)
ax.set_xlabel('Forecast Horizon (days)')
ax.set_ylabel('QLIKE Improvement (%)')
ax.set_title('(C) MF-GJR vs GJR: QLIKE Improvement')
ax.set_xticks(x_pos)
ax.set_xticklabels([f'h={h}' for h in HORIZONS])
# Add DM t-stat annotation
for i, (imp, t_s) in enumerate(zip(improvements_pct, dm_t_stats)):
    pass_str = "★" if abs(t_s) > 3.0 else ""
    ax.annotate(f't={t_s:.1f}{pass_str}',
                xy=(i, imp), xytext=(0, 5),
                textcoords='offset points', ha='center', fontsize=9)
ax.axhline(y=0, color='black', linewidth=0.5)
ax.grid(axis='y', alpha=0.3)

# Panel D: Spearman ρ across horizons
ax = axes[1, 1]
for i, m in enumerate(model_names):
    vals = [results_by_horizon[str(h)]['spearman'][m]['rho'] for h in HORIZONS if str(h) in results_by_horizon]
    ax.bar(x_pos + i * width, vals, width, label=m, color=colors[i], alpha=0.85)
ax.set_xlabel('Forecast Horizon (days)')
ax.set_ylabel('Spearman ρ')
ax.set_title('(D) Spearman Rank Correlation by Horizon')
ax.set_xticks(x_pos + width)
ax.set_xticklabels([f'h={h}' for h in HORIZONS])
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved: {CHART_PATH}")

# ============================================================
# SECTION 8: SAVE RESULTS
# ============================================================
print("\n[8] Saving results...")

elapsed_total = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Multi-Horizon MF-GJR(VIX) — Multi-step Forecasting Ability',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': float(elapsed_total),
    'config': {
        'asset': 'SPY',
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'horizons': HORIZONS,
        'n_refits': n_refits,
        'data_source': 'yfinance',
    },
    'diagnostics': diagnostics,
    'results_by_horizon': results_by_horizon,
    'summary_table': summary_table,
    'conclusion': {},
    'references': [
        'Engle, Ghysels & Sohn (2013) Stock market volatility and macroeconomic fundamentals, RES 95(3):776-797',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) Volatility forecast comparison using imperfect proxies, J Econometrics 160:246-256',
        'Harvey et al. (2016) Tests for forecast encompassing, JBES 34:92-104',
        'Bollerslev, Engle & Nelson (1994) ARCH models, Handbook of Econometrics vol 4',
    ]
}

# Build conclusion
if len(summary_table) >= 3:
    # Determine trend
    h1_imp = summary_table[0]['qlike_improvement_pct']
    h5_imp = summary_table[1]['qlike_improvement_pct']
    h22_imp = summary_table[2]['qlike_improvement_pct']

    h1_pass = summary_table[0]['dm_mfgjr_vs_gjr_pass']
    h5_pass = summary_table[1]['dm_mfgjr_vs_gjr_pass']
    h22_pass = summary_table[2]['dm_mfgjr_vs_gjr_pass']

    conclusion = {
        'vix_advantage_grows_with_horizon': h22_imp > h1_imp,
        'improvements': {
            'h1': f"{h1_imp:.2f}%",
            'h5': f"{h5_imp:.2f}%",
            'h22': f"{h22_imp:.2f}%",
        },
        'harvey_pass': {
            'h1': h1_pass,
            'h5': h5_pass,
            'h22': h22_pass,
        },
        'best_model_by_horizon': {
            'h1': summary_table[0]['best_qlike'],
            'h5': summary_table[1]['best_qlike'],
            'h22': summary_table[2]['best_qlike'],
        },
        'interpretation': (
            f"MF-GJR(VIX) improves over GJR by "
            f"{h1_imp:.2f}% (h=1), {h5_imp:.2f}% (h=5), {h22_imp:.2f}% (h=22). "
            f"VIX advantage {'grows' if h22_imp > h1_imp else 'does not grow'} with horizon. "
            f"Harvey PASS: h=1={h1_pass}, h=5={h5_pass}, h=22={h22_pass}."
        )
    }
    results['conclusion'] = conclusion

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved: {RESULTS_PATH}")

print(f"\nTotal runtime: {elapsed_total:.1f}s")
print("=" * 70)
print("K943 COMPLETE")
print("=" * 70)
