#!/usr/bin/env python3
"""
K1083: 0050.TW × Synthetic USD — Isolating Pure Currency Effect on A4f
======================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K1077 tested 0050.TW (TWD) and reported A4f DM t=-0.49 NS.
  K1082 (implied) tested EWT (Taiwan USD ETF) and reported DM t=+2.26 (marginal).
  The +2.75 t-unit gap combines two effects:
    (a) Currency wrapper: TWD return vs USD-equivalent return
    (b) Composition: EWT holds MSCI Taiwan (includes ADRs), 0050.TW is pure
        listed TWSE top-50.

  K1083 isolates (a) by constructing a synthetic USD return on the SAME
  0050.TW basket:
      r_0050_USD_synth_t = r_0050_TWD_t + r_FX_t
  where TWDUSD=X (Yahoo) quotes USD per TWD (~0.032), so when TWD
  appreciates, a USD investor gains on top of the TWD-denominated asset
  return. Derivation: P_USD = P_TWD × (USD per TWD) ⇒ r_USD = r_TWD + r_FX.

Research Questions:
  H1: 0050.TW-USD-synth A4f DM t ≈ EWT +2.26?  (pure currency hypothesis)
  H2: Currency effect = DM(0050-USD) - DM(0050-TWD) ≈ +2.75?
  H3: If 0050-USD still FAIL Harvey → TSMC/TWSE concentration is binding
  H4: If 0050-USD > EWT → 0050 basket is "purer" than EWT (ADR dilution)

Design:
  - SAME 0050.TW basket, two return series: TWD vs USD-synthetic
  - GJR baseline vs A4f (VIX^2, free omega) on each return series
  - Three non-overlapping OOS windows (2010-2014, 2015-2019, 2020-2025),
    aligned with K1075/K1077
  - Rolling w=2000, refit 63d, seed 42
  - Patton (2011) QLIKE on r², Harvey (2016) DM t>3 threshold
  - Decomposition bars: TWD | USD-synth | EWT | EEM | SPY

FX sign unit test:
  TWDUSD=X = 0.0326 on day t-1, 0.0336 on day t
  ⇒ r_FX = log(0.0336/0.0326) > 0 (TWD appreciated, USD investor gains)
  ⇒ r_USD_synth = r_TWD + r_FX (both contribute)

Data: yfinance 0050.TW + ^VIX + TWDUSD=X, 2005-2026, cleaned via clean_tw50_data
Evaluation: QLIKE on r², DM test (Harvey 2016, |t|>3.0), Spearman
References:
  - Engle et al. (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). Testing equality of MSEs.
  - K1075 SPY DM +7.92; K1077 0050-TWD DM -0.49; K1082 EWT DM +2.26.

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1083
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
EXPERIMENT_ID = "K1083"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data  # MANDATORY for 0050.TW

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1083_results.json')

DATA_START = '2005-07-01'
DATA_END = '2025-12-31'
WINDOW = 2000
REFIT_EVERY = 63

OOS_WINDOWS = [
    ('Early_2010_2014', '2010-01-01', '2014-12-31'),
    ('Middle_2015_2019', '2015-01-01', '2019-12-31'),
    ('Late_2020_2025', '2020-01-01', '2025-12-31'),
]

CRISIS_PERIODS = [
    ('Euro_Crisis_2011', '2011-06-01', '2012-06-30'),
    ('TradeWar_2018_2019', '2018-01-01', '2019-12-31'),
    ('COVID_2020', '2020-02-01', '2020-06-30'),
    ('Bear_2022', '2022-01-01', '2022-12-31'),
]

VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

print("=" * 72)
print(f"{EXPERIMENT_ID}: 0050.TW × Synthetic USD — Isolating Pure Currency Effect")
print(f"  Same basket, two returns (TWD vs USD-synth), A4f vs GJR")
print(f"  3 OOS windows, 4 crisis sub-periods, 5 VIX buckets")
print("=" * 72)

# ============================================================
# SECTION 0: FX SIGN CONVENTION UNIT TEST
# ============================================================
print("\n[0] FX sign convention unit test...")
# TWDUSD=X quotes USD per TWD (values ~0.032)
# If TWDUSD rises, TWD appreciates vs USD (1 TWD buys more USD)
# USD investor in TWD-denominated asset: gains when TWD appreciates
# Derivation: P_USD_t = P_TWD_t × FX_t (FX = USD/TWD)
#   r_USD = log(P_USD_t / P_USD_{t-1})
#         = log(P_TWD_t / P_TWD_{t-1}) + log(FX_t / FX_{t-1})
#         = r_TWD + r_FX
fx_prev, fx_now = 0.0326, 0.0336  # TWD appreciates
p_tw_prev, p_tw_now = 100.0, 100.0  # TWD price unchanged
r_tw_test = np.log(p_tw_now / p_tw_prev)
r_fx_test = np.log(fx_now / fx_prev)
r_usd_test = r_tw_test + r_fx_test
# When TWD stock flat but TWD appreciates, USD investor should gain
assert r_tw_test == 0.0, "TWD stock return should be 0"
assert r_fx_test > 0, "FX return should be positive when TWD appreciates"
assert r_usd_test > 0, "USD-synth return should be positive (gain from FX only)"
print(f"  Unit test PASS: FX appreciation only → r_USD = +{r_usd_test:.6f} ✓")
print(f"  Sign convention: r_USD_synth = r_TWD + r_FX (TWDUSD=X as USD/TWD)")

# ============================================================
# SECTION 1: DATA LOADING
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

# --- Yahoo FX data quality fix ---
# Known glitches: Close gets corrupted (~10-20x normal) on random days while
# High/Low stay accurate. Detect and repair using High/Low median.
# Normal range for TWDUSD=X (USD/TWD): 0.028 - 0.037.
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
                print(f"    {d.strftime('%Y-%m-%d')}: Close={orig:.5f} → repaired to "
                      f"(H+L)/2 = {fixed:.5f}")
                fx_close.loc[d] = fixed
                continue
        # Fallback: mark NaN, will be forward-filled below
        print(f"    {d.strftime('%Y-%m-%d')}: Close={orig:.5f} → set to NaN (will ffill)")
        fx_close.loc[d] = np.nan
    # Re-verify
    residual_bad = ((fx_close.dropna() > 0.05) | (fx_close.dropna() < 0.02)).sum()
    print(f"  [FX cleanup] After repair: residual bad={int(residual_bad)}")

fx_ffill = fx_close.reindex(prices_tw.index, method='ffill')

# Verify FX value range (sanity check)
fx_valid = fx_ffill.dropna()
fx_min, fx_max = float(fx_valid.min()), float(fx_valid.max())
print(f"  TWDUSD=X range after cleanup: [{fx_min:.5f}, {fx_max:.5f}]")
assert 0.02 < fx_min < 0.05 and 0.02 < fx_max < 0.05, \
    f"TWDUSD=X still not in expected USD/TWD range; got [{fx_min}, {fx_max}]"

# Compute FX log return
log_ret_fx = np.log(fx_ffill / fx_ffill.shift(1))

# Synthetic USD return
log_ret_tw_usd = log_ret_tw + log_ret_fx

df = pd.DataFrame({
    'price': prices_tw,
    'log_ret_twd': log_ret_tw,
    'log_ret_fx': log_ret_fx,
    'log_ret_usd': log_ret_tw_usd,
    'VIX': vix_ffill,
    'fx': fx_ffill,
})
df = df.dropna()

# Safety net: drop extreme returns (>30% daily) in either series
max_abs_twd = df['log_ret_twd'].abs().max()
max_abs_usd = df['log_ret_usd'].abs().max()
if max_abs_twd > 0.3 or max_abs_usd > 0.3:
    mask_bad = (df['log_ret_twd'].abs() > 0.3) | (df['log_ret_usd'].abs() > 0.3)
    for d in df[mask_bad].index:
        print(f"    Suspicious return on {d.strftime('%Y-%m-%d')}: "
              f"TWD={df.loc[d, 'log_ret_twd']:.4f}, USD={df.loc[d, 'log_ret_usd']:.4f}")
    df = df[~mask_bad]

n_total = len(df)
print(f"  Full data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  Max |log_ret_twd|: {df['log_ret_twd'].abs().max():.4f}")
print(f"  Max |log_ret_usd|: {df['log_ret_usd'].abs().max():.4f}")

ret_twd = df['log_ret_twd'].values
ret_usd = df['log_ret_usd'].values
ret_fx = df['log_ret_fx'].values
vix = df['VIX'].values
r2_twd = ret_twd ** 2
r2_usd = ret_usd ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics (TWD vs USD-synthetic)...")
print(f"  Full sample:")
print(f"    r_TWD mean (ann):   {np.mean(ret_twd)*252:+.4f}")
print(f"    r_TWD std (ann):    {np.std(ret_twd)*np.sqrt(252):.4f}")
print(f"    r_USD mean (ann):   {np.mean(ret_usd)*252:+.4f}")
print(f"    r_USD std (ann):    {np.std(ret_usd)*np.sqrt(252):.4f}")
print(f"    r_FX  mean (ann):   {np.mean(ret_fx)*252:+.4f}")
print(f"    r_FX  std (ann):    {np.std(ret_fx)*np.sqrt(252):.4f}")
print(f"    FX contribution:    +{(np.std(ret_usd) - np.std(ret_twd))*np.sqrt(252):+.4f} vol (ann)")
print(f"    Skew TWD: {stats.skew(ret_twd):+.3f}, USD: {stats.skew(ret_usd):+.3f}")
print(f"    Kurt TWD: {stats.kurtosis(ret_twd):+.3f}, USD: {stats.kurtosis(ret_usd):+.3f}")
print(f"    Corr(r_TWD, r_FX):  {np.corrcoef(ret_twd, ret_fx)[0,1]:+.4f}")

try:
    from statsmodels.tsa.stattools import adfuller
    adf_twd = adfuller(ret_twd, maxlag=10, autolag='AIC')
    adf_usd = adfuller(ret_usd, maxlag=10, autolag='AIC')
    print(f"    ADF r_TWD: stat={adf_twd[0]:.3f}, p={adf_twd[1]:.4f}")
    print(f"    ADF r_USD: stat={adf_usd[0]:.3f}, p={adf_usd[1]:.4f}")
except Exception as e:
    print(f"    ADF skipped: {e}")

try:
    from statsmodels.stats.diagnostic import het_arch
    arch_twd = het_arch(ret_twd, nlags=5)
    arch_usd = het_arch(ret_usd, nlags=5)
    print(f"    ARCH-LM(5) r_TWD: stat={arch_twd[0]:.1f}, p={arch_twd[1]:.4f}")
    print(f"    ARCH-LM(5) r_USD: stat={arch_usd[0]:.1f}, p={arch_usd[1]:.4f}")
except Exception as e:
    print(f"    ARCH-LM skipped: {e}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS (identical to K1075/K1077)
# ============================================================
print("\n[3] Model implementations...")


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


def fit_a4f(returns, vix_vals):
    """A4f: tau_t = theta0 + theta1·VIX²_{t-1}, g_t GJR, sigma² = tau·g."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix_lag_sq = vix_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)
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
    vix2_mean = np.mean(vix_lag_sq) + 1e-8
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2), (1e-10, 1e-2), (1e-6, 1.0),
        (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999),
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
# SECTION 4: OOS FORECASTING for BOTH return series
# ============================================================
print("\n[4] Out-of-sample forecasting...")

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

