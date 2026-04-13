#!/usr/bin/env python3
"""
K1100f: Copula-GARCH + PRG on REAL spot-futures pair (SPY-ES=F)
=================================================================
[提出: Claude 自主研究 / 設計: Claude / 執行: Claude worktree agent]

Parent experiments:
  - K1100 (SPY-GLD, copula null, tail-independent pair)
  - K1100b (5 equity pairs, copula null on all — general equity fails)
  - K868/K874c/d/e/K880 (PRG on TAIFEX session structure)
  - Lai (2024 APFM 31(2)) — PRS copula hedging on TAIFEX TX spot-futures

Motivation:
  K1100 + K1100b establishes that copula-GARCH CANNOT generalize to general
  equity pairs. But Lai 2024 PRS succeeded on TAIFEX TX spot-futures because:
    1. Near-perfect corr (~0.99) between spot-futures
    2. Periodic return structure (day-of-week, settlement day, session effects)
    3. Temporal lead-lag (futures price discovery)

  K1100f asks: on a REAL US spot-futures pair (SPY vs ES=F CME E-mini),
  does COPULA + PERIODIC GARCH (PRG) give decisive advantage over DCC?

Design: 1 primary pair (SPY-ES=F) × 4 models = 4 cells
  Optional: GLD-GC=F as second pair (robustness, futures-ETF tracking)

Models (shared A4f-style marginal framework):
  M1. DCC-A4f-ASYM (K1041/K1092 baseline)
  M2. Student-t Copula-A4f-ASYM (K1100 standard)
  M3. PRG-A4f-ASYM + Gaussian DCC correlation
       (marginals add day-of-week dummies in τ; corr via DCC)
  M4. PRG-A4f-ASYM + Student-t Copula
       (FULL Paper 3 target spec: periodic marginal + tail-dep copula)

Hypotheses:
  H1: M4 > M1 at Harvey |t|>3.0 on DM QLIKE (full combo wins)
  H2: M3 > M1 significantly (periodic marginal alone helps)
  H3: M2 > M1 significantly (copula alone helps on real spot-futures)
  H4: Interaction: (M4-M3) > (M2-M1) (PRG+copula synergy)

PRG Specification (daily frequency):
  A4f marginal:
    τ_t  = θ₀ + θ₁·x²_{t-1}         (baseline, K1041 A4f)
  PRG marginal (extends A4f):
    τ_t  = θ₀ + θ₁·x²_{t-1} + δ_Tue·I_Tue + δ_Wed·I_Wed
         + δ_Thu·I_Thu + δ_Fri·I_Fri  (Monday = baseline; 4 extra params)
    g_t  = ω + α·u²_{t-1} + γ·u²_{t-1}·I(r<0) + β·g_{t-1}  (same as A4f)
    h_t  = τ_t · g_t

  Reference: Bollerslev & Ghysels (1996) periodic GARCH; Lai 2024 PRS.

Data:
  - SPY (yfinance, auto_adjust=True)
  - ES=F (yfinance, continuous E-mini S&P 500 futures)
  - ^VIX (regressor for both marginals)
  - 2013-01-02 → 2026-04-10 (both series available from 2013)

OOS:
  - Training window: 1250 days
  - OOS start: 2018-02-01 (to preserve 5+ years training given 2013 start)
  - Refit frequency: 63 days
  - MC paths: 3000 (slightly smaller than K1100b's 5000 for speed)
  - Seed: 42 (reproducibility)

Evaluation:
  - Portfolio (50/50): DM QLIKE, FZ, Trinity VaR test, ES backtest
  - Periodic diagnostics: conditional variance by day-of-week
  - Spot-futures basis time series + correlation regime check

Runtime target: < 25 min (1 pair × 4 models; k1100b 1 pair × 3 models ~340s;
  expect ~400s/pair with 4th model, so 1 pair < 10 min is feasible; if we
  add GLD-GC=F, ~25 min total).

Key Decisions (informing Paper 3):
  - If H1-H4 all FAIL → Paper 3 needs reframing as Taiwan-specific finding
  - If H1 passes (full combo wins) → Paper 3 core thesis validated
  - If only H3 passes (copula alone) → periodic is unnecessary on SPY-ES
  - If only H2 passes (PRG alone) → copula doesn't add on top

Author: VolPred Research System
Date: 2026-04-13
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
EXPERIMENT_ID = "K1100f"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1100f_results.json')

# ============================================================
# Configuration
# ============================================================
DATA_START = '2013-01-01'   # ES=F and SPY both available from 2013-01-02
DATA_END = '2026-04-12'
OOS_START = '2018-02-01'    # ~5yr training before OOS
WINDOW = 1250
REFIT_EVERY = 63
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS = np.array([0.5, 0.5])
MC_PATHS = 3000

# Pairs: (name, asset1, asset2) — use VIX^2 as common regressor
PAIRS = [
    ('SPY-ES', 'SPY', 'ES=F'),        # Primary US spot-futures
    ('GLD-GC', 'GLD', 'GC=F'),        # Gold robustness (different asset class)
]

# 4 models × both flavours of marginal and correlation
MODELS = [
    'DCC-A4f-ASYM',           # M1 baseline
    'Copula-t-A4f-ASYM',      # M2 copula only
    'DCC-PRG-ASYM',           # M3 PRG only (periodic marginal + Gaussian DCC)
    'Copula-t-PRG-ASYM',      # M4 PRG + copula (full combo)
]

# Day-of-week indicator setup: Monday=0 baseline, Tuesday..Friday as dummies
# Total 4 extra parameters per asset in the PRG variant.
N_DOW_DUMMIES = 4  # Tue, Wed, Thu, Fri

print("=" * 72)
print(f"{EXPERIMENT_ID}: Copula + PRG on spot-futures pair (SPY-ES=F)")
print(f"  Pairs: {[p[0] for p in PAIRS]}")
print(f"  Models: 4 (DCC-A4f, Copula-A4f, DCC-PRG, Copula-PRG)")
print(f"  OOS from {OOS_START}, window={WINDOW}, refit={REFIT_EVERY}d, "
      f"MC={MC_PATHS}")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS — A4f and PRG marginals
# ============================================================
@njit(cache=True)
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, x2):
    """A4f GARCH: τ = θ₀ + θ₁·x²_{t-1}, g_t is GJR on normalised u.

    Returns (h, tau, g).
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


