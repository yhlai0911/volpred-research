#!/usr/bin/env python3
"""
K1066: A4f_oc vs A4f_close — Full Rolling OOS Test (Paper 9 Target Switch?)
==========================================================================
[提出: Claude, 執行: Claude]

Motivation:
  K1065 (Hansen-Lunde 2005 decomposition) found:
  - VIX^2 improves intraday QLIKE by 26% but overnight only 3.9%
  - A4f_oc (fit on open-to-close) QLIKE=0.123 on intraday RV target
  - A4f_close QLIKE=0.322 on intraday RV target
  - DM test A4f_close vs A4f_oc (intraday target): t=+5.38

  But K1065 used single pre-OOS estimation (60-day window).
  K988 (full rolling OOS) uses close-to-close with DM t=4.48 for A4f_close vs GJR_close.

  If A4f_oc beats A4f_close in full rolling OOS, Paper 9 should reconsider
  its main target: "VIX^2 captures open-to-close (trading session) volatility"
  is a stronger and cleaner claim than close-to-close.

Hypotheses:
  H1: A4f_oc vs GJR_oc on r²_oc, DM |t| > 3.0
  H2: DM(A4f_oc vs GJR_oc on r²_oc) > 4.48 (K988 A4f_close vs GJR_close)
  H3: A4f_oc wins 5/5 sub-periods (replicate K1056 stability)

Design (aligned with K988/K1056):
  - 4 models: GJR_close, A4f_close, GJR_oc, A4f_oc
  - SPY 2005-01-01 to 2026-04-12, VIX from yfinance
  - Window: 2000 days, Refit: every 63 days
  - OOS: 2019-01-01 onwards (matching K988)
  - Random seed: 42
  - Proxies: r²_close (K988 target) AND r²_oc (natural for oc models)
  - Sub-periods: P1 PreCOVID, P2 COVID, P3 PostCOVID, P4 RateHike, P5 Recent

References:
  - Engle, Ghysels & Sohn (2013). RES 95(3):776-797. [GARCH-MIDAS]
  - Hansen & Lunde (2005). JAE. [Realized variance decomposition]
  - Patton (2011). J Econometrics 160:246-256. [QLIKE robustness]
  - Harvey et al. (2016). [t > 3.0 threshold]
  - Lai research notes: K988 (A4f_close), K1056 (sub-period), K1065 (decomposition)

Author: VolPred Research System
Date: 2026-04-12
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
EXPERIMENT_ID = "K1066"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1066_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-13'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit
RANDOM_SEED = 42

# K988 reference for H2 comparison
K988_A4F_CLOSE_VS_GJR_CLOSE_DM = 4.482553559343101

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f_oc vs A4f_close Full Rolling OOS")
print("  Paper 9 target reconsideration")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data (SPY + VIX from yfinance)...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)

# Use adjusted close for close-to-close (accounts for splits/dividends)
# For open-to-close, use raw Open and Close (both same day, no adjustment needed for intraday)
close_adj = raw['Adj Close'].copy()
close_raw = raw['Close'].copy()
open_raw = raw['Open'].copy()

# Log returns (no lookahead: all use data at time t)
log_ret_close = np.log(close_adj / close_adj.shift(1))  # close-to-close (adj)
log_ret_oc = np.log(close_raw / open_raw)  # open-to-close (same day, raw)

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({
    'close_adj': close_adj,
    'close_raw': close_raw,
    'open_raw': open_raw,
    'log_ret_close': log_ret_close,
    'log_ret_oc': log_ret_oc,
    'VIX': vix_close,
})
df = df.dropna()

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = int(oos_mask.sum())
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret_close = df['log_ret_close'].values
ret_oc = df['log_ret_oc'].values
vix = df['VIX'].values
r2_close = ret_close ** 2
r2_oc = ret_oc ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_idx_arr = np.where(oos_mask)[0]
oos_ret_close = ret_close[oos_mask]
oos_ret_oc = ret_oc[oos_mask]

print(f"  Close returns: mean={np.mean(oos_ret_close)*252:.4f}, "
      f"std={np.std(oos_ret_close)*np.sqrt(252):.4f}, "
      f"skew={stats.skew(oos_ret_close):.3f}, kurt={stats.kurtosis(oos_ret_close):.3f}")
print(f"  OC returns:    mean={np.mean(oos_ret_oc)*252:.4f}, "
      f"std={np.std(oos_ret_oc)*np.sqrt(252):.4f}, "
      f"skew={stats.skew(oos_ret_oc):.3f}, kurt={stats.kurtosis(oos_ret_oc):.3f}")
print(f"  r²_close mean: {np.mean(r2_close[oos_mask]):.6e}")
print(f"  r²_oc mean:    {np.mean(r2_oc[oos_mask]):.6e}")
print(f"  VIX AC(1): {np.corrcoef(vix[1:], vix[:-1])[0,1]:.4f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) ---
@njit(cache=True)
def gjr_loglik(params, returns):
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
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def init_gjr_h(params, train_ret):
    """Initialize h by running GJR recursion over training set."""
    omega, alpha, gamma, beta = params
    n = len(train_ret)
    h = np.var(train_ret[:min(250, n)])
    for i in range(1, n):
        asym = gamma * train_ret[i-1]**2 if train_ret[i-1] < 0 else 0.0
        h = omega + alpha * train_ret[i-1]**2 + asym + beta * h
        if h < 1e-10:
            h = 1e-10
    return h


# --- A4f: Multiplicative GARCH-X with VIX^2 (free omega) ---
# tau_t = max(theta0 + theta1 * VIX²_{t-1}, eps)
# g_t = omega_g + alpha * u²_{t-1} + gamma * u²_{t-1} * I{u<0} + beta * g_{t-1}
# where u_{t-1} = r_{t-1} / sqrt(tau_t)  [Engle et al. 2013: tau_t predetermined]
# sigma²_t = tau_t * g_t

def fit_a4f(returns, vix_vals):
    """
    Fit A4f: multiplicative GJR with VIX^2 long-run component, free omega.
    Returns: params = [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)

    # Lagged VIX (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
        ll = 0.0

        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])  # denom = tau_t (predetermined)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

        return -ll

    # Initial values (same pattern as K988 A4f_vix2_free_omega)
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),    # theta0
        (1e-8, 1e-3),     # theta1
        (1e-6, 1.0),      # omega_g
        (1e-4, 0.3),      # alpha
        (1e-4, 0.3),      # gamma
        (0.5, 0.999),     # beta
    ]

    best_ll = np.inf
    best_params = None
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


