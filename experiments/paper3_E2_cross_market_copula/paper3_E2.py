#!/usr/bin/env python3
"""
Paper3_E2: Copula-GARCH on Cross-Market Equity Index Pairs (lambda_L threshold)
==============================================================================
[Boss directive 2026-05-29 / Claude design / Claude execute]

Parent: K1100b (ETF-level asset-class copula advantage), Paper3_E1 (individual
stocks, completed 2026-05-29: NULL verdict, 12/12 pairs no Harvey advantage).
Related: K1100/K1142/K1172 — Paper 3 reframe = asset-class-specific copula
advantage; boss 2026-05-29 directive = expand validation to individual stocks
(E1 ✅ NULL), other equity markets (E2 — this), commodities (E3) before body
rewrite.

Motivation:
  E1 (individual US stocks within one country) showed Copula-GARCH NULL even
  at low lambda_L (~0.01-0.20). Boss directive: test whether cross-MARKET
  equity pairs (different countries / time zones / regulatory regimes)
  exhibit copula advantage. Hypothesis: lower trading-hour overlap +
  segmented market microstructure → lambda_L < 0.2 and DCC fails to capture
  asymmetric crash co-movement → Copula-GARCH PASS.

  H1 (cross-developed-region): SPY-STOXX50, SPY-N225 — high diversification
      but moderate crisis comovement. Expected lambda_L 0.15-0.30. Test
      whether DCC already captures or copula adds tail value.
  H2 (developed-vs-emerging): SPY-HSI, SPY-0050.TW, STOXX50-HSI — low
      day-to-day overlap, asymmetric crisis transmission. Expected
      lambda_L < 0.20 + Copula advantage candidate.
  H3 (asia-intraregional): 0050.TW-HSI, HSI-N225 — partial overlap with
      Asian session synchronization. Lambda_L moderate.
  H4 (cross-pair scatter): replicate E1 H3 — does DM t-stat fall as
      lambda_L rises? With cross-market pairs (more lambda_L heterogeneity
      than within-US-stocks E1) the scatter should resolve cleaner.

Design: 10 pairs x 3 models (DCC-A4f-ASYM, Copula-t, Clayton) = 30 cells.

Marginal: all markets A4f with VIX^2 regressor (VIX is global systemic
factor — Christoffersen et al. 2012 RFS; same rationale as E1).
A4f-ASYM per K1092 / K1100b.

Markets (5):
  - SPY        (US S&P 500 ETF — proxy for ^GSPC; same-time-zone benchmark)
  - 0050.TW    (Taiwan 50 ETF; emerging-Asia, ~13hr offset from SPY)
  - ^HSI       (Hang Seng; HK developed-Asia)
  - ^N225      (Nikkei 225; Japan developed-Asia)
  - ^STOXX50E  (EuroStoxx 50; developed-Europe, ~6hr offset from SPY)
                Paper 9 forensic known unstable in yfinance → FEZ ETF
                fallback auto-detected if ^STOXX50E returns insufficient.

Pairs (region classification):
  Developed cross-region (expected moderate lambda_L):
    SPY-STOXX50, SPY-N225, STOXX50-N225
  Developed-vs-emerging Asia (expected low lambda_L, copula candidate):
    SPY-HSI, SPY-0050.TW, STOXX50-HSI, STOXX50-0050.TW
  Asia intraregional (expected mixed lambda_L):
    HSI-N225, 0050.TW-HSI, 0050.TW-N225

Evaluation (identical to E1):
  - Portfolio VaR/ES via CF-Rolling (DCC) or MC (copula), alpha=1%, 2.5%
  - Trinity (Kupiec + CC + Basel) + FZ + DM QLIKE (HLN-corrected DM)
  - Cross-pair scatter: DM t vs mean lambda_L (H4)

Data: yfinance 5 indices/ETFs + ^VIX (2010-01-01 to 2026-05-28).
  Calendar-day INNER JOIN across all 5 markets (drop non-overlap holidays);
  expect ~3500-3800 obs after intersection.
  OOS: 2015-06-01 onwards (~2700 days per pair), window=1250, refit=63,
  seed=42. MC paths: 5000/day.

Runtime estimate: K1100b 5 pairs ~28 min; E1 12 pairs ~70 min. E2 10 pairs
~60-90 min plus 5-market data fetch buffer. Boss directive 3-4 hr estimate
covers MLE multistart + plot generation comfortably.

Data caveats:
  - 0050.TW: TWSE, start 2003-06-30; trading hours non-overlapping with SPY
    (use calendar-day overlap, NO synthetic time-zone alignment).
  - ^HSI: yfinance early-year thin / zero rows possible; FALLBACK candidate
    EWH ETF if first attempt yields <100 valid rows pre-2012.
  - ^N225: usually clean.
  - ^STOXX50E: Paper 9 known sketchy; try first; if rows <1000 in 2010-2026
    inner join → fall back to FEZ ETF and log it.
  - VIX: ^VIX global risk barometer; same vix2 regressor for ALL markets'
    marginals (Christoffersen et al. 2012 rationale).
  - Inner join: post-drop expected ~3400-3800 obs (US+Asia+EU calendar
    triple-intersect with VIX availability).

Lookahead guard: signal at t-1, return at t (identical to E1 recursion).
MLE seed=42, MC paths 5000 with sub-rng seeded by 42+i.

References (additive to E1):
  - Karolyi & Stulz (1996). JF — cross-country equity comovement.
  - Forbes & Rigobon (2002). JF — contagion vs interdependence.
  - Longin & Solnik (2001). JF — extreme correlation int'l equity.
  - K1100b (ETF-level asset-class copula advantage).
  - Paper3_E1 results (NULL verdict on within-US-stock pairs).

Author: VolPred Research System
Date: 2026-05-29 (Paper 3 reframe E2 expansion per boss directive)
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
EXPERIMENT_ID = "Paper3_E2"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'paper3_E2_results.json')

# Configuration (identical to E1)
DATA_START = '2010-01-01'
DATA_END = '2026-05-28'
OOS_START = '2015-06-01'
WINDOW = 1250
REFIT_EVERY = 63
ALPHA_LEVELS = [0.025, 0.01]
WEIGHTS = np.array([0.5, 0.5])
MC_PATHS = 5000

# Smoke-test mode (set via env SMOKE_TEST=1)
SMOKE_TEST = os.environ.get('SMOKE_TEST', '0') == '1'

# Market ticker registry
# Map: short_name -> (yf_ticker, fallback_ticker, region_class)
# short_name used as column key (safe for f-string interpolation)
MARKETS = {
    'SPY':      ('SPY', None, 'developed_us'),
    'TW0050':   ('0050.TW', None, 'emerging_asia'),
    'HSI':      ('^HSI', 'EWH', 'developed_asia_hk'),
    'N225':     ('^N225', 'EWJ', 'developed_asia_jp'),
    'STOXX50':  ('^STOXX50E', 'FEZ', 'developed_eu'),
}

# Pairs: (name, asset1_short, asset2_short, regressor1_col, regressor2_col)
# region classification embedded in name for downstream analysis.
PAIRS = [
    # Developed cross-region (expected moderate λ_L)
    ('SPY-STOXX50',     'SPY',     'STOXX50', 'vix2', 'vix2'),
    ('SPY-N225',        'SPY',     'N225',    'vix2', 'vix2'),
    ('STOXX50-N225',    'STOXX50', 'N225',    'vix2', 'vix2'),
    # Developed-vs-emerging Asia (expected low λ_L, copula candidate)
    ('SPY-HSI',         'SPY',     'HSI',     'vix2', 'vix2'),
    ('SPY-TW0050',      'SPY',     'TW0050',  'vix2', 'vix2'),
    ('STOXX50-HSI',     'STOXX50', 'HSI',     'vix2', 'vix2'),
    ('STOXX50-TW0050',  'STOXX50', 'TW0050',  'vix2', 'vix2'),
    # Asia intraregional (mixed λ_L)
    ('HSI-N225',        'HSI',     'N225',    'vix2', 'vix2'),
    ('TW0050-HSI',      'TW0050',  'HSI',     'vix2', 'vix2'),
    ('TW0050-N225',     'TW0050',  'N225',    'vix2', 'vix2'),
]

# Region classification per pair (for downstream H1/H2/H3 grouping)
PAIR_REGION_CLASS = {
    'SPY-STOXX50':    'developed_cross_region',
    'SPY-N225':       'developed_cross_region',
    'STOXX50-N225':   'developed_cross_region',
    'SPY-HSI':        'developed_vs_emerging_asia',
    'SPY-TW0050':     'developed_vs_emerging_asia',
    'STOXX50-HSI':    'developed_vs_emerging_asia',
    'STOXX50-TW0050': 'developed_vs_emerging_asia',
    'HSI-N225':       'asia_intraregional',
    'TW0050-HSI':     'asia_intraregional',
    'TW0050-N225':    'asia_intraregional',
}

MODELS = [
    'DCC-A4f-ASYM',
    'Copula-t-A4f-ASYM',
    'Copula-Clayton-A4f-ASYM',
]

if SMOKE_TEST:
    # Smoke-test: 1 pair × Copula-t only, 100 obs window, very small
    PAIRS = [PAIRS[4]]  # SPY-TW0050 (cross-region, expected to exercise data path)
    MODELS_FILTER = ['Copula-t-A4f-ASYM']
    WINDOW = 100
    REFIT_EVERY = 50
    MC_PATHS = 200
    print("*** SMOKE TEST MODE: 1 pair, copula-t only, 100-obs window ***")
else:
    MODELS_FILTER = MODELS

print("=" * 72)
print(f"{EXPERIMENT_ID}: Copula-GARCH on Cross-Market Equity Pairs (λ_L threshold)")
print(f"  {len(PAIRS)} pairs x {len(MODELS_FILTER)} models = "
      f"{len(PAIRS)*len(MODELS_FILTER)} cells")
print(f"  Markets: {list(MARKETS.keys())}")
print(f"  OOS from {OOS_START}, window={WINDOW}, refit={REFIT_EVERY}d, MC={MC_PATHS}")
print("=" * 72)


# ============================================================
# 1. NUMBA KERNELS (identical to E1 / K1100)
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
# 2. MARGINAL + DCC FITTING (identical to E1 / K1100)
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
# 3. COPULA FITTING (identical to E1 / K1100)
# ============================================================
def fit_marginal_t_df(z):
    def neg_ll(nu):
        if nu <= 2.05 or nu > 100:
            return 1e10
        scale = np.sqrt((nu - 2.0) / nu)
        ll = np.sum(student_t.logpdf(z / scale, df=nu) - np.log(scale))
        return -ll if np.isfinite(ll) else 1e10

    best_nu, best_ll = 10.0, 1e10
    try:
        res = optimize.minimize_scalar(neg_ll, bounds=(2.1, 80.0),
                                       method='bounded',
                                       options={'xatol': 1e-4})
        if res.fun < best_ll:
            best_ll = res.fun
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
    if theta <= 1e-4 or theta > 30.0:
        return 1e10
    try:
        log_u1 = np.log(u1)
        log_u2 = np.log(u2)
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
    tau = stats.kendalltau(u1, u2).statistic
    if not np.isfinite(tau) or tau <= 0:
        theta_init = 0.05
    else:
        theta_init = max(0.05, 2.0 * tau / (1.0 - tau))

    try:
        res = optimize.minimize_scalar(
            clayton_copula_nll,
            bounds=(0.01, 20.0),
            method='bounded',
            args=(u1, u2),
            options={'xatol': 1e-4})
    except Exception:
        return {'theta': theta_init, 'converged': False}
    theta_hat = float(res.x)
    lambda_L = 2.0**(-1.0 / theta_hat) if theta_hat > 0.01 else 0.0
    return {'theta': theta_hat, 'lambda_L': float(lambda_L),
            'converged': bool(res.success),
            'nll': float(res.fun)}


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


def sample_clayton_copula(theta, n_samples, rng):
    if theta <= 0.01:
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
    if copula_type == 't':
        rho = copula_params['rho']
        nu_c = copula_params['nu']
        u1, u2 = sample_student_t_copula(rho, nu_c, n_paths, rng)
    elif copula_type == 'clayton':
        theta = copula_params['theta']
        u1, u2 = sample_clayton_copula(theta, n_paths, rng)
    else:
        raise ValueError(f"Unknown copula: {copula_type}")

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
# 4. BACKTESTING (identical to E1 / K1100)
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
# 5. DM TESTS (identical to E1 / K1100)
# ============================================================
def hln_small_sample_factor(n, h=1):
    if n <= 1:
        return 1.0
    return np.sqrt((n + 1 - 2 * h + (h * (h - 1)) / n) / n)


def dm_test(loss_series_1, loss_series_2, horizon=1):
    valid = np.isfinite(loss_series_1) & np.isfinite(loss_series_2)
    l1 = loss_series_1[valid]
    l2 = loss_series_2[valid]
    d = l1 - l2
    n = len(d)
    if n < 10:
        return {'t_stat': 0.0, 'p_value': 1.0, 'mean_loss_diff': 0.0,
                'n': n, 'significant_harvey': False,
                't_stat_raw': 0.0, 'hln_factor': 1.0,
                'critical_value': np.nan}
    d_bar = np.mean(d)
    max_lag = max(1, int(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * w * gamma_k
    se = np.sqrt(nw_var / n) if nw_var > 0 else 1e-12
    t_stat_raw = d_bar / se if se > 1e-12 else 0.0
    hln_factor = hln_small_sample_factor(n, h=horizon)
    t_stat = t_stat_raw * hln_factor
    df = max(n - 1, 1)
    p_val = 2 * student_t.cdf(-abs(t_stat), df=df)
    critical_value = student_t.ppf(0.975, df=df)
    return {'t_stat': float(t_stat), 'p_value': float(p_val),
            'mean_loss_diff': float(d_bar), 'n': int(n),
            'significant_harvey': bool(abs(t_stat) > critical_value),
            't_stat_raw': float(t_stat_raw),
            'hln_factor': float(hln_factor),
            'critical_value': float(critical_value)}


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
# 6. OOS FORECASTING for ONE pair (identical to E1, MODELS_FILTER used)
# ============================================================
def oos_forecast_pair(ret1, ret2, x21, x22, dates, oos_start,
                      pair_label, window=None, refit_every=None):
    """Fit DCC-A4f-ASYM + Copula-t + Clayton for one asset pair.

    Lookahead guard: signal/forecast use observations through t-1; portfolio
    return realized at t (returns indexed at t). Recursive recursion uses
    ret[t-1] / x2[t-1] only.
    """
    if window is None:
        window = WINDOW
    if refit_every is None:
        refit_every = REFIT_EVERY

    oos_idx = np.searchsorted(dates, np.datetime64(oos_start))
    T = len(ret1)
    n_oos = T - oos_idx

    h1_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    h2_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    rho_store = {m: np.full(n_oos, np.nan) for m in MODELS}
    pvar_store = {m: np.full(n_oos, np.nan) for m in MODELS}

    copula_t_rho = np.full(n_oos, np.nan)
    copula_t_nu = np.full(n_oos, np.nan)
    copula_clayton_theta = np.full(n_oos, np.nan)
    lambda_L_t = np.full(n_oos, np.nan)
    lambda_L_clayton = np.full(n_oos, np.nan)

    copula_t_params_t = [None] * n_oos
    copula_clayton_params_t = [None] * n_oos
    marg_t_df_1 = np.full(n_oos, np.nan)
    marg_t_df_2 = np.full(n_oos, np.nan)

    state = {m: {
        'h1_prev': np.nan, 'h2_prev': np.nan,
        'g1_prev': np.nan, 'g2_prev': np.nan,
        'marg1_p': None, 'marg2_p': None,
        'dcc_a': 0.0, 'dcc_b': 0.0,
        'qbar11': 1.0, 'qbar22': 1.0, 'qbar12': 0.0,
        'last_fit': -refit_every,
        'eps1_prev': 0.0, 'eps2_prev': 0.0,
        'q11_prev': 1.0, 'q22_prev': 1.0, 'q12_prev': 0.0,
        'copula_t': None, 'copula_clayton': None,
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
            s = max(0, t - window)
            tr1 = ret1[s:t]
            tr2 = ret2[s:t]
            tr_x21 = x21[s:t]
            tr_x22 = x22[s:t]

            # A4f marginals (shared)
            a4f_1 = fit_a4f(tr1, tr_x21)
            a4f_2 = fit_a4f(tr2, tr_x22)
            eps_1 = tr1 / np.sqrt(a4f_1['h'])
            eps_2 = tr2 / np.sqrt(a4f_2['h'])

            # DCC (ASYM)
            dcc = fit_dcc(eps_1, eps_2)

            # Copula marginals
            df_1 = fit_marginal_t_df(eps_1)
            df_2 = fit_marginal_t_df(eps_2)
            u_1 = pit_student_t(eps_1, df_1)
            u_2 = pit_student_t(eps_2, df_2)

            cop_t = fit_student_t_copula(u_1, u_2)
            cop_clayton = fit_clayton_copula(u_1, u_2)

            for m in MODELS:
                state[m]['marg1_p'] = ('A4f', a4f_1['params'])
                state[m]['marg2_p'] = ('A4f', a4f_2['params'])
                state[m]['h1_prev'] = float(a4f_1['h'][-1])
                state[m]['h2_prev'] = float(a4f_2['h'][-1])
                state[m]['g1_prev'] = float(a4f_1['g'][-1])
                state[m]['g2_prev'] = float(a4f_2['g'][-1])
                state[m]['last_fit'] = i

            state['DCC-A4f-ASYM']['dcc_a'] = dcc['a']
            state['DCC-A4f-ASYM']['dcc_b'] = dcc['b']
            state['DCC-A4f-ASYM']['qbar11'] = dcc['qbar11']
            state['DCC-A4f-ASYM']['qbar22'] = dcc['qbar22']
            state['DCC-A4f-ASYM']['qbar12'] = dcc['qbar12']
            state['DCC-A4f-ASYM']['eps1_prev'] = float(eps_1[-1])
            state['DCC-A4f-ASYM']['eps2_prev'] = float(eps_2[-1])
            state['DCC-A4f-ASYM']['q11_prev'] = dcc['qbar11']
            state['DCC-A4f-ASYM']['q22_prev'] = dcc['qbar22']
            state['DCC-A4f-ASYM']['q12_prev'] = dcc['qbar12']

            state['Copula-t-A4f-ASYM']['copula_t'] = cop_t
            state['Copula-t-A4f-ASYM']['marg_t_df_1'] = df_1
            state['Copula-t-A4f-ASYM']['marg_t_df_2'] = df_2
            state['Copula-Clayton-A4f-ASYM']['copula_clayton'] = cop_clayton
            state['Copula-Clayton-A4f-ASYM']['marg_t_df_1'] = df_1
            state['Copula-Clayton-A4f-ASYM']['marg_t_df_2'] = df_2

        # ---- Recursive one-step forecast (lookahead guard: r[t-1], x2[t-1]) ----
        r1_prev = ret1[t-1]
        r2_prev = ret2[t-1]
        x21_prev = x21[t-1]
        x22_prev = x22[t-1]

        for m in MODELS:
            if m not in MODELS_FILTER:
                continue
            marg1 = state[m]['marg1_p']
            marg2 = state[m]['marg2_p']

            p = marg1[1]
            tau1 = max(p[0] + p[1] * x21_prev, 1e-16)
            u_prev1 = r1_prev / np.sqrt(tau1)
            ind1 = 1.0 if r1_prev < 0 else 0.0
            g1_t = p[2] + p[3]*u_prev1**2 + p[4]*u_prev1**2*ind1 + \
                   p[5]*state[m]['g1_prev']
            g1_t = max(g1_t, 1e-16)
            state[m]['g1_prev'] = g1_t
            h1_t = max(tau1 * g1_t, 1e-16)

            p = marg2[1]
            tau2 = max(p[0] + p[1] * x22_prev, 1e-16)
            u_prev2 = r2_prev / np.sqrt(tau2)
            ind2 = 1.0 if r2_prev < 0 else 0.0
            g2_t = p[2] + p[3]*u_prev2**2 + p[4]*u_prev2**2*ind2 + \
                   p[5]*state[m]['g2_prev']
            g2_t = max(g2_t, 1e-16)
            state[m]['g2_prev'] = g2_t
            h2_t = max(tau2 * g2_t, 1e-16)

            state[m]['h1_prev'] = h1_t
            state[m]['h2_prev'] = h2_t
            h1_store[m][i] = h1_t
            h2_store[m][i] = h2_t

            if m == 'DCC-A4f-ASYM':
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
                rho_store[m][i] = rho_t

                eps1_now = r1_prev / np.sqrt(h1_t) if h1_t > 1e-16 else 0.0
                eps2_now = r2_prev / np.sqrt(h2_t) if h2_t > 1e-16 else 0.0
                state[m]['eps1_prev'] = eps1_now
                state[m]['eps2_prev'] = eps2_now
                state[m]['q11_prev'] = q11
                state[m]['q22_prev'] = q22
                state[m]['q12_prev'] = q12

                s1 = np.sqrt(h1_t)
                s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * rho_t * s1 * s2
                pvar_store[m][i] = max(pv, 1e-16)

            elif m == 'Copula-t-A4f-ASYM':
                cop = state[m]['copula_t']
                copula_t_rho[i] = cop['rho']
                copula_t_nu[i] = cop['nu']
                lambda_L_t[i] = t_copula_lambda(cop['rho'], cop['nu'])
                copula_t_params_t[i] = cop
                marg_t_df_1[i] = state[m]['marg_t_df_1']
                marg_t_df_2[i] = state[m]['marg_t_df_2']
                s1 = np.sqrt(h1_t)
                s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * cop['rho'] * s1 * s2
                pvar_store[m][i] = max(pv, 1e-16)
                rho_store[m][i] = cop['rho']

            elif m == 'Copula-Clayton-A4f-ASYM':
                cop = state[m]['copula_clayton']
                copula_clayton_theta[i] = cop['theta']
                lambda_L_clayton[i] = cop.get('lambda_L', 0.0)
                copula_clayton_params_t[i] = cop
                tau_k = cop['theta'] / (cop['theta'] + 2.0)
                rho_approx = np.sin(np.pi * tau_k / 2.0)
                s1 = np.sqrt(h1_t)
                s2 = np.sqrt(h2_t)
                pv = WEIGHTS[0]**2 * h1_t + WEIGHTS[1]**2 * h2_t + \
                     2 * WEIGHTS[0] * WEIGHTS[1] * rho_approx * s1 * s2
                pvar_store[m][i] = max(pv, 1e-16)
                rho_store[m][i] = rho_approx

    oos_dates = dates[oos_idx:]
    return {
        'pvar': pvar_store, 'h1': h1_store, 'h2': h2_store,
        'rho': rho_store, 'oos_dates': oos_dates, 'oos_idx': oos_idx,
        'copula_t_rho': copula_t_rho,
        'copula_t_nu': copula_t_nu,
        'copula_clayton_theta': copula_clayton_theta,
        'lambda_L_t': lambda_L_t,
        'lambda_L_clayton': lambda_L_clayton,
        'copula_t_params_t': copula_t_params_t,
        'copula_clayton_params_t': copula_clayton_params_t,
        'marg_t_df_1': marg_t_df_1,
        'marg_t_df_2': marg_t_df_2,
    }


def compute_copula_mc_var(forecasts, copula_type, model_key,
                          alpha_levels, n_paths):
    h1 = forecasts['h1'][model_key]
    h2 = forecasts['h2'][model_key]
    n_oos = len(h1)
    var_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}
    es_out = {a: np.full(n_oos, np.nan) for a in alpha_levels}

    if copula_type == 't':
        params_list = forecasts['copula_t_params_t']
    else:
        params_list = forecasts['copula_clayton_params_t']
    df_1_arr = forecasts['marg_t_df_1']
    df_2_arr = forecasts['marg_t_df_2']

    for i in range(n_oos):
        if (not np.isfinite(h1[i]) or not np.isfinite(h2[i])
                or params_list[i] is None):
            continue
        if not (np.isfinite(df_1_arr[i]) and np.isfinite(df_2_arr[i])):
            continue
        sub_rng = np.random.default_rng(42 + i)
        mc = copula_mc_var_es(
            h1[i], h2[i], copula_type, params_list[i],
            (float(df_1_arr[i]), float(df_2_arr[i])),
            alpha_levels, n_paths, sub_rng)
        for a in alpha_levels:
            var_out[a][i] = mc[a][0]
            es_out[a][i] = mc[a][1]

    return var_out, es_out


# ============================================================
# 7. DATA LOADING (5 markets + ^VIX, with STOXX50E→FEZ fallback)
# ============================================================
def _fetch_yf_close(ticker, start, end, auto_adjust=True):
    import yfinance as yf
    raw = yf.download(ticker, start=start, end=end,
                      auto_adjust=auto_adjust, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = raw.columns.get_level_values(0)
    if 'Close' not in raw.columns:
        return pd.Series(dtype=float, name=ticker)
    return raw['Close'].rename(ticker)


def load_data():
    print(f"Downloading prices: {len(MARKETS)} markets + ^VIX ...")
    closes = {}
    ticker_used = {}  # short_name -> actual ticker used (primary or fallback)

    for short, (primary, fallback, region) in MARKETS.items():
        s = _fetch_yf_close(primary, DATA_START, DATA_END)
        valid_count = s.dropna().shape[0]
        used = primary
        print(f"  {short} <- {primary}: {valid_count} valid rows")
        if valid_count < 1000 and fallback is not None:
            print(f"    INSUFFICIENT (<1000); falling back to {fallback}")
            s_alt = _fetch_yf_close(fallback, DATA_START, DATA_END)
            valid_alt = s_alt.dropna().shape[0]
            print(f"    {fallback}: {valid_alt} valid rows")
            if valid_alt > valid_count:
                s = s_alt
                used = fallback
                print(f"    USING fallback {fallback} for {short}")
            else:
                print(f"    Fallback no better — keeping {primary}")
        elif valid_count < 1000 and fallback is None:
            print(f"    WARNING: {short} ({primary}) has only {valid_count} "
                  f"rows but no fallback configured.")
        closes[short] = s
        ticker_used[short] = used

    vix_raw_close = _fetch_yf_close('^VIX', DATA_START, DATA_END,
                                     auto_adjust=False)

    df = pd.DataFrame({
        **{short: closes[short] for short in MARKETS},
        'vix': vix_raw_close,
    }).sort_index()

    df = df.dropna(subset=['vix'])

    for short in MARKETS:
        df[f'ret_{short}'] = np.log(df[short] / df[short].shift(1))
        df[f'simple_{short}'] = df[short].pct_change()

    df['vix2'] = (df['vix'] / 100.0) ** 2 / 252.0

    # INNER JOIN: drop any row missing any market's return (calendar overlap)
    ret_cols = [f'ret_{short}' for short in MARKETS]
    df_full = df.dropna(subset=ret_cols + ['vix2'])
    if df_full.empty:
        raise RuntimeError(
            "load_data() produced an empty inner-joined panel; "
            "yfinance data fetch likely failed in this environment."
        )

    print(f"\nData (inner-joined across all markets):")
    print(f"  Period: {df_full.index[0].strftime('%Y-%m-%d')} to "
          f"{df_full.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Total inner-join days: {len(df_full)}")
    for short in MARKETS:
        valid = df[short].notna().sum()
        first = df[short].first_valid_index()
        first_str = first.strftime('%Y-%m-%d') if first is not None else 'NaN'
        print(f"  {short} ({ticker_used[short]}): "
              f"{valid} pre-join valid, first valid {first_str}")
    print(f"  ticker_used: {ticker_used}")

    # Stash ticker_used metadata as attr for downstream save
    df_full.attrs['ticker_used'] = ticker_used
    return df_full


# ============================================================
# 8. EVALUATE PAIR (identical to E1)
# ============================================================
def evaluate_pair(pair_name, asset1, asset2, reg1_col, reg2_col, df):
    print(f"\n{'=' * 72}")
    print(f"PAIR: {pair_name} ({asset1} vs {asset2}) "
          f"[{PAIR_REGION_CLASS.get(pair_name, 'unclassified')}]")
    print(f"  Regressors: {asset1}->{reg1_col}, {asset2}->{reg2_col}")
    print(f"{'=' * 72}")

    required = [f'ret_{asset1}', f'ret_{asset2}',
                f'simple_{asset1}', f'simple_{asset2}',
                reg1_col, reg2_col]
    pair_df = df.dropna(subset=required).copy()
    print(f"  Pair sample: {len(pair_df)} days, "
          f"from {pair_df.index[0].strftime('%Y-%m-%d')} to "
          f"{pair_df.index[-1].strftime('%Y-%m-%d')}")

    ret1 = pair_df[f'ret_{asset1}'].values
    ret2 = pair_df[f'ret_{asset2}'].values
    x21 = pair_df[reg1_col].values
    x22 = pair_df[reg2_col].values
    dates = pair_df.index.values
    port_ret = (WEIGHTS[0] * pair_df[f'simple_{asset1}'].values
                + WEIGHTS[1] * pair_df[f'simple_{asset2}'].values)

    corr = np.corrcoef(ret1, ret2)[0, 1]
    print(f"  Full-sample log-return corr: {corr:.4f}")

    t_start = time.time()
    forecasts = oos_forecast_pair(ret1, ret2, x21, x22, dates, OOS_START,
                                   pair_name)
    oos_idx = forecasts['oos_idx']
    oos_dates = forecasts['oos_dates']
    n_oos = len(oos_dates)
    port_ret_oos = port_ret[oos_idx:]
    r2_port_oos = port_ret_oos ** 2

    print(f"  OOS period: "
          f"{pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d')} to "
          f"{pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d')} "
          f"({n_oos} days, {time.time()-t_start:.0f}s fit)")

    var_series_store = {m: {} for m in MODELS}
    es_series_store = {m: {} for m in MODELS}
    fz_mean_store = {m: {} for m in MODELS}
    fz_series_store = {m: {} for m in MODELS}
    models_results = {}

    if 'DCC-A4f-ASYM' in MODELS_FILTER:
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
            alpha_key = f"alpha_{alpha:.3f}"
            model_results['var_tests'][alpha_key] = trinity
            model_results['fz_score'][alpha_key] = {
                'mean': fz_mean, 'n': int(len(fz_s))}
        models_results[m] = model_results

    for m, copula_type in [('Copula-t-A4f-ASYM', 't'),
                            ('Copula-Clayton-A4f-ASYM', 'clayton')]:
        if m not in MODELS_FILTER:
            continue
        var_dict, es_dict = compute_copula_mc_var(
            forecasts, copula_type, m, ALPHA_LEVELS, MC_PATHS)
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

    # DM QLIKE comparisons (only over models in MODELS_FILTER)
    qlike_dm = {}
    pairs_qlike = [
        ('DCC-A4f-ASYM', 'Copula-t-A4f-ASYM'),
        ('DCC-A4f-ASYM', 'Copula-Clayton-A4f-ASYM'),
        ('Copula-t-A4f-ASYM', 'Copula-Clayton-A4f-ASYM'),
    ]
    for m1, m2 in pairs_qlike:
        if m1 not in MODELS_FILTER or m2 not in MODELS_FILTER:
            continue
        dm = dm_qlike(r2_port_oos, forecasts['pvar'][m1],
                      forecasts['pvar'][m2])
        qlike_dm[f"{m1}_vs_{m2}"] = dm

    fz_dm = {}
    for alpha in ALPHA_LEVELS:
        alpha_key = f"alpha_{alpha:.3f}"
        fz_dm[alpha_key] = {}
        for m1, m2 in pairs_qlike:
            if m1 not in MODELS_FILTER or m2 not in MODELS_FILTER:
                continue
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

    qlike_means = {}
    for m in MODELS_FILTER:
        pv = forecasts['pvar'][m]
        valid = np.isfinite(pv) & (pv > 0) & np.isfinite(r2_port_oos)
        q = np.log(pv[valid]) + r2_port_oos[valid] / pv[valid]
        qlike_means[m] = float(np.mean(q))

    cop_stats = {
        'student_t': {
            'rho_mean': float(np.nanmean(forecasts['copula_t_rho'])),
            'rho_std': float(np.nanstd(forecasts['copula_t_rho'])),
            'rho_min': float(np.nanmin(forecasts['copula_t_rho'])),
            'rho_max': float(np.nanmax(forecasts['copula_t_rho'])),
            'nu_mean': float(np.nanmean(forecasts['copula_t_nu'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_t'])),
            'lambda_L_std': float(np.nanstd(forecasts['lambda_L_t'])),
            'lambda_L_min': float(np.nanmin(forecasts['lambda_L_t'])),
            'lambda_L_max': float(np.nanmax(forecasts['lambda_L_t'])),
        },
        'clayton': {
            'theta_mean': float(np.nanmean(forecasts['copula_clayton_theta'])),
            'theta_std': float(np.nanstd(forecasts['copula_clayton_theta'])),
            'theta_min': float(np.nanmin(forecasts['copula_clayton_theta'])),
            'theta_max': float(np.nanmax(forecasts['copula_clayton_theta'])),
            'lambda_L_mean': float(np.nanmean(forecasts['lambda_L_clayton'])),
            'lambda_L_std': float(np.nanstd(forecasts['lambda_L_clayton'])),
            'lambda_L_min': float(np.nanmin(forecasts['lambda_L_clayton'])),
            'lambda_L_max': float(np.nanmax(forecasts['lambda_L_clayton'])),
        },
    }

    print(f"\n  --- {pair_name} Summary ---")
    print(f"    Copula-t: mean ρ={cop_stats['student_t']['rho_mean']:+.3f}, "
          f"ν={cop_stats['student_t']['nu_mean']:.1f}, "
          f"λ_L={cop_stats['student_t']['lambda_L_mean']:.4f}")
    print(f"    Clayton: mean θ={cop_stats['clayton']['theta_mean']:.3f}, "
          f"λ_L={cop_stats['clayton']['lambda_L_mean']:.4f}")
    for m in MODELS_FILTER:
        q = qlike_means[m]
        t_pass_01 = models_results[m]['var_tests']['alpha_0.010'][
            'trinity_pass']
        t_pass_025 = models_results[m]['var_tests']['alpha_0.025'][
            'trinity_pass']
        fz_01 = fz_mean_store[m][0.01]
        print(f"    {m}: QLIKE={q:.5f}, Trinity 1%={t_pass_01}, "
              f"2.5%={t_pass_025}, FZ 1%={fz_01:.4f}")
    for k, dm in qlike_dm.items():
        direction = "copula_better" if dm['t_stat'] > 0 else "dcc_better"
        sig = "***" if dm['significant_harvey'] else ("*" if dm['p_value']<0.05 else "")
        print(f"    DM QLIKE {k}: t={dm['t_stat']:+.3f} ({direction}) {sig}")

    return {
        'pair_name': pair_name,
        'asset1': asset1, 'asset2': asset2,
        'reg1': reg1_col, 'reg2': reg2_col,
        'region_class': PAIR_REGION_CLASS.get(pair_name, 'unclassified'),
        'n_oos': int(n_oos),
        'full_sample_corr': float(corr),
        'models': models_results,
        'dm_qlike': qlike_dm,
        'dm_fz': fz_dm,
        'mean_qlike': qlike_means,
        'copula_stats': cop_stats,
        'oos_dates_first': pd.Timestamp(oos_dates[0]).strftime('%Y-%m-%d'),
        'oos_dates_last': pd.Timestamp(oos_dates[-1]).strftime('%Y-%m-%d'),
        '_fz_mean_store': fz_mean_store,
        '_lambda_L_t_series': forecasts['lambda_L_t'],
        '_lambda_L_clayton_series': forecasts['lambda_L_clayton'],
        '_oos_dates': oos_dates,
        '_port_ret_oos': port_ret_oos,
        '_pvar': forecasts['pvar'],
        '_var_series_store': var_series_store,
        '_fit_time_s': float(time.time() - t_start),
    }


# ============================================================
# 9. MAIN
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
    ticker_used = df.attrs.get('ticker_used', {})

    pair_results = {}
    for pair_tuple in PAIRS:
        pair_name, a1, a2, r1, r2 = pair_tuple
        elapsed = time.time() - START_TIME
        print(f"\n>>> [{elapsed:.0f}s elapsed] Starting pair {pair_name} ...")
        pair_results[pair_name] = evaluate_pair(pair_name, a1, a2, r1, r2, df)

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
                    'smoke_test': SMOKE_TEST,
                    'models_filter': MODELS_FILTER,
                    'ticker_used': ticker_used,
                },
                'timestamp_partial': datetime.now(timezone.utc).isoformat(),
                'pairs_done': list(pair_results.keys()),
            }, f, indent=2)
        print(f"  Checkpoint saved ({len(pair_results)}/{len(PAIRS)} pairs)")

    # ===== Cross-pair analysis =====
    print(f"\n{'=' * 72}")
    print(f"CROSS-PAIR ANALYSIS")
    print(f"{'=' * 72}")

    cross_table = []
    for pair_name, pr in pair_results.items():
        # If smoke test (single model), use whatever copula is available
        if 'DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM' in pr['dm_qlike']:
            dm_vs_t = pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-t-A4f-ASYM']
        else:
            dm_vs_t = {'t_stat': 0.0, 'significant_harvey': False,
                       'p_value': 1.0, 'critical_value': np.nan}
        if 'DCC-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM' in pr['dm_qlike']:
            dm_vs_c = pr['dm_qlike']['DCC-A4f-ASYM_vs_Copula-Clayton-A4f-ASYM']
        else:
            dm_vs_c = {'t_stat': 0.0, 'significant_harvey': False,
                       'p_value': 1.0, 'critical_value': np.nan}
        if dm_vs_t['t_stat'] > dm_vs_c['t_stat']:
            best_cop = 'Student-t'
            best_dm = dm_vs_t
        else:
            best_cop = 'Clayton'
            best_dm = dm_vs_c
        row = {
            'pair': pair_name,
            'region_class': pr['region_class'],
            'lambda_L_t_mean': pr['copula_stats']['student_t']['lambda_L_mean'],
            'lambda_L_clayton_mean': pr['copula_stats']['clayton']['lambda_L_mean'],
            'qlike_dcc': pr['mean_qlike'].get('DCC-A4f-ASYM', np.nan),
            'qlike_copula_t': pr['mean_qlike'].get('Copula-t-A4f-ASYM', np.nan),
            'qlike_clayton': pr['mean_qlike'].get('Copula-Clayton-A4f-ASYM',
                                                   np.nan),
            'dm_dcc_vs_copula_t': dm_vs_t['t_stat'],
            'dm_dcc_vs_clayton': dm_vs_c['t_stat'],
            'best_copula': best_cop,
            'best_copula_dm_t': best_dm['t_stat'],
            'best_copula_harvey': best_dm['significant_harvey'],
            'full_sample_corr': pr['full_sample_corr'],
        }
        cross_table.append(row)

    print(f"\n{'Pair':<18} {'region':<28} {'corr':>6} {'λ_L(t)':>8} "
          f"{'λ_L(C)':>7} {'DM(t)':>7} {'DM(C)':>7} {'HLN':>7}")
    print("-" * 100)
    for r in cross_table:
        harvey = "Y" if r['best_copula_harvey'] else "N"
        print(f"{r['pair']:<18} {r['region_class']:<28} "
              f"{r['full_sample_corr']:+.3f} "
              f"{r['lambda_L_t_mean']:>8.4f} "
              f"{r['lambda_L_clayton_mean']:>7.4f} "
              f"{r['dm_dcc_vs_copula_t']:>+7.3f} "
              f"{r['dm_dcc_vs_clayton']:>+7.3f} {harvey:>7}")

    lam_t_arr = np.array([r['lambda_L_t_mean'] for r in cross_table])
    lam_c_arr = np.array([r['lambda_L_clayton_mean'] for r in cross_table])
    dm_t_arr = np.array([r['dm_dcc_vs_copula_t'] for r in cross_table])
    dm_c_arr = np.array([r['dm_dcc_vs_clayton'] for r in cross_table])

    r_t = r_c = None
    if len(cross_table) >= 3:
        try:
            r_t = stats.spearmanr(lam_t_arr, dm_t_arr)
            r_c = stats.spearmanr(lam_c_arr, dm_c_arr)
            print(f"\n  Spearman(λ_L Student-t, DM t-stat Copula-t vs DCC): "
                  f"rho={r_t.statistic:+.3f}, p={r_t.pvalue:.3f}")
            print(f"  Spearman(λ_L Clayton, DM t-stat Clayton vs DCC): "
                  f"rho={r_c.statistic:+.3f}, p={r_c.pvalue:.3f}")
        except Exception as e:
            print(f"  Spearman error: {e}")

    core = {
        'n_pairs': len(cross_table),
        'cross_table': cross_table,
        'any_copula_beats_dcc_harvey': any(
            r['best_copula_harvey'] and r['best_copula_dm_t'] > 0
            for r in cross_table),
        'pairs_with_copula_advantage_harvey': [
            r['pair'] for r in cross_table
            if r['best_copula_harvey'] and r['best_copula_dm_t'] > 0],
        'spearman_lambdaL_vs_dm_t': {
            'rho': r_t.statistic if r_t else None,
            'p': r_t.pvalue if r_t else None,
        } if r_t else None,
        'spearman_lambdaL_vs_dm_clayton': {
            'rho': r_c.statistic if r_c else None,
            'p': r_c.pvalue if r_c else None,
        } if r_c else None,
        # By-region rollups (E2-specific)
        'by_region': {},
    }
    # Group pairs by region for H1/H2/H3 verdict
    region_groups = {}
    for r in cross_table:
        region_groups.setdefault(r['region_class'], []).append(r)
    for region, rows in region_groups.items():
        core['by_region'][region] = {
            'n_pairs': len(rows),
            'pairs': [r['pair'] for r in rows],
            'lambda_L_t_mean': float(np.mean([r['lambda_L_t_mean']
                                              for r in rows])),
            'lambda_L_clayton_mean': float(np.mean([r['lambda_L_clayton_mean']
                                                    for r in rows])),
            'dm_dcc_vs_copula_t_mean': float(np.mean([r['dm_dcc_vs_copula_t']
                                                       for r in rows])),
            'dm_dcc_vs_clayton_mean': float(np.mean([r['dm_dcc_vs_clayton']
                                                      for r in rows])),
            'n_harvey_sig': sum(1 for r in rows if r['best_copula_harvey']
                                 and r['best_copula_dm_t'] > 0),
        }

    results_final = {
        'experiment_id': EXPERIMENT_ID,
        'pair_results': {pn: to_json_safe(pr)
                          for pn, pr in pair_results.items()},
        'cross_pair_table': cross_table,
        'core_answers': core,
        'config': {
            'oos_start': OOS_START, 'window': WINDOW,
            'refit_every': REFIT_EVERY, 'alpha_levels': ALPHA_LEVELS,
            'weights': WEIGHTS.tolist(), 'mc_paths': MC_PATHS,
            'seed': 42, 'smoke_test': SMOKE_TEST,
            'models_filter': MODELS_FILTER,
            'ticker_used': ticker_used,
        },
        'metadata': {
            'experiment_id': EXPERIMENT_ID,
            'parent_experiments': ['K1100b', 'K1100', 'K1092', 'K1142',
                                    'K1172', 'Paper3_E1'],
            'data_source': 'yfinance (5 equity markets + ^VIX)',
            'data_period': f"{DATA_START} to {DATA_END}",
            'oos_start': OOS_START,
            'pairs': [p[0] for p in PAIRS],
            'markets': list(MARKETS.keys()),
            'ticker_used': ticker_used,
            'proposer': 'Boss directive 2026-05-29 (Paper 3 reframe E2 expansion)',
            'runtime_seconds': float(time.time() - START_TIME),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'references': [
                'K1100b (ETF-level asset-class copula advantage)',
                'Paper3_E1 (individual stocks NULL verdict, 2026-05-29)',
                'Patton (2006) IER 47(2)',
                'Christoffersen et al. (2012) RFS int copula tail',
                'Karolyi & Stulz (1996) JF cross-country equity comov',
                'Forbes & Rigobon (2002) JF contagion vs interdependence',
                'Longin & Solnik (2001) JF extreme corr int equity',
                'Lai (2024) APFM 31(2) PRS copula',
            ],
        },
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(to_json_safe(results_final), f, indent=2)
    print(f"\nResults saved: {RESULTS_PATH}")

    # PLOTS (skip in smoke test)
    if not SMOKE_TEST:
        print("\n--- Generating Plots ---")
        make_plots(pair_results, cross_table)

    runtime = time.time() - START_TIME
    print(f"\nTotal runtime: {runtime:.1f}s")

    print(f"\n{'=' * 72}")
    print(f"FINAL VERDICT")
    print(f"{'=' * 72}")
    if core['any_copula_beats_dcc_harvey']:
        print(f"✅ H1 CONFIRMED: Copula-GARCH beats DCC-A4f-ASYM "
              f"at the HLN-corrected critical value on pair(s): "
              f"{core['pairs_with_copula_advantage_harvey']}")
        print("  → Cross-market copula advantage IDENTIFIED. Investigate "
              "which region class drives it (H2 candidate).")
    else:
        print("❌ H1 REJECTED: No cross-market pair shows copula beating "
              "DCC at the HLN-corrected critical value.")
        print("  → Combined with E1 NULL, Paper 3 reframe needs E3 commodity "
              "results to determine whether asset-class advantage exists.")
    if r_t is not None:
        if r_t.statistic > 0 and r_t.pvalue < 0.20:
            print(f"✅ H4 SUPPORTED: λ_L(t) positively correlates with DM t "
                  f"(Spearman ρ={r_t.statistic:+.3f}).")
        else:
            print(f"⚠️  H4 WEAK: Spearman ρ(λ_L(t), DM t)={r_t.statistic:+.3f} "
                  f"(p={r_t.pvalue:.3f}).")
    print("\nBy-region summary:")
    for region, agg in core['by_region'].items():
        print(f"  {region}: n={agg['n_pairs']}, "
              f"mean λ_L(t)={agg['lambda_L_t_mean']:.4f}, "
              f"mean DM(t)={agg['dm_dcc_vs_copula_t_mean']:+.3f}, "
              f"HLN-sig pairs={agg['n_harvey_sig']}")


def make_plots(pair_results, cross_table):
    # Plot 1: tail dependence dynamics by pair
    fig, axes = plt.subplots(len(pair_results), 1,
                             figsize=(14, 2.6 * len(pair_results)),
                             sharex=False)
    if len(pair_results) == 1:
        axes = [axes]
    for ax, (pair_name, pr) in zip(axes, pair_results.items()):
        oos_pd = pd.DatetimeIndex(pr['_oos_dates']).to_numpy()
        ax.plot(oos_pd, pr['_lambda_L_t_series'],
                label='Student-t λ (sym)', color='steelblue', lw=1.1)
        ax.plot(oos_pd, pr['_lambda_L_clayton_series'],
                label='Clayton λ_L', color='darkred', lw=1.1)
        ax.axvspan(pd.Timestamp('2020-02-20'), pd.Timestamp('2020-06-30'),
                   alpha=0.12, color='red')
        ax.axvspan(pd.Timestamp('2022-01-01'), pd.Timestamp('2022-12-31'),
                   alpha=0.10, color='orange')
        ax.set_ylabel('λ_L')
        ax.set_title(f'{pair_name} [{pr["region_class"]}]: '
                     f'mean λ_L(t)={pr["copula_stats"]["student_t"]["lambda_L_mean"]:.3f}, '
                     f'λ_L(Clay)={pr["copula_stats"]["clayton"]["lambda_L_mean"]:.3f}')
        ax.legend(fontsize=8, loc='upper right')
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel('Date')
    plt.suptitle(f'{EXPERIMENT_ID}: Tail Dependence λ_L by Cross-Market Pair',
                 fontsize=12)
    plt.tight_layout()
    p1 = os.path.join(SCRIPT_DIR, 'paper3_E2_tail_dependence_by_pair.png')
    plt.savefig(p1, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p1}")

    # Plot 2: DM t-stat vs mean λ_L (cross-pair scatter)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    region_colors = {
        'developed_cross_region': 'steelblue',
        'developed_vs_emerging_asia': 'darkred',
        'asia_intraregional': 'darkgreen',
    }

    for idx, (ax, lam_key, dm_key, cop_label) in enumerate([
        (axes[0], 'lambda_L_t_mean', 'dm_dcc_vs_copula_t', 'Student-t'),
        (axes[1], 'lambda_L_clayton_mean', 'dm_dcc_vs_clayton', 'Clayton'),
    ]):
        for region, color in region_colors.items():
            rows = [r for r in cross_table if r['region_class'] == region]
            if not rows:
                continue
            x = [r[lam_key] for r in rows]
            y = [r[dm_key] for r in rows]
            names = [r['pair'] for r in rows]
            ax.scatter(x, y, s=80, color=color, edgecolor='black',
                       zorder=3, label=region)
            for xi, yi, n in zip(x, y, names):
                ax.annotate(n, (xi, yi), fontsize=8,
                            xytext=(5, 5), textcoords='offset points')
        ax.axhline(0, color='black', lw=0.5)
        ax.set_xlabel(f'Mean λ_L ({cop_label} copula)')
        ax.set_ylabel(f'DM t-stat: DCC-A4f-ASYM vs {cop_label}\n'
                      f'(positive → copula better)')
        ax.set_title(f'{cop_label}: DM t vs λ_L (by region)')
        ax.grid(alpha=0.3)
        ax.legend(fontsize=7, loc='best')

    plt.suptitle(
        f'{EXPERIMENT_ID}: Cross-Market DM t-stat vs Tail Dependence',
        fontsize=11)
    plt.tight_layout()
    p2 = os.path.join(SCRIPT_DIR, 'paper3_E2_dm_vs_lambdaL.png')
    plt.savefig(p2, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p2}")

    # Plot 3: FZ heatmap
    pair_names = list(pair_results.keys())
    fig, axes = plt.subplots(1, 2, figsize=(14, 4 + 0.4 * len(pair_names)))
    for ax_i, alpha in enumerate(ALPHA_LEVELS):
        ax = axes[ax_i]
        try:
            fz_mat = np.array([
                [pr['_fz_mean_store'][m].get(alpha, np.nan) for m in MODELS]
                for pr in pair_results.values()])
        except Exception:
            continue
        im = ax.imshow(fz_mat, cmap='RdYlGn_r', aspect='auto')
        ax.set_xticks(range(len(MODELS)))
        ax.set_xticklabels(MODELS, rotation=25, ha='right', fontsize=9)
        ax.set_yticks(range(len(pair_names)))
        ax.set_yticklabels(pair_names, fontsize=9)
        ax.set_title(f'FZ Score α={alpha:.3f} (lower=better)')
        for i in range(len(pair_names)):
            for j in range(len(MODELS)):
                val = fz_mat[i, j]
                if not np.isfinite(val):
                    continue
                color = 'white' if (val - np.nanmin(fz_mat)) / max(
                    np.nanmax(fz_mat) - np.nanmin(fz_mat), 1e-6) > 0.5 else 'black'
                ax.text(j, i, f'{val:.3f}', ha='center', va='center',
                        fontsize=8, color=color)
        plt.colorbar(im, ax=ax, fraction=0.04)
    plt.suptitle(f'{EXPERIMENT_ID}: Fissler-Ziegel Score Heatmap',
                 fontsize=12)
    plt.tight_layout()
    p3 = os.path.join(SCRIPT_DIR, 'paper3_E2_fz_heatmap.png')
    plt.savefig(p3, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {p3}")


if __name__ == '__main__':
    main()
