#!/usr/bin/env python3
"""
K1002: Unified 7-Model OOS Comparison Pipeline for Paper 5
============================================================
[提出: 賴奕豪, 執行: Claude]

Models (7):
  1. GJR-N:     GJR-GARCH(1,1) + Normal
  2. GJR-t:     GJR-GARCH(1,1) + Student-t joint MLE
  3. EGARCH-t:  EGARCH(1,1) + Student-t joint MLE
  4. A4f-N:     MF-GJR-X(VIX², free ω) + Normal
  5. A4f-t:     MF-GJR-X(VIX², free ω) + Student-t joint MLE (champion)
  6. HAR-ABS:   HAR on |r_t| (K530 top model)
  7. Macro-X:   GJR-GARCH-X(term_spread, unemployment)

Data: SPY 2004-2026 (yfinance), OOS: 2019-2026, w=2000, refit/63d.
Evaluation (5 layers, Patton 2011 + Harvey 2016):
  1. QLIKE on r² (proxy-robust ranking)
  2. Pairwise DM tests (21 pairs, Harvey t>3.0)
  3. MCS (Hansen, Lunde & Nason 2011, 10% significance)
  4. Spearman rank ρ
  5. VaR/ES backtesting (1%/2.5%/5% VaR + 2.5% ES)

References:
  - Engle & Rangel (2008): Spline-GARCH. RFS 21(3):1187-1222.
  - Conrad & Loch (2015): Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.
  - Patton (2011): Volatility forecast comparison. J Econometrics 160:246-256.
  - Nelson (1991): EGARCH. Econometrica 59(2):347-370.
  - Corsi (2009): HAR-RV. J Financial Econometrics 7(2):174-196.
  - Hansen, Lunde & Nason (2011): MCS. Econometrica 79(2):453-497.
  - Kupiec (1995), Christoffersen (1998): VaR backtesting.
  - Acerbi & Szekely (2014): ES backtesting.
  - Harvey et al. (2016): t>3.0 threshold.

Author: VolPred Research System
Date: 2026-04-08
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
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import t as t_dist, chi2, norm
from numba import njit
import math

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1002"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Configuration
DATA_START = '2004-01-01'
DATA_END = '2026-12-31'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 72)
print(f"{EXPERIMENT_ID}: Unified 7-Model OOS Comparison Pipeline for Paper 5")
print("=" * 72)

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n[1] Loading data...", flush=True)
import yfinance as yf

spy = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
for d in [spy, vix_raw]:
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)

df = pd.DataFrame(index=spy.index)
df['close'] = spy['Close']
df['vix'] = vix_raw['Close'].reindex(spy.index, method='ffill')
df['ret'] = np.log(df['close'] / df['close'].shift(1))
df = df.dropna()
df['ret'] = df['ret'].clip(-0.20, 0.20)
df['r2'] = df['ret'] ** 2
df['vix2'] = (df['vix'] / 100) ** 2
df['abs_ret'] = np.abs(df['ret'])

print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

# Load macro data from FRED (using direct URL, pandas_datareader has compatibility issues)
print("  Loading FRED macro data...", flush=True)
try:
    def read_fred(series_id, start, end):
        """Read FRED data directly via CSV API."""
        url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
               f"?id={series_id}&cosd={start}&coed={end}")
        d = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        d.columns = [series_id]
        d[series_id] = pd.to_numeric(d[series_id], errors='coerce')
        return d

    gs10 = read_fred('GS10', DATA_START, DATA_END)
    tb3ms = read_fred('TB3MS', DATA_START, DATA_END)
    unrate = read_fred('UNRATE', DATA_START, DATA_END)
    term_spread = (gs10['GS10'] - tb3ms['TB3MS'])
    term_spread = term_spread.reindex(df.index, method='ffill')
    unrate_daily = unrate['UNRATE'].reindex(df.index, method='ffill')
    # Lag by 1 month (~22 trading days) for real-time availability
    df['term_spread'] = term_spread.shift(22).ffill()
    df['unrate'] = unrate_daily.shift(22).ffill()
    df['term_spread'] = df['term_spread'].fillna(df['term_spread'].median())
    df['unrate'] = df['unrate'].fillna(df['unrate'].median())
    MACRO_OK = True
    print(f"  Macro: term_spread range [{df['term_spread'].min():.2f}, {df['term_spread'].max():.2f}]")
    print(f"  Macro: unrate range [{df['unrate'].min():.2f}, {df['unrate'].max():.2f}]")
except Exception as e:
    print(f"  WARNING: FRED data failed: {e}. Macro-X model will be skipped.")
    MACRO_OK = False
    df['term_spread'] = 0.0
    df['unrate'] = 0.0

# OOS mask
oos_mask = df.index >= OOS_START
n_oos = oos_mask.sum()
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

# ============================================================
# 2. DIAGNOSTICS
# ============================================================
print("\n[2] Descriptive statistics (OOS period)...", flush=True)
oos_ret = df.loc[oos_mask, 'ret'].values
print(f"  Mean return (ann): {np.mean(oos_ret)*252:.4f}")
print(f"  Std (ann):         {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  Skewness:          {stats.skew(oos_ret):.3f}")
print(f"  Kurtosis:          {stats.kurtosis(oos_ret):.3f}")
oos_r2 = oos_ret ** 2
print(f"  Mean r²:           {np.mean(oos_r2):.6f}")

# ============================================================
# 3. NUMBA-ACCELERATED MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations (Numba-accelerated)...", flush=True)

# --- GJR-GARCH(1,1) ---
@njit(cache=True)
def gjr_h(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h

@njit(cache=True)
def gjr_nll_normal(omega, alpha, gamma, beta, returns):
    h = gjr_h(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

@njit(cache=True)
def t_logpdf_sum(returns, h, df):
    T = len(returns)
    scale_factor = np.sqrt((df - 2.0) / df)
    c = math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0) - 0.5 * np.log(np.pi * df)
    ll = 0.0
    for t in range(T):
        sigma = np.sqrt(h[t])
        s = sigma * scale_factor
        z = returns[t] / s
        ll += c - np.log(s) - (df + 1.0) / 2.0 * np.log(1.0 + z * z / df)
    return ll

# --- MF-GJR-X (A4f) ---
@njit(cache=True)
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2[t-1]
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
def a4f_nll_normal(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

# --- EGARCH ---
@njit(cache=True)
def egarch_recursion(omega, alpha, gamma, beta, returns, e_abs_z):
    """EGARCH(1,1): log(h_t) = ω + α(|z|-E|z|) + γz + β log(h_{t-1})"""
    T = len(returns)
    log_h = np.empty(T)
    h = np.empty(T)
    log_h[0] = np.log(np.var(returns))
    h[0] = np.exp(log_h[0])
    for t in range(1, T):
        z = returns[t-1] / np.sqrt(h[t-1])
        log_h[t] = omega + alpha * (np.abs(z) - e_abs_z) + gamma * z + beta * log_h[t-1]
        # Clamp to prevent overflow
        if log_h[t] > 0:
            log_h[t] = 0.0
        if log_h[t] < -30:
            log_h[t] = -30.0
        h[t] = np.exp(log_h[t])
    return h, log_h

# --- GJR-GARCH-X (Macro) ---
@njit(cache=True)
def gjr_x_h(omega, alpha, gamma, beta, delta1, delta2, returns, x1, x2):
    """GJR-GARCH-X with 2 exogenous regressors in mean equation for variance."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = (omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
                + delta1 * x1[t-1] + delta2 * x2[t-1])
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


