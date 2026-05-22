#!/usr/bin/env python3
"""
K1391: Leave-COVID-out DM Test for A4f vs GJR (Paper 9 garch-x-vix C1 fix)
===========================================================================
Motivation:
  Paper 9 (garch-x-vix) OOS period 2019-2026 includes COVID-19 crash (VIX peak=82.69).
  v3 review (RANK-1 CRITICAL issue C1): without leave-COVID-out analysis, any VIX-based
  model trivially wins on crisis episodes. This experiment quantifies how much of A4f's
  DM t=4.03 advantage is driven by the COVID episode.

Design:
  - Re-run A4f (tau = theta0 + theta1*VIX^2, free omega) and GJR from K988 protocol
  - Same OOS: 2019-01-01 to latest, W=2000 training window, refit every 63 days
  - Save per-day QLIKE losses for each model
  - Compute DM tests on 4 subperiods:
    (a) Full OOS (verify K988 result)
    (b) Non-COVID: exclude 2020-02-01 to 2020-06-30
    (c) Pre-COVID: 2019-01-01 to 2020-01-31
    (d) COVID window: 2020-02-01 to 2020-06-30
    (e) Post-COVID: 2020-07-01 to 2026-latest

  Signal timing: return at t uses VIX from t-1 (signal.shift(1) equivalent via
  lagged indexing: tau_t computed from VIX[t-1], no lookahead).

Data: paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv (local snapshot)

References:
  - K988 (Multiplicative GARCH-X spec comparison, baseline)
  - consolidated_issues_v3.md C1 CRITICAL (COVID subperiod analysis missing)
  - Diebold & Mariano (2002); Harvey et al. (2016) |t|>3.0 threshold

Author: VolPred Research System
Date: 2026-05-22
Seed: 42
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import optimize

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1391"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1391_results.json')
DATA_PATH = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data',
                          'spy_vix_qqq_eem_fez_2000-2026.csv')

# Configuration (mirrors K988 protocol)
OOS_START = '2019-01-01'
WINDOW = 2000       # training window
REFIT_EVERY = 63    # quarterly refit
COVID_START = '2020-02-01'
COVID_END = '2020-06-30'

print("=" * 70)
print(f"{EXPERIMENT_ID}: Leave-COVID-out DM Test — A4f vs GJR")
print("  Paper 9 garch-x-vix CRITICAL issue C1 fix")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING (local snapshot, no live fetch)
# ============================================================
print("\n[1] Loading data from local snapshot...")
df_raw = pd.read_csv(DATA_PATH, parse_dates=['date'], index_col='date')
df_raw = df_raw.sort_index()

# Use adjusted close for SPY, close for VIX
spy_prices = df_raw['spy_adj_close'].dropna()
vix_close = df_raw['vix_close'].dropna()

# Align and compute log returns
common_idx = spy_prices.index.intersection(vix_close.index)
spy_prices = spy_prices.loc[common_idx]
vix_close = vix_close.loc[common_idx]

log_ret = np.log(spy_prices / spy_prices.shift(1))
df = pd.DataFrame({
    'log_ret': log_ret,
    'VIX': vix_close
}).dropna()

# OOS mask — signal uses VIX[t-1] (lagged), no lookahead risk
oos_mask = df.index >= OOS_START
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS period: {OOS_START} onwards, n_oos={n_oos}")
print(f"  VIX range (OOS): {df.loc[oos_mask, 'VIX'].min():.1f} – {df.loc[oos_mask, 'VIX'].max():.1f}")

ret = df['log_ret'].values
vix = df['VIX'].values

# Lookahead check: VIX used in tau_t is VIX[t-1] (index t-1 in the array)
# This is enforced in the rolling window: when predicting h_{t+1}, we use vix[t]
# as the "lagged VIX" — the current period's VIX, which is known at t.
# No future information enters the forecast.

# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS (A4f and GJR only)
# ============================================================
print("\n[2] Model implementations...")


def gjr_loglik(params, returns):
    """GJR-GARCH(1,1) negative log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = float(np.var(returns[:min(250, n)]))
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0.0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2.0 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) with 3 starting values and stationarity constraint."""
    var0 = float(np.var(returns))
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    # Stationarity: alpha + gamma/2 + beta < 1 (symmetric to A4f g-component constraint)
    constraints = [{'type': 'ineq', 'fun': lambda p: 0.999 - (p[1] + p[2] / 2 + p[3])}]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='SLSQP', bounds=bounds,
                                    constraints=constraints,
                                    options={'maxiter': 500, 'ftol': 1e-9})
            if res.success and res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params if best_params is not None else np.array([var0 * 0.05, 0.05, 0.05, 0.90])


def gjr_variance_series(params, returns):
    """Compute GJR conditional variance series."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = float(np.var(returns[:min(250, n)]))
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0.0 else 0.0
        h[t] = max(omega + alpha * returns[t-1]**2 + asym + beta * h[t-1], 1e-10)
    return h


