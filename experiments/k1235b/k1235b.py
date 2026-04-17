#!/usr/bin/env python3
"""
K1235b: Paper 9 Table 6 A4f spec replication on FEZ + STOXX50E
==============================================================

Purpose: Decisive test of Paper 9 Table 6 values (FEZ t=3.45, STOXX50E t=3.64)
  under the EXACT A4f spec used by the paper's primary SPY result.

Context:
  - K1235 (commit 9bbca5b0) applied K949 log-exp spec and got FEZ t=4.03,
    STOXX50E t=5.01 — MISMATCH vs paper 3.45 / 3.64.
  - Paper 9 Table 6 (line 533) explicitly states "OOS: 2019-2026" and A4f spec.
  - K1235b uses A4f spec verbatim per K988/Paper 9 main.tex to decide:
      * MATCH (within Harvey tolerance ±0.5): Paper Table 6 vindicated under
        A4f; R2 path (b) — spec-clarification footnote only.
      * MISMATCH: Paper Table 6 T values cannot be reproduced under either
        spec; R2 path (a) — errata required.

A4f spec (verbatim from Paper 9 main.tex Table 6 line 533 + K988 implementation):
  - tau_t = max(theta0 + theta1 * VIX_{t-1}^2, eps)   [VIX^2, not log-VIX]
  - Positivity floor eps = 1e-16
  - Short-run g_t: GJR(1,1,1) with FREE omega
    g_t = omega_g + alpha * u_{t-1}^2 + gamma * u_{t-1}^2 * I(u<0) + beta * g_{t-1}
  - u_{t-1} = r_{t-1} / sqrt(tau_t)  [contemporaneous normalization]
  - Joint MLE (6 params: theta0, theta1, omega_g, alpha, gamma, beta)
  - Returns in raw log-scale (NO *100 scaling — matches K988 SPY result t=4.03)
  - OOS: 2019-01-01 to 2026-04-15
  - WINDOW = 2000
  - REFIT_EVERY = 63  (quarterly)
  - Benchmark: plain GJR-GARCH(1,1) [matches paper's GJR benchmark in Table 6]

Difference vs K1235 (log-exp K949 spec):
  - log-exp tau (exp(theta0 + theta1 log VIX)) → VIX^2 linear tau
  - Constrained omega (E[g]=1) → FREE omega
  - OOS 2016-2025 → OOS 2019-2026
  - REFIT 21 → REFIT 63
  - Returns *100 → Returns raw log-scale

Tickers:
  FEZ        — paper claim t=3.45
  ^STOXX50E  — paper claim t=3.64

Evaluation:
  - QLIKE on r^2 (Patton 2011)
  - DM test vs GJR with Newey-West HAC + Harvey (1997) small-sample correction
  - Verdict tolerance vs paper:
      |diff| < 0.2  → MATCH
      |diff| < 0.5  → BORDERLINE
      otherwise     → MISMATCH
  - Paper 9 R2 recommendation:
      All MATCH/BORDERLINE → path (b) spec-clarification footnote
      Any MISMATCH         → path (a) errata with K1235/K1235b replacement

Lookahead protection:
  - VIX_{t-1} lagged by construction (see vix_lag assignment)
  - r_{t-1} used for g_t update; forecast is for r_t^2
  - No same-day signal * same-day return

Reproducibility:
  - np.random.seed(42) fixed
  - Same MLE starts / bounds as K988 A4f_vix2_free_omega
"""

import os
import sys
import json
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from scipy import stats, optimize
from scipy.stats import norm, spearmanr
from numba import njit

import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1235b"
OUTPUT_DIR = Path(__file__).resolve().parent

# ============================================================
# Configuration — A4f spec from Paper 9 main.tex Table 6
# ============================================================
ASSETS = ['FEZ', '^STOXX50E']
ASSET_LABELS = {'FEZ': 'FEZ', '^STOXX50E': 'STOXX50E'}

DATA_START = '2005-01-01'
DATA_END = '2026-04-15'
OOS_START = '2019-01-01'     # A4f spec per Paper 9 Table 6 note (line 533)
WINDOW = 2000                # K988 A4f verbatim
REFIT_EVERY = 63             # K988 A4f verbatim (quarterly)

PAPER_CLAIMS = {
    'FEZ': 3.45,
    '^STOXX50E': 3.64,
}

