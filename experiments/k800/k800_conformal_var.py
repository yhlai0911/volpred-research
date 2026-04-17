#!/usr/bin/env python3
"""
K800: Conformal VaR Calibration — Can It Fix GJR's VaR Failure?
================================================================
[提出: 用戶, 執行: Claude]

Context:
  K799 showed GJR wins QLIKE (1.466 vs GARCH 1.510) but FAILS VaR 1%:
  - GJR: 1.99% violation rate (Kupiec p=0.049, FAIL)
  - GARCH: 1.39% (Kupiec PASS), HAR: 0.80% (PASS)
  Question: can post-hoc conformal calibration fix GJR's VaR without hurting QLIKE?

Method:
  Conformal prediction applied to VaR (inspired by arXiv:2602.03903):
  1. Compute VaR_t = -σ_t × z_α using model's σ forecast (shifted by 1 day)
  2. Track nonconformity scores: e_t = r_t - VaR_t
  3. Expanding-window conformal adjustment:
     - Maintain expanding set of past (violation_indicator, severity) pairs
     - If rolling violation_rate > α: widen VaR by multiplier
     - Multiplier = max(1, violation_rate_rolling / α)
     - This is conservative: only widens, never narrows

  Two conformal variants tested:
  A) "Simple": rolling 252-day violation rate → multiplicative widening
  B) "Quantile": expanding quantile of nonconformity scores → direct adjustment

Data: SPY 2006-2025, OOS: 2023-2024, expanding window, refit every 63 days
VaR: 1% left tail (99% confidence), Normal quantile for comparability with K799

signal.shift(1) enforced: forecast from t-1 data, evaluate against r_t

References:
  - arXiv:2602.03903 — Regime-Weighted Conformal VaR
  - Vovk, Gammerman, Shafer (2005) — Algorithmic Learning in a Random World
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust
  - Kupiec (1995) — unconditional VaR coverage
  - Christoffersen (1998) — conditional VaR independence
  - K799 — Grand Model Evaluation (GJR wins QLIKE, fails VaR)
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
from scipy.stats import norm, chi2, spearmanr

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k800_conformal_var_results.json')

# ==============================================================
# A. Numba-accelerated variance filters (from K799)
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
# B. Model fitting (from K799)
# ==============================================================

def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal)."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 100:
        return None
    rv = np.var(r)

    def negll(params, r):
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
        res = minimize(negll, [o0, a0, b0, g0], args=(r,),
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    return {'omega': float(best.x[0]), 'alpha': float(best.x[1]),
            'beta': float(best.x[2]), 'gamma': float(best.x[3]),
            'persistence': float(best.x[1] + best.x[2] + 0.5 * best.x[3])}


def fit_garch(returns, n_starts=4):
    """Fit GARCH(1,1) via quasi-MLE (Normal)."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 100:
        return None
    rv = np.var(r)

    def negll(params, r):
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
        res = minimize(negll, [o0, a0, b0], args=(r,),
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    return {'omega': float(best.x[0]), 'alpha': float(best.x[1]),
            'beta': float(best.x[2]),
            'persistence': float(best.x[1] + best.x[2])}


def fit_har_r2(sq_ret):
    """HAR-r²: r²_{t+1} = β₀ + β₁·r²_d + β₂·r²_w + β₃·r²_m (OLS)"""
    x = np.asarray(sq_ret, dtype=np.float64)
    n = len(x)
    if n < 52:
        return None
    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values
    valid_start = 22
    idx = np.arange(valid_start, n)
    Y = x[idx]
    X = np.column_stack([np.ones(len(idx)), x[idx - 1], ma5[idx - 1], ma22[idx - 1]])
    good = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if good.sum() < 30:
        return None
    Y, X = Y[good], X[good]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


# ==============================================================
# C. One-step-ahead forecasters (σ² forecast)
# ==============================================================

def fcast_gjr(returns, params):
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega'] + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def fcast_garch(returns, params):
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = garch_filter(r, params['omega'], params['alpha'], params['beta'])
    f = params['omega'] + params['alpha'] * r[-1] ** 2 + params['beta'] * s2[-1]
    return max(f, 1e-12)


def fcast_har(sq_ret, beta):
    n = len(sq_ret)
    if n < 22 or beta is None:
        return None
    f = (beta[0] + beta[1] * sq_ret[-1]
         + beta[2] * np.mean(sq_ret[-5:])
         + beta[3] * np.mean(sq_ret[-22:]))
    return max(f, 1e-12)


def fcast_ewma(sq_ret, lam=0.94):
    var = sq_ret[0]
    for i in range(1, len(sq_ret)):
        var = lam * var + (1 - lam) * sq_ret[i]
    return max(var, 1e-12)


# ==============================================================
# D. Conformal VaR Calibration Methods
# ==============================================================

def conformal_simple(raw_var_series, returns_oos, alpha=0.01, lookback=252):
    """
    Simple conformal VaR: track rolling violation rate, widen if > alpha.

    raw_var_series: array of raw VaR values (negative, left tail)
    returns_oos: array of actual OOS returns
    alpha: target violation rate (0.01 = 1%)
    lookback: rolling window for violation rate tracking

    Returns: adjusted VaR series (same length as input)
    """
    n = len(raw_var_series)
    adjusted_var = np.copy(raw_var_series)
    violations = np.zeros(n)

    for t in range(n):
        # Track violations up to (but not including) t
        if t > 0:
            violations[t-1] = 1.0 if returns_oos[t-1] < raw_var_series[t-1] else 0.0

        if t < lookback:
            # Not enough history for rolling window — use expanding
            if t > 0:
                viol_rate = np.mean(violations[:t])
            else:
                viol_rate = alpha  # no data yet, assume on-target
        else:
            viol_rate = np.mean(violations[t-lookback:t])

        # If violation rate exceeds target, widen VaR
        if viol_rate > alpha:
            multiplier = viol_rate / alpha
            # Cap multiplier at 3x to prevent extreme widening
            multiplier = min(multiplier, 3.0)
            adjusted_var[t] = raw_var_series[t] * multiplier
        # else: keep raw VaR (don't narrow — conservative)

    return adjusted_var


def conformal_quantile(raw_var_series, sigma_oos, returns_oos, alpha=0.01):
    """
    Quantile-based conformal VaR: use expanding quantile of nonconformity scores.

    Nonconformity score: s_t = (VaR_t - r_t) / σ_t  (positive = violation was severe)
    Adjusted VaR: VaR_t = -σ_t × quantile(past_scores, α)

    This directly learns the empirical distribution of standardized residuals,
    replacing the Normal z_α assumption with data-driven quantile.
    """
    n = len(raw_var_series)
    adjusted_var = np.copy(raw_var_series)
    z_alpha = norm.ppf(alpha)  # ≈ -2.326

    # Collect standardized residuals: r_t / σ_t
    std_residuals = []

    for t in range(n):
        sigma_t = sigma_oos[t]

        if t > 0:
            # Record standardized residual from previous period
            std_res = returns_oos[t-1] / sigma_oos[t-1] if sigma_oos[t-1] > 1e-10 else 0.0
            std_residuals.append(std_res)

        if len(std_residuals) >= 50:
            # Use expanding quantile of actual standardized residuals
            # instead of Normal z_α
            empirical_z = np.quantile(std_residuals, alpha)
            # Only adjust if empirical quantile is MORE negative than Normal
            # (i.e., fatter left tail than assumed)
            if empirical_z < z_alpha:
                adjusted_var[t] = sigma_t * empirical_z
            # else: keep raw VaR (Normal was conservative enough)

    return adjusted_var


# ==============================================================
# E. VaR Backtest (standalone, from K799/model_evaluation.py)
# ==============================================================

def var_backtest(returns, var_series, alpha=0.01):
    """
    VaR backtesting: Kupiec + Christoffersen + Basel traffic light.

    returns: actual returns
    var_series: VaR threshold (negative values, left tail)
    alpha: target violation rate
    """
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = violations.sum()
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0

    # Kupiec (1995) unconditional coverage test
    if n1 == 0 or n1 == n:
        kupiec_stat, kupiec_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha) + n0 * np.log(1 - alpha)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kupiec_stat = float(lr)
        kupiec_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen (1998) independence test
    try:
        t00 = np.sum((violations[:-1] == 0) & (violations[1:] == 0))
        t01 = np.sum((violations[:-1] == 0) & (violations[1:] == 1))
        t10 = np.sum((violations[:-1] == 1) & (violations[1:] == 0))
        t11 = np.sum((violations[:-1] == 1) & (violations[1:] == 1))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if pi01 > 0 and pi11 > 0 and pi_all > 0 and pi01 < 1 and pi11 < 1 and pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all) + (t01 + t11) * np.log(pi_all)
                          - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                          - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    # Basel traffic light
    if pi_hat <= alpha * 1.5:
        traffic = "green"
    elif pi_hat <= alpha * 2.0:
        traffic = "yellow"
    else:
        traffic = "red"

    return {
        "violation_rate": float(pi_hat),
        "expected_rate": float(alpha),
        "n_violations": int(n1),
        "n_total": int(n),
        "kupiec": {"stat": round(kupiec_stat, 4), "p_value": round(kupiec_p, 4),
                   "pass": kupiec_p > 0.05},
        "christoffersen": {"stat": round(cc_stat, 4), "p_value": round(cc_p, 4),
                           "pass": cc_p > 0.05},
        "basel_traffic_light": traffic,
        "trinity_pass": kupiec_p > 0.05 and cc_p > 0.05 and traffic == "green",
    }


