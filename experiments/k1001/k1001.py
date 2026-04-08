#!/usr/bin/env python3
"""
K1001: Conrad & Loch (2015) Macro GARCH-X vs VIX GARCH-X Comparison
====================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 found A4f_VIX (τ = θ₀ + θ₁·VIX²_{t-1}, free ω) significantly beats
  GJR (DM t=+4.48). This experiment asks: does VIX GARCH-X also beat
  macro-variable GARCH-X models?

  Conrad & Loch (2015, JAE 30(7):1090-1114) used GARCH-MIDAS with macro
  variables (term spread, housing starts, corporate profits, unemployment)
  to drive the long-run component τ.

  If VIX >> macro → market-implied info dominates macro fundamentals
  If VIX ≈ macro → both channels contribute
  If VIX+macro > VIX alone → macro adds incremental info

Models:
  1. GJR_N: GJR-GARCH(1,1) Normal — benchmark
  2. A4f_VIX: τ = θ₀ + θ₁·VIX²_{t-1}, free ω — K988 champion
  3. Macro_TermSpread: τ = exp(θ₀ + θ₁·TermSpread_{t-1})
  4. Macro_Unemployment: τ = exp(θ₀ + θ₁·UnempRate_{t-1})
  5. Macro_Combined: τ = exp(θ₀ + θ₁·TermSpread + θ₂·UnempRate)
  6. VIX_Macro: τ = θ₀ + θ₁·VIX² + θ₂·TermSpread

  All models use GJR short-run g_t with free ω (for fair comparison).

References:
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility.
    JAE 30(7):1090-1114.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - K988: VIX GARCH-X A4f champion (DM t=+4.48 vs GJR)

Data: SPY 2005-2026, VIX from yfinance, macro from FRED.
OOS: 2019-01-01 to latest. w=2000, refit/63d.
Evaluation: QLIKE on r² (Patton 2011), pairwise DM test, Spearman ρ.

Author: VolPred Research System
Date: 2026-04-08
"""

import os
import sys
import json
import time
import warnings
import requests
import io
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1001"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1001_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit

print("=" * 70)
print(f"{EXPERIMENT_ID}: Conrad-Loch Macro GARCH-X vs VIX GARCH-X")
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

# --- FRED macro data ---
print("  Loading FRED macro data...")


def fetch_fred(series_id, start, end):
    """Fetch FRED data via direct CSV download."""
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}'
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), parse_dates=['observation_date'],
                     index_col='observation_date')
    df.columns = [series_id]
    # Replace '.' with NaN (FRED uses '.' for missing)
    df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
    return df


gs10 = fetch_fred('GS10', DATA_START, DATA_END)
tb3ms = fetch_fred('TB3MS', DATA_START, DATA_END)
unrate = fetch_fred('UNRATE', DATA_START, DATA_END)

# Term spread = 10Y - 3M
macro = gs10.join(tb3ms, how='outer').join(unrate, how='outer')
macro['TermSpread'] = macro['GS10'] - macro['TB3MS']
macro['UnempRate'] = macro['UNRATE']

# Forward-fill monthly data to daily frequency, then lag by 1 month
# to avoid lookahead (use previous month's value)
macro_daily = macro[['TermSpread', 'UnempRate']].resample('D').ffill()

# Lag by 1 month: shift forward by ~22 trading days (use 30 calendar days)
# This ensures we only use data that was publicly available
macro_daily_lagged = macro_daily.shift(30)  # 30 calendar days lag

print(f"  GS10: {len(gs10)} obs, TB3MS: {len(tb3ms)} obs, UNRATE: {len(unrate)} obs")
print(f"  Term spread range: {macro['TermSpread'].min():.2f} to {macro['TermSpread'].max():.2f}")
print(f"  Unemployment range: {macro['UnempRate'].min():.1f}% to {macro['UnempRate'].max():.1f}%")

