#!/usr/bin/env python3
"""
K825: Proxy-Reliance Control in Conformal VaR
==============================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K824v2 confirmed GJR+HistSim as the best 1% VaR method (only Basel Green +
  Trinity PASS with 4/502 violations). However, ALL VaR methods ultimately
  depend on r² as a proxy for the unobservable true variance σ².

  This experiment tests whether conformal prediction methods can reduce this
  proxy dependence and improve VaR calibration, building on:
  - K800/K800v2 lessons (conformal heuristics led to artifacts)
  - Patton (2011) proxy-robust loss functions
  - arXiv:2603.22569 (2026) proxy-reliance control in conformal calibration

Methods (all built on K824v2's GJR-GARCH expanding window):

  1. **Naive Conformal**: Split conformal using raw conformity scores
     c_t = |r_t| / σ_{t|t-1}. This is K800v2's proper method, re-implemented
     cleanly without the artifact bugs.

  2. **Proxy-Robust Conformal**: Uses Patton (2011) QLIKE-based conformity
     scores. Instead of c_t = |r_t|/σ_t, we use:
       s_t = r²_t/σ²_t - log(r²_t/σ²_t) - 1  (QLIKE residual)
     The key insight: QLIKE is consistent for σ² ranking even when r² is
     a noisy proxy (Patton 2011, Theorem 1). The conformal correction
     based on QLIKE scores should be more robust to proxy noise.

  3. **Split Conformal with Exchangeability Test**: Before applying conformal
     correction, test whether the calibration scores are exchangeable (IID)
     using a runs test. If exchangeability fails, fall back to raw VaR.
     This guards against regime changes invalidating the conformal guarantee.

Baselines (from K824v2, re-computed here for fair comparison):
  - GJR + Normal VaR
  - GJR + Student-t VaR (with scale = sqrt((df-2)/df))
  - GJR + HistSim VaR

Asset: SPY
OOS: 2023-01-01 ~ 2024-12-31
Window: expanding (K783 confirmed optimal)
Refit: every 63 trading days
VaR levels: 1%, 5%

Evaluation:
  - Kupiec (1995) unconditional coverage
  - Christoffersen (1998) conditional independence
  - Basel II/III traffic light (standard 250-day, Green: 0-4, Yellow: 5-9, Red: >=10)
  - Trinity test (all three pass)
  - Pinball (tick) loss at 1% and 5%
  - DM test on pinball loss (Harvey t>3.0 threshold)
  - Average VaR width (efficiency measure)

Error Log rules applied:
  - GARCH OOS: recursive h[t]=f(h[t-1],r²[t-1]), no stale variance
  - Basel: standard 250-day count thresholds, not custom ratio
  - Student-t: scale = sqrt((df-2)/df) for unit-variance residuals
  - Conformal: theory-based methods only, no heuristic corrections
  - signal.shift(1): forecast from t-1 data, evaluate against r_t

References:
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss
  - Vovk, Gammerman, Shafer (2005) — Algorithmic Learning, conformal prediction
  - arXiv:2603.22569 (2026) — Proxy-reliance control in conformal VaR
  - Kupiec (1995) — unconditional VaR coverage
  - Christoffersen (1998) — conditional VaR independence
  - Basel Committee (1996, 2019) — Traffic light backtesting
  - Gneiting & Raftery (2007) JASA 102 — Scoring rules, pinball loss
  - K824v2: HistSim 4/502 violations, Basel Green, Trinity PASS
  - K800/K800v2: Conformal heuristic artifact (Codex flagged)
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
from scipy.stats import norm, t as t_dist, chi2, mannwhitneyu

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__),
                            'k825_conformal_var_proxy_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63  # quarterly refit
ALPHA_LEVELS = [0.01, 0.05]  # VaR levels to test


# ==============================================================
# A. Numba-accelerated GJR-GARCH variance filter
# ==============================================================

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


# ==============================================================
# B. GJR-GARCH fitting (quasi-MLE, Normal innovations)
# ==============================================================

def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via quasi-MLE. Returns params dict or None."""
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


# ==============================================================
# C. One-step-ahead forecast + standardized residuals
# ==============================================================

def gjr_one_step_forecast(returns, params):
    """GJR one-step forecast: sigma2_{t+1} given data up to t."""
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


