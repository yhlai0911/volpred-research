"""
K934: CARR Conditional Autoregressive Range Model
Range-Based Volatility Prediction vs GARCH/GJR

Reference: Chou (2005) "Forecasting Financial Volatilities with Extreme Values"
           Parkinson (1980) range efficiency ~5x vs squared return
           Patton (2011) proxy-robust QLIKE on r²

Data source: yfinance (SPY + ^VIX), OHLC daily
Period: 2006-01-01 ~ 2025-12-31
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000
Refit: every 21 trading days

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import sys
from datetime import datetime
from scipy.optimize import minimize
from scipy import stats

np.random.seed(42)
warnings.filterwarnings('ignore')

# Add project root for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

import yfinance as yf

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K934: CARR Model — Range-Based Volatility Prediction")
print("=" * 60)

print("\n[1/6] Downloading data...")
spy = yf.download('SPY', start='2004-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2004-01-01', end='2026-01-01', progress=False)

# Flatten multi-level columns if needed
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Compute log range and returns
spy['log_range'] = np.log(spy['High']) - np.log(spy['Low'])
spy['log_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['r2'] = spy['log_return'] ** 2  # squared return (proxy for σ²)
spy['parkinson_var'] = spy['log_range'] ** 2 / (4 * np.log(2))  # Parkinson variance

# Add VIX (lagged by 1 day for models that use it)
vix_close = vix['Close'].rename('VIX')
spy = spy.join(vix_close, how='left')
spy['VIX'] = spy['VIX'].ffill()
spy['log_VIX'] = np.log(spy['VIX'])

spy = spy.dropna(subset=['log_range', 'log_return', 'r2', 'VIX'])
print(f"  Total observations: {len(spy)}")
print(f"  Date range: {spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}")

# Descriptive statistics
print("\n  Descriptive Statistics (full sample):")
print(f"    log_range: mean={spy['log_range'].mean():.6f}, std={spy['log_range'].std():.6f}")
print(f"    r2:        mean={spy['r2'].mean():.6f}, std={spy['r2'].std():.6f}")
print(f"    parkinson: mean={spy['parkinson_var'].mean():.6f}, std={spy['parkinson_var'].std():.6f}")
print(f"    VIX:       mean={spy['VIX'].mean():.2f}, std={spy['VIX'].std():.2f}")

# Efficiency ratio: Var(Parkinson) / Var(r²)
corr_pk_r2 = np.corrcoef(spy['parkinson_var'].values, spy['r2'].values)[0, 1]
print(f"    corr(Parkinson, r²): {corr_pk_r2:.4f}")

# ============================================================
# 2. MODEL IMPLEMENTATIONS
# ============================================================
print("\n[2/6] Implementing models...")

# --- CARR(1,1) with Exponential distribution ---
def carr_fit(ranges, max_iter=500):
    """Fit CARR(1,1) with Exponential innovation.
    Range_t = lambda_t * epsilon_t, epsilon_t ~ Exp(1)
    lambda_t = omega + alpha * Range_{t-1} + beta * lambda_{t-1}
    Log-likelihood: sum(-log(lambda_t) - Range_t / lambda_t)
    """
    T = len(ranges)
    mean_r = np.mean(ranges)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        lam = np.zeros(T)
        lam[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r
        for t in range(1, T):
            lam[t] = omega + alpha * ranges[t - 1] + beta * lam[t - 1]
            if lam[t] <= 1e-10:
                lam[t] = 1e-10
        ll = -np.log(lam) - ranges / lam
        return -np.sum(ll[10:])  # skip first 10 for burn-in

    # Starting values
    omega0 = mean_r * 0.05
    alpha0 = 0.10
    beta0 = 0.85
    x0 = [omega0, alpha0, beta0]

    bounds = [(1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        # Try alternative starting values
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


def carr_forecast(params, ranges):
    """One-step-ahead CARR forecast (recursive)."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(ranges)
    lam = np.zeros(T + 1)
    lam[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        lam[t + 1] = omega + alpha * ranges[t] + beta * lam[t]
        if lam[t + 1] <= 1e-10:
            lam[t + 1] = 1e-10
    return lam[1:]  # forecasts for t=1,...,T (using info up to t-1)


# --- CARR-MF(VIX): Multiplicative Factor CARR ---
def carr_mf_fit(ranges, log_vix, max_iter=500):
    """CARR-MF(VIX):
    lambda_t = tau_t * g_t
    tau_t = exp(theta0 + theta1 * log_VIX_{t-1})
    g_t = omega + alpha * (Range_{t-1}/tau_{t-1}) + beta * g_{t-1}
    """
    T = len(ranges)
    mean_r = np.mean(ranges)

    def neg_loglik(params):
        theta0, theta1, omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10

        # Long-run component (use lagged VIX)
        tau = np.exp(theta0 + theta1 * log_vix)
        tau = np.maximum(tau, 1e-10)

        # Short-run component
        g = np.zeros(T)
        g[0] = 1.0  # unconditional mean of g is 1
        for t in range(1, T):
            g[t] = omega + alpha * (ranges[t - 1] / tau[t - 1]) + beta * g[t - 1]
            if g[t] <= 1e-10:
                g[t] = 1e-10

        lam = tau * g
        ll = -np.log(lam) - ranges / lam
        return -np.sum(ll[10:])

    # Starting values
    theta0_0 = np.log(mean_r) - 0.5 * np.mean(log_vix)
    theta1_0 = 0.5
    omega0 = 0.05
    alpha0 = 0.08
    beta0 = 0.85

    x0 = [theta0_0, theta1_0, omega0, alpha0, beta0]
    bounds = [(None, None), (0.0, 3.0), (1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1 in [0.3, 0.7, 1.0]:
            x0_alt = [theta0_0, t1, 0.05, 0.08, 0.85]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    theta0, theta1, omega, alpha, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'beta': beta, 'persistence': alpha + beta,
            'converged': result.success, 'loglik': -result.fun}


def carr_mf_forecast(params, ranges, log_vix):
    """One-step-ahead CARR-MF forecast (recursive)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(ranges)

    tau = np.exp(theta0 + theta1 * log_vix)
    tau = np.maximum(tau, 1e-10)

    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        g[t + 1] = omega + alpha * (ranges[t] / tau[t]) + beta * g[t]
        if g[t + 1] <= 1e-10:
            g[t + 1] = 1e-10

    # Forecast for t+1: use tau[t] (lagged VIX) * g[t+1]
    # But we need tau for the forecast date. Since we use lagged VIX,
    # tau_{t+1} uses VIX_t which is known at t.
    # For OOS, we'll compute this in the main loop.
    lam_forecast = tau * g[1:]  # this uses concurrent tau, need adjustment in OOS
    return lam_forecast


# --- GARCH(1,1) ---
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
        h[0] = omega / max(1 - alpha - beta, 0.01)
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
    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def garch_forecast(params, returns):
    """One-step-ahead GARCH(1,1) forecast (recursive)."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(returns)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        h[t + 1] = omega + alpha * returns[t] ** 2 + beta * h[t]
        if h[t + 1] <= 1e-10:
            h[t + 1] = 1e-10
    return h[1:]


# --- GJR-GARCH(1,1,1) ---
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
        h[0] = omega / max(1 - alpha - 0.5 * gamma - beta, 0.01)
        for t in range(1, T):
            shock = r[t - 1] ** 2
            asym = shock * (r[t - 1] < 0)
            h[t] = omega + alpha * shock + gamma * asym + beta * h[t - 1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = mean_r2 * 0.05
    x0 = [omega0, 0.03, 0.10, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})
    omega, alpha, gamma, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta,
            'converged': result.success, 'loglik': -result.fun}


def gjr_forecast(params, returns):
    """One-step-ahead GJR forecast (recursive)."""
    omega = params['omega']
    alpha, gamma, beta = params['alpha'], params['gamma'], params['beta']
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


# --- MF-GJR(VIX): Multiplicative Factor GJR ---
def mf_gjr_fit(returns, log_vix, max_iter=500):
    """MF-GJR:
    sigma2_t = tau_t * g_t
    tau_t = exp(theta0 + theta1 * log_VIX_{t-1})
    g_t = omega + alpha * (r²_{t-1}/tau_{t-1}) + gamma * I_{t-1} * (r²_{t-1}/tau_{t-1}) + beta * g_{t-1}
    """
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
        tau = np.maximum(tau, 1e-10)

        g = np.zeros(T)
        g[0] = 1.0
        for t in range(1, T):
            r2_norm = r[t - 1] ** 2 / tau[t - 1]
            asym = r2_norm * (r[t - 1] < 0)
            g[t] = omega + alpha * r2_norm + gamma * asym + beta * g[t - 1]
            if g[t] <= 1e-10:
                g[t] = 1e-10

        h = tau * g
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    theta0_0 = np.log(mean_r2) - 0.5 * np.mean(log_vix)
    x0 = [theta0_0, 1.0, 0.05, 0.03, 0.08, 0.85]
    bounds = [(None, None), (0.0, 5.0), (1e-8, None),
              (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1 in [0.5, 1.5, 2.0]:
            x0_alt = [theta0_0, t1, 0.05, 0.03, 0.08, 0.85]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    theta0, theta1, omega, alpha, gamma, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta,
            'converged': result.success, 'loglik': -result.fun}


def mf_gjr_forecast(params, returns, log_vix):
    """One-step-ahead MF-GJR forecast (recursive)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)

    tau = np.exp(theta0 + theta1 * log_vix)
    tau = np.maximum(tau, 1e-10)

    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        r2_norm = returns[t] ** 2 / tau[t]
        asym = r2_norm * (returns[t] < 0)
        g[t + 1] = omega + alpha * r2_norm + gamma * asym + beta * g[t]
        if g[t + 1] <= 1e-10:
            g[t + 1] = 1e-10

    h_forecast = tau * g[1:]
    return h_forecast


# ============================================================
# 3. OOS EVALUATION
# ============================================================
print("\n[3/6] Running OOS evaluation...")

# OOS period
oos_start = '2016-01-01'
oos_mask = spy.index >= oos_start
oos_dates = spy.index[oos_mask]

WINDOW = 2000
REFIT_EVERY = 21

# Prepare arrays
all_ranges = spy['log_range'].values
all_returns = spy['log_return'].values
all_log_vix = spy['log_VIX'].values
all_r2 = spy['r2'].values
all_parkinson = spy['parkinson_var'].values
dates = spy.index

# Find OOS start index
oos_start_idx = np.searchsorted(dates, pd.Timestamp(oos_start))
print(f"  OOS start index: {oos_start_idx}, date: {dates[oos_start_idx].strftime('%Y-%m-%d')}")
print(f"  OOS end: {dates[-1].strftime('%Y-%m-%d')}")
print(f"  OOS days: {len(dates) - oos_start_idx}")

# Storage for forecasts
n_oos = len(dates) - oos_start_idx
forecasts = {
    'CARR': np.zeros(n_oos),
    'CARR_MF': np.zeros(n_oos),
    'GARCH': np.zeros(n_oos),
    'GJR': np.zeros(n_oos),
    'MF_GJR': np.zeros(n_oos),
}
# CARR forecasts in range space (for native target evaluation)
range_forecasts = {
    'CARR': np.zeros(n_oos),
    'CARR_MF': np.zeros(n_oos),
}

actual_r2 = all_r2[oos_start_idx:]
actual_range = all_ranges[oos_start_idx:]
actual_parkinson = all_parkinson[oos_start_idx:]

# Model parameters storage (for reporting)
model_params = {}

# Rolling OOS
last_fit = -999  # force first fit
n_refits = 0

for i in range(n_oos):
    t = oos_start_idx + i  # absolute index

    if t < WINDOW:
        # Not enough data — use simple forecast
        forecasts['CARR'][i] = np.mean(all_ranges[:t]) if t > 0 else 0.01
        forecasts['CARR_MF'][i] = forecasts['CARR'][i]
        forecasts['GARCH'][i] = np.mean(all_r2[:t]) if t > 0 else 1e-4
        forecasts['GJR'][i] = forecasts['GARCH'][i]
        forecasts['MF_GJR'][i] = forecasts['GARCH'][i]
        range_forecasts['CARR'][i] = forecasts['CARR'][i]
        range_forecasts['CARR_MF'][i] = forecasts['CARR_MF'][i]
        continue

    # Refit check
    if (i - last_fit) >= REFIT_EVERY or last_fit < 0:
        train_start = t - WINDOW
        train_ranges = all_ranges[train_start:t]
        train_returns = all_returns[train_start:t]
        train_log_vix = all_log_vix[train_start:t]

        # Fit all models
        carr_params = carr_fit(train_ranges)
        carr_mf_params = carr_mf_fit(train_ranges, train_log_vix)
        garch_params = garch_fit(train_returns)
        gjr_params = gjr_fit(train_returns)
        mf_gjr_params = mf_gjr_fit(train_returns, train_log_vix)

        last_fit = i
        n_refits += 1

        if n_refits == 1:
            model_params = {
                'CARR': carr_params,
                'CARR_MF': carr_mf_params,
                'GARCH': garch_params,
                'GJR': gjr_params,
                'MF_GJR': mf_gjr_params,
            }

        if n_refits % 20 == 0:
            print(f"    Refit #{n_refits} at OOS day {i}/{n_oos} "
                  f"({dates[t].strftime('%Y-%m-%d')})")

    # Day-by-day recursive forecasts using info up to t-1
    # CARR: lambda_t = omega + alpha * Range_{t-1} + beta * lambda_{t-1}
    if i == 0 or (i - last_fit) == 0:
        # After refit: run recursion from training data to get current state
        train_start = t - WINDOW
        # CARR recursion
        lam_carr = np.zeros(WINDOW + 1)
        lam_carr[0] = carr_params['omega'] / max(1 - carr_params['persistence'], 0.01)
        for j in range(WINDOW):
            lam_carr[j + 1] = (carr_params['omega']
                               + carr_params['alpha'] * all_ranges[train_start + j]
                               + carr_params['beta'] * lam_carr[j])
            lam_carr[j + 1] = max(lam_carr[j + 1], 1e-10)
        carr_lambda_prev = lam_carr[WINDOW]

        # CARR-MF recursion
        tau_mf = np.exp(carr_mf_params['theta0']
                        + carr_mf_params['theta1'] * all_log_vix[train_start:t])
        tau_mf = np.maximum(tau_mf, 1e-10)
        g_mf = np.zeros(WINDOW + 1)
        g_mf[0] = 1.0
        for j in range(WINDOW):
            g_mf[j + 1] = (carr_mf_params['omega']
                           + carr_mf_params['alpha'] * (all_ranges[train_start + j] / tau_mf[j])
                           + carr_mf_params['beta'] * g_mf[j])
            g_mf[j + 1] = max(g_mf[j + 1], 1e-10)
        carr_mf_g_prev = g_mf[WINDOW]

        # GARCH recursion
        h_garch = np.zeros(WINDOW + 1)
        h_garch[0] = garch_params['omega'] / max(1 - garch_params['persistence'], 0.01)
        for j in range(WINDOW):
            h_garch[j + 1] = (garch_params['omega']
                              + garch_params['alpha'] * all_returns[train_start + j] ** 2
                              + garch_params['beta'] * h_garch[j])
            h_garch[j + 1] = max(h_garch[j + 1], 1e-10)
        garch_h_prev = h_garch[WINDOW]

        # GJR recursion
        h_gjr = np.zeros(WINDOW + 1)
        h_gjr[0] = gjr_params['omega'] / max(1 - gjr_params['persistence'], 0.01)
        for j in range(WINDOW):
            shock = all_returns[train_start + j] ** 2
            asym = shock * (all_returns[train_start + j] < 0)
            h_gjr[j + 1] = (gjr_params['omega']
                            + gjr_params['alpha'] * shock
                            + gjr_params['gamma'] * asym
                            + gjr_params['beta'] * h_gjr[j])
            h_gjr[j + 1] = max(h_gjr[j + 1], 1e-10)
        gjr_h_prev = h_gjr[WINDOW]

        # MF-GJR recursion
        tau_mfgjr = np.exp(mf_gjr_params['theta0']
                           + mf_gjr_params['theta1'] * all_log_vix[train_start:t])
        tau_mfgjr = np.maximum(tau_mfgjr, 1e-10)
        g_mfgjr = np.zeros(WINDOW + 1)
        g_mfgjr[0] = 1.0
        for j in range(WINDOW):
            r2n = all_returns[train_start + j] ** 2 / tau_mfgjr[j]
            asym_n = r2n * (all_returns[train_start + j] < 0)
            g_mfgjr[j + 1] = (mf_gjr_params['omega']
                              + mf_gjr_params['alpha'] * r2n
                              + mf_gjr_params['gamma'] * asym_n
                              + mf_gjr_params['beta'] * g_mfgjr[j])
            g_mfgjr[j + 1] = max(g_mfgjr[j + 1], 1e-10)
        mfgjr_g_prev = g_mfgjr[WINDOW]
    else:
        # Day-by-day update using yesterday's observation
        prev_t = t - 1

        # CARR update
        carr_lambda_prev = (carr_params['omega']
                            + carr_params['alpha'] * all_ranges[prev_t]
                            + carr_params['beta'] * carr_lambda_prev)
        carr_lambda_prev = max(carr_lambda_prev, 1e-10)

        # CARR-MF update
        tau_prev = np.exp(carr_mf_params['theta0']
                          + carr_mf_params['theta1'] * all_log_vix[prev_t])
        tau_prev = max(tau_prev, 1e-10)
        carr_mf_g_prev = (carr_mf_params['omega']
                          + carr_mf_params['alpha'] * (all_ranges[prev_t] / tau_prev)
                          + carr_mf_params['beta'] * carr_mf_g_prev)
        carr_mf_g_prev = max(carr_mf_g_prev, 1e-10)

        # GARCH update
        garch_h_prev = (garch_params['omega']
                        + garch_params['alpha'] * all_returns[prev_t] ** 2
                        + garch_params['beta'] * garch_h_prev)
        garch_h_prev = max(garch_h_prev, 1e-10)

        # GJR update
        shock = all_returns[prev_t] ** 2
        asym = shock * (all_returns[prev_t] < 0)
        gjr_h_prev = (gjr_params['omega']
                      + gjr_params['alpha'] * shock
                      + gjr_params['gamma'] * asym
                      + gjr_params['beta'] * gjr_h_prev)
        gjr_h_prev = max(gjr_h_prev, 1e-10)

        # MF-GJR update
        tau_t = np.exp(mf_gjr_params['theta0']
                       + mf_gjr_params['theta1'] * all_log_vix[prev_t])
        tau_t = max(tau_t, 1e-10)
        r2n = all_returns[prev_t] ** 2 / tau_t
        asym_n = r2n * (all_returns[prev_t] < 0)
        mfgjr_g_prev = (mf_gjr_params['omega']
                        + mf_gjr_params['alpha'] * r2n
                        + mf_gjr_params['gamma'] * asym_n
                        + mf_gjr_params['beta'] * mfgjr_g_prev)
        mfgjr_g_prev = max(mfgjr_g_prev, 1e-10)

    # Store range forecasts (native CARR target)
    range_forecasts['CARR'][i] = carr_lambda_prev
    tau_t_mf = np.exp(carr_mf_params['theta0']
                      + carr_mf_params['theta1'] * all_log_vix[t - 1])
    tau_t_mf = max(tau_t_mf, 1e-10)
    range_forecasts['CARR_MF'][i] = tau_t_mf * carr_mf_g_prev

    # Convert CARR range forecast to variance: Parkinson conversion
    # sigma² = Range² / (4 * ln(2))
    forecasts['CARR'][i] = carr_lambda_prev ** 2 / (4 * np.log(2))
    forecasts['CARR_MF'][i] = range_forecasts['CARR_MF'][i] ** 2 / (4 * np.log(2))

    # GARCH/GJR forecasts are already variance
    forecasts['GARCH'][i] = garch_h_prev
    forecasts['GJR'][i] = gjr_h_prev

    # MF-GJR: tau * g
    tau_mfgjr_t = np.exp(mf_gjr_params['theta0']
                         + mf_gjr_params['theta1'] * all_log_vix[t - 1])
    tau_mfgjr_t = max(tau_mfgjr_t, 1e-10)
    forecasts['MF_GJR'][i] = tau_mfgjr_t * mfgjr_g_prev

print(f"  Total refits: {n_refits}")

# ============================================================
# 4. EVALUATION
# ============================================================
print("\n[4/6] Evaluating models...")

results = {}

# --- Layer 1: Native target QLIKE ---
print("\n  --- Layer 1: Native Target QLIKE ---")
# CARR native: QLIKE on range (lambda forecasts range)
carr_qlike_range = qlike(actual_range, range_forecasts['CARR'])
carr_mf_qlike_range = qlike(actual_range, range_forecasts['CARR_MF'])
# GARCH/GJR native: QLIKE on r²
garch_qlike_r2 = qlike(actual_r2, forecasts['GARCH'])
gjr_qlike_r2 = qlike(actual_r2, forecasts['GJR'])
mf_gjr_qlike_r2 = qlike(actual_r2, forecasts['MF_GJR'])

print(f"    CARR     on range: QLIKE = {carr_qlike_range:.6f}")
print(f"    CARR-MF  on range: QLIKE = {carr_mf_qlike_range:.6f}")
print(f"    GARCH    on r²:    QLIKE = {garch_qlike_r2:.6f}")
print(f"    GJR      on r²:    QLIKE = {gjr_qlike_r2:.6f}")
print(f"    MF-GJR   on r²:    QLIKE = {mf_gjr_qlike_r2:.6f}")

# --- Layer 2: Patton (2011) QLIKE on r² (proxy-robust, fair comparison) ---
print("\n  --- Layer 2: QLIKE on r² (Patton 2011, Fair Comparison) ---")
qlike_on_r2 = {}
for name in forecasts:
    qlike_on_r2[name] = qlike(actual_r2, forecasts[name])
    print(f"    {name:10s}: QLIKE = {qlike_on_r2[name]:.6f}")

# Ranking
ranking = sorted(qlike_on_r2.items(), key=lambda x: x[1])
print("\n    Ranking (lower is better):")
for rank, (name, val) in enumerate(ranking, 1):
    print(f"      #{rank}: {name:10s} = {val:.6f}")

# --- Layer 3: Spearman Rank Correlation ---
print("\n  --- Layer 3: Spearman Rank Correlation ---")
spearman = {}
for name in forecasts:
    rho, pval = stats.spearmanr(actual_r2, forecasts[name])
    spearman[name] = {'rho': rho, 'pval': pval}
    sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
    print(f"    {name:10s}: rho = {rho:.4f} (p={pval:.2e}) {sig}")

# --- Layer 4: DM Tests (Harvey |t| > 3.0) ---
print("\n  --- Layer 4: DM Tests (Harvey |t| > 3.0) ---")
model_names = list(forecasts.keys())
dm_results = {}

# Compute pointwise QLIKE losses for DM
pointwise_losses = {}
for name in model_names:
    pointwise_losses[name] = qlike_pointwise(actual_r2, forecasts[name])

print(f"    {'Pair':30s} {'t-stat':>8s} {'p-value':>10s} {'Harvey':>8s} {'Winner':>10s}")
print(f"    {'-' * 70}")
for i_m in range(len(model_names)):
    for j_m in range(i_m + 1, len(model_names)):
        name_i = model_names[i_m]
        name_j = model_names[j_m]
        t_stat, p_val = dm_test(pointwise_losses[name_i], pointwise_losses[name_j])
        significant = abs(t_stat) > 3.0
        winner = name_i if t_stat < 0 else name_j if t_stat > 0 else "tie"
        dm_results[f"{name_i} vs {name_j}"] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant': significant,
            'winner': winner if significant else 'n.s.'
        }
        sig_str = "SIG" if significant else "n.s."
        print(f"    {name_i + ' vs ' + name_j:30s} {t_stat:8.4f} {p_val:10.6f} {sig_str:>8s} "
              f"{winner if significant else 'n.s.':>10s}")

# --- Layer 5: Also evaluate on Parkinson variance (range² / 4ln2) ---
print("\n  --- Supplementary: QLIKE on Parkinson Variance ---")
qlike_on_pk = {}
for name in forecasts:
    qlike_on_pk[name] = qlike(actual_parkinson, forecasts[name])
    print(f"    {name:10s}: QLIKE = {qlike_on_pk[name]:.6f}")

# ============================================================
# 5. PARAMETER SUMMARY
# ============================================================
print("\n[5/6] Model parameter summary (first fit)...")

for name, params in model_params.items():
    print(f"\n  {name}:")
    for k, v in params.items():
        if isinstance(v, float):
            print(f"    {k}: {v:.8f}")
        else:
            print(f"    {k}: {v}")

# ============================================================
# 6. SAVE RESULTS + PLOTS
# ============================================================
print("\n[6/6] Saving results and plots...")

exp_dir = os.path.dirname(os.path.abspath(__file__))

# Save JSON results
results_dict = {
    'experiment_id': 'K934',
    'title': 'CARR Conditional Autoregressive Range Model vs GARCH/GJR',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY + ^VIX)',
    'period': '2004-01-01 ~ 2025-12-31',
    'oos_period': f'{oos_start} ~ {dates[-1].strftime("%Y-%m-%d")}',
    'oos_days': int(n_oos),
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': int(n_refits),
    'reference': 'Chou (2005) "Forecasting Financial Volatilities with Extreme Values"; '
                 'Patton (2011) J. Econometrics 160; Parkinson (1980)',
    'descriptive_stats': {
        'log_range_mean': round(float(spy['log_range'].mean()), 6),
        'log_range_std': round(float(spy['log_range'].std()), 6),
        'r2_mean': round(float(spy['r2'].mean()), 6),
        'r2_std': round(float(spy['r2'].std()), 6),
        'parkinson_var_mean': round(float(spy['parkinson_var'].mean()), 6),
        'corr_parkinson_r2': round(float(corr_pk_r2), 4),
    },
    'model_parameters_first_fit': {
        name: {k: round(v, 8) if isinstance(v, float) else v
               for k, v in params.items()}
        for name, params in model_params.items()
    },
    'layer1_native_target_qlike': {
        'CARR_on_range': round(carr_qlike_range, 6),
        'CARR_MF_on_range': round(carr_mf_qlike_range, 6),
        'GARCH_on_r2': round(garch_qlike_r2, 6),
        'GJR_on_r2': round(gjr_qlike_r2, 6),
        'MF_GJR_on_r2': round(mf_gjr_qlike_r2, 6),
    },
    'layer2_qlike_on_r2_patton': {
        name: round(val, 6) for name, val in qlike_on_r2.items()
    },
    'layer2_ranking': [
        {'rank': r + 1, 'model': name, 'qlike': round(val, 6)}
        for r, (name, val) in enumerate(ranking)
    ],
    'layer3_spearman': {
        name: {'rho': round(v['rho'], 4), 'pval': round(v['pval'], 8)}
        for name, v in spearman.items()
    },
    'layer4_dm_tests': dm_results,
    'supplementary_qlike_on_parkinson': {
        name: round(val, 6) for name, val in qlike_on_pk.items()
    },
}

results_path = os.path.join(exp_dir, 'k934_results.json')
with open(results_path, 'w') as f:
    json.dump(results_dict, f, indent=2, ensure_ascii=False)
print(f"  Results saved to {results_path}")

# --- Plots ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 2, figsize=(16, 12))

# Plot 1: QLIKE on r² comparison (bar chart)
ax = axes[0, 0]
models_sorted = [x[0] for x in ranking]
qlike_sorted = [x[1] for x in ranking]
colors = ['#2ecc71' if 'CARR' in m else '#3498db' for m in models_sorted]
bars = ax.bar(models_sorted, qlike_sorted, color=colors, edgecolor='black', alpha=0.85)
ax.set_ylabel('QLIKE Loss (lower is better)')
ax.set_title('Layer 2: QLIKE on r² (Patton 2011)')
ax.tick_params(axis='x', rotation=15)
for bar, val in zip(bars, qlike_sorted):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
            f'{val:.4f}', ha='center', va='bottom', fontsize=9)

# Plot 2: Spearman rho comparison
ax = axes[0, 1]
rho_names = list(spearman.keys())
rho_vals = [spearman[n]['rho'] for n in rho_names]
colors2 = ['#2ecc71' if 'CARR' in m else '#3498db' for m in rho_names]
bars2 = ax.bar(rho_names, rho_vals, color=colors2, edgecolor='black', alpha=0.85)
ax.set_ylabel('Spearman ρ (higher is better)')
ax.set_title('Layer 3: Spearman Rank Correlation with r²')
ax.tick_params(axis='x', rotation=15)
for bar, val in zip(bars2, rho_vals):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
            f'{val:.4f}', ha='center', va='bottom', fontsize=9)

# Plot 3: Time series of forecasted vol (sqrt of sigma2) — sample 500 days
ax = axes[1, 0]
sample_start = max(0, n_oos - 500)
sample_dates = oos_dates[sample_start:]
ax.plot(sample_dates, np.sqrt(actual_r2[sample_start:]) * 100,
        alpha=0.3, color='gray', label='|return| (%)', linewidth=0.5)
for name, color in [('CARR', '#e74c3c'), ('GJR', '#3498db'),
                     ('MF_GJR', '#9b59b6'), ('CARR_MF', '#e67e22')]:
    ax.plot(sample_dates, np.sqrt(forecasts[name][sample_start:]) * 100,
            label=name, alpha=0.8, linewidth=0.8, color=color)
ax.set_ylabel('Annualized Vol Forecast (% daily)')
ax.set_title('Forecast Comparison (Last 500 Trading Days)')
ax.legend(fontsize=8, ncol=2)
ax.tick_params(axis='x', rotation=30)

# Plot 4: DM test heatmap
ax = axes[1, 1]
n_models = len(model_names)
dm_matrix = np.zeros((n_models, n_models))
for i_m in range(n_models):
    for j_m in range(n_models):
        if i_m == j_m:
            dm_matrix[i_m, j_m] = 0
        elif i_m < j_m:
            key = f"{model_names[i_m]} vs {model_names[j_m]}"
            dm_matrix[i_m, j_m] = dm_results[key]['t_stat']
            dm_matrix[j_m, i_m] = -dm_results[key]['t_stat']

im = ax.imshow(dm_matrix, cmap='RdBu_r', vmin=-5, vmax=5, aspect='auto')
ax.set_xticks(range(n_models))
ax.set_yticks(range(n_models))
ax.set_xticklabels(model_names, fontsize=8, rotation=30)
ax.set_yticklabels(model_names, fontsize=8)
ax.set_title('DM Test t-statistics (negative = row model better)')
plt.colorbar(im, ax=ax, shrink=0.8)

# Add significance markers
for i_m in range(n_models):
    for j_m in range(n_models):
        val = dm_matrix[i_m, j_m]
        marker = "***" if abs(val) > 3.0 else ""
        ax.text(j_m, i_m, f'{val:.1f}\n{marker}', ha='center', va='center',
                fontsize=7, color='black' if abs(val) < 3 else 'white')

plt.tight_layout()
fig_path = os.path.join(exp_dir, 'k934_comparison.png')
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Plot saved to {fig_path}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY: K934 CARR Model Results")
print("=" * 60)

print(f"\nBest model on QLIKE/r² (Patton 2011): {ranking[0][0]} ({ranking[0][1]:.6f})")
print(f"Worst model on QLIKE/r²:               {ranking[-1][0]} ({ranking[-1][1]:.6f})")

print("\nKey findings:")
carr_rank = [r for r, (n, _) in enumerate(ranking, 1) if n == 'CARR'][0]
carr_mf_rank = [r for r, (n, _) in enumerate(ranking, 1) if n == 'CARR_MF'][0]
print(f"  CARR    rank: #{carr_rank}/5")
print(f"  CARR-MF rank: #{carr_mf_rank}/5")

# Check if CARR beats GARCH
carr_vs_garch = dm_results.get('CARR vs GARCH', {})
carr_vs_gjr = dm_results.get('CARR vs GJR', {})
print(f"\n  CARR vs GARCH: t={carr_vs_garch.get('t_stat', 'N/A')}, "
      f"sig={carr_vs_garch.get('significant', 'N/A')}")
print(f"  CARR vs GJR:   t={carr_vs_gjr.get('t_stat', 'N/A')}, "
      f"sig={carr_vs_gjr.get('significant', 'N/A')}")

# CARR-MF vs MF-GJR
carrmf_vs_mfgjr = dm_results.get('CARR_MF vs MF_GJR', {})
print(f"  CARR-MF vs MF-GJR: t={carrmf_vs_mfgjr.get('t_stat', 'N/A')}, "
      f"sig={carrmf_vs_mfgjr.get('significant', 'N/A')}")

print("\nDone!")
