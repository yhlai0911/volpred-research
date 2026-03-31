#!/usr/bin/env python3
"""
K777: Multi-Target Fair Model Comparison — Each Model on Its Native Ground
==========================================================================
[提出: 用戶, 執行: Claude]

K770b used sqrt(2/π) conversion to unify targets, but this assumes Normality.
Real returns are fat-tailed (kurtosis >> 3), making the conversion biased.
This experiment evaluates each model on ALL 3 targets using EMPIRICAL conversions.

3 Evaluation Targets:
  Target 1: |r_{t+1}| (absolute return)
    - Native for: MEM, AMEM, HAR-ABS, EWMA-|r|
    - GARCH/EWMA-r²: use EMPIRICAL E[|r|/σ] from rolling 500d window

  Target 2: r²_{t+1} (squared return = variance proxy)
    - Native for: GJR-GARCH, HAR-SQ, EWMA-r²
    - MEM/AMEM/HAR-ABS/EWMA-|r|: use EMPIRICAL E[r²/|r|²] from rolling 500d

  Target 3: Rank correlation (distribution-free)
    - Spearman rank correlation between forecast and actual
    - No conversion needed — rank both forecast and actual
    - Robust to ANY distributional assumption

7 Models:
  1. AMEM (native: |r|) — Engle & Gallo (2006)
  2. MEM (native: |r|) — Engle & Gallo (2006)
  3. GJR-GARCH (native: σ²) — Glosten, Jagannathan, Runkle (1993)
  4. HAR-ABS (native: |r|) — Corsi (2009)
  5. HAR-SQ (native: r²) — Corsi (2009) with squared target
  6. EWMA-|r| (native: |r|) — exponential smoothing on |r|
  7. EWMA-r² (native: r²) — RiskMetrics EWMA on r²

Metrics per target:
  - QLIKE (primary) — Patton (2011) robust loss
  - MSE
  - Spearman rank correlation

FAIR ranking = average rank across all 3 targets.

References:
  - Engle, R.F. & Gallo, G.M. (2006) J.Econometrics 131, 3-27
  - Glosten, Jagannathan, Runkle (1993) JoF 48, 1779-1801
  - Corsi (2009) J.Financial Econometrics 7, 174-196
  - Patton (2011) J.Econometrics 160, 246-256
  - K770: OVERTURNED — QLIKE mismatch
  - K770b: Fixed with sqrt(2/π) but assumes Normality
  - K777: This experiment — EMPIRICAL conversions, 3 targets, rank-based

Data: SPY, 2007-2026, expanding window (min_window=500, refit_freq=63)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import norm, spearmanr
from datetime import datetime, timezone
from numba import njit
import warnings
import os
import sys
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = 'experiments/k777_multi_target_fair_results.json'


# ============================================================
# Part A: Model Implementations
# ============================================================

@njit(cache=True)
def mem_filter(x, omega, alpha, beta):
    """MEM(1,1) conditional mean: μ_t = ω + α×x_{t-1} + β×μ_{t-1}"""
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
    """AMEM(1,1): μ_t = ω + (α + γ×I_{r<0})×x_{t-1} + β×μ_{t-1}"""
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


# ============================================================
# MEM/AMEM fitting (Gamma MLE)
# ============================================================

def mem_negloglik(params, x, model='mem', r=None):
    """Gamma MLE for MEM/AMEM. ε_t = x_t/μ_t ~ Gamma(k, 1/k)"""
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
    return -total_ll if np.isfinite(total_ll) else 1e10


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
            alpha0 = max(0.01, min(0.5, 0.1 + 0.05 * np.random.randn()))
            beta0 = max(0.3, min(0.95, 0.85 + 0.05 * np.random.randn()))
            k0 = max(0.5, 2.0 + np.random.rand())
            if alpha0 + beta0 >= 0.99:
                beta0 = 0.98 - alpha0
            p0 = [max(1e-6, omega0), alpha0, beta0, k0]
            bounds = [(1e-8, None), (0, 0.9), (0, 0.99), (0.1, 100)]
            result = minimize(mem_negloglik, p0, args=(x, 'mem', None),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 5000, 'ftol': 1e-10})
        else:
            omega0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
            alpha0 = max(0.01, min(0.4, 0.05 + 0.03 * np.random.randn()))
            beta0 = max(0.3, min(0.95, 0.85 + 0.05 * np.random.randn()))
            gamma0 = max(0.01, min(0.4, 0.1 + 0.05 * np.random.randn()))
            k0 = max(0.5, 2.0 + np.random.rand())
            if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
                beta0 = 0.97 - alpha0 - 0.5 * gamma0
            p0 = [max(1e-6, omega0), alpha0, beta0, max(0.01, gamma0), k0]
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
        'params': params, 'converged': res.success,
        'nll': res.fun, 'n_obs': len(x)
    }


# ============================================================
# Benchmark Models
# ============================================================

def fit_har_abs(abs_ret):
    """
    HAR-ABS: |r_t| = β0 + β1×|r_{t-1}| + β5×MA5_{t-1}(|r|) + β22×MA22_{t-1}(|r|)
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


