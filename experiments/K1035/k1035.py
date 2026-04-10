#!/usr/bin/env python3
"""
K1035: EVT-VaR with A4f Residuals (Extreme Value Theory)
=========================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K159 used GJR residuals with EVT-GPD: Kupiec 12/12 PASS but Trinity only 3/12.
  Now A4f-VIX is the best volatility model (K988/K1000). Using A4f residuals
  for EVT may improve Trinity pass rate because A4f's conditional variance is
  more accurate, making standardized residuals closer to i.i.d.

  This experiment compares:
  1. GJR-t VaR: GJR-GARCH + parametric Student-t(df=8) [baseline]
  2. GJR-EVT VaR: GJR-GARCH + EVT-GPD on standardized residuals
  3. A4f-t VaR: A4f-VIX + parametric Student-t(df=8) [current best]
  4. A4f-EVT VaR: A4f-VIX + EVT-GPD on standardized residuals

Data: SPY, QQQ from yfinance (2005-2026).
OOS: 2019-01-01 onwards, window=2000, refit/63d, seed=42.

Evaluation:
  - VaR at 2.5% and 1%: Kupiec (1995) LR test
  - ES backtesting: Acerbi & Szekely (2014) Z-test
  - Christoffersen (1998) CC test
  - Trinity test (Kupiec + CC + Basel)
  - Violation rate vs expected rate

References:
  - McNeil & Frey (2000). Estimation of tail-related risk measures for
    heteroscedastic financial time series: An EVT approach. J Empirical Finance.
  - Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement
    Models. Journal of Derivatives 3:73-84.
  - Christoffersen (1998). Evaluating Interval Forecasts. International Economic
    Review 39(4):841-862.
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - K159: GJR+EVT-GPD Kupiec 12/12 but Trinity 3/12
  - K988: A4f champion for SPY (DM t=+4.48 vs GJR)
  - K995: A4f-t best VaR model (12/12 PASS)
  - K1000: A4f-t joint MLE 6/6 VaR/ES scorecard
  - K1005: Conformal VaR, A4f already 14/14
  - K536: HAR-EVT passed Trinity (only model to do so)

Author: VolPred Research System
Date: 2026-04-10
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
from scipy.stats import genpareto
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1035"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike as qlike_func

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1035_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8
GPD_THRESHOLD_QUANTILE = 0.10  # Left tail 10th percentile of negative residuals

print("=" * 70)
print(f"{EXPERIMENT_ID}: EVT-VaR with A4f Residuals (GPD Tail Modeling)")
print("  Comparing: GJR-t, GJR-EVT, A4f-t, A4f-EVT")
print("  Assets: SPY, QQQ")
print("=" * 70)


# ============================================================
# GARCH RECURSIONS (from K1030)
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


def student_t_const(df):
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))

T_CONST_8 = student_t_const(DF_FIXED)


def gjr_nll_t(omega, alpha, gamma, beta, df, t_const, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2):
    """A4f multiplicative GARCH-X recursion.
    tau_t = max(theta0 + theta1 * fear2_{t-1}, eps)
    u_{t-1} = r_{t-1} / sqrt(tau_t)
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
        omega, alpha, gamma_p, beta = params
        if alpha + gamma_p / 2 + beta >= 0.999:
            return 1e10
        return gjr_nll_t(omega, alpha, gamma_p, beta, float(df), T_CONST_8, returns)

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
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if alpha + gamma_p / 2 + beta >= 0.999 or omega_g <= 0:
            return 1e10
        return a4f_nll_t(theta0, theta1, omega_g, alpha, gamma_p, beta,
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
# GPD-BASED VaR AND ES (EVT)
# ============================================================

def fit_gpd_to_residuals(std_residuals, threshold_quantile=GPD_THRESHOLD_QUANTILE):
    """Fit GPD to the left tail of standardized residuals.

    Following McNeil & Frey (2000):
    1. Negate residuals so we work with the right tail of losses
    2. Set threshold u at the (1 - threshold_quantile) quantile of negated residuals
    3. Fit GPD to exceedances above u

    Returns: (xi, beta_gpd, u, n_exceed, n_total) or None if fitting fails
    """
    # Work with losses (negate residuals)
    losses = -std_residuals

    # Threshold: upper quantile of losses (corresponds to left tail of returns)
    u = np.quantile(losses, 1 - threshold_quantile)

    exceedances = losses[losses > u] - u
    n_exceed = len(exceedances)
    n_total = len(losses)

    if n_exceed < 20:  # Need enough exceedances for reliable GPD fit
        return None

    try:
        # Fit GPD: genpareto.fit returns (c, loc, scale) where c = xi (shape)
        xi, loc, beta_gpd = genpareto.fit(exceedances, floc=0)  # fix location at 0

        # Sanity checks
        if beta_gpd <= 0 or xi < -0.5 or xi > 1.0:
            return None

        return (xi, beta_gpd, u, n_exceed, n_total)
    except Exception:
        return None


def gpd_var_es(alpha_level, xi, beta_gpd, u, n_exceed, n_total):
    """Compute VaR and ES from GPD parameters.

    VaR_p = u + (beta/xi) * ((n/N_u * p)^(-xi) - 1)  for xi != 0
    ES_p = VaR_p/(1-xi) + (beta - xi*u)/(1-xi)       for xi < 1

    Here alpha_level is the probability of loss exceedance (e.g., 0.025 for 2.5%).
    We compute VaR and ES for the LOSS distribution (negated returns).
    """
    p = alpha_level  # Tail probability

    # Fraction of observations exceeding threshold
    F_u = n_exceed / n_total

    if abs(xi) < 1e-8:
        # xi -> 0: exponential tail
        var_loss = u + beta_gpd * np.log(F_u / p)
    else:
        var_loss = u + (beta_gpd / xi) * ((F_u / p)**xi - 1)

    if xi < 1.0:
        es_loss = var_loss / (1 - xi) + (beta_gpd - xi * u) / (1 - xi)
    else:
        es_loss = var_loss * 2  # Fallback (shouldn't happen with xi < 1 check)

    # Convert back: VaR for returns is -var_loss, ES for returns is -es_loss
    return -var_loss, -es_loss


# ============================================================
# OOS FORECASTING WITH VaR/ES
# ============================================================

def oos_var_es_gjr_t(ret, oos_mask, window, refit_every, alpha_levels, df=DF_FIXED):
    """GJR-t parametric VaR/ES."""
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)

    results = {}
    for alpha in alpha_levels:
        results[alpha] = {
            'var': np.full(n_oos, np.nan),
            'es': np.full(n_oos, np.nan),
        }

    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every
    h_prev = None

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr_t(train_ret, df)
            if params is None:
                continue
            last_fit = t
            omega, alpha_p, gamma_p, beta = params
            h_series = gjr_recursion(omega, alpha_p, gamma_p, beta, train_ret)
            h_prev = h_series[-1]
        else:
            omega, alpha_p, gamma_p, beta = params
            u2 = ret[t-2]**2 if t >= 2 else ret[0]**2
            ind = 1.0 if (ret[t-2] if t >= 2 else ret[0]) < 0 else 0.0
            h_prev = max(omega + alpha_p * u2 + gamma_p * u2 * ind + beta * h_prev, 1e-10)

        if params is None:
            continue
        omega, alpha_p, gamma_p, beta = params
        u2 = ret[t-1]**2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        h_t = max(omega + alpha_p * u2 + gamma_p * u2 * ind + beta * h_prev, 1e-10)
        forecasts[i] = h_t

        # Parametric VaR/ES using Student-t
        scale = np.sqrt(h_t * (df - 2) / df)
        for alpha_lev in alpha_levels:
            t_q = stats.t.ppf(alpha_lev, df)
            results[alpha_lev]['var'][i] = t_q * scale
            # ES for Student-t
            t_pdf = stats.t.pdf(t_q, df)
            es_factor = -(df + t_q**2) / (df - 1) * t_pdf / alpha_lev
            results[alpha_lev]['es'][i] = es_factor * scale

    return results, forecasts


