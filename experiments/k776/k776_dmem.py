#!/usr/bin/env python3
"""
K776: Doubly Multiplicative Error Model (DMEM) — Long/Short Components
======================================================================
[提出: 用戶 + 文獻搜尋, 執行: Claude]

DMEM decomposes volatility into long-run and short-run multiplicative components,
similar to GARCH-MIDAS but in the MEM framework:

  x_t = τ_t × g_t × ε_t

where:
  τ_t = long-run component (slow-moving, monthly scale)
    τ_t = exp(ω_τ + α_τ × log(RV_22d_t))
  g_t = short-run component (daily dynamics)
    g_t = ω_g + α_g × (x_{t-1}/τ_{t-1}) + β_g × g_{t-1} + γ_g × I(r<0) × (x_{t-1}/τ_{t-1})
  ε_t ~ Gamma(k, 1/k) with E[ε]=1

This is a 7-parameter model: ω_τ, α_τ, ω_g, α_g, β_g, γ_g, k

Compare on SPY (2007-2026):
  DMEM vs AMEM vs MEM vs HAR-ABS vs GJR-GARCH
  All predicting |r_{t+1}| (Approach A: unified target)

References:
  - Cipollini, Engle & Gallo (2013) "Semiparametric Vector MEM"
    Journal of Applied Econometrics 28, 1067-1088
  - Engle & Gallo (2006) "A multiple indicators model for volatility
    using intra-daily data" J.Econometrics 131, 3-27
  - Brownlees, Cipollini & Gallo (2012) Handbook of Volatility Models
  - Engle, Ghysels & Sohn (2013) "Stock Market Volatility and
    Macroeconomic Fundamentals" (GARCH-MIDAS long/short decomp)
  - Corsi (2009) "A Simple Approximate Long-Memory Model of Realized
    Volatility" J.Financial Econometrics (HAR baseline)
  - K770b: AMEM beats HAR-ABS with unified target (confirmed by Codex)
  - Patton (2011) "Volatility forecast comparison using imperfect
    volatility proxies" J.Econometrics 160, 246-256

Data: SPY from yfinance, 2007-01-01 to 2026-03-31
Metrics: QLIKE (primary), MSE, MAE, Diebold-Mariano test, Harvey t>3.0
OOS: Expanding window, min_window=500, refit_freq=63
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

RESULTS_PATH = 'experiments/k776_dmem_results.json'

# Conversion constants under Normal assumption
# If r ~ N(0, σ²), then E[|r|] = σ × sqrt(2/π)
SQRT_2_OVER_PI = np.sqrt(2.0 / np.pi)  # ≈ 0.7979
PI_OVER_2 = np.pi / 2.0                # ≈ 1.5708

# ============================================================
# Part A: Existing Model Implementations (from K770b, verified)
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


# ============================================================
# Part B: DMEM Implementation (NEW)
# ============================================================

@njit(cache=True)
def dmem_long_run_component(abs_ret, omega_tau, alpha_tau):
    """
    Long-run component:
      τ_t = exp(ω_τ + α_τ × log(RV_22d_t))
    where RV_22d_t = mean(|r_{t-21}|, ..., |r_t|) = 22-day rolling mean of |r|

    For t < 22, use expanding mean.
    Returns: τ array (same length as abs_ret)
    """
    T = len(abs_ret)
    tau = np.zeros(T)
    for t in range(T):
        # Compute rolling 22-day mean of |r| up to t
        start = max(0, t - 21)
        rv_22d = 0.0
        count = 0
        for s in range(start, t + 1):
            rv_22d += abs_ret[s]
            count += 1
        rv_22d /= count
        if rv_22d < 1e-10:
            rv_22d = 1e-10
        tau[t] = np.exp(omega_tau + alpha_tau * np.log(rv_22d))
        if tau[t] < 1e-10:
            tau[t] = 1e-10
    return tau


@njit(cache=True)
def dmem_short_run_filter(x, r, tau, omega_g, alpha_g, beta_g, gamma_g):
    """
    Short-run component with leverage:
      g_t = ω_g + α_g × (x_{t-1}/τ_{t-1}) + β_g × g_{t-1}
            + γ_g × I(r_{t-1}<0) × (x_{t-1}/τ_{t-1})

    g_t captures daily dynamics around the long-run level τ_t.
    The full model: E[x_t | F_{t-1}] = τ_t × g_t (with E[ε]=1).
    Returns: g array
    """
    T = len(x)
    g = np.zeros(T)
    # Initialize: g_0 = 1 (neutral around long-run)
    g[0] = 1.0
    for t in range(1, T):
        # Deseasonalized lagged observation
        ratio = x[t-1] / tau[t-1] if tau[t-1] > 1e-10 else 1.0
        indicator = 1.0 if r[t-1] < 0 else 0.0
        g[t] = omega_g + alpha_g * ratio + beta_g * g[t-1] + gamma_g * indicator * ratio
        if g[t] < 1e-10:
            g[t] = 1e-10
    return g


def dmem_negloglik(params, x, r):
    """
    Gamma MLE for DMEM.
    x_t = τ_t × g_t × ε_t
    ε_t = x_t / (τ_t × g_t) ~ Gamma(k, 1/k), E[ε]=1

    params: [omega_tau, alpha_tau, omega_g, alpha_g, beta_g, gamma_g, k]
    """
    omega_tau, alpha_tau, omega_g, alpha_g, beta_g, gamma_g, k = params

    # Constraints
    if omega_g <= 0 or alpha_g < 0 or beta_g < 0 or gamma_g < 0 or k <= 0:
        return 1e10
    # Stationarity of short-run: α_g + β_g + 0.5*γ_g < 1
    if alpha_g + beta_g + 0.5 * gamma_g >= 1.0:
        return 1e10
    # α_τ should be positive (higher past vol → higher long-run)
    # but allow negative for flexibility
    if abs(alpha_tau) > 5.0:
        return 1e10

    # Compute components
    tau = dmem_long_run_component(x, omega_tau, alpha_tau)
    g = dmem_short_run_filter(x, r, tau, omega_g, alpha_g, beta_g, gamma_g)

    # Conditional mean: μ_t = τ_t × g_t
    mu = tau * g

    # Gamma log-likelihood (skip first obs)
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


def fit_dmem(x, r, max_attempts=5):
    """
    Fit DMEM via Gamma MLE with multiple restarts.
    Parameters: [omega_tau, alpha_tau, omega_g, alpha_g, beta_g, gamma_g, k]
    """
    x = np.ascontiguousarray(x, dtype=np.float64)
    r = np.ascontiguousarray(r, dtype=np.float64)
    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 0.01

    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt * 7)

        # Long-run initial guesses
        # τ = exp(ω_τ + α_τ × log(RV_22d))
        # If α_τ=1, ω_τ=0, then τ ≈ RV_22d (reasonable starting point)
        omega_tau0 = 0.0 + 0.3 * np.random.randn()
        alpha_tau0 = 0.8 + 0.2 * np.random.randn()
        alpha_tau0 = max(0.1, min(alpha_tau0, 2.0))

        # Short-run initial guesses (similar to AMEM but for deseasonalized)
        omega_g0 = 0.05 + 0.03 * np.random.randn()
        alpha_g0 = 0.05 + 0.03 * np.random.randn()
        beta_g0 = 0.85 + 0.05 * np.random.randn()
        gamma_g0 = 0.1 + 0.05 * np.random.randn()
        k0 = 2.0 + np.random.rand()

        omega_g0 = max(0.01, min(omega_g0, 0.3))
        alpha_g0 = max(0.01, min(alpha_g0, 0.4))
        beta_g0 = max(0.3, min(beta_g0, 0.95))
        gamma_g0 = max(0.01, min(gamma_g0, 0.3))
        if alpha_g0 + beta_g0 + 0.5 * gamma_g0 >= 0.99:
            beta_g0 = 0.97 - alpha_g0 - 0.5 * gamma_g0

        p0 = [omega_tau0, alpha_tau0, max(0.01, omega_g0),
              alpha_g0, beta_g0, max(0.01, gamma_g0), max(0.5, k0)]

        bounds = [
            (-3.0, 3.0),     # omega_tau
            (0.01, 3.0),     # alpha_tau
            (1e-6, 1.0),     # omega_g
            (0.0, 0.8),      # alpha_g
            (0.0, 0.99),     # beta_g
            (0.0, 0.8),      # gamma_g
            (0.1, 100.0),    # k
        ]

        try:
            result = minimize(dmem_negloglik, p0, args=(x, r),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 8000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        return None

    res = best_result
    params = {
        'omega_tau': float(res.x[0]),
        'alpha_tau': float(res.x[1]),
        'omega_g': float(res.x[2]),
        'alpha_g': float(res.x[3]),
        'beta_g': float(res.x[4]),
        'gamma_g': float(res.x[5]),
        'k': float(res.x[6]),
        'short_persistence': float(res.x[3] + res.x[4] + 0.5 * res.x[5]),
    }
    return {
        'params': params,
        'converged': bool(res.success),
        'nll': float(res.fun),
        'n_obs': len(x)
    }


def dmem_forecast(x, r, params):
    """
    One-step-ahead DMEM forecast: E[x_{t+1}|F_t] = τ_{t+1} × g_{t+1}.

    Note: τ_{t+1} uses RV_22d up to t+1, but we only have data up to t.
    For OOS forecasting, we use τ_t as proxy for τ_{t+1} (slow-moving).
    g_{t+1} uses the recursion based on data up to t.
    """
    x = np.ascontiguousarray(x, dtype=np.float64)
    r = np.ascontiguousarray(r, dtype=np.float64)

    # Long-run component at t (use as proxy for t+1)
    tau = dmem_long_run_component(x, params['omega_tau'], params['alpha_tau'])
    tau_next = tau[-1]  # τ_t ≈ τ_{t+1} (slow-moving)

    # Short-run component recursion up to t
    g = dmem_short_run_filter(x, r, tau,
                              params['omega_g'], params['alpha_g'],
                              params['beta_g'], params['gamma_g'])
    # g_{t+1}
    ratio = x[-1] / tau[-1] if tau[-1] > 1e-10 else 1.0
    indicator = 1.0 if r[-1] < 0 else 0.0
    g_next = (params['omega_g']
              + params['alpha_g'] * ratio
              + params['beta_g'] * g[-1]
              + params['gamma_g'] * indicator * ratio)
    g_next = max(g_next, 1e-10)

    # Forecast: E[x_{t+1}] = τ_{t+1} × g_{t+1} × E[ε] = τ_{t+1} × g_{t+1}
    fc = tau_next * g_next
    return max(fc, 1e-10)


# ============================================================
# Existing Model Implementations (from K770b)
# ============================================================

def mem_negloglik(params, x, model='mem', r=None):
    """Gamma MLE for MEM/AMEM."""
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
    """GJR-GARCH(1,1) via quasi-MLE (Gaussian). Forecast: σ²."""
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
    """One-step-ahead GJR-GARCH forecast. Returns σ²_{t+1}."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    next_sigma2 = (params['omega'] + (params['alpha'] + params['gamma'] * ind)
                   * r[-1]**2 + params['beta'] * sigma2[-1])
    return max(next_sigma2, 1e-12)