for name, start, end in OOS_WINDOWS:
    start_hits = np.where(dates >= start)[0]
    if len(start_hits) == 0:
        continue
    start_idx = start_hits[0]
    print(f"    {name}: start_idx={start_idx}, window_required={WINDOW}, "
          f"sufficient={'YES' if start_idx >= WINDOW else 'NO'}")


def run_oos_pipeline(ret_series, label):
    """Run GJR vs A4f OOS for a given return series."""
    print(f"\n  >>> Running OOS for {label} ...")
    gjr_fc = np.full(n_oos_actual, np.nan)
    a4f_fc = np.full(n_oos_actual, np.nan)

    refit_log_local = []

    gjr_h = None
    gjr_params = None
    a4f_g = None
    a4f_params = None

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
            train_ret = ret_series[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]

            gjr_p, gjr_conv = fit_gjr(train_ret)
            if gjr_p is not None:
                gjr_params = gjr_p
                h = np.var(train_ret[:min(250, len(train_ret))])
                for i in range(1, len(train_ret)):
                    h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
                gjr_h = h
            else:
                gjr_conv = False

            a4f_p, a4f_conv = fit_a4f(train_ret, train_vix)
            if a4f_p is not None:
                a4f_params = a4f_p
                theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_p
                vix_lag_tr = np.empty(len(train_vix))
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                tau_tr = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)
                persist = alpha_p + gamma_p / 2.0 + beta_p
                g = omega_g / (1.0 - persist)
                for i in range(1, len(train_ret)):
                    u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)
                a4f_g = g
            else:
                a4f_conv = False

            refit_log_local.append({
                'date': dates[abs_idx].strftime('%Y-%m-%d'),
                'window': current_window,
                'gjr_conv': bool(gjr_conv),
                'a4f_conv': bool(a4f_conv),
                'a4f_theta0': float(a4f_params[0]) if a4f_params is not None else None,
                'a4f_theta1': float(a4f_params[1]) if a4f_params is not None else None,
                'a4f_omega': float(a4f_params[2]) if a4f_params is not None else None,
                'a4f_persist': float(a4f_params[3] + a4f_params[4]/2 + a4f_params[5])
                               if a4f_params is not None else None,
            })

            if refit_count % 10 == 0:
                elapsed = time.time() - START_TIME
                print(f"      Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                      f"({current_window}), elapsed {elapsed:.0f}s")

        if gjr_params is not None:
            r_prev = ret_series[abs_idx - 1]
            h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
            gjr_fc[t_idx] = h_new
            gjr_h = h_new

        if a4f_params is not None:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
            v_lag = vix[abs_idx - 1]
            tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)
            r_prev = ret_series[abs_idx - 1]
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
            g_new = max(g_new, 1e-10)
            a4f_fc[t_idx] = tau_t * g_new
            a4f_g = g_new

        prev_window = current_window

    elapsed = time.time() - START_TIME
    print(f"      {label} complete in {elapsed:.0f}s, {refit_count} refits")
    return gjr_fc, a4f_fc, refit_log_local, refit_count


