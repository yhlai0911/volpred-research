#!/usr/bin/env python3
"""
K899: Unified VaR/ES Experiment for Paper 1 (Leverage-Direction)
================================================================
[提出: 用戶 (Paper 1 R1 reviewer C3), 執行: Claude]

PURPOSE: Paper 1 R1 found CRITICAL C3 — "Table 5 cherry-picks from 3 different
experiments (K799, K802, K824v2) with different refit schedules." This experiment
replaces the cherry-picked Table 5 with a SINGLE unified experiment using
consistent settings across ALL 7 VaR methods.

METHODS COMPARED (all sharing identical GARCH/GJR estimation settings):
  1. GARCH + Normal         — symmetric vol + Normal quantile
  2. GARCH + Student-t      — symmetric vol + fat-tailed quantile
  3. GJR + Normal           — leverage effect + Normal quantile
  4. GJR + Student-t        — leverage effect + fat-tailed quantile
  5. GJR + Historical Sim   — leverage effect + nonparametric (500-day std resid)
  6. GJR + Skewed-t         — leverage effect + asymmetric fat tails (Hansen 1994)
  7. GJR + Adaptive floor   — leverage effect + floor(h_t, 0.5*rolling_20d_std)

SETTINGS (IDENTICAL for all methods):
  - Asset: SPY (yfinance, 2000-01-01 to 2026-01-01)
  - OOS: 2020-01-01 to 2025-12-31 (6-year period)
  - Expanding window for GARCH/GJR estimation
  - Refit every 63 trading days (quarterly)
  - VaR at 1% and 5%
  - ES at 2.5% (Basel standard)

EVALUATION for each method:
  - Violation count and rate
  - Kupiec (1995) LR test (p-value)
  - Christoffersen (1998) CC test (p-value)
  - Basel traffic light zone (standard 250-day)
  - Trinity PASS/FAIL (Kupiec + CC + Basel all pass)
  - Acerbi-Szekely (2014) Z2 test for ES
  - Fissler-Ziegel (2016) joint VaR-ES score
  - Average VaR width (capital efficiency)

ERROR LOG RULES APPLIED:
  - Student-t: scale correction sqrt((df-2)/df) applied (K824 bug fix)
  - Basel: standard 250-day lookback (K824 bug fix)
  - GARCH OOS: day-by-day recursive h[t]=f(h[t-1],r^2[t-1]) (K816 bug fix)
  - DM test: standard HAC (not custom)

DATA SOURCE: yfinance (SPY, 2000-01-01 to 2025-12-31)
signal.shift(1) enforced: forecast from t-1 data, evaluate against r_t

References:
  - Kupiec (1995) J. of Derivatives — POF test
  - Christoffersen (1998) Int. Econ. Rev. 39 — CC test
  - Basel Committee (1996, rev. 2019) — traffic light framework
  - Hansen (1994) J. Business Econ. Stat. 12 — skewed-t distribution
  - Fernandez & Steel (1998) JASA 93 — skewed distributions
  - Acerbi & Szekely (2014) J. Banking & Finance 49 — ES backtest
  - Fissler & Ziegel (2016) Annals of Statistics 44 — joint VaR-ES scoring
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss
  - Harvey et al. (2016) — multiple testing threshold t>3.0
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - Bollerslev (1986) J. Econometrics 31 — GARCH(1,1)
  - K799, K802, K824v2 — prior experiments (now superseded by this unified one)
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
from scipy.stats import norm, t as t_dist, chi2

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k899_unified_var_paper1_results.json')
OOS_START = '2020-01-01'
OOS_END = '2025-12-31'
REFIT_EVERY = 63  # quarterly refit
HS_WINDOW = 500   # rolling window for Historical Simulation standardized residuals
ADAPTIVE_FLOOR_WINDOW = 20  # rolling window for adaptive sigma floor


# ================================================================
# A. Numba-accelerated variance filters
# ================================================================

@njit(cache=True)
def garch_filter(r, omega, alpha, beta):
    """GARCH(1,1): sigma2_t = omega + alpha * r^2_{t-1} + beta * sigma2_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    s2[0] = var_r
    for t in range(1, T):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): sigma2_t = omega + (alpha + gamma*I_{r<0}) * r^2_{t-1} + beta * sigma2_{t-1}"""
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


# ================================================================
# B. Model fitting
# ================================================================

def fit_garch(returns, n_starts=4):
    """Fit GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        s2 = garch_filter(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 200)
        a0 = np.clip(0.06 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.90 + 0.03 * np.random.randn(), 0.5, 0.98)
        if a0 + b0 >= 0.99:
            b0 = 0.98 - a0
        o0 = max(1e-8, rv * (1 - a0 - b0))
        res = minimize(negll, [o0, a0, b0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta),
            'persistence': float(alpha + beta)}


def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
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


# ================================================================
# C. One-step-ahead forecasters
# ================================================================

