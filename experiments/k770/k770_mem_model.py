#!/usr/bin/env python3
"""
K770: Multiplicative Error Model (MEM) for Volatility Forecasting
=================================================================
[提出: 用戶, 執行: Claude]

MEM (Engle & Gallo 2006) is a third modeling paradigm beyond GARCH and HAR.
It models non-negative series (|r_t|) directly as:
    x_t = μ_t × ε_t
where μ_t is conditional mean, ε_t > 0 is unit-mean innovation.

Parts:
  A) Basic MEM(1,1): μ_t = ω + α × x_{t-1} + β × μ_{t-1}
  B) AMEM(1,1): μ_t = ω + (α + γ × I_{r<0}) × x_{t-1} + β × μ_{t-1}
  C) Horse race: MEM vs AMEM vs HAR-ABS vs GJR-GARCH vs EWMA (expanding window)
  D) Multi-asset: SPY, GLD, 0050.TW

References:
  - Engle, R.F. & Gallo, G.M. (2006) "A multiple indicators model for
    volatility using intra-daily data" J.Econometrics 131, 3-27
  - Brownlees, C.T., Cipollini, F. & Gallo, G.M. (2012) "Multiplicative
    Error Models" in Handbook of Volatility Models and Their Applications
  - Corsi (2009) "A Simple Approximate Long-Memory Model of Realized
    Volatility" J.Financial Econometrics — HAR-ABS benchmark
  - K530: HAR-ABS champion (QLIKE=0.49, DM=-15.45 vs GJR)
  - K442: FIGARCH null (long memory doesn't improve OOS)

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

RESULTS_PATH = 'experiments/k770_mem_model_results.json'

# ============================================================
# Part A: MEM(1,1) Implementation
# ============================================================

@njit(cache=True)
def mem_filter(x, omega, alpha, beta):
    """
    MEM(1,1) conditional mean recursion:
        μ_t = ω + α × x_{t-1} + β × μ_{t-1}

    x: array of non-negative observations (|r_t|)
    Returns: μ (conditional mean array, same length)
    """
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 0.01

    for t in range(1, T):
        mu[t] = omega + alpha * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-10:
            mu[t] = 1e-10  # floor to avoid log(0)

    return mu


@njit(cache=True)
def amem_filter(x, r, omega, alpha, beta, gamma):
    """
    AMEM(1,1) conditional mean recursion with leverage:
        μ_t = ω + (α + γ × I_{r<0}) × x_{t-1} + β × μ_{t-1}

    x: |r_t|, r: raw returns (for sign indicator)
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
    """GJR-GARCH(1,1) variance filter."""
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

    Log-likelihood of x_t | μ_t under Gamma(k, 1/k):
        log f(x|μ,k) = (k-1) log(x) - k x/μ + k log(k/μ) - log(Γ(k))
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
        if alpha + beta + 0.5 * gamma >= 1.0:  # stationarity with asymmetry
            return 1e10
        mu = amem_filter(x, r, omega, alpha, beta, gamma)
    else:
        return 1e10

    # Gamma log-likelihood: x_t ~ Gamma(k, μ_t/k) with E=μ_t
    # rate = k/μ_t, shape = k
    # log f = k log(k/μ) + (k-1) log(x) - k x/μ - log Γ(k)
    # Skip first observation (initialization)
    x_trim = x[1:]
    mu_trim = mu[1:]

    # Guard against numerical issues
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
    """
    Fit MEM or AMEM via Gamma MLE with multiple restarts.
    Returns: dict with params and convergence info.
    """
    x = np.ascontiguousarray(x, dtype=np.float64)
    if r is not None:
        r = np.ascontiguousarray(r, dtype=np.float64)
    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 0.01

    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)

        if model == 'mem':
            # Initial: omega, alpha, beta, k
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
            # AMEM: omega, alpha, beta, gamma, k
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
# Part B: Benchmark Models
# ============================================================