@njit(cache=True)
def a4f_nll(theta0, theta1, omega, alpha, gamma, beta, returns, x2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta,
                            returns, x2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit(cache=True)
def prg_recursion(theta0, theta1, delta_tue, delta_wed, delta_thu, delta_fri,
                  omega, alpha, gamma, beta, returns, x2, dow):
    """PRG-A4f: τ_t = θ₀ + θ₁·x²_{t-1} + δ_d·I(dow==d).

    dow is an int array in {0..4} representing Monday..Friday.
    Monday (dow==0) is baseline (no dummy).
    """
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    # Periodic adjustment for τ
    for t in range(T):
        if t == 0:
            tau[0] = theta0 + theta1 * x2[0]
        else:
            tau[t] = theta0 + theta1 * x2[t-1]
        d = dow[t]
        if d == 1:
            tau[t] += delta_tue
        elif d == 2:
            tau[t] += delta_wed
        elif d == 3:
            tau[t] += delta_thu
        elif d == 4:
            tau[t] += delta_fri
        if tau[t] < 1e-16:
            tau[t] = 1e-16
    # g recursion (same shape as A4f)
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
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


@njit(cache=True)
def prg_nll(theta0, theta1, delta_tue, delta_wed, delta_thu, delta_fri,
            omega, alpha, gamma, beta, returns, x2, dow):
    h, _, _ = prg_recursion(theta0, theta1, delta_tue, delta_wed, delta_thu,
                             delta_fri, omega, alpha, gamma, beta,
                             returns, x2, dow)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit(cache=True)
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


@njit(cache=True)
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
# 2. MARGINAL FITTING
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
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                     bounds=bounds)
    h, tau, g = a4f_recursion(*best_res.x, returns, x2)
    return {'params': best_res.x.tolist(), 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'type': 'A4f'}


def fit_prg(returns, x2, dow):
    """Fit PRG (A4f + day-of-week dummies in τ).

    Parameters (10 total):
      θ₀, θ₁, δ_Tue, δ_Wed, δ_Thu, δ_Fri, ω, α, γ, β
    """
    # Bounds: dummy perturbations on τ.
    # τ baseline ≈ theta0 + theta1·VIX² ≈ 1e-5 + 1·1e-4 ≈ 1e-4 typical.
    # Allow dummies ±1e-4 (≈100% of baseline) — generous but not swamping.
    # (Codex K1100f review: original ±5e-4 too wide.)
    bounds = [
        (-0.01, 0.01),   # θ₀ intercept
        (0.01, 5.0),     # θ₁ slope on x²
        (-1e-4, 1e-4),   # δ_Tue
        (-1e-4, 1e-4),   # δ_Wed
        (-1e-4, 1e-4),   # δ_Thu
        (-1e-4, 1e-4),   # δ_Fri
        (1e-6, 1.0),     # ω
        (1e-6, 0.5),     # α
        (1e-6, 0.5),     # γ
        (0.5, 0.999),    # β
    ]

    def obj(p):
        if p[7] + 0.5*p[8] + p[9] >= 1.0:
            return 1e10
        try:
            v = prg_nll(p[0], p[1], p[2], p[3], p[4], p[5],
                        p[6], p[7], p[8], p[9], returns, x2, dow)
            return v if np.isfinite(v) else 1e10
        except Exception:
            return 1e10

    best_res, best_nll = None, 1e10
    # Initialise dummies at 0 (start from A4f solution), multiple restarts
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, 0.0, 0.0, 0.0, 0.0,
                  omega_init, 0.04, 0.06, 0.90]
            try:
                res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                        bounds=bounds,
                                        options={'maxiter': 500})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except Exception:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.05, 0.04, 0.06, 0.90]
        best_res = optimize.minimize(obj, x0, method='L-BFGS-B',
                                     bounds=bounds)
    p = best_res.x
    h, tau, g = prg_recursion(p[0], p[1], p[2], p[3], p[4], p[5],
                               p[6], p[7], p[8], p[9], returns, x2, dow)
    return {'params': p.tolist(), 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'type': 'PRG',
            'delta_dummies': [float(p[2]), float(p[3]), float(p[4]),
                              float(p[5])]}


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
# 3. COPULA (Student-t only; Clayton dropped for speed)
# ============================================================
def fit_marginal_t_df(z):
    def neg_ll(nu):
        if nu <= 2.05 or nu > 100:
            return 1e10
        scale = np.sqrt((nu - 2.0) / nu)
        ll = np.sum(student_t.logpdf(z / scale, df=nu) - np.log(scale))
        return -ll if np.isfinite(ll) else 1e10

    try:
        res = optimize.minimize_scalar(neg_ll, bounds=(2.1, 80.0),
                                       method='bounded',
                                       options={'xatol': 1e-4})
        nu = res.x
    except Exception:
        nu = 10.0
    return float(np.clip(nu, 2.1, 80.0))


def pit_student_t(z, nu):
    scale = np.sqrt((nu - 2.0) / nu)
    u = student_t.cdf(z / scale, df=nu)
    return np.clip(u, 1e-6, 1.0 - 1e-6)


def inv_pit_student_t(u, nu):
    scale = np.sqrt((nu - 2.0) / nu)
    z = student_t.ppf(u, df=nu) * scale
    return z


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
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau):
        tau = 0.0
    rho_init = float(np.clip(np.sin(np.pi * tau / 2.0), -0.9, 0.9))
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


def t_copula_lambda(rho, nu):
    if rho >= 0.99:
        return 1.0
    if rho <= -0.99:
        return 0.0
    arg = -np.sqrt((nu + 1.0) * (1.0 - rho) / (1.0 + rho))
    return 2.0 * student_t.cdf(arg, df=nu + 1.0)


def sample_student_t_copula(rho, nu, n_samples, rng):
    R = np.array([[1.0, rho], [rho, 1.0]])
    try:
        L = np.linalg.cholesky(R)
    except np.linalg.LinAlgError:
        R = np.array([[1.0, np.clip(rho, -0.99, 0.99)],
                      [np.clip(rho, -0.99, 0.99), 1.0]])
        L = np.linalg.cholesky(R)
    Z = rng.standard_normal((n_samples, 2)) @ L.T
    chi_vals = rng.chisquare(df=nu, size=n_samples)
    X = Z * np.sqrt(nu / chi_vals)[:, None]
    u1 = student_t.cdf(X[:, 0], df=nu)
    u2 = student_t.cdf(X[:, 1], df=nu)
    return np.clip(u1, 1e-6, 1.0 - 1e-6), np.clip(u2, 1e-6, 1.0 - 1e-6)