# Combine all data
df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.join(macro_daily_lagged, how='left')
df = df.dropna(subset=['log_ret', 'VIX', 'TermSpread', 'UnempRate'])

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
term_spread = df['TermSpread'].values
unemp_rate = df['UnempRate'].values

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
print(f"  OOS mean return (ann): {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std (ann): {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
print(f"  VIX autocorr(1): {np.corrcoef(vix[1:], vix[:-1])[0,1]:.4f}")
print(f"  TermSpread autocorr(1): {np.corrcoef(term_spread[1:], term_spread[:-1])[0,1]:.4f}")
print(f"  UnempRate autocorr(1): {np.corrcoef(unemp_rate[1:], unemp_rate[:-1])[0,1]:.4f}")

# Correlations between macro vars and r²
oos_idx = np.where(oos_mask)[0]
print(f"\n  Correlations with r² (OOS):")
print(f"    VIX²: {np.corrcoef(vix[oos_idx-1]**2, r2[oos_idx])[0,1]:.4f}")
print(f"    TermSpread: {np.corrcoef(term_spread[oos_idx-1], r2[oos_idx])[0,1]:.4f}")
print(f"    UnempRate: {np.corrcoef(unemp_rate[oos_idx-1], r2[oos_idx])[0,1]:.4f}")

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


# --- Generic Multiplicative GARCH-X with external regressors ---
def fit_mfgjr_generic(returns, X_ext, tau_type='exp', n_ext=1):
    """
    Fit multiplicative GJR model: σ² = τ × g

    tau_type:
      'exp': τ = exp(θ₀ + θ₁·x₁ + ...), good for macro vars
      'linear': τ = max(θ₀ + θ₁·x₁ + ..., eps), good for VIX²

    X_ext: array of shape (n, n_ext), lagged external regressors
    All models use free ω for fair comparison.
    """
    n = len(returns)

    # Initial theta from OLS on log(r²)
    r2_pos = np.maximum(returns**2, 1e-16)
    log_r2 = np.log(r2_pos)
    X_design = np.column_stack([np.ones(n), X_ext])
    theta_init = np.linalg.lstsq(X_design, log_r2, rcond=None)[0]

    n_theta = 1 + n_ext  # intercept + regressors

    def neg_loglik(params):
        theta = params[:n_theta]
        omega_g = params[n_theta]
        alpha = params[n_theta + 1]
        gamma_p = params[n_theta + 2]
        beta = params[n_theta + 3]

        # Compute tau
        linear_comb = X_design @ theta
        if tau_type == 'exp':
            tau = np.exp(np.clip(linear_comb, -20, 20))
            tau = np.maximum(tau, 1e-16)
        else:  # linear
            tau = np.maximum(linear_comb, 1e-16)

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

    # Build starting values
    for omega_start in [0.05, 0.10, 0.02]:
        for alpha_start, gamma_start, beta_start in [(0.05, 0.05, 0.90), (0.03, 0.08, 0.88), (0.08, 0.10, 0.80)]:
            start = list(theta_init) + [omega_start, alpha_start, gamma_start, beta_start]

            if tau_type == 'exp':
                theta_bounds = [(-20, 5)] * n_theta
            else:  # linear (VIX²)
                # For VIX²: intercept can be small, coefficient must be positive
                theta_bounds = [(-1e-2, 1e-2)]  # intercept
                for j in range(n_ext):
                    theta_bounds.append((1e-8, 1e-3))  # VIX² coefficient

            bounds = theta_bounds + [
                (1e-6, 1.0),    # omega_g
                (1e-4, 0.3),    # alpha
                (1e-4, 0.3),    # gamma
                (0.5, 0.999),   # beta
            ]

            try:
                res = optimize.minimize(neg_loglik, start, method='L-BFGS-B',
                                        bounds=bounds, options={'maxiter': 500})
                if res.fun < best_ll:
                    best_ll = res.fun
                    best_params = res.x
            except Exception:
                continue

    # Special starting values for VIX² linear models
    if tau_type == 'linear':
        var0 = np.var(returns)
        x_mean = np.mean(X_ext[:, 0]) + 1e-8
        extra_starts = [
            [var0 * 0.1, var0 / x_mean] + [0.0] * (n_ext - 1) + [0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / x_mean * 0.5] + [0.0] * (n_ext - 1) + [0.10, 0.03, 0.08, 0.88],
        ]
        theta_bounds_vix = [(-1e-2, 1e-2)]
        for j in range(n_ext):
            theta_bounds_vix.append((1e-8, 1e-3))
        bounds_vix = theta_bounds_vix + [(1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

        for start in extra_starts:
            if len(start) != len(bounds_vix):
                continue
            try:
                res = optimize.minimize(neg_loglik, start, method='L-BFGS-B',
                                        bounds=bounds_vix, options={'maxiter': 500})
                if res.fun < best_ll:
                    best_ll = res.fun
                    best_params = res.x
            except Exception:
                continue

    return best_params


def compute_tau_generic(theta, X_ext_row, tau_type):
    """Compute tau for a single observation given theta and external regressors."""
    linear_comb = theta[0] + np.dot(theta[1:], X_ext_row)
    if tau_type == 'exp':
        return max(np.exp(np.clip(linear_comb, -20, 20)), 1e-16)
    else:  # linear
        return max(linear_comb, 1e-16)


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")

# Model definitions
# Format: (name, tau_type, ext_vars_func, n_ext)
# ext_vars_func: lambda that creates X_ext from (vix, term_spread, unemp_rate) arrays
model_defs = {
    'GJR_N': None,  # Standard GJR, no tau
    'A4f_VIX': ('linear', lambda v, ts, ur: v**2, 1),
    'Macro_TermSpread': ('exp', lambda v, ts, ur: ts, 1),
    'Macro_Unemployment': ('exp', lambda v, ts, ur: ur, 1),
    'Macro_Combined': ('exp', lambda v, ts, ur: np.column_stack([ts, ur]), 2),
    'VIX_Macro': ('linear', lambda v, ts, ur: np.column_stack([v**2, ts]), 2),
}

model_names = list(model_defs.keys())
forecasts = {name: np.full(n_oos_actual, np.nan) for name in model_names}
param_history = {name: [] for name in model_names}

# State variables
states = {}
for name in model_names:
    states[name] = {'h': None, 'g': None, 'tau_prev': None, 'params': None, 'n_theta': None}

print(f"  Models: {model_names}")
print(f"  Refit every {REFIT_EVERY} days")

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]
        train_ts = term_spread[train_start:abs_idx]
        train_ur = unemp_rate[train_start:abs_idx]

        # --- GJR benchmark ---
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            states['GJR_N']['params'] = gjr_params
            # Initialize h from last training obs
            h = np.var(train_ret[:250])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            states['GJR_N']['h'] = h
            param_history['GJR_N'].append({
                'omega': float(gjr_params[0]), 'alpha': float(gjr_params[1]),
                'gamma': float(gjr_params[2]), 'beta': float(gjr_params[3]),
                'persist': float(gjr_params[1] + gjr_params[2]/2 + gjr_params[3])
            })

        # --- Multiplicative models ---
        for name, mdef in model_defs.items():
            if mdef is None:
                continue
            tau_type, ext_func, n_ext = mdef

            # Build lagged external regressors for training
            ext_raw = ext_func(train_vix, train_ts, train_ur)
            if ext_raw.ndim == 1:
                ext_raw = ext_raw.reshape(-1, 1)

            # Lag by 1 day (use t-1 values)
            X_ext_lagged = np.empty_like(ext_raw)
            X_ext_lagged[0, :] = ext_raw[0, :]
            X_ext_lagged[1:, :] = ext_raw[:-1, :]

            params = fit_mfgjr_generic(train_ret, X_ext_lagged, tau_type, n_ext)

            if params is not None:
                n_theta = 1 + n_ext
                states[name]['params'] = params
                states[name]['n_theta'] = n_theta

                # Run through training to get final g state
                theta = params[:n_theta]
                omega_g = params[n_theta]
                alpha_p = params[n_theta + 1]
                gamma_p = params[n_theta + 2]
                beta_p = params[n_theta + 3]
                persist = alpha_p + gamma_p / 2.0 + beta_p
                eg = omega_g / max(1.0 - persist, 1e-6)

                g = eg
                tau_prev = None
                for i in range(1, len(train_ret)):
                    x_row = X_ext_lagged[i, :]
                    tau_cur = compute_tau_generic(theta, x_row, tau_type)
                    u_prev = train_ret[i-1] / np.sqrt(tau_cur)
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)
                    tau_prev = tau_cur

                states[name]['g'] = g
                states[name]['tau_prev'] = tau_prev

                param_history[name].append({
                    'theta': [float(x) for x in theta],
                    'omega_g': float(omega_g), 'alpha': float(alpha_p),
                    'gamma': float(gamma_p), 'beta': float(beta_p),
                    'persist': float(persist)
                })

    # --- Forecast at t ---
    r_prev = ret[abs_idx - 1]
    vix_prev = vix[abs_idx - 1]
    ts_prev = term_spread[abs_idx - 1]
    ur_prev = unemp_rate[abs_idx - 1]

    # GJR
    if states['GJR_N']['params'] is not None:
        h_new = gjr_forecast_1step(states['GJR_N']['params'], states['GJR_N']['h'], r_prev)
        forecasts['GJR_N'][t_idx] = h_new
        states['GJR_N']['h'] = h_new

    # Multiplicative models
    for name, mdef in model_defs.items():
        if mdef is None:
            continue
        tau_type, ext_func, n_ext = mdef

        if states[name]['params'] is None:
            continue

        params = states[name]['params']
        n_theta = states[name]['n_theta']
        theta = params[:n_theta]
        omega_g = params[n_theta]
        alpha_p = params[n_theta + 1]
        gamma_p = params[n_theta + 2]
        beta_p = params[n_theta + 3]

        # Build external regressor vector (using t-1 values = no lookahead)
        ext_raw_prev = ext_func(
            np.array([vix_prev]),
            np.array([ts_prev]),
            np.array([ur_prev])
        )
        if ext_raw_prev.ndim > 1:
            x_row = ext_raw_prev[0, :]
        else:
            x_row = ext_raw_prev

        tau_cur = compute_tau_generic(theta, x_row, tau_type)

        # Update g using previous return and current tau
        g_prev = states[name]['g']
        u_prev = r_prev / np.sqrt(tau_cur)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        sigma2_forecast = tau_cur * g_new
        forecasts[name][t_idx] = sigma2_forecast
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_cur

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

target = r2[oos_indices]

# Remove any NaN rows
valid = np.ones(n_oos_actual, dtype=bool)
for name in model_names:
    valid &= ~np.isnan(forecasts[name])
valid &= ~np.isnan(target)
valid &= (target > 0)

n_valid = valid.sum()
print(f"  Valid OOS observations: {n_valid}/{n_oos_actual}")

target_v = target[valid]

# QLIKE scores
qlike_scores = {}
for name in model_names:
    fc = forecasts[name][valid]
    fc = np.maximum(fc, 1e-16)
    ql = np.mean(target_v / fc - np.log(target_v / fc) - 1)
    qlike_scores[name] = float(ql)

print("\n  QLIKE scores (lower = better):")
sorted_models = sorted(qlike_scores.items(), key=lambda x: x[1])
for name, ql in sorted_models:
    pct_vs_gjr = (ql / qlike_scores['GJR_N'] - 1) * 100
    print(f"    {name:25s}: {ql:.6f} ({pct_vs_gjr:+.2f}% vs GJR)")

# Spearman correlations
print("\n  Spearman rank correlations with r²:")
spearman_scores = {}
for name in model_names:
    fc = forecasts[name][valid]
    rho, p = stats.spearmanr(fc, target_v)
    spearman_scores[name] = {'rho': float(rho), 'p': float(p)}
    print(f"    {name:25s}: ρ={rho:.4f} (p={p:.4e})")

# Pairwise DM tests
print("\n  Pairwise DM tests (QLIKE loss):")
dm_results = {}
for i, name1 in enumerate(model_names):
    for j, name2 in enumerate(model_names):
        if i >= j:
            continue
        fc1 = forecasts[name1][valid]
        fc2 = forecasts[name2][valid]

        # QLIKE loss for each model
        fc1 = np.maximum(fc1, 1e-16)
        fc2 = np.maximum(fc2, 1e-16)
        loss1 = target_v / fc1 - np.log(target_v / fc1) - 1
        loss2 = target_v / fc2 - np.log(target_v / fc2) - 1

        d = loss1 - loss2  # positive = model2 better
        n_d = len(d)
        d_mean = np.mean(d)

        # HAC variance (Newey-West with ~sqrt(n) lags)
        max_lag = int(np.ceil(np.sqrt(n_d)))
        gamma0 = np.mean((d - d_mean)**2)
        hac_var = gamma0
        for lag in range(1, max_lag + 1):
            w = 1 - lag / (max_lag + 1)  # Bartlett kernel
            gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
            hac_var += 2 * w * gamma_l

        se = np.sqrt(max(hac_var / n_d, 1e-20))
        t_stat = d_mean / se if se > 0 else 0.0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n_d - 1))

        key = f"{name1}_vs_{name2}"
        dm_results[key] = {
            't_stat': float(t_stat),
            'p_value': float(p_val),
            'mean_diff': float(d_mean),
            'interpretation': f"{'model1 better' if t_stat < 0 else 'model2 better'}"
        }

        # Highlight significant results
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
        better = name1 if t_stat < 0 else name2
        print(f"    {name1:20s} vs {name2:20s}: t={t_stat:+.3f}{sig:4s} → {better} better")