def fit_har_abs(abs_ret, window_data=None):
    """
    HAR-ABS: |r_t| = β0 + β1 × |r_{t-1}| + β5 × MA5_{t-1}(|r|) + β22 × MA22_{t-1}(|r|)
    Returns coefficients from OLS. All features are lagged to avoid lookahead.
    """
    x = abs_ret.copy()
    n = len(x)
    if n < 30:
        return None

    # Build features
    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values

    # Need: Y = x[t], X uses x[t-1], ma5[t-1], ma22[t-1]
    # ma22 first valid at index 21, so ma22[t-1] first valid when t-1=21, i.e. t=22
    # So valid range: t from 22 to n-1

    valid_start = 22  # first t where all lag features exist
    if n <= valid_start + 30:
        return None

    idx = np.arange(valid_start, n)
    Y = x[idx]
    X = np.column_stack([
        np.ones(len(idx)),
        x[idx - 1],           # lag-1
        ma5[idx - 1],         # lag-1 of MA5
        ma22[idx - 1]         # lag-1 of MA22
    ])

    # Check for NaN in features
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None

    Y = Y[valid_rows]
    X = X[valid_rows]

    # OLS
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except:
        return None

    return beta


def har_abs_forecast(abs_ret, beta):
    """One-step-ahead HAR-ABS forecast using fitted coefficients."""
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
    GJR-GARCH(1,1) via quasi-MLE (Gaussian) with numba-accelerated filter.
    σ² = ω + (α + γ I_{r<0}) r²_{t-1} + β σ²_{t-1}
    Returns params dict.
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


