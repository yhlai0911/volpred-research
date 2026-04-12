#!/usr/bin/env python3
"""
K1064: TW_EAV_factor as Exogenous Regressor in A4f — From Description to Prediction
====================================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1060 established that individual Taiwan stocks show significant T+1 EAV
  (ratio = 1.466, binom p = 0.034). K1062 showed 0050.TW ETF-level T+1 ratio = 1.132
  (directional but NS due to diversification dilution). K1059 showed A4f vs GJR
  advantage is amplified during earnings-event windows (DM t = 2.50 vs 1.22).

  All three findings are *descriptive*. The question now: can we use the EAV
  signal as an *active exogenous regressor* inside A4f to improve OOS volatility
  prediction for 0050.TW?

  H1 (main):     A4f+EAV delivers DM-significant improvement over A4f (|t|>3.0)
  H2:            θ₂ (EAV loading) > 0 and statistically significant
  H3:            Improvement concentrates in event-window subsamples

Model specification (no-lookahead):
  τ_{t+1} = max(θ₀ + θ₁·VIX²_t + θ₂·EAV_signal_t, ε)   (all info ≤ t close)
  u_t    = r_t / sqrt(τ_{t+1})  (evaluated at forecast step)
  g_t    = ω_g + α·u_{t-1}² + γ·u_{t-1}²·I(u<0) + β·g_{t-1}
  σ²_{t+1} = τ_{t+1} · g_{t+1}

  EAV_signal_t = Σ_i weight_i · 1(company i announced on day t)
  Taiwan announcements are post-close → signal known at t close, forecasts t+1 vol.

Variants tested:
  (v1) equal-weight EAV (every announcing company = 1)
  (v2) sector-weighted EAV (K1060 T+1 ratios: tech 1.60, fin 1.29, trad 2.15, tel 0.85)
  (v3) top-50 market-cap proxy (restricted to 0050.TW constituents ≈ weight 1)

Data Sources:
  - 財報公告日.txt  (Big5, ~158K records, 1986-2025, 2,411 unique companies)
  - 0050.TW daily  (yfinance, cleaned with clean_tw50_data)
  - ^VIX daily      (yfinance)
  - Period: 2010-01-01 ~ 2025-12-31 ; OOS: 2019-01-01 onwards

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test vs A4f baseline (Harvey |t|>3.0)
  - θ₂ t-stat bootstrapped across refits
  - Event vs non-event conditional DM
  - Robustness: EAV_t vs EAV_{t-1}

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256
  - Harvey et al. (2016). Diebold-Mariano t>3.0 threshold
  - Patell & Wolfson (1984). Earnings announcement vol. JAR
  - K1058: A4f on 0050.TW (baseline)
  - K1059: A4f vs GJR event-window amplification (DM t=2.50 vs 1.22)
  - K1060: Individual TW stock T+1 ratio=1.466, sectoral heterogeneity
  - K1062: ETF T+1 ratio=1.132 (diversification dilution)

Random seed: 42
Author: VolPred Research System
Date: 2026-04-12
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
EXPERIMENT_ID = "K1064"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr  # noqa: E402
from volpred.utils import clean_tw50_data  # noqa: E402

DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
RESULTS_PATH = SCRIPT_DIR / 'k1064_results.json'

# Configuration
DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
OOS_START = '2019-01-01'
WINDOW = 2000            # rolling train window
REFIT_EVERY = 63         # quarterly refit

# Sector weights from K1060 T+1 ratios
SECTOR_WEIGHTS = {
    'Tech': 1.60,
    'Financial': 1.29,
    'Traditional': 2.15,
    'Telecom': 0.85,
}

# 0050.TW constituent sector mapping (approximate — only for tickers we use)
# Full 0050 has ~50 constituents; here we use the representative core set
# that matches K1060's stock list. For stocks outside this set, default to 1.0.
TICKER_SECTOR = {
    # Tech
    '2330': 'Tech', '2454': 'Tech', '2317': 'Tech', '2308': 'Tech', '2303': 'Tech',
    '2382': 'Tech', '2357': 'Tech', '3008': 'Tech', '2379': 'Tech', '2409': 'Tech',
    '2376': 'Tech', '2474': 'Tech', '3711': 'Tech', '2353': 'Tech', '2327': 'Tech',
    '3034': 'Tech', '2345': 'Tech', '3231': 'Tech', '2408': 'Tech',
    # Financial
    '2882': 'Financial', '2891': 'Financial', '2881': 'Financial', '2884': 'Financial',
    '2886': 'Financial', '2885': 'Financial', '2892': 'Financial', '2880': 'Financial',
    '5880': 'Financial', '2883': 'Financial', '5876': 'Financial',
    # Traditional (materials/industrial/consumer)
    '2002': 'Traditional', '1301': 'Traditional', '1303': 'Traditional', '1216': 'Traditional',
    '1101': 'Traditional', '1326': 'Traditional', '2207': 'Traditional', '2105': 'Traditional',
    '2912': 'Traditional', '2603': 'Traditional', '2609': 'Traditional', '2615': 'Traditional',
    '9910': 'Traditional', '1102': 'Traditional', '1402': 'Traditional',
    # Telecom
    '2412': 'Telecom', '3045': 'Telecom', '4904': 'Telecom',
}

# Top-50 constituents proxy (the above list captures most 0050 tickers)
TOP50_CODES = set(TICKER_SECTOR.keys())

print("=" * 72)
print(f"{EXPERIMENT_ID}: EAV as Exogenous Regressor in A4f (0050.TW)")
print("  From description (K1060/K1062) to prediction")
print("=" * 72)

# ==========================================================================
# SECTION 1: LOAD EARNINGS ANNOUNCEMENTS
# ==========================================================================
print("\n[1] Loading earnings announcements (Big5)...")

with open(DATA_FILE, 'rb') as f:
    raw_text = f.read().decode('big5', errors='replace')

lines = raw_text.strip().split('\n')
records = []
for line in lines[1:]:
    parts = line.strip().split('\t')
    if len(parts) >= 4:
        code = parts[0].strip()
        name = parts[1].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace('/', '-'))
                records.append({'code': code, 'name': name, 'ym': ym, 'date': dt})
            except Exception:
                pass

ea_df = pd.DataFrame(records)
ea_df = ea_df[(ea_df['date'] >= DATA_START) & (ea_df['date'] <= DATA_END)].copy()
print(f"  Announcements in period: {len(ea_df):,}")
print(f"  Unique companies: {ea_df['code'].nunique():,}")

# ==========================================================================
# SECTION 2: LOAD MARKET DATA (0050.TW + VIX)
# ==========================================================================
print("\n[2] Loading market data...")

raw_tw = yf.download('0050.TW', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw_tw.columns, pd.MultiIndex):
    raw_tw.columns = raw_tw.columns.get_level_values(0)
prices_tw = raw_tw['Close'].copy()

# MANDATORY: clean 0050.TW split artifacts
prices_tw, _ = clean_tw50_data(prices_tw)
log_ret_tw = np.log(prices_tw / prices_tw.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()
vix_ffill = vix_close.reindex(prices_tw.index, method='ffill')

df = pd.DataFrame({
    'price': prices_tw,
    'log_ret': log_ret_tw,
    'VIX': vix_ffill,
}).dropna()

# Drop extreme outliers (split artifacts)
max_abs_ret = df['log_ret'].abs().max()
if max_abs_ret > 0.3:
    print(f"  WARNING: max |return|={max_abs_ret:.4f}, dropping outliers > 0.3")
    df = df[df['log_ret'].abs() <= 0.3]

print(f"  0050.TW: {df.index[0].date()} to {df.index[-1].date()}, n={len(df)}")

# ==========================================================================
# SECTION 3: BUILD EAV SIGNALS (3 weighting schemes)
# ==========================================================================
print("\n[3] Building EAV signals...")

# Build a Series: date -> (equal_count, sector_weighted, top50_count)
trading_days = df.index

eq_count = np.zeros(len(trading_days))
sector_weighted = np.zeros(len(trading_days))
top50_count = np.zeros(len(trading_days))

# For each announcement, map to the trading-day it becomes known at close.
# Taiwan announcements are "post-close" → signal known at the day's close.
# If announcement falls on a non-trading day, attribute to NEXT trading day's signal
# (i.e. the first trading day on which the news is actionable at close).
ea_df_sorted = ea_df.sort_values('date').reset_index(drop=True)

pos_arr = trading_days.searchsorted(ea_df_sorted['date'].values)
# searchsorted default 'left' returns index where date would be inserted;
# if exact match, pos points to that trading day. If not, points to next trading day.
for i in range(len(ea_df_sorted)):
    pos = int(pos_arr[i])
    if pos >= len(trading_days):
        continue
    code = str(ea_df_sorted.iloc[i]['code'])
    eq_count[pos] += 1
    sector = TICKER_SECTOR.get(code)
    if sector:
        sector_weighted[pos] += SECTOR_WEIGHTS[sector]
    else:
        # default weight for unmapped stocks
        sector_weighted[pos] += 1.0
    if code in TOP50_CODES:
        top50_count[pos] += 1

df['eav_eq'] = eq_count
df['eav_sector'] = sector_weighted
df['eav_top50'] = top50_count

# Log-transform (count distributions are heavy-tailed)
df['eav_eq_log'] = np.log1p(df['eav_eq'])
df['eav_sector_log'] = np.log1p(df['eav_sector'])
df['eav_top50_log'] = np.log1p(df['eav_top50'])

print(f"  EAV equal-count:    mean={df['eav_eq'].mean():.3f}, max={df['eav_eq'].max():.0f}, "
      f"nonzero_days={int((df['eav_eq']>0).sum())}")
print(f"  EAV sector-weight:  mean={df['eav_sector'].mean():.3f}, max={df['eav_sector'].max():.2f}")
print(f"  EAV top50-count:    mean={df['eav_top50'].mean():.3f}, max={df['eav_top50'].max():.0f}, "
      f"nonzero_days={int((df['eav_top50']>0).sum())}")

# Event mask for conditional analysis (any announcement by a top-50 constituent = event day)
event_mask_arr = (df['eav_top50'].values > 0)
print(f"  Top-50 event days: {int(event_mask_arr.sum())} / {len(df)} "
      f"({100*event_mask_arr.mean():.1f}%)")

# ==========================================================================
# SECTION 4: DIAGNOSTICS
# ==========================================================================
print("\n[4] Diagnostics...")
ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2

oos_mask = np.array(df.index >= OOS_START)
oos_ret = ret[oos_mask]
n_oos = int(oos_mask.sum())

print(f"  Full sample std (ann): {np.std(ret)*np.sqrt(252):.4f}")
print(f"  OOS mean return (ann): {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std (ann):         {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness:          {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis:          {stats.kurtosis(oos_ret):.3f}")
print(f"  VIX mean:              {np.mean(vix):.2f}")

# Correlation check: raw r² vs EAV signals on training portion
is_mask = ~oos_mask
corr_eq = float(np.corrcoef(r2[is_mask], df['eav_eq_log'].values[is_mask])[0, 1])
corr_sec = float(np.corrcoef(r2[is_mask], df['eav_sector_log'].values[is_mask])[0, 1])
corr_t50 = float(np.corrcoef(r2[is_mask], df['eav_top50_log'].values[is_mask])[0, 1])
print(f"  In-sample corr(r², EAV_eq_log):     {corr_eq:+.4f}")
print(f"  In-sample corr(r², EAV_sector_log): {corr_sec:+.4f}")
print(f"  In-sample corr(r², EAV_top50_log):  {corr_t50:+.4f}")

# ==========================================================================
# SECTION 5: MODEL IMPLEMENTATIONS
# ==========================================================================
print("\n[5] Model implementations (A4f and A4f-EAV)...")


@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])
    return -ll


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
    """A4f + EAV: τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε). 7 params.

    Info-set: both VIX_{t-1} and EAV_{t-1} are known at time t-1 close →
    τ_t is a legitimate t-1-measurable prediction of t's variance.
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
    # θ₂ initial scale: expected vol contribution ~ var0 * 0.05 / eav_mean
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
        (-1e-2, 1e-2),         # θ₂ (EAV)  — allow both signs; H2: θ₂>0
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
    return max(theta0 + theta1 * vix_lag_val ** 2, 1e-16) if np.isscalar(vix_lag_val) \
        else np.maximum(theta0 + theta1 * vix_lag_val ** 2, 1e-16)