# ============================================================
# Evaluation Metrics
# ============================================================

def qlike(actual, predicted):
    """QLIKE loss: actual/predicted - log(actual/predicted) - 1."""
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
    """Pointwise QLIKE losses for DM test."""
    a = np.array(actual)
    p = np.array(predicted)
    ratio = a / p
    return ratio - np.log(ratio) - 1


# ============================================================
# Expanding Window Forecast with DMEM
# ============================================================

def expanding_window_forecast(returns, abs_ret, min_window=500, refit_freq=63):
    """
    Expanding window 1-day-ahead forecasts for all models including DMEM.
    All models forecast E[|r_{t+1}|] (Approach A: unified target).

    Models:
      - DMEM: long/short decomposition → E[|r|]
      - AMEM: asymmetric MEM → E[|r|]
      - MEM: basic MEM → E[|r|]
      - HAR-ABS: heterogeneous AR → E[|r|]
      - GJR-GARCH: → σ², converted to E[|r|] = sqrt(σ²) × sqrt(2/π)
    """
    T = len(returns)
    n_oos = T - min_window

    if n_oos < 100:
        print(f"  WARNING: Only {n_oos} OOS obs (need >=100)")
        return None

    print(f"  Expanding window: T={T}, min_window={min_window}, OOS={n_oos}, refit_freq={refit_freq}")

    models = ['dmem', 'amem', 'mem', 'har_abs', 'gjr']
    forecasts = {m: np.full(n_oos, np.nan) for m in models}
    actuals = np.full(n_oos, np.nan)   # |r_{t+1}|

    # Cached model params
    dmem_params = None
    amem_params = None
    mem_params = None
    har_beta = None
    gjr_params = None
    last_refit = -refit_freq

    t0 = time.time()

    for i in range(n_oos):
        t = min_window + i
        if t >= T - 1:
            break

        # Actual target: |r_{t+1}|
        actuals[i] = abs_ret[t + 1]

        # History up to t
        x_hist = np.ascontiguousarray(abs_ret[:t + 1], dtype=np.float64)
        r_hist = np.ascontiguousarray(returns[:t + 1], dtype=np.float64)

        # Refit periodically
        if i - last_refit >= refit_freq or dmem_params is None:
            last_refit = i

            # DMEM fit
            dmem_fit = fit_dmem(x_hist, r_hist, max_attempts=5)
            if dmem_fit and dmem_fit['converged']:
                dmem_params = dmem_fit['params']

            # AMEM fit
            amem_fit = fit_mem(x_hist, model='amem', r=r_hist)
            if amem_fit and amem_fit['converged']:
                amem_params = amem_fit['params']

            # MEM fit
            mem_fit = fit_mem(x_hist, model='mem')
            if mem_fit and mem_fit['converged']:
                mem_params = mem_fit['params']

            # HAR-ABS fit (OLS, cheap)
            har_beta = fit_har_abs(x_hist)

            # GJR-GARCH fit
            gjr_params = fit_gjr_garch(r_hist)

            if (i + 1) <= 3 or (i + 1) % 500 == 0:
                elapsed = time.time() - t0
                print(f"    Refit at OOS step {i+1}/{n_oos}, elapsed={elapsed:.1f}s")
                if dmem_fit:
                    p = dmem_fit['params']
                    print(f"      DMEM: α_τ={p['alpha_tau']:.3f}, α_g={p['alpha_g']:.3f}, "
                          f"β_g={p['beta_g']:.3f}, γ_g={p['gamma_g']:.3f}, "
                          f"short_pers={p['short_persistence']:.3f}, conv={dmem_fit['converged']}")

        # --- Generate forecasts ---

        # DMEM → E[|r_{t+1}|]
        if dmem_params is not None:
            forecasts['dmem'][i] = dmem_forecast(x_hist, r_hist, dmem_params)

        # AMEM → E[|r_{t+1}|]
        if amem_params is not None:
            mu = amem_filter(x_hist, r_hist, amem_params['omega'],
                           amem_params['alpha'], amem_params['beta'],
                           amem_params['gamma'])
            ind = 1.0 if r_hist[-1] < 0 else 0.0
            fc = (amem_params['omega']
                  + (amem_params['alpha'] + amem_params['gamma'] * ind) * x_hist[-1]
                  + amem_params['beta'] * mu[-1])
            forecasts['amem'][i] = max(fc, 1e-10)

        # MEM → E[|r_{t+1}|]
        if mem_params is not None:
            mu = mem_filter(x_hist, mem_params['omega'],
                          mem_params['alpha'], mem_params['beta'])
            fc = mem_params['omega'] + mem_params['alpha'] * x_hist[-1] + mem_params['beta'] * mu[-1]
            forecasts['mem'][i] = max(fc, 1e-10)

        # HAR-ABS → E[|r_{t+1}|]
        if har_beta is not None:
            fc = har_abs_forecast(x_hist, har_beta)
            if fc is not None:
                forecasts['har_abs'][i] = fc

        # GJR-GARCH → σ²_{t+1} → E[|r|] = sqrt(σ²) × sqrt(2/π)
        if gjr_params is not None:
            sigma2_fc = gjr_forecast_sigma2(r_hist, gjr_params)
            forecasts['gjr'][i] = np.sqrt(sigma2_fc) * SQRT_2_OVER_PI

        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            print(f"    OOS step {i+1}/{n_oos}, elapsed={elapsed:.1f}s")

    elapsed = time.time() - t0
    print(f"  Total forecast time: {elapsed:.1f}s")

    # Valid mask: all models have forecasts and actuals > 0
    valid = ~np.isnan(actuals) & (actuals > 0)
    for m in models:
        valid &= ~np.isnan(forecasts[m])

    n_valid = int(valid.sum())
    print(f"  Valid OOS observations (all models): {n_valid}")

    if n_valid < 50:
        print("  ERROR: Too few valid observations")
        return None

    return {
        'actuals': actuals[valid],
        'forecasts': {m: forecasts[m][valid] for m in models},
        'n_oos': n_valid
    }


