#!/usr/bin/env python3
"""
K905: Quantile Regression for Volatility — From Point to Distribution
=====================================================================
[提出: 用戶, 執行: Claude]

Research Question:
  Can direct quantile recursion (CAViaR-style on returns) outperform
  traditional GARCH + distributional assumption for VaR forecasting?

Background:
  - K824v2: GJR + HistSim confirmed best among GARCH-residual-quantile methods
  - CAViaR (Engle & Manganelli 2004): Direct quantile dynamics, no σ² needed
  - Phase O15: CAViaR-SAV ≈ GJR-SkewT (DM p=0.35, not significantly different)
  - This experiment extends with: (a) longer OOS (2019-2026), (b) Quantile HAR,
    (c) pinball loss scoring, (d) comprehensive VaR+ES evaluation

Models:
  M1: GJR-GARCH + Normal VaR
  M2: GJR-GARCH + Student-t VaR (df estimated from residuals, scaled)
  M3: GJR-GARCH + FHS (historical simulation on standardized residuals)
  M4: CAViaR-SAV (direct quantile recursion: q_t = b0 + b1*q_{t-1} + b2*|r_{t-1}|)
  M5: Quantile HAR (q_τ = ω + β_d*r²_{t-1} + β_w*RV_w + β_m*RV_m, quantile loss)

Data: SPY from yfinance (2005-01-01 to latest)
OOS: 2019-01-01 to latest (~7 years, >1750 days)
Expanding window, GJR refit every 63 days, CAViaR/QR-HAR refit every 63 days

Evaluation:
  - VaR 1% and 5% violation rate
  - Trinity test: Kupiec + Christoffersen + Basel traffic light
  - ES backtest: Acerbi-Szekely Z-test (both 1% and 5%)
  - Pinball loss (proper scoring rule for quantile forecasts)
  - DM test on pinball loss (Harvey |t| > 3.0)
  - Capital efficiency: mean VaR level

Error log rules:
  - DM test: use standard implementation, Harvey t > 3.0
  - Student-t: scale term sqrt((df-2)/df) included (K824v2 fix)
  - Basel: standard 250-day lookback (K824v2 fix)
  - GARCH OOS: day-by-day recursive h[t]=f(h[t-1], r²[t-1])
  - signal.shift(1) enforced: all forecasts use data up to t-1

References:
  - Engle & Manganelli (2004) JBES 22 — CAViaR
  - Koenker & Bassett (1978) Econometrica 46 — Quantile Regression
  - Corsi (2009) J. Financial Econometrics — HAR model
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss
  - Kupiec (1995) — unconditional VaR coverage
  - Christoffersen (1998) — conditional VaR independence
  - Basel Committee (1996, 2019) — Traffic light framework
  - Acerbi & Szekely (2014) — ES backtest
  - Gneiting & Raftery (2007) JASA 102 — Pinball loss
  - Harvey et al. (2016) — multiple testing t>3.0
  - K824v2: Bug-fixed quantile forecasting (HistSim > Student-t confirmed)
  - Phase O15: CAViaR-SAV ≈ GJR-SkewT
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

RESULTS_PATH = os.path.join(os.path.dirname(__file__),
                            'k905_quantile_vol_forecast_results.json')
DATA_START = '2005-01-01'
OOS_START = '2019-01-01'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]  # VaR confidence levels

print("=" * 70)
print("K905: Quantile Regression for Volatility")
print("=" * 70)

# ================================================================
# A. GJR-GARCH core (numba-accelerated)
# ================================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1) variance filter."""
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


def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via Normal QMLE."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
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