def har_abs_forecast(abs_ret, beta):
    """One-step-ahead HAR-ABS forecast → E[|r_{t+1}|]"""
    n = len(abs_ret)
    if n < 22:
        return None
    return max(beta[0] + beta[1]*abs_ret[-1] + beta[2]*np.mean(abs_ret[-5:])
               + beta[3]*np.mean(abs_ret[-22:]), 1e-10)


def fit_har_sq(sq_ret):
    """
    HAR-SQ: r²_t = β0 + β1×r²_{t-1} + β5×MA5_{t-1}(r²) + β22×MA22_{t-1}(r²)
    Native variance predictor using HAR framework.
    """
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


def har_sq_forecast(sq_ret, beta):
    """One-step-ahead HAR-SQ forecast → E[r²_{t+1}]"""
    n = len(sq_ret)
    if n < 22:
        return None
    return max(beta[0] + beta[1]*sq_ret[-1] + beta[2]*np.mean(sq_ret[-5:])
               + beta[3]*np.mean(sq_ret[-22:]), 1e-10)


def fit_gjr_garch(returns):
    """GJR-GARCH(1,1) via quasi-MLE. Forecast: σ²."""
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
        a0 = max(0.01, min(0.3, 0.05 + 0.03 * np.random.randn()))
        b0 = max(0.5, min(0.98, 0.88 + 0.04 * np.random.randn()))
        g0 = max(0.01, min(0.3, 0.08 + 0.04 * np.random.randn()))
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
    """One-step-ahead GJR-GARCH forecast → σ²_{t+1}"""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    return max(params['omega'] + (params['alpha'] + params['gamma'] * ind) * r[-1]**2
               + params['beta'] * sigma2[-1], 1e-12)


def ewma_forecast_var(returns, lam=0.94):
    """EWMA-r² forecast → σ²_{t+1}"""
    var = returns[0]**2
    for i in range(1, len(returns)):
        var = lam * var + (1 - lam) * returns[i]**2
    return max(var, 1e-12)


def ewma_forecast_abs(abs_ret, lam=0.94):
    """EWMA-|r| forecast → E[|r_{t+1}|]"""
    mu = abs_ret[0]
    for i in range(1, len(abs_ret)):
        mu = lam * mu + (1 - lam) * abs_ret[i]
    return max(mu, 1e-10)


# ============================================================
# Evaluation Metrics
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


def mse_metric(actual, predicted):
    return float(np.mean((np.array(actual) - np.array(predicted))**2))