# Verdict tolerance bands (Harvey-corrected t-stat)
TOL_MATCH = 0.2       # |t_k1235b - t_paper| < 0.2 → MATCH
TOL_BORDERLINE = 0.5  # |diff| < 0.5 → BORDERLINE

# ============================================================
# Data loading — FEZ, ^STOXX50E, ^VIX
# ============================================================
print("=" * 70)
print(f"{EXPERIMENT_ID}: Paper 9 Table 6 A4f spec replication on FEZ + STOXX50E")
print("=" * 70)
print(f"\n[1] Downloading data from yfinance ({DATA_START}..{DATA_END})...")

price_data = {}
for ticker in ASSETS + ['^VIX']:
    df = yf.download(ticker, start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_data[ticker] = df['Close']
    print(f"  {ticker}: {len(df)} rows, range={df.index[0].date()}..{df.index[-1].date()}")

prices_df = pd.DataFrame(price_data).ffill()
vix_close = prices_df['^VIX']

# ============================================================
# GJR benchmark (K988 verbatim)
# ============================================================
@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# ============================================================
# A4f (vix_squared, free omega) — verbatim K988 implementation
# ============================================================
def fit_a4f(returns, vix_vals):
    """
    Fit A4f: MF-GJR with tau_t = max(theta0 + theta1 * VIX_{t-1}^2, eps),
    free omega, contemporaneous normalization u_{t-1} = r_{t-1}/sqrt(tau_t).

    Returns 6-element param vector [theta0, theta1, omega_g, alpha, gamma, beta]
    or None if optimization failed.
    """
    n = len(returns)
    # Lagged VIX (no lookahead): vix_lag[t] = VIX_{t-1}
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    vix2_mean = np.mean(vix_lag**2) + 1e-8
    var0 = np.var(returns)

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if alpha + gamma_p / 2.0 + beta >= 0.999:
            return 1e10

        persist = alpha + gamma_p / 2.0 + beta
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg  # free_omega → init at E[g]
        ll = 0.0

        for t in range(1, n):
            # Contemporaneous normalization (denom_mode='tau_t')
            u_prev = returns[t-1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2)
                              + returns[t]**2 / sigma2)
        return -ll

    # K988 A4f starts (data-adapted)
    starts = [
        [var0 * 0.1,  var0 / vix2_mean,       0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def compute_tau_a4f(params, vix_lag):
    """tau_t = max(theta0 + theta1 * VIX_{t-1}^2, 1e-16)."""
    theta0, theta1 = params[0], params[1]
    return np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)


# ============================================================
# OOS loop per ticker
# ============================================================
def run_oos_for_ticker(ticker, ret_series, vix_series):
    label = ASSET_LABELS.get(ticker, ticker)
    print(f"\n{'='*60}")
    print(f"{label} (ticker={ticker}): A4f OOS forecasting")
    print(f"{'='*60}")

    # Align series
    common_idx = ret_series.index.intersection(vix_series.index)
    ret_s = ret_series.loc[common_idx].copy()
    vix_s = vix_series.loc[common_idx].copy()
    mask_f = np.isfinite(ret_s.values) & np.isfinite(vix_s.values)
    ret_s = ret_s[mask_f]
    vix_s = vix_s[mask_f]

    dates = ret_s.index
    ret = ret_s.values
    vix = vix_s.values

    oos_mask = dates >= OOS_START
    oos_indices = np.where(oos_mask)[0]
    n_oos = len(oos_indices)
    print(f"  Total days: {len(dates)}, OOS days: {n_oos}")
    print(f"  OOS period: {dates[oos_indices[0]].date()}..{dates[oos_indices[-1]].date()}")

    fc_gjr = np.full(n_oos, np.nan)
    fc_a4f = np.full(n_oos, np.nan)

    state_gjr = {'params': None, 'h': None}
    state_a4f = {'params': None, 'g': None, 'tau_prev': None}

    refit_count = 0

    for t_idx, abs_idx in enumerate(oos_indices):
        if t_idx % 250 == 0:
            elapsed = time.time() - START_TIME
            print(f"  {label}: OOS {t_idx}/{n_oos} ({elapsed:.0f}s)")

        need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

        if need_refit:
            refit_count += 1
            train_start = max(0, abs_idx - WINDOW)
            train_ret = ret[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]

            # GJR fit
            gjr_p = fit_gjr(train_ret)
            if gjr_p is not None:
                state_gjr['params'] = gjr_p
                h = np.var(train_ret)
                for i in range(1, len(train_ret)):
                    h = gjr_forecast_1step(gjr_p, h, train_ret[i-1])
                state_gjr['h'] = h

            # A4f fit
            a4f_p = fit_a4f(train_ret, train_vix)
            if a4f_p is not None:
                state_a4f['params'] = a4f_p
                theta0, theta1, omega_g, alpha, gamma_p, beta = a4f_p
                n_tr = len(train_ret)
                vix_lag_tr = np.empty(n_tr)
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                tau_tr = compute_tau_a4f(a4f_p, vix_lag_tr)

                persist = alpha + gamma_p / 2.0 + beta
                eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg  # free omega init at E[g]
                for i in range(1, n_tr):
                    u_prev = train_ret[i-1] / np.sqrt(max(tau_tr[i], 1e-16))
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha * u_prev**2 + asym + beta * g
                    g = max(g, 1e-10)
                state_a4f['g'] = g
                state_a4f['tau_prev'] = tau_tr[-1]

        # --- Generate forecast for abs_idx using t-1 information ---

        # GJR
        if state_gjr['params'] is not None:
            h_prev = state_gjr['h']
            r_prev = ret[abs_idx - 1]
            h_new = gjr_forecast_1step(state_gjr['params'], h_prev, r_prev)
            fc_gjr[t_idx] = h_new
            state_gjr['h'] = h_new

        # A4f
        if state_a4f['params'] is not None:
            theta0, theta1, omega_g, alpha, gamma_p, beta = state_a4f['params']
            v_lag = vix[abs_idx - 1]              # VIX_{t-1}
            tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)
            r_prev = ret[abs_idx - 1]
            # Contemporaneous normalization: denominator = tau_t
            u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha * u_prev**2 + asym + beta * state_a4f['g']
            g_new = max(g_new, 1e-10)
            fc_a4f[t_idx] = tau_t * g_new
            state_a4f['g'] = g_new
            state_a4f['tau_prev'] = tau_t

    print(f"  {label}: {refit_count} refits done")

    # Evaluation on overlap
    r2_oos = ret[oos_indices] ** 2
    valid = np.isfinite(fc_gjr) & np.isfinite(fc_a4f) & (fc_gjr > 0) & (fc_a4f > 0) \
            & np.isfinite(r2_oos)
    n_valid = int(valid.sum())
    print(f"  Valid OOS observations: {n_valid}")

    if n_valid < 100:
        print(f"  [ERROR] Too few valid observations for {ticker}")
        return None

    r2_v = r2_oos[valid]
    fc_gjr_v = fc_gjr[valid]
    fc_a4f_v = fc_a4f[valid]
    oos_dates_v = dates[oos_indices][valid]

    ql_gjr = float(np.mean(np.log(fc_gjr_v) + r2_v / fc_gjr_v))
    ql_a4f = float(np.mean(np.log(fc_a4f_v) + r2_v / fc_a4f_v))

    rho_gjr, _ = spearmanr(fc_gjr_v, r2_v)
    rho_a4f, _ = spearmanr(fc_a4f_v, r2_v)

    print(f"  QLIKE GJR = {ql_gjr:.4f}, QLIKE A4f = {ql_a4f:.4f}")
    print(f"  Spearman rho — GJR: {rho_gjr:.4f}, A4f: {rho_a4f:.4f}")

    # DM test: A4f vs GJR (positive t = A4f better)
    loss_gjr = np.log(fc_gjr_v) + r2_v / fc_gjr_v
    loss_a4f = np.log(fc_a4f_v) + r2_v / fc_a4f_v
    d = loss_gjr - loss_a4f  # positive = A4f better

    T = len(d)
    d_mean = float(np.mean(d))
    max_lag = int(np.floor(T ** (1/3)))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1.0 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j

    se_d = np.sqrt(max(hac_var / T, 1e-20))
    dm_t = d_mean / se_d if se_d > 0 else 0.0
    # Harvey correction (h=1): t* = t * sqrt((T + 1 - 2 + 1/T) / T)
    dm_t_harvey = dm_t * np.sqrt((T + 1 - 2 + 1.0/T) / T)
    dm_p_raw = 2.0 * (1.0 - norm.cdf(abs(dm_t)))
    dm_p_harvey = 2.0 * (1.0 - norm.cdf(abs(dm_t_harvey)))

    print(f"  DM (A4f vs GJR): t={dm_t:.3f}, t_harvey={dm_t_harvey:.3f}, "
          f"p_harvey={dm_p_harvey:.4g}")

    # Paper comparison
    paper_t = PAPER_CLAIMS.get(ticker)
    diff = dm_t_harvey - paper_t
    abs_diff = abs(diff)
    if abs_diff < TOL_MATCH:
        verdict = 'MATCH'
    elif abs_diff < TOL_BORDERLINE:
        verdict = 'BORDERLINE'
    else:
        verdict = 'MISMATCH'
    pct_diff = (diff / paper_t) * 100 if paper_t != 0 else 0.0

    print(f"  Paper claim t={paper_t:.2f}, K1235b t_harvey={dm_t_harvey:.3f}, "
          f"diff={diff:+.3f} ({pct_diff:+.1f}%), verdict={verdict}")

    qlike_imp_pct = (ql_gjr - ql_a4f) / abs(ql_gjr) * 100

    result = {
        'ticker': ticker,
        'label': label,
        'n_oos': n_valid,
        'oos_period': f"{oos_dates_v[0].date()} to {oos_dates_v[-1].date()}",
        'GJR': {'QLIKE': ql_gjr, 'Spearman_rho': float(rho_gjr)},
        'A4f': {'QLIKE': ql_a4f, 'Spearman_rho': float(rho_a4f)},
        'QLIKE_improvement_pct': float(qlike_imp_pct),
        'DM_A4f_vs_GJR': {
            't_stat': float(dm_t),
            't_harvey': float(dm_t_harvey),
            'p_value_raw': float(dm_p_raw),
            'p_value_harvey': float(dm_p_harvey),
            'significant_harvey3': bool(abs(dm_t_harvey) > 3.0),
            'mean_loss_diff': d_mean,
            'hac_lag': int(max_lag),
            'n_effective': int(T),
        },
        'paper_comparison': {
            'paper_claimed_t': float(paper_t),
            'k1235b_t_harvey': float(dm_t_harvey),
            'diff': float(diff),
            'abs_diff': float(abs_diff),
            'pct_diff': float(pct_diff),
            'verdict': verdict,
            'tolerance_match_lt': TOL_MATCH,
            'tolerance_borderline_lt': TOL_BORDERLINE,
            'note': 'A4f spec: tau=VIX^2 + free omega + OOS 2019-2026 + refit=63. '
                    'Verdict reflects reproducibility under paper-declared spec.',
        },
        'a4f_params': {
            'theta0': float(state_a4f['params'][0]) if state_a4f['params'] is not None else None,
            'theta1': float(state_a4f['params'][1]) if state_a4f['params'] is not None else None,
            'omega_g': float(state_a4f['params'][2]) if state_a4f['params'] is not None else None,
            'alpha': float(state_a4f['params'][3]) if state_a4f['params'] is not None else None,
            'gamma': float(state_a4f['params'][4]) if state_a4f['params'] is not None else None,
            'beta': float(state_a4f['params'][5]) if state_a4f['params'] is not None else None,
        },
    }

    diag = {
        'dates': oos_dates_v,
        'r2': r2_v,
        'fc_gjr': fc_gjr_v,
        'fc_a4f': fc_a4f_v,
        'd': d,
    }
    return result, diag


