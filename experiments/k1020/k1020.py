#!/usr/bin/env python3
"""
K1020: MS(2)-A4f — Markov Regime Switching + VIX Multiplicative GARCH-X
=======================================================================
[提出: 賴奕豪, 執行: Claude]

Research Question:
  K1019 showed MS(2)-GJR significantly beats GJR-t (DM t=-3.20) but loses
  to A4f-VIX9D (DM t=+2.75, NS). Regime probability and VIX are only weakly
  correlated (r=0.225), suggesting they capture different information.
  Can combining both regime switching and VIX external information beat either alone?

Models:
  M1: GJR-t (baseline)
  M2: A4f-VIX9D-t (K1004 current best, multiplicative: σ²=τ×g)
  M3: MS(2)-GJR-N (K1019, 2-regime Hamilton filter)
  M4: MS(2)-A4f — 2-regime multiplicative GARCH-X (NEW)
      Simplified: shared g-dynamics (alpha, gamma, beta), regime-specific tau
      Regime s: tau_{s,t} = theta0_s + theta1_s * VIX9D²_{t-1}
      g_t = omega + alpha * u² + gamma * u² * I(u<0) + beta * g_{t-1}
      u_t = r_t / sqrt(tau_{regime_t,t})
      sigma²_t = sum_s P(s_t=s) * tau_{s,t} * g_t
  M5: A4f-VIX9D + regime_prob (A4f with K1019 regime probability as extra regressor)
      tau_t = theta0 + theta1 * VIX9D² + theta2 * P(crisis_t)

Data: SPY 2005-2026 (yfinance), VIX9D (^VIX9D), VIX (^VIX)
OOS: 2013-2026 (after 2000-day window)
Evaluation: QLIKE on r² (Patton 2011), DM test (Harvey t>3.0), VaR 2.5%

References:
- Hamilton (1989): A New Approach to the Economic Analysis of Nonstationary
  Time Series and the Business Cycle. Econometrica, 57(2), 357-384.
- Gray (1996): Modeling the Conditional Distribution of Interest Rates as a
  Regime-Switching Process. JFE, 42(1), 27-62.
- Klaassen (2002): Improving GARCH Volatility Forecasts with RS. Emp Econ.
- Haas, Mittnik & Paolella (2004): Mixed Normal Conditional Heteroskedasticity.
  JFEC, 2(4), 493-530.
- Engle & Rangel (2008): Spline-GARCH. RFS.
- Patton (2011): QLIKE loss. J Econometrics, 160(1), 246-256.
- Harvey (2016): t>3.0 threshold.
- Kupiec (1995), Christoffersen (1998): VaR backtesting.
- Acerbi & Szekely (2014): ES backtesting.

seed = 42
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import time
from datetime import datetime, timezone
from scipy.optimize import minimize
from scipy.stats import norm, chi2, t as t_dist
from numba import njit
import math
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
START_TIME = time.time()

# ============================================================
# 1. Data Loading
# ============================================================
def load_data():
    """Load SPY + VIX + VIX9D data."""
    print("\n" + "=" * 70)
    print("K1020: MS(2)-A4f — Regime Switching + VIX Multiplicative GARCH-X")
    print("=" * 70)
    print("\n[1] Loading data...")

    spy = yf.download('SPY', start='2003-01-01', end='2026-12-31', progress=False)
    vix = yf.download('^VIX', start='2003-01-01', end='2026-12-31', progress=False)
    vix9d = yf.download('^VIX9D', start='2003-01-01', end='2026-12-31', progress=False)

    for d in [spy, vix, vix9d]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['close'] = spy['Close']
    df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    df['vix9d'] = vix9d['Close'].reindex(spy.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna(subset=['ret', 'close', 'vix'])
    df['ret'] = df['ret'].clip(-0.20, 0.20)
    df['r2'] = df['ret'] ** 2
    df['vix9d2'] = (df['vix9d'] / 100.0) ** 2  # VIX9D in variance scale

    # VIX percentile for initialization
    df['vix_pct'] = df['vix'].rolling(252, min_periods=126).apply(
        lambda x: (x.values[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=False
    )
    df['vix_pct'] = df['vix_pct'].fillna(0.5)

    vix9d_start = df[df['vix9d'].notna()].index[0]
    print(f"  SPY: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    print(f"  VIX9D available from: {vix9d_start.date()}")

    return df


# ============================================================
# 2. Numba-accelerated GARCH cores
# ============================================================
@njit
def gjr_h(omega, alpha, gamma, beta, returns):
    """GJR-GARCH variance recursion."""
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
    """Sum of Student-t log-pdf with scale sqrt((df-2)/df)."""
    T = len(returns)
    scale_factor = np.sqrt((df - 2.0) / df)
    c = math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0) - 0.5 * np.log(np.pi * df)
    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        s = sigma * scale_factor
        if s < 1e-16:
            s = 1e-16
        z = returns[t] / s
        ll += c - np.log(s) - (df + 1.0) / 2.0 * np.log(1.0 + z * z / df)
    return ll


@njit
def gjr_nll_t(omega, alpha, gamma, beta, df, returns):
    """GJR-GARCH Student-t NLL (negative of ll)."""
    h = gjr_h(omega, alpha, gamma, beta, returns)
    ll = t_logpdf_sum(returns, h, df)
    return -ll if np.isfinite(ll) else 1e10


@njit
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    """Multiplicative A4f recursion: sigma^2 = tau * g."""
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
        tau[t] = theta0 + theta1 * vix2[t-1]  # lagged VIX (no lookahead)
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
def a4f_nll_normal(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    """A4f Normal NLL."""
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


# ============================================================
# 3. Model M1: GJR-t (baseline)
# ============================================================
def fit_gjr_t(returns):
    """Fit GJR-GARCH(1,1) with Student-t innovations."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(params):
        omega, alpha, gamma_p, beta, df = params
        if alpha + 0.5 * gamma_p + beta >= 1.0:
            return 1e10
        if df <= 2.01:
            return 1e10
        return gjr_nll_t(omega, alpha, gamma_p, beta, df, ret)

    best_res, best_val = None, 1e20
    starts = [
        [var0 * 0.05, 0.05, 0.10, 0.85, 8.0],
        [var0 * 0.02, 0.03, 0.08, 0.88, 6.0],
        [var0 * 0.10, 0.08, 0.15, 0.75, 10.0],
    ]
    bounds = [(1e-10, 0.01), (1e-6, 0.5), (1e-6, 0.5), (0.3, 0.999), (2.1, 100)]

    for x0 in starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500})
            if res.fun < best_val:
                best_val = res.fun
                best_res = res
        except:
            pass

    if best_res is None:
        return None
    p = best_res.x
    h = gjr_h(p[0], p[1], p[2], p[3], ret)
    return {
        'params': p, 'h': h, 'df': p[4],
        'persistence': p[1] + 0.5 * p[2] + p[3],
        'converged': best_res.success, 'nll': best_val
    }


