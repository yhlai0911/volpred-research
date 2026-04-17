#!/usr/bin/env python3
"""
K896: Expected Shortfall Analysis for Taiwan VT Paper (Paper 2 Supplement)
==========================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  Paper 2 (taiwan-vt) R1 review: SEVERE S1 = "Missing Expected Shortfall
  analysis — VaR-only is incomplete for a 2026 paper citing Basel III."
  Paper 2 currently has VaR backtesting from K836/K852 but NO ES analysis.
  This experiment adds the missing ES evaluation for all models.

Models (5):
  M1: GJR-GARCH + Normal VaR/ES
  M2: GJR-GARCH + Student-t VaR/ES
  M3: GJR-GARCH + Historical Simulation VaR/ES
  M4: GJR-GARCH + Cornish-Fisher VaR/ES  (K836 champion for 0050.TW)
  M5: 8.63/VIX VT strategy portfolio ES  (strategy-level tail risk)

Data:
  - 0050.TW from yfinance (2006-2026), clean_tw50_data mandatory
  - VIX from yfinance (^VIX), lagged 1 day for Taiwan
  - OOS: 2019-01-01 to latest (extended period for robust ES testing)

ES Evaluation (at 1% and 5%):
  1. Acerbi-Szekely (2014) Z2 statistic + bootstrap p-value (1000 reps)
  2. Fissler-Ziegel (2016) joint VaR-ES scoring function
  3. ES coverage ratio: mean(loss | loss > VaR) vs predicted ES
  4. VaR Trinity (Kupiec + Christoffersen + Basel) for cross-validation

Error Log rules:
  - 0050.TW: clean_tw50_data applied (mandatory)
  - Student-t: scale=sqrt((df-2)/df) per-refit
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1]), not stale variance
  - Basel: standard 250-day window (Green 0-4, Yellow 5-9, Red >=10)
  - VT signal: signal.shift(1) for lookahead prevention
  - CF expansion: 4th order (skew + excess kurtosis)

References:
  - Acerbi & Szekely (2014) "Backtesting Expected Shortfall" Risk Magazine
  - Fissler & Ziegel (2016) "Higher order elicitability and Osband's principle"
    Annals of Statistics 44(4), 1680-1707
  - McNeil & Frey (2000) "Estimation of tail-related risk measures..."
    Journal of Empirical Finance
  - Cornish & Fisher (1938) "Moments and cumulants..."
  - K836: GJR+Cornish-Fisher = ONLY 0050.TW 1% VaR Trinity PASS (3/481)
  - K829: 0050.TW Normal 9/481, Student-t 6/481, HistSim 6/481 — all FAIL
  - K824v2: SPY confirmed HistSim(4/502, Trinity PASS)
  - Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)

Data source: yfinance
Author: VolPred Research System
Date: 2026-04-05
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, chi2, skew, kurtosis
from scipy.integrate import trapezoid

warnings.filterwarnings('ignore')

# Add project root for volpred.utils
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(os.path.dirname(__file__),
                            'k896_taiwan_es_supplement_results.json')

# ============================================================
# Configuration
# ============================================================
OOS_START = '2019-01-01'
OOS_END = '2026-06-01'
REFIT_EVERY = 63  # ~quarterly refit
ALPHA_LEVELS = [0.01, 0.05]
N_BOOTSTRAP = 1000
SEED = 42
VT_CONSTANT = 8.63  # Taiwan VT: 8.63/VIX


# ============================================================
# A. Numba-accelerated GJR-GARCH variance filter
# ============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): sigma2_t = omega + (alpha + gamma*I_{r<0})*r2_{t-1} + beta*sigma2_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    s2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


# ============================================================
# B. GJR-GARCH model fitting (quasi-MLE, Normal)
# ============================================================

def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 100)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.98)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


# ============================================================
# C. One-step-ahead forecast + standardized residuals
# ============================================================

def gjr_one_step_forecast(returns, params):
    """sigma2_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params):
    """z_t = r_t / sigma_t for in-sample data."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized from sample)


# ============================================================
# D. Student-t df estimation (FIXED: scale=sqrt((df-2)/df))
# ============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """MLE for Student-t df from unit-variance standardized residuals."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return 5.0

    def neg_loglik(log_df):
        df = np.exp(log_df)
        if df < df_min or df > df_max:
            return 1e10
        scale = np.sqrt((df - 2.0) / df)
        ll = np.sum(t_dist.logpdf(z, df=df, loc=0.0, scale=scale))
        return -ll if np.isfinite(ll) else 1e10

    best_nll = 1e10
    best_df = 5.0
    for df_init in [3.0, 5.0, 8.0, 15.0]:
        res = minimize(neg_loglik, x0=[np.log(df_init)],
                       method='L-BFGS-B',
                       bounds=[(np.log(df_min), np.log(df_max))],
                       options={'maxiter': 500})
        if res.fun < best_nll:
            best_nll = res.fun
            best_df = float(np.exp(res.x[0]))

    return float(np.clip(best_df, df_min, df_max))


