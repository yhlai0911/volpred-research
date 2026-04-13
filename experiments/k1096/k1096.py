#!/usr/bin/env python3
"""
K1096: BTC Regime-Switching A4f — Can State-Dependent VIX Loading Rescue Crypto?
=================================================================================
[提出: 用戶 (via K1096 brief), 執行: Claude]

Motivation:
  K1089 tested A4f-VIX on BTC and found:
    - Full OOS DM t = +1.13 (NS)
    - High-VIX bucket [25,40): DM t = -2.91 (WRONG DIRECTION, i.e. A4f-VIX
      HURTS BTC vol forecasting in high-VIX regimes)
  This is consistent with K1025 (Paper 6): BTC-equity fear contagion is
  asymmetric — crypto DECOUPLES during equity stress (large corr swings).

  If the damage is concentrated in high-VIX state, can a REGIME-SWITCHING
  rule "turn off" the VIX regressor when it actively hurts?

Hypotheses:
  H1: A4f-Regime (VIX loading turned OFF when VIX >= 25) improves full-OOS
      vs pure GJR (Harvey |t|>3)?
  H2: A4f-Regime (VIX loading turned ON only when |corr(BTC,SPY)| > 0.3)
      improves vs pure GJR?
  H3: A4f-Adaptive (smooth weighting by |corr|) improves vs pure GJR?
  H4: Best regime model improves vs pure A4f-VIX (K1089 baseline)?
  H5: High-VIX bucket damage disappears under regime switching?

Design:
  We reuse the K1089 4 baseline models and ADD 3 regime-switching variants:
    M1: GJR-GARCH(1,1) (K1089 baseline)
    M2: A4f-VIX (full, no regime — K1089 NS)
    M3: A4f-Regime-VIX-Off-HighVIX   : tau = theta0 + theta1 * VIX² * 1(VIX<25)
    M4: A4f-Regime-VIX-On-HighCorr  : tau = theta0 + theta1 * VIX² * 1(|corr|>0.3)
    M5: A4f-Adaptive                : tau = theta0 + theta1 * VIX² * max(|corr|,0)

  Rolling-window GARCH, 1000-day train, 63-day refit.
  Correlation: rolling 60-day Pearson corr of (BTC log ret, SPY log ret).
  VIX and SPY forward-filled onto BTC's 24/7 calendar.
  Three OOS windows (matching K1089): Early 2018-bear / Middle COVID-Luna
  / Late FTX-Rally.

  Regime indicators are constructed from LAGGED information (t-1) so
  there is no lookahead. Specifically:
    - VIX_threshold_indicator[t]   = 1(VIX[t-1] < 25)
    - corr_indicator[t]            = 1(|corr60d up to t-1| > 0.3)
    - adaptive_weight[t]           = max(|corr60d up to t-1|, 0)

  Random seed 42.

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test with Newey-West HAC (Harvey 2016, |t|>3.0)
  - Spearman rank correlation
  - Bootstrap CI (1000 reps, block bootstrap, seed 42)
  - VIX bucket analysis: does High-VIX damage disappear under regimes?
  - Theta1 evolution across refits

References:
  - K1089: BTC A4f-VIX baseline (NS, high-VIX wrong direction)
  - K1025 (Paper 6): Crypto fear channel asymmetry
  - Baur & Dimpfl (2018). Asymmetric volatility in cryptocurrencies. EL.
  - Bollerslev, Patton & Quaedvlieg (2016). Exploiting the errors: A simple
    approach for improved volatility forecasting. JoE 192:1-18.
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS origin.
  - Hamilton (1989). Regime-switching. Econometrica.
  - Patton (2011). Volatility forecast comparison. JoE 160:246-256.
  - Harvey, Leybourne & Newbold (2016). MSE equality testing.

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1096
Upstream: K1089 (BTC A4f NS with high-VIX wrong direction)
          K1025/Paper 6 (crypto fear asymmetry)
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
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1096"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1096_results.json')

# Configuration (aligned with K1089 for direct comparability)
DATA_START = '2014-09-01'
DATA_END = '2026-04-12'
WINDOW = 1000
REFIT_EVERY = 63
CORR_WINDOW = 60            # rolling correlation window (days)
VIX_THRESHOLD = 25.0        # "high VIX" cutoff from K1089 bucket analysis
CORR_THRESHOLD = 0.30       # "high correlation" cutoff

OOS_WINDOWS = [
    ('Early_2018Bear', '2018-01-01', '2020-02-14'),
    ('Middle_COVID_Luna', '2020-02-15', '2022-10-31'),
    ('Late_FTX_Rally', '2022-11-01', '2026-04-11'),
]

VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

CORR_BUCKETS = [
    ('NegCorr', -1.0, -0.1),
    ('Decoupled', -0.1, 0.1),
    ('LowPosCorr', 0.1, 0.3),
    ('HighPosCorr', 0.3, 1.0),
]

print("=" * 72)
print(f"{EXPERIMENT_ID}: BTC Regime-Switching A4f — rescue attempt")
print(f"  5 models (GJR, A4f-VIX, A4f-Reg-HighVIXOff, A4f-Reg-HighCorrOn, A4f-Adaptive)")
print(f"  3 OOS windows, VIX & correlation bucket analysis")
print(f"  Corr window = {CORR_WINDOW}d, VIX threshold = {VIX_THRESHOLD}, "
      f"|corr| threshold = {CORR_THRESHOLD}")
print("=" * 72)

# ============================================================
# SECTION 1: DATA LOADING — BTC, SPY, VIX
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

btc_raw = yf.download('BTC-USD', start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=False)
if isinstance(btc_raw.columns, pd.MultiIndex):
    btc_raw.columns = btc_raw.columns.get_level_values(0)
btc_price = btc_raw['Close'].copy()
btc_ret = np.log(btc_price / btc_price.shift(1))

spy_raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
spy_price = spy_raw['Close'].copy()
spy_ret = np.log(spy_price / spy_price.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# Build DataFrame on BTC's 24/7 calendar
df = pd.DataFrame({'price': btc_price, 'log_ret': btc_ret})
df = df.dropna()

# SPY return forward-filled (SPY does not trade weekends; BTC does). For a
# weekend day, the most recent known SPY return is Friday's. When computing
# rolling 60-day correlation we use forward-filled SPY returns aligned to
# BTC calendar (this is standard practice: use the most recent SPY info
# available as of day t).
spy_ret_aligned = spy_ret.reindex(df.index).ffill()
df['spy_ret'] = spy_ret_aligned

# VIX forward-filled onto BTC calendar
vix_aligned = vix_close.reindex(df.index).ffill()
df['VIX'] = vix_aligned

df = df.dropna(subset=['VIX', 'spy_ret'])
df = df.iloc[1:]  # drop the first row (NaN BTC return)

# Rolling 60-day correlation of BTC return and SPY return.
# This uses returns through t, producing corr[t]. We will LAG this by 1 day
# before using it as a regime indicator (so forecasts only use past info).
df['corr60d'] = df['log_ret'].rolling(CORR_WINDOW).corr(df['spy_ret'])

# Drop rows where corr is not yet defined
df = df.dropna(subset=['corr60d'])

n_total = len(df)
print(f"  Aligned data: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  (24/7 BTC calendar with forward-filled SPY return and VIX)")

ret = df['log_ret'].values
vix = df['VIX'].values
spy = df['spy_ret'].values
corr60 = df['corr60d'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
print(f"  BTC return:  mean(ann)={np.mean(ret)*365:.4f}, "
      f"std(ann)={np.std(ret)*np.sqrt(365):.4f}, "
      f"skew={stats.skew(ret):.3f}, kurt={stats.kurtosis(ret):.3f}")
print(f"  SPY return:  mean(ann)={np.mean(spy)*252:.4f}, "
      f"std(ann)={np.std(spy)*np.sqrt(252):.4f}")
print(f"  VIX:  mean={np.mean(vix):.2f}, max={np.max(vix):.2f}")
print(f"  corr60d: mean={np.mean(corr60):.3f}, std={np.std(corr60):.3f}, "
      f"min={np.min(corr60):.3f}, max={np.max(corr60):.3f}")

# Decompose corr60d into regimes
corr_abs = np.abs(corr60)
print(f"  |corr60d| > {CORR_THRESHOLD}: "
      f"{(corr_abs > CORR_THRESHOLD).sum()} / {len(corr60)} "
      f"({100*(corr_abs > CORR_THRESHOLD).mean():.1f}%)")
print(f"  VIX > {VIX_THRESHOLD}: "
      f"{(vix > VIX_THRESHOLD).sum()} / {len(vix)} "
      f"({100*(vix > VIX_THRESHOLD).mean():.1f}%)")

for name, start, end in OOS_WINDOWS:
    mask = (dates >= start) & (dates <= end)
    n_w = mask.sum()
    print(f"  {name} ({start} to {end}): n={n_w}, VIX max={np.max(vix[mask]):.1f}, "
          f"corr mean={np.mean(corr60[mask]):.3f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) benchmark ---
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
    converged = False
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
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f-VIX (full, no regime — K1089 baseline) ---
# tau[t] = theta0 + theta1 * VIX[t-1]²
def fit_a4f_vix(returns, vix_vals):
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix_sq = vix_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_sq, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
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
    vix_sq_mean = np.mean(vix_sq) + 1e-8
    starts = [
        [var0 * 0.1,  var0 / vix_sq_mean,       0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix_sq_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / vix_sq_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-1, 1e-1), (1e-12, 1.0), (1e-6, 1.0),
              (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


# --- A4f-Regime-Weighted ---
# tau[t] = theta0 + theta1 * VIX[t-1]² * w[t]
#   where w[t] is a prebuilt weight series (pulled through the MIDAS tau term)
# This general specification covers M3/M4/M5 by passing different w series.
def fit_a4f_regime(returns, vix_vals, weights):
    """
    Fit A4f with a LAGGED, prebuilt regime weight series.
    weights should be aligned so that weights[t] uses only past information
    (already lagged by caller).
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix_sq = vix_lag ** 2

    # weights is already aligned to day t (uses only info up to t-1)
    w = np.asarray(weights, dtype=float)
    assert len(w) == n, f"weights length {len(w)} != n {n}"

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_sq * w, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
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
    # Scale initial theta1 by mean of effective (vix²*w) not just vix²
    eff_mean = np.mean(vix_sq * w) + 1e-8
    starts = [
        [var0 * 0.1,  var0 / eff_mean,       0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / eff_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / eff_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-1, 1e-1), (1e-12, 10.0), (1e-6, 1.0),
              (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def init_a4f_state(train_ret, vix_vals, params, weights=None):
    """Run the filter on the training set to produce final g[T] state."""
    theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params
    n = len(vix_vals)
    vix_lag = np.empty(n); vix_lag[0] = vix_vals[0]; vix_lag[1:] = vix_vals[:-1]
    vix_sq = vix_lag ** 2
    if weights is None:
        tau = np.maximum(theta0 + theta1 * vix_sq, 1e-16)
    else:
        w = np.asarray(weights, dtype=float)
        tau = np.maximum(theta0 + theta1 * vix_sq * w, 1e-16)

    persist = alpha_p + gamma_p / 2.0 + beta_p
    g = omega_g / (1.0 - persist)
    for i in range(1, len(train_ret)):
        u_prev = train_ret[i-1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
        g = max(g, 1e-10)
    return g


# ============================================================
# SECTION 4: BUILD REGIME INDICATORS (LAGGED)
# ============================================================
# All regime indicators use LAGGED info only.
# For day t's forecast we use info up to t-1.
# So indicator[t] is built from vix[t-1], corr60[t-1].

vix_lag_series = np.empty(n_total)
vix_lag_series[0] = vix[0]
vix_lag_series[1:] = vix[:-1]

corr_lag_series = np.empty(n_total)
corr_lag_series[0] = corr60[0]
corr_lag_series[1:] = corr60[:-1]

# M3: VIX loading OFF when VIX_{t-1} >= threshold
#     i.e. weight = 1 if VIX_{t-1} < 25 else 0
w_vix_off = (vix_lag_series < VIX_THRESHOLD).astype(float)

# M4: VIX loading ON only when |corr_{t-1}| > threshold
w_corr_on = (np.abs(corr_lag_series) > CORR_THRESHOLD).astype(float)

# M5: Adaptive smooth weighting by |corr_{t-1}| (clipped to [0,1])
w_adaptive = np.clip(np.abs(corr_lag_series), 0.0, 1.0)

print(f"\n[3b] Regime indicators (full sample, lagged):")
print(f"  M3 weight (VIX<{VIX_THRESHOLD}): mean={w_vix_off.mean():.3f}, "
      f"active days = {int(w_vix_off.sum())}")
print(f"  M4 weight (|corr|>{CORR_THRESHOLD}): mean={w_corr_on.mean():.3f}, "
      f"active days = {int(w_corr_on.sum())}")
print(f"  M5 weight (|corr|): mean={w_adaptive.mean():.3f}, "
      f"nonzero days = {int((w_adaptive>0.01).sum())}")

# ============================================================
# SECTION 5: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[5] Out-of-sample forecasting (3 windows, 5 models)...")

oos_full_mask = np.zeros(n_total, dtype=bool)
window_tags = np.empty(n_total, dtype=object)
for name, start, end in OOS_WINDOWS:
    m = (dates >= start) & (dates <= end)
    oos_full_mask |= m
    for idx in np.where(m)[0]:
        window_tags[idx] = name

oos_indices = np.where(oos_full_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  Total OOS observations (union): {n_oos_actual}")

# Forecast arrays (M1..M5)
fc_gjr = np.full(n_oos_actual, np.nan)
fc_vix = np.full(n_oos_actual, np.nan)
fc_reg_voff = np.full(n_oos_actual, np.nan)
fc_reg_corron = np.full(n_oos_actual, np.nan)
fc_adaptive = np.full(n_oos_actual, np.nan)

refit_log = []

# States
gjr_h = None; gjr_params = None
vix_g = None; vix_params = None
voff_g = None; voff_params = None
corron_g = None; corron_params = None
adap_g = None; adap_params = None

prev_window = None
refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    current_window = window_tags[abs_idx]

    if t_idx == 0 or current_window != prev_window:
        need_refit = True
    else:
        window_start = next(s for n, s, e in OOS_WINDOWS if n == current_window)
        window_start_idx = np.where(dates >= window_start)[0][0]
        days_in_window = abs_idx - window_start_idx
        need_refit = (days_in_window % REFIT_EVERY == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]
        train_w_voff = w_vix_off[train_start:abs_idx]
        train_w_corron = w_corr_on[train_start:abs_idx]
        train_w_adap = w_adaptive[train_start:abs_idx]

        # M1: GJR
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_params = gjr_p
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h
        else:
            gjr_conv = False

        # M2: A4f-VIX
        vix_p, vix_conv = fit_a4f_vix(train_ret, train_vix)
        if vix_p is not None:
            vix_params = vix_p
            vix_g = init_a4f_state(train_ret, train_vix, vix_p)
        else:
            vix_conv = False

        # M3: A4f-Reg-VIX-Off-HighVIX
        voff_p, voff_conv = fit_a4f_regime(train_ret, train_vix, train_w_voff)
        if voff_p is not None:
            voff_params = voff_p
            voff_g = init_a4f_state(train_ret, train_vix, voff_p, weights=train_w_voff)
        else:
            voff_conv = False

        # M4: A4f-Reg-VIX-On-HighCorr
        corron_p, corron_conv = fit_a4f_regime(train_ret, train_vix, train_w_corron)
        if corron_p is not None:
            corron_params = corron_p
            corron_g = init_a4f_state(train_ret, train_vix, corron_p, weights=train_w_corron)
        else:
            corron_conv = False

        # M5: A4f-Adaptive (|corr| weighting)
        adap_p, adap_conv = fit_a4f_regime(train_ret, train_vix, train_w_adap)
        if adap_p is not None:
            adap_params = adap_p
            adap_g = init_a4f_state(train_ret, train_vix, adap_p, weights=train_w_adap)
        else:
            adap_conv = False

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            'gjr_conv': bool(gjr_conv),
            'vix_conv': bool(vix_conv),
            'voff_conv': bool(voff_conv),
            'corron_conv': bool(corron_conv),
            'adap_conv': bool(adap_conv),
            'vix_theta0': float(vix_params[0]) if vix_params is not None else None,
            'vix_theta1': float(vix_params[1]) if vix_params is not None else None,
            'voff_theta0': float(voff_params[0]) if voff_params is not None else None,
            'voff_theta1': float(voff_params[1]) if voff_params is not None else None,
            'corron_theta0': float(corron_params[0]) if corron_params is not None else None,
            'corron_theta1': float(corron_params[1]) if corron_params is not None else None,
            'adap_theta0': float(adap_params[0]) if adap_params is not None else None,
            'adap_theta1': float(adap_params[1]) if adap_params is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # Forecast for day abs_idx (uses info up to t-1)
    r_prev = ret[abs_idx - 1]
    v_lag = vix[abs_idx - 1]

    # Regime indicators for day abs_idx are already lagged (built from t-1)
    w_voff_t = w_vix_off[abs_idx]
    w_corron_t = w_corr_on[abs_idx]
    w_adap_t = w_adaptive[abs_idx]

    # M1: GJR
    if gjr_params is not None:
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        fc_gjr[t_idx] = h_new
        gjr_h = h_new

    # M2: A4f-VIX (no regime)
    if vix_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = vix_params
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * vix_g
        g_new = max(g_new, 1e-10)
        fc_vix[t_idx] = tau_t * g_new
        vix_g = g_new

    # M3: A4f-Reg-VIX-Off-HighVIX
    if voff_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = voff_params
        tau_t = max(theta0 + theta1 * v_lag**2 * w_voff_t, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * voff_g
        g_new = max(g_new, 1e-10)
        fc_reg_voff[t_idx] = tau_t * g_new
        voff_g = g_new

    # M4: A4f-Reg-VIX-On-HighCorr
    if corron_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = corron_params
        tau_t = max(theta0 + theta1 * v_lag**2 * w_corron_t, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * corron_g
        g_new = max(g_new, 1e-10)
        fc_reg_corron[t_idx] = tau_t * g_new
        corron_g = g_new

    # M5: A4f-Adaptive
    if adap_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = adap_params
        tau_t = max(theta0 + theta1 * v_lag**2 * w_adap_t, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * adap_g
        g_new = max(g_new, 1e-10)
        fc_adaptive[t_idx] = tau_t * g_new
        adap_g = g_new

    prev_window = current_window

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")

# ============================================================
# SECTION 6: EVALUATION
# ============================================================
print("\n[6] Evaluation...")

oos_r2 = r2[oos_indices]
oos_dates = dates[oos_indices]
oos_vix_arr = vix[oos_indices]
oos_corr = corr60[oos_indices]
oos_vix_lag = vix_lag_series[oos_indices]
oos_corr_lag = corr_lag_series[oos_indices]
oos_window_tags = np.array([window_tags[i] for i in oos_indices])


def qlike_loss(fc, r2_vals):
    return np.log(fc) + r2_vals / fc


def hac_dm_test(d_array):
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d_array)
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = np.var(d_array, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci_mean_diff(arr, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        starts_ = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts_ if s + block_len <= n]
        if not blocks:
            return (np.nan, np.nan)
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


def evaluate_pair(fc_base, fc_alt, r2_vals, label_alt):
    both_valid = (~np.isnan(fc_base) & (fc_base > 0) &
                  ~np.isnan(fc_alt) & (fc_alt > 0))
    n = both_valid.sum()
    if n < 30:
        return None
    b = fc_base[both_valid]
    a = fc_alt[both_valid]
    r2_v = r2_vals[both_valid]
    ql_b = float(np.mean(qlike_loss(b, r2_v)))
    ql_a = float(np.mean(qlike_loss(a, r2_v)))
    loss_b = qlike_loss(b, r2_v)
    loss_a = qlike_loss(a, r2_v)
    d = loss_b - loss_a  # positive => alt better
    dm_t, dm_p, _ = hac_dm_test(d)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(d, n_boot=1000)
    rho_b, _ = stats.spearmanr(b, r2_v)
    rho_a, _ = stats.spearmanr(a, r2_v)
    return {
        'n': int(n),
        'qlike_base': ql_b,
        f'qlike_{label_alt}': ql_a,
        'qlike_diff_pct': (ql_a - ql_b) / abs(ql_b) * 100,
        'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
        'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
        'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
        'spearman_base': float(rho_b),
        f'spearman_{label_alt}': float(rho_a),
        'bootstrap_ci_95': [ci_lo, ci_hi],
    }


MODEL_NAMES = [
    ('vix', fc_vix),
    ('reg_voff', fc_reg_voff),
    ('reg_corron', fc_reg_corron),
    ('adaptive', fc_adaptive),
]

results = {
    'metadata': {},
    'full_oos_vs_gjr': {},
    'full_oos_vs_a4f_vix': {},
    'per_window_vs_gjr': {},
    'vix_buckets_vs_gjr': {},
    'corr_buckets_vs_gjr': {},
    'refit_log': refit_log,
}

# --- Full OOS vs GJR ---
print("\n  FULL OOS vs GJR baseline:")
print(f"  {'Alt model':<16} {'n':>6} {'QL_GJR':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
for label_alt, fc_alt in MODEL_NAMES:
    res = evaluate_pair(fc_gjr, fc_alt, oos_r2, label_alt)
    if res is None:
        print(f"  {label_alt:<16} insufficient")
        continue
    results['full_oos_vs_gjr'][f'gjr_vs_{label_alt}'] = res
    harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
    print(f"  {label_alt:<16} {res['n']:>6} {res['qlike_base']:>10.5f} "
          f"{res[f'qlike_{label_alt}']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
          f"{res['dm_t']:>+8.3f} {harvey:>8}")

# --- Full OOS: regime models vs pure A4f-VIX ---
print("\n  FULL OOS: regime models vs pure A4f-VIX (K1089 baseline):")
print(f"  {'Alt model':<16} {'n':>6} {'QL_VIX':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
for label_alt, fc_alt in [('reg_voff', fc_reg_voff),
                           ('reg_corron', fc_reg_corron),
                           ('adaptive', fc_adaptive)]:
    res = evaluate_pair(fc_vix, fc_alt, oos_r2, label_alt)
    if res is None:
        continue
    results['full_oos_vs_a4f_vix'][f'vix_vs_{label_alt}'] = res
    harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
    print(f"  {label_alt:<16} {res['n']:>6} {res['qlike_base']:>10.5f} "
          f"{res[f'qlike_{label_alt}']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
          f"{res['dm_t']:>+8.3f} {harvey:>8}")

# --- Per-window vs GJR ---
print("\n  Per-window vs GJR:")
for name, start, end in OOS_WINDOWS:
    mask = (oos_window_tags == name)
    if mask.sum() < 30:
        continue
    r2_w = oos_r2[mask]
    results['per_window_vs_gjr'][name] = {'start': start, 'end': end, 'n': int(mask.sum())}
    print(f"\n  [{name}] n={mask.sum()}")
    for label_alt, fc_alt_full in MODEL_NAMES:
        res = evaluate_pair(fc_gjr[mask], fc_alt_full[mask], r2_w, label_alt)
        if res is None:
            continue
        results['per_window_vs_gjr'][name][f'gjr_vs_{label_alt}'] = res
        harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
        print(f"    {label_alt:<16} {res['n']:>6} {res['qlike_base']:>10.5f} "
              f"{res[f'qlike_{label_alt}']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
              f"{res['dm_t']:>+8.3f} {harvey}")

# --- VIX bucket analysis (KEY QUESTION: does High-VIX damage disappear?) ---
print("\n  VIX bucket analysis (all A4f variants vs GJR):")
print(f"  {'Bucket':<10} {'Range':<10} {'Model':<14} {'n':>6} {'QL_GJR':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8}")
for bname, bmin, bmax in VIX_BUCKETS:
    mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax)
    n_b = mask.sum()
    if n_b < 20:
        results['vix_buckets_vs_gjr'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue
    results['vix_buckets_vs_gjr'][bname] = {'range': [bmin, bmax], 'n': int(n_b), 'models': {}}
    for label_alt, fc_alt_full in MODEL_NAMES:
        res = evaluate_pair(fc_gjr[mask], fc_alt_full[mask], oos_r2[mask], label_alt)
        if res is None:
            continue
        results['vix_buckets_vs_gjr'][bname]['models'][label_alt] = res
        harvey = 'PASS' if res['harvey_pass'] else ''
        print(f"  {bname:<10} [{bmin},{bmax}) {label_alt:<14} {res['n']:>6} "
              f"{res['qlike_base']:>10.5f} {res[f'qlike_{label_alt}']:>10.5f} "
              f"{res['qlike_diff_pct']:>+7.2f}% {res['dm_t']:>+8.3f} {harvey}")

# --- Correlation bucket analysis ---
print("\n  Correlation bucket analysis (all A4f variants vs GJR):")
print(f"  {'Bucket':<14} {'Range':<12} {'Model':<14} {'n':>6} {'QL_GJR':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8}")
for bname, bmin, bmax in CORR_BUCKETS:
    mask = (oos_corr_lag >= bmin) & (oos_corr_lag < bmax)
    n_b = mask.sum()
    if n_b < 20:
        results['corr_buckets_vs_gjr'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue
    results['corr_buckets_vs_gjr'][bname] = {'range': [bmin, bmax], 'n': int(n_b), 'models': {}}
    for label_alt, fc_alt_full in MODEL_NAMES:
        res = evaluate_pair(fc_gjr[mask], fc_alt_full[mask], oos_r2[mask], label_alt)
        if res is None:
            continue
        results['corr_buckets_vs_gjr'][bname]['models'][label_alt] = res
        harvey = 'PASS' if res['harvey_pass'] else ''
        print(f"  {bname:<14} [{bmin:+.1f},{bmax:+.1f}) {label_alt:<14} {res['n']:>6} "
              f"{res['qlike_base']:>10.5f} {res[f'qlike_{label_alt}']:>10.5f} "
              f"{res['qlike_diff_pct']:>+7.2f}% {res['dm_t']:>+8.3f} {harvey}")

# ============================================================
# SECTION 7: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)


def _dm_verdict(t, direction_positive=True):
    if t is None:
        return 'N/A'
    if direction_positive:
        return 'PASS' if abs(t) > 3.0 and t > 0 else 'FAIL'
    else:
        return 'PASS' if abs(t) > 3.0 and t < 0 else 'FAIL'


# H1: A4f-Reg-VIX-Off-HighVIX vs GJR
h1_entry = results['full_oos_vs_gjr'].get('gjr_vs_reg_voff', {})
h1_t = h1_entry.get('dm_t')
h1_verdict = _dm_verdict(h1_t)
print(f"  H1 (Reg-VIX-OFF-HighVIX > GJR, |t|>3): {h1_verdict} (t={h1_t})")

# H2: A4f-Reg-VIX-On-HighCorr vs GJR
h2_entry = results['full_oos_vs_gjr'].get('gjr_vs_reg_corron', {})
h2_t = h2_entry.get('dm_t')
h2_verdict = _dm_verdict(h2_t)
print(f"  H2 (Reg-VIX-ON-HighCorr > GJR, |t|>3): {h2_verdict} (t={h2_t})")

# H3: A4f-Adaptive vs GJR
h3_entry = results['full_oos_vs_gjr'].get('gjr_vs_adaptive', {})
h3_t = h3_entry.get('dm_t')
h3_verdict = _dm_verdict(h3_t)
print(f"  H3 (Adaptive > GJR, |t|>3): {h3_verdict} (t={h3_t})")

# H4: Best regime model vs pure A4f-VIX
best_t = None
best_model = None
for k, v in results['full_oos_vs_a4f_vix'].items():
    t = v.get('dm_t')
    if t is not None and (best_t is None or t > best_t):
        best_t = t
        best_model = k
h4_verdict = _dm_verdict(best_t)
print(f"  H4 (best regime > pure A4f-VIX): {h4_verdict} "
      f"(best={best_model}, t={best_t})")

# H5: High-VIX bucket — does damage disappear under regime?
high_bucket = results['vix_buckets_vs_gjr'].get('High', {})
h5_results = {}
if isinstance(high_bucket, dict) and 'models' in high_bucket:
    for m_label, r in high_bucket['models'].items():
        t = r.get('dm_t')
        h5_results[m_label] = t
    original_vix_t = h5_results.get('vix')
    best_regime_t = max(
        (t for k, t in h5_results.items() if k != 'vix' and t is not None),
        default=None
    )
    if original_vix_t is not None and best_regime_t is not None:
        damage_reduced = best_regime_t > original_vix_t
        h5_verdict = 'DAMAGE_REDUCED' if damage_reduced else 'DAMAGE_PERSISTS'
    else:
        h5_verdict = 'N/A'
    print(f"  H5 (High-VIX damage reduced): {h5_verdict}")
    print(f"      VIX model: t={original_vix_t}")
    for m_label, t in h5_results.items():
        if m_label != 'vix':
            print(f"      {m_label}: t={t}")
else:
    h5_verdict = 'N/A (insufficient data)'
    print(f"  H5: {h5_verdict}")

results['hypothesis_verdicts'] = {
    'H1_reg_voff_vs_gjr': {'dm_t': h1_t, 'verdict': h1_verdict},
    'H2_reg_corron_vs_gjr': {'dm_t': h2_t, 'verdict': h2_verdict},
    'H3_adaptive_vs_gjr': {'dm_t': h3_t, 'verdict': h3_verdict},
    'H4_best_regime_vs_a4f_vix': {'dm_t': best_t, 'best_model': best_model,
                                   'verdict': h4_verdict},
    'H5_high_vix_damage': {
        'verdict': h5_verdict,
        'vix_dm_t': h5_results.get('vix'),
        'regime_models': {k: v for k, v in h5_results.items() if k != 'vix'},
    },
}

# ============================================================
# SECTION 8: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

results['metadata'] = {
    'experiment_id': 'K1096',
    'title': 'BTC Regime-Switching A4f — rescue attempt via correlation/VIX switching',
    'asset': 'BTC-USD',
    'exogenous': 'VIX with regime switching',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'corr_window': CORR_WINDOW,
    'vix_threshold': VIX_THRESHOLD,
    'corr_threshold': CORR_THRESHOLD,
    'n_total': int(n_total),
    'n_oos_actual': int(n_oos_actual),
    'n_refits': int(refit_count),
    'oos_windows': [[n, s, e] for n, s, e in OOS_WINDOWS],
    'vix_buckets': [[n, s, e] for n, s, e in VIX_BUCKETS],
    'corr_buckets': [[n, s, e] for n, s, e in CORR_BUCKETS],
    'random_seed': 42,
    'elapsed_seconds': elapsed,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (via K1096 brief)',
    'executor': 'Claude',
    'upstream_experiments': [
        'K1089 (BTC A4f-VIX NS, high-VIX wrong direction)',
        'K1025 / Paper 6 (crypto fear channel asymmetry)',
        'K1075 (SPY A4f PASS)',
        'K1085 (GLD + GVZ PASS)',
    ],
    'models_tested': [
        'GJR-GARCH(1,1)',
        'A4f-VIX (full, K1089 baseline)',
        'A4f-Reg-VIX-Off-HighVIX (tau = theta0 + theta1 * VIX² * 1(VIX<25))',
        'A4f-Reg-VIX-On-HighCorr (tau = theta0 + theta1 * VIX² * 1(|corr60d|>0.3))',
        'A4f-Adaptive (tau = theta0 + theta1 * VIX² * |corr60d|)',
    ],
    'references': [
        'K1089 (BTC A4f-VIX baseline)',
        'Paper 6 (K1025) crypto fear asymmetry',
        'Baur & Dimpfl (2018). Asymmetric volatility in cryptocurrencies. EL.',
        'Bollerslev, Patton & Quaedvlieg (2016). Exploiting the errors. JoE 192:1-18.',
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Hamilton (1989). A new approach to the economic analysis of nonstationary time series. Econometrica 57(2):357-384.',
        'Patton (2011). Volatility forecast comparison. JoE 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). MSE equality testing.',
    ],
    'design_notes': (
        'Regime indicators built from VIX[t-1] and corr60d[t-1] only. '
        'Correlation computed on forward-filled SPY returns over BTC 24/7 calendar. '
        'Weights are multiplied into the MIDAS long-run term tau (not the short-run g term). '
        'When the weight is zero, the model collapses to GJR structure (only theta0 remains). '
        'This is a single-state "soft" regime switch — parameters theta0, theta1 are constant '
        'across regimes; only the regressor loading is gated.'
    ),
}

# Save forecasts and indicators for downstream analysis
results['forecasts'] = {
    'dates': [d.strftime('%Y-%m-%d') for d in oos_dates],
    'window_tags': oos_window_tags.tolist(),
    'r2': oos_r2.tolist(),
    'vix_lag': oos_vix_lag.tolist(),
    'corr60d_lag': oos_corr_lag.tolist(),
    'fc_gjr': [float(x) if np.isfinite(x) else None for x in fc_gjr],
    'fc_a4f_vix': [float(x) if np.isfinite(x) else None for x in fc_vix],
    'fc_a4f_reg_voff': [float(x) if np.isfinite(x) else None for x in fc_reg_voff],
    'fc_a4f_reg_corron': [float(x) if np.isfinite(x) else None for x in fc_reg_corron],
    'fc_a4f_adaptive': [float(x) if np.isfinite(x) else None for x in fc_adaptive],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {RESULTS_PATH}")
print(f"Total elapsed: {elapsed:.0f}s")
print("=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