def gjr_variance_series(returns, params):
    """Full in-sample variance series."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    return gjr_filter(r, params['omega'], params['alpha'],
                      params['beta'], params['gamma'])


def gjr_one_step_ahead(returns, params):
    """One-step-ahead forecast σ²_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_std_residuals(returns, params):
    """z_t = r_t / σ_t for in-sample data."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]


# ================================================================
# B. Student-t df estimation (K824v2 fix: scale term)
# ================================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """MLE for Student-t df with scale = sqrt((df-2)/df) for unit-variance z."""
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

    best_nll, best_df = 1e10, 5.0
    for df_init in [3.0, 5.0, 8.0, 15.0]:
        res = minimize(neg_loglik, x0=[np.log(df_init)],
                       method='L-BFGS-B',
                       bounds=[(np.log(df_min), np.log(df_max))],
                       options={'maxiter': 500})
        if res.fun < best_nll:
            best_nll = res.fun
            best_df = float(np.exp(res.x[0]))
    return float(np.clip(best_df, df_min, df_max))


# ================================================================
# C. CAViaR-SAV (direct quantile recursion)
# ================================================================

@njit(cache=True)
def caviar_sav_filter(b0, b1, b2, returns, q0):
    """CAViaR-SAV: q_t = b0 + b1*q_{t-1} + b2*|r_{t-1}|
    Returns negative quantile (VaR is negative for losses)."""
    T = len(returns)
    q = np.empty(T)
    q[0] = q0
    for t in range(1, T):
        q[t] = b0 + b1 * q[t - 1] + b2 * abs(returns[t - 1])
    return q


@njit(cache=True)
def quantile_loss(returns, q, tau):
    """Quantile loss (check/tick function): ρ_τ(r - q) = (r - q)(τ - I(r < q))."""
    T = len(returns)
    loss = 0.0
    for t in range(T):
        e = returns[t] - q[t]
        if e < 0:
            loss += e * (tau - 1.0)
        else:
            loss += e * tau
    return loss / T


def fit_caviar_sav(returns, alpha, n_restarts=5):
    """Fit CAViaR-SAV for a given quantile level alpha (e.g., 0.01 or 0.05).

    q_t = b0 + b1*q_{t-1} + b2*|r_{t-1}|
    q is the alpha-quantile of returns (negative for left tail).
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    # Initial quantile from empirical distribution
    q0 = float(np.quantile(r, alpha))
    tau = alpha

    def objective(params):
        b0, b1, b2 = params
        # Enforce stationarity: b1 < 1
        if b1 >= 1.0 or b1 < 0:
            return 1e10
        q = caviar_sav_filter(b0, b1, b2, r, q0)
        loss = quantile_loss(r, q, tau)
        return loss if np.isfinite(loss) else 1e10

    best, best_loss = None, 1e10
    for seed in range(n_restarts):
        np.random.seed(seed + 200)
        # b0: intercept (small negative for left tail)
        b0_init = q0 * (1 - 0.95) + np.random.randn() * 0.001
        b1_init = np.clip(0.95 + 0.02 * np.random.randn(), 0.5, 0.999)
        b2_init = np.clip(0.05 + 0.02 * np.random.randn(), 0.001, 0.5)

        res = minimize(objective, [b0_init, b1_init, b2_init],
                       method='L-BFGS-B',
                       bounds=[(-0.1, 0.01), (0.0, 0.999), (0.001, 1.0)],
                       options={'maxiter': 3000})
        if res.fun < best_loss:
            best_loss = res.fun
            best = res.x.copy()

    if best is None:
        return None
    return {'b0': float(best[0]), 'b1': float(best[1]), 'b2': float(best[2]),
            'q0': q0}


def caviar_sav_one_step(params, last_q, last_r):
    """One-step-ahead CAViaR-SAV forecast."""
    q_next = params['b0'] + params['b1'] * last_q + params['b2'] * abs(last_r)
    return q_next


# ================================================================
# D. Quantile HAR
# ================================================================

def compute_har_features(returns_sq, idx):
    """Compute HAR features: RV_d, RV_w, RV_m at position idx.
    Uses r²_{idx} as daily, mean(r²_{idx-4:idx+1}) as weekly,
    mean(r²_{idx-21:idx+1}) as monthly."""
    # Daily: r²_{idx}
    rv_d = returns_sq[idx]
    # Weekly: mean of last 5 days (idx-4 to idx inclusive)
    start_w = max(0, idx - 4)
    rv_w = np.mean(returns_sq[start_w:idx + 1])
    # Monthly: mean of last 22 days
    start_m = max(0, idx - 21)
    rv_m = np.mean(returns_sq[start_m:idx + 1])
    return rv_d, rv_w, rv_m


def fit_quantile_har(returns, alpha, min_obs=252):
    """Fit Quantile HAR: q_τ(r_t) = ω + β_d*r²_{t-1} + β_w*RV_w_{t-1} + β_m*RV_m_{t-1}

    This predicts the alpha-quantile of r_t directly using HAR-style features
    on past squared returns, estimated via quantile regression loss.
    """
    r = np.asarray(returns, dtype=np.float64)
    r_sq = r ** 2
    T = len(r)
    if T < min_obs:
        return None

    tau = alpha
    # Build design matrix: for each t, features are from t-1
    # Start from t=22 to have enough history for monthly RV
    start = 22
    n = T - start

    X = np.zeros((n, 4))  # constant, rv_d, rv_w, rv_m
    y = np.zeros(n)

    for i in range(n):
        t = start + i
        y[i] = r[t]  # actual return at t
        rv_d, rv_w, rv_m = compute_har_features(r_sq, t - 1)  # features from t-1
        X[i, 0] = 1.0  # intercept
        X[i, 1] = rv_d
        X[i, 2] = rv_w
        X[i, 3] = rv_m

    # Quantile regression via optimization
    def objective(beta):
        q_pred = X @ beta
        loss = 0.0
        for j in range(n):
            e = y[j] - q_pred[j]
            if e < 0:
                loss += e * (tau - 1.0)
            else:
                loss += e * tau
        return loss / n

    # Multiple starting points
    best, best_loss = None, 1e10
    for seed in range(5):
        np.random.seed(seed + 300)
        # Intercept should be negative for left-tail quantiles
        emp_q = np.quantile(r, alpha)
        beta0 = np.array([
            emp_q * (1 + 0.1 * np.random.randn()),
            -2.0 * np.random.rand(),  # negative: high past vol -> more negative quantile
            -2.0 * np.random.rand(),
            -2.0 * np.random.rand()
        ])

        res = minimize(objective, beta0, method='L-BFGS-B',
                       bounds=[(-0.2, 0.05), (-50.0, 50.0),
                               (-50.0, 50.0), (-50.0, 50.0)],
                       options={'maxiter': 3000})
        if res.fun < best_loss:
            best_loss = res.fun
            best = res.x.copy()

    if best is None:
        return None
    return {'beta': best.tolist()}


