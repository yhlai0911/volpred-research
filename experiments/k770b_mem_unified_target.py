#!/usr/bin/env python3
"""
K770b: MEM with Unified Forecast Target — Fix the QLIKE Mismatch
=================================================================
[提出: 用戶, 執行: Claude]

K770 was OVERTURNED by Codex because QLIKE was applied to |r| for MEM but
sqrt(σ²) for GARCH — different forecast objects. This experiment fixes the
mismatch by making ALL models predict the SAME target.

Two approaches:
  Approach A: All predict E[|r|] (absolute return)
    - MEM/AMEM/HAR-ABS: already predict E[|r|] → no change
    - GJR-GARCH: take sqrt(σ²) × sqrt(2/π) to convert σ to E[|r|]
    - EWMA: same conversion
    - QLIKE applied to |r| for ALL models

  Approach B: All predict σ² (variance)
    - GJR-GARCH/EWMA: already predict σ² → no change
    - MEM/AMEM: predict E[|r|], then square × (π/2) to get E[σ²]
    - HAR-ABS: same conversion
    - QLIKE applied to r² for ALL models

Both approaches should give consistent rankings if the Normal assumption
holds. Discrepancies reveal non-normality effects.

References:
  - Engle, R.F. & Gallo, G.M. (2006) J.Econometrics 131, 3-27
  - Brownlees, Cipollini & Gallo (2012) Handbook of Volatility Models
  - Corsi (2009) J.Financial Econometrics (HAR-ABS benchmark)
  - Patton (2011) "Volatility forecast comparison using imperfect
    volatility proxies" J.Econometrics 160, 246-256
    (QLIKE is robust to proxy noise only when applied to same-scale objects)
  - K770: OVERTURNED — QLIKE mismatch between |r| and σ models

Data: SPY, GLD, 0050.TW from yfinance, 2007-2026
Metrics: QLIKE (primary), MSE, MAE, Diebold-Mariano test, Harvey t>3.0
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import norm
from datetime import datetime, timezone
from numba import njit
import warnings
import os
import sys
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = 'experiments/k770b_mem_unified_target_results.json'

# Conversion constants under Normal assumption
# If r ~ N(0, σ²), then E[|r|] = σ × sqrt(2/π)
SQRT_2_OVER_PI = np.sqrt(2.0 / np.pi)  # ≈ 0.7979
PI_OVER_2 = np.pi / 2.0                # ≈ 1.5708

# ============================================================
# Part A: Model Implementations (same as K770, verified)
# ============================================================

@njit(cache=True)
def mem_filter(x, omega, alpha, beta):
    """
    MEM(1,1) conditional mean recursion:
        μ_t = ω + α × x_{t-1} + β × μ_{t-1}
    x: array of non-negative observations (|r_t|)
    Returns: μ (conditional mean array)
    """
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 0.01
    for t in range(1, T):
        mu[t] = omega + alpha * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-10:
            mu[t] = 1e-10
    return mu


@njit(cache=True)
def amem_filter(x, r, omega, alpha, beta, gamma):
    """
    AMEM(1,1) with leverage:
        μ_t = ω + (α + γ × I_{r<0}) × x_{t-1} + β × μ_{t-1}
    x: |r_t|, r: raw returns
    """
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 0.01
    for t in range(1, T):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        mu[t] = omega + (alpha + gamma * indicator) * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-10:
            mu[t] = 1e-10
    return mu


@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1) variance filter. Returns σ² array."""
    T = len(r)
    sigma2 = np.zeros(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i]**2
    var_r /= T
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        sigma2[t] = omega + (alpha + gamma * ind) * r[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return sigma2


def mem_negloglik(params, x, model='mem', r=None):
    """
    Gamma MLE for MEM/AMEM.
    ε_t = x_t / μ_t ~ Gamma(k, 1/k), E[ε]=1, Var[ε]=1/k
    """
    if model == 'mem':
        omega, alpha, beta, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or k <= 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        mu = mem_filter(x, omega, alpha, beta)
    elif model == 'amem':
        omega, alpha, beta, gamma, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or k <= 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        mu = amem_filter(x, r, omega, alpha, beta, gamma)
    else:
        return 1e10

    x_trim = x[1:]
    mu_trim = mu[1:]
    valid = (mu_trim > 1e-10) & (x_trim > 0)
    if valid.sum() < 10:
        return 1e10
    x_v = x_trim[valid]
    mu_v = mu_trim[valid]
    ll = (k * np.log(k / mu_v) + (k - 1) * np.log(x_v)
          - k * x_v / mu_v - gammaln(k))
    total_ll = np.sum(ll)
    if not np.isfinite(total_ll):
        return 1e10
    return -total_ll


def fit_mem(x, model='mem', r=None, max_attempts=3):
    """Fit MEM or AMEM via Gamma MLE with multiple restarts."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    if r is not None:
        r = np.ascontiguousarray(r, dtype=np.float64)
    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 0.01
    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)
        if model == 'mem':
            omega0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
            alpha0 = 0.1 + 0.05 * np.random.randn()
            beta0 = 0.85 + 0.05 * np.random.randn()
            k0 = 2.0 + np.random.rand()
            alpha0 = max(0.01, min(alpha0, 0.5))
            beta0 = max(0.3, min(beta0, 0.95))
            if alpha0 + beta0 >= 0.99:
                beta0 = 0.98 - alpha0
            p0 = [max(1e-6, omega0), alpha0, beta0, max(0.5, k0)]
            bounds = [(1e-8, None), (0, 0.9), (0, 0.99), (0.1, 100)]
            result = minimize(mem_negloglik, p0, args=(x, 'mem', None),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 5000, 'ftol': 1e-10})
        else:
            omega0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
            alpha0 = 0.05 + 0.03 * np.random.randn()
            beta0 = 0.85 + 0.05 * np.random.randn()
            gamma0 = 0.1 + 0.05 * np.random.randn()
            k0 = 2.0 + np.random.rand()
            alpha0 = max(0.01, min(alpha0, 0.4))
            beta0 = max(0.3, min(beta0, 0.95))
            gamma0 = max(0.01, min(gamma0, 0.4))
            if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
                beta0 = 0.97 - alpha0 - 0.5 * gamma0
            p0 = [max(1e-6, omega0), alpha0, beta0, max(0.01, gamma0), max(0.5, k0)]
            bounds = [(1e-8, None), (0, 0.9), (0, 0.99), (0, 0.9), (0.1, 100)]
            result = minimize(mem_negloglik, p0, args=(x, 'amem', r),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 5000, 'ftol': 1e-10})
        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    if best_result is None:
        return None
    res = best_result
    if model == 'mem':
        params = {
            'omega': res.x[0], 'alpha': res.x[1],
            'beta': res.x[2], 'k': res.x[3],
            'persistence': res.x[1] + res.x[2]
        }
    else:
        params = {
            'omega': res.x[0], 'alpha': res.x[1],
            'beta': res.x[2], 'gamma': res.x[3], 'k': res.x[4],
            'persistence': res.x[1] + res.x[2] + 0.5 * res.x[3]
        }
    return {
        'params': params,
        'converged': res.success,
        'nll': res.fun,
        'n_obs': len(x)
    }


# ============================================================
# Benchmark Models
# ============================================================

def fit_har_abs(abs_ret):
    """
    HAR-ABS: |r_t| = β0 + β1 × |r_{t-1}| + β5 × MA5_{t-1}(|r|) + β22 × MA22_{t-1}(|r|)
    All features are lagged to avoid lookahead.
    """
    x = abs_ret.copy()
    n = len(x)
    if n < 30:
        return None
    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values
    valid_start = 22
    if n <= valid_start + 30:
        return None
    idx = np.arange(valid_start, n)
    Y = x[idx]
    X = np.column_stack([
        np.ones(len(idx)),
        x[idx - 1],
        ma5[idx - 1],
        ma22[idx - 1]
    ])
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None
    Y = Y[valid_rows]
    X = X[valid_rows]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


def har_abs_forecast(abs_ret, beta):
    """One-step-ahead HAR-ABS forecast (predicts E[|r|])."""
    n = len(abs_ret)
    if n < 22:
        return None
    lag1 = abs_ret[-1]
    ma5 = np.mean(abs_ret[-5:])
    ma22 = np.mean(abs_ret[-22:])
    pred = beta[0] + beta[1] * lag1 + beta[2] * ma5 + beta[3] * ma22
    return max(pred, 1e-10)


def fit_gjr_garch(returns):
    """
    GJR-GARCH(1,1) via quasi-MLE (Gaussian).
    Returns params dict. Forecast object: σ² (variance).
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 50:
        return None

    def gjr_negll(params, r):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        sigma2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:]**2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rv = np.var(r)
    best = None
    best_nll = 1e10
    for seed in range(3):
        np.random.seed(seed + 100)
        a0 = 0.05 + 0.03 * np.random.randn()
        b0 = 0.88 + 0.04 * np.random.randn()
        g0 = 0.08 + 0.04 * np.random.randn()
        a0 = max(0.01, min(a0, 0.3))
        b0 = max(0.5, min(b0, 0.98))
        g0 = max(0.01, min(g0, 0.3))
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = rv * (1 - a0 - b0 - 0.5 * g0)
        res = minimize(gjr_negll, [max(1e-8, o0), a0, b0, g0], args=(r,),
                      method='L-BFGS-B',
                      bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                      options={'maxiter': 2000})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res
    if best is None:
        return None
    return {
        'omega': best.x[0], 'alpha': best.x[1],
        'beta': best.x[2], 'gamma': best.x[3],
        'persistence': best.x[1] + best.x[2] + 0.5 * best.x[3]
    }


