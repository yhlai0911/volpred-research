#!/usr/bin/env python3
"""
K1075: A4f Extended History — 2007-2026 Stress Test Including 2008 GFC
======================================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation:
  K988 validated A4f (VIX^2 with free omega) over 2019-2026 (7yr, DM t=4.48).
  K1056 extended to 2015-2026 (5 sub-periods, all won vs GJR).
  GAP: Never tested on pre-2015 data — most importantly the 2008 GFC.

  If A4f survives 2008-09 GFC (VIX=80), the Paper 9 robustness argument
  becomes near-bulletproof. If it breaks down, we must acknowledge
  regime-dependence and adapt the paper.

Design:
  - Three non-overlapping OOS windows (2007-2012, 2013-2018, 2019-2026)
  - Rolling-window GARCH with 2000-day training, 63-day refit
  - Two models only: GJR baseline vs A4f (τ=θ₀+θ₁·VIX²_{t-1}, g=GJR, free ω)
  - Crisis sub-period analysis: GFC, Euro, COVID, 2022 Bear
  - VIX bucket analysis: Low/Normal/High/Extreme/Crisis

Hypotheses:
  H1: Extended OOS 2007-2026 A4f vs GJR DM still Harvey-PASS (|t|>3)
  H2: 2008-09 GFC sub-period A4f still improves over GJR
  H3: 2011 Euro crisis sub-period A4f still improves
  H4: A4f does NOT break down at extreme VIX (>60)

Data: yfinance SPY + ^VIX 2000-01-01 ~ 2026-04-10
Evaluation: QLIKE on r² (Patton 2011), DM test (Harvey 2016)

References:
  - Engle et al. (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - Hansen & Lunde (2005). Consistent ranking.

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1075
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
EXPERIMENT_ID = "K1075"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1075_results.json')

# Configuration
DATA_START = '2000-01-01'  # Need pre-history for 2000-day window before 2007
DATA_END = '2026-04-11'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly

# Three non-overlapping OOS windows
OOS_WINDOWS = [
    ('Early_Crisis', '2007-01-01', '2012-12-31'),   # GFC + Euro
    ('Middle_Recovery', '2013-01-01', '2018-12-31'),  # Taper tantrum + low vol
    ('Late_COVID', '2019-01-01', '2026-04-11'),       # COVID + Rate Hike (K988 OOS)
]

# Crisis sub-periods within OOS
CRISIS_PERIODS = [
    ('GFC', '2008-01-01', '2009-12-31'),
    ('Euro_Crisis', '2011-06-01', '2012-06-30'),
    ('COVID_Crash', '2020-02-01', '2020-06-30'),
    ('Bear_2022', '2022-01-01', '2022-12-31'),
]

# VIX buckets
VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Extended History Stress Test (2007-2026)")
print(f"  3 OOS windows, 4 crisis sub-periods, 5 VIX buckets")
print(f"  Only 2 models: GJR vs A4f (VIX^2 free omega)")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Adj Close'].copy() if 'Adj Close' in raw.columns else raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

n_total = len(df)
print(f"  Full data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS (full and per-OOS)
# ============================================================
print("\n[2] Diagnostics...")
print(f"  Full sample:")
print(f"    Return mean (ann): {np.mean(ret)*252:.4f}")
print(f"    Return std (ann): {np.std(ret)*np.sqrt(252):.4f}")
print(f"    Return skew: {stats.skew(ret):.3f}")
print(f"    Return kurt: {stats.kurtosis(ret):.3f}")
print(f"    VIX mean: {np.mean(vix):.2f}, max: {np.max(vix):.2f}")
print(f"    Date of VIX max: {dates[np.argmax(vix)].strftime('%Y-%m-%d')}")

for name, start, end in OOS_WINDOWS:
    mask = (dates >= start) & (dates <= end)
    n_w = mask.sum()
    vix_w = vix[mask]
    ret_w = ret[mask]
    print(f"  {name} ({start} to {end}): n={n_w}, VIX max={np.max(vix_w):.1f}, "
          f"ret std={np.std(ret_w)*np.sqrt(252):.3f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) Benchmark ---
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
    converged = False
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
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f: Multiplicative GARCH-X with VIX^2 and free omega ---
def fit_a4f(returns, vix_vals):
    """
    A4f specification (K988 winner):
      tau_t = max(theta0 + theta1 * VIX_{t-1}^2, eps)
      g_t = omega_g + alpha * u_{t-1}^2 + gamma * u_{t-1}^2 * I(u_{t-1}<0) + beta * g_{t-1}
      u_{t-1} = r_{t-1} / sqrt(tau_t)    [Engle 2013 logic: denom = tau_t]
      sigma^2_t = tau_t * g_t
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix_lag_sq = vix_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params

        # Basic constraints
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)

        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)  # E(g) at stationary mean
        ll = 0.0

        for t in range(1, n):
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

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag_sq) + 1e-8

    # Multiple starting points
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),    # theta0
        (1e-10, 1e-2),    # theta1 (positive for VIX relation)
        (1e-6, 1.0),      # omega_g
        (1e-4, 0.3),      # alpha
        (1e-4, 0.3),      # gamma
        (0.5, 0.999),     # beta
    ]

    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue

    return best_params, converged


