#!/usr/bin/env python3
"""
K1056b: A4f Tau-Alignment Fix Refit (Paper 9 Robustness Follow-up)
==================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  Codex 24h review of K1056 found an A4f recursion alignment issue:
  u_{t-1} was standardized with sqrt(tau_t) instead of sqrt(tau_{t-1}).
  This follow-up re-runs K1056 with corrected two-step state update:
    1. standardize r_{t-1} with tau_{t-1}
    2. update g_t
    3. combine sigma²_t = tau_t * g_t

Prior results:
  - K1056: 5/5 sub-period wins, full OOS DM t=-6.59, improvement=6.27%
  - K988/K988b/K994/K1024/K1033: Paper 9 A4f family using same recursion style

Research questions:
  1. Does the corrected tau alignment preserve the 5/5 directional result?
  2. How much do full-OOS, sub-period, and VIX-bucket magnitudes drift vs K1056?
  3. Does rolling 252-day dominance remain intact after the fix?
  4. Are all 45 theta1 refits still positive?

Method:
  - SPY adjusted close + VIX close, local snapshot 2005-2026
  - A4f: σ²_t = τ_t × g_t, τ = θ₀ + θ₁·VIX²_{t-1}, g_t = GJR with free ω
  - GJR-GARCH(1,1) benchmark
  - Rolling window = 2000, refit every 63 days
  - Evaluation: QLIKE on r² (Patton 2011), DM test per sub-period
  - 5 non-overlapping sub-periods (each ≥252 days)
  - VIX regime conditional analysis (VIX<15, 15-25, 25-35, >35)
  - θ₁ rolling evolution + explicit comparison to original K1056 results

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility.
    JBES 33(3):338-358.

Data: paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv (local snapshot).
Evaluation: QLIKE on r² (Patton 2011), DM test, Spearman rank.

Author: VolPred Research System
Date: 2026-06-06
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
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1056b"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1056b_results.json')
ORIGINAL_RESULTS_PATH = os.path.join(PROJECT_ROOT, 'experiments', 'k1056', 'k1056_results.json')
DATA_PATH = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data',
                         'spy_vix_qqq_eem_fez_2000-2026.csv')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2015-01-01'  # extended OOS to cover all 5 sub-periods
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit (matching K988)

# Sub-period definitions
SUB_PERIODS = {
    'P1_PreCOVID': ('2015-01-01', '2019-12-31'),
    'P2_COVID': ('2020-01-01', '2021-06-30'),
    'P3_PostCOVID': ('2021-07-01', '2022-12-31'),
    'P4_RateHike': ('2023-01-01', '2024-06-30'),
    'P5_Recent': ('2024-07-01', '2026-04-10'),
}

# VIX regime thresholds
VIX_REGIMES = {
    'Low_VIX_lt15': (0, 15),
    'Normal_VIX_15_25': (15, 25),
    'High_VIX_25_35': (25, 35),
    'Crisis_VIX_gt35': (35, 999),
}

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Tau-Alignment Fix Refit")
print("  Paper 9 Robustness follow-up — corrected tau recursion")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data from local snapshot...")
df_raw = pd.read_csv(DATA_PATH, parse_dates=['date'])
df_raw = df_raw.sort_values('date')
df_raw = df_raw[(df_raw['date'] >= DATA_START) & (df_raw['date'] <= DATA_END)]

prices = pd.Series(df_raw['spy_adj_close'].values, index=pd.to_datetime(df_raw['date']))
vix_close = pd.Series(df_raw['vix_close'].values, index=pd.to_datetime(df_raw['date']))

df = pd.DataFrame({'price': prices, 'VIX': vix_close}).dropna()
df['log_ret'] = np.log(df['price'] / df['price'].shift(1))
df = df.dropna()

n_total = len(df)
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_mask = dates >= OOS_START
n_oos = oos_mask.sum()
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

for name, (start, end) in SUB_PERIODS.items():
    mask = (dates >= start) & (dates <= end)
    sub_ret = ret[mask]
    sub_vix = vix[mask]
    n_sub = mask.sum()
    print(f"  {name}: n={n_sub}, mean_ret={np.mean(sub_ret)*252:.4f}, "
          f"std={np.std(sub_ret)*np.sqrt(252):.4f}, mean_VIX={np.mean(sub_vix):.1f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


@njit(cache=True)
def gjr_loglik(params, returns):
    """Standard GJR-GARCH(1,1) log-likelihood."""
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
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns, vix_vals):
    """
    Fit A4f: multiplicative GARCH-X with VIX², free omega.
    σ²_t = τ_t × g_t
    τ_t = max(θ₀ + θ₁ × VIX²_{t-1}, eps)
    g_t = ω_g + α × u²_{t-1} + γ × u²_{t-1} × I(u<0) + β × g_{t-1}
    u_t = r_t / √τ_t
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta_g = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta_g < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta_g
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
        ll = 0.0

        for t in range(1, n):
            tau_prev = tau[t-1]
            u_prev = returns[t-1] / np.sqrt(tau_prev)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta_g * g[t-1]
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
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
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


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")
print(f"  OOS start: {dates[oos_indices[0]].strftime('%Y-%m-%d')}")
print(f"  OOS end: {dates[oos_indices[-1]].strftime('%Y-%m-%d')}")

