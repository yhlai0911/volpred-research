#!/usr/bin/env python3
"""
K1067b: UMC (2303.TW) Single-Stock A4f-EAV — Maximum Power Test vs K1067 TSMC
==============================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation / Big question:
  K1067 tested A4f+EAV on TSMC (2330.TW), which K1060 identified as having the
  *weakest* earnings-day vol amplification among Top 4 Taiwanese chip stocks
  (T+1 ratio=0.983, effectively zero excess event vol). Result: NULL
  (DM t=+0.348, θ₂ mean=-4.5e-4, one-sided p=0.95).

  However, TSMC's low T+1 amplification may reflect pre-announcement price-in
  (TSMC results are heavily anticipated by analysts) rather than absence of EAV
  signal. The K1067 NULL could therefore be a power problem, not a real
  falsification of the EAV hypothesis.

  K1067b runs the *maximum power* test: UMC (2303.TW), which K1060 reported as
  having T+1 amplification = 2.579 — the STRONGEST among the Top 4 chip stocks.
  UMC surprises markets more (less analyst coverage, less pre-announcement
  price-in), so any latent EAV signal should be MOST visible here.

  Decisive test design:
    - If UMC A4f+EAV PASSES  → K1067 TSMC NULL was a power problem;
                                Paper 2 can keep EAV BUT must pick high-surprise firms
    - If UMC A4f+EAV NULLS   → H_vix dominance confirmed across the surprise spectrum;
                                Paper 2 should REMOVE the EAV regressor entirely
    - If partial (|t|∈(1.96,3.0)) → mixed; descriptive-only claim for Paper 2

Hypotheses (mirror K1067 exactly):
  H1 (main): A4f+EAV delivers DM-significant improvement over A4f baseline
             on UMC (Harvey |t|>3.0) in OOS r² QLIKE.
  H2:        θ₂ (EAV loading) > 0 with statistical significance
             (one-sample t-test across refits, bootstrap CI excludes 0).
  H3:        Improvement concentrates on event windows (T+1 subsample DM |t|
             strictly larger than non-event subsample).
  H4:        UMC A4f+EAV improvement strictly exceeds K1067 TSMC improvement
             (testing power hypothesis: higher T+1 amplification → larger EAV edge).

Model specification (identical to K1067 — only asset changes):
  τ_{t+1} = max(θ₀ + θ₁·VIX²_t + θ₂·EAV_signal_t, ε)  (all info ≤ t close)
  u_t    = r_t / √τ_{t+1}
  g_t    = ω_g + α·u_{t-1}² + γ·u_{t-1}²·I(u<0) + β·g_{t-1}
  σ²_{t+1} = τ_{t+1} · g_{t+1}

  EAV_signal_t = 1 if day t is a UMC earnings announcement (post-close), else 0.
  Taiwan: announcements are released after daily close, so the indicator
  created on day t is used to forecast day t+1's variance — no look-ahead.

Data:
  - 2303.TW daily OHLC (yfinance, auto_adjust=True).
  - ^VIX daily (yfinance, Close).
  - 財報公告日.txt (Big5, filter code == '2303').
  - Period: 2010-01-01 ~ 2025-12-31 ; OOS: 2019-01-01 ~ end
  - WINDOW=2000, REFIT_EVERY=63 (quarterly), random seed=42
  - Methodology is 100% identical to K1067 so any difference is
    attributable to asset choice (UMC vs TSMC), not implementation drift.

Evaluation: identical to K1067 — QLIKE on r² (Patton 2011), Harvey DM |t|>3.0,
  θ₂ one-sample t-test + 2000-rep bootstrap CI, event T+1 vs non-event
  conditional DM, sub-period stability, lag robustness.

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). DM t > 3.0 threshold.
  - Patell & Wolfson (1984). Earnings announcement vol. JAR.
  - K1058: A4f on 0050.TW baseline.
  - K1060: Per-stock EAV — TSMC T+1=0.983 (weakest), UMC T+1=2.579 (strongest of Top 4).
  - K1064: ETF A4f+EAV all NULL.
  - K1067: TSMC A4f+EAV NULL (DM t=+0.348, θ₂ mean=-4.5e-4, one-sided p=0.95).

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
from numba import njit

import yfinance as yf

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1067b"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr  # noqa: E402

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
RESULTS_PATH = SCRIPT_DIR / 'k1067b_results.json'

# Configuration
TICKER = '2303.TW'
TICKER_CODE = '2303'   # UMC — for matching 財報公告日.txt (code==2303)
DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
OOS_START = '2019-01-01'
WINDOW = 2000            # rolling train window
REFIT_EVERY = 63         # quarterly refit

# K1067 TSMC reference for H4 comparison (power hypothesis test)
K1067_TSMC_IMPROVEMENT_PCT = -0.070  # TSMC A4f+EAV vs A4f
K1067_TSMC_DM_T = 0.348
K1067_TSMC_T1_AMP = 0.983            # K1060 TSMC T+1 amplification (weakest)

# UMC reference numbers (K1060)
K1060_UMC_T1_AMP = 2.579             # K1060 UMC T+1 amplification (strongest of Top 4)

# K1064 reference (0050.TW ETF) kept for context in charts
K1064_SECTOR_IMPROVEMENT_PCT = -0.207
K1064_TOP50_IMPROVEMENT_PCT = -0.419
K1064_EQUAL_IMPROVEMENT_PCT = -0.205

print("=" * 72)
print(f"{EXPERIMENT_ID}: UMC (2303.TW) single-stock A4f-EAV — max-power test vs K1067")
print("=" * 72)

# ==========================================================================
# SECTION 1: LOAD UMC EARNINGS ANNOUNCEMENTS
# ==========================================================================
print("\n[1] Loading UMC (2303) earnings announcements...")

with open(DATA_FILE, 'rb') as f:
    raw_text = f.read().decode('big5', errors='replace')

lines = raw_text.strip().split('\n')
tsmc_records = []
for line in lines[1:]:
    parts = line.strip().split('\t')
    if len(parts) >= 4:
        code = parts[0].strip()
        if code != TICKER_CODE:
            continue
        name = parts[1].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace('/', '-'))
                tsmc_records.append({'code': code, 'name': name, 'ym': ym, 'date': dt})
            except Exception:
                pass

ea_df = pd.DataFrame(tsmc_records)  # keep var name `tsmc_records` for code parity; holds UMC now
ea_df = ea_df[(ea_df['date'] >= DATA_START) & (ea_df['date'] <= DATA_END)].copy()
print(f"  UMC announcements (2010-2025): {len(ea_df)}")
if len(ea_df) > 0:
    print(f"  Date range: {ea_df['date'].min().date()} to {ea_df['date'].max().date()}")

# ==========================================================================
# SECTION 2: LOAD MARKET DATA (UMC 2303.TW + VIX)
# ==========================================================================
print("\n[2] Loading UMC + VIX market data...")

raw = yf.download(TICKER, start=DATA_START, end=DATA_END, progress=False,
                  auto_adjust=True)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices_umc = raw['Close'].copy().dropna()
log_ret_umc = np.log(prices_umc / prices_umc.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()
vix_ffill = vix_close.reindex(prices_umc.index, method='ffill')

df = pd.DataFrame({
    'price': prices_umc,
    'log_ret': log_ret_umc,
    'VIX': vix_ffill,
}).dropna()

# Drop extreme outliers (split/data error safety)
max_abs_ret = df['log_ret'].abs().max()
if max_abs_ret > 0.30:
    n_before = len(df)
    df = df[df['log_ret'].abs() <= 0.30]
    print(f"  WARNING: dropped {n_before - len(df)} extreme returns (>|30%|)")

print(f"  {TICKER}: {df.index[0].date()} to {df.index[-1].date()}, n={len(df)}")
print(f"  max |return|={df['log_ret'].abs().max():.4f}")

# ==========================================================================
# SECTION 3: BUILD UMC-SPECIFIC BINARY EAV SIGNAL
# ==========================================================================
print("\n[3] Building UMC-specific EAV signal...")

trading_days = df.index
eav_binary = np.zeros(len(trading_days), dtype=float)

# Map each UMC announcement to the *first trading day >= announcement date*
# (post-close announcement → signal known at that day's close)
ea_sorted = ea_df.sort_values('date').reset_index(drop=True)
pos_arr = trading_days.searchsorted(ea_sorted['date'].values)
mapped_count = 0
mapped_dates = set()
for i in range(len(ea_sorted)):
    pos = int(pos_arr[i])
    if pos >= len(trading_days):
        continue
    eav_binary[pos] = 1.0
    mapped_count += 1
    mapped_dates.add(trading_days[pos])

df['eav'] = eav_binary
n_event_days = int((df['eav'] > 0).sum())
print(f"  Announcements mapped: {mapped_count} → {n_event_days} distinct event trading days")
print(f"  Event-day fraction:   {n_event_days/len(df)*100:.2f}%")

# ==========================================================================
# SECTION 4: DIAGNOSTICS (observations-before-computation, per error_log rule 5)
# ==========================================================================
print("\n[4] Diagnostics...")

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2
eav_arr = df['eav'].values

# Full-sample descriptive stats
print(f"  Full sample: mean(r)={np.mean(ret)*252:.4f} (ann), "
      f"std(r)={np.std(ret)*np.sqrt(252):.4f} (ann)")
print(f"  Skewness={stats.skew(ret):.3f}, Kurtosis={stats.kurtosis(ret):.3f}")
print(f"  VIX mean={np.mean(vix):.2f}")

# OOS mask
oos_mask = np.array(df.index >= OOS_START)
n_oos_actual = int(oos_mask.sum())
oos_ret = ret[oos_mask]
n_oos_events = int((eav_arr[oos_mask] > 0).sum())
print(f"  OOS ({OOS_START}+): n={n_oos_actual}, event days in OOS={n_oos_events}")
print(f"  OOS mean={np.mean(oos_ret)*252:.4f} ann, std={np.std(oos_ret)*np.sqrt(252):.4f} ann")

# ADF test & ARCH LM on log returns (full sample)
try:
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.stats.diagnostic import het_arch
    adf_res = adfuller(ret, autolag='AIC', regression='c')
    arch_lm = het_arch(ret, nlags=10)
    print(f"  ADF stat={adf_res[0]:.3f}, p={adf_res[1]:.4f}")
    print(f"  ARCH-LM(10) stat={arch_lm[0]:.2f}, p={arch_lm[1]:.4e}")
    adf_stat = float(adf_res[0]); adf_p = float(adf_res[1])
    arch_stat = float(arch_lm[0]); arch_p = float(arch_lm[1])
except Exception as e:
    print(f"  Diagnostic tests skipped: {e}")
    adf_stat = adf_p = arch_stat = arch_p = np.nan

# In-sample correlation of r² with EAV (pre-OOS)
is_mask = ~oos_mask
corr_eav = float(np.corrcoef(r2[is_mask], eav_arr[is_mask])[0, 1])
print(f"  In-sample corr(r², EAV_binary): {corr_eav:+.4f}")

# Event-day vs non-event r² ratio (naive, full sample)
event_mask_full = eav_arr > 0
if event_mask_full.sum() > 5:
    r2_event = r2[event_mask_full].mean()
    r2_nonevent = r2[~event_mask_full].mean()
    r2_ratio_t0 = float(r2_event / r2_nonevent) if r2_nonevent > 0 else np.nan
    print(f"  Full-sample r²_event/r²_nonevent (T+0): {r2_ratio_t0:.3f} "
          f"(K1060 UMC T+1=2.579 — strongest among Top 4)")
    # T+1 ratio: shift event mask by 1
    event_mask_t1 = np.concatenate([[False], event_mask_full[:-1]])
    r2_t1 = r2[event_mask_t1].mean()
    r2_nonevent_t1 = r2[~event_mask_t1].mean()
    r2_ratio_t1 = float(r2_t1 / r2_nonevent_t1) if r2_nonevent_t1 > 0 else np.nan
    print(f"  Full-sample r²_event_t1/r²_other (T+1): {r2_ratio_t1:.3f}")
else:
    r2_ratio_t0 = r2_ratio_t1 = np.nan

# ==========================================================================
# SECTION 5: MODEL IMPLEMENTATIONS
# ==========================================================================
print("\n[5] Model implementations (A4f baseline + A4f-EAV)...")


def fit_a4f(returns, vix_vals):
    """Baseline A4f: τ_t = max(θ₀ + θ₁·VIX²_{t-1}, ε). 6 params."""
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
            u_prev = returns[t - 1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev ** 2 + asym + beta * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8

    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-8, 1e-3),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]

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
    return best_params, best_ll


def fit_a4f_eav(returns, vix_vals, eav_vals):
    """A4f + EAV: τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε). 7 params."""
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
            u_prev = returns[t - 1] / np.sqrt(max(tau[t], 1e-16))
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev ** 2 + asym + beta * g
            if g < 1e-10:
                g = 1e-10
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8
    eav_mean = np.mean(eav_lag) + 1e-8
    # EAV is binary → expected vol contribution ~ r²_event_boost × prob(event)
    # Scale θ₂ init so that θ₂·E[EAV] ≈ var0 * 0.05
    theta2_init_scale = var0 * 0.05 / max(eav_mean, 1e-4)

    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.0, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, theta2_init_scale, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, theta2_init_scale * 0.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, -theta2_init_scale * 0.5, 0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2),         # θ₀
        (1e-8, 1e-3),          # θ₁ (VIX²)
        (-1e-2, 1e-2),         # θ₂ (EAV)
        (1e-6, 1.0),           # ω_g
        (1e-4, 0.3),           # α
        (1e-4, 0.3),           # γ
        (0.5, 0.999),          # β
    ]

    best_ll = np.inf
    best_params = None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 800})
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
# SECTION 6: OUT-OF-SAMPLE FORECASTING (rolling refit)
# ==========================================================================
print("\n[6] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}, refit every {REFIT_EVERY} days, "
      f"window {WINDOW}")

forecasts = {'A4f': np.full(n_oos_actual, np.nan),
             'A4f_EAV': np.full(n_oos_actual, np.nan)}
a4f_param_history = []
a4f_eav_param_history = []

state_a4f = {'params': None, 'g': None}
state_eav = {'params': None, 'g': None}

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]
        train_eav = eav_arr[train_start:abs_idx]

        # Fit A4f baseline
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
                u_prev = train_ret[i - 1] / np.sqrt(max(tau_tr[i], 1e-16))
                asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
                g = max(g, 1e-10)
            state_a4f['g'] = g

        # Fit A4f-EAV
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
                u_prev = train_ret[i - 1] / np.sqrt(max(tau_tr[i], 1e-16))
                asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
                g = max(g, 1e-10)
            state_eav['g'] = g

    # --- Forecast for abs_idx using t-1 information (no lookahead) ---
    v_lag = vix[abs_idx - 1]
    r_prev = ret[abs_idx - 1]
    eav_lag_val = eav_arr[abs_idx - 1]

    # A4f baseline
    p = state_a4f['params']
    if p is not None:
        theta0, theta1_val, omega_g, alpha_p, gamma_p, beta_p = p
        tau_t = compute_tau_a4f(theta0, theta1_val, v_lag)
        g_prev = state_a4f['g']
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g_prev, 1e-10)
        forecasts['A4f'][t_idx] = tau_t * g_new
        state_a4f['g'] = g_new

    # A4f-EAV
    p = state_eav['params']
    if p is not None:
        theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = p
        tau_t = compute_tau_a4f_eav(theta0, theta1_val, theta2_val, v_lag, eav_lag_val)
        g_prev = state_eav['g']
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g_prev, 1e-10)
        forecasts['A4f_EAV'][t_idx] = tau_t * g_new
        state_eav['g'] = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting complete: {refit_count} refits in {elapsed:.0f}s")

# ==========================================================================
# SECTION 7: EVALUATION (QLIKE, DM, Spearman)
# ==========================================================================
print("\n[7] Evaluation...")

oos_r2 = r2[oos_mask]
event_mask_oos = (eav_arr[oos_mask] > 0)

# Event T+1 mask: day after announcement (within OOS)
event_t1_mask_full = np.concatenate([[False], eav_arr[:-1] > 0])
event_t1_mask_oos = event_t1_mask_full[oos_mask]

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'UMC (2303.TW) Single-Stock A4f-EAV — Maximum Power Test vs K1067 TSMC',
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'asset': TICKER,
    'external_regressors': ['US_VIX', 'UMC_EAV_binary'],
    'data_source': 'yfinance (auto_adjust) + 財報公告日.txt (Big5)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(len(df)),
    'n_oos': int(n_oos_actual),
    'oos_start': OOS_START,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'n_event_days_full': int(event_mask_full.sum()),
    'n_event_days_oos': int(event_mask_oos.sum()),
    'n_event_t1_days_oos': int(event_t1_mask_oos.sum()),
    'diagnostics': {
        'mean_return_ann': float(np.mean(ret) * 252),
        'std_return_ann': float(np.std(ret) * np.sqrt(252)),
        'skewness': float(stats.skew(ret)),
        'kurtosis': float(stats.kurtosis(ret)),
        'adf_stat': adf_stat,
        'adf_p': adf_p,
        'arch_lm_stat': arch_stat,
        'arch_lm_p': arch_p,
        'vix_mean': float(np.mean(vix)),
        'in_sample_corr_r2_eav': corr_eav,
        'r2_ratio_t0': r2_ratio_t0,
        'r2_ratio_t1': r2_ratio_t1,
    },
    'models': {},
    'dm_tests': {},
    'theta2_distribution': {},
    'event_window_analysis': {},
    'subperiod_analysis': {},
    'robustness': {},
    'h4_diversification_comparison': {},
}

# Model-level metrics
for name in ['A4f', 'A4f_EAV']:
    fc = forecasts[name]
    valid = np.isfinite(fc) & np.isfinite(oos_r2)
    n_valid = int(valid.sum())
    if n_valid < 100:
        print(f"  {name}: too few valid ({n_valid})")
        continue
    fc_v = fc[valid]
    r2_v = oos_r2[valid]
    qlike_val = float(qlike(r2_v, fc_v))
    rho, rho_p = spearman_corr(r2_v, fc_v)
    mse_val = float(np.mean((r2_v - fc_v) ** 2))
    results['models'][name] = {
        'qlike': qlike_val,
        'mse': mse_val,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
        'n_valid': n_valid,
        'mean_forecast': float(np.mean(fc_v)),
        'std_forecast': float(np.std(fc_v)),
    }
    print(f"  {name:10s}: QLIKE={qlike_val:.6f}, Spearman ρ={rho:+.4f} (p={rho_p:.4f}), n={n_valid}")

# DM test: A4f_EAV vs A4f
print("\n  DM tests (negative t → EAV better):")
a4f_fc = forecasts['A4f']
eav_fc = forecasts['A4f_EAV']
valid = np.isfinite(a4f_fc) & np.isfinite(eav_fc) & np.isfinite(oos_r2)
if valid.sum() >= 100:
    loss_a4f = qlike_pointwise(oos_r2[valid], a4f_fc[valid])
    loss_eav = qlike_pointwise(oos_r2[valid], eav_fc[valid])
    dm_t, dm_p = dm_test(loss_eav, loss_a4f)
    direction = 'EAV_better' if dm_t < 0 else 'A4f_better'
    significant = abs(dm_t) > 3.0
    mean_loss_a4f = float(np.mean(loss_a4f))
    mean_loss_eav = float(np.mean(loss_eav))
    improvement_pct = (mean_loss_a4f - mean_loss_eav) / mean_loss_a4f * 100 \
        if mean_loss_a4f != 0 else 0.0
    results['dm_tests']['A4f_EAV_vs_A4f'] = {
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'significant_harvey': bool(significant),
        'direction': direction,
        'n_compared': int(valid.sum()),
        'mean_qlike_loss_a4f': mean_loss_a4f,
        'mean_qlike_loss_eav': mean_loss_eav,
        'qlike_improvement_pct': float(improvement_pct),
    }
    print(f"    A4f_EAV vs A4f: t={dm_t:+.3f}, p={dm_p:.4f}, "
          f"improve={improvement_pct:+.3f}%, Harvey(|t|>3)={significant}, dir={direction}")

# ==========================================================================
# SECTION 8: θ₂ DISTRIBUTION ACROSS REFITS (H2)
# ==========================================================================
print("\n[8] θ₂ distribution across refits...")

theta2_arr = np.array([h['theta2'] for h in a4f_eav_param_history])
n_theta2 = len(theta2_arr)

if n_theta2 >= 2:
    theta2_mean = float(theta2_arr.mean())
    theta2_std = float(theta2_arr.std(ddof=1))
    theta2_median = float(np.median(theta2_arr))
    positive_frac = float((theta2_arr > 0).mean())
    t_one, p_one = stats.ttest_1samp(theta2_arr, popmean=0.0, alternative='greater')
    # Bootstrap 95% CI
    rng = np.random.default_rng(42)
    boots = []
    for _ in range(2000):
        sample = rng.choice(theta2_arr, size=n_theta2, replace=True)
        boots.append(float(sample.mean()))
    ci_low = float(np.percentile(boots, 2.5))
    ci_high = float(np.percentile(boots, 97.5))

    results['theta2_distribution'] = {
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
    }
    print(f"  θ₂: mean={theta2_mean:+.3e}, std={theta2_std:.3e}, "
          f"median={theta2_median:+.3e}, pos_frac={positive_frac:.2f}")
    print(f"  t(θ₂>0)={t_one:+.2f}, p={p_one:.4f}, CI95=[{ci_low:.3e}, {ci_high:.3e}]")

# ==========================================================================
# SECTION 9: EVENT-WINDOW CONDITIONAL ANALYSIS (H3)
# ==========================================================================
print("\n[9] Event (T+1) vs non-event conditional DM...")

# T+1 subsample: day after announcement; non-event: all other OOS days
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
                                 abs(qlike_a4f_ev) * 100) if qlike_a4f_ev != 0 else 0.0,
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
                                 abs(qlike_a4f_ne) * 100) if qlike_a4f_ne != 0 else 0.0,
    }
else:
    event_block['nonevent'] = None

results['event_window_analysis'] = event_block
if event_block.get('event_t1') and event_block.get('nonevent'):
    e = event_block['event_t1']; ne = event_block['nonevent']
    print(f"  T+1 event: n={event_block['n_event_t1_days']}, DM t={e['dm_t']:+.3f}, "
          f"improve={e['improvement_pct']:+.3f}%")
    print(f"  non-event: n={event_block['n_nonevent_days']}, DM t={ne['dm_t']:+.3f}, "
          f"improve={ne['improvement_pct']:+.3f}%")

# ==========================================================================
# SECTION 10: SUB-PERIOD STABILITY (5 equal sub-periods)
# ==========================================================================
print("\n[10] Sub-period stability analysis...")

n_subperiods = 5
if valid_all.sum() >= 5 * 100:
    valid_oos_indices = np.where(valid_all)[0]
    chunks = np.array_split(valid_oos_indices, n_subperiods)
    oos_dates = df.index[oos_indices]
    for k, idx_chunk in enumerate(chunks):
        if len(idx_chunk) < 50:
            continue
        r2_k = oos_r2[idx_chunk]
        a4f_k = a4f_fc[idx_chunk]
        eav_k = eav_fc[idx_chunk]
        loss_a4f_k = qlike_pointwise(r2_k, a4f_k)
        loss_eav_k = qlike_pointwise(r2_k, eav_k)
        dm_t_k, dm_p_k = dm_test(loss_eav_k, loss_a4f_k)
        qlike_a4f_k = float(qlike(r2_k, a4f_k))
        qlike_eav_k = float(qlike(r2_k, eav_k))
        results['subperiod_analysis'][f'period_{k+1}'] = {
            'start': str(oos_dates[idx_chunk[0]].date()),
            'end': str(oos_dates[idx_chunk[-1]].date()),
            'n': int(len(idx_chunk)),
            'dm_t': float(dm_t_k),
            'dm_p': float(dm_p_k),
            'qlike_a4f': qlike_a4f_k,
            'qlike_eav': qlike_eav_k,
            'improvement_pct': float((qlike_a4f_k - qlike_eav_k) /
                                     abs(qlike_a4f_k) * 100) if qlike_a4f_k != 0 else 0.0,
        }
        print(f"  Period {k+1}: {oos_dates[idx_chunk[0]].date()}~{oos_dates[idx_chunk[-1]].date()}, "
              f"n={len(idx_chunk)}, DM t={dm_t_k:+.3f}, improve={results['subperiod_analysis'][f'period_{k+1}']['improvement_pct']:+.3f}%")

# ==========================================================================
# SECTION 11: ROBUSTNESS — LAG SENSITIVITY (in-sample quick check)
# ==========================================================================
print("\n[11] Robustness: EAV lag sensitivity (in-sample)...")


def fit_and_score_full_sample(eav_series, label):
    full_params, full_ll = fit_a4f_eav(ret, vix, eav_series)
    if full_params is None:
        return None
    theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = full_params
    n = len(ret)
    vix_lag = np.empty(n); vix_lag[0] = vix[0]; vix_lag[1:] = vix[:-1]
    eav_lag = np.empty(n); eav_lag[0] = eav_series[0]; eav_lag[1:] = eav_series[:-1]
    tau = compute_tau_a4f_eav(theta0, theta1_val, theta2_val, vix_lag, eav_lag)
    persist = alpha_p + gamma_p / 2.0 + beta_p
    g = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
    sigma2 = np.empty(n)
    sigma2[0] = tau[0] * g
    for t in range(1, n):
        u_prev = ret[t-1] / np.sqrt(max(tau[t], 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
        g = max(g, 1e-10)
        sigma2[t] = tau[t] * g
    is_qlike = float(qlike(r2[1:], sigma2[1:]))
    return {
        'label': label,
        'theta2': float(theta2_val),
        'theta1': float(theta1_val),
        'in_sample_qlike': is_qlike,
        'in_sample_loglik': float(-full_ll),
    }


eav_base = eav_arr.copy()
rb_default = fit_and_score_full_sample(eav_base, 'EAV_t-1 (default)')
# t-2: extra lag
eav_t2 = np.empty_like(eav_base); eav_t2[0] = eav_base[0]; eav_t2[1:] = eav_base[:-1]
rb_t2 = fit_and_score_full_sample(eav_t2, 'EAV_t-2')
# rolling 3-day sum
eav_roll3 = pd.Series(eav_base, index=df.index).rolling(3, min_periods=1).sum().values
rb_roll3 = fit_and_score_full_sample(eav_roll3, 'EAV rolling-3d')

results['robustness']['lag_sensitivity'] = [rb_default, rb_t2, rb_roll3]
for rb in [rb_default, rb_t2, rb_roll3]:
    if rb is not None:
        print(f"  {rb['label']:22s}: θ₂={rb['theta2']:+.3e}, IS QLIKE={rb['in_sample_qlike']:.6f}")

# ==========================================================================
# SECTION 12: H4 — POWER COMPARISON vs K1067 TSMC
# ==========================================================================
print("\n[12] H4 — UMC improvement vs K1067 TSMC improvement (power hypothesis)...")

umc_improvement = results['dm_tests'].get('A4f_EAV_vs_A4f', {}).get('qlike_improvement_pct', np.nan)
umc_dm_t = results['dm_tests'].get('A4f_EAV_vs_A4f', {}).get('dm_t', np.nan)

# H4 PASS = UMC strictly beats TSMC improvement (testing power: higher T+1 amp → larger edge)
h4_verdict = 'PASS' if umc_improvement > K1067_TSMC_IMPROVEMENT_PCT else 'FAIL'
results['h4_diversification_comparison'] = {
    'umc_improvement_pct': umc_improvement,
    'umc_dm_t': umc_dm_t,
    'umc_t1_amplification_k1060': K1060_UMC_T1_AMP,
    'tsmc_improvement_pct_k1067': K1067_TSMC_IMPROVEMENT_PCT,
    'tsmc_dm_t_k1067': K1067_TSMC_DM_T,
    'tsmc_t1_amplification_k1060': K1067_TSMC_T1_AMP,
    'umc_strictly_better_than_tsmc': bool(umc_improvement > K1067_TSMC_IMPROVEMENT_PCT),
    'h4_verdict': h4_verdict,
    # retain ETF reference for chart consistency
    'etf_sector_improvement_pct_k1064': K1064_SECTOR_IMPROVEMENT_PCT,
    'etf_equal_improvement_pct_k1064': K1064_EQUAL_IMPROVEMENT_PCT,
    'etf_top50_improvement_pct_k1064': K1064_TOP50_IMPROVEMENT_PCT,
}
print(f"  UMC  improvement: {umc_improvement:+.3f}% (T+1 amp={K1060_UMC_T1_AMP:.3f})")
print(f"  TSMC improvement: {K1067_TSMC_IMPROVEMENT_PCT:+.3f}% (T+1 amp={K1067_TSMC_T1_AMP:.3f}) [K1067 ref]")
print(f"  H4 verdict: {h4_verdict}")

# ==========================================================================
# SECTION 13: SAVE RESULTS
# ==========================================================================
print("\n[13] Saving results...")

results['parameter_history'] = {
    'a4f': a4f_param_history,
    'a4f_eav': a4f_eav_param_history,
}
results['metadata'] = {
    'script': 'k1067b.py',
    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(time.time() - START_TIME, 1),
    'random_seed': 42,
    'references': [
        'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey et al. (2016). DM t > 3.0 threshold.',
        'Patell & Wolfson (1984). Earnings announcement vol. JAR.',
        'K1058: A4f on 0050.TW baseline.',
        'K1060: Per-stock EAV — TSMC T+1=0.983 (weakest), UMC T+1=2.579 (strongest of Top 4).',
        'K1064: ETF A4f+EAV all NULL (DM t=+1.08/+0.96/+2.36).',
        'K1067: TSMC single-stock A4f+EAV NULL (DM t=+0.348, θ₂ mean=-4.5e-4).',
    ],
    'notes': [
        'UMC 2303.TW uses yfinance auto_adjust=True (individual stock, not ETF).',
        'EAV is binary (announcement-day indicator) since we test one company only.',
        'Timing: Taiwan announcements post-close → signal at t close → forecasts t+1 vol.',
        'UMC chosen because K1060 reported T+1 amplification=2.579 — strongest among '
        'Top 4 chip stocks (TSMC=0.983, MediaTek=1.67, Hon Hai=1.22, UMC=2.579). '
        'This is the maximum-power test of the EAV hypothesis at single-stock level.',
        'Methodology is 100% identical to K1067 so any result difference can only be '
        'attributed to the asset choice (UMC vs TSMC).',
        'Decisive test: UMC PASS → K1067 NULL = power problem (Paper 2 can keep EAV '
        'for high-surprise firms); UMC NULL → H_vix dominates (Paper 2 should drop EAV).',
    ],
}

with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"  Results saved to {RESULTS_PATH}")

# ==========================================================================
# SECTION 14: CHARTS
# ==========================================================================
print("\n[14] Generating charts...")
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# --- Chart 1: DM comparison (UMC vs TSMC vs K1064 ETF — full context) ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: QLIKE bar (UMC A4f vs A4f+EAV)
ax = axes[0]
bar_labels = ['A4f (UMC)', 'A4f+EAV (UMC)']
bar_qlikes = [results['models'].get('A4f', {}).get('qlike', np.nan),
              results['models'].get('A4f_EAV', {}).get('qlike', np.nan)]
bar_colors = ['#3498db', '#e74c3c']
bars = ax.barh(bar_labels, bar_qlikes, color=bar_colors, edgecolor='white', height=0.55)
ax.set_xlabel('QLIKE (lower = better)')
ax.set_title(f'QLIKE on r² — UMC OOS ({OOS_START}+)')
for bar, val in zip(bars, bar_qlikes):
    if np.isfinite(val):
        ax.text(bar.get_width() * 1.001, bar.get_y() + bar.get_height() / 2,
                f'{val:.5f}', va='center', fontsize=9)

# Right: DM t-stat comparison UMC vs TSMC (K1067) vs K1064 ETF variants (H4)
ax = axes[1]
comp_labels = ['UMC\n(K1067b)', 'TSMC\n(K1067)', 'ETF equal\n(K1064)',
               'ETF sector\n(K1064)', 'ETF top50\n(K1064)']
umc_t_val = results['dm_tests'].get('A4f_EAV_vs_A4f', {}).get('dm_t', np.nan)
comp_ts = [umc_t_val, K1067_TSMC_DM_T, 1.082, 0.959, 2.360]
comp_colors = ['#27ae60' if abs(v) > 3.0 else
               '#e67e22' if abs(v) > 1.96 else '#95a5a6' for v in comp_ts]
bars2 = ax.barh(comp_labels, comp_ts, color=comp_colors, height=0.5, edgecolor='black')
ax.axvline(x=-3.0, color='red', linestyle='--', alpha=0.7, label='Harvey |t|=3.0')
ax.axvline(x=3.0, color='red', linestyle='--', alpha=0.7)
ax.axvline(x=-1.96, color='gray', linestyle=':', alpha=0.5, label='Std |t|=1.96')
ax.axvline(x=1.96, color='gray', linestyle=':', alpha=0.5)
ax.axvline(x=0, color='gray', linestyle='-', alpha=0.3)
ax.set_xlabel('DM t-statistic (negative = EAV variant better)')
ax.set_title('DM Tests: UMC vs TSMC vs K1064 ETF\n(all A4f+EAV vs A4f baseline)')
for bar, v in zip(bars2, comp_ts):
    if np.isfinite(v):
        ax.text(bar.get_width() + (0.05 if bar.get_width() >= 0 else -0.05),
                bar.get_y() + bar.get_height() / 2,
                f'{v:+.2f}', va='center', fontsize=9,
                ha='left' if bar.get_width() >= 0 else 'right')
ax.legend(loc='best', fontsize=8)
plt.tight_layout()
chart1_path = SCRIPT_DIR / 'k1067b_dm_comparison.png'
plt.savefig(chart1_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart1_path}")

# --- Chart 2: Event (T+1) vs non-event conditional performance ---
fig, ax = plt.subplots(figsize=(10, 5))
ev_block = results.get('event_window_analysis', {})
labels_ev = []
impr_ev = []
dm_t_ev_list = []
if ev_block.get('event_t1'):
    labels_ev.append(f"T+1 Event\n(n={ev_block['n_event_t1_days']})")
    impr_ev.append(ev_block['event_t1']['improvement_pct'])
    dm_t_ev_list.append(ev_block['event_t1']['dm_t'])
if ev_block.get('nonevent'):
    labels_ev.append(f"Non-event\n(n={ev_block['n_nonevent_days']})")
    impr_ev.append(ev_block['nonevent']['improvement_pct'])
    dm_t_ev_list.append(ev_block['nonevent']['dm_t'])

if labels_ev:
    bar_colors_ev = ['#e74c3c', '#3498db']
    xpos = np.arange(len(labels_ev))
    bars3 = ax.bar(xpos, impr_ev, color=bar_colors_ev, edgecolor='black', width=0.55)
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.4)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels_ev)
    ax.set_ylabel('QLIKE improvement vs A4f (%)')
    ax.set_title('UMC A4f+EAV: Event (T+1) vs Non-event days')
    for b, impr, tval in zip(bars3, impr_ev, dm_t_ev_list):
        h = b.get_height()
        ax.text(b.get_x() + b.get_width()/2, h + (0.01 if h >= 0 else -0.02),
                f'{impr:+.3f}%\nt={tval:+.2f}',
                ha='center', fontsize=9,
                va='bottom' if h >= 0 else 'top')
    ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart2_path = SCRIPT_DIR / 'k1067b_event_window_analysis.png'
plt.savefig(chart2_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart2_path}")

# --- Chart 3: θ₂ evolution across refits ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: θ₂ time-series
ax = axes[0]
if a4f_eav_param_history:
    theta2_ts = [h['theta2'] for h in a4f_eav_param_history]
    refit_nums = [h['refit'] for h in a4f_eav_param_history]
    ax.plot(refit_nums, theta2_ts, marker='o', color='#e74c3c',
            linewidth=1.5, markersize=5)
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.4)
    ax.set_xlabel('Refit #')
    ax.set_ylabel(r'$\theta_2$ (EAV loading)')
    ax.set_title(r'UMC A4f+EAV: $\theta_2$ Evolution')
    ax.grid(True, alpha=0.3)

# Right: θ₂ mean + 95% bootstrap CI
ax = axes[1]
if n_theta2 >= 2:
    t2_dist = results['theta2_distribution']
    m = t2_dist['mean']
    lo = t2_dist['bootstrap_ci_95'][0]
    hi = t2_dist['bootstrap_ci_95'][1]
    ax.bar([0], [m], yerr=[[m - lo], [hi - m]], color='#e74c3c',
           edgecolor='black', capsize=6, alpha=0.85, width=0.3)
    ax.axhline(y=0, color='red', linestyle='--', alpha=0.5, label=r'$\theta_2=0$')
    ax.set_xticks([0])
    ax.set_xticklabels(['UMC A4f+EAV'])
    ax.set_ylabel(r'$\theta_2$ (mean ± 95% bootstrap CI)')
    ax.set_title(r'$\theta_2$ Point Estimate + 95% Bootstrap CI')
    ax.text(0, m + (hi - m) * 0.3 if (hi - m) > 0 else m * 0.1,
            f'mean={m:+.2e}\npos_frac={t2_dist["positive_fraction"]:.2f}\n'
            f't={t2_dist["one_sample_t_vs_zero"]:+.2f}\n'
            f'p={t2_dist["one_sample_p_one_sided"]:.3f}',
            ha='center', fontsize=8,
            bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray'))
    ax.legend()
plt.tight_layout()
chart3_path = SCRIPT_DIR / 'k1067b_theta2_evolution.png'
plt.savefig(chart3_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart3_path}")

# ==========================================================================
# SECTION 15: SUMMARY
# ==========================================================================
print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)

# H1
dm = results['dm_tests'].get('A4f_EAV_vs_A4f', {})
if dm:
    h1_verdict = 'PASS' if dm.get('significant_harvey') and dm.get('dm_t', 0) < 0 else 'FAIL'
    print(f"  H1 (DM Harvey |t|>3): {h1_verdict} "
          f"(t={dm['dm_t']:+.3f}, dir={dm['direction']}, improve={dm['qlike_improvement_pct']:+.3f}%)")
else:
    h1_verdict = 'ERROR'

# H2
if n_theta2 >= 2:
    t2 = results['theta2_distribution']
    h2_verdict = 'PASS' if (t2['one_sample_p_one_sided'] < 0.05 and t2['bootstrap_ci_95'][0] > 0) else 'FAIL'
    print(f"  H2 (θ₂>0):           {h2_verdict} "
          f"(mean={t2['mean']:+.3e}, t={t2['one_sample_t_vs_zero']:+.2f}, "
          f"p={t2['one_sample_p_one_sided']:.4f}, CI95=[{t2['bootstrap_ci_95'][0]:.2e}, {t2['bootstrap_ci_95'][1]:.2e}])")
else:
    h2_verdict = 'ERROR'

# H3
ev_blk = results.get('event_window_analysis', {})
if ev_blk.get('event_t1') and ev_blk.get('nonevent'):
    h3_verdict = 'PASS' if abs(ev_blk['event_t1']['dm_t']) > abs(ev_blk['nonevent']['dm_t']) else 'FAIL'
    print(f"  H3 (event |t|>non-ev|t|): {h3_verdict} "
          f"(event |t|={abs(ev_blk['event_t1']['dm_t']):.3f}, "
          f"non-event |t|={abs(ev_blk['nonevent']['dm_t']):.3f})")
else:
    h3_verdict = 'ERROR'

# H4
h4_verdict_s = results['h4_diversification_comparison']['h4_verdict']
print(f"  H4 (UMC > TSMC K1067): {h4_verdict_s}")

# Research interpretation — Paper 2 decisive test
print("\n  ===== Interpretation — Paper 2 Decisive Test =====")
if h1_verdict == 'PASS':
    print("  → DECISION: K1067 TSMC NULL was a POWER PROBLEM, not signal absence.")
    print("    UMC's higher surprise component (T+1=2.579) carries real EAV signal.")
    print("    Paper 2 CAN keep EAV as regressor IF assets chosen have high earnings surprise.")
    print("    Recommend further validation on MediaTek (T+1=1.67).")
elif h1_verdict == 'FAIL' and h4_verdict_s == 'PASS':
    print("  → MIXED: UMC delivers a bit more EAV signal than TSMC but still below DM threshold.")
    print("    Paper 2: descriptive event-study only. Cannot claim EAV as prediction regressor.")
else:
    print("  → DECISION: H_vix DOMINATES across the surprise spectrum.")
    print("    Even UMC (strongest T+1 amplification) cannot extract EAV signal once VIX² is in τ.")
    print("    Paper 2 MUST REMOVE EAV from A4f regressor list — it is empirically redundant.")
    print("    Retain K1059's A4f-vs-GJR event-amplification finding (architectural claim only).")

print(f"\n  Runtime: {time.time() - START_TIME:.1f}s")
print("=" * 72)
print("DONE")