def compute_tau_a4f_eav(theta0, theta1, theta2, vix_lag_val, eav_lag_val):
    val = theta0 + theta1 * vix_lag_val ** 2 + theta2 * eav_lag_val
    return max(val, 1e-16) if np.isscalar(val) else np.maximum(val, 1e-16)


# ==========================================================================
# SECTION 6: OUT-OF-SAMPLE FORECASTING (A4f vs A4f-EAV for each variant)
# ==========================================================================
print("\n[6] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}, refit every {REFIT_EVERY} days")

# Variants to test
EAV_VARIANTS = {
    'equal': 'eav_eq_log',
    'sector': 'eav_sector_log',
    'top50': 'eav_top50_log',
}

# Storage
models_to_run = ['A4f'] + [f'A4f_EAV_{v}' for v in EAV_VARIANTS]
forecasts = {m: np.full(n_oos_actual, np.nan) for m in models_to_run}

a4f_param_history = []
a4f_eav_param_history = {v: [] for v in EAV_VARIANTS}

# Baseline A4f state
state_a4f = {'params': None, 'g': None}
# A4f-EAV state per variant
state_eav = {v: {'params': None, 'g': None} for v in EAV_VARIANTS}

refit_count = 0

# Pre-extract EAV columns
eav_arrays = {v: df[col].values for v, col in EAV_VARIANTS.items()}

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
            # Initialize g via training
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

        # Fit A4f-EAV for each variant
        for v, col in EAV_VARIANTS.items():
            train_eav = eav_arrays[v][train_start:abs_idx]
            params, ll = fit_a4f_eav(train_ret, train_vix, train_eav)
            if params is not None:
                state_eav[v]['params'] = params
                theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = params
                a4f_eav_param_history[v].append({
                    'refit': refit_count,
                    'date': str(df.index[abs_idx].date()),
                    'theta0': float(theta0),
                    'theta1': float(theta1_val),
                    'theta2': float(theta2_val),
                    'omega_g': float(omega_g),
                    'alpha': float(alpha_p),
                    'gamma': float(gamma_p),
                    'beta': float(beta_p),
                    'loglik': float(-ll),
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
                state_eav[v]['g'] = g

    # --- Generate forecast for abs_idx (day t+1 in forecast convention) ---
    # We use predetermined lagged VIX and EAV → no lookahead.
    v_lag = vix[abs_idx - 1]

    # A4f baseline
    p = state_a4f['params']
    if p is not None:
        theta0, theta1_val, omega_g, alpha_p, gamma_p, beta_p = p
        tau_t = compute_tau_a4f(theta0, theta1_val, v_lag)
        r_prev = ret[abs_idx - 1]
        g_prev = state_a4f['g']
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g_prev, 1e-10)
        forecasts['A4f'][t_idx] = tau_t * g_new
        state_a4f['g'] = g_new

    # A4f-EAV for each variant
    for v in EAV_VARIANTS:
        p = state_eav[v]['params']
        if p is None:
            continue
        theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = p
        eav_lag_val = eav_arrays[v][abs_idx - 1]
        tau_t = compute_tau_a4f_eav(theta0, theta1_val, theta2_val, v_lag, eav_lag_val)
        r_prev = ret[abs_idx - 1]
        g_prev = state_eav[v]['g']
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g_prev, 1e-10)
        forecasts[f'A4f_EAV_{v}'][t_idx] = tau_t * g_new
        state_eav[v]['g'] = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting complete: {refit_count} refits in {elapsed:.0f}s")

