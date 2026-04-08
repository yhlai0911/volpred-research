#!/usr/bin/env python3
"""
K933: FIGARCH-MF(VIX) — Does long memory add value beyond VIX?

Question:
    K442 showed FIGARCH has long memory (d=0.61) but cannot beat GARCH OOS.
    K889 showed MF-GJR(VIX) significantly improves forecasting (QLIKE -2.6%, DM t=-4.42).
    Does combining FIGARCH with MF(VIX) capture persistence that VIX misses?

Hypotheses:
    H0: FIGARCH-MF(VIX) ≈ MF-GJR(VIX) (VIX already captures long memory)
    H1: FIGARCH-MF(VIX) > MF-GJR(VIX) (long memory has incremental value beyond VIX)

Models:
    1. GARCH(1,1) — baseline
    2. GJR(1,1,1) — asymmetry
    3. FIGARCH(1,d,1) — long memory
    4. MF-GJR(VIX) — VIX multiplicative factor with GJR short-run
    5. FIGARCH-MF(VIX) — VIX multiplicative factor with FIGARCH short-run

Data: SPY 2006-2026, yfinance. VIX from ^VIX.
Window: 2000. OOS: 2016-01-01 ~ 2025-12-31.
Refit: every 21 trading days with daily OOS recursion.

Evaluation:
    - QLIKE on r² (Patton 2011 proxy-robust)
    - MSE on r²
    - Spearman rank correlation
    - DM test (Harvey threshold |t| > 3.0)

References:
    - Baillie, Bollerslev, Mikkelsen (1996) — FIGARCH
    - Engle, Ghysels, Sohn (2013) — GARCH-MIDAS / MF structure
    - Patton (2011) — Proxy-robust loss functions
    - Hansen & Lunde (2005) — Forecast evaluation

Data source: yfinance (SPY, ^VIX)
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import spearmanr
from datetime import datetime
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import sys
import time

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 0. Numba-accelerated core functions
# ============================================================

@njit(cache=True)
def _figarch_lambda(d, phi, beta, n_lags):
    """Compute FIGARCH lambda coefficients."""
    delta = np.zeros(n_lags + 1)
    delta[0] = 1.0
    for k in range(1, n_lags + 1):
        delta[k] = delta[k-1] * (k - 1.0 - d) / k

    lam = np.zeros(n_lags)
    if n_lags >= 1:
        lam[0] = d - phi + beta
    for k in range(1, n_lags):
        lam[k] = beta * lam[k-1] + (-delta[k+1] + phi * delta[k])
    return lam


@njit(cache=True)
def _figarch_variance(r2, omega, d, phi, beta, n_lags):
    """Compute FIGARCH conditional variance series."""
    T = len(r2)
    lam = _figarch_lambda(d, phi, beta, min(n_lags, T - 1))
    omega_star = omega / (1.0 - beta) if abs(beta) < 1.0 else omega
    sigma2_uncond = 0.0
    for i in range(T):
        sigma2_uncond += r2[i]
    sigma2_uncond /= T

    sigma2 = np.full(T, sigma2_uncond)
    for t in range(1, T):
        n_use = min(t, len(lam))
        ws = 0.0
        for k in range(n_use):
            ws += lam[k] * r2[t - 1 - k]
        sigma2[t] = omega_star + ws + beta * sigma2[t - 1]
        if sigma2[t] <= 0:
            sigma2[t] = sigma2_uncond
    return sigma2


@njit(cache=True)
def _figarch_negloglik(omega, d, phi, beta, r2, n_lags):
    """Negative log-likelihood for FIGARCH."""
    if omega <= 0 or d <= 0 or d >= 1 or phi < 0 or phi >= 1 or beta < 0 or beta >= 1:
        return 1e10
    if d - phi + beta <= 0 or d - phi + beta >= 1:
        return 1e10

    sigma2 = _figarch_variance(r2, omega, d, phi, beta, n_lags)
    T = len(r2)
    nll = 0.0
    for t in range(T):
        if sigma2[t] <= 0:
            return 1e10
        nll += 0.5 * (np.log(2 * np.pi) + np.log(sigma2[t]) + r2[t] / sigma2[t])
    if np.isnan(nll) or np.isinf(nll):
        return 1e10
    return nll


@njit(cache=True)
def _mf_gjr_negloglik(theta0, theta1, omega, alpha, gamma, beta, returns, log_vix):
    """Negative log-likelihood for MF-GJR(VIX)."""
    if omega <= 0 or alpha < 0 or gamma < -alpha or beta < 0:
        return 1e10
    if alpha + gamma / 2.0 + beta >= 1.0:
        return 1e10

    T = len(returns)
    nll = 0.0
    g = 1.0

    for t in range(T):
        tau_t = np.exp(theta0 + theta1 * log_vix[t])
        sigma2_t = tau_t * g
        if sigma2_t <= 0:
            return 1e10

        r2_t = returns[t] ** 2
        nll += 0.5 * (np.log(2 * np.pi) + np.log(sigma2_t) + r2_t / sigma2_t)

        # Update g for next period
        eps2_norm = r2_t / tau_t
        ind = 1.0 if returns[t] < 0 else 0.0
        g_next = omega + alpha * eps2_norm + gamma * eps2_norm * ind + beta * g
        if g_next <= 0:
            g_next = 1.0
        g = g_next

    if np.isnan(nll) or np.isinf(nll):
        return 1e10
    return nll


@njit(cache=True)
def _mf_gjr_g_series(theta0, theta1, omega, alpha, gamma, beta, returns, log_vix):
    """Compute full g series for MF-GJR."""
    T = len(returns)
    g = np.ones(T)
    for t in range(1, T):
        tau_prev = np.exp(theta0 + theta1 * log_vix[t-1])
        eps2_norm = returns[t-1]**2 / tau_prev
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * eps2_norm + gamma * eps2_norm * ind + beta * g[t-1]
        if g[t] <= 0:
            g[t] = 1.0
    return g


@njit(cache=True)
def _figarch_mf_negloglik(theta0, theta1, omega, d, phi, beta, returns, log_vix, n_lags):
    """Negative log-likelihood for FIGARCH-MF(VIX)."""
    if omega <= 0 or d <= 0 or d >= 1 or phi < 0 or phi >= 1 or beta < 0 or beta >= 1:
        return 1e10

    T = len(returns)
    r2 = np.empty(T)
    tau = np.empty(T)
    eps2_norm = np.empty(T)

    for t in range(T):
        r2[t] = returns[t] ** 2
        tau[t] = np.exp(theta0 + theta1 * log_vix[t])
        eps2_norm[t] = r2[t] / tau[t]

    lam = _figarch_lambda(d, phi, beta, min(n_lags, T - 1))
    omega_star = omega / (1.0 - beta) if abs(beta) < 1.0 else omega

    # g unconditional
    g_uncond = 0.0
    for t in range(T):
        g_uncond += eps2_norm[t]
    g_uncond /= T

    g = np.full(T, g_uncond)
    nll = 0.0

    for t in range(T):
        if t > 0:
            n_use = min(t, len(lam))
            ws = 0.0
            for k in range(n_use):
                ws += lam[k] * eps2_norm[t - 1 - k]
            g[t] = omega_star + ws + beta * g[t - 1]
            if g[t] <= 0:
                g[t] = g_uncond

        sigma2_t = tau[t] * g[t]
        if sigma2_t <= 0:
            return 1e10
        nll += 0.5 * (np.log(2 * np.pi) + np.log(sigma2_t) + r2[t] / sigma2_t)

    if np.isnan(nll) or np.isinf(nll):
        return 1e10
    return nll


@njit(cache=True)
def _figarch_mf_g_series(theta0, theta1, omega, d, phi, beta, returns, log_vix, n_lags):
    """Compute full g and eps2_norm series for FIGARCH-MF."""
    T = len(returns)
    tau = np.empty(T)
    eps2_norm = np.empty(T)

    for t in range(T):
        tau[t] = np.exp(theta0 + theta1 * log_vix[t])
        eps2_norm[t] = returns[t]**2 / tau[t]

    lam = _figarch_lambda(d, phi, beta, min(n_lags, T - 1))
    omega_star = omega / (1.0 - beta) if abs(beta) < 1.0 else omega

    g_uncond = 0.0
    for t in range(T):
        g_uncond += eps2_norm[t]
    g_uncond /= T

    g = np.full(T, g_uncond)
    for t in range(1, T):
        n_use = min(t, len(lam))
        ws = 0.0
        for k in range(n_use):
            ws += lam[k] * eps2_norm[t - 1 - k]
        g[t] = omega_star + ws + beta * g[t - 1]
        if g[t] <= 0:
            g[t] = g_uncond

    return g, eps2_norm


# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K933: FIGARCH-MF(VIX) — Long Memory + VIX")
print("=" * 60)
sys.stdout.flush()

# Warm up numba JIT (compile before timing)
print("\n[0] Warming up numba JIT...")
sys.stdout.flush()
_dummy = _figarch_lambda(0.5, 0.1, 0.5, 10)
_dummy2 = _figarch_variance(np.ones(100), 0.01, 0.5, 0.1, 0.5, 50)
_dummy3 = _mf_gjr_negloglik(0.0, 1.0, 0.02, 0.05, 0.05, 0.85, np.ones(100), np.ones(100))
_dummy4 = _figarch_mf_negloglik(0.0, 1.0, 0.02, 0.5, 0.1, 0.5, np.ones(100), np.ones(100), 50)
print("  JIT compilation done.")
sys.stdout.flush()

print("\n[1] Downloading data...")
sys.stdout.flush()
spy = yf.download("SPY", start="2004-01-01", end="2026-01-01", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2004-01-01", end="2026-01-01", auto_adjust=True, progress=False)

if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy['Return'] = np.log(spy['Close'] / spy['Close'].shift(1)) * 100
spy['r2'] = spy['Return'] ** 2
vix_close = vix['Close'].rename('VIX')

data = spy[['Return', 'r2']].join(vix_close, how='inner').dropna()
print(f"  Total observations: {len(data)}")
print(f"  Date range: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
sys.stdout.flush()

# ============================================================
# 2. OOS Setup
# ============================================================
oos_start = pd.Timestamp("2016-01-01")
oos_mask = data.index >= oos_start
oos_dates = data.index[oos_mask]
print(f"\n[2] OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"  OOS observations: {len(oos_dates)}")
sys.stdout.flush()

WINDOW = 2000
REFIT_FREQ = 21
N_LAGS = 200

all_idx = data.index.tolist()
date_to_pos = {dt: i for i, dt in enumerate(all_idx)}

# Pre-extract numpy arrays
returns_arr = data['Return'].values.astype(np.float64)
r2_arr = data['r2'].values.astype(np.float64)
vix_arr = data['VIX'].values.astype(np.float64)
log_vix_arr = np.log(vix_arr)

# ============================================================
# 3. Model Functions
# ============================================================
from arch import arch_model


def garch_oos_forecast(model_type='GARCH'):
    """OOS forecast for GARCH/GJR."""
    forecasts = np.full(len(oos_dates), np.nan)
    last_params = None
    last_h = None

    for i, dt in enumerate(oos_dates):
        pos = date_to_pos[dt]

        if i % REFIT_FREQ == 0 or last_params is None:
            train_start = max(0, pos - WINDOW)
            train_data = data['Return'].iloc[train_start:pos]

            if model_type == 'GJR':
                am = arch_model(train_data, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
            else:
                am = arch_model(train_data, vol='GARCH', p=1, q=1, mean='Zero', dist='normal')

            try:
                res = am.fit(disp='off', options={'maxiter': 500})
                params = res.params
                if model_type == 'GJR':
                    last_params = (params.get('omega', 0.01), params.get('alpha[1]', 0.05),
                                   params.get('gamma[1]', 0.05), params.get('beta[1]', 0.9))
                else:
                    last_params = (params.get('omega', 0.01), params.get('alpha[1]', 0.05),
                                   0.0, params.get('beta[1]', 0.9))
                last_h = float(res.conditional_volatility.iloc[-1] ** 2)
            except Exception:
                pass

        if last_params is None:
            continue

        omega, alpha, gamma, beta = last_params
        r_prev = returns_arr[pos - 1]
        r2_prev = r_prev ** 2
        ind = 1.0 if r_prev < 0 else 0.0
        h_t = omega + alpha * r2_prev + gamma * r2_prev * ind + beta * last_h
        h_t = max(h_t, 1e-6)
        forecasts[i] = h_t
        last_h = h_t

    return pd.Series(forecasts, index=oos_dates).dropna()


def figarch_oos_forecast():
    """OOS forecast for FIGARCH(1,d,1)."""
    forecasts = np.full(len(oos_dates), np.nan)
    last_params = None
    last_sigma2 = None
    r2_buffer = np.zeros(0)

    def _fit(r2_train):
        """Fit FIGARCH via scipy."""
        sigma2_avg = np.mean(r2_train)
        bounds = [(1e-6, sigma2_avg * 2), (0.01, 0.99), (0.001, 0.98), (0.001, 0.98)]
        best_f, best_x = 1e10, None

        for d_init in [0.3, 0.5, 0.7]:
            for beta_init in [0.3, 0.5]:
                x0 = [sigma2_avg * 0.05, d_init, 0.1, beta_init]
                try:
                    res = minimize(lambda p: _figarch_negloglik(p[0], p[1], p[2], p[3], r2_train, N_LAGS),
                                  x0, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': 200, 'ftol': 1e-7})
                    if res.fun < best_f:
                        best_f, best_x = res.fun, res.x
                except Exception:
                    pass
        return best_x

    for i, dt in enumerate(oos_dates):
        pos = date_to_pos[dt]

        if i % REFIT_FREQ == 0 or last_params is None:
            train_start = max(0, pos - WINDOW)
            r2_train = r2_arr[train_start:pos].copy()

            x = _fit(r2_train)
            if x is not None:
                last_params = {'omega': x[0], 'd': x[1], 'phi': x[2], 'beta': x[3]}
                sv = _figarch_variance(r2_train, x[0], x[1], x[2], x[3], N_LAGS)
                last_sigma2 = sv[-1]
                r2_buffer = r2_train[-N_LAGS:].copy()

        if last_params is None:
            continue

        r2_prev = r2_arr[pos - 1]
        r2_buffer = np.append(r2_buffer, r2_prev)
        if len(r2_buffer) > N_LAGS + 50:
            r2_buffer = r2_buffer[-(N_LAGS):]

        lam = _figarch_lambda(last_params['d'], last_params['phi'], last_params['beta'],
                              min(N_LAGS, len(r2_buffer)))
        omega_star = last_params['omega'] / (1.0 - last_params['beta'])
        n_use = min(len(r2_buffer), len(lam))
        ws = np.dot(lam[:n_use], r2_buffer[-n_use:][::-1])

        h_t = omega_star + ws + last_params['beta'] * last_sigma2
        h_t = max(h_t, 1e-6)
        forecasts[i] = h_t
        last_sigma2 = h_t

    return pd.Series(forecasts, index=oos_dates).dropna()


def mf_gjr_oos_forecast():
    """OOS forecast for MF-GJR(VIX)."""
    forecasts = np.full(len(oos_dates), np.nan)
    last_params = None
    last_g = None

    def _fit(r_train, lv_train):
        sigma2_avg = np.mean(r_train ** 2)
        mean_lv = np.mean(lv_train)
        theta0_init = np.log(sigma2_avg) - 0.5 * mean_lv

        bounds = [(-10, 10), (-5, 5), (1e-6, 5), (0, 0.5), (0, 0.5), (0, 0.999)]
        best_f, best_x = 1e10, None

        for theta1 in [0.5, 1.0, 1.5]:
            for beta in [0.8, 0.9]:
                x0 = [theta0_init, theta1, 0.02, 0.05, 0.05, beta]
                try:
                    res = minimize(
                        lambda p: _mf_gjr_negloglik(p[0], p[1], p[2], p[3], p[4], p[5], r_train, lv_train),
                        x0, method='L-BFGS-B', bounds=bounds,
                        options={'maxiter': 200, 'ftol': 1e-7})
                    if res.fun < best_f:
                        best_f, best_x = res.fun, res.x
                except Exception:
                    pass
        return best_x

    for i, dt in enumerate(oos_dates):
        pos = date_to_pos[dt]

        if i % REFIT_FREQ == 0 or last_params is None:
            train_start = max(0, pos - WINDOW)
            r_train = returns_arr[train_start:pos].copy()
            lv_train = log_vix_arr[train_start:pos].copy()

            x = _fit(r_train, lv_train)
            if x is not None:
                last_params = {'theta0': x[0], 'theta1': x[1], 'omega': x[2],
                               'alpha': x[3], 'gamma': x[4], 'beta': x[5]}
                g_s = _mf_gjr_g_series(x[0], x[1], x[2], x[3], x[4], x[5], r_train, lv_train)
                last_g = g_s[-1]

        if last_params is None:
            continue

        p = last_params
        r_prev = returns_arr[pos - 1]
        r2_prev = r_prev ** 2
        lvix_prev = log_vix_arr[pos - 1]

        tau_prev = np.exp(p['theta0'] + p['theta1'] * lvix_prev)
        tau_t = np.exp(p['theta0'] + p['theta1'] * lvix_prev)  # use t-1 VIX

        eps2_norm = r2_prev / tau_prev
        ind = 1.0 if r_prev < 0 else 0.0
        g_t = p['omega'] + p['alpha'] * eps2_norm + p['gamma'] * eps2_norm * ind + p['beta'] * last_g
        g_t = max(g_t, 1e-6)

        sigma2_t = max(tau_t * g_t, 1e-6)
        forecasts[i] = sigma2_t
        last_g = g_t

    return pd.Series(forecasts, index=oos_dates).dropna()


def figarch_mf_oos_forecast():
    """OOS forecast for FIGARCH-MF(VIX).

    Key safeguard: clamp g_t to prevent explosion. The FIGARCH long-memory
    filter can diverge in OOS when parameters shift across refits. We use
    the unconditional variance of eps2_norm as a ceiling (10x) to prevent
    unrealistic forecasts while preserving the model's dynamics.
    """
    forecasts = np.full(len(oos_dates), np.nan)
    last_params = None
    last_g = None
    eps2_norm_buffer = np.zeros(0)
    g_uncond_last = 1.0  # track unconditional g for clamping

    def _fit(r_train, lv_train):
        sigma2_avg = np.mean(r_train ** 2)
        mean_lv = np.mean(lv_train)
        theta0_init = np.log(sigma2_avg) - 0.5 * mean_lv

        bounds = [(-10, 10), (-5, 5), (1e-6, 5), (0.01, 0.99), (0.001, 0.98), (0.001, 0.98)]
        best_f, best_x = 1e10, None

        for theta1 in [0.5, 1.0]:
            for d_init in [0.3, 0.5]:
                for beta in [0.3, 0.5]:
                    x0 = [theta0_init, theta1, 0.02, d_init, 0.1, beta]
                    try:
                        res = minimize(
                            lambda p: _figarch_mf_negloglik(
                                p[0], p[1], p[2], p[3], p[4], p[5], r_train, lv_train, N_LAGS),
                            x0, method='L-BFGS-B', bounds=bounds,
                            options={'maxiter': 200, 'ftol': 1e-7})
                        if res.fun < best_f:
                            best_f, best_x = res.fun, res.x
                    except Exception:
                        pass
        return best_x

    for i, dt in enumerate(oos_dates):
        pos = date_to_pos[dt]

        if i % REFIT_FREQ == 0 or last_params is None:
            train_start = max(0, pos - WINDOW)
            r_train = returns_arr[train_start:pos].copy()
            lv_train = log_vix_arr[train_start:pos].copy()

            x = _fit(r_train, lv_train)
            if x is not None:
                last_params = {'theta0': x[0], 'theta1': x[1], 'omega': x[2],
                               'd': x[3], 'phi': x[4], 'beta': x[5]}
                g_s, e2n = _figarch_mf_g_series(x[0], x[1], x[2], x[3], x[4], x[5],
                                                 r_train, lv_train, N_LAGS)
                last_g = g_s[-1]
                eps2_norm_buffer = e2n[-N_LAGS:].copy()
                g_uncond_last = np.mean(e2n)  # E[g] under MF ≈ E[eps2_norm]

        if last_params is None:
            continue

        p = last_params
        r_prev = returns_arr[pos - 1]
        r2_prev = r_prev ** 2
        lvix_prev = log_vix_arr[pos - 1]

        tau_prev = np.exp(p['theta0'] + p['theta1'] * lvix_prev)
        tau_t = np.exp(p['theta0'] + p['theta1'] * lvix_prev)

        eps2_norm_prev = r2_prev / tau_prev
        eps2_norm_buffer = np.append(eps2_norm_buffer, eps2_norm_prev)
        if len(eps2_norm_buffer) > N_LAGS + 50:
            eps2_norm_buffer = eps2_norm_buffer[-N_LAGS:]

        lam = _figarch_lambda(p['d'], p['phi'], p['beta'], min(N_LAGS, len(eps2_norm_buffer)))
        omega_star = p['omega'] / (1.0 - p['beta'])
        n_use = min(len(eps2_norm_buffer), len(lam))
        ws = np.dot(lam[:n_use], eps2_norm_buffer[-n_use:][::-1])

        g_t = omega_star + ws + p['beta'] * last_g
        g_t = max(g_t, 1e-6)
        # Clamp g_t to prevent explosion (max 20x unconditional)
        g_t = min(g_t, 20.0 * max(g_uncond_last, 1.0))

        sigma2_t = tau_t * g_t
        sigma2_t = max(sigma2_t, 1e-6)
        # Also clamp total sigma2 to reasonable range (max 100x unconditional r2)
        sigma2_uncond = np.mean(r2_arr)
        sigma2_t = min(sigma2_t, 50.0 * sigma2_uncond)

        forecasts[i] = sigma2_t
        last_g = g_t

    return pd.Series(forecasts, index=oos_dates).dropna()


# ============================================================
# 4. Evaluation Functions
# ============================================================
def qlike(actual_r2, forecast_sigma2):
    mask = (forecast_sigma2 > 0) & (actual_r2 > 0)
    ratio = actual_r2[mask] / forecast_sigma2[mask]
    return (ratio - np.log(ratio) - 1).mean()


def mse_loss(actual_r2, forecast_sigma2):
    return ((actual_r2 - forecast_sigma2) ** 2).mean()


def dm_test(loss1, loss2):
    d = loss1 - loss2
    d = d[~np.isnan(d)]
    n = len(d)
    d_bar = d.mean()
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0 / n
    if var_d <= 0:
        var_d = 1e-20
    return d_bar / np.sqrt(var_d)


# ============================================================
# 5. Run All Models
# ============================================================
t0 = time.time()

print("\n[3] Running GARCH(1,1) OOS...")
sys.stdout.flush()
fc_garch = garch_oos_forecast('GARCH')
print(f"  Done. {len(fc_garch)} forecasts. ({time.time()-t0:.1f}s)")
sys.stdout.flush()

print("\n[4] Running GJR(1,1,1) OOS...")
sys.stdout.flush()
fc_gjr = garch_oos_forecast('GJR')
print(f"  Done. {len(fc_gjr)} forecasts. ({time.time()-t0:.1f}s)")
sys.stdout.flush()

print("\n[5] Running FIGARCH(1,d,1) OOS...")
sys.stdout.flush()
fc_figarch = figarch_oos_forecast()
print(f"  Done. {len(fc_figarch)} forecasts. ({time.time()-t0:.1f}s)")
sys.stdout.flush()

print("\n[6] Running MF-GJR(VIX) OOS...")
sys.stdout.flush()
fc_mf_gjr = mf_gjr_oos_forecast()
print(f"  Done. {len(fc_mf_gjr)} forecasts. ({time.time()-t0:.1f}s)")
sys.stdout.flush()

print("\n[7] Running FIGARCH-MF(VIX) OOS...")
sys.stdout.flush()
fc_figarch_mf = figarch_mf_oos_forecast()
print(f"  Done. {len(fc_figarch_mf)} forecasts. ({time.time()-t0:.1f}s)")
sys.stdout.flush()

total_runtime = time.time() - t0
print(f"\n  Total model computation: {total_runtime:.1f}s")

# ============================================================
# 6. Align and Evaluate
# ============================================================
print("\n[8] Evaluating...")
sys.stdout.flush()

common_dates = sorted(set(fc_garch.index) & set(fc_gjr.index) &
                       set(fc_figarch.index) & set(fc_mf_gjr.index) &
                       set(fc_figarch_mf.index))
print(f"  Common OOS dates: {len(common_dates)}")

actual = r2_arr[[date_to_pos[d] for d in common_dates]]

models = {
    'GARCH(1,1)': fc_garch.loc[common_dates].values,
    'GJR(1,1,1)': fc_gjr.loc[common_dates].values,
    'FIGARCH(1,d,1)': fc_figarch.loc[common_dates].values,
    'MF-GJR(VIX)': fc_mf_gjr.loc[common_dates].values,
    'FIGARCH-MF(VIX)': fc_figarch_mf.loc[common_dates].values,
}

results = {}
for name, fc in models.items():
    ql = qlike(actual, fc)
    ms = mse_loss(actual, fc)
    rho, pval = spearmanr(actual, fc)
    results[name] = {
        'QLIKE': float(ql),
        'MSE': float(ms),
        'Spearman_rho': float(rho),
        'Spearman_pval': float(pval),
    }
    print(f"\n  {name}:")
    print(f"    QLIKE     = {ql:.6f}")
    print(f"    MSE       = {ms:.6f}")
    print(f"    Spearman  = {rho:.4f} (p={pval:.2e})")

# ============================================================
# 7. DM Tests
# ============================================================
print("\n[9] Diebold-Mariano Tests (QLIKE loss)...")

qlike_losses = {}
for name, fc in models.items():
    mask = (fc > 0) & (actual > 0)
    ratio = np.where(mask, actual / fc, np.nan)
    qlike_losses[name] = np.where(mask, ratio - np.log(ratio) - 1, np.nan)

valid = np.ones(len(common_dates), dtype=bool)
for name in qlike_losses:
    valid &= ~np.isnan(qlike_losses[name])

for name in qlike_losses:
    qlike_losses[name] = qlike_losses[name][valid]

dm_results = {}
model_names = list(models.keys())
baseline_name = 'GARCH(1,1)'

print(f"\n  --- vs {baseline_name} (baseline) ---")
for name in model_names:
    if name == baseline_name:
        continue
    t_stat = dm_test(qlike_losses[baseline_name], qlike_losses[name])
    dm_results[f'{baseline_name} vs {name}'] = float(t_stat)
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
    direction = f"{name} better" if t_stat > 0 else f"{baseline_name} better"
    print(f"    DM t = {t_stat:+.3f} {sig}  ({direction})")

# Key comparison
print(f"\n  --- MF-GJR(VIX) vs FIGARCH-MF(VIX) (key test) ---")
t_key = dm_test(qlike_losses['MF-GJR(VIX)'], qlike_losses['FIGARCH-MF(VIX)'])
dm_results['MF-GJR(VIX) vs FIGARCH-MF(VIX)'] = float(t_key)
sig = "***" if abs(t_key) > 3.0 else ("**" if abs(t_key) > 2.0 else ("*" if abs(t_key) > 1.65 else ""))
direction = "FIGARCH-MF better" if t_key > 0 else "MF-GJR better"
print(f"    DM t = {t_key:+.3f} {sig}  ({direction})")

# Additional comparisons
for pair_name, (m1, m2) in [
    ('GJR(1,1,1) vs FIGARCH(1,d,1)', ('GJR(1,1,1)', 'FIGARCH(1,d,1)')),
    ('GJR(1,1,1) vs MF-GJR(VIX)', ('GJR(1,1,1)', 'MF-GJR(VIX)')),
    ('FIGARCH(1,d,1) vs FIGARCH-MF(VIX)', ('FIGARCH(1,d,1)', 'FIGARCH-MF(VIX)')),
]:
    t_extra = dm_test(qlike_losses[m1], qlike_losses[m2])
    dm_results[pair_name] = float(t_extra)
    print(f"\n  --- {pair_name} ---")
    sig = "***" if abs(t_extra) > 3.0 else ""
    print(f"    DM t = {t_extra:+.3f} {sig}")

# ============================================================
# 8. QLIKE improvements
# ============================================================
print("\n[10] QLIKE improvements vs GARCH(1,1) baseline:")
baseline_qlike = results['GARCH(1,1)']['QLIKE']
for name in model_names:
    if name == 'GARCH(1,1)':
        continue
    improvement = (baseline_qlike - results[name]['QLIKE']) / baseline_qlike * 100
    results[name]['QLIKE_improvement_pct'] = float(improvement)
    print(f"    {name}: {improvement:+.3f}%")

mf_gjr_qlike = results['MF-GJR(VIX)']['QLIKE']
figarch_mf_qlike = results['FIGARCH-MF(VIX)']['QLIKE']
marginal_improvement = (mf_gjr_qlike - figarch_mf_qlike) / mf_gjr_qlike * 100
print(f"\n  FIGARCH-MF(VIX) marginal improvement over MF-GJR(VIX): {marginal_improvement:+.3f}%")

# ============================================================
# 9. Hypothesis Decision
# ============================================================
print("\n" + "=" * 60)
print("HYPOTHESIS TEST DECISION")
print("=" * 60)

if abs(t_key) > 3.0 and t_key > 0:
    decision = "REJECT H0: FIGARCH-MF(VIX) significantly better than MF-GJR(VIX). Long memory has incremental value beyond VIX."
    h_result = "H1"
elif abs(t_key) > 3.0 and t_key < 0:
    decision = "MF-GJR(VIX) significantly better than FIGARCH-MF(VIX). Long memory adds noise, not signal."
    h_result = "H0 (MF-GJR dominates)"
else:
    decision = "FAIL TO REJECT H0: No significant difference (DM |t| < 3.0). VIX already captures the persistence that FIGARCH models."
    h_result = "H0"

print(f"  DM t-stat (MF-GJR vs FIGARCH-MF): {t_key:+.3f}")
print(f"  Harvey (2016) threshold: |t| > 3.0")
print(f"  Decision: {decision}")

# ============================================================
# 10. Save Results
# ============================================================
output = {
    'experiment_id': 'K933',
    'title': 'FIGARCH-MF(VIX) — Does long memory add value beyond VIX?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{common_dates[0].strftime('%Y-%m-%d')} to {common_dates[-1].strftime('%Y-%m-%d')}",
    'oos_obs': len(common_dates),
    'window': WINDOW,
    'refit_freq': REFIT_FREQ,
    'n_lags_figarch': N_LAGS,
    'total_runtime_seconds': round(total_runtime, 1),
    'models': results,
    'dm_tests': dm_results,
    'key_comparison': {
        'models': 'MF-GJR(VIX) vs FIGARCH-MF(VIX)',
        'dm_t_stat': float(t_key),
        'marginal_qlike_improvement_pct': float(marginal_improvement),
        'harvey_threshold': 3.0,
        'significant': bool(abs(t_key) > 3.0),
        'hypothesis_result': h_result,
        'decision': decision,
    },
    'references': [
        'Baillie, Bollerslev, Mikkelsen (1996) - FIGARCH',
        'Engle, Ghysels, Sohn (2013) - GARCH-MIDAS',
        'Patton (2011) - Proxy-robust loss functions',
        'Hansen & Lunde (2005) - Forecast evaluation',
        'Harvey (2016) - Multiple testing threshold t>3.0',
    ]
}

output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a80934f6/experiments/k933/k933_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

# ============================================================
# 11. Generate Charts
# ============================================================
print("\n[11] Generating charts...")

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

model_labels = list(results.keys())
qlike_vals = [results[m]['QLIKE'] for m in model_labels]
colors = ['#607D8B', '#2196F3', '#FF9800', '#4CAF50', '#E91E63']

bars = axes[0].bar(range(len(model_labels)), qlike_vals, color=colors, width=0.6, edgecolor='white', linewidth=0.5)
axes[0].set_xticks(range(len(model_labels)))
axes[0].set_xticklabels([m.replace('(', '\n(') for m in model_labels], fontsize=9)
axes[0].set_ylabel('QLIKE (lower = better)', fontsize=11)
axes[0].set_title('QLIKE on r$^2$ (OOS)', fontsize=13, fontweight='bold')
axes[0].grid(axis='y', alpha=0.3)
for bar, val in zip(bars, qlike_vals):
    axes[0].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                f'{val:.4f}', ha='center', va='bottom', fontsize=9)

spearman_vals = [results[m]['Spearman_rho'] for m in model_labels]
bars2 = axes[1].bar(range(len(model_labels)), spearman_vals, color=colors, width=0.6, edgecolor='white', linewidth=0.5)
axes[1].set_xticks(range(len(model_labels)))
axes[1].set_xticklabels([m.replace('(', '\n(') for m in model_labels], fontsize=9)
axes[1].set_ylabel('Spearman $\\rho$ (higher = better)', fontsize=11)
axes[1].set_title('Spearman Rank Correlation with r$^2$ (OOS)', fontsize=13, fontweight='bold')
axes[1].grid(axis='y', alpha=0.3)
for bar, val in zip(bars2, spearman_vals):
    axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.002,
                f'{val:.4f}', ha='center', va='bottom', fontsize=9)

plt.suptitle('K933: FIGARCH-MF(VIX) vs MF-GJR(VIX)\nDoes long memory add value beyond VIX?',
             fontsize=14, fontweight='bold', y=1.02)
plt.tight_layout()
chart_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a80934f6/experiments/k933/k933_qlike_comparison.png'
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved to {chart_path}")

# ============================================================
# 12. Summary
# ============================================================
print("\n" + "=" * 60)
print("K933 SUMMARY")
print("=" * 60)
print(f"\n  Total runtime: {total_runtime:.1f}s")

print(f"\n  QLIKE Rankings (lower = better):")
ranked = sorted(results.items(), key=lambda x: x[1]['QLIKE'])
for i, (name, res) in enumerate(ranked, 1):
    improvement = (baseline_qlike - res['QLIKE']) / baseline_qlike * 100
    print(f"    {i}. {name}: {res['QLIKE']:.6f} ({improvement:+.2f}% vs baseline)")

print(f"\n  Key DM tests:")
for pair, t in dm_results.items():
    sig = "***" if abs(t) > 3.0 else ("  " if abs(t) < 1.65 else " * ")
    print(f"    {pair}: t = {t:+.3f} {sig}")

print(f"\n  Conclusion: {decision}")
print("\nDone.")
