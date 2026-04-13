#!/usr/bin/env python3
"""
K1103: τ-lag Bug-Fix Replication Across TSMC / MediaTek / UMC
=============================================================
[提出: 賴奕豪, 執行: Claude]

Motivation / Big question:
  K1067/K1067b/K1067c A4f-EAV code contains a subtle τ-lag bug in the
  GARCH-MIDAS update equation:

      Buggy:  u_prev = r_{t-1} / sqrt(tau[t])          # uses τ at t
      Fix  :  u_prev = r_{t-1} / sqrt(tau[t-1])        # uses τ at t-1

  In the canonical GARCH-MIDAS (Engle-Ghysels-Sohn 2013), the short-run
  residual u_t is defined as u_t = r_t / sqrt(τ_t).  Therefore the update
  rule for g_t must use u_{t-1} = r_{t-1} / sqrt(τ_{t-1}), not τ_t.
  Using τ_t leaks forecast-day exogenous state (VIX_{t-1}, EAV_{t-1})
  backward into the previous day's standardized residual.  This matters
  particularly when EAV is a binary announcement indicator that causes
  a large jump in τ on T+1 relative to τ on T.

  Concretely:
    - If EAV_{t-1}=1, then tau[t] is large (announcement-day effect).
    - The buggy code divides r_{t-1} by sqrt(large τ), producing an
      artificially small u_{t-1}², which shrinks the g update, which
      keeps σ²_t = τ_t · g_t close to τ_t · (un-disrupted g).
    - This artificially *amplifies* the EAV-day edge of A4f_EAV over
      A4f in the event window — exactly the kind of bias that could
      explain UMC's +39.27% event improvement vs TSMC's -0.25%.

  K1103 rebuilds all three single-stock experiments (TSMC, UMC, MediaTek)
  with the τ-lag fix and recomputes the full result set to determine
  whether the monotonicity story survives.

Decisive test:
  1. UMC event DM |t| drops below 1 → conclusion 1: K1067b/c monotonicity
     discussion is a τ-lag artefact; Paper 2 drops EAV entirely.
  2. UMC event DM |t| in [1, 2] → conclusion 2: partial artefact; Paper 2
     may keep EAV but must warn about timing sensitivity.
  3. UMC event DM |t| stable near -2.2 → conclusion 3: bug impact is
     negligible; K1067b/c findings are robust.

Methodology:
  - Run three stocks (TSMC=2330, MediaTek=2454, UMC=2303) with the
    *fixed* τ-lag in every evaluation context:
      (a) in-sample MLE loss  (neg_loglik inside fit_a4f / fit_a4f_eav)
      (b) warm-up state propagation after each refit
      (c) OOS forecast recursion (maintain tau_prev state)
      (d) full-sample robustness scoring (fit_and_score_full_sample)
  - Everything else matches K1067 exactly: WINDOW=2000, REFIT_EVERY=63,
    OOS_START=2019-01-01, DATA_END=2025-12-31, seed=42.
  - QLIKE on r² target; DM test via volpred.stats.model_evaluation.

Data:
  - yfinance (auto_adjust=True) for 2330.TW / 2454.TW / 2303.TW + ^VIX.
  - 財報公告日.txt (Big5) filtered per code.

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). DM t > 3.0 threshold.
  - K1067, K1067b, K1067c (original, buggy implementations).

Random seed: 42
Author: VolPred Research System
Date: 2026-04-13
"""

import os
import sys
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats, optimize

import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1103"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from volpred.stats.model_evaluation import (  # noqa: E402
    dm_test, qlike, qlike_pointwise, spearman_corr,
)

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
RESULTS_PATH = SCRIPT_DIR / 'k1103_results.json'

# ==========================================================================
# CONFIGURATION
# ==========================================================================
DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

FIRMS = [
    {  # matches K1067 (TSMC)
        'key': 'TSMC',
        'ticker': '2330.TW',
        'code': '2330',
        't1_amp': 0.983,            # K1060 T+1 amplification
        'old_event_dm_t': 0.083,
        'old_event_improvement_pct': -0.249,
        'old_theta2_pos_frac': 0.5925925925925926,
        'old_theta2_p_one': 0.9477644944864295,
        'old_dm_t_aggregate': 0.348,
        'old_improvement_pct_aggregate': -0.070,
    },
    {  # matches K1067c (MediaTek)
        'key': 'MediaTek',
        'ticker': '2454.TW',
        'code': '2454',
        't1_amp': 1.67,
        'old_event_dm_t': 1.59,     # from k1067c (approximate; exact value from JSON)
        'old_event_improvement_pct': -23.46,
        'old_theta2_pos_frac': None,   # filled from k1067c_results.json below
        'old_theta2_p_one': None,
        'old_dm_t_aggregate': None,
        'old_improvement_pct_aggregate': None,
    },
    {  # matches K1067b (UMC)
        'key': 'UMC',
        'ticker': '2303.TW',
        'code': '2303',
        't1_amp': 2.579,
        'old_event_dm_t': -2.204,
        'old_event_improvement_pct': 39.266,
        'old_theta2_pos_frac': 1.0,
        'old_theta2_p_one': 6.67591e-15,
        'old_dm_t_aggregate': -1.371,
        'old_improvement_pct_aggregate': 0.517,
    },
]


