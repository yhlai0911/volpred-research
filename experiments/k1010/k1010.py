#!/usr/bin/env python3
"""
K1010: Probabilistic Volatility Quantile Forecasting
=====================================================
[提出: Claude, 執行: Claude]

Motivation:
  Traditional volatility forecasts produce point estimates (sigma^2_t), but risk
  management needs to know the uncertainty around predictions. This experiment
  builds conditional quantiles of forecast errors using quantile regression (QR),
  then constructs prediction intervals (PI) for volatility.

  K988 A4f is the QLIKE champion. K1000 tested parametric VaR/ES under Normal
  and Student-t assumptions. This experiment asks:
  1. Are A4f's prediction interval coverage rates properly calibrated?
  2. Does QR correction improve calibration vs parametric Normal/t PIs?
  3. Can QR-based conditional quantiles improve VaR computation?

Method:
  Step 1: Generate OOS forecasts from GJR and A4f models (rolling, w=2000, refit/63d)
  Step 2: Compute forecast errors e_t = r^2_t - sigma^2_hat_t
  Step 3: Fit quantile regression on errors: Q_tau(e_t | X_t)
          X_t = [1, sigma^2_hat, VIX_{t-1}/100, |e_{t-1}|]
  Step 4: Construct prediction intervals: PI_tau = sigma^2_hat + Q_tau(e_t | X_t)
  Step 5: Evaluate calibration, sharpness, Winkler score
  Step 6: VaR backtesting comparison

  Six PI methods:
    1. GJR + Normal PI
    2. GJR + QR PI
    3. A4f + Normal PI
    4. A4f + QR PI
    5. A4f + Student-t PI (from K1000)
    6. Direct QR on r^2

References:
  - Koenker & Bassett (1978). Regression Quantiles. Econometrica 46:33-50.
  - Christoffersen (1998). Evaluating Interval Forecasts. Int Econ Rev 39:841-862.
  - Gneiting & Raftery (2007). Strictly Proper Scoring Rules, Prediction, and
    Estimation. JASA 102:359-378.
  - Winkler (1972). A Decision-Theoretic Approach to Interval Estimation.
    JASA 67:187-191.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Harvey et al. (2016). t > 3.0 threshold.

Data: SPY 2005-2026 (yfinance), VIX from yfinance. OOS: 2019-01-01 to latest.
      Window=2000, refit every 63 days.
Evaluation: Calibration (coverage rate), Sharpness (PI width), Winkler score,
            VaR backtesting (Kupiec, Christoffersen CC, DQ, Basel traffic light),
            ES backtesting (Acerbi-Szekely Z1/Z2).
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
from scipy.stats import t as t_dist, chi2, norm
from numba import njit
import statsmodels.api as sm

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1010"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1010_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
QR_WINDOW = 500  # Rolling window for QR training on forecast errors
TAUS = [0.025, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.975]

print("=" * 70)
print(f"{EXPERIMENT_ID}: Probabilistic Volatility Quantile Forecasting")
print("  QR correction of GJR and A4f prediction intervals")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
vix2 = (vix / 100.0) ** 2  # VIX scaled to variance units

n_total = len(df)
oos_mask = np.array(df.index >= OOS_START)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
oos_r2 = r2[oos_mask]
print(f"  OOS mean return: {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std (ann): {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
print(f"  OOS mean r2: {np.mean(oos_r2):.6f}")
print(f"  VIX autocorr(1): {np.corrcoef(vix[1:], vix[:-1])[0,1]:.4f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS (GJR + A4f)
# ============================================================
print("\n[3] Model implementations...")


@njit(cache=True)
def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2v = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2v + gamma * r2v * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


@njit(cache=True)
def gjr_nll(omega, alpha, gamma, beta, returns):
    h = gjr_h(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit(cache=True)
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2_arr):
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2_arr[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2_arr[t-1]
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


@njit(cache=True)
def a4f_nll(theta0, theta1, omega, alpha, gamma, beta, returns, vix2_arr):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2_arr)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit(cache=True)
def t_logpdf_sum(returns, h, df_val):
    """Sum of Student-t logpdf with scale = sigma * sqrt((df-2)/df)."""
    import math
    T = len(returns)
    scale_factor = np.sqrt((df_val - 2.0) / df_val)
    c = math.lgamma((df_val + 1.0) / 2.0) - math.lgamma(df_val / 2.0) - 0.5 * np.log(np.pi * df_val)
    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        s = sigma * scale_factor
        z = returns[t] / s
        ll += c - np.log(s) - (df_val + 1.0) / 2.0 * np.log(1.0 + z * z / df_val)
    return ll


# --- Fitting functions ---
def fit_gjr(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            return gjr_nll(p[0], p[1], p[2], p[3], returns)
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for x0 in [[var0*0.05, 0.05, 0.05, 0.90], [var0*0.02, 0.03, 0.08, 0.88]]:
        try:
            res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h = gjr_h(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3], returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success}


def fit_a4f(returns, vix2_arr):
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2_arr)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5],
                               returns, vix2_arr)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g, 'converged': best_res.success}


def fit_a4f_t(returns, vix2_arr):
    """Joint A4f + Student-t MLE."""
    res_n = fit_a4f(returns, vix2_arr)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2_arr)
            ll = t_logpdf_sum(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(res_n['params']) + [df_init]
        try:
            res = optimize.minimize(obj, p0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    if best_res is None:
        # Fallback: use Normal A4f with default df=8
        p_fallback = np.append(res_n['params'], 8.0)
        return {'params': p_fallback, 'h': res_n['h'], 'tau': res_n['tau'],
                'g': res_n['g'], 'converged': False, 'df': 8.0}
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5],
                               returns, vix2_arr)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'df': best_res.x[6]}


# ============================================================
# SECTION 4: OOS FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting (rolling window)...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)

# Storage
gjr_sigma2 = np.full(n_oos_actual, np.nan)
a4f_sigma2 = np.full(n_oos_actual, np.nan)
a4f_t_sigma2 = np.full(n_oos_actual, np.nan)
a4f_t_df = np.full(n_oos_actual, np.nan)

# Track state for recursive forecasting
gjr_fit = None
a4f_fit = None
a4f_t_fit = None
gjr_h_prev = np.nan
a4f_g_prev = np.nan
a4f_t_g_prev = np.nan
last_refit = -REFIT_EVERY

for i, t in enumerate(oos_indices):
    if i % 200 == 0:
        print(f"  OOS day {i}/{n_oos_actual}...")

    # Refit?
    if t - last_refit >= REFIT_EVERY or gjr_fit is None:
        s = max(0, t - WINDOW)
        tr = ret[s:t]
        tv = vix2[s:t]

        gjr_fit = fit_gjr(tr)
        a4f_fit = fit_a4f(tr, tv)
        a4f_t_fit = fit_a4f_t(tr, tv)

        last_refit = t
        gjr_h_prev = gjr_fit['h'][-1]
        a4f_g_prev = a4f_fit['g'][-1]
        a4f_t_g_prev = a4f_t_fit['g'][-1]

    # GJR 1-step forecast
    p = gjr_fit['params']
    r_prev = ret[t-1]
    r2p = r_prev ** 2
    ind = 1.0 if r_prev < 0 else 0.0
    h_t = p[0] + p[1] * r2p + p[2] * r2p * ind + p[3] * gjr_h_prev
    h_t = max(h_t, 1e-16)
    gjr_sigma2[i] = h_t
    gjr_h_prev = h_t

    # A4f 1-step forecast (Normal)
    p = a4f_fit['params']
    tau_t = max(p[0] + p[1] * vix2[t-1], 1e-16)
    u_prev = ret[t-1] / np.sqrt(tau_t)
    u2 = u_prev ** 2
    ind = 1.0 if ret[t-1] < 0 else 0.0
    g_t = p[2] + p[3] * u2 + p[4] * u2 * ind + p[5] * a4f_g_prev
    g_t = max(g_t, 1e-16)
    a4f_sigma2[i] = tau_t * g_t
    a4f_g_prev = g_t

    # A4f-t 1-step forecast
    p = a4f_t_fit['params']
    tau_t = max(p[0] + p[1] * vix2[t-1], 1e-16)
    u_prev = ret[t-1] / np.sqrt(tau_t)
    u2 = u_prev ** 2
    ind = 1.0 if ret[t-1] < 0 else 0.0
    g_t = p[2] + p[3] * u2 + p[4] * u2 * ind + p[5] * a4f_t_g_prev
    g_t = max(g_t, 1e-16)
    a4f_t_sigma2[i] = tau_t * g_t
    a4f_t_df[i] = p[6]
    a4f_t_g_prev = g_t

print(f"  Done. Valid GJR: {np.sum(~np.isnan(gjr_sigma2))}, A4f: {np.sum(~np.isnan(a4f_sigma2))}")

# OOS target
oos_r2_vals = r2[oos_indices]
oos_ret_vals = ret[oos_indices]
oos_vix_vals = vix[oos_indices]


# ============================================================
# SECTION 5: QLIKE EVALUATION (Point forecast quality)
# ============================================================
print("\n[5] Point forecast evaluation (QLIKE on r^2)...")

def qlike_loss(r2_arr, h_arr):
    mask = ~np.isnan(h_arr) & ~np.isnan(r2_arr) & (h_arr > 0)
    return np.mean(r2_arr[mask] / h_arr[mask] + np.log(h_arr[mask]))

def qlike_loss_array(r2_arr, h_arr):
    mask = ~np.isnan(h_arr) & ~np.isnan(r2_arr) & (h_arr > 0)
    losses = np.full(len(r2_arr), np.nan)
    losses[mask] = r2_arr[mask] / h_arr[mask] + np.log(h_arr[mask])
    return losses

qlike_gjr = qlike_loss(oos_r2_vals, gjr_sigma2)
qlike_a4f = qlike_loss(oos_r2_vals, a4f_sigma2)
qlike_a4f_t = qlike_loss(oos_r2_vals, a4f_t_sigma2)

print(f"  QLIKE GJR:   {qlike_gjr:.6f}")
print(f"  QLIKE A4f:   {qlike_a4f:.6f}")
print(f"  QLIKE A4f-t: {qlike_a4f_t:.6f}")

# DM tests
loss_gjr = qlike_loss_array(oos_r2_vals, gjr_sigma2)
loss_a4f = qlike_loss_array(oos_r2_vals, a4f_sigma2)

def dm_test_custom(loss1, loss2):
    d = loss1 - loss2
    mask = ~np.isnan(d)
    d = d[mask]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)
    max_lag = int(n ** (1/3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return t_stat, p_val

dm_gjr_a4f_t, dm_gjr_a4f_p = dm_test_custom(loss_gjr, loss_a4f)
print(f"  DM test GJR vs A4f: t={dm_gjr_a4f_t:.3f}, p={dm_gjr_a4f_p:.4f}")


# ============================================================
# SECTION 6: QUANTILE REGRESSION ON FORECAST ERRORS
# ============================================================
print("\n[6] Quantile regression on forecast errors...")

def fit_quantile_regression(errors, features, tau_val, max_iter=500):
    """Fit quantile regression Q_tau(e | X) = X @ beta."""
    try:
        model = sm.QuantReg(errors, features)
        result = model.fit(q=tau_val, max_iter=max_iter)
        return result.params
    except:
        return None


def build_qr_features(sigma2_hat, vix_lag, abs_error_lag):
    """Build feature matrix for QR: [1, sigma2_hat, vix_lag/100, |e_{lag}|]."""
    n = len(sigma2_hat)
    X = np.column_stack([
        np.ones(n),
        sigma2_hat,
        vix_lag / 100.0,
        abs_error_lag
    ])
    return X


# Compute forecast errors for both models
gjr_errors = oos_r2_vals - gjr_sigma2
a4f_errors = oos_r2_vals - a4f_sigma2

# Lagged features (using t-1 info only, no lookahead)
vix_lag_oos = np.empty(n_oos_actual)
vix_lag_oos[0] = vix[oos_indices[0] - 1]
vix_lag_oos[1:] = oos_vix_vals[:-1]

# Lagged absolute errors
gjr_abs_error_lag = np.empty(n_oos_actual)
gjr_abs_error_lag[0] = 0.0
gjr_abs_error_lag[1:] = np.abs(gjr_errors[:-1])

a4f_abs_error_lag = np.empty(n_oos_actual)
a4f_abs_error_lag[0] = 0.0
a4f_abs_error_lag[1:] = np.abs(a4f_errors[:-1])

# Rolling QR: for each OOS day t, fit QR on previous QR_WINDOW days' errors
# Then predict quantiles for day t
print(f"  Rolling QR with window={QR_WINDOW}, taus={TAUS}")

gjr_qr_quantiles = {tau: np.full(n_oos_actual, np.nan) for tau in TAUS}
a4f_qr_quantiles = {tau: np.full(n_oos_actual, np.nan) for tau in TAUS}
direct_qr_quantiles = {tau: np.full(n_oos_actual, np.nan) for tau in TAUS}

# Start QR predictions after QR_WINDOW burn-in
qr_start = QR_WINDOW

for i in range(qr_start, n_oos_actual):
    if i % 300 == 0:
        print(f"    QR day {i}/{n_oos_actual}...")

    # Training window for QR
    train_start = max(0, i - QR_WINDOW)
    train_end = i

    # --- GJR QR ---
    train_errors = gjr_errors[train_start:train_end]
    train_X = build_qr_features(
        gjr_sigma2[train_start:train_end],
        vix_lag_oos[train_start:train_end],
        gjr_abs_error_lag[train_start:train_end]
    )
    # Current features for prediction
    pred_X = build_qr_features(
        gjr_sigma2[i:i+1],
        vix_lag_oos[i:i+1],
        gjr_abs_error_lag[i:i+1]
    )

    for tau in TAUS:
        beta = fit_quantile_regression(train_errors, train_X, tau)
        if beta is not None:
            # PI lower/upper for r^2: sigma2_hat + Q_tau(error)
            qr_pred = pred_X @ beta
            gjr_qr_quantiles[tau][i] = gjr_sigma2[i] + qr_pred[0]

    # --- A4f QR ---
    train_errors_a4f = a4f_errors[train_start:train_end]
    train_X_a4f = build_qr_features(
        a4f_sigma2[train_start:train_end],
        vix_lag_oos[train_start:train_end],
        a4f_abs_error_lag[train_start:train_end]
    )
    pred_X_a4f = build_qr_features(
        a4f_sigma2[i:i+1],
        vix_lag_oos[i:i+1],
        a4f_abs_error_lag[i:i+1]
    )

    for tau in TAUS:
        beta = fit_quantile_regression(train_errors_a4f, train_X_a4f, tau)
        if beta is not None:
            qr_pred = pred_X_a4f @ beta
            a4f_qr_quantiles[tau][i] = a4f_sigma2[i] + qr_pred[0]

    # --- Direct QR on r^2 ---
    train_r2 = oos_r2_vals[train_start:train_end]
    # Features: [1, gjr_sigma2, a4f_sigma2, vix_lag/100]
    train_X_direct = np.column_stack([
        np.ones(train_end - train_start),
        gjr_sigma2[train_start:train_end],
        a4f_sigma2[train_start:train_end],
        vix_lag_oos[train_start:train_end] / 100.0
    ])
    pred_X_direct = np.column_stack([
        np.ones(1),
        gjr_sigma2[i:i+1],
        a4f_sigma2[i:i+1],
        vix_lag_oos[i:i+1] / 100.0
    ])

    for tau in TAUS:
        beta = fit_quantile_regression(train_r2, train_X_direct, tau)
        if beta is not None:
            direct_qr_quantiles[tau][i] = (pred_X_direct @ beta)[0]

print("  QR fitting complete.")


# ============================================================
# SECTION 7: PARAMETRIC PREDICTION INTERVALS
# ============================================================
print("\n[7] Parametric prediction intervals...")

# Under Normal: r_t | F_{t-1} ~ N(0, sigma2_t)
# => r^2_t / sigma2_t ~ chi2(1) => r^2_t ~ sigma2_t * chi2(1)
# Q_tau(r^2) = sigma2_t * chi2_inv(tau, df=1)
# Under Student-t(df): r_t ~ sigma_t * sqrt((df-2)/df) * t(df)
# => r^2_t ... more complex, use simulation-based quantiles

# For return-level VaR (used in VaR backtesting):
# Normal VaR: sigma_t * z_alpha
# Student-t VaR: sigma_t * sqrt((df-2)/df) * t_alpha(df)

# For r^2 quantiles (calibration test):
# Under N(0, sigma2): r^2 ~ sigma2 * chi2(1)
gjr_normal_quantiles = {}
a4f_normal_quantiles = {}
a4f_t_quantiles = {}

for tau in TAUS:
    chi2_q = chi2.ppf(tau, df=1)
    gjr_normal_quantiles[tau] = gjr_sigma2 * chi2_q
    a4f_normal_quantiles[tau] = a4f_sigma2 * chi2_q

    # Student-t: r^2 / sigma^2 ~ (df-2)/df * F(1, df)
    # Actually: z ~ t(df), so z^2 ~ F(1, df), and r = sigma*sqrt((df-2)/df)*z
    # => r^2 = sigma^2 * (df-2)/df * z^2 where z^2 ~ F(1, df)
    # => r^2 / (sigma^2 * (df-2)/df) ~ F(1, df)
    from scipy.stats import f as f_dist
    # Use median df estimate
    valid_df = a4f_t_df[~np.isnan(a4f_t_df)]
    median_df = np.median(valid_df) if len(valid_df) > 0 else 8.0
    f_q = f_dist.ppf(tau, dfn=1, dfd=median_df)
    a4f_t_quantiles[tau] = a4f_t_sigma2 * (median_df - 2) / median_df * f_q

print(f"  Median Student-t df: {median_df:.2f}")


# ============================================================
# SECTION 8: CALIBRATION EVALUATION
# ============================================================
print("\n[8] Calibration evaluation...")

# For each method and each tau, compute coverage rate
# Coverage = P(r^2 <= Q_tau) should be close to tau

eval_start = qr_start  # Only evaluate where QR predictions are available
eval_r2 = oos_r2_vals[eval_start:]
n_eval = len(eval_r2)

methods = {
    'GJR_Normal': {tau: gjr_normal_quantiles[tau][eval_start:] for tau in TAUS},
    'GJR_QR': {tau: gjr_qr_quantiles[tau][eval_start:] for tau in TAUS},
    'A4f_Normal': {tau: a4f_normal_quantiles[tau][eval_start:] for tau in TAUS},
    'A4f_QR': {tau: a4f_qr_quantiles[tau][eval_start:] for tau in TAUS},
    'A4f_t': {tau: a4f_t_quantiles[tau][eval_start:] for tau in TAUS},
    'Direct_QR': {tau: direct_qr_quantiles[tau][eval_start:] for tau in TAUS},
}

calibration_results = {}
for method_name, quantile_dict in methods.items():
    cal = {}
    for tau in TAUS:
        q_vals = quantile_dict[tau]
        valid = ~np.isnan(q_vals) & ~np.isnan(eval_r2)
        if valid.sum() < 50:
            cal[str(tau)] = {'coverage': np.nan, 'n_valid': int(valid.sum())}
            continue
        coverage = np.mean(eval_r2[valid] <= q_vals[valid])
        # Binomial CI for coverage
        se = np.sqrt(coverage * (1 - coverage) / valid.sum())
        cal[str(tau)] = {
            'coverage': round(float(coverage), 4),
            'target': tau,
            'deviation': round(float(coverage - tau), 4),
            'se': round(float(se), 4),
            'n_valid': int(valid.sum())
        }
    calibration_results[method_name] = cal

# Print calibration table
print(f"\n  Calibration (coverage rates, n_eval={n_eval}):")
print(f"  {'Method':<15}", end="")
for tau in TAUS:
    print(f"  {tau:>6.3f}", end="")
print()
print("  " + "-" * (15 + 8 * len(TAUS)))
for method_name in methods:
    print(f"  {method_name:<15}", end="")
    for tau in TAUS:
        cov = calibration_results[method_name][str(tau)].get('coverage', np.nan)
        if np.isnan(cov):
            print(f"  {'NaN':>6}", end="")
        else:
            print(f"  {cov:>6.3f}", end="")
    print()
print(f"  {'Target':<15}", end="")
for tau in TAUS:
    print(f"  {tau:>6.3f}", end="")
print()


# ============================================================
# SECTION 9: SHARPNESS (PI WIDTH)
# ============================================================
print("\n[9] Sharpness (PI width)...")

# Sharpness = average width of (1-alpha) prediction intervals
# Use symmetric intervals: [Q_{alpha/2}, Q_{1-alpha/2}]
pi_levels = [(0.025, 0.975), (0.05, 0.95), (0.10, 0.90)]
sharpness_results = {}

for method_name, quantile_dict in methods.items():
    sharp = {}
    for lo, hi in pi_levels:
        lo_vals = quantile_dict[lo][:]
        hi_vals = quantile_dict[hi][:]
        valid = ~np.isnan(lo_vals) & ~np.isnan(hi_vals)
        if valid.sum() < 50:
            sharp[f"{1-2*lo:.0%}"] = np.nan
            continue
        widths = hi_vals[valid] - lo_vals[valid]
        sharp[f"{1-2*lo:.0%}"] = round(float(np.mean(widths)), 8)
    sharpness_results[method_name] = sharp

print(f"  {'Method':<15}  {'95% PI':>12}  {'90% PI':>12}  {'80% PI':>12}")
print("  " + "-" * 55)
for method_name in methods:
    s = sharpness_results[method_name]
    print(f"  {method_name:<15}", end="")
    for key in ['95%', '90%', '80%']:
        v = s.get(key, np.nan)
        if np.isnan(v):
            print(f"  {'NaN':>12}", end="")
        else:
            print(f"  {v:>12.8f}", end="")
    print()


# ============================================================
# SECTION 10: WINKLER SCORE
# ============================================================
print("\n[10] Winkler score (calibration + sharpness)...")

def winkler_score(y, lower, upper, alpha):
    """
    Winkler (1972) interval score.
    Lower alpha = wider interval expected.
    Score = (upper - lower) + 2/alpha * (lower - y) * I(y < lower)
                             + 2/alpha * (y - upper) * I(y > upper)
    """
    width = upper - lower
    below = np.maximum(lower - y, 0)
    above = np.maximum(y - upper, 0)
    return width + (2.0 / alpha) * below + (2.0 / alpha) * above


winkler_results = {}
for method_name, quantile_dict in methods.items():
    wink = {}
    for lo, hi in pi_levels:
        alpha_pi = 2 * lo  # alpha for the PI (e.g., 0.05 for 95% PI)
        lo_vals = quantile_dict[lo][:]
        hi_vals = quantile_dict[hi][:]
        valid = ~np.isnan(lo_vals) & ~np.isnan(hi_vals) & ~np.isnan(eval_r2)
        if valid.sum() < 50:
            wink[f"{1-alpha_pi:.0%}"] = np.nan
            continue
        scores = winkler_score(eval_r2[valid], lo_vals[valid], hi_vals[valid], alpha_pi)
        wink[f"{1-alpha_pi:.0%}"] = round(float(np.mean(scores)), 8)
    winkler_results[method_name] = wink

print(f"  {'Method':<15}  {'95% Winkler':>14}  {'90% Winkler':>14}  {'80% Winkler':>14}")
print("  " + "-" * 60)
for method_name in methods:
    w = winkler_results[method_name]
    print(f"  {method_name:<15}", end="")
    for key in ['95%', '90%', '80%']:
        v = w.get(key, np.nan)
        if np.isnan(v):
            print(f"  {'NaN':>14}", end="")
        else:
            print(f"  {v:>14.8f}", end="")
    print()


# ============================================================
# SECTION 11: VaR/ES BACKTESTING
# ============================================================
print("\n[11] VaR/ES backtesting...")

# VaR is on returns, not on r^2
# VaR_alpha(r_t) = -sigma_t * z_{1-alpha}  (left tail)
# For QR-based: use QR quantiles of r^2 to get return quantiles
# Q_{alpha}(r_t) = -sqrt(Q_{1-alpha}(r^2_t))  (approximate for symmetric dist)

def kupiec_test(violations, T, alpha):
    n1 = np.sum(violations)
    n0 = T - n1
    pi_hat = n1 / T
    if pi_hat == 0 or pi_hat == 1:
        return 0, 1.0
    lr = 2 * (n1 * np.log(pi_hat / alpha) + n0 * np.log((1 - pi_hat) / (1 - alpha)))
    return lr, 1 - chi2.cdf(lr, 1)


def christoffersen_cc_test(violations):
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        v0, v1 = violations[t-1], violations[t]
        if v0 == 0 and v1 == 0: n00 += 1
        elif v0 == 0 and v1 == 1: n01 += 1
        elif v0 == 1 and v1 == 0: n10 += 1
        else: n11 += 1
    if (n00+n01) == 0 or (n10+n11) == 0:
        return 0, 1.0
    pi01 = n01 / (n00+n01)
    pi11 = n11 / (n10+n11)
    pi = (n01+n11) / T
    if pi in (0,1) or pi01 in (0,1) or pi11 in (0,1):
        return 0, 1.0
    try:
        lr = 2 * (n00*np.log((1-pi01)/(1-pi)) + n01*np.log(pi01/pi)
                   + n10*np.log((1-pi11)/(1-pi)) + n11*np.log(pi11/pi))
    except:
        return 0, 1.0
    if np.isnan(lr):
        return 0, 1.0
    return lr, 1 - chi2.cdf(lr, 1)


def dq_test(violations, alpha, sigma_arr):
    T = len(violations)
    hit = violations.astype(float) - alpha
    if T < 5:
        return 0, 1.0
    X = np.column_stack([np.ones(T-1), hit[:-1], sigma_arr[1:]])
    y = hit[1:]
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        beta = XtX_inv @ X.T @ y
        dq_stat = (beta.T @ X.T @ X @ beta) / (alpha * (1 - alpha))
        return dq_stat, 1 - chi2.cdf(dq_stat, X.shape[1])
    except:
        return 0, 1.0


def acerbi_szekely_z1(returns_arr, var_vals, es_vals, alpha):
    violations = returns_arr < var_vals
    n_viol = np.sum(violations)
    if n_viol == 0:
        return 0, 1.0
    T = len(returns_arr)
    z1 = np.sum(returns_arr[violations] / es_vals[violations]) / (T * alpha) + 1
    rng = np.random.default_rng(42)
    z1_boot = np.zeros(1000)
    for b in range(1000):
        idx = rng.choice(T, T, replace=True)
        rb = returns_arr[idx]; vb = var_vals[idx]; eb = es_vals[idx]
        viol_b = rb < vb
        if np.sum(viol_b) > 0:
            z1_boot[b] = np.sum(rb[viol_b] / eb[viol_b]) / (T * alpha) + 1
    return z1, float(np.mean(z1_boot <= z1))


# Parametric VaR/ES
eval_ret = oos_ret_vals[eval_start:]
eval_sigma_gjr = np.sqrt(np.maximum(gjr_sigma2[eval_start:], 0))
eval_sigma_a4f = np.sqrt(np.maximum(a4f_sigma2[eval_start:], 0))
eval_sigma_a4f_t = np.sqrt(np.maximum(a4f_t_sigma2[eval_start:], 0))

var_alphas = [0.01, 0.025, 0.05]
var_results = {}

for alpha in var_alphas:
    print(f"\n  VaR alpha={alpha}:")
    z_norm = norm.ppf(alpha)

    # 1. GJR Normal VaR
    gjr_var = eval_sigma_gjr * z_norm
    gjr_es = eval_sigma_gjr * (-norm.pdf(z_norm) / alpha)

    # 2. A4f Normal VaR
    a4f_var = eval_sigma_a4f * z_norm
    a4f_es = eval_sigma_a4f * (-norm.pdf(z_norm) / alpha)

    # 3. A4f-t VaR
    sf = np.sqrt((median_df - 2) / median_df)
    z_t = t_dist.ppf(alpha, median_df)
    a4f_t_var = eval_sigma_a4f_t * sf * z_t
    pdf_q = t_dist.pdf(z_t, median_df)
    a4f_t_es = eval_sigma_a4f_t * sf * (-pdf_q / alpha) * ((median_df + z_t**2) / (median_df - 1))

    # 4. QR-based VaR: use Q_{alpha}(r^2) from QR, then VaR = -sqrt(Q_{1-alpha}(r^2))
    # This is an approximation. For return quantiles, we need to think about sign.
    # Better approach: QR directly on returns (but we fit QR on forecast errors of r^2)
    # Alternative: use QR quantile of r^2 as conditional variance for VaR
    # VaR_alpha = -sqrt(Q_{1-alpha}(r^2_t)) (for left tail of return)
    # This is approximate but reasonable since E[r]=0 approx for daily returns

    # A4f QR VaR: use the QR-adjusted sigma^2 (median quantile gives adjusted variance)
    # Use the 50th percentile from QR as the adjusted variance estimate
    a4f_qr_median = a4f_qr_quantiles[0.50][eval_start:]
    a4f_qr_sigma = np.sqrt(np.maximum(a4f_qr_median, 1e-16))
    a4f_qr_var = a4f_qr_sigma * z_norm
    a4f_qr_es = a4f_qr_sigma * (-norm.pdf(z_norm) / alpha)

    # Evaluate each method
    for name, var_v, es_v, sig_v in [
        ('GJR_Normal', gjr_var, gjr_es, eval_sigma_gjr),
        ('A4f_Normal', a4f_var, a4f_es, eval_sigma_a4f),
        ('A4f_t', a4f_t_var, a4f_t_es, eval_sigma_a4f_t),
        ('A4f_QR_med', a4f_qr_var, a4f_qr_es, a4f_qr_sigma),
    ]:
        valid = ~np.isnan(var_v) & ~np.isnan(eval_ret)
        if valid.sum() < 50:
            continue
        r = eval_ret[valid]
        v = var_v[valid]
        e = es_v[valid]
        s = sig_v[valid]
        violations = (r < v).astype(int)
        T = len(r)
        viol_rate = np.sum(violations) / T

        uc_stat, uc_p = kupiec_test(violations, T, alpha)
        cc_stat, cc_p = christoffersen_cc_test(violations)
        dq_stat, dq_p = dq_test(violations, alpha, s)

        expected = T * alpha
        if np.sum(violations) <= expected * 1.5:
            basel = "GREEN"
        elif np.sum(violations) <= expected * 2.0:
            basel = "YELLOW"
        else:
            basel = "RED"

        # ES test for alpha=0.025
        es_z1 = es_z1_p = es_z2 = es_z2_p = None
        if abs(alpha - 0.025) < 0.001:
            es_z1, es_z1_p = acerbi_szekely_z1(r, v, e, alpha)

        n_pass = sum([uc_p > 0.05, cc_p > 0.05, dq_p > 0.05, basel == "GREEN"])

        key = f"{name}_alpha{alpha}"
        var_results[key] = {
            'method': name, 'alpha': alpha, 'T': T,
            'violations': int(np.sum(violations)),
            'violation_rate': round(float(viol_rate * 100), 2),
            'expected_rate': round(alpha * 100, 2),
            'UC_p': round(float(uc_p), 4),
            'CC_p': round(float(cc_p), 4),
            'DQ_p': round(float(dq_p), 4),
            'Basel': basel,
            'pass_count': n_pass,
        }
        if es_z1 is not None:
            var_results[key]['ES_Z1'] = round(float(es_z1), 4)
            var_results[key]['ES_Z1_p'] = round(float(es_z1_p), 4)

        print(f"    {name:<15}: viol={viol_rate*100:.2f}% (exp={alpha*100:.1f}%), "
              f"UC_p={uc_p:.3f}, CC_p={cc_p:.3f}, Basel={basel}, pass={n_pass}/4")


# ============================================================
# SECTION 12: CALIBRATION DEVIATION SCORE
# ============================================================
print("\n[12] Overall calibration deviation score...")

# Mean absolute deviation of coverage from target across all taus
cal_deviation = {}
for method_name in methods:
    devs = []
    for tau in TAUS:
        c = calibration_results[method_name][str(tau)].get('coverage', np.nan)
        if not np.isnan(c):
            devs.append(abs(c - tau))
    cal_deviation[method_name] = round(float(np.mean(devs)), 4) if devs else np.nan

print(f"  {'Method':<15}  {'MAD from target':>16}")
print("  " + "-" * 35)
for method_name in sorted(cal_deviation, key=lambda x: cal_deviation.get(x, 1)):
    print(f"  {method_name:<15}  {cal_deviation[method_name]:>16.4f}")


# ============================================================
# SECTION 13: SAVE RESULTS
# ============================================================
print("\n[13] Saving results...")

elapsed = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Probabilistic Volatility Quantile Forecasting',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(n_total),
    'n_oos': int(n_oos_actual),
    'n_eval': int(n_eval),
    'config': {
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'qr_window': QR_WINDOW,
        'oos_start': OOS_START,
        'taus': TAUS,
    },
    'point_forecasts': {
        'qlike_gjr': round(float(qlike_gjr), 6),
        'qlike_a4f': round(float(qlike_a4f), 6),
        'qlike_a4f_t': round(float(qlike_a4f_t), 6),
        'dm_gjr_vs_a4f': {
            't_stat': round(float(dm_gjr_a4f_t), 3),
            'p_value': round(float(dm_gjr_a4f_p), 4),
        },
    },
    'calibration': calibration_results,
    'calibration_deviation_mad': cal_deviation,
    'sharpness': sharpness_results,
    'winkler_scores': winkler_results,
    'var_es_backtest': var_results,
    'student_t_df_median': round(float(median_df), 2),
    'elapsed_seconds': round(elapsed, 1),
    'references': [
        'Koenker & Bassett (1978). Regression Quantiles. Econometrica 46:33-50.',
        'Christoffersen (1998). Evaluating Interval Forecasts. Int Econ Rev 39:841-862.',
        'Gneiting & Raftery (2007). JASA 102:359-378.',
        'Winkler (1972). JASA 67:187-191.',
        'Patton (2011). J Econometrics 160:246-256.',
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
        'Kupiec (1995). J Derivatives 3:73-84.',
        'Acerbi & Szekely (2014). Risk Magazine.',
        'Harvey et al. (2016). t > 3.0 threshold.',
    ],
    'conclusions': {},  # filled below
}

# Determine conclusions
best_cal = min(cal_deviation, key=lambda x: cal_deviation.get(x, 999))
conclusions = {
    'best_calibrated_method': best_cal,
    'best_calibration_mad': cal_deviation[best_cal],
    'qr_improves_gjr_calibration': cal_deviation.get('GJR_QR', 1) < cal_deviation.get('GJR_Normal', 1),
    'qr_improves_a4f_calibration': cal_deviation.get('A4f_QR', 1) < cal_deviation.get('A4f_Normal', 1),
    'a4f_beats_gjr_qlike': qlike_a4f < qlike_gjr,
    'dm_significant_harvey': abs(dm_gjr_a4f_t) > 3.0,
}

# Check Winkler scores
for pi_key in ['95%', '90%', '80%']:
    wink_scores = {m: winkler_results[m].get(pi_key, np.nan) for m in methods}
    valid_scores = {m: v for m, v in wink_scores.items() if not (isinstance(v, float) and np.isnan(v))}
    if valid_scores:
        best_winkler = min(valid_scores, key=valid_scores.get)
        conclusions[f'best_winkler_{pi_key}'] = best_winkler
        conclusions[f'best_winkler_{pi_key}_score'] = valid_scores[best_winkler]

results['conclusions'] = conclusions

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Elapsed: {elapsed:.1f}s")

# ============================================================
# SECTION 14: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"\n  Point forecasts (QLIKE, lower=better):")
print(f"    GJR:   {qlike_gjr:.6f}")
print(f"    A4f:   {qlike_a4f:.6f} {'<-- best' if qlike_a4f <= qlike_a4f_t else ''}")
print(f"    A4f-t: {qlike_a4f_t:.6f}")
print(f"    DM (GJR vs A4f): t={dm_gjr_a4f_t:.3f}")

print(f"\n  Best calibrated (MAD from target, lower=better):")
for method_name in sorted(cal_deviation, key=lambda x: cal_deviation.get(x, 1)):
    marker = " <-- best" if method_name == best_cal else ""
    print(f"    {method_name:<15}: {cal_deviation[method_name]:.4f}{marker}")

print(f"\n  QR improves GJR calibration: {conclusions['qr_improves_gjr_calibration']}")
print(f"  QR improves A4f calibration: {conclusions['qr_improves_a4f_calibration']}")

print(f"\n  Winkler scores (lower=better):")
for pi_key in ['95%', '90%', '80%']:
    best_key = f'best_winkler_{pi_key}'
    if best_key in conclusions:
        print(f"    {pi_key} PI: {conclusions[best_key]} = {conclusions[best_key + '_score']:.8f}")

print(f"\n  Elapsed: {elapsed:.1f}s")
print("=" * 70)