# ==============================================================
# F. QLIKE metrics
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
    """DM test with Newey-West HAC. Negative t → model 1 better."""
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
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
    from scipy.stats import t as t_dist
    t_stat = d_mean / se
    p_val = 2 * (1 - t_dist.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ==============================================================
# G. Main experiment
# ==============================================================

def main():
    t_start = time.time()
    print("=" * 70)
    print("K800: Conformal VaR Calibration — Can It Fix GJR's VaR Failure?")
    print("=" * 70)

    # ── 1. Download data ──
    print("\n[1/5] Downloading SPY data...")
    spy = yf.download("SPY", start="2006-01-01", end="2025-12-31",
                       auto_adjust=True, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.sort_index()
    close = spy['Close'].dropna()
    returns = close.pct_change().dropna()
    dates = returns.index
    r = returns.values.astype(np.float64)
    r2 = r ** 2
    n_total = len(r)
    print(f"  Total observations: {n_total} ({dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')})")

    # ── 2. Define OOS period ──
    oos_start = pd.Timestamp("2023-01-01")
    oos_end = pd.Timestamp("2024-12-31")
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    is_end = oos_indices[0]  # first OOS index (all data before this for initial fit)
    print(f"  OOS period: {dates[oos_indices[0]].strftime('%Y-%m-%d')} to "
          f"{dates[oos_indices[-1]].strftime('%Y-%m-%d')} ({n_oos} obs)")
    print(f"  IS before OOS: {is_end} obs")

    # ── 3. Expanding-window OOS forecasts ──
    print("\n[2/5] Computing expanding-window OOS forecasts (refit every 63 days)...")
    refit_every = 63
    alpha_var = 0.01
    z_alpha = norm.ppf(alpha_var)  # ≈ -2.326

    # Storage for forecasts
    gjr_sigma2 = np.full(n_oos, np.nan)
    garch_sigma2 = np.full(n_oos, np.nan)
    har_sigma2 = np.full(n_oos, np.nan)
    ewma_sigma2 = np.full(n_oos, np.nan)

    # Current model params
    gjr_params = None
    garch_params = None
    har_beta = None
    last_refit = -refit_every  # force initial fit

    for i, oos_idx in enumerate(oos_indices):
        # Expanding window: all data up to (but not including) oos_idx
        # signal.shift(1): we use data up to t-1 to forecast t
        train_r = r[:oos_idx]
        train_r2 = r2[:oos_idx]

        # Refit models periodically
        if i - last_refit >= refit_every:
            gjr_params = fit_gjr(train_r)
            garch_params = fit_garch(train_r)
            har_beta = fit_har_r2(train_r2)
            last_refit = i
            if i == 0:
                print(f"  Initial fit at OOS[0], GJR persistence: "
                      f"{gjr_params['persistence']:.4f}" if gjr_params else "  GJR fit failed!")

        # One-step-ahead σ² forecasts
        if gjr_params:
            gjr_sigma2[i] = fcast_gjr(train_r, gjr_params)
        if garch_params:
            garch_sigma2[i] = fcast_garch(train_r, garch_params)
        if har_beta is not None:
            f = fcast_har(train_r2, har_beta)
            if f is not None:
                har_sigma2[i] = f
        ewma_sigma2[i] = fcast_ewma(train_r2)

        if (i + 1) % 100 == 0:
            print(f"  ... {i+1}/{n_oos} forecasts done")

    print(f"  All {n_oos} forecasts complete.")

    # ── 4. Compute raw VaR and conformal adjustments ──
    print("\n[3/5] Computing raw VaR + conformal calibrations...")

    returns_oos = r[oos_indices]
    r2_oos = r2[oos_indices]

    # σ forecasts (sqrt of σ²)
    gjr_sigma = np.sqrt(np.maximum(gjr_sigma2, 1e-16))
    garch_sigma = np.sqrt(np.maximum(garch_sigma2, 1e-16))
    har_sigma = np.sqrt(np.maximum(har_sigma2, 1e-16))
    ewma_sigma = np.sqrt(np.maximum(ewma_sigma2, 1e-16))

    # Raw VaR (Normal quantile)
    gjr_var_raw = gjr_sigma * z_alpha
    garch_var_raw = garch_sigma * z_alpha
    har_var_raw = har_sigma * z_alpha
    ewma_var_raw = ewma_sigma * z_alpha

    # Conformal Simple (rolling 252-day violation tracking)
    gjr_var_conf_s = conformal_simple(gjr_var_raw, returns_oos, alpha=alpha_var, lookback=252)
    garch_var_conf_s = conformal_simple(garch_var_raw, returns_oos, alpha=alpha_var, lookback=252)

    # Conformal Quantile (expanding quantile of standardized residuals)
    gjr_var_conf_q = conformal_quantile(gjr_var_raw, gjr_sigma, returns_oos, alpha=alpha_var)
    garch_var_conf_q = conformal_quantile(garch_var_raw, garch_sigma, returns_oos, alpha=alpha_var)

    # ── 5. Evaluate all variants ──
    print("\n[4/5] Running VaR backtests + QLIKE evaluation...")

    # Build evaluation dict
    models = {
        "GJR_raw": {"sigma2": gjr_sigma2, "var": gjr_var_raw, "sigma": gjr_sigma},
        "GJR_conformal_simple": {"sigma2": gjr_sigma2, "var": gjr_var_conf_s, "sigma": gjr_sigma},
        "GJR_conformal_quantile": {"sigma2": gjr_sigma2, "var": gjr_var_conf_q, "sigma": gjr_sigma},
        "GARCH_raw": {"sigma2": garch_sigma2, "var": garch_var_raw, "sigma": garch_sigma},
        "GARCH_conformal_simple": {"sigma2": garch_sigma2, "var": garch_var_conf_s, "sigma": garch_sigma},
        "GARCH_conformal_quantile": {"sigma2": garch_sigma2, "var": garch_var_conf_q, "sigma": garch_sigma},
        "HAR_raw": {"sigma2": har_sigma2, "var": har_var_raw, "sigma": har_sigma},
        "EWMA_raw": {"sigma2": ewma_sigma2, "var": ewma_var_raw, "sigma": ewma_sigma},
    }

    # QLIKE (conformal doesn't change σ² forecasts, so QLIKE is the same for raw vs conformal)
    print("\n  QLIKE on r² (lower is better):")
    qlike_results = {}
    for name, data in models.items():
        q = qlike_score(r2_oos, data["sigma2"])
        qlike_results[name] = round(q, 6)
        print(f"    {name:30s}: {q:.6f}")

    # VaR backtest
    print(f"\n  VaR {alpha_var*100:.0f}% Backtest (target violation: {alpha_var*100:.1f}%):")
    var_results = {}
    for name, data in models.items():
        vb = var_backtest(returns_oos, data["var"], alpha=alpha_var)
        var_results[name] = vb
        kupiec_pass = "PASS" if vb["kupiec"]["pass"] else "FAIL"
        cc_pass = "PASS" if vb["christoffersen"]["pass"] else "FAIL"
        trinity = "PASS" if vb["trinity_pass"] else "FAIL"
        print(f"    {name:30s}: viol={vb['violation_rate']:.4f} "
              f"({vb['n_violations']}/{vb['n_total']}), "
              f"Kupiec {kupiec_pass} (p={vb['kupiec']['p_value']:.4f}), "
              f"CC {cc_pass}, Basel={vb['basel_traffic_light']}, "
              f"Trinity={trinity}")

    # Spearman rank correlation
    print("\n  Spearman rank correlation (σ² forecast vs r²):")
    spearman_results = {}
    for name in ["GJR_raw", "GARCH_raw", "HAR_raw", "EWMA_raw"]:
        rho, p = spearmanr(r2_oos, models[name]["sigma2"])
        spearman_results[name] = {"rho": round(float(rho), 4), "p_value": round(float(p), 6)}
        print(f"    {name:30s}: ρ={rho:.4f} (p={p:.6f})")

    # DM tests: GJR raw vs others (QLIKE losses)
    print("\n  DM tests (GJR_raw as reference, QLIKE loss):")
    dm_results = {}
    gjr_losses = pointwise_qlike(r2_oos, gjr_sigma2)
    for other in ["GARCH_raw", "HAR_raw", "EWMA_raw"]:
        other_losses = pointwise_qlike(r2_oos, models[other]["sigma2"])
        t_stat, p_val = dm_test(gjr_losses, other_losses)
        dm_results[f"GJR_vs_{other}"] = {
            "dm_stat": round(t_stat, 4),
            "p_value": round(p_val, 6),
            "harvey_pass": abs(t_stat) > 3.0,
            "better": "GJR_raw" if t_stat < 0 else other,
        }
        harvey = "PASS" if abs(t_stat) > 3.0 else "FAIL"
        better = "GJR" if t_stat < 0 else other.split("_")[0]
        print(f"    GJR vs {other:15s}: DM={t_stat:+.4f}, p={p_val:.6f}, "
              f"Harvey {harvey}, better={better}")

    # ── 6. Summary analysis ──
    print("\n[5/5] Summary analysis...")

    # Did conformal fix GJR's VaR?
    gjr_raw_fixed = var_results["GJR_raw"]["kupiec"]["pass"]
    gjr_cs_fixed = var_results["GJR_conformal_simple"]["kupiec"]["pass"]
    gjr_cq_fixed = var_results["GJR_conformal_quantile"]["kupiec"]["pass"]

    print(f"\n  GJR VaR fix analysis:")
    print(f"    GJR raw Kupiec:               {'PASS' if gjr_raw_fixed else 'FAIL'} "
          f"(viol={var_results['GJR_raw']['violation_rate']:.4f})")
    print(f"    GJR + conformal simple Kupiec: {'PASS' if gjr_cs_fixed else 'FAIL'} "
          f"(viol={var_results['GJR_conformal_simple']['violation_rate']:.4f})")
    print(f"    GJR + conformal quantile Kupiec: {'PASS' if gjr_cq_fixed else 'FAIL'} "
          f"(viol={var_results['GJR_conformal_quantile']['violation_rate']:.4f})")

    # QLIKE preservation check
    print(f"\n  QLIKE preservation (conformal doesn't change σ² forecast):")
    print(f"    GJR QLIKE: {qlike_results['GJR_raw']:.6f} (same for all GJR variants)")
    print(f"    GARCH QLIKE: {qlike_results['GARCH_raw']:.6f}")

    # Did conformal hurt GARCH (already passing)?
    garch_raw_pass = var_results["GARCH_raw"]["kupiec"]["pass"]
    garch_cs_pass = var_results["GARCH_conformal_simple"]["kupiec"]["pass"]
    garch_cq_pass = var_results["GARCH_conformal_quantile"]["kupiec"]["pass"]
    print(f"\n  GARCH stability check (should remain PASS):")
    print(f"    GARCH raw:              {'PASS' if garch_raw_pass else 'FAIL'}")
    print(f"    GARCH + conformal simple:  {'PASS' if garch_cs_pass else 'FAIL'}")
    print(f"    GARCH + conformal quantile: {'PASS' if garch_cq_pass else 'FAIL'}")

    # Best combined model
    best_combined = None
    for name in ["GJR_conformal_simple", "GJR_conformal_quantile"]:
        if var_results[name]["trinity_pass"]:
            best_combined = name
            break
    if best_combined is None:
        for name in ["GJR_conformal_simple", "GJR_conformal_quantile"]:
            if var_results[name]["kupiec"]["pass"]:
                best_combined = name
                break

    conclusion = ""
    if best_combined:
        conclusion = (f"YES — {best_combined} fixes GJR's VaR failure while preserving "
                      f"QLIKE advantage ({qlike_results['GJR_raw']:.6f} vs "
                      f"GARCH {qlike_results['GARCH_raw']:.6f}). "
                      f"Conformal calibration is a viable post-hoc fix.")
    else:
        conclusion = ("NO — Conformal calibration could not fully fix GJR's VaR in this "
                      "OOS period. GJR's excess violations may be structural (tail "
                      "underestimation from Normal distribution assumption).")

    print(f"\n  CONCLUSION: {conclusion}")

    # ── 7. Save results ──
    elapsed = time.time() - t_start
    results = {
        "experiment_id": "K800",
        "title": "Conformal VaR Calibration — Can It Fix GJR's VaR Failure?",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance",
        "asset": "SPY",
        "full_period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
        "oos_period": f"{dates[oos_indices[0]].strftime('%Y-%m-%d')} to {dates[oos_indices[-1]].strftime('%Y-%m-%d')}",
        "n_total": int(n_total),
        "n_oos": int(n_oos),
        "refit_every": refit_every,
        "alpha_var": alpha_var,
        "conformal_methods": {
            "simple": "Rolling 252-day violation rate, multiplicative widening if > alpha",
            "quantile": "Expanding quantile of standardized residuals (r/σ), replaces Normal z_α",
        },
        "qlike_on_r2": qlike_results,
        "qlike_note": "Conformal does NOT change σ² forecast — only adjusts VaR threshold. "
                      "QLIKE is identical for raw vs conformal variants of the same model.",
        "var_backtest": var_results,
        "spearman": spearman_results,
        "dm_tests": dm_results,
        "key_finding": {
            "question": "Can conformal calibration fix GJR's VaR 1% failure?",
            "answer": conclusion,
            "gjr_raw_kupiec_pass": gjr_raw_fixed,
            "gjr_conformal_simple_kupiec_pass": gjr_cs_fixed,
            "gjr_conformal_quantile_kupiec_pass": gjr_cq_fixed,
            "qlike_preserved": True,  # By design: conformal only adjusts VaR, not σ²
            "best_combined_model": best_combined,
        },
        "runtime_seconds": round(elapsed, 1),
        "references": [
            "arXiv:2602.03903 — Regime-Weighted Conformal VaR",
            "Vovk, Gammerman, Shafer (2005) — Algorithmic Learning in a Random World",
            "Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss",
            "Kupiec (1995) — unconditional VaR coverage test",
            "Christoffersen (1998) — conditional VaR independence test",
            "K799 — Grand Model Evaluation (GJR wins QLIKE, fails VaR)",
        ],
        "limitations": [
            "OOS period (2023-2024) is relatively calm — conformal adjustment has limited training signal",
            "252-day lookback may be too long for regime changes, too short for rare events at 1%",
            "Conformal simple only widens (conservative) — may be over-conservative in calm periods",
            "Normal distribution assumption for VaR may be the root cause of GJR's failure (fat tails)",
            "With only ~5 expected violations in 502 OOS days, statistical power is inherently low",
        ],
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to {RESULTS_PATH}")
    print(f"  Runtime: {elapsed:.1f}s")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