# ==========================================================================
# FIXED MODEL IMPLEMENTATIONS (τ-lag bug corrected)
# ==========================================================================
def _tau_lag_prev(tau_arr, t):
    """Return τ at index t-1 (the already-observed long-run component).

    This is the correct input to the GARCH-MIDAS short-run update:
        u_{t-1} = r_{t-1} / sqrt(tau_{t-1}).
    The buggy k1067* code used tau_arr[t] instead.
    """
    return max(tau_arr[t - 1], 1e-16)


def fit_a4f(returns, vix_vals):
    """Baseline A4f: τ_t = max(θ₀ + θ₁·VIX²_{t-1}, ε). 6 params.

    *FIXED VERSION*: u_{t-1} uses tau[t-1], not tau[t].
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = eg
        ll = 0.0
        for t in range(1, n):
            # FIX: use tau[t-1] (known at time t-1) not tau[t].
            u_prev = returns[t - 1] / np.sqrt(_tau_lag_prev(tau, t))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev ** 2 + asym + beta * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) +
                              returns[t] ** 2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2), (1e-8, 1e-3),
        (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999),
    ]
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
    return best_params, best_ll


def fit_a4f_eav(returns, vix_vals, eav_vals):
    """A4f + EAV: τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε). 7 params.

    *FIXED VERSION*: u_{t-1} uses tau[t-1], not tau[t].
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    eav_lag = np.empty(n)
    eav_lag[0] = eav_vals[0]
    eav_lag[1:] = eav_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau_raw = theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag
        tau = np.maximum(tau_raw, 1e-16)
        eg = omega_g / (1.0 - persist)
        g = eg
        ll = 0.0
        for t in range(1, n):
            # FIX: use tau[t-1] not tau[t].
            u_prev = returns[t - 1] / np.sqrt(_tau_lag_prev(tau, t))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev ** 2 + asym + beta * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) +
                              returns[t] ** 2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8
    eav_mean = np.mean(eav_lag) + 1e-8
    theta2_init_scale = var0 * 0.05 / max(eav_mean, 1e-4)
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.0, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init_scale,
         0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, theta2_init_scale * 0.5,
         0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init_scale * 0.5,
         0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2), (1e-8, 1e-3), (-1e-2, 1e-2),
        (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 800})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params, best_ll


def compute_tau_a4f(theta0, theta1, vix_lag_val):
    if np.isscalar(vix_lag_val):
        return max(theta0 + theta1 * vix_lag_val ** 2, 1e-16)
    return np.maximum(theta0 + theta1 * vix_lag_val ** 2, 1e-16)


def compute_tau_a4f_eav(theta0, theta1, theta2, vix_lag_val, eav_lag_val):
    val = theta0 + theta1 * vix_lag_val ** 2 + theta2 * eav_lag_val
    if np.isscalar(val):
        return max(val, 1e-16)
    return np.maximum(val, 1e-16)


# ==========================================================================
# PER-FIRM EXPERIMENT RUNNER
# ==========================================================================
def load_earnings(code):
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
                    recs.append({'date': dt})
                except Exception:
                    pass
    ea_df = pd.DataFrame(recs)
    if len(ea_df) == 0:
        return ea_df
    ea_df = ea_df[(ea_df['date'] >= DATA_START) & (ea_df['date'] <= DATA_END)]
    return ea_df


