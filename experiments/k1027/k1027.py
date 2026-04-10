#!/usr/bin/env python3
"""
K1027: A4f Sub-Period Robustness Analysis (Paper 9 必備 robustness)
===================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 showed A4f(VIX²) DM t=+4.48 vs GJR on SPY full OOS (2013-2026).
  Reviewer concern: "Is the A4f advantage driven by COVID?"
  This experiment tests A4f across 7 non-overlapping 2-year sub-periods
  to demonstrate regime-robustness.

Models:
  - A4f-VIX-t (df=8): τ = θ₀ + θ₁ × VIX²_{t-1}, ω free, Student-t(8)
  - GJR-t (df=8): baseline, Student-t(8)

Design:
  - Use rolling estimation (window=2000), extract OOS forecasts for each sub-period
  - Full-sample estimation to avoid small-sample estimation issues
  - QLIKE on r² (Patton 2011), DM test (note: small sample → report but
    don't rely on Harvey t>3.0 threshold)

Sub-periods:
  P1: 2013-2014 (low vol, post-crisis recovery)
  P2: 2015-2016 (mid vol, oil crash + Brexit)
  P3: 2017-2018 (low vol → vol spike)
  P4: 2019-2020 (COVID crash + recovery)
  P5: 2021-2022 (inflation + rate hikes + bear)
  P6: 2023-2024 (AI rally + normalization)
  P7: 2025-2026 (tariff war volatility, latest)

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility.
    JBES 33(3):338-358.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). |t| > 3.0 threshold.

Data: SPY 2005-2026, VIX from yfinance.
Seed: 42
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
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1027"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1027_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit
STUDENT_T_DF = 8  # K1021 recommended

# Sub-periods definition
SUB_PERIODS = {
    'P1': ('2013-01-01', '2014-12-31', 'Low vol, post-crisis recovery'),
    'P2': ('2015-01-01', '2016-12-31', 'Mid vol, oil crash + Brexit'),
    'P3': ('2017-01-01', '2018-12-31', 'Low vol → vol spike'),
    'P4': ('2019-01-01', '2020-12-31', 'COVID crash + recovery'),
    'P5': ('2021-01-01', '2022-12-31', 'Inflation + rate hikes + bear'),
    'P6': ('2023-01-01', '2024-12-31', 'AI rally + normalization'),
    'P7': ('2025-01-01', '2026-12-31', 'Tariff war volatility'),
}

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Sub-Period Robustness Analysis")
print("  7 non-overlapping 2-year sub-periods, Paper 9 robustness test")
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

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

n_total = len(df)
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Overall diagnostics...")
print(f"  Mean daily return: {np.mean(ret)*252:.4f}")
print(f"  Annualized std: {np.std(ret)*np.sqrt(252):.4f}")
print(f"  Skewness: {stats.skew(ret):.3f}")
print(f"  Kurtosis: {stats.kurtosis(ret):.3f}")
print(f"  VIX range: [{np.min(vix):.1f}, {np.max(vix):.1f}]")
print(f"  VIX mean: {np.mean(vix):.1f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS (Student-t with df=8)
# ============================================================
print("\n[3] Model implementations (Student-t df=8)...")


@njit(cache=True)
def gjr_t_loglik(params, returns, df_val):
    """GJR-GARCH(1,1) with Student-t innovations."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    # Student-t scale adjustment
    scale = (df_val - 2.0) / df_val

    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    # Precompute log-likelihood constant for Student-t
    from scipy.special import gammaln
    # Can't use gammaln inside numba, compute outside
    # Use Gaussian approx inside numba, correct outside
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(h[t]) + (1 + df_val) * np.log(1 + returns[t]**2 / (h[t] * (df_val - 2))))
    return -ll