# ============================================================
# Returns per asset & run
# ============================================================
print("\n[2] Building return series + A4f OOS loop per ticker...")

# Compute log returns aligned with VIX dates
returns_by_ticker = {}
for ticker in ASSETS:
    r = np.log(prices_df[ticker] / prices_df[ticker].shift(1)).dropna()
    returns_by_ticker[ticker] = r

all_results = {}
all_diag = {}
for ticker in ASSETS:
    out = run_oos_for_ticker(ticker, returns_by_ticker[ticker], vix_close)
    if out is not None:
        result, diag = out
        all_results[ticker] = result
        all_diag[ticker] = diag

# ============================================================
# Summary + Paper 9 R2 recommendation
# ============================================================
print("\n" + "=" * 70)
print("K1235b SUMMARY")
print("=" * 70)

summary_rows = []
for ticker in ASSETS:
    if ticker not in all_results:
        continue
    r = all_results[ticker]
    cmp_ = r['paper_comparison']
    dm = r['DM_A4f_vs_GJR']
    summary_rows.append({
        'Ticker': ticker,
        'Label': r['label'],
        'N_OOS': r['n_oos'],
        'QLIKE_GJR': r['GJR']['QLIKE'],
        'QLIKE_A4f': r['A4f']['QLIKE'],
        'Improve_pct': r['QLIKE_improvement_pct'],
        'DM_t_raw': dm['t_stat'],
        'DM_t_harvey': dm['t_harvey'],
        'p_harvey': dm['p_value_harvey'],
        'paper_claim': cmp_['paper_claimed_t'],
        'diff': cmp_['diff'],
        'verdict': cmp_['verdict'],
    })