# ============================================================
# SECTION 6: KEY COMPARISONS
# ============================================================
print("\n[6] Key comparisons...")

# A4f_VIX vs each macro model
print("\n  A4f_VIX vs Macro models:")
for macro_name in ['Macro_TermSpread', 'Macro_Unemployment', 'Macro_Combined']:
    key1 = f"A4f_VIX_vs_{macro_name}"
    key2 = f"{macro_name}_vs_A4f_VIX"
    if key1 in dm_results:
        r = dm_results[key1]
        print(f"    vs {macro_name:20s}: DM t={r['t_stat']:+.3f}, QLIKE: VIX={qlike_scores['A4f_VIX']:.6f}, Macro={qlike_scores[macro_name]:.6f}")
    elif key2 in dm_results:
        r = dm_results[key2]
        print(f"    vs {macro_name:20s}: DM t={-r['t_stat']:+.3f}, QLIKE: VIX={qlike_scores['A4f_VIX']:.6f}, Macro={qlike_scores[macro_name]:.6f}")

# VIX_Macro vs A4f_VIX
print("\n  Does adding macro to VIX help?")
key1 = f"A4f_VIX_vs_VIX_Macro"
key2 = f"VIX_Macro_vs_A4f_VIX"
if key1 in dm_results:
    r = dm_results[key1]
    print(f"    A4f_VIX vs VIX_Macro: DM t={r['t_stat']:+.3f}")