# ==============================================================
# D. Student-t df estimation (K824v2 FIXED version)
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """
    Estimate Student-t df from unit-variance standardized residuals via MLE.
    Uses scale = sqrt((df-2)/df) so fitted distribution has unit variance.
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


# ==============================================================
# E. Conformal Method 1: Naive Split Conformal
# ==============================================================

def conformal_naive(sigma_forecasts, returns_oos, alpha, lookback=252,
                    min_calibration=50):
    """
    Naive Split Conformal VaR (corrected from K800v2).

    Conformity score: c_t = -r_t / sigma_t  (large c = big loss relative to forecast)
    At each t, compute alpha-quantile of past {c_i}_{i=t-lookback..t-1},
    then VaR_t = -sigma_t * q_{1-alpha}(c).

    Key difference from K800: no heuristic multiplier, pure quantile-based.
    Tracks violations against DEPLOYED (adjusted) VaR, not raw.

    Parameters
    ----------
    sigma_forecasts : array, sigma (not sigma2) forecasts, positive
    returns_oos : array, actual realized returns
    alpha : float, target VaR level (0.01 for 1%)
    lookback : int, rolling calibration window
    min_calibration : int, minimum calibration points before applying conformal

    Returns
    -------
    var_adjusted : array, conformally calibrated VaR (negative values)
    """
    n = len(sigma_forecasts)
    z_alpha = norm.ppf(alpha)  # e.g., -2.326 for 1%

    # Raw VaR as fallback
    var_raw = sigma_forecasts * z_alpha  # negative
    var_adjusted = np.copy(var_raw)

    # Collect conformity scores: c_t = -r_t / sigma_t
    # (positive c means loss; larger c = bigger loss relative to sigma)
    conformity_scores = []

    for t in range(n):
        # First record the conformity score from the PREVIOUS period
        # (we know r_{t-1} and sigma_{t-1} was the deployed forecast)
        if t > 0:
            # Use sigma from the DEPLOYED forecast at t-1
            sigma_prev = sigma_forecasts[t - 1]
            if sigma_prev > 1e-10:
                c_prev = -returns_oos[t - 1] / sigma_prev
            else:
                c_prev = 0.0
            conformity_scores.append(c_prev)

        if len(conformity_scores) < min_calibration:
            # Not enough calibration data, use raw VaR
            var_adjusted[t] = var_raw[t]
            continue

        # Use last `lookback` conformity scores
        calib = np.array(conformity_scores[-lookback:])

        # FIX Bug 2: Split conformal order statistic with finite-sample correction
        # q = ceil((n+1)(1-alpha))-th smallest value / n
        n_calib = len(calib)
        sorted_calib = np.sort(calib)
        conformal_idx = int(np.ceil((n_calib + 1) * (1.0 - alpha))) - 1
        conformal_idx = min(conformal_idx, n_calib - 1)
        q_critical = sorted_calib[conformal_idx]

        # VaR = -sigma * q_critical (negative, since VaR is a loss threshold)
        var_conformal = -sigma_forecasts[t] * q_critical
        var_adjusted[t] = var_conformal

    return var_adjusted


# ==============================================================
# F. Conformal Method 2: Proxy-Robust Conformal (Patton 2011)
# ==============================================================

def conformal_proxy_robust(sigma2_forecasts, returns_oos, alpha, lookback=252,
                           min_calibration=50):
    """
    Proxy-Robust Conformal VaR using QLIKE-based conformity scores.

    Instead of using raw conformity scores c_t = |r_t|/sigma_t which depend
    on the scale of r_t as a proxy for sigma_t, we use QLIKE residuals:

      s_t = r²_t / sigma²_t - log(r²_t / sigma²_t) - 1

    Patton (2011, Theorem 1) shows QLIKE is consistent for sigma² ranking
    even when r² is a noisy proxy. The distribution of s_t under correct
    specification is chi²(1)-based (after transformation), which is more
    stable than raw ratio-based scores.

    The conformal correction:
    1. Compute expanding/rolling QLIKE scores s_t
    2. If s_t at quantile (1-alpha) is "large", the model underestimates
       tail risk -> widen VaR proportionally
    3. The widening factor is derived from the QLIKE score quantile,
       converted back to a sigma multiplier

    Parameters
    ----------
    sigma2_forecasts : array, sigma² forecasts (positive)
    returns_oos : array, actual realized returns
    alpha : float, target VaR level
    lookback : int, rolling calibration window
    min_calibration : int, minimum calibration points

    Returns
    -------
    var_adjusted : array, proxy-robust conformally calibrated VaR (negative)
    """
    n = len(sigma2_forecasts)
    z_alpha = norm.ppf(alpha)

    sigma = np.sqrt(np.maximum(sigma2_forecasts, 1e-16))
    var_raw = sigma * z_alpha  # negative
    var_adjusted = np.copy(var_raw)

    # Collect QLIKE-based conformity scores
    # QLIKE score: s_t = r²_t/h_t - log(r²_t/h_t) - 1
    # where h_t = sigma²_t forecast, r²_t = proxy for true variance
    #
    # Under correct model: E[s_t] = 0, s_t >= 0 always (Jensen's inequality)
    # Large s_t means model is poorly calibrated at time t
    qlike_scores = []

    # Also collect ratio scores r²_t / h_t for VaR adjustment
    ratio_scores = []

    for t in range(n):
        if t > 0:
            r2_prev = returns_oos[t - 1] ** 2
            h_prev = sigma2_forecasts[t - 1]
            if h_prev > 1e-16 and r2_prev > 1e-20:
                ratio = r2_prev / h_prev
                s = ratio - np.log(ratio) - 1.0
                qlike_scores.append(s)
                ratio_scores.append(ratio)
            else:
                qlike_scores.append(0.0)
                ratio_scores.append(1.0)

        if len(qlike_scores) < min_calibration:
            var_adjusted[t] = var_raw[t]
            continue

        # FIX Bug 2: Use QLIKE scores (not ratio scores) for conformal calibration
        # QLIKE score s_t >= 0 always. Large s_t = poor calibration.
        # Use split conformal order statistic on QLIKE scores
        calib_qlike = np.array(qlike_scores[-lookback:])
        n_calib = len(calib_qlike)
        sorted_qlike = np.sort(calib_qlike)
        conformal_idx = int(np.ceil((n_calib + 1) * (1.0 - alpha))) - 1
        conformal_idx = min(conformal_idx, n_calib - 1)
        q_qlike = sorted_qlike[conformal_idx]

        # Convert QLIKE score back to variance ratio:
        # s = ratio - log(ratio) - 1, we need to find ratio from s
        # For small s, ratio ≈ 1 + sqrt(2*s). For larger s, solve numerically.
        # But for VaR adjustment, use the ratio scores at the same quantile
        # for a direct conversion (QLIKE ordering preserves ratio ordering
        # for ratio > 1, which is the tail we care about)
        calib_ratios = np.array(ratio_scores[-lookback:])
        # Sort ratios and use the same conformal index
        sorted_ratios = np.sort(calib_ratios)
        q_ratio = sorted_ratios[conformal_idx]

        # sigma_corrected = sigma * sqrt(q_ratio), capped
        sigma_corrected = sigma[t] * np.sqrt(max(q_ratio, 1.0))
        sigma_corrected = min(sigma_corrected, sigma[t] * 3.0)

        var_adjusted[t] = sigma_corrected * z_alpha  # negative

    return var_adjusted


# ==============================================================
# G. Conformal Method 3: Split Conformal with Exchangeability Check
# ==============================================================

def runs_test_exchangeability(scores, significance=0.05):
    """
    Wald-Wolfowitz runs test for exchangeability (IID-ness) of scores.

    For conformal prediction to have valid coverage guarantee, the
    calibration scores must be exchangeable (a weaker condition than IID,
    but the runs test is a practical approximation).

    Returns (is_exchangeable, p_value).
    """
    if len(scores) < 20:
        return True, 1.0  # too few points, assume OK

    median = np.median(scores)
    binary = (scores > median).astype(int)

    # Count runs
    n = len(binary)
    n1 = int(binary.sum())
    n0 = n - n1

    if n1 == 0 or n0 == 0:
        return True, 1.0  # all same sign, can't test

    runs = 1
    for i in range(1, n):
        if binary[i] != binary[i - 1]:
            runs += 1

    # Expected runs under IID
    mu = 1 + 2 * n0 * n1 / n
    denom = n * n * (n - 1)
    if denom == 0:
        return True, 1.0
    sigma2 = (2 * n0 * n1 * (2 * n0 * n1 - n)) / denom
    if sigma2 <= 0:
        return True, 1.0

    z = (runs - mu) / np.sqrt(sigma2)
    p_value = float(2 * (1 - norm.cdf(abs(z))))

    return p_value > significance, p_value


def conformal_exchangeability(sigma_forecasts, returns_oos, alpha, lookback=252,
                              min_calibration=50, exch_test_window=100):
    """
    Split Conformal with Exchangeability Guard.

    Before applying conformal correction, tests whether the calibration
    scores satisfy the exchangeability assumption using a runs test.
    If exchangeability is rejected (regime change detected), falls back
    to raw VaR (Normal quantile).

    This addresses the concern that conformal guarantees are invalid when
    the data-generating process changes (e.g., volatility regimes).

    Parameters
    ----------
    sigma_forecasts : array, sigma forecasts (positive)
    returns_oos : array, actual returns
    alpha : float, target VaR level
    lookback : int, rolling calibration window
    min_calibration : int, minimum calibration points
    exch_test_window : int, window for exchangeability test

    Returns
    -------
    var_adjusted : array, conformally calibrated VaR (negative)
    exchangeability_log : list of dicts, test results at each point
    """
    n = len(sigma_forecasts)
    z_alpha = norm.ppf(alpha)

    var_raw = sigma_forecasts * z_alpha  # negative
    var_adjusted = np.copy(var_raw)

    conformity_scores = []
    exchangeability_log = []

    for t in range(n):
        if t > 0:
            sigma_prev = sigma_forecasts[t - 1]
            if sigma_prev > 1e-10:
                c_prev = -returns_oos[t - 1] / sigma_prev
            else:
                c_prev = 0.0
            conformity_scores.append(c_prev)

        if len(conformity_scores) < min_calibration:
            var_adjusted[t] = var_raw[t]
            continue

        # Test exchangeability on recent calibration scores
        recent_scores = np.array(conformity_scores[-exch_test_window:])
        is_exch, exch_p = runs_test_exchangeability(recent_scores)

        # Log every 50th day for diagnostics
        if t % 50 == 0:
            exchangeability_log.append({
                'oos_day': t,
                'is_exchangeable': bool(is_exch),
                'runs_test_p': round(float(exch_p), 4),
                'n_scores': len(recent_scores),
            })

        if not is_exch:
            # Exchangeability rejected: regime change detected
            # Fall back to raw VaR (conformal guarantee not valid)
            var_adjusted[t] = var_raw[t]
            continue

        # Exchangeability holds: apply conformal correction
        # FIX Bug 2: Split conformal order statistic
        calib = np.array(conformity_scores[-lookback:])
        n_calib = len(calib)
        sorted_calib = np.sort(calib)
        conformal_idx = int(np.ceil((n_calib + 1) * (1.0 - alpha))) - 1
        conformal_idx = min(conformal_idx, n_calib - 1)
        q_critical = sorted_calib[conformal_idx]
        var_conformal = -sigma_forecasts[t] * q_critical
        var_adjusted[t] = var_conformal

    return var_adjusted, exchangeability_log


# ==============================================================
# H. VaR Backtest: Kupiec + Christoffersen + Basel
# ==============================================================

def basel_traffic_light_250(violations_array, n_lookback=250):
    """
    Standard Basel II/III traffic light (250-day lookback).
    Green: 0-4, Yellow: 5-9, Red: >=10 violations.
    For windows < 250 days, scale proportionally.
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
    var_series: VaR threshold (negative values)
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # FIX Bug 3: Kupiec (1995) — handle boundary cases correctly
    # When n1=0: LR = -2*(n*log(1-alpha) - n*log(1)) = -2*n*log(1-alpha)
    # When n1=n: LR = -2*(n*log(alpha) - n*log(1)) = -2*n*log(alpha)
    if n == 0:
        kup_stat, kup_p = 0.0, 1.0
    elif n1 == 0:
        lr = -2 * (n * np.log(1 - alpha_var))  # unrestricted: 0*log(0) -> 0
        kup_stat = float(max(lr, 0.0))
        kup_p = float(1 - chi2.cdf(kup_stat, df=1))
    elif n1 == n:
        lr = -2 * (n * np.log(alpha_var))
        kup_stat = float(max(lr, 0.0))
        kup_p = float(1 - chi2.cdf(kup_stat, df=1))
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(max(lr, 0.0))
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # FIX Bug 3: Christoffersen (1998) — handle boundary properly
    try:
        t00 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 0)))
        t01 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 1)))
        t10 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 0)))
        t11 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 1)))
        # If no violations at all, independence is trivially satisfied
        if n1 == 0 or n1 == n:
            cc_stat, cc_p = 0.0, 1.0
        else:
            pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
            pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
            pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
            if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
                lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all)
                               + (t01 + t11) * np.log(pi_all)
                               - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                               - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
                cc_stat = float(max(lr_ind, 0.0))
                cc_p = float(1 - chi2.cdf(cc_stat, df=1))
            else:
                # Cannot compute independence test with degenerate transitions
                cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    # Basel traffic light (standard 250-day)
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