def quantile_har_predict(returns, params):
    """Predict quantile using HAR features from the latest data."""
    r = np.asarray(returns, dtype=np.float64)
    r_sq = r ** 2
    idx = len(r) - 1
    rv_d, rv_w, rv_m = compute_har_features(r_sq, idx)
    x = np.array([1.0, rv_d, rv_w, rv_m])
    beta = np.array(params['beta'])
    return float(x @ beta)


# ================================================================
# E. VaR and ES computation for each model
# ================================================================

def var_normal(sigma, alpha):
    """VaR from Normal distribution: VaR = sigma * z_alpha."""
    return sigma * norm.ppf(alpha)


def var_student_t(sigma, alpha, df):
    """VaR from Student-t: VaR = sigma * t_ppf(alpha, df) * sqrt((df-2)/df)."""
    if df <= 2.0:
        df = 2.1
    scale = np.sqrt((df - 2.0) / df)
    return sigma * t_dist.ppf(alpha, df) * scale


def var_fhs(sigma, std_residuals, alpha):
    """VaR from Filtered Historical Simulation: VaR = sigma * quantile(z, alpha)."""
    z_q = np.quantile(std_residuals, alpha)
    return sigma * z_q


def es_normal(sigma, alpha):
    """ES from Normal distribution: ES = -sigma * phi(z_alpha) / alpha."""
    z_a = norm.ppf(alpha)
    return -sigma * norm.pdf(z_a) / alpha


def es_student_t(sigma, alpha, df):
    """ES from Student-t distribution."""
    if df <= 2.0:
        df = 2.1
    scale = np.sqrt((df - 2.0) / df)
    z_a = t_dist.ppf(alpha, df)
    # ES for standardized t: E[X|X<VaR] where X ~ t(df)
    es_std = -(t_dist.pdf(z_a, df) / alpha) * (df + z_a**2) / (df - 1)
    return sigma * es_std * scale


def es_fhs(sigma, std_residuals, alpha):
    """ES from FHS: mean of z below quantile, scaled by sigma."""
    z_q = np.quantile(std_residuals, alpha)
    z_below = std_residuals[std_residuals <= z_q]
    if len(z_below) == 0:
        return var_fhs(sigma, std_residuals, alpha) * 1.5
    return sigma * np.mean(z_below)


def es_caviar(returns_hist, q_series, alpha):
    """ES from CAViaR: mean of returns below VaR (non-parametric)."""
    # Use tail average of returns that violated VaR
    violations = returns_hist[returns_hist <= q_series]
    if len(violations) < 3:
        return q_series[-1] * 1.5  # fallback
    return np.mean(violations)


def es_quantile_har(returns_hist, var_forecast, alpha):
    """ES from Quantile HAR: similar to CAViaR, use historical tail."""
    # Approximate: use returns below empirical alpha quantile, scaled by current VaR ratio
    emp_var = np.quantile(returns_hist, alpha)
    violations = returns_hist[returns_hist <= emp_var]
    if len(violations) < 3:
        return var_forecast * 1.5
    emp_es = np.mean(violations)
    # Scale: if current VaR is different from empirical, adjust proportionally
    if abs(emp_var) > 1e-10:
        return emp_es * (var_forecast / emp_var)
    return var_forecast * 1.5


# ================================================================
# F. Statistical tests
# ================================================================

