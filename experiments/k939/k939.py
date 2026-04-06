"""
K939: CARR_YZ-MF(VIX) — Range + VIX Ultimate Combination
Can Yang-Zhang range + VIX multiplicative factor beat MF-GJR(VIX)?

K935 showed CARR_YZ (QLIKE=1.556) beats CARR_Parkinson (1.699) by 8%.
K889 showed MF-GJR(VIX) is the current best (QLIKE~1.47).
CARR_YZ hasn't been combined with VIX yet.

Hypotheses:
  H1: CARR_YZ-MF(VIX) QLIKE < MF-GJR(VIX) (range + VIX > return + VIX)
  H0: CARR_YZ-MF(VIX) ~ MF-GJR(VIX) (VIX dominates, range adds no increment)

Models (6):
  1. GARCH(1,1)           — baseline
  2. GJR(1,1,1)           — asymmetric baseline
  3. MF-GJR(VIX)          — current best (K889)
  4. CARR_YZ(1,1)          — K935 best range model
  5. CARR_YZ-MF(VIX)       — NEW: range + VIX multiplicative factor
  6. CARR_YZ-MF-A(VIX)     — NEW: above + asymmetric return effect

References:
  Yang & Zhang (2000) 'Drift Independent Volatility Estimation'
  Chou (2005) 'Forecasting Financial Volatilities with Extreme Values'
  Engle & Rangel (2008) 'The Spline-GARCH Model' — multiplicative decomposition
  Patton (2011) J. Econometrics 160 — proxy-robust QLIKE
  Harvey et al. (2016) 'Tests for Forecast Encompassing' — |t|>3.0

Data source: yfinance (SPY + ^VIX), OHLC daily
Period: 2004-01-01 ~ 2025-12-31
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000, Refit: every 21 trading days

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy.optimize import minimize
from scipy import stats

np.random.seed(42)
warnings.filterwarnings('ignore')

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)

# Add project root for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K939: CARR_YZ-MF(VIX) — Range + VIX Ultimate Combination")
print("=" * 60)

print("\n[1/7] Downloading data...")
spy = yf.download('SPY', start='2004-01-01', end='2026-01-01', progress=False)

# VIX download — use Ticker.history() which is more reliable
vix_ticker = yf.Ticker('^VIX')
vix = vix_ticker.history(start='2004-01-01', end='2026-01-01')
if vix is None or len(vix) == 0:
    raise RuntimeError("Cannot download VIX data")
# Normalize timezone-aware index to timezone-naive (match SPY)
if vix.index.tz is not None:
    vix.index = vix.index.tz_localize(None)
print(f"  VIX: {len(vix)} observations")

# Flatten multi-level columns if needed
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Log prices
spy['log_H'] = np.log(spy['High'])
spy['log_L'] = np.log(spy['Low'])
spy['log_O'] = np.log(spy['Open'])
spy['log_C'] = np.log(spy['Close'])

# Returns
spy['log_return'] = spy['log_C'] - spy['log_C'].shift(1)
spy['r2'] = spy['log_return'] ** 2

# Overnight return: log(Open_t / Close_{t-1})
spy['overnight_return'] = spy['log_O'] - spy['log_C'].shift(1)

# ============================================================
# 2. RANGE ESTIMATORS
# ============================================================
print("\n[2/7] Computing range estimators...")

# --- Parkinson (1980) ---
spy['range_parkinson'] = (spy['log_H'] - spy['log_L'])**2 / (4 * np.log(2))

# --- Rogers-Satchell (1991) ---
spy['range_rs'] = ((spy['log_H'] - spy['log_C']) * (spy['log_H'] - spy['log_O'])
                  + (spy['log_L'] - spy['log_C']) * (spy['log_L'] - spy['log_O']))

# --- Yang-Zhang (2000) ---
# sigma^2_YZ = sigma^2_overnight + k * sigma^2_open + (1-k) * sigma^2_RS
spy['overnight_sq'] = spy['overnight_return']**2
k_yz = 0.34 / (1.34 + 2.0)  # asymptotic k for large n
spy['open_var'] = ((spy['log_H'] - spy['log_O'])**2 + (spy['log_L'] - spy['log_O'])**2)
spy['range_yz'] = spy['overnight_sq'] + k_yz * spy['open_var'] + (1 - k_yz) * spy['range_rs']

# Add VIX
vix_close = vix['Close'].rename('VIX')
spy = spy.join(vix_close, how='left')
spy['VIX'] = spy['VIX'].ffill()
spy['log_VIX'] = np.log(spy['VIX'])

# Drop NaN
spy = spy.dropna(subset=['range_yz', 'log_return', 'r2', 'VIX', 'overnight_return'])

# Floor at small positive value
FLOOR = 1e-10
for col in ['range_parkinson', 'range_rs', 'range_yz']:
    spy[col] = np.maximum(spy[col], FLOOR)

print(f"  Total observations: {len(spy)}")
print(f"  Date range: {spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}")

# Descriptive statistics
print("\n  Descriptive Statistics:")
for name, col in [('YZ', 'range_yz'), ('r2', 'r2'), ('VIX', 'VIX')]:
    vals = spy[col]
    print(f"    {name:10s}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
          f"min={vals.min():.6f}, max={vals.max():.6f}")

# ============================================================
# 3. MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3/7] Implementing models...")


# --- Model 1: GARCH(1,1) ---
def garch_fit(returns, max_iter=500):
    """Fit GARCH(1,1) via MLE with Normal innovations."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r2
        for t in range(1, T):
            h[t] = omega + alpha * r[t - 1] ** 2 + beta * h[t - 1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = mean_r2 * 0.05
    x0 = [omega0, 0.08, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.92), (0.12, 0.85), (0.03, 0.95)]:
            x0_alt = [mean_r2 * 0.05, a0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def garch_forecast_oos(params, returns):
    """One-step-ahead GARCH forecast (recursive)."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(returns)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        h[t + 1] = omega + alpha * returns[t] ** 2 + beta * h[t]
        if h[t + 1] <= 1e-10:
            h[t + 1] = 1e-10
    return h[1:]


# --- Model 2: GJR-GARCH(1,1,1) ---
def gjr_fit(returns, max_iter=500):
    """Fit GJR-GARCH(1,1,1) via MLE."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5 * gamma + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - 0.5 * gamma - beta) if (alpha + 0.5 * gamma + beta) < 1 else mean_r2
        for t in range(1, T):
            shock = r[t - 1] ** 2
            asym = shock * (r[t - 1] < 0)
            h[t] = omega + alpha * shock + gamma * asym + beta * h[t - 1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = mean_r2 * 0.05
    x0 = [omega0, 0.02, 0.10, 0.85]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.0, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, g0, b0 in [(0.01, 0.15, 0.85), (0.05, 0.08, 0.88), (0.02, 0.12, 0.80)]:
            x0_alt = [mean_r2 * 0.05, a0, g0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, gamma, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta, 'converged': result.success,
            'loglik': -result.fun}


def gjr_forecast_oos(params, returns):
    """One-step-ahead GJR forecast (recursive)."""
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - 0.5 * gamma - beta, 0.01)
    for t in range(T):
        shock = returns[t] ** 2
        asym = shock * (returns[t] < 0)
        h[t + 1] = omega + alpha * shock + gamma * asym + beta * h[t]
        if h[t + 1] <= 1e-10:
            h[t + 1] = 1e-10
    return h[1:]


# --- Model 3: MF-GJR(VIX) --- current best from K889
def mf_gjr_fit(returns, log_vix, max_iter=500):
    """MF-GJR(VIX): h_t = tau_t * g_t where tau = exp(theta0 + theta1 * log_VIX)."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        theta0, theta1, omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5 * gamma + beta) >= 0.9999:
            return 1e10
        tau = np.exp(theta0 + theta1 * log_vix)
        tau = np.maximum(tau, 1e-16)
        g = np.zeros(T)
        g[0] = 1.0
        for t in range(1, T):
            shock = r[t - 1] ** 2 / tau[t - 1]
            asym = shock * (r[t - 1] < 0)
            g[t] = omega + alpha * shock + gamma * asym + beta * g[t - 1]
            if g[t] <= 1e-10:
                g[t] = 1e-10
        h = tau * g
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = 0.02
    x0 = [np.log(mean_r2) - 0.5 * np.mean(log_vix), 0.5, omega0, 0.02, 0.10, 0.85]
    bounds = [(None, None), (0.0, 3.0), (1e-8, None), (0.0, 0.5), (0.0, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1 in [0.3, 0.7, 1.0]:
            x0_alt = [x0[0], t1, 0.05, 0.02, 0.10, 0.85]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    theta0, theta1, omega, alpha, gamma, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta,
            'converged': result.success, 'loglik': -result.fun}


def mf_gjr_forecast_oos(params, returns, log_vix):
    """One-step-ahead MF-GJR forecast (recursive)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    tau = np.exp(theta0 + theta1 * log_vix)
    tau = np.maximum(tau, 1e-16)
    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        shock = returns[t] ** 2 / tau[t]
        asym = shock * (returns[t] < 0)
        g[t + 1] = omega + alpha * shock + gamma * asym + beta * g[t]
        if g[t + 1] <= 1e-10:
            g[t + 1] = 1e-10
    # Forecast for t+1: uses tau[t] (which uses VIX[t]) and g[t+1]
    # But tau for forecast day needs VIX at t (last known).
    # For 1-step-ahead: h_{t+1} = tau_{t+1} * g_{t+1}
    # tau_{t+1} = exp(theta0 + theta1 * log_VIX_t) — we use the latest VIX
    # Actually, tau uses concurrent VIX, but in forecast we need VIX at forecast time.
    # Standard approach: use lag-1 VIX for the forecast period.
    # The way K935 does it: tau is computed on the full history,
    # and g[t+1] uses info up to t. h = tau * g[1:]
    h = tau * g[1:]
    return h


# --- Model 4: CARR_YZ(1,1) --- from K935
def carr_yz_fit(yz_ranges, max_iter=500):
    """Fit CARR(1,1) on Yang-Zhang variance with Exponential innovation."""
    T = len(yz_ranges)
    mean_r = np.mean(yz_ranges)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        lam = np.zeros(T)
        lam[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r
        for t in range(1, T):
            lam[t] = omega + alpha * yz_ranges[t - 1] + beta * lam[t - 1]
            if lam[t] <= 1e-10:
                lam[t] = 1e-10
        ll = -np.log(lam) - yz_ranges / lam
        return -np.sum(ll[10:])

    omega0 = mean_r * 0.05
    x0 = [omega0, 0.10, 0.85]
    bounds = [(1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.90), (0.15, 0.80), (0.08, 0.88)]:
            x0_alt = [mean_r * 0.05, a0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def carr_yz_forecast_oos(params, yz_ranges):
    """One-step-ahead CARR_YZ forecast (recursive)."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(yz_ranges)
    lam = np.zeros(T + 1)
    lam[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        lam[t + 1] = omega + alpha * yz_ranges[t] + beta * lam[t]
        if lam[t + 1] <= 1e-10:
            lam[t + 1] = 1e-10
    return lam[1:]


# --- Model 5: CARR_YZ-MF(VIX) --- NEW
def carr_yz_mf_fit(yz_ranges, log_vix, max_iter=500):
    """
    CARR_YZ with VIX multiplicative factor:
      tau_t = exp(theta0 + theta1 * log(VIX_{t-1}))
      g_t = omega + alpha * (YZ_{t-1}/tau_{t-1}) + beta * g_{t-1}
      lambda_t = tau_t * g_t

    Exponential innovation: YZ_t / lambda_t ~ Exp(1)
    Log-likelihood: -log(lambda_t) - YZ_t / lambda_t
    """
    T = len(yz_ranges)
    mean_yz = np.mean(yz_ranges)

    def neg_loglik(params):
        theta0, theta1, omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10

        tau = np.exp(theta0 + theta1 * log_vix)
        tau = np.maximum(tau, 1e-16)

        g = np.zeros(T)
        g[0] = 1.0
        for t in range(1, T):
            normalized = yz_ranges[t - 1] / tau[t - 1]
            g[t] = omega + alpha * normalized + beta * g[t - 1]
            if g[t] <= 1e-10:
                g[t] = 1e-10

        lam = tau * g
        lam = np.maximum(lam, 1e-16)
        ll = -np.log(lam) - yz_ranges / lam
        return -np.sum(ll[10:])

    # Initial values
    theta0_init = np.log(mean_yz) - 0.5 * np.mean(log_vix)
    x0 = [theta0_init, 0.5, 0.02, 0.10, 0.85]
    bounds = [(None, None), (0.0, 3.0), (1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1 in [0.3, 0.7, 1.0, 1.5]:
            x0_alt = [theta0_init, t1, 0.05, 0.08, 0.88]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    theta0, theta1, omega, alpha, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta,
            'converged': result.success, 'loglik': -result.fun}


def carr_yz_mf_forecast_oos(params, yz_ranges, log_vix):
    """One-step-ahead CARR_YZ-MF(VIX) forecast (recursive)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(yz_ranges)

    tau = np.exp(theta0 + theta1 * log_vix)
    tau = np.maximum(tau, 1e-16)

    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        normalized = yz_ranges[t] / tau[t]
        g[t + 1] = omega + alpha * normalized + beta * g[t]
        if g[t + 1] <= 1e-10:
            g[t + 1] = 1e-10

    lam = tau * g[1:]
    return lam


# --- Model 6: CARR_YZ-MF-A(VIX) --- NEW with asymmetry
def carr_yz_mf_asym_fit(yz_ranges, log_vix, returns, max_iter=500):
    """
    CARR_YZ-MF(VIX) with asymmetric return effect:
      tau_t = exp(theta0 + theta1 * log(VIX_{t-1}))
      g_t = omega + alpha * (YZ_{t-1}/tau_{t-1}) + gamma * (YZ_{t-1}/tau_{t-1}) * I(r_{t-1}<0) + beta * g_{t-1}
      lambda_t = tau_t * g_t
    """
    T = len(yz_ranges)
    mean_yz = np.mean(yz_ranges)

    def neg_loglik(params):
        theta0, theta1, omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5 * gamma + beta) >= 0.9999:
            return 1e10

        tau = np.exp(theta0 + theta1 * log_vix)
        tau = np.maximum(tau, 1e-16)

        g = np.zeros(T)
        g[0] = 1.0
        for t in range(1, T):
            normalized = yz_ranges[t - 1] / tau[t - 1]
            asym = normalized * (returns[t - 1] < 0)
            g[t] = omega + alpha * normalized + gamma * asym + beta * g[t - 1]
            if g[t] <= 1e-10:
                g[t] = 1e-10

        lam = tau * g
        lam = np.maximum(lam, 1e-16)
        ll = -np.log(lam) - yz_ranges / lam
        return -np.sum(ll[10:])

    theta0_init = np.log(mean_yz) - 0.5 * np.mean(log_vix)
    x0 = [theta0_init, 0.5, 0.02, 0.05, 0.10, 0.85]
    bounds = [(None, None), (0.0, 3.0), (1e-8, None), (0.0, 0.5), (0.0, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1, g0 in [(0.3, 0.08), (0.7, 0.12), (1.0, 0.05), (1.5, 0.10)]:
            x0_alt = [theta0_init, t1, 0.05, 0.03, g0, 0.85]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    theta0, theta1, omega, alpha, gamma, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta,
            'converged': result.success, 'loglik': -result.fun}


def carr_yz_mf_asym_forecast_oos(params, yz_ranges, log_vix, returns):
    """One-step-ahead CARR_YZ-MF-A(VIX) forecast (recursive)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(yz_ranges)

    tau = np.exp(theta0 + theta1 * log_vix)
    tau = np.maximum(tau, 1e-16)

    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        normalized = yz_ranges[t] / tau[t]
        asym = normalized * (returns[t] < 0)
        g[t + 1] = omega + alpha * normalized + gamma * asym + beta * g[t]
        if g[t + 1] <= 1e-10:
            g[t + 1] = 1e-10

    lam = tau * g[1:]
    return lam


# ============================================================
# 4. OOS FORECASTING (Optimized: incremental state updates)
# ============================================================
print("\n[4/7] Running OOS forecasting (optimized)...")

oos_start = '2016-01-01'
oos_mask = spy.index >= oos_start
oos_idx = spy.index[oos_mask]
n_oos = len(oos_idx)
print(f"  OOS period: {oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')}")
print(f"  OOS days: {n_oos}")

WINDOW = 2000
REFIT = 21

# Storage for forecasts
model_names = ['GARCH', 'GJR', 'MF_GJR', 'CARR_YZ', 'CARR_YZ_MF', 'CARR_YZ_MF_A']
forecasts = {name: np.full(n_oos, np.nan) for name in model_names}

# Get all data arrays
returns_all = spy['log_return'].values
r2_all = spy['r2'].values
log_vix_all = spy['log_VIX'].values
yz_all = spy['range_yz'].values

# Find the position of first OOS observation
first_oos_pos = np.searchsorted(spy.index, pd.Timestamp(oos_start))

# Track model parameters and running state
model_params = {}
# Running state: last h/g/lam value for incremental updates
running_state = {}
n_refits = 0

for i in range(n_oos):
    t = first_oos_pos + i  # position in full array

    # Refit every REFIT days
    if i % REFIT == 0:
        train_start = max(0, t - WINDOW)
        train_end = t  # exclusive

        # Training data
        returns_train = returns_all[train_start:train_end]
        log_vix_train = log_vix_all[train_start:train_end]
        yz_train = yz_all[train_start:train_end]

        # 1. GARCH
        model_params['GARCH'] = garch_fit(returns_train)

        # 2. GJR
        model_params['GJR'] = gjr_fit(returns_train)

        # 3. MF-GJR(VIX)
        model_params['MF_GJR'] = mf_gjr_fit(returns_train, log_vix_train)

        # 4. CARR_YZ
        model_params['CARR_YZ'] = carr_yz_fit(yz_train)

        # 5. CARR_YZ-MF(VIX)
        model_params['CARR_YZ_MF'] = carr_yz_mf_fit(yz_train, log_vix_train)

        # 6. CARR_YZ-MF-A(VIX)
        model_params['CARR_YZ_MF_A'] = carr_yz_mf_asym_fit(yz_train, log_vix_train, returns_train)

        n_refits += 1
        if n_refits % 20 == 0:
            print(f"    Refit {n_refits}: t={i}/{n_oos}")

        # After refit, compute full recursion on training data to get running state
        # GARCH
        p = model_params['GARCH']
        h_garch = np.zeros(train_end - train_start + 1)
        h_garch[0] = p['omega'] / max(1 - p['alpha'] - p['beta'], 0.01)
        for tt in range(train_end - train_start):
            h_garch[tt + 1] = p['omega'] + p['alpha'] * returns_all[train_start + tt] ** 2 + p['beta'] * h_garch[tt]
            h_garch[tt + 1] = max(h_garch[tt + 1], 1e-10)
        running_state['GARCH_h'] = h_garch[-1]  # h at time t (forecast for t)

        # GJR
        p = model_params['GJR']
        h_gjr = np.zeros(train_end - train_start + 1)
        h_gjr[0] = p['omega'] / max(1 - p['alpha'] - 0.5 * p['gamma'] - p['beta'], 0.01)
        for tt in range(train_end - train_start):
            r_tt = returns_all[train_start + tt]
            shock = r_tt ** 2
            asym = shock * (r_tt < 0)
            h_gjr[tt + 1] = p['omega'] + p['alpha'] * shock + p['gamma'] * asym + p['beta'] * h_gjr[tt]
            h_gjr[tt + 1] = max(h_gjr[tt + 1], 1e-10)
        running_state['GJR_h'] = h_gjr[-1]

        # MF-GJR
        p = model_params['MF_GJR']
        tau_mf = np.exp(p['theta0'] + p['theta1'] * log_vix_all[train_start:train_end])
        tau_mf = np.maximum(tau_mf, 1e-16)
        g_mf = np.zeros(train_end - train_start + 1)
        g_mf[0] = 1.0
        for tt in range(train_end - train_start):
            r_tt = returns_all[train_start + tt]
            shock = r_tt ** 2 / tau_mf[tt]
            asym = shock * (r_tt < 0)
            g_mf[tt + 1] = p['omega'] + p['alpha'] * shock + p['gamma'] * asym + p['beta'] * g_mf[tt]
            g_mf[tt + 1] = max(g_mf[tt + 1], 1e-10)
        running_state['MF_GJR_g'] = g_mf[-1]

        # CARR_YZ
        p = model_params['CARR_YZ']
        lam_carr = np.zeros(train_end - train_start + 1)
        lam_carr[0] = p['omega'] / max(1 - p['alpha'] - p['beta'], 0.01)
        for tt in range(train_end - train_start):
            lam_carr[tt + 1] = p['omega'] + p['alpha'] * yz_all[train_start + tt] + p['beta'] * lam_carr[tt]
            lam_carr[tt + 1] = max(lam_carr[tt + 1], 1e-10)
        running_state['CARR_YZ_lam'] = lam_carr[-1]

        # CARR_YZ_MF
        p = model_params['CARR_YZ_MF']
        tau_cm = np.exp(p['theta0'] + p['theta1'] * log_vix_all[train_start:train_end])
        tau_cm = np.maximum(tau_cm, 1e-16)
        g_cm = np.zeros(train_end - train_start + 1)
        g_cm[0] = 1.0
        for tt in range(train_end - train_start):
            normalized = yz_all[train_start + tt] / tau_cm[tt]
            g_cm[tt + 1] = p['omega'] + p['alpha'] * normalized + p['beta'] * g_cm[tt]
            g_cm[tt + 1] = max(g_cm[tt + 1], 1e-10)
        running_state['CARR_YZ_MF_g'] = g_cm[-1]

        # CARR_YZ_MF_A
        p = model_params['CARR_YZ_MF_A']
        tau_ca = np.exp(p['theta0'] + p['theta1'] * log_vix_all[train_start:train_end])
        tau_ca = np.maximum(tau_ca, 1e-16)
        g_ca = np.zeros(train_end - train_start + 1)
        g_ca[0] = 1.0
        for tt in range(train_end - train_start):
            r_tt = returns_all[train_start + tt]
            normalized = yz_all[train_start + tt] / tau_ca[tt]
            asym = normalized * (r_tt < 0)
            g_ca[tt + 1] = p['omega'] + p['alpha'] * normalized + p['gamma'] * asym + p['beta'] * g_ca[tt]
            g_ca[tt + 1] = max(g_ca[tt + 1], 1e-10)
        running_state['CARR_YZ_MF_A_g'] = g_ca[-1]

    else:
        # Incremental update: update running state with new observation at t-1
        # (The observation at position t-1 has just become available)
        prev_t = t - 1  # last observed position
        r_prev = returns_all[prev_t]
        yz_prev = yz_all[prev_t]
        log_vix_prev = log_vix_all[prev_t]

        # GARCH
        p = model_params['GARCH']
        h_old = running_state['GARCH_h']
        h_new = p['omega'] + p['alpha'] * r_prev ** 2 + p['beta'] * h_old
        running_state['GARCH_h'] = max(h_new, 1e-10)

        # GJR
        p = model_params['GJR']
        h_old = running_state['GJR_h']
        shock = r_prev ** 2
        asym = shock * (r_prev < 0)
        h_new = p['omega'] + p['alpha'] * shock + p['gamma'] * asym + p['beta'] * h_old
        running_state['GJR_h'] = max(h_new, 1e-10)

        # MF-GJR
        p = model_params['MF_GJR']
        g_old = running_state['MF_GJR_g']
        tau_prev = max(np.exp(p['theta0'] + p['theta1'] * log_vix_prev), 1e-16)
        shock = r_prev ** 2 / tau_prev
        asym = shock * (r_prev < 0)
        g_new = p['omega'] + p['alpha'] * shock + p['gamma'] * asym + p['beta'] * g_old
        running_state['MF_GJR_g'] = max(g_new, 1e-10)

        # CARR_YZ
        p = model_params['CARR_YZ']
        lam_old = running_state['CARR_YZ_lam']
        lam_new = p['omega'] + p['alpha'] * yz_prev + p['beta'] * lam_old
        running_state['CARR_YZ_lam'] = max(lam_new, 1e-10)

        # CARR_YZ_MF
        p = model_params['CARR_YZ_MF']
        g_old = running_state['CARR_YZ_MF_g']
        tau_prev = max(np.exp(p['theta0'] + p['theta1'] * log_vix_prev), 1e-16)
        normalized = yz_prev / tau_prev
        g_new = p['omega'] + p['alpha'] * normalized + p['beta'] * g_old
        running_state['CARR_YZ_MF_g'] = max(g_new, 1e-10)

        # CARR_YZ_MF_A
        p = model_params['CARR_YZ_MF_A']
        g_old = running_state['CARR_YZ_MF_A_g']
        tau_prev = max(np.exp(p['theta0'] + p['theta1'] * log_vix_prev), 1e-16)
        normalized = yz_prev / tau_prev
        asym = normalized * (r_prev < 0)
        g_new = p['omega'] + p['alpha'] * normalized + p['gamma'] * asym + p['beta'] * g_old
        running_state['CARR_YZ_MF_A_g'] = max(g_new, 1e-10)

    # Store forecasts
    # GARCH: forecast = h_{t} (current running state = forecast for today)
    forecasts['GARCH'][i] = running_state['GARCH_h']

    # GJR: forecast = h_{t}
    forecasts['GJR'][i] = running_state['GJR_h']

    # MF-GJR: forecast = tau_t * g_t
    p = model_params['MF_GJR']
    tau_t = max(np.exp(p['theta0'] + p['theta1'] * log_vix_all[t-1]), 1e-16)  # use VIX_{t-1} for forecast
    forecasts['MF_GJR'][i] = tau_t * running_state['MF_GJR_g']

    # CARR_YZ: forecast = lam_t
    forecasts['CARR_YZ'][i] = running_state['CARR_YZ_lam']

    # CARR_YZ_MF: forecast = tau_t * g_t
    p = model_params['CARR_YZ_MF']
    tau_t = max(np.exp(p['theta0'] + p['theta1'] * log_vix_all[t-1]), 1e-16)
    forecasts['CARR_YZ_MF'][i] = tau_t * running_state['CARR_YZ_MF_g']

    # CARR_YZ_MF_A: forecast = tau_t * g_t
    p = model_params['CARR_YZ_MF_A']
    tau_t = max(np.exp(p['theta0'] + p['theta1'] * log_vix_all[t-1]), 1e-16)
    forecasts['CARR_YZ_MF_A'][i] = tau_t * running_state['CARR_YZ_MF_A_g']

print(f"  Total refits: {n_refits}")

# ============================================================
# 5. EVALUATION
# ============================================================
print("\n[5/7] Evaluating models...")

# Target: r² (Patton 2011 proxy-robust)
actual_r2 = r2_all[first_oos_pos:first_oos_pos + n_oos]
actual_yz = yz_all[first_oos_pos:first_oos_pos + n_oos]

# --- Layer 1: Native target QLIKE ---
print("\n  Layer 1: Native Target QLIKE")
native_qlike = {}
# Return-based models on r²
for model_name in ['GARCH', 'GJR', 'MF_GJR']:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_r2) & (fcast > 0) & (actual_r2 > 0)
    q = qlike(actual_r2[valid], fcast[valid])
    native_qlike[model_name] = q
    print(f"    {model_name:18s} on r2:       QLIKE={q:.6f}")

# Range-based models on YZ range
for model_name in ['CARR_YZ', 'CARR_YZ_MF', 'CARR_YZ_MF_A']:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_yz) & (fcast > 0) & (actual_yz > 0)
    q = qlike(actual_yz[valid], fcast[valid])
    native_qlike[model_name] = q
    print(f"    {model_name:18s} on YZ:       QLIKE={q:.6f}")

# --- Layer 2: QLIKE on r² (Patton 2011 — fair cross-model comparison) ---
print("\n  Layer 2: QLIKE on r2 (Patton 2011)")
qlike_r2 = {}
for model_name in model_names:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_r2) & (fcast > 0) & (actual_r2 > 0)
    q = qlike(actual_r2[valid], fcast[valid])
    qlike_r2[model_name] = q
    print(f"    {model_name:18s}: QLIKE={q:.6f}")

# Ranking
ranking = sorted(qlike_r2.items(), key=lambda x: x[1])
print("\n  Ranking (lower = better):")
for rank, (model, q) in enumerate(ranking, 1):
    marker = " <-- BEST" if rank == 1 else ""
    print(f"    {rank}. {model:18s}: {q:.6f}{marker}")

# --- Layer 3: Spearman rank correlation ---
print("\n  Layer 3: Spearman rank correlation with r2")
spearman_results = {}
for model_name in model_names:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_r2)
    rho, pval = stats.spearmanr(fcast[valid], actual_r2[valid])
    spearman_results[model_name] = {'rho': round(rho, 4), 'pval': round(pval, 6)}
    print(f"    {model_name:18s}: rho={rho:.4f}, p={pval:.2e}")

# --- Layer 4: DM tests (Harvey |t| > 3.0) ---
print("\n  Layer 4: DM tests (Harvey threshold |t| > 3.0)")

# Key comparisons
dm_results = {}
key_pairs = [
    ('CARR_YZ_MF', 'MF_GJR'),      # THE KEY TEST: range+VIX vs return+VIX
    ('CARR_YZ_MF_A', 'MF_GJR'),    # Asymmetric range+VIX vs return+VIX
    ('CARR_YZ_MF', 'CARR_YZ'),     # Does VIX help the range model?
    ('CARR_YZ_MF_A', 'CARR_YZ_MF'),# Does asymmetry help?
    ('MF_GJR', 'GJR'),             # Does VIX help the return model?
    ('MF_GJR', 'GARCH'),           # MF-GJR vs GARCH baseline
    ('CARR_YZ', 'GARCH'),          # Range vs return baseline
    ('CARR_YZ_MF', 'GARCH'),       # Range+VIX vs return baseline
]

for m1, m2 in key_pairs:
    f1 = forecasts[m1]
    f2 = forecasts[m2]
    valid = (np.isfinite(f1) & np.isfinite(f2) & np.isfinite(actual_r2)
             & (f1 > 0) & (f2 > 0) & (actual_r2 > 0))
    loss1 = qlike_pointwise(actual_r2[valid], f1[valid])
    loss2 = qlike_pointwise(actual_r2[valid], f2[valid])
    t_stat, p_val = dm_test(loss1, loss2)

    significant = abs(t_stat) > 3.0
    if t_stat < 0:
        winner = m1 if significant else "n.s."
    else:
        winner = m2 if significant else "n.s."

    key = f"{m1} vs {m2}"
    dm_results[key] = {
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 6),
        'significant': significant,
        'winner': winner
    }
    sig_marker = "***" if significant else ""
    print(f"    {key:40s}: t={t_stat:7.4f}, p={p_val:.4f} {sig_marker} -> {winner}")

# --- Key comparison summaries ---
print("\n  === KEY COMPARISONS ===")

# CARR_YZ-MF(VIX) vs MF-GJR(VIX) — the main question
q_carr_mf = qlike_r2['CARR_YZ_MF']
q_mf_gjr = qlike_r2['MF_GJR']
diff_pct = (q_carr_mf - q_mf_gjr) / q_mf_gjr * 100
print(f"\n  1. CARR_YZ-MF(VIX) vs MF-GJR(VIX) [THE KEY TEST]:")
print(f"     CARR_YZ-MF:  QLIKE={q_carr_mf:.6f}")
print(f"     MF-GJR:      QLIKE={q_mf_gjr:.6f}")
print(f"     Difference:   {diff_pct:+.2f}%")
dm_key = dm_results.get('CARR_YZ_MF vs MF_GJR', {})
print(f"     DM test: t={dm_key.get('t_stat', 'N/A')}, winner={dm_key.get('winner', 'N/A')}")

# CARR_YZ-MF-A(VIX) vs MF-GJR(VIX)
q_carr_mf_a = qlike_r2['CARR_YZ_MF_A']
diff_pct_a = (q_carr_mf_a - q_mf_gjr) / q_mf_gjr * 100
print(f"\n  2. CARR_YZ-MF-A(VIX) vs MF-GJR(VIX):")
print(f"     CARR_YZ-MF-A: QLIKE={q_carr_mf_a:.6f}")
print(f"     MF-GJR:       QLIKE={q_mf_gjr:.6f}")
print(f"     Difference:    {diff_pct_a:+.2f}%")

# VIX effect on CARR_YZ
q_carr = qlike_r2['CARR_YZ']
vix_effect_pct = (q_carr - q_carr_mf) / q_carr * 100
print(f"\n  3. VIX Multiplicative Factor Effect on CARR_YZ:")
print(f"     CARR_YZ:       QLIKE={q_carr:.6f}")
print(f"     CARR_YZ-MF:    QLIKE={q_carr_mf:.6f}")
print(f"     Improvement:   {vix_effect_pct:+.2f}%")

# ============================================================
# 6. VISUALIZATION
# ============================================================
print("\n[6/7] Creating visualization...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K939: CARR_YZ-MF(VIX) — Range + VIX Ultimate Test\n'
             'SPY OOS 2016-2026, Patton (2011) QLIKE on r$^2$', fontsize=13, fontweight='bold')

# Plot 1: QLIKE on r2 bar chart
ax = axes[0, 0]
models_sorted = [m for m, _ in ranking]
qlike_vals = [qlike_r2[m] for m in models_sorted]
colors = []
for m in models_sorted:
    if 'MF_A' in m:
        colors.append('#9b59b6')  # purple for asymmetric
    elif 'MF' in m and 'CARR' in m:
        colors.append('#e74c3c')  # red for CARR_YZ_MF
    elif 'CARR' in m:
        colors.append('#3498db')  # blue for CARR_YZ
    elif 'MF' in m:
        colors.append('#2ecc71')  # green for MF-GJR
    elif 'GJR' in m:
        colors.append('#27ae60')  # dark green for GJR
    else:
        colors.append('#95a5a6')  # gray for GARCH

bars = ax.barh(range(len(models_sorted)), qlike_vals, color=colors, edgecolor='white', linewidth=0.5)
ax.set_yticks(range(len(models_sorted)))
ax.set_yticklabels(models_sorted, fontsize=9)
ax.set_xlabel('QLIKE on r$^2$ (lower = better)')
ax.set_title('QLIKE on r$^2$ Ranking')
ax.invert_yaxis()
for bar, val in zip(bars, qlike_vals):
    ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
            f'{val:.4f}', va='center', fontsize=8)

# Plot 2: Spearman rho bar chart
ax = axes[0, 1]
spearman_sorted = sorted(spearman_results.items(), key=lambda x: x[1]['rho'], reverse=True)
models_sp = [m for m, _ in spearman_sorted]
rho_vals = [v['rho'] for _, v in spearman_sorted]
colors_sp = []
for m in models_sp:
    if 'MF_A' in m:
        colors_sp.append('#9b59b6')
    elif 'MF' in m and 'CARR' in m:
        colors_sp.append('#e74c3c')
    elif 'CARR' in m:
        colors_sp.append('#3498db')
    elif 'MF' in m:
        colors_sp.append('#2ecc71')
    elif 'GJR' in m:
        colors_sp.append('#27ae60')
    else:
        colors_sp.append('#95a5a6')

bars = ax.barh(range(len(models_sp)), rho_vals, color=colors_sp, edgecolor='white', linewidth=0.5)
ax.set_yticks(range(len(models_sp)))
ax.set_yticklabels(models_sp, fontsize=9)
ax.set_xlabel('Spearman rho (higher = better)')
ax.set_title('Spearman Rank Correlation with r$^2$')
ax.invert_yaxis()
for bar, val in zip(bars, rho_vals):
    ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height()/2,
            f'{val:.4f}', va='center', fontsize=8)

# Plot 3: Cumulative QLIKE difference — CARR_YZ_MF vs MF_GJR
ax = axes[1, 0]
comparisons = [
    ('CARR_YZ_MF', 'MF_GJR', '#e74c3c', '-', 'CARR_YZ_MF vs MF_GJR'),
    ('CARR_YZ_MF_A', 'MF_GJR', '#9b59b6', '--', 'CARR_YZ_MF_A vs MF_GJR'),
    ('CARR_YZ_MF', 'CARR_YZ', '#3498db', '-.', 'CARR_YZ_MF vs CARR_YZ'),
]

for m1, m2, color, ls, label in comparisons:
    f1 = forecasts[m1]
    f2 = forecasts[m2]
    valid = (np.isfinite(f1) & np.isfinite(f2) & np.isfinite(actual_r2)
             & (f1 > 0) & (f2 > 0) & (actual_r2 > 0))
    loss1 = qlike_pointwise(actual_r2[valid], f1[valid])
    loss2 = qlike_pointwise(actual_r2[valid], f2[valid])
    cum_diff = np.cumsum(loss2 - loss1)  # positive = m1 better
    ax.plot(cum_diff, color=color, linestyle=ls, linewidth=1.2, label=label)

ax.axhline(y=0, color='gray', linestyle=':', linewidth=0.5)
ax.set_xlabel('OOS day index')
ax.set_ylabel('Cumulative QLIKE difference')
ax.set_title('Cumulative QLIKE: model2 - model1\n(positive = model1 better)')
ax.legend(fontsize=7, loc='best')

# Plot 4: Time series comparison (sample window)
ax = axes[1, 1]
window_start = 500
window_end = 700
t_range = range(window_start, window_end)
ax.plot(t_range, actual_r2[window_start:window_end], 'k-', alpha=0.3, linewidth=0.5, label='Actual r$^2$')
for model_name, color, ls in [
    ('GARCH', '#95a5a6', ':'),
    ('MF_GJR', '#2ecc71', '-'),
    ('CARR_YZ', '#3498db', '--'),
    ('CARR_YZ_MF', '#e74c3c', '-'),
    ('CARR_YZ_MF_A', '#9b59b6', '-.'),
]:
    fcast = forecasts[model_name]
    ax.plot(t_range, fcast[window_start:window_end], ls, color=color,
            linewidth=1.0, alpha=0.8, label=model_name)
ax.set_xlabel('OOS day index')
ax.set_ylabel('Variance forecast')
ax.set_title('Forecast Comparison (sample window)')
ax.legend(fontsize=7, loc='upper right')
ax.set_ylim(bottom=0)

plt.tight_layout()
chart_path = os.path.join(SCRIPT_DIR, 'k939_comparison.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved: {chart_path}")

# ============================================================
# 7. SAVE RESULTS
# ============================================================
print("\n[7/7] Saving results...")

# Last-fit parameters
last_fit_params = {}
for model_name in model_names:
    if model_name in model_params:
        p = model_params[model_name]
        last_fit_params[model_name] = {k: round(v, 8) if isinstance(v, float) else v
                                       for k, v in p.items()}

# Determine conclusions
best_model = ranking[0][0]
best_qlike = ranking[0][1]

# H1: CARR_YZ-MF(VIX) < MF-GJR(VIX)?
h1_result = q_carr_mf < q_mf_gjr
h1_dm = dm_results.get('CARR_YZ_MF vs MF_GJR', {})
h1_significant = h1_dm.get('significant', False) and h1_dm.get('winner', '') == 'CARR_YZ_MF'

# H0: VIX dominates?
h0_evidence = abs(diff_pct) < 5.0 and not h1_significant

results = {
    "experiment_id": "K939",
    "title": "CARR_YZ-MF(VIX) — Range + VIX Ultimate Combination",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (SPY + ^VIX)",
    "period": f"{spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}",
    "oos_period": f"{oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')}",
    "oos_days": int(n_oos),
    "window": WINDOW,
    "refit_every": REFIT,
    "n_refits": int(n_refits),
    "models": {
        "GARCH": "GARCH(1,1) baseline",
        "GJR": "GJR(1,1,1) asymmetric baseline",
        "MF_GJR": "MF-GJR(VIX) — current best (K889)",
        "CARR_YZ": "CARR(1,1) on Yang-Zhang variance (K935)",
        "CARR_YZ_MF": "CARR_YZ with VIX multiplicative factor (NEW)",
        "CARR_YZ_MF_A": "CARR_YZ-MF(VIX) + asymmetric return effect (NEW)"
    },
    "references": [
        "Yang & Zhang (2000) 'Drift Independent Volatility Estimation'",
        "Chou (2005) 'Forecasting Financial Volatilities with Extreme Values'",
        "Engle & Rangel (2008) 'The Spline-GARCH Model'",
        "Patton (2011) J. Econometrics 160",
        "Harvey et al. (2016) 'Tests for Forecast Encompassing'"
    ],
    "model_parameters_last_fit": last_fit_params,
    "layer1_native_target_qlike": {k: round(v, 6) for k, v in native_qlike.items()},
    "layer2_qlike_on_r2": {k: round(v, 6) for k, v in qlike_r2.items()},
    "layer2_ranking": [
        {"rank": i+1, "model": m, "qlike": round(q, 6)}
        for i, (m, q) in enumerate(ranking)
    ],
    "layer3_spearman": spearman_results,
    "layer4_dm_tests": dm_results,
    "key_comparisons": {
        "CARR_YZ_MF_vs_MF_GJR": {
            "carr_yz_mf_qlike": round(q_carr_mf, 6),
            "mf_gjr_qlike": round(q_mf_gjr, 6),
            "difference_pct": round(diff_pct, 2),
            "dm_t_stat": dm_results.get('CARR_YZ_MF vs MF_GJR', {}).get('t_stat', None),
            "dm_significant": dm_results.get('CARR_YZ_MF vs MF_GJR', {}).get('significant', None),
        },
        "CARR_YZ_MF_A_vs_MF_GJR": {
            "carr_yz_mf_a_qlike": round(q_carr_mf_a, 6),
            "mf_gjr_qlike": round(q_mf_gjr, 6),
            "difference_pct": round(diff_pct_a, 2),
        },
        "VIX_effect_on_CARR_YZ": {
            "carr_yz_qlike": round(q_carr, 6),
            "carr_yz_mf_qlike": round(q_carr_mf, 6),
            "improvement_pct": round(vix_effect_pct, 2),
        }
    },
    "conclusions": {
        "H1_CARR_YZ_MF_beats_MF_GJR": h1_result,
        "H1_statistically_significant": h1_significant,
        "H0_VIX_dominates": h0_evidence,
        "best_model": best_model,
        "best_qlike": round(best_qlike, 6),
        "interpretation": None  # will be filled below
    }
}

# Interpretation
if h1_significant:
    interpretation = (
        f"CARR_YZ-MF(VIX) significantly outperforms MF-GJR(VIX) "
        f"(QLIKE {q_carr_mf:.4f} vs {q_mf_gjr:.4f}, DM t={h1_dm.get('t_stat', 'N/A')}). "
        f"Yang-Zhang range provides incremental information beyond returns when combined with VIX."
    )
elif h1_result and not h1_significant:
    interpretation = (
        f"CARR_YZ-MF(VIX) has lower QLIKE ({q_carr_mf:.4f}) than MF-GJR(VIX) ({q_mf_gjr:.4f}), "
        f"but the difference is not statistically significant (Harvey |t|>3.0). "
        f"Range adds marginal improvement, VIX is the main driver."
    )
else:
    interpretation = (
        f"MF-GJR(VIX) remains superior (QLIKE {q_mf_gjr:.4f} vs {q_carr_mf:.4f}). "
        f"Close-to-close returns capture information that range estimators miss "
        f"(e.g., direction, sign). VIX is the dominant external factor."
    )

results["conclusions"]["interpretation"] = interpretation

results_path = os.path.join(SCRIPT_DIR, 'k939_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"  Results saved: {results_path}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"\n  Overall Ranking (QLIKE on r2):")
for i, (m, q) in enumerate(ranking, 1):
    marker = " <-- BEST" if i == 1 else ""
    print(f"    {i}. {m:18s}: {q:.6f}{marker}")

print(f"\n  Key Test: CARR_YZ-MF(VIX) vs MF-GJR(VIX)")
print(f"    QLIKE diff: {diff_pct:+.2f}%")
print(f"    H1 (range+VIX > return+VIX): {h1_result}")
print(f"    Statistically significant: {h1_significant}")

print(f"\n  VIX effect on CARR_YZ: {vix_effect_pct:+.2f}%")
print(f"\n  Interpretation: {interpretation}")
print("\nDone.")