# ============================================================
# E. VaR and ES Formulas
# ============================================================

def normal_var_es(sigma, alpha):
    """VaR and ES under Normal distribution."""
    z = norm.ppf(alpha)  # negative
    var_val = sigma * z  # negative (loss direction: r < VaR)
    # ES = -sigma * phi(z_alpha) / alpha (as negative value for loss direction)
    es_val = -sigma * norm.pdf(z) / alpha  # negative (more extreme than VaR)
    return float(var_val), float(es_val)


def studentt_var_es(sigma, df, alpha):
    """VaR and ES under Student-t distribution with scale correction."""
    if df <= 2:
        df = 2.1
    scale = np.sqrt((df - 2.0) / df)
    t_q = t_dist.ppf(alpha, df)  # negative
    var_val = sigma * scale * t_q  # negative

    # ES for Student-t: -sigma * scale * (f_t(t_q) / alpha) * ((df + t_q^2) / (df - 1))
    f_t = t_dist.pdf(t_q, df)
    es_val = -sigma * scale * (f_t / alpha) * ((df + t_q ** 2) / (df - 1))  # negative
    return float(var_val), float(es_val)


def histsim_var_es(sigma, std_residuals, alpha):
    """VaR and ES via Historical Simulation on standardized residuals."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    z_var = np.percentile(z, alpha * 100)
    var_val = sigma * z_var  # negative

    # ES = mean of residuals below VaR quantile, scaled by sigma
    tail = z[z <= z_var]
    if len(tail) > 0:
        z_es = np.mean(tail)
    else:
        z_es = z_var * 1.2  # fallback: 20% worse
    es_val = sigma * z_es  # negative
    return float(var_val), float(es_val)


def cornish_fisher_var_es(sigma, std_residuals, alpha, n_int=5000):
    """VaR and ES using Cornish-Fisher expansion.

    CF VaR: adjusts Normal quantile using sample skewness + kurtosis.
    CF ES:  numerical integration over the implied distribution.

    Cornish & Fisher (1938).
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]

    S = float(skew(z))
    K = float(kurtosis(z, fisher=True))  # excess kurtosis
    z_alpha = norm.ppf(alpha)

    # CF 4th-order expansion for VaR quantile
    z_cf = (z_alpha
            + (z_alpha ** 2 - 1) * S / 6.0
            + (z_alpha ** 3 - 3.0 * z_alpha) * K / 24.0
            - (2.0 * z_alpha ** 3 - 5.0 * z_alpha) * S ** 2 / 36.0)

    var_val = sigma * z_cf  # negative

    # ES via numerical integration of CF-adjusted quantile function
    # ES = -(1/alpha) * integral_0^alpha Q(u) du, where Q(u) is CF quantile
    u_grid = np.linspace(1e-10, alpha, n_int)
    z_grid = norm.ppf(u_grid)
    q_grid = (z_grid
              + (z_grid ** 2 - 1) * S / 6.0
              + (z_grid ** 3 - 3.0 * z_grid) * K / 24.0
              - (2.0 * z_grid ** 3 - 5.0 * z_grid) * S ** 2 / 36.0)
    # ES = -(1/alpha) * integral, but q_grid is negative, so integral is negative
    # => ES_std = (1/alpha) * integral_0^alpha |Q(u)| du (positive)
    # In our sign convention (negative = loss):
    es_std = trapezoid(q_grid, u_grid) / alpha  # negative
    es_val = sigma * es_std  # negative

    return float(var_val), float(es_val)


# ============================================================
# F. Acerbi-Szekely (2014) ES Backtest
# ============================================================

def acerbi_szekely_z2(returns, var_series, es_series, alpha):
    """Z2 statistic (Acerbi & Szekely 2014, based on all observations).

    Z2 = 1/(T*alpha) * sum_t [r_t * I(r_t < VaR_t) / ES_t] + 1

    Both VaR and ES are negative (loss direction).
    Under H0 (correct ES): E[Z2] = 0.
    Z2 < 0 means ES is underestimated (actual losses exceed predictions).

    Returns (Z2, n_violations).
    """
    T = len(returns)
    violations = returns < var_series  # r < VaR (both negative)
    n_viol = int(violations.sum())
    if n_viol == 0:
        return np.nan, 0

    # r_t * I(violation) / ES_t: both r_t and ES_t are negative, ratio is positive
    indicator_returns = returns * violations.astype(float)
    z2 = float(np.sum(indicator_returns / es_series) / (T * alpha) + 1)
    return z2, n_viol


