#!/usr/bin/env python3
"""
K781: Multiplicative Volatility Factor (MVF) Model
===================================================
[提出: 文獻搜尋 J.Econometrics 2025, 執行: Claude]

The MVF model decomposes conditional variance multiplicatively into a
slow-moving long-run factor and a fast short-run GARCH component:

  σ²_t = exp(f_t) × g_t

where:
  f_t = long-run factor (log-linear, captures regime shifts):
        f_t = ρ × f_{t-1} + (1-ρ) × log(RV_66d_t)
        This is an exponentially-smoothed log-realized-variance
  g_t = short-run factor (GARCH on detrended squared returns):
        g_t = ω_g + α_g × (r²_{t-1}/exp(f_{t-1})) + β_g × g_{t-1}
        + γ_g × I(r_{t-1}<0) × (r²_{t-1}/exp(f_{t-1}))

Forecast: σ²_{t+1|t} = exp(f_t) × g_{t+1|t}

This is a DIFFERENT multiplicative decomposition from K776 DMEM:
  - DMEM: τ_t × g_t × ε_t with τ estimated from RV_22d via MLE
  - MVF: exp(f_t) × g_t with f_t as a SMOOTHER (EWA of log-RV)
    + short-run g_t estimated via GARCH on detrended returns
The key difference: MVF's long-run factor uses 66-day RV (quarterly),
is more parsimonious (f_t has only 1 param ρ vs DMEM's 2), and the
short-run component sees detrended r² which should be closer to
stationary → better GARCH fit.

Compare on r² target (Patton 2011, proxy-robust QLIKE):
  1. MVF (this, 5 params: ρ, ω_g, α_g, β_g, γ_g)
  2. GJR-GARCH (4 params: ω, α, β, γ)
  3. AMEM-r² (5 params: ω, α, β, γ, k)
  4. GARCH(1,1) (3 params: ω, α, β)
  5. HAR-r² (4 params: β₀, β₁, β₂, β₃)

References:
  - J. Econometrics 2025, "Multiplicative Volatility Factor" model
  - Conrad (2025) MF2-GARCH, J. Applied Econometrics — related multiplicative approach
  - Engle, Ghysels & Sohn (2013) GARCH-MIDAS — multiplicative decomposition inspiration
  - Patton (2011) J.Econometrics 160 — QLIKE proxy-robust loss
  - Hansen, Lunde & Nason (2011) Econometrica — Model Confidence Set
  - Glosten, Jagannathan, Runkle (1993) JoF — GJR-GARCH
  - Engle & Gallo (2006) J.Econometrics — MEM/AMEM framework
  - Corsi (2009) J.Financial Econometrics — HAR model
  - K778: MEM-r² native comparison (GJR > AMEM-r² on r²)
  - K776: DMEM long/short decomposition (AMEM still wins)

Data: SPY, 2007-2026, expanding window OOS
Evaluation: QLIKE on r², Spearman, DM + Harvey t>3.0, MCS
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import spearmanr, norm
from datetime import datetime, timezone
from numba import njit
import warnings
import os
import sys
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = 'experiments/k781_mvf_results.json'

# ============================================================
# Part A: Numba-accelerated filters
# ============================================================

@njit(cache=True)
def mvf_long_run_factor(log_rv66, rho):
    """
    MVF long-run factor (exponentially smoothed log-RV66):
        f_t = ρ × f_{t-1} + (1-ρ) × log(RV_66d_t)

    log_rv66: log of 66-day rolling mean of r²
    rho: smoothing parameter (0 < ρ < 1, higher = smoother)
    Returns: f (same length as log_rv66)
    """
    T = len(log_rv66)
    f = np.zeros(T)
    f[0] = log_rv66[0]
    for t in range(1, T):
        f[t] = rho * f[t-1] + (1.0 - rho) * log_rv66[t]
    return f


@njit(cache=True)
def mvf_short_run_filter(detrended_r2, r, omega_g, alpha_g, beta_g, gamma_g):
    """
    MVF short-run GJR-GARCH on detrended squared returns:
        g_t = ω_g + α_g × z²_{t-1} + β_g × g_{t-1} + γ_g × I(r<0) × z²_{t-1}

    where z²_t = r²_t / exp(f_t)  (detrended squared return)
    detrended_r2: r²/exp(f) array
    r: raw returns (for sign/leverage)
    Returns: g (conditional variance of detrended series)
    """
    T = len(detrended_r2)
    g = np.zeros(T)
    # Initialize at mean of detrended squared returns
    g_init = 0.0
    for i in range(T):
        g_init += detrended_r2[i]
    g_init /= T
    g[0] = max(g_init, 1e-10)

    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        g[t] = (omega_g + alpha_g * detrended_r2[t-1]
                + beta_g * g[t-1]
                + gamma_g * ind * detrended_r2[t-1])
        if g[t] < 1e-12:
            g[t] = 1e-12
    return g


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


@njit(cache=True)
def garch_filter(r, omega, alpha, beta):
    """GARCH(1,1) variance filter. Returns σ² array."""
    T = len(r)
    sigma2 = np.zeros(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i]**2
    var_r /= T
    sigma2[0] = var_r
    for t in range(1, T):
        sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return sigma2


@njit(cache=True)
def amem_r2_filter(r2, r, omega, alpha, beta, gamma):
    """
    AMEM-r² conditional mean recursion with leverage (native variance space):
        μ_t = ω + (α + γ × I_{r<0}) × r²_{t-1} + β × μ_{t-1}
    """
    T = len(r2)
    mu = np.zeros(T)
    mu[0] = r2[0] if r2[0] > 0 else 1e-6
    for t in range(1, T):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        mu[t] = omega + (alpha + gamma * indicator) * r2[t-1] + beta * mu[t-1]
        if mu[t] < 1e-12:
            mu[t] = 1e-12
    return mu


# ============================================================
# Part B: MVF fitting (two-step estimation)
# ============================================================

def compute_long_run_factor(r2, rho, rv_window=66):
    """
    Compute f_t = EWA of log(RV_66d).

    r2: squared returns
    rho: smoothing parameter
    rv_window: rolling window for RV (default 66 = quarterly)
    """
    r2_series = pd.Series(r2)
    rv = r2_series.rolling(rv_window, min_periods=rv_window).mean().values.copy()

    # Fill initial NaNs with expanding mean
    for i in range(rv_window):
        if i == 0:
            rv[i] = r2[0] if r2[0] > 0 else 1e-8
        else:
            rv[i] = np.mean(r2[:i+1])

    # Floor at small positive
    rv = np.maximum(rv, 1e-12)
    log_rv = np.log(rv)

    # Exponentially smooth
    f = mvf_long_run_factor(log_rv, rho)
    return f


def fit_mvf(returns, r2, max_attempts=5):
    """
    Fit MVF model via two-step:
    Step 1: Profile over ρ (long-run smoother) via grid
    Step 2: For each ρ, fit GJR-GARCH on detrended r² via MLE
    Select ρ that minimizes total negative log-likelihood.

    Parameters: ρ, ω_g, α_g, β_g, γ_g (5 total)
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    r2_arr = np.ascontiguousarray(r2, dtype=np.float64)
    T = len(r)

    if T < 100:
        return None

    best_nll = 1e10
    best_params = None

    # Grid search over ρ
    rho_grid = [0.90, 0.93, 0.95, 0.97, 0.98, 0.99, 0.995]

    for rho in rho_grid:
        f = compute_long_run_factor(r2_arr, rho, rv_window=66)
        exp_f = np.exp(f)

        # Detrended squared returns
        z2 = r2_arr / exp_f
        z2 = np.maximum(z2, 1e-12)

        # Fit short-run GJR on z²
        z2_c = np.ascontiguousarray(z2, dtype=np.float64)

        for attempt in range(max_attempts):
            np.random.seed(42 + attempt)
            z2_mean = np.mean(z2_c[z2_c > 0])

            alpha0 = max(0.01, min(0.3, 0.05 + 0.03 * np.random.randn()))
            beta0 = max(0.5, min(0.98, 0.88 + 0.04 * np.random.randn()))
            gamma0 = max(0.01, min(0.3, 0.08 + 0.04 * np.random.randn()))
            if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
                beta0 = 0.97 - alpha0 - 0.5 * gamma0
            omega0 = z2_mean * (1 - alpha0 - beta0 - 0.5 * gamma0)

            p0 = [max(1e-8, omega0), alpha0, beta0, gamma0]

            def mvf_short_negll(params, z2, r):
                omega_g, alpha_g, beta_g, gamma_g = params
                if omega_g <= 0 or alpha_g < 0 or beta_g < 0 or gamma_g < 0:
                    return 1e10
                if alpha_g + beta_g + 0.5 * gamma_g >= 1.0:
                    return 1e10
                g = mvf_short_run_filter(z2, r, omega_g, alpha_g, beta_g, gamma_g)
                # Gaussian quasi-log-likelihood on detrended r²
                # z²_t | g_t ~ like a GARCH: -0.5*(log(g_t) + z²_t/g_t)
                ll = -0.5 * np.sum(np.log(g[1:]) + z2[1:] / g[1:])
                return -ll if np.isfinite(ll) else 1e10

            try:
                res = minimize(mvf_short_negll, p0, args=(z2_c, r),
                              method='L-BFGS-B',
                              bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                              options={'maxiter': 5000, 'ftol': 1e-10})

                if res.fun < best_nll:
                    best_nll = res.fun
                    best_params = {
                        'rho': float(rho),
                        'omega_g': float(res.x[0]),
                        'alpha_g': float(res.x[1]),
                        'beta_g': float(res.x[2]),
                        'gamma_g': float(res.x[3]),
                        'persistence_short': float(res.x[1] + res.x[2] + 0.5 * res.x[3]),
                        'converged': bool(res.success),
                        'nll': float(res.fun),
                        'n_obs': T
                    }
            except Exception:
                continue

    return best_params


