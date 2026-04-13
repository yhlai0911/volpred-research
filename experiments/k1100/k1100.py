#!/usr/bin/env python3
"""
K1100: Student-t Copula-GARCH vs DCC-A4f for 50/50 SPY/GLD Portfolio Tail Risk
==============================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K1041: DCC-A4f (both VIX^2) beats DCC-GJR on portfolio VaR (DM t=3.83).
  K1092: DCC-A4f-ASYM (SPY-VIX, GLD-GVZ) best on QLIKE + FZ (vs DCC-GJR
         Harvey PASS, vs SYMM non-Harvey).
  K193:  Dynamic copula tail dependence (static, non-VaR); confirms asymmetric
         SPY-GLD tail dependence.
  User (Lai 2024 APFM, PRS paper): copula-GARCH expert, requested comparison.

  Question (H1): Does Student-t Copula-GARCH (symmetric lower+upper tail
    dependence) beat K1092's DCC-A4f-ASYM on portfolio VaR/ES at 1% and 2.5%?
  Question (H2): Does Clayton Copula-GARCH (lower-tail only) beat Student-t
    and DCC-A4f-ASYM on 1% downside VaR/ES?
  Question (H3): How does tail dependence dynamics (λ_L, λ_U time-varying)
    explain portfolio crash risk during COVID 2020-03?

Design (5 models):
  1. DCC-GJR              (baseline from K1041/K1092)
  2. DCC-A4f-SYMM         (both VIX^2)  [=K1041 DCC-A4f, K1092 SYMM]
  3. DCC-A4f-ASYM         (SPY-VIX, GLD-GVZ) [=K1092 best]
  4. Student-t Copula-GARCH-A4f-ASYM (A4f marginals + Student-t copula)
  5. Clayton Copula-GARCH-A4f-ASYM   (A4f marginals + Clayton copula)

Copula parameters: time-varying via rolling window (same refit frequency).
  - Student-t copula: rho (Kendall's tau-matched), nu (df) via MLE
  - Clayton copula: theta via MLE on lower-quadrant pairs

Marginal: A4f-ASYM (SPY-VIX, GLD-GVZ) for all copula models (K1092 best).
Innovation: standardized residuals -> PIT via Student-t CDF (same df as copula).

Portfolio VaR/ES:
  Monte Carlo simulation at each t (N=10000 draws):
    1. Draw (u1, u2) from copula_t
    2. Transform u -> z via marginal Student-t^{-1}(v_i) CDFs
    3. Simulated returns r_i = sigma_i(t) * z_i (GARCH variance * innovation)
    4. Portfolio r_p = 0.5 * r_1 + 0.5 * r_2
    5. VaR_alpha = -quantile_alpha(r_p); ES_alpha = mean of r_p below VaR
  Seed fixed at 42 for reproducibility.

Data: yfinance SPY, GLD, ^VIX, ^GVZ. 2005-01-01 to 2026-04-12.
OOS: 2013-06-01 onwards (same as K1092), window=1250, refit=63.
Alpha: 1%, 2.5%.
Seed: 42.

Evaluation:
  - VaR Trinity (Kupiec + CC + Basel) at 1% and 2.5%
  - ES backtest (Acerbi-Szekely Z1)
  - Fissler-Ziegel joint VaR-ES score
  - DM test (FZ) Copula-A4f vs K1092 DCC-A4f-ASYM
  - DM test (FZ) Student-t vs Clayton copula
  - Tail dependence time series: lambda_L, lambda_U
  - COVID sub-sample: did copula detect breakdown?

References:
  - Patton (2006). Modelling asymmetric exchange rate dependence. IER 47(2).
  - Jondeau & Rockinger (2006). The Copula-GARCH model. JIMF 25(5).
  - Nelsen (2006). An Introduction to Copulas. Springer.
  - Demarta & McNeil (2005). The t Copula and Related Copulas. Int Stat Rev 73(1).
  - Lai, Chen, Gerlach (2009). Copula-GARCH and VaR. JEDC.
  - Lai (2024, APFM 31(2)). PRS-based copula hedging. (User's paper.)
  - K1041, K1092, K193.

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
from scipy import stats, optimize, special
from scipy.stats import norm, chi2, t as student_t
from numba import njit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)
RNG = np.random.default_rng(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1100"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1100_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-12'
OOS_START = '2013-06-01'
WINDOW = 1250
REFIT_EVERY = 63
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS = np.array([0.5, 0.5])
MC_PATHS = 5000

MODELS = [
    'DCC-GJR',
    'DCC-A4f-SYMM',
    'DCC-A4f-ASYM',
    'Copula-t-A4f-ASYM',
    'Copula-Clayton-A4f-ASYM',
]

print("=" * 72)
print(f"{EXPERIMENT_ID}: Student-t/Clayton Copula-GARCH vs DCC-A4f")
print(f"  50/50 SPY/GLD portfolio VaR/ES via Monte Carlo copula simulation")
print(f"  Baselines: DCC-GJR, DCC-A4f-SYMM, DCC-A4f-ASYM (K1092)")
print(f"  Copulas: Student-t, Clayton (lower-tail)")
print(f"  OOS from {OOS_START}, window={WINDOW}, refit={REFIT_EVERY}d,"
      f" MC={MC_PATHS}")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (GJR + A4f, same as K1092)
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
# 2. MARGINAL FITTING (GJR, A4f)
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
                res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                        bounds=bounds,
                                        options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        x0 = [5e-6, 0.04, 0.08, 0.88]
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                     bounds=bounds)
    h = gjr_recursion(*best_res.x, returns)
    return {'params': best_res.x.tolist(), 'h': h,
            'converged': best_res.success}


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
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                     bounds=bounds)
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
                res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                        bounds=bounds,
                                        options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        best_res = optimize.minimize(obj, [0.05, 0.90], method='L-BFGS-B',
                                     bounds=bounds)

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
# 3. COPULA FITTING (Student-t, Clayton)
# ============================================================
def fit_marginal_t_df(z):
    """Fit univariate Student-t df by MLE on standardized residuals.
    z has unit scale (approximately). Model z ~ t_nu * sqrt((nu-2)/nu).
    """
    def neg_ll(nu):
        if nu <= 2.05 or nu > 100:
            return 1e10
        scale = np.sqrt((nu - 2.0) / nu)
        # z / scale ~ t_nu
        loc = 0.0
        ll = np.sum(student_t.logpdf(z / scale, df=nu) - np.log(scale))
        return -ll if np.isfinite(ll) else 1e10

    best_nu, best_ll = 10.0, 1e10
    for nu_init in [4.0, 6.0, 10.0, 15.0, 25.0]:
        try:
            res = optimize.minimize_scalar(neg_ll, bounds=(2.1, 80.0),
                                           method='bounded',
                                           options={'xatol': 1e-4})
            if res.fun < best_ll:
                best_ll = res.fun
                best_nu = res.x
        except Exception:
            continue
        # Also try with x0 initialization via minimize
        try:
            res2 = optimize.minimize(lambda p: neg_ll(p[0]),
                                     x0=[nu_init],
                                     method='Nelder-Mead',
                                     options={'xatol': 1e-3, 'fatol': 1e-3})
            if res2.fun < best_ll:
                best_ll = res2.fun
                best_nu = res2.x[0]
        except Exception:
            continue
    return float(np.clip(best_nu, 2.1, 80.0))


def pit_student_t(z, nu):
    """Probability integral transform z -> u via Student-t CDF."""
    scale = np.sqrt((nu - 2.0) / nu)
    u = student_t.cdf(z / scale, df=nu)
    # Clip to avoid 0/1 exact
    return np.clip(u, 1e-6, 1.0 - 1e-6)


def inv_pit_student_t(u, nu):
    """Inverse PIT u -> z via Student-t^{-1}."""
    scale = np.sqrt((nu - 2.0) / nu)
    z = student_t.ppf(u, df=nu) * scale
    return z


def student_t_copula_nll(params, u1, u2):
    """Negative log-likelihood of bivariate Student-t copula.
    params = [rho, nu_c]. u1, u2 in (0,1).
    """
    rho, nu_c = params
    if not (-0.995 < rho < 0.995) or not (2.1 < nu_c < 80.0):
        return 1e10
    # Inverse CDF (t)
    x1 = student_t.ppf(u1, df=nu_c)
    x2 = student_t.ppf(u2, df=nu_c)

    # Bivariate t density (unnormalized log)
    det = 1.0 - rho * rho
    if det < 1e-10:
        return 1e10
    q = (x1*x1 - 2.0*rho*x1*x2 + x2*x2) / det
    # log c(u1,u2) = log f_biv_t(x1,x2) - log f_t(x1;nu_c) - log f_t(x2;nu_c)
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
    """Fit Student-t copula (rho, nu_c)."""
    # Initialize rho via Kendall's tau
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau):
        tau = 0.0
    rho_init = np.sin(np.pi * tau / 2.0)
    rho_init = float(np.clip(rho_init, -0.9, 0.9))

    best_res, best_nll = None, 1e10
    for nu_init in [4.0, 8.0, 15.0]:
        for rho_try in [rho_init, 0.0, 0.3]:
            try:
                res = optimize.minimize(
                    student_t_copula_nll,
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
            'converged': bool(best_res.success),
            'nll': float(best_res.fun)}


def clayton_copula_nll(theta, u1, u2):
    """Negative log-likelihood of Clayton copula.
    Clayton: C(u,v;theta) = (u^{-theta} + v^{-theta} - 1)^{-1/theta}, theta > 0
    """
    if theta <= 1e-4 or theta > 30.0:
        return 1e10
    # log density:
    # log c = log(1+theta) - (1+theta)*(log u1 + log u2)
    #         - (2 + 1/theta) * log(u1^{-theta} + u2^{-theta} - 1)
    try:
        log_u1 = np.log(u1)
        log_u2 = np.log(u2)
        # w = u1^{-theta} + u2^{-theta} - 1
        term = u1**(-theta) + u2**(-theta) - 1.0
        if np.any(term <= 0):
            return 1e10
        log_term = np.log(term)
        ll = np.sum(np.log(1.0 + theta)
                    - (1.0 + theta) * (log_u1 + log_u2)
                    - (2.0 + 1.0 / theta) * log_term)
        return -ll if np.isfinite(ll) else 1e10
    except Exception:
        return 1e10


def fit_clayton_copula(u1, u2):
    """Fit Clayton copula parameter theta via MLE.
    If data shows no lower-tail dependence (negative correlation), theta
    collapses to 0. Report as weakly-converged.
    """
    # Kendall's tau -> theta (2*tau / (1-tau)) approximation for Clayton
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau) or tau <= 0:
        # Clayton requires positive dependence; use small positive
        theta_init = 0.05
    else:
        theta_init = max(0.05, 2.0 * tau / (1.0 - tau))

    best_res, best_nll = None, 1e10
    for theta_try in [0.05, 0.1, theta_init, 0.5, 1.0]:
        try:
            res = optimize.minimize_scalar(
                clayton_copula_nll,
                bounds=(0.01, 20.0),
                method='bounded',
                args=(u1, u2),
                options={'xatol': 1e-4})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except Exception:
            continue
    if best_res is None:
        return {'theta': theta_init, 'converged': False}
    theta_hat = float(best_res.x)
    lambda_L = 2.0**(-1.0 / theta_hat) if theta_hat > 0.01 else 0.0
    return {'theta': theta_hat, 'lambda_L': float(lambda_L),
            'converged': bool(best_res.success),
            'nll': float(best_res.fun)}


# ============================================================
# 4. TAIL DEPENDENCE (Student-t copula)
# ============================================================
def t_copula_lambda(rho, nu):
    """Upper/lower tail dependence of Student-t copula.
    λ = 2 * T_{ν+1}(-sqrt((ν+1)(1-ρ)/(1+ρ)))
    Symmetric (λ_L = λ_U).
    """
    if rho >= 0.99:
        return 1.0
    if rho <= -0.99:
        return 0.0
    arg = -np.sqrt((nu + 1.0) * (1.0 - rho) / (1.0 + rho))
    return 2.0 * student_t.cdf(arg, df=nu + 1.0)


# ============================================================
# 5. COPULA MC SAMPLING
# ============================================================
def sample_student_t_copula(rho, nu, n_samples, rng):
    """Sample from bivariate Student-t copula -> (u1, u2)."""
    # Sample from bivariate t: X = sqrt(nu/chi2(nu)) * Z, Z ~ N(0, R)
    R = np.array([[1.0, rho], [rho, 1.0]])
    L = np.linalg.cholesky(R)
    Z = rng.standard_normal((n_samples, 2)) @ L.T
    chi_vals = rng.chisquare(df=nu, size=n_samples)
    X = Z * np.sqrt(nu / chi_vals)[:, None]
    # Transform X -> U via t CDF
    u1 = student_t.cdf(X[:, 0], df=nu)
    u2 = student_t.cdf(X[:, 1], df=nu)
    return np.clip(u1, 1e-6, 1.0 - 1e-6), np.clip(u2, 1e-6, 1.0 - 1e-6)


def sample_clayton_copula(theta, n_samples, rng):
    """Sample from Clayton copula via Marshall-Olkin algorithm.
    1. Sample V ~ Gamma(1/theta, 1)
    2. Sample E1, E2 ~ Exp(1) independent
    3. U1 = (1 + E1/V)^{-1/theta}, U2 = (1 + E2/V)^{-1/theta}
    """
    if theta <= 0.01:
        # Independence
        u1 = rng.uniform(0, 1, n_samples)
        u2 = rng.uniform(0, 1, n_samples)
        return np.clip(u1, 1e-6, 1.0 - 1e-6), np.clip(u2, 1e-6, 1.0 - 1e-6)
    V = rng.gamma(1.0 / theta, scale=1.0, size=n_samples)
    V = np.maximum(V, 1e-8)
    E1 = rng.exponential(scale=1.0, size=n_samples)
    E2 = rng.exponential(scale=1.0, size=n_samples)
    u1 = (1.0 + E1 / V) ** (-1.0 / theta)
    u2 = (1.0 + E2 / V) ** (-1.0 / theta)
    return np.clip(u1, 1e-6, 1.0 - 1e-6), np.clip(u2, 1e-6, 1.0 - 1e-6)


def copula_mc_var_es(h1, h2, copula_type, copula_params, marg_t_dfs,
                     alpha_levels, n_paths, rng):
    """Compute portfolio VaR/ES via MC simulation from copula.

    h1, h2: scalar forecast variances for SPY, GLD at time t.
    copula_type: 't' or 'clayton'.
    copula_params: dict with {rho, nu} or {theta}.
    marg_t_dfs: (df_spy, df_gld) for Student-t marginal CDFs.
    Returns dict {alpha: (VaR, ES)}.
    """
    if copula_type == 't':
        rho = copula_params['rho']
        nu_c = copula_params['nu']
        u1, u2 = sample_student_t_copula(rho, nu_c, n_paths, rng)
    elif copula_type == 'clayton':
        theta = copula_params['theta']
        u1, u2 = sample_clayton_copula(theta, n_paths, rng)
    else:
        raise ValueError(f"Unknown copula: {copula_type}")

    # Inverse PIT via marginal Student-t CDF (fitted marginal df)
    z1 = inv_pit_student_t(u1, marg_t_dfs[0])
    z2 = inv_pit_student_t(u2, marg_t_dfs[1])

    # Simulated returns (conditional on today's forecast variance)
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
# 6. OOS FORECASTING (all models)
# ============================================================
def oos_forecast_all(ret_spy, ret_gld, vix2, gvz2, dates, oos_start,
                     window=WINDOW, refit_every=REFIT_EVERY):
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret_spy)
    n_oos = T - oos_idx

    # Store forecasts
    h_spy = {m: np.full(n_oos, np.nan) for m in MODELS}
    h_gld = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_f = {m: np.full(n_oos, np.nan) for m in MODELS}
    pvar = {m: np.full(n_oos, np.nan) for m in MODELS}
    # Copula-specific state
    copula_t_rho = np.full(n_oos, np.nan)
    copula_t_nu = np.full(n_oos, np.nan)
    copula_clayton_theta = np.full(n_oos, np.nan)
    lambda_L_t = np.full(n_oos, np.nan)  # Student-t copula tail dep
    lambda_L_clayton = np.full(n_oos, np.nan)

    # Store copula parameters for MC at each OOS day
    copula_t_params_t = [None] * n_oos
    copula_clayton_params_t = [None] * n_oos
    marg_t_df_spy_t = np.full(n_oos, np.nan)
    marg_t_df_gld_t = np.full(n_oos, np.nan)

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
            # copula specific
            'copula_t': None, 'copula_clayton': None,
            'marg_t_df_spy': np.nan, 'marg_t_df_gld': np.nan,
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

            # --- DCC-A4f-SYMM ---
            a4f_spy_vix = fit_a4f(tr_spy, tr_vix2)
            a4f_gld_vix = fit_a4f(tr_gld, tr_vix2)
            eps_symm_spy = tr_spy / np.sqrt(a4f_spy_vix['h'])
            eps_symm_gld = tr_gld / np.sqrt(a4f_gld_vix['h'])
            dcc_symm = fit_dcc(eps_symm_spy, eps_symm_gld)

            # --- DCC-A4f-ASYM: SPY-VIX + GLD-GVZ ---
            a4f_gld_gvz = fit_a4f(tr_gld, tr_gvz2)
            eps_asym_spy = tr_spy / np.sqrt(a4f_spy_vix['h'])
            eps_asym_gld = tr_gld / np.sqrt(a4f_gld_gvz['h'])
            dcc_asym = fit_dcc(eps_asym_spy, eps_asym_gld)

            # --- Copula marginals: same A4f-ASYM as DCC-A4f-ASYM ---
            # Fit marginal Student-t df for SPY and GLD standardized residuals
            df_spy = fit_marginal_t_df(eps_asym_spy)
            df_gld = fit_marginal_t_df(eps_asym_gld)
            # PIT to uniforms
            u_spy = pit_student_t(eps_asym_spy, df_spy)
            u_gld = pit_student_t(eps_asym_gld, df_gld)
            # Fit Student-t copula
            cop_t = fit_student_t_copula(u_spy, u_gld)
            # Fit Clayton copula (lower-tail)
            cop_clayton = fit_clayton_copula(u_spy, u_gld)

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

            # Copula-t-A4f-ASYM (same marginals as DCC-A4f-ASYM)
            m = 'Copula-t-A4f-ASYM'
            state[m]['marg1_p'] = ('A4f', a4f_spy_vix['params'], 'VIX')
            state[m]['marg2_p'] = ('A4f', a4f_gld_gvz['params'], 'GVZ')
            state[m]['h1_prev'] = float(a4f_spy_vix['h'][-1])
            state[m]['h2_prev'] = float(a4f_gld_gvz['h'][-1])
            state[m]['g1_prev'] = float(a4f_spy_vix['g'][-1])
            state[m]['g2_prev'] = float(a4f_gld_gvz['g'][-1])
            state[m]['copula_t'] = cop_t
            state[m]['marg_t_df_spy'] = df_spy
            state[m]['marg_t_df_gld'] = df_gld

            # Copula-Clayton-A4f-ASYM
            m = 'Copula-Clayton-A4f-ASYM'
            state[m]['marg1_p'] = ('A4f', a4f_spy_vix['params'], 'VIX')
            state[m]['marg2_p'] = ('A4f', a4f_gld_gvz['params'], 'GVZ')
            state[m]['h1_prev'] = float(a4f_spy_vix['h'][-1])
            state[m]['h2_prev'] = float(a4f_gld_gvz['h'][-1])
            state[m]['g1_prev'] = float(a4f_spy_vix['g'][-1])
            state[m]['g2_prev'] = float(a4f_gld_gvz['g'][-1])
            state[m]['copula_clayton'] = cop_clayton
            state[m]['marg_t_df_spy'] = df_spy
            state[m]['marg_t_df_gld'] = df_gld

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

            # SPY marginal
            if marg1[0] == 'GJR':
                p = marg1[1]
                ind = 1.0 if r1_prev < 0 else 0.0
                h1_t = p[0] + p[1]*r1_prev**2 + p[2]*r1_prev**2*ind + \
                       p[3]*state[m]['h1_prev']
            else:  # A4f-VIX
                p = marg1[1]
                tau = max(p[0] + p[1] * vix2_prev, 1e-16)
                u_prev = r1_prev / np.sqrt(tau)
                ind = 1.0 if r1_prev < 0 else 0.0
                g_t = p[2] + p[3]*u_prev**2 + p[4]*u_prev**2*ind + \
                      p[5]*state[m]['g1_prev']
                g_t = max(g_t, 1e-16)
                state[m]['g1_prev'] = g_t
                h1_t = tau * g_t
            h1_t = max(h1_t, 1e-16)

            # GLD marginal
            if marg2[0] == 'GJR':
                p = marg2[1]
                ind = 1.0 if r2_prev < 0 else 0.0
                h2_t = p[0] + p[1]*r2_prev**2 + p[2]*r2_prev**2*ind + \
                       p[3]*state[m]['h2_prev']
            else:  # A4f
                p = marg2[1]
                regressor = marg2[2]
                x2_prev = vix2_prev if regressor == 'VIX' else gvz2_prev
                tau = max(p[0] + p[1] * x2_prev, 1e-16)
                u_prev = r2_prev / np.sqrt(tau)
                ind = 1.0 if r2_prev < 0 else 0.0
                g_t = p[2] + p[3]*u_prev**2 + p[4]*u_prev**2*ind + \
                      p[5]*state[m]['g2_prev']
                g_t = max(g_t, 1e-16)
                state[m]['g2_prev'] = g_t
                h2_t = tau * g_t
            h2_t = max(h2_t, 1e-16)

            state[m]['h1_prev'] = h1_t
            state[m]['h2_prev'] = h2_t
            h_spy[m][i] = h1_t
            h_gld[m][i] = h2_t

            # DCC models: update DCC
            if m in ['DCC-GJR', 'DCC-A4f-SYMM', 'DCC-A4f-ASYM']:
                a_dcc = state[m]['dcc_a']
                b_dcc = state[m]['dcc_b']
                c_dcc = 1.0 - a_dcc - b_dcc
                e1p = state[m]['eps1_prev']
                e2p = state[m]['eps2_prev']
                q11 = c_dcc * state[m]['qbar11'] + a_dcc * e1p**2 + \
                      b_dcc * state[m]['q11_prev']
                q22 = c_dcc * state[m]['qbar22'] + a_dcc * e2p**2 + \
                      b_dcc * state[m]['q22_prev']
                q12 = c_dcc * state[m]['qbar12'] + a_dcc * e1p*e2p + \
                      b_dcc * state[m]['q12_prev']
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

                # Portfolio variance (DCC-based Gaussian closed-form)
                s1 = np.sqrt(h1_t)
                s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * rho_t * s1 * s2
                pvar[m][i] = max(pv, 1e-16)

            elif m == 'Copula-t-A4f-ASYM':
                # Portfolio variance from copula (use MC mean) -- we report
                # VaR/ES directly from MC, but store pvar for QLIKE comparison
                cop = state[m]['copula_t']
                copula_t_rho[i] = cop['rho']
                copula_t_nu[i] = cop['nu']
                lambda_L_t[i] = t_copula_lambda(cop['rho'], cop['nu'])
                copula_t_params_t[i] = cop
                marg_t_df_spy_t[i] = state[m]['marg_t_df_spy']
                marg_t_df_gld_t[i] = state[m]['marg_t_df_gld']
                # portfolio variance ~= analytical from Student-t copula
                # For Student-t copula the implied Pearson correlation is
                # close to rho for moderate nu. Use rho as proxy for pvar.
                s1 = np.sqrt(h1_t)
                s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * cop['rho'] * s1 * s2
                pvar[m][i] = max(pv, 1e-16)
                rho_f[m][i] = cop['rho']

            elif m == 'Copula-Clayton-A4f-ASYM':
                cop = state[m]['copula_clayton']
                copula_clayton_theta[i] = cop['theta']
                lambda_L_clayton[i] = cop.get('lambda_L', 0.0)
                copula_clayton_params_t[i] = cop
                # No closed-form correlation; approximate via Kendall tau.
                # Clayton: tau = theta / (theta + 2).
                tau_k = cop['theta'] / (cop['theta'] + 2.0)
                rho_approx = np.sin(np.pi * tau_k / 2.0)
                s1 = np.sqrt(h1_t)
                s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * rho_approx * s1 * s2
                pvar[m][i] = max(pv, 1e-16)
                rho_f[m][i] = rho_approx

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar, 'h_spy': h_spy, 'h_gld': h_gld,
        'rho': rho_f, 'oos_dates': oos_dates, 'oos_idx': oos_idx,
        'copula_t_rho': copula_t_rho,
        'copula_t_nu': copula_t_nu,
        'copula_clayton_theta': copula_clayton_theta,
        'lambda_L_t': lambda_L_t,
        'lambda_L_clayton': lambda_L_clayton,
        'copula_t_params_t': copula_t_params_t,
        'copula_clayton_params_t': copula_clayton_params_t,
        'marg_t_df_spy_t': marg_t_df_spy_t,
        'marg_t_df_gld_t': marg_t_df_gld_t,
    }


# ============================================================
# 7. VaR/ES for 5 MODELS
# ============================================================
def cf_quantile(alpha, skew, exkurt):
    z = norm.ppf(alpha)
    q = (z + (z**2 - 1) * skew / 6
         + (z**3 - 3*z) * exkurt / 24
         - (2*z**3 - 5*z) * skew**2 / 36)
    return q


def compute_cf_rolling_var(port_returns, port_sigma, alpha, cf_window=252):
    """CF-rolling VaR/ES for Gaussian DCC models (K1092 approach)."""
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


def compute_copula_mc_var(forecasts, copula_type, h_spy_key, h_gld_key,
                          alpha_levels, n_paths, rng):
    """Compute VaR/ES time series via MC at each OOS day."""
    h1 = forecasts['h_spy'][h_spy_key]
    h2 = forecasts['h_gld'][h_gld_key]
    n_oos = len(h1)
    var_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}
    es_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}

    if copula_type == 't':
        params_list = forecasts['copula_t_params_t']
    else:
        params_list = forecasts['copula_clayton_params_t']
    df_spy_arr = forecasts['marg_t_df_spy_t']
    df_gld_arr = forecasts['marg_t_df_gld_t']

    for i in range(n_oos):
        if (not np.isfinite(h1[i]) or not np.isfinite(h2[i])
                or params_list[i] is None):
            continue
        if not (np.isfinite(df_spy_arr[i]) and np.isfinite(df_gld_arr[i])):
            continue
        # Use a deterministic per-day seed derived from the master seed
        # to keep reproducibility without coupling days.
        sub_rng = np.random.default_rng(42 + i)
        mc = copula_mc_var_es(
            h1[i], h2[i], copula_type, params_list[i],
            (float(df_spy_arr[i]), float(df_gld_arr[i])),
            alpha_levels, n_paths, sub_rng)
        for a in alpha_levels:
            var_out[a][i] = mc[a][0]
            es_out[a][i] = mc[a][1]

    return var_out, es_out


# ============================================================
# 8. BACKTESTING (Kupiec/CC/Basel/ES/FZ) — same as K1092
# ============================================================
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
                            - t10 * np.log(1 - pi11)
                            - t11 * np.log(pi11)))
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

    return {'color': color,
            'violations_per_block': float(avg_violations_per_block),
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
    """Fissler-Ziegel (2016) FZ0 score, lower better."""
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
    return {
        'kupiec': kupiec, 'christoffersen': cc, 'basel': basel,
        'es_test': es_test, 'trinity_pass': trinity_pass,
        'n_oos': n, 'violation_rate': float(kupiec['rate']),
    }


# ============================================================
# 9. DM TESTS
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
             & np.isfinite(forecast_var2))
    valid &= (forecast_var1 > 0) & (forecast_var2 > 0)
    r2 = actual_r2[valid]
    h1 = forecast_var1[valid]
    h2 = forecast_var2[valid]
    loss1 = np.log(h1) + r2 / h1
    loss2 = np.log(h2) + r2 / h2
    return dm_test(loss1, loss2)


# ============================================================
# 10. DATA LOADING (same as K1092)
# ============================================================
def load_data():
    import yfinance as yf

    print("Downloading data from yfinance (SPY, GLD, ^VIX, ^GVZ)...")
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
        'spy': spy_close, 'gld': gld_close,
        'vix': vix_close, 'gvz': gvz_close
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

    df['r2_spy'] = df['ret_spy'] ** 2
    df['r2_gld'] = df['ret_gld'] ** 2

    simple_spy = df['spy'].pct_change()
    simple_gld = df['gld'].pct_change()
    df['port_ret'] = 0.5 * simple_spy + 0.5 * simple_gld

    df = df.dropna(subset=['ret_spy', 'ret_gld', 'vix2', 'gvz2'])

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total days: {len(df)}")
    first_gvz = df['gvz'].first_valid_index()
    if first_gvz is not None:
        print(f"GVZ native start: {first_gvz.strftime('%Y-%m-%d')}")
    print(f"SPY mean return: {df['ret_spy'].mean()*252:.4f}, "
          f"vol: {df['ret_spy'].std()*np.sqrt(252):.4f}")
    print(f"GLD mean return: {df['ret_gld'].mean()*252:.4f}, "
          f"vol: {df['ret_gld'].std()*np.sqrt(252):.4f}")
    print(f"SPY-GLD full-sample corr: "
          f"{np.corrcoef(df['ret_spy'], df['ret_gld'])[0,1]:.4f}")
    print(f"VIX mean: {df['vix'].mean():.2f}, "
          f"GVZ (native) mean: {df['gvz'].mean():.2f}")
    return df


# ============================================================
# 11. MAIN + PLOTS
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

    print("\n--- OOS Forecasting (5 models: 3 DCC + 2 Copula) ---")
    forecasts = oos_forecast_all(ret_spy, ret_gld, vix2, gvz2, dates,
                                 OOS_START)
    oos_dates = forecasts['oos_dates']
    oos_idx = forecasts['oos_idx']
    n_oos = len(oos_dates)

    port_ret_oos = port_ret[oos_idx:]
    r2_port_oos = port_ret_oos ** 2

    print(f"\nOOS period: {pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} "
          f"to {pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')}")
    print(f"OOS days: {n_oos}")

    # ---- VaR/ES for 5 models ----
    print("\n--- VaR/ES Evaluation ---")
    results = {'experiment_id': EXPERIMENT_ID, 'models': {}}
    var_series_store = {m: {} for m in MODELS}
    es_series_store = {m: {} for m in MODELS}
    fz_mean_store = {m: {} for m in MODELS}
    fz_series_store = {m: {} for m in MODELS}

    # DCC models use CF-Rolling VaR
    for m in ['DCC-GJR', 'DCC-A4f-SYMM', 'DCC-A4f-ASYM']:
        port_sigma = np.sqrt(forecasts['pvar'][m])
        model_results = {'var_tests': {}, 'fz_score': {}}
        print(f"\n  Model: {m} (CF-Rolling VaR)")

        for alpha in ALPHA_LEVELS:
            var_s, es_s = compute_cf_rolling_var(port_ret_oos, port_sigma,
                                                 alpha)
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
            print(f"    alpha={alpha:.3f}: viol_rate="
                  f"{trinity['violation_rate']:.4f}, "
                  f"Trinity={'PASS' if trinity['trinity_pass'] else 'FAIL'}, "
                  f"FZ={fz_mean:.4f}")

        results['models'][m] = model_results

    # Copula models use MC VaR (compute once for all alphas)
    for m, copula_type in [('Copula-t-A4f-ASYM', 't'),
                           ('Copula-Clayton-A4f-ASYM', 'clayton')]:
        print(f"\n  Model: {m} (MC VaR, N={MC_PATHS})")
        var_dict, es_dict = compute_copula_mc_var(
            forecasts, copula_type, m, m, ALPHA_LEVELS, MC_PATHS, RNG)

        model_results = {'var_tests': {}, 'fz_score': {}}
        for alpha in ALPHA_LEVELS:
            var_s = var_dict[alpha]
            es_s = es_dict[alpha]
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
            print(f"    alpha={alpha:.3f}: viol_rate="
                  f"{trinity['violation_rate']:.4f}, "
                  f"Trinity={'PASS' if trinity['trinity_pass'] else 'FAIL'}, "
                  f"FZ={fz_mean:.4f}")

        results['models'][m] = model_results

    # ---- DM tests: QLIKE ----
    print("\n--- DM Tests (Portfolio QLIKE) ---")
    qlike_dm = {}
    pairs_qlike = [
        ('DCC-A4f-ASYM', 'Copula-t-A4f-ASYM'),
        ('DCC-A4f-ASYM', 'Copula-Clayton-A4f-ASYM'),
        ('Copula-t-A4f-ASYM', 'Copula-Clayton-A4f-ASYM'),
        ('DCC-GJR', 'Copula-t-A4f-ASYM'),
        ('DCC-GJR', 'Copula-Clayton-A4f-ASYM'),
    ]
    for m1, m2 in pairs_qlike:
        dm = dm_qlike(r2_port_oos, forecasts['pvar'][m1],
                      forecasts['pvar'][m2])
        key = f"{m1}_vs_{m2}"
        qlike_dm[key] = dm
        direction = f"{m1} better" if dm['t_stat'] < 0 else f"{m2} better"
        sig = ("***" if dm['significant_harvey']
               else ("*" if dm['p_value'] < 0.05 else ""))
        print(f"  {m1} vs {m2}: DM t={dm['t_stat']:+.3f} "
              f"({direction}) {sig}")
    results['dm_qlike'] = qlike_dm

    # ---- DM tests: FZ ----
    print("\n--- DM Tests (FZ Joint VaR-ES Score) ---")
    fz_dm = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f"alpha_{alpha:.3f}"
        fz_dm[alpha_key] = {}
        for m1, m2 in pairs_qlike:
            s1 = fz_series_store[m1][alpha]
            s2 = fz_series_store[m2][alpha]
            n = min(len(s1), len(s2))
            if n < 50:
                fz_dm[alpha_key][f"{m1}_vs_{m2}"] = {
                    't_stat': 0.0, 'p_value': 1.0, 'mean_loss_diff': 0.0,
                    'n': int(n), 'significant_harvey': False}
                continue
            dm = dm_test(s1[:n], s2[:n])
            key = f"{m1}_vs_{m2}"
            fz_dm[alpha_key][key] = dm
            direction = (f"{m1} better" if dm['t_stat'] < 0
                         else f"{m2} better")
            sig = ("***" if dm['significant_harvey']
                   else ("*" if dm['p_value'] < 0.05 else ""))
            print(f"  [{alpha_key}] {m1} vs {m2}: "
                  f"DM t={dm['t_stat']:+.3f} ({direction}) {sig}")
    results['dm_fz'] = fz_dm

    # ---- Copula dynamics ----
    print("\n--- Copula Dynamics ---")
    copula_stats = {
        'student_t': {
            'rho_mean': float(np.nanmean(forecasts['copula_t_rho'])),
            'rho_std': float(np.nanstd(forecasts['copula_t_rho'])),
            'rho_min': float(np.nanmin(forecasts['copula_t_rho'])),
            'rho_max': float(np.nanmax(forecasts['copula_t_rho'])),
            'nu_mean': float(np.nanmean(forecasts['copula_t_nu'])),
            'nu_std': float(np.nanstd(forecasts['copula_t_nu'])),
            'nu_min': float(np.nanmin(forecasts['copula_t_nu'])),
            'nu_max': float(np.nanmax(forecasts['copula_t_nu'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_t'])),
            'lambda_L_std': float(np.nanstd(forecasts['lambda_L_t'])),
            'lambda_L_min': float(np.nanmin(forecasts['lambda_L_t'])),
            'lambda_L_max': float(np.nanmax(forecasts['lambda_L_t'])),
        },
        'clayton': {
            'theta_mean': float(np.nanmean(
                forecasts['copula_clayton_theta'])),
            'theta_std': float(np.nanstd(
                forecasts['copula_clayton_theta'])),
            'theta_min': float(np.nanmin(
                forecasts['copula_clayton_theta'])),
            'theta_max': float(np.nanmax(
                forecasts['copula_clayton_theta'])),
            'lambda_L_mean': float(np.nanmean(
                forecasts['lambda_L_clayton'])),
            'lambda_L_std': float(np.nanstd(
                forecasts['lambda_L_clayton'])),
            'lambda_L_min': float(np.nanmin(
                forecasts['lambda_L_clayton'])),
            'lambda_L_max': float(np.nanmax(
                forecasts['lambda_L_clayton'])),
        },
    }
    print(f"  Student-t copula: rho={copula_stats['student_t']['rho_mean']:+.4f},"
          f" nu={copula_stats['student_t']['nu_mean']:.2f},"
          f" lambda_L={copula_stats['student_t']['lambda_L_mean']:.4f}")
    print(f"  Clayton copula: theta={copula_stats['clayton']['theta_mean']:.4f},"
          f" lambda_L={copula_stats['clayton']['lambda_L_mean']:.4f}")
    results['copula_stats'] = copula_stats

    # COVID sub-sample analysis
    print("\n--- COVID Sub-sample (2020-02 to 2020-06) ---")
    covid_mask = ((pd.DatetimeIndex(oos_dates) >= '2020-02-01')
                  & (pd.DatetimeIndex(oos_dates) <= '2020-06-30'))
    covid_stats = {}
    for key_name, arr in [
        ('student_t_rho', forecasts['copula_t_rho']),
        ('student_t_lambda_L', forecasts['lambda_L_t']),
        ('clayton_theta', forecasts['copula_clayton_theta']),
        ('clayton_lambda_L', forecasts['lambda_L_clayton']),
    ]:
        covid_vals = arr[covid_mask]
        valid = np.isfinite(covid_vals)
        if valid.sum() > 0:
            v = covid_vals[valid]
            covid_stats[key_name] = {
                'mean': float(np.mean(v)),
                'min': float(np.min(v)),
                'max': float(np.max(v)),
                'range': float(np.max(v) - np.min(v)),
            }
            print(f"  COVID {key_name}: mean={np.mean(v):+.4f}, "
                  f"range=[{np.min(v):+.4f}, {np.max(v):+.4f}]")
    results['covid_copula_stats'] = covid_stats

    # Mean QLIKE
    print("\n--- Mean QLIKE ---")
    qlike_results = {}
    for m in MODELS:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_port_oos)
        q = np.log(pv[valid]) + r2_port_oos[valid] / pv[valid]
        qlike_results[m] = float(np.mean(q))
        print(f"  {m}: QLIKE = {np.mean(q):.6f}")
    results['mean_qlike'] = qlike_results

    # Trinity scoring
    trinity_scores = {}
    for m in MODELS:
        n_pass = sum(
            1 for alpha in ALPHA_LEVELS
            if results['models'][m]['var_tests']
                   [f"alpha_{alpha:.3f}"]['trinity_pass'])
        trinity_scores[m] = f"{n_pass}/{len(ALPHA_LEVELS)}"
    results['trinity_scores'] = trinity_scores

    # Core answers
    asym_vs_copt_qlike = qlike_dm['DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM']
    asym_vs_copc_qlike = qlike_dm['DCC-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM']
    core = {
        'h1_copula_t_beats_dcc_asym_qlike': {
            't_stat': asym_vs_copt_qlike['t_stat'],
            'harvey_sig': asym_vs_copt_qlike['significant_harvey'],
            'copula_better': asym_vs_copt_qlike['t_stat'] > 0,
        },
        'h2_clayton_beats_dcc_asym_qlike': {
            't_stat': asym_vs_copc_qlike['t_stat'],
            'harvey_sig': asym_vs_copc_qlike['significant_harvey'],
            'copula_better': asym_vs_copc_qlike['t_stat'] > 0,
        },
        'h1_copula_t_beats_dcc_asym_fz_1pct':
            fz_dm['alpha_0.010'].get(
                'DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM', {}),
        'h2_clayton_beats_dcc_asym_fz_1pct':
            fz_dm['alpha_0.010'].get(
                'DCC-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM', {}),
        'h3_t_vs_clayton_fz_1pct':
            fz_dm['alpha_0.010'].get(
                'Copula-t-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM', {}),
        'best_model_by_qlike': min(qlike_results.items(),
                                    key=lambda kv: kv[1])[0],
        'best_model_by_trinity': max(
            trinity_scores.items(),
            key=lambda kv: int(kv[1].split('/')[0]))[0],
    }
    results['core_answers'] = core
    print("\n--- Core Answers ---")
    print(f"  H1 (Copula-t vs DCC-A4f-ASYM QLIKE): "
          f"t={core['h1_copula_t_beats_dcc_asym_qlike']['t_stat']:+.3f} "
          f"Harvey sig="
          f"{core['h1_copula_t_beats_dcc_asym_qlike']['harvey_sig']}")
    print(f"  H2 (Clayton vs DCC-A4f-ASYM QLIKE): "
          f"t={core['h2_clayton_beats_dcc_asym_qlike']['t_stat']:+.3f} "
          f"Harvey sig="
          f"{core['h2_clayton_beats_dcc_asym_qlike']['harvey_sig']}")
    print(f"  Best by QLIKE: {core['best_model_by_qlike']}")
    print(f"  Best by Trinity: {core['best_model_by_trinity']}")

    # Metadata
    runtime = time.time() - START_TIME
    results['metadata'] = {
        'experiment_id': EXPERIMENT_ID,
        'data_source': 'yfinance (SPY, GLD, ^VIX, ^GVZ)',
        'data_period': f"{DATA_START} to {DATA_END}",
        'oos_start': OOS_START,
        'n_oos': int(n_oos),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'portfolio_weights': WEIGHTS.tolist(),
        'mc_paths': MC_PATHS,
        'seed': 42,
        'runtime_seconds': float(runtime),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'parent_experiments': ['K1041', 'K1092', 'K193'],
        'proposer': 'User (Lai Yi-Hao)',
        'references': [
            'Patton (2006) IER 47(2)',
            'Jondeau & Rockinger (2006) JIMF 25(5)',
            'Demarta & McNeil (2005) Int Stat Rev 73(1)',
            'Nelsen (2006) Intro to Copulas, Springer',
            'Lai, Chen, Gerlach (2009) JEDC',
            'Lai (2024) APFM 31(2) [PRS copula]',
            'Fissler & Ziegel (2016) Ann Stat 44(4)',
            'Kupiec (1995) J Derivatives 3',
            'Christoffersen (1998) Int Econ Rev',
            'Acerbi & Szekely (2014) Risk',
        ],
    }

    # SAVE RESULTS FIRST (before plots to avoid plotting bugs losing data)
    results_safe = to_json_safe(results)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_safe, f, indent=2)
    print(f"\nResults saved: {RESULTS_PATH}")

    # ===== PLOTS =====
    print("\n--- Generating Plots ---")
    # Convert to numpy datetime64 array for matplotlib (avoids pandas Index indexing issues)
    oos_pd_idx = pd.DatetimeIndex(oos_dates)
    oos_pd = oos_pd_idx.to_numpy()

    # Plot 1: Copula fit — rho, nu, theta time series
    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    axes[0].plot(oos_pd, forecasts['copula_t_rho'], color='steelblue', lw=1.1)
    axes[0].axhline(0, color='black', lw=0.6, linestyle=':')
    axes[0].set_ylabel('Student-t ρ')
    axes[0].set_title(f'{EXPERIMENT_ID}: Copula Parameters Time Series '
                      f'(refit every {REFIT_EVERY}d)')
    axes[0].axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
                    alpha=0.15, color='red', label='COVID')
    axes[0].grid(alpha=0.3)
    axes[0].legend()

    axes[1].plot(oos_pd, forecasts['copula_t_nu'], color='darkorange', lw=1.1)
    axes[1].set_ylabel('Student-t ν (df)')
    axes[1].axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
                    alpha=0.15, color='red')
    axes[1].grid(alpha=0.3)

    axes[2].plot(oos_pd, forecasts['copula_clayton_theta'],
                 color='darkred', lw=1.1)
    axes[2].set_ylabel('Clayton θ')
    axes[2].set_xlabel('Date')
    axes[2].axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
                    alpha=0.15, color='red')
    axes[2].grid(alpha=0.3)
    plt.tight_layout()
    cop_path = os.path.join(SCRIPT_DIR, 'k1100_copula_fit.png')
    plt.savefig(cop_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {cop_path}")

    # Plot 2: Tail dependence dynamics (lambda_L)
    fig, ax = plt.subplots(1, 1, figsize=(13, 6))
    ax.plot(oos_pd, forecasts['lambda_L_t'],
            label='Student-t λ (symmetric)', color='steelblue', lw=1.3)
    ax.plot(oos_pd, forecasts['lambda_L_clayton'],
            label='Clayton λ_L (lower-tail)', color='darkred', lw=1.3)
    ax.axhline(0, color='black', lw=0.5, linestyle=':')
    ax.axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
               alpha=0.15, color='red', label='COVID')
    ax.axvspan(pd.Timestamp('2008-09-01'), pd.Timestamp('2009-03-31'),
               alpha=0.10, color='orange', label='GFC (pre-OOS)')
    ax.set_ylabel('Tail Dependence λ')
    ax.set_xlabel('Date')
    ax.set_title(f'{EXPERIMENT_ID}: SPY-GLD Tail Dependence Dynamics')
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    td_path = os.path.join(SCRIPT_DIR, 'k1100_tail_dependence_ts.png')
    plt.savefig(td_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {td_path}")

    # Plot 3: Portfolio VaR comparison (5 models at 1%)
    fig, axes = plt.subplots(len(MODELS), 1,
                             figsize=(14, 3.0 * len(MODELS)),
                             sharex=True)
    for ax_i, m in enumerate(MODELS):
        ax = axes[ax_i]
        var_s = var_series_store[m][0.01]
        es_s = es_series_store[m][0.01]
        valid = np.isfinite(var_s)
        ax.plot(oos_pd[valid], port_ret_oos[valid], color='grey',
                alpha=0.45, linewidth=0.6, label='Portfolio Return')
        ax.plot(oos_pd[valid], var_s[valid], color='red', alpha=0.85,
                linewidth=1.0, label='VaR 1%')
        ax.plot(oos_pd[valid], es_s[valid], color='purple', alpha=0.85,
                linewidth=0.9, linestyle='--', label='ES 1%')
        violations = (port_ret_oos < var_s) & valid
        if np.any(violations):
            ax.scatter(oos_pd[violations], port_ret_oos[violations],
                       color='red', s=12, zorder=5, alpha=0.75)
        viol_rate = np.sum(violations) / max(np.sum(valid), 1)
        ax.set_title(f'{m}: violation_rate={viol_rate:.4f}')
        ax.set_ylabel('Return')
        ax.legend(fontsize=7, loc='lower left')
    axes[-1].set_xlabel('Date')
    plt.tight_layout()
    pv_path = os.path.join(SCRIPT_DIR, 'k1100_portfolio_var_compare.png')
    plt.savefig(pv_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {pv_path}")

    # Plot 4: Trinity + FZ comparison
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    ax = axes[0]
    x = np.arange(len(MODELS))
    width = 0.35
    fz_01 = [fz_mean_store[m][0.01] for m in MODELS]
    fz_025 = [fz_mean_store[m][0.025] for m in MODELS]
    ax.bar(x - width/2, fz_01, width, label='α=1%', alpha=0.85,
           color='steelblue', edgecolor='black')
    ax.bar(x + width/2, fz_025, width, label='α=2.5%', alpha=0.85,
           color='darkorange', edgecolor='black')
    ax.set_xticks(x)
    ax.set_xticklabels([m.replace('-A4f', '\n-A4f') for m in MODELS],
                       rotation=30, ha='right', fontsize=9)
    ax.set_ylabel('Mean FZ Score (lower = better)')
    ax.set_title('FZ Joint VaR-ES Score')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

    ax = axes[1]
    trinity_pass_01 = []
    trinity_pass_025 = []
    for m in MODELS:
        trinity_pass_01.append(
            1 if results['models'][m]['var_tests']
                      ['alpha_0.010']['trinity_pass'] else 0)
        trinity_pass_025.append(
            1 if results['models'][m]['var_tests']
                      ['alpha_0.025']['trinity_pass'] else 0)
    ax.bar(x - width/2, trinity_pass_01, width, label='α=1%',
           alpha=0.85, color='steelblue', edgecolor='black')
    ax.bar(x + width/2, trinity_pass_025, width, label='α=2.5%',
           alpha=0.85, color='darkorange', edgecolor='black')
    ax.set_xticks(x)
    ax.set_xticklabels([m.replace('-A4f', '\n-A4f') for m in MODELS],
                       rotation=30, ha='right', fontsize=9)
    ax.set_ylabel('Trinity PASS (1) / FAIL (0)')
    ax.set_title('Trinity Test (Kupiec + CC + Basel)')
    ax.set_ylim(0, 1.2)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

    plt.suptitle(f'{EXPERIMENT_ID}: Portfolio VaR/ES — 5 Models Comparison',
                 fontsize=12)
    plt.tight_layout()
    tr_path = os.path.join(SCRIPT_DIR, 'k1100_trinity_comparison.png')
    plt.savefig(tr_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {tr_path}")

    print(f"Total runtime: {runtime:.1f}s")


if __name__ == '__main__':
    main()