gjr_fc_twd, a4f_fc_twd, refit_log_twd, n_refit_twd = run_oos_pipeline(ret_twd, "TWD series")
gjr_fc_usd, a4f_fc_usd, refit_log_usd, n_refit_usd = run_oos_pipeline(ret_usd, "USD-synth series")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_dates = dates[oos_indices]
oos_r2_twd = r2_twd[oos_indices]
oos_r2_usd = r2_usd[oos_indices]
oos_vix = vix[oos_indices]
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
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


def evaluate_series(gjr_fc, a4f_fc, r2_v, label):
    """Full evaluation for a (gjr_fc, a4f_fc, r2) triple."""
    both_valid = (~np.isnan(gjr_fc) & (gjr_fc > 0) &
                  ~np.isnan(a4f_fc) & (a4f_fc > 0))
    n_both = int(both_valid.sum())
    out = {'label': label, 'n': n_both}

    if n_both < 30:
        out['status'] = 'insufficient'
        return out, both_valid

    fc_g = gjr_fc[both_valid]
    fc_a = a4f_fc[both_valid]
    r2_k = r2_v[both_valid]

    ql_g = float(np.mean(qlike_loss(fc_g, r2_k)))
    ql_a = float(np.mean(qlike_loss(fc_a, r2_k)))

    loss_g = qlike_loss(fc_g, r2_k)
    loss_a = qlike_loss(fc_a, r2_k)
    d = loss_g - loss_a  # positive => A4f better

    dm_t, dm_p, _ = hac_dm_test(d)
    ci_lo, ci_hi = bootstrap_ci_mean_diff(d, n_boot=1000)

    rho_g, _ = stats.spearmanr(fc_g, r2_k)
    rho_a, _ = stats.spearmanr(fc_a, r2_k)

    out.update({
        'qlike_gjr': ql_g,
        'qlike_a4f': ql_a,
        'qlike_diff_pct': (ql_a - ql_g) / abs(ql_g) * 100,
        'dm_t': dm_t,
        'dm_p': dm_p,
        'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
        'spearman_gjr': float(rho_g),
        'spearman_a4f': float(rho_a),
        'bootstrap_ci_95': [ci_lo, ci_hi],
    })
    return out, both_valid


