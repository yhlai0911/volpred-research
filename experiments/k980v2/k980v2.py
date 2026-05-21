"""
K980v2: Threshold GJR-GARCH — Correct Joint MLE Implementation
===============================================================

Motivation:
-----------
K980 (FAIL per Codex primary-path review 2026-05-17) implemented the Threshold GJR by
fitting two SEPARATE GJR models on non-contiguous subset arrays, then evaluating
with a CONTINUOUS h_t recursion. This is an estimation-evaluation mismatch: the model
estimated ≠ the model evaluated.

K980v2 fixes this by implementing TRUE JOINT MLE over the full time series, where:
  - h_t recursion is continuous (never restarted at regime switches)
  - The likelihood is summed over ALL t simultaneously
  - Regime-specific parameters apply to h_t update at each t based on VIX_{t-1}

Core model (TGJR):
  h_t = omega[s_t] + alpha[s_t]*e_{t-1}^2 + gamma[s_t]*I(e_{t-1}<0)*e_{t-1}^2
        + beta[s_t]*h_{t-1}
  where s_t = I(VIX_{t-1} > c)  (0 = low VIX, 1 = high VIX)
  h_{t-1} is the SAME continuous variance state regardless of regime

Baseline:
  Standard GJR-GARCH(1,1) — same scipy MLE, 20 multistart

References:
  - Glosten, Jagannathan & Runkle (1993): GJR-GARCH
  - Zakoian (1994): Threshold GARCH
  - Patton (2011): QLIKE loss for volatility model comparison
  - Diebold & Mariano (1995): Predictive accuracy comparison
  - Hansen & Lunde (2005): Forecast comparison of volatility models

Data: SPY + ^VIX from yfinance, 2006-01-05 to 2026-04-06
IS: 2006-2018, OOS: 2019-2026

Author: VolPred Research System
Experiment ID: k980v2
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from scipy.stats import norm, chi2
from pathlib import Path
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)
rng = np.random.default_rng(42)

BASE_DIR = Path(__file__).parent

print("=" * 70)
print("K980v2: Threshold GJR-GARCH — Correct Joint MLE Implementation")
print("=" * 70)

# ============================================================
# 1. Data Download & Preparation
# ============================================================
print("\n[1] Downloading data...")

spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle MultiIndex columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Compute log returns
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['ret'])

# Merge VIX — STEP 1: apply shift(1) FIRST before any downstream use
vix_close = vix[['Close']].rename(columns={'Close': 'VIX'})
data = spy[['ret']].join(vix_close, how='inner')

# CRITICAL: VIX lag applied here, FIRST thing, before split or anything else
data['VIX_lag'] = data['VIX'].shift(1)  # VIX_{t-1} — NO LOOKAHEAD
data = data.dropna()  # removes first row with NaN VIX_lag

# Squared returns as proxy for realized variance
data['r2'] = data['ret'] ** 2

print(f"Total observations: {len(data)}")
print(f"Date range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"VIX mean: {data['VIX'].mean():.2f}, median: {data['VIX'].median():.2f}")
print(f"VIX_lag mean: {data['VIX_lag'].mean():.2f}")

# Split IS/OOS
is_mask = data.index < '2019-01-01'
oos_mask = data.index >= '2019-01-01'
data_is = data[is_mask].copy()
data_oos = data[oos_mask].copy()

print(f"\nIS: {len(data_is)} obs ({data_is.index[0].date()} to {data_is.index[-1].date()})")
print(f"OOS: {len(data_oos)} obs ({data_oos.index[0].date()} to {data_oos.index[-1].date()})")

returns_is = data_is['ret'].values
returns_oos = data_oos['ret'].values
vix_lag_is = data_is['VIX_lag'].values   # VIX_{t-1} for IS
vix_lag_oos = data_oos['VIX_lag'].values  # VIX_{t-1} for OOS
r2_oos = returns_oos ** 2

# Full combined series for OOS recursion (need last IS return as r_{t-1} for first OOS step)
all_returns = np.concatenate([returns_is, returns_oos])

# ============================================================
# 2. Core Model Functions
# ============================================================

def qlike_loss(actual, forecast):
    """QLIKE loss per observation (element-wise). Patton (2011)."""
    actual_c = np.maximum(actual, 1e-12)
    forecast_c = np.maximum(forecast, 1e-12)
    return actual_c / forecast_c - np.log(actual_c / forecast_c) - 1


def qlike(actual, forecast):
    """Mean QLIKE loss."""
    return np.mean(qlike_loss(actual, forecast))


def compute_h_gjr(params, returns, h0=None):
    """
    Compute full conditional variance sequence for GJR-GARCH(1,1).
    params = [omega, alpha, gamma, beta]
    Returns h array of length T.
    """
    omega, alpha, gamma, beta = params
    T = len(returns)
    h = np.empty(T)
    h[0] = h0 if h0 is not None else np.var(returns)

    for t in range(1, T):
        r_prev = returns[t - 1]
        ind = 1.0 if r_prev < 0 else 0.0
        h_t = omega + alpha * r_prev ** 2 + gamma * r_prev ** 2 * ind + beta * h[t - 1]
        h[t] = max(h_t, 1e-10)

    return h


def gjr_negloglik(params, returns):
    """Negative Gaussian log-likelihood for GJR-GARCH."""
    omega, alpha, gamma, beta = params
    # Stationarity check in log-space
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e15
    if alpha + beta + 0.5 * gamma >= 0.999:
        return 1e15

    h = compute_h_gjr(params, returns)
    ll = -0.5 * np.sum(np.log(h) + returns ** 2 / h)
    return -ll  # return negative for minimization


def compute_h_tgjr_with_c(params, returns, vix_lag, c, h0=None):
    """
    TGJR with explicit threshold c. Regime: s_t = I(vix_lag[t] > c).
    h_t is CONTINUOUS — not restarted at regime boundaries.
    """
    omega_L, alpha_L, gamma_L, beta_L = params[0:4]
    omega_H, alpha_H, gamma_H, beta_H = params[4:8]

    T = len(returns)
    h = np.empty(T)
    h[0] = h0 if h0 is not None else np.var(returns)

    for t in range(1, T):
        r_prev = returns[t - 1]
        ind = 1.0 if r_prev < 0 else 0.0
        r2_prev = r_prev ** 2
        h_prev = h[t - 1]

        if vix_lag[t] <= c:
            h_t = omega_L + alpha_L * r2_prev + gamma_L * r2_prev * ind + beta_L * h_prev
        else:
            h_t = omega_H + alpha_H * r2_prev + gamma_H * r2_prev * ind + beta_H * h_prev

        h[t] = max(h_t, 1e-10)

    return h


def tgjr_negloglik(params, returns, vix_lag, c):
    """
    Negative Gaussian log-likelihood for TGJR-GARCH.
    JOINT MLE: single pass over full time series, h_t continuous.
    params = [omega_low, alpha_low, gamma_low, beta_low,
              omega_high, alpha_high, gamma_high, beta_high]
    """
    omega_L, alpha_L, gamma_L, beta_L = params[0:4]
    omega_H, alpha_H, gamma_H, beta_H = params[4:8]

    # Positivity and stationarity constraints
    if any(x <= 0 for x in [omega_L, omega_H]):
        return 1e15
    if any(x < 0 for x in [alpha_L, gamma_L, beta_L, alpha_H, gamma_H, beta_H]):
        return 1e15
    if alpha_L + beta_L + 0.5 * gamma_L >= 0.999:
        return 1e15
    if alpha_H + beta_H + 0.5 * gamma_H >= 0.999:
        return 1e15

    h = compute_h_tgjr_with_c(params, returns, vix_lag, c)
    ll = -0.5 * np.sum(np.log(h) + returns ** 2 / h)
    return -ll


# ============================================================
# 3. Multistart MLE Helpers
# ============================================================

def sample_gjr_init(var_r, n, rng_obj):
    """Sample n random starting points for GJR-GARCH."""
    inits = []
    for _ in range(n):
        omega = rng_obj.uniform(1e-7, var_r * 0.1)
        alpha = rng_obj.uniform(0.01, 0.15)
        gamma = rng_obj.uniform(0.0, 0.15)
        beta = rng_obj.uniform(0.7, 0.97)
        # enforce stationarity
        pers = alpha + beta + 0.5 * gamma
        if pers >= 0.999:
            beta = 0.999 - alpha - 0.5 * gamma - 0.001
        if beta < 0.01:
            beta = 0.01
        inits.append([omega, alpha, gamma, beta])
    return inits


def sample_tgjr_init(var_r, n, rng_obj):
    """Sample n random starting points for TGJR-GARCH (8 params)."""
    inits = []
    for _ in range(n):
        params = []
        for _ in range(2):  # low then high regime
            omega = rng_obj.uniform(1e-7, var_r * 0.1)
            alpha = rng_obj.uniform(0.01, 0.12)
            gamma = rng_obj.uniform(0.0, 0.12)
            beta = rng_obj.uniform(0.70, 0.96)
            pers = alpha + beta + 0.5 * gamma
            if pers >= 0.999:
                beta = 0.999 - alpha - 0.5 * gamma - 0.001
            if beta < 0.01:
                beta = 0.01
            params.extend([omega, alpha, gamma, beta])
        inits.append(params)
    return inits


def fit_gjr_multistart(returns, n_starts=20, rng_obj=None):
    """
    Fit GJR-GARCH by MLE with n_starts random initializations.
    Returns best (highest log-likelihood) result.
    """
    if rng_obj is None:
        rng_obj = np.random.default_rng(42)

    var_r = np.var(returns)
    bounds = [(1e-8, var_r), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.999)]

    # Canonical starting point + random ones
    x0_canonical = [var_r * 0.05, 0.07, 0.07, 0.88]
    starts = [x0_canonical] + sample_gjr_init(var_r, n_starts - 1, rng_obj)

    best_loglik = -np.inf
    best_result = None

    for x0 in starts:
        # Project initial point into feasible region
        x0[3] = min(x0[3], 0.999 - x0[1] - 0.5 * x0[2] - 0.001)
        try:
            res = minimize(gjr_negloglik, x0, args=(returns,),
                           method='L-BFGS-B', bounds=bounds,
                           options={'maxiter': 5000, 'ftol': 1e-12, 'gtol': 1e-8})
            ll = -res.fun
            if ll > best_loglik and res.fun < 1e14:
                best_loglik = ll
                best_result = res
        except Exception:
            continue

    if best_result is None:
        raise RuntimeError("GJR fitting failed on all starts")

    p = best_result.x
    return {
        'omega': float(p[0]),
        'alpha': float(p[1]),
        'gamma': float(p[2]),
        'beta': float(p[3]),
        'persistence': float(p[1] + p[3] + 0.5 * p[2]),
        'loglik': float(best_loglik),
        'converged': bool(best_result.success),
        'nobs': int(len(returns))
    }


def fit_tgjr_multistart(returns, vix_lag, c, n_starts=20, rng_obj=None):
    """
    Fit TGJR-GARCH by JOINT MLE with n_starts random initializations.
    Joint MLE: single likelihood computed over full time series.
    Returns best (highest log-likelihood) result.
    """
    if rng_obj is None:
        rng_obj = np.random.default_rng(42)

    var_r = np.var(returns)
    # Bounds: [omega_L, alpha_L, gamma_L, beta_L, omega_H, alpha_H, gamma_H, beta_H]
    bounds = [
        (1e-8, var_r), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.998),
        (1e-8, var_r), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.998),
    ]

    # Canonical starting point based on GJR fit
    gjr_fit = fit_gjr_multistart(returns, n_starts=5, rng_obj=rng_obj)
    p_gjr = [gjr_fit['omega'], gjr_fit['alpha'], gjr_fit['gamma'], gjr_fit['beta']]
    x0_canonical = p_gjr + p_gjr  # both regimes start at GJR estimates

    starts = [x0_canonical] + sample_tgjr_init(var_r, n_starts - 1, rng_obj)

    best_loglik = -np.inf
    best_result = None
    loglik_values = []

    for x0 in starts:
        # Enforce stationarity in both regimes
        x0[3] = min(x0[3], 0.998 - x0[1] - 0.5 * x0[2] - 0.001)
        x0[7] = min(x0[7], 0.998 - x0[5] - 0.5 * x0[6] - 0.001)
        for i in [3, 7]:
            if x0[i] < 0.01:
                x0[i] = 0.01
        try:
            res = minimize(tgjr_negloglik, x0, args=(returns, vix_lag, c),
                           method='L-BFGS-B', bounds=bounds,
                           options={'maxiter': 5000, 'ftol': 1e-12, 'gtol': 1e-8})
            ll = -res.fun
            if res.fun < 1e14:
                loglik_values.append(ll)
            if ll > best_loglik and res.fun < 1e14:
                best_loglik = ll
                best_result = res
        except Exception:
            continue

    if best_result is None:
        raise RuntimeError(f"TGJR fitting failed on all starts for c={c}")

    p = best_result.x
    return {
        'omega_low': float(p[0]),
        'alpha_low': float(p[1]),
        'gamma_low': float(p[2]),
        'beta_low': float(p[3]),
        'persistence_low': float(p[1] + p[3] + 0.5 * p[2]),
        'omega_high': float(p[4]),
        'alpha_high': float(p[5]),
        'gamma_high': float(p[6]),
        'beta_high': float(p[7]),
        'persistence_high': float(p[5] + p[7] + 0.5 * p[6]),
        'loglik': float(best_loglik),
        'converged': bool(best_result.success),
        'nobs': int(len(returns)),
        'loglik_distribution': {
            'n_converged': len(loglik_values),
            'min': float(min(loglik_values)) if loglik_values else np.nan,
            'max': float(max(loglik_values)) if loglik_values else np.nan,
            'std': float(np.std(loglik_values)) if len(loglik_values) > 1 else 0.0,
        }
    }


# ============================================================
# 4. Model 1: Standard GJR-GARCH Baseline (20 multistart)
# ============================================================
print("\n[2] Fitting Standard GJR-GARCH baseline (20 multistart)...")

gjr_fit = fit_gjr_multistart(returns_is, n_starts=20, rng_obj=rng)

print(f"  omega={gjr_fit['omega']:.6e}, alpha={gjr_fit['alpha']:.4f}, "
      f"gamma={gjr_fit['gamma']:.4f}, beta={gjr_fit['beta']:.4f}")
print(f"  Persistence: {gjr_fit['persistence']:.4f}, Converged: {gjr_fit['converged']}")
print(f"  IS log-likelihood: {gjr_fit['loglik']:.2f}")

# Reference check: K980 GJR OOS QLIKE was 1.4989
print(f"  (K980 baseline GJR IS loglik was 10781.76; reference for sanity check)")

# Compute IS conditional variances for GJR (to pass h_last into OOS)
h_is_gjr = compute_h_gjr(
    [gjr_fit['omega'], gjr_fit['alpha'], gjr_fit['gamma'], gjr_fit['beta']],
    returns_is
)

# OOS recursive forecasting — GJR
h_oos_gjr = np.empty(len(returns_oos))
h_prev = h_is_gjr[-1]

for t in range(len(returns_oos)):
    r_prev = all_returns[len(returns_is) + t - 1]
    ind = 1.0 if r_prev < 0 else 0.0
    r2_prev = r_prev ** 2
    h_t = (gjr_fit['omega'] + gjr_fit['alpha'] * r2_prev +
           gjr_fit['gamma'] * r2_prev * ind + gjr_fit['beta'] * h_prev)
    h_t = max(h_t, 1e-10)
    h_oos_gjr[t] = h_t
    h_prev = h_t

qlike_gjr = qlike(r2_oos, h_oos_gjr)
print(f"\n  GJR OOS QLIKE: {qlike_gjr:.6f}  (K980 reference: 1.4989)")

# ============================================================
# 5. Model 2: Threshold GJR-GARCH — Joint MLE (20 multistart)
# ============================================================
print("\n[3] Grid search for optimal threshold c (joint MLE, IS QLIKE criterion)...")

thresholds = [14, 16, 18, 20, 22, 24]
best_qlike_is = np.inf
best_c = None
best_tgjr_fit = None
best_h_is_tgjr = None

threshold_results = {}

for c in thresholds:
    low_mask = vix_lag_is <= c
    high_mask = vix_lag_is > c
    pct_low = low_mask.mean()
    pct_high = high_mask.mean()

    # Require each regime to have at least 15% of IS observations
    if pct_low < 0.15 or pct_high < 0.15:
        print(f"  c={c:2d}: skipped (low={pct_low:.1%}, high={pct_high:.1%})")
        continue

    print(f"  c={c:2d}: low={pct_low:.1%} ({low_mask.sum()} obs), "
          f"high={pct_high:.1%} ({high_mask.sum()} obs) — fitting TGJR joint MLE...")

    try:
        fit = fit_tgjr_multistart(returns_is, vix_lag_is, c, n_starts=20, rng_obj=rng)
    except RuntimeError as e:
        print(f"    ERROR: {e}")
        continue

    # IS conditional variances using joint-MLE parameters
    tgjr_params = [fit['omega_low'], fit['alpha_low'], fit['gamma_low'], fit['beta_low'],
                   fit['omega_high'], fit['alpha_high'], fit['gamma_high'], fit['beta_high']]
    h_is = compute_h_tgjr_with_c(tgjr_params, returns_is, vix_lag_is, c)

    # IS QLIKE (skip first 100 for burn-in)
    r2_is = returns_is ** 2
    q_is = qlike(r2_is[100:], h_is[100:])

    print(f"    IS QLIKE={q_is:.6f}, loglik={fit['loglik']:.2f}, "
          f"converged={fit['converged']}")
    print(f"    Low:  omega={fit['omega_low']:.2e}, alpha={fit['alpha_low']:.4f}, "
          f"gamma={fit['gamma_low']:.4f}, beta={fit['beta_low']:.4f}, "
          f"pers={fit['persistence_low']:.4f}")
    print(f"    High: omega={fit['omega_high']:.2e}, alpha={fit['alpha_high']:.4f}, "
          f"gamma={fit['gamma_high']:.4f}, beta={fit['beta_high']:.4f}, "
          f"pers={fit['persistence_high']:.4f}")

    threshold_results[c] = {
        'fit': fit,
        'qlike_is': float(q_is),
        'pct_low': float(pct_low),
        'pct_high': float(pct_high),
        'n_low': int(low_mask.sum()),
        'n_high': int(high_mask.sum()),
    }

    if q_is < best_qlike_is:
        best_qlike_is = q_is
        best_c = c
        best_tgjr_fit = fit
        best_h_is_tgjr = h_is.copy()

print(f"\n  Best threshold: c = {best_c} (IS QLIKE = {best_qlike_is:.6f})")

# TGJR OOS recursive forecasting
tgjr_params_best = [
    best_tgjr_fit['omega_low'], best_tgjr_fit['alpha_low'],
    best_tgjr_fit['gamma_low'], best_tgjr_fit['beta_low'],
    best_tgjr_fit['omega_high'], best_tgjr_fit['alpha_high'],
    best_tgjr_fit['gamma_high'], best_tgjr_fit['beta_high'],
]

h_oos_tgjr = np.empty(len(returns_oos))
h_prev = best_h_is_tgjr[-1]

for t in range(len(returns_oos)):
    r_prev = all_returns[len(returns_is) + t - 1]
    ind = 1.0 if r_prev < 0 else 0.0
    r2_prev = r_prev ** 2
    h_prev_val = h_prev

    if vix_lag_oos[t] <= best_c:
        h_t = (best_tgjr_fit['omega_low'] +
               best_tgjr_fit['alpha_low'] * r2_prev +
               best_tgjr_fit['gamma_low'] * r2_prev * ind +
               best_tgjr_fit['beta_low'] * h_prev_val)
    else:
        h_t = (best_tgjr_fit['omega_high'] +
               best_tgjr_fit['alpha_high'] * r2_prev +
               best_tgjr_fit['gamma_high'] * r2_prev * ind +
               best_tgjr_fit['beta_high'] * h_prev_val)

    h_t = max(h_t, 1e-10)
    h_oos_tgjr[t] = h_t
    h_prev = h_t

# ============================================================
# 6. OOS Evaluation
# ============================================================
print("\n[4] OOS Evaluation Metrics...")

target = r2_oos

def mse(actual, forecast):
    return float(np.mean((actual - forecast) ** 2))


def dm_test_hac(loss1, loss2):
    """
    Diebold-Mariano test with HAC variance.
    HAC max_lag = int(12*(T/100)^0.25) per standard formula.
    H0: equal predictive accuracy.
    Returns (dm_stat, p_value).
    """
    d = loss1 - loss2
    T = len(d)
    d_mean = np.mean(d)
    max_lag = int(12 * (T / 100) ** 0.25)

    # Newey-West HAC variance
    gamma0 = np.mean(d ** 2) - d_mean ** 2  # biased variance
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w_k = 1.0 - k / (max_lag + 1)  # Bartlett weight
        cov_k = np.mean(d[k:] * d[:-k]) - d_mean ** 2
        gamma_sum += 2.0 * w_k * cov_k

    var_d = (gamma0 + gamma_sum) / T
    if var_d <= 0:
        var_d = max(gamma0 / T, 1e-20)

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2.0 * (1.0 - norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)


def kupiec_lr_test(violations, T, alpha_level):
    """Kupiec (1995) likelihood ratio test for VaR coverage."""
    n1 = violations
    n0 = T - n1
    p_hat = n1 / T
    p_null = alpha_level
    if n1 == 0:
        lr = -2 * n0 * np.log(1 - p_null)
    elif n1 == T:
        lr = -2 * n0 * np.log(p_null)
    else:
        lr = -2 * (n0 * np.log(1 - p_null) + n1 * np.log(p_null) -
                   n0 * np.log(1 - p_hat) - n1 * np.log(p_hat))
    lr = max(lr, 0.0)
    p_kupiec = float(1 - chi2.cdf(lr, 1))
    return float(lr), p_kupiec


models = {'GJR': h_oos_gjr, 'TGJR': h_oos_tgjr}

oos_eval = {}
for name, h_oos in models.items():
    q = float(qlike(target, h_oos))
    m = mse(target, h_oos)
    oos_eval[name] = {'QLIKE': q, 'MSE': m}
    print(f"  {name}: QLIKE={q:.6f}, MSE={m:.3e}")

# DM test: GJR vs TGJR
loss_gjr = qlike_loss(target, h_oos_gjr)
loss_tgjr = qlike_loss(target, h_oos_tgjr)
dm_stat, dm_pval = dm_test_hac(loss_gjr, loss_tgjr)
T_oos = len(target)
max_lag_used = int(12 * (T_oos / 100) ** 0.25)

print(f"\n  DM test (GJR vs TGJR, HAC max_lag={max_lag_used}):")
print(f"    DM stat = {dm_stat:.4f}, p-value = {dm_pval:.4f}")
print(f"    {'TGJR beats GJR' if dm_stat > 0 else 'GJR beats TGJR'} in point estimates")

# Anomaly check
if abs(dm_stat) > 5:
    print(f"  WARNING: |DM stat| > 5 — possible lookahead or bug!")
    raise ValueError(f"DM stat anomaly: {dm_stat:.4f}")

if oos_eval['TGJR']['QLIKE'] > oos_eval['GJR']['QLIKE'] * 1.05:
    print("  WARNING: TGJR QLIKE > 5% worse than GJR — check multistart count!")

# ============================================================
# 7. Regime-Conditional OOS Evaluation
# ============================================================
print("\n[5] Regime-Conditional OOS Evaluation...")

low_oos_mask = vix_lag_oos <= best_c
high_oos_mask = vix_lag_oos > best_c

print(f"  OOS low-VIX days  (VIX_lag <= {best_c}): {low_oos_mask.sum()} ({low_oos_mask.mean():.1%})")
print(f"  OOS high-VIX days (VIX_lag >  {best_c}): {high_oos_mask.sum()} ({high_oos_mask.mean():.1%})")

regime_eval = {}
for regime_name, mask in [('Low_VIX', low_oos_mask), ('High_VIX', high_oos_mask)]:
    regime_eval[regime_name] = {}
    for name, h_oos in models.items():
        q = float(qlike(target[mask], h_oos[mask]))
        m = mse(target[mask], h_oos[mask])
        regime_eval[regime_name][name] = {'QLIKE': q, 'MSE': m}
    print(f"  {regime_name}: GJR QLIKE={regime_eval[regime_name]['GJR']['QLIKE']:.6f}, "
          f"TGJR QLIKE={regime_eval[regime_name]['TGJR']['QLIKE']:.6f}")

# ============================================================
# 8. VaR Backtesting
# ============================================================
print("\n[6] VaR Backtesting...")

var_results = {}
for alpha_level in [0.01, 0.05]:
    z = norm.ppf(alpha_level)
    var_results[f'VaR_{alpha_level}'] = {}

    for name, h_oos in models.items():
        var_forecasts = z * np.sqrt(h_oos)
        violations = int((returns_oos < var_forecasts).sum())
        vr = violations / len(returns_oos)
        lr, p_k = kupiec_lr_test(violations, len(returns_oos), alpha_level)
        status = "PASS" if p_k > 0.05 else "FAIL"

        var_results[f'VaR_{alpha_level}'][name] = {
            'violations': violations,
            'violation_rate': float(vr),
            'expected_rate': float(alpha_level),
            'kupiec_LR': float(lr),
            'kupiec_p': float(p_k),
            'kupiec_status': status
        }
        print(f"  VaR {alpha_level:.0%} {name}: "
              f"violations={violations}/{len(returns_oos)} ({vr:.3%}), "
              f"Kupiec p={p_k:.4f} [{status}]")

# ============================================================
# 9. Parameter Stationarity Check
# ============================================================
print("\n[7] Parameter Stationarity Check...")

pers_low = best_tgjr_fit['persistence_low']
pers_high = best_tgjr_fit['persistence_high']

for label, pers in [('Low regime', pers_low), ('High regime', pers_high)]:
    flag = " WARNING: persistence > 0.999!" if pers > 0.999 else ""
    print(f"  {label} persistence: {pers:.4f}{flag}")

if pers_low > 0.999 or pers_high > 0.999:
    print("  WARNING: Non-stationary TGJR — results should be interpreted with caution!")

# ============================================================
# 10. Comparison to K980 (FAIL) Baseline
# ============================================================
k980_gjr_qlike = 1.4988919784179369  # from k980_threshold_garch_results.json
pct_diff_gjr = (oos_eval['GJR']['QLIKE'] - k980_gjr_qlike) / k980_gjr_qlike * 100

print(f"\n[8] Comparison to K980 (FAIL) Baseline:")
print(f"  K980 GJR OOS QLIKE (reference): {k980_gjr_qlike:.6f}")
print(f"  K980v2 GJR OOS QLIKE:           {oos_eval['GJR']['QLIKE']:.6f}")
print(f"  Difference: {pct_diff_gjr:+.2f}% (sanity check — should be <1%)")

pct_diff_tgjr = (oos_eval['TGJR']['QLIKE'] - oos_eval['GJR']['QLIKE']) / oos_eval['GJR']['QLIKE'] * 100
print(f"\n  K980v2 TGJR vs GJR: {pct_diff_tgjr:+.2f}%")
print(f"  DM p-value: {dm_pval:.4f}")

# ============================================================
# 11. Plots
# ============================================================
print("\n[9] Generating plots...")

# --- Plot 1: OOS Forecast Comparison + Cumulative QLIKE Diff ---
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
oos_dates = data_oos.index.to_numpy()

# Panel 1: Annualized volatility forecasts
for name, h_oos in models.items():
    ann_vol = np.sqrt(h_oos * 252) * 100
    axes[0].plot(oos_dates, ann_vol, label=name, alpha=0.75, linewidth=0.8)
axes[0].set_ylabel('Annualized Volatility (%)', fontsize=10)
axes[0].set_title('K980v2: OOS Conditional Volatility Forecasts\n'
                  '(Joint-MLE Threshold GJR vs Baseline GJR)', fontsize=12, fontweight='bold')
axes[0].legend(fontsize=9)
axes[0].grid(True, alpha=0.3)

# Panel 2: Cumulative QLIKE difference (positive = TGJR worse)
qlike_diff = qlike_loss(target, h_oos_tgjr) - qlike_loss(target, h_oos_gjr)
cum_diff = np.cumsum(qlike_diff)
axes[1].plot(oos_dates, cum_diff, color='steelblue', linewidth=1)
axes[1].axhline(0, color='black', linewidth=0.7, linestyle='--')
axes[1].fill_between(oos_dates, cum_diff, 0,
                     where=cum_diff < 0, color='green', alpha=0.2, label='TGJR better')
axes[1].fill_between(oos_dates, cum_diff, 0,
                     where=cum_diff > 0, color='red', alpha=0.2, label='GJR better')
axes[1].set_ylabel('Cum. QLIKE Diff\n(TGJR − GJR)', fontsize=9)
axes[1].set_title('Cumulative QLIKE Differential (positive = TGJR worse)', fontsize=10)
axes[1].legend(fontsize=9)
axes[1].grid(True, alpha=0.3)

# Panel 3: VIX_lag with regime threshold
axes[2].plot(oos_dates, vix_lag_oos, color='gray', linewidth=0.7, alpha=0.7)
axes[2].axhline(best_c, color='red', linewidth=1.2, linestyle='--', label=f'c={best_c}')
axes[2].fill_between(oos_dates, vix_lag_oos, best_c,
                     where=vix_lag_oos <= best_c, color='blue', alpha=0.1, label='Low VIX')
axes[2].fill_between(oos_dates, vix_lag_oos, best_c,
                     where=vix_lag_oos > best_c, color='orange', alpha=0.1, label='High VIX')
axes[2].set_ylabel('VIX_{t−1}', fontsize=9)
axes[2].set_title(f'OOS VIX Regime (threshold c={best_c})', fontsize=10)
axes[2].legend(fontsize=8, loc='upper right')
axes[2].grid(True, alpha=0.3)

plt.tight_layout()
fig_path = BASE_DIR / 'k980v2_oos_comparison.png'
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig_path}")

# --- Plot 2: TGJR Parameters by Regime ---
fig, axes = plt.subplots(1, 5, figsize=(16, 4))
param_names = ['omega', 'alpha', 'gamma', 'beta', 'persistence']
low_vals = [
    best_tgjr_fit['omega_low'], best_tgjr_fit['alpha_low'],
    best_tgjr_fit['gamma_low'], best_tgjr_fit['beta_low'],
    best_tgjr_fit['persistence_low']
]
high_vals = [
    best_tgjr_fit['omega_high'], best_tgjr_fit['alpha_high'],
    best_tgjr_fit['gamma_high'], best_tgjr_fit['beta_high'],
    best_tgjr_fit['persistence_high']
]

for i, (pn, lv, hv) in enumerate(zip(param_names, low_vals, high_vals)):
    bars = axes[i].bar(['Low VIX', 'High VIX'], [lv, hv],
                       color=['#2196F3', '#F44336'], alpha=0.8)
    axes[i].set_title(pn.capitalize(), fontsize=11, fontweight='bold')
    axes[i].set_ylabel('Value', fontsize=9)
    for bar, val in zip(bars, [lv, hv]):
        axes[i].text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f'{val:.4f}', ha='center', va='bottom', fontsize=8)
    if pn == 'omega':
        axes[i].ticklabel_format(style='sci', axis='y', scilimits=(0, 0))

plt.suptitle(f'K980v2: TGJR Parameters by VIX Regime (c={best_c}, Joint MLE)',
             fontsize=12, fontweight='bold')
plt.tight_layout()
fig2_path = BASE_DIR / 'k980v2_regime_parameters.png'
plt.savefig(fig2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig2_path}")

# ============================================================
# 12. Results JSON
# ============================================================
print("\n[10] Saving results JSON...")

# Prepare threshold grid summary
threshold_summary = {}
for c_val, tr in threshold_results.items():
    fit_c = tr['fit']
    threshold_summary[str(c_val)] = {
        'qlike_is': tr['qlike_is'],
        'pct_low': tr['pct_low'],
        'pct_high': tr['pct_high'],
        'n_low': tr['n_low'],
        'n_high': tr['n_high'],
        'loglik': fit_c['loglik'],
        'converged': fit_c['converged'],
        'persistence_low': fit_c['persistence_low'],
        'persistence_high': fit_c['persistence_high'],
    }

# Key finding text
if oos_eval['TGJR']['QLIKE'] < oos_eval['GJR']['QLIKE']:
    direction_word = 'improves'
else:
    direction_word = 'worsens'

sig_text = ('statistically significant' if dm_pval < 0.05
            else 'not statistically significant')
verdict = 'EXPLORATORY_NULL' if dm_pval >= 0.05 else 'EXPLORATORY_SIGNAL'

key_finding = (
    f"K980v2 (joint MLE) TGJR {direction_word} OOS QLIKE by "
    f"{abs(pct_diff_tgjr):.2f}% vs baseline GJR. "
    f"DM test: stat={dm_stat:.3f}, p={dm_pval:.4f} "
    f"({sig_text}). "
    f"Optimal threshold c={best_c}. "
    f"Low-regime persistence={best_tgjr_fit['persistence_low']:.4f}, "
    f"high-regime persistence={best_tgjr_fit['persistence_high']:.4f}."
)

results = {
    'experiment_id': 'k980v2',
    'title': 'Threshold GJR-GARCH — Correct Joint MLE (K980 Methodology Fix)',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{data.index[0].date()} to {data.index[-1].date()}",
    'total_obs': int(len(data)),
    'is_obs': int(len(data_is)),
    'oos_obs': int(len(data_oos)),
    'is_period': f"{data_is.index[0].date()} to {data_is.index[-1].date()}",
    'oos_period': f"{data_oos.index[0].date()} to {data_oos.index[-1].date()}",
    'seed': 42,
    'methodology': {
        'description': (
            'Threshold GJR-GARCH(1,1) with JOINT MLE over full time series. '
            'h_t is continuous across regime switches — h_{t-1} is always the '
            'variance from the previous step regardless of active regime. '
            'Fixes K980 estimation-evaluation mismatch where fit_gjr() was run '
            'on non-contiguous subsets but h_t was evaluated on continuous sequence.'
        ),
        'k980_fix': 'Joint MLE on full time series (vs K980 subset-wise MLE)',
        'threshold_variable': 'VIX_{t-1} (shifted: vix_lag = vix.shift(1) applied first)',
        'threshold_grid': thresholds,
        'best_threshold': int(best_c),
        'regime_constraint': 'Each regime >= 15% of IS observations',
        'multistart': 20,
        'optimizer': 'scipy.optimize.minimize L-BFGS-B',
        'likelihood': 'Gaussian log-likelihood summed over full IS time series',
        'models': ['GJR baseline (20 multistart)', 'TGJR joint MLE (20 multistart)'],
    },
    'parameters': {
        'gjr_baseline': gjr_fit,
        'tgjr_joint_mle': {
            'best_threshold': int(best_c),
            'low_regime': {
                'omega': best_tgjr_fit['omega_low'],
                'alpha': best_tgjr_fit['alpha_low'],
                'gamma': best_tgjr_fit['gamma_low'],
                'beta': best_tgjr_fit['beta_low'],
                'persistence': best_tgjr_fit['persistence_low'],
            },
            'high_regime': {
                'omega': best_tgjr_fit['omega_high'],
                'alpha': best_tgjr_fit['alpha_high'],
                'gamma': best_tgjr_fit['gamma_high'],
                'beta': best_tgjr_fit['beta_high'],
                'persistence': best_tgjr_fit['persistence_high'],
            },
            'loglik': best_tgjr_fit['loglik'],
            'converged': best_tgjr_fit['converged'],
            'loglik_distribution': best_tgjr_fit['loglik_distribution'],
        }
    },
    'threshold_grid_results': threshold_summary,
    'oos_evaluation': oos_eval,
    'regime_conditional_evaluation': regime_eval,
    'dm_test': {
        'comparison': 'GJR vs TGJR',
        'loss_function': 'QLIKE',
        'dm_stat': float(dm_stat),
        'p_value': float(dm_pval),
        'max_lag': int(max_lag_used),
        'hac': 'Newey-West Bartlett kernel',
        'h': 1,
        'significant_at_5pct': bool(dm_pval < 0.05),
        'winner': 'GJR' if oos_eval['GJR']['QLIKE'] <= oos_eval['TGJR']['QLIKE'] else 'TGJR'
    },
    'var_backtesting': var_results,
    'k980_comparison': {
        'k980_gjr_qlike': k980_gjr_qlike,
        'k980v2_gjr_qlike': float(oos_eval['GJR']['QLIKE']),
        'pct_diff_gjr': float(pct_diff_gjr),
        'k980v2_tgjr_qlike': float(oos_eval['TGJR']['QLIKE']),
        'pct_diff_tgjr_vs_gjr': float(pct_diff_tgjr),
    },
    'stationarity_check': {
        'tgjr_low_persistence': float(pers_low),
        'tgjr_high_persistence': float(pers_high),
        'low_stationary': bool(pers_low < 0.999),
        'high_stationary': bool(pers_high < 0.999),
    },
    'oos_regime_obs': {
        'low_vix_obs': int(low_oos_mask.sum()),
        'high_vix_obs': int(high_oos_mask.sum()),
        'pct_low': float(low_oos_mask.mean()),
        'pct_high': float(high_oos_mask.mean()),
    },
    'references': [
        'Glosten, Jagannathan & Runkle (1993, JoF): On the relation between expected value and volatility of nominal excess return on stocks',
        'Zakoian (1994): Threshold heteroskedastic models',
        'Chen, Liu & Gerlach (2011, Comp. Stats): Bayesian subset selection for threshold ARMA',
        'Patton (2011, J Econometrics): Volatility forecast comparison using imperfect proxies',
        'Diebold & Mariano (1995, JBES): Comparing predictive accuracy',
        'Hansen & Lunde (2005, J Econometrics): Forecast comparison of volatility models',
    ],
    'conclusions': {
        'verdict': verdict,
        'key_finding': key_finding,
        'methodology_fix': (
            'K980 FAIL was due to estimating two separate GJR models on non-contiguous '
            'subsets but evaluating with a continuous h_t recursion (estimation-evaluation '
            'mismatch). K980v2 uses joint MLE where h_t is continuous across regime switches.'
        ),
        'null_result_integrity': (
            'NULL result from K980 is directionally conserved. Joint MLE TGJR still '
            f'{direction_word} vs GJR by {abs(pct_diff_tgjr):.2f}% (DM p={dm_pval:.4f}).'
        ),
    }
}

result_path = BASE_DIR / 'k980v2_results.json'
with open(result_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Saved: {result_path}")
print(f"\n{'='*70}")
print(f"K980v2 COMPLETE")
print(f"{'='*70}")
print(f"  GJR  OOS QLIKE: {oos_eval['GJR']['QLIKE']:.6f}")
print(f"  TGJR OOS QLIKE: {oos_eval['TGJR']['QLIKE']:.6f}")
print(f"  Diff (TGJR-GJR): {pct_diff_tgjr:+.2f}%")
print(f"  DM p-value: {dm_pval:.4f}")
print(f"  Verdict: {verdict}")
print(f"  KEY FINDING: {key_finding}")
