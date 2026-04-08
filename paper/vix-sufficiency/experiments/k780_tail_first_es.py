#!/usr/bin/env python3
"""
K780: Tail-First Expected Shortfall Allocation — Risk Control Over Vol Prediction
==================================================================================
[提出: Codex GPT-5.4 (#4), 執行: Claude]

Retail investors care more about large losses than forecast RMSE.
This experiment evaluates vol models by their RISK MANAGEMENT outcomes
(VaR/ES calibration), not just statistical accuracy.

Parts:
  A) Compute 1%/5% VaR + ES from each model (expanding window OOS)
  B) VaR Backtesting: Kupiec, Christoffersen, Basel traffic light
  C) Inverse-ES Portfolio Allocation: SPY+GLD weighted by 1/ES
  D) Model Ranking by economic criterion (violation rate + ES calibration + Sharpe)

Models:
  1. GJR-GARCH(1,1) — Student-t quantile
  2. AMEM(1,1) — Gamma-based quantile (|r| space)
  3. HAR-ABS — empirical distribution of standardized residuals
  4. EWMA(0.94) — Gaussian quantile
  5. Historical Simulation (250-day rolling window)

References:
  - Kupiec (1995) "Techniques for verifying the accuracy of risk measurement models"
  - Christoffersen (1998) "Evaluating interval forecasts" Intl Economic Review
  - Acerbi & Szekely (2014) "Backtesting Expected Shortfall" Risk Magazine
  - Basel III traffic light system (BCBS 2016)
  - K770: AMEM beats HAR-ABS (DM=-7.46) on forecast accuracy
  - K778: GJR beats MEM-r² in σ² space (Patton QLIKE)
  - K116: CVaR Tail Risk Parity — null, 50/50 unbeatable

Data: SPY, GLD, ^VIX from yfinance, 2007-2026
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.special import gammaln, gammaincinv
from scipy.stats import t as t_dist, norm, chi2, gamma as gamma_dist
from datetime import datetime, timezone
from numba import njit
import warnings
import os
import sys

warnings.filterwarnings('ignore')

RESULTS_PATH = 'experiments/k780_tail_first_es_results.json'

# ============================================================
# Model Filters (numba accelerated)
# ============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma_p):
    """GJR-GARCH(1,1) variance filter."""
    T = len(r)
    sigma2 = np.zeros(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i]**2
    var_r /= T
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        sigma2[t] = omega + (alpha + gamma_p * ind) * r[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return sigma2


@njit(cache=True)
def amem_filter(x, r, omega, alpha, beta, gamma_p):
    """AMEM(1,1) conditional mean filter for |r_t|."""
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 0.01
    for t in range(1, T):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        mu[t] = omega + (alpha + gamma_p * indicator) * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-10:
            mu[t] = 1e-10
    return mu


# ============================================================
# Model Estimation Functions
# ============================================================

def fit_gjr_garch(returns, fit_df=True):
    """
    GJR-GARCH(1,1) with Student-t innovations.
    Returns params + df (degrees of freedom for t-distribution).
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 100:
        return None

    # Phase 1: Gaussian QMLE for GARCH params
    def gjr_negll_gauss(params, r):
        omega, alpha, beta, gamma_p = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma_p < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma_p >= 1.0:
            return 1e10
        sigma2 = gjr_filter(r, omega, alpha, beta, gamma_p)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:]**2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rv = np.var(r)
    best = None
    best_nll = 1e10

    for seed in range(3):
        np.random.seed(seed + 100)
        a0 = max(0.01, min(0.05 + 0.03 * np.random.randn(), 0.3))
        b0 = max(0.5, min(0.88 + 0.04 * np.random.randn(), 0.98))
        g0 = max(0.01, min(0.08 + 0.04 * np.random.randn(), 0.3))
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = rv * (1 - a0 - b0 - 0.5 * g0)
        res = minimize(gjr_negll_gauss, [max(1e-8, o0), a0, b0, g0], args=(r,),
                      method='L-BFGS-B',
                      bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                      options={'maxiter': 2000})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res

    if best is None:
        return None

    params = {
        'omega': best.x[0], 'alpha': best.x[1],
        'beta': best.x[2], 'gamma': best.x[3],
        'persistence': best.x[1] + best.x[2] + 0.5 * best.x[3]
    }

    # Phase 2: Estimate t-distribution df from standardized residuals
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    z = r[1:] / np.sqrt(sigma2[1:])

    if fit_df:
        # MLE for t-distribution df
        def t_negll(df_arr):
            df = df_arr[0]
            if df <= 2.01:
                return 1e10
            ll = np.sum(t_dist.logpdf(z, df=df))
            return -ll if np.isfinite(ll) else 1e10

        df_res = minimize(t_negll, [5.0], method='L-BFGS-B',
                         bounds=[(2.1, 100)])
        params['df'] = df_res.x[0]
    else:
        params['df'] = 5.0

    return params


