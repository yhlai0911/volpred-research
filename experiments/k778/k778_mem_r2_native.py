#!/usr/bin/env python3
"""
K778: MEM/AMEM Native r² — Pure σ² Space Comparison per Patton (2011)
=====================================================================
[提出: 用戶, 執行: Claude]

KEY INSIGHT: MEM can directly model r² (squared return = variance proxy),
not just |r|. This means MEM and GARCH compete in the SAME native space (σ²)
WITHOUT any distributional conversion.

K777 showed AMEM vs GJR is NS on r² target (DM=0.47, p=0.64) — but K777
used |r|-native AMEM with empirical ratio conversion, not NATIVE MEM-r².

This experiment builds MEM-r² and AMEM-r² that directly model r² with
Gamma innovations (since r² > 0 and is right-skewed → Gamma is natural).

Models (ALL predict r²_{t+1} natively):
  1. MEM-r²:  μ_t = ω + α×r²_{t-1} + β×μ_{t-1}, ε~Gamma
  2. AMEM-r²: μ_t = ω + (α + γ×I(r<0))×r²_{t-1} + β×μ_{t-1}, ε~Gamma
  3. GJR-GARCH: σ²_t = ω + (α + γ×I(r<0))×r²_{t-1} + β×σ²_{t-1} (Normal MLE)
  4. GARCH(1,1): σ²_t = ω + α×r²_{t-1} + β×σ²_{t-1}
  5. HAR-r²: r²_{t+1} = β₀ + β₁×r²_d + β₂×r²_w + β₃×r²_m (OLS)
  6. EWMA-r²: exponential smoothing of r²

Evaluation (Patton 2011 standard):
  - QLIKE on r² (primary — proxy-robust, r² unbiased for σ²)
  - MSE on r²
  - Spearman rank correlation (distribution-free)
  - DM tests with Harvey t>3.0
  - Model Confidence Set (MCS) via bootstrap elimination

References:
  - Engle & Gallo (2006) J.Econometrics 131, MEM framework
  - Glosten, Jagannathan, Runkle (1993) JoF 48, GJR-GARCH
  - Bollerslev (1986) J.Econometrics 31, GARCH(1,1)
  - Corsi (2009) J.Financial Econometrics 7, HAR model
  - Patton (2011) J.Econometrics 160, QLIKE proxy-robust loss
  - Hansen, Lunde, Nason (2011) Econometrica 79, Model Confidence Set
  - K770: MEM on |r| — OVERTURNED due to QLIKE target mismatch
  - K777: Multi-target fair comparison — AMEM vs GJR NS on r²
  - K778: THIS — native MEM-r², no conversion needed

Data: SPY, 2007-2026, expanding window OOS
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

RESULTS_PATH = 'experiments/k778_mem_r2_native_results.json'

# ============================================================
# Part A: Numba-accelerated filters
# ============================================================

@njit(cache=True)
def mem_r2_filter(r2, omega, alpha, beta):
    """
    MEM-r² conditional mean recursion (native variance space):
        μ_t = ω + α × r²_{t-1} + β × μ_{t-1}

    r²: array of squared returns (non-negative)
    Returns: μ (conditional mean of r², same length)
    """
    T = len(r2)
    mu = np.zeros(T)
    mu[0] = r2[0] if r2[0] > 0 else 1e-6
    for t in range(1, T):
        mu[t] = omega + alpha * r2[t-1] + beta * mu[t-1]
        if mu[t] < 1e-12:
            mu[t] = 1e-12
    return mu


@njit(cache=True)
def amem_r2_filter(r2, r, omega, alpha, beta, gamma):
    """
    AMEM-r² conditional mean recursion with leverage (native variance space):
        μ_t = ω + (α + γ × I_{r<0}) × r²_{t-1} + β × μ_{t-1}

    r²: squared returns, r: raw returns (for sign)
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


# ============================================================
# Part B: MLE fitting functions
# ============================================================