# ==========================================================================
# SECTION 7: EVALUATION
# ==========================================================================
print("\n[7] Evaluation...")

oos_r2 = r2[oos_mask]
oos_dates = df.index[oos_mask]
event_mask_oos = event_mask_arr[oos_mask]

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'TW_EAV_factor as Exogenous Regressor in A4f — From Description to Prediction',
    'proposer': '賴奕豪',
    'executor': 'Claude',
    'asset': '0050.TW',
    'external_regressors': ['US_VIX', 'TW_EAV_factor'],
    'data_source': 'yfinance + 財報公告日.txt',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(len(df)),
    'n_oos': int(n_oos_actual),
    'oos_start': OOS_START,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'n_event_days_oos': int(event_mask_oos.sum()),
    'eav_variants': list(EAV_VARIANTS.keys()),
    'in_sample_corr': {
        'eav_eq_log': corr_eq,
        'eav_sector_log': corr_sec,
        'eav_top50_log': corr_t50,
    },
    'models': {},
    'dm_tests': {},
    'theta2_distribution': {},
    'event_window_analysis': {},
    'regime_analysis': {},
    'diagnostics': {
        'oos_mean_return_ann': float(np.mean(oos_ret) * 252),
        'oos_std_ann': float(np.std(oos_ret) * np.sqrt(252)),
        'oos_skewness': float(stats.skew(oos_ret)),
        'oos_kurtosis': float(stats.kurtosis(oos_ret)),
        'vix_mean_full': float(np.mean(vix)),
    },
}