# ============================================================
# Evaluation
# ============================================================

def evaluate_models(result):
    """
    Evaluate all models on unified target: E[|r|].
    QLIKE is primary metric. DM test for pairwise comparison.
    """
    actuals = result['actuals']
    models = list(result['forecasts'].keys())

    metrics = {}
    qlike_losses = {}
    for m in models:
        preds = result['forecasts'][m]
        metrics[m] = {
            'qlike': float(qlike(actuals, preds)),
            'mse': float(mse(actuals, preds)),
            'mae': float(mae(actuals, preds)),
            'mean_forecast': float(np.mean(preds)),
            'std_forecast': float(np.std(preds)),
            'corr_with_actual': float(np.corrcoef(actuals, preds)[0, 1]),
        }
        qlike_losses[m] = pointwise_qlike(actuals, preds)

    # DM tests (all pairs)
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

    # Ranking by QLIKE (lower is better)
    ranking = sorted(models, key=lambda m: metrics[m]['qlike'])

    return metrics, dm_results, ranking


# ============================================================
# Subsample Analysis
# ============================================================

def subsample_analysis(result, n_splits=3):
    """Split OOS into n_splits for robustness check."""
    actuals = result['actuals']
    n = len(actuals)
    split_size = n // n_splits
    models = list(result['forecasts'].keys())

    subsample_results = []
    for s in range(n_splits):
        start = s * split_size
        end = (s + 1) * split_size if s < n_splits - 1 else n
        sub_actuals = actuals[start:end]
        sub_metrics = {}
        for m in models:
            sub_preds = result['forecasts'][m][start:end]
            sub_metrics[m] = {
                'qlike': float(qlike(sub_actuals, sub_preds)),
                'mae': float(mae(sub_actuals, sub_preds)),
            }
        sub_ranking = sorted(models, key=lambda m: sub_metrics[m]['qlike'])
        subsample_results.append({
            'period': f'split_{s+1}',
            'n_obs': end - start,
            'metrics': sub_metrics,
            'ranking': sub_ranking,
        })
    return subsample_results