# ============================================================
# 4. FITTING FUNCTIONS
# ============================================================
print("\n[4] Defining fitting functions...", flush=True)

def fit_gjr_normal(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            v = gjr_nll_normal(p[0], p[1], p[2], p[3], returns)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    x0 = [var0 * 0.05, 0.05, 0.05, 0.90]
    res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
    h = gjr_h(res.x[0], res.x[1], res.x[2], res.x[3], returns)
    return {'params': res.x, 'h': h, 'converged': res.success, 'nll': res.fun}


def fit_gjr_t(returns):
    var0 = np.var(returns)
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_h(p[0], p[1], p[2], p[3], returns)
            ll = t_logpdf_sum(returns, h, p[4])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, df_init]
        try:
            res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h = gjr_h(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3], returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success,
            'nll': best_res.fun, 'df': best_res.x[4]}


def fit_egarch_t(returns):
    """EGARCH(1,1) + Student-t joint MLE."""
    var0 = np.var(returns)
    # E[|z|] for Student-t computed inside
    bounds = [(-5.0, 0.0), (0.0, 1.0), (-0.5, 0.0), (0.5, 0.9999), (3.0, 50.0)]
    def obj(p):
        omega, alpha, gamma_e, beta, df = p
        if abs(beta) >= 1.0:
            return 1e10
        try:
            # E[|z|] for Student-t
            e_abs_z = (math.gamma((df-1)/2) / (np.sqrt((df-2)/2) * math.gamma(df/2)))
            h, log_h = egarch_recursion(omega, alpha, gamma_e, beta, returns, e_abs_z)
            ll = t_logpdf_sum(returns, h, df)
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        for omega_init in [np.log(var0), np.log(var0) * 0.5]:
            x0 = [omega_init * (1.0 - 0.95), 0.1, -0.08, 0.95, df_init]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        return {'params': np.array([-0.1, 0.1, -0.08, 0.95, 8.0]),
                'h': np.full(len(returns), var0), 'converged': False, 'nll': 1e10, 'df': 8.0}
    df_val = best_res.x[4]
    e_abs_z = math.gamma((df_val-1)/2) / (np.sqrt((df_val-2)/2) * math.gamma(df_val/2))
    h, _ = egarch_recursion(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3],
                            returns, e_abs_z)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success,
            'nll': best_res.fun, 'df': df_val, 'e_abs_z': e_abs_z}


