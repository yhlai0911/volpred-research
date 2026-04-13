#!/usr/bin/env python3
"""
K1099: 0050.TW A4f with USD/TWD Realized Vol — Direct Currency Channel Attack
=============================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K1077 showed A4f(VIX²) on 0050.TW gives DM t=-0.49 NS (Taiwan extended OOS
  Harvey FAIL).
  K1083 decomposed Taiwan→EWT gap and found 83% is explained by the USD
  currency wrapper (not domestic composition or idiosyncratic).
  K1098 (not yet run) asks whether VIXTWN (domestic implied vol) can rescue
  0050.TW — but domestic IV cannot fix an FX problem.

  K1099 tests the direct currency channel hypothesis: if FX is the root cause,
  then using USD/TWD realized volatility² as the A4f long-run driver should
  work. This is Paper 10's potential revival path ("FX vol, not domestic IV,
  is the correct τ regressor for non-US ETFs").

Design:
  - Three non-overlapping OOS windows (2010-2014, 2015-2019, 2020-2025),
    matching K1077 for fair comparison.
  - Rolling-window GARCH with 2000-day training, 63-day refit.
  - Four models:
      (1) GJR baseline
      (2) A4f-VIX:    τ = θ₀ + θ₁·VIX²_{t-1}                   [K1077 replication]
      (3) A4f-FXVol:  τ = θ₀ + θ₁·FXVol²_{t-1}                 [NEW]
      (4) A4f-COMBO:  τ = θ₀ + θ₁·VIX²_{t-1} + θ₂·FXVol²_{t-1}  [NEW]
  - Two FX realized-vol measures:
      RV_21:   21-day rolling realized vol of TWDUSD log returns (annualized)
      EWMA:    RiskMetrics EWMA(λ=0.94) of TWDUSD squared returns (annualized)
    Primary: RV_21 (robust and simple). EWMA reported as sensitivity.
  - FX regime analysis: High-FXVol (top tercile) vs Low-FXVol (bottom tercile).
  - Crisis sub-periods: 2011 Euro, 2013 Taper Tantrum, 2015 TWD devaluation,
    2020 COVID, 2022 Bear.

Hypotheses:
  H1: A4f-FXVol on 0050.TW Harvey-PASS (|t|>3.0 vs GJR baseline).
  H2: A4f-FXVol vs A4f-VIX direct DM comparison (better / worse / indifferent?).
  H3: COMBO (VIX² + FXVol²) dominates either solo.
  H4: In high-FXVol regimes, A4f-FXVol strictly outperforms A4f-VIX.

Data sources (yfinance):
  - 0050.TW (cleaned via clean_tw50_data, MANDATORY Yahoo 2014 split fix).
  - ^VIX for baseline A4f.
  - TWDUSD=X for FX return (with K1083-style corrupted-close repair).
Evaluation: QLIKE on r² (Patton 2011), DM HAC t (Harvey |t|>3.0), Spearman ρ.

References:
  - Engle et al. (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Conrad & Loch (2015). JBES.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). Testing equality of MSEs.
  - K1077 (0050.TW A4f-VIX NULL), K1083 (FX=83% of gap), K1085 (GVZ for gold).

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1099
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
EXPERIMENT_ID = "K1099"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data  # MANDATORY for 0050.TW

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1099_results.json')

# Configuration (matches K1077 for fair replication + FX additions)
DATA_START = '2005-07-01'
DATA_END = '2025-12-31'
WINDOW = 2000
REFIT_EVERY = 63

OOS_WINDOWS = [
    ('Early_2010_2014', '2010-01-01', '2014-12-31'),
    ('Middle_2015_2019', '2015-01-01', '2019-12-31'),
    ('Late_2020_2025', '2020-01-01', '2025-12-31'),
]

# FX-focused crisis sub-periods (K1099 specific)
CRISIS_PERIODS = [
    ('Euro_Crisis_2011', '2011-06-01', '2012-06-30'),
    ('TaperTantrum_2013', '2013-05-01', '2013-09-30'),
    ('TWD_Deval_2015', '2015-08-01', '2016-01-31'),
    ('COVID_2020', '2020-02-01', '2020-06-30'),
    ('Bear_2022', '2022-01-01', '2022-12-31'),
]

# FX-vol window for regime split (annualized RV_21)
# Computed in-sample per-OOS quantiles; placeholders for printout
FX_REGIME_TERCILES = [0.33, 0.67]  # Bottom / Middle / Top tercile

FXVOL_WINDOW = 21  # 1-month rolling realized vol
EWMA_LAMBDA = 0.94  # RiskMetrics standard


print("=" * 72)
print(f"{EXPERIMENT_ID}: 0050.TW A4f-FXVol (Direct Currency Channel Attack)")
print(f"  Models: GJR | A4f-VIX | A4f-FXVol | A4f-COMBO")
print(f"  3 OOS windows, 5 FX-crisis periods, 3 FX-regime terciles")
print("=" * 72)

# ============================================================
# SECTION 1: DATA LOADING (0050.TW + ^VIX + TWDUSD=X)
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

# 0050.TW (mandatory clean_tw50_data)
raw_tw = yf.download('0050.TW', start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=False)
if isinstance(raw_tw.columns, pd.MultiIndex):
    raw_tw.columns = raw_tw.columns.get_level_values(0)
prices_tw_raw = raw_tw['Close'].copy() if 'Close' in raw_tw.columns else raw_tw.iloc[:, 0].copy()
prices_tw, _ = clean_tw50_data(prices_tw_raw)
log_ret_tw = np.log(prices_tw / prices_tw.shift(1))

# VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()
vix_ffill = vix_close.reindex(prices_tw.index, method='ffill')

# TWDUSD=X (USD per TWD)
fx_raw = yf.download('TWDUSD=X', start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=False)
if isinstance(fx_raw.columns, pd.MultiIndex):
    fx_raw.columns = fx_raw.columns.get_level_values(0)
fx_close = fx_raw['Close'].copy() if 'Close' in fx_raw.columns else fx_raw.iloc[:, 0].copy()

# --- Yahoo FX data quality fix (K1083 pattern) ---
fx_high = fx_raw['High'] if 'High' in fx_raw.columns else None
fx_low = fx_raw['Low'] if 'Low' in fx_raw.columns else None
bad_fx_mask = (fx_close > 0.05) | (fx_close < 0.02)
n_bad_fx = int(bad_fx_mask.sum())
if n_bad_fx > 0:
    print(f"  [FX cleanup] Detected {n_bad_fx} corrupted FX closes (outside 0.02-0.05)")
    for d in fx_close[bad_fx_mask].index:
        orig = float(fx_close.loc[d])
        if fx_high is not None and fx_low is not None:
            hi = float(fx_high.loc[d]) if not pd.isna(fx_high.loc[d]) else np.nan
            lo = float(fx_low.loc[d]) if not pd.isna(fx_low.loc[d]) else np.nan
            if 0.02 < hi < 0.05 and 0.02 < lo < 0.05:
                fixed = (hi + lo) / 2.0
                print(f"    {d.strftime('%Y-%m-%d')}: Close={orig:.5f} → "
                      f"repaired to (H+L)/2 = {fixed:.5f}")
                fx_close.loc[d] = fixed
                continue
        print(f"    {d.strftime('%Y-%m-%d')}: Close={orig:.5f} → NaN (will ffill)")
        fx_close.loc[d] = np.nan
    residual_bad = ((fx_close.dropna() > 0.05) | (fx_close.dropna() < 0.02)).sum()
    print(f"  [FX cleanup] After repair: residual bad={int(residual_bad)}")

fx_ffill = fx_close.reindex(prices_tw.index, method='ffill')

fx_valid = fx_ffill.dropna()
fx_min, fx_max = float(fx_valid.min()), float(fx_valid.max())
print(f"  TWDUSD=X range after cleanup: [{fx_min:.5f}, {fx_max:.5f}]")
assert 0.02 < fx_min < 0.05 and 0.02 < fx_max < 0.05, \
    f"TWDUSD=X not in expected USD/TWD range; got [{fx_min}, {fx_max}]"

# FX log return
log_ret_fx = np.log(fx_ffill / fx_ffill.shift(1))

# --- Build FX realized vol series (annualized, in % units for numerical
#     scale symmetry with VIX which is annualized implied vol in % units) ---
# RV_21: sqrt( sum_{i=1..21} r_fx^2_{t-i} * 252 / 21 ) * 100
fx_r2 = (log_ret_fx ** 2)
fx_rv21_var_annual = fx_r2.rolling(window=FXVOL_WINDOW, min_periods=FXVOL_WINDOW).mean() * 252.0
fx_rv21_vol_annual_pct = np.sqrt(fx_rv21_var_annual) * 100.0  # percent

# EWMA of squared returns, annualized * 252, sqrt and *100 → vol percent
# Initialize with rolling variance of first FXVOL_WINDOW points
fx_ewma_var = pd.Series(index=fx_r2.index, dtype=float)
init_var = fx_r2.iloc[:FXVOL_WINDOW].mean()
if not np.isfinite(init_var):
    init_var = 1e-8
prev = float(init_var)
for i, val in enumerate(fx_r2.values):
    if not np.isfinite(val):
        fx_ewma_var.iloc[i] = prev
        continue
    if i == 0:
        fx_ewma_var.iloc[i] = prev
    else:
        prev = EWMA_LAMBDA * prev + (1.0 - EWMA_LAMBDA) * val
        fx_ewma_var.iloc[i] = prev
fx_ewma_vol_annual_pct = np.sqrt(fx_ewma_var * 252.0) * 100.0

df = pd.DataFrame({
    'price': prices_tw,
    'log_ret': log_ret_tw,
    'log_ret_fx': log_ret_fx,
    'VIX': vix_ffill,
    'FXVOL_RV21': fx_rv21_vol_annual_pct,
    'FXVOL_EWMA': fx_ewma_vol_annual_pct,
})
df = df.dropna()

# Safety net: drop extreme returns
max_abs = df['log_ret'].abs().max()
if max_abs > 0.3:
    bad = df['log_ret'].abs() > 0.3
    for d in df[bad].index:
        print(f"    Suspicious ret on {d.strftime('%Y-%m-%d')}: {df.loc[d, 'log_ret']:.4f}")
    df = df[~bad]

n_total = len(df)
print(f"  Full data: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  FXVOL_RV21 (annualized %) — mean {df['FXVOL_RV21'].mean():.2f}, "
      f"range [{df['FXVOL_RV21'].min():.2f}, {df['FXVOL_RV21'].max():.2f}]")
print(f"  FXVOL_EWMA (annualized %) — mean {df['FXVOL_EWMA'].mean():.2f}, "
      f"range [{df['FXVOL_EWMA'].min():.2f}, {df['FXVOL_EWMA'].max():.2f}]")
print(f"  VIX (annualized %)        — mean {df['VIX'].mean():.2f}, "
      f"range [{df['VIX'].min():.2f}, {df['VIX'].max():.2f}]")

ret = df['log_ret'].values
vix = df['VIX'].values
fxvol_rv21 = df['FXVOL_RV21'].values
fxvol_ewma = df['FXVOL_EWMA'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
print(f"  Return mean (ann): {np.mean(ret)*252:.4f}")
print(f"  Return std (ann):  {np.std(ret)*np.sqrt(252):.4f}")
print(f"  Return skew:  {stats.skew(ret):.3f}")
print(f"  Return kurt:  {stats.kurtosis(ret):.3f}")
try:
    from statsmodels.tsa.stattools import adfuller
    adf = adfuller(ret, maxlag=10, autolag='AIC')
    print(f"  ADF on returns: stat={adf[0]:.3f}, p={adf[1]:.4f}")
except Exception as e:
    print(f"  ADF skipped: {e}")
try:
    from statsmodels.stats.diagnostic import het_arch
    archlm = het_arch(ret, nlags=5)
    print(f"  ARCH-LM(5): stat={archlm[0]:.2f}, p={archlm[1]:.4f}")
except Exception as e:
    print(f"  ARCH-LM skipped: {e}")

# Correlation check: does FXVol co-move with domestic return vol?
r2_ann_pct = np.sqrt(pd.Series(r2).rolling(21, min_periods=21).mean().values * 252.0) * 100.0
valid_corr = np.isfinite(r2_ann_pct) & np.isfinite(fxvol_rv21) & np.isfinite(vix)
if valid_corr.sum() > 100:
    cor_fx_rv_vs_r2 = np.corrcoef(fxvol_rv21[valid_corr], r2_ann_pct[valid_corr])[0, 1]
    cor_vix_vs_r2 = np.corrcoef(vix[valid_corr], r2_ann_pct[valid_corr])[0, 1]
    cor_fx_vs_vix = np.corrcoef(fxvol_rv21[valid_corr], vix[valid_corr])[0, 1]
    print(f"  Corr(FXVOL_RV21, realized vol 0050.TW): {cor_fx_rv_vs_r2:+.3f}")
    print(f"  Corr(VIX,        realized vol 0050.TW): {cor_vix_vs_r2:+.3f}")
    print(f"  Corr(FXVOL_RV21, VIX):                   {cor_fx_vs_vix:+.3f}")
else:
    cor_fx_rv_vs_r2 = np.nan
    cor_vix_vs_r2 = np.nan
    cor_fx_vs_vix = np.nan

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) Benchmark ---
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


# --- A4f with single external regressor X^2_{t-1} ---
def fit_a4f_single(returns, x_vals):
    """
    A4f: tau_t = max(theta0 + theta1 * x_{t-1}^2, eps); g GJR; sigma2 = tau*g.
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    x_lag = np.empty(n)
    x_lag[0] = x_vals[0]
    x_lag[1:] = x_vals[:-1]
    x_lag_sq = x_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * x_lag_sq, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    x2_mean = np.mean(x_lag_sq) + 1e-8

    starts = [
        [var0 * 0.10, var0 / x2_mean * 1.0, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.20, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-12, 1e-2),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]

    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