def forecast_mvf(r2, returns, params, rv_window=66):
    """
    One-step-ahead MVF forecast → σ²_{t+1|t} = exp(f_t) × g_{t+1|t}
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    r2_arr = np.ascontiguousarray(r2, dtype=np.float64)

    # Long-run factor
    f = compute_long_run_factor(r2_arr, params['rho'], rv_window)
    exp_f = np.exp(f)

    # Detrended r²
    z2 = r2_arr / exp_f
    z2 = np.maximum(z2, 1e-12)
    z2_c = np.ascontiguousarray(z2, dtype=np.float64)

    # Short-run filter
    g = mvf_short_run_filter(z2_c, r, params['omega_g'], params['alpha_g'],
                              params['beta_g'], params['gamma_g'])

    # One-step forecast for short-run component
    ind = 1.0 if r[-1] < 0 else 0.0
    g_next = (params['omega_g'] + params['alpha_g'] * z2[-1]
              + params['beta_g'] * g[-1]
              + params['gamma_g'] * ind * z2[-1])
    g_next = max(g_next, 1e-12)

    # Long-run: f_{t+1} ≈ f_t (very persistent)
    # Combined forecast
    forecast = exp_f[-1] * g_next
    return max(forecast, 1e-12)


# ============================================================
# Part C: Other model fitting (reused from K778)
# ============================================================

def fit_gjr_garch(returns):
    """GJR-GARCH(1,1) via quasi-MLE (Normal). Forecast: σ²."""
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
    for seed in range(4):
        np.random.seed(seed + 100)
        a0 = max(0.01, min(0.3, 0.05 + 0.03 * np.random.randn()))
        b0 = max(0.5, min(0.98, 0.88 + 0.04 * np.random.randn()))
        g0 = max(0.01, min(0.3, 0.08 + 0.04 * np.random.randn()))
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = rv * (1 - a0 - b0 - 0.5 * g0)
        res = minimize(gjr_negll, [max(1e-8, o0), a0, b0, g0], args=(r,),
                      method='L-BFGS-B',
                      bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                      options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res
    if best is None:
        return None
    return {
        'omega': float(best.x[0]), 'alpha': float(best.x[1]),
        'beta': float(best.x[2]), 'gamma': float(best.x[3]),
        'persistence': float(best.x[1] + best.x[2] + 0.5 * best.x[3])
    }


def fit_garch(returns):
    """GARCH(1,1) via quasi-MLE (Normal). Forecast: σ²."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 50:
        return None

    def garch_negll(params, r):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        sigma2 = garch_filter(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:]**2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rv = np.var(r)
    best = None
    best_nll = 1e10
    for seed in range(4):
        np.random.seed(seed + 200)
        a0 = max(0.01, min(0.3, 0.06 + 0.03 * np.random.randn()))
        b0 = max(0.5, min(0.98, 0.90 + 0.03 * np.random.randn()))
        if a0 + b0 >= 0.99:
            b0 = 0.98 - a0
        o0 = rv * (1 - a0 - b0)
        res = minimize(garch_negll, [max(1e-8, o0), a0, b0], args=(r,),
                      method='L-BFGS-B',
                      bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
                      options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res
    if best is None:
        return None
    return {
        'omega': float(best.x[0]), 'alpha': float(best.x[1]),
        'beta': float(best.x[2]),
        'persistence': float(best.x[1] + best.x[2])
    }


def fit_amem_r2(r2, r, max_attempts=4):
    """Fit AMEM-r² via Gamma MLE."""
    r2_arr = np.ascontiguousarray(r2, dtype=np.float64)
    r_arr = np.ascontiguousarray(r, dtype=np.float64)

    r2_mean = np.mean(r2_arr[r2_arr > 0]) if np.any(r2_arr > 0) else 1e-4
    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)
        omega0 = r2_mean * 0.05 * (1 + 0.3 * np.random.randn())
        alpha0 = max(0.01, min(0.4, 0.04 + 0.03 * np.random.randn()))
        beta0 = max(0.3, min(0.95, 0.87 + 0.04 * np.random.randn()))
        gamma0 = max(0.01, min(0.4, 0.08 + 0.05 * np.random.randn()))
        k0 = max(0.1, 0.8 + 0.3 * np.random.randn())
        if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
            beta0 = 0.97 - alpha0 - 0.5 * gamma0
        p0 = [max(1e-8, omega0), alpha0, beta0, max(0.01, gamma0), max(0.1, k0)]
        bounds = [(1e-10, None), (0, 0.9), (0, 0.999), (0, 0.9), (0.05, 100)]

        def amem_negloglik(params, r2, r):
            omega, alpha, beta, gamma, k = params
            if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or k <= 0:
                return 1e10
            if alpha + beta + 0.5 * gamma >= 1.0:
                return 1e10
            mu = amem_r2_filter(r2, r, omega, alpha, beta, gamma)
            r2_trim = r2[1:]
            mu_trim = mu[1:]
            valid = (mu_trim > 1e-12) & (r2_trim > 0)
            if valid.sum() < 10:
                return 1e10
            r2_v = r2_trim[valid]
            mu_v = mu_trim[valid]
            ll = (k * np.log(k / mu_v) + (k - 1) * np.log(r2_v)
                  - k * r2_v / mu_v - gammaln(k))
            total_ll = np.sum(ll)
            return -total_ll if np.isfinite(total_ll) else 1e10

        result = minimize(amem_negloglik, p0, args=(r2_arr, r_arr),
                         method='L-BFGS-B', bounds=bounds,
                         options={'maxiter': 5000, 'ftol': 1e-10})
        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    if best_result is None:
        return None

    res = best_result
    return {
        'omega': float(res.x[0]), 'alpha': float(res.x[1]),
        'beta': float(res.x[2]), 'gamma': float(res.x[3]),
        'k': float(res.x[4]),
        'persistence': float(res.x[1] + res.x[2] + 0.5 * res.x[3])
    }