def fit_a4f_normal(returns, vix2):
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll_normal(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5], returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun}


def fit_a4f_t(returns, vix2):
    """A4f + Student-t joint MLE."""
    res_n = fit_a4f_normal(returns, vix2)
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            ll = t_logpdf_sum(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(res_n['params']) + [df_init]
        try:
            res = minimize(obj, p0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    h, tau, g = a4f_recursion(best_res.x[0], best_res.x[1], best_res.x[2],
                               best_res.x[3], best_res.x[4], best_res.x[5], returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun, 'df': best_res.x[6]}


def fit_har_abs(returns):
    """HAR-ABS: HAR(1,5,22) on |r_t|, OLS."""
    abs_r = np.abs(returns)
    T = len(returns)
    if T < 23:
        return {'params': np.zeros(4), 'fitted': np.full(T, np.nan), 'converged': False}
    # Construct HAR regressors
    y = abs_r[22:]
    x1 = abs_r[21:-1]  # lag 1
    x5 = np.array([np.mean(abs_r[t-5:t]) for t in range(22, T)])  # lag 1-5
    x22 = np.array([np.mean(abs_r[t-22:t]) for t in range(22, T)])  # lag 1-22
    X = np.column_stack([np.ones(len(y)), x1, x5, x22])
    try:
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
    except:
        beta = np.zeros(4)
    fitted = X @ beta
    fitted = np.maximum(fitted, 1e-8)
    return {'params': beta, 'fitted': fitted, 'converged': True,
            'n_train': len(y)}


def fit_gjr_x_t(returns, x1_vals, x2_vals):
    """GJR-GARCH-X + Student-t: macro regressors in variance equation."""
    var0 = np.var(returns)
    x1_sc = x1_vals / 100.0  # scale term spread
    x2_sc = x2_vals / 100.0  # scale unrate
    bounds = [(1e-10, var0*10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999),
              (-1e-4, 1e-4), (-1e-4, 1e-4), (3.0, 50.0)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_x_h(p[0], p[1], p[2], p[3], p[4], p[5], returns, x1_sc, x2_sc)
            ll = t_logpdf_sum(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, 0.0, 0.0, df_init]
        try:
            res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds, options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except:
            continue
    if best_res is None:
        return {'params': np.array([var0*0.05, 0.05, 0.05, 0.90, 0, 0, 8.0]),
                'h': np.full(len(returns), var0), 'converged': False, 'nll': 1e10, 'df': 8.0}
    h = gjr_x_h(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3],
                best_res.x[4], best_res.x[5], returns, x1_sc, x2_sc)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success,
            'nll': best_res.fun, 'df': best_res.x[6]}


# ============================================================
# 5. OOS FORECASTING ENGINE
# ============================================================
print("\n[5] OOS forecasting...", flush=True)

MODEL_NAMES = ['GJR_N', 'GJR_t', 'EGARCH_t', 'A4f_N', 'A4f_t', 'HAR_ABS']
if MACRO_OK:
    MODEL_NAMES.append('Macro_X')

returns = df['ret'].values
vix2 = df['vix2'].values
r2 = df['r2'].values
abs_ret = df['abs_ret'].values
ts_vals = df['term_spread'].values
un_vals = df['unrate'].values

T = len(df)
oos_start_idx = np.where(df.index >= OOS_START)[0][0]

# Store forecasts and df estimates
forecasts = {m: np.full(T, np.nan) for m in MODEL_NAMES}
df_estimates = {m: np.full(T, np.nan) for m in MODEL_NAMES}

# Per-model state
state = {}
C_GAMMA_NORMAL = np.sqrt(2.0 / np.pi)

for t in range(oos_start_idx, T):
    need_refit = (t == oos_start_idx) or (t - state.get('last_fit_idx', -REFIT_EVERY) >= REFIT_EVERY)

    if need_refit:
        s = max(0, t - WINDOW)
        tr = returns[s:t]
        tv = vix2[s:t]
        ts_tr = ts_vals[s:t]
        un_tr = un_vals[s:t]

        if t % 200 == 0 or t == oos_start_idx:
            elapsed = time.time() - START_TIME
            pct = (t - oos_start_idx) / (T - oos_start_idx) * 100
            print(f"  Refitting at t={t} ({pct:.0f}%, {elapsed:.0f}s)...", flush=True)

        state['gjr_n'] = fit_gjr_normal(tr)
        state['gjr_t'] = fit_gjr_t(tr)
        state['egarch_t'] = fit_egarch_t(tr)
        state['a4f_n'] = fit_a4f_normal(tr, tv)
        state['a4f_t'] = fit_a4f_t(tr, tv)
        state['har'] = fit_har_abs(tr)
        if MACRO_OK:
            state['macro_x'] = fit_gjr_x_t(tr, ts_tr, un_tr)

        state['last_fit_idx'] = t
        # Initialize h_prev from last in-sample value
        state['h_prev_gjr_n'] = state['gjr_n']['h'][-1]
        state['h_prev_gjr_t'] = state['gjr_t']['h'][-1]
        state['h_prev_egarch_t'] = state['egarch_t']['h'][-1]
        state['g_prev_a4f'] = state['a4f_n'].get('g', np.array([1.0]))[-1]
        state['g_prev_a4f_t'] = state['a4f_t'].get('g', np.array([1.0]))[-1]
        if MACRO_OK:
            state['h_prev_macro'] = state['macro_x']['h'][-1]

    # --- GJR-N ---
    p = state['gjr_n']['params']
    r_prev = returns[t-1]
    r2p = r_prev ** 2
    ind = 1.0 if r_prev < 0 else 0.0
    h_t = p[0] + p[1]*r2p + p[2]*r2p*ind + p[3]*state['h_prev_gjr_n']
    h_t = max(h_t, 1e-16)
    forecasts['GJR_N'][t] = h_t
    state['h_prev_gjr_n'] = h_t

    # --- GJR-t ---
    p = state['gjr_t']['params']
    h_t = p[0] + p[1]*r2p + p[2]*r2p*ind + p[3]*state['h_prev_gjr_t']
    h_t = max(h_t, 1e-16)
    forecasts['GJR_t'][t] = h_t
    df_estimates['GJR_t'][t] = p[4]
    state['h_prev_gjr_t'] = h_t

    # --- EGARCH-t ---
    p = state['egarch_t']['params']
    omega_e, alpha_e, gamma_e, beta_e, df_e = p
    e_abs_z = state['egarch_t'].get('e_abs_z',
        math.gamma((df_e-1)/2) / (np.sqrt((df_e-2)/2) * math.gamma(df_e/2)))
    z_prev = returns[t-1] / np.sqrt(state['h_prev_egarch_t'])
    log_h_prev = np.log(max(state['h_prev_egarch_t'], 1e-16))
    log_h_t = omega_e + alpha_e*(abs(z_prev) - e_abs_z) + gamma_e*z_prev + beta_e*log_h_prev
    log_h_t = max(min(log_h_t, 0.0), -30.0)
    h_t = np.exp(log_h_t)
    forecasts['EGARCH_t'][t] = h_t
    df_estimates['EGARCH_t'][t] = df_e
    state['h_prev_egarch_t'] = h_t

    # --- A4f-N ---
    p = state['a4f_n']['params']
    theta0, theta1, omega_a, alpha_a, gamma_a, beta_a = p
    tau_t = max(theta0 + theta1 * vix2[t-1], 1e-16)
    u_prev = returns[t-1] / np.sqrt(tau_t)
    u2 = u_prev ** 2
    ind_a = 1.0 if returns[t-1] < 0 else 0.0
    g_t = omega_a + alpha_a*u2 + gamma_a*u2*ind_a + beta_a*state['g_prev_a4f']
    g_t = max(g_t, 1e-16)
    forecasts['A4f_N'][t] = tau_t * g_t
    state['g_prev_a4f'] = g_t

    # --- A4f-t ---
    p = state['a4f_t']['params']
    theta0, theta1, omega_a, alpha_a, gamma_a, beta_a = p[:6]
    tau_t = max(theta0 + theta1 * vix2[t-1], 1e-16)
    u_prev = returns[t-1] / np.sqrt(tau_t)
    u2 = u_prev ** 2
    g_t = omega_a + alpha_a*u2 + gamma_a*u2*ind_a + beta_a*state['g_prev_a4f_t']
    g_t = max(g_t, 1e-16)
    forecasts['A4f_t'][t] = tau_t * g_t
    df_estimates['A4f_t'][t] = p[6]
    state['g_prev_a4f_t'] = g_t

    # --- HAR-ABS ---
    har_beta = state['har']['params']
    if t >= 22:
        x1_h = abs_ret[t-1]
        x5_h = np.mean(abs_ret[t-5:t])
        x22_h = np.mean(abs_ret[t-22:t])
        pred_abs = max(har_beta[0] + har_beta[1]*x1_h + har_beta[2]*x5_h + har_beta[3]*x22_h, 1e-8)
        forecasts['HAR_ABS'][t] = (pred_abs / C_GAMMA_NORMAL) ** 2
    else:
        forecasts['HAR_ABS'][t] = np.var(returns[:t]) if t > 1 else 1e-4

    # --- Macro-X ---
    if MACRO_OK:
        p = state['macro_x']['params']
        x1_sc = ts_vals[t-1] / 100.0
        x2_sc = un_vals[t-1] / 100.0
        h_t = (p[0] + p[1]*r2p + p[2]*r2p*ind + p[3]*state['h_prev_macro']
               + p[4]*x1_sc + p[5]*x2_sc)
        h_t = max(h_t, 1e-16)
        forecasts['Macro_X'][t] = h_t
        df_estimates['Macro_X'][t] = p[6]
        state['h_prev_macro'] = h_t

elapsed = time.time() - START_TIME
print(f"  OOS forecasting complete in {elapsed:.0f}s", flush=True)

# ============================================================
# 6. EVALUATION LAYER 1: QLIKE
# ============================================================
print("\n[6] QLIKE evaluation...", flush=True)

oos_idx = np.where(oos_mask)[0]
oos_r2 = r2[oos_idx]

qlike_scores = {}
qlike_losses = {}
for m in MODEL_NAMES:
    h_oos = forecasts[m][oos_idx]
    valid = ~np.isnan(h_oos) & (h_oos > 0)
    if valid.sum() < 100:
        print(f"  WARNING: {m} has only {valid.sum()} valid forecasts")
        qlike_scores[m] = np.nan
        qlike_losses[m] = np.full(len(oos_idx), np.nan)
        continue
    # Pointwise QLIKE: log(h) + r²/h
    pw = np.log(h_oos) + oos_r2 / h_oos
    pw[~valid] = np.nan
    qlike_losses[m] = pw
    qlike_scores[m] = float(np.nanmean(pw))

# Rank
ranked = sorted(qlike_scores.items(), key=lambda x: x[1])
print("\n  QLIKE Ranking (lower = better):")
for i, (m, q) in enumerate(ranked):
    print(f"  {i+1}. {m:12s}: {q:.6f}")

# ============================================================
# 7. EVALUATION LAYER 2: PAIRWISE DM TESTS
# ============================================================
print("\n[7] Pairwise DM tests (Harvey t>3.0)...", flush=True)

def dm_test_nw(loss1, loss2):
    """Diebold-Mariano with Newey-West HAC."""
    d = loss1 - loss2
    valid = ~np.isnan(d)
    d = d[valid]
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
    return float(t_stat), float(p_val)

dm_matrix = {}
for i, m1 in enumerate(MODEL_NAMES):
    for j, m2 in enumerate(MODEL_NAMES):
        if i >= j:
            continue
        t_stat, p_val = dm_test_nw(qlike_losses[m1], qlike_losses[m2])
        dm_matrix[f"{m1}_vs_{m2}"] = {'t_stat': t_stat, 'p_val': p_val}
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
        winner = m1 if t_stat < 0 else m2
        print(f"  {m1:12s} vs {m2:12s}: DM t={t_stat:+6.2f}  p={p_val:.4f} {sig}  -> {winner}")

# ============================================================
# 8. EVALUATION LAYER 3: MODEL CONFIDENCE SET (MCS)
# ============================================================
print("\n[8] Model Confidence Set (Hansen et al. 2011)...", flush=True)

def compute_mcs(losses_dict, alpha=0.10, n_boot=1000, block_size=None):
    """
    Bootstrap MCS implementation.
    losses_dict: {model_name: array of pointwise losses}
    Returns: set of model names in the superior set.
    """
    models = list(losses_dict.keys())
    # Build loss matrix (T x M)
    T_min = min(len(v) for v in losses_dict.values())
    loss_mat = np.column_stack([losses_dict[m][:T_min] for m in models])
    # Remove NaN rows
    valid = ~np.any(np.isnan(loss_mat), axis=1)
    loss_mat = loss_mat[valid]
    T = len(loss_mat)
    M = len(models)

    if block_size is None:
        block_size = max(1, int(T ** (1/3)))

    rng = np.random.default_rng(42)
    surviving = list(range(M))

    while len(surviving) > 1:
        sub_loss = loss_mat[:, surviving]
        m_sub = len(surviving)
        # Compute pairwise loss differentials
        d_bar = np.zeros((m_sub, m_sub))
        for i in range(m_sub):
            for j in range(i+1, m_sub):
                d = sub_loss[:, i] - sub_loss[:, j]
                d_bar[i, j] = np.mean(d)
                d_bar[j, i] = -d_bar[i, j]

        # t_max statistic: max over pairs of |t_ij|
        t_stats = np.zeros((m_sub, m_sub))
        for i in range(m_sub):
            for j in range(i+1, m_sub):
                d = sub_loss[:, i] - sub_loss[:, j]
                var_d = np.var(d, ddof=1) / T
                if var_d > 0:
                    t_stats[i, j] = abs(np.mean(d)) / np.sqrt(var_d)
                    t_stats[j, i] = t_stats[i, j]

        t_max_obs = np.max(t_stats)

        # Block bootstrap
        n_blocks = int(np.ceil(T / block_size))
        boot_t_max = np.zeros(n_boot)
        for b in range(n_boot):
            block_starts = rng.integers(0, T - block_size + 1, size=n_blocks)
            idx = np.concatenate([np.arange(s, min(s + block_size, T)) for s in block_starts])[:T]
            boot_loss = sub_loss[idx]
            boot_t_max_val = 0.0
            for i in range(m_sub):
                for j in range(i+1, m_sub):
                    d_b = boot_loss[:, i] - boot_loss[:, j]
                    d_centered = d_b - np.mean(sub_loss[:, i] - sub_loss[:, j])
                    var_b = np.var(d_centered, ddof=1) / T
                    if var_b > 0:
                        t_b = abs(np.mean(d_centered)) / np.sqrt(var_b)
                        boot_t_max_val = max(boot_t_max_val, t_b)
            boot_t_max[b] = boot_t_max_val

        p_val = np.mean(boot_t_max >= t_max_obs)

        if p_val >= alpha:
            break  # Cannot reject: current set is the MCS

        # Eliminate the worst model (highest average loss)
        avg_loss = np.mean(sub_loss, axis=0)
        worst_idx = np.argmax(avg_loss)
        surviving.pop(worst_idx)

    mcs_models = [models[i] for i in surviving]
    return mcs_models

mcs_set = compute_mcs(qlike_losses, alpha=0.10, n_boot=1000)
print(f"  MCS (10% significance): {mcs_set}")

# ============================================================
# 9. EVALUATION LAYER 4: SPEARMAN RANK CORRELATION
# ============================================================
print("\n[9] Spearman rank correlation with r²...", flush=True)

spearman_results = {}
for m in MODEL_NAMES:
    h_oos = forecasts[m][oos_idx]
    valid = ~np.isnan(h_oos)
    if valid.sum() < 100:
        spearman_results[m] = {'rho': np.nan, 'p_val': np.nan}
        continue
    rho, p = stats.spearmanr(oos_r2[valid], h_oos[valid])
    spearman_results[m] = {'rho': float(rho), 'p_val': float(p)}
    print(f"  {m:12s}: rho={rho:.4f}  p={p:.2e}")

# ============================================================
# 10. EVALUATION LAYER 5: VaR/ES BACKTESTING
# ============================================================
print("\n[10] VaR/ES backtesting...", flush=True)

def var_normal(sigma, alpha):
    return sigma * norm.ppf(alpha)

def es_normal(sigma, alpha):
    z_alpha = norm.ppf(alpha)
    return sigma * (-norm.pdf(z_alpha) / alpha)

def var_student_t(sigma, alpha, df_val):
    t_q = t_dist.ppf(alpha, df_val)
    scale = np.sqrt((df_val - 2.0) / df_val)
    return sigma * t_q * scale

def es_student_t(sigma, alpha, df_val):
    t_q = t_dist.ppf(alpha, df_val)
    t_pdf = t_dist.pdf(t_q, df_val)
    scale = np.sqrt((df_val - 2.0) / df_val)
    return sigma * (-(t_pdf * (df_val + t_q**2) / ((df_val - 1.0) * alpha)) * scale)

def kupiec_uc_test(violations, n, alpha):
    n_viol = int(np.sum(violations))
    pi_hat = n_viol / n if n > 0 else 0.0
    if n_viol == 0 or n_viol == n:
        return {'stat': 0.0, 'p_value': 1.0 if n_viol == 0 else 0.0,
                'violation_rate': float(pi_hat), 'n_violations': n_viol, 'n': n}
    log_l_null = n_viol * np.log(alpha) + (n - n_viol) * np.log(1 - alpha)
    log_l_alt = n_viol * np.log(pi_hat) + (n - n_viol) * np.log(1 - pi_hat)
    lr = -2.0 * (log_l_null - log_l_alt)
    p_value = 1.0 - chi2.cdf(max(lr, 0), 1)
    return {'stat': float(lr), 'p_value': float(p_value),
            'violation_rate': float(pi_hat), 'n_violations': n_viol, 'n': n}

def christoffersen_cc_test(violations_arr, n, alpha):
    uc = kupiec_uc_test(violations_arr, n, alpha)
    n00, n01, n10, n11 = 0, 0, 0, 0
    for t_idx in range(1, len(violations_arr)):
        v0, v1 = violations_arr[t_idx-1], violations_arr[t_idx]
        if v0 == 0 and v1 == 0: n00 += 1
        elif v0 == 0 and v1 == 1: n01 += 1
        elif v0 == 1 and v1 == 0: n10 += 1
        else: n11 += 1
    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi_hat_all = (n01 + n11) / max(n00+n01+n10+n11, 1)
    eps = 1e-16
    if (n00+n01) > 0 and (n10+n11) > 0 and 0 < pi_hat_all < 1:
        log_l_ind = 0.0
        if n00 > 0: log_l_ind += n00 * np.log(max(1-pi01, eps))
        if n01 > 0: log_l_ind += n01 * np.log(max(pi01, eps))
        if n10 > 0: log_l_ind += n10 * np.log(max(1-pi11, eps))
        if n11 > 0: log_l_ind += n11 * np.log(max(pi11, eps))
        log_l_null_ind = ((n00+n10)*np.log(max(1-pi_hat_all, eps))
                         + (n01+n11)*np.log(max(pi_hat_all, eps)))
        lr_ind = max(-2.0*(log_l_null_ind - log_l_ind), 0.0)
    else:
        lr_ind = 0.0
    lr_cc = uc['stat'] + lr_ind
    p_cc = 1.0 - chi2.cdf(lr_cc, 2)
    p_ind = 1.0 - chi2.cdf(lr_ind, 1)
    return {'stat_cc': float(lr_cc), 'p_cc': float(p_cc),
            'stat_uc': uc['stat'], 'p_uc': uc['p_value'],
            'violation_rate': uc['violation_rate'],
            'n_violations': uc['n_violations'], 'n': n}

def acerbi_szekely_z1(ret_arr, es_arr, var_arr, alpha):
    violations = ret_arr < var_arr
    n_viol = int(np.sum(violations))
    if n_viol == 0:
        return {'stat': 0.0, 'p_value': 1.0, 'n_violations': 0}
    z1 = np.mean(ret_arr[violations] / es_arr[violations]) + 1.0
    T_len = len(ret_arr)
    n_boot = 1000
    rng = np.random.default_rng(42)
    z1_boot = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, T_len, size=T_len)
        br, bv, be = ret_arr[idx], var_arr[idx], es_arr[idx]
        bviol = br < bv
        z1_boot[b] = (np.mean(br[bviol]/be[bviol]) + 1.0) if np.sum(bviol) > 0 else 0.0
    p_value = float(np.mean(z1_boot <= z1))
    return {'stat': float(z1), 'p_value': p_value, 'n_violations': n_viol}