def run_firm(firm):
    """Execute the τ-lag-fixed A4f / A4f-EAV experiment for a single stock.
    Returns a dict of results matching the k1067* JSON structure."""
    ticker = firm['ticker']
    code = firm['code']
    key = firm['key']
    print("\n" + "=" * 78)
    print(f"[{key}] {ticker} — τ-lag bug-fix replication")
    print("=" * 78)

    # --- Earnings ---
    ea_df = load_earnings(code)
    print(f"  Earnings announcements ({DATA_START}~{DATA_END}): {len(ea_df)}")

    # --- Market data ---
    raw = yf.download(ticker, start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))

    vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                          progress=False)
    if isinstance(vix_raw.columns, pd.MultiIndex):
        vix_raw.columns = vix_raw.columns.get_level_values(0)
    vix_ffill = vix_raw['Close'].reindex(prices.index, method='ffill')

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret,
                       'VIX': vix_ffill}).dropna()
    max_abs_ret = df['log_ret'].abs().max()
    if max_abs_ret > 0.30:
        n_before = len(df)
        df = df[df['log_ret'].abs() <= 0.30]
        print(f"  Dropped {n_before - len(df)} extreme returns (>|30%|)")
    print(f"  {ticker}: {df.index[0].date()} → {df.index[-1].date()}, "
          f"n={len(df)}")

    trading_days = df.index
    eav_binary = np.zeros(len(trading_days), dtype=float)
    if len(ea_df) > 0:
        ea_sorted = ea_df.sort_values('date').reset_index(drop=True)
        pos_arr = trading_days.searchsorted(ea_sorted['date'].values)
        for i in range(len(ea_sorted)):
            pos = int(pos_arr[i])
            if pos < len(trading_days):
                eav_binary[pos] = 1.0
    df['eav'] = eav_binary
    ret = df['log_ret'].values
    vix = df['VIX'].values
    r2 = ret ** 2
    eav_arr = df['eav'].values
    oos_mask = np.array(df.index >= OOS_START)
    n_oos_actual = int(oos_mask.sum())
    n_event_full = int((eav_arr > 0).sum())
    n_event_oos = int((eav_arr[oos_mask] > 0).sum())
    print(f"  Events: full={n_event_full}, OOS={n_event_oos}")

    # IS corr for diagnostics
    is_mask = ~oos_mask
    corr_eav = float(np.corrcoef(r2[is_mask], eav_arr[is_mask])[0, 1]) \
        if is_mask.sum() > 10 else np.nan

    # ==========================================================================
    # OOS Rolling-refit forecasting
    # ==========================================================================
    oos_indices = np.where(oos_mask)[0]
    forecasts = {'A4f': np.full(n_oos_actual, np.nan),
                 'A4f_EAV': np.full(n_oos_actual, np.nan)}
    a4f_param_history = []
    a4f_eav_param_history = []

    state_a4f = {'params': None, 'g': None, 'tau_prev': None}
    state_eav = {'params': None, 'g': None, 'tau_prev': None}

    refit_count = 0
    for t_idx, abs_idx in enumerate(oos_indices):
        if t_idx % 250 == 0:
            elapsed = time.time() - START_TIME
            print(f"  [{key}] OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s)")

        need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)
        if need_refit:
            refit_count += 1
            train_start = max(0, abs_idx - WINDOW)
            train_ret = ret[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]
            train_eav = eav_arr[train_start:abs_idx]

            # --- A4f baseline ---
            params_a4f, ll_a4f = fit_a4f(train_ret, train_vix)
            if params_a4f is not None:
                state_a4f['params'] = params_a4f
                theta0, theta1_val, omega_g, alpha_p, gamma_p, beta_p = params_a4f
                a4f_param_history.append({
                    'refit': refit_count,
                    'date': str(df.index[abs_idx].date()),
                    'theta0': float(theta0),
                    'theta1': float(theta1_val),
                    'omega_g': float(omega_g),
                    'alpha': float(alpha_p),
                    'gamma': float(gamma_p),
                    'beta': float(beta_p),
                    'loglik': float(-ll_a4f),
                })
                n_train = len(train_ret)
                vix_lag_tr = np.empty(n_train)
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                tau_tr = compute_tau_a4f(theta0, theta1_val, vix_lag_tr)
                persist = alpha_p + gamma_p / 2.0 + beta_p
                g = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                for i in range(1, n_train):
                    # FIX: use tau_tr[i-1] not tau_tr[i].
                    u_prev = train_ret[i - 1] / np.sqrt(
                        max(tau_tr[i - 1], 1e-16))
                    asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
                    g = max(g, 1e-10)
                state_a4f['g'] = g
                # Carry the last-in-sample τ forward so that the first OOS
                # u_prev = r_{abs_idx-1} / sqrt(tau_prev) uses the τ that
                # was actually observed on the last training day.
                state_a4f['tau_prev'] = float(tau_tr[-1])

            # --- A4f-EAV ---
            params_eav, ll_eav = fit_a4f_eav(train_ret, train_vix, train_eav)
            if params_eav is not None:
                state_eav['params'] = params_eav
                theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = params_eav
                a4f_eav_param_history.append({
                    'refit': refit_count,
                    'date': str(df.index[abs_idx].date()),
                    'theta0': float(theta0),
                    'theta1': float(theta1_val),
                    'theta2': float(theta2_val),
                    'omega_g': float(omega_g),
                    'alpha': float(alpha_p),
                    'gamma': float(gamma_p),
                    'beta': float(beta_p),
                    'loglik': float(-ll_eav),
                })
                n_train = len(train_ret)
                vix_lag_tr = np.empty(n_train)
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                eav_lag_tr = np.empty(n_train)
                eav_lag_tr[0] = train_eav[0]
                eav_lag_tr[1:] = train_eav[:-1]
                tau_tr = compute_tau_a4f_eav(theta0, theta1_val, theta2_val,
                                             vix_lag_tr, eav_lag_tr)
                persist = alpha_p + gamma_p / 2.0 + beta_p
                g = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                for i in range(1, n_train):
                    u_prev = train_ret[i - 1] / np.sqrt(
                        max(tau_tr[i - 1], 1e-16))
                    asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
                    g = max(g, 1e-10)
                state_eav['g'] = g
                state_eav['tau_prev'] = float(tau_tr[-1])

        # --- Forecast for abs_idx ---
        v_lag = vix[abs_idx - 1]
        r_prev = ret[abs_idx - 1]
        eav_lag_val = eav_arr[abs_idx - 1]

        p = state_a4f['params']
        if p is not None and state_a4f['tau_prev'] is not None:
            theta0, theta1_val, omega_g, alpha_p, gamma_p, beta_p = p
            tau_t = compute_tau_a4f(theta0, theta1_val, v_lag)
            g_prev = state_a4f['g']
            # FIX: u_prev uses the previously-observed τ (state_a4f['tau_prev'])
            # not the forecast-day τ (tau_t).
            u_prev = r_prev / np.sqrt(max(state_a4f['tau_prev'], 1e-16))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g_new = max(omega_g + alpha_p * u_prev ** 2 + asym +
                        beta_p * g_prev, 1e-10)
            forecasts['A4f'][t_idx] = tau_t * g_new
            state_a4f['g'] = g_new
            state_a4f['tau_prev'] = float(tau_t)

        p = state_eav['params']
        if p is not None and state_eav['tau_prev'] is not None:
            theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = p
            tau_t = compute_tau_a4f_eav(theta0, theta1_val, theta2_val,
                                        v_lag, eav_lag_val)
            g_prev = state_eav['g']
            u_prev = r_prev / np.sqrt(max(state_eav['tau_prev'], 1e-16))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g_new = max(omega_g + alpha_p * u_prev ** 2 + asym +
                        beta_p * g_prev, 1e-10)
            forecasts['A4f_EAV'][t_idx] = tau_t * g_new
            state_eav['g'] = g_new
            state_eav['tau_prev'] = float(tau_t)

    print(f"  [{key}] OOS done — refits={refit_count}")

    # ==========================================================================
    # Evaluation
    # ==========================================================================
    oos_r2 = r2[oos_mask]
    out = {
        'firm': key,
        'ticker': ticker,
        'n_oos': n_oos_actual,
        'n_refits': refit_count,
        'in_sample_corr_r2_eav': corr_eav,
        'models': {},
        'dm_tests': {},
        'theta2_distribution': {},
        'event_window_analysis': {},
    }

    for name in ['A4f', 'A4f_EAV']:
        fc = forecasts[name]
        valid = np.isfinite(fc) & np.isfinite(oos_r2)
        n_valid = int(valid.sum())
        if n_valid < 100:
            continue
        fc_v = fc[valid]
        r2_v = oos_r2[valid]
        qlike_val = float(qlike(r2_v, fc_v))
        rho, rho_p = spearman_corr(r2_v, fc_v)
        out['models'][name] = {
            'qlike': qlike_val,
            'spearman_rho': float(rho),
            'spearman_p': float(rho_p),
            'n_valid': n_valid,
            'mean_forecast': float(np.mean(fc_v)),
        }

    # Aggregate DM test
    a4f_fc = forecasts['A4f']
    eav_fc = forecasts['A4f_EAV']
    valid = np.isfinite(a4f_fc) & np.isfinite(eav_fc) & np.isfinite(oos_r2)
    if valid.sum() >= 100:
        loss_a4f = qlike_pointwise(oos_r2[valid], a4f_fc[valid])
        loss_eav = qlike_pointwise(oos_r2[valid], eav_fc[valid])
        dm_t, dm_p = dm_test(loss_eav, loss_a4f)
        mean_loss_a4f = float(np.mean(loss_a4f))
        mean_loss_eav = float(np.mean(loss_eav))
        improvement_pct = ((mean_loss_a4f - mean_loss_eav) / mean_loss_a4f
                           * 100) if mean_loss_a4f != 0 else 0.0
        out['dm_tests']['A4f_EAV_vs_A4f'] = {
            'dm_t': float(dm_t),
            'dm_p': float(dm_p),
            'direction': 'EAV_better' if dm_t < 0 else 'A4f_better',
            'significant_harvey': bool(abs(dm_t) > 3.0),
            'mean_qlike_loss_a4f': mean_loss_a4f,
            'mean_qlike_loss_eav': mean_loss_eav,
            'qlike_improvement_pct': float(improvement_pct),
            'n_compared': int(valid.sum()),
        }

    # θ₂ distribution
    theta2_arr = np.array([h['theta2'] for h in a4f_eav_param_history])
    n_theta2 = len(theta2_arr)
    if n_theta2 >= 2:
        theta2_mean = float(theta2_arr.mean())
        theta2_std = float(theta2_arr.std(ddof=1))
        theta2_median = float(np.median(theta2_arr))
        positive_frac = float((theta2_arr > 0).mean())
        t_one, p_one = stats.ttest_1samp(theta2_arr, popmean=0.0,
                                         alternative='greater')
        rng = np.random.default_rng(42)
        boots = []
        for _ in range(2000):
            boots.append(float(rng.choice(theta2_arr, size=n_theta2,
                                          replace=True).mean()))
        ci_low = float(np.percentile(boots, 2.5))
        ci_high = float(np.percentile(boots, 97.5))
        out['theta2_distribution'] = {
            'n_refits': n_theta2,
            'mean': theta2_mean,
            'std': theta2_std,
            'median': theta2_median,
            'min': float(theta2_arr.min()),
            'max': float(theta2_arr.max()),
            'positive_fraction': positive_frac,
            'one_sample_t_vs_zero': float(t_one),
            'one_sample_p_one_sided': float(p_one),
            'bootstrap_ci_95': [ci_low, ci_high],
            'time_series': theta2_arr.tolist(),
        }

    # Event-window (T+1) DM
    event_t1_mask_full = np.concatenate([[False], eav_arr[:-1] > 0])
    event_t1_mask_oos = event_t1_mask_full[oos_mask]
    valid_all = np.isfinite(a4f_fc) & np.isfinite(eav_fc) & np.isfinite(oos_r2)
    event_t1_sub = valid_all & event_t1_mask_oos
    nonevent_sub = valid_all & (~event_t1_mask_oos)
    event_block = {
        'n_event_t1_days': int(event_t1_sub.sum()),
        'n_nonevent_days': int(nonevent_sub.sum()),
    }
    if event_t1_sub.sum() > 20:
        r2_ev = oos_r2[event_t1_sub]
        a4f_ev = a4f_fc[event_t1_sub]
        eav_ev = eav_fc[event_t1_sub]
        loss_a4f_ev = qlike_pointwise(r2_ev, a4f_ev)
        loss_eav_ev = qlike_pointwise(r2_ev, eav_ev)
        dm_t_ev, dm_p_ev = dm_test(loss_eav_ev, loss_a4f_ev)
        qlike_a4f_ev = float(qlike(r2_ev, a4f_ev))
        qlike_eav_ev = float(qlike(r2_ev, eav_ev))
        event_block['event_t1'] = {
            'dm_t': float(dm_t_ev),
            'dm_p': float(dm_p_ev),
            'qlike_a4f': qlike_a4f_ev,
            'qlike_eav': qlike_eav_ev,
            'improvement_pct': float((qlike_a4f_ev - qlike_eav_ev) /
                                     abs(qlike_a4f_ev) * 100)
                               if qlike_a4f_ev != 0 else 0.0,
        }
    else:
        event_block['event_t1'] = None
    if nonevent_sub.sum() > 100:
        r2_ne = oos_r2[nonevent_sub]
        a4f_ne = a4f_fc[nonevent_sub]
        eav_ne = eav_fc[nonevent_sub]
        loss_a4f_ne = qlike_pointwise(r2_ne, a4f_ne)
        loss_eav_ne = qlike_pointwise(r2_ne, eav_ne)
        dm_t_ne, dm_p_ne = dm_test(loss_eav_ne, loss_a4f_ne)
        qlike_a4f_ne = float(qlike(r2_ne, a4f_ne))
        qlike_eav_ne = float(qlike(r2_ne, eav_ne))
        event_block['nonevent'] = {
            'dm_t': float(dm_t_ne),
            'dm_p': float(dm_p_ne),
            'qlike_a4f': qlike_a4f_ne,
            'qlike_eav': qlike_eav_ne,
            'improvement_pct': float((qlike_a4f_ne - qlike_eav_ne) /
                                     abs(qlike_a4f_ne) * 100)
                               if qlike_a4f_ne != 0 else 0.0,
        }
    else:
        event_block['nonevent'] = None
    out['event_window_analysis'] = event_block

    # θ₂ history for chart
    out['parameter_history'] = {
        'a4f': a4f_param_history,
        'a4f_eav': a4f_eav_param_history,
    }
    return out