def mem_r2_negloglik(params, r2, model='mem_r2', r=None):
    """
    Gamma MLE for MEM-r² / AMEM-r².
    ε_t = r²_t / μ_t ~ Gamma(k, 1/k), E[ε]=1, Var[ε]=1/k

    Log-likelihood per obs:
        k*log(k) - log(Γ(k)) + (k-1)*log(ε_t) - k*ε_t
      = k*log(k/μ_t) + (k-1)*log(r²_t) - k*r²_t/μ_t - log(Γ(k))
    """
    if model == 'mem_r2':
        omega, alpha, beta, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or k <= 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        mu = mem_r2_filter(r2, omega, alpha, beta)
    elif model == 'amem_r2':
        omega, alpha, beta, gamma, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or k <= 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        mu = amem_r2_filter(r2, r, omega, alpha, beta, gamma)
    else:
        return 1e10

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


def fit_mem_r2(r2, model='mem_r2', r=None, max_attempts=4):
    """Fit MEM-r² or AMEM-r² via Gamma MLE with multiple restarts."""
    r2 = np.ascontiguousarray(r2, dtype=np.float64)
    if r is not None:
        r = np.ascontiguousarray(r, dtype=np.float64)

    r2_mean = np.mean(r2[r2 > 0]) if np.any(r2 > 0) else 1e-4
    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)
        if model == 'mem_r2':
            omega0 = r2_mean * 0.05 * (1 + 0.3 * np.random.randn())
            alpha0 = max(0.01, min(0.5, 0.08 + 0.05 * np.random.randn()))
            beta0 = max(0.3, min(0.95, 0.87 + 0.04 * np.random.randn()))
            k0 = max(0.1, 0.8 + 0.3 * np.random.randn())  # r² has high kurtosis → small k
            if alpha0 + beta0 >= 0.99:
                beta0 = 0.98 - alpha0
            p0 = [max(1e-8, omega0), alpha0, beta0, max(0.1, k0)]
            bounds = [(1e-10, None), (0, 0.9), (0, 0.999), (0.05, 100)]
            result = minimize(mem_r2_negloglik, p0, args=(r2, 'mem_r2', None),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 5000, 'ftol': 1e-10})
        else:  # amem_r2
            omega0 = r2_mean * 0.05 * (1 + 0.3 * np.random.randn())
            alpha0 = max(0.01, min(0.4, 0.04 + 0.03 * np.random.randn()))
            beta0 = max(0.3, min(0.95, 0.87 + 0.04 * np.random.randn()))
            gamma0 = max(0.01, min(0.4, 0.08 + 0.05 * np.random.randn()))
            k0 = max(0.1, 0.8 + 0.3 * np.random.randn())
            if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
                beta0 = 0.97 - alpha0 - 0.5 * gamma0
            p0 = [max(1e-8, omega0), alpha0, beta0, max(0.01, gamma0), max(0.1, k0)]
            bounds = [(1e-10, None), (0, 0.9), (0, 0.999), (0, 0.9), (0.05, 100)]
            result = minimize(mem_r2_negloglik, p0, args=(r2, 'amem_r2', r),
                            method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 5000, 'ftol': 1e-10})

        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    if best_result is None:
        return None

    res = best_result
    if model == 'mem_r2':
        params = {
            'omega': float(res.x[0]), 'alpha': float(res.x[1]),
            'beta': float(res.x[2]), 'k': float(res.x[3]),
            'persistence': float(res.x[1] + res.x[2])
        }
    else:
        params = {
            'omega': float(res.x[0]), 'alpha': float(res.x[1]),
            'beta': float(res.x[2]), 'gamma': float(res.x[3]),
            'k': float(res.x[4]),
            'persistence': float(res.x[1] + res.x[2] + 0.5 * res.x[3])
        }
    return {
        'params': params, 'converged': bool(res.success),
        'nll': float(res.fun), 'n_obs': len(r2)
    }


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
# Part C: Forecast functions (all produce r²_{t+1} forecasts)
# ============================================================

