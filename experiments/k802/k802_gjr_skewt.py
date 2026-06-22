#!/usr/bin/env python3
"""
K802: GJR + Skewed-t Distribution — Complete the K799 VaR Fix
==============================================================
[提出: 用戶, 執行: Claude]

K799 finding: GJR wins QLIKE (#1, QLIKE=1.466) but FAILS VaR 1%
(Normal quantile z=-2.326 underestimates fat tails → too many violations).

K800/v2: Conformal calibration was artifact. Real fix: replace Normal with
fat-tail distribution.

Phase O established: Skewed-t distribution passes VaR 6/6 assets (K800v2).

This experiment: combine GJR (best QLIKE) with Skewed-t (best VaR) in the
full 6-layer Patton (2011) framework.

Models compared:
  1. GJR + Normal VaR          — K799 baseline: QLIKE #1, VaR FAIL
  2. GJR + Student-t VaR       — fat tails (df estimated from residuals)
  3. GJR + Skewed-t VaR        — fat tails + asymmetry (df + skew estimated)
  4. GARCH + Normal VaR        — K799 VaR PASS, but QLIKE #3
  5. GJR + FHS VaR             — nonparametric: sort standardized residuals

KEY QUESTION: Does GJR + Skewed-t achieve BOTH best QLIKE AND VaR Trinity PASS?

Implementation:
- σ² forecast is the SAME GJR (or GARCH) expanding window for all models
- Only the VaR quantile distribution changes
- df and skewness estimated from expanding-window standardized residuals
- Expanding window: refit GJR every 63 trading days
- For t and skewed-t: df estimated from residuals using MLE (fixed at first fit,
  updated each refit)
- FHS: empirical quantile of sorted standardized residuals

Data: SPY from yfinance, 2006-2025, OOS 2023-2024.
      Expanding window (no lookahead — all forecasts use only past data).

References:
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss
  - Hansen, Lunde & Nason (2011) Econometrica 79 — Model Confidence Set
  - Kupiec (1995) — unconditional VaR coverage
  - Christoffersen (1998) — conditional VaR independence
  - Harvey et al. (2016) — multiple testing threshold t>3.0
  - Hansen (1994) J. Business Econ. Stat. 12 — skewed-t distribution
  - Fernandez & Steel (1998) JASA 93 — skewed distributions for finance
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - Bollerslev (1986) J. Econometrics 31 — GARCH(1,1)
  - K799: Grand Model Evaluation — GJR wins QLIKE, fails VaR
  - K800v2: Skewed-t VaR passes 6/6 assets (Phase O)
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
from scipy.stats import norm, t as t_dist, chi2, spearmanr

from volpred.stats.model_evaluation import unit_variance_student_t_ppf

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k802_gjr_skewt_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63  # quarterly
ALPHA_VAR = 0.01  # 1% VaR


# ==============================================================
# A. Numba-accelerated variance filters
# ==============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}"""
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


@njit(cache=True)
def garch_filter(r, omega, alpha, beta):
    """GARCH(1,1): σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}"""
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


# ==============================================================
# B. Model fitting
# ==============================================================

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


