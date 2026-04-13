#!/usr/bin/env python3
"""
K1092: Asset-Matched DCC-A4f Portfolio VaR (SPY-VIX + GLD-GVZ)
==============================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1041: DCC-A4f (both assets use VIX²) vs DCC-GJR for 50/50 SPY/GLD
         portfolio VaR. DM Harvey PASS (t=3.83), DCC-A4f = best model.
         BUT both marginals use VIX², which is equity-centric.
  K1085: For GLD univariate, A4f-GVZ strictly dominates A4f-VIX.
         DM(GVZ vs VIX): t=+4.46, QLIKE improvement much larger.
  K1088: OVX on USO — commodity asset-matched theorem (DM t=4.48).
  K1091: Meta validation confirms equity uses VIX; matched-IV for
         commodity. Asset-matching is a universal principle.

  Question (H1): Does ASSET-MATCHED DCC-A4f (SPY-VIX² + GLD-GVZ²) beat
  K1041's SYMMETRIC DCC-A4f (both VIX²) on portfolio VaR?

Design (three DCC models):
  1. DCC-GJR         : both GJR, no exogenous regressor (baseline)
  2. DCC-A4f-SYMM    : SPY uses VIX², GLD uses VIX²   (=K1041 DCC-A4f)
  3. DCC-A4f-ASYM    : SPY uses VIX², GLD uses GVZ²   (NEW)

  VaR method: CF-Rolling (252d window on portfolio standardized residuals)
  Alpha levels: 1%, 2.5%.

Portfolio: 50/50 SPY/GLD (daily rebalanced, 50/50 weights applied to
           simple returns for VaR backtesting).
Data: yfinance SPY, GLD, ^VIX, ^GVZ. GVZ starts 2008-06-03.
OOS: 2013-06-01 onwards, window=1250 (5y), refit/63d.
     (Window reduced from K1041's 2000 to accommodate GVZ start.)
Seed: 42.

Evaluation:
  - Trinity test (Kupiec + CC + Basel) at 1% and 2.5%
  - ES backtest (Acerbi-Szekely Z1)
  - Fissler-Ziegel joint VaR-ES score (Fissler & Ziegel 2016)
  - DM test on portfolio variance QLIKE
  - DM test on FZ scores (joint VaR-ES comparison)
  - Rolling correlation plot; COVID sub-sample

References:
  - Engle (2002). Dynamic Conditional Correlation. JBES 20(3).
  - Engle, Ghysels & Sohn (2013). A4f specification. RES 95(3).
  - Patton (2011). Volatility forecast comparison. JoE 160(1).
  - Kupiec (1995). J Derivatives 3:73-84.
  - Christoffersen (1998). Int Econ Rev.
  - Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320.
  - Acerbi & Szekely (2014). Back-testing ES. Risk.
  - Fissler & Ziegel (2016). Higher order elicitability and Osband's
    principle. Annals of Statistics 44(4):1680-1707.
  - Nolte & Xu (2015). Volatility indices and VaR. [GVZ]
  - K1041, K1085, K1088, K1091.

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
from scipy.stats import norm, chi2
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1092"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1092_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-12'
OOS_START = '2013-06-01'   # GVZ starts 2008-06-03; need >=1250d training
WINDOW = 1250              # Reduced from K1041's 2000 to span OOS 2013-2026
REFIT_EVERY = 63
CF_ROLLING_WINDOW = 252
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS = np.array([0.5, 0.5])

print("=" * 72)
print(f"{EXPERIMENT_ID}: Asset-Matched DCC-A4f Portfolio VaR")
print(f"  SPY uses VIX^2, GLD uses GVZ^2 (asymmetric)")
print(f"  Models: DCC-GJR, DCC-A4f-SYMM (both VIX), DCC-A4f-ASYM (SPY-VIX GLD-GVZ)")
print(f"  VaR: CF-Rolling (252d), alpha=1%, 2.5%")
print(f"  Portfolio: 50/50 SPY/GLD, OOS from {OOS_START}, window={WINDOW}")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (GJR + A4f + DCC)
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
    """A4f multiplicative GARCH-X: h_t = tau_t * g_t
    tau_t = theta0 + theta1 * x2_{t-1}   (x2 = VIX^2 or GVZ^2 scaled)
    g_t GJR on u_t = r_t / sqrt(tau_t)
    """
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
# 2. MODEL FITTING
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
    """Fit A4f multiplicative GARCH-X by MLE. x2 is daily-variance-scaled IV^2."""
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
MODELS = ['DCC-GJR', 'DCC-A4f-SYMM', 'DCC-A4f-ASYM']


def oos_forecast_all(ret_spy, ret_gld, vix2, gvz2, dates, oos_start,
                     window=WINDOW, refit_every=REFIT_EVERY):
    """
    OOS portfolio variance forecast for 3 models:
      DCC-GJR         : GJR marginals (no exogenous)
      DCC-A4f-SYMM    : A4f marginals, both use VIX^2
      DCC-A4f-ASYM    : A4f marginals, SPY uses VIX^2 and GLD uses GVZ^2
    """
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret_spy)
    n_oos = T - oos_idx

    h_spy = {m: np.full(n_oos, np.nan) for m in MODELS}
    h_gld = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_f = {m: np.full(n_oos, np.nan) for m in MODELS}
    pvar = {m: np.full(n_oos, np.nan) for m in MODELS}

    state = {}
    for m in MODELS:
        state[m] = {
            'h1_prev': np.nan, 'h2_prev': np.nan,
            'g1_prev': np.nan, 'g2_prev': np.nan,
            'marg1_p': None, 'marg2_p': None,  # params
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

            # --- DCC-GJR baseline ---
            gjr_spy = fit_gjr(tr_spy)
            gjr_gld = fit_gjr(tr_gld)
            eps_gjr_spy = tr_spy / np.sqrt(gjr_spy['h'])
            eps_gjr_gld = tr_gld / np.sqrt(gjr_gld['h'])
            dcc_gjr = fit_dcc(eps_gjr_spy, eps_gjr_gld)

            # --- DCC-A4f-SYMM: both use VIX^2 ---
            a4f_spy_vix = fit_a4f(tr_spy, tr_vix2)
            a4f_gld_vix = fit_a4f(tr_gld, tr_vix2)
            eps_symm_spy = tr_spy / np.sqrt(a4f_spy_vix['h'])
            eps_symm_gld = tr_gld / np.sqrt(a4f_gld_vix['h'])
            dcc_symm = fit_dcc(eps_symm_spy, eps_symm_gld)

            # --- DCC-A4f-ASYM: SPY uses VIX^2, GLD uses GVZ^2 ---
            # SPY marginal same as above (reuse)
            a4f_gld_gvz = fit_a4f(tr_gld, tr_gvz2)
            eps_asym_spy = tr_spy / np.sqrt(a4f_spy_vix['h'])  # reuse
            eps_asym_gld = tr_gld / np.sqrt(a4f_gld_gvz['h'])
            dcc_asym = fit_dcc(eps_asym_spy, eps_asym_gld)

            # Populate states
            # DCC-GJR
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

            # DCC-A4f-SYMM
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

            # DCC-A4f-ASYM
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

        # ---- Recursive one-step forecast ----
        r1_prev = ret_spy[t-1]
        r2_prev = ret_gld[t-1]
        vix2_prev = vix2[t-1]
        gvz2_prev = gvz2[t-1]

        for m in MODELS:
            marg1 = state[m]['marg1_p']
            marg2 = state[m]['marg2_p']

            # SPY marginal (always equity side)
            if marg1[0] == 'GJR':
                p = marg1[1]
                ind = 1.0 if r1_prev < 0 else 0.0
                h1_t = p[0] + p[1]*r1_prev**2 + p[2]*r1_prev**2*ind + p[3]*state[m]['h1_prev']
            else:  # A4f-VIX
                p = marg1[1]
                tau = max(p[0] + p[1] * vix2_prev, 1e-16)
                u_prev = r1_prev / np.sqrt(tau)
                ind = 1.0 if r1_prev < 0 else 0.0
                g_t = p[2] + p[3]*u_prev**2 + p[4]*u_prev**2*ind + p[5]*state[m]['g1_prev']
                g_t = max(g_t, 1e-16)
                state[m]['g1_prev'] = g_t
                h1_t = tau * g_t
            h1_t = max(h1_t, 1e-16)

            # GLD marginal (varies: GJR / A4f-VIX / A4f-GVZ)
            if marg2[0] == 'GJR':
                p = marg2[1]
                ind = 1.0 if r2_prev < 0 else 0.0
                h2_t = p[0] + p[1]*r2_prev**2 + p[2]*r2_prev**2*ind + p[3]*state[m]['h2_prev']
            else:  # A4f
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

            # Update DCC state with current standardized residuals
            eps1_now = r1_prev / np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
            eps2_now = r2_prev / np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
            state[m]['eps1_prev'] = eps1_now
            state[m]['eps2_prev'] = eps2_now
            state[m]['q11_prev'] = q11
            state[m]['q22_prev'] = q22
            state[m]['q12_prev'] = q12

            # Portfolio variance
            s1 = np.sqrt(h1_t)
            s2 = np.sqrt(h2_t)
            pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                 2 * WEIGHTS[0] * WEIGHTS[1] * rho_t * s1 * s2
            pvar[m][i] = max(pv, 1e-16)

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar, 'h_spy': h_spy, 'h_gld': h_gld,
        'rho': rho_f, 'oos_dates': oos_dates, 'oos_idx': oos_idx,
    }


# ============================================================
# 4. VaR (CF-Rolling)
# ============================================================
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


# ============================================================
# 5. BACKTESTING: Kupiec / CC / Basel / ES / FZ
# ============================================================
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

    return {'color': color, 'violations_per_block': float(avg_violations_per_block),
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
    """Fissler & Ziegel (2016) strictly consistent joint VaR-ES score.

    S(V, E; r) = (I{r<=V} - alpha)(V - r)/alpha
                 + E/alpha * (I{r<=V} - alpha + (alpha - I{r<=V}) V/E)
                 - log(-E) + log(-V)    [when V, E are negative]

    We use the form from Fissler-Ziegel (2016, Theorem 5.2) with G1=identity,
    G2=-1/x:  S(V,E;r) = -1/(alpha*E) * I{r<=V} * (V-r) + V/E + log(-E) - 1.
    Both V and E are negative quantile/shortfall values. Lower score = better.
    """
    valid = (np.isfinite(var_series) & np.isfinite(es_series)
             & np.isfinite(port_returns) & (es_series < 0) & (var_series < 0))
    r = port_returns[valid]
    V = var_series[valid]
    E = es_series[valid]
    n = len(r)
    if n == 0:
        return np.array([]), 0.0

    indicator = (r <= V).astype(float)
    # FZ0 score (from Patton, Ziegel, Chen 2019, eq 2.5): strictly consistent
    # S(V,E;r) = (1/alpha) * I{r<=V} * (V - r) / (-E) - V/E + log(-E) - 1
    # Lower is better.
    with np.errstate(divide='ignore', invalid='ignore'):
        s = (1.0 / alpha) * indicator * (V - r) / (-E) - V / E + np.log(-E) - 1.0
    s = s[np.isfinite(s)]
    return s, float(np.mean(s)) if len(s) else np.nan


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
    return {
        'kupiec': kupiec, 'christoffersen': cc, 'basel': basel,
        'es_test': es_test, 'trinity_pass': trinity_pass,
        'n_oos': n, 'violation_rate': float(kupiec['rate']),
    }


# ============================================================
# 6. DM TESTS
# ============================================================
def dm_test(loss_series_1, loss_series_2):
    """Diebold-Mariano test. Negative t => model 1 is better."""
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
    valid = np.isfinite(actual_r2) & np.isfinite(forecast_var1) & np.isfinite(forecast_var2)
    valid &= (forecast_var1 > 0) & (forecast_var2 > 0)
    r2 = actual_r2[valid]
    h1 = forecast_var1[valid]
    h2 = forecast_var2[valid]
    loss1 = np.log(h1) + r2 / h1
    loss2 = np.log(h2) + r2 / h2
    return dm_test(loss1, loss2)


# ============================================================
# 7. DATA LOADING
# ============================================================
def load_data():
    import yfinance as yf

    print("Downloading data from yfinance (SPY, GLD, ^VIX, ^GVZ)...")
    # SPY, GLD: auto_adjust=True for total-return prices
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

    # Common dates for returns (SPY, GLD, VIX). GVZ joins later.
    df = pd.DataFrame({
        'spy': spy_close, 'gld': gld_close, 'vix': vix_close, 'gvz': gvz_close
    }).sort_index()
    df = df.dropna(subset=['spy', 'gld', 'vix'])

    # Fill GVZ before 2008-06-03 with VIX (fallback; only matters in pre-OOS training
    # if a rolling window happens to start before GVZ starts). We'll prefer to push
    # OOS_START so that all training windows have valid GVZ.
    df['gvz_filled'] = df['gvz'].copy()
    # Backfill using VIX (shares scale since both are annualized IV in % points)
    mask = df['gvz_filled'].isna()
    df.loc[mask, 'gvz_filled'] = df.loc[mask, 'vix']
    df['gvz_filled'] = df['gvz_filled'].ffill()

    df['ret_spy'] = np.log(df['spy'] / df['spy'].shift(1))
    df['ret_gld'] = np.log(df['gld'] / df['gld'].shift(1))
    # IV^2 scaled to daily variance (annual % -> daily variance)
    df['vix2'] = (df['vix'] / 100.0) ** 2 / 252.0
    df['gvz2'] = (df['gvz_filled'] / 100.0) ** 2 / 252.0

    df['r2_spy'] = df['ret_spy'] ** 2
    df['r2_gld'] = df['ret_gld'] ** 2

    # Portfolio simple returns
    simple_spy = df['spy'].pct_change()
    simple_gld = df['gld'].pct_change()
    df['port_ret'] = 0.5 * simple_spy + 0.5 * simple_gld

    df = df.dropna(subset=['ret_spy', 'ret_gld', 'vix2', 'gvz2'])

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total days: {len(df)}")
    print(f"GVZ native start: {(df['gvz'].first_valid_index()).strftime('%Y-%m-%d')}")
    print(f"SPY mean return: {df['ret_spy'].mean()*252:.4f}, vol: {df['ret_spy'].std()*np.sqrt(252):.4f}")
    print(f"GLD mean return: {df['ret_gld'].mean()*252:.4f}, vol: {df['ret_gld'].std()*np.sqrt(252):.4f}")
    print(f"SPY-GLD full-sample corr: {np.corrcoef(df['ret_spy'], df['ret_gld'])[0,1]:.4f}")
    print(f"VIX mean: {df['vix'].mean():.2f}, GVZ (native) mean: {df['gvz'].mean():.2f}")
    return df


# ============================================================
# 8. PLOTS
# ============================================================
def to_json_safe(obj):
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
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


def main():
    df = load_data()

    ret_spy = df['ret_spy'].values
    ret_gld = df['ret_gld'].values
    vix2 = df['vix2'].values
    gvz2 = df['gvz2'].values
    dates = df.index.values
    port_ret = df['port_ret'].values

    print("\n--- OOS Forecasting (3 DCC models) ---")
    forecasts = oos_forecast_all(ret_spy, ret_gld, vix2, gvz2, dates, OOS_START)
    oos_dates = forecasts['oos_dates']
    oos_idx = forecasts['oos_idx']
    n_oos = len(oos_dates)

    port_ret_oos = port_ret[oos_idx:]
    r2_port_oos = port_ret_oos ** 2

    print(f"\nOOS period: {pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} "
          f"to {pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')}")
    print(f"OOS days: {n_oos}")

    # -------------------- VaR/ES evaluation --------------------
    print("\n--- VaR Evaluation (CF-Rolling) ---")
    results = {'experiment_id': EXPERIMENT_ID, 'models': {}}
    var_series_store = {m: {} for m in MODELS}
    es_series_store = {m: {} for m in MODELS}
    fz_mean_store = {m: {} for m in MODELS}
    fz_series_store = {m: {} for m in MODELS}

    for m in MODELS:
        port_sigma = np.sqrt(forecasts['pvar'][m])
        model_results = {'var_tests': {}, 'fz_score': {}}
        print(f"\n  Model: {m}")

        for alpha in ALPHA_LEVELS:
            var_s, es_s = compute_cf_rolling_var(port_ret_oos, port_sigma, alpha)
            var_series_store[m][alpha] = var_s
            es_series_store[m][alpha] = es_s

            trinity = trinity_test(port_ret_oos, var_s, es_s, alpha)
            fz_s, fz_mean = fz_score_series(port_ret_oos, var_s, es_s, alpha)
            fz_mean_store[m][alpha] = fz_mean
            fz_series_store[m][alpha] = fz_s

            alpha_key = f"alpha_{alpha:.3f}"
            model_results['var_tests'][alpha_key] = trinity
            model_results['fz_score'][alpha_key] = {
                'mean': fz_mean, 'n': int(len(fz_s))
            }

            print(f"    alpha={alpha:.3f}: viol_rate={trinity['violation_rate']:.4f} "
                  f"(exp {alpha:.4f}), Trinity={'PASS' if trinity['trinity_pass'] else 'FAIL'}, "
                  f"Kupiec p={trinity['kupiec']['p_value']:.4f}, "
                  f"CC p={trinity['christoffersen']['p_value']:.4f}, "
                  f"Basel={trinity['basel']['color']}, "
                  f"ES p={trinity['es_test']['p_value']:.4f}, "
                  f"FZ={fz_mean:.4f}")

        results['models'][m] = model_results

    # -------------------- DM tests: portfolio QLIKE --------------------
    print("\n--- DM Tests (Portfolio QLIKE) ---")
    qlike_dm = {}
    pairs_qlike = [
        ('DCC-GJR', 'DCC-A4f-SYMM'),
        ('DCC-GJR', 'DCC-A4f-ASYM'),
        ('DCC-A4f-SYMM', 'DCC-A4f-ASYM'),
    ]
    for m1, m2 in pairs_qlike:
        dm = dm_qlike(r2_port_oos, forecasts['pvar'][m1], forecasts['pvar'][m2])
        key = f"{m1}_vs_{m2}"
        qlike_dm[key] = dm
        direction = f"{m1} better" if dm['t_stat'] < 0 else f"{m2} better"
        sig = "***" if dm['significant_harvey'] else ("*" if dm['p_value'] < 0.05 else "")
        print(f"  {m1} vs {m2}: DM t={dm['t_stat']:+.3f} ({direction}) {sig}")
    results['dm_qlike'] = qlike_dm

    # -------------------- DM tests: FZ scores (joint VaR-ES) --------------------
    print("\n--- DM Tests (FZ Joint VaR-ES Score) ---")
    fz_dm = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f"alpha_{alpha:.3f}"
        fz_dm[alpha_key] = {}
        for m1, m2 in pairs_qlike:
            s1 = fz_series_store[m1][alpha]
            s2 = fz_series_store[m2][alpha]
            # Align lengths (should be same)
            n = min(len(s1), len(s2))
            if n < 50:
                fz_dm[alpha_key][f"{m1}_vs_{m2}"] = {
                    't_stat': 0.0, 'p_value': 1.0, 'mean_loss_diff': 0.0,
                    'n': int(n), 'significant_harvey': False}
                continue
            dm = dm_test(s1[:n], s2[:n])
            key = f"{m1}_vs_{m2}"
            fz_dm[alpha_key][key] = dm
            direction = f"{m1} better" if dm['t_stat'] < 0 else f"{m2} better"
            sig = "***" if dm['significant_harvey'] else ("*" if dm['p_value'] < 0.05 else "")
            print(f"  [{alpha_key}] {m1} vs {m2}: DM t={dm['t_stat']:+.3f} ({direction}) {sig}")
    results['dm_fz'] = fz_dm

    # -------------------- Correlation stats --------------------
    print("\n--- Correlation Analysis ---")
    corr_stats = {}
    for m in MODELS:
        rho = forecasts['rho'][m]
        valid = np.isfinite(rho)
        rv = rho[valid]
        corr_stats[m] = {
            'mean_rho': float(np.mean(rv)),
            'std_rho': float(np.std(rv)),
            'min_rho': float(np.min(rv)),
            'max_rho': float(np.max(rv)),
        }
        print(f"  {m}: rho mean={np.mean(rv):+.4f}, std={np.std(rv):.4f}, "
              f"range=[{np.min(rv):+.4f}, {np.max(rv):+.4f}]")
    results['correlation_stats'] = corr_stats

    # COVID sub-sample
    print("\n--- COVID Sub-sample (2020-02 to 2020-06) ---")
    covid_mask = (pd.DatetimeIndex(oos_dates) >= '2020-02-01') & \
                 (pd.DatetimeIndex(oos_dates) <= '2020-06-30')
    covid_stats = {}
    for m in MODELS:
        rho_c = forecasts['rho'][m][covid_mask]
        valid = np.isfinite(rho_c)
        if valid.sum() > 0:
            rv = rho_c[valid]
            covid_stats[m] = {
                'mean_rho': float(np.mean(rv)),
                'min_rho': float(np.min(rv)),
                'max_rho': float(np.max(rv)),
                'range': float(np.max(rv) - np.min(rv)),
            }
            print(f"  {m}: COVID rho mean={np.mean(rv):+.4f}, "
                  f"range=[{np.min(rv):+.4f}, {np.max(rv):+.4f}]")
    results['covid_correlation'] = covid_stats

    # -------------------- Mean QLIKE --------------------
    print("\n--- Mean QLIKE ---")
    qlike_results = {}
    for m in MODELS:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_port_oos)
        q = np.log(pv[valid]) + r2_port_oos[valid] / pv[valid]
        qlike_results[m] = float(np.mean(q))
        print(f"  {m}: QLIKE = {np.mean(q):.6f}")
    results['mean_qlike'] = qlike_results

    # -------------------- Trinity scoring --------------------
    trinity_scores = {}
    for m in MODELS:
        n_pass = sum(1 for alpha in ALPHA_LEVELS
                     if results['models'][m]['var_tests'][f"alpha_{alpha:.3f}"]['trinity_pass'])
        trinity_scores[m] = f"{n_pass}/{len(ALPHA_LEVELS)}"
    results['trinity_scores'] = trinity_scores

    # -------------------- Core answers --------------------
    # Compare DCC-A4f-ASYM vs DCC-A4f-SYMM on QLIKE
    key_dm = 'DCC-A4f-SYMM_vs_DCC-A4f-ASYM'
    core = {
        'q1_asym_beats_symm_qlike': {
            't_stat': qlike_dm[key_dm]['t_stat'],
            'harvey_sig': qlike_dm[key_dm]['significant_harvey'],
            'asym_better': qlike_dm[key_dm]['t_stat'] > 0,  # SYMM worse => ASYM better => t>0
        },
        'q2_asym_fz_1pct': fz_dm['alpha_0.010'].get(key_dm, {}),
        'q3_asym_fz_25pct': fz_dm['alpha_0.025'].get(key_dm, {}),
        'q4_best_model_by_qlike': min(qlike_results.items(), key=lambda kv: kv[1])[0],
        'q5_asym_qlike_improvement_vs_symm_pct': (
            (qlike_results['DCC-A4f-SYMM'] - qlike_results['DCC-A4f-ASYM']) /
            abs(qlike_results['DCC-A4f-SYMM']) * 100.0
        ),
    }
    results['core_answers'] = core
    print("\n--- Core Answers ---")
    print(f"  ASYM beats SYMM (QLIKE): t={core['q1_asym_beats_symm_qlike']['t_stat']:+.3f} "
          f"Harvey sig={core['q1_asym_beats_symm_qlike']['harvey_sig']}")
    print(f"  Best by QLIKE: {core['q4_best_model_by_qlike']}")
    print(f"  ASYM vs SYMM QLIKE improvement: {core['q5_asym_qlike_improvement_vs_symm_pct']:+.3f}%")

    # -------------------- Metadata --------------------
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
        'portfolio_weights': WEIGHTS.tolist(),
        'seed': 42,
        'runtime_seconds': float(runtime),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'parent_experiments': ['K1041', 'K1085', 'K1088', 'K1091'],
        'references': [
            'Engle (2002) JBES 20(3)',
            'Engle, Ghysels & Sohn (2013) RES 95(3)',
            'Patton (2011) JoE 160(1)',
            'Kupiec (1995) J Derivatives 3',
            'Christoffersen (1998) Int Econ Rev',
            'Acerbi & Szekely (2014) Risk',
            'Fissler & Ziegel (2016) Ann Stat 44(4)',
        ],
    }

    # -------------------- PLOTS --------------------
    print("\n--- Generating Plots ---")
    oos_pd = pd.DatetimeIndex(oos_dates)

    # Plot 1: DM t-stat comparison (QLIKE + FZ)
    fig, ax = plt.subplots(1, 1, figsize=(11, 6))
    labels = []
    t_vals = []
    colors = []
    newline = '\n'
    for key, dm in qlike_dm.items():
        pretty = key.replace('_vs_', newline + 'vs ')
        labels.append(f"QLIKE{newline}{pretty}")
        t_vals.append(dm['t_stat'])
        colors.append('steelblue')
    for alpha in ALPHA_LEVELS:
        alpha_key = f"alpha_{alpha:.3f}"
        for key, dm in fz_dm[alpha_key].items():
            pretty = key.replace('_vs_', newline + 'vs ')
            labels.append(f"FZ {alpha*100:.1f}%{newline}{pretty}")
            t_vals.append(dm['t_stat'])
            colors.append('darkorange' if alpha == 0.01 else 'forestgreen')
    x = np.arange(len(labels))
    bars = ax.bar(x, t_vals, color=colors, alpha=0.85, edgecolor='black')
    ax.axhline(0, color='black', lw=0.8)
    ax.axhline(3.0, color='red', linestyle='--', lw=1, label='Harvey |t|=3.0')
    ax.axhline(-3.0, color='red', linestyle='--', lw=1)
    ax.axhline(1.96, color='grey', linestyle=':', lw=1, label='|t|=1.96')
    ax.axhline(-1.96, color='grey', linestyle=':', lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=60, ha='right', fontsize=8)
    ax.set_ylabel('DM t-statistic (negative = 1st model better)')
    ax.set_title(f'{EXPERIMENT_ID}: DM Tests — 3 DCC Models, Portfolio QLIKE & FZ Scores')
    ax.legend(loc='best', fontsize=9)
    plt.tight_layout()
    dm_path = os.path.join(SCRIPT_DIR, 'k1092_dm_comparison.png')
    plt.savefig(dm_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {dm_path}")

    # Plot 2: VaR Trinity (Kupiec/CC/Basel p-values for 3 models at 1% and 2.5%)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax_i, alpha in enumerate(ALPHA_LEVELS):
        ax = axes[ax_i]
        alpha_key = f"alpha_{alpha:.3f}"
        test_names = ['Kupiec', 'CC', 'ES']
        model_positions = np.arange(len(MODELS))
        width = 0.25
        for i, tname in enumerate(test_names):
            p_vals = []
            for m in MODELS:
                t = results['models'][m]['var_tests'][alpha_key]
                if tname == 'Kupiec':
                    p_vals.append(t['kupiec']['p_value'])
                elif tname == 'CC':
                    p_vals.append(t['christoffersen']['p_value'])
                else:
                    p_vals.append(t['es_test']['p_value'])
            ax.bar(model_positions + i*width, p_vals, width, label=tname, alpha=0.85,
                   edgecolor='black')
        ax.axhline(0.05, color='red', linestyle='--', lw=1, label='0.05 threshold')
        ax.set_xticks(model_positions + width)
        ax.set_xticklabels(MODELS, rotation=30, ha='right')
        ax.set_title(f'VaR Trinity p-values at alpha={alpha*100:.1f}%')
        ax.set_ylabel('p-value')
        ax.legend(fontsize=8)
        ax.set_ylim(0, 1.05)
    plt.tight_layout()
    trinity_path = os.path.join(SCRIPT_DIR, 'k1092_var_trinity.png')
    plt.savefig(trinity_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {trinity_path}")

    # Plot 3: Mean FZ score comparison
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    x = np.arange(len(MODELS))
    width = 0.35
    fz_01 = [fz_mean_store[m][0.01] for m in MODELS]
    fz_025 = [fz_mean_store[m][0.025] for m in MODELS]
    ax.bar(x - width/2, fz_01, width, label='α=1%', alpha=0.85, color='steelblue',
           edgecolor='black')
    ax.bar(x + width/2, fz_025, width, label='α=2.5%', alpha=0.85, color='darkorange',
           edgecolor='black')
    ax.set_xticks(x)
    ax.set_xticklabels(MODELS, rotation=30, ha='right')
    ax.set_ylabel('Mean Fissler-Ziegel Score (lower = better)')
    ax.set_title(f'{EXPERIMENT_ID}: FZ Joint VaR-ES Score — 3 DCC Models')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    fz_path = os.path.join(SCRIPT_DIR, 'k1092_fz_score.png')
    plt.savefig(fz_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {fz_path}")

    # Plot 4: DCC rho time series
    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    for m, color in zip(MODELS, ['gray', 'steelblue', 'darkred']):
        ax.plot(oos_pd, forecasts['rho'][m], label=m, alpha=0.8,
                linewidth=1.2 if 'ASYM' in m else 0.9,
                color=color)
    ax.axhline(0, color='black', lw=0.7, linestyle=':')
    ax.axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
               alpha=0.15, color='red')
    ax.axvspan(pd.Timestamp('2022-02-24'), pd.Timestamp('2022-08-15'),
               alpha=0.10, color='orange')
    ax.set_ylabel('SPY-GLD Conditional Correlation (ρ)')
    ax.set_xlabel('Date')
    ax.set_title(f'{EXPERIMENT_ID}: Time-varying SPY-GLD Correlation (COVID red, Ukraine orange)')
    ax.legend(loc='best')
    plt.tight_layout()
    corr_path = os.path.join(SCRIPT_DIR, 'k1092_correlation_ts.png')
    plt.savefig(corr_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {corr_path}")

    # Plot 5: Portfolio returns + VaR overlay at 1% for ASYM model
    fig, axes = plt.subplots(len(MODELS), 1, figsize=(14, 3.5*len(MODELS)), sharex=True)
    for ax_i, m in enumerate(MODELS):
        ax = axes[ax_i]
        var_s = var_series_store[m][0.01]
        es_s = es_series_store[m][0.01]
        valid = np.isfinite(var_s)
        ax.plot(oos_pd[valid], port_ret_oos[valid], color='grey', alpha=0.45,
                linewidth=0.6, label='50/50 Portfolio Return')
        ax.plot(oos_pd[valid], var_s[valid], color='red', alpha=0.85,
                linewidth=1.1, label='VaR 1%')
        ax.plot(oos_pd[valid], es_s[valid], color='purple', alpha=0.85,
                linewidth=1.0, linestyle='--', label='ES 1%')
        violations = (port_ret_oos < var_s) & valid
        if np.any(violations):
            ax.scatter(oos_pd[violations], port_ret_oos[violations],
                      color='red', s=15, zorder=5, alpha=0.8)
        viol_rate = np.sum(violations) / max(np.sum(valid), 1)
        ax.set_title(f'{m}: VaR 1% (violation_rate={viol_rate:.4f})')
        ax.set_ylabel('Return')
        ax.legend(fontsize=8, loc='lower left')
    axes[-1].set_xlabel('Date')
    plt.tight_layout()
    pf_path = os.path.join(SCRIPT_DIR, 'k1092_portfolio_series.png')
    plt.savefig(pf_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {pf_path}")

    # -------------------- SAVE --------------------
    results_safe = to_json_safe(results)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_safe, f, indent=2)
    print(f"\nResults saved: {RESULTS_PATH}")
    print(f"Total runtime: {runtime:.1f}s")


if __name__ == '__main__':
    main()