results = {'metadata': {}, 'fx_sign_test': {}, 'diagnostics': {},
           'full_oos': {}, 'per_window': {}, 'crisis_subperiods': {},
           'vix_buckets': {},
           'refit_log_twd': refit_log_twd, 'refit_log_usd': refit_log_usd}

# ---------- Full OOS for both series ----------
twd_full, twd_valid = evaluate_series(gjr_fc_twd, a4f_fc_twd, oos_r2_twd, 'TWD')
usd_full, usd_valid = evaluate_series(gjr_fc_usd, a4f_fc_usd, oos_r2_usd, 'USD_synth')

results['full_oos']['TWD'] = twd_full
results['full_oos']['USD_synth'] = usd_full

print(f"\n  FULL OOS Comparison (n_TWD={twd_full['n']}, n_USD={usd_full['n']}):")
print(f"    TWD     : QL_GJR={twd_full['qlike_gjr']:.6f}  QL_A4f={twd_full['qlike_a4f']:.6f}  "
      f"Diff={twd_full['qlike_diff_pct']:+.2f}%  DM t={twd_full['dm_t']:+.3f}  "
      f"Harvey={'PASS' if twd_full['harvey_pass'] else 'FAIL'}")
print(f"    USD_syn : QL_GJR={usd_full['qlike_gjr']:.6f}  QL_A4f={usd_full['qlike_a4f']:.6f}  "
      f"Diff={usd_full['qlike_diff_pct']:+.2f}%  DM t={usd_full['dm_t']:+.3f}  "
      f"Harvey={'PASS' if usd_full['harvey_pass'] else 'FAIL'}")

