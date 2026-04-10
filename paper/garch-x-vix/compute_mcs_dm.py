#!/usr/bin/env python3
"""
MCS and Pairwise DM Tests for Paper 9 (GARCH-X VIX)
====================================================
Combines K988 (11 models) + K988b (6 additional models) = 17 total models.
Computes:
  1. Full pairwise DM matrix (136 pairs)
  2. Model Confidence Set (Hansen, Lunde & Nason 2011) at alpha=0.10 and 0.25
  3. Giacomini-White conditional predictive ability test for key pairs

Models:
  B0: GJR-GARCH(1,1) [benchmark]
  A1: K889-original (inconsistent tau)
  A2: consistent-tau_t (log-exp)
  A3: consistent-tau_{t-1} (log-exp)
  A4: VIX-squared (constrained omega)
  A5: VIX-level
  A2f: log-exp, free omega
  A4f: VIX^2, free omega [champion]
  A3f: tau_{t-1}, free omega
  A2n: log-exp, sample-normalized
  A4n: VIX^2, sample-normalized
  B1: MIDAS-RW K=22
  B2: MIDAS-RW K=65
  B3: MIDAS-RW K=125
  C1: MIDAS-FS K_m=6
  C2: MIDAS-FS K_m=12
  C3: MIDAS-FS K_m=24

References:
  Hansen, Lunde & Nason (2011). MCS. Econometrica 79(2):453-497.
  Diebold & Mariano (1995). J Business & Econ Stat 13(3):253-263.
  Giacomini & White (2006). Econometrica 74(6):1545-1578.
  Patton (2011). J Econometrics 160:246-256.
  Harvey et al. (2016). t>3.0 threshold.

Author: VolPred Research System
Date: 2026-04-10
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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

# Configuration — must match K988/K988b exactly
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print("MCS + Pairwise DM for Paper 9: 17-Model Horse Race")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
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
df['month'] = df.index.to_period('M')

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2
month_labels = df['month'].values

oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

# ============================================================
# 2. MODEL IMPLEMENTATIONS
# ============================================================
print("\n[2] Setting up models...")

# --- GJR-GARCH(1,1) ---
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
    best_ll, best_p = np.inf, None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except:
            pass
    return best_p

def gjr_1step(p, h, r):
    o, a, g, b = p
    asym = g * r**2 if r < 0 else 0.0
    return max(o + a * r**2 + asym + b * h, 1e-10)


# --- Multiplicative GARCH-X ---
def fit_mfgjr_x(returns, log_vix_vals, vix_vals, tau_func='log_exp',
                denom_mode='tau_t', free_omega=False, sample_norm=False):
    n = len(returns)
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)

    r2_pos = np.maximum(returns**2, 1e-16)
    log_r2 = np.log(r2_pos)

    if tau_func == 'log_exp':
        X = np.column_stack([np.ones(n), log_vix_lag])
    elif tau_func == 'vix_level':
        X = np.column_stack([np.ones(n), vix_lag])
    elif tau_func == 'vix_squared':
        X = np.column_stack([np.ones(n), vix_lag**2])
    theta_init = np.linalg.lstsq(X, log_r2, rcond=None)[0]

    def neg_loglik(params):
        if free_omega:
            if tau_func == 'vix_squared':
                th0, th1, omg, alp, gam, bet = params
                tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
            elif tau_func == 'vix_level':
                th0, th1, omg, alp, gam, bet = params
                tau = np.maximum(np.exp(th0 + th1 * vix_lag), 1e-16)
            else:
                th0, th1, omg, alp, gam, bet = params
                tau = np.maximum(np.exp(th0 + th1 * log_vix_lag), 1e-16)
        else:
            if tau_func == 'vix_squared':
                th0, th1, alp, gam, bet = params
                tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
            elif tau_func == 'vix_level':
                th0, th1, alp, gam, bet = params
                tau = np.maximum(np.exp(th0 + th1 * vix_lag), 1e-16)
            else:
                th0, th1, alp, gam, bet = params
                tau = np.maximum(np.exp(th0 + th1 * log_vix_lag), 1e-16)
            omg = None

        if free_omega:
            if omg <= 0: return 1e10
            alp_v, gam_v, bet_v = alp, gam, bet
        else:
            alp_v, gam_v, bet_v = alp, gam, bet

        if alp_v < 0 or gam_v < 0 or bet_v < 0: return 1e10
        persist = alp_v + gam_v/2.0 + bet_v
        if persist >= 1.0: return 1e10

        if free_omega:
            omega_g = omg
        else:
            omega_g = 1.0 - persist
            if omega_g <= 0: return 1e10

        # Sample-mean normalization
        if sample_norm:
            if denom_mode == 'tau_t':
                mean_r2_over_tau = np.mean(returns[:-1]**2 / tau[1:])
            else:
                mean_r2_over_tau = np.mean(returns[:-1]**2 / tau[:-1])
            norm_factor = np.sqrt(max(mean_r2_over_tau, 1e-16))
        else:
            norm_factor = 1.0

        eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
        g = np.empty(n)
        g[0] = eg if free_omega else 1.0
        ll = 0.0

        for t in range(1, n):
            if denom_mode == 'tau_t':
                u_prev = (returns[t-1] / np.sqrt(tau[t])) / norm_factor
            else:
                u_prev = (returns[t-1] / np.sqrt(tau[t-1])) / norm_factor
            asym = gam_v * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alp_v * u_prev**2 + asym + bet_v * g[t-1]
            if g[t] < 1e-10: g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sample_norm:
                sigma2 *= mean_r2_over_tau
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    best_ll, best_p = np.inf, None

    if free_omega:
        if tau_func == 'vix_squared':
            var0 = np.var(returns); vm = np.mean(vix_lag**2)+1e-8
            starts = [[var0*0.1,var0/vm,0.05,0.05,0.05,0.90],
                       [var0*0.05,var0/vm*0.5,0.10,0.03,0.08,0.88],
                       [var0*0.2,var0/vm*1.5,0.02,0.08,0.10,0.80]]
            bounds = [(-1e-2,1e-2),(1e-8,1e-3),(1e-6,1.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
        else:
            starts = [[theta_init[0],theta_init[1],0.05,0.05,0.05,0.90],
                       [theta_init[0],theta_init[1],0.10,0.03,0.08,0.88],
                       [theta_init[0],theta_init[1],0.02,0.08,0.10,0.80]]
            bounds = [(-20,0),(0.1,5.0),(1e-6,1.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
    else:
        if tau_func == 'vix_squared':
            var0 = np.var(returns); vm = np.mean(vix_lag**2)+1e-8
            starts = [[var0*0.1,var0/vm,0.05,0.05,0.90],
                       [var0*0.05,var0/vm*0.5,0.03,0.08,0.88],
                       [var0*0.2,var0/vm*1.5,0.08,0.10,0.80]]
            bounds = [(-1e-2,1e-2),(1e-8,1e-3),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
        elif tau_func == 'vix_level':
            starts = [[theta_init[0],theta_init[1],0.05,0.05,0.90],
                       [theta_init[0],theta_init[1],0.03,0.08,0.88],
                       [theta_init[0],theta_init[1],0.08,0.10,0.80]]
            bounds = [(-20,0),(0.01,1.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
        else:
            starts = [[theta_init[0],theta_init[1],0.05,0.05,0.90],
                       [theta_init[0],theta_init[1],0.03,0.08,0.88],
                       [theta_init[0],theta_init[1],0.08,0.10,0.80]]
            bounds = [(-20,0),(0.1,5.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]

    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except:
            pass
    return best_p


def compute_tau(params, log_vix_lag, vix_lag, tau_func):
    th0, th1 = params[0], params[1]
    if tau_func == 'log_exp':
        return np.maximum(np.exp(th0 + th1 * log_vix_lag), 1e-16)
    elif tau_func == 'vix_level':
        return np.maximum(np.exp(th0 + th1 * vix_lag), 1e-16)
    elif tau_func == 'vix_squared':
        return np.maximum(th0 + th1 * vix_lag**2, 1e-16)


# --- GARCH-MIDAS Rolling Window ---
def beta_weights(K, omega1, omega2):
    k_vals = np.arange(1, K + 1, dtype=np.float64) / K
    raw = k_vals**(omega1 - 1) * (1 - k_vals)**(omega2 - 1)
    raw_sum = raw.sum()
    if raw_sum < 1e-16:
        return np.ones(K) / K
    return raw / raw_sum


def fit_garch_midas_vix(returns, vix_vals, K_midas):
    """GARCH-MIDAS(VIX) rolling window."""
    n = len(returns)
    log_vix_v = np.log(np.maximum(vix_vals, 1.0))
    valid_start = K_midas
    n_valid = n - valid_start
    if n_valid < 500:
        return None, valid_start

    vix_lags = np.empty((n_valid, K_midas))
    for k in range(K_midas):
        vix_lags[:, k] = log_vix_v[valid_start - 1 - k:n - 1 - k]
    ret_valid = returns[valid_start:]

    def neg_loglik(params):
        m_p, theta, alpha, gamma_p, beta_g, omega1, omega2 = params
        if omega1 < 1.0 or omega2 < 1.0: return 1e10
        if alpha < 0 or gamma_p < 0 or beta_g < 0: return 1e10
        omega_g = 1.0 - alpha - gamma_p / 2.0 - beta_g
        if omega_g <= 0 or alpha + gamma_p / 2.0 + beta_g >= 1.0: return 1e10

        weights = beta_weights(K_midas, omega1, omega2)
        midas_component = vix_lags @ weights
        log_tau = m_p + theta * midas_component
        tau = np.maximum(np.exp(log_tau), 1e-16)

        g = np.empty(n_valid)
        g[0] = 1.0
        ll = 0.0
        for t in range(1, n_valid):
            u_prev = ret_valid[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta_g * g[t-1]
            if g[t] < 1e-10: g[t] = 1e-10
        for t in range(n_valid):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + ret_valid[t]**2 / sigma2)
        return -ll

    best_ll, best_p = np.inf, None
    starts = [[-10.0,1.0,0.05,0.05,0.90,1.5,2.0],
              [-8.0,0.5,0.03,0.08,0.88,1.0,5.0],
              [-12.0,1.5,0.08,0.10,0.80,2.0,3.0]]
    bounds = [(-20,0),(0.01,5.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999),(1.0,20.0),(1.0,20.0)]
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except:
            pass
    return best_p, valid_start


# --- GARCH-MIDAS Fixed-Span ---
def fit_garch_midas_fixed_span(returns, vix_vals, month_labels_arr, K_months):
    df_temp = pd.DataFrame({'log_vix': np.log(np.maximum(vix_vals, 1.0)),
                            'month': month_labels_arr})
    monthly_vix = df_temp.groupby('month')['log_vix'].mean()
    unique_months = monthly_vix.index.tolist()
    month_to_idx = {m: i for i, m in enumerate(unique_months)}

    n = len(returns)
    day_month_idx = np.array([month_to_idx[m] for m in month_labels_arr])

    valid_start_month = K_months
    if valid_start_month >= len(unique_months):
        return None, 0

    valid_start_day = 0
    for i in range(n):
        if day_month_idx[i] >= valid_start_month:
            valid_start_day = i
            break

    n_valid = n - valid_start_day
    if n_valid < 500:
        return None, valid_start_day

    monthly_vix_arr = monthly_vix.values

    def neg_loglik(params):
        m_p, theta_p, alpha, gamma_p, beta_g, w1, w2 = params
        if w1 < 1.0 or w2 < 1.0: return 1e10
        if alpha < 0 or gamma_p < 0 or beta_g < 0: return 1e10
        omega_g = 1.0 - alpha - gamma_p/2.0 - beta_g
        if omega_g <= 0 or alpha + gamma_p/2.0 + beta_g >= 1.0: return 1e10

        weights = beta_weights(K_months, w1, w2)
        n_months = len(unique_months)
        tau_monthly = np.empty(n_months)
        for mi in range(n_months):
            if mi < K_months:
                tau_monthly[mi] = np.exp(m_p)
            else:
                midas_sum = sum(weights[k] * monthly_vix_arr[mi-1-k] for k in range(K_months))
                tau_monthly[mi] = max(np.exp(m_p + theta_p * midas_sum), 1e-16)

        g = 1.0
        ll = 0.0
        for i in range(valid_start_day, n):
            mi = day_month_idx[i]
            tau_t = tau_monthly[mi]
            if i > valid_start_day:
                u_prev = returns[i-1] / np.sqrt(tau_t)
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha * u_prev**2 + asym + beta_g * g
                g = max(g, 1e-10)
            sigma2 = tau_t * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[i]**2 / sigma2)
        return -ll

    best_ll, best_p = np.inf, None
    starts = [[-10.0,1.0,0.05,0.05,0.90,1.5,2.0],
              [-8.0,0.5,0.03,0.08,0.88,1.0,5.0],
              [-12.0,1.5,0.08,0.10,0.80,2.0,3.0]]
    bounds = [(-20,0),(0.01,5.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999),(1.0,20.0),(1.0,20.0)]
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except:
            pass
    return best_p, valid_start_day


# ============================================================
# 3. ALL 17 MODELS — CONFIGURATION
# ============================================================

# Complete model list
ALL_MODELS = [
    'B0_GJR',
    # Part A: GARCH-X daily (from K988)
    'A1_K889_original',
    'A2_consistent_tau_t',
    'A3_consistent_tau_t1',
    'A4_vix_squared',
    'A5_vix_level',
    'A2f_free_omega',
    'A4f_vix2_free_omega',
    # Part A supplement (from K988b)
    'A3f_tau_t1_free_omega',
    'A2n_logexp_samplenorm',
    'A4n_vix2_samplenorm',
    # Part B: MIDAS rolling window (from K988)
    'B1_MIDAS_K22',
    'B2_MIDAS_K65',
    'B3_MIDAS_K125',
    # Part C: MIDAS fixed-span (from K988b)
    'C1_MIDAS_FS_K6',
    'C2_MIDAS_FS_K12',
    'C3_MIDAS_FS_K24',
]

# MF-X configs: (tau_func, denom_mode, free_omega, sample_norm)
MFX_CONFIGS = {
    'A1_K889_original':       ('log_exp', 'tau_t_minus_1', False, False),  # est uses tau_t, OOS uses tau_{t-1}
    'A2_consistent_tau_t':    ('log_exp', 'tau_t', False, False),
    'A3_consistent_tau_t1':   ('log_exp', 'tau_t_minus_1', False, False),
    'A4_vix_squared':         ('vix_squared', 'tau_t', False, False),
    'A5_vix_level':           ('vix_level', 'tau_t', False, False),
    'A2f_free_omega':         ('log_exp', 'tau_t', True, False),
    'A4f_vix2_free_omega':    ('vix_squared', 'tau_t', True, False),
    'A3f_tau_t1_free_omega':  ('log_exp', 'tau_t_minus_1', True, False),
    'A2n_logexp_samplenorm':  ('log_exp', 'tau_t', False, True),
    'A4n_vix2_samplenorm':    ('vix_squared', 'tau_t', False, True),
}

MIDAS_RW_CONFIGS = {
    'B1_MIDAS_K22': 22,
    'B2_MIDAS_K65': 65,
    'B3_MIDAS_K125': 125,
}

MIDAS_FS_CONFIGS = {
    'C1_MIDAS_FS_K6': 6,
    'C2_MIDAS_FS_K12': 12,
    'C3_MIDAS_FS_K24': 24,
}

# ============================================================
# 4. OOS FORECASTING (all 17 models in one pass)
# ============================================================
print("\n[3] Out-of-sample forecasting (all 17 models)...")

forecasts = {name: np.full(n_oos, np.nan) for name in ALL_MODELS}
states = {}
for name in ALL_MODELS:
    states[name] = {'h': None, 'g': None, 'tau_prev': None, 'params': None, 'norm_factor': 1.0}

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        ts = max(0, abs_idx - WINDOW)
        tr_ret = ret[ts:abs_idx]
        tr_log_vix = log_vix[ts:abs_idx]
        tr_vix = vix[ts:abs_idx]
        tr_months = month_labels[ts:abs_idx]

        # B0: GJR
        gjr_p = fit_gjr(tr_ret)
        if gjr_p is not None:
            states['B0_GJR']['params'] = gjr_p
            h = np.var(tr_ret)
            for i in range(1, len(tr_ret)):
                h = gjr_1step(gjr_p, h, tr_ret[i-1])
            states['B0_GJR']['h'] = h

        # MF-X models (A1-A5, A2f, A4f, A3f, A2n, A4n)
        for name, (tf, dm, fo, sn) in MFX_CONFIGS.items():
            # A1 special: estimation uses tau_t, OOS uses tau_{t-1}
            est_denom = 'tau_t' if name == 'A1_K889_original' else dm
            p = fit_mfgjr_x(tr_ret, tr_log_vix, tr_vix,
                            tau_func=tf, denom_mode=est_denom,
                            free_omega=fo, sample_norm=sn)
            if p is not None:
                states[name]['params'] = p
                th0, th1 = p[0], p[1]
                if fo:
                    omg, alp, gam, bet = p[2], p[3], p[4], p[5]
                else:
                    alp, gam, bet = p[2], p[3], p[4]
                    omg = 1.0 - alp - gam/2.0 - bet

                nt = len(tr_ret)
                lv_lag = np.empty(nt); lv_lag[0] = tr_log_vix[0]; lv_lag[1:] = tr_log_vix[:-1]
                v_lag = np.exp(lv_lag)
                tau_tr = compute_tau(p, lv_lag, v_lag, tf)

                # Normalization factor for sample-norm models
                nf = 1.0
                if sn:
                    if est_denom == 'tau_t':
                        mean_r2_tau = np.mean(tr_ret[:-1]**2 / tau_tr[1:])
                    else:
                        mean_r2_tau = np.mean(tr_ret[:-1]**2 / tau_tr[:-1])
                    nf = np.sqrt(max(mean_r2_tau, 1e-16))
                states[name]['norm_factor'] = nf

                persist = alp + gam/2.0 + bet
                eg = omg / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg if fo else 1.0
                for i in range(1, nt):
                    if est_denom == 'tau_t':
                        u = (tr_ret[i-1] / np.sqrt(max(tau_tr[i], 1e-16))) / nf
                    else:
                        u = (tr_ret[i-1] / np.sqrt(max(tau_tr[i-1], 1e-16))) / nf
                    asym = gam * u**2 if u < 0 else 0.0
                    g = omg + alp * u**2 + asym + bet * g
                    g = max(g, 1e-10)
                states[name]['g'] = g
                states[name]['tau_prev'] = tau_tr[-1]

        # MIDAS-RW models (B1-B3)
        for name, K_m in MIDAS_RW_CONFIGS.items():
            if len(tr_ret) > K_m + 100:
                p, valid_start = fit_garch_midas_vix(tr_ret, tr_vix, K_m)
                if p is not None:
                    states[name]['params'] = p
                    m_p, theta_p = p[0], p[1]
                    alp, gam, bet = p[2], p[3], p[4]
                    w1, w2 = p[5], p[6]
                    omega_g = 1.0 - alp - gam/2.0 - bet
                    weights = beta_weights(K_m, w1, w2)
                    log_vix_tr = np.log(np.maximum(tr_vix, 1.0))

                    g = 1.0; tau_last = None
                    for i in range(valid_start, len(tr_ret)):
                        midas_sum = sum(weights[k] * log_vix_tr[i-1-k]
                                       for k in range(K_m) if i-1-k >= 0)
                        tau_i = max(np.exp(m_p + theta_p * midas_sum), 1e-16)
                        if i > valid_start:
                            u = tr_ret[i-1] / np.sqrt(tau_i)
                            asym = gam * u**2 if u < 0 else 0.0
                            g = omega_g + alp * u**2 + asym + bet * g
                            g = max(g, 1e-10)
                        tau_last = tau_i
                    states[name]['g'] = g
                    states[name]['tau_prev'] = tau_last

        # MIDAS-FS models (C1-C3)
        for name, K_m in MIDAS_FS_CONFIGS.items():
            p, vs = fit_garch_midas_fixed_span(tr_ret, tr_vix, tr_months, K_m)
            if p is not None:
                states[name]['params'] = p
                m_p, theta_p = p[0], p[1]
                alp, gam, bet = p[2], p[3], p[4]
                w1, w2 = p[5], p[6]
                omg = 1.0 - alp - gam/2.0 - bet
                weights = beta_weights(K_m, w1, w2)

                df_tr = pd.DataFrame({'lv': np.log(np.maximum(tr_vix, 1.0)), 'mo': tr_months})
                mo_avg = df_tr.groupby('mo')['lv'].mean()
                mo_arr = mo_avg.values
                mo_list = mo_avg.index.tolist()
                mo_map = {m: i for i, m in enumerate(mo_list)}

                g = 1.0
                tau_i = np.exp(m_p)
                for i in range(vs, len(tr_ret)):
                    mi = mo_map.get(tr_months[i], 0)
                    if mi >= K_m:
                        ms = sum(weights[k] * mo_arr[mi-1-k] for k in range(K_m) if mi-1-k >= 0)
                        tau_i = max(np.exp(m_p + theta_p * ms), 1e-16)
                    else:
                        tau_i = max(np.exp(m_p), 1e-16)
                    if i > vs:
                        u = tr_ret[i-1] / np.sqrt(tau_i)
                        asym = gam * u**2 if u < 0 else 0.0
                        g = omg + alp * u**2 + asym + bet * g
                        g = max(g, 1e-10)
                states[name]['g'] = g
                states[name]['tau_prev'] = tau_i

    # --- Generate forecasts ---

    # B0: GJR
    p = states['B0_GJR']['params']
    if p is not None:
        h = states['B0_GJR']['h']
        h = gjr_1step(p, h, ret[abs_idx-1])
        forecasts['B0_GJR'][t_idx] = h
        states['B0_GJR']['h'] = h

    # MF-X models
    for name, (tf, dm, fo, sn) in MFX_CONFIGS.items():
        p = states[name]['params']
        if p is None:
            continue

        th0, th1 = p[0], p[1]
        if fo:
            omg, alp, gam, bet = p[2], p[3], p[4], p[5]
        else:
            alp, gam, bet = p[2], p[3], p[4]
            omg = 1.0 - alp - gam/2.0 - bet

        lv_l = log_vix[abs_idx-1]
        v_l = vix[abs_idx-1]
        tau_t = compute_tau(p, lv_l, v_l, tf)
        if isinstance(tau_t, np.ndarray):
            tau_t = float(tau_t.flat[0])

        r_prev = ret[abs_idx-1]
        g_prev = states[name]['g']
        tau_prev = states[name]['tau_prev']
        nf = states[name]['norm_factor']

        # A1 special: OOS uses tau_{t-1} as denominator
        if name == 'A1_K889_original':
            u = r_prev / np.sqrt(max(tau_prev, 1e-16))
        elif dm == 'tau_t':
            u = (r_prev / np.sqrt(max(tau_t, 1e-16))) / nf
        else:
            u = (r_prev / np.sqrt(max(tau_prev, 1e-16))) / nf

        asym = gam * u**2 if u < 0 else 0.0
        g_new = omg + alp * u**2 + asym + bet * g_prev
        g_new = max(g_new, 1e-10)

        fc = tau_t * g_new
        if sn:
            fc *= nf**2
        forecasts[name][t_idx] = fc
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t

    # MIDAS-RW models
    for name, K_m in MIDAS_RW_CONFIGS.items():
        p = states[name]['params']
        if p is None:
            continue
        m_p, theta_p = p[0], p[1]
        alp, gam, bet = p[2], p[3], p[4]
        w1, w2 = p[5], p[6]
        omega_g = 1.0 - alp - gam/2.0 - bet
        weights = beta_weights(K_m, w1, w2)

        log_vix_history = []
        for k in range(K_m):
            idx_k = abs_idx - 1 - k
            if idx_k >= 0:
                log_vix_history.append(log_vix[idx_k])
            else:
                log_vix_history.append(log_vix[0])
        midas_sum = sum(weights[k] * log_vix_history[k] for k in range(K_m))
        tau_t = max(np.exp(m_p + theta_p * midas_sum), 1e-16)

        r_prev = ret[abs_idx-1]
        g_prev = states[name]['g']
        u = r_prev / np.sqrt(tau_t)
        asym = gam * u**2 if u < 0 else 0.0
        g_new = omega_g + alp * u**2 + asym + bet * g_prev
        g_new = max(g_new, 1e-10)

        forecasts[name][t_idx] = tau_t * g_new
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t

    # MIDAS-FS models
    for name, K_m in MIDAS_FS_CONFIGS.items():
        p = states[name]['params']
        if p is None:
            continue
        m_p, theta_p = p[0], p[1]
        alp, gam, bet = p[2], p[3], p[4]
        w1, w2 = p[5], p[6]
        omg = 1.0 - alp - gam/2.0 - bet
        weights = beta_weights(K_m, w1, w2)

        current_month = month_labels[abs_idx]
        df_hist = pd.DataFrame({'lv': np.log(np.maximum(vix[:abs_idx], 1.0)),
                                'mo': month_labels[:abs_idx]})
        mo_avg = df_hist.groupby('mo')['lv'].mean()
        mo_list = mo_avg.index.tolist()
        if current_month in mo_list:
            mi = mo_list.index(current_month)
        else:
            mi = len(mo_list)

        if mi >= K_m:
            ms = sum(weights[k] * mo_avg.iloc[mi-1-k] for k in range(K_m) if mi-1-k >= 0)
            tau_t = max(np.exp(m_p + theta_p * ms), 1e-16)
        else:
            tau_t = max(np.exp(m_p), 1e-16)

        r_prev = ret[abs_idx-1]
        g_prev = states[name]['g']
        u = r_prev / np.sqrt(tau_t)
        asym = gam * u**2 if u < 0 else 0.0
        g_new = omg + alp * u**2 + asym + bet * g_prev
        g_new = max(g_new, 1e-10)

        forecasts[name][t_idx] = tau_t * g_new
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t

elapsed = time.time() - START_TIME
print(f"  Forecasting complete: {elapsed:.0f}s, {refit_count} refits")


# ============================================================
# 5. COMPUTE DAILY QLIKE LOSSES
# ============================================================
print("\n[4] Computing daily QLIKE losses...")

oos_r2 = r2[oos_indices]
qlike_losses = {}

for name in ALL_MODELS:
    fc = forecasts[name]
    valid = ~np.isnan(fc) & (fc > 0)
    n_valid = valid.sum()
    # Pointwise QLIKE: log(h) + r2/h
    pw = np.full(n_oos, np.nan)
    pw[valid] = np.log(fc[valid]) + oos_r2[valid] / fc[valid]
    qlike_losses[name] = pw
    mean_ql = np.nanmean(pw)
    print(f"  {name:<25} QLIKE={mean_ql:.4f}  n_valid={n_valid}")


# ============================================================
# 6. PAIRWISE DM TESTS (full 136 pairs)
# ============================================================
print("\n[5] Pairwise DM tests (Newey-West HAC, Harvey t>3.0)...")

def dm_test_nw(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t = model 1 better."""
    d = loss1 - loss2
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 50:
        return 0.0, 1.0

    d_mean = np.mean(d)
    max_lag = max(1, int(np.floor(n ** (1/3))))
    gamma0 = np.var(d, ddof=0)
    var_d = gamma0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        var_d += 2 * w_j * gamma_j

    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