# --- A4f-COMBO: tau = theta0 + theta1*VIX^2 + theta2*FXVOL^2 ---
def fit_a4f_combo(returns, vix_vals, fx_vals):
    n = len(returns)
    v_lag = np.empty(n); v_lag[0] = vix_vals[0]; v_lag[1:] = vix_vals[:-1]
    f_lag = np.empty(n); f_lag[0] = fx_vals[0];  f_lag[1:] = fx_vals[:-1]
    v_lag_sq = v_lag ** 2
    f_lag_sq = f_lag ** 2

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * v_lag_sq + theta2 * f_lag_sq, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    v2_mean = np.mean(v_lag_sq) + 1e-8
    f2_mean = np.mean(f_lag_sq) + 1e-8

    starts = [
        [var0 * 0.05, var0 / v2_mean * 0.5, var0 / f2_mean * 0.5, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, var0 / v2_mean * 0.3, var0 / f2_mean * 0.7, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.10, var0 / v2_mean * 1.0, var0 / f2_mean * 1.0, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),    # theta0
        (1e-12, 1e-2),    # theta1 (VIX)
        (1e-12, 1e-2),    # theta2 (FXVol)
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]

    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting (3 windows × 4 models)...")

oos_full_mask = np.zeros(n_total, dtype=bool)
window_tags = np.empty(n_total, dtype=object)
for name, start, end in OOS_WINDOWS:
    m = (dates >= start) & (dates <= end)
    oos_full_mask |= m
    for idx in np.where(m)[0]:
        window_tags[idx] = name