def copula_mc_var_es(h1, h2, rho, nu, marg_t_dfs, alpha_levels, n_paths, rng):
    u1, u2 = sample_student_t_copula(rho, nu, n_paths, rng)
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
# 4. BACKTESTING (CF-Rolling for DCC, MC for Copula)
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
    avg = n1 / n_blocks
    if alpha <= 0.01:
        thresholds = {'green': 4, 'yellow': 9}
    else:
        thresholds = {'green': int(250 * alpha * 1.5) + 1,
                      'yellow': int(250 * alpha * 2.5) + 1}
    if avg <= thresholds['green']:
        color = 'Green'
    elif avg <= thresholds['yellow']:
        color = 'Yellow'
    else:
        color = 'Red'
    return {'color': color, 'violations_per_block': float(avg),
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
    return {
        'kupiec': kupiec, 'christoffersen': cc, 'basel': basel,
        'es_test': es_test, 'trinity_pass': trinity_pass,
        'n_oos': n, 'violation_rate': float(kupiec['rate']),
    }


# ============================================================
# 5. DM tests (Harvey)
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
# 6. One-step-ahead recursive helpers for both marginals
# ============================================================
def a4f_onestep(params, r_prev, x2_prev, g_prev):
    """Given A4f params + previous state, return (h, tau, g) at step t."""
    theta0, theta1, omega, alpha_, gamma_, beta_ = params
    tau = max(theta0 + theta1 * x2_prev, 1e-16)
    u_prev = r_prev / np.sqrt(tau)
    ind = 1.0 if r_prev < 0 else 0.0
    g = max(omega + alpha_ * u_prev**2 + gamma_ * u_prev**2 * ind
            + beta_ * g_prev, 1e-16)
    h = max(tau * g, 1e-16)
    return h, tau, g


def prg_onestep(params, r_prev, x2_prev, g_prev, dow_t):
    """Given PRG params + previous state + current dow, return (h,tau,g)."""
    (theta0, theta1, delta_tue, delta_wed, delta_thu, delta_fri,
     omega, alpha_, gamma_, beta_) = params
    tau = theta0 + theta1 * x2_prev
    if dow_t == 1:
        tau += delta_tue
    elif dow_t == 2:
        tau += delta_wed
    elif dow_t == 3:
        tau += delta_thu
    elif dow_t == 4:
        tau += delta_fri
    tau = max(tau, 1e-16)
    u_prev = r_prev / np.sqrt(tau)
    ind = 1.0 if r_prev < 0 else 0.0
    g = max(omega + alpha_ * u_prev**2 + gamma_ * u_prev**2 * ind
            + beta_ * g_prev, 1e-16)
    h = max(tau * g, 1e-16)
    return h, tau, g


# ============================================================
# 7. OOS forecasting for one pair
# ============================================================
def oos_forecast_pair(ret1, ret2, x21, x22, dow, dates, oos_start,
                      pair_label, window=WINDOW, refit_every=REFIT_EVERY):
    """Fit 4 models for one asset pair. Returns per-model forecasts.

    - A4f marginals shared by M1, M2 (DCC-A4f, Copula-A4f)
    - PRG marginals shared by M3, M4 (DCC-PRG, Copula-PRG)
    - DCC fitted on A4f residuals → M1 and on PRG residuals → M3
    - Student-t Copula fitted on A4f residuals → M2 and on PRG residuals → M4
    """
    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret1)
    n_oos = T - oos_idx

    # Storage
    h1_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    h2_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    tau1_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    tau2_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    pvar_store = {m: np.full(n_oos, np.nan) for m in MODELS}

    copula_rho_a4f = np.full(n_oos, np.nan)
    copula_nu_a4f = np.full(n_oos, np.nan)
    copula_rho_prg = np.full(n_oos, np.nan)
    copula_nu_prg = np.full(n_oos, np.nan)
    lambda_L_a4f = np.full(n_oos, np.nan)
    lambda_L_prg = np.full(n_oos, np.nan)

    marg_t_df_1_a4f = np.full(n_oos, np.nan)
    marg_t_df_2_a4f = np.full(n_oos, np.nan)
    marg_t_df_1_prg = np.full(n_oos, np.nan)
    marg_t_df_2_prg = np.full(n_oos, np.nan)

    # PRG dummy param storage (take means over OOS for diagnostic)
    prg_deltas_history = []

    # State per-model
    state = {m: {
        'marg_params1': None,
        'marg_params2': None,
        'marg_type1': None,
        'marg_type2': None,
        'g1_prev': 1.0, 'g2_prev': 1.0,
        'last_fit': -refit_every,
    } for m in MODELS}
    # DCC state (2 copies: one on A4f residuals [M1] and one on PRG [M3])
    dcc_state = {
        'DCC-A4f-ASYM': {
            'a': 0.0, 'b': 0.0,
            'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
            'eps1_prev': 0.0, 'eps2_prev': 0.0,
            'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        },
        'DCC-PRG-ASYM': {
            'a': 0.0, 'b': 0.0,
            'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
            'eps1_prev': 0.0, 'eps2_prev': 0.0,
            'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        },
    }
    # Copula state
    copula_state = {
        'Copula-t-A4f-ASYM': {'params': None, 'df1': 10.0, 'df2': 10.0},
        'Copula-t-PRG-ASYM': {'params': None, 'df1': 10.0, 'df2': 10.0},
    }

    for i in range(n_oos):
        t = oos_idx + i
        if i % 300 == 0:
            elapsed = time.time() - START_TIME
            print(f"    [{pair_label}] OOS day {i}/{n_oos} ({elapsed:.0f}s)")

        need_refit = (i - state[MODELS[0]]['last_fit'] >= refit_every
                      or state[MODELS[0]]['marg_params1'] is None)

        if need_refit:
            s = max(0, t - window)
            tr1 = ret1[s:t]
            tr2 = ret2[s:t]
            tr_x21 = x21[s:t]
            tr_x22 = x22[s:t]
            tr_dow = dow[s:t]

            # A4f marginals
            a4f_1 = fit_a4f(tr1, tr_x21)
            a4f_2 = fit_a4f(tr2, tr_x22)
            eps_a4f_1 = tr1 / np.sqrt(a4f_1['h'])
            eps_a4f_2 = tr2 / np.sqrt(a4f_2['h'])

            # PRG marginals
            prg_1 = fit_prg(tr1, tr_x21, tr_dow)
            prg_2 = fit_prg(tr2, tr_x22, tr_dow)
            eps_prg_1 = tr1 / np.sqrt(prg_1['h'])
            eps_prg_2 = tr2 / np.sqrt(prg_2['h'])

            prg_deltas_history.append({
                'fit_day': i,
                'prg1_deltas': prg_1['delta_dummies'],
                'prg2_deltas': prg_2['delta_dummies'],
            })

            # DCC on A4f residuals (M1)
            dcc_a4f = fit_dcc(eps_a4f_1, eps_a4f_2)
            # DCC on PRG residuals (M3)
            dcc_prg = fit_dcc(eps_prg_1, eps_prg_2)

            # Student-t copula on A4f residuals (M2)
            df1_a4f = fit_marginal_t_df(eps_a4f_1)
            df2_a4f = fit_marginal_t_df(eps_a4f_2)
            u_a4f_1 = pit_student_t(eps_a4f_1, df1_a4f)
            u_a4f_2 = pit_student_t(eps_a4f_2, df2_a4f)
            cop_a4f = fit_student_t_copula(u_a4f_1, u_a4f_2)

            # Student-t copula on PRG residuals (M4)
            df1_prg = fit_marginal_t_df(eps_prg_1)
            df2_prg = fit_marginal_t_df(eps_prg_2)
            u_prg_1 = pit_student_t(eps_prg_1, df1_prg)
            u_prg_2 = pit_student_t(eps_prg_2, df2_prg)
            cop_prg = fit_student_t_copula(u_prg_1, u_prg_2)

            # Update state for all 4 models
            for m in ['DCC-A4f-ASYM', 'Copula-t-A4f-ASYM']:
                state[m]['marg_params1'] = a4f_1['params']
                state[m]['marg_params2'] = a4f_2['params']
                state[m]['marg_type1'] = 'A4f'
                state[m]['marg_type2'] = 'A4f'
                state[m]['g1_prev'] = float(a4f_1['g'][-1])
                state[m]['g2_prev'] = float(a4f_2['g'][-1])
                state[m]['last_fit'] = i
            for m in ['DCC-PRG-ASYM', 'Copula-t-PRG-ASYM']:
                state[m]['marg_params1'] = prg_1['params']
                state[m]['marg_params2'] = prg_2['params']
                state[m]['marg_type1'] = 'PRG'
                state[m]['marg_type2'] = 'PRG'
                state[m]['g1_prev'] = float(prg_1['g'][-1])
                state[m]['g2_prev'] = float(prg_2['g'][-1])
                state[m]['last_fit'] = i

            # DCC state
            for key, dcc in [('DCC-A4f-ASYM', dcc_a4f),
                             ('DCC-PRG-ASYM', dcc_prg)]:
                dcc_state[key]['a'] = dcc['a']
                dcc_state[key]['b'] = dcc['b']
                dcc_state[key]['qbar11'] = dcc['qbar11']
                dcc_state[key]['qbar22'] = dcc['qbar22']
                dcc_state[key]['qbar12'] = dcc['qbar12']
                if key == 'DCC-A4f-ASYM':
                    dcc_state[key]['eps1_prev'] = float(eps_a4f_1[-1])
                    dcc_state[key]['eps2_prev'] = float(eps_a4f_2[-1])
                else:
                    dcc_state[key]['eps1_prev'] = float(eps_prg_1[-1])
                    dcc_state[key]['eps2_prev'] = float(eps_prg_2[-1])
                dcc_state[key]['q11_prev'] = dcc['qbar11']
                dcc_state[key]['q22_prev'] = dcc['qbar22']
                dcc_state[key]['q12_prev'] = dcc['qbar12']

            # Copula state
            copula_state['Copula-t-A4f-ASYM']['params'] = cop_a4f
            copula_state['Copula-t-A4f-ASYM']['df1'] = df1_a4f
            copula_state['Copula-t-A4f-ASYM']['df2'] = df2_a4f
            copula_state['Copula-t-PRG-ASYM']['params'] = cop_prg
            copula_state['Copula-t-PRG-ASYM']['df1'] = df1_prg
            copula_state['Copula-t-PRG-ASYM']['df2'] = df2_prg

        # --- One-step recursive forecast ---
        r1_prev = ret1[t-1]
        r2_prev = ret2[t-1]
        x21_prev = x21[t-1]
        x22_prev = x22[t-1]
        dow_t = dow[t]

        for m in MODELS:
            p1 = state[m]['marg_params1']
            p2 = state[m]['marg_params2']
            if state[m]['marg_type1'] == 'A4f':
                h1_t, tau1_t, g1_t = a4f_onestep(
                    p1, r1_prev, x21_prev, state[m]['g1_prev'])
                h2_t, tau2_t, g2_t = a4f_onestep(
                    p2, r2_prev, x22_prev, state[m]['g2_prev'])
            else:
                h1_t, tau1_t, g1_t = prg_onestep(
                    p1, r1_prev, x21_prev, state[m]['g1_prev'], dow_t)
                h2_t, tau2_t, g2_t = prg_onestep(
                    p2, r2_prev, x22_prev, state[m]['g2_prev'], dow_t)
            state[m]['g1_prev'] = g1_t
            state[m]['g2_prev'] = g2_t
            h1_store[m][i] = h1_t
            h2_store[m][i] = h2_t
            tau1_store[m][i] = tau1_t
            tau2_store[m][i] = tau2_t

            s1 = np.sqrt(h1_t)
            s2 = np.sqrt(h2_t)

            if m in ['DCC-A4f-ASYM', 'DCC-PRG-ASYM']:
                dcc = dcc_state[m]
                a_d = dcc['a']
                b_d = dcc['b']
                c_d = 1.0 - a_d - b_d
                e1p = dcc['eps1_prev']
                e2p = dcc['eps2_prev']
                q11 = c_d * dcc['qbar11'] + a_d * e1p**2 + b_d * dcc['q11_prev']
                q22 = c_d * dcc['qbar22'] + a_d * e2p**2 + b_d * dcc['q22_prev']
                q12 = c_d * dcc['qbar12'] + a_d * e1p*e2p + b_d * dcc['q12_prev']
                denom = np.sqrt(q11 * q22)
                rho_t = q12 / denom if denom > 1e-20 else 0.0
                rho_t = np.clip(rho_t, -0.9999, 0.9999)
                rho_store[m][i] = rho_t
                # Correct DCC timing (Codex fix K1100f):
                # eps_prev in the next iteration must be ε_{t-1}=r_{t-1}/√h_{t-1}.
                # r_{t-1} = r1_prev (already used this step), h_{t-1} is the
                # h we computed in the PREVIOUS iteration (h1_store[m][i-1]).
                # At iteration i+1, r_prev_new = ret[t] (next day's r_{t-1})
                # and h_prev_new should be h_t (what we just computed here).
                # So we save h_t as the denominator-for-next-iter-eps, and the
                # actual ε update happens at top of next iteration using
                # ret[new_t - 1] which = ret[t] (now known).
                # Thus the current step's ε update uses h1_store[m][i-1]:
                if i > 0:
                    h1_prev = h1_store[m][i-1]
                    h2_prev = h2_store[m][i-1]
                    eps1_now = r1_prev / np.sqrt(h1_prev) if h1_prev > 1e-16 else 0.0
                    eps2_now = r2_prev / np.sqrt(h2_prev) if h2_prev > 1e-16 else 0.0
                else:
                    # First OOS step: use h_t as the only available denominator.
                    # This is a one-step approximation; impact negligible across
                    # 2000+ OOS days.
                    eps1_now = r1_prev / np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
                    eps2_now = r2_prev / np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
                dcc['eps1_prev'] = eps1_now
                dcc['eps2_prev'] = eps2_now
                dcc['q11_prev'] = q11
                dcc['q22_prev'] = q22
                dcc['q12_prev'] = q12
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * rho_t * s1 * s2
                pvar_store[m][i] = max(pv, 1e-16)
            else:
                # Copula models: rho from copula params (static between refits)
                cop = copula_state[m]['params']
                rho_t = cop['rho']
                rho_store[m][i] = rho_t
                if m == 'Copula-t-A4f-ASYM':
                    copula_rho_a4f[i] = cop['rho']
                    copula_nu_a4f[i] = cop['nu']
                    lambda_L_a4f[i] = t_copula_lambda(cop['rho'], cop['nu'])
                    marg_t_df_1_a4f[i] = copula_state[m]['df1']
                    marg_t_df_2_a4f[i] = copula_state[m]['df2']
                else:
                    copula_rho_prg[i] = cop['rho']
                    copula_nu_prg[i] = cop['nu']
                    lambda_L_prg[i] = t_copula_lambda(cop['rho'], cop['nu'])
                    marg_t_df_1_prg[i] = copula_state[m]['df1']
                    marg_t_df_2_prg[i] = copula_state[m]['df2']
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * rho_t * s1 * s2
                pvar_store[m][i] = max(pv, 1e-16)

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar_store,
        'h1': h1_store, 'h2': h2_store,
        'tau1': tau1_store, 'tau2': tau2_store,
        'rho': rho_store,
        'oos_dates': oos_dates,
        'oos_idx': oos_idx,
        'copula_rho_a4f': copula_rho_a4f,
        'copula_nu_a4f': copula_nu_a4f,
        'copula_rho_prg': copula_rho_prg,
        'copula_nu_prg': copula_nu_prg,
        'lambda_L_a4f': lambda_L_a4f,
        'lambda_L_prg': lambda_L_prg,
        'marg_t_df_1_a4f': marg_t_df_1_a4f,
        'marg_t_df_2_a4f': marg_t_df_2_a4f,
        'marg_t_df_1_prg': marg_t_df_1_prg,
        'marg_t_df_2_prg': marg_t_df_2_prg,
        'copula_state': copula_state,
        'prg_deltas_history': prg_deltas_history,
    }


def compute_copula_mc_var(forecasts, model_key, alpha_levels, n_paths):
    """Monte Carlo VaR/ES via Student-t copula + Student-t marginals."""
    h1 = forecasts['h1'][model_key]
    h2 = forecasts['h2'][model_key]
    n_oos = len(h1)
    var_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}
    es_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}

    if model_key == 'Copula-t-A4f-ASYM':
        rho_arr = forecasts['copula_rho_a4f']
        nu_arr = forecasts['copula_nu_a4f']
        df1_arr = forecasts['marg_t_df_1_a4f']
        df2_arr = forecasts['marg_t_df_2_a4f']
    else:
        rho_arr = forecasts['copula_rho_prg']
        nu_arr = forecasts['copula_nu_prg']
        df1_arr = forecasts['marg_t_df_1_prg']
        df2_arr = forecasts['marg_t_df_2_prg']

    for i in range(n_oos):
        if (not np.isfinite(h1[i]) or not np.isfinite(h2[i])
                or not np.isfinite(rho_arr[i]) or not np.isfinite(nu_arr[i])):
            continue
        if not (np.isfinite(df1_arr[i]) and np.isfinite(df2_arr[i])):
            continue
        sub_rng = np.random.default_rng(42 + i)
        mc = copula_mc_var_es(
            h1[i], h2[i], rho_arr[i], nu_arr[i],
            (float(df1_arr[i]), float(df2_arr[i])),
            alpha_levels, n_paths, sub_rng)
        for a in alpha_levels:
            var_out[a][i] = mc[a][0]
            es_out[a][i] = mc[a][1]
    return var_out, es_out


