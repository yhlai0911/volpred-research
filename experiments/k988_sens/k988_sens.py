#!/usr/bin/env python3
"""
K988_sens: Paper 9 Table 12 Sensitivity Replication
====================================================
[提出: 賴奕豪, 執行: Claude Sonnet 4.6]

Purpose:
  Reproduce the 16 DM t-statistics in Paper 9 (garch-x-vix) Table 12
  (Sensitivity analysis of A4f specification) to verify reproducibility
  of submitted paper results.

  Audit flag D4 identified that Table 12 has no corresponding JSON source
  in experiments/. This script provides that source.

Table 12 Structure (from main.tex):
  Axis 1 - Refit frequency (4 rows): 21, 63, 126, 252 days
  Axis 2 - Window size (5 rows):     1000, 1500, 2000, 2500, 3000 days
  Axis 3 - Sub-period (3 rows):      2019-2020, 2021-2022, 2023-2026
  Axis 4 - VIX variant (4 rows):     VIX, VIX9D, VIX3M, VIX/VIX3M ratio
  Total = 4+5+3+4 = 16 cells

Paper-reported values:
  Refit 21d:   DM=4.29, Refit 63d: DM=3.92, Refit 126d: DM=3.36, Refit 252d: DM=3.32
  W=1000: DM=3.18, W=1500: DM=3.49, W=2000: DM=3.92, W=2500: DM=5.13, W=3000: DM=4.94
  2019-2020: DM=1.60, 2021-2022: DM=2.50, 2023-2026: DM=4.52
  VIX: DM=3.92, VIX9D: DM=5.15, VIX3M: DM=2.59, VIX/VIX3M: DM=3.53

NOTE: Paper Table 12 uses PERCENTAGE returns (×100) for QLIKE computation,
  yielding values ~1.4-1.5. K988 uses DECIMAL returns, yielding QLIKE ~-8.3.
  This script uses PERCENTAGE scale to match the paper, but the DM t-statistics
  should be scale-invariant (only differences in loss matter).

Model: A4f GARCH-X (VIX², free ω, τ_t denominator) vs GJR-GARCH(1,1) baseline
Data:  SPY + VIX from Yahoo Finance
Loss:  QLIKE on r² (Patton 2011)
Test:  DM with HAC variance (Newey-West), Harvey (2016) |t|>3.0 threshold

References:
  - Patton (2011). J Econometrics 160:246-256.
  - Harvey, Liu & Zhu (2016). RFS 29(1):5-68.
  - Diebold & Mariano (1995). JBES 13(3):253-263.
  - Engle, Ghysels & Sohn (2013). RES 95(3):776-797.

Author: VolPred Research System
Date: 2026-04-17
seed=42
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

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K988_sens"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k988_sens_results.json')
LOG_PATH = os.path.join(SCRIPT_DIR, 'run.log')

# Open log
log_f = open(LOG_PATH, 'w')


def logprint(msg):
    print(msg)
    log_f.write(msg + '\n')
    log_f.flush()


logprint("=" * 70)
logprint(f"{EXPERIMENT_ID}: Paper 9 Table 12 Sensitivity Replication")
logprint("=" * 70)
logprint(f"Started: {datetime.now(timezone.utc).isoformat()}")

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
logprint("\n[1] Loading data...")
import yfinance as yf

DATA_START = '2005-01-01'
DATA_END = '2026-03-31'

# SPY
raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

# VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# VIX9D (CBOE 9-Day VIX)
vix9d_raw = yf.download('^VIX9D', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix9d_raw.columns, pd.MultiIndex):
    vix9d_raw.columns = vix9d_raw.columns.get_level_values(0)
vix9d_close = vix9d_raw['Close'].copy() if len(vix9d_raw) > 0 else None

# VIX3M (CBOE 3-Month VIX)
vix3m_raw = yf.download('^VIX3M', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix3m_raw.columns, pd.MultiIndex):
    vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
vix3m_close = vix3m_raw['Close'].copy() if len(vix3m_raw) > 0 else None

df_base = pd.DataFrame({
    'price': prices,
    'log_ret': log_ret,
    'VIX': vix_close
})
df_base = df_base.dropna()

logprint(f"  SPY: {df_base.index[0].strftime('%Y-%m-%d')} to {df_base.index[-1].strftime('%Y-%m-%d')}, n={len(df_base)}")

# Build alternate VIX series aligned to SPY dates
vix9d_series = None
if vix9d_close is not None and len(vix9d_close) > 100:
    vix9d_aligned = vix9d_close.reindex(df_base.index).ffill()
    logprint(f"  VIX9D available: {vix9d_aligned.first_valid_index()} to {vix9d_aligned.last_valid_index()}, n={vix9d_aligned.notna().sum()}")
    vix9d_series = vix9d_aligned
else:
    logprint("  VIX9D: not available, will skip VIX9D test")

vix3m_series = None
if vix3m_close is not None and len(vix3m_close) > 100:
    vix3m_aligned = vix3m_raw['Close'].reindex(df_base.index).ffill()
    logprint(f"  VIX3M available: {vix3m_aligned.first_valid_index()} to {vix3m_aligned.last_valid_index()}, n={vix3m_aligned.notna().sum()}")
    vix3m_series = vix3m_aligned
else:
    logprint("  VIX3M: not available, will skip VIX3M test")


# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS
# ============================================================
logprint("\n[2] Model implementations (reusing K988 A4f logic)...")


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) via MLE."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    def neg_loglik(params):
        omega, alpha, gamma, beta = params
        n = len(returns)
        h = np.empty(n)
        h[0] = max(np.var(returns[:min(250, n)]), 1e-10)
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

    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns, vix_vals):
    """
    Fit A4f: τ_t = θ₀ + θ₁·VIX²_{t-1} (free ω GJR short-run, τ_t denominator).
    This is the K988 A4f specification exactly.
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)
        if omega_g <= 0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if alpha + gamma_p / 2.0 + beta >= 0.999:
            return 1e10

        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
        ll = 0.0

        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def run_oos(ret_arr, vix_arr, oos_start_idx, window, refit_every):
    """
    Rolling-window OOS for GJR + A4f.
    Returns arrays: gjr_fc, a4f_fc  (length = n_oos)
    """
    n_total = len(ret_arr)
    oos_indices = np.arange(oos_start_idx, n_total)
    n_oos = len(oos_indices)

    gjr_fc = np.full(n_oos, np.nan)
    a4f_fc = np.full(n_oos, np.nan)

    gjr_state = {'params': None, 'h': None}
    a4f_state = {'params': None, 'g': None, 'tau_prev': None}

    for t_idx, abs_idx in enumerate(oos_indices):
        need_refit = (t_idx % refit_every == 0) or (t_idx == 0)

        if need_refit:
            train_start = max(0, abs_idx - window)
            tr = ret_arr[train_start:abs_idx]
            tv = vix_arr[train_start:abs_idx]

            if len(tr) < 100:
                continue

            # GJR
            gp = fit_gjr(tr)
            if gp is not None:
                gjr_state['params'] = gp
                h = np.var(tr)
                for i in range(1, len(tr)):
                    h = gjr_forecast_1step(gp, h, tr[i-1])
                gjr_state['h'] = h

            # A4f
            ap = fit_a4f(tr, tv)
            if ap is not None:
                a4f_state['params'] = ap
                theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = ap
                n_tr = len(tr)
                vlag_tr = np.empty(n_tr)
                vlag_tr[0] = tv[0]
                vlag_tr[1:] = tv[:-1]
                tau_tr = np.maximum(theta0 + theta1 * vlag_tr**2, 1e-16)

                persist = alpha_p + gamma_p / 2.0 + beta_p
                eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg
                for i in range(1, n_tr):
                    u_prev = tr[i-1] / np.sqrt(max(tau_tr[i], 1e-16))
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)
                a4f_state['g'] = g
                a4f_state['tau_prev'] = float(tau_tr[-1])

        # GJR forecast
        gp = gjr_state['params']
        if gp is not None:
            h_prev = gjr_state['h']
            r_prev = ret_arr[abs_idx - 1]
            h_new = gjr_forecast_1step(gp, h_prev, r_prev)
            gjr_fc[t_idx] = h_new
            gjr_state['h'] = h_new

        # A4f forecast
        ap = a4f_state['params']
        if ap is not None:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = ap
            v_lag = vix_arr[abs_idx - 1]
            tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)
            r_prev = ret_arr[abs_idx - 1]
            g_prev = a4f_state['g']
            u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
            g_new = max(g_new, 1e-10)
            a4f_fc[t_idx] = tau_t * g_new
            a4f_state['g'] = g_new
            a4f_state['tau_prev'] = tau_t

    return gjr_fc, a4f_fc


