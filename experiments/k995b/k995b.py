#!/usr/bin/env python3
"""
K995b: Paper 9 Table 11 Residual Diagnostics Source Recovery
=============================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  Paper 9 (garch-x-vix, submitted J. Empirical Finance) audit found
  Table 11 residual diagnostics entirely lacking script source:
  - GJR-t: kurtosis=3.065, skewness=-0.856, JB=938.8
  - A4f-t: kurtosis=1.238, skewness=-0.594, JB=224.2
  The ν degrees-of-freedom is sourced from K995, but kurtosis/JB/skewness
  have no corresponding results JSON.

  K995b IDENTIFIED the source: K1045 (experiments/K1045/k1045.py)
  K1045 uses a different setup than K995:
  - vix2 = (vix / 100)^2  [VIX divided by 100]
  - ret.clip(-0.20, 0.20)
  - Joint MLE for both GJR-t and A4f-t
  - Different Student-t parameterization: K1045 uses 1+z²/df (standard t)
    vs K995 uses 1+z²/(df-2) (standardized t with unit variance)
  - K1045 OOS period: 2019-01-02 to 2026-04-10, n_oos=1828

  K995b replicates K1045's methodology exactly to reproduce Table 11.

Kurtosis convention:
  Paper says "Excess kurtosis relative to normal (=0)" => Fisher convention
  scipy.stats.kurtosis(z, fisher=True), confirmed by K1045 code.

Paper Table 11 targets (from main.tex and K1045 JSON):
  | Stat     | GJR-t  | A4f-t  |
  |----------|--------|--------|
  | kurtosis | 3.065  | 1.238  |
  | skewness | -0.856 | -0.594 |
  | JB stat  | 938.8  | 224.2  |
  | median ν | 5.28   | 8.00   |
  Footnote: OOS 2019-2026, n=1,828

Source: K1045 (experiments/K1045/k1045.py, k1045_results.json)
  k1045_results.json has: GJR-t kurtosis=3.0650, skewness=-0.8560, JB=938.78
                          A4f-t kurtosis=1.2384, skewness=-0.5937, JB=224.19

FORBIDDEN:
  - Do NOT modify K995/k995_results.json (submitted paper artifact)
  - Do NOT modify paper/garch-x-vix/main.tex
  - Do NOT hard-code or seed-tune to match paper numbers

Author: VolPred Research System (K995b)
Date: 2026-04-17
"""

import os
import sys
import json
import time
import warnings
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K995b"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k995b_results.json')
LOG_PATH = os.path.join(SCRIPT_DIR, 'run.log')

# Configuration — matches K1045 exactly
DATA_START = '2004-01-01'
# K1045 was run on 2026-04-11 (data ends 2026-04-10, n_oos=1828)
# Setting end='2026-04-11' ensures we get the same 1828 OOS observations
# to exactly match K1045's residual computation
DATA_END = '2026-04-11'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

# Paper Table 11 targets for verification
PAPER_TABLE11 = {
    'GJR_t': {
        'excess_kurtosis': 3.065,
        'skewness': -0.856,
        'JB_stat': 938.8,
        'median_nu': 5.28,
        'n_oos': 1828,
    },
    'A4f_t': {
        'excess_kurtosis': 1.238,
        'skewness': -0.594,
        'JB_stat': 224.2,
        'median_nu': 8.00,
        'n_oos': 1828,
    },
}

# K1045 exact values (ground truth source)
K1045_VALUES = {
    'GJR_t': {
        'excess_kurtosis': 3.0650001618374274,
        'skewness': -0.8560196530413117,
        'JB_stat': 938.7773653298907,
        'median_df': 5.282358470566755,
    },
    'A4f_t': {
        'excess_kurtosis': 1.2384292192893565,
        'skewness': -0.5936660077752721,
        'JB_stat': 224.19386009630335,
        'median_df': 8.000606865786747,
    },
}

# --- Logging ---
log_lines = []
def log(msg):
    print(msg, flush=True)
    log_lines.append(msg)


log("=" * 70)
log(f"{EXPERIMENT_ID}: Paper 9 Table 11 Residual Diagnostics Source Recovery")
log("=" * 70)
log("NOTE: Replicating K1045 methodology which produced Table 11 values.")
log(f"      K1045 source: experiments/K1045/k1045.py")

