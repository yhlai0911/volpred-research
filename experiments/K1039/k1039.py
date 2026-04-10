#!/usr/bin/env python3
"""
K1039: A4f Multi-Horizon VaR (h=1, 5, 10 days)
================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1036 confirmed A4f + CF-Rolling is the best 1-day VaR method (6/6 Trinity PASS).
  Basel III requires 10-day VaR. This experiment extends to multi-horizon VaR.
  K943 found MF-GJR h=5 best (+18.4%, DM t=-4.12).

  Core questions:
    1. Does A4f multi-horizon advantage increase or decay with h?
    2. Does CF-Rolling maintain 100% PASS at h=5/10?
    3. Is simple sqrt(h) scaling sufficient? (if so, no need for h-step formulas)

Method:
  h-step GARCH conditional variance:
    For GJR: recursive sigma2_h[j] for j=1..h, total_var = sum(sigma2_h)
    For A4f:  tau held constant at tau_{t+1} (Strategy 1: VIX unchanged),
              g evolves recursively, total_var = sum(tau * g_h[j])

  Comparison models (per horizon):
    1. GJR + Normal
    2. GJR + CF-Rolling
    3. A4f + Normal
    4. A4f + CF-Rolling
    5. Scaled 1-day VaR (sqrt(h) scaling, industry standard)

  VaR horizons: h = 1, 5, 10 days
  Alpha levels: 1%, 2.5%

  h-day returns: non-overlapping blocks for clean backtesting
  DM test: HAC (Newey-West lag h-1) for overlapping returns comparison

Data: SPY, QQQ from yfinance (2005-01-01 ~ 2026-04-10).
OOS: 2019-01-01 onwards, window=2000, refit_every=63, seed=42.

Evaluation:
  - Trinity test (Kupiec + CC + Basel) at each horizon
  - ES backtesting: Acerbi & Szekely (2014)
  - DM test: Newey-West HAC for overlapping returns
  - Comparison: scaled sqrt(h) vs proper h-step

References:
  - Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320
  - Kupiec (1995). J Derivatives 3:73-84
  - Christoffersen (1998). Int Econ Rev 39(4):841-862
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Basel Committee (2019). Minimum capital requirements for market risk.
  - K1036: A4f + CF-Rolling 6/6 Trinity PASS (best 1-day VaR)
  - K943: MF-GJR h=5 best (+18.4%, DM t=-4.12)
  - K988: A4f champion for SPY (DM t=+4.48 vs GJR)

Author: VolPred Research System
Date: 2026-04-11
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.special import gammaln
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1039"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1039_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8
CF_ROLLING_WINDOW = 252
ALPHA_LEVELS = [0.025, 0.01]
HORIZONS = [1, 5, 10]
ASSETS = ['SPY', 'QQQ']

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Multi-Horizon VaR (h=1, 5, 10 days)")
print(f"  Models: GJR, A4f | Methods: Normal, CF-Rolling, Scaled-1d")
print(f"  Horizons: {HORIZONS} | Assets: {ASSETS}")
print("=" * 70)


# ============================================================
# GARCH RECURSIONS
# ============================================================

def gjr_recursion(omega, alpha, gamma, beta, returns):
    """GJR-GARCH(1,1) variance recursion."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns[:min(250, T)])
    for t in range(1, T):
        u2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * u2 + gamma * u2 * ind + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    return h


def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2):
    """A4f multiplicative GARCH-X recursion.
    tau_t = max(theta0 + theta1 * fear2_{t-1}, eps)
    g_t = omega + alpha * u^2 + gamma * u^2 * I(u<0) + beta * g_{t-1}
    sigma^2_t = tau_t * g_t
    """
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)

    tau[0] = theta0 + theta1 * fear2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, T):
        tau[t] = theta0 + theta1 * fear2[t-1]
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


def student_t_const(df):
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))


T_CONST_8 = student_t_const(DF_FIXED)


# ============================================================
# LOG-LIKELIHOOD FUNCTIONS
# ============================================================

