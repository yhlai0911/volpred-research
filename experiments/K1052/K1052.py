#!/usr/bin/env python3
"""
K1052: Asymmetric A4f — Does VIX Direction Matter?
===================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  A4f (Paper 9 champion, K988) treats VIX symmetrically:
    τ_t = θ₀ + θ₁ × VIX²_{t-1}
  But VIX has known asymmetry: spikes (fear) are sharper than declines (calm).
  If ΔVIX > 0 and ΔVIX < 0 have different impacts on next-day volatility,
  an asymmetric extension could improve forecasts.

  Related: GJR γ already captures return asymmetry. Does VIX asymmetry add
  information beyond return asymmetry?

Models tested:
  M1: A4f baseline        — τ_t = θ₀ + θ₁ × VIX²_{t-1}
  M2: A4f-Asym (ΔVIX)     — τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₂ × ΔVIX⁺_{t-1}
  M3: A4f-Asym (high-VIX) — τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₃ × VIX²_{t-1} × 1_{VIX > median}
  M4: GJR-GARCH(1,1)      — standard benchmark

  All with GJR short-run g_t, free ω_g, joint MLE.

Prior knowledge:
  - K988: A4f DM t=4.03 vs GJR (champion)
  - K1015: Dual-factor VIX9D+VIX3M NULL (θ₂=0, collinear)
  - K1048: Threshold GARCH (VIX regime switching) IS sig but OOS NULL

References:
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). Tests for forecast encompassing. JBES 34(4):574-587. [t>3.0]
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Conrad & Loch (2015). JBES 33(3):338-358. [External regressors in τ]

Data: SPY 2005-2026, VIX from yfinance. OOS: 2019-01-01 to latest.
Evaluation: QLIKE on r² (Patton 2011), DM test with Harvey |t| > 3.0.
Seed: 42

Author: VolPred Research System
Date: 2026-04-11
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

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1052"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'K1052_results.json')
PLOT_PATH = os.path.join(SCRIPT_DIR, 'K1052_asymmetric.png')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-11'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit

print("=" * 70)
print(f"{EXPERIMENT_ID}: Asymmetric A4f — Does VIX Direction Matter?")
print("  Testing VIX asymmetry extensions to A4f model")
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

# Compute VIX change and rolling median
df['DVIX'] = df['VIX'].diff()
df['DVIX_pos'] = np.maximum(df['DVIX'], 0.0)  # positive changes only
df['VIX_median_252'] = df['VIX'].rolling(252, min_periods=63).median()
df = df.dropna()

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
dvix_pos = df['DVIX_pos'].values  # ΔVIX⁺ (only positive changes)
vix_median = df['VIX_median_252'].values
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
oos_r2 = r2[oos_mask]
print(f"  OOS mean return: {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std: {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
print(f"  VIX autocorr(1): {np.corrcoef(vix[1:], vix[:-1])[0,1]:.4f}")

# VIX asymmetry diagnostics
oos_dvix = df['DVIX'].values[oos_mask]
print(f"  ΔVIX stats: mean={np.mean(oos_dvix):.3f}, std={np.std(oos_dvix):.3f}")
print(f"  ΔVIX>0 count: {np.sum(oos_dvix > 0)} ({np.mean(oos_dvix > 0)*100:.1f}%)")
print(f"  ΔVIX>0 mean: {np.mean(oos_dvix[oos_dvix > 0]):.3f}")
print(f"  ΔVIX<0 count: {np.sum(oos_dvix < 0)} ({np.mean(oos_dvix < 0)*100:.1f}%)")
print(f"  ΔVIX<0 mean: {np.mean(oos_dvix[oos_dvix < 0]):.3f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


def gjr_loglik_py(params, returns):
    """Standard GJR-GARCH(1,1) log-likelihood (pure Python)."""
    omega, alpha, gamma_p, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    for t in range(1, n):
        asym = gamma_p * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    ll = 0.0
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
            res = optimize.minimize(gjr_loglik_py, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma_p, beta = params
    asym = gamma_p * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# ====================================================================
# A4f Model Family: Multiplicative τ × g with free ω_g
# ====================================================================
def fit_a4f(returns, vix_vals, dvix_pos_vals=None, vix_median_vals=None,
            model_type='baseline'):
    """
    Joint MLE for A4f family.

    model_type:
      'baseline' (M1): τ_t = θ₀ + θ₁ × VIX²_{t-1}
      'asym_dvix' (M2): τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₂ × ΔVIX⁺_{t-1}
      'asym_regime' (M3): τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₃ × VIX²_{t-1} × 1_{VIX > median}

    Parameters (baseline):  θ₀, θ₁, ω_g, α, γ, β  (6 params)
    Parameters (asym_dvix): θ₀, θ₁, θ₂, ω_g, α, γ, β  (7 params)
    Parameters (asym_regime): θ₀, θ₁, θ₃, ω_g, α, γ, β  (7 params)
    """
    n = len(returns)

    # Lagged VIX (no lookahead): VIX_{t-1} for forecasting τ_t
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix2_lag = vix_lag ** 2

    # For M2: lagged ΔVIX⁺
    if dvix_pos_vals is not None:
        dvix_pos_lag = np.empty(n)
        dvix_pos_lag[0] = 0.0
        dvix_pos_lag[1:] = dvix_pos_vals[:-1]
    else:
        dvix_pos_lag = None

    # For M3: lagged VIX median indicator
    if vix_median_vals is not None:
        vix_above_med_lag = np.empty(n)
        vix_above_med_lag[0] = 0.0
        vix_above_med_lag[1:] = (vix_vals[:-1] > vix_median_vals[:-1]).astype(float)
    else:
        vix_above_med_lag = None

    var0 = np.var(returns)
    vix2_mean = np.mean(vix2_lag) + 1e-8

    def neg_loglik(params):
        if model_type == 'baseline':
            theta0, theta1, omega_g, alpha, gamma_p, beta = params
            theta_extra = 0.0
        elif model_type == 'asym_dvix':
            theta0, theta1, theta_extra, omega_g, alpha, gamma_p, beta = params
        elif model_type == 'asym_regime':
            theta0, theta1, theta_extra, omega_g, alpha, gamma_p, beta = params
        else:
            return 1e10

        # Compute τ
        tau = theta0 + theta1 * vix2_lag
        if model_type == 'asym_dvix' and dvix_pos_lag is not None:
            tau = tau + theta_extra * dvix_pos_lag
        elif model_type == 'asym_regime' and vix_above_med_lag is not None:
            tau = tau + theta_extra * vix2_lag * vix_above_med_lag
        tau = np.maximum(tau, 1e-16)

        # Check g-equation constraints
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)

        # Recursion
        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])  # tau_t denominator (Engle et al. 2013)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        # Log-likelihood
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

        return -ll

    best_ll = np.inf
    best_params = None

    # Build starting values and bounds based on model type
    if model_type == 'baseline':
        starts = [
            [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        ]
        bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
                  (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    elif model_type == 'asym_dvix':
        starts = [
            [var0 * 0.1, var0 / vix2_mean, 1e-5, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.5, 5e-5, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 1.5, 1e-4, 0.02, 0.08, 0.10, 0.80],
            [var0 * 0.1, var0 / vix2_mean, -1e-5, 0.05, 0.05, 0.05, 0.90],
        ]
        bounds = [(-1e-2, 1e-2), (1e-8, 1e-3), (-1e-2, 1e-2),
                  (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    elif model_type == 'asym_regime':
        starts = [
            [var0 * 0.1, var0 / vix2_mean, var0 / vix2_mean * 0.1, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.5, var0 / vix2_mean * 0.2, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 1.5, var0 / vix2_mean * -0.1, 0.02, 0.08, 0.10, 0.80],
        ]
        bounds = [(-1e-2, 1e-2), (1e-8, 1e-3), (-1e-2, 1e-2),
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

    return best_params, best_ll


def compute_tau_a4f(theta0, theta1, vix2_lag, model_type='baseline',
                    theta_extra=0.0, dvix_pos_lag=None, vix_above_med_lag=None):
    """Compute tau for a single observation or array."""
    tau = theta0 + theta1 * vix2_lag
    if model_type == 'asym_dvix' and dvix_pos_lag is not None:
        tau = tau + theta_extra * dvix_pos_lag
    elif model_type == 'asym_regime' and vix_above_med_lag is not None:
        tau = tau + theta_extra * vix2_lag * vix_above_med_lag
    return np.maximum(tau, 1e-16)


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")

model_names = ['M1_A4f', 'M2_A4f_DeltaVIX', 'M3_A4f_HighVIX', 'M4_GJR']
model_types = {
    'M1_A4f': 'baseline',
    'M2_A4f_DeltaVIX': 'asym_dvix',
    'M3_A4f_HighVIX': 'asym_regime',
}

forecasts = {name: np.full(n_oos_actual, np.nan) for name in model_names}

# Store parameter estimates for reporting
all_param_estimates = {name: [] for name in model_names}

# State variables for recursive forecasting
states = {}
for name in model_names:
    states[name] = {'params': None, 'g': None, 'h': None}

refit_count = 0

print(f"  Refit every {REFIT_EVERY} days")

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
        train_dvix_pos = dvix_pos[train_start:abs_idx]
        train_vix_median = vix_median[train_start:abs_idx]
        n_train = len(train_ret)

        # M4: GJR benchmark
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            states['M4_GJR']['params'] = gjr_params
            h = np.var(train_ret)
            for i in range(1, n_train):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            states['M4_GJR']['h'] = h
            all_param_estimates['M4_GJR'].append({
                'refit': refit_count,
                'omega': float(gjr_params[0]),
                'alpha': float(gjr_params[1]),
                'gamma': float(gjr_params[2]),
                'beta': float(gjr_params[3]),
            })

        # A4f family
        for name, mtype in model_types.items():
            params, nll = fit_a4f(
                train_ret, train_vix,
                dvix_pos_vals=train_dvix_pos if mtype == 'asym_dvix' else None,
                vix_median_vals=train_vix_median if mtype == 'asym_regime' else None,
                model_type=mtype
            )

            if params is not None:
                states[name]['params'] = params
                states[name]['model_type'] = mtype

                # Parse parameters
                if mtype == 'baseline':
                    theta0, theta1 = params[0], params[1]
                    theta_extra = 0.0
                    omega_g, alpha_p, gamma_p, beta_p = params[2], params[3], params[4], params[5]
                    pdict = {
                        'refit': refit_count, 'theta0': float(theta0),
                        'theta1': float(theta1), 'omega_g': float(omega_g),
                        'alpha': float(alpha_p), 'gamma': float(gamma_p),
                        'beta': float(beta_p), 'nll': float(nll),
                    }
                else:
                    theta0, theta1, theta_extra = params[0], params[1], params[2]
                    omega_g, alpha_p, gamma_p, beta_p = params[3], params[4], params[5], params[6]
                    extra_name = 'theta2' if mtype == 'asym_dvix' else 'theta3'
                    pdict = {
                        'refit': refit_count, 'theta0': float(theta0),
                        'theta1': float(theta1), extra_name: float(theta_extra),
                        'omega_g': float(omega_g), 'alpha': float(alpha_p),
                        'gamma': float(gamma_p), 'beta': float(beta_p),
                        'nll': float(nll),
                    }
                all_param_estimates[name].append(pdict)

                # Initialize g from training data
                vix_lag_tr = np.empty(n_train)
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                vix2_lag_tr = vix_lag_tr ** 2

                dvix_pos_lag_tr = None
                if mtype == 'asym_dvix':
                    dvix_pos_lag_tr = np.empty(n_train)
                    dvix_pos_lag_tr[0] = 0.0
                    dvix_pos_lag_tr[1:] = train_dvix_pos[:-1]

                vix_above_med_lag_tr = None
                if mtype == 'asym_regime':
                    vix_above_med_lag_tr = np.empty(n_train)
                    vix_above_med_lag_tr[0] = 0.0
                    vix_above_med_lag_tr[1:] = (train_vix[:-1] > train_vix_median[:-1]).astype(float)

                tau_train = compute_tau_a4f(theta0, theta1, vix2_lag_tr,
                                            model_type=mtype, theta_extra=theta_extra,
                                            dvix_pos_lag=dvix_pos_lag_tr,
                                            vix_above_med_lag=vix_above_med_lag_tr)

                persist = alpha_p + gamma_p / 2.0 + beta_p
                eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg
                for i in range(1, n_train):
                    u_prev = train_ret[i-1] / np.sqrt(max(float(tau_train[i]), 1e-16))
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)

                states[name]['g'] = g

    # --- Generate forecasts for day abs_idx ---

    # M4: GJR
    p = states['M4_GJR']['params']
    if p is not None:
        h_prev = states['M4_GJR']['h']
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        forecasts['M4_GJR'][t_idx] = h_new
        states['M4_GJR']['h'] = h_new

    # A4f family: one-step-ahead
    for name, mtype in model_types.items():
        p = states[name].get('params')
        if p is None:
            continue

        if mtype == 'baseline':
            theta0, theta1 = p[0], p[1]
            theta_extra = 0.0
            omega_g, alpha_p, gamma_p, beta_p = p[2], p[3], p[4], p[5]
        else:
            theta0, theta1, theta_extra = p[0], p[1], p[2]
            omega_g, alpha_p, gamma_p, beta_p = p[3], p[4], p[5], p[6]

        # Compute τ_t using lagged VIX (VIX_{t-1})
        v_lag = vix[abs_idx - 1]
        vix2_lag_val = v_lag ** 2

        dvix_pos_lag_val = None
        if mtype == 'asym_dvix':
            dvix_pos_lag_val = dvix_pos[abs_idx - 1]

        vix_above_med_val = None
        if mtype == 'asym_regime':
            vix_above_med_val = 1.0 if vix[abs_idx - 1] > vix_median[abs_idx - 1] else 0.0

        tau_t = compute_tau_a4f(theta0, theta1, vix2_lag_val,
                                model_type=mtype, theta_extra=theta_extra,
                                dvix_pos_lag=dvix_pos_lag_val,
                                vix_above_med_lag=vix_above_med_val)
        if isinstance(tau_t, np.ndarray):
            tau_t = float(tau_t)

        # Update g: g_t = ω + α u²_{t-1} + γ u²_{t-1} 1_{u<0} + β g_{t-1}
        r_prev = ret[abs_idx - 1]
        g_prev = states[name]['g']
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        sigma2_forecast = tau_t * g_new
        forecasts[name][t_idx] = sigma2_forecast
        states[name]['g'] = g_new

elapsed = time.time() - START_TIME
print(f"  OOS forecasting complete: {refit_count} refits, {elapsed:.0f}s elapsed")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_target = r2[oos_mask]

# Remove NaN entries
valid = np.ones(n_oos_actual, dtype=bool)
for name in model_names:
    valid &= ~np.isnan(forecasts[name])
print(f"  Valid OOS observations: {valid.sum()}/{n_oos_actual}")

target_valid = oos_target[valid]

results = {}
for name in model_names:
    fc = forecasts[name][valid]
    fc = np.maximum(fc, 1e-16)  # ensure positive
    q = qlike(target_valid, fc)
    rho, _ = stats.spearmanr(target_valid, fc)
    results[name] = {'qlike': q, 'spearman': rho, 'forecast': fc}
    print(f"  {name}: QLIKE={q:.6f}, Spearman={rho:.4f}")

# DM tests: M2 vs M1, M3 vs M1, M1 vs M4
print("\n  DM Tests (Harvey |t| > 3.0 required):")
dm_pairs = [
    ('M2_A4f_DeltaVIX', 'M1_A4f', 'M2 vs M1 (ΔVIX asymmetry)'),
    ('M3_A4f_HighVIX', 'M1_A4f', 'M3 vs M1 (VIX regime)'),
    ('M1_A4f', 'M4_GJR', 'M1(A4f) vs M4(GJR)'),
    ('M2_A4f_DeltaVIX', 'M4_GJR', 'M2 vs M4(GJR)'),
    ('M3_A4f_HighVIX', 'M4_GJR', 'M3 vs M4(GJR)'),
]

from volpred.stats.model_evaluation import qlike_pointwise

dm_results = {}
for name1, name2, desc in dm_pairs:
    fc1 = results[name1]['forecast']
    fc2 = results[name2]['forecast']
    loss1 = qlike_pointwise(target_valid, fc1)
    loss2 = qlike_pointwise(target_valid, fc2)
    t_stat, p_val = dm_test(loss1, loss2)
    sig = '***' if abs(t_stat) > 3.0 else ('**' if abs(t_stat) > 2.0 else ('*' if abs(t_stat) > 1.65 else 'NS'))
    print(f"    {desc}: DM t={t_stat:.3f}, p={p_val:.4f} {sig}")
    # Negative t-stat means model 1 has LOWER loss (better)
    dm_results[f'{name1}_vs_{name2}'] = {
        'dm_t': round(float(t_stat), 4),
        'p_value': round(float(p_val), 6),
        'significant_harvey': abs(t_stat) > 3.0,
        'description': desc,
        'interpretation': f'{name1} better' if t_stat < 0 else f'{name2} better'
    }

# ============================================================
# SECTION 6: PARAMETER ANALYSIS
# ============================================================
print("\n[6] Parameter analysis...")

# Analyze the asymmetry parameters across refits
for name in ['M2_A4f_DeltaVIX', 'M3_A4f_HighVIX']:
    ests = all_param_estimates[name]
    if not ests:
        continue

    if name == 'M2_A4f_DeltaVIX':
        extra_key = 'theta2'
        print(f"\n  {name} — θ₂ (ΔVIX⁺ coefficient):")
    else:
        extra_key = 'theta3'
        print(f"\n  {name} — θ₃ (VIX² × 1_{{VIX>median}} coefficient):")

    theta_extras = [e[extra_key] for e in ests if extra_key in e]
    if theta_extras:
        arr = np.array(theta_extras)
        print(f"    n_refits: {len(arr)}")
        print(f"    mean: {np.mean(arr):.8f}")
        print(f"    std: {np.std(arr):.8f}")
        print(f"    min: {np.min(arr):.8f}")
        print(f"    max: {np.max(arr):.8f}")
        print(f"    % positive: {np.mean(arr > 0)*100:.1f}%")

        # Simple t-test: is mean significantly different from 0?
        if len(arr) > 2 and np.std(arr) > 0:
            t_param, p_param = stats.ttest_1samp(arr, 0)
            print(f"    t-test vs 0: t={t_param:.3f}, p={p_param:.4f}")

# Report baseline A4f parameters for reference
print("\n  M1 (A4f baseline) — parameter summary:")
m1_ests = all_param_estimates['M1_A4f']
if m1_ests:
    for key in ['theta0', 'theta1', 'omega_g', 'alpha', 'gamma', 'beta']:
        vals = [e[key] for e in m1_ests if key in e]
        if vals:
            arr = np.array(vals)
            print(f"    {key}: mean={np.mean(arr):.6f}, std={np.std(arr):.6f}")

# ============================================================
# SECTION 7: QLIKE IMPROVEMENT ANALYSIS
# ============================================================
print("\n[7] QLIKE improvement analysis...")

qlike_baseline = results['M1_A4f']['qlike']
for name in model_names:
    q = results[name]['qlike']
    change_pct = (q - qlike_baseline) / qlike_baseline * 100 if qlike_baseline > 0 else 0
    print(f"  {name}: QLIKE={q:.6f}, vs M1: {change_pct:+.2f}%")

# ============================================================
# SECTION 8: PLOT
# ============================================================
print("\n[8] Generating plot...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K1052: Asymmetric A4f — Does VIX Direction Matter?', fontsize=14, fontweight='bold')

oos_dates = df.index[oos_mask][valid]

# Panel 1: QLIKE comparison bar chart
ax = axes[0, 0]
qlike_vals = [results[name]['qlike'] for name in model_names]
colors = ['#2196F3', '#FF9800', '#4CAF50', '#9E9E9E']
bars = ax.bar(range(len(model_names)), qlike_vals, color=colors, alpha=0.8)
ax.set_xticks(range(len(model_names)))
ax.set_xticklabels(['M1\n(A4f)', 'M2\n(+ΔVIX⁺)', 'M3\n(+HighVIX)', 'M4\n(GJR)'],
                    fontsize=9)
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('OOS QLIKE Comparison')
for i, (bar, val) in enumerate(zip(bars, qlike_vals)):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height(),
            f'{val:.4f}', ha='center', va='bottom', fontsize=8)

# Panel 2: Forecasts over time (rolling 63d mean)
ax = axes[0, 1]
for name, color in zip(model_names, colors):
    fc = forecasts[name][valid]
    fc_smooth = pd.Series(fc).rolling(63, min_periods=10).mean().values
    ax.plot(oos_dates, fc_smooth, label=name, color=color, linewidth=0.8, alpha=0.8)
target_smooth = pd.Series(target_valid).rolling(63, min_periods=10).mean().values
ax.plot(oos_dates, target_smooth, label='r² (63d MA)', color='black',
        linewidth=1.0, linestyle='--', alpha=0.5)
ax.set_ylabel('Variance forecast (63d MA)')
ax.set_title('Rolling Forecasts')
ax.legend(fontsize=7, ncol=2)
ax.tick_params(axis='x', rotation=30)

# Panel 3: DM test results
ax = axes[1, 0]
dm_labels = []
dm_t_vals = []
dm_colors_list = []
for key, val in dm_results.items():
    dm_labels.append(val['description'].replace(' ', '\n', 1))
    dm_t_vals.append(val['dm_t'])
    if val['significant_harvey']:
        dm_colors_list.append('#4CAF50' if val['dm_t'] < 0 else '#F44336')
    else:
        dm_colors_list.append('#9E9E9E')

bars = ax.barh(range(len(dm_labels)), dm_t_vals, color=dm_colors_list, alpha=0.8)
ax.set_yticks(range(len(dm_labels)))
ax.set_yticklabels(dm_labels, fontsize=7)
ax.set_xlabel('DM t-statistic (negative = first model better)')
ax.set_title('DM Test Results')
ax.axvline(x=-3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3.0')
ax.axvline(x=3.0, color='red', linestyle='--', alpha=0.5)
ax.axvline(x=0, color='gray', linestyle='-', alpha=0.3)

# Panel 4: θ₂ (M2) parameter evolution across refits
ax = axes[1, 1]
m2_ests = all_param_estimates['M2_A4f_DeltaVIX']
if m2_ests:
    theta2_vals = [e.get('theta2', 0) for e in m2_ests]
    ax.plot(range(1, len(theta2_vals)+1), theta2_vals, 'o-', color='#FF9800',
            markersize=3, linewidth=1)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel('Refit #')
    ax.set_ylabel('θ₂ (ΔVIX⁺ coefficient)')
    ax.set_title('M2: θ₂ Evolution Across Refits')

    # Also plot θ₃ from M3
    m3_ests = all_param_estimates['M3_A4f_HighVIX']
    if m3_ests:
        theta3_vals = [e.get('theta3', 0) for e in m3_ests]
        ax2 = ax.twinx()
        ax2.plot(range(1, len(theta3_vals)+1), theta3_vals, 's-', color='#4CAF50',
                 markersize=3, linewidth=1, alpha=0.7)
        ax2.set_ylabel('θ₃ (high-VIX regime)', color='#4CAF50')

plt.tight_layout()
plt.savefig(PLOT_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Plot saved: {PLOT_PATH}")

# ============================================================
# SECTION 9: SAVE RESULTS
# ============================================================
print("\n[9] Saving results...")

# Determine best model
best_model = min(results.keys(), key=lambda k: results[k]['qlike'])

# Summarize conclusions
m2_vs_m1 = dm_results.get('M2_A4f_DeltaVIX_vs_M1_A4f', {})
m3_vs_m1 = dm_results.get('M3_A4f_HighVIX_vs_M1_A4f', {})
m1_vs_m4 = dm_results.get('M1_A4f_vs_M4_GJR', {})

m2_improves = m2_vs_m1.get('dm_t', 0) < -3.0
m3_improves = m3_vs_m1.get('dm_t', 0) < -3.0
a4f_beats_gjr = m1_vs_m4.get('dm_t', 0) < -3.0

if m2_improves:
    conclusion = "VIX direction MATTERS: ΔVIX⁺ significantly improves A4f forecasts"
elif m3_improves:
    conclusion = "VIX regime MATTERS: high-VIX interaction significantly improves A4f forecasts"
else:
    conclusion = "NULL: Neither VIX direction nor VIX regime significantly improves over A4f. Symmetric VIX² in A4f is parsimonious and sufficient."

output = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Asymmetric A4f — Does VIX Direction Matter?',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{OOS_START} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(n_total),
    'n_oos': int(valid.sum()),
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'seed': 42,
    'models': {
        'M1_A4f': 'τ_t = θ₀ + θ₁ × VIX²_{t-1} (baseline)',
        'M2_A4f_DeltaVIX': 'τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₂ × ΔVIX⁺_{t-1}',
        'M3_A4f_HighVIX': 'τ_t = θ₀ + θ₁ × VIX²_{t-1} + θ₃ × VIX²_{t-1} × 1_{VIX>median}',
        'M4_GJR': 'Standard GJR-GARCH(1,1)',
    },
    'evaluation': {
        name: {
            'qlike': round(results[name]['qlike'], 6),
            'spearman': round(results[name]['spearman'], 4),
        }
        for name in model_names
    },
    'dm_tests': dm_results,
    'parameter_estimates': {
        name: {
            'n_refits': len(ests),
            'last_refit': ests[-1] if ests else None,
        }
        for name, ests in all_param_estimates.items()
    },
    'best_model': best_model,
    'conclusion': conclusion,
    'a4f_beats_gjr': a4f_beats_gjr,
    'm2_improves_over_m1': m2_improves,
    'm3_improves_over_m1': m3_improves,
    'implications': {
        'for_paper9': 'Symmetric A4f is sufficient; asymmetric extensions do not improve forecasts'
            if not (m2_improves or m3_improves)
            else 'Asymmetric extension recommended for Paper 9 revision',
        'for_gjr_gamma': 'GJR γ already captures return-based asymmetry; VIX-based asymmetry is redundant'
            if not (m2_improves or m3_improves)
            else 'VIX asymmetry adds information beyond return asymmetry',
        'parsimony': f'A4f with {6} params is optimal (vs {7} for asymmetric extensions)'
            if not (m2_improves or m3_improves)
            else f'Additional parameter justified by DM test',
    },
    'references': [
        'Patton (2011). J Econometrics 160:246-256.',
        'Harvey et al. (2016). JBES 34(4):574-587.',
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
        'Conrad & Loch (2015). JBES 33(3):338-358.',
    ],
    'runtime_seconds': round(time.time() - START_TIME, 1),
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"  Results saved: {RESULTS_PATH}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"\n  Best model: {best_model} (QLIKE={results[best_model]['qlike']:.6f})")
print(f"\n  M2 (ΔVIX⁺) improves over M1: {'YES ***' if m2_improves else 'NO'}")
print(f"  M3 (high-VIX) improves over M1: {'YES ***' if m3_improves else 'NO'}")
print(f"  A4f beats GJR: {'YES ***' if a4f_beats_gjr else 'NO'}")
print(f"\n  Conclusion: {conclusion}")
print(f"\n  Runtime: {time.time() - START_TIME:.1f}s")
print("=" * 70)