df_sum = pd.DataFrame(summary_rows)
print("\n" + df_sum.to_string(index=False))

verdicts = [r['paper_comparison']['verdict'] for r in all_results.values()]
if all(v == 'MATCH' for v in verdicts):
    r2_path = 'b'
    r2_code = 'spec_clarification_footnote'
    r2_msg = ('All tickers MATCH under A4f spec. Paper 9 Table 6 values are '
              'reproducible — only a spec-clarification footnote is required '
              '(path b). No errata needed for FEZ/STOXX50E values.')
elif all(v in ('MATCH', 'BORDERLINE') for v in verdicts):
    r2_path = 'b'
    r2_code = 'spec_clarification_footnote_with_borderline_note'
    r2_msg = ('All tickers MATCH or BORDERLINE under A4f spec. Path (b): '
              'spec-clarification footnote with note on borderline divergence '
              '(|diff| < 0.5 Harvey). Errata not required.')
else:
    r2_path = 'a'
    r2_code = 'errata_required'
    r2_msg = ('At least one ticker MISMATCH under A4f spec. Paper 9 Table 6 '
              'values cannot be reproduced under either K949 log-exp (K1235) '
              'or A4f (K1235b) specs → path (a) full errata replacement '
              'required, citing K1235b as canonical source.')