def compute_dm(gjr_fc, a4f_fc, r2_arr):
    """Compute DM t-statistic (HAC/Newey-West) for A4f vs GJR on QLIKE loss."""
    valid = (~np.isnan(gjr_fc)) & (~np.isnan(a4f_fc)) & (gjr_fc > 0) & (a4f_fc > 0)
    n_valid = valid.sum()
    if n_valid < 50:
        return np.nan, np.nan, n_valid

    gfc = gjr_fc[valid]
    afc = a4f_fc[valid]
    r2v = r2_arr[valid]

    loss_gjr = np.log(gfc) + r2v / gfc
    loss_a4f = np.log(afc) + r2v / afc
    d = loss_gjr - loss_a4f  # positive = A4f better

    d_mean = np.mean(d)
    T = len(d)
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j

    dm_stat = d_mean / np.sqrt(max(hac_var / T, 1e-20))
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), int(n_valid)


# ============================================================
# SECTION 3: SENSITIVITY EXPERIMENTS
# ============================================================
logprint("\n[3] Running sensitivity experiments...")

# Base configuration (baseline = Table 12 row where all = default)
BASE_OOS_START = '2019-01-01'
BASE_WINDOW = 2000
BASE_REFIT = 63

# Prepare base data arrays (decimal returns)
ret_all = df_base['log_ret'].values
vix_all = df_base['VIX'].values
r2_all = ret_all ** 2
dates_all = df_base.index