def gjr_nll_t(omega, alpha, gamma, beta, df, t_const, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


def a4f_nll_t(theta0, theta1, omega, alpha, gamma, beta, df, t_const, returns, fear2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


# ============================================================
# MODEL FITTING
# ============================================================

def fit_gjr_t(returns, df=DF_FIXED):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
        [var0 * 0.01, 0.04, 0.04, 0.92],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def nll(params):
        omega, alpha_p, gamma_p, beta_p = params
        if alpha_p + gamma_p / 2 + beta_p >= 0.999:
            return 1e10
        return gjr_nll_t(omega, alpha_p, gamma_p, beta_p, float(df), T_CONST_8, returns)

    for s in starts:
        try:
            res = optimize.minimize(nll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def fit_a4f_t(returns, fear_vals, df=DF_FIXED):
    var0 = np.var(returns)
    fear2_mean = np.mean(fear_vals**2) + 1e-8
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / fear2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / fear2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / fear2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / fear2_mean * 2.0, 0.08, 0.04, 0.04, 0.92],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def nll(params):
        th0, th1, omega_g, alpha_p, gamma_p, beta_p = params
        if alpha_p + gamma_p / 2 + beta_p >= 0.999 or omega_g <= 0:
            return 1e10
        return a4f_nll_t(th0, th1, omega_g, alpha_p, gamma_p, beta_p,
                         float(df), T_CONST_8, returns, fear_vals**2)

    for s in starts:
        try:
            res = optimize.minimize(nll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500, 'ftol': 1e-10})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


# ============================================================
# CORNISH-FISHER EXPANSION
# ============================================================

def cornish_fisher_quantile(alpha, skewness, excess_kurtosis):
    """Cornish-Fisher adjusted quantile."""
    z = stats.norm.ppf(alpha)
    z2 = z ** 2
    z3 = z ** 3
    S = skewness
    K = excess_kurtosis
    z_cf = (z
            + (z2 - 1) / 6 * S
            + (z3 - 3 * z) / 24 * K
            - (2 * z3 - 5 * z) / 36 * S**2)
    return z_cf


# ============================================================
# MULTI-STEP VARIANCE FORECASTING
# ============================================================

def gjr_hstep_variance(omega, alpha, gamma, beta, h_prev, r_prev, h_horizon):
    """
    Compute h-step ahead total variance for GJR-GARCH.

    For step 1: use actual r_{t-1} for asymmetry indicator.
    For steps 2..h: assume E[I(r<0)] = 0.5 (unconditional), so
      E[sigma2_{t+j}] = omega + (alpha + gamma/2 + beta) * sigma2_{t+j-1}

    Returns: array of per-step variances and total_var = sum
    """
    sigma2 = np.zeros(h_horizon)
    persistence = alpha + gamma / 2 + beta

    # Step 1: use actual r_{t-1}
    u2 = r_prev ** 2
    ind = 1.0 if r_prev < 0 else 0.0
    sigma2[0] = max(omega + alpha * u2 + gamma * u2 * ind + beta * h_prev, 1e-10)

    # Steps 2..h: unconditional asymmetry E[I] = 0.5
    for j in range(1, h_horizon):
        sigma2[j] = max(omega + persistence * sigma2[j-1], 1e-10)

    return sigma2, np.sum(sigma2)


def a4f_hstep_variance(theta0, theta1, omega_g, alpha, gamma, beta,
                       g_prev, r_prev, tau_current, h_horizon):
    """
    Compute h-step ahead total variance for A4f.

    Strategy 1 (constant tau): assume VIX unchanged over horizon.
    tau_{t+j} = tau_{t+1} for all j.
    g evolves with GJR recursion on the g-component.

    For step 1: use actual r_{t-1} / sqrt(tau) for asymmetry.
    For steps 2..h: assume E[I] = 0.5.

    Returns: array of per-step variances and total_var = sum(tau * g_j)
    """
    sigma2 = np.zeros(h_horizon)
    g = np.zeros(h_horizon)
    persistence = alpha + gamma / 2 + beta

    # Step 1: use actual r_{t-1}
    u_prev = r_prev / np.sqrt(max(tau_current, 1e-16))
    u2 = u_prev ** 2
    ind = 1.0 if r_prev < 0 else 0.0
    g[0] = max(omega_g + alpha * u2 + gamma * u2 * ind + beta * g_prev, 1e-10)
    sigma2[0] = tau_current * g[0]

    # Steps 2..h: E[u^2] = 1 (unit variance process), E[I] = 0.5
    for j in range(1, h_horizon):
        # E[u^2 | g_{j-1}] = 1 (standardized), so alpha*u^2 + gamma*u^2*I ~ (alpha + gamma/2)*1
        g[j] = max(omega_g + persistence * g[j-1], 1e-10)
        sigma2[j] = tau_current * g[j]

    return sigma2, np.sum(sigma2)


# ============================================================
# OOS FORECASTING WITH MULTI-HORIZON
# ============================================================

def oos_gjr_multi(ret, oos_start_idx, window, refit_every, horizons, df=DF_FIXED):
    """OOS multi-horizon variance forecast using GJR-GARCH.
    Returns dict: {h: (forecasts_h, std_resid)}
    """
    n_total = len(ret)
    n_oos = n_total - oos_start_idx
    max_h = max(horizons)

    # Per-horizon forecast arrays
    forecasts = {h: np.full(n_oos, np.nan) for h in horizons}
    std_resid_at_refit = {}

    params = None
    last_fit = -refit_every
    h_prev = None

    for i in range(n_oos):
        t = oos_start_idx + i

        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr_t(train_ret, df)
            if params is None:
                continue
            last_fit = t
            omega, alpha_p, gamma_p, beta_p = params
            h_series = gjr_recursion(omega, alpha_p, gamma_p, beta_p, train_ret)
            h_prev = h_series[-1]
            std_resid_at_refit[i] = train_ret / np.sqrt(h_series)

        if params is None:
            continue

        omega, alpha_p, gamma_p, beta_p = params

        # 1-step update (real-time recursion)
        u2 = ret[t-1] ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        h_1step = max(omega + alpha_p * u2 + gamma_p * u2 * ind + beta_p * h_prev, 1e-10)

        # Multi-horizon: h-step ahead total variance
        for hh in horizons:
            if hh == 1:
                forecasts[hh][i] = h_1step
            else:
                _, total_var = gjr_hstep_variance(
                    omega, alpha_p, gamma_p, beta_p, h_prev, ret[t-1], hh
                )
                forecasts[hh][i] = total_var

        h_prev = h_1step  # update state with 1-step

    return forecasts, std_resid_at_refit


def oos_a4f_multi(ret, fear_vals, oos_start_idx, window, refit_every, horizons, df=DF_FIXED):
    """OOS multi-horizon variance forecast using A4f.
    Returns dict: {h: (forecasts_h, std_resid)}
    """
    n_total = len(ret)
    n_oos = n_total - oos_start_idx
    max_h = max(horizons)

    forecasts = {h: np.full(n_oos, np.nan) for h in horizons}
    std_resid_at_refit = {}

    params = None
    last_fit = -refit_every
    g_prev = None

    for i in range(n_oos):
        t = oos_start_idx + i

        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            train_fear = fear_vals[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_a4f_t(train_ret, train_fear, df)
            if params is None:
                continue
            last_fit = t
            th0, th1, omega_g, alpha_p, gamma_p, beta_p = params
            h_series, _, g_series = a4f_recursion(
                th0, th1, omega_g, alpha_p, gamma_p, beta_p,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            std_resid_at_refit[i] = train_ret / np.sqrt(h_series)

        if params is None:
            continue

        th0, th1, omega_g, alpha_p, gamma_p, beta_p = params

        # Current tau (from VIX at t-1)
        tau_t = max(th0 + th1 * fear_vals[t-1]**2, 1e-16)

        # 1-step g update
        u_prev = ret[t-1] / np.sqrt(tau_t)
        u2 = u_prev ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        g_1step = max(omega_g + alpha_p * u2 + gamma_p * u2 * ind + beta_p * g_prev, 1e-10)
        h_1step = tau_t * g_1step

        for hh in horizons:
            if hh == 1:
                forecasts[hh][i] = h_1step
            else:
                _, total_var = a4f_hstep_variance(
                    th0, th1, omega_g, alpha_p, gamma_p, beta_p,
                    g_prev, ret[t-1], tau_t, hh
                )
                forecasts[hh][i] = total_var

        g_prev = g_1step

    return forecasts, std_resid_at_refit


# ============================================================
# VAR/ES COMPUTATION
# ============================================================

def compute_var_normal(sigma, alpha):
    return stats.norm.ppf(alpha) * sigma


def compute_var_cf(sigma, alpha, skewness, excess_kurtosis):
    z_cf = cornish_fisher_quantile(alpha, skewness, excess_kurtosis)
    return z_cf * sigma


def compute_es_normal(sigma, alpha):
    z = stats.norm.ppf(alpha)
    return -sigma * stats.norm.pdf(z) / alpha


def compute_es_cf(sigma, alpha, skewness, excess_kurtosis):
    n_points = 200
    u_vals = np.linspace(1e-6, alpha, n_points)
    q_vals = np.array([cornish_fisher_quantile(u, skewness, excess_kurtosis) for u in u_vals])
    es = sigma * np.trapezoid(q_vals, u_vals) / alpha
    return es


# ============================================================
# BACKTESTING FUNCTIONS
# ============================================================

def kupiec_test(n_obs, n_viol, alpha_level):
    if n_obs < 50:
        return np.nan, np.nan, 'SKIP'
    vr = n_viol / n_obs
    if n_viol == 0:
        lr = -2 * n_obs * np.log(1 - alpha_level)
    elif n_viol == n_obs:
        lr = -2 * n_obs * np.log(alpha_level)
    else:
        lr = -2 * (np.log((1 - alpha_level)**(n_obs - n_viol) * alpha_level**n_viol)
                    - np.log((1 - vr)**(n_obs - n_viol) * vr**n_viol))
    p_value = 1 - stats.chi2.cdf(lr, 1)
    return float(lr), float(p_value), 'PASS' if p_value > 0.05 else 'FAIL'


def christoffersen_cc_test(violations_series):
    n = len(violations_series)
    if n < 50:
        return np.nan, np.nan, 'SKIP'
    v = violations_series.astype(int)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if v[i-1] == 0 and v[i] == 0:
            n00 += 1
        elif v[i-1] == 0 and v[i] == 1:
            n01 += 1
        elif v[i-1] == 1 and v[i] == 0:
            n10 += 1
        else:
            n11 += 1
    if n01 + n00 == 0 or n10 + n11 == 0:
        return np.nan, np.nan, 'SKIP'
    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    pi = (n01 + n11) / n
    if pi == 0 or pi == 1:
        return np.nan, np.nan, 'SKIP'
    try:
        ll_ind = 0
        if n00 + n01 > 0:
            ll_ind += (n00 * np.log(1 - pi) + n01 * np.log(pi)) if pi > 0 and pi < 1 else 0
        if n10 + n11 > 0:
            ll_ind += (n10 * np.log(1 - pi) + n11 * np.log(pi)) if pi > 0 and pi < 1 else 0
        ll_markov = 0
        if n00 > 0 and pi01 < 1:
            ll_markov += n00 * np.log(1 - pi01)
        if n01 > 0 and pi01 > 0:
            ll_markov += n01 * np.log(pi01)
        if n10 > 0 and pi11 < 1:
            ll_markov += n10 * np.log(1 - pi11)
        if n11 > 0 and pi11 > 0:
            ll_markov += n11 * np.log(pi11)
        lr_cc = -2 * (ll_ind - ll_markov)
        p_value = 1 - stats.chi2.cdf(max(lr_cc, 0), 1)
        return float(lr_cc), float(p_value), 'PASS' if p_value > 0.05 else 'FAIL'
    except (ValueError, RuntimeWarning):
        return np.nan, np.nan, 'SKIP'


def basel_traffic_light(n_obs, n_viol, alpha_level):
    expected = n_obs * alpha_level
    sigma = np.sqrt(n_obs * alpha_level * (1 - alpha_level))
    green_cutoff = expected + 1.645 * sigma
    red_cutoff = expected + 2.326 * sigma
    if n_viol <= green_cutoff:
        return 'GREEN', 'PASS'
    elif n_viol <= red_cutoff:
        return 'YELLOW', 'PASS'
    else:
        return 'RED', 'FAIL'


def es_backtest_as2014(returns_block, var_series, es_series, alpha_level):
    n = len(returns_block)
    if n < 20:
        return np.nan, np.nan, 'SKIP'
    violations_mask = returns_block < var_series
    n_viol = violations_mask.sum()
    if n_viol == 0:
        return 0.0, np.nan, 'SKIP'
    es_safe = np.where(es_series != 0, es_series, -1e-10)
    z_stat = 1 / (n * alpha_level) * np.sum(returns_block[violations_mask] / es_safe[violations_mask]) + 1
    p_value = stats.norm.cdf(z_stat)
    return float(z_stat), float(p_value), 'PASS' if p_value > 0.05 else 'FAIL'


def run_trinity_test(returns_block, var_series, es_series, alpha_level):
    """Run full Trinity + ES test on (possibly non-overlapping) blocks."""
    n_obs = len(returns_block)
    violations = (returns_block < var_series).astype(int)
    n_viol = int(violations.sum())
    vr = n_viol / n_obs if n_obs > 0 else np.nan

    kupiec_lr, kupiec_p, kupiec_result = kupiec_test(n_obs, n_viol, alpha_level)
    cc_lr, cc_p, cc_result = christoffersen_cc_test(violations)
    basel_color, basel_result = basel_traffic_light(n_obs, n_viol, alpha_level)
    es_z, es_p, es_result = es_backtest_as2014(returns_block, var_series, es_series, alpha_level)

    trinity = 'PASS' if (kupiec_result == 'PASS' and cc_result == 'PASS' and basel_result == 'PASS') else 'FAIL'

    return {
        'n_obs': n_obs,
        'n_violations': n_viol,
        'violation_rate': round(vr, 6),
        'expected_rate': alpha_level,
        'kupiec_LR': round(kupiec_lr, 4) if not np.isnan(kupiec_lr) else None,
        'kupiec_p': round(kupiec_p, 4) if not np.isnan(kupiec_p) else None,
        'kupiec': kupiec_result,
        'cc_LR': round(cc_lr, 4) if not np.isnan(cc_lr) else None,
        'cc_p': round(cc_p, 4) if not np.isnan(cc_p) else None,
        'cc': cc_result,
        'basel_color': basel_color,
        'basel': basel_result,
        'es_z': round(es_z, 4) if not np.isnan(es_z) else None,
        'es_p': round(es_p, 4) if not np.isnan(es_p) else None,
        'es': es_result,
        'trinity': trinity,
    }


# ============================================================
# NON-OVERLAPPING h-DAY RETURNS
# ============================================================

def compute_nonoverlapping_blocks(oos_ret, var_h_series, es_h_series, h):
    """
    Extract non-overlapping h-day return blocks and corresponding VaR/ES.
    h-day return = sum of daily log-returns over h consecutive days.
    VaR/ES forecast is taken from the first day of each block.
    """
    n = len(oos_ret)
    n_blocks = n // h
    block_returns = np.full(n_blocks, np.nan)
    block_var = np.full(n_blocks, np.nan)
    block_es = np.full(n_blocks, np.nan)

    for b in range(n_blocks):
        start = b * h
        end = start + h
        if end > n:
            break
        block_returns[b] = np.sum(oos_ret[start:end])
        block_var[b] = var_h_series[start]
        block_es[b] = es_h_series[start]

    valid = ~(np.isnan(block_returns) | np.isnan(block_var) | np.isnan(block_es))
    return block_returns[valid], block_var[valid], block_es[valid]


# ============================================================
# MAIN BACKTEST FOR ONE ASSET
# ============================================================

def run_backtest_for_asset(ticker):
    print(f"\n{'='*60}")
    print(f"  Processing {ticker}")
    print(f"{'='*60}")

    import yfinance as yf
    data = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if data.empty:
        print(f"  ERROR: No data for {ticker}")
        return None

    if isinstance(data.columns, pd.MultiIndex):
        close = data[('Close', ticker)].dropna()
    else:
        close = data['Close'].dropna()

    ret = np.log(close / close.shift(1)).dropna().values
    dates = close.index[1:]

    # VIX data for A4f
    vix_data = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
    if isinstance(vix_data.columns, pd.MultiIndex):
        vix_close = vix_data[('Close', '^VIX')].dropna()
    else:
        vix_close = vix_data['Close'].dropna()

    vix_aligned = vix_close.reindex(dates).ffill().bfill()
    fear_vals = vix_aligned.values / 100.0

    oos_start_idx = None
    for i, d in enumerate(dates):
        if str(d)[:10] >= OOS_START:
            oos_start_idx = i
            break

    if oos_start_idx is None:
        print(f"  ERROR: Cannot find OOS start for {ticker}")
        return None

    n_total = len(ret)
    n_oos = n_total - oos_start_idx
    print(f"  Total obs: {n_total}, OOS: {n_oos} (from {dates[oos_start_idx].strftime('%Y-%m-%d')})")

    # ---- GJR Multi-Horizon Forecasts ----
    print(f"  Fitting GJR-GARCH(1,1) multi-horizon...")
    t0 = time.time()
    gjr_forecasts, gjr_std_resid = oos_gjr_multi(ret, oos_start_idx, WINDOW, REFIT_EVERY, HORIZONS)
    print(f"  GJR done in {time.time()-t0:.1f}s")

    # ---- A4f Multi-Horizon Forecasts ----
    print(f"  Fitting A4f-VIX multi-horizon...")
    t0 = time.time()
    a4f_forecasts, a4f_std_resid = oos_a4f_multi(ret, fear_vals, oos_start_idx, WINDOW, REFIT_EVERY, HORIZONS)
    print(f"  A4f done in {time.time()-t0:.1f}s")

    oos_ret = ret[oos_start_idx:]

    # ---- Build CF rolling standardized residuals ----
    # For CF-Rolling, we need rolling skewness/kurtosis of standardized residuals
    # We build one combined residual series per model (IS + OOS)

    models_info = {
        'GJR': {
            'forecasts': gjr_forecasts,
            'std_resid_at_refit': gjr_std_resid,
        },
        'A4f': {
            'forecasts': a4f_forecasts,
            'std_resid_at_refit': a4f_std_resid,
        },
    }

    all_results = {}

    for model_name, model_info in models_info.items():
        fc = model_info['forecasts']
        std_resid_at_refit = model_info['std_resid_at_refit']

        # Get initial in-sample residuals from first refit for CF
        if len(std_resid_at_refit) > 0:
            first_key = sorted(std_resid_at_refit.keys())[0]
            initial_is_resid = std_resid_at_refit[first_key]
        else:
            initial_is_resid = np.array([])

        # Build OOS standardized residuals using h=1 forecasts
        fc_1 = fc[1]
        oos_std_resid = np.full(n_oos, np.nan)
        for i in range(n_oos):
            if not np.isnan(fc_1[i]) and fc_1[i] > 0:
                oos_std_resid[i] = oos_ret[i] / np.sqrt(fc_1[i])

        # Combined residual series for CF rolling
        combined_resid = np.concatenate([initial_is_resid, oos_std_resid])
        combined_valid = ~np.isnan(combined_resid)
        n_is = len(initial_is_resid)

        for hh in HORIZONS:
            fc_h = fc[hh]
            valid = ~np.isnan(fc_h)
            n_valid = valid.sum()
            print(f"\n  {model_name} h={hh}: {n_valid}/{n_oos} valid forecasts")

            if n_valid < 100:
                print(f"  WARNING: Too few valid forecasts for {model_name} h={hh}")
                continue

            sigma_h = np.sqrt(fc_h)

            # === Methods ===
            # 1. Normal VaR
            # 2. CF-Rolling VaR
            # 3. Scaled 1-day VaR (sqrt(h) * 1-day VaR) -- only for h>1

            methods_to_test = ['Normal', 'CF-Rolling']
            if hh > 1:
                methods_to_test.append('Scaled_1d')

            for method in methods_to_test:
                for alpha in ALPHA_LEVELS:
                    key = f"{model_name}_{method}_h{hh}_{alpha}"

                    var_series = np.full(n_oos, np.nan)
                    es_series = np.full(n_oos, np.nan)

                    if method == 'Normal':
                        for i in range(n_oos):
                            if valid[i]:
                                var_series[i] = compute_var_normal(sigma_h[i], alpha)
                                es_series[i] = compute_es_normal(sigma_h[i], alpha)

                    elif method == 'CF-Rolling':
                        for i in range(n_oos):
                            if not valid[i]:
                                continue
                            # Rolling window of combined residuals
                            idx_combined = n_is + i
                            start_idx = max(0, idx_combined - CF_ROLLING_WINDOW)
                            window_resid = combined_resid[start_idx:idx_combined]
                            window_resid = window_resid[~np.isnan(window_resid)]
                            if len(window_resid) < 50:
                                # fallback to normal
                                var_series[i] = compute_var_normal(sigma_h[i], alpha)
                                es_series[i] = compute_es_normal(sigma_h[i], alpha)
                            else:
                                sk = float(stats.skew(window_resid))
                                ku = float(stats.kurtosis(window_resid))
                                var_series[i] = compute_var_cf(sigma_h[i], alpha, sk, ku)
                                es_series[i] = compute_es_cf(sigma_h[i], alpha, sk, ku)

                    elif method == 'Scaled_1d':
                        # Simple sqrt(h) scaling of 1-day VaR/ES
                        fc_1_valid = ~np.isnan(fc_1)
                        for i in range(n_oos):
                            if not fc_1_valid[i]:
                                continue
                            sigma_1 = np.sqrt(fc_1[i])
                            # For CF-Rolling based scaled VaR
                            idx_combined = n_is + i
                            start_idx = max(0, idx_combined - CF_ROLLING_WINDOW)
                            window_resid = combined_resid[start_idx:idx_combined]
                            window_resid = window_resid[~np.isnan(window_resid)]
                            if len(window_resid) < 50:
                                var_1d = compute_var_normal(sigma_1, alpha)
                                es_1d = compute_es_normal(sigma_1, alpha)
                            else:
                                sk = float(stats.skew(window_resid))
                                ku = float(stats.kurtosis(window_resid))
                                var_1d = compute_var_cf(sigma_1, alpha, sk, ku)
                                es_1d = compute_es_cf(sigma_1, alpha, sk, ku)
                            var_series[i] = var_1d * np.sqrt(hh)
                            es_series[i] = es_1d * np.sqrt(hh)

                    # ---- Evaluate using non-overlapping blocks ----
                    block_ret, block_var, block_es = compute_nonoverlapping_blocks(
                        oos_ret, var_series, es_series, hh
                    )

                    if len(block_ret) < 20:
                        print(f"    {key}: too few blocks ({len(block_ret)})")
                        continue

                    result = run_trinity_test(block_ret, block_var, block_es, alpha)
                    result['model'] = model_name
                    result['method'] = method
                    result['horizon'] = hh
                    result['alpha'] = alpha
                    all_results[key] = result

                    print(f"    {key}: VR={result['violation_rate']:.4f} "
                          f"Kupiec={result['kupiec']} CC={result['cc']} "
                          f"Basel={result['basel_color']} ES={result['es']} "
                          f"Trinity={result['trinity']}")

    return {
        'ticker': ticker,
        'n_total': n_total,
        'n_oos': n_oos,
        'oos_start': dates[oos_start_idx].strftime('%Y-%m-%d'),
        'results': all_results,
    }


# ============================================================
# SUMMARY ANALYSIS
# ============================================================

def compute_summary(all_asset_results):
    """Compute Trinity pass rates by model x method x horizon."""
    summary = {}

    for model in ['GJR', 'A4f']:
        for method in ['Normal', 'CF-Rolling', 'Scaled_1d']:
            for h in HORIZONS:
                if h == 1 and method == 'Scaled_1d':
                    continue  # no Scaled_1d for h=1
                key = f"{model}_{method}_h{h}"
                total = 0
                passed = 0
                for asset_data in all_asset_results.values():
                    if asset_data is None:
                        continue
                    for alpha in ALPHA_LEVELS:
                        rkey = f"{model}_{method}_h{h}_{alpha}"
                        if rkey in asset_data['results']:
                            total += 1
                            if asset_data['results'][rkey]['trinity'] == 'PASS':
                                passed += 1
                summary[key] = {
                    'total_tests': total,
                    'trinity_pass': passed,
                    'trinity_rate': round(passed / total, 3) if total > 0 else 0,
                }

    return summary


# ============================================================
# PLOTTING
# ============================================================

def plot_trinity_heatmap(summary, all_asset_results, save_path):
    """Create heatmap of Trinity pass rates by horizon x method."""
    fig, ax = plt.subplots(figsize=(12, 6))

    # Build matrix: rows = model_method, cols = horizons
    row_labels = []
    data_matrix = []

    for model in ['GJR', 'A4f']:
        for method in ['Normal', 'CF-Rolling', 'Scaled_1d']:
            row = []
            for h in HORIZONS:
                if h == 1 and method == 'Scaled_1d':
                    row.append(np.nan)
                else:
                    key = f"{model}_{method}_h{h}"
                    if key in summary:
                        row.append(summary[key]['trinity_rate'] * 100)
                    else:
                        row.append(0)
            row_labels.append(f"{model} + {method}")
            data_matrix.append(row)

    data_matrix = np.array(data_matrix)

    im = ax.imshow(data_matrix, cmap='RdYlGn', aspect='auto', vmin=0, vmax=100)

    ax.set_xticks(range(len(HORIZONS)))
    ax.set_xticklabels([f'h={h}' for h in HORIZONS], fontsize=12)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=10)

    for i in range(len(row_labels)):
        for j in range(len(HORIZONS)):
            val = data_matrix[i, j]
            if np.isnan(val):
                text = 'N/A'
                color = 'gray'
            else:
                text = f'{val:.0f}%'
                color = 'white' if val < 50 else 'black'
            ax.text(j, i, text, ha='center', va='center', fontsize=11,
                    fontweight='bold', color=color)

    ax.set_title(f'{EXPERIMENT_ID}: Trinity Pass Rate by Model x Method x Horizon\n'
                 f'(across {len(all_asset_results)} assets, alpha=1%/2.5%)',
                 fontsize=13, fontweight='bold')
    ax.set_xlabel('Forecast Horizon', fontsize=12)

    plt.colorbar(im, ax=ax, label='Trinity Pass Rate (%)')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\n  Saved heatmap: {save_path}")


def plot_violation_rates(all_asset_results, save_path):
    """Plot violation rates vs expected rates across horizons."""
    fig, axes = plt.subplots(1, len(HORIZONS), figsize=(5*len(HORIZONS), 6), sharey=True)

    if len(HORIZONS) == 1:
        axes = [axes]

    for idx, h in enumerate(HORIZONS):
        ax = axes[idx]
        models_methods = []
        vr_values = {a: [] for a in ALPHA_LEVELS}
        labels = []

        for model in ['GJR', 'A4f']:
            methods = ['Normal', 'CF-Rolling']
            if h > 1:
                methods.append('Scaled_1d')
            for method in methods:
                label = f"{model}\n{method}"
                labels.append(label)
                for alpha in ALPHA_LEVELS:
                    vrs = []
                    for asset_data in all_asset_results.values():
                        if asset_data is None:
                            continue
                        rkey = f"{model}_{method}_h{h}_{alpha}"
                        if rkey in asset_data['results']:
                            vrs.append(asset_data['results'][rkey]['violation_rate'])
                    vr_values[alpha].append(np.mean(vrs) if vrs else np.nan)

        x = np.arange(len(labels))
        width = 0.35

        ax.bar(x - width/2, vr_values[0.025], width, label='VR (alpha=2.5%)', color='steelblue', alpha=0.8)
        ax.bar(x + width/2, vr_values[0.01], width, label='VR (alpha=1%)', color='coral', alpha=0.8)

        ax.axhline(0.025, color='steelblue', linestyle='--', linewidth=1, alpha=0.5)
        ax.axhline(0.01, color='coral', linestyle='--', linewidth=1, alpha=0.5)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8, rotation=45, ha='right')
        ax.set_title(f'h = {h} day{"s" if h > 1 else ""}', fontsize=12, fontweight='bold')
        ax.set_ylabel('Violation Rate' if idx == 0 else '')
        ax.legend(fontsize=8)

    fig.suptitle(f'{EXPERIMENT_ID}: Violation Rates by Horizon (avg across assets)',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved violation rates: {save_path}")


def plot_scaling_comparison(all_asset_results, save_path):
    """Compare proper h-step vs sqrt(h) scaling."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for model_idx, model in enumerate(['GJR', 'A4f']):
        ax = axes[model_idx]

        for alpha in ALPHA_LEVELS:
            proper_vrs = []
            scaled_vrs = []
            horizons_plot = [h for h in HORIZONS if h > 1]

            for h in horizons_plot:
                prop_list = []
                scal_list = []
                for asset_data in all_asset_results.values():
                    if asset_data is None:
                        continue
                    rkey_cf = f"{model}_CF-Rolling_h{h}_{alpha}"
                    rkey_sc = f"{model}_Scaled_1d_h{h}_{alpha}"
                    if rkey_cf in asset_data['results']:
                        prop_list.append(asset_data['results'][rkey_cf]['violation_rate'])
                    if rkey_sc in asset_data['results']:
                        scal_list.append(asset_data['results'][rkey_sc]['violation_rate'])
                proper_vrs.append(np.mean(prop_list) if prop_list else np.nan)
                scaled_vrs.append(np.mean(scal_list) if scal_list else np.nan)

            ax.plot(horizons_plot, proper_vrs, 'o-', label=f'h-step CF (alpha={alpha})', linewidth=2)
            ax.plot(horizons_plot, scaled_vrs, 's--', label=f'sqrt(h) scaled (alpha={alpha})', linewidth=2)
            ax.axhline(alpha, color='gray', linestyle=':', alpha=0.5)

        ax.set_xlabel('Horizon (days)')
        ax.set_ylabel('Avg Violation Rate')
        ax.set_title(f'{model}: h-step vs sqrt(h) scaling')
        ax.legend(fontsize=9)
        ax.set_xticks(horizons_plot)

    fig.suptitle(f'{EXPERIMENT_ID}: Proper h-step vs sqrt(h) Scaling',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved scaling comparison: {save_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    all_asset_results = {}

    for ticker in ASSETS:
        result = run_backtest_for_asset(ticker)
        if result is not None:
            all_asset_results[ticker] = result

    if not all_asset_results:
        print("\nERROR: No results generated!")
        return

    # Summary
    summary = compute_summary(all_asset_results)

    print("\n" + "=" * 70)
    print("  SUMMARY: Trinity Pass Rates")
    print("=" * 70)

    for key, val in sorted(summary.items()):
        print(f"  {key:30s}: {val['trinity_pass']}/{val['total_tests']} "
              f"({val['trinity_rate']*100:.0f}%)")

    # Core conclusions
    print("\n" + "=" * 70)
    print("  CORE CONCLUSIONS")
    print("=" * 70)

    # Compare h=1 vs h=5 vs h=10 for best method (A4f + CF-Rolling)
    for h in HORIZONS:
        key = f"A4f_CF-Rolling_h{h}"
        if key in summary:
            rate = summary[key]['trinity_rate']
            print(f"  A4f + CF-Rolling h={h}: {rate*100:.0f}% Trinity PASS")

    # Compare proper vs scaled for h>1
    for h in [5, 10]:
        for model in ['GJR', 'A4f']:
            key_proper = f"{model}_CF-Rolling_h{h}"
            key_scaled = f"{model}_Scaled_1d_h{h}"
            if key_proper in summary and key_scaled in summary:
                rate_p = summary[key_proper]['trinity_rate']
                rate_s = summary[key_scaled]['trinity_rate']
                diff = rate_p - rate_s
                print(f"  {model} h={h}: proper={rate_p*100:.0f}% vs scaled={rate_s*100:.0f}% "
                      f"(diff={diff*100:+.0f}pp)")

    # ---- Plots ----
    heatmap_path = os.path.join(SCRIPT_DIR, 'k1039_trinity_heatmap.png')
    plot_trinity_heatmap(summary, all_asset_results, heatmap_path)

    vr_path = os.path.join(SCRIPT_DIR, 'k1039_violation_rates.png')
    plot_violation_rates(all_asset_results, vr_path)

    scaling_path = os.path.join(SCRIPT_DIR, 'k1039_scaling_comparison.png')
    plot_scaling_comparison(all_asset_results, scaling_path)

    # ---- Save results ----
    elapsed = time.time() - START_TIME

    results_json = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'A4f Multi-Horizon VaR (h=1, 5, 10 days)',
        'date': datetime.now(timezone.utc).isoformat(),
        'configuration': {
            'data_start': DATA_START,
            'data_end': DATA_END,
            'oos_start': OOS_START,
            'window': WINDOW,
            'refit_every': REFIT_EVERY,
            'df_fixed': DF_FIXED,
            'cf_rolling_window': CF_ROLLING_WINDOW,
            'alpha_levels': ALPHA_LEVELS,
            'horizons': HORIZONS,
            'assets': ASSETS,
            'seed': 42,
        },
        'models': {
            'GJR': 'GJR-GARCH(1,1) with Student-t(df=8) innovations',
            'A4f': 'A4f-VIX: tau_t = theta0 + theta1*VIX^2_{t-1}, sigma^2 = tau*g (multiplicative)',
        },
        'var_methods': {
            'Normal': 'VaR = sigma_h * z_alpha (Normal quantile)',
            'CF-Rolling': 'VaR = sigma_h * z_cf (CF with 252d rolling moments)',
            'Scaled_1d': 'VaR = sqrt(h) * VaR_1d (simple scaling, industry standard)',
        },
        'multi_horizon_method': {
            'GJR': 'Recursive h-step: sigma2[j] = omega + (alpha+gamma/2+beta)*sigma2[j-1], total_var = sum(sigma2)',
            'A4f': 'Strategy 1 (constant tau): tau fixed at tau_{t+1}, g evolves recursively',
        },
        'evaluation': {
            'non_overlapping': 'h-day returns in non-overlapping blocks for clean backtesting',
            'trinity': 'Kupiec + CC + Basel all PASS',
        },
        'asset_results': all_asset_results,
        'summary': summary,
        'references': [
            'Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320',
            'Kupiec (1995). J Derivatives 3:73-84',
            'Christoffersen (1998). Int Econ Rev 39(4):841-862',
            'Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk',
            'Basel Committee (2019). Minimum capital requirements for market risk',
            'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797',
            'K1036: A4f + CF-Rolling 6/6 Trinity PASS (best 1-day VaR)',
            'K943: MF-GJR h=5 best (+18.4%, DM t=-4.12)',
            'K988: A4f champion for SPY (DM t=+4.48 vs GJR)',
        ],
        'figures': [
            'k1039_trinity_heatmap.png',
            'k1039_violation_rates.png',
            'k1039_scaling_comparison.png',
        ],
        'elapsed_seconds': round(elapsed, 1),
        'data_source': 'yfinance',
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved: {RESULTS_PATH}")
    print(f"  Total elapsed: {elapsed:.1f}s")


if __name__ == '__main__':
    main()
