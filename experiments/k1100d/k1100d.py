#!/usr/bin/env python3
"""
K1100d: VIX Regime-Switching Copula
====================================
[提出: 用戶 (Lai Yi-Hao) / 設計: Claude / 執行: Claude]

Parent: K1100b (5/5 NULL — Student-t and Clayton copulas lose to DCC-A4f-ASYM)
K1100c: asymmetric copula direction (separate worktree, do not touch)

Hypothesis (K1100d):
  K1100b used uniform copula family across all market states.
  Financial intuition: low-VIX → markets relatively independent (Gaussian enough);
  high-VIX → tail co-movement strengthens (need Student-t / Clayton).
  If regime-switching copula beats uniform DCC → K1100b NULL is averaging artifact.

Regime definitions (3 alternatives for robustness):
  R1: VIX(t-1) >= 25  (classical crisis cutoff)
  R2: VIX(t-1) >= rolling 252-day 75th pct  (adaptive)
  R3: 2-state Markov HMM on VIX level (most principled, but only if R1/R2 show signal)

Models (4):
  M1: DCC-A4f-ASYM (baseline, K1092 best)
  M2: Copula-t (K1100b reproduction — uniform)
  M3: RS-Copula-Gaussian-t  (VIX<threshold → Gaussian copula, VIX>=threshold → Student-t)
  M4: RS-Copula-Gaussian-Clayton (VIX<threshold → Gaussian, VIX>=threshold → Clayton)

Key lookahead prevention:
  regime(t) = VIX(t-1) >= threshold  — lag-1 mandatory
  Rolling MLE: within-regime estimate using only same-regime obs in training window

Evaluation:
  - DM QLIKE: full OOS + high-VIX sub-period + low-VIX sub-period (critical)
  - Harvey |t|>3.0 full OOS; regime sub-period |t|>2.5 + Bonferroni(4 tests)
  - Trinity (Kupiec + CC + Basel) + FZ + Acerbi-Szekely Z1
  - By-regime FZ comparison

Data: yfinance SPY, QQQ, IWM, XLF, TLT, GLD, ^VIX, ^GVZ  2005-01-04 ~ 2026-04-10
OOS: 2013-06-01 ~ 2026-04-10
window=1250, refit=63d, MC=5000, seed=42

Author: VolPred Research System (K1100d)
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
EXPERIMENT_ID = "K1100d"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1100d_results.json')
LOG_PATH = os.path.join(SCRIPT_DIR, 'run.log')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2013-06-01'
WINDOW = 1250
REFIT_EVERY = 63
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS = np.array([0.5, 0.5])
MC_PATHS = 5000

# Regime thresholds
VIX_CRISIS_THRESHOLD = 25.0          # R1: classical
VIX_ROLLING_WINDOW = 252             # R2: adaptive
VIX_ROLLING_PCT = 75.0               # R2: 75th pct

PAIRS = [
    ('SPY-QQQ', 'SPY', 'QQQ', 'vix2', 'vix2'),
    ('SPY-XLF', 'SPY', 'XLF', 'vix2', 'vix2'),
    ('SPY-IWM', 'SPY', 'IWM', 'vix2', 'vix2'),
    ('SPY-TLT', 'SPY', 'TLT', 'vix2', 'vix2'),
    ('SPY-GLD', 'SPY', 'GLD', 'vix2', 'gvz2'),
]

MODELS = [
    'DCC-A4f-ASYM',
    'Copula-t-A4f-ASYM',
    'RS-Copula-Gaussian-t-R1',
    'RS-Copula-Gaussian-Clayton-R1',
    'RS-Copula-Gaussian-t-R2',
    'RS-Copula-Gaussian-Clayton-R2',
]

# For DM analysis we focus on the 4 K1100d-specific models vs M1
RS_MODELS_R1 = ['RS-Copula-Gaussian-t-R1', 'RS-Copula-Gaussian-Clayton-R1']
RS_MODELS_R2 = ['RS-Copula-Gaussian-t-R2', 'RS-Copula-Gaussian-Clayton-R2']

# Log utility
_log_lines = []
def log(msg):
    ts = f"[{time.time()-START_TIME:7.1f}s] "
    line = ts + msg
    print(line)
    _log_lines.append(line)

def flush_log():
    with open(LOG_PATH, 'w') as f:
        f.write('\n'.join(_log_lines) + '\n')

log("=" * 72)
log(f"{EXPERIMENT_ID}: VIX Regime-Switching Copula")
log(f"  5 pairs × 6 models; OOS from {OOS_START}; window={WINDOW}; refit={REFIT_EVERY}d")
log(f"  Regime R1: VIX(t-1)>=25; R2: rolling-252d-75pct")
log("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (from K1100b)
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
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta,
                            returns, x2)
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
# 3. COPULA FITTING
# ============================================================
def fit_marginal_t_df(z):
    def neg_ll(nu):
        if nu <= 2.05 or nu > 100:
            return 1e10
        scale = np.sqrt((nu - 2.0) / nu)
        ll = np.sum(student_t.logpdf(z / scale, df=nu) - np.log(scale))
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
    u = student_t.cdf(z / scale, df=nu)
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
    log_biv = (special.gammaln((nu_c + 2.0) / 2.0)
               + special.gammaln(nu_c / 2.0)
               - 2.0 * special.gammaln((nu_c + 1.0) / 2.0)
               - 0.5 * np.log(det)
               - ((nu_c + 2.0) / 2.0) * np.log(1.0 + q / nu_c)
               + ((nu_c + 1.0) / 2.0) * np.log(1.0 + x1*x1 / nu_c)
               + ((nu_c + 1.0) / 2.0) * np.log(1.0 + x2*x2 / nu_c))
    ll = np.sum(log_biv)
    return -ll if np.isfinite(ll) else 1e10


def fit_student_t_copula(u1, u2):
    if len(u1) < 20:
        return {'rho': 0.0, 'nu': 10.0, 'converged': False}
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau):
        tau = 0.0
    rho_init = float(np.clip(np.sin(np.pi * tau / 2.0), -0.9, 0.9))
    best_res, best_nll = None, 1e10
    for nu_init in [4.0, 8.0, 15.0]:
        for rho_try in [rho_init, 0.0, 0.3]:
            try:
                res = optimize.minimize(
                    student_t_copula_nll, x0=[rho_try, nu_init],
                    args=(u1, u2), method='L-BFGS-B',
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
        term = u1**(-theta) + u2**(-theta) - 1.0
        if np.any(term <= 0):
            return 1e10
        log_term = np.log(term)
        ll = np.sum(np.log(1.0 + theta)
                    - (1.0 + theta) * (np.log(u1) + np.log(u2))
                    - (2.0 + 1.0 / theta) * log_term)
        return -ll if np.isfinite(ll) else 1e10
    except Exception:
        return 1e10


def fit_clayton_copula(u1, u2):
    if len(u1) < 20:
        return {'theta': 0.1, 'lambda_L': 0.0, 'converged': False}
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau) or tau <= 0:
        theta_init = 0.05
    else:
        theta_init = max(0.05, 2.0 * tau / (1.0 - tau))
    try:
        res = optimize.minimize_scalar(
            clayton_copula_nll, bounds=(0.01, 20.0),
            method='bounded', args=(u1, u2),
            options={'xatol': 1e-4})
    except Exception:
        return {'theta': theta_init, 'lambda_L': 0.0, 'converged': False}
    theta_hat = float(res.x)
    lambda_L = 2.0**(-1.0 / theta_hat) if theta_hat > 0.01 else 0.0
    return {'theta': theta_hat, 'lambda_L': float(lambda_L),
            'converged': bool(res.success), 'nll': float(res.fun)}


def fit_gaussian_copula(u1, u2):
    """Fit Gaussian copula (ρ only)."""
    if len(u1) < 10:
        return {'rho': 0.0, 'converged': False}
    x1 = norm.ppf(u1)
    x2 = norm.ppf(u2)
    valid = np.isfinite(x1) & np.isfinite(x2)
    if valid.sum() < 10:
        return {'rho': 0.0, 'converged': False}
    rho = float(np.corrcoef(x1[valid], x2[valid])[0, 1])
    rho = float(np.clip(rho, -0.995, 0.995))
    return {'rho': rho, 'converged': True}


def t_copula_lambda(rho, nu):
    if rho >= 0.99:
        return 1.0
    if rho <= -0.99:
        return 0.0
    arg = -np.sqrt((nu + 1.0) * (1.0 - rho) / (1.0 + rho))
    return 2.0 * student_t.cdf(arg, df=nu + 1.0)


# ============================================================
# 4. COPULA SAMPLING
# ============================================================
def sample_student_t_copula(rho, nu, n_samples, rng):
    R = np.array([[1.0, rho], [rho, 1.0]])
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        rho_c = float(np.clip(rho, -0.99, 0.99))
        R = np.array([[1.0, rho_c], [rho_c, 1.0]])
        L = np.linalg.cholesky(R)
    Z = rng.standard_normal((n_samples, 2)) @ L.T
    chi_vals = rng.chisquare(df=nu, size=n_samples)
    X = Z * np.sqrt(nu / chi_vals)[:, None]
    u1 = student_t.cdf(X[:, 0], df=nu)
    u2 = student_t.cdf(X[:, 1], df=nu)
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


def sample_clayton_copula(theta, n_samples, rng):
    if theta <= 0.01:
        u1 = rng.uniform(0, 1, n_samples)
        u2 = rng.uniform(0, 1, n_samples)
        return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)
    V = rng.gamma(1.0 / theta, scale=1.0, size=n_samples)
    V = np.maximum(V, 1e-8)
    E1 = rng.exponential(scale=1.0, size=n_samples)
    E2 = rng.exponential(scale=1.0, size=n_samples)
    u1 = (1.0 + E1 / V) ** (-1.0 / theta)
    u2 = (1.0 + E2 / V) ** (-1.0 / theta)
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


def sample_gaussian_copula(rho, n_samples, rng):
    rho_c = float(np.clip(rho, -0.995, 0.995))
    R = np.array([[1.0, rho_c], [rho_c, 1.0]])
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        L = np.eye(2)
    Z = rng.standard_normal((n_samples, 2)) @ L.T
    u1 = norm.cdf(Z[:, 0])
    u2 = norm.cdf(Z[:, 1])
    return np.clip(u1, 1e-6, 1.0-1e-6), np.clip(u2, 1e-6, 1.0-1e-6)


# ============================================================
# 5. MC VAR/ES
# ============================================================
def copula_mc_var_es(h1, h2, copula_type, copula_params,
                     marg_t_dfs, alpha_levels, n_paths, rng):
    """Simulate portfolio VaR/ES from copula.
    copula_type: 't', 'clayton', 'gaussian'
    """
    if copula_type == 't':
        rho = copula_params['rho']
        nu_c = copula_params['nu']
        u1, u2 = sample_student_t_copula(rho, nu_c, n_paths, rng)
    elif copula_type == 'clayton':
        theta = copula_params['theta']
        u1, u2 = sample_clayton_copula(theta, n_paths, rng)
    elif copula_type == 'gaussian':
        rho = copula_params['rho']
        u1, u2 = sample_gaussian_copula(rho, n_paths, rng)
    else:
        raise ValueError(f"Unknown copula type: {copula_type}")

    z1 = inv_pit_student_t(u1, marg_t_dfs[0])
    z2 = inv_pit_student_t(u2, marg_t_dfs[1])
    r1 = np.sqrt(h1) * z1
    r2 = np.sqrt(h2) * z2
    r_port = WEIGHTS[0] * r1 + WEIGHTS[1] * r2
    out = {}
    for alpha in alpha_levels:
        var_a = np.quantile(r_port, alpha)
        below = r_port[r_port <= var_a]
        es_a = np.mean(below) if len(below) > 0 else var_a
        out[alpha] = (float(var_a), float(es_a))
    return out


# ============================================================
# 6. BACKTESTING
# ============================================================
def cf_quantile(alpha, skew, exkurt):
    z = norm.ppf(alpha)
    q = (z + (z**2 - 1) * skew / 6
         + (z**3 - 3*z) * exkurt / 24
         - (2*z**3 - 5*z) * skew**2 / 36)
    return q


def compute_cf_rolling_var(port_returns, port_sigma, alpha, cf_window=252):
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
        return {'stat': 0.0, 'p_value': 1.0, 'violations': n1,
                'rate': pi_hat, 'expected_rate': float(alpha), 'pass': True}
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
            lr_ind = (-2 * ((t00 + t10) * np.log(1 - pi_all)
                            + (t01 + t11) * np.log(pi_all)
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
    valid = (np.isfinite(var_series) & np.isfinite(es_series)
             & np.isfinite(port_returns))
    r = port_returns[valid]
    v = var_series[valid]
    es = es_series[valid]
    n = len(r)
    violations = r < v
    n_viol = int(np.sum(violations))
    if n_viol < 3:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True,
                'n_violations': n_viol}
    numerator = np.sum(r[violations])
    es_avg = np.mean(es[violations])
    if abs(es_avg) < 1e-12:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True,
                'n_violations': n_viol}
    z1 = numerator / (n * alpha * es_avg) - 1
    p_val = 2 * norm.cdf(-abs(z1))
    return {'z_stat': float(z1), 'p_value': float(p_val),
            'pass': bool(p_val > 0.05), 'n_violations': n_viol}


def fz_score_series(port_returns, var_series, es_series, alpha):
    valid = (np.isfinite(var_series) & np.isfinite(es_series)
             & np.isfinite(port_returns) & (es_series < 0)
             & (var_series < 0))
    r = port_returns[valid]
    V = var_series[valid]
    E = es_series[valid]
    n = len(r)
    if n == 0:
        return np.array([]), np.nan
    indicator = (r <= V).astype(float)
    with np.errstate(divide='ignore', invalid='ignore'):
        s = (1.0 / alpha) * indicator * (V - r) / (-E) - V / E \
            + np.log(-E) - 1.0
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
    es_test = es_backtest_acerbi_szekely(
        port_returns[valid], v,
        es_series[valid] if es_series is not None else v * 1.3, alpha)
    trinity_pass = bool(kupiec['pass'] and cc['pass'] and basel['pass'])
    return {'kupiec': kupiec, 'christoffersen': cc, 'basel': basel,
            'es_test': es_test, 'trinity_pass': trinity_pass,
            'n_oos': n, 'violation_rate': float(kupiec['rate'])}


# ============================================================
# 7. DM TESTS
# ============================================================
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
    valid = (np.isfinite(actual_r2) & np.isfinite(forecast_var1)
             & np.isfinite(forecast_var2)
             & (forecast_var1 > 0) & (forecast_var2 > 0))
    r2 = actual_r2[valid]
    h1 = forecast_var1[valid]
    h2 = forecast_var2[valid]
    loss1 = np.log(h1) + r2 / h1
    loss2 = np.log(h2) + r2 / h2
    return dm_test(loss1, loss2)


# ============================================================
# 8. REGIME COMPUTATION
# ============================================================
def compute_regimes(vix_series, dates_idx):
    """
    Compute two regime masks (lag-1: regime(t) = f(VIX(t-1))).
    Returns dict with 'R1_high', 'R1_low', 'R2_high', 'R2_low' boolean arrays
    aligned to the input series (same length as vix_series).

    CRITICAL: VIX must be lagged 1 step before applying thresholds.
    """
    n = len(vix_series)
    vix_lag1 = np.full(n, np.nan)
    vix_lag1[1:] = vix_series[:-1]   # lag-1

    # R1: fixed 25 threshold
    r1_high = vix_lag1 >= VIX_CRISIS_THRESHOLD

    # R2: adaptive rolling 75th percentile
    # Rolling window 252 on the original (un-lagged) VIX then lag
    vix_roll_pct = pd.Series(vix_series).rolling(window=VIX_ROLLING_WINDOW,
                                                   min_periods=63).quantile(
        VIX_ROLLING_PCT / 100.0).values
    # Lag the threshold too
    vix_roll_pct_lag1 = np.full(n, np.nan)
    vix_roll_pct_lag1[1:] = vix_roll_pct[:-1]
    r2_high = vix_lag1 >= vix_roll_pct_lag1

    # Where we don't have a threshold yet, default to False (low regime)
    r2_high = np.where(np.isnan(vix_roll_pct_lag1), False, r2_high)

    r1_low = ~r1_high
    r2_low = ~r2_high

    return {
        'R1_high': r1_high.astype(bool),
        'R1_low': r1_low.astype(bool),
        'R2_high': r2_high.astype(bool),
        'R2_low': r2_low.astype(bool),
        'vix_lag1': vix_lag1,
        'vix_roll_pct_lag1': vix_roll_pct_lag1,
    }


def within_regime_copula_fit(u1_window, u2_window, regime_mask_window,
                              copula_type):
    """
    Fit copula using only within-regime observations from the training window.
    Falls back to full-window fit if too few regime observations.
    """
    mask = regime_mask_window
    if mask.sum() >= 30:
        u1_r = u1_window[mask]
        u2_r = u2_window[mask]
    else:
        # Insufficient within-regime obs → use full window
        u1_r = u1_window
        u2_r = u2_window

    if copula_type == 't':
        return fit_student_t_copula(u1_r, u2_r)
    elif copula_type == 'clayton':
        return fit_clayton_copula(u1_r, u2_r)
    elif copula_type == 'gaussian':
        return fit_gaussian_copula(u1_r, u2_r)
    else:
        raise ValueError(f"Unknown copula: {copula_type}")


# ============================================================
# 9. OOS FORECASTING for ONE pair
# ============================================================
def oos_forecast_pair(ret1, ret2, x21, x22, vix_full, dates,
                      oos_start, pair_label,
                      window=WINDOW, refit_every=REFIT_EVERY):
    """
    For each OOS day t:
      1. Refit A4f marginals every 63 days
      2. Compute regimes using VIX(t-1)  [lag-1 enforced]
      3. RS models: pick copula based on regime at t (from VIX(t-1))
         and use regime-conditional MLE from training window
      4. DCC & Copula-t (uniform, M2) use full-window estimates

    Returns dict with pvar_store for all models + auxiliary arrays.
    """
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret1)
    n_oos = T - oos_idx

    # Regime arrays over the full sample (lag-1 VIX)
    regimes = compute_regimes(vix_full, np.arange(T))

    # Storage
    pvar_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    h1_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    h2_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    # Active regime flags for OOS period
    regime_flag_R1 = np.full(n_oos, False, dtype=bool)
    regime_flag_R2 = np.full(n_oos, False, dtype=bool)
    # Copula params time series
    copula_t_rho = np.full(n_oos, np.nan)
    copula_t_nu = np.full(n_oos, np.nan)
    copula_clayton_theta = np.full(n_oos, np.nan)
    lambda_L_t = np.full(n_oos, np.nan)
    lambda_L_clayton = np.full(n_oos, np.nan)
    # RS copula params (active)
    rs_rho_store = {m: np.full(n_oos, np.nan) for m in
                    RS_MODELS_R1 + RS_MODELS_R2}

    # Marginal DFs for copula MC
    marg_t_df_1 = np.full(n_oos, np.nan)
    marg_t_df_2 = np.full(n_oos, np.nan)

    # Copula param stores for MC
    copula_t_params_list = [None] * n_oos
    copula_clay_params_list = [None] * n_oos
    rs_params_store = {m: [None] * n_oos for m in RS_MODELS_R1 + RS_MODELS_R2}

    # State dict
    state = {
        'marg1_p': None, 'marg2_p': None,
        'h1_prev': {m: np.nan for m in MODELS},
        'h2_prev': {m: np.nan for m in MODELS},
        'g1_prev': {m: np.nan for m in MODELS},
        'g2_prev': {m: np.nan for m in MODELS},
        'dcc_a': 0.0, 'dcc_b': 0.0,
        'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
        'eps1_prev': 0.0, 'eps2_prev': 0.0,
        'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        'cop_t': None, 'cop_clay': None,
        # RS: regime-conditional params (high/low × R1/R2)
        'rs_cop_R1_high_t': None, 'rs_cop_R1_low_gauss': None,
        'rs_cop_R1_high_clay': None,
        'rs_cop_R2_high_t': None, 'rs_cop_R2_low_gauss': None,
        'rs_cop_R2_high_clay': None,
        'marg_t_df_1': np.nan, 'marg_t_df_2': np.nan,
        'last_fit': -refit_every,
    }

    for i in range(n_oos):
        t = oos_idx + i
        if i % 500 == 0:
            elapsed = time.time() - START_TIME
            log(f"  [{pair_label}] OOS day {i}/{n_oos} ({elapsed:.0f}s)")

        # Regime at time t uses VIX(t-1) = regimes already computed with lag-1
        is_high_R1 = bool(regimes['R1_high'][t])
        is_high_R2 = bool(regimes['R2_high'][t])
        regime_flag_R1[i] = is_high_R1
        regime_flag_R2[i] = is_high_R2

        need_refit = ((i - state['last_fit']) >= refit_every
                      or state['marg1_p'] is None)

        if need_refit:
            s = max(0, t - window)
            tr1 = ret1[s:t]
            tr2 = ret2[s:t]
            tr_x21 = x21[s:t]
            tr_x22 = x22[s:t]
            tw = len(tr1)

            # A4f marginals
            a4f_1 = fit_a4f(tr1, tr_x21)
            a4f_2 = fit_a4f(tr2, tr_x22)
            eps_1 = tr1 / np.sqrt(a4f_1['h'])
            eps_2 = tr2 / np.sqrt(a4f_2['h'])

            # DCC
            dcc = fit_dcc(eps_1, eps_2)

            # Marginal df (shared across copula models)
            df_1 = fit_marginal_t_df(eps_1)
            df_2 = fit_marginal_t_df(eps_2)
            u_1 = pit_student_t(eps_1, df_1)
            u_2 = pit_student_t(eps_2, df_2)

            # Uniform copulas (M2: Copula-t)
            cop_t = fit_student_t_copula(u_1, u_2)
            cop_clay = fit_clayton_copula(u_1, u_2)

            # Training window regime masks (same lag-1 logic)
            tr_vix = vix_full[s:t]
            tr_regimes = compute_regimes(tr_vix, np.arange(tw))

            # RS R1 copulas: within-regime MLE
            rs_r1_high_t = within_regime_copula_fit(
                u_1, u_2, tr_regimes['R1_high'], 't')
            rs_r1_low_g = within_regime_copula_fit(
                u_1, u_2, tr_regimes['R1_low'], 'gaussian')
            rs_r1_high_clay = within_regime_copula_fit(
                u_1, u_2, tr_regimes['R1_high'], 'clayton')

            # RS R2 copulas
            rs_r2_high_t = within_regime_copula_fit(
                u_1, u_2, tr_regimes['R2_high'], 't')
            rs_r2_low_g = within_regime_copula_fit(
                u_1, u_2, tr_regimes['R2_low'], 'gaussian')
            rs_r2_high_clay = within_regime_copula_fit(
                u_1, u_2, tr_regimes['R2_high'], 'clayton')

            # Update state
            state['marg1_p'] = ('A4f', a4f_1['params'])
            state['marg2_p'] = ('A4f', a4f_2['params'])
            for m in MODELS:
                state['h1_prev'][m] = float(a4f_1['h'][-1])
                state['h2_prev'][m] = float(a4f_2['h'][-1])
                state['g1_prev'][m] = float(a4f_1['g'][-1])
                state['g2_prev'][m] = float(a4f_2['g'][-1])
            state['dcc_a'] = dcc['a']
            state['dcc_b'] = dcc['b']
            state['qbar11'] = dcc['qbar11']
            state['qbar22'] = dcc['qbar22']
            state['qbar12'] = dcc['qbar12']
            state['eps1_prev'] = float(eps_1[-1])
            state['eps2_prev'] = float(eps_2[-1])
            state['q11_prev'] = dcc['qbar11']
            state['q22_prev'] = dcc['qbar22']
            state['q12_prev'] = dcc['qbar12']
            state['cop_t'] = cop_t
            state['cop_clay'] = cop_clay
            state['rs_cop_R1_high_t'] = rs_r1_high_t
            state['rs_cop_R1_low_gauss'] = rs_r1_low_g
            state['rs_cop_R1_high_clay'] = rs_r1_high_clay
            state['rs_cop_R2_high_t'] = rs_r2_high_t
            state['rs_cop_R2_low_gauss'] = rs_r2_low_g
            state['rs_cop_R2_high_clay'] = rs_r2_high_clay
            state['marg_t_df_1'] = df_1
            state['marg_t_df_2'] = df_2
            state['last_fit'] = i

        # ---- One-step marginal forecast ----
        r1_prev = ret1[t-1]
        r2_prev = ret2[t-1]
        x21_prev = x21[t-1]
        x22_prev = x22[t-1]

        # Asset 1 A4f recursion
        p1 = state['marg1_p'][1]
        tau1 = max(p1[0] + p1[1] * x21_prev, 1e-16)
        u_prev1 = r1_prev / np.sqrt(tau1)
        ind1 = 1.0 if r1_prev < 0 else 0.0
        g1_t = (p1[2] + p1[3]*u_prev1**2 + p1[4]*u_prev1**2*ind1
                + p1[5]*state['g1_prev']['DCC-A4f-ASYM'])
        g1_t = max(g1_t, 1e-16)
        h1_t = max(tau1 * g1_t, 1e-16)

        # Asset 2 A4f recursion
        p2 = state['marg2_p'][1]
        tau2 = max(p2[0] + p2[1] * x22_prev, 1e-16)
        u_prev2 = r2_prev / np.sqrt(tau2)
        ind2 = 1.0 if r2_prev < 0 else 0.0
        g2_t = (p2[2] + p2[3]*u_prev2**2 + p2[4]*u_prev2**2*ind2
                + p2[5]*state['g2_prev']['DCC-A4f-ASYM'])
        g2_t = max(g2_t, 1e-16)
        h2_t = max(tau2 * g2_t, 1e-16)

        # Update g_prev for all models (same marginals)
        for m in MODELS:
            state['g1_prev'][m] = g1_t
            state['g2_prev'][m] = g2_t
            state['h1_prev'][m] = h1_t
            state['h2_prev'][m] = h2_t
            h1_store[m][i] = h1_t
            h2_store[m][i] = h2_t

        s1 = np.sqrt(h1_t)
        s2 = np.sqrt(h2_t)

        # --- DCC-A4f-ASYM ---
        a_dcc = state['dcc_a']
        b_dcc = state['dcc_b']
        c_dcc = 1.0 - a_dcc - b_dcc
        e1p = state['eps1_prev']
        e2p = state['eps2_prev']
        q11 = c_dcc * state['qbar11'] + a_dcc * e1p**2 + b_dcc * state['q11_prev']
        q22 = c_dcc * state['qbar22'] + a_dcc * e2p**2 + b_dcc * state['q22_prev']
        q12 = c_dcc * state['qbar12'] + a_dcc * e1p*e2p + b_dcc * state['q12_prev']
        denom = np.sqrt(q11 * q22)
        rho_dcc = float(np.clip(q12 / denom if denom > 1e-20 else 0.0, -0.9999, 0.9999))
        state['q11_prev'] = q11
        state['q22_prev'] = q22
        state['q12_prev'] = q12
        eps1_now = r1_prev / np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
        eps2_now = r2_prev / np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
        state['eps1_prev'] = eps1_now
        state['eps2_prev'] = eps2_now
        pv_dcc = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                  + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_dcc * s1 * s2)
        pvar_store['DCC-A4f-ASYM'][i] = max(pv_dcc, 1e-16)

        # --- Copula-t (uniform, M2) ---
        cop_t = state['cop_t']
        if cop_t is not None:
            rho_ct = cop_t['rho']
            copula_t_rho[i] = rho_ct
            copula_t_nu[i] = cop_t['nu']
            lambda_L_t[i] = t_copula_lambda(rho_ct, cop_t['nu'])
            pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                  + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_ct * s1 * s2)
            pvar_store['Copula-t-A4f-ASYM'][i] = max(pv, 1e-16)
            copula_t_params_list[i] = cop_t

        cop_clay = state['cop_clay']
        if cop_clay is not None:
            theta_cl = cop_clay['theta']
            copula_clayton_theta[i] = theta_cl
            lambda_L_clayton[i] = cop_clay.get('lambda_L', 0.0)
            tau_k = theta_cl / (theta_cl + 2.0)
            rho_clay_approx = float(np.sin(np.pi * tau_k / 2.0))
            copula_clay_params_list[i] = cop_clay

        marg_t_df_1[i] = state['marg_t_df_1']
        marg_t_df_2[i] = state['marg_t_df_2']

        # --- RS models ---
        # RS-Copula-Gaussian-t-R1
        if is_high_R1:
            cop_active_r1t = state['rs_cop_R1_high_t']
            if cop_active_r1t is not None:
                rho_r = cop_active_r1t['rho']
                rs_rho_store['RS-Copula-Gaussian-t-R1'][i] = rho_r
                rs_params_store['RS-Copula-Gaussian-t-R1'][i] = {
                    'type': 't', 'params': cop_active_r1t}
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_r * s1 * s2)
                pvar_store['RS-Copula-Gaussian-t-R1'][i] = max(pv, 1e-16)
        else:
            cop_active_r1g = state['rs_cop_R1_low_gauss']
            if cop_active_r1g is not None:
                rho_g = cop_active_r1g['rho']
                rs_rho_store['RS-Copula-Gaussian-t-R1'][i] = rho_g
                rs_params_store['RS-Copula-Gaussian-t-R1'][i] = {
                    'type': 'gaussian', 'params': cop_active_r1g}
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_g * s1 * s2)
                pvar_store['RS-Copula-Gaussian-t-R1'][i] = max(pv, 1e-16)

        # RS-Copula-Gaussian-Clayton-R1
        if is_high_R1:
            cop_active_r1c = state['rs_cop_R1_high_clay']
            if cop_active_r1c is not None:
                theta_c = cop_active_r1c.get('theta', 0.1)
                rs_rho_store['RS-Copula-Gaussian-Clayton-R1'][i] = theta_c
                rs_params_store['RS-Copula-Gaussian-Clayton-R1'][i] = {
                    'type': 'clayton', 'params': cop_active_r1c}
                tau_k = theta_c / (theta_c + 2.0)
                rho_approx = float(np.sin(np.pi * tau_k / 2.0))
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_approx * s1 * s2)
                pvar_store['RS-Copula-Gaussian-Clayton-R1'][i] = max(pv, 1e-16)
        else:
            cop_active_r1g2 = state['rs_cop_R1_low_gauss']
            if cop_active_r1g2 is not None:
                rho_g = cop_active_r1g2['rho']
                rs_rho_store['RS-Copula-Gaussian-Clayton-R1'][i] = rho_g
                rs_params_store['RS-Copula-Gaussian-Clayton-R1'][i] = {
                    'type': 'gaussian', 'params': cop_active_r1g2}
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_g * s1 * s2)
                pvar_store['RS-Copula-Gaussian-Clayton-R1'][i] = max(pv, 1e-16)

        # RS-Copula-Gaussian-t-R2
        if is_high_R2:
            cop_active_r2t = state['rs_cop_R2_high_t']
            if cop_active_r2t is not None:
                rho_r = cop_active_r2t['rho']
                rs_rho_store['RS-Copula-Gaussian-t-R2'][i] = rho_r
                rs_params_store['RS-Copula-Gaussian-t-R2'][i] = {
                    'type': 't', 'params': cop_active_r2t}
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_r * s1 * s2)
                pvar_store['RS-Copula-Gaussian-t-R2'][i] = max(pv, 1e-16)
        else:
            cop_active_r2g = state['rs_cop_R2_low_gauss']
            if cop_active_r2g is not None:
                rho_g = cop_active_r2g['rho']
                rs_rho_store['RS-Copula-Gaussian-t-R2'][i] = rho_g
                rs_params_store['RS-Copula-Gaussian-t-R2'][i] = {
                    'type': 'gaussian', 'params': cop_active_r2g}
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_g * s1 * s2)
                pvar_store['RS-Copula-Gaussian-t-R2'][i] = max(pv, 1e-16)

        # RS-Copula-Gaussian-Clayton-R2
        if is_high_R2:
            cop_active_r2c = state['rs_cop_R2_high_clay']
            if cop_active_r2c is not None:
                theta_c = cop_active_r2c.get('theta', 0.1)
                rs_rho_store['RS-Copula-Gaussian-Clayton-R2'][i] = theta_c
                rs_params_store['RS-Copula-Gaussian-Clayton-R2'][i] = {
                    'type': 'clayton', 'params': cop_active_r2c}
                tau_k = theta_c / (theta_c + 2.0)
                rho_approx = float(np.sin(np.pi * tau_k / 2.0))
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_approx * s1 * s2)
                pvar_store['RS-Copula-Gaussian-Clayton-R2'][i] = max(pv, 1e-16)
        else:
            cop_active_r2g2 = state['rs_cop_R2_low_gauss']
            if cop_active_r2g2 is not None:
                rho_g = cop_active_r2g2['rho']
                rs_rho_store['RS-Copula-Gaussian-Clayton-R2'][i] = rho_g
                rs_params_store['RS-Copula-Gaussian-Clayton-R2'][i] = {
                    'type': 'gaussian', 'params': cop_active_r2g2}
                pv = (WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t
                      + 2 * WEIGHTS[0] * WEIGHTS[1] * rho_g * s1 * s2)
                pvar_store['RS-Copula-Gaussian-Clayton-R2'][i] = max(pv, 1e-16)

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar_store,
        'h1': h1_store,
        'h2': h2_store,
        'oos_dates': oos_dates,
        'oos_idx': oos_idx,
        'regime_flag_R1': regime_flag_R1,
        'regime_flag_R2': regime_flag_R2,
        'copula_t_rho': copula_t_rho,
        'copula_t_nu': copula_t_nu,
        'copula_clayton_theta': copula_clayton_theta,
        'lambda_L_t': lambda_L_t,
        'lambda_L_clayton': lambda_L_clayton,
        'marg_t_df_1': marg_t_df_1,
        'marg_t_df_2': marg_t_df_2,
        'copula_t_params_list': copula_t_params_list,
        'copula_clay_params_list': copula_clay_params_list,
        'rs_params_store': rs_params_store,
        'rs_rho_store': rs_rho_store,
    }


# ============================================================
# 10. MC VAR/ES for copula models
# ============================================================
def compute_mc_var_for_model(forecasts, model_key, alpha_levels, n_paths):
    """Compute MC VaR/ES for copula-based models."""
    h1 = forecasts['h1'][model_key]
    h2 = forecasts['h2'][model_key]
    n_oos = len(h1)
    var_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}
    es_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}

    if model_key == 'Copula-t-A4f-ASYM':
        params_list = forecasts['copula_t_params_list']
        copula_type_list = ['t'] * n_oos
    elif model_key in RS_MODELS_R1 + RS_MODELS_R2:
        params_list = [p['params'] if p is not None else None
                       for p in forecasts['rs_params_store'][model_key]]
        copula_type_list = [p['type'] if p is not None else None
                            for p in forecasts['rs_params_store'][model_key]]
    else:
        return var_out, es_out

    df_1_arr = forecasts['marg_t_df_1']
    df_2_arr = forecasts['marg_t_df_2']

    for i in range(n_oos):
        if (not np.isfinite(h1[i]) or not np.isfinite(h2[i])
                or params_list[i] is None or copula_type_list[i] is None):
            continue
        if not (np.isfinite(df_1_arr[i]) and np.isfinite(df_2_arr[i])):
            continue
        sub_rng = np.random.default_rng(42 + i)
        mc = copula_mc_var_es(
            h1[i], h2[i], copula_type_list[i], params_list[i],
            (float(df_1_arr[i]), float(df_2_arr[i])),
            alpha_levels, n_paths, sub_rng)
        for a in alpha_levels:
            var_out[a][i] = mc[a][0]
            es_out[a][i] = mc[a][1]
    return var_out, es_out


# ============================================================
# 11. DATA LOADING
# ============================================================
def load_data():
    import yfinance as yf
    tickers = ['SPY', 'QQQ', 'IWM', 'XLF', 'TLT', 'GLD']
    log(f"Downloading: {tickers} + ^VIX + ^GVZ ...")

    closes = {}
    for tk in tickers:
        raw = yf.download(tk, start=DATA_START, end=DATA_END,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        closes[tk] = raw['Close']

    def _close(raw):
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return raw['Close']

    vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)
    gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)

    df = pd.DataFrame({
        **{tk.lower(): closes[tk] for tk in tickers},
        'vix': _close(vix_raw),
        'gvz': _close(gvz_raw),
    }).sort_index()

    df = df.dropna(subset=['spy', 'qqq', 'vix'])
    df['gvz_filled'] = df['gvz'].copy()
    mask = df['gvz_filled'].isna()
    df.loc[mask, 'gvz_filled'] = df.loc[mask, 'vix']
    df['gvz_filled'] = df['gvz_filled'].ffill()

    for tk in tickers:
        col = tk.lower()
        df[f'ret_{col}'] = np.log(df[col] / df[col].shift(1))
        df[f'simple_{col}'] = df[col].pct_change()

    df['vix2'] = (df['vix'] / 100.0) ** 2 / 252.0
    df['gvz2'] = (df['gvz_filled'] / 100.0) ** 2 / 252.0
    df = df.dropna(subset=['ret_spy', 'ret_qqq', 'vix2'])

    log(f"Data: {df.index[0].strftime('%Y-%m-%d')} to "
        f"{df.index[-1].strftime('%Y-%m-%d')} ({len(df)} days)")
    return df


# ============================================================
# 12. EVALUATE ONE PAIR
# ============================================================
def evaluate_pair(pair_name, asset1, asset2, reg1_col, reg2_col, df):
    log(f"\n{'=' * 72}")
    log(f"PAIR: {pair_name}")
    log(f"{'=' * 72}")

    a1l = asset1.lower()
    a2l = asset2.lower()
    required = [f'ret_{a1l}', f'ret_{a2l}',
                f'simple_{a1l}', f'simple_{a2l}',
                reg1_col, reg2_col, 'vix']
    pair_df = df.dropna(subset=required).copy()
    log(f"  Pair sample: {len(pair_df)} days")

    ret1 = pair_df[f'ret_{a1l}'].values
    ret2 = pair_df[f'ret_{a2l}'].values
    x21 = pair_df[reg1_col].values
    x22 = pair_df[reg2_col].values
    vix_full = pair_df['vix'].values
    dates = pair_df.index.values
    port_ret = (WEIGHTS[0] * pair_df[f'simple_{a1l}'].values
                + WEIGHTS[1] * pair_df[f'simple_{a2l}'].values)
    corr = float(np.corrcoef(ret1, ret2)[0, 1])
    log(f"  Full-sample log-return corr: {corr:.4f}")

    t_start = time.time()
    forecasts = oos_forecast_pair(ret1, ret2, x21, x22, vix_full,
                                  dates, OOS_START, pair_name)
    oos_idx = forecasts['oos_idx']
    oos_dates = forecasts['oos_dates']
    n_oos = len(oos_dates)
    port_ret_oos = port_ret[oos_idx:]
    r2_port_oos = port_ret_oos ** 2

    log(f"  OOS: {n_oos} days; fit time {time.time()-t_start:.0f}s")

    # Regime stats
    rf_R1 = forecasts['regime_flag_R1']
    rf_R2 = forecasts['regime_flag_R2']
    n_high_R1 = int(rf_R1.sum())
    n_high_R2 = int(rf_R2.sum())
    log(f"  Regime R1 high-VIX: {n_high_R1}/{n_oos} ({100*n_high_R1/n_oos:.1f}%)")
    log(f"  Regime R2 high-VIX: {n_high_R2}/{n_oos} ({100*n_high_R2/n_oos:.1f}%)")

    # --- VaR/ES computation ---
    var_series_store = {m: {} for m in MODELS}
    es_series_store = {m: {} for m in MODELS}
    fz_series_store = {m: {} for m in MODELS}
    fz_mean_store = {m: {} for m in MODELS}
    models_results = {}

    # DCC: CF-Rolling
    m = 'DCC-A4f-ASYM'
    port_sigma = np.sqrt(forecasts['pvar'][m])
    model_results = {'var_tests': {}, 'fz_score': {}}
    for alpha in ALPHA_LEVELS:
        var_s, es_s = compute_cf_rolling_var(port_ret_oos, port_sigma, alpha)
        var_series_store[m][alpha] = var_s
        es_series_store[m][alpha] = es_s
        trinity = trinity_test(port_ret_oos, var_s, es_s, alpha)
        fz_s, fz_mean = fz_score_series(port_ret_oos, var_s, es_s, alpha)
        fz_mean_store[m][alpha] = fz_mean
        fz_series_store[m][alpha] = fz_s
        ak = f"alpha_{alpha:.3f}"
        model_results['var_tests'][ak] = trinity
        model_results['fz_score'][ak] = {'mean': fz_mean, 'n': int(len(fz_s))}
    models_results[m] = model_results

    # Copula-t (M2) + RS models: MC VaR
    mc_models = ['Copula-t-A4f-ASYM'] + RS_MODELS_R1 + RS_MODELS_R2
    for m in mc_models:
        var_dict, es_dict = compute_mc_var_for_model(
            forecasts, m, ALPHA_LEVELS, MC_PATHS)
        mr = {'var_tests': {}, 'fz_score': {}}
        for alpha in ALPHA_LEVELS:
            var_s = var_dict[alpha]
            es_s = es_dict[alpha]
            var_series_store[m][alpha] = var_s
            es_series_store[m][alpha] = es_s
            trinity = trinity_test(port_ret_oos, var_s, es_s, alpha)
            fz_s, fz_mean = fz_score_series(port_ret_oos, var_s, es_s, alpha)
            fz_mean_store[m][alpha] = fz_mean
            fz_series_store[m][alpha] = fz_s
            ak = f"alpha_{alpha:.3f}"
            mr['var_tests'][ak] = trinity
            mr['fz_score'][ak] = {'mean': fz_mean, 'n': int(len(fz_s))}
        models_results[m] = mr

    # --- DM tests: full OOS, high-VIX sub-period, low-VIX sub-period ---
    def dm_subperiod(mask, model1, model2):
        """DM on masked sub-period using QLIKE."""
        pv1 = forecasts['pvar'][model1][mask]
        pv2 = forecasts['pvar'][model2][mask]
        r2_sub = r2_port_oos[mask]
        if mask.sum() < 20:
            return {'t_stat': 0.0, 'p_value': 1.0, 'n': int(mask.sum()),
                    'significant_harvey': False, 'mean_loss_diff': 0.0}
        return dm_qlike(r2_sub, pv1, pv2)

    dm_full = {}   # model vs DCC
    dm_high_R1 = {}
    dm_low_R1 = {}
    dm_high_R2 = {}
    dm_low_R2 = {}

    for m_test in ['Copula-t-A4f-ASYM'] + RS_MODELS_R1 + RS_MODELS_R2:
        key = f"DCC_vs_{m_test}"
        dm_full[key] = dm_qlike(r2_port_oos,
                                forecasts['pvar']['DCC-A4f-ASYM'],
                                forecasts['pvar'][m_test])
        dm_high_R1[key] = dm_subperiod(rf_R1, 'DCC-A4f-ASYM', m_test)
        dm_low_R1[key] = dm_subperiod(~rf_R1, 'DCC-A4f-ASYM', m_test)
        dm_high_R2[key] = dm_subperiod(rf_R2, 'DCC-A4f-ASYM', m_test)
        dm_low_R2[key] = dm_subperiod(~rf_R2, 'DCC-A4f-ASYM', m_test)

    # --- Mean QLIKE ---
    qlike_means = {}
    for m in MODELS:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_port_oos)
        if valid.sum() > 0:
            q = np.log(pv[valid]) + r2_port_oos[valid] / pv[valid]
            qlike_means[m] = float(np.mean(q))
        else:
            qlike_means[m] = np.nan

    # --- FZ by regime ---
    def fz_regime_comparison(mask, alpha):
        """Compare FZ scores by regime sub-period."""
        out = {}
        for m in MODELS:
            vs = var_series_store[m].get(alpha, np.full(n_oos, np.nan))
            es = es_series_store[m].get(alpha, np.full(n_oos, np.nan))
            _, fz_m = fz_score_series(port_ret_oos[mask], vs[mask], es[mask], alpha)
            out[m] = fz_m
        return out

    fz_high_R1 = fz_regime_comparison(rf_R1, 0.01)
    fz_low_R1 = fz_regime_comparison(~rf_R1, 0.01)
    fz_high_R2 = fz_regime_comparison(rf_R2, 0.01)
    fz_low_R2 = fz_regime_comparison(~rf_R2, 0.01)

    # Print summary
    log(f"\n  --- {pair_name} DM Summary (QLIKE, full OOS) ---")
    log(f"  {'Model':<40} {'DM t-stat':>10}  Harvey")
    for m_test in ['Copula-t-A4f-ASYM'] + RS_MODELS_R1 + RS_MODELS_R2:
        key = f"DCC_vs_{m_test}"
        t_s = dm_full[key]['t_stat']
        sig = "***" if abs(t_s) > 3.0 else ("*" if dm_full[key]['p_value'] < 0.05 else "")
        direction = "RS_better" if t_s > 0 else "DCC_better"
        log(f"  {m_test:<40} {t_s:>+10.3f}  {sig} [{direction}]")

    log(f"\n  --- {pair_name} DM by Regime (R1 VIX>=25) ---")
    log(f"  {'Model':<40} {'High-VIX t':>10}  {'Low-VIX t':>10}")
    for m_test in RS_MODELS_R1:
        key = f"DCC_vs_{m_test}"
        th = dm_high_R1[key]['t_stat']
        tl = dm_low_R1[key]['t_stat']
        log(f"  {m_test:<40} {th:>+10.3f}  {tl:>+10.3f}")

    log(f"\n  --- {pair_name} DM by Regime (R2 rolling-75pct) ---")
    log(f"  {'Model':<40} {'High-VIX t':>10}  {'Low-VIX t':>10}")
    for m_test in RS_MODELS_R2:
        key = f"DCC_vs_{m_test}"
        th = dm_high_R2[key]['t_stat']
        tl = dm_low_R2[key]['t_stat']
        log(f"  {m_test:<40} {th:>+10.3f}  {tl:>+10.3f}")

    return {
        'pair_name': pair_name,
        'asset1': asset1, 'asset2': asset2,
        'n_oos': int(n_oos),
        'full_sample_corr': corr,
        'regime_stats': {
            'R1_high_n': int(n_high_R1), 'R1_high_frac': float(n_high_R1/n_oos),
            'R2_high_n': int(n_high_R2), 'R2_high_frac': float(n_high_R2/n_oos),
        },
        'models': models_results,
        'dm_full': dm_full,
        'dm_high_R1': dm_high_R1, 'dm_low_R1': dm_low_R1,
        'dm_high_R2': dm_high_R2, 'dm_low_R2': dm_low_R2,
        'mean_qlike': qlike_means,
        'fz_high_R1': fz_high_R1, 'fz_low_R1': fz_low_R1,
        'fz_high_R2': fz_high_R2, 'fz_low_R2': fz_low_R2,
        'oos_dates_first': pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d'),
        'oos_dates_last': pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d'),
        # Private for plots
        '_oos_dates': oos_dates,
        '_port_ret_oos': port_ret_oos,
        '_pvar': forecasts['pvar'],
        '_var_series_store': var_series_store,
        '_es_series_store': es_series_store,
        '_regime_flag_R1': forecasts['regime_flag_R1'],
        '_regime_flag_R2': forecasts['regime_flag_R2'],
        '_lambda_L_t': forecasts['lambda_L_t'],
        '_copula_t_rho': forecasts['copula_t_rho'],
    }


# ============================================================
# 13. JSON SERIALIZER
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


# ============================================================
# 14. SCENARIO DETERMINATION
# ============================================================
def determine_scenario(pair_results):
    """
    Scenario A: any RS model beats DCC Harvey |t|>3.0 on any pair  → regime-averaging artifact confirmed
    Scenario B: 5/5 NULL on RS models too  → mixing-averaging is fundamental
    Scenario C: tail-dep pairs (SPY-QQQ/XLF/IWM) PASS, tail-indep (SPY-TLT/GLD) NULL
    Scenario D: high-VIX sub-period PASS, full OOS NULL
    """
    tail_dep_pairs = {'SPY-QQQ', 'SPY-XLF', 'SPY-IWM'}
    tail_indep_pairs = {'SPY-TLT', 'SPY-GLD'}
    rs_test_models = RS_MODELS_R1 + RS_MODELS_R2

    any_rs_harvey_full = False
    any_rs_harvey_highvix = False
    tail_dep_any_pass = False
    tail_indep_all_null = True

    pair_verdicts = {}
    for pn, pr in pair_results.items():
        rs_full_pass = False
        rs_highvix_pass = False
        for m in rs_test_models:
            key = f"DCC_vs_{m}"
            t_full = pr['dm_full'].get(key, {}).get('t_stat', 0.0)
            t_high_r1 = pr['dm_high_R1'].get(key, {}).get('t_stat', 0.0)
            t_high_r2 = pr['dm_high_R2'].get(key, {}).get('t_stat', 0.0)
            # Positive t_stat = RS model beats DCC
            if t_full > 3.0:
                rs_full_pass = True
                any_rs_harvey_full = True
            # Sub-period: relaxed |t|>2.5 + Bonferroni(4)
            # 4 tests: 2 RS models R1/R2 × high/low → Bonferroni α=0.05/4≈0.0125
            # Approx: |t|>2.5 as conservative cutoff
            if t_high_r1 > 2.5 or t_high_r2 > 2.5:
                rs_highvix_pass = True
                any_rs_harvey_highvix = True

        if pn in tail_dep_pairs and rs_full_pass:
            tail_dep_any_pass = True
        if pn in tail_indep_pairs and rs_full_pass:
            tail_indep_all_null = False

        pair_verdicts[pn] = {
            'rs_full_harvey': rs_full_pass,
            'rs_highvix_pass': rs_highvix_pass,
            'is_tail_dep': pn in tail_dep_pairs,
        }

    if any_rs_harvey_full:
        if tail_dep_any_pass and tail_indep_all_null:
            scenario = 'C'
            scenario_desc = 'C (tail-dep pairs only): RS copula helps on SPY-QQQ/XLF/IWM but not tail-indep pairs'
        else:
            scenario = 'A'
            scenario_desc = 'A (PASS): RS-Copula beats DCC Harvey |t|>3 → K1100b NULL was regime-averaging artifact'
    elif any_rs_harvey_highvix:
        scenario = 'D'
        scenario_desc = 'D (high-VIX effect only): RS-Copula PASS in high-VIX sub-period, full OOS NULL'
    else:
        scenario = 'B'
        scenario_desc = 'B (NULL): All RS models 5/5 NULL → mixing-averaging is fundamental, not regime-specific'

    return scenario, scenario_desc, pair_verdicts


# ============================================================
# 15. PLOTS
# ============================================================
def make_plots(pair_results):
    log("\n--- Generating Plots ---")

    # Plot 1: DM by regime heatmap
    # 5 pairs × 2 regimes (R1/R2) × 2 RS models (Gauss-t, Gauss-Clayton) × high/low
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f'{EXPERIMENT_ID}: DM t-stat by Regime (positive = RS model beats DCC)',
                 fontsize=13)

    pairs = list(pair_results.keys())
    rs_m_r1 = ['RS-Copula-Gaussian-t-R1', 'RS-Copula-Gaussian-Clayton-R1']
    rs_m_r2 = ['RS-Copula-Gaussian-t-R2', 'RS-Copula-Gaussian-Clayton-R2']

    plot_configs = [
        (axes[0, 0], 'dm_high_R1', rs_m_r1, 'R1 (VIX≥25) High-VIX Sub-period'),
        (axes[0, 1], 'dm_low_R1', rs_m_r1, 'R1 (VIX≥25) Low-VIX Sub-period'),
        (axes[1, 0], 'dm_high_R2', rs_m_r2, 'R2 (rolling-75pct) High-VIX Sub-period'),
        (axes[1, 1], 'dm_low_R2', rs_m_r2, 'R2 (rolling-75pct) Low-VIX Sub-period'),
    ]

    short_model_labels = {
        'RS-Copula-Gaussian-t-R1': 'RS-Gauss-t R1',
        'RS-Copula-Gaussian-Clayton-R1': 'RS-Gauss-Clay R1',
        'RS-Copula-Gaussian-t-R2': 'RS-Gauss-t R2',
        'RS-Copula-Gaussian-Clayton-R2': 'RS-Gauss-Clay R2',
    }

    for ax, dm_key, models_subset, title in plot_configs:
        mat = np.zeros((len(pairs), len(models_subset)))
        for pi, pn in enumerate(pairs):
            pr = pair_results[pn]
            dm_dict = pr[dm_key]
            for mi, m in enumerate(models_subset):
                k = f"DCC_vs_{m}"
                mat[pi, mi] = dm_dict.get(k, {}).get('t_stat', 0.0)

        vmax = max(3.5, np.abs(mat).max() * 1.1)
        im = ax.imshow(mat, cmap='RdYlGn', vmin=-vmax, vmax=vmax, aspect='auto')
        ax.set_xticks(range(len(models_subset)))
        ax.set_xticklabels([short_model_labels[m] for m in models_subset],
                           rotation=20, ha='right', fontsize=9)
        ax.set_yticks(range(len(pairs)))
        ax.set_yticklabels(pairs, fontsize=9)
        ax.set_title(title, fontsize=10)

        for pi in range(len(pairs)):
            for mi in range(len(models_subset)):
                val = mat[pi, mi]
                star = '***' if abs(val) > 3.0 else ('**' if abs(val) > 2.5 else '')
                ax.text(mi, pi, f'{val:+.2f}{star}', ha='center', va='center',
                        fontsize=8, color='black')

        plt.colorbar(im, ax=ax, shrink=0.8)
        ax.axhline(2.5, color='gray', lw=0.5, linestyle='--')

    plt.tight_layout()
    p1 = os.path.join(SCRIPT_DIR, 'k1100d_dm_by_regime.png')
    plt.savefig(p1, dpi=130, bbox_inches='tight')
    plt.close()
    log(f"  Saved: {p1}")

    # Plot 2: FZ score by regime comparison
    fig, axes = plt.subplots(2, len(pairs), figsize=(18, 9))
    fig.suptitle(f'{EXPERIMENT_ID}: FZ Score by Regime (lower = better)',
                 fontsize=12)

    model_colors = {
        'DCC-A4f-ASYM': 'steelblue',
        'Copula-t-A4f-ASYM': 'darkorange',
        'RS-Copula-Gaussian-t-R1': 'green',
        'RS-Copula-Gaussian-Clayton-R1': 'darkgreen',
        'RS-Copula-Gaussian-t-R2': 'purple',
        'RS-Copula-Gaussian-Clayton-R2': 'darkviolet',
    }

    for row_idx, (regime_high_key, regime_low_key, regime_label) in enumerate([
        ('fz_high_R1', 'fz_low_R1', 'R1 (VIX≥25)'),
        ('fz_high_R2', 'fz_low_R2', 'R2 rolling-75pct'),
    ]):
        for col_idx, pn in enumerate(pairs):
            pr = pair_results[pn]
            ax = axes[row_idx, col_idx]

            fz_high = pr[regime_high_key]
            fz_low = pr[regime_low_key]

            x_pos = np.arange(len(MODELS))
            bar_w = 0.35
            fz_high_vals = [fz_high.get(m, np.nan) for m in MODELS]
            fz_low_vals = [fz_low.get(m, np.nan) for m in MODELS]

            short_labels = ['DCC', 'Cop-t', 'RS-Gt-R1', 'RS-GCl-R1',
                            'RS-Gt-R2', 'RS-GCl-R2']
            colors_high = [model_colors[m] for m in MODELS]

            bars_high = ax.bar(x_pos - bar_w/2,
                               [v if np.isfinite(v) else 0 for v in fz_high_vals],
                               bar_w, label='High-VIX', color=colors_high,
                               alpha=0.85, edgecolor='black', linewidth=0.5)
            bars_low = ax.bar(x_pos + bar_w/2,
                              [v if np.isfinite(v) else 0 for v in fz_low_vals],
                              bar_w, label='Low-VIX', color=colors_high,
                              alpha=0.4, edgecolor='black', linewidth=0.5)

            ax.set_xticks(x_pos)
            ax.set_xticklabels(short_labels, rotation=30, ha='right', fontsize=7)
            if col_idx == 0:
                ax.set_ylabel(f'{regime_label}\nFZ Score (1%)', fontsize=8)
            ax.set_title(pn, fontsize=9)
            ax.grid(alpha=0.3)
            if row_idx == 0 and col_idx == 0:
                ax.legend(fontsize=7)

    plt.tight_layout()
    p2 = os.path.join(SCRIPT_DIR, 'k1100d_fz_regime_comparison.png')
    plt.savefig(p2, dpi=130, bbox_inches='tight')
    plt.close()
    log(f"  Saved: {p2}")


# ============================================================
# 16. MAIN
# ============================================================
def main():
    df = load_data()

    pair_results = {}
    for pair_name, a1, a2, r1, r2 in PAIRS:
        elapsed = time.time() - START_TIME
        log(f"\n>>> [{elapsed:.0f}s] Starting pair {pair_name} ...")
        pair_results[pair_name] = evaluate_pair(
            pair_name, a1, a2, r1, r2, df)

        # Checkpoint
        results_safe = {pn: to_json_safe(pr)
                        for pn, pr in pair_results.items()}
        with open(RESULTS_PATH, 'w') as f:
            json.dump({
                'experiment_id': EXPERIMENT_ID,
                'pair_results': results_safe,
                'config': {
                    'oos_start': OOS_START, 'window': WINDOW,
                    'refit_every': REFIT_EVERY,
                    'alpha_levels': ALPHA_LEVELS,
                    'weights': WEIGHTS.tolist(),
                    'mc_paths': MC_PATHS, 'seed': 42,
                    'vix_crisis_threshold': VIX_CRISIS_THRESHOLD,
                    'vix_rolling_window': VIX_ROLLING_WINDOW,
                    'vix_rolling_pct': VIX_ROLLING_PCT,
                },
                'pairs_done': list(pair_results.keys()),
                'timestamp_partial': datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)
        log(f"  Checkpoint saved ({len(pair_results)}/{len(PAIRS)} pairs)")
        flush_log()

    # ---- Scenario determination ----
    scenario, scenario_desc, pair_verdicts = determine_scenario(pair_results)
    log(f"\n{'=' * 72}")
    log(f"SCENARIO DETERMINATION: {scenario}")
    log(f"  {scenario_desc}")
    log(f"{'=' * 72}")

    for pn, pv in pair_verdicts.items():
        log(f"  {pn}: RS-full-Harvey={pv['rs_full_harvey']}, "
            f"RS-highVIX-pass={pv['rs_highvix_pass']}")

    # ---- Cross-pair DM summary table ----
    log(f"\n{'Pair':<12}  {'Full DM':>9}  {'HighR1':>9}  {'LowR1':>8}  "
        f"{'HighR2':>9}  {'LowR2':>8}  Model")
    log("-" * 80)
    for pn, pr in pair_results.items():
        for m in RS_MODELS_R1[:1]:  # show first RS R1 model
            key = f"DCC_vs_{m}"
            tf = pr['dm_full'].get(key, {}).get('t_stat', 0.0)
            th1 = pr['dm_high_R1'].get(key, {}).get('t_stat', 0.0)
            tl1 = pr['dm_low_R1'].get(key, {}).get('t_stat', 0.0)
        for m in RS_MODELS_R2[:1]:
            key2 = f"DCC_vs_{m}"
            th2 = pr['dm_high_R2'].get(key2, {}).get('t_stat', 0.0)
            tl2 = pr['dm_low_R2'].get(key2, {}).get('t_stat', 0.0)
        log(f"  {pn:<12} {tf:>+9.3f} {th1:>+9.3f} {tl1:>+8.3f} "
            f"{th2:>+9.3f} {tl2:>+8.3f}  RS-Gauss-t")

    # ---- Final results ----
    results_final = {
        'experiment_id': EXPERIMENT_ID,
        'scenario': scenario,
        'scenario_description': scenario_desc,
        'pair_verdicts': pair_verdicts,
        'pair_results': {pn: to_json_safe(pr) for pn, pr in pair_results.items()},
        'config': {
            'oos_start': OOS_START, 'window': WINDOW,
            'refit_every': REFIT_EVERY,
            'alpha_levels': ALPHA_LEVELS,
            'weights': WEIGHTS.tolist(),
            'mc_paths': MC_PATHS, 'seed': 42,
            'vix_crisis_threshold': VIX_CRISIS_THRESHOLD,
            'vix_rolling_window': VIX_ROLLING_WINDOW,
            'vix_rolling_pct': VIX_ROLLING_PCT,
        },
        'metadata': {
            'experiment_id': EXPERIMENT_ID,
            'parent_experiments': ['K1100b', 'K1092', 'K1041'],
            'data_source': 'yfinance (SPY, QQQ, IWM, XLF, TLT, GLD, ^VIX, ^GVZ)',
            'data_period': f"{DATA_START} to {DATA_END}",
            'oos_start': OOS_START,
            'pairs': [p[0] for p in PAIRS],
            'models': MODELS,
            'regime_definitions': {
                'R1': f'VIX(t-1) >= {VIX_CRISIS_THRESHOLD} (classical crisis)',
                'R2': f'VIX(t-1) >= rolling-{VIX_ROLLING_WINDOW}d-{VIX_ROLLING_PCT}pct (adaptive)',
            },
            'lookahead_prevention': 'regime(t) = VIX(t-1) >= threshold; 1-day lag enforced',
            'runtime_seconds': float(time.time() - START_TIME),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        },
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(to_json_safe(results_final), f, indent=2)
    log(f"\nFinal results saved: {RESULTS_PATH}")

    make_plots(pair_results)

    total_rt = time.time() - START_TIME
    log(f"\nTotal runtime: {total_rt:.1f}s")
    log(f"FINAL SCENARIO: {scenario} — {scenario_desc}")
    flush_log()


if __name__ == '__main__':
    main()