def init_a4f_state(params, train_ret, train_vix):
    """Initialize g state at the end of training set."""
    theta0, theta1, omega_g, alpha, gamma_p, beta = params
    n = len(train_ret)
    vix_lag = np.empty(n)
    vix_lag[0] = train_vix[0]
    vix_lag[1:] = train_vix[:-1]
    tau_train = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

    persist = alpha + gamma_p / 2.0 + beta
    eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
    g = eg
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau_train[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        if g < 1e-10:
            g = 1e-10
    return g, tau_train[-1]


# ============================================================
# SECTION 4: OOS FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")
print(f"  Window: {WINDOW}, Refit every: {REFIT_EVERY}")

model_names = ['GJR_close', 'A4f_close', 'GJR_oc', 'A4f_oc']
forecasts = {name: np.full(n_oos_actual, np.nan) for name in model_names}
theta1_history = {'A4f_close': [], 'A4f_oc': []}
refit_dates = []

states = {name: {'h': None, 'g': None, 'tau_prev': None, 'params': None}
          for name in model_names}

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        refit_dates.append(str(df.index[abs_idx].date()))
        train_start = max(0, abs_idx - WINDOW)

        train_ret_close = ret_close[train_start:abs_idx]
        train_ret_oc = ret_oc[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR_close
        p = fit_gjr(train_ret_close)
        if p is not None:
            states['GJR_close']['params'] = p
            states['GJR_close']['h'] = init_gjr_h(p, train_ret_close)

        # GJR_oc
        p = fit_gjr(train_ret_oc)
        if p is not None:
            states['GJR_oc']['params'] = p
            states['GJR_oc']['h'] = init_gjr_h(p, train_ret_oc)

        # A4f_close
        p = fit_a4f(train_ret_close, train_vix)
        if p is not None:
            states['A4f_close']['params'] = p
            g, tau_prev = init_a4f_state(p, train_ret_close, train_vix)
            states['A4f_close']['g'] = g
            states['A4f_close']['tau_prev'] = tau_prev
            theta1_history['A4f_close'].append({
                'date': str(df.index[abs_idx].date()),
                'theta0': float(p[0]),
                'theta1': float(p[1]),
                'alpha': float(p[3]),
                'gamma': float(p[4]),
                'beta': float(p[5]),
            })

        # A4f_oc
        p = fit_a4f(train_ret_oc, train_vix)
        if p is not None:
            states['A4f_oc']['params'] = p
            g, tau_prev = init_a4f_state(p, train_ret_oc, train_vix)
            states['A4f_oc']['g'] = g
            states['A4f_oc']['tau_prev'] = tau_prev
            theta1_history['A4f_oc'].append({
                'date': str(df.index[abs_idx].date()),
                'theta0': float(p[0]),
                'theta1': float(p[1]),
                'alpha': float(p[3]),
                'gamma': float(p[4]),
                'beta': float(p[5]),
            })

    # --- Generate forecasts for day abs_idx (using info up to abs_idx - 1) ---

    # GJR_close
    p = states['GJR_close']['params']
    if p is not None:
        h_prev = states['GJR_close']['h']
        r_prev = ret_close[abs_idx - 1]
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        forecasts['GJR_close'][t_idx] = h_new
        states['GJR_close']['h'] = h_new

    # GJR_oc
    p = states['GJR_oc']['params']
    if p is not None:
        h_prev = states['GJR_oc']['h']
        r_prev = ret_oc[abs_idx - 1]
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        forecasts['GJR_oc'][t_idx] = h_new
        states['GJR_oc']['h'] = h_new

    # A4f_close
    p = states['A4f_close']['params']
    if p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p
        v_lag = vix[abs_idx - 1]  # VIX at t-1 (predetermined)
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)

        r_prev = ret_close[abs_idx - 1]
        g_prev = states['A4f_close']['g']
        u_prev = r_prev / np.sqrt(tau_t)  # denom = tau_t (Engle et al. 2013)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        forecasts['A4f_close'][t_idx] = tau_t * g_new
        states['A4f_close']['g'] = g_new
        states['A4f_close']['tau_prev'] = tau_t

    # A4f_oc
    p = states['A4f_oc']['params']
    if p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)

        r_prev = ret_oc[abs_idx - 1]
        g_prev = states['A4f_oc']['g']
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        forecasts['A4f_oc'][t_idx] = tau_t * g_new
        states['A4f_oc']['g'] = g_new
        states['A4f_oc']['tau_prev'] = tau_t

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")