def a4f_loglik(params, returns, vix_vals):
    """
    A4f: tau_t = max(theta0 + theta1 * VIX^2_{t-1}, eps)
    g_t follows GJR(1,1) with free omega (free_omega = True).
    Standardized return: u_{t-1} = r_{t-1} / sqrt(tau_t) [contemporaneous normalization].

    VIX timing: vix_vals[t] = VIX at time t = VIX_{t}, used as VIX_{t-1} in tau_t.
    So tau_t uses vix_vals[t-1] — correct, no lookahead.
    """
    theta0, theta1, omega_g, alpha_g, gamma_g, beta_g = params
    n = len(returns)
    EPS = 1e-10
    h_g = np.empty(n)
    h_g[0] = 1.0

    # tau_t = theta0 + theta1 * VIX^2_{t-1}: use lagged VIX so tau_t is predetermined
    vix_lag = np.empty_like(vix_vals)
    vix_lag[0] = vix_vals[0]   # warmup: pad t=0 with same-day (negligible, train starts far pre-OOS)
    vix_lag[1:] = vix_vals[:-1]
    tau = np.maximum(theta0 + theta1 * vix_lag**2, EPS)

    ll = 0.0
    for t in range(1, n):
        tau_t = tau[t]
        u_prev = returns[t-1] / max(np.sqrt(tau_t), EPS)  # tau_t uses VIX_{t-1}: predetermined
        asym = gamma_g * u_prev**2 if u_prev < 0.0 else 0.0
        h_g[t] = max(omega_g + alpha_g * u_prev**2 + asym + beta_g * h_g[t-1], EPS)
        sigma2_t = tau_t * h_g[t]
        if sigma2_t > EPS:
            ll += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2_t) + returns[t]**2 / sigma2_t)
    return -ll


def fit_a4f(returns, vix_vals):
    """Fit A4f with multiple starting values."""
    var0 = float(np.var(returns))
    vix_mean_sq = float(np.mean(vix_vals**2))
    # theta0 near 0, theta1 * E[VIX^2] ~ var0
    theta1_start = var0 / max(vix_mean_sq, 1.0)

    starts = [
        [var0 * 0.05, theta1_start, 0.01, 0.05, 0.05, 0.90],
        [var0 * 0.02, theta1_start * 0.5, 0.02, 0.03, 0.08, 0.88],
        [1e-6, theta1_start * 2.0, 0.005, 0.07, 0.10, 0.85],
    ]
    bounds = [
        (0.0, var0 * 2),       # theta0 >= 0
        (1e-10, 1.0),           # theta1 > 0
        (1e-8, var0),           # omega_g > 0
        (1e-4, 0.3),            # alpha_g
        (1e-4, 0.3),            # gamma_g
        (0.5, 0.999),           # beta_g
    ]
    # Stationarity constraint: alpha_g + gamma_g/2 + beta_g < 1
    constraints = [{'type': 'ineq',
                    'fun': lambda p: 0.999 - (p[3] + p[4]/2 + p[5])}]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(a4f_loglik, s, args=(returns, vix_vals),
                                    method='SLSQP', bounds=bounds,
                                    constraints=constraints,
                                    options={'maxiter': 500, 'ftol': 1e-9})
            if res.success and res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    if best_params is None:
        best_params = np.array([var0 * 0.05, theta1_start, 0.01, 0.05, 0.05, 0.90])
    return best_params