# Determine distribution type per model
DIST_MAP = {
    'GJR_N': 'normal',
    'GJR_t': 't',
    'EGARCH_t': 't',
    'A4f_N': 'normal',
    'A4f_t': 't',
    'HAR_ABS': 'normal',
}
if MACRO_OK:
    DIST_MAP['Macro_X'] = 't'

VAR_ALPHAS = [0.01, 0.025, 0.05]
ES_ALPHAS = [0.025]

var_es_results = {}
oos_returns = returns[oos_idx]

for m in MODEL_NAMES:
    h_oos = forecasts[m][oos_idx]
    sigma_oos = np.sqrt(np.maximum(h_oos, 1e-16))
    df_oos = df_estimates[m][oos_idx]
    dist = DIST_MAP[m]

    model_results = {}
    for alpha_val in VAR_ALPHAS:
        if dist == 'normal':
            var_series = var_normal(sigma_oos, alpha_val)
            es_series = es_normal(sigma_oos, alpha_val)
        else:
            # Use median df for VaR/ES if df varies
            median_df = np.nanmedian(df_oos)
            if np.isnan(median_df) or median_df <= 2.01:
                median_df = 8.0
            var_series = var_student_t(sigma_oos, alpha_val, median_df)
            es_series = es_student_t(sigma_oos, alpha_val, median_df)

        valid = ~np.isnan(var_series) & ~np.isnan(oos_returns)
        if valid.sum() < 100:
            continue

        violations = (oos_returns[valid] < var_series[valid]).astype(int)
        n_valid = int(valid.sum())

        uc = kupiec_uc_test(violations, n_valid, alpha_val)
        cc = christoffersen_cc_test(violations, n_valid, alpha_val)

        alpha_key = f"VaR_{alpha_val}"
        model_results[alpha_key] = {
            'violation_rate': uc['violation_rate'],
            'n_violations': uc['n_violations'],
            'n': n_valid,
            'UC_stat': uc['stat'], 'UC_p': uc['p_value'],
            'CC_stat': cc['stat_cc'], 'CC_p': cc['p_cc'],
            'UC_pass': uc['p_value'] > 0.05,
            'CC_pass': cc['p_cc'] > 0.05,
        }

        # ES backtest at 2.5%
        if alpha_val in ES_ALPHAS:
            if dist == 'normal':
                es_s = es_normal(sigma_oos[valid], alpha_val)
            else:
                es_s = es_student_t(sigma_oos[valid], alpha_val, median_df)
            var_s = var_series[valid]
            ret_v = oos_returns[valid]
            as_z1 = acerbi_szekely_z1(ret_v, es_s, var_s, alpha_val)
            model_results[f"ES_{alpha_val}"] = {
                'Z1_stat': as_z1['stat'],
                'Z1_p': as_z1['p_value'],
                'Z1_pass': as_z1['p_value'] > 0.05,
                'n_violations': as_z1['n_violations'],
            }

    var_es_results[m] = model_results

