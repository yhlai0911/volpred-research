#!/usr/bin/env python3
"""
K775: HAR-PD (Path-Dependent) Volatility Model
================================================
[提出: 文獻搜尋 arXiv:2503.00851, 執行: Claude]

Background:
  arXiv:2503.00851 (2025): "Forecasting realized volatility: a path-dependent
  perspective." Combines HAR with path-dependent features that capture
  volatility trends, momentum, and return paths.

Standard HAR-ABS:
  E[|r_{t+1}|] = β₀ + β₁×|r_t| + β₂×MA5(|r|) + β₃×MA22(|r|)

HAR-PD adds path-dependent features:
  1. Vol trend:     sign(MA5(|r|) - MA22(|r|))  — is vol trending up or down?
  2. Vol momentum:  (MA5(|r|) / MA22(|r|)) - 1  — speed of vol change
  3. Return path:   cumulative return over 22d   — captures drift direction
  4. Max drawdown:  max drawdown over 22d        — captures tail events

HAR-PD:
  E[|r_{t+1}|] = β₀ + β₁×|r_t| + β₂×MA5 + β₃×MA22
               + β₄×trend + β₅×momentum + β₆×cum_ret + β₇×max_dd

Comparison (expanding window, SPY 2007-2026):
  HAR-ABS vs HAR-PD vs AMEM vs GJR-GARCH vs EWMA
  All predicting |r_{t+1}| (unified target per K770b)
  Evaluation: QLIKE on |r|, DM test, Harvey t>3.0

References:
  - arXiv:2503.00851 (2025) "Forecasting realized volatility: a path-dependent
    perspective"
  - Corsi (2009) J.Financial Econometrics — HAR model
  - Engle & Gallo (2006) J.Econometrics 131 — MEM/AMEM
  - Patton (2011) J.Econometrics 160 — QLIKE robustness
  - K770b: Unified target framework (approach A: all predict E[|r|])

Data: SPY from yfinance, 2007-01-01 to 2026-03-31
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

RESULTS_PATH = 'experiments/k775_har_pd_results.json'

# Conversion constant: E[|r|] = σ × sqrt(2/π) under Normal
SQRT_2_OVER_PI = np.sqrt(2.0 / np.pi)  # ≈ 0.7979

# ============================================================
# Part A: Model Implementations
# ============================================================

# --- Numba filters ---
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


# --- AMEM MLE ---
def amem_negloglik(params, x, r):
    """Gamma MLE for AMEM."""
    omega, alpha, beta, gamma, k = params
    if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or k <= 0:
        return 1e10
    if alpha + beta + 0.5 * gamma >= 1.0:
        return 1e10
    mu = amem_filter(x, r, omega, alpha, beta, gamma)
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


def fit_amem(x, r, max_attempts=3):
    """Fit AMEM via Gamma MLE with multiple restarts."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    r = np.ascontiguousarray(r, dtype=np.float64)
    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 0.01
    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)
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
        result = minimize(amem_negloglik, p0, args=(x, r),
                         method='L-BFGS-B', bounds=bounds,
                         options={'maxiter': 5000, 'ftol': 1e-10})
        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    if best_result is None:
        return None
    res = best_result
    return {
        'params': {
            'omega': res.x[0], 'alpha': res.x[1],
            'beta': res.x[2], 'gamma': res.x[3], 'k': res.x[4],
            'persistence': res.x[1] + res.x[2] + 0.5 * res.x[3]
        },
        'converged': res.success,
        'nll': res.fun,
        'n_obs': len(x)
    }


# --- HAR-ABS ---
def fit_har_abs(abs_ret):
    """
    HAR-ABS: |r_t| = β0 + β1 × |r_{t-1}| + β2 × MA5_{t-1}(|r|) + β3 × MA22_{t-1}(|r|)
    All features are lagged to avoid lookahead.
    """
    x = abs_ret.copy()
    n = len(x)
    if n < 50:
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