def a4f_variance_series(params, returns, vix_vals):
    """Compute A4f conditional variance series. Returns (sigma2, h_g)."""
    theta0, theta1, omega_g, alpha_g, gamma_g, beta_g = params
    n = len(returns)
    EPS = 1e-10
    h_g = np.empty(n)
    h_g[0] = 1.0
    # Consistent with a4f_loglik: tau_t uses VIX_{t-1} (lagged)
    vix_lag = np.empty_like(vix_vals)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    tau = np.maximum(theta0 + theta1 * vix_lag**2, EPS)
    sigma2 = np.empty(n)
    sigma2[0] = tau[0] * h_g[0]
    for t in range(1, n):
        tau_t = tau[t]
        u_prev = returns[t-1] / max(np.sqrt(tau_t), EPS)
        asym = gamma_g * u_prev**2 if u_prev < 0.0 else 0.0
        h_g[t] = max(omega_g + alpha_g * u_prev**2 + asym + beta_g * h_g[t-1], EPS)
        sigma2[t] = tau_t * h_g[t]
    return sigma2, h_g


def qlike_loss(sigma2_hat, r):
    """QLIKE loss: E[r^2/sigma2 - log(r^2/sigma2) - 1], use kernel log(sigma2) + r^2/sigma2."""
    with np.errstate(divide='ignore', invalid='ignore'):
        loss = np.log(sigma2_hat) + r**2 / sigma2_hat
    return loss


# ============================================================
# SECTION 3: ROLLING OOS FORECASTING
# ============================================================
print("\n[3] Rolling OOS forecasting...")
print(f"  Protocol: W={WINDOW}, refit every {REFIT_EVERY} days, OOS start={OOS_START}")

oos_indices = np.where(oos_mask)[0]
n_oos_total = len(oos_indices)
print(f"  OOS observations: {n_oos_total}")

# Storage for per-day losses
gjr_losses = np.full(n_oos_total, np.nan)
a4f_losses = np.full(n_oos_total, np.nan)
oos_dates = df.index[oos_indices]

gjr_params_cached = None
a4f_params_cached = None
last_refit_idx = -REFIT_EVERY  # force refit at start

