#!/usr/bin/env python3
"""
K1073: A4f Exogenous Variable Sensitivity — VIX9D vs VIX vs VIX3M vs VVIX
==========================================================================
[提出: Claude, 執行: Claude]

Research questions:
  H1: Is VIX² the best A4f exogenous regressor, or does VIX9D² / VIX3M² / VVIX² win?
  H2: Does adding VIX3M-VIX slope provide marginal contribution?
  H3: Does the optimal VIX choice differ by target (r²_close vs r²_oc)?
  H4: How do θ₁ stability (CV) differ across variants?

Background:
  K988: A4f with VIX² DM t=4.48 vs GJR_close on r²_close.
  K1056: A4f-VIX² 5/5 sub-period stable.
  K1066: A4f_oc (target r²_oc) DM t=+7.05 vs GJR_oc (target r²_oc).
  No systematic comparison of VIX9D/VIX/VIX3M/VVIX as A4f exogenous regressor.

Design:
  - 6 A4f specifications (VIX, VIX9D, VIX3M, VVIX, SLOPE, COMBO)
  - Baseline: GJR_close, GJR_oc
  - SPY 2011+ (VIX9D binding), OOS from 2013-01 onwards
  - Window 2000, refit every 63 days
  - Targets: r²_close AND r²_oc
  - Patton (2011) QLIKE proxy-robust evaluation
  - Newey-West DM test with Harvey (2016) |t|>3.0 threshold
  - Random seed 42

Data source: yfinance ^VIX, ^VIX9D, ^VIX3M, ^VVIX, SPY
Author: VolPred Research System
Date: 2026-04-12
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
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1073"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1073_results.json')

# Configuration
DATA_START = '2011-01-01'   # VIX9D available from 2011-01
DATA_END = '2026-04-13'
OOS_START = '2013-01-02'    # 2 years training buffer
WINDOW = 2000
REFIT_EVERY = 63
RANDOM_SEED = 42

# K988 reference for interpretation
K988_A4F_VIX_VS_GJR_CLOSE_DM = 4.482553559343101

print("=" * 72)
print(f"{EXPERIMENT_ID}: A4f Exogenous Variable Sensitivity")
print("  VIX9D vs VIX vs VIX3M vs VVIX + SLOPE + COMBO")
print("=" * 72)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data (SPY + VIX family from yfinance)...")
import yfinance as yf


def dl_close(sym):
    d = yf.download(sym, start=DATA_START, end=DATA_END,
                    progress=False, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    return d


spy_raw = dl_close('SPY')
vix_close = dl_close('^VIX')['Close']
vix9d_close = dl_close('^VIX9D')['Close']
vix3m_close = dl_close('^VIX3M')['Close']
vvix_close = dl_close('^VVIX')['Close']

spy_close_adj = spy_raw['Adj Close']
spy_close_raw = spy_raw['Close']
spy_open_raw = spy_raw['Open']

log_ret_close = np.log(spy_close_adj / spy_close_adj.shift(1))
log_ret_oc = np.log(spy_close_raw / spy_open_raw)

df = pd.DataFrame({
    'log_ret_close': log_ret_close,
    'log_ret_oc': log_ret_oc,
    'VIX': vix_close,
    'VIX9D': vix9d_close,
    'VIX3M': vix3m_close,
    'VVIX': vvix_close,
})
df = df.dropna()

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = int(oos_mask.sum())
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret_close = df['log_ret_close'].values
ret_oc = df['log_ret_oc'].values
vix_arr = df['VIX'].values
vix9d_arr = df['VIX9D'].values
vix3m_arr = df['VIX3M'].values
vvix_arr = df['VVIX'].values

r2_close = ret_close ** 2
r2_oc = ret_oc ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_idx_arr = np.where(oos_mask)[0]
oos_ret_close = ret_close[oos_mask]
oos_ret_oc = ret_oc[oos_mask]

print(f"  Close ret:  mean={np.mean(oos_ret_close)*252:+.4f}, "
      f"std={np.std(oos_ret_close)*np.sqrt(252):.4f}, "
      f"skew={stats.skew(oos_ret_close):+.3f}, kurt={stats.kurtosis(oos_ret_close):.3f}")
print(f"  OC ret:     mean={np.mean(oos_ret_oc)*252:+.4f}, "
      f"std={np.std(oos_ret_oc)*np.sqrt(252):.4f}, "
      f"skew={stats.skew(oos_ret_oc):+.3f}, kurt={stats.kurtosis(oos_ret_oc):.3f}")
print(f"  r²_close mean: {np.mean(r2_close[oos_mask]):.3e}")
print(f"  r²_oc mean:    {np.mean(r2_oc[oos_mask]):.3e}")

# VIX family descriptive stats (full sample)
vix_family = {'VIX': vix_arr, 'VIX9D': vix9d_arr,
              'VIX3M': vix3m_arr, 'VVIX': vvix_arr}
print(f"  VIX family statistics (full sample, 2011+):")
for name, arr in vix_family.items():
    print(f"    {name:>6}: mean={np.mean(arr):6.2f}, std={np.std(arr):6.2f}, "
          f"min={np.min(arr):5.2f}, max={np.max(arr):6.2f}, "
          f"AC(1)={np.corrcoef(arr[1:], arr[:-1])[0, 1]:.3f}")
# Correlation matrix among VIX variants
corr_df = df[['VIX', 'VIX9D', 'VIX3M', 'VVIX']].corr()
print(f"  VIX family correlation:\n{corr_df.round(3).to_string()}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) (baseline) ---
@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def init_gjr_h(params, train_ret):
    omega, alpha, gamma, beta = params
    n = len(train_ret)
    h = np.var(train_ret[:min(250, n)])
    for i in range(1, n):
        asym = gamma * train_ret[i-1]**2 if train_ret[i-1] < 0 else 0.0
        h = omega + alpha * train_ret[i-1]**2 + asym + beta * h
        if h < 1e-10:
            h = 1e-10
    return h


# --- A4f with 1 exogenous variable (X) ---
# tau_t = max(theta0 + theta1 * X²_{t-1}, eps)
# g_t = omega_g + alpha * u²_{t-1} + gamma * u²_{t-1} * I{u<0} + beta * g_{t-1}
# where u_{t-1} = r_{t-1} / sqrt(tau_t)   [Engle et al. 2013]
# sigma²_t = tau_t * g_t

def build_vix2_lag(vix_vals):
    n = len(vix_vals)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    return vix_lag ** 2  # squared VIX at t-1


@njit(cache=True)
def _a4f_single_nll(params, returns, x2_lag):
    theta0, theta1, omega_g, alpha, gamma_p, beta = params
    n = len(returns)
    if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    persist = alpha + gamma_p / 2.0 + beta
    if persist >= 0.999:
        return 1e10
    eg = omega_g / (1.0 - persist)
    ll = 0.0
    g_prev = eg
    tau0 = theta0 + theta1 * x2_lag[0]
    if tau0 < 1e-16:
        tau0 = 1e-16
    sigma2 = tau0 * eg
    if sigma2 > 0:
        ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                      + returns[0]**2 / sigma2)
    for t in range(1, n):
        tau_t = theta0 + theta1 * x2_lag[t]
        if tau_t < 1e-16:
            tau_t = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau_t)
        if u_prev < 0:
            asym = gamma_p * u_prev * u_prev
        else:
            asym = 0.0
        g_t = omega_g + alpha * u_prev * u_prev + asym + beta * g_prev
        if g_t < 1e-10:
            g_t = 1e-10
        sigma2 = tau_t * g_t
        if sigma2 > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                          + returns[t] * returns[t] / sigma2)
        g_prev = g_t
    return -ll


def fit_a4f_single(returns, x2_lag):
    """
    A4f with single X²_{t-1}: tau = theta0 + theta1 * X²_lag
    Returns params = [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    var0 = np.var(returns)
    x2_mean = np.mean(x2_lag) + 1e-8

    def neg_loglik(params):
        return _a4f_single_nll(np.asarray(params), returns, x2_lag)

    starts = [
        [var0 * 0.1, var0 / x2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    # Bounds: theta1 magnitude depends on x2 scale. VVIX² is much larger than VIX²
    # Use scale-adaptive upper bound.
    theta1_upper = var0 / x2_mean * 100.0  # 100x equilibrium ~ allows wide search
    bounds = [
        (-1e-2, 1e-2),
        (1e-12, max(theta1_upper, 1e-3)),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    for s in starts:
        # Clip start to bounds
        s_clip = [min(max(s_i, b[0]), b[1]) for s_i, b in zip(s, bounds)]
        try:
            res = optimize.minimize(neg_loglik, s_clip, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def init_a4f_single_state(params, train_ret, x2_lag_train):
    theta0, theta1, omega_g, alpha, gamma_p, beta = params
    n = len(train_ret)
    tau_train = np.maximum(theta0 + theta1 * x2_lag_train, 1e-16)
    persist = alpha + gamma_p / 2.0 + beta
    eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
    g = eg
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau_train[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        if g < 1e-10:
            g = 1e-10
    return g


# --- A4f-SLOPE: tau = theta0 + theta1 * VIX²_lag + theta2 * slope_lag ---
# slope = VIX3M - VIX
def build_slope_lag(vix_vals, vix3m_vals):
    n = len(vix_vals)
    slope = vix3m_vals - vix_vals
    slope_lag = np.empty(n)
    slope_lag[0] = slope[0]
    slope_lag[1:] = slope[:-1]
    return slope_lag


@njit(cache=True)
def _a4f_slope_nll(params, returns, vix2_lag, slope_lag):
    theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
    n = len(returns)
    if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    persist = alpha + gamma_p / 2.0 + beta
    if persist >= 0.999:
        return 1e10
    eg = omega_g / (1.0 - persist)
    ll = 0.0
    g_prev = eg
    tau0 = theta0 + theta1 * vix2_lag[0] + theta2 * slope_lag[0]
    if tau0 < 1e-16:
        tau0 = 1e-16
    sigma2 = tau0 * eg
    if sigma2 > 0:
        ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                      + returns[0] * returns[0] / sigma2)
    for t in range(1, n):
        tau_t = theta0 + theta1 * vix2_lag[t] + theta2 * slope_lag[t]
        if tau_t < 1e-16:
            tau_t = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau_t)
        if u_prev < 0:
            asym = gamma_p * u_prev * u_prev
        else:
            asym = 0.0
        g_t = omega_g + alpha * u_prev * u_prev + asym + beta * g_prev
        if g_t < 1e-10:
            g_t = 1e-10
        sigma2 = tau_t * g_t
        if sigma2 > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                          + returns[t] * returns[t] / sigma2)
        g_prev = g_t
    return -ll


def fit_a4f_slope(returns, vix2_lag, slope_lag):
    n = len(returns)
    var0 = np.var(returns)
    vix2_mean = np.mean(vix2_lag) + 1e-8
    slope_std = np.std(slope_lag) + 1e-8

    def neg_loglik(params):
        return _a4f_slope_nll(np.asarray(params), returns, vix2_lag, slope_lag)

    theta2_scale = var0 / slope_std
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_scale * 0.1, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, -theta2_scale * 0.1, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-12, 1e-3),
        (-theta2_scale * 10, theta2_scale * 10),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    for s in starts:
        s_clip = [min(max(s_i, b[0]), b[1]) for s_i, b in zip(s, bounds)]
        try:
            res = optimize.minimize(neg_loglik, s_clip, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def init_a4f_slope_state(params, train_ret, vix2_lag_train, slope_lag_train):
    theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
    n = len(train_ret)
    tau_train = np.maximum(theta0 + theta1 * vix2_lag_train
                           + theta2 * slope_lag_train, 1e-16)
    persist = alpha + gamma_p / 2.0 + beta
    eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
    g = eg
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau_train[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        if g < 1e-10:
            g = 1e-10
    return g


# --- A4f-COMBO: tau = theta0 + theta1 * VIX9D²_lag + theta2 * VIX²_lag + theta3 * VIX3M²_lag ---
@njit(cache=True)
def _a4f_combo_nll(params, returns, vix9d2_lag, vix2_lag, vix3m2_lag):
    theta0, t1, t2, t3, omega_g, alpha, gamma_p, beta = params
    n = len(returns)
    if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    persist = alpha + gamma_p / 2.0 + beta
    if persist >= 0.999:
        return 1e10
    eg = omega_g / (1.0 - persist)
    ll = 0.0
    g_prev = eg
    tau0 = (theta0 + t1 * vix9d2_lag[0] + t2 * vix2_lag[0]
            + t3 * vix3m2_lag[0])
    if tau0 < 1e-16:
        tau0 = 1e-16
    sigma2 = tau0 * eg
    if sigma2 > 0:
        ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                      + returns[0] * returns[0] / sigma2)
    for t in range(1, n):
        tau_t = (theta0 + t1 * vix9d2_lag[t] + t2 * vix2_lag[t]
                 + t3 * vix3m2_lag[t])
        if tau_t < 1e-16:
            tau_t = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau_t)
        if u_prev < 0:
            asym = gamma_p * u_prev * u_prev
        else:
            asym = 0.0
        g_t = omega_g + alpha * u_prev * u_prev + asym + beta * g_prev
        if g_t < 1e-10:
            g_t = 1e-10
        sigma2 = tau_t * g_t
        if sigma2 > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                          + returns[t] * returns[t] / sigma2)
        g_prev = g_t
    return -ll


def fit_a4f_combo(returns, vix9d2_lag, vix2_lag, vix3m2_lag):
    n = len(returns)
    var0 = np.var(returns)
    m1 = np.mean(vix9d2_lag) + 1e-8
    m2 = np.mean(vix2_lag) + 1e-8
    m3 = np.mean(vix3m2_lag) + 1e-8

    def neg_loglik(params):
        return _a4f_combo_nll(np.asarray(params), returns, vix9d2_lag,
                              vix2_lag, vix3m2_lag)

    # Seed with split equal among 3 components
    base = var0 / 3.0
    starts = [
        [var0 * 0.1, base/m1, base/m2, base/m3, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, 0, var0 / m2, 0, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.05, base/m1 * 0.5, base/m2 * 0.5, base/m3 * 2, 0.02, 0.05, 0.05, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (-1e-3, 1e-3),
        (-1e-3, 1e-3),
        (-1e-3, 1e-3),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    for s in starts:
        s_clip = [min(max(s_i, b[0]), b[1]) for s_i, b in zip(s, bounds)]
        try:
            res = optimize.minimize(neg_loglik, s_clip, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def init_a4f_combo_state(params, train_ret, vix9d2_lag_train,
                         vix2_lag_train, vix3m2_lag_train):
    theta0, t1, t2, t3, omega_g, alpha, gamma_p, beta = params
    n = len(train_ret)
    tau_train = np.maximum(theta0 + t1 * vix9d2_lag_train
                           + t2 * vix2_lag_train
                           + t3 * vix3m2_lag_train, 1e-16)
    persist = alpha + gamma_p / 2.0 + beta
    eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
    g = eg
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau_train[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        if g < 1e-10:
            g = 1e-10
    return g


# ============================================================
# SECTION 4: OOS FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

# Precompute lagged X² (predetermined, no lookahead)
vix2_lag_full = build_vix2_lag(vix_arr)
vix9d2_lag_full = build_vix2_lag(vix9d_arr)
vix3m2_lag_full = build_vix2_lag(vix3m_arr)
vvix2_lag_full = build_vix2_lag(vvix_arr)
slope_lag_full = build_slope_lag(vix_arr, vix3m_arr)

# Models: separate series for each target (close, oc)
# To keep things compact, we fit one set on close returns and another on oc returns
# We'll prefix model names: A4f_VIX (fit on close), A4f_VIX_oc (fit on oc), etc.

base_specs = ['A4f_VIX', 'A4f_VIX9D', 'A4f_VIX3M', 'A4f_VVIX',
              'A4f_SLOPE', 'A4f_COMBO']
model_names = ['GJR_close', 'GJR_oc']
for s in base_specs:
    model_names += [f'{s}_close', f'{s}_oc']

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")
print(f"  Window: {WINDOW}, Refit every: {REFIT_EVERY}")
print(f"  Models: {len(model_names)}")

forecasts = {name: np.full(n_oos_actual, np.nan) for name in model_names}
param_history = {name: [] for name in model_names if name not in
                 ['GJR_close', 'GJR_oc']}
refit_dates = []

states = {name: {'h': None, 'g': None, 'params': None}
          for name in model_names}

refit_count = 0


def fit_all_for_returns(ret_train, vix2_tr, vix9d2_tr, vix3m2_tr, vvix2_tr,
                        slope_tr):
    """Fit all A4f variants + GJR for one return series."""
    out = {}
    out['GJR'] = fit_gjr(ret_train)
    out['A4f_VIX'] = fit_a4f_single(ret_train, vix2_tr)
    out['A4f_VIX9D'] = fit_a4f_single(ret_train, vix9d2_tr)
    out['A4f_VIX3M'] = fit_a4f_single(ret_train, vix3m2_tr)
    out['A4f_VVIX'] = fit_a4f_single(ret_train, vvix2_tr)
    out['A4f_SLOPE'] = fit_a4f_slope(ret_train, vix2_tr, slope_tr)
    out['A4f_COMBO'] = fit_a4f_combo(ret_train, vix9d2_tr, vix2_tr, vix3m2_tr)
    return out


for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        refit_dates.append(str(df.index[abs_idx].date()))
        train_start = max(0, abs_idx - WINDOW)

        train_ret_close = ret_close[train_start:abs_idx]
        train_ret_oc = ret_oc[train_start:abs_idx]
        tr_vix2 = vix2_lag_full[train_start:abs_idx]
        tr_vix9d2 = vix9d2_lag_full[train_start:abs_idx]
        tr_vix3m2 = vix3m2_lag_full[train_start:abs_idx]
        tr_vvix2 = vvix2_lag_full[train_start:abs_idx]
        tr_slope = slope_lag_full[train_start:abs_idx]

        # Fit for close target
        fitted_close = fit_all_for_returns(
            train_ret_close, tr_vix2, tr_vix9d2, tr_vix3m2, tr_vvix2, tr_slope)
        # Fit for oc target
        fitted_oc = fit_all_for_returns(
            train_ret_oc, tr_vix2, tr_vix9d2, tr_vix3m2, tr_vvix2, tr_slope)

        # GJR_close
        p = fitted_close['GJR']
        if p is not None:
            states['GJR_close']['params'] = p
            states['GJR_close']['h'] = init_gjr_h(p, train_ret_close)

        # GJR_oc
        p = fitted_oc['GJR']
        if p is not None:
            states['GJR_oc']['params'] = p
            states['GJR_oc']['h'] = init_gjr_h(p, train_ret_oc)

        # A4f variants (single-exog)
        single_map = {
            'A4f_VIX':   tr_vix2,
            'A4f_VIX9D': tr_vix9d2,
            'A4f_VIX3M': tr_vix3m2,
            'A4f_VVIX':  tr_vvix2,
        }
        for spec, x2_tr in single_map.items():
            for tgt, fitted, train_ret in [
                ('close', fitted_close, train_ret_close),
                ('oc',    fitted_oc,    train_ret_oc)
            ]:
                mname = f'{spec}_{tgt}'
                p = fitted[spec]
                if p is not None:
                    g = init_a4f_single_state(p, train_ret, x2_tr)
                    states[mname]['params'] = p
                    states[mname]['g'] = g
                    param_history[mname].append({
                        'date': str(df.index[abs_idx].date()),
                        'theta0': float(p[0]),
                        'theta1': float(p[1]),
                        'omega_g': float(p[2]),
                        'alpha': float(p[3]),
                        'gamma': float(p[4]),
                        'beta': float(p[5]),
                    })

        # SLOPE (7 params)
        for tgt, fitted, train_ret in [
            ('close', fitted_close, train_ret_close),
            ('oc',    fitted_oc,    train_ret_oc)
        ]:
            mname = f'A4f_SLOPE_{tgt}'
            p = fitted['A4f_SLOPE']
            if p is not None:
                g = init_a4f_slope_state(p, train_ret, tr_vix2, tr_slope)
                states[mname]['params'] = p
                states[mname]['g'] = g
                param_history[mname].append({
                    'date': str(df.index[abs_idx].date()),
                    'theta0': float(p[0]),
                    'theta1_vix2': float(p[1]),
                    'theta2_slope': float(p[2]),
                    'omega_g': float(p[3]),
                    'alpha': float(p[4]),
                    'gamma': float(p[5]),
                    'beta': float(p[6]),
                })

        # COMBO (8 params)
        for tgt, fitted, train_ret in [
            ('close', fitted_close, train_ret_close),
            ('oc',    fitted_oc,    train_ret_oc)
        ]:
            mname = f'A4f_COMBO_{tgt}'
            p = fitted['A4f_COMBO']
            if p is not None:
                g = init_a4f_combo_state(p, train_ret, tr_vix9d2, tr_vix2, tr_vix3m2)
                states[mname]['params'] = p
                states[mname]['g'] = g
                param_history[mname].append({
                    'date': str(df.index[abs_idx].date()),
                    'theta0': float(p[0]),
                    'theta1_vix9d2': float(p[1]),
                    'theta2_vix2': float(p[2]),
                    'theta3_vix3m2': float(p[3]),
                    'omega_g': float(p[4]),
                    'alpha': float(p[5]),
                    'gamma': float(p[6]),
                    'beta': float(p[7]),
                })

    # --- Generate forecasts for day abs_idx (using info up to abs_idx - 1) ---

    # GJR baselines
    p = states['GJR_close']['params']
    if p is not None:
        h_new = gjr_forecast_1step(p, states['GJR_close']['h'],
                                    ret_close[abs_idx - 1])
        forecasts['GJR_close'][t_idx] = h_new
        states['GJR_close']['h'] = h_new

    p = states['GJR_oc']['params']
    if p is not None:
        h_new = gjr_forecast_1step(p, states['GJR_oc']['h'],
                                    ret_oc[abs_idx - 1])
        forecasts['GJR_oc'][t_idx] = h_new
        states['GJR_oc']['h'] = h_new

    # A4f single-exog variants
    single_x2 = {
        'A4f_VIX':   vix2_lag_full[abs_idx],
        'A4f_VIX9D': vix9d2_lag_full[abs_idx],
        'A4f_VIX3M': vix3m2_lag_full[abs_idx],
        'A4f_VVIX':  vvix2_lag_full[abs_idx],
    }
    for spec, x2_now in single_x2.items():
        for tgt, r_prev in [('close', ret_close[abs_idx - 1]),
                            ('oc',    ret_oc[abs_idx - 1])]:
            mname = f'{spec}_{tgt}'
            p = states[mname]['params']
            if p is not None:
                theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p
                tau_t = max(theta0 + theta1 * x2_now, 1e-16)
                g_prev = states[mname]['g']
                u_prev = r_prev / np.sqrt(tau_t)
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
                g_new = max(g_new, 1e-10)
                forecasts[mname][t_idx] = tau_t * g_new
                states[mname]['g'] = g_new

    # SLOPE
    vix2_now = vix2_lag_full[abs_idx]
    slope_now = slope_lag_full[abs_idx]
    for tgt, r_prev in [('close', ret_close[abs_idx - 1]),
                        ('oc',    ret_oc[abs_idx - 1])]:
        mname = f'A4f_SLOPE_{tgt}'
        p = states[mname]['params']
        if p is not None:
            theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = p
            tau_t = max(theta0 + theta1 * vix2_now + theta2 * slope_now, 1e-16)
            g_prev = states[mname]['g']
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
            g_new = max(g_new, 1e-10)
            forecasts[mname][t_idx] = tau_t * g_new
            states[mname]['g'] = g_new

    # COMBO
    vix9d2_now = vix9d2_lag_full[abs_idx]
    vix3m2_now = vix3m2_lag_full[abs_idx]
    for tgt, r_prev in [('close', ret_close[abs_idx - 1]),
                        ('oc',    ret_oc[abs_idx - 1])]:
        mname = f'A4f_COMBO_{tgt}'
        p = states[mname]['params']
        if p is not None:
            theta0, t1, t2, t3, omega_g, alpha_p, gamma_p, beta_p = p
            tau_t = max(theta0 + t1 * vix9d2_now + t2 * vix2_now
                        + t3 * vix3m2_now, 1e-16)
            g_prev = states[mname]['g']
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
            g_new = max(g_new, 1e-10)
            forecasts[mname][t_idx] = tau_t * g_new
            states[mname]['g'] = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")


# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")


def newey_west_dm(d_vec):
    d = np.asarray(d_vec)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    max_lag = int(np.floor(T ** (1/3)))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(hac_var / T)
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


def qlike_loss(forecast, r2):
    return np.log(forecast) + r2 / forecast


def evaluate_model(fc_vec, proxy_vec):
    valid = np.isfinite(fc_vec) & (fc_vec > 0) & np.isfinite(proxy_vec)
    n = int(valid.sum())
    if n < 100:
        return {'n_valid': n, 'qlike': None, 'mse': None, 'mae': None,
                'spearman_rho': None}
    fc = fc_vec[valid]
    pr = proxy_vec[valid]
    ql = float(np.mean(qlike_loss(fc, pr)))
    mse = float(np.mean((fc - pr) ** 2))
    mae = float(np.mean(np.abs(fc - pr)))
    rho, rho_p = stats.spearmanr(fc, pr)
    return {
        'n_valid': n,
        'qlike': ql,
        'mse': mse,
        'mae': mae,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
    }


oos_r2_close = r2_close[oos_indices]
oos_r2_oc = r2_oc[oos_indices]

results = {
    'experiment_id': EXPERIMENT_ID,
    'description': 'A4f exogenous variable sensitivity — VIX9D/VIX/VIX3M/VVIX + SLOPE + COMBO',
    'motivation': (
        'K988/K1056/K1066 all used VIX² as the A4f exogenous regressor. '
        'This experiment tests whether VIX9D, VIX3M, VVIX, VIX3M-VIX slope, '
        'or a combined specification produces better OOS volatility forecasts '
        'on SPY for r²_close and r²_oc targets.'
    ),
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX, ^VIX9D, ^VIX3M, ^VVIX)',
    'data_period': f'{DATA_START} to {df.index[-1].strftime("%Y-%m-%d")}',
    'n_total': n_total,
    'oos_start': OOS_START,
    'n_oos': n_oos_actual,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'random_seed': RANDOM_SEED,
    'vix_family_stats': {
        name: {
            'mean': float(np.mean(arr)),
            'std': float(np.std(arr)),
            'min': float(np.min(arr)),
            'max': float(np.max(arr)),
            'ac1': float(np.corrcoef(arr[1:], arr[:-1])[0, 1]),
        } for name, arr in vix_family.items()
    },
    'vix_family_corr': corr_df.to_dict(),
    'references': [
        'K988: A4f-VIX close DM t=4.48',
        'K1056: A4f-VIX sub-period 5/5',
        'K1066: A4f_oc on r²_oc DM t=+7.05',
        'Engle, Ghysels & Sohn 2013 RES 95(3): GARCH-MIDAS',
        'Patton 2011 JoE 160: QLIKE robustness',
        'Harvey et al. 2016: t>3.0 threshold',
    ],
    'models': model_names,
    'proxies': {},
    'dm_tests': {},
    'param_history_summary': {},
}

# Evaluate each model on each proxy
print("\n  ----- Proxy: r²_close -----")
hdr = f"  {'Model':<20} {'QLIKE':>10} {'MSE':>12} {'MAE':>12} {'Spearman':>9} {'N':>5}"
print(hdr)
print("  " + "-" * 72)
results['proxies']['r2_close'] = {}
for name in model_names:
    eval_res = evaluate_model(forecasts[name], oos_r2_close)
    results['proxies']['r2_close'][name] = eval_res
    if eval_res['qlike'] is not None:
        print(f"  {name:<20} {eval_res['qlike']:>10.4f} {eval_res['mse']:>12.2e} "
              f"{eval_res['mae']:>12.2e} {eval_res['spearman_rho']:>9.4f} "
              f"{eval_res['n_valid']:>5}")

print("\n  ----- Proxy: r²_oc -----")
print(hdr)
print("  " + "-" * 72)
results['proxies']['r2_oc'] = {}
for name in model_names:
    eval_res = evaluate_model(forecasts[name], oos_r2_oc)
    results['proxies']['r2_oc'][name] = eval_res
    if eval_res['qlike'] is not None:
        print(f"  {name:<20} {eval_res['qlike']:>10.4f} {eval_res['mse']:>12.2e} "
              f"{eval_res['mae']:>12.2e} {eval_res['spearman_rho']:>9.4f} "
              f"{eval_res['n_valid']:>5}")


# ============================================================
# DM matrix (full pairwise on each target)
# ============================================================
print("\n  DM Tests: building full pairwise matrix on both proxies...")

close_models = [m for m in model_names if m.endswith('close')]
oc_models = [m for m in model_names if m.endswith('oc')]

dm_matrix_close = {}
dm_matrix_oc = {}
proxy_pairs = [
    ('r2_close', oos_r2_close, close_models),
    ('r2_oc',    oos_r2_oc,    oc_models),
]
for pn, pv, ms in proxy_pairs:
    store = dm_matrix_close if pn == 'r2_close' else dm_matrix_oc
    for n1 in ms:
        for n2 in ms:
            if n1 == n2:
                continue
            fc1 = forecasts[n1]
            fc2 = forecasts[n2]
            both = (np.isfinite(fc1) & (fc1 > 0) & np.isfinite(fc2)
                    & (fc2 > 0) & np.isfinite(pv))
            n = int(both.sum())
            if n < 100:
                continue
            l1 = qlike_loss(fc1[both], pv[both])
            l2 = qlike_loss(fc2[both], pv[both])
            d = l1 - l2
            t_stat, p_val = newey_west_dm(d)
            key = f'{n1}__vs__{n2}'
            store[key] = {
                'n': n,
                'dm_t': float(t_stat) if np.isfinite(t_stat) else None,
                'dm_p': float(p_val) if np.isfinite(p_val) else None,
                'winner': n2 if (np.isfinite(t_stat) and t_stat > 0) else n1,
                'harvey_sig': bool(np.isfinite(t_stat) and abs(t_stat) > 3.0),
            }

results['dm_tests']['r2_close'] = dm_matrix_close
results['dm_tests']['r2_oc'] = dm_matrix_oc


def print_key_pairs(store, label, models_subset, proxy_label):
    print(f"\n  Key comparisons on {proxy_label}:")
    baseline = models_subset[0]  # GJR
    # vs GJR
    for m in models_subset[1:]:
        key = f'{baseline}__vs__{m}'
        if key in store and store[key]['dm_t'] is not None:
            r = store[key]
            mark = '***' if r['harvey_sig'] else ('*' if abs(r['dm_t']) > 1.96 else '')
            print(f"    {baseline} vs {m}: t={r['dm_t']:+.3f} "
                  f"winner={r['winner']} {mark}")
    # A4f_VIX vs others
    vix_base = f'A4f_VIX_{label}'
    for m in models_subset:
        if m == vix_base or m == baseline:
            continue
        key = f'{vix_base}__vs__{m}'
        if key in store and store[key]['dm_t'] is not None:
            r = store[key]
            mark = '***' if r['harvey_sig'] else ('*' if abs(r['dm_t']) > 1.96 else '')
            print(f"    {vix_base} vs {m}: t={r['dm_t']:+.3f} "
                  f"winner={r['winner']} {mark}")


print_key_pairs(dm_matrix_close, 'close', close_models, 'r²_close')
print_key_pairs(dm_matrix_oc, 'oc', oc_models, 'r²_oc')


# ============================================================
# SECTION 6: Theta1 stability (CV analysis)
# ============================================================
print("\n[6] Parameter stability (θ₁ CV)...")
stability = {}
for mname, hist in param_history.items():
    if not hist:
        continue
    if 'theta1' in hist[0]:  # single-exog
        theta1_vals = np.array([x['theta1'] for x in hist])
        mean_ = float(np.mean(theta1_vals))
        std_ = float(np.std(theta1_vals))
        cv = float(abs(std_ / mean_)) if mean_ != 0 else None
        stability[mname] = {
            'n_refits': len(hist),
            'theta1_mean': mean_,
            'theta1_std': std_,
            'theta1_min': float(np.min(theta1_vals)),
            'theta1_max': float(np.max(theta1_vals)),
            'theta1_cv': cv,
        }
    elif 'theta1_vix2' in hist[0]:  # SLOPE
        t1_vals = np.array([x['theta1_vix2'] for x in hist])
        t2_vals = np.array([x['theta2_slope'] for x in hist])
        stability[mname] = {
            'n_refits': len(hist),
            'theta1_vix2_mean': float(np.mean(t1_vals)),
            'theta1_vix2_cv': float(abs(np.std(t1_vals)/np.mean(t1_vals)))
                              if np.mean(t1_vals) != 0 else None,
            'theta2_slope_mean': float(np.mean(t2_vals)),
            'theta2_slope_std': float(np.std(t2_vals)),
        }
    elif 'theta1_vix9d2' in hist[0]:  # COMBO
        t1 = np.array([x['theta1_vix9d2'] for x in hist])
        t2 = np.array([x['theta2_vix2'] for x in hist])
        t3 = np.array([x['theta3_vix3m2'] for x in hist])
        stability[mname] = {
            'n_refits': len(hist),
            'theta1_vix9d2_mean': float(np.mean(t1)),
            'theta2_vix2_mean': float(np.mean(t2)),
            'theta3_vix3m2_mean': float(np.mean(t3)),
            'theta1_vix9d2_std': float(np.std(t1)),
            'theta2_vix2_std': float(np.std(t2)),
            'theta3_vix3m2_std': float(np.std(t3)),
        }

# Print stability summary sorted by CV
print(f"  {'Model':<20} {'N refits':>8} {'θ₁ mean':>12} {'θ₁ std':>12} {'θ₁ CV':>8}")
print("  " + "-" * 65)
single_entries = [(m, s) for m, s in stability.items() if 'theta1_cv' in s]
single_entries.sort(key=lambda x: x[1].get('theta1_cv') if x[1].get('theta1_cv') is not None else 1e9)
for m, s in single_entries:
    cv_str = f"{s['theta1_cv']:.3f}" if s['theta1_cv'] is not None else 'nan'
    print(f"  {m:<20} {s['n_refits']:>8d} {s['theta1_mean']:>12.3e} "
          f"{s['theta1_std']:>12.3e} {cv_str:>8}")
results['param_stability'] = stability
results['param_history'] = param_history
results['refit_dates'] = refit_dates


# ============================================================
# SECTION 7: τ contribution analysis
# ============================================================
print("\n[7] Mean τ contribution to total σ²...")
# Approximation: compare tau_mean vs sigma2_mean. We didn't save intermediate tau
# but we can reconstruct for each single-exog model using param history.
tau_contribution = {}
# Use most recent params for approximation (end-of-sample values from last refit)
last_params = {}
for mname, hist in param_history.items():
    if hist:
        last_params[mname] = hist[-1]

# For each single-exog A4f model at OOS, reconstruct tau on oos_indices
oos_vix2 = vix2_lag_full[oos_indices]
oos_vix9d2 = vix9d2_lag_full[oos_indices]
oos_vix3m2 = vix3m2_lag_full[oos_indices]
oos_vvix2 = vvix2_lag_full[oos_indices]
oos_slope = slope_lag_full[oos_indices]

x2_map = {
    'A4f_VIX_close': oos_vix2, 'A4f_VIX_oc': oos_vix2,
    'A4f_VIX9D_close': oos_vix9d2, 'A4f_VIX9D_oc': oos_vix9d2,
    'A4f_VIX3M_close': oos_vix3m2, 'A4f_VIX3M_oc': oos_vix3m2,
    'A4f_VVIX_close': oos_vvix2, 'A4f_VVIX_oc': oos_vvix2,
}

for mname, x2_oos in x2_map.items():
    p = last_params.get(mname)
    if p is None:
        continue
    tau_series = np.maximum(p['theta0'] + p['theta1'] * x2_oos, 1e-16)
    fc = forecasts[mname]
    valid = np.isfinite(fc) & (fc > 0)
    if valid.sum() < 100:
        continue
    # tau vs sigma²
    tau_mean = float(np.mean(tau_series[valid]))
    sigma2_mean = float(np.mean(fc[valid]))
    # Ratio tau / sigma2 over time
    ratio = tau_series[valid] / fc[valid]
    tau_contribution[mname] = {
        'tau_mean_end_of_sample_params': tau_mean,
        'sigma2_mean_forecast': sigma2_mean,
        'tau_over_sigma2_mean': float(np.mean(ratio)),
        'tau_over_sigma2_std': float(np.std(ratio)),
    }
    print(f"  {mname:<20} τ/σ² mean={np.mean(ratio):.3f}, std={np.std(ratio):.3f}")
results['tau_contribution'] = tau_contribution


# ============================================================
# SECTION 8: HYPOTHESIS VERDICTS
# ============================================================
print("\n[8] Hypothesis verdicts...")

# H1: Is VIX² the best A4f exog for r²_close?
ql_close = {m: results['proxies']['r2_close'][m]['qlike']
            for m in close_models
            if results['proxies']['r2_close'][m]['qlike'] is not None}
ranked_close = sorted(ql_close.items(), key=lambda x: x[1])
best_close = ranked_close[0][0]
vix_rank_close = [i for i, (m, _) in enumerate(ranked_close) if m == 'A4f_VIX_close']
vix_rank_close = vix_rank_close[0] + 1 if vix_rank_close else None

ql_oc = {m: results['proxies']['r2_oc'][m]['qlike']
         for m in oc_models
         if results['proxies']['r2_oc'][m]['qlike'] is not None}
ranked_oc = sorted(ql_oc.items(), key=lambda x: x[1])
best_oc = ranked_oc[0][0]
vix_rank_oc = [i for i, (m, _) in enumerate(ranked_oc) if m == 'A4f_VIX_oc']
vix_rank_oc = vix_rank_oc[0] + 1 if vix_rank_oc else None

# Check if best is Harvey-significantly better than A4f_VIX
def dm_best_vs_vix(store, best_m, vix_m):
    if best_m == vix_m:
        return None
    key = f'{vix_m}__vs__{best_m}'
    if key not in store:
        return None
    return store[key]

h1_close = dm_best_vs_vix(dm_matrix_close, best_close, 'A4f_VIX_close')
h1_oc = dm_best_vs_vix(dm_matrix_oc, best_oc, 'A4f_VIX_oc')

h1_pass_close = (best_close != 'A4f_VIX_close' and h1_close is not None
                 and h1_close['harvey_sig'])
h1_pass_oc = (best_oc != 'A4f_VIX_oc' and h1_oc is not None
              and h1_oc['harvey_sig'])

# H2: SLOPE adds incremental contribution vs A4f_VIX?
h2_close = dm_matrix_close.get('A4f_VIX_close__vs__A4f_SLOPE_close')
h2_oc = dm_matrix_oc.get('A4f_VIX_oc__vs__A4f_SLOPE_oc')

h2_pass_close = (h2_close is not None and h2_close['winner'] == 'A4f_SLOPE_close'
                 and h2_close['harvey_sig'])
h2_pass_oc = (h2_oc is not None and h2_oc['winner'] == 'A4f_SLOPE_oc'
              and h2_oc['harvey_sig'])

# H3: Does best choice differ between close and oc?
h3_differs = (best_close.replace('_close', '') != best_oc.replace('_oc', ''))

# H4: θ₁ CV comparison
single_cv = {m: s.get('theta1_cv') for m, s in stability.items()
             if s.get('theta1_cv') is not None}
if single_cv:
    min_cv_model = min(single_cv, key=single_cv.get)
    max_cv_model = max(single_cv, key=single_cv.get)
    h4_stability_rank = sorted(single_cv.items(), key=lambda x: x[1])
else:
    min_cv_model = None
    max_cv_model = None
    h4_stability_rank = []

results['hypotheses'] = {
    'H1_best_exog_vs_VIX': {
        'claim': 'Best A4f-X is Harvey-significantly better than A4f-VIX',
        'best_on_r2_close': best_close,
        'VIX_rank_on_r2_close': vix_rank_close,
        'dm_t_vs_VIX_close': h1_close['dm_t'] if h1_close else None,
        'verdict_r2_close': 'PASS' if h1_pass_close else 'FAIL',
        'best_on_r2_oc': best_oc,
        'VIX_rank_on_r2_oc': vix_rank_oc,
        'dm_t_vs_VIX_oc': h1_oc['dm_t'] if h1_oc else None,
        'verdict_r2_oc': 'PASS' if h1_pass_oc else 'FAIL',
    },
    'H2_SLOPE_adds_contribution': {
        'claim': 'SLOPE (VIX3M-VIX) Harvey-significantly beats A4f-VIX',
        'dm_t_close': h2_close['dm_t'] if h2_close else None,
        'verdict_r2_close': 'PASS' if h2_pass_close else 'FAIL',
        'dm_t_oc': h2_oc['dm_t'] if h2_oc else None,
        'verdict_r2_oc': 'PASS' if h2_pass_oc else 'FAIL',
    },
    'H3_best_choice_differs_by_target': {
        'claim': 'Optimal A4f exog is different for r²_close vs r²_oc',
        'best_close': best_close,
        'best_oc': best_oc,
        'differs': bool(h3_differs),
        'verdict': 'PASS' if h3_differs else 'FAIL',
    },
    'H4_theta1_stability': {
        'claim': 'Different VIX variants have different θ₁ CV',
        'min_cv_model': min_cv_model,
        'max_cv_model': max_cv_model,
        'stability_ranking': h4_stability_rank,
    },
}

print(f"  H1 (close): best={best_close}, VIX rank={vix_rank_close}/{len(close_models)-1}, "
      f"→ {'PASS' if h1_pass_close else 'FAIL'}")
print(f"  H1 (oc):    best={best_oc}, VIX rank={vix_rank_oc}/{len(oc_models)-1}, "
      f"→ {'PASS' if h1_pass_oc else 'FAIL'}")
print(f"  H2 (close SLOPE vs VIX): t={h2_close['dm_t']:+.3f} "
      f"→ {'PASS' if h2_pass_close else 'FAIL'}" if h2_close else "  H2 close: n/a")
print(f"  H2 (oc SLOPE vs VIX):    t={h2_oc['dm_t']:+.3f} "
      f"→ {'PASS' if h2_pass_oc else 'FAIL'}" if h2_oc else "  H2 oc: n/a")
print(f"  H3 (best differs by target): {'YES' if h3_differs else 'NO'}")
if min_cv_model:
    print(f"  H4 θ₁ CV: most stable = {min_cv_model} "
          f"(CV={single_cv[min_cv_model]:.3f}), least stable = {max_cv_model} "
          f"(CV={single_cv[max_cv_model]:.3f})")


# ============================================================
# Paper 9 implication
# ============================================================
if h1_pass_close or h1_pass_oc:
    paper9_rec = (f"CONSIDER_SWITCH: Best exog ({best_close}/close, {best_oc}/oc) "
                  f"is Harvey-significantly better than A4f-VIX. "
                  f"Paper 9 may benefit from switching main spec.")
elif h2_pass_close or h2_pass_oc:
    paper9_rec = ("ADD_SLOPE: VIX3M-VIX slope adds marginal contribution. "
                  "Paper 9 can add SLOPE as robustness or main extension.")
else:
    paper9_rec = ("BASELINE_CONFIRMED: VIX² is the best or tied-best A4f exog. "
                  "K1073 confirms K988 baseline; no change to Paper 9 main spec.")
results['paper9_recommendation'] = paper9_rec
print(f"\n  Paper 9 implication: {paper9_rec}")

# Save results
results['elapsed_seconds'] = time.time() - START_TIME
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved: {RESULTS_PATH}")


# ============================================================
# SECTION 9: PLOTS
# ============================================================
print("\n[9] Generating plots...")
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # === Plot 1: DM matrix (close + oc) ===
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for idx, (pname, store, ms) in enumerate([
        ('r²_close', dm_matrix_close, close_models),
        ('r²_oc',    dm_matrix_oc,    oc_models),
    ]):
        ax = axes[idx]
        n = len(ms)
        mtx = np.full((n, n), np.nan)
        for i, n1 in enumerate(ms):
            for j, n2 in enumerate(ms):
                if i == j:
                    continue
                key = f'{n1}__vs__{n2}'
                if key in store and store[key]['dm_t'] is not None:
                    mtx[i, j] = store[key]['dm_t']
        vmax = max(8.0, float(np.nanmax(np.abs(mtx))) if np.any(np.isfinite(mtx)) else 8.0)
        im = ax.imshow(mtx, cmap='RdBu_r', vmin=-vmax, vmax=vmax, aspect='auto')
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        # Short labels (strip _close/_oc)
        short = [m.replace('_close', '').replace('_oc', '') for m in ms]
        ax.set_xticklabels(short, rotation=45, ha='right', fontsize=9)
        ax.set_yticklabels(short, fontsize=9)
        ax.set_title(f'DM t-stat: col wins over row ({pname})')
        ax.set_xlabel('Column (winner candidate)')
        ax.set_ylabel('Row (loser)')
        for i in range(n):
            for j in range(n):
                if not np.isnan(mtx[i, j]):
                    color = 'white' if abs(mtx[i, j]) > 4 else 'black'
                    ax.text(j, i, f'{mtx[i, j]:+.1f}', ha='center', va='center',
                            color=color, fontsize=7)
        plt.colorbar(im, ax=ax, label='DM t-stat', shrink=0.8)
    plt.tight_layout()
    p1 = os.path.join(SCRIPT_DIR, 'k1073_dm_matrix.png')
    plt.savefig(p1, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p1}")

    # === Plot 2: θ₁ stability time series + CV ===
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    singles = ['A4f_VIX', 'A4f_VIX9D', 'A4f_VIX3M', 'A4f_VVIX']
    colors = {'A4f_VIX': '#2196F3', 'A4f_VIX9D': '#F44336',
              'A4f_VIX3M': '#4CAF50', 'A4f_VVIX': '#FF9800'}
    for ax, tgt in zip(axes, ['close', 'oc']):
        for s in singles:
            mname = f'{s}_{tgt}'
            hist = param_history.get(mname, [])
            if not hist:
                continue
            dts = [pd.Timestamp(x['date']) for x in hist]
            theta1 = np.array([x['theta1'] for x in hist])
            # Normalize: multiply by mean(X²) so comparable across scales
            # Instead, just plot CV info
            mean_ = np.mean(theta1)
            std_ = np.std(theta1)
            cv = abs(std_ / mean_) if mean_ != 0 else 0
            ax.plot(dts, theta1, 'o-', label=f'{s} (CV={cv:.2f})',
                    color=colors[s], alpha=0.8)
        ax.set_ylabel(f'θ₁ ({tgt})')
        ax.set_title(f'A4f-X θ₁ evolution, target=r²_{tgt}')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        ax.set_yscale('symlog', linthresh=1e-6)
    axes[-1].set_xlabel('Refit date')
    plt.tight_layout()
    p2 = os.path.join(SCRIPT_DIR, 'k1073_theta1_stability.png')
    plt.savefig(p2, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p2}")

    # === Plot 3: QLIKE ranking ===
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    for ax, (pname, ms, store) in zip(axes, [
        ('r²_close', close_models, results['proxies']['r2_close']),
        ('r²_oc',    oc_models,    results['proxies']['r2_oc']),
    ]):
        ql_vals = []
        labels_ = []
        colors_ = []
        for m in ms:
            r = store[m]
            if r['qlike'] is not None:
                ql_vals.append(r['qlike'])
                labels_.append(m.replace('_close', '').replace('_oc', ''))
                if 'GJR' in m:
                    colors_.append('#9E9E9E')
                elif 'VIX9D' in m:
                    colors_.append('#F44336')
                elif 'VIX3M' in m:
                    colors_.append('#4CAF50')
                elif 'VVIX' in m:
                    colors_.append('#FF9800')
                elif 'SLOPE' in m:
                    colors_.append('#9C27B0')
                elif 'COMBO' in m:
                    colors_.append('#607D8B')
                else:
                    colors_.append('#2196F3')
        # Sort by QLIKE
        order = np.argsort(ql_vals)
        ql_sorted = [ql_vals[i] for i in order]
        lab_sorted = [labels_[i] for i in order]
        col_sorted = [colors_[i] for i in order]
        bars = ax.barh(range(len(ql_sorted)), ql_sorted, color=col_sorted)
        ax.set_yticks(range(len(ql_sorted)))
        ax.set_yticklabels(lab_sorted)
        ax.invert_yaxis()
        ax.set_xlabel('QLIKE (lower better)')
        ax.set_title(f'QLIKE ranking on {pname}')
        for i, v in enumerate(ql_sorted):
            ax.text(v, i, f' {v:.4f}', va='center', fontsize=9)
        ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    p3 = os.path.join(SCRIPT_DIR, 'k1073_qlike_ranking.png')
    plt.savefig(p3, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p3}")

    # === Plot 4: τ contribution (bar of τ/σ² ratio) ===
    fig, ax = plt.subplots(1, 1, figsize=(11, 6))
    entries = sorted(tau_contribution.items())
    if entries:
        labels = [k.replace('_close', ' (close)').replace('_oc', ' (oc)')
                  for k, _ in entries]
        ratios = [v['tau_over_sigma2_mean'] for _, v in entries]
        stds = [v['tau_over_sigma2_std'] for _, v in entries]
        x = np.arange(len(entries))
        bars = ax.bar(x, ratios, yerr=stds, capsize=4, color='#3F51B5',
                      alpha=0.7, edgecolor='black')
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=35, ha='right', fontsize=9)
        ax.axhline(y=1.0, color='red', linestyle='--', alpha=0.5,
                   label='τ=σ² (full contribution)')
        ax.set_ylabel('τ / σ² (mean ± std over OOS)')
        ax.set_title('A4f-X mean τ contribution to total σ² forecast')
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
        for i, (r, s) in enumerate(zip(ratios, stds)):
            ax.text(i, r, f'{r:.2f}', ha='center', va='bottom', fontsize=8)
    plt.tight_layout()
    p4 = os.path.join(SCRIPT_DIR, 'k1073_tau_contribution.png')
    plt.savefig(p4, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p4}")

    # === Plot 5: comparison table heatmap (QLIKE + Spearman + DM vs GJR) ===
    fig, ax = plt.subplots(1, 1, figsize=(14, 7))
    cols = ['QLIKE r²_close', 'Spearman r²_close', 'DM(vs GJR) r²_close',
            'QLIKE r²_oc', 'Spearman r²_oc', 'DM(vs GJR) r²_oc']
    row_names = [b for b in base_specs]
    matrix = np.full((len(row_names), 6), np.nan)
    for i, spec in enumerate(row_names):
        # close
        mc = f'{spec}_close'
        rc = results['proxies']['r2_close'].get(mc)
        if rc and rc['qlike'] is not None:
            matrix[i, 0] = rc['qlike']
            matrix[i, 1] = rc['spearman_rho']
        # DM vs GJR_close
        key = f'GJR_close__vs__{mc}'
        if key in dm_matrix_close:
            matrix[i, 2] = dm_matrix_close[key]['dm_t']
        # oc
        mo = f'{spec}_oc'
        ro = results['proxies']['r2_oc'].get(mo)
        if ro and ro['qlike'] is not None:
            matrix[i, 3] = ro['qlike']
            matrix[i, 4] = ro['spearman_rho']
        key = f'GJR_oc__vs__{mo}'
        if key in dm_matrix_oc:
            matrix[i, 5] = dm_matrix_oc[key]['dm_t']

    # Normalize each column for heatmap coloring (QLIKE: lower better, others: higher better)
    display = matrix.copy()
    im = ax.imshow(display, cmap='RdYlGn', aspect='auto')
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=25, ha='right')
    ax.set_yticks(range(len(row_names)))
    ax.set_yticklabels(row_names)
    ax.set_title('K1073 A4f-X comparison table')
    for i in range(len(row_names)):
        for j in range(len(cols)):
            v = matrix[i, j]
            if np.isfinite(v):
                txt = f'{v:.3f}' if abs(v) < 100 else f'{v:.1e}'
                ax.text(j, i, txt, ha='center', va='center', fontsize=9)
    plt.tight_layout()
    p5 = os.path.join(SCRIPT_DIR, 'k1073_comparison_table.png')
    plt.savefig(p5, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p5}")

except Exception as e:
    print(f"  Plot error: {e}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*72}")
print(f"K1073 COMPLETE. Total time: {time.time() - START_TIME:.0f}s")
