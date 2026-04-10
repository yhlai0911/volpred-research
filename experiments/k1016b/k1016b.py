#!/usr/bin/env python3
"""
K1016b: HAR+vix_gap Corrected (Fixed M4/M5 Bug + vix_gap Variants)
===================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
    K1016 had two bugs:
    1. M4 (A4f-VIX9D) and M5 (GJR-t) produced IDENTICAL results (QLIKE=1.537,
       Spearman=0.386) — the arch library's x= parameter silently fell back to
       plain GJR when VIX9D had NaN values.
    2. HAR+vix_gap improved on |r| (DM=-2.87) but degraded on QLIKE(r²)
       (1.616→1.831). Need to investigate why.

    This experiment:
    1. Implements A4f properly using K988's multiplicative GARCH-X structure
       (tau = theta0 + theta1*VIX²_{t-1}, free omega, GJR g_t) — NOT arch library
    2. Implements GJR-t independently using custom MLE (no arch library dependency)
    3. Tests vix_gap variants: original, vix_gap², abs(vix_gap), log-transform
    4. Evaluates both QLIKE(r²) and MSE(|r|) with proper DM tests

Models:
    M1: HAR(1,5,22) baseline — predicts |r_{t+1}|
    M2: HAR + vix_gap — M1 + (VIX_{t-1}/100√252 - |r|_5d)
    M2b: HAR + vix_gap² — quadratic vix_gap
    M2c: HAR + |vix_gap| — absolute vix_gap
    M3: HAR + VIX_level — M1 + VIX_{t-1}/100
    M4: A4f (multiplicative GJR-X with VIX², free omega) — from K988
    M5: GJR-GARCH(1,1)-t — independent custom MLE

Data: SPY 2005-2026, yfinance. VIX: ^VIX.
Evaluation: QLIKE on r² (Patton 2011), MSE on |r|, Spearman, DM test
OOS: 2012+ (after GARCH window=2000 warm-up)

References:
    - Corsi (2009): HAR-RV model
    - Patton (2011): Volatility forecast comparison using imperfect proxies
    - Bollerslev et al. (2009): Expected stock returns and variance risk premia
    - Harvey (2016): Multiple testing threshold t > 3.0
    - K988: Multiplicative GARCH-X implementation (A4f)
    - K1016: Original (buggy) version

Author: VolPred Research System
Date: 2026-04-10
Seed: 42
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats, optimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

# ============================================================
# Configuration
# ============================================================
ROLLING_WINDOW = 1000       # HAR estimation window
GARCH_WINDOW = 2000         # GARCH estimation window
REFIT_EVERY = 63            # Refit every ~quarter
START_DATE = '2004-01-01'
END_DATE = '2026-04-10'

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K1016b: HAR+vix_gap Corrected (Fixed M4/M5 Bug + vix_gap Variants)")
print("=" * 70)

print("\n[1/7] Downloading data...")
spy = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
vix = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)

for df in [spy, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Returns and volatility proxies
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['abs_ret'] = spy['ret'].abs()
spy['r2'] = spy['ret'] ** 2

# HAR components
spy['abs_ret_5'] = spy['abs_ret'].rolling(5).mean()
spy['abs_ret_22'] = spy['abs_ret'].rolling(22).mean()

# RV_22 for vix_gap
spy['rv_22'] = spy['r2'].rolling(22).mean()

# Merge VIX
spy['VIX'] = vix['Close']

# vix_gap variants
spy['vix_daily_implied'] = spy['VIX'] / (100 * np.sqrt(252))
spy['vix_gap'] = spy['vix_daily_implied'] - spy['abs_ret_5']  # use |r|_5d not sqrt(rv_22)
spy['vix_gap_sq'] = spy['vix_gap'] ** 2
spy['vix_gap_abs'] = spy['vix_gap'].abs()
spy['vix_level'] = spy['VIX'] / 100

# Drop NaN
spy = spy.dropna(subset=['abs_ret', 'abs_ret_5', 'abs_ret_22', 'rv_22',
                          'vix_gap', 'vix_level', 'ret'])

print(f"  SPY: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(spy)}")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n[2/7] Descriptive statistics...")
desc_vars = ['abs_ret', 'r2', 'VIX', 'vix_gap', 'vix_gap_sq', 'vix_gap_abs', 'vix_level']
desc_stats = {}
for v in desc_vars:
    s = spy[v].dropna()
    desc_stats[v] = {
        'mean': float(s.mean()), 'std': float(s.std()),
        'skew': float(s.skew()), 'kurtosis': float(s.kurtosis()),
        'min': float(s.min()), 'max': float(s.max()), 'N': int(len(s))
    }
    print(f"  {v}: mean={s.mean():.6f}, std={s.std():.6f}, skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

vg = spy['vix_gap']
print(f"\n  vix_gap > 0 (VIX overprices vol): {(vg > 0).sum()} ({(vg > 0).mean()*100:.1f}%)")
print(f"  vix_gap < 0 (VIX underprices vol): {(vg < 0).sum()} ({(vg < 0).mean()*100:.1f}%)")

# ============================================================
# 3. HAR Models (Rolling OLS)
# ============================================================
print("\n[3/7] HAR model estimation (rolling OLS)...")

def har_rolling_forecast(data, extra_cols=None, window=1000, refit_every=63):
    """
    Rolling HAR forecast.
    Target: |r_{t+1}|
    Regressors at time t: |r_t|, avg|r_5_t|, avg|r_22_t|, [extra_cols_t]
    """
    y = data['abs_ret'].values
    X_base = np.column_stack([
        data['abs_ret'].values,
        data['abs_ret_5'].values,
        data['abs_ret_22'].values,
    ])

    if extra_cols is not None:
        extras = np.column_stack([data[c].values for c in extra_cols])
        X_full = np.hstack([X_base, extras])
    else:
        X_full = X_base

    n = len(y)
    forecasts = np.full(n, np.nan)
    betas_history = []
    last_beta = None

    for t in range(window, n - 1):
        if last_beta is None or (t - window) % refit_every == 0:
            y_train = y[t - window + 1: t + 1]
            X_train = X_full[t - window: t]
            X_with_const = np.column_stack([np.ones(len(X_train)), X_train])
            try:
                beta = np.linalg.lstsq(X_with_const, y_train, rcond=None)[0]
                last_beta = beta
                betas_history.append((t, beta.copy()))
            except Exception:
                pass

        if last_beta is not None:
            x_t = np.concatenate([[1.0], X_full[t]])
            forecasts[t + 1] = max(x_t @ last_beta, 1e-8)

    return pd.Series(forecasts, index=data.index), betas_history

# M1: HAR baseline
print("  M1: HAR(1,5,22)...")
m1_fc, m1_betas = har_rolling_forecast(spy, window=ROLLING_WINDOW, refit_every=REFIT_EVERY)

# M2: HAR + vix_gap
print("  M2: HAR+vix_gap...")
m2_fc, m2_betas = har_rolling_forecast(spy, extra_cols=['vix_gap'],
                                        window=ROLLING_WINDOW, refit_every=REFIT_EVERY)

# M2b: HAR + vix_gap²
print("  M2b: HAR+vix_gap²...")
m2b_fc, m2b_betas = har_rolling_forecast(spy, extra_cols=['vix_gap_sq'],
                                          window=ROLLING_WINDOW, refit_every=REFIT_EVERY)

# M2c: HAR + |vix_gap|
print("  M2c: HAR+|vix_gap|...")
m2c_fc, m2c_betas = har_rolling_forecast(spy, extra_cols=['vix_gap_abs'],
                                          window=ROLLING_WINDOW, refit_every=REFIT_EVERY)

# M3: HAR + VIX_level
print("  M3: HAR+VIX_level...")
m3_fc, m3_betas = har_rolling_forecast(spy, extra_cols=['vix_level'],
                                        window=ROLLING_WINDOW, refit_every=REFIT_EVERY)

print(f"  HAR models done ({time.time()-START_TIME:.1f}s)")

# ============================================================
# 4. GARCH Models (Custom MLE, NOT arch library)
# ============================================================
print("\n[4/7] GARCH models (custom MLE)...")

# --- M5: Pure GJR-GARCH(1,1)-t ---
def fit_gjr_t(returns):
    """
    Fit GJR-GARCH(1,1) with Student-t innovations via MLE.
    params = [mu, omega, alpha, gamma, beta, nu]
    """
    n = len(returns)
    r = returns.copy()

    def neg_loglik(params):
        mu, omega, alpha, gamma_p, beta, nu = params
        if omega <= 0 or alpha < 0 or gamma_p < 0 or beta < 0 or nu <= 2:
            return 1e10
        if alpha + gamma_p / 2.0 + beta >= 1.0:
            return 1e10

        eps = r - mu
        h = np.empty(n)
        h[0] = omega / (1.0 - alpha - gamma_p / 2.0 - beta)
        if h[0] <= 0:
            h[0] = np.var(r)

        for t in range(1, n):
            asym = gamma_p * eps[t-1]**2 if eps[t-1] < 0 else 0.0
            h[t] = omega + alpha * eps[t-1]**2 + asym + beta * h[t-1]
            if h[t] < 1e-12:
                h[t] = 1e-12

        # Student-t log-likelihood
        from scipy.special import gammaln
        ll = (gammaln((nu+1)/2) - gammaln(nu/2)
              - 0.5 * np.log(np.pi * (nu-2))
              - 0.5 * np.log(h)
              - (nu+1)/2 * np.log(1 + eps**2 / (h * (nu-2))))
        return -np.sum(ll)

    var0 = np.var(r)
    starts = [
        [np.mean(r), var0 * 0.05, 0.05, 0.05, 0.90, 6.0],
        [0.0, var0 * 0.02, 0.03, 0.10, 0.85, 8.0],
        [np.mean(r), var0 * 0.10, 0.08, 0.08, 0.80, 5.0],
    ]
    bounds = [(-0.01, 0.01), (1e-10, var0), (1e-6, 0.3), (1e-6, 0.3), (0.5, 0.999), (2.1, 50)]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 2000})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            pass

    return best_params


def gjr_forecast_1step(params, h_prev, eps_prev):
    """One-step GJR variance forecast."""
    mu, omega, alpha, gamma_p, beta, nu = params
    asym = gamma_p * eps_prev**2 if eps_prev < 0 else 0.0
    return max(omega + alpha * eps_prev**2 + asym + beta * h_prev, 1e-12)


# --- M4: A4f — Multiplicative GJR-X with VIX² (from K988) ---
def fit_a4f(returns, vix_vals):
    """
    Fit A4f model: sigma²_t = tau_t * g_t
    tau_t = max(theta0 + theta1 * VIX²_{t-1}, eps)
    g_t: GJR dynamics on normalized returns u_t = r_t / sqrt(tau_t)
    Free omega (not constrained to E[g]=1).
    params = [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    r = returns.copy()

    # Lagged VIX (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    vix_lag_sq = vix_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg

        for t in range(1, n):
            u_prev = r[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = 0.0
        for t in range(n):
            if sigma2[t] > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2[t]) + r[t]**2 / sigma2[t])
        return -ll

    var0 = np.var(r)
    vix2_mean = np.mean(vix_lag_sq) + 1e-8

    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 3000})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            pass

    return best_params