def gjr_forecast_sigma2(returns, params):
    """
    One-step-ahead GJR-GARCH forecast.
    Returns: σ²_{t+1} (variance, NOT standard deviation).
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    omega = params['omega']
    alpha = params['alpha']
    beta_p = params['beta']
    gamma = params['gamma']
    sigma2 = gjr_filter(r, omega, alpha, beta_p, gamma)
    ind = 1.0 if r[-1] < 0 else 0.0
    next_sigma2 = omega + (alpha + gamma * ind) * r[-1]**2 + beta_p * sigma2[-1]
    return max(next_sigma2, 1e-12)


def ewma_forecast_sigma2(returns, lam=0.94):
    """
    EWMA variance forecast.
    Returns: σ²_{t+1} (variance, NOT standard deviation).
    """
    r = returns
    var = r[0]**2
    for i in range(1, len(r)):
        var = lam * var + (1 - lam) * r[i]**2
    return max(var, 1e-12)


# ============================================================
# Evaluation Metrics
# ============================================================

def qlike(actual, predicted):
    """
    QLIKE loss: actual/predicted - log(actual/predicted) - 1.
    CRITICAL: actual and predicted must be on the SAME scale.
    """
    a = np.array(actual)
    p = np.array(predicted)
    valid = (a > 0) & (p > 0)
    a, p = a[valid], p[valid]
    if len(a) == 0:
        return np.nan
    return np.mean(a / p - np.log(a / p) - 1)


def mse(actual, predicted):
    return np.mean((np.array(actual) - np.array(predicted))**2)


def mae(actual, predicted):
    return np.mean(np.abs(np.array(actual) - np.array(predicted)))


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test with Newey-West HAC variance.
    Negative stat means model 1 is better.
    """
    d = np.array(loss1) - np.array(loss2)
    n = len(d)
    d_mean = np.mean(d)
    max_lag = int(np.ceil(h**(1/3) * n**(1/3)))
    max_lag = max(1, min(max_lag, n // 4))
    gamma0 = np.mean((d - d_mean)**2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l
    if var_d <= 0:
        return 0.0, 1.0
    stat = d_mean / np.sqrt(var_d / n)
    p_val = 2 * (1 - norm.cdf(abs(stat)))
    return stat, p_val


def pointwise_qlike(actual, predicted):
    """Pointwise QLIKE losses for DM test. Both must be same scale."""
    a = np.array(actual)
    p = np.array(predicted)
    ratio = a / p
    return ratio - np.log(ratio) - 1


# ============================================================
# Expanding Window Forecast (Dual-Target)
# ============================================================

def expanding_window_forecast(returns, abs_ret, min_window=500, refit_freq=63):
    """
    Expanding window 1-day-ahead forecasts for all models.

    Returns RAW forecasts in each model's native scale:
      - MEM/AMEM/HAR-ABS → E[|r_{t+1}|]
      - GJR/EWMA → σ²_{t+1}

    Conversion to unified targets done AFTER this function.
    """
    T = len(returns)
    n_oos = T - min_window

    if n_oos < 100:
        print(f"  WARNING: Only {n_oos} OOS obs (need >=100)")
        return None

    print(f"  Expanding window: T={T}, min_window={min_window}, OOS={n_oos}, refit_freq={refit_freq}")

    # Storage: raw forecasts in native scale
    forecasts_abs = {  # Models that natively predict E[|r|]
        'mem': np.full(n_oos, np.nan),
        'amem': np.full(n_oos, np.nan),
        'har_abs': np.full(n_oos, np.nan),
    }
    forecasts_var = {  # Models that natively predict σ²
        'gjr': np.full(n_oos, np.nan),
        'ewma': np.full(n_oos, np.nan),
    }

    actuals_abs = np.full(n_oos, np.nan)   # |r_{t+1}|
    actuals_var = np.full(n_oos, np.nan)   # r_{t+1}²

    # Cached model params
    mem_params = None
    amem_params = None
    har_beta = None
    gjr_params = None
    last_refit = -refit_freq

    for i in range(n_oos):
        t = min_window + i
        if t >= T - 1:
            break

        # Actual targets
        actuals_abs[i] = abs_ret[t + 1]        # |r_{t+1}|
        actuals_var[i] = returns[t + 1]**2      # r_{t+1}²

        # History up to t
        x_hist = np.ascontiguousarray(abs_ret[:t + 1], dtype=np.float64)
        r_hist = np.ascontiguousarray(returns[:t + 1], dtype=np.float64)

        # Refit periodically
        if i - last_refit >= refit_freq or mem_params is None:
            last_refit = i

            mem_fit = fit_mem(x_hist, model='mem')
            if mem_fit and mem_fit['converged']:
                mem_params = mem_fit['params']

            amem_fit = fit_mem(x_hist, model='amem', r=r_hist)
            if amem_fit and amem_fit['converged']:
                amem_params = amem_fit['params']

            har_beta = fit_har_abs(x_hist)
            gjr_params = fit_gjr_garch(r_hist)

        # --- Generate forecasts (in native scale) ---

        # MEM → E[|r_{t+1}|]
        if mem_params is not None:
            mu = mem_filter(x_hist, mem_params['omega'],
                          mem_params['alpha'], mem_params['beta'])
            fc = mem_params['omega'] + mem_params['alpha'] * x_hist[-1] + mem_params['beta'] * mu[-1]
            forecasts_abs['mem'][i] = max(fc, 1e-10)

        # AMEM → E[|r_{t+1}|]
        if amem_params is not None:
            mu = amem_filter(x_hist, r_hist, amem_params['omega'],
                           amem_params['alpha'], amem_params['beta'],
                           amem_params['gamma'])
            ind = 1.0 if r_hist[-1] < 0 else 0.0
            fc = (amem_params['omega']
                  + (amem_params['alpha'] + amem_params['gamma'] * ind) * x_hist[-1]
                  + amem_params['beta'] * mu[-1])
            forecasts_abs['amem'][i] = max(fc, 1e-10)

        # HAR-ABS → E[|r_{t+1}|]
        if har_beta is not None:
            fc = har_abs_forecast(x_hist, har_beta)
            if fc is not None:
                forecasts_abs['har_abs'][i] = fc

        # GJR-GARCH → σ²_{t+1}
        if gjr_params is not None:
            forecasts_var['gjr'][i] = gjr_forecast_sigma2(r_hist, gjr_params)

        # EWMA → σ²_{t+1}
        forecasts_var['ewma'][i] = ewma_forecast_sigma2(r_hist)

        if (i + 1) % 500 == 0:
            print(f"    OOS step {i+1}/{n_oos}")

    # Determine valid mask: all models have forecasts
    valid = ~np.isnan(actuals_abs)
    for k in forecasts_abs:
        valid &= ~np.isnan(forecasts_abs[k])
    for k in forecasts_var:
        valid &= ~np.isnan(forecasts_var[k])

    # Also need positive actuals for QLIKE
    valid &= (actuals_abs > 0)

    n_valid = int(valid.sum())
    print(f"  Valid OOS observations (all models): {n_valid}")

    if n_valid < 50:
        print("  ERROR: Too few valid observations")
        return None

    return {
        'actuals_abs': actuals_abs[valid],     # |r_{t+1}|
        'actuals_var': actuals_var[valid],      # r_{t+1}²
        'forecasts_abs': {k: v[valid] for k, v in forecasts_abs.items()},
        'forecasts_var': {k: v[valid] for k, v in forecasts_var.items()},
        'n_oos': n_valid
    }


# ============================================================
# Unified Target Evaluation
# ============================================================

def evaluate_approach_a(result):
    """
    Approach A: All predict E[|r|].
    - MEM/AMEM/HAR-ABS: use raw forecasts (already E[|r|])
    - GJR/EWMA: convert σ² → E[|r|] = sqrt(σ²) × sqrt(2/π)
    - Actual: |r_{t+1}|
    """
    actuals = result['actuals_abs']  # |r_{t+1}|
    models = ['mem', 'amem', 'har_abs', 'gjr', 'ewma']

    # Build unified forecasts
    unified = {}
    for m in ['mem', 'amem', 'har_abs']:
        unified[m] = result['forecasts_abs'][m]  # already E[|r|]

    for m in ['gjr', 'ewma']:
        sigma2 = result['forecasts_var'][m]
        # σ² → E[|r|] = sqrt(σ²) × sqrt(2/π) under Normal
        unified[m] = np.sqrt(sigma2) * SQRT_2_OVER_PI

    # Metrics
    metrics = {}
    qlike_losses = {}
    for m in models:
        preds = unified[m]
        metrics[m] = {
            'qlike': float(qlike(actuals, preds)),
            'mse': float(mse(actuals, preds)),
            'mae': float(mae(actuals, preds)),
        }
        # Pointwise losses for DM
        qlike_losses[m] = pointwise_qlike(actuals, preds)

    # DM tests
    dm_results = {}
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            stat, pval = dm_test(qlike_losses[m1], qlike_losses[m2])
            dm_results[f'{m1}_vs_{m2}'] = {
                'dm_stat': float(stat),
                'p_value': float(pval),
                'harvey_pass': bool(abs(stat) > 3.0),
                'better': m1 if stat < 0 else m2
            }

    ranking = sorted(models, key=lambda m: metrics[m]['qlike'])
    return metrics, dm_results, ranking


def evaluate_approach_b(result):
    """
    Approach B: All predict σ² (variance).
    - GJR/EWMA: use raw forecasts (already σ²)
    - MEM/AMEM/HAR-ABS: convert E[|r|] → σ² = (E[|r|])² × (π/2)
    - Actual: r_{t+1}² (squared return as variance proxy)
    """
    actuals = result['actuals_var']  # r_{t+1}²
    models = ['mem', 'amem', 'har_abs', 'gjr', 'ewma']

    # Build unified forecasts
    unified = {}
    for m in ['gjr', 'ewma']:
        unified[m] = result['forecasts_var'][m]  # already σ²

    for m in ['mem', 'amem', 'har_abs']:
        e_abs_r = result['forecasts_abs'][m]
        # E[|r|] → E[σ²] = (E[|r|])² × (π/2) under Normal
        unified[m] = e_abs_r**2 * PI_OVER_2

    # Metrics
    metrics = {}
    qlike_losses = {}
    for m in models:
        preds = unified[m]
        metrics[m] = {
            'qlike': float(qlike(actuals, preds)),
            'mse': float(mse(actuals, preds)),
            'mae': float(mae(actuals, preds)),
        }
        qlike_losses[m] = pointwise_qlike(actuals, preds)

    # DM tests
    dm_results = {}
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            stat, pval = dm_test(qlike_losses[m1], qlike_losses[m2])
            dm_results[f'{m1}_vs_{m2}'] = {
                'dm_stat': float(stat),
                'p_value': float(pval),
                'harvey_pass': bool(abs(stat) > 3.0),
                'better': m1 if stat < 0 else m2
            }

    ranking = sorted(models, key=lambda m: metrics[m]['qlike'])
    return metrics, dm_results, ranking


# ============================================================
# Full-sample estimation (for reporting)
# ============================================================

def full_sample_estimation(abs_ret, returns, asset_name):
    """Full-sample MEM and AMEM estimation for parameter reporting."""
    print(f"\n{'='*60}")
    print(f"Full-sample estimation: {asset_name}")
    print(f"{'='*60}")

    print(f"  N = {len(abs_ret)}")
    print(f"  Mean |r| = {np.mean(abs_ret):.6f}")
    print(f"  Std  |r| = {np.std(abs_ret):.6f}")
    print(f"  Skew |r| = {pd.Series(abs_ret).skew():.3f}")
    print(f"  Kurt |r| = {pd.Series(abs_ret).kurtosis():.3f}")

    mem_fit = fit_mem(abs_ret, model='mem')
    if mem_fit:
        p = mem_fit['params']
        print(f"\n  MEM(1,1): omega={p['omega']:.6f}, alpha={p['alpha']:.4f}, "
              f"beta={p['beta']:.4f}, k={p['k']:.2f}, "
              f"persistence={p['persistence']:.4f}")
        print(f"  Converged: {mem_fit['converged']}, NLL: {mem_fit['nll']:.2f}")

    amem_fit = fit_mem(abs_ret, model='amem', r=returns)
    if amem_fit:
        p = amem_fit['params']
        print(f"\n  AMEM(1,1): omega={p['omega']:.6f}, alpha={p['alpha']:.4f}, "
              f"beta={p['beta']:.4f}, gamma={p['gamma']:.4f}, k={p['k']:.2f}, "
              f"persistence={p['persistence']:.4f}")
        print(f"  Converged: {amem_fit['converged']}, NLL: {amem_fit['nll']:.2f}")

    return mem_fit, amem_fit


# ============================================================
# Main
# ============================================================

def run_asset(ticker, start='2007-01-01', min_window=500, refit_freq=63):
    """Run full experiment for one asset with BOTH approaches."""
    print(f"\n{'#'*70}")
    print(f"# Asset: {ticker}")
    print(f"{'#'*70}")

    print(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=start, end='2026-04-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])

    if len(df) < min_window + 200:
        print(f"  ERROR: Not enough data ({len(df)} rows)")
        return None

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")

    returns = df['Close'].pct_change().dropna().values
    abs_ret = np.abs(returns)

    # Full-sample estimation
    mem_full, amem_full = full_sample_estimation(abs_ret, returns, ticker)

    # Expanding window
    print(f"\n  Starting expanding window forecast...")
    result = expanding_window_forecast(returns, abs_ret,
                                       min_window=min_window,
                                       refit_freq=refit_freq)
    if result is None:
        print(f"  ERROR: Forecasting failed for {ticker}")
        return None

    # ---- Approach A: All predict E[|r|] ----
    print(f"\n  === Approach A: All predict E[|r|] ===")
    metrics_a, dm_a, ranking_a = evaluate_approach_a(result)

    print(f"  {'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MAE':>10}")
    print(f"  {'-'*46}")
    for m in ranking_a:
        met = metrics_a[m]
        print(f"  {m:<12} {met['qlike']:>10.4f} {met['mse']:>12.8f} {met['mae']:>10.6f}")

    print(f"\n  DM Tests (QLIKE, Approach A):")
    print(f"  {'Pair':<25} {'DM stat':>10} {'p-value':>10} {'Harvey':>8} {'Better':>10}")
    print(f"  {'-'*65}")
    for pair, res in sorted(dm_a.items()):
        harvey = '***' if res['harvey_pass'] else ''
        print(f"  {pair:<25} {res['dm_stat']:>10.3f} {res['p_value']:>10.4f} "
              f"{harvey:>8} {res['better']:>10}")

    # ---- Approach B: All predict σ² ----
    print(f"\n  === Approach B: All predict sigma2 ===")
    metrics_b, dm_b, ranking_b = evaluate_approach_b(result)

    print(f"  {'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MAE':>10}")
    print(f"  {'-'*46}")
    for m in ranking_b:
        met = metrics_b[m]
        print(f"  {m:<12} {met['qlike']:>10.4f} {met['mse']:>12.8f} {met['mae']:>10.6f}")

    print(f"\n  DM Tests (QLIKE, Approach B):")
    print(f"  {'Pair':<25} {'DM stat':>10} {'p-value':>10} {'Harvey':>8} {'Better':>10}")
    print(f"  {'-'*65}")
    for pair, res in sorted(dm_b.items()):
        harvey = '***' if res['harvey_pass'] else ''
        print(f"  {pair:<25} {res['dm_stat']:>10.3f} {res['p_value']:>10.4f} "
              f"{harvey:>8} {res['better']:>10}")

    # ---- Consistency check ----
    print(f"\n  === Ranking Consistency ===")
    print(f"  Approach A ranking: {' > '.join(ranking_a)}")
    print(f"  Approach B ranking: {' > '.join(ranking_b)}")
    consistent = (ranking_a == ranking_b)
    print(f"  Rankings identical: {consistent}")
    if not consistent:
        # Check top-3 consistency
        top3_a = set(ranking_a[:3])
        top3_b = set(ranking_b[:3])
        print(f"  Top-3 overlap: {len(top3_a & top3_b)}/3")

    return {
        'ticker': ticker,
        'n_total': len(df),
        'n_oos': result['n_oos'],
        'date_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'full_sample': {
            'mem': mem_full['params'] if mem_full else None,
            'amem': amem_full['params'] if amem_full else None,
            'mem_converged': mem_full['converged'] if mem_full else False,
            'amem_converged': amem_full['converged'] if amem_full else False,
        },
        'approach_a': {
            'description': 'All predict E[|r|]; GJR/EWMA converted via sqrt(sigma2)*sqrt(2/pi)',
            'target': '|r_{t+1}|',
            'metrics': metrics_a,
            'dm_tests': dm_a,
            'ranking': ranking_a,
        },
        'approach_b': {
            'description': 'All predict sigma2; MEM/AMEM/HAR converted via E[|r|]^2 * (pi/2)',
            'target': 'r_{t+1}^2',
            'metrics': metrics_b,
            'dm_tests': dm_b,
            'ranking': ranking_b,
        },
        'rankings_consistent': consistent,
    }


def main():
    print("="*70)
    print("K770b: MEM with Unified Forecast Target — Fix QLIKE Mismatch")
    print("="*70)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    print(f"\nConversion constants:")
    print(f"  sqrt(2/pi) = {SQRT_2_OVER_PI:.6f}  (sigma -> E[|r|])")
    print(f"  pi/2       = {PI_OVER_2:.6f}  (E[|r|]^2 -> sigma^2)")
    t_start = time.time()

    # Warmup numba JIT
    print("\n  Warming up numba JIT...")
    _x = np.random.rand(100).astype(np.float64)
    _r = np.random.randn(100).astype(np.float64)
    _ = mem_filter(_x, 0.01, 0.1, 0.8)
    _ = amem_filter(_x, _r, 0.01, 0.1, 0.8, 0.05)
    _ = gjr_filter(_r, 0.001, 0.05, 0.9, 0.05)
    print("  JIT warmup complete.")

    assets = ['SPY', 'GLD', '0050.TW']
    all_results = {}

    for ticker in assets:
        try:
            result = run_asset(ticker, start='2007-01-01',
                             min_window=500, refit_freq=63)
            if result:
                all_results[ticker] = result
        except Exception as e:
            print(f"  ERROR for {ticker}: {e}")
            import traceback
            traceback.print_exc()

    # ============================================================
    # Cross-Asset Summary
    # ============================================================
    print("\n" + "="*70)
    print("CROSS-ASSET SUMMARY")
    print("="*70)

    # For each approach, compute average ranks
    summary_cross = {}
    for approach in ['approach_a', 'approach_b']:
        model_ranks = {}
        for ticker, result in all_results.items():
            ranking = result[approach]['ranking']
            for rank, m in enumerate(ranking, 1):
                if m not in model_ranks:
                    model_ranks[m] = []
                model_ranks[m].append(rank)

        avg_ranks = {m: float(np.mean(ranks)) for m, ranks in model_ranks.items()}
        summary_cross[approach] = {
            'avg_ranks': avg_ranks,
            'best_model': min(avg_ranks, key=avg_ranks.get),
            'model_ranks': {m: ranks for m, ranks in model_ranks.items()}
        }

        label = 'E[|r|]' if approach == 'approach_a' else 'sigma2'
        print(f"\n  {approach} (target: {label}):")
        for m in sorted(avg_ranks, key=avg_ranks.get):
            r_list = model_ranks[m]
            print(f"    {m:<12}: avg rank = {avg_ranks[m]:.2f} (ranks: {r_list})")

    # Check consistency
    best_a = summary_cross['approach_a']['best_model']
    best_b = summary_cross['approach_b']['best_model']
    print(f"\n  Best model (Approach A): {best_a}")
    print(f"  Best model (Approach B): {best_b}")
    print(f"  Cross-approach consistent: {best_a == best_b}")

    # Count Harvey-significant DM tests
    harvey_summary = {'approach_a': [], 'approach_b': []}
    for ticker, result in all_results.items():
        for approach in ['approach_a', 'approach_b']:
            for pair, dm in result[approach]['dm_tests'].items():
                if dm['harvey_pass']:
                    harvey_summary[approach].append(
                        f"{ticker}: {pair} DM={dm['dm_stat']:.2f} -> {dm['better']}"
                    )

    print(f"\n  Harvey t>3.0 passes:")
    for approach in ['approach_a', 'approach_b']:
        print(f"    {approach}: {len(harvey_summary[approach])} significant pairs")
        for h in harvey_summary[approach][:10]:
            print(f"      {h}")

    # K770 comparison: did the fix change rankings?
    print(f"\n  === K770 vs K770b Comparison ===")
    print(f"  K770 (flawed): applied QLIKE to |r| for MEM but sqrt(sigma2) for GARCH")
    print(f"  K770b (fixed): unified target — both approaches above")
    print(f"  Key question: does AMEM still dominate after fixing the mismatch?")

    # Build conclusions
    conclusions = []

    # 1. Does AMEM still beat HAR-ABS?
    for approach in ['approach_a', 'approach_b']:
        amem_beats_har = 0
        for ticker, result in all_results.items():
            r_list = result[approach]['ranking']
            if r_list.index('amem') < r_list.index('har_abs'):
                amem_beats_har += 1
        conclusions.append(
            f"{approach}: AMEM beats HAR-ABS in {amem_beats_har}/{len(all_results)} assets"
        )

    # 2. Does MEM beat HAR-ABS?
    for approach in ['approach_a', 'approach_b']:
        mem_beats_har = 0
        for ticker, result in all_results.items():
            r_list = result[approach]['ranking']
            if r_list.index('mem') < r_list.index('har_abs'):
                mem_beats_har += 1
        conclusions.append(
            f"{approach}: MEM beats HAR-ABS in {mem_beats_har}/{len(all_results)} assets"
        )

    # 3. Leverage effect
    for approach in ['approach_a', 'approach_b']:
        amem_beats_mem = 0
        for ticker, result in all_results.items():
            r_list = result[approach]['ranking']
            if r_list.index('amem') < r_list.index('mem'):
                amem_beats_mem += 1
        conclusions.append(
            f"{approach}: AMEM beats MEM (leverage helps) in {amem_beats_mem}/{len(all_results)} assets"
        )

    # 4. Ranking consistency
    all_consistent = all(
        result['rankings_consistent'] for result in all_results.values()
    )
    conclusions.append(
        f"Rankings consistent across approaches: {all_consistent}"
    )
    if not all_consistent:
        for ticker, result in all_results.items():
            if not result['rankings_consistent']:
                conclusions.append(
                    f"  {ticker}: A={result['approach_a']['ranking']}, "
                    f"B={result['approach_b']['ranking']}"
                )

    # 5. Overall best
    conclusions.append(
        f"Best model (Approach A cross-asset): {best_a} "
        f"(avg rank {summary_cross['approach_a']['avg_ranks'][best_a]:.2f})"
    )
    conclusions.append(
        f"Best model (Approach B cross-asset): {best_b} "
        f"(avg rank {summary_cross['approach_b']['avg_ranks'][best_b]:.2f})"
    )

    print(f"\nConclusions:")
    for c in conclusions:
        print(f"  - {c}")

    # ============================================================
    # Build final summary
    # ============================================================
    summary = {
        'experiment_id': 'k770b',
        'title': 'K770b: MEM Unified Forecast Target — Fix QLIKE Mismatch',
        'proposer': '用戶',
        'executor': 'Claude',
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY, GLD, 0050.TW)',
        'methodology': (
            'Expanding window, 1-day-ahead, Gamma MLE for MEM/AMEM, '
            'Gaussian QMLE for GJR-GARCH, OLS for HAR-ABS. '
            'Two unified evaluation approaches: (A) all predict E[|r|], '
            '(B) all predict sigma2. Conversions use Normal assumption: '
            'E[|r|] = sigma * sqrt(2/pi).'
        ),
        'bug_fix': (
            'K770 applied QLIKE to |r| for MEM/HAR but sqrt(sigma2) for GARCH/EWMA. '
            'sqrt(sigma2) != E[|r|] under non-Gaussian returns. '
            'K770b converts ALL models to the SAME target before QLIKE.'
        ),
        'conversion_constants': {
            'sqrt_2_over_pi': SQRT_2_OVER_PI,
            'pi_over_2': PI_OVER_2,
            'interpretation': (
                'Under r~N(0,sigma2): E[|r|] = sigma*sqrt(2/pi) ≈ 0.798*sigma. '
                'So sigma2 -> E[|r|]: multiply sqrt(sigma2) by 0.798. '
                'E[|r|] -> sigma2: square E[|r|] and multiply by pi/2 ≈ 1.571.'
            )
        },
        'references': [
            'Engle & Gallo (2006) J.Econometrics 131',
            'Brownlees, Cipollini & Gallo (2012) Handbook of Volatility Models',
            'Corsi (2009) J.Financial Econometrics (HAR)',
            'Patton (2011) J.Econometrics 160 — QLIKE robustness to proxy noise',
            'K770: OVERTURNED (QLIKE mismatch between |r| and sigma models)',
            'K530: HAR multi-scale champion'
        ],
        'results_by_asset': {},
        'cross_asset_summary': summary_cross,
        'harvey_significant_tests': harvey_summary,
        'conclusions': conclusions,
    }

    for ticker, result in all_results.items():
        summary['results_by_asset'][ticker] = {
            'n_oos': result['n_oos'],
            'date_range': result['date_range'],
            'full_sample_params': result['full_sample'],
            'approach_a': result['approach_a'],
            'approach_b': result['approach_b'],
            'rankings_consistent': result['rankings_consistent'],
        }

    # JSON serialization helper
    def convert_np(obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            if np.isnan(v) or np.isinf(v):
                return None
            return v
        if isinstance(obj, float):
            if np.isnan(obj) or np.isinf(obj):
                return None
            return obj
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: convert_np(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert_np(v) for v in obj]
        return obj

    summary = convert_np(summary)

    elapsed = time.time() - t_start
    summary['elapsed_seconds'] = round(elapsed, 1)
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    with open(RESULTS_PATH, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {RESULTS_PATH}")

    return summary


if __name__ == '__main__':
    results = main()