# ==========================================================================
# LOAD OLD (BUGGY) RESULTS FOR DIFF TABLE
# ==========================================================================
def load_old_results():
    """Load the old (buggy) k1067/k1067b/k1067c results JSONs for comparison."""
    old = {}
    for firm_key, fname in [
        ('TSMC', 'k1067/k1067_results.json'),
        ('MediaTek', 'k1067c/k1067c_results.json'),
        ('UMC', 'k1067b/k1067b_results.json'),
    ]:
        path = PROJECT_ROOT / 'experiments' / fname
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    old[firm_key] = json.load(f)
            except Exception as e:
                print(f"  Warning: could not load {path}: {e}")
    return old


# ==========================================================================
# MAIN
# ==========================================================================
print("=" * 78)
print(f"{EXPERIMENT_ID}: τ-lag Bug-Fix Replication Across TSMC/MediaTek/UMC")
print("=" * 78)

old_results = load_old_results()
all_firm_results = {}
for firm in FIRMS:
    try:
        all_firm_results[firm['key']] = run_firm(firm)
    except Exception as e:
        print(f"  ERROR running {firm['key']}: {e}")
        import traceback
        traceback.print_exc()
        all_firm_results[firm['key']] = {'error': str(e)}

# ==========================================================================
# OLD-vs-NEW COMPARISON TABLE
# ==========================================================================
print("\n" + "=" * 78)
print("OLD (buggy) vs NEW (τ-lag fixed)")
print("=" * 78)

