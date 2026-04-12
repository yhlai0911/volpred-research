#!/usr/bin/env python3
"""
K1078: A4f Extended History on QQQ — US Tech-Heavy Cross-Asset Validation
========================================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation:
  K1075 (SPY 2007-2026): A4f DM t=+7.92, GFC Harvey-PASS, theta1 stable.
  K1077 (0050.TW 2010-2025): A4f DM t=-0.49 NS, theta1 4 orders of magnitude unstable.

  Two extremes. Where does QQQ (US tech-heavy, correlated with SPY 0.90+ but
  ~1.3x volatility) sit? This is the Paper 9 cross-asset key question — is
  A4f an SPY-specific artifact, or robust to US liquid ETFs?

  K994 did a brief QQQ comparison (2019-2026 only, PASS) but never the 3 OOS
  window extended-history stress test. This experiment fills that gap.

Design (strict parity with K1075):
  - Three non-overlapping OOS windows (2007-2012, 2013-2018, 2019-2026)
  - Rolling-window GARCH with 2000-day training, 63-day refit
  - Two models: GJR baseline vs A4f (τ=θ₀+θ₁·VIX²_{t-1}, g=GJR, free ω)
  - Crisis sub-period analysis: GFC, Euro, COVID, 2022 Bear
  - VIX bucket analysis: Low/Normal/High/Extreme/Crisis

  Note: QQQ IPO 1999-03-10. At 2007-01-01 QQQ has ~1965 obs (vs WINDOW=2000
  requested). This mirrors K1075 where SPY at 2007-01-01 had only 1758 obs.
  The rolling-window code uses `max(0, abs_idx - WINDOW)` so first refit uses
  whatever is available — same behavior as K1075.

  The 2003-2006 "dot-com recovery" window mentioned in the brief is NOT feasible
  because QQQ IPO 1999-03 gives insufficient training history (e.g., 2003-01-01
  start_idx ≈ 958). Documented here and skipped; all 3 primary windows produce
  well-posed estimation.

Hypotheses:
  H1: QQQ full OOS 2007-2026 A4f vs GJR DM Harvey-PASS (|t|>3)
  H2: QQQ 2008-09 GFC sub-period A4f still improves over GJR
  H3: All 3 OOS windows A4f wins (directional consistency with SPY)
  H4: A4f does NOT break down at extreme VIX (>40)
  H5: QQQ theta1 stability intermediate between SPY and 0050.TW

Data: yfinance QQQ + ^VIX 1999-01-01 ~ 2026-04-12
Evaluation: QLIKE on r² (Patton 2011), DM test (Harvey 2016)

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - Hansen & Lunde (2005). Consistent ranking.

Upstream experiments:
  - K988  (SPY A4f, 2019-2026 DM t=4.48)
  - K994  (Cross-asset MF-GJR-X incl. QQQ brief)
  - K1056 (5 sub-periods 2015+)
  - K1075 (SPY extended 2007-2026: DM t=+7.92, GFC PASS)
  - K1077 (0050.TW extended: DM t=-0.49 NS)

Author: VolPred Research System
Date: 2026-04-13
Experiment ID: K1078
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
EXPERIMENT_ID = "K1078"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1078_results.json')

# Configuration
DATA_START = '1999-01-01'  # QQQ IPO 1999-03-10
DATA_END = '2026-04-12'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly

# Three non-overlapping OOS windows (parity with K1075)
OOS_WINDOWS = [
    ('Early_Crisis', '2007-01-01', '2012-12-31'),   # GFC + Euro + Flash Crash
    ('Middle_Recovery', '2013-01-01', '2018-12-31'),  # Taper + China + 2018Q4 spike
    ('Late_COVID', '2019-01-01', '2026-04-11'),       # COVID + Rate Hike
]

# Crisis sub-periods within OOS (parity with K1075)
CRISIS_PERIODS = [
    ('GFC', '2008-01-01', '2009-12-31'),
    ('Euro_Crisis', '2011-06-01', '2012-06-30'),
    ('COVID_Crash', '2020-02-01', '2020-06-30'),
    ('Bear_2022', '2022-01-01', '2022-12-31'),
]

# VIX buckets (parity with K1075)
VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

# SPY (K1075) and 0050.TW (K1077) reference numbers for three-asset comparison.
# These are loaded from their results JSONs at the end of this script; we
# pre-declare the paths so the plot section can find them.
K1075_RESULTS_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1075', 'k1075_results.json'))
K1077_RESULTS_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'k1077', 'k1077_results.json'))

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Extended History on QQQ (2007-2026)")
print(f"  3 OOS windows, 4 crisis sub-periods, 5 VIX buckets")
print(f"  Only 2 models: GJR vs A4f (VIX^2 free omega)")
print(f"  Strict parity with K1075 (SPY) design")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading QQQ + ^VIX from yfinance...")
import yfinance as yf

raw = yf.download('QQQ', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
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
print(f"  QQQ joined data: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
print(f"  Full sample:")
print(f"    Return mean (ann): {np.mean(ret)*252:.4f}")
print(f"    Return std (ann):  {np.std(ret)*np.sqrt(252):.4f}")
print(f"    Return skew:       {stats.skew(ret):.3f}")
print(f"    Return kurt:       {stats.kurtosis(ret):.3f}")
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
      g_t   = omega_g + alpha * u_{t-1}^2 + gamma * u_{t-1}^2 * I(u_{t-1}<0)
              + beta * g_{t-1}
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

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)

        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
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

# Verify training history availability at each OOS start
for name, start, end in OOS_WINDOWS:
    start_idx_arr = np.where(dates >= start)[0]
    if len(start_idx_arr) == 0:
        continue
    start_idx = start_idx_arr[0]
    print(f"    {name}: start_idx={start_idx}, window_requested={WINDOW}, "
          f"sufficient_2000={'YES' if start_idx >= WINDOW else 'NO (uses all available)'}")

# Forecasts storage
gjr_forecasts = np.full(n_oos_actual, np.nan)
a4f_forecasts = np.full(n_oos_actual, np.nan)

# Convergence tracking per refit
refit_log = []

# State
gjr_h = None
gjr_params = None
a4f_g = None
a4f_tau_prev = None
a4f_params = None

prev_window = None
refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    current_window = window_tags[abs_idx]

    if t_idx == 0 or current_window != prev_window:
        need_refit = True
    else:
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

    # Forecast for day abs_idx
    if gjr_params is not None:
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_h = h_new

    if a4f_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)

        r_prev = ret[abs_idx - 1]
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
    """Moving-block bootstrap CI for mean of differences."""
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        if not blocks:
            return (np.nan, np.nan)
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

# Use lagged VIX (what the model sees)
oos_vix_lag = np.empty(n_oos_actual)
for i, idx in enumerate(oos_indices):
    oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]

for bname, bmin, bmax in VIX_BUCKETS:
    mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax) & both_valid
    n_b = mask.sum()
    if n_b < 20:
        print(f"  {bname:<12} [{bmin},{bmax}) insufficient (n={n_b})")
        results['vix_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b),
                                         'range': [bmin, bmax]}
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

# --- theta1 summary statistics ---
valid_theta1 = [r['a4f_theta1'] for r in refit_log
                if r.get('a4f_theta1') is not None and r.get('a4f_conv')]
if valid_theta1:
    t1 = np.array(valid_theta1)
    theta1_stats = {
        'n_refits_converged': int(len(t1)),
        'median': float(np.median(t1)),
        'mean': float(np.mean(t1)),
        'std': float(np.std(t1)),
        'min': float(np.min(t1)),
        'max': float(np.max(t1)),
        'cv': float(np.std(t1) / (np.mean(t1) + 1e-30)),
        'orders_of_magnitude_span': float(np.log10(np.max(t1) / max(np.min(t1), 1e-30))),
    }
    results['theta1_stability'] = theta1_stats
    print(f"\n  theta1 stability:")
    print(f"    median: {theta1_stats['median']:.3e}")
    print(f"    range : {theta1_stats['min']:.3e} ~ {theta1_stats['max']:.3e}")
    print(f"    CV: {theta1_stats['cv']:.3f}, orders span: "
          f"{theta1_stats['orders_of_magnitude_span']:.2f}")

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)

# H1: Full OOS DM Harvey-PASS (positive)
full_dm = results['full_oos'].get('dm_t')
h1_verdict = 'PASS' if (full_dm is not None and abs(full_dm) > 3.0 and full_dm > 0) else 'FAIL'
print(f"  H1 (QQQ Full OOS A4f > GJR, DM t>3): {h1_verdict} "
      f"(t={full_dm:+.3f})" if full_dm is not None else "  H1: N/A")

# H2: GFC sub-period A4f improves
gfc = results['crisis_subperiods'].get('GFC', {})
gfc_diff = gfc.get('qlike_diff_pct')
gfc_dm = gfc.get('dm_t')
h2_verdict = ('PASS' if gfc_diff is not None and gfc_diff < 0 else 'FAIL')
print(f"  H2 (QQQ GFC A4f improves): {h2_verdict} "
      f"(QLIKE diff={gfc_diff:+.2f}%, DM t={gfc_dm:+.3f})"
      if gfc_diff is not None else "  H2: N/A")

# H3: All 3 OOS windows win
window_wins = [1 if v.get('qlike_diff_pct', 0) < 0 else 0
               for v in results['per_window'].values()]
h3_verdict = 'PASS' if (len(window_wins) == 3 and sum(window_wins) == 3) else (
    'PARTIAL' if sum(window_wins) >= 2 else 'FAIL')
print(f"  H3 (All 3 windows A4f wins directionally): {h3_verdict} "
      f"({sum(window_wins)}/{len(window_wins)})")

# H4: A4f does not break down at extreme VIX
crisis_bucket = results['vix_buckets'].get('Crisis', {})
extreme_bucket = results['vix_buckets'].get('Extreme', {})
h4_checks = []
for b_name, b in [('Crisis', crisis_bucket), ('Extreme', extreme_bucket)]:
    if b.get('qlike_diff_pct') is not None:
        h4_checks.append(b['qlike_diff_pct'] < 5.0)
h4_verdict = 'PASS' if h4_checks and all(h4_checks) else ('FAIL' if h4_checks else 'N/A')
print(f"  H4 (A4f no breakdown at VIX>40): {h4_verdict}")
for b_name, b in [('Crisis', crisis_bucket), ('Extreme', extreme_bucket)]:
    if b.get('qlike_diff_pct') is not None:
        print(f"    {b_name} (VIX {b['range']}): diff={b['qlike_diff_pct']:+.2f}%, "
              f"DM t={b['dm_t']:+.3f}, n={b['n']}")

# H5: theta1 stability vs SPY/0050.TW
qqq_orders = results.get('theta1_stability', {}).get('orders_of_magnitude_span')
h5_verdict = 'N/A'
if qqq_orders is not None:
    # SPY K1075 spans <1 order; 0050.TW K1077 spans ~4 orders
    if qqq_orders <= 2.0:
        h5_verdict = 'STABLE (SPY-like)'
    elif qqq_orders <= 3.5:
        h5_verdict = 'INTERMEDIATE'
    else:
        h5_verdict = 'UNSTABLE (TW-like)'
print(f"  H5 (theta1 stability): {h5_verdict} "
      f"(orders span = {qqq_orders:.2f})" if qqq_orders is not None else "  H5: N/A")

results['hypothesis_verdicts'] = {
    'H1_full_oos_harvey_pass': h1_verdict,
    'H2_gfc_improves': h2_verdict,
    'H3_all_windows_directional_win': h3_verdict,
    'H4_no_breakdown_extreme_vix': h4_verdict,
    'H5_theta1_stability': h5_verdict,
}

# ============================================================
# SECTION 7: THREE-ASSET COMPARISON
# ============================================================
print("\n[7] Three-asset comparison (SPY K1075 / 0050.TW K1077 / QQQ K1078)...")

three_asset = {}
try:
    with open(K1075_RESULTS_PATH) as f:
        spy_res = json.load(f)
    three_asset['SPY_K1075'] = {
        'full_dm': spy_res['full_oos']['dm_t'],
        'full_diff_pct': spy_res['full_oos']['qlike_diff_pct'],
        'harvey_pass': spy_res['full_oos']['harvey_pass'],
        'per_window': {k: {'dm': v['dm_t'], 'diff_pct': v['qlike_diff_pct']}
                       for k, v in spy_res['per_window'].items()},
        'gfc': {'dm': spy_res['crisis_subperiods'].get('GFC', {}).get('dm_t'),
                'diff_pct': spy_res['crisis_subperiods'].get('GFC', {}).get('qlike_diff_pct')},
    }
except Exception as e:
    print(f"  Warning: cannot load K1075 ({e})")
    three_asset['SPY_K1075'] = None

try:
    with open(K1077_RESULTS_PATH) as f:
        tw_res = json.load(f)
    three_asset['TW_K1077'] = {
        'full_dm': tw_res['full_oos']['dm_t'],
        'full_diff_pct': tw_res['full_oos']['qlike_diff_pct'],
        'harvey_pass': tw_res['full_oos']['harvey_pass'],
        'per_window': {k: {'dm': v['dm_t'], 'diff_pct': v['qlike_diff_pct']}
                       for k, v in tw_res['per_window'].items()},
    }
except Exception as e:
    print(f"  Warning: cannot load K1077 ({e})")
    three_asset['TW_K1077'] = None

three_asset['QQQ_K1078'] = {
    'full_dm': results['full_oos']['dm_t'],
    'full_diff_pct': results['full_oos']['qlike_diff_pct'],
    'harvey_pass': results['full_oos']['harvey_pass'],
    'per_window': {k: {'dm': v['dm_t'], 'diff_pct': v['qlike_diff_pct']}
                   for k, v in results['per_window'].items()},
    'gfc': {'dm': results['crisis_subperiods'].get('GFC', {}).get('dm_t'),
            'diff_pct': results['crisis_subperiods'].get('GFC', {}).get('qlike_diff_pct')},
}
results['three_asset_comparison'] = three_asset

print(f"  {'Asset':<12} {'Full DM':>10} {'Full Diff%':>12} {'Harvey':>8}")
for label, r in three_asset.items():
    if r is None:
        continue
    print(f"  {label:<12} {r['full_dm']:>+10.3f} {r['full_diff_pct']:>+11.2f}% "
          f"{'PASS' if r['harvey_pass'] else 'FAIL':>8}")

# ============================================================
# SECTION 8: METADATA AND SAVE
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'QQQ',
    'data_source': 'yfinance',
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
    'proposer': 'User (via K1078 brief)',
    'executor': 'Claude',
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors.',
        'Hansen & Lunde (2005). A forecast comparison of volatility models.',
    ],
    'upstream_experiments': [
        'K988 SPY A4f 2019-2026 DM t=4.48',
        'K994 cross-asset MF-GJR-X incl. QQQ brief',
        'K1056 5 sub-periods 2015+',
        'K1075 SPY extended 2007-2026 DM t=7.92 GFC PASS',
        'K1077 0050.TW extended 2010-2025 DM t=-0.49 NS',
    ],
    'notes': (
        'QQQ IPO 1999-03-10, so at 2007-01-01 start there are ~1965 training obs '
        '(vs WINDOW=2000 requested). Code uses max(0, abs_idx - WINDOW) so first '
        'refit uses all available history — same behavior as K1075 SPY (1758 obs '
        'at 2007 start). The 2003-2006 dot-com recovery window in the brief is '
        'NOT feasible: 2003-01-01 has only ~958 training obs, insufficient for '
        'stable GARCH estimation. Only the 3 primary OOS windows are used.'
    ),
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")

# ============================================================
# SECTION 9: PLOTS
# ============================================================
print("\n[9] Generating plots...")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # --- Plot 1: Extended DM — 3 OOS windows, QLIKE comparison ---
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
    ax1.set_title(f'{EXPERIMENT_ID} QQQ: QLIKE by OOS Window')
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
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1078_extended_dm.png'), dpi=120)
    plt.close()
    print("    k1078_extended_dm.png")

    # --- Plot 2: Crisis sub-periods ---
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
    ax.set_title(f'{EXPERIMENT_ID} QQQ: A4f vs GJR across Crisis Sub-periods\n'
                 '(positive = A4f better, |t|>3 = Harvey significance)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    for i, (name, dm) in enumerate(zip(crisis_names_valid, crisis_dms)):
        n = results['crisis_subperiods'][name]['n']
        ax.text(i, dm + (0.1 if dm >= 0 else -0.3), f'n={n}', ha='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1078_crisis_periods.png'), dpi=120)
    plt.close()
    print("    k1078_crisis_periods.png")

    # --- Plot 3: VIX bucket analysis ---
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
    ax.set_title(f'{EXPERIMENT_ID} QQQ: A4f Performance Across VIX Regimes (OOS 2007-2026)')
    ax.grid(True, alpha=0.3)
    for i, (name, diff, n) in enumerate(zip(bucket_names_valid, bucket_diffs_valid, bucket_ns_valid)):
        ax.text(i, diff + (0.05 if diff >= 0 else -0.15),
                f'n={n}', ha='center', fontsize=9)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1078_vix_bucket.png'), dpi=120)
    plt.close()
    print("    k1078_vix_bucket.png")

    # --- Plot 4: theta1 evolution over time ---
    fig, ax = plt.subplots(figsize=(14, 6))
    refit_dates = [pd.to_datetime(r['date']) for r in refit_log
                   if r.get('a4f_theta1') is not None]
    theta1s = [r['a4f_theta1'] for r in refit_log if r.get('a4f_theta1') is not None]

    ax.plot(refit_dates, theta1s, marker='o', markersize=4, alpha=0.7, color='coral')
    ax.set_xlabel('Refit date')
    ax.set_ylabel('θ₁ (VIX² coefficient)')
    ax.set_yscale('log')
    ax.set_title(f'{EXPERIMENT_ID} QQQ: A4f θ₁ Evolution across Rolling Refits (2007-2026)')
    ax.grid(True, alpha=0.3, which='both')

    for cname, cstart, cend in CRISIS_PERIODS:
        ax.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
                   alpha=0.15, color='red', label=cname if cname == 'GFC' else None)
    ax.legend()

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1078_theta1_evolution.png'), dpi=120)
    plt.close()
    print("    k1078_theta1_evolution.png")

    # --- Plot 5: Three-asset comparison (SPY vs QQQ vs 0050.TW) ---
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    # 5a: Full-OOS DM t-stat bar
    ax = axes[0]
    assets = []
    dms = []
    bar_colors = []
    for label, r in [('SPY (K1075)', three_asset.get('SPY_K1075')),
                     ('QQQ (K1078)', three_asset.get('QQQ_K1078')),
                     ('0050.TW (K1077)', three_asset.get('TW_K1077'))]:
        if r is None:
            continue
        assets.append(label)
        dms.append(r['full_dm'])
        bar_colors.append('green' if abs(r['full_dm']) > 3.0 and r['full_dm'] > 0
                          else 'orange' if abs(r['full_dm']) > 1.96
                          else 'gray')
    ax.bar(assets, dms, color=bar_colors, alpha=0.75)
    ax.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_ylabel('Full-OOS DM t-stat (A4f vs GJR)')
    ax.set_title('Cross-Asset: Full OOS DM')
    ax.legend()
    ax.grid(True, alpha=0.3)
    for i, dm in enumerate(dms):
        ax.text(i, dm + (0.3 if dm >= 0 else -0.5), f'{dm:+.2f}',
                ha='center', fontsize=10, fontweight='bold')

    # 5b: Per-window DM comparison (3 windows x 3 assets)
    ax = axes[1]
    win_labels = ['Early', 'Middle', 'Late']
    width = 0.25
    x = np.arange(len(win_labels))

    for i, (label, r, color) in enumerate([
        ('SPY', three_asset.get('SPY_K1075'), 'steelblue'),
        ('QQQ', three_asset.get('QQQ_K1078'), 'coral'),
        ('0050.TW', three_asset.get('TW_K1077'), 'mediumseagreen'),
    ]):
        if r is None:
            continue
        vals = []
        # Window names differ across experiments; map by order.
        per_win = r.get('per_window', {})
        keys_sorted = list(per_win.keys())
        for k in keys_sorted[:3]:
            vals.append(per_win[k]['dm'] if per_win[k]['dm'] is not None else 0)
        # Pad
        while len(vals) < 3:
            vals.append(0)
        ax.bar(x + (i - 1) * width, vals, width, label=label, color=color, alpha=0.8)

    ax.axhline(3.0, color='red', linestyle='--', alpha=0.4)
    ax.axhline(-3.0, color='red', linestyle='--', alpha=0.4)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(win_labels)
    ax.set_ylabel('Per-window DM t-stat')
    ax.set_title('Cross-Asset: Per-Window DM')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 5c: QLIKE diff% summary text panel
    ax = axes[2]
    ax.axis('off')
    lines = ['Three-Asset A4f vs GJR Summary\n']
    lines.append(f"{'Asset':<12}{'Full DM':>10}{'Diff %':>10}{'Harvey':>10}\n")
    lines.append('-' * 42 + '\n')
    for label, r in [('SPY K1075', three_asset.get('SPY_K1075')),
                     ('QQQ K1078', three_asset.get('QQQ_K1078')),
                     ('TW K1077', three_asset.get('TW_K1077'))]:
        if r is None:
            lines.append(f"{label:<12}{'N/A':>10}\n")
            continue
        lines.append(f"{label:<12}{r['full_dm']:>+10.3f}"
                     f"{r['full_diff_pct']:>+9.2f}%"
                     f"{'PASS' if r['harvey_pass'] else 'FAIL':>10}\n")
    lines.append('\nGFC Sub-period:\n')
    spy_gfc = three_asset.get('SPY_K1075', {}).get('gfc') if three_asset.get('SPY_K1075') else None
    qqq_gfc = three_asset.get('QQQ_K1078', {}).get('gfc') if three_asset.get('QQQ_K1078') else None
    if spy_gfc and spy_gfc.get('dm') is not None:
        lines.append(f"  SPY  DM t = {spy_gfc['dm']:+.3f}, diff {spy_gfc['diff_pct']:+.2f}%\n")
    if qqq_gfc and qqq_gfc.get('dm') is not None:
        lines.append(f"  QQQ  DM t = {qqq_gfc['dm']:+.3f}, diff {qqq_gfc['diff_pct']:+.2f}%\n")
    lines.append('\n(0050.TW Asia-based: GFC window captures\n'
                 'Euro crisis aftermath not 2008-09 directly.)\n')
    ax.text(0, 1, ''.join(lines), family='monospace', fontsize=10,
            verticalalignment='top')
    ax.set_title('Summary')

    plt.suptitle(f'{EXPERIMENT_ID}: SPY vs QQQ vs 0050.TW Cross-Asset A4f Comparison',
                 fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1078_three_asset_comparison.png'),
                dpi=120, bbox_inches='tight')
    plt.close()
    print("    k1078_three_asset_comparison.png")

except Exception as e:
    print(f"  Plot error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE in {time.time() - START_TIME:.0f}s")
print("=" * 70)