# ============================================================
# SECTION 5: EVALUATION (two proxies)
# ============================================================
print("\n[5] Evaluation...")


def newey_west_dm(d_vec):
    """Diebold-Mariano test with Newey-West HAC variance.
    d_vec: difference in losses (positive = first predictor has higher loss)
    Returns: (t-stat, p-value)
    """
    d = np.asarray(d_vec)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    max_lag = int(np.floor(T ** (1/3)))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(hac_var / T)
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


def qlike_loss(forecast, r2):
    """Pointwise QLIKE loss: log(h) + r²/h"""
    return np.log(forecast) + r2 / forecast


def evaluate_model(fc_vec, proxy_vec):
    """Compute QLIKE/MSE/MAE/Spearman for a model on a proxy."""
    valid = np.isfinite(fc_vec) & (fc_vec > 0) & np.isfinite(proxy_vec)
    n = int(valid.sum())
    if n < 100:
        return {'n_valid': n, 'qlike': None, 'mse': None, 'mae': None,
                'spearman_rho': None}
    fc = fc_vec[valid]
    pr = proxy_vec[valid]
    ql = float(np.mean(qlike_loss(fc, pr)))
    mse = float(np.mean((fc - pr) ** 2))
    mae = float(np.mean(np.abs(fc - pr)))
    rho, rho_p = stats.spearmanr(fc, pr)
    return {
        'n_valid': n,
        'qlike': ql,
        'mse': mse,
        'mae': mae,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
    }


oos_r2_close = r2_close[oos_indices]
oos_r2_oc = r2_oc[oos_indices]