def har_abs_forecast(abs_ret, beta, floor=None):
    """One-step-ahead HAR-ABS forecast (predicts E[|r|])."""
    n = len(abs_ret)
    if n < 22:
        return None
    lag1 = abs_ret[-1]
    ma5 = np.mean(abs_ret[-5:])
    ma22 = np.mean(abs_ret[-22:])
    pred = beta[0] + beta[1] * lag1 + beta[2] * ma5 + beta[3] * ma22
    # Floor: 10% of recent mean to prevent QLIKE explosion
    if floor is None:
        floor = 0.1 * np.mean(abs_ret[-252:]) if n >= 252 else 0.1 * np.mean(abs_ret)
    return max(pred, floor)


# --- HAR-PD (Path-Dependent, arXiv:2503.00851) ---
def compute_pd_features(abs_ret, returns):
    """
    Compute path-dependent features at the LAST time point.
    All features use data up to and including the last observation (no lookahead).

    Returns: dict with 4 features, or None if insufficient data.
    """
    n = len(abs_ret)
    if n < 22:
        return None

    ma5 = np.mean(abs_ret[-5:])
    ma22 = np.mean(abs_ret[-22:])

    # 1. Vol trend: sign(MA5 - MA22), binary {-1, +1}
    vol_trend = 1.0 if ma5 >= ma22 else -1.0

    # 2. Vol momentum: (MA5 / MA22) - 1
    vol_momentum = (ma5 / ma22) - 1.0 if ma22 > 1e-10 else 0.0

    # 3. Return path: cumulative return over 22d
    cum_ret = np.sum(returns[-22:])

    # 4. Max drawdown over 22d
    cum_returns = np.cumsum(returns[-22:])
    running_max = np.maximum.accumulate(cum_returns)
    drawdowns = cum_returns - running_max
    max_dd = np.min(drawdowns)  # most negative

    return {
        'vol_trend': vol_trend,
        'vol_momentum': vol_momentum,
        'cum_ret': cum_ret,
        'max_dd': max_dd
    }


def fit_har_pd(abs_ret, returns):
    """
    HAR-PD: HAR-ABS + 4 path-dependent features.
    |r_t| = β0 + β1×|r_{t-1}| + β2×MA5 + β3×MA22
          + β4×vol_trend + β5×vol_momentum + β6×cum_ret + β7×max_dd

    All features at time t use data up to t-1 (lag 1).
    Uses Ridge regression (L2 penalty) to stabilize 8-parameter OLS when
    training data is limited. Lambda chosen by leave-one-out GCV.
    """
    x = abs_ret.copy()
    r = returns.copy()
    n = len(x)
    if n < 60:
        return None

    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values

    valid_start = 23  # need 22 for MA22 + 1 for lag
    if n <= valid_start + 30:
        return None

    Y_list = []
    X_list = []

    for t in range(valid_start, n):
        # Target: |r_t|
        y = x[t]

        # HAR features (lagged by 1)
        lag1 = x[t - 1]
        f_ma5 = ma5[t - 1]
        f_ma22 = ma22[t - 1]
        if np.isnan(f_ma5) or np.isnan(f_ma22):
            continue

        # Path-dependent features (using data up to t-1)
        if t - 1 < 22:
            continue
        sub_abs = x[t-22:t]  # 22 days ending at t-1 (inclusive)
        sub_ret = r[t-22:t]

        sub_ma5 = np.mean(sub_abs[-5:])
        sub_ma22 = np.mean(sub_abs)
        vol_trend = 1.0 if sub_ma5 >= sub_ma22 else -1.0
        vol_momentum = (sub_ma5 / sub_ma22) - 1.0 if sub_ma22 > 1e-10 else 0.0
        cum_ret = np.sum(sub_ret)
        cum_rets = np.cumsum(sub_ret)
        running_max = np.maximum.accumulate(cum_rets)
        drawdowns = cum_rets - running_max
        max_dd = np.min(drawdowns)

        Y_list.append(y)
        X_list.append([1.0, lag1, f_ma5, f_ma22,
                       vol_trend, vol_momentum, cum_ret, max_dd])

    if len(Y_list) < 30:
        return None

    Y = np.array(Y_list)
    X = np.array(X_list)

    try:
        # Ridge regression: (X'X + λI)^-1 X'Y
        # Small λ to stabilize without heavy bias; skip penalizing intercept
        lam = 1e-4
        XtX = X.T @ X
        p = XtX.shape[0]
        penalty = lam * np.eye(p)
        penalty[0, 0] = 0.0  # don't penalize intercept
        beta = np.linalg.solve(XtX + penalty, X.T @ Y)
    except Exception:
        return None
    return beta