# ---------- Per-window ----------
print("\n  Per-window results:")
print(f"  {'Window':<22} {'Ret':<10} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
for name, start, end in OOS_WINDOWS:
    mask_win = (oos_window_tags == name)
    for lbl, gjr_fc, a4f_fc, r2_v in [
        ('TWD', gjr_fc_twd, a4f_fc_twd, oos_r2_twd),
        ('USD_synth', gjr_fc_usd, a4f_fc_usd, oos_r2_usd),
    ]:
        valid = (~np.isnan(gjr_fc) & (gjr_fc > 0) &
                 ~np.isnan(a4f_fc) & (a4f_fc > 0))
        mask = mask_win & valid
        n_w = int(mask.sum())
        if n_w < 30:
            continue
        fc_g = gjr_fc[mask]
        fc_a = a4f_fc[mask]
        r2_k = r2_v[mask]
        ql_g = float(np.mean(qlike_loss(fc_g, r2_k)))
        ql_a = float(np.mean(qlike_loss(fc_a, r2_k)))
        d = qlike_loss(fc_g, r2_k) - qlike_loss(fc_a, r2_k)
        dm_t, dm_p, _ = hac_dm_test(d)
        ci_lo, ci_hi = bootstrap_ci_mean_diff(d, n_boot=1000)
        rho_g, _ = stats.spearmanr(fc_g, r2_k)
        rho_a, _ = stats.spearmanr(fc_a, r2_k)
        harvey = abs(dm_t) > 3.0 if np.isfinite(dm_t) else False
        diff_pct = (ql_a - ql_g) / abs(ql_g) * 100
        print(f"  {name:<22} {lbl:<10} {n_w:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
              f"{diff_pct:>+7.2f}% {dm_t:>+8.3f} {'PASS' if harvey else 'FAIL':>8}")

        if name not in results['per_window']:
            results['per_window'][name] = {}
        results['per_window'][name][lbl] = {
            'start': start, 'end': end, 'n': n_w,
            'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
            'qlike_diff_pct': diff_pct,
            'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
            'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
            'harvey_pass': bool(harvey),
            'spearman_gjr': float(rho_g),
            'spearman_a4f': float(rho_a),
            'bootstrap_ci_95': [ci_lo, ci_hi],
        }

# ---------- Crisis sub-periods ----------
print("\n  Crisis sub-periods:")
print(f"  {'Crisis':<20} {'Ret':<10} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
for cname, cstart, cend in CRISIS_PERIODS:
    c_mask_full = (oos_dates >= cstart) & (oos_dates <= cend)
    for lbl, gjr_fc, a4f_fc, r2_v in [
        ('TWD', gjr_fc_twd, a4f_fc_twd, oos_r2_twd),
        ('USD_synth', gjr_fc_usd, a4f_fc_usd, oos_r2_usd),
    ]:
        valid = (~np.isnan(gjr_fc) & (gjr_fc > 0) &
                 ~np.isnan(a4f_fc) & (a4f_fc > 0))
        mask = c_mask_full & valid
        n_c = int(mask.sum())
        if n_c < 30:
            continue
        fc_g = gjr_fc[mask]
        fc_a = a4f_fc[mask]
        r2_k = r2_v[mask]
        ql_g = float(np.mean(qlike_loss(fc_g, r2_k)))
        ql_a = float(np.mean(qlike_loss(fc_a, r2_k)))
        d = qlike_loss(fc_g, r2_k) - qlike_loss(fc_a, r2_k)
        dm_t, dm_p, _ = hac_dm_test(d)
        diff_pct = (ql_a - ql_g) / abs(ql_g) * 100
        harvey = abs(dm_t) > 3.0 if np.isfinite(dm_t) else False
        vix_v = oos_vix[mask]
        print(f"  {cname:<20} {lbl:<10} {n_c:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
              f"{diff_pct:>+7.2f}% {dm_t:>+8.3f}")
        if cname not in results['crisis_subperiods']:
            results['crisis_subperiods'][cname] = {}
        results['crisis_subperiods'][cname][lbl] = {
            'start': cstart, 'end': cend, 'n': n_c,
            'vix_mean': float(np.mean(vix_v)), 'vix_max': float(np.max(vix_v)),
            'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
            'qlike_diff_pct': diff_pct,
            'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
            'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
            'harvey_pass': bool(harvey),
        }

# ---------- VIX buckets ----------
print("\n  VIX buckets:")
print(f"  {'Bucket':<12} {'Ret':<10} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
oos_vix_lag = np.empty(n_oos_actual)
for i, idx in enumerate(oos_indices):
    oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]

for bname, bmin, bmax in VIX_BUCKETS:
    b_mask_full = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax)
    for lbl, gjr_fc, a4f_fc, r2_v in [
        ('TWD', gjr_fc_twd, a4f_fc_twd, oos_r2_twd),
        ('USD_synth', gjr_fc_usd, a4f_fc_usd, oos_r2_usd),
    ]:
        valid = (~np.isnan(gjr_fc) & (gjr_fc > 0) &
                 ~np.isnan(a4f_fc) & (a4f_fc > 0))
        mask = b_mask_full & valid
        n_b = int(mask.sum())
        if bname not in results['vix_buckets']:
            results['vix_buckets'][bname] = {}
        if n_b < 20:
            results['vix_buckets'][bname][lbl] = {'status': 'insufficient', 'n': n_b,
                                                    'range': [bmin, bmax]}
            continue
        fc_g = gjr_fc[mask]
        fc_a = a4f_fc[mask]
        r2_k = r2_v[mask]
        ql_g = float(np.mean(qlike_loss(fc_g, r2_k)))
        ql_a = float(np.mean(qlike_loss(fc_a, r2_k)))
        d = qlike_loss(fc_g, r2_k) - qlike_loss(fc_a, r2_k)
        dm_t, dm_p, _ = hac_dm_test(d)
        diff_pct = (ql_a - ql_g) / abs(ql_g) * 100
        harvey = abs(dm_t) > 3.0 if np.isfinite(dm_t) else False
        print(f"  {bname:<12} {lbl:<10} {n_b:>6} {ql_g:>10.5f} {ql_a:>10.5f} "
              f"{diff_pct:>+7.2f}% {dm_t:>+8.3f}")
        results['vix_buckets'][bname][lbl] = {
            'range': [bmin, bmax], 'n': n_b,
            'qlike_gjr': ql_g, 'qlike_a4f': ql_a,
            'qlike_diff_pct': diff_pct,
            'dm_t': float(dm_t) if np.isfinite(dm_t) else None,
            'dm_p': float(dm_p) if np.isfinite(dm_p) else None,
            'harvey_pass': bool(harvey),
        }

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS + DECOMPOSITION
# ============================================================
print("\n" + "=" * 72)
print("HYPOTHESIS VERDICTS & CURRENCY DECOMPOSITION")
print("=" * 72)

# K1077 0050-TWD baseline (this experiment's own TWD reading)
twd_dm = twd_full.get('dm_t')
usd_dm = usd_full.get('dm_t')
ewt_dm_ref = 2.26     # K1082 (per task brief)
eem_dm_ref = 5.25     # K1081 (per task brief)
spy_dm_ref = 7.92     # K1075
k1077_dm_ref = -0.49  # K1077

# H1: 0050-USD A4f DM t ≈ EWT (+2.26)?
if np.isfinite(usd_dm):
    h1_gap = usd_dm - ewt_dm_ref
    h1_verdict = 'PASS' if abs(h1_gap) < 1.0 else 'FAIL'
    print(f"  H1 (0050-USD ≈ EWT +2.26): {h1_verdict} "
          f"(USD-synth t={usd_dm:+.3f}, gap={h1_gap:+.2f})")
else:
    h1_verdict = 'N/A'

# H2: Currency effect = DM(USD) - DM(TWD)
currency_effect = (usd_dm - twd_dm) if (np.isfinite(usd_dm) and np.isfinite(twd_dm)) else None
if currency_effect is not None:
    print(f"  H2 (Currency effect ≈ +2.75 t-unit): "
          f"DM(USD)-DM(TWD)={currency_effect:+.2f} t-unit")
    h2_verdict = 'LARGE' if currency_effect > 2.0 else \
                 ('MODEST' if currency_effect > 0.5 else 'NEGLIGIBLE')
else:
    h2_verdict = 'N/A'

# H3: 0050-USD Harvey FAIL?
if np.isfinite(usd_dm):
    h3_verdict = 'FAIL_HARVEY' if abs(usd_dm) <= 3.0 else 'PASS_HARVEY'
    print(f"  H3 (0050-USD Harvey |t|>3?): USD-synth t={usd_dm:+.3f} → {h3_verdict}")
else:
    h3_verdict = 'N/A'

# H4: 0050-USD vs EWT
if np.isfinite(usd_dm):
    composition_effect = usd_dm - ewt_dm_ref
    if abs(composition_effect) < 0.5:
        h4_verdict = '0050_USD_≈_EWT (composition effect ~0)'
    elif composition_effect > 0:
        h4_verdict = '0050_USD_>_EWT (basket purer, EWT diluted by ADRs)'
    else:
        h4_verdict = '0050_USD_<_EWT (EWT has edge)'
    print(f"  H4 (0050-USD vs EWT): 0050-USD t={usd_dm:+.3f}, "
          f"EWT t={ewt_dm_ref:+.2f}, gap={composition_effect:+.2f} → {h4_verdict}")
else:
    h4_verdict = 'N/A'

# Decomposition: currency / composition / diversification
decomposition = {
    'baseline_0050_TWD': twd_dm,
    'currency_effect': currency_effect,
    '0050_USD_synth': usd_dm,
    'composition_effect': (ewt_dm_ref - usd_dm) if np.isfinite(usd_dm) else None,
    'EWT_reference_from_K1082': ewt_dm_ref,
    'diversification_effect': eem_dm_ref - ewt_dm_ref,
    'EEM_reference_from_K1081': eem_dm_ref,
    'SPY_reference_from_K1075': spy_dm_ref,
    'K1077_reference_TWD': k1077_dm_ref,
    'note': 'Decomposition: K1077 → K1083(USD) → K1082(EWT) → K1081(EEM) → K1075(SPY)',
}

# θ₁ statistics for each series
def theta1_stats(refit_log):
    vals = [r['a4f_theta1'] for r in refit_log if r.get('a4f_theta1') is not None]
    if not vals:
        return None
    return {
        'mean': float(np.mean(vals)),
        'median': float(np.median(vals)),
        'min': float(np.min(vals)),
        'max': float(np.max(vals)),
        'n_refits': len(vals),
    }

theta1_twd = theta1_stats(refit_log_twd)
theta1_usd = theta1_stats(refit_log_usd)
print(f"\n  θ₁ statistics:")
if theta1_twd:
    print(f"    TWD:  mean={theta1_twd['mean']:.2e}, range=[{theta1_twd['min']:.2e}, {theta1_twd['max']:.2e}]")
if theta1_usd:
    print(f"    USD:  mean={theta1_usd['mean']:.2e}, range=[{theta1_usd['min']:.2e}, {theta1_usd['max']:.2e}]")

results['hypothesis_verdicts'] = {
    'H1_0050USD_approx_EWT': h1_verdict,
    'H2_currency_effect': h2_verdict,
    'H3_harvey_test_USD': h3_verdict,
    'H4_composition_effect': h4_verdict,
}
results['decomposition'] = decomposition
results['theta1_stats'] = {'TWD': theta1_twd, 'USD_synth': theta1_usd}

# ============================================================
# SECTION 7: FX CONTRIBUTION PER REFIT WINDOW
# ============================================================
print("\n[7] FX contribution per refit window...")
# For each refit date, compute local (trailing 63d) FX std and stock std
fx_contrib_log = []
for log_entry in refit_log_twd:  # align timestamps across series
    d = log_entry['date']
    try:
        d_idx = dates.get_loc(d)
        local_start = max(0, d_idx - 63)
        local_fx_std = float(np.std(ret_fx[local_start:d_idx]))
        local_twd_std = float(np.std(ret_twd[local_start:d_idx]))
        local_usd_std = float(np.std(ret_usd[local_start:d_idx]))
        fx_contrib_log.append({
            'date': d,
            'fx_std': local_fx_std,
            'twd_std': local_twd_std,
            'usd_std': local_usd_std,
            'fx_vol_share': local_fx_std / local_usd_std if local_usd_std > 0 else 0,
        })
    except (KeyError, IndexError):
        continue
results['fx_contribution_log'] = fx_contrib_log

# ============================================================
# SECTION 8: SAVE RESULTS
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': '0050.TW (same basket, TWD vs USD-synth returns)',
    'fx_ticker': 'TWDUSD=X (Yahoo quotes USD per TWD)',
    'vix_source': '^VIX (forward-filled to TW trading days)',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_total': int(n_total),
    'n_oos_actual': int(n_oos_actual),
    'n_refits_twd': int(n_refit_twd),
    'n_refits_usd': int(n_refit_usd),
    'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
    'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
    'vix_buckets': [(n, lo, hi) for n, lo, hi in VIX_BUCKETS],
    'seed': 42,
    'runtime_seconds': time.time() - START_TIME,
    'completion_utc': datetime.now(timezone.utc).isoformat(),
    'proposed_by': 'User (Paper 9 precision expansion)',
    'executed_by': 'Claude',
    'references': [
        'K1075 SPY DM t=+7.92',
        'K1077 0050-TWD DM t=-0.49 (this study re-derives for consistency)',
        'K1078 QQQ DM t=+5.99',
        'K1080 IWM DM t=+4.80',
        'K1081 EEM DM t=+5.25',
        'K1082 EWT/EWZ/FXI DM t=+2.26/+2.33/+3.61',
    ],
}
results['fx_sign_test'] = {
    'description': 'TWDUSD=X quoted as USD per TWD (values ~0.032). '
                   'When TWD appreciates (FX rises), USD investor gains. '
                   'Correct formula: r_USD_synth = r_TWD + r_FX',
    'verified_value_range': [float(df['fx'].min()), float(df['fx'].max())],
    'unit_test': {
        'case': 'FX rises 0.0326→0.0336 with TWD stock flat',
        'expected_r_USD_synth': '> 0 (gain from FX only)',
        'computed_r_USD_synth': float(r_usd_test),
        'status': 'PASS',
    },
}
results['diagnostics'] = {
    'ret_twd': {
        'mean_ann': float(np.mean(ret_twd)*252),
        'std_ann': float(np.std(ret_twd)*np.sqrt(252)),
        'skew': float(stats.skew(ret_twd)),
        'kurt': float(stats.kurtosis(ret_twd)),
    },
    'ret_usd': {
        'mean_ann': float(np.mean(ret_usd)*252),
        'std_ann': float(np.std(ret_usd)*np.sqrt(252)),
        'skew': float(stats.skew(ret_usd)),
        'kurt': float(stats.kurtosis(ret_usd)),
    },
    'ret_fx': {
        'mean_ann': float(np.mean(ret_fx)*252),
        'std_ann': float(np.std(ret_fx)*np.sqrt(252)),
        'corr_with_twd': float(np.corrcoef(ret_twd, ret_fx)[0, 1]),
    },
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

elapsed_final = time.time() - START_TIME
print(f"\n[8] Results saved: {RESULTS_PATH}")
print(f"    Total runtime: {elapsed_final:.0f}s ({elapsed_final/60:.1f} min)")
print("=" * 72)
print("K1083 COMPLETE")
print("=" * 72)