# Model-level metrics
for name in models_to_run:
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
    print(f"  {name:20s}: QLIKE={qlike_val:.6f}, Spearman={rho:+.4f}, n={n_valid}")

# DM tests — each A4f-EAV variant vs A4f baseline
print("\n  DM tests vs A4f baseline (neg t-stat → EAV variant better):")
a4f_fc = forecasts['A4f']
for v in EAV_VARIANTS:
    name = f'A4f_EAV_{v}'
    fc = forecasts[name]
    valid = np.isfinite(a4f_fc) & np.isfinite(fc) & np.isfinite(oos_r2)
    if valid.sum() < 100:
        continue

    loss_a4f = qlike_pointwise(oos_r2[valid], a4f_fc[valid])
    loss_eav = qlike_pointwise(oos_r2[valid], fc[valid])
    dm_t, dm_p = dm_test(loss_eav, loss_a4f)
    direction = 'EAV_better' if dm_t < 0 else 'A4f_better'
    significant = abs(dm_t) > 3.0

    mean_loss_a4f = float(np.mean(loss_a4f))
    mean_loss_eav = float(np.mean(loss_eav))
    improvement_pct = (mean_loss_a4f - mean_loss_eav) / mean_loss_a4f * 100 \
        if mean_loss_a4f != 0 else 0.0

    results['dm_tests'][f'{name}_vs_A4f'] = {
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'significant_harvey': bool(significant),
        'direction': direction,
        'n_compared': int(valid.sum()),
        'mean_qlike_loss_a4f': mean_loss_a4f,
        'mean_qlike_loss_eav': mean_loss_eav,
        'qlike_improvement_pct': float(improvement_pct),
    }
    print(f"    {name:20s} vs A4f: t={dm_t:+.3f}, p={dm_p:.4f}, "
          f"improve={improvement_pct:+.3f}%, sig(|t|>3)={significant}, dir={direction}")