results = {
    'experiment_id': EXPERIMENT_ID,
    'description': 'A4f_oc vs A4f_close full rolling OOS — Paper 9 target reconsideration',
    'motivation': (
        'K1065 found VIX² improves intraday QLIKE 26% but overnight only 3.9%. '
        'In single pre-OOS estimation, A4f_oc beat A4f_close on intraday RV '
        '(DM t=+5.38). This experiment tests whether this holds in full rolling '
        'OOS (2019-2026) against K988 baseline.'
    ),
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f'{DATA_START} to {df.index[-1].strftime("%Y-%m-%d")}',
    'n_total': n_total,
    'oos_start': OOS_START,
    'n_oos': n_oos_actual,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'random_seed': RANDOM_SEED,
    'references': [
        'K988: A4f_close vs GJR_close DM t=4.48',
        'K1056: A4f_close sub-period 5/5 robust',
        'K1065: A4f_oc vs A4f_close intraday DM t=+5.38 (single refit)',
        'Engle et al. 2013 RES 95(3)',
        'Hansen & Lunde 2005 JAE',
        'Patton 2011 JoE 160',
        'Harvey et al. 2016',
    ],
    'models': model_names,
    'proxies': {},
    'dm_tests': {},
    'theta1_evolution_summary': {},
}

# Evaluate each model on each proxy
print("\n  Proxy: r²_close")
print(f"  {'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MAE':>12} {'Spearman':>10} {'N':>6}")
print("  " + "-" * 64)
results['proxies']['r2_close'] = {}
for name in model_names:
    eval_res = evaluate_model(forecasts[name], oos_r2_close)
    results['proxies']['r2_close'][name] = eval_res
    if eval_res['qlike'] is not None:
        print(f"  {name:<12} {eval_res['qlike']:>10.4f} {eval_res['mse']:>12.2e} "
              f"{eval_res['mae']:>12.2e} {eval_res['spearman_rho']:>10.4f} "
              f"{eval_res['n_valid']:>6}")

print("\n  Proxy: r²_oc")
print(f"  {'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MAE':>12} {'Spearman':>10} {'N':>6}")
print("  " + "-" * 64)
results['proxies']['r2_oc'] = {}
for name in model_names:
    eval_res = evaluate_model(forecasts[name], oos_r2_oc)
    results['proxies']['r2_oc'][name] = eval_res
    if eval_res['qlike'] is not None:
        print(f"  {name:<12} {eval_res['qlike']:>10.4f} {eval_res['mse']:>12.2e} "
              f"{eval_res['mae']:>12.2e} {eval_res['spearman_rho']:>10.4f} "
              f"{eval_res['n_valid']:>6}")

# DM tests on both proxies
print("\n  DM Tests (Harvey t>3.0 significant):")
print(f"  {'Comparison':<35} {'Proxy':<10} {'DM t':>8} {'p':>10} {'Winner':<15}")
print("  " + "-" * 85)


def run_dm(name1, name2, proxy_vec, proxy_name):
    fc1 = forecasts[name1]
    fc2 = forecasts[name2]
    both_valid = (np.isfinite(fc1) & (fc1 > 0) &
                  np.isfinite(fc2) & (fc2 > 0) &
                  np.isfinite(proxy_vec))
    n = int(both_valid.sum())
    if n < 100:
        return None

    loss1 = qlike_loss(fc1[both_valid], proxy_vec[both_valid])
    loss2 = qlike_loss(fc2[both_valid], proxy_vec[both_valid])
    # d = loss1 - loss2, positive means name1 is WORSE (higher loss) → name2 wins
    d = loss1 - loss2
    t_stat, p_val = newey_west_dm(d)
    winner = name2 if t_stat > 0 else name1
    harvey_sig = abs(t_stat) > 3.0 if np.isfinite(t_stat) else False
    return {
        'n': n,
        'proxy': proxy_name,
        'dm_t': t_stat,
        'dm_p': p_val,
        'winner': winner,
        'harvey_significant': bool(harvey_sig),
        'mean_diff': float(np.mean(d)),
    }


dm_pairs = [
    # (name1, name2, description)
    # Convention: d = loss1 - loss2; positive t means name2 wins
    ('GJR_close', 'A4f_close', 'A4f_close vs GJR_close'),
    ('GJR_oc',    'A4f_oc',    'A4f_oc vs GJR_oc'),
    ('A4f_close', 'A4f_oc',    'A4f_oc vs A4f_close'),
    ('GJR_close', 'GJR_oc',    'GJR_oc vs GJR_close'),
    ('A4f_close', 'GJR_oc',    'GJR_oc vs A4f_close'),
    ('GJR_close', 'A4f_oc',    'A4f_oc vs GJR_close'),
]