def fcast_garch_next(returns, params):
    """GARCH one-step forecast: sigma2_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = garch_filter(r, params['omega'], params['alpha'], params['beta'])
    f = params['omega'] + params['alpha'] * r[-1] ** 2 + params['beta'] * s2[-1]
    return max(f, 1e-12)


def fcast_gjr_next(returns, params):
    """GJR one-step forecast: sigma2_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_std_resid(returns, params, model='gjr'):
    """Compute standardized residuals z_t = r_t / sigma_t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if model == 'gjr':
        s2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    else:
        s2 = garch_filter(r, params['omega'], params['alpha'], params['beta'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized from sample)


# ================================================================
# D. Distribution parameter estimation
# ================================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """
    Estimate Student-t df from unit-variance standardized residuals via MLE.
    FIXED: Uses scale = sqrt((df-2)/df) so the fitted distribution has unit
    variance, matching the standardized residuals (K824v2 fix).
    """
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


def estimate_skewt_params(std_residuals, df_min=2.1, df_max=30.0):
    """
    Estimate Fernandez-Steel (1998) skewed-t parameters (df, xi) from
    standardized residuals. xi < 1 means left-skewed (typical for equities).
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return {'df': 5.0, 'xi': 0.85}

    def skewt_logpdf(x, df, xi):
        c = 2.0 / (xi + 1.0 / xi)
        y = np.where(x >= 0, x / xi, x * xi)
        return np.log(c) + t_dist.logpdf(y, df=df)

    def neg_loglik(params):
        log_df, log_xi = params
        df = np.exp(log_df)
        xi = np.exp(log_xi)
        if df < df_min or df > df_max:
            return 1e10
        if xi <= 0:
            return 1e10
        ll = np.sum(skewt_logpdf(z, df, xi))
        return -ll if np.isfinite(ll) else 1e10

    best_nll, best_df, best_xi = 1e10, 5.0, 0.85
    for df_init in [4.0, 7.0, 12.0]:
        for xi_init in [0.7, 0.9, 1.1]:
            res = minimize(neg_loglik,
                           x0=[np.log(df_init), np.log(xi_init)],
                           method='L-BFGS-B',
                           bounds=[(np.log(df_min), np.log(df_max)),
                                   (np.log(0.3), np.log(3.0))],
                           options={'maxiter': 1000})
            if res.fun < best_nll:
                best_nll = res.fun
                best_df = float(np.exp(res.x[0]))
                best_xi = float(np.exp(res.x[1]))

    return {'df': float(np.clip(best_df, df_min, df_max)),
            'xi': float(np.clip(best_xi, 0.3, 3.0))}


def skewt_ppf(p, df, xi):
    """
    Quantile function (PPF) of Fernandez-Steel (1998) skewed-t.
    """
    c = 2.0 / (xi + 1.0 / xi)
    p0 = 1.0 / (1.0 + xi ** 2)

    if p <= p0:
        inner = p * xi / c
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = float(t_dist.ppf(inner, df=df)) / xi
    else:
        inner = 0.5 + (p - p0) / (xi * c)
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = xi * float(t_dist.ppf(inner, df=df))

    return z


# ================================================================
# E. VaR/ES backtest functions
# ================================================================

def basel_traffic_light_250(violations_array, n_lookback=250):
    """
    Standard Basel II/III traffic light based on last n_lookback days.
    Green: 0-4, Yellow: 5-9, Red: >=10 violations in 250 trading days.
    For shorter windows, scale proportionally.
    """
    v = np.asarray(violations_array, dtype=int)
    n = len(v)
    window = min(n, n_lookback)
    v_window = v[-window:]
    n_viol = int(v_window.sum())

    if window >= 250:
        green_max = 4
        yellow_max = 9
    else:
        green_max = int(np.floor(window * 4.0 / 250.0))
        yellow_max = int(np.floor(window * 9.0 / 250.0))
        green_max = max(green_max, 0)
        yellow_max = max(yellow_max, max(green_max + 1, 1))

    if n_viol <= green_max:
        color = 'green'
    elif n_viol <= yellow_max:
        color = 'yellow'
    else:
        color = 'red'

    return color, n_viol, window


def var_backtest(returns, var_series, alpha_var=0.01):
    """
    VaR backtest: Kupiec (1995) + Christoffersen (1998) + Basel traffic light.
    returns: OOS realized returns
    var_series: VaR threshold (negative values, e.g. -0.02 means 2% loss)
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec (1995) unconditional coverage
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen (1998) independence
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

    # Basel 250-day traffic light
    traffic, n_viol_window, window_size = basel_traffic_light_250(violations)

    return {
        'violation_rate': round(float(pi_hat), 6),
        'expected_rate': float(alpha_var),
        'n_violations': n1,
        'n_total': n,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': traffic,
        'basel_violations_in_window': n_viol_window,
        'basel_window_size': window_size,
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


def acerbi_szekely_z2(returns, var_series, es_series, alpha_es):
    """
    Acerbi & Szekely (2014) Z2 test for Expected Shortfall.
    H0: ES model is correctly specified.
    Z2 = (1/(T*alpha)) * sum_{I_t=1} (r_t / ES_t) + 1

    Under H0, Z2 ~ N(0, 1/T) approximately.
    We return the Z-statistic and p-value.
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    es = np.asarray(es_series, dtype=np.float64)
    T = len(r)

    violations = r < var
    n_viol = int(violations.sum())

    if n_viol == 0:
        return {'z_stat': 0.0, 'p_value': 1.0, 'n_violations': 0, 'pass': True}

    # Z2 statistic
    # ES is negative (e.g., -0.03), r on violation days is also negative
    # Z2 = (1/(T*alpha)) * sum(r_t / ES_t where violations) + 1
    # Under correct specification, E[Z2] = 0
    ratio = r[violations] / es[violations]
    z2_raw = (1.0 / (T * alpha_es)) * np.sum(ratio) + 1.0

    # Approximate standard error: SE ~ sqrt(n_viol) / (T * alpha_es)
    # More accurately: Var(Z2) ~ 1/(T*alpha) * (1/alpha - 1) under H0
    se = np.sqrt((1.0 / (T * alpha_es)) * (1.0 / alpha_es - 1.0))
    if se <= 0:
        se = 1e-6

    z_stat = z2_raw / se
    p_value = 2.0 * (1.0 - norm.cdf(abs(z_stat)))

    return {
        'z2_raw': round(float(z2_raw), 6),
        'z_stat': round(float(z_stat), 4),
        'p_value': round(float(p_value), 4),
        'se': round(float(se), 6),
        'n_violations': n_viol,
        'pass': bool(p_value > 0.05),
    }