print("\n" + "=" * 70)
print("PAPER 9 R2 RECOMMENDATION")
print("=" * 70)
print(f"Path: {r2_path}")
print(f"Code: {r2_code}")
print(f"Message: {r2_msg}")

# ============================================================
# Figures
# ============================================================
print("\n[3] Generating figures...")

# Load K1235 for side-by-side A4f vs K1235 comparison
try:
    k1235_json = Path('/Users/yhlai0911/Desktop/volpred-research/experiments/k1235/k1235_results.json')
    with open(k1235_json) as f:
        k1235_data = json.load(f)
except Exception:
    k1235_data = None

# Fig 1: Per-ticker cumulative QLIKE (A4f vs GJR)
fig, axes = plt.subplots(len(all_results), 1,
                          figsize=(12, 4 * max(len(all_results), 1)),
                          squeeze=False)
for idx, ticker in enumerate(ASSETS):
    if ticker not in all_diag:
        continue
    label = ASSET_LABELS[ticker]
    ax = axes[idx, 0]
    diag = all_diag[ticker]
    dates = diag['dates']
    r2_v = diag['r2']
    fc_gjr = diag['fc_gjr']
    fc_a4f = diag['fc_a4f']

    loss_gjr = np.log(fc_gjr) + r2_v / fc_gjr
    loss_a4f = np.log(fc_a4f) + r2_v / fc_a4f
    cum_gjr = np.cumsum(loss_gjr) / np.arange(1, len(loss_gjr) + 1)
    cum_a4f = np.cumsum(loss_a4f) / np.arange(1, len(loss_a4f) + 1)

    ax.plot(dates, cum_gjr, label='GJR', color='#f5a623', alpha=0.85)
    ax.plot(dates, cum_a4f, label='A4f', color='#d0021b', alpha=0.85)
    t_h = all_results[ticker]['DM_A4f_vs_GJR']['t_harvey']
    t_paper = PAPER_CLAIMS[ticker]
    verdict = all_results[ticker]['paper_comparison']['verdict']
    ax.set_title(f'{label}: cumulative-mean QLIKE (A4f spec) — '
                 f'K1235b t_harvey={t_h:.2f} vs paper={t_paper:.2f} [{verdict}]')
    ax.set_ylabel('QLIKE (cum mean)')
    ax.legend()
    ax.grid(alpha=0.3)