# Print VaR/ES summary
print("\n  VaR/ES Scorecard:")
print(f"  {'Model':12s} | {'VaR1%':>8s} | {'VaR2.5%':>8s} | {'VaR5%':>8s} | {'ES2.5%':>8s} | Score")
print("  " + "-" * 72)
scorecard = {}
for m in MODEL_NAMES:
    mr = var_es_results.get(m, {})
    score = 0
    total = 0
    parts = []
    for ak in ['VaR_0.01', 'VaR_0.025', 'VaR_0.05']:
        if ak in mr:
            total += 2  # UC + CC
            passed = 0
            if mr[ak]['UC_pass']:
                passed += 1; score += 1
            if mr[ak]['CC_pass']:
                passed += 1; score += 1
            vr = mr[ak]['violation_rate']
            parts.append(f"{vr:.3f}{'*' if passed==2 else ''}")
        else:
            parts.append("N/A")
    if 'ES_0.025' in mr:
        total += 1
        if mr['ES_0.025']['Z1_pass']:
            score += 1
        parts.append(f"{'P' if mr['ES_0.025']['Z1_pass'] else 'F'}")
    else:
        parts.append("N/A")
    scorecard[m] = {'score': score, 'total': total}
    print(f"  {m:12s} | {parts[0]:>8s} | {parts[1]:>8s} | {parts[2]:>8s} | {parts[3]:>8s} | {score}/{total}")