# Storage for forecasts
gjr_forecasts = np.full(n_oos_actual, np.nan)
a4f_forecasts = np.full(n_oos_actual, np.nan)
oos_r2 = np.full(n_oos_actual, np.nan)
oos_dates = dates[oos_indices]
oos_vix = vix[oos_indices]

# Track θ₁ evolution
theta1_history = []  # (date, theta1_value)

# State variables
gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None, 'tau_prev': None}

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            gjr_state['params'] = gjr_params
            # Reconstruct in-sample variance for initialization
            h = np.var(train_ret[:250])
            for i in range(1, len(train_ret)):
                omega, alpha, gamma, beta = gjr_params
                asym = gamma * train_ret[i-1]**2 if train_ret[i-1] < 0 else 0.0
                h = omega + alpha * train_ret[i-1]**2 + asym + beta * h
                h = max(h, 1e-10)
            gjr_state['h'] = h

        # A4f
        a4f_params = fit_a4f(train_ret, train_vix)
        if a4f_params is not None:
            a4f_state['params'] = a4f_params
            theta0, theta1, omega_g, alpha_a, gamma_a, beta_a = a4f_params

            # Record θ₁
            theta1_history.append({
                'date': dates[abs_idx].strftime('%Y-%m-%d'),
                'theta1': float(theta1),
                'theta0': float(theta0),
                'refit_idx': refit_count
            })

            # Reconstruct in-sample g for initialization
            n_train = len(train_ret)
            vix_lag_train = np.empty(n_train)
            vix_lag_train[0] = train_vix[0]
            vix_lag_train[1:] = train_vix[:-1]
            tau_train = np.maximum(theta0 + theta1 * vix_lag_train**2, 1e-16)

            persist = alpha_a + gamma_a / 2.0 + beta_a
            eg = omega_g / max(1.0 - persist, 1e-6)
            g = eg
            for i in range(1, n_train):
                tau_prev = tau_train[i-1]
                u_prev = train_ret[i-1] / np.sqrt(tau_prev)
                asym = gamma_a * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_a * u_prev**2 + asym + beta_a * g
                g = max(g, 1e-10)
            a4f_state['g'] = g
            # τ for the last training observation; used to standardize r_{t-1}
            a4f_state['tau_prev'] = np.maximum(theta0 + theta1 * train_vix[-1]**2, 1e-16)

    # --- GJR Forecast ---
    if gjr_state['params'] is not None and gjr_state['h'] is not None:
        params_g = gjr_state['params']
        h_prev = gjr_state['h']
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(params_g, h_prev, r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_state['h'] = h_new

    # --- A4f Forecast ---
    if a4f_state['params'] is not None and a4f_state['g'] is not None:
        theta0, theta1, omega_g, alpha_a, gamma_a, beta_a = a4f_state['params']
        # Step 1: standardize r_{t-1} using tau_{t-1}; no lookahead.
        tau_prev = a4f_state['tau_prev']
        r_prev = ret[abs_idx - 1]
        u_prev = r_prev / np.sqrt(tau_prev)
        asym = gamma_a * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_a * u_prev**2 + asym + beta_a * a4f_state['g']
        g_new = max(g_new, 1e-10)

        # Step 2: build tau_t from VIX_{t-1}, then combine sigma²_t = tau_t * g_t.
        vix_prev = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * vix_prev**2, 1e-16)
        a4f_forecasts[t_idx] = tau_t * g_new
        a4f_state['g'] = g_new
        a4f_state['tau_prev'] = tau_t

    oos_r2[t_idx] = r2[abs_idx]

