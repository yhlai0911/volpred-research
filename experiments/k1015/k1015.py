"""
K1015: VIX9D+VIX3M Dual-Factor A4f Model
=========================================
Data: SPY 2011-2026 (yfinance), VIX9D (^VIX9D), VIX3M (^VIX3M), VIX (^VIX)
OOS: adjusted to VIX9D/VIX3M availability (~2011+), window=2000, refit/63d
Models:
  M1: A4f-VIX9D-t   (baseline from K1004): tau = theta0 + theta1*VIX9D^2
  M2: A4f-VIX3M-t:  tau = theta0 + theta1*VIX3M^2
  M3: A4f-Dual-t:   tau = theta0 + theta1*VIX9D^2 + theta2*VIX3M^2
  M4: A4f-Slope-t:  tau = theta0 + theta1*VIX9D^2 + theta2*(VIX9D/VIX3M - 1)^2
  M5: A4f-VIX-t     (standard VIX reference)
  M6: GJR-t         (benchmark)
All models use Student-t distribution.

Evaluation: QLIKE on r^2 (Patton 2011 proxy-robust), DM test (Harvey t>3.0),
            VaR 2.5% (Kupiec + Christoffersen + DQ), ES 2.5% (Acerbi-Szekely)

Motivation: K1004 showed A4f-VIX9D DM t=-4.588 vs A4f-VIX (SPY). VIX9D captures
short-term fear, VIX3M captures medium-term. Does combining them improve further?
Does term structure slope (VIX9D/VIX3M - 1) carry incremental information?

Related experiments:
- K988/K988b: A4f(VIX^2) champion, DM t=+4.48 vs GJR
- K1004: A4f-VIX9D-t significantly beats A4f-VIX-t (SPY DM t=-4.588)
- K1003: VIX9D DM t=+5.15, VIX3M DM t=+2.59 (not robust)
- K879: VIX/VIX3M reversion speed NULL

References:
- Engle & Rangel (2008): Spline-GARCH component model
- Patton (2011): QLIKE loss, proxy-robust ranking
- Kupiec (1995), Christoffersen (1998): VaR backtesting
- Engle & Manganelli (2004): DQ test
- Acerbi & Szekely (2014): ES backtesting
- Harvey (2016): t>3.0 threshold for multiple testing
- CBOE VIX9D: 9-day expected volatility index
- CBOE VIX3M: 3-month expected volatility index
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import time
from datetime import datetime
from scipy.optimize import minimize
from scipy.stats import t as t_dist, chi2, norm
import math
import yfinance as yf
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data
# ============================================================
def load_data():
    """Load SPY + VIX + VIX9D + VIX3M data."""
    print("\nLoading SPY + ^VIX + ^VIX9D + ^VIX3M...")
    tickers = ['SPY', '^VIX', '^VIX9D', '^VIX3M']
    raw = {}
    for tk in tickers:
        d = yf.download(tk, start='2004-01-01', end='2026-12-31', progress=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        raw[tk] = d

    df = pd.DataFrame(index=raw['SPY'].index)
    df['close'] = raw['SPY']['Close']
    df['vix'] = raw['^VIX']['Close'].reindex(df.index, method='ffill')
    df['vix9d'] = raw['^VIX9D']['Close'].reindex(df.index, method='ffill')
    df['vix3m'] = raw['^VIX3M']['Close'].reindex(df.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna()
    df['ret'] = df['ret'].clip(-0.20, 0.20)
    df['r2'] = df['ret'] ** 2

    # Squared VIX variants (annualized vol -> daily variance)
    df['vix2'] = (df['vix'] / 100) ** 2
    df['vix9d2'] = (df['vix9d'] / 100) ** 2
    df['vix3m2'] = (df['vix3m'] / 100) ** 2

    # Term structure slope: (VIX9D/VIX3M - 1)^2
    # When VIX9D >> VIX3M, slope > 0 (contango broken, short-term fear spike)
    # When VIX9D << VIX3M, slope < 0 (normal contango)
    df['slope'] = (df['vix9d'] / df['vix3m'] - 1.0)
    df['slope2'] = df['slope'] ** 2

    # Report availability
    for col, name in [('vix9d', 'VIX9D'), ('vix3m', 'VIX3M')]:
        first_valid = df[df[col].notna()].index[0]
        print(f"  {name} available from: {first_valid.date()}")
    print(f"  SPY data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

    return df


# ============================================================
# 2. Numba-accelerated GARCH recursions
# ============================================================
@njit
def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


@njit
def t_logpdf_sum(returns, h, df):
    """Sum of Student-t logpdf with scale = sigma * sqrt((df-2)/df)."""
    T = len(returns)
    scale_factor = np.sqrt((df - 2.0) / df)
    c = math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0) - 0.5 * np.log(np.pi * df)
    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        s = sigma * scale_factor
        z = returns[t] / s
        ll += c - np.log(s) - (df + 1.0) / 2.0 * np.log(1.0 + z * z / df)
    return ll


@njit
def a4f_single_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    """Single-factor A4f: tau = theta0 + theta1 * vix2[t-1]"""
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2[t-1]  # lag-1 to avoid lookahead
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


@njit
def a4f_dual_recursion(theta0, theta1, theta2, omega, alpha, gamma, beta,
                        returns, vix9d2, vix3m2):
    """Dual-factor A4f: tau = theta0 + theta1 * vix9d2[t-1] + theta2 * vix3m2[t-1]"""
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix9d2[0] + theta2 * vix3m2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix9d2[t-1] + theta2 * vix3m2[t-1]  # lag-1
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


@njit
def a4f_slope_recursion(theta0, theta1, theta2, omega, alpha, gamma, beta,
                         returns, vix9d2, slope2):
    """Slope A4f: tau = theta0 + theta1 * vix9d2[t-1] + theta2 * slope2[t-1]"""
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix9d2[0] + theta2 * slope2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix9d2[t-1] + theta2 * slope2[t-1]  # lag-1
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


# ============================================================
# 3. Fitting functions
# ============================================================
def fit_gjr_t(returns):
    """Fit GJR-GARCH(1,1) with Student-t innovations."""
    var0 = np.var(returns)
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_h(p[0], p[1], p[2], p[3], returns)
            ll = t_logpdf_sum(returns, h, p[4])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, df_init]
        try:
            res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h = gjr_h(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3], returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success,
            'nll': best_res.fun, 'df': best_res.x[4]}


def fit_a4f_single_t(returns, vix2):
    """Fit single-factor A4f-t: tau = theta0 + theta1 * vix2."""
    # Step 1: Normal initialization
    bounds_n = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj_n(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_single_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            T = len(returns)
            ll = 0.0
            for t in range(T):
                ll += np.log(h[t]) + returns[t]**2 / h[t]
            v = 0.5 * ll
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_n, best_nll_n = None, 1e10
    for th1 in [0.3, 0.8, 2.0]:
        for om in [0.02, 0.08]:
            x0 = [1e-5, th1, om, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n, options={'maxiter': 300})
                if res.fun < best_nll_n:
                    best_nll_n = res.fun
                    best_n = res
            except:
                continue
    if best_n is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_n = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n)

    # Step 2: Student-t joint
    bounds_t = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj_t(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_single_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            ll = t_logpdf_sum(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(best_n.x) + [df_init]
        try:
            res = minimize(obj_t, p0, method='L-BFGS-B', bounds=bounds_t, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h, tau, g = a4f_single_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                                      best_res.x[3], best_res.x[4], best_res.x[5],
                                      returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun, 'df': best_res.x[6]}


def fit_a4f_dual_t(returns, vix9d2, vix3m2):
    """Fit dual-factor A4f-t: tau = theta0 + theta1*VIX9D^2 + theta2*VIX3M^2.
    theta1, theta2 >= 0 enforced via bounds."""
    # Step 1: Normal initialization
    bounds_n = [(-0.01, 0.01), (0.0, 5.0), (0.0, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj_n(p):
        if p[4] + 0.5*p[5] + p[6] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_dual_recursion(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                                          returns, vix9d2, vix3m2)
            T = len(returns)
            ll = 0.0
            for t in range(T):
                ll += np.log(h[t]) + returns[t]**2 / h[t]
            v = 0.5 * ll
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10

    best_n, best_nll_n = None, 1e10
    for th1 in [0.3, 1.0, 2.0]:
        for th2 in [0.0, 0.3, 1.0]:
            for om in [0.02, 0.08]:
                x0 = [1e-5, th1, th2, om, 0.04, 0.06, 0.90]
                try:
                    res = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n,
                                   options={'maxiter': 300})
                    if res.fun < best_nll_n:
                        best_nll_n = res.fun
                        best_n = res
                except:
                    continue
    if best_n is None:
        x0 = [1e-5, 0.5, 0.2, 0.05, 0.04, 0.06, 0.90]
        best_n = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n)

    # Step 2: Student-t
    bounds_t = [(-0.01, 0.01), (0.0, 5.0), (0.0, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj_t(p):
        if p[4] + 0.5*p[5] + p[6] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_dual_recursion(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                                          returns, vix9d2, vix3m2)
            ll = t_logpdf_sum(returns, h, p[7])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10

    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(best_n.x) + [df_init]
        try:
            res = minimize(obj_t, p0, method='L-BFGS-B', bounds=bounds_t,
                           options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h, tau, g = a4f_dual_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                                    best_res.x[3], best_res.x[4], best_res.x[5],
                                    best_res.x[6], returns, vix9d2, vix3m2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun, 'df': best_res.x[7]}


def fit_a4f_slope_t(returns, vix9d2, slope2):
    """Fit slope A4f-t: tau = theta0 + theta1*VIX9D^2 + theta2*(VIX9D/VIX3M-1)^2.
    theta1, theta2 >= 0 enforced via bounds."""
    # Step 1: Normal initialization
    bounds_n = [(-0.01, 0.01), (0.0, 5.0), (0.0, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj_n(p):
        if p[4] + 0.5*p[5] + p[6] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_slope_recursion(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                                           returns, vix9d2, slope2)
            T = len(returns)
            ll = 0.0
            for t in range(T):
                ll += np.log(h[t]) + returns[t]**2 / h[t]
            v = 0.5 * ll
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10

    best_n, best_nll_n = None, 1e10
    for th1 in [0.3, 1.0, 2.0]:
        for th2 in [0.0, 0.001, 0.01]:
            for om in [0.02, 0.08]:
                x0 = [1e-5, th1, th2, om, 0.04, 0.06, 0.90]
                try:
                    res = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n,
                                   options={'maxiter': 300})
                    if res.fun < best_nll_n:
                        best_nll_n = res.fun
                        best_n = res
                except:
                    continue
    if best_n is None:
        x0 = [1e-5, 0.5, 0.001, 0.05, 0.04, 0.06, 0.90]
        best_n = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n)

    # Step 2: Student-t
    bounds_t = [(-0.01, 0.01), (0.0, 5.0), (0.0, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj_t(p):
        if p[4] + 0.5*p[5] + p[6] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_slope_recursion(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                                           returns, vix9d2, slope2)
            ll = t_logpdf_sum(returns, h, p[7])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10

    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(best_n.x) + [df_init]
        try:
            res = minimize(obj_t, p0, method='L-BFGS-B', bounds=bounds_t,
                           options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h, tau, g = a4f_slope_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                                     best_res.x[3], best_res.x[4], best_res.x[5],
                                     best_res.x[6], returns, vix9d2, slope2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun, 'df': best_res.x[7]}


# ============================================================
# 4. OOS forecasting
# ============================================================
def oos_forecast(df, model_name, oos_start_date, window=2000, refit_every=63):
    """
    model_name: 'GJR_t', 'A4f_VIX9D_t', 'A4f_VIX3M_t', 'A4f_VIX_t',
                'A4f_Dual_t', 'A4f_Slope_t'
    """
    oos_start_idx = np.where(df.index >= oos_start_date)[0][0]
    T = len(df)
    forecasts = np.full(T, np.nan)
    df_estimates = np.full(T, np.nan)
    returns = df['ret'].values
    vix2 = df['vix2'].values
    vix9d2 = df['vix9d2'].values
    vix3m2 = df['vix3m2'].values
    slope2 = df['slope2'].values

    last_fit = None
    last_fit_idx = -refit_every
    h_prev = np.nan
    g_prev = np.nan

    for t in range(oos_start_idx, T):
        # Refit?
        if t - last_fit_idx >= refit_every or last_fit is None:
            s = max(0, t - window)
            tr = returns[s:t]

            if model_name == 'GJR_t':
                last_fit = fit_gjr_t(tr)
            elif model_name == 'A4f_VIX9D_t':
                last_fit = fit_a4f_single_t(tr, vix9d2[s:t])
            elif model_name == 'A4f_VIX3M_t':
                last_fit = fit_a4f_single_t(tr, vix3m2[s:t])
            elif model_name == 'A4f_VIX_t':
                last_fit = fit_a4f_single_t(tr, vix2[s:t])
            elif model_name == 'A4f_Dual_t':
                last_fit = fit_a4f_dual_t(tr, vix9d2[s:t], vix3m2[s:t])
            elif model_name == 'A4f_Slope_t':
                last_fit = fit_a4f_slope_t(tr, vix9d2[s:t], slope2[s:t])

            last_fit_idx = t
            h_prev = last_fit['h'][-1]
            g_prev = last_fit.get('g', np.array([1.0]))[-1]

        p = last_fit['params']

        if model_name == 'GJR_t':
            omega, alpha, gamma, beta = p[0], p[1], p[2], p[3]
            df_estimates[t] = p[4]
            r_prev = returns[t-1]
            r2p = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_t = omega + alpha * r2p + gamma * r2p * ind + beta * h_prev
            h_t = max(h_t, 1e-16)
            forecasts[t] = h_t
            h_prev = h_t

        elif model_name in ('A4f_VIX9D_t', 'A4f_VIX3M_t', 'A4f_VIX_t'):
            theta0, theta1, omega, alpha, gamma, beta, df_val = (
                p[0], p[1], p[2], p[3], p[4], p[5], p[6])
            df_estimates[t] = df_val
            if model_name == 'A4f_VIX9D_t':
                vix_val = vix9d2[t-1]  # lag-1
            elif model_name == 'A4f_VIX3M_t':
                vix_val = vix3m2[t-1]
            else:
                vix_val = vix2[t-1]
            tau_t = max(theta0 + theta1 * vix_val, 1e-16)
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
            g_t = max(g_t, 1e-16)
            forecasts[t] = tau_t * g_t
            g_prev = g_t

        elif model_name == 'A4f_Dual_t':
            theta0, theta1, theta2, omega, alpha, gamma, beta, df_val = (
                p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7])
            df_estimates[t] = df_val
            tau_t = max(theta0 + theta1 * vix9d2[t-1] + theta2 * vix3m2[t-1], 1e-16)
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
            g_t = max(g_t, 1e-16)
            forecasts[t] = tau_t * g_t
            g_prev = g_t

        elif model_name == 'A4f_Slope_t':
            theta0, theta1, theta2, omega, alpha, gamma, beta, df_val = (
                p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7])
            df_estimates[t] = df_val
            tau_t = max(theta0 + theta1 * vix9d2[t-1] + theta2 * slope2[t-1], 1e-16)
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev
            g_t = max(g_t, 1e-16)
            forecasts[t] = tau_t * g_t
            g_prev = g_t

    return forecasts, df_estimates


# ============================================================
# 5. Evaluation functions
# ============================================================
def qlike(r2, h):
    mask = ~np.isnan(h) & ~np.isnan(r2) & (h > 0)
    return np.mean(r2[mask] / h[mask] + np.log(h[mask]))


def dm_test(loss1, loss2):
    """Diebold-Mariano test with Newey-West HAC variance."""
    d = loss1 - loss2
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)
    max_lag = int(n ** (1/3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return t_stat, p_val


def qlike_losses(r2, h):
    """Per-observation QLIKE losses for DM test."""
    mask = ~np.isnan(h) & ~np.isnan(r2) & (h > 0)
    losses = np.full_like(r2, np.nan)
    losses[mask] = r2[mask] / h[mask] + np.log(h[mask])
    return losses


def kupiec_test(violations, T, alpha):
    n1 = np.sum(violations)
    n0 = T - n1
    pi_hat = n1 / T
    if pi_hat == 0 or pi_hat == 1:
        return 0, 1.0
    lr = 2 * (n1 * np.log(pi_hat / alpha) + n0 * np.log((1 - pi_hat) / (1 - alpha)))
    return lr, 1 - chi2.cdf(lr, 1)


def christoffersen_cc_test(violations):
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        v0, v1 = violations[t-1], violations[t]
        if v0 == 0 and v1 == 0: n00 += 1
        elif v0 == 0 and v1 == 1: n01 += 1
        elif v0 == 1 and v1 == 0: n10 += 1
        else: n11 += 1
    if (n00+n01) == 0 or (n10+n11) == 0:
        return 0, 1.0
    pi01 = n01 / (n00+n01)
    pi11 = n11 / (n10+n11)
    pi = (n01+n11) / T
    if pi in (0, 1) or pi01 in (0, 1) or pi11 in (0, 1):
        return 0, 1.0
    try:
        lr = 2 * (n00*np.log((1-pi01)/(1-pi)) + n01*np.log(pi01/pi)
                   + n10*np.log((1-pi11)/(1-pi)) + n11*np.log(pi11/pi))
    except:
        return 0, 1.0
    if np.isnan(lr):
        return 0, 1.0
    return lr, 1 - chi2.cdf(lr, 1)


def dq_test(violations, alpha, returns_arr, sigma_arr):
    T = len(violations)
    hit = violations.astype(float) - alpha
    X = np.column_stack([np.ones(T-1), hit[:-1], sigma_arr[1:]])
    y = hit[1:]
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        beta_coef = XtX_inv @ X.T @ y
        dq_stat = (beta_coef.T @ X.T @ X @ beta_coef) / (alpha * (1 - alpha))
        return dq_stat, 1 - chi2.cdf(dq_stat, X.shape[1])
    except:
        return 0, 1.0


def acerbi_szekely_z1(returns_arr, var_vals, es_vals, alpha):
    violations = returns_arr < var_vals
    n_viol = np.sum(violations)
    if n_viol == 0:
        return 0, 1.0
    T = len(returns_arr)
    z1 = np.sum(returns_arr[violations] / es_vals[violations]) / (T * alpha) + 1
    rng = np.random.default_rng(42)
    z1_boot = np.zeros(1000)
    for b in range(1000):
        idx = rng.choice(T, T, replace=True)
        rb = returns_arr[idx]; vb = var_vals[idx]; eb = es_vals[idx]
        viol_b = rb < vb
        if np.sum(viol_b) > 0:
            z1_boot[b] = np.sum(rb[viol_b] / eb[viol_b]) / (T * alpha) + 1
    return z1, float(np.mean(z1_boot <= z1))


def acerbi_szekely_z2(returns_arr, es_vals, alpha):
    T = len(returns_arr)
    k = int(np.floor(T * alpha))
    if k == 0:
        return 0, 1.0
    sorted_ret = np.sort(returns_arr)
    z2 = np.mean(sorted_ret[:k]) / np.mean(es_vals) - 1
    rng = np.random.default_rng(42)
    z2_boot = np.zeros(1000)
    for b in range(1000):
        idx = rng.choice(T, T, replace=True)
        rb = returns_arr[idx]; eb = es_vals[idx]
        z2_boot[b] = np.mean(np.sort(rb)[:k]) / np.mean(eb) - 1
    return z2, float(np.mean(z2_boot <= z2))


def compute_var_es(sigma, df_vals, alpha):
    """VaR and ES from sigma and df (Student-t). Normal fallback if df is NaN."""
    T = len(sigma)
    var_v = np.full(T, np.nan)
    es_v = np.full(T, np.nan)
    for i in range(T):
        s = sigma[i]
        if np.isnan(s) or s <= 0:
            continue
        if not np.isnan(df_vals[i]) and df_vals[i] > 2:
            df = df_vals[i]
            sf = np.sqrt((df-2)/df)
            q = t_dist.ppf(alpha, df)
            var_v[i] = s * q * sf
            pdf_q = t_dist.pdf(q, df)
            es_v[i] = s * sf * (-pdf_q / alpha) * ((df + q**2) / (df - 1))
        else:
            q = norm.ppf(alpha)
            var_v[i] = s * q
            es_v[i] = s * (-norm.pdf(q) / alpha)
    return var_v, es_v


def var_es_evaluation(returns_arr, sigma, df_vals, alpha):
    var_v, es_v = compute_var_es(sigma, df_vals, alpha)
    mask = ~np.isnan(var_v)
    ret = returns_arr[mask]; vv = var_v[mask]; ev = es_v[mask]; sig = sigma[mask]
    violations = (ret < vv).astype(int)
    T = len(ret)
    viol_rate = np.sum(violations) / T
    uc_stat, uc_p = kupiec_test(violations, T, alpha)
    cc_stat, cc_p = christoffersen_cc_test(violations)
    dq_stat, dq_p = dq_test(violations, alpha, ret, sig)

    es_z1 = es_z1_p = es_z2 = es_z2_p = None
    if abs(alpha - 0.025) < 0.001:
        es_z1, es_z1_p = acerbi_szekely_z1(ret, vv, ev, alpha)
        es_z2, es_z2_p = acerbi_szekely_z2(ret, ev, alpha)

    expected = T * alpha
    if np.sum(violations) <= expected * 1.5:
        basel = "GREEN"
    elif np.sum(violations) <= expected * 2.0:
        basel = "YELLOW"
    else:
        basel = "RED"

    n_pass = sum([uc_p > 0.05, cc_p > 0.05, dq_p > 0.05, basel == "GREEN"])
    if abs(alpha - 0.025) < 0.001 and es_z1_p is not None:
        n_pass_total = n_pass + sum([es_z1_p > 0.05, es_z2_p > 0.05])
        scorecard = f"{n_pass_total}/6"
    else:
        scorecard = f"{n_pass}/4"

    return {
        'alpha': alpha, 'T': T,
        'violations': int(np.sum(violations)),
        'violation_rate': round(viol_rate * 100, 2),
        'expected_rate': round(alpha * 100, 2),
        'UC_stat': round(uc_stat, 3), 'UC_p': round(uc_p, 4),
        'CC_stat': round(cc_stat, 3), 'CC_p': round(cc_p, 4),
        'DQ_stat': round(dq_stat, 3), 'DQ_p': round(dq_p, 4),
        'Basel': basel,
        'ES_Z1': round(es_z1, 4) if es_z1 is not None else None,
        'ES_Z1_p': round(es_z1_p, 4) if es_z1_p is not None else None,
        'ES_Z2': round(es_z2, 4) if es_z2 is not None else None,
        'ES_Z2_p': round(es_z2_p, 4) if es_z2_p is not None else None,
        'scorecard': scorecard,
    }


# ============================================================
# 6. Plotting
# ============================================================
def plot_qlike_comparison(model_names, qlike_values, save_path):
    """Bar chart of QLIKE scores across models."""
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#607D8B', '#F44336']
    bars = ax.bar(range(len(model_names)), qlike_values,
                  color=colors[:len(model_names)], edgecolor='black', linewidth=0.5)

    # Highlight the best (lowest QLIKE)
    best_idx = np.argmin(qlike_values)
    bars[best_idx].set_edgecolor('red')
    bars[best_idx].set_linewidth(2.5)

    ax.set_xticks(range(len(model_names)))
    ax.set_xticklabels(model_names, rotation=30, ha='right', fontsize=10)
    ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
    ax.set_title('K1015: QLIKE Comparison - VIX9D+VIX3M Dual-Factor A4f Models\n(SPY, OOS)', fontsize=13)

    # Add value labels
    for i, (bar, val) in enumerate(zip(bars, qlike_values)):
        label = f"{val:.6f}"
        if i == best_idx:
            label += " *"
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.0001,
                label, ha='center', va='bottom', fontsize=9)

    ax.set_ylim(min(qlike_values) * 0.9998, max(qlike_values) * 1.0005)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


def plot_var_timeline(df_dates, returns_oos, var_dict, model_labels, save_path, alpha=0.025):
    """Timeline of VaR violations for multiple models."""
    n_models = len(model_labels)
    fig, axes = plt.subplots(n_models, 1, figsize=(14, 3*n_models), sharex=True)
    if n_models == 1:
        axes = [axes]

    colors = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#607D8B', '#F44336']

    for i, label in enumerate(model_labels):
        ax = axes[i]
        var_vals = var_dict[label]
        mask = ~np.isnan(var_vals)
        dates = df_dates[mask]
        ret = returns_oos[mask]
        vv = var_vals[mask]
        violations = ret < vv
        viol_rate = np.sum(violations) / len(ret) * 100

        ax.plot(dates, ret, color='gray', alpha=0.4, linewidth=0.5, label='Returns')
        ax.plot(dates, vv, color=colors[i % len(colors)], linewidth=0.8, label=f'VaR {alpha*100:.1f}%')
        ax.scatter(dates[violations], ret[violations], color='red', s=10, zorder=5,
                   label=f'Violations ({np.sum(violations)})')
        ax.set_ylabel('Return', fontsize=9)
        ax.set_title(f'{label} (violation rate: {viol_rate:.2f}%, expected: {alpha*100:.1f}%)',
                      fontsize=10)
        ax.legend(loc='lower left', fontsize=8)
        ax.axhline(0, color='black', linewidth=0.3)

    axes[-1].set_xlabel('Date', fontsize=10)
    fig.suptitle('K1015: VaR 2.5% Violation Timeline', fontsize=13, y=1.01)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {save_path}")


# ============================================================
# 7. Main
# ============================================================
def main():
    print("=" * 70)
    print("K1015: VIX9D+VIX3M Dual-Factor A4f Model")
    print("=" * 70)

    t_start = time.time()
    df = load_data()

    # Determine OOS start: need window=2000 + VIX9D/VIX3M availability
    oos_desired = '2014-01-01'
    desired_idx = np.where(df.index >= oos_desired)[0]
    if len(desired_idx) == 0:
        print("ERROR: OOS start beyond data range")
        return
    desired_idx = desired_idx[0]
    actual_oos_start = max(desired_idx, 2000)
    actual_oos_date = df.index[actual_oos_start].strftime('%Y-%m-%d')
    print(f"\nOOS start: {actual_oos_date} (window=2000)")

    oos_mask = np.array(df.index >= actual_oos_date)
    returns_oos = df['ret'].values[oos_mask]
    r2_oos = df['r2'].values[oos_mask]
    n_oos = int(oos_mask.sum())
    oos_dates = df.index[oos_mask]
    print(f"OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}, N={n_oos}")

    # Descriptive statistics
    print(f"\nDescriptive stats (OOS):")
    print(f"  Mean return: {np.mean(returns_oos):.6f}")
    print(f"  Std return:  {np.std(returns_oos):.6f}")
    print(f"  Skewness:    {pd.Series(returns_oos).skew():.4f}")
    print(f"  Kurtosis:    {pd.Series(returns_oos).kurtosis():.4f}")
    print(f"  VIX9D mean:  {df['vix9d'][oos_mask].mean():.2f}")
    print(f"  VIX3M mean:  {df['vix3m'][oos_mask].mean():.2f}")
    print(f"  Slope mean:  {df['slope'][oos_mask].mean():.4f}")
    print(f"  Slope std:   {df['slope'][oos_mask].std():.4f}")

    # Model configurations
    model_configs = [
        ('M1: A4f-VIX9D',  'A4f_VIX9D_t'),
        ('M2: A4f-VIX3M',  'A4f_VIX3M_t'),
        ('M3: A4f-Dual',   'A4f_Dual_t'),
        ('M4: A4f-Slope',  'A4f_Slope_t'),
        ('M5: A4f-VIX',    'A4f_VIX_t'),
        ('M6: GJR-t',      'GJR_t'),
    ]

    forecasts_all = {}
    df_all = {}
    qlike_all = {}
    qlike_losses_all = {}
    var_dict = {}  # for plotting

    for label, model_type in model_configs:
        print(f"\n{'='*50}")
        print(f"Running {label} ({model_type})...")
        print(f"{'='*50}")
        t0 = time.time()
        h_forecast, df_est = oos_forecast(df, model_type, actual_oos_date,
                                           window=2000, refit_every=63)
        elapsed = time.time() - t0
        print(f"  Elapsed: {elapsed:.1f}s")

        h_oos = h_forecast[oos_mask]
        df_oos = df_est[oos_mask]
        sigma_oos = np.sqrt(h_oos)
        forecasts_all[label] = h_oos
        df_all[label] = df_oos

        ql = qlike(r2_oos, h_oos)
        qlike_all[label] = ql
        qlike_losses_all[label] = qlike_losses(r2_oos, h_oos)
        print(f"  QLIKE = {ql:.6f}")

        # VaR/ES at 2.5%
        ve = var_es_evaluation(returns_oos, sigma_oos, df_oos, 0.025)
        print(f"  VaR 2.5%: violations={ve['violations']}/{ve['T']}, "
              f"rate={ve['violation_rate']}%, "
              f"Kupiec p={ve['UC_p']:.4f}, CC p={ve['CC_p']:.4f}, "
              f"DQ p={ve['DQ_p']:.4f}, Basel={ve['Basel']}")
        if ve['ES_Z1'] is not None:
            print(f"  ES 2.5%: Z1={ve['ES_Z1']:.4f} (p={ve['ES_Z1_p']:.4f}), "
                  f"Z2={ve['ES_Z2']:.4f} (p={ve['ES_Z2_p']:.4f})")
        print(f"  Scorecard: {ve['scorecard']}")

        # Store VaR for timeline plot
        var_v, _ = compute_var_es(sigma_oos, df_oos, 0.025)
        var_dict[label] = var_v

    # ============================================================
    # DM Tests
    # ============================================================
    print(f"\n{'='*70}")
    print("DM Tests (negative t = first model better)")
    print(f"{'='*70}")

    dm_pairs = [
        ('M1: A4f-VIX9D', 'M3: A4f-Dual',  'M1 vs M3 (single vs dual)'),
        ('M1: A4f-VIX9D', 'M4: A4f-Slope',  'M1 vs M4 (single vs slope)'),
        ('M3: A4f-Dual',  'M6: GJR-t',      'M3 vs M6 (dual vs GJR)'),
        ('M1: A4f-VIX9D', 'M2: A4f-VIX3M',  'M1 vs M2 (VIX9D vs VIX3M)'),
        ('M1: A4f-VIX9D', 'M5: A4f-VIX',    'M1 vs M5 (VIX9D vs VIX)'),
        ('M1: A4f-VIX9D', 'M6: GJR-t',      'M1 vs M6 (VIX9D vs GJR)'),
        ('M3: A4f-Dual',  'M1: A4f-VIX9D',  'M3 vs M1 (dual vs single)'),
        ('M4: A4f-Slope', 'M1: A4f-VIX9D',  'M4 vs M1 (slope vs single)'),
    ]

    dm_results = {}
    for m1_label, m2_label, desc in dm_pairs:
        l1 = qlike_losses_all[m1_label]
        l2 = qlike_losses_all[m2_label]
        t_stat, p_val = dm_test(l1, l2)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.5 else (
            "*" if abs(t_stat) > 1.96 else ""))
        print(f"  {desc}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")
        dm_results[desc] = {'t_stat': round(t_stat, 3), 'p_value': round(p_val, 4),
                            'harvey_significant': abs(t_stat) > 3.0}

    # ============================================================
    # Check theta2 degeneracy (dual/slope models)
    # ============================================================
    print(f"\n{'='*70}")
    print("Parameter Degeneracy Check")
    print(f"{'='*70}")

    # Re-fit final window to check theta2
    final_s = max(0, len(df) - 2000)
    final_returns = df['ret'].values[final_s:]
    final_vix9d2 = df['vix9d2'].values[final_s:]
    final_vix3m2 = df['vix3m2'].values[final_s:]
    final_slope2 = df['slope2'].values[final_s:]

    dual_fit = fit_a4f_dual_t(final_returns, final_vix9d2, final_vix3m2)
    slope_fit = fit_a4f_slope_t(final_returns, final_vix9d2, final_slope2)

    p_dual = dual_fit['params']
    p_slope = slope_fit['params']
    print(f"  M3 (Dual) final params: theta0={p_dual[0]:.6f}, theta1(VIX9D)={p_dual[1]:.4f}, "
          f"theta2(VIX3M)={p_dual[2]:.4f}")
    print(f"    omega={p_dual[3]:.6f}, alpha={p_dual[4]:.4f}, gamma={p_dual[5]:.4f}, "
          f"beta={p_dual[6]:.4f}, df={p_dual[7]:.2f}")
    print(f"    persistence = {p_dual[4] + 0.5*p_dual[5] + p_dual[6]:.4f}")
    print(f"    theta2 == 0? {'YES (degenerate)' if p_dual[2] < 1e-4 else 'NO (incremental)'}")

    print(f"  M4 (Slope) final params: theta0={p_slope[0]:.6f}, theta1(VIX9D)={p_slope[1]:.4f}, "
          f"theta2(slope)={p_slope[2]:.4f}")
    print(f"    omega={p_slope[3]:.6f}, alpha={p_slope[4]:.4f}, gamma={p_slope[5]:.4f}, "
          f"beta={p_slope[6]:.4f}, df={p_slope[7]:.2f}")
    print(f"    persistence = {p_slope[4] + 0.5*p_slope[5] + p_slope[6]:.4f}")
    print(f"    theta2 == 0? {'YES (degenerate)' if p_slope[2] < 1e-4 else 'NO (incremental)'}")

    # ============================================================
    # VaR/ES full evaluation
    # ============================================================
    print(f"\n{'='*70}")
    print("VaR/ES Full Evaluation (alpha=2.5%)")
    print(f"{'='*70}")

    var_es_results = {}
    for label in [m[0] for m in model_configs]:
        h_oos = forecasts_all[label]
        df_oos = df_all[label]
        sigma_oos = np.sqrt(h_oos)
        ve = var_es_evaluation(returns_oos, sigma_oos, df_oos, 0.025)
        var_es_results[label] = ve
        print(f"  {label}: viols={ve['violations']}/{ve['T']}, "
              f"rate={ve['violation_rate']}%, "
              f"UC_p={ve['UC_p']:.4f}, CC_p={ve['CC_p']:.4f}, "
              f"DQ_p={ve['DQ_p']:.4f}, Basel={ve['Basel']}, "
              f"Score={ve['scorecard']}")

    # ============================================================
    # Plots
    # ============================================================
    print(f"\n{'='*70}")
    print("Generating plots...")
    print(f"{'='*70}")

    # Plot 1: QLIKE bar chart
    model_names = [m[0] for m in model_configs]
    qlike_values = [qlike_all[m] for m in model_names]
    plot_qlike_comparison(model_names, qlike_values,
                          os.path.join(SCRIPT_DIR, 'k1015_qlike_comparison.png'))

    # Plot 2: VaR timeline (top 4 models)
    top_labels = ['M1: A4f-VIX9D', 'M3: A4f-Dual', 'M4: A4f-Slope', 'M6: GJR-t']
    plot_var_timeline(oos_dates, returns_oos, var_dict, top_labels,
                      os.path.join(SCRIPT_DIR, 'k1015_var_timeline.png'))

    # ============================================================
    # Save results
    # ============================================================
    total_time = time.time() - t_start

    results = {
        'experiment_id': 'K1015',
        'title': 'VIX9D+VIX3M Dual-Factor A4f Model',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data': {
            'asset': 'SPY',
            'source': 'yfinance',
            'period': f"{df.index[0].date()} to {df.index[-1].date()}",
            'total_obs': len(df),
            'oos_start': actual_oos_date,
            'oos_obs': n_oos,
            'oos_period': f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
        },
        'descriptive_stats': {
            'mean_return': round(float(np.mean(returns_oos)), 6),
            'std_return': round(float(np.std(returns_oos)), 6),
            'skewness': round(float(pd.Series(returns_oos).skew()), 4),
            'kurtosis': round(float(pd.Series(returns_oos).kurtosis()), 4),
            'vix9d_mean': round(float(df['vix9d'][oos_mask].mean()), 2),
            'vix3m_mean': round(float(df['vix3m'][oos_mask].mean()), 2),
            'slope_mean': round(float(df['slope'][oos_mask].mean()), 4),
            'slope_std': round(float(df['slope'][oos_mask].std()), 4),
        },
        'models': {
            'M1_A4f_VIX9D': {
                'spec': 'tau = theta0 + theta1 * VIX9D^2',
                'distribution': 'Student-t',
                'QLIKE': round(qlike_all['M1: A4f-VIX9D'], 6),
            },
            'M2_A4f_VIX3M': {
                'spec': 'tau = theta0 + theta1 * VIX3M^2',
                'distribution': 'Student-t',
                'QLIKE': round(qlike_all['M2: A4f-VIX3M'], 6),
            },
            'M3_A4f_Dual': {
                'spec': 'tau = theta0 + theta1 * VIX9D^2 + theta2 * VIX3M^2',
                'distribution': 'Student-t',
                'QLIKE': round(qlike_all['M3: A4f-Dual'], 6),
                'theta2_degenerate': bool(p_dual[2] < 1e-4),
                'final_theta2': round(float(p_dual[2]), 6),
            },
            'M4_A4f_Slope': {
                'spec': 'tau = theta0 + theta1 * VIX9D^2 + theta2 * (VIX9D/VIX3M - 1)^2',
                'distribution': 'Student-t',
                'QLIKE': round(qlike_all['M4: A4f-Slope'], 6),
                'theta2_degenerate': bool(p_slope[2] < 1e-4),
                'final_theta2': round(float(p_slope[2]), 6),
            },
            'M5_A4f_VIX': {
                'spec': 'tau = theta0 + theta1 * VIX^2',
                'distribution': 'Student-t',
                'QLIKE': round(qlike_all['M5: A4f-VIX'], 6),
            },
            'M6_GJR_t': {
                'spec': 'GJR-GARCH(1,1)-t',
                'QLIKE': round(qlike_all['M6: GJR-t'], 6),
            },
        },
        'qlike_ranking': sorted(
            [(m, round(qlike_all[m], 6)) for m in qlike_all],
            key=lambda x: x[1]
        ),
        'dm_tests': dm_results,
        'var_es_2_5pct': {label: var_es_results[label] for label in var_es_results},
        'parameter_check': {
            'M3_dual_final': {
                'theta0': round(float(p_dual[0]), 6),
                'theta1_VIX9D': round(float(p_dual[1]), 4),
                'theta2_VIX3M': round(float(p_dual[2]), 4),
                'omega': round(float(p_dual[3]), 6),
                'alpha': round(float(p_dual[4]), 4),
                'gamma': round(float(p_dual[5]), 4),
                'beta': round(float(p_dual[6]), 4),
                'df': round(float(p_dual[7]), 2),
                'persistence': round(float(p_dual[4] + 0.5*p_dual[5] + p_dual[6]), 4),
                'converged': bool(dual_fit['converged']),
            },
            'M4_slope_final': {
                'theta0': round(float(p_slope[0]), 6),
                'theta1_VIX9D': round(float(p_slope[1]), 4),
                'theta2_slope': round(float(p_slope[2]), 4),
                'omega': round(float(p_slope[3]), 6),
                'alpha': round(float(p_slope[4]), 4),
                'gamma': round(float(p_slope[5]), 4),
                'beta': round(float(p_slope[6]), 4),
                'df': round(float(p_slope[7]), 2),
                'persistence': round(float(p_slope[4] + 0.5*p_slope[5] + p_slope[6]), 4),
                'converged': bool(slope_fit['converged']),
            },
        },
        'conclusions': {
            'best_model': sorted(qlike_all.items(), key=lambda x: x[1])[0][0],
            'best_qlike': sorted(qlike_all.values())[0],
            'dual_adds_value': not (p_dual[2] < 1e-4),
            'slope_adds_value': not (p_slope[2] < 1e-4),
        },
        'methodology': {
            'window': 2000,
            'refit_every': 63,
            'evaluation_target': 'r^2 (Patton 2011 proxy-robust)',
            'dm_threshold': 'Harvey (2016) |t| > 3.0',
            'var_alpha': 0.025,
            'es_method': 'Acerbi-Szekely (2014)',
            'seed': 42,
        },
        'references': [
            'Engle & Rangel (2008) - Spline-GARCH',
            'Patton (2011) - QLIKE loss proxy-robust ranking',
            'Kupiec (1995) - VaR unconditional coverage',
            'Christoffersen (1998) - VaR conditional coverage',
            'Engle & Manganelli (2004) - DQ test',
            'Acerbi & Szekely (2014) - ES backtesting',
            'Harvey (2016) - Multiple testing threshold t>3.0',
        ],
        'runtime_seconds': round(total_time, 1),
    }

    results_path = os.path.join(SCRIPT_DIR, 'k1015_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {results_path}")
    print(f"Total runtime: {total_time:.1f}s")

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print("QLIKE ranking (lower = better):")
    for rank, (model, ql) in enumerate(results['qlike_ranking'], 1):
        print(f"  {rank}. {model}: {ql:.6f}")
    print(f"\nBest model: {results['conclusions']['best_model']}")
    print(f"Dual factor adds value: {results['conclusions']['dual_adds_value']}")
    print(f"Slope adds value: {results['conclusions']['slope_adds_value']}")


if __name__ == '__main__':
    main()