def forecast_mem_r2(r2, params):
    """One-step-ahead MEM-r² forecast → E[r²_{t+1}]"""
    mu = mem_r2_filter(r2, params['omega'], params['alpha'], params['beta'])
    # Next-step: ω + α × r²_T + β × μ_T
    f = params['omega'] + params['alpha'] * r2[-1] + params['beta'] * mu[-1]
    return max(f, 1e-12)


def forecast_amem_r2(r2, r, params):
    """One-step-ahead AMEM-r² forecast → E[r²_{t+1}]"""
    mu = amem_r2_filter(r2, r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    indicator = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega'] + (params['alpha'] + params['gamma'] * indicator) * r2[-1]
         + params['beta'] * mu[-1])
    return max(f, 1e-12)


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


def forecast_har_r2(sq_ret, beta):
    """One-step-ahead HAR-r² forecast → E[r²_{t+1}]"""
    n = len(sq_ret)
    if n < 22:
        return None
    f = (beta[0] + beta[1] * sq_ret[-1] + beta[2] * np.mean(sq_ret[-5:])
         + beta[3] * np.mean(sq_ret[-22:]))
    return max(f, 1e-12)


def forecast_ewma_r2(sq_ret, lam=0.94):
    """EWMA-r² forecast → σ²_{t+1}"""
    var = sq_ret[0]
    for i in range(1, len(sq_ret)):
        var = lam * var + (1 - lam) * sq_ret[i]
    return max(var, 1e-12)


# ============================================================
# Part D: Evaluation metrics
# ============================================================

