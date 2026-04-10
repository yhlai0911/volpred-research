#!/usr/bin/env python3
"""
K1041: DCC-A4f Portfolio VaR (SPY/GLD)
======================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1028: DCC-A4f beats DCC-GJR (DM t=2.58) for SPY/QQQ portfolio variance,
         but DCC ~= CCC because SPY-QQQ correlation is very stable.
  K891:  DCC-GARCH Portfolio VaR for 50/50 SPY/GLD showed NULL result.
  K920:  Copula-GARCH SPY/GLD -- Student-t copula best, COVID lambda=0.364.
  K1036: CF-Rolling is best univariate VaR method (6/6 Trinity PASS).

  Core question: SPY/GLD correlation changes DRAMATICALLY in crises
  (K920: COVID lambda=0.364 vs normal). DCC should capture this better
  than CCC. Combined with A4f marginals (which improve univariate vol),
  DCC-A4f might be the best portfolio VaR method.

Design (2x2 factorial):
  Marginals: GJR, A4f (tau=theta0+theta1*VIX^2, g=GJR unit-var)
  Correlation: CCC (constant), DCC(1,1) (time-varying)
  => 4 models: CCC-GJR, DCC-GJR, CCC-A4f, DCC-A4f

  VaR method: CF-Rolling (252d window on portfolio std residuals)
  This is the best VaR method from K1036.

Portfolio: 50/50 SPY/GLD (daily rebalanced).
Data: yfinance SPY, GLD, ^VIX, 2005-01-01 to 2026-04-10.
OOS: 2019-01-01 onwards, window=2000, refit/63d.
Alpha: 1%, 2.5%.
Seed: 42.

Evaluation:
  - Trinity test (Kupiec + CC + Basel) at 1% and 2.5%
  - ES backtest (Acerbi-Szekely Z1)
  - DM test on portfolio variance QLIKE
  - Rolling correlation plot
  - COVID sub-sample analysis (2020-02 to 2020-06)

References:
  - Engle (2002). Dynamic Conditional Correlation. JBES 20(3).
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and
    Macroeconomic Fundamentals. RES 95(3):776-797. [A4f]
  - Patton (2011). Volatility forecast comparison using imperfect
    proxies. JoE 160(1). [QLIKE]
  - Kupiec (1995). Techniques for Verifying the Accuracy of Risk
    Measurement Models. J Derivatives 3:73-84.
  - Christoffersen (1998). Evaluating Interval Forecasts. Int Econ Rev.
  - Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320.
  - Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
  - K1028, K891, K920, K1036.

Author: VolPred Research System
Date: 2026-04-11
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
from scipy.stats import norm, chi2
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1041"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1041_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
CF_ROLLING_WINDOW = 252
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS = np.array([0.5, 0.5])

print("=" * 70)
print(f"{EXPERIMENT_ID}: DCC-A4f Portfolio VaR (SPY/GLD)")
print(f"  Models: CCC-GJR, DCC-GJR, CCC-A4f, DCC-A4f")
print(f"  VaR: CF-Rolling (252d)")
print(f"  Portfolio: 50/50 SPY/GLD")
print("=" * 70)


# ============================================================
# 1. NUMBA KERNELS
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
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    """A4f multiplicative GARCH-X: h_t = tau_t * g_t"""
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
        tau[t] = theta0 + theta1 * vix2[t-1]   # lagged VIX^2
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
def a4f_nll(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit
def dcc_filter(eps1, eps2, a, b, qbar11, qbar22, qbar12):
    """
    Scalar DCC(1,1) filter given pre-computed Qbar.
    Returns rho array.
    """
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
    """DCC log-likelihood (second stage)."""
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
# 2. MODEL FITTING
# ============================================================
def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) by MLE with multiple starting values."""
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


def fit_a4f(returns, vix2):
    """Fit A4f multiplicative GARCH-X by MLE."""
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
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
    h, tau, g = a4f_recursion(*best_res.x, returns, vix2)
    return {'params': best_res.x.tolist(), 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success}


def fit_dcc(eps1, eps2):
    """Fit scalar DCC(1,1) by maximising 2nd-stage loglik."""
    T = len(eps1)
    # Compute Qbar from data
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
    return {
        'a': float(a_hat), 'b': float(b_hat),
        'rho': rho,
        'qbar11': float(qbar11), 'qbar22': float(qbar22),
        'qbar12': float(qbar12),
        'converged': best_res.success
    }