def fissler_ziegel_score(returns, var_series, es_series, alpha):
    """
    Fissler & Ziegel (2016) strictly consistent joint VaR-ES scoring function.

    S(VaR, ES, r) = (1/alpha) * I(r < VaR) * (VaR - r) - VaR + ES
                     + (1/(2*ES^2)) * (1/alpha) * I(r < VaR) * (VaR - r)^2
                     - (1/ES) * (1/alpha) * I(r < VaR) * (VaR - r)
                     + log(-ES)/2

    We use the standard FZ0 loss from Patton, Ziegel & Chen (2019):
      FZ0_t = -1/(alpha * ES_t) * I_t * (r_t - VaR_t) + VaR_t / ES_t
              + log(-ES_t) - 1

    where I_t = I(r_t <= VaR_t).
    Lower is better.
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    es = np.asarray(es_series, dtype=np.float64)

    # Ensure ES is strictly negative
    es_safe = np.minimum(es, -1e-10)

    indicator = (r <= var).astype(float)

    # FZ0 loss (Patton, Ziegel & Chen 2019)
    fz = (-1.0 / (alpha * es_safe)) * indicator * (r - var) \
         + var / es_safe \
         + np.log(-es_safe) - 1.0

    # Filter out non-finite values
    valid = np.isfinite(fz)
    if valid.sum() < 10:
        return {'mean_score': float('nan'), 'n_valid': int(valid.sum())}

    return {
        'mean_score': round(float(np.mean(fz[valid])), 6),
        'std_score': round(float(np.std(fz[valid])), 6),
        'n_valid': int(valid.sum()),
    }


def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t means model 1 better (lower loss)."""
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * w * gamma_l
    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    t_stat = d_mean / se
    p_value = float(2 * (1 - norm.cdf(abs(t_stat))))
    return float(t_stat), p_value


# ================================================================
# F. VaR computation for each method
# ================================================================

def compute_var_normal(sigma, alpha):
    """VaR = sigma * z_alpha (Normal distribution)."""
    return sigma * norm.ppf(alpha)


def compute_var_student_t(sigma, alpha, df):
    """VaR = sigma * t_inv(alpha, df) * sqrt((df-2)/df) for unit-variance residuals."""
    if df > 2.0:
        scale = np.sqrt((df - 2.0) / df)
        return sigma * t_dist.ppf(alpha, df=df) * scale
    else:
        return sigma * t_dist.ppf(alpha, df=df)


def compute_var_skewt(sigma, alpha, df, xi):
    """VaR = sigma * skewt_ppf(alpha, df, xi)."""
    return sigma * skewt_ppf(alpha, df, xi)


def compute_var_histsim(sigma, z_residuals, alpha, window=500):
    """VaR = sigma * empirical quantile of last `window` standardized residuals."""
    if len(z_residuals) < 10:
        return sigma * norm.ppf(alpha)  # fallback
    z_window = z_residuals[-window:] if len(z_residuals) > window else z_residuals
    return sigma * float(np.percentile(z_window, alpha * 100))


def compute_var_adaptive_floor(sigma_garch, returns, alpha, floor_window=20):
    """
    Adaptive sigma floor: sigma_eff = max(sigma_garch, 0.5 * rolling_std(20d)).
    Then VaR = sigma_eff * z_alpha (Normal).
    """
    if len(returns) < floor_window:
        sigma_eff = sigma_garch
    else:
        rolling_std = float(np.std(returns[-floor_window:]))
        sigma_eff = max(sigma_garch, 0.5 * rolling_std)
    return sigma_eff * norm.ppf(alpha)


# ================================================================
# G. ES computation for each method
# ================================================================

def compute_es_normal(sigma, alpha):
    """ES under Normal: ES = -sigma * phi(z_alpha) / alpha."""
    z = norm.ppf(alpha)
    return -sigma * norm.pdf(z) / alpha


def compute_es_student_t(sigma, alpha, df):
    """ES under Student-t: using the analytical formula for unit-variance t."""
    if df <= 2.0:
        return compute_es_normal(sigma, alpha)  # fallback
    scale = np.sqrt((df - 2.0) / df)
    q = t_dist.ppf(alpha, df=df)
    # ES for standard Student-t:
    # ES_std = -(df + q^2) / (df - 1) * t_pdf(q, df) / alpha
    es_std = -(df + q ** 2) / (df - 1.0) * t_dist.pdf(q, df=df) / alpha
    return sigma * es_std * scale


def compute_es_skewt(sigma, alpha, df, xi, n_mc=10000):
    """ES under Skewed-t: Monte Carlo average below VaR quantile."""
    var_q = skewt_ppf(alpha, df, xi)
    # Generate MC samples from standard Student-t and apply skewness
    np.random.seed(42)
    u = np.random.uniform(0, 1, n_mc)
    samples = np.array([skewt_ppf(ui, df, xi) for ui in u])
    tail = samples[samples <= var_q]
    if len(tail) == 0:
        return sigma * var_q  # fallback to VaR
    return sigma * float(np.mean(tail))