def gjr_t_loglik_scipy(params, returns, df_val):
    """GJR-GARCH(1,1) with Student-t log-likelihood (scipy version)."""
    from scipy.special import gammaln
    omega, alpha, gamma_p, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])

    for t in range(1, n):
        asym = gamma_p * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    # Student-t log-likelihood
    const = gammaln((df_val + 1) / 2) - gammaln(df_val / 2) - 0.5 * np.log(np.pi * (df_val - 2))
    ll = 0.0
    for t in range(n):
        if h[t] > 0:
            ll += const - 0.5 * np.log(h[t]) - (df_val + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df_val - 2)))
    return -ll


def fit_gjr_t(returns, df_val=8):
    """Fit GJR-GARCH(1,1) with Student-t innovations."""
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
            res = optimize.minimize(gjr_t_loglik_scipy, s, args=(returns, df_val),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_t_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR-t forecast."""
    omega, alpha, gamma_p, beta = params
    asym = gamma_p * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f: Multiplicative GARCH-X with VIX², free omega, Student-t ---
def fit_a4f_t(returns, vix_vals, df_val=8):
    """
    Fit A4f model: σ²_t = τ_t × g_t
    τ_t = θ₀ + θ₁ × VIX²_{t-1}
    g_t follows GJR on de-trended returns, with free omega
    Student-t innovations with df=df_val
    """
    from scipy.special import gammaln
    n = len(returns)

    # Lagged VIX (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8

    # Student-t constant
    t_const = gammaln((df_val + 1) / 2) - gammaln(df_val / 2) - 0.5 * np.log(np.pi * (df_val - 2))

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params

        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        if omega_g <= 0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg

        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])  # denom = tau_t (current, predetermined from VIX_{t-1})
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += t_const - 0.5 * np.log(sigma2) - (df_val + 1) / 2 * np.log(1 + returns[t]**2 / (sigma2 * (df_val - 2)))

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
# SECTION 4: FULL OOS FORECASTING (2013-2026)
# ============================================================
print("\n[4] Running full OOS forecasting from 2013-01-01 to end...")

# We need OOS from 2013 onward (earliest sub-period)
OOS_START = '2013-01-01'
oos_mask = np.array(df.index >= OOS_START)
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  OOS observations: {n_oos} (from {OOS_START})")
print(f"  OOS dates: {df.index[oos_indices[0]].strftime('%Y-%m-%d')} to {df.index[oos_indices[-1]].strftime('%Y-%m-%d')}")
print(f"  Refit every {REFIT_EVERY} days")

# Storage for forecasts
forecasts_gjr = np.full(n_oos, np.nan)
forecasts_a4f = np.full(n_oos, np.nan)
oos_dates = df.index[oos_indices]
oos_r2 = r2[oos_indices]

# State variables
gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None, 'tau_prev': None}

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 500 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR-t
        gjr_params = fit_gjr_t(train_ret, STUDENT_T_DF)
        if gjr_params is not None:
            gjr_state['params'] = gjr_params
            h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_t_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_state['h'] = h

        # A4f-t
        a4f_params = fit_a4f_t(train_ret, train_vix, STUDENT_T_DF)
        if a4f_params is not None:
            a4f_state['params'] = a4f_params
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
            n_train = len(train_ret)

            vix_lag_tr = np.empty(n_train)
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            tau_train = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)

            persist = alpha_p + gamma_p / 2.0 + beta_p
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, n_train):
                u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i], 1e-16))
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)

            a4f_state['g'] = g
            a4f_state['tau_prev'] = tau_train[-1]

    # --- Generate forecasts ---

    # GJR-t forecast
    p = gjr_state['params']
    if p is not None:
        h_prev = gjr_state['h']
        r_prev = ret[abs_idx - 1]
        h_new = gjr_t_forecast_1step(p, h_prev, r_prev)
        forecasts_gjr[t_idx] = h_new
        gjr_state['h'] = h_new

    # A4f-t forecast
    p = a4f_state['params']
    if p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p

        # tau uses lagged VIX (VIX_{t-1})
        vix_prev = vix[abs_idx - 1]
        tau_now = max(theta0 + theta1 * vix_prev**2, 1e-16)

        # g recursion
        g_prev = a4f_state['g']
        r_prev = ret[abs_idx - 1]

        # For g update: use previous tau for denominator of u_{t-1}
        # But A4f uses tau_t (current, predetermined) for denom
        # tau_now is computed from VIX_{t-1}, which is known at time t
        u_prev = r_prev / np.sqrt(tau_now)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        sigma2_forecast = tau_now * g_new
        forecasts_a4f[t_idx] = sigma2_forecast
        a4f_state['g'] = g_new
        a4f_state['tau_prev'] = tau_now

elapsed = time.time() - START_TIME
print(f"\n  OOS forecasting completed in {elapsed:.0f}s, {refit_count} refits")

# ============================================================
# SECTION 5: SUB-PERIOD ANALYSIS
# ============================================================
print("\n[5] Sub-period analysis...")

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'A4f Sub-Period Robustness Analysis',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f'{df.index[0].strftime("%Y-%m-%d")} to {df.index[-1].strftime("%Y-%m-%d")}',
    'n_total': int(n_total),
    'n_oos_total': int(n_oos),
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'student_t_df': STUDENT_T_DF,
    'models': ['A4f-VIX²-t(df=8)', 'GJR-t(df=8)'],
    'evaluation': 'QLIKE on r² (Patton 2011)',
    'sub_periods': {},
    'summary': {},
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey et al. (2016). Testing the accuracy of out-of-sample forecasts.',
    ],
    'seed': 42,
}

# Full OOS metrics
valid_full = np.isfinite(forecasts_gjr) & np.isfinite(forecasts_a4f) & (oos_r2 > 0)
gjr_qlike_full = qlike(oos_r2[valid_full], forecasts_gjr[valid_full])
a4f_qlike_full = qlike(oos_r2[valid_full], forecasts_a4f[valid_full])
loss_gjr_full = qlike_pointwise(oos_r2[valid_full], forecasts_gjr[valid_full])
loss_a4f_full = qlike_pointwise(oos_r2[valid_full], forecasts_a4f[valid_full])
dm_t_full, dm_p_full = dm_test(loss_a4f_full, loss_gjr_full)

print(f"\n  Full OOS ({OOS_START} to end):")
print(f"    GJR QLIKE: {gjr_qlike_full:.6f}")
print(f"    A4f QLIKE: {a4f_qlike_full:.6f}")
print(f"    Improvement: {(gjr_qlike_full - a4f_qlike_full)/gjr_qlike_full*100:.2f}%")
print(f"    DM t-stat: {dm_t_full:.4f} (negative = A4f better)")

results['full_oos'] = {
    'gjr_qlike': float(gjr_qlike_full),
    'a4f_qlike': float(a4f_qlike_full),
    'improvement_pct': float((gjr_qlike_full - a4f_qlike_full)/gjr_qlike_full*100),
    'dm_t_stat': float(dm_t_full),
    'dm_p_value': float(dm_p_full),
    'n_obs': int(valid_full.sum()),
}

# Per sub-period analysis
print("\n  Sub-period results:")
print(f"  {'Period':<6} {'Dates':<24} {'N':>5} {'VIX_avg':>8} {'GJR_QLIKE':>10} {'A4f_QLIKE':>10} {'Improv%':>8} {'DM_t':>8} {'Winner':>8}")
print("  " + "-" * 100)

a4f_wins = 0
period_data = []

for period_key in sorted(SUB_PERIODS.keys()):
    p_start, p_end, p_desc = SUB_PERIODS[period_key]

    # Find OOS indices in this sub-period
    mask = (oos_dates >= p_start) & (oos_dates <= p_end)
    n_period = mask.sum()

    if n_period < 50:
        print(f"  {period_key:<6} {p_start} to {p_end}  N={n_period} (too few, skipped)")
        continue

    r2_p = oos_r2[mask]
    gjr_p = forecasts_gjr[mask]
    a4f_p = forecasts_a4f[mask]

    # Get VIX for this period
    vix_period = df.loc[(df.index >= p_start) & (df.index <= p_end), 'VIX']
    avg_vix = float(vix_period.mean())
    max_vix = float(vix_period.max())
    min_vix = float(vix_period.min())

    # Compute QLIKE
    valid_p = np.isfinite(gjr_p) & np.isfinite(a4f_p) & (r2_p > 0)
    gjr_qlike_p = qlike(r2_p[valid_p], gjr_p[valid_p])
    a4f_qlike_p = qlike(r2_p[valid_p], a4f_p[valid_p])

    # DM test
    loss_gjr_p = qlike_pointwise(r2_p[valid_p], gjr_p[valid_p])
    loss_a4f_p = qlike_pointwise(r2_p[valid_p], a4f_p[valid_p])
    dm_t_p, dm_p_p = dm_test(loss_a4f_p, loss_gjr_p)

    # Improvement
    improv_pct = (gjr_qlike_p - a4f_qlike_p) / gjr_qlike_p * 100 if gjr_qlike_p > 0 else 0.0
    winner = 'A4f' if a4f_qlike_p < gjr_qlike_p else 'GJR'
    if winner == 'A4f':
        a4f_wins += 1

    # Return statistics for this period
    ret_period = df.loc[(df.index >= p_start) & (df.index <= p_end), 'log_ret']
    ann_vol = float(ret_period.std() * np.sqrt(252))
    ann_ret = float(ret_period.mean() * 252)

    print(f"  {period_key:<6} {p_start[:7]}~{p_end[:7]}  {n_period:>5} {avg_vix:>8.1f} {gjr_qlike_p:>10.6f} {a4f_qlike_p:>10.6f} {improv_pct:>+7.2f}% {dm_t_p:>+8.3f} {winner:>8}")

    period_result = {
        'period': period_key,
        'start': p_start,
        'end': p_end,
        'description': p_desc,
        'n_obs': int(valid_p.sum()),
        'avg_vix': round(avg_vix, 2),
        'max_vix': round(max_vix, 2),
        'min_vix': round(min_vix, 2),
        'ann_vol': round(ann_vol, 4),
        'ann_ret': round(ann_ret, 4),
        'gjr_qlike': round(float(gjr_qlike_p), 6),
        'a4f_qlike': round(float(a4f_qlike_p), 6),
        'improvement_pct': round(float(improv_pct), 4),
        'dm_t_stat': round(float(dm_t_p), 4),
        'dm_p_value': round(float(dm_p_p), 4),
        'winner': winner,
    }
    results['sub_periods'][period_key] = period_result
    period_data.append(period_result)

n_periods = len(period_data)
print(f"\n  A4f wins: {a4f_wins}/{n_periods}")

# Summary statistics
improvements = [p['improvement_pct'] for p in period_data]
dm_stats = [p['dm_t_stat'] for p in period_data]
avg_vix_list = [p['avg_vix'] for p in period_data]

results['summary'] = {
    'n_periods': n_periods,
    'a4f_wins': a4f_wins,
    'a4f_win_rate': round(a4f_wins / n_periods, 4) if n_periods > 0 else 0,
    'mean_improvement_pct': round(float(np.mean(improvements)), 4),
    'median_improvement_pct': round(float(np.median(improvements)), 4),
    'min_improvement_pct': round(float(np.min(improvements)), 4),
    'max_improvement_pct': round(float(np.max(improvements)), 4),
    'mean_dm_t_stat': round(float(np.mean(dm_stats)), 4),
    'n_periods_dm_significant_3': int(sum(1 for t in dm_stats if t < -3.0)),
    'n_periods_dm_significant_2': int(sum(1 for t in dm_stats if t < -2.0)),
    'n_periods_dm_significant_1_96': int(sum(1 for t in dm_stats if t < -1.96)),
    'conclusion': '',
}

# Determine conclusion
if a4f_wins >= 5:
    if all(imp > 0 for imp in improvements):
        results['summary']['conclusion'] = 'A4f robustly outperforms GJR across ALL regimes — advantage not driven by any single period'
    else:
        results['summary']['conclusion'] = f'A4f wins {a4f_wins}/{n_periods} periods — robust across most regimes'
elif a4f_wins >= 4:
    # Check if losses correlate with low VIX
    losers = [p for p in period_data if p['winner'] == 'GJR']
    loser_vix = np.mean([p['avg_vix'] for p in losers]) if losers else 0
    winners = [p for p in period_data if p['winner'] == 'A4f']
    winner_vix = np.mean([p['avg_vix'] for p in winners]) if winners else 0
    if loser_vix < winner_vix:
        results['summary']['conclusion'] = f'A4f wins {a4f_wins}/{n_periods} — slight VIX-dependent advantage (loses in lowest VIX periods)'
    else:
        results['summary']['conclusion'] = f'A4f wins {a4f_wins}/{n_periods} — mostly robust'
else:
    results['summary']['conclusion'] = f'A4f wins only {a4f_wins}/{n_periods} — advantage may be regime-specific'

print(f"\n  Conclusion: {results['summary']['conclusion']}")

# Correlation: avg VIX vs QLIKE improvement
if n_periods >= 5:
    vix_arr = np.array(avg_vix_list)
    imp_arr = np.array(improvements)
    corr, corr_p = stats.spearmanr(vix_arr, imp_arr)
    print(f"\n  Spearman(avg_VIX, QLIKE_improvement): rho={corr:.3f}, p={corr_p:.4f}")
    results['summary']['vix_improvement_spearman_rho'] = round(float(corr), 4)
    results['summary']['vix_improvement_spearman_p'] = round(float(corr_p), 4)

# ============================================================
# SECTION 6: CHARTS
# ============================================================
print("\n[6] Generating charts...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# Chart 1: DM t-stat bar chart by sub-period
fig, ax = plt.subplots(figsize=(10, 6))
periods_labels = [f"{p['period']}\n{p['start'][:4]}-{p['end'][:4]}" for p in period_data]
dm_values = [p['dm_t_stat'] for p in period_data]
colors = ['#2ca02c' if t < 0 else '#d62728' for t in dm_values]

bars = ax.bar(periods_labels, dm_values, color=colors, edgecolor='black', linewidth=0.5)

# Add value labels
for bar, val in zip(bars, dm_values):
    y_pos = bar.get_height() + (0.1 if val > 0 else -0.3)
    ax.text(bar.get_x() + bar.get_width()/2, y_pos, f'{val:.2f}',
            ha='center', va='bottom' if val > 0 else 'top', fontsize=10, fontweight='bold')

ax.axhline(y=0, color='black', linewidth=0.8)
ax.axhline(y=-1.96, color='grey', linewidth=0.8, linestyle='--', alpha=0.5, label='t=-1.96')
ax.axhline(y=-3.0, color='red', linewidth=0.8, linestyle='--', alpha=0.5, label='Harvey t=-3.0')
ax.set_ylabel('DM t-statistic (negative = A4f better)', fontsize=12)
ax.set_title(f'{EXPERIMENT_ID}: A4f vs GJR DM Test by Sub-Period\n(Student-t df={STUDENT_T_DF}, QLIKE on r²)', fontsize=13)
ax.legend(loc='upper right')
ax.grid(axis='y', alpha=0.3)

# Add regime descriptions
for i, p in enumerate(period_data):
    ax.text(i, ax.get_ylim()[0] + 0.15, p['description'], ha='center', va='bottom',
            fontsize=7, color='grey', rotation=0)

plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1027_dm_by_period.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")

# Chart 2: Scatter - avg VIX vs QLIKE improvement %
fig, ax = plt.subplots(figsize=(8, 6))
vix_arr = [p['avg_vix'] for p in period_data]
imp_arr = [p['improvement_pct'] for p in period_data]

ax.scatter(vix_arr, imp_arr, s=120, c='steelblue', edgecolors='black', zorder=5)

# Label each point
for p in period_data:
    ax.annotate(f"{p['period']}\n({p['start'][:4]}-{p['end'][:4]})",
                (p['avg_vix'], p['improvement_pct']),
                textcoords="offset points", xytext=(10, 5), fontsize=9)

# Trend line
if n_periods >= 3:
    z = np.polyfit(vix_arr, imp_arr, 1)
    x_line = np.linspace(min(vix_arr) - 1, max(vix_arr) + 1, 100)
    y_line = np.polyval(z, x_line)
    ax.plot(x_line, y_line, 'r--', alpha=0.5, label=f'Linear fit (slope={z[0]:.3f})')

ax.axhline(y=0, color='grey', linewidth=0.8, linestyle='-')
ax.set_xlabel('Average VIX Level', fontsize=12)
ax.set_ylabel('QLIKE Improvement % (A4f vs GJR)', fontsize=12)
ax.set_title(f'{EXPERIMENT_ID}: VIX Level vs A4f Improvement\n(positive = A4f better)', fontsize=13)
if n_periods >= 3:
    ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1027_vix_vs_improvement.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")

# Chart 3: QLIKE comparison bar chart
fig, ax = plt.subplots(figsize=(10, 6))
x = np.arange(n_periods)
width = 0.35

gjr_qlikes = [p['gjr_qlike'] for p in period_data]
a4f_qlikes = [p['a4f_qlike'] for p in period_data]

bars1 = ax.bar(x - width/2, gjr_qlikes, width, label='GJR-t(8)', color='#d62728', alpha=0.8, edgecolor='black', linewidth=0.5)
bars2 = ax.bar(x + width/2, a4f_qlikes, width, label='A4f-VIX²-t(8)', color='#2ca02c', alpha=0.8, edgecolor='black', linewidth=0.5)

ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
ax.set_title(f'{EXPERIMENT_ID}: QLIKE Comparison by Sub-Period', fontsize=13)
ax.set_xticks(x)
ax.set_xticklabels(periods_labels, fontsize=9)
ax.legend()
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
chart3_path = os.path.join(SCRIPT_DIR, 'k1027_qlike_comparison.png')
plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart3_path}")

# ============================================================
# SECTION 7: SAVE RESULTS
# ============================================================
elapsed_total = time.time() - START_TIME
results['runtime_seconds'] = round(elapsed_total, 1)
results['refit_count'] = refit_count

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n  Results saved to: {RESULTS_PATH}")

# ============================================================
# SECTION 8: FINAL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID}: FINAL SUMMARY")
print("=" * 70)
print(f"  Models: A4f-VIX²-t(df={STUDENT_T_DF}) vs GJR-t(df={STUDENT_T_DF})")
print(f"  Window: {WINDOW}, Refit: every {REFIT_EVERY} days")
print(f"  Full OOS QLIKE improvement: {results['full_oos']['improvement_pct']:+.2f}%")
print(f"  Full OOS DM t-stat: {results['full_oos']['dm_t_stat']:.3f}")
print(f"\n  Sub-period results ({n_periods} periods):")
print(f"    A4f win rate: {a4f_wins}/{n_periods} ({a4f_wins/n_periods*100:.0f}%)")
print(f"    Mean QLIKE improvement: {np.mean(improvements):+.2f}%")
print(f"    Improvement range: [{np.min(improvements):+.2f}%, {np.max(improvements):+.2f}%]")
if 'vix_improvement_spearman_rho' in results['summary']:
    print(f"    VIX-Improvement correlation: rho={results['summary']['vix_improvement_spearman_rho']:.3f}")
print(f"\n  Conclusion: {results['summary']['conclusion']}")
print(f"  Runtime: {elapsed_total:.0f}s")
print("=" * 70)