# ============================================================
# 3. OOS FORECASTING
# ============================================================
def oos_forecast_all(ret_spy, ret_gld, vix2, dates, oos_start,
                     window=WINDOW, refit_every=REFIT_EVERY):
    """
    OOS portfolio variance forecast for 4 models:
      CCC-GJR, DCC-GJR, CCC-A4f, DCC-A4f

    Returns dict with arrays aligned to dates[oos_start_idx:].
    """
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret_spy)
    n_oos = T - oos_idx

    # Storage for forecasts
    models = ['CCC-GJR', 'DCC-GJR', 'CCC-A4f', 'DCC-A4f']
    h_spy = {m: np.full(n_oos, np.nan) for m in models}
    h_gld = {m: np.full(n_oos, np.nan) for m in models}
    rho_f = {m: np.full(n_oos, np.nan) for m in models}
    pvar = {m: np.full(n_oos, np.nan) for m in models}

    # State tracking for recursive forecasting
    state = {}
    for m in models:
        state[m] = {
            'h1_prev': np.nan, 'h2_prev': np.nan,
            'g1_prev': np.nan, 'g2_prev': np.nan,
            'gjr1_p': None, 'gjr2_p': None,
            'a4f1_p': None, 'a4f2_p': None,
            'dcc_a': 0.0, 'dcc_b': 0.0,
            'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
            'ccc_rho': 0.0,
            'last_fit': -refit_every,
        }

    for i in range(n_oos):
        t = oos_idx + i
        if i % 200 == 0:
            elapsed = time.time() - START_TIME
            print(f"  OOS day {i}/{n_oos} ({elapsed:.0f}s)")

        # Check if we need to refit
        need_refit = (i - state['CCC-GJR']['last_fit'] >= refit_every
                      or state['CCC-GJR']['gjr1_p'] is None)

        if need_refit:
            s = max(0, t - window)
            tr_spy = ret_spy[s:t]
            tr_gld = ret_gld[s:t]
            tr_vix2 = vix2[s:t]

            # Fit GJR for both assets
            gjr_spy = fit_gjr(tr_spy)
            gjr_gld = fit_gjr(tr_gld)

            # Fit A4f for both assets
            a4f_spy = fit_a4f(tr_spy, tr_vix2)
            a4f_gld = fit_a4f(tr_gld, tr_vix2)

            # Standardized residuals for DCC
            eps_gjr_spy = tr_spy / np.sqrt(gjr_spy['h'])
            eps_gjr_gld = tr_gld / np.sqrt(gjr_gld['h'])
            eps_a4f_spy = tr_spy / np.sqrt(a4f_spy['h'])
            eps_a4f_gld = tr_gld / np.sqrt(a4f_gld['h'])

            # CCC: constant correlation from training window
            ccc_rho_gjr = float(np.corrcoef(eps_gjr_spy, eps_gjr_gld)[0, 1])
            ccc_rho_a4f = float(np.corrcoef(eps_a4f_spy, eps_a4f_gld)[0, 1])

            # DCC: fit on training residuals
            dcc_gjr = fit_dcc(eps_gjr_spy, eps_gjr_gld)
            dcc_a4f = fit_dcc(eps_a4f_spy, eps_a4f_gld)

            # Update states for CCC-GJR
            for m in ['CCC-GJR', 'DCC-GJR']:
                state[m]['gjr1_p'] = gjr_spy['params']
                state[m]['gjr2_p'] = gjr_gld['params']
                state[m]['h1_prev'] = float(gjr_spy['h'][-1])
                state[m]['h2_prev'] = float(gjr_gld['h'][-1])
            state['CCC-GJR']['ccc_rho'] = ccc_rho_gjr
            state['DCC-GJR']['dcc_a'] = dcc_gjr['a']
            state['DCC-GJR']['dcc_b'] = dcc_gjr['b']
            state['DCC-GJR']['qbar11'] = dcc_gjr['qbar11']
            state['DCC-GJR']['qbar22'] = dcc_gjr['qbar22']
            state['DCC-GJR']['qbar12'] = dcc_gjr['qbar12']
            # last DCC rho from training
            state['DCC-GJR']['rho_prev'] = float(dcc_gjr['rho'][-1])
            state['DCC-GJR']['eps1_prev'] = float(eps_gjr_spy[-1])
            state['DCC-GJR']['eps2_prev'] = float(eps_gjr_gld[-1])
            # q_prev
            state['DCC-GJR']['q11_prev'] = float(dcc_gjr['qbar11'])
            state['DCC-GJR']['q22_prev'] = float(dcc_gjr['qbar22'])
            state['DCC-GJR']['q12_prev'] = float(dcc_gjr['qbar12'])

            for m in ['CCC-A4f', 'DCC-A4f']:
                state[m]['a4f1_p'] = a4f_spy['params']
                state[m]['a4f2_p'] = a4f_gld['params']
                state[m]['h1_prev'] = float(a4f_spy['h'][-1])
                state[m]['h2_prev'] = float(a4f_gld['h'][-1])
                state[m]['g1_prev'] = float(a4f_spy['g'][-1])
                state[m]['g2_prev'] = float(a4f_gld['g'][-1])
            state['CCC-A4f']['ccc_rho'] = ccc_rho_a4f
            state['DCC-A4f']['dcc_a'] = dcc_a4f['a']
            state['DCC-A4f']['dcc_b'] = dcc_a4f['b']
            state['DCC-A4f']['qbar11'] = dcc_a4f['qbar11']
            state['DCC-A4f']['qbar22'] = dcc_a4f['qbar22']
            state['DCC-A4f']['qbar12'] = dcc_a4f['qbar12']
            state['DCC-A4f']['rho_prev'] = float(dcc_a4f['rho'][-1])
            state['DCC-A4f']['eps1_prev'] = float(eps_a4f_spy[-1])
            state['DCC-A4f']['eps2_prev'] = float(eps_a4f_gld[-1])
            state['DCC-A4f']['q11_prev'] = float(dcc_a4f['qbar11'])
            state['DCC-A4f']['q22_prev'] = float(dcc_a4f['qbar22'])
            state['DCC-A4f']['q12_prev'] = float(dcc_a4f['qbar12'])

            for m in models:
                state[m]['last_fit'] = i

        # ---- Recursive one-step forecast for each model ----
        r1_prev = ret_spy[t-1]
        r2_prev = ret_gld[t-1]
        v2_prev = vix2[t-1]  # lagged VIX^2

        # --- GJR models ---
        for m in ['CCC-GJR', 'DCC-GJR']:
            p1 = state[m]['gjr1_p']
            p2 = state[m]['gjr2_p']
            # h[t] = omega + alpha*r^2_{t-1} + gamma*r^2_{t-1}*I + beta*h_{t-1}
            ind1 = 1.0 if r1_prev < 0 else 0.0
            ind2 = 1.0 if r2_prev < 0 else 0.0
            h1_t = p1[0] + p1[1]*r1_prev**2 + p1[2]*r1_prev**2*ind1 + p1[3]*state[m]['h1_prev']
            h2_t = p2[0] + p2[1]*r2_prev**2 + p2[2]*r2_prev**2*ind2 + p2[3]*state[m]['h2_prev']
            h1_t = max(h1_t, 1e-16)
            h2_t = max(h2_t, 1e-16)
            state[m]['h1_prev'] = h1_t
            state[m]['h2_prev'] = h2_t
            h_spy[m][i] = h1_t
            h_gld[m][i] = h2_t

        # --- A4f models ---
        for m in ['CCC-A4f', 'DCC-A4f']:
            p1 = state[m]['a4f1_p']
            p2 = state[m]['a4f2_p']
            # tau = theta0 + theta1 * vix2_{t-1}
            tau1 = p1[0] + p1[1] * v2_prev
            tau2 = p2[0] + p2[1] * v2_prev
            tau1 = max(tau1, 1e-16)
            tau2 = max(tau2, 1e-16)
            # g recursion on demeaned returns
            u1_prev = r1_prev / np.sqrt(tau1)
            u2_prev = r2_prev / np.sqrt(tau2)
            ind1 = 1.0 if r1_prev < 0 else 0.0
            ind2 = 1.0 if r2_prev < 0 else 0.0
            g1_t = p1[2] + p1[3]*u1_prev**2 + p1[4]*u1_prev**2*ind1 + p1[5]*state[m]['g1_prev']
            g2_t = p2[2] + p2[3]*u2_prev**2 + p2[4]*u2_prev**2*ind2 + p2[5]*state[m]['g2_prev']
            g1_t = max(g1_t, 1e-16)
            g2_t = max(g2_t, 1e-16)
            h1_t = tau1 * g1_t
            h2_t = tau2 * g2_t
            state[m]['g1_prev'] = g1_t
            state[m]['g2_prev'] = g2_t
            state[m]['h1_prev'] = h1_t
            state[m]['h2_prev'] = h2_t
            h_spy[m][i] = h1_t
            h_gld[m][i] = h2_t

        # --- CCC: use constant rho ---
        for m in ['CCC-GJR', 'CCC-A4f']:
            rho_f[m][i] = state[m]['ccc_rho']

        # --- DCC: recursive Q filter for one step ---
        for m in ['DCC-GJR', 'DCC-A4f']:
            a_dcc = state[m]['dcc_a']
            b_dcc = state[m]['dcc_b']
            c_dcc = 1.0 - a_dcc - b_dcc
            e1p = state[m].get('eps1_prev', 0.0)
            e2p = state[m].get('eps2_prev', 0.0)
            q11 = c_dcc * state[m]['qbar11'] + a_dcc * e1p**2 + b_dcc * state[m].get('q11_prev', state[m]['qbar11'])
            q22 = c_dcc * state[m]['qbar22'] + a_dcc * e2p**2 + b_dcc * state[m].get('q22_prev', state[m]['qbar22'])
            q12 = c_dcc * state[m]['qbar12'] + a_dcc * e1p*e2p + b_dcc * state[m].get('q12_prev', state[m]['qbar12'])
            denom = np.sqrt(q11 * q22)
            rho_t = q12 / denom if denom > 1e-20 else 0.0
            rho_t = np.clip(rho_t, -0.9999, 0.9999)
            rho_f[m][i] = rho_t
            # Update DCC state
            # Current standardized residuals (for next step)
            eps1_now = r1_prev / np.sqrt(h_spy[m][i]) if h_spy[m][i] > 1e-16 else 0.0
            eps2_now = r2_prev / np.sqrt(h_gld[m][i]) if h_gld[m][i] > 1e-16 else 0.0
            state[m]['eps1_prev'] = eps1_now
            state[m]['eps2_prev'] = eps2_now
            state[m]['q11_prev'] = q11
            state[m]['q22_prev'] = q22
            state[m]['q12_prev'] = q12

        # --- Portfolio variance: w'Hw ---
        for m in models:
            s1 = np.sqrt(h_spy[m][i])
            s2 = np.sqrt(h_gld[m][i])
            r = rho_f[m][i]
            pv = WEIGHTS[0]**2 * h_spy[m][i] + WEIGHTS[1]**2 * h_gld[m][i] + \
                 2 * WEIGHTS[0] * WEIGHTS[1] * r * s1 * s2
            pvar[m][i] = max(pv, 1e-16)

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar,
        'h_spy': h_spy,
        'h_gld': h_gld,
        'rho': rho_f,
        'oos_dates': oos_dates,
        'oos_idx': oos_idx,
    }