def qlike(actual, predicted):
    """QLIKE loss: actual/predicted - log(actual/predicted) - 1
    Patton (2011): proxy-robust for r² as proxy for σ²."""
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
    """Pointwise QLIKE losses for DM test.
    Handle r²=0 by replacing with small epsilon (r²=0 means return=0,
    rare but possible; QLIKE undefined at 0 so we floor)."""
    a = np.array(actual, dtype=np.float64)
    p = np.array(predicted, dtype=np.float64)
    # Floor zeros to avoid log(0)
    a = np.maximum(a, 1e-16)
    p = np.maximum(p, 1e-16)
    ratio = a / p
    return ratio - np.log(ratio) - 1


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC. Negative → model 1 better."""
    d = np.array(loss1, dtype=np.float64) - np.array(loss2, dtype=np.float64)
    # Remove NaN/Inf
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
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
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    from scipy.stats import t as t_dist
    p_val = 2 * (1 - t_dist.cdf(abs(t_stat), df=n-1))
    return float(t_stat), float(p_val)


# ============================================================
# Part E: Model Confidence Set (Hansen, Lunde, Nason 2011)
# ============================================================

def model_confidence_set(losses_dict, alpha=0.10, n_boot=5000, seed=42):
    """
    MCS procedure (Hansen, Lunde, Nason 2011):
    Iteratively eliminate the worst model until the null that all
    remaining models are equal in expected loss cannot be rejected.

    losses_dict: {model_name: np.array of pointwise losses}
    alpha: significance level
    n_boot: bootstrap replications

    Returns: list of model names in the MCS
    """
    np.random.seed(seed)
    models = list(losses_dict.keys())
    losses_mat = np.column_stack([losses_dict[m] for m in models])
    n = losses_mat.shape[0]

    remaining = list(range(len(models)))

    while len(remaining) > 1:
        sub_losses = losses_mat[:, remaining]
        m_count = len(remaining)

        # Compute pairwise mean loss differences
        d_bar = np.zeros((m_count, m_count))
        for i in range(m_count):
            for j in range(m_count):
                d_bar[i, j] = np.mean(sub_losses[:, i] - sub_losses[:, j])

        # T_max statistic: max over pairs of |d_bar_ij| / se(d_bar_ij)
        t_stats = np.zeros((m_count, m_count))
        for i in range(m_count):
            for j in range(i+1, m_count):
                d_ij = sub_losses[:, i] - sub_losses[:, j]
                se_ij = np.std(d_ij) / np.sqrt(n)
                if se_ij > 1e-15:
                    t_stats[i, j] = abs(np.mean(d_ij)) / se_ij
                    t_stats[j, i] = t_stats[i, j]

        t_max_observed = np.max(t_stats)

        # Bootstrap the t_max distribution
        boot_t_max = np.zeros(n_boot)
        for b in range(n_boot):
            idx = np.random.randint(0, n, size=n)
            boot_losses = sub_losses[idx, :]
            boot_t_max_val = 0.0
            for i in range(m_count):
                for j in range(i+1, m_count):
                    d_ij_b = boot_losses[:, i] - boot_losses[:, j]
                    # Center the bootstrap (under H0: equal expected loss)
                    d_ij_centered = d_ij_b - np.mean(d_ij_b) + d_bar[i, j]
                    # Actually for MCS we center to 0 under H0
                    d_ij_boot_centered = d_ij_b - np.mean(d_ij_b)
                    se_b = np.std(d_ij_boot_centered) / np.sqrt(n)
                    if se_b > 1e-15:
                        t_val = abs(np.mean(d_ij_boot_centered)) / se_b
                        boot_t_max_val = max(boot_t_max_val, t_val)
            boot_t_max[b] = boot_t_max_val

        # p-value
        p_val = np.mean(boot_t_max >= t_max_observed)

        if p_val >= alpha:
            # Cannot reject H0: all remaining models are equal
            break

        # Eliminate the worst model (highest average loss)
        avg_losses = np.mean(sub_losses, axis=0)
        worst_idx = np.argmax(avg_losses)
        remaining.pop(worst_idx)

    return [models[i] for i in remaining]


# ============================================================
# Part F: Main OOS horse race
# ============================================================

def run_oos_comparison():
    """Expanding-window OOS comparison of all 6 models on r² target."""

    print("=" * 70)
    print("K778: MEM/AMEM Native r² — Pure σ² Space Comparison")
    print("=" * 70)

    # --- Data ---
    t0 = time.time()
    spy = yf.download('SPY', start='2006-01-01', end='2026-04-01', progress=False)
    if 'Close' in spy.columns:
        close = spy['Close'].squeeze()
    elif ('Close', 'SPY') in spy.columns:
        close = spy[('Close', 'SPY')].squeeze()
    else:
        close = spy.iloc[:, 3].squeeze()

    returns = close.pct_change().dropna().values
    dates = close.index[1:]  # aligned with returns
    n_total = len(returns)
    r2 = returns ** 2  # squared returns

    print(f"\nData: SPY {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"Total observations: {n_total}")
    print(f"Download time: {time.time()-t0:.1f}s")

    # --- Diagnostics ---
    print("\n--- Diagnostics (squared returns) ---")
    print(f"  mean(r²): {np.mean(r2):.6e}")
    print(f"  std(r²):  {np.std(r2):.6e}")
    print(f"  skewness(r²): {pd.Series(r2).skew():.2f}")
    print(f"  kurtosis(r²): {pd.Series(r2).kurtosis():.2f}")
    print(f"  mean(|r|): {np.mean(np.abs(returns)):.6f}")
    print(f"  Empirical E[r²/|r|²] = {np.mean(r2)/np.mean(np.abs(returns))**2:.4f}")
    print(f"  Theoretical (Normal) E[r²/|r|²] = π/2 = {np.pi/2:.4f}")

    # --- OOS Setup ---
    min_window = 500
    refit_freq = 63  # quarterly refit

    forecasts = {
        'mem_r2': [], 'amem_r2': [], 'gjr': [], 'garch': [],
        'har_r2': [], 'ewma_r2': []
    }
    actuals_r2 = []
    oos_dates = []

    # Track parameters for diagnostics
    param_samples = {'mem_r2': [], 'amem_r2': [], 'gjr': [], 'garch': []}

    # Current model fits (reused between refits)
    current_fits = {k: None for k in forecasts}
    last_refit = -refit_freq  # force first refit

    n_oos = 0
    n_refit = 0
    t1 = time.time()

    print(f"\nOOS from index {min_window} to {n_total-1}")
    print(f"Expected ~{n_total - min_window - 1} OOS observations")
    print(f"Refit every {refit_freq} days")

    for t in range(min_window, n_total - 1):
        # Refit if needed
        if t - last_refit >= refit_freq or current_fits['gjr'] is None:
            r_train = returns[:t]
            r2_train = r2[:t]

            # MEM-r²
            fit = fit_mem_r2(r2_train, model='mem_r2')
            if fit and fit['converged']:
                current_fits['mem_r2'] = fit['params']
                if n_refit % 10 == 0:
                    param_samples['mem_r2'].append(fit['params'].copy())

            # AMEM-r²
            fit = fit_mem_r2(r2_train, model='amem_r2', r=r_train)
            if fit and fit['converged']:
                current_fits['amem_r2'] = fit['params']
                if n_refit % 10 == 0:
                    param_samples['amem_r2'].append(fit['params'].copy())

            # GJR-GARCH
            fit = fit_gjr_garch(r_train)
            if fit:
                current_fits['gjr'] = fit
                if n_refit % 10 == 0:
                    param_samples['gjr'].append(fit.copy())

            # GARCH(1,1)
            fit = fit_garch(r_train)
            if fit:
                current_fits['garch'] = fit
                if n_refit % 10 == 0:
                    param_samples['garch'].append(fit.copy())

            # HAR-r²
            har_beta = fit_har_r2(r2_train)
            if har_beta is not None:
                current_fits['har_r2'] = har_beta

            last_refit = t
            n_refit += 1

        # Generate forecasts for r²_{t+1}
        r_up_to_t = returns[:t+1]
        r2_up_to_t = r2[:t+1]

        fc = {}

        # MEM-r²
        if current_fits['mem_r2'] is not None:
            fc['mem_r2'] = forecast_mem_r2(
                np.ascontiguousarray(r2_up_to_t, dtype=np.float64),
                current_fits['mem_r2'])

        # AMEM-r²
        if current_fits['amem_r2'] is not None:
            fc['amem_r2'] = forecast_amem_r2(
                np.ascontiguousarray(r2_up_to_t, dtype=np.float64),
                np.ascontiguousarray(r_up_to_t, dtype=np.float64),
                current_fits['amem_r2'])

        # GJR-GARCH
        if current_fits['gjr'] is not None:
            fc['gjr'] = forecast_gjr(r_up_to_t, current_fits['gjr'])

        # GARCH(1,1)
        if current_fits['garch'] is not None:
            fc['garch'] = forecast_garch(r_up_to_t, current_fits['garch'])

        # HAR-r²
        if current_fits['har_r2'] is not None:
            fc['har_r2'] = forecast_har_r2(r2_up_to_t, current_fits['har_r2'])

        # EWMA-r²
        fc['ewma_r2'] = forecast_ewma_r2(r2_up_to_t)

        # Only include if ALL models have forecasts
        if len(fc) == 6:
            for k in forecasts:
                forecasts[k].append(fc[k])
            actuals_r2.append(r2[t+1])
            oos_dates.append(str(dates[t+1]) if hasattr(dates[t+1], 'strftime') else str(dates[t+1]))
            n_oos += 1

        if n_oos % 500 == 0 and n_oos > 0:
            elapsed = time.time() - t1
            print(f"  OOS {n_oos}: {elapsed:.1f}s elapsed, {n_refit} refits")

    elapsed_total = time.time() - t1
    print(f"\nOOS complete: {n_oos} observations, {n_refit} refits, {elapsed_total:.1f}s")

    # Convert to arrays
    actuals = np.array(actuals_r2)
    fc_arrays = {k: np.array(v) for k, v in forecasts.items()}

    # ============================================================
    # Part G: Evaluation
    # ============================================================

    print("\n" + "=" * 70)
    print("EVALUATION: QLIKE on r² (Patton 2011 proxy-robust)")
    print("=" * 70)

    # Metrics
    metrics = {}
    for model_name, fc in fc_arrays.items():
        q = qlike(actuals, fc)
        m = mse_metric(actuals, fc)
        sp_r, sp_p = spearmanr(actuals, fc)
        metrics[model_name] = {
            'qlike': q, 'mse': m,
            'spearman_r': float(sp_r), 'spearman_p': float(sp_p)
        }
        print(f"  {model_name:12s}: QLIKE={q:.6f}  MSE={m:.4e}  Spearman={sp_r:.4f}")

    # Rankings
    ranking_qlike = sorted(metrics.keys(), key=lambda m: metrics[m]['qlike'])
    ranking_spearman = sorted(metrics.keys(), key=lambda m: -metrics[m]['spearman_r'])

    print(f"\n  QLIKE ranking: {' > '.join(ranking_qlike)}")
    print(f"  Spearman ranking: {' > '.join(ranking_spearman)}")

    # ============================================================
    # Part H: DM Tests (all pairwise)
    # ============================================================

    print("\n" + "=" * 70)
    print("DIEBOLD-MARIANO TESTS (Harvey t>3.0)")
    print("=" * 70)

    pw_losses = {}
    for model_name, fc in fc_arrays.items():
        pw_losses[model_name] = pointwise_qlike(actuals, fc)

    model_names = list(metrics.keys())
    dm_results = {}
    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            t_stat, p_val = dm_test(pw_losses[m1], pw_losses[m2])
            harvey_pass = abs(t_stat) > 3.0
            better = m1 if t_stat < 0 else m2
            key = f"{m1}_vs_{m2}"
            dm_results[key] = {
                'dm_stat': t_stat, 'p_value': p_val,
                'harvey_pass': harvey_pass, 'better': better
            }
            sig = "***" if harvey_pass else ("*" if p_val < 0.05 else "ns")
            print(f"  {m1:10s} vs {m2:10s}: DM={t_stat:+.3f} p={p_val:.4f} "
                  f"better={better} {sig}")

    # ============================================================
    # Part I: Model Confidence Set
    # ============================================================

    print("\n" + "=" * 70)
    print("MODEL CONFIDENCE SET (α=0.10, bootstrap=5000)")
    print("=" * 70)

    mcs_models = model_confidence_set(pw_losses, alpha=0.10, n_boot=5000)
    print(f"  MCS members: {mcs_models}")
    print(f"  MCS size: {len(mcs_models)} / {len(model_names)}")

    # ============================================================
    # Part J: Sub-period analysis (stability check)
    # ============================================================

    print("\n" + "=" * 70)
    print("SUB-PERIOD ANALYSIS")
    print("=" * 70)

    n = len(actuals)
    mid = n // 2
    periods = {
        'first_half': (0, mid),
        'second_half': (mid, n),
        'crisis_2020': None,
        'post_covid': None,
        'recent_2024_2026': None
    }

    # Find crisis periods by date
    for idx, d in enumerate(oos_dates):
        if '2020-02' in d and periods['crisis_2020'] is None:
            periods['crisis_2020'] = (idx, None)
        if '2020-07' in d and periods['crisis_2020'] is not None and periods['crisis_2020'][1] is None:
            periods['crisis_2020'] = (periods['crisis_2020'][0], idx)
        if '2021-01' in d and periods['post_covid'] is None:
            periods['post_covid'] = (idx, None)
        if '2023-01' in d and periods['post_covid'] is not None and periods['post_covid'][1] is None:
            periods['post_covid'] = (periods['post_covid'][0], idx)
        if '2024-01' in d and periods['recent_2024_2026'] is None:
            periods['recent_2024_2026'] = (idx, None)
    if periods['recent_2024_2026'] is not None and periods['recent_2024_2026'][1] is None:
        periods['recent_2024_2026'] = (periods['recent_2024_2026'][0], n)

    sub_period_results = {}
    for period_name, bounds in periods.items():
        if bounds is None or bounds[1] is None:
            continue
        s, e = bounds
        if e - s < 50:
            continue

        sub_act = actuals[s:e]
        sub_metrics = {}
        for model_name, fc in fc_arrays.items():
            sub_fc = fc[s:e]
            q = qlike(sub_act, sub_fc)
            sp_r, _ = spearmanr(sub_act, sub_fc)
            sub_metrics[model_name] = {'qlike': q, 'spearman_r': float(sp_r)}

        sub_ranking = sorted(sub_metrics.keys(), key=lambda m: sub_metrics[m]['qlike'])
        sub_period_results[period_name] = {
            'n_obs': e - s, 'metrics': sub_metrics, 'ranking': sub_ranking
        }

        print(f"\n  {period_name} (n={e-s}):")
        for m in sub_ranking:
            print(f"    {m:12s}: QLIKE={sub_metrics[m]['qlike']:.6f}  "
                  f"Spearman={sub_metrics[m]['spearman_r']:.4f}")

    # ============================================================
    # Part K: Key comparison — MEM-r² family vs GARCH family
    # ============================================================

    print("\n" + "=" * 70)
    print("KEY COMPARISON: MEM-r² FAMILY vs GARCH FAMILY")
    print("=" * 70)

    comparisons = [
        ('amem_r2', 'gjr', 'AMEM-r² vs GJR-GARCH (both asymmetric)'),
        ('mem_r2', 'garch', 'MEM-r² vs GARCH(1,1) (both symmetric)'),
        ('amem_r2', 'garch', 'AMEM-r² vs GARCH(1,1) (asym MEM vs sym GARCH)'),
        ('mem_r2', 'gjr', 'MEM-r² vs GJR-GARCH (sym MEM vs asym GARCH)'),
        ('amem_r2', 'mem_r2', 'AMEM-r² vs MEM-r² (asymmetry value in MEM)'),
        ('gjr', 'garch', 'GJR vs GARCH (asymmetry value in GARCH)'),
    ]

    key_dm = {}
    for m1, m2, desc in comparisons:
        t_stat, p_val = dm_test(pw_losses[m1], pw_losses[m2])
        better = m1 if t_stat < 0 else m2
        sig = "***" if abs(t_stat) > 3.0 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else "ns"))
        key_dm[f"{m1}_vs_{m2}"] = {
            'dm_stat': t_stat, 'p_value': p_val,
            'harvey_pass': abs(t_stat) > 3.0, 'better': better,
            'description': desc
        }

        # Compute QLIKE improvement percentage
        q1 = metrics[m1]['qlike']
        q2 = metrics[m2]['qlike']
        pct_diff = (q1 - q2) / q2 * 100

        print(f"\n  {desc}")
        print(f"    DM={t_stat:+.4f}  p={p_val:.6f}  better={better} {sig}")
        print(f"    QLIKE: {m1}={q1:.6f} vs {m2}={q2:.6f} (diff={pct_diff:+.3f}%)")

    # ============================================================
    # Part L: Parameter diagnostics
    # ============================================================

    print("\n" + "=" * 70)
    print("PARAMETER DIAGNOSTICS (sampled every 10th refit)")
    print("=" * 70)

    param_diagnostics = {}
    for model_name, samples in param_samples.items():
        if not samples:
            continue
        df = pd.DataFrame(samples)
        param_diagnostics[model_name] = {}
        for col in df.columns:
            param_diagnostics[model_name][col] = {
                'mean': float(df[col].mean()),
                'std': float(df[col].std()),
                'min': float(df[col].min()),
                'max': float(df[col].max())
            }
        print(f"\n  {model_name}:")
        for col in df.columns:
            print(f"    {col:12s}: mean={df[col].mean():.6f}  "
                  f"std={df[col].std():.6f}  [{df[col].min():.6f}, {df[col].max():.6f}]")

    # ============================================================
    # Part M: Compile results
    # ============================================================

    results = {
        'experiment_id': 'K778',
        'title': 'MEM/AMEM Native r² — Pure σ² Space Comparison per Patton (2011)',
        'proposer': '用戶',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance SPY 2007-2026',
        'n_oos': n_oos,
        'n_refits': n_refit,
        'min_window': min_window,
        'refit_freq': refit_freq,
        'oos_period': f"{oos_dates[0]} to {oos_dates[-1]}" if oos_dates else "N/A",
        'diagnostics': {
            'n_obs': n_total,
            'mean_r2': float(np.mean(r2)),
            'std_r2': float(np.std(r2)),
            'skewness_r2': float(pd.Series(r2).skew()),
            'kurtosis_r2': float(pd.Series(r2).kurtosis()),
            'mean_abs_r': float(np.mean(np.abs(returns))),
            'empirical_r2_over_abs2': float(np.mean(r2) / np.mean(np.abs(returns))**2),
            'theoretical_normal_ratio': float(np.pi / 2),
        },
        'metrics': metrics,
        'ranking_qlike': ranking_qlike,
        'ranking_spearman': ranking_spearman,
        'dm_tests_all_pairs': dm_results,
        'key_comparisons': key_dm,
        'model_confidence_set': {
            'alpha': 0.10,
            'n_boot': 5000,
            'mcs_members': mcs_models,
            'mcs_size': len(mcs_models)
        },
        'sub_period_analysis': sub_period_results,
        'parameter_diagnostics': param_diagnostics,
        'references': [
            'Engle & Gallo (2006) J.Econometrics 131, MEM framework',
            'Glosten, Jagannathan, Runkle (1993) JoF 48, GJR-GARCH',
            'Bollerslev (1986) J.Econometrics 31, GARCH(1,1)',
            'Corsi (2009) J.Financial Econometrics 7, HAR model',
            'Patton (2011) J.Econometrics 160, QLIKE proxy-robust loss',
            'Hansen, Lunde, Nason (2011) Econometrica 79, Model Confidence Set',
            'K770: MEM on |r| — OVERTURNED',
            'K777: Multi-target fair — AMEM vs GJR NS on r² (converted)',
            'K778: This — native MEM-r², no conversion'
        ]
    }

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    best_model = ranking_qlike[0]
    best_qlike = metrics[best_model]['qlike']
    print(f"\n  Best model: {best_model} (QLIKE={best_qlike:.6f})")
    print(f"  MCS: {mcs_models}")

    # The key question
    amem_q = metrics['amem_r2']['qlike']
    gjr_q = metrics['gjr']['qlike']
    amem_vs_gjr = key_dm.get('amem_r2_vs_gjr', {})

    print(f"\n  KEY QUESTION: Does native MEM-r² beat GARCH on GARCH's turf?")
    print(f"    AMEM-r² QLIKE: {amem_q:.6f}")
    print(f"    GJR-GARCH QLIKE: {gjr_q:.6f}")
    print(f"    Difference: {(amem_q - gjr_q)/gjr_q*100:+.3f}%")
    if amem_vs_gjr:
        print(f"    DM: {amem_vs_gjr['dm_stat']:+.4f} (p={amem_vs_gjr['p_value']:.6f})")
        print(f"    Harvey t>3.0: {amem_vs_gjr['harvey_pass']}")
        if amem_vs_gjr['harvey_pass']:
            print(f"    VERDICT: {amem_vs_gjr['better']} is SIGNIFICANTLY better!")
        else:
            print(f"    VERDICT: NOT SIGNIFICANT — models statistically indistinguishable")

    # Save
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_PATH}")

    return results


if __name__ == '__main__':
    # Warm up numba
    print("Warming up numba JIT...")
    _dummy = np.array([0.01, 0.02, 0.015], dtype=np.float64)
    _dummy_r = np.array([0.01, -0.02, 0.015], dtype=np.float64)
    mem_r2_filter(_dummy, 1e-6, 0.05, 0.9)
    amem_r2_filter(_dummy, _dummy_r, 1e-6, 0.05, 0.9, 0.05)
    gjr_filter(_dummy_r, 1e-6, 0.05, 0.9, 0.05)
    garch_filter(_dummy_r, 1e-6, 0.05, 0.9)
    print("Numba warm-up done.\n")

    results = run_oos_comparison()