# ============================================================
# 4. Model M2: A4f-VIX9D-t (K1004 best)
# ============================================================
def fit_a4f_t(returns, vix2):
    """Fit A4f with Student-t innovations."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    v2 = np.ascontiguousarray(vix2, dtype=np.float64)

    # First get Normal estimates as starting point
    bounds_n = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj_n(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            return a4f_nll_normal(p[0], p[1], p[2], p[3], p[4], p[5], ret, v2)
        except:
            return 1e10

    best_n_res, best_n_val = None, 1e20
    for t1 in [0.3, 0.8, 2.0]:
        for om in [0.02, 0.08]:
            x0 = [1e-5, t1, om, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n,
                              options={'maxiter': 300})
                if res.fun < best_n_val:
                    best_n_val = res.fun
                    best_n_res = res
            except:
                continue

    if best_n_res is None:
        return None

    # Now Student-t joint estimation
    bounds_t = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj_t(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], ret, v2)
            ll = t_logpdf_sum(ret, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10

    best_res, best_val = None, 1e20
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(best_n_res.x) + [df_init]
        try:
            res = minimize(obj_t, p0, method='L-BFGS-B', bounds=bounds_t,
                          options={'maxiter': 300})
            if res.fun < best_val:
                best_val = res.fun
                best_res = res
        except:
            continue

    if best_res is None:
        return None
    p = best_res.x
    h, tau, g = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], ret, v2)
    return {
        'params': p, 'h': h, 'tau': tau, 'g': g, 'df': p[6],
        'persistence': p[3] + 0.5*p[4] + p[5],
        'converged': best_res.success, 'nll': best_val
    }


# ============================================================
# 5. Model M3: MS(2)-GJR-N (Markov-Switching GJR)
# ============================================================
@njit
def ms_gjr_filter(omega0, alpha0, gamma0, beta0,
                  omega1, alpha1, gamma1, beta1,
                  p00, p11, returns):
    """
    Hamilton filter for 2-regime GJR-GARCH with Normal innovations.
    Gray (1996) variance collapse approach.
    """
    T = len(returns)
    xi_filt = np.empty(T)  # P(s_t=0 | info_t)
    h0 = np.empty(T)
    h1 = np.empty(T)
    h_comb = np.empty(T)

    denom = 2.0 - p00 - p11
    if abs(denom) < 1e-10:
        pi0 = 0.5
    else:
        pi0 = (1.0 - p11) / denom
    pi0 = max(min(pi0, 0.99), 0.01)

    var_all = np.var(returns)
    h0[0] = var_all * 0.5
    h1[0] = var_all * 2.0
    xi_filt[0] = pi0
    h_comb[0] = pi0 * h0[0] + (1.0 - pi0) * h1[0]

    log_lik = 0.0
    for t in range(1, T):
        xi_pred_0 = p00 * xi_filt[t-1] + (1.0 - p11) * (1.0 - xi_filt[t-1])
        xi_pred_0 = max(min(xi_pred_0, 1.0 - 1e-8), 1e-8)
        xi_pred_1 = 1.0 - xi_pred_0

        r2_prev = returns[t-1] ** 2
        ind_prev = 1.0 if returns[t-1] < 0 else 0.0
        h_prev = h_comb[t-1]

        h0[t] = omega0 + alpha0 * r2_prev + gamma0 * r2_prev * ind_prev + beta0 * h_prev
        h1[t] = omega1 + alpha1 * r2_prev + gamma1 * r2_prev * ind_prev + beta1 * h_prev
        h0[t] = max(h0[t], 1e-16)
        h1[t] = max(h1[t], 1e-16)

        r_t = returns[t]
        f0 = (1.0 / np.sqrt(2.0 * np.pi * h0[t])) * np.exp(-0.5 * r_t**2 / h0[t])
        f1 = (1.0 / np.sqrt(2.0 * np.pi * h1[t])) * np.exp(-0.5 * r_t**2 / h1[t])
        f_total = xi_pred_0 * f0 + xi_pred_1 * f1
        if f_total < 1e-300:
            f_total = 1e-300

        log_lik += np.log(f_total)
        xi_filt[t] = xi_pred_0 * f0 / f_total
        xi_filt[t] = max(min(xi_filt[t], 1.0 - 1e-8), 1e-8)
        h_comb[t] = xi_filt[t] * h0[t] + (1.0 - xi_filt[t]) * h1[t]

    return log_lik, xi_filt, h0, h1, h_comb


def fit_ms_gjr(returns, n_starts=10):
    """Fit MS(2)-GJR with Normal innovations (unconstrained parameterization)."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def inv_sig(y, upper=1.0):
        y_c = max(min(y, upper * 0.999), upper * 0.001)
        return np.log(y_c / (upper - y_c))

    def neg_ll(x):
        omega0 = np.exp(x[0])
        alpha0 = 0.4 / (1.0 + np.exp(-x[1]))
        gamma0 = 0.6 / (1.0 + np.exp(-x[2]))
        beta0  = 0.999 / (1.0 + np.exp(-x[3]))
        omega1 = np.exp(x[4])
        alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
        gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
        beta1  = 0.999 / (1.0 + np.exp(-x[7]))
        p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01
        p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01

        if alpha0 + 0.5*gamma0 + beta0 >= 0.999:
            return 1e10
        if alpha1 + 0.5*gamma1 + beta1 >= 0.999:
            return 1e10

        ll, _, _, _, _ = ms_gjr_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1,
            p00, p11, ret)
        return -ll if np.isfinite(ll) else 1e10

    rng = np.random.RandomState(42)
    best_val, best_x = 1e20, None

    base_starts = [
        [np.log(var0*0.01), inv_sig(0.02, 0.4), inv_sig(0.05, 0.6), inv_sig(0.90, 0.999),
         np.log(var0*0.10), inv_sig(0.10, 0.4), inv_sig(0.20, 0.6), inv_sig(0.70, 0.999),
         inv_sig(0.96, 0.98), inv_sig(0.90, 0.98)],
        [np.log(var0*0.005), inv_sig(0.01, 0.4), inv_sig(0.03, 0.6), inv_sig(0.93, 0.999),
         np.log(var0*0.05), inv_sig(0.05, 0.4), inv_sig(0.15, 0.6), inv_sig(0.75, 0.999),
         inv_sig(0.97, 0.98), inv_sig(0.85, 0.98)],
    ]
    all_starts = list(base_starts)
    for _ in range(n_starts - len(base_starts)):
        base = base_starts[rng.randint(len(base_starts))]
        perturbed = [b + rng.normal(0, 0.5) for b in base]
        all_starts.append(perturbed)

    for x0 in all_starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B',
                          options={'maxiter': 2000, 'ftol': 1e-10})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except:
            pass

    if best_x is None:
        return None

    x = best_x
    omega0 = np.exp(x[0])
    alpha0 = 0.4 / (1.0 + np.exp(-x[1]))
    gamma0 = 0.6 / (1.0 + np.exp(-x[2]))
    beta0  = 0.999 / (1.0 + np.exp(-x[3]))
    omega1 = np.exp(x[4])
    alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
    gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
    beta1  = 0.999 / (1.0 + np.exp(-x[7]))
    p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01
    p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01

    ll, xi_filt, h0_arr, h1_arr, h_comb = ms_gjr_filter(
        omega0, alpha0, gamma0, beta0,
        omega1, alpha1, gamma1, beta1,
        p00, p11, ret)

    return {
        'regime0': {'omega': omega0, 'alpha': alpha0, 'gamma': gamma0, 'beta': beta0,
                    'persistence': alpha0 + 0.5*gamma0 + beta0},
        'regime1': {'omega': omega1, 'alpha': alpha1, 'gamma': gamma1, 'beta': beta1,
                    'persistence': alpha1 + 0.5*gamma1 + beta1},
        'p00': p00, 'p11': p11,
        'h_combined': h_comb, 'xi_filtered': xi_filt,
        'h0': h0_arr, 'h1': h1_arr,
        'converged': True, 'nll': best_val,
        'raw_x': best_x
    }