comparison_rows = []
for firm in FIRMS:
    key = firm['key']
    new = all_firm_results.get(key, {})
    old = old_results.get(key, {})

    # Extract OLD numbers (fallback to hardcoded references if JSON missing)
    old_event_dm = firm['old_event_dm_t']
    old_event_impr = firm['old_event_improvement_pct']
    old_theta2_pos = firm['old_theta2_pos_frac']
    old_theta2_p = firm['old_theta2_p_one']
    old_agg_dm = firm['old_dm_t_aggregate']
    old_agg_impr = firm['old_improvement_pct_aggregate']

    if old:
        ev_old = (old.get('event_window_analysis') or {}).get('event_t1') or {}
        if 'dm_t' in ev_old:
            old_event_dm = float(ev_old['dm_t'])
        if 'improvement_pct' in ev_old:
            old_event_impr = float(ev_old['improvement_pct'])
        t2_old = old.get('theta2_distribution') or {}
        if 'positive_fraction' in t2_old:
            old_theta2_pos = float(t2_old['positive_fraction'])
        if 'one_sample_p_one_sided' in t2_old:
            old_theta2_p = float(t2_old['one_sample_p_one_sided'])
        dm_old = (old.get('dm_tests') or {}).get('A4f_EAV_vs_A4f') or {}
        if 'dm_t' in dm_old:
            old_agg_dm = float(dm_old['dm_t'])
        if 'qlike_improvement_pct' in dm_old:
            old_agg_impr = float(dm_old['qlike_improvement_pct'])

    # Extract NEW numbers
    ev_new = (new.get('event_window_analysis') or {}).get('event_t1') or {}
    new_event_dm = float(ev_new.get('dm_t', np.nan)) \
        if ev_new else np.nan
    new_event_impr = float(ev_new.get('improvement_pct', np.nan)) \
        if ev_new else np.nan
    t2_new = new.get('theta2_distribution') or {}
    new_theta2_pos = float(t2_new.get('positive_fraction', np.nan)) \
        if t2_new else np.nan
    new_theta2_p = float(t2_new.get('one_sample_p_one_sided', np.nan)) \
        if t2_new else np.nan
    dm_new = (new.get('dm_tests') or {}).get('A4f_EAV_vs_A4f') or {}
    new_agg_dm = float(dm_new.get('dm_t', np.nan)) if dm_new else np.nan
    new_agg_impr = float(dm_new.get('qlike_improvement_pct', np.nan)) \
        if dm_new else np.nan

    row = {
        'firm': key,
        'ticker': firm['ticker'],
        't1_amp': firm['t1_amp'],
        'old': {
            'event_dm_t': old_event_dm,
            'event_improvement_pct': old_event_impr,
            'theta2_pos_frac': old_theta2_pos,
            'theta2_p_one_sided': old_theta2_p,
            'aggregate_dm_t': old_agg_dm,
            'aggregate_improvement_pct': old_agg_impr,
        },
        'new': {
            'event_dm_t': new_event_dm,
            'event_improvement_pct': new_event_impr,
            'theta2_pos_frac': new_theta2_pos,
            'theta2_p_one_sided': new_theta2_p,
            'aggregate_dm_t': new_agg_dm,
            'aggregate_improvement_pct': new_agg_impr,
        },
        'delta': {
            'event_dm_t': new_event_dm - (old_event_dm or 0),
            'event_improvement_pct': new_event_impr - (old_event_impr or 0),
            'theta2_pos_frac': new_theta2_pos - (old_theta2_pos or 0)
                if np.isfinite(new_theta2_pos) and old_theta2_pos is not None
                else np.nan,
        },
    }
    comparison_rows.append(row)

    print(f"\n[{key} ({firm['ticker']}, T+1 amp={firm['t1_amp']:.2f})]")
    print(f"  Event DM t   : old={old_event_dm:+.3f}   →  new={new_event_dm:+.3f}   "
          f"Δ={new_event_dm - (old_event_dm or 0):+.3f}")
    print(f"  Event impr % : old={old_event_impr:+.3f} →  new={new_event_impr:+.3f} "
          f"Δ={new_event_impr - (old_event_impr or 0):+.3f}")
    print(f"  θ₂ pos_frac  : old={old_theta2_pos}      →  new={new_theta2_pos:.3f}")
    print(f"  θ₂ p one-sid : old={old_theta2_p}       →  new={new_theta2_p:.3e}")
    print(f"  Aggregate DM : old={old_agg_dm}          →  new={new_agg_dm:+.3f}")
    print(f"  Aggregate ΔQ%: old={old_agg_impr}        →  new={new_agg_impr:+.3f}")