def gjr_forecast_sigma(returns, params):
    """One-step-ahead GJR-GARCH σ forecast."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    sigma2 = gjr_filter(r, params['omega'], params['alpha'],
                        params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    next_sigma2 = (params['omega'] + (params['alpha'] + params['gamma'] * ind) *
                   r[-1]**2 + params['beta'] * sigma2[-1])
    return max(np.sqrt(next_sigma2), 1e-8)


def fit_amem(x, r):
    """Fit AMEM(1,1) via Gamma MLE. Returns params + k (shape)."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    r = np.ascontiguousarray(r, dtype=np.float64)
    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 0.01

    def amem_negll(params):
        omega, alpha, beta, gamma_p, k = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma_p < 0 or k <= 0:
            return 1e10
        if alpha + beta + 0.5 * gamma_p >= 1.0:
            return 1e10
        mu = amem_filter(x, r, omega, alpha, beta, gamma_p)
        x_trim = x[1:]
        mu_trim = mu[1:]
        valid = (mu_trim > 1e-10) & (x_trim > 0)
        if valid.sum() < 10:
            return 1e10
        x_v = x_trim[valid]
        mu_v = mu_trim[valid]
        ll = (k * np.log(k / mu_v) + (k - 1) * np.log(x_v)
              - k * x_v / mu_v - gammaln(k))
        total = np.sum(ll)
        return -total if np.isfinite(total) else 1e10

    best = None
    best_nll = 1e10
    for seed in range(3):
        np.random.seed(seed + 42)
        a0 = max(0.01, min(0.05 + 0.03 * np.random.randn(), 0.4))
        b0 = max(0.3, min(0.85 + 0.05 * np.random.randn(), 0.95))
        g0 = max(0.01, min(0.1 + 0.05 * np.random.randn(), 0.4))
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
        k0 = max(0.5, 2.0 + np.random.rand())
        p0 = [max(1e-6, o0), a0, b0, g0, k0]
        bounds = [(1e-8, None), (0, 0.9), (0, 0.99), (0, 0.9), (0.1, 100)]
        res = minimize(amem_negll, p0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 5000, 'ftol': 1e-10})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res

    if best is None:
        return None

    return {
        'omega': best.x[0], 'alpha': best.x[1],
        'beta': best.x[2], 'gamma': best.x[3],
        'k': best.x[4],
        'persistence': best.x[1] + best.x[2] + 0.5 * best.x[3]
    }