# ============================================================
# 6. Model M4: MS(2)-A4f (NEW — regime-specific tau, shared g)
# ============================================================
# Simplified MS(2)-A4f: shared g-dynamics but regime-specific tau parameters
# This keeps the parameter count manageable (12 params instead of 18+)
# Parameters: theta0_0, theta1_0, theta0_1, theta1_1, omega, alpha, gamma, beta, p00, p11

@njit
def ms_a4f_filter(theta0_0, theta1_0, theta0_1, theta1_1,
                  omega, alpha, gamma, beta,
                  p00, p11, returns, vix2):
    """
    Hamilton filter for MS(2)-A4f with shared g-dynamics.

    Each regime has its own tau: tau_{s,t} = theta0_s + theta1_s * VIX²_{t-1}
    Shared short-run: g_t = omega + alpha*u² + gamma*u²*I(u<0) + beta*g_{t-1}
    where u_t = r_t / sqrt(tau_combined_t) (using regime-weighted tau)

    sigma²_{s,t} = tau_{s,t} * g_t
    sigma²_combined = P(s=0)*tau_0*g + P(s=1)*tau_1*g = g * (P(s=0)*tau_0 + P(s=1)*tau_1)
    """
    T = len(returns)
    xi_filt = np.empty(T)
    tau0 = np.empty(T)
    tau1 = np.empty(T)
    g = np.empty(T)
    h_comb = np.empty(T)

    denom = 2.0 - p00 - p11
    if abs(denom) < 1e-10:
        pi0 = 0.5
    else:
        pi0 = (1.0 - p11) / denom
    pi0 = max(min(pi0, 0.99), 0.01)

    # Initial tau
    tau0[0] = max(theta0_0 + theta1_0 * vix2[0], 1e-16)
    tau1[0] = max(theta0_1 + theta1_1 * vix2[0], 1e-16)
    g[0] = 1.0  # E(g) initialization
    xi_filt[0] = pi0
    tau_comb = pi0 * tau0[0] + (1.0 - pi0) * tau1[0]
    h_comb[0] = tau_comb * g[0]

    log_lik = 0.0

    for t in range(1, T):
        # Prediction step
        xi_pred_0 = p00 * xi_filt[t-1] + (1.0 - p11) * (1.0 - xi_filt[t-1])
        xi_pred_0 = max(min(xi_pred_0, 1.0 - 1e-8), 1e-8)
        xi_pred_1 = 1.0 - xi_pred_0

        # Regime-specific tau (lagged VIX, no lookahead)
        tau0[t] = max(theta0_0 + theta1_0 * vix2[t-1], 1e-16)
        tau1[t] = max(theta0_1 + theta1_1 * vix2[t-1], 1e-16)

        # Weighted tau for g-recursion normalization
        tau_w = xi_filt[t-1] * tau0[t] + (1.0 - xi_filt[t-1]) * tau1[t]
        if tau_w < 1e-16:
            tau_w = 1e-16

        # g recursion (shared across regimes, normalized by weighted tau)
        u_prev = returns[t-1] / np.sqrt(tau_w)
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16

        # Regime-specific conditional variance
        h0_t = tau0[t] * g[t]
        h1_t = tau1[t] * g[t]
        if h0_t < 1e-16:
            h0_t = 1e-16
        if h1_t < 1e-16:
            h1_t = 1e-16

        # Normal density
        r_t = returns[t]
        f0 = (1.0 / np.sqrt(2.0 * np.pi * h0_t)) * np.exp(-0.5 * r_t**2 / h0_t)
        f1 = (1.0 / np.sqrt(2.0 * np.pi * h1_t)) * np.exp(-0.5 * r_t**2 / h1_t)
        f_total = xi_pred_0 * f0 + xi_pred_1 * f1
        if f_total < 1e-300:
            f_total = 1e-300

        log_lik += np.log(f_total)

        # Update step
        xi_filt[t] = xi_pred_0 * f0 / f_total
        xi_filt[t] = max(min(xi_filt[t], 1.0 - 1e-8), 1e-8)

        # Combined h
        h_comb[t] = xi_filt[t] * h0_t + (1.0 - xi_filt[t]) * h1_t

    return log_lik, xi_filt, tau0, tau1, g, h_comb


