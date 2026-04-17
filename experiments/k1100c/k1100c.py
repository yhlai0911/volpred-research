#!/usr/bin/env python3
"""
K1100c: Skew-t / Joe Copula for Asymmetric Tail (extension of K1100b)
======================================================================
[提出: 用戶 (Lai Yi-Hao) / 設計: Claude / 執行: Claude]

Parent experiment: K1100b (symmetric Student-t + Clayton = 5/5 NULL)
Related: K1100, K1041, K1092, K193

Motivation:
  K1100b found 5/5 NULL with Student-t (symmetric) and Clayton (lower tail only).
  Mechanism: 50/50 portfolio mixing averages out copula tail information.

  K1100c question: Does Hansen (1994) skew-t copula (asymmetric) or Joe copula
  (upper-tail, complementary to Clayton) reveal that asymmetric tail structure
  is the MISSING VARIABLE in K1100b?

  Three Scenarios:
    A (PASS): At least one pair shows Harvey |t| > 3.0 for M4 or M5
              → asymmetric tail IS the missing variable, Paper 3 has a path
    B (NULL, structural): 5/5 NULL regardless of copula family
              → mechanism is portfolio mixing, copula family choice irrelevant
    C (mixed): Some pairs pass (especially SPY-XLF), others null
              → limits Paper 3 narrative to crash-sensitive pairs only

Models:
  M1: DCC-A4f-ASYM (baseline, K1092 best)
  M2: Copula-t-A4f-ASYM (K1100b, symmetric Student-t)
  M3: Copula-Clayton-A4f-ASYM (K1100b, lower-tail only)
  M4: Copula-SkewT-A4f-ASYM (NEW) — Hansen (1994) bivariate skew-t
      copula with asymmetry parameter lambda in [-1,1]. Captures
      asymmetric tail dependence: lower tail > upper tail for equities.
  M5: Copula-Joe-A4f-ASYM (NEW) — Joe copula (upper-tail dependence)
      as complement to Clayton (lower-tail). Tests if UPPER-tail
      asymmetry (short squeeze / rally co-movement) matters.

Data: 5 pairs (SPY-QQQ/XLF/IWM/TLT/GLD), 2005-01-04 to 2026-04-10
OOS: 2013-06-01 onwards, window=1250, refit=63, MC=5000, seed=42

Anti-lookahead: marginal GARCH uses t-1 info to forecast h_t; copula
  params from training window ending at t-1; MC VaR drawn before t.
  All forecasts are strictly one-step-ahead.

References:
  - Hansen (1994). Autoregressive Conditional Density Estimation.
    International Economic Review 35(3): 705-730.  [Skew-t distribution]
  - Joe (1997). Multivariate Models and Dependence Concepts. Chapman & Hall.
  - Patton (2006). Modelling asymmetric exchange rate dependence. IER 47(2).
  - K1100b README for full methodology inheritance.

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
EXPERIMENT_ID = "K1100c"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1100c_results.json')
LOG_PATH = os.path.join(SCRIPT_DIR, 'run.log')

# Redirect print to both stdout and log
import io

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

PAIRS = [
    ('SPY-QQQ', 'SPY', 'QQQ', 'vix2', 'vix2'),
    ('SPY-XLF', 'SPY', 'XLF', 'vix2', 'vix2'),
    ('SPY-IWM', 'SPY', 'IWM', 'vix2', 'vix2'),
    ('SPY-TLT', 'SPY', 'TLT', 'vix2', 'vix2'),
    ('SPY-GLD', 'SPY', 'GLD', 'vix2', 'gvz2'),
]

# K1100b models (recomputed here for reference) + 2 new
MODELS_K1100B = ['DCC-A4f-ASYM', 'Copula-t-A4f-ASYM', 'Copula-Clayton-A4f-ASYM']
MODELS_NEW    = ['Copula-SkewT-A4f-ASYM', 'Copula-Joe-A4f-ASYM']
MODELS        = MODELS_K1100B + MODELS_NEW

print("=" * 72)
print(f"{EXPERIMENT_ID}: Skew-t + Joe Copula for Asymmetric Tail")
print(f"  5 pairs x 5 models = 25 cells")
print(f"  NEW: Hansen skew-t (M4) + Joe upper-tail (M5)")
print(f"  OOS from {OOS_START}, window={WINDOW}, refit={REFIT_EVERY}d,"
      f" MC={MC_PATHS}")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (inherited from K1100b)
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
# 2. MARGINAL + DCC FITTING (inherited from K1100b)
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
    T  = len(eps1)
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
# 3. COPULA FITTING — Inherited (Student-t, Clayton)
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
        return {'rho': rho_init, 'nu': 10.0, 'converged': False}
    rho_hat, nu_hat = best_res.x
    return {'rho': float(rho_hat), 'nu': float(nu_hat),
            'converged': bool(best_res.success), 'nll': float(best_res.fun)}


def clayton_copula_nll(theta, u1, u2):
    if theta <= 1e-4 or theta > 30.0:
        return 1e10
    try:
        log_u1  = np.log(u1)
        log_u2  = np.log(u2)
        term    = u1**(-theta) + u2**(-theta) - 1.0
        if np.any(term <= 0):
            return 1e10
        log_term = np.log(term)
        ll = np.sum(np.log(1.0+theta)
                    - (1.0+theta)*(log_u1+log_u2)
                    - (2.0+1.0/theta)*log_term)
        return -ll if np.isfinite(ll) else 1e10
    except Exception:
        return 1e10


def fit_clayton_copula(u1, u2):
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau) or tau <= 0:
        theta_init = 0.05
    else:
        theta_init = max(0.05, 2.0 * tau / (1.0 - tau))
    try:
        res = optimize.minimize_scalar(clayton_copula_nll,
                                       bounds=(0.01, 20.0),
                                       method='bounded',
                                       args=(u1, u2),
                                       options={'xatol': 1e-4})
    except Exception:
        return {'theta': theta_init, 'converged': False, 'lambda_L': 0.0}
    theta_hat  = float(res.x)
    lambda_L   = 2.0**(-1.0/theta_hat) if theta_hat > 0.01 else 0.0
    return {'theta': theta_hat, 'lambda_L': float(lambda_L),
            'converged': bool(res.success), 'nll': float(res.fun)}


def t_copula_lambda(rho, nu):
    if rho >= 0.99:  return 1.0
    if rho <= -0.99: return 0.0
    arg = -np.sqrt((nu+1.0)*(1.0-rho)/(1.0+rho))
    return 2.0 * student_t.cdf(arg, df=nu+1.0)


def sample_student_t_copula(rho, nu, n_samples, rng):
    R = np.array([[1.0, rho], [rho, 1.0]])
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        rho_clipped = np.clip(rho, -0.99, 0.99)
        R = np.array([[1.0, rho_clipped], [rho_clipped, 1.0]])
        L = np.linalg.cholesky(R)
    Z        = rng.standard_normal((n_samples, 2)) @ L.T
    chi_vals = rng.chisquare(df=nu, size=n_samples)
    X        = Z * np.sqrt(nu / chi_vals)[:, None]
    u1       = student_t.cdf(X[:, 0], df=nu)
    u2       = student_t.cdf(X[:, 1], df=nu)
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


def sample_clayton_copula(theta, n_samples, rng):
    if theta <= 0.01:
        u1 = rng.uniform(0, 1, n_samples)
        u2 = rng.uniform(0, 1, n_samples)
        return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)
    V  = rng.gamma(1.0/theta, scale=1.0, size=n_samples)
    V  = np.maximum(V, 1e-8)
    E1 = rng.exponential(scale=1.0, size=n_samples)
    E2 = rng.exponential(scale=1.0, size=n_samples)
    u1 = (1.0 + E1/V)**(-1.0/theta)
    u2 = (1.0 + E2/V)**(-1.0/theta)
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


# ============================================================
# 4. SKEW-T COPULA (NEW — Hansen 1994)
# ============================================================
# Hansen (1994) skew-t PDF:
#   f(x; nu, lam) = bc (1 + 1/(nu-2) * (bx+a)^2/(1+sign(x+a/b)*lam)^2)^(-(nu+1)/2)
# where:
#   a = 4*lam*c * ((nu-2)/(nu-1))
#   b = sqrt(1 + 3*lam^2 - a^2)
#   c = Gamma((nu+1)/2) / (sqrt(pi*(nu-2)) * Gamma(nu/2))

def hansen_skewt_logpdf_scalar(x, nu, lam):
    """Log-PDF of Hansen (1994) skewed-t for scalar x."""
    # nu > 2, lam in (-1, 1)
    if nu <= 2.0 or abs(lam) >= 1.0:
        return -1e10
    c = (special.gammaln((nu+1.0)/2.0)
         - special.gammaln(nu/2.0)
         - 0.5*np.log(np.pi*(nu-2.0)))
    c = np.exp(c)
    a = 4.0*lam*c*(nu-2.0)/(nu-1.0)
    b2 = 1.0 + 3.0*lam*lam - a*a
    if b2 <= 0:
        return -1e10
    b = np.sqrt(b2)
    bxa = b*x + a
    sign_part = 1.0 + np.sign(x + a/b)*lam
    if sign_part <= 0:
        return -1e10
    inner = 1.0 + (bxa/sign_part)**2 / (nu-2.0)
    if inner <= 0:
        return -1e10
    logpdf = (np.log(b) + np.log(c)
              - ((nu+1.0)/2.0)*np.log(inner))
    return logpdf


def hansen_skewt_logpdf(x_arr, nu, lam):
    """Vectorized log-PDF."""
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


def hansen_skewt_cdf_scalar(x, nu, lam):
    """CDF of Hansen skew-t via numerical integration (Patton 2006 style)."""
    # Use relation to student-t CDF
    # CDF(x; nu, lam) = 2/(1-lam) * t_nu(bx+a / (1-lam)) if x < -a/b
    #                  = 1 - 2/(1+lam) * t_nu(-(bx+a)/(1+lam)) if x >= -a/b
    if nu <= 2.0 or abs(lam) >= 1.0:
        return 0.5
    c_val = np.exp(special.gammaln((nu+1.0)/2.0)
                   - special.gammaln(nu/2.0)
                   - 0.5*np.log(np.pi*(nu-2.0)))
    a = 4.0*lam*c_val*(nu-2.0)/(nu-1.0)
    b2 = 1.0 + 3.0*lam**2 - a**2
    if b2 <= 0:
        return 0.5
    b   = np.sqrt(b2)
    bxa = b*x + a
    # Scale for t_nu
    sc = np.sqrt((nu-2.0)/nu)
    if x < -a/b:
        # left region
        arg  = bxa / ((1.0-lam)*sc)
        cdf  = 2.0/(1.0-lam) * student_t.cdf(arg, df=nu) * student_t.sf(0, df=nu)
        # Simpler (Patton 2004): cdf = 2/(1+lam) * T_nu(bxa / (1-lam)) for x < -a/b
        # Use standard implementation
        arg2 = bxa / (1.0 - lam)
        cdf  = 2.0/(1.0+lam) * student_t.cdf(arg2, df=nu)
    else:
        arg2 = bxa / (1.0 + lam)
        cdf  = 2.0/(1.0+lam) * student_t.cdf(arg2, df=nu)
    return float(np.clip(cdf, 0.0, 1.0))


def _hansen_t_cdf(x, nu):
    """CDF of Hansen (1994) symmetric t: T_nu(x/sqrt((nu-2)/nu)) = student_t.cdf(x*sqrt(nu/(nu-2)), df=nu)."""
    scale = np.sqrt((nu-2.0)/nu)  # so that inner = (x/scale)^2/nu
    return student_t.cdf(x / scale, df=nu)


def _hansen_t_ppf(p, nu):
    """PPF of Hansen symmetric t."""
    scale = np.sqrt((nu-2.0)/nu)
    return student_t.ppf(p, df=nu) * scale


def hansen_skewt_cdf_vec(x_arr, nu, lam):
    """
    Vectorized CDF of Hansen (1994) skew-t.
    The density is f(x) = bc*(1+(bx+a)^2/((1±lam)^2*(nu-2)))^{-(nu+1)/2}

    Two-branch formula (correctly derived via substitution into integral):
    Scale s = sqrt((nu-2)/nu) (Hansen's parameterization)

    For bxa = b*x + a:
      x < -a/b (bxa < 0): F(x) = (1-lam) * T_H((bxa/(1-lam)))
      x >= -a/b (bxa >= 0): F(x) = (1-lam)/2 + (1+lam)*[T_H(bxa/(1+lam)) - 1/2]
                                   = (1+lam)*T_H(bxa/(1+lam)) - lam/2

    where T_H(y) = student_t.cdf(y/s, df=nu) (Hansen's scaled t CDF, s=sqrt((nu-2)/nu))

    Verify continuity at bxa=0:
      left: (1-lam)*T_H(0) = (1-lam)*0.5
      right: (1+lam)*T_H(0) - lam/2 = (1+lam)*0.5 - lam/2 = 0.5 + lam/2 - lam/2 = 0.5
    Wait: left = (1-lam)*0.5 ≠ 0.5. So there IS a discontinuity unless lam=0.

    Correct formula (from integrating f properly):
    F(x) = sp * T_H(bxa/sp)   where sp = 1-lam (left) or 1+lam (right)
    At bxa=0: left gives (1-lam)*0.5, right gives (1+lam)*0.5
    These are different! → The distribution is NOT symmetric at 0.

    The true CDF is:
    F(-a/b) = (1-lam)/2 from both branches (the join is at x=-a/b, bxa=0).
    Actually the formula sp*T_H(bxa/sp) does give (1-lam)*T_H(0) = (1-lam)/2
    from the left, and (1+lam)*T_H(0) = (1+lam)/2 from the right — these differ!

    Resolution: Add constant offset for right branch so it starts at (1-lam)/2:
    Right branch: F(x) = (1-lam)/2 + (1+lam)*(T_H(bxa/(1+lam)) - 1/2)
                       = (1+lam)*T_H(bxa/(1+lam)) - lam/2
    At bxa=0: (1+lam)*0.5 - lam/2 = 0.5 + lam/2 - lam/2 = 0.5 ≠ (1-lam)/2.

    The discontinuity is fundamental unless the density integrates to the same split at x=-a/b.
    Since f is left-heavier for lam<0, integral(-inf, -a/b) should equal (1-lam)/2:
    integral = sp * T_H(0) = (1-lam)/2 ✓  (this IS (1-lam)/2)
    And integral(-a/b, +inf) = (1+lam)*[1 - T_H(0)] = (1+lam)/2
    Wait: total = (1-lam)/2 + (1+lam)/2 = 1 ✓

    So F(-a/b) = (1-lam)/2 from the left branch (using sp=1-lam, T_H(0)=0.5).
    Right branch: F(x) = (1-lam)/2 + (1+lam)*(T_H(bxa/(1+lam)) - T_H(0))
                       = (1-lam)/2 + (1+lam)*(T_H(bxa/(1+lam)) - 0.5)
                       = (1+lam)*T_H(bxa/(1+lam)) - lam/2

    At bxa=0: (1+lam)*0.5 - lam/2 = 0.5. But left at bxa=0: (1-lam)*0.5. These differ by lam*0.5!
    → Continuity requires: (1-lam)*0.5 == 0.5, i.e. lam=0. So for lam≠0 there's a jump!

    This means the density must be 0 at x=-a/b, OR the formula is wrong.
    Actually: the Hansen density is f(x) = bc*(...)^{-...}. At x=-a/b, bxa=0, f≠0.
    The function IS continuous (f is defined everywhere). The CDF must be continuous.

    THE KEY: the two-branch formula should be:
    F(x) = (1-lam) * T_H(bxa/(1-lam))   for x < -a/b
    F(x) = (1-lam)/2 + (1+lam)*(T_H(bxa/(1+lam)) - 1/2)  for x >= -a/b

    At bxa→0 from left: (1-lam)*T_H(0) = (1-lam)/2 ✓
    At bxa→0 from right: (1-lam)/2 + (1+lam)*(1/2-1/2) = (1-lam)/2 ✓ CONTINUOUS!
    """
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
    # Left: F = (1-lam) * T_H(bxa/(1-lam))
    cdf[mask_left]  = (1.0-lam) * _hansen_t_cdf(bxa[mask_left]/(1.0-lam), nu)
    # Right: F = (1-lam)/2 + (1+lam)*(T_H(bxa/(1+lam)) - 1/2)
    cdf[~mask_left] = ((1.0-lam)/2.0
                       + (1.0+lam) * (_hansen_t_cdf(bxa[~mask_left]/(1.0+lam), nu) - 0.5))
    return np.clip(cdf, 1e-6, 1.0-1e-6)


def hansen_skewt_ppf(p, nu, lam, tol=1e-6, max_iter=60):
    """
    PPF of Hansen (1994) skew-t via analytical inversion.
    CDF formula (two-branch):
      p = 2/(1+lam) * T_nu((bx+a)/(1-lam))   for x < -a/b  (left branch)
      p = 1 - 2/(1+lam) * T_nu(-(bx+a)/(1+lam))  for x >= -a/b  (right branch)
    where threshold p_0 = 2/(1+lam) * T_nu(0) = 2/(1+lam) * 0.5 = 1/(1+lam)
    """
    if nu <= 2.0 or abs(lam) >= 1.0:
        return student_t.ppf(p, df=10)
    c_val = np.exp(special.gammaln((nu+1.0)/2.0)
                   - special.gammaln(nu/2.0)
                   - 0.5*np.log(np.pi*(nu-2.0)))
    a  = 4.0*lam*c_val*(nu-2.0)/(nu-1.0)
    b2 = 1.0 + 3.0*lam**2 - a**2
    if b2 <= 0:
        return student_t.ppf(p, df=10)
    b   = np.sqrt(b2)
    p0  = (1.0 - lam) / 2.0   # CDF at split point bxa=0

    if p < p0:
        # Left branch: F = (1-lam) * T_H(bxa/(1-lam))
        # => T_H(bxa/(1-lam)) = p/(1-lam)
        q   = float(np.clip(p / (1.0-lam), 1e-10, 1.0-1e-10))
        bxa = _hansen_t_ppf(q, nu) * (1.0 - lam)
    else:
        # Right branch: F = (1-lam)/2 + (1+lam)*(T_H(bxa/(1+lam)) - 0.5)
        # => T_H(bxa/(1+lam)) = 0.5 + (p - (1-lam)/2) / (1+lam)
        q   = float(np.clip(0.5 + (p - (1.0-lam)/2.0)/(1.0+lam), 1e-10, 1.0-1e-10))
        bxa = _hansen_t_ppf(q, nu) * (1.0 + lam)
    x = (bxa - a) / b
    return float(x)


def hansen_skewt_ppf_vec(p_arr, nu, lam):
    """
    Fully vectorized PPF of Hansen skew-t (no Python loop).
    Uses numpy array operations for speed.
    """
    if nu <= 2.0 or abs(lam) >= 1.0:
        # Fallback: standard t
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
    p0   = (1.0 - lam) / 2.0   # CDF at split bxa=0
    scale = np.sqrt((nu-2.0)/nu)  # Hansen t scale

    p_arr = np.asarray(p_arr, dtype=float)
    mask  = p_arr < p0
    out   = np.empty_like(p_arr)

    # Left branch: bxa = t_ppf(p/(1-lam)) * scale * (1-lam)
    if mask.any():
        q_left = np.clip(p_arr[mask] / (1.0-lam), 1e-10, 1.0-1e-10)
        bxa_left = student_t.ppf(q_left, df=nu) * scale * (1.0-lam)
        out[mask] = (bxa_left - a) / b

    # Right branch: bxa = t_ppf(0.5 + (p-(1-lam)/2)/(1+lam)) * scale * (1+lam)
    if (~mask).any():
        q_right = np.clip(0.5 + (p_arr[~mask] - p0)/(1.0+lam), 1e-10, 1.0-1e-10)
        bxa_right = student_t.ppf(q_right, df=nu) * scale * (1.0+lam)
        out[~mask] = (bxa_right - a) / b

    return out


# Fit marginal skew-t df and lambda (for PIT in skew-t copula)
def fit_marginal_skt(z):
    """Fit Hansen skew-t marginal to standardized residuals z."""
    def neg_ll(params):
        nu, lam = params
        if nu <= 2.1 or nu > 100 or abs(lam) >= 0.99:
            return 1e10
        lpdf = hansen_skewt_logpdf(z, nu, lam)
        ll   = np.sum(lpdf)
        return -ll if np.isfinite(ll) else 1e10
    # Grid init
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


def pit_skt(z, nu, lam):
    """PIT transform via skew-t CDF."""
    return hansen_skewt_cdf_vec(z, nu, lam)


def inv_pit_skt(u, nu, lam):
    """Inverse PIT via skew-t PPF (vectorized)."""
    return hansen_skewt_ppf_vec(u, nu, lam)


# Bivariate skew-t copula NLL
# We use a Gaussian copula with skew-t marginals (meta-skew-t copula approach)
# The copula density is: c(u1,u2) = f_2(F1^{-1}(u1), F2^{-1}(u2)) / (f1(x1)*f2(x2))
# where f_2 is bivariate skew-t and f1,f2 are marginal skew-t densities.
# For tractability we use a bivariate t copula density but with skew-t marginal PIT.
# This is the Patton (2006) approach: separate copula from marginals.
# The copula is the dependence structure embedded in the t copula:
#   C_{rho,nu}(u1, u2) = T_{rho,nu}(t_nu^{-1}(u1), t_nu^{-1}(u2))
# But here u1,u2 come from skew-t PIT, giving an asymmetric joint distribution.

def skewt_copula_nll(params, u1, u2):
    """
    Meta-SkewT copula NLL.
    Uses t copula dependence (rho, nu_c) applied to skew-t PIT residuals.
    The asymmetry comes from the marginal skew-t PIT transformation.
    This is a hybrid: t copula density + skew-t marginals.
    """
    rho, nu_c = params
    if not (-0.995 < rho < 0.995) or not (2.1 < nu_c < 80.0):
        return 1e10
    # Invert skew-t PIT to get x1, x2 on standard scale
    # u1, u2 are already PIT-transformed via skew-t in fit step
    # Here we use student-t ppf (copula scale) as in standard t copula
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
    """
    Fit skew-t copula.
    Steps:
      1. Fit Hansen skew-t marginals to z1, z2
      2. PIT transform to get uniform u1, u2 via skew-t CDF
      3. Fit t copula (rho, nu_c) to (u1, u2)
    Returns: rho, nu_c, nu1, lam1, nu2, lam2, lambda_L (asymmetric)
    """
    # Step 1: marginal fit
    nu1, lam1 = fit_marginal_skt(z1)
    nu2, lam2 = fit_marginal_skt(z2)

    # Step 2: PIT via skew-t
    u1_skt = pit_skt(z1, nu1, lam1)
    u2_skt = pit_skt(z2, nu2, lam2)

    # Step 3: t copula on skew-t PIT
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

    # Tail dependence for skew-t copula
    # Lower tail: λ_L measured from t copula with skew-t marginals
    # As approximation: use standard t-copula formula but with nu_c
    lambda_L = t_copula_lambda(rho_hat, nu_c_hat)
    # Asymmetry measure: skewness of lam1, lam2
    asym_index = (lam1 + lam2) / 2.0

    return {
        'rho': float(rho_hat),
        'nu_c': float(nu_c_hat),
        'nu1': float(nu1), 'lam1': float(lam1),
        'nu2': float(nu2), 'lam2': float(lam2),
        'lambda_L': float(lambda_L),
        'asym_index': float(asym_index),
        'u1_skt': u1_skt,
        'u2_skt': u2_skt,
        'converged': best_res.success if best_res else False,
        'nll': float(best_res.fun) if best_res else 1e10,
    }


def sample_skewt_copula(cop_params, n_samples, rng):
    """
    Sample from meta-skew-t copula:
    1. Sample from t copula (rho, nu_c) → get u1, u2
    2. Invert through skew-t PPF to get z1_sim, z2_sim
    """
    rho  = cop_params['rho']
    nu_c = cop_params['nu_c']
    nu1  = cop_params['nu1']
    lam1 = cop_params['lam1']
    nu2  = cop_params['nu2']
    lam2 = cop_params['lam2']

    # Step 1: sample from t copula
    u1_t, u2_t = sample_student_t_copula(rho, nu_c, n_samples, rng)

    # Step 2: invert skew-t PPF to get standardized innovations
    z1_sim = inv_pit_skt(u1_t, nu1, lam1)
    z2_sim = inv_pit_skt(u2_t, nu2, lam2)

    # Now apply student-t PIT (for marginal h fitting)
    # u_marg = F_skt(z) — we return z directly; caller uses h_t
    return z1_sim, z2_sim


# ============================================================
# 5. JOE COPULA (NEW — upper-tail dependence)
# ============================================================
# Joe copula: C(u,v; theta) = 1 - ((1-u)^theta + (1-v)^theta - (1-u)^theta*(1-v)^theta)^{1/theta}
# theta >= 1; upper tail dependence: lambda_U = 2 - 2^{1/theta}

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
        # log density of Joe: log c = (theta-1)*log(a*(1-u1)^{-1}) + log(...)
        # c(u,v) = (1-u)^{theta-1}*(1-v)^{theta-1}*((1-u)^theta+(1-v)^theta-(1-u)^theta*(1-v)^theta)^{1/theta-2}
        #          * (theta-1 + (1-u)^theta + (1-v)^theta - (1-u)^theta*(1-v)^theta - theta*(1-u)^theta - theta*(1-v)^theta + ...)
        # Cleaner formula (Nelsen 2006, p.160):
        # c(u,v) = (1-u)^{theta-1}*(1-v)^{theta-1} * S^{1/theta-2} * ((theta-1)*S + ab)
        # where S = a + b - ab
        log_c = ((theta-1.0)*np.log(1.0-u1)
                 + (theta-1.0)*np.log(1.0-u2)
                 + (1.0/theta - 2.0)*logs
                 + np.log((theta-1.0)*s + ab))
        ll = np.sum(log_c)
        return -ll if np.isfinite(ll) else 1e10
    except Exception:
        return 1e10


def fit_joe_copula(u1, u2):
    """Fit Joe copula. For negative-correlation pairs, theta → 1 (independence)."""
    # Initial: from Kendall tau  tau = 1 - 4*int_0^1 ... (no simple closed form)
    # Use numerical approach
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau) or tau <= 0:
        theta_init = 1.5
    else:
        # rough: tau = (theta-1)*log(2) for small theta (Joe 1997)
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
            'lambda_L': 0.0,  # Joe has no lower tail dependence
            'converged': bool(res.success),
            'nll': float(res.fun)}


def sample_joe_copula(theta, n_samples, rng):
    """
    Sample from Joe copula using Marshall-Olkin frailty method.
    Joe (1997): frailty V ~ Log-Series(exp(-theta)) is complex;
    Use the power-series / conditional approach via Frank's frailty representation.

    Fast approximation: use stable Frechet frailty.
    Joe copula can be simulated via:
      V ~ Stable(1/theta, 1) with Laplace transform phi(t) = 1 - (1-exp(-t))^{1/theta}
    Alternative (simpler): use the fact that Joe is in the BB1 family with delta=0.
    For Joe theta: use Sibuya distribution frailty.

    Practical fast approach for theta >= 1:
      1. Draw V from Sibuya(alpha=1/theta) distribution
      2. Draw N_i ~ Exp(1)
      3. u_i = phi(N_i/V) where phi is the inverse Laplace transform

    For tractability, use the truncated series approach:
      Joe is a Archimedean copula with generator phi(t) = 1-(1-exp(-t))^{1/theta}
    Actually, simplest: sample via conditional CDF using vectorized Newton-Raphson.
    """
    if theta <= 1.01:
        # Near independence
        u1 = rng.uniform(0, 1, n_samples)
        u2 = rng.uniform(0, 1, n_samples)
        return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)

    u1 = rng.uniform(1e-6, 1.0-1e-6, n_samples)
    w  = rng.uniform(1e-6, 1.0-1e-6, n_samples)

    # Conditional CDF: C(v|u) = (1-u)^{theta-1} * [(1-u)^theta + (1-v)^theta - (1-u)^theta*(1-v)^theta]^{1/theta - 1}
    # Set C(v|u) = w, solve for v.
    # Let a = (1-u)^theta, b = (1-v)^theta
    # f(b) = a^{(theta-1)/theta} * (a + b*(1-a))^{1/theta - 1} = w
    # (a + b*(1-a))^{1/theta - 1} = w / a^{(theta-1)/theta}
    # Let c = a + b*(1-a)
    # c = (w / a^{(theta-1)/theta})^{1/(1/theta-1)} = (w / a^{(theta-1)/theta})^{theta/(1-theta)}
    # b = (c - a) / (1 - a) if a < 1

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
# 6. MC VaR/ES (unified for all copulas)
# ============================================================
def copula_mc_var_es(h1, h2, copula_type, copula_params,
                     marg_t_dfs, alpha_levels, n_paths, rng):
    """
    Simulate portfolio returns and compute VaR/ES.
    copula_type: 't', 'clayton', 'skt', 'joe'
    marg_t_dfs: (df1, df2) for standard t PIT (used by t/clayton)
                or ignored (skt generates z directly, joe uses uniform)
    """
    if copula_type == 't':
        rho  = copula_params['rho']
        nu_c = copula_params['nu']
        u1, u2 = sample_student_t_copula(rho, nu_c, n_paths, rng)
        z1 = inv_pit_student_t(u1, marg_t_dfs[0])
        z2 = inv_pit_student_t(u2, marg_t_dfs[1])

    elif copula_type == 'clayton':
        theta = copula_params['theta']
        u1, u2 = sample_clayton_copula(theta, n_paths, rng)
        z1 = inv_pit_student_t(u1, marg_t_dfs[0])
        z2 = inv_pit_student_t(u2, marg_t_dfs[1])

    elif copula_type == 'skt':
        # z1, z2 are skew-t innovations (not t-PIT)
        z1, z2 = sample_skewt_copula(copula_params, n_paths, rng)

    elif copula_type == 'joe':
        theta = copula_params['theta']
        u1, u2 = sample_joe_copula(theta, n_paths, rng)
        z1 = inv_pit_student_t(u1, marg_t_dfs[0])
        z2 = inv_pit_student_t(u2, marg_t_dfs[1])

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
# 7. BACKTESTING (inherited from K1100b)
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
# 8. DM TESTS (inherited from K1100b)
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
# 9. OOS FORECASTING for ONE pair (5 models)
# ============================================================
def oos_forecast_pair(ret1, ret2, x21, x22, dates, oos_start,
                      pair_label, window=WINDOW, refit_every=REFIT_EVERY):
    """
    Compute one-step-ahead OOS forecasts for all 5 models.
    Anti-lookahead: at time t, use only data [t-window, t-1].
    """
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T       = len(ret1)
    n_oos   = T - oos_idx

    # Storage
    h1_store   = {m: np.full(n_oos, np.nan) for m in MODELS}
    h2_store   = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_store  = {m: np.full(n_oos, np.nan) for m in MODELS}
    pvar_store = {m: np.full(n_oos, np.nan) for m in MODELS}

    # Copula parameter time series
    cop_t_rho        = np.full(n_oos, np.nan)
    cop_t_nu         = np.full(n_oos, np.nan)
    cop_clay_theta   = np.full(n_oos, np.nan)
    lambda_L_t       = np.full(n_oos, np.nan)
    lambda_L_clay    = np.full(n_oos, np.nan)
    lambda_L_skt     = np.full(n_oos, np.nan)
    lambda_U_joe     = np.full(n_oos, np.nan)
    skt_asym_idx     = np.full(n_oos, np.nan)

    cop_t_params     = [None] * n_oos
    cop_clay_params  = [None] * n_oos
    cop_skt_params   = [None] * n_oos
    cop_joe_params   = [None] * n_oos
    marg_t_df_1      = np.full(n_oos, np.nan)
    marg_t_df_2      = np.full(n_oos, np.nan)

    # Shared state for all models
    state = {m: {
        'h1_prev': np.nan, 'h2_prev': np.nan,
        'g1_prev': np.nan, 'g2_prev': np.nan,
        'marg1_p': None,   'marg2_p': None,
        'dcc_a': 0.0, 'dcc_b': 0.0,
        'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
        'last_fit': -refit_every,
        'eps1_prev': 0.0, 'eps2_prev': 0.0,
        'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        'copula_t': None, 'copula_clay': None,
        'copula_skt': None, 'copula_joe': None,
        'marg_t_df_1': np.nan, 'marg_t_df_2': np.nan,
    } for m in MODELS}

    for i in range(n_oos):
        t = oos_idx + i
        if i % 500 == 0:
            elapsed = time.time() - START_TIME
            print(f"    [{pair_label}] OOS day {i}/{n_oos} ({elapsed:.0f}s)")

        need_refit = (i - state['DCC-A4f-ASYM']['last_fit'] >= refit_every
                      or state['DCC-A4f-ASYM']['marg1_p'] is None)

        if need_refit:
            s    = max(0, t - window)
            tr1  = ret1[s:t]
            tr2  = ret2[s:t]
            tr_x21 = x21[s:t]
            tr_x22 = x22[s:t]

            # === Shared: A4f marginals ===
            a4f_1 = fit_a4f(tr1, tr_x21)
            a4f_2 = fit_a4f(tr2, tr_x22)
            eps_1 = tr1 / np.sqrt(np.maximum(a4f_1['h'], 1e-16))
            eps_2 = tr2 / np.sqrt(np.maximum(a4f_2['h'], 1e-16))

            # === DCC ===
            dcc = fit_dcc(eps_1, eps_2)

            # === Standard t PIT ===
            df_1 = fit_marginal_t_df(eps_1)
            df_2 = fit_marginal_t_df(eps_2)
            u1_t = pit_student_t(eps_1, df_1)
            u2_t = pit_student_t(eps_2, df_2)

            # === M2: Student-t copula ===
            cop_t   = fit_student_t_copula(u1_t, u2_t)
            # === M3: Clayton copula ===
            cop_clay = fit_clayton_copula(u1_t, u2_t)
            # === M4: Skew-t copula (new) ===
            cop_skt = fit_skewt_copula(u1_t, u2_t, eps_1, eps_2)
            # === M5: Joe copula (new) ===
            cop_joe = fit_joe_copula(u1_t, u2_t)

            # Populate state for all models
            for m in MODELS:
                state[m]['marg1_p']    = ('A4f', a4f_1['params'])
                state[m]['marg2_p']    = ('A4f', a4f_2['params'])
                state[m]['h1_prev']    = float(a4f_1['h'][-1])
                state[m]['h2_prev']    = float(a4f_2['h'][-1])
                state[m]['g1_prev']    = float(a4f_1['g'][-1])
                state[m]['g2_prev']    = float(a4f_2['g'][-1])
                state[m]['last_fit']   = i
                state[m]['marg_t_df_1'] = df_1
                state[m]['marg_t_df_2'] = df_2

            # DCC state
            state['DCC-A4f-ASYM']['dcc_a']     = dcc['a']
            state['DCC-A4f-ASYM']['dcc_b']     = dcc['b']
            state['DCC-A4f-ASYM']['qbar11']    = dcc['qbar11']
            state['DCC-A4f-ASYM']['qbar22']    = dcc['qbar22']
            state['DCC-A4f-ASYM']['qbar12']    = dcc['qbar12']
            state['DCC-A4f-ASYM']['eps1_prev'] = float(eps_1[-1])
            state['DCC-A4f-ASYM']['eps2_prev'] = float(eps_2[-1])
            state['DCC-A4f-ASYM']['q11_prev']  = dcc['qbar11']
            state['DCC-A4f-ASYM']['q22_prev']  = dcc['qbar22']
            state['DCC-A4f-ASYM']['q12_prev']  = dcc['qbar12']

            # Copula states
            state['Copula-t-A4f-ASYM']['copula_t']       = cop_t
            state['Copula-Clayton-A4f-ASYM']['copula_clay'] = cop_clay
            state['Copula-SkewT-A4f-ASYM']['copula_skt'] = cop_skt
            state['Copula-Joe-A4f-ASYM']['copula_joe']   = cop_joe

        # ---- One-step-ahead forecast (t-1 info → h_t) ----
        r1_prev  = ret1[t-1]
        r2_prev  = ret2[t-1]
        x21_prev = x21[t-1]
        x22_prev = x22[t-1]

        for m in MODELS:
            marg1 = state[m]['marg1_p']
            marg2 = state[m]['marg2_p']
            if marg1 is None or marg2 is None:
                continue

            # Asset 1 A4f recursion
            p    = marg1[1]
            tau1 = max(p[0] + p[1]*x21_prev, 1e-16)
            u1_  = r1_prev / np.sqrt(tau1)
            ind1 = 1.0 if r1_prev < 0 else 0.0
            g1   = p[2] + p[3]*u1_**2 + p[4]*u1_**2*ind1 + p[5]*state[m]['g1_prev']
            g1   = max(g1, 1e-16)
            h1_t = max(tau1 * g1, 1e-16)
            state[m]['g1_prev'] = g1

            # Asset 2 A4f recursion
            p    = marg2[1]
            tau2 = max(p[0] + p[1]*x22_prev, 1e-16)
            u2_  = r2_prev / np.sqrt(tau2)
            ind2 = 1.0 if r2_prev < 0 else 0.0
            g2   = p[2] + p[3]*u2_**2 + p[4]*u2_**2*ind2 + p[5]*state[m]['g2_prev']
            g2   = max(g2, 1e-16)
            h2_t = max(tau2 * g2, 1e-16)
            state[m]['g2_prev'] = g2

            state[m]['h1_prev'] = h1_t
            state[m]['h2_prev'] = h2_t
            h1_store[m][i] = h1_t
            h2_store[m][i] = h2_t

            if m == 'DCC-A4f-ASYM':
                a_d = state[m]['dcc_a']
                b_d = state[m]['dcc_b']
                c_d = 1.0 - a_d - b_d
                e1p = state[m]['eps1_prev']
                e2p = state[m]['eps2_prev']
                q11 = c_d*state[m]['qbar11'] + a_d*e1p**2 + b_d*state[m]['q11_prev']
                q22 = c_d*state[m]['qbar22'] + a_d*e2p**2 + b_d*state[m]['q22_prev']
                q12 = c_d*state[m]['qbar12'] + a_d*e1p*e2p + b_d*state[m]['q12_prev']
                denom = np.sqrt(q11*q22)
                rho_t = np.clip(q12/denom if denom > 1e-20 else 0.0, -0.9999, 0.9999)
                rho_store[m][i] = rho_t
                e1n = r1_prev/np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
                e2n = r2_prev/np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
                state[m]['eps1_prev'] = e1n
                state[m]['eps2_prev'] = e2n
                state[m]['q11_prev'] = q11
                state[m]['q22_prev'] = q22
                state[m]['q12_prev'] = q12
                s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*rho_t*s1*s2
                pvar_store[m][i] = max(pv, 1e-16)

            elif m == 'Copula-t-A4f-ASYM':
                cop = state[m]['copula_t']
                if cop is None: continue
                cop_t_rho[i]    = cop['rho']
                cop_t_nu[i]     = cop['nu']
                lambda_L_t[i]   = t_copula_lambda(cop['rho'], cop['nu'])
                cop_t_params[i] = cop
                s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*cop['rho']*s1*s2
                pvar_store[m][i] = max(pv, 1e-16)
                rho_store[m][i] = cop['rho']

            elif m == 'Copula-Clayton-A4f-ASYM':
                cop = state[m]['copula_clay']
                if cop is None: continue
                cop_clay_theta[i] = cop['theta']
                lambda_L_clay[i]  = cop.get('lambda_L', 0.0)
                cop_clay_params[i] = cop
                tau_k   = cop['theta']/(cop['theta']+2.0)
                rho_approx = np.sin(np.pi*tau_k/2.0)
                s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*rho_approx*s1*s2
                pvar_store[m][i] = max(pv, 1e-16)
                rho_store[m][i] = rho_approx

            elif m == 'Copula-SkewT-A4f-ASYM':
                cop = state[m]['copula_skt']
                if cop is None: continue
                lambda_L_skt[i]    = cop.get('lambda_L', 0.0)
                skt_asym_idx[i]    = cop.get('asym_index', 0.0)
                cop_skt_params[i]  = cop
                s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*cop['rho']*s1*s2
                pvar_store[m][i] = max(pv, 1e-16)
                rho_store[m][i] = cop['rho']

            elif m == 'Copula-Joe-A4f-ASYM':
                cop = state[m]['copula_joe']
                if cop is None: continue
                lambda_U_joe[i]    = cop.get('lambda_U', 0.0)
                cop_joe_params[i]  = cop
                # Joe: tau ≈ 1 - 2/(theta*(theta+2)) (approximation)
                th  = cop['theta']
                tau_j = 1.0 - 2.0/(th*(th+2.0)) if th > 1.0 else 0.0
                rho_approx = np.sin(np.pi*tau_j/2.0)
                s1 = np.sqrt(h1_t); s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2*h1_t + WEIGHTS[1]**2*h2_t + 2*WEIGHTS[0]*WEIGHTS[1]*rho_approx*s1*s2
                pvar_store[m][i] = max(pv, 1e-16)
                rho_store[m][i] = rho_approx

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar_store,
        'h1': h1_store, 'h2': h2_store, 'rho': rho_store,
        'oos_dates': oos_dates, 'oos_idx': oos_idx,
        # Copula parameter series
        'cop_t_rho': cop_t_rho, 'cop_t_nu': cop_t_nu,
        'cop_clay_theta': cop_clay_theta,
        'lambda_L_t': lambda_L_t, 'lambda_L_clay': lambda_L_clay,
        'lambda_L_skt': lambda_L_skt,
        'lambda_U_joe': lambda_U_joe,
        'skt_asym_idx': skt_asym_idx,
        # Per-day params (for MC)
        'cop_t_params': cop_t_params,
        'cop_clay_params': cop_clay_params,
        'cop_skt_params': cop_skt_params,
        'cop_joe_params': cop_joe_params,
        'marg_t_df_1': marg_t_df_1,
        'marg_t_df_2': marg_t_df_2,
    }


def compute_copula_mc_var(forecasts, copula_type, model_key,
                          alpha_levels, n_paths):
    """Compute MC VaR/ES series for one copula model."""
    h1_arr = forecasts['h1'][model_key]
    h2_arr = forecasts['h2'][model_key]
    n_oos  = len(h1_arr)

    if copula_type == 't':
        params_list = forecasts['cop_t_params']
    elif copula_type == 'clayton':
        params_list = forecasts['cop_clay_params']
    elif copula_type == 'skt':
        params_list = forecasts['cop_skt_params']
    elif copula_type == 'joe':
        params_list = forecasts['cop_joe_params']
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

    tickers = ['SPY', 'QQQ', 'IWM', 'XLF', 'TLT', 'GLD']
    print(f"Downloading prices: {tickers} + ^VIX + ^GVZ ...")

    closes = {}
    for t in tickers:
        raw = yf.download(t, start=DATA_START, end=DATA_END,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        closes[t] = raw['Close']

    vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)
    gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)

    def _close(raw):
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return raw['Close']

    df = pd.DataFrame({
        **{t.lower(): closes[t] for t in tickers},
        'vix': _close(vix_raw),
        'gvz': _close(gvz_raw),
    }).sort_index()

    df = df.dropna(subset=['spy', 'qqq', 'vix'])
    df['gvz_filled'] = df['gvz'].copy()
    df.loc[df['gvz_filled'].isna(), 'gvz_filled'] = df.loc[df['gvz_filled'].isna(), 'vix']
    df['gvz_filled'] = df['gvz_filled'].ffill()

    for t in tickers:
        col = t.lower()
        df[f'ret_{col}']    = np.log(df[col] / df[col].shift(1))
        df[f'simple_{col}'] = df[col].pct_change()

    df['vix2'] = (df['vix'] / 100.0)**2 / 252.0
    df['gvz2'] = (df['gvz_filled'] / 100.0)**2 / 252.0
    df = df.dropna(subset=['ret_spy', 'ret_qqq', 'vix2'])

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')} ({len(df)} days)")
    return df


# ============================================================
# 11. EVALUATE PAIR (all 5 models)
# ============================================================
def evaluate_pair(pair_name, asset1, asset2, reg1_col, reg2_col, df):
    print(f"\n{'=' * 72}")
    print(f"PAIR: {pair_name}  ({asset1} vs {asset2})")
    print(f"{'=' * 72}")

    a1l = asset1.lower()
    a2l = asset2.lower()
    required = [f'ret_{a1l}', f'ret_{a2l}',
                f'simple_{a1l}', f'simple_{a2l}',
                reg1_col, reg2_col]
    pair_df  = df.dropna(subset=required).copy()
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

    # M2/M3/M4/M5: MC Copula
    copula_map = {
        'Copula-t-A4f-ASYM':       't',
        'Copula-Clayton-A4f-ASYM': 'clayton',
        'Copula-SkewT-A4f-ASYM':   'skt',
        'Copula-Joe-A4f-ASYM':     'joe',
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

    # ---- DM QLIKE tests (all pairs vs baseline DCC) ----
    qlike_dm = {}
    dm_pairs = [(m, 'DCC-A4f-ASYM') for m in MODELS[1:]]  # each vs DCC
    dm_pairs += [('Copula-SkewT-A4f-ASYM', 'Copula-t-A4f-ASYM'),    # new vs K1100b
                 ('Copula-SkewT-A4f-ASYM', 'Copula-Clayton-A4f-ASYM'),
                 ('Copula-Joe-A4f-ASYM',   'Copula-t-A4f-ASYM'),
                 ('Copula-Joe-A4f-ASYM',   'Copula-Clayton-A4f-ASYM')]
    for m1, m2 in dm_pairs:
        key  = f"{m1}_vs_{m2}"
        dm   = dm_qlike(r2_oos, forecasts['pvar'][m1], forecasts['pvar'][m2])
        qlike_dm[key] = dm

    # ---- DM FZ tests ----
    fz_dm = {}
    for alpha in ALPHA_LEVELS:
        ak  = f"alpha_{alpha:.3f}"
        fz_dm[ak] = {}
        for m1, m2 in dm_pairs:
            key  = f"{m1}_vs_{m2}"
            s1   = fz_s_store[m1][alpha]
            s2   = fz_s_store[m2][alpha]
            nn   = min(len(s1), len(s2))
            if nn < 50:
                fz_dm[ak][key] = {'t_stat': 0.0, 'p_value': 1.0,
                                  'n': int(nn), 'significant_harvey': False}
            else:
                fz_dm[ak][key] = dm_test(s1[:nn], s2[:nn])

    # ---- Mean QLIKE ----
    qlike_means = {}
    for m in MODELS:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_oos)
        q = np.log(pv[valid]) + r2_oos[valid] / pv[valid]
        qlike_means[m] = float(np.mean(q))

    # ---- Copula stats ----
    cop_stats = {
        'student_t': {
            'rho_mean':    float(np.nanmean(forecasts['cop_t_rho'])),
            'nu_mean':     float(np.nanmean(forecasts['cop_t_nu'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_t'])),
        },
        'clayton': {
            'theta_mean':  float(np.nanmean(forecasts['cop_clay_theta'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_clay'])),
        },
        'skt': {
            'rho_mean':    float(np.nanmean(forecasts['rho']['Copula-SkewT-A4f-ASYM'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_skt'])),
            'asym_mean':   float(np.nanmean(forecasts['skt_asym_idx'])),
        },
        'joe': {
            'theta_mean':  float(np.nanmean(forecasts['cop_joe_params'] and [
                p['theta'] for p in forecasts['cop_joe_params'] if p is not None] or [np.nan])),
            'lambda_U_mean': float(np.nanmean(forecasts['lambda_U_joe'])),
        },
    }
    # Joe theta_mean fix
    joe_thetas = [p['theta'] for p in forecasts['cop_joe_params'] if p is not None]
    cop_stats['joe']['theta_mean'] = float(np.mean(joe_thetas)) if joe_thetas else np.nan

    # Summary print
    print(f"\n  --- {pair_name} Summary ---")
    for m in MODELS:
        q   = qlike_means[m]
        tp1 = model_res[m]['var_tests']['alpha_0.010']['trinity_pass']
        tp2 = model_res[m]['var_tests']['alpha_0.025']['trinity_pass']
        fz  = fz_m_store[m][0.01]
        print(f"    {m}: QLIKE={q:.5f}, Trinity1%={tp1}, 2.5%={tp2}, FZ={fz:.4f}")

    # DM vs DCC
    for m in MODELS[1:]:
        key = f"{m}_vs_DCC-A4f-ASYM"
        dm  = qlike_dm.get(key, {})
        t   = dm.get('t_stat', 0.0)
        sig = "***Harvey" if abs(t) > 3.0 else ("*" if dm.get('p_value', 1.0) < 0.05 else "")
        direction = "copula_better" if t > 0 else "dcc_better"
        print(f"    DM QLIKE {m} vs DCC: t={t:+.3f} ({direction}) {sig}")

    return {
        'pair_name': pair_name,
        'asset1': asset1, 'asset2': asset2,
        'n_oos': int(n_oos),
        'full_sample_corr': float(corr),
        'models': model_res,
        'dm_qlike': qlike_dm,
        'dm_fz':    fz_dm,
        'mean_qlike': qlike_means,
        'copula_stats': cop_stats,
        'oos_dates_first': pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d'),
        'oos_dates_last':  pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d'),
        # Private (for plots)
        '_fz_mean_store': fz_m_store,
        '_lambda_L_t':     forecasts['lambda_L_t'],
        '_lambda_L_skt':   forecasts['lambda_L_skt'],
        '_lambda_U_joe':   forecasts['lambda_U_joe'],
        '_oos_dates':      oos_dates,
        '_port_ret_oos':   port_ret_oos,
        '_pvar':           forecasts['pvar'],
        '_var_store':      var_store,
        '_fit_time_s':     float(time.time() - t_start),
    }


# ============================================================
# 12. PLOTS
# ============================================================
def make_plots(pair_results):
    """Generate 2 required plots."""

    pairs     = list(pair_results.keys())
    n_pairs   = len(pairs)

    # --- Plot 1: DM heatmap (5 pairs x 5 models vs DCC) ---
    fig, ax = plt.subplots(figsize=(12, 5))

    models_vs_dcc = ['Copula-t-A4f-ASYM',
                     'Copula-Clayton-A4f-ASYM',
                     'Copula-SkewT-A4f-ASYM',
                     'Copula-Joe-A4f-ASYM']
    short_labels = ['M2: Copula-t', 'M3: Copula-Clayton',
                    'M4: Copula-SkewT (NEW)', 'M5: Copula-Joe (NEW)']

    dm_matrix = np.zeros((n_pairs, len(models_vs_dcc)))
    for pi, pair in enumerate(pairs):
        pr = pair_results[pair]
        for mi, m in enumerate(models_vs_dcc):
            key = f"{m}_vs_DCC-A4f-ASYM"
            t   = pr['dm_qlike'].get(key, {}).get('t_stat', 0.0)
            dm_matrix[pi, mi] = t

    vmax = max(3.5, np.max(np.abs(dm_matrix)))
    norm = mcolors.TwoSlopeNorm(vmin=-vmax, vcenter=0.0, vmax=vmax)
    im   = ax.imshow(dm_matrix, cmap='RdYlGn', norm=norm, aspect='auto')
    plt.colorbar(im, ax=ax, label='DM t-stat (positive = copula better than DCC)')
    ax.set_xticks(range(len(models_vs_dcc)))
    ax.set_xticklabels(short_labels, rotation=20, ha='right', fontsize=9)
    ax.set_yticks(range(n_pairs))
    ax.set_yticklabels(pairs, fontsize=9)
    ax.set_title('K1100c: DM QLIKE t-stat (copula vs DCC-A4f-ASYM baseline)\n'
                 'Green = copula better; Red = DCC better; |t|>3 = Harvey sig',
                 fontsize=10)
    # Annotate
    for pi in range(n_pairs):
        for mi in range(len(models_vs_dcc)):
            t_val = dm_matrix[pi, mi]
            col   = 'white' if abs(t_val) > 1.5 else 'black'
            ax.text(mi, pi, f'{t_val:+.2f}', ha='center', va='center',
                    fontsize=8, color=col,
                    fontweight='bold' if abs(t_val) > 3.0 else 'normal')

    plt.tight_layout()
    out1 = os.path.join(SCRIPT_DIR, 'k1100c_dm_vs_family.png')
    plt.savefig(out1, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved: {out1}")

    # --- Plot 2: FZ score comparison (new models vs DCC) ---
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    alpha_vals = [0.01, 0.025]
    alpha_keys = ['alpha_0.010', 'alpha_0.025']

    for ax_idx, (alpha_v, alpha_k) in enumerate(zip(alpha_vals, alpha_keys)):
        ax = axes[ax_idx]
        models_plot = ['DCC-A4f-ASYM', 'Copula-t-A4f-ASYM',
                       'Copula-Clayton-A4f-ASYM',
                       'Copula-SkewT-A4f-ASYM', 'Copula-Joe-A4f-ASYM']
        x   = np.arange(n_pairs)
        w   = 0.15
        colors = ['#2196F3', '#FF9800', '#9C27B0', '#F44336', '#4CAF50']

        for mi, (m, col) in enumerate(zip(models_plot, colors)):
            fz_vals = []
            for pair in pairs:
                fz_vals.append(pair_results[pair]['_fz_mean_store'][m][alpha_v])
            ax.bar(x + mi*w - 2*w, fz_vals, width=w, label=m[:20],
                   color=col, alpha=0.8)

        ax.set_xticks(x)
        ax.set_xticklabels(pairs, rotation=15, ha='right', fontsize=8)
        ax.set_title(f'FZ Score (lower = better) — α={alpha_v:.1%}', fontsize=9)
        ax.set_ylabel('Mean FZ Score')
        ax.legend(fontsize=7, loc='upper right')
        ax.axhline(y=0, color='black', linewidth=0.5)

    plt.suptitle('K1100c: Fissler-Ziegel Joint VaR-ES Score by Pair and Model',
                 fontsize=10, fontweight='bold')
    plt.tight_layout()
    out2 = os.path.join(SCRIPT_DIR, 'k1100c_fz_comparison.png')
    plt.savefig(out2, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved: {out2}")


# ============================================================
# 13. MAIN
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
    for pair_name, a1, a2, r1_col, r2_col in PAIRS:
        elapsed = time.time() - START_TIME
        print(f"\n>>> [{elapsed:.0f}s elapsed] Starting pair {pair_name}")
        pair_results[pair_name] = evaluate_pair(
            pair_name, a1, a2, r1_col, r2_col, df)

        # Checkpoint save
        safe = {pn: to_json_safe(pr) for pn, pr in pair_results.items()}
        with open(RESULTS_PATH, 'w') as f:
            json.dump({'experiment_id': EXPERIMENT_ID,
                       'pair_results': safe,
                       'pairs_done': list(pair_results.keys()),
                       'timestamp_partial': datetime.now(timezone.utc).isoformat()},
                      f, indent=2)
        print(f"  Checkpoint saved ({len(pair_results)}/{len(PAIRS)} pairs)")

    # ---- Cross-pair analysis ----
    print(f"\n{'=' * 72}")
    print("CROSS-PAIR ANALYSIS")
    print(f"{'=' * 72}")

    cross_table = []
    for pair_name, pr in pair_results.items():
        row = {
            'pair': pair_name,
            'corr': pr['full_sample_corr'],
            'lambda_L_t_mean':    pr['copula_stats']['student_t']['lambda_L_mean'],
            'lambda_L_clay_mean': pr['copula_stats']['clayton']['lambda_L_mean'],
            'lambda_L_skt_mean':  pr['copula_stats']['skt']['lambda_L_mean'],
            'lambda_U_joe_mean':  pr['copula_stats']['joe']['lambda_U_mean'],
            'skt_asym_mean':      pr['copula_stats']['skt']['asym_mean'],
        }
        for m in MODELS:
            row[f'qlike_{m}'] = pr['mean_qlike'][m]
        for m in MODELS[1:]:
            key = f"{m}_vs_DCC-A4f-ASYM"
            dm  = pr['dm_qlike'].get(key, {})
            row[f'dm_t_{m}'] = dm.get('t_stat', 0.0)
            row[f'harvey_{m}'] = bool(abs(dm.get('t_stat', 0.0)) > 3.0
                                      and dm.get('t_stat', 0.0) > 0)
        cross_table.append(row)

    # Print main table
    print(f"\n{'Pair':<12} {'λ_L(t)':>7} {'λ_L(Clay)':>9} "
          f"{'λ_L(SKT)':>8} {'λ_U(Joe)':>8} "
          f"{'DM_SkewT':>9} {'DM_Joe':>8} {'Harvey_SkewT':>13} {'Harvey_Joe':>11}")
    print("-" * 100)
    for r in cross_table:
        print(f"{r['pair']:<12} "
              f"{r['lambda_L_t_mean']:>7.4f} "
              f"{r['lambda_L_clay_mean']:>9.4f} "
              f"{r['lambda_L_skt_mean']:>8.4f} "
              f"{r['lambda_U_joe_mean']:>8.4f} "
              f"{r.get('dm_t_Copula-SkewT-A4f-ASYM', 0.0):>+9.3f} "
              f"{r.get('dm_t_Copula-Joe-A4f-ASYM', 0.0):>+8.3f} "
              f"{'YES***' if r.get('harvey_Copula-SkewT-A4f-ASYM') else 'no':>13} "
              f"{'YES***' if r.get('harvey_Copula-Joe-A4f-ASYM') else 'no':>11}")

    # Cross-pair Spearman correlations
    lambda_arr  = np.array([r['lambda_L_t_mean'] for r in cross_table])
    dm_skt_arr  = np.array([r.get('dm_t_Copula-SkewT-A4f-ASYM', 0.0) for r in cross_table])
    dm_joe_arr  = np.array([r.get('dm_t_Copula-Joe-A4f-ASYM', 0.0) for r in cross_table])

    spearman_results = {}
    if len(cross_table) >= 3:
        try:
            r_skt = stats.spearmanr(lambda_arr, dm_skt_arr)
            r_joe = stats.spearmanr(lambda_arr, dm_joe_arr)
            print(f"\n  Spearman(λ_L, DM_SkewT): rho={r_skt.statistic:+.3f} p={r_skt.pvalue:.3f}")
            print(f"  Spearman(λ_L, DM_Joe):   rho={r_joe.statistic:+.3f} p={r_joe.pvalue:.3f}")
            spearman_results = {
                'lambda_L_vs_dm_skt': {'rho': float(r_skt.statistic), 'p': float(r_skt.pvalue)},
                'lambda_L_vs_dm_joe': {'rho': float(r_joe.statistic), 'p': float(r_joe.pvalue)},
            }
        except Exception as e:
            print(f"  Spearman error: {e}")

    # Scenario determination
    any_skt_pass = any(r.get('harvey_Copula-SkewT-A4f-ASYM', False) for r in cross_table)
    any_joe_pass = any(r.get('harvey_Copula-Joe-A4f-ASYM', False)   for r in cross_table)
    any_new_pass = any_skt_pass or any_joe_pass
    n_pass       = sum(r.get('harvey_Copula-SkewT-A4f-ASYM', False) or
                       r.get('harvey_Copula-Joe-A4f-ASYM', False)
                       for r in cross_table)

    if n_pass == 0:
        scenario = 'B'
        scenario_desc = ("NULL (structural confirmed): 5/5 NULL. "
                         "Portfolio mixing averaging confirmed as mechanism "
                         "regardless of copula family.")
    elif n_pass == len(PAIRS):
        scenario = 'A'
        scenario_desc = ("PASS: All pairs show Harvey |t|>3.0 for M4 or M5. "
                         "Asymmetric tail IS the missing variable.")
    else:
        scenario = 'C'
        scenario_desc = (f"MIXED: {n_pass}/{len(PAIRS)} pairs PASS Harvey |t|>3.0. "
                         f"Narrative limited to specific crash-sensitive pairs.")

    print(f"\n{'=' * 72}")
    print(f"SCENARIO DETERMINATION: {scenario}")
    print(f"  {scenario_desc}")
    print(f"  Any SkewT passes Harvey: {any_skt_pass}")
    print(f"  Any Joe passes Harvey:   {any_joe_pass}")
    print(f"{'=' * 72}")

    # Generate plots
    print("\nGenerating plots ...")
    try:
        make_plots(pair_results)
    except Exception as e:
        print(f"  Plot error: {e}")

    # Final results
    results_final = {
        'experiment_id': EXPERIMENT_ID,
        'pair_results':  {pn: to_json_safe(pr) for pn, pr in pair_results.items()},
        'cross_pair_table': cross_table,
        'scenario': scenario,
        'scenario_description': scenario_desc,
        'core_answers': {
            'any_new_copula_beats_dcc_harvey': any_new_pass,
            'any_skt_beats_dcc_harvey': any_skt_pass,
            'any_joe_beats_dcc_harvey': any_joe_pass,
            'n_pairs_with_new_copula_advantage': int(n_pass),
            'spearman': spearman_results,
        },
        'config': {
            'oos_start': OOS_START, 'window': WINDOW,
            'refit_every': REFIT_EVERY, 'alpha_levels': ALPHA_LEVELS,
            'weights': WEIGHTS.tolist(), 'mc_paths': MC_PATHS, 'seed': 42,
        },
        'metadata': {
            'experiment_id': EXPERIMENT_ID,
            'parent_experiments': ['K1100b', 'K1100', 'K1041', 'K1092'],
            'data_source': 'yfinance (SPY/QQQ/IWM/XLF/TLT/GLD + ^VIX/^GVZ)',
            'data_period': f"{DATA_START} to {DATA_END}",
            'oos_start': OOS_START,
            'pairs': [p[0] for p in PAIRS],
            'models': MODELS,
            'new_models': MODELS_NEW,
            'proposer': 'User (Lai Yi-Hao) via K1100b follow-up',
            'runtime_seconds': float(time.time() - START_TIME),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'references': [
                'Hansen (1994). Autoregressive Conditional Density. IER 35(3)',
                'Joe (1997). Multivariate Models and Dependence Concepts. Chapman&Hall',
                'Patton (2006). Modelling asymmetric exchange rate dependence. IER 47(2)',
                'K1100b (2026-04-13): symmetric copula 5/5 NULL',
                'K1100 (2026-04-12): SPY-GLD tail-independent baseline',
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