def kupiec_test(violations, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n = len(violations)
    v = int(np.sum(violations))
    p_hat = v / n if n > 0 else 0

    if v == 0 or v == n:
        return {'stat': 0.0, 'p_value': 1.0, 'pass': True, 'violations': v,
                'rate': p_hat, 'expected': alpha}

    lr = 2 * (v * np.log(p_hat / alpha) + (n - v) * np.log((1 - p_hat) / (1 - alpha)))
    p_val = 1 - chi2.cdf(lr, 1)
    return {'stat': float(lr), 'p_value': float(p_val), 'pass': bool(p_val > 0.05),
            'violations': v, 'rate': float(p_hat), 'expected': alpha}


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage (independence) test."""
    v = np.asarray(violations, dtype=int)
    n = len(v)
    # Count transitions
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if v[i - 1] == 0 and v[i] == 0:
            n00 += 1
        elif v[i - 1] == 0 and v[i] == 1:
            n01 += 1
        elif v[i - 1] == 1 and v[i] == 0:
            n10 += 1
        else:
            n11 += 1

    # Avoid division by zero
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return {'stat': 0.0, 'p_value': 1.0, 'pass': True}

    p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n if n > 0 else 0

    # LR independence
    ll_u = 0.0
    if p > 0 and p < 1:
        ll_u = (n01 + n11) * np.log(p) + (n00 + n10) * np.log(1 - p)

    ll_a = 0.0
    if n00 > 0 and (n00 + n01) > 0:
        ll_a += n00 * np.log(1 - p01)
    if n01 > 0:
        ll_a += n01 * np.log(max(p01, 1e-10))
    if n10 > 0 and (n10 + n11) > 0:
        ll_a += n10 * np.log(1 - p11)
    if n11 > 0:
        ll_a += n11 * np.log(max(p11, 1e-10))

    lr = 2 * (ll_a - ll_u)
    lr = max(lr, 0)
    p_val = 1 - chi2.cdf(lr, 1)
    return {'stat': float(lr), 'p_value': float(p_val), 'pass': bool(p_val > 0.05)}


def basel_traffic_light(violations, n_obs):
    """Basel II/III traffic light: standard 250-day lookback."""
    v = int(np.sum(violations))
    # Scale to 250-day equivalent
    if n_obs >= 250:
        # Use last 250 days
        v_250 = int(np.sum(violations[-250:]))
    else:
        v_250 = int(round(v * 250 / n_obs))

    if v_250 <= 4:
        color = 'Green'
    elif v_250 <= 9:
        color = 'Yellow'
    else:
        color = 'Red'
    return {'color': color, 'violations_250d': v_250, 'pass': color == 'Green'}


def acerbi_szekely_es_test(returns, var_series, es_series, alpha):
    """Acerbi & Szekely (2014) ES backtest (Z1 test).
    H0: ES model is correctly specified.
    Z1 = (1/T) * sum_{t: r_t < VaR_t} (r_t / ES_t) / alpha + 1
    Under H0, Z1 ≈ 0.
    """
    r = np.asarray(returns, dtype=np.float64)
    var_s = np.asarray(var_series, dtype=np.float64)
    es_s = np.asarray(es_series, dtype=np.float64)

    T = len(r)
    violations = r < var_s

    if np.sum(violations) == 0:
        return {'z_stat': 0.0, 'pass': True, 'n_violations': 0}

    # Z1 statistic
    z1 = 0.0
    for t in range(T):
        if r[t] < var_s[t]:
            if abs(es_s[t]) > 1e-10:
                z1 += r[t] / es_s[t]
    z1 = z1 / T / alpha + 1.0

    # Under H0, Z1 ~ N(0, 1/T * var). Approximate p-value
    # Standard error approximation from Acerbi & Szekely
    se = 1.0 / np.sqrt(T * alpha)
    z_stat = z1 / se if se > 0 else 0.0

    # Two-sided test (though one-sided is also used)
    p_val = 2 * (1 - norm.cdf(abs(z_stat)))

    return {'z1': float(z1), 'z_stat': float(z_stat), 'p_value': float(p_val),
            'pass': bool(p_val > 0.05), 'n_violations': int(np.sum(violations))}


def trinity_test(violations, n_obs, alpha):
    """Run Kupiec + Christoffersen + Basel = Trinity."""
    kup = kupiec_test(violations, alpha)
    cc = christoffersen_test(violations)
    bas = basel_traffic_light(violations, n_obs)
    all_pass = kup['pass'] and cc['pass'] and bas['pass']
    return {
        'kupiec': kup,
        'christoffersen': cc,
        'basel': bas,
        'all_pass': all_pass
    }


def pinball_loss_fn(y, q, tau):
    """Pinball (tick/check) loss: ρ_τ(y - q) = (y - q)(τ - I(y < q))."""
    e = y - q
    return np.mean(np.where(e < 0, e * (tau - 1.0), e * tau))


def dm_test_pinball(loss1, loss2):
    """Diebold-Mariano test on loss differentials."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)
    # HAC variance (Newey-West with auto bandwidth)
    max_lag = int(np.ceil(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for h in range(1, max_lag + 1):
        w = 1 - h / (max_lag + 1)
        cov_h = np.mean((d[h:] - d_bar) * (d[:-h] - d_bar))
        gamma_sum += 2 * w * cov_h
    var_d = gamma_0 + gamma_sum
    se = np.sqrt(max(var_d / n, 1e-20))
    t_stat = d_bar / se if se > 0 else 0.0
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return {'t_stat': float(t_stat), 'p_value': float(p_val),
            'mean_diff': float(d_bar), 'significant': bool(abs(t_stat) > 3.0)}


# ================================================================
# G. Data
# ================================================================

print("\n[1/5] Downloading SPY data...")
spy = yf.download("SPY", start=DATA_START, progress=False, auto_adjust=True)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
returns = spy['Close'].pct_change().dropna()
print(f"  Data: {returns.index[0].date()} to {returns.index[-1].date()}, "
      f"{len(returns)} observations")

# OOS split
oos_mask = returns.index >= OOS_START
oos_dates = returns.index[oos_mask]
n_oos = len(oos_dates)
print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()}, {n_oos} days")

# Pre-compute positions
all_dates = returns.index.tolist()
oos_positions = [all_dates.index(d) for d in oos_dates]

# ================================================================
# H. Main OOS loop
# ================================================================

print("\n[2/5] Running OOS forecasting loop...")
t_start = time.time()

# Storage for each model
results = {
    'M1_Normal': {'var_1': [], 'var_5': [], 'es_1': [], 'es_5': []},
    'M2_StudentT': {'var_1': [], 'var_5': [], 'es_1': [], 'es_5': []},
    'M3_FHS': {'var_1': [], 'var_5': [], 'es_1': [], 'es_5': []},
    'M4_CAViaR': {'var_1': [], 'var_5': [], 'es_1': [], 'es_5': []},
    'M5_QuantHAR': {'var_1': [], 'var_5': [], 'es_1': [], 'es_5': []},
}
oos_returns = []

# Model states
gjr_params = None
t_df = 5.0
caviar_params = {0.01: None, 0.05: None}
caviar_last_q = {0.01: None, 0.05: None}
qhar_params = {0.01: None, 0.05: None}

last_refit = -REFIT_EVERY  # force refit on first day
refit_count = 0

for i, pos in enumerate(oos_positions):
    # Data available up to pos-1 (signal.shift(1) enforced)
    train_end = pos  # exclusive: use returns[0:pos]
    r_train = returns.values[:train_end]

    # Refit models periodically
    if i - last_refit >= REFIT_EVERY or gjr_params is None:
        # GJR-GARCH
        gjr_params = fit_gjr(r_train)
        if gjr_params is None:
            print(f"  WARNING: GJR fit failed at i={i}, using fallback")
            gjr_params = {'omega': 1e-6, 'alpha': 0.05, 'beta': 0.9,
                          'gamma': 0.1, 'persistence': 0.999}

        # Student-t df from standardized residuals
        z_train = compute_std_residuals(r_train, gjr_params)
        t_df = estimate_t_df(z_train)

        # CAViaR-SAV for each alpha
        for alpha in ALPHA_LEVELS:
            cp = fit_caviar_sav(r_train, alpha)
            if cp is not None:
                caviar_params[alpha] = cp
                # Initialize q from last fitted value
                q_series = caviar_sav_filter(cp['b0'], cp['b1'], cp['b2'],
                                              r_train, cp['q0'])
                caviar_last_q[alpha] = float(q_series[-1])
            elif caviar_last_q[alpha] is None:
                caviar_last_q[alpha] = float(np.quantile(r_train, alpha))

        # Quantile HAR for each alpha
        for alpha in ALPHA_LEVELS:
            qhp = fit_quantile_har(r_train, alpha)
            if qhp is not None:
                qhar_params[alpha] = qhp

        last_refit = i
        refit_count += 1

    # --- GJR one-step-ahead sigma ---
    sigma2_forecast = gjr_one_step_ahead(r_train, gjr_params)
    sigma_forecast = np.sqrt(sigma2_forecast)

    # Standardized residuals for FHS (from training data)
    z_train = compute_std_residuals(r_train, gjr_params)

    # --- M1: Normal VaR/ES ---
    results['M1_Normal']['var_1'].append(var_normal(sigma_forecast, 0.01))
    results['M1_Normal']['var_5'].append(var_normal(sigma_forecast, 0.05))
    results['M1_Normal']['es_1'].append(es_normal(sigma_forecast, 0.01))
    results['M1_Normal']['es_5'].append(es_normal(sigma_forecast, 0.05))

    # --- M2: Student-t VaR/ES ---
    results['M2_StudentT']['var_1'].append(var_student_t(sigma_forecast, 0.01, t_df))
    results['M2_StudentT']['var_5'].append(var_student_t(sigma_forecast, 0.05, t_df))
    results['M2_StudentT']['es_1'].append(es_student_t(sigma_forecast, 0.01, t_df))
    results['M2_StudentT']['es_5'].append(es_student_t(sigma_forecast, 0.05, t_df))

    # --- M3: FHS VaR/ES ---
    results['M3_FHS']['var_1'].append(var_fhs(sigma_forecast, z_train, 0.01))
    results['M3_FHS']['var_5'].append(var_fhs(sigma_forecast, z_train, 0.05))
    results['M3_FHS']['es_1'].append(es_fhs(sigma_forecast, z_train, 0.01))
    results['M3_FHS']['es_5'].append(es_fhs(sigma_forecast, z_train, 0.05))

    # --- M4: CAViaR-SAV VaR ---
    for alpha_key, var_key, es_key in [(0.01, 'var_1', 'es_1'), (0.05, 'var_5', 'es_5')]:
        if caviar_params[alpha_key] is not None and caviar_last_q[alpha_key] is not None:
            # One-step recursion: q_{t+1} = b0 + b1*q_t + b2*|r_t|
            q_next = caviar_sav_one_step(caviar_params[alpha_key],
                                          caviar_last_q[alpha_key],
                                          r_train[-1])
            results['M4_CAViaR'][var_key].append(q_next)
            # ES: approximate from recent violations
            recent_r = r_train[-500:] if len(r_train) > 500 else r_train
            recent_var = np.quantile(recent_r, alpha_key)
            tail_returns = recent_r[recent_r <= recent_var]
            if len(tail_returns) >= 3:
                # Scale ES by ratio of current VaR to empirical VaR
                emp_es = np.mean(tail_returns)
                if abs(recent_var) > 1e-10:
                    es_val = emp_es * (q_next / recent_var)
                else:
                    es_val = q_next * 1.5
            else:
                es_val = q_next * 1.5
            results['M4_CAViaR'][es_key].append(es_val)
            # Update state for next step
            caviar_last_q[alpha_key] = q_next
        else:
            # Fallback
            fallback_q = float(np.quantile(r_train, alpha_key))
            results['M4_CAViaR'][var_key].append(fallback_q)
            results['M4_CAViaR'][es_key].append(fallback_q * 1.5)

    # --- M5: Quantile HAR VaR ---
    for alpha_key, var_key, es_key in [(0.01, 'var_1', 'es_1'), (0.05, 'var_5', 'es_5')]:
        if qhar_params[alpha_key] is not None:
            q_pred = quantile_har_predict(r_train, qhar_params[alpha_key])
            results['M5_QuantHAR'][var_key].append(q_pred)
            # ES from historical tail
            es_val = es_quantile_har(r_train[-500:] if len(r_train) > 500 else r_train,
                                      q_pred, alpha_key)
            results['M5_QuantHAR'][es_key].append(es_val)
        else:
            fallback_q = float(np.quantile(r_train, alpha_key))
            results['M5_QuantHAR'][var_key].append(fallback_q)
            results['M5_QuantHAR'][es_key].append(fallback_q * 1.5)

    oos_returns.append(returns.values[pos])

    if (i + 1) % 250 == 0:
        elapsed = time.time() - t_start
        print(f"  Day {i+1}/{n_oos} ({elapsed:.1f}s, {refit_count} refits)")

elapsed = time.time() - t_start
print(f"  Completed: {n_oos} OOS days, {refit_count} refits, {elapsed:.1f}s")

# Convert to arrays
oos_returns = np.array(oos_returns)
for model in results:
    for key in results[model]:
        results[model][key] = np.array(results[model][key])

# ================================================================
# I. Evaluation
# ================================================================

print("\n[3/5] Evaluating models...")

evaluation = {}
model_names = list(results.keys())

for model in model_names:
    eval_result = {}

    for alpha, var_key, es_key, suffix in [
        (0.01, 'var_1', 'es_1', '1pct'),
        (0.05, 'var_5', 'es_5', '5pct')
    ]:
        var_series = results[model][var_key]
        es_series = results[model][es_key]

        # Violations
        violations = (oos_returns < var_series).astype(int)
        viol_rate = float(np.mean(violations))
        n_viol = int(np.sum(violations))

        # Trinity test
        tri = trinity_test(violations, n_oos, alpha)

        # ES backtest
        es_test = acerbi_szekely_es_test(oos_returns, var_series, es_series, alpha)

        # Pinball loss
        pb = pinball_loss_fn(oos_returns, var_series, alpha)

        # Capital efficiency: mean |VaR|
        mean_var = float(np.mean(np.abs(var_series)))

        eval_result[f'var_{suffix}'] = {
            'violations': n_viol,
            'violation_rate': round(viol_rate, 6),
            'expected_rate': alpha,
            'trinity': {
                'kupiec': {'stat': round(tri['kupiec']['stat'], 4),
                           'p': round(tri['kupiec']['p_value'], 4),
                           'pass': tri['kupiec']['pass']},
                'christoffersen': {'stat': round(tri['christoffersen']['stat'], 4),
                                   'p': round(tri['christoffersen']['p_value'], 4),
                                   'pass': tri['christoffersen']['pass']},
                'basel': {'color': tri['basel']['color'],
                          'pass': tri['basel']['pass']},
                'all_pass': tri['all_pass']
            },
            'es_backtest': {
                'z1': round(es_test['z1'], 4) if 'z1' in es_test else None,
                'z_stat': round(es_test['z_stat'], 4) if 'z_stat' in es_test else None,
                'p': round(es_test.get('p_value', 1.0), 4),
                'pass': es_test['pass']
            },
            'pinball_loss': round(pb, 8),
            'mean_var_abs': round(mean_var, 6),
        }

    evaluation[model] = eval_result

# ================================================================
# J. DM tests on pinball loss (pairwise)
# ================================================================

print("\n[4/5] Running DM tests on pinball loss...")

# Compute pointwise pinball losses
pinball_losses = {}
for model in model_names:
    for alpha, var_key, suffix in [(0.01, 'var_1', '1pct'), (0.05, 'var_5', '5pct')]:
        var_series = results[model][var_key]
        e = oos_returns - var_series
        pw_loss = np.where(e < 0, e * (alpha - 1.0), e * alpha)
        pinball_losses[(model, suffix)] = pw_loss

dm_results = {}
# Use M3_FHS as reference (current champion)
ref_model = 'M3_FHS'
for alpha_suffix in ['1pct', '5pct']:
    ref_loss = pinball_losses[(ref_model, alpha_suffix)]
    for model in model_names:
        if model == ref_model:
            continue
        other_loss = pinball_losses[(model, alpha_suffix)]
        dm = dm_test_pinball(other_loss, ref_loss)
        key = f'{model}_vs_{ref_model}_{alpha_suffix}'
        dm_results[key] = {
            't_stat': round(dm['t_stat'], 4),
            'p_value': round(dm['p_value'], 4),
            'mean_diff': round(dm['mean_diff'], 8),
            'significant_Harvey': dm['significant'],
            'interpretation': ('better' if dm['t_stat'] < -3.0 else
                               'worse' if dm['t_stat'] > 3.0 else
                               'not_significant')
        }
        print(f"  {key}: t={dm['t_stat']:.3f}, "
              f"{'SIGNIFICANT' if dm['significant'] else 'NS'}")

# ================================================================
# K. Summary tables
# ================================================================

print("\n[5/5] Building summary...")

# Trinity pass count
trinity_summary = {}
for model in model_names:
    passes_1 = evaluation[model]['var_1pct']['trinity']['all_pass']
    passes_5 = evaluation[model]['var_5pct']['trinity']['all_pass']
    es_1 = evaluation[model]['var_1pct']['es_backtest']['pass']
    es_5 = evaluation[model]['var_5pct']['es_backtest']['pass']
    total_pass = sum([passes_1, passes_5, es_1, es_5])
    trinity_summary[model] = {
        'trinity_1pct': passes_1,
        'trinity_5pct': passes_5,
        'es_1pct': es_1,
        'es_5pct': es_5,
        'total_pass_4': total_pass,
    }

# Pinball loss ranking
pinball_ranking = {}
for suffix in ['1pct', '5pct']:
    losses = {m: evaluation[m][f'var_{suffix}']['pinball_loss'] for m in model_names}
    ranked = sorted(losses.items(), key=lambda x: x[1])
    pinball_ranking[suffix] = [{'model': m, 'pinball': l} for m, l in ranked]

# Print summary table
print("\n" + "=" * 80)
print("VaR 1% Summary")
print("-" * 80)
print(f"{'Model':<15} {'Viol%':>8} {'Kupiec':>10} {'CC':>10} {'Basel':>8} "
      f"{'Trinity':>8} {'ES':>6} {'Pinball':>12}")
for model in model_names:
    ev = evaluation[model]['var_1pct']
    tri = ev['trinity']
    es = ev['es_backtest']
    print(f"{model:<15} {ev['violation_rate']*100:>7.2f}% "
          f"{'PASS' if tri['kupiec']['pass'] else 'FAIL':>10} "
          f"{'PASS' if tri['christoffersen']['pass'] else 'FAIL':>10} "
          f"{tri['basel']['color']:>8} "
          f"{'PASS' if tri['all_pass'] else 'FAIL':>8} "
          f"{'PASS' if es['pass'] else 'FAIL':>6} "
          f"{ev['pinball_loss']:>12.8f}")

print("\n" + "=" * 80)
print("VaR 5% Summary")
print("-" * 80)
print(f"{'Model':<15} {'Viol%':>8} {'Kupiec':>10} {'CC':>10} {'Basel':>8} "
      f"{'Trinity':>8} {'ES':>6} {'Pinball':>12}")
for model in model_names:
    ev = evaluation[model]['var_5pct']
    tri = ev['trinity']
    es = ev['es_backtest']
    print(f"{model:<15} {ev['violation_rate']*100:>7.2f}% "
          f"{'PASS' if tri['kupiec']['pass'] else 'FAIL':>10} "
          f"{'PASS' if tri['christoffersen']['pass'] else 'FAIL':>10} "
          f"{tri['basel']['color']:>8} "
          f"{'PASS' if tri['all_pass'] else 'FAIL':>8} "
          f"{'PASS' if es['pass'] else 'FAIL':>6} "
          f"{ev['pinball_loss']:>12.8f}")

# Capital efficiency comparison
print("\n" + "=" * 80)
print("Capital Efficiency (mean |VaR|)")
print("-" * 80)
for model in model_names:
    v1 = evaluation[model]['var_1pct']['mean_var_abs']
    v5 = evaluation[model]['var_5pct']['mean_var_abs']
    print(f"  {model:<15}: 1% VaR = {v1*100:.3f}%, 5% VaR = {v5*100:.3f}%")

# ================================================================
# L. Save results
# ================================================================

output = {
    'experiment_id': 'K905',
    'title': 'K905: Quantile Regression for Volatility — From Point to Distribution',
    'asset': 'SPY',
    'data_source': f'yfinance (SPY, {DATA_START} to {returns.index[-1].date()})',
    'oos_period': f'{oos_dates[0].date()} to {oos_dates[-1].date()}',
    'n_oos': n_oos,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'models': model_names,
    'method': {
        'M1_Normal': 'GJR-GARCH(1,1) + Normal quantile',
        'M2_StudentT': 'GJR-GARCH(1,1) + Student-t quantile (scaled, df MLE)',
        'M3_FHS': 'GJR-GARCH(1,1) + Filtered Historical Simulation',
        'M4_CAViaR': 'CAViaR-SAV (direct quantile recursion, Engle & Manganelli 2004)',
        'M5_QuantHAR': 'Quantile HAR (HAR features + quantile regression loss)',
    },
    'evaluation': evaluation,
    'trinity_summary': trinity_summary,
    'pinball_ranking': pinball_ranking,
    'dm_tests_vs_FHS': dm_results,
    'runtime_seconds': round(elapsed, 1),
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Engle & Manganelli (2004) JBES — CAViaR',
        'Koenker & Bassett (1978) Econometrica — Quantile Regression',
        'Corsi (2009) J. Financial Econometrics — HAR',
        'Kupiec (1995) — Unconditional VaR coverage',
        'Christoffersen (1998) — Conditional VaR independence',
        'Basel Committee (1996, 2019) — Traffic light',
        'Acerbi & Szekely (2014) — ES backtest',
        'Gneiting & Raftery (2007) — Pinball loss',
        'Harvey et al. (2016) — DM t>3.0',
        'K824v2: Bug-fixed quantile forecasting',
        'Phase O15: CAViaR ≈ GJR-SkewT',
    ],
    'conclusion': '',  # Filled after analysis
}

# Determine conclusion
best_trinity = max(trinity_summary.items(), key=lambda x: x[1]['total_pass_4'])
best_pinball_1 = pinball_ranking['1pct'][0]['model']
best_pinball_5 = pinball_ranking['5pct'][0]['model']

# Check if any non-FHS model significantly beats FHS
sig_better = [k for k, v in dm_results.items() if v['interpretation'] == 'better']
sig_worse = [k for k, v in dm_results.items() if v['interpretation'] == 'worse']

conclusion_parts = []
conclusion_parts.append(
    f"Trinity pass leader: {best_trinity[0]} ({best_trinity[1]['total_pass_4']}/4)."
)
conclusion_parts.append(
    f"Best pinball 1%: {best_pinball_1}, 5%: {best_pinball_5}."
)
if sig_better:
    conclusion_parts.append(
        f"Models significantly better than FHS (|t|>3.0): {sig_better}."
    )
else:
    conclusion_parts.append(
        "No model significantly outperforms FHS on pinball loss (Harvey |t|>3.0)."
    )
if sig_worse:
    conclusion_parts.append(
        f"Models significantly worse than FHS: {sig_worse}."
    )

output['conclusion'] = ' '.join(conclusion_parts)

with open(RESULTS_PATH, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {RESULTS_PATH}")
print(f"\nConclusion: {output['conclusion']}")
print("\nDone!")