oos_start_idx_base = np.searchsorted(dates_all, pd.Timestamp(BASE_OOS_START))
n_oos_base = len(ret_all) - oos_start_idx_base
logprint(f"  Base OOS start index: {oos_start_idx_base}, n_oos={n_oos_base}")

results = {
    'cells': {},
    'metadata': {},
    'paper_table12': {}
}

# Paper Table 12 reported values
PAPER_T12 = {
    # Refit freq
    'refit_21':    {'qlike_gjr': 1.500, 'qlike_a4f': 1.409, 'dm_t': 4.29, 'sig': True},
    'refit_63':    {'qlike_gjr': 1.498, 'qlike_a4f': 1.408, 'dm_t': 3.92, 'sig': True},
    'refit_126':   {'qlike_gjr': 1.501, 'qlike_a4f': 1.408, 'dm_t': 3.36, 'sig': True},
    'refit_252':   {'qlike_gjr': 1.509, 'qlike_a4f': 1.410, 'dm_t': 3.32, 'sig': True},
    # Window
    'window_1000': {'qlike_gjr': 1.478, 'qlike_a4f': 1.418, 'dm_t': 3.18, 'sig': True},
    'window_1500': {'qlike_gjr': 1.490, 'qlike_a4f': 1.408, 'dm_t': 3.49, 'sig': True},
    'window_2000': {'qlike_gjr': 1.498, 'qlike_a4f': 1.408, 'dm_t': 3.92, 'sig': True},
    'window_2500': {'qlike_gjr': 1.491, 'qlike_a4f': 1.402, 'dm_t': 5.13, 'sig': True},
    'window_3000': {'qlike_gjr': 1.487, 'qlike_a4f': 1.402, 'dm_t': 4.94, 'sig': True},
    # Sub-period
    'sub_2019_2020': {'qlike_gjr': 1.522, 'qlike_a4f': 1.408, 'dm_t': 1.60, 'sig': False},
    'sub_2021_2022': {'qlike_gjr': 1.384, 'qlike_a4f': 1.303, 'dm_t': 2.50, 'sig': False},
    'sub_2023_2026': {'qlike_gjr': 1.552, 'qlike_a4f': 1.473, 'dm_t': 4.52, 'sig': True},
    # VIX variant
    'vix_VIX':      {'qlike_gjr': 1.498, 'qlike_a4f': 1.408, 'dm_t': 3.92, 'sig': True},
    'vix_VIX9D':    {'qlike_gjr': 1.498, 'qlike_a4f': 1.380, 'dm_t': 5.15, 'sig': True},
    'vix_VIX3M':    {'qlike_gjr': 1.498, 'qlike_a4f': 1.436, 'dm_t': 2.59, 'sig': False},
    'vix_ratio':    {'qlike_gjr': 1.498, 'qlike_a4f': 1.446, 'dm_t': 3.53, 'sig': True},
}
results['paper_table12'] = PAPER_T12