oos_indices = np.where(oos_full_mask)[0]
n_oos = len(oos_indices)
print(f"  Total OOS (union): {n_oos}")
for name, start, end in OOS_WINDOWS:
    hits = np.where(dates >= start)[0]
    if len(hits) == 0:
        continue
    sidx = hits[0]
    print(f"    {name}: start_idx={sidx}, W={WINDOW}, "
          f"sufficient={'YES' if sidx >= WINDOW else 'NO'}")

gjr_forecasts = np.full(n_oos, np.nan)
a4fvix_forecasts = np.full(n_oos, np.nan)
a4ffx_forecasts = np.full(n_oos, np.nan)
a4fcombo_forecasts = np.full(n_oos, np.nan)

refit_log = []

# State
gjr_h = None; gjr_params = None
a4fvix_g = None; a4fvix_params = None
a4ffx_g = None;  a4ffx_params = None
a4fcombo_g = None; a4fcombo_params = None

prev_window = None
refit_count = 0

# Use RV_21 as primary FXVOL driver
fxvol = fxvol_rv21.copy()

for t_idx, abs_idx in enumerate(oos_indices):
    current_window = window_tags[abs_idx]

    if t_idx == 0 or current_window != prev_window:
        need_refit = True
    else:
        wstart = next(s for n, s, e in OOS_WINDOWS if n == current_window)
        wstart_idx = np.where(dates >= wstart)[0][0]
        days_in = abs_idx - wstart_idx
        need_refit = (days_in % REFIT_EVERY == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]
        train_fx = fxvol[train_start:abs_idx]

        # GJR fit
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_params = gjr_p
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h

        # A4f-VIX fit
        av_p, av_conv = fit_a4f_single(train_ret, train_vix)
        if av_p is not None:
            a4fvix_params = av_p
            t0, t1, og, ap, gp, bp = av_p
            v_lag_tr = np.empty(len(train_vix))
            v_lag_tr[0] = train_vix[0]; v_lag_tr[1:] = train_vix[:-1]
            tau_tr = np.maximum(t0 + t1 * v_lag_tr**2, 1e-16)
            persist = ap + gp/2 + bp
            g = og / (1.0 - persist)
            for i in range(1, len(train_ret)):
                u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gp * u_prev**2 if u_prev < 0 else 0.0
                g = og + ap * u_prev**2 + asym + bp * g
                g = max(g, 1e-10)
            a4fvix_g = g

        # A4f-FXVol fit
        af_p, af_conv = fit_a4f_single(train_ret, train_fx)
        if af_p is not None:
            a4ffx_params = af_p
            t0, t1, og, ap, gp, bp = af_p
            f_lag_tr = np.empty(len(train_fx))
            f_lag_tr[0] = train_fx[0]; f_lag_tr[1:] = train_fx[:-1]
            tau_tr = np.maximum(t0 + t1 * f_lag_tr**2, 1e-16)
            persist = ap + gp/2 + bp
            g = og / (1.0 - persist)
            for i in range(1, len(train_ret)):
                u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gp * u_prev**2 if u_prev < 0 else 0.0
                g = og + ap * u_prev**2 + asym + bp * g
                g = max(g, 1e-10)
            a4ffx_g = g

        # A4f-COMBO fit
        ac_p, ac_conv = fit_a4f_combo(train_ret, train_vix, train_fx)
        if ac_p is not None:
            a4fcombo_params = ac_p
            t0, t1, t2, og, ap, gp, bp = ac_p
            v_lag_tr = np.empty(len(train_vix))
            v_lag_tr[0] = train_vix[0]; v_lag_tr[1:] = train_vix[:-1]
            f_lag_tr = np.empty(len(train_fx))
            f_lag_tr[0] = train_fx[0]; f_lag_tr[1:] = train_fx[:-1]
            tau_tr = np.maximum(t0 + t1 * v_lag_tr**2 + t2 * f_lag_tr**2, 1e-16)
            persist = ap + gp/2 + bp
            g = og / (1.0 - persist)
            for i in range(1, len(train_ret)):
                u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gp * u_prev**2 if u_prev < 0 else 0.0
                g = og + ap * u_prev**2 + asym + bp * g
                g = max(g, 1e-10)
            a4fcombo_g = g

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            'gjr_conv': bool(gjr_conv),
            'a4fvix_conv': bool(av_conv) if av_p is not None else False,
            'a4ffx_conv': bool(af_conv) if af_p is not None else False,
            'a4fcombo_conv': bool(ac_conv) if ac_p is not None else False,
            'a4fvix_theta1': float(av_p[1]) if av_p is not None else None,
            'a4ffx_theta1': float(af_p[1]) if af_p is not None else None,
            'a4fcombo_theta1_vix': float(ac_p[1]) if ac_p is not None else None,
            'a4fcombo_theta2_fx': float(ac_p[2]) if ac_p is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # Forecast for day abs_idx
    r_prev = ret[abs_idx - 1]

    if gjr_params is not None:
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_h = h_new

    if a4fvix_params is not None:
        t0, t1, og, ap, gp, bp = a4fvix_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(t0 + t1 * v_lag**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gp * u_prev**2 if u_prev < 0 else 0.0
        g_new = og + ap * u_prev**2 + asym + bp * a4fvix_g
        g_new = max(g_new, 1e-10)
        a4fvix_forecasts[t_idx] = tau_t * g_new
        a4fvix_g = g_new

    if a4ffx_params is not None:
        t0, t1, og, ap, gp, bp = a4ffx_params
        f_lag = fxvol[abs_idx - 1]
        tau_t = max(t0 + t1 * f_lag**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gp * u_prev**2 if u_prev < 0 else 0.0
        g_new = og + ap * u_prev**2 + asym + bp * a4ffx_g
        g_new = max(g_new, 1e-10)
        a4ffx_forecasts[t_idx] = tau_t * g_new
        a4ffx_g = g_new

    if a4fcombo_params is not None:
        t0, t1, t2, og, ap, gp, bp = a4fcombo_params
        v_lag = vix[abs_idx - 1]
        f_lag = fxvol[abs_idx - 1]
        tau_t = max(t0 + t1 * v_lag**2 + t2 * f_lag**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gp * u_prev**2 if u_prev < 0 else 0.0
        g_new = og + ap * u_prev**2 + asym + bp * a4fcombo_g
        g_new = max(g_new, 1e-10)
        a4fcombo_forecasts[t_idx] = tau_t * g_new
        a4fcombo_g = g_new

    prev_window = current_window

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_r2 = r2[oos_indices]
oos_dates = dates[oos_indices]
oos_vix = vix[oos_indices]
oos_fxvol = fxvol[oos_indices]
oos_wtags = np.array([window_tags[i] for i in oos_indices])

both_valid = (~np.isnan(gjr_forecasts) & (gjr_forecasts > 0)
              & ~np.isnan(a4fvix_forecasts) & (a4fvix_forecasts > 0)
              & ~np.isnan(a4ffx_forecasts) & (a4ffx_forecasts > 0)
              & ~np.isnan(a4fcombo_forecasts) & (a4fcombo_forecasts > 0))
n_both = int(both_valid.sum())
print(f"  Valid joint obs (all 4 models): {n_both}/{n_oos}")


def qlike(fc, r2v):
    return np.log(fc) + r2v / fc


def hac_dm(d):
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d)
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = np.var(d, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci(arr, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


MODELS = {
    'GJR':     (gjr_forecasts, 'GJR baseline'),
    'A4f_VIX': (a4fvix_forecasts, 'A4f with VIX² (K1077 replication)'),
    'A4f_FX':  (a4ffx_forecasts, 'A4f with FXVol² (NEW)'),
    'A4f_COMBO': (a4fcombo_forecasts, 'A4f with VIX² + FXVol² (NEW)'),
}


def eval_losses(mask):
    """Return dict model -> (qlike_mean, loss_array, rho)"""
    out = {}
    r2v = oos_r2[mask]
    for k, (fc, _) in MODELS.items():
        fcv = fc[mask]
        ql_arr = qlike(fcv, r2v)
        rho, _ = stats.spearmanr(fcv, r2v)
        out[k] = {
            'qlike_mean': float(np.mean(ql_arr)),
            'loss_arr': ql_arr,
            'spearman': float(rho),
            'fc': fcv,
        }
    return out


def pairwise_dm(eval_dict, benchmark):
    """Return {other_model: (dm_t, dm_p, harvey, diff_pct)} vs benchmark."""
    out = {}
    bench = eval_dict[benchmark]
    for k, v in eval_dict.items():
        if k == benchmark:
            continue
        d = bench['loss_arr'] - v['loss_arr']  # positive => k better
        dm_t, dm_p, _ = hac_dm(d)
        ci_lo, ci_hi = bootstrap_ci(d, n_boot=1000)
        diff = (v['qlike_mean'] - bench['qlike_mean']) / abs(bench['qlike_mean']) * 100
        out[k] = {
            'dm_t_vs_' + benchmark: float(dm_t) if np.isfinite(dm_t) else None,
            'dm_p_vs_' + benchmark: float(dm_p) if np.isfinite(dm_p) else None,
            'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
            'qlike_diff_pct_vs_' + benchmark: float(diff),
            'bootstrap_ci_95': [ci_lo, ci_hi],
        }
    return out


results = {
    'metadata': {},
    'diagnostics': {
        'corr_fxvol_rv21_vs_realized_vol': float(cor_fx_rv_vs_r2) if np.isfinite(cor_fx_rv_vs_r2) else None,
        'corr_vix_vs_realized_vol': float(cor_vix_vs_r2) if np.isfinite(cor_vix_vs_r2) else None,
        'corr_fxvol_vs_vix': float(cor_fx_vs_vix) if np.isfinite(cor_fx_vs_vix) else None,
    },
    'full_oos': {},
    'per_window': {},
    'crisis_subperiods': {},
    'fx_regime': {},
    'refit_log': refit_log,
}

# --- Full OOS ---
if n_both > 0:
    ev = eval_losses(both_valid)
    print(f"\n  FULL OOS (2010-2025, n={n_both}):")
    print(f"    {'Model':<12} {'QLIKE':>12} {'Spearman':>10}")
    for k in ['GJR', 'A4f_VIX', 'A4f_FX', 'A4f_COMBO']:
        print(f"    {k:<12} {ev[k]['qlike_mean']:>12.5f} {ev[k]['spearman']:>10.3f}")

    # vs GJR (H1 test)
    vs_gjr = pairwise_dm(ev, 'GJR')
    # vs A4f_VIX (H2 test: is FX better than VIX?)
    vs_vix = pairwise_dm(ev, 'A4f_VIX')
    # vs A4f_FX (H3 test: COMBO vs solo FX)
    vs_fx = pairwise_dm(ev, 'A4f_FX')

    print("\n    Pairwise DM (vs GJR benchmark, Harvey |t|>3):")
    for k in ['A4f_VIX', 'A4f_FX', 'A4f_COMBO']:
        r = vs_gjr[k]
        dm_t = r['dm_t_vs_GJR']
        diff = r['qlike_diff_pct_vs_GJR']
        ok = 'PASS' if r['harvey_pass'] else 'FAIL'
        print(f"      {k:<12} DM t={dm_t:+.3f}  diff={diff:+.2f}%  {ok}")

    print("\n    Pairwise DM (vs A4f_VIX):")
    for k in ['A4f_FX', 'A4f_COMBO']:
        r = vs_vix[k]
        dm_t = r['dm_t_vs_A4f_VIX']
        diff = r['qlike_diff_pct_vs_A4f_VIX']
        ok = 'PASS' if r['harvey_pass'] else 'FAIL'
        print(f"      {k:<12} DM t={dm_t:+.3f}  diff={diff:+.2f}%  {ok}")

    print("\n    Pairwise DM (vs A4f_FX):")
    for k in ['A4f_COMBO']:
        r = vs_fx[k]
        dm_t = r['dm_t_vs_A4f_FX']
        diff = r['qlike_diff_pct_vs_A4f_FX']
        ok = 'PASS' if r['harvey_pass'] else 'FAIL'
        print(f"      {k:<12} DM t={dm_t:+.3f}  diff={diff:+.2f}%  {ok}")

    results['full_oos'] = {
        'n': n_both,
        'qlike': {k: ev[k]['qlike_mean'] for k in MODELS},
        'spearman': {k: ev[k]['spearman'] for k in MODELS},
        'dm_vs_GJR': vs_gjr,
        'dm_vs_A4f_VIX': vs_vix,
        'dm_vs_A4f_FX': vs_fx,
    }

# --- Per OOS window ---
print("\n  Per-window results:")
print(f"  {'Window':<22} {'n':>6} {'QL_GJR':>10} {'QL_VIX':>10} {'QL_FX':>10} {'QL_COMBO':>10}")
for name, start, end in OOS_WINDOWS:
    mask = (oos_wtags == name) & both_valid
    n_w = int(mask.sum())
    if n_w < 30:
        continue
    ev = eval_losses(mask)
    print(f"  {name:<22} {n_w:>6} {ev['GJR']['qlike_mean']:>10.5f} "
          f"{ev['A4f_VIX']['qlike_mean']:>10.5f} {ev['A4f_FX']['qlike_mean']:>10.5f} "
          f"{ev['A4f_COMBO']['qlike_mean']:>10.5f}")
    vs_gjr = pairwise_dm(ev, 'GJR')
    vs_vix = pairwise_dm(ev, 'A4f_VIX')
    vs_fx = pairwise_dm(ev, 'A4f_FX')

    # Print key DMs for this window
    print(f"    vs GJR: FX DM t={vs_gjr['A4f_FX']['dm_t_vs_GJR']:+.3f}, "
          f"COMBO DM t={vs_gjr['A4f_COMBO']['dm_t_vs_GJR']:+.3f}")
    print(f"    vs VIX: FX DM t={vs_vix['A4f_FX']['dm_t_vs_A4f_VIX']:+.3f}")

    results['per_window'][name] = {
        'start': start, 'end': end, 'n': n_w,
        'qlike': {k: ev[k]['qlike_mean'] for k in MODELS},
        'spearman': {k: ev[k]['spearman'] for k in MODELS},
        'dm_vs_GJR': vs_gjr,
        'dm_vs_A4f_VIX': vs_vix,
        'dm_vs_A4f_FX': vs_fx,
    }

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods (focus: A4f_FX vs GJR and vs A4f_VIX):")
print(f"  {'Crisis':<22} {'n':>5} {'FXvsGJR t':>10} {'FXvsVIX t':>10} {'COMBO t':>9}")
for cname, cstart, cend in CRISIS_PERIODS:
    c_mask_full = (oos_dates >= cstart) & (oos_dates <= cend)
    mask = c_mask_full & both_valid
    n_c = int(mask.sum())
    if n_c < 30:
        print(f"  {cname:<22} insufficient (n={n_c})")
        continue
    ev = eval_losses(mask)
    vs_gjr = pairwise_dm(ev, 'GJR')
    vs_vix = pairwise_dm(ev, 'A4f_VIX')
    fx_vs_gjr_t = vs_gjr['A4f_FX']['dm_t_vs_GJR']
    fx_vs_vix_t = vs_vix['A4f_FX']['dm_t_vs_A4f_VIX']
    combo_t = vs_gjr['A4f_COMBO']['dm_t_vs_GJR']
    print(f"  {cname:<22} {n_c:>5} {fx_vs_gjr_t:+10.3f} {fx_vs_vix_t:+10.3f} "
          f"{combo_t:+9.3f}")

    results['crisis_subperiods'][cname] = {
        'start': cstart, 'end': cend, 'n': n_c,
        'fxvol_mean': float(np.mean(oos_fxvol[mask])),
        'vix_mean': float(np.mean(oos_vix[mask])),
        'qlike': {k: ev[k]['qlike_mean'] for k in MODELS},
        'dm_vs_GJR': vs_gjr,
        'dm_vs_A4f_VIX': vs_vix,
    }

# --- FX Regime analysis (terciles of OOS FXVol) ---
print("\n  FX Regime analysis (OOS FXVOL_RV21 terciles):")
fxvol_sorted = np.sort(oos_fxvol[both_valid])
q33 = np.quantile(fxvol_sorted, FX_REGIME_TERCILES[0])
q67 = np.quantile(fxvol_sorted, FX_REGIME_TERCILES[1])

REGIMES = [
    ('Low_FXVol',  -np.inf, q33),
    ('Mid_FXVol',  q33, q67),
    ('High_FXVol', q67, np.inf),
]

print(f"  Terciles on annualized FXVOL_RV21 (%): q33={q33:.2f}, q67={q67:.2f}")
print(f"  {'Regime':<14} {'range (%ann)':<16} {'n':>6} {'QL_GJR':>10} "
      f"{'QL_VIX':>10} {'QL_FX':>10} {'FXvsVIX t':>11}")
for rname, lo, hi in REGIMES:
    if lo == -np.inf:
        mask_r = (oos_fxvol < hi) & both_valid
        rstr = f"<{hi:.2f}"
    elif hi == np.inf:
        mask_r = (oos_fxvol >= lo) & both_valid
        rstr = f">={lo:.2f}"
    else:
        mask_r = (oos_fxvol >= lo) & (oos_fxvol < hi) & both_valid
        rstr = f"[{lo:.2f},{hi:.2f})"
    n_r = int(mask_r.sum())
    if n_r < 30:
        print(f"  {rname:<14} {rstr:<16} insufficient (n={n_r})")
        continue
    ev = eval_losses(mask_r)
    vs_vix = pairwise_dm(ev, 'A4f_VIX')
    fx_vs_vix_t = vs_vix['A4f_FX']['dm_t_vs_A4f_VIX']
    print(f"  {rname:<14} {rstr:<16} {n_r:>6} {ev['GJR']['qlike_mean']:>10.5f} "
          f"{ev['A4f_VIX']['qlike_mean']:>10.5f} {ev['A4f_FX']['qlike_mean']:>10.5f} "
          f"{fx_vs_vix_t:+10.3f}")

    results['fx_regime'][rname] = {
        'fxvol_range': [float(lo) if np.isfinite(lo) else None,
                        float(hi) if np.isfinite(hi) else None],
        'n': n_r,
        'qlike': {k: ev[k]['qlike_mean'] for k in MODELS},
        'dm_vs_A4f_VIX': vs_vix,
    }

results['fx_regime_terciles'] = {'q33': float(q33), 'q67': float(q67)}

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS + PAPER 10 ASSESSMENT
# ============================================================
print("\n" + "=" * 72)
print("HYPOTHESIS VERDICTS")
print("=" * 72)

full = results.get('full_oos', {})
if full:
    # H1: A4f-FXVol vs GJR
    fx_vs_gjr = full['dm_vs_GJR'].get('A4f_FX', {})
    t1 = fx_vs_gjr.get('dm_t_vs_GJR')
    d1 = fx_vs_gjr.get('qlike_diff_pct_vs_GJR')
    if t1 is not None:
        h1_verdict = 'PASS' if (abs(t1) > 3.0 and t1 > 0) else 'FAIL'
        print(f"  H1 (A4f-FXVol Harvey-PASS vs GJR):     {h1_verdict} "
              f"(t={t1:+.3f}, diff={d1:+.2f}%)")
    else:
        h1_verdict = 'N/A'
        print(f"  H1: N/A")

    # H2: A4f-FXVol vs A4f-VIX
    fx_vs_vix = full['dm_vs_A4f_VIX'].get('A4f_FX', {})
    t2 = fx_vs_vix.get('dm_t_vs_A4f_VIX')
    d2 = fx_vs_vix.get('qlike_diff_pct_vs_A4f_VIX')
    if t2 is not None:
        if abs(t2) > 3.0:
            h2_verdict = 'FX_BETTER' if t2 > 0 else 'VIX_BETTER'
        else:
            h2_verdict = 'INDIFFERENT'
        print(f"  H2 (A4f-FXVol vs A4f-VIX):             {h2_verdict} "
              f"(t={t2:+.3f}, diff={d2:+.2f}%)")
    else:
        h2_verdict = 'N/A'
        print(f"  H2: N/A")

    # H3: COMBO dominates both solos
    combo_vs_vix = full['dm_vs_A4f_VIX'].get('A4f_COMBO', {})
    combo_vs_fx = full['dm_vs_A4f_FX'].get('A4f_COMBO', {})
    t3a = combo_vs_vix.get('dm_t_vs_A4f_VIX')
    t3b = combo_vs_fx.get('dm_t_vs_A4f_FX')
    if t3a is not None and t3b is not None:
        if t3a > 3.0 and t3b > 3.0:
            h3_verdict = 'PASS'
        elif t3a > 0 and t3b > 0:
            h3_verdict = 'MARGINAL'
        else:
            h3_verdict = 'FAIL'
        print(f"  H3 (COMBO dominates VIX and FX):       {h3_verdict} "
              f"(t vs VIX={t3a:+.3f}, t vs FX={t3b:+.3f})")
    else:
        h3_verdict = 'N/A'
        print(f"  H3: N/A")

    # H4: High-FXVol regime: FX strictly better than VIX
    high_reg = results['fx_regime'].get('High_FXVol', {})
    if high_reg:
        hr_fx_vs_vix = high_reg['dm_vs_A4f_VIX'].get('A4f_FX', {})
        t4 = hr_fx_vs_vix.get('dm_t_vs_A4f_VIX')
        d4 = hr_fx_vs_vix.get('qlike_diff_pct_vs_A4f_VIX')
        if t4 is not None:
            if t4 > 3.0:
                h4_verdict = 'PASS'
            elif t4 > 0:
                h4_verdict = 'MARGINAL'
            else:
                h4_verdict = 'FAIL'
            print(f"  H4 (High-FXVol: FX > VIX):             {h4_verdict} "
                  f"(t={t4:+.3f}, diff={d4:+.2f}%)")
        else:
            h4_verdict = 'N/A'
    else:
        h4_verdict = 'N/A'
        print(f"  H4: N/A")

    results['hypothesis_verdicts'] = {
        'H1_a4ffx_vs_gjr_harvey_pass': h1_verdict,
        'H2_a4ffx_vs_a4fvix': h2_verdict,
        'H3_combo_dominates_both': h3_verdict,
        'H4_high_fxvol_fx_beats_vix': h4_verdict,
    }

    # Paper 10 revival assessment
    revival = (h1_verdict == 'PASS' or h2_verdict == 'FX_BETTER'
               or h3_verdict in ('PASS', 'MARGINAL')
               or h4_verdict in ('PASS', 'MARGINAL'))
    results['paper10_revival_assessment'] = {
        'revival_warranted': bool(revival),
        'notes': (
            "Revival warranted if ANY of: (a) A4f-FXVol Harvey-PASS full OOS, "
            "(b) A4f-FXVol beats A4f-VIX full OOS, (c) COMBO dominates at least "
            "marginally, or (d) High-FXVol regime shows FX>VIX at least marginally. "
            "If all four fail, Taiwan is structurally unrescuable for A4f—even FX "
            "realized vol (the supposed root cause) cannot restore transmission."
        )
    }

# K1077 comparison (for reporting)
results['k1077_comparison'] = {
    'k1077_a4fvix_full_dm_t_vs_gjr': -0.488,  # from k1077_results.json
    'k1077_full_qlike_diff_pct': 0.332,
    'k1099_a4fvix_full_dm_t_vs_gjr': (full['dm_vs_GJR'].get('A4f_VIX', {})
                                       .get('dm_t_vs_GJR') if full else None),
    'note': ("K1099 replicates K1077's A4f-VIX as internal sanity check; "
             "values should be close though not identical (FX data requirement "
             "restricts sample slightly).")
}

# ============================================================
# SECTION 7: SAVE RESULTS
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': '0050.TW',
    'regressors': {
        'VIX': '^VIX (CBOE, forward-filled to TW trading days)',
        'FXVOL_RV21': f'TWDUSD=X {FXVOL_WINDOW}-day realized vol, annualized %',
        'FXVOL_EWMA': f'TWDUSD=X EWMA λ={EWMA_LAMBDA} realized vol, annualized %',
    },
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'fxvol_window': FXVOL_WINDOW,
    'ewma_lambda': EWMA_LAMBDA,
    'random_seed': 42,
    'n_total': int(n_total),
    'n_oos_actual': int(n_oos),
    'n_both_valid': int(n_both),
    'n_refits': int(refit_count),
    'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
    'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': time.time() - START_TIME,
    'references': [
        'Engle, Ghysels, Sohn (2013) RES 95(3):776-797',
        'Conrad & Loch (2015) JBES',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey, Leybourne, Whitehouse (2016)',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to: {RESULTS_PATH}")

# ============================================================
# SECTION 8: FIGURES
# ============================================================
print("\n[8] Generating figures...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Figure 1: DM comparison bar chart (4 models, 3 benchmarks visible via grid)
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

models_ordered = ['A4f_VIX', 'A4f_FX', 'A4f_COMBO']
colors = ['#4E79A7', '#59A14F', '#E15759']

# Left: DM vs GJR
if full:
    vals_gjr = [full['dm_vs_GJR'][k]['dm_t_vs_GJR'] for k in models_ordered]
    bars = axes[0].bar(models_ordered, vals_gjr, color=colors)
    for bar, v in zip(bars, vals_gjr):
        axes[0].annotate(f"{v:+.2f}", xy=(bar.get_x() + bar.get_width()/2,
                         v), ha='center',
                         va='bottom' if v >= 0 else 'top',
                         fontsize=10)
    axes[0].axhline(3.0, linestyle='--', color='red', alpha=0.5, label='Harvey |t|=3')
    axes[0].axhline(-3.0, linestyle='--', color='red', alpha=0.5)
    axes[0].axhline(0, linestyle='-', color='black', alpha=0.3, linewidth=0.5)
    axes[0].set_title('Full OOS DM t (vs GJR baseline)', fontsize=12)
    axes[0].set_ylabel('DM HAC t-statistic')
    axes[0].legend(loc='best')
    axes[0].grid(alpha=0.3, axis='y')

    # Right: DM vs A4f_VIX
    vals_vix = [full['dm_vs_A4f_VIX'][k]['dm_t_vs_A4f_VIX']
                for k in ['A4f_FX', 'A4f_COMBO']]
    bars = axes[1].bar(['A4f_FX', 'A4f_COMBO'], vals_vix, color=['#59A14F', '#E15759'])
    for bar, v in zip(bars, vals_vix):
        axes[1].annotate(f"{v:+.2f}", xy=(bar.get_x() + bar.get_width()/2,
                         v), ha='center',
                         va='bottom' if v >= 0 else 'top',
                         fontsize=10)
    axes[1].axhline(3.0, linestyle='--', color='red', alpha=0.5, label='Harvey |t|=3')
    axes[1].axhline(-3.0, linestyle='--', color='red', alpha=0.5)
    axes[1].axhline(0, linestyle='-', color='black', alpha=0.3, linewidth=0.5)
    axes[1].set_title('Full OOS DM t (vs A4f_VIX; K1077 replication)', fontsize=12)
    axes[1].set_ylabel('DM HAC t-statistic')
    axes[1].legend(loc='best')
    axes[1].grid(alpha=0.3, axis='y')

fig.suptitle('K1099: 0050.TW A4f with USD/TWD FX Realized Vol — DM Comparison',
             fontsize=13, y=1.02)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k1099_dm_comparison.png'), dpi=120,
            bbox_inches='tight')
plt.close(fig)
print(f"  Saved: k1099_dm_comparison.png")

# Figure 2: FXVol time series with regime bands
fig, ax = plt.subplots(figsize=(14, 5))
ax.plot(df.index, df['FXVOL_RV21'], color='#59A14F', alpha=0.75,
        label='FXVOL_RV21 (21-day)', linewidth=0.9)
ax.plot(df.index, df['FXVOL_EWMA'], color='#E15759', alpha=0.6,
        label=f'FXVOL_EWMA (λ={EWMA_LAMBDA})', linewidth=0.9)
ax.axhline(q33, color='gray', linestyle='--', alpha=0.6, label=f'OOS q33={q33:.1f}')
ax.axhline(q67, color='black', linestyle='--', alpha=0.6, label=f'OOS q67={q67:.1f}')
# Shade each crisis period
for cname, cstart, cend in CRISIS_PERIODS:
    ax.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
               color='yellow', alpha=0.18)
ax.set_title('K1099: TWDUSD Realized Volatility (annualized %, 2005-2025)',
             fontsize=12)
ax.set_ylabel('Annualized FX volatility (%)')
ax.legend(loc='upper right')
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k1099_fxvol_ts.png'), dpi=120,
            bbox_inches='tight')
plt.close(fig)
print(f"  Saved: k1099_fxvol_ts.png")

# Figure 3: Regime analysis — QLIKE by FX regime, for all 4 models
fig, ax = plt.subplots(figsize=(11, 5.5))
regimes_plot = [r for r in ['Low_FXVol', 'Mid_FXVol', 'High_FXVol']
                if r in results['fx_regime']]
if regimes_plot:
    x = np.arange(len(regimes_plot))
    w = 0.2
    model_order = ['GJR', 'A4f_VIX', 'A4f_FX', 'A4f_COMBO']
    model_colors = ['#BDC3C7', '#4E79A7', '#59A14F', '#E15759']
    for j, mk in enumerate(model_order):
        ys = [results['fx_regime'][r]['qlike'][mk] for r in regimes_plot]
        ax.bar(x + (j - 1.5) * w, ys, w, label=mk, color=model_colors[j])
    ax.set_xticks(x)
    ax.set_xticklabels(regimes_plot)
    ax.set_ylabel('Mean QLIKE (lower is better)')
    ax.set_title('K1099: QLIKE by FX Regime (OOS FXVOL_RV21 terciles)',
                 fontsize=12)
    ax.legend(loc='best', ncol=4, fontsize=9)
    ax.grid(alpha=0.3, axis='y')

    # Annotate: FX vs VIX DM t per regime
    note_y = ax.get_ylim()[1] * 0.97
    for i, r in enumerate(regimes_plot):
        dm_t = (results['fx_regime'][r]['dm_vs_A4f_VIX']
                .get('A4f_FX', {}).get('dm_t_vs_A4f_VIX'))
        if dm_t is not None:
            ax.annotate(f"FX vs VIX t={dm_t:+.2f}", xy=(i, note_y),
                        ha='center', fontsize=9,
                        color='darkred' if abs(dm_t) > 3 else 'dimgray')
fig.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k1099_regime_analysis.png'), dpi=120,
            bbox_inches='tight')
plt.close(fig)
print(f"  Saved: k1099_regime_analysis.png")

print("\n" + "=" * 72)
total_elapsed = time.time() - START_TIME
print(f"K1099 DONE — elapsed {total_elapsed:.0f}s = {total_elapsed/60:.1f} min")
print("=" * 72)