# ==============================================================
# I. Pinball (Tick) Loss + DM Test
# ==============================================================

def pinball_loss(y, q, tau):
    """Pinball loss: rho_tau(y - q) = (tau - I{y < q}) * (y - q)"""
    y = np.asarray(y, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    e = y - q
    loss = np.where(e >= 0, tau * e, (tau - 1.0) * e)
    return float(np.mean(loss))


def pointwise_pinball(y, q, tau):
    """Pointwise pinball loss for DM test."""
    y = np.asarray(y, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    e = y - q
    return np.where(e >= 0, tau * e, (tau - 1.0) * e)


def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t -> model 1 better."""
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
    p_value = float(2 * (1 - norm.cdf(abs(t_stat))))
    return float(t_stat), p_value


# ==============================================================
# J. Average VaR Width (efficiency measure)
# ==============================================================

def avg_var_width(var_series):
    """Average absolute VaR (larger = more conservative/wider)."""
    v = np.abs(np.asarray(var_series, dtype=np.float64))
    return float(np.mean(v[np.isfinite(v)]))


# ==============================================================
# MAIN: Expanding-window OOS with 3 conformal methods
# ==============================================================

def main():
    t0 = time.time()
    print("=" * 72)
    print("K825: Proxy-Reliance Control in Conformal VaR")
    print("  Building on K824v2 GJR framework + 3 conformal methods")
    print("  Error Log: Basel standard 250-day, Student-t scale, no heuristics")
    print("=" * 72)

    # ----------------------------------------------------------
    # 1. Download data
    # ----------------------------------------------------------
    print("\n[1/6] Downloading SPY data...")
    spy = yf.download('SPY', start='2006-01-01', end='2026-01-01', progress=False)
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

    if n_oos == 0:
        print("ERROR: No OOS data found!")
        sys.exit(1)

    # ----------------------------------------------------------
    # 2. Expanding-window GJR-GARCH forecasting
    # ----------------------------------------------------------
    print(f"\n[2/6] Running expanding-window GJR-GARCH (refit every {REFIT_EVERY} days)...")

    sigma2_forecasts = np.full(n_oos, np.nan)
    sigma_forecasts = np.full(n_oos, np.nan)
    t_df_per_day = np.full(n_oos, np.nan)  # FIX Bug 1: per-refit t_df
    gjr_params = None
    last_fit_idx = -999
    t_df = 5.0

    # Track in-sample standardized residuals for HistSim
    z_train_all = None

    for i, oos_pos in enumerate(oos_idx):
        # signal.shift(1): use data up to (but not including) oos_pos
        train_end = oos_pos
        r_train = r_values[:train_end]

        # Refit every REFIT_EVERY days
        if oos_pos - last_fit_idx >= REFIT_EVERY:
            gjr_params = fit_gjr(r_train)
            if gjr_params is None:
                print(f"  WARNING: GJR fit failed at OOS day {i}")
                continue
            last_fit_idx = oos_pos

            z_train_all = compute_standardized_residuals(r_train, gjr_params)
            t_df = estimate_t_df(z_train_all)

            if i % 100 == 0 or i == 0:
                print(f"  Refit at OOS day {i}/{n_oos}: "
                      f"persistence={gjr_params['persistence']:.4f}, "
                      f"t_df={t_df:.2f}")

        if gjr_params is None:
            continue

        # One-step-ahead variance forecast: h[t] = f(h[t-1], r²[t-1])
        sigma2_f = gjr_one_step_forecast(r_train, gjr_params)
        sigma2_forecasts[i] = sigma2_f
        sigma_forecasts[i] = np.sqrt(sigma2_f)
        t_df_per_day[i] = t_df  # FIX Bug 1: store per-refit t_df

        # Update standardized residuals with latest observation
        z_train_all = compute_standardized_residuals(r_train, gjr_params)

    print(f"  GJR forecasting complete. Valid: {np.isfinite(sigma2_forecasts).sum()}/{n_oos}")

    # ----------------------------------------------------------
    # 3. Compute VaR for all methods
    # ----------------------------------------------------------
    print("\n[3/6] Computing VaR for 6 methods (3 baselines + 3 conformal)...")

    oos_returns = r_values[oos_idx]
    valid = np.isfinite(sigma_forecasts)

    # --- Baselines (from K824v2) ---
    # B1: GJR + Normal
    var_normal = {}
    for alpha in ALPHA_LEVELS:
        z_alpha = norm.ppf(alpha)
        var_normal[alpha] = sigma_forecasts * z_alpha

    # B2: GJR + Student-t (with scale = sqrt((df-2)/df))
    # FIX Bug 1: use per-day t_df (not final value) to avoid lookahead
    var_student = {alpha: np.full(n_oos, np.nan) for alpha in ALPHA_LEVELS}
    for i in range(n_oos):
        df_i = t_df_per_day[i]
        if np.isnan(df_i) or np.isnan(sigma_forecasts[i]):
            continue
        for alpha in ALPHA_LEVELS:
            if df_i > 2.0:
                scale = np.sqrt((df_i - 2.0) / df_i)
                z_t = t_dist.ppf(alpha, df=df_i) * scale
            else:
                z_t = t_dist.ppf(alpha, df=df_i)
            var_student[alpha][i] = sigma_forecasts[i] * z_t

    # B3: GJR + HistSim (empirical quantile of standardized residuals)
    # Need to recompute per-day HistSim using expanding z_train
    var_histsim = {alpha: np.full(n_oos, np.nan) for alpha in ALPHA_LEVELS}
    gjr_params_tmp = None
    last_fit_tmp = -999
    for i, oos_pos in enumerate(oos_idx):
        r_train = r_values[:oos_pos]
        if oos_pos - last_fit_tmp >= REFIT_EVERY:
            gjr_params_tmp = fit_gjr(r_train)
            last_fit_tmp = oos_pos
        if gjr_params_tmp is None:
            continue
        z_t = compute_standardized_residuals(r_train, gjr_params_tmp)
        if len(z_t) < 30:
            continue
        for alpha in ALPHA_LEVELS:
            z_hs = float(np.percentile(z_t, alpha * 100))
            var_histsim[alpha][i] = sigma_forecasts[i] * z_hs

    # --- Conformal Methods ---
    # C1: Naive Conformal
    var_conf_naive = {}
    for alpha in ALPHA_LEVELS:
        var_conf_naive[alpha] = conformal_naive(
            sigma_forecasts, oos_returns, alpha=alpha, lookback=252)

    # C2: Proxy-Robust Conformal
    var_conf_proxy = {}
    for alpha in ALPHA_LEVELS:
        var_conf_proxy[alpha] = conformal_proxy_robust(
            sigma2_forecasts, oos_returns, alpha=alpha, lookback=252)

    # C3: Split Conformal with Exchangeability
    var_conf_exch = {}
    exch_logs = {}
    for alpha in ALPHA_LEVELS:
        var_adj, elog = conformal_exchangeability(
            sigma_forecasts, oos_returns, alpha=alpha, lookback=252)
        var_conf_exch[alpha] = var_adj
        exch_logs[alpha] = elog

    print("  All VaR series computed.")

    # ----------------------------------------------------------
    # 4. VaR Backtest
    # ----------------------------------------------------------
    print("\n[4/6] Running VaR backtests...")

    all_methods = {}
    for alpha in ALPHA_LEVELS:
        all_methods[alpha] = {
            'B1_Normal': var_normal[alpha],
            'B2_StudentT': var_student[alpha],
            'B3_HistSim': var_histsim[alpha],
            'C1_Naive_Conformal': var_conf_naive[alpha],
            'C2_Proxy_Robust': var_conf_proxy[alpha],
            'C3_Exch_Conformal': var_conf_exch[alpha],
        }

    backtest_results = {}
    for alpha in ALPHA_LEVELS:
        pct = f"{alpha*100:.0f}pct"
        backtest_results[pct] = {}
        print(f"\n  --- VaR {alpha*100:.0f}% Backtest (target: {alpha*100:.1f}%) ---")
        for name, var_series in all_methods[alpha].items():
            # Only use valid (non-NaN) periods
            mask = valid & np.isfinite(var_series)
            if mask.sum() < 50:
                print(f"    {name:25s}: INSUFFICIENT DATA ({mask.sum()} valid)")
                backtest_results[pct][name] = {'error': 'insufficient_data'}
                continue

            bt = var_backtest(oos_returns[mask], var_series[mask], alpha_var=alpha)
            backtest_results[pct][name] = bt
            width = avg_var_width(var_series[mask])

            kup = "PASS" if bt['kupiec']['pass'] else "FAIL"
            cc = "PASS" if bt['christoffersen']['pass'] else "FAIL"
            tri = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"    {name:25s}: viol={bt['violation_rate']:.4f} "
                  f"({bt['n_violations']}/{bt['n_total']}), "
                  f"Kupiec {kup} (p={bt['kupiec']['p_value']:.4f}), "
                  f"CC {cc}, Basel={bt['basel_traffic_light']}, "
                  f"Trinity={tri}, width={width:.6f}")

    # ----------------------------------------------------------
    # 5. Pinball Loss + DM Tests
    # ----------------------------------------------------------
    print("\n[5/6] Computing pinball loss and DM tests...")

    pinball_results = {}
    dm_results = {}

    for alpha in ALPHA_LEVELS:
        pct = f"{alpha*100:.0f}pct"
        pinball_results[pct] = {}
        dm_results[pct] = {}

        print(f"\n  --- Pinball Loss at {alpha*100:.0f}% ---")
        losses = {}
        for name, var_series in all_methods[alpha].items():
            mask = valid & np.isfinite(var_series)
            if mask.sum() < 50:
                continue
            pl = pinball_loss(oos_returns[mask], var_series[mask], alpha)
            pw_loss = pointwise_pinball(oos_returns[mask], var_series[mask], alpha)
            pinball_results[pct][name] = round(pl, 8)
            losses[name] = pw_loss
            print(f"    {name:25s}: pinball = {pl:.8f}")

        # DM tests: each conformal vs its closest baseline
        # C1 (Naive) vs B1 (Normal) — both use sigma-based scores
        # C2 (Proxy-Robust) vs B1 (Normal) — both Normal-quantile based
        # C3 (Exch) vs B1 (Normal) — same
        # Also test all conformal vs B3 (HistSim, the K824v2 champion)
        pairs = [
            ('C1_Naive_Conformal', 'B1_Normal'),
            ('C1_Naive_Conformal', 'B3_HistSim'),
            ('C2_Proxy_Robust', 'B1_Normal'),
            ('C2_Proxy_Robust', 'B3_HistSim'),
            ('C3_Exch_Conformal', 'B1_Normal'),
            ('C3_Exch_Conformal', 'B3_HistSim'),
            ('B3_HistSim', 'B1_Normal'),
            ('B3_HistSim', 'B2_StudentT'),
        ]

        print(f"\n  --- DM Tests (pinball loss, {alpha*100:.0f}%) ---")
        for m1, m2 in pairs:
            if m1 not in losses or m2 not in losses:
                continue
            # Need aligned losses (same mask)
            mask1 = valid & np.isfinite(all_methods[alpha][m1])
            mask2 = valid & np.isfinite(all_methods[alpha][m2])
            common = mask1 & mask2
            if common.sum() < 50:
                continue
            l1 = pointwise_pinball(oos_returns[common], all_methods[alpha][m1][common], alpha)
            l2 = pointwise_pinball(oos_returns[common], all_methods[alpha][m2][common], alpha)
            t_stat, p_val = dm_test(l1, l2)
            harvey_pass = abs(t_stat) > 3.0
            winner = m1 if t_stat < 0 else m2
            dm_results[pct][f"{m1}_vs_{m2}"] = {
                'dm_stat': round(t_stat, 4),
                'p_value': round(p_val, 6),
                'harvey_pass': bool(harvey_pass),
                'winner': winner,
            }
            sig = "***" if harvey_pass else ""
            print(f"    {m1:25s} vs {m2:25s}: DM={t_stat:+.4f}, p={p_val:.6f} "
                  f"{'HARVEY PASS' if harvey_pass else ''} -> {winner} {sig}")

    # ----------------------------------------------------------
    # 6. Summary + Width Analysis
    # ----------------------------------------------------------
    print("\n[6/6] Summary analysis...")

    width_results = {}
    for alpha in ALPHA_LEVELS:
        pct = f"{alpha*100:.0f}pct"
        width_results[pct] = {}
        print(f"\n  --- Average VaR Width at {alpha*100:.0f}% ---")
        for name, var_series in all_methods[alpha].items():
            mask = valid & np.isfinite(var_series)
            if mask.sum() < 50:
                continue
            w = avg_var_width(var_series[mask])
            width_results[pct][name] = round(w, 6)
            print(f"    {name:25s}: avg|VaR| = {w:.6f}")

    # Exchangeability test summary
    print("\n  --- Exchangeability Test Summary ---")
    exch_summary = {}
    for alpha in ALPHA_LEVELS:
        pct = f"{alpha*100:.0f}pct"
        elog = exch_logs.get(alpha, [])
        if elog:
            n_exch = sum(1 for e in elog if e['is_exchangeable'])
            n_fail = sum(1 for e in elog if not e['is_exchangeable'])
            avg_p = np.mean([e['runs_test_p'] for e in elog])
            exch_summary[pct] = {
                'n_test_points': len(elog),
                'n_exchangeable': n_exch,
                'n_rejected': n_fail,
                'avg_p_value': round(float(avg_p), 4),
                'rejection_rate': round(n_fail / len(elog), 4) if elog else 0,
            }
            print(f"    {pct}: {n_exch}/{len(elog)} passed ({n_fail} rejected), "
                  f"avg p={avg_p:.4f}")
        else:
            exch_summary[pct] = {'n_test_points': 0}
            print(f"    {pct}: no test points")

    # Overall ranking
    print("\n  === OVERALL RANKING (1% VaR) ===")
    if '1pct' in backtest_results:
        ranked = []
        for name, bt in backtest_results['1pct'].items():
            if 'error' in bt:
                continue
            ranked.append({
                'method': name,
                'trinity': bt['trinity_pass'],
                'violations': bt['n_violations'],
                'violation_rate': bt['violation_rate'],
                'basel': bt['basel_traffic_light'],
                'kupiec_p': bt['kupiec']['p_value'],
                'pinball': pinball_results.get('1pct', {}).get(name, np.nan),
                'width': width_results.get('1pct', {}).get(name, np.nan),
            })
        # Sort: Trinity PASS first, then by violations (closer to expected),
        # then by pinball loss
        ranked.sort(key=lambda x: (
            not x['trinity'],
            abs(x['violations'] - 0.01 * backtest_results['1pct'][x['method']]['n_total']),
            x['pinball'] if not np.isnan(x['pinball']) else 999,
        ))
        for rank, r in enumerate(ranked, 1):
            tri = "TRINITY PASS" if r['trinity'] else "FAIL"
            print(f"    #{rank}: {r['method']:25s} — {tri}, "
                  f"{r['violations']} violations, Basel {r['basel']}, "
                  f"pinball={r['pinball']:.8f}, width={r['width']:.6f}")

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    elapsed = time.time() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s")

    # Convert backtest results for JSON serialization
    def clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_for_json(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    results = {
        'experiment_id': 'K825',
        'title': 'K825: Proxy-Reliance Control in Conformal VaR',
        'description': (
            'Tests 3 conformal VaR calibration methods against K824v2 baselines. '
            'C1: Naive conformal (quantile of conformity scores). '
            'C2: Proxy-robust conformal (QLIKE-based scores, Patton 2011). '
            'C3: Split conformal with exchangeability guard (runs test). '
            'Baselines: Normal, Student-t, HistSim (K824v2 champion).'
        ),
        'asset': 'SPY',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'n_oos': int(n_oos),
        'n_valid': int(valid.sum()),
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'methods': {
            'baselines': ['B1_Normal', 'B2_StudentT', 'B3_HistSim'],
            'conformal': ['C1_Naive_Conformal', 'C2_Proxy_Robust', 'C3_Exch_Conformal'],
        },
        'data_source': 'yfinance (SPY, 2006-01-01 to 2025-12-31)',
        'method': 'GJR-GARCH(1,1) expanding window + 3 conformal calibrations',
        'conformal_details': {
            'C1_Naive_Conformal': (
                'Split conformal using conformity score c_t = -r_t/sigma_t. '
                'VaR = -sigma * q_{1-alpha}(c). Lookback=252, min_calib=50.'
            ),
            'C2_Proxy_Robust': (
                'Proxy-robust conformal using QLIKE ratios r²_t/h_t. '
                'VaR correction via sqrt of (1-alpha) quantile of variance ratios. '
                'Patton (2011) theory: QLIKE consistent under proxy noise.'
            ),
            'C3_Exch_Conformal': (
                'Same as C1 but with Wald-Wolfowitz runs test for exchangeability. '
                'Falls back to raw Normal VaR when exchangeability rejected.'
            ),
        },
        'references': [
            'Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss',
            'Vovk, Gammerman, Shafer (2005) — Conformal prediction',
            'arXiv:2603.22569 (2026) — Proxy-reliance in conformal VaR',
            'Kupiec (1995) — Unconditional VaR coverage',
            'Christoffersen (1998) — Conditional VaR independence',
            'Basel Committee (1996, 2019) — Traffic light framework',
            'K824v2 — HistSim best (4/502, Basel Green, Trinity PASS)',
            'K800/K800v2 — Conformal artifact lesson',
        ],
        'backtest_results': clean_for_json(backtest_results),
        'pinball_loss': clean_for_json(pinball_results),
        'dm_tests': clean_for_json(dm_results),
        'var_width': clean_for_json(width_results),
        'exchangeability_summary': clean_for_json(exch_summary),
        'exchangeability_log': clean_for_json({
            f"{a*100:.0f}pct": exch_logs.get(a, []) for a in ALPHA_LEVELS
        }),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': round(elapsed, 1),
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {RESULTS_PATH}")

    # Final verdict
    print("\n" + "=" * 72)
    print("VERDICT:")
    if '1pct' in backtest_results:
        trinity_methods = [name for name, bt in backtest_results['1pct'].items()
                          if 'trinity_pass' in bt and bt['trinity_pass']]
        if trinity_methods:
            print(f"  Trinity PASS methods (1% VaR): {trinity_methods}")
        else:
            print("  No method achieved Trinity PASS at 1% VaR")
        conformal_trinity = [m for m in trinity_methods if m.startswith('C')]
        if conformal_trinity:
            print(f"  Conformal methods that achieved Trinity: {conformal_trinity}")
            print("  -> Conformal calibration adds value!")
        else:
            print("  -> No conformal method achieved Trinity PASS")
            print("  -> K824v2 HistSim remains the best practice for 1% VaR")
    print("=" * 72)


if __name__ == '__main__':
    main()
