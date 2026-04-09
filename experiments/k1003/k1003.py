#!/usr/bin/env python3
"""
K1003: A4f Sensitivity Analysis (Paper Robustness)
===================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 found A4f (τ=θ₀+θ₁VIX², free ω) with DM t=+4.48 vs GJR on SPY.
  For the paper's robustness section, we need sensitivity analysis across:
  1. Refit frequency: 21d, 63d (baseline), 126d, 252d
  2. Estimation window: 1000, 1500, 2000 (baseline), 2500, 3000
  3. OOS sub-period stability: 2019-2020, 2021-2022, 2023-2026
  4. VIX variants: VIX, VIX9D, VIX3M, VIX/VIX3M ratio

Model spec (A4f):
  τ_t = max(θ₀ + θ₁ × X²_{t-1}, 1e-16)
  g_t = ω + α × u²_{t-1} + γ × u²_{t-1} × 1_{u<0} + β × g_{t-1}
  u_{t-1} = r_{t-1} / sqrt(τ_t)
  ω: free parameter

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - Conrad & Loch (2015). JBES 33(3):338-358.

Data: SPY + ^VIX + ^VIX9D + ^VIX3M from yfinance, 2005-2026.
OOS: 2019-01-01 onwards.
Evaluation: QLIKE on r² (Patton 2011), DM test vs GJR.

Author: VolPred Research System
Date: 2026-04-08
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
EXPERIMENT_ID = "K1003"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1003_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Sensitivity Analysis (Paper Robustness)")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

# Load VIX variants
tickers_vix = {
    'VIX': '^VIX',
    'VIX9D': '^VIX9D',
    'VIX3M': '^VIX3M',
}
vix_data = {}
for name, ticker in tickers_vix.items():
    d = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    vix_data[name] = d['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
for name, series in vix_data.items():
    df[name] = series
df = df.dropna()

# Compute VIX/VIX3M ratio
df['VIX_VIX3M_ratio'] = df['VIX'] / df['VIX3M']

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
print(f"  OOS mean return: {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std: {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")

for vname in ['VIX', 'VIX9D', 'VIX3M', 'VIX_VIX3M_ratio']:
    vals = df[vname].values[oos_mask]
    print(f"  {vname}: mean={np.mean(vals):.2f}, std={np.std(vals):.2f}")

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


def fit_a4f(returns, x_vals):
    """
    Fit A4f model: τ_t = max(θ₀ + θ₁ × X²_{t-1}, eps), free ω.
    x_vals: the external variable (VIX, VIX9D, VIX3M, or ratio).
    """
    n = len(returns)
    x_lag = np.empty(n)
    x_lag[0] = x_vals[0]
    x_lag[1:] = x_vals[:-1]

    var0 = np.var(returns)
    x2_mean = np.mean(x_lag**2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params

        tau = np.maximum(theta0 + theta1 * x_lag**2, 1e-16)

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
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

    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / x2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
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


def compute_tau_a4f(theta0, theta1, x_lag):
    """Compute τ for A4f: τ = max(θ₀ + θ₁ × X², eps)."""
    return np.maximum(theta0 + theta1 * x_lag**2, 1e-16)


def run_oos_comparison(ret_all, x_vals_all, oos_mask_arr, window, refit_every):
    """
    Run OOS forecasting for both GJR and A4f with given settings.
    Returns (gjr_forecasts, a4f_forecasts, oos_r2) arrays.
    """
    oos_indices = np.where(oos_mask_arr)[0]
    n_oos_actual = len(oos_indices)

    gjr_fc = np.full(n_oos_actual, np.nan)
    a4f_fc = np.full(n_oos_actual, np.nan)

    # State variables
    gjr_params = None
    gjr_h = None
    a4f_params = None
    a4f_g = None
    a4f_tau_prev = None

    for t_idx, abs_idx in enumerate(oos_indices):
        need_refit = (t_idx % refit_every == 0) or (t_idx == 0)

        if need_refit:
            train_start = max(0, abs_idx - window)
            train_ret = ret_all[train_start:abs_idx]
            train_x = x_vals_all[train_start:abs_idx]

            # Fit GJR
            p_gjr = fit_gjr(train_ret)
            if p_gjr is not None:
                gjr_params = p_gjr
                h = np.var(train_ret)
                for i in range(1, len(train_ret)):
                    h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
                gjr_h = h

            # Fit A4f
            p_a4f = fit_a4f(train_ret, train_x)
            if p_a4f is not None:
                a4f_params = p_a4f
                theta0, theta1 = p_a4f[0], p_a4f[1]
                omega_g, alpha_p, gamma_p, beta_p = p_a4f[2], p_a4f[3], p_a4f[4], p_a4f[5]

                n_train = len(train_ret)
                x_lag_tr = np.empty(n_train)
                x_lag_tr[0] = train_x[0]
                x_lag_tr[1:] = train_x[:-1]
                tau_train = compute_tau_a4f(theta0, theta1, x_lag_tr)

                persist = alpha_p + gamma_p / 2.0 + beta_p
                eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg
                for i in range(1, n_train):
                    u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i], 1e-16))
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)
                a4f_g = g
                a4f_tau_prev = tau_train[-1]

        # Forecast for day abs_idx

        # GJR
        if gjr_params is not None:
            r_prev = ret_all[abs_idx - 1]
            h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
            gjr_fc[t_idx] = h_new
            gjr_h = h_new

        # A4f
        if a4f_params is not None:
            theta0, theta1 = a4f_params[0], a4f_params[1]
            omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]

            x_prev = x_vals_all[abs_idx - 1]
            tau_t = max(theta0 + theta1 * x_prev**2, 1e-16)

            r_prev = ret_all[abs_idx - 1]
            u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
            g_new = max(g_new, 1e-10)

            a4f_fc[t_idx] = tau_t * g_new
            a4f_g = g_new
            a4f_tau_prev = tau_t

    oos_r2 = ret_all[oos_indices]**2
    return gjr_fc, a4f_fc, oos_r2


def evaluate_forecasts(gjr_fc, a4f_fc, oos_r2):
    """Compute QLIKE and DM test for a pair of forecasts."""
    valid = np.isfinite(gjr_fc) & np.isfinite(a4f_fc) & (oos_r2 > 0)
    if valid.sum() < 100:
        return {'qlike_gjr': None, 'qlike_a4f': None, 'dm_t': None, 'dm_p': None, 'n_valid': int(valid.sum())}

    r2v = oos_r2[valid]
    gjr_v = gjr_fc[valid]
    a4f_v = a4f_fc[valid]

    q_gjr = float(qlike(r2v, gjr_v))
    q_a4f = float(qlike(r2v, a4f_v))

    # DM test using pointwise QLIKE losses
    # dm_test(loss1, loss2): negative t means loss1 < loss2 (model 1 better)
    # We want positive t when A4f is better, so: loss_gjr - loss_a4f > 0
    loss_gjr = qlike_pointwise(r2v, gjr_v)
    loss_a4f = qlike_pointwise(r2v, a4f_v)
    dm_t, dm_p = dm_test(loss_gjr, loss_a4f)
    # dm_t < 0 means loss_gjr < loss_a4f (GJR better)
    # dm_t > 0 means loss_a4f < loss_gjr ... wait, let me check
    # dm_test computes d = loss1 - loss2, negative t means loss1 < loss2
    # So dm_test(loss_gjr, loss_a4f): negative t means GJR better
    # We want: positive t means A4f better → use dm_test(loss_gjr, loss_a4f)
    # Actually negative d means loss_gjr < loss_a4f means GJR wins
    # Positive d means loss_gjr > loss_a4f means A4f wins
    # t = mean(d) / se(d), positive t → A4f better ✓

    return {
        'qlike_gjr': q_gjr,
        'qlike_a4f': q_a4f,
        'qlike_improvement': q_gjr - q_a4f,
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'n_valid': int(valid.sum()),
        'robust': abs(dm_t) > 3.0,
    }


# ============================================================
# SECTION 4: SENSITIVITY ANALYSIS
# ============================================================

results = {
    'experiment_id': EXPERIMENT_ID,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'asset': 'SPY',
    'oos_start': OOS_START,
    'model': 'A4f (τ=θ₀+θ₁X², free ω)',
    'benchmark': 'GJR-GARCH(1,1)',
}

# --- 4a: Refit Frequency ---
print("\n[4a] Refit frequency sensitivity...")
refit_freqs = [21, 63, 126, 252]
vix_vals = df['VIX'].values

refit_results = {}
for rf in refit_freqs:
    t0 = time.time()
    gjr_fc, a4f_fc, oos_r2_vals = run_oos_comparison(ret, vix_vals, oos_mask, window=2000, refit_every=rf)
    ev = evaluate_forecasts(gjr_fc, a4f_fc, oos_r2_vals)
    elapsed = time.time() - t0
    ev['elapsed_s'] = round(elapsed, 1)
    refit_results[f'refit_{rf}d'] = ev
    robust_str = "ROBUST" if ev.get('robust') else "NOT robust"
    print(f"  refit={rf:3d}d: QLIKE GJR={ev['qlike_gjr']:.4f}, A4f={ev['qlike_a4f']:.4f}, "
          f"DM t={ev['dm_t']:+.3f} [{robust_str}] ({elapsed:.1f}s)")

results['refit_frequency'] = refit_results

# --- 4b: Estimation Window ---
print("\n[4b] Estimation window sensitivity...")
windows = [1000, 1500, 2000, 2500, 3000]

window_results = {}
for w in windows:
    t0 = time.time()
    gjr_fc, a4f_fc, oos_r2_vals = run_oos_comparison(ret, vix_vals, oos_mask, window=w, refit_every=63)
    ev = evaluate_forecasts(gjr_fc, a4f_fc, oos_r2_vals)
    elapsed = time.time() - t0
    ev['elapsed_s'] = round(elapsed, 1)
    window_results[f'window_{w}'] = ev
    robust_str = "ROBUST" if ev.get('robust') else "NOT robust"
    print(f"  window={w:4d}: QLIKE GJR={ev['qlike_gjr']:.4f}, A4f={ev['qlike_a4f']:.4f}, "
          f"DM t={ev['dm_t']:+.3f} [{robust_str}] ({elapsed:.1f}s)")

results['estimation_window'] = window_results

# --- 4c: OOS Sub-period Stability ---
print("\n[4c] OOS sub-period stability...")

sub_periods = {
    '2019-2020_COVID': ('2019-01-01', '2020-12-31'),
    '2021-2022_PostCOVID_Hike': ('2021-01-01', '2022-12-31'),
    '2023-2026_Stable': ('2023-01-01', '2026-12-31'),
}

# First run full OOS with baseline settings to get all forecasts
gjr_fc_full, a4f_fc_full, oos_r2_full = run_oos_comparison(ret, vix_vals, oos_mask, window=2000, refit_every=63)
oos_dates = df.index[oos_mask]

subperiod_results = {}
for period_name, (start, end) in sub_periods.items():
    mask_period = (oos_dates >= start) & (oos_dates <= end)
    n_period = mask_period.sum()
    if n_period < 50:
        print(f"  {period_name}: too few obs ({n_period}), skipping")
        continue

    gjr_sub = gjr_fc_full[mask_period]
    a4f_sub = a4f_fc_full[mask_period]
    r2_sub = oos_r2_full[mask_period]

    ev = evaluate_forecasts(gjr_sub, a4f_sub, r2_sub)
    subperiod_results[period_name] = ev
    robust_str = "ROBUST" if ev.get('robust') else "NOT robust"
    print(f"  {period_name}: QLIKE GJR={ev['qlike_gjr']:.4f}, A4f={ev['qlike_a4f']:.4f}, "
          f"DM t={ev['dm_t']:+.3f}, n={ev['n_valid']} [{robust_str}]")

results['subperiod_stability'] = subperiod_results

# --- 4d: VIX Variant Sensitivity ---
print("\n[4d] VIX variant sensitivity...")

vix_variants = {
    'VIX': df['VIX'].values,
    'VIX9D': df['VIX9D'].values,
    'VIX3M': df['VIX3M'].values,
    'VIX_VIX3M_ratio': df['VIX_VIX3M_ratio'].values,
}

variant_results = {}
for vname, x_vals in vix_variants.items():
    t0 = time.time()
    gjr_fc, a4f_fc, oos_r2_vals = run_oos_comparison(ret, x_vals, oos_mask, window=2000, refit_every=63)
    ev = evaluate_forecasts(gjr_fc, a4f_fc, oos_r2_vals)
    elapsed = time.time() - t0
    ev['elapsed_s'] = round(elapsed, 1)
    variant_results[vname] = ev
    robust_str = "ROBUST" if ev.get('robust') else "NOT robust"
    print(f"  {vname:20s}: QLIKE GJR={ev['qlike_gjr']:.4f}, A4f={ev['qlike_a4f']:.4f}, "
          f"DM t={ev['dm_t']:+.3f} [{robust_str}] ({elapsed:.1f}s)")

results['vix_variants'] = variant_results

# ============================================================
# SECTION 5: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Count robustness
total_tests = 0
robust_count = 0
summary_table = []

print("\n--- Refit Frequency ---")
for k, v in refit_results.items():
    total_tests += 1
    if v.get('robust'):
        robust_count += 1
    summary_table.append({'dimension': 'refit', 'setting': k, 'dm_t': v['dm_t'], 'robust': v.get('robust', False)})
    print(f"  {k}: DM t={v['dm_t']:+.3f} {'✓' if v.get('robust') else '✗'}")

print("\n--- Estimation Window ---")
for k, v in window_results.items():
    total_tests += 1
    if v.get('robust'):
        robust_count += 1
    summary_table.append({'dimension': 'window', 'setting': k, 'dm_t': v['dm_t'], 'robust': v.get('robust', False)})
    print(f"  {k}: DM t={v['dm_t']:+.3f} {'✓' if v.get('robust') else '✗'}")

print("\n--- Sub-period Stability ---")
for k, v in subperiod_results.items():
    total_tests += 1
    if v.get('robust'):
        robust_count += 1
    summary_table.append({'dimension': 'subperiod', 'setting': k, 'dm_t': v['dm_t'], 'robust': v.get('robust', False)})
    print(f"  {k}: DM t={v['dm_t']:+.3f} {'✓' if v.get('robust') else '✗'}")

print("\n--- VIX Variants ---")
for k, v in variant_results.items():
    total_tests += 1
    if v.get('robust'):
        robust_count += 1
    summary_table.append({'dimension': 'vix_variant', 'setting': k, 'dm_t': v['dm_t'], 'robust': v.get('robust', False)})
    print(f"  {k}: DM t={v['dm_t']:+.3f} {'✓' if v.get('robust') else '✗'}")

print(f"\nOverall: {robust_count}/{total_tests} tests pass Harvey (2016) |t| > 3.0 threshold")

results['summary'] = {
    'total_tests': total_tests,
    'robust_count': robust_count,
    'robust_pct': round(100 * robust_count / total_tests, 1) if total_tests > 0 else 0,
    'table': summary_table,
}

results['limitations'] = [
    'Single asset (SPY only)',
    'OOS period 2019-2026 includes extreme COVID regime',
    'VIX9D series may have shorter history',
    'VIX/VIX3M ratio amplifies noise when VIX3M is small',
    'Sub-period DM test has reduced power due to smaller n',
]

# ============================================================
# SECTION 6: SAVE RESULTS
# ============================================================
elapsed_total = time.time() - START_TIME
results['elapsed_total_s'] = round(elapsed_total, 1)

print(f"\n[6] Saving results to {RESULTS_PATH}...")
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nDone! Total elapsed: {elapsed_total:.0f}s")
print(f"Results saved to: {RESULTS_PATH}")
