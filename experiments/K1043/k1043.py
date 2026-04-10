#!/usr/bin/env python3
"""
K1043: FHS-A4f VaR -- Filtered Historical Simulation vs CF-Rolling
==================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1036 showed CF-Rolling achieves 6/6 Trinity PASS -- the best VaR method.
  K905 showed FHS beat CAViaR/QuantHAR, but never compared to CF-Rolling or A4f.
  FHS (Barone-Adesi & Giannopoulos 1999) is an industry-standard VaR method
  that uses empirical distribution of GARCH-standardized residuals.

  This experiment extends K1036's 2x3 design to a 2x4 factorial:
    Model: GJR, A4f
    VaR method: Normal, Student-t(df=8), CF-Rolling(252d), FHS(252d)

  Core questions:
    1. Can FHS match CF-Rolling's 6/6 Trinity PASS?
    2. Does A4f improve FHS? (A4f+FHS vs GJR+FHS)
    3. Which non-parametric method is better? (FHS vs CF-Rolling)
    4. Is FHS stable across VIX regimes?

  FHS method:
    1. Fit GARCH to get conditional sigma_t
    2. Compute standardized residuals z_t = r_t / sigma_t
    3. From rolling window of z_t, take empirical quantile
    4. VaR_{t+1} = sigma_{t+1} * quantile(z, alpha)
    5. ES_{t+1} = sigma_{t+1} * mean(z[z <= quantile(z, alpha)])

  A4f model: tau_t = theta0 + theta1 * VIX^2_{t-1}
             sigma^2_t = tau_t * g_t
             g_t is GJR unit-variance process

  CF-Rolling: Use 252-day rolling window of standardized residuals to
              compute skewness and kurtosis, then Cornish-Fisher expansion.

Data: SPY, QQQ, GLD from yfinance (2005-2026).
OOS: 2019-01-01 onwards, window=2000, refit/63d, seed=42.

Evaluation:
  - VaR at 2.5% and 1%: Kupiec (1995) LR test
  - Christoffersen (1998) CC test
  - Basel traffic light
  - Trinity = Kupiec + CC + Basel all PASS
  - ES backtesting: Acerbi & Szekely (2014) Z-test
  - DM test on VaR violations (comparing FHS vs CF-Rolling)
  - 2x4 interaction analysis (model x method)

References:
  - Barone-Adesi & Giannopoulos (1999). "VaR without Correlations for
    Portfolios of Derivative Securities." J Futures Markets 19(5):583-602.
  - Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320
  - Kupiec (1995). J Derivatives 3:73-84
  - Christoffersen (1998). Int Econ Rev 39(4):841-862
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - K1036: A4f + CF-Rolling 6/6 Trinity PASS (best model x best VaR method)
  - K905: FHS beat CAViaR/QuantHAR

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
EXPERIMENT_ID = "K1043"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1043_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8
CF_ROLLING_WINDOW = 252
FHS_ROLLING_WINDOW = 252
ALPHA_LEVELS = [0.025, 0.01]
ASSETS = ['SPY', 'QQQ', 'GLD']

print("=" * 70)
print(f"{EXPERIMENT_ID}: FHS-A4f VaR -- Filtered Historical Simulation vs CF-Rolling")
print(f"  Models: GJR, A4f | Methods: Normal, Student-t, CF-Rolling, FHS")
print(f"  Assets: {ASSETS}")
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
        omega, alpha_p, gamma_p, beta = params
        if alpha_p + gamma_p / 2 + beta >= 0.999:
            return 1e10
        return gjr_nll_t(omega, alpha_p, gamma_p, beta, float(df), T_CONST_8, returns)

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
        theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
        if alpha_p + gamma_p / 2 + beta >= 0.999 or omega_g <= 0:
            return 1e10
        return a4f_nll_t(theta0, theta1, omega_g, alpha_p, gamma_p, beta,
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
    """Cornish-Fisher adjusted quantile.
    z_cf = z + (z^2-1)/6 * S + (z^3-3z)/24 * K - (2z^3-5z)/36 * S^2
    """
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
# VAR/ES COMPUTATION METHODS
# ============================================================

def compute_var_normal(sigma, alpha):
    """Normal VaR: VaR = sigma * z_alpha."""
    return stats.norm.ppf(alpha) * sigma


def compute_var_student_t(sigma, alpha, df=DF_FIXED):
    """Student-t VaR: VaR = sigma * t_alpha(df) * sqrt((df-2)/df)."""
    t_q = stats.t.ppf(alpha, df)
    scale = np.sqrt((df - 2) / df)
    return t_q * scale * sigma


def compute_var_cf(sigma, alpha, skewness, excess_kurtosis):
    """Cornish-Fisher VaR: VaR = sigma * z_cf."""
    z_cf = cornish_fisher_quantile(alpha, skewness, excess_kurtosis)
    return z_cf * sigma


def compute_var_fhs(sigma, alpha, z_history):
    """FHS VaR: VaR = sigma * empirical_quantile(z_history, alpha).
    Uses np.percentile on standardized residuals.
    """
    q = np.percentile(z_history, alpha * 100)
    return sigma * q


def compute_es_normal(sigma, alpha):
    """Normal ES: ES = -sigma * phi(z_alpha) / alpha."""
    z = stats.norm.ppf(alpha)
    return -sigma * stats.norm.pdf(z) / alpha


def compute_es_student_t(sigma, alpha, df=DF_FIXED):
    """Student-t ES."""
    t_q = stats.t.ppf(alpha, df)
    scale = np.sqrt((df - 2) / df)
    t_pdf = stats.t.pdf(t_q, df)
    es_factor = -(df + t_q**2) / (df - 1) * t_pdf / alpha
    return es_factor * scale * sigma


def compute_es_cf(sigma, alpha, skewness, excess_kurtosis):
    """CF-based ES using numerical integration of CF quantile function."""
    n_points = 200
    u_vals = np.linspace(1e-6, alpha, n_points)
    q_vals = np.array([cornish_fisher_quantile(u, skewness, excess_kurtosis) for u in u_vals])
    es = sigma * np.trapezoid(q_vals, u_vals) / alpha
    return es


def compute_es_fhs(sigma, alpha, z_history):
    """FHS ES: ES = sigma * mean(z[z <= quantile(z, alpha)]).
    Average of standardized residuals in the left tail.
    """
    q = np.percentile(z_history, alpha * 100)
    tail = z_history[z_history <= q]
    if len(tail) == 0:
        # Fallback: use the most extreme residual
        return sigma * np.min(z_history)
    return sigma * np.mean(tail)


# ============================================================
# BACKTESTING FUNCTIONS
# ============================================================

def kupiec_test(n_obs, n_viol, alpha_level):
    """Kupiec (1995) LR test for unconditional VaR coverage."""
    if n_obs < 100:
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
    """Christoffersen (1998) conditional coverage test."""
    n = len(violations_series)
    if n < 100:
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
    """Basel traffic light test."""
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


def es_backtest_as2014(returns_oos, var_series, es_series, alpha_level):
    """Acerbi & Szekely (2014) ES backtest.
    Z = 1/(n*alpha) * sum(r_t/ES_t * I(r_t < VaR_t)) + 1
    """
    n = len(returns_oos)
    if n < 100:
        return np.nan, np.nan, 'SKIP'

    violations_mask = returns_oos < var_series
    n_viol = violations_mask.sum()

    if n_viol == 0:
        return 0.0, np.nan, 'SKIP'

    es_safe = np.where(es_series != 0, es_series, -1e-10)

    z_stat = 1 / (n * alpha_level) * np.sum(returns_oos[violations_mask] / es_safe[violations_mask]) + 1
    p_value = stats.norm.cdf(z_stat)
    return float(z_stat), float(p_value), 'PASS' if p_value > 0.05 else 'FAIL'


def dm_test_var(returns, var1, var2, alpha_level):
    """DM test on VaR violations: compare quantile loss (tick loss).
    L_t = (alpha - I(r_t < VaR_t)) * (r_t - VaR_t)
    """
    n = len(returns)
    loss1 = np.zeros(n)
    loss2 = np.zeros(n)

    for t in range(n):
        ind1 = 1.0 if returns[t] < var1[t] else 0.0
        ind2 = 1.0 if returns[t] < var2[t] else 0.0
        loss1[t] = (alpha_level - ind1) * (returns[t] - var1[t])
        loss2[t] = (alpha_level - ind2) * (returns[t] - var2[t])

    d = loss1 - loss2
    d_mean = np.mean(d)
    d_var = np.var(d, ddof=1)
    if d_var < 1e-20:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(d_var / n)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_value)


# ============================================================
# OOS FORECASTING: GJR
# ============================================================

def oos_gjr(ret, oos_start_idx, window, refit_every, df=DF_FIXED):
    """OOS variance forecast using GJR-GARCH with periodic refitting.
    Returns: (forecasts, std_resid_at_refit_dict)
    """
    n_total = len(ret)
    n_oos = n_total - oos_start_idx
    forecasts = np.full(n_oos, np.nan)
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
            omega, alpha_p, gamma_p, beta = params
            h_series = gjr_recursion(omega, alpha_p, gamma_p, beta, train_ret)
            h_prev = h_series[-1]
            std_resid_at_refit[i] = train_ret / np.sqrt(h_series)

        if params is None:
            continue

        omega, alpha_p, gamma_p, beta = params
        u2 = ret[t-1] ** 2
        ind = 1.0 if ret[t-1] < 0 else 0.0
        h_new = max(omega + alpha_p * u2 + gamma_p * u2 * ind + beta * h_prev, 1e-10)
        forecasts[i] = h_new
        h_prev = h_new

    return forecasts, std_resid_at_refit


# ============================================================
# OOS FORECASTING: A4f
# ============================================================

def oos_a4f(ret, fear_vals, oos_start_idx, window, refit_every, df=DF_FIXED):
    """OOS variance forecast using A4f with periodic refitting.
    Returns: (forecasts, std_resid_at_refit_dict)
    """
    n_total = len(ret)
    n_oos = n_total - oos_start_idx
    forecasts = np.full(n_oos, np.nan)
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
            theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
            h_series, _, g_series = a4f_recursion(
                theta0, theta1, omega_g, alpha_p, gamma_p, beta,
                train_ret, train_fear**2
            )
            g_prev = g_series[-1]
            std_resid_at_refit[i] = train_ret / np.sqrt(h_series)

        if params is None:
            continue

        theta0, theta1, omega_g, alpha_p, gamma_p, beta = params
        # Step g_t forward
        tau_t = max(theta0 + theta1 * fear_vals[t-1]**2, 1e-16)
        u_prev_fc = ret[t-1] / np.sqrt(tau_t)
        u2_fc = u_prev_fc ** 2
        ind_fc = 1.0 if ret[t-1] < 0 else 0.0
        g_fc = max(omega_g + alpha_p * u2_fc + gamma_p * u2_fc * ind_fc + beta * g_prev, 1e-10)
        h_t = tau_t * g_fc
        forecasts[i] = h_t
        g_prev = g_fc

    return forecasts, std_resid_at_refit


# ============================================================
# FULL BACKTEST FOR ONE ASSET
# ============================================================

def run_backtest_for_asset(ticker):
    """Run full 2x4 VaR/ES comparison for one asset."""
    print(f"\n{'='*60}")
    print(f"  Processing {ticker}")
    print(f"{'='*60}")

    # ---- DATA ----
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

    # Align VIX with return dates
    vix_aligned = vix_close.reindex(dates).ffill().bfill()
    fear_vals = vix_aligned.values / 100.0  # Convert to decimal

    # OOS split
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

    # ---- GJR OOS Forecasts ----
    print(f"  Fitting GJR-GARCH(1,1)...")
    t0 = time.time()
    gjr_forecasts, gjr_std_resid_at_refit = oos_gjr(ret, oos_start_idx, WINDOW, REFIT_EVERY)
    print(f"  GJR done in {time.time()-t0:.1f}s")

    # ---- A4f OOS Forecasts ----
    print(f"  Fitting A4f-VIX...")
    t0 = time.time()
    a4f_forecasts, a4f_std_resid_at_refit = oos_a4f(ret, fear_vals, oos_start_idx, WINDOW, REFIT_EVERY)
    print(f"  A4f done in {time.time()-t0:.1f}s")

    oos_ret = ret[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    # ---- Build combined residual series for CF-Rolling and FHS ----
    models = {
        'GJR': {
            'forecasts': gjr_forecasts,
            'std_resid_at_refit': gjr_std_resid_at_refit,
        },
        'A4f': {
            'forecasts': a4f_forecasts,
            'std_resid_at_refit': a4f_std_resid_at_refit,
        },
    }

    all_results = {}
    # Store VaR series for DM test comparisons later
    var_series_store = {}

    for model_name, model_info in models.items():
        forecasts = model_info['forecasts']
        std_resid_at_refit = model_info['std_resid_at_refit']

        valid = ~np.isnan(forecasts)
        n_valid = valid.sum()
        print(f"\n  {model_name}: {n_valid}/{n_oos} valid forecasts")

        if n_valid < 200:
            print(f"  ERROR: Too few valid forecasts for {model_name}")
            continue

        sigma = np.sqrt(forecasts)

        # Build combined residual series (in-sample + OOS) for CF and FHS
        oos_std_resid = np.full(n_oos, np.nan)
        for i in range(n_oos):
            if valid[i] and forecasts[i] > 0:
                oos_std_resid[i] = oos_ret[i] / np.sqrt(forecasts[i])

        # Get initial in-sample residuals from first refit
        if len(std_resid_at_refit) > 0:
            first_key = sorted(std_resid_at_refit.keys())[0]
            initial_is_resid = std_resid_at_refit[first_key]
        else:
            initial_is_resid = np.array([])

        combined_resid = np.concatenate([initial_is_resid, oos_std_resid])
        n_is = len(initial_is_resid)

        # Descriptive stats of standardized residuals (in-sample)
        valid_resid = combined_resid[~np.isnan(combined_resid)]
        if len(valid_resid) > 100:
            desc_stats = {
                'mean': float(np.mean(valid_resid)),
                'std': float(np.std(valid_resid)),
                'skewness': float(stats.skew(valid_resid)),
                'excess_kurtosis': float(stats.kurtosis(valid_resid)),
                'n': int(len(valid_resid))
            }
            print(f"  {model_name} std resid: skew={desc_stats['skewness']:.3f}, "
                  f"ex.kurt={desc_stats['excess_kurtosis']:.3f}")
        else:
            desc_stats = {}

        # ---- Compute VaR/ES for each method and alpha level ----
        methods_list = ['Normal', 'Student-t', 'CF-Rolling', 'FHS']
        for alpha in ALPHA_LEVELS:
            for method_name in methods_list:
                key = f"{model_name}_{method_name}_{alpha}"
                var_series = np.full(n_oos, np.nan)
                es_series = np.full(n_oos, np.nan)

                for i in range(n_oos):
                    if not valid[i]:
                        continue
                    s = sigma[i]

                    if method_name == 'Normal':
                        var_series[i] = compute_var_normal(s, alpha)
                        es_series[i] = compute_es_normal(s, alpha)

                    elif method_name == 'Student-t':
                        var_series[i] = compute_var_student_t(s, alpha)
                        es_series[i] = compute_es_student_t(s, alpha)

                    elif method_name == 'CF-Rolling':
                        idx_combined = n_is + i
                        start_idx = max(0, idx_combined - CF_ROLLING_WINDOW)
                        window_resid = combined_resid[start_idx:idx_combined]
                        window_resid = window_resid[~np.isnan(window_resid)]

                        if len(window_resid) >= 60:
                            skw = stats.skew(window_resid)
                            ekurt = stats.kurtosis(window_resid)
                            skw = np.clip(skw, -3, 3)
                            ekurt = np.clip(ekurt, -2, 30)
                            var_series[i] = compute_var_cf(s, alpha, skw, ekurt)
                            es_series[i] = compute_es_cf(s, alpha, skw, ekurt)

                    elif method_name == 'FHS':
                        # FHS: use rolling window of standardized residuals
                        idx_combined = n_is + i
                        start_idx = max(0, idx_combined - FHS_ROLLING_WINDOW)
                        window_resid = combined_resid[start_idx:idx_combined]
                        window_resid = window_resid[~np.isnan(window_resid)]

                        if len(window_resid) >= 100:
                            var_series[i] = compute_var_fhs(s, alpha, window_resid)
                            es_series[i] = compute_es_fhs(s, alpha, window_resid)

                # Store VaR for DM test comparisons
                var_series_store[key] = var_series.copy()

                # ---- Backtest ----
                valid_bt = valid & ~np.isnan(var_series) & ~np.isnan(es_series)
                bt_ret = oos_ret[valid_bt]
                bt_var = var_series[valid_bt]
                bt_es = es_series[valid_bt]

                n_obs = len(bt_ret)
                violations = bt_ret < bt_var
                n_viol = violations.sum()
                vr = n_viol / n_obs if n_obs > 0 else np.nan

                kupiec_lr, kupiec_p, kupiec_result = kupiec_test(n_obs, n_viol, alpha)
                cc_lr, cc_p, cc_result = christoffersen_cc_test(violations.astype(int))
                basel_color, basel_result = basel_traffic_light(n_obs, n_viol, alpha)
                es_z, es_p, es_result = es_backtest_as2014(bt_ret, bt_var, bt_es, alpha)

                trinity = 'PASS' if (kupiec_result == 'PASS' and
                                      cc_result == 'PASS' and
                                      basel_result == 'PASS') else 'FAIL'

                result_entry = {
                    'model': model_name,
                    'method': method_name,
                    'alpha': alpha,
                    'n_obs': int(n_obs),
                    'n_violations': int(n_viol),
                    'violation_rate': round(float(vr), 6),
                    'expected_rate': alpha,
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

                all_results[key] = result_entry

                status = "PASS" if trinity == "PASS" else "FAIL"
                print(f"  {model_name}+{method_name} alpha={alpha}: "
                      f"VR={vr:.4f} (exp={alpha}) "
                      f"Kupiec={kupiec_result} CC={cc_result} Basel={basel_color} "
                      f"ES={es_result} Trinity={status}")

    # ---- DM Tests: FHS vs CF-Rolling ----
    dm_results = {}
    for model_name in ['GJR', 'A4f']:
        for alpha in ALPHA_LEVELS:
            key_fhs = f"{model_name}_FHS_{alpha}"
            key_cf = f"{model_name}_CF-Rolling_{alpha}"

            if key_fhs in var_series_store and key_cf in var_series_store:
                var_fhs = var_series_store[key_fhs]
                var_cf = var_series_store[key_cf]

                # Only compare where both are valid
                both_valid = ~np.isnan(var_fhs) & ~np.isnan(var_cf)
                if both_valid.sum() > 100:
                    dm_t, dm_p = dm_test_var(
                        oos_ret[both_valid], var_fhs[both_valid], var_cf[both_valid], alpha
                    )
                    dm_results[f"{model_name}_alpha{alpha}"] = {
                        'dm_t_stat': round(dm_t, 4),
                        'dm_p_value': round(dm_p, 4),
                        'n_compared': int(both_valid.sum()),
                        'interpretation': (
                            'FHS significantly better' if dm_t < -1.96 else
                            'CF-Rolling significantly better' if dm_t > 1.96 else
                            'No significant difference'
                        )
                    }
                    print(f"\n  DM test {model_name} FHS vs CF-Rolling alpha={alpha}: "
                          f"t={dm_t:.3f} p={dm_p:.4f} → {dm_results[f'{model_name}_alpha{alpha}']['interpretation']}")

    # ---- VIX regime analysis for FHS ----
    vix_regime_results = {}
    vix_oos = vix_aligned.values[oos_start_idx:] * 100  # back to VIX level
    for model_name in ['GJR', 'A4f']:
        for alpha in ALPHA_LEVELS:
            key_fhs = f"{model_name}_FHS_{alpha}"
            if key_fhs not in all_results:
                continue

            # Split into VIX regimes: low (<15), medium (15-25), high (>25)
            forecasts = models[model_name]['forecasts']
            valid_mask = ~np.isnan(forecasts)
            var_fhs = var_series_store.get(key_fhs)
            if var_fhs is None:
                continue

            for regime_name, (lo, hi) in [('low', (0, 15)), ('medium', (15, 25)), ('high', (25, 100))]:
                regime_mask = valid_mask & (vix_oos >= lo) & (vix_oos < hi) & ~np.isnan(var_fhs)
                n_regime = regime_mask.sum()
                if n_regime < 30:
                    continue

                regime_ret = oos_ret[regime_mask]
                regime_var = var_fhs[regime_mask]
                viols = regime_ret < regime_var
                n_viols = viols.sum()
                vr = n_viols / n_regime

                regime_key = f"{model_name}_FHS_{alpha}_{regime_name}"
                vix_regime_results[regime_key] = {
                    'model': model_name,
                    'alpha': alpha,
                    'regime': regime_name,
                    'vix_range': f"{lo}-{hi}",
                    'n_obs': int(n_regime),
                    'n_violations': int(n_viols),
                    'violation_rate': round(float(vr), 4),
                    'expected_rate': alpha,
                }

    return {
        'ticker': ticker,
        'n_total': n_total,
        'n_oos': n_oos,
        'oos_start': dates[oos_start_idx].strftime('%Y-%m-%d'),
        'results': all_results,
        'dm_tests': dm_results,
        'vix_regime': vix_regime_results,
    }


# ============================================================
# MAIN EXECUTION
# ============================================================

print("\n" + "=" * 70)
print("RUNNING FULL 2x4 BACKTEST")
print("=" * 70)

all_asset_results = {}

for ticker in ASSETS:
    result = run_backtest_for_asset(ticker)
    if result is not None:
        all_asset_results[ticker] = result

# ============================================================
# SUMMARY ANALYSIS: 2x4 Interaction Table
# ============================================================

print("\n" + "=" * 70)
print("2x4 INTERACTION ANALYSIS (Model x VaR Method)")
print("=" * 70)

models_list = ['GJR', 'A4f']
methods_list = ['Normal', 'Student-t', 'CF-Rolling', 'FHS']

# Count Trinity PASS for each combination
combinations = {}
for model in models_list:
    for method in methods_list:
        combo_key = f"{model}_{method}"
        total = 0
        passed = 0
        es_total = 0
        es_passed = 0
        for ticker in all_asset_results:
            for alpha in ALPHA_LEVELS:
                key = f"{model}_{method}_{alpha}"
                if key in all_asset_results[ticker]['results']:
                    total += 1
                    if all_asset_results[ticker]['results'][key]['trinity'] == 'PASS':
                        passed += 1
                    es_total += 1
                    if all_asset_results[ticker]['results'][key]['es'] == 'PASS':
                        es_passed += 1
        combinations[combo_key] = {
            'total_tests': total,
            'trinity_pass': passed,
            'trinity_rate': round(passed / total, 3) if total > 0 else 0,
            'es_pass': es_passed,
            'es_total': es_total,
            'es_rate': round(es_passed / es_total, 3) if es_total > 0 else 0,
        }

# Print interaction table
print(f"\n{'Combo':<25} {'Trinity PASS':<15} {'Rate':<10} {'ES PASS':<12} {'ES Rate':<10}")
print("-" * 72)
for combo in [f"{m}_{met}" for m in models_list for met in methods_list]:
    info = combinations[combo]
    print(f"{combo:<25} {info['trinity_pass']}/{info['total_tests']:<10} {info['trinity_rate']:.1%}"
          f"      {info['es_pass']}/{info['es_total']:<8} {info['es_rate']:.1%}")

# Decomposition: model effect vs method effect
print("\n--- Model Effect (averaging over methods) ---")
for model in models_list:
    total = sum(combinations[f"{model}_{m}"]['total_tests'] for m in methods_list)
    passed = sum(combinations[f"{model}_{m}"]['trinity_pass'] for m in methods_list)
    rate = passed / total if total > 0 else 0
    print(f"  {model}: {passed}/{total} = {rate:.1%}")

print("\n--- Method Effect (averaging over models) ---")
for method in methods_list:
    total = sum(combinations[f"{m}_{method}"]['total_tests'] for m in models_list)
    passed = sum(combinations[f"{m}_{method}"]['trinity_pass'] for m in models_list)
    rate = passed / total if total > 0 else 0
    print(f"  {method}: {passed}/{total} = {rate:.1%}")

# ============================================================
# DM TEST SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("DM TEST SUMMARY: FHS vs CF-Rolling")
print("=" * 70)

all_dm = {}
for ticker in all_asset_results:
    if 'dm_tests' in all_asset_results[ticker]:
        for k, v in all_asset_results[ticker]['dm_tests'].items():
            print(f"  {ticker} {k}: t={v['dm_t_stat']:.3f} p={v['dm_p_value']:.4f} "
                  f"→ {v['interpretation']}")
            all_dm[f"{ticker}_{k}"] = v

# ============================================================
# VIX REGIME STABILITY
# ============================================================

print("\n" + "=" * 70)
print("FHS VIX REGIME STABILITY")
print("=" * 70)

for ticker in all_asset_results:
    if 'vix_regime' in all_asset_results[ticker]:
        print(f"\n  {ticker}:")
        for k, v in sorted(all_asset_results[ticker]['vix_regime'].items()):
            excess = v['violation_rate'] - v['expected_rate']
            sign = '+' if excess >= 0 else ''
            print(f"    {k}: VR={v['violation_rate']:.4f} (exp={v['expected_rate']}) "
                  f"{sign}{excess:.4f} n={v['n_obs']}")


# ============================================================
# GENERATE FIGURES
# ============================================================

print("\n" + "=" * 70)
print("GENERATING FIGURES")
print("=" * 70)

# Figure 1: Trinity PASS heatmap (2x4)
fig, ax = plt.subplots(figsize=(10, 5))
heatmap_data = np.zeros((len(models_list), len(methods_list)))

for i, model in enumerate(models_list):
    for j, method in enumerate(methods_list):
        combo_key = f"{model}_{method}"
        if combo_key in combinations:
            heatmap_data[i, j] = combinations[combo_key]['trinity_rate'] * 100

im = ax.imshow(heatmap_data, cmap='RdYlGn', aspect='auto', vmin=0, vmax=100)

# Annotate cells
for i in range(len(models_list)):
    for j in range(len(methods_list)):
        combo_key = f"{models_list[i]}_{methods_list[j]}"
        info = combinations.get(combo_key, {})
        val = heatmap_data[i, j]
        text_color = 'white' if val < 40 or val > 80 else 'black'
        ax.text(j, i, f"{info.get('trinity_pass', 0)}/{info.get('total_tests', 0)}\n({val:.0f}%)",
                ha='center', va='center', fontsize=12, fontweight='bold', color=text_color)

ax.set_xticks(range(len(methods_list)))
ax.set_xticklabels(methods_list, fontsize=11)
ax.set_yticks(range(len(models_list)))
ax.set_yticklabels(models_list, fontsize=11)

cbar = plt.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label('Trinity PASS Rate (%)', fontsize=10)

ax.set_title('K1043: Trinity PASS Rate -- Model x VaR Method (2x4)\n'
             '(3 assets x 2 alpha levels = 6 tests per cell)',
             fontsize=13, fontweight='bold')
ax.set_xlabel('VaR Method', fontsize=11)
ax.set_ylabel('Volatility Model', fontsize=11)

plt.tight_layout()
fig1_path = os.path.join(SCRIPT_DIR, 'k1043_trinity_heatmap.png')
plt.savefig(fig1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig1_path}")


# Figure 2: Violation rates comparison (bar chart grouped by method)
fig, axes = plt.subplots(1, len(ASSETS), figsize=(5 * len(ASSETS), 6), sharey=True)
if len(ASSETS) == 1:
    axes = [axes]

bar_width = 0.10
colors = {
    'GJR_Normal': '#d62728',
    'GJR_Student-t': '#ff7f0e',
    'GJR_CF-Rolling': '#2ca02c',
    'GJR_FHS': '#17becf',
    'A4f_Normal': '#9467bd',
    'A4f_Student-t': '#8c564b',
    'A4f_CF-Rolling': '#1f77b4',
    'A4f_FHS': '#bcbd22',
}

for ax_idx, ticker in enumerate(ASSETS):
    ax = axes[ax_idx]
    if ticker not in all_asset_results:
        continue

    x_positions = np.arange(len(ALPHA_LEVELS))
    offset = 0

    for model in models_list:
        for method in methods_list:
            vr_vals = []
            for alpha in ALPHA_LEVELS:
                key = f"{model}_{method}_{alpha}"
                if key in all_asset_results[ticker]['results']:
                    vr_vals.append(all_asset_results[ticker]['results'][key]['violation_rate'])
                else:
                    vr_vals.append(0)

            combo_key = f"{model}_{method}"
            ax.bar(x_positions + offset * bar_width, vr_vals,
                   bar_width, label=combo_key if ax_idx == 0 else '',
                   color=colors[combo_key], alpha=0.85)
            offset += 1

    # Add expected rate lines
    for j, alpha in enumerate(ALPHA_LEVELS):
        ax.axhline(y=alpha, color='black', linestyle='--', alpha=0.5, linewidth=0.8)

    ax.set_title(ticker, fontsize=14, fontweight='bold')
    ax.set_xticks(x_positions + bar_width * 3.5)
    ax.set_xticklabels([f'{a:.1%}' for a in ALPHA_LEVELS])
    ax.set_xlabel('Alpha Level')
    if ax_idx == 0:
        ax.set_ylabel('Violation Rate')

if len(ASSETS) > 0:
    axes[0].legend(bbox_to_anchor=(0.5, -0.25), loc='upper center', ncol=4,
                   fontsize=7, frameon=True)

plt.suptitle('K1043: Violation Rates by Model x VaR Method (2x4)', fontsize=14, fontweight='bold', y=1.02)
plt.tight_layout()
fig2_path = os.path.join(SCRIPT_DIR, 'k1043_violation_rates.png')
plt.savefig(fig2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig2_path}")


# Figure 3: FHS vs CF-Rolling detail comparison
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Panel A: Trinity pass rates side by side
for ax_idx, model in enumerate(models_list):
    ax = axes[ax_idx]
    methods_compare = ['CF-Rolling', 'FHS']
    x = np.arange(len(ASSETS))
    width = 0.35

    for j, method in enumerate(methods_compare):
        pass_counts = []
        for ticker in ASSETS:
            if ticker in all_asset_results:
                count = 0
                for alpha in ALPHA_LEVELS:
                    key = f"{model}_{method}_{alpha}"
                    if key in all_asset_results[ticker]['results']:
                        if all_asset_results[ticker]['results'][key]['trinity'] == 'PASS':
                            count += 1
                pass_counts.append(count)
            else:
                pass_counts.append(0)

        color = '#2ca02c' if method == 'CF-Rolling' else '#17becf'
        ax.bar(x + j * width, pass_counts, width, label=method, color=color, alpha=0.85)

    ax.set_xticks(x + width / 2)
    ax.set_xticklabels(ASSETS, fontsize=11)
    ax.set_ylabel('Trinity PASS count (out of 2)')
    ax.set_title(f'{model} Model', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 2.5)
    ax.legend(fontsize=10)
    ax.axhline(y=2, color='gray', linestyle=':', alpha=0.5)

plt.suptitle('K1043: FHS vs CF-Rolling -- Trinity PASS per Asset',
             fontsize=13, fontweight='bold')
plt.tight_layout()
fig3_path = os.path.join(SCRIPT_DIR, 'k1043_fhs_vs_cf.png')
plt.savefig(fig3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig3_path}")


# ============================================================
# SAVE RESULTS JSON
# ============================================================

elapsed = time.time() - START_TIME

# Compile final results
final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'FHS-A4f VaR: Filtered Historical Simulation vs CF-Rolling',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'data_period': f'{DATA_START} to {DATA_END}',
    'oos_start': OOS_START,
    'assets': ASSETS,
    'config': {
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'df_fixed': DF_FIXED,
        'cf_rolling_window': CF_ROLLING_WINDOW,
        'fhs_rolling_window': FHS_ROLLING_WINDOW,
        'alpha_levels': ALPHA_LEVELS,
        'seed': 42,
    },
    'models': models_list,
    'methods': methods_list,
    'factorial_design': '2x4 (2 models x 4 VaR methods)',
    'asset_results': {},
    'interaction_table': combinations,
    'dm_tests_fhs_vs_cf': all_dm,
    'elapsed_seconds': round(elapsed, 1),
    'references': [
        'Barone-Adesi & Giannopoulos (1999). J Futures Markets 19(5):583-602.',
        'Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320.',
        'Kupiec (1995). J Derivatives 3:73-84.',
        'Christoffersen (1998). Int Econ Rev 39(4):841-862.',
        'Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.',
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
    ],
}

# Flatten asset results
for ticker in all_asset_results:
    ar = all_asset_results[ticker]
    final_results['asset_results'][ticker] = {
        'n_total': ar['n_total'],
        'n_oos': ar['n_oos'],
        'oos_start': ar['oos_start'],
        'var_backtest': ar['results'],
        'dm_tests': ar.get('dm_tests', {}),
        'vix_regime': ar.get('vix_regime', {}),
    }

# Summary statistics
total_trinity_tests = 0
total_trinity_pass = 0
total_es_tests = 0
total_es_pass = 0
for combo, info in combinations.items():
    total_trinity_tests += info['total_tests']
    total_trinity_pass += info['trinity_pass']
    total_es_tests += info['es_total']
    total_es_pass += info['es_pass']

final_results['summary'] = {
    'total_trinity_tests': total_trinity_tests,
    'total_trinity_pass': total_trinity_pass,
    'overall_trinity_rate': round(total_trinity_pass / total_trinity_tests, 3) if total_trinity_tests > 0 else 0,
    'total_es_tests': total_es_tests,
    'total_es_pass': total_es_pass,
    'overall_es_rate': round(total_es_pass / total_es_tests, 3) if total_es_tests > 0 else 0,
    'best_combination': max(combinations.items(), key=lambda x: x[1]['trinity_rate'])[0] if combinations else None,
    'fhs_trinity_rate': round(
        (combinations.get('GJR_FHS', {}).get('trinity_pass', 0) +
         combinations.get('A4f_FHS', {}).get('trinity_pass', 0)) /
        max(1, (combinations.get('GJR_FHS', {}).get('total_tests', 0) +
                combinations.get('A4f_FHS', {}).get('total_tests', 0))), 3
    ),
    'cf_rolling_trinity_rate': round(
        (combinations.get('GJR_CF-Rolling', {}).get('trinity_pass', 0) +
         combinations.get('A4f_CF-Rolling', {}).get('trinity_pass', 0)) /
        max(1, (combinations.get('GJR_CF-Rolling', {}).get('total_tests', 0) +
                combinations.get('A4f_CF-Rolling', {}).get('total_tests', 0))), 3
    ),
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\n{'='*70}")
print(f"RESULTS SAVED: {RESULTS_PATH}")
print(f"Total elapsed: {elapsed:.1f}s")
print(f"{'='*70}")

# ============================================================
# FINAL SUMMARY
# ============================================================

print(f"\n{'='*70}")
print(f"K1043 FINAL SUMMARY")
print(f"{'='*70}")
print(f"  Design: {final_results['factorial_design']}")
print(f"  Total Trinity tests: {total_trinity_tests}")
print(f"  Total Trinity PASS: {total_trinity_pass} ({total_trinity_pass/max(1,total_trinity_tests)*100:.1f}%)")
print(f"  Total ES tests: {total_es_tests}")
print(f"  Total ES PASS: {total_es_pass} ({total_es_pass/max(1,total_es_tests)*100:.1f}%)")
print(f"  FHS Trinity rate: {final_results['summary']['fhs_trinity_rate']:.1%}")
print(f"  CF-Rolling Trinity rate: {final_results['summary']['cf_rolling_trinity_rate']:.1%}")
print(f"  Best combination: {final_results['summary']['best_combination']}")
print(f"  Elapsed: {elapsed:.1f}s")
print(f"{'='*70}")