# ============================================================
# 4. VaR COMPUTATION (CF-Rolling)
# ============================================================
def cf_quantile(alpha, skew, exkurt):
    """Cornish-Fisher expansion quantile."""
    z = norm.ppf(alpha)
    q = (z + (z**2 - 1) * skew / 6
         + (z**3 - 3*z) * exkurt / 24
         - (2*z**3 - 5*z) * skew**2 / 36)
    return q


def compute_cf_rolling_var(port_returns, port_sigma, alpha, cf_window=CF_ROLLING_WINDOW):
    """
    CF-Rolling VaR: use rolling skewness/kurtosis of standardized
    portfolio residuals with Cornish-Fisher expansion.
    """
    T = len(port_returns)
    var_series = np.full(T, np.nan)
    es_series = np.full(T, np.nan)

    std_resid = np.where(port_sigma > 1e-10,
                         port_returns / port_sigma,
                         0.0)

    for t in range(cf_window, T):
        window_resid = std_resid[t - cf_window:t]
        valid = np.isfinite(window_resid) & (np.abs(window_resid) < 20)
        if valid.sum() < 50:
            var_series[t] = port_sigma[t] * norm.ppf(alpha)
            continue
        wr = window_resid[valid]
        sk = float(stats.skew(wr))
        ek = float(stats.kurtosis(wr))  # excess kurtosis
        # Clamp extreme values
        sk = np.clip(sk, -3, 3)
        ek = np.clip(ek, -2, 30)
        q_cf = cf_quantile(alpha, sk, ek)
        var_series[t] = port_sigma[t] * q_cf

        # ES via expected shortfall of CF distribution (approximate)
        # Use empirical ES of standardized residuals below CF quantile
        below = wr[wr < q_cf]
        if len(below) >= 3:
            es_series[t] = port_sigma[t] * np.mean(below)
        else:
            es_series[t] = var_series[t] * 1.3  # conservative fallback

    return var_series, es_series