# ============================================================
# Crisis vs Calm Analysis
# ============================================================

def crisis_calm_analysis(result):
    """
    Compare model performance in high-vol vs low-vol regimes.
    High-vol: actual |r| > 75th percentile
    Low-vol: actual |r| < 25th percentile
    """
    actuals = result['actuals']
    models = list(result['forecasts'].keys())
    p25, p75 = np.percentile(actuals, [25, 75])

    regime_results = {}
    for regime_name, mask in [('calm', actuals < p25), ('crisis', actuals > p75)]:
        r_actuals = actuals[mask]
        r_metrics = {}
        for m in models:
            r_preds = result['forecasts'][m][mask]
            r_metrics[m] = {
                'qlike': float(qlike(r_actuals, r_preds)),
                'mae': float(mae(r_actuals, r_preds)),
            }
        r_ranking = sorted(models, key=lambda m: r_metrics[m]['qlike'])
        regime_results[regime_name] = {
            'n_obs': int(mask.sum()),
            'threshold': float(p25) if regime_name == 'calm' else float(p75),
            'metrics': r_metrics,
            'ranking': r_ranking,
        }
    return regime_results


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K776: DMEM (Doubly Multiplicative Error Model) — Long/Short Components")
    print("=" * 70)
    print()

    # ---- Data ----
    print("[1/5] Downloading SPY data...")
    spy = yf.download('SPY', start='2007-01-01', end='2026-03-31', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.dropna(subset=['Close'])
    returns = spy['Close'].pct_change().dropna().values
    abs_ret = np.abs(returns)
    dates = spy.index[1:]  # align with returns

    print(f"  SPY: {len(returns)} daily returns, {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean |r|: {np.mean(abs_ret):.6f}, Std |r|: {np.std(abs_ret):.6f}")
    print()

    # ---- Descriptive: Long-run component check ----
    print("[2/5] DMEM long-run component diagnostic...")
    # Check if long-run component captures slow variation
    rv_22d = pd.Series(abs_ret).rolling(22).mean().values
    rv_22d_valid = rv_22d[~np.isnan(rv_22d)]
    print(f"  RV_22d stats: mean={np.mean(rv_22d_valid):.6f}, std={np.std(rv_22d_valid):.6f}")
    print(f"  RV_22d range: [{np.min(rv_22d_valid):.6f}, {np.max(rv_22d_valid):.6f}]")
    print(f"  RV_22d autocorr(1): {np.corrcoef(rv_22d_valid[:-1], rv_22d_valid[1:])[0,1]:.4f}")
    print(f"  RV_22d autocorr(22): {np.corrcoef(rv_22d_valid[:-22], rv_22d_valid[22:])[0,1]:.4f}")
    print()

    # ---- Full-sample DMEM fit for diagnostics ----
    print("[3/5] Full-sample DMEM estimation (diagnostic only)...")
    x_full = np.ascontiguousarray(abs_ret, dtype=np.float64)
    r_full = np.ascontiguousarray(returns, dtype=np.float64)
    dmem_full = fit_dmem(x_full, r_full, max_attempts=5)
    if dmem_full:
        p = dmem_full['params']
        print(f"  DMEM converged: {dmem_full['converged']}")
        print(f"  Long-run: ω_τ={p['omega_tau']:.4f}, α_τ={p['alpha_tau']:.4f}")
        print(f"  Short-run: ω_g={p['omega_g']:.6f}, α_g={p['alpha_g']:.4f}, "
              f"β_g={p['beta_g']:.4f}, γ_g={p['gamma_g']:.4f}")
        print(f"  Short persistence: {p['short_persistence']:.4f}")
        print(f"  Gamma shape k: {p['k']:.4f}")
        print(f"  NLL: {dmem_full['nll']:.2f}")

        # Compare with AMEM full-sample
        amem_full = fit_mem(x_full, model='amem', r=r_full)
        if amem_full:
            print(f"\n  AMEM for comparison:")
            pa = amem_full['params']
            print(f"    ω={pa['omega']:.6f}, α={pa['alpha']:.4f}, "
                  f"β={pa['beta']:.4f}, γ={pa['gamma']:.4f}")
            print(f"    Persistence: {pa['persistence']:.4f}, k={pa['k']:.4f}")
            print(f"    NLL: {amem_full['nll']:.2f}")
            print(f"    NLL improvement (DMEM vs AMEM): {amem_full['nll'] - dmem_full['nll']:.2f}")
    print()

    # ---- Expanding window OOS ----
    print("[4/5] Expanding window OOS forecast (5 models)...")
    result = expanding_window_forecast(returns, abs_ret, min_window=500, refit_freq=63)

    if result is None:
        print("ERROR: Forecast failed")
        return

    print(f"\n  OOS observations: {result['n_oos']}")
    print()

    # ---- Evaluation ----
    print("[5/5] Evaluation...")
    metrics, dm_results, ranking = evaluate_models(result)

    print("\n  === QLIKE Ranking (lower = better) ===")
    for i, m in enumerate(ranking):
        print(f"    #{i+1}: {m:12s}  QLIKE={metrics[m]['qlike']:.6f}  "
              f"MAE={metrics[m]['mae']:.6f}  Corr={metrics[m]['corr_with_actual']:.4f}")

    print("\n  === DM Test Results (QLIKE, Harvey t>3.0) ===")
    for pair, res in sorted(dm_results.items()):
        marker = "***" if res['harvey_pass'] else ""
        print(f"    {pair:25s}: DM={res['dm_stat']:+7.3f}, p={res['p_value']:.4f}, "
              f"better={res['better']:12s} {marker}")

    # Key comparison: DMEM vs AMEM
    key_pair = 'dmem_vs_amem'
    if key_pair in dm_results:
        kp = dm_results[key_pair]
        print(f"\n  *** KEY: DMEM vs AMEM: DM={kp['dm_stat']:+.3f}, "
              f"p={kp['p_value']:.4f}, better={kp['better']}, "
              f"Harvey={kp['harvey_pass']}")

    # Subsample analysis
    print("\n  === Subsample Robustness (3 splits) ===")
    sub_results = subsample_analysis(result, n_splits=3)
    for sr in sub_results:
        qlike_str = ", ".join(f"{m}={sr['metrics'][m]['qlike']:.6f}" for m in ranking[:3])
        print(f"    {sr['period']} (n={sr['n_obs']}): top3 QLIKE: {qlike_str}")
        print(f"      ranking: {sr['ranking']}")

    # Crisis vs calm
    print("\n  === Crisis vs Calm Regimes ===")
    regime_results = crisis_calm_analysis(result)
    for regime, rr in regime_results.items():
        qlike_str = ", ".join(f"{m}={rr['metrics'][m]['qlike']:.6f}" for m in rr['ranking'][:3])
        print(f"    {regime} (n={rr['n_obs']}, threshold={rr['threshold']:.6f}):")
        print(f"      top3 QLIKE: {qlike_str}")
        print(f"      ranking: {rr['ranking']}")

    # ---- Assemble results JSON ----
    full_sample_dmem = None
    if dmem_full:
        full_sample_dmem = {
            'params': {k: float(v) for k, v in dmem_full['params'].items()},
            'converged': bool(dmem_full['converged']),
            'nll': float(dmem_full['nll']),
        }

    results = {
        'experiment_id': 'K776',
        'title': 'DMEM (Doubly Multiplicative Error Model) — Long/Short Components',
        'proposer': '用戶 + 文獻搜尋',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'asset': 'SPY',
        'data_period': f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
        'n_total': len(returns),
        'n_oos': result['n_oos'],
        'min_window': 500,
        'refit_freq': 63,
        'target': 'E[|r_{t+1}|] (Approach A: unified absolute return target)',
        'models_compared': ['DMEM', 'AMEM', 'MEM', 'HAR-ABS', 'GJR-GARCH'],
        'dmem_specification': {
            'long_run': 'τ_t = exp(ω_τ + α_τ × log(RV_22d_t))',
            'short_run': 'g_t = ω_g + α_g × (x_{t-1}/τ_{t-1}) + β_g × g_{t-1} + γ_g × I(r<0) × (x_{t-1}/τ_{t-1})',
            'full_model': 'x_t = τ_t × g_t × ε_t, ε_t ~ Gamma(k, 1/k)',
            'n_params': 7,
        },
        'full_sample_dmem': full_sample_dmem,
        'oos_metrics': metrics,
        'dm_tests': dm_results,
        'qlike_ranking': ranking,
        'subsample_robustness': sub_results,
        'regime_analysis': regime_results,
        'conclusion': '',
        'references': [
            'Cipollini, Engle & Gallo (2013) J.Applied Econometrics 28, 1067-1088',
            'Engle & Gallo (2006) J.Econometrics 131, 3-27',
            'Brownlees, Cipollini & Gallo (2012) Handbook of Volatility Models',
            'Engle, Ghysels & Sohn (2013) GARCH-MIDAS long/short decomposition',
            'Corsi (2009) J.Financial Econometrics (HAR baseline)',
            'Patton (2011) J.Econometrics 160, 246-256 (QLIKE robustness)',
        ],
    }

    # Generate conclusion
    best = ranking[0]
    second = ranking[1]
    dmem_rank = ranking.index('dmem') + 1
    amem_rank = ranking.index('amem') + 1

    # Check if DMEM beats AMEM significantly
    dmem_vs_amem = dm_results.get('dmem_vs_amem', {})
    dmem_wins = dmem_vs_amem.get('better', '') == 'dmem'
    harvey_pass = dmem_vs_amem.get('harvey_pass', False)

    if dmem_rank == 1 and harvey_pass and dmem_wins:
        conclusion = (f"DMEM (long/short decomposition) BEATS all competitors including AMEM. "
                     f"QLIKE ranking: {ranking}. "
                     f"DM stat vs AMEM: {dmem_vs_amem.get('dm_stat', 'N/A'):.3f} (Harvey PASS). "
                     f"The explicit long-run/short-run decomposition provides significant "
                     f"forecasting improvement.")
    elif dmem_rank <= 2:
        conclusion = (f"DMEM ranks #{dmem_rank}, competitive with AMEM (#{amem_rank}). "
                     f"QLIKE ranking: {ranking}. "
                     f"DM stat DMEM vs AMEM: {dmem_vs_amem.get('dm_stat', 'N/A')}. "
                     f"Long/short decomposition adds marginal value but may not pass Harvey t>3 threshold.")
    else:
        conclusion = (f"DMEM ranks #{dmem_rank}, below AMEM (#{amem_rank}). "
                     f"QLIKE ranking: {ranking}. "
                     f"Despite theoretical appeal, the explicit long/short decomposition "
                     f"does NOT improve over simpler AMEM in OOS forecasting. "
                     f"Possible reasons: (1) 7-parameter model overfits in-sample, "
                     f"(2) τ_t estimation noise hurts OOS, (3) AMEM implicitly captures "
                     f"long-memory through high β persistence.")

    results['conclusion'] = conclusion
    print(f"\n  CONCLUSION: {conclusion}")

    # Save results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_PATH}")

    return results


if __name__ == '__main__':
    main()