# ==========================================================================
# SECTION 8: θ₂ DISTRIBUTION ACROSS REFITS (H2)
# ==========================================================================
print("\n[8] θ₂ distribution across refits...")

for v in EAV_VARIANTS:
    hist = a4f_eav_param_history[v]
    if not hist:
        continue
    theta2_arr = np.array([h['theta2'] for h in hist])
    n = len(theta2_arr)
    if n < 2:
        continue
    theta2_mean = float(theta2_arr.mean())
    theta2_std = float(theta2_arr.std(ddof=1))
    theta2_median = float(np.median(theta2_arr))
    positive_frac = float((theta2_arr > 0).mean())
    # one-sample t-test: θ₂ > 0?
    t_one, p_one = stats.ttest_1samp(theta2_arr, popmean=0.0, alternative='greater')
    # Bootstrap 95% CI
    rng = np.random.default_rng(42)
    boots = []
    for _ in range(2000):
        sample = rng.choice(theta2_arr, size=n, replace=True)
        boots.append(float(sample.mean()))
    ci_low = float(np.percentile(boots, 2.5))
    ci_high = float(np.percentile(boots, 97.5))

    results['theta2_distribution'][v] = {
        'n_refits': n,
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
    print(f"  [{v:7s}] θ₂ mean={theta2_mean:+.6e}, std={theta2_std:.3e}, "
          f"median={theta2_median:+.3e}, pos_frac={positive_frac:.2f}, "
          f"t(θ₂>0)={t_one:+.2f}, p={p_one:.4f}, CI95=[{ci_low:.3e}, {ci_high:.3e}]")

# ==========================================================================
# SECTION 9: EVENT vs NON-EVENT CONDITIONAL ANALYSIS (H3)
# ==========================================================================
print("\n[9] Event vs non-event conditional DM...")

# For each EAV variant, compute DM in event-day subsample and non-event subsample
for v in EAV_VARIANTS:
    name = f'A4f_EAV_{v}'
    fc = forecasts[name]
    valid = np.isfinite(a4f_fc) & np.isfinite(fc) & np.isfinite(oos_r2)

    event_sub = valid & event_mask_oos
    nonevent_sub = valid & (~event_mask_oos)

    r2_ev = oos_r2[event_sub]
    a4f_ev = a4f_fc[event_sub]
    eav_ev = fc[event_sub]

    r2_ne = oos_r2[nonevent_sub]
    a4f_ne = a4f_fc[nonevent_sub]
    eav_ne = fc[nonevent_sub]

    event_block = {'n_event_days': int(event_sub.sum()),
                   'n_nonevent_days': int(nonevent_sub.sum())}

    if event_sub.sum() > 30:
        loss_a4f_ev = qlike_pointwise(r2_ev, a4f_ev)
        loss_eav_ev = qlike_pointwise(r2_ev, eav_ev)
        dm_t_ev, dm_p_ev = dm_test(loss_eav_ev, loss_a4f_ev)
        qlike_a4f_ev = float(qlike(r2_ev, a4f_ev))
        qlike_eav_ev = float(qlike(r2_ev, eav_ev))
        event_block['event'] = {
            'dm_t': float(dm_t_ev),
            'dm_p': float(dm_p_ev),
            'qlike_a4f': qlike_a4f_ev,
            'qlike_eav': qlike_eav_ev,
            'improvement_pct': float((qlike_a4f_ev - qlike_eav_ev) / abs(qlike_a4f_ev) * 100),
        }
    else:
        event_block['event'] = None

    if nonevent_sub.sum() > 30:
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
            'improvement_pct': float((qlike_a4f_ne - qlike_eav_ne) / abs(qlike_a4f_ne) * 100),
        }
    else:
        event_block['nonevent'] = None

    results['event_window_analysis'][v] = event_block

    ev_t = event_block.get('event', {})
    ne_t = event_block.get('nonevent', {})
    if ev_t and ne_t:
        print(f"  [{v:7s}] event: n={event_block['n_event_days']}, DM t={ev_t['dm_t']:+.3f}, "
              f"improve={ev_t['improvement_pct']:+.3f}% | nonevent: n={event_block['n_nonevent_days']}, "
              f"DM t={ne_t['dm_t']:+.3f}, improve={ne_t['improvement_pct']:+.3f}%")

