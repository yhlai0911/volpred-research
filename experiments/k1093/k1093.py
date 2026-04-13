#!/usr/bin/env python3
"""
K1093: DCC-A4f Weight Sensitivity — Can Commodity-Heavy Portfolios Push ASYM above Harvey?
===========================================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1092 found DCC-A4f-ASYM (SPY-VIX, GLD-GVZ) beats DCC-A4f-SYMM (both VIX)
  on 50/50 SPY/GLD portfolio variance:
    - Portfolio QLIKE DM t=+2.95 (just below Harvey |t|>3.0)
    - FZ 1% DM t=+2.95
    - FZ 2.5% DM t=+2.14
  Hypothesis: 50/50 weight dilutes GLD-GVZ advantage. Tilting toward GLD
  should amplify the GVZ channel and may push DM across Harvey.

Research questions:
  H1: Is the ASYM-vs-SYMM DM t monotonic in GLD weight? (Spearman rank corr)
  H2: Does a GLD-heavy weight reach Harvey |t|>3.0 for ASYM vs SYMM?
  H3: Is 70/30 GLD/SPY (commodity heavy) sufficient?
  H4: Does the weight curve match the asset-matched theory prediction?

Design:
  Same data, same OOS protocol as K1092:
    - SPY, GLD, ^VIX, ^GVZ from yfinance 2005-01-01 to 2026-04-12
    - OOS 2013-06-01; window=1250; refit_every=63; CF_rolling=252
    - Three DCC models: DCC-GJR, DCC-A4f-SYMM, DCC-A4f-ASYM

  Key insight: marginal fits (h_SPY, h_GLD) and ρ_t are INDEPENDENT of
  portfolio weights. So we fit once and evaluate at 5 weight schemes:

    Portfolio       SPY %    GLD %
    70/30           70%      30%
    60/40           60%      40%
    50/50 (K1092)   50%      50%     <- baseline replication
    40/60           40%      60%
    30/70           30%      70%

  For each weight w=(w_SPY, w_GLD) and each DCC model we recompute:
    σ²_port,t = w_SPY²·h_SPY,t + w_GLD²·h_GLD,t + 2·w_SPY·w_GLD·ρ_t·√(h_SPY·h_GLD)
    port_ret_t = w_SPY·r_SPY + w_GLD·r_GLD  (simple returns, daily rebalanced)
    VaR/ES via CF-Rolling on portfolio standardized residuals.

  Evaluation (for each weight and DCC pair):
    - Portfolio QLIKE DM (SYMM vs ASYM)
    - FZ 1% / 2.5% DM
    - Trinity tests (Kupiec + CC + Basel)
    - Portfolio Sharpe (for economic context)

  Core test: Spearman rank correlation of DM t vs GLD weight across the 5
             portfolios. Strong positive ρ + monotone curve → theory supported.

Seed: 42. No simulation; all estimates are deterministic MLE.

References:
  - Engle (2002). Dynamic Conditional Correlation. JBES 20(3).
  - Engle, Ghysels & Sohn (2013). A4f specification. RES 95(3).
  - Patton (2011). QLIKE. JoE 160(1).
  - Fissler & Ziegel (2016). Annals of Statistics 44(4).
  - Diebold & Mariano (1995). JBES 13(3).
  - Harvey (2016). 'Testing Significance' JoF.
  - K1041 (50/50 baseline), K1085 (GLD-GVZ univariate), K1088 (USO-OVX),
    K1091 (asset-matched IV meta), K1092 (50/50 asymmetric DCC-A4f).

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
from scipy.stats import norm, chi2, spearmanr
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1093"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1093_results.json')

# Configuration (mirrors K1092 for reproducibility)
DATA_START = '2005-01-01'
DATA_END = '2026-04-12'
OOS_START = '2013-06-01'
WINDOW = 1250
REFIT_EVERY = 63
CF_ROLLING_WINDOW = 252
ALPHA_LEVELS = [0.025, 0.01]

# Five weight schemes (SPY, GLD)
WEIGHT_SCHEMES = [
    ('70/30', np.array([0.70, 0.30])),
    ('60/40', np.array([0.60, 0.40])),
    ('50/50', np.array([0.50, 0.50])),  # K1092 replication
    ('40/60', np.array([0.40, 0.60])),
    ('30/70', np.array([0.30, 0.70])),
]

MODELS = ['DCC-GJR', 'DCC-A4f-SYMM', 'DCC-A4f-ASYM']

print("=" * 72)
print(f"{EXPERIMENT_ID}: DCC-A4f Weight Sensitivity — SPY/GLD Portfolios")
print(f"  Models: DCC-GJR, DCC-A4f-SYMM (both VIX), DCC-A4f-ASYM (VIX+GVZ)")
print(f"  Weights: {[w[0] for w in WEIGHT_SCHEMES]}")
print(f"  OOS {OOS_START}, window={WINDOW}, refit/{REFIT_EVERY}d, CF/{CF_ROLLING_WINDOW}d")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (identical to K1092)
# ============================================================
@njit
def gjr_recursion(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns[:min(100, T)])
    if h[0] < 1e-16:
        h[0] = 1e-6
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0.0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


@njit
def gjr_nll(omega, alpha, gamma, beta, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, x2):
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * x2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * x2[t-1]
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0.0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


@njit
def a4f_nll(theta0, theta1, omega, alpha, gamma, beta, returns, x2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, x2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit
def dcc_filter(eps1, eps2, a, b, qbar11, qbar22, qbar12):
    T = len(eps1)
    q11 = np.empty(T)
    q22 = np.empty(T)
    q12 = np.empty(T)
    rho = np.empty(T)
    q11[0] = qbar11
    q22[0] = qbar22
    q12[0] = qbar12
    denom = np.sqrt(q11[0] * q22[0])
    rho[0] = q12[0] / denom if denom > 1e-20 else 0.0
    c = 1.0 - a - b
    for t in range(1, T):
        q11[t] = c * qbar11 + a * eps1[t-1] * eps1[t-1] + b * q11[t-1]
        q22[t] = c * qbar22 + a * eps2[t-1] * eps2[t-1] + b * q22[t-1]
        q12[t] = c * qbar12 + a * eps1[t-1] * eps2[t-1] + b * q12[t-1]
        denom = np.sqrt(q11[t] * q22[t])
        if denom > 1e-20:
            rho[t] = q12[t] / denom
            if rho[t] > 0.9999:
                rho[t] = 0.9999
            elif rho[t] < -0.9999:
                rho[t] = -0.9999
        else:
            rho[t] = 0.0
    return rho


@njit
def dcc_loglik(eps1, eps2, a, b, qbar11, qbar22, qbar12):
    rho = dcc_filter(eps1, eps2, a, b, qbar11, qbar22, qbar12)
    T = len(eps1)
    ll = 0.0
    for t in range(T):
        r = rho[t]
        r2 = r * r
        if r2 > 0.9998:
            r2 = 0.9998
        det = 1.0 - r2
        e1 = eps1[t]
        e2 = eps2[t]
        ll += -0.5 * (np.log(det) + (r2 * (e1*e1 + e2*e2) - 2.0*r*e1*e2) / det)
    return ll


# ============================================================
# 2. MODEL FITTING (identical to K1092)
# ============================================================
def fit_gjr(returns):
    bounds = [(1e-8, 0.01), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            v = gjr_nll(p[0], p[1], p[2], p[3], returns)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10
    best_res, best_nll = None, 1e10
    for omega_init in [1e-6, 5e-6, 1e-5]:
        for alpha_init in [0.03, 0.06]:
            x0 = [omega_init, alpha_init, 0.08, 0.88]
            try:
                res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                                        options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        x0 = [5e-6, 0.04, 0.08, 0.88]
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h = gjr_recursion(*best_res.x, returns)
    return {'params': best_res.x.tolist(), 'h': h, 'converged': best_res.success}


def fit_a4f(returns, x2):
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll(p[0], p[1], p[2], p[3], p[4], p[5], returns, x2)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10
    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                                        options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h, tau, g = a4f_recursion(*best_res.x, returns, x2)
    return {'params': best_res.x.tolist(), 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success}


def fit_dcc(eps1, eps2):
    T = len(eps1)
    m1, m2 = np.mean(eps1), np.mean(eps2)
    e1c, e2c = eps1 - m1, eps2 - m2
    qbar11 = np.mean(e1c**2)
    qbar22 = np.mean(e2c**2)
    qbar12 = np.mean(e1c * e2c)
    bounds = [(1e-6, 0.3), (0.5, 0.999)]
    def obj(p):
        a, b = p
        if a + b >= 0.999:
            return 1e10
        try:
            ll = dcc_loglik(eps1, eps2, a, b, qbar11, qbar22, qbar12)
            return -ll if np.isfinite(ll) else 1e10
        except Exception:
            return 1e10
    best_res, best_nll = None, 1e10
    for a_init in [0.01, 0.05, 0.1]:
        for b_init in [0.85, 0.92, 0.95]:
            if a_init + b_init >= 0.999:
                continue
            x0 = [a_init, b_init]
            try:
                res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                                        options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        best_res = optimize.minimize(obj, [0.05, 0.90], method='L-BFGS-B', bounds=bounds)
    a_hat, b_hat = best_res.x
    rho = dcc_filter(eps1, eps2, a_hat, b_hat, qbar11, qbar22, qbar12)
    return {'a': float(a_hat), 'b': float(b_hat), 'rho': rho,
            'qbar11': float(qbar11), 'qbar22': float(qbar22),
            'qbar12': float(qbar12), 'converged': best_res.success}


# ============================================================
# 3. OOS FORECASTING (identical to K1092) — produces marginal h and ρ only
# ============================================================
def oos_forecast_all(ret_spy, ret_gld, vix2, gvz2, dates,
                     oos_start, window=WINDOW, refit_every=REFIT_EVERY):
    """OOS one-step-ahead h_SPY, h_GLD, rho for each DCC model.
    Weight-independent output — we can re-use it for all 5 weight schemes."""
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret_spy)
    n_oos = T - oos_idx

    h_spy = {m: np.full(n_oos, np.nan) for m in MODELS}
    h_gld = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_f = {m: np.full(n_oos, np.nan) for m in MODELS}

    state = {}
    for m in MODELS:
        state[m] = {
            'h1_prev': np.nan, 'h2_prev': np.nan,
            'g1_prev': np.nan, 'g2_prev': np.nan,
            'marg1_p': None, 'marg2_p': None,
            'dcc_a': 0.0, 'dcc_b': 0.0,
            'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
            'last_fit': -refit_every,
            'eps1_prev': 0.0, 'eps2_prev': 0.0,
            'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        }

    for i in range(n_oos):
        t = oos_idx + i
        if i % 250 == 0:
            elapsed = time.time() - START_TIME
            print(f"  OOS day {i}/{n_oos} ({elapsed:.0f}s)")

        need_refit = (i - state['DCC-GJR']['last_fit'] >= refit_every
                      or state['DCC-GJR']['marg1_p'] is None)

        if need_refit:
            s = max(0, t - window)
            tr_spy = ret_spy[s:t]
            tr_gld = ret_gld[s:t]
            tr_vix2 = vix2[s:t]
            tr_gvz2 = gvz2[s:t]

            gjr_spy = fit_gjr(tr_spy)
            gjr_gld = fit_gjr(tr_gld)
            eps_gjr_spy = tr_spy / np.sqrt(gjr_spy['h'])
            eps_gjr_gld = tr_gld / np.sqrt(gjr_gld['h'])
            dcc_gjr = fit_dcc(eps_gjr_spy, eps_gjr_gld)

            a4f_spy_vix = fit_a4f(tr_spy, tr_vix2)
            a4f_gld_vix = fit_a4f(tr_gld, tr_vix2)
            eps_symm_spy = tr_spy / np.sqrt(a4f_spy_vix['h'])
            eps_symm_gld = tr_gld / np.sqrt(a4f_gld_vix['h'])
            dcc_symm = fit_dcc(eps_symm_spy, eps_symm_gld)

            a4f_gld_gvz = fit_a4f(tr_gld, tr_gvz2)
            eps_asym_spy = tr_spy / np.sqrt(a4f_spy_vix['h'])
            eps_asym_gld = tr_gld / np.sqrt(a4f_gld_gvz['h'])
            dcc_asym = fit_dcc(eps_asym_spy, eps_asym_gld)

            # populate states
            m = 'DCC-GJR'
            state[m]['marg1_p'] = ('GJR', gjr_spy['params'])
            state[m]['marg2_p'] = ('GJR', gjr_gld['params'])
            state[m]['h1_prev'] = float(gjr_spy['h'][-1])
            state[m]['h2_prev'] = float(gjr_gld['h'][-1])
            state[m]['dcc_a'] = dcc_gjr['a']
            state[m]['dcc_b'] = dcc_gjr['b']
            state[m]['qbar11'] = dcc_gjr['qbar11']
            state[m]['qbar22'] = dcc_gjr['qbar22']
            state[m]['qbar12'] = dcc_gjr['qbar12']
            state[m]['eps1_prev'] = float(eps_gjr_spy[-1])
            state[m]['eps2_prev'] = float(eps_gjr_gld[-1])
            state[m]['q11_prev'] = dcc_gjr['qbar11']
            state[m]['q22_prev'] = dcc_gjr['qbar22']
            state[m]['q12_prev'] = dcc_gjr['qbar12']

            m = 'DCC-A4f-SYMM'
            state[m]['marg1_p'] = ('A4f', a4f_spy_vix['params'], 'VIX')
            state[m]['marg2_p'] = ('A4f', a4f_gld_vix['params'], 'VIX')
            state[m]['h1_prev'] = float(a4f_spy_vix['h'][-1])
            state[m]['h2_prev'] = float(a4f_gld_vix['h'][-1])
            state[m]['g1_prev'] = float(a4f_spy_vix['g'][-1])
            state[m]['g2_prev'] = float(a4f_gld_vix['g'][-1])
            state[m]['dcc_a'] = dcc_symm['a']
            state[m]['dcc_b'] = dcc_symm['b']
            state[m]['qbar11'] = dcc_symm['qbar11']
            state[m]['qbar22'] = dcc_symm['qbar22']
            state[m]['qbar12'] = dcc_symm['qbar12']
            state[m]['eps1_prev'] = float(eps_symm_spy[-1])
            state[m]['eps2_prev'] = float(eps_symm_gld[-1])
            state[m]['q11_prev'] = dcc_symm['qbar11']
            state[m]['q22_prev'] = dcc_symm['qbar22']
            state[m]['q12_prev'] = dcc_symm['qbar12']

            m = 'DCC-A4f-ASYM'
            state[m]['marg1_p'] = ('A4f', a4f_spy_vix['params'], 'VIX')
            state[m]['marg2_p'] = ('A4f', a4f_gld_gvz['params'], 'GVZ')
            state[m]['h1_prev'] = float(a4f_spy_vix['h'][-1])
            state[m]['h2_prev'] = float(a4f_gld_gvz['h'][-1])
            state[m]['g1_prev'] = float(a4f_spy_vix['g'][-1])
            state[m]['g2_prev'] = float(a4f_gld_gvz['g'][-1])
            state[m]['dcc_a'] = dcc_asym['a']
            state[m]['dcc_b'] = dcc_asym['b']
            state[m]['qbar11'] = dcc_asym['qbar11']
            state[m]['qbar22'] = dcc_asym['qbar22']
            state[m]['qbar12'] = dcc_asym['qbar12']
            state[m]['eps1_prev'] = float(eps_asym_spy[-1])
            state[m]['eps2_prev'] = float(eps_asym_gld[-1])
            state[m]['q11_prev'] = dcc_asym['qbar11']
            state[m]['q22_prev'] = dcc_asym['qbar22']
            state[m]['q12_prev'] = dcc_asym['qbar12']

            for m in MODELS:
                state[m]['last_fit'] = i

        r1_prev = ret_spy[t-1]
        r2_prev = ret_gld[t-1]
        vix2_prev = vix2[t-1]
        gvz2_prev = gvz2[t-1]

        for m in MODELS:
            marg1 = state[m]['marg1_p']
            marg2 = state[m]['marg2_p']

            # SPY marginal
            if marg1[0] == 'GJR':
                p = marg1[1]
                ind = 1.0 if r1_prev < 0 else 0.0
                h1_t = p[0] + p[1]*r1_prev**2 + p[2]*r1_prev**2*ind + p[3]*state[m]['h1_prev']
            else:
                p = marg1[1]
                tau = max(p[0] + p[1] * vix2_prev, 1e-16)
                u_prev = r1_prev / np.sqrt(tau)
                ind = 1.0 if r1_prev < 0 else 0.0
                g_t = p[2] + p[3]*u_prev**2 + p[4]*u_prev**2*ind + p[5]*state[m]['g1_prev']
                g_t = max(g_t, 1e-16)
                state[m]['g1_prev'] = g_t
                h1_t = tau * g_t
            h1_t = max(h1_t, 1e-16)

            # GLD marginal
            if marg2[0] == 'GJR':
                p = marg2[1]
                ind = 1.0 if r2_prev < 0 else 0.0
                h2_t = p[0] + p[1]*r2_prev**2 + p[2]*r2_prev**2*ind + p[3]*state[m]['h2_prev']
            else:
                p = marg2[1]
                regressor = marg2[2]
                x2_prev = vix2_prev if regressor == 'VIX' else gvz2_prev
                tau = max(p[0] + p[1] * x2_prev, 1e-16)
                u_prev = r2_prev / np.sqrt(tau)
                ind = 1.0 if r2_prev < 0 else 0.0
                g_t = p[2] + p[3]*u_prev**2 + p[4]*u_prev**2*ind + p[5]*state[m]['g2_prev']
                g_t = max(g_t, 1e-16)
                state[m]['g2_prev'] = g_t
                h2_t = tau * g_t
            h2_t = max(h2_t, 1e-16)

            state[m]['h1_prev'] = h1_t
            state[m]['h2_prev'] = h2_t
            h_spy[m][i] = h1_t
            h_gld[m][i] = h2_t

            # DCC one-step update
            a_dcc = state[m]['dcc_a']
            b_dcc = state[m]['dcc_b']
            c_dcc = 1.0 - a_dcc - b_dcc
            e1p = state[m]['eps1_prev']
            e2p = state[m]['eps2_prev']
            q11 = c_dcc * state[m]['qbar11'] + a_dcc * e1p**2 + b_dcc * state[m]['q11_prev']
            q22 = c_dcc * state[m]['qbar22'] + a_dcc * e2p**2 + b_dcc * state[m]['q22_prev']
            q12 = c_dcc * state[m]['qbar12'] + a_dcc * e1p*e2p + b_dcc * state[m]['q12_prev']
            denom = np.sqrt(q11 * q22)
            rho_t = q12 / denom if denom > 1e-20 else 0.0
            rho_t = np.clip(rho_t, -0.9999, 0.9999)
            rho_f[m][i] = rho_t

            eps1_now = r1_prev / np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
            eps2_now = r2_prev / np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
            state[m]['eps1_prev'] = eps1_now
            state[m]['eps2_prev'] = eps2_now
            state[m]['q11_prev'] = q11
            state[m]['q22_prev'] = q22
            state[m]['q12_prev'] = q12

    oos_dates = dates[oos_idx:]
    return {'h_spy': h_spy, 'h_gld': h_gld, 'rho': rho_f,
            'oos_dates': oos_dates, 'oos_idx': oos_idx}


# ============================================================
# 4. PORTFOLIO VAR / ES / FZ / DM helpers
# ============================================================
def compute_portfolio_variance(h1, h2, rho, w_spy, w_gld):
    """σ²_port,t = w1²·h1 + w2²·h2 + 2·w1·w2·ρ·√(h1·h2)"""
    s1 = np.sqrt(h1)
    s2 = np.sqrt(h2)
    return w_spy**2 * h1 + w_gld**2 * h2 + 2.0 * w_spy * w_gld * rho * s1 * s2


def cf_quantile(alpha, skew, exkurt):
    z = norm.ppf(alpha)
    q = (z + (z**2 - 1) * skew / 6
         + (z**3 - 3*z) * exkurt / 24
         - (2*z**3 - 5*z) * skew**2 / 36)
    return q


def compute_cf_rolling_var(port_returns, port_sigma, alpha, cf_window=CF_ROLLING_WINDOW):
    T = len(port_returns)
    var_series = np.full(T, np.nan)
    es_series = np.full(T, np.nan)
    std_resid = np.where(port_sigma > 1e-10, port_returns / port_sigma, 0.0)
    for t in range(cf_window, T):
        window_resid = std_resid[t - cf_window:t]
        valid = np.isfinite(window_resid) & (np.abs(window_resid) < 20)
        if valid.sum() < 50:
            var_series[t] = port_sigma[t] * norm.ppf(alpha)
            continue
        wr = window_resid[valid]
        sk = np.clip(float(stats.skew(wr)), -3, 3)
        ek = np.clip(float(stats.kurtosis(wr)), -2, 30)
        q_cf = cf_quantile(alpha, sk, ek)
        var_series[t] = port_sigma[t] * q_cf
        below = wr[wr < q_cf]
        if len(below) >= 3:
            es_series[t] = port_sigma[t] * np.mean(below)
        else:
            es_series[t] = var_series[t] * 1.3
    return var_series, es_series


def kupiec_test(violations, n, alpha):
    n1 = int(np.sum(violations))
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0
    if n1 == 0 or n1 == n:
        return {'stat': 0.0, 'p_value': 1.0, 'violations': n1, 'rate': pi_hat,
                'expected_rate': float(alpha), 'pass': True}
    lr = -2 * (n1 * np.log(alpha) + n0 * np.log(1 - alpha)
               - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
    p_val = 1 - chi2.cdf(lr, df=1)
    return {'stat': float(lr), 'p_value': float(p_val),
            'violations': n1, 'rate': float(pi_hat),
            'expected_rate': float(alpha), 'pass': bool(p_val > 0.05)}


def christoffersen_test(violations):
    v = violations.astype(int)
    n = len(v)
    t00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
    t01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
    t10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
    t11 = np.sum((v[:-1] == 1) & (v[1:] == 1))
    pi_all = (t01 + t11) / (n - 1) if n > 1 else 0
    pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
    pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
    try:
        if all(0 < x < 1 for x in [pi01, pi11, pi_all]):
            lr_ind = (-2 * ((t00 + t10) * np.log(1 - pi_all) + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11)))
            p_val = 1 - chi2.cdf(lr_ind, df=1)
        else:
            lr_ind, p_val = 0.0, 1.0
    except Exception:
        lr_ind, p_val = 0.0, 1.0
    return {'stat': float(lr_ind), 'p_value': float(p_val),
            'clusters': int(t11), 'pass': bool(p_val > 0.05)}


def basel_traffic_light(violations, n, alpha):
    n1 = int(np.sum(violations))
    n_blocks = max(1, n // 250)
    avg = n1 / n_blocks
    if alpha <= 0.01:
        thr = {'green': 4, 'yellow': 9}
    else:
        thr = {'green': int(250 * alpha * 1.5) + 1,
               'yellow': int(250 * alpha * 2.5) + 1}
    if avg <= thr['green']:
        color = 'Green'
    elif avg <= thr['yellow']:
        color = 'Yellow'
    else:
        color = 'Red'
    return {'color': color, 'violations_per_block': float(avg),
            'n_blocks': n_blocks, 'pass': bool(color == 'Green')}


def es_backtest_acerbi_szekely(port_returns, var_series, es_series, alpha):
    valid = np.isfinite(var_series) & np.isfinite(es_series) & np.isfinite(port_returns)
    r = port_returns[valid]
    v = var_series[valid]
    es = es_series[valid]
    n = len(r)
    violations = r < v
    n_viol = int(np.sum(violations))
    if n_viol < 3:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': n_viol}
    numerator = np.sum(r[violations])
    es_avg = np.mean(es[violations])
    if abs(es_avg) < 1e-12:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': n_viol}
    z1 = numerator / (n * alpha * es_avg) - 1
    p_val = 2 * norm.cdf(-abs(z1))
    return {'z_stat': float(z1), 'p_value': float(p_val),
            'pass': bool(p_val > 0.05), 'n_violations': n_viol}


def fz_score_series(port_returns, var_series, es_series, alpha):
    """Fissler-Ziegel FZ0 strictly consistent joint VaR-ES score (Patton-Ziegel-Chen 2019)."""
    valid = (np.isfinite(var_series) & np.isfinite(es_series)
             & np.isfinite(port_returns) & (es_series < 0) & (var_series < 0))
    r = port_returns[valid]
    V = var_series[valid]
    E = es_series[valid]
    n = len(r)
    if n == 0:
        return np.array([]), float('nan')
    indicator = (r <= V).astype(float)
    with np.errstate(divide='ignore', invalid='ignore'):
        s = (1.0 / alpha) * indicator * (V - r) / (-E) - V / E + np.log(-E) - 1.0
    s = s[np.isfinite(s)]
    return s, float(np.mean(s)) if len(s) else float('nan')


def trinity_test(port_returns, var_series, es_series, alpha):
    valid = np.isfinite(var_series) & np.isfinite(port_returns)
    r = port_returns[valid]
    v = var_series[valid]
    n = len(r)
    violations = (r < v).astype(int)
    kupiec = kupiec_test(violations, n, alpha)
    cc = christoffersen_test(violations)
    basel = basel_traffic_light(violations, n, alpha)
    es_test = es_backtest_acerbi_szekely(port_returns[valid], v,
                                         es_series[valid] if es_series is not None else v * 1.3,
                                         alpha)
    trinity_pass = bool(kupiec['pass'] and cc['pass'] and basel['pass'])
    return {'kupiec': kupiec, 'christoffersen': cc, 'basel': basel,
            'es_test': es_test, 'trinity_pass': trinity_pass,
            'n_oos': n, 'violation_rate': float(kupiec['rate'])}


def dm_test(loss_series_1, loss_series_2):
    valid = np.isfinite(loss_series_1) & np.isfinite(loss_series_2)
    l1 = loss_series_1[valid]
    l2 = loss_series_2[valid]
    d = l1 - l2
    n = len(d)
    if n < 10:
        return {'t_stat': 0.0, 'p_value': 1.0, 'mean_loss_diff': 0.0,
                'n': n, 'significant_harvey': False}
    d_bar = np.mean(d)
    max_lag = max(1, int(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * w * gamma_k
    se = np.sqrt(nw_var / n) if nw_var > 0 else 1e-12
    t_stat = d_bar / se if se > 1e-12 else 0.0
    p_val = 2 * norm.cdf(-abs(t_stat))
    return {'t_stat': float(t_stat), 'p_value': float(p_val),
            'mean_loss_diff': float(d_bar), 'n': int(n),
            'significant_harvey': bool(abs(t_stat) > 3.0)}


def dm_qlike(actual_r2, forecast_var1, forecast_var2):
    valid = (np.isfinite(actual_r2) & np.isfinite(forecast_var1) & np.isfinite(forecast_var2)
             & (forecast_var1 > 0) & (forecast_var2 > 0))
    r2 = actual_r2[valid]
    h1 = forecast_var1[valid]
    h2 = forecast_var2[valid]
    loss1 = np.log(h1) + r2 / h1
    loss2 = np.log(h2) + r2 / h2
    return dm_test(loss1, loss2)


def portfolio_sharpe(port_returns):
    pr = port_returns[np.isfinite(port_returns)]
    mean = np.mean(pr) * 252.0
    vol = np.std(pr, ddof=1) * np.sqrt(252.0)
    if vol < 1e-12:
        return {'annual_mean': float(mean), 'annual_vol': float(vol), 'sharpe': 0.0}
    return {'annual_mean': float(mean), 'annual_vol': float(vol),
            'sharpe': float(mean / vol)}


# ============================================================
# 5. DATA (identical to K1092)
# ============================================================
def load_data():
    import yfinance as yf
    print("Downloading data (SPY, GLD, ^VIX, ^GVZ)...")
    spy_raw = yf.download('SPY', start=DATA_START, end=DATA_END,
                          auto_adjust=True, progress=False)
    gld_raw = yf.download('GLD', start=DATA_START, end=DATA_END,
                          auto_adjust=True, progress=False)
    vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)
    gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)

    def _close(raw):
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.copy()
            raw.columns = raw.columns.get_level_values(0)
        return raw['Close']

    spy_close = _close(spy_raw)
    gld_close = _close(gld_raw)
    vix_close = _close(vix_raw)
    gvz_close = _close(gvz_raw)

    df = pd.DataFrame({
        'spy': spy_close, 'gld': gld_close, 'vix': vix_close, 'gvz': gvz_close
    }).sort_index()
    df = df.dropna(subset=['spy', 'gld', 'vix'])

    df['gvz_filled'] = df['gvz'].copy()
    mask = df['gvz_filled'].isna()
    df.loc[mask, 'gvz_filled'] = df.loc[mask, 'vix']
    df['gvz_filled'] = df['gvz_filled'].ffill()

    df['ret_spy'] = np.log(df['spy'] / df['spy'].shift(1))
    df['ret_gld'] = np.log(df['gld'] / df['gld'].shift(1))
    df['vix2'] = (df['vix'] / 100.0) ** 2 / 252.0
    df['gvz2'] = (df['gvz_filled'] / 100.0) ** 2 / 252.0

    df['simple_spy'] = df['spy'].pct_change()
    df['simple_gld'] = df['gld'].pct_change()

    df = df.dropna(subset=['ret_spy', 'ret_gld', 'vix2', 'gvz2'])

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")
    return df


# ============================================================
# 6. JSON SAFE
# ============================================================
def to_json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(obj).strftime('%Y-%m-%d')
    return obj


# ============================================================
# 7. MAIN
# ============================================================
def main():
    df = load_data()

    ret_spy = df['ret_spy'].values
    ret_gld = df['ret_gld'].values
    vix2 = df['vix2'].values
    gvz2 = df['gvz2'].values
    dates = df.index.values
    simple_spy = df['simple_spy'].values
    simple_gld = df['simple_gld'].values

    print("\n--- OOS Forecasting (3 DCC models) ---")
    forecasts = oos_forecast_all(ret_spy, ret_gld, vix2, gvz2, dates, OOS_START)
    oos_idx = forecasts['oos_idx']
    oos_dates = forecasts['oos_dates']
    n_oos = len(oos_dates)
    print(f"OOS: {pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} to "
          f"{pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')}  n={n_oos}")

    simple_spy_oos = simple_spy[oos_idx:]
    simple_gld_oos = simple_gld[oos_idx:]

    # Storage
    results = {
        'experiment_id': EXPERIMENT_ID,
        'weights_tested': [{'label': lab, 'w_spy': w[0], 'w_gld': w[1]}
                          for lab, w in WEIGHT_SCHEMES],
        'per_weight': {},
    }

    # Per-weight evaluation loop
    for label, w in WEIGHT_SCHEMES:
        w_spy, w_gld = float(w[0]), float(w[1])
        gld_frac = w_gld  # <-- key variable for H1
        print(f"\n{'='*72}")
        print(f"Weight scheme: {label} (SPY={w_spy:.2f}, GLD={w_gld:.2f})")
        print(f"{'='*72}")

        # Portfolio returns (simple, daily rebalanced)
        port_ret_oos = w_spy * simple_spy_oos + w_gld * simple_gld_oos
        r2_port_oos = port_ret_oos ** 2

        per_weight = {
            'label': label, 'w_spy': w_spy, 'w_gld': w_gld,
            'models': {},
            'dm_qlike': {},
            'dm_fz': {'alpha_0.010': {}, 'alpha_0.025': {}},
            'mean_qlike': {},
            'sharpe': portfolio_sharpe(port_ret_oos),
        }

        # For each DCC model: compute portfolio variance, VaR, ES, FZ
        pvar_dict = {}
        fz_series_dict = {m: {} for m in MODELS}
        fz_mean_dict = {m: {} for m in MODELS}

        for m in MODELS:
            print(f"\n  Model: {m}")
            h1 = forecasts['h_spy'][m]
            h2 = forecasts['h_gld'][m]
            rho = forecasts['rho'][m]
            pvar = compute_portfolio_variance(h1, h2, rho, w_spy, w_gld)
            pvar_dict[m] = pvar
            port_sigma = np.sqrt(np.maximum(pvar, 1e-16))

            model_results = {'var_tests': {}, 'fz_score': {}}

            for alpha in ALPHA_LEVELS:
                var_s, es_s = compute_cf_rolling_var(port_ret_oos, port_sigma, alpha)
                trinity = trinity_test(port_ret_oos, var_s, es_s, alpha)
                fz_s, fz_mean = fz_score_series(port_ret_oos, var_s, es_s, alpha)
                fz_series_dict[m][alpha] = fz_s
                fz_mean_dict[m][alpha] = fz_mean

                akey = f"alpha_{alpha:.3f}"
                model_results['var_tests'][akey] = trinity
                model_results['fz_score'][akey] = {'mean': fz_mean, 'n': int(len(fz_s))}
                print(f"    alpha={alpha:.3f}: viol={trinity['violation_rate']:.4f} "
                      f"exp={alpha:.4f}, Trinity={'PASS' if trinity['trinity_pass'] else 'FAIL'}, "
                      f"Kupiec p={trinity['kupiec']['p_value']:.4f}, FZ={fz_mean:.4f}")

            # Mean QLIKE
            valid = np.isfinite(pvar) & (pvar > 0) & np.isfinite(r2_port_oos)
            q = np.log(pvar[valid]) + r2_port_oos[valid] / pvar[valid]
            mean_qlike = float(np.mean(q))
            model_results['mean_qlike'] = mean_qlike
            per_weight['mean_qlike'][m] = mean_qlike

            per_weight['models'][m] = model_results

        # DM tests (portfolio QLIKE)
        pairs = [
            ('DCC-GJR', 'DCC-A4f-SYMM'),
            ('DCC-GJR', 'DCC-A4f-ASYM'),
            ('DCC-A4f-SYMM', 'DCC-A4f-ASYM'),
        ]
        print(f"\n  --- DM QLIKE ({label}) ---")
        for m1, m2 in pairs:
            dm = dm_qlike(r2_port_oos, pvar_dict[m1], pvar_dict[m2])
            key = f"{m1}_vs_{m2}"
            per_weight['dm_qlike'][key] = dm
            direction = f"{m1} better" if dm['t_stat'] < 0 else f"{m2} better"
            sig = "***" if dm['significant_harvey'] else ("*" if dm['p_value'] < 0.05 else "")
            print(f"    {m1} vs {m2}: DM t={dm['t_stat']:+.3f} ({direction}) {sig}")

        # DM tests (FZ)
        print(f"  --- DM FZ ({label}) ---")
        for alpha in ALPHA_LEVELS:
            akey = f"alpha_{alpha:.3f}"
            for m1, m2 in pairs:
                s1 = fz_series_dict[m1][alpha]
                s2 = fz_series_dict[m2][alpha]
                n = min(len(s1), len(s2))
                if n < 50:
                    dm = {'t_stat': 0.0, 'p_value': 1.0, 'mean_loss_diff': 0.0,
                          'n': int(n), 'significant_harvey': False}
                else:
                    dm = dm_test(s1[:n], s2[:n])
                per_weight['dm_fz'][akey][f"{m1}_vs_{m2}"] = dm
                direction = f"{m1} better" if dm['t_stat'] < 0 else f"{m2} better"
                sig = "***" if dm['significant_harvey'] else ("*" if dm['p_value'] < 0.05 else "")
                print(f"    [{akey}] {m1} vs {m2}: DM t={dm['t_stat']:+.3f} ({direction}) {sig}")

        # FZ mean store (for plotting)
        per_weight['fz_mean'] = {
            m: {f"alpha_{a:.3f}": fz_mean_dict[m][a] for a in ALPHA_LEVELS}
            for m in MODELS
        }

        results['per_weight'][label] = per_weight

    # ============================================================
    # 8. CROSS-WEIGHT ANALYSIS (Spearman, monotonicity)
    # ============================================================
    print("\n" + "=" * 72)
    print("CROSS-WEIGHT ANALYSIS")
    print("=" * 72)

    key_pair = 'DCC-A4f-SYMM_vs_DCC-A4f-ASYM'
    gld_weights = [w[1] for lab, w in WEIGHT_SCHEMES]
    labels_order = [lab for lab, w in WEIGHT_SCHEMES]

    # Series of DM t-stats as GLD weight increases
    dm_qlike_t = [results['per_weight'][lab]['dm_qlike'][key_pair]['t_stat']
                  for lab in labels_order]
    dm_fz1_t = [results['per_weight'][lab]['dm_fz']['alpha_0.010'][key_pair]['t_stat']
                for lab in labels_order]
    dm_fz25_t = [results['per_weight'][lab]['dm_fz']['alpha_0.025'][key_pair]['t_stat']
                 for lab in labels_order]

    print(f"\nGLD weight (%):      {[int(w*100) for w in gld_weights]}")
    print(f"QLIKE DM t:          {[f'{t:+.3f}' for t in dm_qlike_t]}")
    print(f"FZ 1% DM t:          {[f'{t:+.3f}' for t in dm_fz1_t]}")
    print(f"FZ 2.5% DM t:        {[f'{t:+.3f}' for t in dm_fz25_t]}")

    # Spearman rank correlations
    sp_qlike = spearmanr(gld_weights, dm_qlike_t)
    sp_fz1 = spearmanr(gld_weights, dm_fz1_t)
    sp_fz25 = spearmanr(gld_weights, dm_fz25_t)

    # Monotonicity: is the sequence non-decreasing?
    def monotonic_up(xs):
        return all(xs[i+1] >= xs[i] for i in range(len(xs)-1))
    def monotonic_down(xs):
        return all(xs[i+1] <= xs[i] for i in range(len(xs)-1))

    cross = {
        'gld_weights': gld_weights,
        'weight_labels': labels_order,
        'dm_qlike_t_symm_vs_asym': dm_qlike_t,
        'dm_fz1_t_symm_vs_asym': dm_fz1_t,
        'dm_fz25_t_symm_vs_asym': dm_fz25_t,
        'spearman_qlike': {'rho': float(sp_qlike.statistic), 'p_value': float(sp_qlike.pvalue)},
        'spearman_fz1': {'rho': float(sp_fz1.statistic), 'p_value': float(sp_fz1.pvalue)},
        'spearman_fz25': {'rho': float(sp_fz25.statistic), 'p_value': float(sp_fz25.pvalue)},
        'monotonic_qlike': monotonic_up(dm_qlike_t),
        'monotonic_fz1': monotonic_up(dm_fz1_t),
        'monotonic_fz25': monotonic_up(dm_fz25_t),
        'harvey_pass_count_qlike': int(sum(1 for t in dm_qlike_t if t > 3.0)),
        'harvey_pass_count_fz1': int(sum(1 for t in dm_fz1_t if t > 3.0)),
        'harvey_pass_count_fz25': int(sum(1 for t in dm_fz25_t if t > 3.0)),
        'max_dm_qlike_t': float(max(dm_qlike_t)),
        'argmax_dm_qlike_label': labels_order[int(np.argmax(dm_qlike_t))],
        'max_dm_fz1_t': float(max(dm_fz1_t)),
        'argmax_dm_fz1_label': labels_order[int(np.argmax(dm_fz1_t))],
    }
    print(f"\nSpearman (GLD weight vs DM QLIKE t):  ρ={sp_qlike.statistic:+.3f}, p={sp_qlike.pvalue:.4f}")
    print(f"Spearman (GLD weight vs DM FZ 1% t):  ρ={sp_fz1.statistic:+.3f}, p={sp_fz1.pvalue:.4f}")
    print(f"Spearman (GLD weight vs DM FZ 2.5% t):ρ={sp_fz25.statistic:+.3f}, p={sp_fz25.pvalue:.4f}")
    print(f"Monotonic upward? QLIKE={cross['monotonic_qlike']}, FZ1={cross['monotonic_fz1']}, "
          f"FZ25={cross['monotonic_fz25']}")
    print(f"Harvey PASS count (|t|>3, ASYM better): QLIKE={cross['harvey_pass_count_qlike']}/5, "
          f"FZ1={cross['harvey_pass_count_fz1']}/5, FZ25={cross['harvey_pass_count_fz25']}/5")
    print(f"Max DM QLIKE t = {cross['max_dm_qlike_t']:+.3f} at {cross['argmax_dm_qlike_label']}")
    print(f"Max DM FZ 1% t = {cross['max_dm_fz1_t']:+.3f} at {cross['argmax_dm_fz1_label']}")

    results['cross_weight_analysis'] = cross

    # ============================================================
    # 9. CORE ANSWERS (pre-registered questions)
    # ============================================================
    # H1: monotonic? And Spearman significant?
    h1_pass = (cross['monotonic_qlike'] or cross['monotonic_fz1'] or cross['monotonic_fz25'])
    # H2: any weight hits Harvey on any metric?
    h2_pass = (cross['harvey_pass_count_qlike'] > 0
               or cross['harvey_pass_count_fz1'] > 0
               or cross['harvey_pass_count_fz25'] > 0)
    # H3: 30/70 portfolio (GLD heavy) — does ASYM vs SYMM hit Harvey?
    p3070 = results['per_weight']['30/70']
    h3_qlike_harvey = p3070['dm_qlike'][key_pair]['significant_harvey']
    h3_fz1_harvey = p3070['dm_fz']['alpha_0.010'][key_pair]['significant_harvey']

    core = {
        'H1_monotonic_up_in_gld_weight': h1_pass,
        'H1_spearman_qlike_rho': cross['spearman_qlike']['rho'],
        'H2_any_weight_hits_harvey': h2_pass,
        'H3_3070_qlike_harvey': h3_qlike_harvey,
        'H3_3070_fz1_harvey': h3_fz1_harvey,
        'H4_50_50_matches_k1092': {
            'qlike_t_expected': 2.950922731110805,
            'qlike_t_observed': results['per_weight']['50/50']['dm_qlike'][key_pair]['t_stat'],
            'fz1_t_expected': 2.947038946558994,
            'fz1_t_observed': results['per_weight']['50/50']['dm_fz']['alpha_0.010'][key_pair]['t_stat'],
        },
        'max_dm_qlike_weight': cross['argmax_dm_qlike_label'],
        'max_dm_fz1_weight': cross['argmax_dm_fz1_label'],
    }
    results['core_answers'] = core

    print("\n" + "=" * 72)
    print("CORE ANSWERS")
    print("=" * 72)
    print(f"  H1 (monotonic up in GLD weight, QLIKE Spearman ρ): "
          f"ρ={cross['spearman_qlike']['rho']:+.3f}, monotonic={cross['monotonic_qlike']}")
    print(f"  H2 (any weight Harvey PASS for ASYM): {h2_pass}")
    print(f"  H3 (30/70 QLIKE Harvey): {h3_qlike_harvey} | FZ 1% Harvey: {h3_fz1_harvey}")
    print(f"  H4 (50/50 replicates K1092): observed QLIKE t={core['H4_50_50_matches_k1092']['qlike_t_observed']:+.3f} "
          f"(K1092 reported +2.951)")

    # ============================================================
    # 10. METADATA
    # ============================================================
    runtime = time.time() - START_TIME
    results['metadata'] = {
        'experiment_id': EXPERIMENT_ID,
        'data_source': 'yfinance (SPY, GLD, ^VIX, ^GVZ)',
        'data_period': f"{DATA_START} to {DATA_END}",
        'oos_start': OOS_START,
        'n_oos': int(n_oos),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'cf_rolling_window': CF_ROLLING_WINDOW,
        'alpha_levels': ALPHA_LEVELS,
        'weight_schemes': [{'label': lab, 'w_spy': float(w[0]), 'w_gld': float(w[1])}
                           for lab, w in WEIGHT_SCHEMES],
        'seed': 42,
        'runtime_seconds': float(runtime),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'parent_experiments': ['K1041', 'K1085', 'K1088', 'K1091', 'K1092'],
        'references': [
            'Engle (2002) JBES 20(3)',
            'Engle, Ghysels & Sohn (2013) RES 95(3)',
            'Patton (2011) JoE 160(1)',
            'Fissler & Ziegel (2016) Ann Stat 44(4)',
            'Diebold & Mariano (1995) JBES 13(3)',
            'Harvey (2016)',
        ],
    }

    # ============================================================
    # 11. PLOTS
    # ============================================================
    print("\n--- Generating Plots ---")
    gld_pct = np.array([w[1]*100 for lab, w in WEIGHT_SCHEMES])

    # Plot 1: DM t vs GLD weight — the core figure
    fig, ax = plt.subplots(1, 1, figsize=(10, 6.5))
    ax.plot(gld_pct, dm_qlike_t, marker='o', linewidth=2.2, markersize=9,
            color='steelblue', label='Portfolio QLIKE DM')
    ax.plot(gld_pct, dm_fz1_t, marker='s', linewidth=2.0, markersize=8,
            color='darkorange', label='FZ 1% DM')
    ax.plot(gld_pct, dm_fz25_t, marker='^', linewidth=2.0, markersize=8,
            color='forestgreen', label='FZ 2.5% DM')
    ax.axhline(3.0, color='red', linestyle='--', lw=1.2, label='Harvey |t|=3.0')
    ax.axhline(-3.0, color='red', linestyle='--', lw=1.2)
    ax.axhline(1.96, color='grey', linestyle=':', lw=1, label='|t|=1.96')
    ax.axhline(-1.96, color='grey', linestyle=':', lw=1)
    ax.axhline(0, color='black', lw=0.6)
    ax.set_xlabel('GLD Weight (%)')
    ax.set_ylabel('DM t-statistic (ASYM vs SYMM; +t = ASYM better)')
    ax.set_title(f'{EXPERIMENT_ID}: DM t vs GLD Weight — DCC-A4f-ASYM vs DCC-A4f-SYMM\n'
                 f'(Hypothesis: commodity-heavy portfolios amplify GVZ channel)')
    ax.set_xticks(gld_pct)
    ax.set_xticklabels([lab for lab, w in WEIGHT_SCHEMES])
    ax.grid(alpha=0.3)
    ax.legend(loc='best', fontsize=9)
    # Annotate values
    for i, lab in enumerate(labels_order):
        ax.annotate(f'{dm_qlike_t[i]:+.2f}', (gld_pct[i], dm_qlike_t[i]),
                    textcoords="offset points", xytext=(0, 8),
                    ha='center', fontsize=8, color='steelblue')
    plt.tight_layout()
    p1 = os.path.join(SCRIPT_DIR, 'k1093_dm_weight_curve.png')
    plt.savefig(p1, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p1}")

    # Plot 2: VaR Trinity by weight and alpha
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax_i, alpha in enumerate(ALPHA_LEVELS):
        ax = axes[ax_i]
        akey = f"alpha_{alpha:.3f}"
        width = 0.25
        x = np.arange(len(labels_order))
        for mi, m in enumerate(MODELS):
            viol_rates = []
            for lab in labels_order:
                t = results['per_weight'][lab]['models'][m]['var_tests'][akey]
                viol_rates.append(t['violation_rate'])
            ax.bar(x + (mi-1)*width, viol_rates, width, label=m, alpha=0.85,
                   edgecolor='black')
        ax.axhline(alpha, color='red', linestyle='--', lw=1.2,
                   label=f'Expected α={alpha:.3f}')
        ax.set_xticks(x)
        ax.set_xticklabels(labels_order)
        ax.set_xlabel('Portfolio (SPY/GLD)')
        ax.set_ylabel('Violation Rate')
        ax.set_title(f'Violation Rate at α={alpha*100:.1f}%')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)
    plt.suptitle(f'{EXPERIMENT_ID}: VaR Violation Rates by Weight × Model')
    plt.tight_layout()
    p2 = os.path.join(SCRIPT_DIR, 'k1093_trinity_by_weight.png')
    plt.savefig(p2, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p2}")

    # Plot 3: FZ mean by weight × model
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    for ax_i, alpha in enumerate(ALPHA_LEVELS):
        ax = axes[ax_i]
        akey = f"alpha_{alpha:.3f}"
        width = 0.25
        x = np.arange(len(labels_order))
        for mi, m in enumerate(MODELS):
            vals = [results['per_weight'][lab]['fz_mean'][m][akey] for lab in labels_order]
            ax.bar(x + (mi-1)*width, vals, width, label=m, alpha=0.85,
                   edgecolor='black')
        ax.set_xticks(x)
        ax.set_xticklabels(labels_order)
        ax.set_xlabel('Portfolio (SPY/GLD)')
        ax.set_ylabel('Mean FZ Score (lower = better)')
        ax.set_title(f'FZ Score at α={alpha*100:.1f}%')
        ax.legend(fontsize=8)
        ax.grid(axis='y', alpha=0.3)
    plt.suptitle(f'{EXPERIMENT_ID}: FZ Joint VaR-ES Score by Weight × Model')
    plt.tight_layout()
    p3 = os.path.join(SCRIPT_DIR, 'k1093_fz_by_weight.png')
    plt.savefig(p3, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p3}")

    # Plot 4: Portfolio Sharpe by weight (context, not the core test)
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    sharpe_vals = [results['per_weight'][lab]['sharpe']['sharpe'] for lab in labels_order]
    mean_vals = [results['per_weight'][lab]['sharpe']['annual_mean']*100 for lab in labels_order]
    vol_vals = [results['per_weight'][lab]['sharpe']['annual_vol']*100 for lab in labels_order]
    x = np.arange(len(labels_order))
    ax2 = ax.twinx()
    bars = ax.bar(x, sharpe_vals, color='steelblue', alpha=0.7, edgecolor='black',
                  label='Sharpe (annualized)')
    ax2.plot(x, mean_vals, color='darkorange', marker='o', lw=2,
             label='Annual mean return (%)')
    ax2.plot(x, vol_vals, color='forestgreen', marker='s', lw=2,
             label='Annual vol (%)')
    ax.set_xticks(x)
    ax.set_xticklabels(labels_order)
    ax.set_xlabel('Portfolio (SPY/GLD)')
    ax.set_ylabel('Sharpe Ratio')
    ax2.set_ylabel('Return / Vol (%)')
    ax.set_title(f'{EXPERIMENT_ID}: Portfolio Sharpe by Weight (OOS 2013-2026)')
    # Combine legends
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc='best', fontsize=9)
    for i, s in enumerate(sharpe_vals):
        ax.annotate(f'{s:.2f}', (x[i], s),
                    textcoords="offset points", xytext=(0, 5),
                    ha='center', fontsize=9)
    plt.tight_layout()
    p4 = os.path.join(SCRIPT_DIR, 'k1093_sharpe_by_weight.png')
    plt.savefig(p4, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p4}")

    # ============================================================
    # 12. SAVE
    # ============================================================
    results_safe = to_json_safe(results)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_safe, f, indent=2)
    print(f"\nResults saved: {RESULTS_PATH}")
    print(f"Total runtime: {runtime:.1f}s")


if __name__ == '__main__':
    main()