# ============================================================
# 11. COMPILE RESULTS
# ============================================================
print("\n[11] Compiling results...", flush=True)

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Unified 7-Model OOS Comparison Pipeline for Paper 5',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'config': {
        'data_source': 'yfinance (SPY, ^VIX) + FRED (GS10, TB3MS, UNRATE)',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'oos_start': OOS_START,
        'n_total': len(df),
        'n_oos': int(n_oos),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'seed': 42,
    },
    'models': MODEL_NAMES,
    'qlike_ranking': [{'model': m, 'qlike': qlike_scores[m],
                       'rank': i+1} for i, (m, _) in enumerate(ranked)],
    'dm_matrix': {},
    'mcs': {
        'significance': 0.10,
        'n_boot': 1000,
        'members': mcs_set,
    },
    'spearman': spearman_results,
    'var_es': {},
    'var_es_scorecard': scorecard,
    'runtime_seconds': time.time() - START_TIME,
}

# DM matrix as nested dict
for key, val in dm_matrix.items():
    results['dm_matrix'][key] = val

# VaR/ES - convert to JSON-safe
for m in MODEL_NAMES:
    mr = var_es_results.get(m, {})
    safe_mr = {}
    for k, v in mr.items():
        safe_mr[k] = {kk: (int(vv) if isinstance(vv, (np.integer, np.bool_)) else
                           float(vv) if isinstance(vv, (np.floating,)) else
                           bool(vv) if isinstance(vv, (bool, np.bool_)) else vv)
                      for kk, vv in v.items()}
    results['var_es'][m] = safe_mr