# ==========================================================================
# FINAL VERDICT
# ==========================================================================
umc_row = next(r for r in comparison_rows if r['firm'] == 'UMC')
umc_new_event_dm = umc_row['new']['event_dm_t']

if np.isnan(umc_new_event_dm):
    scenario = 'ERROR'
    verdict = 'UMC run failed — cannot decide.'
elif abs(umc_new_event_dm) < 1.0:
    scenario = 'SCENARIO_1_DESTROYED'
    verdict = ('UMC event |t|<1 after fix → K1067b monotonicity story '
               'was a τ-lag artefact.  Paper 2 drops EAV entirely.')
elif abs(umc_new_event_dm) < 2.0:
    scenario = 'SCENARIO_2_WEAKENED'
    verdict = ('UMC event |t| in [1,2] after fix → partial artefact.  '
               'Paper 2 may keep event-window analysis with timing warning.')
else:
    scenario = 'SCENARIO_3_STABLE'
    verdict = ('UMC event |t| >= 2 after fix → bug is negligible.  '
               'K1067b/c monotonicity findings hold.')
print("\n" + "=" * 78)
print("FINAL VERDICT")
print("=" * 78)
print(f"  Scenario: {scenario}")
print(f"  {verdict}")
print(f"  UMC new event DM t = {umc_new_event_dm:+.3f}")