plt.tight_layout()
fig_path = OUTPUT_DIR / 'k1235b_qlike_timeseries.png'
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig_path}")

# Fig 2: A4f vs K1235 log-exp comparison (t_harvey side-by-side)
fig, ax = plt.subplots(1, 1, figsize=(10, 5))

labels_plot = []
paper_vals = []
k1235_vals = []
k1235b_vals = []
for ticker in ASSETS:
    if ticker not in all_results:
        continue
    labels_plot.append(ASSET_LABELS[ticker])
    paper_vals.append(PAPER_CLAIMS[ticker])
    k1235b_vals.append(all_results[ticker]['DM_A4f_vs_GJR']['t_harvey'])
    if k1235_data is not None and ticker in k1235_data.get('results', {}):
        k1235_vals.append(k1235_data['results'][ticker]['DM_MFvsGJR']['t_harvey'])
    else:
        k1235_vals.append(np.nan)

x = np.arange(len(labels_plot))
w = 0.25
ax.bar(x - w, paper_vals, w, label='Paper 9 Table 6 claim',
       color='#4a90d9', alpha=0.85)
ax.bar(x, k1235_vals, w, label='K1235 (log-exp K949 spec)',
       color='#f5a623', alpha=0.85)
ax.bar(x + w, k1235b_vals, w, label='K1235b (A4f spec)',
       color='#d0021b', alpha=0.85)
ax.axhline(y=3.0, color='gray', linestyle='--', alpha=0.4,
           label='Harvey threshold |t|=3.0')
ax.set_xticks(x)
ax.set_xticklabels(labels_plot)
ax.set_ylabel('Harvey-corrected DM t-stat (A4f or MF vs GJR)')
ax.set_title('K1235b A4f vs K1235 log-exp vs Paper 9 Table 6 claims')
ax.legend(fontsize=9)
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
fig_path2 = OUTPUT_DIR / 'k1235b_vs_k1235_vs_paper.png'
plt.savefig(fig_path2, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {fig_path2}")

# ============================================================
# Save JSON
# ============================================================
output = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Paper 9 Table 6 A4f spec decisive replication on FEZ + STOXX50E',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (daily Close, auto_adjust=True)',
    'tickers': ASSETS,
    'ticker_labels': ASSET_LABELS,
    'spec': 'A4f (Paper 9 main.tex Table 6): tau=max(theta0+theta1*VIX_{t-1}^2, 1e-16), '
            'free omega, contemporaneous u_{t-1}=r_{t-1}/sqrt(tau_t), '
            'GJR(1,1,1) short-run, joint MLE with L-BFGS-B',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'oos_start': OOS_START,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'seed': 42,
    'paper_claims': PAPER_CLAIMS,
    'tolerance_match_lt': TOL_MATCH,
    'tolerance_borderline_lt': TOL_BORDERLINE,
    'evaluation': 'QLIKE on r^2 (Patton 2011), DM test with Newey-West HAC + '
                  'Harvey (1997) small-sample correction; DM t positive = A4f better',
    'results': all_results,
    'summary_table': summary_rows,
    'paper9_r2_recommendation': {
        'path': r2_path,
        'code': r2_code,
        'message': r2_msg,
    },
    'context': {
        'prior_experiment': 'K1235 (log-exp K949 spec, OOS 2016-2025, refit 21) '
                            'MISMATCH: FEZ t=4.03 vs 3.45; STOXX50E t=5.01 vs 3.64',
        'k1235b_goal': 'Decisive test under paper-declared A4f spec. MATCH → path b; '
                       'MISMATCH → path a errata.',
    },
    'reproducibility': {
        'numpy_seed': 42,
        'mle_starts_per_fit': 3,
        'optimizer': 'scipy L-BFGS-B, maxiter=500',
        'yfinance_mode': 'auto_adjust=True',
    },
}

out_path = OUTPUT_DIR / 'k1235b_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved: {out_path}")

elapsed_total = time.time() - START_TIME
print(f"\n{EXPERIMENT_ID} complete in {elapsed_total:.0f}s.")