def pointwise_qlike(actual, predicted):
    """Pointwise QLIKE losses for DM test."""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    ratio = a / p
    return ratio - np.log(ratio) - 1


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC. Negative → model 1 better."""
    d = np.array(loss1) - np.array(loss2)
    n = len(d)
    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h**(1/3) * n**(1/3))), n // 4))
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
    return float(stat), float(p_val)


# ============================================================
# Empirical Conversion Ratios
# ============================================================

def compute_empirical_ratios(returns, abs_ret, window=500):
    """
    Compute EMPIRICAL conversion ratios from rolling windows.

    Under Normality: E[|r|] = σ × sqrt(2/π) ≈ 0.7979
    Under fat tails:  E[|r|/σ] ≠ sqrt(2/π) — we estimate this empirically.

    Returns rolling arrays:
      ratio_abs_to_sigma: E[|r_t|/σ_t]  (for converting σ → |r|)
      ratio_sq_to_abs2:   E[r²_t/|r_t|²] = E[r²_t/(|r_t|)²] (always = 1 since |r|²=r²)
        → NOT useful. Instead: E[σ²/|r|²] or E[r²] / E[|r|]²

    Practically:
      - To convert GARCH σ → E[|r|]: multiply by empirical_ratio_abs_over_sigma
      - To convert MEM E[|r|] → E[r²]: multiply by empirical_ratio_sq_over_abs2
    """
    n = len(returns)
    # rolling stdev as proxy for σ
    rolling_std = pd.Series(returns).rolling(window, min_periods=100).std().values

    # Empirical E[|r|/σ] — how much of σ shows up as |r|
    ratio_abs_over_sigma = np.full(n, np.nan)
    # Empirical E[r²/|r|²] — always 1.0 since |r|²=r²
    # Instead compute E[r²] / E[|r|]² which captures the kurtosis effect
    ratio_sq_over_abs2 = np.full(n, np.nan)

    for t in range(window, n):
        w_ret = returns[t-window:t]
        w_abs = abs_ret[t-window:t]
        w_std = np.std(w_ret)
        if w_std > 1e-10:
            ratio_abs_over_sigma[t] = np.mean(w_abs) / w_std
        # E[r²] / E[|r|]² = E[X²] / (E[|X|])²
        # Under Normal: π/2 ≈ 1.571. Under fat tails: > π/2.
        mean_abs = np.mean(w_abs)
        if mean_abs > 1e-10:
            ratio_sq_over_abs2[t] = np.mean(w_ret**2) / (mean_abs**2)

    return ratio_abs_over_sigma, ratio_sq_over_abs2


# ============================================================
# Main Expanding Window Forecast (All 7 Models, 3 Targets)
# ============================================================

def expanding_window_all(returns, abs_ret, sq_ret, min_window=500, refit_freq=63):
    """
    Expanding window 1-day-ahead forecasts for 7 models.
    Returns raw native forecasts + empirical conversion ratios.
    """
    T = len(returns)
    n_oos = T - min_window
    if n_oos < 100:
        print(f"  WARNING: Only {n_oos} OOS obs")
        return None

    print(f"  Expanding window: T={T}, min_window={min_window}, OOS={n_oos}")

    # Native |r| forecasters
    fc_mem = np.full(n_oos, np.nan)
    fc_amem = np.full(n_oos, np.nan)
    fc_har_abs = np.full(n_oos, np.nan)
    fc_ewma_abs = np.full(n_oos, np.nan)

    # Native r² forecasters
    fc_gjr = np.full(n_oos, np.nan)         # σ² forecast
    fc_har_sq = np.full(n_oos, np.nan)       # r² forecast
    fc_ewma_var = np.full(n_oos, np.nan)     # σ² forecast

    # Actuals
    act_abs = np.full(n_oos, np.nan)
    act_sq = np.full(n_oos, np.nan)

    # Empirical ratios (rolling 500d)
    emp_abs_over_sigma = np.full(n_oos, np.nan)
    emp_sq_over_abs2 = np.full(n_oos, np.nan)

    # Cached params
    mem_params = amem_params = har_abs_beta = har_sq_beta = gjr_params = None
    last_refit = -refit_freq

    t_start = time.time()

    for i in range(n_oos):
        t = min_window + i
        if t >= T - 1:
            break

        # Actuals (next day)
        act_abs[i] = abs_ret[t + 1]
        act_sq[i] = sq_ret[t + 1]

        # History up to t
        x_hist = np.ascontiguousarray(abs_ret[:t+1], dtype=np.float64)
        r_hist = np.ascontiguousarray(returns[:t+1], dtype=np.float64)
        sq_hist = sq_ret[:t+1]

        # Compute empirical conversion ratios from the in-sample window
        window = min(500, t)
        w_ret = returns[t-window+1:t+1]
        w_abs = abs_ret[t-window+1:t+1]
        w_std = np.std(w_ret)
        if w_std > 1e-10:
            emp_abs_over_sigma[i] = np.mean(w_abs) / w_std
        w_mean_abs = np.mean(w_abs)
        if w_mean_abs > 1e-10:
            emp_sq_over_abs2[i] = np.mean(w_ret**2) / (w_mean_abs**2)

        # Refit
        if i - last_refit >= refit_freq or mem_params is None:
            last_refit = i
            mem_fit = fit_mem(x_hist, model='mem')
            if mem_fit and mem_fit['converged']:
                mem_params = mem_fit['params']
            amem_fit = fit_mem(x_hist, model='amem', r=r_hist)
            if amem_fit and amem_fit['converged']:
                amem_params = amem_fit['params']
            har_abs_beta = fit_har_abs(x_hist)
            har_sq_beta = fit_har_sq(sq_hist)
            gjr_params = fit_gjr_garch(r_hist)

        # --- MEM → E[|r|] ---
        if mem_params is not None:
            mu = mem_filter(x_hist, mem_params['omega'],
                           mem_params['alpha'], mem_params['beta'])
            fc = mem_params['omega'] + mem_params['alpha'] * x_hist[-1] + mem_params['beta'] * mu[-1]
            fc_mem[i] = max(fc, 1e-10)

        # --- AMEM → E[|r|] ---
        if amem_params is not None:
            mu = amem_filter(x_hist, r_hist, amem_params['omega'],
                            amem_params['alpha'], amem_params['beta'],
                            amem_params['gamma'])
            ind = 1.0 if r_hist[-1] < 0 else 0.0
            fc = (amem_params['omega']
                  + (amem_params['alpha'] + amem_params['gamma'] * ind) * x_hist[-1]
                  + amem_params['beta'] * mu[-1])
            fc_amem[i] = max(fc, 1e-10)

        # --- HAR-ABS → E[|r|] ---
        if har_abs_beta is not None:
            fc = har_abs_forecast(x_hist, har_abs_beta)
            if fc is not None:
                fc_har_abs[i] = fc

        # --- HAR-SQ → E[r²] ---
        if har_sq_beta is not None:
            fc = har_sq_forecast(sq_hist, har_sq_beta)
            if fc is not None:
                fc_har_sq[i] = fc

        # --- GJR-GARCH → σ² ---
        if gjr_params is not None:
            fc_gjr[i] = gjr_forecast_sigma2(r_hist, gjr_params)

        # --- EWMA-|r| → E[|r|] ---
        fc_ewma_abs[i] = ewma_forecast_abs(x_hist)

        # --- EWMA-r² → σ² ---
        fc_ewma_var[i] = ewma_forecast_var(r_hist)

        if (i + 1) % 500 == 0:
            elapsed = time.time() - t_start
            speed = (i + 1) / elapsed
            eta = (n_oos - i - 1) / speed
            print(f"    OOS step {i+1}/{n_oos}  ({speed:.0f} steps/s, ETA {eta:.0f}s)")

    elapsed = time.time() - t_start
    print(f"  Completed in {elapsed:.1f}s")

    # Valid mask: all models + positive actuals
    valid = (~np.isnan(act_abs) & (act_abs > 0) &
             ~np.isnan(fc_mem) & ~np.isnan(fc_amem) &
             ~np.isnan(fc_har_abs) & ~np.isnan(fc_har_sq) &
             ~np.isnan(fc_gjr) & ~np.isnan(fc_ewma_abs) &
             ~np.isnan(fc_ewma_var) &
             ~np.isnan(emp_abs_over_sigma) & ~np.isnan(emp_sq_over_abs2))

    n_valid = int(valid.sum())
    print(f"  Valid OOS: {n_valid}")
    if n_valid < 50:
        print("  ERROR: Too few valid observations")
        return None

    return {
        'act_abs': act_abs[valid],
        'act_sq': act_sq[valid],
        # Native |r| forecasters
        'fc_mem': fc_mem[valid],
        'fc_amem': fc_amem[valid],
        'fc_har_abs': fc_har_abs[valid],
        'fc_ewma_abs': fc_ewma_abs[valid],
        # Native r² forecasters
        'fc_gjr': fc_gjr[valid],          # σ² ≈ E[r²]
        'fc_har_sq': fc_har_sq[valid],
        'fc_ewma_var': fc_ewma_var[valid], # σ²
        # Empirical ratios
        'emp_abs_over_sigma': emp_abs_over_sigma[valid],
        'emp_sq_over_abs2': emp_sq_over_abs2[valid],
        'n_oos': n_valid,
    }


# ============================================================
# Target Evaluation
# ============================================================

ALL_MODELS = ['amem', 'mem', 'gjr', 'har_abs', 'har_sq', 'ewma_abs', 'ewma_var']
NATIVE_ABS = {'amem', 'mem', 'har_abs', 'ewma_abs'}  # native |r| predictors
NATIVE_VAR = {'gjr', 'har_sq', 'ewma_var'}            # native σ²/r² predictors


def build_target1_forecasts(data):
    """
    TARGET 1: |r_{t+1}|

    Native |r| models: use directly.
    σ²-native models: convert σ² → |r| via EMPIRICAL ratio.
      forecast_|r| = sqrt(σ²_forecast) × emp_abs_over_sigma[t]
    """
    act = data['act_abs']
    emp_ratio = data['emp_abs_over_sigma']

    forecasts = {}
    # Native |r| — use directly
    forecasts['amem'] = data['fc_amem']
    forecasts['mem'] = data['fc_mem']
    forecasts['har_abs'] = data['fc_har_abs']
    forecasts['ewma_abs'] = data['fc_ewma_abs']

    # σ² → |r| via empirical conversion
    # E[|r|] ≈ sqrt(E[σ²]) × empirical_E[|r|/σ]
    forecasts['gjr'] = np.sqrt(data['fc_gjr']) * emp_ratio
    forecasts['har_sq'] = np.sqrt(np.maximum(data['fc_har_sq'], 1e-12)) * emp_ratio
    forecasts['ewma_var'] = np.sqrt(data['fc_ewma_var']) * emp_ratio

    # Ensure positive
    for m in forecasts:
        forecasts[m] = np.maximum(forecasts[m], 1e-10)

    return act, forecasts


def build_target2_forecasts(data):
    """
    TARGET 2: r²_{t+1}

    Native σ²/r² models: use directly.
    |r|-native models: convert |r| → r² via EMPIRICAL ratio.
      forecast_r² = (forecast_|r|)² × emp_sq_over_abs2[t]
    """
    act = data['act_sq']
    emp_ratio = data['emp_sq_over_abs2']

    forecasts = {}
    # Native σ²/r² — use directly
    forecasts['gjr'] = data['fc_gjr']
    forecasts['har_sq'] = np.maximum(data['fc_har_sq'], 1e-12)
    forecasts['ewma_var'] = data['fc_ewma_var']

    # |r| → r² via empirical conversion
    # E[r²] ≈ E[|r|]² × empirical_E[r²]/E[|r|]²
    forecasts['amem'] = data['fc_amem']**2 * emp_ratio
    forecasts['mem'] = data['fc_mem']**2 * emp_ratio
    forecasts['har_abs'] = data['fc_har_abs']**2 * emp_ratio
    forecasts['ewma_abs'] = data['fc_ewma_abs']**2 * emp_ratio

    # Ensure positive
    for m in forecasts:
        forecasts[m] = np.maximum(forecasts[m], 1e-12)

    return act, forecasts


def evaluate_single_target(act, forecasts, target_name):
    """Evaluate all models on one target. Returns metrics + DM tests."""
    models = list(forecasts.keys())

    # Metrics
    metrics = {}
    qlike_losses = {}
    for m in models:
        pred = forecasts[m]
        q = qlike(act, pred)
        ms = mse_metric(act, pred)
        # Spearman rank correlation
        sp_r, sp_p = spearmanr(act, pred)
        metrics[m] = {
            'qlike': q,
            'mse': ms,
            'spearman_r': float(sp_r),
            'spearman_p': float(sp_p),
        }
        qlike_losses[m] = pointwise_qlike(act, pred)

    # DM tests (all pairs, QLIKE-based)
    dm_results = {}
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            stat, pval = dm_test(qlike_losses[m1], qlike_losses[m2])
            dm_results[f'{m1}_vs_{m2}'] = {
                'dm_stat': stat,
                'p_value': pval,
                'harvey_pass': bool(abs(stat) > 3.0),
                'better': m1 if stat < 0 else m2,
            }

    # Rankings (lower QLIKE = better)
    ranking_qlike = sorted(models, key=lambda m: metrics[m]['qlike'])
    # Rankings (higher Spearman = better)
    ranking_spearman = sorted(models, key=lambda m: -metrics[m]['spearman_r'])

    return {
        'target': target_name,
        'metrics': metrics,
        'dm_tests': dm_results,
        'ranking_qlike': ranking_qlike,
        'ranking_spearman': ranking_spearman,
    }


def evaluate_target3_rank(data):
    """
    TARGET 3: Rank Correlation (distribution-free)

    No conversion needed. Each model's raw forecast is ranked against
    actual |r_{t+1}| (or r²_{t+1} — rank is invariant to monotone transform).

    The model with highest Spearman rank correlation is the best "orderer"
    of volatility days.
    """
    # Use |r| as the actual — rank-invariant to r² since r² = |r|² is monotone
    act = data['act_abs']

    # Raw forecasts (no conversion — we just rank them)
    raw_forecasts = {
        'amem': data['fc_amem'],
        'mem': data['fc_mem'],
        'har_abs': data['fc_har_abs'],
        'ewma_abs': data['fc_ewma_abs'],
        'gjr': np.sqrt(data['fc_gjr']),       # sqrt(σ²) for same direction
        'har_sq': np.sqrt(np.maximum(data['fc_har_sq'], 1e-12)),
        'ewma_var': np.sqrt(data['fc_ewma_var']),
    }

    results = {}
    for m, pred in raw_forecasts.items():
        sp_r, sp_p = spearmanr(act, pred)
        results[m] = {
            'spearman_r': float(sp_r),
            'spearman_p': float(sp_p),
        }

    ranking = sorted(results.keys(), key=lambda m: -results[m]['spearman_r'])

    return {
        'target': 'rank_correlation',
        'metrics': results,
        'ranking': ranking,
    }


# ============================================================
# Fair Ranking = Average Rank Across All 3 Targets
# ============================================================

def compute_fair_ranking(target1_eval, target2_eval, target3_eval):
    """
    Fair ranking: average rank across:
      - Target 1 QLIKE rank
      - Target 2 QLIKE rank
      - Target 3 Spearman rank

    Rank 1 = best, 7 = worst.
    """
    models = ALL_MODELS

    # Target 1 QLIKE ranking (lower QLIKE = better = rank 1)
    t1_sorted = target1_eval['ranking_qlike']
    t1_ranks = {m: t1_sorted.index(m) + 1 for m in models}

    # Target 2 QLIKE ranking
    t2_sorted = target2_eval['ranking_qlike']
    t2_ranks = {m: t2_sorted.index(m) + 1 for m in models}

    # Target 3 Spearman ranking (higher Spearman = better = rank 1)
    t3_sorted = target3_eval['ranking']
    t3_ranks = {m: t3_sorted.index(m) + 1 for m in models}

    # Average rank
    avg_ranks = {}
    for m in models:
        avg_ranks[m] = {
            'target1_rank': t1_ranks[m],
            'target2_rank': t2_ranks[m],
            'target3_rank': t3_ranks[m],
            'avg_rank': (t1_ranks[m] + t2_ranks[m] + t3_ranks[m]) / 3.0,
        }

    fair_order = sorted(models, key=lambda m: avg_ranks[m]['avg_rank'])

    return avg_ranks, fair_order


# ============================================================
# Data Diagnostics
# ============================================================

def data_diagnostics(returns):
    """Descriptive stats to verify fat tails + check Normality."""
    from scipy.stats import kurtosis, skew, jarque_bera
    r = returns
    n = len(r)
    mean_r = np.mean(r)
    std_r = np.std(r)
    sk = skew(r)
    if hasattr(sk, 'item'):
        sk = sk.item()
    kt = kurtosis(r, fisher=True)  # excess kurtosis (Normal=0)
    if hasattr(kt, 'item'):
        kt = kt.item()
    jb_result = jarque_bera(r)
    jb_stat = float(jb_result.statistic) if hasattr(jb_result, 'statistic') else float(jb_result[0])
    jb_p = float(jb_result.pvalue) if hasattr(jb_result, 'pvalue') else float(jb_result[1])

    # Empirical E[|r|/σ] vs theoretical sqrt(2/π)
    abs_r = np.abs(r)
    empirical_ratio = np.mean(abs_r) / std_r
    theoretical_ratio = np.sqrt(2/np.pi)
    ratio_diff_pct = (empirical_ratio - theoretical_ratio) / theoretical_ratio * 100

    # E[r²] / E[|r|]² vs theoretical π/2
    empirical_moment_ratio = np.mean(r**2) / (np.mean(abs_r)**2)
    theoretical_moment_ratio = np.pi / 2
    moment_diff_pct = (empirical_moment_ratio - theoretical_moment_ratio) / theoretical_moment_ratio * 100

    return {
        'n_obs': n,
        'mean': float(mean_r),
        'std': float(std_r),
        'skewness': sk,
        'excess_kurtosis': kt,
        'jarque_bera_stat': jb_stat,
        'jarque_bera_p': jb_p,
        'normality_rejected': bool(jb_p < 0.05),
        'empirical_abs_over_sigma': float(empirical_ratio),
        'theoretical_abs_over_sigma': float(theoretical_ratio),
        'ratio_diff_pct': float(ratio_diff_pct),
        'empirical_sq_over_abs2': float(empirical_moment_ratio),
        'theoretical_sq_over_abs2': float(theoretical_moment_ratio),
        'moment_diff_pct': float(moment_diff_pct),
    }


# ============================================================
# Main
# ============================================================

def run_experiment():
    print("=" * 70)
    print("K777: Multi-Target Fair Model Comparison")
    print("=" * 70)

    # --- Data ---
    print("\n[1/5] Downloading SPY data...")
    spy = yf.download('SPY', start='2007-01-01', end='2026-12-31',
                      progress=False, auto_adjust=True)
    if len(spy) < 1000:
        print("ERROR: Insufficient data")
        return

    close = spy['Close']
    if hasattr(close, 'columns'):
        close = close.iloc[:, 0]  # multi-level columns from yfinance
    returns = close.pct_change().dropna().values.flatten()
    abs_ret = np.abs(returns)
    sq_ret = returns**2

    dates = spy.index[1:]  # dates aligned with returns

    print(f"  Data: SPY, {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Total observations: {len(returns)}")

    # --- Diagnostics ---
    print("\n[2/5] Data Diagnostics (checking Normality assumption)...")
    diag = data_diagnostics(returns)
    print(f"  Mean: {diag['mean']:.6f}")
    print(f"  Std:  {diag['std']:.6f}")
    print(f"  Skewness: {diag['skewness']:.3f}")
    print(f"  Excess Kurtosis: {diag['excess_kurtosis']:.3f}  (Normal=0)")
    print(f"  Jarque-Bera p: {diag['jarque_bera_p']:.2e}  → Normality {'REJECTED' if diag['normality_rejected'] else 'NOT rejected'}")
    print(f"\n  E[|r|/σ] empirical: {diag['empirical_abs_over_sigma']:.4f}")
    print(f"  E[|r|/σ] Normal:    {diag['theoretical_abs_over_sigma']:.4f}")
    print(f"  → Diff: {diag['ratio_diff_pct']:+.2f}%  ({'BIASED' if abs(diag['ratio_diff_pct']) > 2 else 'OK'})")
    print(f"\n  E[r²]/E[|r|]² empirical: {diag['empirical_sq_over_abs2']:.4f}")
    print(f"  E[r²]/E[|r|]² Normal:    {diag['theoretical_sq_over_abs2']:.4f}")
    print(f"  → Diff: {diag['moment_diff_pct']:+.2f}%  ({'BIASED' if abs(diag['moment_diff_pct']) > 2 else 'OK'})")

    # --- Expanding Window ---
    print("\n[3/5] Expanding Window Forecasting (7 models)...")
    data = expanding_window_all(returns, abs_ret, sq_ret, min_window=500, refit_freq=63)
    if data is None:
        print("ERROR: Expanding window failed")
        return

    # Report empirical ratio summary
    emp_abs = data['emp_abs_over_sigma']
    emp_sq = data['emp_sq_over_abs2']
    print(f"\n  Rolling empirical E[|r|/σ]: mean={np.mean(emp_abs):.4f}, "
          f"std={np.std(emp_abs):.4f}, range=[{np.min(emp_abs):.4f}, {np.max(emp_abs):.4f}]")
    print(f"  Rolling empirical E[r²]/E[|r|]²: mean={np.mean(emp_sq):.4f}, "
          f"std={np.std(emp_sq):.4f}, range=[{np.min(emp_sq):.4f}, {np.max(emp_sq):.4f}]")
    print(f"  Normal assumption would use: sqrt(2/π)={np.sqrt(2/np.pi):.4f} and π/2={np.pi/2:.4f}")

    # --- Evaluate 3 Targets ---
    print("\n[4/5] Evaluating on 3 Targets...")

    # Target 1: |r_{t+1}|
    print("\n--- TARGET 1: |r_{t+1}| (absolute return) ---")
    act1, fc1 = build_target1_forecasts(data)
    t1_eval = evaluate_single_target(act1, fc1, 'abs_return')
    print(f"  QLIKE ranking: {' > '.join(t1_eval['ranking_qlike'])}")
    for m in t1_eval['ranking_qlike']:
        met = t1_eval['metrics'][m]
        native = "NATIVE" if m in NATIVE_ABS else "converted"
        print(f"    {m:12s}: QLIKE={met['qlike']:.6f}  MSE={met['mse']:.2e}  "
              f"Spearman={met['spearman_r']:.4f}  [{native}]")

    # Target 2: r²_{t+1}
    print("\n--- TARGET 2: r²_{t+1} (squared return) ---")
    act2, fc2 = build_target2_forecasts(data)
    t2_eval = evaluate_single_target(act2, fc2, 'squared_return')
    print(f"  QLIKE ranking: {' > '.join(t2_eval['ranking_qlike'])}")
    for m in t2_eval['ranking_qlike']:
        met = t2_eval['metrics'][m]
        native = "NATIVE" if m in NATIVE_VAR else "converted"
        print(f"    {m:12s}: QLIKE={met['qlike']:.6f}  MSE={met['mse']:.2e}  "
              f"Spearman={met['spearman_r']:.4f}  [{native}]")

    # Target 3: Rank Correlation
    print("\n--- TARGET 3: Rank Correlation (distribution-free) ---")
    t3_eval = evaluate_target3_rank(data)
    print(f"  Spearman ranking: {' > '.join(t3_eval['ranking'])}")
    for m in t3_eval['ranking']:
        met = t3_eval['metrics'][m]
        print(f"    {m:12s}: Spearman={met['spearman_r']:.4f}  (p={met['spearman_p']:.2e})")

    # --- Fair Ranking ---
    print("\n[5/5] Fair Ranking (average rank across 3 targets)...")
    avg_ranks, fair_order = compute_fair_ranking(t1_eval, t2_eval, t3_eval)
    print(f"\n  {'Model':12s}  {'T1(|r|)':>8s}  {'T2(r²)':>8s}  {'T3(Rank)':>8s}  {'AvgRank':>8s}")
    print(f"  {'-'*52}")
    for m in fair_order:
        r = avg_ranks[m]
        print(f"  {m:12s}  {r['target1_rank']:>8d}  {r['target2_rank']:>8d}  "
              f"{r['target3_rank']:>8d}  {r['avg_rank']:>8.2f}")

    # DM test: best model vs each other (on each target)
    best_model = fair_order[0]
    print(f"\n  FAIR WINNER: {best_model}")
    print(f"\n  DM tests for {best_model} vs others:")

    for target_name, t_eval in [('T1(|r|)', t1_eval), ('T2(r²)', t2_eval)]:
        print(f"\n  {target_name}:")
        for m in fair_order[1:]:
            key1 = f'{best_model}_vs_{m}'
            key2 = f'{m}_vs_{best_model}'
            if key1 in t_eval['dm_tests']:
                dm = t_eval['dm_tests'][key1]
                stat = dm['dm_stat']
            elif key2 in t_eval['dm_tests']:
                dm = t_eval['dm_tests'][key2]
                stat = -dm['dm_stat']  # flip
            else:
                continue
            sig = "★★★" if abs(stat) > 3.0 else ("★★" if abs(stat) > 2.0 else ("★" if abs(stat) > 1.64 else ""))
            direction = "BETTER" if stat < 0 else "WORSE"
            print(f"    vs {m:12s}: DM={stat:+.3f}  p={dm['p_value']:.4f}  "
                  f"Harvey={'PASS' if abs(stat)>3.0 else 'fail'}  {sig}")

    # --- Normality Bias Assessment ---
    print("\n" + "=" * 70)
    print("NORMALITY BIAS ASSESSMENT")
    print("=" * 70)

    # Compare rankings: Target 1 (where |r| models have home advantage)
    # vs Target 2 (where σ² models have home advantage)
    t1_abs_ranks = [t1_eval['ranking_qlike'].index(m)+1 for m in NATIVE_ABS]
    t1_var_ranks = [t1_eval['ranking_qlike'].index(m)+1 for m in NATIVE_VAR]
    t2_abs_ranks = [t2_eval['ranking_qlike'].index(m)+1 for m in NATIVE_ABS]
    t2_var_ranks = [t2_eval['ranking_qlike'].index(m)+1 for m in NATIVE_VAR]

    print(f"\n  |r|-native models avg rank: T1(home)={np.mean(t1_abs_ranks):.2f}, T2(away)={np.mean(t2_abs_ranks):.2f}")
    print(f"  σ²-native models avg rank:  T1(away)={np.mean(t1_var_ranks):.2f}, T2(home)={np.mean(t2_var_ranks):.2f}")
    print(f"\n  Home advantage = better rank on native target?")
    abs_home_adv = np.mean(t2_abs_ranks) - np.mean(t1_abs_ranks)  # positive = home better
    var_home_adv = np.mean(t1_var_ranks) - np.mean(t2_var_ranks)
    print(f"  |r|-native home advantage: {abs_home_adv:+.2f} ranks")
    print(f"  σ²-native home advantage:  {var_home_adv:+.2f} ranks")

    # --- Save Results ---
    results = {
        'experiment_id': 'K777',
        'title': 'Multi-Target Fair Model Comparison — Each Model on Its Native Ground',
        'proposer': '用戶',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance SPY 2007-2026',
        'n_oos': data['n_oos'],
        'min_window': 500,
        'refit_freq': 63,
        'diagnostics': diag,
        'empirical_ratios': {
            'abs_over_sigma_mean': float(np.mean(emp_abs)),
            'abs_over_sigma_std': float(np.std(emp_abs)),
            'sq_over_abs2_mean': float(np.mean(emp_sq)),
            'sq_over_abs2_std': float(np.std(emp_sq)),
            'normal_abs_over_sigma': float(np.sqrt(2/np.pi)),
            'normal_sq_over_abs2': float(np.pi/2),
        },
        'target1_abs_return': {
            'metrics': t1_eval['metrics'],
            'dm_tests': t1_eval['dm_tests'],
            'ranking_qlike': t1_eval['ranking_qlike'],
            'ranking_spearman': t1_eval['ranking_spearman'],
        },
        'target2_squared_return': {
            'metrics': t2_eval['metrics'],
            'dm_tests': t2_eval['dm_tests'],
            'ranking_qlike': t2_eval['ranking_qlike'],
            'ranking_spearman': t2_eval['ranking_spearman'],
        },
        'target3_rank_correlation': {
            'metrics': t3_eval['metrics'],
            'ranking': t3_eval['ranking'],
        },
        'fair_ranking': {
            'model_ranks': avg_ranks,
            'order': fair_order,
            'winner': fair_order[0],
        },
        'normality_bias': {
            'abs_native_home_advantage': float(abs_home_adv),
            'var_native_home_advantage': float(var_home_adv),
            'normality_rejected': diag['normality_rejected'],
            'excess_kurtosis': diag['excess_kurtosis'],
            'conversion_bias_abs_pct': diag['ratio_diff_pct'],
            'conversion_bias_sq_pct': diag['moment_diff_pct'],
        },
        'references': [
            'Engle & Gallo (2006) J.Econometrics 131, MEM framework',
            'Glosten, Jagannathan, Runkle (1993) JoF 48, GJR-GARCH',
            'Corsi (2009) J.Financial Econometrics 7, HAR model',
            'Patton (2011) J.Econometrics 160, QLIKE robust loss',
            'K770: OVERTURNED — QLIKE target mismatch',
            'K770b: Fixed with sqrt(2/pi) — assumes Normality',
        ],
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_PATH}")

    # Final Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n  FAIR WINNER: {fair_order[0]} (avg rank {avg_ranks[fair_order[0]]['avg_rank']:.2f})")
    print(f"  Runner-up:   {fair_order[1]} (avg rank {avg_ranks[fair_order[1]]['avg_rank']:.2f})")
    print(f"  Worst:       {fair_order[-1]} (avg rank {avg_ranks[fair_order[-1]]['avg_rank']:.2f})")
    print(f"\n  Normality assumption: {'REJECTED (kurtosis={:.1f})'.format(diag['excess_kurtosis'])}")
    print(f"  Empirical conversion bias: |r|/σ = {diag['ratio_diff_pct']:+.2f}%, "
          f"r²/|r|² = {diag['moment_diff_pct']:+.2f}%")
    print(f"\n  This result is FAIR because:")
    print(f"    - Each model evaluated on ALL 3 targets (no home-field advantage)")
    print(f"    - EMPIRICAL conversions (not Normal assumption)")
    print(f"    - Rank correlation is completely distribution-free")

    return results


if __name__ == '__main__':
    results = run_experiment()