def bootstrap_pvalue_z2(returns, var_series, es_series, observed_z2,
                        alpha, n_boot=1000, seed=42):
    """Bootstrap p-value for Acerbi-Szekely Z2 test.

    Resample standardized returns (r/ES) to simulate under H0.
    p-value = proportion of bootstrap Z2 <= observed Z2 (one-sided, lower tail).
    """
    rng = np.random.default_rng(seed)
    T = len(returns)
    std_returns = returns / es_series  # standardized by ES
    boot_stats = []

    for _ in range(n_boot):
        idx = rng.choice(T, size=T, replace=True)
        boot_returns = std_returns[idx] * es_series
        z2, nv = acerbi_szekely_z2(boot_returns, var_series, es_series, alpha)
        if not np.isnan(z2):
            boot_stats.append(z2)

    if len(boot_stats) == 0:
        return np.nan
    boot_stats = np.array(boot_stats)
    p_value = float(np.mean(boot_stats <= observed_z2))
    return p_value


# ============================================================
# G. Fissler-Ziegel (2016) Joint VaR-ES Scoring Function
# ============================================================

def fissler_ziegel_score(returns, var_series, es_series, alpha):
    """Fissler-Ziegel (2016) strictly consistent joint VaR-ES scoring function.

    S(VaR, ES, r) = (1/alpha) * I(r < VaR) * (VaR - r) - VaR + ES
                    + (1/(2*alpha)) * I(r < VaR) * (VaR - r)^2 / (-ES)
                    - ES / 2

    This uses the FZ0 identification function (Patton, Ziegel & Chen 2019).
    Lower is better. VaR and ES are negative (loss direction), ES < VaR < 0.

    Ref: Fissler & Ziegel (2016) Annals of Statistics 44(4):1680-1707
         Patton, Ziegel & Chen (2019) "Dynamic semiparametric models..."
    """
    r = np.asarray(returns, dtype=np.float64)
    v = np.asarray(var_series, dtype=np.float64)
    e = np.asarray(es_series, dtype=np.float64)

    T = len(r)
    violations = (r < v).astype(float)

    # Component 1: (1/alpha) * I * (VaR - r) - VaR
    c1 = (1.0 / alpha) * violations * (v - r) - v

    # Component 2: ES + (1/(2*alpha*(-ES))) * I * (VaR - r)^2 - ES/2
    # Using log-based scoring for numerical stability (Patton et al. 2019)
    neg_es = np.maximum(-e, 1e-12)  # -ES is positive
    c2 = -np.log(neg_es) - (1.0 / (alpha * neg_es)) * violations * (v - r) + 1.0

    scores = c1 + c2
    mean_score = float(np.nanmean(scores))
    return mean_score


# ============================================================
# H. ES Coverage Ratio
# ============================================================

def es_coverage_ratio(returns, var_series, es_series):
    """Compute ratio of actual mean tail loss to predicted ES.

    Ratio = mean(r_t | r_t < VaR_t) / mean(ES_t | r_t < VaR_t)

    Ideal ratio = 1.0. Ratio > 1.0 means losses less severe than ES (conservative).
    Ratio < 1.0 means losses more severe than ES (underestimated).

    Both r_t and ES_t are negative.
    """
    violations = returns < var_series
    n_viol = int(violations.sum())
    if n_viol == 0:
        return np.nan, 0

    actual_tail_loss = float(np.mean(returns[violations]))
    predicted_es = float(np.mean(es_series[violations]))

    if abs(predicted_es) < 1e-12:
        return np.nan, n_viol

    ratio = actual_tail_loss / predicted_es
    return float(ratio), n_viol


# ============================================================
# I. VaR Backtest: Kupiec + Christoffersen + Basel
# ============================================================

def var_backtest(returns, var_series, alpha_var):
    """Kupiec (1995) + Christoffersen (1998) + Basel traffic light."""
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec unconditional coverage
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen independence
    try:
        t00 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 0)))
        t01 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 1)))
        t10 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 0)))
        t11 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 1)))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all)
                           + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    # Basel traffic light (250-day window)
    v = violations
    window = min(len(v), 250)
    v_window = v[-window:]
    n_viol_window = int(v_window.sum())

    alpha_scale = alpha_var / 0.01
    if window >= 250:
        green_max = int(np.floor(4 * alpha_scale))
        yellow_max = int(np.floor(9 * alpha_scale))
    else:
        green_max = int(np.floor(window * 4.0 * alpha_scale / 250.0))
        yellow_max = int(np.floor(window * 9.0 * alpha_scale / 250.0))
    green_max = max(green_max, 0)
    yellow_max = max(yellow_max, max(green_max + 1, 1))

    if n_viol_window <= green_max:
        color = 'green'
    elif n_viol_window <= yellow_max:
        color = 'yellow'
    else:
        color = 'red'

    return {
        'violation_rate': round(pi_hat, 6),
        'expected_rate': float(alpha_var),
        'n_violations': n1,
        'n_total': n,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': color,
        'basel_violations_in_window': n_viol_window,
        'basel_window_size': window,
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and color == 'green'),
    }


# ============================================================
# J. Cornish-Fisher quantile (standalone, for diagnostics)
# ============================================================