def gjr_forecast(returns, params):
    """One-step-ahead GJR-GARCH volatility forecast (as |σ|)."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    omega = params['omega']
    alpha = params['alpha']
    beta_p = params['beta']
    gamma = params['gamma']

    sigma2 = gjr_filter(r, omega, alpha, beta_p, gamma)

    # One-step ahead
    ind = 1.0 if r[-1] < 0 else 0.0
    next_sigma2 = omega + (alpha + gamma * ind) * r[-1]**2 + beta_p * sigma2[-1]
    return max(np.sqrt(next_sigma2), 1e-10)


def ewma_forecast(abs_ret, lam=0.94):
    """EWMA volatility forecast (as |σ|). Forward recursive from t=0."""
    var = abs_ret[0]**2
    for i in range(1, len(abs_ret)):
        var = lam * var + (1 - lam) * abs_ret[i]**2
    # var now = EWMA variance estimate at end of sample
    # One-step forecast = same (persistence)
    return max(np.sqrt(var), 1e-10)


# ============================================================
# Part C: Evaluation Metrics & Horse Race
# ============================================================

def qlike(actual, predicted):
    """QLIKE loss: actual/predicted - log(actual/predicted) - 1."""
    a = np.array(actual)
    p = np.array(predicted)
    valid = (a > 0) & (p > 0)
    a, p = a[valid], p[valid]
    return np.mean(a / p - np.log(a / p) - 1)


def mse(actual, predicted):
    return np.mean((np.array(actual) - np.array(predicted))**2)


def mae(actual, predicted):
    return np.mean(np.abs(np.array(actual) - np.array(predicted)))


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test. H0: E[d_t] = 0 where d_t = loss1_t - loss2_t.
    Negative stat means model 1 is better.
    Returns: (stat, p_value)
    """
    d = np.array(loss1) - np.array(loss2)
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC variance
    max_lag = int(np.ceil(h**(1/3) * n**(1/3)))
    max_lag = max(1, min(max_lag, n // 4))

    gamma0 = np.mean((d - d_mean)**2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l

    if var_d <= 0:
        return 0.0, 1.0

    stat = d_mean / np.sqrt(var_d / n)
    p_val = 2 * (1 - norm.cdf(abs(stat)))
    return stat, p_val


def expanding_window_forecast(returns, abs_ret, min_window=500, refit_freq=63):
    """
    Expanding window 1-day-ahead forecasts for all models.
    Target: |r_{t+1}| (next-day absolute return)

    Refit every 'refit_freq' days for efficiency (63 = quarterly).
    Signal from t, predicting t+1.
    """
    T = len(returns)
    n_oos = T - min_window

    if n_oos < 100:
        print(f"  WARNING: Only {n_oos} OOS obs (need >=100)")
        return None

    print(f"  Expanding window: T={T}, min_window={min_window}, OOS={n_oos}, refit_freq={refit_freq}")

    # Storage
    forecasts = {
        'mem': np.full(n_oos, np.nan),
        'amem': np.full(n_oos, np.nan),
        'har_abs': np.full(n_oos, np.nan),
        'gjr': np.full(n_oos, np.nan),
        'ewma': np.full(n_oos, np.nan),
    }
    actuals = np.full(n_oos, np.nan)

    # Cached model params (refit every refit_freq days)
    mem_params = None
    amem_params = None
    har_beta = None
    gjr_params = None
    last_refit = -refit_freq  # force first refit

    for i in range(n_oos):
        t = min_window + i  # current time index

        if t >= T - 1:
            break

        # Actual target: |r_{t+1}|
        actuals[i] = abs_ret[t + 1]  # next-day realized

        # History up to and including t (contiguous for numba)
        x_hist = np.ascontiguousarray(abs_ret[:t + 1], dtype=np.float64)
        r_hist = np.ascontiguousarray(returns[:t + 1], dtype=np.float64)

        # Refit models periodically
        if i - last_refit >= refit_freq or mem_params is None:
            last_refit = i

            # MEM fit
            mem_fit = fit_mem(x_hist, model='mem')
            if mem_fit and mem_fit['converged']:
                mem_params = mem_fit['params']

            # AMEM fit
            amem_fit = fit_mem(x_hist, model='amem', r=r_hist)
            if amem_fit and amem_fit['converged']:
                amem_params = amem_fit['params']

            # HAR-ABS fit
            har_beta = fit_har_abs(x_hist)

            # GJR-GARCH fit
            gjr_params = fit_gjr_garch(r_hist)

        # --- Generate forecasts ---

        # MEM forecast
        if mem_params is not None:
            mu = mem_filter(x_hist, mem_params['omega'],
                          mem_params['alpha'], mem_params['beta'])
            # One-step ahead: μ_{t+1} = ω + α × x_t + β × μ_t
            fc = mem_params['omega'] + mem_params['alpha'] * x_hist[-1] + mem_params['beta'] * mu[-1]
            forecasts['mem'][i] = max(fc, 1e-10)

        # AMEM forecast
        if amem_params is not None:
            mu = amem_filter(x_hist, r_hist, amem_params['omega'],
                           amem_params['alpha'], amem_params['beta'],
                           amem_params['gamma'])
            ind = 1.0 if r_hist[-1] < 0 else 0.0
            fc = (amem_params['omega']
                  + (amem_params['alpha'] + amem_params['gamma'] * ind) * x_hist[-1]
                  + amem_params['beta'] * mu[-1])
            forecasts['amem'][i] = max(fc, 1e-10)

        # HAR-ABS forecast
        if har_beta is not None:
            fc = har_abs_forecast(x_hist, har_beta)
            if fc is not None:
                forecasts['har_abs'][i] = fc

        # GJR-GARCH forecast
        if gjr_params is not None:
            fc = gjr_forecast(r_hist, gjr_params)
            forecasts['gjr'][i] = fc

        # EWMA forecast
        forecasts['ewma'][i] = ewma_forecast(x_hist)

        # Progress
        if (i + 1) % 500 == 0:
            print(f"    OOS step {i+1}/{n_oos}")

    # Diagnostic: per-model NaN counts
    valid_actuals = ~np.isnan(actuals)
    print(f"  Valid actuals: {valid_actuals.sum()}/{len(actuals)}")
    for k in forecasts:
        valid_k = ~np.isnan(forecasts[k])
        print(f"  Valid {k}: {valid_k.sum()}/{len(forecasts[k])}")
        if valid_k.sum() > 0:
            vals = forecasts[k][valid_k]
            print(f"    range: [{vals.min():.6f}, {vals.max():.6f}]")

    # Trim to valid (require actuals + all forecasts valid)
    valid = valid_actuals.copy()
    for k in forecasts:
        valid &= ~np.isnan(forecasts[k])

    n_valid = valid.sum()
    print(f"  Valid OOS observations (all models): {n_valid}")

    if n_valid < 50:
        # Try with subset of working models
        print("  Trying per-model valid counts...")
        working_models = {}
        for k in forecasts:
            mask = valid_actuals & (~np.isnan(forecasts[k]))
            if mask.sum() >= 50:
                working_models[k] = forecasts[k][mask]
                print(f"    {k}: {mask.sum()} valid")

        if len(working_models) < 2:
            print("  ERROR: fewer than 2 working models")
            return None

        # Use the intersection of working models
        valid = valid_actuals.copy()
        for k in working_models:
            valid &= ~np.isnan(forecasts[k])

        n_valid = valid.sum()
        print(f"  Valid OOS observations (working models): {n_valid}")
        if n_valid < 50:
            return None

    return {
        'actuals': actuals[valid],
        'forecasts': {k: v[valid] for k, v in forecasts.items()},
        'n_oos': int(n_valid)
    }


def evaluate_models(result):
    """Compute QLIKE, MSE, MAE and DM tests for all model pairs."""
    actuals = result['actuals']
    forecasts = result['forecasts']
    models = list(forecasts.keys())

    # Per-model metrics
    metrics = {}
    for m in models:
        preds = forecasts[m]
        metrics[m] = {
            'qlike': float(qlike(actuals, preds)),
            'mse': float(mse(actuals, preds)),
            'mae': float(mae(actuals, preds)),
        }

    # Pointwise QLIKE losses for DM test
    # Filter out zero actuals (|r|=0 causes log(0) = -inf)
    pos_mask = actuals > 0
    a_pos = actuals[pos_mask]
    print(f"  Positive actuals for DM: {pos_mask.sum()}/{len(actuals)}")

    qlike_losses = {}
    for m in models:
        preds = forecasts[m][pos_mask]
        # Pointwise QLIKE: a/p - log(a/p) - 1
        ratio = a_pos / preds
        qlike_losses[m] = ratio - np.log(ratio) - 1

    # DM tests: pairwise
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

    return metrics, dm_results


# ============================================================
# Part D: Full-sample parameter estimation (for reporting)
# ============================================================

def full_sample_estimation(abs_ret, returns, asset_name):
    """Full-sample MEM and AMEM estimation for parameter reporting."""
    print(f"\n{'='*60}")
    print(f"Full-sample estimation: {asset_name}")
    print(f"{'='*60}")

    # Basic stats
    print(f"  N = {len(abs_ret)}")
    print(f"  Mean |r| = {np.mean(abs_ret):.6f}")
    print(f"  Std  |r| = {np.std(abs_ret):.6f}")
    print(f"  Skew |r| = {pd.Series(abs_ret).skew():.3f}")
    print(f"  Kurt |r| = {pd.Series(abs_ret).kurtosis():.3f}")

    # MEM
    mem_fit = fit_mem(abs_ret, model='mem')
    if mem_fit:
        p = mem_fit['params']
        print(f"\n  MEM(1,1): ω={p['omega']:.6f}, α={p['alpha']:.4f}, "
              f"β={p['beta']:.4f}, k={p['k']:.2f}, "
              f"persistence={p['persistence']:.4f}")
        print(f"  Converged: {mem_fit['converged']}, NLL: {mem_fit['nll']:.2f}")

    # AMEM
    amem_fit = fit_mem(abs_ret, model='amem', r=returns)
    if amem_fit:
        p = amem_fit['params']
        print(f"\n  AMEM(1,1): ω={p['omega']:.6f}, α={p['alpha']:.4f}, "
              f"β={p['beta']:.4f}, γ={p['gamma']:.4f}, k={p['k']:.2f}, "
              f"persistence={p['persistence']:.4f}")
        print(f"  Converged: {amem_fit['converged']}, NLL: {amem_fit['nll']:.2f}")

    return mem_fit, amem_fit


# ============================================================
# Main
# ============================================================

def run_asset(ticker, start='2007-01-01', min_window=500, refit_freq=63):
    """Run full experiment for one asset."""
    print(f"\n{'#'*70}")
    print(f"# Asset: {ticker}")
    print(f"{'#'*70}")

    # Download data
    print(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=start, end='2026-04-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])

    if len(df) < min_window + 200:
        print(f"  ERROR: Not enough data ({len(df)} rows)")
        return None

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")

    # Compute returns and absolute returns
    returns = df['Close'].pct_change().dropna().values
    abs_ret = np.abs(returns)

    # Align (drop first)
    returns = returns
    abs_ret = abs_ret

    # Part A+B: Full-sample estimation
    mem_full, amem_full = full_sample_estimation(abs_ret, returns, ticker)

    # Part C: Expanding window horse race
    print(f"\n  Starting expanding window forecast...")
    result = expanding_window_forecast(returns, abs_ret, min_window=min_window,
                                        refit_freq=refit_freq)

    if result is None:
        print(f"  ERROR: Forecasting failed for {ticker}")
        return None

    # Evaluate
    metrics, dm_results = evaluate_models(result)

    # Print results
    print(f"\n  {'Model':<12} {'QLIKE':>10} {'MSE':>12} {'MAE':>10}")
    print(f"  {'-'*46}")

    # Sort by QLIKE
    sorted_models = sorted(metrics.keys(), key=lambda m: metrics[m]['qlike'])
    for m in sorted_models:
        met = metrics[m]
        print(f"  {m:<12} {met['qlike']:>10.4f} {met['mse']:>12.8f} {met['mae']:>10.6f}")

    print(f"\n  DM Tests (QLIKE):")
    print(f"  {'Pair':<25} {'DM stat':>10} {'p-value':>10} {'Harvey':>8} {'Better':>10}")
    print(f"  {'-'*65}")
    for pair, res in sorted(dm_results.items()):
        harvey = '***' if res['harvey_pass'] else ''
        print(f"  {pair:<25} {res['dm_stat']:>10.3f} {res['p_value']:>10.4f} {harvey:>8} {res['better']:>10}")

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
        'oos_metrics': metrics,
        'dm_tests': dm_results,
        'oos_ranking': sorted_models,
    }


def main():
    print("="*70)
    print("K770: Multiplicative Error Model (MEM) for Volatility Forecasting")
    print("="*70)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")
    t_start = time.time()

    # Warmup numba JIT
    print("  Warming up numba JIT...")
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
            result = run_asset(ticker, start='2007-01-01', min_window=500, refit_freq=63)
            if result:
                all_results[ticker] = result
        except Exception as e:
            print(f"  ERROR for {ticker}: {e}")
            import traceback
            traceback.print_exc()

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    summary = {
        'experiment_id': 'k770',
        'title': 'K770: MEM (Multiplicative Error Model) for Volatility Forecasting',
        'proposer': '用戶',
        'executor': 'Claude',
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY, GLD, 0050.TW)',
        'methodology': 'Expanding window, 1-day-ahead, Gamma MLE, QLIKE primary metric',
        'references': [
            'Engle & Gallo (2006) J.Econometrics 131',
            'Brownlees, Cipollini & Gallo (2012) Handbook of Volatility Models',
            'Corsi (2009) J.Financial Econometrics (HAR)',
            'K530: HAR multi-scale champion'
        ],
        'results_by_asset': {},
        'cross_asset_summary': {},
    }

    # Cross-asset analysis
    for ticker, result in all_results.items():
        print(f"\n{ticker}:")
        print(f"  OOS N = {result['n_oos']}, Period: {result['date_range']}")
        print(f"  Ranking (QLIKE): {' > '.join(result['oos_ranking'])}")

        # Best model
        best = result['oos_ranking'][0]
        best_qlike = result['oos_metrics'][best]['qlike']
        print(f"  Best: {best} (QLIKE={best_qlike:.4f})")

        # MEM vs HAR-ABS
        key_mem_har = None
        for k in result['dm_tests']:
            if ('mem' in k and 'har' in k) or ('har' in k and 'mem' in k):
                if 'amem' not in k:
                    key_mem_har = k
                    break

        if key_mem_har:
            dm = result['dm_tests'][key_mem_har]
            print(f"  MEM vs HAR-ABS: DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f}, "
                  f"Harvey={'PASS' if dm['harvey_pass'] else 'FAIL'}")

        # Store summary
        summary['results_by_asset'][ticker] = {
            'n_oos': result['n_oos'],
            'date_range': result['date_range'],
            'oos_metrics': result['oos_metrics'],
            'dm_tests': result['dm_tests'],
            'ranking': result['oos_ranking'],
            'best_model': best,
            'full_sample_params': result['full_sample'],
        }

    # Cross-asset: how often does each model rank best?
    model_ranks = {}
    for ticker, result in all_results.items():
        for rank, m in enumerate(result['oos_ranking'], 1):
            if m not in model_ranks:
                model_ranks[m] = []
            model_ranks[m].append(rank)

    print("\nCross-Asset Average Rank (by QLIKE):")
    for m in sorted(model_ranks.keys(), key=lambda m: np.mean(model_ranks[m])):
        ranks = model_ranks[m]
        print(f"  {m:<12}: avg rank = {np.mean(ranks):.2f} (ranks: {ranks})")
        summary['cross_asset_summary'][m] = {
            'avg_rank': float(np.mean(ranks)),
            'ranks': ranks
        }

    # Key conclusions
    conclusions = []

    # Check if MEM beats HAR
    mem_beats_har = 0
    amem_beats_har = 0
    for ticker, result in all_results.items():
        ranking = result['oos_ranking']
        if ranking.index('mem') < ranking.index('har_abs'):
            mem_beats_har += 1
        if ranking.index('amem') < ranking.index('har_abs'):
            amem_beats_har += 1

    n_assets = len(all_results)
    conclusions.append(
        f"MEM beats HAR-ABS: {mem_beats_har}/{n_assets} assets"
    )
    conclusions.append(
        f"AMEM beats HAR-ABS: {amem_beats_har}/{n_assets} assets"
    )

    # Check if leverage (AMEM > MEM) matters
    amem_beats_mem = 0
    for ticker, result in all_results.items():
        ranking = result['oos_ranking']
        if ranking.index('amem') < ranking.index('mem'):
            amem_beats_mem += 1
    conclusions.append(
        f"AMEM beats MEM (leverage helps): {amem_beats_mem}/{n_assets} assets"
    )

    # Check any Harvey-significant DM
    harvey_passes = []
    for ticker, result in all_results.items():
        for pair, dm in result['dm_tests'].items():
            if dm['harvey_pass']:
                harvey_passes.append(f"{ticker}: {pair} DM={dm['dm_stat']:.2f}")

    if harvey_passes:
        conclusions.append(f"Harvey t>3.0 passes: {harvey_passes}")
    else:
        conclusions.append("No Harvey t>3.0 passes in any pairwise DM test")

    summary['conclusions'] = conclusions
    summary['timestamp'] = datetime.now(timezone.utc).isoformat()

    print(f"\nConclusions:")
    for c in conclusions:
        print(f"  - {c}")

    # Convert numpy types for JSON serialization
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

    # Save results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {RESULTS_PATH}")

    return summary


if __name__ == '__main__':
    results = main()