for i, oos_idx in enumerate(oos_indices):
    if i % 100 == 0:
        print(f"  Progress: {i}/{n_oos_total} ({100*i/n_oos_total:.0f}%)")

    if oos_idx < WINDOW:
        continue  # not enough history

    # Refit parameters every REFIT_EVERY steps
    if (oos_idx - last_refit_idx) >= REFIT_EVERY or gjr_params_cached is None:
        train_idx = slice(oos_idx - WINDOW, oos_idx)
        train_ret = ret[train_idx]
        train_vix = vix[train_idx]
        gjr_params_cached = fit_gjr(train_ret)
        a4f_params_cached = fit_a4f(train_ret, train_vix)
        last_refit_idx = oos_idx

    # GJR: compute h_{t} using all training data up to t-1, predict h_{t}
    # We need h at position oos_idx using params fit on [oos_idx-W, oos_idx)
    train_idx = slice(oos_idx - WINDOW, oos_idx)
    train_ret = ret[train_idx]
    h_series = gjr_variance_series(gjr_params_cached, train_ret)
    # One-step-ahead forecast: h_{t+1} from t
    r_t = train_ret[-1]
    h_t = h_series[-1]
    omega, alpha, gamma, beta = gjr_params_cached
    asym = gamma * r_t**2 if r_t < 0 else 0.0
    h_forecast = max(omega + alpha * r_t**2 + asym + beta * h_t, 1e-10)

    # A4f: forecast sigma2_{oos_idx} (one-step-ahead for return r_{oos_idx})
    # tau_{oos_idx} uses VIX_{oos_idx-1} (lagged, no lookahead) — consistent with training lag convention
    train_ret_a4f = ret[train_idx]
    train_vix_a4f = vix[train_idx]
    sigma2_series_a4f, h_g_series_a4f = a4f_variance_series(a4f_params_cached, train_ret_a4f, train_vix_a4f)

    # vix_for_tau = VIX_{t-1}: consistent with vix_lag shift applied in a4f_variance_series
    vix_for_tau = vix[oos_idx - 1]
    theta0, theta1, omega_g, alpha_g, gamma_g, beta_g = a4f_params_cached
    tau_forecast = max(theta0 + theta1 * vix_for_tau**2, 1e-10)
    # g_last = h_g[-1] from training (sigma2[-1] / tau[-1], extracted directly to avoid tau mismatch)
    g_last = h_g_series_a4f[-1]
    # u_{t-1} = r_{t-1}/sqrt(tau_t): tau_forecast uses VIX_{t-1} so denominator is predetermined
    u_last = train_ret_a4f[-1] / max(np.sqrt(tau_forecast), 1e-10)
    asym_g = gamma_g * u_last**2 if u_last < 0 else 0.0
    g_forecast = max(omega_g + alpha_g * u_last**2 + asym_g + beta_g * g_last, 1e-10)
    a4f_forecast = tau_forecast * g_forecast

    # Actual return at oos_idx
    r_actual = ret[oos_idx]
    r2_actual = r_actual**2

    gjr_losses[i] = float(np.log(h_forecast) + r2_actual / h_forecast)
    a4f_losses[i] = float(np.log(a4f_forecast) + r2_actual / a4f_forecast)


print(f"  Valid OOS days: {np.sum(~np.isnan(gjr_losses))}")

# ============================================================
# SECTION 4: COVID EXCLUSION MASKS
# ============================================================
print("\n[4] Computing subperiod masks...")

# Date masks for subperiods
covid_start_dt = pd.Timestamp(COVID_START)
covid_end_dt = pd.Timestamp(COVID_END)

mask_full = ~np.isnan(gjr_losses)
mask_covid = (oos_dates >= covid_start_dt) & (oos_dates <= covid_end_dt) & mask_full
mask_non_covid = ~mask_covid & mask_full
mask_pre_covid = (oos_dates < covid_start_dt) & mask_full
mask_post_covid = (oos_dates > covid_end_dt) & mask_full

n_full = mask_full.sum()
n_covid = mask_covid.sum()
n_non_covid = mask_non_covid.sum()
n_pre = mask_pre_covid.sum()
n_post = mask_post_covid.sum()

print(f"  Full OOS: {n_full} days")
print(f"  COVID window ({COVID_START} – {COVID_END}): {n_covid} days")
print(f"  Non-COVID: {n_non_covid} days")
print(f"  Pre-COVID: {n_pre} days")
print(f"  Post-COVID: {n_post} days")

# ============================================================
# SECTION 5: DM TESTS
# ============================================================
print("\n[5] DM Tests (Newey-West HAC, q=int(T^(1/3)))...")


def dm_test_hac(loss1, loss2):
    """
    Diebold-Mariano test with Newey-West HAC variance.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t.
    Negative t = loss1 < loss2 (model 1 better).
    """
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return {'t_stat': np.nan, 'p_value': np.nan, 'mean_diff': np.nan, 'n': n}
    d_mean = np.mean(d)
    q = max(1, int(n ** (1/3)))
    # Newey-West variance
    gamma0 = np.mean((d - d_mean)**2)
    nw_var = gamma0
    for lag in range(1, q + 1):
        gamma_lag = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        nw_var += 2 * (1 - lag / (q + 1)) * gamma_lag
    nw_var = max(nw_var, 1e-20)
    t_stat = d_mean / np.sqrt(nw_var / n)
    from scipy import stats as scipy_stats
    p_value = 2 * (1 - scipy_stats.t.cdf(abs(t_stat), df=n - 1))
    return {
        't_stat': float(t_stat),
        'p_value': float(p_value),
        'mean_diff': float(d_mean),
        'n': int(n),
        'harvey_significant': bool(abs(t_stat) > 3.0),
    }