dm_matrix = {}
dm_table = []

print(f"\n  {'Model_1':<25} {'Model_2':<25} {'DM t':>8} {'p':>8} {'Winner':<25} {'Sig':>4}")
print(f"  {'-'*25} {'-'*25} {'-'*8} {'-'*8} {'-'*25} {'-'*4}")

for i, m1 in enumerate(ALL_MODELS):
    for j, m2 in enumerate(ALL_MODELS):
        if i >= j:
            continue
        t_stat, p_val = dm_test_nw(qlike_losses[m1], qlike_losses[m2])
        winner = m1 if t_stat < 0 else m2
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.96 else ""))
        key = f"{m1}_vs_{m2}"
        dm_matrix[key] = {
            't_stat': t_stat,
            'p_val': p_val,
            'winner': winner,
            'significant_harvey': abs(t_stat) > 3.0,
            'significant_5pct': abs(t_stat) > 1.96,
        }
        dm_table.append({
            'model_1': m1,
            'model_2': m2,
            't_stat': t_stat,
            'p_val': p_val,
            'winner': winner,
        })

        # Print only notable pairs (vs GJR or involving A4f)
        if m1 == 'B0_GJR' or m2 == 'B0_GJR' or 'A4f' in m1 or 'A4f' in m2:
            print(f"  {m1:<25} {m2:<25} {t_stat:>+8.3f} {p_val:>8.4f} {winner:<25} {sig:>4}")