def compute_tau_a4f(params, vix_lag_val):
    """Compute tau given A4f parameters and lagged VIX."""
    theta0, theta1 = params[0], params[1]
    return max(theta0 + theta1 * vix_lag_val**2, 1e-16)


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING (loop per OOS window)
# ============================================================
print("\n[4] Out-of-sample forecasting (3 windows)...")

# Build full forecasting arrays (all OOS observations across all windows)
# We compute all OOS indices (union) and loop linearly for efficiency
oos_full_mask = np.zeros(n_total, dtype=bool)
window_tags = np.empty(n_total, dtype=object)
for name, start, end in OOS_WINDOWS:
    m = (dates >= start) & (dates <= end)
    oos_full_mask |= m
    for idx in np.where(m)[0]:
        window_tags[idx] = name

oos_indices = np.where(oos_full_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  Total OOS observations (union): {n_oos_actual}")

# Verify we have enough history for each OOS start
for name, start, end in OOS_WINDOWS:
    start_idx = np.where(dates >= start)[0][0]
    print(f"    {name}: start_idx={start_idx}, window_required={WINDOW}, "
          f"sufficient={'YES' if start_idx >= WINDOW else 'NO'}")

# Forecasts storage
gjr_forecasts = np.full(n_oos_actual, np.nan)
a4f_forecasts = np.full(n_oos_actual, np.nan)

# Convergence tracking per refit
refit_log = []  # list of dicts: {date, window, gjr_conv, a4f_conv, theta1, ...}

# State
gjr_h = None
gjr_params = None
a4f_g = None
a4f_tau_prev = None
a4f_params = None

# Track previous window to force refit at window boundary
prev_window = None
refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    current_window = window_tags[abs_idx]

    # Refit trigger: first obs OR at each REFIT_EVERY boundary within window
    # OR when window transitions (to avoid cross-contamination)
    if t_idx == 0 or current_window != prev_window:
        need_refit = True
    else:
        # Count how many days into this window
        window_start = next(s for n, s, e in OOS_WINDOWS if n == current_window)
        window_start_idx = np.where(dates >= window_start)[0][0]
        days_in_window = abs_idx - window_start_idx
        need_refit = (days_in_window % REFIT_EVERY == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR fit
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_params = gjr_p
            # Initialize h using training recursion
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h
        else:
            gjr_conv = False

        # A4f fit
        a4f_p, a4f_conv = fit_a4f(train_ret, train_vix)
        if a4f_p is not None:
            a4f_params = a4f_p
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_p
            # Initialize g using training recursion
            vix_lag_tr = np.empty(len(train_vix))
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            tau_tr = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)
            persist = alpha_p + gamma_p / 2.0 + beta_p
            g = omega_g / (1.0 - persist)
            for i in range(1, len(train_ret)):
                u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)
            a4f_g = g
            a4f_tau_prev = tau_tr[-1]
        else:
            a4f_conv = False

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            'gjr_conv': bool(gjr_conv),
            'a4f_conv': bool(a4f_conv),
            'a4f_theta0': float(a4f_params[0]) if a4f_params is not None else None,
            'a4f_theta1': float(a4f_params[1]) if a4f_params is not None else None,
            'a4f_omega': float(a4f_params[2]) if a4f_params is not None else None,
            'a4f_persist': float(a4f_params[3] + a4f_params[4]/2 + a4f_params[5])
                           if a4f_params is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # Generate forecasts for day abs_idx

    # GJR forecast
    if gjr_params is not None:
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_h = h_new

    # A4f forecast
    if a4f_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)

        r_prev = ret[abs_idx - 1]
        # Engle 2013 logic: denom = tau_t (predetermined)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
        g_new = max(g_new, 1e-10)

        a4f_forecasts[t_idx] = tau_t * g_new
        a4f_g = g_new
        a4f_tau_prev = tau_t

    prev_window = current_window

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_r2 = r2[oos_indices]
oos_dates = dates[oos_indices]
oos_vix = vix[oos_indices]
oos_window_tags = np.array([window_tags[i] for i in oos_indices])

