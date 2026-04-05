#!/usr/bin/env python3
"""
K799: Grand Model Evaluation — Full 6-Layer Patton (2011) Framework
====================================================================
[提出: 用戶, 執行: Claude]

First experiment to implement ALL 6 evaluation layers on 5 core models:
  1. QLIKE on r² (proxy-robust, primary ranking)
  2. MSE on r² (secondary)
  3. Spearman rank correlation (distribution-free)
  4. DM tests + Harvey t>3.0 (pairwise significance)
  5. MCS — Model Confidence Set (HLN 2011, stationary bootstrap)
  6. VaR 1% backtest (Kupiec + Christoffersen + Basel traffic light)

Models (all produce σ²/r² forecasts, expanding window OOS):
  1. GJR-GARCH(1,1) — our champion
  2. GARCH(1,1) — simpler baseline
  3. EWMA (λ=0.94) — RiskMetrics
  4. HAR-r² — multi-scale daily (Corsi 2009)
  5. AMEM-r² — Engle & Gallo (2006), Gamma MLE on r² (from K778)

Data: SPY 2006-01-01 to 2025-12-31, OOS period 2023-2024, expanding window
      Refit every 63 trading days

References:
  - Patton (2011) J. Econometrics 160 — proxy-robust loss (QLIKE)
  - Hansen, Lunde & Nason (2011) Econometrica 79 — Model Confidence Set
  - Kupiec (1995) — unconditional VaR coverage test
  - Christoffersen (1998) — conditional VaR independence test
  - Harvey et al. (2016) — multiple testing threshold t>3.0
  - Engle & Gallo (2006) J. Econometrics 131 — MEM framework
  - Corsi (2009) J. Financial Econometrics 7 — HAR model
  - Bollerslev (1986) J. Econometrics 31 — GARCH(1,1)
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - RiskMetrics (1996) — EWMA λ=0.94
  - K778: MEM-r² native — GJR beats AMEM-r² (DM=3.78)
  - K778-review: Codex flagged MCS as HIGH (iid bootstrap) — now fixed
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
from scipy.special import gammaln
from scipy.stats import spearmanr, norm, chi2

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k799_grand_evaluation_results.json')

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


@njit(cache=True)
def amem_r2_filter(r2, r, omega, alpha, beta, gamma):
    """AMEM-r²: μ_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·μ_{t-1}"""
    T = len(r2)
    mu = np.empty(T)
    mu[0] = r2[0] if r2[0] > 0 else 1e-6
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        mu[t] = omega + (alpha + gamma * ind) * r2[t - 1] + beta * mu[t - 1]
        if mu[t] < 1e-12:
            mu[t] = 1e-12
    return mu


# ==============================================================
# B. Model fitting
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


def fit_amem_r2(r2, r, n_starts=4):
    """Fit AMEM-r² via Gamma MLE. Returns dict or None."""
    r2 = np.ascontiguousarray(r2, dtype=np.float64)
    r = np.ascontiguousarray(r, dtype=np.float64)
    r2_mean = np.mean(r2[r2 > 0]) if np.any(r2 > 0) else 1e-4

    def negll(params, r2, r):
        omega, alpha, beta, gamma, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0 or k <= 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        mu = amem_r2_filter(r2, r, omega, alpha, beta, gamma)
        r2_t, mu_t = r2[1:], mu[1:]
        valid = (mu_t > 1e-12) & (r2_t > 0)
        if valid.sum() < 10:
            return 1e10
        r2_v, mu_v = r2_t[valid], mu_t[valid]
        ll = np.sum(k * np.log(k / mu_v) + (k - 1) * np.log(r2_v)
                    - k * r2_v / mu_v - gammaln(k))
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 300)
        o0 = max(1e-8, r2_mean * 0.05 * (1 + 0.3 * np.random.randn()))
        a0 = np.clip(0.04 + 0.03 * np.random.randn(), 0.01, 0.4)
        b0 = np.clip(0.87 + 0.04 * np.random.randn(), 0.3, 0.95)
        g0 = np.clip(0.08 + 0.05 * np.random.randn(), 0.01, 0.4)
        k0 = np.clip(0.8 + 0.3 * np.random.randn(), 0.1, 10.0)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        res = minimize(negll, [o0, a0, b0, g0, k0], args=(r2, r),
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.9), (0, 0.999),
                               (0, 0.9), (0.05, 100)],
                       options={'maxiter': 5000, 'ftol': 1e-10})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    return {'omega': float(best.x[0]), 'alpha': float(best.x[1]),
            'beta': float(best.x[2]), 'gamma': float(best.x[3]),
            'k': float(best.x[4]),
            'persistence': float(best.x[1] + best.x[2] + 0.5 * best.x[3])}


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
# C. One-step-ahead forecasters (all produce σ²/r² forecast)
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


def fcast_amem(r2, r, params):
    r2a = np.ascontiguousarray(r2, dtype=np.float64)
    ra = np.ascontiguousarray(r, dtype=np.float64)
    mu = amem_r2_filter(r2a, ra, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    ind = 1.0 if ra[-1] < 0 else 0.0
    f = (params['omega'] + (params['alpha'] + params['gamma'] * ind) * r2a[-1]
         + params['beta'] * mu[-1])
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
# D. Evaluation metrics (standalone, not depending on volpred)
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
    from scipy.stats import t as t_dist
    t_stat = d_mean / se
    p_val = 2 * (1 - t_dist.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ==============================================================
# E. VaR backtest (Layer 6)
# ==============================================================

def var_backtest(returns, sigma2_forecasts, alpha_var=0.01):
    """
    VaR 1% backtest: Kupiec + Christoffersen + Basel traffic light.

    For all models: VaR = sigma * z_alpha (Normal assumption for comparability).
    Models that predict σ²: sigma = sqrt(σ²)
    """
    r = np.asarray(returns, dtype=np.float64)
    s2 = np.asarray(sigma2_forecasts, dtype=np.float64)
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z_alpha = norm.ppf(alpha_var)  # negative, e.g. -2.326 for 1%
    var_threshold = sigma * z_alpha  # negative

    violations = (r < var_threshold).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0

    # Kupiec (1995)
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
        if (0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1):
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
        traffic = "green"
    elif pi_hat <= alpha_var * 2.0:
        traffic = "yellow"
    else:
        traffic = "red"

    return {
        "violation_rate": round(float(pi_hat), 6),
        "expected_rate": float(alpha_var),
        "n_violations": n1,
        "n_total": n,
        "kupiec": {"stat": round(kup_stat, 4), "p_value": round(kup_p, 4),
                   "pass": kup_p > 0.05},
        "christoffersen": {"stat": round(cc_stat, 4), "p_value": round(cc_p, 4),
                           "pass": cc_p > 0.05},
        "basel_traffic_light": traffic,
        "trinity_pass": kup_p > 0.05 and cc_p > 0.05 and traffic == "green",
    }


# ==============================================================
# F. Main OOS forecasting loop
# ==============================================================

def generate_oos_forecasts(returns_all, oos_start_idx, refit_every=63):
    """
    Generate expanding-window OOS forecasts for all 5 models.

    returns_all: full return series (numpy array)
    oos_start_idx: index where OOS begins
    refit_every: refit models every N days (default 63 = quarterly)

    Returns dict of {model_name: array of OOS σ² forecasts}
    """
    n_oos = len(returns_all) - oos_start_idx
    print(f"\n{'='*60}")
    print(f"OOS forecasting: {n_oos} days, refit every {refit_every} days")
    print(f"{'='*60}")

    forecasts = {m: np.full(n_oos, np.nan) for m in
                 ['GJR', 'GARCH', 'EWMA', 'HAR', 'AMEM']}

    # Cache fitted parameters (refit only every refit_every)
    gjr_params = None
    garch_params = None
    amem_params = None
    har_beta = None
    last_fit = -refit_every  # force fit on first day

    t0 = time.time()

    for i in range(n_oos):
        t = oos_start_idx + i  # current day index

        # All data up to day t (exclusive) is available for fitting/forecasting
        r_train = returns_all[:t]
        r2_train = r_train ** 2

        # ── Refit models if needed ──────────────────────────────
        if i - last_fit >= refit_every or gjr_params is None:
            last_fit = i
            gjr_params = fit_gjr(r_train)
            garch_params = fit_garch(r_train)
            amem_params = fit_amem_r2(r2_train, r_train)
            har_beta = fit_har_r2(r2_train)
            if i == 0 or i % 126 == 0:
                pct = 100 * i / n_oos
                elapsed = time.time() - t0
                print(f"  [{pct:5.1f}%] Day {i}/{n_oos}, "
                      f"elapsed {elapsed:.1f}s, "
                      f"GJR persist={gjr_params['persistence']:.4f}" if gjr_params else
                      f"  [{pct:5.1f}%] Day {i}/{n_oos}, GJR fit failed")

        # ── Generate forecasts for day t+1 ──────────────────────
        # NOTE: forecast uses data up to day t-1 (the last available return)
        # The forecast is for day t's realized variance
        # This is NOT lookahead: we use past data to predict today

        # GJR-GARCH
        if gjr_params is not None:
            forecasts['GJR'][i] = fcast_gjr(r_train, gjr_params)

        # GARCH(1,1)
        if garch_params is not None:
            forecasts['GARCH'][i] = fcast_garch(r_train, garch_params)

        # EWMA (no fitting needed)
        forecasts['EWMA'][i] = fcast_ewma(r2_train)

        # HAR-r²
        if har_beta is not None:
            f = fcast_har(r2_train, har_beta)
            if f is not None:
                forecasts['HAR'][i] = f

        # AMEM-r²
        if amem_params is not None:
            forecasts['AMEM'][i] = fcast_amem(r2_train, r_train, amem_params)

    elapsed = time.time() - t0
    print(f"\n  OOS forecasting completed in {elapsed:.1f}s")

    # Report forecast coverage
    for m, fc in forecasts.items():
        valid = np.isfinite(fc).sum()
        print(f"  {m}: {valid}/{n_oos} valid forecasts ({100*valid/n_oos:.1f}%)")

    return forecasts


# ==============================================================
# G. Full 6-layer evaluation
# ==============================================================

def run_6layer_evaluation(forecasts, realized_r2, returns_oos):
    """
    Execute all 6 evaluation layers.

    forecasts: {model: array of σ² forecasts}
    realized_r2: actual r² in OOS period
    returns_oos: actual returns in OOS period (for VaR)
    """
    models = list(forecasts.keys())
    n = len(realized_r2)
    results = {}

    print(f"\n{'='*60}")
    print(f"6-LAYER EVALUATION ({n} OOS observations, {len(models)} models)")
    print(f"{'='*60}")

    # ── Layer 1-2: QLIKE on r² ──────────────────────────────────
    print("\n── Layer 1-2: QLIKE on r² (Patton 2011 proxy-robust) ──")
    qlike_scores = {}
    pw_losses = {}
    mse_scores = {}
    for m in models:
        fc = forecasts[m][:n]
        valid = np.isfinite(fc)
        if valid.sum() < 10:
            qlike_scores[m] = np.nan
            mse_scores[m] = np.nan
            pw_losses[m] = np.full(n, np.nan)
            continue
        # Use only valid observations (aligned across models later for DM/MCS)
        qlike_scores[m] = qlike_score(realized_r2[valid], fc[valid])
        mse_scores[m] = float(np.mean((realized_r2[valid] - fc[valid]) ** 2))
        pw_losses[m] = pointwise_qlike(realized_r2, fc)

    ranking = sorted(qlike_scores.items(), key=lambda x: x[1] if not np.isnan(x[1]) else 1e10)
    print(f"\n  {'Rank':<6}{'Model':<12}{'QLIKE':<12}{'MSE':<14}")
    print(f"  {'-'*44}")
    for rank, (m, q) in enumerate(ranking, 1):
        print(f"  {rank:<6}{m:<12}{q:.6f}    {mse_scores[m]:.2e}")

    results['layer_1_2_qlike'] = {m: round(v, 6) for m, v in qlike_scores.items()}
    results['layer_1_2_mse'] = {m: f"{v:.2e}" for m, v in mse_scores.items()}
    results['layer_2_ranking'] = [
        {"rank": i + 1, "model": m, "qlike": round(q, 6)}
        for i, (m, q) in enumerate(ranking)
    ]

    # ── Layer 3: Spearman rank correlation ──────────────────────
    print("\n── Layer 3: Spearman Rank Correlation ──")
    spearman_scores = {}
    for m in models:
        fc = forecasts[m][:n]
        valid = np.isfinite(fc) & (realized_r2 > 0) & (fc > 0)
        if valid.sum() < 10:
            spearman_scores[m] = {"rho": np.nan, "p_value": np.nan}
            continue
        rho, p = spearmanr(realized_r2[valid], fc[valid])
        spearman_scores[m] = {"rho": round(float(rho), 4), "p_value": round(float(p), 6)}
        print(f"  {m:<12} rho={rho:.4f}  p={p:.2e}")
    results['layer_3_spearman'] = spearman_scores

    # ── Layer 4: DM tests (all pairs) ──────────────────────────
    print("\n── Layer 4: Diebold-Mariano Tests (Harvey t>3.0) ──")
    # Align losses: use only observations where ALL models have valid forecasts
    all_valid = np.ones(n, dtype=bool)
    for m in models:
        all_valid &= np.isfinite(pw_losses[m])
    n_aligned = all_valid.sum()
    print(f"  Aligned observations: {n_aligned}/{n}")

    aligned_losses = {m: pw_losses[m][all_valid] for m in models}

    dm_results = {}
    print(f"\n  {'Pair':<22}{'DM t':<10}{'p-value':<10}{'|t|>3?':<8}{'Better'}")
    print(f"  {'-'*58}")
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            t_stat, p_val = dm_test(aligned_losses[m1], aligned_losses[m2])
            better = m1 if t_stat < 0 else m2
            harvey = abs(t_stat) > 3.0
            pair = f"{m1} vs {m2}"
            dm_results[pair] = {
                "dm_stat": round(t_stat, 4),
                "p_value": round(p_val, 6),
                "harvey_pass": harvey,
                "better": better,
            }
            flag = "***" if harvey else ""
            print(f"  {pair:<22}{t_stat:>8.4f}  {p_val:>8.4f}  "
                  f"{'YES' if harvey else 'no':<8}{better} {flag}")
    results['layer_4_dm_tests'] = dm_results

    # ── Layer 5: Model Confidence Set (HLN 2011) ──────────────
    print("\n── Layer 5: Model Confidence Set (Hansen, Lunde, Nason 2011) ──")
    print("  Using stationary bootstrap (Politis & Romano 1994)")
    from volpred.stats.mcs import model_confidence_set as mcs_fn

    t_mcs = time.time()
    mcs_result = mcs_fn(aligned_losses, alpha=0.10, n_boot=5000, seed=42)
    mcs_time = time.time() - t_mcs
    print(f"  MCS computed in {mcs_time:.1f}s")
    print(f"\n  MCS members (alpha=0.10): {mcs_result['mcs_models']}")
    print(f"  MCS size: {len(mcs_result['mcs_models'])}")
    if mcs_result.get('eliminated'):
        print(f"  Elimination order:")
        for m, p in mcs_result['eliminated']:
            print(f"    {m}: p={p:.4f} (eliminated)")
    print(f"  P-values: {mcs_result['p_values']}")

    results['layer_5_mcs'] = {
        "members": mcs_result['mcs_models'],
        "size": len(mcs_result['mcs_models']),
        "p_values": {k: round(v, 4) for k, v in mcs_result['p_values'].items()},
        "eliminated": [(m, round(p, 4)) for m, p in mcs_result.get('eliminated', [])],
        "method": "HLN2011_stationary_bootstrap",
        "n_boot": 5000,
        "alpha": 0.10,
        "compute_time_s": round(mcs_time, 1),
    }

    # ── Layer 6: VaR 1% Backtest ──────────────────────────────
    print("\n── Layer 6: VaR 1% Backtest (Kupiec + Christoffersen + Basel) ──")
    print("  VaR = sigma * z_0.01 (Normal quantile = -2.326)")
    var_results = {}
    print(f"\n  {'Model':<12}{'Viol%':<10}{'n_viol':<8}{'Kupiec p':<12}"
          f"{'CC p':<10}{'Basel':<8}{'Trinity'}")
    print(f"  {'-'*68}")
    for m in models:
        fc = forecasts[m][:n]
        valid = np.isfinite(fc)
        if valid.sum() < 50:
            var_results[m] = {"error": "insufficient valid forecasts"}
            continue
        vr = var_backtest(returns_oos[valid], fc[valid], alpha_var=0.01)
        var_results[m] = vr
        print(f"  {m:<12}{vr['violation_rate']:<10.4f}{vr['n_violations']:<8}"
              f"{vr['kupiec']['p_value']:<12.4f}{vr['christoffersen']['p_value']:<10.4f}"
              f"{vr['basel_traffic_light']:<8}{'PASS' if vr['trinity_pass'] else 'FAIL'}")
    results['layer_6_var_backtest'] = var_results

    return results


# ==============================================================
# H. Main
# ==============================================================

def main():
    start_time = time.time()
    print("K799: Grand Model Evaluation — Full 6-Layer Framework")
    print("=" * 60)

    # ── 1. Download data ──────────────────────────────────────
    print("\n[1/4] Downloading SPY data...")
    spy = yf.download('SPY', start='2006-01-01', end='2025-12-31',
                      auto_adjust=True, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy = spy.dropna(subset=['Close'])
    spy['Return'] = spy['Close'].pct_change()
    spy = spy.dropna(subset=['Return'])
    spy['r2'] = spy['Return'] ** 2

    returns_all = spy['Return'].values.astype(np.float64)
    r2_all = spy['r2'].values.astype(np.float64)
    dates = spy.index

    print(f"  Total: {len(returns_all)} trading days")
    print(f"  Period: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean return: {returns_all.mean():.6f}")
    print(f"  Std return:  {returns_all.std():.6f}")
    print(f"  Mean r²:     {r2_all.mean():.6f}")

    # ── 2. Define OOS period ──────────────────────────────────
    # OOS: 2023-01-01 to 2024-12-31
    oos_mask = (dates >= '2023-01-01') & (dates <= '2024-12-31')
    oos_start_idx = np.where(oos_mask)[0][0]
    oos_end_idx = np.where(oos_mask)[0][-1] + 1
    n_oos = oos_end_idx - oos_start_idx

    print(f"\n[2/4] OOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} "
          f"to {dates[oos_end_idx-1].strftime('%Y-%m-%d')}")
    print(f"  OOS days: {n_oos}")
    print(f"  IS days before OOS: {oos_start_idx}")

    # ── 3. Generate OOS forecasts ─────────────────────────────
    print("\n[3/4] Generating OOS forecasts (expanding window, refit every 63 days)...")

    # Warm up numba
    _warmup = np.random.randn(100).astype(np.float64)
    _ = gjr_filter(_warmup, 1e-6, 0.05, 0.9, 0.05)
    _ = garch_filter(_warmup, 1e-6, 0.05, 0.9)
    _ = amem_r2_filter(_warmup ** 2, _warmup, 1e-6, 0.05, 0.9, 0.05)

    forecasts = generate_oos_forecasts(returns_all[:oos_end_idx],
                                       oos_start_idx, refit_every=63)

    # Realized values in OOS
    realized_r2 = r2_all[oos_start_idx:oos_end_idx]
    returns_oos = returns_all[oos_start_idx:oos_end_idx]

    # ── 4. Run 6-layer evaluation ─────────────────────────────
    print("\n[4/4] Running 6-layer evaluation...")
    eval_results = run_6layer_evaluation(forecasts, realized_r2, returns_oos)

    # ── 5. Compile and save results ───────────────────────────
    total_time = time.time() - start_time

    # Descriptive stats for the OOS period
    oos_stats = {
        "mean_return": round(float(returns_oos.mean()), 6),
        "std_return": round(float(returns_oos.std()), 6),
        "mean_r2": round(float(realized_r2.mean()), 6),
        "skewness_return": round(float(pd.Series(returns_oos).skew()), 4),
        "kurtosis_return": round(float(pd.Series(returns_oos).kurtosis()), 4),
    }

    results = {
        "experiment_id": "K799",
        "title": "Grand Model Evaluation — Full 6-Layer Patton (2011) Framework",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance",
        "asset": "SPY",
        "full_period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
        "oos_period": f"{dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[oos_end_idx-1].strftime('%Y-%m-%d')}",
        "n_total": int(len(returns_all)),
        "n_oos": int(n_oos),
        "n_is_before_oos": int(oos_start_idx),
        "refit_every": 63,
        "models": ["GJR-GARCH(1,1)", "GARCH(1,1)", "EWMA(0.94)", "HAR-r²", "AMEM-r²"],
        "oos_descriptive_stats": oos_stats,
        "evaluation_layers": {
            "layer_1_2": {
                "description": "QLIKE on r² (Patton 2011 proxy-robust) + MSE",
                "qlike": eval_results['layer_1_2_qlike'],
                "mse": eval_results['layer_1_2_mse'],
                "ranking": eval_results['layer_2_ranking'],
            },
            "layer_3": {
                "description": "Spearman rank correlation (distribution-free)",
                "results": eval_results['layer_3_spearman'],
            },
            "layer_4": {
                "description": "Diebold-Mariano tests with Harvey (2016) t>3.0",
                "results": eval_results['layer_4_dm_tests'],
            },
            "layer_5": {
                "description": "Model Confidence Set (Hansen, Lunde, Nason 2011)",
                "results": eval_results['layer_5_mcs'],
            },
            "layer_6": {
                "description": "VaR 1% backtest (Kupiec + Christoffersen + Basel traffic light)",
                "results": eval_results['layer_6_var_backtest'],
            },
        },
        "runtime_seconds": round(total_time, 1),
        "references": [
            "Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss",
            "Hansen, Lunde & Nason (2011) Econometrica 79 — MCS",
            "Kupiec (1995) — unconditional VaR coverage",
            "Christoffersen (1998) — conditional VaR independence",
            "Harvey et al. (2016) — t>3.0 multiple testing",
            "Engle & Gallo (2006) J. Econometrics 131 — MEM/AMEM",
            "Corsi (2009) J. Financial Econometrics 7 — HAR",
            "Bollerslev (1986) J. Econometrics 31 — GARCH",
            "Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH",
            "RiskMetrics (1996) — EWMA lambda=0.94",
        ],
        "limitations": [
            "OOS period (2023-2024) is relatively calm — results may differ in crisis periods",
            "Daily r² is a noisy proxy for true σ²; 5-min RV would be gold standard",
            "VaR uses Normal quantile for all models (simplification for comparability)",
            "AMEM Gamma assumption may not hold exactly for r²",
            "HAR-r² without intraday RV is less powerful than HAR-RV with 5-min data",
        ],
    }

    # ── Print summary ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    winner = eval_results['layer_2_ranking'][0]
    print(f"  QLIKE Winner:  {winner['model']} (QLIKE={winner['qlike']:.6f})")
    mcs = eval_results['layer_5_mcs']
    print(f"  MCS Members:   {mcs['members']} (size={mcs['size']})")

    # Count DM significance
    n_sig = sum(1 for v in eval_results['layer_4_dm_tests'].values() if v['harvey_pass'])
    n_pairs = len(eval_results['layer_4_dm_tests'])
    print(f"  DM Harvey sig: {n_sig}/{n_pairs} pairs")

    # VaR summary
    model_names = list(eval_results['layer_6_var_backtest'].keys())
    trinity_pass = [m for m in model_names if
                    eval_results['layer_6_var_backtest'].get(m, {}).get('trinity_pass', False)]
    print(f"  VaR Trinity:   {trinity_pass} pass all 3 tests")
    print(f"  Runtime:       {total_time:.1f}s")

    # Save
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {RESULTS_PATH}")

    return results


if __name__ == '__main__':
    main()