# ============================================================
# 7. MODEL CONFIDENCE SET (Hansen, Lunde & Nason 2011)
# ============================================================
print("\n[6] Model Confidence Set...")

def compute_mcs(losses_dict, alpha=0.10, n_boot=1000, block_size=None):
    """
    Bootstrap MCS implementation (T_max statistic).
    losses_dict: {model_name: array of pointwise losses}
    Returns: (surviving_models, elimination_order)
    """
    models = list(losses_dict.keys())
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
    elimination_order = []

    while len(surviving) > 1:
        sub_loss = loss_mat[:, surviving]
        m_sub = len(surviving)

        # Pairwise loss differentials
        d_bar = np.zeros((m_sub, m_sub))
        for ii in range(m_sub):
            for jj in range(ii+1, m_sub):
                d = sub_loss[:, ii] - sub_loss[:, jj]
                d_bar[ii, jj] = np.mean(d)
                d_bar[jj, ii] = -d_bar[ii, jj]

        # t_max statistic
        t_stats = np.zeros((m_sub, m_sub))
        for ii in range(m_sub):
            for jj in range(ii+1, m_sub):
                d = sub_loss[:, ii] - sub_loss[:, jj]
                var_d = np.var(d, ddof=1) / T
                if var_d > 0:
                    t_stats[ii, jj] = abs(np.mean(d)) / np.sqrt(var_d)
                    t_stats[jj, ii] = t_stats[ii, jj]

        t_max_obs = np.max(t_stats)

        # Block bootstrap
        n_blocks = int(np.ceil(T / block_size))
        boot_t_max = np.zeros(n_boot)
        for b in range(n_boot):
            block_starts = rng.integers(0, T - block_size + 1, size=n_blocks)
            idx = np.concatenate([np.arange(s, min(s + block_size, T)) for s in block_starts])[:T]
            boot_loss = sub_loss[idx]
            boot_t_max_val = 0.0
            for ii in range(m_sub):
                for jj in range(ii+1, m_sub):
                    d_b = boot_loss[:, ii] - boot_loss[:, jj]
                    d_centered = d_b - np.mean(sub_loss[:, ii] - sub_loss[:, jj])
                    var_b = np.var(d_centered, ddof=1) / T
                    if var_b > 0:
                        t_b = abs(np.mean(d_centered)) / np.sqrt(var_b)
                        boot_t_max_val = max(boot_t_max_val, t_b)
            boot_t_max[b] = boot_t_max_val

        p_val = np.mean(boot_t_max >= t_max_obs)

        if p_val >= alpha:
            break  # Cannot reject: current set is the MCS

        # Eliminate worst model (highest average loss)
        avg_loss = np.mean(sub_loss, axis=0)
        worst_idx = np.argmax(avg_loss)
        eliminated = models[surviving[worst_idx]]
        elimination_order.append({
            'model': eliminated,
            'p_value': float(p_val),
            'avg_qlike': float(np.mean(loss_mat[:, surviving[worst_idx]])),
        })
        surviving.pop(worst_idx)

    mcs_models = [models[i] for i in surviving]
    return mcs_models, elimination_order