def fit_ms_a4f(returns, vix2, n_starts=8):
    """
    Fit MS(2)-A4f with shared g-dynamics and regime-specific tau.
    Unconstrained parameterization with sigmoid transforms.
    """
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    v2 = np.ascontiguousarray(vix2, dtype=np.float64)
    var0 = np.var(ret)
    vix2_mean = np.mean(v2) + 1e-10

    def inv_sig(y, upper=1.0):
        y_c = max(min(y, upper * 0.999), upper * 0.001)
        return np.log(y_c / (upper - y_c))

    def neg_ll(x):
        # tau regime 0 (calm): theta0_0, theta1_0
        theta0_0 = x[0]  # can be negative (intercept)
        theta1_0 = np.exp(x[1])  # > 0 (VIX coefficient)
        # tau regime 1 (crisis): theta0_1, theta1_1
        theta0_1 = x[2]
        theta1_1 = np.exp(x[3])

        # Shared g dynamics
        omega = np.exp(x[4])
        alpha = 0.3 / (1.0 + np.exp(-x[5]))
        gamma_p = 0.5 / (1.0 + np.exp(-x[6]))
        beta = 0.999 / (1.0 + np.exp(-x[7]))

        # Transition probs
        p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01
        p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01

        # Stationarity
        if alpha + 0.5*gamma_p + beta >= 0.999:
            return 1e10

        ll, _, _, _, _, _ = ms_a4f_filter(
            theta0_0, theta1_0, theta0_1, theta1_1,
            omega, alpha, gamma_p, beta,
            p00, p11, ret, v2)
        return -ll if np.isfinite(ll) else 1e10

    rng = np.random.RandomState(42)
    best_val, best_x = 1e20, None

    # theta1 ratio: var0/vix2_mean gives reasonable scale
    t1_log = np.log(var0 / vix2_mean)

    base_starts = [
        # Calm regime: small theta0, moderate theta1; Crisis: larger theta0/theta1
        [var0*0.05, t1_log-0.5, var0*0.15, t1_log+0.5,
         np.log(var0*0.05), inv_sig(0.04, 0.3), inv_sig(0.08, 0.5), inv_sig(0.88, 0.999),
         inv_sig(0.96, 0.98), inv_sig(0.90, 0.98)],
        [var0*0.02, t1_log, var0*0.10, t1_log+1.0,
         np.log(var0*0.02), inv_sig(0.03, 0.3), inv_sig(0.06, 0.5), inv_sig(0.92, 0.999),
         inv_sig(0.97, 0.98), inv_sig(0.85, 0.98)],
        [0.0, t1_log+0.3, var0*0.20, t1_log+0.8,
         np.log(var0*0.08), inv_sig(0.05, 0.3), inv_sig(0.10, 0.5), inv_sig(0.85, 0.999),
         inv_sig(0.95, 0.98), inv_sig(0.92, 0.98)],
    ]

    all_starts = list(base_starts)
    for _ in range(n_starts - len(base_starts)):
        base = base_starts[rng.randint(len(base_starts))]
        perturbed = [b + rng.normal(0, 0.3) for b in base]
        all_starts.append(perturbed)

    for x0 in all_starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B',
                          options={'maxiter': 2000, 'ftol': 1e-10})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except:
            pass

    if best_x is None:
        return None

    x = best_x
    theta0_0 = x[0]
    theta1_0 = np.exp(x[1])
    theta0_1 = x[2]
    theta1_1 = np.exp(x[3])
    omega = np.exp(x[4])
    alpha = 0.3 / (1.0 + np.exp(-x[5]))
    gamma_p = 0.5 / (1.0 + np.exp(-x[6]))
    beta = 0.999 / (1.0 + np.exp(-x[7]))
    p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01
    p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01

    ll, xi_filt, tau0, tau1, g, h_comb = ms_a4f_filter(
        theta0_0, theta1_0, theta0_1, theta1_1,
        omega, alpha, gamma_p, beta,
        p00, p11, ret, v2)

    return {
        'regime0_tau': {'theta0': theta0_0, 'theta1': theta1_0},
        'regime1_tau': {'theta0': theta0_1, 'theta1': theta1_1},
        'shared_g': {'omega': omega, 'alpha': alpha, 'gamma': gamma_p, 'beta': beta,
                     'persistence': alpha + 0.5*gamma_p + beta},
        'p00': p00, 'p11': p11,
        'h_combined': h_comb, 'xi_filtered': xi_filt,
        'tau0': tau0, 'tau1': tau1, 'g': g,
        'converged': True, 'nll': best_val,
        'raw_x': best_x
    }