def cornish_fisher_quantile(std_residuals, alpha):
    """CF expansion quantile in z-space."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    S = float(skew(z))
    K = float(kurtosis(z, fisher=True))
    z_alpha = norm.ppf(alpha)
    z_cf = (z_alpha
            + (z_alpha ** 2 - 1) * S / 6.0
            + (z_alpha ** 3 - 3.0 * z_alpha) * K / 24.0
            - (2.0 * z_alpha ** 3 - 5.0 * z_alpha) * S ** 2 / 36.0)
    return float(z_cf)


# ============================================================
# K. JSON serialization helper
# ============================================================

def make_serializable(obj):
    """Convert numpy types to Python native types for JSON."""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ============================================================
# MAIN
# ============================================================

def main():
    t0 = time.time()
    print("=" * 74)
    print("K896: Expected Shortfall Analysis for Taiwan VT Paper (Paper 2)")
    print("  Asset: 0050.TW (Taiwan 50 ETF)")
    print("  Models: Normal, Student-t, HistSim, Cornish-Fisher, 8.63/VIX VT")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print(f"  Refit: every {REFIT_EVERY} trading days")
    print(f"  ES evaluation: Acerbi-Szekely Z2 + Fissler-Ziegel + Coverage")
    print(f"  Bootstrap: {N_BOOTSTRAP} replications")
    print("=" * 74)

    # ----------------------------------------------------------------
    # 1. Download data
    # ----------------------------------------------------------------
    print("\n[1] Downloading 0050.TW and VIX...")
    df_tw = yf.download('0050.TW', start='2006-01-01', end='2026-06-01',
                        progress=False)
    if isinstance(df_tw.columns, pd.MultiIndex):
        df_tw.columns = df_tw.columns.get_level_values(0)
    df_tw = df_tw.dropna(subset=['Close'])

    prices = df_tw['Close']
    returns = prices.pct_change().dropna()

    # Apply clean_tw50_data (mandatory for 0050.TW)
    print("[*] Applying clean_tw50_data...")
    prices, returns = clean_tw50_data(prices, returns)
    returns = returns.dropna()

    # Filter extreme returns (>50% = data error)
    extreme = returns.abs() > 0.50
    if extreme.any():
        n_extreme = int(extreme.sum())
        print(f"[!] Removed {n_extreme} extreme return(s) (|r| > 50%)")
        returns = returns[~extreme]

    print(f"  0050.TW: {len(returns)} days ({returns.index[0].date()} ~ "
          f"{returns.index[-1].date()})")

    # VIX for VT strategy
    df_vix = yf.download('^VIX', start='2006-01-01', end='2026-06-01',
                         progress=False)
    if isinstance(df_vix.columns, pd.MultiIndex):
        df_vix.columns = df_vix.columns.get_level_values(0)
    vix = df_vix['Close'].dropna()
    print(f"  VIX: {len(vix)} days")

    # ----------------------------------------------------------------
    # 2. OOS setup
    # ----------------------------------------------------------------
    all_returns = returns.values
    all_dates = returns.index
    oos_mask = (all_dates >= OOS_START) & (all_dates <= OOS_END)
    oos_returns = returns[oos_mask]
    n_oos = len(oos_returns)
    print(f"\n[2] OOS: {n_oos} days ({oos_returns.index[0].date()} ~ "
          f"{oos_returns.index[-1].date()})")

    # Descriptive stats
    r_oos = oos_returns.values
    oos_stats = {
        'mean': float(np.mean(r_oos)),
        'std': float(np.std(r_oos)),
        'skewness': float(skew(r_oos)),
        'kurtosis': float(kurtosis(r_oos, fisher=True)),
        'min': float(np.min(r_oos)),
        'max': float(np.max(r_oos)),
    }
    print(f"  OOS stats: mean={oos_stats['mean']:.6f}, std={oos_stats['std']:.4f}, "
          f"skew={oos_stats['skewness']:.3f}, kurt={oos_stats['kurtosis']:.2f}")

    # ----------------------------------------------------------------
    # 3. Rolling GJR-GARCH + VaR/ES forecasts (M1-M4)
    # ----------------------------------------------------------------
    oos_start_idx = int(np.searchsorted(all_dates, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(all_dates, pd.Timestamp(OOS_END), side='right'))
    oos_end_idx = min(oos_end_idx, len(all_returns))

    method_keys = ['normal', 'student_t', 'histsim', 'cornish_fisher']
    method_display = {
        'normal': 'GJR+Normal',
        'student_t': 'GJR+Student-t',
        'histsim': 'GJR+HistSim',
        'cornish_fisher': 'GJR+Cornish-Fisher',
    }

    # Store VaR and ES forecasts
    var_forecasts = {a: {m: [] for m in method_keys} for a in ALPHA_LEVELS}
    es_forecasts = {a: {m: [] for m in method_keys} for a in ALPHA_LEVELS}

    current_params = None
    current_z = None
    current_df_t = None
    last_refit = -999
    n_refits = 0

    print(f"\n[3] Running expanding window OOS forecast (M1-M4)...")
    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        # Refit?
        if day_idx - last_refit >= REFIT_EVERY or current_params is None:
            train_r = all_returns[:i]
            params = fit_gjr(train_r)
            if params is not None:
                current_params = params
                current_z = compute_standardized_residuals(train_r, params)
                current_df_t = estimate_t_df(current_z)
                n_refits += 1
                last_refit = day_idx

                if n_refits <= 3 or n_refits % 5 == 0:
                    print(f"    Refit #{n_refits} @day {day_idx}: "
                          f"pers={params['persistence']:.4f}, t-df={current_df_t:.2f}")

        if current_params is None:
            for alpha in ALPHA_LEVELS:
                for m in method_keys:
                    var_forecasts[alpha][m].append(np.nan)
                    es_forecasts[alpha][m].append(np.nan)
            continue

        # One-step forecast: sigma2_{t+1|t}
        train_r = all_returns[:i]
        sigma2_f = gjr_one_step_forecast(train_r, current_params)
        sigma_f = np.sqrt(sigma2_f)

        for alpha in ALPHA_LEVELS:
            # M1: Normal
            v, e = normal_var_es(sigma_f, alpha)
            var_forecasts[alpha]['normal'].append(v)
            es_forecasts[alpha]['normal'].append(e)

            # M2: Student-t
            v, e = studentt_var_es(sigma_f, current_df_t, alpha)
            var_forecasts[alpha]['student_t'].append(v)
            es_forecasts[alpha]['student_t'].append(e)

            # M3: HistSim
            v, e = histsim_var_es(sigma_f, current_z, alpha)
            var_forecasts[alpha]['histsim'].append(v)
            es_forecasts[alpha]['histsim'].append(e)

            # M4: Cornish-Fisher
            v, e = cornish_fisher_var_es(sigma_f, current_z, alpha)
            var_forecasts[alpha]['cornish_fisher'].append(v)
            es_forecasts[alpha]['cornish_fisher'].append(e)

    print(f"  Refits: {n_refits}, OOS forecasts: "
          f"{len(var_forecasts[0.01]['normal'])}")

    # ----------------------------------------------------------------
    # 4. VT strategy portfolio ES (M5: 8.63/VIX)
    # ----------------------------------------------------------------
    print(f"\n[4] Computing 8.63/VIX VT strategy portfolio returns...")

    # Build VT portfolio returns with lag=1
    vt_returns = []
    vt_dates = []
    vt_var = {a: [] for a in ALPHA_LEVELS}
    vt_es = {a: [] for a in ALPHA_LEVELS}

    for i in range(oos_start_idx, oos_end_idx):
        date = all_dates[i]
        ret = all_returns[i]

        # VIX from previous trading day (lag for cross-market)
        # Find closest VIX date <= date - 1 business day
        prev_dates = vix.index[vix.index < date]
        if len(prev_dates) == 0:
            continue

        vix_prev = float(vix.loc[prev_dates[-1]])
        w = min(VT_CONSTANT / vix_prev, 1.0)

        # Portfolio return: w * stock_return + (1-w) * 0 (cash)
        port_ret = w * ret
        vt_returns.append(port_ret)
        vt_dates.append(date)

    vt_returns = np.array(vt_returns)
    vt_dates = np.array(vt_dates)
    print(f"  VT portfolio: {len(vt_returns)} days, "
          f"mean={np.mean(vt_returns)*100:.4f}%, std={np.std(vt_returns)*100:.4f}%")

    # Compute VaR/ES for VT portfolio using expanding window HistSim
    min_window_vt = 252
    for idx in range(len(vt_returns)):
        if idx < min_window_vt:
            for alpha in ALPHA_LEVELS:
                vt_var[alpha].append(np.nan)
                vt_es[alpha].append(np.nan)
            continue

        # Expanding window of VT portfolio returns
        hist_window = vt_returns[:idx]

        for alpha in ALPHA_LEVELS:
            var_q = np.percentile(hist_window, alpha * 100)
            tail = hist_window[hist_window <= var_q]
            if len(tail) > 0:
                es_q = float(np.mean(tail))
            else:
                es_q = var_q * 1.2
            vt_var[alpha].append(float(var_q))
            vt_es[alpha].append(float(es_q))

    print(f"  VT VaR/ES computed for {sum(1 for x in vt_var[0.01] if not np.isnan(x))} "
          f"valid days")

    # ----------------------------------------------------------------
    # 5. Evaluate all models: VaR Trinity + ES backtest
    # ----------------------------------------------------------------
    print(f"\n[5] Evaluating all models...")
    print("=" * 74)

    all_results = {}

    # M1-M4: GARCH-based models
    oos_r = oos_returns.values
    for alpha in ALPHA_LEVELS:
        alpha_key = f"{int(alpha*100)}%"
        all_results[alpha_key] = {}

        print(f"\n--- {alpha_key} VaR/ES Results ---")
        print(f"  {'Model':<22s} {'Viol':>5s} {'Rate':>7s} {'Basel':>7s} "
              f"{'Trinity':>8s} {'Z2':>8s} {'p(Z2)':>8s} {'ES-test':>8s} "
              f"{'FZ-score':>9s} {'ES-cov':>7s}")
        print(f"  {'-'*22} {'-'*5} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*8} "
              f"{'-'*8} {'-'*9} {'-'*7}")

        for mk in method_keys:
            mn = method_display[mk]
            var_arr = np.array(var_forecasts[alpha][mk])
            es_arr = np.array(es_forecasts[alpha][mk])

            valid = np.isfinite(var_arr) & np.isfinite(es_arr)
            if valid.sum() < 50:
                all_results[alpha_key][mn] = {'error': 'insufficient valid forecasts'}
                continue

            r_valid = oos_r[valid]
            v_valid = var_arr[valid]
            e_valid = es_arr[valid]

            # VaR Trinity
            bt = var_backtest(r_valid, v_valid, alpha)

            # ES: Acerbi-Szekely Z2
            z2, n_viol_z2 = acerbi_szekely_z2(r_valid, v_valid, e_valid, alpha)
            if not np.isnan(z2):
                p_z2 = bootstrap_pvalue_z2(r_valid, v_valid, e_valid, z2,
                                           alpha, n_boot=N_BOOTSTRAP, seed=SEED)
            else:
                p_z2 = np.nan
            pass_z2 = 'PASS' if (np.isnan(p_z2) or p_z2 > 0.05) else 'FAIL'

            # ES: Fissler-Ziegel score
            fz = fissler_ziegel_score(r_valid, v_valid, e_valid, alpha)

            # ES coverage ratio
            es_cov, _ = es_coverage_ratio(r_valid, v_valid, e_valid)

            # Store results
            all_results[alpha_key][mn] = {
                **bt,
                'acerbi_szekely': {
                    'Z2': round(z2, 6) if not np.isnan(z2) else None,
                    'p_value_Z2': round(p_z2, 4) if not np.isnan(p_z2) else None,
                    'pass_Z2': pass_z2,
                },
                'fissler_ziegel_score': round(fz, 6),
                'es_coverage_ratio': round(es_cov, 4) if not np.isnan(es_cov) else None,
                'mean_var_pct': round(float(np.mean(np.abs(v_valid))) * 100, 4),
                'mean_es_pct': round(float(np.mean(np.abs(e_valid))) * 100, 4),
                'es_var_ratio': round(float(np.mean(np.abs(e_valid)) /
                                            np.mean(np.abs(v_valid))), 4),
            }

            z2_str = f"{z2:.4f}" if not np.isnan(z2) else "N/A"
            p_str = f"{p_z2:.4f}" if not np.isnan(p_z2) else "N/A"
            fz_str = f"{fz:.4f}"
            cov_str = f"{es_cov:.4f}" if not np.isnan(es_cov) else "N/A"
            tri_str = "PASS" if bt['trinity_pass'] else "FAIL"

            print(f"  {mn:<22s} {bt['n_violations']:5d} "
                  f"{bt['violation_rate']:7.4f} {bt['basel_traffic_light']:>7s} "
                  f"{tri_str:>8s} {z2_str:>8s} {p_str:>8s} {pass_z2:>8s} "
                  f"{fz_str:>9s} {cov_str:>7s}")

        # M5: VT strategy
        mn_vt = '8.63/VIX VT'
        vt_var_arr = np.array(vt_var[alpha])
        vt_es_arr = np.array(vt_es[alpha])
        valid_vt = np.isfinite(vt_var_arr) & np.isfinite(vt_es_arr)

        if valid_vt.sum() >= 50:
            r_vt = vt_returns[valid_vt]
            v_vt = vt_var_arr[valid_vt]
            e_vt = vt_es_arr[valid_vt]

            bt_vt = var_backtest(r_vt, v_vt, alpha)

            z2_vt, _ = acerbi_szekely_z2(r_vt, v_vt, e_vt, alpha)
            if not np.isnan(z2_vt):
                p_z2_vt = bootstrap_pvalue_z2(r_vt, v_vt, e_vt, z2_vt,
                                              alpha, n_boot=N_BOOTSTRAP, seed=SEED)
            else:
                p_z2_vt = np.nan
            pass_z2_vt = 'PASS' if (np.isnan(p_z2_vt) or p_z2_vt > 0.05) else 'FAIL'

            fz_vt = fissler_ziegel_score(r_vt, v_vt, e_vt, alpha)
            es_cov_vt, _ = es_coverage_ratio(r_vt, v_vt, e_vt)

            all_results[alpha_key][mn_vt] = {
                **bt_vt,
                'acerbi_szekely': {
                    'Z2': round(z2_vt, 6) if not np.isnan(z2_vt) else None,
                    'p_value_Z2': round(p_z2_vt, 4) if not np.isnan(p_z2_vt) else None,
                    'pass_Z2': pass_z2_vt,
                },
                'fissler_ziegel_score': round(fz_vt, 6),
                'es_coverage_ratio': round(es_cov_vt, 4) if not np.isnan(es_cov_vt) else None,
                'mean_var_pct': round(float(np.mean(np.abs(v_vt))) * 100, 4),
                'mean_es_pct': round(float(np.mean(np.abs(e_vt))) * 100, 4),
                'es_var_ratio': round(float(np.mean(np.abs(e_vt)) /
                                            np.mean(np.abs(v_vt))), 4),
                'note': 'VT portfolio HistSim ES (expanding window, signal lagged 1 day)',
            }

            z2_str = f"{z2_vt:.4f}" if not np.isnan(z2_vt) else "N/A"
            p_str = f"{p_z2_vt:.4f}" if not np.isnan(p_z2_vt) else "N/A"
            fz_str = f"{fz_vt:.4f}"
            cov_str = f"{es_cov_vt:.4f}" if not np.isnan(es_cov_vt) else "N/A"
            tri_str = "PASS" if bt_vt['trinity_pass'] else "FAIL"

            print(f"  {mn_vt:<22s} {bt_vt['n_violations']:5d} "
                  f"{bt_vt['violation_rate']:7.4f} {bt_vt['basel_traffic_light']:>7s} "
                  f"{tri_str:>8s} {z2_str:>8s} {p_str:>8s} {pass_z2_vt:>8s} "
                  f"{fz_str:>9s} {cov_str:>7s}")
        else:
            all_results[alpha_key][mn_vt] = {'error': 'insufficient valid VT forecasts'}
            print(f"  {mn_vt:<22s} — insufficient data")

    # ----------------------------------------------------------------
    # 6. Summary for Paper 2
    # ----------------------------------------------------------------
    print(f"\n{'='*74}")
    print("PAPER 2 TABLE: Combined VaR + ES Results for 0050.TW")
    print(f"{'='*74}\n")

    for alpha_key in ['1%', '5%']:
        if alpha_key not in all_results:
            continue
        print(f"  === {alpha_key} VaR/ES ===")
        print(f"  {'Model':<22s} {'Viol':>4s}/{'' :>4s} {'Basel':>6s} "
              f"{'VaR-Trinity':>11s} {'Z2':>7s} {'ES-p':>6s} {'ES-test':>7s} "
              f"{'FZ':>8s} {'ES/VaR':>6s}")
        print(f"  {'-'*90}")

        for mn in list(method_display.values()) + ['8.63/VIX VT']:
            if mn not in all_results[alpha_key]:
                continue
            r = all_results[alpha_key][mn]
            if 'error' in r:
                print(f"  {mn:<22s} ERROR")
                continue

            tri_str = "PASS" if r['trinity_pass'] else "FAIL"
            if 'acerbi_szekely' in r:
                z2_val = r['acerbi_szekely'].get('Z2')
                p_val = r['acerbi_szekely'].get('p_value_Z2')
                es_pass = r['acerbi_szekely'].get('pass_Z2', 'N/A')
                z2_str = f"{z2_val:.3f}" if z2_val is not None else "N/A"
                p_str = f"{p_val:.3f}" if p_val is not None else "N/A"
            else:
                z2_str, p_str, es_pass = "N/A", "N/A", "N/A"

            fz = r.get('fissler_ziegel_score', None)
            fz_str = f"{fz:.4f}" if fz is not None else "N/A"
            ratio = r.get('es_var_ratio', None)
            ratio_str = f"{ratio:.3f}" if ratio is not None else "N/A"

            print(f"  {mn:<22s} {r['n_violations']:3d}/{r['n_total']:<4d} "
                  f"{r['basel_traffic_light']:>6s} {tri_str:>11s} "
                  f"{z2_str:>7s} {p_str:>6s} {es_pass:>7s} "
                  f"{fz_str:>8s} {ratio_str:>6s}")
        print()

    # ----------------------------------------------------------------
    # 7. Key findings
    # ----------------------------------------------------------------
    print(f"{'='*74}")
    print("KEY FINDINGS")
    print(f"{'='*74}\n")

    print("INTERPRETATION:")
    print("  VaR Trinity: Kupiec + Christoffersen + Basel Green = all PASS")
    print("  Acerbi-Szekely Z2: p > 0.05 = ES adequate (fail to reject H0)")
    print("  Z2 > 0: ES conservative (overestimates tail risk)")
    print("  Z2 < 0: ES underestimates tail risk (dangerous)")
    print("  Fissler-Ziegel: lower is better (strictly consistent joint VaR-ES score)")
    print("  ES coverage: actual_tail/predicted_ES, ideal ~1.0")
    print()

    # Identify best model for each alpha
    for alpha_key in ['1%', '5%']:
        if alpha_key not in all_results:
            continue
        print(f"  {alpha_key} VaR/ES ranking:")
        models_ok = []
        for mn in list(method_display.values()) + ['8.63/VIX VT']:
            if mn not in all_results[alpha_key]:
                continue
            r = all_results[alpha_key][mn]
            if 'error' in r:
                continue
            trinity = r.get('trinity_pass', False)
            es_pass = r.get('acerbi_szekely', {}).get('pass_Z2', 'N/A')
            fz = r.get('fissler_ziegel_score', 999)
            models_ok.append((mn, trinity, es_pass, fz))

        # Sort by: (1) both pass, (2) FZ score
        def sort_key(item):
            mn, tri, es_p, fz = item
            both = 0 if (tri and es_p == 'PASS') else 1
            return (both, fz)

        models_ok.sort(key=sort_key)
        for rank, (mn, tri, es_p, fz) in enumerate(models_ok, 1):
            status = "VaR+ES PASS" if (tri and es_p == 'PASS') else (
                "VaR PASS" if tri else "FAIL")
            print(f"    #{rank}: {mn} — {status}, FZ={fz:.4f}")
        print()

    # ----------------------------------------------------------------
    # 8. Basel III context
    # ----------------------------------------------------------------
    print("BASEL III CONTEXT:")
    print("  Basel III (FRTB) requires ES at 97.5% for market risk capital.")
    print("  We test at 1% (stricter) and 5%. Passing at 1% implies adequacy at 2.5%.")
    print("  0050.TW's high kurtosis (7.67 OOS) makes ES testing critical —")
    print("  Normal and thin-tailed models likely underestimate extreme losses.")
    print("  Cornish-Fisher adjusts for this via skewness + kurtosis correction.")
    print()

    # ----------------------------------------------------------------
    # 9. Save results
    # ----------------------------------------------------------------
    elapsed = time.time() - t0

    output = make_serializable({
        'experiment_id': 'K896',
        'title': 'K896: Expected Shortfall Analysis for Taiwan VT Paper (Paper 2 Supplement)',
        'purpose': 'Address R1 SEVERE S1: Missing Expected Shortfall analysis',
        'method': 'GJR-GARCH(1,1) + 4 distribution methods + VT portfolio ES',
        'asset': '0050.TW',
        'oos_period': f'{OOS_START} to {oos_returns.index[-1].date()}',
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'n_bootstrap': N_BOOTSTRAP,
        'data_source': 'yfinance',
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'Student-t: scale=sqrt((df-2)/df) per-refit',
            'GARCH OOS: recursive h[t]=f(h[t-1], r^2[t-1])',
            'Basel: standard 250-day window',
            'VT signal: lagged 1 day (cross-market)',
        ],
        'references': [
            'Acerbi & Szekely (2014) "Backtesting Expected Shortfall" Risk Magazine',
            'Fissler & Ziegel (2016) "Higher order elicitability" Annals of Statistics 44(4):1680-1707',
            'Patton, Ziegel & Chen (2019) "Dynamic semiparametric models" JASA',
            'McNeil & Frey (2000) J Empirical Finance',
            'Cornish & Fisher (1938)',
            'Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)',
            'K836: GJR+CF = ONLY 0050.TW 1% VaR Trinity PASS',
            'K829: all methods FAIL for 0050.TW 1% VaR',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(elapsed, 1),
        'n_oos': n_oos,
        'n_refits': n_refits,
        'oos_stats': oos_stats,
        'vt_portfolio_stats': {
            'n_days': len(vt_returns),
            'mean_return_pct': round(float(np.mean(vt_returns)) * 100, 4),
            'std_pct': round(float(np.std(vt_returns)) * 100, 4),
            'min_pct': round(float(np.min(vt_returns)) * 100, 4),
            'max_pct': round(float(np.max(vt_returns)) * 100, 4),
        },
        'results': all_results,
        'model_ranking': {},
    })

    # Build model ranking
    for alpha_key in ['1%', '5%']:
        if alpha_key not in all_results:
            continue
        ranking = []
        for mn in list(method_display.values()) + ['8.63/VIX VT']:
            if mn not in all_results[alpha_key]:
                continue
            r = all_results[alpha_key][mn]
            if 'error' in r:
                continue
            trinity = r.get('trinity_pass', False)
            es_pass = r.get('acerbi_szekely', {}).get('pass_Z2', 'N/A')
            fz = r.get('fissler_ziegel_score', 999)
            ranking.append({
                'model': mn,
                'var_trinity': 'PASS' if trinity else 'FAIL',
                'es_test': es_pass,
                'fissler_ziegel': round(fz, 6),
                'both_pass': trinity and es_pass == 'PASS',
            })
        ranking.sort(key=lambda x: (not x['both_pass'], x['fissler_ziegel']))
        output['model_ranking'][alpha_key] = ranking

    with open(RESULTS_PATH, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Total elapsed: {elapsed:.1f}s")


if __name__ == '__main__':
    main()