# MCS at alpha=0.10
print("  Computing MCS (alpha=0.10, 1000 bootstrap)...")
mcs_10, elim_10 = compute_mcs(qlike_losses, alpha=0.10, n_boot=1000)
print(f"  MCS (alpha=0.10): {mcs_10}")
print(f"  Elimination order:")
for e in elim_10:
    print(f"    Eliminated {e['model']:<25} (p={e['p_value']:.4f}, avg QLIKE={e['avg_qlike']:.4f})")

# MCS at alpha=0.25
print("\n  Computing MCS (alpha=0.25, 1000 bootstrap)...")
mcs_25, elim_25 = compute_mcs(qlike_losses, alpha=0.25, n_boot=1000)
print(f"  MCS (alpha=0.25): {mcs_25}")


# ============================================================
# 8. GIACOMINI-WHITE CONDITIONAL PREDICTIVE ABILITY TEST
# ============================================================
print("\n[7] Giacomini-White tests for key pairs...")

def gw_test(loss1, loss2, instruments=None):
    """
    Giacomini-White (2006) conditional predictive ability test.
    Tests whether the forecast loss differential is conditionally zero.
    Uses h_t = [1, d_{t-1}] as default instruments.
    Returns (chi2_stat, p_value, df).
    """
    d = loss1 - loss2
    valid = np.isfinite(d)
    d = d[valid]
    T = len(d)
    if T < 50:
        return np.nan, np.nan, 0

    if instruments is None:
        # Default: constant + lagged loss differential
        h = np.column_stack([np.ones(T-1), d[:-1]])
        d_curr = d[1:]
    else:
        h = instruments
        d_curr = d

    q = h.shape[1]
    T_eff = len(d_curr)

    # OLS of d_t on h_t
    hd = h * d_curr[:, np.newaxis]  # h_t * d_t
    hd_mean = np.mean(hd, axis=0)

    # HAC covariance (Newey-West)
    max_lag = max(1, int(T_eff ** (1/3)))
    S = np.zeros((q, q))
    hd_centered = hd - hd_mean
    for lag in range(0, max_lag + 1):
        if lag == 0:
            Gamma = hd_centered.T @ hd_centered / T_eff
        else:
            Gamma = hd_centered[lag:].T @ hd_centered[:-lag] / T_eff
        weight = 1.0 if lag == 0 else (1 - lag / (max_lag + 1))
        S += weight * (Gamma + Gamma.T) if lag > 0 else weight * Gamma

    try:
        S_inv = np.linalg.inv(S)
    except np.linalg.LinAlgError:
        return np.nan, np.nan, q

    chi2_stat = float(T_eff * hd_mean @ S_inv @ hd_mean)
    p_val = float(1 - stats.chi2.cdf(chi2_stat, df=q))
    return chi2_stat, p_val, q


