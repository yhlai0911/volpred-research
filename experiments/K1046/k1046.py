#!/usr/bin/env python3
"""
K1046: Monte Carlo VaR with A4f -- Simulated Path VaR
=====================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1036 showed CF-Rolling achieves 6/6 Trinity PASS (best VaR method with GJR).
  K1043 showed FHS 12/12 = CF-Rolling 12/12 (identical Trinity performance).
  This experiment tests the remaining Face B VaR method: Monte Carlo simulation.

  MC-VaR uses GARCH model to simulate future return paths, then takes the
  empirical quantile of simulated returns as VaR. This is the most flexible
  approach -- it can handle multi-step forecasts, jumps, regimes.

  We compare 8 models in a 2x4 factorial design:
    Model: GJR, A4f
    VaR method: MC-Normal, MC-t(df=8), CF-Rolling(reference), FHS(reference)

  Core questions:
    1. Can MC-VaR match CF-Rolling/FHS's 100% Trinity PASS?
    2. MC-Normal vs MC-t: does distribution assumption matter in simulation?
    3. Is MC's computational cost justified (vs simpler CF-Rolling)?
    4. Does A4f MC outperform GJR MC?

  MC-VaR method (1-day):
    At time t, to compute VaR for t+1:
    1. Use fitted GARCH params + latest conditional variance h_t
    2. For each sim s = 1, ..., N_sim:
       a. Draw epsilon ~ N(0,1) or t(df)
       b. sigma^2_{t+1} = omega + alpha*r_t^2 + gamma*r_t^2*I(r_t<0) + beta*h_t
       c. r_sim = sqrt(sigma^2_{t+1}) * epsilon
    3. VaR = percentile(r_sim, alpha*100)
    4. ES = mean(r_sim[r_sim <= VaR])

  A4f MC-VaR:
    tau_{t+1} = theta0 + theta1 * VIX_t^2  (known at time t)
    g_{t+1} = omega_g + alpha*(r_t/sqrt(tau_t))^2 + ... + beta*g_t
    sigma^2_{t+1} = tau_{t+1} * g_{t+1}
    r_sim = sqrt(sigma^2_{t+1}) * epsilon

Data: SPY, QQQ from yfinance (2005-2026).
OOS: 2019-01-01 onwards, window=2000, refit/63d, seed=42.
N_sim: 10,000 per day.

Evaluation:
  - VaR at 2.5% and 1%: Kupiec (1995) LR test
  - Christoffersen (1998) CC test
  - Basel traffic light
  - Trinity = Kupiec + CC + Basel all PASS
  - ES backtesting: Acerbi & Szekely (2014) Z-test
  - 2x4 interaction analysis (model x method)

References:
  - Pritsker (2006). The Hidden Dangers of Historical Simulation. J Bank Finance.
  - Glasserman (2003). Monte Carlo Methods in Financial Engineering. Springer.
  - Barone-Adesi, Engle & Mancini (2008). A GARCH Option Pricing Model with
    Filtered Historical Simulation. RFS 21(3):1223-1258.
  - Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320
  - Kupiec (1995). J Derivatives 3:73-84
  - Christoffersen (1998). Int Econ Rev 39(4):841-862
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - K1036: A4f + CF-Rolling 6/6 Trinity PASS
  - K1043: FHS 12/12 = CF-Rolling 12/12

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

# Fixed seed for reproducibility
RNG = np.random.default_rng(42)
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1046"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1046_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8
CF_ROLLING_WINDOW = 252
FHS_ROLLING_WINDOW = 252
N_SIM = 10000
ALPHA_LEVELS = [0.025, 0.01]
ASSETS = ['SPY', 'QQQ']

print("=" * 70)
print(f"{EXPERIMENT_ID}: Monte Carlo VaR with A4f -- Simulated Path VaR")
print(f"  Models: GJR, A4f | Methods: MC-Normal, MC-t, CF-Rolling, FHS")
print(f"  Assets: {ASSETS} | N_sim: {N_SIM}")
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
    """FHS VaR: VaR = sigma * empirical_quantile(z_history, alpha)."""
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
    """FHS ES: ES = sigma * mean(z[z <= quantile(z, alpha)])."""
    q = np.percentile(z_history, alpha * 100)
    tail = z_history[z_history <= q]
    if len(tail) == 0:
        return sigma * np.min(z_history)
    return sigma * np.mean(tail)


# ============================================================
# MONTE CARLO VAR/ES (VECTORIZED)
# ============================================================

def compute_mc_var_es(sigma_forecast, alpha, n_sim, rng, dist='normal', df=DF_FIXED):
    """Monte Carlo VaR and ES using vectorized simulation.

    For 1-day MC-VaR:
      - sigma^2_{t+1} is already the GARCH forecast (deterministic given info at t)
      - We simulate r_{t+1} = sigma_{t+1} * epsilon
      - epsilon ~ N(0,1) or t(df) scaled by sqrt((df-2)/df)

    Parameters:
      sigma_forecast: float, sqrt of forecasted conditional variance
      alpha: float, VaR confidence level (e.g., 0.01)
      n_sim: int, number of simulations
      rng: numpy random Generator
      dist: 'normal' or 'student_t'
      df: degrees of freedom for student-t

    Returns:
      var_val: float (negative)
      es_val: float (negative)
    """
    if dist == 'normal':
        eps = rng.standard_normal(n_sim)
    elif dist == 'student_t':
        # Scale t draws so that Var(eps)=1
        eps = rng.standard_t(df, size=n_sim) * np.sqrt((df - 2) / df)
    else:
        raise ValueError(f"Unknown distribution: {dist}")

    # Simulated returns
    r_sim = sigma_forecast * eps

    # VaR = alpha-quantile of simulated returns
    var_val = np.percentile(r_sim, alpha * 100)

    # ES = mean of returns below VaR
    tail = r_sim[r_sim <= var_val]
    if len(tail) == 0:
        es_val = np.min(r_sim)
    else:
        es_val = np.mean(tail)

    return float(var_val), float(es_val)


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

        # Build combined residual series (in-sample + OOS) for CF/FHS
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

        # Create per-model RNG for MC (deterministic per model+asset)
        # Use different seeds for each model to avoid correlation
        mc_seed = 42 + hash(f"{ticker}_{model_name}") % (2**31)
        mc_rng = np.random.default_rng(mc_seed)

        # ---- Compute VaR/ES for each method and alpha level ----
        methods_list = ['MC-Normal', 'MC-t', 'CF-Rolling', 'FHS']

        for alpha in ALPHA_LEVELS:
            for method_name in methods_list:
                key = f"{model_name}_{method_name}_{alpha}"
                var_series = np.full(n_oos, np.nan)
                es_series = np.full(n_oos, np.nan)

                t_method = time.time()

                for i in range(n_oos):
                    if not valid[i]:
                        continue
                    s = sigma[i]

                    if method_name == 'MC-Normal':
                        var_val, es_val = compute_mc_var_es(
                            s, alpha, N_SIM, mc_rng, dist='normal')
                        var_series[i] = var_val
                        es_series[i] = es_val

                    elif method_name == 'MC-t':
                        var_val, es_val = compute_mc_var_es(
                            s, alpha, N_SIM, mc_rng, dist='student_t', df=DF_FIXED)
                        var_series[i] = var_val
                        es_series[i] = es_val

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
                        idx_combined = n_is + i
                        start_idx = max(0, idx_combined - FHS_ROLLING_WINDOW)
                        window_resid = combined_resid[start_idx:idx_combined]
                        window_resid = window_resid[~np.isnan(window_resid)]

                        if len(window_resid) >= 60:
                            var_series[i] = compute_var_fhs(s, alpha, window_resid)
                            es_series[i] = compute_es_fhs(s, alpha, window_resid)

                elapsed_method = time.time() - t_method

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
                    'elapsed_seconds': round(elapsed_method, 2),
                }

                all_results[key] = result_entry

                status = "PASS" if trinity == "PASS" else "FAIL"
                print(f"  {model_name}+{method_name} alpha={alpha}: "
                      f"VR={vr:.4f} (exp={alpha}) "
                      f"Kupiec={kupiec_result} CC={cc_result} Basel={basel_color} "
                      f"Trinity={status} [{elapsed_method:.1f}s]")

    return {
        'ticker': ticker,
        'n_total': n_total,
        'n_oos': n_oos,
        'oos_start': dates[oos_start_idx].strftime('%Y-%m-%d'),
        'results': all_results,
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
methods_list = ['MC-Normal', 'MC-t', 'CF-Rolling', 'FHS']

# Count Trinity PASS for each combination
combinations = {}
for model in models_list:
    for method in methods_list:
        combo_key = f"{model}_{method}"
        total = 0
        passed = 0
        for ticker in all_asset_results:
            for alpha in ALPHA_LEVELS:
                key = f"{model}_{method}_{alpha}"
                if key in all_asset_results[ticker]['results']:
                    total += 1
                    if all_asset_results[ticker]['results'][key]['trinity'] == 'PASS':
                        passed += 1
        combinations[combo_key] = {
            'total_tests': total,
            'trinity_pass': passed,
            'trinity_rate': round(passed / total, 3) if total > 0 else 0,
        }

# Print interaction table
print(f"\n{'Combo':<25} {'Trinity PASS':<15} {'Rate':<10}")
print("-" * 50)
for combo, info in sorted(combinations.items()):
    print(f"{combo:<25} {info['trinity_pass']}/{info['total_tests']:<10} {info['trinity_rate']:.1%}")

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

# ---- Timing comparison ----
print("\n--- Computational Cost (avg seconds per method) ---")
for method in methods_list:
    times = []
    for ticker in all_asset_results:
        for model in models_list:
            for alpha in ALPHA_LEVELS:
                key = f"{model}_{method}_{alpha}"
                if key in all_asset_results[ticker]['results']:
                    times.append(all_asset_results[ticker]['results'][key]['elapsed_seconds'])
    if times:
        print(f"  {method}: avg={np.mean(times):.1f}s, max={np.max(times):.1f}s")


# ============================================================
# GENERATE FIGURES
# ============================================================

print("\n" + "=" * 70)
print("GENERATING FIGURES")
print("=" * 70)

# Figure 1: Trinity PASS heatmap (Model x Method)
fig, ax = plt.subplots(figsize=(10, 5))
heatmap_data = np.zeros((len(models_list), len(methods_list)))

for i, model in enumerate(models_list):
    for j, method in enumerate(methods_list):
        combo = f"{model}_{method}"
        if combo in combinations:
            heatmap_data[i, j] = combinations[combo]['trinity_rate']

im = ax.imshow(heatmap_data, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto')

ax.set_xticks(np.arange(len(methods_list)))
ax.set_yticks(np.arange(len(models_list)))
ax.set_xticklabels(methods_list, fontsize=12)
ax.set_yticklabels(models_list, fontsize=12)

for i in range(len(models_list)):
    for j in range(len(methods_list)):
        combo = f"{models_list[i]}_{methods_list[j]}"
        if combo in combinations:
            info = combinations[combo]
            text = f"{info['trinity_pass']}/{info['total_tests']}\n({info['trinity_rate']:.0%})"
            text_color = 'white' if heatmap_data[i, j] < 0.5 else 'black'
            ax.text(j, i, text, ha='center', va='center',
                    fontsize=11, fontweight='bold', color=text_color)

plt.colorbar(im, ax=ax, label='Trinity PASS Rate')
ax.set_title('K1046: Trinity PASS Rate (Model x VaR Method)\nMC-VaR vs CF-Rolling vs FHS',
             fontsize=14, fontweight='bold')
ax.set_xlabel('VaR Method', fontsize=12)
ax.set_ylabel('Volatility Model', fontsize=12)
plt.tight_layout()
fig1_path = os.path.join(SCRIPT_DIR, 'k1046_trinity_heatmap.png')
plt.savefig(fig1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig1_path}")


# Figure 2: Violation rates comparison
fig, axes = plt.subplots(1, len(ASSETS), figsize=(6 * len(ASSETS), 6), sharey=True)
if len(ASSETS) == 1:
    axes = [axes]

bar_width = 0.09
colors = {
    'GJR_MC-Normal': '#d62728',
    'GJR_MC-t': '#ff7f0e',
    'GJR_CF-Rolling': '#2ca02c',
    'GJR_FHS': '#17becf',
    'A4f_MC-Normal': '#9467bd',
    'A4f_MC-t': '#8c564b',
    'A4f_CF-Rolling': '#1f77b4',
    'A4f_FHS': '#e377c2',
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
                   color=colors.get(combo_key, '#333333'), alpha=0.85)
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

plt.suptitle('K1046: Violation Rates by Model x VaR Method', fontsize=14, fontweight='bold', y=1.02)
plt.tight_layout()
fig2_path = os.path.join(SCRIPT_DIR, 'k1046_violation_rates.png')
plt.savefig(fig2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig2_path}")


# Figure 3: MC vs Non-MC timing comparison
fig, ax = plt.subplots(figsize=(8, 5))
mc_methods = ['MC-Normal', 'MC-t']
non_mc_methods = ['CF-Rolling', 'FHS']

timing_data = {}
for method in methods_list:
    times = []
    for ticker in all_asset_results:
        for model in models_list:
            for alpha in ALPHA_LEVELS:
                key = f"{model}_{method}_{alpha}"
                if key in all_asset_results[ticker]['results']:
                    times.append(all_asset_results[ticker]['results'][key]['elapsed_seconds'])
    if times:
        timing_data[method] = {
            'mean': np.mean(times),
            'max': np.max(times),
            'min': np.min(times),
        }

if timing_data:
    method_names = list(timing_data.keys())
    mean_times = [timing_data[m]['mean'] for m in method_names]
    method_colors = ['#d62728' if 'MC' in m else '#2ca02c' for m in method_names]

    bars = ax.bar(method_names, mean_times, color=method_colors, alpha=0.85, edgecolor='black')
    ax.set_ylabel('Average Time (seconds)', fontsize=12)
    ax.set_title('K1046: Computational Cost -- MC vs Non-MC Methods', fontsize=14, fontweight='bold')

    for bar, val in zip(bars, mean_times):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.1,
                f'{val:.1f}s', ha='center', va='bottom', fontsize=10, fontweight='bold')

    ax.set_xlabel('VaR Method', fontsize=12)

plt.tight_layout()
fig3_path = os.path.join(SCRIPT_DIR, 'k1046_timing_comparison.png')
plt.savefig(fig3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig3_path}")


# ============================================================
# SAVE RESULTS
# ============================================================

elapsed = time.time() - START_TIME

results_json = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Monte Carlo VaR with A4f -- Simulated Path VaR',
    'date': datetime.now(timezone.utc).isoformat(),
    'configuration': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'df_fixed': DF_FIXED,
        'cf_rolling_window': CF_ROLLING_WINDOW,
        'fhs_rolling_window': FHS_ROLLING_WINDOW,
        'n_sim': N_SIM,
        'alpha_levels': ALPHA_LEVELS,
        'assets': ASSETS,
        'seed': 42,
    },
    'models': {
        'GJR': 'GJR-GARCH(1,1) with Student-t(df=8) innovations',
        'A4f': 'A4f-VIX: tau_t = theta0 + theta1*VIX^2_{t-1}, sigma^2 = tau*g (multiplicative)',
    },
    'var_methods': {
        'MC-Normal': f'Monte Carlo VaR: {N_SIM} simulations with N(0,1) shocks',
        'MC-t': f'Monte Carlo VaR: {N_SIM} simulations with t({DF_FIXED}) shocks (scaled)',
        'CF-Rolling': 'VaR = sigma * z_cf (CF with 252d rolling moments) [reference]',
        'FHS': 'Filtered Historical Simulation (252d rolling residuals) [reference]',
    },
    'asset_results': all_asset_results,
    'interaction_analysis': {
        'combinations': combinations,
    },
    'references': [
        'Pritsker (2006). The Hidden Dangers of Historical Simulation. J Bank Finance',
        'Glasserman (2003). Monte Carlo Methods in Financial Engineering. Springer',
        'Barone-Adesi, Engle & Mancini (2008). A GARCH Option Pricing Model with FHS. RFS 21(3):1223-1258',
        'Barone-Adesi & Giannopoulos (1999). J Futures Markets 19(5):583-602',
        'Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320',
        'Kupiec (1995). J Derivatives 3:73-84',
        'Christoffersen (1998). Int Econ Rev 39(4):841-862',
        'Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk',
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797',
        'K1036: A4f + CF-Rolling 6/6 Trinity PASS',
        'K1043: FHS 12/12 = CF-Rolling 12/12',
    ],
    'figures': [
        'k1046_trinity_heatmap.png',
        'k1046_violation_rates.png',
        'k1046_timing_comparison.png',
    ],
    'elapsed_seconds': round(elapsed, 1),
    'data_source': 'yfinance',
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)

print(f"\n{'='*70}")
print(f"Results saved to {RESULTS_PATH}")
print(f"Elapsed: {elapsed:.1f}s")
print(f"{'='*70}")

# ============================================================
# FINAL SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("FINAL SUMMARY")
print("=" * 70)

print(f"\n{'Model+Method':<25} {'Trinity PASS':<15} {'Rate'}")
print("-" * 55)
for combo in sorted(combinations.keys()):
    info = combinations[combo]
    marker = " <-- BEST" if info['trinity_rate'] == 1.0 else ""
    print(f"{combo:<25} {info['trinity_pass']}/{info['total_tests']:<10} "
          f"{info['trinity_rate']:.1%}{marker}")

# Check what achieves 100%
best_combo = max(combinations.items(), key=lambda x: x[1]['trinity_rate'])
print(f"\nBest combination: {best_combo[0]} ({best_combo[1]['trinity_rate']:.0%})")

# MC vs non-MC summary
mc_total = sum(combinations[f"{m}_{method}"]['total_tests']
               for m in models_list for method in mc_methods)
mc_passed = sum(combinations[f"{m}_{method}"]['trinity_pass']
                for m in models_list for method in mc_methods)
nonmc_total = sum(combinations[f"{m}_{method}"]['total_tests']
                  for m in models_list for method in non_mc_methods)
nonmc_passed = sum(combinations[f"{m}_{method}"]['trinity_pass']
                   for m in models_list for method in non_mc_methods)

print(f"\nMC methods: {mc_passed}/{mc_total} = {mc_passed/mc_total:.1%}" if mc_total > 0 else "")
print(f"Non-MC methods: {nonmc_passed}/{nonmc_total} = {nonmc_passed/nonmc_total:.1%}" if nonmc_total > 0 else "")

print(f"\nDone! Elapsed: {elapsed:.1f}s")