subperiods = {
    'full_oos': mask_full,
    'non_covid': mask_non_covid,
    'pre_covid': mask_pre_covid,
    'covid_window': mask_covid,
    'post_covid': mask_post_covid,
}

dm_results = {}
for name, mask in subperiods.items():
    if mask.sum() < 10:
        dm_results[name] = {'t_stat': np.nan, 'p_value': np.nan, 'n': int(mask.sum()),
                             'note': 'insufficient observations'}
        continue
    l_gjr = gjr_losses[mask]
    l_a4f = a4f_losses[mask]
    result = dm_test_hac(l_gjr, l_a4f)
    result['mean_qlike_gjr'] = float(np.mean(l_gjr))
    result['mean_qlike_a4f'] = float(np.mean(l_a4f))
    dm_results[name] = result
    sig = '*** Harvey-sig' if result.get('harvey_significant') else ''
    print(f"  {name:20s}: DM t={result['t_stat']:+.3f}, p={result['p_value']:.4f}, "
          f"n={result['n']:4d} {sig}")

# ============================================================
# SECTION 6: RESULTS SUMMARY
# ============================================================
full = dm_results.get('full_oos', {})
non_cov = dm_results.get('non_covid', {})

print("\n[6] Key findings:")
print(f"  Full OOS DM t={full.get('t_stat', 'N/A'):.3f} "
      f"(d=loss_gjr-loss_a4f; positive t = A4f better; K988 reported: +4.03)")
print(f"  Non-COVID DM t={non_cov.get('t_stat', 'N/A'):.3f}")
if not np.isnan(full.get('t_stat', np.nan)) and not np.isnan(non_cov.get('t_stat', np.nan)):
    reduction = abs(non_cov['t_stat']) / max(abs(full['t_stat']), 1e-6)
    print(f"  Advantage retention (non-COVID / full): {reduction:.2%}")
    print(f"  COVID driving: {'Yes — significant drop' if reduction < 0.6 else 'Partial' if reduction < 0.8 else 'Minimal — A4f advantage robust'}")

# ============================================================
# SECTION 7: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
results = {
    'experiment_id': EXPERIMENT_ID,
    'run_at': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': round(elapsed, 1),
    'configuration': {
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'covid_start': COVID_START,
        'covid_end': COVID_END,
        'data_source': 'paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv',
        'seed': 42,
    },
    'sample_sizes': {
        'n_full_oos': int(n_full),
        'n_covid': int(n_covid),
        'n_non_covid': int(n_non_covid),
        'n_pre_covid': int(n_pre),
        'n_post_covid': int(n_post),
    },
    'dm_tests': dm_results,
    'per_day_losses': {
        'dates': [str(d.date()) for d in oos_dates[mask_full]],
        'gjr_qlike': gjr_losses[mask_full].tolist(),
        'a4f_qlike': a4f_losses[mask_full].tolist(),
    },
    'metadata': {
        'paper': 'garch-x-vix',
        'issue_addressed': 'C1 CRITICAL — COVID subperiod analysis',
        'review_round': 'v3',
        'reviewer': 'K1391 dedicated experiment',
        'hypothesis': 'H0: A4f advantage is not COVID-driven (non-COVID DM remains Harvey-significant)',
    },
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n[7] Results saved to {RESULTS_PATH}")
print(f"    Elapsed: {elapsed:.1f}s")
print("=" * 70)
print("DONE")