def fit_har_r2(sq_ret):
    """HAR-r²: r²_{t+1} = β₀ + β₁×r²_d + β₂×r²_w + β₃×r²_m (OLS)"""
    x = sq_ret.copy()
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
    X = np.column_stack([np.ones(len(idx)), x[idx-1], ma5[idx-1], ma22[idx-1]])
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None
    Y, X = Y[valid_rows], X[valid_rows]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


# ============================================================
# Part D: Forecast functions (all → r²_{t+1})
# ============================================================

def forecast_gjr(returns, params):
    """One-step-ahead GJR-GARCH forecast → σ²_{t+1}"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega'] + (params['alpha'] + params['gamma'] * ind) * r[-1]**2
         + params['beta'] * sigma2[-1])
    return max(f, 1e-12)


def forecast_garch(returns, params):
    """One-step-ahead GARCH(1,1) forecast → σ²_{t+1}"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = garch_filter(r, params['omega'], params['alpha'], params['beta'])
    f = params['omega'] + params['alpha'] * r[-1]**2 + params['beta'] * sigma2[-1]
    return max(f, 1e-12)


def forecast_amem_r2(r2, r, params):
    """One-step-ahead AMEM-r² forecast → E[r²_{t+1}]"""
    mu = amem_r2_filter(r2, r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    indicator = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega'] + (params['alpha'] + params['gamma'] * indicator) * r2[-1]
         + params['beta'] * mu[-1])
    return max(f, 1e-12)