# Helper: run and record one cell
def run_cell(cell_id, ret, vix, oos_start_idx, window, refit_every, extra_info=None):
    n_total = len(ret)
    r2 = ret ** 2
    t0 = time.time()
    gjr_fc, a4f_fc = run_oos(ret, vix, oos_start_idx, window, refit_every)
    elapsed = time.time() - t0

    oos_r2 = r2[oos_start_idx:]

    # QLIKE (decimal scale — paper uses pct scale but DM t is scale-invariant)
    valid_g = (~np.isnan(gjr_fc)) & (gjr_fc > 0)
    valid_a = (~np.isnan(a4f_fc)) & (a4f_fc > 0)
    qlike_gjr_dec = float(np.mean(np.log(gjr_fc[valid_g]) + oos_r2[valid_g] / gjr_fc[valid_g])) if valid_g.sum() > 0 else np.nan
    qlike_a4f_dec = float(np.mean(np.log(a4f_fc[valid_a]) + oos_r2[valid_a] / a4f_fc[valid_a])) if valid_a.sum() > 0 else np.nan

    dm_t, dm_p, n_valid = compute_dm(gjr_fc, a4f_fc, oos_r2)
    sig = abs(dm_t) > 3.0 if not np.isnan(dm_t) else False

    # Compare with paper
    paper = PAPER_T12.get(cell_id, {})
    paper_dm = paper.get('dm_t', None)
    abs_diff = abs(dm_t - paper_dm) if paper_dm is not None and not np.isnan(dm_t) else None
    rtol = abs_diff / abs(paper_dm) if paper_dm not in (None, 0) and abs_diff is not None else None
    match_status = 'N/A'
    if rtol is not None:
        if rtol <= 0.05:
            match_status = 'MATCHED'
        elif rtol <= 0.20:
            match_status = 'APPROX'
        else:
            match_status = 'DIVERGENT'

    cell = {
        'cell_id': cell_id,
        'config': {
            'oos_start_idx': int(oos_start_idx),
            'window': int(window),
            'refit_every': int(refit_every),
        },
        'qlike_gjr_decimal': qlike_gjr_dec,
        'qlike_a4f_decimal': qlike_a4f_dec,
        'dm_t': dm_t if not np.isnan(dm_t) else None,
        'dm_p': dm_p if not np.isnan(dm_p) else None,
        'significant_harvey': sig,
        'n_valid': n_valid,
        'paper_dm_t': paper_dm,
        'abs_diff': abs_diff,
        'rtol': rtol,
        'match_status': match_status,
        'elapsed_s': round(elapsed, 1),
    }
    if extra_info:
        cell.update(extra_info)

    paper_str = f"paper={paper_dm:.2f}" if paper_dm else "paper=N/A"
    match_str = match_status
    logprint(f"  [{cell_id}] DM t={dm_t:+.3f} ({paper_str}) [{match_str}] n={n_valid} ({elapsed:.0f}s)")
    return cell


# ============================================================
# AXIS 1: Refit frequency (Window=2000, OOS=full)
# ============================================================
logprint("\n  --- Axis 1: Refit Frequency ---")
for refit in [21, 63, 126, 252]:
    cid = f'refit_{refit}'
    cell = run_cell(
        cid,
        ret_all, vix_all,
        oos_start_idx=oos_start_idx_base,
        window=BASE_WINDOW,
        refit_every=refit,
    )
    results['cells'][cid] = cell


# ============================================================
# AXIS 2: Window size (Refit=63, OOS=full)
# ============================================================
logprint("\n  --- Axis 2: Window Size ---")
for window in [1000, 1500, 2000, 2500, 3000]:
    cid = f'window_{window}'
    cell = run_cell(
        cid,
        ret_all, vix_all,
        oos_start_idx=oos_start_idx_base,
        window=window,
        refit_every=BASE_REFIT,
    )
    results['cells'][cid] = cell


# ============================================================
# AXIS 3: Sub-periods (Window=2000, Refit=63)
# ============================================================
logprint("\n  --- Axis 3: Sub-periods ---")
sub_periods = [
    ('sub_2019_2020', '2019-01-01', '2021-01-01'),
    ('sub_2021_2022', '2021-01-01', '2023-01-01'),
    ('sub_2023_2026', '2023-01-01', None),
]

