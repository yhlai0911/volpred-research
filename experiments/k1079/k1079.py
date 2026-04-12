#!/usr/bin/env python3
"""
K1079: Matched-IV Hypothesis — VXN vs VIX for QQQ A4f
======================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation:
  K1078 showed QQQ with VIX² as A4f exogenous driver: DM t=+5.99 Harvey-PASS.
  However, QQQ tracks Nasdaq-100, while VIX is S&P 500 IV. CBOE also publishes
  VXN = Nasdaq-100 IV. Matched-IV Hypothesis:

    If VXN is "more matched" to QQQ than VIX, VXN² should produce stronger
    or more stable A4f improvement.

  Counter-hypothesis:
    QQQ and SPY correlate ~0.90+. VIX and VXN are highly correlated
    (possibly >0.95). The marginal gain from switching may be negligible.

Design (4 A4f specifications on QQQ, strict parity with K1078):
  - A4f-VIX    : τ = θ₀ + θ₁·VIX²_{t-1}         (K1078 baseline)
  - A4f-VXN    : τ = θ₀ + θ₁·VXN²_{t-1}         (matched IV)
  - A4f-COMBO  : τ = θ₀ + θ₁·VIX² + θ₂·VXN²     (joint)
  - A4f-SPREAD : τ = θ₀ + θ₁·(VXN² - VIX²)      (tech risk premium)

  Rolling window: W=2000, refit every 63d
  OOS: 3 non-overlapping windows aligned with K1078
    Early_Crisis    2007-01-01 ~ 2012-12-31
    Middle_Recovery 2013-01-01 ~ 2018-12-31
    Late_COVID      2019-01-01 ~ 2026-04-11

Hypotheses:
  H1: A4f-VXN vs A4f-VIX DM t > 1.96 (VXN empirically beats VIX on QQQ)
  H2: θ₁(VXN) CV < θ₁(VIX) CV  (VXN produces more stable loading)
  H3: A4f-COMBO vs A4f-VIX and A4f-VXN DM t > 1.96 (joint > single)
  H4: Regime-contingent advantage (dot-com residual, GFC, tech rally, 2022)

Data: yfinance QQQ + ^VIX + ^VXN  (1999-01-01 ~ 2026-04-12)
Evaluation: QLIKE on r² (Patton 2011), DM test (Harvey 2016 |t|>3 threshold)

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t>3.0 threshold.
  - Whaley (2009). Understanding the VIX. JPM.

Upstream experiments:
  - K988  SPY A4f baseline
  - K1073 VIX vs VIX9D/VIX3M/VVIX on SPY (VIX wins)
  - K1075 SPY extended 2007-2026 DM t=+7.92
  - K1077 0050.TW extended 2010-2025 DM t=-0.49 NS
  - K1078 QQQ + VIX² (direct upstream, DM t=+5.99)

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1079
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
EXPERIMENT_ID = "K1079"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1079_results.json')

# Config
DATA_START = '1999-01-01'
DATA_END = '2026-04-12'
WINDOW = 2000
REFIT_EVERY = 63

OOS_WINDOWS = [
    ('Early_Crisis', '2007-01-01', '2012-12-31'),
    ('Middle_Recovery', '2013-01-01', '2018-12-31'),
    ('Late_COVID', '2019-01-01', '2026-04-11'),
]

CRISIS_PERIODS = [
    ('GFC', '2008-01-01', '2009-12-31'),
    ('Euro_Crisis', '2011-06-01', '2012-06-30'),
    ('COVID_Crash', '2020-02-01', '2020-06-30'),
    ('Bear_2022', '2022-01-01', '2022-12-31'),
]

VIX_BUCKETS = [
    ('Low', 0, 15),
    ('Normal', 15, 25),
    ('High', 25, 40),
    ('Extreme', 40, 60),
    ('Crisis', 60, 200),
]

print("=" * 70)
print(f"{EXPERIMENT_ID}: VXN vs VIX Matched-IV Hypothesis for QQQ A4f")
print(f"  4 specifications: VIX, VXN, COMBO, SPREAD")
print(f"  3 OOS windows, 4 crisis sub-periods, 5 VIX buckets")
print(f"  Strict parity with K1078 (QQQ VIX² baseline)")
print("=" * 70)

# ============================================================
# SECTION 1: DATA
# ============================================================
print("\n[1] Loading QQQ + ^VIX + ^VXN from yfinance...")
import yfinance as yf

raw = yf.download('QQQ', start=DATA_START, end=DATA_END,
                  progress=False, auto_adjust=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Adj Close'].copy() if 'Adj Close' in raw.columns else raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

vxn_raw = yf.download('^VXN', start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=False)
if isinstance(vxn_raw.columns, pd.MultiIndex):
    vxn_raw.columns = vxn_raw.columns.get_level_values(0)
vxn_close = vxn_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret,
                   'VIX': vix_close, 'VXN': vxn_close})
df = df.dropna()

n_total = len(df)
print(f"  Joined: {df.index[0].strftime('%Y-%m-%d')} ~ "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
vxn = df['VXN'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 2: DIAGNOSTICS & VIX-VXN RELATIONSHIP
# ============================================================
print("\n[2] Diagnostics + VIX/VXN relationship...")
corr_vix_vxn = float(np.corrcoef(vix, vxn)[0, 1])
spread_vxn_vix = vxn - vix
print(f"  corr(VIX, VXN) = {corr_vix_vxn:.4f}")
print(f"  VIX  mean={np.mean(vix):.2f}, max={np.max(vix):.2f} on "
      f"{dates[np.argmax(vix)].strftime('%Y-%m-%d')}")
print(f"  VXN  mean={np.mean(vxn):.2f}, max={np.max(vxn):.2f} on "
      f"{dates[np.argmax(vxn)].strftime('%Y-%m-%d')}")
print(f"  VXN - VIX mean={np.mean(spread_vxn_vix):+.2f}, "
      f"std={np.std(spread_vxn_vix):.2f}, max spread="
      f"{np.max(np.abs(spread_vxn_vix)):.2f}")
print(f"  VXN > VIX pct: {100*np.mean(vxn > vix):.1f}%")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations (A4f with 4 exog specifications)...")


@njit(cache=True)
def gjr_loglik(params, returns):
    """Standard GJR-GARCH(1,1) log-likelihood."""
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


# --- A4f with flexible exogenous specification ---
# spec_type: 'vix' | 'vxn' | 'combo' | 'spread'
# - vix:    tau = theta0 + theta1 * vix_lag^2
# - vxn:    tau = theta0 + theta1 * vxn_lag^2
# - combo:  tau = theta0 + theta1 * vix_lag^2 + theta2 * vxn_lag^2
# - spread: tau = theta0 + theta1 * (vxn_lag^2 - vix_lag^2)

def build_tau_series(spec_type, params, vix_lag, vxn_lag):
    if spec_type == 'vix':
        return np.maximum(params[0] + params[1] * vix_lag**2, 1e-16)
    elif spec_type == 'vxn':
        return np.maximum(params[0] + params[1] * vxn_lag**2, 1e-16)
    elif spec_type == 'combo':
        return np.maximum(params[0] + params[1] * vix_lag**2
                          + params[2] * vxn_lag**2, 1e-16)
    elif spec_type == 'spread':
        return np.maximum(params[0] + params[1] * (vxn_lag**2 - vix_lag**2), 1e-16)
    else:
        raise ValueError(f"Unknown spec_type: {spec_type}")


def tau_1step(spec_type, params, vix_lag_val, vxn_lag_val):
    if spec_type == 'vix':
        return max(params[0] + params[1] * vix_lag_val**2, 1e-16)
    elif spec_type == 'vxn':
        return max(params[0] + params[1] * vxn_lag_val**2, 1e-16)
    elif spec_type == 'combo':
        return max(params[0] + params[1] * vix_lag_val**2
                   + params[2] * vxn_lag_val**2, 1e-16)
    elif spec_type == 'spread':
        return max(params[0] + params[1] * (vxn_lag_val**2 - vix_lag_val**2), 1e-16)
    else:
        raise ValueError(f"Unknown spec_type: {spec_type}")


def fit_a4f(returns, vix_vals, vxn_vals, spec_type):
    """
    A4f multiplicative GARCH-X with flexible exog:
      tau_t = build_tau_series(...)
      u_{t-1} = r_{t-1} / sqrt(tau_t)
      g_t = omega_g + alpha * u^2 + gamma * u^2 * I(u<0) + beta * g_{t-1}
      sigma^2_t = tau_t * g_t

    Parameter layout by spec_type:
      vix/vxn: [theta0, theta1, omega_g, alpha, gamma, beta]           (n=6)
      combo  : [theta0, theta1, theta2, omega_g, alpha, gamma, beta]   (n=7)
      spread : [theta0, theta1, omega_g, alpha, gamma, beta]           (n=6)
    """
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vxn_lag = np.empty(n)
    vxn_lag[0] = vxn_vals[0]
    vxn_lag[1:] = vxn_vals[:-1]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8
    vxn2_mean = np.mean(vxn_lag**2) + 1e-8

    if spec_type == 'vix':
        param_idx_g = slice(2, 6)
        param_idx_tau = slice(0, 2)
        n_params = 6
        bounds = [
            (-1e-2, 1e-2),    # theta0
            (1e-10, 1e-2),    # theta1 (positive)
            (1e-6, 1.0),      # omega_g
            (1e-4, 0.3),      # alpha
            (1e-4, 0.3),      # gamma
            (0.5, 0.999),     # beta
        ]
        starts = [
            [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        ]
    elif spec_type == 'vxn':
        param_idx_g = slice(2, 6)
        param_idx_tau = slice(0, 2)
        n_params = 6
        bounds = [
            (-1e-2, 1e-2),
            (1e-10, 1e-2),
            (1e-6, 1.0),
            (1e-4, 0.3),
            (1e-4, 0.3),
            (0.5, 0.999),
        ]
        starts = [
            [var0 * 0.1, var0 / vxn2_mean, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vxn2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vxn2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        ]
    elif spec_type == 'combo':
        param_idx_g = slice(3, 7)
        param_idx_tau = slice(0, 3)
        n_params = 7
        # theta1, theta2 unconstrained-sign within small bounds
        bounds = [
            (-1e-2, 1e-2),    # theta0
            (-1e-2, 1e-2),    # theta1 VIX (allow negative for collinearity)
            (-1e-2, 1e-2),    # theta2 VXN
            (1e-6, 1.0),
            (1e-4, 0.3),
            (1e-4, 0.3),
            (0.5, 0.999),
        ]
        starts = [
            [var0 * 0.1, var0 / vix2_mean * 0.5, var0 / vxn2_mean * 0.5,
             0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, var0 / vix2_mean * 0.3, var0 / vxn2_mean * 0.7,
             0.10, 0.03, 0.08, 0.88],
            [var0 * 0.2, var0 / vix2_mean * 0.7, var0 / vxn2_mean * 0.3,
             0.02, 0.08, 0.10, 0.80],
        ]
    elif spec_type == 'spread':
        param_idx_g = slice(2, 6)
        param_idx_tau = slice(0, 2)
        n_params = 6
        # theta1 unconstrained sign (spread can add or subtract from theta0 baseline)
        bounds = [
            (1e-6, 1.0),      # theta0 positive anchor
            (-1e-3, 1e-3),    # theta1 spread loading
            (1e-6, 1.0),
            (1e-4, 0.3),
            (1e-4, 0.3),
            (0.5, 0.999),
        ]
        starts = [
            [var0 * 0.5, 0.0, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.3, 1e-5, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.7, -1e-5, 0.02, 0.08, 0.10, 0.80],
        ]
    else:
        raise ValueError(f"Unknown spec: {spec_type}")

    def neg_loglik(params):
        if spec_type == 'vix':
            theta_params = params[0:2]
            omega_g, alpha, gamma_p, beta = params[2:6]
        elif spec_type == 'vxn':
            theta_params = params[0:2]
            omega_g, alpha, gamma_p, beta = params[2:6]
        elif spec_type == 'combo':
            theta_params = params[0:3]
            omega_g, alpha, gamma_p, beta = params[3:7]
        else:  # spread
            theta_params = params[0:2]
            omega_g, alpha, gamma_p, beta = params[2:6]

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau = build_tau_series(spec_type, theta_params, vix_lag, vxn_lag)

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
# SECTION 4: OOS FORECASTING
# ============================================================
print("\n[4] OOS forecasting (4 models x union of 3 windows)...")

oos_full_mask = np.zeros(n_total, dtype=bool)
window_tags = np.empty(n_total, dtype=object)
for name, start, end in OOS_WINDOWS:
    m = (dates >= start) & (dates <= end)
    oos_full_mask |= m
    for idx in np.where(m)[0]:
        window_tags[idx] = name

oos_indices = np.where(oos_full_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  Total OOS obs (union): {n_oos_actual}")

for name, start, end in OOS_WINDOWS:
    s_arr = np.where(dates >= start)[0]
    if len(s_arr) > 0:
        si = s_arr[0]
        print(f"    {name}: start_idx={si}, training={min(si, WINDOW)}")

# Containers
spec_types = ['vix', 'vxn', 'combo', 'spread']
forecasts = {s: np.full(n_oos_actual, np.nan) for s in spec_types}
gjr_forecasts = np.full(n_oos_actual, np.nan)
refit_log = []

# State
state = {s: {'g': None, 'params': None} for s in spec_types}
gjr_state = {'h': None, 'params': None}

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
        train_vxn = vxn[train_start:abs_idx]

        refit_entry = {
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
        }

        # GJR
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_state['params'] = gjr_p
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_p, h, train_ret[i-1])
            gjr_state['h'] = h
        refit_entry['gjr_conv'] = bool(gjr_conv)

        # A4f 4 specs
        for spec in spec_types:
            p, conv = fit_a4f(train_ret, train_vix, train_vxn, spec)
            if p is not None:
                state[spec]['params'] = p
                # recurse g through training
                vix_lag_tr = np.empty(len(train_vix))
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                vxn_lag_tr = np.empty(len(train_vxn))
                vxn_lag_tr[0] = train_vxn[0]
                vxn_lag_tr[1:] = train_vxn[:-1]

                if spec == 'combo':
                    theta_params = p[0:3]
                    omega_g, alpha_p, gamma_p, beta_p = p[3:7]
                else:
                    theta_params = p[0:2]
                    omega_g, alpha_p, gamma_p, beta_p = p[2:6]

                tau_tr = build_tau_series(spec, theta_params, vix_lag_tr, vxn_lag_tr)
                persist = alpha_p + gamma_p / 2.0 + beta_p
                g = omega_g / (1.0 - persist)
                for i in range(1, len(train_ret)):
                    u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                    g = max(g, 1e-10)
                state[spec]['g'] = g

            refit_entry[f'{spec}_conv'] = bool(conv)
            if p is not None:
                if spec == 'combo':
                    refit_entry[f'{spec}_theta0'] = float(p[0])
                    refit_entry[f'{spec}_theta1_vix'] = float(p[1])
                    refit_entry[f'{spec}_theta2_vxn'] = float(p[2])
                    refit_entry[f'{spec}_persist'] = float(p[3] + p[4]/2 + p[5])
                else:
                    refit_entry[f'{spec}_theta0'] = float(p[0])
                    refit_entry[f'{spec}_theta1'] = float(p[1])
                    refit_entry[f'{spec}_persist'] = float(p[2] + p[3]/2 + p[4])
            else:
                if spec == 'combo':
                    refit_entry[f'{spec}_theta0'] = None
                    refit_entry[f'{spec}_theta1_vix'] = None
                    refit_entry[f'{spec}_theta2_vxn'] = None
                else:
                    refit_entry[f'{spec}_theta0'] = None
                    refit_entry[f'{spec}_theta1'] = None

        refit_log.append(refit_entry)

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # Forecast for abs_idx
    r_prev = ret[abs_idx - 1]
    v_lag = vix[abs_idx - 1]
    n_lag = vxn[abs_idx - 1]

    # GJR
    if gjr_state['params'] is not None:
        h_new = gjr_forecast_1step(gjr_state['params'], gjr_state['h'], r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_state['h'] = h_new

    # A4f specs
    for spec in spec_types:
        p = state[spec]['params']
        g_prev = state[spec]['g']
        if p is None or g_prev is None:
            continue
        if spec == 'combo':
            theta_params = p[0:3]
            omega_g, alpha_p, gamma_p, beta_p = p[3:7]
        else:
            theta_params = p[0:2]
            omega_g, alpha_p, gamma_p, beta_p = p[2:6]

        tau_t = tau_1step(spec, theta_params, v_lag, n_lag)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)
        forecasts[spec][t_idx] = tau_t * g_new
        state[spec]['g'] = g_new

    prev_window = current_window

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits total")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_r2 = r2[oos_indices]
oos_dates = dates[oos_indices]
oos_vix = vix[oos_indices]
oos_vxn = vxn[oos_indices]
oos_window_tags = np.array([window_tags[i] for i in oos_indices])

# Joint valid mask across all 5 forecast series (4 A4f + GJR)
valid_joint = ~np.isnan(gjr_forecasts) & (gjr_forecasts > 0)
for s in spec_types:
    valid_joint &= ~np.isnan(forecasts[s]) & (forecasts[s] > 0)

n_both = int(valid_joint.sum())
print(f"  Joint valid obs (5 series): {n_both}/{n_oos_actual}")


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
    block_len = max(1, int(n**(1/3)))
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        if not blocks:
            return (np.nan, np.nan)
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


results = {
    'metadata': {},
    'vix_vxn_relationship': {
        'correlation': corr_vix_vxn,
        'vxn_vix_spread_mean': float(np.mean(spread_vxn_vix)),
        'vxn_vix_spread_std': float(np.std(spread_vxn_vix)),
        'pct_vxn_gt_vix': float(100 * np.mean(vxn > vix)),
    },
    'full_oos': {},
    'per_window': {},
    'crisis_subperiods': {},
    'vix_buckets': {},
    'pairwise_dm': {},
    'theta_stability': {},
    'refit_log': refit_log,
}

# --- Per-model full-OOS QLIKE ---
r2_v = oos_r2[valid_joint]
fc_gjr = gjr_forecasts[valid_joint]
fc_specs = {s: forecasts[s][valid_joint] for s in spec_types}

ql_gjr = float(np.mean(qlike_loss(fc_gjr, r2_v)))
ql_specs = {s: float(np.mean(qlike_loss(fc_specs[s], r2_v))) for s in spec_types}
rho_gjr = float(stats.spearmanr(fc_gjr, r2_v)[0])
rho_specs = {s: float(stats.spearmanr(fc_specs[s], r2_v)[0]) for s in spec_types}

print(f"\n  Full OOS (n={n_both}):")
print(f"    GJR           QLIKE={ql_gjr:.6f}")
for s in spec_types:
    diff_pct = (ql_specs[s] - ql_gjr) / abs(ql_gjr) * 100
    print(f"    A4f-{s.upper():<6} QLIKE={ql_specs[s]:.6f} ({diff_pct:+.3f}% vs GJR)")

results['full_oos']['n'] = n_both
results['full_oos']['qlike_gjr'] = ql_gjr
results['full_oos']['qlike'] = ql_specs
results['full_oos']['qlike_diff_pct_vs_gjr'] = {
    s: (ql_specs[s] - ql_gjr) / abs(ql_gjr) * 100 for s in spec_types
}
results['full_oos']['spearman_gjr'] = rho_gjr
results['full_oos']['spearman'] = rho_specs

# --- Pairwise DM tests on full OOS ---
print("\n  Pairwise DM tests (full OOS):")
print(f"  {'Pair (A vs B, positive=A better)':<40} {'DM t':>8} {'p':>10} {'CI95 lo':>10} {'CI95 hi':>10}")

all_models = {'gjr': fc_gjr, **fc_specs}
pair_list = [
    ('vix', 'gjr'),
    ('vxn', 'gjr'),
    ('combo', 'gjr'),
    ('spread', 'gjr'),
    ('vxn', 'vix'),       # H1 primary: matched IV
    ('combo', 'vix'),     # H3
    ('combo', 'vxn'),     # H3
    ('vxn', 'spread'),
    ('vix', 'spread'),
]

pairwise = {}
for a_name, b_name in pair_list:
    fc_a = all_models[a_name]
    fc_b = all_models[b_name]
    d = qlike_loss(fc_b, r2_v) - qlike_loss(fc_a, r2_v)  # positive => A better
    dm_t, dm_p, T = hac_dm_test(d)
    ci = bootstrap_ci_mean_diff(d, n_boot=1000)
    key = f"{a_name}_vs_{b_name}"
    pairwise[key] = {
        'dm_t': dm_t,
        'dm_p': dm_p,
        'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
        'bootstrap_ci_95': list(ci),
        'n': int(T),
    }
    print(f"  {f'A4f-{a_name.upper()} vs A4f/GJR-{b_name.upper()}':<40} "
          f"{dm_t:>+8.3f} {dm_p:>10.4f} {ci[0]:>+10.5f} {ci[1]:>+10.5f}")

results['pairwise_dm'] = pairwise

# --- Per OOS window: primary VXN vs VIX DM ---
print("\n  Per-window pairwise (VXN vs VIX, VXN vs GJR):")
print(f"  {'Window':<20} {'n':>6} {'QL_VIX':>10} {'QL_VXN':>10} {'VXN-VIX Diff%':>15} {'DM(VXN-VIX)':>14}")

for name, start, end in OOS_WINDOWS:
    mask = (oos_window_tags == name) & valid_joint
    n_w = int(mask.sum())
    if n_w < 30:
        continue
    r2_w = oos_r2[mask]
    fc_v = forecasts['vix'][mask]
    fc_x = forecasts['vxn'][mask]
    fc_c = forecasts['combo'][mask]
    fc_s = forecasts['spread'][mask]
    fc_g = gjr_forecasts[mask]

    ql_v = float(np.mean(qlike_loss(fc_v, r2_w)))
    ql_x = float(np.mean(qlike_loss(fc_x, r2_w)))
    ql_c = float(np.mean(qlike_loss(fc_c, r2_w)))
    ql_s = float(np.mean(qlike_loss(fc_s, r2_w)))
    ql_g = float(np.mean(qlike_loss(fc_g, r2_w)))

    # Primary: VXN vs VIX
    d_xv = qlike_loss(fc_v, r2_w) - qlike_loss(fc_x, r2_w)
    dm_xv, p_xv, _ = hac_dm_test(d_xv)

    # VXN vs GJR
    d_xg = qlike_loss(fc_g, r2_w) - qlike_loss(fc_x, r2_w)
    dm_xg, p_xg, _ = hac_dm_test(d_xg)

    # VIX vs GJR
    d_vg = qlike_loss(fc_g, r2_w) - qlike_loss(fc_v, r2_w)
    dm_vg, p_vg, _ = hac_dm_test(d_vg)

    diff_xv_pct = (ql_x - ql_v) / abs(ql_v) * 100
    print(f"  {name:<20} {n_w:>6} {ql_v:>10.5f} {ql_x:>10.5f} "
          f"{diff_xv_pct:>+14.3f}% {dm_xv:>+14.3f}")

    results['per_window'][name] = {
        'start': start, 'end': end, 'n': n_w,
        'qlike_gjr': ql_g,
        'qlike_vix': ql_v,
        'qlike_vxn': ql_x,
        'qlike_combo': ql_c,
        'qlike_spread': ql_s,
        'dm_vxn_vs_vix': dm_xv,
        'p_vxn_vs_vix': p_xv,
        'dm_vxn_vs_gjr': dm_xg,
        'p_vxn_vs_gjr': p_xg,
        'dm_vix_vs_gjr': dm_vg,
        'p_vix_vs_gjr': p_vg,
        'qlike_diff_vxn_vs_vix_pct': diff_xv_pct,
    }

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods (VXN vs VIX):")
print(f"  {'Crisis':<15} {'n':>6} {'VIX mean':>10} {'VXN mean':>10} "
      f"{'QL_VIX':>10} {'QL_VXN':>10} {'DM(VXN-VIX)':>14}")

for cname, cstart, cend in CRISIS_PERIODS:
    c_mask = (oos_dates >= cstart) & (oos_dates <= cend) & valid_joint
    n_c = int(c_mask.sum())
    if n_c < 30:
        print(f"  {cname:<15} {n_c:>6}  insufficient")
        continue
    r2_c = oos_r2[c_mask]
    fc_v = forecasts['vix'][c_mask]
    fc_x = forecasts['vxn'][c_mask]
    fc_g = gjr_forecasts[c_mask]
    vix_c = oos_vix[c_mask]
    vxn_c = oos_vxn[c_mask]

    ql_v = float(np.mean(qlike_loss(fc_v, r2_c)))
    ql_x = float(np.mean(qlike_loss(fc_x, r2_c)))
    ql_g = float(np.mean(qlike_loss(fc_g, r2_c)))

    d_xv = qlike_loss(fc_v, r2_c) - qlike_loss(fc_x, r2_c)
    dm_xv, p_xv, _ = hac_dm_test(d_xv)
    d_xg = qlike_loss(fc_g, r2_c) - qlike_loss(fc_x, r2_c)
    dm_xg, p_xg, _ = hac_dm_test(d_xg)
    d_vg = qlike_loss(fc_g, r2_c) - qlike_loss(fc_v, r2_c)
    dm_vg, p_vg, _ = hac_dm_test(d_vg)

    print(f"  {cname:<15} {n_c:>6} {np.mean(vix_c):>10.2f} {np.mean(vxn_c):>10.2f} "
          f"{ql_v:>10.5f} {ql_x:>10.5f} {dm_xv:>+14.3f}")

    results['crisis_subperiods'][cname] = {
        'start': cstart, 'end': cend, 'n': n_c,
        'vix_mean': float(np.mean(vix_c)),
        'vxn_mean': float(np.mean(vxn_c)),
        'qlike_gjr': ql_g,
        'qlike_vix': ql_v,
        'qlike_vxn': ql_x,
        'dm_vxn_vs_vix': dm_xv, 'p_vxn_vs_vix': p_xv,
        'dm_vxn_vs_gjr': dm_xg, 'p_vxn_vs_gjr': p_xg,
        'dm_vix_vs_gjr': dm_vg, 'p_vix_vs_gjr': p_vg,
        'qlike_diff_vxn_vs_vix_pct': (ql_x - ql_v) / abs(ql_v) * 100,
    }

# --- VIX buckets (using VIX for bucketing, consistent with K1078) ---
print("\n  VIX bucket analysis (VXN vs VIX):")
print(f"  {'Bucket':<12} {'Range':<12} {'n':>6} {'QL_VIX':>10} {'QL_VXN':>10} {'Diff%':>10} {'DM':>10}")

oos_vix_lag = np.empty(n_oos_actual)
for i, idx in enumerate(oos_indices):
    oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]

for bname, bmin, bmax in VIX_BUCKETS:
    mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax) & valid_joint
    n_b = int(mask.sum())
    if n_b < 20:
        print(f"  {bname:<12} [{bmin},{bmax})  insufficient (n={n_b})")
        results['vix_buckets'][bname] = {'status': 'insufficient', 'n': n_b,
                                         'range': [bmin, bmax]}
        continue
    r2_b = oos_r2[mask]
    fc_v = forecasts['vix'][mask]
    fc_x = forecasts['vxn'][mask]
    fc_g = gjr_forecasts[mask]

    ql_v = float(np.mean(qlike_loss(fc_v, r2_b)))
    ql_x = float(np.mean(qlike_loss(fc_x, r2_b)))
    ql_g = float(np.mean(qlike_loss(fc_g, r2_b)))

    d_xv = qlike_loss(fc_v, r2_b) - qlike_loss(fc_x, r2_b)
    dm_xv, p_xv, _ = hac_dm_test(d_xv)

    diff = (ql_x - ql_v) / abs(ql_v) * 100
    print(f"  {bname:<12} [{bmin},{bmax})    {n_b:>6} {ql_v:>10.5f} "
          f"{ql_x:>10.5f} {diff:>+10.3f}% {dm_xv:>+10.3f}")

    results['vix_buckets'][bname] = {
        'range': [bmin, bmax], 'n': n_b,
        'qlike_vix': ql_v, 'qlike_vxn': ql_x, 'qlike_gjr': ql_g,
        'dm_vxn_vs_vix': dm_xv, 'p_vxn_vs_vix': p_xv,
        'diff_pct_vxn_vs_vix': diff,
    }

# --- theta stability comparison ---
print("\n  theta1 stability (VXN vs VIX):")

for spec in ['vix', 'vxn']:
    valid_theta1 = [r[f'{spec}_theta1'] for r in refit_log
                    if r.get(f'{spec}_theta1') is not None and r.get(f'{spec}_conv')]
    if valid_theta1:
        t1 = np.array(valid_theta1)
        stats_d = {
            'n_refits': len(t1),
            'median': float(np.median(t1)),
            'mean': float(np.mean(t1)),
            'std': float(np.std(t1)),
            'min': float(np.min(t1)),
            'max': float(np.max(t1)),
            'cv': float(np.std(t1) / (np.mean(t1) + 1e-30)),
            'orders_of_magnitude_span': float(np.log10(np.max(t1) / max(np.min(t1), 1e-30))),
        }
        results['theta_stability'][spec] = stats_d
        print(f"    {spec.upper()}  median={stats_d['median']:.3e}  "
              f"range=[{stats_d['min']:.3e}, {stats_d['max']:.3e}]  "
              f"CV={stats_d['cv']:.3f}  span={stats_d['orders_of_magnitude_span']:.2f}")

# Combo collinearity diagnostic
combo_theta1_vix = [r.get('combo_theta1_vix') for r in refit_log
                    if r.get('combo_conv')]
combo_theta2_vxn = [r.get('combo_theta2_vxn') for r in refit_log
                    if r.get('combo_conv')]
combo_theta1_vix = [x for x in combo_theta1_vix if x is not None]
combo_theta2_vxn = [x for x in combo_theta2_vxn if x is not None]
if combo_theta1_vix and combo_theta2_vxn:
    results['theta_stability']['combo'] = {
        'theta1_vix_mean': float(np.mean(combo_theta1_vix)),
        'theta1_vix_std': float(np.std(combo_theta1_vix)),
        'theta2_vxn_mean': float(np.mean(combo_theta2_vxn)),
        'theta2_vxn_std': float(np.std(combo_theta2_vxn)),
        'pct_theta1_vix_negative': float(100 * np.mean(np.array(combo_theta1_vix) < 0)),
        'pct_theta2_vxn_negative': float(100 * np.mean(np.array(combo_theta2_vxn) < 0)),
    }
    print(f"    COMBO  mean theta1(VIX)={np.mean(combo_theta1_vix):+.3e}  "
          f"pct_negative={100 * np.mean(np.array(combo_theta1_vix) < 0):.1f}%")
    print(f"    COMBO  mean theta2(VXN)={np.mean(combo_theta2_vxn):+.3e}  "
          f"pct_negative={100 * np.mean(np.array(combo_theta2_vxn) < 0):.1f}%")

# ============================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)

# H1: A4f-VXN vs A4f-VIX full-OOS DM t > 1.96
dm_xv_full = pairwise['vxn_vs_vix']['dm_t']
h1_primary = 'PASS' if (np.isfinite(dm_xv_full) and dm_xv_full > 3.0) else (
    'WEAK PASS' if dm_xv_full > 1.96 else 'FAIL')
print(f"  H1 (VXN beats VIX, Harvey |t|>3): {h1_primary} "
      f"(DM t={dm_xv_full:+.3f})")

# H2: theta1 stability CV(VXN) < CV(VIX)
cv_vix = results['theta_stability'].get('vix', {}).get('cv')
cv_vxn = results['theta_stability'].get('vxn', {}).get('cv')
if cv_vix is not None and cv_vxn is not None:
    h2 = 'PASS' if cv_vxn < cv_vix else 'FAIL'
    print(f"  H2 (CV(VXN) < CV(VIX)): {h2} (CV_VIX={cv_vix:.3f}, CV_VXN={cv_vxn:.3f})")
else:
    h2 = 'N/A'
    print("  H2: N/A")

# H3: COMBO beats each single
dm_cv = pairwise['combo_vs_vix']['dm_t']
dm_cx = pairwise['combo_vs_vxn']['dm_t']
h3_cv = 'PASS' if np.isfinite(dm_cv) and dm_cv > 1.96 else 'FAIL'
h3_cx = 'PASS' if np.isfinite(dm_cx) and dm_cx > 1.96 else 'FAIL'
h3 = ('PASS' if h3_cv == 'PASS' and h3_cx == 'PASS'
      else 'PARTIAL' if (h3_cv == 'PASS' or h3_cx == 'PASS') else 'FAIL')
print(f"  H3 (COMBO > single): {h3}  "
      f"(COMBO vs VIX DM={dm_cv:+.3f}, COMBO vs VXN DM={dm_cx:+.3f})")

# H4: Regime-contingent — per-window VXN vs VIX
win_dms_xv = [results['per_window'][n].get('dm_vxn_vs_vix')
              for n in results['per_window']]
win_dms_xv = [x for x in win_dms_xv if x is not None and np.isfinite(x)]
win_wins = sum(1 for x in win_dms_xv if x > 0)
h4 = ('CONSISTENT' if win_wins == len(win_dms_xv) and len(win_dms_xv) == 3
      else 'PARTIAL' if win_wins >= 2
      else 'INCONSISTENT')
print(f"  H4 (directional consistency VXN vs VIX across windows): "
      f"{h4} ({win_wins}/{len(win_dms_xv)} windows VXN>VIX directionally)")

results['hypothesis_verdicts'] = {
    'H1_vxn_beats_vix_harvey': h1_primary,
    'H1_dm_t': dm_xv_full,
    'H2_cv_vxn_less_than_vix': h2,
    'H2_cv_vix': cv_vix, 'H2_cv_vxn': cv_vxn,
    'H3_combo_beats_single': h3,
    'H3_combo_vs_vix_dm': dm_cv,
    'H3_combo_vs_vxn_dm': dm_cx,
    'H4_regime_consistency': h4,
    'H4_wins': win_wins,
    'H4_total': len(win_dms_xv),
}

# ============================================================
# SECTION 7: METADATA + SAVE
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'QQQ',
    'exog_variables': ['VIX (^VIX)', 'VXN (^VXN)'],
    'data_source': 'yfinance',
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
    'specifications': [
        'A4f-VIX:    tau = theta0 + theta1 * VIX_lag^2',
        'A4f-VXN:    tau = theta0 + theta1 * VXN_lag^2',
        'A4f-COMBO:  tau = theta0 + theta1 * VIX_lag^2 + theta2 * VXN_lag^2',
        'A4f-SPREAD: tau = theta0 + theta1 * (VXN_lag^2 - VIX_lag^2)',
    ],
    'random_seed': 42,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (matched-IV hypothesis)',
    'executor': 'Claude',
    'references': [
        'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). Testing equality of MSE. t>3 threshold.',
        'Whaley (2009). Understanding the VIX. JPM.',
    ],
    'upstream_experiments': [
        'K988 SPY A4f baseline',
        'K1073 VIX vs VIX9D/VIX3M/VVIX on SPY (VIX wins)',
        'K1075 SPY extended 2007-2026 DM t=+7.92',
        'K1077 0050.TW extended 2010-2025 DM t=-0.49 NS',
        'K1078 QQQ + VIX² extended DM t=+5.99 (direct upstream)',
    ],
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

    # ----- Plot 1: DM matrix (4 A4f models + GJR) -----
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    ax = axes[0]
    models_for_matrix = ['gjr', 'vix', 'vxn', 'combo', 'spread']
    model_labels = ['GJR', 'A4f-VIX', 'A4f-VXN', 'A4f-COMBO', 'A4f-SPREAD']
    M = len(models_for_matrix)
    mat = np.full((M, M), np.nan)
    for i, a in enumerate(models_for_matrix):
        for j, b in enumerate(models_for_matrix):
            if i == j:
                continue
            fc_a = all_models[a]
            fc_b = all_models[b]
            d = qlike_loss(fc_b, r2_v) - qlike_loss(fc_a, r2_v)
            dm_t, _, _ = hac_dm_test(d)
            mat[i, j] = dm_t if np.isfinite(dm_t) else np.nan

    vlim = max(abs(np.nanmin(mat)), abs(np.nanmax(mat)))
    im = ax.imshow(mat, cmap='RdYlGn', vmin=-vlim, vmax=vlim, aspect='auto')
    ax.set_xticks(range(M))
    ax.set_yticks(range(M))
    ax.set_xticklabels(model_labels, rotation=30, ha='right')
    ax.set_yticklabels(model_labels)
    ax.set_title(f'{EXPERIMENT_ID} QQQ: Pairwise DM t-stat Matrix\n'
                 '(row vs column, positive = row better)')
    for i in range(M):
        for j in range(M):
            if np.isfinite(mat[i, j]):
                txt_color = 'white' if abs(mat[i, j]) > vlim * 0.6 else 'black'
                ax.text(j, i, f'{mat[i, j]:+.2f}', ha='center', va='center',
                        fontsize=9, color=txt_color, fontweight='bold')
    plt.colorbar(im, ax=ax, label='DM t-stat')

    # ----- Sub-plot: QLIKE bar compare -----
    ax2 = axes[1]
    qlikes = [ql_gjr] + [ql_specs[s] for s in spec_types]
    colors_bar = ['gray', 'steelblue', 'coral', 'mediumseagreen', 'goldenrod']
    bars = ax2.bar(model_labels, qlikes, color=colors_bar, alpha=0.8)
    ax2.set_ylabel('QLIKE (lower = better)')
    ax2.set_title('Full OOS QLIKE by Model')
    ax2.grid(True, alpha=0.3)
    for bar, v in zip(bars, qlikes):
        ax2.text(bar.get_x() + bar.get_width()/2, v, f'{v:.5f}',
                 ha='center', va='bottom', fontsize=9)
    ax2.set_ylim([min(qlikes) * 1.0005, max(qlikes) * 1.0005 - (max(qlikes) - min(qlikes)) * 0.02])
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1079_dm_matrix.png'), dpi=120,
                bbox_inches='tight')
    plt.close()
    print("    k1079_dm_matrix.png")

    # ----- Plot 2: VIX vs VXN time-series + scatter -----
    fig, axes = plt.subplots(1, 2, figsize=(16, 5))
    ax = axes[0]
    ax.plot(dates, vix, color='steelblue', alpha=0.7, lw=0.6, label='VIX')
    ax.plot(dates, vxn, color='coral', alpha=0.7, lw=0.6, label='VXN')
    ax.set_ylabel('Index level')
    ax.set_title(f'VIX vs VXN {dates[0].year}-{dates[-1].year}\n'
                 f'corr={corr_vix_vxn:.4f}')
    ax.legend()
    ax.grid(True, alpha=0.3)
    for cname, cstart, cend in CRISIS_PERIODS:
        ax.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
                   alpha=0.1, color='red')

    ax = axes[1]
    ax.scatter(vix, vxn, alpha=0.3, s=4, color='purple')
    lim_max = max(np.max(vix), np.max(vxn)) * 1.05
    ax.plot([0, lim_max], [0, lim_max], 'k--', lw=0.7, alpha=0.6, label='y=x')
    ax.set_xlabel('VIX')
    ax.set_ylabel('VXN')
    ax.set_title(f'VIX vs VXN scatter (corr={corr_vix_vxn:.4f})\n'
                 f'VXN>VIX {100*np.mean(vxn>vix):.1f}% of days')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1079_vix_vs_vxn.png'), dpi=120,
                bbox_inches='tight')
    plt.close()
    print("    k1079_vix_vs_vxn.png")

    # ----- Plot 3: theta1 evolution VIX vs VXN -----
    fig, ax = plt.subplots(figsize=(14, 6))
    refit_dates_valid = [pd.to_datetime(r['date']) for r in refit_log]
    for spec, color in [('vix', 'steelblue'), ('vxn', 'coral')]:
        t1 = [r.get(f'{spec}_theta1') for r in refit_log]
        dates_plot = [d for d, v in zip(refit_dates_valid, t1) if v is not None]
        vals = [v for v in t1 if v is not None]
        ax.plot(dates_plot, vals, marker='o', markersize=4, alpha=0.75,
                color=color, label=f'theta1 ({spec.upper()}^2)')
    ax.set_xlabel('Refit date')
    ax.set_ylabel('theta1 (exog coefficient)')
    ax.set_yscale('log')
    ax.set_title(f'{EXPERIMENT_ID} QQQ: theta1(VIX) vs theta1(VXN) '
                 f'Evolution (78 refits, 2007-2026)')
    ax.grid(True, alpha=0.3, which='both')
    for cname, cstart, cend in CRISIS_PERIODS:
        ax.axvspan(pd.to_datetime(cstart), pd.to_datetime(cend),
                   alpha=0.15, color='red', label=cname if cname == 'GFC' else None)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1079_theta1_compare.png'), dpi=120,
                bbox_inches='tight')
    plt.close()
    print("    k1079_theta1_compare.png")

    # ----- Plot 4: Regime analysis (crisis sub-periods VXN vs VIX) -----
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    ax = axes[0]
    c_names = list(results['crisis_subperiods'].keys())
    c_diffs = [results['crisis_subperiods'][c].get('qlike_diff_vxn_vs_vix_pct')
               for c in c_names]
    c_dms = [results['crisis_subperiods'][c].get('dm_vxn_vs_vix')
             for c in c_names]
    c_valid = [i for i, (d, t) in enumerate(zip(c_diffs, c_dms))
               if d is not None and t is not None]
    c_names_v = [c_names[i] for i in c_valid]
    c_diffs_v = [c_diffs[i] for i in c_valid]
    c_dms_v = [c_dms[i] for i in c_valid]
    colors_c = ['green' if d < 0 else 'red' for d in c_diffs_v]
    ax.bar(c_names_v, c_diffs_v, color=colors_c, alpha=0.75)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_ylabel('QLIKE Diff % (VXN vs VIX, negative = VXN better)')
    ax.set_title(f'{EXPERIMENT_ID} QQQ: VXN vs VIX by Crisis')
    ax.grid(True, alpha=0.3)
    for i, (d, t) in enumerate(zip(c_diffs_v, c_dms_v)):
        ax.text(i, d + (0.05 if d >= 0 else -0.15),
                f't={t:+.2f}', ha='center', fontsize=9, fontweight='bold')

    ax = axes[1]
    # Per-window VXN vs VIX
    w_names = list(results['per_window'].keys())
    w_dms = [results['per_window'][w]['dm_vxn_vs_vix'] for w in w_names]
    colors_w = ['green' if t > 3.0 else ('orange' if t > 1.96 else
                'lightgray' if t > -1.96 else ('salmon' if t > -3.0 else 'red'))
                for t in w_dms]
    ax.bar(w_names, w_dms, color=colors_w, alpha=0.8)
    ax.axhline(3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3')
    ax.axhline(-3.0, color='red', linestyle='--', alpha=0.5)
    ax.axhline(1.96, color='gray', linestyle=':', alpha=0.3, label='|t|=1.96')
    ax.axhline(-1.96, color='gray', linestyle=':', alpha=0.3)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_ylabel('DM t-stat (VXN vs VIX)')
    ax.set_title('Per-Window DM: VXN vs VIX')
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis='x', rotation=10)
    for i, t in enumerate(w_dms):
        ax.text(i, t + (0.15 if t >= 0 else -0.35), f'{t:+.2f}',
                ha='center', fontsize=10, fontweight='bold')

    plt.suptitle(f'{EXPERIMENT_ID}: Regime Analysis — VXN vs VIX for QQQ A4f',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1079_regime_analysis.png'), dpi=120,
                bbox_inches='tight')
    plt.close()
    print("    k1079_regime_analysis.png")

except Exception as e:
    print(f"  Plot error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE in {time.time() - START_TIME:.0f}s")
print("=" * 70)
