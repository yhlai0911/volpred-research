#!/usr/bin/env python3
"""
K988: Multiplicative GARCH-X vs GARCH-MIDAS(VIX) Specification Comparison
=========================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K889 introduced MF-GJR(VIX) with σ²_t = τ_t × g_t, claiming GARCH-MIDAS.
  Professor Lai identified two issues:
  1. The model is NOT GARCH-MIDAS — τ is daily with single-lag VIX, no MIDAS weights
  2. The g_t denominator is inconsistent between estimation (τ_t) and OOS (τ_{t-1})

  This experiment systematically tests:
  Part A: Multiplicative GARCH-X variants (daily τ, no MIDAS)
    A1: K889-original (inconsistent τ_{t-1} in OOS)
    A2: Consistent-τ_t (denominator = τ_t everywhere, per Engle et al. 2013 logic)
    A3: Consistent-τ_{t-1} (denominator = τ_{t-1} everywhere, DGP interpretation)
    A4: VIX-squared (τ = θ₀ + θ₁ VIX²_{t-1}, since VIX~vol so VIX²~variance)
    A5: VIX-level (τ = exp(θ₀ + θ₁ VIX_{t-1}), no log transform)

  Part B: Proper GARCH-MIDAS(VIX) with Beta-weighted MIDAS filter
    B1: Rolling window K=22 (monthly)
    B2: Rolling window K=65 (quarterly)
    B3: Rolling window K=125 (semi-annual)

  Benchmark:
    B0: GJR-GARCH(1,1)

  All models use GJR short-run component (leverage effect).

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797. [Original GARCH-MIDAS]
  - Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility.
    JBES 33(3):338-358. [External regressors in τ]
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.

Data: SPY 2005-2026, VIX from yfinance. OOS: 2019-01-01 to latest.
Evaluation: QLIKE on r² (Patton 2011), DM test, Spearman rank correlation.

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
from scipy.special import beta as beta_func
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K988"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k988_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit

print("=" * 70)
print(f"{EXPERIMENT_ID}: Multiplicative GARCH-X vs GARCH-MIDAS(VIX)")
print("  Systematic specification comparison")
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

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
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
print(f"  VIX autocorr(1): {np.corrcoef(vix[1:], vix[:-1])[0,1]:.4f}")

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


# --- Multiplicative GARCH-X: Two-step estimation ---
def fit_mfgjr_x(returns, log_vix_vals, vix_vals, tau_func='log_exp', denom_mode='tau_t',
                 free_omega=False):
    """
    Fit multiplicative factor GJR model.

    tau_func: how to compute tau from VIX
      'log_exp': tau_t = exp(theta0 + theta1 * log(VIX_{t-1}))
      'vix_level': tau_t = exp(theta0 + theta1 * VIX_{t-1})
      'vix_squared': tau_t = max(theta0 + theta1 * VIX_{t-1}^2, eps)

    denom_mode: which tau to use when normalizing returns in g equation
      'tau_t': use current-period tau (Engle et al. 2013 logic)
      'tau_t_minus_1': use previous-period tau (DGP interpretation)
    """
    n = len(returns)

    # Lagged VIX for tau (no lookahead)
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]

    vix_lag = np.exp(log_vix_lag)  # actual VIX values (lagged)

    # Step 1: Estimate theta via regression on log(r^2) ~ tau_spec
    r2_pos = np.maximum(returns**2, 1e-16)
    log_r2 = np.log(r2_pos)

    if tau_func == 'log_exp':
        X = np.column_stack([np.ones(n), log_vix_lag])
    elif tau_func == 'vix_level':
        X = np.column_stack([np.ones(n), vix_lag])
    elif tau_func == 'vix_squared':
        X = np.column_stack([np.ones(n), vix_lag**2])
    else:
        raise ValueError(f"Unknown tau_func: {tau_func}")

    theta_init = np.linalg.lstsq(X, log_r2, rcond=None)[0]

    # Joint MLE
    # Parameter vector:
    #   free_omega=False: [theta0, theta1, alpha, gamma, beta]  (omega = 1-a-g/2-b)
    #   free_omega=True:  [theta0, theta1, omega, alpha, gamma, beta]
    def neg_loglik(params):
        if free_omega:
            if tau_func == 'vix_squared':
                theta0, theta1, omega_g, alpha, gamma_p, beta = params
                tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
            elif tau_func == 'vix_level':
                theta0, theta1, omega_g, alpha, gamma_p, beta = params
                tau = np.exp(theta0 + theta1 * vix_lag)
                tau = np.maximum(tau, 1e-16)
            else:
                theta0, theta1, omega_g, alpha, gamma_p, beta = params
                tau = np.exp(theta0 + theta1 * log_vix_lag)
                tau = np.maximum(tau, 1e-16)
        else:
            if tau_func == 'vix_squared':
                theta0, theta1, alpha, gamma_p, beta = params
                tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
            elif tau_func == 'vix_level':
                theta0, theta1, alpha, gamma_p, beta = params
                tau = np.exp(theta0 + theta1 * vix_lag)
                tau = np.maximum(tau, 1e-16)
            else:
                theta0, theta1, alpha, gamma_p, beta = params
                tau = np.exp(theta0 + theta1 * log_vix_lag)
                tau = np.maximum(tau, 1e-16)
            omega_g = 1.0 - alpha - gamma_p / 2.0 - beta

        if omega_g <= 0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if not free_omega and (alpha + gamma_p / 2.0 + beta >= 1.0):
            return 1e10
        if free_omega and (alpha + gamma_p / 2.0 + beta >= 0.999):
            return 1e10

        # E(g) = omega / (1 - alpha - gamma/2 - beta)
        # For free omega, g[0] initialized at E(g) instead of 1
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg if free_omega else 1.0
        ll = 0.0

        for t in range(1, n):
            if denom_mode == 'tau_t':
                u_prev = returns[t-1] / np.sqrt(tau[t])
            else:
                u_prev = returns[t-1] / np.sqrt(tau[t-1])

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

    if free_omega:
        # 6 parameters: theta0, theta1, omega, alpha, gamma, beta
        if tau_func == 'vix_squared':
            var0 = np.var(returns)
            vix2_mean = np.mean(vix_lag**2) + 1e-8
            starts = [
                [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
                [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
                [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
            ]
            bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
                      (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
        else:
            starts = [
                [theta_init[0], theta_init[1], 0.05, 0.05, 0.05, 0.90],
                [theta_init[0], theta_init[1], 0.10, 0.03, 0.08, 0.88],
                [theta_init[0], theta_init[1], 0.02, 0.08, 0.10, 0.80],
            ]
            bounds = [(-20, 0), (0.1, 5.0),
                      (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    else:
        # 5 parameters: theta0, theta1, alpha, gamma, beta
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.05, 0.90],
            [theta_init[0], theta_init[1], 0.03, 0.08, 0.88],
            [theta_init[0], theta_init[1], 0.08, 0.10, 0.80],
        ]
        if tau_func == 'vix_squared':
            bounds = [(-1e-2, 1e-2), (1e-8, 1e-3), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
            var0 = np.var(returns)
            starts = [
                [var0 * 0.1, var0 / (np.mean(vix_lag**2) + 1e-8), 0.05, 0.05, 0.90],
                [var0 * 0.05, var0 / (np.mean(vix_lag**2) + 1e-8) * 0.5, 0.03, 0.08, 0.88],
                [var0 * 0.2, var0 / (np.mean(vix_lag**2) + 1e-8) * 1.5, 0.08, 0.10, 0.80],
            ]
        else:
            bounds = [(-20, 0), (0.1, 5.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

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


def compute_tau(params, log_vix_lag, vix_lag, tau_func):
    """Compute tau given parameters and lagged VIX."""
    theta0, theta1 = params[0], params[1]
    if tau_func == 'log_exp':
        return np.maximum(np.exp(theta0 + theta1 * log_vix_lag), 1e-16)
    elif tau_func == 'vix_level':
        return np.maximum(np.exp(theta0 + theta1 * vix_lag), 1e-16)
    elif tau_func == 'vix_squared':
        return np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)


# --- GARCH-MIDAS(VIX) with Beta weighting ---
def beta_weights(K, omega1, omega2):
    """Compute normalized Beta polynomial weights for MIDAS."""
    k_vals = np.arange(1, K + 1, dtype=np.float64) / K
    raw = k_vals**(omega1 - 1) * (1 - k_vals)**(omega2 - 1)
    raw_sum = raw.sum()
    if raw_sum < 1e-16:
        return np.ones(K) / K
    return raw / raw_sum


def fit_garch_midas_vix(returns, vix_vals, K_midas):
    """
    Fit proper GARCH-MIDAS(VIX) with rolling window specification.

    Eq (3): r_t = mu + sqrt(tau_t * g_t) * eps_t
    Eq (4): g_t = (1-alpha-gamma/2-beta) + alpha*(r_{t-1}-mu)^2/tau_t + gamma*(...)*I + beta*g_{t-1}
    tau_t = exp(m + theta * sum_{k=1}^{K} phi_k(w1,w2) * log(VIX_{t-k}))

    Note: denominator in g equation is tau_t (predetermined, per Engle et al. 2013 Eq.4)
    """
    n = len(returns)
    log_vix_v = np.log(np.maximum(vix_vals, 1.0))

    # Build MIDAS regressor matrix: for each t, need VIX_{t-1}, ..., VIX_{t-K}
    # We need at least K past observations
    valid_start = K_midas
    n_valid = n - valid_start

    if n_valid < 500:
        return None, valid_start

    # Pre-compute lagged VIX matrix
    vix_lags = np.empty((n_valid, K_midas))
    for k in range(K_midas):
        vix_lags[:, k] = log_vix_v[valid_start - 1 - k:n - 1 - k]

    ret_valid = returns[valid_start:]

    def neg_loglik(params):
        m_param, theta, alpha, gamma_p, beta_g, omega1, omega2 = params

        if omega1 < 1.0 or omega2 < 1.0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta_g < 0:
            return 1e10
        omega_g = 1.0 - alpha - gamma_p / 2.0 - beta_g
        if omega_g <= 0 or alpha + gamma_p / 2.0 + beta_g >= 1.0:
            return 1e10

        # Beta weights
        weights = beta_weights(K_midas, omega1, omega2)

        # Compute tau for each valid observation
        midas_component = vix_lags @ weights  # (n_valid,)
        log_tau = m_param + theta * midas_component
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        # Short-run g (GJR on standardized returns)
        g = np.empty(n_valid)
        g[0] = 1.0
        ll = 0.0

        for t in range(1, n_valid):
            u_prev = ret_valid[t-1] / np.sqrt(tau[t])  # denominator = tau_t (current, predetermined)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta_g * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n_valid):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + ret_valid[t]**2 / sigma2)

        return -ll

    best_ll = np.inf
    best_params = None

    # Initial values
    starts = [
        [-10.0, 1.0, 0.05, 0.05, 0.90, 1.5, 2.0],
        [-8.0, 0.5, 0.03, 0.08, 0.88, 1.0, 5.0],
        [-12.0, 1.5, 0.08, 0.10, 0.80, 2.0, 3.0],
    ]

    bounds = [
        (-20, 0),      # m
        (0.01, 5.0),   # theta
        (1e-4, 0.3),   # alpha
        (1e-4, 0.3),   # gamma
        (0.5, 0.999),  # beta
        (1.0, 20.0),   # omega1 (Beta weight param)
        (1.0, 20.0),   # omega2 (Beta weight param)
    ]

    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, valid_start


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")

# Storage for all model forecasts
model_names = [
    'B0_GJR',
    'A1_K889_original',
    'A2_consistent_tau_t',
    'A3_consistent_tau_t1',
    'A4_vix_squared',
    'A5_vix_level',
    'A2f_free_omega',
    'A4f_vix2_free_omega',
    'B1_MIDAS_K22',
    'B2_MIDAS_K65',
    'B3_MIDAS_K125',
]

forecasts = {name: np.full(n_oos_actual, np.nan) for name in model_names}

# Track parameters for each model
param_history = {name: [] for name in model_names}

# Refit schedule
refit_count = 0

# State variables for recursive forecasting
states = {}
for name in model_names:
    states[name] = {'h': None, 'g': None, 'tau_prev': None, 'params': None}

# MIDAS configurations
midas_configs = {
    'B1_MIDAS_K22': 22,
    'B2_MIDAS_K65': 65,
    'B3_MIDAS_K125': 125,
}

# MF-X configurations: (tau_func, denom_mode, free_omega)
mfx_configs = {
    'A1_K889_original': ('log_exp', 'tau_t_minus_1', False),  # estimation uses tau_t, OOS uses tau_{t-1}
    'A2_consistent_tau_t': ('log_exp', 'tau_t', False),
    'A3_consistent_tau_t1': ('log_exp', 'tau_t_minus_1', False),
    'A4_vix_squared': ('vix_squared', 'tau_t', False),
    'A5_vix_level': ('vix_level', 'tau_t', False),
    'A2f_free_omega': ('log_exp', 'tau_t', True),
    'A4f_vix2_free_omega': ('vix_squared', 'tau_t', True),
}

# For A1 specifically: estimation uses tau_t but OOS uses tau_{t-1} (the K889 bug)
# For A3: estimation AND OOS both use tau_{t-1} (fully consistent DGP interpretation)

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
        train_log_vix = log_vix[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # B0: GJR
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            states['B0_GJR']['params'] = gjr_params
            # Initialize h from last training observation
            h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            states['B0_GJR']['h'] = h

        # Part A: MF-X models
        for name, (tau_func, denom_mode, is_free_omega) in mfx_configs.items():
            # For A1: estimate with tau_t (like K889 estimation)
            est_denom = 'tau_t' if name == 'A1_K889_original' else denom_mode
            mfx_params = fit_mfgjr_x(train_ret, train_log_vix, train_vix,
                                      tau_func=tau_func, denom_mode=est_denom,
                                      free_omega=is_free_omega)
            if mfx_params is not None:
                states[name]['params'] = mfx_params
                states[name]['free_omega'] = is_free_omega
                # Initialize g from training
                theta0, theta1 = mfx_params[0], mfx_params[1]
                if is_free_omega:
                    omega_g = mfx_params[2]
                    alpha_p, gamma_p, beta_p = mfx_params[3], mfx_params[4], mfx_params[5]
                else:
                    alpha_p, gamma_p, beta_p = mfx_params[2], mfx_params[3], mfx_params[4]
                    omega_g = 1.0 - alpha_p - gamma_p / 2.0 - beta_p

                n_train = len(train_ret)
                log_vix_lag_tr = np.empty(n_train)
                log_vix_lag_tr[0] = train_log_vix[0]
                log_vix_lag_tr[1:] = train_log_vix[:-1]
                vix_lag_tr = np.exp(log_vix_lag_tr)

                tau_train = compute_tau(mfx_params, log_vix_lag_tr, vix_lag_tr, tau_func)

                # Initialize g at E(g) for free_omega, 1.0 for constrained
                persist = alpha_p + gamma_p / 2.0 + beta_p
                eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg if is_free_omega else 1.0
                for i in range(1, n_train):
                    if est_denom == 'tau_t':
                        u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i], 1e-16))
                    else:
                        u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i-1], 1e-16))
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)

                states[name]['g'] = g
                states[name]['tau_prev'] = tau_train[-1]

        # Part B: GARCH-MIDAS models
        for name, K_m in midas_configs.items():
            # Need enough data for MIDAS lags
            if len(train_ret) > K_m + 100:
                midas_params, valid_start = fit_garch_midas_vix(train_ret, train_vix, K_m)
                if midas_params is not None:
                    states[name]['params'] = midas_params
                    # Initialize g from training tail
                    m_p, theta_p = midas_params[0], midas_params[1]
                    alpha_p, gamma_p, beta_p = midas_params[2], midas_params[3], midas_params[4]
                    omega1_p, omega2_p = midas_params[5], midas_params[6]

                    weights = beta_weights(K_m, omega1_p, omega2_p)
                    omega_g = 1.0 - alpha_p - gamma_p / 2.0 - beta_p

                    # Compute tau and g for last part of training
                    log_vix_tr = np.log(np.maximum(train_vix, 1.0))
                    g = 1.0
                    tau_last = None
                    for i in range(valid_start, len(train_ret)):
                        # MIDAS tau
                        midas_sum = sum(weights[k] * log_vix_tr[i - 1 - k]
                                       for k in range(K_m) if i - 1 - k >= 0)
                        tau_i = max(np.exp(m_p + theta_p * midas_sum), 1e-16)

                        if i > valid_start:
                            u_prev = train_ret[i-1] / np.sqrt(tau_i)  # tau_t denominator
                            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                            g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                            g = max(g, 1e-10)
                        tau_last = tau_i

                    states[name]['g'] = g
                    states[name]['tau_prev'] = tau_last

    # --- Generate forecasts for day abs_idx ---

    # B0: GJR
    p = states['B0_GJR']['params']
    if p is not None:
        h_prev = states['B0_GJR']['h']
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        forecasts['B0_GJR'][t_idx] = h_new
        states['B0_GJR']['h'] = h_new

    # Part A: MF-X models
    for name, (tau_func, denom_mode, is_free_omega) in mfx_configs.items():
        p = states[name]['params']
        if p is None:
            continue

        theta0, theta1 = p[0], p[1]
        if is_free_omega:
            omega_g = p[2]
            alpha_p, gamma_p, beta_p = p[3], p[4], p[5]
        else:
            alpha_p, gamma_p, beta_p = p[2], p[3], p[4]
            omega_g = 1.0 - alpha_p - gamma_p / 2.0 - beta_p

        # Compute tau_t (for today's forecast)
        # tau_t uses VIX_{t-1} — predetermined
        lv_lag = log_vix[abs_idx - 1]
        v_lag = vix[abs_idx - 1]
        tau_t = compute_tau(p, lv_lag, v_lag, tau_func)
        if isinstance(tau_t, np.ndarray):
            tau_t = float(tau_t[0]) if len(tau_t) > 0 else float(tau_t)

        # Update g using r_{t-1}
        r_prev = ret[abs_idx - 1]
        g_prev = states[name]['g']
        tau_prev = states[name]['tau_prev']

        # Key difference: which tau to use as denominator
        if name == 'A1_K889_original':
            # K889 bug: OOS uses tau_{t-1} as denominator
            u_prev = r_prev / np.sqrt(max(tau_prev, 1e-16))
        elif denom_mode == 'tau_t':
            # Engle et al. (2013) logic: denominator = tau_t (current, predetermined)
            u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        else:  # tau_t_minus_1
            # DGP interpretation: r_{t-1} generated under tau_{t-1}
            u_prev = r_prev / np.sqrt(max(tau_prev, 1e-16))

        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        forecasts[name][t_idx] = tau_t * g_new
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t

    # Part B: MIDAS models
    for name, K_m in midas_configs.items():
        p = states[name]['params']
        if p is None:
            continue

        m_p, theta_p = p[0], p[1]
        alpha_p, gamma_p, beta_p = p[2], p[3], p[4]
        omega1_p, omega2_p = p[5], p[6]
        omega_g = 1.0 - alpha_p - gamma_p / 2.0 - beta_p

        weights = beta_weights(K_m, omega1_p, omega2_p)

        # Compute tau_t using MIDAS-weighted past K VIX values
        log_vix_history = []
        for k in range(K_m):
            idx_k = abs_idx - 1 - k
            if idx_k >= 0:
                log_vix_history.append(log_vix[idx_k])
            else:
                log_vix_history.append(log_vix[0])

        midas_sum = sum(weights[k] * log_vix_history[k] for k in range(K_m))
        tau_t = max(np.exp(m_p + theta_p * midas_sum), 1e-16)

        # Update g
        r_prev = ret[abs_idx - 1]
        g_prev = states[name]['g']

        # Denominator = tau_t (per Engle et al. 2013 Eq.4)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        forecasts[name][t_idx] = tau_t * g_new
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")


# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_r2 = r2[oos_indices]
results = {'models': {}, 'dm_tests': {}, 'metadata': {}}

# Compute QLIKE, MSE, Spearman for each model
print(f"\n  {'Model':<25} {'QLIKE':>8} {'MSE':>12} {'Spearman':>10} {'Valid':>6}")
print(f"  {'-'*25} {'-'*8} {'-'*12} {'-'*10} {'-'*6}")

for name in model_names:
    fc = forecasts[name]
    valid = ~np.isnan(fc) & (fc > 0)
    n_valid = valid.sum()

    if n_valid < 100:
        print(f"  {name:<25} {'N/A':>8} {'N/A':>12} {'N/A':>10} {n_valid:>6}")
        results['models'][name] = {'status': 'insufficient_data', 'n_valid': int(n_valid)}
        continue

    fc_v = fc[valid]
    r2_v = oos_r2[valid]

    # QLIKE
    ql = float(np.mean(np.log(fc_v) + r2_v / fc_v))

    # MSE
    mse = float(np.mean((fc_v - r2_v)**2))

    # Spearman
    rho, rho_p = stats.spearmanr(fc_v, r2_v)

    print(f"  {name:<25} {ql:>8.4f} {mse:>12.2e} {rho:>10.4f} {n_valid:>6}")

    results['models'][name] = {
        'qlike': ql,
        'mse': mse,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
        'n_valid': int(n_valid),
    }

# DM tests: all models vs B0_GJR
print(f"\n  DM Tests vs B0_GJR (QLIKE loss, Harvey t > 3.0):")
print(f"  {'Model':<25} {'DM t-stat':>10} {'p-value':>10} {'Sig?':>6}")
print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*6}")

gjr_fc = forecasts['B0_GJR']
gjr_valid = ~np.isnan(gjr_fc) & (gjr_fc > 0)

for name in model_names:
    if name == 'B0_GJR':
        continue

    fc = forecasts[name]
    both_valid = gjr_valid & ~np.isnan(fc) & (fc > 0)
    n_both = both_valid.sum()

    if n_both < 100:
        print(f"  {name:<25} {'N/A':>10} {'N/A':>10} {'N/A':>6}")
        results['dm_tests'][f'{name}_vs_GJR'] = {'status': 'insufficient_data'}
        continue

    # QLIKE pointwise losses
    loss_gjr = np.log(gjr_fc[both_valid]) + oos_r2[both_valid] / gjr_fc[both_valid]
    loss_model = np.log(fc[both_valid]) + oos_r2[both_valid] / fc[both_valid]

    d = loss_gjr - loss_model  # positive = model better than GJR

    # DM test with HAC (Newey-West)
    d_mean = np.mean(d)
    T = len(d)

    # Newey-West HAC variance
    max_lag = int(np.floor(T**(1/3)))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j

    dm_stat = d_mean / np.sqrt(max(hac_var / T, 1e-20))
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    sig = "YES" if abs(dm_stat) > 3.0 else "No"

    print(f"  {name:<25} {dm_stat:>10.3f} {dm_p:>10.4f} {sig:>6}")

    results['dm_tests'][f'{name}_vs_GJR'] = {
        'dm_t': float(dm_stat),
        'dm_p': float(dm_p),
        'significant_harvey': abs(dm_stat) > 3.0,
        'n_compared': int(n_both),
        'direction': 'model_better' if dm_stat > 0 else 'gjr_better',
    }

# Pairwise DM: A2 vs A1, A2 vs A3 (key comparisons)
print(f"\n  Key Pairwise DM Tests:")
key_pairs = [
    ('A2_consistent_tau_t', 'A1_K889_original', 'Consistent τ_t vs K889-original'),
    ('A2_consistent_tau_t', 'A3_consistent_tau_t1', 'τ_t denom vs τ_{t-1} denom'),
    ('A4_vix_squared', 'A2_consistent_tau_t', 'VIX² vs log-exp'),
    ('B1_MIDAS_K22', 'A2_consistent_tau_t', 'MIDAS-22 vs GARCH-X'),
    ('B2_MIDAS_K65', 'A2_consistent_tau_t', 'MIDAS-65 vs GARCH-X'),
    ('B3_MIDAS_K125', 'A2_consistent_tau_t', 'MIDAS-125 vs GARCH-X'),
]

for name1, name2, desc in key_pairs:
    fc1 = forecasts[name1]
    fc2 = forecasts[name2]
    both_valid = ~np.isnan(fc1) & (fc1 > 0) & ~np.isnan(fc2) & (fc2 > 0)
    n_both = both_valid.sum()

    if n_both < 100:
        print(f"  {desc:<40} N/A")
        continue

    loss1 = np.log(fc1[both_valid]) + oos_r2[both_valid] / fc1[both_valid]
    loss2 = np.log(fc2[both_valid]) + oos_r2[both_valid] / fc2[both_valid]
    d = loss2 - loss1  # positive = name1 better

    d_mean = np.mean(d)
    T = len(d)
    max_lag = int(np.floor(T**(1/3)))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j

    dm_stat = d_mean / np.sqrt(max(hac_var / T, 1e-20))
    sig = "***" if abs(dm_stat) > 3.0 else ("*" if abs(dm_stat) > 1.96 else "")
    winner = name1 if dm_stat > 0 else name2
    print(f"  {desc:<40} DM t={dm_stat:+.3f} {sig} → {winner}")

    results['dm_tests'][f'{name1}_vs_{name2}'] = {
        'dm_t': float(dm_stat),
        'significant_harvey': abs(dm_stat) > 3.0,
        'winner': winner,
    }


# ============================================================
# SECTION 6: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Rank by QLIKE
ranked = [(name, results['models'][name]['qlike'])
          for name in model_names
          if 'qlike' in results['models'].get(name, {})]
ranked.sort(key=lambda x: x[1])

print(f"\n  QLIKE Rankings (lower = better):")
print(f"  {'Rank':>4} {'Model':<25} {'QLIKE':>8} {'vs GJR':>8} {'DM t':>8}")
print(f"  {'-'*4} {'-'*25} {'-'*8} {'-'*8} {'-'*8}")

gjr_qlike = results['models'].get('B0_GJR', {}).get('qlike', None)

for rank, (name, ql) in enumerate(ranked, 1):
    if gjr_qlike:
        pct_diff = (ql - gjr_qlike) / gjr_qlike * 100
        pct_str = f"{pct_diff:+.2f}%"
    else:
        pct_str = "N/A"

    dm_key = f'{name}_vs_GJR'
    dm_t = results['dm_tests'].get(dm_key, {}).get('dm_t', None)
    dm_str = f"{dm_t:+.2f}" if dm_t is not None else "ref"

    print(f"  {rank:>4} {name:<25} {ql:>8.4f} {pct_str:>8} {dm_str:>8}")

# Metadata
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'SPY',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'oos_start': OOS_START,
    'n_total': n_total,
    'n_oos': n_oos_actual,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Engle & Rangel (2008). Spline-GARCH. RFS 21(3):1187-1222.',
        'Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
    ],
}

# Save results
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")


# ============================================================
# SECTION 7: PLOTS
# ============================================================
print("\n[7] Generating plots...")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Plot 1: QLIKE comparison bar chart
    ax = axes[0, 0]
    names_ranked = [r[0] for r in ranked]
    qlikes_ranked = [r[1] for r in ranked]
    colors = ['#2196F3' if 'A' in n else '#FF9800' if 'B' in n and 'B0' not in n else '#4CAF50'
              for n in names_ranked]
    bars = ax.barh(range(len(names_ranked)), qlikes_ranked, color=colors)
    ax.set_yticks(range(len(names_ranked)))
    ax.set_yticklabels([n.replace('_', '\n') for n in names_ranked], fontsize=8)
    ax.set_xlabel('QLIKE (lower = better)')
    ax.set_title('QLIKE Ranking: All Specifications')
    ax.invert_yaxis()

    # Plot 2: DM t-statistics vs GJR
    ax = axes[0, 1]
    dm_names = []
    dm_vals = []
    for name in model_names:
        if name == 'B0_GJR':
            continue
        dm_key = f'{name}_vs_GJR'
        dm_t = results['dm_tests'].get(dm_key, {}).get('dm_t', None)
        if dm_t is not None:
            dm_names.append(name)
            dm_vals.append(dm_t)

    colors_dm = ['green' if v > 3.0 else 'orange' if v > 0 else 'red' for v in dm_vals]
    ax.barh(range(len(dm_names)), dm_vals, color=colors_dm)
    ax.axvline(x=3.0, color='red', linestyle='--', label='Harvey t=3.0')
    ax.axvline(x=-3.0, color='red', linestyle='--')
    ax.axvline(x=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_yticks(range(len(dm_names)))
    ax.set_yticklabels([n.replace('_', '\n') for n in dm_names], fontsize=8)
    ax.set_xlabel('DM t-stat vs GJR (positive = better)')
    ax.set_title('DM Tests vs GJR Benchmark')
    ax.legend(fontsize=8)
    ax.invert_yaxis()

    # Plot 3: Spearman rank correlation
    ax = axes[1, 0]
    spearman_data = [(name, results['models'][name]['spearman_rho'])
                     for name in model_names
                     if 'spearman_rho' in results['models'].get(name, {})]
    spearman_data.sort(key=lambda x: x[1], reverse=True)
    sp_names = [s[0] for s in spearman_data]
    sp_vals = [s[1] for s in spearman_data]
    colors_sp = ['#2196F3' if 'A' in n else '#FF9800' if 'B' in n and 'B0' not in n else '#4CAF50'
                 for n in sp_names]
    ax.barh(range(len(sp_names)), sp_vals, color=colors_sp)
    ax.set_yticks(range(len(sp_names)))
    ax.set_yticklabels([n.replace('_', '\n') for n in sp_names], fontsize=8)
    ax.set_xlabel('Spearman ρ (higher = better)')
    ax.set_title('Spearman Rank Correlation with r²')
    ax.invert_yaxis()

    # Plot 4: Time series of forecasts (subset)
    ax = axes[1, 1]
    plot_models = ['B0_GJR', 'A2_consistent_tau_t', 'B2_MIDAS_K65']
    oos_dates = df.index[oos_indices]
    for name in plot_models:
        fc = forecasts[name]
        valid = ~np.isnan(fc)
        if valid.sum() > 0:
            # Rolling average for visibility
            window_avg = pd.Series(fc[valid]).rolling(22, min_periods=1).mean()
            ax.plot(oos_dates[valid], window_avg, label=name, alpha=0.8)

    r2_smooth = pd.Series(oos_r2).rolling(22, min_periods=1).mean()
    ax.plot(oos_dates, r2_smooth, 'k--', alpha=0.3, label='r² (22d avg)')
    ax.set_ylabel('Conditional Variance')
    ax.set_title('Forecast Time Series (22-day MA)')
    ax.legend(fontsize=8)
    ax.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    fig_path = os.path.join(SCRIPT_DIR, 'k988_specification_comparison.png')
    plt.savefig(fig_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved: {fig_path}")

except Exception as e:
    print(f"  Plot error: {e}")

print(f"\n{'='*70}")
print(f"K988 COMPLETE. Total time: {time.time() - START_TIME:.0f}s")
print(f"{'='*70}")
