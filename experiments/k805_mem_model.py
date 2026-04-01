#!/usr/bin/env python3
"""
K805: MEM(1,1) Comprehensive Evaluation — r² and |r| Targets
=============================================================
[提出: 用戶, 執行: Claude]

Background:
  - K778 tested MEM-r² natively but only showed GJR dominance on full OOS (2008-2026)
  - K782 showed proxy > model (HAR wins on |r| but loses on r²)
  - K770b confirmed AMEM beating HAR-ABS legitimately on |r| target
  - This experiment does a CLEAN head-to-head with FOCUSED OOS (2023-2025)

Models:
  1. MEM(1,1) on r²:  μ_t = ω + α × r²_{t-1} + β × μ_{t-1}, ε ~ Gamma(k, 1/k)
  2. MEM(1,1) on |r|: μ_t = ω + α × |r_{t-1}| + β × μ_{t-1}, ε ~ Gamma(k, 1/k)
  3. AMEM(1,1) on r²: μ_t = ω + (α + γ·I_{r<0}) × r²_{t-1} + β × μ_{t-1}
  4. AMEM(1,1) on |r|: μ_t = ω + (α + γ·I_{r<0}) × |r_{t-1}| + β × μ_{t-1}
  5. GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0}) × r²_{t-1} + β × σ²_{t-1}
  6. GARCH(1,1): σ²_t = ω + α × r²_{t-1} + β × σ²_{t-1}

Evaluation (Patton 2011 standard):
  - QLIKE on r² (proxy-robust: r² is unbiased for σ²)
  - Spearman rank correlation with r²_{t+1}
  - DM test with Harvey (2016) t>3.0 threshold
  - Also: QLIKE/Spearman on |r| target for fair comparison

Design:
  - Asset: SPY
  - Data: 2007-01-01 to present (expanding window)
  - OOS: 2023-01-01 to 2024-12-31
  - Refit: every 63 trading days
  - Min IS window: 500 obs

References:
  - Engle & Gallo (2006) J.Econometrics 131 — MEM framework
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - Patton (2011) J.Econometrics 160 — QLIKE proxy-robust loss
  - Corsi (2009) J.Financial Econometrics 7 — HAR
  - Harvey (2016) JoF — t>3.0 threshold
  - K778: MEM-r² native — GJR > AMEM-r² (DM=3.78, Harvey PASS)
  - K782: proxy > model — HAR wins |r| but loses r²
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import spearmanr
from datetime import datetime, timezone
from numba import njit
import warnings
import os
import sys
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = 'experiments/k805_mem_model_results.json'

# ============================================================
# Part A: Numba-accelerated filters
# ============================================================

@njit(cache=True)
def mem_filter(x, omega, alpha, beta):
    """
    MEM(1,1) conditional mean recursion:
        μ_t = ω + α × x_{t-1} + β × μ_{t-1}
    x can be r² or |r| (any positive series).
    """
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 1e-6
    for t in range(1, T):
        mu[t] = omega + alpha * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-12:
            mu[t] = 1e-12
    return mu


@njit(cache=True)
def amem_filter(x, r_sign, omega, alpha, beta, gamma):
    """
    AMEM(1,1) conditional mean with leverage:
        μ_t = ω + (α + γ × I_{r<0}) × x_{t-1} + β × μ_{t-1}
    x: positive series (r² or |r|)
    r_sign: raw returns for sign indicator
    """
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 1e-6
    for t in range(1, T):
        indicator = 1.0 if r_sign[t-1] < 0 else 0.0
        mu[t] = omega + (alpha + gamma * indicator) * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-12:
            mu[t] = 1e-12
    return mu


@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1) variance filter. Returns σ²."""
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
    """GARCH(1,1) variance filter. Returns σ²."""
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


# ============================================================
# Part B: MLE fitting functions
# ============================================================

def mem_negloglik(params, x, model_type='mem', r_sign=None):
    """
    Gamma MLE for MEM / AMEM.
    ε_t = x_t / μ_t ~ Gamma(k, 1/k), E[ε]=1, Var[ε]=1/k

    Log-likelihood per obs:
        k*log(k) - log(Γ(k)) + (k-1)*log(ε_t) - k*ε_t
      = k*log(k/μ_t) + (k-1)*log(x_t) - k*x_t/μ_t - log(Γ(k))
    """
    if model_type == 'mem':
        omega, alpha, beta, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or k <= 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        mu = mem_filter(x, omega, alpha, beta)
    elif model_type == 'amem':
        omega, alpha, beta, gamma, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or k <= 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        mu = amem_filter(x, r_sign, omega, alpha, beta, gamma)
    else:
        return 1e10

    # skip first obs (initialization)
    x_trim = x[1:]
    mu_trim = mu[1:]
    valid = (mu_trim > 1e-12) & (x_trim > 0)
    if valid.sum() < 10:
        return 1e10

    x_v = x_trim[valid]
    mu_v = mu_trim[valid]

    ll = (k * np.log(k / mu_v) + (k - 1) * np.log(x_v)
          - k * x_v / mu_v - gammaln(k))
    total_ll = np.sum(ll)
    return -total_ll if np.isfinite(total_ll) else 1e10