# ==========================================================================
# SAVE RESULTS
# ==========================================================================
out_json = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'τ-lag bug-fix replication across TSMC / MediaTek / UMC',
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'data_source': 'yfinance (auto_adjust) + 財報公告日.txt (Big5)',
    'data_period': f'{DATA_START} to {DATA_END}',
    'oos_start': OOS_START,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'random_seed': 42,
    'bug_description': (
        'K1067/K1067b/K1067c used u_prev = r_{t-1} / sqrt(tau[t]) inside '
        'the GARCH-MIDAS g update.  The correct form is '
        'u_prev = r_{t-1} / sqrt(tau[t-1]), because tau[t-1] is the '
        'long-run component observed at time t-1.  Using tau[t] leaks '
        'forecast-day exogenous state into the previous day\'s '
        'standardized residual.'
    ),
    'firms': {k: v for k, v in all_firm_results.items()},
    'comparison_old_vs_new': comparison_rows,
    'scenario': scenario,
    'final_verdict': verdict,
    'metadata': {
        'script': 'experiments/k1103/k1103.py',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'runtime_seconds': round(time.time() - START_TIME, 1),
        'references': [
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160.',
            'Harvey et al. (2016). DM t > 3.0 threshold.',
            'K1067, K1067b, K1067c (original buggy implementations).',
        ],
    },
}