def oos_var_es_gjr_evt(ret, oos_mask, window, refit_every, alpha_levels, df=DF_FIXED):
    """GJR-EVT VaR/ES: GJR variance + GPD on standardized residuals."""
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)

    results = {}
    for alpha in alpha_levels:
        results[alpha] = {
            'var': np.full(n_oos, np.nan),
            'es': np.full(n_oos, np.nan),
        }

    forecasts = np.full(n_oos, np.nan)
    gpd_params_history = []  # Track GPD xi over time
    params = None
    last_fit = -refit_every
    h_prev = None
    gpd_fit = None

    for i, t in enumerate(oos_indices):
        if t - last_fit >= refit_every or params is None:
            train_start = max(0, t - window)
            train_ret = ret[train_start:t]
            if len(train_ret) < 500:
                continue
            params = fit_gjr_t(train_ret, df)
            if params is None:
                continue
            last_fit = t
            omega, alpha_p, gamma_p, beta = params
            h_series = gjr_recursion(omega, alpha_p, gamma_p, beta, train_ret)
            h_prev = h_series[-1]

            # Compute standardized residuals and fit GPD
            std_resid = train_ret / np.sqrt(h_series)
            gpd_fit = fit_gpd_to_residuals(std_resid)
            if gpd_fit is not None:
                gpd_params_history.append({
                    'time_idx': int(t),
                    'xi': float(gpd_fit[0]),
                    'beta': float(gpd_fit[1]),
                    'u': float(gpd_fit[2]),
                    'n_exceed': int(gpd_fit[3]),
                })
        else:
            omega, alpha_p, gamma_p, beta = params
            u2 = ret[t-2]**2 if t >= 2 else ret[0]**2
            ind = 1.0 if (ret[t-2] if t >= 2 else ret[0]) < 0 else 0.0
            h_prev = max(omega + alpha_p * u2 + gamma_p * u2 * ind + beta * h_prev, 1e-10)

        if params is None or gpd_fit is None:
            continue
        omega, alpha_p, gamma_p, beta = params
        u2 = ret[t-1]**2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        h_t = max(omega + alpha_p * u2 + gamma_p * u2 * ind + beta * h_prev, 1e-10)
        forecasts[i] = h_t

        # EVT VaR/ES: scale GPD quantiles by sqrt(h_t)
        xi, beta_gpd, u_thresh, n_exc, n_tot = gpd_fit
        for alpha_lev in alpha_levels:
            var_std, es_std = gpd_var_es(alpha_lev, xi, beta_gpd, u_thresh, n_exc, n_tot)
            results[alpha_lev]['var'][i] = var_std * np.sqrt(h_t)
            results[alpha_lev]['es'][i] = es_std * np.sqrt(h_t)

    return results, forecasts, gpd_params_history


