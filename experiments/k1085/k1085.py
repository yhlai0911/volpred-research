#!/usr/bin/env python3
"""
K1085: A4f on GLD — Non-Equity Asset Class Extension of Paper 9
================================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation:
  Paper 9 cross-asset results so far are all equity ETFs (SPY, QQQ, IWM,
  EEM, EWT, EWZ, FXI, 0050.TW). The critical open question is whether
  A4f's VIX-as-tau advantage is *equity-specific* or *cross-asset general*.

  GLD (iShares Gold Trust) is the natural first test:
    - Completely different asset class (commodity, safe-haven)
    - Different vol regime mechanism (inflation, real rates, geopolitics)
    - Part of the core 50/50 SPY/GLD portfolio (K846)

  Three possible outcomes shape Paper 9's cross-asset claim:
    PASS (t>3)    → "A4f generalizes to non-equity; VIX-as-USD-funding-risk"
    Marginal      → "A4f effect attenuates; VIX is primarily equity fear"
    NULL          → "A4f is equity-specific; gold has different risk factors"

Design (align with K1075):
  - Three OOS windows: 2007-2012 (Early), 2013-2018 (Middle), 2019-2026 (Late)
  - Rolling-window GARCH, 2000-day train, 63-day refit
  - Four models: GJR, A4f-VIX, A4f-GVZ, A4f-COMBO (VIX²+GVZ²)
  - Crisis sub-periods: 2008 GFC, 2013 gold crash, 2020 COVID, 2022
  - VIX buckets: Low/Normal/High/Extreme/Crisis
  - Separate diagnostics on gold-specific events

Hypotheses:
  H1: GLD 2007-2026 A4f vs GJR DM Harvey-PASS (|t|>3)?
  H2: GLD in VIX>60 regime — does A4f advantage attenuate (safe haven)?
  H3: GLD theta1 stability vs SPY (K1075)
  H4: Gold VIX (GVZ) as regressor superior to VIX?

Data:
  - GLD daily Adj Close (yfinance, 2005-01-03 ~ 2026-04-10)
  - ^VIX daily Close (yfinance, 2005-01-03 ~)
  - ^GVZ daily Close (yfinance, 2008-06-03 ~)  — used for A4f-GVZ only
  - Note: GVZ starts 2008-06-03, so A4f-GVZ OOS begins after 2000-day window
    => Effectively A4f-GVZ has shorter history than A4f-VIX

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test with Newey-West HAC (Harvey 2016, |t|>3.0)
  - Spearman rank correlation
  - Bootstrap CI (1000 reps)

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.  [GARCH-MIDAS origin]
  - Chen & Qu (2017). GARCH-type model with VIX leading to volatility forecasting.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors.
  - Baur & McDermott (2010). Is gold a safe haven? International evidence.
  - Reboredo (2013). Is gold a safe haven or a hedge for the US dollar?

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1085
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
EXPERIMENT_ID = "K1085"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1085_results.json')

# Configuration
DATA_START = '2000-01-01'  # need pre-history for 2000-day window
DATA_END = '2026-04-11'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly

# Three non-overlapping OOS windows
OOS_WINDOWS = [
    ('Early_GFC', '2007-01-01', '2012-12-31'),         # GFC + 2011 gold peak
    ('Middle_GoldCrash', '2013-01-01', '2018-12-31'),   # 2013 crash + low-vol recovery
    ('Late_COVID', '2019-01-01', '2026-04-11'),         # COVID + Rate Hike + Ukraine
]

# Gold-specific + general crisis sub-periods
CRISIS_PERIODS = [
    ('GFC_2008', '2008-09-01', '2009-03-31'),            # Equity crisis, gold rally
    ('GoldCrash_2013', '2013-04-01', '2013-07-31'),      # Cyprus/taper, -25% in weeks
    ('COVID_2020', '2020-02-15', '2020-08-15'),          # COVID, gold-safe-haven
    ('Ukraine_2022', '2022-02-15', '2022-08-15'),        # Russia invasion, gold rally
]

# VIX buckets
VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f on GLD — Non-Equity Asset Class Extension")
print(f"  4 models (GJR, A4f-VIX, A4f-GVZ, A4f-COMBO), 3 OOS windows,")
print(f"  4 crisis sub-periods, 5 VIX buckets")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

raw = yf.download('GLD', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Adj Close'].copy() if 'Adj Close' in raw.columns else raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

gvz_raw = yf.download('^GVZ', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(gvz_raw.columns, pd.MultiIndex):
    gvz_raw.columns = gvz_raw.columns.get_level_values(0)
gvz_close = gvz_raw['Close'].copy() if len(gvz_raw) > 0 else pd.Series(dtype=float)

# Align all on GLD dates (VIX + GLD intersection for A4f-VIX)
df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close, 'GVZ': gvz_close})
df = df.dropna(subset=['price', 'log_ret', 'VIX'])  # keep rows with VIX; GVZ may be NaN

n_total = len(df)
print(f"  Full data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
gvz_avail_mask = ~df['GVZ'].isna()
print(f"  GVZ availability: {gvz_avail_mask.sum()} days "
      f"from {df.index[gvz_avail_mask][0].strftime('%Y-%m-%d') if gvz_avail_mask.any() else 'N/A'}")

ret = df['log_ret'].values
vix = df['VIX'].values
# For GVZ use forward-fill then back-fill for pre-2008 (will only be used when GVZ is present)
gvz = df['GVZ'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
print(f"  Full sample GLD:")
print(f"    Return mean (ann): {np.mean(ret)*252:.4f}")
print(f"    Return std  (ann): {np.std(ret)*np.sqrt(252):.4f}")
print(f"    Return skew:      {stats.skew(ret):.3f}")
print(f"    Return kurt:      {stats.kurtosis(ret):.3f}")
print(f"    VIX mean/max: {np.mean(vix):.2f} / {np.max(vix):.2f}")
if gvz_avail_mask.any():
    gvz_valid = gvz[gvz_avail_mask]
    print(f"    GVZ mean/max: {np.mean(gvz_valid):.2f} / {np.max(gvz_valid):.2f}")

for name, start, end in OOS_WINDOWS:
    mask = (dates >= start) & (dates <= end)
    n_w = mask.sum()
    vix_w = vix[mask]
    ret_w = ret[mask]
    print(f"  {name} ({start} to {end}): n={n_w}, VIX max={np.max(vix_w):.1f}, "
          f"ret std={np.std(ret_w)*np.sqrt(252):.3f}")

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


# --- A4f: Multiplicative GARCH-X with VIX^2 (or GVZ^2 or both) and free omega ---
def fit_a4f_single(returns, x_vals):
    """
    A4f-single: τ = θ₀ + θ₁ · X²_{t-1}
    X can be VIX or GVZ.
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
    x2_mean = np.mean(x_lag_sq) + 1e-8

    starts = [
        [var0 * 0.1, var0 / x2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-10, 1e-2),
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


def fit_a4f_combo(returns, vix_vals, gvz_vals):
    """
    A4f-combo: τ = θ₀ + θ₁·VIX²_{t-1} + θ₂·GVZ²_{t-1}
    Parameters: [theta0, theta1_vix, theta2_gvz, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    vix_lag = np.empty(n); vix_lag[0] = vix_vals[0]; vix_lag[1:] = vix_vals[:-1]
    gvz_lag = np.empty(n); gvz_lag[0] = gvz_vals[0]; gvz_lag[1:] = gvz_vals[:-1]
    vix_sq = vix_lag ** 2
    gvz_sq = gvz_lag ** 2

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_sq + theta2 * gvz_sq, 1e-16)

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
    gvz_sq_mean = np.mean(gvz_sq) + 1e-8

    starts = [
        [var0 * 0.1, var0 / vix_sq_mean * 0.5, var0 / gvz_sq_mean * 0.5, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix_sq_mean * 0.3, var0 / gvz_sq_mean * 0.3, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix_sq_mean * 0.7, var0 / gvz_sq_mean * 0.7, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),  # theta0
        (0, 1e-2),      # theta1 (VIX coefficient, nonneg)
        (0, 1e-2),      # theta2 (GVZ coefficient, nonneg)
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
print("\n[4] Out-of-sample forecasting (3 windows, 4 models)...")

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
    start_idx = np.where(dates >= start)[0][0]
    print(f"    {name}: start_idx={start_idx}, window_required={WINDOW}, "
          f"sufficient={'YES' if start_idx >= WINDOW else 'NO'}")

# Forecast arrays — 4 models
gjr_fc = np.full(n_oos_actual, np.nan)
a4f_vix_fc = np.full(n_oos_actual, np.nan)
a4f_gvz_fc = np.full(n_oos_actual, np.nan)
a4f_combo_fc = np.full(n_oos_actual, np.nan)

# Refit logs
refit_log = []

# States
gjr_h = None; gjr_params = None
a4f_vix_g = None; a4f_vix_params = None
a4f_gvz_g = None; a4f_gvz_params = None
a4f_combo_g = None; a4f_combo_params = None

prev_window = None
refit_count = 0

# Helper: initialize states from training via filtering recursion
def init_a4f_state(train_ret, x_vals, params, regressor='single'):
    """Run filter on training to get final g."""
    if regressor == 'single':
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params
        x_lag = np.empty(len(x_vals)); x_lag[0] = x_vals[0]; x_lag[1:] = x_vals[:-1]
        tau = np.maximum(theta0 + theta1 * x_lag**2, 1e-16)
    elif regressor == 'combo':
        theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = params
        vix_v, gvz_v = x_vals
        vix_lag = np.empty(len(vix_v)); vix_lag[0] = vix_v[0]; vix_lag[1:] = vix_v[:-1]
        gvz_lag = np.empty(len(gvz_v)); gvz_lag[0] = gvz_v[0]; gvz_lag[1:] = gvz_v[:-1]
        tau = np.maximum(theta0 + theta1 * vix_lag**2 + theta2 * gvz_lag**2, 1e-16)

    persist = alpha_p + gamma_p / 2.0 + beta_p
    g = omega_g / (1.0 - persist)
    for i in range(1, len(train_ret)):
        u_prev = train_ret[i-1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
        g = max(g, 1e-10)
    return g


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
        train_gvz = gvz[train_start:abs_idx]

        # Determine if GVZ is available across the full training window
        gvz_sufficient = np.sum(~np.isnan(train_gvz)) >= len(train_gvz) * 0.9
        gvz_for_train = np.where(np.isnan(train_gvz), np.nanmean(train_gvz) if gvz_sufficient else np.nan, train_gvz)

        # --- GJR fit ---
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_params = gjr_p
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h
        else:
            gjr_conv = False

        # --- A4f-VIX fit ---
        a4f_vix_p, a4f_vix_conv = fit_a4f_single(train_ret, train_vix)
        if a4f_vix_p is not None:
            a4f_vix_params = a4f_vix_p
            a4f_vix_g = init_a4f_state(train_ret, train_vix, a4f_vix_p, 'single')
        else:
            a4f_vix_conv = False

        # --- A4f-GVZ fit (only if GVZ available) ---
        if gvz_sufficient and not np.all(np.isnan(gvz_for_train)):
            a4f_gvz_p, a4f_gvz_conv = fit_a4f_single(train_ret, gvz_for_train)
            if a4f_gvz_p is not None:
                a4f_gvz_params = a4f_gvz_p
                a4f_gvz_g = init_a4f_state(train_ret, gvz_for_train, a4f_gvz_p, 'single')
            else:
                a4f_gvz_conv = False
        else:
            a4f_gvz_p = None
            a4f_gvz_conv = False
            a4f_gvz_params = None
            a4f_gvz_g = None

        # --- A4f-COMBO fit (only if GVZ available) ---
        if gvz_sufficient and not np.all(np.isnan(gvz_for_train)):
            a4f_combo_p, a4f_combo_conv = fit_a4f_combo(train_ret, train_vix, gvz_for_train)
            if a4f_combo_p is not None:
                a4f_combo_params = a4f_combo_p
                a4f_combo_g = init_a4f_state(train_ret,
                                             (train_vix, gvz_for_train),
                                             a4f_combo_p, 'combo')
            else:
                a4f_combo_conv = False
        else:
            a4f_combo_p = None
            a4f_combo_conv = False
            a4f_combo_params = None
            a4f_combo_g = None

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            'gjr_conv': bool(gjr_conv),
            'a4f_vix_conv': bool(a4f_vix_conv),
            'a4f_gvz_conv': bool(a4f_gvz_conv),
            'a4f_combo_conv': bool(a4f_combo_conv),
            'gvz_sufficient': bool(gvz_sufficient),
            'a4f_vix_theta0': float(a4f_vix_params[0]) if a4f_vix_params is not None else None,
            'a4f_vix_theta1': float(a4f_vix_params[1]) if a4f_vix_params is not None else None,
            'a4f_gvz_theta0': float(a4f_gvz_params[0]) if a4f_gvz_params is not None else None,
            'a4f_gvz_theta1': float(a4f_gvz_params[1]) if a4f_gvz_params is not None else None,
            'a4f_combo_theta1_vix': float(a4f_combo_params[1]) if a4f_combo_params is not None else None,
            'a4f_combo_theta2_gvz': float(a4f_combo_params[2]) if a4f_combo_params is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # --- Forecast generation for day abs_idx ---
    r_prev = ret[abs_idx - 1]

    # GJR
    if gjr_params is not None:
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_fc[t_idx] = h_new
        gjr_h = h_new

    # A4f-VIX
    if a4f_vix_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_vix_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_vix_g
        g_new = max(g_new, 1e-10)
        a4f_vix_fc[t_idx] = tau_t * g_new
        a4f_vix_g = g_new

    # A4f-GVZ
    if a4f_gvz_params is not None:
        gvz_prev = gvz[abs_idx - 1]
        if not np.isnan(gvz_prev):
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_gvz_params
            tau_t = max(theta0 + theta1 * gvz_prev**2, 1e-16)
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_gvz_g
            g_new = max(g_new, 1e-10)
            a4f_gvz_fc[t_idx] = tau_t * g_new
            a4f_gvz_g = g_new

    # A4f-COMBO
    if a4f_combo_params is not None:
        gvz_prev = gvz[abs_idx - 1]
        if not np.isnan(gvz_prev):
            theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = a4f_combo_params
            v_lag = vix[abs_idx - 1]
            tau_t = max(theta0 + theta1 * v_lag**2 + theta2 * gvz_prev**2, 1e-16)
            u_prev = r_prev / np.sqrt(tau_t)
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_combo_g
            g_new = max(g_new, 1e-10)
            a4f_combo_fc[t_idx] = tau_t * g_new
            a4f_combo_g = g_new

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
oos_gvz = gvz[oos_indices]
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
    """Evaluate alt vs base. positive d = alt better."""
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


results = {'metadata': {}, 'full_oos': {}, 'per_window': {},
           'crisis_subperiods': {}, 'vix_buckets': {},
           'vix_vs_gvz_compare': {}, 'refit_log': refit_log}

# --- Full OOS (union) ---
print("\n  FULL OOS (2007-2026):")
print(f"  {'Comparison':<30} {'n':>6} {'QL_base':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
for label_alt, fc_alt in [('a4f_vix', a4f_vix_fc),
                           ('a4f_gvz', a4f_gvz_fc),
                           ('a4f_combo', a4f_combo_fc)]:
    res = evaluate_pair(gjr_fc, fc_alt, oos_r2, label_alt)
    if res is None:
        print(f"  gjr vs {label_alt:<22} insufficient")
        continue
    results['full_oos'][f'gjr_vs_{label_alt}'] = res
    harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
    print(f"  gjr vs {label_alt:<22} {res['n']:>6} {res['qlike_base']:>10.5f} "
          f"{res[f'qlike_{label_alt}']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
          f"{res['dm_t']:>+8.3f} {harvey:>8}")

# --- Per OOS window ---
print("\n  Per-window results (vs GJR):")
for name, start, end in OOS_WINDOWS:
    mask = (oos_window_tags == name)
    if mask.sum() < 30:
        continue
    r2_w = oos_r2[mask]

    results['per_window'][name] = {'start': start, 'end': end}

    print(f"\n  [{name}]")
    print(f"  {'Comparison':<30} {'n':>6} {'QL_base':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")

    for label_alt, fc_alt in [('a4f_vix', a4f_vix_fc[mask]),
                               ('a4f_gvz', a4f_gvz_fc[mask]),
                               ('a4f_combo', a4f_combo_fc[mask])]:
        res = evaluate_pair(gjr_fc[mask], fc_alt, r2_w, label_alt)
        if res is None:
            continue
        results['per_window'][name][f'gjr_vs_{label_alt}'] = res
        harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
        print(f"  gjr vs {label_alt:<22} {res['n']:>6} {res['qlike_base']:>10.5f} "
              f"{res[f'qlike_{label_alt}']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
              f"{res['dm_t']:>+8.3f} {harvey:>8}")

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods (vs GJR, A4f-VIX only):")
print(f"  {'Crisis':<18} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
for cname, cstart, cend in CRISIS_PERIODS:
    c_mask_full = (oos_dates >= cstart) & (oos_dates <= cend)
    r2_c = oos_r2[c_mask_full]
    vix_c = oos_vix[c_mask_full]
    gvz_c = oos_gvz[c_mask_full]

    if c_mask_full.sum() < 30:
        print(f"  {cname:<18} insufficient (n={c_mask_full.sum()})")
        continue

    # A4f-VIX vs GJR
    res_vix = evaluate_pair(gjr_fc[c_mask_full], a4f_vix_fc[c_mask_full], r2_c, 'a4f_vix')
    # A4f-GVZ vs GJR
    res_gvz = evaluate_pair(gjr_fc[c_mask_full], a4f_gvz_fc[c_mask_full], r2_c, 'a4f_gvz')
    # A4f-COMBO vs GJR
    res_combo = evaluate_pair(gjr_fc[c_mask_full], a4f_combo_fc[c_mask_full], r2_c, 'a4f_combo')

    if res_vix is None:
        continue

    print(f"  {cname:<18} {res_vix['n']:>6} {res_vix['qlike_base']:>10.5f} "
          f"{res_vix['qlike_a4f_vix']:>10.5f} {res_vix['qlike_diff_pct']:>+7.2f}% "
          f"{res_vix['dm_t']:>+8.3f}")

    results['crisis_subperiods'][cname] = {
        'start': cstart, 'end': cend,
        'n': int(res_vix['n']),
        'vix_mean': float(np.mean(vix_c)),
        'vix_max': float(np.max(vix_c)),
        'gvz_mean': float(np.nanmean(gvz_c)) if (~np.isnan(gvz_c)).any() else None,
        'gvz_max': float(np.nanmax(gvz_c)) if (~np.isnan(gvz_c)).any() else None,
        'gjr_vs_a4f_vix': res_vix,
        'gjr_vs_a4f_gvz': res_gvz,
        'gjr_vs_a4f_combo': res_combo,
    }

# --- VIX bucket analysis (A4f-VIX vs GJR) ---
print("\n  VIX bucket analysis (A4f-VIX vs GJR):")
print(f"  {'Bucket':<12} {'Range':<15} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
oos_vix_lag = np.empty(n_oos_actual)
for i, idx in enumerate(oos_indices):
    oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]

for bname, bmin, bmax in VIX_BUCKETS:
    mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax)
    n_b = mask.sum()
    if n_b < 20:
        print(f"  {bname:<12} [{bmin},{bmax}) insufficient (n={n_b})")
        results['vix_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue

    res = evaluate_pair(gjr_fc[mask], a4f_vix_fc[mask], oos_r2[mask], 'a4f_vix')
    if res is None:
        continue

    harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
    print(f"  {bname:<12} [{bmin},{bmax})     {res['n']:>6} {res['qlike_base']:>10.5f} "
          f"{res['qlike_a4f_vix']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
          f"{res['dm_t']:>+8.3f}")
    results['vix_buckets'][bname] = {
        'range': [bmin, bmax],
        **res,
    }

# --- VIX vs GVZ head-to-head (A4f-GVZ vs A4f-VIX) ---
print("\n  VIX vs GVZ head-to-head (A4f-GVZ vs A4f-VIX):")
# restrict to subset where both available
res_headtohead = evaluate_pair(a4f_vix_fc, a4f_gvz_fc, oos_r2, 'a4f_gvz')
if res_headtohead is not None:
    results['vix_vs_gvz_compare']['a4f_vix_vs_a4f_gvz'] = res_headtohead
    harvey = 'PASS' if res_headtohead['harvey_pass'] else 'FAIL'
    print(f"  A4f-VIX (base) vs A4f-GVZ (alt): n={res_headtohead['n']}, "
          f"QL_VIX={res_headtohead['qlike_base']:.5f}, QL_GVZ={res_headtohead['qlike_a4f_gvz']:.5f}, "
          f"DM_t={res_headtohead['dm_t']:+.3f} {harvey}")

# A4f-COMBO vs A4f-VIX
res_combo_vs_vix = evaluate_pair(a4f_vix_fc, a4f_combo_fc, oos_r2, 'a4f_combo')
if res_combo_vs_vix is not None:
    results['vix_vs_gvz_compare']['a4f_vix_vs_a4f_combo'] = res_combo_vs_vix
    harvey = 'PASS' if res_combo_vs_vix['harvey_pass'] else 'FAIL'
    print(f"  A4f-VIX (base) vs A4f-COMBO (alt): n={res_combo_vs_vix['n']}, "
          f"QL_VIX={res_combo_vs_vix['qlike_base']:.5f}, QL_COMBO={res_combo_vs_vix['qlike_a4f_combo']:.5f}, "
          f"DM_t={res_combo_vs_vix['dm_t']:+.3f} {harvey}")

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)

# H1: Full OOS A4f-VIX vs GJR Harvey-PASS
full_vix = results['full_oos'].get('gjr_vs_a4f_vix', {})
h1_t = full_vix.get('dm_t')
h1_verdict = 'PASS' if h1_t is not None and abs(h1_t) > 3.0 and h1_t > 0 else 'FAIL'
if h1_t is not None:
    print(f"  H1 (GLD full OOS A4f-VIX > GJR, |t|>3): {h1_verdict} (t={h1_t:+.3f})")
else:
    print(f"  H1: N/A")

# H2: A4f advantage at VIX Crisis (>60) — does it persist or attenuate?
crisis_bucket = results['vix_buckets'].get('Crisis', {})
extreme_bucket = results['vix_buckets'].get('Extreme', {})
h2_checks = []
for b_name, b in [('Crisis', crisis_bucket), ('Extreme', extreme_bucket)]:
    if isinstance(b, dict) and b.get('qlike_diff_pct') is not None:
        h2_checks.append((b_name, b['qlike_diff_pct'], b.get('dm_t')))
h2_verdict = 'N/A'
if h2_checks:
    # Attenuation if |diff| at extreme VIX noticeably smaller than average
    avg_diff = full_vix.get('qlike_diff_pct')
    if avg_diff is not None and avg_diff < 0:
        # A4f wins on average; check if still wins at extreme
        h2_verdict = 'PASS (no attenuation)' if all(d < 0 for _, d, _ in h2_checks) else 'ATTENUATES'
    else:
        h2_verdict = 'N/A (A4f no avg advantage)'
print(f"  H2 (GLD A4f at VIX>60 regime): {h2_verdict}")
for b_name, diff, t in h2_checks:
    print(f"    {b_name}: diff={diff:+.2f}%, DM t={t}")

# H3: theta1 stability vs SPY — we report coefficient range
vix_theta1s = [r['a4f_vix_theta1'] for r in refit_log
               if r.get('a4f_vix_theta1') is not None]
if vix_theta1s:
    theta1_mean = float(np.mean(vix_theta1s))
    theta1_std = float(np.std(vix_theta1s))
    theta1_cv = theta1_std / abs(theta1_mean) if theta1_mean != 0 else None
    print(f"  H3 (GLD θ₁ stability): mean={theta1_mean:.6e}, "
          f"std={theta1_std:.6e}, CV={theta1_cv:.3f}")
    results['theta1_stability'] = {
        'n_refits': len(vix_theta1s),
        'mean': theta1_mean, 'std': theta1_std,
        'cv': theta1_cv,
        'min': float(np.min(vix_theta1s)),
        'max': float(np.max(vix_theta1s)),
    }

# H4: GVZ superior to VIX?
h2h = results['vix_vs_gvz_compare'].get('a4f_vix_vs_a4f_gvz', {})
if h2h.get('dm_t') is not None:
    # base = A4f-VIX, alt = A4f-GVZ; positive DM t => GVZ better
    gvz_dm = h2h['dm_t']
    if abs(gvz_dm) > 3.0:
        h4_verdict = 'GVZ_SUPERIOR' if gvz_dm > 0 else 'VIX_SUPERIOR'
    else:
        h4_verdict = 'TIE (neither clearly better)'
    print(f"  H4 (Gold VIX vs VIX): {h4_verdict} (DM t={gvz_dm:+.3f})")
else:
    h4_verdict = 'N/A'
    print(f"  H4: {h4_verdict}")

results['hypothesis_verdicts'] = {
    'H1_full_oos_harvey_pass': h1_verdict,
    'H2_vix_crisis_regime': h2_verdict,
    'H4_gvz_vs_vix': h4_verdict,
}

# ============================================================
# SECTION 7: METADATA AND SAVE
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'GLD',
    'asset_class': 'Commodity_Gold',
    'currency': 'USD',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_total': n_total,
    'n_oos_actual': n_oos_actual,
    'n_refits': refit_count,
    'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
    'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
    'vix_buckets': [(n, lo, hi) for n, lo, hi in VIX_BUCKETS],
    'random_seed': 42,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (via K1085 brief)',
    'executor': 'Claude',
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors.',
        'Hansen & Lunde (2005). A forecast comparison of volatility models.',
        'Baur & McDermott (2010). Is gold a safe haven? International evidence.',
        'Reboredo (2013). Is gold a safe haven or a hedge for the US dollar?',
    ],
    'upstream_experiments': ['K988 (SPY A4f DM t=4.48 2019-2026)',
                             'K1075 (SPY A4f extended 2007-2026)',
                             'K994 (GLD brief A4f)',
                             'K1041 (DCC-A4f SPY+GLD VaR)'],
    'cross_asset_context': 'Paper 9: SPY/QQQ/IWM/EEM/EWT/EWZ/FXI all equity ETFs. '
                           'GLD is first non-equity (commodity safe-haven) test.',
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")

# ============================================================
# SECTION 8: PLOTS
# ============================================================
print("\n[8] Generating plots...")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # ------- Plot 1: Extended DM — 3 OOS windows x 4 model comparisons (vs GJR) -------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    win_names = [n for n, s, e in OOS_WINDOWS]
    win_names_valid = [n for n in win_names if n in results['per_window']]

    model_labels = ['A4f-VIX', 'A4f-GVZ', 'A4f-COMBO']
    model_keys = ['gjr_vs_a4f_vix', 'gjr_vs_a4f_gvz', 'gjr_vs_a4f_combo']
    colors_m = ['coral', 'goldenrod', 'steelblue']

    x = np.arange(len(win_names_valid))
    w = 0.25
    for i, (label_m, key_m, col) in enumerate(zip(model_labels, model_keys, colors_m)):
        diffs = []
        for wn in win_names_valid:
            r = results['per_window'].get(wn, {}).get(key_m)
            diffs.append(r['qlike_diff_pct'] if r else np.nan)
        ax1.bar(x + (i - 1) * w, diffs, w, label=label_m, color=col, alpha=0.85)
    ax1.axhline(0, color='black', lw=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(win_names_valid, rotation=15)
    ax1.set_ylabel('QLIKE Diff % vs GJR (negative = better)')
    ax1.set_title(f'{EXPERIMENT_ID}: QLIKE Improvement by OOS Window (GLD)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    for i, (label_m, key_m, col) in enumerate(zip(model_labels, model_keys, colors_m)):
        dms = []
        for wn in win_names_valid:
            r = results['per_window'].get(wn, {}).get(key_m)
            dms.append(r['dm_t'] if (r and r.get('dm_t') is not None) else np.nan)
        ax2.bar(x + (i - 1) * w, dms, w, label=label_m, color=col, alpha=0.85)
    ax2.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax2.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax2.axhline(0, color='black', lw=0.5)
    ax2.set_xticks(x)
    ax2.set_xticklabels(win_names_valid, rotation=15)
    ax2.set_ylabel('DM t-stat (>0 = A4f-variant better)')
    ax2.set_title('DM Test by OOS Window (GLD)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1085_extended_dm.png'), dpi=120)
    plt.close()
    print("    k1085_extended_dm.png")

    # ------- Plot 2: Crisis sub-periods -------
    fig, ax = plt.subplots(figsize=(13, 6))
    crisis_names = list(results['crisis_subperiods'].keys())
    x2 = np.arange(len(crisis_names))
    w2 = 0.25

    for i, (label_m, key_m, col) in enumerate(zip(model_labels, model_keys, colors_m)):
        dms = []
        for cn in crisis_names:
            r = results['crisis_subperiods'].get(cn, {}).get(key_m)
            dms.append(r['dm_t'] if (r and r.get('dm_t') is not None) else np.nan)
        ax.bar(x2 + (i - 1) * w2, dms, w2, label=label_m, color=col, alpha=0.85)

    ax.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_xticks(x2)
    ax.set_xticklabels(crisis_names, rotation=10)
    ax.set_ylabel('DM t-stat vs GJR (positive = A4f better)')
    ax.set_title(f'{EXPERIMENT_ID}: A4f vs GJR across GLD Crisis Sub-periods')
    ax.legend()
    ax.grid(True, alpha=0.3)
    for ci, cn in enumerate(crisis_names):
        n = results['crisis_subperiods'][cn].get('n', 0)
        ax.text(ci, ax.get_ylim()[1] * 0.95, f'n={n}', ha='center', fontsize=8, color='gray')

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1085_crisis_periods.png'), dpi=120)
    plt.close()
    print("    k1085_crisis_periods.png")

    # ------- Plot 3: VIX vs GVZ as regressor head-to-head -------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Left: QLIKE by model (Full OOS)
    model_full_labels = ['GJR', 'A4f-VIX', 'A4f-GVZ', 'A4f-COMBO']
    ql_vals = []
    ql_vals.append(results['full_oos'].get('gjr_vs_a4f_vix', {}).get('qlike_base'))
    ql_vals.append(results['full_oos'].get('gjr_vs_a4f_vix', {}).get('qlike_a4f_vix'))
    ql_vals.append(results['full_oos'].get('gjr_vs_a4f_gvz', {}).get('qlike_a4f_gvz'))
    ql_vals.append(results['full_oos'].get('gjr_vs_a4f_combo', {}).get('qlike_a4f_combo'))

    colors_all = ['gray', 'coral', 'goldenrod', 'steelblue']
    ax1.bar(model_full_labels, ql_vals, color=colors_all, alpha=0.85)
    ax1.set_ylabel('QLIKE (lower = better)')
    ax1.set_title(f'{EXPERIMENT_ID}: QLIKE by Model (GLD Full OOS 2007-2026)')
    ax1.grid(True, alpha=0.3, axis='y')
    for i, v in enumerate(ql_vals):
        if v is not None:
            ax1.text(i, v, f'{v:.5f}', ha='center', fontsize=9,
                     va='bottom' if v >= 0 else 'top')

    # Right: DM t-stat of alt vs GJR, and GVZ vs VIX
    dm_labels = ['A4f-VIX\nvs GJR', 'A4f-GVZ\nvs GJR', 'A4f-COMBO\nvs GJR',
                 'A4f-GVZ\nvs A4f-VIX', 'A4f-COMBO\nvs A4f-VIX']
    dm_vals = [
        results['full_oos'].get('gjr_vs_a4f_vix', {}).get('dm_t'),
        results['full_oos'].get('gjr_vs_a4f_gvz', {}).get('dm_t'),
        results['full_oos'].get('gjr_vs_a4f_combo', {}).get('dm_t'),
        results['vix_vs_gvz_compare'].get('a4f_vix_vs_a4f_gvz', {}).get('dm_t'),
        results['vix_vs_gvz_compare'].get('a4f_vix_vs_a4f_combo', {}).get('dm_t'),
    ]
    colors_dm = ['green' if (v is not None and abs(v) > 3.0) else
                 ('orange' if (v is not None and abs(v) > 1.96) else 'gray') for v in dm_vals]
    ax2.bar(dm_labels, [v if v is not None else 0 for v in dm_vals], color=colors_dm, alpha=0.85)
    ax2.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax2.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax2.axhline(0, color='black', lw=0.5)
    ax2.set_ylabel('DM t-stat')
    ax2.set_title('Pairwise DM Tests (GLD Full OOS)')
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.legend()
    plt.setp(ax2.get_xticklabels(), rotation=10, fontsize=8)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1085_vix_gvz_compare.png'), dpi=120)
    plt.close()
    print("    k1085_vix_gvz_compare.png")

    # ------- Plot 4: θ₁ evolution (VIX and GVZ separately) -------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    refit_dates_vix = [pd.to_datetime(r['date']) for r in refit_log
                       if r.get('a4f_vix_theta1') is not None]
    theta1_vix = [r['a4f_vix_theta1'] for r in refit_log
                  if r.get('a4f_vix_theta1') is not None]
    refit_dates_gvz = [pd.to_datetime(r['date']) for r in refit_log
                       if r.get('a4f_gvz_theta1') is not None]
    theta1_gvz = [r['a4f_gvz_theta1'] for r in refit_log
                  if r.get('a4f_gvz_theta1') is not None]

    ax1.plot(refit_dates_vix, theta1_vix, marker='o', markersize=4, alpha=0.7, color='coral')
    ax1.set_ylabel('θ₁ (VIX² coeff)')
    ax1.set_title(f'{EXPERIMENT_ID}: A4f-VIX θ₁ Evolution (GLD, 2007-2026)')
    ax1.grid(True, alpha=0.3)
    for cname, cstart, cend in CRISIS_PERIODS:
        ax1.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
                    alpha=0.15, color='red', label=cname if cname == 'GFC_2008' else None)
    ax1.legend()

    ax2.plot(refit_dates_gvz, theta1_gvz, marker='s', markersize=4, alpha=0.7, color='goldenrod')
    ax2.set_xlabel('Refit date')
    ax2.set_ylabel('θ₁ (GVZ² coeff)')
    ax2.set_title('A4f-GVZ θ₁ Evolution (GLD)')
    ax2.grid(True, alpha=0.3)
    for cname, cstart, cend in CRISIS_PERIODS:
        ax2.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
                    alpha=0.15, color='red')

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1085_theta1_evolution.png'), dpi=120)
    plt.close()
    print("    k1085_theta1_evolution.png")

    # ------- Plot 5: 9-asset cross-section summary -------
    # Compile all 9 assets results from context
    # Canonical Paper 9 cross-asset table (excluding current GLD result, which we'll add)
    cross_assets = [
        ('SPY', 'Equity US Large', 'USD', 7.92),
        ('QQQ', 'Equity US Tech', 'USD', 5.99),
        ('EEM', 'Equity EM', 'USD', 5.25),
        ('IWM', 'Equity US Small', 'USD', 4.80),
        ('FXI', 'Equity China', 'USD', 3.61),
        ('EWZ', 'Equity Brazil', 'USD', 2.33),
        ('EWT', 'Equity Taiwan', 'USD', 2.26),
    ]
    # Current GLD result (from full_oos A4f-VIX vs GJR)
    gld_dm = results['full_oos'].get('gjr_vs_a4f_vix', {}).get('dm_t')
    if gld_dm is not None:
        cross_assets.append(('GLD', 'Commodity Gold', 'USD', float(gld_dm)))
    cross_assets.append(('0050.TW', 'Equity Taiwan', 'TWD', -0.49))

    fig, ax = plt.subplots(figsize=(13, 6))
    names = [a[0] for a in cross_assets]
    classes = [a[1] for a in cross_assets]
    dms = [a[3] for a in cross_assets]
    colors_cs = []
    for dm in dms:
        if abs(dm) > 3.0:
            colors_cs.append('green' if dm > 0 else 'red')
        elif abs(dm) > 1.96:
            colors_cs.append('orange')
        else:
            colors_cs.append('gray')

    bars = ax.bar(names, dms, color=colors_cs, alpha=0.85)
    ax.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax.axhline(1.96, color='gray', linestyle=':', alpha=0.3, label='95% CI |t|=1.96')
    ax.axhline(-1.96, color='gray', linestyle=':', alpha=0.3)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_ylabel('DM t-stat (A4f-VIX vs GJR, >0 = A4f better)')
    ax.set_title(f'{EXPERIMENT_ID}: Paper 9 Nine-Asset Cross-Section '
                 '(GLD = 1st non-equity test)')
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')
    for i, (name, cls, dm) in enumerate(zip(names, classes, dms)):
        ax.text(i, dm + (0.2 if dm >= 0 else -0.4), f'{dm:+.2f}',
                ha='center', fontsize=9, fontweight='bold')
        ax.text(i, ax.get_ylim()[0] * 0.95, cls.split()[0][:8],
                ha='center', fontsize=7, color='gray', rotation=0)

    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1085_nine_asset_final.png'), dpi=120)
    plt.close()
    print("    k1085_nine_asset_final.png")

except Exception as e:
    print(f"  Plot error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE in {time.time() - START_TIME:.0f}s")
print("=" * 70)