with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
    json.dump(out_json, f, indent=2, ensure_ascii=False, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")

# ==========================================================================
# CHARTS
# ==========================================================================
print("\n[Charts] Generating comparison charts...")
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

firm_labels = [r['firm'] for r in comparison_rows]

# --- Chart 1: three-firm old-vs-new bar comparison ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
x = np.arange(len(firm_labels))
width = 0.35

ax = axes[0]
old_dm = [r['old']['event_dm_t'] for r in comparison_rows]
new_dm = [r['new']['event_dm_t'] for r in comparison_rows]
b1 = ax.bar(x - width/2, old_dm, width, color='#e67e22', edgecolor='black',
            label='Old (buggy)')
b2 = ax.bar(x + width/2, new_dm, width, color='#27ae60', edgecolor='black',
            label='New (τ-lag fixed)')
ax.axhline(y=0, color='black', alpha=0.4)
ax.axhline(y=-3.0, color='red', linestyle='--', alpha=0.5,
           label='Harvey |t|=3')
ax.axhline(y=3.0, color='red', linestyle='--', alpha=0.5)
ax.set_xticks(x)
ax.set_xticklabels(firm_labels)
ax.set_ylabel('Event-window DM t-statistic')
ax.set_title('Event (T+1) DM t: Old vs New')
for bars in (b1, b2):
    for bar, v in zip(bars, [bar.get_height() for bar in bars]):
        if np.isfinite(v):
            ax.annotate(f'{v:+.2f}',
                        xy=(bar.get_x() + bar.get_width() / 2, v),
                        xytext=(0, 4 if v >= 0 else -14),
                        textcoords='offset points',
                        ha='center', fontsize=8)
ax.legend(loc='best', fontsize=8)
ax.grid(axis='y', alpha=0.3)

ax = axes[1]
old_impr = [r['old']['event_improvement_pct'] for r in comparison_rows]
new_impr = [r['new']['event_improvement_pct'] for r in comparison_rows]
b1 = ax.bar(x - width/2, old_impr, width, color='#e67e22', edgecolor='black',
            label='Old (buggy)')
b2 = ax.bar(x + width/2, new_impr, width, color='#27ae60', edgecolor='black',
            label='New (τ-lag fixed)')
ax.axhline(y=0, color='black', alpha=0.4)
ax.set_xticks(x)
ax.set_xticklabels(firm_labels)
ax.set_ylabel('QLIKE improvement over A4f (%)')
ax.set_title('Event (T+1) QLIKE Improvement: Old vs New')
for bars in (b1, b2):
    for bar in bars:
        v = bar.get_height()
        if np.isfinite(v):
            ax.annotate(f'{v:+.2f}%',
                        xy=(bar.get_x() + bar.get_width() / 2, v),
                        xytext=(0, 4 if v >= 0 else -14),
                        textcoords='offset points',
                        ha='center', fontsize=8)
ax.legend(loc='best', fontsize=8)
ax.grid(axis='y', alpha=0.3)

plt.suptitle(f'K1103: τ-lag Bug-Fix Replication — {scenario}',
             fontsize=13, fontweight='bold')
plt.tight_layout()
p1 = SCRIPT_DIR / 'k1103_three_firms_comparison.png'
plt.savefig(p1, bbox_inches='tight')
plt.close()
print(f"  saved {p1}")

# --- Chart 2: θ₂ time-series (fixed) for all three firms ---
fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharey=False)
for ax, firm in zip(axes, FIRMS):
    key = firm['key']
    new = all_firm_results.get(key, {})
    t2 = (new.get('theta2_distribution') or {}).get('time_series', [])
    if t2:
        ax.plot(range(1, len(t2) + 1), t2, marker='o', color='#2980b9',
                linewidth=1.4, markersize=4)
        ax.axhline(y=0, color='black', alpha=0.3)
        t2dist = new['theta2_distribution']
        ax.set_title(f"{key} ({firm['ticker']})\n"
                     f"pos_frac={t2dist['positive_fraction']:.2f}  "
                     f"p={t2dist['one_sample_p_one_sided']:.3e}")
    else:
        ax.text(0.5, 0.5, 'No θ₂ data', ha='center', va='center',
                transform=ax.transAxes)
        ax.set_title(f"{key} ({firm['ticker']})")
    ax.set_xlabel('Refit #')
    ax.set_ylabel(r'$\theta_2$')
    ax.grid(True, alpha=0.3)
plt.suptitle('K1103: θ₂ Evolution (Fixed Code) — All Three Firms',
             fontsize=13, fontweight='bold')
plt.tight_layout()
p2 = SCRIPT_DIR / 'k1103_theta2_evolution_fixed.png'
plt.savefig(p2, bbox_inches='tight')
plt.close()
print(f"  saved {p2}")

# --- Chart 3: event-window analysis per firm (fixed) ---
fig, axes = plt.subplots(1, 3, figsize=(18, 5))
for ax, firm in zip(axes, FIRMS):
    key = firm['key']
    new = all_firm_results.get(key, {})
    ev = new.get('event_window_analysis') or {}
    e = ev.get('event_t1')
    ne = ev.get('nonevent')
    labels_ev = []
    impr_ev = []
    dm_t_list = []
    if e:
        labels_ev.append(f"T+1 Event\n(n={ev.get('n_event_t1_days')})")
        impr_ev.append(e['improvement_pct'])
        dm_t_list.append(e['dm_t'])
    if ne:
        labels_ev.append(f"Non-event\n(n={ev.get('n_nonevent_days')})")
        impr_ev.append(ne['improvement_pct'])
        dm_t_list.append(ne['dm_t'])
    if labels_ev:
        bar_colors = ['#e74c3c', '#3498db'][:len(labels_ev)]
        bars = ax.bar(labels_ev, impr_ev, color=bar_colors, edgecolor='black',
                      width=0.55)
        ax.axhline(y=0, color='black', alpha=0.4)
        ax.set_ylabel('QLIKE improvement (%)')
        ax.set_title(f"{key} ({firm['ticker']}) — FIXED")
        for b, impr, tval in zip(bars, impr_ev, dm_t_list):
            h = b.get_height()
            ax.text(b.get_x() + b.get_width()/2,
                    h + (0.01 if h >= 0 else -0.02),
                    f'{impr:+.2f}%\nt={tval:+.2f}',
                    ha='center', fontsize=8,
                    va='bottom' if h >= 0 else 'top')
    ax.grid(axis='y', alpha=0.3)
plt.suptitle('K1103: Event (T+1) vs Non-Event — All Three Firms (Fixed)',
             fontsize=13, fontweight='bold')
plt.tight_layout()
p3 = SCRIPT_DIR / 'k1103_event_window_fixed.png'
plt.savefig(p3, bbox_inches='tight')
plt.close()
print(f"  saved {p3}")

print(f"\nRuntime: {time.time() - START_TIME:.1f}s")
print("=" * 78)
print("K1103 DONE")
print("=" * 78)