def oos_var_es_a4f_t(ret, fear_vals, oos_mask, window, refit_every, alpha_levels, df=DF_FIXED):
    """A4f-t parametric VaR/ES."""
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)

    results = {}
    for alpha in alpha_levels:
        results[alpha] = {
            'var': np.full(n_oos, np.nan),
            'es': np.full(n_oos, np.nan),
        }

    forecasts = np.full(n_oos, np.nan)
    params = None
    last_fit = -refit_every
    g_prev = None
    r_prev_val = None

    for i, t in enumerate(oos_indices):
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
            theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
            _, _, g_series = a4f_recursion(
                theta0, theta1, omega_g, alpha_p, gamma_p, beta,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]
        else:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
            tau_curr = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            u2 = u_prev ** 2
            ind = 1.0 if r_prev_val < 0 else 0.0
            g_prev = max(omega_g + alpha_p * u2 + gamma_p * u2 * ind + beta * g_prev, 1e-10)
            r_prev_val = ret[t-1]

        if params is None:
            continue
        theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        u2_fc = u_prev_fc ** 2
        ind_fc = 1.0 if ret[t-1] < 0 else 0.0
        g_fc = max(omega_g + alpha_p * u2_fc + gamma_p * u2_fc * ind_fc + beta * g_prev, 1e-10)
        h_t = tau_t * g_fc
        forecasts[i] = h_t

        # Parametric VaR/ES using Student-t
        scale = np.sqrt(h_t * (df - 2) / df)
        for alpha_lev in alpha_levels:
            t_q = stats.t.ppf(alpha_lev, df)
            results[alpha_lev]['var'][i] = t_q * scale
            t_pdf = stats.t.pdf(t_q, df)
            es_factor = -(df + t_q**2) / (df - 1) * t_pdf / alpha_lev
            results[alpha_lev]['es'][i] = es_factor * scale

    return results, forecasts


