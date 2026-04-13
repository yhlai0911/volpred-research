#!/usr/bin/env python3
"""
K1089: A4f on BTC-USD with VIX + BTC30RV — Asset-Matched Theory on Crypto (5th Class)
=====================================================================================
[提出: 用戶 (via K1089 brief), 執行: Claude]

Motivation:
  Paper 9 cross-asset matrix before this experiment:
    - Equity  (SPY/QQQ/IWM/EEM/FXI) : VIX  PASS (K1075-K1082)
    - Commodity - Gold (GLD)        : GVZ  PASS (K1085)
    - Commodity - Oil  (USO)        : OVX  PASS (K1088)
    - Bonds   (TLT)                 : MOVE/Yield Curve FAIL (K1086-K1087)
    - Crypto  (BTC-USD)             : THIS EXPERIMENT (5th asset class)

  The 5th asset-class test asks: does the asset-matched implied-vol
  principle extend to a 24/7-traded, post-2008 asset with adoption-curve
  and regulatory shocks rather than macro cycles?

  ------------------------------------------------------------------
  NOTE ON CRYPTO-IV DATA: BVIV / BitVol (Volmex) and official DVOL
  (Deribit) are not exposed by yfinance (verified 2026-04-12). Instead
  we build a *home-IV proxy* from BTC itself: the 30-day rolling
  realized vol of log returns. It captures own-market vol state in the
  same spirit GVZ/OVX captures gold/oil implied vol.
  We therefore test:
    - A4f-VIX      : cross-asset global fear
    - A4f-BTC30RV  : crypto home-vol proxy
    - A4f-COMBO    : VIX² + BTC30RV²
  If BVIV/DVOL become available later, this can be re-run with true IV.
  ------------------------------------------------------------------

Hypotheses:
  H1: BTC full OOS A4f-VIX vs GJR Harvey-PASS (|t|>3, positive)?
  H2: BTC full OOS A4f-BTC30RV vs GJR Harvey-PASS?
  H3: A4f-BTC30RV beats A4f-VIX (head-to-head DM)?
  H4: A4f-COMBO improves further vs best single?
  H5: Results hold across crypto crises (2018 bear, 2020 COVID,
      2022 Terra Luna, 2022 FTX)?
  H6: VIX-regime conditional — does BTC A4f help more in high VIX?

Design (aligned with K1088 where possible):
  - BTC-USD is 24/7 → all calendar days have observation; VIX is
    business-day only, so VIX is forward-filled onto BTC dates
    (value used at t is the most recent known VIX at close of day t-1).
  - Rolling-window GARCH, 1000-day train (shorter than K1088's 2000
    because BTC data only starts 2014-09-17 giving us ~4200 days total),
    63-day refit.
  - Three OOS windows (non-overlapping):
      Early (2018-01-01 ~ 2020-02-14) : 2018 bear (post 2017 bubble)
      Middle (2020-02-15 ~ 2022-10-31) : COVID + Luna collapse
      Late  (2022-11-01 ~ 2026-04-11) : FTX + 2024 rally
  - Four models: GJR, A4f-VIX, A4f-BTC30RV, A4f-COMBO
  - Crypto crisis sub-periods: 2018 bear, 2020 COVID, 2021-05 China ban,
    2022 Luna, 2022 FTX, 2024 Yen-carry unwind
  - VIX and BTC30RV bucket analysis
  - Random seed 42

Data:
  - BTC-USD daily Close (yfinance, 2014-09-17 ~ 2026-04-11, ~4225 days)
  - ^VIX daily Close (yfinance, forward-filled to BTC dates)
  - BTC30RV: 30-day rolling realized vol of BTC log returns,
    annualized = sqrt(252 * mean(r_t..r_{t-29}^2))  (lagged so t's
    value uses returns through t-1; no lookahead)

Evaluation:
  - QLIKE on r² (Patton 2011)
  - DM test with Newey-West HAC (Harvey 2016, |t|>3.0)
  - Spearman rank correlation
  - Bootstrap CI (1000 reps, block bootstrap, seed 42)

References:
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797. [GARCH-MIDAS origin]
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey, Leybourne & Newbold (2016). Testing the equality of prediction
    mean squared errors.
  - Baur & Dimpfl (2018). Asymmetric volatility in cryptocurrencies. Econ Letters.
  - Conlon, Corbet & McGee (2020). Bitcoin risk-return trade-off. JIFMIM.
  - Katsiampa (2017). Volatility estimation for Bitcoin: A comparison of
    GARCH models. Econ Letters 158:3-6.
  - Liu, Tsyvinski & Wu (2022). Common Risk Factors in Cryptocurrency. JF.

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1089
Upstream: K1088 (USO + OVX PASS), K1085 (GLD + GVZ PASS)
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
EXPERIMENT_ID = "K1089"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1089_results.json')

# Configuration
DATA_START = '2014-09-01'
DATA_END = '2026-04-12'
WINDOW = 1000          # shorter than K1088 (2000) because BTC history is shorter
REFIT_EVERY = 63       # quarterly
RV_LOOKBACK = 30       # days for realized vol home-IV proxy

# Three non-overlapping OOS windows
# With BTC from 2014-09-17 and WINDOW=1000, pure-training OOS starts ~2017-06
# We start OOS at 2018-01 for a clean post-2017-bubble boundary
OOS_WINDOWS = [
    ('Early_2018Bear', '2018-01-01', '2020-02-14'),       # 2018 crypto winter
    ('Middle_COVID_Luna', '2020-02-15', '2022-10-31'),    # COVID + Terra Luna
    ('Late_FTX_Rally', '2022-11-01', '2026-04-11'),       # FTX + 2024 ETF rally
]

# Crypto crisis sub-periods
CRISIS_PERIODS = [
    ('Bear_2018', '2018-01-15', '2018-12-31'),           # $20k -> $3k
    ('COVID_2020', '2020-02-15', '2020-04-30'),          # Black Thursday
    ('China_Ban_2021', '2021-05-12', '2021-07-31'),      # China mining ban
    ('Luna_2022', '2022-05-05', '2022-06-30'),           # Terra Luna collapse
    ('FTX_2022', '2022-11-05', '2023-01-15'),            # FTX bankruptcy
    ('Carry_Unwind_2024', '2024-07-25', '2024-09-10'),   # JPY carry unwind
]

# VIX buckets
VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

# BTC30RV buckets (annualized vol %)
# BTC annualized vol typical range 40%-150%+
BTC30RV_BUCKETS = [
    ('RV_Low', 0, 40),
    ('RV_Normal', 40, 70),
    ('RV_High', 70, 100),
    ('RV_Extreme', 100, 200),
]

print("=" * 72)
print(f"{EXPERIMENT_ID}: A4f on BTC-USD with VIX + BTC30RV — 5th Asset Class")
print(f"  4 models (GJR, A4f-VIX, A4f-BTC30RV, A4f-COMBO), 3 OOS windows,")
print(f"  6 crypto crisis sub-periods, VIX + BTC30RV bucket analysis")
print("=" * 72)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

btc_raw = yf.download('BTC-USD', start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=False)
if isinstance(btc_raw.columns, pd.MultiIndex):
    btc_raw.columns = btc_raw.columns.get_level_values(0)
btc_price = btc_raw['Close'].copy()  # BTC has no dividends/splits
btc_ret = np.log(btc_price / btc_price.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False,
                      auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# Build DataFrame on BTC's 24/7 calendar.
# VIX: reindex to BTC dates with forward-fill. This represents "the most
# recent publicly-known VIX level". For day t's conditional variance of BTC,
# we use lag-1 VIX (VIX at close of t-1). Forward-fill across weekends is
# the correct operational information set for a 24/7 asset.
df = pd.DataFrame({'price': btc_price, 'log_ret': btc_ret})
df = df.dropna()

vix_aligned = vix_close.reindex(df.index).ffill()
# Drop rows where VIX is still NaN (very earliest dates before VIX starts)
df['VIX'] = vix_aligned
df = df.dropna(subset=['VIX'])

# Build BTC30RV proxy: sqrt(252 * mean(r^2 over past RV_LOOKBACK days))
# r² observed up to time t-1 produces the RV value used as regressor at time t
r2_series = df['log_ret'] ** 2
rv_raw = r2_series.rolling(window=RV_LOOKBACK, min_periods=RV_LOOKBACK).mean()
df['BTC30RV'] = 100.0 * np.sqrt(252.0 * rv_raw)  # annualized percent, to match VIX scale

df = df.dropna(subset=['BTC30RV'])

n_total = len(df)
print(f"  Aligned data: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  (24/7 BTC calendar with forward-filled VIX)")

ret = df['log_ret'].values
vix = df['VIX'].values
btc_rv = df['BTC30RV'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
print(f"  Full sample BTC-USD:")
print(f"    Return mean (ann): {np.mean(ret)*365:.4f}  (365d calendar)")
print(f"    Return std  (ann): {np.std(ret)*np.sqrt(365):.4f}")
print(f"    Return skew:      {stats.skew(ret):.3f}")
print(f"    Return kurt:      {stats.kurtosis(ret):.3f}")
print(f"    Return min/max:   {np.min(ret):.4f} / {np.max(ret):.4f}")
print(f"    VIX mean/max: {np.mean(vix):.2f} / {np.max(vix):.2f}")
print(f"    BTC30RV mean/max: {np.mean(btc_rv):.2f} / {np.max(btc_rv):.2f} (ann %)")

for name, start, end in OOS_WINDOWS:
    mask = (dates >= start) & (dates <= end)
    n_w = mask.sum()
    print(f"  {name} ({start} to {end}): n={n_w}, VIX max={np.max(vix[mask]):.1f}, "
          f"BTC30RV max={np.max(btc_rv[mask]):.1f}, "
          f"ret std={np.std(ret[mask])*np.sqrt(365):.3f}")

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


# --- A4f single regressor: tau = theta0 + theta1 * X_lag² ---
def fit_a4f_single(returns, x_vals):
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
        (-1e-1, 1e-1),
        (1e-12, 1.0),
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


# --- A4f-COMBO: tau = theta0 + theta1*VIX² + theta2*BTC30RV² ---
def fit_a4f_combo(returns, vix_vals, rv_vals):
    n = len(returns)
    vix_lag = np.empty(n); vix_lag[0] = vix_vals[0]; vix_lag[1:] = vix_vals[:-1]
    rv_lag = np.empty(n); rv_lag[0] = rv_vals[0]; rv_lag[1:] = rv_vals[:-1]
    vix_sq = vix_lag ** 2
    rv_sq = rv_lag ** 2

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = np.maximum(theta0 + theta1 * vix_sq + theta2 * rv_sq, 1e-16)

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
    rv_sq_mean = np.mean(rv_sq) + 1e-8

    starts = [
        [var0 * 0.1, var0 / vix_sq_mean * 0.5, var0 / rv_sq_mean * 0.5,
         0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix_sq_mean * 0.3, var0 / rv_sq_mean * 0.3,
         0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix_sq_mean * 0.7, var0 / rv_sq_mean * 0.7,
         0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-1, 1e-1),     # theta0
        (0, 1.0),          # theta1 (VIX coeff, nonneg)
        (0, 1.0),          # theta2 (RV coeff, nonneg)
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
    start_idx_arr = np.where(dates >= start)[0]
    if len(start_idx_arr) == 0:
        print(f"    {name}: no data")
        continue
    start_idx = start_idx_arr[0]
    print(f"    {name}: start_idx={start_idx}, window_required={WINDOW}, "
          f"sufficient={'YES' if start_idx >= WINDOW else 'NO'}")

# Forecast arrays
gjr_fc = np.full(n_oos_actual, np.nan)
a4f_vix_fc = np.full(n_oos_actual, np.nan)
a4f_rv_fc = np.full(n_oos_actual, np.nan)
a4f_combo_fc = np.full(n_oos_actual, np.nan)

refit_log = []

# States
gjr_h = None; gjr_params = None
a4f_vix_g = None; a4f_vix_params = None
a4f_rv_g = None; a4f_rv_params = None
a4f_combo_g = None; a4f_combo_params = None

prev_window = None
refit_count = 0


def init_a4f_state(train_ret, x_vals, params, regressor='single'):
    """Run filter on training to produce the final g."""
    if regressor == 'single':
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params
        x_lag = np.empty(len(x_vals)); x_lag[0] = x_vals[0]; x_lag[1:] = x_vals[:-1]
        tau = np.maximum(theta0 + theta1 * x_lag**2, 1e-16)
    elif regressor == 'combo':
        theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = params
        vix_v, rv_v = x_vals
        vix_lag = np.empty(len(vix_v)); vix_lag[0] = vix_v[0]; vix_lag[1:] = vix_v[:-1]
        rv_lag = np.empty(len(rv_v)); rv_lag[0] = rv_v[0]; rv_lag[1:] = rv_v[:-1]
        tau = np.maximum(theta0 + theta1 * vix_lag**2 + theta2 * rv_lag**2, 1e-16)

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
        train_rv = btc_rv[train_start:abs_idx]

        # GJR
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_params = gjr_p
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h
        else:
            gjr_conv = False

        # A4f-VIX
        a4f_vix_p, a4f_vix_conv = fit_a4f_single(train_ret, train_vix)
        if a4f_vix_p is not None:
            a4f_vix_params = a4f_vix_p
            a4f_vix_g = init_a4f_state(train_ret, train_vix, a4f_vix_p, 'single')
        else:
            a4f_vix_conv = False

        # A4f-BTC30RV
        a4f_rv_p, a4f_rv_conv = fit_a4f_single(train_ret, train_rv)
        if a4f_rv_p is not None:
            a4f_rv_params = a4f_rv_p
            a4f_rv_g = init_a4f_state(train_ret, train_rv, a4f_rv_p, 'single')
        else:
            a4f_rv_conv = False

        # A4f-COMBO
        a4f_combo_p, a4f_combo_conv = fit_a4f_combo(train_ret, train_vix, train_rv)
        if a4f_combo_p is not None:
            a4f_combo_params = a4f_combo_p
            a4f_combo_g = init_a4f_state(train_ret, (train_vix, train_rv),
                                          a4f_combo_p, 'combo')
        else:
            a4f_combo_conv = False

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            'gjr_conv': bool(gjr_conv),
            'a4f_vix_conv': bool(a4f_vix_conv),
            'a4f_rv_conv': bool(a4f_rv_conv),
            'a4f_combo_conv': bool(a4f_combo_conv),
            'a4f_vix_theta0': float(a4f_vix_params[0]) if a4f_vix_params is not None else None,
            'a4f_vix_theta1': float(a4f_vix_params[1]) if a4f_vix_params is not None else None,
            'a4f_rv_theta0': float(a4f_rv_params[0]) if a4f_rv_params is not None else None,
            'a4f_rv_theta1': float(a4f_rv_params[1]) if a4f_rv_params is not None else None,
            'a4f_combo_theta1_vix': float(a4f_combo_params[1]) if a4f_combo_params is not None else None,
            'a4f_combo_theta2_rv': float(a4f_combo_params[2]) if a4f_combo_params is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # Forecast for day abs_idx (uses info up to t-1)
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

    # A4f-BTC30RV
    if a4f_rv_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_rv_params
        rv_prev = btc_rv[abs_idx - 1]
        tau_t = max(theta0 + theta1 * rv_prev**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_rv_g
        g_new = max(g_new, 1e-10)
        a4f_rv_fc[t_idx] = tau_t * g_new
        a4f_rv_g = g_new

    # A4f-COMBO
    if a4f_combo_params is not None:
        theta0, theta1, theta2, omega_g, alpha_p, gamma_p, beta_p = a4f_combo_params
        v_lag = vix[abs_idx - 1]
        rv_prev = btc_rv[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag**2 + theta2 * rv_prev**2, 1e-16)
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
oos_rv = btc_rv[oos_indices]
oos_ret = ret[oos_indices]
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


results = {'metadata': {}, 'full_oos': {}, 'per_window': {},
           'crisis_subperiods': {}, 'vix_buckets': {}, 'btc_rv_buckets': {},
           'head_to_head': {}, 'refit_log': refit_log}

# --- Full OOS (union) ---
print("\n  FULL OOS (2018-2026):")
print(f"  {'Comparison':<30} {'n':>6} {'QL_base':>10} {'QL_alt':>10} {'Diff%':>8} {'DM t':>8} {'Harvey':>8}")
for label_alt, fc_alt in [('a4f_vix', a4f_vix_fc),
                           ('a4f_rv', a4f_rv_fc),
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

    for label_alt, fc_alt_full in [('a4f_vix', a4f_vix_fc),
                                    ('a4f_rv', a4f_rv_fc),
                                    ('a4f_combo', a4f_combo_fc)]:
        res = evaluate_pair(gjr_fc[mask], fc_alt_full[mask], r2_w, label_alt)
        if res is None:
            continue
        results['per_window'][name][f'gjr_vs_{label_alt}'] = res
        harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
        print(f"  gjr vs {label_alt:<22} {res['n']:>6} {res['qlike_base']:>10.5f} "
              f"{res[f'qlike_{label_alt}']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
              f"{res['dm_t']:>+8.3f} {harvey:>8}")

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods (vs GJR, all three A4f variants):")
for cname, cstart, cend in CRISIS_PERIODS:
    c_mask_full = (oos_dates >= cstart) & (oos_dates <= cend)
    r2_c = oos_r2[c_mask_full]
    vix_c = oos_vix[c_mask_full]
    rv_c = oos_rv[c_mask_full]

    if c_mask_full.sum() < 30:
        print(f"  {cname:<20} insufficient (n={c_mask_full.sum()})")
        continue

    res_vix = evaluate_pair(gjr_fc[c_mask_full], a4f_vix_fc[c_mask_full], r2_c, 'a4f_vix')
    res_rv = evaluate_pair(gjr_fc[c_mask_full], a4f_rv_fc[c_mask_full], r2_c, 'a4f_rv')
    res_combo = evaluate_pair(gjr_fc[c_mask_full], a4f_combo_fc[c_mask_full], r2_c, 'a4f_combo')

    if res_vix is None:
        continue

    print(f"  {cname:<20} n={res_vix['n']}, VIX max={np.max(vix_c):.1f}, "
          f"RV max={np.max(rv_c):.1f}")
    print(f"    A4f-VIX     : diff={res_vix['qlike_diff_pct']:+.2f}%, DM t={res_vix['dm_t']:+.3f}")
    if res_rv:
        print(f"    A4f-BTC30RV : diff={res_rv['qlike_diff_pct']:+.2f}%, DM t={res_rv['dm_t']:+.3f}")
    if res_combo:
        print(f"    A4f-COMBO   : diff={res_combo['qlike_diff_pct']:+.2f}%, DM t={res_combo['dm_t']:+.3f}")

    results['crisis_subperiods'][cname] = {
        'start': cstart, 'end': cend,
        'n': int(res_vix['n']),
        'vix_mean': float(np.mean(vix_c)),
        'vix_max': float(np.max(vix_c)),
        'rv_mean': float(np.mean(rv_c)),
        'rv_max': float(np.max(rv_c)),
        'gjr_vs_a4f_vix': res_vix,
        'gjr_vs_a4f_rv': res_rv,
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

# --- BTC30RV bucket analysis (A4f-BTC30RV vs GJR) ---
print("\n  BTC30RV bucket analysis (A4f-BTC30RV vs GJR):")
print(f"  {'Bucket':<12} {'Range':<15} {'n':>6} {'QL_GJR':>10} {'QL_A4f':>10} {'Diff%':>8} {'DM t':>8}")
oos_rv_lag = np.empty(n_oos_actual)
for i, idx in enumerate(oos_indices):
    oos_rv_lag[i] = btc_rv[idx - 1] if idx > 0 else btc_rv[0]

for bname, bmin, bmax in BTC30RV_BUCKETS:
    mask = (oos_rv_lag >= bmin) & (oos_rv_lag < bmax)
    n_b = mask.sum()
    if n_b < 20:
        print(f"  {bname:<12} [{bmin},{bmax}) insufficient (n={n_b})")
        results['btc_rv_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue

    res = evaluate_pair(gjr_fc[mask], a4f_rv_fc[mask], oos_r2[mask], 'a4f_rv')
    if res is None:
        continue

    harvey = 'PASS' if res['harvey_pass'] else 'FAIL'
    print(f"  {bname:<12} [{bmin},{bmax})     {res['n']:>6} {res['qlike_base']:>10.5f} "
          f"{res['qlike_a4f_rv']:>10.5f} {res['qlike_diff_pct']:>+7.2f}% "
          f"{res['dm_t']:>+8.3f}")
    results['btc_rv_buckets'][bname] = {
        'range': [bmin, bmax],
        **res,
    }

# --- Head-to-head comparisons ---
print("\n  Head-to-head comparisons:")
# A4f-VIX vs A4f-BTC30RV (base = VIX, alt = RV → positive means RV better)
res_hth = evaluate_pair(a4f_vix_fc, a4f_rv_fc, oos_r2, 'a4f_rv')
if res_hth is not None:
    results['head_to_head']['a4f_vix_vs_a4f_rv'] = res_hth
    harvey = 'PASS' if res_hth['harvey_pass'] else 'FAIL'
    print(f"  A4f-VIX (base) vs A4f-BTC30RV (alt): n={res_hth['n']}, "
          f"QL_VIX={res_hth['qlike_base']:.5f}, QL_RV={res_hth['qlike_a4f_rv']:.5f}, "
          f"DM t={res_hth['dm_t']:+.3f} {harvey}")

res_combo_vs_vix = evaluate_pair(a4f_vix_fc, a4f_combo_fc, oos_r2, 'a4f_combo')
if res_combo_vs_vix is not None:
    results['head_to_head']['a4f_vix_vs_a4f_combo'] = res_combo_vs_vix
    harvey = 'PASS' if res_combo_vs_vix['harvey_pass'] else 'FAIL'
    print(f"  A4f-VIX (base) vs A4f-COMBO (alt): n={res_combo_vs_vix['n']}, "
          f"QL_VIX={res_combo_vs_vix['qlike_base']:.5f}, "
          f"QL_COMBO={res_combo_vs_vix['qlike_a4f_combo']:.5f}, "
          f"DM t={res_combo_vs_vix['dm_t']:+.3f} {harvey}")

res_combo_vs_rv = evaluate_pair(a4f_rv_fc, a4f_combo_fc, oos_r2, 'a4f_combo')
if res_combo_vs_rv is not None:
    results['head_to_head']['a4f_rv_vs_a4f_combo'] = res_combo_vs_rv
    harvey = 'PASS' if res_combo_vs_rv['harvey_pass'] else 'FAIL'
    print(f"  A4f-BTC30RV (base) vs A4f-COMBO (alt): n={res_combo_vs_rv['n']}, "
          f"QL_RV={res_combo_vs_rv['qlike_base']:.5f}, "
          f"QL_COMBO={res_combo_vs_rv['qlike_a4f_combo']:.5f}, "
          f"DM t={res_combo_vs_rv['dm_t']:+.3f} {harvey}")

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)

# H1: Full OOS A4f-VIX vs GJR
full_vix = results['full_oos'].get('gjr_vs_a4f_vix', {})
h1_t = full_vix.get('dm_t')
h1_verdict = 'PASS' if h1_t is not None and abs(h1_t) > 3.0 and h1_t > 0 else 'FAIL'
if h1_t is not None:
    print(f"  H1 (BTC full OOS A4f-VIX > GJR, |t|>3): {h1_verdict} (t={h1_t:+.3f})")
else:
    print(f"  H1: N/A")

# H2: Full OOS A4f-BTC30RV vs GJR
full_rv = results['full_oos'].get('gjr_vs_a4f_rv', {})
h2_t = full_rv.get('dm_t')
h2_verdict = 'PASS' if h2_t is not None and abs(h2_t) > 3.0 and h2_t > 0 else 'FAIL'
if h2_t is not None:
    print(f"  H2 (BTC full OOS A4f-BTC30RV > GJR, |t|>3): {h2_verdict} (t={h2_t:+.3f})")
else:
    print(f"  H2: N/A")

# H3: BTC30RV beats VIX (head-to-head)
h3h = results['head_to_head'].get('a4f_vix_vs_a4f_rv', {})
h3_t = h3h.get('dm_t')
if h3_t is not None:
    if abs(h3_t) > 3.0 and h3_t > 0:
        h3_verdict = 'RV_SUPERIOR'
    elif abs(h3_t) > 3.0 and h3_t < 0:
        h3_verdict = 'VIX_SUPERIOR'
    else:
        h3_verdict = 'TIE'
    print(f"  H3 (RV vs VIX as regressor): {h3_verdict} (DM t={h3_t:+.3f})")
else:
    h3_verdict = 'N/A'
    print(f"  H3: {h3_verdict}")

# H4: A4f-COMBO improvement over both single regressors
combo_vs_vix = results['head_to_head'].get('a4f_vix_vs_a4f_combo', {})
combo_vs_rv = results['head_to_head'].get('a4f_rv_vs_a4f_combo', {})
h4_vs_vix_pass = (combo_vs_vix.get('dm_t') is not None and combo_vs_vix['dm_t'] > 3.0)
h4_vs_rv_pass = (combo_vs_rv.get('dm_t') is not None and combo_vs_rv['dm_t'] > 3.0)
if h4_vs_vix_pass and h4_vs_rv_pass:
    h4_verdict = 'COMBO_SUPERIOR_TO_BOTH'
elif h4_vs_vix_pass or h4_vs_rv_pass:
    h4_verdict = 'COMBO_SUPERIOR_TO_ONE'
else:
    h4_verdict = 'COMBO_NO_IMPROVEMENT'
print(f"  H4 (A4f-COMBO vs singles): {h4_verdict} "
      f"(t_vs_VIX={combo_vs_vix.get('dm_t')}, t_vs_RV={combo_vs_rv.get('dm_t')})")

# H5: Crisis sub-period consistency
crisis_results = results['crisis_subperiods']
crisis_rv_wins = 0
crisis_rv_total = 0
crisis_vix_wins = 0
crisis_vix_total = 0
for cname, cdata in crisis_results.items():
    r_rv = cdata.get('gjr_vs_a4f_rv')
    r_vix = cdata.get('gjr_vs_a4f_vix')
    if r_rv and r_rv.get('dm_t') is not None:
        crisis_rv_total += 1
        if r_rv['dm_t'] > 0:
            crisis_rv_wins += 1
    if r_vix and r_vix.get('dm_t') is not None:
        crisis_vix_total += 1
        if r_vix['dm_t'] > 0:
            crisis_vix_wins += 1
h5_verdict = (f"RV wins {crisis_rv_wins}/{crisis_rv_total}, "
              f"VIX wins {crisis_vix_wins}/{crisis_vix_total}")
print(f"  H5 (crisis consistency): {h5_verdict}")

# H6: VIX regime conditional
high_vix_res = None
for bname in ['High', 'Extreme', 'Crisis']:
    b = results['vix_buckets'].get(bname, {})
    t = b.get('dm_t')
    if t is not None:
        label = f"{bname}(t={t:+.2f})"
        if high_vix_res is None:
            high_vix_res = []
        high_vix_res.append(label)
h6_verdict = 'N/A' if high_vix_res is None else ' | '.join(high_vix_res)
print(f"  H6 (VIX-regime conditional): {h6_verdict}")

# Theta stability summary
vix_theta1s = [r['a4f_vix_theta1'] for r in refit_log
               if r.get('a4f_vix_theta1') is not None]
rv_theta1s = [r['a4f_rv_theta1'] for r in refit_log
              if r.get('a4f_rv_theta1') is not None]
theta1_stats = {}
for label, vals in [('vix', vix_theta1s), ('rv', rv_theta1s)]:
    if vals:
        m = float(np.mean(vals))
        s = float(np.std(vals))
        theta1_stats[label] = {
            'n_refits': len(vals),
            'mean': m,
            'std': s,
            'cv': s / abs(m) if m != 0 else None,
            'min': float(np.min(vals)),
            'max': float(np.max(vals)),
        }
        print(f"  theta1_{label.upper()}: mean={m:.6e}, std={s:.6e}, "
              f"CV={s/abs(m) if m!=0 else None:.3f}")
results['theta1_stability'] = theta1_stats

results['hypothesis_verdicts'] = {
    'H1_full_oos_vix_harvey_pass': h1_verdict,
    'H2_full_oos_rv_harvey_pass': h2_verdict,
    'H3_rv_vs_vix': h3_verdict,
    'H4_combo_improvement': h4_verdict,
    'H5_crisis_consistency': h5_verdict,
    'H6_vix_regime': h6_verdict,
}

# ============================================================
# SECTION 7: METADATA AND SAVE
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'BTC-USD',
    'asset_class': 'Crypto',
    'currency': 'USD',
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'rv_lookback_days': RV_LOOKBACK,
    'n_total': n_total,
    'n_oos_actual': n_oos_actual,
    'n_refits': refit_count,
    'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
    'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
    'vix_buckets': [(n, lo, hi) for n, lo, hi in VIX_BUCKETS],
    'btc_rv_buckets': [(n, lo, hi) for n, lo, hi in BTC30RV_BUCKETS],
    'random_seed': 42,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (via K1089 brief)',
    'executor': 'Claude',
    'iv_availability_note': (
        'BVIV (Volmex) and official DVOL (Deribit) not available via yfinance '
        'as of 2026-04-12. BTC30RV (30-day rolling realized vol of BTC log '
        'returns) used as home-IV proxy. Lagged so only past information is used.'
    ),
    'calendar_note': (
        '24/7 BTC calendar used; VIX forward-filled across weekends and US '
        'holidays so weekend BTC observations use most recent known VIX '
        '(Friday close).'
    ),
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). Testing the equality of prediction mean squared errors.',
        'Baur & Dimpfl (2018). Asymmetric volatility in cryptocurrencies. Econ Letters.',
        'Conlon, Corbet & McGee (2020). Bitcoin risk-return trade-off. JIFMIM.',
        'Katsiampa (2017). Volatility estimation for Bitcoin: A comparison of GARCH models. Econ Letters 158:3-6.',
        'Liu, Tsyvinski & Wu (2022). Common Risk Factors in Cryptocurrency. JF.',
    ],
    'upstream_experiments': [
        'K1075 (SPY A4f PASS)',
        'K1082 (Equity cross-asset 5 ETFs PASS)',
        'K1085 (GLD + GVZ PASS, DM t=+4.46)',
        'K1086 (TLT + MOVE FAIL)',
        'K1087 (TLT + yield curve FAIL)',
        'K1088 (USO + OVX)',
    ],
    'cross_asset_context': (
        'Paper 9 5th asset class. With Equity (PASS), Gold (PASS), Oil (PASS), '
        'Bonds (FAIL), this experiment asks whether asset-matched IV principle '
        'holds for crypto — a 24/7 post-2008 asset class without macro-cycle '
        'history and with regulatory/adoption shocks.'
    ),
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")