def forecast_har_r2(sq_ret, beta):
    """One-step-ahead HAR-r² forecast → E[r²_{t+1}]"""
    n = len(sq_ret)
    if n < 22:
        return None
    f = (beta[0] + beta[1] * sq_ret[-1] + beta[2] * np.mean(sq_ret[-5:])
         + beta[3] * np.mean(sq_ret[-22:]))
    return max(f, 1e-12)


# ============================================================
# Part E: Evaluation metrics
# ============================================================

def qlike(actual, predicted):
    """QLIKE loss: actual/predicted - log(actual/predicted) - 1"""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    valid = (a > 0) & (p > 0)
    a, p = a[valid], p[valid]
    if len(a) == 0:
        return np.nan
    return float(np.mean(a / p - np.log(a / p) - 1))


def pointwise_qlike(actual, predicted):
    """Pointwise QLIKE losses for DM test."""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    a = np.maximum(a, 1e-12)
    p = np.maximum(p, 1e-12)
    return a / p - np.log(a / p) - 1


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test (two-sided).
    H0: equal predictive ability.
    Returns DM stat, p-value, and Harvey-adjusted t-stat.
    """
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West, bandwidth ~ h)
    bw = max(1, h)
    gamma0 = np.mean((d - d_bar)**2)
    V = gamma0
    for lag in range(1, bw + 1):
        w = 1.0 - lag / (bw + 1)
        gamma_lag = np.mean((d[lag:] - d_bar) * (d[:-lag] - d_bar))
        V += 2 * w * gamma_lag
    V = max(V, 1e-20)

    dm = d_bar / np.sqrt(V / n)
    p_value = 2 * (1 - norm.cdf(abs(dm)))

    # Harvey, Leybourne, Newbold (1997) small-sample correction
    harvey_factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    harvey_t = dm * harvey_factor

    return float(dm), float(p_value), float(harvey_t)


# ============================================================
# Part F: Main OOS comparison
# ============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K781: Multiplicative Volatility Factor (MVF) Model")
    print("=" * 70)

    # ---- Data ----
    print("\n[1/5] Downloading SPY data...")
    spy = yf.download('SPY', start='2007-01-01', end='2026-12-31', progress=False)
    # Handle yfinance MultiIndex columns
    if 'Close' in spy.columns:
        close = spy['Close'].squeeze()
    elif ('Close', 'SPY') in spy.columns:
        close = spy[('Close', 'SPY')].squeeze()
    elif isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
        close = spy['Close'].squeeze()
    else:
        close = spy['Close'].squeeze()

    close = close.sort_index().dropna()
    ret_series = close.pct_change().dropna()

    returns = ret_series.values.astype(np.float64)
    r2 = returns ** 2
    dates = ret_series.index

    print(f"  SPY: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  N = {len(returns)}")

    # Descriptive stats
    print(f"\n  Descriptive stats (returns):")
    print(f"    Mean:   {returns.mean():.6f}")
    print(f"    Std:    {returns.std():.6f}")
    print(f"    Skew:   {pd.Series(returns).skew():.4f}")
    print(f"    Kurt:   {pd.Series(returns).kurtosis():.4f}")
    print(f"    r² mean: {r2.mean():.8f}")

    # ---- OOS setup ----
    min_window = 750  # ~3 years for MVF (needs 66-day rolling)
    refit_freq = 63   # quarterly refits
    n_total = len(returns)
    n_oos = n_total - min_window

    print(f"\n[2/5] OOS setup: min_window={min_window}, refit_freq={refit_freq}")
    print(f"  OOS period: {dates[min_window].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS size: {n_oos}")

    # Storage for forecasts
    models = ['MVF', 'GJR-GARCH', 'AMEM-r2', 'GARCH', 'HAR-r2']
    forecasts = {m: [] for m in models}
    actuals = []
    oos_dates = []

    # Track last fit params
    last_params = {m: None for m in models}
    last_fit_t = -refit_freq  # force first fit

    # Track full-sample params for reporting
    full_sample_params = {}

    print(f"\n[3/5] Running expanding window OOS...")

    n_refits = 0
    for t in range(min_window, n_total):
        # Refit check
        need_refit = (t - last_fit_t >= refit_freq) or (last_params['MVF'] is None)

        if need_refit:
            train_r = returns[:t]
            train_r2 = r2[:t]

            # 1. MVF
            mvf_params = fit_mvf(train_r, train_r2, max_attempts=3)
            if mvf_params is not None:
                last_params['MVF'] = mvf_params

            # 2. GJR-GARCH
            gjr_params = fit_gjr_garch(train_r)
            if gjr_params is not None:
                last_params['GJR-GARCH'] = gjr_params

            # 3. AMEM-r²
            amem_params = fit_amem_r2(train_r2, train_r, max_attempts=3)
            if amem_params is not None:
                last_params['AMEM-r2'] = amem_params

            # 4. GARCH
            garch_params = fit_garch(train_r)
            if garch_params is not None:
                last_params['GARCH'] = garch_params

            # 5. HAR-r²
            har_beta = fit_har_r2(train_r2)
            if har_beta is not None:
                last_params['HAR-r2'] = har_beta

            last_fit_t = t
            n_refits += 1

            if n_refits <= 3 or n_refits % 10 == 0:
                elapsed = time.time() - t0
                pct = (t - min_window) / n_oos * 100
                print(f"    Refit #{n_refits} at t={t} ({pct:.0f}%), elapsed {elapsed:.0f}s")

        # Generate forecasts using ALL data up to t
        # (params from last refit, but filter on full data up to t)
        train_r = returns[:t]
        train_r2 = r2[:t]

        # Actual (r²_{t+1} — the target we're forecasting)
        actual_r2 = r2[t]
        actuals.append(actual_r2)
        oos_dates.append(dates[t])

        # MVF forecast
        if last_params['MVF'] is not None:
            forecasts['MVF'].append(forecast_mvf(train_r2, train_r, last_params['MVF']))
        else:
            forecasts['MVF'].append(np.mean(train_r2))

        # GJR forecast
        if last_params['GJR-GARCH'] is not None:
            forecasts['GJR-GARCH'].append(forecast_gjr(train_r, last_params['GJR-GARCH']))
        else:
            forecasts['GJR-GARCH'].append(np.mean(train_r2))

        # AMEM-r² forecast
        if last_params['AMEM-r2'] is not None:
            forecasts['AMEM-r2'].append(forecast_amem_r2(
                np.ascontiguousarray(train_r2, dtype=np.float64),
                np.ascontiguousarray(train_r, dtype=np.float64),
                last_params['AMEM-r2']))
        else:
            forecasts['AMEM-r2'].append(np.mean(train_r2))

        # GARCH forecast
        if last_params['GARCH'] is not None:
            forecasts['GARCH'].append(forecast_garch(train_r, last_params['GARCH']))
        else:
            forecasts['GARCH'].append(np.mean(train_r2))

        # HAR-r² forecast
        if last_params['HAR-r2'] is not None:
            f_har = forecast_har_r2(train_r2, last_params['HAR-r2'])
            forecasts['HAR-r2'].append(f_har if f_har is not None else np.mean(train_r2))
        else:
            forecasts['HAR-r2'].append(np.mean(train_r2))

    elapsed_oos = time.time() - t0
    print(f"  Done. {n_refits} refits in {elapsed_oos:.0f}s")

    # Store last params as full sample params
    full_sample_params = {}
    if last_params['MVF'] is not None:
        full_sample_params['MVF'] = {k: v for k, v in last_params['MVF'].items()
                                      if k not in ['converged', 'nll', 'n_obs']}
    if last_params['GJR-GARCH'] is not None:
        full_sample_params['GJR-GARCH'] = last_params['GJR-GARCH']
    if last_params['AMEM-r2'] is not None:
        full_sample_params['AMEM-r2'] = last_params['AMEM-r2']
    if last_params['GARCH'] is not None:
        full_sample_params['GARCH'] = last_params['GARCH']

    # ---- Evaluation ----
    print(f"\n[4/5] Evaluation metrics (all on r² target)...")

    actuals = np.array(actuals)
    for m in models:
        forecasts[m] = np.array(forecasts[m])

    # QLIKE & Spearman
    results = {}
    print(f"\n  {'Model':<15} {'QLIKE':>8} {'Spearman':>10} {'Spearman p':>12}")
    print(f"  {'-'*45}")

    model_qlike = {}
    for m in models:
        q = qlike(actuals, forecasts[m])
        rho_s, p_s = spearmanr(actuals, forecasts[m])
        model_qlike[m] = q
        results[m] = {
            'QLIKE': round(q, 6),
            'Spearman_rho': round(float(rho_s), 4),
            'Spearman_p': round(float(p_s), 6)
        }
        print(f"  {m:<15} {q:8.6f} {rho_s:10.4f} {p_s:12.6f}")

    # Ranking
    ranking = sorted(model_qlike.items(), key=lambda x: x[1])
    print(f"\n  QLIKE Ranking (lower = better):")
    for rank, (m, q) in enumerate(ranking, 1):
        print(f"    #{rank}: {m} ({q:.6f})")

    # DM tests (all pairs vs best)
    print(f"\n  Diebold-Mariano tests (vs best: {ranking[0][0]}):")
    print(f"  {'Pair':<35} {'DM':>8} {'p-value':>10} {'Harvey t':>10} {'Harvey |t|>3?':>14}")
    print(f"  {'-'*77}")

    best_model = ranking[0][0]
    best_losses = pointwise_qlike(actuals, forecasts[best_model])

    dm_results = {}
    for m in models:
        if m == best_model:
            continue
        m_losses = pointwise_qlike(actuals, forecasts[m])
        dm_stat, dm_p, harvey_t = dm_test(m_losses, best_losses)
        harvey_pass = "PASS" if abs(harvey_t) > 3.0 else "FAIL"
        dm_results[f"{m} vs {best_model}"] = {
            'DM_stat': round(dm_stat, 4),
            'p_value': round(dm_p, 6),
            'Harvey_t': round(harvey_t, 4),
            'Harvey_pass': harvey_pass
        }
        print(f"  {m+' vs '+best_model:<35} {dm_stat:8.4f} {dm_p:10.6f} {harvey_t:10.4f} {harvey_pass:>14}")

    # Also do MVF vs each competitor specifically
    print(f"\n  DM tests: MVF vs each competitor:")
    print(f"  {'Pair':<35} {'DM':>8} {'p-value':>10} {'Harvey t':>10} {'Harvey |t|>3?':>14}")
    print(f"  {'-'*77}")

    mvf_losses = pointwise_qlike(actuals, forecasts['MVF'])
    dm_mvf_results = {}
    for m in models:
        if m == 'MVF':
            continue
        m_losses = pointwise_qlike(actuals, forecasts[m])
        dm_stat, dm_p, harvey_t = dm_test(mvf_losses, m_losses)
        harvey_pass = "PASS" if abs(harvey_t) > 3.0 else "FAIL"
        dm_mvf_results[f"MVF vs {m}"] = {
            'DM_stat': round(dm_stat, 4),
            'p_value': round(dm_p, 6),
            'Harvey_t': round(harvey_t, 4),
            'Harvey_pass': harvey_pass
        }
        sign = "<" if dm_stat < 0 else ">"
        print(f"  {'MVF vs '+m:<35} {dm_stat:8.4f} {dm_p:10.6f} {harvey_t:10.4f} {harvey_pass:>14}")

    # ---- MCS (proper stationary bootstrap) ----
    print(f"\n[5/5] Model Confidence Set (Hansen, Lunde, Nason 2011)...")

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
    from volpred.stats.mcs import model_confidence_set

    mcs_losses = {}
    for m in models:
        mcs_losses[m] = pointwise_qlike(actuals, forecasts[m])

    mcs_result = model_confidence_set(mcs_losses, alpha=0.10, n_boot=5000, seed=42)

    print(f"\n  MCS surviving models (α=0.10): {mcs_result['mcs_models']}")
    print(f"  MCS p-values:")
    for m, p in sorted(mcs_result['p_values'].items(), key=lambda x: -x[1]):
        in_mcs = "✓ IN MCS" if m in mcs_result['mcs_models'] else "✗ eliminated"
        print(f"    {m:<15}: p={p:.4f}  {in_mcs}")

    if mcs_result['eliminated']:
        print(f"  Elimination order:")
        for m, p in mcs_result['eliminated']:
            print(f"    {m} (p={p:.4f})")

    # ---- Regime analysis ----
    print(f"\n  Regime analysis (high vol = VIX > 20 equivalent, r²_66d > median)...")
    rv66 = pd.Series(r2).rolling(66, min_periods=1).mean().values
    rv66_oos = rv66[min_window:n_total]
    median_rv = np.median(rv66_oos)
    high_vol = rv66_oos > median_rv
    low_vol = ~high_vol

    print(f"\n  {'Model':<15} {'QLIKE(all)':>12} {'QLIKE(high)':>12} {'QLIKE(low)':>12}")
    print(f"  {'-'*51}")

    regime_results = {}
    for m in models:
        q_all = qlike(actuals, forecasts[m])
        q_high = qlike(actuals[high_vol], forecasts[m][high_vol])
        q_low = qlike(actuals[low_vol], forecasts[m][low_vol])
        regime_results[m] = {
            'QLIKE_all': round(q_all, 6),
            'QLIKE_high_vol': round(q_high, 6),
            'QLIKE_low_vol': round(q_low, 6)
        }
        print(f"  {m:<15} {q_all:12.6f} {q_high:12.6f} {q_low:12.6f}")

    # ---- Subsample stability ----
    print(f"\n  Subsample stability (3 equal splits):")
    split_size = n_oos // 3
    subsample_results = {}
    for i in range(3):
        start = i * split_size
        end = (i + 1) * split_size if i < 2 else n_oos
        period = f"{oos_dates[start].strftime('%Y')}-{oos_dates[end-1].strftime('%Y')}"
        sub_a = actuals[start:end]
        print(f"\n  Period {i+1}: {period} (n={end-start})")
        sub_ranking = {}
        for m in models:
            sub_f = forecasts[m][start:end]
            q = qlike(sub_a, sub_f)
            sub_ranking[m] = q
            print(f"    {m:<15}: QLIKE={q:.6f}")

        sub_ranked = sorted(sub_ranking.items(), key=lambda x: x[1])
        subsample_results[f"period_{i+1}_{period}"] = {
            m: round(q, 6) for m, q in sub_ranked
        }
        print(f"    Winner: {sub_ranked[0][0]}")

    # ---- Final summary ----
    total_time = time.time() - t0

    print(f"\n{'='*70}")
    print(f"K781 SUMMARY")
    print(f"{'='*70}")
    print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')} (n={n_oos})")
    print(f"  Refits: {n_refits}, Total time: {total_time:.0f}s")
    print(f"\n  QLIKE ranking:")
    for rank, (m, q) in enumerate(ranking, 1):
        in_mcs = "∈ MCS" if m in mcs_result['mcs_models'] else ""
        print(f"    #{rank}: {m:<15} QLIKE={q:.6f}  {in_mcs}")

    best = ranking[0][0]
    mvf_rank = [i+1 for i, (m, _) in enumerate(ranking) if m == 'MVF'][0]
    print(f"\n  Best model: {best}")
    print(f"  MVF rank: #{mvf_rank}")

    # Check if MVF beats GJR significantly
    mvf_vs_gjr = dm_mvf_results.get('MVF vs GJR-GARCH', {})
    if mvf_vs_gjr:
        sign = "better" if mvf_vs_gjr['DM_stat'] < 0 else "worse"
        print(f"  MVF vs GJR-GARCH: DM={mvf_vs_gjr['DM_stat']:.4f} ({sign}), Harvey t={mvf_vs_gjr['Harvey_t']:.4f} ({mvf_vs_gjr['Harvey_pass']})")

    if last_params['MVF'] is not None:
        print(f"\n  MVF final params:")
        for k, v in last_params['MVF'].items():
            if k in ['converged', 'nll', 'n_obs']:
                continue
            print(f"    {k}: {v:.6f}")

    # ---- Save results ----
    output = {
        'experiment_id': 'K781',
        'title': 'K781 MVF: Multiplicative Volatility Factor Model',
        'proposer': '文獻搜尋 J.Econometrics 2025',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'asset': 'SPY',
        'data_period': f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
        'n_total': int(n_total),
        'oos_period': f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
        'n_oos': int(n_oos),
        'n_refits': int(n_refits),
        'min_window': int(min_window),
        'refit_freq': int(refit_freq),
        'evaluation_target': 'r² (squared returns, Patton 2011 proxy-robust)',
        'models': {
            'MVF': '5 params (ρ, ω_g, α_g, β_g, γ_g): σ²=exp(f_t)×g_t, f=EWA of log-RV66, g=GJR on detrended r²',
            'GJR-GARCH': '4 params (ω, α, β, γ): standard GJR-GARCH(1,1)',
            'AMEM-r2': '5 params (ω, α, β, γ, k): Asymmetric MEM on r², Gamma innovations',
            'GARCH': '3 params (ω, α, β): standard GARCH(1,1)',
            'HAR-r2': '4 params (β₀, β₁, β₂, β₃): HAR on squared returns'
        },
        'full_sample_params': full_sample_params,
        'qlike_ranking': [{'rank': i+1, 'model': m, 'QLIKE': round(q, 6)}
                          for i, (m, q) in enumerate(ranking)],
        'metrics': results,
        'dm_tests_vs_best': dm_results,
        'dm_tests_mvf_vs_each': dm_mvf_results,
        'mcs': {
            'alpha': 0.10,
            'n_boot': 5000,
            'surviving_models': mcs_result['mcs_models'],
            'p_values': {m: round(p, 4) for m, p in mcs_result['p_values'].items()},
            'elimination_order': [(m, round(p, 4)) for m, p in mcs_result['eliminated']]
        },
        'regime_analysis': regime_results,
        'subsample_stability': subsample_results,
        'references': [
            'J. Econometrics 2025: Multiplicative Volatility Factor model',
            'Conrad (2025) MF2-GARCH, J. Applied Econometrics',
            'Engle, Ghysels & Sohn (2013) GARCH-MIDAS',
            'Patton (2011) J.Econometrics 160, QLIKE proxy-robust loss',
            'Hansen, Lunde & Nason (2011) Econometrica 79, MCS',
            'Glosten, Jagannathan, Runkle (1993) JoF 48, GJR-GARCH',
            'Engle & Gallo (2006) J.Econometrics 131, MEM/AMEM',
            'Corsi (2009) J.Financial Econometrics 7, HAR'
        ],
        'conclusion': '',  # filled below
        'runtime_seconds': round(total_time, 1)
    }

    # Build conclusion
    mvf_q = model_qlike['MVF']
    gjr_q = model_qlike['GJR-GARCH']
    amem_q = model_qlike['AMEM-r2']

    conclusion_parts = [
        f"MVF QLIKE={mvf_q:.6f} (rank #{mvf_rank}/5).",
        f"Best: {ranking[0][0]} ({ranking[0][1]:.6f}).",
    ]

    if 'MVF' in mcs_result['mcs_models']:
        conclusion_parts.append(f"MVF IN MCS (p={mcs_result['p_values']['MVF']:.4f}).")
    else:
        conclusion_parts.append(f"MVF ELIMINATED from MCS (p={mcs_result['p_values']['MVF']:.4f}).")

    if mvf_vs_gjr:
        if mvf_vs_gjr['DM_stat'] < 0 and mvf_vs_gjr['Harvey_pass'] == 'PASS':
            conclusion_parts.append(f"MVF SIGNIFICANTLY beats GJR (Harvey t={mvf_vs_gjr['Harvey_t']:.2f}, PASS).")
        elif mvf_vs_gjr['DM_stat'] > 0 and mvf_vs_gjr['Harvey_pass'] == 'PASS':
            conclusion_parts.append(f"GJR SIGNIFICANTLY beats MVF (Harvey t={mvf_vs_gjr['Harvey_t']:.2f}, PASS).")
        else:
            conclusion_parts.append(f"MVF vs GJR: NS (Harvey t={mvf_vs_gjr['Harvey_t']:.2f}, FAIL).")

    conclusion_parts.append(
        f"Multiplicative decomposition (slow exp(f) × fast GARCH) "
        f"{'improves' if mvf_q < gjr_q else 'does not improve'} over standard GJR."
    )

    output['conclusion'] = ' '.join(conclusion_parts)

    with open(RESULTS_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_PATH}")

    print(f"\n  CONCLUSION: {output['conclusion']}")
    print(f"\n  Runtime: {total_time:.0f}s")

    return output


if __name__ == '__main__':
    main()