def amem_forecast_mu(abs_ret, returns, params):
    """One-step-ahead AMEM forecast of E[|r_{t+1}|]."""
    x = np.ascontiguousarray(abs_ret, dtype=np.float64)
    r = np.ascontiguousarray(returns, dtype=np.float64)
    mu = amem_filter(x, r, params['omega'], params['alpha'],
                     params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    next_mu = (params['omega'] + (params['alpha'] + params['gamma'] * ind) *
               x[-1] + params['beta'] * mu[-1])
    return max(next_mu, 1e-10)


def fit_har_abs(abs_ret):
    """HAR-ABS: |r_t| = β0 + β1×|r_{t-1}| + β5×MA5 + β22×MA22."""
    x = abs_ret.copy()
    n = len(x)
    if n < 50:
        return None
    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values
    valid_start = 22
    if n <= valid_start + 30:
        return None
    idx = np.arange(valid_start, n)
    Y = x[idx]
    X = np.column_stack([
        np.ones(len(idx)),
        x[idx - 1],
        ma5[idx - 1],
        ma22[idx - 1]
    ])
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None
    Y = Y[valid_rows]
    X = X[valid_rows]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


def har_abs_forecast(abs_ret, beta):
    """One-step HAR-ABS forecast."""
    n = len(abs_ret)
    if n < 22:
        return None
    pred = beta[0] + beta[1] * abs_ret[-1] + beta[2] * np.mean(abs_ret[-5:]) + beta[3] * np.mean(abs_ret[-22:])
    return max(pred, 1e-10)


def ewma_forecast_sigma(returns, lam=0.94):
    """EWMA σ forecast."""
    var_est = returns[0]**2
    for i in range(1, len(returns)):
        var_est = lam * var_est + (1 - lam) * returns[i]**2
    return max(np.sqrt(var_est), 1e-8)


# ============================================================
# VaR/ES Computation Functions
# ============================================================

def var_gjr(sigma, df, alpha):
    """VaR from GJR-GARCH with Student-t innovations.
    VaR_α = -σ × t_inv(α, df)  (positive number = loss)
    """
    q = t_dist.ppf(alpha, df=df)
    return -sigma * q


def es_gjr(sigma, df, alpha):
    """ES from GJR-GARCH with Student-t.
    ES_α = σ × (t_pdf(t_inv(α,df),df) / α) × ((df + (t_inv(α,df))²) / (df-1))
    Exact formula for Student-t ES.
    """
    q = t_dist.ppf(alpha, df=df)
    pdf_val = t_dist.pdf(q, df=df)
    es = sigma * (pdf_val / alpha) * ((df + q**2) / (df - 1))
    return es


def var_amem(mu_abs, k, alpha):
    """VaR from AMEM.
    |r| ~ MEM with E[|r|] = μ, innovations Gamma(k, 1/k).
    So |r| = μ × ε, ε ~ Gamma(k, 1/k).
    Return VaR: we need quantile of r distribution.

    Since AMEM models |r|, we convert to return VaR assuming symmetric tails
    (conservative: use |r| quantile as two-sided symmetric).
    P(r < -VaR) = α → P(|r| > VaR) ≈ 2α for symmetric → VaR = quantile of |r| at (1-2α)

    Actually, for proper VaR: P(r < -VaR) = α
    If returns are approximately symmetric: P(|r| > VaR) = 2α
    So VaR = μ × Gamma_quantile(1-2α, k, 1/k) when α < 0.5
    But this is conservative. Better: use standardized residuals.

    Simpler robust approach: use μ × z_α where z_α from empirical distribution of ε = |r|/μ.
    But in expanding window we don't have enough history per refit.

    Use Gamma quantile: ε ~ Gamma(k, 1/k), VaR of |r| at level p = μ × Gamma_inv(p, k, 1/k)
    For return VaR at α: assume half goes to each tail → |r| quantile at (1-2α)
    """
    # Gamma quantile: F^{-1}(p) for ε ~ Gamma(k, scale=1/k)
    # scipy gamma ppf with a=k, scale=1/k
    p_tail = 1 - 2 * alpha  # e.g., for α=0.05: p_tail=0.90; for α=0.01: p_tail=0.98
    if p_tail >= 1.0:
        p_tail = 0.999
    eps_q = gamma_dist.ppf(p_tail, a=k, scale=1.0/k)
    var_val = mu_abs * eps_q
    return var_val


def es_amem(mu_abs, k, alpha):
    """ES from AMEM using Gamma distribution.
    ES = E[|r| | |r| > VaR] for the tail portion.
    Using the conditional expectation of Gamma above threshold.

    For Gamma(k, 1/k): E[X | X > q] = (1 - Gamma_cdf_regularized(q, k+1, 1/k)) / (1 - Gamma_cdf(q, k, 1/k)) × k/k
    Simpler: ES_α = μ × E[ε | ε > ε_q] where ε_q = Gamma_inv(1-2α, k, 1/k)
    """
    p_tail = 1 - 2 * alpha
    if p_tail >= 1.0:
        p_tail = 0.999
    eps_q = gamma_dist.ppf(p_tail, a=k, scale=1.0/k)

    # E[ε | ε > q] for Gamma(k, 1/k)
    # = (1 - Gamma_CDF(q; k+1, 1/k)) × (k+1)/k / (1 - Gamma_CDF(q; k, 1/k))
    # Wait, exact formula: E[X | X > q] = E[X × I(X>q)] / P(X>q)
    # For Gamma(a, scale): E[X × I(X>q)] = a × scale × (1 - F(q; a+1, scale))
    # P(X>q) = 1 - F(q; a, scale)

    a = k
    scale = 1.0 / k
    survival = 1 - gamma_dist.cdf(eps_q, a=a, scale=scale)
    if survival < 1e-15:
        return mu_abs * eps_q * 1.5  # fallback

    e_x_above = a * scale * (1 - gamma_dist.cdf(eps_q, a=a+1, scale=scale))
    cond_mean = e_x_above / survival

    return mu_abs * cond_mean


def var_gaussian(sigma, alpha):
    """VaR from Gaussian model (EWMA / HAR). VaR = -σ × z_α."""
    return -sigma * norm.ppf(alpha)


def es_gaussian(sigma, alpha):
    """ES from Gaussian model. ES = σ × φ(z_α) / α."""
    z = norm.ppf(alpha)
    return sigma * norm.pdf(z) / alpha


def var_historical(returns_window, alpha):
    """Historical simulation VaR: negative quantile of returns."""
    q = np.percentile(returns_window, alpha * 100)
    return -q  # positive number


def es_historical(returns_window, alpha):
    """Historical simulation ES: mean of returns below VaR quantile."""
    q = np.percentile(returns_window, alpha * 100)
    tail = returns_window[returns_window <= q]
    if len(tail) == 0:
        return -q * 1.5
    return -np.mean(tail)


# ============================================================
# VaR Backtesting
# ============================================================

def kupiec_test(violations, n_obs, alpha):
    """
    Kupiec (1995) Proportion of Failures (POF) test.
    H0: violation rate = α
    LR ~ χ²(1)
    """
    n_viol = np.sum(violations)
    p_hat = n_viol / n_obs if n_obs > 0 else 0

    if n_viol == 0:
        return {'stat': 0, 'p_value': 1.0, 'n_violations': 0,
                'violation_rate': 0, 'expected_rate': alpha}
    if n_viol == n_obs:
        return {'stat': np.inf, 'p_value': 0.0, 'n_violations': int(n_viol),
                'violation_rate': 1.0, 'expected_rate': alpha}

    # LR = 2 × [log(p_hat^x × (1-p_hat)^(n-x)) - log(α^x × (1-α)^(n-x))]
    lr = 2 * (n_viol * np.log(p_hat / alpha) +
              (n_obs - n_viol) * np.log((1 - p_hat) / (1 - alpha)))

    p_val = 1 - chi2.cdf(lr, df=1)

    return {
        'stat': float(lr),
        'p_value': float(p_val),
        'n_violations': int(n_viol),
        'violation_rate': float(p_hat),
        'expected_rate': alpha
    }


def christoffersen_test(violations):
    """
    Christoffersen (1998) conditional coverage test.
    Tests both unconditional coverage AND independence.
    H0: violations are iid Bernoulli
    LR_CC = LR_UC + LR_IND ~ χ²(2)
    """
    n = len(violations)
    viol = violations.astype(int)

    # Count transitions
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if viol[i-1] == 0 and viol[i] == 0:
            n00 += 1
        elif viol[i-1] == 0 and viol[i] == 1:
            n01 += 1
        elif viol[i-1] == 1 and viol[i] == 0:
            n10 += 1
        else:
            n11 += 1

    # Independence test
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return {'stat': 0, 'p_value': 1.0, 'independence_stat': 0,
                'independence_p': 1.0, 'n00': n00, 'n01': n01, 'n10': n10, 'n11': n11}

    p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p_hat = (n01 + n11) / (n - 1)

    # Guard against log(0)
    eps = 1e-15

    # LR_IND
    if p01 < eps or p11 < eps or (1-p01) < eps or (1-p11) < eps or p_hat < eps or (1-p_hat) < eps:
        lr_ind = 0
    else:
        lr_ind = 2 * (n00 * np.log(max((1-p01), eps) / max((1-p_hat), eps)) +
                       n01 * np.log(max(p01, eps) / max(p_hat, eps)) +
                       n10 * np.log(max((1-p11), eps) / max((1-p_hat), eps)) +
                       n11 * np.log(max(p11, eps) / max(p_hat, eps)))

    lr_ind = max(0, lr_ind)
    p_ind = 1 - chi2.cdf(lr_ind, df=1)

    # Full CC test = UC + IND (but we just return IND since Kupiec handles UC)
    return {
        'independence_stat': float(lr_ind),
        'independence_p': float(p_ind),
        'n00': int(n00), 'n01': int(n01),
        'n10': int(n10), 'n11': int(n11),
        'p01': float(p01), 'p11': float(p11)
    }


def basel_traffic_light(n_violations, n_obs, alpha):
    """
    Basel III traffic light system (250-day window standard, but we scale).
    Green: ≤ threshold_green violations
    Yellow: > green, ≤ red
    Red: > threshold_red

    For 250-day @ 1%: Green ≤ 4, Yellow 5-9, Red ≥ 10
    Scale proportionally for other window sizes.
    """
    expected = n_obs * alpha

    # Basel thresholds for 1% VaR over 250 days:
    # Zone 0 (green): 0-4 exceedances → surcharge 0
    # Zone 1 (yellow): 5-9 → surcharge 0.4-0.85
    # Zone 2 (red): 10+ → surcharge 1.0

    # Scale for actual window size
    scale = n_obs / 250
    green_threshold = 4 * scale
    red_threshold = 10 * scale

    if alpha == 0.05:
        # For 5% VaR, scale thresholds: expected is 5x more
        green_threshold = 5 * green_threshold
        red_threshold = 5 * red_threshold

    if n_violations <= green_threshold:
        zone = 'Green'
        surcharge = 0.0
    elif n_violations <= red_threshold:
        zone = 'Yellow'
        frac = (n_violations - green_threshold) / (red_threshold - green_threshold)
        surcharge = 0.4 + 0.6 * frac
    else:
        zone = 'Red'
        surcharge = 1.0

    return {
        'zone': zone,
        'surcharge': float(round(surcharge, 3)),
        'n_violations': int(n_violations),
        'expected_violations': float(round(expected, 1)),
        'ratio': float(round(n_violations / max(expected, 1), 3))
    }


def acerbi_szekely_test(returns, var_forecasts, es_forecasts, alpha, n_bootstrap=1000):
    """
    Acerbi & Szekely (2014) ES backtest.
    Z = (1/N_α) × Σ (r_t × I(r_t < -VaR_t)) / ES_t + 1
    Under H0: E[Z] = 0
    One-sided test: Z < 0 means ES is too small (underestimates risk).
    """
    violations = returns < -var_forecasts
    n_viol = np.sum(violations)

    if n_viol == 0:
        return {'Z_stat': 0, 'p_value': 1.0, 'n_violations': 0}

    # Z statistic
    ratio = np.where(violations,
                     returns / (-es_forecasts),  # r_t / (-ES_t), both negative
                     0.0)
    Z = np.sum(ratio[violations]) / n_viol + 1

    # Bootstrap for p-value
    np.random.seed(42)
    Z_boot = np.zeros(n_bootstrap)
    for b in range(n_bootstrap):
        idx = np.random.choice(len(returns), size=len(returns), replace=True)
        r_b = returns[idx]
        var_b = var_forecasts[idx]
        es_b = es_forecasts[idx]
        viol_b = r_b < -var_b
        n_viol_b = np.sum(viol_b)
        if n_viol_b > 0:
            ratio_b = np.where(viol_b, r_b / (-es_b), 0.0)
            Z_boot[b] = np.sum(ratio_b[viol_b]) / n_viol_b + 1
        else:
            Z_boot[b] = 0

    p_val = np.mean(Z_boot <= Z)  # one-sided: Z < 0 rejects

    return {
        'Z_stat': float(Z),
        'p_value': float(p_val),
        'n_violations': int(n_viol)
    }


# ============================================================
# Main Expanding-Window OOS Engine
# ============================================================

def run_oos_var_es(returns, abs_returns, min_window=500, refit_freq=63,
                   alphas=[0.01, 0.05], hist_window=250):
    """
    Expanding-window OOS VaR/ES forecasting for all 5 models.

    Models:
    1. GJR-GARCH (Student-t)
    2. AMEM (Gamma)
    3. HAR-ABS (Gaussian from σ estimate)
    4. EWMA (Gaussian)
    5. Historical Simulation (rolling 250-day)

    Returns: dict of {model: {alpha: {'var': [...], 'es': [...], 'returns': [...]}}}
    """
    T = len(returns)
    n_oos = T - min_window

    print(f"  Total obs: {T}, Min window: {min_window}, OOS: {n_oos}")
    print(f"  Refit freq: {refit_freq} days, Alphas: {alphas}")

    # Storage
    models = ['gjr', 'amem', 'har_abs', 'ewma', 'hist_sim']
    results = {}
    for m in models:
        results[m] = {}
        for a in alphas:
            results[m][a] = {'var': [], 'es': [], 'actual_return': []}

    # Model caches (refit every refit_freq days)
    gjr_params = None
    amem_params = None
    har_params = None
    last_refit = -refit_freq  # force refit on first step

    refit_count = 0

    for t in range(min_window, T):
        oos_idx = t - min_window

        # Data up to t-1 (for forecast at t)
        r_train = returns[:t]
        abs_train = abs_returns[:t]

        # Refit models periodically
        if (t - min_window) - last_refit >= refit_freq or gjr_params is None:
            last_refit = t - min_window
            refit_count += 1

            if refit_count % 10 == 1:
                print(f"  Refit #{refit_count} at t={t} (OOS {oos_idx}/{n_oos})")

            # Fit GJR-GARCH with t-dist
            gjr_params = fit_gjr_garch(r_train, fit_df=True)

            # Fit AMEM
            amem_params = fit_amem(abs_train, r_train)

            # Fit HAR-ABS
            har_params = fit_har_abs(abs_train)

        # Actual return at time t
        r_actual = returns[t]

        for a in alphas:
            # 1. GJR-GARCH VaR/ES (Student-t)
            if gjr_params is not None:
                sigma_gjr = gjr_forecast_sigma(r_train, gjr_params)
                v_gjr = var_gjr(sigma_gjr, gjr_params['df'], a)
                e_gjr = es_gjr(sigma_gjr, gjr_params['df'], a)
            else:
                sigma_gjr = np.std(r_train)
                v_gjr = var_gaussian(sigma_gjr, a)
                e_gjr = es_gaussian(sigma_gjr, a)
            results['gjr'][a]['var'].append(v_gjr)
            results['gjr'][a]['es'].append(e_gjr)
            results['gjr'][a]['actual_return'].append(r_actual)

            # 2. AMEM VaR/ES (Gamma)
            if amem_params is not None:
                mu_amem = amem_forecast_mu(abs_train, r_train, amem_params)
                v_amem = var_amem(mu_amem, amem_params['k'], a)
                e_amem = es_amem(mu_amem, amem_params['k'], a)
            else:
                mu_amem = np.mean(abs_train)
                sigma_est = mu_amem * np.sqrt(np.pi / 2)
                v_amem = var_gaussian(sigma_est, a)
                e_amem = es_gaussian(sigma_est, a)
            results['amem'][a]['var'].append(v_amem)
            results['amem'][a]['es'].append(e_amem)
            results['amem'][a]['actual_return'].append(r_actual)

            # 3. HAR-ABS VaR/ES (Gaussian)
            if har_params is not None:
                mu_har = har_abs_forecast(abs_train, har_params)
                if mu_har is not None:
                    sigma_har = mu_har * np.sqrt(np.pi / 2)  # E[|r|] = σ√(2/π)
                else:
                    sigma_har = np.std(r_train)
            else:
                sigma_har = np.std(r_train)
            v_har = var_gaussian(sigma_har, a)
            e_har = es_gaussian(sigma_har, a)
            results['har_abs'][a]['var'].append(v_har)
            results['har_abs'][a]['es'].append(e_har)
            results['har_abs'][a]['actual_return'].append(r_actual)

            # 4. EWMA VaR/ES (Gaussian)
            sigma_ewma = ewma_forecast_sigma(r_train)
            v_ewma = var_gaussian(sigma_ewma, a)
            e_ewma = es_gaussian(sigma_ewma, a)
            results['ewma'][a]['var'].append(v_ewma)
            results['ewma'][a]['es'].append(e_ewma)
            results['ewma'][a]['actual_return'].append(r_actual)

            # 5. Historical Simulation (rolling window)
            hist_start = max(0, t - hist_window)
            r_hist = returns[hist_start:t]
            v_hist = var_historical(r_hist, a)
            e_hist = es_historical(r_hist, a)
            results['hist_sim'][a]['var'].append(v_hist)
            results['hist_sim'][a]['es'].append(e_hist)
            results['hist_sim'][a]['actual_return'].append(r_actual)

    # Convert to numpy
    for m in models:
        for a in alphas:
            for k in ['var', 'es', 'actual_return']:
                results[m][a][k] = np.array(results[m][a][k])

    print(f"  Total refits: {refit_count}")
    return results


# ============================================================
# Part C: Inverse-ES Portfolio Allocation
# ============================================================

def inverse_es_portfolio(spy_returns, gld_returns, spy_abs, gld_abs,
                         min_window=500, refit_freq=21, alpha_es=0.05):
    """
    Allocate SPY vs GLD inversely proportional to forecast ES.
    w_SPY = ES_GLD / (ES_SPY + ES_GLD)
    Monthly rebalancing (refit_freq=21).

    Uses GJR-GARCH (best VaR model from Part B typically) for ES forecasts.
    Also try AMEM-based ES and EWMA-based ES.
    """
    T = len(spy_returns)
    n_oos = T - min_window

    print(f"\n=== Part C: Inverse-ES Portfolio ===")
    print(f"  OOS days: {n_oos}, rebalance freq: {refit_freq}")

    # Storage for different ES-based allocations
    methods = ['gjr_es', 'amem_es', 'ewma_es', '12_vix', 'equal_50_50']
    port_returns = {m: [] for m in methods}
    weights_spy = {m: [] for m in methods}

    # Caches
    spy_gjr = None
    gld_gjr = None
    spy_amem = None
    gld_amem = None
    last_refit = -refit_freq

    # For 12/VIX we need VIX data — compute separately outside
    # Here we just do ES-based and benchmarks

    refit_count = 0

    for t in range(min_window, T):
        spy_r_train = spy_returns[:t]
        gld_r_train = gld_returns[:t]
        spy_abs_train = spy_abs[:t]
        gld_abs_train = gld_abs[:t]

        # Refit
        if (t - min_window) - last_refit >= refit_freq or spy_gjr is None:
            last_refit = t - min_window
            refit_count += 1

            spy_gjr = fit_gjr_garch(spy_r_train, fit_df=True)
            gld_gjr = fit_gjr_garch(gld_r_train, fit_df=True)
            spy_amem = fit_amem(spy_abs_train, spy_r_train)
            gld_amem = fit_amem(gld_abs_train, gld_r_train)

        # GJR-ES weights
        if spy_gjr and gld_gjr:
            spy_sigma = gjr_forecast_sigma(spy_r_train, spy_gjr)
            gld_sigma = gjr_forecast_sigma(gld_r_train, gld_gjr)
            spy_es = es_gjr(spy_sigma, spy_gjr['df'], alpha_es)
            gld_es = es_gjr(gld_sigma, gld_gjr['df'], alpha_es)
            w_spy_gjr = gld_es / (spy_es + gld_es)
        else:
            w_spy_gjr = 0.5

        # AMEM-ES weights
        if spy_amem and gld_amem:
            spy_mu = amem_forecast_mu(spy_abs_train, spy_r_train, spy_amem)
            gld_mu = amem_forecast_mu(gld_abs_train, gld_r_train, gld_amem)
            spy_es_a = es_amem(spy_mu, spy_amem['k'], alpha_es)
            gld_es_a = es_amem(gld_mu, gld_amem['k'], alpha_es)
            w_spy_amem = gld_es_a / (spy_es_a + gld_es_a)
        else:
            w_spy_amem = 0.5

        # EWMA-ES weights
        spy_sigma_ewma = ewma_forecast_sigma(spy_r_train)
        gld_sigma_ewma = ewma_forecast_sigma(gld_r_train)
        spy_es_e = es_gaussian(spy_sigma_ewma, alpha_es)
        gld_es_e = es_gaussian(gld_sigma_ewma, alpha_es)
        w_spy_ewma = gld_es_e / (spy_es_e + gld_es_e)

        # Portfolio returns at time t (signal from t-1 data)
        r_spy = spy_returns[t]
        r_gld = gld_returns[t]

        port_returns['gjr_es'].append(w_spy_gjr * r_spy + (1 - w_spy_gjr) * r_gld)
        port_returns['amem_es'].append(w_spy_amem * r_spy + (1 - w_spy_amem) * r_gld)
        port_returns['ewma_es'].append(w_spy_ewma * r_spy + (1 - w_spy_ewma) * r_gld)
        port_returns['equal_50_50'].append(0.5 * r_spy + 0.5 * r_gld)

        weights_spy['gjr_es'].append(w_spy_gjr)
        weights_spy['amem_es'].append(w_spy_amem)
        weights_spy['ewma_es'].append(w_spy_ewma)
        weights_spy['equal_50_50'].append(0.5)

    print(f"  Total refits: {refit_count}")

    # Convert
    for m in methods:
        if len(port_returns[m]) > 0:
            port_returns[m] = np.array(port_returns[m])
            weights_spy[m] = np.array(weights_spy[m])

    return port_returns, weights_spy


def compute_portfolio_metrics(returns, ann_factor=252):
    """Compute Sharpe, MDD, Calmar, Sortino for a return series."""
    if len(returns) == 0:
        return {}
    cum = np.cumprod(1 + returns)
    total_ret = cum[-1] / cum[0] - 1
    n_years = len(returns) / ann_factor
    cagr = (1 + total_ret) ** (1 / max(n_years, 0.01)) - 1

    mean_r = np.mean(returns) * ann_factor
    std_r = np.std(returns, ddof=1) * np.sqrt(ann_factor)
    sharpe = mean_r / std_r if std_r > 0 else 0

    # MDD
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = np.min(dd)

    # Calmar
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    downside = returns[returns < 0]
    down_std = np.std(downside, ddof=1) * np.sqrt(ann_factor) if len(downside) > 1 else std_r
    sortino = mean_r / down_std if down_std > 0 else 0

    return {
        'sharpe': round(float(sharpe), 4),
        'cagr': round(float(cagr), 4),
        'mdd': round(float(mdd), 4),
        'calmar': round(float(calmar), 4),
        'sortino': round(float(sortino), 4),
        'ann_vol': round(float(std_r), 4),
        'n_days': len(returns)
    }


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("K780: Tail-First Expected Shortfall Allocation")
    print("[提出: Codex GPT-5.4, 執行: Claude]")
    print("=" * 70)

    # ---- Data ----
    print("\n--- Downloading data ---")
    spy = yf.download('SPY', start='2006-01-01', end='2026-04-01', progress=False)
    gld = yf.download('GLD', start='2006-01-01', end='2026-04-01', progress=False)
    vix = yf.download('^VIX', start='2006-01-01', end='2026-04-01', progress=False)

    # Handle multi-index columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(gld.columns, pd.MultiIndex):
        gld.columns = gld.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Align dates
    common_idx = spy.index.intersection(gld.index).intersection(vix.index)
    spy = spy.loc[common_idx]
    gld = gld.loc[common_idx]
    vix = vix.loc[common_idx]

    spy_ret = spy['Close'].pct_change().dropna().values
    gld_ret = gld['Close'].pct_change().dropna().values
    vix_close = vix['Close'].values[1:]  # align with returns

    # Make sure aligned
    n = min(len(spy_ret), len(gld_ret), len(vix_close))
    spy_ret = spy_ret[:n]
    gld_ret = gld_ret[:n]
    vix_close = vix_close[:n]

    spy_abs = np.abs(spy_ret)
    gld_abs = np.abs(gld_ret)

    dates = common_idx[1:n+1]  # dates for returns

    print(f"  SPY returns: {len(spy_ret)} obs, {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  GLD returns: {len(gld_ret)} obs")
    print(f"  VIX: {len(vix_close)} obs")

    # Diagnostics
    print(f"\n  SPY: mean={np.mean(spy_ret)*252:.4f}, vol={np.std(spy_ret)*np.sqrt(252):.4f}")
    print(f"  GLD: mean={np.mean(gld_ret)*252:.4f}, vol={np.std(gld_ret)*np.sqrt(252):.4f}")
    print(f"  SPY skew={pd.Series(spy_ret).skew():.3f}, kurt={pd.Series(spy_ret).kurtosis():.3f}")

    MIN_WINDOW = 500
    REFIT_FREQ = 63  # quarterly refit
    ALPHAS = [0.01, 0.05]

    # ============================================================
    # Part A + B: OOS VaR/ES for SPY
    # ============================================================
    print("\n" + "=" * 70)
    print("PART A + B: OOS VaR/ES Backtesting (SPY)")
    print("=" * 70)

    oos_results = run_oos_var_es(spy_ret, spy_abs, min_window=MIN_WINDOW,
                                 refit_freq=REFIT_FREQ, alphas=ALPHAS)

    # Backtest each model at each alpha
    model_names = {
        'gjr': 'GJR-GARCH(t)',
        'amem': 'AMEM(Gamma)',
        'har_abs': 'HAR-ABS(Gauss)',
        'ewma': 'EWMA(Gauss)',
        'hist_sim': 'Hist.Sim(250d)'
    }

    backtest_results = {}

    for model_key, model_name in model_names.items():
        backtest_results[model_key] = {}
        for alpha in ALPHAS:
            data = oos_results[model_key][alpha]
            var_f = data['var']
            es_f = data['es']
            actual = data['actual_return']

            n_oos = len(actual)

            # Violations: actual < -VaR (loss exceeds VaR)
            violations = actual < -var_f

            # Kupiec
            kupiec = kupiec_test(violations, n_oos, alpha)

            # Christoffersen
            cc = christoffersen_test(violations)

            # Basel
            basel = basel_traffic_light(kupiec['n_violations'], n_oos, alpha)

            # Acerbi-Szekely ES test
            as_test = acerbi_szekely_test(actual, var_f, es_f, alpha)

            backtest_results[model_key][alpha] = {
                'kupiec': kupiec,
                'christoffersen': cc,
                'basel': basel,
                'acerbi_szekely': as_test,
                'n_oos': n_oos,
                'mean_var': float(np.mean(var_f)),
                'mean_es': float(np.mean(es_f))
            }

            print(f"\n  {model_name} @ α={alpha}:")
            print(f"    Violations: {kupiec['n_violations']}/{n_oos} = {kupiec['violation_rate']:.4f} (target: {alpha})")
            print(f"    Kupiec p={kupiec['p_value']:.4f} | CC Indep p={cc['independence_p']:.4f}")
            print(f"    Basel: {basel['zone']} (ratio={basel['ratio']:.2f})")
            print(f"    ES test Z={as_test['Z_stat']:.4f}, p={as_test['p_value']:.4f}")
            print(f"    Mean VaR={np.mean(var_f):.6f}, Mean ES={np.mean(es_f):.6f}")

    # ============================================================
    # Summary Table (Part B)
    # ============================================================
    print("\n" + "=" * 70)
    print("PART B SUMMARY: VaR Backtest Scorecard")
    print("=" * 70)

    # Scoring: for each test, score 0-3
    # Kupiec p > 0.05 = 3 (pass), p > 0.01 = 2, p < 0.01 = 1, violation=0 = 0
    # CC Indep p > 0.05 = 2 (pass), else 0
    # Basel Green = 3, Yellow = 1, Red = 0
    # AS ES p > 0.05 = 2 (pass), else 0

    scores = {}
    for model_key in model_names:
        score = 0
        for alpha in ALPHAS:
            bt = backtest_results[model_key][alpha]
            k = bt['kupiec']
            c = bt['christoffersen']
            b = bt['basel']
            a_s = bt['acerbi_szekely']

            # Kupiec: closer violation rate to target = better
            viol_ratio = abs(k['violation_rate'] - alpha) / alpha
            if viol_ratio < 0.2:
                score += 3  # within 20% of target
            elif viol_ratio < 0.5:
                score += 2
            elif viol_ratio < 1.0:
                score += 1

            # Kupiec p-value
            if k['p_value'] > 0.05:
                score += 2
            elif k['p_value'] > 0.01:
                score += 1

            # Independence
            if c['independence_p'] > 0.05:
                score += 2

            # Basel
            if b['zone'] == 'Green':
                score += 3
            elif b['zone'] == 'Yellow':
                score += 1

            # ES calibration
            if a_s['p_value'] > 0.05:
                score += 2
            elif a_s['p_value'] > 0.01:
                score += 1

        scores[model_key] = score

    # Print scorecard
    print(f"\n  {'Model':<20} {'Score':>6} {'1% Viol':>10} {'5% Viol':>10} {'1% Basel':>10} {'5% Basel':>10}")
    print("  " + "-" * 68)
    for model_key in sorted(scores, key=lambda x: scores[x], reverse=True):
        mn = model_names[model_key]
        s = scores[model_key]
        v1 = backtest_results[model_key][0.01]['kupiec']['violation_rate']
        v5 = backtest_results[model_key][0.05]['kupiec']['violation_rate']
        b1 = backtest_results[model_key][0.01]['basel']['zone']
        b5 = backtest_results[model_key][0.05]['basel']['zone']
        print(f"  {mn:<20} {s:>6} {v1:>10.4f} {v5:>10.4f} {b1:>10} {b5:>10}")

    # ============================================================
    # Part C: Inverse-ES Portfolio
    # ============================================================
    print("\n" + "=" * 70)
    print("PART C: Inverse-ES Portfolio Allocation (SPY + GLD)")
    print("=" * 70)

    port_ret, port_w = inverse_es_portfolio(
        spy_ret, gld_ret, spy_abs, gld_abs,
        min_window=MIN_WINDOW, refit_freq=21, alpha_es=0.05
    )

    # Also compute 12/VIX benchmark
    n_oos_port = len(port_ret['equal_50_50'])
    oos_start = MIN_WINDOW
    vix_oos = vix_close[oos_start:oos_start + n_oos_port]
    spy_ret_oos = spy_ret[oos_start:oos_start + n_oos_port]
    gld_ret_oos = gld_ret[oos_start:oos_start + n_oos_port]

    # 12/VIX weights with proper lag (signal from t-1)
    w_12vix = np.clip(12.0 / vix_oos, 0, 1.0)
    w_12vix_lagged = np.roll(w_12vix, 1)
    w_12vix_lagged[0] = 0.5  # first day use equal weight
    port_ret_12vix = w_12vix_lagged * spy_ret_oos + (1 - w_12vix_lagged) * gld_ret_oos

    port_ret['12_vix'] = port_ret_12vix
    port_w['12_vix'] = w_12vix_lagged

    # Compute metrics
    print(f"\n  Portfolio metrics (OOS {n_oos_port} days):")
    print(f"  {'Strategy':<20} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8} {'Vol':>8}")
    print("  " + "-" * 72)

    portfolio_metrics = {}
    for method in ['gjr_es', 'amem_es', 'ewma_es', '12_vix', 'equal_50_50']:
        if method in port_ret and len(port_ret[method]) > 0:
            metrics = compute_portfolio_metrics(port_ret[method])
            portfolio_metrics[method] = metrics

            # Weight stats
            w = port_w[method] if method in port_w else np.full(n_oos_port, 0.5)
            metrics['mean_spy_weight'] = round(float(np.mean(w)), 4)
            metrics['std_spy_weight'] = round(float(np.std(w)), 4)
            metrics['turnover'] = round(float(np.mean(np.abs(np.diff(w)))), 6)

            print(f"  {method:<20} {metrics['sharpe']:>8.4f} {metrics['cagr']:>8.4f} "
                  f"{metrics['mdd']:>8.4f} {metrics['calmar']:>8.4f} "
                  f"{metrics['sortino']:>8.4f} {metrics['ann_vol']:>8.4f}")

    # ============================================================
    # Part D: Model Ranking by Economic Criterion
    # ============================================================
    print("\n" + "=" * 70)
    print("PART D: Model Ranking by Economic Criterion")
    print("=" * 70)

    # Composite score: VaR accuracy + ES calibration + Basel compliance
    # Weighted: VaR calibration (40%) + Independence (20%) + Basel (20%) + ES test (20%)

    economic_ranking = {}
    for model_key in model_names:
        rank_score = 0
        details = {}

        for alpha in ALPHAS:
            bt = backtest_results[model_key][alpha]
            k = bt['kupiec']
            c = bt['christoffersen']
            b = bt['basel']
            a_s = bt['acerbi_szekely']

            # VaR calibration: 1 - |violation_rate - target| / target (capped at [0,1])
            calib = max(0, 1 - abs(k['violation_rate'] - alpha) / alpha)

            # Independence: binary
            indep = 1.0 if c['independence_p'] > 0.05 else 0.0

            # Basel: Green=1, Yellow=0.5, Red=0
            basel_score = {'Green': 1.0, 'Yellow': 0.5, 'Red': 0.0}[b['zone']]

            # ES calibration: binary
            es_score = 1.0 if a_s['p_value'] > 0.05 else 0.0

            composite = 0.4 * calib + 0.2 * indep + 0.2 * basel_score + 0.2 * es_score
            rank_score += composite

            details[f'alpha_{alpha}'] = {
                'calibration': round(calib, 4),
                'independence': indep,
                'basel_score': basel_score,
                'es_score': es_score,
                'composite': round(composite, 4)
            }

        economic_ranking[model_key] = {
            'total_score': round(rank_score, 4),
            'details': details
        }

    # Print ranking
    print(f"\n  {'Rank':>4} {'Model':<20} {'Total':>8} {'1% Score':>10} {'5% Score':>10}")
    print("  " + "-" * 56)

    ranked = sorted(economic_ranking.items(), key=lambda x: x[1]['total_score'], reverse=True)
    for rank, (model_key, data) in enumerate(ranked, 1):
        mn = model_names[model_key]
        total = data['total_score']
        s1 = data['details']['alpha_0.01']['composite']
        s5 = data['details']['alpha_0.05']['composite']
        print(f"  {rank:>4} {mn:<20} {total:>8.4f} {s1:>10.4f} {s5:>10.4f}")

    # ============================================================
    # Key Finding: Does best VaR model = best forecast model?
    # ============================================================
    print("\n" + "=" * 70)
    print("KEY FINDING: Forecast Accuracy vs Risk Management")
    print("=" * 70)

    best_var_model = ranked[0][0]
    worst_var_model = ranked[-1][0]

    print(f"\n  Best risk management model: {model_names[best_var_model]} (score={ranked[0][1]['total_score']:.3f})")
    print(f"  Worst risk management model: {model_names[worst_var_model]} (score={ranked[-1][1]['total_score']:.3f})")
    print(f"\n  From K778: GJR best QLIKE on σ², AMEM best on |r|")
    print(f"  → Does forecast champion = risk management champion?")
    print(f"  → Answer: {model_names[best_var_model]} wins risk management")

    # ES allocation insight
    if 'gjr_es' in portfolio_metrics and 'equal_50_50' in portfolio_metrics:
        gjr_sharpe = portfolio_metrics['gjr_es']['sharpe']
        eq_sharpe = portfolio_metrics['equal_50_50']['sharpe']
        diff = gjr_sharpe - eq_sharpe
        print(f"\n  ES-based allocation Sharpe: {gjr_sharpe:.4f}")
        print(f"  Equal 50/50 Sharpe: {eq_sharpe:.4f}")
        print(f"  Difference: {diff:+.4f}")
        if abs(diff) < 0.1:
            print(f"  → ES-based allocation ≈ 50/50 (confirms K116/K687: hard to beat naive)")
        elif diff > 0:
            print(f"  → ES-based allocation beats 50/50!")
        else:
            print(f"  → 50/50 still wins (tail risk allocation doesn't add value)")

    # ============================================================
    # Save Results
    # ============================================================
    print("\n\nSaving results...")

    # Prepare serializable backtest results
    bt_serial = {}
    for model_key in model_names:
        bt_serial[model_key] = {}
        for alpha in ALPHAS:
            bt = backtest_results[model_key][alpha]
            bt_serial[model_key][str(alpha)] = {
                'kupiec': bt['kupiec'],
                'christoffersen': bt['christoffersen'],
                'basel': bt['basel'],
                'acerbi_szekely': bt['acerbi_szekely'],
                'n_oos': bt['n_oos'],
                'mean_var': bt['mean_var'],
                'mean_es': bt['mean_es']
            }

    # Serializable economic ranking
    econ_serial = {}
    for k, v in economic_ranking.items():
        econ_serial[k] = v

    results = {
        'experiment_id': 'K780',
        'title': 'Tail-First Expected Shortfall Allocation — Risk Control Over Vol Prediction',
        'proposer': 'Codex GPT-5.4',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance SPY, GLD, VIX 2006-2026',
        'n_spy': len(spy_ret),
        'n_oos': int(len(spy_ret) - MIN_WINDOW),
        'min_window': MIN_WINDOW,
        'refit_freq': REFIT_FREQ,
        'oos_period': f"{dates[MIN_WINDOW].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
        'models': list(model_names.values()),
        'part_b_backtest': bt_serial,
        'part_b_scores': scores,
        'part_c_portfolio_metrics': portfolio_metrics,
        'part_d_economic_ranking': econ_serial,
        'best_risk_model': model_names[best_var_model],
        'best_risk_score': ranked[0][1]['total_score'],
        'key_findings': {
            'best_var_model': model_names[best_var_model],
            'worst_var_model': model_names[worst_var_model],
            'es_vs_5050': f"GJR-ES Sharpe {portfolio_metrics.get('gjr_es', {}).get('sharpe', 'N/A')} vs 50/50 {portfolio_metrics.get('equal_50_50', {}).get('sharpe', 'N/A')}",
            'forecast_vs_risk': 'See part_d for full ranking'
        },
        'references': [
            'Kupiec (1995) "Techniques for verifying risk measurement models" J.Derivatives',
            'Christoffersen (1998) "Evaluating interval forecasts" Intl Economic Review',
            'Acerbi & Szekely (2014) "Backtesting Expected Shortfall" Risk Magazine',
            'Basel III BCBS (2016) traffic light system',
            'Engle & Gallo (2006) MEM for volatility',
            'K770: AMEM beats HAR-ABS',
            'K778: GJR beats MEM in sigma-squared space',
            'K116: CVaR Tail Risk Parity null result'
        ]
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n  Results saved to {RESULTS_PATH}")
    print("\n" + "=" * 70)
    print("K780 COMPLETE")
    print("=" * 70)

    return results


if __name__ == '__main__':
    main()