proxy_map = [('r2_close', oos_r2_close), ('r2_oc', oos_r2_oc)]
for name1, name2, desc in dm_pairs:
    for proxy_name, proxy_vec in proxy_map:
        dm_res = run_dm(name1, name2, proxy_vec, proxy_name)
        if dm_res is None:
            continue
        key = f'{desc}__{proxy_name}'
        results['dm_tests'][key] = dm_res
        sig_str = '***' if dm_res['harvey_significant'] else (
            '*' if abs(dm_res['dm_t']) > 1.96 else '')
        print(f"  {desc:<35} {proxy_name:<10} {dm_res['dm_t']:>+8.3f} "
              f"{dm_res['dm_p']:>10.4f} {dm_res['winner']:<15} {sig_str}")


# ============================================================
# SECTION 6: SUB-PERIOD STABILITY (replicate K1056 for A4f_oc)
# ============================================================
print("\n[6] Sub-period stability analysis (A4f_oc vs GJR_oc on r²_oc)...")

sub_periods = [
    ('P1_PreCOVID',  '2015-01-01', '2019-12-31'),
    ('P2_COVID',     '2020-01-01', '2021-06-30'),
    ('P3_PostCOVID', '2021-07-01', '2022-12-31'),
    ('P4_RateHike',  '2023-01-01', '2024-06-30'),
    ('P5_Recent',    '2024-07-01', df.index[-1].strftime('%Y-%m-%d')),
]

oos_dates = df.index[oos_indices]
sub_period_results = {}

print(f"  {'Period':<15} {'N':>5} {'GJR_oc QL':>10} {'A4f_oc QL':>10} "
      f"{'Imp%':>7} {'DM t':>8} {'Harvey':>8}")
print("  " + "-" * 78)

for label, start_str, end_str in sub_periods:
    start_dt = pd.Timestamp(start_str)
    end_dt = pd.Timestamp(end_str)
    mask = (oos_dates >= start_dt) & (oos_dates <= end_dt)
    n_sub = int(mask.sum())

    if n_sub < 50:
        print(f"  {label:<15} {n_sub:>5} (too few)")
        sub_period_results[label] = {'n_obs': n_sub, 'status': 'insufficient'}
        continue

    fc_gjr = forecasts['GJR_oc'][mask]
    fc_a4f = forecasts['A4f_oc'][mask]
    pr_sub = oos_r2_oc[mask]
    date_sub = oos_dates[mask]

    valid = (np.isfinite(fc_gjr) & (fc_gjr > 0) &
             np.isfinite(fc_a4f) & (fc_a4f > 0) &
             np.isfinite(pr_sub))
    n_valid = int(valid.sum())
    if n_valid < 50:
        sub_period_results[label] = {'n_obs': n_sub, 'status': 'insufficient_valid'}
        continue

    fc_gjr_v = fc_gjr[valid]
    fc_a4f_v = fc_a4f[valid]
    pr_v = pr_sub[valid]

    ql_gjr = float(np.mean(qlike_loss(fc_gjr_v, pr_v)))
    ql_a4f = float(np.mean(qlike_loss(fc_a4f_v, pr_v)))
    imp_pct = (ql_gjr - ql_a4f) / ql_gjr * 100

    # DM: d = loss_gjr - loss_a4f; positive t → A4f_oc wins
    d = qlike_loss(fc_gjr_v, pr_v) - qlike_loss(fc_a4f_v, pr_v)
    t_stat, p_val = newey_west_dm(d)

    rho_gjr, _ = stats.spearmanr(fc_gjr_v, pr_v)
    rho_a4f, _ = stats.spearmanr(fc_a4f_v, pr_v)
    mean_vix_sub = float(np.mean(vix[oos_indices[mask]]))

    a4f_better = ql_a4f < ql_gjr
    harvey_sig = abs(t_stat) > 3.0 if np.isfinite(t_stat) else False

    sub_period_results[label] = {
        'n_obs': n_valid,
        'date_range': f'{start_str} to {end_str}',
        'mean_vix': mean_vix_sub,
        'gjr_oc_qlike': ql_gjr,
        'a4f_oc_qlike': ql_a4f,
        'improvement_pct': float(imp_pct),
        'a4f_better': bool(a4f_better),
        'dm_t': float(t_stat) if np.isfinite(t_stat) else None,
        'dm_p': float(p_val) if np.isfinite(p_val) else None,
        'harvey_significant': bool(harvey_sig),
        'direction': 'A4f_oc_better' if a4f_better else 'GJR_oc_better',
        'spearman_gjr_oc': float(rho_gjr),
        'spearman_a4f_oc': float(rho_a4f),
    }

    print(f"  {label:<15} {n_valid:>5} {ql_gjr:>10.4f} {ql_a4f:>10.4f} "
          f"{imp_pct:>+7.2f} {t_stat:>+8.3f} {'YES' if harvey_sig else 'No':>8}")