# ============================================================
# 8. DATA LOADING
# ============================================================
def load_data():
    import yfinance as yf
    tickers = ['SPY', 'ES=F', 'GLD', 'GC=F']
    print(f"Downloading prices: {tickers} + ^VIX ...")

    closes = {}
    for t in tickers:
        raw = yf.download(t, start=DATA_START, end=DATA_END,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.copy()
            raw.columns = raw.columns.get_level_values(0)
        closes[t] = raw['Close']
    vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                          auto_adjust=False, progress=False)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw = vix_raw.copy()
        vix_raw.columns = vix_raw.columns.get_level_values(0)

    df_dict = {t.lower().replace('=f', '_f'): closes[t] for t in tickers}
    df_dict['vix'] = vix_raw['Close']
    df = pd.DataFrame(df_dict).sort_index()

    df = df.dropna(subset=['spy', 'es_f', 'vix'])

    # Log returns
    col_map = {'SPY': 'spy', 'ES=F': 'es_f', 'GLD': 'gld', 'GC=F': 'gc_f'}
    for t, col in col_map.items():
        df[f'ret_{col}'] = np.log(df[col] / df[col].shift(1))
        df[f'simple_{col}'] = df[col].pct_change()

    # VIX^2 (annualized squared vol)
    df['vix2'] = (df['vix'] / 100.0) ** 2 / 252.0

    # Day-of-week: Monday=0 ... Friday=4
    df['dow'] = df.index.dayofweek.astype(np.int64)

    df = df.dropna(subset=['ret_spy', 'ret_es_f', 'vix2'])

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to "
          f"{df.index[-1].strftime('%Y-%m-%d')}")
    print(f"Total days: {len(df)}")
    for t, col in col_map.items():
        valid = df[col].notna().sum() if col in df else 0
        first = df[col].first_valid_index() if col in df else None
        print(f"  {t}: {valid} valid days, first={first}")
    # DOW distribution
    print("  Day-of-week distribution (Mon/Tue/Wed/Thu/Fri):",
          df['dow'].value_counts().sort_index().values)
    return df