gw_results = {}
gw_pairs = [
    ('A4f_vix2_free_omega', 'B0_GJR', 'A4f vs GJR'),
    ('A4f_vix2_free_omega', 'B1_MIDAS_K22', 'A4f vs MIDAS-RW-K22'),
    ('A4f_vix2_free_omega', 'A2_consistent_tau_t', 'A4f vs A2'),
    ('A4f_vix2_free_omega', 'A4_vix_squared', 'A4f vs A4'),
    ('A2_consistent_tau_t', 'B1_MIDAS_K22', 'A2 vs MIDAS-RW-K22'),
    ('A4f_vix2_free_omega', 'C1_MIDAS_FS_K6', 'A4f vs MIDAS-FS-K6'),
]

print(f"\n  {'Pair':<30} {'GW chi2':>10} {'p-value':>10} {'df':>4} {'Sig':>5}")
print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*4} {'-'*5}")

for m1, m2, desc in gw_pairs:
    chi2_stat, p_val, df = gw_test(qlike_losses[m1], qlike_losses[m2])
    sig = "YES" if p_val < 0.05 else "No"
    gw_results[f"{m1}_vs_{m2}"] = {
        'chi2_stat': chi2_stat,
        'p_value': p_val,
        'df': df,
        'significant_5pct': bool(p_val < 0.05) if not np.isnan(p_val) else False,
        'description': desc,
    }
    print(f"  {desc:<30} {chi2_stat:>10.3f} {p_val:>10.4f} {df:>4} {sig:>5}")