def har_pd_forecast(abs_ret, returns, beta, floor=None):
    """
    One-step-ahead HAR-PD forecast (predicts E[|r|]).
    Uses a sensible floor (10% of recent mean |r|) to prevent near-zero
    forecasts that would explode QLIKE.
    """
    n = len(abs_ret)
    if n < 22:
        return None

    lag1 = abs_ret[-1]
    ma5 = np.mean(abs_ret[-5:])
    ma22 = np.mean(abs_ret[-22:])

    # Path-dependent features
    sub_abs = abs_ret[-22:]
    sub_ret = returns[-22:]
    sub_ma5 = np.mean(sub_abs[-5:])
    sub_ma22 = np.mean(sub_abs)
    vol_trend = 1.0 if sub_ma5 >= sub_ma22 else -1.0
    vol_momentum = (sub_ma5 / sub_ma22) - 1.0 if sub_ma22 > 1e-10 else 0.0
    cum_ret = np.sum(sub_ret)
    cum_rets = np.cumsum(sub_ret)
    running_max = np.maximum.accumulate(cum_rets)
    drawdowns = cum_rets - running_max
    max_dd = np.min(drawdowns)

    pred = (beta[0] + beta[1] * lag1 + beta[2] * ma5 + beta[3] * ma22
            + beta[4] * vol_trend + beta[5] * vol_momentum
            + beta[6] * cum_ret + beta[7] * max_dd)
    # Floor: 10% of recent mean absolute return to prevent QLIKE explosion
    if floor is None:
        floor = 0.1 * np.mean(abs_ret[-252:]) if n >= 252 else 0.1 * np.mean(abs_ret)
    return max(pred, floor)


# --- GJR-GARCH ---
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
        'params': {
            'omega': best.x[0], 'alpha': best.x[1],
            'beta': best.x[2], 'gamma': best.x[3],
            'persistence': best.x[1] + best.x[2] + 0.5 * best.x[3]
        },
        'converged': best.success,
        'nll': best.fun
    }


def gjr_one_step_sigma2(returns, params):
    """One-step-ahead GJR-GARCH σ² forecast."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    # Next step: σ²_{T+1} = ω + (α + γ×I) × r_T² + β × σ²_T
    r_last = r[-1]
    ind = 1.0 if r_last < 0 else 0.0
    forecast = (params['omega'] +
                (params['alpha'] + params['gamma'] * ind) * r_last**2 +
                params['beta'] * sigma2[-1])
    return max(forecast, 1e-12)


# --- EWMA ---
def ewma_forecast(returns, lam=0.94):
    """EWMA σ² forecast with RiskMetrics lambda=0.94. Returns σ²."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    sigma2 = np.var(r[:30]) if T >= 30 else np.var(r)
    for t in range(T):
        sigma2 = lam * sigma2 + (1 - lam) * r[t]**2
    return max(sigma2, 1e-12)


# ============================================================
# Part B: Evaluation Functions
# ============================================================