results['sub_periods'] = sub_period_results

# Sub-period summary
n_sub_ok = sum(1 for v in sub_period_results.values()
               if isinstance(v.get('a4f_better'), bool))
n_a4f_wins = sum(1 for v in sub_period_results.values()
                 if v.get('a4f_better') is True)
n_harvey_sig = sum(1 for v in sub_period_results.values()
                   if v.get('harvey_significant') is True)

# Binomial p-value (one-sided, H0: p=0.5)
if n_sub_ok > 0:
    try:
        binom_p = stats.binomtest(n_a4f_wins, n_sub_ok, 0.5, alternative='greater').pvalue
    except AttributeError:
        binom_p = stats.binom_test(n_a4f_wins, n_sub_ok, 0.5, alternative='greater')
else:
    binom_p = None

results['sub_period_summary'] = {
    'n_periods': n_sub_ok,
    'n_a4f_oc_wins': n_a4f_wins,
    'n_harvey_significant': n_harvey_sig,
    'binomial_p_greater': float(binom_p) if binom_p is not None else None,
    'all_periods_a4f_oc_better': n_a4f_wins == n_sub_ok,
}
print(f"\n  Sub-period summary: {n_a4f_wins}/{n_sub_ok} A4f_oc wins, "
      f"{n_harvey_sig} Harvey significant, binomial p={binom_p:.4f}" if binom_p is not None
      else f"\n  Sub-period summary: {n_a4f_wins}/{n_sub_ok} A4f_oc wins")


# ============================================================
# SECTION 7: HYPOTHESIS VERDICTS
# ============================================================
print("\n[7] Hypothesis verdicts...")

# H1: A4f_oc vs GJR_oc on r²_oc, DM |t| > 3.0
dm_h1 = results['dm_tests'].get('A4f_oc vs GJR_oc__r2_oc')
h1_pass = False
h1_t = None
if dm_h1 is not None:
    h1_t = dm_h1['dm_t']
    h1_pass = (abs(h1_t) > 3.0) and (dm_h1['winner'] == 'A4f_oc')

# H2: DM(A4f_oc vs GJR_oc on r²_oc) > K988 DM(A4f_close vs GJR_close)=4.48
h2_pass = False
if h1_t is not None and dm_h1['winner'] == 'A4f_oc':
    h2_pass = h1_t > K988_A4F_CLOSE_VS_GJR_CLOSE_DM

# H3: A4f_oc wins 5/5 sub-periods
h3_pass = (n_a4f_wins == n_sub_ok) and (n_sub_ok == 5)

results['hypotheses'] = {
    'H1_A4f_oc_beats_GJR_oc_on_r2_oc': {
        'claim': 'A4f_oc vs GJR_oc on r²_oc, DM |t| > 3.0 (Harvey threshold)',
        'dm_t': float(h1_t) if h1_t is not None else None,
        'threshold': 3.0,
        'verdict': 'PASS' if h1_pass else 'FAIL',
    },
    'H2_A4f_oc_stronger_than_K988_A4f_close': {
        'claim': (f'DM(A4f_oc vs GJR_oc on r²_oc) > {K988_A4F_CLOSE_VS_GJR_CLOSE_DM:.2f} '
                  '(K988 A4f_close vs GJR_close)'),
        'dm_t_oc': float(h1_t) if h1_t is not None else None,
        'benchmark': K988_A4F_CLOSE_VS_GJR_CLOSE_DM,
        'verdict': 'PASS' if h2_pass else 'FAIL',
    },
    'H3_A4f_oc_stable_across_subperiods': {
        'claim': 'A4f_oc wins all 5 sub-periods (replicate K1056 for A4f_close)',
        'n_wins': n_a4f_wins,
        'n_periods': n_sub_ok,
        'n_harvey_sig': n_harvey_sig,
        'verdict': 'PASS' if h3_pass else 'FAIL',
    },
}