elapsed = time.time() - START_TIME
print(f"  Forecasting complete: {refit_count} refits, {elapsed:.0f}s total")

# ============================================================
# SECTION 5: FULL OOS EVALUATION
# ============================================================
print("\n[5] Full OOS evaluation...")

valid = np.isfinite(gjr_forecasts) & np.isfinite(a4f_forecasts) & (oos_r2 > 0)
n_valid = valid.sum()
print(f"  Valid OOS observations: {n_valid}")

gjr_qlike = qlike(oos_r2[valid], gjr_forecasts[valid])
a4f_qlike = qlike(oos_r2[valid], a4f_forecasts[valid])
print(f"  GJR QLIKE:  {gjr_qlike:.6f}")
print(f"  A4f QLIKE:  {a4f_qlike:.6f}")
print(f"  Improvement: {(gjr_qlike - a4f_qlike) / abs(gjr_qlike) * 100:.3f}%")

gjr_losses = qlike_pointwise(oos_r2[valid], gjr_forecasts[valid])
a4f_losses = qlike_pointwise(oos_r2[valid], a4f_forecasts[valid])
dm_t_full, dm_p_full = dm_test(a4f_losses, gjr_losses)
print(f"  DM test (A4f vs GJR): t={dm_t_full:.3f}, p={dm_p_full:.6f}")
print(f"  Harvey |t|>3.0: {abs(dm_t_full) > 3.0}")

rho_gjr, p_gjr = spearman_corr(oos_r2[valid], gjr_forecasts[valid])
rho_a4f, p_a4f = spearman_corr(oos_r2[valid], a4f_forecasts[valid])
print(f"  Spearman: GJR={rho_gjr:.4f}, A4f={rho_a4f:.4f}")

# ============================================================
# SECTION 6: SUB-PERIOD ANALYSIS
# ============================================================
print("\n[6] Sub-period analysis...")

subperiod_results = {}

for name, (start, end) in SUB_PERIODS.items():
    mask = (oos_dates >= start) & (oos_dates <= end)
    mask_valid = mask & valid

    if mask_valid.sum() < 50:
        print(f"  {name}: SKIPPED (n={mask_valid.sum()} < 50)")
        continue

    sub_r2 = oos_r2[mask_valid]
    sub_gjr = gjr_forecasts[mask_valid]
    sub_a4f = a4f_forecasts[mask_valid]
    sub_vix = oos_vix[mask]
    n_sub = mask_valid.sum()

    sub_gjr_qlike = qlike(sub_r2, sub_gjr)
    sub_a4f_qlike = qlike(sub_r2, sub_a4f)
    improvement_pct = (sub_gjr_qlike - sub_a4f_qlike) / abs(sub_gjr_qlike) * 100

    sub_gjr_losses = qlike_pointwise(sub_r2, sub_gjr)
    sub_a4f_losses = qlike_pointwise(sub_r2, sub_a4f)
    sub_dm_t, sub_dm_p = dm_test(sub_a4f_losses, sub_gjr_losses)

    sub_rho_gjr, sub_p_gjr = spearman_corr(sub_r2, sub_gjr)
    sub_rho_a4f, sub_p_a4f = spearman_corr(sub_r2, sub_a4f)

    a4f_better = sub_a4f_qlike < sub_gjr_qlike

    result = {
        'n_obs': int(n_sub),
        'date_range': f"{start} to {end}",
        'mean_vix': float(np.mean(sub_vix)),
        'gjr_qlike': float(sub_gjr_qlike),
        'a4f_qlike': float(sub_a4f_qlike),
        'improvement_pct': float(improvement_pct),
        'a4f_better': bool(a4f_better),
        'dm_t': float(sub_dm_t),
        'dm_p': float(sub_dm_p),
        'harvey_significant': bool(abs(sub_dm_t) > 3.0),
        'direction': 'A4f_better' if sub_dm_t < 0 else 'GJR_better',
        'spearman_gjr': float(sub_rho_gjr),
        'spearman_a4f': float(sub_rho_a4f),
    }
    subperiod_results[name] = result

    sig_str = "***" if abs(sub_dm_t) > 3.0 else ("**" if abs(sub_dm_t) > 2.0 else "")
    print(f"  {name} (n={n_sub}, VIX={np.mean(sub_vix):.1f}):")
    print(f"    QLIKE: GJR={sub_gjr_qlike:.6f}, A4f={sub_a4f_qlike:.6f}, "
          f"improve={improvement_pct:+.3f}%")
    print(f"    DM t={sub_dm_t:.3f} {sig_str}, p={sub_dm_p:.4f}, "
          f"{'A4f better' if a4f_better else 'GJR better'}")
    print(f"    Spearman: GJR={sub_rho_gjr:.4f}, A4f={sub_rho_a4f:.4f}")