# Valid mask: both models have valid forecast
both_valid = (~np.isnan(gjr_forecasts) & (gjr_forecasts > 0) &
              ~np.isnan(a4f_forecasts) & (a4f_forecasts > 0))

n_both = both_valid.sum()
print(f"  Valid joint observations: {n_both}/{n_oos_actual}")


def qlike_loss(fc, r2_vals):
    """Pointwise QLIKE loss."""
    return np.log(fc) + r2_vals / fc


def hac_dm_test(d_array):
    """Newey-West HAC DM test."""
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d_array)
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = np.var(d_array, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci_mean_diff(arr, n_boot=1000, seed=42):
    """Stationary bootstrap CI for mean of differences."""
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        # Moving block bootstrap
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


results = {'metadata': {}, 'full_oos': {}, 'per_window': {},
           'crisis_subperiods': {}, 'vix_buckets': {}, 'refit_log': refit_log}

# --- Full OOS (union) ---
if n_both > 0:
    fc_g = gjr_forecasts[both_valid]
    fc_a = a4f_forecasts[both_valid]
    r2_v = oos_r2[both_valid]

    ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
    ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))

    loss_g = qlike_loss(fc_g, r2_v)
    loss_a = qlike_loss(fc_a, r2_v)
    d = loss_g - loss_a  # positive => A4f better

    dm_t, dm_p, T = hac_dm_test(d)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(d, n_boot=1000)

    rho_g, _ = stats.spearmanr(fc_g, r2_v)
    rho_a, _ = stats.spearmanr(fc_a, r2_v)

    results['full_oos'] = {
        'n': int(n_both),
        'qlike_gjr': ql_g,
        'qlike_a4f': ql_a,
        'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
        'dm_t': dm_t,
        'dm_p': dm_p,
        'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
        'spearman_gjr': float(rho_g),
        'spearman_a4f': float(rho_a),
        'bootstrap_ci_95': [ci_lo, ci_hi],
    }

    print(f"\n  FULL OOS (2007-2026, n={n_both}):")
    print(f"    QLIKE GJR: {ql_g:.6f}")
    print(f"    QLIKE A4f: {ql_a:.6f} ({(ql_a-ql_g)/abs(ql_g)*100:+.2f}%)")
    print(f"    DM t: {dm_t:+.3f} (p={dm_p:.4f}) Harvey-PASS: {abs(dm_t) > 3.0}")