def qlike(actual, forecast):
    """QLIKE loss: mean(actual/forecast - log(actual/forecast) - 1)."""
    a = np.array(actual)
    f = np.array(forecast)
    valid = (a > 0) & (f > 0)
    if valid.sum() < 10:
        return np.nan
    a = a[valid]
    f = f[valid]
    ratio = a / f
    return np.mean(ratio - np.log(ratio) - 1.0)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. Returns (DM stat, p-value, Harvey adjusted t)."""
    d = np.array(loss1) - np.array(loss2)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return np.nan, np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    total_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        total_var += 2 * gamma_k
    se = np.sqrt(total_var / T)
    if se < 1e-20:
        return np.nan, np.nan, np.nan
    dm_stat = d_mean / se
    # Harvey (1997) small-sample correction
    harvey_factor = np.sqrt((T + 1 - 2*h + h*(h-1)/T) / T)
    dm_harvey = dm_stat * harvey_factor
    p_value = 2 * (1 - norm.cdf(abs(dm_harvey)))
    return dm_stat, p_value, dm_harvey


def qlike_loss_series(actual, forecast):
    """Element-wise QLIKE loss for DM test."""
    a = np.array(actual)
    f = np.array(forecast)
    ratio = a / f
    losses = ratio - np.log(ratio) - 1.0
    losses[~np.isfinite(losses)] = np.nan
    return losses


# ============================================================
# Part C: Expanding Window OOS Evaluation
# ============================================================

def run_expanding_oos(returns, abs_ret, init_window=500, refit_every=50):
    """
    Run expanding window OOS forecast for all 5 models.
    All forecasts converted to E[|r|] space (Approach A from K770b).

    Models:
      1. har_abs — HAR on absolute returns (OLS)
      2. har_pd  — HAR + 4 path-dependent features (OLS)
      3. amem    — AMEM(1,1) via Gamma MLE
      4. gjr     — GJR-GARCH(1,1) → σ → E[|r|] = σ × sqrt(2/π)
      5. ewma    — EWMA(0.94) → σ → E[|r|] = σ × sqrt(2/π)
    """
    T = len(returns)
    n_oos = T - init_window
    if n_oos < 100:
        raise ValueError(f"Not enough OOS data: {n_oos}")

    print(f"  Total obs: {T}, Init window: {init_window}, OOS: {n_oos}")
    print(f"  Refit every: {refit_every} days")

    # Storage
    actuals = []  # |r_{t+1}|
    forecasts = {m: [] for m in ['har_abs', 'har_pd', 'amem', 'gjr', 'ewma']}

    # Model state (re-estimated periodically)
    har_abs_beta = None
    har_pd_beta = None
    amem_result = None
    gjr_result = None

    last_fit = -refit_every  # force initial fit

    for t in range(init_window, T):
        step = t - init_window
        if step % 500 == 0:
            print(f"    OOS step {step}/{n_oos} ({100*step/n_oos:.1f}%)")

        # Actual: |r_{t+1}| — but we're at position t, so actual is |r_t|
        # Wait — to be precise: at time t, we use data [0..t-1] to predict |r_t|
        # So actual = |r_t| = abs_ret[t]
        actual = abs_ret[t]

        # Training data: [0..t-1]
        train_ret = returns[:t]
        train_abs = abs_ret[:t]

        # Refit models periodically
        if step - last_fit >= refit_every or step == 0:
            har_abs_beta = fit_har_abs(train_abs)
            har_pd_beta = fit_har_pd(train_abs, train_ret)
            amem_result = fit_amem(train_abs, train_ret)
            gjr_result = fit_gjr_garch(train_ret)
            last_fit = step

        # --- Forecasts ---
        # 1. HAR-ABS
        if har_abs_beta is not None:
            fc = har_abs_forecast(train_abs, har_abs_beta)
        else:
            fc = np.mean(train_abs[-22:])
        forecasts['har_abs'].append(fc)

        # 2. HAR-PD
        if har_pd_beta is not None:
            fc = har_pd_forecast(train_abs, train_ret, har_pd_beta)
        else:
            fc = np.mean(train_abs[-22:])
        forecasts['har_pd'].append(fc)

        # 3. AMEM
        if amem_result is not None:
            p = amem_result['params']
            mu = amem_filter(train_abs, train_ret,
                           p['omega'], p['alpha'], p['beta'], p['gamma'])
            fc = p['omega'] + (p['alpha'] + p['gamma'] * (1.0 if train_ret[-1] < 0 else 0.0)) * train_abs[-1] + p['beta'] * mu[-1]
            fc = max(fc, 1e-10)
        else:
            fc = np.mean(train_abs[-22:])
        forecasts['amem'].append(fc)

        # 4. GJR-GARCH → convert σ to E[|r|]
        if gjr_result is not None:
            sigma2_fc = gjr_one_step_sigma2(train_ret, gjr_result['params'])
            fc = np.sqrt(sigma2_fc) * SQRT_2_OVER_PI
        else:
            fc = np.mean(train_abs[-22:])
        forecasts['gjr'].append(fc)

        # 5. EWMA → convert σ to E[|r|]
        sigma2_fc = ewma_forecast(train_ret)
        fc = np.sqrt(sigma2_fc) * SQRT_2_OVER_PI
        forecasts['ewma'].append(fc)

        actuals.append(actual)

    return np.array(actuals), {k: np.array(v) for k, v in forecasts.items()}


# ============================================================
# Part D: Full-sample parameter diagnostics
# ============================================================

def full_sample_diagnostics(abs_ret, returns):
    """Fit all models on full sample for parameter reporting."""
    print("  Full-sample parameter estimation...")

    # HAR-ABS
    har_abs_beta = fit_har_abs(abs_ret)
    print(f"    HAR-ABS coefs: {har_abs_beta}")

    # HAR-PD
    har_pd_beta = fit_har_pd(abs_ret, returns)
    if har_pd_beta is not None:
        print(f"    HAR-PD coefs: intercept={har_pd_beta[0]:.6f}, "
              f"lag1={har_pd_beta[1]:.4f}, ma5={har_pd_beta[2]:.4f}, "
              f"ma22={har_pd_beta[3]:.4f}")
        print(f"    HAR-PD PD coefs: vol_trend={har_pd_beta[4]:.6f}, "
              f"vol_mom={har_pd_beta[5]:.6f}, cum_ret={har_pd_beta[6]:.6f}, "
              f"max_dd={har_pd_beta[7]:.6f}")

    # AMEM
    amem_result = fit_amem(abs_ret, returns)
    if amem_result:
        print(f"    AMEM params: {amem_result['params']}")

    # GJR-GARCH
    gjr_result = fit_gjr_garch(returns)
    if gjr_result:
        print(f"    GJR params: {gjr_result['params']}")

    return {
        'har_abs': har_abs_beta.tolist() if har_abs_beta is not None else None,
        'har_pd': har_pd_beta.tolist() if har_pd_beta is not None else None,
        'amem': amem_result['params'] if amem_result else None,
        'gjr': gjr_result['params'] if gjr_result else None,
    }


# ============================================================
# Part E: Sub-period analysis (crisis vs calm)
# ============================================================

def subperiod_analysis(actuals, forecasts, dates):
    """Analyze performance in high-vol vs low-vol subperiods."""
    # Use rolling 22d vol to classify regimes
    abs_act = actuals
    if len(abs_act) < 44:
        return None

    rolling_vol = pd.Series(abs_act).rolling(22).mean().values
    median_vol = np.nanmedian(rolling_vol)

    high_vol = rolling_vol > median_vol
    low_vol = ~high_vol & ~np.isnan(rolling_vol)
    high_vol = high_vol & ~np.isnan(rolling_vol)

    results = {}
    for regime, mask in [('high_vol', high_vol), ('low_vol', low_vol)]:
        if mask.sum() < 30:
            continue
        regime_results = {}
        for model_name, fc in forecasts.items():
            regime_results[model_name] = {
                'qlike': float(qlike(abs_act[mask], fc[mask])),
                'n_obs': int(mask.sum())
            }
        results[regime] = regime_results

    return results


# ============================================================
# Main
# ============================================================

def main():
    t_start = time.time()
    print("=" * 70)
    print("K775: HAR-PD (Path-Dependent) Volatility Model")
    print("arXiv:2503.00851 (2025)")
    print("=" * 70)

    # --- Download data ---
    print("\n[1] Downloading SPY data...")
    spy = yf.download('SPY', start='2006-01-01', end='2026-04-01', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.dropna(subset=['Close'])
    returns = spy['Close'].pct_change().dropna().values
    abs_ret = np.abs(returns)
    dates = spy.index[1:]  # align with returns
    print(f"  SPY: {len(returns)} daily returns from {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")

    # --- Full-sample diagnostics ---
    print("\n[2] Full-sample parameter diagnostics...")
    full_params = full_sample_diagnostics(abs_ret, returns)

    # --- Expanding window OOS ---
    print("\n[3] Expanding window OOS evaluation...")
    actuals, forecasts = run_expanding_oos(
        returns, abs_ret,
        init_window=500,   # ~2 years
        refit_every=50     # refit every 50 days
    )
    oos_dates = dates[500:500+len(actuals)]
    print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
    print(f"  OOS observations: {len(actuals)}")

    # --- QLIKE metrics ---
    print("\n[4] QLIKE evaluation (all in |r| space)...")
    models = ['har_abs', 'har_pd', 'amem', 'gjr', 'ewma']
    metrics = {}
    for m in models:
        q = qlike(actuals, forecasts[m])
        mse = np.mean((actuals - forecasts[m])**2)
        mae = np.mean(np.abs(actuals - forecasts[m]))
        metrics[m] = {'qlike': float(q), 'mse': float(mse), 'mae': float(mae)}
        print(f"  {m:10s}: QLIKE={q:.6f}  MSE={mse:.2e}  MAE={mae:.6f}")

    # Ranking
    ranked = sorted(models, key=lambda m: metrics[m]['qlike'])
    print(f"\n  Ranking (QLIKE, lower is better): {ranked}")

    # --- DM tests ---
    print("\n[5] Diebold-Mariano tests (QLIKE loss, Harvey t>3.0)...")
    loss_series = {}
    for m in models:
        loss_series[m] = qlike_loss_series(actuals, forecasts[m])

    dm_results = {}
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            key = f"{m1}_vs_{m2}"
            dm_stat, p_val, dm_harvey = dm_test(loss_series[m1], loss_series[m2])
            harvey_pass = abs(dm_harvey) > 3.0 if not np.isnan(dm_harvey) else False
            better = m1 if dm_stat < 0 else m2
            dm_results[key] = {
                'dm_stat': float(dm_stat) if not np.isnan(dm_stat) else None,
                'p_value': float(p_val) if not np.isnan(p_val) else None,
                'dm_harvey': float(dm_harvey) if not np.isnan(dm_harvey) else None,
                'harvey_pass': harvey_pass,
                'better': better
            }
            sig = "***" if harvey_pass else ""
            print(f"  {key:25s}: DM={dm_stat:+.3f}  p={p_val:.4f}  "
                  f"Harvey_t={dm_harvey:+.3f}  → {better} {sig}")

    # --- Key comparison: HAR-PD vs HAR-ABS ---
    print("\n[6] Key comparison: HAR-PD vs HAR-ABS")
    har_pd_qlike = metrics['har_pd']['qlike']
    har_abs_qlike = metrics['har_abs']['qlike']
    improvement_pct = (har_abs_qlike - har_pd_qlike) / har_abs_qlike * 100
    print(f"  HAR-ABS QLIKE: {har_abs_qlike:.6f}")
    print(f"  HAR-PD  QLIKE: {har_pd_qlike:.6f}")
    print(f"  Improvement:   {improvement_pct:+.3f}%")
    dm_key = 'har_abs_vs_har_pd'
    if dm_key in dm_results:
        d = dm_results[dm_key]
        print(f"  DM test: stat={d['dm_stat']:.3f}, p={d['p_value']:.4f}, "
              f"Harvey_t={d['dm_harvey']:.3f} {'(SIGNIFICANT)' if d['harvey_pass'] else '(not significant)'}")

    # --- Sub-period analysis ---
    print("\n[7] Sub-period analysis (high-vol vs low-vol)...")
    subperiod = subperiod_analysis(actuals, forecasts, oos_dates)
    if subperiod:
        for regime, results in subperiod.items():
            print(f"  {regime}:")
            regime_ranked = sorted(results.keys(), key=lambda m: results[m]['qlike'])
            for m in regime_ranked:
                print(f"    {m:10s}: QLIKE={results[m]['qlike']:.6f} (n={results[m]['n_obs']})")

    # --- HAR-PD coefficient analysis ---
    print("\n[8] HAR-PD coefficient significance (full sample)...")
    if full_params['har_pd'] is not None:
        beta = full_params['har_pd']
        names = ['intercept', 'lag1_|r|', 'MA5_|r|', 'MA22_|r|',
                 'vol_trend', 'vol_momentum', 'cum_ret', 'max_dd']
        print(f"  {'Feature':20s} {'Coef':>12s}")
        print(f"  {'-'*32}")
        for name, b in zip(names, beta):
            print(f"  {name:20s} {b:12.6f}")

    # --- Build results ---
    elapsed = time.time() - t_start
    print(f"\n  Elapsed: {elapsed:.1f}s")

    results = {
        'experiment_id': 'k775',
        'title': 'K775: HAR-PD (Path-Dependent) Volatility Model',
        'proposer': '文獻搜尋 arXiv:2503.00851',
        'executor': 'Claude',
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY)',
        'data_period': f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
        'n_oos': len(actuals),
        'methodology': (
            'Expanding window (init=500d, refit=50d). HAR-PD adds 4 path-dependent '
            'features to HAR-ABS: vol_trend (sign of MA5-MA22), vol_momentum '
            '(MA5/MA22-1), cum_ret (22d cumulative return), max_dd (22d max drawdown). '
            'All models predict E[|r_{t+1}|] (unified target per K770b approach A). '
            'GJR/EWMA converted via sqrt(sigma2)*sqrt(2/pi).'
        ),
        'references': [
            'arXiv:2503.00851 (2025) Forecasting realized volatility: a path-dependent perspective',
            'Corsi (2009) J.Financial Econometrics — HAR-RV',
            'Engle & Gallo (2006) J.Econometrics 131 — MEM/AMEM',
            'Patton (2011) J.Econometrics 160 — QLIKE robustness',
            'K770b: Unified target framework'
        ],
        'full_sample_params': full_params,
        'metrics': metrics,
        'ranking': ranked,
        'dm_tests': dm_results,
        'har_pd_vs_har_abs': {
            'har_pd_qlike': float(har_pd_qlike),
            'har_abs_qlike': float(har_abs_qlike),
            'improvement_pct': float(improvement_pct),
            'dm_test': dm_results.get('har_abs_vs_har_pd', None)
        },
        'subperiod_analysis': subperiod,
        'harvey_significant_tests': [
            f"{k}: DM={v['dm_stat']:.2f} → {v['better']}"
            for k, v in dm_results.items()
            if v['harvey_pass']
        ],
        'conclusions': [],
        'elapsed_seconds': round(elapsed, 1)
    }

    # --- Conclusions ---
    conclusions = []
    # 1. HAR-PD vs HAR-ABS
    if improvement_pct > 0:
        conclusions.append(
            f"HAR-PD improves on HAR-ABS by {improvement_pct:.3f}% in QLIKE"
        )
    else:
        conclusions.append(
            f"HAR-PD does NOT improve on HAR-ABS (QLIKE {improvement_pct:+.3f}%)"
        )

    # 2. DM significance for HAR-PD vs HAR-ABS
    dm_pd = dm_results.get('har_abs_vs_har_pd', {})
    if dm_pd.get('harvey_pass', False):
        conclusions.append(
            f"HAR-PD vs HAR-ABS: STATISTICALLY SIGNIFICANT (Harvey t={dm_pd['dm_harvey']:.2f})"
        )
    else:
        harvey_t = dm_pd.get('dm_harvey', 0)
        conclusions.append(
            f"HAR-PD vs HAR-ABS: NOT significant (Harvey t={harvey_t:.2f}, threshold 3.0)"
        )

    # 3. Overall ranking
    conclusions.append(f"Overall ranking: {' > '.join(ranked)}")

    # 4. Best model
    best = ranked[0]
    conclusions.append(f"Best model: {best} (QLIKE={metrics[best]['qlike']:.6f})")

    # 5. Path-dependent features value
    if full_params['har_pd'] is not None:
        pd_coefs = full_params['har_pd'][4:]  # last 4 coefficients
        pd_names = ['vol_trend', 'vol_momentum', 'cum_ret', 'max_dd']
        nonzero = [n for n, c in zip(pd_names, pd_coefs) if abs(c) > 1e-8]
        conclusions.append(
            f"Non-trivial PD features: {', '.join(nonzero) if nonzero else 'NONE'}"
        )

    # 6. Sub-period insights
    if subperiod:
        for regime in ['high_vol', 'low_vol']:
            if regime in subperiod:
                regime_ranked = sorted(
                    subperiod[regime].keys(),
                    key=lambda m: subperiod[regime][m]['qlike']
                )
                conclusions.append(f"{regime} ranking: {' > '.join(regime_ranked)}")

    results['conclusions'] = conclusions

    # Print conclusions
    print("\n" + "=" * 70)
    print("CONCLUSIONS:")
    for c in conclusions:
        print(f"  • {c}")

    # Save
    os.makedirs('experiments', exist_ok=True)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_PATH}")

    return results


if __name__ == '__main__':
    main()