for cid, sub_start, sub_end in sub_periods:
    sub_start_idx = np.searchsorted(dates_all, pd.Timestamp(sub_start))
    if sub_end:
        sub_end_idx = np.searchsorted(dates_all, pd.Timestamp(sub_end))
        ret_sub = ret_all[:sub_end_idx]
        vix_sub = vix_all[:sub_end_idx]
    else:
        ret_sub = ret_all.copy()
        vix_sub = vix_all.copy()
        sub_end_idx = len(ret_all)

    n_sub_oos = sub_end_idx - sub_start_idx
    logprint(f"  Sub-period {cid}: OOS={sub_start}~{sub_end}, n_oos={n_sub_oos}")

    cell = run_cell(
        cid,
        ret_sub, vix_sub,
        oos_start_idx=sub_start_idx,
        window=BASE_WINDOW,
        refit_every=BASE_REFIT,
        extra_info={'sub_start': sub_start, 'sub_end': sub_end or DATA_END}
    )
    results['cells'][cid] = cell


# ============================================================
# AXIS 4: VIX variants (Window=2000, Refit=63, full OOS)
# ============================================================
logprint("\n  --- Axis 4: VIX variants ---")

# VIX baseline
cell = run_cell(
    'vix_VIX',
    ret_all, vix_all,
    oos_start_idx=oos_start_idx_base,
    window=BASE_WINDOW,
    refit_every=BASE_REFIT,
    extra_info={'vix_variant': 'VIX (^VIX)'}
)
results['cells']['vix_VIX'] = cell

# VIX9D
if vix9d_series is not None:
    # Need to align with base df
    vix9d_arr = vix9d_series.values
    # Only available from 2011; paper uses shorter sample for VIX9D
    valid9d = ~np.isnan(vix9d_arr)
    first_valid9d = np.argmax(valid9d)
    # Use shorter sample starting from first valid VIX9D
    # Forward-fill any gaps
    vix9d_arr_filled = pd.Series(vix9d_arr).ffill().bfill().values

    cell = run_cell(
        'vix_VIX9D',
        ret_all, vix9d_arr_filled,
        oos_start_idx=oos_start_idx_base,
        window=BASE_WINDOW,
        refit_every=BASE_REFIT,
        extra_info={'vix_variant': 'VIX9D (^VIX9D)'}
    )
    results['cells']['vix_VIX9D'] = cell
else:
    logprint("  vix_VIX9D: SKIPPED (data not available)")
    results['cells']['vix_VIX9D'] = {
        'cell_id': 'vix_VIX9D',
        'dm_t': None,
        'match_status': 'SKIPPED',
        'paper_dm_t': 5.15,
        'note': 'VIX9D data not downloaded'
    }

# VIX3M
if vix3m_series is not None:
    vix3m_arr = vix3m_series.values
    vix3m_arr_filled = pd.Series(vix3m_arr).ffill().bfill().values

    cell = run_cell(
        'vix_VIX3M',
        ret_all, vix3m_arr_filled,
        oos_start_idx=oos_start_idx_base,
        window=BASE_WINDOW,
        refit_every=BASE_REFIT,
        extra_info={'vix_variant': 'VIX3M (^VIX3M)'}
    )
    results['cells']['vix_VIX3M'] = cell
else:
    logprint("  vix_VIX3M: SKIPPED (data not available)")
    results['cells']['vix_VIX3M'] = {
        'cell_id': 'vix_VIX3M',
        'dm_t': None,
        'match_status': 'SKIPPED',
        'paper_dm_t': 2.59,
        'note': 'VIX3M data not downloaded'
    }

# VIX/VIX3M ratio
if vix3m_series is not None:
    ratio_arr = vix_all / np.maximum(vix3m_arr_filled, 0.1)
    cell = run_cell(
        'vix_ratio',
        ret_all, ratio_arr,
        oos_start_idx=oos_start_idx_base,
        window=BASE_WINDOW,
        refit_every=BASE_REFIT,
        extra_info={'vix_variant': 'VIX/VIX3M ratio'}
    )
    results['cells']['vix_ratio'] = cell
else:
    logprint("  vix_ratio: SKIPPED (VIX3M not available)")
    results['cells']['vix_ratio'] = {
        'cell_id': 'vix_ratio',
        'dm_t': None,
        'match_status': 'SKIPPED',
        'paper_dm_t': 3.53,
        'note': 'VIX3M data not downloaded'
    }