# ============================================================
# 9. VERIFY MIDAS-FS DM NUMBERS (H1 fix)
# ============================================================
print("\n[8] Verifying MIDAS-FS DM statistics...")

# Check C1, C2, C3 vs B0_GJR
for name in ['C1_MIDAS_FS_K6', 'C2_MIDAS_FS_K12', 'C3_MIDAS_FS_K24']:
    key_fwd = f"B0_GJR_vs_{name}"
    key_rev = f"{name}_vs_B0_GJR"  # may not exist if we only compute i<j
    # Find in dm_matrix
    found = False
    for k, v in dm_matrix.items():
        if name in k and 'B0_GJR' in k:
            t = v['t_stat']
            # Convention: positive t means model2 (larger index) is better
            # For B0_GJR vs Cx: positive t means Cx better (since B0 is index 0, Cx is higher)
            print(f"  {name}: DM t = {t:+.4f} (vs B0_GJR)")
            print(f"    K988b reported: C1={2.8486:.4f}, C2={1.7109:.4f}, C3={2.1889:.4f}")
            found = True
            break
    if not found:
        print(f"  {name}: not found in DM matrix")


# ============================================================
# 10. QLIKE RANKING TABLE
# ============================================================
print("\n[9] Final QLIKE Ranking:")
rankings = []
for name in ALL_MODELS:
    fc = forecasts[name]
    valid = ~np.isnan(fc) & (fc > 0)
    n_valid = valid.sum()
    mean_ql = np.nanmean(qlike_losses[name])
    rankings.append((name, mean_ql, int(n_valid)))