# Count how many sub-periods A4f wins
n_a4f_wins = sum(1 for r in subperiod_results.values() if r['a4f_better'])
n_periods = len(subperiod_results)
# Binomial test: if A4f is no better than GJR, P(winning all) = 0.5^n
binom_p = stats.binom.sf(n_a4f_wins - 1, n_periods, 0.5)
print(f"\n  A4f wins {n_a4f_wins}/{n_periods} sub-periods")
print(f"  Binomial test (H0: 50/50): p={binom_p:.4f}")

# ============================================================
# SECTION 7: VIX REGIME CONDITIONAL ANALYSIS
# ============================================================
print("\n[7] VIX regime conditional analysis...")

regime_results = {}

for regime_name, (vix_low, vix_high) in VIX_REGIMES.items():
    mask = (oos_vix >= vix_low) & (oos_vix < vix_high) & valid

    if mask.sum() < 30:
        print(f"  {regime_name}: SKIPPED (n={mask.sum()} < 30)")
        continue

    sub_r2 = oos_r2[mask]
    sub_gjr = gjr_forecasts[mask]
    sub_a4f = a4f_forecasts[mask]
    n_sub = mask.sum()

    sub_gjr_qlike = qlike(sub_r2, sub_gjr)
    sub_a4f_qlike = qlike(sub_r2, sub_a4f)
    improvement_pct = (sub_gjr_qlike - sub_a4f_qlike) / abs(sub_gjr_qlike) * 100

    sub_gjr_losses = qlike_pointwise(sub_r2, sub_gjr)
    sub_a4f_losses = qlike_pointwise(sub_r2, sub_a4f)
    sub_dm_t, sub_dm_p = dm_test(sub_a4f_losses, sub_gjr_losses)

    a4f_better = sub_a4f_qlike < sub_gjr_qlike

    result = {
        'n_obs': int(n_sub),
        'vix_range': f"{vix_low}-{vix_high}",
        'gjr_qlike': float(sub_gjr_qlike),
        'a4f_qlike': float(sub_a4f_qlike),
        'improvement_pct': float(improvement_pct),
        'a4f_better': bool(a4f_better),
        'dm_t': float(sub_dm_t),
        'dm_p': float(sub_dm_p),
        'harvey_significant': bool(abs(sub_dm_t) > 3.0),
        'direction': 'A4f_better' if sub_dm_t < 0 else 'GJR_better',
    }
    regime_results[regime_name] = result

    sig_str = "***" if abs(sub_dm_t) > 3.0 else ("**" if abs(sub_dm_t) > 2.0 else "")
    print(f"  {regime_name} (n={n_sub}):")
    print(f"    QLIKE: GJR={sub_gjr_qlike:.6f}, A4f={sub_a4f_qlike:.6f}, "
          f"improve={improvement_pct:+.3f}%")
    print(f"    DM t={sub_dm_t:.3f} {sig_str}")

# ============================================================
# SECTION 8: θ₁ EVOLUTION ANALYSIS
# ============================================================
print("\n[8] θ₁ evolution analysis...")

if len(theta1_history) > 0:
    theta1_vals = [h['theta1'] for h in theta1_history]
    theta1_dates = [h['date'] for h in theta1_history]
    theta1_mean = np.mean(theta1_vals)
    theta1_std = np.std(theta1_vals)
    theta1_cv = theta1_std / theta1_mean if theta1_mean > 0 else np.nan
    theta1_min = np.min(theta1_vals)
    theta1_max = np.max(theta1_vals)

    print(f"  θ₁ estimates: n={len(theta1_vals)}")
    print(f"  Mean: {theta1_mean:.8f}")
    print(f"  Std:  {theta1_std:.8f}")
    print(f"  CV:   {theta1_cv:.4f}")
    print(f"  Range: [{theta1_min:.8f}, {theta1_max:.8f}]")
    print(f"  All positive: {all(v > 0 for v in theta1_vals)}")

    theta1_summary = {
        'n_refits': len(theta1_vals),
        'mean': float(theta1_mean),
        'std': float(theta1_std),
        'cv': float(theta1_cv),
        'min': float(theta1_min),
        'max': float(theta1_max),
        'all_positive': bool(all(v > 0 for v in theta1_vals)),
        'history': theta1_history,
    }