print(f"  H1 (A4f_oc DM |t|>3.0 vs GJR_oc on r²_oc): "
      f"t={h1_t:.3f} → {'PASS' if h1_pass else 'FAIL'}" if h1_t is not None
      else "  H1: insufficient data")
print(f"  H2 (A4f_oc DM t > {K988_A4F_CLOSE_VS_GJR_CLOSE_DM:.2f}): "
      f"{'PASS' if h2_pass else 'FAIL'}")
print(f"  H3 (A4f_oc 5/5 sub-periods): "
      f"{n_a4f_wins}/{n_sub_ok} → {'PASS' if h3_pass else 'FAIL'}")

# Paper 9 implications
all_pass = h1_pass and h2_pass and h3_pass
any_pass = h1_pass or h2_pass or h3_pass
if all_pass:
    paper9_rec = 'SWITCH_TARGET: Paper 9 should use r²_oc (open-to-close) as main target.'
elif h1_pass and h3_pass and not h2_pass:
    paper9_rec = ('DUAL_TARGET: A4f_oc robust but not stronger than K988 A4f_close. '
                  'Paper 9 can present both, emphasizing decomposition insight.')
elif h1_pass and not h3_pass:
    paper9_rec = ('ROBUSTNESS_SECTION: A4f_oc significant overall but not across all sub-periods. '
                  'Add to robustness section, keep close-to-close as main.')
elif any_pass:
    paper9_rec = 'PARTIAL: Mixed evidence. Add intraday attribution section only.'
else:
    paper9_rec = 'NO_CHANGE: K1065 single-refit result was sample artifact. Paper 9 unchanged.'

results['paper9_recommendation'] = paper9_rec
print(f"\n  Paper 9 recommendation: {paper9_rec}")


# ============================================================
# SECTION 8: THETA1 EVOLUTION SUMMARY
# ============================================================
print("\n[8] Theta1 evolution summary...")
for mname in ['A4f_close', 'A4f_oc']:
    th = theta1_history[mname]
    if th:
        theta1_vals = [x['theta1'] for x in th]
        theta0_vals = [x['theta0'] for x in th]
        results['theta1_evolution_summary'][mname] = {
            'n_refits': len(th),
            'theta1_mean': float(np.mean(theta1_vals)),
            'theta1_std': float(np.std(theta1_vals)),
            'theta1_min': float(np.min(theta1_vals)),
            'theta1_max': float(np.max(theta1_vals)),
            'theta0_mean': float(np.mean(theta0_vals)),
        }
        print(f"  {mname}: theta1 mean={np.mean(theta1_vals):.2e}, "
              f"std={np.std(theta1_vals):.2e}, "
              f"range=[{np.min(theta1_vals):.2e}, {np.max(theta1_vals):.2e}]")

# Store full theta1 history
results['theta1_history'] = theta1_history
results['refit_dates'] = refit_dates

# Save results
results['elapsed_seconds'] = time.time() - START_TIME
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved: {RESULTS_PATH}")