# ============================================================
# 9. EVALUATE PAIR
# ============================================================
def evaluate_pair(pair_name, asset1, asset2, df):
    print(f"\n{'=' * 72}")
    print(f"PAIR: {pair_name} ({asset1} vs {asset2})")
    print(f"{'=' * 72}")

    col_map = {'SPY': 'spy', 'ES=F': 'es_f', 'GLD': 'gld', 'GC=F': 'gc_f'}
    a1_col = col_map[asset1]
    a2_col = col_map[asset2]
    required = [f'ret_{a1_col}', f'ret_{a2_col}',
                f'simple_{a1_col}', f'simple_{a2_col}',
                'vix2', 'dow']
    pair_df = df.dropna(subset=required).copy()
    print(f"  Pair sample: {len(pair_df)} days, "
          f"from {pair_df.index[0].strftime('%Y-%m-%d')} to "
          f"{pair_df.index[-1].strftime('%Y-%m-%d')}")

    ret1 = pair_df[f'ret_{a1_col}'].values
    ret2 = pair_df[f'ret_{a2_col}'].values
    x21 = pair_df['vix2'].values
    x22 = pair_df['vix2'].values  # Both use VIX² (US market regressor)
    dow = pair_df['dow'].values.astype(np.int64)
    dates = pair_df.index.values
    port_ret = (WEIGHTS[0] * pair_df[f'simple_{a1_col}'].values
                + WEIGHTS[1] * pair_df[f'simple_{a2_col}'].values)

    # Full-sample diagnostics
    corr = float(np.corrcoef(ret1, ret2)[0, 1])
    print(f"  Full-sample log-return corr: {corr:.6f}")
    print(f"  Full-sample basis diagnostic:")
    # basis proxy: log-diff between raw prices
    basis = np.log(pair_df[a2_col].values / pair_df[a1_col].values)
    print(f"    basis mean={basis.mean():.5f}, std={basis.std():.5f}, "
          f"min={basis.min():.4f}, max={basis.max():.4f}")

    # Regime correlation (VIX<20 calm; VIX>30 stressed)
    vix_vals = pair_df['vix'].values if 'vix' in pair_df else None
    if vix_vals is None:
        # reconstruct
        vix_vals = np.sqrt(x21 * 252.0) * 100.0
    calm_mask = vix_vals < 20
    stress_mask = vix_vals > 30
    if calm_mask.sum() > 20:
        calm_corr = float(np.corrcoef(ret1[calm_mask], ret2[calm_mask])[0, 1])
    else:
        calm_corr = np.nan
    if stress_mask.sum() > 20:
        stress_corr = float(np.corrcoef(ret1[stress_mask], ret2[stress_mask])[0, 1])
    else:
        stress_corr = np.nan
    print(f"    calm (VIX<20) corr: {calm_corr:.5f} (n={calm_mask.sum()})")
    print(f"    stressed (VIX>30) corr: {stress_corr:.5f} (n={stress_mask.sum()})")

    # Forecast
    t_start = time.time()
    forecasts = oos_forecast_pair(ret1, ret2, x21, x22, dow, dates, OOS_START,
                                   pair_name)
    oos_idx = forecasts['oos_idx']
    oos_dates = forecasts['oos_dates']
    n_oos = len(oos_dates)
    port_ret_oos = port_ret[oos_idx:]
    r2_port_oos = port_ret_oos ** 2
    dow_oos = dow[oos_idx:]

    print(f"  OOS period: "
          f"{pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} to "
          f"{pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')} "
          f"({n_oos} days, {time.time()-t_start:.0f}s fit)")

    # VaR/ES
    var_series_store = {m: {} for m in MODELS}
    es_series_store = {m: {} for m in MODELS}
    fz_mean_store = {m: {} for m in MODELS}
    fz_series_store = {m: {} for m in MODELS}
    models_results = {}

    # DCC models: CF-Rolling
    for m in ['DCC-A4f-ASYM', 'DCC-PRG-ASYM']:
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
            alpha_key = f"alpha_{alpha:.3f}"
            model_results['var_tests'][alpha_key] = trinity
            model_results['fz_score'][alpha_key] = {
                'mean': fz_mean, 'n': int(len(fz_s))}
        models_results[m] = model_results

    # Copula models: MC
    for m in ['Copula-t-A4f-ASYM', 'Copula-t-PRG-ASYM']:
        var_dict, es_dict = compute_copula_mc_var(
            forecasts, m, ALPHA_LEVELS, MC_PATHS)
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
                'mean': fz_mean, 'n': int(len(fz_s))}
        models_results[m] = model_results

    # Mean QLIKE
    qlike_means = {}
    for m in MODELS:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_port_oos)
        q = np.log(pv[valid]) + r2_port_oos[valid] / pv[valid]
        qlike_means[m] = float(np.mean(q))

    # DM QLIKE pairwise (all vs all)
    qlike_dm = {}
    pairs_qlike = [
        ('DCC-A4f-ASYM', 'Copula-t-A4f-ASYM'),       # copula vs base [H3]
        ('DCC-A4f-ASYM', 'DCC-PRG-ASYM'),            # PRG vs base [H2]
        ('DCC-A4f-ASYM', 'Copula-t-PRG-ASYM'),       # full vs base [H1]
        ('DCC-PRG-ASYM', 'Copula-t-PRG-ASYM'),       # copula gain on PRG
        ('Copula-t-A4f-ASYM', 'Copula-t-PRG-ASYM'),  # PRG gain on copula
        ('Copula-t-A4f-ASYM', 'DCC-PRG-ASYM'),       # copula vs PRG
    ]
    for m1, m2 in pairs_qlike:
        dm = dm_qlike(r2_port_oos, forecasts['pvar'][m1],
                      forecasts['pvar'][m2])
        qlike_dm[f"{m1}_vs_{m2}"] = dm

    # DM FZ (at each alpha level)
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
            fz_dm[alpha_key][f"{m1}_vs_{m2}"] = dm

    # Decomposition: PRG gain, Copula gain, interaction
    # Δ_PRG = QLIKE(A4f) - QLIKE(PRG)   (on DCC side)
    # Δ_Copula = QLIKE(DCC) - QLIKE(Copula)  (on A4f side)
    # Δ_Full = QLIKE(base M1) - QLIKE(M4)
    # Interaction = Δ_Full - Δ_PRG - Δ_Copula
    delta_prg = qlike_means['DCC-A4f-ASYM'] - qlike_means['DCC-PRG-ASYM']
    delta_copula = qlike_means['DCC-A4f-ASYM'] - qlike_means['Copula-t-A4f-ASYM']
    delta_full = qlike_means['DCC-A4f-ASYM'] - qlike_means['Copula-t-PRG-ASYM']
    interaction = delta_full - delta_prg - delta_copula

    # Periodic diagnostic: conditional variance by day-of-week
    periodic_diag = {}
    for m in MODELS:
        pv = forecasts['pvar'][m]
        diag = {}
        for d in range(5):
            mask = (dow_oos == d) & np.isfinite(pv)
            if mask.sum() > 5:
                diag[f'dow_{d}'] = float(np.mean(pv[mask]))
            else:
                diag[f'dow_{d}'] = np.nan
        periodic_diag[m] = diag

    # Copula stats
    cop_stats = {
        'a4f_copula': {
            'rho_mean': float(np.nanmean(forecasts['copula_rho_a4f'])),
            'rho_std': float(np.nanstd(forecasts['copula_rho_a4f'])),
            'rho_min': float(np.nanmin(forecasts['copula_rho_a4f'])),
            'rho_max': float(np.nanmax(forecasts['copula_rho_a4f'])),
            'nu_mean': float(np.nanmean(forecasts['copula_nu_a4f'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_a4f'])),
        },
        'prg_copula': {
            'rho_mean': float(np.nanmean(forecasts['copula_rho_prg'])),
            'rho_std': float(np.nanstd(forecasts['copula_rho_prg'])),
            'rho_min': float(np.nanmin(forecasts['copula_rho_prg'])),
            'rho_max': float(np.nanmax(forecasts['copula_rho_prg'])),
            'nu_mean': float(np.nanmean(forecasts['copula_nu_prg'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_prg'])),
        },
    }

    # PRG dummies summary
    prg1_last = (forecasts['prg_deltas_history'][-1]['prg1_deltas']
                 if forecasts['prg_deltas_history'] else [np.nan]*4)
    prg2_last = (forecasts['prg_deltas_history'][-1]['prg2_deltas']
                 if forecasts['prg_deltas_history'] else [np.nan]*4)

    # Print summary
    print(f"\n  --- {pair_name} Summary ---")
    print(f"    Mean QLIKE:")
    for m in MODELS:
        q = qlike_means[m]
        t_pass_01 = models_results[m]['var_tests']['alpha_0.010']['trinity_pass']
        fz_01 = fz_mean_store[m][0.01]
        print(f"      {m}: QLIKE={q:.5f}, Trinity1%={t_pass_01}, FZ1%={fz_01:.4f}")
    print(f"    DM QLIKE (positive = right-side of 'vs' better):")
    for k, dm in qlike_dm.items():
        sig = ("***" if dm['significant_harvey']
               else ("*" if dm['p_value'] < 0.05 else ""))
        print(f"      {k}: t={dm['t_stat']:+.3f} {sig}")
    print(f"    Decomposition:")
    print(f"      Δ_PRG (copula-side mean QLIKE improvement)  = {delta_prg:+.5f}")
    print(f"      Δ_Copula (A4f→Copula) = {delta_copula:+.5f}")
    print(f"      Δ_Full (M1→M4)        = {delta_full:+.5f}")
    print(f"      Interaction          = {interaction:+.5f} "
          f"(positive => PRG+copula synergy)")
    print(f"    PRG dummies (last fit window, asset1): "
          f"Tue={prg1_last[0]:+.2e}, Wed={prg1_last[1]:+.2e}, "
          f"Thu={prg1_last[2]:+.2e}, Fri={prg1_last[3]:+.2e}")
    print(f"    PRG dummies (last fit, asset2): "
          f"Tue={prg2_last[0]:+.2e}, Wed={prg2_last[1]:+.2e}, "
          f"Thu={prg2_last[2]:+.2e}, Fri={prg2_last[3]:+.2e}")
    print(f"    Copula λ_L A4f={cop_stats['a4f_copula']['lambda_L_mean']:.4f}, "
          f"PRG={cop_stats['prg_copula']['lambda_L_mean']:.4f}")

    return {
        'pair_name': pair_name,
        'asset1': asset1, 'asset2': asset2,
        'n_oos': int(n_oos),
        'full_sample_corr': corr,
        'calm_corr': calm_corr,
        'stress_corr': stress_corr,
        'basis_stats': {
            'mean': float(basis.mean()),
            'std': float(basis.std()),
            'min': float(basis.min()),
            'max': float(basis.max()),
        },
        'models': models_results,
        'dm_qlike': qlike_dm,
        'dm_fz': fz_dm,
        'mean_qlike': qlike_means,
        'copula_stats': cop_stats,
        'periodic_variance_by_dow': periodic_diag,
        'decomposition': {
            'delta_PRG': float(delta_prg),
            'delta_Copula': float(delta_copula),
            'delta_Full': float(delta_full),
            'interaction': float(interaction),
        },
        'prg_dummies_last_asset1': prg1_last,
        'prg_dummies_last_asset2': prg2_last,
        'oos_dates_first': pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d'),
        'oos_dates_last': pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d'),
        # Private (plotting)
        '_fz_mean_store': fz_mean_store,
        '_lambda_L_a4f': forecasts['lambda_L_a4f'],
        '_lambda_L_prg': forecasts['lambda_L_prg'],
        '_oos_dates': oos_dates,
        '_port_ret_oos': port_ret_oos,
        '_pvar': forecasts['pvar'],
        '_var_series_store': var_series_store,
        '_dow_oos': dow_oos,
        '_pair_df': pair_df,
        '_fit_time_s': float(time.time() - t_start),
    }


# ============================================================
# 10. PLOTTING
# ============================================================
def plot_results(pair_results):
    # 1. 4-model DM vs DCC-A4f baseline (per pair)
    fig, axes = plt.subplots(1, len(pair_results), figsize=(6*len(pair_results), 5),
                              squeeze=False)
    for ax_idx, (pair_name, pr) in enumerate(pair_results.items()):
        ax = axes[0, ax_idx]
        pairs_labels = ['vs Copula-t\n(H3)', 'vs DCC-PRG\n(H2)',
                        'vs Copula-PRG\n(H1)']
        dm_vals = [
            pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM']['t_stat'],
            pr['dm_qlike']['DCC-A4f-ASYM_vs_DCC-PRG-ASYM']['t_stat'],
            pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-t-PRG-ASYM']['t_stat'],
        ]
        colors = ['#5DA5DA' if abs(v) < 3 else ('#60BD68' if v > 0 else '#F15854')
                  for v in dm_vals]
        bars = ax.bar(pairs_labels, dm_vals, color=colors)
        ax.axhline(y=3.0, color='gray', linestyle='--', alpha=0.5,
                    label='Harvey |t|=3')
        ax.axhline(y=-3.0, color='gray', linestyle='--', alpha=0.5)
        ax.axhline(y=0, color='black', linewidth=0.5)
        ax.set_ylabel("DM t-stat (positive = alt model better)")
        ax.set_title(f"{pair_name}: DM vs DCC-A4f baseline")
        ax.legend(loc='lower right')
        for bar, v in zip(bars, dm_vals):
            ax.text(bar.get_x() + bar.get_width()/2, v,
                    f"{v:+.2f}", ha='center',
                    va='bottom' if v >= 0 else 'top', fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1100f_4model_dm.png'),
                 dpi=120, bbox_inches='tight')
    plt.close()

    # 2. Periodic seasonality: conditional variance by day-of-week (M3 PRG)
    fig, axes = plt.subplots(1, len(pair_results), figsize=(6*len(pair_results), 5),
                              squeeze=False)
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    for ax_idx, (pair_name, pr) in enumerate(pair_results.items()):
        ax = axes[0, ax_idx]
        model_colors = {
            'DCC-A4f-ASYM': '#5DA5DA',
            'Copula-t-A4f-ASYM': '#60BD68',
            'DCC-PRG-ASYM': '#FAA43A',
            'Copula-t-PRG-ASYM': '#F15854',
        }
        width = 0.2
        x = np.arange(5)
        for i, m in enumerate(MODELS):
            vals = [pr['periodic_variance_by_dow'][m][f'dow_{d}']*10000 for d in range(5)]
            ax.bar(x + i*width - 1.5*width, vals, width,
                    label=m.replace('-ASYM', ''), color=model_colors[m])
        ax.set_xticks(x)
        ax.set_xticklabels(dow_names)
        ax.set_ylabel("Mean conditional variance (×10⁴)")
        ax.set_title(f"{pair_name}: portfolio conditional variance by DOW")
        ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1100f_periodic_seasonality.png'),
                 dpi=120, bbox_inches='tight')
    plt.close()

    # 3. Spot-futures basis time series (SPY-ES only)
    for pair_name, pr in pair_results.items():
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        pair_df = pr['_pair_df']
        col_map = {'SPY': 'spy', 'ES=F': 'es_f', 'GLD': 'gld', 'GC=F': 'gc_f'}
        a1 = col_map[pr['asset1']]
        a2 = col_map[pr['asset2']]
        basis = np.log(pair_df[a2].values / pair_df[a1].values)
        ax1.plot(pair_df.index, basis, color='black', linewidth=0.7)
        ax1.set_ylabel(f"log({pr['asset2']} / {pr['asset1']}) [basis]")
        ax1.set_title(f"{pair_name}: spot-futures basis + copula ρ (OOS)")
        ax1.grid(True, alpha=0.3)
        # Secondary: copula rho OOS (A4f)
        oos_dates = pr['_oos_dates']
        rho_a4f = pr.get('_rho_a4f', None)
        try:
            rho_series = pd.Series(
                [pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM'].get('t_stat')]
                if False else [], index=[])
        except Exception:
            rho_series = None
        # Plot copula ρ for A4f model as OOS overlay
        lam_a = pr['_lambda_L_a4f']
        lam_p = pr['_lambda_L_prg']
        ax2.plot(oos_dates, lam_a, label='λ_L (A4f)', alpha=0.7)
        ax2.plot(oos_dates, lam_p, label='λ_L (PRG)', alpha=0.7)
        ax2.set_ylabel("Copula lower tail dependence λ_L")
        ax2.set_xlabel("Date")
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(SCRIPT_DIR,
                                  f'k1100f_basis_{pair_name}.png'),
                     dpi=120, bbox_inches='tight')
        plt.close()

    # 4. Copula gain decomposition (bar chart)
    fig, ax = plt.subplots(figsize=(8, 5))
    pairs = list(pair_results.keys())
    dec_labels = ['Δ_PRG', 'Δ_Copula', 'Δ_Full', 'Interaction']
    width = 0.2
    x = np.arange(len(dec_labels))
    pair_colors = ['#5DA5DA', '#60BD68']
    for i, p in enumerate(pairs):
        d = pair_results[p]['decomposition']
        vals = [d['delta_PRG'], d['delta_Copula'], d['delta_Full'],
                d['interaction']]
        ax.bar(x + i*width, vals, width, label=p, color=pair_colors[i])
    ax.set_xticks(x + width/2)
    ax.set_xticklabels(dec_labels)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_ylabel("Mean QLIKE improvement (positive = better)")
    ax.set_title("K1100f: PRG vs Copula vs Interaction decomposition")
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1100f_copula_gain_decomposition.png'),
                 dpi=120, bbox_inches='tight')
    plt.close()

    print(f"  Saved 4 charts to {SCRIPT_DIR}")


# ============================================================
# 11. MAIN
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
    for pair_name, a1, a2 in PAIRS:
        elapsed = time.time() - START_TIME
        print(f"\n>>> [{elapsed:.0f}s elapsed] Starting pair {pair_name} ...")
        pair_results[pair_name] = evaluate_pair(pair_name, a1, a2, df)

        # Checkpoint save after each pair
        results_safe = {pn: to_json_safe(pr)
                         for pn, pr in pair_results.items()}
        with open(RESULTS_PATH, 'w') as f:
            json.dump({
                'experiment_id': EXPERIMENT_ID,
                'pair_results': results_safe,
                'config': {
                    'oos_start': OOS_START,
                    'window': WINDOW, 'refit_every': REFIT_EVERY,
                    'alpha_levels': ALPHA_LEVELS,
                    'weights': WEIGHTS.tolist(),
                    'mc_paths': MC_PATHS, 'seed': 42,
                },
                'timestamp_partial': datetime.now(timezone.utc).isoformat(),
                'pairs_done': list(pair_results.keys()),
            }, f, indent=2)
        print(f"  Checkpoint saved ({len(pair_results)}/{len(PAIRS)} pairs)")

    # Cross-pair summary
    print(f"\n{'=' * 72}")
    print(f"K1100f CROSS-PAIR VERDICT")
    print(f"{'=' * 72}")

    verdict_table = []
    any_h1_passes = False
    for pair_name, pr in pair_results.items():
        dm_h3 = pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM']
        dm_h2 = pr['dm_qlike']['DCC-A4f-ASYM_vs_DCC-PRG-ASYM']
        dm_h1 = pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-t-PRG-ASYM']
        h1_pass = dm_h1['t_stat'] > 3.0
        if h1_pass:
            any_h1_passes = True
        row = {
            'pair': pair_name,
            'n_oos': pr['n_oos'],
            'corr_full': pr['full_sample_corr'],
            'corr_stressed': pr['stress_corr'],
            'dm_t_copula_vs_base_H3': dm_h3['t_stat'],
            'dm_t_prg_vs_base_H2': dm_h2['t_stat'],
            'dm_t_full_vs_base_H1': dm_h1['t_stat'],
            'h1_harvey_sig': h1_pass,
            'h2_harvey_sig': abs(dm_h2['t_stat']) > 3,
            'h3_harvey_sig': abs(dm_h3['t_stat']) > 3,
            'delta_PRG': pr['decomposition']['delta_PRG'],
            'delta_Copula': pr['decomposition']['delta_Copula'],
            'delta_Full': pr['decomposition']['delta_Full'],
            'interaction': pr['decomposition']['interaction'],
        }
        verdict_table.append(row)

    print(f"\n{'Pair':<10} {'corr':>7} {'corr-S':>7} "
          f"{'H3(cop)':>9} {'H2(prg)':>9} {'H1(full)':>10} "
          f"{'Δ_PRG':>9} {'Δ_Cop':>9} {'Δ_Full':>9} {'Int':>9}")
    for r in verdict_table:
        print(f"{r['pair']:<10} {r['corr_full']:>+7.4f} "
              f"{r['corr_stressed']:>+7.4f} "
              f"{r['dm_t_copula_vs_base_H3']:>+9.3f} "
              f"{r['dm_t_prg_vs_base_H2']:>+9.3f} "
              f"{r['dm_t_full_vs_base_H1']:>+10.3f} "
              f"{r['delta_PRG']:>+9.5f} "
              f"{r['delta_Copula']:>+9.5f} "
              f"{r['delta_Full']:>+9.5f} "
              f"{r['interaction']:>+9.5f}")

    verdict = {
        'any_h1_passes_harvey': any_h1_passes,
        'verdict_per_pair': verdict_table,
        'overall_verdict': (
            "PRG+COPULA VALIDATED (H1 passes on at least 1 pair)"
            if any_h1_passes else
            "PRG+COPULA NULL on US spot-futures — Paper 3 needs reframing "
            "as Taiwan market finding"
        ),
    }

    print(f"\n  OVERALL VERDICT: {verdict['overall_verdict']}")

    # Plotting
    plot_results(pair_results)

    # Final save
    final_results = {
        'experiment_id': EXPERIMENT_ID,
        'pair_results': {pn: to_json_safe(pr)
                          for pn, pr in pair_results.items()},
        'cross_pair_verdict': verdict,
        'config': {
            'oos_start': OOS_START, 'window': WINDOW,
            'refit_every': REFIT_EVERY, 'alpha_levels': ALPHA_LEVELS,
            'weights': WEIGHTS.tolist(), 'mc_paths': MC_PATHS,
            'seed': 42,
        },
        'metadata': {
            'experiment_id': EXPERIMENT_ID,
            'parent_experiments': ['K1100', 'K1100b', 'K1092', 'K1041',
                                    'K868', 'K874c', 'K874d', 'K880'],
            'data_source': 'yfinance (SPY, ES=F, GLD, GC=F, ^VIX)',
            'data_period': f"{DATA_START} to {DATA_END}",
            'oos_start': OOS_START,
            'pairs': [p[0] for p in PAIRS],
            'proposer': 'Claude autonomous-research (via K1100b Paper 3 reassessment)',
            'runtime_seconds': float(time.time() - START_TIME),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'models': MODELS,
            'references': [
                'K1100, K1100b (parent copula null results)',
                'Bollerslev & Ghysels (1996) JBES periodic GARCH',
                'Patton (2006) IER; Jondeau & Rockinger (2006) JIMF',
                'Christoffersen et al. (2012) RFS copula tail',
                'Lai (2024) APFM 31(2) PRS copula hedging (user paper)',
                'Harvey et al. (2016) JBES DM robust',
                'Fissler & Ziegel (2016) Ann Stat joint VaR-ES',
            ],
            'hypotheses': {
                'H1': 'Copula-PRG (M4) > DCC-A4f (M1) Harvey |t|>3',
                'H2': 'DCC-PRG (M3) > DCC-A4f (M1) Harvey |t|>3',
                'H3': 'Copula-A4f (M2) > DCC-A4f (M1) Harvey |t|>3',
                'H4': 'Interaction > 0 (PRG+copula synergy)',
            },
        },
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(final_results, f, indent=2)
    print(f"\n  Final results saved: {RESULTS_PATH}")
    print(f"  Total runtime: {time.time()-START_TIME:.0f}s")


if __name__ == "__main__":
    main()