# Final parameter estimates (last refit)
param_summary = {}
for m in MODEL_NAMES:
    key_map = {
        'GJR_N': 'gjr_n', 'GJR_t': 'gjr_t', 'EGARCH_t': 'egarch_t',
        'A4f_N': 'a4f_n', 'A4f_t': 'a4f_t', 'HAR_ABS': 'har',
    }
    if MACRO_OK:
        key_map['Macro_X'] = 'macro_x'
    sk = key_map.get(m)
    if sk and sk in state:
        fit = state[sk]
        param_summary[m] = {
            'params': [float(x) for x in fit['params']],
            'converged': bool(fit['converged']),
        }
        if 'df' in fit:
            param_summary[m]['df'] = float(fit['df'])
        if 'nll' in fit:
            param_summary[m]['nll'] = float(fit['nll'])
results['parameter_summary'] = param_summary

# Save
results_path = os.path.join(SCRIPT_DIR, 'k1002_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")

# ============================================================
# 12. SUMMARY
# ============================================================
elapsed_total = time.time() - START_TIME
print(f"\n{'='*72}")
print(f"K1002 SUMMARY (runtime: {elapsed_total:.0f}s)")
print(f"{'='*72}")

print(f"\n  QLIKE Ranking:")
for item in results['qlike_ranking']:
    champion = " <-- CHAMPION" if item['rank'] == 1 else ""
    print(f"    {item['rank']}. {item['model']:12s}: {item['qlike']:.6f}{champion}")

print(f"\n  MCS Members (10%): {mcs_set}")

a4f_t_in_mcs = 'A4f_t' in mcs_set
print(f"\n  A4f-t in MCS: {'YES' if a4f_t_in_mcs else 'NO'}")

print(f"\n  Key DM tests (A4f_t vs others):")
for m in MODEL_NAMES:
    if m == 'A4f_t':
        continue
    # Find the DM result
    key1 = f"A4f_t_vs_{m}"
    key2 = f"{m}_vs_A4f_t"
    if key1 in dm_matrix:
        t_s = dm_matrix[key1]['t_stat']
        p_v = dm_matrix[key1]['p_val']
        winner = "A4f_t" if t_s < 0 else m
    elif key2 in dm_matrix:
        t_s = -dm_matrix[key2]['t_stat']
        p_v = dm_matrix[key2]['p_val']
        winner = "A4f_t" if t_s < 0 else m
    else:
        continue
    sig = "***" if abs(t_s) > 3.0 else ""
    print(f"    A4f_t vs {m:12s}: t={t_s:+6.2f}  {sig}  -> {winner}")

print(f"\n  VaR/ES Scorecard:")
for m in MODEL_NAMES:
    sc = scorecard.get(m, {})
    print(f"    {m:12s}: {sc.get('score',0)}/{sc.get('total',0)}")

print(f"\n  Total runtime: {elapsed_total:.0f}s")
print(f"\n  Done.")