# ============================================================
# 5. BACKTESTING
# ============================================================
def kupiec_test(violations, n, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n1 = int(np.sum(violations))
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0

    if n1 == 0 or n1 == n:
        return {'stat': 0.0, 'p_value': 1.0, 'violations': n1, 'rate': pi_hat, 'pass': True}

    lr = -2 * (n1 * np.log(alpha) + n0 * np.log(1 - alpha)
               - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
    p_val = 1 - chi2.cdf(lr, df=1)

    return {
        'stat': float(lr),
        'p_value': float(p_val),
        'violations': n1,
        'rate': float(pi_hat),
        'expected_rate': float(alpha),
        'pass': p_val > 0.05
    }


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage test."""
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

    return {
        'stat': float(lr_ind),
        'p_value': float(p_val),
        'clusters': int(t11),
        'pass': p_val > 0.05
    }


def basel_traffic_light(violations, n, alpha):
    """Basel traffic light test (250-day convention)."""
    n1 = int(np.sum(violations))
    expected = n * alpha

    # Use 250-day blocks
    n_blocks = max(1, n // 250)
    avg_violations_per_block = n1 / n_blocks

    if alpha <= 0.01:
        thresholds = {'green': 4, 'yellow': 9}
    else:
        thresholds = {'green': int(250 * alpha * 1.5) + 1,
                      'yellow': int(250 * alpha * 2.5) + 1}

    if avg_violations_per_block <= thresholds['green']:
        color = 'Green'
    elif avg_violations_per_block <= thresholds['yellow']:
        color = 'Yellow'
    else:
        color = 'Red'

    return {
        'color': color,
        'violations_per_block': float(avg_violations_per_block),
        'n_blocks': n_blocks,
        'pass': color == 'Green'
    }


def es_backtest_acerbi_szekely(port_returns, var_series, es_series, alpha):
    """Acerbi-Szekely Z1 test for ES."""
    valid = np.isfinite(var_series) & np.isfinite(es_series) & np.isfinite(port_returns)
    r = port_returns[valid]
    v = var_series[valid]
    es = es_series[valid]
    n = len(r)

    # Z1: sum(r_t * I(r_t < VaR_t)) / (N * alpha * ES_avg) - 1
    violations = r < v
    n_viol = int(np.sum(violations))

    if n_viol < 3:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': n_viol}

    numerator = np.sum(r[violations])
    es_avg = np.mean(es[violations])
    if abs(es_avg) < 1e-12:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': n_viol}

    z1 = numerator / (n * alpha * es_avg) - 1
    # Under H0, Z1 ~ N(0, 1) approximately
    p_val = 2 * norm.cdf(-abs(z1))

    return {
        'z_stat': float(z1),
        'p_value': float(p_val),
        'pass': p_val > 0.05,
        'n_violations': n_viol
    }


def trinity_test(port_returns, var_series, es_series, alpha):
    """Run Kupiec + Christoffersen + Basel + ES tests."""
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

    trinity_pass = kupiec['pass'] and cc['pass'] and basel['pass']

    return {
        'kupiec': kupiec,
        'christoffersen': cc,
        'basel': basel,
        'es_test': es_test,
        'trinity_pass': trinity_pass,
        'n_oos': n,
        'violation_rate': float(kupiec['rate']),
    }


# ============================================================
# 6. DM TEST
# ============================================================
def dm_test_qlike(actual_r2, forecast_var1, forecast_var2):
    """
    Diebold-Mariano test on QLIKE loss.
    QLIKE = log(h) + r^2/h
    H0: equal predictive accuracy
    Returns t-stat, p-value. Negative t means model 1 is better.
    """
    valid = np.isfinite(actual_r2) & np.isfinite(forecast_var1) & np.isfinite(forecast_var2)
    valid &= (forecast_var1 > 0) & (forecast_var2 > 0)
    r2 = actual_r2[valid]
    h1 = forecast_var1[valid]
    h2 = forecast_var2[valid]

    loss1 = np.log(h1) + r2 / h1
    loss2 = np.log(h2) + r2 / h2
    d = loss1 - loss2
    n = len(d)

    d_bar = np.mean(d)
    # Newey-West HAC variance with lag=int(n^(1/3))
    max_lag = int(n ** (1/3))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * w * gamma_k
    se = np.sqrt(nw_var / n)
    t_stat = d_bar / se if se > 1e-12 else 0.0
    p_val = 2 * norm.cdf(-abs(t_stat))

    return {
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'mean_loss_diff': float(d_bar),
        'n': n,
        'significant_harvey': abs(t_stat) > 3.0,
    }


# ============================================================
# 7. DATA LOADING
# ============================================================
def load_data():
    """Load SPY, GLD, VIX from yfinance."""
    import yfinance as yf

    tickers = ['SPY', 'GLD', '^VIX']
    print("Downloading data from yfinance...")
    raw = yf.download(tickers, start='2004-01-01', end='2026-12-31',
                      auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw['Close'][['SPY', 'GLD']].dropna()
        vix = raw['Close']['^VIX'].reindex(close.index).ffill().bfill()
    else:
        raise ValueError("Expected MultiIndex columns from yfinance")

    ret_spy = np.log(close['SPY'] / close['SPY'].shift(1))
    ret_gld = np.log(close['GLD'] / close['GLD'].shift(1))

    df = pd.DataFrame({
        'ret_spy': ret_spy,
        'ret_gld': ret_gld,
        'vix': vix,
        'vix2': (vix / 100.0) ** 2 / 252.0,  # annualised VIX -> daily variance scale
        'r2_spy': ret_spy ** 2,
        'r2_gld': ret_gld ** 2,
    }).dropna()

    # Portfolio return (simple, not log, for VaR evaluation)
    # But for portfolio return we need simple returns
    close_spy = close['SPY'].reindex(df.index)
    close_gld = close['GLD'].reindex(df.index)
    simple_ret_spy = close_spy.pct_change()
    simple_ret_gld = close_gld.pct_change()
    df['port_ret'] = 0.5 * simple_ret_spy + 0.5 * simple_ret_gld

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total days: {len(df)}")
    print(f"SPY mean return: {df['ret_spy'].mean()*252:.4f}, vol: {df['ret_spy'].std()*np.sqrt(252):.4f}")
    print(f"GLD mean return: {df['ret_gld'].mean()*252:.4f}, vol: {df['ret_gld'].std()*np.sqrt(252):.4f}")
    print(f"SPY-GLD full-sample corr: {np.corrcoef(df['ret_spy'], df['ret_gld'])[0,1]:.4f}")
    return df


# ============================================================
# 8. MAIN
# ============================================================
def main():
    df = load_data()

    # OOS forecasting
    print("\n--- OOS Forecasting (4 models) ---")
    ret_spy = df['ret_spy'].values
    ret_gld = df['ret_gld'].values
    vix2 = df['vix2'].values
    dates = df.index.values

    forecasts = oos_forecast_all(ret_spy, ret_gld, vix2, dates, OOS_START)
    oos_dates = forecasts['oos_dates']
    n_oos = len(oos_dates)

    # Align portfolio returns
    oos_start_idx = forecasts['oos_idx']
    port_ret_oos = df['port_ret'].values[oos_start_idx:]
    r2_port_oos = port_ret_oos ** 2

    print(f"\nOOS period: {pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} to {pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')}")
    print(f"OOS days: {n_oos}")

    # ============================================================
    # 9. VaR EVALUATION
    # ============================================================
    print("\n--- VaR Evaluation (CF-Rolling) ---")
    models = ['CCC-GJR', 'DCC-GJR', 'CCC-A4f', 'DCC-A4f']
    results = {'experiment_id': EXPERIMENT_ID, 'models': {}}

    for m in models:
        print(f"\n  Model: {m}")
        port_sigma = np.sqrt(forecasts['pvar'][m])

        model_results = {'var_tests': {}}

        for alpha in ALPHA_LEVELS:
            var_series, es_series = compute_cf_rolling_var(
                port_ret_oos, port_sigma, alpha)

            # Skip initial NaN period
            valid = np.isfinite(var_series)
            n_valid = int(np.sum(valid))

            trinity = trinity_test(port_ret_oos, var_series, es_series, alpha)

            alpha_key = f"alpha_{alpha:.3f}"
            model_results['var_tests'][alpha_key] = trinity

            print(f"    alpha={alpha:.3f}: violations={trinity['violation_rate']:.4f} "
                  f"(expected {alpha:.4f}), "
                  f"Trinity={'PASS' if trinity['trinity_pass'] else 'FAIL'}, "
                  f"Kupiec p={trinity['kupiec']['p_value']:.4f}, "
                  f"CC p={trinity['christoffersen']['p_value']:.4f}, "
                  f"Basel={trinity['basel']['color']}, "
                  f"ES p={trinity['es_test']['p_value']:.4f}")

        results['models'][m] = model_results

    # ============================================================
    # 10. DM TESTS ON PORTFOLIO QLIKE
    # ============================================================
    print("\n--- DM Tests (Portfolio QLIKE) ---")
    dm_results = {}
    pairs = [
        ('CCC-GJR', 'DCC-GJR'),
        ('CCC-A4f', 'DCC-A4f'),
        ('CCC-GJR', 'CCC-A4f'),
        ('DCC-GJR', 'DCC-A4f'),
        ('CCC-GJR', 'DCC-A4f'),
    ]
    for m1, m2 in pairs:
        dm = dm_test_qlike(r2_port_oos, forecasts['pvar'][m1], forecasts['pvar'][m2])
        key = f"{m1}_vs_{m2}"
        dm_results[key] = dm
        direction = f"{m1} better" if dm['t_stat'] < 0 else f"{m2} better"
        sig = "***" if dm['significant_harvey'] else ("*" if dm['p_value'] < 0.05 else "")
        print(f"  {m1} vs {m2}: DM t={dm['t_stat']:+.3f} ({direction}) {sig}")

    results['dm_tests'] = dm_results

    # ============================================================
    # 11. CORRELATION ANALYSIS
    # ============================================================
    print("\n--- Correlation Analysis ---")
    corr_stats = {}
    for m in models:
        rho = forecasts['rho'][m]
        valid = np.isfinite(rho)
        rho_v = rho[valid]
        corr_stats[m] = {
            'mean_rho': float(np.mean(rho_v)),
            'std_rho': float(np.std(rho_v)),
            'min_rho': float(np.min(rho_v)),
            'max_rho': float(np.max(rho_v)),
        }
        print(f"  {m}: rho mean={np.mean(rho_v):.4f}, std={np.std(rho_v):.4f}, "
              f"range=[{np.min(rho_v):.4f}, {np.max(rho_v):.4f}]")

    results['correlation_stats'] = corr_stats

    # COVID sub-sample (2020-02 to 2020-06)
    print("\n--- COVID Sub-sample (2020-02 to 2020-06) ---")
    covid_mask = (pd.DatetimeIndex(oos_dates) >= '2020-02-01') & \
                 (pd.DatetimeIndex(oos_dates) <= '2020-06-30')
    covid_stats = {}
    for m in models:
        rho_covid = forecasts['rho'][m][covid_mask]
        valid = np.isfinite(rho_covid)
        if valid.sum() > 0:
            rho_v = rho_covid[valid]
            covid_stats[m] = {
                'mean_rho': float(np.mean(rho_v)),
                'min_rho': float(np.min(rho_v)),
                'max_rho': float(np.max(rho_v)),
                'range': float(np.max(rho_v) - np.min(rho_v)),
            }
            print(f"  {m}: COVID rho mean={np.mean(rho_v):.4f}, "
                  f"range=[{np.min(rho_v):.4f}, {np.max(rho_v):.4f}]")

    results['covid_correlation'] = covid_stats

    # ============================================================
    # 12. MEAN QLIKE
    # ============================================================
    print("\n--- Mean QLIKE ---")
    qlike_results = {}
    for m in models:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_port_oos)
        q = np.log(pv[valid]) + r2_port_oos[valid] / pv[valid]
        qlike_results[m] = float(np.mean(q))
        print(f"  {m}: QLIKE = {np.mean(q):.6f}")

    results['mean_qlike'] = qlike_results

    # ============================================================
    # 13. PLOTS
    # ============================================================
    print("\n--- Generating plots ---")

    # Plot 1: Rolling correlation comparison
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    oos_pd = pd.DatetimeIndex(oos_dates)

    ax = axes[0]
    for m in ['CCC-GJR', 'DCC-GJR']:
        rho = forecasts['rho'][m]
        label = m
        ax.plot(oos_pd, rho, label=label, alpha=0.8,
                linewidth=1.5 if 'DCC' in m else 0.8,
                linestyle='-' if 'DCC' in m else '--')
    ax.set_ylabel('Correlation (ρ)')
    ax.set_title('SPY-GLD Correlation: CCC vs DCC (GJR marginals)')
    ax.legend()
    ax.axhline(y=0, color='grey', linestyle=':', alpha=0.5)
    ax.axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
               alpha=0.15, color='red', label='COVID')

    ax = axes[1]
    for m in ['CCC-A4f', 'DCC-A4f']:
        rho = forecasts['rho'][m]
        label = m
        ax.plot(oos_pd, rho, label=label, alpha=0.8,
                linewidth=1.5 if 'DCC' in m else 0.8,
                linestyle='-' if 'DCC' in m else '--')
    ax.set_ylabel('Correlation (ρ)')
    ax.set_title('SPY-GLD Correlation: CCC vs DCC (A4f marginals)')
    ax.legend()
    ax.axhline(y=0, color='grey', linestyle=':', alpha=0.5)
    ax.axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
               alpha=0.15, color='red', label='COVID')
    ax.set_xlabel('Date')

    plt.tight_layout()
    corr_path = os.path.join(SCRIPT_DIR, 'k1041_rolling_correlation.png')
    plt.savefig(corr_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {corr_path}")

    # Plot 2: Portfolio VaR comparison (2.5%)
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    for idx, m in enumerate(models):
        ax = axes[idx // 2][idx % 2]
        port_sigma = np.sqrt(forecasts['pvar'][m])
        var_025, _ = compute_cf_rolling_var(port_ret_oos, port_sigma, 0.025)

        valid = np.isfinite(var_025)
        ax.plot(oos_pd[valid], port_ret_oos[valid], color='grey', alpha=0.3,
                linewidth=0.5, label='Portfolio Return')
        ax.plot(oos_pd[valid], var_025[valid], color='red', alpha=0.8,
                linewidth=1.0, label='VaR 2.5%')

        # Mark violations
        violations = (port_ret_oos < var_025) & valid
        if np.any(violations):
            ax.scatter(oos_pd[violations], port_ret_oos[violations],
                      color='red', s=10, zorder=5, alpha=0.7)

        viol_rate = np.sum(violations) / np.sum(valid)
        ax.set_title(f'{m}: VaR 2.5% (violations={viol_rate:.4f})')
        ax.legend(fontsize=8)
        ax.set_ylabel('Return')

    axes[1][0].set_xlabel('Date')
    axes[1][1].set_xlabel('Date')
    plt.tight_layout()
    var_path = os.path.join(SCRIPT_DIR, 'k1041_portfolio_var.png')
    plt.savefig(var_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {var_path}")

    # ============================================================
    # 14. SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Trinity scorecard
    trinity_scores = {}
    for m in models:
        n_pass = 0
        n_total = 0
        for alpha in ALPHA_LEVELS:
            alpha_key = f"alpha_{alpha:.3f}"
            if results['models'][m]['var_tests'][alpha_key]['trinity_pass']:
                n_pass += 1
            n_total += 1
        trinity_scores[m] = f"{n_pass}/{n_total}"
        print(f"  {m}: Trinity {n_pass}/{n_total}")

    results['trinity_scores'] = trinity_scores

    # Best model by QLIKE
    best_model = min(qlike_results, key=qlike_results.get)
    print(f"\n  Best QLIKE: {best_model} ({qlike_results[best_model]:.6f})")

    # DCC value for SPY/GLD
    ccc_gjr_q = qlike_results['CCC-GJR']
    dcc_gjr_q = qlike_results['DCC-GJR']
    ccc_a4f_q = qlike_results['CCC-A4f']
    dcc_a4f_q = qlike_results['DCC-A4f']

    dcc_value_gjr = (ccc_gjr_q - dcc_gjr_q) / abs(ccc_gjr_q) * 100
    dcc_value_a4f = (ccc_a4f_q - dcc_a4f_q) / abs(ccc_a4f_q) * 100
    a4f_value_ccc = (ccc_gjr_q - ccc_a4f_q) / abs(ccc_gjr_q) * 100
    a4f_value_dcc = (dcc_gjr_q - dcc_a4f_q) / abs(dcc_gjr_q) * 100

    print(f"\n  DCC improvement (GJR): {dcc_value_gjr:+.2f}%")
    print(f"  DCC improvement (A4f): {dcc_value_a4f:+.2f}%")
    print(f"  A4f improvement (CCC): {a4f_value_ccc:+.2f}%")
    print(f"  A4f improvement (DCC): {a4f_value_dcc:+.2f}%")

    results['qlike_improvements'] = {
        'dcc_over_ccc_gjr_pct': float(dcc_value_gjr),
        'dcc_over_ccc_a4f_pct': float(dcc_value_a4f),
        'a4f_over_gjr_ccc_pct': float(a4f_value_ccc),
        'a4f_over_gjr_dcc_pct': float(a4f_value_dcc),
    }

    # Answers to core questions
    print("\n--- Core Questions ---")

    # Q1: Is DCC more valuable for SPY/GLD than SPY/QQQ?
    rho_dcc_gjr_std = corr_stats['DCC-GJR']['std_rho']
    rho_ccc_gjr_std = corr_stats['CCC-GJR']['std_rho']
    print(f"  Q1 DCC value: DCC-GJR rho_std={rho_dcc_gjr_std:.4f} "
          f"(CCC std={rho_ccc_gjr_std:.4f})")
    print(f"     SPY/GLD correlation is {'variable' if rho_dcc_gjr_std > 0.05 else 'stable'}")

    # Q2: A4f marginals improve portfolio VaR?
    print(f"  Q2 A4f value: QLIKE improvement = {a4f_value_ccc:+.2f}% (CCC), {a4f_value_dcc:+.2f}% (DCC)")

    # Q3: DCC-A4f is best?
    print(f"  Q3 Best model: {best_model} (QLIKE={qlike_results[best_model]:.6f})")

    results['core_answers'] = {
        'q1_dcc_value_for_spy_gld': {
            'dcc_rho_std': float(rho_dcc_gjr_std),
            'dcc_rho_range': corr_stats['DCC-GJR']['max_rho'] - corr_stats['DCC-GJR']['min_rho'],
            'correlation_is_variable': rho_dcc_gjr_std > 0.05,
        },
        'q2_a4f_improves_portfolio_var': a4f_value_ccc > 0 or a4f_value_dcc > 0,
        'q3_best_model': best_model,
    }

    # Metadata
    elapsed = time.time() - START_TIME
    results['metadata'] = {
        'experiment_id': EXPERIMENT_ID,
        'data_source': 'yfinance (SPY, GLD, ^VIX)',
        'data_period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'n_oos': n_oos,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'cf_rolling_window': CF_ROLLING_WINDOW,
        'alpha_levels': ALPHA_LEVELS,
        'portfolio_weights': WEIGHTS.tolist(),
        'seed': 42,
        'runtime_seconds': round(elapsed, 1),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    # Save results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Runtime: {elapsed:.1f}s")

    return results


if __name__ == '__main__':
    main()