# ==========================================================================
# SECTION 10: ROBUSTNESS — LAG SENSITIVITY
# ==========================================================================
print("\n[10] Robustness: EAV lag sensitivity (t-1 vs t-2 vs rolling-5)...")

# For best variant (sector), refit using EAV_{t-2} and rolling 5-day EAV_{t-1..t-5}
# Use in-sample full period for quick refit (not OOS) as a robustness sanity check.
robustness = {}

def fit_and_score_full_sample(eav_series, label):
    """Fit A4f-EAV on full sample, compute in-sample QLIKE and θ₂."""
    full_params, full_ll = fit_a4f_eav(ret, vix, eav_series)
    if full_params is None:
        return None
    theta0, theta1_val, theta2_val, omega_g, alpha_p, gamma_p, beta_p = full_params
    # Compute in-sample σ²
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

sector_eav = df['eav_sector_log'].values
# (a) EAV_{t-1} (already the default in main)
rb_default = fit_and_score_full_sample(sector_eav, 'EAV_t-1 (default)')
# (b) EAV_{t-2}: shift by extra 1 day
sector_eav_t2 = np.empty_like(sector_eav)
sector_eav_t2[0] = sector_eav[0]
sector_eav_t2[1:] = sector_eav[:-1]  # this creates an extra lag relative to default
rb_t2 = fit_and_score_full_sample(sector_eav_t2, 'EAV_t-2')
# (c) rolling 5-day sum of EAV_{t-1..t-5}
sector_eav_roll5 = pd.Series(sector_eav, index=df.index).rolling(5, min_periods=1).sum().values
rb_roll5 = fit_and_score_full_sample(sector_eav_roll5, 'EAV rolling-5d')

robustness['lag_sensitivity'] = [rb_default, rb_t2, rb_roll5]
results['robustness'] = robustness
print(f"  EAV_t-1 default: θ₂={rb_default['theta2']:+.3e}, IS QLIKE={rb_default['in_sample_qlike']:.6f}")
print(f"  EAV_t-2:         θ₂={rb_t2['theta2']:+.3e}, IS QLIKE={rb_t2['in_sample_qlike']:.6f}")
print(f"  EAV rolling-5d:  θ₂={rb_roll5['theta2']:+.3e}, IS QLIKE={rb_roll5['in_sample_qlike']:.6f}")

# ==========================================================================
# SECTION 11: SAVE RESULTS
# ==========================================================================
print("\n[11] Saving results...")

results['parameter_history'] = {
    'a4f': a4f_param_history,
    'a4f_eav_equal': a4f_eav_param_history['equal'],
    'a4f_eav_sector': a4f_eav_param_history['sector'],
    'a4f_eav_top50': a4f_eav_param_history['top50'],
}
results['metadata'] = {
    'script': 'k1064.py',
    'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(time.time() - START_TIME, 1),
    'random_seed': 42,
    'references': [
        'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256',
        'Harvey et al. (2016). DM t > 3.0 threshold',
        'Patell & Wolfson (1984). Earnings announcement vol. JAR',
        'K1058: A4f on 0050.TW baseline',
        'K1059: A4f vs GJR event-window amplification',
        'K1060: Individual TW stock EAV T+1=1.466',
        'K1062: 0050.TW ETF T+1=1.132',
    ],
}

