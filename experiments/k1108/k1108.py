#!/usr/bin/env python3
"""
K1108: Foundry economic rationale — capex guidance mechanism for θ₂ > 0.
==========================================================================
[提出: 賴奕豪, 執行: Claude]  Date: 2026-04-13

Context
-------
K1104 found (N=23 0050.TW constituents):
  - fabless firms → θ₂ < 0 (t=-2.22, p=0.039 *): MediaTek/Realtek/
    Novatek/Phison consistent.
  - foundry firms → θ₂ ≥ 0 (direction only; TSMC ~0, UMC strong +).

Why would foundry firms react DIFFERENTLY to earnings announcements?
Economic hypothesis: **foundry earnings calls include capex guidance
updates** ("Full-year capex raised to $38-42 bn"). Capex guidance
directly signals future capacity, utilisation, and investor-expected
vol of supply. Fabless firms report gross-margin / product cycle —
without capex guidance.

K1108 tests whether the foundry θ₂ signal is concentrated on
**capex-guidance REVISION days**, not on ordinary EAV days.

Hypothesis
----------
H1 (capex mechanism): θ₂_capex_change >> θ₂_capex_stable (Wald test).
    If confirmed → foundry θ₂ > 0 is a capex-guidance-driven phenomenon,
    not a generic EAV edge. Paper 2 firm-selection rule becomes
    "prefer firms that issue capex guidance", not the binary foundry
    dummy.

Design
------
Model family: A4f-EAV (K1067 baseline).
  τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε)
  u_t = r_t / √τ_t
  g_t = ω + α·u²_{t-1} + γ·u²_{t-1}·I[u<0] + β·g_{t-1}
  σ² = τ_t · g_t

Specs
  M1: GJR-GARCH baseline (θ₁=θ₂=0), same g dynamics.
  M2: A4f-EAV standard (K1067), single θ₂ for all earnings days.
  M3: A4f-EAV + CAPEX split:
      τ_t = max(θ₀ + θ₁·VIX²_{t-1}
                + θ_capex_change · EAV_change_{t-1}
                + θ_capex_stable · EAV_stable_{t-1}, ε)
      where EAV_change and EAV_stable are disjoint indicators
      (capex guidance revised vs unchanged on the earnings day).

Tests
  T1: LR test M3 vs M2 (does split improve fit?).
  T2: Wald test H0: θ_capex_change = θ_capex_stable.
  T3: t-test θ_capex_change > 0 one-sided.
  T4: Bootstrap (seed 42, 1000 reps) resample capex-change/stable days
      with replacement; bootstrap CI for (θ_change − θ_stable).

Data
  - TSMC 2330.TW daily close 2014-01-01 → 2025-12-31 (from K1104 cache
    2330.TW.parquet).
  - ^VIX daily close (K1104 cache IDX_VIX.parquet).
  - 財報公告日.txt for earnings announcement dates (48 events 2014-25).
  - experiments/k1108/data/tsmc_capex_guidance.csv (hand-coded from
    TSMC IR public press releases; 25 revisions, 23 held).

Lookahead guard
  EAV indicator positioned at the earnings announcement TRADING DAY
  (not the day before). τ uses EAV_{t-1} → effect shows up on next
  trading day's vol forecast, which is what we want. capex_flag is
  the ANNOUNCEMENT-DAY-OF value (i.e. we know by market close whether
  the call revised guidance). No lookahead.

Random seed: 42.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats
import matplotlib.pyplot as plt

import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = 'K1108'

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1104_CACHE = PROJECT_ROOT / 'experiments' / 'k1104' / 'data'
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True, parents=True)

RESULTS_PATH = SCRIPT_DIR / 'k1108_results.json'
PLOT_THETA = SCRIPT_DIR / 'k1108_theta_split.png'
PLOT_TAU = SCRIPT_DIR / 'k1108_tau_jump_timeseries.png'

CAPEX_CSV = DATA_DIR / 'tsmc_capex_guidance.csv'
DATA_START = '2014-01-01'
DATA_END = '2025-12-31'

TICKER = '2330.TW'
CODE = '2330'


# ==========================================================================
# DATA LOADERS
# ==========================================================================

def load_prices():
    path = K1104_CACHE / '2330.TW.parquet'
    if not path.exists():
        raise FileNotFoundError(f"TSMC cache missing: {path}")
    raw = pd.read_parquet(path)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    prices = raw['Close'].dropna()
    prices = prices[(prices.index >= DATA_START) & (prices.index <= DATA_END)]
    return prices


def load_vix():
    path = K1104_CACHE / 'IDX_VIX.parquet'
    if not path.exists():
        raise FileNotFoundError(f"VIX cache missing: {path}")
    raw = pd.read_parquet(path)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    vix = raw['Close'].dropna()
    return vix


def load_earnings_dates(code):
    with open(DATA_FILE, 'rb') as f:
        raw_text = f.read().decode('big5', errors='replace')
    lines = raw_text.strip().split('\n')
    recs = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) >= 4 and parts[0].strip() == code:
            ds = parts[3].strip()
            if ds:
                try:
                    dt = pd.Timestamp(ds.replace('/', '-'))
                    period = parts[2].strip() if len(parts) > 2 else ''
                    recs.append({'date': dt, 'period': period})
                except Exception:
                    pass
    ea_df = pd.DataFrame(recs)
    ea_df = ea_df[(ea_df['date'] >= DATA_START) & (ea_df['date'] <= DATA_END)]
    return ea_df.sort_values('date').reset_index(drop=True)


def load_capex_guidance():
    if not CAPEX_CSV.exists():
        # Regenerate the file using the helper script logic.
        import k1108_fetch_capex as helper  # type: ignore
        helper.main()
    g = pd.read_csv(CAPEX_CSV)
    g['announce_date'] = pd.to_datetime(g['announce_date'])
    return g


# ==========================================================================
# DESCRIPTIVE PRE-ESTIMATION DIAGNOSTICS (誠實原則 §5)
# ==========================================================================

def pre_estimation_diagnostics(ret, tag=""):
    from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
    from statsmodels.tsa.stattools import adfuller

    d = {
        'tag': tag,
        'n': int(len(ret)),
        'mean': float(np.mean(ret)),
        'std': float(np.std(ret, ddof=1)),
        'skew': float(stats.skew(ret)),
        'kurt': float(stats.kurtosis(ret)),
        'min': float(np.min(ret)),
        'max': float(np.max(ret)),
    }
    try:
        adf = adfuller(ret, autolag='AIC')
        d['adf_stat'] = float(adf[0])
        d['adf_pvalue'] = float(adf[1])
    except Exception as e:
        d['adf_error'] = str(e)
    try:
        lb = acorr_ljungbox(ret, lags=[10], return_df=True)
        d['ljungbox_Q10'] = float(lb['lb_stat'].iloc[0])
        d['ljungbox_p10'] = float(lb['lb_pvalue'].iloc[0])
    except Exception as e:
        d['ljungbox_error'] = str(e)
    try:
        arch = het_arch(ret, nlags=10)
        d['arch_lm_stat'] = float(arch[0])
        d['arch_lm_p'] = float(arch[1])
    except Exception as e:
        d['arch_error'] = str(e)
    return d


# ==========================================================================
# MODEL FITTING (A4f-EAV family, L-BFGS-B MLE, multi-start)
# ==========================================================================

def _neg_loglik_generic(params, returns, regressors):
    """Generic A4f-style negative log-likelihood.

    τ_t = max(θ₀ + Σ_k θ_k · X_k_{t-1}, ε)
    followed by GJR-GARCH on u = r/√τ.

    regressors: (n, K) matrix of pre-lagged regressors (X[t] is
      the value at time t-1 relative to the return index).
    params: [θ₀, θ₁..θ_K, ω, α, γ, β].
    """
    n = len(returns)
    K = regressors.shape[1]
    theta0 = params[0]
    theta = params[1:1 + K]
    omega_g, alpha, gamma_p, beta = params[1 + K:1 + K + 4]
    if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    persist = alpha + gamma_p / 2.0 + beta
    if persist >= 0.999:
        return 1e10
    tau_raw = theta0 + regressors @ theta
    tau = np.maximum(tau_raw, 1e-16)
    eg = omega_g / (1.0 - persist)
    g = eg
    ll = 0.0
    for t in range(1, n):
        tau_prev = max(tau[t - 1], 1e-16)
        u_prev = returns[t - 1] / np.sqrt(tau_prev)
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev ** 2 + asym + beta * g
        if g < 1e-10:
            g = 1e-10
        sigma2 = tau[t] * g
        if sigma2 > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) +
                          returns[t] ** 2 / sigma2)
    return -ll


def fit_model(returns, regressors, starts, bounds, label='', with_hessian=True,
              maxiter=1500, ftol=1e-10):
    """Multi-start L-BFGS-B MLE. Returns (params, loglik, std_err)."""
    best_ll = np.inf
    best_params = None
    best_res = None
    for s in starts:
        try:
            res = optimize.minimize(
                _neg_loglik_generic, s, args=(returns, regressors),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': maxiter, 'ftol': ftol})
            if res.fun < best_ll and np.isfinite(res.fun):
                best_ll = res.fun
                best_params = res.x
                best_res = res
        except Exception:
            continue
    if best_params is None:
        return None

    if not with_hessian:
        k = len(best_params)
        return {
            'label': label,
            'params': best_params,
            'loglik': -best_ll,
            'se': np.full(k, np.nan),
            'cov': np.eye(k) * np.nan,
            'converged': best_res is not None and best_res.success,
        }

    # Numerical Hessian for standard errors.
    eps = 1e-5
    k = len(best_params)
    H = np.zeros((k, k))
    f0 = _neg_loglik_generic(best_params, returns, regressors)
    for i in range(k):
        for j in range(k):
            pi_p = best_params.copy(); pi_p[i] += eps
            pi_m = best_params.copy(); pi_m[i] -= eps
            pj_p = best_params.copy(); pj_p[j] += eps
            pj_m = best_params.copy(); pj_m[j] -= eps
            if i == j:
                fpp = _neg_loglik_generic(pi_p, returns, regressors)
                fmm = _neg_loglik_generic(pi_m, returns, regressors)
                H[i, j] = (fpp - 2 * f0 + fmm) / (eps ** 2)
            else:
                pij_pp = best_params.copy(); pij_pp[i] += eps; pij_pp[j] += eps
                pij_pm = best_params.copy(); pij_pm[i] += eps; pij_pm[j] -= eps
                pij_mp = best_params.copy(); pij_mp[i] -= eps; pij_mp[j] += eps
                pij_mm = best_params.copy(); pij_mm[i] -= eps; pij_mm[j] -= eps
                fpp = _neg_loglik_generic(pij_pp, returns, regressors)
                fpm = _neg_loglik_generic(pij_pm, returns, regressors)
                fmp = _neg_loglik_generic(pij_mp, returns, regressors)
                fmm = _neg_loglik_generic(pij_mm, returns, regressors)
                H[i, j] = (fpp - fpm - fmp + fmm) / (4 * eps ** 2)
    try:
        cov = np.linalg.pinv(H)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except Exception:
        cov = np.eye(k) * np.nan
        se = np.full(k, np.nan)
    return {
        'label': label,
        'params': best_params,
        'loglik': -best_ll,
        'se': se,
        'cov': cov,
        'converged': best_res is not None and best_res.success,
    }


# ==========================================================================
# BUILD FRAME
# ==========================================================================

def build_analysis_frame():
    prices = load_prices()
    vix = load_vix()
    earnings = load_earnings_dates(CODE)
    guidance = load_capex_guidance()

    # Align VIX onto TSMC trading days (ffill).
    vix_al = vix.reindex(prices.index, method='ffill')
    log_ret = np.log(prices / prices.shift(1))

    df = pd.DataFrame({
        'price': prices,
        'log_ret': log_ret,
        'VIX': vix_al,
    }).dropna()
    # Drop extreme returns (same as K1104).
    df = df[df['log_ret'].abs() <= 0.30]

    trading_days = df.index

    # Position earnings events on trading days (K1104 convention).
    eav_all = np.zeros(len(trading_days), dtype=float)
    eav_change = np.zeros(len(trading_days), dtype=float)
    eav_stable = np.zeros(len(trading_days), dtype=float)

    positions = trading_days.searchsorted(earnings['date'].values)
    guidance_by_date = {
        pd.Timestamp(row.announce_date).normalize(): int(row.guide_updated)
        for row in guidance.itertuples(index=False)
    }

    matched_events = []
    unmatched = 0
    for i, ea in earnings.iterrows():
        pos = int(positions[i])
        if pos >= len(trading_days):
            continue
        flag = guidance_by_date.get(pd.Timestamp(ea['date']).normalize(), None)
        eav_all[pos] = 1.0
        if flag is None:
            unmatched += 1
            # Treat unmatched (shouldn't happen with our table) as stable.
            eav_stable[pos] = 1.0
            matched_events.append(
                {'date': str(ea['date'].date()), 'pos': pos, 'flag': 'UNMATCHED'})
        elif flag == 1:
            eav_change[pos] = 1.0
            matched_events.append(
                {'date': str(ea['date'].date()), 'pos': pos, 'flag': 'change'})
        else:
            eav_stable[pos] = 1.0
            matched_events.append(
                {'date': str(ea['date'].date()), 'pos': pos, 'flag': 'stable'})

    df['EAV_all'] = eav_all
    df['EAV_change'] = eav_change
    df['EAV_stable'] = eav_stable

    return df, matched_events, unmatched


# ==========================================================================
# MAIN EXPERIMENT
# ==========================================================================

def run_experiment():
    print(f"=== {EXPERIMENT_ID} ===")
    df, matched_events, unmatched = build_analysis_frame()
    print(f"Sample: {df.index[0].date()} → {df.index[-1].date()}")
    print(f"Obs: {len(df)}")
    print(f"Earnings events matched: {len(matched_events)}  "
          f"(unmatched: {unmatched})")
    n_change = int(df['EAV_change'].sum())
    n_stable = int(df['EAV_stable'].sum())
    print(f"  capex_change days: {n_change}")
    print(f"  capex_stable days: {n_stable}")
    print(f"  total EAV days:    {int(df['EAV_all'].sum())}")

    ret = df['log_ret'].values
    vix_vals = df['VIX'].values
    eav_all = df['EAV_all'].values
    eav_change = df['EAV_change'].values
    eav_stable = df['EAV_stable'].values

    # Pre-lag regressors (X[t] = VIX²_{t-1}, EAV_{t-1}).
    vix_lag = np.concatenate([[vix_vals[0]], vix_vals[:-1]])
    vix2_lag = vix_lag ** 2
    eav_all_lag = np.concatenate([[eav_all[0]], eav_all[:-1]])
    eav_change_lag = np.concatenate([[eav_change[0]], eav_change[:-1]])
    eav_stable_lag = np.concatenate([[eav_stable[0]], eav_stable[:-1]])

    diag = pre_estimation_diagnostics(ret, tag='TSMC log_ret 2014-2025')
    print("\n--- Pre-estimation diagnostics ---")
    for k_, v in diag.items():
        print(f"  {k_}: {v}")

    var0 = float(np.var(ret))
    vix2_mean = float(np.mean(vix2_lag)) + 1e-8
    eav_mean = float(np.mean(eav_all_lag)) + 1e-8
    theta2_init = var0 * 0.05 / max(eav_mean, 1e-4)

    # ---------- M1: GJR baseline (no VIX, no EAV) ----------
    regs_M1 = np.zeros((len(ret), 0))
    starts_M1 = [
        # Deliberately break α=γ symmetry so solver explores asymmetric leverage.
        [var0 * 0.1, 0.05, 0.03, 0.06, 0.90],
        [var0 * 0.05, 0.10, 0.02, 0.08, 0.88],
        [var0 * 0.2, 0.02, 0.07, 0.10, 0.80],
        [var0 * 0.01, 0.08, 0.04, 0.08, 0.85],
        [var0 * 0.1, 0.05, 0.02, 0.12, 0.83],
    ]
    # bounds: θ₀, ω, α, γ, β
    bounds_M1 = [(1e-8, 1e-2), (1e-6, 1.0), (1e-4, 0.3),
                 (1e-4, 0.3), (0.5, 0.999)]
    m1 = fit_model(ret, regs_M1, starts_M1, bounds_M1, label='M1_GJR',
                   maxiter=600)

    # ---------- M2: A4f-EAV standard (θ₁·VIX² + θ₂·EAV_all) ----------
    regs_M2 = np.column_stack([vix2_lag, eav_all_lag])
    # params: θ₀, θ₁, θ₂, ω, α, γ, β  — break α=γ symmetry
    starts_M2 = [
        [var0 * 0.1, var0 / vix2_mean, 0.0, 0.05, 0.03, 0.06, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init, 0.10, 0.02, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, theta2_init * 0.5, 0.02, 0.07, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init * 0.5, 0.08, 0.04, 0.08, 0.85],
        [var0 * 0.1, var0 / vix2_mean, theta2_init * 1.5, 0.05, 0.02, 0.12, 0.83],
    ]
    bounds_M2 = [(-1e-2, 1e-2), (1e-8, 1e-3), (-1e-2, 1e-2),
                 (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    # Seed M2 with M1's optimum (θ₀ picks up unconditional variance).
    if m1 is not None:
        m1p = m1['params']
        # M1 params: [θ₀, ω, α, γ, β]
        # M2 params: [θ₀, θ₁, θ₂, ω, α, γ, β]
        seed_from_m1 = [m1p[0], 1e-8, 0.0, m1p[1], m1p[2], m1p[3], m1p[4]]
        starts_M2 = [seed_from_m1] + starts_M2
    m2 = fit_model(ret, regs_M2, starts_M2, bounds_M2, label='M2_A4fEAV',
                   maxiter=600)

    # ---------- M3: A4f-EAV + capex split ----------
    regs_M3 = np.column_stack([vix2_lag, eav_change_lag, eav_stable_lag])
    # params: θ₀, θ₁, θ_change, θ_stable, ω, α, γ, β
    # IMPORTANT: deliberately use asymmetric starts so solver can explore
    # both θ_change > θ_stable and θ_change < θ_stable regions. All-zeros
    # start + identical init values creates a quasi-saddle that artificially
    # pulls both thetas to the same M2 solution.
    starts_M3 = [
        # 1) M2-like seed: θ_change = θ_stable (baseline)
        [var0 * 0.1, var0 / vix2_mean, theta2_init * 0.5, theta2_init * 0.5,
         0.05, 0.03, 0.06, 0.90],
        # 2) Capex-mechanism hypothesis: θ_change strong positive, θ_stable 0
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init * 2.0, 0.0,
         0.10, 0.02, 0.08, 0.88],
        # 3) Reverse: θ_change 0, θ_stable positive (null to mechanism)
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.0, theta2_init * 2.0,
         0.02, 0.07, 0.10, 0.80],
        # 4) Both negative (fabless-like behaviour, for symmetry)
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init * 0.5,
         -theta2_init * 0.5, 0.08, 0.04, 0.08, 0.85],
        # 5) Opposite signs: θ_change positive, θ_stable negative
        [var0 * 0.1, var0 / vix2_mean, theta2_init, -theta2_init,
         0.05, 0.02, 0.12, 0.83],
        # 6) Strong asymmetric
        [var0 * 0.1, var0 / vix2_mean, theta2_init * 3.0,
         -theta2_init * 0.5, 0.06, 0.04, 0.08, 0.88],
        # 7) Mildly asymmetric (small but non-zero)
        [var0 * 0.1, var0 / vix2_mean, 1e-5, -1e-5,
         0.05, 0.03, 0.07, 0.90],
    ]
    bounds_M3 = [(-1e-2, 1e-2), (1e-8, 1e-3),
                 (-1e-2, 1e-2), (-1e-2, 1e-2),
                 (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    # Critical: seed M3 with M2's optimum (θ_change = θ_stable = θ₂_M2).
    # This guarantees M3's loglik >= M2's (nested model property).
    if m2 is not None:
        m2_params = m2['params']
        # M2 params: [θ₀, θ₁, θ₂, ω, α, γ, β]
        # M3 params: [θ₀, θ₁, θ_change, θ_stable, ω, α, γ, β]
        seed_from_m2 = [
            m2_params[0], m2_params[1], m2_params[2], m2_params[2],
            m2_params[3], m2_params[4], m2_params[5], m2_params[6],
        ]
        # Also seed small perturbations around M2 so solver can improve
        seed_m2_plus_eps = [
            m2_params[0], m2_params[1],
            m2_params[2] + abs(m2_params[2]) * 0.5 + 1e-6,
            m2_params[2] - abs(m2_params[2]) * 0.5 - 1e-6,
            m2_params[3], m2_params[4], m2_params[5], m2_params[6],
        ]
        seed_m2_minus_eps = [
            m2_params[0], m2_params[1],
            m2_params[2] - abs(m2_params[2]) * 0.5 - 1e-6,
            m2_params[2] + abs(m2_params[2]) * 0.5 + 1e-6,
            m2_params[3], m2_params[4], m2_params[5], m2_params[6],
        ]
        starts_M3 = [seed_from_m2, seed_m2_plus_eps, seed_m2_minus_eps] + starts_M3

    m3 = fit_model(ret, regs_M3, starts_M3, bounds_M3,
                   label='M3_A4fEAV_capex_split', maxiter=600)

    def param_dict(m, names):
        if m is None:
            return None
        return {
            'label': m['label'],
            'params': {n: float(v) for n, v in zip(names, m['params'])},
            'se': {n: float(s) for n, s in zip(names, m['se'])},
            'loglik': float(m['loglik']),
            'converged': bool(m['converged']),
        }

    M1_names = ['theta0', 'omega_g', 'alpha', 'gamma', 'beta']
    M2_names = ['theta0', 'theta1', 'theta2', 'omega_g', 'alpha', 'gamma', 'beta']
    M3_names = ['theta0', 'theta1', 'theta_capex_change', 'theta_capex_stable',
                'omega_g', 'alpha', 'gamma', 'beta']

    m1_d = param_dict(m1, M1_names)
    m2_d = param_dict(m2, M2_names)
    m3_d = param_dict(m3, M3_names)

    if m1 is None or m2 is None or m3 is None:
        raise RuntimeError("Some MLE fits failed")

    # LR test M3 vs M2
    lr_stat = 2 * (m3['loglik'] - m2['loglik'])
    lr_pval = 1 - stats.chi2.cdf(lr_stat, df=1)  # one extra free parameter

    # Wald test θ_change = θ_stable
    idx_change = M3_names.index('theta_capex_change')
    idx_stable = M3_names.index('theta_capex_stable')
    diff = m3['params'][idx_change] - m3['params'][idx_stable]
    cov = m3['cov']
    var_diff = (cov[idx_change, idx_change]
                + cov[idx_stable, idx_stable]
                - 2 * cov[idx_change, idx_stable])
    se_diff = float(np.sqrt(max(var_diff, 1e-30)))
    wald_t = float(diff / se_diff) if se_diff > 0 else np.nan
    wald_p = 2 * (1 - stats.norm.cdf(abs(wald_t))) if np.isfinite(wald_t) else np.nan

    # t-test θ_change > 0 one-sided
    t_change = m3['params'][idx_change] / m3['se'][idx_change] if m3['se'][idx_change] > 0 else np.nan
    p_change_one_sided = 1 - stats.norm.cdf(t_change) if np.isfinite(t_change) else np.nan

    # Bootstrap (resample EAV event-days only; keep non-event backbone)
    rng = np.random.default_rng(42)
    change_positions = np.where(eav_change_lag > 0)[0]
    stable_positions = np.where(eav_stable_lag > 0)[0]
    n_reps = int(os.environ.get('K1108_BOOT_REPS', '1000'))
    time_budget_sec = int(os.environ.get('K1108_BOOT_TIME_BUDGET', '900'))
    boot_diffs = []
    boot_start_time = time.time()
    print(f"\n--- Bootstrap ({n_reps} reps, seed 42, "
          f"time budget {time_budget_sec}s) ---", flush=True)
    for b in range(n_reps):
        # Time budget guard — exit early with whatever we have.
        if time.time() - boot_start_time > time_budget_sec:
            print(f"  time budget {time_budget_sec}s exceeded at rep {b}; "
                  f"stopping with {len(boot_diffs)} successful reps",
                  flush=True)
            break
        # resample with replacement separately within each class
        cp_boot = rng.choice(change_positions, size=len(change_positions),
                             replace=True)
        sp_boot = rng.choice(stable_positions, size=len(stable_positions),
                             replace=True)
        eav_c_boot = np.zeros_like(eav_change_lag)
        eav_s_boot = np.zeros_like(eav_stable_lag)
        eav_c_boot[cp_boot] = 1.0
        eav_s_boot[sp_boot] = 1.0
        regs_boot = np.column_stack([vix2_lag, eav_c_boot, eav_s_boot])
        # Use M3 point estimate as hot start (+ one perturbation); skip Hessian.
        m3_hot = [
            m3['params'][0], m3['params'][1],
            m3['params'][2], m3['params'][3],
            m3['params'][4], m3['params'][5],
            m3['params'][6], m3['params'][7],
        ]
        m3_hot2 = m3_hot.copy()
        m3_hot2[2] = m3_hot[3]
        m3_hot2[3] = m3_hot[2]  # swap
        # Tight maxiter + relaxed ftol so pathological samples terminate fast.
        mb = fit_model(ret, regs_boot, [m3_hot, m3_hot2], bounds_M3,
                       label=f'M3_boot_{b}', with_hessian=False,
                       maxiter=80, ftol=1e-6)
        if mb is None:
            continue
        boot_diffs.append(mb['params'][idx_change] - mb['params'][idx_stable])
        if (b + 1) % 50 == 0:
            elapsed = time.time() - START_TIME
            print(f"  boot {b+1}/{n_reps}  elapsed {elapsed:.0f}s  "
                  f"mean={np.mean(boot_diffs):+.3e}  n_good={len(boot_diffs)}",
                  flush=True)
            # Save checkpoint in case the long run gets killed.
            try:
                np.save(SCRIPT_DIR / 'boot_diffs_checkpoint.npy',
                        np.array(boot_diffs))
            except Exception:
                pass
    boot_diffs = np.array(boot_diffs)
    if len(boot_diffs) >= 20:
        ci_lo, ci_hi = np.percentile(boot_diffs, [2.5, 97.5])
        boot_se = float(np.std(boot_diffs, ddof=1))
        boot_p_one = float((boot_diffs <= 0).mean())
    else:
        ci_lo = ci_hi = boot_se = boot_p_one = np.nan

    # Compute τ series for visualisation under M3
    theta0_hat, theta1_hat, th_ch, th_st = m3['params'][:4]
    tau_series = np.maximum(
        theta0_hat + theta1_hat * vix2_lag + th_ch * eav_change_lag
        + th_st * eav_stable_lag, 1e-16)

    tau_on_change = tau_series[eav_change_lag > 0].mean()
    tau_on_stable = tau_series[eav_stable_lag > 0].mean()
    tau_nonevent = tau_series[eav_all_lag == 0].mean()
    jump_change = (tau_on_change - tau_nonevent) / tau_nonevent * 100
    jump_stable = (tau_on_stable - tau_nonevent) / tau_nonevent * 100

    print("\n--- M3 coefficients ---")
    for n in M3_names:
        v = m3_d['params'][n]
        se = m3_d['se'][n]
        t = v / se if se > 0 else np.nan
        print(f"  {n:22s} = {v:+.4e}  SE={se:.4e}  t={t:+.3f}")
    print(f"\nLR(M3 vs M2): stat={lr_stat:.3f}, p={lr_pval:.4f}")
    print(f"Wald (θ_change = θ_stable): diff={diff:+.4e}  "
          f"SE_diff={se_diff:.4e}  t={wald_t:+.3f}  p={wald_p:.4f}")
    print(f"One-sided θ_change > 0: t={t_change:+.3f}  "
          f"p={p_change_one_sided:.4f}")
    if np.isfinite(ci_lo):
        print(f"Bootstrap diff: mean={np.mean(boot_diffs):+.4e}  "
              f"SE={boot_se:.4e}  95% CI=[{ci_lo:+.4e}, {ci_hi:+.4e}]")
        print(f"Bootstrap one-sided p (diff<=0): {boot_p_one:.4f}")

    verdict = decide_verdict(
        theta_change=m3['params'][idx_change],
        theta_stable=m3['params'][idx_stable],
        wald_t=wald_t, wald_p=wald_p,
        t_change=t_change, p_change_one=p_change_one_sided,
        lr_p=lr_pval, unmatched=unmatched)
    print(f"\n>>> VERDICT: {verdict['label']}")
    for b in verdict['bullets']:
        print(f"    - {b}")

    # ---- Plots ----
    make_theta_plot(m2, m3, M2_names, M3_names)
    make_tau_timeseries_plot(df, tau_series, eav_change_lag, eav_stable_lag)

    # ---- Write results JSON ----
    results = {
        'experiment_id': EXPERIMENT_ID,
        'timestamp': pd.Timestamp.utcnow().isoformat(),
        'data_source': [
            'TSMC 2330.TW yfinance cache (experiments/k1104/data/2330.TW.parquet)',
            '^VIX yfinance cache (experiments/k1104/data/IDX_VIX.parquet)',
            '財報公告日.txt (TWSE earnings announcement dates)',
            'TSMC IR public capex guidance press releases (hand-coded '
            'in k1108_fetch_capex.py — 48 announcements 2014-2025)',
        ],
        'sample': {
            'start': str(df.index[0].date()),
            'end': str(df.index[-1].date()),
            'n_obs': int(len(df)),
            'n_earnings_events': int(df['EAV_all'].sum()),
            'n_capex_change_events': n_change,
            'n_capex_stable_events': n_stable,
            'n_unmatched_events': int(unmatched),
        },
        'pre_estimation_diagnostics': diag,
        'models': {
            'M1_GJR_baseline': m1_d,
            'M2_A4fEAV_standard': m2_d,
            'M3_A4fEAV_capex_split': m3_d,
        },
        'tests': {
            'LR_M3_vs_M2': {
                'stat': float(lr_stat),
                'df': 1,
                'p_value': float(lr_pval),
                'description': 'Does adding capex split improve fit?'},
            'Wald_change_eq_stable': {
                'theta_change_minus_stable': float(diff),
                'se_diff': float(se_diff),
                't_stat': float(wald_t),
                'p_value_two_sided': float(wald_p),
                'description': 'H0: θ_change = θ_stable'},
            't_test_change_positive': {
                't_stat': float(t_change),
                'p_value_one_sided': float(p_change_one_sided),
                'description': 'H0: θ_change <= 0 vs H1: > 0'},
            'Bootstrap_diff': {
                'n_reps': int(len(boot_diffs)),
                'mean': float(np.mean(boot_diffs)) if len(boot_diffs) else None,
                'se': float(boot_se) if np.isfinite(boot_se) else None,
                'ci_2.5': float(ci_lo) if np.isfinite(ci_lo) else None,
                'ci_97.5': float(ci_hi) if np.isfinite(ci_hi) else None,
                'p_one_sided_leq_0': float(boot_p_one) if np.isfinite(boot_p_one) else None},
        },
        'tau_diagnostics_M3': {
            'tau_on_capex_change': float(tau_on_change),
            'tau_on_capex_stable': float(tau_on_stable),
            'tau_non_event': float(tau_nonevent),
            'tau_jump_change_pct': float(jump_change),
            'tau_jump_stable_pct': float(jump_stable),
        },
        'matched_events_sample': matched_events[:10],
        'verdict': verdict,
        'references': [
            'K1067/K1067b/K1067c single-firm A4f-EAV series',
            'K1103 τ-lag fixed rolling estimates',
            'K1104 firm-level covariate regression',
            'Engle, Ghysels & Sohn (2013) GARCH-MIDAS. RES 95(3).',
            'Patton (2011) Volatility forecast comparison. JoE 160:246-256.',
            'Harvey et al. (2016) t>3.0 threshold for multiple testing.',
        ],
        'runtime_seconds': float(time.time() - START_TIME),
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written: {RESULTS_PATH}")
    return results


def decide_verdict(theta_change, theta_stable, wald_t, wald_p,
                   t_change, p_change_one, lr_p, unmatched):
    bullets = []
    # Strong confirmation: change >> stable, Wald p<0.05, θ_change >0
    if (np.isfinite(wald_p) and wald_p < 0.05
            and theta_change > 2 * abs(theta_stable)
            and t_change > 1.96):
        label = 'MECHANISM_CONFIRMED'
        bullets.append(
            f"Wald p={wald_p:.3f} < 0.05: θ_change ≠ θ_stable significant")
        bullets.append(
            f"θ_change={theta_change:+.3e} > 2× |θ_stable|={theta_stable:+.3e}")
        bullets.append(
            f"θ_change one-sided p={p_change_one:.3f} — foundry vol burst "
            f"driven by capex guidance revisions")
    elif (np.isfinite(wald_p) and wald_p < 0.10
          and abs(theta_change) > abs(theta_stable)
          and np.sign(theta_change) == np.sign(theta_change - theta_stable)):
        label = 'MECHANISM_PARTIAL'
        bullets.append(f"Wald p={wald_p:.3f}: marginal evidence (0.05-0.10)")
        bullets.append(
            f"θ_change larger magnitude than θ_stable but not statistically "
            f"dominant")
    elif (np.isfinite(wald_p) and wald_p >= 0.10
          and abs(theta_change - theta_stable) / max(abs(theta_change), 1e-10) < 0.5):
        label = 'MECHANISM_REJECTED'
        bullets.append(
            f"Wald p={wald_p:.3f} >> 0.05: θ_change ≈ θ_stable "
            f"(no differential effect)")
        bullets.append(
            "Capex guidance flag does NOT explain TSMC θ₂ structure — "
            "both types of earnings days behave similarly")
    else:
        label = 'INCONCLUSIVE'
        bullets.append(
            f"Wald p={wald_p:.3f}, θ_change={theta_change:+.3e}, "
            f"θ_stable={theta_stable:+.3e}")
        bullets.append(
            "Evidence is mixed or low-powered; N=25 / N=23 event days is "
            "the main limitation")
    if unmatched:
        bullets.append(f"⚠ {unmatched} earnings events unmatched to capex "
                       f"guidance table (treated as stable)")
    return {'label': label, 'bullets': bullets}


# ==========================================================================
# PLOTTING
# ==========================================================================

def make_theta_plot(m2, m3, M2_names, M3_names):
    fig, ax = plt.subplots(figsize=(8, 5))
    # bar chart: M2 θ₂, M3 θ_change, M3 θ_stable with 95% CI
    points = [
        ('M2: θ₂\n(all EAV)',
         m2['params'][M2_names.index('theta2')],
         m2['se'][M2_names.index('theta2')], 'tab:blue'),
        ('M3: θ_change\n(capex revised)',
         m3['params'][M3_names.index('theta_capex_change')],
         m3['se'][M3_names.index('theta_capex_change')], 'tab:green'),
        ('M3: θ_stable\n(capex held)',
         m3['params'][M3_names.index('theta_capex_stable')],
         m3['se'][M3_names.index('theta_capex_stable')], 'tab:orange'),
    ]
    xs = np.arange(len(points))
    vals = [p[1] for p in points]
    errs = [1.96 * p[2] for p in points]
    colors = [p[3] for p in points]
    ax.bar(xs, vals, yerr=errs, color=colors, capsize=6, alpha=0.75)
    ax.set_xticks(xs)
    ax.set_xticklabels([p[0] for p in points])
    ax.axhline(0, color='black', lw=0.8)
    ax.set_ylabel('θ (τ-scale shift on EAV day)')
    ax.set_title('K1108: TSMC A4f-EAV θ split by capex-guidance flag\n'
                 '(error bars = ±1.96·SE)')
    plt.tight_layout()
    plt.savefig(PLOT_THETA, dpi=120)
    plt.close()
    print(f"Saved {PLOT_THETA}")


def make_tau_timeseries_plot(df, tau_series, eav_change_lag, eav_stable_lag):
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(df.index, tau_series, lw=0.8, color='tab:blue', alpha=0.7,
            label='τ_t (M3)')
    change_mask = eav_change_lag > 0
    stable_mask = eav_stable_lag > 0
    ax.scatter(df.index[change_mask], tau_series[change_mask],
               color='tab:green', s=60, marker='^', label='capex_change day',
               zorder=5, edgecolor='black', linewidth=0.5)
    ax.scatter(df.index[stable_mask], tau_series[stable_mask],
               color='tab:orange', s=50, marker='o', label='capex_stable day',
               zorder=5, edgecolor='black', linewidth=0.5)
    ax.set_xlabel('Date')
    ax.set_ylabel('τ_t (low-freq variance component)')
    ax.set_title(f'K1108: TSMC τ_t series — capex-change vs capex-stable '
                 f'earnings events')
    ax.legend(loc='best')
    plt.tight_layout()
    plt.savefig(PLOT_TAU, dpi=120)
    plt.close()
    print(f"Saved {PLOT_TAU}")


# ==========================================================================

if __name__ == '__main__':
    try:
        results = run_experiment()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