def oos_var_es_a4f_evt(ret, fear_vals, oos_mask, window, refit_every, alpha_levels, df=DF_FIXED):
    """A4f-EVT VaR/ES: A4f variance + GPD on standardized residuals."""
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)

    results = {}
    for alpha in alpha_levels:
        results[alpha] = {
            'var': np.full(n_oos, np.nan),
            'es': np.full(n_oos, np.nan),
        }

    forecasts = np.full(n_oos, np.nan)
    gpd_params_history = []
    params = None
    last_fit = -refit_every
    g_prev = None
    r_prev_val = None
    gpd_fit = None

    for i, t in enumerate(oos_indices):
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
            theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
            h_series, _, g_series = a4f_recursion(
                theta0, theta1, omega_g, alpha_p, gamma_p, beta,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            r_prev_val = train_ret[-1]

            # Standardized residuals from A4f
            std_resid = train_ret / np.sqrt(h_series)
            gpd_fit = fit_gpd_to_residuals(std_resid)
            if gpd_fit is not None:
                gpd_params_history.append({
                    'time_idx': int(t),
                    'xi': float(gpd_fit[0]),
                    'beta': float(gpd_fit[1]),
                    'u': float(gpd_fit[2]),
                    'n_exceed': int(gpd_fit[3]),
                })
        else:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
            tau_curr = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
            u_prev = r_prev_val / np.sqrt(tau_curr)
            u2 = u_prev ** 2
            ind = 1.0 if r_prev_val < 0 else 0.0
            g_prev = max(omega_g + alpha_p * u2 + gamma_p * u2 * ind + beta * g_prev, 1e-10)
            r_prev_val = ret[t-1]

        if params is None or gpd_fit is None:
            continue
        theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        u2_fc = u_prev_fc ** 2
        ind_fc = 1.0 if ret[t-1] < 0 else 0.0
        g_fc = max(omega_g + alpha_p * u2_fc + gamma_p * u2_fc * ind_fc + beta * g_prev, 1e-10)
        h_t = tau_t * g_fc
        forecasts[i] = h_t

        # EVT VaR/ES
        xi, beta_gpd, u_thresh, n_exc, n_tot = gpd_fit
        for alpha_lev in alpha_levels:
            var_std, es_std = gpd_var_es(alpha_lev, xi, beta_gpd, u_thresh, n_exc, n_tot)
            results[alpha_lev]['var'][i] = var_std * np.sqrt(h_t)
            results[alpha_lev]['es'][i] = es_std * np.sqrt(h_t)

    return results, forecasts, gpd_params_history


# ============================================================
# BACKTESTING FUNCTIONS
# ============================================================

def kupiec_test(returns_oos, var_series, alpha_level):
    """Kupiec (1995) unconditional coverage test."""
    valid = ~np.isnan(var_series)
    ret = returns_oos[valid]
    var_s = var_series[valid]
    n = len(ret)
    if n < 100:
        return {'vr': np.nan, 'expected': alpha_level, 'lr': np.nan, 'p_value': np.nan, 'result': 'SKIP'}

    violations = (ret < var_s).sum()
    vr = violations / n

    if violations == 0:
        lr = -2 * n * np.log(1 - alpha_level)
    elif violations == n:
        lr = -2 * n * np.log(alpha_level)
    else:
        lr = -2 * (np.log((1 - alpha_level)**(n - violations) * alpha_level**violations)
                    - np.log((1 - vr)**(n - violations) * vr**violations))

    p_value = 1 - stats.chi2.cdf(lr, 1)
    return {
        'vr': float(vr),
        'expected': alpha_level,
        'n_violations': int(violations),
        'n_obs': n,
        'lr': float(lr),
        'p_value': float(p_value),
        'result': 'PASS' if p_value > 0.05 else 'FAIL'
    }


def christoffersen_cc_test(returns_oos, var_series, alpha_level):
    """Christoffersen (1998) conditional coverage test (independence + coverage)."""
    valid = ~np.isnan(var_series)
    ret = returns_oos[valid]
    var_s = var_series[valid]
    n = len(ret)
    if n < 100:
        return {'lr_cc': np.nan, 'p_value': np.nan, 'result': 'SKIP'}

    # Violation indicator
    viol = (ret < var_s).astype(int)

    # Count transitions
    n00 = n01 = n10 = n11 = 0
    for j in range(1, len(viol)):
        if viol[j-1] == 0 and viol[j] == 0:
            n00 += 1
        elif viol[j-1] == 0 and viol[j] == 1:
            n01 += 1
        elif viol[j-1] == 1 and viol[j] == 0:
            n10 += 1
        else:
            n11 += 1

    # Independence test
    n0 = n00 + n01
    n1 = n10 + n11

    if n0 == 0 or n1 == 0 or n01 + n11 == 0:
        return {'lr_cc': np.nan, 'p_value': np.nan, 'result': 'SKIP'}

    pi_hat = (n01 + n11) / (n - 1)
    pi0 = n01 / n0 if n0 > 0 else 0
    pi1 = n11 / n1 if n1 > 0 else 0

    # Avoid log(0)
    eps = 1e-15
    pi0 = max(eps, min(1-eps, pi0))
    pi1 = max(eps, min(1-eps, pi1))
    pi_hat = max(eps, min(1-eps, pi_hat))

    # LR independence
    lr_ind = -2 * (n00 * np.log(1-pi_hat) + n01 * np.log(pi_hat) +
                    n10 * np.log(1-pi_hat) + n11 * np.log(pi_hat))
    lr_ind += 2 * (n00 * np.log(1-pi0) + n01 * np.log(pi0) +
                   n10 * np.log(1-pi1) + n11 * np.log(pi1))

    # LR unconditional coverage
    vr = (n01 + n11) / (n - 1)
    vr = max(eps, min(1-eps, vr))
    alpha_c = max(eps, min(1-eps, alpha_level))
    n_viol = n01 + n11
    n_no_viol = n00 + n10

    lr_uc = -2 * (n_no_viol * np.log(1-alpha_c) + n_viol * np.log(alpha_c))
    lr_uc += 2 * (n_no_viol * np.log(1-vr) + n_viol * np.log(vr))

    # CC = UC + IND
    lr_cc = lr_uc + lr_ind
    p_value = 1 - stats.chi2.cdf(lr_cc, 2)  # 2 degrees of freedom

    return {
        'lr_cc': float(lr_cc),
        'lr_ind': float(lr_ind),
        'lr_uc': float(lr_uc),
        'p_value': float(p_value),
        'result': 'PASS' if p_value > 0.05 else 'FAIL',
        'n01': int(n01), 'n11': int(n11),
    }


def basel_traffic_light(returns_oos, var_series, alpha_level):
    """Basel traffic light test (250-day rolling window)."""
    valid = ~np.isnan(var_series)
    ret = returns_oos[valid]
    var_s = var_series[valid]
    n = len(ret)
    if n < 250:
        return {'color': 'SKIP', 'max_violations_250': np.nan}

    violations = (ret < var_s).astype(int)

    # Check the last 250 days
    max_viol_250 = 0
    for start in range(max(0, n - 250), n - 249):
        end = start + 250
        v_count = violations[start:end].sum()
        max_viol_250 = max(max_viol_250, v_count)

    # For 1% VaR, expected = 2.5 violations in 250 days
    # Green: <= 4, Yellow: 5-9, Red: >= 10
    if alpha_level <= 0.01:
        if max_viol_250 <= 4:
            color = 'GREEN'
        elif max_viol_250 <= 9:
            color = 'YELLOW'
        else:
            color = 'RED'
    else:  # 2.5%
        # Expected = 6.25 violations in 250 days
        # Green: <= 9, Yellow: 10-14, Red: >= 15
        if max_viol_250 <= 9:
            color = 'GREEN'
        elif max_viol_250 <= 14:
            color = 'YELLOW'
        else:
            color = 'RED'

    return {
        'color': color,
        'max_violations_250': int(max_viol_250),
        'result': 'PASS' if color == 'GREEN' else 'FAIL'
    }


def es_backtest_as(returns_oos, var_series, es_series, alpha_level):
    """Acerbi & Szekely (2014) ES backtest."""
    valid = ~(np.isnan(var_series) | np.isnan(es_series))
    ret = returns_oos[valid]
    var_s = var_series[valid]
    es_s = es_series[valid]
    n = len(ret)
    if n < 100:
        return {'z_stat': np.nan, 'p_value': np.nan, 'result': 'SKIP'}

    violations_mask = ret < var_s
    n_viol = violations_mask.sum()

    if n_viol == 0:
        return {'z_stat': 0.0, 'p_value': np.nan, 'n_violations': 0, 'result': 'SKIP'}

    # Acerbi-Szekely Z1 statistic
    z_stat = 1 / (n * alpha_level) * np.sum(ret[violations_mask] / es_s[violations_mask]) + 1

    p_value = stats.norm.cdf(z_stat)

    return {
        'z_stat': float(z_stat),
        'p_value': float(p_value),
        'n_violations': int(n_viol),
        'vr': float(n_viol / n),
        'result': 'PASS' if p_value > 0.05 else 'FAIL'
    }


def trinity_test(kupiec_res, cc_res, basel_res):
    """Trinity = all three pass."""
    k = kupiec_res.get('result', 'SKIP')
    c = cc_res.get('result', 'SKIP')
    b = basel_res.get('result', 'SKIP')

    if 'SKIP' in [k, c, b]:
        return 'SKIP'

    return 'PASS' if k == 'PASS' and c == 'PASS' and b == 'PASS' else 'FAIL'


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

# Load VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_series = vix_raw['Close'].copy() / 100.0  # VIX as decimal
print(f"  VIX: {len(vix_series)} obs ({vix_series.index[0].strftime('%Y-%m-%d')} to {vix_series.index[-1].strftime('%Y-%m-%d')})")

# Assets
ASSETS = ['SPY', 'QQQ']
ALPHA_LEVELS = [0.025, 0.01]

all_results = {}

for asset in ASSETS:
    print(f"\n{'='*60}")
    print(f"  Asset: {asset}")
    print(f"{'='*60}")

    raw = yf.download(asset, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    # Align with VIX
    df_data = pd.DataFrame({
        'price': prices,
        'log_ret': log_ret,
        'VIX': vix_series,
    }).dropna()

    ret_arr = df_data['log_ret'].values
    vix_arr = df_data['VIX'].values
    dates = df_data.index

    # OOS mask
    oos_mask = dates >= OOS_START
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    returns_oos = ret_arr[oos_indices]

    print(f"  Total obs: {len(ret_arr)}, OOS: {n_oos}")
    print(f"  OOS period: {dates[oos_indices[0]].strftime('%Y-%m-%d')} to {dates[oos_indices[-1]].strftime('%Y-%m-%d')}")

    # Descriptive stats
    print(f"\n  OOS Descriptive Statistics:")
    print(f"    Mean: {np.mean(returns_oos)*252:.4f} (ann)")
    print(f"    Std:  {np.std(returns_oos)*np.sqrt(252):.4f} (ann)")
    print(f"    Skew: {stats.skew(returns_oos):.4f}")
    print(f"    Kurt: {stats.kurtosis(returns_oos):.4f}")

    asset_results = {
        'n_total': len(ret_arr),
        'n_oos': n_oos,
        'oos_start': dates[oos_indices[0]].strftime('%Y-%m-%d'),
        'oos_end': dates[oos_indices[-1]].strftime('%Y-%m-%d'),
        'models': {}
    }

    # ============================================================
    # MODEL 1: GJR-t (baseline)
    # ============================================================
    print(f"\n  [M1] GJR-t(df=8) parametric VaR/ES...")
    t0 = time.time()
    gjr_t_results, gjr_forecasts = oos_var_es_gjr_t(
        ret_arr, oos_mask, WINDOW, REFIT_EVERY, ALPHA_LEVELS, DF_FIXED
    )
    t1 = time.time()
    print(f"    Time: {t1-t0:.1f}s")

    m1_res = {'backtests': {}, 'time_s': round(t1-t0, 1)}
    for alpha_lev in ALPHA_LEVELS:
        var_s = gjr_t_results[alpha_lev]['var']
        es_s = gjr_t_results[alpha_lev]['es']
        kup = kupiec_test(returns_oos, var_s, alpha_lev)
        cc = christoffersen_cc_test(returns_oos, var_s, alpha_lev)
        bas = basel_traffic_light(returns_oos, var_s, alpha_lev)
        es = es_backtest_as(returns_oos, var_s, es_s, alpha_lev)
        tri = trinity_test(kup, cc, bas)

        key = f"{alpha_lev:.3f}"
        m1_res['backtests'][key] = {
            'kupiec': kup,
            'christoffersen': cc,
            'basel': bas,
            'es_backtest': es,
            'trinity': tri
        }
        print(f"    alpha={alpha_lev}: Kupiec={kup['result']}(vr={kup['vr']:.4f}) CC={cc['result']} "
              f"Basel={bas['color']} ES={es['result']} Trinity={tri}")

    asset_results['models']['GJR-t'] = m1_res

    # ============================================================
    # MODEL 2: GJR-EVT
    # ============================================================
    print(f"\n  [M2] GJR-EVT (GPD tail)...")
    t0 = time.time()
    gjr_evt_results, gjr_evt_forecasts, gjr_gpd_history = oos_var_es_gjr_evt(
        ret_arr, oos_mask, WINDOW, REFIT_EVERY, ALPHA_LEVELS, DF_FIXED
    )
    t1 = time.time()
    print(f"    Time: {t1-t0:.1f}s")

    if gjr_gpd_history:
        xi_vals = [g['xi'] for g in gjr_gpd_history]
        print(f"    GPD xi: mean={np.mean(xi_vals):.4f}, std={np.std(xi_vals):.4f}, "
              f"range=[{np.min(xi_vals):.4f}, {np.max(xi_vals):.4f}]")

    m2_res = {'backtests': {}, 'time_s': round(t1-t0, 1), 'gpd_history': gjr_gpd_history}
    for alpha_lev in ALPHA_LEVELS:
        var_s = gjr_evt_results[alpha_lev]['var']
        es_s = gjr_evt_results[alpha_lev]['es']
        kup = kupiec_test(returns_oos, var_s, alpha_lev)
        cc = christoffersen_cc_test(returns_oos, var_s, alpha_lev)
        bas = basel_traffic_light(returns_oos, var_s, alpha_lev)
        es = es_backtest_as(returns_oos, var_s, es_s, alpha_lev)
        tri = trinity_test(kup, cc, bas)

        key = f"{alpha_lev:.3f}"
        m2_res['backtests'][key] = {
            'kupiec': kup,
            'christoffersen': cc,
            'basel': bas,
            'es_backtest': es,
            'trinity': tri
        }
        print(f"    alpha={alpha_lev}: Kupiec={kup['result']}(vr={kup['vr']:.4f}) CC={cc['result']} "
              f"Basel={bas['color']} ES={es['result']} Trinity={tri}")

    asset_results['models']['GJR-EVT'] = m2_res

    # ============================================================
    # MODEL 3: A4f-t
    # ============================================================
    print(f"\n  [M3] A4f-t(df=8) parametric VaR/ES...")
    t0 = time.time()
    a4f_t_results, a4f_forecasts = oos_var_es_a4f_t(
        ret_arr, vix_arr, oos_mask, WINDOW, REFIT_EVERY, ALPHA_LEVELS, DF_FIXED
    )
    t1 = time.time()
    print(f"    Time: {t1-t0:.1f}s")

    m3_res = {'backtests': {}, 'time_s': round(t1-t0, 1)}
    for alpha_lev in ALPHA_LEVELS:
        var_s = a4f_t_results[alpha_lev]['var']
        es_s = a4f_t_results[alpha_lev]['es']
        kup = kupiec_test(returns_oos, var_s, alpha_lev)
        cc = christoffersen_cc_test(returns_oos, var_s, alpha_lev)
        bas = basel_traffic_light(returns_oos, var_s, alpha_lev)
        es = es_backtest_as(returns_oos, var_s, es_s, alpha_lev)
        tri = trinity_test(kup, cc, bas)

        key = f"{alpha_lev:.3f}"
        m3_res['backtests'][key] = {
            'kupiec': kup,
            'christoffersen': cc,
            'basel': bas,
            'es_backtest': es,
            'trinity': tri
        }
        print(f"    alpha={alpha_lev}: Kupiec={kup['result']}(vr={kup['vr']:.4f}) CC={cc['result']} "
              f"Basel={bas['color']} ES={es['result']} Trinity={tri}")

    asset_results['models']['A4f-t'] = m3_res

    # ============================================================
    # MODEL 4: A4f-EVT
    # ============================================================
    print(f"\n  [M4] A4f-EVT (GPD tail)...")
    t0 = time.time()
    a4f_evt_results, a4f_evt_forecasts, a4f_gpd_history = oos_var_es_a4f_evt(
        ret_arr, vix_arr, oos_mask, WINDOW, REFIT_EVERY, ALPHA_LEVELS, DF_FIXED
    )
    t1 = time.time()
    print(f"    Time: {t1-t0:.1f}s")

    if a4f_gpd_history:
        xi_vals = [g['xi'] for g in a4f_gpd_history]
        print(f"    GPD xi: mean={np.mean(xi_vals):.4f}, std={np.std(xi_vals):.4f}, "
              f"range=[{np.min(xi_vals):.4f}, {np.max(xi_vals):.4f}]")

    m4_res = {'backtests': {}, 'time_s': round(t1-t0, 1), 'gpd_history': a4f_gpd_history}
    for alpha_lev in ALPHA_LEVELS:
        var_s = a4f_evt_results[alpha_lev]['var']
        es_s = a4f_evt_results[alpha_lev]['es']
        kup = kupiec_test(returns_oos, var_s, alpha_lev)
        cc = christoffersen_cc_test(returns_oos, var_s, alpha_lev)
        bas = basel_traffic_light(returns_oos, var_s, alpha_lev)
        es = es_backtest_as(returns_oos, var_s, es_s, alpha_lev)
        tri = trinity_test(kup, cc, bas)

        key = f"{alpha_lev:.3f}"
        m4_res['backtests'][key] = {
            'kupiec': kup,
            'christoffersen': cc,
            'basel': bas,
            'es_backtest': es,
            'trinity': tri
        }
        print(f"    alpha={alpha_lev}: Kupiec={kup['result']}(vr={kup['vr']:.4f}) CC={cc['result']} "
              f"Basel={bas['color']} ES={es['result']} Trinity={tri}")

    asset_results['models']['A4f-EVT'] = m4_res

    # ============================================================
    # QLIKE comparison (variance forecasts)
    # ============================================================
    print(f"\n  [QLIKE] Variance forecast comparison (r² target)...")
    r2 = returns_oos ** 2

    models_fc = {
        'GJR': gjr_forecasts,
        'A4f': a4f_forecasts,
    }

    qlike_results = {}
    for name, fc in models_fc.items():
        valid = ~np.isnan(fc)
        if valid.sum() > 100:
            ql = float(qlike_func(r2[valid], fc[valid]))
            qlike_results[name] = ql
            print(f"    {name}: QLIKE = {ql:.6f}")

    # DM test: A4f vs GJR (using QLIKE losses)
    valid_both = ~(np.isnan(gjr_forecasts) | np.isnan(a4f_forecasts))
    if valid_both.sum() > 100:
        # QLIKE loss: L(sigma2, r2) = log(sigma2) + r2/sigma2
        loss_a4f = np.log(a4f_forecasts[valid_both]) + r2[valid_both] / a4f_forecasts[valid_both]
        loss_gjr = np.log(gjr_forecasts[valid_both]) + r2[valid_both] / gjr_forecasts[valid_both]
        dm_stat, dm_pval = dm_test(loss_a4f, loss_gjr)
        print(f"    DM test (A4f vs GJR): t={dm_stat:.4f}, p={dm_pval:.4f}")
        print(f"      Negative t => A4f better")
        qlike_results['dm_a4f_vs_gjr'] = {'t_stat': float(dm_stat), 'p_value': float(dm_pval)}

    asset_results['qlike'] = qlike_results

    # ============================================================
    # SUMMARY TABLE
    # ============================================================
    print(f"\n  {'='*60}")
    print(f"  SUMMARY: {asset}")
    print(f"  {'='*60}")
    print(f"  {'Model':<12} {'alpha':>6} {'Kupiec':>8} {'CC':>8} {'Basel':>8} {'ES':>8} {'Trinity':>8}")
    print(f"  {'-'*60}")

    trinity_counts = {}
    for model_name in ['GJR-t', 'GJR-EVT', 'A4f-t', 'A4f-EVT']:
        trinity_counts[model_name] = 0
        total_tests = 0
        for alpha_lev in ALPHA_LEVELS:
            key = f"{alpha_lev:.3f}"
            bt = asset_results['models'][model_name]['backtests'][key]
            tri = bt['trinity']
            if tri == 'PASS':
                trinity_counts[model_name] += 1
            if tri != 'SKIP':
                total_tests += 1
            print(f"  {model_name:<12} {alpha_lev:>6.3f} "
                  f"{bt['kupiec']['result']:>8} "
                  f"{bt['christoffersen']['result']:>8} "
                  f"{bt['basel']['result']:>8} "
                  f"{bt['es_backtest']['result']:>8} "
                  f"{tri:>8}")
        print(f"  {'':>12} {'':>6} Trinity pass rate: {trinity_counts[model_name]}/{total_tests}")

    asset_results['trinity_summary'] = trinity_counts
    all_results[asset] = asset_results


# ============================================================
# VISUALIZATION
# ============================================================
print("\n\n[PLOTS] Generating visualizations...")

# --- Plot 1: Violation Rate Comparison ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6))
model_names = ['GJR-t', 'GJR-EVT', 'A4f-t', 'A4f-EVT']
colors = ['#3498db', '#2ecc71', '#e74c3c', '#9b59b6']

for ax_idx, asset in enumerate(ASSETS):
    ax = axes[ax_idx]
    x = np.arange(len(ALPHA_LEVELS))
    width = 0.18

    for m_idx, model_name in enumerate(model_names):
        vrs = []
        for alpha_lev in ALPHA_LEVELS:
            key = f"{alpha_lev:.3f}"
            bt = all_results[asset]['models'][model_name]['backtests'][key]
            vrs.append(bt['kupiec']['vr'] if not np.isnan(bt['kupiec'].get('vr', np.nan)) else 0)
        ax.bar(x + (m_idx - 1.5) * width, vrs, width, label=model_name, color=colors[m_idx], alpha=0.85)

    # Expected violation rates
    for i, alpha_lev in enumerate(ALPHA_LEVELS):
        ax.axhline(y=alpha_lev, color='black', linestyle='--', alpha=0.3)
        ax.text(len(ALPHA_LEVELS) - 0.5, alpha_lev + 0.001, f'Expected: {alpha_lev}', fontsize=8, alpha=0.6)

    ax.set_xlabel('VaR Level')
    ax.set_ylabel('Violation Rate')
    ax.set_title(f'{asset}: VaR Violation Rates')
    ax.set_xticks(x)
    ax.set_xticklabels([f'{a:.1%}' for a in ALPHA_LEVELS])
    ax.legend(fontsize=8)

plt.tight_layout()
plot1_path = os.path.join(SCRIPT_DIR, 'k1035_violation_rates.png')
plt.savefig(plot1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot1_path}")


# --- Plot 2: Trinity Heatmap ---
fig, ax = plt.subplots(figsize=(12, 5))

# Build matrix: rows = models, columns = (asset, alpha)
col_labels = []
for asset in ASSETS:
    for alpha_lev in ALPHA_LEVELS:
        col_labels.append(f"{asset}\n{alpha_lev:.1%}")

matrix = np.zeros((len(model_names), len(col_labels)))
text_matrix = []

for m_idx, model_name in enumerate(model_names):
    row_text = []
    for c_idx, (asset, alpha_lev) in enumerate([(a, al) for a in ASSETS for al in ALPHA_LEVELS]):
        key = f"{alpha_lev:.3f}"
        bt = all_results[asset]['models'][model_name]['backtests'][key]

        # Kupiec, CC, Basel, ES, Trinity
        kupiec = 1 if bt['kupiec']['result'] == 'PASS' else 0
        cc = 1 if bt['christoffersen']['result'] == 'PASS' else 0
        basel = 1 if bt['basel']['result'] == 'PASS' else 0
        es = 1 if bt['es_backtest']['result'] == 'PASS' else 0
        trinity = bt['trinity']

        score = kupiec + cc + basel + es  # out of 4
        matrix[m_idx, c_idx] = score

        tri_symbol = 'T:PASS' if trinity == 'PASS' else 'T:FAIL'
        row_text.append(f"K:{bt['kupiec']['result'][0]} C:{bt['christoffersen']['result'][0]}\n"
                       f"B:{bt['basel']['result'][0]} E:{bt['es_backtest']['result'][0]}\n{tri_symbol}")
    text_matrix.append(row_text)

# Colormap: 0=red, 4=green
cmap = plt.cm.RdYlGn
im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=4, aspect='auto')

for i in range(len(model_names)):
    for j in range(len(col_labels)):
        ax.text(j, i, text_matrix[i][j], ha='center', va='center', fontsize=7,
                fontweight='bold' if 'T:PASS' in text_matrix[i][j] else 'normal')

ax.set_xticks(range(len(col_labels)))
ax.set_xticklabels(col_labels, fontsize=9)
ax.set_yticks(range(len(model_names)))
ax.set_yticklabels(model_names, fontsize=10)
ax.set_title('K1035: VaR/ES Backtesting Results\n(K=Kupiec, C=CC, B=Basel, E=ES, T=Trinity)', fontsize=12)
plt.colorbar(im, label='Tests Passed (out of 4)', shrink=0.8)

plt.tight_layout()
plot2_path = os.path.join(SCRIPT_DIR, 'k1035_trinity_heatmap.png')
plt.savefig(plot2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot2_path}")


# --- Plot 3: GPD xi parameter stability ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for ax_idx, asset in enumerate(ASSETS):
    ax = axes[ax_idx]

    gjr_gpd = all_results[asset]['models']['GJR-EVT'].get('gpd_history', [])
    a4f_gpd = all_results[asset]['models']['A4f-EVT'].get('gpd_history', [])

    if gjr_gpd:
        gjr_xi = [g['xi'] for g in gjr_gpd]
        gjr_t = range(len(gjr_xi))
        ax.plot(gjr_t, gjr_xi, 'o-', color='#2ecc71', label='GJR-EVT xi', alpha=0.8, markersize=4)

    if a4f_gpd:
        a4f_xi = [g['xi'] for g in a4f_gpd]
        a4f_t = range(len(a4f_xi))
        ax.plot(a4f_t, a4f_xi, 's-', color='#9b59b6', label='A4f-EVT xi', alpha=0.8, markersize=4)

    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_xlabel('Refit Period')
    ax.set_ylabel('GPD Shape Parameter (xi)')
    ax.set_title(f'{asset}: GPD xi Over Time')
    ax.legend()

plt.tight_layout()
plot3_path = os.path.join(SCRIPT_DIR, 'k1035_gpd_xi_stability.png')
plt.savefig(plot3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot3_path}")


# ============================================================
# OVERALL SUMMARY
# ============================================================
print("\n\n" + "=" * 70)
print("OVERALL SUMMARY: EVT vs Parametric VaR/ES")
print("=" * 70)

total_trinity = {m: 0 for m in model_names}
total_tests = 0

for asset in ASSETS:
    for model_name in model_names:
        total_trinity[model_name] += all_results[asset]['trinity_summary'][model_name]
    total_tests += len(ALPHA_LEVELS)

print(f"\n  Trinity PASS rates across {len(ASSETS)} assets x {len(ALPHA_LEVELS)} levels = {total_tests} tests:")
for model_name in model_names:
    print(f"    {model_name:<12}: {total_trinity[model_name]}/{total_tests}")

# EVT improvement check
print(f"\n  EVT improvement over parametric:")
print(f"    GJR: {total_trinity['GJR-t']} -> {total_trinity['GJR-EVT']} "
      f"({'IMPROVED' if total_trinity['GJR-EVT'] > total_trinity['GJR-t'] else 'NO IMPROVEMENT' if total_trinity['GJR-EVT'] == total_trinity['GJR-t'] else 'WORSE'})")
print(f"    A4f: {total_trinity['A4f-t']} -> {total_trinity['A4f-EVT']} "
      f"({'IMPROVED' if total_trinity['A4f-EVT'] > total_trinity['A4f-t'] else 'NO IMPROVEMENT' if total_trinity['A4f-EVT'] == total_trinity['A4f-t'] else 'WORSE'})")


# ============================================================
# SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n  Total runtime: {elapsed:.1f}s")

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'EVT-VaR with A4f Residuals (Extreme Value Theory)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'config': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'df_fixed': DF_FIXED,
        'gpd_threshold_quantile': GPD_THRESHOLD_QUANTILE,
        'seed': 42,
        'alpha_levels': ALPHA_LEVELS,
        'assets': ASSETS,
    },
    'data_source': 'yfinance',
    'references': [
        'McNeil & Frey (2000). Estimation of tail-related risk measures. J Empirical Finance.',
        'Kupiec (1995). Techniques for Verifying Risk Measurement Models.',
        'Christoffersen (1998). Evaluating Interval Forecasts.',
        'Acerbi & Szekely (2014). Back-testing Expected Shortfall.',
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility.',
        'K159: GJR+EVT Kupiec 12/12 but Trinity 3/12',
        'K988: A4f champion for SPY',
        'K995: A4f-t best VaR model (12/12 PASS)',
        'K1000: A4f-t joint MLE 6/6 VaR/ES',
    ],
    'related_experiments': ['K159', 'K536', 'K988', 'K995', 'K1000', 'K1005'],
    'results': all_results,
    'trinity_totals': total_trinity,
    'total_tests': total_tests,
    'runtime_s': round(elapsed, 1),
    'conclusion': '',  # Will be filled after analysis
}