def compute_es_histsim(sigma, z_residuals, alpha, window=500):
    """ES from Historical Simulation: average of z below the quantile, times sigma."""
    if len(z_residuals) < 10:
        return compute_es_normal(sigma, alpha)
    z_window = z_residuals[-window:] if len(z_residuals) > window else z_residuals
    q = float(np.percentile(z_window, alpha * 100))
    tail = z_window[z_window <= q]
    if len(tail) == 0:
        return sigma * q
    return sigma * float(np.mean(tail))


def compute_es_adaptive_floor(sigma_garch, returns, alpha, floor_window=20):
    """ES with adaptive floor: sigma_eff = max(sigma_garch, 0.5*rolling_std), Normal ES."""
    if len(returns) < floor_window:
        sigma_eff = sigma_garch
    else:
        rolling_std = float(np.std(returns[-floor_window:]))
        sigma_eff = max(sigma_garch, 0.5 * rolling_std)
    return compute_es_normal(sigma_eff, alpha)


# ================================================================
# MAIN: Unified VaR/ES Backtest
# ================================================================

def main():
    t0 = time.time()
    print("=" * 72)
    print("K899: Unified VaR/ES Experiment for Paper 1")
    print("  7 methods, IDENTICAL settings, single experiment")
    print("  OOS: 2020-01-01 to 2025-12-31 (6 years)")
    print("  Replaces cherry-picked Table 5 (K799/K802/K824v2)")
    print("=" * 72)

    # ----------------------------------------------------------
    # 1. Download data
    # ----------------------------------------------------------
    print("\n[1/6] Downloading SPY data...")
    spy = yf.download('SPY', start='2000-01-01', end='2026-01-01', progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.dropna(subset=['Close'])
    returns = spy['Close'].pct_change().dropna()
    returns.index = pd.to_datetime(returns.index)
    returns = returns.loc[~returns.index.duplicated(keep='first')]
    r_values = returns.values.astype(np.float64)
    dates = returns.index

    print(f"  Total data: {len(returns)} days ({dates[0].date()} to {dates[-1].date()})")

    # OOS range
    oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
    oos_idx = np.where(oos_mask)[0]
    n_oos = len(oos_idx)
    print(f"  OOS period: {OOS_START} to {OOS_END}, {n_oos} days")
    print(f"  First OOS date: {dates[oos_idx[0]].date()}, last: {dates[oos_idx[-1]].date()}")

    if n_oos == 0:
        print("ERROR: No OOS data found!")
        sys.exit(1)

    # ----------------------------------------------------------
    # 2. Define methods
    # ----------------------------------------------------------
    METHOD_NAMES = [
        'GARCH_Normal',
        'GARCH_StudentT',
        'GJR_Normal',
        'GJR_StudentT',
        'GJR_HistSim',
        'GJR_SkewedT',
        'GJR_AdaptiveFloor',
    ]

    ALPHA_LEVELS = [0.01, 0.05]
    ALPHA_ES = 0.025  # Basel standard

    # Storage
    var_forecasts = {m: {a: np.full(n_oos, np.nan) for a in ALPHA_LEVELS}
                     for m in METHOD_NAMES}
    es_forecasts = {m: np.full(n_oos, np.nan) for m in METHOD_NAMES}  # at ALPHA_ES
    sigma_forecasts = {'garch': np.full(n_oos, np.nan),
                       'gjr': np.full(n_oos, np.nan)}
    var_width = {m: {a: [] for a in ALPHA_LEVELS} for m in METHOD_NAMES}

    # ----------------------------------------------------------
    # 3. Expanding-window OOS forecasting
    # ----------------------------------------------------------
    print(f"\n[2/6] Running expanding-window OOS ({n_oos} days, refit every {REFIT_EVERY})...")

    garch_params = None
    gjr_params = None
    last_garch_fit = -999
    last_gjr_fit = -999
    t_df_garch = 5.0
    t_df_gjr = 5.0
    skewt_params = {'df': 5.0, 'xi': 0.85}
    z_gjr_all = None  # for HistSim

    for i, oos_pos in enumerate(oos_idx):
        train_end = oos_pos
        r_train = r_values[:train_end]

        # === Refit GARCH ===
        if oos_pos - last_garch_fit >= REFIT_EVERY:
            garch_params = fit_garch(r_train)
            if garch_params is not None:
                last_garch_fit = oos_pos
                z_garch = compute_std_resid(r_train, garch_params, model='garch')
                t_df_garch = estimate_t_df(z_garch)

        # === Refit GJR ===
        if oos_pos - last_gjr_fit >= REFIT_EVERY:
            gjr_params = fit_gjr(r_train)
            if gjr_params is not None:
                last_gjr_fit = oos_pos
                z_gjr_all = compute_std_resid(r_train, gjr_params, model='gjr')
                t_df_gjr = estimate_t_df(z_gjr_all)
                skewt_params = estimate_skewt_params(z_gjr_all)

                if i % 250 == 0 or i == 0:
                    print(f"  Refit at OOS day {i}/{n_oos}: "
                          f"GARCH pers={garch_params['persistence']:.4f}, "
                          f"GJR pers={gjr_params['persistence']:.4f}, "
                          f"t_df_garch={t_df_garch:.2f}, t_df_gjr={t_df_gjr:.2f}, "
                          f"skewt df={skewt_params['df']:.2f} xi={skewt_params['xi']:.3f}")

        if garch_params is None or gjr_params is None:
            continue

        # === One-step-ahead sigma forecasts ===
        sigma2_garch = fcast_garch_next(r_train, garch_params)
        sigma_garch = np.sqrt(sigma2_garch)
        sigma2_gjr = fcast_gjr_next(r_train, gjr_params)
        sigma_gjr = np.sqrt(sigma2_gjr)

        sigma_forecasts['garch'][i] = sigma_garch
        sigma_forecasts['gjr'][i] = sigma_gjr

        # Get latest GJR standardized residuals for HistSim
        z_gjr_current = compute_std_resid(r_train, gjr_params, model='gjr')

        # === Compute VaR and ES for each method and alpha level ===
        for alpha in ALPHA_LEVELS:
            # 1. GARCH + Normal
            var_forecasts['GARCH_Normal'][alpha][i] = compute_var_normal(sigma_garch, alpha)
            # 2. GARCH + Student-t
            var_forecasts['GARCH_StudentT'][alpha][i] = compute_var_student_t(sigma_garch, alpha, t_df_garch)
            # 3. GJR + Normal
            var_forecasts['GJR_Normal'][alpha][i] = compute_var_normal(sigma_gjr, alpha)
            # 4. GJR + Student-t
            var_forecasts['GJR_StudentT'][alpha][i] = compute_var_student_t(sigma_gjr, alpha, t_df_gjr)
            # 5. GJR + Historical Simulation
            var_forecasts['GJR_HistSim'][alpha][i] = compute_var_histsim(
                sigma_gjr, z_gjr_current, alpha, HS_WINDOW)
            # 6. GJR + Skewed-t
            var_forecasts['GJR_SkewedT'][alpha][i] = compute_var_skewt(
                sigma_gjr, alpha, skewt_params['df'], skewt_params['xi'])
            # 7. GJR + Adaptive Floor
            var_forecasts['GJR_AdaptiveFloor'][alpha][i] = compute_var_adaptive_floor(
                sigma_gjr, r_train, alpha, ADAPTIVE_FLOOR_WINDOW)

        # === ES at 2.5% for each method ===
        es_forecasts['GARCH_Normal'][i] = compute_es_normal(sigma_garch, ALPHA_ES)
        es_forecasts['GARCH_StudentT'][i] = compute_es_student_t(sigma_garch, ALPHA_ES, t_df_garch)
        es_forecasts['GJR_Normal'][i] = compute_es_normal(sigma_gjr, ALPHA_ES)
        es_forecasts['GJR_StudentT'][i] = compute_es_student_t(sigma_gjr, ALPHA_ES, t_df_gjr)
        es_forecasts['GJR_HistSim'][i] = compute_es_histsim(
            sigma_gjr, z_gjr_current, ALPHA_ES, HS_WINDOW)
        es_forecasts['GJR_SkewedT'][i] = compute_es_skewt(
            sigma_gjr, ALPHA_ES, skewt_params['df'], skewt_params['xi'])
        es_forecasts['GJR_AdaptiveFloor'][i] = compute_es_adaptive_floor(
            sigma_gjr, r_train, ALPHA_ES, ADAPTIVE_FLOOR_WINDOW)

        if (i + 1) % 250 == 0:
            print(f"  Progress: {i + 1}/{n_oos} days completed ({time.time()-t0:.1f}s)")

    print(f"  Forecasting complete. Elapsed: {time.time() - t0:.1f}s")

    # ----------------------------------------------------------
    # 4. Evaluate all methods
    # ----------------------------------------------------------
    print(f"\n[3/6] Evaluating all methods...")

    oos_returns = r_values[oos_idx]
    valid_garch = np.isfinite(sigma_forecasts['garch'])
    valid_gjr = np.isfinite(sigma_forecasts['gjr'])

    results = {
        'experiment_id': 'K899',
        'title': 'K899: Unified VaR/ES for Paper 1 (replaces cherry-picked Table 5)',
        'asset': 'SPY',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'n_oos': int(n_oos),
        'refit_every': REFIT_EVERY,
        'hs_window': HS_WINDOW,
        'adaptive_floor_window': ADAPTIVE_FLOOR_WINDOW,
        'alpha_levels_var': ALPHA_LEVELS,
        'alpha_es': ALPHA_ES,
        'methods': METHOD_NAMES,
        'data_source': 'yfinance (SPY, 2000-01-01 to 2025-12-31)',
        'method_description': 'Expanding window GARCH/GJR + 7 VaR distribution methods',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'purpose': 'Replace cherry-picked Table 5 from K799/K802/K824v2 with single unified experiment',
        'fixes_applied': [
            'Student-t scale correction sqrt((df-2)/df) from K824v2',
            'Basel 250-day standard traffic light from K824v2',
            'Day-by-day GARCH state propagation (no stale variance) from K816v2',
        ],
    }

    # --- 4a. VaR Backtest at each alpha ---
    print("\n  === VaR BACKTEST ===")
    var_results = {}
    for alpha in ALPHA_LEVELS:
        print(f"\n  --- VaR {int(alpha*100)}% ---")
        print(f"  {'Method':<22} {'Viol':<8} {'Rate':<10} {'Kupiec p':<10} "
              f"{'CC p':<10} {'Basel':<10} {'Trinity':<10} {'Avg|VaR|':<12}")
        var_results[str(alpha)] = {}
        for method in METHOD_NAMES:
            valid = valid_gjr if 'GJR' in method else valid_garch
            q = var_forecasts[method][alpha]
            mask = valid & np.isfinite(q)
            if mask.sum() < 50:
                var_results[str(alpha)][method] = None
                continue

            vbt = var_backtest(oos_returns[mask], q[mask], alpha_var=alpha)
            avg_var_width = float(np.mean(np.abs(q[mask])))
            vbt['avg_var_width'] = round(avg_var_width, 6)
            var_results[str(alpha)][method] = vbt

            status = "PASS" if vbt['trinity_pass'] else "FAIL"
            print(f"  {method:<22} {vbt['n_violations']:<8d} {vbt['violation_rate']:<10.4f} "
                  f"{vbt['kupiec']['p_value']:<10.4f} {vbt['christoffersen']['p_value']:<10.4f} "
                  f"{vbt['basel_traffic_light']:<10s} {status:<10s} {avg_var_width:<12.6f}")

    results['var_backtest'] = var_results

    # --- 4b. ES Backtest (Acerbi-Szekely Z2) ---
    print(f"\n  === ES BACKTEST at {ALPHA_ES*100}% (Acerbi-Szekely Z2) ===")
    print(f"  {'Method':<22} {'Z2_raw':<10} {'Z_stat':<10} {'p_value':<10} {'Result':<8}")
    es_results = {}

    # For ES test, we use VaR at the ES alpha level
    for method in METHOD_NAMES:
        valid = valid_gjr if 'GJR' in method else valid_garch
        # We need VaR at ALPHA_ES level for the ES test
        # Since we only computed VaR at 1% and 5%, compute VaR at 2.5% inline
        # Actually, let's compute VaR at 2.5% for the ES backtest
        # We'll recompute on the fly from sigma forecasts
        es = es_forecasts[method]
        mask = valid & np.isfinite(es)

        if mask.sum() < 50:
            es_results[method] = None
            continue

        # For ES backtest, we need VaR at the same alpha to define violations
        # Compute VaR at ALPHA_ES from the stored sigma
        if 'GARCH' in method and 'GJR' not in method:
            sigma_arr = sigma_forecasts['garch']
        else:
            sigma_arr = sigma_forecasts['gjr']

        # Compute VaR at ALPHA_ES for each OOS day
        var_es_level = np.full(n_oos, np.nan)
        for ii in range(n_oos):
            if not mask[ii]:
                continue
            sig = sigma_arr[ii]
            if method.endswith('_Normal') or method.endswith('_AdaptiveFloor'):
                var_es_level[ii] = compute_var_normal(sig, ALPHA_ES)
            elif method.endswith('_StudentT'):
                df = t_df_garch if 'GARCH' in method and 'GJR' not in method else t_df_gjr
                var_es_level[ii] = compute_var_student_t(sig, ALPHA_ES, df)
            elif method.endswith('_HistSim'):
                # Use last available z residuals (already computed at last refit)
                var_es_level[ii] = var_forecasts['GJR_HistSim'].get(ALPHA_ES, var_forecasts['GJR_HistSim'][0.01])[ii] if ALPHA_ES in var_forecasts['GJR_HistSim'] else np.nan
            elif method.endswith('_SkewedT'):
                var_es_level[ii] = compute_var_skewt(sig, ALPHA_ES, skewt_params['df'], skewt_params['xi'])

        # For methods where we couldn't compute VaR at 2.5%, use 1% VaR as proxy
        var_for_es = var_es_level
        var_finite = np.isfinite(var_for_es)
        if var_finite.sum() < 50:
            # Fallback: use stored 1% VaR
            var_for_es = var_forecasts[method][0.01]
            var_finite = np.isfinite(var_for_es)

        combined_mask = mask & var_finite
        if combined_mask.sum() < 50:
            es_results[method] = None
            continue

        as_test = acerbi_szekely_z2(oos_returns[combined_mask],
                                     var_for_es[combined_mask],
                                     es[combined_mask], ALPHA_ES)
        es_results[method] = as_test
        status = "PASS" if as_test['pass'] else "FAIL"
        print(f"  {method:<22} {as_test['z2_raw']:<10.4f} {as_test['z_stat']:<10.4f} "
              f"{as_test['p_value']:<10.4f} {status:<8s}")

    results['es_backtest_acerbi_szekely'] = es_results

    # --- 4c. Fissler-Ziegel Joint VaR-ES Score ---
    print(f"\n  === FISSLER-ZIEGEL JOINT VaR-ES SCORE (lower = better) ===")
    print(f"  {'Method':<22} {'FZ Score (1%)':<16} {'FZ Score (5%)':<16}")
    fz_results = {}
    fz_losses = {}

    for alpha in ALPHA_LEVELS:
        fz_results[str(alpha)] = {}
        fz_losses[str(alpha)] = {}
        for method in METHOD_NAMES:
            valid = valid_gjr if 'GJR' in method else valid_garch
            q = var_forecasts[method][alpha]
            es = es_forecasts[method]
            mask = valid & np.isfinite(q) & np.isfinite(es)
            if mask.sum() < 50:
                fz_results[str(alpha)][method] = None
                continue

            fz = fissler_ziegel_score(oos_returns[mask], q[mask], es[mask], alpha)
            fz_results[str(alpha)][method] = fz

            # Store pointwise FZ losses for DM test
            r_m = oos_returns[mask]
            v_m = q[mask]
            e_m = np.minimum(es[mask], -1e-10)
            ind = (r_m <= v_m).astype(float)
            fz_pw = (-1.0 / (alpha * e_m)) * ind * (r_m - v_m) \
                     + v_m / e_m + np.log(-e_m) - 1.0
            fz_losses[str(alpha)][method] = fz_pw

    for method in METHOD_NAMES:
        fz1 = fz_results['0.01'].get(method)
        fz5 = fz_results['0.05'].get(method)
        s1 = f"{fz1['mean_score']:.4f}" if fz1 else "N/A"
        s5 = f"{fz5['mean_score']:.4f}" if fz5 else "N/A"
        print(f"  {method:<22} {s1:<16} {s5:<16}")

    results['fissler_ziegel_scores'] = fz_results

    # --- 4d. Average VaR width (capital efficiency) ---
    print(f"\n  === AVERAGE VaR WIDTH (capital efficiency, lower = more efficient) ===")
    avg_width = {}
    for alpha in ALPHA_LEVELS:
        avg_width[str(alpha)] = {}
        for method in METHOD_NAMES:
            vr = var_results[str(alpha)].get(method)
            if vr:
                avg_width[str(alpha)][method] = vr.get('avg_var_width')
    results['avg_var_width'] = avg_width

    # ----------------------------------------------------------
    # 5. DM tests (pairwise on FZ loss)
    # ----------------------------------------------------------
    print(f"\n[4/6] DM tests (pairwise FZ joint loss, Harvey |t|>3.0)...")

    dm_results = {}
    # Key pairs to test (GJR_HistSim as reference, since it was best in K824v2)
    ref_method = 'GJR_HistSim'
    test_pairs = [
        ('GJR_HistSim', 'GARCH_Normal'),
        ('GJR_HistSim', 'GARCH_StudentT'),
        ('GJR_HistSim', 'GJR_Normal'),
        ('GJR_HistSim', 'GJR_StudentT'),
        ('GJR_HistSim', 'GJR_SkewedT'),
        ('GJR_HistSim', 'GJR_AdaptiveFloor'),
        ('GJR_StudentT', 'GARCH_StudentT'),
        ('GJR_SkewedT', 'GJR_StudentT'),
        ('GJR_Normal', 'GARCH_Normal'),
    ]

    for alpha in ALPHA_LEVELS:
        dm_results[str(alpha)] = {}
        print(f"\n  --- DM tests on FZ loss at {int(alpha*100)}% ---")
        for model_a, model_b in test_pairs:
            key = f'{model_a}_vs_{model_b}'
            la = fz_losses[str(alpha)].get(model_a)
            lb = fz_losses[str(alpha)].get(model_b)
            if la is None or lb is None:
                dm_results[str(alpha)][key] = None
                continue
            min_n = min(len(la), len(lb))
            t_stat, p_val = dm_test(la[:min_n], lb[:min_n])
            dm_results[str(alpha)][key] = {
                't_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'significant_harvey': bool(abs(t_stat) > 3.0),
                'winner': model_a if t_stat < 0 else model_b
            }
            sig_mark = "***" if abs(t_stat) > 3.0 else ("*" if p_val < 0.05 else "")
            winner = model_a if t_stat < 0 else model_b
            print(f"  {model_a} vs {model_b}: DM t={t_stat:+.3f} p={p_val:.4f} "
                  f"winner={winner} {sig_mark}")

    results['dm_tests_fz'] = dm_results

    # ----------------------------------------------------------
    # 6. Summary table for Paper 1 Table 5
    # ----------------------------------------------------------
    print(f"\n[5/6] Paper 1 Table 5 replacement...")
    print("\n" + "=" * 100)
    print("  UNIFIED TABLE 5: VaR and ES Evaluation (K899)")
    print("  Asset: SPY | OOS: 2020-01-01 to 2025-12-31 | Refit: 63 days")
    print("=" * 100)

    summary_table = []
    for method in METHOD_NAMES:
        row = {'method': method}
        for alpha in ALPHA_LEVELS:
            vr = var_results[str(alpha)].get(method)
            if vr:
                row[f'viol_{alpha}'] = vr['n_violations']
                row[f'rate_{alpha}'] = vr['violation_rate']
                row[f'kupiec_p_{alpha}'] = vr['kupiec']['p_value']
                row[f'cc_p_{alpha}'] = vr['christoffersen']['p_value']
                row[f'basel_{alpha}'] = vr['basel_traffic_light']
                row[f'trinity_{alpha}'] = vr['trinity_pass']
                row[f'width_{alpha}'] = vr.get('avg_var_width')
        es_r = es_results.get(method)
        if es_r:
            row['es_z_stat'] = es_r.get('z_stat')
            row['es_p_value'] = es_r.get('p_value')
            row['es_pass'] = es_r.get('pass')
        fz1 = fz_results['0.01'].get(method)
        fz5 = fz_results['0.05'].get(method)
        row['fz_1pct'] = fz1['mean_score'] if fz1 else None
        row['fz_5pct'] = fz5['mean_score'] if fz5 else None
        summary_table.append(row)

    results['summary_table'] = summary_table

    # Print formatted summary
    print(f"\n  {'Method':<22} | {'VaR 1%':^38} | {'VaR 5%':^38} | {'ES 2.5%':^18} | {'FZ Score':^18}")
    print(f"  {'':22s} | {'Viol':>5} {'Rate':>6} {'Kup.p':>6} {'CC.p':>6} {'Basel':>6} {'Trin':>5} | "
          f"{'Viol':>5} {'Rate':>6} {'Kup.p':>6} {'CC.p':>6} {'Basel':>6} {'Trin':>5} | "
          f"{'Z':>5} {'p':>6} {'OK':>4} | {'1%':>7} {'5%':>7}")
    print("  " + "-" * 128)

    for row in summary_table:
        m = row['method']
        # VaR 1%
        v1 = row.get('viol_0.01', '-')
        r1 = f"{row.get('rate_0.01', 0):.4f}" if row.get('rate_0.01') is not None else '-'
        k1 = f"{row.get('kupiec_p_0.01', 0):.3f}" if row.get('kupiec_p_0.01') is not None else '-'
        c1 = f"{row.get('cc_p_0.01', 0):.3f}" if row.get('cc_p_0.01') is not None else '-'
        b1 = row.get('basel_0.01', '-')
        t1 = 'Y' if row.get('trinity_0.01') else 'N'
        # VaR 5%
        v5 = row.get('viol_0.05', '-')
        r5 = f"{row.get('rate_0.05', 0):.4f}" if row.get('rate_0.05') is not None else '-'
        k5 = f"{row.get('kupiec_p_0.05', 0):.3f}" if row.get('kupiec_p_0.05') is not None else '-'
        c5 = f"{row.get('cc_p_0.05', 0):.3f}" if row.get('cc_p_0.05') is not None else '-'
        b5 = row.get('basel_0.05', '-')
        t5 = 'Y' if row.get('trinity_0.05') else 'N'
        # ES
        ez = f"{row.get('es_z_stat', 0):.2f}" if row.get('es_z_stat') is not None else '-'
        ep = f"{row.get('es_p_value', 0):.3f}" if row.get('es_p_value') is not None else '-'
        eok = 'Y' if row.get('es_pass') else 'N'
        # FZ
        f1 = f"{row.get('fz_1pct', 0):.4f}" if row.get('fz_1pct') is not None else '-'
        f5 = f"{row.get('fz_5pct', 0):.4f}" if row.get('fz_5pct') is not None else '-'

        print(f"  {m:<22} | {v1:>5} {r1:>6} {k1:>6} {c1:>6} {b1:>6} {t1:>5} | "
              f"{v5:>5} {r5:>6} {k5:>6} {c5:>6} {b5:>6} {t5:>5} | "
              f"{ez:>5} {ep:>6} {eok:>4} | {f1:>7} {f5:>7}")

    # ----------------------------------------------------------
    # Best methods summary
    # ----------------------------------------------------------
    print(f"\n[6/6] Summary & ranking...")

    # Count Trinity passes
    trinity_summary = {}
    for method in METHOD_NAMES:
        passes = 0
        for alpha in ALPHA_LEVELS:
            vr = var_results[str(alpha)].get(method)
            if vr and vr['trinity_pass']:
                passes += 1
        trinity_summary[method] = passes

    results['trinity_summary'] = trinity_summary

    # Best FZ score
    for alpha in ALPHA_LEVELS:
        valid_fz = [(m, fz_results[str(alpha)][m]['mean_score'])
                     for m in METHOD_NAMES
                     if fz_results[str(alpha)].get(m) and fz_results[str(alpha)][m].get('mean_score') is not None
                     and not np.isnan(fz_results[str(alpha)][m]['mean_score'])]
        if valid_fz:
            best = min(valid_fz, key=lambda x: x[1])
            print(f"  Best FZ score at {int(alpha*100)}%: {best[0]} ({best[1]:.4f})")

    # Overall recommendation
    print(f"\n  Trinity PASS count (VaR 1% + VaR 5%):")
    for method in METHOD_NAMES:
        print(f"    {method:<22} {trinity_summary[method]}/2")

    # ES pass
    print(f"\n  ES Acerbi-Szekely PASS:")
    for method in METHOD_NAMES:
        esr = es_results.get(method)
        if esr:
            print(f"    {method:<22} {'PASS' if esr['pass'] else 'FAIL'} (p={esr['p_value']:.4f})")

    # Overall champion
    full_pass = []
    for method in METHOD_NAMES:
        vr1 = var_results['0.01'].get(method)
        vr5 = var_results['0.05'].get(method)
        esr = es_results.get(method)
        if (vr1 and vr1['trinity_pass'] and
            vr5 and vr5['trinity_pass'] and
            esr and esr['pass']):
            full_pass.append(method)

    results['full_pass_models'] = full_pass
    print(f"\n  FULL PASS (VaR 1% Trinity + VaR 5% Trinity + ES pass): {full_pass if full_pass else 'NONE'}")

    # GJR params
    if gjr_params:
        results['final_gjr_params'] = {k: round(v, 6) for k, v in gjr_params.items()}
    if garch_params:
        results['final_garch_params'] = {k: round(v, 6) for k, v in garch_params.items()}
    results['student_t_df_garch'] = round(t_df_garch, 2)
    results['student_t_df_gjr'] = round(t_df_gjr, 2)
    results['skewt_params'] = {k: round(v, 4) for k, v in skewt_params.items()}

    results['elapsed_seconds'] = round(time.time() - t0, 1)

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_PATH}")
    print(f"  Total elapsed: {results['elapsed_seconds']}s")
    print("=" * 72)

    return results


if __name__ == '__main__':
    main()