# ============================================================
# SECTION 9: PLOTS
# ============================================================
print("\n[9] Generating plots...")
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Plot 1: DM t-stat matrix
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for idx, proxy_name in enumerate(['r2_close', 'r2_oc']):
        ax = axes[idx]
        dm_matrix = np.full((4, 4), np.nan)
        for i, n1 in enumerate(model_names):
            for j, n2 in enumerate(model_names):
                if i == j:
                    continue
                # Look up DM test key (name2 wins if positive)
                for key, res in results['dm_tests'].items():
                    # key format: 'NameA vs NameB__proxy'
                    if not key.endswith(f'__{proxy_name}'):
                        continue
                    # parse winner column from res
                    pass
                # direct: run mini DM
                fc1 = forecasts[n1]
                fc2 = forecasts[n2]
                proxy_vec = oos_r2_close if proxy_name == 'r2_close' else oos_r2_oc
                both_valid = (np.isfinite(fc1) & (fc1 > 0) &
                              np.isfinite(fc2) & (fc2 > 0) &
                              np.isfinite(proxy_vec))
                if both_valid.sum() < 100:
                    continue
                loss1 = qlike_loss(fc1[both_valid], proxy_vec[both_valid])
                loss2 = qlike_loss(fc2[both_valid], proxy_vec[both_valid])
                d = loss1 - loss2  # positive: n2 better
                t_stat, _ = newey_west_dm(d)
                dm_matrix[i, j] = t_stat

        im = ax.imshow(dm_matrix, cmap='RdBu_r', vmin=-8, vmax=8, aspect='auto')
        ax.set_xticks(range(4))
        ax.set_yticks(range(4))
        ax.set_xticklabels(model_names, rotation=45, ha='right')
        ax.set_yticklabels(model_names)
        ax.set_title(f'DM t-stat: col wins over row (proxy={proxy_name})')
        ax.set_xlabel('Winning model (column)')
        ax.set_ylabel('Losing model (row)')
        for i in range(4):
            for j in range(4):
                if not np.isnan(dm_matrix[i, j]):
                    color = 'white' if abs(dm_matrix[i, j]) > 4 else 'black'
                    ax.text(j, i, f'{dm_matrix[i, j]:+.2f}', ha='center', va='center',
                            color=color, fontsize=9)
        plt.colorbar(im, ax=ax, label='DM t-stat')

    plt.tight_layout()
    p1 = os.path.join(SCRIPT_DIR, 'k1066_dm_comparison.png')
    plt.savefig(p1, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p1}")

    # Plot 2: Sub-period stability for A4f_oc
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    labels_sub = []
    dm_ts = []
    imps = []
    colors_sub = []
    for label, _, _ in sub_periods:
        res_sub = sub_period_results.get(label, {})
        if isinstance(res_sub.get('dm_t'), float):
            labels_sub.append(label)
            dm_ts.append(res_sub['dm_t'])
            imps.append(res_sub['improvement_pct'])
            colors_sub.append('green' if res_sub.get('harvey_significant') else
                              'orange' if res_sub.get('a4f_better') else 'red')

    x = np.arange(len(labels_sub))
    bars = ax.bar(x, dm_ts, color=colors_sub, alpha=0.7)
    ax.axhline(y=3.0, color='red', linestyle='--', label='Harvey t=3.0')
    ax.axhline(y=-3.0, color='red', linestyle='--')
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels_sub, rotation=30, ha='right')
    ax.set_ylabel('DM t-stat (A4f_oc vs GJR_oc on r²_oc)')
    ax.set_title(f'K1066: A4f_oc sub-period stability '
                 f'({n_a4f_wins}/{n_sub_ok} wins, {n_harvey_sig} Harvey sig)')
    ax.legend()

    # Add improvement % labels
    for i, (t, imp) in enumerate(zip(dm_ts, imps)):
        ax.text(i, t + 0.3 if t >= 0 else t - 0.5, f'{imp:+.1f}%',
                ha='center', fontsize=9)

    plt.tight_layout()
    p2 = os.path.join(SCRIPT_DIR, 'k1066_subperiod_stability.png')
    plt.savefig(p2, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p2}")

    # Plot 3: theta1 evolution
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for ax, mname in zip(axes, ['A4f_close', 'A4f_oc']):
        th = theta1_history[mname]
        if th:
            dates = [pd.Timestamp(x['date']) for x in th]
            theta1_vals = [x['theta1'] for x in th]
            theta0_vals = [x['theta0'] for x in th]
            ax.plot(dates, theta1_vals, 'o-', label='theta1 (VIX² coef)',
                    color='#2196F3')
            ax_tw = ax.twinx()
            ax_tw.plot(dates, theta0_vals, 's-', label='theta0 (intercept)',
                       color='#FF9800', alpha=0.5)
            ax.set_ylabel('theta1', color='#2196F3')
            ax_tw.set_ylabel('theta0', color='#FF9800')
            ax.set_title(f'{mname}: Parameter evolution (refit every {REFIT_EVERY} days)')
            ax.grid(alpha=0.3)
    axes[-1].set_xlabel('Refit Date')
    plt.tight_layout()
    p3 = os.path.join(SCRIPT_DIR, 'k1066_theta1_evolution.png')
    plt.savefig(p3, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p3}")

except Exception as e:
    print(f"  Plot error: {e}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*70}")
print(f"K1066 COMPLETE. Total time: {time.time() - START_TIME:.0f}s")
print(f"{'='*70}")