# --- Per OOS window ---
print("\n  Per-window results:")
print(f"  {'Window':<20} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
for name, start, end in OOS_WINDOWS:
    mask = (oos_window_tags == name) & both_valid
    n_w = mask.sum()
    if n_w < 30:
        continue

    fc_g = gjr_forecasts[mask]
    fc_a = a4f_forecasts[mask]
    r2_v = oos_r2[mask]

    ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
    ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))

    loss_g = qlike_loss(fc_g, r2_v)
    loss_a = qlike_loss(fc_a, r2_v)
    d = loss_g - loss_a

    dm_t, dm_p, _ = hac_dm_test(d)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(d, n_boot=1000)

    rho_g, _ = stats.spearmanr(fc_g, r2_v)
    rho_a, _ = stats.spearmanr(fc_a, r2_v)

    harvey = abs(dm_t) > 3.0 if np.isfinite(dm_t) else False
    print(f"  {name:<20} {n_w:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
          f"{(ql_a-ql_g)/abs(ql_g)*100:>+7.2f}% {dm_t:>+8.3f} {'PASS' if harvey else 'FAIL':>8}")

    results['per_window'][name] = {
        'start': start, 'end': end, 'n': int(n_w),
        'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
        'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
        'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
        'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
        'harvey_pass': bool(harvey),
        'spearman_gjr': float(rho_g),
        'spearman_a4f': float(rho_a),
        'bootstrap_ci_95': [ci_lo, ci_hi],
    }

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods:")
print(f"  {'Crisis':<15} {'Dates':<25} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
for cname, cstart, cend in CRISIS_PERIODS:
    # Apply to OOS arrays
    c_mask_full = (oos_dates >= cstart) & (oos_dates <= cend)
    mask = c_mask_full & both_valid
    n_c = mask.sum()
    if n_c < 30:
        print(f"  {cname:<15} {cstart}/{cend} insufficient (n={n_c})")
        continue

    fc_g = gjr_forecasts[mask]
    fc_a = a4f_forecasts[mask]
    r2_v = oos_r2[mask]
    vix_v = oos_vix[mask]

    ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
    ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))

    loss_g = qlike_loss(fc_g, r2_v)
    loss_a = qlike_loss(fc_a, r2_v)
    d = loss_g - loss_a

    dm_t, dm_p, _ = hac_dm_test(d)

    # Get theta1 during crisis (average of refits within crisis)
    crisis_refits = [r for r in refit_log
                     if cstart <= r['date'] <= cend and r.get('a4f_theta1') is not None]
    mean_theta1 = (np.mean([r['a4f_theta1'] for r in crisis_refits])
                   if crisis_refits else None)

    harvey = abs(dm_t) > 3.0 if np.isfinite(dm_t) else False
    print(f"  {cname:<15} {cstart[:10]}-{cend[:10]} {n_c:>6} "
          f"{ql_g:>10.5f} {ql_a:>10.5f} {(ql_a-ql_g)/abs(ql_g)*100:>+7.2f}% {dm_t:>+8.3f}")

    results['crisis_subperiods'][cname] = {
        'start': cstart, 'end': cend, 'n': int(n_c),
        'vix_mean': float(np.mean(vix_v)), 'vix_max': float(np.max(vix_v)),
        'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
        'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
        'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
        'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
        'harvey_pass': bool(harvey),
        'mean_theta1': float(mean_theta1) if mean_theta1 is not None else None,
    }

# --- VIX buckets ---
print("\n  VIX bucket analysis:")
print(f"  {'Bucket':<12} {'Range':<15} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
for bname, bmin, bmax in VIX_BUCKETS:
    # Use lagged VIX (what the model sees)
    oos_vix_lag = np.empty(n_oos_actual)
    for i, idx in enumerate(oos_indices):
        oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]

    mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax) & both_valid
    n_b = mask.sum()
    if n_b < 20:
        print(f"  {bname:<12} [{bmin},{bmax}) insufficient (n={n_b})")
        results['vix_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue

    fc_g = gjr_forecasts[mask]
    fc_a = a4f_forecasts[mask]
    r2_v = oos_r2[mask]

    ql_g = float(np.mean(qlike_loss(fc_g, r2_v)))
    ql_a = float(np.mean(qlike_loss(fc_a, r2_v)))

    loss_g = qlike_loss(fc_g, r2_v)
    loss_a = qlike_loss(fc_a, r2_v)
    d = loss_g - loss_a

    dm_t, dm_p, _ = hac_dm_test(d)

    harvey = abs(dm_t) > 3.0 if np.isfinite(dm_t) else False
    print(f"  {bname:<12} [{bmin},{bmax})     {n_b:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
          f"{(ql_a-ql_g)/abs(ql_g)*100:>+7.2f}% {dm_t:>+8.3f}")

    results['vix_buckets'][bname] = {
        'range': [bmin, bmax], 'n': int(n_b),
        'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
        'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
        'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
        'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
        'harvey_pass': bool(harvey),
    }

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)