with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"  Results saved to {RESULTS_PATH}")

# ==========================================================================
# SECTION 12: CHARTS
# ==========================================================================
print("\n[12] Generating charts...")
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402

plt.rcParams.update({'figure.dpi': 120, 'savefig.dpi': 120})

# --- Chart 1: DM comparison (A4f vs each A4f-EAV variant) ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: QLIKE bar
ax = axes[0]
m_names = [m for m in models_to_run if m in results['models']]
qvals = [results['models'][m]['qlike'] for m in m_names]
colors_map = {'A4f': '#3498db',
              'A4f_EAV_equal': '#e67e22',
              'A4f_EAV_sector': '#e74c3c',
              'A4f_EAV_top50': '#9b59b6'}
bar_colors = [colors_map.get(m, 'gray') for m in m_names]
bars = ax.barh(m_names, qvals, color=bar_colors, edgecolor='white', height=0.55)
ax.set_xlabel('QLIKE (lower = better)')
ax.set_title(f'QLIKE on r² — 0050.TW OOS ({OOS_START}+)')
for bar, val in zip(bars, qvals):
    ax.text(bar.get_width() + abs(bar.get_width())*0.002, bar.get_y() + bar.get_height() / 2,
            f'{val:.5f}', va='center', fontsize=9)

# Right: DM t-stats
ax = axes[1]
dm_labels, dm_vals = [], []
for v in EAV_VARIANTS:
    key = f'A4f_EAV_{v}_vs_A4f'
    if key in results['dm_tests']:
        dm_labels.append(f'A4f_EAV_{v}\nvs A4f')
        dm_vals.append(results['dm_tests'][key]['dm_t'])
dm_colors = ['#27ae60' if abs(v) > 3.0 else '#e67e22' if abs(v) > 1.96 else '#95a5a6'
             for v in dm_vals]
bars = ax.barh(dm_labels, dm_vals, color=dm_colors, height=0.4, edgecolor='black')
ax.axvline(x=-3.0, color='red', linestyle='--', alpha=0.7, label='Harvey |t|=3.0')
ax.axvline(x=3.0, color='red', linestyle='--', alpha=0.7)
ax.axvline(x=-1.96, color='gray', linestyle=':', alpha=0.5, label='Std |t|=1.96')
ax.axvline(x=1.96, color='gray', linestyle=':', alpha=0.5)
ax.axvline(x=0, color='gray', linestyle='-', alpha=0.3)
ax.set_xlabel('DM t-statistic (negative = EAV variant better)')
ax.set_title('DM Test: A4f-EAV vs A4f baseline')
for bar, v in zip(bars, dm_vals):
    ax.text(bar.get_width() + 0.05 if bar.get_width() > 0 else bar.get_width() - 0.05,
            bar.get_y() + bar.get_height() / 2,
            f'{v:+.2f}', va='center', fontsize=9,
            ha='left' if bar.get_width() > 0 else 'right')
ax.legend(loc='best', fontsize=8)

plt.tight_layout()
chart1_path = SCRIPT_DIR / 'k1064_dm_comparison.png'
plt.savefig(chart1_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart1_path}")

# --- Chart 2: θ₂ distribution across refits ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: θ₂ time series for each variant
ax = axes[0]
for v in EAV_VARIANTS:
    hist = a4f_eav_param_history[v]
    if not hist:
        continue
    theta2_ts = [h['theta2'] for h in hist]
    ax.plot(range(len(theta2_ts)), theta2_ts, marker='o',
            color=colors_map[f'A4f_EAV_{v}'], label=v, linewidth=1.3, markersize=4)
ax.axhline(y=0, color='black', linestyle='-', alpha=0.4)
ax.set_xlabel('Refit #')
ax.set_ylabel(r'$\theta_2$ (EAV loading)')
ax.set_title(r'$\theta_2$ Evolution Across Refits')
ax.legend()
ax.grid(True, alpha=0.3)