# Generate conclusion
evts_better = total_trinity['A4f-EVT'] > total_trinity['A4f-t']
gjr_evts_better = total_trinity['GJR-EVT'] > total_trinity['GJR-t']

conclusion_parts = []
conclusion_parts.append(f"EVT-GPD on A4f residuals: Trinity {total_trinity['A4f-EVT']}/{total_tests} "
                       f"vs A4f-t {total_trinity['A4f-t']}/{total_tests}.")
conclusion_parts.append(f"EVT-GPD on GJR residuals: Trinity {total_trinity['GJR-EVT']}/{total_tests} "
                       f"vs GJR-t {total_trinity['GJR-t']}/{total_tests}.")

if evts_better:
    conclusion_parts.append("A4f-EVT IMPROVES over A4f-t Trinity pass rate.")
elif total_trinity['A4f-EVT'] == total_trinity['A4f-t']:
    conclusion_parts.append("A4f-EVT shows NO CHANGE vs A4f-t Trinity pass rate.")
else:
    conclusion_parts.append("A4f-EVT DEGRADES vs A4f-t Trinity pass rate.")

if gjr_evts_better:
    conclusion_parts.append("GJR-EVT IMPROVES over GJR-t.")
elif total_trinity['GJR-EVT'] == total_trinity['GJR-t']:
    conclusion_parts.append("GJR-EVT shows NO CHANGE vs GJR-t.")
else:
    conclusion_parts.append("GJR-EVT DEGRADES vs GJR-t.")

final_results['conclusion'] = ' '.join(conclusion_parts)

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"\n  Results saved to: {RESULTS_PATH}")
print(f"\n  Conclusion: {final_results['conclusion']}")
print(f"\nDone!")