else:
    theta1_summary = {'n_refits': 0, 'error': 'No theta1 values recorded'}

# ============================================================
# SECTION 9: ROLLING DM-STAT ANALYSIS
# ============================================================
print("\n[9] Rolling DM-stat analysis (252-day windows)...")

rolling_window = 252
rolling_dm = []

for i in range(rolling_window, n_valid):
    window_start = i - rolling_window
    window_gjr_losses = gjr_losses[window_start:i]
    window_a4f_losses = a4f_losses[window_start:i]
    dm_t_roll, _ = dm_test(window_a4f_losses, window_gjr_losses)
    date_str = oos_dates[valid][i - 1].strftime('%Y-%m-%d') if i - 1 < len(oos_dates[valid]) else 'N/A'
    rolling_dm.append({
        'idx': int(i),
        'date': date_str,
        'dm_t': float(dm_t_roll),
    })

if rolling_dm:
    dm_t_vals = [r['dm_t'] for r in rolling_dm]
    pct_negative = sum(1 for t in dm_t_vals if t < 0) / len(dm_t_vals) * 100
    pct_significant = sum(1 for t in dm_t_vals if abs(t) > 3.0) / len(dm_t_vals) * 100
    print(f"  Rolling windows: {len(rolling_dm)}")
    print(f"  % negative (A4f better): {pct_negative:.1f}%")
    print(f"  % Harvey significant: {pct_significant:.1f}%")
    print(f"  DM-t range: [{min(dm_t_vals):.3f}, {max(dm_t_vals):.3f}]")

# ============================================================
# SECTION 10: PLOTS
# ============================================================
print("\n[10] Generating plots...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Plot 1: Sub-period DM t-stats ---
fig, ax = plt.subplots(figsize=(10, 6))
period_names = list(subperiod_results.keys())
dm_t_values = [subperiod_results[n]['dm_t'] for n in period_names]
colors = ['#2ca02c' if t < -3.0 else ('#7bc67b' if t < 0 else '#e74c3c') for t in dm_t_values]
bars = ax.bar(range(len(period_names)), dm_t_values, color=colors, edgecolor='black', linewidth=0.8)
ax.axhline(y=0, color='black', linewidth=0.5)
ax.axhline(y=-3.0, color='red', linewidth=1.5, linestyle='--', label='Harvey |t|=3.0')
ax.axhline(y=3.0, color='red', linewidth=1.5, linestyle='--')
ax.set_xticks(range(len(period_names)))
short_names = [n.replace('P1_PreCOVID', 'Pre-COVID\n2015-2019')
                .replace('P2_COVID', 'COVID\n2020-2021H1')
                .replace('P3_PostCOVID', 'Post-COVID\n2021H2-2022')
                .replace('P4_RateHike', 'Rate Hike\n2023-2024H1')
                .replace('P5_Recent', 'Recent\n2024H2-2026')
               for n in period_names]
ax.set_xticklabels(short_names, fontsize=10)
ax.set_ylabel('DM t-statistic', fontsize=12)
ax.set_title('K1056: A4f vs GJR — DM Test by Sub-Period\n(Negative = A4f better)', fontsize=13)
ax.legend(fontsize=10)
for i, (bar, t_val) in enumerate(zip(bars, dm_t_values)):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + (0.1 if t_val >= 0 else -0.3),
            f't={t_val:.2f}', ha='center', va='bottom' if t_val >= 0 else 'top', fontsize=10, fontweight='bold')
plt.tight_layout()
plot1_path = os.path.join(SCRIPT_DIR, 'k1056b_subperiod_dm.png')
plt.savefig(plot1_path, dpi=150)
plt.close()
print(f"  Saved: {plot1_path}")