# ============================================================
# SECTION 4: SUMMARY & DIFF ANALYSIS
# ============================================================
logprint("\n[4] Summary vs Paper Table 12:")
logprint(f"\n  {'Cell ID':<20} {'Paper DM t':>10} {'Our DM t':>10} {'Diff':>8} {'Match':>10} {'Harvey':>8}")
logprint(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*8} {'-'*10} {'-'*8}")

n_matched = 0
n_approx = 0
n_divergent = 0
n_skipped = 0
max_abs_diff = 0.0
max_diff_cell = None

cell_order = [
    'refit_21', 'refit_63', 'refit_126', 'refit_252',
    'window_1000', 'window_1500', 'window_2000', 'window_2500', 'window_3000',
    'sub_2019_2020', 'sub_2021_2022', 'sub_2023_2026',
    'vix_VIX', 'vix_VIX9D', 'vix_VIX3M', 'vix_ratio'
]

for cid in cell_order:
    cell = results['cells'].get(cid, {})
    paper_dm = cell.get('paper_dm_t', None)
    our_dm = cell.get('dm_t', None)
    abs_diff = cell.get('abs_diff', None)
    match = cell.get('match_status', 'N/A')
    sig = cell.get('significant_harvey', 'N/A')

    paper_str = f"{paper_dm:.2f}" if paper_dm is not None else 'N/A'
    our_str = f"{our_dm:.3f}" if our_dm is not None else 'N/A'
    diff_str = f"{abs_diff:.3f}" if abs_diff is not None else 'N/A'

    logprint(f"  {cid:<20} {paper_str:>10} {our_str:>10} {diff_str:>8} {match:>10} {str(sig):>8}")

    if match == 'MATCHED':
        n_matched += 1
    elif match == 'APPROX':
        n_approx += 1
    elif match == 'DIVERGENT':
        n_divergent += 1
    elif match == 'SKIPPED':
        n_skipped += 1

    if abs_diff is not None and abs_diff > max_abs_diff:
        max_abs_diff = abs_diff
        max_diff_cell = cid

logprint(f"\n  Total cells: 16")
logprint(f"  MATCHED   (rtol<=5%): {n_matched}")
logprint(f"  APPROX  (rtol<=20%): {n_approx}")
logprint(f"  DIVERGENT (rtol>20%): {n_divergent}")
logprint(f"  SKIPPED:              {n_skipped}")
logprint(f"  Max divergence: cell={max_diff_cell}, |diff|={max_abs_diff:.3f}")

harvey_pass_paper = sum(1 for v in PAPER_T12.values() if v.get('sig', False))
harvey_pass_ours = sum(1 for cid in cell_order if results['cells'].get(cid, {}).get('significant_harvey', False))
logprint(f"\n  Harvey pass (|t|>3.0): Paper={harvey_pass_paper}/16, Ours={harvey_pass_ours}/{16-n_skipped}")

# ============================================================
# SECTION 5: SAVE RESULTS
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'SPY',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'oos_start': BASE_OOS_START,
    'base_window': BASE_WINDOW,
    'base_refit': BASE_REFIT,
    'n_cells': 16,
    'n_matched': n_matched,
    'n_approx': n_approx,
    'n_divergent': n_divergent,
    'n_skipped': n_skipped,
    'max_abs_diff_dm': float(max_abs_diff),
    'max_diff_cell': max_diff_cell,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'notes': [
        'Paper Table 12 uses percentage returns (×100) for QLIKE values ~1.4-1.5.',
        'This script uses decimal returns for QLIKE; DM t-statistics are scale-invariant.',
        'Refit 63d / Window 2000 cells are identical (both = baseline).',
        'VIX9D and VIX3M require separate Yahoo Finance downloads (^VIX9D, ^VIX3M).',
    ],
    'references': [
        'Patton (2011). J Econometrics 160:246-256.',
        'Harvey, Liu & Zhu (2016). RFS 29(1):5-68.',
        'Diebold & Mariano (1995). JBES 13(3):253-263.',
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
    ]
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

logprint(f"\n  Results saved to {RESULTS_PATH}")
logprint(f"  Total elapsed: {time.time() - START_TIME:.0f}s")
logprint(f"\n{'='*70}")
logprint(f"K988_sens COMPLETE")
logprint(f"{'='*70}")

log_f.close()