def fit_mem(x, model_type='mem', r_sign=None, max_attempts=5):
    """Fit MEM or AMEM via Gamma MLE with multiple restarts."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    if r_sign is not None:
        r_sign = np.ascontiguousarray(r_sign, dtype=np.float64)

    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 1e-4
    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)
        if model_type == 'mem':
            omega0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
            alpha0 = max(0.01, min(0.5, 0.08 + 0.04 * np.random.randn()))
            beta0 = max(0.3, min(0.95, 0.87 + 0.03 * np.random.randn()))
            k0 = max(0.1, 0.5 + 0.3 * np.random.randn())
            if alpha0 + beta0 >= 0.99:
                beta0 = 0.98 - alpha0
            p0 = [max(1e-8, omega0), alpha0, beta0, max(0.1, k0)]
            bounds = [(1e-10, None), (0, 0.9), (0, 0.999), (0.05, 50)]
            result = minimize(mem_negloglik, p0, args=(x, 'mem', None),
                              method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 5000, 'ftol': 1e-10})
        else:  # amem
            omega0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
            alpha0 = max(0.01, min(0.4, 0.04 + 0.02 * np.random.randn()))
            beta0 = max(0.3, min(0.95, 0.87 + 0.03 * np.random.randn()))
            gamma0 = max(0.01, min(0.4, 0.08 + 0.04 * np.random.randn()))
            k0 = max(0.1, 0.5 + 0.3 * np.random.randn())
            if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
                beta0 = 0.97 - alpha0 - 0.5 * gamma0
            p0 = [max(1e-8, omega0), alpha0, beta0, max(0.01, gamma0), max(0.1, k0)]
            bounds = [(1e-10, None), (0, 0.9), (0, 0.999), (0, 0.9), (0.05, 50)]
            result = minimize(mem_negloglik, p0, args=(x, 'amem', r_sign),
                              method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 5000, 'ftol': 1e-10})

        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    return best_result


def fit_gjr(r):
    """Fit GJR-GARCH(1,1) via Gaussian MLE."""
    r = np.ascontiguousarray(r, dtype=np.float64)

    def negloglik(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        sigma2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + r**2 / sigma2)
        total = np.sum(ll[1:])
        return -total if np.isfinite(total) else 1e10

    var_r = np.var(r)
    best_result = None
    best_nll = 1e10
    for attempt in range(4):
        np.random.seed(100 + attempt)
        omega0 = var_r * 0.05 * (1 + 0.2 * np.random.randn())
        alpha0 = max(0.01, 0.05 + 0.03 * np.random.randn())
        beta0 = max(0.5, min(0.98, 0.88 + 0.03 * np.random.randn()))
        gamma0 = max(0.01, 0.1 + 0.05 * np.random.randn())
        if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
            beta0 = 0.97 - alpha0 - 0.5 * gamma0
        p0 = [max(1e-8, omega0), alpha0, beta0, max(0.01, gamma0)]
        bounds = [(1e-10, None), (0, 0.5), (0.3, 0.999), (0, 0.5)]
        result = minimize(negloglik, p0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 5000, 'ftol': 1e-10})
        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    return best_result


def fit_garch(r):
    """Fit GARCH(1,1) via Gaussian MLE."""
    r = np.ascontiguousarray(r, dtype=np.float64)

    def negloglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        sigma2 = garch_filter(r, omega, alpha, beta)
        ll = -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + r**2 / sigma2)
        total = np.sum(ll[1:])
        return -total if np.isfinite(total) else 1e10

    var_r = np.var(r)
    best_result = None
    best_nll = 1e10
    for attempt in range(4):
        np.random.seed(200 + attempt)
        omega0 = var_r * 0.05 * (1 + 0.2 * np.random.randn())
        alpha0 = max(0.01, 0.08 + 0.04 * np.random.randn())
        beta0 = max(0.5, min(0.98, 0.88 + 0.03 * np.random.randn()))
        if alpha0 + beta0 >= 0.99:
            beta0 = 0.98 - alpha0
        p0 = [max(1e-8, omega0), alpha0, beta0]
        bounds = [(1e-10, None), (0, 0.5), (0.3, 0.999)]
        result = minimize(negloglik, p0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 5000, 'ftol': 1e-10})
        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    return best_result


# ============================================================
# Part C: Evaluation functions
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss (Patton 2011): L = actual/forecast - log(actual/forecast) - 1"""
    valid = (forecast > 0) & (actual > 0)
    a = actual[valid]
    f = forecast[valid]
    return np.mean(a / f - np.log(a / f) - 1)


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test with HAC variance (Newey-West).
    Returns DM statistic, p-value, and whether |t| > 3.0 (Harvey threshold).
    Negative DM → model 1 is better.
    """
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # Newey-West HAC variance
    max_lag = int(np.ceil(n ** (1/3)))
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0.0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_j = np.mean((d[lag:] - d_bar) * (d[:-lag] - d_bar))
        gamma_sum += 2 * w * gamma_j

    var_d = gamma_0 + gamma_sum
    if var_d <= 0:
        var_d = gamma_0

    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0, False

    dm_stat = d_bar / se
    from scipy.stats import norm
    p_value = 2 * (1 - norm.cdf(abs(dm_stat)))
    harvey_pass = abs(dm_stat) > 3.0

    return dm_stat, p_value, harvey_pass


def qlike_loss_array(actual, forecast):
    """Per-observation QLIKE loss for DM test."""
    valid = (forecast > 0) & (actual > 0)
    loss = np.full(len(actual), np.nan)
    a = actual[valid]
    f = forecast[valid]
    loss[valid] = a / f - np.log(a / f) - 1
    return loss


# ============================================================
# Part D: Main experiment
# ============================================================

def main():
    print("=" * 70)
    print("K805: MEM(1,1) Comprehensive Evaluation — r² and |r| Targets")
    print("=" * 70)

    # --- Data ---
    print("\n[1/6] Downloading SPY data...")
    spy = yf.download('SPY', start='2007-01-01', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.sort_index()
    # yfinance >= 0.2.31 returns adjusted prices in 'Close' by default
    price_col = 'Adj Close' if 'Adj Close' in spy.columns else 'Close'
    r = spy[price_col].pct_change().dropna().values
    dates = spy.index[1:]  # dates aligned with returns

    r2 = r ** 2  # squared return (variance proxy)
    abs_r = np.abs(r)  # absolute return (volatility proxy)

    print(f"  Total obs: {len(r)}")
    print(f"  Date range: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")

    # --- Diagnostics ---
    print("\n[2/6] Data diagnostics...")
    from scipy.stats import skew, kurtosis
    diag = {
        'n_obs': int(len(r)),
        'mean_r': float(np.mean(r)),
        'std_r': float(np.std(r)),
        'mean_r2': float(np.mean(r2)),
        'std_r2': float(np.std(r2)),
        'skewness_r2': float(skew(r2)),
        'kurtosis_r2': float(kurtosis(r2)),
        'mean_abs_r': float(np.mean(abs_r)),
        'std_abs_r': float(np.std(abs_r)),
        'skewness_abs_r': float(skew(abs_r)),
        'kurtosis_abs_r': float(kurtosis(abs_r)),
    }
    print(f"  Mean r²: {diag['mean_r2']:.6e}, Std r²: {diag['std_r2']:.6e}")
    print(f"  Skewness r²: {diag['skewness_r2']:.2f}, Kurtosis r²: {diag['kurtosis_r2']:.2f}")
    print(f"  Mean |r|: {diag['mean_abs_r']:.6f}, Std |r|: {diag['std_abs_r']:.6f}")

    # --- OOS setup ---
    oos_start = pd.Timestamp('2023-01-01')
    oos_end = pd.Timestamp('2024-12-31')
    refit_freq = 63
    min_window = 500

    dates_series = pd.DatetimeIndex(dates)
    oos_mask = (dates_series >= oos_start) & (dates_series <= oos_end)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)

    print(f"\n[3/6] OOS period: {oos_start.strftime('%Y-%m-%d')} to {oos_end.strftime('%Y-%m-%d')}")
    print(f"  OOS obs: {n_oos}")
    print(f"  First OOS index: {oos_indices[0]}, Last: {oos_indices[-1]}")

    # --- Expanding window refit schedule ---
    refit_points = list(range(oos_indices[0], oos_indices[-1] + 1, refit_freq))
    if oos_indices[-1] not in refit_points:
        refit_points.append(oos_indices[-1])
    n_refits = len(refit_points)
    print(f"  Refit points: {n_refits}")

    # Storage for OOS forecasts (all models, both targets)
    # MEM/AMEM on r² predict E[r²_{t+1}] (variance proxy)
    # MEM/AMEM on |r| predict E[|r_{t+1}|] (volatility proxy)
    # GJR/GARCH predict σ²_{t+1} (conditional variance)
    forecasts = {
        'mem_r2': np.full(n_oos, np.nan),     # MEM(1,1) on r²
        'amem_r2': np.full(n_oos, np.nan),    # AMEM(1,1) on r²
        'mem_abs': np.full(n_oos, np.nan),    # MEM(1,1) on |r|
        'amem_abs': np.full(n_oos, np.nan),   # AMEM(1,1) on |r|
        'gjr': np.full(n_oos, np.nan),        # GJR-GARCH predicts σ²
        'garch': np.full(n_oos, np.nan),      # GARCH(1,1) predicts σ²
    }

    # Track parameters for diagnostics
    param_history = {k: [] for k in forecasts.keys()}

    # --- Expanding window OOS loop ---
    print(f"\n[4/6] Running expanding window OOS forecasts...")
    t0 = time.time()

    for ri, refit_start in enumerate(refit_points):
        # Determine the range of OOS obs for this refit window
        if ri < len(refit_points) - 1:
            refit_end = refit_points[ri + 1]
        else:
            refit_end = oos_indices[-1] + 1

        # Expanding window: all data up to refit_start
        is_r = r[:refit_start]
        is_r2 = r2[:refit_start]
        is_abs = abs_r[:refit_start]

        if len(is_r) < min_window:
            print(f"  Refit {ri+1}/{n_refits}: IS window {len(is_r)} < {min_window}, skip")
            continue

        # --- Fit all models on IS data ---

        # 1. MEM on r²
        try:
            res_mem_r2 = fit_mem(is_r2, model_type='mem')
            p_mem_r2 = res_mem_r2.x
            persistence_mem_r2 = p_mem_r2[1] + p_mem_r2[2]
            param_history['mem_r2'].append({
                'omega': float(p_mem_r2[0]), 'alpha': float(p_mem_r2[1]),
                'beta': float(p_mem_r2[2]), 'k': float(p_mem_r2[3]),
                'persistence': float(persistence_mem_r2),
                'converged': bool(res_mem_r2.success)
            })
        except Exception as e:
            print(f"  MEM-r² fit failed at refit {ri}: {e}")
            p_mem_r2 = None

        # 2. AMEM on r²
        try:
            res_amem_r2 = fit_mem(is_r2, model_type='amem', r_sign=is_r)
            p_amem_r2 = res_amem_r2.x
            persistence_amem_r2 = p_amem_r2[1] + p_amem_r2[2] + 0.5 * p_amem_r2[3]
            param_history['amem_r2'].append({
                'omega': float(p_amem_r2[0]), 'alpha': float(p_amem_r2[1]),
                'beta': float(p_amem_r2[2]), 'gamma': float(p_amem_r2[3]),
                'k': float(p_amem_r2[4]), 'persistence': float(persistence_amem_r2),
                'converged': bool(res_amem_r2.success)
            })
        except Exception as e:
            print(f"  AMEM-r² fit failed at refit {ri}: {e}")
            p_amem_r2 = None

        # 3. MEM on |r|
        try:
            res_mem_abs = fit_mem(is_abs, model_type='mem')
            p_mem_abs = res_mem_abs.x
            persistence_mem_abs = p_mem_abs[1] + p_mem_abs[2]
            param_history['mem_abs'].append({
                'omega': float(p_mem_abs[0]), 'alpha': float(p_mem_abs[1]),
                'beta': float(p_mem_abs[2]), 'k': float(p_mem_abs[3]),
                'persistence': float(persistence_mem_abs),
                'converged': bool(res_mem_abs.success)
            })
        except Exception as e:
            print(f"  MEM-|r| fit failed at refit {ri}: {e}")
            p_mem_abs = None

        # 4. AMEM on |r|
        try:
            res_amem_abs = fit_mem(is_abs, model_type='amem', r_sign=is_r)
            p_amem_abs = res_amem_abs.x
            persistence_amem_abs = p_amem_abs[1] + p_amem_abs[2] + 0.5 * p_amem_abs[3]
            param_history['amem_abs'].append({
                'omega': float(p_amem_abs[0]), 'alpha': float(p_amem_abs[1]),
                'beta': float(p_amem_abs[2]), 'gamma': float(p_amem_abs[3]),
                'k': float(p_amem_abs[4]), 'persistence': float(persistence_amem_abs),
                'converged': bool(res_amem_abs.success)
            })
        except Exception as e:
            print(f"  AMEM-|r| fit failed at refit {ri}: {e}")
            p_amem_abs = None

        # 5. GJR-GARCH
        try:
            res_gjr = fit_gjr(is_r)
            p_gjr = res_gjr.x
            persistence_gjr = p_gjr[1] + p_gjr[2] + 0.5 * p_gjr[3]
            param_history['gjr'].append({
                'omega': float(p_gjr[0]), 'alpha': float(p_gjr[1]),
                'beta': float(p_gjr[2]), 'gamma': float(p_gjr[3]),
                'persistence': float(persistence_gjr),
                'converged': bool(res_gjr.success)
            })
        except Exception as e:
            print(f"  GJR fit failed at refit {ri}: {e}")
            p_gjr = None

        # 6. GARCH(1,1)
        try:
            res_garch = fit_garch(is_r)
            p_garch = res_garch.x
            persistence_garch = p_garch[1] + p_garch[2]
            param_history['garch'].append({
                'omega': float(p_garch[0]), 'alpha': float(p_garch[1]),
                'beta': float(p_garch[2]), 'persistence': float(persistence_garch),
                'converged': bool(res_garch.success)
            })
        except Exception as e:
            print(f"  GARCH fit failed at refit {ri}: {e}")
            p_garch = None

        # --- Generate OOS forecasts for this window ---
        # Use FULL data up to each forecast point to compute conditional mean,
        # then take 1-step-ahead forecast: mu[t] predicts x_{t+1}
        # This is equivalent to signal.shift(1): we use params from IS,
        # but feed all data up to t to get the filter state at t,
        # then forecast for t+1.

        for t_idx in range(refit_start, min(refit_end, oos_indices[-1] + 1)):
            oos_pos = t_idx - oos_indices[0]
            if oos_pos < 0 or oos_pos >= n_oos:
                continue

            # Data up to and including t_idx (for computing filter state)
            r_up_to_t = r[:t_idx + 1]
            r2_up_to_t = r2[:t_idx + 1]
            abs_up_to_t = abs_r[:t_idx + 1]

            # 1. MEM-r²: forecast μ_{t+1} = ω + α × r²_t + β × μ_t
            if p_mem_r2 is not None:
                mu = mem_filter(r2_up_to_t, p_mem_r2[0], p_mem_r2[1], p_mem_r2[2])
                # 1-step ahead: ω + α × r²_t + β × μ_t
                fcast = p_mem_r2[0] + p_mem_r2[1] * r2_up_to_t[-1] + p_mem_r2[2] * mu[-1]
                forecasts['mem_r2'][oos_pos] = max(fcast, 1e-12)

            # 2. AMEM-r²
            if p_amem_r2 is not None:
                mu = amem_filter(r2_up_to_t, r_up_to_t, p_amem_r2[0], p_amem_r2[1],
                                 p_amem_r2[2], p_amem_r2[3])
                ind = 1.0 if r_up_to_t[-1] < 0 else 0.0
                fcast = (p_amem_r2[0] + (p_amem_r2[1] + p_amem_r2[3] * ind) * r2_up_to_t[-1]
                         + p_amem_r2[2] * mu[-1])
                forecasts['amem_r2'][oos_pos] = max(fcast, 1e-12)

            # 3. MEM-|r|
            if p_mem_abs is not None:
                mu = mem_filter(abs_up_to_t, p_mem_abs[0], p_mem_abs[1], p_mem_abs[2])
                fcast = p_mem_abs[0] + p_mem_abs[1] * abs_up_to_t[-1] + p_mem_abs[2] * mu[-1]
                forecasts['mem_abs'][oos_pos] = max(fcast, 1e-12)

            # 4. AMEM-|r|
            if p_amem_abs is not None:
                mu = amem_filter(abs_up_to_t, r_up_to_t, p_amem_abs[0], p_amem_abs[1],
                                 p_amem_abs[2], p_amem_abs[3])
                ind = 1.0 if r_up_to_t[-1] < 0 else 0.0
                fcast = (p_amem_abs[0] + (p_amem_abs[1] + p_amem_abs[3] * ind) * abs_up_to_t[-1]
                         + p_amem_abs[2] * mu[-1])
                forecasts['amem_abs'][oos_pos] = max(fcast, 1e-12)

            # 5. GJR-GARCH → σ²_{t+1}
            if p_gjr is not None:
                sigma2 = gjr_filter(r_up_to_t, p_gjr[0], p_gjr[1], p_gjr[2], p_gjr[3])
                ind = 1.0 if r_up_to_t[-1] < 0 else 0.0
                fcast = (p_gjr[0] + (p_gjr[1] + p_gjr[3] * ind) * r_up_to_t[-1]**2
                         + p_gjr[2] * sigma2[-1])
                forecasts['gjr'][oos_pos] = max(fcast, 1e-12)

            # 6. GARCH → σ²_{t+1}
            if p_garch is not None:
                sigma2 = garch_filter(r_up_to_t, p_garch[0], p_garch[1], p_garch[2])
                fcast = (p_garch[0] + p_garch[1] * r_up_to_t[-1]**2
                         + p_garch[2] * sigma2[-1])
                forecasts['garch'][oos_pos] = max(fcast, 1e-12)

        elapsed = time.time() - t0
        pct = (ri + 1) / n_refits * 100
        print(f"  Refit {ri+1}/{n_refits} ({pct:.0f}%) — IS={len(is_r)}, "
              f"elapsed={elapsed:.1f}s")

    print(f"\n  Total time: {time.time() - t0:.1f}s")

    # --- Actual OOS values ---
    # shift by +1: forecast at t predicts t+1
    r2_oos_actual = r2[oos_indices[0]:oos_indices[-1] + 1]    # r²_{t} for evaluation
    abs_oos_actual = abs_r[oos_indices[0]:oos_indices[-1] + 1]  # |r_t|

    # But we predict for t+1, so actual should be r²_{t+1}
    # forecasts[model][i] = forecast made at time oos_indices[0]+i for time oos_indices[0]+i+1
    # So actual should be r²[oos_indices[0]+i+1]
    # Let's adjust: actual[i] = r²[oos_indices[0] + i + 1] if available
    r2_actual = np.array([r2[oos_indices[0] + i + 1] if oos_indices[0] + i + 1 < len(r2)
                          else np.nan for i in range(n_oos)])
    abs_actual = np.array([abs_r[oos_indices[0] + i + 1] if oos_indices[0] + i + 1 < len(abs_r)
                           else np.nan for i in range(n_oos)])

    # Remove trailing NaNs
    valid_mask = ~np.isnan(r2_actual)
    for k in forecasts:
        valid_mask &= ~np.isnan(forecasts[k])

    print(f"\n  Valid OOS obs: {valid_mask.sum()}/{n_oos}")

    r2_act = r2_actual[valid_mask]
    abs_act = abs_actual[valid_mask]
    fcast_valid = {k: v[valid_mask] for k, v in forecasts.items()}

    # --- Evaluation ---
    print(f"\n[5/6] Evaluation...")

    # Convert MEM-|r| and AMEM-|r| predictions to σ² for r² comparison
    # Under Gaussian: E[|r|] = σ√(2/π), so σ² = (E[|r|])² × π/2
    # Under non-Gaussian: use empirical ratio from IS data

    # Empirical ratio: E[r²] / E[|r|]² from IS data
    empirical_ratio = np.mean(r2[:oos_indices[0]]) / (np.mean(abs_r[:oos_indices[0]])**2)
    gaussian_ratio = np.pi / 2  # ≈ 1.5708
    print(f"  Empirical E[r²]/E[|r|]² = {empirical_ratio:.4f} (Gaussian: {gaussian_ratio:.4f})")

    # Convert |r| forecasts to σ² using empirical ratio
    fcast_mem_abs_to_r2 = fcast_valid['mem_abs']**2 * empirical_ratio
    fcast_amem_abs_to_r2 = fcast_valid['amem_abs']**2 * empirical_ratio

    # Convert σ² forecasts to |r| for fair |r| comparison
    # Under Gaussian: E[|r|] = √(σ²) × √(2/π)
    c_gauss = np.sqrt(2 / np.pi)
    fcast_gjr_to_abs = np.sqrt(fcast_valid['gjr']) * c_gauss
    fcast_garch_to_abs = np.sqrt(fcast_valid['garch']) * c_gauss
    fcast_mem_r2_to_abs = np.sqrt(fcast_valid['mem_r2']) * c_gauss
    fcast_amem_r2_to_abs = np.sqrt(fcast_valid['amem_r2']) * c_gauss

    # ---- Metric A: QLIKE on r² (Patton 2011 — primary) ----
    print("\n  === QLIKE on r² (Patton 2011 proxy-robust) ===")
    metrics_r2 = {}
    # Native r² models
    for name in ['mem_r2', 'amem_r2', 'gjr', 'garch']:
        q = qlike(r2_act, fcast_valid[name])
        sp, sp_p = spearmanr(r2_act, fcast_valid[name])
        metrics_r2[name] = {'qlike': float(q), 'spearman_r': float(sp), 'spearman_p': float(sp_p)}
        print(f"    {name:14s}: QLIKE={q:.6f}, Spearman={sp:.4f}")

    # |r| models converted to r²
    for label, fcast_conv in [('mem_abs_conv', fcast_mem_abs_to_r2),
                               ('amem_abs_conv', fcast_amem_abs_to_r2)]:
        q = qlike(r2_act, fcast_conv)
        sp, sp_p = spearmanr(r2_act, fcast_conv)
        metrics_r2[label] = {'qlike': float(q), 'spearman_r': float(sp), 'spearman_p': float(sp_p)}
        print(f"    {label:14s}: QLIKE={q:.6f}, Spearman={sp:.4f}")

    # ---- Metric B: QLIKE on |r| ----
    print("\n  === QLIKE on |r| ===")
    metrics_abs = {}
    # Native |r| models
    for name in ['mem_abs', 'amem_abs']:
        q = qlike(abs_act, fcast_valid[name])
        sp, sp_p = spearmanr(abs_act, fcast_valid[name])
        metrics_abs[name] = {'qlike': float(q), 'spearman_r': float(sp), 'spearman_p': float(sp_p)}
        print(f"    {name:14s}: QLIKE={q:.6f}, Spearman={sp:.4f}")

    # r² models converted to |r|
    for label, fcast_conv in [('gjr_conv', fcast_gjr_to_abs),
                               ('garch_conv', fcast_garch_to_abs),
                               ('mem_r2_conv', fcast_mem_r2_to_abs),
                               ('amem_r2_conv', fcast_amem_r2_to_abs)]:
        q = qlike(abs_act, fcast_conv)
        sp, sp_p = spearmanr(abs_act, fcast_conv)
        metrics_abs[label] = {'qlike': float(q), 'spearman_r': float(sp), 'spearman_p': float(sp_p)}
        print(f"    {label:14s}: QLIKE={q:.6f}, Spearman={sp:.4f}")

    # ---- Metric C: DM tests on r² (primary comparison) ----
    print("\n  === DM Tests on r² (Harvey t>3.0) ===")
    # Compute QLIKE loss arrays for native r² models
    qlike_losses_r2 = {}
    for name in ['mem_r2', 'amem_r2', 'gjr', 'garch']:
        qlike_losses_r2[name] = qlike_loss_array(r2_act, fcast_valid[name])

    dm_results_r2 = {}
    model_pairs_r2 = [
        ('mem_r2', 'gjr', 'MEM-r² vs GJR-GARCH'),
        ('amem_r2', 'gjr', 'AMEM-r² vs GJR-GARCH'),
        ('mem_r2', 'garch', 'MEM-r² vs GARCH(1,1)'),
        ('amem_r2', 'garch', 'AMEM-r² vs GARCH(1,1)'),
        ('mem_r2', 'amem_r2', 'MEM-r² vs AMEM-r²'),
        ('gjr', 'garch', 'GJR vs GARCH(1,1)'),
    ]

    for m1, m2, desc in model_pairs_r2:
        loss1 = qlike_losses_r2[m1]
        loss2 = qlike_losses_r2[m2]
        valid_dm = ~np.isnan(loss1) & ~np.isnan(loss2)
        dm_stat, p_val, harvey = dm_test(loss1[valid_dm], loss2[valid_dm])
        better = m1 if dm_stat < 0 else m2
        dm_results_r2[f"{m1}_vs_{m2}"] = {
            'dm_stat': float(dm_stat),
            'p_value': float(p_val),
            'harvey_pass': bool(harvey),
            'better': better,
            'description': desc
        }
        status = "PASS" if harvey else "FAIL"
        sign = "<" if dm_stat < 0 else ">"
        print(f"    {desc}: DM={dm_stat:.3f}, p={p_val:.4f}, "
              f"Harvey {status}, {m1} {sign} {m2}")

    # ---- Metric D: DM tests on |r| (fair comparison for |r|-native models) ----
    print("\n  === DM Tests on |r| (Harvey t>3.0) ===")
    qlike_losses_abs = {}
    qlike_losses_abs['mem_abs'] = qlike_loss_array(abs_act, fcast_valid['mem_abs'])
    qlike_losses_abs['amem_abs'] = qlike_loss_array(abs_act, fcast_valid['amem_abs'])
    qlike_losses_abs['gjr_conv'] = qlike_loss_array(abs_act, fcast_gjr_to_abs)
    qlike_losses_abs['garch_conv'] = qlike_loss_array(abs_act, fcast_garch_to_abs)

    dm_results_abs = {}
    model_pairs_abs = [
        ('mem_abs', 'gjr_conv', 'MEM-|r| vs GJR→|r|'),
        ('amem_abs', 'gjr_conv', 'AMEM-|r| vs GJR→|r|'),
        ('mem_abs', 'amem_abs', 'MEM-|r| vs AMEM-|r|'),
        ('amem_abs', 'garch_conv', 'AMEM-|r| vs GARCH→|r|'),
    ]

    for m1, m2, desc in model_pairs_abs:
        loss1 = qlike_losses_abs[m1]
        loss2 = qlike_losses_abs[m2]
        valid_dm = ~np.isnan(loss1) & ~np.isnan(loss2)
        dm_stat, p_val, harvey = dm_test(loss1[valid_dm], loss2[valid_dm])
        better = m1 if dm_stat < 0 else m2
        dm_results_abs[f"{m1}_vs_{m2}"] = {
            'dm_stat': float(dm_stat),
            'p_value': float(p_val),
            'harvey_pass': bool(harvey),
            'better': better,
            'description': desc
        }
        status = "PASS" if harvey else "FAIL"
        sign = "<" if dm_stat < 0 else ">"
        print(f"    {desc}: DM={dm_stat:.3f}, p={p_val:.4f}, "
              f"Harvey {status}, {m1} {sign} {m2}")

    # ---- Rankings ----
    print("\n  === Rankings (QLIKE on r², lower = better) ===")
    ranking_r2 = sorted(metrics_r2.items(), key=lambda x: x[1]['qlike'])
    for i, (name, m) in enumerate(ranking_r2):
        print(f"    {i+1}. {name:14s}: QLIKE={m['qlike']:.6f}, Spearman={m['spearman_r']:.4f}")

    print("\n  === Rankings (QLIKE on |r|, lower = better) ===")
    ranking_abs = sorted(metrics_abs.items(), key=lambda x: x[1]['qlike'])
    for i, (name, m) in enumerate(ranking_abs):
        print(f"    {i+1}. {name:14s}: QLIKE={m['qlike']:.6f}, Spearman={m['spearman_r']:.4f}")

    # ---- Parameter diagnostics ----
    print(f"\n[6/6] Parameter diagnostics...")
    param_summary = {}
    for model_name, params_list in param_history.items():
        if not params_list:
            continue
        summary = {}
        keys = params_list[0].keys()
        for key in keys:
            vals = [p[key] for p in params_list if isinstance(p[key], (int, float))]
            if vals:
                summary[key] = {
                    'mean': float(np.mean(vals)),
                    'std': float(np.std(vals)),
                    'min': float(np.min(vals)),
                    'max': float(np.max(vals))
                }
        param_summary[model_name] = summary
        persistence = summary.get('persistence', {})
        if persistence:
            print(f"  {model_name:12s}: persistence={persistence['mean']:.4f} "
                  f"(range: {persistence.get('min', 0):.4f}-{persistence.get('max', 0):.4f})")

    # ---- Check convergence ----
    for model_name, params_list in param_history.items():
        if params_list:
            converged = sum(1 for p in params_list if p.get('converged', False))
            total = len(params_list)
            if converged < total:
                print(f"  WARNING: {model_name} converged {converged}/{total} refits")

    # ---- Build results JSON ----
    results = {
        'experiment_id': 'K805',
        'title': 'MEM(1,1) Comprehensive Evaluation — r² and |r| Targets',
        'proposer': '用戶',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance SPY 2007-present',
        'asset': 'SPY',
        'oos_period': f"{oos_start.strftime('%Y-%m-%d')} to {oos_end.strftime('%Y-%m-%d')}",
        'n_oos': int(n_oos),
        'n_valid_oos': int(valid_mask.sum()),
        'n_refits': int(n_refits),
        'refit_freq': refit_freq,
        'min_window': min_window,
        'window_type': 'expanding',
        'empirical_ratio': float(empirical_ratio),
        'gaussian_ratio': float(gaussian_ratio),
        'diagnostics': diag,
        'metrics_on_r2': metrics_r2,
        'metrics_on_abs': metrics_abs,
        'ranking_r2_qlike': [name for name, _ in ranking_r2],
        'ranking_abs_qlike': [name for name, _ in ranking_abs],
        'dm_tests_r2': dm_results_r2,
        'dm_tests_abs': dm_results_abs,
        'parameter_diagnostics': param_summary,
        'references': [
            'Engle & Gallo (2006) J.Econometrics 131, MEM framework',
            'Glosten, Jagannathan, Runkle (1993) JoF 48, GJR-GARCH',
            'Bollerslev (1986) J.Econometrics 31, GARCH(1,1)',
            'Patton (2011) J.Econometrics 160, QLIKE proxy-robust loss',
            'Harvey (2016) JoF, t>3.0 threshold',
            'K778: MEM-r² native — GJR > AMEM-r² (DM=3.78)',
            'K782: proxy > model — HAR wins |r| but loses r²',
        ]
    }

    # Save
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_PATH}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nQuality check:")
    print(f"  Valid OOS obs: {valid_mask.sum()}/{n_oos}")
    print(f"  All models converged: {all(all(p.get('converged', True) for p in pl) for pl in param_history.values() if pl)}")

    print(f"\nKey findings (QLIKE on r², lower = better):")
    for i, (name, m) in enumerate(ranking_r2[:4]):
        print(f"  {i+1}. {name}: QLIKE={m['qlike']:.6f}")

    print(f"\nKey DM tests (on r²):")
    for pair, res in dm_results_r2.items():
        if res['harvey_pass']:
            print(f"  {res['description']}: DM={res['dm_stat']:.3f} → {res['better']} WINS (Harvey PASS)")
        else:
            print(f"  {res['description']}: DM={res['dm_stat']:.3f} → NS (Harvey FAIL)")

    print(f"\nKey DM tests (on |r|):")
    for pair, res in dm_results_abs.items():
        if res['harvey_pass']:
            print(f"  {res['description']}: DM={res['dm_stat']:.3f} → {res['better']} WINS (Harvey PASS)")
        else:
            print(f"  {res['description']}: DM={res['dm_stat']:.3f} → NS (Harvey FAIL)")

    return results


if __name__ == '__main__':
    main()