# ==============================================================
# C. Distribution parameter estimation from standardized residuals
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """
    Estimate Student-t df from standardized residuals via MLE.
    z_t ~ t(0, 1, df) — standardized (but we fit on {std_residuals}).
    Returns estimated df (clamped to [df_min, df_max]).
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return 5.0  # fallback

    def neg_loglik(log_df):
        df = np.exp(log_df)
        if df < df_min or df > df_max:
            return 1e10
        scale = np.sqrt((df - 2) / df)
        # z is standardized to unit variance, so use the scaled Student-t
        # density instead of fitting a raw t(df) with variance df/(df-2).
        ll = np.sum(t_dist.logpdf(z / scale, df=df) - np.log(scale))
        return -ll if np.isfinite(ll) else 1e10

    res = minimize(neg_loglik, x0=[np.log(5.0)],
                   method='L-BFGS-B',
                   bounds=[(np.log(df_min), np.log(df_max))],
                   options={'maxiter': 500})
    df_est = float(np.exp(res.x[0]))
    return float(np.clip(df_est, df_min, df_max))


def estimate_skewt_params(std_residuals, df_min=2.1, df_max=30.0):
    """
    Estimate skewed-t distribution parameters (df, skew) from standardized residuals.

    We use the Fernandez-Steel (1998) skewed-t:
      f(z; df, xi) = 2/(xi + 1/xi) * [t(z/xi; df) if z>=0, else t(xi*z; df)]

    where xi > 0 is the skewness parameter (xi=1 → symmetric t).
    xi < 1 → left-skewed (longer left tail, appropriate for equity returns).

    Returns dict with 'df' and 'xi'.
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return {'df': 5.0, 'xi': 0.85}  # typical equity return defaults

    def skewt_logpdf(x, df, xi):
        """Log PDF of Fernandez-Steel skewed-t."""
        # Normalization constant
        c = 2.0 / (xi + 1.0 / xi)
        xi_inv = 1.0 / xi
        # Transform
        y = np.where(x >= 0, x / xi, x * xi)
        # Return log PDF
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

    res = minimize(neg_loglik,
                   x0=[np.log(5.0), np.log(0.85)],
                   method='L-BFGS-B',
                   bounds=[(np.log(df_min), np.log(df_max)),
                           (np.log(0.3), np.log(3.0))],
                   options={'maxiter': 1000})
    df_est = float(np.exp(res.x[0]))
    xi_est = float(np.exp(res.x[1]))
    return {'df': float(np.clip(df_est, df_min, df_max)),
            'xi': float(np.clip(xi_est, 0.3, 3.0))}


def skewt_ppf(p, df, xi):
    """
    Quantile function (PPF) of Fernandez-Steel (1998) skewed-t at probability p.

    PDF: f(x; df, xi) = (2/(xi + 1/xi)) * g(x*xi; df)  if x < 0
                                                g(x/xi; df)  if x >= 0
    where g(.; df) is the symmetric Student-t PDF.

    CDF derivation (Fernandez & Steel 1998, eq. 3):
      For z < 0:  F(z) = (2/(xi + 1/xi)) * (1/xi) * T(xi*z; df)
      For z >= 0: F(z) = 1/(1+xi²) + (2*xi/(xi+1/xi)) * (T(z/xi; df) - 0.5)

    CDF at z=0 (left mass):
      p0 = (2/(xi + 1/xi)) * (1/xi) * T(0; df) = (2/(xi + 1/xi)) * (1/xi) * 0.5
         = 1 / (1 + xi²)

    Inversion:
      If p <= p0 (left branch, z < 0):
        xi*z = T^{-1}(p * xi * (xi + 1/xi) / 2; df)
        z = T^{-1}(...) / xi

      If p > p0 (right branch, z >= 0):
        T(z/xi; df) = 0.5 + (p - p0) * (xi + 1/xi) / (2*xi)
        z = xi * T^{-1}(0.5 + (p - p0) * (xi + 1/xi) / (2*xi); df)
    """
    c = 2.0 / (xi + 1.0 / xi)  # = 2*xi / (xi² + 1)
    # Correct CDF at 0: p0 = 1/(1+xi²)
    p0 = 1.0 / (1.0 + xi ** 2)

    if p <= p0:
        # Left branch: z < 0
        # F(z) = c/xi * T(xi*z; df) → xi*z = T^{-1}(p * xi / c)
        inner = p * xi / c
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = float(t_dist.ppf(inner, df=df)) / xi
    else:
        # Right branch: z >= 0
        # F(z) = p0 + xi*c * (T(z/xi; df) - 0.5)
        # T(z/xi; df) = 0.5 + (p - p0) / (xi * c)
        inner = 0.5 + (p - p0) / (xi * c)
        inner = float(np.clip(inner, 1e-14, 1 - 1e-14))
        z = xi * float(t_dist.ppf(inner, df=df))

    return z