# H1: Full OOS DM Harvey-PASS
full_dm = results['full_oos'].get('dm_t')
h1_verdict = 'PASS' if full_dm is not None and abs(full_dm) > 3.0 and full_dm > 0 else 'FAIL'
print(f"  H1 (Full OOS A4f > GJR, DM t>3): {h1_verdict} (t={full_dm:+.3f})" if full_dm else "  H1: N/A")

# H2: GFC sub-period A4f still improves
gfc = results['crisis_subperiods'].get('GFC', {})
gfc_diff = gfc.get('qlike_diff_pct')
gfc_dm = gfc.get('dm_t')
h2_verdict = ('PASS' if gfc_diff is not None and gfc_diff < 0
              else 'FAIL')
print(f"  H2 (GFC A4f improves): {h2_verdict} "
      f"(QLIKE diff={gfc_diff:+.2f}%, DM t={gfc_dm:+.3f})" if gfc_diff is not None else "  H2: N/A")

# H3: Euro crisis sub-period
euro = results['crisis_subperiods'].get('Euro_Crisis', {})
euro_diff = euro.get('qlike_diff_pct')
euro_dm = euro.get('dm_t')
h3_verdict = 'PASS' if euro_diff is not None and euro_diff < 0 else 'FAIL'
print(f"  H3 (Euro Crisis A4f improves): {h3_verdict} "
      f"(QLIKE diff={euro_diff:+.2f}%, DM t={euro_dm:+.3f})" if euro_diff is not None else "  H3: N/A")

# H4: A4f does not break down at extreme VIX
crisis_bucket = results['vix_buckets'].get('Crisis', {})
extreme_bucket = results['vix_buckets'].get('Extreme', {})
# Check both Crisis (>60) and Extreme (40-60) buckets — A4f still should not be much worse
h4_checks = []
for b_name, b in [('Crisis', crisis_bucket), ('Extreme', extreme_bucket)]:
    if b.get('qlike_diff_pct') is not None:
        # Acceptable if A4f not worse by > 5% in QLIKE
        h4_checks.append(b['qlike_diff_pct'] < 5.0)
h4_verdict = 'PASS' if h4_checks and all(h4_checks) else ('FAIL' if h4_checks else 'N/A')
print(f"  H4 (A4f no breakdown at VIX>40): {h4_verdict}")
for b_name, b in [('Crisis', crisis_bucket), ('Extreme', extreme_bucket)]:
    if b.get('qlike_diff_pct') is not None:
        print(f"    {b_name} (VIX {b['range']}): diff={b['qlike_diff_pct']:+.2f}%, DM t={b['dm_t']:+.3f}, n={b['n']}")

results['hypothesis_verdicts'] = {
    'H1_full_oos_harvey_pass': h1_verdict,
    'H2_gfc_improves': h2_verdict,
    'H3_euro_improves': h3_verdict,
    'H4_no_breakdown_extreme_vix': h4_verdict,
}