elif key2 in dm_results:
    r = dm_results[key2]
    print(f"    VIX_Macro vs A4f_VIX: DM t={r['t_stat']:+.3f}")

# ============================================================
# SECTION 7: SAVE RESULTS
# ============================================================
print("\n[7] Saving results...")

elapsed = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Conrad-Loch Macro GARCH-X vs VIX GARCH-X',
    'date': datetime.now(timezone.utc).isoformat(),
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'references': [
        'Conrad & Loch (2015). JAE 30(7):1090-1114.',
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
        'Patton (2011). J Econometrics 160:246-256.',
        'Harvey et al. (2016). t > 3.0 threshold.',
        'K988: VIX GARCH-X A4f champion (DM t=+4.48 vs GJR)',
    ],
    'config': {
        'asset': 'SPY',
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'n_total': n_total,
        'n_oos': n_oos_actual,
        'n_valid': int(n_valid),
        'macro_lag': '30 calendar days (use previous month value)',
        'macro_sources': {
            'GS10': 'FRED 10-Year Treasury Constant Maturity',
            'TB3MS': 'FRED 3-Month Treasury Bill Secondary Market',
            'UNRATE': 'FRED Civilian Unemployment Rate',
        }
    },
    'models': {
        'GJR_N': 'GJR-GARCH(1,1) Normal — benchmark',
        'A4f_VIX': 'τ = θ₀ + θ₁·VIX²_{t-1}, free ω (K988 champion)',
        'Macro_TermSpread': 'τ = exp(θ₀ + θ₁·TermSpread_{t-1})',
        'Macro_Unemployment': 'τ = exp(θ₀ + θ₁·UnempRate_{t-1})',
        'Macro_Combined': 'τ = exp(θ₀ + θ₁·TermSpread + θ₂·UnempRate)',
        'VIX_Macro': 'τ = θ₀ + θ₁·VIX² + θ₂·TermSpread',
    },
    'qlike_scores': qlike_scores,
    'qlike_ranking': [{'rank': i+1, 'model': name, 'qlike': ql}
                      for i, (name, ql) in enumerate(sorted_models)],
    'spearman_scores': spearman_scores,
    'dm_tests': dm_results,
    'param_history_last': {
        name: (param_history[name][-1] if param_history[name] else None)
        for name in model_names
    },
    'key_findings': {},
    'elapsed_seconds': round(elapsed, 1),
}