# --- Plot 2: θ₁ Evolution ---
if len(theta1_history) > 1:
    fig, ax = plt.subplots(figsize=(12, 5))
    t1_dates_dt = pd.to_datetime([h['date'] for h in theta1_history])
    t1_values = [h['theta1'] for h in theta1_history]
    ax.plot(t1_dates_dt, t1_values, 'b-o', markersize=3, linewidth=1.2, label='θ₁ (VIX² coeff)')
    ax.axhline(y=theta1_mean, color='red', linewidth=1.5, linestyle='--',
               label=f'Mean = {theta1_mean:.2e}')
    ax.fill_between(t1_dates_dt, theta1_mean - 2*theta1_std, theta1_mean + 2*theta1_std,
                    alpha=0.15, color='red', label=f'±2σ (CV={theta1_cv:.3f})')
    # Add sub-period boundaries
    for name, (start, end) in SUB_PERIODS.items():
        ax.axvline(x=pd.Timestamp(start), color='gray', linewidth=0.8, linestyle=':', alpha=0.6)
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('θ₁ (VIX² coefficient)', fontsize=11)
    ax.set_title('K1056: A4f θ₁ Parameter Evolution Over Time\n(Rolling refit, w=2000, refit every 63 days)',
                 fontsize=13)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    plt.tight_layout()
    plot2_path = os.path.join(SCRIPT_DIR, 'k1056b_theta1_evolution.png')
    plt.savefig(plot2_path, dpi=150)
    plt.close()
    print(f"  Saved: {plot2_path}")

# --- Plot 3: QLIKE Improvement by Sub-Period ---
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

# Left: improvement %
improvements = [subperiod_results[n]['improvement_pct'] for n in period_names]
colors_imp = ['#2ca02c' if v > 0 else '#e74c3c' for v in improvements]
bars1 = ax1.bar(range(len(period_names)), improvements, color=colors_imp,
                edgecolor='black', linewidth=0.8)
ax1.set_xticks(range(len(period_names)))
ax1.set_xticklabels(short_names, fontsize=9)
ax1.set_ylabel('QLIKE Improvement (%)', fontsize=11)
ax1.set_title('QLIKE Improvement (positive = A4f better)', fontsize=12)
ax1.axhline(y=0, color='black', linewidth=0.5)
for i, (bar, v) in enumerate(zip(bars1, improvements)):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
             f'{v:+.2f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')

# Right: VIX regime analysis
if regime_results:
    regime_names_sorted = ['Low_VIX_lt15', 'Normal_VIX_15_25', 'High_VIX_25_35', 'Crisis_VIX_gt35']
    regime_names_plot = [n for n in regime_names_sorted if n in regime_results]
    regime_imp = [regime_results[n]['improvement_pct'] for n in regime_names_plot]
    regime_labels = [n.replace('Low_VIX_lt15', 'VIX<15')
                      .replace('Normal_VIX_15_25', '15≤VIX<25')
                      .replace('High_VIX_25_35', '25≤VIX<35')
                      .replace('Crisis_VIX_gt35', 'VIX≥35')
                     for n in regime_names_plot]
    colors_reg = ['#2ca02c' if v > 0 else '#e74c3c' for v in regime_imp]
    bars2 = ax2.bar(range(len(regime_names_plot)), regime_imp, color=colors_reg,
                    edgecolor='black', linewidth=0.8)
    ax2.set_xticks(range(len(regime_names_plot)))
    ax2.set_xticklabels(regime_labels, fontsize=10)
    ax2.set_ylabel('QLIKE Improvement (%)', fontsize=11)
    ax2.set_title('QLIKE Improvement by VIX Regime', fontsize=12)
    ax2.axhline(y=0, color='black', linewidth=0.5)
    for i, (bar, v) in enumerate(zip(bars2, regime_imp)):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                 f'{v:+.2f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')

plt.suptitle('K1056: A4f vs GJR — QLIKE Improvement Analysis', fontsize=14, y=1.02)
plt.tight_layout()
plot3_path = os.path.join(SCRIPT_DIR, 'k1056b_qlike_improvement.png')
plt.savefig(plot3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot3_path}")