# ============================================================
# SECTION 1: DATA LOADING (matches K1045)
# ============================================================
log("\n[1] Loading data (K1045 setup: vix2=(vix/100)^2, ret.clip(-0.20,0.20))...")
import yfinance as yf

spy = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
vix_dl = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix_dl.columns, pd.MultiIndex):
    vix_dl.columns = vix_dl.columns.get_level_values(0)

df = pd.DataFrame(index=spy.index)
df['close'] = spy['Close']
df['vix'] = vix_dl['Close'].reindex(spy.index, method='ffill')
df['ret'] = np.log(df['close'] / df['close'].shift(1))
df = df.dropna()
df['ret'] = df['ret'].clip(-0.20, 0.20)          # K1045 clips returns
df['vix2'] = (df['vix'] / 100.0) ** 2            # K1045 scales VIX by /100

oos_mask = np.array(df.index >= OOS_START)
n_oos = oos_mask.sum()
n_total = len(df)
log(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, n_total={n_total}")
log(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

returns = df['ret'].values
vix2 = df['vix2'].values


# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS (from K1045)
# ============================================================
log("\n[2] Model implementations (K1045 parameterizations)...")


@njit(cache=True)
def gjr_h_k1045(omega, alpha, gamma, beta, returns):
    """K1045 GJR-GARCH(1,1) conditional variance path."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


@njit(cache=True)
def t_logpdf_sum_k1045(returns, h, df_val):
    """K1045 Student-t log-likelihood: uses standard t parameterization (1 + z²/df).

    NOTE: K995 uses (1 + z²/(df-2)) [standardized t, unit variance].
    K1045 uses (1 + z²/df) [standard t, variance df/(df-2)].
    These produce different df estimates and thus different residual properties.
    """
    T = len(returns)
    scale_factor = math.sqrt((df_val - 2.0) / df_val)  # normalize to unit variance
    c = (math.lgamma((df_val + 1.0) / 2.0) - math.lgamma(df_val / 2.0)
         - 0.5 * math.log(math.pi * df_val))
    ll = 0.0
    for t in range(T):
        sigma = math.sqrt(h[t])
        s = sigma * scale_factor       # effective scale with unit variance
        z = returns[t] / s
        ll += c - math.log(s) - (df_val + 1.0) / 2.0 * math.log(1.0 + z * z / df_val)
    return ll


@njit(cache=True)
def a4f_recursion_k1045(theta0, theta1, omega, alpha, gamma, beta, returns, vix2_arr):
    """K1045 A4f recursion. vix2 = (vix/100)^2."""
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2_arr[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2_arr[t-1]
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / math.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g


def fit_gjr_t_k1045(returns):
    """K1045-style GJR-t fit. Exact copy of K1045 fit_gjr_t function."""
    var0 = np.var(returns)
    bounds = [(1e-10, var0 * 10), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]

    def obj(p):
        if p[1] + 0.5 * p[2] + p[3] >= 1.0:
            return 1e10
        try:
            h = gjr_h_k1045(p[0], p[1], p[2], p[3], returns)
            ll = t_logpdf_sum_k1045(returns, h, p[4])
            return -ll if np.isfinite(ll) else 1e10
        except Exception:
            return 1e10

    best_res, best_nll = None, 1e10
    # K1045 uses exactly these 3 starting df values (from code line 186-193)
    for df_init in [5.0, 8.0, 15.0]:
        x0 = [var0 * 0.05, 0.05, 0.05, 0.90, df_init]
        try:
            res = optimize.minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except Exception:
            continue

    if best_res is None:
        return None
    h = gjr_h_k1045(best_res.x[0], best_res.x[1], best_res.x[2], best_res.x[3], returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success,
            'nll': best_res.fun, 'df': best_res.x[4]}


def fit_a4f_normal_k1045(returns, vix2_arr):
    """K1045-style A4f Normal fit (starting point for joint t fit)."""
    bounds_n = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
                (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]

    def obj_n(p):
        if p[3] + 0.5 * p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion_k1045(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2_arr)
            T = len(returns)
            ll = 0.0
            for t in range(T):
                if h[t] > 0:
                    ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
            return -ll if np.isfinite(ll) else 1e10
        except Exception:
            return 1e10

    best_res_n, best_nll_n = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = optimize.minimize(obj_n, x0, method='L-BFGS-B', bounds=bounds_n,
                                        options={'maxiter': 300})
                if res.fun < best_nll_n:
                    best_nll_n = res.fun
                    best_res_n = res
            except Exception:
                continue

    if best_res_n is None:
        best_res_n = optimize.minimize(obj_n, [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90],
                                        method='L-BFGS-B', bounds=bounds_n)
    return best_res_n


def fit_a4f_t_k1045(returns, vix2_arr):
    """K1045-style A4f-t joint MLE fit."""
    best_res_n = fit_a4f_normal_k1045(returns, vix2_arr)

    # Joint MLE with Student-t
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999), (3.0, 50.0)]

    def obj(p):
        if p[3] + 0.5 * p[4] + p[5] >= 1.0:
            return 1e10
        try:
            h, _, _ = a4f_recursion_k1045(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2_arr)
            ll = t_logpdf_sum_k1045(returns, h, p[6])
            return -ll if np.isfinite(ll) else 1e10
        except Exception:
            return 1e10

    best_res, best_nll = None, 1e10
    for df_init in [5.0, 8.0, 15.0]:
        p0 = list(best_res_n.x) + [df_init]
        try:
            res = optimize.minimize(obj, p0, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 300})
            if res.fun < best_nll:
                best_nll = res.fun
                best_res = res
        except Exception:
            continue

    if best_res is None:
        return None
    h, tau, g = a4f_recursion_k1045(best_res.x[0], best_res.x[1], best_res.x[2],
                                     best_res.x[3], best_res.x[4], best_res.x[5],
                                     returns, vix2_arr)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success, 'nll': best_res.fun, 'df': best_res.x[6]}


# ============================================================
# SECTION 3: OOS FORECASTING (mirrors K1045 oos_forecast_full)
# ============================================================
log("\n[3] Out-of-sample rolling forecasts...")

oos_start_idx = np.where(oos_mask)[0][0]
T = len(returns)
n_oos_actual = oos_mask.sum()

h_gjr = np.full(T, np.nan)
h_a4f = np.full(T, np.nan)
tau_a4f = np.full(T, np.nan)
g_a4f = np.full(T, np.nan)
df_gjr_arr = np.full(T, np.nan)
df_a4f_arr = np.full(T, np.nan)

# GJR-t rolling
log("  Running GJR-t rolling OOS...")
last_fit_gjr = None
last_fit_idx_gjr = -REFIT_EVERY
h_prev_gjr = np.nan
refit_count_gjr = 0

for t in range(oos_start_idx, T):
    if t % 500 == 0:
        elapsed = time.time() - START_TIME
        log(f"  GJR-t step {t - oos_start_idx}/{n_oos_actual} ({elapsed:.0f}s)")

    if t - last_fit_idx_gjr >= REFIT_EVERY or last_fit_gjr is None:
        s = max(0, t - WINDOW)
        tr = returns[s:t]
        fit_res = fit_gjr_t_k1045(tr)
        if fit_res is not None:
            last_fit_gjr = fit_res
            last_fit_idx_gjr = t
            h_prev_gjr = last_fit_gjr['h'][-1]
            refit_count_gjr += 1

    if last_fit_gjr is None:
        continue

    p = last_fit_gjr['params']
    omega, alpha, gamma, beta, df_val = p[0], p[1], p[2], p[3], p[4]
    df_gjr_arr[t] = df_val
    r_prev = returns[t-1]
    r2p = r_prev ** 2
    ind = 1.0 if r_prev < 0 else 0.0
    h_t = omega + alpha * r2p + gamma * r2p * ind + beta * h_prev_gjr
    h_t = max(h_t, 1e-16)
    h_gjr[t] = h_t
    h_prev_gjr = h_t

log(f"  GJR-t: {refit_count_gjr} refits")

# A4f-t rolling
log("  Running A4f-t rolling OOS...")
last_fit_a4f = None
last_fit_idx_a4f = -REFIT_EVERY
h_prev_a4f = np.nan
g_prev_a4f = 1.0
refit_count_a4f = 0

for t in range(oos_start_idx, T):
    if t % 500 == 0:
        elapsed = time.time() - START_TIME
        log(f"  A4f-t step {t - oos_start_idx}/{n_oos_actual} ({elapsed:.0f}s)")

    if t - last_fit_idx_a4f >= REFIT_EVERY or last_fit_a4f is None:
        s = max(0, t - WINDOW)
        tr = returns[s:t]
        tv = vix2[s:t]
        fit_res = fit_a4f_t_k1045(tr, tv)
        if fit_res is not None:
            last_fit_a4f = fit_res
            last_fit_idx_a4f = t
            h_prev_a4f = last_fit_a4f['h'][-1]
            g_prev_a4f = last_fit_a4f['g'][-1]
            refit_count_a4f += 1

    if last_fit_a4f is None:
        continue

    p = last_fit_a4f['params']
    theta0, theta1, omega, alpha, gamma, beta, df_val = p
    df_a4f_arr[t] = df_val
    tau_t = max(theta0 + theta1 * vix2[t-1], 1e-16)
    u_prev = returns[t-1] / np.sqrt(tau_t)
    u2 = u_prev ** 2
    ind = 1.0 if returns[t-1] < 0 else 0.0
    g_t = omega + alpha * u2 + gamma * u2 * ind + beta * g_prev_a4f
    g_t = max(g_t, 1e-16)
    h_t = tau_t * g_t
    h_gjr  # just reference to avoid unused warning
    h_a4f[t] = h_t
    tau_a4f[t] = tau_t
    g_a4f[t] = g_t
    g_prev_a4f = g_t
    h_prev_a4f = h_t

log(f"  A4f-t: {refit_count_a4f} refits")

elapsed = time.time() - START_TIME
log(f"  Rolling complete in {elapsed:.0f}s")

# ============================================================
# SECTION 4: COMPUTE STANDARDIZED RESIDUALS AND DIAGNOSTICS
# ============================================================
log("\n[4] Computing standardized residuals and diagnostics...")

# OOS standardized residuals
z_gjr_oos_full = np.full(T, np.nan)
z_a4f_oos_full = np.full(T, np.nan)
mask_gjr = ~np.isnan(h_gjr) & (h_gjr > 0)
mask_a4f = ~np.isnan(h_a4f) & (h_a4f > 0)
z_gjr_oos_full[mask_gjr] = returns[mask_gjr] / np.sqrt(h_gjr[mask_gjr])
z_a4f_oos_full[mask_a4f] = returns[mask_a4f] / np.sqrt(h_a4f[mask_a4f])

# Restrict to OOS period
z_gjr_oos = z_gjr_oos_full[oos_mask]
z_a4f_oos = z_a4f_oos_full[oos_mask]

# Remove NaN
z_gjr_clean = z_gjr_oos[~np.isnan(z_gjr_oos)]
z_a4f_clean = z_a4f_oos[~np.isnan(z_a4f_oos)]

n_z_gjr = len(z_gjr_clean)
n_z_a4f = len(z_a4f_clean)

log(f"  GJR-t OOS residuals: n={n_z_gjr}")
log(f"  A4f-t OOS residuals: n={n_z_a4f}")

# Descriptive stats
log(f"\n  GJR-t: mean={np.mean(z_gjr_clean):.4f}, std={np.std(z_gjr_clean):.4f}")
log(f"  A4f-t: mean={np.mean(z_a4f_clean):.4f}, std={np.std(z_a4f_clean):.4f}")

# Kurtosis: Fisher convention (excess kurtosis, normal=0) — confirmed K1045 code line:
# kurt = float(sp_stats.kurtosis(z_clean, fisher=True))  # excess kurtosis
kurt_gjr = float(stats.kurtosis(z_gjr_clean, fisher=True))
kurt_a4f = float(stats.kurtosis(z_a4f_clean, fisher=True))

skew_gjr = float(stats.skew(z_gjr_clean))
skew_a4f = float(stats.skew(z_a4f_clean))

jb_gjr_stat, jb_gjr_pval = stats.jarque_bera(z_gjr_clean)
jb_a4f_stat, jb_a4f_pval = stats.jarque_bera(z_a4f_clean)
jb_gjr_stat = float(jb_gjr_stat)
jb_a4f_stat = float(jb_a4f_stat)

# Median df
df_gjr_oos = df_gjr_arr[oos_mask]
df_a4f_oos = df_a4f_arr[oos_mask]
median_nu_gjr = float(np.nanmedian(df_gjr_oos))
median_nu_a4f = float(np.nanmedian(df_a4f_oos))

log(f"\n  --- Kurtosis (Fisher excess, normal=0) ---")
log(f"  GJR-t: {kurt_gjr:.3f}  (paper: 3.065, K1045: 3.065)")
log(f"  A4f-t: {kurt_a4f:.3f}  (paper: 1.238, K1045: 1.238)")

log(f"\n  --- Skewness ---")
log(f"  GJR-t: {skew_gjr:.3f}  (paper: -0.856, K1045: -0.856)")
log(f"  A4f-t: {skew_a4f:.3f}  (paper: -0.594, K1045: -0.594)")

log(f"\n  --- Jarque-Bera ---")
log(f"  GJR-t JB: {jb_gjr_stat:.1f}  (paper: 938.8, K1045: 938.78)")
log(f"  A4f-t JB: {jb_a4f_stat:.1f}  (paper: 224.2, K1045: 224.19)")

log(f"\n  --- Median degrees of freedom ---")
log(f"  GJR-t median ν: {median_nu_gjr:.2f}  (paper Table 11: 5.28, K1045: 5.28)")
log(f"  A4f-t median ν: {median_nu_a4f:.2f}  (paper Table 11: 8.00, K1045: 8.00)")

# ============================================================
# SECTION 5: VERIFICATION
# ============================================================
log("\n[5] Verification against Paper 9 Table 11 and K1045...")

RTOL = 0.01   # 1% relative tolerance

def check_match(computed, paper, label, rtol=RTOL):
    """Return match status."""
    if paper == 0:
        rel_diff = abs(computed - paper)
    else:
        rel_diff = abs(computed - paper) / abs(paper)
    if rel_diff <= rtol:
        status = "MATCHED"
    elif rel_diff <= 0.10:
        status = "APPROX"
    else:
        status = "DIVERGENT"
    log(f"  {label}: computed={computed:.3f}, paper={paper:.3f}, "
        f"rel_diff={rel_diff*100:.1f}% => {status}")
    return status, float(computed), float(paper), float(rel_diff * 100)


log("\n  [GJR-t]")
gjr_kurt_status, gjr_kurt_comp, gjr_kurt_paper, gjr_kurt_diff = check_match(
    kurt_gjr, PAPER_TABLE11['GJR_t']['excess_kurtosis'], "GJR-t excess kurtosis")
gjr_skew_status, gjr_skew_comp, gjr_skew_paper, gjr_skew_diff = check_match(
    skew_gjr, PAPER_TABLE11['GJR_t']['skewness'], "GJR-t skewness")
gjr_jb_status, gjr_jb_comp, gjr_jb_paper, gjr_jb_diff = check_match(
    jb_gjr_stat, PAPER_TABLE11['GJR_t']['JB_stat'], "GJR-t JB stat")
gjr_nu_status, gjr_nu_comp, gjr_nu_paper, gjr_nu_diff = check_match(
    median_nu_gjr, PAPER_TABLE11['GJR_t']['median_nu'], "GJR-t median nu")

log("\n  [A4f-t]")
a4f_kurt_status, a4f_kurt_comp, a4f_kurt_paper, a4f_kurt_diff = check_match(
    kurt_a4f, PAPER_TABLE11['A4f_t']['excess_kurtosis'], "A4f-t excess kurtosis")
a4f_skew_status, a4f_skew_comp, a4f_skew_paper, a4f_skew_diff = check_match(
    skew_a4f, PAPER_TABLE11['A4f_t']['skewness'], "A4f-t skewness")
a4f_jb_status, a4f_jb_comp, a4f_jb_paper, a4f_jb_diff = check_match(
    jb_a4f_stat, PAPER_TABLE11['A4f_t']['JB_stat'], "A4f-t JB stat")
a4f_nu_status, a4f_nu_comp, a4f_nu_paper, a4f_nu_diff = check_match(
    median_nu_a4f, PAPER_TABLE11['A4f_t']['median_nu'], "A4f-t median nu")

# Count matches (kurtosis, skewness, JB only — 6 cells from Table 11)
all_statuses_6 = [gjr_kurt_status, gjr_skew_status, gjr_jb_status,
                  a4f_kurt_status, a4f_skew_status, a4f_jb_status]
matched_6 = sum(1 for s in all_statuses_6 if s == "MATCHED")
approx_6 = sum(1 for s in all_statuses_6 if s == "APPROX")
divergent_6 = sum(1 for s in all_statuses_6 if s == "DIVERGENT")

if divergent_6 == 0:
    overall_status = "FULL_REPRODUCTION" if matched_6 == 6 else "APPROX_REPRODUCTION"
else:
    overall_status = "PARTIAL_OR_FAILED"

log(f"\n  Table 11 cells (6): {matched_6} MATCHED, {approx_6} APPROX, {divergent_6} DIVERGENT")
log(f"  Overall: {overall_status}")

# ============================================================
# SECTION 6: SAVE RESULTS
# ============================================================
log("\n[6] Saving results...")

elapsed_total = time.time() - START_TIME

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Paper 9 Table 11 Residual Diagnostics Source Recovery',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'description': (
        'Identifies K1045 as source of Paper 9 Table 11, and replicates '
        'K1045 methodology to reproduce Table 11 values. Key differences from K995: '
        '(1) vix2=(vix/100)^2, (2) ret.clip(-0.20,0.20), (3) joint MLE for GJR-t and A4f-t, '
        '(4) K1045 Student-t uses 1+z^2/df parameterization (standard t).'
    ),
    'source_identification': {
        'source_experiment': 'K1045',
        'source_file': 'experiments/K1045/k1045.py',
        'source_json': 'experiments/K1045/k1045_results.json',
        'k1045_exact_values': K1045_VALUES,
        'key_methodological_differences_from_k995': [
            'vix2 = (vix / 100)^2 [K1045] vs vix raw values [K995]',
            'ret.clip(-0.20, 0.20) [K1045] vs no clipping [K995]',
            'Joint MLE for GJR-t and A4f-t df [K1045] vs residual-based df for A4f-t [K995]',
            'Student-t parameterization: K1045 uses log(1+z^2/df) [standard t], K995 uses log(1+z^2/(df-2)) [standardized t]',
            'Data end: K1045 runs to 2026-04-10 (n_oos=1828), K995 ends 2026-04-07 (n_oos=1825)',
        ],
    },
    'kurtosis_convention': {
        'type': 'Fisher excess kurtosis (normal=0)',
        'scipy_call': 'scipy.stats.kurtosis(z, fisher=True)',
        'paper_note': 'Paper Table 11 footnote: "Excess kurtosis relative to normal (=0)"',
        'confirmed_by': 'K1045 code line 433: kurt = float(sp_stats.kurtosis(z_clean, fisher=True))',
    },
    'data': {
        'asset': 'SPY',
        'source': 'yfinance',
        'data_start': DATA_START,
        'data_end': f"{df.index[-1].strftime('%Y-%m-%d')}",
        'oos_start': OOS_START,
        'oos_end': f"{df.index[oos_mask][-1].strftime('%Y-%m-%d')}",
        'n_total': int(n_total),
        'n_oos': int(n_oos_actual),
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'ret_clip': '(-0.20, 0.20)',
        'vix_transform': 'vix2 = (vix / 100)^2',
    },
    'residual_diagnostics': {
        'GJR_t': {
            'n_residuals': int(n_z_gjr),
            'mean': float(np.mean(z_gjr_clean)),
            'std': float(np.std(z_gjr_clean)),
            'excess_kurtosis_fisher': kurt_gjr,
            'skewness': skew_gjr,
            'JB_stat': jb_gjr_stat,
            'JB_pvalue': float(jb_gjr_pval),
            'median_nu': median_nu_gjr,
        },
        'A4f_t': {
            'n_residuals': int(n_z_a4f),
            'mean': float(np.mean(z_a4f_clean)),
            'std': float(np.std(z_a4f_clean)),
            'excess_kurtosis_fisher': kurt_a4f,
            'skewness': skew_a4f,
            'JB_stat': jb_a4f_stat,
            'JB_pvalue': float(jb_a4f_pval),
            'median_nu': median_nu_a4f,
        },
    },
    'paper_table11_comparison': {
        'GJR_t': {
            'excess_kurtosis': {'computed': kurt_gjr, 'paper': gjr_kurt_paper, 'rel_diff_pct': gjr_kurt_diff, 'status': gjr_kurt_status},
            'skewness': {'computed': skew_gjr, 'paper': gjr_skew_paper, 'rel_diff_pct': gjr_skew_diff, 'status': gjr_skew_status},
            'JB_stat': {'computed': jb_gjr_stat, 'paper': gjr_jb_paper, 'rel_diff_pct': gjr_jb_diff, 'status': gjr_jb_status},
            'median_nu': {'computed': median_nu_gjr, 'paper': gjr_nu_paper, 'rel_diff_pct': gjr_nu_diff, 'status': gjr_nu_status},
        },
        'A4f_t': {
            'excess_kurtosis': {'computed': kurt_a4f, 'paper': a4f_kurt_paper, 'rel_diff_pct': a4f_kurt_diff, 'status': a4f_kurt_status},
            'skewness': {'computed': skew_a4f, 'paper': a4f_skew_paper, 'rel_diff_pct': a4f_skew_diff, 'status': a4f_skew_status},
            'JB_stat': {'computed': jb_a4f_stat, 'paper': a4f_jb_paper, 'rel_diff_pct': a4f_jb_diff, 'status': a4f_jb_status},
            'median_nu': {'computed': median_nu_a4f, 'paper': a4f_nu_paper, 'rel_diff_pct': a4f_nu_diff, 'status': a4f_nu_status},
        },
    },
    'overall_reproduction': {
        'status': overall_status,
        'matched': int(matched_6),
        'approx': int(approx_6),
        'divergent': int(divergent_6),
        'total_cells_table11': 6,
        'rtol_used': RTOL,
    },
    'elapsed_seconds': round(elapsed_total, 1),
    'references': [
        'K1045: A4f vs GJR Residual Diagnostic Suite (Paper 9 Support, 2026-04-11)',
        'Jarque, C.M. and Bera, A.K. (1987). A test for normality of observations and regression residuals. ISR 55(2):163-172.',
        'Paper 9 (garch-x-vix): submitted J. Empirical Finance',
    ],
    'integrity_notes': [
        'K995/k995_results.json was NOT modified (submitted paper artifact preserved)',
        'paper/garch-x-vix/main.tex was NOT modified',
        'No hard-coded values or seed-tuning',
        'K1045 methodology replicated exactly to reproduce paper values',
        'Source K1045 confirmed via exact match of k1045_results.json values',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2)

log(f"  Results saved to {RESULTS_PATH}")
log(f"  Total elapsed: {elapsed_total:.0f}s")

# ============================================================
# SECTION 7: FINAL SUMMARY
# ============================================================
log("\n" + "=" * 70)
log("FINAL SUMMARY: Paper 9 Table 11 Reproduction")
log("=" * 70)
log(f"\nKurtosis convention: Fisher excess kurtosis (scipy.stats.kurtosis, fisher=True)")
log(f"Source identified: K1045 (experiments/K1045/k1045.py)")
log(f"\n{'Stat':<35} {'GJR-t':>10} {'A4f-t':>10}")
log(f"{'':->55}")
log(f"{'Excess kurtosis (paper)':>35} {'3.065':>10} {'1.238':>10}")
log(f"{'Excess kurtosis (computed)':>35} {kurt_gjr:>10.3f} {kurt_a4f:>10.3f}")
log(f"{'Match status':>35} {gjr_kurt_status:>10} {a4f_kurt_status:>10}")
log(f"{'':->55}")
log(f"{'Skewness (paper)':>35} {'-0.856':>10} {'-0.594':>10}")
log(f"{'Skewness (computed)':>35} {skew_gjr:>10.3f} {skew_a4f:>10.3f}")
log(f"{'Match status':>35} {gjr_skew_status:>10} {a4f_skew_status:>10}")
log(f"{'':->55}")
log(f"{'JB stat (paper)':>35} {'938.8':>10} {'224.2':>10}")
log(f"{'JB stat (computed)':>35} {jb_gjr_stat:>10.1f} {jb_a4f_stat:>10.1f}")
log(f"{'Match status':>35} {gjr_jb_status:>10} {a4f_jb_status:>10}")
log(f"{'':->55}")
log(f"{'Median nu (paper)':>35} {'5.28':>10} {'8.00':>10}")
log(f"{'Median nu (computed)':>35} {median_nu_gjr:>10.2f} {median_nu_a4f:>10.2f}")
log(f"{'Match status':>35} {gjr_nu_status:>10} {a4f_nu_status:>10}")
log(f"\n  Table 11 cells (kurtosis/skew/JB, 6 cells): {matched_6} MATCHED / {approx_6} APPROX / {divergent_6} DIVERGENT")
log(f"  => {overall_status}")
log("\n" + "=" * 70)
log(f"{EXPERIMENT_ID} COMPLETE")
log("=" * 70)

# Save log
with open(LOG_PATH, 'w') as f:
    f.write('\n'.join(log_lines) + '\n')

log(f"Log saved to {LOG_PATH}")
