#!/usr/bin/env python3
"""
K1100e: N=13 Cross-Asset λ_L Threshold Test (K1100c Follow-Up)
===============================================================
[提出: User (Lai Yi-Hao) / 設計: Claude / 執行: Claude]

Parent experiments: K1100c (MIXED scenario C: SPY-TLT Joe DM=+10.36,
                              SPY-GLD Joe=+7.66), K1100b (5 pairs NULL)
Related: K1100, K1041, K1092

Hypothesis (H1):
  Spearman(λ_L, DM_Joe-vs-DCC) < 0 with N=13 pairs, p < 0.05
  i.e., lower lower-tail dependence → Joe copula beats DCC more strongly.

The λ_L threshold separates:
  - High λ_L (equity-equity, ~0.4-0.6): symmetric crash co-movement,
    Joe (upper-tail) offers no advantage → DM ≤ 0 (NULL expected)
  - Low λ_L (equity-bond, ~0.01-0.09): asymmetric/opposite tail structure,
    Joe can exploit divergence → DM > 0 (PASS expected)

13 pairs by asset class:
  Equity-equity (high λ_L, expected NULL):
    SPY-QQQ, SPY-IWM, SPY-XLF
  Equity-bond (low λ_L, expected PASS):
    SPY-TLT, SPY-IEF, SPY-TIP
  Equity-commodity (mid-low):
    SPY-GLD, SPY-SLV, SPY-USO
  Equity-FX (low):
    SPY-UUP, SPY-FXE
  Equity-credit (mid):
    SPY-LQD, SPY-HYG

Models:
  M1: DCC-A4f-ASYM (baseline, K1092 best)
  M5: Copula-Joe-A4f-ASYM (main test)
  Secondary: Copula-SkewT-A4f-ASYM (secondary check)

Data: yfinance daily, 2005-01-01 to 2026-04-12
OOS: 2013-06-01 onwards
Window: 1250 days, Refit: every 63 days
MC paths: 5000/day, seed=42
DM test Harvey threshold: |t| > 3.0

Anti-lookahead:
  - GARCH marginals use t-1 info to forecast h_t
  - Copula params from training window ending at t-1
  - MC VaR drawn before using return at t

References:
  - Joe (1997). Multivariate Models and Dependence Concepts. Chapman&Hall.
  - Hansen (1994). Autoregressive Conditional Density. IER 35(3).
  - Harvey (1997). Testing DM: A Note. JBES 15(4).
  - Patton (2006). Modelling asymmetric exchange rate dependence. IER 47(2).
  - K1100c (2026-04-17): MIXED result, Joe significant for cross-class pairs

Author: VolPred Research System
Date: 2026-04-17
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize, special
from scipy.stats import norm, chi2, t as student_t
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

warnings.filterwarnings('ignore')
np.random.seed(42)
RNG = np.random.default_rng(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1100e"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1100e_results.json')
LOG_PATH = os.path.join(SCRIPT_DIR, 'run.log')


class Tee:
    def __init__(self, *files):
        self.files = files

    def write(self, obj):
        for f in self.files:
            f.write(obj)
            f.flush()

    def flush(self):
        for f in self.files:
            f.flush()


log_file = open(LOG_PATH, 'w')
sys.stdout = Tee(sys.__stdout__, log_file)

# ============================================================
# CONFIGURATION
# ============================================================
DATA_START = '2005-01-01'
DATA_END   = '2026-04-12'
OOS_START  = '2013-06-01'
WINDOW     = 1250
REFIT_EVERY = 63
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS    = np.array([0.5, 0.5])
MC_PATHS   = 5000

# 13 pairs: (label, asset1, asset2, vol_reg1, vol_reg2, asset_class)
# vol_reg: 'vix2' = VIX^2/252/10000, 'gvz2' = GVZ^2/252/10000
PAIRS = [
    # Equity-equity (high λ_L expected)
    ('SPY-QQQ', 'SPY', 'QQQ', 'vix2', 'vix2', 'equity-equity'),
    ('SPY-IWM', 'SPY', 'IWM', 'vix2', 'vix2', 'equity-equity'),
    ('SPY-XLF', 'SPY', 'XLF', 'vix2', 'vix2', 'equity-equity'),
    # Equity-bond (low λ_L expected)
    ('SPY-TLT', 'SPY', 'TLT', 'vix2', 'vix2', 'equity-bond'),
    ('SPY-IEF', 'SPY', 'IEF', 'vix2', 'vix2', 'equity-bond'),
    ('SPY-TIP', 'SPY', 'TIP', 'vix2', 'vix2', 'equity-bond'),
    # Equity-commodity (mid-low λ_L)
    ('SPY-GLD', 'SPY', 'GLD', 'vix2', 'gvz2', 'equity-commodity'),
    ('SPY-SLV', 'SPY', 'SLV', 'vix2', 'gvz2', 'equity-commodity'),
    ('SPY-USO', 'SPY', 'USO', 'vix2', 'vix2', 'equity-commodity'),
    # Equity-FX (low λ_L)
    ('SPY-UUP', 'SPY', 'UUP', 'vix2', 'vix2', 'equity-fx'),
    ('SPY-FXE', 'SPY', 'FXE', 'vix2', 'vix2', 'equity-fx'),
    # Equity-credit (mid λ_L)
    ('SPY-LQD', 'SPY', 'LQD', 'vix2', 'vix2', 'equity-credit'),
    ('SPY-HYG', 'SPY', 'HYG', 'vix2', 'vix2', 'equity-credit'),
]

MODELS = ['DCC-A4f-ASYM', 'Copula-Joe-A4f-ASYM', 'Copula-SkewT-A4f-ASYM']

print("=" * 72)
print(f"{EXPERIMENT_ID}: N=13 Cross-Asset λ_L Threshold Test")
print(f"  13 pairs × 3 models")
print(f"  H1: Spearman(λ_L, DM_Joe-vs-DCC) < 0, p < 0.05")
print(f"  OOS from {OOS_START}, window={WINDOW}, refit={REFIT_EVERY}d,"
      f" MC={MC_PATHS}")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (inherited from K1100c)
# ============================================================
@njit
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, x2):
    T = len(returns)
    tau = np.empty(T)
    g   = np.empty(T)
    h   = np.empty(T)
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
        u2     = u_prev ** 2
        ind    = 1.0 if returns[t-1] < 0.0 else 0.0
        g[t]   = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


@njit
def a4f_nll(theta0, theta1, omega, alpha, gamma, beta, returns, x2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta,
                             returns, x2)
    T  = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit
def dcc_filter(eps1, eps2, a, b, qbar11, qbar22, qbar12):
    T   = len(eps1)
    q11 = np.empty(T)
    q22 = np.empty(T)
    q12 = np.empty(T)
    rho = np.empty(T)
    q11[0] = qbar11
    q22[0] = qbar22
    q12[0] = qbar12
    denom  = np.sqrt(q11[0] * q22[0])
    rho[0] = q12[0] / denom if denom > 1e-20 else 0.0
    c = 1.0 - a - b
    for t in range(1, T):
        q11[t] = c*qbar11 + a*eps1[t-1]*eps1[t-1] + b*q11[t-1]
        q22[t] = c*qbar22 + a*eps2[t-1]*eps2[t-1] + b*q22[t-1]
        q12[t] = c*qbar12 + a*eps1[t-1]*eps2[t-1] + b*q12[t-1]
        denom  = np.sqrt(q11[t] * q22[t])
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
    T   = len(eps1)
    ll  = 0.0
    for t in range(T):
        r  = rho[t]
        r2 = r * r
        if r2 > 0.9998:
            r2 = 0.9998
        det = 1.0 - r2
        e1  = eps1[t]
        e2  = eps2[t]
        ll += -0.5 * (np.log(det) + (r2*(e1*e1+e2*e2) - 2.0*r*e1*e2)/det)
    return ll


# ============================================================
# 2. MARGINAL + DCC FITTING
# ============================================================
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
                res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                        bounds=bounds,
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
            try:
                res = optimize.minimize(obj, [a_init, b_init],
                                        method='L-BFGS-B', bounds=bounds,
                                        options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        best_res = optimize.minimize(obj, [0.05, 0.90],
                                     method='L-BFGS-B', bounds=bounds)
    a_hat, b_hat = best_res.x
    rho = dcc_filter(eps1, eps2, a_hat, b_hat, qbar11, qbar22, qbar12)
    return {'a': float(a_hat), 'b': float(b_hat), 'rho': rho,
            'qbar11': float(qbar11), 'qbar22': float(qbar22),
            'qbar12': float(qbar12), 'converged': best_res.success}


# ============================================================
# 3. MARGINAL t PIT + STUDENT-T COPULA
# ============================================================
def fit_marginal_t_df(z):
    def neg_ll(nu):
        if nu <= 2.05 or nu > 100:
            return 1e10
        scale = np.sqrt((nu - 2.0) / nu)
        ll    = np.sum(student_t.logpdf(z / scale, df=nu) - np.log(scale))
        return -ll if np.isfinite(ll) else 1e10
    best_nu = 10.0
    try:
        res = optimize.minimize_scalar(neg_ll, bounds=(2.1, 80.0),
                                       method='bounded',
                                       options={'xatol': 1e-4})
        best_nu = res.x
    except Exception:
        pass
    return float(np.clip(best_nu, 2.1, 80.0))


def pit_student_t(z, nu):
    scale = np.sqrt((nu - 2.0) / nu)
    u     = student_t.cdf(z / scale, df=nu)
    return np.clip(u, 1e-6, 1.0 - 1e-6)


def inv_pit_student_t(u, nu):
    scale = np.sqrt((nu - 2.0) / nu)
    return student_t.ppf(u, df=nu) * scale


def t_copula_lambda(rho, nu):
    if rho >= 0.99:  return 1.0
    if rho <= -0.99: return 0.0
    arg = -np.sqrt((nu+1.0)*(1.0-rho)/(1.0+rho))
    return 2.0 * student_t.cdf(arg, df=nu+1.0)


def student_t_copula_nll(params, u1, u2):
    rho, nu_c = params
    if not (-0.995 < rho < 0.995) or not (2.1 < nu_c < 80.0):
        return 1e10
    x1 = student_t.ppf(u1, df=nu_c)
    x2 = student_t.ppf(u2, df=nu_c)
    det = 1.0 - rho * rho
    if det < 1e-10:
        return 1e10
    q = (x1*x1 - 2.0*rho*x1*x2 + x2*x2) / det
    log_biv = (special.gammaln((nu_c+2.0)/2.0)
               + special.gammaln(nu_c/2.0)
               - 2.0*special.gammaln((nu_c+1.0)/2.0)
               - 0.5*np.log(det)
               - ((nu_c+2.0)/2.0)*np.log(1.0+q/nu_c)
               + ((nu_c+1.0)/2.0)*np.log(1.0+x1*x1/nu_c)
               + ((nu_c+1.0)/2.0)*np.log(1.0+x2*x2/nu_c))
    ll = np.sum(log_biv)
    return -ll if np.isfinite(ll) else 1e10


def fit_student_t_copula(u1, u2):
    tau      = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau):
        tau = 0.0
    rho_init = float(np.clip(np.sin(np.pi * tau / 2.0), -0.9, 0.9))
    best_res, best_nll = None, 1e10
    for nu_init in [4.0, 8.0, 15.0]:
        for rho_try in [rho_init, 0.0, 0.3]:
            try:
                res = optimize.minimize(student_t_copula_nll,
                                        x0=[rho_try, nu_init],
                                        args=(u1, u2),
                                        method='L-BFGS-B',
                                        bounds=[(-0.99, 0.99), (2.2, 60.0)],
                                        options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        return {'rho': rho_init, 'nu': 10.0, 'converged': False,
                'lambda_L': t_copula_lambda(rho_init, 10.0)}
    rho_hat, nu_hat = best_res.x
    lL = t_copula_lambda(rho_hat, nu_hat)
    return {'rho': float(rho_hat), 'nu': float(nu_hat),
            'converged': bool(best_res.success), 'nll': float(best_res.fun),
            'lambda_L': float(lL)}


def sample_student_t_copula(rho, nu, n_samples, rng):
    R = np.array([[1.0, rho], [rho, 1.0]])
    rho_clipped = np.clip(rho, -0.99, 0.99)
    R_safe = np.array([[1.0, rho_clipped], [rho_clipped, 1.0]])
    try:
        L = np.linalg.cholesky(R_safe)
    except np.linalg.LinAlgError:
        L = np.eye(2)
    Z        = rng.standard_normal((n_samples, 2)) @ L.T
    chi_vals = rng.chisquare(df=nu, size=n_samples)
    X        = Z * np.sqrt(nu / chi_vals)[:, None]
    u1       = student_t.cdf(X[:, 0], df=nu)
    u2       = student_t.cdf(X[:, 1], df=nu)
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


# ============================================================
# 4. JOE COPULA
# ============================================================
def joe_copula_nll(theta, u1, u2):
    if theta < 1.001 or theta > 30.0:
        return 1e10
    try:
        a  = (1.0 - u1)**theta
        b  = (1.0 - u2)**theta
        ab = a * b
        s  = a + b - ab
        if np.any(s <= 0):
            return 1e10
        logs = np.log(s)
        # Nelsen (2006) p.160:
        # c(u,v) = (1-u)^{theta-1}*(1-v)^{theta-1} * S^{1/theta-2} * ((theta-1)*S + ab)
        log_c = ((theta-1.0)*np.log(1.0-u1)
                 + (theta-1.0)*np.log(1.0-u2)
                 + (1.0/theta - 2.0)*logs
                 + np.log((theta-1.0)*s + ab))
        ll = np.sum(log_c)
        return -ll if np.isfinite(ll) else 1e10
    except Exception:
        return 1e10


def fit_joe_copula(u1, u2):
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau) or tau <= 0:
        theta_init = 1.5
    else:
        theta_init = max(1.1, 1.0 + tau / np.log(2.0))
    try:
        res = optimize.minimize_scalar(joe_copula_nll,
                                       bounds=(1.01, 25.0),
                                       method='bounded',
                                       args=(u1, u2),
                                       options={'xatol': 1e-4})
    except Exception:
        return {'theta': theta_init, 'converged': False,
                'lambda_U': 0.0, 'lambda_L': 0.0}
    theta_hat = float(res.x)
    lambda_U  = 2.0 - 2.0**(1.0/theta_hat)
    return {'theta': theta_hat,
            'lambda_U': float(lambda_U),
            'lambda_L': 0.0,
            'converged': bool(res.success),
            'nll': float(res.fun)}


def sample_joe_copula(theta, n_samples, rng):
    """Conditional CDF inversion for Joe copula."""
    if theta <= 1.01:
        u1 = rng.uniform(0, 1, n_samples)
        u2 = rng.uniform(0, 1, n_samples)
        return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)

    u1 = rng.uniform(1e-6, 1.0-1e-6, n_samples)
    w  = rng.uniform(1e-6, 1.0-1e-6, n_samples)

    a = (1.0 - u1)**theta
    a = np.clip(a, 1e-10, 1.0 - 1e-10)
    exp_  = (theta-1.0)/theta
    power = theta / (1.0 - theta)  # negative when theta > 1

    ratio = w / (a**exp_)
    ratio = np.maximum(ratio, 1e-10)
    c     = ratio**power
    c     = np.clip(c, 1e-10, 1.0 - 1e-10)

    denom = 1.0 - a
    denom = np.maximum(denom, 1e-10)
    b = (c - a) / denom
    b = np.clip(b, 1e-10, 1.0 - 1e-10)

    u2 = 1.0 - b**(1.0/theta)
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


# ============================================================
# 5. SKEW-T COPULA (Hansen 1994, secondary model)
# ============================================================
def _hansen_t_cdf(x, nu):
    scale = np.sqrt((nu-2.0)/nu)
    return student_t.cdf(x / scale, df=nu)


def _hansen_t_ppf(p, nu):
    scale = np.sqrt((nu-2.0)/nu)
    return student_t.ppf(p, df=nu) * scale


def hansen_skewt_logpdf(x_arr, nu, lam):
    if nu <= 2.0 or abs(lam) >= 1.0:
        return np.full(len(x_arr), -1e10)
    c_val = np.exp(special.gammaln((nu+1.0)/2.0)
                   - special.gammaln(nu/2.0)
                   - 0.5*np.log(np.pi*(nu-2.0)))
    a = 4.0*lam*c_val*(nu-2.0)/(nu-1.0)
    b2 = 1.0 + 3.0*lam**2 - a**2
    if b2 <= 0:
        return np.full(len(x_arr), -1e10)
    b   = np.sqrt(b2)
    bxa = b*x_arr + a
    sgn = np.sign(x_arr + a/b)
    sp  = 1.0 + sgn*lam
    sp  = np.maximum(sp, 1e-10)
    inner = 1.0 + (bxa/sp)**2 / (nu-2.0)
    inner = np.maximum(inner, 1e-10)
    logpdf = np.log(b) + np.log(c_val) - ((nu+1.0)/2.0)*np.log(inner)
    return logpdf


def hansen_skewt_cdf_vec(x_arr, nu, lam):
    if nu <= 2.0 or abs(lam) >= 1.0:
        return np.full(len(x_arr), 0.5)
    c_val = np.exp(special.gammaln((nu+1.0)/2.0)
                   - special.gammaln(nu/2.0)
                   - 0.5*np.log(np.pi*(nu-2.0)))
    a    = 4.0*lam*c_val*(nu-2.0)/(nu-1.0)
    b2   = 1.0 + 3.0*lam**2 - a**2
    if b2 <= 0:
        return np.full(len(x_arr), 0.5)
    b    = np.sqrt(b2)
    bxa  = b*x_arr + a
    mask_left = bxa < 0.0
    cdf = np.empty(len(x_arr))
    cdf[mask_left]  = (1.0-lam) * _hansen_t_cdf(bxa[mask_left]/(1.0-lam), nu)
    cdf[~mask_left] = ((1.0-lam)/2.0
                       + (1.0+lam) * (_hansen_t_cdf(bxa[~mask_left]/(1.0+lam), nu) - 0.5))
    return np.clip(cdf, 1e-6, 1.0-1e-6)


def hansen_skewt_ppf_vec(p_arr, nu, lam):
    if nu <= 2.0 or abs(lam) >= 1.0:
        scale = np.sqrt((nu-2.0)/nu) if nu > 2.0 else 1.0
        return student_t.ppf(p_arr, df=max(nu, 3.0)) * scale
    c_val = np.exp(special.gammaln((nu+1.0)/2.0)
                   - special.gammaln(nu/2.0)
                   - 0.5*np.log(np.pi*(nu-2.0)))
    a    = 4.0*lam*c_val*(nu-2.0)/(nu-1.0)
    b2   = 1.0 + 3.0*lam**2 - a**2
    if b2 <= 0:
        return student_t.ppf(p_arr, df=10)
    b    = np.sqrt(b2)
    p0   = (1.0 - lam) / 2.0
    scale = np.sqrt((nu-2.0)/nu)
    p_arr = np.asarray(p_arr, dtype=float)
    mask  = p_arr < p0
    out   = np.empty_like(p_arr)
    if mask.any():
        q_left = np.clip(p_arr[mask] / (1.0-lam), 1e-10, 1.0-1e-10)
        bxa_left = student_t.ppf(q_left, df=nu) * scale * (1.0-lam)
        out[mask] = (bxa_left - a) / b
    if (~mask).any():
        q_right = np.clip(0.5 + (p_arr[~mask] - p0)/(1.0+lam), 1e-10, 1.0-1e-10)
        bxa_right = student_t.ppf(q_right, df=nu) * scale * (1.0+lam)
        out[~mask] = (bxa_right - a) / b
    return out


def fit_marginal_skt(z):
    def neg_ll(params):
        nu, lam = params
        if nu <= 2.1 or nu > 100 or abs(lam) >= 0.99:
            return 1e10
        lpdf = hansen_skewt_logpdf(z, nu, lam)
        ll   = np.sum(lpdf)
        return -ll if np.isfinite(ll) else 1e10
    best_params, best_nll = [10.0, 0.0], 1e10
    for nu_try in [4.0, 8.0, 15.0]:
        for lam_try in [-0.3, 0.0, 0.3]:
            try:
                res = optimize.minimize(neg_ll, [nu_try, lam_try],
                                        method='L-BFGS-B',
                                        bounds=[(2.2, 80.0), (-0.95, 0.95)],
                                        options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll  = res.fun
                    best_params = res.x.tolist()
            except Exception:
                continue
    nu, lam = best_params
    return float(nu), float(lam)


def skewt_copula_nll(params, u1, u2):
    rho, nu_c = params
    if not (-0.995 < rho < 0.995) or not (2.1 < nu_c < 80.0):
        return 1e10
    x1 = student_t.ppf(u1, df=nu_c)
    x2 = student_t.ppf(u2, df=nu_c)
    det = 1.0 - rho*rho
    if det < 1e-10:
        return 1e10
    q = (x1*x1 - 2.0*rho*x1*x2 + x2*x2) / det
    log_biv = (special.gammaln((nu_c+2.0)/2.0)
               + special.gammaln(nu_c/2.0)
               - 2.0*special.gammaln((nu_c+1.0)/2.0)
               - 0.5*np.log(det)
               - ((nu_c+2.0)/2.0)*np.log(1.0 + q/nu_c)
               + ((nu_c+1.0)/2.0)*np.log(1.0 + x1*x1/nu_c)
               + ((nu_c+1.0)/2.0)*np.log(1.0 + x2*x2/nu_c))
    ll = np.sum(log_biv)
    return -ll if np.isfinite(ll) else 1e10


def fit_skewt_copula(u1_raw, u2_raw, z1, z2):
    nu1, lam1 = fit_marginal_skt(z1)
    nu2, lam2 = fit_marginal_skt(z2)
    u1_skt = hansen_skewt_cdf_vec(z1, nu1, lam1)
    u2_skt = hansen_skewt_cdf_vec(z2, nu2, lam2)
    tau      = stats.kendalltau(u1_skt, u2_skt).statistic
    if not np.isfinite(tau):
        tau = 0.0
    rho_init = float(np.clip(np.sin(np.pi * tau / 2.0), -0.9, 0.9))
    best_res, best_nll = None, 1e10
    for nu_try in [4.0, 8.0, 15.0]:
        for rho_try in [rho_init, 0.0, 0.3]:
            try:
                res = optimize.minimize(skewt_copula_nll,
                                        x0=[rho_try, nu_try],
                                        args=(u1_skt, u2_skt),
                                        method='L-BFGS-B',
                                        bounds=[(-0.99, 0.99), (2.2, 60.0)],
                                        options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        rho_hat, nu_c_hat = rho_init, 10.0
    else:
        rho_hat, nu_c_hat = best_res.x
    lambda_L = t_copula_lambda(rho_hat, nu_c_hat)
    asym_index = (lam1 + lam2) / 2.0
    return {
        'rho': float(rho_hat), 'nu_c': float(nu_c_hat),
        'nu1': float(nu1), 'lam1': float(lam1),
        'nu2': float(nu2), 'lam2': float(lam2),
        'lambda_L': float(lambda_L),
        'asym_index': float(asym_index),
        'u1_skt': u1_skt, 'u2_skt': u2_skt,
        'converged': best_res.success if best_res else False,
        'nll': float(best_res.fun) if best_res else 1e10,
    }


def sample_skewt_copula(cop_params, n_samples, rng):
    rho  = cop_params['rho']
    nu_c = cop_params['nu_c']
    nu1  = cop_params['nu1']
    lam1 = cop_params['lam1']
    nu2  = cop_params['nu2']
    lam2 = cop_params['lam2']
    u1_t, u2_t = sample_student_t_copula(rho, nu_c, n_samples, rng)
    z1_sim = hansen_skewt_ppf_vec(u1_t, nu1, lam1)
    z2_sim = hansen_skewt_ppf_vec(u2_t, nu2, lam2)
    return z1_sim, z2_sim


# ============================================================
# 6. MC VaR/ES
# ============================================================
def copula_mc_var_es(h1, h2, copula_type, copula_params,
                     marg_t_dfs, alpha_levels, n_paths, rng):
    if copula_type == 'joe':
        theta = copula_params['theta']
        u1, u2 = sample_joe_copula(theta, n_paths, rng)
        z1 = inv_pit_student_t(u1, marg_t_dfs[0])
        z2 = inv_pit_student_t(u2, marg_t_dfs[1])
    elif copula_type == 'skt':
        z1, z2 = sample_skewt_copula(copula_params, n_paths, rng)
    else:
        raise ValueError(f"Unknown copula: {copula_type}")

    r1     = np.sqrt(h1) * z1
    r2     = np.sqrt(h2) * z2
    r_port = WEIGHTS[0] * r1 + WEIGHTS[1] * r2

    out = {}
    for alpha in alpha_levels:
        var_a  = np.quantile(r_port, alpha)
        below  = r_port[r_port <= var_a]
        es_a   = np.mean(below) if len(below) > 0 else var_a
        out[alpha] = (float(var_a), float(es_a))
    return out


# ============================================================
# 7. BACKTESTING
# ============================================================
def cf_quantile(alpha, skew, exkurt):
    z = norm.ppf(alpha)
    q = (z + (z**2-1)*skew/6
         + (z**3-3*z)*exkurt/24
         - (2*z**3-5*z)*skew**2/36)
    return q


def compute_cf_rolling_var(port_returns, port_sigma, alpha, cf_window=252):
    T         = len(port_returns)
    var_series = np.full(T, np.nan)
    es_series  = np.full(T, np.nan)
    std_resid  = np.where(port_sigma > 1e-10, port_returns/port_sigma, 0.0)
    for t in range(cf_window, T):
        window_resid = std_resid[t-cf_window:t]
        valid        = np.isfinite(window_resid) & (np.abs(window_resid) < 20)
        if valid.sum() < 50:
            var_series[t] = port_sigma[t] * norm.ppf(alpha)
            continue
        wr  = window_resid[valid]
        sk  = np.clip(float(stats.skew(wr)), -3, 3)
        ek  = np.clip(float(stats.kurtosis(wr)), -2, 30)
        q_cf = cf_quantile(alpha, sk, ek)
        var_series[t] = port_sigma[t] * q_cf
        below = wr[wr < q_cf]
        if len(below) >= 3:
            es_series[t] = port_sigma[t] * np.mean(below)
        else:
            es_series[t] = var_series[t] * 1.3
    return var_series, es_series


def kupiec_test(violations, n, alpha):
    n1   = int(np.sum(violations))
    n0   = n - n1
    pi_hat = n1/n if n > 0 else 0
    if n1 == 0 or n1 == n:
        return {'stat': 0.0, 'p_value': 1.0, 'violations': n1,
                'rate': pi_hat, 'expected_rate': float(alpha), 'pass': True}
    lr   = -2*(n1*np.log(alpha) + n0*np.log(1-alpha)
               - n1*np.log(pi_hat) - n0*np.log(1-pi_hat))
    p_val = 1 - chi2.cdf(lr, df=1)
    return {'stat': float(lr), 'p_value': float(p_val),
            'violations': n1, 'rate': float(pi_hat),
            'expected_rate': float(alpha), 'pass': bool(p_val > 0.05)}


def christoffersen_test(violations):
    v    = violations.astype(int)
    n    = len(v)
    t00  = np.sum((v[:-1]==0) & (v[1:]==0))
    t01  = np.sum((v[:-1]==0) & (v[1:]==1))
    t10  = np.sum((v[:-1]==1) & (v[1:]==0))
    t11  = np.sum((v[:-1]==1) & (v[1:]==1))
    pi_all = (t01+t11)/(n-1) if n > 1 else 0
    pi01   = t01/(t00+t01) if (t00+t01) > 0 else 0
    pi11   = t11/(t10+t11) if (t10+t11) > 0 else 0
    try:
        if all(0 < x < 1 for x in [pi01, pi11, pi_all]):
            lr_ind = (-2*((t00+t10)*np.log(1-pi_all)+(t01+t11)*np.log(pi_all)
                          -t00*np.log(1-pi01)-t01*np.log(pi01)
                          -t10*np.log(1-pi11)-t11*np.log(pi11)))
            p_val = 1 - chi2.cdf(lr_ind, df=1)
        else:
            lr_ind, p_val = 0.0, 1.0
    except Exception:
        lr_ind, p_val = 0.0, 1.0
    return {'stat': float(lr_ind), 'p_value': float(p_val),
            'clusters': int(t11), 'pass': bool(p_val > 0.05)}


def basel_traffic_light(violations, n, alpha):
    n1  = int(np.sum(violations))
    n_blocks = max(1, n//250)
    avg = n1 / n_blocks
    if alpha <= 0.01:
        thresholds = {'green': 4, 'yellow': 9}
    else:
        thresholds = {'green': int(250*alpha*1.5)+1,
                      'yellow': int(250*alpha*2.5)+1}
    color = ('Green' if avg <= thresholds['green']
             else 'Yellow' if avg <= thresholds['yellow']
             else 'Red')
    return {'color': color, 'violations_per_block': float(avg),
            'n_blocks': n_blocks, 'pass': bool(color == 'Green')}


def es_backtest_acerbi_szekely(port_returns, var_series, es_series, alpha):
    valid = (np.isfinite(var_series) & np.isfinite(es_series)
             & np.isfinite(port_returns))
    r, v, es = port_returns[valid], var_series[valid], es_series[valid]
    n        = len(r)
    violations = r < v
    n_viol   = int(np.sum(violations))
    if n_viol < 3:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True,
                'n_violations': n_viol}
    numerator = np.sum(r[violations])
    es_avg    = np.mean(es[violations])
    if abs(es_avg) < 1e-12:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True,
                'n_violations': n_viol}
    z1    = numerator / (n * alpha * es_avg) - 1
    p_val = 2 * norm.cdf(-abs(z1))
    return {'z_stat': float(z1), 'p_value': float(p_val),
            'pass': bool(p_val > 0.05), 'n_violations': n_viol}


def fz_score_series(port_returns, var_series, es_series, alpha):
    valid = (np.isfinite(var_series) & np.isfinite(es_series)
             & np.isfinite(port_returns) & (es_series < 0) & (var_series < 0))
    r, V, E = port_returns[valid], var_series[valid], es_series[valid]
    n       = len(r)
    if n == 0:
        return np.array([]), np.nan
    indicator = (r <= V).astype(float)
    with np.errstate(divide='ignore', invalid='ignore'):
        s = (1.0/alpha)*indicator*(V-r)/(-E) - V/E + np.log(-E) - 1.0
    s = s[np.isfinite(s)]
    return s, float(np.mean(s)) if len(s) else np.nan


def trinity_test(port_returns, var_series, es_series, alpha):
    valid = np.isfinite(var_series) & np.isfinite(port_returns)
    r, v  = port_returns[valid], var_series[valid]
    n     = len(r)
    violations = (r < v).astype(int)
    kupiec = kupiec_test(violations, n, alpha)
    cc     = christoffersen_test(violations)
    basel  = basel_traffic_light(violations, n, alpha)
    es_t   = es_backtest_acerbi_szekely(port_returns[valid], v,
                                        es_series[valid] if es_series is not None
                                        else v*1.3, alpha)
    trinity_pass = bool(kupiec['pass'] and cc['pass'] and basel['pass'])
    return {'kupiec': kupiec, 'christoffersen': cc, 'basel': basel,
            'es_test': es_t, 'trinity_pass': trinity_pass,
            'n_oos': n, 'violation_rate': float(kupiec['rate'])}


# ============================================================
# 8. DM TESTS
# ============================================================
def dm_test(loss_series_1, loss_series_2):
    valid = np.isfinite(loss_series_1) & np.isfinite(loss_series_2)
    l1, l2 = loss_series_1[valid], loss_series_2[valid]
    d  = l1 - l2
    n  = len(d)
    if n < 10:
        return {'t_stat': 0.0, 'p_value': 1.0, 'mean_loss_diff': 0.0,
                'n': n, 'significant_harvey': False}
    d_bar   = np.mean(d)
    max_lag = max(1, int(n**(1/3)))
    nw_var  = np.var(d, ddof=1)
    for k in range(1, max_lag+1):
        w = 1 - k/(max_lag+1)
        nw_var += 2*w*np.cov(d[k:], d[:-k])[0, 1]
    se     = np.sqrt(nw_var/n) if nw_var > 0 else 1e-12
    t_stat = d_bar/se if se > 1e-12 else 0.0
    p_val  = 2*norm.cdf(-abs(t_stat))
    return {'t_stat': float(t_stat), 'p_value': float(p_val),
            'mean_loss_diff': float(d_bar), 'n': int(n),
            'significant_harvey': bool(abs(t_stat) > 3.0)}


def dm_qlike(actual_r2, forecast_var1, forecast_var2):
    valid = (np.isfinite(actual_r2) & np.isfinite(forecast_var1)
             & np.isfinite(forecast_var2))
    valid &= (forecast_var1 > 0) & (forecast_var2 > 0)
    r2, h1, h2 = actual_r2[valid], forecast_var1[valid], forecast_var2[valid]
    loss1 = np.log(h1) + r2/h1
    loss2 = np.log(h2) + r2/h2
    return dm_test(loss1, loss2)


# ============================================================
# 9. OOS FORECASTING for ONE pair (3 models: DCC + Joe + SkewT)
# ============================================================
def oos_forecast_pair(ret1, ret2, x21, x22, dates, oos_start,
                      pair_label, window=WINDOW, refit_every=REFIT_EVERY):
    """One-step-ahead OOS forecasts for DCC + Joe + SkewT."""
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T       = len(ret1)
    n_oos   = T - oos_idx

    # Storage
    h1_store   = {m: np.full(n_oos, np.nan) for m in MODELS}
    h2_store   = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_store  = {m: np.full(n_oos, np.nan) for m in MODELS}
    pvar_store = {m: np.full(n_oos, np.nan) for m in MODELS}

    # Copula parameter series
    cop_t_rho_series    = np.full(n_oos, np.nan)
    cop_t_nu_series     = np.full(n_oos, np.nan)
    lambda_L_t_series   = np.full(n_oos, np.nan)  # from t-copula fit (λ_L measure)
    lambda_U_joe_series = np.full(n_oos, np.nan)

    # Per-day params for MC
    cop_joe_params  = [None] * n_oos
    cop_skt_params  = [None] * n_oos
    marg_t_df_1     = np.full(n_oos, np.nan)
    marg_t_df_2     = np.full(n_oos, np.nan)

    # State variables
    state = {
        'marg1_p': None, 'marg2_p': None,
        'h1_prev': np.nan, 'h2_prev': np.nan,
        'g1_prev': np.nan, 'g2_prev': np.nan,
        'last_fit': -refit_every,
        # DCC
        'dcc_a': 0.0, 'dcc_b': 0.0,
        'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
        'eps1_prev': 0.0, 'eps2_prev': 0.0,
        'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        # Copulas
        'copula_t': None, 'copula_joe': None, 'copula_skt': None,
        'marg_t_df_1': np.nan, 'marg_t_df_2': np.nan,
    }

    for i in range(n_oos):
        t = oos_idx + i
        if i % 500 == 0:
            elapsed = time.time() - START_TIME
            print(f"    [{pair_label}] OOS day {i}/{n_oos} ({elapsed:.0f}s)")

        need_refit = (i - state['last_fit'] >= refit_every
                      or state['marg1_p'] is None)

        if need_refit:
            s = max(0, t - window)
            tr1   = ret1[s:t]
            tr2   = ret2[s:t]
            tr_x21 = x21[s:t]
            tr_x22 = x22[s:t]

            # A4f marginals (shared)
            a4f_1 = fit_a4f(tr1, tr_x21)
            a4f_2 = fit_a4f(tr2, tr_x22)
            eps_1 = tr1 / np.sqrt(np.maximum(a4f_1['h'], 1e-16))
            eps_2 = tr2 / np.sqrt(np.maximum(a4f_2['h'], 1e-16))

            # DCC
            dcc = fit_dcc(eps_1, eps_2)

            # Standard t PIT
            df_1 = fit_marginal_t_df(eps_1)
            df_2 = fit_marginal_t_df(eps_2)
            u1_t = pit_student_t(eps_1, df_1)
            u2_t = pit_student_t(eps_2, df_2)

            # t-copula (for λ_L estimation only, not VaR model)
            cop_t   = fit_student_t_copula(u1_t, u2_t)
            # Joe copula
            cop_joe = fit_joe_copula(u1_t, u2_t)
            # SkewT copula
            cop_skt = fit_skewt_copula(u1_t, u2_t, eps_1, eps_2)

            # Update state
            state['marg1_p']     = ('A4f', a4f_1['params'])
            state['marg2_p']     = ('A4f', a4f_2['params'])
            state['h1_prev']     = float(a4f_1['h'][-1])
            state['h2_prev']     = float(a4f_2['h'][-1])
            state['g1_prev']     = float(a4f_1['g'][-1])
            state['g2_prev']     = float(a4f_2['g'][-1])
            state['last_fit']    = i
            state['marg_t_df_1'] = df_1
            state['marg_t_df_2'] = df_2
            # DCC
            state['dcc_a']     = dcc['a']
            state['dcc_b']     = dcc['b']
            state['qbar11']    = dcc['qbar11']
            state['qbar22']    = dcc['qbar22']
            state['qbar12']    = dcc['qbar12']
            state['eps1_prev'] = float(eps_1[-1])
            state['eps2_prev'] = float(eps_2[-1])
            state['q11_prev']  = dcc['qbar11']
            state['q22_prev']  = dcc['qbar22']
            state['q12_prev']  = dcc['qbar12']
            # Copulas
            state['copula_t']   = cop_t
            state['copula_joe'] = cop_joe
            state['copula_skt'] = cop_skt

        # ---- One-step-ahead forecast (t-1 info → h_t) ----
        r1_prev  = ret1[t-1]
        r2_prev  = ret2[t-1]
        x21_prev = x21[t-1]
        x22_prev = x22[t-1]

        marg1 = state['marg1_p']
        marg2 = state['marg2_p']
        if marg1 is None or marg2 is None:
            continue

        # Asset 1 A4f recursion
        p    = marg1[1]
        tau1 = max(p[0] + p[1]*x21_prev, 1e-16)
        u1_  = r1_prev / np.sqrt(tau1)
        ind1 = 1.0 if r1_prev < 0 else 0.0
        g1   = p[2] + p[3]*u1_**2 + p[4]*u1_**2*ind1 + p[5]*state['g1_prev']
        g1   = max(g1, 1e-16)
        h1_t = max(tau1 * g1, 1e-16)
        state['g1_prev'] = g1

        # Asset 2 A4f recursion
        p    = marg2[1]
        tau2 = max(p[0] + p[1]*x22_prev, 1e-16)
        u2_  = r2_prev / np.sqrt(tau2)
        ind2 = 1.0 if r2_prev < 0 else 0.0
        g2   = p[2] + p[3]*u2_**2 + p[4]*u2_**2*ind2 + p[5]*state['g2_prev']
        g2   = max(g2, 1e-16)
        h2_t = max(tau2 * g2, 1e-16)
        state['g2_prev'] = g2

        state['h1_prev'] = h1_t
        state['h2_prev'] = h2_t

        for m in MODELS:
            h1_store[m][i] = h1_t
            h2_store[m][i] = h2_t

        # Record marginal dfs
        marg_t_df_1[i] = state['marg_t_df_1']
        marg_t_df_2[i] = state['marg_t_df_2']

        # DCC model: update Q matrix and compute DCC rho
        a_d = state['dcc_a']
        b_d = state['dcc_b']
        c_d = 1.0 - a_d - b_d
        e1p = state['eps1_prev']
        e2p = state['eps2_prev']
        q11 = c_d*state['qbar11'] + a_d*e1p**2 + b_d*state['q11_prev']
        q22 = c_d*state['qbar22'] + a_d*e2p**2 + b_d*state['q22_prev']
        q12 = c_d*state['qbar12'] + a_d*e1p*e2p + b_d*state['q12_prev']
        denom = np.sqrt(q11*q22)
        rho_t = np.clip(q12/denom if denom > 1e-20 else 0.0, -0.9999, 0.9999)
        rho_store['DCC-A4f-ASYM'][i] = rho_t
        e1n = r1_prev/np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
        e2n = r2_prev/np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
        state['eps1_prev'] = e1n
        state['eps2_prev'] = e2n
        state['q11_prev'] = q11
        state['q22_prev'] = q22
        state['q12_prev'] = q12
        s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
        pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*rho_t*s1*s2
        pvar_store['DCC-A4f-ASYM'][i] = max(pv, 1e-16)

        # Joe copula model: record params, pvar using Joe rho_approx
        cop_joe = state['copula_joe']
        if cop_joe is not None:
            lambda_U_joe_series[i] = cop_joe.get('lambda_U', 0.0)
            cop_joe_params[i] = cop_joe
            th  = cop_joe['theta']
            tau_j = 1.0 - 2.0/(th*(th+2.0)) if th > 1.0 else 0.0
            rho_j = np.sin(np.pi*tau_j/2.0)
            rho_store['Copula-Joe-A4f-ASYM'][i] = rho_j
            s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
            pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*rho_j*s1*s2
            pvar_store['Copula-Joe-A4f-ASYM'][i] = max(pv, 1e-16)

        # SkewT copula model
        cop_skt = state['copula_skt']
        if cop_skt is not None:
            cop_skt_params[i] = cop_skt
            rho_s = cop_skt['rho']
            rho_store['Copula-SkewT-A4f-ASYM'][i] = rho_s
            s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
            pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*rho_s*s1*s2
            pvar_store['Copula-SkewT-A4f-ASYM'][i] = max(pv, 1e-16)

        # t-copula: record rho + nu for λ_L estimation
        cop_t = state['copula_t']
        if cop_t is not None:
            cop_t_rho_series[i]  = cop_t['rho']
            cop_t_nu_series[i]   = cop_t['nu']
            lambda_L_t_series[i] = t_copula_lambda(cop_t['rho'], cop_t['nu'])

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar_store,
        'h1': h1_store, 'h2': h2_store, 'rho': rho_store,
        'oos_dates': oos_dates, 'oos_idx': oos_idx,
        'lambda_L_t': lambda_L_t_series,
        'lambda_U_joe': lambda_U_joe_series,
        'cop_t_rho': cop_t_rho_series,
        'cop_t_nu': cop_t_nu_series,
        'cop_joe_params': cop_joe_params,
        'cop_skt_params': cop_skt_params,
        'marg_t_df_1': marg_t_df_1,
        'marg_t_df_2': marg_t_df_2,
    }


def compute_copula_mc_var(forecasts, copula_type, model_key,
                          alpha_levels, n_paths):
    h1_arr = forecasts['h1'][model_key]
    h2_arr = forecasts['h2'][model_key]
    n_oos  = len(h1_arr)

    if copula_type == 'joe':
        params_list = forecasts['cop_joe_params']
    elif copula_type == 'skt':
        params_list = forecasts['cop_skt_params']
    else:
        raise ValueError(copula_type)

    df1_arr = forecasts['marg_t_df_1']
    df2_arr = forecasts['marg_t_df_2']

    var_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}
    es_out  = {a: np.full(n_oos, np.nan) for a in alpha_levels}

    for i in range(n_oos):
        if not (np.isfinite(h1_arr[i]) and np.isfinite(h2_arr[i])):
            continue
        if params_list[i] is None:
            continue
        sub_rng = np.random.default_rng(42 + i)
        mc = copula_mc_var_es(
            h1_arr[i], h2_arr[i],
            copula_type, params_list[i],
            (float(df1_arr[i]), float(df2_arr[i])),
            alpha_levels, n_paths, sub_rng)
        for a in alpha_levels:
            var_out[a][i] = mc[a][0]
            es_out[a][i]  = mc[a][1]

    return var_out, es_out


# ============================================================
# 10. DATA LOADING
# ============================================================
def load_data():
    import yfinance as yf

    tickers = ['SPY', 'QQQ', 'IWM', 'XLF', 'TLT', 'IEF', 'TIP',
               'GLD', 'SLV', 'USO', 'UUP', 'FXE', 'LQD', 'HYG']
    print(f"Downloading prices: {tickers} + ^VIX + ^GVZ ...")

    closes = {}
    for t in tickers:
        try:
            raw = yf.download(t, start=DATA_START, end=DATA_END,
                              auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            closes[t] = raw['Close']
            print(f"  {t}: {len(raw)} rows")
        except Exception as e:
            print(f"  {t}: DOWNLOAD FAILED ({e})")
            closes[t] = pd.Series(dtype=float)

    vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)
    gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)

    def _close(raw):
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return raw['Close']

    price_cols = {t.lower(): closes[t] for t in tickers if len(closes[t]) > 0}
    df = pd.DataFrame({
        **price_cols,
        'vix': _close(vix_raw),
        'gvz': _close(gvz_raw),
    }).sort_index()

    df = df.dropna(subset=['spy', 'vix'])
    df['gvz_filled'] = df['gvz'].copy()
    df.loc[df['gvz_filled'].isna(), 'gvz_filled'] = df.loc[df['gvz_filled'].isna(), 'vix']
    df['gvz_filled'] = df['gvz_filled'].ffill()

    for t in tickers:
        col = t.lower()
        if col in df.columns:
            df[f'ret_{col}']    = np.log(df[col] / df[col].shift(1))
            df[f'simple_{col}'] = df[col].pct_change()

    df['vix2'] = (df['vix'] / 100.0)**2 / 252.0
    df['gvz2'] = (df['gvz_filled'] / 100.0)**2 / 252.0
    df = df.dropna(subset=['ret_spy', 'vix2'])

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')} ({len(df)} days)")
    return df


# ============================================================
# 11. EVALUATE PAIR
# ============================================================
def evaluate_pair(pair_name, asset1, asset2, reg1_col, reg2_col,
                  asset_class, df):
    print(f"\n{'=' * 72}")
    print(f"PAIR: {pair_name}  ({asset1} vs {asset2}) [{asset_class}]")
    print(f"{'=' * 72}")

    a1l = asset1.lower()
    a2l = asset2.lower()
    required = [f'ret_{a1l}', f'ret_{a2l}',
                f'simple_{a1l}', f'simple_{a2l}',
                reg1_col, reg2_col]
    # Check columns exist
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"  SKIP: missing columns {missing}")
        return None

    pair_df  = df.dropna(subset=required).copy()
    if len(pair_df) < 500:
        print(f"  SKIP: only {len(pair_df)} non-NaN rows")
        return None

    print(f"  Sample: {len(pair_df)} days, "
          f"{pair_df.index[0].strftime('%Y-%m-%d')} to "
          f"{pair_df.index[-1].strftime('%Y-%m-%d')}")

    ret1     = pair_df[f'ret_{a1l}'].values
    ret2     = pair_df[f'ret_{a2l}'].values
    x21      = pair_df[reg1_col].values
    x22      = pair_df[reg2_col].values
    dates    = pair_df.index.values
    port_ret = (WEIGHTS[0]*pair_df[f'simple_{a1l}'].values
                + WEIGHTS[1]*pair_df[f'simple_{a2l}'].values)

    corr = float(np.corrcoef(ret1, ret2)[0, 1])
    print(f"  Full-sample corr: {corr:+.4f}")

    t_start   = time.time()
    forecasts = oos_forecast_pair(ret1, ret2, x21, x22, dates, OOS_START,
                                  pair_name)
    oos_idx  = forecasts['oos_idx']
    oos_dates = forecasts['oos_dates']
    n_oos    = len(oos_dates)
    port_ret_oos = port_ret[oos_idx:]
    r2_oos   = port_ret_oos**2

    print(f"  OOS: {pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} to "
          f"{pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')} "
          f"({n_oos} days)")

    # ---- VaR/ES computation ----
    var_store  = {m: {} for m in MODELS}
    es_store   = {m: {} for m in MODELS}
    fz_m_store = {m: {} for m in MODELS}
    fz_s_store = {m: {} for m in MODELS}
    model_res  = {}

    # M1: DCC-CF-Rolling
    m = 'DCC-A4f-ASYM'
    port_sigma = np.sqrt(forecasts['pvar'][m])
    mr = {'var_tests': {}, 'fz_score': {}}
    for alpha in ALPHA_LEVELS:
        vs, es = compute_cf_rolling_var(port_ret_oos, port_sigma, alpha)
        var_store[m][alpha] = vs
        es_store[m][alpha]  = es
        tri = trinity_test(port_ret_oos, vs, es, alpha)
        fzs, fzm = fz_score_series(port_ret_oos, vs, es, alpha)
        fz_m_store[m][alpha] = fzm
        fz_s_store[m][alpha] = fzs
        ak = f"alpha_{alpha:.3f}"
        mr['var_tests'][ak]  = tri
        mr['fz_score'][ak]   = {'mean': fzm, 'n': int(len(fzs))}
    model_res[m] = mr

    # M5: Joe, M4: SkewT
    copula_map = {
        'Copula-Joe-A4f-ASYM': 'joe',
        'Copula-SkewT-A4f-ASYM': 'skt',
    }
    for m, ctype in copula_map.items():
        print(f"  Computing MC VaR for {m} ...")
        vd, ed = compute_copula_mc_var(forecasts, ctype, m,
                                       ALPHA_LEVELS, MC_PATHS)
        mr = {'var_tests': {}, 'fz_score': {}}
        for alpha in ALPHA_LEVELS:
            vs = vd[alpha]; es = ed[alpha]
            var_store[m][alpha] = vs
            es_store[m][alpha]  = es
            tri = trinity_test(port_ret_oos, vs, es, alpha)
            fzs, fzm = fz_score_series(port_ret_oos, vs, es, alpha)
            fz_m_store[m][alpha] = fzm
            fz_s_store[m][alpha] = fzs
            ak = f"alpha_{alpha:.3f}"
            mr['var_tests'][ak] = tri
            mr['fz_score'][ak]  = {'mean': fzm, 'n': int(len(fzs))}
        model_res[m] = mr

    # ---- DM QLIKE tests vs baseline DCC ----
    dm_joe_vs_dcc = dm_qlike(r2_oos,
                             forecasts['pvar']['Copula-Joe-A4f-ASYM'],
                             forecasts['pvar']['DCC-A4f-ASYM'])
    dm_skt_vs_dcc = dm_qlike(r2_oos,
                             forecasts['pvar']['Copula-SkewT-A4f-ASYM'],
                             forecasts['pvar']['DCC-A4f-ASYM'])

    # ---- Lambda_L: mean of t-copula λ_L (represents OOS empirical lower tail dep) ----
    lambda_L_mean = float(np.nanmean(forecasts['lambda_L_t']))
    lambda_U_joe_mean = float(np.nanmean(forecasts['lambda_U_joe']))

    # ---- Mean QLIKE ----
    qlike_means = {}
    for m_k in MODELS:
        pv = forecasts['pvar'][m_k]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_oos)
        q = np.log(pv[valid]) + r2_oos[valid] / pv[valid]
        qlike_means[m_k] = float(np.mean(q))

    # ---- Summary print ----
    t_joe = dm_joe_vs_dcc.get('t_stat', 0.0)
    t_skt = dm_skt_vs_dcc.get('t_stat', 0.0)
    sig_joe = "***Harvey" if abs(t_joe) > 3.0 else ("*" if dm_joe_vs_dcc.get('p_value', 1.0) < 0.05 else "")
    print(f"  λ_L(t-copula mean): {lambda_L_mean:.4f}")
    print(f"  DM Joe vs DCC: t={t_joe:+.3f} {sig_joe}")
    print(f"  DM SkewT vs DCC: t={t_skt:+.3f}")

    return {
        'pair_name': pair_name,
        'asset1': asset1, 'asset2': asset2,
        'asset_class': asset_class,
        'n_oos': int(n_oos),
        'full_sample_corr': float(corr),
        'lambda_L_t_mean': float(lambda_L_mean),
        'lambda_U_joe_mean': float(lambda_U_joe_mean),
        'models': model_res,
        'dm_joe_vs_dcc': dm_joe_vs_dcc,
        'dm_skt_vs_dcc': dm_skt_vs_dcc,
        'mean_qlike': qlike_means,
        'oos_dates_first': pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d'),
        'oos_dates_last':  pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d'),
        # Private (for plots)
        '_fz_mean_store': fz_m_store,
        '_fit_time_s':     float(time.time() - t_start),
    }


# ============================================================
# 12. SPEARMAN TEST (H1)
# ============================================================
def run_spearman_test(cross_table):
    """
    Formal Spearman test: H1: Spearman(λ_L, DM_Joe) < 0
    Using scipy.stats.spearmanr with one-sided p-value.
    """
    lambda_arr = np.array([r['lambda_L_t_mean'] for r in cross_table])
    dm_joe_arr = np.array([r['dm_joe_t'] for r in cross_table])
    dm_skt_arr = np.array([r['dm_skt_t'] for r in cross_table])
    n = len(lambda_arr)

    results = {}

    # Two-sided Spearman
    try:
        sp_joe = stats.spearmanr(lambda_arr, dm_joe_arr)
        sp_skt = stats.spearmanr(lambda_arr, dm_skt_arr)
        # One-sided p for H1: rho < 0 (negative relationship)
        p_one_sided_joe = sp_joe.pvalue / 2.0 if sp_joe.statistic < 0 else 1.0 - sp_joe.pvalue / 2.0
        p_one_sided_skt = sp_skt.pvalue / 2.0 if sp_skt.statistic < 0 else 1.0 - sp_skt.pvalue / 2.0

        results = {
            'n': int(n),
            'lambda_L_vs_dm_joe': {
                'spearman_rho': float(sp_joe.statistic),
                'p_two_sided': float(sp_joe.pvalue),
                'p_one_sided_neg': float(p_one_sided_joe),
                'h1_confirmed_p05': bool(sp_joe.statistic < 0 and p_one_sided_joe < 0.05),
                'h1_confirmed_p10': bool(sp_joe.statistic < 0 and p_one_sided_joe < 0.10),
            },
            'lambda_L_vs_dm_skt': {
                'spearman_rho': float(sp_skt.statistic),
                'p_two_sided': float(sp_skt.pvalue),
                'p_one_sided_neg': float(p_one_sided_skt),
                'h1_confirmed_p05': bool(sp_skt.statistic < 0 and p_one_sided_skt < 0.05),
                'h1_confirmed_p10': bool(sp_skt.statistic < 0 and p_one_sided_skt < 0.10),
            },
            'lambda_arr': lambda_arr.tolist(),
            'dm_joe_arr': dm_joe_arr.tolist(),
            'dm_skt_arr': dm_skt_arr.tolist(),
        }
        print(f"\n  Spearman(λ_L, DM_Joe): rho={sp_joe.statistic:+.3f} "
              f"p2={sp_joe.pvalue:.3f} p1(neg)={p_one_sided_joe:.3f}")
        print(f"  Spearman(λ_L, DM_SkewT): rho={sp_skt.statistic:+.3f} "
              f"p2={sp_skt.pvalue:.3f} p1(neg)={p_one_sided_skt:.3f}")
        print(f"  H1 (Joe, p<0.05 one-sided): {'CONFIRMED' if results['lambda_L_vs_dm_joe']['h1_confirmed_p05'] else 'REJECTED'}")
    except Exception as e:
        print(f"  Spearman error: {e}")
        results = {'error': str(e), 'n': int(n)}

    return results


# ============================================================
# 13. PLOTS
# ============================================================
def make_plots(pair_results, cross_table, spearman_results):
    """Generate main scatter plot dm_vs_lambdaL_N13.png"""

    # --- Plot 1: DM vs λ_L scatter with asset-class coloring ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    class_colors = {
        'equity-equity':   '#E53935',
        'equity-bond':     '#1E88E5',
        'equity-commodity': '#43A047',
        'equity-fx':       '#FB8C00',
        'equity-credit':   '#8E24AA',
    }
    class_labels = {
        'equity-equity':   'Equity-Equity (high λ_L)',
        'equity-bond':     'Equity-Bond (low λ_L)',
        'equity-commodity': 'Equity-Commodity',
        'equity-fx':       'Equity-FX',
        'equity-credit':   'Equity-Credit',
    }

    for ax_idx, (dm_key, dm_label) in enumerate([
        ('dm_joe_t',  'DM t-stat: Joe vs DCC'),
        ('dm_skt_t',  'DM t-stat: SkewT vs DCC'),
    ]):
        ax = axes[ax_idx]
        plotted_classes = set()
        for r in cross_table:
            ac = r.get('asset_class', 'unknown')
            col = class_colors.get(ac, 'gray')
            lbl = class_labels.get(ac, ac) if ac not in plotted_classes else None
            ax.scatter(r['lambda_L_t_mean'], r[dm_key],
                       color=col, s=80, label=lbl, zorder=3, alpha=0.85)
            plotted_classes.add(ac)
            ax.annotate(r['pair'], (r['lambda_L_t_mean'], r[dm_key]),
                        fontsize=7, ha='left', va='bottom',
                        xytext=(3, 3), textcoords='offset points')

        # Reference lines
        ax.axhline(y=0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)
        ax.axhline(y=3.0, color='red', linewidth=0.8, linestyle=':', alpha=0.5)
        ax.axhline(y=-3.0, color='red', linewidth=0.8, linestyle=':', alpha=0.5)

        # Regression line
        lambda_arr = np.array([r['lambda_L_t_mean'] for r in cross_table])
        dm_arr     = np.array([r[dm_key] for r in cross_table])
        valid_mask = np.isfinite(lambda_arr) & np.isfinite(dm_arr)
        if valid_mask.sum() >= 3:
            m_fit, b_fit = np.polyfit(lambda_arr[valid_mask], dm_arr[valid_mask], 1)
            x_line = np.linspace(lambda_arr[valid_mask].min(),
                                 lambda_arr[valid_mask].max(), 50)
            ax.plot(x_line, m_fit*x_line + b_fit, 'k-', linewidth=1.5, alpha=0.6,
                    label=f'OLS (slope={m_fit:+.1f})')

        # Spearman annotation
        if dm_key == 'dm_joe_t':
            sp_res = spearman_results.get('lambda_L_vs_dm_joe', {})
        else:
            sp_res = spearman_results.get('lambda_L_vs_dm_skt', {})
        rho_sp = sp_res.get('spearman_rho', np.nan)
        p1     = sp_res.get('p_one_sided_neg', np.nan)
        txt    = f"Spearman ρ = {rho_sp:+.3f}\np(one-sided<0) = {p1:.3f}"
        ax.text(0.03, 0.97, txt, transform=ax.transAxes,
                fontsize=9, va='top', ha='left',
                bbox=dict(boxstyle='round,pad=0.3', fc='wheat', alpha=0.5))

        ax.set_xlabel('λ_L (t-copula lower tail dependence, OOS mean)', fontsize=9)
        ax.set_ylabel(dm_label, fontsize=9)
        ax.set_title(f'K1100e: {dm_label}\nN=13 pairs, asset-class labeled',
                     fontsize=9, fontweight='bold')
        ax.legend(fontsize=7, loc='lower right')
        ax.grid(True, alpha=0.3)

    plt.suptitle('K1100e: λ_L Threshold Hypothesis — Cross-Asset Copula Test (N=13)',
                 fontsize=11, fontweight='bold')
    plt.tight_layout()
    out1 = os.path.join(SCRIPT_DIR, 'dm_vs_lambdaL_N13.png')
    plt.savefig(out1, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved: {out1}")

    # --- Plot 2: DM heatmap (13 pairs x 2 copula models) ---
    fig, ax = plt.subplots(figsize=(7, 8))
    pairs_done = [r['pair'] for r in cross_table]
    model_labels = ['Joe vs DCC', 'SkewT vs DCC']
    dm_matrix = np.zeros((len(pairs_done), 2))
    for pi, r in enumerate(cross_table):
        dm_matrix[pi, 0] = r['dm_joe_t']
        dm_matrix[pi, 1] = r['dm_skt_t']

    vmax = max(3.5, np.max(np.abs(dm_matrix)))
    norm = mcolors.TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
    im   = ax.imshow(dm_matrix, cmap='RdYlGn', norm=norm, aspect='auto')
    plt.colorbar(im, ax=ax, label='DM t-stat (positive = copula better than DCC)')
    ax.set_xticks(range(2))
    ax.set_xticklabels(model_labels, fontsize=10)
    ax.set_yticks(range(len(pairs_done)))
    ax.set_yticklabels([f"{r['pair']} [{r.get('asset_class','?')[:10]}]"
                        for r in cross_table], fontsize=8)
    ax.set_title('K1100e: DM QLIKE t-stat — N=13 pairs\n|t|>3 = Harvey sig',
                 fontsize=10)
    for pi in range(len(pairs_done)):
        for mi in range(2):
            t_val = dm_matrix[pi, mi]
            col   = 'white' if abs(t_val) > 1.5 else 'black'
            ax.text(mi, pi, f'{t_val:+.2f}', ha='center', va='center',
                    fontsize=8, color=col,
                    fontweight='bold' if abs(t_val) > 3.0 else 'normal')

    plt.tight_layout()
    out2 = os.path.join(SCRIPT_DIR, 'k1100e_dm_heatmap.png')
    plt.savefig(out2, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved: {out2}")


# ============================================================
# 14. MAIN
# ============================================================
def to_json_safe(obj):
    if isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()
                if not k.startswith('_')}
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

    pair_results = {}
    pairs_done   = []

    for pair_info in PAIRS:
        pair_name, a1, a2, r1_col, r2_col, asset_class = pair_info
        elapsed = time.time() - START_TIME
        print(f"\n>>> [{elapsed:.0f}s elapsed] Starting pair {pair_name} [{asset_class}]")

        result = evaluate_pair(pair_name, a1, a2, r1_col, r2_col, asset_class, df)
        if result is None:
            print(f"  Pair {pair_name} skipped (missing data)")
            continue
        pair_results[pair_name] = result
        pairs_done.append(pair_name)

        # Checkpoint save
        safe = {pn: to_json_safe(pr) for pn, pr in pair_results.items()}
        with open(RESULTS_PATH, 'w') as f:
            json.dump({'experiment_id': EXPERIMENT_ID,
                       'pair_results': safe,
                       'pairs_done': list(pair_results.keys()),
                       'timestamp_partial': datetime.now(timezone.utc).isoformat()},
                      f, indent=2)
        print(f"  Checkpoint saved ({len(pair_results)}/{len(PAIRS)} pairs done)")

    # ---- Cross-pair analysis ----
    print(f"\n{'=' * 72}")
    print("CROSS-PAIR ANALYSIS — λ_L Threshold Hypothesis")
    print(f"{'=' * 72}")

    cross_table = []
    for pair_name in pairs_done:
        pr = pair_results[pair_name]
        row = {
            'pair':          pair_name,
            'asset_class':   pr['asset_class'],
            'corr':          pr['full_sample_corr'],
            'lambda_L_t_mean': pr['lambda_L_t_mean'],
            'lambda_U_joe_mean': pr['lambda_U_joe_mean'],
            'n_oos':         pr['n_oos'],
            'dm_joe_t':      pr['dm_joe_vs_dcc'].get('t_stat', 0.0),
            'dm_joe_p':      pr['dm_joe_vs_dcc'].get('p_value', 1.0),
            'dm_skt_t':      pr['dm_skt_vs_dcc'].get('t_stat', 0.0),
            'dm_skt_p':      pr['dm_skt_vs_dcc'].get('p_value', 1.0),
            'harvey_joe':    bool(abs(pr['dm_joe_vs_dcc'].get('t_stat', 0.0)) > 3.0
                                  and pr['dm_joe_vs_dcc'].get('t_stat', 0.0) > 0),
            'harvey_skt':    bool(abs(pr['dm_skt_vs_dcc'].get('t_stat', 0.0)) > 3.0
                                  and pr['dm_skt_vs_dcc'].get('t_stat', 0.0) > 0),
        }
        cross_table.append(row)

    # Print main table
    print(f"\n{'Pair':<12} {'Asset Class':<20} {'λ_L':>6} {'λ_U_Joe':>8} "
          f"{'DM_Joe':>8} {'DM_SKT':>8} {'Harvey_Joe':>11}")
    print("-" * 85)
    for r in cross_table:
        harvey_str = "YES***" if r['harvey_joe'] else "no"
        print(f"{r['pair']:<12} {r['asset_class']:<20} "
              f"{r['lambda_L_t_mean']:>6.4f} {r['lambda_U_joe_mean']:>8.4f} "
              f"{r['dm_joe_t']:>+8.3f} {r['dm_skt_t']:>+8.3f} "
              f"{harvey_str:>11}")

    # Harvey pass counts by asset class
    print(f"\nHarvey |t|>3.0 pass count (Joe copula beats DCC):")
    by_class = {}
    for r in cross_table:
        ac = r['asset_class']
        if ac not in by_class:
            by_class[ac] = {'total': 0, 'pass': 0}
        by_class[ac]['total'] += 1
        if r['harvey_joe']:
            by_class[ac]['pass'] += 1
    for ac, cnt in by_class.items():
        print(f"  {ac:<22}: {cnt['pass']}/{cnt['total']} PASS")

    # Total Harvey pass
    n_harvey_joe = sum(r['harvey_joe'] for r in cross_table)
    n_harvey_skt = sum(r['harvey_skt'] for r in cross_table)
    print(f"\n  Total Harvey |t|>3.0 PASS (Joe): {n_harvey_joe}/{len(cross_table)}")
    print(f"  Total Harvey |t|>3.0 PASS (SkewT): {n_harvey_skt}/{len(cross_table)}")

    # ---- Formal Spearman test (H1) ----
    print(f"\n{'=' * 72}")
    print("FORMAL H1 TEST: Spearman(λ_L, DM_Joe) < 0")
    print(f"{'=' * 72}")
    spearman_results = {}
    if len(cross_table) >= 3:
        spearman_results = run_spearman_test(cross_table)
    else:
        print("  Not enough pairs for Spearman test")

    # ---- Scenario determination ----
    sp_joe = spearman_results.get('lambda_L_vs_dm_joe', {})
    h1_confirmed = sp_joe.get('h1_confirmed_p05', False)
    h1_p10 = sp_joe.get('h1_confirmed_p10', False)

    if h1_confirmed:
        scenario = 'CONFIRMED'
        scenario_desc = (f"λ_L threshold confirmed: Spearman ρ<0, p<0.05 (one-sided). "
                         f"N={len(cross_table)}, {n_harvey_joe} pairs Harvey sig. "
                         f"Paper 3 'asset-class-specific copula' claim supported.")
    elif h1_p10:
        scenario = 'PARTIAL'
        scenario_desc = (f"Partial confirmation: Spearman ρ<0, p<0.10 (marginal). "
                         f"N={len(cross_table)}, {n_harvey_joe} pairs Harvey sig.")
    elif sp_joe.get('spearman_rho', 0.0) < 0:
        scenario = 'TREND_ONLY'
        scenario_desc = (f"Negative trend but not significant: "
                         f"Spearman ρ<0 but p>{0.10:.2f}. "
                         f"N={len(cross_table)}, {n_harvey_joe} pairs Harvey sig.")
    else:
        scenario = 'NULL'
        scenario_desc = (f"H1 rejected: No negative Spearman. "
                         f"N={len(cross_table)}, {n_harvey_joe} pairs Harvey sig. "
                         f"K1100c coincidence hypothesis not supported.")

    print(f"\n{'=' * 72}")
    print(f"SCENARIO: {scenario}")
    print(f"  {scenario_desc}")
    print(f"{'=' * 72}")

    # ---- Paper 3 decision ----
    paper3_decision = "pending"
    if h1_confirmed and n_harvey_joe >= 3:
        paper3_decision = "SUPPORT: Publish asset-class-specific copula claim"
    elif h1_p10 and n_harvey_joe >= 2:
        paper3_decision = "PARTIAL: Limited claim for cross-class pairs only"
    elif n_harvey_joe == 0:
        paper3_decision = "AGAINST: K1100c may be coincidence"
    else:
        paper3_decision = "INCONCLUSIVE: More evidence needed"

    print(f"  Paper 3 pivot decision: {paper3_decision}")

    # ---- Generate plots ----
    print("\nGenerating plots ...")
    try:
        make_plots(pair_results, cross_table, spearman_results)
    except Exception as e:
        print(f"  Plot error: {e}")
        import traceback
        traceback.print_exc()

    # ---- Final results ----
    results_final = {
        'experiment_id': EXPERIMENT_ID,
        'pair_results': {pn: to_json_safe(pr) for pn, pr in pair_results.items()},
        'cross_pair_table': cross_table,
        'spearman_results': spearman_results,
        'scenario': scenario,
        'scenario_description': scenario_desc,
        'paper3_decision': paper3_decision,
        'core_answers': {
            'n_pairs_done': int(len(cross_table)),
            'n_harvey_joe': int(n_harvey_joe),
            'n_harvey_skt': int(n_harvey_skt),
            'harvey_pass_by_class': {
                ac: {'total': by_class[ac]['total'],
                     'pass': by_class[ac]['pass']}
                for ac in by_class
            },
            'h1_confirmed_p05': bool(h1_confirmed),
            'h1_confirmed_p10': bool(h1_p10),
            'spearman_rho_joe': float(sp_joe.get('spearman_rho', np.nan)),
            'spearman_p1_joe':  float(sp_joe.get('p_one_sided_neg', np.nan)),
        },
        'config': {
            'oos_start': OOS_START, 'window': WINDOW,
            'refit_every': REFIT_EVERY, 'alpha_levels': ALPHA_LEVELS,
            'weights': WEIGHTS.tolist(), 'mc_paths': MC_PATHS, 'seed': 42,
        },
        'metadata': {
            'experiment_id': EXPERIMENT_ID,
            'parent_experiments': ['K1100c', 'K1100b', 'K1100', 'K1041', 'K1092'],
            'data_source': 'yfinance daily',
            'data_period': f"{DATA_START} to {DATA_END}",
            'oos_start': OOS_START,
            'pairs_attempted': [p[0] for p in PAIRS],
            'pairs_done': pairs_done,
            'models': MODELS,
            'proposer': 'User (Lai Yi-Hao) via K1100c follow-up',
            'runtime_seconds': float(time.time() - START_TIME),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'references': [
                'Joe (1997). Multivariate Models and Dependence Concepts. Chapman&Hall.',
                'Hansen (1994). Autoregressive Conditional Density. IER 35(3).',
                'Harvey (1997). Testing DM: A Note. JBES 15(4).',
                'Patton (2006). Modelling asymmetric exchange rate dependence. IER 47(2).',
                'K1100c (2026-04-17): MIXED scenario, Joe sig for cross-class.',
                'K1100b (2026-04-13): symmetric copula 5/5 NULL.',
            ],
        },
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_final, f, indent=2)
    print(f"\nFinal results saved: {RESULTS_PATH}")
    print(f"Total runtime: {time.time()-START_TIME:.0f}s")

    log_file.flush()
    return results_final


if __name__ == '__main__':
    main()