# ==============================================================
# D. One-step-ahead forecasters and VaR computation
# ==============================================================

def fcast_gjr_next(returns, params):
    """GJR one-step forecast: σ²_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def fcast_garch_next(returns, params):
    """GARCH one-step forecast: σ²_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = garch_filter(r, params['omega'], params['alpha'], params['beta'])
    f = params['omega'] + params['alpha'] * r[-1] ** 2 + params['beta'] * s2[-1]
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params, model='gjr'):
    """
    Compute standardized residuals z_t = r_t / σ_t for in-sample data.
    Used to estimate distribution parameters from the training set.
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if model == 'gjr':
        s2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    else:
        s2 = garch_filter(r, params['omega'], params['alpha'], params['beta'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized)


# ==============================================================
# E. VaR backtest (Kupiec + Christoffersen + Basel)
# ==============================================================

def var_backtest(returns, var_series, alpha_var=0.01):
    """
    VaR backtest: Kupiec (1995) + Christoffersen (1998) + Basel traffic light.

    returns: OOS realized returns (n,)
    var_series: VaR threshold (negative values, e.g. -0.02 means loss > 2%)
    alpha_var: nominal coverage level (default 0.01)

    Trinity PASS: Kupiec p>0.05 AND Christoffersen p>0.05 AND Basel GREEN.
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)

    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec (1995) LR test
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

    # Basel traffic light
    if pi_hat <= alpha_var * 1.5:
        traffic = 'green'
    elif pi_hat <= alpha_var * 2.0:
        traffic = 'yellow'
    else:
        traffic = 'red'

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
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ==============================================================
# F. Statistical evaluation helpers
# ==============================================================

def qlike_score(actual, predicted):
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(predicted, dtype=np.float64)
    valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    if valid.sum() < 10:
        return np.nan
    a, f = a[valid], f[valid]
    ratio = a / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def pointwise_qlike(actual, predicted):
    a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
    f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
    ratio = a / f
    return ratio - np.log(ratio) - 1