# ============================================================
# 7. Model M5: A4f + regime_prob (simplest combination)
# ============================================================
@njit
def a4f_rp_recursion(theta0, theta1, theta2, omega, alpha, gamma, beta,
                     returns, vix2, regime_prob):
    """A4f with regime probability: tau = theta0 + theta1*VIX² + theta2*P(crisis)."""
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)

    tau[0] = theta0 + theta1 * vix2[0] + theta2 * regime_prob[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2[t-1] + theta2 * regime_prob[t-1]
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


def fit_a4f_rp(returns, vix2, regime_prob):
    """Fit A4f + regime_prob with Normal innovations.
    Parameters: theta0, theta1, theta2, omega, alpha, gamma, beta (7 params)."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    v2 = np.ascontiguousarray(vix2, dtype=np.float64)
    rp = np.ascontiguousarray(regime_prob, dtype=np.float64)
    var0 = np.var(ret)

    bounds = [(-0.01, 0.01), (0.01, 5.0), (-0.01, 0.01),
              (1e-6, 1.0), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]

    def obj(p):
        if p[4] + 0.5*p[5] + p[6] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_rp_recursion(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                                        ret, v2, rp)
            T = len(ret)
            ll = 0.0
            for t in range(T):
                ll += np.log(h[t]) + ret[t]**2 / h[t]
            return 0.5 * ll if np.isfinite(ll) else 1e10
        except:
            return 1e10

    best_res, best_val = None, 1e20
    for t1 in [0.3, 0.8, 2.0]:
        for t2 in [1e-4, 5e-4, 1e-3]:
            x0 = [1e-5, t1, t2, 0.05, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                              options={'maxiter': 300})
                if res.fun < best_val:
                    best_val = res.fun
                    best_res = res
            except:
                continue

    if best_res is None:
        return None
    p = best_res.x
    h, tau, g = a4f_rp_recursion(p[0], p[1], p[2], p[3], p[4], p[5], p[6],
                                  ret, v2, rp)
    return {
        'params': p, 'h': h, 'tau': tau, 'g': g,
        'theta2_regime_prob': p[2],
        'persistence': p[4] + 0.5*p[5] + p[6],
        'converged': best_res.success, 'nll': best_val
    }


# ============================================================
# 8. Evaluation functions
# ============================================================
def qlike(r2, h):
    """QLIKE loss."""
    mask = ~np.isnan(h) & ~np.isnan(r2) & (h > 0) & (r2 >= 0)
    return np.mean(r2[mask] / h[mask] + np.log(h[mask]))


def qlike_series(r2, h):
    """QLIKE loss series for DM test."""
    mask = ~np.isnan(h) & ~np.isnan(r2) & (h > 0) & (r2 >= 0)
    loss = np.full(len(r2), np.nan)
    loss[mask] = r2[mask] / h[mask] + np.log(h[mask])
    return loss


def dm_test(loss1, loss2):
    """Diebold-Mariano test with HAC variance."""
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
    pi11 = n11 / (n10+n11) if (n10+n11) > 0 else 0
    pi = (n01+n11) / T
    if pi in (0,1) or pi01 in (0,1) or pi11 in (0,1):
        return 0, 1.0
    try:
        lr = 2 * (n00*np.log((1-pi01)/(1-pi)) + n01*np.log(pi01/pi)
                   + n10*np.log((1-pi11)/(1-pi)) + n11*np.log(pi11/pi))
    except:
        return 0, 1.0
    return lr, 1 - chi2.cdf(lr, 1)


def compute_var(sigma, alpha, df_val=None):
    """Compute VaR from sigma. Uses Normal if df_val is None, else Student-t."""
    if df_val is not None and not np.isnan(df_val) and df_val > 2:
        sf = np.sqrt((df_val - 2) / df_val)
        q = t_dist.ppf(alpha, df_val)
        return sigma * q * sf
    else:
        return sigma * norm.ppf(alpha)


def var_evaluation(returns_arr, sigma_arr, alpha, df_vals=None):
    """Full VaR evaluation: Kupiec + CC + Basel."""
    T = len(returns_arr)
    var_vals = np.full(T, np.nan)
    for i in range(T):
        s = sigma_arr[i]
        if np.isnan(s) or s <= 0:
            continue
        df_v = df_vals[i] if df_vals is not None and not np.isnan(df_vals[i]) else None
        var_vals[i] = compute_var(s, alpha, df_v)

    mask = ~np.isnan(var_vals)
    ret = returns_arr[mask]
    vv = var_vals[mask]
    violations = (ret < vv).astype(int)
    T_eff = len(ret)
    viol_rate = np.sum(violations) / T_eff

    uc_stat, uc_p = kupiec_test(violations, T_eff, alpha)
    cc_stat, cc_p = christoffersen_cc_test(violations)

    expected = T_eff * alpha
    if np.sum(violations) <= expected * 1.5:
        basel = "GREEN"
    elif np.sum(violations) <= expected * 2.0:
        basel = "YELLOW"
    else:
        basel = "RED"

    n_pass = sum([uc_p > 0.05, cc_p > 0.05, basel == "GREEN"])
    return {
        'alpha': alpha, 'T': T_eff,
        'violations': int(np.sum(violations)),
        'violation_rate': round(viol_rate * 100, 3),
        'expected_rate': round(alpha * 100, 2),
        'UC_p': round(uc_p, 4), 'CC_p': round(cc_p, 4),
        'Basel': basel, 'scorecard': f"{n_pass}/3"
    }


# ============================================================
# 9. OOS Rolling Forecast
# ============================================================
def oos_forecast_all(df, window=2000, refit_every=63):
    """Run OOS rolling forecast for all 5 models simultaneously."""
    # Determine OOS start: need VIX9D + enough window
    vix9d_valid = df['vix9d'].notna()
    vix9d_first_idx = np.where(vix9d_valid.values)[0][0]
    oos_start = max(window, vix9d_first_idx + 1)

    T = len(df)
    returns = df['ret'].values
    r2 = df['r2'].values
    vix9d2 = df['vix9d2'].values

    # Initialize forecast arrays
    h_gjr = np.full(T, np.nan)
    h_a4f = np.full(T, np.nan)
    h_ms_gjr = np.full(T, np.nan)
    h_ms_a4f = np.full(T, np.nan)
    h_a4f_rp = np.full(T, np.nan)
    df_gjr = np.full(T, np.nan)
    df_a4f = np.full(T, np.nan)
    xi_ms_gjr = np.full(T, np.nan)  # regime prob from MS-GJR (used for M5)
    xi_ms_a4f = np.full(T, np.nan)  # regime prob from MS-A4f

    last_fit_gjr = None
    last_fit_a4f = None
    last_fit_ms = None
    last_fit_ms_a4f = None
    last_fit_a4f_rp = None
    last_fit_idx = -refit_every

    # Tracking variables for 1-step-ahead recursions
    h_prev_gjr = np.nan
    g_prev_a4f = np.nan
    # For MS models, we use filter directly

    # We need to build regime_prob for M5. Strategy:
    # Use regime prob from MS-GJR (M3) — estimated from the training window at refit
    # For between-refit steps, propagate using transition matrix

    print(f"\n[OOS] Rolling forecast: oos_start={oos_start}, T={T}")
    print(f"  Window={window}, refit_every={refit_every}")
    print(f"  OOS range: index {oos_start} to {T-1} ({T - oos_start} days)")
    print(f"  OOS dates: {df.index[oos_start].date()} to {df.index[-1].date()}")

    refit_count = 0
    convergence_issues = {'gjr': 0, 'a4f': 0, 'ms_gjr': 0, 'ms_a4f': 0, 'a4f_rp': 0}

    for t in range(oos_start, T):
        need_refit = (t - last_fit_idx >= refit_every) or (last_fit_gjr is None)

        if need_refit:
            s = max(0, t - window)
            tr_ret = returns[s:t]
            tr_vix9d2 = vix9d2[s:t]

            if t % 500 == 0 or refit_count == 0:
                print(f"  Refit #{refit_count} at t={t} ({df.index[t].date()})...", end='')

            # M1: GJR-t
            last_fit_gjr = fit_gjr_t(tr_ret)
            if last_fit_gjr is None:
                convergence_issues['gjr'] += 1

            # M2: A4f-VIX9D-t
            last_fit_a4f = fit_a4f_t(tr_ret, tr_vix9d2)
            if last_fit_a4f is None:
                convergence_issues['a4f'] += 1

            # M3: MS(2)-GJR-N
            last_fit_ms = fit_ms_gjr(tr_ret, n_starts=5)
            if last_fit_ms is None:
                convergence_issues['ms_gjr'] += 1

            # M4: MS(2)-A4f
            last_fit_ms_a4f = fit_ms_a4f(tr_ret, tr_vix9d2, n_starts=5)
            if last_fit_ms_a4f is None:
                convergence_issues['ms_a4f'] += 1

            # M5: A4f + regime_prob (needs M3 regime probs)
            if last_fit_ms is not None:
                rp_train = 1.0 - last_fit_ms['xi_filtered']  # P(crisis)
                last_fit_a4f_rp = fit_a4f_rp(tr_ret, tr_vix9d2, rp_train)
                if last_fit_a4f_rp is None:
                    convergence_issues['a4f_rp'] += 1
            else:
                last_fit_a4f_rp = None
                convergence_issues['a4f_rp'] += 1

            last_fit_idx = t
            refit_count += 1

            # Reset tracking for recursions
            if last_fit_gjr is not None:
                h_prev_gjr = last_fit_gjr['h'][-1]
            if last_fit_a4f is not None:
                g_prev_a4f = last_fit_a4f['g'][-1]

            if t % 500 == 0 or refit_count == 1:
                print(" done")

        # ---- One-step-ahead forecasts ----

        # M1: GJR-t
        if last_fit_gjr is not None:
            p = last_fit_gjr['params']
            omega, alpha, gamma_p, beta = p[0], p[1], p[2], p[3]
            df_gjr[t] = p[4]
            r_prev = returns[t-1]
            r2p = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_t = omega + alpha * r2p + gamma_p * r2p * ind + beta * h_prev_gjr
            h_t = max(h_t, 1e-16)
            h_gjr[t] = h_t
            h_prev_gjr = h_t

        # M2: A4f-VIX9D-t
        if last_fit_a4f is not None:
            p = last_fit_a4f['params']
            theta0, theta1, omega, alpha, gamma_p, beta = p[0], p[1], p[2], p[3], p[4], p[5]
            df_a4f[t] = p[6]
            tau_t = max(theta0 + theta1 * vix9d2[t-1], 1e-16)
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t = omega + alpha * u2 + gamma_p * u2 * ind + beta * g_prev_a4f
            g_t = max(g_t, 1e-16)
            h_a4f[t] = tau_t * g_t
            g_prev_a4f = g_t

        # M3: MS(2)-GJR-N — run full filter on last window + 1 step
        if last_fit_ms is not None:
            s = max(0, t - window)
            sub_ret = returns[s:t+1]
            r0 = last_fit_ms['regime0']
            r1 = last_fit_ms['regime1']
            _, xi_f, _, _, h_c = ms_gjr_filter(
                r0['omega'], r0['alpha'], r0['gamma'], r0['beta'],
                r1['omega'], r1['alpha'], r1['gamma'], r1['beta'],
                last_fit_ms['p00'], last_fit_ms['p11'], sub_ret)
            h_ms_gjr[t] = h_c[-1]
            xi_ms_gjr[t] = 1.0 - xi_f[-1]  # P(crisis)

        # M4: MS(2)-A4f — run full filter on window + 1 step
        if last_fit_ms_a4f is not None:
            s = max(0, t - window)
            sub_ret = returns[s:t+1]
            sub_vix2 = vix9d2[s:t+1]
            rt0 = last_fit_ms_a4f['regime0_tau']
            rt1 = last_fit_ms_a4f['regime1_tau']
            sg = last_fit_ms_a4f['shared_g']
            _, xi_f, _, _, _, h_c = ms_a4f_filter(
                rt0['theta0'], rt0['theta1'], rt1['theta0'], rt1['theta1'],
                sg['omega'], sg['alpha'], sg['gamma'], sg['beta'],
                last_fit_ms_a4f['p00'], last_fit_ms_a4f['p11'],
                sub_ret, sub_vix2)
            h_ms_a4f[t] = h_c[-1]
            xi_ms_a4f[t] = 1.0 - xi_f[-1]  # P(crisis)

        # M5: A4f + regime_prob
        if last_fit_a4f_rp is not None and not np.isnan(xi_ms_gjr[t]):
            p = last_fit_a4f_rp['params']
            theta0, theta1, theta2, omega, alpha, gamma_p, beta = p
            # Use M3 regime prob (lagged, from previous step for OOS consistency)
            rp_t = xi_ms_gjr[t-1] if t > oos_start and not np.isnan(xi_ms_gjr[t-1]) else 0.5
            tau_t = max(theta0 + theta1 * vix9d2[t-1] + theta2 * rp_t, 1e-16)
            # We need g_prev for M5 — use a separate tracker
            if not hasattr(oos_forecast_all, '_g_prev_rp') or need_refit:
                oos_forecast_all._g_prev_rp = last_fit_a4f_rp['g'][-1]
            u_prev = returns[t-1] / np.sqrt(tau_t)
            u2 = u_prev ** 2
            ind = 1.0 if returns[t-1] < 0 else 0.0
            g_t_rp = omega + alpha * u2 + gamma_p * u2 * ind + beta * oos_forecast_all._g_prev_rp
            g_t_rp = max(g_t_rp, 1e-16)
            h_a4f_rp[t] = tau_t * g_t_rp
            oos_forecast_all._g_prev_rp = g_t_rp

    print(f"\n  Refit count: {refit_count}")
    print(f"  Convergence issues: {convergence_issues}")

    return {
        'oos_start': oos_start,
        'h_gjr': h_gjr, 'h_a4f': h_a4f, 'h_ms_gjr': h_ms_gjr,
        'h_ms_a4f': h_ms_a4f, 'h_a4f_rp': h_a4f_rp,
        'df_gjr': df_gjr, 'df_a4f': df_a4f,
        'xi_ms_gjr': xi_ms_gjr, 'xi_ms_a4f': xi_ms_a4f,
    }


# ============================================================
# 10. Main execution
# ============================================================
def main():
    df = load_data()

    # ---- Run OOS forecasts ----
    print("\n[2] Running OOS rolling forecasts...")
    forecasts = oos_forecast_all(df, window=2000, refit_every=63)

    oos_start = forecasts['oos_start']
    oos_mask = np.zeros(len(df), dtype=bool)
    oos_mask[oos_start:] = True
    oos_dates = df.index[oos_mask]

    returns_oos = df['ret'].values[oos_mask]
    r2_oos = df['r2'].values[oos_mask]
    vix_oos = df['vix'].values[oos_mask]

    # ---- QLIKE evaluation ----
    print("\n[3] QLIKE evaluation (on r², Patton 2011)...")
    models = {
        'M1: GJR-t': forecasts['h_gjr'],
        'M2: A4f-VIX9D-t': forecasts['h_a4f'],
        'M3: MS(2)-GJR-N': forecasts['h_ms_gjr'],
        'M4: MS(2)-A4f': forecasts['h_ms_a4f'],
        'M5: A4f+RegProb': forecasts['h_a4f_rp'],
    }

    qlike_results = {}
    for name, h_all in models.items():
        h_oos = h_all[oos_mask]
        valid = ~np.isnan(h_oos) & (h_oos > 0)
        q = qlike(r2_oos[valid], h_oos[valid]) if valid.sum() > 100 else np.nan
        n_valid = int(valid.sum())
        qlike_results[name] = {'qlike': round(q, 6) if np.isfinite(q) else None,
                               'n_valid': n_valid}
        status = f"QLIKE={q:.6f}" if np.isfinite(q) else "FAILED"
        print(f"  {name}: {status} (N={n_valid})")

    # ---- DM tests ----
    print("\n[4] Diebold-Mariano tests (Harvey t>3.0)...")

    # Build QLIKE loss series
    loss = {}
    for name, h_all in models.items():
        h_oos = h_all[oos_mask]
        loss[name] = qlike_series(r2_oos, h_oos)

    dm_pairs = [
        ('M4: MS(2)-A4f', 'M2: A4f-VIX9D-t'),
        ('M5: A4f+RegProb', 'M2: A4f-VIX9D-t'),
        ('M4: MS(2)-A4f', 'M3: MS(2)-GJR-N'),
        ('M4: MS(2)-A4f', 'M1: GJR-t'),
        ('M2: A4f-VIX9D-t', 'M1: GJR-t'),
        ('M3: MS(2)-GJR-N', 'M1: GJR-t'),
        ('M5: A4f+RegProb', 'M1: GJR-t'),
        ('M5: A4f+RegProb', 'M3: MS(2)-GJR-N'),
    ]

    dm_results = {}
    for m1, m2 in dm_pairs:
        if loss[m1] is not None and loss[m2] is not None:
            t_stat, p_val = dm_test(loss[m1], loss[m2])
            sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.5 else "NS")
            dm_results[f"{m1} vs {m2}"] = {
                't_stat': round(t_stat, 3), 'p_val': round(p_val, 4), 'significance': sig
            }
            print(f"  {m1} vs {m2}: t={t_stat:.3f}, p={p_val:.4f} {sig}")

    # ---- VaR 2.5% evaluation ----
    print("\n[5] VaR 2.5% evaluation...")
    var_results = {}

    for name, h_all in models.items():
        h_oos = h_all[oos_mask]
        sigma_oos = np.sqrt(np.maximum(h_oos, 0))

        # Choose df: GJR-t and A4f-t use Student-t, others Normal
        if 'GJR-t' in name:
            df_vals = forecasts['df_gjr'][oos_mask]
        elif 'A4f-VIX9D-t' in name or 'A4f+RegProb' in name:
            df_vals = forecasts['df_a4f'][oos_mask]
        else:
            df_vals = None

        try:
            vr = var_evaluation(returns_oos, sigma_oos, 0.025, df_vals)
            var_results[name] = vr
            print(f"  {name}: viol={vr['violations']}/{vr['T']} "
                  f"({vr['violation_rate']:.2f}%), UC_p={vr['UC_p']:.3f}, "
                  f"CC_p={vr['CC_p']:.3f}, Basel={vr['Basel']}, Score={vr['scorecard']}")
        except Exception as e:
            print(f"  {name}: VaR FAILED ({e})")
            var_results[name] = {'error': str(e)}

    # ---- Regime analysis ----
    print("\n[6] Regime analysis...")
    xi_ms_gjr_oos = forecasts['xi_ms_gjr'][oos_mask]
    xi_ms_a4f_oos = forecasts['xi_ms_a4f'][oos_mask]

    valid_both = ~np.isnan(xi_ms_gjr_oos) & ~np.isnan(xi_ms_a4f_oos)
    if valid_both.sum() > 100:
        regime_corr = np.corrcoef(xi_ms_gjr_oos[valid_both],
                                   xi_ms_a4f_oos[valid_both])[0, 1]
        print(f"  Regime prob correlation (MS-GJR vs MS-A4f): r={regime_corr:.4f}")
    else:
        regime_corr = np.nan

    # VIX vs regime prob correlation
    valid_vix_reg = ~np.isnan(xi_ms_a4f_oos) & ~np.isnan(vix_oos)
    if valid_vix_reg.sum() > 100:
        vix_regime_corr = np.corrcoef(vix_oos[valid_vix_reg],
                                       xi_ms_a4f_oos[valid_vix_reg])[0, 1]
        print(f"  VIX vs MS-A4f regime prob: r={vix_regime_corr:.4f}")
    else:
        vix_regime_corr = np.nan

    # ---- Charts ----
    print("\n[7] Generating charts...")

    # Chart 1: QLIKE comparison bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    model_names = []
    qlike_vals = []
    colors = ['#4c72b0', '#dd8452', '#55a868', '#c44e52', '#8172b2']
    for i, (name, qr) in enumerate(qlike_results.items()):
        if qr['qlike'] is not None:
            model_names.append(name.replace('M1: ', '').replace('M2: ', '').replace(
                'M3: ', '').replace('M4: ', '').replace('M5: ', ''))
            qlike_vals.append(qr['qlike'])

    if qlike_vals:
        bars = ax.bar(range(len(model_names)), qlike_vals,
                      color=colors[:len(model_names)], edgecolor='black', linewidth=0.5)
        ax.set_xticks(range(len(model_names)))
        ax.set_xticklabels(model_names, rotation=30, ha='right', fontsize=10)
        ax.set_ylabel('QLIKE (lower = better)', fontsize=12)
        ax.set_title('K1020: QLIKE Comparison — MS(2)-A4f vs Baselines\n'
                     f'OOS: {oos_dates[0].date()} to {oos_dates[-1].date()}',
                     fontsize=13, fontweight='bold')

        # Add value labels
        for bar, val in zip(bars, qlike_vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                   f'{val:.4f}', ha='center', va='bottom', fontsize=9)

        # Highlight best
        best_idx = np.argmin(qlike_vals)
        bars[best_idx].set_edgecolor('gold')
        bars[best_idx].set_linewidth(3)

        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        fig.savefig(os.path.join(SCRIPT_DIR, 'k1020_qlike_comparison.png'), dpi=150)
    plt.close()

    # Chart 2: Regime probability comparison + tau ratio
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # Panel A: MS-GJR regime prob
    valid_gjr = ~np.isnan(xi_ms_gjr_oos)
    if valid_gjr.sum() > 0:
        axes[0].fill_between(oos_dates[valid_gjr], 0,
                            xi_ms_gjr_oos[valid_gjr], alpha=0.6, color='#c44e52',
                            label='P(crisis) MS-GJR')
        axes[0].set_ylabel('P(crisis)', fontsize=11)
        axes[0].set_title('MS(2)-GJR Regime Probability', fontsize=12)
        axes[0].legend(loc='upper left')
        axes[0].set_ylim(0, 1)
        axes[0].grid(alpha=0.3)

    # Panel B: MS-A4f regime prob
    valid_a4f = ~np.isnan(xi_ms_a4f_oos)
    if valid_a4f.sum() > 0:
        axes[1].fill_between(oos_dates[valid_a4f], 0,
                            xi_ms_a4f_oos[valid_a4f], alpha=0.6, color='#8172b2',
                            label='P(crisis) MS-A4f')
        axes[1].set_ylabel('P(crisis)', fontsize=11)
        axes[1].set_title('MS(2)-A4f Regime Probability', fontsize=12)
        axes[1].legend(loc='upper left')
        axes[1].set_ylim(0, 1)
        axes[1].grid(alpha=0.3)

    # Panel C: VIX overlay
    ax_vix = axes[2]
    ax_vix.plot(oos_dates, vix_oos, color='#dd8452', alpha=0.8, linewidth=0.8, label='VIX')
    ax_vix.axhline(20, color='gray', linestyle='--', alpha=0.5, label='VIX=20')
    ax_vix.axhline(30, color='red', linestyle='--', alpha=0.5, label='VIX=30')
    ax_vix.set_ylabel('VIX', fontsize=11)
    ax_vix.set_title('VIX Level', fontsize=12)
    ax_vix.legend(loc='upper left')
    ax_vix.grid(alpha=0.3)
    ax_vix.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax_vix.xaxis.set_major_locator(mdates.YearLocator())
    plt.xticks(rotation=45)

    fig.suptitle(f'K1020: Regime Probabilities — MS-GJR vs MS-A4f\n'
                 f'Regime correlation: r={regime_corr:.3f}',
                 fontsize=14, fontweight='bold', y=1.01)
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, 'k1020_regime_comparison.png'),
                dpi=150, bbox_inches='tight')
    plt.close()

    # ---- Collect results ----
    elapsed = time.time() - START_TIME

    results = {
        'experiment_id': 'K1020',
        'title': 'MS(2)-A4f: Markov Regime Switching + VIX Multiplicative GARCH-X',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance (SPY, ^VIX, ^VIX9D)',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_period': f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
        'oos_n': int(oos_mask.sum()),
        'window': 2000,
        'refit_every': 63,
        'seed': 42,
        'models': {
            'M1_GJR_t': 'GJR-GARCH(1,1) with Student-t (5 params)',
            'M2_A4f_VIX9D_t': 'Multiplicative A4f with VIX9D, Student-t (7 params)',
            'M3_MS2_GJR_N': 'MS(2)-GJR with Normal, Hamilton filter (10 params)',
            'M4_MS2_A4f': 'MS(2)-A4f: regime-specific tau, shared g, Normal (10 params)',
            'M5_A4f_RegProb': 'A4f + regime probability as extra regressor (7 params)',
        },
        'qlike_results': qlike_results,
        'dm_tests': dm_results,
        'var_2_5_pct': var_results,
        'regime_analysis': {
            'regime_corr_ms_gjr_vs_ms_a4f': round(regime_corr, 4) if np.isfinite(regime_corr) else None,
            'vix_vs_ms_a4f_regime_corr': round(vix_regime_corr, 4) if np.isfinite(vix_regime_corr) else None,
        },
        'runtime_seconds': round(elapsed, 1),
        'references': [
            'Hamilton (1989) Econometrica 57(2)',
            'Gray (1996) JFE 42(1)',
            'Klaassen (2002) Empirical Economics 27(2)',
            'Engle & Rangel (2008) RFS 21(3)',
            'Patton (2011) J Econometrics 160(1)',
            'Harvey et al. (2016) t>3.0',
            'Kupiec (1995), Christoffersen (1998)',
        ],
    }

    # ---- Save results ----
    results_path = os.path.join(SCRIPT_DIR, 'k1020_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[8] Results saved to {results_path}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("\nQLIKE ranking (lower = better):")
    sorted_q = sorted(
        [(n, r['qlike']) for n, r in qlike_results.items() if r['qlike'] is not None],
        key=lambda x: x[1]
    )
    for rank, (name, q) in enumerate(sorted_q, 1):
        print(f"  #{rank} {name}: {q:.6f}")

    print("\nKey DM tests:")
    for pair, dr in dm_results.items():
        print(f"  {pair}: t={dr['t_stat']:.3f} {dr['significance']}")

    print(f"\nRuntime: {elapsed:.1f}s")
    print("Done.")

    return results


if __name__ == '__main__':
    results = main()