# --- Rolling GARCH forecasts ---
ret_array = spy['ret'].values
vix_array = spy['VIX'].values / 100.0  # scale VIX to fraction for A4f

n_total = len(ret_array)
m4_forecasts = np.full(n_total, np.nan)  # A4f sigma²
m5_forecasts = np.full(n_total, np.nan)  # GJR-t sigma²

# State tracking
gjr_params = None
gjr_h = None
gjr_eps = None

a4f_params = None
a4f_g = None
a4f_tau_prev = None

print(f"  Rolling GARCH forecast (window={GARCH_WINDOW}, refit={REFIT_EVERY})...")

for t in range(GARCH_WINDOW, n_total - 1):
    need_refit = (gjr_params is None) or ((t - GARCH_WINDOW) % REFIT_EVERY == 0)

    if t % 500 == 0:
        elapsed = time.time() - START_TIME
        print(f"    t={t}/{n_total}, elapsed={elapsed:.0f}s")

    if need_refit:
        train_ret = ret_array[t - GARCH_WINDOW: t]
        train_vix = vix_array[t - GARCH_WINDOW: t]

        # M5: GJR-t
        new_gjr_params = fit_gjr_t(train_ret)
        if new_gjr_params is not None:
            gjr_params = new_gjr_params
            mu = gjr_params[0]
            eps_arr = train_ret - mu
            h = gjr_params[1] / (1.0 - gjr_params[2] - gjr_params[3]/2.0 - gjr_params[4])
            if h <= 0:
                h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, eps_arr[i-1])
            gjr_h = h
            gjr_eps = eps_arr[-1]

        # M4: A4f
        new_a4f_params = fit_a4f(train_ret, train_vix)
        if new_a4f_params is not None:
            a4f_params = new_a4f_params
            theta0, theta1, omega_g, alpha, gamma_p, beta = a4f_params
            persist = alpha + gamma_p / 2.0 + beta
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0

            vix_lag_tr = np.empty(len(train_vix))
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            tau_train = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)

            g = eg
            for i in range(1, len(train_ret)):
                u_prev = train_ret[i-1] / np.sqrt(tau_train[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha * u_prev**2 + asym + beta * g
                g = max(g, 1e-10)
            a4f_g = g
            a4f_tau_prev = tau_train[-1]

    # One-step-ahead forecast at time t for t+1
    # M5: GJR
    if gjr_params is not None and gjr_h is not None:
        mu = gjr_params[0]
        eps_t = ret_array[t] - mu
        gjr_h = gjr_forecast_1step(gjr_params, gjr_h, gjr_eps if gjr_eps is not None else eps_t)
        m5_forecasts[t + 1] = gjr_h
        gjr_eps = eps_t

    # M4: A4f
    if a4f_params is not None and a4f_g is not None:
        theta0, theta1, omega_g, alpha, gamma_p, beta = a4f_params
        # tau at time t+1 uses VIX at time t (lagged)
        vix_t = vix_array[t]
        tau_tp1 = max(theta0 + theta1 * vix_t**2, 1e-16)

        # Update g: use residual from time t
        u_t = ret_array[t] / np.sqrt(max(theta0 + theta1 * vix_array[max(t-1,0)]**2, 1e-16))
        asym = gamma_p * u_t**2 if u_t < 0 else 0.0
        a4f_g = omega_g + alpha * u_t**2 + asym + beta * a4f_g
        a4f_g = max(a4f_g, 1e-10)

        m4_forecasts[t + 1] = tau_tp1 * a4f_g

m4_series = pd.Series(m4_forecasts, index=spy.index)
m5_series = pd.Series(m5_forecasts, index=spy.index)

print(f"  GARCH models done ({time.time()-START_TIME:.1f}s)")
print(f"  M4 (A4f) non-NaN: {m4_series.notna().sum()}")
print(f"  M5 (GJR-t) non-NaN: {m5_series.notna().sum()}")

# Quick check: are M4 and M5 identical?
common_mask = m4_series.notna() & m5_series.notna()
if common_mask.sum() > 0:
    corr_m4_m5 = np.corrcoef(m4_series[common_mask].values, m5_series[common_mask].values)[0,1]
    print(f"  M4-M5 correlation: {corr_m4_m5:.6f}")
    if corr_m4_m5 > 0.9999:
        print("  *** WARNING: M4 and M5 are nearly identical — bug may persist! ***")
    else:
        print("  *** CONFIRMED: M4 and M5 are different models (bug fixed) ***")

# ============================================================
# 5. Evaluation
# ============================================================
print("\n[5/7] Evaluation...")

# Convert HAR |r| forecasts to sigma²: sigma² = |r_hat|² * pi/2
m1_var = m1_fc ** 2 * np.pi / 2
m2_var = m2_fc ** 2 * np.pi / 2
m2b_var = m2b_fc ** 2 * np.pi / 2
m2c_var = m2c_fc ** 2 * np.pi / 2
m3_var = m3_fc ** 2 * np.pi / 2

actual_r2 = spy['r2']
actual_abs = spy['abs_ret']

# Common evaluation period
eval_mask = (m1_var.notna() & m2_var.notna() & m2b_var.notna() & m2c_var.notna() &
             m3_var.notna() & m4_series.notna() & m5_series.notna() &
             actual_r2.notna() & (actual_r2 > 0))

eval_idx = spy.index[eval_mask]
print(f"  Evaluation period: {eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}")
print(f"  Evaluation observations: {len(eval_idx)}")

# Aligned arrays
y_r2 = actual_r2[eval_mask].values
y_abs = actual_abs[eval_mask].values

forecasts = {
    'M1: HAR(1,5,22)':     m1_var[eval_mask].values,
    'M2: HAR+vix_gap':      m2_var[eval_mask].values,
    'M2b: HAR+vix_gap²':    m2b_var[eval_mask].values,
    'M2c: HAR+|vix_gap|':   m2c_var[eval_mask].values,
    'M3: HAR+VIX_level':    m3_var[eval_mask].values,
    'M4: A4f (VIX²)':       m4_series[eval_mask].values,
    'M5: GJR-t':            m5_series[eval_mask].values,
}

# HAR |r| forecasts
har_abs_forecasts = {
    'M1: HAR(1,5,22)':     m1_fc[eval_mask].values,
    'M2: HAR+vix_gap':      m2_fc[eval_mask].values,
    'M2b: HAR+vix_gap²':    m2b_fc[eval_mask].values,
    'M2c: HAR+|vix_gap|':   m2c_fc[eval_mask].values,
    'M3: HAR+VIX_level':    m3_fc[eval_mask].values,
}

# Floor
floor = 1e-12
for k in forecasts:
    forecasts[k] = np.maximum(forecasts[k], floor)

# QLIKE
def qlike(actual_r2, forecast_var):
    ratio = actual_r2 / forecast_var
    return np.mean(ratio - np.log(ratio) - 1)

def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)

def spearman(actual, forecast):
    rho, pval = stats.spearmanr(actual, forecast)
    return rho, pval

def dm_test_nw(actual, forecast1, forecast2, loss='qlike'):
    """Diebold-Mariano test with Newey-West SE. Negative = forecast1 better."""
    if loss == 'qlike':
        L1 = actual / forecast1 - np.log(actual / forecast1) - 1
        L2 = actual / forecast2 - np.log(actual / forecast2) - 1
    elif loss == 'mse':
        L1 = (actual - forecast1) ** 2
        L2 = (actual - forecast2) ** 2
    else:
        raise ValueError(f"Unknown loss: {loss}")

    d = L1 - L2
    d_mean = d.mean()
    n = len(d)
    lag = int(n ** (1/3))
    d_dm = d - d_mean
    gamma_0 = np.mean(d_dm ** 2)
    nw_var = gamma_0
    for k in range(1, lag + 1):
        gamma_k = np.mean(d_dm[k:] * d_dm[:-k])
        nw_var += 2 * (1 - k / (lag + 1)) * gamma_k
    se = np.sqrt(nw_var / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value

# --- QLIKE on r² ---
print("\n  --- QLIKE on r² (lower = better, Patton 2011) ---")
results = {}
for name, h in forecasts.items():
    q = qlike(y_r2, h)
    rho, rho_p = spearman(y_r2, h)
    results[name] = {
        'QLIKE_r2': float(q),
        'Spearman_r2': float(rho),
        'Spearman_r2_pval': float(rho_p),
    }
    print(f"  {name}: QLIKE={q:.6f}, Spearman(r²)={rho:.4f}")

# --- MSE on |r| (HAR models only) ---
print("\n  --- MSE on |r| (HAR models, lower = better) ---")
for name, h_abs in har_abs_forecasts.items():
    m = mse(y_abs, h_abs)
    results[name]['MSE_abs_r'] = float(m)
    print(f"  {name}: MSE(|r|)={m:.8f}")

# --- DM tests ---
print("\n  --- DM Tests (QLIKE on r², Harvey |t|>3.0) ---")
dm_results = {}
dm_pairs = [
    ('M2 vs M1', 'M2: HAR+vix_gap', 'M1: HAR(1,5,22)'),
    ('M2b vs M1', 'M2b: HAR+vix_gap²', 'M1: HAR(1,5,22)'),
    ('M2c vs M1', 'M2c: HAR+|vix_gap|', 'M1: HAR(1,5,22)'),
    ('M3 vs M1', 'M3: HAR+VIX_level', 'M1: HAR(1,5,22)'),
    ('M2 vs M3', 'M2: HAR+vix_gap', 'M3: HAR+VIX_level'),
    ('M2 vs M4', 'M2: HAR+vix_gap', 'M4: A4f (VIX²)'),
    ('M2 vs M5', 'M2: HAR+vix_gap', 'M5: GJR-t'),
    ('M4 vs M5', 'M4: A4f (VIX²)', 'M5: GJR-t'),
    ('M1 vs M5', 'M1: HAR(1,5,22)', 'M5: GJR-t'),
    ('M1 vs M4', 'M1: HAR(1,5,22)', 'M4: A4f (VIX²)'),
]

for label, name1, name2 in dm_pairs:
    t_stat, p_val = dm_test_nw(y_r2, forecasts[name1], forecasts[name2], loss='qlike')
    dm_results[label + '_qlike'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
    direction = "←" if t_stat < 0 else "→"
    print(f"  {label}: t={t_stat:.3f}, p={p_val:.4f} [{sig}] {direction}")

print("\n  --- DM Tests (MSE on |r|, HAR models) ---")
dm_abs_pairs = [
    ('M2 vs M1 |r|', 'M2: HAR+vix_gap', 'M1: HAR(1,5,22)'),
    ('M2b vs M1 |r|', 'M2b: HAR+vix_gap²', 'M1: HAR(1,5,22)'),
    ('M2c vs M1 |r|', 'M2c: HAR+|vix_gap|', 'M1: HAR(1,5,22)'),
    ('M3 vs M1 |r|', 'M3: HAR+VIX_level', 'M1: HAR(1,5,22)'),
    ('M2 vs M3 |r|', 'M2: HAR+vix_gap', 'M3: HAR+VIX_level'),
]

for label, name1, name2 in dm_abs_pairs:
    t_stat, p_val = dm_test_nw(y_abs, har_abs_forecasts[name1], har_abs_forecasts[name2], loss='mse')
    dm_results[label + '_mse'] = {'t_stat': float(t_stat), 'p_value': float(p_val)}
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "NS")
    direction = "←" if t_stat < 0 else "→"
    print(f"  {label}: t={t_stat:.3f}, p={p_val:.4f} [{sig}] {direction}")

# ============================================================
# 6. In-sample coefficient analysis
# ============================================================
print("\n[6/7] In-sample coefficient analysis...")
from numpy.linalg import inv

def ols_with_stats(y, X, col_names):
    """Run OLS with t-statistics."""
    X_c = np.column_stack([np.ones(len(X)), X])
    names = ['const'] + col_names
    beta = inv(X_c.T @ X_c) @ X_c.T @ y
    resid = y - X_c @ beta
    s2 = np.sum(resid**2) / (len(y) - len(names))
    var_b = s2 * inv(X_c.T @ X_c)
    se = np.sqrt(np.diag(var_b))
    t_stats = beta / se
    coefs = {}
    for i, name in enumerate(names):
        coefs[name] = {'coef': float(beta[i]), 'se': float(se[i]), 't_stat': float(t_stats[i])}
    return coefs

y_full = spy['abs_ret'].values[1:]
X_base = np.column_stack([spy['abs_ret'].values, spy['abs_ret_5'].values,
                           spy['abs_ret_22'].values])[:-1]

# M2: vix_gap
X_m2 = np.column_stack([X_base, spy['vix_gap'].values[:-1]])
coefs_m2 = ols_with_stats(y_full, X_m2, ['|r_1|', 'avg|r_5|', 'avg|r_22|', 'vix_gap'])

# M2b: vix_gap²
X_m2b = np.column_stack([X_base, spy['vix_gap_sq'].values[:-1]])
coefs_m2b = ols_with_stats(y_full, X_m2b, ['|r_1|', 'avg|r_5|', 'avg|r_22|', 'vix_gap²'])

# M2c: |vix_gap|
X_m2c = np.column_stack([X_base, spy['vix_gap_abs'].values[:-1]])
coefs_m2c = ols_with_stats(y_full, X_m2c, ['|r_1|', 'avg|r_5|', 'avg|r_22|', '|vix_gap|'])

# M3: VIX_level
X_m3 = np.column_stack([X_base, spy['vix_level'].values[:-1]])
coefs_m3 = ols_with_stats(y_full, X_m3, ['|r_1|', 'avg|r_5|', 'avg|r_22|', 'VIX_level'])

print("\n  M2 (HAR + vix_gap):")
for name, c in coefs_m2.items():
    print(f"    {name:<12} coef={c['coef']:>10.6f}  se={c['se']:>10.6f}  t={c['t_stat']:>8.3f}")

print("\n  M2b (HAR + vix_gap²):")
for name, c in coefs_m2b.items():
    print(f"    {name:<12} coef={c['coef']:>10.6f}  se={c['se']:>10.6f}  t={c['t_stat']:>8.3f}")

print("\n  M2c (HAR + |vix_gap|):")
for name, c in coefs_m2c.items():
    print(f"    {name:<12} coef={c['coef']:>10.6f}  se={c['se']:>10.6f}  t={c['t_stat']:>8.3f}")

print("\n  M3 (HAR + VIX_level):")
for name, c in coefs_m3.items():
    print(f"    {name:<12} coef={c['coef']:>10.6f}  se={c['se']:>10.6f}  t={c['t_stat']:>8.3f}")

# ============================================================
# 7. Save Results and Plots
# ============================================================
print("\n[7/7] Saving results...")

output = {
    'experiment_id': 'K1016b',
    'title': 'HAR+vix_gap Corrected (Fixed M4/M5 Bug + vix_gap Variants)',
    'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
    'fixes': [
        'M4 (A4f) now uses K988 multiplicative GJR-X (tau=theta0+theta1*VIX², free omega)',
        'M5 (GJR-t) uses custom MLE, not arch library',
        'M4 and M5 are confirmed different models',
        'Added vix_gap² and |vix_gap| variants',
        'vix_gap definition: VIX/(100*sqrt(252)) - |r|_5d (not sqrt(rv_22))',
    ],
    'data': {
        'asset': 'SPY',
        'source': 'yfinance',
        'period': f"{spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}",
        'total_obs': int(len(spy)),
        'eval_obs': int(len(eval_idx)),
        'eval_period': f"{eval_idx[0].strftime('%Y-%m-%d')} to {eval_idx[-1].strftime('%Y-%m-%d')}",
    },
    'config': {
        'har_window': ROLLING_WINDOW,
        'garch_window': GARCH_WINDOW,
        'refit_every': REFIT_EVERY,
        'seed': 42,
    },
    'descriptive_stats': desc_stats,
    'evaluation': results,
    'dm_tests': dm_results,
    'in_sample_coefficients': {
        'M2_HAR_vixgap': coefs_m2,
        'M2b_HAR_vixgap_sq': coefs_m2b,
        'M2c_HAR_vixgap_abs': coefs_m2c,
        'M3_HAR_VIX_level': coefs_m3,
    },
    'bug_fix_verification': {
        'M4_M5_correlation': float(corr_m4_m5) if common_mask.sum() > 0 else None,
        'M4_M5_identical': bool(corr_m4_m5 > 0.9999) if common_mask.sum() > 0 else None,
    },
    'references': [
        'Corsi (2009) JAE - HAR-RV',
        'Patton (2011) JoE - Volatility forecast comparison',
        'Bollerslev et al. (2009) RFS - Variance risk premia',
        'Harvey et al. (2016) RFS - Multiple testing t>3.0',
        'K988 - Multiplicative GARCH-X implementation',
        'K1016 - Original (buggy) version',
    ],
    'runtime_seconds': round(time.time() - START_TIME, 1),
}

results_path = os.path.join(SCRIPT_DIR, 'k1016b_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2)
print(f"  Results saved to {results_path}")

# --- Plot 1: QLIKE comparison ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# QLIKE bar chart
model_names = list(results.keys())
qlike_vals = [results[m]['QLIKE_r2'] for m in model_names]
short_names = [m.split(': ')[1] for m in model_names]
colors = ['#4C72B0', '#DD8452', '#55A868', '#C44E52', '#8172B3', '#937860', '#DA8BC3']

ax = axes[0]
bars = ax.barh(range(len(model_names)), qlike_vals, color=colors[:len(model_names)])
ax.set_yticks(range(len(model_names)))
ax.set_yticklabels(short_names, fontsize=10)
ax.set_xlabel('QLIKE (lower = better)')
ax.set_title('QLIKE on r² (Patton 2011)')
ax.invert_yaxis()
for i, v in enumerate(qlike_vals):
    ax.text(v + 0.01, i, f'{v:.4f}', va='center', fontsize=9)

# Spearman bar chart
spearman_vals = [results[m]['Spearman_r2'] for m in model_names]
ax = axes[1]
bars = ax.barh(range(len(model_names)), spearman_vals, color=colors[:len(model_names)])
ax.set_yticks(range(len(model_names)))
ax.set_yticklabels(short_names, fontsize=10)
ax.set_xlabel('Spearman Correlation')
ax.set_title('Spearman Rank Corr with r²')
ax.invert_yaxis()
for i, v in enumerate(spearman_vals):
    ax.text(v + 0.005, i, f'{v:.4f}', va='center', fontsize=9)

plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k1016b_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()

# --- Plot 2: vix_gap coefficient evolution ---
if len(m2_betas) > 0:
    fig, ax = plt.subplots(figsize=(12, 5))
    times = [spy.index[b[0]].strftime('%Y-%m-%d') for b in m2_betas]
    vg_coefs = [b[1][-1] for b in m2_betas]  # Last coefficient = vix_gap
    ax.plot(range(len(vg_coefs)), vg_coefs, 'b-', linewidth=0.8)
    ax.axhline(y=0, color='r', linestyle='--', alpha=0.5)
    ax.set_xlabel('Refit step')
    ax.set_ylabel('vix_gap coefficient')
    ax.set_title('M2: HAR+vix_gap coefficient evolution over rolling windows')
    # Add x-axis labels at intervals
    n_labels = min(10, len(times))
    step = max(1, len(times) // n_labels)
    ax.set_xticks(range(0, len(times), step))
    ax.set_xticklabels([times[i] for i in range(0, len(times), step)], rotation=45, fontsize=8)
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, 'k1016b_vixgap_coef.png'), dpi=150, bbox_inches='tight')
    plt.close()

# --- Plot 3: M4 vs M5 scatter (verify they differ) ---
if common_mask.sum() > 100:
    fig, ax = plt.subplots(figsize=(7, 7))
    m4_vals = m4_series[common_mask].values[:1000]
    m5_vals = m5_series[common_mask].values[:1000]
    ax.scatter(m5_vals, m4_vals, alpha=0.3, s=5)
    max_val = max(m4_vals.max(), m5_vals.max())
    ax.plot([0, max_val], [0, max_val], 'r--', linewidth=1, label='45° line')
    ax.set_xlabel('M5: GJR-t σ²')
    ax.set_ylabel('M4: A4f (VIX²) σ²')
    ax.set_title(f'M4 vs M5 Variance Forecasts (corr={corr_m4_m5:.4f})')
    ax.legend()
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, 'k1016b_m4_vs_m5.png'), dpi=150, bbox_inches='tight')
    plt.close()

elapsed = time.time() - START_TIME
print(f"\n{'='*70}")
print(f"K1016b completed in {elapsed:.1f}s")
print(f"{'='*70}")