# Right: θ₂ distribution histogram + CI95
ax = axes[1]
labels = []
means = []
ci_lows = []
ci_highs = []
for v in EAV_VARIANTS:
    if v in results['theta2_distribution']:
        labels.append(v)
        stats_v = results['theta2_distribution'][v]
        means.append(stats_v['mean'])
        ci_lows.append(stats_v['bootstrap_ci_95'][0])
        ci_highs.append(stats_v['bootstrap_ci_95'][1])
if labels:
    xpos = np.arange(len(labels))
    err_low = [m - lo for m, lo in zip(means, ci_lows)]
    err_high = [hi - m for m, hi in zip(means, ci_highs)]
    bar_colors_v = [colors_map[f'A4f_EAV_{v}'] for v in labels]
    ax.bar(xpos, means, yerr=[err_low, err_high], color=bar_colors_v,
           edgecolor='black', capsize=6, alpha=0.85)
    ax.axhline(y=0, color='red', linestyle='--', alpha=0.5, label=r'$\theta_2=0$')
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels)
    ax.set_ylabel(r'$\theta_2$ (mean ± 95% bootstrap CI)')
    ax.set_title(r'$\theta_2$ Point Estimate + 95% CI')
    for i, m in enumerate(means):
        ax.text(i, m + max(err_high) * 0.15, f'{m:+.2e}', ha='center', fontsize=8)
    ax.legend()

plt.tight_layout()
chart2_path = SCRIPT_DIR / 'k1064_theta2_distribution.png'
plt.savefig(chart2_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart2_path}")

# --- Chart 3: Event vs non-event conditional performance ---
fig, ax = plt.subplots(figsize=(11, 5))
x_labels = []
event_impr = []
nonevent_impr = []
event_t = []
nonevent_t = []
for v in EAV_VARIANTS:
    if v in results['event_window_analysis']:
        blk = results['event_window_analysis'][v]
        if blk.get('event') and blk.get('nonevent'):
            x_labels.append(v)
            event_impr.append(blk['event']['improvement_pct'])
            nonevent_impr.append(blk['nonevent']['improvement_pct'])
            event_t.append(blk['event']['dm_t'])
            nonevent_t.append(blk['nonevent']['dm_t'])

if x_labels:
    xpos = np.arange(len(x_labels))
    width = 0.35
    bars1 = ax.bar(xpos - width/2, event_impr, width, color='#e74c3c',
                   edgecolor='black', label='Event days')
    bars2 = ax.bar(xpos + width/2, nonevent_impr, width, color='#3498db',
                   edgecolor='black', label='Non-event days')
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.4)
    ax.set_xticks(xpos)
    ax.set_xticklabels(x_labels)
    ax.set_ylabel('QLIKE improvement vs A4f (%)')
    ax.set_title('A4f-EAV advantage: Event vs Non-event days (0050.TW OOS)')
    for i, (b1, b2, t1, t2) in enumerate(zip(bars1, bars2, event_t, nonevent_t)):
        ax.text(b1.get_x() + b1.get_width()/2, b1.get_height() + 0.02,
                f't={t1:+.2f}', ha='center', fontsize=8)
        ax.text(b2.get_x() + b2.get_width()/2, b2.get_height() + 0.02,
                f't={t2:+.2f}', ha='center', fontsize=8)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
chart3_path = SCRIPT_DIR / 'k1064_event_window_analysis.png'
plt.savefig(chart3_path, bbox_inches='tight')
plt.close()
print(f"  saved {chart3_path}")

# ==========================================================================
# SECTION 13: SUMMARY
# ==========================================================================
print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)
for v in EAV_VARIANTS:
    key = f'A4f_EAV_{v}_vs_A4f'
    if key in results['dm_tests']:
        d = results['dm_tests'][key]
        print(f"  A4f_EAV_{v:7s} vs A4f: DM t={d['dm_t']:+.3f}, "
              f"improve={d['qlike_improvement_pct']:+.3f}%, "
              f"Harvey(|t|>3)={'PASS' if d['significant_harvey'] else 'FAIL'}")

print("\n  θ₂ H2 test (θ₂ > 0 one-sided t-test across refits):")
for v in EAV_VARIANTS:
    if v in results['theta2_distribution']:
        d = results['theta2_distribution'][v]
        print(f"    [{v:7s}] mean={d['mean']:+.3e}, t={d['one_sample_t_vs_zero']:+.2f}, "
              f"p={d['one_sample_p_one_sided']:.4f}, pos_frac={d['positive_fraction']:.2f}")

print(f"\n  Runtime: {time.time() - START_TIME:.1f}s")
print("=" * 72)
print("DONE")