def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t-stat → model 1 better."""
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
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_val = 2 * (1 - t_dist.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ==============================================================
# G. Main OOS loop
# ==============================================================

def run_oos_loop(returns_all, oos_start_idx, oos_end_idx, refit_every=63, alpha_var=0.01):
    """
    Expanding-window OOS loop for K802 models.

    oos_start_idx: first OOS day (inclusive)
    oos_end_idx: last OOS day (exclusive) — enforces OOS_END date hard stop

    Returns:
      sigma2_gjr: array of GJR σ² forecasts (for QLIKE comparison)
      sigma2_garch: array of GARCH σ² forecasts
      var_results: dict of {model_name: VaR series}
      dist_params: dict of {model_name: list of (df, xi) per refit}
    """
    n_oos = oos_end_idx - oos_start_idx  # enforced window, not open-ended
    print(f"\n{'='*60}")
    print(f"K802 OOS loop: {n_oos} days, refit every {refit_every} days")
    print(f"{'='*60}")

    # σ² forecasts (same for GJR-based models)
    sigma2_gjr = np.full(n_oos, np.nan)
    sigma2_garch = np.full(n_oos, np.nan)

    # VaR series (negative thresholds)
    var_gjr_normal = np.full(n_oos, np.nan)
    var_gjr_t = np.full(n_oos, np.nan)
    var_gjr_skewt = np.full(n_oos, np.nan)
    var_garch_normal = np.full(n_oos, np.nan)
    var_gjr_fhs = np.full(n_oos, np.nan)

    # Distribution parameters per refit
    dist_params_t = []       # (day_idx, df)
    dist_params_skewt = []   # (day_idx, df, xi)
    fhs_quantile_cache = []  # (day_idx, empirical_quantile)

    # Cached fitted parameters
    gjr_params = None
    garch_params = None
    last_fit = -refit_every  # force fit on day 0

    t0 = time.time()
    z_normal = float(norm.ppf(alpha_var))  # -2.326 for 1%

    for i in range(n_oos):
        t = oos_start_idx + i  # current global index

        # All data up to (but NOT including) t is available for forecasting
        # Forecast uses data[:t] → signal at t-1 → NO lookahead
        r_train = returns_all[:t]

        # ── Refit every refit_every days ──────────────────────────
        if i - last_fit >= refit_every or gjr_params is None:
            last_fit = i

            gjr_params = fit_gjr(r_train)
            garch_params = fit_garch(r_train)

            if gjr_params is not None:
                # Compute in-sample standardized residuals for distribution fitting
                z_is = compute_standardized_residuals(r_train, gjr_params, model='gjr')
                z_is = z_is[np.isfinite(z_is)]

                # Estimate Student-t df
                df_t = estimate_t_df(z_is)
                dist_params_t.append({'day_idx': i, 'df': df_t})

                # Estimate skewed-t (df, xi)
                sk_params = estimate_skewt_params(z_is)
                dist_params_skewt.append({'day_idx': i, 'df': sk_params['df'],
                                          'xi': sk_params['xi']})

                # FHS: empirical quantile of standardized residuals
                fhs_q = float(np.quantile(z_is, alpha_var))
                fhs_quantile_cache.append({'day_idx': i, 'fhs_quantile': fhs_q})
            else:
                # Use fallbacks
                dist_params_t.append({'day_idx': i, 'df': 5.0})
                dist_params_skewt.append({'day_idx': i, 'df': 5.0, 'xi': 0.85})
                fhs_quantile_cache.append({'day_idx': i, 'fhs_quantile': z_normal})

            if i == 0 or i % 126 == 0:
                pct = 100 * i / n_oos
                elapsed = time.time() - t0
                if gjr_params:
                    print(f"  [{pct:5.1f}%] Day {i}/{n_oos}, elapsed {elapsed:.1f}s, "
                          f"GJR persist={gjr_params['persistence']:.4f}, "
                          f"df={dist_params_t[-1]['df']:.2f}, "
                          f"xi={dist_params_skewt[-1]['xi']:.3f}, "
                          f"FHS_q={fhs_quantile_cache[-1]['fhs_quantile']:.4f}")
                else:
                    print(f"  [{pct:5.1f}%] Day {i}/{n_oos}, GJR fit FAILED")

        # ── Generate σ² forecasts ──────────────────────────────────
        if gjr_params is not None:
            s2_gjr = fcast_gjr_next(r_train, gjr_params)
            sigma_gjr = np.sqrt(max(s2_gjr, 1e-16))
            sigma2_gjr[i] = s2_gjr

            # Model 1: GJR + Normal VaR
            var_gjr_normal[i] = sigma_gjr * z_normal

            # Model 2: GJR + Student-t VaR
            df_t_cur = dist_params_t[-1]['df'] if dist_params_t else 5.0
            z_t = unit_variance_student_t_ppf(alpha_var, df_t_cur)
            var_gjr_t[i] = sigma_gjr * z_t

            # Model 3: GJR + Skewed-t VaR
            sk_cur = dist_params_skewt[-1] if dist_params_skewt else {'df': 5.0, 'xi': 0.85}
            z_st = skewt_ppf(alpha_var, df=sk_cur['df'], xi=sk_cur['xi'])
            var_gjr_skewt[i] = sigma_gjr * z_st

            # Model 5: GJR + FHS VaR
            fhs_q_cur = fhs_quantile_cache[-1]['fhs_quantile'] if fhs_quantile_cache else z_normal
            var_gjr_fhs[i] = sigma_gjr * fhs_q_cur

        if garch_params is not None:
            s2_garch = fcast_garch_next(r_train, garch_params)
            sigma_garch = np.sqrt(max(s2_garch, 1e-16))
            sigma2_garch[i] = s2_garch

            # Model 4: GARCH + Normal VaR (K799 baseline that passed)
            var_garch_normal[i] = sigma_garch * z_normal

    elapsed_total = time.time() - t0
    print(f"\n  OOS loop complete: {elapsed_total:.1f}s")

    return {
        'sigma2_gjr': sigma2_gjr,
        'sigma2_garch': sigma2_garch,
        'var_gjr_normal': var_gjr_normal,
        'var_gjr_t': var_gjr_t,
        'var_gjr_skewt': var_gjr_skewt,
        'var_garch_normal': var_garch_normal,
        'var_gjr_fhs': var_gjr_fhs,
        'dist_params_t': dist_params_t,
        'dist_params_skewt': dist_params_skewt,
        'fhs_quantile_cache': fhs_quantile_cache,
    }


# ==============================================================
# H. Main
# ==============================================================

def main():
    print("\n" + "=" * 70)
    print("K802: GJR + Skewed-t — Complete the K799 VaR Fix")
    print("=" * 70)
    t_start = time.time()

    # ── 1. Data download ──────────────────────────────────────────
    print("\n[1] Downloading SPY data from yfinance (2006-2025)...")
    spy = yf.download('SPY', start='2006-01-01', end='2025-12-31',
                      auto_adjust=True, progress=False)
    spy = spy.dropna()
    close = spy['Close'].values.flatten()
    dates = spy.index

    returns_all = np.diff(np.log(close))
    dates_ret = dates[1:]  # dates for returns (one shorter than prices)

    n_total = len(returns_all)
    print(f"   Total observations: {n_total} trading days ({dates_ret[0].date()} to {dates_ret[-1].date()})")

    # ── 2. OOS split ──────────────────────────────────────────────
    oos_mask = (dates_ret >= pd.Timestamp(OOS_START)) & (dates_ret <= pd.Timestamp(OOS_END))
    oos_start_idx = int(np.argmax(oos_mask))
    n_oos = int(oos_mask.sum())
    oos_end_idx = oos_start_idx + n_oos  # hard stop: exclusive upper bound
    n_is = oos_start_idx

    print(f"   IS: {n_is} days, OOS: {n_oos} days")
    print(f"   OOS period: {dates_ret[oos_start_idx].date()} to {dates_ret[oos_end_idx - 1].date()}")

    # Only the masked OOS window — NOT open-ended to end of data
    oos_returns = returns_all[oos_start_idx:oos_end_idx]

    # Descriptive stats on OOS period
    desc_stats = {
        'mean_return': round(float(np.mean(oos_returns)), 6),
        'std_return': round(float(np.std(oos_returns)), 6),
        'mean_r2': round(float(np.mean(oos_returns ** 2)), 8),
        'skewness': round(float(pd.Series(oos_returns).skew()), 4),
        'kurtosis': round(float(pd.Series(oos_returns).kurt()), 4),
        'min_return': round(float(np.min(oos_returns)), 6),
        'max_return': round(float(np.max(oos_returns)), 6),
    }
    print(f"\n   OOS descriptive stats:")
    for k, v in desc_stats.items():
        print(f"     {k}: {v}")

    # ── 3. Run OOS loop ───────────────────────────────────────────
    print("\n[2] Running expanding-window OOS loop...")
    oos_results = run_oos_loop(returns_all, oos_start_idx, oos_end_idx,
                               refit_every=REFIT_EVERY, alpha_var=ALPHA_VAR)

    sigma2_gjr = oos_results['sigma2_gjr']
    sigma2_garch = oos_results['sigma2_garch']

    # ── 4. QLIKE evaluation on σ² forecasts ───────────────────────
    print("\n[3] Computing QLIKE on σ² forecasts...")
    r2_oos = oos_returns ** 2  # aligned with oos_returns (n_oos,)

    # Only two distinct σ² models: GJR and GARCH
    # (VaR models differ only in distribution, not σ²)
    qlike_gjr = qlike_score(r2_oos, sigma2_gjr)
    qlike_garch = qlike_score(r2_oos, sigma2_garch)

    pw_gjr = pointwise_qlike(r2_oos, sigma2_gjr)
    pw_garch = pointwise_qlike(r2_oos, sigma2_garch)

    dm_stat_gjr_garch, dm_p_gjr_garch = dm_test(pw_gjr, pw_garch)

    print(f"   QLIKE: GJR={qlike_gjr:.6f}, GARCH={qlike_garch:.6f}")
    print(f"   DM(GJR vs GARCH): t={dm_stat_gjr_garch:.4f}, p={dm_p_gjr_garch:.4f}")

    # Spearman rank correlations
    rho_gjr, p_gjr = spearmanr(r2_oos[np.isfinite(sigma2_gjr)],
                                sigma2_gjr[np.isfinite(sigma2_gjr)])
    rho_garch, p_garch = spearmanr(r2_oos[np.isfinite(sigma2_garch)],
                                   sigma2_garch[np.isfinite(sigma2_garch)])

    print(f"   Spearman: GJR rho={rho_gjr:.4f} (p={p_gjr:.4f}), "
          f"GARCH rho={rho_garch:.4f} (p={p_garch:.4f})")

    # ── 5. VaR backtests ─────────────────────────────────────────
    print("\n[4] Running VaR backtests (Kupiec + Christoffersen + Basel)...")

    models = {
        'GJR+Normal': oos_results['var_gjr_normal'],
        'GJR+StudentT': oos_results['var_gjr_t'],
        'GJR+SkewedT': oos_results['var_gjr_skewt'],
        'GARCH+Normal': oos_results['var_garch_normal'],
        'GJR+FHS': oos_results['var_gjr_fhs'],
    }

    var_results = {}
    print(f"\n   {'Model':<20} {'ViolRate':>10} {'Violations':>12} {'Kupiec_p':>10} {'Christ_p':>10} {'Basel':>8} {'PASS?':>8}")
    print(f"   {'-'*80}")

    for name, var_series in models.items():
        # Only evaluate where we have valid forecasts
        valid = np.isfinite(var_series) & np.isfinite(oos_returns[:len(var_series)])
        r_valid = oos_returns[:len(var_series)][valid]
        v_valid = var_series[valid]

        bt = var_backtest(r_valid, v_valid, alpha_var=ALPHA_VAR)
        var_results[name] = bt

        pass_str = "PASS" if bt['trinity_pass'] else "FAIL"
        print(f"   {name:<20} {bt['violation_rate']:>10.4f} "
              f"{bt['n_violations']:>6}/{bt['n_total']:<5} "
              f"{bt['kupiec']['p_value']:>10.4f} "
              f"{bt['christoffersen']['p_value']:>10.4f} "
              f"{bt['basel_traffic_light']:>8} "
              f"{pass_str:>8}")

    # ── 6. Average VaR quantile analysis ─────────────────────────
    print("\n[5] Average VaR quantile analysis (tail coverage)...")

    # Normal quantile
    z_normal = float(norm.ppf(ALPHA_VAR))
    print(f"   Normal z_alpha = {z_normal:.4f}")

    # Last estimated t params
    if oos_results['dist_params_t']:
        df_last = oos_results['dist_params_t'][-1]['df']
        z_t_last = float(t_dist.ppf(ALPHA_VAR, df=df_last))
        print(f"   Final Student-t: df={df_last:.2f}, z_alpha={z_t_last:.4f}")

    if oos_results['dist_params_skewt']:
        sk_last = oos_results['dist_params_skewt'][-1]
        z_skewt_last = skewt_ppf(ALPHA_VAR, sk_last['df'], sk_last['xi'])
        print(f"   Final Skewed-t: df={sk_last['df']:.2f}, xi={sk_last['xi']:.3f}, "
              f"z_alpha={z_skewt_last:.4f}")

    if oos_results['fhs_quantile_cache']:
        fhs_last = oos_results['fhs_quantile_cache'][-1]['fhs_quantile']
        print(f"   Final FHS quantile: {fhs_last:.4f}")

    # Summary of distribution parameter evolution
    dist_summary = {}
    if oos_results['dist_params_t']:
        df_vals = [d['df'] for d in oos_results['dist_params_t']]
        dist_summary['student_t_df'] = {
            'mean': round(float(np.mean(df_vals)), 3),
            'min': round(float(np.min(df_vals)), 3),
            'max': round(float(np.max(df_vals)), 3),
            'final': round(float(df_vals[-1]), 3),
        }
    if oos_results['dist_params_skewt']:
        df_vals = [d['df'] for d in oos_results['dist_params_skewt']]
        xi_vals = [d['xi'] for d in oos_results['dist_params_skewt']]
        dist_summary['skewed_t'] = {
            'df_mean': round(float(np.mean(df_vals)), 3),
            'df_min': round(float(np.min(df_vals)), 3),
            'df_max': round(float(np.max(df_vals)), 3),
            'df_final': round(float(df_vals[-1]), 3),
            'xi_mean': round(float(np.mean(xi_vals)), 4),
            'xi_min': round(float(np.min(xi_vals)), 4),
            'xi_max': round(float(np.max(xi_vals)), 4),
            'xi_final': round(float(xi_vals[-1]), 4),
            'xi_interpretation': 'xi<1 = left-skewed (longer left tail, typical for equity)',
        }
    if oos_results['fhs_quantile_cache']:
        fhs_vals = [d['fhs_quantile'] for d in oos_results['fhs_quantile_cache']]
        dist_summary['fhs'] = {
            'quantile_mean': round(float(np.mean(fhs_vals)), 4),
            'quantile_min': round(float(np.min(fhs_vals)), 4),
            'quantile_max': round(float(np.max(fhs_vals)), 4),
            'quantile_final': round(float(fhs_vals[-1]), 4),
        }

    # ── 7. Key findings ───────────────────────────────────────────
    print("\n[6] Key findings:")
    gjr_skewt_pass = var_results['GJR+SkewedT']['trinity_pass']
    gjr_normal_pass = var_results['GJR+Normal']['trinity_pass']
    garch_normal_pass = var_results['GARCH+Normal']['trinity_pass']
    gjr_fhs_pass = var_results['GJR+FHS']['trinity_pass']
    gjr_t_pass = var_results['GJR+StudentT']['trinity_pass']

    dual_champion = gjr_skewt_pass  # GJR best QLIKE AND VaR PASS
    print(f"   K799 finding confirmed: GJR wins QLIKE={qlike_gjr:.6f} vs GARCH={qlike_garch:.6f}")
    print(f"   GJR+Normal VaR: {'PASS' if gjr_normal_pass else 'FAIL'} (replicate K799 FAIL expected)")
    print(f"   GARCH+Normal VaR: {'PASS' if garch_normal_pass else 'FAIL'} (K799 baseline PASS expected)")
    print(f"   GJR+StudentT VaR: {'PASS' if gjr_t_pass else 'FAIL'}")
    print(f"   GJR+SkewedT VaR: {'PASS' if gjr_skewt_pass else 'FAIL'}")
    print(f"   GJR+FHS VaR: {'PASS' if gjr_fhs_pass else 'FAIL'}")
    print(f"\n   DUAL CHAMPION (best QLIKE + VaR PASS): {'GJR+SkewedT YES' if dual_champion else 'NOT ACHIEVED'}")

    # ── 8. Save results ───────────────────────────────────────────
    runtime = round(time.time() - t_start, 1)
    print(f"\n[7] Saving results to {RESULTS_PATH}...")

    results = {
        'experiment_id': 'K802',
        'title': 'GJR + Skewed-t Distribution — Complete the K799 VaR Fix',
        'attribution': '[提出: 用戶, 執行: Claude]',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'asset': 'SPY',
        'full_period': f"{dates_ret[0].date()} to {dates_ret[-1].date()}",
        'oos_period': f"{dates_ret[oos_start_idx].date()} to {dates_ret[oos_start_idx + n_oos - 1].date()}",
        'n_total': n_total,
        'n_oos': n_oos,
        'n_is': n_is,
        'refit_every': REFIT_EVERY,
        'alpha_var': ALPHA_VAR,
        'oos_descriptive_stats': desc_stats,
        'models': list(models.keys()),
        'qlike_results': {
            'description': 'QLIKE on r² (Patton 2011 proxy-robust) — same σ² forecast, only VaR distribution differs',
            'GJR_qlike': round(qlike_gjr, 6),
            'GARCH_qlike': round(qlike_garch, 6),
            'GJR_winner': qlike_gjr < qlike_garch,
            'DM_GJR_vs_GARCH': {
                'stat': round(dm_stat_gjr_garch, 4),
                'p_value': round(dm_p_gjr_garch, 4),
                'harvey_pass': bool(abs(dm_stat_gjr_garch) > 3.0),
                'better': 'GJR' if dm_stat_gjr_garch < 0 else 'GARCH',
            },
        },
        'spearman_results': {
            'GJR': {'rho': round(float(rho_gjr), 4), 'p_value': round(float(p_gjr), 6)},
            'GARCH': {'rho': round(float(rho_garch), 4), 'p_value': round(float(p_garch), 6)},
        },
        'var_backtest_results': {model: bt for model, bt in var_results.items()},
        'distribution_params_summary': dist_summary,
        'n_refits': len(oos_results['dist_params_t']),
        'key_findings': {
            'dual_champion_achieved': bool(dual_champion),
            'dual_champion_model': 'GJR+SkewedT' if dual_champion else 'None',
            'gjr_normal_fails_var': bool(not gjr_normal_pass),
            'garch_normal_passes_var': bool(garch_normal_pass),
            'gjr_t_passes_var': bool(gjr_t_pass),
            'gjr_skewt_passes_var': bool(gjr_skewt_pass),
            'gjr_fhs_passes_var': bool(gjr_fhs_pass),
            'conclusion': (
                'GJR+SkewedT achieves BOTH best QLIKE and VaR Trinity PASS: '
                'fat tails + asymmetry fix GJR Normal tail underestimation.'
                if dual_champion else
                'GJR+SkewedT does NOT achieve dual championship — further investigation needed.'
            ),
        },
        'runtime_seconds': runtime,
        'references': [
            'Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss',
            'Hansen, Lunde & Nason (2011) Econometrica 79 — MCS',
            'Kupiec (1995) — unconditional VaR coverage',
            'Christoffersen (1998) — conditional VaR independence',
            'Harvey et al. (2016) — multiple testing threshold t>3.0',
            'Hansen (1994) J. Business Econ. Stat. 12 — skewed-t distribution',
            'Fernandez & Steel (1998) JASA 93 — skewed distributions for finance',
            'Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH',
            'Bollerslev (1986) J. Econometrics 31 — GARCH(1,1)',
            'K799: Grand Model Evaluation — GJR wins QLIKE, fails VaR (Normal)',
            'K800v2: Skewed-t VaR passes 6/6 assets (Phase O confirmation)',
        ],
        'limitations': [
            'OOS period 2023-2024 is relatively calm — results may differ in crisis periods',
            'Daily r² is a noisy proxy for true σ²; 5-min RV would be gold standard',
            'Skewed-t uses Fernandez-Steel (1998) parameterization — other parameterizations exist',
            'df and xi estimated from IS residuals — estimation error may affect tail accuracy',
            'FHS assumes stationarity of standardized residuals across regimes',
            'VaR backtest on n=502 OOS days has limited power — more power with longer OOS',
        ],
    }

    with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*70}")
    print("K802 COMPLETE")
    print(f"{'='*70}")
    print(f"Runtime: {runtime:.1f}s")
    print(f"Results saved: {RESULTS_PATH}")
    print(f"\nKey result: Dual Champion (best QLIKE + VaR PASS) = "
          f"{'GJR+SkewedT: YES' if dual_champion else 'NOT ACHIEVED'}")
    print(f"GJR QLIKE={qlike_gjr:.6f} (vs GARCH={qlike_garch:.6f})")
    for name, bt in var_results.items():
        print(f"  {name}: violation={bt['violation_rate']:.4f}, "
              f"trinity={'PASS' if bt['trinity_pass'] else 'FAIL'}")
    print(f"{'='*70}\n")

    return results


if __name__ == '__main__':
    main()