rankings.sort(key=lambda x: x[1])  # lower QLIKE = better
print(f"\n  {'Rank':>4} {'Model':<25} {'QLIKE':>10} {'n':>6}")
print(f"  {'-'*4} {'-'*25} {'-'*10} {'-'*6}")
for rank, (name, ql, n_v) in enumerate(rankings, 1):
    marker = " ***" if name == 'A4f_vix2_free_omega' else ""
    print(f"  {rank:>4} {name:<25} {ql:>10.4f} {n_v:>6}{marker}")


# ============================================================
# 11. SAVE RESULTS
# ============================================================
print("\n[10] Saving results...")

# A4f pairwise DM summary
a4f_dm = {}
for k, v in dm_matrix.items():
    if 'A4f' in k:
        a4f_dm[k] = v

results = {
    'metadata': {
        'script': 'compute_mcs_dm.py',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'n_oos': int(n_oos),
        'n_refits': int(refit_count),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'elapsed_seconds': time.time() - START_TIME,
        'references': [
            'Hansen, Lunde & Nason (2011). The Model Confidence Set. Econometrica 79(2):453-497.',
            'Diebold & Mariano (1995). Comparing Predictive Accuracy. JBES 13(3):253-263.',
            'Giacomini & White (2006). Tests of Conditional Predictive Ability. Econometrica 74(6):1545-1578.',
            'Patton (2011). Volatility Forecast Comparison. J Econometrics 160:246-256.',
            'Harvey, Leybourne & Newbold (2016). Testing the equality of prediction MSEs. t>3.0.',
        ],
    },
    'qlike_ranking': [
        {'rank': rank, 'model': name, 'qlike': ql, 'n_valid': n_v}
        for rank, (name, ql, n_v) in enumerate(rankings, 1)
    ],
    'mcs': {
        'alpha_0.10': {
            'members': mcs_10,
            'n_members': len(mcs_10),
            'n_boot': 1000,
            'elimination_order': elim_10,
        },
        'alpha_0.25': {
            'members': mcs_25,
            'n_members': len(mcs_25),
            'n_boot': 1000,
            'elimination_order': elim_25,
        },
    },
    'dm_matrix': dm_matrix,
    'a4f_pairwise_dm': a4f_dm,
    'giacomini_white': gw_results,
    'midas_fs_verification': {
        'note': 'C1/C2/C3 DM t-stats recomputed with consistent GJR baseline in this unified run',
    },
}

output_path = os.path.join(SCRIPT_DIR, 'mcs_dm_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

elapsed_total = time.time() - START_TIME
print(f"\n  Results saved to {output_path}")
print(f"  Total elapsed: {elapsed_total:.0f}s ({elapsed_total/60:.1f}min)")

# Summary
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"\n  Total models: {len(ALL_MODELS)}")
print(f"  MCS (alpha=0.10): {mcs_10}")
print(f"  MCS (alpha=0.25): {mcs_25}")
print(f"\n  A4f pairwise DM tests:")
for k, v in a4f_dm.items():
    sig = "***" if v['significant_harvey'] else ("*" if v['significant_5pct'] else "")
    print(f"    {k:<50} t={v['t_stat']:+.3f} {sig}")
print(f"\n  GW tests:")
for k, v in gw_results.items():
    sig = "SIG" if v['significant_5pct'] else ""
    print(f"    {v['description']:<30} chi2={v['chi2_stat']:.3f}  p={v['p_value']:.4f} {sig}")

print(f"\n  Done in {elapsed_total:.0f}s")