# ============================================================
# SECTION 7: METADATA AND SAVE
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'SPY',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_total': n_total,
    'n_oos_actual': n_oos_actual,
    'n_refits': refit_count,
    'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
    'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
    'vix_buckets': [(n, lo, hi) for n, lo, hi in VIX_BUCKETS],
    'random_seed': 42,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (via K1075 brief)',
    'executor': 'Claude',
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors.',
        'Hansen & Lunde (2005). A forecast comparison of volatility models.',
    ],
    'upstream_experiments': ['K988 (DM t=4.48 2019-2026)', 'K1056 (5 sub-periods 2015+)',
                             'K1066 (A4f_oc rolling)', 'K1073 (VIX/VIX9D 2013+)'],
}

# Save
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")

# ============================================================
# SECTION 8: PLOTS
# ============================================================
print("\n[8] Generating plots...")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Plot 1: Extended DM — 3 OOS windows, QLIKE comparison
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    win_names = [n for n, s, e in OOS_WINDOWS]
    ql_gjrs = [results['per_window'][n]['qlike_gjr'] for n in win_names
               if n in results['per_window']]
    ql_a4fs = [results['per_window'][n]['qlike_a4f'] for n in win_names
               if n in results['per_window']]
    dm_ts = [results['per_window'][n]['dm_t'] for n in win_names
             if n in results['per_window']]
    win_names_valid = [n for n in win_names if n in results['per_window']]

    x = np.arange(len(win_names_valid))
    w = 0.35
    ax1.bar(x - w/2, ql_gjrs, w, label='GJR', color='steelblue')
    ax1.bar(x + w/2, ql_a4fs, w, label='A4f (VIX²)', color='coral')
    ax1.set_xticks(x)
    ax1.set_xticklabels(win_names_valid, rotation=15)
    ax1.set_ylabel('QLIKE (lower = better)')
    ax1.set_title(f'{EXPERIMENT_ID}: QLIKE by OOS Window')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    colors = ['green' if abs(t) > 3.0 else ('orange' if abs(t) > 1.96 else 'gray')
              for t in dm_ts]
    ax2.bar(win_names_valid, dm_ts, color=colors, alpha=0.7)
    ax2.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax2.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax2.axhline(1.96, color='gray', linestyle=':', alpha=0.3, label='95% CI |t|=1.96')
    ax2.axhline(-1.96, color='gray', linestyle=':', alpha=0.3)
    ax2.set_ylabel('DM t-stat (A4f vs GJR)')
    ax2.set_title('DM Test by OOS Window (>0 = A4f better)')
    ax2.set_xticklabels(win_names_valid, rotation=15)
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1075_extended_dm.png'), dpi=120)
    plt.close()
    print("    k1075_extended_dm.png")

    # Plot 2: Crisis sub-periods
    fig, ax = plt.subplots(figsize=(12, 6))
    crisis_names = [c for c in results['crisis_subperiods'].keys()]
    crisis_dms = [results['crisis_subperiods'][c]['dm_t'] for c in crisis_names
                  if results['crisis_subperiods'][c].get('dm_t') is not None]
    crisis_names_valid = [c for c in crisis_names
                          if results['crisis_subperiods'][c].get('dm_t') is not None]

    colors_c = ['green' if abs(t) > 3.0 else ('orange' if abs(t) > 1.96 else 'gray')
                for t in crisis_dms]
    ax.bar(crisis_names_valid, crisis_dms, color=colors_c, alpha=0.7)
    ax.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_ylabel('DM t-stat (A4f vs GJR)')
    ax.set_title(f'{EXPERIMENT_ID}: A4f vs GJR DM t-stat across Crisis Sub-periods\n'
                 '(positive = A4f better, |t|>3 = Harvey significance)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    for i, (name, dm) in enumerate(zip(crisis_names_valid, crisis_dms)):
        n = results['crisis_subperiods'][name]['n']
        ax.text(i, dm + (0.1 if dm >= 0 else -0.3), f'n={n}', ha='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1075_crisis_periods.png'), dpi=120)
    plt.close()
    print("    k1075_crisis_periods.png")

    # Plot 3: VIX bucket analysis
    fig, ax = plt.subplots(figsize=(12, 6))
    bucket_names = [b for b in results['vix_buckets'].keys()]
    bucket_ns = [results['vix_buckets'][b].get('n', 0) for b in bucket_names]
    bucket_diffs = [results['vix_buckets'][b].get('qlike_diff_pct') for b in bucket_names]

    valid_idx = [i for i, d in enumerate(bucket_diffs) if d is not None]
    bucket_names_valid = [bucket_names[i] for i in valid_idx]
    bucket_diffs_valid = [bucket_diffs[i] for i in valid_idx]
    bucket_ns_valid = [bucket_ns[i] for i in valid_idx]

    colors_b = ['green' if d < 0 else 'red' for d in bucket_diffs_valid]
    ax.bar(bucket_names_valid, bucket_diffs_valid, color=colors_b, alpha=0.7)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_ylabel('QLIKE Diff % (A4f vs GJR, negative = A4f better)')
    ax.set_title(f'{EXPERIMENT_ID}: A4f Performance Across VIX Regimes (OOS 2007-2026)')
    ax.grid(True, alpha=0.3)
    for i, (name, diff, n) in enumerate(zip(bucket_names_valid, bucket_diffs_valid, bucket_ns_valid)):
        ax.text(i, diff + (0.05 if diff >= 0 else -0.15),
                f'n={n}', ha='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1075_vix_bucket_analysis.png'), dpi=120)
    plt.close()
    print("    k1075_vix_bucket_analysis.png")

    # Plot 4: theta1 evolution over time
    fig, ax = plt.subplots(figsize=(14, 6))
    refit_dates = [pd.to_datetime(r['date']) for r in refit_log
                   if r.get('a4f_theta1') is not None]
    theta1s = [r['a4f_theta1'] for r in refit_log if r.get('a4f_theta1') is not None]

    ax.plot(refit_dates, theta1s, marker='o', markersize=4, alpha=0.7, color='coral')
    ax.set_xlabel('Refit date')
    ax.set_ylabel('θ₁ (VIX² coefficient)')
    ax.set_title(f'{EXPERIMENT_ID}: A4f θ₁ Evolution across Rolling Refits (2007-2026)')
    ax.grid(True, alpha=0.3)

    # Overlay crisis shading
    for cname, cstart, cend in CRISIS_PERIODS:
        ax.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
                   alpha=0.15, color='red', label=cname if cname == 'GFC' else None)
    ax.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1075_theta1_evolution.png'), dpi=120)
    plt.close()
    print("    k1075_theta1_evolution.png")

    # Plot 5: Convergence rate
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    all_refit_dates = [pd.to_datetime(r['date']) for r in refit_log]
    gjr_conv = [1 if r['gjr_conv'] else 0 for r in refit_log]
    a4f_conv = [1 if r['a4f_conv'] else 0 for r in refit_log]

    ax1.plot(all_refit_dates, gjr_conv, marker='o', markersize=3, alpha=0.6,
             color='steelblue', label='GJR')
    ax1.plot(all_refit_dates, a4f_conv, marker='s', markersize=3, alpha=0.6,
             color='coral', label='A4f')
    ax1.set_ylabel('Converged (1=yes)')
    ax1.set_title('MLE Convergence per Refit')
    ax1.set_ylim(-0.1, 1.1)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Rolling conv rate (20 refit window)
    w = 20
    gjr_roll = pd.Series(gjr_conv).rolling(w, min_periods=5).mean()
    a4f_roll = pd.Series(a4f_conv).rolling(w, min_periods=5).mean()
    ax2.plot(all_refit_dates, gjr_roll, color='steelblue', label='GJR (rolling)')
    ax2.plot(all_refit_dates, a4f_roll, color='coral', label='A4f (rolling)')
    ax2.set_ylabel(f'Rolling {w}-refit convergence rate')
    ax2.set_title('Convergence Rate Over Time')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1075_convergence_check.png'), dpi=120)
    plt.close()
    print("    k1075_convergence_check.png")

except Exception as e:
    print(f"  Plot error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE in {time.time() - START_TIME:.0f}s")
print("=" * 70)