# Determine key findings
vix_ql = qlike_scores.get('A4f_VIX', None)
gjr_ql = qlike_scores.get('GJR_N', None)

if vix_ql and gjr_ql:
    results['key_findings']['vix_vs_gjr_pct'] = round((vix_ql / gjr_ql - 1) * 100, 2)

for macro_name in ['Macro_TermSpread', 'Macro_Unemployment', 'Macro_Combined']:
    macro_ql = qlike_scores.get(macro_name, None)
    if macro_ql and gjr_ql:
        results['key_findings'][f'{macro_name}_vs_gjr_pct'] = round((macro_ql / gjr_ql - 1) * 100, 2)
    if macro_ql and vix_ql:
        results['key_findings'][f'vix_vs_{macro_name}_pct'] = round((vix_ql / macro_ql - 1) * 100, 2)

# Find DM test: VIX vs best macro
best_macro = min(['Macro_TermSpread', 'Macro_Unemployment', 'Macro_Combined'],
                 key=lambda x: qlike_scores.get(x, 999))
results['key_findings']['best_macro_model'] = best_macro

# Save
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to: {RESULTS_PATH}")
print(f"  Total elapsed: {elapsed:.1f}s")

# ============================================================
# SECTION 8: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"\nQLIKE ranking (lower = better):")
for i, (name, ql) in enumerate(sorted_models):
    pct = (ql / gjr_ql - 1) * 100 if gjr_ql else 0
    print(f"  {i+1}. {name:25s}: {ql:.6f} ({pct:+.2f}% vs GJR)")

print(f"\nKey question: Does VIX beat macro variables?")
for macro_name in ['Macro_TermSpread', 'Macro_Unemployment', 'Macro_Combined']:
    key1 = f"A4f_VIX_vs_{macro_name}"
    key2 = f"{macro_name}_vs_A4f_VIX"
    if key1 in dm_results:
        t = dm_results[key1]['t_stat']
    elif key2 in dm_results:
        t = -dm_results[key2]['t_stat']
    else:
        t = float('nan')
    sig = "PASS Harvey" if abs(t) > 3.0 else "NS"
    print(f"  VIX vs {macro_name:20s}: DM t={t:+.3f} ({sig})")

print(f"\nKey question: Does adding macro to VIX help?")
key1 = f"A4f_VIX_vs_VIX_Macro"
key2 = f"VIX_Macro_vs_A4f_VIX"
if key1 in dm_results:
    t = dm_results[key1]['t_stat']
elif key2 in dm_results:
    t = -dm_results[key2]['t_stat']
else:
    t = float('nan')
print(f"  VIX-only vs VIX+Macro: DM t={t:+.3f}")

print(f"\nElapsed: {elapsed:.1f}s")
print("Done.")