# --- Plot 4: Rolling DM-stat ---
if rolling_dm:
    fig, ax = plt.subplots(figsize=(12, 5))
    roll_dates = pd.to_datetime([r['date'] for r in rolling_dm])
    roll_dm_vals = [r['dm_t'] for r in rolling_dm]
    ax.plot(roll_dates, roll_dm_vals, 'b-', linewidth=0.8, alpha=0.8, label='Rolling DM t-stat (252d)')
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.axhline(y=-3.0, color='red', linewidth=1.5, linestyle='--', label='Harvey |t|=3.0')
    ax.axhline(y=3.0, color='red', linewidth=1.5, linestyle='--')
    ax.fill_between(roll_dates, -3.0, 3.0, alpha=0.05, color='gray')
    # Sub-period boundaries
    for name, (start, end) in SUB_PERIODS.items():
        ax.axvline(x=pd.Timestamp(start), color='gray', linewidth=0.8, linestyle=':', alpha=0.6)
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('DM t-statistic', fontsize=11)
    ax.set_title('K1056: Rolling DM Test (A4f vs GJR, 252-day window)\n'
                 '(Negative = A4f better)', fontsize=13)
    ax.legend(fontsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    plt.tight_layout()
    plot4_path = os.path.join(SCRIPT_DIR, 'k1056b_rolling_dm.png')
    plt.savefig(plot4_path, dpi=150)
    plt.close()
    print(f"  Saved: {plot4_path}")

# ============================================================
# SECTION 11: SAVE RESULTS
# ============================================================
print("\n[11] Saving results...")

results = {
    'experiment_id': EXPERIMENT_ID,
    'description': 'K1056 rerun with corrected tau_{t-1} alignment in A4f recursion',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(n_total),
    'oos_start': OOS_START,
    'n_oos': int(n_oos_actual),
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'random_seed': 42,
    'references': [
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
        'Patton (2011). J Econometrics 160:246-256.',
        'Harvey et al. (2016). t > 3.0 threshold.',
        'Conrad & Loch (2015). JBES 33(3):338-358.',
    ],
    'full_oos': {
        'gjr_qlike': float(gjr_qlike),
        'a4f_qlike': float(a4f_qlike),
        'improvement_pct': float((gjr_qlike - a4f_qlike) / abs(gjr_qlike) * 100),
        'dm_t': float(dm_t_full),
        'dm_p': float(dm_p_full),
        'harvey_significant': bool(abs(dm_t_full) > 3.0),
        'spearman_gjr': float(rho_gjr),
        'spearman_a4f': float(rho_a4f),
        'n_valid': int(n_valid),
    },
    'sub_periods': subperiod_results,
    'sub_period_summary': {
        'n_periods': n_periods,
        'n_a4f_wins': n_a4f_wins,
        'binomial_p': float(binom_p),
        'all_periods_a4f_better': n_a4f_wins == n_periods,
        'n_harvey_significant': sum(1 for r in subperiod_results.values() if r['harvey_significant']),
    },
    'vix_regimes': regime_results,
    'theta1_evolution': theta1_summary,
    'rolling_dm': {
        'window': rolling_window,
        'n_windows': len(rolling_dm),
        'pct_a4f_better': float(pct_negative) if rolling_dm else None,
        'pct_harvey_significant': float(pct_significant) if rolling_dm else None,
        'dm_t_range': [float(min(dm_t_vals)), float(max(dm_t_vals))] if rolling_dm else None,
        # Store sparse: every 10th entry to save space
        'samples': [rolling_dm[i] for i in range(0, len(rolling_dm), 10)],
    },
    'plots': [
        'k1056b_subperiod_dm.png',
        'k1056b_theta1_evolution.png',
        'k1056b_qlike_improvement.png',
        'k1056b_rolling_dm.png',
    ],
    'conclusions': {},  # Filled below
    'elapsed_seconds': float(time.time() - START_TIME),
}

if os.path.exists(ORIGINAL_RESULTS_PATH):
    with open(ORIGINAL_RESULTS_PATH, 'r') as f:
        original = json.load(f)

    subperiod_drift = {}
    for name, current in subperiod_results.items():
        baseline = original['sub_periods'].get(name, {})
        subperiod_drift[name] = {
            'improvement_pct_old': baseline.get('improvement_pct'),
            'improvement_pct_new': current['improvement_pct'],
            'improvement_pct_delta': (
                current['improvement_pct'] - baseline.get('improvement_pct')
                if baseline.get('improvement_pct') is not None else None
            ),
            'dm_t_old': baseline.get('dm_t'),
            'dm_t_new': current['dm_t'],
            'dm_t_delta': (
                current['dm_t'] - baseline.get('dm_t')
                if baseline.get('dm_t') is not None else None
            ),
            'direction_unchanged': current['a4f_better'] == baseline.get('a4f_better'),
        }

    regime_drift = {}
    for name, current in regime_results.items():
        baseline = original['vix_regimes'].get(name, {})
        regime_drift[name] = {
            'improvement_pct_old': baseline.get('improvement_pct'),
            'improvement_pct_new': current['improvement_pct'],
            'improvement_pct_delta': (
                current['improvement_pct'] - baseline.get('improvement_pct')
                if baseline.get('improvement_pct') is not None else None
            ),
            'direction_unchanged': current['a4f_better'] == baseline.get('a4f_better'),
        }

    results['comparison_to_k1056'] = {
        'full_oos': {
            'n_valid_old': original['full_oos']['n_valid'],
            'n_valid_new': int(n_valid),
            'improvement_pct_old': original['full_oos']['improvement_pct'],
            'improvement_pct_new': results['full_oos']['improvement_pct'],
            'improvement_pct_delta': results['full_oos']['improvement_pct'] - original['full_oos']['improvement_pct'],
            'dm_t_old': original['full_oos']['dm_t'],
            'dm_t_new': dm_t_full,
            'dm_t_delta': dm_t_full - original['full_oos']['dm_t'],
        },
        'subperiods': subperiod_drift,
        'vix_regimes': regime_drift,
        'rolling_dm': {
            'pct_a4f_better_old': original['rolling_dm']['pct_a4f_better'],
            'pct_a4f_better_new': pct_negative if rolling_dm else None,
            'max_dm_t_old': original['rolling_dm']['dm_t_range'][1],
            'max_dm_t_new': max(dm_t_vals) if rolling_dm else None,
        },
    }

# Summary conclusions
conclusions = []

if n_a4f_wins == n_periods:
    conclusions.append(f"A4f wins ALL {n_periods}/{n_periods} sub-periods — advantage is universal, not driven by any single period")
elif n_a4f_wins >= n_periods - 1:
    conclusions.append(f"A4f wins {n_a4f_wins}/{n_periods} sub-periods — advantage is highly robust")
else:
    conclusions.append(f"A4f wins {n_a4f_wins}/{n_periods} sub-periods — mixed stability")

n_sig = sum(1 for r in subperiod_results.values() if r['harvey_significant'])
if n_sig > 0:
    conclusions.append(f"{n_sig}/{n_periods} sub-periods individually Harvey-significant (|t|>3.0)")
else:
    conclusions.append(f"No individual sub-period reaches Harvey |t|>3.0 (expected: sub-periods have ~300-500 obs, limited power)")

if binom_p < 0.05:
    conclusions.append(f"Binomial test significant (p={binom_p:.4f}): winning {n_a4f_wins}/{n_periods} is unlikely by chance")

if len(theta1_history) > 0 and theta1_cv < 0.5:
    conclusions.append(f"θ₁ is stable: CV={theta1_cv:.3f}, all positive={all(v > 0 for v in theta1_vals)}")
elif len(theta1_history) > 0:
    conclusions.append(f"θ₁ shows moderate variation: CV={theta1_cv:.3f}")

if rolling_dm and pct_negative > 70:
    conclusions.append(f"Rolling DM: A4f better in {pct_negative:.0f}% of 252-day windows")

results['conclusions'] = conclusions

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved: {RESULTS_PATH}")

# ============================================================
# SECTION 12: SUMMARY
# ============================================================
elapsed = time.time() - START_TIME
print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID}: SUMMARY")
print("=" * 70)
print(f"\nFull OOS: DM t={dm_t_full:.3f}, QLIKE improvement={results['full_oos']['improvement_pct']:.3f}%")
print(f"\nSub-period results:")
for name in period_names:
    r = subperiod_results[name]
    sig = "***" if r['harvey_significant'] else ""
    print(f"  {name}: improve={r['improvement_pct']:+.3f}%, DM t={r['dm_t']:.3f} {sig}")
print(f"\nA4f wins: {n_a4f_wins}/{n_periods} (binomial p={binom_p:.4f})")
print(f"θ₁ stability: CV={theta1_cv:.4f}" if len(theta1_history) > 0 else "θ₁: no data")
print(f"\nConclusions:")
for c in conclusions:
    print(f"  - {c}")
print(f"\nTotal time: {elapsed:.0f}s")
